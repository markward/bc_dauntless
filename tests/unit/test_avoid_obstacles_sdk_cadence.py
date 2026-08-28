"""The evading-re-decision cadence must apply to the SCAN WE ACTUALLY RUN.

`AVOID_EVADING_UPDATE_DELAY_S` restores BC's own commented-out alternative --
`AI/Preprocessors.py:1624` literally reads `self.fMinimumUpdateDelay = 0.0 #
0.25` -- so an evading ship re-decides at 4 Hz instead of every tick. Same for
`_phase_factor`, which breaks the lock-step herd on the first reschedule.

Both were only ever applied in `_replace_avoid_obstacles`, i.e. to the ENGINE
scan, which is off by default. So on the path everything actually runs, an
evading ship re-scanned every single tick and every ship scanned on the same
tick as its neighbours. CLAUDE.md's "an evading ship re-decides avoidance at
4 Hz" described a configuration nobody was running.

It went unnoticed because the scan was inert: `ProximityManager.GetNextObject`
was a hardcoded `return None`, so `TestCourseOverride` always reported nothing
to avoid and no ship ever entered the evading branch at all. With the walk
restored the rate is real, and measured: +1.4 ms of sim per tick at 16 ships,
+3.4 ms at 32, dominated by scan COUNT (~14 scans/tick at 32 ships, where the
4 Hz cadence predicts ~8).
"""
import pytest

from engine.appc import ai_optimized
from engine.appc.ai import PreprocessingAI_Create
from engine.appc.ships import ShipClass


@pytest.fixture(autouse=True)
def _isolate_dynamic_classes():
    """Undo the dynamic classes these tests cause ai_optimized to mint.

    The wrappers cache one generated class per base and publish it into
    ai_optimized's module globals under a name derived from the base's --
    `FireScript_NonLethal`, `PhasedAvoidObstacles` -- because that is how
    pickle resolves them at unpickle time. The doubles below are NAMED after
    real SDK classes on purpose (OPTIMIZED_PREPROCESSORS is keyed by class
    name), so without this they overwrite the entries generated from the real
    SDK classes, and a later test that pickles a genuinely-wrapped preprocessor
    unpickles into a subclass of a throwaway test double. That is a real
    cross-test failure, caught by the gate:
    test_preprocess_done_is_lethal::test_a_wrapped_fire_script_can_be_pickled_and_unpickled
    passes alone and fails in suite order.
    """
    caches = (ai_optimized._NON_LETHAL_CLASSES,
              ai_optimized._PHASED_AVOIDANCE_CLASSES,
              ai_optimized._ENGINE_AVOIDANCE_CLASSES)
    before_caches = [dict(c) for c in caches]
    before_globals = dict(vars(ai_optimized))
    yield
    for cache, snapshot in zip(caches, before_caches):
        cache.clear()
        cache.update(snapshot)
    g = vars(ai_optimized)
    for name in [n for n in g if n not in before_globals]:
        del g[name]
    g.update(before_globals)


class AvoidObstacles:
    """The SDK ctor's cadence fields, which are what the wrapper adjusts.

    Named `AvoidObstacles` on purpose: OPTIMIZED_PREPROCESSORS is keyed by
    class NAME (mirroring the binary's DAT_00982A1C name registry), so a fake
    called anything else silently misses the registry and every assertion here
    would be about the unwrapped object.
    """
    def __init__(self):
        self.fMinimumUpdateDelay = 0.0        # SDK default; BC's own "# 0.25"
        self.fMaximumUpdateDelay = 0.25
        self.fUpdateDelay = 0.25
        self.pCodeAI = None

    def GetNextUpdateTime(self):
        return self.fUpdateDelay

    def Update(self, dEndTime):
        return 0


def _bind(inst):
    """Bind through BC's substitution point: SetContainedAI -> the registry."""
    node = PreprocessingAI_Create(ShipClass(), "Avoid")
    node.SetPreprocessingMethod(ai_optimized.optimized_version_of(inst), "Update")
    return node


def test_the_default_wrapper_applies_the_evading_cadence():
    inst = AvoidObstacles()
    wrapped = ai_optimized.optimized_version_of(inst)

    assert wrapped.fMinimumUpdateDelay == ai_optimized.AVOID_EVADING_UPDATE_DELAY_S
    assert wrapped.fMinimumUpdateDelay > 0.0, (
        "an evading ship still re-scans every tick on the default path"
    )


def test_the_maximum_delay_is_left_at_bc_s_value():
    """Only the evading (minimum) delay is restored. The not-evading cadence is
    already BC's 0.25 and must not be touched -- reaction latency to a NEW
    threat stays what it always was."""
    inst = AvoidObstacles()
    wrapped = ai_optimized.optimized_version_of(inst)
    assert wrapped.fMaximumUpdateDelay == 0.25


def test_the_wrapper_still_shares_state_with_the_original():
    """The alias shares __dict__, so the SDK Update's own writes to
    fUpdateDelay stay visible -- setting the field must not have broken that."""
    inst = AvoidObstacles()
    wrapped = ai_optimized.optimized_version_of(inst)
    wrapped.fUpdateDelay = 9.0
    assert inst.fUpdateDelay == 9.0
    assert inst.fMinimumUpdateDelay == ai_optimized.AVOID_EVADING_UPDATE_DELAY_S


def test_the_first_reschedule_is_phase_shifted_then_the_rate_is_bc_s():
    """Two ships bound in the same frame must not stay locked to the same tick.
    The offset only ever SHORTENS the first interval, so no re-decision is
    pushed past BC's own fMaximumUpdateDelay."""
    node = _bind(AvoidObstacles())
    inst = node._preprocessing_instance

    first = inst.GetNextUpdateTime()
    assert 0.0 < first <= 0.25
    assert inst.GetNextUpdateTime() == 0.25          # and every one after


def test_ships_bound_together_do_not_all_scan_on_the_same_tick():
    phases = set()
    for _ in range(8):
        node = _bind(AvoidObstacles())
        phases.add(round(node._preprocessing_instance.GetNextUpdateTime(), 6))
    assert len(phases) > 1, (
        "every AvoidObstacles node took the same first interval, so the whole "
        "crowd re-scans on the same tick forever -- the herd this offset exists "
        "to break"
    )


def test_a_zero_setting_restores_the_sdk_behaviour_exactly():
    """The knob documents 0.0 as "restore BC's every-tick behaviour"."""
    inst = AvoidObstacles()
    original = ai_optimized.AVOID_EVADING_UPDATE_DELAY_S
    try:
        ai_optimized.AVOID_EVADING_UPDATE_DELAY_S = 0.0
        wrapped = ai_optimized.optimized_version_of(inst)
        assert wrapped.fMinimumUpdateDelay == 0.0
    finally:
        ai_optimized.AVOID_EVADING_UPDATE_DELAY_S = original


def test_other_preprocessors_are_not_given_a_cadence():
    """FireScript goes through the same non-lethal wrapper. Its cadence is its
    own (GetNextUpdateTime -> 0.2) and must not gain avoidance's fields."""
    class FireScript:
        def __init__(self):
            self.pCodeAI = None

        def Update(self, dEndTime):
            return 0

    wrapped = ai_optimized.optimized_version_of(FireScript())
    assert "fMinimumUpdateDelay" not in wrapped.__dict__
