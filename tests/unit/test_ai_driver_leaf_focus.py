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


def test_got_focus_latch_not_set_when_ticked_before_script_module_lands():
    """A PlainAI ticked before SetScriptModule() has _script_instance is None
    on that tick. _dispatch_got_focus must not latch "GotFocus already fired"
    in that case -- else the real script's GotFocus never runs once the
    module lands. Not reachable through the standard SDK wiring order
    (PlainAI_Create -> SetScriptModule before the tree runs), so this is a
    robustness fix, not a live-game regression."""
    ai = PlainAI_Create(None, "leaf")
    assert ai._script_instance is None

    tick_ai(ai, 0.0)  # ticked with no script instance yet
    assert ai.__dict__.get("_got_focus_called", False) is False, (
        "must not latch GotFocus-fired when there was no instance to fire it on"
    )

    leaf = _Leaf()
    ai._script_instance = leaf
    tick_ai(ai, 0.1)  # module has now landed
    assert leaf.got == 1, "GotFocus must fire once the script instance lands"


class _FalsyLeaf(_Leaf):
    """A script instance that is falsy in a boolean context (defines
    __len__ returning 0) -- must still be picked by _focus_instance_of."""
    def __len__(self):
        return 0


def test_focus_instance_of_picks_a_falsy_script_instance():
    """_focus_instance_of must use an explicit `is not None` check between
    _script_instance and _preprocessing_instance, not `or` -- an `or` would
    fall through to the (absent, None) _preprocessing_instance slot whenever
    the script instance itself happens to be falsy, silently swallowing
    GotFocus/LostFocus."""
    ai = PlainAI_Create(None, "leaf")
    leaf = _FalsyLeaf()
    assert not leaf  # sanity: genuinely falsy
    ai._script_instance = leaf

    tick_ai(ai, 0.0)
    assert leaf.got == 1, "GotFocus must fire even though the script instance is falsy"


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
