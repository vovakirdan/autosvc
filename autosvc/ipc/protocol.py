from __future__ import annotations

import json
import logging
from typing import Any

from autosvc.core.service import DiagnosticService
from autosvc.core.uds.did import parse_did
from autosvc.core.vehicle.discovery import DiscoveryConfig


log = logging.getLogger(__name__)


def decode_json_line(line: bytes) -> dict[str, Any]:
    try:
        text = line.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("invalid utf-8") from exc
    if not text:
        raise ValueError("empty request")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid json") from exc
    if not isinstance(raw, dict):
        raise ValueError("invalid request")
    return raw


def encode_json_line(payload: dict[str, Any]) -> bytes:
    # IPC is JSONL; keep it compact but deterministic.
    return (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


def handle_request(request: dict[str, Any], service: DiagnosticService) -> dict[str, Any]:
    cmd = request.get("cmd")
    if not cmd:
        return error("missing cmd")

    log.info("IPC cmd", extra={"cmd": cmd})

    if cmd == "scan_ecus":
        # Keep the original `ecus` list for compatibility, but include lightweight node metadata.
        can_id_mode = str(getattr(service, "_can_id_mode", "11bit"))
        topo = service.scan_topology(DiscoveryConfig(can_id_mode=can_id_mode))
        ecus = [n.ecu for n in topo.nodes]
        nodes = [{"ecu": n.ecu, "ecu_name": getattr(n, "ecu_name", "Unknown ECU")} for n in topo.nodes]
        return {"ok": True, "ecus": ecus, "nodes": nodes}

    if cmd == "read_dtcs":
        ecu = request.get("ecu")
        if not isinstance(ecu, str):
            return error("ecu must be hex string")
        dtcs = service.read_dtcs(ecu)
        return {"ok": True, "dtcs": dtcs}

    if cmd == "clear_dtcs":
        ecu = request.get("ecu")
        if not isinstance(ecu, str):
            return error("ecu must be hex string")
        service.clear_dtcs(ecu)
        return {"ok": True}

    if cmd == "read_did":
        ecu = request.get("ecu")
        if not isinstance(ecu, str):
            return error("ecu must be hex string")
        did_raw = request.get("did")
        try:
            did_int = parse_did(did_raw)  # accepts str or int
        except Exception:
            return error("did must be hex string")
        item = service.read_did(ecu, did_int)
        return {"ok": True, "item": item}

    return error("unknown cmd")
