from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CanFrame:
    can_id: int
    data: bytes


class CanTransport(ABC):
    @abstractmethod
    def send(self, can_id: int, data: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    def recv(self, timeout_ms: int) -> Optional[CanFrame]:
        raise NotImplementedError

    def close(self) -> None:
        return None
