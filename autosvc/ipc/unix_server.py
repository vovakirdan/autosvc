from __future__ import annotations

import os
import socket
import time
from typing import Any

from autosvc.core.service import DiagnosticService
from autosvc.core.live.watch import WatchItem, Watcher
from autosvc.core.uds.did import parse_did
from autosvc.ipc.protocol import decode_json_line, encode_json_line, error, handle_request


class JsonlUnixServer:
    def __init__(self, socket_path: str, service: DiagnosticService) -> None:
        self._socket_path = socket_path
        self._service = service
        self._sock: socket.socket | None = None

    def serve_forever(self) -> None:
        if self._sock is None:
            self._start()
        assert self._sock is not None
        while True:
            conn, _ = self._sock.accept()
            with conn:
                self._handle_client(conn)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
        if os.path.exists(self._socket_path):
            try:
                os.unlink(self._socket_path)
            except OSError:
                return None

    def _start(self) -> None:
        os.makedirs(os.path.dirname(self._socket_path) or ".", exist_ok=True)
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self._socket_path)
        self._sock.listen(8)

    def _handle_client(self, conn: socket.socket) -> None:
        # Use socket timeouts to allow watch streaming without threads.
        conn.settimeout(1.0)
        fileobj = conn.makefile("rwb")
        with fileobj:
            watcher: Watcher | None = None
            tick_ms = 200
            max_ticks: int | None = None
            tick = 0

            while True:
                if watcher is None:
                    conn.settimeout(None)
                    line = fileobj.readline()
                    if not line:
                        break
                    response, watcher, tick_ms, max_ticks = self._handle_line(line)
                    fileobj.write(response)
                    fileobj.flush()
                    tick = 0
                    continue

                # Watch streaming mode:
                tick += 1
                try:
                    events = watcher.tick(tick)
                except Exception as exc:
                    fileobj.write(encode_json_line(error(str(exc))))
                    fileobj.flush()
                    watcher = None
                    continue

                for evt in events:
                    try:
                        fileobj.write(encode_json_line(evt.to_dict()))
                        fileobj.flush()
                    except OSError:
                        return None

                if max_ticks is not None and tick >= max_ticks:
                    fileobj.write(encode_json_line({"ok": True, "done": True}))
                    fileobj.flush()
                    watcher = None
                    continue

                # Wait for watch_stop (or other commands) while respecting tick_ms.
                deadline = time.monotonic() + (max(0, int(tick_ms)) / 1000.0)
                while time.monotonic() < deadline:
                    remaining = max(0.0, deadline - time.monotonic())
                    conn.settimeout(min(0.1, remaining))
                    try:
                        line = fileobj.readline()
                    except socket.timeout:
                        continue
                    if not line:
                        return None
                    try:
                        req = decode_json_line(line)
                    except ValueError as exc:
                        fileobj.write(encode_json_line(error(str(exc))))
                        fileobj.flush()
                        continue
                    cmd = req.get("cmd")
                    if cmd == "watch_stop":
                        fileobj.write(encode_json_line({"ok": True, "stopped": True}))
                        fileobj.flush()
                        watcher = None
                        break
                    fileobj.write(encode_json_line(error("watch active; only watch_stop is accepted")))
                    fileobj.flush()

    def _handle_line(
        self, line: bytes
    ) -> tuple[bytes, Watcher | None, int, int | None]:
        try:
            request = decode_json_line(line)
        except ValueError as exc:
            return encode_json_line(error(str(exc))), None, 200, None

        if request.get("cmd") == "watch_start":
            try:
                watcher, tick_ms, max_ticks = self._start_watch(request)
            except Exception as exc:
                return encode_json_line(error(str(exc))), None, 200, None
            return encode_json_line({"ok": True, "watching": True}), watcher, tick_ms, max_ticks

        try:
            response = handle_request(request, self._service)
        except Exception as exc:
            response = error(str(exc))
        return encode_json_line(response), None, 200, None

    def _start_watch(self, request: dict[str, Any]) -> tuple[Watcher, int, int | None]:
        items_raw = request.get("items")
        if not isinstance(items_raw, list) or not items_raw:
            raise ValueError("items must be a non-empty list")
        items: list[WatchItem] = []
        for raw in items_raw:
            if not isinstance(raw, dict):
                raise ValueError("items must be objects")
            ecu = raw.get("ecu")
            did_raw = raw.get("did")
            if not isinstance(ecu, str):
                raise ValueError("ecu must be hex string")
            try:
                did_int = parse_did(did_raw)
            except Exception as exc:
                raise ValueError("did must be hex string") from exc
            items.append(WatchItem(ecu=ecu, did=did_int))
        emit = request.get("emit", "changed")
        if emit not in {"changed", "always"}:
            raise ValueError("emit must be changed|always")
        tick_ms = int(request.get("tick_ms", 200))
        max_ticks_raw = request.get("max_ticks")
        max_ticks = int(max_ticks_raw) if max_ticks_raw is not None else None
        watcher = Watcher(self._service, items=items, emit_mode=emit, tick_ms=tick_ms)
        return watcher, tick_ms, max_ticks
