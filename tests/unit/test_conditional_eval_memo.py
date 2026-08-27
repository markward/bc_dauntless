"""The ConditionalAI evaluation memo, and the gate that keeps it sound.

_refresh_conditional_status reuses an EvalFunc's answer when the condition
statuses are unchanged. Measured at 100 ships, 99.9% of refreshes are handed
identical statuses, so the call is almost always recomputing a known answer.

This is a correctness-preserving simplification, NOT a measured speed-up -- see
the sizing note in ai_driver.py. These tests therefore guard the thing that
actually matters about it: that it never returns a stale answer.

Soundness needs the EvalFunc to depend on nothing but its arguments. A corpus
scan found 450 of 458 SDK/engine evaluation functions pure; the 8 exceptions
are AI/Compound/ChainFollow.py, whose EvalFuncs read a module-level global
`iIndex` that CreateAI assigns. So the memo is gated per function, and both
halves are covered here: that it memoises, and that the gate declines what it
must decline.
"""
import pytest

from engine.appc.ai_driver import (_memoisable_evalfunc, _eval_conditional,
                                   _refresh_conditional_status,
                                   US_ACTIVE, US_DORMANT, US_DONE)
from engine.appc.ai import ConditionalAI


class _Cond:
    """Stands in for a ConditionScript: a status somebody else updates."""
    def __init__(self, status=0):
        self.status = status

    def GetStatus(self):
        return self.status

    def AddHandler(self, _owner):
        # ConditionalAI.AddCondition subscribes; a real ConditionScript pushes
        # status changes through this. These tests drive .status directly, so
        # the subscription is a no-op -- but it has to EXIST, because the memo
        # is precisely about what happens between those pushes.
        pass


def _conditional(conds, fn):
    ai = ConditionalAI()
    for c in conds:
        ai.AddCondition(c)
    ai.SetEvaluationFunction(fn)
    return ai


# ── the gate ────────────────────────────────────────────────────────────────

def test_a_pure_evalfunc_is_memoisable():
    """The shape 450 of 458 SDK functions have: reads only its parameters."""
    def EvalFunc(a, b):
        if a and b:
            return 1
        return 2
    assert _memoisable_evalfunc(EvalFunc) is True


def test_an_evalfunc_reading_a_module_global_is_declined():
    """The ChainFollow shape. `iIndex` is a module global CreateAI writes, so
    identical condition statuses do NOT imply an identical answer."""
    src = (
        "iIndex = 0\n"
        "def EvalFunc(bShipExists):\n"
        "    if (iIndex <= 7) or not bShipExists:\n"
        "        return 2\n"
        "    return 1\n"
    )
    ns = {}
    exec(compile(src, "<chainfollow-like>", "exec"), ns)
    assert _memoisable_evalfunc(ns["EvalFunc"]) is False


def test_an_evalfunc_closing_over_a_free_variable_is_declined():
    def make(threshold):
        def EvalFunc(a):
            return 1 if a > threshold else 2
        return EvalFunc
    assert _memoisable_evalfunc(make(3)) is False


def test_reading_App_is_still_memoisable():
    """Every SDK EvalFunc opens with App.ArtificialIntelligence.US_ACTIVE and
    friends. If App disqualified a function the gate would decline all 458 and
    the memo would silently never fire -- which is the failure mode that looks
    exactly like success."""
    src = (
        "import App\n"
        "def EvalFunc(a):\n"
        "    ACTIVE = App.ArtificialIntelligence.US_ACTIVE\n"
        "    DORMANT = App.ArtificialIntelligence.US_DORMANT\n"
        "    return ACTIVE if a else DORMANT\n"
    )
    ns = {}
    exec(compile(src, "<sdk-like>", "exec"), ns)
    assert _memoisable_evalfunc(ns["EvalFunc"]) is True


def test_a_builtin_is_declined_rather_than_crashing():
    assert _memoisable_evalfunc(len) is False
    assert _memoisable_evalfunc(None) is False


# ── the memo ────────────────────────────────────────────────────────────────
#
# HOW TO COUNT CALLS WITHOUT DESTROYING THE THING UNDER TEST
#
# The obvious spelling --
#     calls = []
#     def EvalFunc(a, b):
#         calls.append((a, b))
# -- makes EvalFunc a CLOSURE over `calls`, which _memoisable_evalfunc
# correctly declines. The counter would then guarantee the function is never
# memoised, and every "it was memoised" assertion below would be measuring the
# un-memoised path while appearing to pass.
#
# A mutable default argument is neither a free variable nor a module global, so
# a function carrying one still passes the gate. `args` is the condition list,
# which is shorter than the signature, so the default is never overwritten.
#
# The US_* constants are bound as defaults for the same reason: read directly
# they are module globals of THIS file and the gate declines them too. Real SDK
# EvalFuncs reach them as App.ArtificialIntelligence.US_ACTIVE -- an attribute
# chain, so only `App` is a global -- which is why the corpus passes.

def test_unchanged_conditions_do_not_re_run_the_evalfunc():
    def EvalFunc(a, b, calls=[], ACTIVE=US_ACTIVE, DORMANT=US_DORMANT):
        calls.append((a, b))
        return ACTIVE if (a and b) else DORMANT

    assert _memoisable_evalfunc(EvalFunc), "the counter defeated the gate"
    c1, c2 = _Cond(1), _Cond(1)
    ai = _conditional([c1, c2], EvalFunc)

    for _ in range(20):
        _refresh_conditional_status(ai)
    assert ai._status == US_ACTIVE
    n = len(EvalFunc.__defaults__[0])
    assert n == 1, "EvalFunc ran %d times for one unchanging input" % n


