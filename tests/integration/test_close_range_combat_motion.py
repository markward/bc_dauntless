"""Live-game-faithful close-range combat: drive GameLoop.tick (AI +
ship_motion + timers) and check that hostile NPCs actually approach
and orient toward each other.

User reported after Slices G + H landed: 'ships dont seem to even
approach each other now. no firing observed between them either.'
The headless diagnostic showed setpoints landing — this test runs
the integrator too, which is what the live game does.
"""
import math

import pytest

import App
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, PhaserSystem, PhaserBank, TorpedoSystem, TorpedoAmmoType,
    PulseWeaponSystem, ImpulseEngineSubsystem, SensorSubsystem,
    ShieldSubsystem,
)
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.core.loop import GameLoop, TICK_DELTA


@pytest.fixture
def game_context():
    mission = Mission()
    mission.SetScript("tests.integration.test_close_range_combat_motion")
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    yield
    _set_current_game(None)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    # Reset timers so each test starts from game_time=0.
    App.g_kTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._time = 0.0


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _make_combatant(pSet, name: str, x: float, y: float, z: float) -> ShipClass:
    s = ShipClass()
    s.SetTranslateXYZ(x, y, z)
    s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    ies = ImpulseEngineSubsystem("IES")
    ies.SetMaxSpeed(120.0)
    # Galaxy-class IES values: max accel ~10 m/s², angular limits modest.
    # Without these, FALLBACK_MAX_ACCEL = 1e9 means the integrator hits
    # setpoint in one tick — fine for unit tests but unrealistic.
    ies.SetMaxAccel(10.0)
    ies.SetMaxAngularVelocity(0.5)
    ies.SetMaxAngularAccel(2.0)
    s._impulse_engine_subsystem = ies
    s._sensor_subsystem = SensorSubsystem("Sensors")

    phaser = PhaserSystem("P"); phaser._parent_ship = s
    bank = PhaserBank("PB0"); bank._parent = phaser
    bank._max_charge = 100.0
    bank._charge_level = 100.0
    bank._min_firing_charge = 10.0
    bank._recharge_rate = 50.0
    bank._normal_discharge_rate = 25.0
    phaser._child_subsystems = [bank]
    s._phaser_system = phaser

    torp = TorpedoSystem("T"); torp._parent_ship = s
    torp._ammo_by_slot = {0: TorpedoAmmoType("Photon", launch_speed=19.0)}
    s._torpedo_system = torp
    s._pulse_weapon_system = PulseWeaponSystem("PW")
    s._pulse_weapon_system._parent_ship = s

    shield = ShieldSubsystem("Shields")
    for face in range(6):
        shield.SetMaxShields(face, 100.0)
        shield.SetCurShields(face, 100.0)
    s._shield_subsystem = shield

    pSet.AddObjectToSet(s, name)
    return s


def _dist(a: ShipClass, b: ShipClass) -> float:
    la = a.GetWorldLocation(); lb = b.GetWorldLocation()
    return math.sqrt((la.x - lb.x) ** 2 + (la.y - lb.y) ** 2 + (la.z - lb.z) ** 2)


def test_two_hostile_ships_close_distance_over_time(game_context):
    """Both ships have NonFedAttack at each other, start 200m apart.
    After driving GameLoop.tick for 5 seconds (300 ticks at 60 Hz),
    they should be closer than they started."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    attacker = _make_combatant(pSet, "Attacker", 0.0, 0.0, 0.0)
    target = _make_combatant(pSet, "Target", 0.0, 200.0, 0.0)

    import AI.Compound.NonFedAttack as non_fed_attack
    attacker.SetAI(non_fed_attack.CreateAI(attacker, "Target"))
    target.SetAI(non_fed_attack.CreateAI(target, "Attacker"))

    start_dist = _dist(attacker, target)
    loop = GameLoop()
    distances = [start_dist]
    for sec in range(1, 11):  # 10 seconds
        loop.advance(60)
        distances.append(_dist(attacker, target))
    print("\nRange-over-time (m): " + ", ".join(f"{d:.1f}" for d in distances))
    print(f"Attacker pos: {attacker.GetWorldLocation().x:.1f}, "
          f"{attacker.GetWorldLocation().y:.1f}, "
          f"{attacker.GetWorldLocation().z:.1f}")
    print(f"Target pos:   {target.GetWorldLocation().x:.1f}, "
          f"{target.GetWorldLocation().y:.1f}, "
          f"{target.GetWorldLocation().z:.1f}")
    print(f"Attacker speed setpoint: {attacker.GetSpeedSetpoint()}")
    print(f"Target   speed setpoint: {target.GetSpeedSetpoint()}")
    print(f"Attacker _current_speed: {attacker._current_speed}")
    print(f"Target   _current_speed: {target._current_speed}")
    # The minimum-observed distance should drop well below the
    # starting distance — that proves the ships actually flew at each
    # other and entered combat range. Post-engagement they may drift
    # apart again as they circle (the IntelligentCircleObject body
    # picked up by CloseRangePriorities), so we can't assert the FINAL
    # distance is smaller — just that they came together at some
    # point during the engagement window.
    min_dist = min(distances)
    assert min_dist < start_dist * 0.6, (
        f"after 10 s of GameLoop.tick the ships should have closed "
        f"significantly at some point; "
        f"start={start_dist:.1f}m  min_observed={min_dist:.1f}m  "
        f"trajectory={distances}"
    )
