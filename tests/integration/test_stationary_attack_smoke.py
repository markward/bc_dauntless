"""Integration smoke for AI.PlainAI.StationaryAttack.

SDK PlainAI/StationaryAttack.py: holds position (SetSpeed(0, ...)),
turns toward target's predicted intercept point.

D2 smoke: after one Update call, ship's _speed_setpoint shows
zero speed and TurnTowardLocation was called toward the target."""
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, TorpedoSystem, TorpedoAmmoType


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _build_scene_with_target(target_distance: float = 200.0):
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    # StationaryAttack reads GetTorpedoSystem().GetCurrentAmmoType().GetLaunchSpeed()
    # for predicted intercept; install ammo with non-zero launch speed.
    ours._torpedo_system = TorpedoSystem("T")
    ours._torpedo_system._ammo_by_slot = {0: TorpedoAmmoType("Photon", launch_speed=19.0)}
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, target_distance, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")
    return ours, target


def _wire_stationary_attack(ours, target_name="Target"):
    plain = PlainAI_Create(ours, "StationaryAttack")
    plain.SetScriptModule("StationaryAttack")
    inst = plain.GetScriptInstance()
    inst.SetTargetObjectName(target_name)
    return plain, inst


def test_stationary_attack_update_holds_position():
    """After Update with target ahead, _speed_setpoint[0] is 0 (no impulse)."""
    ours, _target = _build_scene_with_target()
    _plain, inst = _wire_stationary_attack(ours)
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_ACTIVE
    assert ours._speed_setpoint is not None
    assert ours._speed_setpoint[0] == 0.0, (
        f"StationaryAttack should hold position; speed setpoint was "
        f"{ours._speed_setpoint[0]}"
    )


def test_stationary_attack_update_turns_toward_target():
    """TurnTowardLocation called toward the (predicted) target location."""
    ours, _target = _build_scene_with_target()
    _plain, inst = _wire_stationary_attack(ours)
    calls = []
    ours.TurnTowardLocation = lambda *args, **kwargs: calls.append(args)
    inst.Update()
    assert len(calls) >= 1, "expected TurnTowardLocation to be called"


def test_stationary_attack_update_with_no_target_returns_done():
    ours, _target = _build_scene_with_target()
    _plain, inst = _wire_stationary_attack(ours, target_name="NoSuchShip")
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_DONE
