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

from engine.appc import ai_driver
from tests.helpers import ai_walker_oracle as oracle
from engine.appc.ai_driver import (_memoisable_evalfunc,
                                   US_ACTIVE, US_DORMANT, US_DONE)
from engine.appc.ai import ConditionalAI, TGCondition


def _eval_conditional(*args):
    """Resolved at call time: the walker fixture may have installed the
    oracle's over ai_driver's."""
    return ai_driver._eval_conditional(*args)


def _refresh_conditional_status(ai):
    return ai_driver._refresh_conditional_status(ai)


@pytest.fixture(autouse=True, params=["python", "native"])
def walker(request, monkeypatch):
    """Every test here runs against both condition evaluations: the frozen
    Python walker's (tests/helpers/ai_walker_oracle.py, installed over
    ai_driver) and the native one (aitree.cc)."""
    if request.param == "python":
        oracle.install(monkeypatch)
    return request.param


def _native_counts():
    import _dauntless_host
    return tuple(_dauntless_host.aitree_conditional_counts())


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


def test_a_raising_evalfunc_is_retried_rather_than_pinned_dormant():
    """An EXCEPTION is not a pure function of the arguments, so it is the one
    answer the memo must not keep.

    The memo's whole soundness argument is "same arguments => same answer", and
    that holds for what an EvalFunc RETURNS. It does not hold for what it
    raises: a condition script whose target has just been destroyed, or whose
    GetStatus momentarily hands back something unindexable, raises once and
    works thereafter. Caching US_DORMANT for that would pin the branch dormant
    for as long as the conditions hold steady -- 99.9% of ticks -- and the
    pre-memo code retried every tick.

    So the exception path deliberately does not write the cache. The cost is one
    call per tick for a function that is failing anyway.
    """
    def EvalFunc(a, calls=[], ACTIVE=US_ACTIVE):
        calls.append(a)
        if len(calls) < 3:
            raise RuntimeError("boom")     # transient, as a real one would be
        return ACTIVE

    c = _Cond(1)
    ai = _conditional([c], EvalFunc)
    _refresh_conditional_status(ai)
    assert ai._status == US_DORMANT
    _refresh_conditional_status(ai)
    assert ai._status == US_DORMANT
    _refresh_conditional_status(ai)
    assert ai._status == US_ACTIVE, (
        "the EvalFunc stopped raising but the memo kept serving its cached "
        "failure; the branch is dormant forever")
    assert len(EvalFunc.__defaults__[0]) == 3


def test_none_return_is_dormant_and_reusable():
    """None IS a return value, so purity applies to it and it is memoised --
    unlike the raising case above, which deliberately is not."""
    def EvalFunc(a, calls=[]):
        calls.append(a)
        return None

    ai = _conditional([_Cond(1)], EvalFunc)
    _refresh_conditional_status(ai)
    _refresh_conditional_status(ai)
    assert ai._status == US_DORMANT
    assert len(EvalFunc.__defaults__[0]) == 1


def test_the_memoisable_verdict_is_re_taken_when_the_evalfunc_is_swapped():
    """The verdict is per FUNCTION, and SetEvaluationFunction can change it.

    A declined function leaves the cache empty, so a re-check condition written
    as "the cached entry names a different function" can never fire -- there is
    no cached entry. The node would then carry `_evalfn_memoisable = False`
    forever and the replacement function, however pure, is never memoised.
    Lost saving only, never a wrong answer, which is why nothing else here
    would notice.
    """
    src = "iIndex = 0\ndef EvalFunc(a):\n    return 1 if iIndex else 2\n"
    ns = {}
    exec(compile(src, "<chainfollow-like>", "exec"), ns)      # noqa: S102
    declined = ns["EvalFunc"]
    assert _memoisable_evalfunc(declined) is False

    ai = _conditional([_Cond(1)], declined)
    _refresh_conditional_status(ai)
    _refresh_conditional_status(ai)

    def Pure(a, calls=[], ACTIVE=US_ACTIVE):
        calls.append(a)
        return ACTIVE

    assert _memoisable_evalfunc(Pure) is True
    ai.SetEvaluationFunction(Pure)
    for _ in range(5):
        _refresh_conditional_status(ai)
    assert ai._status == US_ACTIVE
    n = len(Pure.__defaults__[0])
    assert n == 1, (
        "the replacement EvalFunc ran %d times for one unchanging input -- the "
        "memoisable verdict stayed stuck on the previous function's" % n)


