"""End-to-end: hull death -> 1.5s cascade -> warp core crosses 0 -> breach
damages a neighbour. Exercises objects.py routing + subsystem_cascade +
warp_core_breach together (Case B), with combat.apply_hit captured."""
import pytest

from engine.appc.objects import DamageableObject
from engine.appc import warp_core_breach, subsystem_cascade, ship_death
from engine.appc.math import TGMatrix3, TGPoint3


class _Sub:
    def __init__(self, name, cond=100.0, critical=False, pos=None,
                 max_condition=None):
        self.name = name
        self._c = cond
        self._max = max_condition if max_condition is not None else cond
        self._crit = critical
        self._pos = pos or TGPoint3(0.0, 0.0, 0.0)
        self._destroyed = False

    def GetCondition(self):    return self._c
    def SetCondition(self, v): self._c = v
    def GetMaxCondition(self): return self._max
    def IsCritical(self):      return 1 if self._crit else 0
    def GetPosition(self):     return self._pos
    def SetDestroyed(self, v): self._destroyed = bool(v)
    def IsDestroyed(self):     return self._destroyed


class _Ship(DamageableObject):
    def __init__(self, name, loc, hull, power, others, radius=1.0):
        super().__init__()
        self._name = name
        self._loc = loc
        self._radius = radius
        self._hull = hull
        self._power = power
        self._others = list(others)

    def GetName(self):           return self._name
    def GetWorldLocation(self):  return self._loc
    def GetWorldRotation(self):  return TGMatrix3()
    def GetRadius(self):         return self._radius
    def GetHull(self):           return self._hull
    def GetPowerSubsystem(self): return self._power
    def GetSubsystems(self):     return [self._hull, self._power, *self._others]
    def IsDestroyBrokenSystems(self): return 1
    def IsDying(self):           return 0
    def IsDead(self):            return 0
    def SetDying(self, v):       pass


@pytest.fixture(autouse=True)
def _clean():
    warp_core_breach.reset()
    subsystem_cascade.reset()
    yield
    warp_core_breach.reset()
    subsystem_cascade.reset()


def test_hull_death_cascade_breach_damages_neighbour(monkeypatch):
    # Source ship at origin with a 5000-condition warp core; neighbour 0.5 away.
    src = _Ship("A", TGPoint3(0, 0, 0),
                hull=_Sub("Hull", cond=20.0, critical=True),
                power=_Sub("WarpCore", cond=100.0, critical=True,
                           max_condition=5000.0),
                others=[_Sub("Sensors", cond=100.0)])
    nbr = _Ship("B", TGPoint3(0.5, 0, 0),
                hull=_Sub("Hull", cond=9999.0, critical=True),
                power=_Sub("WarpCore", cond=9999.0, critical=True,
                           max_condition=5000.0),
                others=[], radius=0.5)

    import engine.appc.ship_iter as ship_iter
    monkeypatch.setattr(ship_iter, "iter_ships", lambda *a, **k: [src, nbr])

    import engine.appc.combat as combat
    hits = []
    monkeypatch.setattr(combat, "apply_hit",
                        lambda ship, damage, hp, source, **kw: hits.append((ship, damage)))

    # Hull dies -> schedules the cascade (no breach yet).
    src.DamageSystem(src.GetHull(), 20.0)
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY / 2.0)
    warp_core_breach.advance(0.0)
    assert hits == []   # cascade not yet fired

    # Past the 1.5s delay: cascade zeroes the warp core -> arms breach.
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY)
    warp_core_breach.advance(0.0)

    targets = [h[0] for h in hits]
    assert nbr in targets and src not in targets


