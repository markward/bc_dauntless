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
    try:
        calls = []
        original = mod.ShipIdentified

        def _recorder(pObject, pEvent):
            calls.append(pEvent.GetDestination())
            return original(pObject, pEvent)

        mod.ShipIdentified = _recorder

        sensor_mission_guards.install()

        other = ShipClass_Create("FedOutpost")
        other.SetName("NotOutpost")

        _post_ship_identified(other)
        _post_ship_identified(other)

        assert len(calls) == 2
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
