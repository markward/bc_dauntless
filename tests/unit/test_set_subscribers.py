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


# ── Auto-mirror tests ─────────────────────────────────────────────────────────

def _setup_bridge_set():
    """Register a fresh "bridge" set in the manager and return it.
    Caller is responsible for teardown via DeleteSet."""
    import App
    bridge = SetClass()
    App.g_kSetManager.AddSet(bridge, "bridge")
    return bridge


def test_ship_added_to_mission_set_appears_in_bridge():
    """Auto-mirror — a ship spawned into a non-bridge mission set is
    also reachable via the global "bridge" set."""
    import App
    bridge = _setup_bridge_set()
    try:
        mission = SetClass()
        App.g_kSetManager.AddSet(mission, "Biranu1")
        try:
            ship = _ship("Player")
            mission.AddObjectToSet(ship, "Player")

            assert bridge.GetObject("Player") is ship
            # Original set retains the ship as primary container.
            assert ship._containing_set is mission
        finally:
            App.g_kSetManager.DeleteSet("Biranu1")
    finally:
        App.g_kSetManager.DeleteSet("bridge")


def test_ship_removed_from_mission_set_disappears_from_bridge():
    """Mirror-removal — RemoveObjectFromSet on the mission set drops
    the ship from the bridge mirror too."""
    import App
    bridge = _setup_bridge_set()
    try:
        mission = SetClass()
        App.g_kSetManager.AddSet(mission, "Biranu1")
        try:
            ship = _ship("Enemy")
            mission.AddObjectToSet(ship, "Enemy")
            assert bridge.GetObject("Enemy") is ship

            mission.RemoveObjectFromSet("Enemy")

            assert bridge.GetObject("Enemy") is None
        finally:
            App.g_kSetManager.DeleteSet("Biranu1")
    finally:
        App.g_kSetManager.DeleteSet("bridge")


def test_non_ship_object_not_mirrored():
    """Mirror only fires for ShipClass. Other ObjectClass / placement
    types stay in their original set only."""
    import App
    from engine.appc.objects import ObjectClass
    bridge = _setup_bridge_set()
    try:
        mission = SetClass()
        App.g_kSetManager.AddSet(mission, "Biranu1")
        try:
            obj = ObjectClass()
            mission.AddObjectToSet(obj, "Placeholder")

            assert mission.GetObject("Placeholder") is obj
            assert bridge.GetObject("Placeholder") is None
        finally:
            App.g_kSetManager.DeleteSet("Biranu1")
    finally:
        App.g_kSetManager.DeleteSet("bridge")


def test_bridge_set_adds_do_not_self_mirror():
    """Adding directly to the bridge set does NOT trigger a re-mirror
    loop — the ship lives in bridge once, not twice."""
    import App
    bridge = _setup_bridge_set()
    try:
        ship = _ship("Galaxy")
        bridge.AddObjectToSet(ship, "Galaxy")

        # Single entry, no recursion.
        assert bridge.GetObject("Galaxy") is ship
        # bridge has the placeholder behavior; just confirm one entry
        # for this key, not duplicates.
        keys = [k for k in bridge._objects.keys() if k == "Galaxy"]
        assert keys == ["Galaxy"]
    finally:
        App.g_kSetManager.DeleteSet("bridge")


def test_unmanaged_test_set_does_not_mirror():
    """A SetClass that was never registered with g_kSetManager (empty
    name) doesn't auto-mirror — keeps unit-test isolation intact even
    when the test process happens to have a "bridge" registered."""
    import App
    bridge = _setup_bridge_set()
    try:
        unmanaged = SetClass()  # not registered, _name is ""
        ship = _ship("Lost")
        unmanaged.AddObjectToSet(ship, "Lost")

        assert unmanaged.GetObject("Lost") is ship
        assert bridge.GetObject("Lost") is None
    finally:
        App.g_kSetManager.DeleteSet("bridge")
