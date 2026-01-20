from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


_DTC_PREFIX = {0: "P", 1: "C", 2: "B", 3: "U"}
_DTC_PREFIX_REV = {v: k for k, v in _DTC_PREFIX.items()}


@dataclass(frozen=True)
class Dtc:
    code: str
    status: str

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "status": self.status}


def encode_dtc(code: str) -> int:
    if len(code) != 5:
        raise ValueError("invalid dtc format")
    prefix = code[0].upper()
    if prefix not in _DTC_PREFIX_REV:
        raise ValueError("invalid dtc prefix")
    digits = code[1:]
    try:
        first = int(digits[0], 16)
        second = int(digits[1], 16)
        third = int(digits[2], 16)
        fourth = int(digits[3], 16)
    except ValueError as exc:
        raise ValueError("invalid dtc digits") from exc
    if first > 3:
        raise ValueError("invalid dtc first digit")
    value = (_DTC_PREFIX_REV[prefix] << 14) | (first << 12)
    value |= (second << 8) | (third << 4) | fourth
    return value


def decode_dtc(value: int) -> str:
    prefix = _DTC_PREFIX.get((value >> 14) & 0x3, "P")
    first = (value >> 12) & 0x3
    second = (value >> 8) & 0xF
    third = (value >> 4) & 0xF
    fourth = value & 0xF
    return f"{prefix}{first}{second:X}{third:X}{fourth:X}"


def status_from_byte(status: int) -> str:
    if status & 0x01:
        return "active"
    if status & 0x02:
        return "stored"
    return "unknown"


def status_to_byte(status: str) -> int:
    if status == "active":
        return 0x01
    if status == "stored":
        return 0x02
    return 0x00
