"""SequenceAI honours SetSkipDormant / SetLoopCount.

Ground truth: ai-architecture.md sec.2 (SequenceAI::Update 0x00492d00) — an
ACTIVE child blocks the sequence; a DORMANT child advances the cursor; wrapping
decrements the loop counter (-1 = forever). All nine E7 mission AI trees set the
flags explicitly (Maelstrom/Episode7/E7M2/EnemyAI.py:60-63), and we stored all
three and read none of them.
"""
from engine.appc.ai import (
    ArtificialIntelligence, PlainAI_Create, SequenceAI_Create,
)
from engine.appc.ai_driver import tick_ai


class _Leaf:
    def __init__(self, status):
        self.status = status
        self.updates = 0

    def GetNextUpdateTime(self):
        return 0.0

    def Update(self):
        self.updates += 1
        return self.status


def _leaf(name, status):
    ai = PlainAI_Create(None, name)
    ai._script_instance = _Leaf(status)
    return ai


def test_skip_dormant_1_advances_past_a_dormant_child():
    seq = SequenceAI_Create(None, "seq")
    seq.SetSkipDormant(1)
    dormant = _leaf("dormant", ArtificialIntelligence.US_DORMANT)
    runner = _leaf("runner", ArtificialIntelligence.US_ACTIVE)
    seq.AddAI(dormant)
    seq.AddAI(runner)

    tick_ai(seq, 0.0)
    tick_ai(seq, 0.1)
    assert runner._script_instance.updates >= 1, "dormant child must be skipped"


def test_skip_dormant_0_blocks_on_a_dormant_child():
    seq = SequenceAI_Create(None, "seq")
    seq.SetSkipDormant(0)          # what all nine E7 trees ask for
    dormant = _leaf("dormant", ArtificialIntelligence.US_DORMANT)
    runner = _leaf("runner", ArtificialIntelligence.US_ACTIVE)
    seq.AddAI(dormant)
    seq.AddAI(runner)

    tick_ai(seq, 0.0)
    tick_ai(seq, 0.1)
    assert runner._script_instance.updates == 0, "dormant child must block"


def test_finite_loop_count_runs_that_many_passes():
    seq = SequenceAI_Create(None, "seq")
    seq.SetLoopCount(2)
    only = _leaf("only", ArtificialIntelligence.US_DONE)
    seq.AddAI(only)

    for t in range(10):
        tick_ai(seq, float(t))

    assert only._script_instance.updates == 2, "two passes, then done"
    assert seq._status == ArtificialIntelligence.US_DONE


def test_loop_count_minus_one_loops_forever():
    seq = SequenceAI_Create(None, "seq")
    seq.SetLoopCount(-1)
    only = _leaf("only", ArtificialIntelligence.US_DONE)
    seq.AddAI(only)

    for t in range(6):
        tick_ai(seq, float(t))

    assert only._script_instance.updates >= 3
    assert seq._status != ArtificialIntelligence.US_DONE
