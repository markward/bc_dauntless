"""A fully cloaked ship drops off the player's target list / radar and can't be
held as a weapon lock — the same per-render road the destruction filter uses.

Surfaces (all keyed on sensor_detection.is_hidden_by_cloak):
  * radar / sensor panel — filters rows on STSubsystemMenu.IsVisible(); the
    per-tick update_target_list_visibility now marks cloaked rows NotVisible.
  * target list view — its _snapshot inclusion predicate drops cloaked ships
    alongside _out_of_action (destroyed) ships.
  * player weapon lock — the host loop clears GetTarget() when it cloaks, which
    also silences fire (FireWeapons no-ops with no target).

Boundary matches can_detect: hidden only while fully CLOAKED, visible again the
moment it starts decloaking.
"""
import App

from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import CloakingSubsystem
from engine.appc.sensor_detection import is_hidden_by_cloak
from engine.appc.target_menu import STTargetMenu_CreateW, STSubsystemMenu
from engine.ui.target_list_visibility import update_target_list_visibility


def _scene():
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    player = ShipClass_Create("Galaxy")
    player.SetName("Player")
    player.SetTranslateXYZ(0, 0, 0)
    pSet.AddObjectToSet(player, "Player")
    enemy = ShipClass_Create("Warbird")
    enemy.SetName("Enemy")
    enemy.SetTranslateXYZ(0, 50, 0)
    enemy.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    pSet.AddObjectToSet(enemy, "Enemy")
    menu = STTargetMenu_CreateW("Targets")
    menu.RebuildShipMenus(pSet)
    return pSet, player, enemy, menu


def _enemy_visible(menu, enemy):
    row = menu.GetObjectEntry(enemy)
    assert isinstance(row, STSubsystemMenu)
    return row.IsVisible() == 1


def test_is_hidden_by_cloak_predicate():
    enemy = ShipClass_Create("Warbird")
    enemy.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    assert not is_hidden_by_cloak(enemy)            # DECLOAKED
    enemy.GetCloakingSubsystem().StartCloaking()    # CLOAKING — still visible
    assert not is_hidden_by_cloak(enemy)
    enemy.GetCloakingSubsystem().InstantCloak()     # CLOAKED — hidden
    assert is_hidden_by_cloak(enemy)
    # A ship with no cloak is never hidden.
    plain = ShipClass_Create("Galaxy")
    assert not is_hidden_by_cloak(plain)


def test_cloaked_ship_marked_not_visible_for_radar():
    pSet, player, enemy, menu = _scene()
    update_target_list_visibility(menu, pSet.GetObjectList(), player, range_units=30000.0)
    assert _enemy_visible(menu, enemy)
    enemy.GetCloakingSubsystem().InstantCloak()
    update_target_list_visibility(menu, pSet.GetObjectList(), player, range_units=30000.0)
    assert not _enemy_visible(menu, enemy)
    # Decloak restores it.
    enemy.GetCloakingSubsystem().InstantDecloak()
    update_target_list_visibility(menu, pSet.GetObjectList(), player, range_units=30000.0)
    assert _enemy_visible(menu, enemy)


def test_cloaked_ship_dropped_from_target_list_view():
    pSet, player, enemy, menu = _scene()

    class _Game:
        def GetPlayer(self):
            return player
        GetCurrentPlayer = GetPlayer
    import engine.core.game as _gmod
    saved = _gmod._current_game
    _gmod._current_game = _Game()
    try:
        from engine.ui.target_list_view import TargetListView
        view = TargetListView()
        rows_before = view._snapshot()[3]
        names_before = {r[0] for r in rows_before}
        assert "Enemy" in names_before

        enemy.GetCloakingSubsystem().InstantCloak()
        rows_after = view._snapshot()[3]
        names_after = {r[0] for r in rows_after}
        assert "Enemy" not in names_after
    finally:
        _gmod._current_game = saved


def test_player_lock_logic_drops_cloaked_target():
    """Mirror the host-loop guard: a player lock on a cloaked ship is dropped."""
    _, player, enemy, _ = _scene()
    player.SetTarget(enemy)
    assert player.GetTarget() is enemy
    # Not yet cloaked → lock holds.
    if player.GetTarget() is not None and is_hidden_by_cloak(player.GetTarget()):
        player.SetTarget(None)
    assert player.GetTarget() is enemy
    # Fully cloaked → the guard drops it.
    enemy.GetCloakingSubsystem().InstantCloak()
    if player.GetTarget() is not None and is_hidden_by_cloak(player.GetTarget()):
        player.SetTarget(None)
    assert player.GetTarget() is None
