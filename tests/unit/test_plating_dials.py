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
    assert len(d.params()) == 27
    monkeypatch.setattr(d, "push", lambda: None)
    import engine.dev_dial_groups as groups
    monkeypatch.setattr(groups, "register_group", lambda *a, **k: None)
    d.reset()
    monkeypatch.setenv("DAUNTLESS_PLATING_FORCE_PROGRAM", "1")
    d.register()
    assert d.current()["force_program"] == 1.0
    d.reset()
