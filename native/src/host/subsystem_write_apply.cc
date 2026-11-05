// native/src/host/subsystem_write_apply.cc -- see subsystem_write_apply.h.

#include "subsystem_write_apply.h"

#include <cstdint>

#include "combat_write_apply.h"

namespace dauntless::host {

namespace cb = dauntless::combat;

namespace {

// Interned names, created on first use (the GIL held), never released.
struct Names {
    PyObject* dict;
    PyObject* nslot;
    PyObject* value;
    PyObject* by_kind[static_cast<int>(cb::SubsystemWriteKind::kCount)];
    PyObject* backup_watcher;   // BATTERY_WATCH index 1 (by_kind: index 0)
};

// Each kind's attribute (BATTERY_WATCH: the main watcher's; index 1 names
// the backup's).
constexpr const char* kAttr[] = {
    "_charge_accum",          // CHARGE_ACCUM
    "_ramp_fraction",         // RAMP
    "_current_shields",       // FACE
    "_shield_watchers",       // SHIELD_WATCH
    "_available_power",       // AVAILABLE_POWER
    "_main_battery_power",    // MAIN_BATTERY
    "_backup_battery_power",  // BACKUP_BATTERY
    "_main_conduit_current",  // MAIN_CONDUIT
    "_backup_conduit_current",  // BACKUP_CONDUIT
    "_interval_elapsed",      // INTERVAL_ELAPSED
    "_power_dispensed",       // POWER_DISPENSED
    "_power_wanted_total",    // POWER_WANTED_TOTAL
    "_power_wanted",          // POWER_WANTED
    "_power_received",        // POWER_RECEIVED
    "_efficiency",            // EFFICIENCY
    "_power_factor",          // POWER_FACTOR
    "_backup_reserve",        // BACKUP_RESERVE
    "_breach_fired",          // BREACH_FIRED
    "_main_battery_watcher",  // BATTERY_WATCH
    "_transition_elapsed",    // TRANSITION_ELAPSED
    "_cloak_state",           // CLOAK_STATE
    "_cannot_complete_notified",  // REPAIR_NOTIFIED
};
static_assert(sizeof(kAttr) / sizeof(kAttr[0]) ==
              static_cast<size_t>(cb::SubsystemWriteKind::kCount));

Names* g_names = nullptr;

const Names* names() {
    if (g_names != nullptr) return g_names;
    auto* t = new Names;
    t->dict = PyUnicode_InternFromString("__dict__");
    t->nslot = PyUnicode_InternFromString("_nslot");
    t->value = PyUnicode_InternFromString("_value");
    for (size_t k = 0; k < sizeof(kAttr) / sizeof(kAttr[0]); ++k)
        t->by_kind[k] = PyUnicode_InternFromString(kAttr[k]);
    t->backup_watcher = PyUnicode_InternFromString("_backup_battery_watcher");
    if (t->dict == nullptr || t->nslot == nullptr || t->value == nullptr ||
        t->backup_watcher == nullptr) {
        delete t;  // the interned strings are immortal enough: leaked
        return nullptr;
    }
    for (PyObject* o : t->by_kind)
        if (o == nullptr) {
            delete t;
            return nullptr;
        }
    g_names = t;
    return g_names;
}

// The live object row `h` names, as its __dict__ (a new reference), or
// nullptr with an error set.
PyObject* live_dict(const Names* n, PyObject* registry, std::int64_t h) {
    PyObject* key = PyLong_FromLongLong(h);
    if (key == nullptr) return nullptr;
    PyObject* obj = registry_lookup(registry, key);
    if (obj == nullptr) {
        Py_DECREF(key);
        return nullptr;
    }
    PyObject* d = obj == Py_None ? nullptr : PyObject_GetAttr(obj, n->dict);
    Py_DECREF(obj);
    if (d == nullptr) {
        Py_DECREF(key);
        if (!PyErr_Occurred())
            PyErr_Format(PyExc_RuntimeError,
                         "subsystem stage: no live object for row %lld",
                         static_cast<long long>(h));
        return nullptr;
    }
    PyObject* slot = PyDict_Check(d) ? PyDict_GetItemWithError(d, n->nslot)
                                     : nullptr;
    int same = 0;
    if (slot != nullptr) {
        Py_INCREF(slot);
        same = PyObject_RichCompareBool(slot, key, Py_EQ);
        Py_DECREF(slot);
    }
    Py_DECREF(key);
    if (same < 0) {
        Py_DECREF(d);
        return nullptr;
    }
    if (!same) {
        Py_DECREF(d);
        if (!PyErr_Occurred())
            PyErr_Format(PyExc_RuntimeError,
                         "subsystem stage: row %lld's object does not carry "
                         "it as its _nslot",
                         static_cast<long long>(h));
        return nullptr;
    }
    return d;
}

// One write into `d` (the object's __dict__). False: an error is set.
bool store(const Names* n, PyObject* d, const cb::SubsystemWrite& w) {
    const auto k = static_cast<int>(w.what);
    if (k < 0 || k >= static_cast<int>(cb::SubsystemWriteKind::kCount)) {
        PyErr_SetString(PyExc_SystemError,
                        "subsystem stage: unknown write kind");
        return false;
    }
    PyObject* name = n->by_kind[k];
    using K = cb::SubsystemWriteKind;
    if (w.what == K::BREACH_FIRED)
        return PyObject_SetItem(d, name, Py_True) == 0;
    if (w.what == K::CLOAK_STATE) {
        PyObject* v = PyLong_FromLongLong(static_cast<long long>(w.value));
        if (v == nullptr) return false;
        const bool ok = PyObject_SetItem(d, name, v) == 0;
        Py_DECREF(v);
        return ok;
    }
    if (w.what == K::REPAIR_NOTIFIED) {
        // The bay's set, in place: add (index 1) or discard (0) the
        // member's handle (the set's key, subsystems._notify_key).
        PyObject* set = PyObject_GetItem(d, name);
        if (set == nullptr) return false;
        if (!PySet_Check(set)) {
            Py_DECREF(set);
            PyErr_SetString(PyExc_TypeError,
                            "subsystem stage: _cannot_complete_notified is "
                            "not a set");
            return false;
        }
        PyObject* key = PyLong_FromLongLong(w.ref);
        bool ok = key != nullptr;
        if (ok)
            ok = (w.index == 1 ? PySet_Add(set, key)
                               : PySet_Discard(set, key)) >= 0;
        Py_XDECREF(key);
        Py_DECREF(set);
        return ok;
    }
    PyObject* v = PyFloat_FromDouble(w.value);
    if (v == nullptr) return false;
    bool ok;
    if (w.what == K::BATTERY_WATCH) {
        PyObject* watcher = PyObject_GetItem(
            d, w.index == 1 ? n->backup_watcher : name);
        PyObject* wd = watcher != nullptr ? PyObject_GetAttr(watcher, n->dict)
                                          : nullptr;
        ok = wd != nullptr && PyObject_SetItem(wd, n->value, v) == 0;
        Py_XDECREF(wd);
        Py_XDECREF(watcher);
    } else if (w.what != K::RAMP && w.what != K::FACE &&
               w.what != K::SHIELD_WATCH) {
        ok = PyObject_SetItem(d, name, v) == 0;   // a float attribute
    } else {
        PyObject* lst = PyObject_GetItem(d, name);
        if (lst == nullptr) {
            Py_DECREF(v);
            return false;
        }
        PyObject* idx = PyLong_FromLong(w.index);
        if (idx == nullptr) {
            ok = false;
        } else if (w.what == cb::SubsystemWriteKind::SHIELD_WATCH) {
            PyObject* watcher = PyObject_GetItem(lst, idx);
            PyObject* wd = watcher != nullptr
                               ? PyObject_GetAttr(watcher, n->dict)
                               : nullptr;
            ok = wd != nullptr && PyObject_SetItem(wd, n->value, v) == 0;
            Py_XDECREF(wd);
            Py_XDECREF(watcher);
        } else {
            ok = PyObject_SetItem(lst, idx, v) == 0;
        }
        Py_XDECREF(idx);
        Py_DECREF(lst);
    }
    Py_DECREF(v);
    return ok;
}

}  // namespace

bool apply_subsystem_writes(PyObject* registry,
                            std::span<const cb::SubsystemWrite> w) {
    if (w.empty()) return true;
    const Names* n = names();
    if (n == nullptr) return false;
    PyObject* d = nullptr;
    std::int64_t at = -1;
    bool ok = true;
    for (const cb::SubsystemWrite& x : w) {
        if (d == nullptr || x.sub != at) {
            Py_XDECREF(d);
            d = live_dict(n, registry, x.sub);
            at = x.sub;
            if (d == nullptr) return false;
        }
        if (!store(n, d, x)) {
            ok = false;
            break;
        }
    }
    Py_XDECREF(d);
    return ok;
}

}  // namespace dauntless::host
