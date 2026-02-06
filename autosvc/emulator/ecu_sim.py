from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Iterable

import can

from autosvc.core.uds.dtc import encode_dtc, status_to_byte


class IsoTpError(Exception):
    pass


def _decode_st_min(value: int) -> float:
    if value <= 0x7F:
        return value / 1000.0
    if 0xF1 <= value <= 0xF9:
        return (value - 0xF0) / 10000.0
    return 0.0


def _pad8(data: bytes) -> bytes:
    if len(data) > 8:
        raise IsoTpError("CAN frame too large")
    if len(data) < 8:
        return data + (b"\x00" * (8 - len(data)))
    return data


def _send_frame(bus: can.BusABC, can_id: int, data: bytes) -> None:
    msg = can.Message(arbitration_id=can_id, data=_pad8(data), is_extended_id=False)
    bus.send(msg)


def _recv_frame(bus: can.BusABC, *, timeout_s: float) -> can.Message | None:
    return bus.recv(timeout_s)


@dataclass
class _IsoTpRxState:
    total_len: int
    buffer: bytearray
    expected_seq: int


class IsoTpEndpoint:
    """Minimal ISO-TP endpoint for the ECU emulator (11-bit IDs)."""

    def __init__(self, bus: can.BusABC, *, req_id: int, resp_id: int) -> None:
        self._bus = bus
        self._req_id = req_id
        self._resp_id = resp_id
        self._rx_state: _IsoTpRxState | None = None

    def poll_request(self, *, timeout_s: float = 0.1) -> bytes | None:
        """Return a complete request payload if available, else None."""
        msg = _recv_frame(self._bus, timeout_s=timeout_s)
        if msg is None:
            return None
        if msg.arbitration_id not in {self._req_id, 0x7DF}:
            return None
        data = bytes(msg.data)
        if not data:
            return None
        frame_type = data[0] >> 4
        if frame_type == 0x3:
            # Flow Control for an outgoing response; handled in send_response().
            return None
        if msg.arbitration_id == 0x7DF:
            # Functional requests are treated as single-frame only.
            if frame_type != 0x0:
                return None
            length = data[0] & 0x0F
            if length > len(data) - 1:
                raise IsoTpError("single frame length mismatch")
            return data[1 : 1 + length]
        return self._rx_feed(data)

    def recv_request_blocking(self, *, timeout_s: float = 1.0) -> bytes | None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            payload = self.poll_request(timeout_s=min(0.1, max(0.0, remaining)))
            if payload is not None:
                return payload
        return None

    def send_response(self, payload: bytes, *, timeout_s: float = 1.0) -> None:
        length = len(payload)
        if length <= 7:
            _send_frame(self._bus, self._resp_id, bytes([length & 0x0F]) + payload)
            return
        if length > 0x0FFF:
            raise IsoTpError("payload too large")

        first = 0x10 | ((length >> 8) & 0x0F)
        second = length & 0xFF
        _send_frame(self._bus, self._resp_id, bytes([first, second]) + payload[:6])

        block_size, st_min_s = self._await_flow_control(timeout_s=timeout_s)
        self._send_consecutive_frames(payload[6:], block_size=block_size, st_min_s=st_min_s, timeout_s=timeout_s)

    def _rx_feed(self, data: bytes) -> bytes | None:
        frame_type = data[0] >> 4
        if frame_type == 0x0:
            length = data[0] & 0x0F
            if length > len(data) - 1:
                raise IsoTpError("single frame length mismatch")
            self._rx_state = None
            return data[1 : 1 + length]

        if frame_type == 0x1:
            if len(data) < 2:
                raise IsoTpError("short first frame")
            total_len = ((data[0] & 0x0F) << 8) | data[1]
            if total_len <= 7:
                raise IsoTpError("invalid first frame length")
            self._rx_state = _IsoTpRxState(total_len=total_len, buffer=bytearray(data[2:]), expected_seq=1)
            # Flow Control (Continue To Send, block_size=0 => unlimited frames, st_min=0).
            _send_frame(self._bus, self._resp_id, bytes([0x30, 0x00, 0x00]))
            if len(self._rx_state.buffer) >= total_len:
                payload = bytes(self._rx_state.buffer[:total_len])
                self._rx_state = None
                return payload
            return None

        if frame_type == 0x2:
            if self._rx_state is None:
                raise IsoTpError("unexpected consecutive frame")
            seq = data[0] & 0x0F
            if seq != self._rx_state.expected_seq:
                raise IsoTpError("sequence number mismatch")
            self._rx_state.buffer.extend(data[1:])
            self._rx_state.expected_seq = (self._rx_state.expected_seq + 1) & 0x0F
            if len(self._rx_state.buffer) >= self._rx_state.total_len:
                payload = bytes(self._rx_state.buffer[: self._rx_state.total_len])
                self._rx_state = None
                return payload
            return None

        if frame_type == 0x3:
            return None

        raise IsoTpError("unknown frame type")

    def _await_flow_control(self, *, timeout_s: float) -> tuple[int, float]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            msg = _recv_frame(self._bus, timeout_s=min(0.1, max(0.0, remaining)))
            if msg is None:
                continue
            if msg.arbitration_id != self._req_id:
                continue
            data = bytes(msg.data)
            if not data:
                continue
            if (data[0] >> 4) != 0x3:
                continue
            if len(data) < 3:
                raise IsoTpError("short flow control")
            flow_status = data[0] & 0x0F
            block_size = data[1]
            st_min_s = _decode_st_min(data[2])
            if flow_status == 0x0:
                return block_size, st_min_s
            if flow_status == 0x1:
                continue
            if flow_status == 0x2:
                raise IsoTpError("flow control overflow")
            raise IsoTpError("invalid flow control status")
        raise IsoTpError("timeout waiting for flow control")

    def _send_consecutive_frames(self, payload: bytes, *, block_size: int, st_min_s: float, timeout_s: float) -> None:
        seq = 1
        offset = 0
        frames_in_block = 0
        while offset < len(payload):
            chunk = payload[offset : offset + 7]
            pci = 0x20 | (seq & 0x0F)
            _send_frame(self._bus, self._resp_id, bytes([pci]) + chunk)
            offset += len(chunk)
            seq = (seq + 1) & 0x0F
            frames_in_block += 1
            if st_min_s > 0:
                time.sleep(st_min_s)
            if block_size and frames_in_block >= block_size and offset < len(payload):
                block_size, st_min_s = self._await_flow_control(timeout_s=timeout_s)
                frames_in_block = 0


