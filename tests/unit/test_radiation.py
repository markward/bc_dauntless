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


import random as _random

from engine.appc.subsystems import (
    HullSubsystem, PowerSubsystem, SensorSubsystem, ShieldSubsystem, _is_offline)


class _SubShip(_Ship):
    def __init__(self):
        super().__init__(shields_on=True)
        self.subs = [HullSubsystem("Hull"), PowerSubsystem("Power"),
                     SensorSubsystem("Sensors"), ShieldSubsystem("Shields")]

    def GetSubsystems(self):
        return list(self.subs)


class _AlwaysRoll(_random.Random):
    def random(self):
        return 0.0


def test_outage_never_picks_hull_or_power():
    ship = _SubShip()
    d = RadiationDriver(lambda s: Sample(radiation=1.0), rng=_random.Random(7))
    for _ in range(400):
        d.apply_chunk(ship, 1.0, 1.0)
        d._tick_outages(1.0 / 16.0, {id(ship)})
    hull, power = ship.subs[0], ship.subs[1]
    assert hull._radiation_out is False and power._radiation_out is False


def test_outage_rate_is_about_one_per_thirty_seconds_at_full_hard():
    ship = _SubShip()
    d = RadiationDriver(lambda s: Sample(radiation=1.0), rng=_random.Random(1))
    starts = 0
    for _ in range(int(16 * 3000)):          # 3000 s of events
        before = set(d.active_outages())
        d.apply_chunk(ship, 1.0, 1.0)
        starts += len(set(d.active_outages()) - before)
        d._tick_outages(1.0 / 16.0, {id(ship)})
    assert 70 <= starts <= 130               # expectation 100


def test_outage_lasts_between_five_and_twenty_seconds():
    ship = _SubShip()
    d = RadiationDriver(lambda s: Sample(radiation=1.0), rng=_AlwaysRoll())
    d.apply_chunk(ship, 1.0, 1.0)
    (sid, left), = d.active_outages().items()
    assert 5.0 <= left <= 20.0


def test_out_subsystem_is_offline_until_expiry():
    ship = _SubShip()
    d = RadiationDriver(lambda s: Sample(radiation=0.0), rng=_AlwaysRoll())
    d.apply_chunk(ship, 1.0, 1.0)
    out = [s for s in ship.subs if s._radiation_out]
    assert len(out) == 1 and _is_offline(out[0])
    for _ in range(21 * 60):
        d.update([ship], 1.0 / 60.0)
    assert not out[0]._radiation_out and not _is_offline(out[0])


def test_outage_clears_when_ship_leaves_the_ship_list():
    ship = _SubShip()
    d = RadiationDriver(lambda s: Sample(radiation=0.0), rng=_AlwaysRoll())
    d.apply_chunk(ship, 1.0, 1.0)
    d.update([], 1.0 / 60.0)
    assert not any(s._radiation_out for s in ship.subs)
    assert d.active_outages() == {}


def test_reset_clears_all_outages():
    ship = _SubShip()
    d = RadiationDriver(lambda s: Sample(radiation=0.0), rng=_AlwaysRoll())
    d.apply_chunk(ship, 1.0, 1.0)
    d.reset()
    assert not any(s._radiation_out for s in ship.subs)


def test_child_of_an_out_subsystem_is_offline():
    parent = SensorSubsystem("Parent")
    child = SensorSubsystem("Child")
    child._parent_subsystem = parent
    parent._radiation_out = True
    assert _is_offline(child)


from engine.appc.nebula_runtime import NebulaTracker


def _armed_set_with(ship_pos):
    s = App.SetClass_Create()
    n = App.MetaNebula_Create(0.6, 0.35, 0.72, 145.0, 10.5, "i.tga", "e.tga")
    n.SetupDamage(150.0, 20.0)
    n.AddNebulaSphere(0.0, 0.0, 0.0, 1500.0)
    s.AddObjectToSet(n, "neb")
    return s


class _PosShip(_Ship):
    def GetWorldLocation(self):
        return App.TGPoint3(0.0, 0.0, 0.0)


def test_ship_inside_armed_local_nebula_gets_no_profile_events():
    ship = _PosShip()
    seen = []
    mod = types.ModuleType("_rad_count2")
    mod.h = lambda o, e: (seen.append(e), o.CallNextHandler(e))
    sys.modules["_rad_count2"] = mod
    ship.AddPythonFuncHandlerForInstance(App.ET_ENVIRONMENT_DAMAGE, "_rad_count2.h")
    s = _armed_set_with((0.0, 0.0, 0.0))
    tracker = NebulaTracker()
    d = RadiationDriver(lambda sh: Sample(radiation=1.0))
    tracker.env_listeners.append(d.on_local_event)
    for _ in range(61):
        tracker.update(s, [ship], 1.0 / 60.0)
        d.update([ship], 1.0 / 60.0, shared=tracker.ships_in_armed_nebula())
    assert len(seen) == 16                    # the tracker's stream only


