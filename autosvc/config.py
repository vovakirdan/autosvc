from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AutosvcDirs:
    config_dir: Path
    cache_dir: Path
    data_dir: Path

    @property
    def backups_dir(self) -> Path:
        # Backup store lives under cache by default.
        return self.cache_dir / "backups"


def _xdg_config_home() -> Path:
    env = (os.getenv("XDG_CONFIG_HOME", "") or "").strip()
    if env:
        return Path(env).expanduser()
    return Path("~/.config").expanduser()


def _xdg_cache_home() -> Path:
    env = (os.getenv("XDG_CACHE_HOME", "") or "").strip()
    if env:
        return Path(env).expanduser()
    return Path("~/.cache").expanduser()


def _package_data_dir() -> Path | None:
    # Best-effort: resolve autosvc/data/datasets from an installed package.
    try:
        import importlib.resources

        base = importlib.resources.files("autosvc.data")
        p = Path(str(base.joinpath("datasets")))
        return p if p.exists() else None
    except Exception:
        return None


def load_dirs(
    *,
    config_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> AutosvcDirs:
    """Resolve base directories.

    Precedence (highest to lowest):
    1) explicit parameters (typically CLI)
    2) env vars AUTOSVC_CONFIG_DIR, AUTOSVC_CACHE_DIR, AUTOSVC_DATA_DIR
    3) config file in config_dir (autosvc.json) for data_dir/cache_dir overrides
    4) defaults (~/.config/autosvc, ~/.cache/autosvc, package datasets)
    """

    cfg_default = _xdg_config_home() / "autosvc"
    cache_default = _xdg_cache_home() / "autosvc"
    data_default = _package_data_dir() or (Path.cwd() / "datasets")

    cfg = Path(config_dir).expanduser() if config_dir is not None else None
    cache = Path(cache_dir).expanduser() if cache_dir is not None else None
    data = Path(data_dir).expanduser() if data_dir is not None else None

    if cfg is None:
        env = (os.getenv("AUTOSVC_CONFIG_DIR", "") or "").strip()
        cfg = Path(env).expanduser() if env else cfg_default
    if cache is None:
        env = (os.getenv("AUTOSVC_CACHE_DIR", "") or "").strip()
        cache = Path(env).expanduser() if env else cache_default
    if data is None:
        env = (os.getenv("AUTOSVC_DATA_DIR", "") or "").strip()
        if not env:
            # Back-compat with older env name.
            env = (os.getenv("AUTOSVC_DATASETS_DIR", "") or "").strip()
        data = Path(env).expanduser() if env else data_default

    # Optional config file overrides.
    cfg_file = cfg / "autosvc.json"
    if cfg_file.exists():
        try:
            obj = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            obj = None
        if isinstance(obj, dict):
            if cache_dir is None and not os.getenv("AUTOSVC_CACHE_DIR"):
                v = obj.get("cache_dir")
                if isinstance(v, str) and v.strip():
                    cache = Path(v).expanduser()
            if data_dir is None and not os.getenv("AUTOSVC_DATA_DIR") and not os.getenv("AUTOSVC_DATASETS_DIR"):
                v = obj.get("data_dir")
                if isinstance(v, str) and v.strip():
                    data = Path(v).expanduser()

    assert cfg is not None and cache is not None and data is not None
    return AutosvcDirs(config_dir=cfg, cache_dir=cache, data_dir=data)


def ensure_dirs(dirs: AutosvcDirs) -> None:
    dirs.config_dir.mkdir(parents=True, exist_ok=True)
    dirs.cache_dir.mkdir(parents=True, exist_ok=True)


def write_default_config(path: Path, *, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
