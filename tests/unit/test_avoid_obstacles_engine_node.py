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


@pytest.fixture(autouse=True)
def _engine_avoidance_enabled(monkeypatch):
    """These tests are ABOUT the engine-side avoidance scan, which is opt-in.

    It is off by default since it was found to return PS_SKIP_ACTIVE far more
    often than the SDK's scan, which suppresses the whole attack subtree and
    strips its focus -- dropping shields and stopping weapons fire (see
    tests/integration/test_avoidance_does_not_suppress_combat.py). Registering
    it here keeps this file testing the thing it was written to test, and keeps
    that coverage alive for whoever picks the optimisation back up.

    Registered directly rather than via DAUNTLESS_ENGINE_AVOIDANCE because the
    env var is read at import time.
    """
    from engine.appc import ai_optimized
    monkeypatch.setitem(ai_optimized.OPTIMIZED_PREPROCESSORS,
                        "AvoidObstacles", ai_optimized._replace_avoid_obstacles)



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
    """Only TestCourseOverride and the first-schedule phase offset are ours.
    The cadence hook in particular must survive: the driver reads
    GetNextUpdateTime, and losing it would make the node re-evaluate every tick
    instead of on BC's 0.25 s idle cadence.

    The FIRST call carries the de-synchronising phase offset (see
    test_first_schedules_are_phase_spread); every call after it is the SDK
    value untouched."""
    node = _optimized()
    node.GetNextUpdateTime()                       # consume the phase offset
    assert node.GetNextUpdateTime() == 0.25
    assert node.GetNextUpdateTime() == 0.25
    assert node.Update(0.0) == 0


def test_a_node_with_no_code_ai_yields_no_override():
    """AvoidObstacles.Update returns PS_DONE with no ship, which is lethal in
    our driver — the non-lethal base handles that, and this path must simply
    report 'no override' rather than raise.

    (None, None) — the SDK's own TestCourseOverride shape (Preprocessors.py
    :1713 `return (None, None)` on both no-ship and no-set). Update unpacks the
    pair straight into vOverrideDirection / fOverrideSpeed and only ever tests
    the direction, so the second slot is free — which is exactly why it should
    not gratuitously differ from the surface it replaces."""
    node = _optimized()
    assert ca.course_override_for(node) == (None, None)


# ── first-schedule phase spread (thundering herd) ────────────────────────────


class _FakeShip:
    def __init__(self, obj_id):
        self._obj_id = obj_id

    def GetObjID(self):
        return self._obj_id


class _FakeCodeAI:
    def __init__(self, ship):
        self._ship = ship

    def GetShip(self):
        return self._ship


def _node_for(obj_id):
    inst = _FakeAvoidObstacles()
    inst.pCodeAI = _FakeCodeAI(_FakeShip(obj_id))
    return ai_optimized.optimized_version_of(inst)


def test_first_schedules_are_phase_spread():
    """Ships created together must not stay lock-stepped forever.

    fMinimumUpdateDelay == fMaximumUpdateDelay == 0.25 and the driver
    reschedules as `game_time + interval`, so any two nodes that ever coincide
    coincide for the rest of the mission — and ships spawned in the same frame
    start coincident. Measured scans/tick was [8,0,0,...,0,8,0,...]: the mean
    dropped 15x but the PER-TICK PEAK did not move at all.

    A one-off offset on the FIRST reschedule breaks the lock permanently.
    """
    firsts = [_node_for(i).GetNextUpdateTime() for i in range(1, 17)]
    assert len(set(firsts)) >= 4, (
        "16 consecutively-created nodes landed on %d distinct first intervals "
        "(%r) — they are still a herd" % (len(set(firsts)), sorted(set(firsts))))


