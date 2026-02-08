from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autosvc.core.datasets.loader import load_adaptations_profile
from autosvc.core.datasets.models import AdaptSettingSpec, AdaptationsProfile
from autosvc.core.safety.backups import BackupStore
from autosvc.core.uds.client import UdsClient, UdsError, UdsNegativeResponseError
from autosvc.core.uds.did import read_did as uds_read_did
from autosvc.core.uds.security import is_security_nrc


class AdaptationsError(Exception):
    pass


@dataclass(frozen=True)
class AdaptSetting:
    ecu: str
    key: str
    label: str
    kind: str
    did: int
    risk: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ecu": self.ecu,
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "did": f"{int(self.did) & 0xFFFF:04X}",
            "risk": self.risk,
            "notes": self.notes,
        }


class AdaptationsManager:
    def __init__(
        self,
        uds: UdsClient,
        *,
        brand: str | None = None,
        datasets_dir: str | Path | None = None,
        backups: BackupStore | None = None,
    ) -> None:
        self._uds = uds
        self._profiles = load_adaptations_profile(brand=brand, datasets_dir=datasets_dir)
        self._backups = backups or BackupStore()

    def list_settings(self, ecu: str) -> list[AdaptSetting]:
        profile = self._profile_for_ecu(ecu)
        out: list[AdaptSetting] = []
        for spec in profile.settings:
            out.append(self._setting_from_spec(profile.ecu, spec))
        out.sort(key=lambda s: s.key)
        return out

    def read_setting(self, ecu: str, key: str) -> dict[str, Any]:
        profile = self._profile_for_ecu(ecu)
        spec = self._spec_for_key(profile, key)
        did = int(spec.read.id, 16) & 0xFFFF
        raw = self._read_did(profile.ecu, did)
        value = _decode_value(spec, raw)
        out: dict[str, Any] = {
            "ecu": profile.ecu,
            "ecu_name": profile.ecu_name,
            "key": spec.key,
            "label": spec.label,
            "kind": spec.kind,
            "did": f"{did:04X}",
            "risk": spec.risk,
            "notes": spec.notes,
            "raw": raw.hex().upper(),
            "value": value,
        }
        if spec.kind == "enum":
            out["value_label"] = _enum_label(spec, raw)
        return out

    def write_setting(self, ecu: str, key: str, value: str, *, mode: str) -> dict[str, Any]:
        profile = self._profile_for_ecu(ecu)
        spec = self._spec_for_key(profile, key)
        _enforce_mode(mode, spec.risk, dataset_key=spec.key)
        did = int(spec.write.id, 16) & 0xFFFF

        old_raw = self._read_did(profile.ecu, did)
        new_raw = _encode_value(spec, value)
        backup = self._backups.create_backup(
            ecu=profile.ecu,
            did=did,
            key=spec.key,
            old=old_raw,
            new=new_raw,
            notes=spec.label,
        )

        self._write_did(profile.ecu, did, new_raw)
        readback = self._read_did(profile.ecu, did)

        return {
            "backup_id": backup.backup_id,
            "ecu": profile.ecu,
            "ecu_name": profile.ecu_name,
            "key": spec.key,
            "label": spec.label,
            "kind": spec.kind,
            "did": f"{did:04X}",
            "risk": spec.risk,
            "mode": mode,
            "old": {"raw": old_raw.hex().upper(), "value": _decode_value(spec, old_raw)},
            "new": {"raw": readback.hex().upper(), "value": _decode_value(spec, readback)},
        }

    def write_raw(self, ecu: str, did: int, hex_payload: str, *, mode: str) -> dict[str, Any]:
        if mode != "unsafe":
            raise AdaptationsError("write-raw requires --mode unsafe")
        ecu_id = _normalize_ecu(ecu)
        did_int = int(did) & 0xFFFF
        new_raw = _parse_hex(hex_payload)
        old_raw = self._read_did(ecu_id, did_int)
        backup = self._backups.create_backup(ecu=ecu_id, did=did_int, key=None, old=old_raw, new=new_raw, notes="raw")
        self._write_did(ecu_id, did_int, new_raw)
        readback = self._read_did(ecu_id, did_int)
        return {
            "backup_id": backup.backup_id,
            "ecu": ecu_id,
            "key": None,
            "did": f"{did_int:04X}",
            "mode": mode,
            "old_hex": old_raw.hex().upper(),
            "new_hex": readback.hex().upper(),
        }

    def revert(self, backup_id: str) -> dict[str, Any]:
        record = self._backups.load(backup_id)
        old = _parse_hex(record.old_hex)
        self._write_did(record.ecu, record.did, old)
        readback = self._read_did(record.ecu, record.did)
        return {
            "backup_id": record.backup_id,
            "ecu": record.ecu,
            "key": record.key,
            "did": f"{int(record.did) & 0xFFFF:04X}",
            "restored_hex": readback.hex().upper(),
        }

    def _profile_for_ecu(self, ecu: str) -> AdaptationsProfile:
        ecu_id = _normalize_ecu(ecu)
        profile = self._profiles.get(ecu_id)
        if profile is None:
            raise AdaptationsError(f"no adaptations profile for ECU {ecu_id}")
        return profile

    def _spec_for_key(self, profile: AdaptationsProfile, key: str) -> AdaptSettingSpec:
        raw_key = (key or "").strip()
        if not raw_key:
            raise AdaptationsError("key is required")
        for spec in profile.settings:
            if spec.key == raw_key:
                return spec
        raise AdaptationsError(f"unknown setting key '{raw_key}'")

    def _setting_from_spec(self, ecu: str, spec: AdaptSettingSpec) -> AdaptSetting:
        did = int(spec.read.id, 16) & 0xFFFF
        return AdaptSetting(
            ecu=ecu,
            key=spec.key,
            label=spec.label,
            kind=str(spec.kind),
            did=did,
            risk=str(spec.risk),
            notes=spec.notes,
        )

    def _read_did(self, ecu: str, did: int) -> bytes:
        self._uds.set_ecu(ecu)
        try:
            return uds_read_did(self._uds, did)
        except Exception as exc:
            raise AdaptationsError(str(exc)) from exc

    def _write_did(self, ecu: str, did: int, payload: bytes) -> None:
        self._uds.set_ecu(ecu)
        try:
            self._uds.write_did(did, payload)
        except UdsNegativeResponseError as exc:
            if is_security_nrc(exc.nrc):
                raise AdaptationsError(
                    f"security access required for DID {int(did) & 0xFFFF:04X} (nrc=0x{exc.nrc:02X})"
                ) from exc
            raise AdaptationsError(f"write failed (nrc=0x{exc.nrc:02X})") from exc
        except UdsError as exc:
            raise AdaptationsError(str(exc)) from exc


