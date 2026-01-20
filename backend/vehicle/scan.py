from __future__ import annotations

from typing import List

from backend.uds.client import UdsClient


def scan_ecus(uds_client: UdsClient) -> List[str]:
    found: List[str] = []
    for ecu in range(1, 0x10):
        ecu_id = f"{ecu:02X}"
        try:
            if uds_client.diagnostic_session_control(ecu_id):
                found.append(ecu_id)
        except Exception:
            continue
    return found
