from __future__ import annotations

import json
from typing import Any


def dumps(obj: Any, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(obj, sort_keys=True, indent=2) + "\n"
    return json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n"


def dump_jsonl_line(obj: Any) -> str:
    # JSONL should be compact and deterministic.
    return json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n"

