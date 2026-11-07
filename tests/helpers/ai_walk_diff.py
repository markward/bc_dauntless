"""The tree-walk differential harness (phase 6 AI part 4, Task 1).

``run_walk_diff(scene, ticks)`` runs one seeded scene twice in this process,
once with ``ai_driver._native_walker`` False (the Python walker) and once with
it True (the native walker, from the task that lands it; until then the
selector routes to the same Python code, so every comparison passes and the
harness proves itself deterministic). It raises ``AssertionError`` naming the
tick and the first difference unless, for every tick,

* the CALL LOG is identical: every call the driver makes into Python, in
  order, with its arguments and its result (or the exception it raised); and
* the STATE of every node reachable from every ship's AI root is identical
  after the tick, plus the roster-level state the walk writes.

How the call log is recorded. Nothing in the driver is edited. Before each
tick the recorder walks every ship's tree and wraps, at INSTANCE level (so the
class, and every other tree, is untouched), the entry points the driver
reaches:

* PlainAI: ``GetScriptInstance``; the script instance's ``Update`` /
  ``GetNextUpdateTime`` / ``GotFocus`` / ``LostFocus`` / ``Reset``;
* PreprocessingAI: the preprocessor method named by ``_preprocessing_method``
  and the same hooks on its instance (``functools.wraps`` keeps
  ``inspect.signature``, which the driver's arity probe reads, unchanged);
* ConditionalAI: the EvalFunc (a wrapper that still exposes ``__code__`` and
  ``__globals__``, so the driver's memoisable-function test gives the same
  verdict) and each condition's ``GetStatus`` / ``SetActive`` /
  ``SetInactive``, and ``Activate`` / ``Deactivate`` of a ConditionScript's
  instance;
* every node: ``SetActive`` / ``SetInactive`` / ``IsInterruptable`` /
  ``ForceUpdate`` / ``Reset``;
* BuilderAI: each ``BuilderCreateN`` in its module.

Module-level glue is wrapped for the run with a ``MonkeyPatch``:
``ship_death._out_of_action``, ``defensive_cloak.is_defensive``,
``ship_iter.iter_non_rock_ships``, ``ai_driver._ensure_select_target_initialized``,
``ai_driver._sync_fire_script_target_subsystem``, ``ai_driver.fire_ai_done``
and ``random.choice``. ``ClearAI`` / ``SetAI`` are wrapped on each ship.
Entries are ``("call", name, who, args, kwargs)``, then ``("ret", name, who,
value)`` or ``("raise", name, who, exception type)``: nesting is visible.

What is compared after each tick (:meth:`_Recorder.snapshot`): per node (by AI
ID, never ``id()``) ``_status``, ``_has_focus``, ``_got_focus_called``,
``_next_update_time``, ``_last_preprocess_status``, ``_is_active_in_tree``,
``_interruptable``, ``_paused``, ``_current_index``, ``_loops_remaining``,
``_current_child``, ``_untried``, ``_evalfn_cache``, the builder fields,
``_last_script_error``, and the child lists; on each root
``_focused_preprocessors`` / ``_active_nodes`` and ``_done_event_fired``; per
ship the installed AI, ``_ai_next_walk_due``; and the driver's
reported-error set. Floats compare by ``float.hex``; node references by ID.

Fresh state per side: the AI and object id counters restart at the same base,
the reported-error log and the dispatch cache are replaced, and every RNG is
seeded with ``k1_fight._seed_every_rng``. IN-PROCESS rather than the
subprocess pair of ``native_ai_ab``: that harness compares whole-fight byte
records, so a stray module global only costs a rerun; this one compares the
call order and ALL node state, and has to see the Python objects (a
subprocess could only compare serialised output, and could not hold the
negative test's mutation or return the log). Everything that differs between
two loads in one process is reset here, and two Python runs are asserted
identical (the harness tests), which is the proof.
"""
import functools
import itertools
import random
from collections import Counter

import pytest

_ABSENT = "<absent>"


