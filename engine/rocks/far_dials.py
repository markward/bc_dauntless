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
    # §2 haze slab (native). The belt generator's dials went with it
    # (rock-fields, 2026-10-02).
    "slab_sigmas": 4.0,
    # §3 look (native)
    # speck_gain 4.0: Mark, live 2026-10-02 ("spec gain needs to come up to
    # about 4").
    "speck_gain": 4.0, "haze_gain": 270.0, "haze_steps": 24,
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
    # Tile-field haze noise (Python, read at use; re-push sources; 2026-10-02):
    # the sphere's density x m(x) = max(0, 1 + contrast (2 fbm(x / scale) -
    # 1)), 3D value noise fixed to the field, mean m ~= 1 (so the gain and
    # brightness above keep their meaning). tile_haze_steps is the sphere's
    # own march step count (the shader caps it at 64).
    "tile_haze_noise_scale_gu": 250.0, "tile_haze_noise_contrast": 0.8,
    "tile_haze_noise_octaves": 3, "tile_haze_steps": 48,
    # Belt noise (Python, read at use; re-push sources; rock-fields R1,
    # 2026-10-02): every source's density is a(x) * m(x), belts included --
    # the near and mid bands sample it. Same m as the tile fields, at a belt's
    # scale. Every *_noise_contrast steps within [0, 1].
    "belt_noise_scale_gu": 4000.0, "belt_noise_contrast": 0.8,
    "belt_noise_octaves": 3,
    # Rock fields near band (native; rock-fields Task 4, parsed natively in
    # Task 7). MUST equal NearDials in
    # native/src/renderer/include/renderer/rock_near.h. Per class: density
    # (rocks / GU^3 where the field density is 1), power-law sizes, cell
    # edge, mesh / billboard camera distances (billboard = streamed radius)
    # and the per-camera instance cap.
    "near_small_density": 0.008, "near_small_r_min": 0.05, "near_small_r_max": 0.5,
    "near_small_exponent": 2.5, "near_small_cell_gu": 10.0, "near_small_mesh_gu": 20.0,
    "near_small_billboard_gu": 30.0, "near_small_max": 4000,
    "near_large_density": 1.25e-4, "near_large_r_min": 1.0, "near_large_r_max": 5.0,
    "near_large_exponent": 2.5, "near_large_cell_gu": 20.0, "near_large_mesh_gu": 50.0,
    "near_large_billboard_gu": 60.0, "near_large_max": 1000,
    "near_fade_gu": 4.0, "near_stream_margin_gu": 10.0, "collide_cooldown_s": 0.5,
}

NATIVE_KEYS = frozenset({"imp_hi", "imp_lo", "speck_hi", "speck_lo", "p_min",
    "slab_sigmas", "speck_gain", "haze_gain", "haze_steps",
    "near_small_density", "near_small_r_min", "near_small_r_max",
    "near_small_exponent", "near_small_cell_gu", "near_small_mesh_gu",
    "near_small_billboard_gu", "near_small_max",
    "near_large_density", "near_large_r_min", "near_large_r_max",
    "near_large_exponent", "near_large_cell_gu", "near_large_mesh_gu",
    "near_large_billboard_gu", "near_large_max",
    "near_fade_gu", "near_stream_margin_gu", "collide_cooldown_s"})

# Ints that must never reach 0 (a zero cap would silently delete the whole
# tier, not shrink it).
_INT_FLOOR_1 = ("haze_steps", "tile_haze_noise_octaves", "tile_haze_steps",
               "belt_noise_octaves", "near_small_max", "near_large_max")

# / L O order: the look dials Mark tunes live come first, the rest after.
_LOOK_FIRST = ("haze_brightness", "tile_haze_brightness", "haze_gain",
               "tile_haze_gain", "speck_gain", "tile_haze_edge_frac",
               "tile_haze_noise_scale_gu", "tile_haze_noise_contrast",
               "tile_haze_noise_octaves", "belt_noise_scale_gu",
               "belt_noise_contrast", "belt_noise_octaves")
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
    float at 0 steps to 0.01 going up. Every `*_noise_contrast` is clamped
    to [0, 1] (m's bound is 1 + contrast)."""
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
    if name.endswith("_noise_contrast"):
        out[name] = min(1.0, max(0.0, out[name]))
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
