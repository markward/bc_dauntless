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
#include <utility>

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
    // Hands the reference to the caller.
    PyObject* steal() {
        PyObject* p = p_;
        p_ = nullptr;
        return p;
    }
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
    // S2, the condition evaluation.
    PyObject* evaluation_function;  // "_evaluation_function"
    PyObject* conditions;           // "_conditions"
    PyObject* status;               // "_status"
    PyObject* contained_ai;         // "_contained_ai"
    PyObject* get_status;           // "GetStatus"
    PyObject* eval_conditional;     // "_eval_conditional"
    PyObject* stock_eval;           // "_STOCK_EVAL_CONDITIONAL"
    PyObject* stock_get_status;     // "_STOCK_CONDITION_GETSTATUS"
    PyObject* us_active;            // "US_ACTIVE"
    PyObject* us_dormant;           // "US_DORMANT"
    PyObject* memoisable;           // "_memoisable_evalfunc"
    PyObject* memo_key_types;       // "_MEMO_KEY_TYPES"
    PyObject* evalfn_cache;         // "_evalfn_cache"
    PyObject* evalfn_memoisable;    // "_evalfn_memoisable"
    PyObject* inf;                  // float("inf")
    PyObject* zero;                 // 0
    PyObject* one;                  // 1
    PyObject* two;                  // 2
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
        {&n->evaluation_function, "_evaluation_function"},
        {&n->conditions, "_conditions"},
        {&n->status, "_status"},
        {&n->contained_ai, "_contained_ai"},
        {&n->get_status, "GetStatus"},
        {&n->eval_conditional, "_eval_conditional"},
        {&n->stock_eval, "_STOCK_EVAL_CONDITIONAL"},
        {&n->stock_get_status, "_STOCK_CONDITION_GETSTATUS"},
        {&n->us_active, "US_ACTIVE"},
        {&n->us_dormant, "US_DORMANT"},
        {&n->memoisable, "_memoisable_evalfunc"},
        {&n->memo_key_types, "_MEMO_KEY_TYPES"},
        {&n->evalfn_cache, "_evalfn_cache"},
        {&n->evalfn_memoisable, "_evalfn_memoisable"},
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
    n->two = PyLong_FromLong(2);
    if (!n->fromlist_iter || !n->fromlist_cloak || !n->inf || !n->zero || !n->one || !n->two)
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

// The Python roster's frame locals, in its co_varnames order (game_time, the
// parameter, is borrowed; still_installed is a bool and never held). Each
// keeps its object until the statement that rebinds that name, as a Python
// local does: rebinding is a move-assign, which stores the new object and
// THEN releases the old one (STORE_FAST's order), so a finaliser (SDK
// conditions tear down in __del__) runs at the same point. At a normal
// return they are released in index order, as _PyFrame_Clear does.
struct Frame {
    Ref iter_non_rock_ships, defensive_cloak, max_sleep, ship, due, ai, status, get_ai,
        clear;

    void release() {
        iter_non_rock_ships = Ref();
        defensive_cloak = Ref();
        max_sleep = Ref();
        ship = Ref();
        due = Ref();
        ai = Ref();
        status = Ref();
        get_ai = Ref();
        clear = Ref();
    }
    ~Frame() { release(); }
};