def test_a_stub_condition_status_is_never_written_into_the_memo_key():
    """The key comparison is the one `==` among these caches, and _Stub.__eq__
    (engine/core/ids.py) returns True for ANY other stub. So a condition whose
    GetStatus fell through to TGObject.__getattr__ would make every later key
    compare equal to the cached one and pin the memo permanently.

    Theoretical today -- ConditionScript always returns a real int -- but it is
    precisely the shape docs/stub_heatmap.md exists for, and the cheap fix is to
    refuse to build a key out of anything but a scalar. That also retires the
    general hazard: no object with a sloppy __eq__ can enter the key.
    """
    from engine.core.ids import _Stub

    class _StubCond:
        def GetStatus(self):
            return _Stub("GetStatus", "ConditionScript")

        def AddHandler(self, _owner):
            pass

    def EvalFunc(a, ACTIVE=US_ACTIVE):
        return ACTIVE

    assert _memoisable_evalfunc(EvalFunc)
    ai = _conditional([_StubCond()], EvalFunc)
    _refresh_conditional_status(ai)
    _refresh_conditional_status(ai)
    assert "_evalfn_cache" not in ai.__dict__, (
        "a _Stub was written into the memo key; every later key will compare "
        "equal to it and the node's status is frozen")


def test_scalar_condition_statuses_still_reach_the_memo():
    """Calibration for the guard above: it must not decline the real world.
    Every ConditionScript returns a plain int, so the memo has to keep firing."""
    def EvalFunc(a, b, calls=[], ACTIVE=US_ACTIVE):
        calls.append((a, b))
        return ACTIVE

    ai = _conditional([_Cond(1), _Cond(0)], EvalFunc)
    for _ in range(5):
        _refresh_conditional_status(ai)
    assert len(EvalFunc.__defaults__[0]) == 1, "the guard declined a plain int"


def test_a_global_read_hidden_in_a_nested_function_is_declined():
    """The gate inspects fn.__code__.co_names -- but a lambda or nested def
    inside the EvalFunc compiles to its OWN code object, so its LOAD_GLOBALs
    never appear in the outer co_names. Such a function reads live module state
    while presenting as pure, and the memo would then pin its first answer
    forever: the ChainFollow-shaped stall the gate exists to prevent.

    No shipped SDK EvalFunc nests a function today, which is exactly why this
    needs a test -- the corpus cannot fail it for us.
    """
    src = (
        "GLOB = 1\n"
        "def outer(a, b):\n"
        "    inner = lambda: GLOB\n"      # global read, hidden one level down
        "    return 1 if inner() else 2\n"
    )
    ns = {}
    exec(compile(src, "<nested>", "exec"), ns)          # noqa: S102
    assert not _memoisable_evalfunc(ns["outer"]), (
        "a global read inside a nested code object was not seen by the gate")


def test_a_global_read_inside_a_nested_def_is_declined():
    """Same hole, reached through `def` rather than `lambda`, and one level
    deeper -- the walk has to recurse, not just look one level down."""
    src = (
        "GLOB = 1\n"
        "def outer(a, b):\n"
        "    def mid():\n"
        "        def leaf():\n"
        "            return GLOB\n"
        "        return leaf()\n"
        "    return 1 if mid() else 2\n"
    )
    ns = {}
    exec(compile(src, "<nested>", "exec"), ns)          # noqa: S102
    assert not _memoisable_evalfunc(ns["outer"])


def test_a_nested_function_touching_nothing_global_is_still_admitted():
    """The recursion must not decline everything it walks into -- a nested
    helper that reads only its arguments leaves the function pure."""
    src = (
        "def outer(a, b):\n"
        "    add = lambda x, y: x + y\n"
        "    return add(a, b)\n"
    )
    ns = {}
    exec(compile(src, "<nested>", "exec"), ns)          # noqa: S102
    assert _memoisable_evalfunc(ns["outer"])


# ── condition reads and the rules around the memo (both walkers) ─────────────

def test_an_evalfunc_raising_a_base_exception_propagates():
    """`except Exception` is the catch: a BaseException that is not an
    Exception (KeyboardInterrupt, SystemExit) escapes, and nothing is cached."""
    class Stop(BaseException):
        pass

    def EvalFunc(a, Stop=Stop):
        raise Stop()

    ai = _conditional([_Cond(1)], EvalFunc)
    ai._status = US_ACTIVE
    with pytest.raises(Stop):
        _refresh_conditional_status(ai)
    assert ai._status == US_ACTIVE
    assert "_evalfn_cache" not in ai.__dict__
    assert "_evalfn_memoisable" not in ai.__dict__