def _norm(v, depth=0):
    """A value as a comparable, repr-stable tuple/scalar: floats by hex, AI
    nodes by ID, ships by name, containers element-wise, anything else by
    type name."""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        return ("int", v)
    if isinstance(v, float):
        return ("f", v.hex())
    if depth > 4:
        return ("deep", type(v).__name__)
    if isinstance(v, (list, tuple)):
        return (type(v).__name__,) + tuple(_norm(x, depth + 1) for x in v)
    if isinstance(v, dict):
        return ("dict",) + tuple(sorted(
            (repr(k), _norm(x, depth + 1)) for k, x in v.items()))
    from engine.appc.ai import ArtificialIntelligence, TGCondition
    if isinstance(v, ArtificialIntelligence):
        return ("ai", v.GetID())
    if isinstance(v, TGCondition):
        return ("cond", v.GetObjID())
    get_name = getattr(type(v), "GetName", None)
    if get_name is not None:
        try:
            return ("obj", type(v).__name__, v.GetName())
        except Exception:                                   # noqa: BLE001
            pass
    return ("type", type(v).__name__)


class _EvalWrap:
    """A recording EvalFunc. Exposes the wrapped function's ``__code__`` and
    ``__globals__`` so ``ai_driver._memoisable_evalfunc`` decides exactly as it
    would for the function itself."""

    def __init__(self, fn, record, who):
        self._fn = fn
        self._record = record
        self._who = who
        self._diff_wrapped = True

    @property
    def __code__(self):
        return self._fn.__code__

    @property
    def __globals__(self):
        return self._fn.__globals__

    def __call__(self, *args):
        return self._record("eval", self._who, self._fn, args, {})


#: Node-level entry points the driver or a re-entrant script reaches.
_NODE_METHODS = ("SetActive", "SetInactive", "IsInterruptable",
                 "ForceUpdate", "Reset")
#: Script-instance hooks.
_HOOKS = ("Update", "GetNextUpdateTime", "GotFocus", "LostFocus", "Reset")


