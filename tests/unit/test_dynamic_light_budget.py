"""Per-category shares of the native dynamic-light cap.

set_dynamic_lights TRUNCATES to the cap -- it keeps the first N and silently
drops the rest -- so plain concatenation starves whichever category is last.
That is not theoretical: the death-fireball lights shipped concatenated last
and were invisible in a 50-ship engagement, because subsystem emitters alone
exceed the cap there.
"""
import pytest

from engine.host_loop import (
    _budgeted_dynamic_lights,
    _LIGHT_CAP,
    _LIGHT_BUDGET_EXPLOSIONS,
    _LIGHT_BUDGET_TORPEDOES,
    _LIGHT_BUDGET_EMITTERS,
)


def _lights(tag, n):
    return [{"tag": tag, "i": i} for i in range(n)]


def _count(out, tag):
    return sum(1 for e in out if e["tag"] == tag)


def test_budgets_fit_inside_the_cap():
    """The guarantees must be satisfiable simultaneously, or one category
    silently never receives its share."""
    total = (_LIGHT_BUDGET_EXPLOSIONS + _LIGHT_BUDGET_TORPEDOES
             + _LIGHT_BUDGET_EMITTERS)
    assert total <= _LIGHT_CAP


def test_never_exceeds_the_native_cap():
    out = _budgeted_dynamic_lights(_lights("x", 99), _lights("t", 99),
                                   _lights("e", 99))
    assert len(out) == _LIGHT_CAP


def test_explosions_survive_a_scene_that_floods_the_emitters():
    """THE regression this exists for: 50 ships' worth of emitters must not be
    able to push every explosion light out of the frame."""
    out = _budgeted_dynamic_lights(_lights("x", 4), _lights("t", 0),
                                   _lights("e", 200))
    assert _count(out, "x") == 4, "explosion lights were starved by emitters"
    assert len(out) == _LIGHT_CAP


def test_each_category_gets_its_guarantee_when_all_are_over_subscribed():
    out = _budgeted_dynamic_lights(_lights("x", 50), _lights("t", 50),
                                   _lights("e", 50))
    assert _count(out, "x") >= _LIGHT_BUDGET_EXPLOSIONS
    assert _count(out, "t") >= _LIGHT_BUDGET_TORPEDOES
    assert _count(out, "e") >= _LIGHT_BUDGET_EMITTERS


def test_a_quiet_frame_is_not_capped_at_the_emitter_guarantee():
    """Unused budget spills, so ordinary play is not made WORSE than plain
    truncation: 50 emitters and nothing else must all get through, even though
    the emitter guarantee is only 40."""
    n = _LIGHT_BUDGET_EMITTERS + 10
    assert n <= _LIGHT_CAP
    out = _budgeted_dynamic_lights([], [], _lights("e", n))
    assert _count(out, "e") == n


def test_nothing_is_dropped_when_everything_fits():
    out = _budgeted_dynamic_lights(_lights("x", 2), _lights("t", 3),
                                   _lights("e", 20))
    assert len(out) == 25


def test_the_spill_favours_explosions_over_emitters():
    """With room left over, the rarer and more dramatic source gets it."""
    out = _budgeted_dynamic_lights(_lights("x", 30), _lights("t", 0),
                                   _lights("e", 40))
    assert _count(out, "x") == 24, "explosions should take the spare slots"
    assert _count(out, "e") == 40


def test_empty_input_is_empty_output():
    assert _budgeted_dynamic_lights([], [], []) == []
