// native/src/host/aitree.h
//
// The AI tree engine (phase 6 AI part 4, A5), built in seams. THE PYTHON
// WALKER IS GONE FROM THE ENGINE (Task 8): what this file calls
// `_tick_all_ai_python`, `_tick_ai_python`, the `_tick_*` bodies and the
// `*_python` condition bodies is frozen verbatim, as of commit 1a9aa97af, in
// tests/helpers/ai_walker_oracle.py, the reference the differential harness
// (tests/helpers/ai_walk_diff.py) holds this walker equal to. In ai_driver
// the same names are one-statement FORWARDERS into this unit (`aitree_run`
// for the ones without a binding of their own): patch points, and the
// "stock" identities the gates below compare against. There is no
// `_native_walker` flag any more; the walk is always this one.
//
// Task 2 (S1): the per-tick ROSTER and its sleep scheduling, i.e.
// `_tick_all_ai_python` in C++, plus the walk's
// min-due slot that `_note_due` writes. Each root walk goes through
// `tick_ai`'s stock gate (native from Task 4). Task 3 (S2): the CONDITION
// EVALUATION,
// ai_driver's `_refresh_conditional_status_python`,
// `_eval_conditional_python` (the memo in `ai.__dict__["_evalfn_cache"]`
// included) and `_tick_conditional`'s two status reads; ai_driver's public
// names pick them when the native walker is selected. Task 4 (S4): the WALK,
// `_tick_ai_python`, `_dispatch_ai`, every stock `_tick_*` handler and the
// helpers they call by global name (`_dispatch_priority_child` and its
// rollback, `_queue_got_focus`, `_focus_instance_of`, `_retain_subtree_focus`,
// `_note_due_ret`). Task 5 (S3): the root end's focus and activation
// RECONCILIATION, `_reconcile_focus` (with `_dispatch_lost_focus`),
// `_flush_pending_got_focus` and `_reconcile_active`.
//
// Python surface (raw METH_FASTCALL; a missing name is a stale binary):
//   aitree_tick_all(game_time, globals)   the roster; `globals` is ai_driver's
//                                         module dict, read at call time
//   aitree_note_due(when)                 `if when < slot: slot = when`
//   aitree_walk_min_due()                 the slot's value
//   aitree_walk_min_due_reset()           slot = float("inf")
//   aitree_roster_count()                 how many rosters have started
//   aitree_refresh_conditional(ai, globals)
//   aitree_eval_conditional(ai, eval_fn, args, globals) -> pre-fold status
//   aitree_condition_statuses(ai, globals) -> [c.GetStatus() for c in ...]
//   aitree_any_condition(ai, globals) -> any(c.GetStatus() != 0 for c ...)
//   aitree_conditional_counts()           (native S2 entries, direct reads)
//   aitree_run(name, globals, *args)      the native body of one ai_driver
//                                         forwarder (_tick_plain, _dispatch_ai,
//                                         _reconcile_focus, ...): what a
//                                         wrapper calling the original lands in
//   aitree_tick(ai, game_time, globals)   tick_ai with the native walker
//   aitree_walk_counts()                  (native walks, then native runs of
//                                         each stock handler kind)
//   aitree_reconcile_counts()             (native runs of the three
//                                         reconcilers, then SetActive /
//                                         SetInactive calls skipped)
//
// S4, THE WALK. ai_driver's `tick_ai` forwards to `_aitree_tick`. The native
// walk runs a driver function's body natively only while the module global of that name
// is the stock one, as captured at import in `_STOCK_WALK` (name -> (function,
// code)) or, for a handler from `_DISPATCH_BY_TYPE` / `_resolve_dispatch`,
// `_STOCK_HANDLERS` (function -> (kind, code)): the very function, still with
// its own code. Anything else in its place (a test's injected handler, a
// monkeypatch, a wrapper, a reassigned __code__) is CALLED, at the point the
// old Python walk called it. A stock forwarder that names a binding of its
// own (tick_ai, the four S2 names) is inlined only while that binding is
// still ours; otherwise the forwarder itself is called (and lands in the same
// binding). `_note_due` is run inline only while the global is our builtin.
// `_note_due_ret` is the one stock name that is still a two-statement Python
// body, inlined likewise.
//
// The walk state is ai_driver's MODULE GLOBALS, read and rebound exactly
// where Python reads and rebinds them: `_focus_depth`, `_ooa_cache`,
// `_reached_this_tick`, `_reached_this_tick_all`, `_reached_this_tick_all_ids`
// and `_pending_got_focus`. Not a native copy, deliberately (ruled in Task
// 4, kept in Task 5 for exactness): a patched reconciler, or a Python
// handler (an injected type's, a patched stock one calling the original),
// reads or appends to them by name; and a root walk nested in a focus or
// activation hook rebinds them under the outer root, whose next root-end step
// then reads the REBOUND lists (`_tick_ai_python` loads each one as it calls
// the reconciler), which is Python's visible behaviour (Review Focus 4).
//
// S3, THE ROOT END. Each reconciler runs natively while its global is the
// stock one (`_STOCK_WALK`), else it is called; the native bodies call
// `_dispatch_lost_focus` and `_focus_instance_of` through the same gate, and
// every LostFocus / GotFocus through `_run_script_step`. The order is
// Python's: LostFocus in the root's previous `_focused_preprocessors` order,
// GotFocus in arrival (`_pending_got_focus`) order, SetInactive in the
// previous `_active_nodes` order, SetActive in reached order. The two
// `{id(n) for n in reached}` sets are only ever tested for membership while
// the PREVIOUS list is iterated, so their iteration order cannot leak; they
// are kept natively as the addresses the ids are. Each list is iterated live
// (a hook mutating it in place is seen; one rebinding the root's attribute is
// not), and the root's `_focused_preprocessors` / `_active_nodes` are stored
// as `list(reached)`: Python lists on the root, which
// `ships._deactivate_ai_tree` resets and the AI inspector reads.
//
// `SetActive()` / `SetInactive()` stay Python calls, made through Python's own
// method lookup on each node, EXCEPT one skip: the call is not made when
//  (a) the lookup lands, unbound, on the stock ArtificialIntelligence method
//      (`_STOCK_SET_ACTIVE` / `_STOCK_SET_INACTIVE`: the very function, still
//      with its code; no instance attribute, subclass override or class
//      patch), and
//  (b) `_is_active_in_tree` can be read without running Python (generic
//      attribute lookup, no descriptor of that name on the type) and is
//      exactly True (SetActive) / exactly False (SetInactive).
// Then the stock body, `if [not] self._is_active_in_tree: return`, would
// read that attribute and return None at its first statement: nothing to
// see but the call itself (the accepted divergences below). The capture in
// ai_driver checks that the method's body is that shape instruction by
// instruction and falls back to (None, None), never skipping, if it is not.
// An edge, a non-bool value (its __bool__ is Python), a descriptor, a
// shadowed or overridden method: always called. ConditionalAI has no
// SetActive of its own; its edge reaches `_on_activated`, the condition
// SetActive / Activate calls, through the stock method, which is called.
//
// `DAUNTLESS_AI_BREAKDOWN`: with the breakdown on, `_dispatch_ai` hands each
// handler to the Python `_timed_dispatch`, which calls the handler's
// forwarder (and so the native body) under a timer. The results are the
// same; the timings carry one Python frame per node that the walk does not
// have with the breakdown off. A diagnostic only.
//
// `_run_script_step` is CALLED BACK, never reproduced: its `except
// Exception`, the `_last_script_error` record, the once-per-(node ID,
// exception type) report and its printed traceback stay one Python body that
// both walkers share, so they cannot drift; it runs only for a script step
// (the whole walk made about 82 k Python callbacks in 3,246 ticks at 128
// ships, C-438), so its one frame per step costs little next to the script
// it runs. The `lambda: bound(game_time + 1.0)` _tick_preprocessing
// hands it for a dEndTime preprocessor is a small native callable holding the
// two values the lambda's cells hold and adding when called (inside the try,
// as the lambda does).
//
// S2 resolves at call time, through `globals`: `_eval_conditional` (the
// refresh evaluates inline only while it is still `_STOCK_EVAL_CONDITIONAL`,
// and calls the replacement otherwise), `_memoisable_evalfunc` (called on a
// verdict miss, exactly as Python; the verdict itself is Python's memo in
// `ai.__dict__["_evalfn_memoisable"]`, so no native memo needs
// invalidating), `_MEMO_KEY_TYPES`, `US_*`. `c.GetStatus()` is Python's own
// method lookup (`_PyObject_GetMethod`, LOAD_METHOD's) every time; only when
// it lands on `_STOCK_CONDITION_GETSTATUS` (TGCondition.GetStatus as taken
// at import, the very function with its very code) is its body,
// `return self._status`, run inline. An override, an instance attribute (the
// differential harness's recording wrapper is one) or a patched class is
// called.
//
// Bit-exact with the Python roster: the same Python callbacks in the same
// order, every callee resolved at call time through the lookup Python does,
// the same stores, and an exception propagates at the point Python's would
// (skipping that ship's stamp and every later ship). The GIL is held
// throughout; nothing borrowed is held across a Python call.
//
// FRAME-LOCAL LIFETIMES (a standing rule for every native walker function):
// each Python local (ship, due, ai, status, get_ai, clear) is an owned slot
// at function scope that keeps its object until the statement rebinding that
// name, the new object stored before the old one is released (STORE_FAST's
// order); the iterator drops at loop exhaustion and the locals in
// co_varnames order at return (_PyFrame_Clear). A finaliser (SDK conditions
// tear down in __del__) therefore runs at the same point under both rosters.
//
// KNOWN, ACCEPTED DIVERGENCES:
//  - The stock-body checks (`_same_body` in ai_driver, for GetStatus,
//    SetActive and SetInactive) compare code flags with only CO_NESTED
//    masked. A Python that sets further flags on a plain function (3.14's
//    CO_METHOD / CO_HAS_DOCSTRING) makes the comparison fail, which FAILS
//    CLOSED: the function is not taken as stock and is called every time.
//    Safe, only slower; widen the mask (or the capture's shape check) when
//    moving the embedded Python.
//  - hasattr, getattr, callable and min are the builtins' semantics applied
//    directly, not looked up through LOAD_GLOBAL, so a module-level shadow of
//    one of those names in ai_driver is ignored natively (Python would call
//    the shadow). Nothing defines one.
//  - The two `from ... import` statements call
//    PyImport_ImportModuleLevelObject directly, so an overridden
//    builtins.__import__ is not consulted (Python's IMPORT_NAME would call
//    it). Nothing overrides it.
//  - Likewise `tuple`, `int`, `any`, `all`, `type` and `Exception` in S2:
//    the builtins' own operations (PySequence_Tuple, PyNumber_Long, ...),
//    never a module-level shadow.
//  - A stock GetStatus read inline pushes no frame: a tracer or profiler
//    (sys.settrace / setprofile, cProfile) does not see that call, and it
//    cannot raise RecursionError at the recursion limit. Likewise a skipped
//    no-edge SetActive / SetInactive.
//  - The skip reads `_is_active_in_tree` from the instance dict once more
//    than Python when it then calls (an edge). The read runs no Python
//    unless the dict holds a non-str key with that key's hash and an
//    __eq__, which nothing does.
//  - The walk's builtins (`id`, `len`, `isinstance`, `type`, `range`,
//    `float`, `sum`, `getattr`, `callable`, TypeError/ValueError in the arity
//    probe's except) likewise, and so is the `(TypeError, ValueError)` tuple.
//  - A driver function or handler run natively pushes no Python frame:
//    tracers and profilers do not see it, `sys._getframe()` in a script
//    called from it shows no driver frames, a printed traceback lacks them,
//    and the recursion limit counts one level per native tick_ai (Python
//    would count about four), so a cyclic tree raises RecursionError later
//    natively (Py_EnterRecursiveCall keeps the C stack safe).
//  - `_reached_this_tick_all_ids.update(id(n) for n in ...)` in the rollback:
//    an exact set takes each id as the generator would yield it; any other
//    receiver gets the ids as one list (its update() still runs once).
//  - The arity probe counts `sum(1 for ...)` as a C integer (the same int).
//  - On an exception, Python keeps the frame's locals alive through the
//    traceback (the frame object) until the caller's `except` clause ends;
//    the native roster releases them before it returns the error. A
//    finaliser of a local can therefore run earlier natively when the roster
//    raises. This cannot be matched from C++ (there is no frame object to
//    hang them on).
#pragma once

#include <Python.h>

#include <span>

namespace dauntless::host::aitree {

// The functions above, for host_bindings.cc to add to the module.
std::span<PyMethodDef> method_defs();

}  // namespace dauntless::host::aitree
