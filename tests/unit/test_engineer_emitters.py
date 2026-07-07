"""All seven Engineering emitters fire end-to-end against the REAL SDK
Bridge/EngineerCharacterHandlers.py — the regression guard the spec requires.

The five Bridge.*CharacterHandlers (incl. EngineerCharacterHandlers) are REAL
modules in the test path (tests/conftest.py keeps them OUT of the stub list),
so these tests exercise the exact announce/report code the live game runs. The
runtime-vs-test stub divergence (the Helm-silence bug) is precisely what this
capstone guards against.

Fixture: the real GalaxyBridge (LoadBridge.Load builds every station menu and
Brex.ConfigureForShip adds the "Engineer" character to the "bridge" set), a
fully-furnished player ship (sensors / 6 shield faces / hull / power / repair),
and configure_bridge_officers wiring AttachMenuToEngineer's broadcast handlers
and watcher range-checks. Speech is captured at crew_speech.emit — the single
funnel EVERY speak path routes through (CharacterClass.SayLine/SpeakLine AND
CharacterAction AT_SPEAK_LINE), so both the announce SayLine keys and the
Report CharacterAction keys are recorded.

Announce timing: SubsystemDisabled / SubsystemDestroyed / *LevelChange enqueue
a TGSequence whose speaking TGScriptAction is delayed 0.5s; the game clock is
pre-rolled past the handlers' module-global throttles (3.0s) at fixture build,
then _advance() drives the loop past the 0.5s delay so the delayed action
fires. Shield/specific-shield announces bail at GREEN_ALERT, so the ship is
put at RED_ALERT.
"""
import sys

import pytest

import App
import LoadBridge
from engine.appc import crew_speech
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.appc.tg_ui import st_widgets
from engine.appc.windows import TacticalControlWindow
from engine.bridge_officers import configure_bridge_officers
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.core.loop import GameLoop, TICK_RATE
from engine.sdk_ui.widgets.ship_display import (
    _reset_create_count as _reset_ship_display,
)

# EngineerCharacterHandlers module globals throttle the announce paths against
# game time; a value left over from a previous test would block this one, so the
# fixture zeroes them (game clock is then pre-rolled past the 3.0s delays).
_ECH_THROTTLE_GLOBALS = (
    "g_fLastAnnounceHull", "g_fLastAnnounceShields",
    "g_fLastAnnounceSpecificShield", "g_fLastPowerAnnounce",
    "g_fCommunicate", "g_fLastCommunicate",
)


def _advance(seconds=1.0):
    GameLoop().advance(int(seconds * TICK_RATE))


def _prime_game_clock(seconds):
    """Jump the game + realtime clocks forward without running ship updates,
    so the announce handlers' throttle gates (compared against GetGameTime) are
    already satisfied when the test fires an event."""
    App.g_kTimerManager.tick(float(seconds))
    App.g_kRealtimeTimerManager.tick(float(seconds))


@pytest.fixture
def engineer_world(monkeypatch):
    # --- fresh world (mirrors test_bridge_officer_speech._fresh_world) --------
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    st_widgets._reset_module_state()
    _reset_ship_display()
    App.g_kSetManager._sets.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    game = Game()
    episode = Episode()
    mission = Mission()
    episode.SetCurrentMission(mission)
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    for name in list(sys.modules):
        mod = sys.modules[name]
        if name.startswith("Bridge.") and "StubModule" in type(mod).__name__:
            sys.modules.pop(name)

    # --- real SDK bridge + menus ---------------------------------------------
    import Bridge.TacticalMenuHandlers as T
    monkeypatch.setattr(T, "UpdateOrders", lambda *a, **k: None)
    LoadBridge.Load("GalaxyBridge")

    # --- fully-furnished player ship -----------------------------------------
    space = SetClass()
    space.SetName("MainSet")
    App.g_kSetManager.AddSet(space, "MainSet")
    player = ShipClass_Create("Galaxy")

    sensors = player.GetSensorSubsystem()
    sensors.SetMaxCondition(100.0)
    sensors.SetCondition(100.0)

    shields = player.GetShieldSubsystem()
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        shields.SetMaxShields(f, 100.0)
        shields.SetCurrentShields(f, 100.0)

    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(100.0)
    hull.SetCondition(100.0)
    hull._parent_ship = player
    player.SetHull(hull)

    # Repair bay: seed teams + points so RepairSubsystem.Update actually runs
    # (a bare bay has 0 teams / 0 points and no-ops) — the repair-completed
    # emitter needs a real completion to fire ET_REPAIR_COMPLETED.
    from engine.appc.properties import RepairSubsystemProperty
    bay = player.GetRepairSubsystem()
    bay.SetMaxCondition(8000.0)
    rprop = RepairSubsystemProperty("Engineering")
    rprop.SetMaxRepairPoints(50.0)
    rprop.SetNumRepairTeams(3)
    bay.SetProperty(rprop)

    space.AddObjectToSet(player, "player")
    game.SetPlayer(player)

    # --- run the REAL registration (Brex -> AttachMenuToEngineer) -------------
    bridge = App.g_kSetManager.GetSet("bridge")
    results = configure_bridge_officers(bridge, player)
    assert results["Brex"] is None, "Brex.ConfigureForShip failed: %r" % (
        results["Brex"],)
    engineer = App.CharacterClass_GetObject(bridge, "Engineer")
    assert engineer is not None, "no Engineer in the bridge set"
    assert engineer.GetMenu(), "Engineer has no menu"

    # --- capture every spoken line key at the single speech funnel -----------
    spoken = []
    # Return 0.0 duration so chained CharacterAction speak lines (Report emits
    # Hull then Shields sequentially) complete instantly and both fire within a
    # single advance; the announce sequences' own 0.5s TGScriptAction delay is a
    # separate game-time timer, unaffected by this.
    monkeypatch.setattr(
        crew_speech, "emit",
        lambda speaker, db, line, priority, *a, **k: (
            spoken.append(str(line)) or 0.0),
    )

    # --- reset announce throttles + leave GREEN_ALERT ------------------------
    import Bridge.EngineerCharacterHandlers as ECH
    for _g in _ECH_THROTTLE_GLOBALS:
        setattr(ECH, _g, 0.0)
    player.SetAlertLevel(App.ShipClass.RED_ALERT)

    # Pre-roll the clock past the 3.0s announce throttles.
    _prime_game_clock(5.0)

    try:
        yield player, engineer, spoken
    finally:
        App.g_kSetManager._sets.clear()
        _set_current_game(None)


