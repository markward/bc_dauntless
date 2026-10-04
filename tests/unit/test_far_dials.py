import re
from pathlib import Path
from engine.rocks import far_dials


# rock_near.h NearDials / NearClassDials defaults (rock-fields Task 4). The
# header nests them (small.density, large.r_min, ...), so they are listed
# here by hand: change rock_near.h and this table together.
_NEAR_CPP_DEFAULTS = {
    # Mark, live 2026-10-03: near_small_density 0.008 -> 0.010, near_small_mesh_gu
    # 20 -> 15; near_large_density 1.25e-4 -> 6.25e-5, near_large_mesh_gu 50 -> 60,
    # near_large_billboard_gu 60 -> 90.
    "near_small_density": 0.010, "near_small_r_min": 0.05, "near_small_r_max": 0.5,
    "near_small_exponent": 2.5, "near_small_cell_gu": 10.0, "near_small_mesh_gu": 15.0,
    "near_small_billboard_gu": 90.0, "near_small_max": 4000,
    "near_large_density": 1.0 / 16000.0, "near_large_r_min": 1.0, "near_large_r_max": 5.0,
    # rock-real Part 1, 2026-10-03: near_large_cell_gu 20 -> 50, near_large_max
    # 1000 -> 4000; the pixel floors (NearDials large_min_px / small_min_px).
    "near_large_exponent": 2.5, "near_large_cell_gu": 50.0, "near_large_mesh_gu": 60.0,
    "near_large_billboard_gu": 405.0, "near_large_max": 4000,
    # near_large_min_px 1.5 -> 0: review I1, 2026-10-04 (the speck hand-off has no floor).
    "near_large_min_px": 0.0, "near_small_min_px": 2.5,
    "near_fade_gu": 4.0, "near_tumble_scale": 0.05, "near_dash_collapse_step_gu": 25.0, "near_stream_margin_gu": 10.0, "collide_cooldown_s": 0.5,
}


def test_near_defaults_match_rock_near_h():
    """NearDials defaults (native/src/renderer/include/renderer/rock_near.h)
    MUST equal DEFAULTS; every near key is native (parsed in Task 7)."""
    for key, value in _NEAR_CPP_DEFAULTS.items():
        assert key in far_dials.DEFAULTS, key
        assert key in far_dials.NATIVE_KEYS, key
        assert far_dials.DEFAULTS[key] == value, key
    assert isinstance(far_dials.DEFAULTS["near_small_max"], int)
    assert isinstance(far_dials.DEFAULTS["near_large_max"], int)


# SpeckDials (rock_speck.h) field per far_dials key.
_SPECK_CPP_FIELDS = {
    "speck_out_gu": "out_gu", "speck_out_fade_gu": "out_fade_gu",
    "speck_keep_d0_gu": "keep_d0_gu", "speck_keep_power": "keep_power",
    "speck_keep_band": "keep_band", "speck_restream_gu": "restream_gu",
    "speck_band_gain": "gain",
}
_PUFF_CPP_FIELDS = {
    "puff_count": "count", "puff_size_frac": "size_frac", "puff_opacity": "opacity",
    "puff_brightness": "brightness", "puff_start_gu": "start_gu",
    "puff_ramp_gu": "ramp_gu", "puff_near_fade": "near_fade",
    "puff_belt_count": "belt_count", "puff_belt_size_h": "belt_size_h",
}


def test_puff_defaults_match_rock_puffs_h():
    text = (Path(__file__).parents[2]
            / "native/src/renderer/include/renderer/rock_puffs.h").read_text()
    for key, field in _PUFF_CPP_FIELDS.items():
        m = re.search(r"\b%s\s*=\s*([0-9.e+-]+)f?" % field, text)
        assert m, key
        assert float(m.group(1)) == float(far_dials.DEFAULTS[key]), key


