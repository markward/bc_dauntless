"""Load a real SDK mission headlessly and drive its Warp button (spec:
Testing -- the campaign transitions and the handler sweep).

`load(name)` is the dev loader's own path (host_loop._init_mission) on a
fresh world; the warp runs its fallback branch, since the flythrough VFX is
off headless, but the queues, WaitForQueued and _MissionChangePoint all run.
"""
import pytest

import App
from engine import host_loop
from engine.appc import dash, warp, warp_button
from engine.core.loop import GameLoop, TICK_DELTA
from tests.helpers.fresh_world import _fresh_world

# Bound on one warp, in game time (Task 8 brief). The master dialogue a
# mission has queued holds the transit (WaitForQueued), so this is long.
WARP_BOUND_S = 120.0
# A warp pressed during a mission's opening waits (WaitForQueued) for all of
# its queued dialogue: E8M2's runs ~255 s of game time headless.
MASTER_DIALOGUE_BOUND_S = 600.0


def load(name):
    """(mission, episode, game, mod) for mission module `name`, loaded the
    way the dev picker loads it."""
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


def _sim_tick(loop, player=None) -> None:
    """One sim tick plus the per-frame work the host does for the player's
    dash (engine/appc/dash.py) -- the host calls dash.tick each frame, the
    GameLoop does not, so a harness wait on is_warp_active needs it too."""
    loop.tick()
    if player is None:
        player = App.Game_GetCurrentPlayer()
    if player is not None:
        dash.tick(player, TICK_DELTA)


def tick(seconds, loop=None) -> None:
    loop = loop or GameLoop()
    for _ in range(int(round(seconds / TICK_DELTA))):
        _sim_tick(loop)


def warp_and_wait(button, player, bound_s=WARP_BOUND_S,
                  after_tick=None) -> float:
    """Press Warp, then tick until the player's warp sequence detaches.
    Returns the game seconds it took (0 when the warp ran to completion
    inside the press: the hard cut with nothing to wait for is synchronous);
    raises AssertionError if it is still attached after `bound_s`. Callers
    assert the outcome -- a refused warp also returns 0. `after_tick()` runs
    after every sim tick, where the host's frame does its per-frame work
    (the WarpVFX tick)."""
    warp_button.press(button)
    if not warp_button.is_warp_active(player):
        return 0.0
    loop = GameLoop()
    for i in range(int(round(bound_s / TICK_DELTA))):
        _sim_tick(loop, player)
        if after_tick is not None:
            after_tick()
        if not warp_button.is_warp_active(player):
            return (i + 1) * TICK_DELTA
    raise AssertionError("the warp was still attached after %.0f s" % bound_s)


def placement_location(set_name, placement):
    pSet = App.g_kSetManager.GetSet(set_name)
    wp = pSet.GetObject(placement) if pSet is not None else None
    return wp.GetWorldLocation() if wp is not None else None


def first_offered_course(exclude_set=None):
    """The first region module the live Set Course menu offers whose set is
    not `exclude_set` (the player's own), or None."""
    from engine.appc.tg_ui.st_widgets import SortedRegionMenu

    def _walk(node):
        mod = (node.GetRegionModule()
               if isinstance(node, SortedRegionMenu) else None)
        if mod and warp._set_name_from_module(mod) != exclude_set:
            return mod
        # __dict__ read: see warp.region_menu_for_destination.
        for entry in node.__dict__.get("_children", []):
            child = entry[0] if isinstance(entry, tuple) else entry
            found = _walk(child)
            if found:
                return found
        return None

    menu = warp.find_set_course_menu()
    return _walk(menu) if menu is not None else None


@pytest.fixture
def no_logged_failures(capfd):
    """A handler that raises inside a broadcast is logged and swallowed
    (events.py), and a failed change is printed and returns False -- read
    both logs so neither can pass silently."""
    yield
    out, err = capfd.readouterr()
    for marker in ("[events] broadcast handler", "[mission_change]",
                   "Traceback"):
        assert marker not in out + err, (out + err)[-4000:]


def tick_until(pred, bound_s=WARP_BOUND_S) -> None:
    loop = GameLoop()
    for _ in range(int(round(bound_s / TICK_DELTA))):
        if pred():
            return
        _sim_tick(loop)
    raise AssertionError("condition not reached in %.0f s" % bound_s)
