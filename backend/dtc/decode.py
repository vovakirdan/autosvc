from __future__ import annotations

from typing import Dict, List, Tuple

from backend.dtc.format import code24_to_raw_hex, uds_dtc_to_sae
from backend.dtc.registry import describe
from backend.dtc.status import decode_status_byte


def decode_dtcs(raw_dtcs: List[Tuple[int, int]], brand: str | None) -> List[Dict[str, object]]:
    decoded: List[Dict[str, object]] = []
    for code24, status_byte in raw_dtcs:
        code = uds_dtc_to_sae(code24)
        status_info = decode_status_byte(status_byte)
        status = _status_from_flags(status_info)
        description = describe(code, brand) or "Unknown DTC"
        system = code[0]
        severity = _severity(system, code, status_info)
        decoded.append(
            {
                "code": code,
                "status": status,
                "raw": code24_to_raw_hex(code24),
                "status_byte": int(status_byte) & 0xFF,
                "flags": status_info["flags"],
                "description": description,
                "system": system,
                "severity": severity,
            }
        )
    return decoded


def _status_from_flags(status_info: Dict[str, object]) -> str:
    if status_info.get("test_failed") or status_info.get("confirmed_dtc"):
        return "active"
    if status_info.get("pending_dtc"):
        return "pending"
    return "stored"


def _severity(system: str, code: str, status_info: Dict[str, object]) -> str:
    if status_info.get("warning_indicator_requested"):
        return "critical"
    if system == "U":
        return "warning"
    if code.startswith("P0") and status_info.get("confirmed_dtc"):
        return "warning"
    return "info"
