"""Unit tests for the target-list SDK shim (engine/appc/target_menu.py)."""
import pytest

import App
from engine.appc.ships import ShipClass


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset module-level singletons between tests so ordering doesn't matter."""
    App._reset_target_menu_singleton()
    yield
    App._reset_target_menu_singleton()


def test_st_subsystem_menu_records_ship_and_defaults_visible():
    ship = ShipClass()
    ship.SetName("Test Ship")
    menu = App.STSubsystemMenu(ship)
    assert menu.GetShip() is ship
    assert menu.IsVisible() == 1


def test_st_subsystem_menu_show_name_methods_are_noops():
    """ShowUnknownName / ShowRealName never called by SDK; must not raise."""
    ship = ShipClass()
    menu = App.STSubsystemMenu(ship)
    menu.ShowUnknownName()
    menu.ShowRealName()


def test_st_component_menu_is_st_menu_subclass():
    """STComponentMenu never invoked from SDK Python; bare subclass is enough."""
    from engine.appc.characters import STMenu
    assert issubclass(App.STComponentMenu, STMenu)


def test_st_target_menu_inherits_st_top_level_menu():
    from engine.appc.characters import STTopLevelMenu
    menu = App.STTargetMenu("Targets")
    assert isinstance(menu, STTopLevelMenu)
    assert menu.GetLabel() == "Targets"


def test_st_target_menu_child_traversal():
    target_menu = App.STTargetMenu("Targets")
    ship_a, ship_b, ship_c = ShipClass(), ShipClass(), ShipClass()
    ship_a.SetName("A"); ship_b.SetName("B"); ship_c.SetName("C")
    sub_a, sub_b, sub_c = (
        App.STSubsystemMenu(ship_a),
        App.STSubsystemMenu(ship_b),
        App.STSubsystemMenu(ship_c),
    )
    target_menu.AddChild(sub_a)
    target_menu.AddChild(sub_b)
    target_menu.AddChild(sub_c)

    assert target_menu.GetFirstChild() is sub_a
    assert target_menu.GetLastChild() is sub_c
    assert target_menu.GetNextChild(sub_a) is sub_b
    assert target_menu.GetNextChild(sub_c) is None
    assert target_menu.GetPrevChild(sub_c) is sub_b
    assert target_menu.GetPrevChild(sub_a) is None


def test_st_target_menu_get_object_entry_by_ship_identity():
    target_menu = App.STTargetMenu("Targets")
    ship_a, ship_b = ShipClass(), ShipClass()
    ship_a.SetName("A"); ship_b.SetName("B")
    sub_a = App.STSubsystemMenu(ship_a)
    sub_b = App.STSubsystemMenu(ship_b)
    target_menu.AddChild(sub_a)
    target_menu.AddChild(sub_b)
    assert target_menu.GetObjectEntry(ship_a) is sub_a
    assert target_menu.GetObjectEntry(ship_b) is sub_b
    stranger = ShipClass(); stranger.SetName("?")
    assert target_menu.GetObjectEntry(stranger) is None


def test_create_w_installs_singleton():
    App._reset_target_menu_singleton()
    assert App.STTargetMenu_GetTargetMenu() is None

    menu = App.STTargetMenu_CreateW("Targets")
    assert isinstance(menu, App.STTargetMenu)
    assert menu.GetLabel() == "Targets"
    assert App.STTargetMenu_GetTargetMenu() is menu


def test_subsystem_menu_cast_lenient_passthrough():
    """Mirrors STMenu_Cast — real instance → self; None → None; other → pass through."""
    ship = ShipClass()
    menu = App.STSubsystemMenu(ship)
    assert App.STSubsystemMenu_Cast(menu) is menu
    assert App.STSubsystemMenu_Cast(None) is None
    sentinel = object()
    assert App.STSubsystemMenu_Cast(sentinel) is sentinel


def test_clear_target_list_removes_all_rows():
    target_menu = App.STTargetMenu("Targets")
    target_menu.AddChild(App.STSubsystemMenu(ShipClass()))
    target_menu.AddChild(App.STSubsystemMenu(ShipClass()))
    target_menu.ClearTargetList()
    assert target_menu.GetFirstChild() is None


def test_clear_persistent_target_drops_hint():
    target_menu = App.STTargetMenu("Targets")
    target_menu.SetPersistentTarget("USS Enterprise")
    assert target_menu.GetPersistentTarget() == "USS Enterprise"
    target_menu.ClearPersistentTarget()
    assert target_menu.GetPersistentTarget() is None


def _make_mission_with_groups(friendly=(), enemy=(), neutral=()):
    from engine.core.game import Mission
    m = Mission()
    for name in friendly:
        m.GetFriendlyGroup().AddName(name)
    for name in enemy:
        m.GetEnemyGroup().AddName(name)
    for name in neutral:
        m.GetNeutralGroup().AddName(name)
    return m


def test_resolve_affiliation_uses_mission_groups():
    from engine.appc.target_menu import resolve_affiliation
    mission = _make_mission_with_groups(
        friendly=["F"], enemy=["E"], neutral=["N"]
    )
    f = ShipClass(); f.SetName("F")
    e = ShipClass(); e.SetName("E")
    n = ShipClass(); n.SetName("N")
    u = ShipClass(); u.SetName("U")
    assert resolve_affiliation(f, mission) == "FRIENDLY"
    assert resolve_affiliation(e, mission) == "ENEMY"
    assert resolve_affiliation(n, mission) == "NEUTRAL"
    assert resolve_affiliation(u, mission) == "UNKNOWN"


def test_reset_affiliation_colors_recomputes_each_row():
    from engine.core.game import Game, Episode, _set_current_game

    mission = _make_mission_with_groups(friendly=["Dauntless"], enemy=["Kor"])
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    _set_current_game(game)
    try:
        a = ShipClass(); a.SetName("Dauntless")
        b = ShipClass(); b.SetName("Kor")
        target_menu = App.STTargetMenu("Targets")
        sub_a, sub_b = App.STSubsystemMenu(a), App.STSubsystemMenu(b)
        target_menu.AddChild(sub_a); target_menu.AddChild(sub_b)

        target_menu.ResetAffiliationColors()
        assert sub_a.GetAffiliation() == "FRIENDLY"
        assert sub_b.GetAffiliation() == "ENEMY"

        # Defection: Kor changes sides mid-mission.
        mission.GetEnemyGroup().RemoveName("Kor")
        mission.GetFriendlyGroup().AddName("Kor")
        target_menu.ResetAffiliationColors()
        assert sub_b.GetAffiliation() == "FRIENDLY"
    finally:
        _set_current_game(None)