// The roster: `_tick_all_ai_python`'s body, statement for statement.
PyObject* tick_all_impl(PyObject* game_time, PyObject* g) {
    const Names* n = names();
    if (n == nullptr) return nullptr;
    ++g_roster_runs;
    Frame f;
    // from engine.appc.ship_iter import iter_non_rock_ships
    f.iter_non_rock_ships =
        Ref(import_from(n->ship_iter_mod, n->fromlist_iter, n->iter_non_rock_ships, g));
    if (!f.iter_non_rock_ships) return nullptr;
    // from engine.appc import defensive_cloak
    f.defensive_cloak = Ref(import_from(n->appc_pkg, n->fromlist_cloak, n->defensive_cloak, g));
    if (!f.defensive_cloak) return nullptr;
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
    f.max_sleep = Ref(load_global(g, n->max_sleep));
    if (!f.max_sleep) return nullptr;
    // for ship in iter_non_rock_ships():   (the call's result is dropped once
    // GET_ITER has its iterator; the iterator lives on the value stack)
    Ref it;
    {
        Ref roster(PyObject_CallNoArgs(f.iter_non_rock_ships.get()));
        if (!roster) return nullptr;
        it = Ref(PyObject_GetIter(roster.get()));
        if (!it) return nullptr;
    }
    for (;;) {
        {
            Ref next(PyIter_Next(it.get()));
            if (!next) {
                if (PyErr_Occurred()) return nullptr;
                break;
            }
            f.ship = std::move(next);  // the previous ship released here
        }
        // if defensive_cloak.is_defensive(ship): continue
        {
            Ref fn(PyObject_GetAttr(f.defensive_cloak.get(), n->is_defensive));
            if (!fn) return nullptr;
            Ref r(PyObject_CallOneArg(fn.get(), f.ship.get()));
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
            const int ms = PyObject_IsTrue(f.max_sleep.get());
            if (ms < 0) return nullptr;
            if (ms) {
                {
                    Ref d(walk_due_of(f.ship.get(), n));
                    if (!d) return nullptr;
                    f.due = std::move(d);
                }
                if (f.due.get() != Py_None) {
                    const int lt = compare(game_time, f.due.get(), Py_LT);
                    if (lt < 0) return nullptr;
                    if (lt) {
                        Ref cap(cap_of(game_time, f.max_sleep.get(), g));
                        if (!cap) return nullptr;
                        const int le = compare(f.due.get(), cap.get(), Py_LE);
                        if (le < 0) return nullptr;
                        if (le) continue;
                    }
                }
            }
        }
        // ai = ship.GetAI() if hasattr(ship, "GetAI") else None
        {
            PyObject* probe = nullptr;
            const int has = lookup_attr(f.ship.get(), n->get_ai, &probe);
            if (has < 0) return nullptr;
            Py_XDECREF(probe);
            Ref value;
            if (has) {
                value = Ref(PyObject_CallMethodNoArgs(f.ship.get(), n->get_ai));
                if (!value) return nullptr;
            } else {
                value = Ref(Py_NewRef(Py_None));
            }
            f.ai = std::move(value);
        }
        // if ai is not None:
        if (f.ai.get() == Py_None) continue;
        // _walk_min_due[0] = float("inf"); status = tick_ai(ai, game_time)
        set_min_due(n->inf);
        {
            Ref fn(load_global(g, n->tick_ai));
            if (!fn) return nullptr;
            PyObject* a[2] = {f.ai.get(), game_time};
            Ref value(PyObject_Vectorcall(fn.get(), a, 2, nullptr));
            if (!value) return nullptr;
            f.status = std::move(value);
        }
        // if max_sleep:
        //     ship.__dict__["_ai_next_walk_due"] = min(
        //         _walk_min_due[0], game_time + max_sleep * _TICK_SECONDS)
        {
            const int ms = PyObject_IsTrue(f.max_sleep.get());
            if (ms < 0) return nullptr;
            if (ms) {
                Ref v;
                {
                    // min's arguments are released when the call returns,
                    // before `ship.__dict__` is read.
                    Ref cur(Py_NewRef(g_min_due));
                    Ref cap(cap_of(game_time, f.max_sleep.get(), g));
                    if (!cap) return nullptr;
                    // min(a, b): b only when `b < a` (builtin min's own test).
                    const int lt = compare(cap.get(), cur.get(), Py_LT);
                    if (lt < 0) return nullptr;
                    v = Ref(Py_NewRef(lt ? cap.get() : cur.get()));
                }
                Ref d(PyObject_GetAttr(f.ship.get(), n->dict));
                if (!d) return nullptr;
                if (PyObject_SetItem(d.get(), n->walk_due, v.get()) < 0) return nullptr;
            }
        }
        // if status == US_DONE and not getattr(ai, "_done_event_fired", False):
        {
            Ref us_done(load_global(g, n->us_done));
            if (!us_done) return nullptr;
            const int eq = compare(f.status.get(), us_done.get(), Py_EQ);
            if (eq < 0) return nullptr;
            if (!eq) continue;
            Ref fired(getattr_or(f.ai.get(), n->done_fired, Py_False));
            if (!fired) return nullptr;
            const int t = PyObject_IsTrue(fired.get());
            if (t < 0) return nullptr;
            if (t) continue;
        }
        // ai._done_event_fired = True
        if (PyObject_SetAttr(f.ai.get(), n->done_fired, Py_True) < 0) return nullptr;
        // get_ai = getattr(ship, "GetAI", None)
        // still_installed = (get_ai() is ai) if callable(get_ai) else True
        // if not still_installed: continue
        {
            Ref value(getattr_or(f.ship.get(), n->get_ai, Py_None));
            if (!value) return nullptr;
            f.get_ai = std::move(value);
        }
        if (PyCallable_Check(f.get_ai.get())) {
            bool still_installed;
            {
                Ref now(PyObject_CallNoArgs(f.get_ai.get()));
                if (!now) return nullptr;
                still_installed = now.get() == f.ai.get();
            }  // IS_OP drops the call's result before the jump
            if (!still_installed) continue;
        }
        // clear = getattr(ship, "ClearAI", None)
        // if callable(clear): clear()  else: fire_ai_done(ship, ai)
        {
            Ref value(getattr_or(f.ship.get(), n->clear_ai, Py_None));
            if (!value) return nullptr;
            f.clear = std::move(value);
        }
        if (PyCallable_Check(f.clear.get())) {
            Ref r(PyObject_CallNoArgs(f.clear.get()));
            if (!r) return nullptr;
        } else {
            Ref fn(load_global(g, n->fire_ai_done));
            if (!fn) return nullptr;
            PyObject* a[2] = {f.ship.get(), f.ai.get()};
            Ref r(PyObject_Vectorcall(fn.get(), a, 2, nullptr));
            if (!r) return nullptr;
        }
    }
    // FOR_ITER's exhaustion drops the iterator; the return then clears the
    // frame's locals in index order.
    it = Ref();
    f.release();
    Py_RETURN_NONE;
}

