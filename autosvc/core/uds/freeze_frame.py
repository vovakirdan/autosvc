from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autosvc.core.uds.client import UdsClient, UdsError
from autosvc.core.uds.dtc import decode_dtc, encode_dtc
from autosvc.core.uds.did import DidError, DidSpec, decode_value, format_did, spec_for_did


class FreezeFrameError(Exception):
    pass


@dataclass(frozen=True)
class FreezeFrameParam:
    name: str
    did: str
    raw: bytes
    value: str | int | float
    unit: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "did": self.did,
            "raw": self.raw.hex().upper(),
            "value": self.value,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class FreezeFrame:
    dtc: str
    record_id: int
    parameters: list[FreezeFrameParam]

    def to_dict(self) -> dict[str, Any]:
        # Keep the JSON payload focused on useful context. The DTC is already
        # present in the parent DTC object.
        return {
            "record_id": int(self.record_id) & 0xFF,
            "parameters": [p.to_dict() for p in self.parameters],
        }


# Emulator-defined DIDs used for deterministic freeze-frame output.
_FF_DID_SPECS: dict[int, DidSpec] = {
    0x1235: DidSpec(did=0x1235, name="Vehicle Speed", kind="u16be", scale=1.0, unit="km/h"),
    0x1236: DidSpec(did=0x1236, name="Coolant Temp", kind="u16be", scale=1.0, unit="C"),
}


def list_snapshot_identification(uds: UdsClient, *, status_mask: int = 0xFF, record_id: int = 0xFF) -> dict[str, int]:
    """Best-effort snapshot identification via UDS ReadDTCInformation (0x19).

    This uses subfunction 0x04 (reportDTCSnapshotIdentification) in an MVP form:
    it returns a map {DTC -> record_id}. If unsupported, an empty dict is
    returned.
    """

    req = bytes([0x04, int(status_mask) & 0xFF, int(record_id) & 0xFF])
    try:
        resp = uds.request(0x19, req)
    except UdsError:
        return {}
    if not resp:
        return {}
    if resp[0] == 0x7F:
        return {}
    if len(resp) < 3 or resp[0] != 0x59 or resp[1] != 0x04:
        raise FreezeFrameError("unexpected snapshot identification response")
    out: dict[str, int] = {}
    offset = 3
    while offset + 2 < len(resp):
        dtc_val = (resp[offset] << 8) | resp[offset + 1]
        rec = int(resp[offset + 2]) & 0xFF
        out[decode_dtc(dtc_val).formatted] = rec
        offset += 3
    return out


def read_snapshot_record(uds: UdsClient, *, dtc: str, record_id: int) -> FreezeFrame | None:
    """Read a snapshot record for a given DTC (best-effort).

    Uses subfunction 0x05 (reportDTCSnapshotRecordByDTCNumber). Returns None if
    the ECU does not support snapshots for this DTC/record.
    """

    dtc_val = encode_dtc(dtc)
    req = bytes([0x05, (dtc_val >> 8) & 0xFF, dtc_val & 0xFF, int(record_id) & 0xFF])
    try:
        resp = uds.request(0x19, req)
    except UdsError:
        return None
    if not resp:
        return None
    if resp[0] == 0x7F:
        return None
    if len(resp) < 6 or resp[0] != 0x59 or resp[1] != 0x05:
        raise FreezeFrameError("unexpected snapshot record response")
    if resp[2] != ((dtc_val >> 8) & 0xFF) or resp[3] != (dtc_val & 0xFF):
        raise FreezeFrameError("unexpected DTC in snapshot record response")
    if resp[4] != (int(record_id) & 0xFF):
        raise FreezeFrameError("unexpected record id in snapshot record response")

    param_count = int(resp[5]) & 0xFF
    offset = 6
    params: list[FreezeFrameParam] = []
    for _ in range(param_count):
        if offset + 3 > len(resp):
            raise FreezeFrameError("truncated snapshot record")
        did = (resp[offset] << 8) | resp[offset + 1]
        length = int(resp[offset + 2]) & 0xFF
        offset += 3
        if offset + length > len(resp):
            raise FreezeFrameError("truncated snapshot parameter")
        raw = bytes(resp[offset : offset + length])
        offset += length
        spec, value, unit = _decode_param(did, raw)
        params.append(
            FreezeFrameParam(
                name=spec.name,
                did=format_did(spec.did),
                raw=raw,
                value=value,
                unit=unit,
            )
        )

    return FreezeFrame(dtc=dtc, record_id=int(record_id) & 0xFF, parameters=params)


def _decode_param(did: int, raw: bytes) -> tuple[DidSpec, str | int | float, str]:
    spec = _FF_DID_SPECS.get(int(did) & 0xFFFF) or spec_for_did(did)
    try:
        value = decode_value(spec, raw)
    except DidError:
        # Preserve the raw bytes even if decoding fails.
        value = raw.hex().upper()
    return spec, value, spec.unit