def test_speck_band_defaults_match_rock_speck_h():
    hdr = (Path(__file__).parents[2] / "native/src/renderer/include/renderer/rock_speck.h")
    text = hdr.read_text()
    for key, field in _SPECK_CPP_FIELDS.items():
        m = re.search(r"\b%s\s*=\s*([0-9.e+-]+)f?" % field, text)
        assert m, key
        assert float(m.group(1)) == float(far_dials.DEFAULTS[key]), key


def test_native_defaults_match_the_cpp_header():
    """FarDials / TierDials defaults MUST equal DEFAULTS."""
    hdr = (Path(__file__).parents[2] / "native/src/renderer/include/renderer").resolve()
    text = (hdr / "far_math.h").read_text() + (hdr / "far_field.h").read_text()
    for key in far_dials.NATIVE_KEYS - set(_NEAR_CPP_DEFAULTS) - set(_SPECK_CPP_FIELDS) - set(_PUFF_CPP_FIELDS):
        m = re.search(r"\b%s\s*=\s*([0-9.e+-]+)f?" % key, text)
        assert m, key
        assert float(m.group(1)) == float(far_dials.DEFAULTS[key]), key


def test_step_rules():
    d = far_dials.DEFAULTS
    assert far_dials.step(d, "speck_gain", +1)["speck_gain"] == 4.0 * 1.25
    assert far_dials.step(d, "puff_count", -1)["puff_count"] == 360
    assert far_dials.step({**d, "puff_count": 1}, "puff_count", -1)["puff_count"] == 1


def test_the_belt_generator_dials_are_gone():
    """Rock-fields (2026-10-02): the far tier generates no rocks of its own."""
    for k in ("k_ref", "size_classes", "cells_per_range", "max_far_rocks",
              "cell_cache_max", "max_cells_per_axis"):
        assert k not in far_dials.DEFAULTS and k not in far_dials.NATIVE_KEYS, k


def test_registers_the_rock_fields_group_without_new_keys():
    from engine import dev_dial_groups
    far_dials.register()
    assert "rock fields" in dev_dial_groups.groups()


def test_dial_group_is_rock_fields_with_look_dials_first(monkeypatch):
    from engine import dev_dial_groups
    registered = {}
    monkeypatch.setattr(dev_dial_groups, "register_group",
                        lambda name, order, cur, step: registered.setdefault(name, order))
    far_dials.register()
    assert list(registered) == ["rock fields"]
    assert registered["rock fields"][0] == "puff_opacity"


def test_tile_edge_frac_is_a_python_dial():
    assert far_dials.DEFAULTS["tile_edge_frac"] == 0.2
    assert "tile_edge_frac" not in far_dials.NATIVE_KEYS


def test_the_volumetric_haze_dials_are_gone():
    """The volumetric haze was removed (puffs replace it): none of its dials
    survive, native or Python-owned."""
    for k in ("slab_sigmas", "haze_gain", "haze_steps", "haze_res_divisor",
              "haze_start_gu", "haze_start_ramp_gu", "haze_brightness",
              "tile_haze_gain", "tile_haze_brightness", "tile_haze_steps"):
        assert k not in far_dials.DEFAULTS and k not in far_dials.NATIVE_KEYS, k


def test_the_look_dials_come_first_in_the_dial_keys_order():
    """Mark tunes the look live with / L O; the rock-fields look dials
    lead."""
    from engine.rocks import far_dials
    assert far_dials.DIAL_ORDER[:18] == (
        "puff_opacity", "puff_size_frac", "puff_count", "puff_brightness",
        "puff_belt_count", "puff_belt_size_h",
        "tile_shape_warp", "tile_noise_sharpness",
        "speck_band_gain", "speck_out_gu", "speck_keep_d0_gu",
        "near_small_density", "near_large_density", "near_small_mesh_gu",
        "near_small_billboard_gu", "near_large_mesh_gu", "near_large_billboard_gu",
        "collide_damage_scale")
    assert sorted(far_dials.DIAL_ORDER) == sorted(far_dials.DEFAULTS)


