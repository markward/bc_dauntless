import sys
import types

import pytest

import App
from engine.appc.events import TGEventHandlerObject
from engine.appc.radiation import RadiationDriver
from engine.core import game
from engine.systems.profile import Sample


class _Faces:
    NUM_SHIELDS = 6

    def __init__(self, v, on=True):
        self._v = [v] * 6
        self._on = on

    def IsOn(self):
        return 1 if self._on else 0

    def GetCurrentShields(self, f):
        return self._v[f]

    def SetCurrentShields(self, f, v):
        self._v[f] = v


class _Hull:
    def __init__(self, c):
        self._c = c

    def GetCondition(self):
        return self._c

    def SetCondition(self, v):
        self._c = v


class _Ship(TGEventHandlerObject):
    def __init__(self, hull=1000.0, shield=500.0, shields_on=True):
        super().__init__()
        self._hull = _Hull(hull)
        self._shield = _Faces(shield, shields_on)

    def GetHull(self):
        return self._hull

    def GetShieldSubsystem(self):
        return self._shield

    def GetSubsystems(self):
        return []

    def GetSensorSubsystem(self):
        return None


@pytest.fixture(autouse=True)
def _hard():
    before = game.Game_GetDifficulty()
    game.Game_SetDifficulty(2)
    yield
    game.Game_SetDifficulty(before)


def _run(driver, ships, seconds):
    # 61 ticks for "1 s": the 16th event falls exactly on t = 1.0, where
    # summed 1/60 steps can land a hair short.
    for _ in range(int(round(seconds * 60)) + 1):
        driver.update(ships, 1.0 / 60.0)


def test_shields_up_drain_twenty_per_face_per_second_at_full_hard():
    ship = _Ship()
    _run(RadiationDriver(lambda s: Sample(radiation=1.0)), [ship], 1.0)
    assert ship.GetShieldSubsystem().GetCurrentShields(0) == pytest.approx(480.0, abs=1.5)
    assert ship.GetHull().GetCondition() == 1000.0


def test_shields_down_drain_the_hull():
    ship = _Ship(shields_on=False)
    _run(RadiationDriver(lambda s: Sample(radiation=0.5)), [ship], 1.0)
    assert ship.GetHull().GetCondition() == pytest.approx(1000.0 - 75.0, abs=5.0)


@pytest.mark.parametrize("level,expected", [(0, 1000.0), (1, 925.0), (2, 850.0)])
def test_difficulty_scales_the_drain(level, expected):
    game.Game_SetDifficulty(level)
    ship = _Ship(shields_on=False)
    _run(RadiationDriver(lambda s: Sample(radiation=1.0)), [ship], 1.0)
    assert ship.GetHull().GetCondition() == pytest.approx(expected, abs=10.0)


def test_events_fire_at_sixteen_hz_while_irradiated():
    ship = _Ship()
    seen = []
    mod = types.ModuleType("_rad_count")
    mod.h = lambda o, e: (seen.append(e), o.CallNextHandler(e))
    sys.modules["_rad_count"] = mod
    ship.AddPythonFuncHandlerForInstance(App.ET_ENVIRONMENT_DAMAGE, "_rad_count.h")
    _run(RadiationDriver(lambda s: Sample(radiation=0.1)), [ship], 1.0)
    assert len(seen) == 16


def test_no_events_or_damage_in_clear_space():
    ship = _Ship(shields_on=False)
    _run(RadiationDriver(lambda s: Sample()), [ship], 1.0)
    assert ship.GetHull().GetCondition() == 1000.0


def test_swallowed_event_applies_no_damage():
    ship = _Ship(shields_on=False)
    ship.AddPythonFuncHandlerForInstance(App.ET_ENVIRONMENT_DAMAGE, "MissionLib.IgnoreEvent")
    _run(RadiationDriver(lambda s: Sample(radiation=1.0)), [ship], 1.0)
    assert ship.GetHull().GetCondition() == 1000.0


def test_no_drain_while_dashing(monkeypatch):
    from engine.appc import warp_state
    monkeypatch.setattr(warp_state, "is_ship_warping", lambda obj: True)
    ship = _Ship(shields_on=False)
    _run(RadiationDriver(lambda s: Sample(radiation=1.0)), [ship], 1.0)
    assert ship.GetHull().GetCondition() == 1000.0


def test_hull_drain_goes_through_damage_system_when_the_ship_has_one():
    calls = []

    class _Real(_Ship):
        def DamageSystem(self, sub, amount, source=None):
            calls.append(amount)
            sub.SetCondition(sub.GetCondition() - amount)

    ship = _Real(shields_on=False)
    _run(RadiationDriver(lambda s: Sample(radiation=1.0)), [ship], 1.0)
    assert len(calls) == 16 and calls[0] == pytest.approx(150.0 / 16.0)
