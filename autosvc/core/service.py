from __future__ import annotations

import logging
from pathlib import Path

from autosvc.core.dtc.decode import decode_dtcs
from autosvc.core.dtc.registry import get_modules
from autosvc.backups import BackupStore
from autosvc.core.transport.base import CanTransport
from autosvc.core.uds.client import UdsClient
from autosvc.core.uds.security_algo import SecurityAlgoError, load_security_algo
from autosvc.core.uds.adaptations import AdaptationsManager
from autosvc.core.uds.longcoding import LongCodingManager
from autosvc.core.uds.did import decode_did, format_did, parse_did, read_did as _uds_read_did
from autosvc.core.uds.freeze_frame import FreezeFrameError, list_snapshot_identification, read_snapshot_record
from autosvc.core.vehicle.discovery import DiscoveryConfig
from autosvc.core.vehicle.discovery import scan_topology as _scan_topology
from autosvc.core.vehicle.topology import Topology


log = logging.getLogger(__name__)


class DiagnosticService:
    """High-level diagnostic API used by all frontends (CLI/TUI/daemon)."""

    def __init__(
        self,
        transport: CanTransport,
        *,
        brand: str | None = None,
        can_interface: str = "unknown",
        can_id_mode: str = "11bit",
        datasets_dir: str | None = None,
        log_dir: str | None = None,
    ) -> None:
        self._transport = transport
        self._brand = brand
        self._can_interface = can_interface
        self._can_id_mode = can_id_mode
        self._datasets_dir = datasets_dir
        self._log_dir = log_dir
        self._uds = UdsClient(transport, can_id_mode=can_id_mode)
        self._adaptations: AdaptationsManager | None = None
        self._longcoding: LongCodingManager | None = None
        self._backups: BackupStore | None = None

    def scan_ecus(self) -> list[str]:
        log.info(
            "Scanning ECUs",
            extra={"can_interface": self._can_interface, "can_id_mode": self._can_id_mode, "brand": self._brand},
        )
        topo = self.scan_topology(DiscoveryConfig(can_id_mode=self._can_id_mode))
        return [node.ecu for node in topo.nodes]

    def scan_topology(self, config: DiscoveryConfig) -> Topology:
        log.info(
            "Scanning topology",
            extra={
                "can_interface": self._can_interface,
                "can_id_mode": config.can_id_mode,
                "addressing": config.addressing,
                "timeout_ms": config.timeout_ms,
                "retries": config.retries,
            },
        )
        topo = _scan_topology(self._transport, config, can_interface=self._can_interface)
        for node in topo.nodes:
            node.ecu_name = _resolve_ecu_name(node.ecu, self._brand)
        log.info("Topology scan complete", extra={"ecu_count": len(topo.nodes)})
        return topo

    def read_dtcs(self, ecu: str, *, with_freeze_frame: bool = False) -> list[dict[str, object]]:
        ecu_id = _normalize_ecu(ecu)
        log.info(
            "Read DTCs",
            extra={
                "ecu": ecu_id,
                "can_interface": self._can_interface,
                "can_id_mode": self._can_id_mode,
                "with_freeze_frame": bool(with_freeze_frame),
            },
        )
        dtcs = self._uds.read_dtcs(ecu_id)
        raw_dtcs = [dtc.raw_tuple() for dtc in dtcs]
        decoded = decode_dtcs(raw_dtcs, self._brand)
        ecu_name = _resolve_ecu_name(ecu_id, self._brand)
        for item in decoded:
            item["ecu"] = ecu_id
            item["ecu_name"] = ecu_name
        if with_freeze_frame:
            self._attach_freeze_frames(ecu_id, decoded)
        log.info("Read DTCs complete", extra={"ecu": ecu_id, "dtc_count": len(decoded)})
        return decoded

    def clear_dtcs(self, ecu: str) -> None:
        ecu_id = _normalize_ecu(ecu)
        log.info("Clear DTCs", extra={"ecu": ecu_id, "can_interface": self._can_interface})
        self._uds.clear_dtcs(ecu_id)
        log.info("Clear DTCs complete", extra={"ecu": ecu_id})

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

    # SecurityAccess (0x27)
    def security_request_seed(self, ecu: str, level: int) -> dict[str, object]:
        ecu_id = _normalize_ecu(ecu)
        lvl = int(level) & 0xFF
        self._uds.set_ecu(ecu_id)
        seed = self._uds.security_access_request_seed(lvl)
        return {"ecu": ecu_id, "level": f"0x{lvl:02X}", "seed_hex": seed.hex().upper()}

    def security_unlock(
        self,
        ecu: str,
        seed_level: int,
        *,
        key_hex: str | None = None,
        algo_module: str | None = None,
    ) -> dict[str, object]:
        """Generic SecurityAccess unlock flow.

        - Requests seed with sub-function `seed_level` (typically odd).
        - Sends key with sub-function `seed_level + 1`.

        autosvc does NOT ship any OEM algorithms.
        """

        ecu_id = _normalize_ecu(ecu)
        seed_lvl = int(seed_level) & 0xFF
        key_lvl = (seed_lvl + 1) & 0xFF

        self._uds.set_ecu(ecu_id)
        seed = self._uds.security_access_request_seed(seed_lvl)

        used_algo = False
        if key_hex is None:
            algo = load_security_algo(algo_module)
            if algo is None:
                raise ValueError("key is required (pass key_hex or configure AUTOSVC_SECURITY_ALGO)")
            try:
                key = algo.compute_key(seed, level=seed_lvl, ecu=ecu_id)
            except SecurityAlgoError as exc:
                raise ValueError(str(exc)) from exc
            used_algo = True
        else:
            key = _parse_hex_bytes(key_hex)

        self._uds.security_access_send_key(key_lvl, key)

        return {
            "ecu": ecu_id,
            "seed_level": f"0x{seed_lvl:02X}",
            "key_level": f"0x{key_lvl:02X}",
            "seed_hex": seed.hex().upper(),
            "key_len": len(key),
            "used_algo": bool(used_algo),
        }

    # Adaptations (safe ECU configuration changes) are implemented via
    # dataset-driven profiles and explicit backup/revert safety mechanisms.
    def list_adaptations(self, ecu: str) -> list[dict[str, object]]:
        mgr = self._adaptations_manager()
        return [s.to_dict() for s in mgr.list_settings(ecu)]

    def read_adaptation(self, ecu: str, key: str) -> dict[str, object]:
        mgr = self._adaptations_manager()
        return dict(mgr.read_setting(ecu, key))

    def write_adaptation(
        self,
        ecu: str,
        key: str,
        value: str,
        *,
        mode: str,
        unsafe_password: str | None = None,
        security_level: int | None = None,
        security_key_hex: str | None = None,
        security_algo_module: str | None = None,
    ) -> dict[str, object]:
        if str(mode).strip().lower() == "unsafe":
            from autosvc.unsafe import require_password

            if unsafe_password is None:
                raise ValueError("unsafe password is required")
            require_password(unsafe_password)
        ecu_id = _normalize_ecu(ecu)
        if security_level is not None:
            self.security_unlock(
                ecu_id,
                int(security_level),
                key_hex=security_key_hex,
                algo_module=security_algo_module,
            )
        mgr = self._adaptations_manager()
        return dict(mgr.write_setting(ecu_id, key, value, mode=mode))

    def write_adaptation_raw(
        self,
        ecu: str,
        did: int,
        hex_payload: str,
        *,
        mode: str,
        unsafe_password: str | None = None,
        security_level: int | None = None,
        security_key_hex: str | None = None,
        security_algo_module: str | None = None,
    ) -> dict[str, object]:
        if str(mode).strip().lower() == "unsafe":
            from autosvc.unsafe import require_password

            if unsafe_password is None:
                raise ValueError("unsafe password is required")
            require_password(unsafe_password)
        ecu_id = _normalize_ecu(ecu)
        if security_level is not None:
            self.security_unlock(
                ecu_id,
                int(security_level),
                key_hex=security_key_hex,
                algo_module=security_algo_module,
            )
        mgr = self._adaptations_manager()
        return dict(mgr.write_raw(ecu_id, did, hex_payload, mode=mode))

    def backup_did(self, ecu: str, did: int, *, notes: str | None = None) -> dict[str, object]:
        ecu_id = _normalize_ecu(ecu)
        did_int = int(did) & 0xFFFF
        raw = self._uds_read_did(ecu_id, did_int)
        store = self._backup_store()
        rec = store.create_snapshot_backup(
            ecu=ecu_id,
            did=did_int,
            key=None,
            raw=raw,
            notes=notes,
            copy_to_log_dir=Path(self._log_dir).expanduser() if self._log_dir else None,
        )
        return {"backup_id": rec.backup_id, "ecu": ecu_id, "did": f"{did_int:04X}", "raw": raw.hex().upper()}

    def backup_adaptation(self, ecu: str, key: str, *, notes: str | None = None) -> dict[str, object]:
        mgr = self._adaptations_manager()
        return dict(mgr.backup_setting(ecu, key, notes=notes))

    def revert_adaptation(self, backup_id: str) -> dict[str, object]:
        mgr = self._adaptations_manager()
        return dict(mgr.revert(backup_id))

    # Long coding (dataset-driven bitfields).
    def list_coding_fields(self, ecu: str) -> list[dict[str, object]]:
        mgr = self._longcoding_manager()
        return [f.to_dict() for f in mgr.list_fields(ecu)]

    def read_coding_field(self, ecu: str, key: str) -> dict[str, object]:
        mgr = self._longcoding_manager()
        return dict(mgr.read_field(ecu, key))

    def write_coding_field(
        self,
        ecu: str,
        key: str,
        value: str,
        *,
        mode: str,
        unsafe_password: str | None = None,
        security_level: int | None = None,
        security_key_hex: str | None = None,
        security_algo_module: str | None = None,
    ) -> dict[str, object]:
        if str(mode).strip().lower() == "unsafe":
            from autosvc.unsafe import require_password

            if unsafe_password is None:
                raise ValueError("unsafe password is required")
            require_password(unsafe_password)
        ecu_id = _normalize_ecu(ecu)
        if security_level is not None:
            self.security_unlock(
                ecu_id,
                int(security_level),
                key_hex=security_key_hex,
                algo_module=security_algo_module,
            )
        mgr = self._longcoding_manager()
        return dict(mgr.write_field(ecu_id, key, value, mode=mode))

    def write_coding_raw(
        self,
        ecu: str,
        did: int,
        hex_payload: str,
        *,
        mode: str,
        unsafe_password: str | None = None,
        security_level: int | None = None,
        security_key_hex: str | None = None,
        security_algo_module: str | None = None,
    ) -> dict[str, object]:
        if str(mode).strip().lower() == "unsafe":
            from autosvc.unsafe import require_password

            if unsafe_password is None:
                raise ValueError("unsafe password is required")
            require_password(unsafe_password)
        ecu_id = _normalize_ecu(ecu)
        if security_level is not None:
            self.security_unlock(
                ecu_id,
                int(security_level),
                key_hex=security_key_hex,
                algo_module=security_algo_module,
            )
        mgr = self._longcoding_manager()
        return dict(mgr.write_raw(ecu_id, did, hex_payload, mode=mode))

    def backup_coding_field(self, ecu: str, key: str, *, notes: str | None = None) -> dict[str, object]:
        mgr = self._longcoding_manager()
        return dict(mgr.backup_field(ecu, key, notes=notes))

    def revert_coding(self, backup_id: str) -> dict[str, object]:
        mgr = self._longcoding_manager()
        return dict(mgr.revert(backup_id))

    def _backup_store(self) -> BackupStore:
        if self._backups is None:
            self._backups = BackupStore()
        return self._backups

    def _uds_read_did(self, ecu: str, did: int) -> bytes:
        self._uds.set_ecu(ecu)
        return _uds_read_did(self._uds, int(did) & 0xFFFF)

    def _adaptations_manager(self) -> AdaptationsManager:
        if self._adaptations is None:
            # Brand selection is shared with the rest of the core:
            # - explicit `brand=` constructor parameter, OR
            # - AUTOSVC_BRAND env var (if brand is None)
            self._adaptations = AdaptationsManager(
                self._uds,
                brand=self._brand,
                datasets_dir=self._datasets_dir,
                backups=self._backup_store(),
                log_dir=self._log_dir,
            )
        return self._adaptations

    def _longcoding_manager(self) -> LongCodingManager:
        if self._longcoding is None:
            self._longcoding = LongCodingManager(
                self._uds,
                brand=self._brand,
                datasets_dir=self._datasets_dir,
                backups=self._backup_store(),
                log_dir=self._log_dir,
            )
        return self._longcoding

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


def _parse_hex_bytes(value: str) -> bytes:
    raw = (value or "").strip()
    if raw.startswith("0x") or raw.startswith("0X"):
        raw = raw[2:]
    if not raw:
        return b""
    if len(raw) % 2 != 0:
        raise ValueError("hex must have even length")
    try:
        return bytes.fromhex(raw)
    except Exception as exc:
        raise ValueError("invalid hex") from exc


def _resolve_ecu_name(ecu: str, brand: str | None) -> str:
    for module in get_modules(brand):
        try:
            name = module.ecu_name(ecu)
        except Exception:
            name = None
        if name:
            return str(name)
    return "Unknown ECU"