def test_speck_gain_defaults_to_four():
    """Mark, live 2026-10-02: "spec gain needs to come up to about 4"."""
    assert far_dials.DEFAULTS["speck_gain"] == 4.0


def test_tile_noise_dials():
    """Tile-field noise (2026-10-02): Python-owned, ride per source."""
    d = far_dials.DEFAULTS
    assert d["tile_noise_scale_gu"] == 250.0
    assert d["tile_noise_contrast"] == 0.8
    assert d["tile_noise_octaves"] == 3
    for k in ("tile_noise_scale_gu", "tile_noise_contrast",
              "tile_noise_octaves"):
        assert k not in far_dials.NATIVE_KEYS, k
    assert isinstance(d["tile_noise_octaves"], int)
    # Int counts floor at 1; the contrast (a float) may reach 0.
    assert far_dials.step({**d, "tile_noise_octaves": 1}, "tile_noise_octaves",
                          -1)["tile_noise_octaves"] == 1
    assert far_dials.step({**d, "tile_noise_contrast": 0.0},
                          "tile_noise_contrast", -1)["tile_noise_contrast"] == 0.0


def test_belt_noise_dials():
    """Rock-fields R1 (2026-10-02): belts carry noise too; Python-owned."""
    d = far_dials.DEFAULTS
    assert d["belt_noise_scale_gu"] == 4000.0
    assert d["belt_noise_contrast"] == 0.8
    assert d["belt_noise_octaves"] == 3 and isinstance(d["belt_noise_octaves"], int)
    for k in ("belt_noise_scale_gu", "belt_noise_contrast", "belt_noise_octaves"):
        assert k not in far_dials.NATIVE_KEYS, k
    assert far_dials.step({**d, "belt_noise_octaves": 1},
                          "belt_noise_octaves", -1)["belt_noise_octaves"] == 1


def test_noise_contrast_dials_clamp_to_one():
    d = dict(far_dials.DEFAULTS, belt_noise_contrast=0.9)
    assert far_dials.step(d, "belt_noise_contrast", +1)["belt_noise_contrast"] == 1.0
    d = dict(far_dials.DEFAULTS, tile_noise_contrast=0.9)
    assert far_dials.step(d, "tile_noise_contrast", +1)["tile_noise_contrast"] == 1.0


def test_the_far_shell_and_dithered_hand_off_dials_are_gone():
    """The near band's far shell and its dithered mesh <-> billboard hand-off
    were removed (the hand-off is a hard swap); the pixel floors stay."""
    for k in ("near_large_far_gu", "near_large_far_fade_gu", "near_far_shell_max_step_gu",
              "near_far_shell_regrow_gu", "near_handoff_fade_gu"):
        assert k not in far_dials.DEFAULTS and k not in far_dials.NATIVE_KEYS, k
    for k in ("near_large_min_px", "near_small_min_px"):
        assert k in far_dials.NATIVE_KEYS, k


def test_the_old_tile_haze_names_are_gone():
    """The tile field's noise and edge dials shape the field, not a haze:
    tile_haze_noise_* / tile_haze_edge_frac are tile_noise_* / tile_edge_frac."""
    for k in far_dials.DEFAULTS:
        assert "haze" not in k, k
    for k in ("tile_noise_scale_gu", "tile_noise_contrast", "tile_noise_octaves",
              "tile_edge_frac"):
        assert k in far_dials.DEFAULTS, k


def test_the_mid_band_dials_are_gone():
    """The mid band (baked collection sprites) was removed: none of its
    dials survive."""
    for k in ("mid_l0_tile_gu", "mid_l1_tile_gu", "mid_l2_tile_gu", "mid_in_lo_gu",
              "mid_in_hi_gu", "mid_l0_out_gu", "mid_l1_out_gu", "mid_xfade_frac",
              "haze_handoff_gu", "haze_handoff_band_gu", "mid_fill", "mid_sprite_scale",
              "mid_max_sprites"):
        assert k not in far_dials.DEFAULTS and k not in far_dials.NATIVE_KEYS, k
