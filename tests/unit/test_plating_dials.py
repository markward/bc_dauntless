"""SPIKE (damage redesign): plating dials push the slot order frame.cc reads."""
import re
from pathlib import Path

from engine.appc import plating_dials

FRAME_CC = Path(__file__).resolve().parents[2] / "native/src/renderer/frame.cc"


def test_python_defaults_match_the_native_defaults():
    src = FRAME_CC.read_text()
    block = src.split("namespace dauntless_plating {", 1)[1].split("};", 1)[0]
    native = [float(v) for v in re.findall(r"(-?\d+\.\d+)f", block)]
    assert native[:len(plating_dials.DIAL_ORDER)] == plating_dials.params()
    assert len(plating_dials.DIAL_ORDER) <= 32


def test_step_pushes_and_clamps(monkeypatch):
    pushed = []
    monkeypatch.setattr(plating_dials, "push", lambda: pushed.append(plating_dials.params()))
    plating_dials.reset()
    plating_dials._step("enabled", +1)
    assert plating_dials.current()["enabled"] == 1.0
    plating_dials._step("enabled", -1)
    plating_dials._step("enabled", -1)
    assert plating_dials.current()["enabled"] == 0.0
    assert len(pushed) == 3
    plating_dials.reset()


def test_env_starts_the_layer_off_for_perf_ab(monkeypatch):
    monkeypatch.setattr(plating_dials, "push", lambda: None)
    import engine.dev_dial_groups as groups
    monkeypatch.setattr(groups, "register_group", lambda *a, **k: None)
    plating_dials.reset()
    monkeypatch.setenv("DAUNTLESS_PLATING", "0")
    plating_dials.register()
    assert plating_dials.current()["enabled"] == 0.0
    plating_dials.reset()


def test_uneven_breach_dials_sit_in_slots_22_to_25():
    order = plating_dials.DIAL_ORDER
    assert order[22:26] == ("toughness_spread", "breach_lumps",
                            "deck_break_wear", "interior")
    d = plating_dials.DEFAULTS
    assert (d["toughness_spread"], d["breach_lumps"],
            d["deck_break_wear"], d["interior"]) == (0.6, 1.0, 6.0, 1.0)
    assert len(plating_dials.params()) >= 26
    assert plating_dials._MAX["interior"] == 1.0
    assert plating_dials._STEP["toughness_spread"] == 0.1
    assert plating_dials._STEP["breach_lumps"] == 0.25
    assert plating_dials._STEP["deck_break_wear"] == 0.25
    assert plating_dials._STEP["interior"] == 1.0


def test_force_program_dial_is_slot_26_and_env_driven(monkeypatch):
    d = plating_dials
    assert d.DIAL_ORDER[26] == "force_program"
    assert d.DEFAULTS["force_program"] == 0.0
    assert (d._MAX["force_program"], d._STEP["force_program"]) == (1.0, 1.0)
    assert len(d.params()) >= 27
    monkeypatch.setattr(d, "push", lambda: None)
    import engine.dev_dial_groups as groups
    monkeypatch.setattr(groups, "register_group", lambda *a, **k: None)
    d.reset()
    monkeypatch.setenv("DAUNTLESS_PLATING_FORCE_PROGRAM", "1")
    d.register()
    assert d.current()["force_program"] == 1.0
    d.reset()



def test_lod_footprint_dial_is_slot_27_and_env_driven(monkeypatch):
    """Pixel-footprint LOD (perf P-12): the plating short path runs where a
    pixel's footprint exceeds lod_footprint x member width; <= 0 disables
    it. DAUNTLESS_PLATING_LOD sets it at dev boot for a perf A/B."""
    d = plating_dials
    assert d.DIAL_ORDER[27] == "lod_footprint"
    assert d.DEFAULTS["lod_footprint"] == 1.0
    assert d._STEP["lod_footprint"] == 0.25
    assert len(d.params()) == 28
    monkeypatch.setattr(d, "push", lambda: None)
    import engine.dev_dial_groups as groups
    monkeypatch.setattr(groups, "register_group", lambda *a, **k: None)
    d.reset()
    monkeypatch.setenv("DAUNTLESS_PLATING_LOD", "0")
    d.register()
    assert d.current()["lod_footprint"] == 0.0
    monkeypatch.setenv("DAUNTLESS_PLATING_LOD", "2.5")
    d.register()
    assert d.current()["lod_footprint"] == 2.5
    monkeypatch.setenv("DAUNTLESS_PLATING_LOD", "junk")
    d.register()
    assert d.current()["lod_footprint"] == d.defaults()["lod_footprint"]
    d.reset()


# ---- Developer Options "Hull damage" (phase 4 §2.5) -------------------------

def _no_register(monkeypatch):
    monkeypatch.setattr(plating_dials, "push", lambda: None)
    import engine.dev_dial_groups as groups
    monkeypatch.setattr(groups, "register_group", lambda *a, **k: None)


def test_register_prefers_the_native_defaults(monkeypatch):
    from engine import renderer
    _no_register(monkeypatch)
    native = [plating_dials.DEFAULTS[k] for k in plating_dials.DIAL_ORDER]
    native[plating_dials.DIAL_ORDER.index("soot")] = 0.4000000059604645  # 0.4f
    native += [0.0] * (32 - len(native))
    monkeypatch.setattr(renderer, "plating_param_defaults", lambda: native,
                        raising=False)
    try:
        plating_dials.register()
        # float32 comes back as the shortest decimal that round-trips it
        assert plating_dials.defaults()["soot"] == 0.4
        assert plating_dials.current()["soot"] == 0.4
        plating_dials.reset()
        assert plating_dials.current()["soot"] == 0.4
    finally:
        plating_dials._defaults = dict(plating_dials.DEFAULTS)
        plating_dials.reset()


def test_register_falls_back_to_DEFAULTS_without_the_binding(monkeypatch):
    from engine import renderer
    _no_register(monkeypatch)

    def _missing():
        raise AttributeError("plating_param_defaults")
    monkeypatch.setattr(renderer, "plating_param_defaults", _missing,
                        raising=False)
    assert plating_dials.native_defaults() is None
    plating_dials.register()
    assert plating_dials.defaults() == plating_dials.DEFAULTS
    plating_dials.reset()


def test_set_value_clamps_and_pushes(monkeypatch):
    pushed = []
    monkeypatch.setattr(plating_dials, "push", lambda: pushed.append(plating_dials.params()))
    plating_dials.reset()
    plating_dials.set_value("interior", 5.0)
    assert plating_dials.current()["interior"] == 1.0
    plating_dials.set_value("breach_wear", -3.0)
    assert plating_dials.current()["breach_wear"] == 0.0
    assert len(pushed) == 2
    plating_dials.set_values({"breach_wear": 4.5, "soot": 0.5})
    assert len(pushed) == 3
    assert plating_dials.current()["soot"] == 0.5
    plating_dials.reset()
