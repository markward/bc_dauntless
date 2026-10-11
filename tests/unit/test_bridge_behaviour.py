"""Material behaviour over time (spec §13.2)."""
import math

import pytest

from engine.bridge_editor import behaviour as bh

ALCOVE = {"fade_s": 0.5, "modifiers": [
    {"type": "emitter", "scope": ["green"], "tint": [1, 1, 1], "level": 1},
    {"type": "emitter", "scope": ["red"], "tint": [1, 0.1, 0.1], "level": 0.5},
    {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 2.0, "min": 0.2,
     "phase": 0.0}]}


def test_state_names_and_indices():
    assert [bh.state_name(i) for i in range(6)] == ["green", "yellow", "red", "offline",
                                                    "special", "green"]
    assert bh.state_index("offline") == 3


def test_emitters_add_and_animations_multiply():
    m = {"modifiers": [
        {"type": "emitter", "scope": ["red"], "tint": [1, 0, 0], "level": 1},
        {"type": "emitter", "scope": ["red"], "tint": [0, 0, 1], "level": 0.5},
        {"type": "animation", "scope": ["red"], "shape": "square", "period_s": 1, "duty": 0.5,
         "min": 0.5},
        {"type": "animation", "scope": ["red"], "shape": "square", "period_s": 1, "duty": 0.5,
         "min": 0.5, "phase": 0.5}]}
    rgb, k = bh.output(m, "red", 0.25)          # first on (1), second off (0.5)
    assert rgb == pytest.approx((0.5, 0.0, 0.25))
    assert k == pytest.approx(0.75)


def test_out_of_scope_and_parked_modifiers_do_nothing():
    assert bh.output(ALCOVE, "yellow", 0.0) == ((0.0, 0.0, 0.0), 0.0)
    m = {"modifiers": [{"type": "emitter", "scope": [], "tint": [1, 1, 1], "level": 1}]}
    assert bh.output(m, "green", 0.0) == ((0.0, 0.0, 0.0), 0.0)


def test_the_animation_phase_shifts_the_sine():
    a = dict(ALCOVE["modifiers"][2])
    assert bh.wave_factor(a, 0.0) == pytest.approx(1.0)
    assert bh.wave_factor(dict(a, phase=0.5), 0.0) == pytest.approx(0.2)


def test_white_lights_every_state():
    for s in bh.STATES:
        assert bh.output(bh.WHITE, s, 0.0) == ((1.0, 1.0, 1.0), 1.0)


def test_fade_is_continuous_across_two_changes():
    f = bh.StateFade("red")
    f.set_state("green")
    f.advance(0.25)
    before = f.output(ALCOVE, 0.25)
    f.set_state("red")
    after = f.output(ALCOVE, 0.25)
    assert after[1] == pytest.approx(before[1])
    assert all(math.isfinite(c) for c in after[0])
    f.advance(10.0)
    assert f.output(ALCOVE, 10.25) == bh.output(ALCOVE, "red", 10.25)
