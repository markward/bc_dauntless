"""Every far-tier number in one place (far-tier plan Task 9).

Mirrors engine/rocks/minor_dials.py: native keys ride to the C++ FarField
as one dict (`renderer.far_set_dials`); the §2 population + disc-shape keys
stay Python-owned and are read at use by engine/rocks/density.py and
field_table.py, re-pushing sources on change (left to the caller, like
minor_dials' rebuild hook). Not persisted; tuned live through the shared
/ L O keys once Developer Options -> Lighting -> "Dial keys" selects "far"
(engine/dev_dial_groups.py).
"""
from typing import Callable, Optional

DEFAULTS: dict = {
    # §1 ladder (native)
    "imp_hi": 16.0, "imp_lo": 12.0, "speck_hi": 2.0, "speck_lo": 1.5, "p_min": 0.25,
    # §2 generator (native)
    "k_ref": 1713.0, "size_classes": 4, "cells_per_range": 4,
    "max_far_rocks": 60000, "cell_cache_max": 32768, "slab_sigmas": 4.0,
    "max_cells_per_axis": 17,
    # §3 look (native)
    "speck_gain": 1.0, "haze_gain": 270.0, "haze_steps": 24,
    # §2 populations + disc shape (Python, read at use; re-push sources)
    "minor_density_at_1": 9.67e-8, "minor_r_min": 0.05, "minor_r_max": 0.7,
    "minor_exponent": 2.5,
    "major_density_at_1": 1.0 / 1.2e9, "major_a_lo": 0.5,
    "major_r_min": 1.0, "major_r_max": 5.0, "major_exponent": 2.5,
    "scale_height_frac": 0.03, "scale_height_min_gu": 1000.0,
    "outer_fade_gu": 20000.0,
    # Tile-field haze (Python, read at use; re-push sources). tile_haze_gain
    # is the EFFECTIVE gain of an AsteroidField's sphere source (sent as
    # gain_scale = tile_haze_gain / haze_gain). Re-derived 2026-10-02 after
    # ruling R16 removed the pixel cut, by far_field_test.cc
    # FarHazeSphere.DefaultTileGainHitsTheStatedTarget: alpha 0.15 looking
    # from Beol 4's Player Start at its field (tau at gain 1 = 1.15e-5, so
    # gain = -ln 0.85 / tau = 14,136 -> 14,140).
    "tile_haze_gain": 14140.0, "tile_haze_edge_frac": 0.2,
    # Haze brightness (Python, read at use; re-push sources; ruling R16). Sent
    # per source as `brightness`: it scales the haze COLOUR only (alpha is
    # the gains' job). Over black only colour shows, and the pipeline has no
    # sRGB encode, so these are calibrated on the DISPLAYED value: 0.95 x
    # mean(rgb) x 255 = 25 under the production lighting, by far_field_test.cc
    # FarHaze.DefaultBeltBrightnessShowsTwentyFiveOverBlack (Vesuvi mid-band,
    # tangential: 3.12/255 at 1 -> 8.0) and
    # FarHazeSphere.DefaultTileBrightnessShowsTwentyFiveOverBlack (Beol 4
    # Player Start -> field centre: 2.75/255 at 1 -> 9.1).
    "haze_brightness": 8.0, "tile_haze_brightness": 9.1,
}

NATIVE_KEYS = frozenset({"imp_hi", "imp_lo", "speck_hi", "speck_lo", "p_min",
    "k_ref", "size_classes", "cells_per_range", "max_far_rocks",
    "cell_cache_max", "slab_sigmas", "speck_gain", "haze_gain", "haze_steps",
    "max_cells_per_axis"})

# Ints that must never reach 0 (a zero cap would silently delete the whole
# tier, not shrink it).
_INT_FLOOR_1 = ("max_far_rocks", "cell_cache_max", "size_classes",
               "cells_per_range", "haze_steps", "max_cells_per_axis")

# / L O order: the look dials Mark tunes live come first, the rest after.
_LOOK_FIRST = ("haze_brightness", "tile_haze_brightness", "haze_gain",
               "tile_haze_gain", "speck_gain", "tile_haze_edge_frac")
DIAL_ORDER: tuple = _LOOK_FIRST + tuple(k for k in DEFAULTS if k not in _LOOK_FIRST)
_FACTOR = 1.25

_dials: dict = dict(DEFAULTS)
_on_change: Optional[Callable[[set], None]] = None


def reset() -> None:
    global _dials, _on_change
    _dials = dict(DEFAULTS)
    _on_change = None


def get(name: str):
    return _dials[name]


def current() -> dict:
    return dict(_dials)


def native() -> dict:
    return {k: _dials[k] for k in NATIVE_KEYS}


def step(dials: dict, name: str, direction: int) -> dict:
    """Pure. Ints step by +-1 (+-10% when >= 10), floor 1 for the counts
    that must never silently delete the whole tier; floats x//1.25, and a
    float at 0 steps to 0.01 going up."""
    if name not in dials:
        raise ValueError("unknown far dial: %r" % (name,))
    out = dict(dials)
    v = out[name]
    if isinstance(v, int):
        delta = max(1, abs(v) // 10)
        floor = 1 if name in _INT_FLOOR_1 else 0
        out[name] = max(floor, v + direction * delta)
    elif v == 0.0:
        out[name] = 0.01 if direction > 0 else 0.0
    else:
        out[name] = v * _FACTOR if direction > 0 else v / _FACTOR
    return out


def set_on_change(fn: Optional[Callable[[set], None]]) -> None:
    global _on_change
    _on_change = fn


def on_change() -> Optional[Callable[[set], None]]:
    """The hook set_on_change installed, or None."""
    return _on_change


def _step(name: str, direction: int) -> None:
    global _dials
    _dials = step(_dials, name, direction)
    if _on_change is not None:
        _on_change({name})


def register() -> None:
    from engine import dev_dial_groups
    dev_dial_groups.register_group("far", DIAL_ORDER, current, _step)
