from __future__ import annotations

import os

from autosvc.core.brands.base import BrandModule
from autosvc.core.brands.generic import GenericBrand
from autosvc.core.brands.vag import VagBrand


def _load_brand(name: str) -> BrandModule | None:
    if name == "vag":
        return VagBrand()
    return None


def get_modules(brand: str | None = None) -> list[BrandModule]:
    brand_name = (brand or os.getenv("AUTOSVC_BRAND", "")).strip().lower()
    modules: list[BrandModule] = []
    if brand_name:
        module = _load_brand(brand_name)
        if module is not None:
            modules.append(module)
    modules.append(GenericBrand())
    return modules


def describe(code: str, brand: str | None = None) -> str | None:
    for module in get_modules(brand):
        description = module.describe(code)
        if description:
            return description
    return None

