import random

from engine.appc.ai import (
    ArtificialIntelligence, PlainAI, PriorityListAI, SequenceAI,
    ConditionalAI, PreprocessingAI, RandomAI, TGCondition,
)
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass


class _FakeLeaf:
    """Minimal stand-in for an AI.PlainAI.<X>.X instance.
    Records Update calls and returns a programmable US_* status."""
    def __init__(self, next_update=1.0, status=ArtificialIntelligence.US_ACTIVE):
        self.calls = 0
        self._next_update = next_update
        self._status = status

    def GetNextUpdateTime(self):
        return self._next_update

    def Update(self):
        self.calls += 1
        return self._status


def _make_plain(ship, leaf):
    pai = PlainAI(ship, "fake")
    pai._script_instance = leaf  # bypass SetScriptModule for unit tests
    return pai


def test_plain_ai_first_update_fires_at_game_time_zero():
    ship = ShipClass()
    leaf = _FakeLeaf(next_update=5.0)
    pai = _make_plain(ship, leaf)
    tick_ai(pai, game_time=0.01)
    assert leaf.calls == 1


def test_plain_ai_respects_get_next_update_time():
    ship = ShipClass()
    leaf = _FakeLeaf(next_update=5.0)
    pai = _make_plain(ship, leaf)
    tick_ai(pai, game_time=0.01)   # fires (next_update_time was 0)
    tick_ai(pai, game_time=3.0)    # before next fire (5.01) -> no call
    tick_ai(pai, game_time=4.99)   # still before -> no call
    tick_ai(pai, game_time=5.02)   # >= 5.01 -> fires
    assert leaf.calls == 2


def test_plain_ai_missing_get_next_update_time_runs_next_tick_not_throttled():
    """A script instance that omits GetNextUpdateTime (the _AIScriptInstance
    data-bag fallback SetScriptModule installs when a module fails to import
    or is unset) must run Update on the very next tick, not be throttled by
    a made-up 1.0s interval. Appc's PlainAI::Update bridge returns 0.0 when
    the Python call fails, which is "run every tick" -- there is no default
    interval in C++ (ai-architecture.md sec.3).

    All 25 real AI/PlainAI/*.py script classes define GetNextUpdateTime, so
    this fallback is reachable only through the data-bag shape exercised
    here (SetScriptModule with an unresolvable module name)."""
    ship = ShipClass()
    pai = PlainAI(ship, "fake")
    pai.SetScriptModule("NoSuchAIScript_ForCadenceFallbackTest")
    inst = pai.GetScriptInstance()
    calls = []
    # Override just Update (instance attribute shadows the data-bag's
    # __getattr__); GetNextUpdateTime stays absent from the data bag, so
    # the fallback (getattr returns the no-op lambda, which returns None)
    # is exercised exactly as in production.
    inst.Update = lambda: calls.append(1)

    tick_ai(pai, game_time=0.0)
    tick_ai(pai, game_time=0.1)

    assert len(calls) == 2, (
        "missing GetNextUpdateTime must fall back to 0.0s (every tick); "
        "a 1.0s fallback would throttle the second tick out"
    )


def test_plain_ai_status_propagates():
    leaf = _FakeLeaf(status=ArtificialIntelligence.US_DONE)
    pai = _make_plain(ShipClass(), leaf)
    tick_ai(pai, game_time=0.01)
    assert pai._status == ArtificialIntelligence.US_DONE


def test_priority_list_runs_highest_priority_active():
    """Lower priority-int is higher priority (matches SDK semantics)."""
    high = _make_plain(ShipClass(), _FakeLeaf())
    low = _make_plain(ShipClass(), _FakeLeaf())
    p = PriorityListAI(ShipClass(), "P")
    p.AddAI(low, priority=10)
    p.AddAI(high, priority=1)
    tick_ai(p, game_time=0.01)
    assert high.GetScriptInstance().calls == 1
    assert low.GetScriptInstance().calls == 0


def test_priority_list_skips_dormant_child():
    high = _make_plain(ShipClass(), _FakeLeaf())
    low = _make_plain(ShipClass(), _FakeLeaf())
    high._status = ArtificialIntelligence.US_DORMANT
    p = PriorityListAI(ShipClass(), "P")
    p.AddAI(high, priority=1)
    p.AddAI(low, priority=10)
    tick_ai(p, game_time=0.01)
    assert high.GetScriptInstance().calls == 0
    assert low.GetScriptInstance().calls == 1


def test_sequence_advances_on_done():
    a = _make_plain(ShipClass(), _FakeLeaf(status=ArtificialIntelligence.US_DONE))
    b = _make_plain(ShipClass(), _FakeLeaf())
    s = SequenceAI(ShipClass(), "S")
    s.AddAI(a); s.AddAI(b)
    tick_ai(s, game_time=0.01)
    assert a.GetScriptInstance().calls == 1
    assert b.GetScriptInstance().calls == 0
    tick_ai(s, game_time=0.02)
    assert b.GetScriptInstance().calls == 1


