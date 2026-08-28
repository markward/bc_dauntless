"""The AI sleep scheduler's invariants, bound to the REAL handlers.

tests/unit/test_ai_due_time_walking.py proves the scheduling CONTRACT, but it
proves it against a test double (`_handler`) installed into _DISPATCH_BY_TYPE
that makes its own _note_due calls. So the load-bearing invariant --

    every site that gates on `game_time >= ai._next_update_time` must call
    _note_due with that time, or its node oversleeps

-- was asserted only of the double, never of _tick_plain / _tick_preprocessing /
_tick_priority_list. The failure mode is SOFT: a missing _note_due costs at most
AI_MAX_SLEEP_TICKS of timeliness (~66 ms), so nothing goes red, no exception is
raised, and the only symptom is an AI that reacts slightly late. This project
has been bitten repeatedly by doubles that reimplemented the surface they were
standing in for (see the memory note "test doubles must mirror real surface"),
and this is exactly that shape.

So these tests drive the real handlers and count executions per simulated
second, with the sleep on and off. If sleeping delays anything, the counts
diverge.
"""
import ast
import pathlib

import pytest

from engine.appc import ai_driver
from engine.appc.ai import (PlainAI, PreprocessingAI, PriorityListAI)
from engine.appc.ai_driver import tick_all_ai, US_ACTIVE, US_DORMANT
from engine.core import ids as core_ids


TICK = 1.0 / 60.0


class _Ship:
    """Just enough ShipClass surface for tick_all_ai + the out-of-action gate."""

    def __init__(self, ai):
        self._ai = ai

    def GetAI(self):
        return self._ai

    def GetName(self):
        return "S"

    def IsDying(self):
        return False

    def IsDead(self):
        return False


class _Script:
    """A leaf script with an explicit cadence, counting its own Updates."""

    def __init__(self, interval):
        self._interval = interval
        self.runs = 0

    def Update(self):
        self.runs += 1
        return US_ACTIVE

    def GetNextUpdateTime(self):
        return self._interval


class _Preprocessor:
    """A preprocessor with an explicit cadence, counting its own Updates."""

    def __init__(self, interval, result=None):
        self._interval = interval
        self._result = result
        self.runs = 0

    def PreUpdate(self):
        self.runs += 1
        return self._result

    def GetNextUpdateTime(self):
        return self._interval


@pytest.fixture
def drive(monkeypatch):
    """Run one ship's real AI tree through the real tick_all_ai."""

    def run(ai, ticks, max_sleep, start=0.0):
        ship = _Ship(ai)
        ai._ship = ship
        monkeypatch.setattr(ai_driver, "AI_MAX_SLEEP_TICKS", max_sleep)
        import engine.appc.ship_iter as ship_iter
        monkeypatch.setattr(ship_iter, "iter_ships", lambda: [ship])
        t = start
        for _ in range(ticks):
            t += TICK
            tick_all_ai(game_time=t)
        return ship

    return run


# ── the invariant, against the real handlers ────────────────────────────────

@pytest.mark.parametrize("interval", [0.0, 0.05, 0.1, 0.2, 0.5])
def test_a_real_PlainAI_runs_as_often_asleep_as_awake(drive, interval):
    """_tick_plain's own gate, not a double's.

    Sleeping is only allowed to skip walks that would have executed NOTHING, so
    the number of script Updates in one simulated second must be identical with
    the scheduler on and off. Drop either _note_due in _tick_plain and the tree
    oversleeps past its own cadence, and these counts diverge.
    """
    awake = _Script(interval)
    asleep = _Script(interval)
    for script, max_sleep in ((awake, 0), (asleep, 4)):
        ai = PlainAI()
        ai._script_instance = script
        drive(ai, ticks=60, max_sleep=max_sleep)

    assert asleep.runs == awake.runs, (
        "a %.2f s-cadence PlainAI ran %d times asleep vs %d awake -- the sleep "
        "scheduler DELAYED it, which is the regression the per-site _note_due "
        "exists to prevent" % (interval, asleep.runs, awake.runs))


@pytest.mark.parametrize("interval", [0.0, 0.05, 0.1, 0.2, 0.5])
def test_a_real_PreprocessingAI_runs_as_often_asleep_as_awake(drive, interval):
    """Same invariant for _tick_preprocessing's cadence gate. FireScript is
    0.2 s and SelectTarget ~3.5 s, so this is the site that actually gates in
    a live battle."""
    awake = _Preprocessor(interval)
    asleep = _Preprocessor(interval)
    for pre, max_sleep in ((awake, 0), (asleep, 4)):
        ai = PreprocessingAI()
        ai.SetPreprocessingMethod(pre, "PreUpdate")
        drive(ai, ticks=60, max_sleep=max_sleep)

    assert asleep.runs == awake.runs, (
        "a %.2f s-cadence preprocessor ran %d times asleep vs %d awake"
        % (interval, asleep.runs, awake.runs))


