from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


class SecurityAlgoError(Exception):
    pass


@dataclass(frozen=True)
class LoadedSecurityAlgo:
    module: ModuleType
    fn_name: str

    def compute_key(self, seed: bytes, *, level: int, ecu: str) -> bytes:
        fn = getattr(self.module, self.fn_name, None)
        if fn is None or not callable(fn):
            raise SecurityAlgoError(f"algorithm function '{self.fn_name}' not found or not callable")

        # Support either:
        #   compute_key(seed)
        # or:
        #   compute_key(seed, level, ecu)
        try:
            out = fn(seed, level, ecu)
        except TypeError:
            out = fn(seed)
        if not isinstance(out, (bytes, bytearray)):
            raise SecurityAlgoError("compute_key() must return bytes")
        return bytes(out)


def load_security_algo(
    module_ref: str | None,
    *,
    fn_name: str = "compute_key",
    env_var: str = "AUTOSVC_SECURITY_ALGO",
) -> LoadedSecurityAlgo | None:
    ref = (module_ref or os.getenv(env_var, "") or "").strip()
    if not ref:
        return None

    # Accept either a module name (e.g. mypkg.myalgo) or a filesystem path to a .py.
    if ref.endswith(".py") or "/" in ref or ref.startswith("."):
        path = Path(ref).expanduser().resolve()
        if not path.exists():
            raise SecurityAlgoError(f"algorithm module not found: {path}")
        name = f"autosvc_user_security_algo_{path.stem}"
        loader = importlib.machinery.SourceFileLoader(name, str(path))
        spec = importlib.util.spec_from_loader(name, loader)
        if spec is None:
            raise SecurityAlgoError("failed to load algorithm module")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return LoadedSecurityAlgo(module=module, fn_name=fn_name)

    module = importlib.import_module(ref)
    return LoadedSecurityAlgo(module=module, fn_name=fn_name)
