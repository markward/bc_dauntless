"""Integration smoke for AI.PlainAI.TorpedoRun.

SDK PlainAI/TorpedoRun.py: makes a single full-speed torpedo run on
its target. Update() computes target intercept point (predicted via
torpedo launch speed), uses fuzzy logic on distance + facing to pick
speed, calls SetImpulse + TurnDirectionsToDirections.

D2 smoke: after one Update call, ship's _speed_setpoint shows
non-zero impulse and the ship is rotating (angular velocity set)."""
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem, TorpedoAmmoType, TorpedoSystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _build_scene_with_distant_target(distance: float = 300.0):
    """Build ours at origin facing +Y, target at (0, distance, 0)."""
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    # TorpedoRun reads pShip.GetTorpedoSystem() for launch-speed prediction.
    # Install a real TorpedoAmmoType so GetCurrentAmmoType().GetLaunchSpeed()
    # returns non-zero (default photon launch speed ~19).
    ours._torpedo_system = TorpedoSystem("T")
    ours._torpedo_system._ammo_by_slot = {
        0: TorpedoAmmoType("Photon", launch_speed=19.0),
    }
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, distance, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")
    return ours, target


def _wire_torpedo_run(ours, target_name="Target"):
    """Instantiate the SDK TorpedoRun PlainAI."""
    plain = PlainAI_Create(ours, "TorpRun")
    plain.SetScriptModule("TorpedoRun")
    inst = plain.GetScriptInstance()
    inst.SetTargetObjectName(target_name)
    return plain, inst


def test_torpedo_run_update_drives_impulse():
    """At fIdealDistance (200) with target ahead, Update should produce a
    non-zero impulse setpoint (ship moves forward)."""
    ours, _target = _build_scene_with_distant_target(distance=300.0)
    _plain, inst = _wire_torpedo_run(ours)
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_ACTIVE
    # _speed_setpoint is (speed, direction, frame) per ships.py:86-95.
    assert ours._speed_setpoint is not None
    assert ours._speed_setpoint[0] > 0.0, "expected non-zero forward impulse"


def test_torpedo_run_update_with_no_target_returns_done():
    """sTarget resolves to None -> US_DONE."""
    ours, _target = _build_scene_with_distant_target()
    _plain, inst = _wire_torpedo_run(ours, target_name="NoSuchShip")
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_DONE


def test_torpedo_run_reaches_turn_directions_for_heading_adjust():
    """AdjustHeading calls pShip.TurnDirectionsToDirections - verify it
    was reached by capturing the call."""
    ours, _target = _build_scene_with_distant_target(distance=300.0)
    _plain, inst = _wire_torpedo_run(ours)
    calls = []
    ours.TurnDirectionsToDirections = lambda *args, **kwargs: calls.append(args)
    inst.Update()
    assert len(calls) >= 1, "expected TurnDirectionsToDirections to be called"
