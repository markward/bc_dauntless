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


class _WithLostFocus:
    def __init__(self):
        self.got = 0
        self.lost = 0
    def GotFocus(self):
        self.got += 1
    def LostFocus(self):
        self.lost += 1
    def Update(self, dEndTime):
        return PreprocessingAI.PS_NORMAL


class _NoLostFocus:
    def __init__(self):
        self.got = 0
    def GotFocus(self):
        self.got += 1
    def Update(self, dEndTime):
        return PreprocessingAI.PS_NORMAL


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
    a._status = US_DORMANT               # a no longer eligible
    tick_ai(pl, 1.0)                     # b focused, a drops -> a.LostFocus
    assert ia.lost == 1
    assert a._has_focus is False
    assert a.__dict__.get("_got_focus_called") is False


def test_regaining_focus_refires_got_focus():
    ia = _WithLostFocus()
    a, b = _pp(ia, "A"), _pp(_WithLostFocus(), "B")
    pl = _list_with(a, b)
    tick_ai(pl, 0.0)                     # a focused, got=1
    a._status = US_DORMANT
    tick_ai(pl, 1.0)                     # a drops -> lost=1
    a._status = US_ACTIVE
    tick_ai(pl, 2.0)                     # a re-focused -> got=2
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
    a._status = US_DORMANT
    tick_ai(pl, 1.0)                     # a drops; no LostFocus -> no error
    assert a._has_focus is False
    assert a.__dict__.get("_got_focus_called") is False


def test_two_ships_focus_isolated():
    ia, ib = _WithLostFocus(), _WithLostFocus()
    a1, b1 = _pp(ia, "A1"), _pp(_WithLostFocus(), "B1")
    a2, b2 = _pp(ib, "A2"), _pp(_WithLostFocus(), "B2")
    pl1, pl2 = _list_with(a1, b1), _list_with(a2, b2)
    tick_ai(pl1, 0.0)
    tick_ai(pl2, 0.0)
    a1._status = US_DORMANT              # only ship1's A drops
    tick_ai(pl1, 1.0)
    tick_ai(pl2, 1.0)
    assert ia.lost == 1
    assert ib.lost == 0
