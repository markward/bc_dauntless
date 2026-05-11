"""SetClass.AddObjectToSet publishes ship-added events for ShipClass objects."""
import pytest

from engine.appc import ship_lifecycle
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


@pytest.fixture(autouse=True)
def _reset_hub():
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()
    yield
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()


def test_adding_a_ship_publishes_added_event():
    events = []
    ship_lifecycle.subscribe(lambda event, ship: events.append((event, ship)))
    pSet = SetClass()
    pShip = ShipClass()
    pSet.AddObjectToSet(pShip, "Galaxy 1")
    assert events == [("added", pShip)]
    assert pShip in ship_lifecycle.snapshot()


def test_adding_a_non_ship_does_not_publish():
    events = []
    ship_lifecycle.subscribe(lambda event, ship: events.append((event, ship)))
    pSet = SetClass()
    class _NotAShip:
        def SetName(self, _): pass
    pSet.AddObjectToSet(_NotAShip(), "waypoint")
    assert events == []


def test_adding_same_ship_twice_does_not_double_track_in_live():
    pSet = SetClass()
    pShip = ShipClass()
    pSet.AddObjectToSet(pShip, "alpha")
    pSet.AddObjectToSet(pShip, "beta")
    assert ship_lifecycle.snapshot() == (pShip,)