// ── S2: the condition evaluation ────────────────────────────────────────────
// THE REFERENCE is ai_driver.py's `_refresh_conditional_status_python`,
// `_eval_conditional_python`, `_condition_statuses_python` and
// `_any_condition_python`; each step names the statement (and, where the
// order of effects matters, the bytecode) it stands for. Every frame-local
// lifetime follows the rule in aitree.h, comprehensions and generator
// expressions included: their iterator (`.0`) and loop variable are their
// own frame's locals, released in that order when they return (or, for a
// generator `any`/`all` stopped early, when it is dropped right after).

unsigned long long g_s2_runs = 0;         // native S2 entries
unsigned long long g_stock_reads = 0;     // GetStatus calls read directly

// `seq[i]` (BINARY_SUBSCR with a constant int): an exact tuple in range is
// read directly; anything else is Python's subscript. Owned.
PyObject* subscript(PyObject* seq, Py_ssize_t i, PyObject* index) {
    if (PyTuple_CheckExact(seq) && i < PyTuple_GET_SIZE(seq))
        return Py_NewRef(PyTuple_GET_ITEM(seq, i));
    return PyObject_GetItem(seq, index);
}

// `a OP b` jumped on, as COMPARE_OP then POP_JUMP_IF_*: the operands are
// released (left, then right) before the result's truth is taken, and the
// result after. Two exact floats compare as doubles. -1: an error is set.
int compare_owned(Ref a, Ref b, int op) {
    if (PyFloat_CheckExact(a.get()) && PyFloat_CheckExact(b.get())) {
        const int r = compare(a.get(), b.get(), op);
        a = Ref();
        b = Ref();
        return r;
    }
    Ref r(PyObject_RichCompare(a.get(), b.get(), op));
    a = Ref();
    b = Ref();
    if (!r) return -1;
    return PyObject_IsTrue(r.get());
}

