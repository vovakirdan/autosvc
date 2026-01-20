from __future__ import annotations

from typing import Any, Dict

from backend.uds.client import UdsClient
from backend.vehicle.scan import scan_ecus


def handle_request(request: Dict[str, Any], uds_client: UdsClient) -> Dict[str, Any]:
    if not isinstance(request, dict):
        return _error("invalid request")
    cmd = request.get("cmd")
    if not cmd:
        return _error("missing cmd")
    if cmd == "scan_ecus":
        ecus = scan_ecus(uds_client)
        return {"ok": True, "ecus": ecus}
    if cmd == "read_dtcs":
        ecu = _parse_ecu(request.get("ecu"))
        dtcs = uds_client.read_dtcs(ecu)
        return {"ok": True, "dtcs": [dtc.to_dict() for dtc in dtcs]}
    if cmd == "clear_dtcs":
        ecu = _parse_ecu(request.get("ecu"))
        uds_client.clear_dtcs(ecu)
        return {"ok": True}
    return _error("unknown cmd")


def _parse_ecu(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("ecu must be hex string")
    try:
        ecu_int = int(value, 16)
    except ValueError as exc:
        raise ValueError("ecu must be hex string") from exc
    if ecu_int < 0 or ecu_int > 0x7F:
        raise ValueError("ecu out of range")
    return f"{ecu_int:02X}"


def _error(message: str) -> Dict[str, Any]:
    return {"ok": False, "error": message}
