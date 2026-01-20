from __future__ import annotations

from backend.brands.base import BrandModule


_GENERIC_DESCRIPTIONS = {
    "P0300": "Random/multiple cylinder misfire detected",
    "P0420": "Catalyst system efficiency below threshold (Bank 1)",
    "P2002": "Diesel particulate filter efficiency below threshold",
    "U0100": "Lost communication with ECM/PCM",
}


class GenericBrand(BrandModule):
    name = "generic"

    def describe(self, dtc_code: str) -> str | None:
        return _GENERIC_DESCRIPTIONS.get(dtc_code)
