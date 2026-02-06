from __future__ import annotations

import time

from autosvc.core.transport.base import CanFrame, CanTransport


class IsoTpError(Exception):
    pass


class IsoTpTimeoutError(IsoTpError):
    pass


class IsoTpProtocolError(IsoTpError):
    pass


def _encode_st_min(st_min_ms: int) -> int:
    if st_min_ms < 0:
        return 0
    if st_min_ms <= 0x7F:
        return st_min_ms
    return 0x7F


def _decode_st_min(value: int) -> float:
    if value <= 0x7F:
        return value / 1000.0
    if 0xF1 <= value <= 0xF9:
        return (value - 0xF0) / 10000.0
    return 0.0


def _detect_legacy_transport(can_transport: CanTransport) -> bool:
    name = type(can_transport).__name__
    module = type(can_transport).__module__
    # The built-in MockTransport doesn't implement ISO-TP frames yet.
    return name == "MockTransport" or module.endswith(".mock")


class IsoTpTransport:
    """ISO-TP transport for single-request / single-response workflows.

    This class is used by the UDS client for request/response over CAN.
    """

    def __init__(
        self,
        can_transport: CanTransport,
        tx_id: int,
        rx_id: int,
        *,
        block_size: int = 8,
        st_min_ms: int = 10,
        timeout_ms: int = 1000,
    ) -> None:
        self._can = can_transport
        self._tx_id = tx_id
        self._rx_id = rx_id
        self._block_size = int(block_size)
        self._st_min_ms = int(st_min_ms)
        self._timeout_ms = int(timeout_ms)
        self._legacy = _detect_legacy_transport(can_transport)

    @property
    def timeout_ms(self) -> int:
        return self._timeout_ms

    @timeout_ms.setter
    def timeout_ms(self, value: int) -> None:
        self._timeout_ms = int(value)

    def request(self, payload: bytes) -> bytes:
        if self._legacy:
            return self._legacy_request(payload)
        self._send_payload(payload)
        return self._recv_payload(self._timeout_ms)

    def recv_response(self) -> bytes:
        if self._legacy:
            return self._recv_legacy(self._timeout_ms)
        return self._recv_payload(self._timeout_ms)

    def _legacy_request(self, payload: bytes) -> bytes:
        self._can.send(self._tx_id, payload)
        return self._recv_legacy(self._timeout_ms)

    def _recv_legacy(self, timeout_ms: int) -> bytes:
        frame = self._recv_frame(self._rx_id, timeout_ms)
        return frame.data

    def _send_payload(self, payload: bytes) -> None:
        length = len(payload)
        if length <= 7:
            pci = length & 0x0F
            self._send_can(bytes([pci]) + payload)
            return
        if length > 0x0FFF:
            raise IsoTpProtocolError("payload too large")
        first = 0x10 | ((length >> 8) & 0x0F)
        second = length & 0xFF
        self._send_can(bytes([first, second]) + payload[:6])
        block_size, st_min = self._await_flow_control()
        self._send_consecutive_frames(payload[6:], block_size, st_min)

    def _send_consecutive_frames(self, payload: bytes, block_size: int, st_min: float) -> None:
        seq = 1
        frames_in_block = 0
        offset = 0
        while offset < len(payload):
            chunk = payload[offset : offset + 7]
            pci = 0x20 | (seq & 0x0F)
            self._send_can(bytes([pci]) + chunk)
            offset += len(chunk)
            seq = (seq + 1) & 0x0F
            frames_in_block += 1
            if st_min > 0:
                time.sleep(st_min)
            if block_size and frames_in_block >= block_size and offset < len(payload):
                block_size, st_min = self._await_flow_control()
                frames_in_block = 0

    def _await_flow_control(self) -> tuple[int, float]:
        deadline = time.monotonic() + (self._timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                break
            frame = self._can.recv(remaining_ms)
            if frame is None:
                continue
            if frame.can_id != self._rx_id:
                continue
            data = frame.data
            if not data:
                continue
            if (data[0] >> 4) != 0x3:
                continue
            if len(data) < 3:
                raise IsoTpProtocolError("short flow control")
            flow_status = data[0] & 0x0F
            block_size = data[1]
            st_min = _decode_st_min(data[2])
            if flow_status == 0x0:
                return block_size, st_min
            if flow_status == 0x1:
                continue
            if flow_status == 0x2:
                raise IsoTpProtocolError("flow control overflow")
            raise IsoTpProtocolError("invalid flow control status")
        raise IsoTpTimeoutError("timeout waiting for flow control")

    def _recv_payload(self, timeout_ms: int) -> bytes:
        frame = self._recv_frame(self._rx_id, timeout_ms)
        data = frame.data
        if not data:
            raise IsoTpProtocolError("empty frame")
        frame_type = data[0] >> 4
        if frame_type == 0x0:
            length = data[0] & 0x0F
            if length > len(data) - 1:
                raise IsoTpProtocolError("single frame length mismatch")
            return data[1 : 1 + length]
        if frame_type == 0x1:
            if len(data) < 2:
                raise IsoTpProtocolError("short first frame")
            total_len = ((data[0] & 0x0F) << 8) | data[1]
            if total_len <= 7:
                raise IsoTpProtocolError("invalid first frame length")
            buffer = bytearray(data[2:])
            self._send_flow_control()
            return self._recv_consecutive_frames(buffer, total_len)
        if frame_type == 0x2:
            raise IsoTpProtocolError("unexpected consecutive frame")
        if frame_type == 0x3:
            raise IsoTpProtocolError("unexpected flow control")
        raise IsoTpProtocolError("unknown frame type")

    def _recv_consecutive_frames(self, buffer: bytearray, total_len: int) -> bytes:
        expected_seq = 1
        frames_in_block = 0
        while len(buffer) < total_len:
            frame = self._recv_frame(self._rx_id, self._timeout_ms)
            data = frame.data
            if not data:
                raise IsoTpProtocolError("empty consecutive frame")
            frame_type = data[0] >> 4
            if frame_type != 0x2:
                raise IsoTpProtocolError("unexpected frame while receiving")
            seq = data[0] & 0x0F
            if seq != expected_seq:
                raise IsoTpProtocolError("sequence number mismatch")
            buffer.extend(data[1:])
            expected_seq = (expected_seq + 1) & 0x0F
            frames_in_block += 1
            if self._block_size and frames_in_block >= self._block_size and len(buffer) < total_len:
                self._send_flow_control()
                frames_in_block = 0
        return bytes(buffer[:total_len])

    def _send_flow_control(self) -> None:
        st_min = _encode_st_min(self._st_min_ms)
        payload = bytes([0x30, self._block_size & 0xFF, st_min])
        self._send_can(payload)

    def _send_can(self, payload: bytes) -> None:
        if len(payload) > 8:
            raise IsoTpProtocolError("CAN frame too large")
        if len(payload) < 8:
            payload = payload + (b"\x00" * (8 - len(payload)))
        self._can.send(self._tx_id, payload)

    def _recv_frame(self, can_id: int, timeout_ms: int) -> CanFrame:
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                break
            frame = self._can.recv(remaining_ms)
            if frame is None:
                continue
            if frame.can_id != can_id:
                continue
            return frame
        raise IsoTpTimeoutError("timeout waiting for CAN frame")

