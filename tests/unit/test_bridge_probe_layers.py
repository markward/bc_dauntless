"""Probe-layer planner (spec 2026-10-17-bridge-reflection-layers §2, §4.4):
which animated materials share one reflection layer per state."""
import pytest

from engine.bridge_editor import probe_layers as pl


def _anim(scope=("red",), **kw):
    a = {"type": "animation", "scope": list(scope), "shape": "sine", "period_s": 3,
         "phase": 0, "min": 0.2}
    a.update(kw)
    return a


def _doc(**mats):
    return {"materials": mats}


def _glow(*anims, emission=1):
    return {"emission": emission, "modifiers": list(anims)}


def _plan(doc, cap=8, lights=frozenset()):
    resolved = {i: n for i, n in enumerate(doc["materials"])}
    return pl.plan(doc, resolved, lights, frozenset(), cap)


def test_wave_key_none_without_animation_in_state():
    assert pl.wave_key(_glow(_anim()), "green") is None


def test_min_is_part_of_the_key():
    d = _doc(a=_glow(_anim(min=0)), b=_glow(_anim(min=0.2)))
    assert len(_plan(d).layers) == 2


def test_equal_waves_share_one_layer():
    d = _doc(**{n: _glow(_anim()) for n in ("m1", "m2", "m3", "m4")})
    p = _plan(d)
    assert len(p.layers) == 1
    assert p.layers[0].state == "red"
    assert p.layers[0].materials == ("m1", "m2", "m3", "m4")


def test_sine_ignores_duty_and_soft():
    d = _doc(a=_glow(_anim()), b=_glow(_anim(duty=0.3, soft=0.1)))
    assert len(_plan(d).layers) == 1


def test_multiplied_animations_form_one_key():
    two = _glow(_anim(), _anim(period_s=5))
    assert len(pl.wave_key(two, "red")) == 2
    d = _doc(a=two, b=_glow(_anim()))
    assert len(_plan(d).layers) == 2


def test_layer_per_state():
    d = _doc(a=_glow(_anim(scope=("red", "yellow"))))
    p = _plan(d)
    assert [l.state for l in p.layers] == ["yellow", "red"]
    assert p.layers[0].key == p.layers[1].key


def test_cap_keeps_authored_order_and_warns():
    d = _doc(mat_kept1=_glow(_anim(period_s=1)), mat_kept2=_glow(_anim(period_s=2)),
             mat_dropped=_glow(_anim(period_s=4)))
    p = _plan(d, cap=2)
    assert [l.materials for l in p.layers] == [("mat_kept1",), ("mat_kept2",)]
    assert len(p.warnings) == 1
    assert "mat_dropped" in p.warnings[0]
    assert "mat_kept1" not in p.warnings[0] and "mat_kept2" not in p.warnings[0]
    assert p.animated("mat_dropped", "red") is True
    assert p.layer_of("mat_dropped", "red") == -1
    assert p.layer_of("mat_kept1", "red") == 0


def test_non_red_tint_still_contributes():
    st = {"type": "state", "scope": ["red"], "tint": [0, 1, 0], "level": 1}
    assert len(_plan(_doc(a=_glow(st, _anim(), emission=0))).layers) == 1


def test_non_red_tint_lights_only_contributes():
    st = {"type": "state", "scope": ["red"], "tint": [0, 0, 1], "level": 1,
          "glows": False}
    d = _doc(a=_glow(st, _anim(), emission=0))
    assert _plan(d).layers == []
    assert len(_plan(d, lights=frozenset({"a"})).layers) == 1


def test_material_contributing_nothing_makes_no_layer():
    d = _doc(a=_glow(_anim(), emission=0))
    p = _plan(d, cap=1)
    assert p.layers == [] and p.warnings == []
    d2 = _doc(a=_glow(_anim(), emission=0), b=_glow(_anim(period_s=9)))
    assert [l.materials for l in _plan(d2, cap=1).layers] == [("b",)]


def test_light_carrying_material_contributes_through_its_lights():
    state = {"type": "state", "scope": ["red"], "tint": [1, 0, 0], "level": 1,
             "glows": False}
    d = _doc(a=_glow(state, _anim(), emission=0))
    assert _plan(d).layers == []
    assert len(_plan(d, lights=frozenset({"a"})).layers) == 1


def test_unused_material_makes_no_layer():
    d = _doc(a=_glow(_anim()))
    p = pl.plan(d, {}, frozenset(), frozenset(), 8)
    assert p.layers == []


def test_mapped_mesh_defaults_emission_to_one():
    m = {"modifiers": [_anim()]}
    d = _doc(a=m)
    assert pl.plan(d, {0: "a"}, frozenset(), frozenset(), 8).layers == []
    assert len(pl.plan(d, {0: "a"}, frozenset(), frozenset({0}), 8).layers) == 1


def test_layer_cap_by_quality():
    assert [pl.layer_cap(q) for q in (0, 1, 2, -3, 9)] == [2, 4, 8, 2, 8]


def test_layer_values_are_wave_to_the_2_2():
    p = _plan(_doc(a=_glow(_anim())))
    assert pl.layer_values(p, 0.75) == [pytest.approx(0.6 ** 2.2)]
    assert pl.layer_values(p, 0.0) == [pytest.approx(1.0)]
