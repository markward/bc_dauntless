"""Changing mission in transit, carrying the player over (spec §2).

A warp that names a mission or episode other than the current one runs
change() at its after-during point. The old mission's (and, on an episode
change, the old episode's) Terminate runs; the world is cleared except for the
Game, the bridge set(s) and BC's "warp" set (and so the player, when it is
in transit there); the next episode or mission loads through the raw loaders.
What is kept and what is reset is spec §2's keep/reset table -- the shared
resets live in engine.host_loop beside reset_sdk_globals (the dev swap, which
keeps nothing), so the two lists cannot drift.
"""
from __future__ import annotations

import re
import sys
import traceback

_in_progress = False
_on_changed = None

_MISSION_MODULE = re.compile(r"^([^.]+)\.(Episode\d+)\.([^.]+)\.\3$")


def configure(on_changed=None) -> None:
    """Host hook: on_changed() runs, with no args, after each successful
    change (never after a refused or failed one)."""
    global _on_changed
    _on_changed = on_changed


def in_progress() -> bool:
    return _in_progress


def is_running_mission(game) -> bool:
    """Whether Game.LoadEpisode / Episode.LoadMission on `game` is a change
    (spec §2 "One mission-change path"): a named mission is current and no
    change is in progress. Otherwise -- boot, or the next episode's Initialize
    inside a change -- they load raw."""
    if _in_progress or game is None:
        return False
    ep = game.GetCurrentEpisode()
    cur = ep.GetCurrentMission() if ep is not None else None
    return cur is not None and bool(cur._module_name)


def episode_module_for(mission_module: str) -> "str | None":
    """"Maelstrom.Episode7.E7M1.E7M1" -> "Maelstrom.Episode7.Episode7";
    None for any name not shaped <Family>.<EpisodeN>.<M>.<M>."""
    m = _MISSION_MODULE.match(mission_module or "")
    if m is None:
        return None
    return "%s.%s.%s" % (m.group(1), m.group(2), m.group(2))


def change(*, mission=None, episode=None) -> bool:
    """End the current mission, clear the world down to what carries over, and
    load the next episode (whose Initialize picks its mission) or mission.
    True iff a change ran. Refused (False) while a change is in progress or
    when neither name differs from the current one. A clear or load that
    raises is printed and returns False, leaving the player where it is."""
    global _in_progress
    if _in_progress:
        return False
    from engine.core.game import Game_GetCurrentGame
    game = Game_GetCurrentGame()
    cur_ep = game.GetCurrentEpisode() if game is not None else None
    if cur_ep is None:
        return False
    cur_mis = cur_ep.GetCurrentMission()
    ep_changes = bool(episode) and episode != cur_ep._module_name
    mis_changes = bool(mission) and (
        cur_mis is None or mission != cur_mis._module_name)
    if not (ep_changes or mis_changes):
        return False

    _in_progress = True
    try:
        _terminate(cur_mis)
        if ep_changes:
            _terminate(cur_ep)
        try:
            _clear_for_next_mission(
                game, cur_mis, cur_ep if ep_changes else None)
        except Exception as e:
            # Raising out of here would stall the warp that called us with
            # the player in the tunnel; fail like a bad load instead.
            print("[mission_change] clearing for %r failed: %s: %s"
                  % (episode if ep_changes else mission, type(e).__name__, e),
                  flush=True)
            traceback.print_exc()
            return False
        try:
            if ep_changes:
                _ensure_campaign_music(game, episode)
                game._load_episode_raw(episode)
            else:
                import App
                from engine.appc.events import TGEvent
                start_evt = TGEvent()
                start_evt.SetEventType(App.ET_MISSION_START)
                start_evt.SetDestination(cur_ep)
                cur_ep._load_mission_raw(mission, start_evt)
        except Exception as e:
            print("[mission_change] loading %r failed: %s: %s"
                  % (episode if ep_changes else mission, type(e).__name__, e),
                  flush=True)
            traceback.print_exc()
            return False
    finally:
        _in_progress = False

    if _on_changed is not None:
        try:
            _on_changed()
        except Exception:
            traceback.print_exc()
    return True


def _ensure_campaign_music(game, episode_module) -> None:
    """Start the campaign's DynamicMusic if nothing has. Every Maelstrom
    Episode*.Initialize calls DynamicMusic.ChangeMusic, which reads the
    globals DynamicMusic.Initialize sets; that runs from the campaign's
    SetupMusic (Maelstrom.py:109), called by the campaign Initialize at boot.
    The dev loader never runs the campaign Initialize, so the first episode
    change out of a dev-loaded mission raised NameError: pStateMachine. BC
    always booted through the campaign, so music was always started by here
    (inferred)."""
    import importlib
    import DynamicMusic
    if DynamicMusic.g_bInitialized:
        return
    family = str(episode_module).split(".")[0]
    try:
        campaign = importlib.import_module("%s.%s" % (family, family))
    except ImportError:
        return
    setup = getattr(campaign, "SetupMusic", None)
    if callable(setup):
        setup(game)


