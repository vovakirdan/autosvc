from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autosvc.backups import BackupStore
from autosvc.core.datasets.loader import load_longcoding_profiles
from autosvc.core.datasets.models import LongCodingFieldSpec, LongCodingProfile
from autosvc.core.uds.client import UdsClient, UdsError, UdsNegativeResponseError
from autosvc.core.uds.did import read_did as uds_read_did
from autosvc.core.uds.security import is_security_nrc


class LongCodingError(Exception):
    pass


@dataclass(frozen=True)
class LongCodingField:
    ecu: str
    key: str
    label: str
    kind: str
    risk: str
    did: int
    byte: int
    bit: int
    length: int
    notes: str
    needs_security_access: bool
    enum: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ecu": self.ecu,
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "risk": self.risk,
            "did": f"{int(self.did) & 0xFFFF:04X}",
            "byte": int(self.byte),
            "bit": int(self.bit),
            "len": int(self.length),
            "needs_security_access": bool(self.needs_security_access),
            "notes": self.notes,
        }
        if self.enum:
            out["enum"] = dict(self.enum)
        return out


class LongCodingManager:
    def __init__(
        self,
        uds: UdsClient,
        *,
        brand: str | None = None,
        datasets_dir: str | Path | None = None,
        backups: BackupStore | None = None,
        log_dir: str | Path | None = None,
    ) -> None:
        self._uds = uds
        self._profiles = load_longcoding_profiles(brand=brand, datasets_dir=datasets_dir)
        self._backups = backups or BackupStore()
        self._log_dir = Path(log_dir).expanduser() if log_dir is not None else None

    def list_fields(self, ecu: str) -> list[LongCodingField]:
        profile = self._profile_for_ecu(ecu)
        out: list[LongCodingField] = []
        for spec in profile.fields:
            out.append(self._field_from_spec(profile.ecu, spec, default_did=profile.did, default_length=profile.length))
        out.sort(key=lambda f: f.key)
        return out

    def read_field(self, ecu: str, key: str) -> dict[str, Any]:
        profile = self._profile_for_ecu(ecu)
        spec = self._spec_for_key(profile, key)
        did = _field_did(spec, default_did=profile.did)
        raw = self._read_did(profile.ecu, did)
        _require_length(raw, _field_length(spec, default_length=profile.length), did=did)
        value = _decode_field(spec, raw, default_did=profile.did, default_length=profile.length)
        out: dict[str, Any] = {
            "ecu": profile.ecu,
            "ecu_name": profile.ecu_name,
            "key": spec.key,
            "label": spec.label,
            "kind": spec.kind,
            "risk": spec.risk,
            "did": f"{did:04X}",
            "byte": spec.byte,
            "bit": spec.bit,
            "len": spec.length,
            "needs_security_access": bool(spec.needs_security_access),
            "notes": spec.notes,
            "raw": raw.hex().upper(),
            "value": value,
        }
        if spec.kind == "enum":
            out["value_label"] = _enum_label(spec, value)
        return out

    def backup_field(self, ecu: str, key: str, *, notes: str | None = None) -> dict[str, Any]:
        profile = self._profile_for_ecu(ecu)
        spec = self._spec_for_key(profile, key)
        did = _field_did(spec, default_did=profile.did)
        raw = self._read_did(profile.ecu, did)
        _require_length(raw, _field_length(spec, default_length=profile.length), did=did)
        rec = self._backups.create_snapshot_backup(
            ecu=profile.ecu,
            did=did,
            key=spec.key,
            raw=raw,
            notes=notes or spec.label,
            copy_to_log_dir=self._log_dir,
        )
        return {
            "backup_id": rec.backup_id,
            "ecu": profile.ecu,
            "ecu_name": profile.ecu_name,
            "key": spec.key,
            "label": spec.label,
            "did": f"{did:04X}",
            "raw": raw.hex().upper(),
            "value": _decode_field(spec, raw, default_did=profile.did, default_length=profile.length),
        }

    def write_field(self, ecu: str, key: str, value: str, *, mode: str) -> dict[str, Any]:
        profile = self._profile_for_ecu(ecu)
        spec = self._spec_for_key(profile, key)
        _enforce_mode(mode, spec.risk, dataset_key=spec.key)

        did = _field_did(spec, default_did=profile.did)
        old_raw = self._read_did(profile.ecu, did)
        expected_len = _field_length(spec, default_length=profile.length)
        _require_length(old_raw, expected_len, did=did)

        new_raw = bytearray(old_raw)
        new_value_int = _encode_field_value(spec, value)
        _set_bits(new_raw, spec.byte, spec.bit, spec.length, new_value_int)
        new_raw_b = bytes(new_raw)

        backup = self._backups.create_write_backup(
            ecu=profile.ecu,
            did=did,
            key=spec.key,
            old=old_raw,
            new=new_raw_b,
            notes=spec.label,
            copy_to_log_dir=self._log_dir,
        )

        self._write_did(profile.ecu, did, new_raw_b)
        readback = self._read_did(profile.ecu, did)
        _require_length(readback, expected_len, did=did)

        old_decoded = _decode_field(spec, old_raw, default_did=profile.did, default_length=profile.length)
        new_decoded = _decode_field(spec, readback, default_did=profile.did, default_length=profile.length)
        return {
            "backup_id": backup.backup_id,
            "ecu": profile.ecu,
            "ecu_name": profile.ecu_name,
            "key": spec.key,
            "label": spec.label,
            "kind": spec.kind,
            "risk": spec.risk,
            "mode": mode,
            "did": f"{did:04X}",
            "byte": spec.byte,
            "bit": spec.bit,
            "len": spec.length,
            "old": {"raw": old_raw.hex().upper(), "value": old_decoded},
            "new": {"raw": readback.hex().upper(), "value": new_decoded},
            "diff": {"changed": bool(old_raw != readback)},
        }

    def write_raw(self, ecu: str, did: int, hex_payload: str, *, mode: str) -> dict[str, Any]:
        if (mode or "").strip().lower() != "unsafe":
            raise LongCodingError("write-raw requires --mode unsafe")
        ecu_id = _normalize_ecu(ecu)
        did_int = int(did) & 0xFFFF
        new_raw = _parse_hex(hex_payload)
        old_raw = self._read_did(ecu_id, did_int)
        backup = self._backups.create_write_backup(
            ecu=ecu_id,
            did=did_int,
            key=None,
            old=old_raw,
            new=new_raw,
            notes="raw",
            copy_to_log_dir=self._log_dir,
        )
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
        if record.kind != "did_write" or not record.old_hex:
            raise LongCodingError("backup is not a write backup")
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

    def _profile_for_ecu(self, ecu: str) -> LongCodingProfile:
        ecu_id = _normalize_ecu(ecu)
        profile = self._profiles.get(ecu_id)
        if profile is None:
            raise LongCodingError(f"no long coding profile for ECU {ecu_id}")
        return profile

    def _spec_for_key(self, profile: LongCodingProfile, key: str) -> LongCodingFieldSpec:
        raw_key = (key or "").strip()
        if not raw_key:
            raise LongCodingError("key is required")
        for spec in profile.fields:
            if spec.key == raw_key:
                return spec
        raise LongCodingError(f"unknown field key '{raw_key}'")

    def _field_from_spec(
        self, ecu: str, spec: LongCodingFieldSpec, *, default_did: int, default_length: int
    ) -> LongCodingField:
        did = _field_did(spec, default_did=default_did)
        length = _field_length(spec, default_length=default_length)
        return LongCodingField(
            ecu=ecu,
            key=spec.key,
            label=spec.label,
            kind=spec.kind,
            risk=spec.risk,
            did=did,
            byte=spec.byte,
            bit=spec.bit,
            length=spec.length,
            notes=spec.notes,
            needs_security_access=bool(spec.needs_security_access),
            enum=spec.enum,
        )

    def _read_did(self, ecu: str, did: int) -> bytes:
        self._uds.set_ecu(ecu)
        try:
            return uds_read_did(self._uds, did)
        except Exception as exc:
            raise LongCodingError(str(exc)) from exc

    def _write_did(self, ecu: str, did: int, payload: bytes) -> None:
        self._uds.set_ecu(ecu)
        try:
            self._uds.write_did(did, payload)
        except UdsNegativeResponseError as exc:
            if is_security_nrc(exc.nrc):
                raise LongCodingError(
                    f"security access required for DID {int(did) & 0xFFFF:04X} (nrc=0x{exc.nrc:02X})"
                ) from exc
            raise LongCodingError(f"write failed (nrc=0x{exc.nrc:02X})") from exc
        except UdsError as exc:
            raise LongCodingError(str(exc)) from exc


