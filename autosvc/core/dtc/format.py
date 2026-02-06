from __future__ import annotations

_DTC_PREFIX = {0: "P", 1: "C", 2: "B", 3: "U"}


def uds_dtc_to_sae(code24: int) -> str:
    # Use the lower 16 bits for SAE-style formatting; keep the full raw value separately.
    code16 = code24 & 0xFFFF
    prefix = _DTC_PREFIX.get((code16 >> 14) & 0x3, "P")
    first = (code16 >> 12) & 0x3
    rest = code16 & 0x0FFF
    return f"{prefix}{first}{rest:03X}"


def code24_to_raw_hex(code24: int) -> str:
    return f"{code24 & 0xFFFFFF:06X}"

