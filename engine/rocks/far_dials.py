"""Every far-tier number in one place (far-tier plan Task 9).

Mirrors engine/rocks/minor_dials.py: native keys ride to the C++ FarField
as one dict (`renderer.far_set_dials`); the §2 population + disc-shape keys
stay Python-owned and are read at use by engine/rocks/density.py and
field_table.py, re-pushing sources on change (left to the caller, like
minor_dials' rebuild hook). Not persisted; tuned live through the shared
/ L O keys once Developer Options -> Lighting -> "Dial keys" selects
"rock fields" (engine/dev_dial_groups.py).
"""
from typing import Callable, Optional

DEFAULTS: dict = {
    # §1 ladder (native)
    "imp_hi": 16.0, "imp_lo": 12.0, "speck_hi": 2.0, "speck_lo": 1.5, "p_min": 0.25,
    # §3 look (native)
    # speck_gain 4.0: Mark, live 2026-10-02 ("spec gain needs to come up to
    # about 4").
    "speck_gain": 4.0,
    # §2 populations + disc shape (Python, read at use; re-push sources)
    "minor_density_at_1": 9.67e-8, "minor_r_min": 0.05, "minor_r_max": 0.7,
    "minor_exponent": 2.5,
    "major_density_at_1": 1.0 / 1.2e9, "major_a_lo": 0.5,
    "major_r_min": 1.0, "major_r_max": 5.0, "major_exponent": 2.5,
    "scale_height_frac": 0.03, "scale_height_min_gu": 1000.0,
    "outer_fade_gu": 20000.0,
    # Tile-field shape (Python, read at use; re-push sources): the outer
    # fraction of an AsteroidField's radius over which its density ramps to 0.
    "tile_edge_frac": 0.2,
    # Tile-field noise (Python, read at use; re-push sources; 2026-10-02):
    # the sphere's density x m(x) = max(0, 1 + contrast (2 fbm(x / scale) -
    # 1)), 3D value noise fixed to the field, mean m ~= 1.
    "tile_noise_scale_gu": 250.0, "tile_noise_contrast": 0.8,
    "tile_noise_octaves": 3,
    # Tile-field shape (Python, read at use; re-push sources; 2026-10-04): the tile
    # field's ONE density (puffs AND rocks) gets clumps/voids and a lumpy
    # outline. tile_noise_sharpness stretches the noise (1 = off);
    # tile_shape_warp (0 = off, < 0.9) warps the sphere's edge at
    # tile_shape_warp_scale_frac x the field radius.
    "tile_noise_sharpness": 2.5, "tile_shape_warp": 0.35,
    "tile_shape_warp_scale_frac": 0.6,
    # Belt noise (Python, read at use; re-push sources; rock-fields R1,
    # 2026-10-02): every source's density is a(x) * m(x), belts included --
    # the near band, specks and puffs sample it. Same m as the tile fields, at a belt's
    # scale. Every *_noise_contrast steps within [0, 1].
    "belt_noise_scale_gu": 4000.0, "belt_noise_contrast": 0.8,
    "belt_noise_octaves": 3,
    # Rock fields near band (native; rock-fields Task 4, parsed natively in
    # Task 7). MUST equal NearDials in
    # native/src/renderer/include/renderer/rock_near.h. Per class: density
    # (rocks / GU^3 where the field density is 1), power-law sizes, cell
    # edge, mesh / billboard camera distances (billboard = streamed radius)
    # and the per-camera instance cap.
    # near_small_density 0.008 -> 0.010, near_small_mesh_gu 20 -> 15:
    # Mark, live 2026-10-03 (slightly more small rocks, as billboards closer in).
    "near_small_density": 0.010, "near_small_r_min": 0.05, "near_small_r_max": 0.5,
    "near_small_exponent": 2.5, "near_small_cell_gu": 10.0, "near_small_mesh_gu": 15.0,
    "near_small_billboard_gu": 90.0, "near_small_max": 4000,   # 3x (Mark, live 2026-10-04)
    # near_large_density 1.25e-4 -> 6.25e-5, near_large_mesh_gu 50 -> 60,
    # near_large_billboard_gu 60 -> 90: Mark, live 2026-10-03 (fewer big
    # asteroids but visible a bit further).
    "near_large_density": 6.25e-5, "near_large_r_min": 1.0, "near_large_r_max": 5.0,
    # near_large_cell_gu 20 -> 50, near_large_max 1000 -> 4000: rock-real
    # Part 1, 2026-10-03 (every big-asteroid silhouette is a real rock). 50 GU
    # cells keep the large reach (+ margin) under the 33-cells-per-axis cap;
    # near_large_max 4000 covers a full-density field's ~3,200 large rocks in
    # a 60 degree view at 400 GU.
    "near_large_exponent": 2.5, "near_large_cell_gu": 50.0, "near_large_mesh_gu": 60.0,
    "near_large_billboard_gu": 405.0, "near_large_max": 4000,   # 3x, then +50% large only (Mark, live 2026-10-04)
    # Space dust inside rock fields (Python, read at use; Mark, live
    # 2026-10-03): the dust pass's density is multiplied by up to this at
    # full field density (tile field interior or a=1 belt), ramping with the
    # field's a(x) at the player. 1.0 = off.
    "field_dust_mult": 10.0,
    # Pixel floors: a billboard past mesh range at or below its class's
    # floor (on-screen radius, px) draws nothing, fading in over the next px.
    "near_large_min_px": 1.5,
    "near_small_min_px": 2.5,   # Mark, live 2026-10-04 (3x ranges)
    "near_fade_gu": 4.0, "near_tumble_scale": 0.05, "near_dash_collapse_step_gu": 25.0, "near_stream_margin_gu": 10.0, "collide_cooldown_s": 0.5,
    # Large-rock collision response (Python, read at use; rock-fields Task 8,
    # engine/rocks/scenery_contact.py): damage = KE damage x
    # collide_damage_scale x min(1, rock radius / collide_ref_radius_gu).
    "collide_damage_scale": 1.0, "collide_ref_radius_gu": 5.0,
    # Speck band (native; MUST equal SpeckDials in rock_speck.h): the
    # near band's large rocks past their billboard edge as lit specks, out to
    # speck_out_gu (fading over speck_out_fade_gu). Beyond speck_keep_d0_gu
    # whole cells thin as (d0 / d)^speck_keep_power, fading over speck_keep_band of their
    # hash. Re-streamed every speck_restream_gu of travel. speck_band_gain
    # multiplies speck_gain for this band only.
    "speck_out_gu": 1500.0, "speck_out_fade_gu": 400.0,
    "speck_keep_d0_gu": 420.0, "speck_keep_band": 0.25, "speck_keep_power": 3.0,
    "speck_restream_gu": 50.0, "speck_band_gain": 0.25,
    # Puffs (native; MUST equal PuffDials in rock_puffs.h): the far
    # look of a tile field as puff_count soft lit billboards placed by its
    # density, radius puff_size_frac x field radius x [0.6, 1.4], peak alpha
    # puff_opacity, fading in over [puff_start_gu, + puff_ramp_gu] and out
    # within puff_near_fade x their radius.
    "puff_count": 400, "puff_size_frac": 0.18, "puff_opacity": 0.04698,
    "puff_brightness": 8.0, "puff_start_gu": 800.0, "puff_ramp_gu": 800.0,
    "puff_near_fade": 1.5,
    # Belts: puff_belt_count per belt, radius puff_belt_size_h x the local
    # scale height (rock_puffs.h belt_count / belt_size_h).
    "puff_belt_count": 2000, "puff_belt_size_h": 1.2,
}

