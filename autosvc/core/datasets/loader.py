from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from autosvc.core.datasets.models import AdaptRwRef, AdaptationsProfile, AdaptKind, AdaptRisk, AdaptSettingSpec, DatasetManifest


class DatasetError(Exception):
    pass


def load_manifest(pack_dir: Path) -> DatasetManifest:
    path = pack_dir / "manifest.json"
    obj = _read_json(path)
    _require_keys(path, obj, required={"brand", "version", "type"}, optional={"notes"})
    brand = _require_str(path, obj, "brand").strip().lower()
    version = _require_str(path, obj, "version").strip()
    typ = _require_str(path, obj, "type").strip()
    notes = obj.get("notes")
    return DatasetManifest(
        brand=brand,
        version=version,
        type=typ,
        notes=str(notes) if isinstance(notes, str) and notes else None,
    )


def load_adaptations_profile(*, brand: str | None = None, datasets_dir: str | Path | None = None) -> dict[str, AdaptationsProfile]:
    brand_name = (brand or os.getenv("AUTOSVC_BRAND", "")).strip().lower()
    if not brand_name:
        raise DatasetError("brand is required (set AUTOSVC_BRAND or pass --brand)")
    root = _datasets_root(datasets_dir)
    pack_dir = root / brand_name
    if not pack_dir.exists():
        raise DatasetError(f"dataset pack not found for brand '{brand_name}' in {root}")
    manifest = load_manifest(pack_dir)
    if manifest.brand != brand_name:
        raise DatasetError("dataset manifest brand mismatch")
    if manifest.type != "datasets":
        raise DatasetError("dataset manifest type mismatch")

    adapts_dir = pack_dir / "adaptations"
    if not adapts_dir.exists():
        raise DatasetError("adaptations directory not found in dataset pack")

    profiles: dict[str, AdaptationsProfile] = {}
    for path in sorted(adapts_dir.glob("*.json")):
        if path.name == "manifest.json":
            continue
        profile = _load_adapt_profile_file(path)
        profiles[profile.ecu] = profile
    return profiles


def _datasets_root(datasets_dir: str | Path | None) -> Path:
    if datasets_dir is not None:
        return Path(datasets_dir).expanduser()
    env = (os.getenv("AUTOSVC_DATASETS_DIR", "") or "").strip()
    if env:
        return Path(env).expanduser()

    # Default: try CWD datasets/, then repo-root datasets/ (when running from source).
    cwd = Path.cwd() / "datasets"
    if cwd.exists():
        return cwd
    try:
        repo_guess = Path(__file__).resolve().parents[4] / "datasets"
        if repo_guess.exists():
            return repo_guess
    except Exception:
        pass
    return cwd  # for error messages


def _load_adapt_profile_file(path: Path) -> AdaptationsProfile:
    obj = _read_json(path)
    _require_keys(path, obj, required={"ecu", "ecu_name", "settings"}, optional=set())
    ecu = _require_str(path, obj, "ecu").strip().upper()
    if len(ecu) != 2 or not _is_hex(ecu):
        raise DatasetError(f"{path}: invalid ecu (expected 2-hex like '09')")
    ecu_name = _require_str(path, obj, "ecu_name").strip()

    settings_raw = obj.get("settings")
    if not isinstance(settings_raw, list):
        raise DatasetError(f"{path}: settings must be a list")
    settings: list[AdaptSettingSpec] = []
    for idx, item in enumerate(settings_raw):
        if not isinstance(item, dict):
            raise DatasetError(f"{path}: settings[{idx}] must be an object")
        settings.append(_parse_setting(path, idx, item))
    settings.sort(key=lambda s: s.key)
    return AdaptationsProfile(ecu=ecu, ecu_name=ecu_name, settings=settings)


