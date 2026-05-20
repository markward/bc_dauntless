"""FedAttack end-to-end smoke. Federation-ship sibling of NonFedAttack;
the BasicAttack dispatcher (sdk/.../AI/Compound/BasicAttack.py:42-44)
routes Federation ships through FedAttack and everyone else through
NonFedAttack. With Slice D2's PlainAI body ports in place, the combat
subtree drives observable ship behaviour across multiple ticks."""
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
    mission.SetScript("tests.integration.test_fed_attack_smoke")
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


def test_fed_attack_create_ai_drives_combat(game_context):
    """FedAttack's tree activates and writes a speed setpoint within
    10 ticks. Mirrors the NonFedAttack smoke fixture from Slice D2."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    # PlainAI bodies (Intercept, TorpedoRun) need impulse-engine + ammo.
    ours._impulse_engine_subsystem = ImpulseEngineSubsystem("IES")
    ours._impulse_engine_subsystem.SetMaxSpeed(120.0)
    # ConditionSystemDisabled.CheckRootState defaults bState=1 with an
    # empty watchlist — give the ship a sensor subsystem so the
    # NoSensorsEvasive branch doesn't latch ACTIVE.
    ours._sensor_subsystem = SensorSubsystem("Sensors")
    ours._phaser = PhaserSystem("P"); ours._phaser._parent_ship = ours
    ours._torpedo_system = TorpedoSystem("T"); ours._torpedo_system._parent_ship = ours
    ours._torpedo_system._ammo_by_slot = {0: TorpedoAmmoType("Photon", launch_speed=19.0)}
    pSet.AddObjectToSet(ours, "Attacker")
    target = ShipClass(); target.SetTranslateXYZ(0, 500, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")

    import AI.Compound.FedAttack as fed_attack
    builder = fed_attack.CreateAI(ours, "Target")
    assert isinstance(builder, BuilderAI)

    tick_ai(builder, game_time=0.01)
    assert builder._activated is True, (
        f"BuilderAI activation failed: {builder._activation_error}"
    )
    assert builder._activation_failed is False

    for i in range(1, 11):
        tick_ai(builder, game_time=0.01 + i * 0.25)

    assert ours._speed_setpoint is not None, (
        "after 10 ticks, FedAttack should have written a speed setpoint"
    )
