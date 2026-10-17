"""engine.appc.running_lights (running-lights spec §4.2)."""
import pytest

import App
from engine.appc import running_lights, running_light_dials
from engine.appc.light_emitters import emitter_flicker
from engine.appc.math import TGPoint3
from engine.appc.properties import TGModelPropertySet


def _light(name, pos, rgba, radius=1.5, period=3.0, duration=1.0):
    p = App.BlinkingLightProperty_Create(name)
    pt = TGPoint3(); pt.SetXYZ(*pos)
    p.SetPosition(pt)
    c = App.TGColorA(); c.SetRGBA(*rgba)
    p.SetColor(c)
    p.SetRadius(radius); p.SetPeriod(period); p.SetDuration(duration)
    return p


class _Sub:
    def __init__(self, disabled=False, destroyed=False):
        self._dis, self._des = disabled, destroyed
    def IsDisabled(self): return 1 if self._dis else 0
    def IsDestroyed(self): return 1 if self._des else 0


class _Ship:
    def __init__(self, props=(), name="USS Voyager", power=None,
                 dying=False, dead=False):
        self._pset = TGModelPropertySet()
        for p in props:
            self._pset.AddToSet("Scene Root", p)
        self._name, self._power = name, power
        self._dying, self._dead = dying, dead
    def GetPropertySet(self): return self._pset
    def GetName(self): return self._name
    def GetPowerSubsystem(self): return self._power
    def IsDying(self): return 1 if self._dying else 0
    def IsDead(self): return 1 if self._dead else 0


def test_lights_for_reads_static_and_blinker_in_property_order():
    red = _light("Port Static", (-0.5, 0.1, 0.0), (1, 0, 0, 1), radius=1.0, duration=0.0)
    white = _light("Bridge Blinker", (0.0, 0.58, 0.28), (1, 1, 0.5, 0.25))
    ship = _Ship([red, App.SmokeEmitterProperty_Create("not a light"), white])
    specs = running_lights.lights_for(ship)
    assert [s.duration for s in specs] == [0.0, 1.0]
    assert specs[0].pos == pytest.approx((-0.5, 0.1, 0.0))
    assert specs[0].rgb == (1.0, 0.0, 0.0)
    assert specs[1].rgb == pytest.approx((1.0, 1.0, 0.5))   # alpha dropped
    assert specs[1].size == 1.5 and specs[1].period == 3.0
    assert specs[1].as_tuple() == pytest.approx(
        (0.0, 0.58, 0.28, 1.0, 1.0, 0.5, 1.5, 3.0, 1.0))


def test_lights_for_unlit_ship_is_empty():
    assert running_lights.lights_for(_Ship()) == []


def test_lights_for_skips_a_light_with_no_position():
    p = App.BlinkingLightProperty_Create("unplaced")   # SetPosition never called
    assert running_lights.lights_for(_Ship([p])) == []


def test_lights_for_ship_without_property_set_is_empty():
    class _Bare:
        def GetPropertySet(self): return None
    assert running_lights.lights_for(_Bare()) == []


def test_phase_is_stable_per_name_and_differs_across_names():
    a1 = running_lights.phase_for(_Ship(name="USS Voyager"))
    a2 = running_lights.phase_for(_Ship(name="USS Voyager"))
    b = running_lights.phase_for(_Ship(name="USS Defiant"))
    assert a1 == a2
    assert a1 != b
    assert 0.0 <= a1 < 1000.0 and 0.0 <= b < 1000.0


def test_level_healthy_uncloaked_is_one():
    ship = _Ship(power=_Sub())
    assert running_lights.level_for(ship, 0.0, 10.0, 3.0) == 1.0


def test_level_with_no_power_subsystem_is_one():
    assert running_lights.level_for(_Ship(power=None), 0.0, 10.0, 3.0) == 1.0


def test_level_disabled_power_flickers_like_the_emitters():
    ship = _Ship(power=_Sub(disabled=True))
    got = running_lights.level_for(ship, 0.0, 12.5, 7.0)
    assert got == pytest.approx(emitter_flicker(12.5, 7.0))


def test_level_destroyed_power_is_zero():
    assert running_lights.level_for(_Ship(power=_Sub(destroyed=True)), 0.0, 1.0, 0.0) == 0.0


@pytest.mark.parametrize("frac,expected", [(0.0, 1.0), (0.5, 0.5), (1.0, 0.0),
                                           (-0.2, 1.0), (1.7, 0.0)])
def test_level_fades_with_cloak(frac, expected):
    assert running_lights.level_for(_Ship(power=_Sub()), frac, 1.0, 0.0) == pytest.approx(expected)


@pytest.mark.parametrize("dying,dead", [(True, False), (False, True)])
def test_level_is_zero_once_the_ship_dies(dying, dead):
    ship = _Ship(power=_Sub(), dying=dying, dead=dead)
    assert running_lights.level_for(ship, 0.0, 1.0, 0.0) == 0.0


def test_forced_dev_glow_preview_drives_the_lights(monkeypatch):
    from engine import dev_light_preview
    from engine.appc import subsystem_glow
    monkeypatch.setattr(dev_light_preview, "forced_glow_state",
                        lambda: subsystem_glow.DESTROYED)
    assert running_lights.level_for(_Ship(power=_Sub()), 0.0, 1.0, 0.0) == 0.0


def test_dials_defaults_and_reset():
    running_light_dials.reset()
    assert running_light_dials.current() == {
        "size_gu_per_radius": 0.02, "min_px": 2.5, "intensity": 4.0}


def test_dials_step_clamps_at_minimum():
    running_light_dials.reset()
    for _ in range(200):
        running_light_dials._step("min_px", -1)
    assert running_light_dials.current()["min_px"] == pytest.approx(0.5)
    running_light_dials.reset()