def _parse_setting(path: Path, idx: int, obj: dict[str, Any]) -> AdaptSettingSpec:
    required = {"key", "label", "kind", "read", "write", "risk", "notes"}
    optional = {"enum"}
    _require_keys(path, obj, required=required, optional=optional, prefix=f"settings[{idx}]")

    key = _require_str(path, obj, "key", prefix=f"settings[{idx}]").strip()
    if not key or " " in key:
        raise DatasetError(f"{path}: settings[{idx}].key must be a non-empty identifier")
    label = _require_str(path, obj, "label", prefix=f"settings[{idx}]").strip()
    kind_raw = _require_str(path, obj, "kind", prefix=f"settings[{idx}]").strip().lower()
    if kind_raw not in {"bool", "u8", "u16", "i16", "enum", "bytes"}:
        raise DatasetError(f"{path}: settings[{idx}].kind is invalid")
    kind: AdaptKind = kind_raw  # type: ignore[assignment]

    risk_raw = _require_str(path, obj, "risk", prefix=f"settings[{idx}]").strip().lower()
    if risk_raw not in {"safe", "risky", "unsafe"}:
        raise DatasetError(f"{path}: settings[{idx}].risk is invalid")
    risk: AdaptRisk = risk_raw  # type: ignore[assignment]

    notes = _require_str(path, obj, "notes", prefix=f"settings[{idx}]")
    read = _parse_rw_ref(path, obj.get("read"), f"settings[{idx}].read")
    write = _parse_rw_ref(path, obj.get("write"), f"settings[{idx}].write")

    enum_map = None
    if kind == "enum":
        raw_enum = obj.get("enum")
        if not isinstance(raw_enum, dict) or not raw_enum:
            raise DatasetError(f"{path}: settings[{idx}].enum must be a non-empty object for enum kind")
        enum_map = {}
        for k, v in raw_enum.items():
            if not isinstance(k, str) or not k.strip().isdigit():
                raise DatasetError(f"{path}: settings[{idx}].enum keys must be decimal strings")
            if not isinstance(v, str) or not v.strip():
                raise DatasetError(f"{path}: settings[{idx}].enum values must be strings")
            enum_map[k.strip()] = v.strip()

    return AdaptSettingSpec(
        key=key,
        label=label,
        kind=kind,
        read=read,
        write=write,
        risk=risk,
        notes=notes,
        enum=enum_map,
    )


def _parse_rw_ref(path: Path, raw: Any, field: str) -> AdaptRwRef:
    if not isinstance(raw, dict):
        raise DatasetError(f"{path}: {field} must be an object")
    _require_keys(path, raw, required={"service", "id"}, optional=set(), prefix=field)
    service = _require_str(path, raw, "service", prefix=field).strip().lower()
    if service != "did":
        raise DatasetError(f"{path}: {field}.service must be 'did'")
    did = _require_str(path, raw, "id", prefix=field).strip().upper()
    if len(did) != 4 or not _is_hex(did):
        raise DatasetError(f"{path}: {field}.id must be a 4-hex DID string")
    return AdaptRwRef(service=service, id=did)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DatasetError(f"{path}: file not found") from exc
    except Exception as exc:
        raise DatasetError(f"{path}: failed to read") from exc
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DatasetError(f"{path}: invalid json") from exc
    if not isinstance(obj, dict):
        raise DatasetError(f"{path}: expected json object")
    return obj


def _require_str(path: Path, obj: dict[str, Any], key: str, *, prefix: str | None = None) -> str:
    val = obj.get(key)
    if not isinstance(val, str):
        where = f"{prefix}.{key}" if prefix else key
        raise DatasetError(f"{path}: {where} must be a string")
    return val


def _require_keys(
    path: Path,
    obj: dict[str, Any],
    *,
    required: set[str],
    optional: set[str],
    prefix: str | None = None,
) -> None:
    keys = set(obj.keys())
    missing = required - keys
    if missing:
        where = prefix or "object"
        raise DatasetError(f"{path}: missing keys in {where}: {', '.join(sorted(missing))}")
    extra = keys - (required | optional)
    if extra:
        where = prefix or "object"
        raise DatasetError(f"{path}: unknown keys in {where}: {', '.join(sorted(extra))}")


def _is_hex(s: str) -> bool:
    try:
        int(s, 16)
        return True
    except Exception:
        return False

