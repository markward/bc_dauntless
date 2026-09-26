# tests/unit/test_mission_change.py
"""Mission change with carry-over (spec §2)."""
import sys
import App
from engine.core import mission_change
from engine.appc.sets import SetClass_Create
from tests.helpers.mission_change_fixtures import (
    log, _install, _world, _forget_world)


def teardown_function(_):
    _forget_world()


def test_episode_module_for():
    f = mission_change.episode_module_for
    assert f("Maelstrom.Episode7.E7M1.E7M1") == "Maelstrom.Episode7.Episode7"
    assert f("QuickBattle.QuickBattle") is None


def test_change_terminates_clears_and_loads_carrying_the_player():
    game, player, bridge = _world()
    _install("_t.Old", Terminate=lambda m: log.append("Old.Terminate"))
    def _init(m):
        log.append("New.Initialize")
        s = SetClass_Create(); App.g_kSetManager.AddSet(s, "Starbase12")
    _install("_t.New", Initialize=_init)
    assert mission_change.change(mission="_t.New") is True
    assert log == ["Old.Terminate", "New.Initialize"]
    assert App.g_kSetManager.GetSet("Beol4") is None
    assert App.g_kSetManager.GetSet("bridge") is bridge
    assert App.g_kSetManager.GetSet("warp").GetObject("player") is player
    assert App.Game_GetCurrentGame() is game and game.GetPlayer() is player
    assert App.g_kSetManager.GetSet("Starbase12") is not None
    cur = game.GetCurrentEpisode().GetCurrentMission()
    assert cur._module_name == "_t.New"


def test_same_mission_is_not_a_change():
    _world()
    assert mission_change.change(mission="_t.Old") is False


def test_a_failing_next_mission_leaves_the_player_parked():
    """Review Focus 2."""
    game, player, _ = _world()
    _install("_t.Old", Terminate=lambda m: None)
    def _boom(m): raise RuntimeError("bad mission")
    _install("_t.New", Initialize=_boom)
    assert mission_change.change(mission="_t.New") is False
    assert App.g_kSetManager.GetSet("warp").GetObject("player") is player
    assert not mission_change.in_progress()


def test_a_failing_clear_leaves_the_player_parked(monkeypatch):
    """Review Focus 2: the clear raising must not escape into the warp and
    stall the tunnel -- the change reports failure instead."""
    from engine import host_loop
    game, player, _ = _world()
    _install("_t.Old", Terminate=lambda m: None)
    _install("_t.New", Initialize=lambda m: log.append("New.Initialize"))
    def _boom(): raise RuntimeError("bad clear")
    monkeypatch.setattr(host_loop, "_reset_sensor_state", _boom)
    assert mission_change.change(mission="_t.New") is False
    assert App.g_kSetManager.GetSet("warp").GetObject("player") is player
    assert not mission_change.in_progress()
    assert log == []


def test_a_change_inside_a_change_is_refused():
    _world()
    _install("_t.Old", Terminate=lambda m: None)
    def _init(m):
        log.append(mission_change.change(mission="_t.Other"))
    _install("_t.New", Initialize=_init)
    mission_change.change(mission="_t.New")
    assert log == [False]


# ── Episode change ───────────────────────────────────────────────────────────

def test_episode_change_terminates_both_and_loads_through_the_episode():
    game, player, _ = _world()
    old_ep = game.GetCurrentEpisode()
    _install("_t.Old", Terminate=lambda m: log.append("Old.Terminate"))
    _install("_t.EpOld", Terminate=lambda e: log.append("EpOld.Terminate"))
    _install("_t.New", Initialize=lambda m: log.append("New.Initialize"))
    def _ep_init(e):
        log.append("EpNew.Initialize")
        e.LoadMission("_t.New")
    _install("_t.EpNew", Initialize=_ep_init)
    assert mission_change.change(episode="_t.EpNew") is True
    assert log == ["Old.Terminate", "EpOld.Terminate",
                   "EpNew.Initialize", "New.Initialize"]
    ep = game.GetCurrentEpisode()
    assert ep is not old_ep and ep._module_name == "_t.EpNew"
    assert ep.GetCurrentMission()._module_name == "_t.New"
    assert game.GetPlayer() is player


def test_a_mission_change_posts_mission_start_at_the_episode():
    game, _, _ = _world()
    _install("_t.Old", Terminate=lambda m: None)
    _install("_t.New", Initialize=lambda m: None)
    seen = []
    _install("_t.Probe", Seen=lambda d, e: seen.append(e.GetDestination()))
    # Owned by the Game, which the change keeps.
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_MISSION_START, game, "_t.Probe.Seen")
    try:
        assert mission_change.change(mission="_t.New") is True
    finally:
        sys.modules.pop("_t.Probe", None)
    assert seen == [game.GetCurrentEpisode()]


def test_init_mission_records_mission_and_episode_module_names():
    from engine.host_loop import _init_mission
    name = "_tfam.Episode9.E9M1.E9M1"
    _install(name, Initialize=lambda m: None)
    try:
        mission, episode, _game, _mod = _init_mission(name)
    finally:
        sys.modules.pop(name, None)
    assert mission._module_name == name
    assert episode._module_name == "_tfam.Episode9.Episode9"


