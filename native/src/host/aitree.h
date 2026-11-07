// native/src/host/aitree.h
//
// The AI tree engine (phase 6 AI part 4, A5), built in seams. Task 2 (S1):
// the per-tick ROSTER and its sleep scheduling, i.e.
// engine/appc/ai_driver.py `_tick_all_ai_python` in C++, plus the walk's
// min-due slot that `_note_due` writes. Each root walk is still Python's
// `tick_ai` (native from Task 4).
//
// Python surface (raw METH_FASTCALL; a missing name is a stale binary):
//   aitree_tick_all(game_time, globals)   the roster; `globals` is ai_driver's
//                                         module dict, read at call time
//   aitree_note_due(when)                 `if when < slot: slot = when`
//   aitree_walk_min_due()                 the slot's value
//   aitree_walk_min_due_reset()           slot = float("inf")
//   aitree_roster_count()                 how many rosters have started
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
