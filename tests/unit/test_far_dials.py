import re
from pathlib import Path
from engine.rocks import far_dials


def test_native_defaults_match_the_cpp_header():
    """FarDials / TierDials / GenParams defaults MUST equal DEFAULTS."""
    hdr = (Path(__file__).parents[2] / "native/src/renderer/include/renderer").resolve()
    text = (hdr / "far_math.h").read_text() + (hdr / "far_field.h").read_text()
    for key in far_dials.NATIVE_KEYS:
        m = re.search(r"\b%s\s*=\s*([0-9.e+-]+)f?" % key, text)
        assert m, key
        assert float(m.group(1)) == float(far_dials.DEFAULTS[key]), key


def test_step_rules():
    d = far_dials.DEFAULTS
    assert far_dials.step(d, "haze_gain", +1)["haze_gain"] == 270.0 * 1.25
    assert far_dials.step(d, "size_classes", -1)["size_classes"] == 3
    assert far_dials.step({**d, "max_far_rocks": 1}, "max_far_rocks", -1)["max_far_rocks"] == 1


def test_registers_the_far_group_without_new_keys():
    from engine import dev_dial_groups
    far_dials.register()
    assert "far" in dev_dial_groups.groups()


def test_tile_haze_gain_is_the_cpp_derivation():
    """The default tile_haze_gain IS kTileHazeGain in far_field_test.cc,
    where FarHazeSphere.DefaultTileGainHitsTheStatedTarget derives it (alpha
    0.15 +- 0.03 from Beol 4's Player Start). Read, not copied, so the two
    cannot drift."""
    src = (Path(__file__).parents[2] / "native/tests/renderer/far_field_test.cc").read_text()
    m = re.search(r"kTileHazeGain\s*=\s*([0-9.e+-]+)f", src)
    assert m
    assert far_dials.DEFAULTS["tile_haze_gain"] == float(m.group(1))
    assert far_dials.DEFAULTS["tile_haze_edge_frac"] == 0.2
    assert "tile_haze_gain" not in far_dials.NATIVE_KEYS
    assert "tile_haze_edge_frac" not in far_dials.NATIVE_KEYS


def _cpp_constant(name):
    src = (Path(__file__).parents[2] / "native/tests/renderer/far_field_test.cc").read_text()
    m = re.search(r"%s\s*=\s*([0-9.e+-]+)f" % name, src)
    assert m, name
    return float(m.group(1))


def test_haze_brightness_defaults_are_the_cpp_derivations():
    """haze_brightness / tile_haze_brightness ARE kHazeBrightness /
    kTileHazeBrightness in far_field_test.cc, where the
    Default*BrightnessShowsTwentyFiveOverBlack tests derive them (25/255
    displayed under the production lighting of Vesuvi mid-band and Beol 4's
    Player Start). Read, not copied, so the two cannot drift. Python-owned:
    they ride per source as `brightness`, never through far_set_dials."""
    assert far_dials.DEFAULTS["haze_brightness"] == _cpp_constant("kHazeBrightness")
    assert far_dials.DEFAULTS["tile_haze_brightness"] == _cpp_constant("kTileHazeBrightness")
    assert "haze_brightness" not in far_dials.NATIVE_KEYS
    assert "tile_haze_brightness" not in far_dials.NATIVE_KEYS


def test_the_look_dials_come_first_in_the_dial_keys_order():
    """Mark tunes the look live with / L O; the haze and speck dials lead."""
    from engine.rocks import far_dials
    assert far_dials.DIAL_ORDER[:6] == (
        "haze_brightness", "tile_haze_brightness", "haze_gain",
        "tile_haze_gain", "speck_gain", "tile_haze_edge_frac")
    assert sorted(far_dials.DIAL_ORDER) == sorted(far_dials.DEFAULTS)
