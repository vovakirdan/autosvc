from __future__ import annotations

import json
import os
import socket
from typing import Any, Dict

from backend.protocol.handlers import handle_request
from backend.uds.client import UdsClient


class JsonlServer:
    def __init__(self, socket_path: str, uds_client: UdsClient) -> None:
        self._socket_path = socket_path
        self._uds_client = uds_client
        self._sock: socket.socket | None = None

    def serve_forever(self) -> None:
        if self._sock is None:
            self._start()
        while True:
            conn, _ = self._sock.accept()
            with conn:
                self._handle_client(conn)

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        if os.path.exists(self._socket_path):
            try:
                os.unlink(self._socket_path)
            except OSError:
                return None

    def _start(self) -> None:
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self._socket_path)
        self._sock.listen(1)

    def _handle_client(self, conn: socket.socket) -> None:
        fileobj = conn.makefile("rwb")
        with fileobj:
            while True:
                line = fileobj.readline()
                if not line:
                    break
                response = self._handle_line(line)
                fileobj.write(response)
                fileobj.flush()

    def _handle_line(self, line: bytes) -> bytes:
        try:
            text = line.decode("utf-8").strip()
            if not text:
                return self._encode({"ok": False, "error": "empty request"})
            request = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._encode({"ok": False, "error": "invalid json"})
        try:
            response = handle_request(request, self._uds_client)
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        return self._encode(response)

    def _encode(self, payload: Dict[str, Any]) -> bytes:
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
