"""Load a real SDK mission headlessly and drive its Warp button (spec:
Testing -- the campaign transitions and the handler sweep).

`load(name)` is the dev loader's own path (host_loop._init_mission) on a
fresh world; the warp runs its fallback branch, since the flythrough VFX is
off headless, but the queues, WaitForQueued and _MissionChangePoint all run.
"""
import App
from engine import host_loop
from engine.appc import warp, warp_button, warp_gates
from engine.core import mission_change
from engine.core.loop import GameLoop, TICK_DELTA
from tests.integration.test_sdk_bridge_load import _fresh_world

# Bound on one warp, in game time (Task 8 brief). The master dialogue a
# mission has queued holds the transit (WaitForQueued), so this is long.
WARP_BOUND_S = 120.0


def load(name):
    """(mission, episode, game, mod) for mission module `name`, loaded the
    way the dev picker loads it, with the warp's host hooks, VFX and the
    starbase line-of-sight gate hook unset (host_loop.run() installs them and
    does not uninstall them; left over, the starbase hook reads a stale
    session and refuses every warp near Starbase 12)."""
    warp.configure_warp_hooks(realize=None, teardown=None)
    warp_gates.configure_gate_hooks(ray_collide=None)
    warp.configure_warp_vfx(start=None, stop=None, enabled=None,
                            vantage_of=None)
    mission_change.configure(on_changed=None)
    _fresh_world()
    return host_loop._init_mission(name)


def the_warp_button():
    import Bridge.BridgeUtils
    return Bridge.BridgeUtils.GetWarpButton()


def plot_course(button, dest) -> None:
    """What host_loop.record_course_selection does to the button, minus the
    Helm officer's acknowledgement."""
    button.set_player_destination(dest)
    warp.set_course_placement(button, dest)


def current_mission_name(game):
    ep = game.GetCurrentEpisode()
    mis = ep.GetCurrentMission() if ep is not None else None
    return mis._module_name if mis is not None else None


def tick(seconds, loop=None) -> None:
    loop = loop or GameLoop()
    for _ in range(int(round(seconds / TICK_DELTA))):
        loop.tick()


def warp_and_wait(button, player, bound_s=WARP_BOUND_S) -> float:
    """Press Warp, then tick until the player's warp sequence detaches.
    Returns the game seconds it took (0 when the warp ran to completion
    inside the press: the hard cut with nothing to wait for is synchronous);
    raises AssertionError if it is still attached after `bound_s`. Callers
    assert the outcome -- a refused warp also returns 0."""
    warp_button.press(button)
    if not warp_button.is_warp_active(player):
        return 0.0
    loop = GameLoop()
    for i in range(int(round(bound_s / TICK_DELTA))):
        loop.tick()
        if not warp_button.is_warp_active(player):
            return (i + 1) * TICK_DELTA
    raise AssertionError("the warp was still attached after %.0f s" % bound_s)


def placement_location(set_name, placement):
    pSet = App.g_kSetManager.GetSet(set_name)
    wp = pSet.GetObject(placement) if pSet is not None else None
    return wp.GetWorldLocation() if wp is not None else None


def first_offered_course():
    """The first region module the live Set Course menu offers, or None."""
    from engine.appc.tg_ui.st_widgets import SortedRegionMenu

    def _walk(node):
        if isinstance(node, SortedRegionMenu) and node.GetRegionModule():
            return node.GetRegionModule()
        # __dict__ read: see warp.region_menu_for_destination.
        for entry in node.__dict__.get("_children", []):
            child = entry[0] if isinstance(entry, tuple) else entry
            found = _walk(child)
            if found:
                return found
        return None

    menu = warp.find_set_course_menu()
    return _walk(menu) if menu is not None else None
