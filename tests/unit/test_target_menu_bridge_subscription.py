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
