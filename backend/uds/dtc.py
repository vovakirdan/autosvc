from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple, Union


_DTC_PREFIX = {0: "P", 1: "C", 2: "B", 3: "U"}
_DTC_PREFIX_REV = {v: k for k, v in _DTC_PREFIX.items()}


@dataclass(frozen=True)
class DtcCode:
    value: int
    formatted: str


@dataclass(frozen=True)
class DtcStatus:
    byte: int
    label: str


DtcCodeLike = Union[DtcCode, str]
DtcStatusLike = Union[DtcStatus, str]


@dataclass(frozen=True)
class Dtc:
    code: DtcCodeLike
    status: DtcStatusLike

    def to_dict(self) -> Dict[str, str]:
        return {"code": self._code_str(), "status": self._status_str()}

    def raw_tuple(self) -> Tuple[int, int]:
        return (self._code_value(), self._status_byte())

    def _code_str(self) -> str:
        if isinstance(self.code, DtcCode):
            return self.code.formatted
        return self.code

    def _status_str(self) -> str:
        if isinstance(self.status, DtcStatus):
            return self.status.label
        return self.status

    def _code_value(self) -> int:
        if isinstance(self.code, DtcCode):
            return self.code.value
        return encode_dtc(self.code)

    def _status_byte(self) -> int:
        if isinstance(self.status, DtcStatus):
            return self.status.byte
        return status_to_byte(self.status)


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


def decode_dtc(value: int) -> DtcCode:
    formatted = _decode_dtc_string(value)
    return DtcCode(value=value & 0xFFFFFF, formatted=formatted)


def _decode_dtc_string(value: int) -> str:
    prefix = _DTC_PREFIX.get((value >> 14) & 0x3, "P")
    first = (value >> 12) & 0x3
    second = (value >> 8) & 0xF
    third = (value >> 4) & 0xF
    fourth = value & 0xF
    return f"{prefix}{first}{second:X}{third:X}{fourth:X}"


def status_from_byte(status: int) -> DtcStatus:
    if status & 0x01:
        label = "active"
    elif status & 0x04:
        label = "pending"
    elif status & 0x02:
        label = "stored"
    else:
        label = "unknown"
    return DtcStatus(byte=status & 0xFF, label=label)


def status_to_byte(status: str) -> int:
    if status == "active":
        return 0x01
    if status == "pending":
        return 0x04
    if status == "stored":
        return 0x02
    return 0x00
