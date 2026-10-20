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
    assert len(plating_dials.DIAL_ORDER) <= 16


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
