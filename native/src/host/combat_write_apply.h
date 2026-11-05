// native/src/host/combat_write_apply.h
//
// C-applied write logs (spec 2026-11-02-native-weapon-state-design.md §4.1,
// weapon-state-map.md §4). A kernel record's write log -- the decision-path
// writes the kernel already made in the mirror -- is applied by the binding
// straight into the Python objects, in order, before the record is returned,
// exactly as engine/appc/native_combat.py `apply_writes` (THE REFERENCE,
// kept) applies the Python-encoded log: same order, same apply kind per
// (class, field), same values and value types, same exceptions.
//
// THE CONTEXT (combat_set_applier). The driver hands the binding, once per
// session, a 6-tuple
//   (pins, registry, walk, kinds, wake, python_setters)
//   pins            the walk's handle -> object dict (`_K1Walk.pins`)
//   registry        native_combat._registry (`.get(h)`: object or None)
//   walk            the `_K1Walk` (its `materialise(n, h)`, its `walk`)
//   kinds           a mapping (type, field) -> apply kind; the binding asks
//                   it once per (type, field) and caches the answer until a
//                   context with ANOTHER kinds object is set
//   wake            passive_state.wake
//   python_setters  (type, field) -> (setter, value kind PLAIN/REF/REFS),
//                   read for a PYTHON-kind field
// and restores the previous one when the session ends (the K1 sessions
// nest). With no context set, the bindings return the log as before.
//
// THE APPLY KINDS (combat_apply_kinds; native_combat.APPLY_*), each what
// `_apply_write` does through `_quiet_setter`:
//   PLAIN    obj.__dict__[field] = value
//   REF      value = walk.obj(value) (pins, else registry checked by
//            `_nslot`; -1 is None), then PLAIN
//   REFS     value = a NEW list [walk.obj(h) for h in value], then PLAIN
//   WAKE     PLAIN, then passive_state.wake(obj) when
//            obj.__dict__.get("_passive_asleep", False) is true
//            (WakeField.__set__)
//   PYTHON   the reference's quiet setter, setter(obj, value), its value
//            converted first by the setter's value kind
//   SLOT     in place: obj.__dict__[field][index] = value (K0)
//   WATCHER  obj.__dict__[field].__dict__["_value"] = value, `field` the
//            attribute holding the FloatRangeWatcher, "_charge_watcher" (K0)
// The first five are a property of (type, field) (the kinds mapping); SLOT
// and WATCHER are a property of the WRITE: its value is an ApplySlot or an
// ApplyWatcher (below), whatever the field's descriptor. A walk-offset
// marker (combat::K1WalkOffset) is a value too: walk.materialise(walk,
// system), the walk's own offset object, then stored by the field's kind.
//
// THE NATIVE REPRESENTATIONS. K1 / K2 log K1Write / K2Write; a Python log
// (combat_apply_log, tests) parses to ApplyWrite (combat/write_log.h), whose
// slot write is ApplyWrite{handle, "<list attribute>", ApplySlot{index,
// scalar}} and watcher write ApplyWrite{handle, "_charge_watcher",
// ApplyWatcher{scalar}}; every other write uses the K1Value alternatives
// (ApplyValue lists them first, in K1Value's order). Every name is a
// string_view of static (or pooled, never freed) storage: its interned str
// is cached by address. K0 logs combat::K0Write (k0_charging.h): its Field
// (or the watcher) maps to an interned str through a table, its value is a
// float, bool, int, slot element or watcher value -- the same writes as the
// SLOT / WATCHER encodings, applied by the same rules. The Python encoding
// is the reference's plus two tagged tuples: ("slot", index, value) and
// ("watcher", value).
//
// THE REGISTRY. `walk.obj` reads `registry.get(h)`; for the real registry
// (an exact weakref.WeakValueDictionary) the applier reads its `data` dict
// and the KeyedRef's referent in C, exactly as `.get` does (a dead ref is
// None), with no Python call. Any other registry is asked through `.get`.
//
// EXCEPTIONS (apply_writes / _apply_rest): when a write raises, every later
// write of the range is still applied, in order -- a later walk-offset
// marker of a walk whose materialise raised is skipped; another walk's
// materialise raising (an Exception) adds the note "combat K1: walk %d's
// offset also raised %r" to the first exception -- and the first exception
// is re-raised. Any other raise among the rest propagates instead, its
// __context__ the first. While the rest runs, the first exception is the
// one being handled (as inside apply_writes' `except`).
//
// The GIL is held throughout; Python runs inside (materialise, the PYTHON
// setters, wake's hook), exactly the Python the reference runs.
//
// THE LEAN K0 APPLY (phase 6 A2). A K0 record's log is applied by its own
// path, write for write what the general one does, in the style of the
// subsystem stage's applier (subsystem_write_apply.h):
//   - one registry lookup per run of consecutive writes to one handle: the
//     live object carrying the handle as its `_nslot`, and its __dict__,
//     held for the run. No pins dict (the objects are held by the run, and
//     a RUN_PYTHON record's weapon is found through the registry anyway);
//   - the field's apply kind asked once per (type, field) and kept by type,
//     not looked up per write; PLAIN and WAKE stores go straight into the
//     dict, a slot into its list, a watcher value into its `_value`;
//   - a WAKE field's wake check (`_passive_asleep`) always made: K0 never
//     puts a weapon to sleep, but one the Python walk put to sleep (an
//     audit tick, a whole-ship hand-back) may still be asleep. Within a run
//     a falsy answer is kept until Python next runs (a wake, a general-path
//     write);
//   - a write whose value Python already holds -- an exact float with the
//     same bits (-0.0 is not 0.0), the same bool, the same exact int -- is
//     not stored (K0ApplyStats::identical); a WAKE field's wake check still
//     runs (WakeField.__set__ wakes on an equal value too). Python's object
//     is the reference, not the mirror: an int equal to the float is
//     replaced by the float, as Python's arithmetic replaces it.
// Anything else -- a run whose handle the registry does not answer with a
// live, matching object, a REF / REFS / PYTHON kind, a stop's Ref or Null
// write, a slot list or watcher of an unexpected shape -- takes the general
// path for that write (walk.obj with its pins, its exceptions). A raise
// stops the lean loop and the rest is applied as EXCEPTIONS says.
#pragma once

