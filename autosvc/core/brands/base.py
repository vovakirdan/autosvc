from __future__ import annotations


class BrandModule:
    name: str

    def describe(self, dtc_code: str) -> str | None:
        """Return a description override for a formatted DTC code, or None."""
        raise NotImplementedError

