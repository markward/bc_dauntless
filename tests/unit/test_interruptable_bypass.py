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
