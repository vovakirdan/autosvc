from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path

from autosvc.core.brands.base import BrandModule


class VagDataError(Exception):
    pass


def _read_text(rel_parts: list[str]) -> str:
    # Prefer package resources (works in installed wheels). Fall back to source tree paths.
    try:
        p = resources.files("autosvc").joinpath(*rel_parts)
        return p.read_text(encoding="utf-8")
    except Exception:
        base = Path(__file__).resolve().parents[2]  # autosvc/
        return (base.joinpath(*rel_parts)).read_text(encoding="utf-8")


def _load_json_map(rel_parts: list[str]) -> dict[str, str]:
    raw = _read_text(rel_parts)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VagDataError(f"invalid JSON: {'/'.join(rel_parts)}") from exc
    if not isinstance(obj, dict):
        raise VagDataError(f"invalid JSON root: {'/'.join(rel_parts)}")
    out: dict[str, str] = {}
    for k, v in obj.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise VagDataError(f"invalid entry in {'/'.join(rel_parts)}")
        key = k.strip().upper()
        val = v.strip()
        if not key:
            raise VagDataError(f"empty key in {'/'.join(rel_parts)}")
        if not val:
            raise VagDataError(f"empty value for {key} in {'/'.join(rel_parts)}")
        if val[-1] in {".", "!", "?", ":", ";"}:
            raise VagDataError(f"trailing punctuation in description for {key} in {'/'.join(rel_parts)}")
        out[key] = val
    return out


@lru_cache(maxsize=1)
def _load_vag_data() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    ecu_map = _load_json_map(["data", "vag", "ecu_map.json"])
    dtc_powertrain = _load_json_map(["data", "vag", "dtc_powertrain.json"])
    dtc_network = _load_json_map(["data", "vag", "dtc_network.json"])
    dtc_chassis = _load_json_map(["data", "vag", "dtc_chassis.json"])
    dtc_body = _load_json_map(["data", "vag", "dtc_body.json"])
    dtcs: dict[str, dict[str, str]] = {
        "P": dtc_powertrain,
        "U": dtc_network,
        "C": dtc_chassis,
        "B": dtc_body,
    }
    return ecu_map, dtcs


class VagBrand(BrandModule):
    name = "vag"

    def __init__(self) -> None:
        self._ecu_map, self._dtcs = _load_vag_data()

    def ecu_name(self, ecu: str) -> str | None:
        key = str(ecu).strip().upper()
        if not key:
            return None
        return self._ecu_map.get(key)

    def describe(self, dtc_code: str) -> str | None:
        code = str(dtc_code).strip().upper()
        if len(code) < 2:
            return None
        system = code[0]
        table = self._dtcs.get(system)
        if table is None:
            return None
        return table.get(code)

