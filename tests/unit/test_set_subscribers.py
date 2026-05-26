"""Unit tests for SetClass subscribe/unsubscribe + add/remove notifications."""
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass


def _ship(name):
    s = ShipClass(); s.SetName(name); return s


def test_subscriber_receives_added_event():
    s = SetClass()
    received = []
    s.subscribe(lambda event, obj, identifier: received.append((event, identifier)))
    ship = _ship("A")

    s.AddObjectToSet(ship, "A")

    assert received == [("added", "A")]


def test_subscriber_receives_removed_event():
    s = SetClass()
    ship = _ship("A")
    s.AddObjectToSet(ship, "A")

    received = []
    s.subscribe(lambda event, obj, identifier: received.append((event, identifier)))
    s.RemoveObjectFromSet("A")

    assert received == [("removed", "A")]


def test_unsubscribe_stops_notifications():
    s = SetClass()
    received = []
    cb = lambda event, obj, identifier: received.append(event)
    s.subscribe(cb)
    s.unsubscribe(cb)

    s.AddObjectToSet(_ship("A"), "A")

    assert received == []


def test_multiple_subscribers_all_fire():
    s = SetClass()
    a_calls, b_calls = [], []
    s.subscribe(lambda *args: a_calls.append(args[0]))
    s.subscribe(lambda *args: b_calls.append(args[0]))

    s.AddObjectToSet(_ship("X"), "X")

    assert a_calls == ["added"]
    assert b_calls == ["added"]


def test_subscriber_exceptions_do_not_stop_other_subscribers():
    """A broken subscriber must not break the rest of the chain."""
    s = SetClass()
    received_b = []
    def bad(*args): raise RuntimeError("subscriber bug")
    def good(*args): received_b.append(args[0])
    s.subscribe(bad)
    s.subscribe(good)

    s.AddObjectToSet(_ship("X"), "X")

    assert received_b == ["added"]