class EcuSimulator:
    def __init__(self, bus: can.BusABC, *, ecu_hex: str = "01") -> None:
        self._ecu_int = int(ecu_hex, 16)
        if self._ecu_int < 0 or self._ecu_int > 0x7F:
            raise ValueError("ecu out of range")
        self._req_id = 0x7E0 + self._ecu_int
        self._resp_id = 0x7E8 + self._ecu_int
        self._bus = bus
        self._isotp = IsoTpEndpoint(bus, req_id=self._req_id, resp_id=self._resp_id)
        self._dtcs: list[tuple[str, str]] = [
            ("P2002", "active"),
            ("P0420", "stored"),
        ]

    @property
    def ecu(self) -> str:
        return f"{self._ecu_int:02X}"

    def serve_forever(self) -> None:
        while True:
            req = self._isotp.recv_request_blocking(timeout_s=1.0)
            if req is None:
                continue
            try:
                resp = self._handle_uds(req)
            except Exception:
                # Generic negative response: service not supported.
                if req:
                    resp = bytes([0x7F, req[0], 0x11])
                else:
                    continue
            self._isotp.send_response(resp, timeout_s=1.0)

    def _handle_uds(self, payload: bytes) -> bytes:
        if not payload:
            raise ValueError("empty request")
        sid = payload[0]

        if sid == 0x10:
            session_type = payload[1] if len(payload) > 1 else 0x01
            return bytes([0x50, session_type])

        if sid == 0x19:
            if len(payload) < 2 or payload[1] != 0x02:
                return bytes([0x7F, sid, 0x12])
            status_mask = payload[2] if len(payload) > 2 else 0xFF
            out = bytearray([0x59, 0x02, status_mask])
            for code, status in self._dtcs:
                dtc_val = encode_dtc(code)
                out.append((dtc_val >> 8) & 0xFF)
                out.append(dtc_val & 0xFF)
                out.append(status_to_byte(status))
            return bytes(out)

        if sid == 0x14:
            self._dtcs = []
            return bytes([0x54])

        return bytes([0x7F, sid, 0x11])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="autosvc ECU simulator (SocketCAN/vcan)")
    parser.add_argument("--can", default="vcan0", help="SocketCAN interface (e.g. vcan0)")
    parser.add_argument("--ecu", default="01", help="ECU address as hex (default: 01)")
    args = parser.parse_args(argv)

    bus = can.interface.Bus(channel=args.can, interface="socketcan")
    sim = EcuSimulator(bus, ecu_hex=args.ecu)
    print(f"autosvc ECU simulator listening on {args.can} (ECU {sim.ecu})", file=sys.stderr, flush=True)
    try:
        sim.serve_forever()
    except KeyboardInterrupt:
        return None
    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
