from __future__ import annotations

import sys


def confirm_or_raise(message: str, *, assume_yes: bool = False) -> None:
    if assume_yes:
        return
    sys.stderr.write(message.rstrip() + "\n")
    sys.stderr.write("Type 'yes' to continue: ")
    sys.stderr.flush()
    line = sys.stdin.readline()
    if (line or "").strip().lower() != "yes":
        raise RuntimeError("aborted by user")

