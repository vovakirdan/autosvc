from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

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


def _send_frame(bus: can.BusABC, can_id: int, data: bytes, *, is_extended_id: bool) -> None:
    msg = can.Message(arbitration_id=can_id, data=_pad8(data), is_extended_id=is_extended_id)
    bus.send(msg)


def _recv_frame(bus: can.BusABC, *, timeout_s: float, is_extended_id: bool) -> can.Message | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        msg = bus.recv(min(0.1, remaining))
        if msg is None:
            continue
        if bool(getattr(msg, "is_extended_id", False)) != bool(is_extended_id):
            continue
        return msg
    return None

def _decode_isotp_single_frame(data: bytes) -> bytes | None:
    if not data:
        return None
    frame_type = data[0] >> 4
    if frame_type != 0x0:
        return None
    length = data[0] & 0x0F
    if length > len(data) - 1:
        return None
    return data[1 : 1 + length]


def _await_flow_control(
    bus: can.BusABC,
    *,
    req_id: int,
    timeout_s: float,
    is_extended_id: bool,
) -> tuple[int, float]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        msg = _recv_frame(bus, timeout_s=min(0.1, max(0.0, remaining)), is_extended_id=is_extended_id)
        if msg is None:
            continue
        if msg.arbitration_id != req_id:
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


def _send_consecutive_frames(
    bus: can.BusABC,
    *,
    resp_id: int,
    payload: bytes,
    block_size: int,
    st_min_s: float,
    timeout_s: float,
    req_id: int,
    is_extended_id: bool,
) -> None:
    seq = 1
    offset = 0
    frames_in_block = 0
    while offset < len(payload):
        chunk = payload[offset : offset + 7]
        pci = 0x20 | (seq & 0x0F)
        _send_frame(bus, resp_id, bytes([pci]) + chunk, is_extended_id=is_extended_id)
        offset += len(chunk)
        seq = (seq + 1) & 0x0F
        frames_in_block += 1
        if st_min_s > 0:
            time.sleep(st_min_s)
        if block_size and frames_in_block >= block_size and offset < len(payload):
            block_size, st_min_s = _await_flow_control(
                bus, req_id=req_id, timeout_s=timeout_s, is_extended_id=is_extended_id
            )
            frames_in_block = 0


def _isotp_send_response(
    bus: can.BusABC,
    *,
    req_id: int,
    resp_id: int,
    payload: bytes,
    timeout_s: float,
    is_extended_id: bool,
) -> None:
    length = len(payload)
    if length <= 7:
        _send_frame(bus, resp_id, bytes([length & 0x0F]) + payload, is_extended_id=is_extended_id)
        return
    if length > 0x0FFF:
        raise IsoTpError("payload too large")

    first = 0x10 | ((length >> 8) & 0x0F)
    second = length & 0xFF
    _send_frame(bus, resp_id, bytes([first, second]) + payload[:6], is_extended_id=is_extended_id)

    block_size, st_min_s = _await_flow_control(bus, req_id=req_id, timeout_s=timeout_s, is_extended_id=is_extended_id)
    _send_consecutive_frames(
        bus,
        resp_id=resp_id,
        payload=payload[6:],
        block_size=block_size,
        st_min_s=st_min_s,
        timeout_s=timeout_s,
        req_id=req_id,
        is_extended_id=is_extended_id,
    )