def test_first_schedules_are_phase_spread_for_strided_object_ids():
    """The realistic id pattern, and the one a naive `% buckets` fails on.

    Object ids come off ONE global counter shared with every subsystem,
    hardpoint and property a ship allocates, so consecutive SHIPS are strided.
    A stride that is a multiple of the bucket count puts every ship in the same
    bucket — the herd, restored — so the bucket must depend on more than the
    low bits.
    """
    for stride in (8, 16, 40, 64, 128):
        firsts = [_node_for(1000 + i * stride).GetNextUpdateTime()
                  for i in range(16)]
        assert len(set(firsts)) >= 4, (
            "stride %d collapsed 16 ships onto %d first intervals (%r)"
            % (stride, len(set(firsts)), sorted(set(firsts))))


def test_the_phase_offset_never_delays_a_re_decision():
    """Avoidance is a safety system: the offset may only bring a re-scan
    FORWARD, never push it past BC's own fMaximumUpdateDelay."""
    for i in range(1, 33):
        first = _node_for(i).GetNextUpdateTime()
        assert 0.0 < first <= 0.25, "first interval %r out of range" % (first,)


def test_the_phase_offset_is_deterministic():
    """No `random` in sim code — the offset is derived from the ship's object
    id, so the same ship gets the same phase on every run and across a
    save/restore."""
    for i in (1, 5, 23, 100):
        assert _node_for(i).GetNextUpdateTime() == _node_for(i).GetNextUpdateTime()


def test_the_phase_offset_applies_once_only():
    """It is a PHASE shift, not a rate change: after the first reschedule the
    node runs at exactly BC's cadence, merely offset from its neighbours."""
    node = _node_for(3)
    node.GetNextUpdateTime()
    assert [node.GetNextUpdateTime() for _ in range(4)] == [0.25] * 4


def test_a_node_with_no_ship_still_schedules():
    """pCodeAI is bound after construction, and the driver can reach
    GetNextUpdateTime before a ship exists. That must not raise, and must not
    return a delay outside the cadence."""
    node = _optimized()                       # pCodeAI is None
    first = node.GetNextUpdateTime()
    assert 0.0 < first <= 0.25


def test_our_constants_match_the_sdk_defaults():
    """No shipped SDK script customises these, so the engine scan reads module
    constants. If BC's values were ever misread this is where it surfaces,
    rather than as subtly wrong steering.

    Against the REAL ``AI.Preprocessors.AvoidObstacles``, not the fake above.
    This test used to compare ``ca.AVOID_*`` to ``_FakeAvoidObstacles`` — a
    hand-written double carrying the same literals — so it compared a copy to
    itself and could not fail for the reason its docstring claimed. The SDK
    tree is importable in this suite (tests/conftest.py's _SDKFinder), so read
    the values off the class that actually ships.
    """
    import AI.Preprocessors
    sdk = AI.Preprocessors.AvoidObstacles()
    assert ca.AVOID_PREDICTION_TIME_S == sdk.fPredictionTime
    assert ca.AVOID_MINIMUM_RADIUS_GU == sdk.fMinimumRadius
    assert ca.AVOID_PERSONAL_SPACE_MULT == sdk.fPersonalSpace


def test_our_cadence_constants_match_the_sdk_defaults():
    """Same, for the update-delay pair the driver schedules on.

    ``AVOID_MIN_UPDATE_DELAY_S`` is the SDK's shipped ``fMinimumUpdateDelay``
    (0.0). ``ai_optimized.AVOID_EVADING_UPDATE_DELAY_S`` is our deliberate
    departure from it — see that module — and is pinned separately below.
    """
    import AI.Preprocessors
    sdk = AI.Preprocessors.AvoidObstacles()
    assert ca.AVOID_MAX_UPDATE_DELAY_S == sdk.fMaximumUpdateDelay
    assert ca.AVOID_MIN_UPDATE_DELAY_S == sdk.fMinimumUpdateDelay


def test_our_dont_avoid_types_match_the_sdk_list():
    """The engine scan resolves the blacklist from module-level names rather
    than reading ``lDontAvoidTypes`` off the node (see
    ``_engine_avoidance_class``'s docstring, which says so). That is only
    harmless while the two agree — so check them against each other."""
    import AI.Preprocessors
    sdk = AI.Preprocessors.AvoidObstacles()
    assert set(ca._dont_avoid_types()) == set(sdk.lDontAvoidTypes)


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
