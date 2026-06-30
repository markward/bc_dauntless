"""LIGHT (PP_LOW) phaser intensity: "disable, don't destroy".

Verified against the real BC engine via dev-console probe q05/q07: a LIGHT
phaser hit on an unshielded target deals 0% hull / 100% subsystem damage.
We model that with apply_hit(damage_hull=False):

- the hull takes NO condition damage (can never destroy via hull),
- subsystems still take their weighted splash share,
- the hull still reads as struck cosmetically — a scorch decal still fires —
  but the structural hull carve is suppressed (per user: scorching is fine,
  a breach hole is not).
"""
import pytest

from engine.appc.combat import apply_hit
from engine.appc import hit_feedback
from engine.appc import damage_decals as dd
from engine.appc import damage_eligibility as de
from engine.appc.math import TGMatrix3, TGPoint3
import App


# --- apply_hit-level: hull condition suppression -------------------------

class _FakeSub:
    def __init__(self, name, pos, radius, max_condition=1000.0):
        self.name = name
        self._pos = pos
        self._radius = radius
        self._max = max_condition
        self._condition = max_condition

    def GetPosition(self):     return self._pos
    def GetRadius(self):       return self._radius
    def GetCondition(self):    return self._condition
    def GetMaxCondition(self): return self._max
    def IsDamaged(self):       return self._condition < self._max
    def IsDisabled(self):      return False
    def IsDestroyed(self):     return False


class _FakeShip(App.TGEventHandlerObject):
    def __init__(self, hull, subsystems):
        super().__init__()
        self._hull = hull
        self._subs = list(subsystems)
        self._loc = TGPoint3(0.0, 0.0, 0.0)
        self._rot = TGMatrix3()
        self.damage_log = []

    def GetHull(self):          return self._hull
    def GetSubsystems(self):    return list(self._subs)
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetShields(self):       return None  # unshielded for these tests

    def DamageSystem(self, sub, amount):
        self.damage_log.append((sub.name, amount))
        sub._condition = max(0.0, sub._condition - amount)


@pytest.fixture
def restore_event_manager():
    orig = App.g_kEventManager.AddEvent
    yield
    App.g_kEventManager.AddEvent = orig


def _ship_with_sensor():
    hull = _FakeSub("Hull", TGPoint3(0, 0, 0), radius=1.0)
    sensor = _FakeSub("Sensors", TGPoint3(0.3, 0, 0), radius=0.28)
    return _FakeShip(hull=hull, subsystems=[hull, sensor]), hull, sensor


def test_light_intensity_spares_hull_but_damages_subsystem(restore_event_manager):
    ship, hull, sensor = _ship_with_sensor()
    apply_hit(ship, damage=100.0, hit_point=TGPoint3(0.3, 0.0, 0.0),
              source=None, normal=None, damage_hull=False)
    names = [n for n, _ in ship.damage_log]
    assert "Hull" not in names          # hull HP untouched on LIGHT
    assert hull.GetCondition() == 1000.0
    assert "Sensors" in names           # subsystem still disabled-damaged
    assert sensor.GetCondition() < 1000.0


def test_full_intensity_damages_hull_and_subsystem(restore_event_manager):
    ship, hull, sensor = _ship_with_sensor()
    apply_hit(ship, damage=100.0, hit_point=TGPoint3(0.3, 0.0, 0.0),
              source=None, normal=None, damage_hull=True)
    names = [n for n, _ in ship.damage_log]
    assert "Hull" in names
    assert hull.GetCondition() == 900.0
    assert "Sensors" in names


# --- dispatch-level: scorch decal fires, hull carve suppressed -----------

class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _CarveDecalHost:
    """Captures both the scorch decal and the structural carve calls.
    hull_carve_add mirrors the live host_bindings arity (point, normal,
    influ, strength, time, floor, rad_mod)."""
    def __init__(self):
        self.decal_calls = []
        self.carve_calls = []

    def damage_decal_add(self, *, instance_id, world_point, world_normal,
                         radius, intensity, weapon_class, time):
        self.decal_calls.append(instance_id)

    def hull_carve_add(self, iid, point, normal, influ, strength, time,
                       floor, rad_mod):
        self.carve_calls.append(iid)


class _Hull:
    def IsDestroyed(self):
        return 0


class _Ship:
    def GetHull(self):
        return _Hull()


@pytest.fixture
def carve_env(monkeypatch):
    monkeypatch.setattr(dd, "current_game_time", lambda: 100.0)
    hit_feedback._last_carve_time.clear()
    hit_feedback._pending_carve_strength.clear()
    hit_feedback._last_decal_emit.clear()
    de.reset()
    yield
    hit_feedback._last_carve_time.clear()
    hit_feedback._pending_carve_strength.clear()
    hit_feedback._last_decal_emit.clear()
    de.reset()


def _dispatch(host, ship, *, allow_hull_carve):
    hit_feedback.dispatch(
        ship=ship, source=None, point=_Pt(1, 2, 3), normal=_Pt(0, 0, 1),
        damage=10.0, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=60.0, sub_transition=None,
        host=host, ship_instances={ship: "IID"},
        weapon_type="phaser", radius=0.2, persist_decal=True,
        allow_hull_carve=allow_hull_carve,
    )


def test_light_hit_scorches_but_does_not_carve(carve_env):
    host = _CarveDecalHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, allow_hull_carve=False)
    assert host.decal_calls == ["IID"]   # scorch decal still fires
    assert host.carve_calls == []        # but no structural breach


def test_full_hit_scorches_and_carves(carve_env):
    host = _CarveDecalHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, allow_hull_carve=True)
    assert host.decal_calls == ["IID"]
    assert host.carve_calls == ["IID"]