class _Recorder:
    def __init__(self, mp, scene):
        self.mp = mp
        self.scene = scene
        self.log = []
        self.ticks = []                 # [(log_slice, snapshot)]
        self._seen_modules = set()

    # ── the call log ─────────────────────────────────────────────────────────
    def _record(self, name, who, fn, args, kwargs):
        self.log.append(("call", name, _norm(who), _norm(args), _norm(kwargs)))
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:                         # noqa: BLE001
            self.log.append(("raise", name, _norm(who), type(exc).__name__))
            raise
        self.log.append(("ret", name, _norm(who), _norm(result)))
        return result

    def _wrapper(self, name, who, fn):
        record = self._record

        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            return record(name, who, fn, args, kwargs)
        wrapped._diff_wrapped = True
        return wrapped

    def _wrap_attr(self, obj, attr, name, who):
        """Wrap ``obj.attr`` at instance level if the object really has it
        (statically: a data-bag's ``__getattr__`` lambdas are not wrapped)."""
        import inspect
        try:
            current = inspect.getattr_static(obj, attr)
        except AttributeError:
            return
        own = getattr(obj, "__dict__", None)
        if own is not None and getattr(own.get(attr), "_diff_wrapped", False):
            return
        try:
            fn = getattr(obj, attr)
            if not callable(fn):
                return
            setattr(obj, attr, self._wrapper(name, who, fn))
        except (AttributeError, TypeError):
            return

    # ── instrumenting the trees ──────────────────────────────────────────────
    @staticmethod
    def children(node):
        d = node.__dict__
        out = []
        for c in d.get("_ais") or ():
            out.append(c[1] if isinstance(c, tuple) else c)
        for key in ("_contained_ai",):
            c = d.get(key)
            if c is not None:
                out.append(c)
        return [c for c in out if c is not None]

    def nodes(self, root):
        seen, order, stack = set(), [], [root]
        while stack:
            n = stack.pop()
            if id(n) in seen:
                continue
            seen.add(id(n))
            order.append(n)
            stack.extend(reversed(self.children(n)))
        return order

    def roots(self):
        out = []
        for ship in self.scene.ships() + self.scene.extra_ships:
            ai = ship.GetAI() if hasattr(ship, "GetAI") else None
            if ai is not None:
                out.append((ship, ai))
        return out

    def instrument(self):
        for ship, root in self.roots():
            for attr in ("ClearAI", "SetAI"):
                self._wrap_attr(ship, attr, "ship." + attr, ("ship", ship.GetName()))
            for node in self.nodes(root):
                self._instrument_node(node)

    def _instrument_node(self, node):
        who = node.GetID()
        for m in _NODE_METHODS:
            self._wrap_attr(node, m, "node." + m, who)
        d = node.__dict__
        from engine.appc.ai import PlainAI
        if isinstance(node, PlainAI):
            self._wrap_attr(node, "GetScriptInstance", "GetScriptInstance", who)
        for inst, extra in ((d.get("_script_instance"), ()),
                            (d.get("_preprocessing_instance"),
                             (d.get("_preprocessing_method") or "",))):
            if inst is None:
                continue
            for h in _HOOKS + tuple(m for m in extra if m):
                self._wrap_attr(inst, h, "script." + h, who)
        fn = d.get("_evaluation_function")
        if fn is not None and not getattr(fn, "_diff_wrapped", False):
            node._evaluation_function = _EvalWrap(fn, self._record, who)
        for cond in d.get("_conditions") or ():
            cwho = ("cond", cond.GetObjID())
            for m in ("GetStatus", "SetActive", "SetInactive"):
                self._wrap_attr(cond, m, "cond." + m, cwho)
            ci = getattr(cond, "__dict__", {}).get("_instance")
            if ci is not None:
                for m in ("Activate", "Deactivate"):
                    self._wrap_attr(ci, m, "cond." + m, cwho)
        mod_name = d.get("_module_name")
        if mod_name and "_blocks" in d:
            self._instrument_builder_module(node, mod_name)

    def _instrument_builder_module(self, node, mod_name):
        import sys
        mod = sys.modules.get(mod_name)
        if mod is None:
            return
        for func_name in node._blocks.values():
            if not isinstance(func_name, str):
                continue
            fn = getattr(mod, func_name, None)
            if fn is None or getattr(fn, "_diff_wrapped", False):
                continue
            self.mp.setattr(mod, func_name, self._builder_wrapper(
                "builder." + func_name, node.GetID(), fn))

    def _builder_wrapper(self, name, who, fn):
        """A BuilderCreateN wrapper that also instruments the subtree it
        returns, so the nodes built on a tick are recorded on that same tick
        (they are walked in it)."""
        from engine.appc.ai import ArtificialIntelligence
        inner = self._wrapper(name, who, fn)

        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            result = inner(*args, **kwargs)
            if isinstance(result, ArtificialIntelligence):
                for n in self.nodes(result):
                    self._instrument_node(n)
            return result
        wrapped._diff_wrapped = True
        return wrapped

    def install_glue(self):
        """Wrap the module-level callables the driver reaches. Done once,
        before the first tick, so a native walker that resolves them through
        the module sees the wrappers."""
        from engine.appc import ai_driver, defensive_cloak, ship_death, ship_iter
        mp = self.mp

        def glue(mod, attr, name, who_of):
            orig = getattr(mod, attr)

            def wrapped(*args, **kwargs):
                return self._record(name, who_of(args), orig, args, kwargs)
            wrapped._diff_wrapped = True
            mp.setattr(mod, attr, wrapped)

        # Through a proxy bound in ai_driver, NOT by patching ship_death:
        # the native motion stage reads ship_death._out_of_action and runs in
        # Python when it is patched, which would change the scene.
        record = self._record

        class _DeathProxy:
            def __getattr__(self, name):
                return getattr(ship_death, name)

            def _out_of_action(self, ship):
                return record("_out_of_action", ship,
                              ship_death._out_of_action, (ship,), {})
        mp.setattr(ai_driver, "ship_death", _DeathProxy())
        glue(defensive_cloak, "is_defensive", "is_defensive",
             lambda a: a[0] if a else None)
        glue(ai_driver, "_ensure_select_target_initialized",
             "_ensure_select_target_initialized", lambda a: None)
        glue(ai_driver, "_sync_fire_script_target_subsystem",
             "_sync_fire_script_target_subsystem", lambda a: None)
        glue(ai_driver, "fire_ai_done", "fire_ai_done",
             lambda a: a[1] if len(a) > 1 else None)
        glue(random, "choice", "random.choice", lambda a: None)

        if not self.scene.wrap_roster:
            return
        orig_iter = ship_iter.iter_non_rock_ships

        def iter_wrapped(*args, **kwargs):
            ships = list(orig_iter(*args, **kwargs))
            self.log.append(("roster", tuple(_norm(s) for s in ships)))
            return iter(ships)
        mp.setattr(ship_iter, "iter_non_rock_ships", iter_wrapped)

    # ── the state ────────────────────────────────────────────────────────────
    _NODE_FIELDS = (
        "_status", "_has_focus", "_got_focus_called", "_next_update_time",
        "_last_preprocess_status", "_is_active_in_tree", "_interruptable",
        "_paused", "_current_index", "_loops_remaining", "_current_child",
        "_untried", "_last_script_error", "_activated", "_activation_failed",
        "_activation_error", "_contained_ai", "_ais", "_focused_preprocessors",
        "_active_nodes", "_done_event_fired")

    def snapshot(self):
        from engine.appc import ai_driver
        ships = {}
        for ship in self.scene.ships() + self.scene.extra_ships:
            ai = ship.GetAI() if hasattr(ship, "GetAI") else None
            row = {"ai": _norm(ai),
                   "walk_due": _norm(ship.__dict__.get("_ai_next_walk_due",
                                                       _ABSENT))}
            nodes = {}
            if ai is not None:
                for node in self.nodes(ai):
                    d = node.__dict__
                    state = {f: _norm(d.get(f, _ABSENT))
                             for f in self._NODE_FIELDS}
                    cache = d.get("_evalfn_cache")
                    state["_evalfn_cache"] = _ABSENT if cache is None else (
                        cache[0] is d.get("_evaluation_function"),
                        _norm(cache[1]), _norm(cache[2]))
                    state["type"] = type(node).__name__
                    nodes[node.GetID()] = state
            row["nodes"] = nodes
            ships[repr(_norm(ship))] = row
        return {"ships": ships,
                "errors": sorted(ai_driver._reported_script_errors)}