def test_an_unparseable_status_escapes_int():
    """`int(status)` is outside the try: a value it rejects raises."""
    ai = _conditional([_Cond(1)], lambda a: "busy")
    with pytest.raises(ValueError):
        _refresh_conditional_status(ai)


def test_a_condition_class_with_its_own_get_status_is_called(walker):
    """A TGCondition subclass overriding GetStatus is CALLED, in condition
    order, by both walkers (natively only stock TGCondition.GetStatus is read
    directly)."""
    order = []

    class Own(TGCondition):
        def __init__(self, tag, value):
            super().__init__()
            self.tag, self.value = tag, value

        def GetStatus(self):
            order.append(self.tag)
            return self.value

    stock = TGCondition()
    stock.SetStatus(1)
    a, b = Own("a", 1), Own("b", 0)
    seen = []

    def EvalFunc(x, y, z, seen=seen):
        seen.append((x, y, z))
        return US_ACTIVE if (x and y and not z) else US_DORMANT

    ai = _conditional([a, stock, b], EvalFunc)
    before = _native_counts()
    _refresh_conditional_status(ai)
    assert order == ["a", "b"]
    assert seen == [(1, 1, 0)]
    assert ai._status == US_ACTIVE
    reads = _native_counts()[1] - before[1]
    assert reads == (1 if walker == "native" else 0), reads


def test_an_instance_shadowing_get_status_is_called():
    """An instance attribute named GetStatus shadows the class's, so it is what
    `c.GetStatus()` calls -- the stock read must not be taken for it."""
    c = TGCondition()
    c.SetStatus(0)
    c.GetStatus = lambda: 1
    ai = _conditional([c], lambda a, ACTIVE=US_ACTIVE, DORMANT=US_DORMANT:
                      ACTIVE if a else DORMANT)
    _refresh_conditional_status(ai)
    assert ai._status == US_ACTIVE


def test_a_class_level_patch_of_get_status_is_called(monkeypatch):
    """TGCondition.GetStatus replaced on the class: no longer the stock body,
    so it is called (the native stock check compares against the function
    taken at import, not whatever the class holds now)."""
    c = TGCondition()
    c.SetStatus(0)
    monkeypatch.setattr(TGCondition, "GetStatus", lambda self: 7)
    seen = []
    ai = _conditional([c], lambda a, seen=seen: seen.append(a) or US_ACTIVE)
    _refresh_conditional_status(ai)
    assert seen == [7]


def test_a_status_written_directly_is_seen(walker):
    """A test (or an SDK script reaching past SetStatus) writes `_status`
    directly: no handler runs and no event is posted, and the next refresh
    still sees it. Natively that is the direct read of a stock condition."""
    c = TGCondition()

    def EvalFunc(a, calls=[], ACTIVE=US_ACTIVE, DORMANT=US_DORMANT):
        calls.append(a)
        return ACTIVE if a else DORMANT

    ai = _conditional([c], EvalFunc)
    before = _native_counts()
    _refresh_conditional_status(ai)
    assert ai._status == US_DORMANT
    c._status = 3
    _refresh_conditional_status(ai)
    assert ai._status == US_ACTIVE
    _refresh_conditional_status(ai)              # memo hit on (3,)
    assert EvalFunc.__defaults__[0] == [0, 3]
    after = _native_counts()
    if walker == "native":
        assert after[0] - before[0] == 3 and after[1] - before[1] == 3
    else:
        assert after == before


@pytest.mark.parametrize("statuses, expected", [
    ([0, 0], US_DORMANT), ([0, 2], US_ACTIVE), ([-1], US_ACTIVE),
    ([0], US_DORMANT), ([0.0, 0], US_DORMANT), ([False, True], US_ACTIVE),
])
def test_without_an_evalfunc_any_non_zero_condition_is_active(statuses,
                                                              expected):
    ai = ConditionalAI()
    for v in statuses:
        ai.AddCondition(_Cond(v))
    ai._status = 99
    _refresh_conditional_status(ai)
    assert ai._status == expected


def test_without_an_evalfunc_any_stops_at_the_first_non_zero():
    """`any(c.GetStatus() != 0 ...)` short-circuits: conditions after the
    first non-zero one are not read."""
    order = []

    class Probe(_Cond):
        def __init__(self, tag, status):
            super().__init__(status)
            self.tag = tag

        def GetStatus(self):
            order.append(self.tag)
            return self.status

    ai = ConditionalAI()
    for tag, v in (("a", 0), ("b", 1), ("c", 1)):
        ai.AddCondition(Probe(tag, v))
    _refresh_conditional_status(ai)
    assert order == ["a", "b"]
    assert ai._status == US_ACTIVE