def test_local_nebula_events_carry_the_profile_drain():
    ship = _PosShip(shields_on=False)
    s = _armed_set_with((0.0, 0.0, 0.0))
    tracker = NebulaTracker()
    d = RadiationDriver(lambda sh: Sample(radiation=1.0))
    tracker.env_listeners.append(d.on_local_event)
    tracker.update(s, [ship], 1.0 / 60.0)     # first sighting: BC's one-off hit
    after_creation = ship.GetHull().GetCondition()
    for _ in range(61):
        tracker.update(s, [ship], 1.0 / 60.0)
        d.update([ship], 1.0 / 60.0, shared=tracker.ships_in_armed_nebula())
    assert after_creation - ship.GetHull().GetCondition() == pytest.approx(150.0, abs=15.0)


# ── Final review #2: radiation respects invincibility ─────────────────────────
# E3M2's "Derelict Warbird" is SetInvincible(TRUE) at 1% hull; combat.apply_hit
# gates on IsImmuneToDamage, and radiation must too.

class _ImmuneSubShip(_SubShip):
    def IsImmuneToDamage(self):
        return True


def test_immune_ship_takes_no_shield_drain_and_no_outage():
    ship = _ImmuneSubShip()
    d = RadiationDriver(lambda s: Sample(radiation=1.0), rng=_AlwaysRoll())
    d.apply_chunk(ship, 1.0, 1.0)
    assert ship.GetShieldSubsystem().GetCurrentShields(0) == 500.0
    assert d.active_outages() == {}
    assert not any(s._radiation_out for s in ship.subs)


def test_immune_ship_with_shields_down_takes_no_hull_drain():
    ship = _ImmuneSubShip()
    ship._shield = _Faces(500.0, on=False)
    d = RadiationDriver(lambda s: Sample(radiation=1.0), rng=_AlwaysRoll())
    _run(d, [ship], 1.0)
    assert ship.GetHull().GetCondition() == 1000.0
    assert d.active_outages() == {}


def test_a_ship_reporting_not_immune_still_drains():
    class _Mortal(_SubShip):
        def IsImmuneToDamage(self):
            return False
    ship = _Mortal()
    d = RadiationDriver(lambda s: Sample(radiation=1.0), rng=_AlwaysRoll())
    d.apply_chunk(ship, 1.0, 1.0)
    assert ship.GetShieldSubsystem().GetCurrentShields(0) < 500.0


# ── Final review #3: the hull is exposed when the generator cannot shield ──────

def _real_shields(face_value):
    gen = ShieldSubsystem("Shields")
    for f in range(gen.NUM_SHIELDS):
        gen.SetMaxShields(f, 500.0)
        gen.SetCurrentShields(f, face_value)
    return gen


def test_hull_drains_while_the_shield_generator_is_in_radiation_outage():
    ship = _Ship()
    ship._shield = _real_shields(500.0)
    ship._shield._radiation_out = True
    assert ship._shield.IsOn()                       # on, but offline
    d = RadiationDriver(lambda s: Sample(radiation=1.0), rng=_random.Random(3))
    d.apply_chunk(ship, 1.0, 1.0)
    assert ship.GetHull().GetCondition() == pytest.approx(1000.0 - 150.0 / 16.0)
    assert ship._shield.GetCurrentShields(0) == 500.0


def test_hull_drains_when_every_face_is_depleted_though_shields_are_on():
    ship = _Ship(shield=0.0, shields_on=True)
    d = RadiationDriver(lambda s: Sample(radiation=1.0), rng=_random.Random(3))
    d.apply_chunk(ship, 1.0, 1.0)
    assert ship.GetHull().GetCondition() == pytest.approx(1000.0 - 150.0 / 16.0)


def test_shields_drain_when_on_online_and_charged():
    ship = _Ship()
    ship._shield = _real_shields(500.0)
    d = RadiationDriver(lambda s: Sample(radiation=1.0), rng=_random.Random(3))
    d.apply_chunk(ship, 1.0, 1.0)
    assert ship._shield.GetCurrentShields(0) == pytest.approx(500.0 - 20.0 / 16.0)
    assert ship.GetHull().GetCondition() == 1000.0
