"""PriorityListAI must re-evaluate each ConditionalAI child's status
*every* tick before deciding which child to dispatch — not trust a
cached status from a previous evaluation.

Why: ConditionInRange (and other condition scripts) update their
status asynchronously from ProximityCheck events fired by
evaluate_proximity_checks(). The ConditionalAI wrapping the condition
doesn't get re-ticked unless it's the priority list's current pick,
so its cached _status drifts out of sync with the condition's true
value.

Live-game symptom: enemy ships in M2Objects approached the player
into MidRange (200 m), but the MidRange ConditionalAI status stayed
DORMANT (its last-evaluated value) while ConditionInRange.GetStatus()
flipped to 1. PriorityListAI kept picking LongRange (whose status
was ACTIVE from earlier evaluation), so FireScript at MidRange never
dispatched — no weapons fire.
"""
from engine.appc.ai import (
    ArtificialIntelligence, ConditionalAI, PlainAI, PriorityListAI,
    TGCondition,
)
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass


class _Leaf:
    """Counts Update calls so we can see which branch the priority
    list selected each tick."""
    def __init__(self):
        self.calls = 0

    def Update(self):
        self.calls += 1
        return ArtificialIntelligence.US_ACTIVE

    def GetNextUpdateTime(self):
        return 0.0  # tick every frame


def _conditional(eval_fn, cond, leaf):
    plain = PlainAI(ShipClass(), "leaf")
    plain._script_instance = leaf
    c = ConditionalAI(ShipClass(), "C")
    c.SetContainedAI(plain)
    c.AddCondition(cond)
    c.SetEvaluationFunction(eval_fn)
    return c


def _always_active(b):
    return ArtificialIntelligence.US_ACTIVE if b else ArtificialIntelligence.US_DORMANT


def test_priority_list_picks_higher_priority_when_its_condition_flips_active():
    """A higher-priority ConditionalAI starts DORMANT because its
    condition starts at 0. Tick — lower-priority branch runs.
    Flip the high-priority condition to 1 — the very next tick must
    pick the high-priority branch even though its cached status was
    last set to DORMANT.
    """
    cond_high = TGCondition()
    cond_low = TGCondition()
    cond_low.SetStatus(1)  # low-priority condition always true

    leaf_high = _Leaf()
    leaf_low = _Leaf()
    high = _conditional(_always_active, cond_high, leaf_high)
    low = _conditional(_always_active, cond_low, leaf_low)

    pl = PriorityListAI(ShipClass(), "PL")
    pl.AddAI(high, 1)  # priority 1 == highest
    pl.AddAI(low, 2)

    tick_ai(pl, game_time=0.0)
    assert leaf_high.calls == 0, "high-priority condition is False; high leaf should not run"
    assert leaf_low.calls == 1, "low-priority should run when high is dormant"

    # Now flip the high-priority condition active.
    cond_high.SetStatus(1)

    tick_ai(pl, game_time=0.1)
    assert leaf_high.calls == 1, (
        "after high-priority condition flipped active, the priority "
        "list should re-pick it — even though high's cached _status "
        "was DORMANT from the previous evaluation"
    )
