from engine.appc.ai import (
    ArtificialIntelligence, PlainAI, PriorityListAI, SequenceAI,
    ConditionalAI, PreprocessingAI, TGCondition,
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


def test_preprocessing_done_completes_pp():
    leaf = _FakeLeaf()
    child = _make_plain(ShipClass(), leaf)
    pp, inst = _make_pp(PreprocessingAI.PS_DONE, child)
    tick_ai(pp, game_time=0.01)
    assert leaf.calls == 0
    assert pp._status == ArtificialIntelligence.US_DONE
