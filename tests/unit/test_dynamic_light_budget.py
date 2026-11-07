"""Per-category shares of the native dynamic-light cap.

set_dynamic_lights TRUNCATES to the cap -- it keeps the first N and silently
drops the rest -- so plain concatenation starves whichever category is last.
That is not theoretical: the death-fireball lights shipped concatenated last
and were invisible in a 50-ship engagement, because subsystem emitters alone
exceed the cap there.

The blend itself is native (torpedo_feed.h budget_lights, behind
set_dynamic_lights_budgeted; no Python copy): its slicing is pinned by ctest
Budget.SlicingMatchesPython, and each intent case (explosions survive an
emitter flood, a quiet frame is not capped at its guarantee, the spill favours
explosions, ...) by a named Budget.* ctest in
native/tests/combat/torpedo_feed_test.cc. host_loop owns the knobs it reads.
"""
from engine.host_loop import (
    _LIGHT_CAP,
    _LIGHT_BUDGET_EXPLOSIONS,
    _LIGHT_BUDGET_TORPEDOES,
    _LIGHT_BUDGET_EMITTERS,
)


def test_budgets_fit_inside_the_cap():
    """The guarantees must be satisfiable simultaneously, or one category
    silently never receives its share."""
    total = (_LIGHT_BUDGET_EXPLOSIONS + _LIGHT_BUDGET_TORPEDOES
             + _LIGHT_BUDGET_EMITTERS)
    assert total <= _LIGHT_CAP
