"""Persistent wrecks — a dead hull stays in the world after its death sequence.

BC removed the hull the moment the death lifetime expired, and our sequence
matched that: throes, then a 5 s selectable-wreck linger, then gone. Five quiet
seconds after a 5-15 s death reads as vanishing on the spot.

So a dead hull now enters a third phase and STAYS: a hulk. It keeps drawing and
colliding for free (both the renderer's reaper and `iter_collidables` walk set
membership, with no dead filter), but drops out of the target list, because a
battle whose target list fills with corpses is worse than one without wrecks.
Bounded by a global cap, oldest evicted, so a long fight cannot grow without
limit.

This is a deliberate deviation from BC, not recovered behaviour.
"""
import pytest

from engine.appc import death_cascade, ship_death


class FakeSet:
    def __init__(self):
        self.removed = []
    def RemoveObjectFromSet(self, name):
        self.removed.append(name)


class FakeShip:
    def __init__(self, name="Enemy1", containing_set=None, radius=1.0):
        self._name = name
        self._set = containing_set if containing_set is not None else FakeSet()
        self._radius = radius
        self._dying = False
        self._dead = False
    def GetName(self):           return self._name
    def GetContainingSet(self):  return self._set
    def GetRadius(self):         return self._radius
    def GetLifeTime(self):       return 1.0e30
    def GetNode(self):           return None
    def AddDamage(self, *a):     pass
    def GetRandomPointOnModel(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(0.0, 0.0, 0.0)
    def IsDying(self):           return 1 if self._dying else 0
    def IsDead(self):            return 1 if self._dead else 0
    def SetDying(self, v):       self._dying = bool(v)
    def SetDead(self, v=True):   self._dead = bool(v) if v is not True else True


@pytest.fixture(autouse=True)
def _clean():
    ship_death.reset()
    yield
    ship_death.reset()


def _kill(ship):
    """Run a ship all the way through throes and the selectable-wreck linger."""
    ship_death.begin(ship)
    ship_death.advance(ship_death.MAX_THROES_DURATION)
    ship_death.advance(ship_death.WRECK_LINGER_DURATION)


def test_wreck_stays_in_the_world_after_the_death_sequence():
    """The headline: the hull is NOT removed when the linger expires."""
    s = FakeSet()
    ship = FakeShip(name="Doomed", containing_set=s)
    _kill(ship)
    assert s.removed == [], "the hull was removed instead of becoming a hulk"


def test_hulk_persists_indefinitely():
    s = FakeSet()
    ship = FakeShip(name="Doomed", containing_set=s)
    _kill(ship)
    for _ in range(600):
        ship_death.advance(1.0)          # ten more minutes
    assert s.removed == []


def test_hulk_drops_out_of_the_target_list():
    """A selectable corpse is worse than no wreck at all. The wreck stays
    selectable through the linger, then stops."""
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.advance(ship_death.MAX_THROES_DURATION)
    assert ship_death.is_targetable_wreck(ship) is True    # linger: selectable
    ship_death.advance(ship_death.WRECK_LINGER_DURATION)
    assert ship_death.is_targetable_wreck(ship) is False   # hulk: not


def test_locks_release_when_the_wreck_stops_being_targetable(monkeypatch):
    """Locks must clear at the linger->hulk transition, or the player stays
    locked onto a corpse forever."""
    cleared = []
    monkeypatch.setattr(ship_death, "_clear_target_locks",
                        lambda s: cleared.append(s))
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.advance(ship_death.MAX_THROES_DURATION)
    assert cleared == []
    ship_death.advance(ship_death.WRECK_LINGER_DURATION)
    assert cleared == [ship]


def test_oldest_hulk_is_evicted_at_the_cap():
    """Bounded worst case: a massacre cannot grow the scene without limit."""
    sets = []
    for i in range(ship_death.MAX_HULKS + 1):
        s = FakeSet()
        sets.append(s)
        _kill(FakeShip(name=f"Wreck{i}", containing_set=s))

    assert sets[0].removed == [f"Wreck0"], "the oldest hulk was not evicted"
    for s in sets[1:]:
        assert s.removed == [], "a hulk inside the cap was evicted"


def test_cap_holds_across_many_deaths():
    sets = []
    for i in range(ship_death.MAX_HULKS * 3):
        s = FakeSet()
        sets.append(s)
        _kill(FakeShip(name=f"Wreck{i}", containing_set=s))
    still_present = sum(1 for s in sets if not s.removed)
    assert still_present == ship_death.MAX_HULKS


def test_reset_clears_hulks():
    ship = FakeShip()
    _kill(ship)
    ship_death.reset()
    assert ship_death.is_targetable_wreck(ship) is False
    assert ship_death._active == []