#include <Python.h>

#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
#include <variant>
#include <vector>

#include "dauntless/combat/k0_charging.h"
#include "dauntless/combat/k1_fire_control.h"
#include "dauntless/combat/k2_beams.h"
#include "dauntless/combat/write_log.h"

namespace dauntless::host {

enum class ApplyKind : int {
    PLAIN = 0,
    REF,
    REFS,
    WAKE,
    PYTHON,
    SLOT,
    WATCHER,
    kCount
};
const char* apply_kind_name(ApplyKind k);

// The write representation is the combat library's (write_log.h), so the K0
// kernel logs exactly what this applies: combat::K1Value's alternatives,
// then K0's two (a slot or watcher value: None, bool, int or float).
using ApplyScalar = combat::WriteScalar;
using ApplySlot = combat::SlotWrite;
using ApplyWatcher = combat::WatcherWrite;
using ApplyValue = combat::LoggedValue;
using ApplyWrite = combat::LoggedWrite;

class WriteApplier {
public:
    // Install `ctx` (the 6-tuple above, or None to remove it). Returns the
    // previous context (a new reference; None when there was none), or
    // nullptr with a Python error set (nothing changed) for a bad ctx.
    PyObject* set_context(PyObject* ctx);
    bool has_context() const { return ctx_ != nullptr; }
    // The installed context, borrowed (nullptr: none). Identity only: the
    // native damage entries' "is my reused context in use" check.
    PyObject* context() const { return ctx_; }

    // Apply writes[from, to) (see EXCEPTIONS). False: a Python error is set.
    bool apply(const std::vector<combat::K1Write>& w, size_t from, size_t to);
    bool apply(const std::vector<combat::K2Write>& w, size_t from, size_t to);
    bool apply(const std::vector<ApplyWrite>& w, size_t from, size_t to);
    // A K0 record's writes (a view of the session's log), all of them.
    bool apply(std::span<const combat::K0Write> w);

    // `walk.live(h)` on the context's walk (_K1Walk.live): the object the
    // handle names, pinned on the way, or None (-1, or a row freed since).
    // A new reference; nullptr with a Python error set (also when no
    // context is installed: RuntimeError).
    PyObject* live(std::int64_t h);

    // The Python encoding (a list of (handle, field, value)) -> `out`.
    // False: a Python error is set (TypeError / OverflowError).
    static bool parse_log(PyObject* log, std::vector<ApplyWrite>* out);

    // Writes applied by this path since the last reset_counts().
    std::uint64_t applied() const { return applied_; }
    void reset_counts() { applied_ = 0; }

    // Implementation hooks (combat_write_apply.cc).
    struct Impl;

private:
    template <class W>
    bool apply_range(const W* w, size_t size, size_t from, size_t to);

    PyObject* ctx_ = nullptr;  // owned: the 6-tuple
    std::uint64_t applied_ = 0;
};

// The process-wide applier (never destroyed: it owns Python references).
WriteApplier& write_applier();

// `registry.get(h)` (native_combat._registry, keyed by int handle `h`), as
// THE REGISTRY above reads it: a new reference (None when absent or dead),
// or nullptr with a Python error set. Shared with the subsystem stage's
// applier (subsystem_write_apply.h).
PyObject* registry_lookup(PyObject* registry, PyObject* h);

// The lean K0 apply's tallies (combat_k0_apply_stats), since the last
// reset: K0 writes applied, runs (registry lookups), writes not stored
// because Python already held the value, writes taken by the general path.
struct K0ApplyStats {
    std::uint64_t writes = 0;
    std::uint64_t runs = 0;
    std::uint64_t identical = 0;
    std::uint64_t general = 0;
};
K0ApplyStats& k0_apply_stats();

// The attribute a K0 write stores into: its Field's name (interned, never
// freed: a borrowed reference), or "_charge_watcher" for a watcher write.
// nullptr with SystemError for a Field id out of range.
PyObject* k0_field_name(const combat::K0FieldWrite& w);

}  // namespace dauntless::host
