from __future__ import annotations

import json
import sys
from difflib import unified_diff
from pathlib import Path
from typing import Dict, Iterable

from backend.protocol.handlers import handle_request
from backend.transport.replay import ReplayTransport
from backend.uds.client import UdsClient


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _dump(payload: Dict[str, object]) -> str:
    # Stable formatting for diff-friendly golden snapshots.
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def _compare(name: str, actual: str, expected: str) -> bool:
    if actual == expected:
        print(f"OK {name}")
        return True
    print(f"MISMATCH {name}")
    diff = unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile="expected",
        tofile="actual",
    )
    for line in diff:
        sys.stdout.write(line)
    return False


def _run_case(uds: UdsClient, name: str, request: Dict[str, object], golden_path: Path) -> bool:
    response = handle_request(request, uds)
    actual = _dump(response)
    expected = golden_path.read_text(encoding="utf-8")
    return _compare(name, actual, expected)


def main() -> None:
    recording = FIXTURES_DIR / "sample_recording.jsonl"
    transport = ReplayTransport(str(recording))
    uds = UdsClient(transport)

    cases = [
        ("scan_ecus", {"cmd": "scan_ecus"}, FIXTURES_DIR / "scan_ecus.golden.json"),
        (
            "read_dtcs_01",
            {"cmd": "read_dtcs", "ecu": "01"},
            FIXTURES_DIR / "read_dtcs_01.golden.json",
        ),
    ]

    ok = True
    for name, request, path in cases:
        ok = _run_case(uds, name, request, path) and ok

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
