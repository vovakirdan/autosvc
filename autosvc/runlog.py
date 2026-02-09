from __future__ import annotations

import datetime as _dt
import io
import json
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass(frozen=True)
class RunLogPaths:
    run_dir: Path
    log_path: Path
    result_path: Path
    metadata_path: Path


class TeeTextIO(io.TextIOBase):
    """A minimal tee for text output.

    Used to capture stdout to a file without changing the CLI output.
    """

    def __init__(self, primary: TextIO, secondary: TextIO) -> None:
        self._primary = primary
        self._secondary = secondary

    @property
    def encoding(self) -> str | None:  # pragma: no cover
        return getattr(self._primary, "encoding", None)

    def write(self, s: str) -> int:
        n = self._primary.write(s)
        self._secondary.write(s)
        return n

    def flush(self) -> None:
        self._primary.flush()
        self._secondary.flush()


def create_run_log_dir(base_dir: str, *, trace_id: str, argv: list[str]) -> RunLogPaths:
    base = Path(os.path.expanduser(str(base_dir))).resolve()
    ts = _dt.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    run_dir = base / f"run-{ts}-{trace_id}"
    run_dir.mkdir(parents=True, exist_ok=False)

    log_path = run_dir / "autosvc.log"
    result_path = run_dir / "result.json"
    metadata_path = run_dir / "metadata.json"

    meta = {
        "timestamp": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "trace_id": trace_id,
        "argv": list(argv),
        "cwd": os.getcwd(),
        "pid": os.getpid(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    metadata_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return RunLogPaths(
        run_dir=run_dir,
        log_path=log_path,
        result_path=result_path,
        metadata_path=metadata_path,
    )