def _enforce_mode(mode: str, risk: str, *, dataset_key: str) -> None:
    m = (mode or "").strip().lower()
    r = (risk or "").strip().lower()
    if m not in {"safe", "advanced", "unsafe"}:
        raise AdaptationsError("invalid mode")
    if m == "safe" and r != "safe":
        raise AdaptationsError(f"setting '{dataset_key}' is not allowed in safe mode")
    if m == "advanced" and r not in {"safe", "risky"}:
        raise AdaptationsError(f"setting '{dataset_key}' is not allowed in advanced mode")


def _normalize_ecu(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise AdaptationsError("ecu must be hex string")
    try:
        ecu_int = int(raw, 16)
    except Exception as exc:
        raise AdaptationsError("ecu must be hex string") from exc
    if ecu_int < 0 or ecu_int > 0xFF:
        raise AdaptationsError("ecu out of range")
    return f"{ecu_int:02X}"


def _parse_hex(value: str) -> bytes:
    raw = (value or "").strip()
    if raw.startswith("0x") or raw.startswith("0X"):
        raw = raw[2:]
    if not raw:
        return b""
    if len(raw) % 2 != 0:
        raise AdaptationsError("hex payload must have even length")
    try:
        return bytes.fromhex(raw)
    except Exception as exc:
        raise AdaptationsError("invalid hex payload") from exc


def _decode_value(spec: AdaptSettingSpec, raw: bytes) -> Any:
    if spec.kind == "bool":
        return bool(raw[:1] == b"\x01")
    if spec.kind == "u8":
        if len(raw) < 1:
            raise AdaptationsError("short u8 value")
        return int(raw[0]) & 0xFF
    if spec.kind == "u16":
        if len(raw) < 2:
            raise AdaptationsError("short u16 value")
        return int.from_bytes(raw[:2], byteorder="big", signed=False)
    if spec.kind == "i16":
        if len(raw) < 2:
            raise AdaptationsError("short i16 value")
        return int.from_bytes(raw[:2], byteorder="big", signed=True)
    if spec.kind == "bytes":
        return raw.hex().upper()
    if spec.kind == "enum":
        if len(raw) < 1:
            raise AdaptationsError("short enum value")
        return int(raw[0]) & 0xFF
    raise AdaptationsError("invalid kind")


def _enum_label(spec: AdaptSettingSpec, raw: bytes) -> str | None:
    if spec.kind != "enum" or not spec.enum:
        return None
    if not raw:
        return None
    key = str(int(raw[0]) & 0xFF)
    return spec.enum.get(key)


def _encode_value(spec: AdaptSettingSpec, value: str) -> bytes:
    raw = (value or "").strip()
    if spec.kind == "bool":
        v = raw.lower()
        if v in {"true", "1"}:
            return b"\x01"
        if v in {"false", "0"}:
            return b"\x00"
        raise AdaptationsError("invalid bool value (expected true/false/1/0)")
    if spec.kind == "u8":
        try:
            n = int(raw, 10)
        except Exception as exc:
            raise AdaptationsError("invalid u8 value") from exc
        if n < 0 or n > 0xFF:
            raise AdaptationsError("u8 out of range")
        return bytes([n & 0xFF])
    if spec.kind == "u16":
        try:
            n = int(raw, 10)
        except Exception as exc:
            raise AdaptationsError("invalid u16 value") from exc
        if n < 0 or n > 0xFFFF:
            raise AdaptationsError("u16 out of range")
        return int(n).to_bytes(2, byteorder="big", signed=False)
    if spec.kind == "i16":
        try:
            n = int(raw, 10)
        except Exception as exc:
            raise AdaptationsError("invalid i16 value") from exc
        if n < -32768 or n > 32767:
            raise AdaptationsError("i16 out of range")
        return int(n).to_bytes(2, byteorder="big", signed=True)
    if spec.kind == "bytes":
        return _parse_hex(raw)
    if spec.kind == "enum":
        if spec.enum:
            # Accept either a numeric value or an enum label.
            if raw.isdigit() and raw in spec.enum:
                return bytes([int(raw) & 0xFF])
            for k, v in spec.enum.items():
                if v.lower() == raw.lower():
                    return bytes([int(k) & 0xFF])
        try:
            n = int(raw, 10)
        except Exception as exc:
            raise AdaptationsError("invalid enum value") from exc
        if n < 0 or n > 0xFF:
            raise AdaptationsError("enum out of range")
        return bytes([n & 0xFF])
    raise AdaptationsError("invalid kind")
