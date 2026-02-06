from __future__ import annotations

import json
import socket
from typing import Any


class UnixJsonlClient:
    def __init__(self, socket_path: str, *, timeout_s: float = 2.0) -> None:
        self._socket_path = socket_path
        self._timeout_s = float(timeout_s)

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(self._timeout_s)
            sock.connect(self._socket_path)
            sock.sendall(data)
            fileobj = sock.makefile("rb")
            with fileobj:
                line = fileobj.readline()
        if not line:
            raise RuntimeError("no response")
        raw = json.loads(line.decode("utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError("invalid response")
        return raw

