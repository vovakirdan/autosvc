from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from autosvc.core.live.events import LiveDidEvent
from autosvc.core.service import DiagnosticService
from autosvc.core.uds.did import parse_did


EmitMode = Literal["changed", "always"]


@dataclass(frozen=True)
class WatchItem:
    ecu: str
    did: int


class Watcher:
    def __init__(
        self,
        service: DiagnosticService,
        *,
        items: list[WatchItem],
        emit_mode: EmitMode = "changed",
        tick_ms: int = 200,
    ) -> None:
        self._service = service
        self._items = items
        self._emit_mode: EmitMode = emit_mode
        self._tick_ms = int(tick_ms)
        self._last: dict[tuple[str, str], object] = {}

    def tick(self, tick: int) -> list[LiveDidEvent]:
        events: list[LiveDidEvent] = []
        for item in self._items:
            did_int = parse_did(item.did)
            reading = self._service.read_did(item.ecu, did_int)
            evt = LiveDidEvent(
                tick=int(tick),
                ecu=str(reading.get("ecu", "")),
                did=str(reading.get("did", "")),
                name=str(reading.get("name", "")),
                value=reading.get("value", ""),
                unit=str(reading.get("unit", "")),
            )
            key = (evt.ecu, evt.did)
            prev = self._last.get(key)
            emit = self._emit_mode == "always" or prev is None or prev != evt.value
            self._last[key] = evt.value
            if emit:
                events.append(evt)
        return events

    def run_ticks(self, *, max_ticks: int, sleep: bool = False):
        for tick in range(1, int(max_ticks) + 1):
            for evt in self.tick(tick):
                yield evt
            if sleep and self._tick_ms > 0:
                time.sleep(self._tick_ms / 1000.0)