# ── Keep rows ────────────────────────────────────────────────────────────────

def test_timers_of_the_playing_warp_sequence_survive_and_others_do_not():
    from engine.appc.warp import WarpSequence
    from engine.appc.actions import (
        TGAction, TGSequence, TGAction_CreateNull, _deferred_playing)
    from engine.appc.events import TGEvent
    game, player, _ = _world()
    _install("_t.Old", Terminate=lambda m: None)
    _install("_t.New", Initialize=lambda m: None)

    class _Deferred(TGAction):
        def Play(self):
            self._playing = True
            self._complete_after(3.0, mgr=App.g_kTimerManager)

    seq = WarpSequence(player, "", 0.0, "Player Start")
    late = TGAction_CreateNull()
    seq.AddAction(late, 5.0)                 # a pending step timer (dest: seq)
    cutscene = TGSequence()                  # a queued action it is playing
    leaf = _Deferred()
    cutscene.AddAction(leaf)
    seq.AddAction(cutscene)
    seq.Play()

    stranger = TGAction()
    stranger._complete_after(2.0, mgr=App.g_kTimerManager)
    free = App.TGTimer_Create()
    free.SetTimerStart(App.g_kTimerManager.get_time() + 1.0)
    ev = TGEvent(); ev.SetEventType(App.ET_MISSION_START)
    free.SetEvent(ev)
    App.g_kTimerManager.AddTimer(free)

    assert mission_change.change(mission="_t.New") is True

    kept = {t.GetEvent().GetDestination()
            for t in App.g_kTimerManager._timers.values()}
    assert seq in kept and leaf in kept
    assert stranger not in kept
    assert free.GetObjID() not in App.g_kTimerManager._timers
    assert leaf in _deferred_playing and stranger not in _deferred_playing

    App.g_kTimerManager.tick(6.0)            # the warp still finishes
    assert not seq.IsPlaying()


def test_the_game_clock_is_kept():
    _world()
    _install("_t.Old", Terminate=lambda m: None)
    _install("_t.New", Initialize=lambda m: None)
    App.g_kTimerManager.tick(42.0)
    before = App.g_kTimerManager.get_time()
    assert mission_change.change(mission="_t.New") is True
    assert App.g_kTimerManager.get_time() == before


def test_old_mission_handlers_go_and_kept_world_handlers_stay():
    """The bridge's menus register broadcast handlers once, when the bridge
    set is created (LoadBridge.CreateAndPopulateBridgeSet); DynamicMusic's
    are Game-level. Both survive; the old mission's go."""
    from engine.appc.events import TGEventHandlerObject, TGPythonInstanceWrapper
    from engine.appc.input import register_input_handlers
    game, _, _ = _world()
    mis = game.GetCurrentEpisode().GetCurrentMission()
    _install("_t.Old", Terminate=lambda m: None, H=lambda d, e: None)
    _install("_t.New", Initialize=lambda m: None)
    em = App.g_kEventManager
    menu = TGEventHandlerObject()           # stands in for pHelmMenu
    em.AddBroadcastPythonFuncHandler(App.ET_ENTERED_SET, mis, "_t.Old.H")
    em.AddBroadcastPythonFuncHandler(App.ET_ENTERED_SET, menu, "_t.Old.H")
    register_input_handlers(em)
    n_input = sum(1 for lst in em._broadcast_handlers.values()
                  for _d, q, _t in lst
                  if q == "engine.appc.input._OnKeyboardEvent_Dispatch")

    class _Cond: pass
    _Cond.__module__ = "Conditions._TCond"
    class _Music: pass
    _Music.__module__ = "DynamicMusic"
    w_cond = TGPythonInstanceWrapper(); w_cond.SetPyWrapper(_Cond())
    w_music = TGPythonInstanceWrapper(); w_music.SetPyWrapper(_Music())
    em.AddBroadcastPythonMethodHandler(App.ET_ENTERED_SET, w_cond, "X")
    em.AddBroadcastPythonMethodHandler(App.ET_MISSION_START, w_music, "NewMission")

    assert mission_change.change(mission="_t.New") is True

    func_dests = [d for lst in em._broadcast_handlers.values() for d, _q, _t in lst]
    assert mis not in func_dests
    assert any(d is menu for d in func_dests)
    assert sum(1 for lst in em._broadcast_handlers.values()
               for _d, q, _t in lst
               if q == "engine.appc.input._OnKeyboardEvent_Dispatch") == n_input
    wrappers = [w for lst in em._method_handlers.values() for w, _m, _t in lst]
    assert w_music in wrappers and w_cond not in wrappers


def test_the_kept_bridge_keeps_its_tactical_window_and_menus():
    """LoadBridge.Load returns early for a bridge set that already exists with
    the same config, and CreateCharacterMenus runs only when the set is first
    created -- so the menus must not be reset under a kept bridge."""
    from engine.appc.windows import TacticalControlWindow
    from engine.appc.tg_ui import st_widgets
    _world()
    _install("_t.Old", Terminate=lambda m: None)
    _install("_t.New", Initialize=lambda m: None)
    tcw = TacticalControlWindow.GetInstance()
    button = object()
    st_widgets.SortedRegionMenu_SetWarpButton(button)
    assert mission_change.change(mission="_t.New") is True
    assert TacticalControlWindow.GetInstance() is tcw
    assert st_widgets.SortedRegionMenu_GetWarpButton() is button


