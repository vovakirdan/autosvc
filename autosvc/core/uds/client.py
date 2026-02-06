from __future__ import annotations

import time

from autosvc.core.isotp.transport import IsoTpError, IsoTpTimeoutError, IsoTpTransport
from autosvc.core.transport.base import CanTransport
from autosvc.core.uds.dtc import Dtc, decode_dtc, status_from_byte


class UdsError(Exception):
    pass


class UdsClient:
    def __init__(
        self,
        transport: CanTransport,
        p2_ms: int = 50,
        p2_star_ms: int = 5000,
        *,
        can_id_mode: str = "11bit",
    ) -> None:
        self._transport = transport
        self._p2_ms = int(p2_ms)
        self._p2_star_ms = int(p2_star_ms)
        self._can_id_mode = can_id_mode
        self._active_ecu: str | None = None

    def request(self, sid: int, data: bytes = b"") -> bytes:
        if self._active_ecu is None:
            raise UdsError("ecu not set")
        return self._request_for_ecu(self._active_ecu, sid, data)

    def diagnostic_session_control(self, ecu: str, session_type: int = 0x01) -> bool:
        self._active_ecu = ecu
        try:
            response = self.request(0x10, bytes([session_type]))
        except UdsError:
            return False
        if response[0] == 0x7F:
            return False
        return response[:2] == bytes([0x50, session_type])

    def read_dtcs(self, ecu: str) -> list[Dtc]:
        self._active_ecu = ecu
        response = self.request(0x19, b"\x02\xFF")
        if response[0] == 0x7F:
            raise UdsError(f"negative response 0x{response[2]:02X}")
        if len(response) < 3 or response[0] != 0x59 or response[1] != 0x02:
            raise UdsError("unexpected response")
        dtcs: list[Dtc] = []
        offset = 3
        while offset + 2 < len(response):
            dtc_val = (response[offset] << 8) | response[offset + 1]
            status = status_from_byte(response[offset + 2])
            dtcs.append(Dtc(code=decode_dtc(dtc_val), status=status))
            offset += 3
        return dtcs

    def clear_dtcs(self, ecu: str) -> None:
        self._active_ecu = ecu
        response = self.request(0x14, b"\xFF\xFF\xFF")
        if response[0] == 0x7F:
            raise UdsError(f"negative response 0x{response[2]:02X}")
        if response[0] != 0x54:
            raise UdsError("unexpected response")

    def _request_for_ecu(self, ecu: str, sid: int, data: bytes) -> bytes:
        payload = bytes([sid]) + data
        req_id, resp_id = self._ecu_ids(ecu)
        isotp = IsoTpTransport(self._transport, req_id, resp_id, timeout_ms=self._p2_ms)
        try:
            response = isotp.request(payload)
        except IsoTpTimeoutError as exc:
            raise UdsError("timeout waiting for response") from exc
        except IsoTpError as exc:
            raise UdsError(str(exc)) from exc
        if not response:
            raise UdsError("empty response")
        if self._is_response_pending(response, sid):
            response = self._wait_for_pending(isotp, sid)
        return response

    def _wait_for_pending(self, isotp: IsoTpTransport, sid: int) -> bytes:
        deadline = time.monotonic() + (self._p2_star_ms / 1000.0)
        while True:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                raise UdsError("timeout waiting for response")
            isotp.timeout_ms = remaining_ms
            try:
                response = isotp.recv_response()
            except IsoTpTimeoutError as exc:
                raise UdsError("timeout waiting for response") from exc
            except IsoTpError as exc:
                raise UdsError(str(exc)) from exc
            if not response:
                raise UdsError("empty response")
            if not self._is_response_pending(response, sid):
                return response

    def _is_response_pending(self, payload: bytes, sid: int) -> bool:
        return len(payload) >= 3 and payload[0] == 0x7F and payload[1] == sid and payload[2] == 0x78

    def _ecu_ids(self, ecu: str) -> tuple[int, int]:
        ecu_int = int(ecu, 16)
        if ecu_int < 0 or ecu_int > 0xFF:
            raise ValueError("ecu out of range")
        if self._can_id_mode == "11bit":
            if ecu_int > 0x17:
                raise ValueError("ecu out of range")
            return 0x7E0 + ecu_int, 0x7E8 + ecu_int
        if self._can_id_mode == "29bit":
            # See autosvc.core.vehicle.topology.ids_for_ecu() for details.
            tester_sa = 0xF1
            req_id = 0x18DA0000 | ((ecu_int & 0xFF) << 8) | (tester_sa & 0xFF)
            resp_id = 0x18DA0000 | ((tester_sa & 0xFF) << 8) | (ecu_int & 0xFF)
            return req_id, resp_id
        raise ValueError("invalid can_id_mode")