def test_without_conditions_or_evalfunc_the_status_is_left_alone():
    ai = ConditionalAI()
    ai._status = 42
    _refresh_conditional_status(ai)
    assert ai._status == 42


def test_the_done_fold_needs_an_active_evaluation():
    """The fold only turns ACTIVE into DONE: a DORMANT answer stays DORMANT
    even with a finished contained AI."""
    class _Child:
        _status = US_DONE

    ai = _conditional([_Cond(0)], lambda a, ACTIVE=US_ACTIVE,
                      DORMANT=US_DORMANT: ACTIVE if a else DORMANT)
    ai._contained_ai = _Child()
    _refresh_conditional_status(ai)
    assert ai._status == US_DORMANT


def test_the_memo_key_includes_the_function_args_and_answer():
    """The cache entry is `(fn, tuple(args), status)`: the very function, a
    tuple of the read statuses, and the pre-fold answer."""
    def EvalFunc(a, b, ACTIVE=US_ACTIVE):
        return ACTIVE

    ai = _conditional([_Cond(1), _Cond(0)], EvalFunc)
    _refresh_conditional_status(ai)
    fn, key, status = ai.__dict__["_evalfn_cache"]
    assert fn is EvalFunc and key == (1, 0) and type(key) is tuple
    assert status == US_ACTIVE and type(status) is int
    assert ai.__dict__["_evalfn_memoisable"] == (EvalFunc, True)


def test_a_cached_answer_for_other_args_is_not_reused():
    """A cache entry for the same function but different statuses is a miss
    (the key compares `==`, element-wise)."""
    calls = []

    def EvalFunc(a, calls=calls, ACTIVE=US_ACTIVE, DORMANT=US_DORMANT):
        calls.append(a)
        return ACTIVE if a else DORMANT

    c = _Cond(1)
    ai = _conditional([c], EvalFunc)
    ai.__dict__["_evalfn_cache"] = (EvalFunc, (0,), US_DORMANT)
    _refresh_conditional_status(ai)
    assert calls == [1] and ai._status == US_ACTIVE
    ai.__dict__["_evalfn_cache"] = (EvalFunc, (1.0,), 77)   # 1 == 1.0: a hit
    _refresh_conditional_status(ai)
    assert calls == [1] and ai._status == 77


def test_eval_conditional_returns_the_pre_fold_answer():
    """_eval_conditional itself, as _tick_conditional calls it."""
    def EvalFunc(a, ACTIVE=US_ACTIVE):
        return True
    ai = _conditional([_Cond(1)], EvalFunc)
    status = _eval_conditional(ai, EvalFunc, [1])
    assert status == 1 and type(status) is int
    assert _eval_conditional(ai, EvalFunc, [1]) == 1


def test_a_patched_eval_conditional_is_called_by_the_refresh(monkeypatch):
    """The refresh calls _eval_conditional through the module, so a patch
    is honoured by both walkers."""
    seen = []

    def fake(ai, fn, args):
        seen.append(list(args))
        return US_DONE
    monkeypatch.setattr(ai_driver, "_eval_conditional", fake)
    ai = _conditional([_Cond(1), _Cond(0)], lambda a, b: US_ACTIVE)
    _refresh_conditional_status(ai)
    assert seen == [[1, 0]] and ai._status == US_DONE


def test_tick_conditional_reads_and_evaluates_through_s2(walker):
    """_tick_conditional's status reads: the EvalFunc path and the
    any-non-zero path, with the contained AI ticked only when ACTIVE."""
    from engine.appc.ai_driver import _tick_conditional

    class _Child:
        def __init__(self):
            self._status = US_ACTIVE

    ticked = []
    monkey_child = _Child()
    c = TGCondition()
    ai = _conditional([c], lambda a, ACTIVE=US_ACTIVE, DORMANT=US_DORMANT:
                      ACTIVE if a else DORMANT)
    ai._contained_ai = monkey_child
    real_tick = ai_driver.tick_ai
    ai_driver.tick_ai = lambda node, t: ticked.append(node) or US_ACTIVE
    try:
        before = _native_counts()
        assert _tick_conditional(ai, 0.0) == US_DORMANT and ticked == []
        c._status = 1
        assert _tick_conditional(ai, 0.0) == US_ACTIVE and ticked == [
            monkey_child]
        bare = ConditionalAI()
        assert _tick_conditional(bare, 0.0) == US_DORMANT
        bare.AddCondition(_Cond(0))
        bare.AddCondition(c)
        bare._contained_ai = monkey_child
        assert _tick_conditional(bare, 0.0) == US_ACTIVE
        assert ticked == [monkey_child, monkey_child]
        after = _native_counts()
    finally:
        ai_driver.tick_ai = real_tick
    assert (after[0] > before[0]) == (walker == "native")


