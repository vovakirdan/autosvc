from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveDidEvent:
    tick: int
    ecu: str
    did: str
    name: str
    value: str | int | float
    unit: str

    def to_dict(self) -> dict[str, object]:
        # Keep key order stable for golden snapshots and JSONL streaming.
        return {
            "event": "live_did",
            "tick": int(self.tick),
            "ecu": self.ecu,
            "did": self.did,
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
        }

