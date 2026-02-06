from __future__ import annotations

import json

from autosvc.core.transport.base import CanFrame, CanTransport


class RecordingTransport(CanTransport):
    def __init__(self, inner: CanTransport, path: str) -> None:
        self._inner = inner
        self._path = path
        self._tick = 0
        self._file = open(path, "w", encoding="utf-8")

    def send(self, can_id: int, data: bytes) -> None:
        self._inner.send(can_id, data)
        self._write_event("tx", can_id, data)

    def recv(self, timeout_ms: int) -> CanFrame | None:
        frame = self._inner.recv(timeout_ms)
        if frame is None:
            return None
        self._write_event("rx", frame.can_id, frame.data)
        return frame

    def close(self) -> None:
        try:
            self._inner.close()
        finally:
            self._file.close()

    def _write_event(self, direction: str, can_id: int, data: bytes) -> None:
        # Persist deterministic JSONL events for replay/golden fixtures.
        event = {
            "t": self._tick,
            "dir": direction,
            "id": can_id,
            "data": data.hex(),
        }
        self._tick += 1
        self._file.write(json.dumps(event, separators=(",", ":")) + "\n")
        self._file.flush()

