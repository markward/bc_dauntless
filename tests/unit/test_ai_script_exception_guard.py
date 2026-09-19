"""A leaf or preprocessor that raises must not take the whole AI tick down.

Spec #9: nothing between the SDK script and host_loop's loop.tick() caught an
exception, so one Disable order (FireScript.GetChildTargets, spec #6) or
Defend.py's GetConditionScript would end the sim for every ship. BC's
embedded interpreter reports and continues."""
import App
from engine.appc.ai import PlainAI_Create, PreprocessingAI_Create, ArtificialIntelligence, PreprocessingAI
from engine.appc.ai_driver import tick_ai, tick_all_ai
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


class _Boom:
    def __init__(self): self.calls = 0
    def Update(self):
        self.calls += 1
        raise RuntimeError("scripted failure")


class _BoomPreprocessor:
    def GetNextUpdateTime(self): return 0.0
    def Update(self, dEndTime):
        raise AttributeError("GetChildTargets")


def _ship(pSet, name):
    s = ShipClass(); s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    pSet.AddObjectToSet(s, name)
    return s


def test_raising_plain_ai_reports_active_and_records_the_error():
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = _ship(pSet, "A")
    plain = PlainAI_Create(ship, "Boom")
    plain._script_instance = _Boom()      # bypass SetScriptModule: synthetic leaf
    status = tick_ai(plain, 0.0)
    assert status == ArtificialIntelligence.US_ACTIVE
    assert plain._last_script_error[0] == "RuntimeError"


def test_raising_preprocessor_does_not_stop_the_other_ship():
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    bad = _ship(pSet, "Bad"); good = _ship(pSet, "Good")
    pp = PreprocessingAI_Create(bad, "PP")
    pp.SetPreprocessingMethod(_BoomPreprocessor(), "Update")
    bad.SetAI(pp)
    ticked = []
    class _Counter:
        def Update(self): ticked.append(1); return ArtificialIntelligence.US_ACTIVE
    plain = PlainAI_Create(good, "Count"); plain._script_instance = _Counter()
    good.SetAI(plain)

    tick_all_ai(0.0)          # must not raise
    assert ticked, "the healthy ship was never ticked after the bad one raised"
    assert pp._last_script_error[0] == "AttributeError"
