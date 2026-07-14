"""Integration smoke for AI.PlainAI.FollowObject.

SDK PlainAI/FollowObject.py: follow another ship using FuzzyLogic
class form (SDK FollowObject.py:54-62, 110, 116-118) to compute
speed from distance + facing.

D2 smoke: after one Update call, ship's _speed_setpoint shows
positive impulse (follow); TurnTowardDirection was called."""
import pytest

import App
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


def _build_scene_with_target(target_distance: float):
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ours = ShipClass(); ours.SetTranslateXYZ(0, 0, 0)
    ours._hull = HullSubsystem("H"); ours._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(ours, "Ours")
    target = ShipClass(); target.SetTranslateXYZ(0, target_distance, 0)
    target._hull = HullSubsystem("H"); target._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(target, "Target")
    return ours, target


def _wire_follow_object(ours, target_name="Target"):
    plain = PlainAI_Create(ours, "Follow")
    plain.SetScriptModule("FollowObject")
    inst = plain.GetScriptInstance()
    inst.SetFollowObjectName(target_name)
    return plain, inst


def test_follow_object_update_drives_impulse_when_far():
    """At a distance well beyond fFarDistance, FollowObject should
    produce a non-zero impulse setpoint (chase the target)."""
    ours, _target = _build_scene_with_target(target_distance=1000.0)
    _plain, inst = _wire_follow_object(ours)
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_ACTIVE
    assert ours._speed_setpoint is not None
    assert ours._speed_setpoint[0] > 0.0


def test_follow_object_update_turns_toward_target():
    """TurnTowardDirection called toward the target."""
    ours, _target = _build_scene_with_target(target_distance=500.0)
    _plain, inst = _wire_follow_object(ours)
    calls = []
    ours.TurnTowardDirection = lambda *args, **kwargs: calls.append(args)
    inst.Update()
    assert len(calls) >= 1, "expected TurnTowardDirection to be called"


def test_follow_object_update_with_no_target_returns_done():
    ours, _target = _build_scene_with_target(target_distance=500.0)
    _plain, inst = _wire_follow_object(ours, target_name="NoSuchShip")
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_DONE


def test_follow_object_transitional_geometry_requires_sum_aggregation():
    """Regression for e2b2bf2a: FuzzyLogic.GetResultBySet must SUM
    confidence x percentage over every rule targeting an output set,
    not take the MAX. The two smoke tests above only exercise
    single-dominant-rule geometries (far-away / straight-ahead) where
    max happens to equal sum, so they cannot see this bug.

    Geometry: distance = 80, with SetRoughDistances defaults
    (near=30, mid=60, far=100). FuzzyLogic_BreakIntoSets(80, (30, 60,
    100)) lands exactly halfway between the mid and far peaks, so
        fNearSet = 0.0, fMidSet = 0.5, fFarSet = 0.5
    -- both the MID and FAR distance memberships are simultaneously
    nonzero, and both feed rules targeting the SAME output set,
    FS_FAST_AND_TURN_TOWARD (FollowObject.py:59, 61):
        AddRule(FS_MID_WAYPOINT_FACING, FS_FAST_AND_TURN_TOWARD)
        AddRule(FS_FAR_WAYPOINT_FACING, FS_FAST_AND_TURN_TOWARD)

    The ship starts at the origin facing model-forward +Y (identity
    rotation); the target sits at (0, 80, 0), dead ahead, so the
    facing vector and the position-difference vector are parallel.
    FollowObject's fCosAngle is *not* a true cosine -- it divides by
    the SUM of the two vector lengths, not their product
    (FollowObject.py:100-104):
        vFacing = (0, 1, 0), |vFacing| = 1
        vDifference = (0, 80, 0), |vDifference| = 80
        fCosAngle = vFacing . vDifference / (|vFacing| + |vDifference|)
                  = 80 / 81
        fTowardSet = (fCosAngle + 1) / 2 = (80/81 + 1) / 2 = 161/162
        fAwaySet   = 1 - fTowardSet = 1/162

    SetFuzzySetValues (FollowObject.py:135-140) feeds:
        MID_FACING = fMidSet * fTowardSet = 0.5 * 161/162 = 161/324
        FAR_FACING = fFarSet * fTowardSet = 0.5 * 161/162 = 161/324
    (MID_LEAVING/FAR_LEAVING/NEAR_* all route to
    FS_STOP_AND_TURN_TOWARD, whose speed coefficient fGoSlowSpeed is
    0.0, so they cannot affect the commanded velocity either way.)

    Only FS_MID_WAYPOINT_FACING and FS_FAR_WAYPOINT_FACING target
    FS_FAST_AND_TURN_TOWARD, and no rule at all targets
    FS_MED_AND_TURN_TOWARD, so:
        fGoFast (sum) = MID_FACING + FAR_FACING = 161/162 = 0.99382716...
        fGoFast (max) = max(MID_FACING, FAR_FACING) = 161/324 = 0.49691358...

    GoForward's blend (FollowObject.py:150-152) is
        fVel = 0.0*fGoSlow + 0.4*fGoMed + 1.0*fGoFast
    and fGoMed is always 0 here (no rule targets it), so fVel ==
    fGoFast exactly:
        fVel (sum, correct) = 161/162 ~= 0.9938
        fVel (max, buggy)   = 161/324 ~= 0.4969

    Sum-aggregation is bounded strictly above the max-aggregation
    ceiling of 0.5 at this geometry (fMidSet == fFarSet == 0.5, so
    neither single term can exceed 0.5 x fTowardSet < 0.5). Asserting
    fVel > 0.6 is unreachable under max but comfortably below the
    hand-derived sum value of ~0.9938 -- a max regression fails this
    assertion.
    """
    ours, _target = _build_scene_with_target(target_distance=80.0)
    _plain, inst = _wire_follow_object(ours)
    result = inst.Update()
    assert result == App.ArtificialIntelligence.US_ACTIVE

    expected_fVel = 161.0 / 162.0  # hand-derived above; sum-aggregation only.
    max_ceiling = 0.5              # what max-aggregation cannot exceed here.

    setpoint = ours.GetSpeedSetpoint()
    assert setpoint is not None
    fVel = setpoint[0]

    assert fVel > max_ceiling + 0.1, (
        f"fVel={fVel!r} at/below the max-aggregation ceiling of "
        f"{max_ceiling} -- GetResultBySet may have regressed to MAX "
        "instead of SUM"
    )
    assert fVel == pytest.approx(expected_fVel, rel=1e-9)
