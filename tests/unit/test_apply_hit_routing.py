"""apply_hit routes damage via spherical-splash attribution:
shields absorb first, then hull takes full post-shield damage unconditionally,
and each non-hull subsystem within the splash sphere takes weighted damage.
Broadcasts WeaponHitEvent at the end.
"""
import sys
import types
import pytest

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

    def DamageSystem(self, subsystem, amount, source=None):
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


def test_splash_hit_at_subsystem_centre_damages_it():
    """Splash model: impact directly on the bridge (d=0 → w=1.0).
    Shields absorb 100; post-shield=400. Hull takes 400 unconditionally.
    Bridge (r_sub=2, r_hit=0.15) is within range so it takes 400, capped at 300.
    """
    shields = _FakeShields(current=100.0)
    hull = _FakeSubsystem("Hull", max_cond=1000.0)
    bridge = _FakeSubsystem("Bridge", max_cond=300.0, position=TGPoint3(0, 5, 0), radius=2.0)
    ship = _FakeShip(shields=shields, hull=hull, children=[bridge])
    apply_hit(ship, 500.0, TGPoint3(0, 5, 0), source=None)
    # Bridge should be destroyed (took full 400, capped at max 300).
    assert bridge.GetCondition() == 0.0
    # Hull takes full post-shield damage: 1000 - 400 = 600.
    assert hull.GetCondition() == 600.0


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


# ── apply_hit calls hit_feedback.dispatch with per-stage breakdown ─────────

class _SpyDispatch:
    """Capture dispatch calls for assertion."""
    def __init__(self):
        self.calls = []
    def __call__(self, *args, **kwargs):
        self.calls.append(kwargs)


def test_apply_hit_calls_dispatch_with_absorbed_shields(monkeypatch):
    """Shield absorbs the entire hit; absorbed_shields=damage, others=0."""
    from engine.appc import combat, hit_feedback
    from engine.appc.math import TGPoint3

    spy = _SpyDispatch()
    monkeypatch.setattr(hit_feedback, "dispatch", spy)

    ship = _make_ship_with_full_shield(face_charge=100.0)
    combat.apply_hit(ship, damage=30.0, hit_point=TGPoint3(0, 1, 0),
                     source=None,
                     normal=TGPoint3(0, -1, 0))

    assert len(spy.calls) == 1
    kw = spy.calls[0]
    assert kw["absorbed_shields"] == pytest.approx(30.0)
    assert kw["absorbed_subsystem"] == pytest.approx(0.0)
    assert kw["absorbed_hull"] == pytest.approx(0.0)
    assert kw["sub_transition"] is None
    assert kw["normal"].y == pytest.approx(-1.0)


def test_apply_hit_calls_dispatch_with_hull_bleed(monkeypatch):
    """Shields drained; hull takes the full post-shield overflow."""
    from engine.appc import combat, hit_feedback
    from engine.appc.math import TGPoint3

    spy = _SpyDispatch()
    monkeypatch.setattr(hit_feedback, "dispatch", spy)

    ship = _make_ship_with_full_shield(face_charge=10.0)
    combat.apply_hit(ship, damage=30.0, hit_point=TGPoint3(0, 1, 0),
                     source=None,
                     normal=None)

    kw = spy.calls[0]
    assert kw["absorbed_shields"] == pytest.approx(10.0)
    # No subsystems in splash range → absorbed_subsystem stays 0;
    # hull takes the full post-shield 20.
    assert kw["absorbed_subsystem"] == pytest.approx(0.0)
    assert kw["absorbed_hull"] == pytest.approx(20.0)


def test_apply_hit_dispatch_captures_subsystem_transition(monkeypatch):
    """A subsystem in splash range that flips disabled this tick produces sub_transition='disabled'.

    The flipping sub is at body (0, 1, 0) with radius=10; hit_point is
    (0, 1, 0) so d=0 < r_sub+r_hit — it is within the splash sphere and
    will be damaged, triggering the transition detection.
    """
    from engine.appc import combat, hit_feedback
    from engine.appc.math import TGPoint3

    spy = _SpyDispatch()
    monkeypatch.setattr(hit_feedback, "dispatch", spy)

    ship = _make_ship_with_flipping_sub(initial_dmg=False,
                                          initial_dis=False,
                                          final_dmg=True,
                                          final_dis=True)
    combat.apply_hit(ship, damage=50.0, hit_point=TGPoint3(0, 1, 0),
                     source=None,
                     normal=None)

    kw = spy.calls[0]
    assert kw["sub_transition"] == "disabled"


def _make_ship_with_full_shield(*, face_charge):
    """Ship with FRONT shield charged to `face_charge`, no children.
    No subsystems in splash range so absorbed_subsystem stays 0."""
    shields = _FakeShields(current=face_charge)
    hull = _FakeSubsystem("Hull", max_cond=1000.0)
    return _FakeShip(shields=shields, hull=hull, children=[])


class _FlippingSub(_FakeSubsystem):
    """Subsystem whose IsDamaged/IsDisabled return initial_* until
    DamageSystem is called once, then final_*."""
    def __init__(self, *, initial_dmg, initial_dis,
                 final_dmg, final_dis,
                 position=None, radius=2.0):
        super().__init__("Flipping", max_cond=100.0,
                         position=position or TGPoint3(0, 5, 0),
                         radius=radius)
        self._initial = (initial_dmg, initial_dis, False)
        self._final = (final_dmg, final_dis, False)
        self._damaged_called = False
    def IsDamaged(self):
        return (self._final if self._damaged_called else self._initial)[0]
    def IsDisabled(self):
        return (self._final if self._damaged_called else self._initial)[1]
    def IsDestroyed(self):
        return False
    def SetCondition(self, v):
        super().SetCondition(v)
        self._damaged_called = True


def _make_ship_with_flipping_sub(*, initial_dmg, initial_dis,
                                   final_dmg, final_dis):
    """Ship with one _FlippingSub as a child, no shields. The sub is at
    body (0, 1, 0) with radius=10 so a hit at (0, 1, 0) puts it within
    the splash sphere (d=0 < r_sub+r_hit)."""
    shields = _FakeShields(current=0.0)
    hull = _FakeSubsystem("Hull", max_cond=1000.0)
    flipping = _FlippingSub(
        initial_dmg=initial_dmg, initial_dis=initial_dis,
        final_dmg=final_dmg, final_dis=final_dis,
        position=TGPoint3(0, 1, 0), radius=10.0,
    )
    ship = _FakeShip(shields=shields, hull=hull, children=[flipping])
    ship._flipping_sub = flipping
    return ship
