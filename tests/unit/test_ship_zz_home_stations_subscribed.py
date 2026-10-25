"""home_stations subscribes to ship_lifecycle once, at import, and nothing
re-subscribes it. A test fixture that clears the subscriber list without
putting it back would leave every later test with a home-stations module whose
destroyed record never fills.

THE FILE NAME IS DELIBERATE. Pytest runs files alphabetically, and this test
must run AFTER the three hub-fixture files -- test_sets_publish_lifecycle.py,
test_ship_lifecycle.py and test_ship_set_dead_publishes.py -- in one process,
so it catches any of their fixtures dropping the import-time subscribers.
"test_ship_zz_" sorts after all three; do not rename it to sort earlier.
"""
from engine.appc import ship_lifecycle
from engine.systems import home_stations


def test_home_stations_is_still_subscribed():
    assert home_stations._on_lifecycle in ship_lifecycle._subscribers