// `obj.__dict__.get(key)`: the attribute each time (Python looks it up each
// time; an EvalFunc may even rebind it), then dict.get. Owned.
PyObject* own_dict_get(PyObject* obj, PyObject* key, const Names* n) {
    Ref d(PyObject_GetAttr(obj, n->dict));
    if (!d) return nullptr;
    if (PyDict_CheckExact(d.get())) {
        PyObject* v = PyDict_GetItemWithError(d.get(), key);
        if (v != nullptr) return Py_NewRef(v);
        if (PyErr_Occurred()) return nullptr;
        Py_RETURN_NONE;
    }
    return PyObject_CallMethodOneArg(d.get(), n->get, key);
}

// `obj.__dict__[key] = value` (STORE_SUBSCR: the value is already built).
int own_dict_set(PyObject* obj, PyObject* key, PyObject* value, const Names* n) {
    Ref d(PyObject_GetAttr(obj, n->dict));
    if (!d) return -1;
    return PyObject_SetItem(d.get(), key, value);
}

// The stock GetStatus, `_STOCK_CONDITION_GETSTATUS` = (function, its code
// at import), read from ai_driver's globals per native entry.
struct StockStatus {
    Ref fn, code;
};

int stock_status_of(PyObject* g, const Names* n, StockStatus* out) {
    Ref pair(load_global(g, n->stock_get_status));
    if (!pair) return -1;
    if (!PyTuple_CheckExact(pair.get()) || PyTuple_GET_SIZE(pair.get()) != 2) {
        PyErr_SetString(PyExc_TypeError,
                        "ai_driver._STOCK_CONDITION_GETSTATUS must be (function, code)");
        return -1;
    }
    out->fn = Ref(Py_NewRef(PyTuple_GET_ITEM(pair.get(), 0)));
    out->code = Ref(Py_NewRef(PyTuple_GET_ITEM(pair.get(), 1)));
    return 0;
}

// `c.GetStatus()`: Python's method lookup (LOAD_METHOD), then the call --
// except that when the lookup lands on the stock TGCondition.GetStatus (the
// very function, still with its own code) its body, `return self._status`,
// is run here instead of called. An instance attribute, a subclass override
// or a patched class is whatever the lookup finds, and is called. Owned.
PyObject* condition_status(PyObject* c, const StockStatus& stock, const Names* n) {
#if PY_VERSION_HEX < 0x030C0000
    PyObject* m = nullptr;
    const int unbound = _PyObject_GetMethod(c, n->get_status, &m);
    if (m == nullptr) return nullptr;
    Ref meth(m);
    if (unbound) {
        if (m == stock.fn.get() && PyFunction_Check(m) &&
            PyFunction_GET_CODE(m) == stock.code.get()) {
            ++g_stock_reads;
            return PyObject_GetAttr(c, n->status);
        }
        PyObject* a[1] = {c};
        return PyObject_Vectorcall(m, a, 1, nullptr);
    }
    return PyObject_CallNoArgs(m);
#else
    Ref meth(PyObject_GetAttr(c, n->get_status));
    if (!meth) return nullptr;
    if (PyMethod_Check(meth.get()) && PyMethod_GET_SELF(meth.get()) == c) {
        PyObject* f = PyMethod_GET_FUNCTION(meth.get());
        if (f == stock.fn.get() && PyFunction_Check(f) &&
            PyFunction_GET_CODE(f) == stock.code.get()) {
            ++g_stock_reads;
            return PyObject_GetAttr(c, n->status);
        }
    }
    return PyObject_CallNoArgs(meth.get());
#endif
}

