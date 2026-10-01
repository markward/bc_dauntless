"""Every minor-rock number in one place (minor-rocks spec §5).

Python-owned dials are read at use by engine/rocks/minors.py and
engine/rocks/minor_contact.py; a count / shell / size change rebuilds the
viewed set's clouds. NATIVE_KEYS go to the native MinorField as one dict
(renderer.minors_set_dials). Not persisted; tuned live through the shared
/ L O keys once Developer Options -> Lighting -> "Dial keys" selects
"minors" (engine/dev_dial_groups.py).
"""
from typing import Callable, Optional

FAMILY_INDEX = {"silicate": 0, "carbonaceous": 1, "icy": 2, "metallic": 3}

DEFAULTS: dict = {
    # §1 halo
    "halo_inner": 1.1, "halo_outer": 3.0, "halo_falloff": 1.0,
    "halo_per_gu2": 8.0, "halo_min": 12, "halo_max": 400,
    "halo_r_min_gu": 0.03, "halo_r_max_frac": 0.15, "halo_r_max_gu": 1.0,
    "halo_size_exponent": 2.5, "halo_orbit_rate": 0.02,
    # §1 tile field
    "tile_count_mult": 1.0, "tile_r_min_gu": 0.05,
    "tile_r_per_size_factor": 0.1, "tile_size_exponent": 2.5,
    "tile_orbit_rate": 0.0,
    # §1 budget
    "max_live_minors": 20000, "free_cloud_fade_seconds": 2.0,
    # §2 render (native)
    "min_pixel_radius": 1.5, "lod0_pixel_radius": 24.0,
    "tumble_min": 0.05, "tumble_max": 0.6,
    "cloud_fade_in_seconds": 1.5,
    # §3 contact (native)
    "contact_margin_gu": 0.1, "shove_transfer": 0.6, "shove_min_gups": 0.3,
    "shove_damp_seconds": 4.0, "shove_tumble": 1.5,
    "max_shoves_per_frame": 64, "teleport_gu": 20000.0,
    "contact_cooldown_s": 0.5,
    # §3 responses (Python)
    "puff_min_radius_gu": 0.1, "puff_spark_count": 6, "puff_max_per_s": 6,
    "grit_volume": 0.25, "grit_max_per_s": 4,
    "flicker_intensity": 0.3, "flicker_radius": 0.05, "flicker_max_per_s": 2,
    # §4 breakup debris
    "debris_gravel_per_gu": 4.0, "debris_gravel_r_min_gu": 0.03,
    "debris_gravel_r_max_gu": 0.3, "max_debris_per_death": 40,
    "debris_damp_seconds": 6.0,
}

NATIVE_KEYS = frozenset({
    "min_pixel_radius", "lod0_pixel_radius", "tumble_min", "tumble_max",
    "cloud_fade_in_seconds", "contact_margin_gu", "shove_transfer",
    "shove_min_gups", "shove_damp_seconds", "shove_tumble",
    "max_shoves_per_frame", "teleport_gu", "contact_cooldown_s",
    "debris_damp_seconds",
})

DIAL_ORDER: tuple = tuple(DEFAULTS)
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
    """Pure. Ints step by ±1 (±10% when ≥ 10), floor 0 (1 for per-frame
    caps); floats ×/÷ 1.25, and a float at 0 steps to 0.01 going up."""
    if name not in dials:
        raise ValueError("unknown minor dial: %r" % (name,))
    out = dict(dials)
    v = out[name]
    if isinstance(v, int):
        delta = max(1, abs(v) // 10)
        floor = 1 if name in ("max_shoves_per_frame", "max_debris_per_death",
                              "max_live_minors") else 0
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
    dev_dial_groups.register_group("minors", DIAL_ORDER, current, _step)
