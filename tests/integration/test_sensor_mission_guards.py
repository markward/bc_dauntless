"""Guards against re-identification (sensor continuity spec, Guards): sub-
project 2 lets a ship be identified more than once (lost track -> found
again), which two stock SDK handlers were never written to expect.

E5M2's `ShipIdentified` replays Outpost dialogue and re-adds a mission goal
on EVERY Outpost identification; only the first one should run the mission
body. Helm's `AddHailButton` runs 1 s after identification (queued via a
TGSequence/TGScriptAction) and never re-checks the player's known set --
`engine.appc.sensor_mission_guards` re-checks it at the moment the button is
actually about to be built.
"""
import sys

import pytest

import App
import MissionLib
from engine import host_loop
from engine.appc import sensor_mission_guards
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.appc.windows import TacticalControlWindow
from engine.core import mission_change
from engine.core.game import Game, Episode, Mission, _set_current_game
from tests.integration.test_sdk_bridge_load import _fresh_world


# ───────────────────────── E5M2 Outpost re-identification ─────────────────


def _init_e5m2():
    _fresh_world()
    try:
        mission, episode, game, mod = host_loop._init_mission(
            "Maelstrom.Episode5.E5M2.E5M2")
    except Exception:
        pytest.skip("E5M2 could not be loaded headless (BC game data absent)")
    return mission, episode, game, mod


def _post_ship_identified(dest_obj):
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_SENSORS_SHIP_IDENTIFIED)
    evt.SetDestination(dest_obj)
    App.g_kEventManager.AddEvent(evt)


def test_e5m2_outpost_reidentification_replays_nothing():
    mission, episode, game, mod = _init_e5m2()
    try:
        sensor_mission_guards.install()
        mod.g_bBaseDetected = 1

        outpost = mod.pOutpost
        assert outpost is not None
        assert outpost.GetName() == "Outpost"

        goal_calls = []
        orig_add_goal = MissionLib.AddGoal

        def _record_add_goal(*args):
            goal_calls.append(args)
            return orig_add_goal(*args)

        MissionLib.AddGoal = _record_add_goal

        sequence_calls = []
        orig_queue_sequence = mod.QueueSequence

        def _record_queue_sequence(pSequence):
            sequence_calls.append(pSequence)
            return orig_queue_sequence(pSequence)

        mod.QueueSequence = _record_queue_sequence

        try:
            _post_ship_identified(outpost)
            _post_ship_identified(outpost)
        finally:
            MissionLib.AddGoal = orig_add_goal
            mod.QueueSequence = orig_queue_sequence

        assert goal_calls.count(("E5ScanOutpostGoal",)) == 1
        assert len(sequence_calls) <= 1
    finally:
        App.g_kSetManager._sets.clear()
        _set_current_game(None)
        sensor_mission_guards.reset()


def test_e5m2_other_ships_pass_through():
    mission, episode, game, mod = _init_e5m2()
    # _init_e5m2() already ran install() (via host_loop._init_mission ->
    # sensor_mission_guards.install_after_import), so `original` below is
    # ALREADY the guarded ShipIdentified, not the raw SDK function -- fine,
    # this test only cares that non-Outpost identifications reach whatever
    # is beneath the guard, every time.
    #
    # `mod.ShipIdentified` MUST be restored in `finally`, not left pointing
    # at `_recorder`: `_recorder` carries no `_sensor_guarded` marker, and
    # ANY later test's install()/install_after_import() call (there always
    # is one -- every mission (re)load runs it) sees "unguarded" and wraps
    # `_recorder` in a FRESH _wrap_e5m2 layer. That nests two layers sharing
    # one module-level `_outpost_seen` latch: the outer layer sets the latch
    # before the inner (test1's original) layer's own check ever runs, so
    # the inner layer always sees the latch already tripped and never calls
    # down to the real orig/AddGoal -- permanently, for every later test in
    # this file that posts an Outpost identification. This was a REAL bug
    # (Task 5 review fix round): it silently zeroed the goal-add count in
    # both of the production-mission-change tests below, which run later in
    # this file and therefore inherited the unrestored `_recorder`.
    original = mod.ShipIdentified
    try:
        calls = []

        def _recorder(pObject, pEvent):
            calls.append(pEvent.GetDestination())
            return original(pObject, pEvent)

        mod.ShipIdentified = _recorder

        other = ShipClass_Create("FedOutpost")
        other.SetName("NotOutpost")

        _post_ship_identified(other)
        _post_ship_identified(other)

        assert len(calls) == 2
    finally:
        mod.ShipIdentified = original
        App.g_kSetManager._sets.clear()
        _set_current_game(None)
        sensor_mission_guards.reset()


