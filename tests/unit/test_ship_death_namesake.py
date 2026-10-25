"""Dead-hull removal never removes a namesake.

A Quick Battle rebuilds a destroyed station under its old name while the dead
hull may still sit in `ship_death._active`. When the hulk cap evicts it,
`_remove` must not remove the set's entry for that NAME unless it is that ship.
"""
import pytest

import App
from engine.appc import ship_death
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


@pytest.fixture(autouse=True)
def _clean():
    App.g_kSetManager._sets.clear()
    ship_death.reset()
    yield
    ship_death.reset()
    App.g_kSetManager._sets.clear()


def _ship():
    ship = ShipClass()
    ship._hull = HullSubsystem("H")
    ship._hull.SetMaxCondition(1000.0)
    return ship


def _make_set():
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    return pSet


def _kill(ship):
    ship_death.begin(ship)
    ship_death.advance(ship_death.MAX_THROES_DURATION)
    ship_death.advance(ship_death.WRECK_LINGER_DURATION)


def test_evicting_a_hulk_leaves_its_namesake():
    pSet = _make_set()
    old = _ship()
    pSet.AddObjectToSet(old, "A")
    _kill(old)
    pSet.RemoveObjectFromSet("A")
    new = _ship()
    pSet.AddObjectToSet(new, "A")
    # The dead hull still believes it belongs to the set.
    old._containing_set = pSet
    for i in range(ship_death.MAX_HULKS):
        other = _ship()
        pSet.AddObjectToSet(other, "H%d" % i)
        _kill(other)
    assert all(e["ship"] is not old for e in ship_death._active)
    assert pSet.GetObject("A") is new


def test_forget_drops_a_dying_ship():
    pSet = _make_set()
    ship = _ship()
    pSet.AddObjectToSet(ship, "A")
    ship_death.begin(ship)
    ship_death.forget(ship)
    assert all(e["ship"] is not ship for e in ship_death._active)
    ship_death.advance(ship_death.MAX_THROES_DURATION + 1.0)
    assert not ship.IsDead()