def _terminate(obj) -> None:
    """The SDK module's Terminate(obj), if loaded and defined. A raise is
    printed and the change goes on."""
    if obj is None or not obj._module_name:
        return
    fn = getattr(sys.modules.get(obj._module_name), "Terminate", None)
    if not callable(fn):
        return
    try:
        fn(obj)
    except Exception:
        print("[mission_change] %s.Terminate raised -- continuing"
              % obj._module_name, flush=True)
        traceback.print_exc()


def _clear_for_next_mission(game, old_mission, old_episode) -> None:
    """Delete every set but the carried ones, then apply the reset column of
    spec §2's keep/reset table. `old_episode` is None when the episode stays."""
    import App
    from engine import host_loop
    from engine import dev_tutorial_flag
    from engine.appc import contact_index, warp
    from engine.appc.bridge_set import BridgeSet

    # Only the bridge set(s) and "warp" are kept. BC's native unload deletes
    # every set but the bridge (SDK Maelstrom.py:258-262); that the warp set's
    # occupant alone survives is inferred. On a warp the player is in "warp"
    # and carries over; on a direct load (E2M6's StartEpisode3) its region --
    # and the player in it -- goes, and the next CreatePlayerShip builds anew.
    player = game.GetPlayer()
    player_set = player.GetContainingSet() if player is not None else None
    keep_names = {warp._WARP_TRANSIT_SET_NAME, "bridge"}
    kept_sets, doomed = [], []
    for name, pSet in list(App.g_kSetManager._sets.items()):
        if name in keep_names or isinstance(pSet, BridgeSet):
            kept_sets.append(pSet)
        else:
            doomed.append((name, pSet))
    player_kept = any(player_set is s for s in kept_sets)

    survivors = _survivor_ids(player)
    # Handlers owned by what is going away. The Mission (and a replaced
    # Episode) is dropped by the loaders; a deleted set's objects go with it.
    gone = {id(old_mission)}
    if old_episode is not None:
        gone.add(id(old_episode))
    for _name, pSet in doomed:
        gone.add(id(pSet))
        gone.update(id(o) for o in pSet._objects.values())

    # MissionLib first, as reset_sdk_globals does (CallWaiting sees the bridge).
    host_loop._reset_missionlib_state()
    for name, pSet in doomed:
        if warp._teardown_hook is not None:
            try:
                warp._teardown_hook(pSet)
            except Exception:
                traceback.print_exc()
        App.g_kSetManager.DeleteSet(name)
        contact_index.forget_set(pSet)
    if player is not None and not player_kept:
        game.SetPlayer(None)

    host_loop._reset_timers(keep=survivors)
    host_loop._reset_action_registry(keep=survivors)
    _drop_event_handlers(gone)
    host_loop._reset_session_scratch()
    host_loop._reset_system_loader_state()
    _drop_waypoints_outside(kept_sets)
    host_loop._reset_sensor_state()
    dev_tutorial_flag.apply_played_tutorial_flag()


def _survivor_ids(player) -> set:
    """ids of the player's playing WarpSequence(s) and every action they
    schedule, recursively through nested sequences (a during-warp cutscene):
    the warp must finish across the change."""
    if player is None:
        return set()
    from engine.core import ids
    from engine.appc.actions import TGSequence
    from engine.appc.warp import WarpSequence
    stack = [o for o in list(ids._registry.values())
             if isinstance(o, WarpSequence) and o.IsPlaying()
             and o.GetShip() is player]
    keep = set()
    while stack:
        action = stack.pop()
        if action is None or id(action) in keep:
            continue
        keep.add(id(action))
        if isinstance(action, TGSequence):
            for step in action._steps:
                stack.append(step.action)
                stack.append(step.dependency)
    return keep


# Method (wrapper) handlers are registered by SDK Conditions and AI objects --
# the old mission's and its ships' -- and by DynamicMusic, which Maelstrom.py
# initializes once per Game. The first two go; the rest stay.
_MISSION_SCOPED_PACKAGES = ("Conditions", "AI")


def _drop_event_handlers(gone: set) -> None:
    """Drop broadcast handlers owned by what the change discards; keep the
    rest. The kept bridge's menus registered theirs once, when the bridge set
    was created (LoadBridge.CreateAndPopulateBridgeSet), and will not again."""
    import App
    em = App.g_kEventManager
    for handlers in em._broadcast_handlers.values():
        handlers[:] = [h for h in handlers
                       if h[0] is None or id(h[0]) not in gone]
    for handlers in em._method_handlers.values():
        handlers[:] = [h for h in handlers if not _mission_scoped(h[0])]


def _mission_scoped(wrapper) -> bool:
    get = getattr(type(wrapper), "GetPyWrapper", None)
    py = get(wrapper) if get is not None else None
    if py is None:
        return True
    package = (type(py).__module__ or "").split(".")[0]
    return package in _MISSION_SCOPED_PACKAGES


def _drop_waypoints_outside(kept_sets) -> None:
    """Placement names repeat across sets; keep only the kept sets' ones."""
    from engine.appc.placement import _waypoint_registry
    kept = {id(s) for s in kept_sets}
    for name, wp in list(_waypoint_registry.items()):
        get = getattr(type(wp), "GetContainingSet", None)
        pSet = get(wp) if get is not None else None
        if pSet is None or id(pSet) not in kept:
            del _waypoint_registry[name]