def _enforce_mode(mode: str, risk: str, *, dataset_key: str) -> None:
    m = (mode or "").strip().lower()
    r = (risk or "").strip().lower()
    if m not in {"safe", "advanced", "unsafe"}:
        raise LongCodingError("invalid mode")
    if m == "safe":
        raise LongCodingError("safe mode is read-only (use --mode advanced or --mode unsafe)")
    if m == "advanced" and r not in {"safe", "risky"}:
        raise LongCodingError(f"field '{dataset_key}' is not allowed in advanced mode")


def _normalize_ecu(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise LongCodingError("ecu must be hex string")
    try:
        ecu_int = int(raw, 16)
    except Exception as exc:
        raise LongCodingError("ecu must be hex string") from exc
    if ecu_int < 0 or ecu_int > 0xFF:
        raise LongCodingError("ecu out of range")
    return f"{ecu_int:02X}"


def _parse_hex(value: str) -> bytes:
    raw = (value or "").strip()
    if raw.startswith("0x") or raw.startswith("0X"):
        raw = raw[2:]
    if not raw:
        return b""
    if len(raw) % 2 != 0:
        raise LongCodingError("hex payload must have even length")
    try:
        return bytes.fromhex(raw)
    except Exception as exc:
        raise LongCodingError("invalid hex payload") from exc


def _require_length(raw: bytes, expected: int, *, did: int) -> None:
    exp = int(expected)
    if exp <= 0:
        return
    if len(raw) != exp:
        raise LongCodingError(f"unexpected coding length for DID {int(did) & 0xFFFF:04X} (got {len(raw)}, expected {exp})")


def _field_did(spec: LongCodingFieldSpec, *, default_did: int) -> int:
    return int(spec.did) if spec.did is not None else int(default_did)


def _field_length(spec: LongCodingFieldSpec, *, default_length: int) -> int:
    return int(spec.coding_length) if spec.coding_length is not None else int(default_length)


def _get_bits(buf: bytes, byte: int, bit: int, length: int) -> int:
    b = int(byte)
    start = int(bit)
    nbits = int(length)
    if nbits <= 0:
        return 0
    if b < 0 or b >= len(buf):
        raise LongCodingError("byte index out of range")
    if start < 0 or start > 7:
        raise LongCodingError("bit must be 0..7")
    if start + nbits > 8:
        raise LongCodingError("field crosses byte boundary (not supported in v1)")
    mask = (1 << nbits) - 1
    return (buf[b] >> start) & mask


def _set_bits(buf: bytearray, byte: int, bit: int, length: int, value: int) -> None:
    b = int(byte)
    start = int(bit)
    nbits = int(length)
    if nbits <= 0:
        return
    if b < 0 or b >= len(buf):
        raise LongCodingError("byte index out of range")
    if start < 0 or start > 7:
        raise LongCodingError("bit must be 0..7")
    if start + nbits > 8:
        raise LongCodingError("field crosses byte boundary (not supported in v1)")
    mask = (1 << nbits) - 1
    v = int(value)
    if v < 0 or v > mask:
        raise LongCodingError("value out of range for bitfield")
    buf[b] = (buf[b] & ~(mask << start)) | ((v & mask) << start)


def _decode_field(spec: LongCodingFieldSpec, raw: bytes, *, default_did: int, default_length: int) -> Any:
    _ = _field_did(spec, default_did=default_did)
    _ = _field_length(spec, default_length=default_length)
    value_int = _get_bits(raw, spec.byte, spec.bit, spec.length)
    if spec.kind == "bool":
        return bool(value_int)
    if spec.kind in {"u8", "enum"}:
        return int(value_int)
    raise LongCodingError("invalid kind")


def _enum_label(spec: LongCodingFieldSpec, value: Any) -> str | None:
    if spec.kind != "enum" or not spec.enum:
        return None
    try:
        k = str(int(value))
    except Exception:
        return None
    return spec.enum.get(k)


def _encode_field_value(spec: LongCodingFieldSpec, value: str) -> int:
    raw = (value or "").strip()
    if spec.kind == "bool":
        v = raw.lower()
        if v in {"true", "1", "yes", "on"}:
            return 1
        if v in {"false", "0", "no", "off"}:
            return 0
        raise LongCodingError("invalid bool value (expected true/false/1/0)")
    if spec.kind == "enum":
        if spec.enum:
            if raw.isdigit() and raw in spec.enum:
                return int(raw)
            for k, v in spec.enum.items():
                if v.lower() == raw.lower():
                    return int(k)
        if raw.isdigit():
            return int(raw)
        raise LongCodingError("invalid enum value")
    if spec.kind == "u8":
        try:
            return int(raw, 10)
        except Exception as exc:
            raise LongCodingError("invalid u8 value") from exc
    raise LongCodingError("invalid kind")
