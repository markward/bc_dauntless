"""Color registries for Button and CollapsibleList components.

Defaults mirror sdk/Build/scripts/LoadInterface.py — the same RGB values
the original game sets in App.g_kRadar*Color and App.g_kSTMenu{1..4}*.
Both registries are mutable at runtime, so callers can match BC's
`ResetAffiliationColors()` style API or apply per-mission tints.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

RGB = Tuple[int, int, int]


@dataclass(frozen=True)
class MenuPalette:
    normal:      RGB
    highlighted: RGB
    selected:    RGB


_AFFILIATION_DEFAULTS: dict[str, RGB] = {
    "friendly": ( 80, 112, 230),
    "enemy":    (216,  43,  43),
    "neutral":  (255, 255, 175),
    "unknown":  (127, 127, 127),
}

_MENU_LEVEL_DEFAULTS: dict[int, MenuPalette] = {
    1: MenuPalette(normal=(216,  94,  86), highlighted=(254, 120,  86), selected=(127, 60,  43)),
    2: MenuPalette(normal=(147, 103, 255), highlighted=(173, 132, 255), selected=( 86, 66, 127)),
    3: MenuPalette(normal=(207,  96, 159), highlighted=(246, 147, 204), selected=(103, 48,  79)),
    4: MenuPalette(normal=(144, 103, 144), highlighted=(175, 144, 175), selected=( 72, 51,  72)),
}

_affiliation: dict[str, RGB] = dict(_AFFILIATION_DEFAULTS)
_menu_levels: dict[int, MenuPalette] = dict(_MENU_LEVEL_DEFAULTS)


def get_affiliation(name: str) -> RGB:
    return _affiliation[name]


def get_menu_palette(level: int) -> MenuPalette:
    return _menu_levels[level]
