// native/src/host/subsystem_write_apply.h
//
// The subsystem stage's write log applied by C (phase 6 A1, Task 3;
// dauntless/combat/subsystem_step.h THE WRITE LOG). The native piece wrote
// the mirror itself; this stores each logged write into its Python object,
// quietly (no push: the mirror already holds the value), as the Python
// piece's own statements leave it:
//
//   CHARGE_ACCUM  sub.__dict__["_charge_accum"] = value
//   RAMP          sub.__dict__["_ramp_fraction"][index] = value
//   FACE          sub.__dict__["_current_shields"][index] = value
//   SHIELD_WATCH  sub.__dict__["_shield_watchers"][index]
//                    .__dict__["_value"] = value
//   the power piece's (subsystem_step.h THE WRITE LOG): a float into its
//   attribute; BREACH_FIRED True; BATTERY_WATCH into the main (index 0) or
//   backup (1) battery watcher's `_value`; the cloak's and the
//   bay's: TRANSITION_ELAPSED a float, CLOAK_STATE an int, REPAIR_NOTIFIED
//   an add (index 1) / discard (0) of the member's handle on the bay's
//   `_cannot_complete_notified` set, in place.
//
// The lists are the subsystem's own, written in place (the attribute
// lookups Python code makes resolve to the instance dict: these
// descriptors have no __get__). `sub` is a Subsystem handle; its object is
// `registry.get(sub)` (native_combat._registry, read as the K1 applier
// reads it), which must be live and carry that handle as its `_nslot`: the
// native piece writes only through a live row, and no Python runs between
// its read and this apply, so anything else is a broken invariant
// (RuntimeError). One object is looked up once per run of writes to it.
//
// EXCEPTIONS: the first store that raises stops the apply (the native piece
// cannot have made a write Python would not; a raise here is a broken
// invariant, and the driver resyncs the rows). False means a Python error
// is set. The GIL is held throughout.
#pragma once

#include <Python.h>

#include <span>

#include "dauntless/combat/subsystem_step.h"

namespace dauntless::host {

bool apply_subsystem_writes(PyObject* registry,
                            std::span<const combat::SubsystemWrite> w);

}  // namespace dauntless::host
