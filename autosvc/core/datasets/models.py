from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AdaptKind = Literal["bool", "u8", "u16", "i16", "enum", "bytes"]
AdaptRisk = Literal["safe", "risky", "unsafe"]


@dataclass(frozen=True)
class DatasetManifest:
    brand: str
    version: str
    type: str
    notes: str | None = None


@dataclass(frozen=True)
class AdaptRwRef:
    service: str
    id: str


@dataclass(frozen=True)
class AdaptSettingSpec:
    key: str
    label: str
    kind: AdaptKind
    read: AdaptRwRef
    write: AdaptRwRef
    risk: AdaptRisk
    notes: str = ""
    enum: dict[str, str] | None = None


@dataclass(frozen=True)
class AdaptationsProfile:
    ecu: str
    ecu_name: str
    settings: list[AdaptSettingSpec]

