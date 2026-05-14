"""apply_hit routes damage: shields-face → subsystem → hull bleed.
Broadcasts WeaponHitEvent at the end.
"""
import sys
import types

from engine.appc.math import TGPoint3
from engine.appc.combat import apply_hit
from engine.appc.events import ET_WEAPON_HIT


class _FakeShields:
    def __init__(self, current=1000.0):
        self._cur = [current] * 6

    def ApplyDamage(self, face, amount):
        amt = float(amount)
        cur = self._cur[int(face)]
        if amt <= cur:
            self._cur[int(face)] = cur - amt
            return 0.0
        self._cur[int(face)] = 0.0
        return amt - cur


class _FakeSubsystem:
    def __init__(self, name, max_cond=1000.0, position=None, radius=1.0):
        self._name = name
        self._condition = max_cond
        self._max_condition = max_cond
        self._position = position or TGPoint3(0, 0, 0)
        self._radius = radius

    def GetName(self): return self._name
    def GetCondition(self): return self._condition
    def SetCondition(self, v): self._condition = max(0.0, float(v))
    def GetMaxCondition(self): return self._max_condition
    def GetPosition(self): return self._position
    def GetRadius(self): return self._radius


class _FakeShip:
    def __init__(self, shields=None, hull=None, children=()):
        self._shields = shields
        self._hull = hull
        self._children = list(children)
        self._dying = False
        self._loc = TGPoint3(0, 0, 0)

    def GetShields(self): return self._shields
    def GetHull(self): return self._hull
    def GetNumChildSubsystems(self): return len(self._children)
    def GetChildSubsystem(self, i): return self._children[i]
    def GetWorldLocation(self): return self._loc
    def IsDying(self): return 1 if self._dying else 0
    def SetDying(self, v): self._dying = bool(v)

    def DamageSystem(self, subsystem, amount):
        if subsystem is None: return
        new = max(0.0, subsystem.GetCondition() - float(amount))
        subsystem.SetCondition(new)
        if subsystem is self._hull and new <= 0.0:
            self.SetDying(True)


def test_full_damage_absorbed_by_shields():
    shields = _FakeShields(current=1000.0)
    hull = _FakeSubsystem("Hull", max_cond=2000.0)
    ship = _FakeShip(shields=shields, hull=hull)
    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
    assert hull.GetCondition() == 2000.0


def test_excess_bleeds_to_hull_when_no_subsystem_match():
    shields = _FakeShields(current=100.0)
    hull = _FakeSubsystem("Hull", max_cond=1000.0)
    ship = _FakeShip(shields=shields, hull=hull)
    apply_hit(ship, 500.0, TGPoint3(0, 100, 0), source=None)
    # Shields absorbed 100, hull took remaining 400.
    assert hull.GetCondition() == 600.0


def test_excess_routes_to_picked_subsystem_first():
    shields = _FakeShields(current=100.0)
    hull = _FakeSubsystem("Hull", max_cond=1000.0)
    bridge = _FakeSubsystem("Bridge", max_cond=300.0, position=TGPoint3(0, 5, 0), radius=2.0)
    ship = _FakeShip(shields=shields, hull=hull, children=[bridge])
    apply_hit(ship, 500.0, TGPoint3(0, 5, 0), source=None)
    # Shields absorbed 100, bridge took 300 (capped), remaining 100 bled to hull.
    assert bridge.GetCondition() == 0.0
    assert hull.GetCondition() == 900.0


def test_hull_zero_marks_ship_dying():
    shields = _FakeShields(current=0.0)
    hull = _FakeSubsystem("Hull", max_cond=100.0)
    ship = _FakeShip(shields=shields, hull=hull)
    assert ship.IsDying() == 0
    apply_hit(ship, 100.0, TGPoint3(0, 0, 0), source=None)
    assert hull.GetCondition() == 0.0
    assert ship.IsDying() == 1


def test_apply_hit_broadcasts_weapon_hit_event():
    received = []

    def handler(_obj, evt):
        received.append(evt.GetDamage())

    mod = types.ModuleType("_test_apply_hit_broadcast")
    mod.handler = handler
    sys.modules["_test_apply_hit_broadcast"] = mod
    try:
        import App
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            ET_WEAPON_HIT, None, "_test_apply_hit_broadcast.handler")

        shields = _FakeShields(current=10000.0)
        hull = _FakeSubsystem("Hull")
        ship = _FakeShip(shields=shields, hull=hull)
        apply_hit(ship, 42.0, TGPoint3(0, 0, 0), source=None)
        assert received == [42.0]
    finally:
        # Remove the test handler from g_kEventManager so it doesn't leak.
        import App
        App.g_kEventManager.RemoveBroadcastHandler(
            ET_WEAPON_HIT, None, "_test_apply_hit_broadcast.handler")
        del sys.modules["_test_apply_hit_broadcast"]
