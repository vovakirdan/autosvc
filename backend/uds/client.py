from __future__ import annotations

import time
from typing import List

from backend.transport.base import CanTransport
from backend.uds.dtc import Dtc, decode_dtc, status_from_byte


class UdsError(Exception):
    pass


class UdsClient:
    def __init__(self, transport: CanTransport, timeout_ms: int = 200) -> None:
        self._transport = transport
        self._timeout_ms = timeout_ms

    def diagnostic_session_control(self, ecu: str, session_type: int = 0x01) -> bool:
        response = self._request(ecu, bytes([0x10, session_type]))
        if response is None:
            return False
        if response[0] == 0x7F:
            return False
        return response[:2] == bytes([0x50, session_type])

    def read_dtcs(self, ecu: str) -> List[Dtc]:
        response = self._request(ecu, bytes([0x19, 0x02, 0xFF]))
        if response is None:
            raise UdsError("no response")
        if response[0] == 0x7F:
            raise UdsError(f"negative response 0x{response[2]:02X}")
        if len(response) < 3 or response[0] != 0x59 or response[1] != 0x02:
            raise UdsError("unexpected response")
        dtcs: List[Dtc] = []
        offset = 3
        while offset + 2 < len(response):
            dtc_val = (response[offset] << 8) | response[offset + 1]
            status = status_from_byte(response[offset + 2])
            dtcs.append(Dtc(code=decode_dtc(dtc_val), status=status))
            offset += 3
        return dtcs

    def clear_dtcs(self, ecu: str) -> None:
        response = self._request(ecu, bytes([0x14, 0xFF, 0xFF, 0xFF]))
        if response is None:
            raise UdsError("no response")
        if response[0] == 0x7F:
            raise UdsError(f"negative response 0x{response[2]:02X}")
        if response[0] != 0x54:
            raise UdsError("unexpected response")

    def _request(self, ecu: str, payload: bytes) -> bytes | None:
        req_id, resp_id = self._ecu_ids(ecu)
        self._transport.send(req_id, payload)
        deadline = time.monotonic() + (self._timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining <= 0:
                break
            frame = self._transport.recv(remaining)
            if frame is None:
                break
            if frame.can_id != resp_id:
                continue
            return frame.data
        return None

    def _ecu_ids(self, ecu: str) -> tuple[int, int]:
        ecu_int = int(ecu, 16)
        if ecu_int < 0 or ecu_int > 0x7F:
            raise ValueError("ecu out of range")
        return 0x7E0 + ecu_int, 0x7E8 + ecu_int
