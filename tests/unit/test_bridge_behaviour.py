"""Material behaviour over time (spec §13.2, §14: Emission is a Finish level;
State modifiers replace it per state; Animations multiply; Transitions set
the blend into their states)."""
import math

import pytest

from engine.bridge_editor import behaviour as bh

ALCOVE = {"emission": 0, "modifiers": [
    {"type": "state", "scope": ["green"], "tint": [1, 1, 1], "level": 1},
    {"type": "state", "scope": ["red"], "tint": [1, 0.1, 0.1], "level": 0.5},
    {"type": "animation", "scope": ["red"], "shape": "sine", "period_s": 2.0, "min": 0.2,
     "phase": 0.0}]}


def test_state_names_and_indices():
    assert [bh.state_name(i) for i in range(6)] == ["green", "yellow", "red", "offline",
                                                    "special", "green"]
    assert bh.state_index("offline") == 3


def test_states_add_and_animations_multiply():
    m = {"modifiers": [
        {"type": "state", "scope": ["red"], "tint": [1, 0, 0], "level": 1},
        {"type": "state", "scope": ["red"], "tint": [0, 0, 1], "level": 0.5},
        {"type": "animation", "scope": ["red"], "shape": "square", "period_s": 1, "duty": 0.5,
         "min": 0.5},
        {"type": "animation", "scope": ["red"], "shape": "square", "period_s": 1, "duty": 0.5,
         "min": 0.5, "phase": 0.5}]}
    rgb, k = bh.output(m, "red", 0.25)          # first on (1), second off (0.5)
    assert rgb == pytest.approx((0.5, 0.0, 0.25))
    assert k == pytest.approx(0.75)


def test_the_finish_emission_glows_white_in_every_state_but_offline():
    """Mark's com lights (Map 8, no map): raise the level, it glows -- no
    modifier needed. Power offline stays dark, as an `_emissive` map does."""
    m = {"emission": 3}
    for s in ("green", "yellow", "red", "special"):
        assert bh.output(m, s, 0.0) == ((3.0, 3.0, 3.0), 3.0)
    assert bh.output(m, "offline", 0.0) == ((0.0, 0.0, 0.0), 0.0)


def test_the_default_emission_is_the_map_as_painted_else_none():
    assert bh.output({}, "green", 0.0, has_map=True) == ((1.0, 1.0, 1.0), 1.0)
    assert bh.output({}, "green", 0.0) == ((0.0, 0.0, 0.0), 0.0)


def test_a_state_modifier_replaces_the_emission_in_its_states_only():
    m = {"emission": 2, "modifiers": [
        {"type": "state", "scope": ["red", "offline"], "tint": [1, 0, 0], "level": 0.5}]}
    assert bh.output(m, "red", 0.0) == ((0.5, 0.0, 0.0), 0.5)
    assert bh.output(m, "offline", 0.0) == ((0.5, 0.0, 0.0), 0.5)   # lit on reserve power
    assert bh.output(m, "yellow", 0.0) == ((2.0, 2.0, 2.0), 2.0)


def test_an_animation_alone_pulses_the_emission():
    m = {"modifiers": [{"type": "animation", "scope": ["red"], "shape": "square",
                        "period_s": 1, "duty": 0.5, "min": 0.25}]}
    assert bh.output(m, "red", 0.75, has_map=True) == ((0.25, 0.25, 0.25), 0.25)
    assert bh.drives_glow(m) and bh.drives_glow({"emission": 0})
    assert not bh.drives_glow({"roughness": 0.2})
    assert not bh.drives_glow({"modifiers": [{"type": "transition", "scope": [], "seconds": 1}]})


def test_parked_modifiers_do_nothing():
    m = {"modifiers": [{"type": "state", "scope": [], "tint": [1, 0, 0], "level": 4}]}
    assert bh.output(m, "green", 0.0) == ((0.0, 0.0, 0.0), 0.0)
    assert bh.output(ALCOVE, "yellow", 0.0) == ((0.0, 0.0, 0.0), 0.0)


def test_the_animation_phase_shifts_the_sine():
    a = dict(ALCOVE["modifiers"][2])
    assert bh.wave_factor(a, 0.0) == pytest.approx(1.0)
    assert bh.wave_factor(dict(a, phase=0.5), 0.0) == pytest.approx(0.2)


def test_white_lights_every_state():
    for s in bh.STATES:
        assert bh.output(bh.WHITE, s, 0.0) == ((1.0, 1.0, 1.0), 1.0)


def test_a_transition_sets_the_blend_into_its_states_else_half_a_second():
    m = dict(ALCOVE, modifiers=ALCOVE["modifiers"] + [
        {"type": "transition", "scope": ["red"], "seconds": 0.2}])
    assert bh.transition_s(m, "red") == 0.2
    assert bh.transition_s(m, "green") == bh.DEFAULT_FADE_S == 0.5
    f = bh.StateFade("green")
    f.set_state("red")
    f.advance(0.2)
    assert f.output(m, 0.2) == bh.output(m, "red", 0.2)           # done after 0.2 s
    g = bh.StateFade("red")
    g.set_state("green")
    g.advance(0.2)
    assert g.output(m, 0.2) != bh.output(m, "green", 0.2)         # 0.5 s: still blending


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


def test_the_fade_passes_has_map_through():
    f = bh.StateFade("green")
    assert f.output({}, 0.0, has_map=True) == ((1.0, 1.0, 1.0), 1.0)
