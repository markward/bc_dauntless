"""NonFedAttack end-to-end smoke. With Slice D2 in place, the
combat subtree drives observable ship behaviour across multiple ticks
(speed setpoints, weapon dispatch). Pre-D2 this was xfail-marked but
xpassing (activation only); now it's a clean pass with multi-tick
kinematic assertions."""
import pytest

import App
from engine.appc.ai import BuilderAI
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, PhaserSystem, TorpedoSystem, TorpedoAmmoType,
    ImpulseEngineSubsystem, SensorSubsystem,
)
from engine.core.game import Game, Episode, Mission, _set_current_game


@pytest.fixture
def game_context():
    """Mission stack with a non-empty script for sMissionModuleName."""
    mission = Mission()
    mission.SetScript("tests.integration.test_non_fed_attack_smoke")
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


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def test_non_fed_attack_create_ai_smoke(game_context):
    """With Slice D2's PlainAI body ports landed, NonFedAttack's full tree
    activates and drives observable ship behaviour across multiple ticks.

    Pre-D2 this was xfail-marked but xpassing (activation only). Now
    asserts kinematic behaviour over 10 ticks."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    # PlainAI bodies (Intercept, TorpedoRun) need impulse-engine + ammo.
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    # ConditionSystemDisabled.CheckRootState defaults bState=1 when its
    # watchlist is empty (no matching subsystem on the ship), so without
    # a SensorSubsystem the NoSensorsEvasive branch latches ACTIVE and
    # starves the SelectTarget combat subtree.
    ours._sensor_subsystem = SensorSubsystem("Sensors")
    ours._phaser = PhaserSystem("P"); ours._phaser._parent_ship = ours
    ours._torpedo_system = TorpedoSystem("T"); ours._torpedo_system._parent_ship = ours
    ours._torpedo_system._ammo_by_slot = {0: TorpedoAmmoType("Photon", launch_speed=19.0)}
    pSet.AddObjectToSet(ours, "Attacker")
    target = ShipClass(); target.SetTranslateXYZ(0, 500, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")

    import AI.Compound.NonFedAttack as non_fed_attack
    builder = non_fed_attack.CreateAI(ours, "Target")
    assert isinstance(builder, BuilderAI)

    # First tick activates the BuilderAI.
    tick_ai(builder, game_time=0.01)
    assert builder._activated is True, (
        f"BuilderAI activation failed: {builder._activation_error}"
    )
    assert builder._activation_failed is False

    # 10 more ticks — by now some PlainAI body should have written a
    # speed setpoint (the ship is engaging).
    for i in range(1, 11):
        tick_ai(builder, game_time=0.01 + i * 0.25)

    assert ours._speed_setpoint is not None, (
        "after 10 ticks, NonFedAttack should have written a speed setpoint"
    )
