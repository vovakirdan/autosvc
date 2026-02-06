from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from autosvc.core.uds.client import UdsClient, UdsError


DidKind = Literal["ascii", "u16be", "u32be", "bytes"]


@dataclass(frozen=True)
class DidSpec:
    did: int
    name: str
    kind: DidKind
    scale: float = 1.0
    unit: str = ""


_DEFAULT_DIDS: list[DidSpec] = [
    DidSpec(did=0xF190, name="VIN", kind="ascii"),
    DidSpec(did=0xF187, name="ECU Part Number", kind="ascii"),
    # Emulator-defined DID used for deterministic live data tests.
    DidSpec(did=0x1234, name="Engine RPM", kind="u16be", scale=1.0, unit="rpm"),
]

_DID_TABLE: dict[int, DidSpec] = {spec.did: spec for spec in _DEFAULT_DIDS}


class DidError(Exception):
    pass


def spec_for_did(did: int) -> DidSpec:
    did_int = int(did) & 0xFFFF
    spec = _DID_TABLE.get(did_int)
    if spec is not None:
        return spec
    return DidSpec(did=did_int, name=f"DID {format_did(did_int)}", kind="bytes")


def format_did(did: int) -> str:
    return f"{int(did) & 0xFFFF:04X}"


def parse_did(value: str | int) -> int:
    if isinstance(value, int):
        did = value
    elif isinstance(value, str):
        raw = value.strip().lower()
        if raw.startswith("0x"):
            raw = raw[2:]
        if not raw:
            raise ValueError("did must be hex string")
        did = int(raw, 16)
    else:
        raise ValueError("did must be hex string")
    if did < 0 or did > 0xFFFF:
        raise ValueError("did out of range")
    return did


def read_did(uds: UdsClient, did: int) -> bytes:
    did_int = int(did) & 0xFFFF
    request_data = bytes([(did_int >> 8) & 0xFF, did_int & 0xFF])
    try:
        response = uds.request(0x22, request_data)
    except UdsError as exc:
        raise DidError(str(exc)) from exc
    if not response:
        raise DidError("empty response")
    if response[0] == 0x7F:
        if len(response) >= 3:
            raise DidError(f"negative response 0x{response[2]:02X}")
        raise DidError("negative response")
    if len(response) < 3 or response[0] != 0x62:
        raise DidError("unexpected response")
    if response[1] != ((did_int >> 8) & 0xFF) or response[2] != (did_int & 0xFF):
        raise DidError("unexpected DID in response")
    return response[3:]


def read_dids(uds: UdsClient, dids: list[int]) -> dict[int, bytes]:
    out: dict[int, bytes] = {}
    for did in dids:
        did_int = int(did) & 0xFFFF
        out[did_int] = read_did(uds, did_int)
    return out


def decode_did(did: int, data: bytes) -> tuple[DidSpec, str | int | float]:
    spec = spec_for_did(did)
    return spec, decode_value(spec, data)


def decode_value(spec: DidSpec, data: bytes) -> str | int | float:
    if spec.kind == "ascii":
        # Best-effort ASCII. Strip trailing NULs but keep internal spacing.
        return data.decode("ascii", errors="replace").rstrip("\x00")
    if spec.kind == "u16be":
        if len(data) < 2:
            raise DidError("short u16 value")
        raw = int.from_bytes(data[:2], byteorder="big", signed=False)
        if float(spec.scale) == 1.0:
            return raw
        return raw * float(spec.scale)
    if spec.kind == "u32be":
        if len(data) < 4:
            raise DidError("short u32 value")
        raw = int.from_bytes(data[:4], byteorder="big", signed=False)
        if float(spec.scale) == 1.0:
            return raw
        return raw * float(spec.scale)
    if spec.kind == "bytes":
        return data.hex().upper()
    raise DidError("invalid DID spec kind")