class Record:
    """What one side saw: per tick, the call-log slice and the state."""

    def __init__(self, ticks):
        self.ticks = ticks

    def calls(self):
        """Counter of ``("call", name)`` entries over the whole run."""
        c = Counter()
        for log, _snap in self.ticks:
            for e in log:
                if e[0] == "call":
                    c[e[1]] += 1
        return c

    def log(self):
        return [e for log, _s in self.ticks for e in log]


class Scene:
    """What a scene factory returns (see the tests for the synthetic ones).

    ``ships()`` the current roster; ``step(i)`` runs tick ``i`` (default:
    ``tick_all_ai`` at game time ``(i + 1) / 60``)."""

    def __init__(self, ships, step=None, wrap_roster=True, extra_ships=()):
        self._ships = ships
        self._step = step
        #: Ships outside the walked roster whose trees the scene ticks itself
        #: (a nested walk); instrumented and snapshotted like the roster.
        self.extra_ships = list(extra_ships)
        #: Wrap ship_iter.iter_non_rock_ships to log the roster. Off for the
        #: real fights: the native motion stage declines to run when that
        #: function is patched, which would change the scene.
        self.wrap_roster = wrap_roster

    def ships(self):
        s = self._ships
        return list(s() if callable(s) else s)

    def step(self, i):
        if self._step is not None:
            return self._step(i)
        from engine.appc import ai_driver
        ai_driver.tick_all_ai((i + 1) / 60.0)


def synthetic_scene(mp, ships, step=None, extra_ships=()):
    """A :class:`Scene` over hand-built `ships`: the roster the driver walks
    (``iter_non_rock_ships``) is exactly them."""
    from engine.appc import ship_iter
    roster = list(ships)
    mp.setattr(ship_iter, "iter_non_rock_ships", lambda *a, **k: iter(roster))
    return Scene(roster, step, extra_ships=extra_ships)


def _bases():
    from engine.appc.ai import ArtificialIntelligence
    from engine.core import ids
    return ArtificialIntelligence._next_id, next(ids._counter)


def _fresh_state(mp, base_ai, base_obj):
    from engine.appc import ai_driver
    from engine.appc.ai import ArtificialIntelligence
    from engine.core import ids
    ArtificialIntelligence._next_id = base_ai
    mp.setattr(ids, "_counter", itertools.count(base_obj))
    ai_driver.reset_script_error_log()
    mp.setattr(ai_driver, "_DISPATCH_BY_TYPE", {})
    mp.setattr(ai_driver, "_ooa_cache", [None, False])
    mp.setattr(ai_driver, "_walk_min_due", [float("inf")])
    mp.setattr(ai_driver, "_focus_depth", 0)
    from tests.helpers import k1_fight
    k1_fight._seed_every_rng(0)


