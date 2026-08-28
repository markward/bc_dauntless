"""AI driver focus-loss lifecycle: a PreprocessingAI that drops off the active
dispatch path must receive LostFocus() and have its focus flags reset, so the
SDK cloak cadence (CloakShip.LostFocus -> StopCloaking) works. See
docs/superpowers/specs/2026-07-07-ai-focus-loss-lifecycle-design.md.
"""
from engine.appc.ai import (
    PreprocessingAI, PriorityListAI_Create, ArtificialIntelligence,
)
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass

US_ACTIVE = ArtificialIntelligence.US_ACTIVE
US_DORMANT = ArtificialIntelligence.US_DORMANT
PS_NORMAL = PreprocessingAI.PS_NORMAL
PS_SKIP_DORMANT = PreprocessingAI.PS_SKIP_DORMANT


# A node drops off the active path the way a real preprocessor does: its own
# Update returns dormant (SelectTarget returns PS_SKIP_DORMANT when it has no
# target). Poking `_status = US_DORMANT` externally is NOT how BC produces
# dormancy and no longer sticks -- the driver re-dispatches a due dormant
# PreprocessingAI, and a fixture whose Update returned PS_NORMAL would just
# reactivate. So the fixtures expose a settable `result` that Update returns.
class _WithLostFocus:
    def __init__(self):
        self.got = 0
        self.lost = 0
        self.result = PreprocessingAI.PS_NORMAL
    def GotFocus(self):
        self.got += 1
    def LostFocus(self):
        self.lost += 1
    def Update(self, dEndTime):
        return self.result


class _NoLostFocus:
    def __init__(self):
        self.got = 0
        self.result = PreprocessingAI.PS_NORMAL
    def GotFocus(self):
        self.got += 1
    def Update(self, dEndTime):
        return self.result


def _pp(inst, name):
    pp = PreprocessingAI(ShipClass(), name)
    pp.SetPreprocessingMethod(inst, "Update")
    return pp


def _list_with(a_pp, b_pp):
    pl = PriorityListAI_Create(None, "PL")
    pl.AddAI(a_pp, 0)   # a is higher priority (lower int)
    pl.AddAI(b_pp, 1)
    return pl


def test_lost_focus_when_node_drops_off_active_path():
    ia, ib = _WithLostFocus(), _WithLostFocus()
    a, b = _pp(ia, "A"), _pp(ib, "B")
    pl = _list_with(a, b)
    tick_ai(pl, 0.0)                     # a eligible -> a focused
    assert ia.got == 1 and ia.lost == 0
    ia.result = PS_SKIP_DORMANT          # a's Update now goes dormant
    tick_ai(pl, 1.0)                     # a drops -> a.LostFocus; b focused
    assert ia.lost == 1
    assert a._has_focus is False
    assert a.__dict__.get("_got_focus_called") is False


def test_regaining_focus_refires_got_focus():
    ia = _WithLostFocus()
    a, b = _pp(ia, "A"), _pp(_WithLostFocus(), "B")
    pl = _list_with(a, b)
    tick_ai(pl, 0.0)                     # a focused, got=1
    ia.result = PS_SKIP_DORMANT
    tick_ai(pl, 1.0)                     # a's Update -> dormant -> lost=1
    ia.result = PS_NORMAL
    tick_ai(pl, 2.0)                     # a re-probed (due) -> active -> got=2
    assert ia.got == 2
    assert ia.lost == 1


def test_node_staying_on_path_keeps_focus():
    ia = _WithLostFocus()
    a, b = _pp(ia, "A"), _pp(_WithLostFocus(), "B")
    pl = _list_with(a, b)
    tick_ai(pl, 0.0)
    tick_ai(pl, 1.0)
    tick_ai(pl, 2.0)
    assert ia.got == 1
    assert ia.lost == 0


def test_no_lost_focus_method_is_noop_but_resets_flags():
    ia = _NoLostFocus()
    a, b = _pp(ia, "A"), _pp(_WithLostFocus(), "B")
    pl = _list_with(a, b)
    tick_ai(pl, 0.0)
    ia.result = PS_SKIP_DORMANT
    tick_ai(pl, 1.0)                     # a drops; no LostFocus method -> no error
    assert a._has_focus is False
    assert a.__dict__.get("_got_focus_called") is False


