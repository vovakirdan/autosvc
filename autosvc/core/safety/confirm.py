from __future__ import annotations

import sys


def confirm_or_raise(message: str, *, assume_yes: bool = False, token: str = "yes") -> None:
    if assume_yes:
        return
    want = (token or "yes").strip()
    sys.stderr.write(message.rstrip() + "\n")
    sys.stderr.write(f"Type '{want}' to continue (or add --yes to skip): ")
    sys.stderr.flush()
    line = sys.stdin.readline()
    if (line or "").strip() != want:
        raise RuntimeError("aborted by user")

