"""RandomAI draws from the UN-TRIED children, not from all of them.

Ground truth: ai-architecture.md sec.1/sec.2 — the C++ node keeps a per-child
"already tried" byte array (+0x2C) and draws a new child from the un-tried
entries, re-drawing on DORMANT/DONE. Drawing with replacement lets the same
evasive maneuver repeat back-to-back, which is precisely what the shuffle is
there to prevent (AI/Compound/Parts/NoSensorsEvasive.py:47-52).
"""
from engine.appc.ai import (
    ArtificialIntelligence, PlainAI_Create, RandomAI_Create,
)
from engine.appc.ai_driver import tick_ai


class _DoneLeaf:
    """Completes immediately, so RandomAI re-draws on every tick."""
    def __init__(self):
        self.updates = 0

    def GetNextUpdateTime(self):
        return 0.0

    def Update(self):
        self.updates += 1
        return ArtificialIntelligence.US_DONE


def test_every_child_runs_once_before_any_child_repeats():
    rnd = RandomAI_Create(None, "rnd")
    children = []
    for i in range(4):
        ai = PlainAI_Create(None, f"c{i}")
        ai._script_instance = _DoneLeaf()
        rnd.AddAI(ai)
        children.append(ai)

    # Four draws must cover all four children exactly once.
    for t in range(4):
        tick_ai(rnd, float(t))

    counts = [c._script_instance.updates for c in children]
    assert sorted(counts) == [1, 1, 1, 1], f"expected a full shuffle, got {counts}"

    # The fifth draw refills the pool and starts a new cycle.
    tick_ai(rnd, 4.0)
    counts = [c._script_instance.updates for c in children]
    assert sum(counts) == 5
    assert max(counts) == 2
