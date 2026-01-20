from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional

from backend.transport.base import CanFrame, CanTransport


class ReplayError(Exception):
    pass


@dataclass(frozen=True)
class _Event:
    direction: str
    can_id: int
    data: bytes
    tick: int


class ReplayTransport(CanTransport):
    def __init__(self, path: str) -> None:
        self._events = self._load_events(path)
        self._index = 0

    def send(self, can_id: int, data: bytes) -> None:
        # Validate tx events against the recording for deterministic playback.
        event = self._next_event("send")
        if event.direction != "tx":
            raise ReplayError(
                f"unexpected send: next event is {event.direction} at t={event.tick}"
            )
        if event.can_id != can_id:
            raise ReplayError(
                f"send id mismatch: expected {event.can_id}, got {can_id}"
            )
        if event.data != data:
            raise ReplayError(
                "send data mismatch: "
                f"expected {event.data.hex()}, got {data.hex()}"
            )
        self._index += 1

    def recv(self, timeout_ms: int) -> Optional[CanFrame]:
        # Do not sleep; return the next recorded rx event or None.
        if self._index >= len(self._events):
            return None
        event = self._events[self._index]
        if event.direction != "rx":
            return None
        self._index += 1
        return CanFrame(can_id=event.can_id, data=event.data)

    def _next_event(self, action: str) -> _Event:
        if self._index >= len(self._events):
            raise ReplayError(f"unexpected {action}: no more events")
        return self._events[self._index]

    def _load_events(self, path: str) -> List[_Event]:
        events: List[_Event] = []
        last_tick = -1
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                tick = int(raw.get("t"))
                direction = raw.get("dir")
                can_id = int(raw.get("id"))
                data_hex = raw.get("data")
                if direction not in {"tx", "rx"}:
                    raise ReplayError(f"invalid direction at t={tick}")
                if not isinstance(data_hex, str):
                    raise ReplayError(f"invalid data at t={tick}")
                try:
                    data = bytes.fromhex(data_hex)
                except ValueError as exc:
                    raise ReplayError(f"invalid hex data at t={tick}") from exc
                if tick <= last_tick:
                    raise ReplayError("non-monotonic tick sequence")
                last_tick = tick
                events.append(_Event(direction=direction, can_id=can_id, data=data, tick=tick))
        return events
