"""A PreprocessingAI does not preprocess over an active, non-interruptable child.

Established 2026-07-14: IsInterruptable is BaseAI vtable +0x04 (default 1), and
PreprocessingAI::Update bypasses its preprocess switch entirely — running the
child unconditionally — when the child is active and NOT interruptable. Ten SDK
nodes call SetInterruptable (AI/Compound/Defend.py:61,81,92,100;
AI/Compound/CallDamageAI.py:81,112). We stored the flag and never read it.
"""
import App
from engine.appc.ai import (
    ArtificialIntelligence, PlainAI_Create, PreprocessingAI_Create,
)
from engine.appc.ai_driver import tick_ai


class _Child:
    def __init__(self):
        self.updates = 0

    def GetNextUpdateTime(self):
        return 0.0

    def Update(self):
        self.updates += 1
        return ArtificialIntelligence.US_ACTIVE


class _Blocker:
    """A preprocessor that would suppress the child (PS_SKIP_ACTIVE)."""
    def __init__(self):
        self.updates = 0

    def Update(self, dEndTime):
        self.updates += 1
        return App.PreprocessingAI.PS_SKIP_ACTIVE


def _build(interruptable: int):
    node = PreprocessingAI_Create(None, "wrap")
    child_ai = PlainAI_Create(None, "child")
    child = _Child()
    child_ai._script_instance = child
    child_ai.SetInterruptable(interruptable)
    node.SetContainedAI(child_ai)
    pre = _Blocker()
    node.SetPreprocessingMethod(pre, "Update")
    return node, pre, child, child_ai


def test_interruptable_child_is_suppressed_by_the_preprocessor():
    node, pre, child, _ = _build(interruptable=1)     # the default
    tick_ai(node, 0.0)
    assert pre.updates == 1
    assert child.updates == 0, "PS_SKIP_ACTIVE suppresses an interruptable child"


def test_active_non_interruptable_child_bypasses_the_preprocessor_entirely():
    node, pre, child, _ = _build(interruptable=0)
    tick_ai(node, 0.0)
    assert child.updates == 1, "the child runs unconditionally"
    assert pre.updates == 0, "the preprocess step is BYPASSED, not just ignored"


def test_a_non_active_non_interruptable_child_does_not_bypass():
    """The bypass requires the child to be ACTIVE. A done/dormant child must not
    shield the node from its own preprocessor."""
    node, pre, child, child_ai = _build(interruptable=0)
    child_ai._status = ArtificialIntelligence.US_DONE
    tick_ai(node, 0.0)
    assert pre.updates == 1


# --- The bypass must guard BOTH arms of the preprocess switch ----------------
#
# _tick_preprocessing's PS_* -> US_* mapping is written out twice: once in the
# "live" arm (the preprocessor's cadence has elapsed and it actually runs) and
# once in the cadence-skipped `else` arm (which reproduces the LAST recorded
# status on ticks where the cadence has not elapsed -- see
# test_preprocess_done_is_lethal.py's test_cadence_skipped_tick_reproduces_a_ps_done_too).
# Both arms can map to the lethal US_DONE. The IsInterruptable bypass sits
# BEFORE the cadence gate specifically so it skips the whole switch -- live
# arm AND cadence-skipped arm alike. A regression that narrowed the bypass to
# only the live arm would let a slow-cadence preprocessor's stale PS_DONE
# tear an active, non-interruptable child down on the very next tick.


class _SlowDonePreproc:
    """PS_DONE on a 5 s cadence -- long enough that a second tick one second
    later lands in the cadence-skipped `else` arm, not the live arm."""

    def __init__(self):
        self.updates = 0

    def GetNextUpdateTime(self):
        return 5.0

    def Update(self, dEndTime):
        self.updates += 1
        return App.PreprocessingAI.PS_DONE


def test_bypass_holds_on_the_cadence_skipped_tick_too():
    """A slow-cadence preprocessor records PS_DONE on its live tick; the
    contained AI then becomes active and non-interruptable (mirroring the
    SDK: DockWithStarbase.py:644's pDockingSequence.SetInterruptable(0) is
    dormant until docking actually starts, while the wrapping
    PreprocessingAI's own preprocessor has already been ticking on its own
    cadence). On the very next tick -- before that 5 s cadence has elapsed
    -- the bypass must still fire and must override the stale PS_DONE,
    not let the cadence-skipped `else` arm's lethal mapping resurrect it.

    Note: the contained child starts INTERRUPTABLE (the default) so the
    first tick is a genuine, un-bypassed live tick -- this is what actually
    advances `_next_update_time` past `game_time` and makes the second tick
    land in the `else` arm at all. A child that is already non-interruptable
    at t=0 never lets the preprocessor run in the first place, so
    `_next_update_time` never advances off its 0.0 default and every
    subsequent tick keeps re-entering the "cadence elapsed" branch -- which
    would make a bypass mistakenly nested inside that branch behaviourally
    indistinguishable from the correct one. Only a live run that genuinely
    schedules a future `_next_update_time` can expose the narrowed bypass.
    """
    node = PreprocessingAI_Create(None, "wrap")
    child_ai = PlainAI_Create(None, "child")
    child = _Child()
    child_ai._script_instance = child
    node.SetContainedAI(child_ai)
    pre = _SlowDonePreproc()
    node.SetPreprocessingMethod(pre, "Update")

    # t=0.0: child is ACTIVE but still INTERRUPTABLE -- the bypass does not
    # apply, so this is a genuine live tick. The preprocessor runs, records
    # PS_DONE, and schedules its next update 5 s out.
    status = tick_ai(node, 0.0)
    assert pre.updates == 1
    assert status == ArtificialIntelligence.US_DONE, (
        "sanity: an un-bypassed PS_DONE really is lethal")
    assert child.updates == 0

    # The contained AI now enters its non-interruptable action (the dynamic
    # SetInterruptable(0) the SDK does mid-flight), while remaining ACTIVE.
    child_ai._status = ArtificialIntelligence.US_ACTIVE
    child_ai.SetInterruptable(0)

    # t=1.0: the 5 s cadence has NOT elapsed -- this tick would take the
    # cadence-skipped `else` arm, which would reproduce the stale PS_DONE
    # and map it to US_DONE. The bypass must fire first, overriding that,
    # and must not let the preprocessor run again either.
    status = tick_ai(node, 1.0)
    assert pre.updates == 1, "the preprocessor must not run again under the bypass"
    assert status != ArtificialIntelligence.US_DONE, (
        "the cadence-skipped arm's lethal PS_DONE mapping must be bypassed too")
    assert child.updates == 1, "the child must run unconditionally once bypassed"