def run_side(scene, ticks, native, bases=None):
    """One side of the comparison: returns its :class:`Record`. `bases` is the
    (AI id, object id) pair both sides start their counters from."""
    from engine.appc import ai_driver
    from engine.appc.ai import ArtificialIntelligence
    from engine.core import ids
    with pytest.MonkeyPatch.context() as mp:
        base_ai, base_obj = bases or _bases()
        _fresh_state(mp, base_ai, base_obj)
        mp.setattr(ai_driver, "_native_walker", bool(native))
        built = scene(mp)
        rec = _Recorder(mp, built)
        rec.install_glue()
        out = []
        try:
            for i in range(ticks):
                rec.instrument()
                start = len(rec.log)
                try:
                    built.step(i)
                except Exception as exc:                     # noqa: BLE001
                    rec.log.append(("escaped", type(exc).__name__, str(exc)))
                out.append((rec.log[start:], rec.snapshot()))
        finally:
            top_obj = next(ids._counter)
            top_ai = ArtificialIntelligence._next_id
            mp.undo()
            ArtificialIntelligence._next_id = top_ai
            ids._counter = itertools.count(top_obj + 1)
        return Record(out)


def first_difference(py, nat):
    """None, or a message naming the tick and the first difference."""
    if len(py.ticks) != len(nat.ticks):
        return "tick counts differ: %d vs %d" % (len(py.ticks), len(nat.ticks))
    for t, ((plog, psnap), (nlog, nsnap)) in enumerate(
            zip(py.ticks, nat.ticks)):
        if plog != nlog:
            for k, (a, b) in enumerate(zip(plog, nlog)):
                if a != b:
                    return ("tick %d: call log differs at entry %d:\n"
                            "  python: %r\n  native: %r" % (t, k, a, b))
            return ("tick %d: call log lengths differ (%d vs %d); extra %r"
                    % (t, len(plog), len(nlog),
                       (plog if len(plog) > len(nlog) else nlog)[
                           min(len(plog), len(nlog))]))
        if psnap != nsnap:
            if psnap["errors"] != nsnap["errors"]:
                return ("tick %d: reported-error set differs:\n  python: %r\n"
                        "  native: %r" % (t, psnap["errors"], nsnap["errors"]))
            for ship, prow in psnap["ships"].items():
                nrow = nsnap["ships"].get(ship)
                if nrow is None:
                    return "tick %d: ship %s missing natively" % (t, ship)
                for key in ("ai", "walk_due"):
                    if prow[key] != nrow[key]:
                        return ("tick %d: %s %s differs: python %r native %r"
                                % (t, ship, key, prow[key], nrow[key]))
                for nid, pst in prow["nodes"].items():
                    nst = nrow["nodes"].get(nid)
                    if nst is None:
                        return ("tick %d: %s node %s missing natively"
                                % (t, ship, nid))
                    for f, pv in pst.items():
                        if pv != nst[f]:
                            return ("tick %d: %s node %s (%s) field %s differs:"
                                    "\n  python: %r\n  native: %r"
                                    % (t, ship, nid, pst["type"], f, pv,
                                       nst[f]))
                if set(nrow["nodes"]) - set(prow["nodes"]):
                    return ("tick %d: %s natively has extra nodes %r"
                            % (t, ship, sorted(set(nrow["nodes"])
                                               - set(prow["nodes"]))))
            return "tick %d: snapshots differ (unlocated)" % t
    return None


def run_walk_diff(scene, ticks, warm_ticks=0):
    """Run `scene` (a factory ``scene(mp)`` taking the side's MonkeyPatch and
    returning a :class:`Scene`; it is called once per side, after the fresh
    state and the walker flag are set)
    under the Python and the native walker; raise AssertionError naming the
    tick and the first difference. Returns the Python side's :class:`Record`
    so a test can assert the scene reached what it claims."""
    if warm_ticks:
        # A discarded Python-side run first: the first load of a heavy scene
        # touches process-lifetime caches (as the golden fights' warm-up arm
        # does), and the id allocations of that first load differ.
        run_side(scene, warm_ticks, native=False)
    bases = _bases()
    py = run_side(scene, ticks, native=False, bases=bases)
    nat = run_side(scene, ticks, native=True, bases=bases)
    diff = first_difference(py, nat)
    assert diff is None, diff
    return py
