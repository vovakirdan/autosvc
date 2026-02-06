from __future__ import annotations

from typing import Dict, List

from autosvc.core.transport.base import CanFrame, CanTransport
from autosvc.core.uds.dtc import encode_dtc, status_to_byte


class MockTransport(CanTransport):
    """In-memory transport used for local development and deterministic testing.

    This transport intentionally does not implement ISO-TP framing. The ISO-TP
    layer detects it and falls back to a legacy single-frame mode.
    """

    def __init__(self) -> None:
        self._pending: List[CanFrame] = []
        self._profiles: Dict[int, List[tuple[str, str]]] = {
            0x01: [("P2002", "active")],
            0x03: [],
            0x08: [("P0420", "stored")],
        }

    def send(self, can_id: int, data: bytes) -> None:
        ecu = self._ecu_from_request_id(can_id)
        if ecu is None or not data:
            return
        response = self._build_response(ecu, data)
        if response is None:
            return
        resp_id = 0x7E8 + ecu
        self._pending.append(CanFrame(can_id=resp_id, data=response))

    def recv(self, timeout_ms: int) -> CanFrame | None:
        if self._pending:
            return self._pending.pop(0)
        return None

    def _ecu_from_request_id(self, can_id: int) -> int | None:
        if 0x7E0 <= can_id <= 0x7EF:
            return can_id - 0x7E0
        return None

    def _build_response(self, ecu: int, data: bytes) -> bytes | None:
        service = data[0]
        if service == 0x10:
            session_type = data[1] if len(data) > 1 else 0x01
            if ecu in self._profiles:
                return bytes([0x50, session_type])
            return None
        if service == 0x19:
            if len(data) < 2 or data[1] != 0x02:
                return bytes([0x7F, service, 0x12])
            status_mask = data[2] if len(data) > 2 else 0xFF
            payload = bytearray([0x59, 0x02, status_mask])
            for code, status in self._profiles.get(ecu, []):
                dtc_val = encode_dtc(code)
                payload.append((dtc_val >> 8) & 0xFF)
                payload.append(dtc_val & 0xFF)
                payload.append(status_to_byte(status))
            return bytes(payload)
        if service == 0x14:
            if ecu in self._profiles:
                self._profiles[ecu] = []
            return bytes([0x54])
        return bytes([0x7F, service, 0x11])

