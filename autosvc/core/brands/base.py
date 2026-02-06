from __future__ import annotations


class BrandModule:
    name: str

    def describe(self, dtc_code: str) -> str | None:
        """Return a description override for a formatted DTC code, or None."""
        raise NotImplementedError

    def ecu_name(self, ecu: str) -> str | None:
        """Return a human-readable ECU name for a diagnostic address (e.g. '01'), or None."""
        return None