def test_a_reassigned_get_status_code_is_called(walker):
    """TGCondition.GetStatus left in place but its __code__ swapped: the
    function object is still the stock one, but its body is not, so the
    native stock check (function AND code) must call it, not read
    `_status`."""
    c = TGCondition()
    c.SetStatus(0)
    fn = TGCondition.__dict__["GetStatus"]
    stock_code = fn.__code__

    def seven(self):
        return 7
    seen = []
    ai = _conditional([c], lambda a, seen=seen: seen.append(a) or US_ACTIVE)
    fn.__code__ = seven.__code__
    try:
        _refresh_conditional_status(ai)
    finally:
        fn.__code__ = stock_code
    assert seen == [7]


def test_the_stock_get_status_capture_checks_its_shape():
    """_STOCK_CONDITION_GETSTATUS is taken at import and checks that the code
    it takes is `return self._status`. A GetStatus replaced before the import
    is not taken as stock: the capture falls back to (None, None), so every
    GetStatus is called (the import does not fail). A docstring on an
    otherwise stock body does not break the check."""
    assert ai_driver._STOCK_CONDITION_GETSTATUS == (
        TGCondition.__dict__["GetStatus"],
        TGCondition.__dict__["GetStatus"].__code__)
    fn = TGCondition.__dict__["GetStatus"]
    stock_code = fn.__code__

    def other(self):
        return self._status + 0

    def documented(self):
        """The stock body, with a docstring."""
        return self._status

    def bare(self):
        return self._status
    try:
        fn.__code__ = other.__code__
        assert ai_driver._capture_stock_get_status() == (None, None)
        fn.__code__ = documented.__code__
        assert ai_driver._capture_stock_get_status() == (
            fn, documented.__code__)
        fn.__code__ = bare.__code__
        assert ai_driver._capture_stock_get_status() == (fn, bare.__code__)
    finally:
        fn.__code__ = stock_code
    assert ai_driver._capture_stock_get_status() == (fn, stock_code)


def test_with_no_stock_get_status_every_get_status_is_called(monkeypatch):
    """The fallback capture (None, None): a stock TGCondition's GetStatus is
    called by the native evaluation too, never read inline."""
    monkeypatch.setattr(ai_driver, "_STOCK_CONDITION_GETSTATUS", (None, None))
    calls = []
    real = TGCondition.__dict__["GetStatus"]

    def counting(self):
        calls.append(1)
        return real(self)
    c = TGCondition()
    c.SetStatus(1)
    c.GetStatus = counting.__get__(c)
    seen = []
    ai = _conditional([c], lambda a, seen=seen: seen.append(a) or US_ACTIVE)
    before = _native_counts()[1]
    _refresh_conditional_status(ai)
    assert seen == [1] and calls == [1]
    d = TGCondition()
    d.SetStatus(1)
    ai2 = _conditional([d], lambda a, seen=seen: seen.append(a) or US_ACTIVE)
    _refresh_conditional_status(ai2)
    assert _native_counts()[1] == before       # no inline stock read


def test_a_nan_status_hits_the_memo_only_as_the_same_object():
    """A NaN condition status enters the key (float is a memo key type). The
    key compare is a tuple `==`, whose identity shortcut makes the SAME NaN
    object equal and a fresh NaN unequal: the same answer from both walkers
    (an EvalFunc re-run only for the fresh one)."""
    nan = float("nan")
    cond = _Cond(nan)
    calls = []

    def EvalFunc(a, calls=calls, ACTIVE=US_ACTIVE):
        calls.append(a)
        return ACTIVE
    ai = _conditional([cond], EvalFunc)
    _refresh_conditional_status(ai)
    _refresh_conditional_status(ai)              # the same NaN object: a hit
    assert len(calls) == 1
    cond.status = float("nan")                   # equal-looking, not the same
    _refresh_conditional_status(ai)
    assert len(calls) == 2
    assert ai._status == US_ACTIVE
