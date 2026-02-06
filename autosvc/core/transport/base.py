from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class CanFrame:
    can_id: int
    data: bytes


class CanTransport(ABC):
    """Minimal CAN transport interface.

    The core uses this to stay client-agnostic. Concrete transports can be:
    - SocketCAN (real hardware / vcan)
    - mock (in-memory)
    - recorder/replay wrappers
    """

    @abstractmethod
    def send(self, can_id: int, data: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    def recv(self, timeout_ms: int) -> CanFrame | None:
        raise NotImplementedError

    def close(self) -> None:
        return None

