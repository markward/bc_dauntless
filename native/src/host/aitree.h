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
#pragma once

#include <Python.h>

#include <span>

namespace dauntless::host::aitree {

// The functions above, for host_bindings.cc to add to the module.
std::span<PyMethodDef> method_defs();

}  // namespace dauntless::host::aitree