# ──────────── E5M2 guard via the PRODUCTION mission-change path ───────────


def _count_outpost_goal_adds(outpost, n_events):
    """Post ET_SENSORS_SHIP_IDENTIFIED(outpost) *n_events* times, recording
    every MissionLib.AddGoal("E5ScanOutpostGoal") call. Restores AddGoal
    unconditionally."""
    goal_calls = []
    orig_add_goal = MissionLib.AddGoal

    def _record(*args):
        goal_calls.append(args)
        return orig_add_goal(*args)

    MissionLib.AddGoal = _record
    try:
        for _ in range(n_events):
            _post_ship_identified(outpost)
    finally:
        MissionLib.AddGoal = orig_add_goal
    return goal_calls.count(("E5ScanOutpostGoal",))


def test_e5m2_guard_installed_and_reidentification_replays_nothing_via_production_mission_change():
    """Reaches E5M2 through the REAL campaign path -- Episode.LoadMission /
    engine.core.mission_change.change() while a mission runs -- not the dev
    loader (host_loop._init_mission). Regression this guards (Task 5 review,
    finding 1): engine.core.game.Episode._load_mission_raw never called
    sensor_mission_guards.install() after its own import, so E5M2's
    ShipIdentified was never wrapped on this path even though the dev-loader
    path was already fixed -- the guard was dead in normal (non-dev-loader)
    play."""
    _fresh_world()
    try:
        mission, episode, game, mod = host_loop._init_mission(
            "Maelstrom.Episode1.E1M2.E1M2")
    except Exception:
        pytest.skip("E1M2 could not be loaded headless (BC game data absent)")
    try:
        ok = mission_change.change(mission="Maelstrom.Episode5.E5M2.E5M2")
        if not ok:
            pytest.skip(
                "mission_change.change() to E5M2 refused/failed headless")

        e5m2 = sys.modules.get("Maelstrom.Episode5.E5M2.E5M2")
        assert e5m2 is not None
        # The guard marker, not just "no crash" -- proves install() actually
        # ran on THIS module object, through THIS path.
        assert getattr(e5m2.ShipIdentified, "_sensor_guarded", False) is True

        e5m2.g_bBaseDetected = 1
        outpost = e5m2.pOutpost
        assert outpost is not None and outpost.GetName() == "Outpost"

        assert _count_outpost_goal_adds(outpost, 2) == 1
    finally:
        App.g_kSetManager._sets.clear()
        _set_current_game(None)
        sensor_mission_guards.reset()


