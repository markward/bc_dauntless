"""Tests for the engine.appc.ship_lifecycle pub/sub hub."""
import pytest

from engine.appc import ship_lifecycle


@pytest.fixture(autouse=True)
def _reset_hub():
    # Clean slate for the test, then put back the import-time subscribers
    # (home_stations, engine_rumble, ...): nothing re-subscribes them, so a
    # bare clear() would leak into every later test in the process.
    saved = list(ship_lifecycle._subscribers)
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()
    yield
    ship_lifecycle._subscribers[:] = saved
    ship_lifecycle._live.clear()


class _Ship:
    """Minimal stand-in — ship_lifecycle does not call any ship methods."""


def test_publish_added_records_in_live_and_fans_out():
    seen = []
    ship_lifecycle.subscribe(lambda event, ship: seen.append((event, ship)))
    s = _Ship()
    ship_lifecycle.publish_added(s)
    assert seen == [("added", s)]
    assert s in ship_lifecycle.snapshot()


def test_publish_destroyed_removes_from_live_and_fans_out():
    s = _Ship()
    ship_lifecycle.publish_added(s)
    seen = []
    ship_lifecycle.subscribe(lambda event, ship: seen.append((event, ship)))
    ship_lifecycle.publish_destroyed(s)
    assert seen == [("destroyed", s)]
    assert s not in ship_lifecycle.snapshot()


def test_publish_destroyed_on_unknown_ship_is_idempotent():
    seen = []
    ship_lifecycle.subscribe(lambda event, ship: seen.append((event, ship)))
    s = _Ship()
    ship_lifecycle.publish_destroyed(s)
    assert seen == [("destroyed", s)]
    assert s not in ship_lifecycle.snapshot()


def test_unsubscribe_handle_stops_delivery():
    seen = []
    unsub = ship_lifecycle.subscribe(lambda event, ship: seen.append(event))
    ship_lifecycle.publish_added(_Ship())
    unsub()
    ship_lifecycle.publish_added(_Ship())
    assert seen == ["added"]


def test_unsubscribe_is_idempotent():
    unsub = ship_lifecycle.subscribe(lambda event, ship: None)
    unsub()
    unsub()


def test_subscriber_exception_does_not_break_others():
    seen = []
    def boom(event, ship):
        raise RuntimeError("kaboom")
    ship_lifecycle.subscribe(boom)
    ship_lifecycle.subscribe(lambda event, ship: seen.append(event))
    ship_lifecycle.publish_added(_Ship())
    assert seen == ["added"]


def test_reset_clears_live_but_not_subscribers():
    seen = []
    ship_lifecycle.subscribe(lambda event, ship: seen.append(event))
    ship_lifecycle.publish_added(_Ship())
    assert len(ship_lifecycle.snapshot()) == 1
    ship_lifecycle.reset()
    assert ship_lifecycle.snapshot() == ()
    ship_lifecycle.publish_added(_Ship())
    assert seen == ["added", "added"]


def test_snapshot_returns_tuple():
    ship_lifecycle.publish_added(_Ship())
    snap = ship_lifecycle.snapshot()
    assert isinstance(snap, tuple)
