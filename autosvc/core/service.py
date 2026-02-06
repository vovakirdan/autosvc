from __future__ import annotations

from autosvc.core.dtc.decode import decode_dtcs
from autosvc.core.transport.base import CanTransport
from autosvc.core.uds.client import UdsClient


class DiagnosticService:
    """High-level diagnostic API used by all frontends (CLI/TUI/daemon)."""

    def __init__(self, transport: CanTransport, *, brand: str | None = None) -> None:
        self._transport = transport
        self._brand = brand
        self._uds = UdsClient(transport)

    def scan_ecus(self) -> list[str]:
        found: list[str] = []
        for ecu in range(1, 0x10):
            ecu_id = f"{ecu:02X}"
            try:
                if self._uds.diagnostic_session_control(ecu_id):
                    found.append(ecu_id)
            except Exception:
                continue
        return found

    def read_dtcs(self, ecu: str) -> list[dict[str, object]]:
        ecu_id = _normalize_ecu(ecu)
        dtcs = self._uds.read_dtcs(ecu_id)
        raw_dtcs = [dtc.raw_tuple() for dtc in dtcs]
        decoded = decode_dtcs(raw_dtcs, self._brand)
        return decoded

    def clear_dtcs(self, ecu: str) -> None:
        ecu_id = _normalize_ecu(ecu)
        self._uds.clear_dtcs(ecu_id)


def _normalize_ecu(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("ecu must be hex string")
    raw = value.strip()
    if not raw:
        raise ValueError("ecu must be hex string")
    try:
        ecu_int = int(raw, 16)
    except ValueError as exc:
        raise ValueError("ecu must be hex string") from exc
    if ecu_int < 0 or ecu_int > 0x7F:
        raise ValueError("ecu out of range")
    return f"{ecu_int:02X}"