def test_a_dormant_preprocessing_child_is_re_probed_as_promptly_asleep(drive):
    """_tick_priority_list's dormant re-probe gate (the _note_due_ret site).

    A PS_SKIP_DORMANT preprocessor under a PriorityListAI is re-probed once its
    own cadence is due -- that is what lets a ship whose target died re-engage.
    Nothing else in the tree knows that due time, so if the gate stops recording
    it the whole tree sleeps through the revival window.
    """
    counts = []
    for max_sleep in (0, 4):
        pre = _Preprocessor(0.1, result=PreprocessingAI.PS_SKIP_DORMANT)
        child = PreprocessingAI()
        child.SetPreprocessingMethod(pre, "PreUpdate")
        root = PriorityListAI()
        root.AddAI(child, 1)
        drive(root, ticks=60, max_sleep=max_sleep)
        assert child._status == US_DORMANT
        counts.append(pre.runs)

    assert counts[1] == counts[0], (
        "a dormant preprocessor was re-probed %d times asleep vs %d awake"
        % (counts[1], counts[0]))


def test_every_due_time_gate_in_the_driver_records_its_due_time():
    """Structural backstop for the invariant _note_due's docstring claims.

    The behavioural tests above cover the three gates that exist today. This one
    covers the gate somebody adds next year: any comparison of `game_time`
    against a `_next_update_time` must sit in a function that also records that
    time, or its node can oversleep by up to AI_MAX_SLEEP_TICKS -- silently,
    because oversleeping raises nothing and fails no assertion.
    """
    src = pathlib.Path(ai_driver.__file__).read_text()
    tree = ast.parse(src)

    def _mentions(node, names):
        return any(isinstance(n, ast.Name) and n.id in names
                   for n in ast.walk(node))

    def _gates(node):
        for cmp_node in ast.walk(node):
            if not isinstance(cmp_node, ast.Compare):
                continue
            attrs = {n.attr for n in ast.walk(cmp_node)
                     if isinstance(n, ast.Attribute)}
            if "_next_update_time" in attrs and _mentions(cmp_node, {"game_time"}):
                return True
        return False

    offenders = [fn.name for fn in ast.walk(tree)
                 if isinstance(fn, ast.FunctionDef) and _gates(fn)
                 and not _mentions(fn, {"_note_due", "_note_due_ret"})]
    assert not offenders, (
        "these functions gate on game_time vs _next_update_time without ever "
        "calling _note_due, so their nodes can oversleep: %r" % (offenders,))


# ── the measured waste the pre-gate note used to cause ──────────────────────

def test_a_node_that_just_ran_does_not_force_a_walk_on_the_very_next_tick(
        drive, monkeypatch):
    """The pre-gate _note_due used to record an ALREADY-PAST due time on the
    tick a node executes, pinning _walk_min_due to the past so the tree was
    walked again on the very next tick to discover nothing was due. Measured:
    287 walks for 96 runs at cap 4, where ~192 would do.

    Driven through the REAL _tick_plain -- a double reproducing the gate would
    only be testing itself.
    """
    walks = []
    real = ai_driver._tick_plain

    def counting(ai, game_time):
        walks.append((game_time, ai._script_instance.runs))
        return real(ai, game_time)

    monkeypatch.setitem(ai_driver._DISPATCH_BY_TYPE, PlainAI, counting)

    ai = PlainAI()
    ai._script_instance = _Script(0.5)      # 30 ticks: far past the 4-tick cap
    drive(ai, ticks=12, max_sleep=4)

    ran_at = next(i for i, (_t, runs_before) in enumerate(walks)
                  if walks[i + 1][1] > runs_before) if len(walks) > 1 else None
    assert ran_at is not None and ran_at + 1 < len(walks), (
        "the node never executed, or never woke again: %r" % (walks,))
    gap = walks[ran_at + 1][0] - walks[ran_at][0]
    assert gap > 3.5 * TICK, (
        "the tree was walked again %.1f ticks after executing; a node that "
        "just rescheduled 0.5 s out should sleep the full 4-tick cap"
        % (gap / TICK))


