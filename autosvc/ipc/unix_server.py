from __future__ import annotations

import os
import socket
from typing import Any

from autosvc.core.service import DiagnosticService
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
            request = decode_json_line(line)
        except ValueError as exc:
            return encode_json_line(error(str(exc)))
        try:
            response = handle_request(request, self._service)
        except Exception as exc:
            response = error(str(exc))
        return encode_json_line(response)

