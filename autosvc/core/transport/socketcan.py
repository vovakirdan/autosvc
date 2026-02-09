from __future__ import annotations

import logging

import can

from autosvc.core.transport.base import CanFrame, CanTransport


log = logging.getLogger(__name__)


class SocketCanTransport(CanTransport):
    def __init__(self, channel: str = "vcan0", *, is_extended_id: bool = False) -> None:
        self.channel = channel
        self._is_extended_id = bool(is_extended_id)
        self._bus = can.interface.Bus(channel=channel, interface="socketcan")

    def send(self, can_id: int, data: bytes) -> None:
        if log.isEnabledFor(5):
            log.trace(
                "SocketCAN TX",
                extra={"can_interface": self.channel, "can_id": f"0x{int(can_id):X}", "data_hex": (data or b"").hex()},
            )
        msg = can.Message(arbitration_id=can_id, data=data, is_extended_id=self._is_extended_id)
        self._bus.send(msg)

    def recv(self, timeout_ms: int) -> CanFrame | None:
        msg = self._bus.recv(timeout_ms / 1000.0)
        if msg is None:
            return None
        frame = CanFrame(can_id=msg.arbitration_id, data=bytes(msg.data))
        if log.isEnabledFor(5):
            log.trace(
                "SocketCAN RX",
                extra={"can_interface": self.channel, "can_id": f"0x{int(frame.can_id):X}", "data_hex": frame.data.hex()},
            )
        return frame

    def close(self) -> None:
        self._bus.shutdown()
