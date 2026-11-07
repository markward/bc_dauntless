// native/src/host/aitree.h
//
// The AI tree engine (phase 6 AI part 4, A5), built in seams. Task 2 (S1):
// the per-tick ROSTER and its sleep scheduling, i.e.
// engine/appc/ai_driver.py `_tick_all_ai_python` in C++, plus the walk's
// min-due slot that `_note_due` writes. Each root walk is still Python's
// `tick_ai` (native from Task 4). Task 3 (S2): the CONDITION EVALUATION,
// ai_driver's `_refresh_conditional_status_python`,
// `_eval_conditional_python` (the memo in `ai.__dict__["_evalfn_cache"]`
// included) and `_tick_conditional`'s two status reads; ai_driver's public
// names pick them when the native walker is selected. Task 4 (S4): the WALK,
// `_tick_ai_python`, `_dispatch_ai`, every stock `_tick_*` handler and the
// helpers they call by global name (`_dispatch_priority_child` and its
// rollback, `_queue_got_focus`, `_focus_instance_of`, `_retain_subtree_focus`,
// `_note_due_ret`). The focus and activation RECONCILIATION
// (`_reconcile_focus`, `_flush_pending_got_focus`, `_reconcile_active`) is
// still Python, called at the root as Python calls it (Task 5's seam).
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
//   aitree_tick(ai, game_time, globals)   tick_ai with the native walker
//   aitree_walk_counts()                  (native walks, then native runs of
//                                         each stock handler kind)
//
// S4, THE WALK. ai_driver's `tick_ai` is a dispatcher: `_aitree_tick` when
// `_native_walker` is true, else `_tick_ai_python`. The native walk runs a
// driver function's body natively only while the module global of that name
// is the stock one, as captured at import in `_STOCK_WALK` (name -> (function,
// code)) or, for a handler from `_DISPATCH_BY_TYPE` / `_resolve_dispatch`,
// `_STOCK_HANDLERS` (function -> (kind, code)): the very function, still with
// its own code. Anything else in its place (a test's injected handler, a
// monkeypatch, a wrapper, a reassigned __code__) is CALLED, at the point the
// Python walk calls it. A stock dispatcher (tick_ai, the four S2 names) is
// inlined only while `_native_walker` is true and the binding it would call
// is still ours; otherwise the dispatcher itself is called. `_note_due` is
// run inline only while the global is our builtin.
//
// The walk state is ai_driver's MODULE GLOBALS, read and rebound exactly
// where Python reads and rebinds them: `_focus_depth`, `_ooa_cache`,
// `_reached_this_tick`, `_reached_this_tick_all`, `_reached_this_tick_all_ids`
// and `_pending_got_focus`. Not a native copy, deliberately: the
// reconciliation is still Python and reads them by name; a Python handler
// (an injected type's, a patched stock one calling the original) appends to
// them; and a root walk nested in a focus hook rebinds them under the outer
// root, whose reconciliation then reads the rebound lists, which is Python's
// visible behaviour (Review Focus 4). Moving them onto the native frame waits
// for the reconciliation to move (Task 5).
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
//    cannot raise RecursionError at the recursion limit.
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