def test_subsystem_disabled_speaks_typed_line(engineer_world):
    ship, engineer, spoken = engineer_world
    sensors = ship.GetSensorSubsystem()
    sensors.SetCondition(sensors.GetMaxCondition() * 0.05)   # <= disabled pct
    _advance(1.0)                                            # 0.5s announce delay
    assert "SensorsDisabled" in spoken, spoken


def test_subsystem_destroyed_speaks_typed_line(engineer_world):
    ship, engineer, spoken = engineer_world
    ship.GetSensorSubsystem().SetCondition(0.0)
    _advance(1.0)
    assert "SensorsDestroyed" in spoken, spoken


def test_shield_level_change_announces(engineer_world):
    ship, engineer, spoken = engineer_world
    shields = ship.GetShieldSubsystem()
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        shields.SetCurrentShields(f, shields.GetMaxShields(f) * 0.4)
    _advance(1.0)
    assert any(k.startswith("Shields") for k in spoken), spoken


def test_specific_shield_face_announces(engineer_world):
    ship, engineer, spoken = engineer_world
    shields = ship.GetShieldSubsystem()
    shields.SetCurrentShields(0, shields.GetMaxShields(0) * 0.04)  # front < 5%
    _advance(1.0)
    assert any("FrontShield" in k for k in spoken), spoken


def test_hull_level_change_announces(engineer_world):
    ship, engineer, spoken = engineer_world
    hull = ship.GetHull()
    hull.SetCondition(hull.GetMaxCondition() * 0.4)
    _advance(1.0)
    assert any(k.startswith("Hull") for k in spoken), spoken


def test_report_speaks_hull_and_shield_status(engineer_world):
    ship, engineer, spoken = engineer_world
    menu = engineer.GetMenu()
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_REPORT)
    evt.SetDestination(menu)
    App.g_kEventManager.AddEvent(evt)
    _advance(0.5)
    assert any(k.startswith("Hull") for k in spoken), spoken
    assert any(k.startswith("Shields") for k in spoken), spoken


def test_communicate_routes_to_report(engineer_world):
    ship, engineer, spoken = engineer_world
    menu = engineer.GetMenu()
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_COMMUNICATE)
    evt.SetDestination(menu)
    App.g_kEventManager.AddEvent(evt)
    _advance(0.5)
    assert spoken, "Communicate neither egged nor re-dispatched to Report"


def test_repair_completed_event_runs_stock_handler_cleanly(engineer_world):
    # Stock RepairCompleted is an early-return stub — assert the event
    # DISPATCHES through the real handler without error (no speech expected).
    ship, engineer, spoken = engineer_world
    import Bridge.EngineerCharacterHandlers as ECH
    sensors = ship.GetSensorSubsystem()
    sensors.SetCondition(sensors.GetMaxCondition() - 1.0)   # enqueue a repair
    before = list(spoken)

    # Integration: driving the repair bay to completion fires ET_REPAIR_COMPLETED
    # through the live broadcast path (RepairSubsystem.Update -> AddEvent).
    ship.GetRepairSubsystem().Update(10.0)
    _advance(0.2)

    # Direct: the real stock handler runs cleanly on a hand-built event.
    menu = engineer.GetMenu()
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_REPAIR_COMPLETED)
    evt.SetSource(sensors)
    evt.SetDestination(ship)
    ECH.RepairCompleted(menu, evt)          # must not raise
    ECH.RepairCannotBeCompleted(menu, evt)  # sibling stub, same machinery

    # Stub handlers speak nothing.
    assert spoken == before, "stock RepairCompleted should be silent: %r" % (
        [k for k in spoken if k not in before],)
    assert sensors.GetCondition() == sensors.GetMaxCondition(), (
        "repair bay did not restore the sensor subsystem")