// `[c.GetStatus() for c in ai._conditions]`. Owned list.
PyObject* statuses_of(PyObject* ai, const StockStatus& stock, const Names* n) {
    // LOAD_ATTR _conditions; GET_ITER (the list ref goes, the iterator stays)
    Ref it;
    {
        Ref conds(PyObject_GetAttr(ai, n->conditions));
        if (!conds) return nullptr;
        it = Ref(PyObject_GetIter(conds.get()));
        if (!it) return nullptr;
    }
    // The comprehension's frame: `.0` (it), `c`.
    Ref c;
    Ref out(PyList_New(0));
    if (!out) return nullptr;
    for (;;) {
        {
            Ref next(PyIter_Next(it.get()));
            if (!next) {
                if (PyErr_Occurred()) return nullptr;
                break;
            }
            c = std::move(next);
        }
        Ref v(condition_status(c.get(), stock, n));
        if (!v) return nullptr;
        if (PyList_Append(out.get(), v.get()) < 0) return nullptr;
    }
    it = Ref();
    c = Ref();
    return out.steal();
}

// `any(c.GetStatus() != 0 for c in ai._conditions)`: 1, 0, or -1 (error).
// Stops at the first non-zero, as `any` does.
int any_condition_of(PyObject* ai, const StockStatus& stock, const Names* n) {
    Ref it;
    {
        Ref conds(PyObject_GetAttr(ai, n->conditions));
        if (!conds) return -1;
        it = Ref(PyObject_GetIter(conds.get()));
        if (!it) return -1;
    }
    // The generator's frame: `.0` (it), `c`.
    Ref c;
    int found = 0;
    for (;;) {
        {
            Ref next(PyIter_Next(it.get()));
            if (!next) {
                if (PyErr_Occurred()) return -1;
                break;
            }
            c = std::move(next);
        }
        Ref v(condition_status(c.get(), stock, n));
        if (!v) return -1;
        // COMPARE_OP != 0 (the status released), YIELD; any(): truth, then
        // the yielded value released.
        Ref r(PyObject_RichCompare(v.get(), n->zero, Py_NE));
        v = Ref();
        if (!r) return -1;
        const int t = PyObject_IsTrue(r.get());
        r = Ref();
        if (t < 0) return -1;
        if (t) {
            found = 1;
            break;
        }
    }
    it = Ref();
    c = Ref();
    return found;
}

// `all(type(a) in _MEMO_KEY_TYPES for a in args)`: 1, 0, or -1 (error).
// `_MEMO_KEY_TYPES` is looked up per element, as the generator does.
int all_key_types(PyObject* args, PyObject* g, const Names* n) {
    Ref it(PyObject_GetIter(args));
    if (!it) return -1;
    Ref a;  // the generator's frame: `.0` (it), `a`
    int all = 1;
    for (;;) {
        {
            Ref next(PyIter_Next(it.get()));
            if (!next) {
                if (PyErr_Occurred()) return -1;
                break;
            }
            a = std::move(next);
        }
        Ref t(Py_NewRef(reinterpret_cast<PyObject*>(Py_TYPE(a.get()))));
        Ref types(load_global(g, n->memo_key_types));
        if (!types) return -1;
        // CONTAINS_OP: the operands released (left, right) after the test.
        const int in = PySequence_Contains(types.get(), t.get());
        t = Ref();
        types = Ref();
        if (in < 0) return -1;
        if (!in) {
            all = 0;
            break;
        }
    }
    it = Ref();
    a = Ref();
    return all;
}