def test_sequence_completes_when_all_done():
    a = _make_plain(ShipClass(), _FakeLeaf(status=ArtificialIntelligence.US_DONE))
    b = _make_plain(ShipClass(), _FakeLeaf(status=ArtificialIntelligence.US_DONE))
    s = SequenceAI(ShipClass(), "S")
    s.AddAI(a); s.AddAI(b)
    tick_ai(s, game_time=0.01)  # a -> DONE; advance
    tick_ai(s, game_time=0.02)  # b -> DONE; sequence done
    assert s._status == ArtificialIntelligence.US_DONE


def test_conditional_runs_when_condition_active():
    leaf = _FakeLeaf()
    child = _make_plain(ShipClass(), leaf)
    cond = TGCondition(); cond.SetActive(); cond.SetStatus(1)
    cai = ConditionalAI(ShipClass(), "C")
    cai.SetContainedAI(child)
    cai.AddCondition(cond)
    tick_ai(cai, game_time=0.01)
    assert leaf.calls == 1


def test_conditional_does_not_run_when_condition_inactive():
    leaf = _FakeLeaf()
    child = _make_plain(ShipClass(), leaf)
    cond = TGCondition(); cond.SetActive(); cond.SetStatus(0)
    cai = ConditionalAI(ShipClass(), "C")
    cai.SetContainedAI(child)
    cai.AddCondition(cond)
    tick_ai(cai, game_time=0.01)
    assert leaf.calls == 0
    assert cai._status == ArtificialIntelligence.US_DORMANT


def test_conditional_ai_propagates_contained_done():
    """A ConditionalAI whose EvalFunc always reports US_ACTIVE must still
    finish once its contained AI reaches US_DONE.

    Regression for DockWithStarbase: its PriorityList children are
    ConditionalAI wrapping static one-shot flags whose EvalFunc returns
    US_ACTIVE forever. Without folding the contained AI's completion in,
    the ConditionalAI stays ACTIVE forever even after the contained leaf
    (e.g. PlayerDocked) reaches US_DONE, so the parent PriorityList/
    Sequence never completes and EndCutscene never runs (locked in
    cutscene)."""
    leaf = _FakeLeaf(status=ArtificialIntelligence.US_DONE)
    child = _make_plain(ShipClass(), leaf)
    cond = TGCondition(); cond.SetActive(); cond.SetStatus(1)
    cai = ConditionalAI(ShipClass(), "C")
    cai.SetContainedAI(child)
    cai.AddCondition(cond)
    cai.SetEvaluationFunction(lambda *args: ArtificialIntelligence.US_ACTIVE)
    tick_ai(cai, game_time=0.01)
    assert child._status == ArtificialIntelligence.US_DONE
    assert cai._status == ArtificialIntelligence.US_DONE


class _FakePreprocessor:
    """Preprocessor stand-in. Set status to one of PS_*; tick_ai will call
    Preprocess() each tick and dispatch the contained AI accordingly."""
    def __init__(self, status):
        self.status = status
        self.calls = 0
    def Preprocess(self):
        self.calls += 1
        return self.status


def _make_pp(status, contained):
    pp = PreprocessingAI(ShipClass(), "PP")
    inst = _FakePreprocessor(status)
    pp.SetPreprocessingMethod(inst, "Preprocess")
    pp.SetContainedAI(contained)
    return pp, inst


def test_preprocessing_normal_runs_child():
    leaf = _FakeLeaf()
    child = _make_plain(ShipClass(), leaf)
    pp, inst = _make_pp(PreprocessingAI.PS_NORMAL, child)
    tick_ai(pp, game_time=0.01)
    assert inst.calls == 1
    assert leaf.calls == 1


def test_preprocessing_skip_active_does_not_run_child():
    leaf = _FakeLeaf()
    child = _make_plain(ShipClass(), leaf)
    pp, inst = _make_pp(PreprocessingAI.PS_SKIP_ACTIVE, child)
    tick_ai(pp, game_time=0.01)
    assert inst.calls == 1
    assert leaf.calls == 0
    assert pp._status == ArtificialIntelligence.US_ACTIVE


def test_preprocessing_skip_dormant_marks_dormant():
    leaf = _FakeLeaf()
    child = _make_plain(ShipClass(), leaf)
    pp, inst = _make_pp(PreprocessingAI.PS_SKIP_DORMANT, child)
    tick_ai(pp, game_time=0.01)
    assert leaf.calls == 0
    assert pp._status == ArtificialIntelligence.US_DORMANT


