"""Headless: Helm's Intercept lights on targeting in Quick Battle, through a
bridge swap and End Combat's new player.

QB creates the player LATE (StartSimulation2 -> RecreatePlayer ->
CreatePlayerShip), reloads the bridge for the battle ship's class after that,
and recreates the player again on End Combat. Each player must get the
officers attached BEFORE the ET_SET_PLAYER listeners, or Science's
TargetChanged (which never calls CallNextHandler) swallows the event ahead of
Helm's (engine/bridge_officers.py:configure_for_player).
"""
import pytest

pytest.importorskip("_dauntless_host")

from tests.integration.test_quickbattle_setup_e2e import (  # noqa: E402
    _do, _go, _ships, world,  # noqa: F401  (world is a fixture)
)


def _target_and_read_intercept(player, target):
    import Bridge.BridgeUtils as BridgeUtils
    from engine.bridge_officers import wire_after_mission_load
    wire_after_mission_load()   # the host's post-load step, as live
    player.SetTarget(target.GetName())
    return BridgeUtils.GetBridgeMenu("Helm").GetButtonW("Intercept").IsEnabled()


def test_intercept_lights_in_a_sovereign_battle_and_after_end_combat(world):
    hl, _c, panel, QB = world
    import App
    _do(panel, "set-player:Sovereign", "add:Warbird")
    _go(hl, panel)
    player = App.Game_GetCurrentGame().GetPlayer()
    warbird = _ships(QB)["Warbird-1"]
    assert _target_and_read_intercept(player, warbird) == 1

    QB.EndSimulation()
    hl._process_object_deletions()
    home = App.Game_GetCurrentGame().GetPlayer()
    assert home is not player
    # The battle ships are gone; any other object in the set is a target.
    target = next(o for o in home.GetContainingSet().GetClassObjectList(
        App.CT_OBJECT) if o is not home)
    assert _target_and_read_intercept(home, target) == 1