// `_eval_conditional_python(ai, eval_fn, args)`, statement for statement.
// Owned status.
PyObject* eval_impl(PyObject* ai, PyObject* eval_fn, PyObject* args, PyObject* g,
                    const Names* n) {
    // The frame's own locals (co_varnames: ai, eval_fn, args, key, cache,
    // raised, status, verdict), released at return in that order.
    struct Frame {
        Ref key, cache, status, verdict;
        void release() {
            key = Ref();
            cache = Ref();
            status = Ref();
            verdict = Ref();
        }
        ~Frame() { release(); }
    } f;
    bool raised = false;
    // key = tuple(args)
    f.key = Ref(PySequence_Tuple(args));
    if (!f.key) return nullptr;
    // cache = ai.__dict__.get("_evalfn_cache")
    f.cache = Ref(own_dict_get(ai, n->evalfn_cache, n));
    if (!f.cache) return nullptr;
    // if cache is not None and cache[0] is eval_fn and cache[1] == key:
    //     return cache[2]
    if (f.cache.get() != Py_None) {
        bool same_fn;
        {
            Ref c0(subscript(f.cache.get(), 0, n->zero));
            if (!c0) return nullptr;
            same_fn = c0.get() == eval_fn;
        }
        if (same_fn) {
            Ref c1(subscript(f.cache.get(), 1, n->one));
            if (!c1) return nullptr;
            const int eq = compare_owned(std::move(c1), Ref(Py_NewRef(f.key.get())), Py_EQ);
            if (eq < 0) return nullptr;
            if (eq) {
                Ref hit(subscript(f.cache.get(), 2, n->two));
                if (!hit) return nullptr;
                f.release();
                return hit.steal();
            }
        }
    }
    // raised = False
    // try: status = eval_fn(*args)
    // except Exception: raised = True; status = US_DORMANT
    {
        Ref result;
        {
            Ref callargs(PyTuple_CheckExact(args) ? Py_NewRef(args) : PySequence_Tuple(args));
            if (callargs) result = Ref(PyObject_Call(eval_fn, callargs.get(), nullptr));
        }  // CALL_FUNCTION_EX drops its argument tuple before the store
        if (result) {
            f.status = std::move(result);
        } else {
            if (!PyErr_ExceptionMatches(PyExc_Exception)) return nullptr;
            // The handled exception lives until POP_EXCEPT, after the body.
            PyObject *et, *ev, *etb;
            PyErr_Fetch(&et, &ev, &etb);
            raised = true;
            Ref dormant(load_global(g, n->us_dormant));
            if (!dormant) {
                // Raised inside the handler: the caught one is its context.
                _PyErr_ChainExceptions(et, ev, etb);
                return nullptr;
            }
            f.status = std::move(dormant);
            Py_XDECREF(et);
            Py_XDECREF(ev);
            Py_XDECREF(etb);
        }
    }
    // if status is None: status = US_DORMANT
    if (f.status.get() == Py_None) {
        Ref dormant(load_global(g, n->us_dormant));
        if (!dormant) return nullptr;
        f.status = std::move(dormant);
    }
    // status = int(status)
    {
        Ref as_int(PyNumber_Long(f.status.get()));
        if (!as_int) return nullptr;
        f.status = std::move(as_int);
    }
    // verdict = ai.__dict__.get("_evalfn_memoisable")
    f.verdict = Ref(own_dict_get(ai, n->evalfn_memoisable, n));
    if (!f.verdict) return nullptr;
    // if verdict is None or verdict[0] is not eval_fn:
    //     verdict = (eval_fn, _memoisable_evalfunc(eval_fn))
    //     ai.__dict__["_evalfn_memoisable"] = verdict
    bool take = f.verdict.get() == Py_None;
    if (!take) {
        Ref v0(subscript(f.verdict.get(), 0, n->zero));
        if (!v0) return nullptr;
        take = v0.get() != eval_fn;
    }
    if (take) {
        Ref fresh;
        {
            Ref fn(load_global(g, n->memoisable));
            if (!fn) return nullptr;
            Ref ok(PyObject_CallOneArg(fn.get(), eval_fn));
            if (!ok) return nullptr;
            fresh = Ref(PyTuple_Pack(2, eval_fn, ok.get()));
            if (!fresh) return nullptr;
        }
        f.verdict = std::move(fresh);
        if (own_dict_set(ai, n->evalfn_memoisable, f.verdict.get(), n) < 0) return nullptr;
    }
    // if verdict[1] and not raised and all(type(a) in _MEMO_KEY_TYPES
    //                                      for a in args):
    //     ai.__dict__["_evalfn_cache"] = (eval_fn, key, status)
    int memoise;
    {
        Ref v1(subscript(f.verdict.get(), 1, n->one));
        if (!v1) return nullptr;
        memoise = PyObject_IsTrue(v1.get());
    }
    if (memoise < 0) return nullptr;
    if (memoise && !raised) {
        memoise = all_key_types(args, g, n);
        if (memoise < 0) return nullptr;
        if (memoise) {
            Ref entry(PyTuple_Pack(3, eval_fn, f.key.get(), f.status.get()));
            if (!entry) return nullptr;
            if (own_dict_set(ai, n->evalfn_cache, entry.get(), n) < 0) return nullptr;
        }
    }
    // return status
    Ref ret(Py_NewRef(f.status.get()));
    f.release();
    return ret.steal();
}

