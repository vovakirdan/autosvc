from __future__ import annotations

from backend.brands.base import BrandModule


_VAG_DESCRIPTIONS = {
    "P2002": "DPF efficiency below threshold (VAG)",
    "P0420": "Catalyst efficiency below threshold (VAG)",
}


class VagBrand(BrandModule):
    name = "vag"

    def describe(self, dtc_code: str) -> str | None:
        return _VAG_DESCRIPTIONS.get(dtc_code)
