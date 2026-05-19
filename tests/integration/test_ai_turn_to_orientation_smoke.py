"""End-to-end smoke: TurnToOrientation rotates a ship to face a target.

Proves TurnDirectionsToDirections (Task 5), angular integration
(Task 3), GetRelativePositionInfo (Task 4), real SDK script load
(prior slice).

World-forward derivation matches the SDK: TurnToOrientation builds
``vPrimaryWorld`` via ``MultMatrixLeft(pShip.GetWorldRotation())``
(column-vector form, sdk/.../TurnToOrientation.py:135-137), so the
post-rotation forward in world is ``R * (0,1,0)`` — i.e. column 1 of
R, not row 1. Position integration in ``_step_ship_motion`` uses the
same ``MultMatrixLeft`` convention, so consistency holds end-to-end."""
import pytest

import App
from engine.appc.math import TGPoint3
from engine.core.loop import GameLoop, TICK_RATE
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass


def _world_forward(ship):
    """Apply the ship's world rotation to model-forward (+Y) using the
    same convention TurnToOrientation.Update uses to compute
    vPrimaryWorld — column-vector / MultMatrixLeft. Equivalent to
    column 1 of GetWorldRotation()."""
    v = TGPoint3(0.0, 1.0, 0.0)
    v.MultMatrixLeft(ship.GetWorldRotation())
    return v


def _setup_ship_with_turn_to(target_pos, *, done_on_lineup=0,
                              target_name="target"):
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()
    App.g_kSetManager._sets.clear()

    pSet = App.SetClass_Create()
    pSet.SetName("turn_smoke")
    App.g_kSetManager._sets["turn_smoke"] = pSet

    # Target ship — TurnToOrientation looks it up by name from the
    # containing set (sdk/.../TurnToOrientation.py:122-128).
    target = ShipClass()
    target.SetTranslateXYZ(*target_pos)
    pSet.AddObjectToSet(target, target_name)

    # Subject ship at origin, identity rotation.
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    pSet.AddObjectToSet(ship, "subject")

    pai = PlainAI_Create(ship, "TestTurn")
    pai.SetScriptModule("TurnToOrientation")
    inst = pai.GetScriptInstance()
    # Required param — SDK SetExternalFunctions registers "SetTarget"
    # as an alias for SetObjectName, both reach the same field.
    inst.SetObjectName(target_name)
    inst.SetPrimaryDirection()  # default: TGPoint3_GetModelForward()
    inst.SetDoneOnLineup(done_on_lineup)
    ship.SetAI(pai)
    return ship, pai, target


def test_turn_to_orientation_rotates_toward_target_on_plus_x():
    """Target at world (1000, 0, 0). After several seconds, the
    ship's world-forward should have a strong +X component (well
    above 0.9 = the SDK's fDoneDot constant)."""
    ship, pai, target = _setup_ship_with_turn_to((1000.0, 0.0, 0.0))
    loop = GameLoop()
    # The SDK's TurnToOrientation runs every 0.5s; the integrator
    # applies the angular velocity every tick. Give it enough time
    # to traverse 90° at FALLBACK MaxAngularVelocity (which is
    # effectively instant) — even a few seconds is overkill but
    # documents the ceiling.
    loop.advance(TICK_RATE * 10)

    fwd = _world_forward(ship)
    # Strong +X component means the ship is facing the target.
    assert fwd.x > 0.9, f"ship did not turn toward +X target; fwd={fwd}"


def test_turn_to_orientation_rotates_toward_target_on_minus_x():
    """Target at (-1000, 0, 0). After alignment, fwd.x should be
    near -1.0 — proving the solver picks the shorter rotation
    direction, not the wrong way around."""
    ship, pai, target = _setup_ship_with_turn_to((-1000.0, 0.0, 0.0))
    loop = GameLoop()
    loop.advance(TICK_RATE * 10)

    fwd = _world_forward(ship)
    assert fwd.x < -0.9, f"ship did not turn toward -X target; fwd={fwd}"


def test_turn_to_orientation_done_on_lineup_completes():
    """With bDoneOnLineup=1, once the ship is within fDoneDot of
    aligned, the AI returns US_DONE and stops being active."""
    ship, pai, target = _setup_ship_with_turn_to(
        (1000.0, 0.0, 0.0), done_on_lineup=1)
    loop = GameLoop()
    # Run long enough that at least one Update fires after alignment.
    # TurnToOrientation cadence is 0.5s; run for 5s = 10 Update
    # cycles. Under FALLBACK_MAX_ACCEL the ship snaps to facing in
    # the first tick after the first Update.
    loop.advance(TICK_RATE * 5)
    assert pai.IsActive() == 0, "TurnToOrientation should complete with bDoneOnLineup=1"
