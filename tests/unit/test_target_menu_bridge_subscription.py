"""wire_to_bridge_set hooks the target-menu singleton to a bridge set."""
import App
from engine.appc.ships import ShipClass
from engine.appc.sets import SetClass


def _ship(name):
    s = ShipClass(); s.SetName(name); return s


def _setup_game_with_groups(friendly=(), enemy=()):
    """Required because ResetAffiliationColors consults the current
    game's mission for group lookups."""
    from engine.core.game import Game, Episode, Mission, _set_current_game
    mission = Mission()
    for n in friendly:
        mission.GetFriendlyGroup().AddName(n)
    for n in enemy:
        mission.GetEnemyGroup().AddName(n)
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    _set_current_game(game)
    return game


def test_wire_to_bridge_set_adds_row_when_ship_enters():
    from engine.appc.target_menu import wire_to_bridge_set

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    bridge = SetClass()
    _setup_game_with_groups(friendly=["Dauntless"])
    try:
        wire_to_bridge_set(bridge)
        ship = _ship("Dauntless")
        bridge.AddObjectToSet(ship, "Dauntless")

        row = target_menu.GetObjectEntry(ship)
        assert row is not None
        assert row.GetAffiliation() == "FRIENDLY"
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_wire_to_bridge_set_removes_row_when_ship_leaves():
    from engine.appc.target_menu import wire_to_bridge_set

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    bridge = SetClass()
    _setup_game_with_groups(enemy=["Kor"])
    try:
        wire_to_bridge_set(bridge)
        ship = _ship("Kor")
        bridge.AddObjectToSet(ship, "Kor")
        assert target_menu.GetObjectEntry(ship) is not None

        bridge.RemoveObjectFromSet("Kor")
        assert target_menu.GetObjectEntry(ship) is None
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_wire_to_bridge_set_is_idempotent_for_singleton():
    """Calling wire_to_bridge_set twice on the same set must not produce
    duplicate rows on subsequent add events."""
    from engine.appc.target_menu import wire_to_bridge_set

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    bridge = SetClass()
    _setup_game_with_groups(friendly=["Dauntless"])
    try:
        wire_to_bridge_set(bridge)
        wire_to_bridge_set(bridge)  # second call
        ship = _ship("Dauntless")
        bridge.AddObjectToSet(ship, "Dauntless")

        rows = [c for c in target_menu._children]
        assert len(rows) == 1
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_unwire_stops_subsequent_events():
    """After unwire_from_bridge_set, add/remove on the same set
    must no longer drive the target menu."""
    from engine.appc.target_menu import wire_to_bridge_set, unwire_from_bridge_set

    App._reset_target_menu_singleton()
    target_menu = App.STTargetMenu_CreateW("Targets")
    bridge = SetClass()
    _setup_game_with_groups(friendly=["A"])
    try:
        wire_to_bridge_set(bridge)
        unwire_from_bridge_set(bridge)

        ship = _ship("A")
        bridge.AddObjectToSet(ship, "A")

        # Subscriber removed — no row should have been added.
        assert target_menu.GetObjectEntry(ship) is None
    finally:
        from engine.core.game import _set_current_game
        _set_current_game(None)


def test_reset_sdk_globals_unwires_from_bridge_set():
    """reset_sdk_globals removes the subscriber from the bridge set
    so a mission swap doesn't leave a dangling callback."""
    from engine.host_loop import reset_sdk_globals
    from engine.appc.target_menu import wire_to_bridge_set

    App._reset_target_menu_singleton()
    App.STTargetMenu_CreateW("Targets")
    bridge = App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        from engine.appc.sets import SetClass
        bridge = SetClass()
        App.g_kSetManager.AddSet(bridge, "bridge")
    wire_to_bridge_set(bridge)
    assert len(bridge._subscribers) == 1

    reset_sdk_globals()

    # Subscriber removed (either directly via unwire, or because the
    # set itself was dropped from the manager — both acceptable).
    if "bridge" in App.g_kSetManager._sets:
        # Set still in manager → must have no subscribers
        assert len(App.g_kSetManager.GetSet("bridge")._subscribers) == 0
    # Either way, the subscription on the original bridge ref is gone.
    assert len(bridge._subscribers) == 0


def test_reset_sdk_globals_safe_when_no_subscription():
    """Calling reset_sdk_globals without ever wiring must not raise."""
    from engine.host_loop import reset_sdk_globals

    App._reset_target_menu_singleton()
    reset_sdk_globals()  # must not raise
