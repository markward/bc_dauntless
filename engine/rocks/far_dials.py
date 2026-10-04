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
    # §2 haze slab (native). The belt generator's dials went with it
    # (rock-fields, 2026-10-02).
    "slab_sigmas": 4.0,
    # §3 look (native)
    # speck_gain 4.0: Mark, live 2026-10-02 ("spec gain needs to come up to
    # about 4").
    "speck_gain": 4.0, "haze_gain": 270.0, "haze_steps": 24,
    # Haze resolution (native; rock-fields Task 12): the haze marches at
    # (w / d, h / d) and is depth-aware upsampled; 1 = full resolution. Its
    # START is not a dial: far_tier derives FarDials::haze_start_gu /
    # haze_start_ramp_gu from haze_handoff_gu / haze_handoff_band_gu, so the
    # haze ramps in exactly over the mid band's L2 fade-out.
    "haze_res_divisor": 4,
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
    # gain = -ln 0.85 / tau = 14,136 -> 14,140). The DEFAULT is Mark's live
    # choice 2026-10-03 ("this works well"): 131,700 = 9.3x that derivation
    # (Player Start column alpha ~0.78), kTileHazeGain in far_field_test.cc.
    # tile_haze_brightness below stays calibrated at the 14,140 derivation.
    # 131,700 -> 17,676.47 (9 dial steps down; Player Start column alpha
    # ~0.18): Mark, live 2026-10-04 on spike/rock-specks ("works better").
    "tile_haze_gain": 17676.47, "tile_haze_edge_frac": 0.2,
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
    # spike/rock-specks (Python, read at use; re-push sources): the tile
    # field's ONE density (haze AND rocks) gets clumps/voids and a lumpy
    # outline. tile_noise_sharpness stretches the noise (1 = off);
    # tile_shape_warp (0 = off, < 0.9) warps the sphere's edge at
    # tile_shape_warp_scale_frac x the field radius.
    "tile_noise_sharpness": 2.5, "tile_shape_warp": 0.35,
    "tile_shape_warp_scale_frac": 0.6,
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
    # near_small_density 0.008 -> 0.010, near_small_mesh_gu 20 -> 15:
    # Mark, live 2026-10-03 (slightly more small rocks, as billboards closer in).
    "near_small_density": 0.010, "near_small_r_min": 0.05, "near_small_r_max": 0.5,
    "near_small_exponent": 2.5, "near_small_cell_gu": 10.0, "near_small_mesh_gu": 15.0,
    "near_small_billboard_gu": 90.0, "near_small_max": 4000,   # 3x (Mark, live 2026-10-04)
    # near_large_density 1.25e-4 -> 6.25e-5, near_large_mesh_gu 50 -> 60,
    # near_large_billboard_gu 60 -> 90: Mark, live 2026-10-03 (fewer big
    # asteroids but visible a bit further).
    "near_large_density": 6.25e-5, "near_large_r_min": 1.0, "near_large_r_max": 5.0,
    # near_large_cell_gu 20 -> 50, near_large_max 1000 -> 4000 and the far
    # shell: rock-real Part 1, 2026-10-03 (every big-asteroid silhouette is a
    # real rock). With near_large_far_gu > near_large_billboard_gu the SAME
    # large rocks stream on as billboards out to near_large_far_gu, fading
    # out translucent over the last near_large_far_fade_gu; a large billboard
    # at or below near_large_min_px on screen draws nothing (1 px fade-in
    # above it, blended in from the mesh edge). 250, not the 400 target:
    # 400 cost +1.5 ms CPU per frame in the Beol 4 inside bench, 250 ~ +0.4.
    # 50 GU cells keep 250 (+ margin) under the 33-cells-per-axis cap;
    # near_large_max 4000 covers a full-density field's ~770 large rocks in a
    # 60 degree view at 250 GU (~2,300 at 90 degrees, ~3,200 at 400 GU).
    "near_large_exponent": 2.5, "near_large_cell_gu": 50.0, "near_large_mesh_gu": 60.0,
    "near_large_billboard_gu": 270.0, "near_large_max": 4000,   # 3x (Mark, live 2026-10-04)
    # Space dust inside rock fields (Python, read at use; Mark, live
    # 2026-10-03): the dust pass's density is multiplied by up to this at
    # full field density (tile field interior or a=1 belt), ramping with the
    # field's a(x) at the player. 1.0 = off.
    "field_dust_mult": 10.0,
    "near_large_far_gu": 0.0,   # far shell OFF during the near-only strip-back (Mark, 2026-10-03)
    "near_large_far_fade_gu": 40.0, "near_large_min_px": 1.5,
    "near_small_min_px": 2.5,   # Mark, live 2026-10-04 (3x ranges)
    # The far shell at dash speed (rock-real review, 2026-10-03): a stream
    # whose centre moved more than near_far_shell_max_step_gu since the last
    # (25 GU = 1,500 GU/s at 60 Hz, 3.75x in-system warp) shrinks the large
    # reach to near_large_billboard_gu; it regrows by at most
    # near_far_shell_regrow_gu per stream once slower (no one-frame hitch).
    "near_far_shell_max_step_gu": 25.0, "near_far_shell_regrow_gu": 20.0,
    "near_fade_gu": 4.0, "near_handoff_fade_gu": 0.0, "near_tumble_scale": 0.05, "near_dash_collapse_step_gu": 25.0, "near_stream_margin_gu": 10.0, "collide_cooldown_s": 0.5,
    # Large-rock collision response (Python, read at use; rock-fields Task 8,
    # engine/rocks/scenery_contact.py): damage = KE damage x
    # collide_damage_scale x min(1, rock radius / collide_ref_radius_gu).
    "collide_damage_scale": 1.0, "collide_ref_radius_gu": 5.0,
    # Rock fields mid band (native; rock-fields Task 10). MUST equal MidDials
    # in native/src/renderer/include/renderer/rock_mid.h. Three nested tile
    # levels (150 / 600 / 2,400 GU cubes fixed in system coordinates): L0
    # fades in over [mid_in_lo_gu, mid_in_hi_gu], each level boundary b
    # crossfades over [b (1 - mid_xfade_frac), b], and L2 fades out over the
    # last haze_handoff_band_gu before haze_handoff_gu. A tile shows a
    # collection sprite with chance density x mid_fill; mid_max_sprites caps
    # one camera build, nearest first.
    "mid_l0_tile_gu": 150.0, "mid_l1_tile_gu": 600.0, "mid_l2_tile_gu": 2400.0,
    # mid_in_lo_gu 80 -> 100, mid_in_hi_gu 150 -> 170: Mark, live 2026-10-03
    # (keeps mid sprites outside the widened near_large_billboard_gu, 90).
    "mid_in_lo_gu": 100.0, "mid_in_hi_gu": 170.0,
    "mid_l0_out_gu": 600.0, "mid_l1_out_gu": 2400.0, "mid_xfade_frac": 0.25,
    # spike/rock-specks (2026-10-04): the haze ramps in over [600, 1500] GU,
    # behind the speck band (was 8000 / 2000, behind the mid band's L2).
    "haze_handoff_gu": 1500.0, "haze_handoff_band_gu": 900.0,
    # Speck band (SPIKE, native; MUST equal SpeckDials in rock_speck.h): the
    # near band's large rocks past their billboard edge as lit specks, out to
    # speck_out_gu (fading over speck_out_fade_gu). Beyond speck_keep_d0_gu
    # whole cells thin as (d0 / d)^speck_keep_power, fading over speck_keep_band of their
    # hash. Re-streamed every speck_restream_gu of travel. speck_band_gain
    # multiplies speck_gain for this band only.
    "speck_out_gu": 1500.0, "speck_out_fade_gu": 400.0,
    "speck_keep_d0_gu": 350.0, "speck_keep_band": 0.25, "speck_keep_power": 3.0,
    "speck_restream_gu": 50.0, "speck_band_gain": 0.25,
    "mid_fill": 1.0, "mid_sprite_scale": 1.0, "mid_max_sprites": 4000,
}