def test_preprocessing_done_marks_the_node_done_and_stops_the_child():
    """PS_DONE means 'this node is finished' -> US_DONE, which tears the node
    down. Binary-verified 2026-07-14: PreprocessingAI::Update's PS_* switch
    (0x48eab1) maps PS_DONE and PS_INVALID to US_DONE via its default arm.

    This test used to assert the opposite ('keep dispatching the child'), a
    wrong lesson drawn from ManagePower's `# Unused. return PS_DONE` body —
    which never runs in the shipped game, because the engine swaps that node for
    a native one (see engine/appc/ai_optimized.py and
    tests/unit/test_preprocess_done_is_lethal.py)."""
    # next_update=0 so the contained PlainAI would dispatch every tick if it
    # were reached at all.
    leaf = _FakeLeaf(next_update=0.0)
    child = _make_plain(ShipClass(), leaf)
    pp, inst = _make_pp(PreprocessingAI.PS_DONE, child)
    tick_ai(pp, game_time=0.01)
    assert pp._status == ArtificialIntelligence.US_DONE
    assert leaf.calls == 0, "PS_DONE must not fall through to the contained AI"
    # Still done on a later tick; the child is never reached.
    tick_ai(pp, game_time=1.0)
    assert pp._status == ArtificialIntelligence.US_DONE
    assert leaf.calls == 0


def test_random_ai_ticks_a_child():
    """A RandomAI is no longer inert: one tick picks and ticks a child.

    SDK semantics (docs/.../ai-architecture.md RandomAI): picks one child
    at random and runs it. Proves the missing dispatch branch is wired.
    """
    random.seed(0)
    leaves = [_FakeLeaf(next_update=0.0) for _ in range(4)]
    children = [_make_plain(ShipClass(), leaf) for leaf in leaves]
    rai = RandomAI(ShipClass(), "R")
    for child in children:
        rai.AddAI(child)
    tick_ai(rai, game_time=0.01)
    # Exactly one child was ticked (the random pick).
    assert sum(leaf.calls for leaf in leaves) == 1
    # RandomAI stays active while a child runs (infinite maneuver picker).
    assert rai._status == ArtificialIntelligence.US_ACTIVE


def test_random_ai_repicks_after_child_done():
    """When the current child reaches US_DONE, the next tick re-picks a new
    random child (SDK: 'on completion, picks another'). The RandomAI itself
    does NOT terminate."""
    random.seed(0)
    # All children report DONE immediately so we exercise the re-pick path.
    leaves = [
        _FakeLeaf(next_update=0.0, status=ArtificialIntelligence.US_DONE)
        for _ in range(4)
    ]
    children = [_make_plain(ShipClass(), leaf) for leaf in leaves]
    rai = RandomAI(ShipClass(), "R")
    for child in children:
        rai.AddAI(child)
    tick_ai(rai, game_time=0.01)   # pick + tick child -> child DONE
    first_pick = rai._current_child
    assert sum(leaf.calls for leaf in leaves) == 1
    tick_ai(rai, game_time=0.02)   # child was DONE -> re-pick + tick again
    assert sum(leaf.calls for leaf in leaves) == 2
    # RandomAI never terminates just because one child finished.
    assert rai._status == ArtificialIntelligence.US_ACTIVE
    assert first_pick is not None


def test_random_ai_repick_rearms_a_previously_done_child():
    """A re-selected child is reset to US_ACTIVE before being ticked, so a
    child that finished earlier can run again (single-element RandomAI makes
    the re-pick deterministic without seeding)."""
    leaf = _FakeLeaf(next_update=0.0)  # reports ACTIVE on Update
    child = _make_plain(ShipClass(), leaf)
    rai = RandomAI(ShipClass(), "R")
    rai.AddAI(child)
    tick_ai(rai, game_time=0.01)
    child._status = ArtificialIntelligence.US_DONE  # simulate completion
    tick_ai(rai, game_time=0.02)                    # re-pick re-arms it
    assert child._status == ArtificialIntelligence.US_ACTIVE
    assert leaf.calls == 2


def test_random_ai_repick_is_seeded_deterministic():
    """With a seeded RNG the picks are reproducible — guards against the
    branch silently no-op'ing."""
    random.seed(1)
    leaves = [_FakeLeaf(next_update=0.0) for _ in range(3)]
    children = [_make_plain(ShipClass(), leaf) for leaf in leaves]
    rai = RandomAI(ShipClass(), "R")
    for child in children:
        rai.AddAI(child)
    random.seed(1)
    expected = random.choice(children)
    random.seed(1)
    tick_ai(rai, game_time=0.01)
    assert rai._current_child is expected


def test_random_ai_empty_is_done():
    """A RandomAI with no children completes immediately."""
    rai = RandomAI(ShipClass(), "R")
    status = tick_ai(rai, game_time=0.01)
    assert status == ArtificialIntelligence.US_DONE
    assert rai._status == ArtificialIntelligence.US_DONE


def test_random_ai_get_ais_returns_children():
    """GetAIs() accessor exposes the child list for an AI inspector."""
    rai = RandomAI(ShipClass(), "R")
    a = _make_plain(ShipClass(), _FakeLeaf())
    b = _make_plain(ShipClass(), _FakeLeaf())
    rai.AddAI(a); rai.AddAI(b)
    assert rai.GetAIs() == [a, b]
