from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

from autosvc.config import AutosvcDirs, ensure_dirs, load_dirs


class UnsafeError(Exception):
    pass


@dataclass(frozen=True)
class UnsafePasswordHash:
    salt_b64: str
    n: int
    r: int
    p: int
    dklen: int
    hash_b64: str

    def to_dict(self) -> dict[str, object]:
        return {
            "salt_b64": self.salt_b64,
            "n": int(self.n),
            "r": int(self.r),
            "p": int(self.p),
            "dklen": int(self.dklen),
            "hash_b64": self.hash_b64,
        }


def unsafe_config_path(dirs: AutosvcDirs | None = None) -> Path:
    d = dirs or load_dirs()
    return d.config_dir / "unsafe.json"


def is_password_configured(*, dirs: AutosvcDirs | None = None) -> bool:
    path = unsafe_config_path(dirs)
    return path.exists()


def set_password_interactive(*, dirs: AutosvcDirs | None = None) -> None:
    d = dirs or load_dirs()
    ensure_dirs(d)

    pw1 = getpass("Set unsafe mode password: ")
    if not pw1:
        raise UnsafeError("password cannot be empty")
    pw2 = getpass("Repeat password: ")
    if pw1 != pw2:
        raise UnsafeError("passwords do not match")

    rec = _hash_password(pw1)
    path = unsafe_config_path(d)
    path.write_text(json.dumps(rec.to_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8")


def prompt_password() -> str:
    pw = getpass("Unsafe mode password: ")
    if not pw:
        raise UnsafeError("password is required")
    return pw


def load_hash(*, dirs: AutosvcDirs | None = None) -> UnsafePasswordHash:
    path = unsafe_config_path(dirs)
    if not path.exists():
        raise UnsafeError("unsafe password is not configured (run: autosvc unsafe set-password)")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise UnsafeError("invalid unsafe password config") from exc
    if not isinstance(obj, dict):
        raise UnsafeError("invalid unsafe password config")
    try:
        return UnsafePasswordHash(
            salt_b64=str(obj.get("salt_b64") or ""),
            n=int(obj.get("n") or 0),
            r=int(obj.get("r") or 0),
            p=int(obj.get("p") or 0),
            dklen=int(obj.get("dklen") or 0),
            hash_b64=str(obj.get("hash_b64") or ""),
        )
    except Exception as exc:
        raise UnsafeError("invalid unsafe password config") from exc


def verify_password(password: str, *, dirs: AutosvcDirs | None = None) -> bool:
    rec = load_hash(dirs=dirs)
    if not password:
        return False
    salt = base64.b64decode(rec.salt_b64.encode("ascii"), validate=False)
    expected = base64.b64decode(rec.hash_b64.encode("ascii"), validate=False)
    got = _scrypt(password, salt=salt, n=rec.n, r=rec.r, p=rec.p, dklen=rec.dklen)
    return _consteq(got, expected)


def require_password(password: str, *, dirs: AutosvcDirs | None = None) -> None:
    if not verify_password(password, dirs=dirs):
        raise UnsafeError("invalid unsafe password")


def _hash_password(password: str) -> UnsafePasswordHash:
    # Parameters chosen to be reasonable on a modern laptop without external deps.
    # (n must be a power of two)
    n = 2**14
    r = 8
    p = 1
    dklen = 32
    salt = os.urandom(16)
    out = _scrypt(password, salt=salt, n=n, r=r, p=p, dklen=dklen)
    return UnsafePasswordHash(
        salt_b64=base64.b64encode(salt).decode("ascii"),
        n=n,
        r=r,
        p=p,
        dklen=dklen,
        hash_b64=base64.b64encode(out).decode("ascii"),
    )


def _scrypt(password: str, *, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    import hashlib

    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen)


def _consteq(a: bytes, b: bytes) -> bool:
    if len(a) != len(b):
        return False
    res = 0
    for x, y in zip(a, b, strict=False):
        res |= x ^ y
    return res == 0