// `_refresh_conditional_status_python(ai)`, statement for statement.
PyObject* refresh_impl(PyObject* ai, PyObject* g) {
    const Names* n = names();
    if (n == nullptr) return nullptr;
    ++g_s2_runs;
    StockStatus stock;
    if (stock_status_of(g, n, &stock) < 0) return nullptr;
    // The frame's locals (co_varnames: ai, eval_fn, args).
    struct Frame {
        Ref eval_fn, args;
        void release() {
            eval_fn = Ref();
            args = Ref();
        }
        ~Frame() { release(); }
    } f;
    // eval_fn = ai._evaluation_function
    f.eval_fn = Ref(PyObject_GetAttr(ai, n->evaluation_function));
    if (!f.eval_fn) return nullptr;
    if (f.eval_fn.get() != Py_None) {
        // args = [c.GetStatus() for c in ai._conditions]
        f.args = Ref(statuses_of(ai, stock, n));
        if (!f.args) return nullptr;
        // ai._status = _eval_conditional(ai, eval_fn, args)
        {
            Ref value;
            {
                Ref fn(load_global(g, n->eval_conditional));
                if (!fn) return nullptr;
                Ref stock_fn(load_global(g, n->stock_eval));
                if (!stock_fn) return nullptr;
                if (fn.get() == stock_fn.get()) {
                    value = Ref(eval_impl(ai, f.eval_fn.get(), f.args.get(), g, n));
                } else {
                    PyObject* a[3] = {ai, f.eval_fn.get(), f.args.get()};
                    value = Ref(PyObject_Vectorcall(fn.get(), a, 3, nullptr));
                }
                if (!value) return nullptr;
            }
            if (PyObject_SetAttr(ai, n->status, value.get()) < 0) return nullptr;
        }
        // if (ai._status == US_ACTIVE and ai._contained_ai is not None
        //         and ai._contained_ai._status == US_DONE):
        //     ai._status = US_DONE
        {
            Ref st(PyObject_GetAttr(ai, n->status));
            if (!st) return nullptr;
            Ref active(load_global(g, n->us_active));
            if (!active) return nullptr;
            const int is_active = compare_owned(std::move(st), std::move(active), Py_EQ);
            if (is_active < 0) return nullptr;
            if (is_active) {
                bool has_contained;
                {
                    Ref ca(PyObject_GetAttr(ai, n->contained_ai));
                    if (!ca) return nullptr;
                    has_contained = ca.get() != Py_None;
                }
                if (has_contained) {
                    Ref cst;
                    {
                        Ref ca(PyObject_GetAttr(ai, n->contained_ai));
                        if (!ca) return nullptr;
                        cst = Ref(PyObject_GetAttr(ca.get(), n->status));
                        if (!cst) return nullptr;
                    }
                    Ref done(load_global(g, n->us_done));
                    if (!done) return nullptr;
                    const int is_done = compare_owned(std::move(cst), std::move(done), Py_EQ);
                    if (is_done < 0) return nullptr;
                    if (is_done) {
                        Ref d(load_global(g, n->us_done));
                        if (!d) return nullptr;
                        if (PyObject_SetAttr(ai, n->status, d.get()) < 0) return nullptr;
                    }
                }
            }
        }
        f.release();
        Py_RETURN_NONE;
    }
    // if not ai._conditions: return
    {
        Ref conds(PyObject_GetAttr(ai, n->conditions));
        if (!conds) return nullptr;
        const int t = PyObject_IsTrue(conds.get());
        if (t < 0) return nullptr;
        if (!t) {
            conds = Ref();
            f.release();
            Py_RETURN_NONE;
        }
    }
    // ai._status = US_ACTIVE if any(c.GetStatus() != 0 for c in ...) else US_DORMANT
    const int any = any_condition_of(ai, stock, n);
    if (any < 0) return nullptr;
    Ref value(load_global(g, any ? n->us_active : n->us_dormant));
    if (!value) return nullptr;
    if (PyObject_SetAttr(ai, n->status, value.get()) < 0) return nullptr;
    value = Ref();
    f.release();
    Py_RETURN_NONE;
}

