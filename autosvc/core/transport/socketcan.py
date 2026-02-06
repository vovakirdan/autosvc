from __future__ import annotations

import can

from autosvc.core.transport.base import CanFrame, CanTransport


class SocketCanTransport(CanTransport):
    def __init__(self, channel: str = "vcan0", *, is_extended_id: bool = False) -> None:
        self.channel = channel
        self._is_extended_id = bool(is_extended_id)
        self._bus = can.interface.Bus(channel=channel, interface="socketcan")

    def send(self, can_id: int, data: bytes) -> None:
        msg = can.Message(arbitration_id=can_id, data=data, is_extended_id=self._is_extended_id)
        self._bus.send(msg)

    def recv(self, timeout_ms: int) -> CanFrame | None:
        msg = self._bus.recv(timeout_ms / 1000.0)
        if msg is None:
            return None
        return CanFrame(can_id=msg.arbitration_id, data=bytes(msg.data))

    def close(self) -> None:
        self._bus.shutdown()
