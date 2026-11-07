// native/src/host/aitree.cc -- see aitree.h.
//
// THE REFERENCE is engine/appc/ai_driver.py `_tick_all_ai_python` (the Python
// roster) and `_note_due`'s former Python body; each step below names the
// statement it stands for. The arithmetic is Python's, in its operand order,
// with no multiply-add contracted (the pragma here; -ffp-contract=off from
// CMake for other compilers).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "aitree.h"

#include <new>

namespace dauntless::host::aitree {
namespace {

// An owned reference (steals on construction).
class Ref {
public:
    Ref() = default;
    explicit Ref(PyObject* p) : p_(p) {}
    Ref(const Ref&) = delete;
    Ref& operator=(const Ref&) = delete;
    Ref(Ref&& o) noexcept : p_(o.p_) { o.p_ = nullptr; }
    Ref& operator=(Ref&& o) noexcept {
        PyObject* old = p_;
        p_ = o.p_;
        o.p_ = nullptr;
        Py_XDECREF(old);
        return *this;
    }
    ~Ref() { Py_XDECREF(p_); }
    PyObject* get() const { return p_; }
    explicit operator bool() const { return p_ != nullptr; }

private:
    PyObject* p_ = nullptr;
};

// Interned names and constants, created on first use (the GIL held), never
// released. Names and constants only: every CALLEE is looked up per call.
struct Names {
    PyObject* dict;                 // "__dict__"
    PyObject* get;                  // "get"
    PyObject* walk_due;             // "_ai_next_walk_due"
    PyObject* get_ai;               // "GetAI"
    PyObject* clear_ai;             // "ClearAI"
    PyObject* done_fired;           // "_done_event_fired"
    PyObject* is_defensive;         // "is_defensive"
    PyObject* iter_non_rock_ships;  // "iter_non_rock_ships"
    PyObject* defensive_cloak;      // "defensive_cloak"
    PyObject* max_sleep;            // "AI_MAX_SLEEP_TICKS"
    PyObject* tick_seconds;         // "_TICK_SECONDS"
    PyObject* tick_ai;              // "tick_ai"
    PyObject* us_done;              // "US_DONE"
    PyObject* fire_ai_done;         // "fire_ai_done"
    PyObject* ai_breakdown;         // "_AI_BREAKDOWN"
    PyObject* ai_ticks;             // "_AI_TICKS"
    PyObject* builtins;             // "__builtins__"
    PyObject* name;                 // "__name__"
    PyObject* ship_iter_mod;        // "engine.appc.ship_iter"
    PyObject* appc_pkg;             // "engine.appc"
    PyObject* fromlist_iter;        // ("iter_non_rock_ships",)
    PyObject* fromlist_cloak;       // ("defensive_cloak",)
    PyObject* inf;                  // float("inf")
    PyObject* zero;                 // 0
    PyObject* one;                  // 1
};

Names* g_names = nullptr;

const Names* names() {
    if (g_names != nullptr) return g_names;
    auto* n = new Names();
    struct S {
        PyObject** slot;
        const char* text;
    };
    const S strs[] = {
        {&n->dict, "__dict__"},
        {&n->get, "get"},
        {&n->walk_due, "_ai_next_walk_due"},
        {&n->get_ai, "GetAI"},
        {&n->clear_ai, "ClearAI"},
        {&n->done_fired, "_done_event_fired"},
        {&n->is_defensive, "is_defensive"},
        {&n->iter_non_rock_ships, "iter_non_rock_ships"},
        {&n->defensive_cloak, "defensive_cloak"},
        {&n->max_sleep, "AI_MAX_SLEEP_TICKS"},
        {&n->tick_seconds, "_TICK_SECONDS"},
        {&n->tick_ai, "tick_ai"},
        {&n->us_done, "US_DONE"},
        {&n->fire_ai_done, "fire_ai_done"},
        {&n->ai_breakdown, "_AI_BREAKDOWN"},
        {&n->ai_ticks, "_AI_TICKS"},
        {&n->builtins, "__builtins__"},
        {&n->name, "__name__"},
        {&n->ship_iter_mod, "engine.appc.ship_iter"},
        {&n->appc_pkg, "engine.appc"},
    };
    for (const S& s : strs) {
        *s.slot = PyUnicode_InternFromString(s.text);
        if (*s.slot == nullptr) return nullptr;  // leaks a partial table: once
    }
    n->fromlist_iter = PyTuple_Pack(1, n->iter_non_rock_ships);
    n->fromlist_cloak = PyTuple_Pack(1, n->defensive_cloak);
    n->inf = PyFloat_FromDouble(Py_HUGE_VAL);
    n->zero = PyLong_FromLong(0);
    n->one = PyLong_FromLong(1);
    if (!n->fromlist_iter || !n->fromlist_cloak || !n->inf || !n->zero || !n->one)
        return nullptr;
    g_names = n;
    return n;
}

// ── the walk's min-due slot (Python: `_walk_min_due[0]`) ────────────────────
// Holds the very object `_note_due` was given (an int due time stays an int,
// as it did in the Python list), owned.
PyObject* g_min_due = nullptr;
unsigned long long g_roster_runs = 0;

// The slot's value, borrowed; nullptr (an error set) only if the first-use
// table could not be built.
PyObject* min_due() {
    if (g_min_due == nullptr) {
        const Names* n = names();
        if (n == nullptr) return nullptr;
        g_min_due = Py_NewRef(n->inf);
    }
    return g_min_due;
}

// `_walk_min_due[0] = v`: the new value first, then the old one released (a
// release can run Python, which must find the slot whole).
void set_min_due(PyObject* v) {
    PyObject* old = g_min_due;
    g_min_due = Py_NewRef(v);
    Py_XDECREF(old);
}

// Truthiness of `a OP b`, as Python's COMPARE_OP then jump: two exact floats
// compare as doubles (float_richcompare's own arm); anything else is
// Python's operator. -1: an error is set.
int compare(PyObject* a, PyObject* b, int op) {
    if (PyFloat_CheckExact(a) && PyFloat_CheckExact(b)) {
        const double x = PyFloat_AS_DOUBLE(a);
        const double y = PyFloat_AS_DOUBLE(b);
        switch (op) {
            case Py_LT: return x < y;
            case Py_LE: return x <= y;
            case Py_EQ: return x == y;
            default: break;
        }
    }
    Ref r(PyObject_RichCompare(a, b, op));
    if (!r) return -1;
    return PyObject_IsTrue(r.get());
}

// getattr's lookup: 1 found (*r owned), 0 an AttributeError (cleared), -1
// any other error.
int lookup_attr(PyObject* o, PyObject* name, PyObject** r) {
#if PY_VERSION_HEX >= 0x030D0000
    return PyObject_GetOptionalAttr(o, name, r);
#else
    return _PyObject_LookupAttr(o, name, r);
#endif
}

// `getattr(o, name, default)`, owned.
PyObject* getattr_or(PyObject* o, PyObject* name, PyObject* dflt) {
    PyObject* r = nullptr;
    const int has = lookup_attr(o, name, &r);
    if (has < 0) return nullptr;
    return has ? r : Py_NewRef(dflt);
}

// LOAD_GLOBAL in a function of the module whose dict is `globals`: the
// globals, then its builtins, else NameError. Owned.
PyObject* load_global(PyObject* globals, PyObject* name) {
    PyObject* v = PyDict_GetItemWithError(globals, name);
    if (v != nullptr) return Py_NewRef(v);
    if (PyErr_Occurred()) return nullptr;
    const Names* n = names();
    if (n == nullptr) return nullptr;
    PyObject* b = PyDict_GetItemWithError(globals, n->builtins);
    if (b == nullptr && PyErr_Occurred()) return nullptr;
    if (b != nullptr && PyModule_Check(b)) b = PyModule_GetDict(b);
    if (b != nullptr) {
        v = PyObject_GetItem(b, name);
        if (v != nullptr) return v;
        if (!PyErr_ExceptionMatches(PyExc_KeyError)) return nullptr;
        PyErr_Clear();
    }
    PyErr_Format(PyExc_NameError, "name '%U' is not defined", name);
    return nullptr;
}

// `from <module> import <attr>` as the function body runs it, each time:
// the import (IMPORT_NAME: sys.modules, or a real import), then the
// attribute (IMPORT_FROM: getattr, else the submodule in sys.modules).
// Owned.
PyObject* import_from(PyObject* module, PyObject* fromlist, PyObject* attr,
                      PyObject* globals) {
    Ref mod(PyImport_ImportModuleLevelObject(module, globals, Py_None, fromlist, 0));
    if (!mod) return nullptr;
    PyObject* x = PyObject_GetAttr(mod.get(), attr);
    if (x != nullptr) return x;
    if (!PyErr_ExceptionMatches(PyExc_AttributeError)) return nullptr;
    PyErr_Clear();
    const Names* n = names();
    if (n == nullptr) return nullptr;
    Ref pkg(PyObject_GetAttr(mod.get(), n->name));
    if (pkg && PyUnicode_Check(pkg.get())) {
        Ref full(PyUnicode_FromFormat("%U.%U", pkg.get(), attr));
        if (!full) return nullptr;
        x = PyImport_GetModule(full.get());
        if (x != nullptr) return x;
        if (PyErr_Occurred()) return nullptr;
    } else {
        PyErr_Clear();
    }
    PyErr_Format(PyExc_ImportError, "cannot import name '%U' from '%U'", attr, module);
    return nullptr;
}

// `game_time + max_sleep * _TICK_SECONDS`, `_TICK_SECONDS` read from the
// module now. Plain float / int / float is the double arithmetic float_mul
// and float_add do (the int converted by PyLong_AsDouble, as theirs is);
// anything else is Python's operators. Owned.
PyObject* cap_of(PyObject* game_time, PyObject* max_sleep, PyObject* globals) {
    const Names* n = names();
    if (n == nullptr) return nullptr;
    Ref ts(load_global(globals, n->tick_seconds));
    if (!ts) return nullptr;
    if (PyFloat_CheckExact(game_time) && PyLong_CheckExact(max_sleep) &&
        PyFloat_CheckExact(ts.get())) {
        const double ms = PyLong_AsDouble(max_sleep);
        if (ms == -1.0 && PyErr_Occurred()) return nullptr;
        const double prod = ms * PyFloat_AS_DOUBLE(ts.get());
        const double cap = PyFloat_AS_DOUBLE(game_time) + prod;
        return PyFloat_FromDouble(cap);
    }
    Ref prod(PyNumber_Multiply(max_sleep, ts.get()));
    if (!prod) return nullptr;
    return PyNumber_Add(game_time, prod.get());
}

// `ship.__dict__.get("_ai_next_walk_due")`, owned (None when absent).
PyObject* walk_due_of(PyObject* ship, const Names* n) {
    Ref d(PyObject_GetAttr(ship, n->dict));
    if (!d) return nullptr;
    if (PyDict_CheckExact(d.get())) {
        PyObject* v = PyDict_GetItemWithError(d.get(), n->walk_due);
        if (v != nullptr) return Py_NewRef(v);
        if (PyErr_Occurred()) return nullptr;
        Py_RETURN_NONE;
    }
    return PyObject_CallMethodOneArg(d.get(), n->get, n->walk_due);
}

// The roster: `_tick_all_ai_python`'s body, statement for statement.
PyObject* tick_all_impl(PyObject* game_time, PyObject* g) {
    const Names* n = names();
    if (n == nullptr) return nullptr;
    ++g_roster_runs;
    // from engine.appc.ship_iter import iter_non_rock_ships
    Ref iter_fn(import_from(n->ship_iter_mod, n->fromlist_iter, n->iter_non_rock_ships, g));
    if (!iter_fn) return nullptr;
    // from engine.appc import defensive_cloak
    Ref cloak(import_from(n->appc_pkg, n->fromlist_cloak, n->defensive_cloak, g));
    if (!cloak) return nullptr;
    // if _AI_BREAKDOWN is not None: _AI_TICKS[0] += 1
    {
        Ref bd(load_global(g, n->ai_breakdown));
        if (!bd) return nullptr;
        if (bd.get() != Py_None) {
            Ref ticks(load_global(g, n->ai_ticks));
            if (!ticks) return nullptr;
            Ref v(PyObject_GetItem(ticks.get(), n->zero));
            if (!v) return nullptr;
            Ref v2(PyNumber_InPlaceAdd(v.get(), n->one));
            if (!v2) return nullptr;
            if (PyObject_SetItem(ticks.get(), n->zero, v2.get()) < 0) return nullptr;
        }
    }
    // max_sleep = AI_MAX_SLEEP_TICKS
    Ref max_sleep(load_global(g, n->max_sleep));
    if (!max_sleep) return nullptr;
    // for ship in iter_non_rock_ships():
    Ref it;
    {
        Ref roster(PyObject_CallNoArgs(iter_fn.get()));
        if (!roster) return nullptr;
        it = Ref(PyObject_GetIter(roster.get()));
        if (!it) return nullptr;
    }
    for (;;) {
        Ref ship(PyIter_Next(it.get()));
        if (!ship) {
            if (PyErr_Occurred()) return nullptr;
            break;
        }
        // if defensive_cloak.is_defensive(ship): continue
        {
            Ref fn(PyObject_GetAttr(cloak.get(), n->is_defensive));
            if (!fn) return nullptr;
            Ref r(PyObject_CallOneArg(fn.get(), ship.get()));
            if (!r) return nullptr;
            const int t = PyObject_IsTrue(r.get());
            if (t < 0) return nullptr;
            if (t) continue;
        }
        // if max_sleep:
        //     due = ship.__dict__.get("_ai_next_walk_due")
        //     if due is not None and (
        //             game_time < due <= game_time + max_sleep * _TICK_SECONDS):
        //         continue
        {
            const int ms = PyObject_IsTrue(max_sleep.get());
            if (ms < 0) return nullptr;
            if (ms) {
                Ref due(walk_due_of(ship.get(), n));
                if (!due) return nullptr;
                if (due.get() != Py_None) {
                    const int lt = compare(game_time, due.get(), Py_LT);
                    if (lt < 0) return nullptr;
                    if (lt) {
                        Ref cap(cap_of(game_time, max_sleep.get(), g));
                        if (!cap) return nullptr;
                        const int le = compare(due.get(), cap.get(), Py_LE);
                        if (le < 0) return nullptr;
                        if (le) continue;
                    }
                }
            }
        }
        // ai = ship.GetAI() if hasattr(ship, "GetAI") else None
        Ref ai;
        {
            PyObject* probe = nullptr;
            const int has = lookup_attr(ship.get(), n->get_ai, &probe);
            if (has < 0) return nullptr;
            Py_XDECREF(probe);
            if (has) {
                ai = Ref(PyObject_CallMethodNoArgs(ship.get(), n->get_ai));
                if (!ai) return nullptr;
            }
        }
        // if ai is not None:
        if (!ai || ai.get() == Py_None) continue;
        // _walk_min_due[0] = float("inf"); status = tick_ai(ai, game_time)
        set_min_due(n->inf);
        Ref status;
        {
            Ref fn(load_global(g, n->tick_ai));
            if (!fn) return nullptr;
            PyObject* a[2] = {ai.get(), game_time};
            status = Ref(PyObject_Vectorcall(fn.get(), a, 2, nullptr));
            if (!status) return nullptr;
        }
        // if max_sleep:
        //     ship.__dict__["_ai_next_walk_due"] = min(
        //         _walk_min_due[0], game_time + max_sleep * _TICK_SECONDS)
        {
            const int ms = PyObject_IsTrue(max_sleep.get());
            if (ms < 0) return nullptr;
            if (ms) {
                Ref cur(Py_NewRef(g_min_due));
                Ref cap(cap_of(game_time, max_sleep.get(), g));
                if (!cap) return nullptr;
                // min(a, b): b only when `b < a` (builtin min's own test).
                const int lt = compare(cap.get(), cur.get(), Py_LT);
                if (lt < 0) return nullptr;
                PyObject* v = lt ? cap.get() : cur.get();
                Ref d(PyObject_GetAttr(ship.get(), n->dict));
                if (!d) return nullptr;
                if (PyObject_SetItem(d.get(), n->walk_due, v) < 0) return nullptr;
            }
        }
        // if status == US_DONE and not getattr(ai, "_done_event_fired", False):
        {
            Ref us_done(load_global(g, n->us_done));
            if (!us_done) return nullptr;
            const int eq = compare(status.get(), us_done.get(), Py_EQ);
            if (eq < 0) return nullptr;
            if (!eq) continue;
            Ref fired(getattr_or(ai.get(), n->done_fired, Py_False));
            if (!fired) return nullptr;
            const int t = PyObject_IsTrue(fired.get());
            if (t < 0) return nullptr;
            if (t) continue;
        }
        // ai._done_event_fired = True
        if (PyObject_SetAttr(ai.get(), n->done_fired, Py_True) < 0) return nullptr;
        // get_ai = getattr(ship, "GetAI", None)
        // still_installed = (get_ai() is ai) if callable(get_ai) else True
        // if not still_installed: continue
        {
            Ref get_ai(getattr_or(ship.get(), n->get_ai, Py_None));
            if (!get_ai) return nullptr;
            if (PyCallable_Check(get_ai.get())) {
                Ref now(PyObject_CallNoArgs(get_ai.get()));
                if (!now) return nullptr;
                if (now.get() != ai.get()) continue;
            }
        }
        // clear = getattr(ship, "ClearAI", None)
        // if callable(clear): clear()  else: fire_ai_done(ship, ai)
        {
            Ref clear(getattr_or(ship.get(), n->clear_ai, Py_None));
            if (!clear) return nullptr;
            if (PyCallable_Check(clear.get())) {
                Ref r(PyObject_CallNoArgs(clear.get()));
                if (!r) return nullptr;
            } else {
                Ref fn(load_global(g, n->fire_ai_done));
                if (!fn) return nullptr;
                PyObject* a[2] = {ship.get(), ai.get()};
                Ref r(PyObject_Vectorcall(fn.get(), a, 2, nullptr));
                if (!r) return nullptr;
            }
        }
    }
    Py_RETURN_NONE;
}

PyObject* tick_all(PyObject*, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs != 2 || !PyDict_Check(args[1])) {
        PyErr_SetString(PyExc_TypeError, "aitree_tick_all(game_time, globals: dict)");
        return nullptr;
    }
    try {
        return tick_all_impl(args[0], args[1]);
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

// _note_due(when): `if when < _walk_min_due[0]: _walk_min_due[0] = when`.
PyObject* note_due(PyObject*, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs != 1) {
        PyErr_Format(PyExc_TypeError, "_note_due() takes 1 positional argument but %zd were given",
                     nargs);
        return nullptr;
    }
    PyObject* when = args[0];
    PyObject* cur = min_due();
    if (cur == nullptr) return nullptr;
    if (PyFloat_CheckExact(when) && PyFloat_CheckExact(cur)) {
        if (PyFloat_AS_DOUBLE(when) < PyFloat_AS_DOUBLE(cur)) set_min_due(when);
        Py_RETURN_NONE;
    }
    // The comparison can run Python (which may write the slot): it reads
    // the value it was handed, held.
    Ref held(Py_NewRef(cur));
    const int lt = compare(when, held.get(), Py_LT);
    if (lt < 0) return nullptr;
    if (lt) set_min_due(when);
    Py_RETURN_NONE;
}

PyObject* walk_min_due(PyObject*, PyObject* const*, Py_ssize_t nargs) {
    if (nargs != 0) {
        PyErr_SetString(PyExc_TypeError, "aitree_walk_min_due()");
        return nullptr;
    }
    PyObject* cur = min_due();
    return cur == nullptr ? nullptr : Py_NewRef(cur);
}

PyObject* walk_min_due_reset(PyObject*, PyObject* const*, Py_ssize_t nargs) {
    if (nargs != 0) {
        PyErr_SetString(PyExc_TypeError, "aitree_walk_min_due_reset()");
        return nullptr;
    }
    const Names* n = names();
    if (n == nullptr) return nullptr;
    set_min_due(n->inf);
    Py_RETURN_NONE;
}

PyObject* roster_count(PyObject*, PyObject* const*, Py_ssize_t nargs) {
    if (nargs != 0) {
        PyErr_SetString(PyExc_TypeError, "aitree_roster_count()");
        return nullptr;
    }
    return PyLong_FromUnsignedLongLong(g_roster_runs);
}

template <auto F>
PyCFunction fast() {
    return reinterpret_cast<PyCFunction>(reinterpret_cast<void (*)(void)>(F));
}

PyMethodDef kDefs[] = {
    {"aitree_tick_all", fast<tick_all>(), METH_FASTCALL,
     "aitree_tick_all(game_time, globals): ai_driver's per-tick roster and "
     "sleep scheduling (its _tick_all_ai_python), each root walk Python's "
     "tick_ai; `globals` is ai_driver's module dict."},
    {"aitree_note_due", fast<note_due>(), METH_FASTCALL,
     "aitree_note_due(when): record a node's next-update time in the walk in "
     "progress (ai_driver._note_due)."},
    {"aitree_walk_min_due", fast<walk_min_due>(), METH_FASTCALL,
     "aitree_walk_min_due() -> the earliest due time noted since the reset."},
    {"aitree_walk_min_due_reset", fast<walk_min_due_reset>(), METH_FASTCALL,
     "aitree_walk_min_due_reset(): the slot back to float('inf')."},
    {"aitree_roster_count", fast<roster_count>(), METH_FASTCALL,
     "aitree_roster_count() -> how many native rosters have started."},
};

}  // namespace

std::span<PyMethodDef> method_defs() { return kDefs; }

}  // namespace dauntless::host::aitree
