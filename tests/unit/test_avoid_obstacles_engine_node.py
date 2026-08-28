"""AvoidObstacles is replaced through BC's own substitution point.

PreprocessingAI::SetContainedAI (0x0048E570) calls GetOptimizedVersion
(vtable +0x34) and stores the RETURNED object; PreprocessingAI's override
(0x0048EB20) swaps four named Python preprocessors for native nodes at bind
time. AvoidObstacles is one of them, so replacing it is the mechanism working
as designed rather than a workaround.

What matters is that ONLY the world scan is replaced. Everything else about the
node -- the PS_* contract, the steering calls, the update cadence, the
parameters the SDK ctor set -- must still be SDK code operating on SDK state.
"""
import pytest

from engine.appc import ai_optimized
from engine.appc import collision_avoidance as ca


class _FakeAvoidObstacles:
    """Stands in for the SDK class: same surface the real node exposes."""
    def __init__(self):
        self.fPredictionTime = 15.0
        self.fMinimumRadius = 225.0
        self.fPersonalSpace = 2.5
        self.vOverrideDirection = None
        self.fOverrideSpeed = None
        self.lDontAvoidTypes = ["a", "b"]
        self.pCodeAI = None
        self.scanned = 0

    def GetNextUpdateTime(self):
        return 0.25

    def Update(self, dEndTime):
        return 0

    def TestCourseOverride(self):
        self.scanned += 1          # the SDK scan; must NOT run once replaced
        return None, None


# Give the fake the registry's name so optimized_version_of picks it up.
_FakeAvoidObstacles.__name__ = "AvoidObstacles"


def _optimized():
    return ai_optimized.optimized_version_of(_FakeAvoidObstacles())


def test_the_registry_replaces_avoid_obstacles():
    assert "AvoidObstacles" in ai_optimized.OPTIMIZED_PREPROCESSORS
    node = _optimized()
    assert type(node) is not _FakeAvoidObstacles


def test_the_sdk_scan_no_longer_runs():
    node = _optimized()
    node.TestCourseOverride()
    assert node.scanned == 0, "the SDK world scan still ran"


def test_state_is_shared_not_copied():
    """The alias shares __dict__, so SDK-set parameters and post-bind mutation
    stay visible through both objects — as the shipped engine's swap does."""
    original = _FakeAvoidObstacles()
    node = ai_optimized.optimized_version_of(original)
    assert node.__dict__ is original.__dict__
    assert node.fPersonalSpace == 2.5
    assert node.lDontAvoidTypes == ["a", "b"]
    original.fOverrideSpeed = 7.0
    assert node.fOverrideSpeed == 7.0


def test_the_rest_of_the_node_is_still_sdk_code():
    """Only TestCourseOverride is ours. The cadence hook in particular must
    survive: the driver reads GetNextUpdateTime, and losing it would make the
    node re-evaluate every tick instead of on BC's 0.25 s idle cadence."""
    node = _optimized()
    assert node.GetNextUpdateTime() == 0.25
    assert node.Update(0.0) == 0


def test_a_node_with_no_code_ai_yields_no_override():
    """AvoidObstacles.Update returns PS_DONE with no ship, which is lethal in
    our driver — the non-lethal base handles that, and this path must simply
    report 'no override' rather than raise."""
    node = _optimized()
    assert ca.course_override_for(node) == (None, 0.0)


def test_our_constants_match_the_sdk_defaults():
    """No shipped SDK script customises these, so the engine scan reads module
    constants. If BC's values were ever misread — or a mod changes them — this
    is where it surfaces, rather than as subtly wrong steering."""
    sdk = _FakeAvoidObstacles()
    assert ca.AVOID_PREDICTION_TIME_S == sdk.fPredictionTime
    assert ca.AVOID_MINIMUM_RADIUS_GU == sdk.fMinimumRadius
    assert ca.AVOID_PERSONAL_SPACE_MULT == sdk.fPersonalSpace


def test_the_game_loop_no_longer_runs_a_second_controller():
    """The duplicate pass is gone; avoidance is the preprocessor only."""
    import inspect
    from engine.core import loop
    src = inspect.getsource(loop.GameLoop.tick)
    assert "tick_collision_avoidance" not in src


def test_the_shipped_evading_cadence_is_pinned():
    """Both cadence tests patch AVOID_EVADING_UPDATE_DELAY_S explicitly, so
    nothing exercised the value that actually ships. Setting the default to
    5.0 (20x) left the whole avoidance suite green.

    0.25 s is BC's own fMaximumUpdateDelay: this change makes an EVADING ship
    re-decide on the same cadence a non-evading one already used, rather than
    every tick. Raising it further is a real behaviour change and should fail
    here rather than pass quietly.
    """
    from engine.appc import ai_optimized
    assert ai_optimized.AVOID_EVADING_UPDATE_DELAY_S == 0.25, (
        "the shipped evading re-decision cadence changed; if that is "
        "deliberate, re-run the separation probes before editing this number")