def test_e5m2_outpost_latch_resets_on_replay_through_production_mission_change():
    """The Outpost first-identification latch must go stale when LEAVING
    E5M2 through the production path too, exactly as it does through the
    dev loader: mission_change._clear_for_next_mission calls
    host_loop._reset_sensor_state() -- the SAME function the dev-loader path
    goes through -- which resets sensor_mission_guards' latch. Without
    this, a player replaying a campaign mission would find its Outpost
    permanently guarded after the first playthrough: ShipIdentified's
    goal-add body would never run again on any later playthrough's first
    identification.

    Does not drive a literal second E5M2.Initialize() in the same process:
    E5M2's own opening cutscene (E5Intro) calls
    Actions.CameraScriptActions.CutsceneCameraBegin("CutsceneCam", "bridge"),
    whose own per-set "already began" registry is SDK module state that
    nothing in the mission-change reset table clears -- and "bridge" is one
    of the two set names mission_change deliberately KEEPS across a change
    (spec §2). Re-entering E5M2 a second time within one process trips that
    unrelated registry's own KeyError guard, independent of anything this
    task touches. The claim under test here is narrower and still exactly
    what matters for this guard: the latch goes stale the moment the
    mission-change machinery clears mission state, which happens on every
    departure from E5M2 regardless of what the NEXT mission is or whether
    re-entering this exact one would hit that unrelated issue."""
    _fresh_world()
    try:
        mission, episode, game, mod = host_loop._init_mission(
            "Maelstrom.Episode1.E1M2.E1M2")
    except Exception:
        pytest.skip("E1M2 could not be loaded headless (BC game data absent)")
    try:
        ok = mission_change.change(mission="Maelstrom.Episode5.E5M2.E5M2")
        if not ok:
            pytest.skip(
                "mission_change.change() to E5M2 refused/failed headless")
        e5m2 = sys.modules["Maelstrom.Episode5.E5M2.E5M2"]
        e5m2.g_bBaseDetected = 1
        assert _count_outpost_goal_adds(e5m2.pOutpost, 1) == 1
        assert sensor_mission_guards._outpost_seen is True

        # Leave E5M2 -- the production path's own mission-change machinery
        # runs (the same host_loop._reset_sensor_state the dev loader uses).
        ok2 = mission_change.change(mission="Maelstrom.Episode1.E1M2.E1M2")
        assert ok2, "mission_change.change() back to E1M2 failed"

        assert sensor_mission_guards._outpost_seen is False
    finally:
        App.g_kSetManager._sets.clear()
        _set_current_game(None)
        sensor_mission_guards.reset()


# ───────────────────────── Helm's delayed AddHailButton ────────────────────


def _fresh_real_helm():
    saved = sys.modules.pop("Bridge.HelmMenuHandlers", None)
    saved_bare = sys.modules.pop("HelmMenuHandlers", None)
    import Bridge.HelmMenuHandlers as real
    return real, saved, saved_bare


def _restore_helm(saved, saved_bare):
    if saved is not None:
        sys.modules["Bridge.HelmMenuHandlers"] = saved
    if saved_bare is not None:
        sys.modules["HelmMenuHandlers"] = saved_bare


def _setup_helm_and_target():
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()

    game = Game()
    episode = Episode()
    mission = Mission()
    episode.SetCurrentMission(mission)
    game.SetCurrentEpisode(episode)
    _set_current_game(game)

    real, saved, saved_bare = _fresh_real_helm()
    real.CreateMenus()

    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    player.SetSensorSubsystem(sensors)
    game.SetPlayer(player)

    target = ShipClass_Create("FedOutpost")
    target.SetName("Contact")
    target.SetDisplayName("Contact")
    assert target.IsHailable() == 1
    sensors.AddKnownObject(target)

    return real, saved, saved_bare, sensors, target


def test_delayed_hail_button_skipped_after_lost_track():
    real, saved, saved_bare, sensors, target = _setup_helm_and_target()
    try:
        sensor_mission_guards.install()
        sensors.RemoveKnownObject(target)

        result = real.AddHailButton(None, target.GetObjID())

        pHailMenu = MissionLib.GetCharacterSubmenu("Helm", "Hail")
        assert pHailMenu.GetButtonW(target.GetDisplayName()) is None
        assert result == 0
    finally:
        _restore_helm(saved, saved_bare)
        _set_current_game(None)


def test_delayed_hail_button_added_when_still_known():
    real, saved, saved_bare, sensors, target = _setup_helm_and_target()
    try:
        sensor_mission_guards.install()
        # target is still in sensors._known_objects -- never removed.

        real.AddHailButton(None, target.GetObjID())

        pHailMenu = MissionLib.GetCharacterSubmenu("Helm", "Hail")
        assert pHailMenu.GetButtonW(target.GetDisplayName()) is not None
    finally:
        _restore_helm(saved, saved_bare)
        _set_current_game(None)
