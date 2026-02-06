from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def __getattr__(name: str) -> str:
    if name != "__version__":
        raise AttributeError(name)
    try:
        return version("autosvc")
    except PackageNotFoundError:
        return "0.0.0"