def test_neighbour_breach_does_not_rearm_lingering_wreck(monkeypatch):
    """A dead wreck in the 10-s linger window must not be re-armed or
    re-detonated when a neighbouring ship's warp core breaches nearby.

    Safety invariants under test:
    - The wreck remains in _breached exactly once (single-fire guard).
    - arm(wreck) after detonation is a no-op (_breached guard).
    - ship_death.is_targetable_wreck(wreck) is True before AND after the
      neighbour breach (begin() is idempotent on dying/dead ships).
    - The neighbour detonation terminates (no infinite loop / hang).
    """

    # -- Subclass that tracks dying/dead state so ship_death.begin() honours
    # the idempotency guard (begin checks IsDying() / IsDead() via _out_of_action).
    class _StatefulShip(_Ship):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._dying = False
            self._dead = False

        def IsDying(self):        return 1 if self._dying else 0
        def IsDead(self):         return 1 if self._dead else 0
        def SetDying(self, v):    self._dying = bool(v)
        def SetDead(self):        self._dead = True

    # Wreck: already dead, warp core at 0, located near the neighbour.
    wreck = _StatefulShip(
        "Wreck",
        TGPoint3(0.0, 0.0, 0.0),
        hull=_Sub("Hull", cond=0.0, critical=True),
        power=_Sub("WarpCore", cond=0.0, critical=True, max_condition=5000.0),
        others=[],
        radius=0.5,
    )

    # Neighbour: healthy ship that will breach, placed within blast radius.
    nbr = _StatefulShip(
        "Neighbour",
        TGPoint3(0.8, 0.0, 0.0),
        hull=_Sub("Hull", cond=9999.0, critical=True),
        power=_Sub("WarpCore", cond=100.0, critical=True, max_condition=5000.0),
        others=[],
        radius=0.5,
    )

    import engine.appc.ship_iter as ship_iter
    monkeypatch.setattr(ship_iter, "iter_ships", lambda *a, **k: [nbr, wreck])

    import engine.appc.combat as combat
    hits = []
    monkeypatch.setattr(
        combat, "apply_hit",
        lambda ship, damage, hp, source, **kw: hits.append((ship, damage)),
    )

    ship_death.reset()
    try:
        # --- Step 1: put the wreck through ship_death into the linger phase ---
        ship_death.begin(wreck)
        # Advance past the full throes window so the wreck transitions to linger.
        ship_death.advance(ship_death.THROES_DURATION)

        # Precondition: wreck is now a dead, targetable linger-phase wreck.
        assert ship_death.is_targetable_wreck(wreck), (
            "wreck should be in the linger phase after THROES_DURATION"
        )
        assert wreck._dead, "wreck._dead should be True after throes expire"

        # --- Step 2: arm the wreck to represent its own prior warp-core breach
        # (the zero-crossing hook would have done this; we do it explicitly here
        # to represent the state the real engine would be in at this point).
        warp_core_breach.arm(wreck)
        # Drain the queue so the wreck is now in _breached (already detonated).
        warp_core_breach.advance(0.0)
        assert wreck in warp_core_breach._breached, (
            "wreck must be in _breached after its own detonation"
        )

        # --- Step 3: neighbour ship breaches; wreck is in the blast radius ---
        warp_core_breach.arm(nbr)
        warp_core_breach.advance(0.0)   # must terminate; no hang

        # --- Invariant assertions ---

        # The wreck must NOT be re-armed: it appears in _breached exactly once
        # (sets cannot have duplicates, but also arm() must not queue it again).
        assert wreck in warp_core_breach._breached, (
            "wreck should still be in _breached"
        )
        # arm() on an already-breached ship is a pure no-op: calling it again
        # must not add it to _armed.
        pre_armed_len = len(warp_core_breach._armed)
        warp_core_breach.arm(wreck)
        assert len(warp_core_breach._armed) == pre_armed_len, (
            "arm(wreck) after detonation must not enqueue it again"
        )

        # The wreck must still be a targetable linger-phase wreck after the
        # neighbour breach — ship_death.begin() must not have restarted its sequence.
        assert ship_death.is_targetable_wreck(wreck), (
            "wreck must remain in the targetable linger window after neighbour breach"
        )

        # What must NOT have happened is a second arm/detonate cycle on the wreck.
        # The _breached guard ensures that; the assertions above already cover it.
        # (combat.apply_hit may be called on the wreck from the neighbour's blast —
        # that is correct behaviour; what we forbid is a fresh arm() + detonate().)

    finally:
        ship_death.reset()