NATIVE_KEYS = frozenset({"imp_hi", "imp_lo", "speck_hi", "speck_lo", "p_min",
    "slab_sigmas", "speck_gain", "haze_gain", "haze_steps", "haze_res_divisor",
    "near_small_density", "near_small_r_min", "near_small_r_max",
    "near_small_exponent", "near_small_cell_gu", "near_small_mesh_gu",
    "near_small_billboard_gu", "near_small_max",
    "near_large_density", "near_large_r_min", "near_large_r_max",
    "near_large_exponent", "near_large_cell_gu", "near_large_mesh_gu",
    "near_large_billboard_gu", "near_large_max",
    "near_large_far_gu", "near_large_far_fade_gu", "near_large_min_px", "near_small_min_px",
    "near_far_shell_max_step_gu", "near_far_shell_regrow_gu",
    "near_fade_gu", "near_handoff_fade_gu", "near_tumble_scale", "near_dash_collapse_step_gu", "near_stream_margin_gu", "collide_cooldown_s",
    "mid_l0_tile_gu", "mid_l1_tile_gu", "mid_l2_tile_gu", "mid_in_lo_gu",
    "mid_in_hi_gu", "mid_l0_out_gu", "mid_l1_out_gu", "mid_xfade_frac",
    "haze_handoff_gu", "haze_handoff_band_gu", "mid_fill", "mid_sprite_scale",
    "mid_max_sprites",
    "speck_out_gu", "speck_out_fade_gu", "speck_keep_d0_gu", "speck_keep_band",
    "speck_keep_power", "speck_restream_gu", "speck_band_gain"})

# Ints that must never reach 0 (a zero cap would silently delete the whole
# tier, not shrink it).
_INT_FLOOR_1 = ("haze_steps", "haze_res_divisor", "tile_haze_noise_octaves", "tile_haze_steps",
               "belt_noise_octaves", "near_small_max", "near_large_max",
               "mid_max_sprites")

# / L O order: the look dials Mark tunes live come first, the rest after.
_LOOK_FIRST = ("tile_shape_warp", "tile_noise_sharpness", "tile_haze_brightness",
               "speck_band_gain", "speck_out_gu", "speck_keep_d0_gu",
               "haze_handoff_gu", "haze_handoff_band_gu",
               "near_small_density", "near_large_density",
               "near_small_mesh_gu", "near_small_billboard_gu",
               "near_large_mesh_gu", "near_large_billboard_gu",
               "near_large_far_gu", "mid_fill", "mid_sprite_scale", "mid_l0_out_gu",
               "mid_l1_out_gu", "haze_brightness",
               "haze_gain", "tile_haze_gain",
               "tile_haze_noise_contrast", "belt_noise_contrast",
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
