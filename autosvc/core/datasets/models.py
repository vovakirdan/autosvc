from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AdaptKind = Literal["bool", "u8", "u16", "i16", "enum", "bytes"]
AdaptRisk = Literal["safe", "risky", "unsafe"]

LongCodingKind = Literal["bool", "u8", "enum"]
LongCodingRisk = Literal["safe", "risky", "unsafe"]


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
    needs_security_access: bool = False
    enum: dict[str, str] | None = None


@dataclass(frozen=True)
class AdaptationsProfile:
    ecu: str
    ecu_name: str
    settings: list[AdaptSettingSpec]


@dataclass(frozen=True)
class LongCodingFieldSpec:
    key: str
    label: str
    kind: LongCodingKind
    risk: LongCodingRisk
    byte: int
    bit: int
    length: int
    notes: str = ""
    enum: dict[str, str] | None = None
    did: int | None = None
    coding_length: int | None = None
    needs_security_access: bool = False


@dataclass(frozen=True)
class LongCodingProfile:
    ecu: str
    ecu_name: str
    did: int
    length: int
    fields: list[LongCodingFieldSpec]

