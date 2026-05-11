"""ShipClass.SetDead publishes a destroyed event exactly on False -> True."""
import pytest

from engine.appc import ship_lifecycle
from engine.appc.ships import ShipClass


@pytest.fixture(autouse=True)
def _reset_hub():
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()
    yield
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()


def test_set_dead_true_publishes_destroyed_once():
    events = []
    ship_lifecycle.subscribe(lambda event, ship: events.append(event))
    s = ShipClass()
    s.SetDead(True)
    assert events == ["destroyed"]
    assert s.IsDead() == 1


def test_set_dead_true_twice_publishes_once():
    events = []
    ship_lifecycle.subscribe(lambda event, ship: events.append(event))
    s = ShipClass()
    s.SetDead(True)
    s.SetDead(True)
    assert events == ["destroyed"]


def test_set_dead_false_does_not_publish():
    events = []
    ship_lifecycle.subscribe(lambda event, ship: events.append(event))
    s = ShipClass()
    s.SetDead(False)
    assert events == []
    assert s.IsDead() == 0


def test_resurrection_then_redeath_publishes_again():
    events = []
    ship_lifecycle.subscribe(lambda event, ship: events.append(event))
    s = ShipClass()
    s.SetDead(True)
    s.SetDead(False)
    s.SetDead(True)
    assert events == ["destroyed", "destroyed"]


def test_default_arg_sets_dead_and_publishes():
    events = []
    ship_lifecycle.subscribe(lambda event, ship: events.append(event))
    s = ShipClass()
    s.SetDead()
    assert events == ["destroyed"]
    assert s.IsDead() == 1