@dataclass
class EcuSimulator:
    ecu_int: int
    dtcs: list[tuple[str, str]]
    vin: str
    part_number: str
    rpm_reads: int = 0

    def ecu(self) -> str:
        return f"{self.ecu_int:02X}"

    def request_id(self, can_id_mode: str) -> int:
        if can_id_mode == "11bit":
            return 0x7E0 + (self.ecu_int & 0xFF)
        if can_id_mode == "29bit":
            tester_sa = 0xF1
            return 0x18DA0000 | ((self.ecu_int & 0xFF) << 8) | (tester_sa & 0xFF)
        raise ValueError("invalid can_id_mode")

    def response_id(self, can_id_mode: str) -> int:
        if can_id_mode == "11bit":
            return 0x7E8 + (self.ecu_int & 0xFF)
        if can_id_mode == "29bit":
            tester_sa = 0xF1
            return 0x18DA0000 | ((tester_sa & 0xFF) << 8) | (self.ecu_int & 0xFF)
        raise ValueError("invalid can_id_mode")

    def handle_uds(self, payload: bytes) -> bytes:
        if not payload:
            raise ValueError("empty request")
        sid = payload[0]

        if sid == 0x10:
            session_type = payload[1] if len(payload) > 1 else 0x01
            return bytes([0x50, session_type])

        if sid == 0x22:
            # ReadDataByIdentifier (DID). Keep behavior deterministic for golden tests:
            # - VIN and part number are constant per ECU
            # - RPM DID 0x1234 is scripted and advances only when 0x1234 is read
            if len(payload) < 3:
                return bytes([0x7F, sid, 0x13])  # incorrect message length or invalid format
            did = (payload[1] << 8) | payload[2]
            if did == 0xF190:
                data = self.vin.encode("ascii", errors="replace")
            elif did == 0xF187:
                data = self.part_number.encode("ascii", errors="replace")
            elif did == 0x1234:
                self.rpm_reads += 1
                # Produce a deterministic sequence: 850, 900, 950, ...
                rpm = 850 + ((self.rpm_reads - 1) * 50)
                data = int(rpm).to_bytes(2, byteorder="big", signed=False)
            else:
                return bytes([0x7F, sid, 0x31])  # request out of range
            return bytes([0x62, payload[1], payload[2]]) + data

        if sid == 0x19:
            if len(payload) < 2 or payload[1] != 0x02:
                return bytes([0x7F, sid, 0x12])
            status_mask = payload[2] if len(payload) > 2 else 0xFF
            out = bytearray([0x59, 0x02, status_mask])
            for code, status in self.dtcs:
                dtc_val = encode_dtc(code)
                out.append((dtc_val >> 8) & 0xFF)
                out.append(dtc_val & 0xFF)
                out.append(status_to_byte(status))
            return bytes(out)

        if sid == 0x14:
            self.dtcs = []
            return bytes([0x54])

        return bytes([0x7F, sid, 0x11])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="autosvc ECU simulator (SocketCAN/vcan)")
    parser.add_argument("--can", default="vcan0", help="SocketCAN interface (e.g. vcan0)")
    parser.add_argument("--can-id-mode", choices=["11bit", "29bit"], default="11bit")
    parser.add_argument("--ecu", action="append", help="ECU address as hex. May be passed multiple times.")
    args = parser.parse_args(argv)

    bus = can.interface.Bus(channel=args.can, interface="socketcan")
    is_extended_id = args.can_id_mode == "29bit"
    functional_id = 0x7DF if args.can_id_mode == "11bit" else 0x18DB33F1

    ecu_hexes = (args.ecu or []) + ["01", "03"]
    ecu_ints = sorted({int(e, 16) & 0xFF for e in ecu_hexes})
    ecus: list[EcuSimulator] = []
    for ecu_int in ecu_ints:
        # Keep ECU 01 deterministic for golden DTC tests.
        if ecu_int == 0x01:
            dtcs = [("P0300", "active"), ("P0171", "stored")]
        elif ecu_int == 0x03:
            dtcs = []
        else:
            dtcs = []
        vin = "WVWZZZ00000000001"
        part_number = f"AUTOSVC-ECU{ecu_int:02X}"
        ecus.append(EcuSimulator(ecu_int=ecu_int, dtcs=dtcs, vin=vin, part_number=part_number))

    request_map = {ecu.request_id(args.can_id_mode): ecu for ecu in ecus}

    ecu_list_str = ",".join([ecu.ecu() for ecu in ecus])
    print(
        f"autosvc ECU simulator listening on {args.can} (mode={args.can_id_mode}, ecus={ecu_list_str})",
        file=sys.stderr,
        flush=True,
    )
    try:
        while True:
            msg = _recv_frame(bus, timeout_s=1.0, is_extended_id=is_extended_id)
            if msg is None:
                continue
            can_id = int(msg.arbitration_id)
            req_payload = _decode_isotp_single_frame(bytes(msg.data))
            if req_payload is None:
                continue

            targets: list[EcuSimulator]
            if can_id == functional_id:
                targets = list(ecus)
            else:
                ecu = request_map.get(can_id)
                if ecu is None:
                    continue
                targets = [ecu]

            for target in targets:
                try:
                    resp = target.handle_uds(req_payload)
                except Exception:
                    resp = bytes([0x7F, req_payload[0], 0x11]) if req_payload else b""
                _isotp_send_response(
                    bus,
                    req_id=target.request_id(args.can_id_mode),
                    resp_id=target.response_id(args.can_id_mode),
                    payload=resp,
                    timeout_s=1.0,
                    is_extended_id=is_extended_id,
                )
    except KeyboardInterrupt:
        return None
    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
