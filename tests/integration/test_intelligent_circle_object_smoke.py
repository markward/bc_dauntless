"""Integration smoke for AI.PlainAI.IntelligentCircleObject.

SDK PlainAI/IntelligentCircleObject.py: orbit target with shield-bias
(turn weak shield away) + weapon-arc orientation. Most elaborate of
the 5 PlainAI bodies.

D2 smoke: after one Update call, the orbit-angle computation does
not crash and ship's _speed_setpoint is updated."""
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _build_scene():
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    # ICO reads pShip.GetShields() for shield-bias orientation.
    ours._shield_subsystem = ShieldSubsystem("Shield")
    # Initialize shield levels so the bias logic has data.
    for face in range(ShieldSubsystem.NUM_SHIELDS):
        ours._shield_subsystem._max_shields[face] = 100.0
        ours._shield_subsystem._current_shields[face] = 80.0
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, 200, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")
    return ours, target


def _wire_ico(ours, target_name="Target"):
    plain = PlainAI_Create(ours, "ICO")
    plain.SetScriptModule("IntelligentCircleObject")
    inst = plain.GetScriptInstance()
    inst.SetFollowObjectName(target_name)
    return plain, inst


def test_ico_update_does_not_crash():
    """Activation smoke — Update runs without raising."""
    ours, _target = _build_scene()
    _plain, inst = _wire_ico(ours)
    inst.Update()  # should not raise


def test_ico_update_drives_motion():
    """Update updates either _speed_setpoint or _angular_velocity_setpoint."""
    ours, _target = _build_scene()
    _plain, inst = _wire_ico(ours)
    inst.Update()
    # Either impulse or angular velocity should be touched.
    setpoint_set = (
        ours._speed_setpoint is not None
        or getattr(ours, "_angular_velocity_setpoint", None) is not None
    )
    assert setpoint_set, "expected ICO to set speed or angular setpoint"


def test_ico_update_with_no_target_returns_done():
    ours, _target = _build_scene()
    _plain, inst = _wire_ico(ours, target_name="NoSuchShip")
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_DONE
