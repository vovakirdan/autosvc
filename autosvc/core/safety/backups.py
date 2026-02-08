from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class BackupError(Exception):
    pass


def default_backup_dir() -> Path:
    env = (os.getenv("AUTOSVC_BACKUP_DIR", "") or "").strip()
    if env:
        return Path(env).expanduser()
    # Linux-first default.
    return Path("~/.local/share/autosvc/backups").expanduser()


@dataclass(frozen=True)
class BackupRecord:
    backup_id: str
    ecu: str
    did: int
    key: str | None
    old_hex: str
    new_hex: str
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "ecu": self.ecu,
            "did": f"{int(self.did) & 0xFFFF:04X}",
            "key": self.key,
            "old_hex": self.old_hex,
            "new_hex": self.new_hex,
            "notes": self.notes,
        }


class BackupStore:
    """Simple local backup store for write operations.

    Backups are sequentially numbered and intentionally contain no wall-clock
    timestamps to keep regression tests deterministic.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else default_backup_dir()

    @property
    def root(self) -> Path:
        return self._root

    def create_backup(
        self,
        *,
        ecu: str,
        did: int,
        key: str | None,
        old: bytes,
        new: bytes,
        notes: str | None = None,
    ) -> BackupRecord:
        self._root.mkdir(parents=True, exist_ok=True)
        backup_id = self._next_id()
        record = BackupRecord(
            backup_id=backup_id,
            ecu=str(ecu).upper(),
            did=int(did) & 0xFFFF,
            key=key,
            old_hex=old.hex().upper(),
            new_hex=new.hex().upper(),
            notes=notes,
        )
        path = self._record_path(backup_id)
        path.write_text(json.dumps(record.to_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return record

    def load(self, backup_id: str) -> BackupRecord:
        raw_id = (backup_id or "").strip()
        if not raw_id:
            raise BackupError("backup_id is required")
        if not raw_id.isdigit():
            raise BackupError("invalid backup_id")
        normalized = f"{int(raw_id):06d}"
        path = self._record_path(normalized)
        if not path.exists():
            raise BackupError("backup not found")
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise BackupError("invalid backup record") from exc
        if not isinstance(obj, dict):
            raise BackupError("invalid backup record")
        ecu = str(obj.get("ecu") or "").upper()
        did_raw = str(obj.get("did") or "")
        key = obj.get("key")
        old_hex = str(obj.get("old_hex") or "")
        new_hex = str(obj.get("new_hex") or "")
        notes = obj.get("notes")
        try:
            did_int = int(did_raw, 16) & 0xFFFF
        except Exception as exc:
            raise BackupError("invalid backup record") from exc
        if not ecu or len(ecu) != 2:
            raise BackupError("invalid backup record")
        if not old_hex or not new_hex:
            raise BackupError("invalid backup record")
        return BackupRecord(
            backup_id=normalized,
            ecu=ecu,
            did=did_int,
            key=str(key) if isinstance(key, str) and key else None,
            old_hex=old_hex.upper(),
            new_hex=new_hex.upper(),
            notes=str(notes) if isinstance(notes, str) and notes else None,
        )

    def _record_path(self, backup_id: str) -> Path:
        return self._root / f"{backup_id}.json"

    def _next_id(self) -> str:
        idx_path = self._root / "index.txt"
        last = 0
        if idx_path.exists():
            try:
                last = int(idx_path.read_text(encoding="utf-8").strip() or "0")
            except Exception:
                last = 0
        nxt = last + 1
        idx_path.write_text(str(nxt), encoding="utf-8")
        return f"{nxt:06d}"