def test_kept_sets_keep_their_contacts_and_waypoints():
    from engine.appc import contact_index
    from engine.appc.placement import Waypoint_Create, _waypoint_registry
    game, player, _ = _world()
    _install("_t.Old", Terminate=lambda m: None)
    _install("_t.New", Initialize=lambda m: None)
    kept_wp = Waypoint_Create("Warp Point", "warp")
    Waypoint_Create("Beol Point", "Beol4")
    warp_set = App.g_kSetManager.GetSet("warp")
    assert player in contact_index.ships_in(warp_set)
    assert mission_change.change(mission="_t.New") is True
    assert player in contact_index.ships_in(warp_set)
    assert _waypoint_registry.get("Warp Point") is kept_wp
    assert "Beol Point" not in _waypoint_registry


def test_teardown_hook_runs_for_each_deleted_set_only():
    from engine.appc import warp
    game, _, bridge = _world()
    beol = App.g_kSetManager.GetSet("Beol4")
    _install("_t.Old", Terminate=lambda m: None)
    _install("_t.New", Initialize=lambda m: None)
    torn = []
    saved = warp._teardown_hook
    warp._teardown_hook = torn.append
    try:
        assert mission_change.change(mission="_t.New") is True
    finally:
        warp._teardown_hook = saved
    assert torn == [beol]


def test_on_changed_runs_after_a_successful_change_only():
    _world()
    calls = []
    mission_change.configure(on_changed=lambda: calls.append(1))
    try:
        _install("_t.Old", Terminate=lambda m: None)
        def _boom(m): raise RuntimeError("bad")
        _install("_t.New", Initialize=_boom)
        assert mission_change.change(mission="_t.New") is False
        assert calls == []
        _world()
        _install("_t.New", Initialize=lambda m: None)
        assert mission_change.change(mission="_t.New") is True
        assert calls == [1]
    finally:
        mission_change.configure(on_changed=None)


def test_a_direct_load_deletes_the_players_region_and_the_player():
    """R9: only the bridge and "warp" sets are kept. A direct load (no warp,
    e.g. E2M6's StartEpisode3) finds the player in a region; the region goes
    with the player in it, and the next mission's CreatePlayerShip builds a
    new one because Game.GetPlayer() is None by then."""
    game, player, bridge = _world()
    warp_set = App.g_kSetManager.GetSet("warp")
    warp_set.RemoveObjectFromSet("player")
    beol = App.g_kSetManager.GetSet("Beol4")
    beol.AddObjectToSet(player, "player")
    _install("_t.Old", Terminate=lambda m: None)
    _install("_t.New", Initialize=lambda m: log.append(game.GetPlayer()))
    assert mission_change.change(mission="_t.New") is True
    assert log == [None]
    assert App.g_kSetManager.GetSet("Beol4") is None
    assert App.g_kSetManager.GetSet("bridge") is bridge
    assert App.g_kSetManager.GetSet("warp") is warp_set


def test_an_episode_change_starts_the_campaign_music_the_dev_loader_skipped(
        monkeypatch):
    """Every Maelstrom Episode*.Initialize calls DynamicMusic.ChangeMusic,
    which reads the module globals DynamicMusic.Initialize sets -- run once by
    the campaign's SetupMusic (Maelstrom.py:109) at campaign boot. The dev
    loader never runs the campaign Initialize, so warping from a dev-loaded
    E6M5 into Episode 7 died with NameError: pStateMachine. The change runs
    the campaign's SetupMusic first when DynamicMusic was never started."""
    import DynamicMusic
    monkeypatch.setattr(DynamicMusic, "g_bInitialized", 0)
    game, _, _ = _world()
    _install("_t.Old", Terminate=lambda m: None)
    _install("_t._t", SetupMusic=lambda g: log.append(("SetupMusic", g)))
    _install("_t.EpNew", Initialize=lambda e: log.append("EpNew.Initialize"))
    try:
        assert mission_change.change(episode="_t.EpNew") is True
    finally:
        sys.modules.pop("_t._t", None)
    assert log == [("SetupMusic", game), "EpNew.Initialize"]


def test_an_episode_change_leaves_running_campaign_music_alone(monkeypatch):
    import DynamicMusic
    monkeypatch.setattr(DynamicMusic, "g_bInitialized", 1)
    _world()
    _install("_t.Old", Terminate=lambda m: None)
    _install("_t._t", SetupMusic=lambda g: log.append("SetupMusic"))
    _install("_t.EpNew", Initialize=lambda e: log.append("EpNew.Initialize"))
    try:
        assert mission_change.change(episode="_t.EpNew") is True
    finally:
        sys.modules.pop("_t._t", None)
    assert log == ["EpNew.Initialize"]
