"""PlainAI leaves get GotFocus() on entering the active path and LostFocus()
on leaving it — not just PreprocessingAI nodes.

Four shipped leaf scripts define these, and every body is cleanup that MUST run:
AI/PlainAI/Warp.py:217 (stop towing + RE-ENABLE COLLISIONS it disabled),
RunAction.py:50 (abort the action), Intercept.py:70 (StopInSystemWarp),
StarbaseAttack.py:54/58 (start/stop firing).
"""
from engine.appc.ai import (
    ArtificialIntelligence, PlainAI_Create, PriorityListAI_Create,
)
from engine.appc.ai_driver import tick_ai


class _Leaf:
    """Stand-in for a PlainAI script: records the focus lifecycle."""
    def __init__(self, status=ArtificialIntelligence.US_ACTIVE):
        self.got = 0
        self.lost = 0
        self._status = status

    def GotFocus(self):
        self.got += 1

    def LostFocus(self):
        self.lost += 1

    def GetNextUpdateTime(self):
        return 0.0

    def Update(self):
        return self._status


def test_plain_ai_gets_got_focus_once_on_entering_the_path():
    ai = PlainAI_Create(None, "leaf")
    leaf = _Leaf()
    ai._script_instance = leaf

    tick_ai(ai, 0.0)
    tick_ai(ai, 0.1)
    assert leaf.got == 1, "GotFocus fires once, not every tick"
    assert leaf.lost == 0


def test_plain_ai_gets_lost_focus_when_a_sibling_takes_over():
    """A priority list whose high-priority child goes DORMANT hands focus to the
    next child; the incumbent must be told it lost focus."""
    plist = PriorityListAI_Create(None, "root")

    hi = PlainAI_Create(None, "hi")
    hi_leaf = _Leaf(status=ArtificialIntelligence.US_ACTIVE)
    hi._script_instance = hi_leaf

    lo = PlainAI_Create(None, "lo")
    lo_leaf = _Leaf(status=ArtificialIntelligence.US_ACTIVE)
    lo._script_instance = lo_leaf

    plist.AddAI(hi, 0)
    plist.AddAI(lo, 1)

    tick_ai(plist, 0.0)
    assert hi_leaf.got == 1
    assert lo_leaf.got == 0

    # The high-priority leaf goes dormant: focus must move to `lo`, and `hi`
    # must get LostFocus().
    hi_leaf._status = ArtificialIntelligence.US_DORMANT
    tick_ai(plist, 0.1)          # hi reports DORMANT and is skipped from here on
    tick_ai(plist, 0.2)          # lo now runs

    assert lo_leaf.got == 1, "the new incumbent gains focus"
    assert hi_leaf.lost == 1, "the displaced leaf loses focus exactly once"