# ── the dispatch cache ──────────────────────────────────────────────────────

def test_a_node_type_matching_no_handler_is_resolved_only_once(monkeypatch):
    """_resolve_dispatch legitimately answers None for a node type that matches
    nothing, and the cache read used to be a plain .get() -- so None-for-stored
    was indistinguishable from None-for-absent and such a type re-ran the whole
    ordered issubclass chain on EVERY visit. That is precisely the case the
    cache exists to kill, and it is invisible: the node still dispatches
    correctly, just slowly."""
    resolved = []
    real = ai_driver._resolve_dispatch

    def counting(node_type):
        resolved.append(node_type)
        return real(node_type)

    monkeypatch.setattr(ai_driver, "_resolve_dispatch", counting)

    class _Foreign:
        """Not an ArtificialIntelligence subclass at all -- matches no arm."""
        _status = US_ACTIVE
        _has_focus = False
        _contained_ai = None

        def GetShip(self):
            return None

        def SetActive(self, *a):
            pass

        def SetInactive(self, *a):
            pass

    node = _Foreign()
    for _ in range(10):
        ai_driver.tick_ai(node, 0.0)
    ai_driver._DISPATCH_BY_TYPE.pop(_Foreign, None)

    assert resolved.count(_Foreign) == 1, (
        "the isinstance chain ran %d times for one unmatched node type"
        % resolved.count(_Foreign))


# ── constants that must not drift ───────────────────────────────────────────

def test_the_local_tick_seconds_matches_the_game_loop():
    """ai_driver keeps its own copy of the tick length because importing
    engine.core.loop here would cycle. Nothing pinned the two together, so a
    change to the game loop's rate would silently leave the AI scheduler
    computing sleeps against the old one."""
    from engine.core.loop import TICK_DELTA
    assert ai_driver._TICK_SECONDS == TICK_DELTA


# ── environment parsing ─────────────────────────────────────────────────────

def test_a_typo_in_the_sleep_env_var_falls_back_instead_of_killing_the_engine(
        monkeypatch):
    """DAUNTLESS_AI_MAX_SLEEP is parsed at import time. A bare int() there means
    `DAUNTLESS_AI_MAX_SLEEP=4x` takes the whole engine down with a ValueError
    during `import engine.appc.ai_driver` -- before any log, from a developer
    convenience knob."""
    monkeypatch.setenv("DAUNTLESS_AI_MAX_SLEEP", "4x")
    assert ai_driver._env_int("DAUNTLESS_AI_MAX_SLEEP", 4) == 4
    monkeypatch.setenv("DAUNTLESS_AI_MAX_SLEEP", "")
    assert ai_driver._env_int("DAUNTLESS_AI_MAX_SLEEP", 4) == 4
    monkeypatch.setenv("DAUNTLESS_AI_MAX_SLEEP", "0")
    assert ai_driver._env_int("DAUNTLESS_AI_MAX_SLEEP", 4) == 0
    monkeypatch.setenv("DAUNTLESS_AI_MAX_SLEEP", "7")
    assert ai_driver._env_int("DAUNTLESS_AI_MAX_SLEEP", 4) == 7
    monkeypatch.delenv("DAUNTLESS_AI_MAX_SLEEP")
    assert ai_driver._env_int("DAUNTLESS_AI_MAX_SLEEP", 4) == 4


# ── cross-test isolation of the two new process-lifetime caches ─────────────

def test_the_autouse_reset_clears_the_implements_and_dispatch_caches():
    """Both caches are keyed on a CLASS and live for the whole process.

    implements() answers from _IMPLEMENTS_CACHE and _dispatch_ai from
    _DISPATCH_BY_TYPE, so a test that monkeypatches a class method -- or installs
    a stand-in handler, as two AI test modules do -- poisons every LATER test in
    the same process. Order-dependent, silent, and exactly the class of leak
    tests/conftest.py's autouse reset exists to close.
    """
    from tests import conftest

    class _Poison:
        pass

    core_ids._IMPLEMENTS_CACHE[_Poison] = {"GetShip": True}
    ai_driver._DISPATCH_BY_TYPE[_Poison] = lambda ai, t: US_ACTIVE

    conftest._reset_leakable_engine_globals()

    assert _Poison not in core_ids._IMPLEMENTS_CACHE, (
        "implements() would keep answering from a monkeypatched class")
    assert _Poison not in ai_driver._DISPATCH_BY_TYPE, (
        "a stand-in AI handler survives into unrelated later tests")
