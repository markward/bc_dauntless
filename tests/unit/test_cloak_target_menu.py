"""A cloaked ship drops off the player's target menu (and reappears on decloak).

The AI candidate gate (sensor_detection.can_detect) already hides cloaked
contacts from AI target selection, but the player's STTargetMenu is rebuilt from
raw set membership — a cloaked ship never leaves the set, so without a dedicated
gate it lingers in the target list and stays lockable. install_cloak_target_menu_gate
registers broadcast handlers on the cloak events that prune / restore the row.

Boundary matches can_detect: invisible only while fully CLOAKED
(ET_CLOAK_COMPLETED removes; ET_DECLOAK_BEGINNING restores).
"""
import App

from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import CloakingSubsystem
from engine.appc.target_menu import (
    STTargetMenu_CreateW, install_cloak_target_menu_gate,
    reset_cloak_target_menu_gate,
)


def _menu_with_enemy():
    reset_cloak_target_menu_gate()
    menu = STTargetMenu_CreateW("targets")
    install_cloak_target_menu_gate()
    enemy = ShipClass_Create("Warbird")
    enemy.SetName("Enemy")
    enemy.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    menu.RebuildShipMenu(enemy)
    return menu, enemy


def test_cloaked_ship_removed_from_target_menu():
    menu, enemy = _menu_with_enemy()
    assert menu.GetObjectEntry(enemy) is not None
    enemy.GetCloakingSubsystem().InstantCloak()       # ET_CLOAK_COMPLETED
    assert menu.GetObjectEntry(enemy) is None


def test_decloaking_ship_returns_to_target_menu():
    menu, enemy = _menu_with_enemy()
    cloak = enemy.GetCloakingSubsystem()
    cloak.InstantCloak()
    assert menu.GetObjectEntry(enemy) is None
    cloak.StopCloaking()                              # CLOAKED -> DECLOAKING: ET_DECLOAK_BEGINNING
    assert menu.GetObjectEntry(enemy) is not None


def test_cloak_clears_player_lock_on_that_ship():
    menu, enemy = _menu_with_enemy()
    # Player locked onto the enemy that is about to cloak.
    player = ShipClass_Create("Galaxy")
    player.SetName("Player")
    player.SetTarget(enemy)
    assert player.GetTarget() is enemy

    class _Player:
        def GetShip(self):
            return player
    App._current_player = _Player() if hasattr(App, "_current_player") else None

    # Drive the player resolution the gate uses (Game_GetCurrentPlayer).
    import engine.core.game as _game
    saved = _game._current_game

    class _Game:
        def GetCurrentPlayer(self):
            return _Player()
    _game._current_game = _Game()
    try:
        enemy.GetCloakingSubsystem().InstantCloak()
        assert menu.GetObjectEntry(enemy) is None
        assert player.GetTarget() is None
    finally:
        _game._current_game = saved
