"""_build_dynamic_light_render_data() marshals projectiles._active into the
dict shape host_io.set_dynamic_lights expects. Task 11 of the
authentic-projectile-visuals plan: BC's torpedoes carry a glow-colored
dynamic light that attaches to ships within radius (weapon-firing-mechanics
audit §5.5); disruptor bolts carry no light at all ("the bolt illuminates
nothing"). One point light per in-flight torpedo-style projectile; disruptor
bolts are skipped entirely."""
import App
import pytest

from engine.appc.projectiles import Torpedo, register
from engine.appc import projectiles
from engine.host_loop import (
    _build_dynamic_light_render_data, _color_tuple,
    _TORPEDO_LIGHT_RADIUS_SCALE, _TORPEDO_LIGHT_INTENSITY,
)


def _color(r, g, b, a=1.0):
    c = App.TGColorA()
    c.SetRGBA(r, g, b, a)
    return c


@pytest.fixture(autouse=True)
def clear_torpedo_registry():
    projectiles._active.clear()
    yield
    projectiles._active.clear()


def _make_photon():
    t = Torpedo()
    core_color = _color(1.0, 0.99, 0.39)
    glow_color = _color(1.0, 0.25, 0.0)
    t.CreateTorpedoModel(
        "data/Textures/Tactical/TorpedoCore.tga",   core_color, 0.2, 1.2,
        "data/Textures/Tactical/TorpedoGlow.tga",   glow_color, 3.0, 0.3, 0.6,
        "data/Textures/Tactical/TorpedoFlares.tga", glow_color, 8, 0.7, 0.4,
    )
    t._position = App.TGPoint3(5.0, 6.0, 7.0)
    t._velocity = App.TGPoint3(3.0, 4.0, 0.0)
    register(t)
    return t, core_color, glow_color


def _make_disruptor():
    t = Torpedo()
    shell = _color(0.172549, 1.0, 0.172549)
    core = _color(0.639216, 1.0, 0.639216)
    t.CreateDisruptorModel(shell, core, 2.0, 0.2)
    register(t)
    return t, shell, core


def test_photon_torpedo_emits_exactly_one_light():
    t, core_color, glow_color = _make_photon()
    out = _build_dynamic_light_render_data()
    assert len(out) == 1

    entry = out[0]
    assert entry["position"] == pytest.approx((5.0, 6.0, 7.0))
    assert entry["color"] == pytest.approx(_color_tuple(glow_color)[:3])
    # photon: glow_size_a=3.0, glow_size_b=0.3 -> max=3.0
    assert entry["radius"] == pytest.approx(
        _TORPEDO_LIGHT_RADIUS_SCALE * 3.0)
    assert entry["radius"] == pytest.approx(100.0 * 3.0)
    # Intensity is a tuning knob (VFX calibrate-up-then-down convention), not
    # audit-pinned evidence, so pin it against the named constant rather than
    # a bare literal — plus a sanity floor so a future accidental 0.0 fails.
    assert entry["intensity"] == _TORPEDO_LIGHT_INTENSITY
    assert entry["intensity"] > 0
    assert "position_b" not in entry


def test_disruptor_emits_no_light():
    _make_disruptor()
    out = _build_dynamic_light_render_data()
    assert out == []


def test_mixed_registry_emits_one_light_for_the_photon_only():
    _make_photon()
    _make_disruptor()
    out = _build_dynamic_light_render_data()
    assert len(out) == 1


def test_torpedo_with_no_create_call_is_skipped():
    t = Torpedo()
    t._position = App.TGPoint3(1.0, 1.0, 1.0)
    register(t)
    out = _build_dynamic_light_render_data()
    assert out == []


def test_empty_registry_emits_no_lights():
    out = _build_dynamic_light_render_data()
    assert out == []
