"""Climate classes for Earth points (CHELSA-BIOCLIM+ 1981-2010; values per point from scripts/build_climate.py).

Koppen legend of CHELSA kg0. The GeoTIFF carries no legend. Codes run in alphabetical class order (Af, Am, As, Aw,
BWk, BWh, BSk, BSh, Cfa ... Dwd), then ET = 30 and EF = 31. Checked on 2026-11-15 by sampling the file at places of
known climate (tests/test_climate.py): codes 1, 2, 4, 5, 6, 8, 9, 10, 11, 12, 13, 15, 16, 18, 19, 21, 26, 27, 29, 30
and 31 match. Codes 3, 7, 14, 17, 20, 22-25 and 28 follow the same order but were not checked with a place
(KOPPEN_INFERRED).

Aridity classes (precipitation / PET), as tabulated by Zomer et al. 2022, Sci Data 9:409,
https://www.nature.com/articles/s41597-022-01493-1 ("a climate classification scheme ... provided by UNEP"):
< 0.03 hyper-arid, 0.03-0.2 arid, 0.2-0.5 semi-arid, 0.5-0.65 dry sub-humid, > 0.65 humid.
"""
from __future__ import annotations

import math

KOPPEN = {
    1: ("Af", "Tropical rainforest"), 2: ("Am", "Tropical monsoon"), 3: ("As", "Tropical savanna, dry summer"),
    4: ("Aw", "Tropical savanna, dry winter"), 5: ("BWk", "Cold desert"), 6: ("BWh", "Hot desert"),
    7: ("BSk", "Cold steppe"), 8: ("BSh", "Hot steppe"), 9: ("Cfa", "Humid subtropical"),
    10: ("Cfb", "Temperate oceanic"), 11: ("Cfc", "Subpolar oceanic"), 12: ("Csa", "Hot-summer Mediterranean"),
    13: ("Csb", "Warm-summer Mediterranean"), 14: ("Csc", "Cold-summer Mediterranean"),
    15: ("Cwa", "Monsoon-influenced humid subtropical"), 16: ("Cwb", "Subtropical highland"),
    17: ("Cwc", "Cold subtropical highland"), 18: ("Dfa", "Hot-summer humid continental"),
    19: ("Dfb", "Warm-summer humid continental"), 20: ("Dfc", "Subarctic"), 21: ("Dfd", "Extremely cold subarctic"),
    22: ("Dsa", "Hot, dry-summer continental"), 23: ("Dsb", "Warm, dry-summer continental"),
    24: ("Dsc", "Dry-summer subarctic"), 25: ("Dsd", "Very cold, dry-summer subarctic"),
    26: ("Dwa", "Monsoon-influenced hot-summer continental"), 27: ("Dwb", "Monsoon-influenced warm-summer continental"),
    28: ("Dwc", "Monsoon-influenced subarctic"), 29: ("Dwd", "Monsoon-influenced extremely cold subarctic"),
    30: ("ET", "Tundra"), 31: ("EF", "Ice cap"),
}
N_CODES = len(KOPPEN)
KOPPEN_INFERRED = frozenset({3, 7, 14, 17, 20, 22, 23, 24, 25, 28})
ARIDITY_CAP = 100.0  # stored maximum; the raw ratio reaches 1e8 where PET is near zero (ice sheets)
ARIDITY_CLASSES = ((0.03, "hyper-arid"), (0.2, "arid"), (0.5, "semi-arid"), (0.65, "dry sub-humid"))


def koppen(code) -> tuple[str, str] | tuple[None, None]:
    """(code, label) for a CHELSA kg0 value; (None, None) for 0 / unknown."""
    try:
        return KOPPEN[int(code)]
    except (KeyError, TypeError, ValueError):
        return None, None


def is_dry_or_polar(code) -> bool:
    """Koppen main group B (arid) or E (polar)."""
    c, _ = koppen(code)
    return bool(c) and c[0] in "BE"


def aridity_class(ai) -> str | None:
    if ai is None or not math.isfinite(float(ai)):
        return None
    for edge, name in ARIDITY_CLASSES:
        if ai < edge:
            return name
    return "humid"