def test_a_changed_condition_re_runs_it_and_changes_the_status():
    def EvalFunc(a, b, calls=[], ACTIVE=US_ACTIVE, DORMANT=US_DORMANT):
        calls.append((a, b))
        return ACTIVE if (a and b) else DORMANT

    assert _memoisable_evalfunc(EvalFunc)
    calls = EvalFunc.__defaults__[0]
    c1, c2 = _Cond(1), _Cond(1)
    ai = _conditional([c1, c2], EvalFunc)

    _refresh_conditional_status(ai)
    _refresh_conditional_status(ai)     # settle, so the counts below are memo hits
    assert ai._status == US_ACTIVE
    assert len(calls) == 1

    c2.status = 0                      # the event-driven update the memo must see
    _refresh_conditional_status(ai)
    assert ai._status == US_DORMANT
    assert len(calls) == 2
    _refresh_conditional_status(ai)
    assert len(calls) == 2, "re-ran for an input it had just seen"

    c2.status = 1                      # ...and back again
    _refresh_conditional_status(ai)
    assert ai._status == US_ACTIVE
    assert len(calls) == 3


def test_an_impure_evalfunc_is_re_run_every_time():
    """The gate has to actually bite: a declined function must never be
    memoised, or ChainFollow strands on a stale answer."""
    src = (
        "iIndex = 0\n"
        "def EvalFunc(a):\n"
        "    return 1 if (iIndex > 7 and a) else 2\n"
    )
    ns = {}
    exec(compile(src, "<chainfollow-like>", "exec"), ns)
    fn = ns["EvalFunc"]
    assert _memoisable_evalfunc(fn) is False

    c = _Cond(1)
    ai = _conditional([c], fn)
    _refresh_conditional_status(ai)
    assert ai._status == 2
    ns["iIndex"] = 9                   # the global moves; conditions do not
    _refresh_conditional_status(ai)
    assert ai._status == 1, "memoised an impure EvalFunc and went stale"


def test_swapping_the_evaluation_function_invalidates_the_memo():
    c = _Cond(1)
    # Memoisable spellings, so the swap is tested against a LIVE cache entry.
    ai = _conditional([c], lambda a, ACTIVE=US_ACTIVE: ACTIVE)
    assert _memoisable_evalfunc(ai._evaluation_function)
    _refresh_conditional_status(ai)
    _refresh_conditional_status(ai)   # settle, so there is a cache entry to invalidate
    assert ai._status == US_ACTIVE
    ai.SetEvaluationFunction(lambda a, DORMANT=US_DORMANT: DORMANT)
    _refresh_conditional_status(ai)
    assert ai._status == US_DORMANT


def test_the_contained_done_fold_is_not_cached():
    """The fold reads _contained_ai._status, which is NOT part of the key, so
    caching it would let a finished child stay invisible forever. This is the
    subtle half: the memo stores the EvalFunc's own answer, pre-fold."""
    class _Child:
        _status = US_ACTIVE

    child = _Child()
    c = _Cond(1)
    # MUST be memoisable, or this test is vacuous: a declined EvalFunc is
    # recomputed every call, so a fold wrongly moved INSIDE the memo would
    # still produce the right answer here and the test would pass. Verified by
    # calibration -- with a plain `lambda a: US_ACTIVE` (declined, because
    # US_ACTIVE is a module global of this file) moving the fold into
    # _eval_conditional broke nothing across 208 tests.
    ai = _conditional([c], lambda a, ACTIVE=US_ACTIVE: ACTIVE)
    assert _memoisable_evalfunc(ai._evaluation_function), (
        "the EvalFunc is declined, so the cached path is never taken and this "
        "test cannot see the defect it exists to catch")
    ai._contained_ai = child

    _refresh_conditional_status(ai)
    _refresh_conditional_status(ai)   # settle: the next call must be a memo HIT
    assert ai._status == US_ACTIVE

    child._status = US_DONE            # changes with no condition change at all
    _refresh_conditional_status(ai)
    assert ai._status == US_DONE, "the DONE fold was cached along with the eval"


def test_a_raising_evalfunc_is_dormant_and_that_answer_is_reusable():
    def EvalFunc(a, calls=[]):
        calls.append(a)
        raise RuntimeError("boom")

    c = _Cond(1)
    ai = _conditional([c], EvalFunc)
    _refresh_conditional_status(ai)
    assert ai._status == US_DORMANT
    _refresh_conditional_status(ai)
    assert ai._status == US_DORMANT
    n = len(EvalFunc.__defaults__[0])
    assert n == 1, "a raising EvalFunc is re-entered every tick (%d times)" % n


def test_none_return_is_dormant_and_reusable():
    def EvalFunc(a, calls=[]):
        calls.append(a)
        return None

    ai = _conditional([_Cond(1)], EvalFunc)
    _refresh_conditional_status(ai)
    _refresh_conditional_status(ai)
    assert ai._status == US_DORMANT
    assert len(EvalFunc.__defaults__[0]) == 1
