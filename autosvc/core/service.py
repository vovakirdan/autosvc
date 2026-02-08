from __future__ import annotations

from autosvc.core.dtc.decode import decode_dtcs
from autosvc.core.dtc.registry import get_modules
from autosvc.core.transport.base import CanTransport
from autosvc.core.uds.client import UdsClient
from autosvc.core.uds.did import decode_did, format_did, parse_did, read_did as _uds_read_did
from autosvc.core.uds.freeze_frame import FreezeFrameError, list_snapshot_identification, read_snapshot_record
from autosvc.core.vehicle.discovery import DiscoveryConfig
from autosvc.core.vehicle.discovery import scan_topology as _scan_topology
from autosvc.core.vehicle.topology import Topology


class DiagnosticService:
    """High-level diagnostic API used by all frontends (CLI/TUI/daemon)."""

    def __init__(
        self,
        transport: CanTransport,
        *,
        brand: str | None = None,
        can_interface: str = "unknown",
        can_id_mode: str = "11bit",
    ) -> None:
        self._transport = transport
        self._brand = brand
        self._can_interface = can_interface
        self._can_id_mode = can_id_mode
        self._uds = UdsClient(transport, can_id_mode=can_id_mode)

    def scan_ecus(self) -> list[str]:
        topo = self.scan_topology(DiscoveryConfig(can_id_mode=self._can_id_mode))
        return [node.ecu for node in topo.nodes]

    def scan_topology(self, config: DiscoveryConfig) -> Topology:
        topo = _scan_topology(self._transport, config, can_interface=self._can_interface)
        for node in topo.nodes:
            node.ecu_name = _resolve_ecu_name(node.ecu, self._brand)
        return topo

    def read_dtcs(self, ecu: str, *, with_freeze_frame: bool = False) -> list[dict[str, object]]:
        ecu_id = _normalize_ecu(ecu)
        dtcs = self._uds.read_dtcs(ecu_id)
        raw_dtcs = [dtc.raw_tuple() for dtc in dtcs]
        decoded = decode_dtcs(raw_dtcs, self._brand)
        ecu_name = _resolve_ecu_name(ecu_id, self._brand)
        for item in decoded:
            item["ecu"] = ecu_id
            item["ecu_name"] = ecu_name
        if with_freeze_frame:
            self._attach_freeze_frames(ecu_id, decoded)
        return decoded

    def clear_dtcs(self, ecu: str) -> None:
        ecu_id = _normalize_ecu(ecu)
        self._uds.clear_dtcs(ecu_id)

    def read_did(self, ecu: str, did: int) -> dict[str, object]:
        ecu_id = _normalize_ecu(ecu)
        did_int = parse_did(did)
        self._uds.set_ecu(ecu_id)
        data = _uds_read_did(self._uds, did_int)
        spec, value = decode_did(did_int, data)
        return {
            "ecu": ecu_id,
            "did": format_did(spec.did),
            "name": spec.name,
            "value": value,
            "unit": spec.unit,
        }

    def read_dids(self, ecu: str, dids: list[int]) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for did in dids:
            out.append(self.read_did(ecu, did))
        return out

    def _attach_freeze_frames(self, ecu: str, items: list[dict[str, object]]) -> None:
        # Freeze-frame is optional and ECU-dependent. Failure to retrieve it
        # should not make DTC reads fail.
        self._uds.set_ecu(ecu)
        try:
            snapshot_map = list_snapshot_identification(self._uds)
        except Exception:
            snapshot_map = {}
        for item in items:
            code = str(item.get("code") or "")
            record_id = snapshot_map.get(code)
            if record_id is None:
                item["freeze_frame"] = None
                continue
            try:
                ff = read_snapshot_record(self._uds, dtc=code, record_id=int(record_id))
            except FreezeFrameError:
                ff = None
            item["freeze_frame"] = ff.to_dict() if ff else None


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
    if ecu_int < 0 or ecu_int > 0xFF:
        raise ValueError("ecu out of range")
    return f"{ecu_int:02X}"


def _resolve_ecu_name(ecu: str, brand: str | None) -> str:
    for module in get_modules(brand):
        try:
            name = module.ecu_name(ecu)
        except Exception:
            name = None
        if name:
            return str(name)
    return "Unknown ECU"
