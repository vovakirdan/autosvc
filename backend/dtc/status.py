from __future__ import annotations

from typing import Dict, List


_FLAG_BITS = [
    ("test_failed", 0),
    ("test_failed_this_operation_cycle", 1),
    ("pending_dtc", 2),
    ("confirmed_dtc", 3),
    ("test_not_completed_since_last_clear", 4),
    ("test_failed_since_last_clear", 5),
    ("test_not_completed_this_operation_cycle", 6),
    ("warning_indicator_requested", 7),
]


def decode_status_byte(status: int) -> Dict[str, object]:
    value = status & 0xFF
    flags: List[str] = []
    decoded: Dict[str, object] = {"flags": flags}
    for name, bit in _FLAG_BITS:
        enabled = bool(value & (1 << bit))
        decoded[name] = enabled
        if enabled:
            flags.append(name)
    return decoded
