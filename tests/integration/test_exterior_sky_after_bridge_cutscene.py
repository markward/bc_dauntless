"""The space view never takes its sky or lights from the bridge set.

E2M0's Warbird decloak cutscene ends with ChangeRenderedSet("bridge")
(E2M0.py:1924). The bridge set has a light but no backdrops, so while it was
the explicit rendered set the exterior view drew no sky at all (the plain
clear colour) and lit the player's ship with the bridge light, until the next
warp changed the rendered set. Found live, 2026-09-28.
"""
import App
from engine import host_loop
from tests.helpers import headless_mission as hm
from tests.helpers.headless_mission import no_logged_failures  # noqa: F401 (fixture)


def test_e2m0_decloak_cutscene_end_keeps_the_players_sky(no_logged_failures):
    hm.load("Maelstrom.Episode2.E2M0.E2M0")
    player = App.Game_GetCurrentPlayer()
    tevron = player.GetContainingSet()
    assert tevron.GetName() == "Tevron2"
    assert host_loop._resolve_active_set(player) is tevron

    import Actions.CameraScriptActions as camera_actions
    camera_actions.ChangeRenderedSet(None, "bridge")
    assert App.g_kSetManager.get_explicit_rendered_set().GetName() == "bridge"

    active = host_loop._resolve_active_set(player)
    assert active is tevron
    assert host_loop._authored_backdrops(active)


def test_rendered_bridge_set_is_skipped_without_a_player():
    """No player to fall back to: no exterior set at all, never the bridge."""
    App.g_kSetManager._rendered_set_name = None
    bridge = App.SetClass_Create()
    bridge.CreateAmbientLight(1, 1, 1, 1, "a")
    App.g_kSetManager.AddSet(bridge, "bridge")
    App.g_kSetManager.MakeRenderedSet("bridge")
    try:
        assert host_loop._resolve_active_set(player=None) is None
    finally:
        App.g_kSetManager.DeleteSet("bridge")
        App.g_kSetManager._rendered_set_name = None