def test_two_ships_focus_isolated():
    ia, ib = _WithLostFocus(), _WithLostFocus()
    a1, b1 = _pp(ia, "A1"), _pp(_WithLostFocus(), "B1")
    a2, b2 = _pp(ib, "A2"), _pp(_WithLostFocus(), "B2")
    pl1, pl2 = _list_with(a1, b1), _list_with(a2, b2)
    tick_ai(pl1, 0.0)
    tick_ai(pl2, 0.0)
    ia.result = PS_SKIP_DORMANT          # only ship1's A drops
    tick_ai(pl1, 1.0)
    tick_ai(pl2, 1.0)
    assert ia.lost == 1
    assert ib.lost == 0


# ── PS_SKIP_ACTIVE must not read as focus loss ──────────────────────────────
#
# A preprocessor returning PS_SKIP_ACTIVE means "I am handling this tick, do
# not run my child" (US_ACTIVE, child not run -- PreprocessingAI::Update's
# switch at 0x48eab1). The child has NOT left the active dispatch path; its
# parent is momentarily driving instead.
#
# Treating that as focus loss is what made restored collision avoidance switch
# combat off. AvoidObstacles sits ABOVE the attack tree in BC's own QuickBattleAI
# and returns PS_SKIP_ACTIVE for as long as a ship is evading. Measured in a
# 12-ship fight: three ships evaded for 250+ of 300 consecutive ticks -- so for
# five unbroken seconds their AlertLevel.LostFocus had restored the pre-combat
# alert level (shields down) and their FireScript.LostFocus had called
# StopFiring(). If BC dropped a ship's shields every time it dodged, dodging
# would be suicide.
#
# Focus only. Tree activation (SetActive/SetInactive, _reconcile_active) asks a
# different question -- "did dispatch reach this node" -- whose answer really is
# no, and conditions are edge-guarded and re-arm when the skip ends.

class _SkipActive:
    """A preprocessor that suppresses its child the way AvoidObstacles does."""
    def __init__(self):
        self.result = PreprocessingAI.PS_NORMAL
    def Update(self, dEndTime):
        return self.result


def _pp_containing(inst, name, child):
    pp = PreprocessingAI(ShipClass(), name)
    pp.SetPreprocessingMethod(inst, "Update")
    pp.SetContainedAI(child)
    return pp


def test_skip_active_does_not_cost_the_child_its_focus():
    guard = _SkipActive()
    child_inst = _WithLostFocus()
    child = _pp(child_inst, "Attack")
    root = _pp_containing(guard, "AvoidObstacles", child)

    tick_ai(root, 0.0)
    assert child_inst.got == 1 and child_inst.lost == 0
    assert child._has_focus is True

    guard.result = PreprocessingAI.PS_SKIP_ACTIVE
    tick_ai(root, 1.0)

    assert child_inst.lost == 0, (
        "a child suppressed for one tick by PS_SKIP_ACTIVE was told it had "
        "lost focus; AlertLevel.LostFocus drops shields and "
        "FireScript.LostFocus stops firing on that signal"
    )
    assert child._has_focus is True


def test_focus_survives_a_sustained_skip_and_no_refocus_churn():
    """The failure was a five-second run, not one tick -- and re-entry must not
    fire GotFocus again either, or AlertLevel re-runs its combat-entry side
    effects on every dodge."""
    guard = _SkipActive()
    child_inst = _WithLostFocus()
    child = _pp(child_inst, "Attack")
    root = _pp_containing(guard, "AvoidObstacles", child)

    tick_ai(root, 0.0)
    guard.result = PreprocessingAI.PS_SKIP_ACTIVE
    for t in range(1, 40):
        tick_ai(root, float(t))
    guard.result = PS_NORMAL
    tick_ai(root, 40.0)

    assert child_inst.lost == 0
    assert child_inst.got == 1


def test_a_child_that_really_leaves_the_path_still_loses_focus():
    """Guard against the fix becoming 'nobody ever loses focus'."""
    ia, ib = _WithLostFocus(), _WithLostFocus()
    a, b = _pp(ia, "A"), _pp(ib, "B")
    pl = _list_with(a, b)
    tick_ai(pl, 0.0)
    assert ia.got == 1
    ia.result = PS_SKIP_DORMANT
    tick_ai(pl, 1.0)
    assert ia.lost == 1
