"""home_stations subscribes to ship_lifecycle once, at import, and nothing
re-subscribes it. A test fixture that clears the subscriber list without
restoring it would leave every later test with a home-stations module whose
destroyed record never fills. Run after tests/unit/test_ship_lifecycle.py in
one process, this pins that its fixtures put the list back.
"""
from engine.appc import ship_lifecycle
from engine.systems import home_stations


def test_home_stations_is_still_subscribed():
    assert home_stations._on_lifecycle in ship_lifecycle._subscribers
