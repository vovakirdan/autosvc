from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autosvc.config import AutosvcDirs, load_dirs


class BackupError(Exception):
    pass


def _default_backups_dir(dirs: AutosvcDirs | None = None) -> Path:
    # Explicit override.
    env = (os.getenv("AUTOSVC_BACKUPS_DIR", "") or "").strip()
    if env:
        return Path(env).expanduser()

    # Back-compat with earlier AUTOSVC_BACKUP_DIR.
    env = (os.getenv("AUTOSVC_BACKUP_DIR", "") or "").strip()
    if env:
        return Path(env).expanduser()

    d = dirs or load_dirs()
    return d.backups_dir


@dataclass(frozen=True)
class BackupRecord:
    """A persisted backup record.

    Notes:
      - For write backups, old_hex/new_hex are populated.
      - For snapshot backups, raw_hex is populated.
      - No wall-clock timestamps: deterministic for regression tests.
    """

    backup_id: str
    kind: str
    ecu: str
    did: int
    key: str | None
    old_hex: str | None = None
    new_hex: str | None = None
    raw_hex: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "backup_id": self.backup_id,
            "kind": self.kind,
            "ecu": self.ecu,
            "did": f"{int(self.did) & 0xFFFF:04X}",
            "key": self.key,
            "notes": self.notes,
        }
        if self.old_hex is not None:
            out["old_hex"] = self.old_hex
        if self.new_hex is not None:
            out["new_hex"] = self.new_hex
        if self.raw_hex is not None:
            out["raw_hex"] = self.raw_hex
        return out


class BackupStore:
    def __init__(self, root: Path | None = None, *, dirs: AutosvcDirs | None = None) -> None:
        self._dirs = dirs
        self._root = Path(root) if root is not None else _default_backups_dir(dirs)

    @property
    def root(self) -> Path:
        return self._root

    def create_write_backup(
        self,
        *,
        ecu: str,
        did: int,
        key: str | None,
        old: bytes,
        new: bytes,
        notes: str | None = None,
        copy_to_log_dir: Path | None = None,
    ) -> BackupRecord:
        return self.create_backup(
            kind="did_write",
            ecu=ecu,
            did=did,
            key=key,
            old_hex=old.hex().upper(),
            new_hex=new.hex().upper(),
            raw_hex=None,
            notes=notes,
            copy_to_log_dir=copy_to_log_dir,
        )

    def create_snapshot_backup(
        self,
        *,
        ecu: str,
        did: int,
        key: str | None,
        raw: bytes,
        notes: str | None = None,
        copy_to_log_dir: Path | None = None,
    ) -> BackupRecord:
        return self.create_backup(
            kind="did_snapshot",
            ecu=ecu,
            did=did,
            key=key,
            old_hex=None,
            new_hex=None,
            raw_hex=raw.hex().upper(),
            notes=notes,
            copy_to_log_dir=copy_to_log_dir,
        )

    def create_backup(
        self,
        *,
        kind: str,
        ecu: str,
        did: int,
        key: str | None,
        old_hex: str | None,
        new_hex: str | None,
        raw_hex: str | None,
        notes: str | None,
        copy_to_log_dir: Path | None = None,
    ) -> BackupRecord:
        self._root.mkdir(parents=True, exist_ok=True)
        backup_id = self._next_id()
        record = BackupRecord(
            backup_id=backup_id,
            kind=str(kind),
            ecu=str(ecu).upper(),
            did=int(did) & 0xFFFF,
            key=str(key) if isinstance(key, str) and key else None,
            old_hex=str(old_hex).upper() if isinstance(old_hex, str) and old_hex else None,
            new_hex=str(new_hex).upper() if isinstance(new_hex, str) and new_hex else None,
            raw_hex=str(raw_hex).upper() if isinstance(raw_hex, str) and raw_hex else None,
            notes=str(notes) if isinstance(notes, str) and notes else None,
        )

        record_path = self._record_path(backup_id)
        record_path.write_text(json.dumps(record.to_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8")

        idx_path = self._index_path()
        with idx_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")) + "\n")

        if copy_to_log_dir is not None:
            self._copy_to_log_bundle(record, copy_to_log_dir)

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

        kind = str(obj.get("kind") or "")
        ecu = str(obj.get("ecu") or "").upper()
        did_raw = str(obj.get("did") or "")
        key = obj.get("key")
        old_hex = obj.get("old_hex")
        new_hex = obj.get("new_hex")
        raw_hex = obj.get("raw_hex")
        notes = obj.get("notes")

        try:
            did_int = int(did_raw, 16) & 0xFFFF
        except Exception as exc:
            raise BackupError("invalid backup record") from exc
        if not ecu or len(ecu) != 2:
            raise BackupError("invalid backup record")
        if kind not in {"did_write", "did_snapshot"}:
            raise BackupError("invalid backup record")

        return BackupRecord(
            backup_id=normalized,
            kind=kind,
            ecu=ecu,
            did=did_int,
            key=str(key) if isinstance(key, str) and key else None,
            old_hex=str(old_hex).upper() if isinstance(old_hex, str) and old_hex else None,
            new_hex=str(new_hex).upper() if isinstance(new_hex, str) and new_hex else None,
            raw_hex=str(raw_hex).upper() if isinstance(raw_hex, str) and raw_hex else None,
            notes=str(notes) if isinstance(notes, str) and notes else None,
        )

    def _record_path(self, backup_id: str) -> Path:
        return self._root / f"{backup_id}.json"

    def _index_path(self) -> Path:
        return self._root / "index.jsonl"

    def _next_id(self) -> str:
        # Find last backup_id from index.jsonl (last line), deterministic and
        # does not require a separate index counter file.
        idx = self._index_path()
        last = 0
        if idx.exists():
            try:
                # Read last non-empty line.
                with idx.open("rb") as f:
                    f.seek(0, os.SEEK_END)
                    size = f.tell()
                    # scan backwards a bit
                    step = min(8192, size)
                    f.seek(max(0, size - step), os.SEEK_SET)
                    chunk = f.read().decode("utf-8", errors="ignore")
                lines = [ln for ln in chunk.splitlines() if ln.strip()]
                if lines:
                    obj = json.loads(lines[-1])
                    if isinstance(obj, dict) and str(obj.get("backup_id") or "").isdigit():
                        last = int(str(obj.get("backup_id")))
            except Exception:
                last = 0
        nxt = last + 1
        return f"{nxt:06d}"

    def _copy_to_log_bundle(self, record: BackupRecord, log_dir: Path) -> None:
        # Keep backups grouped.
        bdir = Path(log_dir) / "backups"
        bdir.mkdir(parents=True, exist_ok=True)

        src = self._record_path(record.backup_id)
        dst = bdir / src.name
        try:
            shutil.copyfile(src, dst)
        except Exception:
            # Best-effort; do not fail the main operation.
            return

        # Also append to a per-run index.
        idx = bdir / "index.jsonl"
        try:
            with idx.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")) + "\n")
        except Exception:
            return