NATIVE_KEYS = frozenset({"imp_hi", "imp_lo", "speck_hi", "speck_lo", "p_min",
    "speck_gain",
    "near_small_density", "near_small_r_min", "near_small_r_max",
    "near_small_exponent", "near_small_cell_gu", "near_small_mesh_gu",
    "near_small_billboard_gu", "near_small_max",
    "near_large_density", "near_large_r_min", "near_large_r_max",
    "near_large_exponent", "near_large_cell_gu", "near_large_mesh_gu",
    "near_large_billboard_gu", "near_large_max",
    "near_large_min_px", "near_small_min_px",
    "near_fade_gu", "near_tumble_scale", "near_dash_collapse_step_gu", "near_stream_margin_gu", "collide_cooldown_s",
    "speck_out_gu", "speck_out_fade_gu", "speck_keep_d0_gu", "speck_keep_band",
    "speck_keep_power", "speck_restream_gu", "speck_band_gain",
    "puff_count", "puff_size_frac", "puff_opacity", "puff_brightness",
    "puff_start_gu", "puff_ramp_gu", "puff_near_fade",
    "puff_belt_count", "puff_belt_size_h"})

# Ints that must never reach 0 (a zero cap would silently delete the whole
# tier, not shrink it).
_INT_FLOOR_1 = ("tile_noise_octaves",
               "belt_noise_octaves", "near_small_max", "near_large_max",
               "puff_count", "puff_belt_count")

# / L O order: the look dials Mark tunes live come first, the rest after.
_LOOK_FIRST = ("puff_opacity", "puff_size_frac", "puff_count", "puff_brightness",
               "puff_belt_count", "puff_belt_size_h",
               "tile_shape_warp", "tile_noise_sharpness",
               "speck_band_gain", "speck_out_gu", "speck_keep_d0_gu",
               "near_small_density", "near_large_density",
               "near_small_mesh_gu", "near_small_billboard_gu",
               "near_large_mesh_gu", "near_large_billboard_gu",
               "collide_damage_scale")
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
    dev_dial_groups.register_group("rock fields", DIAL_ORDER, current, _step)
