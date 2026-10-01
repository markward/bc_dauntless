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