template <typename F>
PyObject* guarded(F&& body) {
    try {
        return body();
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

PyObject* refresh_conditional(PyObject*, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs != 2 || !PyDict_Check(args[1])) {
        PyErr_SetString(PyExc_TypeError, "aitree_refresh_conditional(ai, globals: dict)");
        return nullptr;
    }
    return guarded([&] { return refresh_impl(args[0], args[1]); });
}

PyObject* eval_conditional(PyObject*, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs != 4 || !PyDict_Check(args[3])) {
        PyErr_SetString(PyExc_TypeError,
                        "aitree_eval_conditional(ai, eval_fn, args, globals: dict)");
        return nullptr;
    }
    return guarded([&]() -> PyObject* {
        const Names* n = names();
        if (n == nullptr) return nullptr;
        ++g_s2_runs;
        return eval_impl(args[0], args[1], args[2], args[3], n);
    });
}

PyObject* condition_statuses(PyObject*, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs != 2 || !PyDict_Check(args[1])) {
        PyErr_SetString(PyExc_TypeError, "aitree_condition_statuses(ai, globals: dict)");
        return nullptr;
    }
    return guarded([&]() -> PyObject* {
        const Names* n = names();
        if (n == nullptr) return nullptr;
        ++g_s2_runs;
        StockStatus stock;
        if (stock_status_of(args[1], n, &stock) < 0) return nullptr;
        return statuses_of(args[0], stock, n);
    });
}

PyObject* any_condition(PyObject*, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs != 2 || !PyDict_Check(args[1])) {
        PyErr_SetString(PyExc_TypeError, "aitree_any_condition(ai, globals: dict)");
        return nullptr;
    }
    return guarded([&]() -> PyObject* {
        const Names* n = names();
        if (n == nullptr) return nullptr;
        ++g_s2_runs;
        StockStatus stock;
        if (stock_status_of(args[1], n, &stock) < 0) return nullptr;
        const int any = any_condition_of(args[0], stock, n);
        if (any < 0) return nullptr;
        return Py_NewRef(any ? Py_True : Py_False);
    });
}

PyObject* conditional_counts(PyObject*, PyObject* const*, Py_ssize_t nargs) {
    if (nargs != 0) {
        PyErr_SetString(PyExc_TypeError, "aitree_conditional_counts()");
        return nullptr;
    }
    return Py_BuildValue("(KK)", g_s2_runs, g_stock_reads);
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
    {"aitree_refresh_conditional", fast<refresh_conditional>(), METH_FASTCALL,
     "aitree_refresh_conditional(ai, globals): ai_driver's "
     "_refresh_conditional_status_python (the memoised EvalFunc, or the "
     "any-non-zero rule, then the contained-DONE fold)."},
    {"aitree_eval_conditional", fast<eval_conditional>(), METH_FASTCALL,
     "aitree_eval_conditional(ai, eval_fn, args, globals) -> ai_driver's "
     "_eval_conditional_python: the pre-fold status, through the memo."},
    {"aitree_condition_statuses", fast<condition_statuses>(), METH_FASTCALL,
     "aitree_condition_statuses(ai, globals) -> "
     "[c.GetStatus() for c in ai._conditions]."},
    {"aitree_any_condition", fast<any_condition>(), METH_FASTCALL,
     "aitree_any_condition(ai, globals) -> "
     "any(c.GetStatus() != 0 for c in ai._conditions)."},
    {"aitree_conditional_counts", fast<conditional_counts>(), METH_FASTCALL,
     "aitree_conditional_counts() -> (native condition-evaluation entries, "
     "stock GetStatus calls read directly)."},
};

}  // namespace

std::span<PyMethodDef> method_defs() { return kDefs; }

}  // namespace dauntless::host::aitree
