// native/src/host/aitree.cc -- see aitree.h.
//
// THE REFERENCE is the Python oracle, tests/helpers/ai_walker_oracle.py (the
// former engine/appc/ai_driver.py `_tick_all_ai_python`, `_tick_ai_python`
// and the rest, verbatim at commit 1a9aa97af, kept equal to this walk since)
// and `_note_due`'s former Python body;
// each step below names the statement it stands for. The arithmetic is Python's, in its operand order,
// with no multiply-add contracted (the pragma here; -ffp-contract=off from
// CMake for other compilers).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "aitree.h"

#include <algorithm>
#include <new>
#include <string_view>
#include <utility>
#include <vector>

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
    PyObject* stock_get_status;     // "_STOCK_CONDITION_GETSTATUS"
    PyObject* us_active;            // "US_ACTIVE"
    PyObject* us_dormant;           // "US_DORMANT"
    PyObject* memoisable;           // "_memoisable_evalfunc"
    PyObject* memo_key_types;       // "_MEMO_KEY_TYPES"
    PyObject* evalfn_cache;         // "_evalfn_cache"
    PyObject* evalfn_memoisable;    // "_evalfn_memoisable"
    // S4, the walk.
    PyObject* focus_depth;           // "_focus_depth"
    PyObject* ooa_cache;             // "_ooa_cache"
    PyObject* reached;               // "_reached_this_tick"
    PyObject* reached_all;           // "_reached_this_tick_all"
    PyObject* reached_all_ids;       // "_reached_this_tick_all_ids"
    PyObject* pending;               // "_pending_got_focus"
    PyObject* dispatch_ai;           // "_dispatch_ai"
    PyObject* reconcile_focus;       // "_reconcile_focus"
    PyObject* flush_pending;         // "_flush_pending_got_focus"
    PyObject* reconcile_active;      // "_reconcile_active"
    PyObject* aitree_tick;           // "_aitree_tick"
    PyObject* stock_walk;            // "_STOCK_WALK"
    PyObject* stock_handlers;        // "_STOCK_HANDLERS"
    PyObject* get_ship;              // "GetShip"
    PyObject* ship_death;            // "ship_death"
    PyObject* out_of_action;         // "_out_of_action"
    PyObject* dispatch_by_type;      // "_DISPATCH_BY_TYPE"
    PyObject* unresolved;            // "_UNRESOLVED"
    PyObject* resolve_dispatch;      // "_resolve_dispatch"
    PyObject* timed_dispatch;        // "_timed_dispatch"
    PyObject* append;                // "append"
    PyObject* add;                   // "add"
    PyObject* clear;                 // "clear"
    PyObject* update_m;              // "update"
    PyObject* remove;                // "remove"
    PyObject* has_focus;             // "_has_focus"
    PyObject* next_update_time;      // "_next_update_time"
    PyObject* get_script_instance;   // "GetScriptInstance"
    PyObject* update;                // "Update"
    PyObject* get_next_update_time;  // "GetNextUpdateTime"
    PyObject* run_script_step;       // "_run_script_step"
    PyObject* note_due;              // "_note_due"
    PyObject* note_due_ret;          // "_note_due_ret"
    PyObject* queue_got_focus;       // "_queue_got_focus"
    PyObject* focus_instance_of;     // "_focus_instance_of"
    PyObject* got_focus_called;      // "_got_focus_called"
    PyObject* script_instance;       // "_script_instance"
    PyObject* preprocessing_instance; // "_preprocessing_instance"
    PyObject* ais;                   // "_ais"
    PyObject* conditional_cls;       // "ConditionalAI"
    PyObject* preprocessing_cls;     // "PreprocessingAI"
    PyObject* refresh_cond;          // "_refresh_conditional_status"
    PyObject* aitree_refresh;        // "_aitree_refresh_conditional"
    PyObject* dispatch_priority_child; // "_dispatch_priority_child"
    PyObject* current_index;         // "_current_index"
    PyObject* loops_remaining;       // "_loops_remaining"
    PyObject* skip_dormant;          // "_skip_dormant"
    PyObject* current_child;         // "_current_child"
    PyObject* untried;               // "_untried"
    PyObject* random;                // "random"
    PyObject* choice;                // "choice"
    PyObject* condition_statuses;    // "_condition_statuses"
    PyObject* aitree_statuses;       // "_aitree_condition_statuses"
    PyObject* any_condition;         // "_any_condition"
    PyObject* aitree_any;            // "_aitree_any_condition"
    PyObject* aitree_eval;           // "_aitree_eval_conditional"
    PyObject* preprocessing_method;  // "_preprocessing_method"
    PyObject* damage_event;          // "DamageEvent"
    PyObject* pcodeai;               // "pCodeAI"
    PyObject* ensure_select;         // "_ensure_select_target_initialized"
    PyObject* arity_cache;           // "_preprocess_arity_cache"
    PyObject* inspect;               // "inspect"
    PyObject* signature;             // "signature"
    PyObject* parameters;            // "parameters"
    PyObject* values;                // "values"
    PyObject* kind;                  // "kind"
    PyObject* parameter;             // "Parameter"
    PyObject* positional_only;       // "POSITIONAL_ONLY"
    PyObject* positional_or_keyword; // "POSITIONAL_OR_KEYWORD"
    PyObject* is_interruptable;      // "IsInterruptable"
    PyObject* last_preprocess_status; // "_last_preprocess_status"
    PyObject* sync_fire;             // "_sync_fire_script_target_subsystem"
    PyObject* ps_normal;             // "PS_NORMAL"
    PyObject* ps_skip_active;        // "PS_SKIP_ACTIVE"
    PyObject* ps_skip_dormant;       // "PS_SKIP_DORMANT"
    PyObject* retain_focus;          // "_retain_subtree_focus"
    PyObject* activation_failed;     // "_activation_failed"
    PyObject* activated;             // "_activated"
    PyObject* activate_builder;      // "_activate_builder"
    PyObject* tick_preprocessing;    // "_tick_preprocessing"
    // S3, the root-end reconciliation.
    PyObject* focused_preprocessors; // "_focused_preprocessors"
    PyObject* active_nodes;          // "_active_nodes"
    PyObject* dispatch_lost_focus;   // "_dispatch_lost_focus"
    PyObject* lost_focus;            // "LostFocus"
    PyObject* got_focus;             // "GotFocus"
    PyObject* set_active;            // "SetActive"
    PyObject* set_inactive;          // "SetInactive"
    PyObject* is_active_in_tree;     // "_is_active_in_tree"
    PyObject* stock_set_active;      // "_STOCK_SET_ACTIVE"
    PyObject* stock_set_inactive;    // "_STOCK_SET_INACTIVE"
    PyObject* whole_slice;          // slice(None, None) (`x[:]`)
    PyObject* inf;                  // float("inf")
    PyObject* zero;                 // 0
    PyObject* one;                  // 1
    PyObject* two;                  // 2
    PyObject* fzero;                // 0.0
    PyObject* fone;                 // 1.0
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
        {&n->stock_get_status, "_STOCK_CONDITION_GETSTATUS"},
        {&n->us_active, "US_ACTIVE"},
        {&n->us_dormant, "US_DORMANT"},
        {&n->memoisable, "_memoisable_evalfunc"},
        {&n->memo_key_types, "_MEMO_KEY_TYPES"},
        {&n->evalfn_cache, "_evalfn_cache"},
        {&n->evalfn_memoisable, "_evalfn_memoisable"},
        {&n->focus_depth, "_focus_depth"},
        {&n->ooa_cache, "_ooa_cache"},
        {&n->reached, "_reached_this_tick"},
        {&n->reached_all, "_reached_this_tick_all"},
        {&n->reached_all_ids, "_reached_this_tick_all_ids"},
        {&n->pending, "_pending_got_focus"},
        {&n->dispatch_ai, "_dispatch_ai"},
        {&n->reconcile_focus, "_reconcile_focus"},
        {&n->flush_pending, "_flush_pending_got_focus"},
        {&n->reconcile_active, "_reconcile_active"},
        {&n->aitree_tick, "_aitree_tick"},
        {&n->stock_walk, "_STOCK_WALK"},
        {&n->stock_handlers, "_STOCK_HANDLERS"},
        {&n->get_ship, "GetShip"},
        {&n->ship_death, "ship_death"},
        {&n->out_of_action, "_out_of_action"},
        {&n->dispatch_by_type, "_DISPATCH_BY_TYPE"},
        {&n->unresolved, "_UNRESOLVED"},
        {&n->resolve_dispatch, "_resolve_dispatch"},
        {&n->timed_dispatch, "_timed_dispatch"},
        {&n->append, "append"},
        {&n->add, "add"},
        {&n->clear, "clear"},
        {&n->update_m, "update"},
        {&n->remove, "remove"},
        {&n->has_focus, "_has_focus"},
        {&n->next_update_time, "_next_update_time"},
        {&n->get_script_instance, "GetScriptInstance"},
        {&n->update, "Update"},
        {&n->get_next_update_time, "GetNextUpdateTime"},
        {&n->run_script_step, "_run_script_step"},
        {&n->note_due, "_note_due"},
        {&n->note_due_ret, "_note_due_ret"},
        {&n->queue_got_focus, "_queue_got_focus"},
        {&n->focus_instance_of, "_focus_instance_of"},
        {&n->got_focus_called, "_got_focus_called"},
        {&n->script_instance, "_script_instance"},
        {&n->preprocessing_instance, "_preprocessing_instance"},
        {&n->ais, "_ais"},
        {&n->conditional_cls, "ConditionalAI"},
        {&n->preprocessing_cls, "PreprocessingAI"},
        {&n->refresh_cond, "_refresh_conditional_status"},
        {&n->aitree_refresh, "_aitree_refresh_conditional"},
        {&n->dispatch_priority_child, "_dispatch_priority_child"},
        {&n->current_index, "_current_index"},
        {&n->loops_remaining, "_loops_remaining"},
        {&n->skip_dormant, "_skip_dormant"},
        {&n->current_child, "_current_child"},
        {&n->untried, "_untried"},
        {&n->random, "random"},
        {&n->choice, "choice"},
        {&n->condition_statuses, "_condition_statuses"},
        {&n->aitree_statuses, "_aitree_condition_statuses"},
        {&n->any_condition, "_any_condition"},
        {&n->aitree_any, "_aitree_any_condition"},
        {&n->aitree_eval, "_aitree_eval_conditional"},
        {&n->preprocessing_method, "_preprocessing_method"},
        {&n->damage_event, "DamageEvent"},
        {&n->pcodeai, "pCodeAI"},
        {&n->ensure_select, "_ensure_select_target_initialized"},
        {&n->arity_cache, "_preprocess_arity_cache"},
        {&n->inspect, "inspect"},
        {&n->signature, "signature"},
        {&n->parameters, "parameters"},
        {&n->values, "values"},
        {&n->kind, "kind"},
        {&n->parameter, "Parameter"},
        {&n->positional_only, "POSITIONAL_ONLY"},
        {&n->positional_or_keyword, "POSITIONAL_OR_KEYWORD"},
        {&n->is_interruptable, "IsInterruptable"},
        {&n->last_preprocess_status, "_last_preprocess_status"},
        {&n->sync_fire, "_sync_fire_script_target_subsystem"},
        {&n->ps_normal, "PS_NORMAL"},
        {&n->ps_skip_active, "PS_SKIP_ACTIVE"},
        {&n->ps_skip_dormant, "PS_SKIP_DORMANT"},
        {&n->retain_focus, "_retain_subtree_focus"},
        {&n->activation_failed, "_activation_failed"},
        {&n->activated, "_activated"},
        {&n->activate_builder, "_activate_builder"},
        {&n->tick_preprocessing, "_tick_preprocessing"},
        {&n->focused_preprocessors, "_focused_preprocessors"},
        {&n->active_nodes, "_active_nodes"},
        {&n->dispatch_lost_focus, "_dispatch_lost_focus"},
        {&n->lost_focus, "LostFocus"},
        {&n->got_focus, "GotFocus"},
        {&n->set_active, "SetActive"},
        {&n->set_inactive, "SetInactive"},
        {&n->is_active_in_tree, "_is_active_in_tree"},
        {&n->stock_set_active, "_STOCK_SET_ACTIVE"},
        {&n->stock_set_inactive, "_STOCK_SET_INACTIVE"},
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
    n->fzero = PyFloat_FromDouble(0.0);
    n->fone = PyFloat_FromDouble(1.0);
    n->whole_slice = PySlice_New(Py_None, Py_None, nullptr);
    if (!n->fromlist_iter || !n->fromlist_cloak || !n->inf || !n->zero || !n->one || !n->two ||
        !n->fzero || !n->fone || !n->whole_slice)
        return nullptr;
    g_names = n;
    return n;
}

// ai_driver's globals and the name table, for one native entry.
struct Ctx {
    PyObject* g;
    const Names* n;
};

// The walk (S4, below): `tick_ai(node, game_time)` with the global loaded.
PyObject* run_tick(const Ctx& c, PyObject* fn, PyObject* node, PyObject* gt);

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
            case Py_NE: return x != y;
            case Py_GT: return x > y;
            case Py_GE: return x >= y;
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

// The roster: the oracle's `_tick_all_ai_python`, statement for statement.
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
            Ref value(run_tick(Ctx{g, n}, fn.get(), f.ai.get(), game_time));
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
// THE REFERENCE is the oracle's (tests/helpers/ai_walker_oracle.py)
// `_refresh_conditional_status_python`, `_eval_conditional_python`,
// `_condition_statuses_python` and `_any_condition_python`; each step names the statement (and, where the
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

// Set the pending-exception context: the fetched exception (et, ev, etb) is
// the context of the one now raised. Takes the three references.
// 3.11 has `_PyErr_ChainExceptions(type, value, tb)`; 3.12 replaced it with
// `_PyErr_ChainExceptions1(exc)` and 3.13 removed the old name. The #else arm
// is UNCOMPILED here (only 3.11 headers are installed): written from the 3.12
// API, to be checked on first build against a newer Python.
void chain_exceptions(PyObject* et, PyObject* ev, PyObject* etb) {
#if PY_VERSION_HEX < 0x030C0000
    _PyErr_ChainExceptions(et, ev, etb);
#else
    PyErr_NormalizeException(&et, &ev, &etb);
    if (ev != nullptr && etb != nullptr) PyException_SetTraceback(ev, etb);
    Py_XDECREF(et);
    Py_XDECREF(etb);
    _PyErr_ChainExceptions1(ev);
#endif
}

// The oracle's `_eval_conditional_python(ai, eval_fn, args)`, statement for statement.
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
                chain_exceptions(et, ev, etb);
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

PyObject* eval_conditional_call(const Ctx& c, PyObject* ai, PyObject* eval_fn, PyObject* args,
                                 bool count_entry = true);

// The oracle's `_refresh_conditional_status_python(ai)`, statement for statement.
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
            // The call goes through the same routing as _tick_conditional's:
            // native only while the global is stock (same code, same binding).
            // refresh_impl already counted this entry (++g_s2_runs above).
            Ref value(eval_conditional_call(Ctx{g, n}, ai, f.eval_fn.get(), f.args.get(),
                                            /*count_entry=*/false));
            if (!value) return nullptr;
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

// ── S4: the walk ────────────────────────────────────────────────────────────
// THE REFERENCE is the oracle's `_tick_ai_python`, `_dispatch_ai`, the
// stock `_tick_*` handlers and the helpers they call by global name
// (`_dispatch_priority_child`, `_queue_got_focus`, `_focus_instance_of`,
// `_retain_subtree_focus`, `_note_due_ret`); each step names the statement it
// stands for. The rules (aitree.h) in short:
//  - every module global is read when Python reads it (LOAD_GLOBAL), the walk
//    state included: `_focus_depth`, `_ooa_cache`, `_reached_this_tick`,
//    `_reached_this_tick_all(_ids)` and `_pending_got_focus` stay ai_driver's
//    module globals, rebound at a root walk as Python rebinds them, so a
//    Python handler (a patched one, or a test's), a patched reconciler and
//    the native root end (S3, below) see exactly the lists Python's walk
//    would hand them;
//  - a driver function runs natively only while its global is the stock one
//    (`_STOCK_WALK` / `_STOCK_HANDLERS`: the very function with its code at
//    import); anything else in its place is called, at the same point;
//  - each Python local is an owned slot at function scope, rebound by
//    move-assignment where Python rebinds it, released in co_varnames order
//    at return (cells after plain locals).

unsigned long long g_tick_runs = 0;            // native walks started
enum Kind {
    kNotStock = 0,
    kPlain = 1,  // _STOCK_HANDLERS' order
    kPriorityList,
    kSequence,
    kRandom,
    kConditional,
    kPreprocessing,
    kBuilder,
    kKinds
};
unsigned long long g_kind_runs[kKinds] = {};   // native runs per stock handler

PyObject* tick(PyObject*, PyObject* const*, Py_ssize_t);
PyObject* note_due(PyObject*, PyObject* const*, Py_ssize_t);
PyObject* refresh_conditional(PyObject*, PyObject* const*, Py_ssize_t);
PyObject* eval_conditional(PyObject*, PyObject* const*, Py_ssize_t);
PyObject* condition_statuses(PyObject*, PyObject* const*, Py_ssize_t);
PyObject* any_condition(PyObject*, PyObject* const*, Py_ssize_t);

template <auto F>
PyCFunction fast() {
    return reinterpret_cast<PyCFunction>(reinterpret_cast<void (*)(void)>(F));
}

// `if when < slot: slot = when` (the native _note_due's body). 0, or -1.
int note_due_value(PyObject* when) {
    PyObject* cur = min_due();
    if (cur == nullptr) return -1;
    if (PyFloat_CheckExact(when) && PyFloat_CheckExact(cur)) {
        if (PyFloat_AS_DOUBLE(when) < PyFloat_AS_DOUBLE(cur)) set_min_due(when);
        return 0;
    }
    // The comparison can run Python (which may write the slot): it reads
    // the value it was handed, held.
    Ref held(Py_NewRef(cur));
    const int lt = compare(when, held.get(), Py_LT);
    if (lt < 0) return -1;
    if (lt) set_min_due(when);
    return 0;
}

// `fn` is this module's builtin `impl` (the binding as registered).
bool our_builtin(PyObject* fn, PyCFunction impl) {
    return PyCFunction_Check(fn) && PyCFunction_GET_FUNCTION(fn) == impl;
}

// 1: `fn` is ai_driver's stock function `name` (`_STOCK_WALK[name]`: the very
// function, still running the code it had at import); 0: anything else; -1:
// an error. A function hashes by identity, so the lookup runs no Python.
int stock_fn(const Ctx& c, PyObject* name, PyObject* fn) {
    if (!PyFunction_Check(fn)) return 0;
    Ref table(load_global(c.g, c.n->stock_walk));
    if (!table) return -1;
    if (!PyDict_Check(table.get())) {
        PyErr_SetString(PyExc_TypeError, "ai_driver._STOCK_WALK must be a dict");
        return -1;
    }
    PyObject* pair = PyDict_GetItemWithError(table.get(), name);  // borrowed, used at once
    if (pair == nullptr) return PyErr_Occurred() ? -1 : 0;
    if (!PyTuple_Check(pair) || PyTuple_GET_SIZE(pair) != 2) {
        PyErr_SetString(PyExc_TypeError, "ai_driver._STOCK_WALK values must be (function, code)");
        return -1;
    }
    return PyTuple_GET_ITEM(pair, 0) == fn && PyFunction_GET_CODE(fn) == PyTuple_GET_ITEM(pair, 1);
}

// The stock handler kind of `handler` (`_STOCK_HANDLERS[handler]`, code
// unchanged), kNotStock for anything else, -1 on an error.
int handler_kind(const Ctx& c, PyObject* handler) {
    if (!PyFunction_Check(handler)) return kNotStock;
    Ref table(load_global(c.g, c.n->stock_handlers));
    if (!table) return -1;
    if (!PyDict_Check(table.get())) {
        PyErr_SetString(PyExc_TypeError, "ai_driver._STOCK_HANDLERS must be a dict");
        return -1;
    }
    PyObject* entry = PyDict_GetItemWithError(table.get(), handler);  // borrowed, used at once
    if (entry == nullptr) return PyErr_Occurred() ? -1 : kNotStock;
    if (!PyTuple_Check(entry) || PyTuple_GET_SIZE(entry) != 2 ||
        !PyLong_Check(PyTuple_GET_ITEM(entry, 0))) {
        PyErr_SetString(PyExc_TypeError, "ai_driver._STOCK_HANDLERS values must be (kind, code)");
        return -1;
    }
    if (PyFunction_GET_CODE(handler) != PyTuple_GET_ITEM(entry, 1)) return kNotStock;
    const long kind = PyLong_AsLong(PyTuple_GET_ITEM(entry, 0));
    if (kind == -1 && PyErr_Occurred()) return -1;
    return kind > kNotStock && kind < kKinds ? static_cast<int>(kind) : kNotStock;
}

// A stock forwarder `name` (`return <binding>(...)`, e.g. tick_ai) would run
// our native `impl` now: 1. 0: call the global itself (it is not stock, or
// the binding it would call has been replaced). -1: an error.
int routes_native(const Ctx& c, PyObject* name, PyObject* fn, PyObject* binding,
                  PyCFunction impl) {
    const int s = stock_fn(c, name, fn);
    if (s <= 0) return s;
    Ref b(load_global(c.g, binding));
    if (!b) return -1;
    return our_builtin(b.get(), impl) ? 1 : 0;
}

PyObject* call2(PyObject* fn, PyObject* a, PyObject* b) {
    PyObject* args[2] = {a, b};
    return PyObject_Vectorcall(fn, args, 2, nullptr);
}

PyObject* call3(PyObject* fn, PyObject* a, PyObject* b, PyObject* d) {
    PyObject* args[3] = {a, b, d};
    return PyObject_Vectorcall(fn, args, 3, nullptr);
}

// `a + b` (BINARY_OP +): two exact floats add as doubles (float_add);
// anything else is Python's operator. Owned.
PyObject* add_obj(PyObject* a, PyObject* b) {
    if (PyFloat_CheckExact(a) && PyFloat_CheckExact(b)) {
        const double s = PyFloat_AS_DOUBLE(a) + PyFloat_AS_DOUBLE(b);
        return PyFloat_FromDouble(s);
    }
    return PyNumber_Add(a, b);
}

// `float(x)` (float_new: a str parses, anything else is PyNumber_Float).
PyObject* py_float(PyObject* x) {
    if (PyUnicode_CheckExact(x)) return PyFloat_FromString(x);
    return PyNumber_Float(x);
}

// `obj.attr OP <global>` jumped on: the attribute, the global, COMPARE_OP
// (operands released before the truth test). 1, 0, or -1.
int attr_cmp_global(const Ctx& c, PyObject* obj, PyObject* attr, PyObject* gname, int op) {
    Ref a(PyObject_GetAttr(obj, attr));
    if (!a) return -1;
    Ref b(load_global(c.g, gname));
    if (!b) return -1;
    return compare_owned(std::move(a), std::move(b), op);
}

// `local OP <global>` jumped on. 1, 0, or -1.
int local_cmp_global(const Ctx& c, PyObject* local, PyObject* gname, int op) {
    Ref b(load_global(c.g, gname));
    if (!b) return -1;
    return compare_owned(Ref(Py_NewRef(local)), std::move(b), op);
}

// `obj.attr = <global>`.
int set_attr_global(const Ctx& c, PyObject* obj, PyObject* attr, PyObject* gname) {
    Ref v(load_global(c.g, gname));
    if (!v) return -1;
    return PyObject_SetAttr(obj, attr, v.get());
}

// `lst.append(item)`: an exact list's own append; anything else, the method.
int list_append(PyObject* lst, PyObject* item, const Names* n) {
    if (PyList_CheckExact(lst)) return PyList_Append(lst, item);
    Ref r(PyObject_CallMethodOneArg(lst, n->append, item));
    return r ? 0 : -1;
}

// `<global>.append(item)`.
int global_append(const Ctx& c, PyObject* gname, PyObject* item) {
    Ref l(load_global(c.g, gname));
    if (!l) return -1;
    return list_append(l.get(), item, c.n);
}

// `d.get(key)` / `d.get(key, dflt)` (dflt nullptr: the one-argument form).
PyObject* dict_get(PyObject* d, PyObject* key, PyObject* dflt, const Names* n) {
    if (PyDict_CheckExact(d)) {
        PyObject* v = PyDict_GetItemWithError(d, key);
        if (v != nullptr) return Py_NewRef(v);
        if (PyErr_Occurred()) return nullptr;
        return Py_NewRef(dflt != nullptr ? dflt : Py_None);
    }
    if (dflt == nullptr) return PyObject_CallMethodOneArg(d, n->get, key);
    return PyObject_CallMethodObjArgs(d, n->get, key, dflt, nullptr);
}

// `obj.__dict__.get(key[, dflt])`.
PyObject* obj_dict_get(PyObject* obj, PyObject* key, PyObject* dflt, const Names* n) {
    Ref d(PyObject_GetAttr(obj, n->dict));
    if (!d) return nullptr;
    return dict_get(d.get(), key, dflt, n);
}

// UNPACK_SEQUENCE 2 (CPython 3.11's, messages included). The sequence is
// released by the caller after the items are taken, before they are stored.
int unpack2(PyObject* seq, Ref* a, Ref* b) {
    if ((PyTuple_CheckExact(seq) && PyTuple_GET_SIZE(seq) == 2) ||
        (PyList_CheckExact(seq) && PyList_GET_SIZE(seq) == 2)) {
        PyObject** items = PyTuple_CheckExact(seq) ? &PyTuple_GET_ITEM(seq, 0)
                                                   : &PyList_GET_ITEM(seq, 0);
        *a = Ref(Py_NewRef(items[0]));
        *b = Ref(Py_NewRef(items[1]));
        return 0;
    }
    Ref it(PyObject_GetIter(seq));
    if (!it) {
        if (PyErr_ExceptionMatches(PyExc_TypeError) && Py_TYPE(seq)->tp_iter == nullptr &&
            !PySequence_Check(seq)) {
            PyErr_Clear();
            PyErr_Format(PyExc_TypeError, "cannot unpack non-iterable %.200s object",
                         Py_TYPE(seq)->tp_name);
        }
        return -1;
    }
    Ref x(PyIter_Next(it.get()));
    if (!x) {
        if (!PyErr_Occurred())
            PyErr_Format(PyExc_ValueError, "not enough values to unpack (expected %d, got %d)",
                         2, 0);
        return -1;
    }
    Ref y(PyIter_Next(it.get()));
    if (!y) {
        if (!PyErr_Occurred())
            PyErr_Format(PyExc_ValueError, "not enough values to unpack (expected %d, got %d)",
                         2, 1);
        return -1;
    }
    Ref z(PyIter_Next(it.get()));
    if (z) {
        z = Ref();
        PyErr_Format(PyExc_ValueError, "too many values to unpack (expected %d)", 2);
        return -1;
    }
    if (PyErr_Occurred()) return -1;
    *a = std::move(x);
    *b = std::move(y);
    return 0;
}

// The `lambda: bound(game_time + 1.0)` _tick_preprocessing hands to
// _run_script_step for a preprocessor taking dEndTime: a callable holding the
// two values its closure cells hold, adding when called (inside
// _run_script_step's try, as the lambda's body does).
struct EndTimeCall {
    PyObject_HEAD
    PyObject* bound;
    PyObject* game_time;
};

PyTypeObject* g_end_time_type = nullptr;

int etc_traverse(PyObject* self, visitproc visit, void* arg) {
    auto* o = reinterpret_cast<EndTimeCall*>(self);
    Py_VISIT(o->bound);
    Py_VISIT(o->game_time);
    Py_VISIT(Py_TYPE(self));
    return 0;
}

int etc_clear(PyObject* self) {
    auto* o = reinterpret_cast<EndTimeCall*>(self);
    Py_CLEAR(o->bound);
    Py_CLEAR(o->game_time);
    return 0;
}

void etc_dealloc(PyObject* self) {
    PyTypeObject* tp = Py_TYPE(self);
    PyObject_GC_UnTrack(self);
    etc_clear(self);
    tp->tp_free(self);
    Py_DECREF(tp);
}

PyObject* etc_call(PyObject* self, PyObject* args, PyObject* kw) {
    if (PyTuple_GET_SIZE(args) != 0) {
        PyErr_Format(PyExc_TypeError,
                     "<lambda>() takes 0 positional arguments but %zd were given",
                     PyTuple_GET_SIZE(args));
        return nullptr;
    }
    if (kw != nullptr && PyDict_GET_SIZE(kw) != 0) {
        PyErr_SetString(PyExc_TypeError, "<lambda>() got an unexpected keyword argument");
        return nullptr;
    }
    const Names* n = names();
    if (n == nullptr) return nullptr;
    auto* o = reinterpret_cast<EndTimeCall*>(self);
    if (o->bound == nullptr) {
        PyErr_SetString(PyExc_RuntimeError, "aitree end-time call cleared");
        return nullptr;
    }
    Ref bound(Py_NewRef(o->bound));             // LOAD_DEREF bound
    Ref arg(add_obj(o->game_time, n->fone));    // game_time + 1.0
    if (!arg) return nullptr;
    return PyObject_CallOneArg(bound.get(), arg.get());
}

PyObject* make_end_time_call(PyObject* bound, PyObject* game_time) {
    if (g_end_time_type == nullptr) {
        static PyType_Slot slots[] = {
            {Py_tp_call, reinterpret_cast<void*>(etc_call)},
            {Py_tp_dealloc, reinterpret_cast<void*>(etc_dealloc)},
            {Py_tp_traverse, reinterpret_cast<void*>(etc_traverse)},
            {Py_tp_clear, reinterpret_cast<void*>(etc_clear)},
            {0, nullptr},
        };
        static PyType_Spec spec = {
            "_dauntless_host.aitree_end_time_call", sizeof(EndTimeCall), 0,
            Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC, slots};
        PyObject* t = PyType_FromSpec(&spec);
        if (t == nullptr) return nullptr;
        g_end_time_type = reinterpret_cast<PyTypeObject*>(t);  // kept for good
    }
    EndTimeCall* o = PyObject_GC_New(EndTimeCall, g_end_time_type);
    if (o == nullptr) return nullptr;
    o->bound = Py_NewRef(bound);
    o->game_time = Py_NewRef(game_time);
    PyObject_GC_Track(reinterpret_cast<PyObject*>(o));
    return reinterpret_cast<PyObject*>(o);
}

PyObject* tick_impl(const Ctx& c, PyObject* ai, PyObject* gt);

// `tick_ai(node, game_time)` with `fn` the global already loaded (LOAD_GLOBAL
// comes before the arguments): natively when the stock tick_ai would select
// the native walk, else the global is called. Owned status.
PyObject* run_tick(const Ctx& c, PyObject* fn, PyObject* node, PyObject* gt) {
    const int r = routes_native(c, c.n->tick_ai, fn, c.n->aitree_tick, fast<tick>());
    if (r < 0) return nullptr;
    if (r) return tick_impl(c, node, gt);
    return call2(fn, node, gt);
}

// `tick_ai(node, game_time)` as a statement (its result popped). 0 / -1.
int tick_stmt(const Ctx& c, PyObject* node, PyObject* gt) {
    Ref fn(load_global(c.g, c.n->tick_ai));
    if (!fn) return -1;
    Ref r(run_tick(c, fn.get(), node, gt));
    return r ? 0 : -1;
}

// `tick_ai(obj.<attr>, game_time)` as a statement: the callee loaded, then
// the attribute; the argument goes with the callee's frame, before the
// result is popped. 0 / -1.
int tick_attr_stmt(const Ctx& c, PyObject* obj, PyObject* attr, PyObject* gt) {
    Ref fn(load_global(c.g, c.n->tick_ai));
    if (!fn) return -1;
    Ref arg(PyObject_GetAttr(obj, attr));
    if (!arg) return -1;
    Ref r(run_tick(c, fn.get(), arg.get(), gt));
    if (!r) return -1;
    arg = Ref();
    r = Ref();
    return 0;
}

// `_note_due(obj._next_update_time)` as a statement: the callee loaded, then
// the attribute. Our builtin runs inline; anything else is called. 0 / -1.
int note_due_attr_stmt(const Ctx& c, PyObject* obj) {
    Ref fn(load_global(c.g, c.n->note_due));
    if (!fn) return -1;
    Ref when(PyObject_GetAttr(obj, c.n->next_update_time));
    if (!when) return -1;
    if (our_builtin(fn.get(), fast<note_due>())) return note_due_value(when.get());
    Ref r(PyObject_CallOneArg(fn.get(), when.get()));
    return r ? 0 : -1;
}

// `_run_script_step(ai, call)`, CALLED BACK, never reproduced: see aitree.h
// (the exception policy, its log and its traceback stay one Python body).
PyObject* run_script_step(const Ctx& c, PyObject* ai, PyObject* call) {
    Ref fn(load_global(c.g, c.n->run_script_step));
    if (!fn) return nullptr;
    return call2(fn.get(), ai, call);
}

// `_focus_instance_of(node)`'s body. Owned.
PyObject* focus_instance_of_impl(const Ctx& c, PyObject* node) {
    const Names* n = c.n;
    struct Frame {
        Ref d, script_inst;
        void release() {
            d = Ref();
            script_inst = Ref();
        }
        ~Frame() { release(); }
    } f;
    // d = getattr(node, "__dict__", {})
    {
        PyObject* r = nullptr;
        const int has = lookup_attr(node, n->dict, &r);
        if (has < 0) return nullptr;
        Ref d(has ? r : PyDict_New());
        if (!d) return nullptr;
        f.d = std::move(d);
    }
    // script_inst = d.get("_script_instance")
    {
        Ref v(dict_get(f.d.get(), n->script_instance, nullptr, n));
        if (!v) return nullptr;
        f.script_inst = std::move(v);
    }
    // if script_inst is not None: return script_inst
    if (f.script_inst.get() != Py_None) {
        Ref ret(Py_NewRef(f.script_inst.get()));
        f.release();
        return ret.steal();
    }
    // return d.get("_preprocessing_instance")
    Ref ret(dict_get(f.d.get(), n->preprocessing_instance, nullptr, n));
    if (!ret) return nullptr;
    f.release();
    return ret.steal();
}

// `_queue_got_focus(node)`'s body. Owned None.
PyObject* queue_got_focus_impl(const Ctx& c, PyObject* node) {
    const Names* n = c.n;
    struct Frame {
        Ref inst, queued, inst2;  // inst, queued, _inst
        void release() {
            inst = Ref();
            queued = Ref();
            inst2 = Ref();
        }
        ~Frame() { release(); }
    } f;
    // if node.__dict__.get("_got_focus_called", False): return
    {
        Ref v(obj_dict_get(node, n->got_focus_called, Py_False, n));
        if (!v) return nullptr;
        const int t = PyObject_IsTrue(v.get());
        if (t < 0) return nullptr;
        if (t) {
            v = Ref();
            f.release();
            Py_RETURN_NONE;
        }
    }
    // inst = _focus_instance_of(node)
    {
        Ref fn(load_global(c.g, n->focus_instance_of));
        if (!fn) return nullptr;
        const int s = stock_fn(c, n->focus_instance_of, fn.get());
        if (s < 0) return nullptr;
        Ref v(s ? focus_instance_of_impl(c, node) : PyObject_CallOneArg(fn.get(), node));
        if (!v) return nullptr;
        fn = Ref();
        f.inst = std::move(v);
    }
    // if inst is None: return
    if (f.inst.get() == Py_None) {
        f.release();
        Py_RETURN_NONE;
    }
    // for queued, _inst in _pending_got_focus:
    //     if queued is node: return
    {
        Ref it;
        {
            Ref l(load_global(c.g, n->pending));
            if (!l) return nullptr;
            it = Ref(PyObject_GetIter(l.get()));
            if (!it) return nullptr;
        }
        for (;;) {
            Ref item(PyIter_Next(it.get()));
            if (!item) {
                if (PyErr_Occurred()) return nullptr;
                break;
            }
            Ref a, b;
            if (unpack2(item.get(), &a, &b) < 0) return nullptr;
            item = Ref();
            f.queued = std::move(a);
            f.inst2 = std::move(b);
            if (f.queued.get() == node) {
                it = Ref();
                f.release();
                Py_RETURN_NONE;
            }
        }
    }
    // _pending_got_focus.append((node, inst))
    {
        Ref l(load_global(c.g, n->pending));
        if (!l) return nullptr;
        Ref t(PyTuple_Pack(2, node, f.inst.get()));
        if (!t) return nullptr;
        if (list_append(l.get(), t.get(), n) < 0) return nullptr;
    }
    f.release();
    Py_RETURN_NONE;
}

// `_queue_got_focus(node)` as a statement. 0 / -1.
int queue_got_focus_stmt(const Ctx& c, PyObject* node) {
    Ref fn(load_global(c.g, c.n->queue_got_focus));
    if (!fn) return -1;
    const int s = stock_fn(c, c.n->queue_got_focus, fn.get());
    if (s < 0) return -1;
    Ref r(s ? queue_got_focus_impl(c, node) : PyObject_CallOneArg(fn.get(), node));
    return r ? 0 : -1;
}

// `_retain_subtree_focus(ai)`'s body. Owned None.
PyObject* retain_subtree_focus_impl(const Ctx& c, PyObject* ai) {
    const Names* n = c.n;
    struct Frame {
        Ref node;
        std::vector<Ref> stack;  // a local list nothing else can see
        Ref nn, child, cc;       // n, child, c
        void release() {
            node = Ref();
            stack.clear();
            nn = Ref();
            child = Ref();
            cc = Ref();
        }
        ~Frame() { release(); }
    } f;
    // node = ai._contained_ai
    {
        Ref v(PyObject_GetAttr(ai, n->contained_ai));
        if (!v) return nullptr;
        f.node = std::move(v);
    }
    // if node is None: return
    if (f.node.get() == Py_None) {
        f.release();
        Py_RETURN_NONE;
    }
    // stack = [node]
    f.stack.emplace_back(Py_NewRef(f.node.get()));
    // while stack:
    while (!f.stack.empty()) {
        // n = stack.pop()
        {
            Ref top = std::move(f.stack.back());
            f.stack.pop_back();
            f.nn = std::move(top);
        }
        // if n.__dict__.get("_has_focus"): _reached_this_tick.append(n)
        {
            Ref v(obj_dict_get(f.nn.get(), n->has_focus, nullptr, n));
            if (!v) return nullptr;
            const int t = PyObject_IsTrue(v.get());
            if (t < 0) return nullptr;
            v = Ref();
            if (t && global_append(c, n->reached, f.nn.get()) < 0) return nullptr;
        }
        // child = n.__dict__.get("_contained_ai")
        {
            Ref v(obj_dict_get(f.nn.get(), n->contained_ai, nullptr, n));
            if (!v) return nullptr;
            f.child = std::move(v);
        }
        // if child is not None: stack.append(child)
        if (f.child.get() != Py_None) f.stack.emplace_back(Py_NewRef(f.child.get()));
        // for c in (n.__dict__.get("_ais") or ()):
        //     stack.append(c[1] if isinstance(c, tuple) else c)
        Ref it;
        {
            Ref v(obj_dict_get(f.nn.get(), n->ais, nullptr, n));
            if (!v) return nullptr;
            const int t = PyObject_IsTrue(v.get());
            if (t < 0) return nullptr;
            if (!t) v = Ref(PyTuple_New(0));
            if (!v) return nullptr;
            it = Ref(PyObject_GetIter(v.get()));
            if (!it) return nullptr;
        }
        for (;;) {
            Ref next(PyIter_Next(it.get()));
            if (!next) {
                if (PyErr_Occurred()) return nullptr;
                break;
            }
            f.cc = std::move(next);
            const int is_tuple =
                PyObject_IsInstance(f.cc.get(), reinterpret_cast<PyObject*>(&PyTuple_Type));
            if (is_tuple < 0) return nullptr;
            Ref item(is_tuple ? subscript(f.cc.get(), 1, n->one) : Py_NewRef(f.cc.get()));
            if (!item) return nullptr;
            f.stack.push_back(std::move(item));
        }
    }
    f.release();
    Py_RETURN_NONE;
}

// `_retain_subtree_focus(ai)` as a statement. 0 / -1.
int retain_subtree_focus_stmt(const Ctx& c, PyObject* ai) {
    Ref fn(load_global(c.g, c.n->retain_focus));
    if (!fn) return -1;
    const int s = stock_fn(c, c.n->retain_focus, fn.get());
    if (s < 0) return -1;
    Ref r(s ? retain_subtree_focus_impl(c, ai) : PyObject_CallOneArg(fn.get(), ai));
    return r ? 0 : -1;
}

// `_refresh_conditional_status(child)` as a statement. 0 / -1.
int refresh_stmt(const Ctx& c, PyObject* child) {
    Ref fn(load_global(c.g, c.n->refresh_cond));
    if (!fn) return -1;
    const int r = routes_native(c, c.n->refresh_cond, fn.get(), c.n->aitree_refresh,
                                fast<refresh_conditional>());
    if (r < 0) return -1;
    Ref v(r ? refresh_impl(child, c.g) : PyObject_CallOneArg(fn.get(), child));
    return v ? 0 : -1;
}

// `_condition_statuses(ai)`. Owned.
PyObject* condition_statuses_call(const Ctx& c, PyObject* ai) {
    Ref fn(load_global(c.g, c.n->condition_statuses));
    if (!fn) return nullptr;
    const int r = routes_native(c, c.n->condition_statuses, fn.get(), c.n->aitree_statuses,
                                fast<condition_statuses>());
    if (r < 0) return nullptr;
    if (!r) return PyObject_CallOneArg(fn.get(), ai);
    ++g_s2_runs;
    StockStatus stock;
    if (stock_status_of(c.g, c.n, &stock) < 0) return nullptr;
    return statuses_of(ai, stock, c.n);
}

// `_any_condition(ai)`. Owned (a bool, natively).
PyObject* any_condition_call(const Ctx& c, PyObject* ai) {
    Ref fn(load_global(c.g, c.n->any_condition));
    if (!fn) return nullptr;
    const int r = routes_native(c, c.n->any_condition, fn.get(), c.n->aitree_any,
                                fast<any_condition>());
    if (r < 0) return nullptr;
    if (!r) return PyObject_CallOneArg(fn.get(), ai);
    ++g_s2_runs;
    StockStatus stock;
    if (stock_status_of(c.g, c.n, &stock) < 0) return nullptr;
    const int any = any_condition_of(ai, stock, c.n);
    if (any < 0) return nullptr;
    return Py_NewRef(any ? Py_True : Py_False);
}

// `_eval_conditional(ai, eval_fn, args)`. Owned.
PyObject* eval_conditional_call(const Ctx& c, PyObject* ai, PyObject* eval_fn, PyObject* args,
                                 bool count_entry) {
    Ref fn(load_global(c.g, c.n->eval_conditional));
    if (!fn) return nullptr;
    const int r = routes_native(c, c.n->eval_conditional, fn.get(), c.n->aitree_eval,
                                fast<eval_conditional>());
    if (r < 0) return nullptr;
    if (!r) return call3(fn.get(), ai, eval_fn, args);
    if (count_entry) ++g_s2_runs;
    return eval_impl(ai, eval_fn, args, c.g, c.n);
}

// ── S3: the root-end reconciliation ─────────────────────────────────────────
// THE REFERENCE is the oracle's `_reconcile_focus`, `_dispatch_lost_focus`,
// `_flush_pending_got_focus` and `_reconcile_active`; each step names the
// statement it stands for. The calls out (LostFocus / GotFocus through
// `_run_script_step`, `SetActive` / `SetInactive` through Python's own method
// lookup) are the Python calls, in Python's order, with one exception: a
// stock SetActive / SetInactive whose edge test says nothing changes is not
// called (`activation_stmt`; aitree.h says why that is invisible).

unsigned long long g_s3_runs[3] = {};          // native focus, flush, active
unsigned long long g_activation_skips = 0;     // no-edge stock calls skipped

// `{id(n) for n in reached}`, the set comprehension: its iterator (`.0`)
// and loop variable `n` are its own frame's locals, released in that order
// when it returns. The set never leaves `_reconcile_*`, so only membership
// is observable: the ids are kept as the addresses they are, sorted. 0 / -1.
int id_set_of(PyObject* reached, std::vector<void*>* out) {
    Ref it(PyObject_GetIter(reached));  // GET_ITER, in the caller's frame
    if (!it) return -1;
    Ref nn;
    for (;;) {
        Ref x(PyIter_Next(it.get()));
        if (!x) {
            if (PyErr_Occurred()) return -1;
            break;
        }
        nn = std::move(x);
        out->push_back(nn.get());
    }
    it = Ref();
    nn = Ref();
    std::sort(out->begin(), out->end());
    return 0;
}

bool has_id(const std::vector<void*>& ids, PyObject* o) {
    return std::binary_search(ids.begin(), ids.end(), static_cast<void*>(o));
}

// `_dispatch_lost_focus(node)`'s body. Owned None.
PyObject* dispatch_lost_focus_impl(const Ctx& c, PyObject* node) {
    const Names* n = c.n;
    struct Frame {
        Ref inst, lost;
        void release() {
            inst = Ref();
            lost = Ref();
        }
        ~Frame() { release(); }
    } f;
    // inst = _focus_instance_of(node)
    {
        Ref fn(load_global(c.g, n->focus_instance_of));
        if (!fn) return nullptr;
        const int s = stock_fn(c, n->focus_instance_of, fn.get());
        if (s < 0) return nullptr;
        Ref v(s ? focus_instance_of_impl(c, node) : PyObject_CallOneArg(fn.get(), node));
        if (!v) return nullptr;
        fn = Ref();
        f.inst = std::move(v);
    }
    // lost = getattr(inst, "LostFocus", None) if inst is not None else None
    {
        Ref v(f.inst.get() != Py_None ? getattr_or(f.inst.get(), n->lost_focus, Py_None)
                                      : Py_NewRef(Py_None));
        if (!v) return nullptr;
        f.lost = std::move(v);
    }
    // if callable(lost): _run_script_step(node, lost)
    if (PyCallable_Check(f.lost.get())) {
        Ref r(run_script_step(c, node, f.lost.get()));
        if (!r) return nullptr;
    }
    // node._has_focus = False
    if (PyObject_SetAttr(node, n->has_focus, Py_False) < 0) return nullptr;
    // node.__dict__["_got_focus_called"] = False
    if (own_dict_set(node, n->got_focus_called, Py_False, n) < 0) return nullptr;
    f.release();
    Py_RETURN_NONE;
}

// `_dispatch_lost_focus(node)` as a statement. 0 / -1.
int dispatch_lost_focus_stmt(const Ctx& c, PyObject* node) {
    Ref fn(load_global(c.g, c.n->dispatch_lost_focus));
    if (!fn) return -1;
    const int s = stock_fn(c, c.n->dispatch_lost_focus, fn.get());
    if (s < 0) return -1;
    Ref r(s ? dispatch_lost_focus_impl(c, node) : PyObject_CallOneArg(fn.get(), node));
    return r ? 0 : -1;
}

// `root_ai.<attr> = list(reached)`. 0 / -1.
int store_list_of(PyObject* root_ai, PyObject* attr, PyObject* reached) {
    Ref l(PySequence_List(reached));
    if (!l) return -1;
    return PyObject_SetAttr(root_ai, attr, l.get());
}

// `_reconcile_focus(root_ai, reached)`'s body; `reached` is the frame's own
// reference (the caller's argument, moved in). Owned None.
PyObject* reconcile_focus_impl(const Ctx& c, PyObject* root_ai, Ref reached) {
    const Names* n = c.n;
    ++g_s3_runs[0];
    // Locals after root_ai: reached, reached_ids (a set of ints: nothing to
    // finalise), node.
    struct Frame {
        Ref reached, node;
        void release() {
            reached = Ref();
            node = Ref();
        }
        ~Frame() { release(); }
    } f;
    f.reached = std::move(reached);
    // reached_ids = {id(n) for n in reached}
    std::vector<void*> ids;
    if (id_set_of(f.reached.get(), &ids) < 0) return nullptr;
    // for node in getattr(root_ai, "_focused_preprocessors", ()):
    //     if id(node) not in reached_ids:
    //         _dispatch_lost_focus(node)
    {
        Ref it;
        {
            Ref empty(PyTuple_New(0));
            if (!empty) return nullptr;
            Ref seq(getattr_or(root_ai, n->focused_preprocessors, empty.get()));
            if (!seq) return nullptr;
            it = Ref(PyObject_GetIter(seq.get()));
            if (!it) return nullptr;
        }
        for (;;) {
            Ref x(PyIter_Next(it.get()));
            if (!x) {
                if (PyErr_Occurred()) return nullptr;
                break;
            }
            f.node = std::move(x);
            if (!has_id(ids, f.node.get()) && dispatch_lost_focus_stmt(c, f.node.get()) < 0)
                return nullptr;
        }
    }
    // root_ai._focused_preprocessors = list(reached)
    if (store_list_of(root_ai, n->focused_preprocessors, f.reached.get()) < 0) return nullptr;
    f.release();
    Py_RETURN_NONE;
}

// `_flush_pending_got_focus()`'s body. Owned None.
PyObject* flush_pending_impl(const Ctx& c) {
    const Names* n = c.n;
    ++g_s3_runs[1];
    struct Frame {
        Ref pending, node, inst, got;
        void release() {
            pending = Ref();
            node = Ref();
            inst = Ref();
            got = Ref();
        }
        ~Frame() { release(); }
    } f;
    // if not _pending_got_focus: return
    {
        Ref l(load_global(c.g, n->pending));
        if (!l) return nullptr;
        const int t = PyObject_IsTrue(l.get());
        if (t < 0) return nullptr;
        if (!t) {
            l = Ref();
            f.release();
            Py_RETURN_NONE;
        }
    }
    // pending = list(_pending_got_focus)
    {
        Ref l(load_global(c.g, n->pending));
        if (!l) return nullptr;
        Ref v(PySequence_List(l.get()));
        if (!v) return nullptr;
        l = Ref();
        f.pending = std::move(v);
    }
    // del _pending_got_focus[:]
    {
        Ref l(load_global(c.g, n->pending));
        if (!l) return nullptr;
        if (PyObject_DelItem(l.get(), n->whole_slice) < 0) return nullptr;
    }
    // for node, inst in pending:
    Ref it(PyObject_GetIter(f.pending.get()));
    if (!it) return nullptr;
    for (;;) {
        Ref item(PyIter_Next(it.get()));
        if (!item) {
            if (PyErr_Occurred()) return nullptr;
            break;
        }
        Ref a, b;
        if (unpack2(item.get(), &a, &b) < 0) return nullptr;
        item = Ref();
        f.node = std::move(a);
        f.inst = std::move(b);
        // if node.__dict__.get("_got_focus_called", False): continue
        {
            Ref v(obj_dict_get(f.node.get(), n->got_focus_called, Py_False, n));
            if (!v) return nullptr;
            const int t = PyObject_IsTrue(v.get());
            if (t < 0) return nullptr;
            if (t) continue;
        }
        // got = getattr(inst, "GotFocus", None)
        {
            Ref v(getattr_or(f.inst.get(), n->got_focus, Py_None));
            if (!v) return nullptr;
            f.got = std::move(v);
        }
        // if callable(got): _run_script_step(node, got)
        if (PyCallable_Check(f.got.get())) {
            Ref r(run_script_step(c, f.node.get(), f.got.get()));
            if (!r) return nullptr;
        }
        // node.__dict__["_got_focus_called"] = True
        if (own_dict_set(f.node.get(), n->got_focus_called, Py_True, n) < 0) return nullptr;
    }
    it = Ref();
    f.release();
    Py_RETURN_NONE;
}

// The stock SetActive or SetInactive, `_STOCK_SET_ACTIVE` /
// `_STOCK_SET_INACTIVE` = (function, its code at import), or (None, None)
// when the capture did not recognise the body (then nothing is skipped).
struct StockMethod {
    Ref fn, code;
};

int stock_method_of(const Ctx& c, PyObject* gname, StockMethod* out) {
    Ref pair(load_global(c.g, gname));
    if (!pair) return -1;
    if (!PyTuple_CheckExact(pair.get()) || PyTuple_GET_SIZE(pair.get()) != 2) {
        PyErr_Format(PyExc_TypeError, "ai_driver.%U must be (function, code)", gname);
        return -1;
    }
    out->fn = Ref(Py_NewRef(PyTuple_GET_ITEM(pair.get(), 0)));
    out->code = Ref(Py_NewRef(PyTuple_GET_ITEM(pair.get(), 1)));
    return 0;
}

// `fn` is the stock method, still running its code.
bool is_stock_method(PyObject* fn, const StockMethod& stock) {
    return fn == stock.fn.get() && PyFunction_Check(fn) &&
           PyFunction_GET_CODE(fn) == stock.code.get();
}

// The stock body's first statement, `if [not] self._is_active_in_tree:
// return`, would return without running Python: the attribute comes from the
// instance (no descriptor of that name on the type, generic attribute
// lookup) and is exactly `unchanged` (True for SetActive, False for
// SetInactive), whose truth test runs nothing. 1 skip, 0 call, -1 error.
int edge_unchanged(PyObject* node, PyObject* unchanged, const Names* n) {
    PyTypeObject* tp = Py_TYPE(node);
    if (tp->tp_getattro != PyObject_GenericGetAttr) return 0;
    PyObject* descr = _PyType_Lookup(tp, n->is_active_in_tree);  // borrowed, runs nothing
    if (descr != nullptr && Py_TYPE(descr)->tp_descr_get != nullptr) return 0;
    Ref v(PyObject_GenericGetAttr(node, n->is_active_in_tree));
    if (!v) {
        if (!PyErr_ExceptionMatches(PyExc_AttributeError)) return -1;
        PyErr_Clear();  // the call raises it again, as Python's would
        return 0;
    }
    return v.get() == unchanged;
}

// `node.SetActive()` / `node.SetInactive()` as a statement: Python's method
// lookup (LOAD_METHOD), then the call -- skipped only when the lookup lands
// on the stock method, unbound, and `edge_unchanged`. The callable is
// released before the result, as CALL then POP_TOP do. 0 / -1.
int activation_stmt(const Ctx& c, PyObject* node, PyObject* name, const StockMethod& stock,
                    PyObject* unchanged) {
#if PY_VERSION_HEX < 0x030C0000
    PyObject* m = nullptr;
    const int unbound = _PyObject_GetMethod(node, name, &m);
    if (m == nullptr) return -1;
    Ref meth(m);
    Ref r;
    if (unbound) {
        if (is_stock_method(m, stock)) {
            const int same = edge_unchanged(node, unchanged, c.n);
            if (same < 0) return -1;
            if (same) {
                ++g_activation_skips;
                return 0;
            }
        }
        PyObject* a[1] = {node};
        r = Ref(PyObject_Vectorcall(m, a, 1, nullptr));
    } else {
        r = Ref(PyObject_CallNoArgs(m));
    }
#else
    Ref meth(PyObject_GetAttr(node, name));
    if (!meth) return -1;
    if (PyMethod_Check(meth.get()) && PyMethod_GET_SELF(meth.get()) == node &&
        is_stock_method(PyMethod_GET_FUNCTION(meth.get()), stock)) {
        const int same = edge_unchanged(node, unchanged, c.n);
        if (same < 0) return -1;
        if (same) {
            ++g_activation_skips;
            return 0;
        }
    }
    Ref r(PyObject_CallNoArgs(meth.get()));
#endif
    meth = Ref();
    return r ? 0 : -1;
}

// `_reconcile_active(root_ai, reached)`'s body; `reached` moved in, as for
// `_reconcile_focus`. Owned None.
PyObject* reconcile_active_impl(const Ctx& c, PyObject* root_ai, Ref reached) {
    const Names* n = c.n;
    ++g_s3_runs[2];
    struct Frame {
        Ref reached, node;
        void release() {
            reached = Ref();
            node = Ref();
        }
        ~Frame() { release(); }
    } f;
    f.reached = std::move(reached);
    StockMethod on, off;
    if (stock_method_of(c, n->stock_set_active, &on) < 0 ||
        stock_method_of(c, n->stock_set_inactive, &off) < 0)
        return nullptr;
    // reached_ids = {id(n) for n in reached}
    std::vector<void*> ids;
    if (id_set_of(f.reached.get(), &ids) < 0) return nullptr;
    // for node in getattr(root_ai, "_active_nodes", ()):
    //     if id(node) not in reached_ids:
    //         node.SetInactive()
    {
        Ref it;
        {
            Ref empty(PyTuple_New(0));
            if (!empty) return nullptr;
            Ref seq(getattr_or(root_ai, n->active_nodes, empty.get()));
            if (!seq) return nullptr;
            it = Ref(PyObject_GetIter(seq.get()));
            if (!it) return nullptr;
        }
        for (;;) {
            Ref x(PyIter_Next(it.get()));
            if (!x) {
                if (PyErr_Occurred()) return nullptr;
                break;
            }
            f.node = std::move(x);
            if (!has_id(ids, f.node.get()) &&
                activation_stmt(c, f.node.get(), n->set_inactive, off, Py_False) < 0)
                return nullptr;
        }
    }
    // for node in reached:
    //     node.SetActive()
    {
        Ref it(PyObject_GetIter(f.reached.get()));
        if (!it) return nullptr;
        for (;;) {
            Ref x(PyIter_Next(it.get()));
            if (!x) {
                if (PyErr_Occurred()) return nullptr;
                break;
            }
            f.node = std::move(x);
            if (activation_stmt(c, f.node.get(), n->set_active, on, Py_True) < 0) return nullptr;
        }
    }
    // root_ai._active_nodes = list(reached)
    if (store_list_of(root_ai, n->active_nodes, f.reached.get()) < 0) return nullptr;
    f.release();
    Py_RETURN_NONE;
}

// `<reconciler>(ai, <walk-state global>)` as a statement, at the root end:
// the callee loaded, then the list; run natively while the callee is stock.
int reconcile_stmt(const Ctx& c, PyObject* fname, PyObject* lname, PyObject* ai,
                   PyObject* (*impl)(const Ctx&, PyObject*, Ref)) {
    Ref fn(load_global(c.g, fname));
    if (!fn) return -1;
    Ref reached(load_global(c.g, lname));
    if (!reached) return -1;
    const int s = stock_fn(c, fname, fn.get());
    if (s < 0) return -1;
    Ref r(s ? impl(c, ai, std::move(reached)) : call2(fn.get(), ai, reached.get()));
    if (!r) return -1;
    reached = Ref();
    fn = Ref();
    return 0;
}

// `_flush_pending_got_focus()` as a statement. 0 / -1.
int flush_stmt(const Ctx& c) {
    Ref fn(load_global(c.g, c.n->flush_pending));
    if (!fn) return -1;
    const int s = stock_fn(c, c.n->flush_pending, fn.get());
    if (s < 0) return -1;
    Ref r(s ? flush_pending_impl(c) : PyObject_CallNoArgs(fn.get()));
    if (!r) return -1;
    fn = Ref();
    return 0;
}

// ── the stock handlers ──────────────────────────────────────────────────────

// `return ai._status`, the frame released after the value is loaded.
template <typename F>
PyObject* return_status(PyObject* ai, const Names* n, F& frame) {
    Ref r(PyObject_GetAttr(ai, n->status));
    if (!r) return nullptr;
    frame.release();
    return r.steal();
}

// _tick_plain
PyObject* plain_impl(const Ctx& c, PyObject* ai, PyObject* gt) {
    const Names* n = c.n;
    ++g_kind_runs[kPlain];
    struct Frame {
        Ref inst, update_fn, status, next_update_fn, next_update, interval;
        void release() {
            inst = Ref();
            update_fn = Ref();
            status = Ref();
            next_update_fn = Ref();
            next_update = Ref();
            interval = Ref();
        }
        ~Frame() { release(); }
    } f;
    // if ai._status != US_ACTIVE: return ai._status
    {
        const int ne = attr_cmp_global(c, ai, n->status, n->us_active, Py_NE);
        if (ne < 0) return nullptr;
        if (ne) return return_status(ai, n, f);
    }
    // ai._has_focus = True
    if (PyObject_SetAttr(ai, n->has_focus, Py_True) < 0) return nullptr;
    // _reached_this_tick.append(ai)
    if (global_append(c, n->reached, ai) < 0) return nullptr;
    // _queue_got_focus(ai)
    if (queue_got_focus_stmt(c, ai) < 0) return nullptr;
    // if game_time < ai._next_update_time:
    //     _note_due(ai._next_update_time)
    //     return ai._status
    {
        Ref due(PyObject_GetAttr(ai, n->next_update_time));
        if (!due) return nullptr;
        const int lt = compare_owned(Ref(Py_NewRef(gt)), std::move(due), Py_LT);
        if (lt < 0) return nullptr;
        if (lt) {
            if (note_due_attr_stmt(c, ai) < 0) return nullptr;
            return return_status(ai, n, f);
        }
    }
    // inst = ai.GetScriptInstance()
    {
        Ref v(PyObject_CallMethodNoArgs(ai, n->get_script_instance));
        if (!v) return nullptr;
        f.inst = std::move(v);
    }
    // update_fn = getattr(inst, "Update", None)
    {
        Ref v(getattr_or(f.inst.get(), n->update, Py_None));
        if (!v) return nullptr;
        f.update_fn = std::move(v);
    }
    // if update_fn is None or not callable(update_fn): return ai._status
    if (f.update_fn.get() == Py_None || !PyCallable_Check(f.update_fn.get()))
        return return_status(ai, n, f);
    // status = _run_script_step(ai, update_fn)
    {
        Ref v(run_script_step(c, ai, f.update_fn.get()));
        if (!v) return nullptr;
        f.status = std::move(v);
    }
    // if status is None: status = US_ACTIVE
    if (f.status.get() == Py_None) {
        Ref v(load_global(c.g, n->us_active));
        if (!v) return nullptr;
        f.status = std::move(v);
    }
    // ai._status = int(status)
    {
        Ref v(PyNumber_Long(f.status.get()));
        if (!v) return nullptr;
        if (PyObject_SetAttr(ai, n->status, v.get()) < 0) return nullptr;
    }
    // next_update_fn = getattr(inst, "GetNextUpdateTime", None)
    {
        Ref v(getattr_or(f.inst.get(), n->get_next_update_time, Py_None));
        if (!v) return nullptr;
        f.next_update_fn = std::move(v);
    }
    // next_update = next_update_fn() if callable(next_update_fn) else None
    {
        Ref v(PyCallable_Check(f.next_update_fn.get()) ? PyObject_CallNoArgs(f.next_update_fn.get())
                                                       : Py_NewRef(Py_None));
        if (!v) return nullptr;
        f.next_update = std::move(v);
    }
    // interval = float(next_update) if next_update is not None else 0.0
    {
        Ref v(f.next_update.get() != Py_None ? py_float(f.next_update.get())
                                             : Py_NewRef(n->fzero));
        if (!v) return nullptr;
        f.interval = std::move(v);
    }
    // ai._next_update_time = game_time + interval
    {
        Ref v(add_obj(gt, f.interval.get()));
        if (!v) return nullptr;
        if (PyObject_SetAttr(ai, n->next_update_time, v.get()) < 0) return nullptr;
    }
    // _note_due(ai._next_update_time)
    if (note_due_attr_stmt(c, ai) < 0) return nullptr;
    // return ai._status
    return return_status(ai, n, f);
}

// `len(<global>)` as an int object.
PyObject* len_global(const Ctx& c, PyObject* gname) {
    Ref l(load_global(c.g, gname));
    if (!l) return nullptr;
    const Py_ssize_t k = PyObject_Size(l.get());
    if (k < 0) return nullptr;
    return PyLong_FromSsize_t(k);
}

// `del <global>[start:]` (BUILD_SLICE, DELETE_SUBSCR). 0 / -1.
int del_tail(const Ctx& c, PyObject* gname, PyObject* start) {
    Ref l(load_global(c.g, gname));
    if (!l) return -1;
    Ref sl(PySlice_New(start, Py_None, nullptr));
    if (!sl) return -1;
    return PyObject_DelItem(l.get(), sl.get());
}

// _dispatch_priority_child's body. Owned status.
PyObject* dispatch_priority_child_impl(const Ctx& c, PyObject* child, PyObject* gt) {
    const Names* n = c.n;
    struct Frame {
        Ref focus_n, all_n, pending_n, had_focus, had_got;
        void release() {
            focus_n = Ref();
            all_n = Ref();
            pending_n = Ref();
            had_focus = Ref();
            had_got = Ref();
        }
        ~Frame() { release(); }
    } f;
    // focus_n = len(_reached_this_tick)
    // all_n = len(_reached_this_tick_all)
    // pending_n = len(_pending_got_focus)
    f.focus_n = Ref(len_global(c, n->reached));
    if (!f.focus_n) return nullptr;
    f.all_n = Ref(len_global(c, n->reached_all));
    if (!f.all_n) return nullptr;
    f.pending_n = Ref(len_global(c, n->pending));
    if (!f.pending_n) return nullptr;
    // had_focus = child._has_focus
    f.had_focus = Ref(PyObject_GetAttr(child, n->has_focus));
    if (!f.had_focus) return nullptr;
    // had_got = child.__dict__.get("_got_focus_called", False)
    f.had_got = Ref(obj_dict_get(child, n->got_focus_called, Py_False, n));
    if (!f.had_got) return nullptr;
    // tick_ai(child, game_time)
    if (tick_stmt(c, child, gt) < 0) return nullptr;
    // if child._status != US_ACTIVE:
    const int ne = attr_cmp_global(c, child, n->status, n->us_active, Py_NE);
    if (ne < 0) return nullptr;
    if (ne) {
        // del _reached_this_tick[focus_n:] (and the other two)
        if (del_tail(c, n->reached, f.focus_n.get()) < 0) return nullptr;
        if (del_tail(c, n->reached_all, f.all_n.get()) < 0) return nullptr;
        if (del_tail(c, n->pending, f.pending_n.get()) < 0) return nullptr;
        // _reached_this_tick_all_ids.clear()
        {
            Ref ids(load_global(c.g, n->reached_all_ids));
            if (!ids) return nullptr;
            if (PySet_CheckExact(ids.get())) {
                if (PySet_Clear(ids.get()) < 0) return nullptr;
            } else {
                Ref r(PyObject_CallMethodNoArgs(ids.get(), n->clear));
                if (!r) return nullptr;
            }
        }
        // _reached_this_tick_all_ids.update(id(n) for n in _reached_this_tick_all)
        {
            Ref ids(load_global(c.g, n->reached_all_ids));
            if (!ids) return nullptr;
            Ref it;
            {
                Ref l(load_global(c.g, n->reached_all));
                if (!l) return nullptr;
                it = Ref(PyObject_GetIter(l.get()));
                if (!it) return nullptr;
            }
            // An exact set takes each id as the generator yields it; any
            // other receiver gets the ids as a list (its update() runs once).
            const bool exact = PySet_CheckExact(ids.get());
            Ref batch(exact ? nullptr : PyList_New(0));
            if (!exact && !batch) return nullptr;
            Ref node;  // the generator's frame: `.0` (it), `n`
            for (;;) {
                Ref next(PyIter_Next(it.get()));
                if (!next) {
                    if (PyErr_Occurred()) return nullptr;
                    break;
                }
                node = std::move(next);
                Ref ident(PyLong_FromVoidPtr(node.get()));
                if (!ident) return nullptr;
                if (exact ? PySet_Add(ids.get(), ident.get()) < 0
                          : PyList_Append(batch.get(), ident.get()) < 0)
                    return nullptr;
            }
            it = Ref();
            node = Ref();
            if (!exact) {
                Ref r(PyObject_CallMethodOneArg(ids.get(), n->update_m, batch.get()));
                if (!r) return nullptr;
            }
        }
        // child._has_focus = had_focus
        if (PyObject_SetAttr(child, n->has_focus, f.had_focus.get()) < 0) return nullptr;
        // child.__dict__["_got_focus_called"] = had_got
        if (own_dict_set(child, n->got_focus_called, f.had_got.get(), n) < 0) return nullptr;
    }
    // return child._status
    return return_status(child, n, f);
}

// `_dispatch_priority_child(child, game_time)`. Owned status.
PyObject* dispatch_priority_child_call(const Ctx& c, PyObject* child, PyObject* gt) {
    Ref fn(load_global(c.g, c.n->dispatch_priority_child));
    if (!fn) return nullptr;
    const int s = stock_fn(c, c.n->dispatch_priority_child, fn.get());
    if (s < 0) return nullptr;
    if (s) return dispatch_priority_child_impl(c, child, gt);
    return call2(fn.get(), child, gt);
}

// `isinstance(obj, <global class>)`. 1, 0, -1.
int isinstance_global(const Ctx& c, PyObject* obj, PyObject* gname) {
    Ref cls(load_global(c.g, gname));
    if (!cls) return -1;
    return PyObject_IsInstance(obj, cls.get());
}

// `_note_due_ret(child._next_update_time)`'s truth: the callee loaded, then
// the attribute. The stock body (`_note_due(when); return True`) runs
// inline. 1, 0, -1.
int note_due_ret_test(const Ctx& c, PyObject* child) {
    Ref fn(load_global(c.g, c.n->note_due_ret));
    if (!fn) return -1;
    Ref when(PyObject_GetAttr(child, c.n->next_update_time));
    if (!when) return -1;
    const int s = stock_fn(c, c.n->note_due_ret, fn.get());
    if (s < 0) return -1;
    if (s) {
        // _note_due(when); return True
        Ref nd(load_global(c.g, c.n->note_due));
        if (!nd) return -1;
        if (our_builtin(nd.get(), fast<note_due>())) {
            if (note_due_value(when.get()) < 0) return -1;
        } else {
            Ref r(PyObject_CallOneArg(nd.get(), when.get()));
            if (!r) return -1;
        }
        return 1;
    }
    Ref r(PyObject_CallOneArg(fn.get(), when.get()));
    if (!r) return -1;
    when = Ref();
    return PyObject_IsTrue(r.get());
}

// _tick_priority_list
PyObject* priority_list_impl(const Ctx& c, PyObject* ai, PyObject* gt) {
    const Names* n = c.n;
    ++g_kind_runs[kPriorityList];
    struct Frame {
        Ref prio, child;  // _prio, child
        void release() {
            prio = Ref();
            child = Ref();
        }
        ~Frame() { release(); }
    } f;
    // for _prio, child in ai._ais:
    Ref it;
    {
        Ref ais(PyObject_GetAttr(ai, n->ais));
        if (!ais) return nullptr;
        it = Ref(PyObject_GetIter(ais.get()));
        if (!it) return nullptr;
    }
    // A `return` inside the loop: the value is loaded, then the iterator
    // popped, then the frame cleared.
    auto return_in_loop = [&](Ref& iter) -> PyObject* {
        Ref r(PyObject_GetAttr(ai, n->status));
        if (!r) return nullptr;
        iter = Ref();
        f.release();
        return r.steal();
    };
    for (;;) {
        {
            Ref item(PyIter_Next(it.get()));
            if (!item) {
                if (PyErr_Occurred()) return nullptr;
                break;
            }
            Ref a, b;
            if (unpack2(item.get(), &a, &b) < 0) return nullptr;
            item = Ref();
            f.prio = std::move(a);
            f.child = std::move(b);
        }
        // `child` borrows the frame's own slot, which only this loop rebinds.
        PyObject* child = f.child.get();
        // if isinstance(child, ConditionalAI): _refresh_conditional_status(child)
        {
            const int is = isinstance_global(c, child, n->conditional_cls);
            if (is < 0) return nullptr;
            if (is && refresh_stmt(c, child) < 0) return nullptr;
        }
        // if child._status == US_DONE: continue
        {
            const int done = attr_cmp_global(c, f.child.get(), n->status, n->us_done, Py_EQ);
            if (done < 0) return nullptr;
            if (done) continue;
        }
        // if child._status == US_DORMANT:
        {
            const int dormant =
                attr_cmp_global(c, f.child.get(), n->status, n->us_dormant, Py_EQ);
            if (dormant < 0) return nullptr;
            if (dormant) {
                // if not (isinstance(child, PreprocessingAI)
                //         and _note_due_ret(child._next_update_time)
                //         and game_time >= child._next_update_time):
                //     continue
                int probe = isinstance_global(c, f.child.get(), n->preprocessing_cls);
                if (probe < 0) return nullptr;
                if (probe) {
                    probe = note_due_ret_test(c, f.child.get());
                    if (probe < 0) return nullptr;
                }
                if (probe) {
                    Ref due(PyObject_GetAttr(f.child.get(), n->next_update_time));
                    if (!due) return nullptr;
                    probe = compare_owned(Ref(Py_NewRef(gt)), std::move(due), Py_GE);
                    if (probe < 0) return nullptr;
                }
                if (!probe) continue;
                // if _dispatch_priority_child(child, game_time) == US_ACTIVE:
                //     ai._status = US_ACTIVE
                //     return ai._status
                // continue
                Ref st(dispatch_priority_child_call(c, f.child.get(), gt));
                if (!st) return nullptr;
                Ref active(load_global(c.g, n->us_active));
                if (!active) return nullptr;
                const int eq = compare_owned(std::move(st), std::move(active), Py_EQ);
                if (eq < 0) return nullptr;
                if (eq) {
                    if (set_attr_global(c, ai, n->status, n->us_active) < 0) return nullptr;
                    return return_in_loop(it);
                }
                continue;
            }
        }
        // if _dispatch_priority_child(child, game_time) == US_ACTIVE:
        //     ai._status = US_ACTIVE
        // return ai._status
        {
            Ref st(dispatch_priority_child_call(c, f.child.get(), gt));
            if (!st) return nullptr;
            Ref active(load_global(c.g, n->us_active));
            if (!active) return nullptr;
            const int eq = compare_owned(std::move(st), std::move(active), Py_EQ);
            if (eq < 0) return nullptr;
            if (eq && set_attr_global(c, ai, n->status, n->us_active) < 0) return nullptr;
        }
        return return_in_loop(it);
    }
    it = Ref();
    // if ai._ais and all(c._status == US_DONE for _p, c in ai._ais):
    //     ai._status = US_DONE
    int all_done;
    {
        Ref ais(PyObject_GetAttr(ai, n->ais));
        if (!ais) return nullptr;
        all_done = PyObject_IsTrue(ais.get());
        if (all_done < 0) return nullptr;
    }
    if (all_done) {
        Ref git;
        {
            Ref ais(PyObject_GetAttr(ai, n->ais));
            if (!ais) return nullptr;
            git = Ref(PyObject_GetIter(ais.get()));
            if (!git) return nullptr;
        }
        Ref p, cc;  // the generator's frame: `.0` (git), `_p`, `c`
        for (;;) {
            Ref item(PyIter_Next(git.get()));
            if (!item) {
                if (PyErr_Occurred()) return nullptr;
                break;
            }
            Ref a, b;
            if (unpack2(item.get(), &a, &b) < 0) return nullptr;
            item = Ref();
            p = std::move(a);
            cc = std::move(b);
            const int done = attr_cmp_global(c, cc.get(), n->status, n->us_done, Py_EQ);
            if (done < 0) return nullptr;
            if (!done) {
                all_done = 0;
                break;
            }
        }
        git = Ref();
        p = Ref();
        cc = Ref();
        if (all_done && set_attr_global(c, ai, n->status, n->us_done) < 0) return nullptr;
    }
    // return ai._status
    return return_status(ai, n, f);
}

// _tick_sequence's `_wrap_or_finish(i)` (a closure over `ai`). Owned: None
// (finished) or the int 0.
PyObject* wrap_or_finish(const Ctx& c, PyObject* ai, PyObject* i) {
    const Names* n = c.n;
    struct Frame {
        Ref remaining, child;
        void release() {
            remaining = Ref();
            child = Ref();
        }
        ~Frame() { release(); }
    } f;
    // remaining = int(getattr(ai, "_loops_remaining", 1))
    {
        Ref v(getattr_or(ai, n->loops_remaining, n->one));
        if (!v) return nullptr;
        Ref as_int(PyNumber_Long(v.get()));
        if (!as_int) return nullptr;
        v = Ref();
        f.remaining = std::move(as_int);
    }
    // if remaining > 0:
    //     remaining -= 1
    //     ai._loops_remaining = remaining
    {
        const int gt0 = compare_owned(Ref(Py_NewRef(f.remaining.get())), Ref(Py_NewRef(n->zero)),
                                      Py_GT);
        if (gt0 < 0) return nullptr;
        if (gt0) {
            Ref v(PyNumber_InPlaceSubtract(f.remaining.get(), n->one));
            if (!v) return nullptr;
            f.remaining = std::move(v);
            if (PyObject_SetAttr(ai, n->loops_remaining, f.remaining.get()) < 0) return nullptr;
        }
    }
    // if remaining == 0:
    //     ai._current_index = i
    //     ai._status = US_DONE
    //     return None
    {
        const int eq0 = compare_owned(Ref(Py_NewRef(f.remaining.get())), Ref(Py_NewRef(n->zero)),
                                      Py_EQ);
        if (eq0 < 0) return nullptr;
        if (eq0) {
            if (PyObject_SetAttr(ai, n->current_index, i) < 0) return nullptr;
            if (set_attr_global(c, ai, n->status, n->us_done) < 0) return nullptr;
            f.release();
            Py_RETURN_NONE;
        }
    }
    // for child in ai._ais: child._status = US_ACTIVE
    {
        Ref it;
        {
            Ref ais(PyObject_GetAttr(ai, n->ais));
            if (!ais) return nullptr;
            it = Ref(PyObject_GetIter(ais.get()));
            if (!it) return nullptr;
        }
        for (;;) {
            Ref next(PyIter_Next(it.get()));
            if (!next) {
                if (PyErr_Occurred()) return nullptr;
                break;
            }
            f.child = std::move(next);
            if (set_attr_global(c, f.child.get(), n->status, n->us_active) < 0) return nullptr;
        }
    }
    // return 0
    f.release();
    return Py_NewRef(n->zero);
}

// _tick_sequence
PyObject* sequence_impl(const Ctx& c, PyObject* ai, PyObject* gt) {
    const Names* n = c.n;
    ++g_kind_runs[kSequence];
    struct Frame {
        Ref nlen, idx, child;  // n, idx, child (`_wrap_or_finish` and `_` hold
                               // nothing observable)
        void release() {
            nlen = Ref();
            idx = Ref();
            child = Ref();
        }
        ~Frame() { release(); }
    } f;
    // if not ai._ais:
    //     ai._status = US_DONE
    //     return ai._status
    {
        Ref ais(PyObject_GetAttr(ai, n->ais));
        if (!ais) return nullptr;
        const int t = PyObject_IsTrue(ais.get());
        if (t < 0) return nullptr;
        if (!t) {
            ais = Ref();
            if (set_attr_global(c, ai, n->status, n->us_done) < 0) return nullptr;
            return return_status(ai, n, f);
        }
    }
    // n = len(ai._ais)
    Py_ssize_t count;
    {
        Ref ais(PyObject_GetAttr(ai, n->ais));
        if (!ais) return nullptr;
        const Py_ssize_t k = PyObject_Size(ais.get());
        if (k < 0) return nullptr;
        f.nlen = Ref(PyLong_FromSsize_t(k));
        if (!f.nlen) return nullptr;
        count = k;
    }
    // idx = getattr(ai, "_current_index", 0)
    f.idx = Ref(getattr_or(ai, n->current_index, n->zero));
    if (!f.idx) return nullptr;
    // `idx >= n` (jumped on)
    auto past_end = [&]() -> int {
        return compare_owned(Ref(Py_NewRef(f.idx.get())), Ref(Py_NewRef(f.nlen.get())), Py_GE);
    };
    // idx = _wrap_or_finish(idx); 1 when it finished (idx is None).
    auto wrap = [&]() -> int {
        Ref v(wrap_or_finish(c, ai, f.idx.get()));
        if (!v) return -1;
        f.idx = std::move(v);
        return f.idx.get() == Py_None ? 1 : 0;
    };
    // idx += 1
    auto step = [&]() -> int {
        Ref v(PyNumber_InPlaceAdd(f.idx.get(), n->one));
        if (!v) return -1;
        f.idx = std::move(v);
        return 0;
    };
    // ai._current_index = idx; ai._status = US_ACTIVE; return ai._status
    auto hold = [&]() -> PyObject* {
        if (PyObject_SetAttr(ai, n->current_index, f.idx.get()) < 0) return nullptr;
        if (set_attr_global(c, ai, n->status, n->us_active) < 0) return nullptr;
        return return_status(ai, n, f);
    };
    // for _ in range(n + 1):   (range of an exact int from len(): n + 1 passes)
    for (Py_ssize_t pass = 0; pass <= count; ++pass) {
        // if idx >= n:
        //     idx = _wrap_or_finish(idx)
        //     if idx is None: return ai._status
        {
            const int past = past_end();
            if (past < 0) return nullptr;
            if (past) {
                const int fin = wrap();
                if (fin < 0) return nullptr;
                if (fin) return return_status(ai, n, f);
            }
        }
        // child = ai._ais[idx]
        {
            Ref ais(PyObject_GetAttr(ai, n->ais));
            if (!ais) return nullptr;
            Ref v(PyObject_GetItem(ais.get(), f.idx.get()));
            if (!v) return nullptr;
            ais = Ref();
            f.child = std::move(v);
        }
        // if isinstance(child, ConditionalAI): _refresh_conditional_status(child)
        {
            const int is = isinstance_global(c, f.child.get(), n->conditional_cls);
            if (is < 0) return nullptr;
            if (is && refresh_stmt(c, f.child.get()) < 0) return nullptr;
        }
        // if child._status == US_DORMANT:
        {
            const int dormant =
                attr_cmp_global(c, f.child.get(), n->status, n->us_dormant, Py_EQ);
            if (dormant < 0) return nullptr;
            if (dormant) {
                // if int(getattr(ai, "_skip_dormant", 0)): idx += 1; continue
                int skip;
                {
                    Ref v(getattr_or(ai, n->skip_dormant, n->zero));
                    if (!v) return nullptr;
                    Ref as_int(PyNumber_Long(v.get()));
                    if (!as_int) return nullptr;
                    v = Ref();
                    skip = PyObject_IsTrue(as_int.get());
                    if (skip < 0) return nullptr;
                }
                if (skip) {
                    if (step() < 0) return nullptr;
                    continue;
                }
                // ai._current_index = idx; ai._status = US_ACTIVE; return ai._status
                return hold();
            }
        }
        // if child._status == US_DONE: idx += 1; continue
        {
            const int done = attr_cmp_global(c, f.child.get(), n->status, n->us_done, Py_EQ);
            if (done < 0) return nullptr;
            if (done) {
                if (step() < 0) return nullptr;
                continue;
            }
        }
        // tick_ai(child, game_time)
        if (tick_stmt(c, f.child.get(), gt) < 0) return nullptr;
        // if child._status == US_DONE:
        //     idx += 1
        //     if idx >= n:
        //         idx = _wrap_or_finish(idx)
        //         if idx is None: return ai._status
        {
            const int done = attr_cmp_global(c, f.child.get(), n->status, n->us_done, Py_EQ);
            if (done < 0) return nullptr;
            if (done) {
                if (step() < 0) return nullptr;
                const int past = past_end();
                if (past < 0) return nullptr;
                if (past) {
                    const int fin = wrap();
                    if (fin < 0) return nullptr;
                    if (fin) return return_status(ai, n, f);
                }
            }
        }
        return hold();
    }
    // ai._current_index = 0
    if (PyObject_SetAttr(ai, n->current_index, n->zero) < 0) return nullptr;
    // ai._status = US_ACTIVE if int(getattr(ai, "_loops_remaining", 1)) != 0 else US_DONE
    {
        int more;
        {
            Ref v(getattr_or(ai, n->loops_remaining, n->one));
            if (!v) return nullptr;
            Ref as_int(PyNumber_Long(v.get()));
            if (!as_int) return nullptr;
            v = Ref();
            more = compare_owned(std::move(as_int), Ref(Py_NewRef(n->zero)), Py_NE);
            if (more < 0) return nullptr;
        }
        if (set_attr_global(c, ai, n->status, more ? n->us_active : n->us_done) < 0)
            return nullptr;
    }
    return return_status(ai, n, f);
}

// _tick_random
PyObject* random_impl(const Ctx& c, PyObject* ai, PyObject* gt) {
    const Names* n = c.n;
    ++g_kind_runs[kRandom];
    struct Frame {
        Ref child;
        void release() { child = Ref(); }
        ~Frame() { release(); }
    } f;
    // if not ai._ais: ai._status = US_DONE; return ai._status
    {
        Ref ais(PyObject_GetAttr(ai, n->ais));
        if (!ais) return nullptr;
        const int t = PyObject_IsTrue(ais.get());
        if (t < 0) return nullptr;
        if (!t) {
            ais = Ref();
            if (set_attr_global(c, ai, n->status, n->us_done) < 0) return nullptr;
            return return_status(ai, n, f);
        }
    }
    // child = ai._current_child
    f.child = Ref(PyObject_GetAttr(ai, n->current_child));
    if (!f.child) return nullptr;
    // if child is None or child._status in (US_DONE, US_DORMANT):
    int redraw = f.child.get() == Py_None;
    if (!redraw) {
        Ref st(PyObject_GetAttr(f.child.get(), n->status));
        if (!st) return nullptr;
        Ref pair;
        {
            Ref done(load_global(c.g, n->us_done));
            if (!done) return nullptr;
            Ref dormant(load_global(c.g, n->us_dormant));
            if (!dormant) return nullptr;
            pair = Ref(PyTuple_Pack(2, done.get(), dormant.get()));
            if (!pair) return nullptr;
        }
        redraw = PySequence_Contains(pair.get(), st.get());
        if (redraw < 0) return nullptr;
    }
    if (redraw) {
        // if not ai._untried: ai._untried = list(ai._ais)
        {
            Ref u(PyObject_GetAttr(ai, n->untried));
            if (!u) return nullptr;
            const int t = PyObject_IsTrue(u.get());
            if (t < 0) return nullptr;
            u = Ref();
            if (!t) {
                Ref ais(PyObject_GetAttr(ai, n->ais));
                if (!ais) return nullptr;
                Ref l(PySequence_List(ais.get()));
                if (!l) return nullptr;
                ais = Ref();
                if (PyObject_SetAttr(ai, n->untried, l.get()) < 0) return nullptr;
            }
        }
        // child = random.choice(ai._untried)
        {
            Ref v;
            {
                Ref rnd(load_global(c.g, n->random));
                if (!rnd) return nullptr;
                Ref choice(PyObject_GetAttr(rnd.get(), n->choice));
                if (!choice) return nullptr;
                Ref u(PyObject_GetAttr(ai, n->untried));
                if (!u) return nullptr;
                v = Ref(PyObject_CallOneArg(choice.get(), u.get()));
                if (!v) return nullptr;
            }
            f.child = std::move(v);
        }
        // ai._untried.remove(child)
        {
            Ref u(PyObject_GetAttr(ai, n->untried));
            if (!u) return nullptr;
            Ref r(PyObject_CallMethodOneArg(u.get(), n->remove, f.child.get()));
            if (!r) return nullptr;
        }
        // child._status = US_ACTIVE
        if (set_attr_global(c, f.child.get(), n->status, n->us_active) < 0) return nullptr;
        // ai._current_child = child
        if (PyObject_SetAttr(ai, n->current_child, f.child.get()) < 0) return nullptr;
    }
    // tick_ai(child, game_time)
    if (tick_stmt(c, f.child.get(), gt) < 0) return nullptr;
    // ai._status = US_ACTIVE; return ai._status
    if (set_attr_global(c, ai, n->status, n->us_active) < 0) return nullptr;
    return return_status(ai, n, f);
}

// `ai._contained_ai is not None` (the attribute released before the jump).
int has_contained(PyObject* ai, const Names* n) {
    Ref ca(PyObject_GetAttr(ai, n->contained_ai));
    if (!ca) return -1;
    return ca.get() != Py_None ? 1 : 0;
}

// `if ai._contained_ai._status == US_DONE: ai._status = US_DONE`. 0 / -1.
int fold_contained_done(const Ctx& c, PyObject* ai) {
    const Names* n = c.n;
    Ref st;
    {
        Ref ca(PyObject_GetAttr(ai, n->contained_ai));
        if (!ca) return -1;
        st = Ref(PyObject_GetAttr(ca.get(), n->status));
        if (!st) return -1;
    }
    Ref done(load_global(c.g, n->us_done));
    if (!done) return -1;
    const int eq = compare_owned(std::move(st), std::move(done), Py_EQ);
    if (eq < 0) return -1;
    if (eq && set_attr_global(c, ai, n->status, n->us_done) < 0) return -1;
    return 0;
}

// _tick_conditional
PyObject* conditional_impl(const Ctx& c, PyObject* ai, PyObject* gt) {
    const Names* n = c.n;
    ++g_kind_runs[kConditional];
    struct Frame {
        Ref eval_fn, args, active;
        void release() {
            eval_fn = Ref();
            args = Ref();
            active = Ref();
        }
        ~Frame() { release(); }
    } f;
    // eval_fn = ai._evaluation_function
    f.eval_fn = Ref(PyObject_GetAttr(ai, n->evaluation_function));
    if (!f.eval_fn) return nullptr;
    if (f.eval_fn.get() != Py_None) {
        // args = _condition_statuses(ai)
        f.args = Ref(condition_statuses_call(c, ai));
        if (!f.args) return nullptr;
        // ai._status = _eval_conditional(ai, eval_fn, args)
        {
            Ref v(eval_conditional_call(c, ai, f.eval_fn.get(), f.args.get()));
            if (!v) return nullptr;
            if (PyObject_SetAttr(ai, n->status, v.get()) < 0) return nullptr;
        }
        // if ai._status == US_ACTIVE and ai._contained_ai is not None:
        //     tick_ai(ai._contained_ai, game_time)
        //     if ai._contained_ai._status == US_DONE: ai._status = US_DONE
        int go = attr_cmp_global(c, ai, n->status, n->us_active, Py_EQ);
        if (go < 0) return nullptr;
        if (go) {
            go = has_contained(ai, n);
            if (go < 0) return nullptr;
        }
        if (go) {
            if (tick_attr_stmt(c, ai, n->contained_ai, gt) < 0) return nullptr;
            if (fold_contained_done(c, ai) < 0) return nullptr;
        }
        return return_status(ai, n, f);
    }
    // active = _any_condition(ai) if ai._conditions else False
    {
        int has;
        {
            Ref conds(PyObject_GetAttr(ai, n->conditions));
            if (!conds) return nullptr;
            has = PyObject_IsTrue(conds.get());
            if (has < 0) return nullptr;
        }
        Ref v(has ? any_condition_call(c, ai) : Py_NewRef(Py_False));
        if (!v) return nullptr;
        f.active = std::move(v);
    }
    // if not active: ai._status = US_DORMANT; return ai._status
    {
        const int t = PyObject_IsTrue(f.active.get());
        if (t < 0) return nullptr;
        if (!t) {
            if (set_attr_global(c, ai, n->status, n->us_dormant) < 0) return nullptr;
            return return_status(ai, n, f);
        }
    }
    // ai._status = US_ACTIVE
    if (set_attr_global(c, ai, n->status, n->us_active) < 0) return nullptr;
    // if ai._contained_ai is not None: tick_ai(ai._contained_ai, game_time)
    {
        const int has = has_contained(ai, n);
        if (has < 0) return nullptr;
        if (has && tick_attr_stmt(c, ai, n->contained_ai, gt) < 0) return nullptr;
    }
    return return_status(ai, n, f);
}

// _tick_preprocessing's frame (co_varnames, then the cell `bound`; the
// `game_time` cell is the argument's own slot).
struct PreFrame {
    Ref inst, method, cache, sig, arity, contained, result, next_update_fn, nxt, interval, last,
        bound;
    void release() {
        inst = Ref();
        method = Ref();
        cache = Ref();
        sig = Ref();
        arity = Ref();
        contained = Ref();
        result = Ref();
        next_update_fn = Ref();
        nxt = Ref();
        interval = Ref();
        last = Ref();
        bound = Ref();
    }
    ~PreFrame() { release(); }
};

// `bound = getattr(inst, method)`: the builtin's own check of the name, then
// the lookup. 0 / -1.
int bind_method(PreFrame& f) {
    if (!PyUnicode_Check(f.method.get())) {
        PyErr_SetString(PyExc_TypeError, "getattr(): attribute name must be string");
        return -1;
    }
    Ref b(PyObject_GetAttr(f.inst.get(), f.method.get()));
    if (!b) return -1;
    f.bound = std::move(b);
    return 0;
}

// The arity probe's try body:
//     sig = inspect.signature(bound)
//     arity = sum(1 for p in sig.parameters.values()
//                 if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
//                               inspect.Parameter.POSITIONAL_OR_KEYWORD))
// 0, or -1 with the exception set (the caller's `except` decides).
int arity_try(const Ctx& c, PreFrame& f) {
    const Names* n = c.n;
    {
        Ref insp(load_global(c.g, n->inspect));
        if (!insp) return -1;
        Ref sig(PyObject_CallMethodOneArg(insp.get(), n->signature, f.bound.get()));
        if (!sig) return -1;
        insp = Ref();
        f.sig = std::move(sig);
    }
    Ref it;
    {
        Ref params(PyObject_GetAttr(f.sig.get(), n->parameters));
        if (!params) return -1;
        Ref vals(PyObject_CallMethodNoArgs(params.get(), n->values));
        if (!vals) return -1;
        params = Ref();
        it = Ref(PyObject_GetIter(vals.get()));
        if (!it) return -1;
    }
    Py_ssize_t count = 0;
    Ref p;  // the generator's frame: `.0` (it), `p`
    for (;;) {
        Ref next(PyIter_Next(it.get()));
        if (!next) {
            if (PyErr_Occurred()) return -1;
            break;
        }
        p = std::move(next);
        Ref kind(PyObject_GetAttr(p.get(), n->kind));
        if (!kind) return -1;
        Ref pair;
        {
            Ref first, second;
            {
                Ref insp(load_global(c.g, n->inspect));
                if (!insp) return -1;
                Ref param(PyObject_GetAttr(insp.get(), n->parameter));
                if (!param) return -1;
                first = Ref(PyObject_GetAttr(param.get(), n->positional_only));
                if (!first) return -1;
            }
            {
                Ref insp(load_global(c.g, n->inspect));
                if (!insp) return -1;
                Ref param(PyObject_GetAttr(insp.get(), n->parameter));
                if (!param) return -1;
                second = Ref(PyObject_GetAttr(param.get(), n->positional_or_keyword));
                if (!second) return -1;
            }
            pair = Ref(PyTuple_Pack(2, first.get(), second.get()));
            if (!pair) return -1;
        }
        // CONTAINS_OP: both operands released after the test.
        const int in = PySequence_Contains(pair.get(), kind.get());
        kind = Ref();
        pair = Ref();
        if (in < 0) return -1;
        if (in) ++count;
    }
    it = Ref();
    p = Ref();
    Ref arity(PyLong_FromSsize_t(count));
    if (!arity) return -1;
    f.arity = std::move(arity);
    return 0;
}

// `if <local> == PS_*:` and the three-way PS_* mapping shared by the two
// arms. 1: a mapped status was set and the caller returns ai._status (after
// _retain_subtree_focus for SKIP_ACTIVE); 0: PS_NORMAL, fall through; -1.
int map_ps(const Ctx& c, PyObject* ai, PyObject* value) {
    const Names* n = c.n;
    int eq = local_cmp_global(c, value, n->ps_skip_active, Py_EQ);
    if (eq < 0) return -1;
    if (eq) {
        if (set_attr_global(c, ai, n->status, n->us_active) < 0) return -1;
        if (retain_subtree_focus_stmt(c, ai) < 0) return -1;
        return 1;
    }
    eq = local_cmp_global(c, value, n->ps_skip_dormant, Py_EQ);
    if (eq < 0) return -1;
    if (eq) {
        if (set_attr_global(c, ai, n->status, n->us_dormant) < 0) return -1;
        return 1;
    }
    const int ne = local_cmp_global(c, value, n->ps_normal, Py_NE);
    if (ne < 0) return -1;
    if (ne) {
        if (set_attr_global(c, ai, n->status, n->us_done) < 0) return -1;
        return 1;
    }
    return 0;
}

// _tick_preprocessing
PyObject* preprocessing_impl(const Ctx& c, PyObject* ai, PyObject* gt) {
    const Names* n = c.n;
    ++g_kind_runs[kPreprocessing];
    PreFrame f;
    // inst = ai._preprocessing_instance
    f.inst = Ref(PyObject_GetAttr(ai, n->preprocessing_instance));
    if (!f.inst) return nullptr;
    // method = ai._preprocessing_method
    f.method = Ref(PyObject_GetAttr(ai, n->preprocessing_method));
    if (!f.method) return nullptr;
    // if inst is None or not method:
    //     if ai._contained_ai is not None: tick_ai(ai._contained_ai, game_time)
    //     return ai._status
    {
        int bare = f.inst.get() == Py_None;
        if (!bare) {
            const int t = PyObject_IsTrue(f.method.get());
            if (t < 0) return nullptr;
            bare = !t;
        }
        if (bare) {
            const int has = has_contained(ai, n);
            if (has < 0) return nullptr;
            if (has && tick_attr_stmt(c, ai, n->contained_ai, gt) < 0) return nullptr;
            return return_status(ai, n, f);
        }
    }
    // if callable(getattr(inst, "DamageEvent", None)) and getattr(inst, "pCodeAI", None) is not None:
    //     _ensure_select_target_initialized(inst)
    {
        int go;
        {
            Ref de(getattr_or(f.inst.get(), n->damage_event, Py_None));
            if (!de) return nullptr;
            go = PyCallable_Check(de.get());
        }
        if (go) {
            Ref pc(getattr_or(f.inst.get(), n->pcodeai, Py_None));
            if (!pc) return nullptr;
            go = pc.get() != Py_None;
        }
        if (go) {
            Ref fn(load_global(c.g, n->ensure_select));
            if (!fn) return nullptr;
            Ref r(PyObject_CallOneArg(fn.get(), f.inst.get()));
            if (!r) return nullptr;
        }
    }
    // ai._has_focus = True
    if (PyObject_SetAttr(ai, n->has_focus, Py_True) < 0) return nullptr;
    // _reached_this_tick.append(ai)
    if (global_append(c, n->reached, ai) < 0) return nullptr;
    // _queue_got_focus(ai)
    if (queue_got_focus_stmt(c, ai) < 0) return nullptr;
    // cache = ai.__dict__.get("_preprocess_arity_cache")
    f.cache = Ref(obj_dict_get(ai, n->arity_cache, nullptr, n));
    if (!f.cache) return nullptr;
    // if cache is None or cache[0] is not inst or cache[1] != method:
    int miss = f.cache.get() == Py_None;
    if (!miss) {
        Ref c0(subscript(f.cache.get(), 0, n->zero));
        if (!c0) return nullptr;
        miss = c0.get() != f.inst.get();
    }
    if (!miss) {
        Ref c1(subscript(f.cache.get(), 1, n->one));
        if (!c1) return nullptr;
        miss = compare_owned(std::move(c1), Ref(Py_NewRef(f.method.get())), Py_NE);
        if (miss < 0) return nullptr;
    }
    if (miss) {
        // bound = getattr(inst, method)
        if (bind_method(f) < 0) return nullptr;
        // try: ... except (TypeError, ValueError): arity = 0
        if (arity_try(c, f) < 0) {
            if (!PyErr_ExceptionMatches(PyExc_TypeError) &&
                !PyErr_ExceptionMatches(PyExc_ValueError))
                return nullptr;
            PyErr_Clear();
            f.arity = Ref(Py_NewRef(n->zero));
        }
        // ai._preprocess_arity_cache = (inst, method, arity)
        {
            Ref t(PyTuple_Pack(3, f.inst.get(), f.method.get(), f.arity.get()));
            if (!t) return nullptr;
            if (PyObject_SetAttr(ai, n->arity_cache, t.get()) < 0) return nullptr;
        }
        // cache = ai._preprocess_arity_cache
        {
            Ref v(PyObject_GetAttr(ai, n->arity_cache));
            if (!v) return nullptr;
            f.cache = std::move(v);
        }
    }
    // arity = cache[2]
    {
        Ref v(subscript(f.cache.get(), 2, n->two));
        if (!v) return nullptr;
        f.arity = std::move(v);
    }
    // contained = ai._contained_ai
    f.contained = Ref(PyObject_GetAttr(ai, n->contained_ai));
    if (!f.contained) return nullptr;
    // if (contained is not None and contained._status == US_ACTIVE
    //         and not contained.IsInterruptable()):
    //     ai._status = US_ACTIVE
    //     tick_ai(contained, game_time)
    //     return ai._status
    {
        int bypass = f.contained.get() != Py_None;
        if (bypass) {
            bypass = attr_cmp_global(c, f.contained.get(), n->status, n->us_active, Py_EQ);
            if (bypass < 0) return nullptr;
        }
        if (bypass) {
            Ref r(PyObject_CallMethodNoArgs(f.contained.get(), n->is_interruptable));
            if (!r) return nullptr;
            const int t = PyObject_IsTrue(r.get());
            if (t < 0) return nullptr;
            bypass = !t;
        }
        if (bypass) {
            if (set_attr_global(c, ai, n->status, n->us_active) < 0) return nullptr;
            if (tick_stmt(c, f.contained.get(), gt) < 0) return nullptr;
            return return_status(ai, n, f);
        }
    }
    // if game_time >= ai._next_update_time:
    int due;
    {
        Ref when(PyObject_GetAttr(ai, n->next_update_time));
        if (!when) return nullptr;
        due = compare_owned(Ref(Py_NewRef(gt)), std::move(when), Py_GE);
        if (due < 0) return nullptr;
    }
    if (due) {
        // bound = getattr(inst, method)
        if (bind_method(f) < 0) return nullptr;
        // if arity >= 1: result = _run_script_step(ai, lambda: bound(game_time + 1.0))
        // else:          result = _run_script_step(ai, bound)
        {
            const int ge = compare_owned(Ref(Py_NewRef(f.arity.get())), Ref(Py_NewRef(n->one)),
                                         Py_GE);
            if (ge < 0) return nullptr;
            Ref v;
            {
                Ref fn(load_global(c.g, n->run_script_step));
                if (!fn) return nullptr;
                Ref call(ge ? make_end_time_call(f.bound.get(), gt) : Py_NewRef(f.bound.get()));
                if (!call) return nullptr;
                v = Ref(call2(fn.get(), ai, call.get()));
                if (!v) return nullptr;
            }
            f.result = std::move(v);
        }
        // if result is None: result = PS_NORMAL
        if (f.result.get() == Py_None) {
            Ref v(load_global(c.g, n->ps_normal));
            if (!v) return nullptr;
            f.result = std::move(v);
        }
        // ai._last_preprocess_status = result
        if (PyObject_SetAttr(ai, n->last_preprocess_status, f.result.get()) < 0) return nullptr;
        // _sync_fire_script_target_subsystem(inst)
        {
            Ref fn(load_global(c.g, n->sync_fire));
            if (!fn) return nullptr;
            Ref r(PyObject_CallOneArg(fn.get(), f.inst.get()));
            if (!r) return nullptr;
        }
        // next_update_fn = getattr(inst, "GetNextUpdateTime", None)
        {
            Ref v(getattr_or(f.inst.get(), n->get_next_update_time, Py_None));
            if (!v) return nullptr;
            f.next_update_fn = std::move(v);
        }
        // nxt = next_update_fn() if callable(next_update_fn) else None
        {
            Ref v(PyCallable_Check(f.next_update_fn.get())
                      ? PyObject_CallNoArgs(f.next_update_fn.get())
                      : Py_NewRef(Py_None));
            if (!v) return nullptr;
            f.nxt = std::move(v);
        }
        // interval = float(nxt) if nxt is not None else 0.0
        {
            Ref v(f.nxt.get() != Py_None ? py_float(f.nxt.get()) : Py_NewRef(n->fzero));
            if (!v) return nullptr;
            f.interval = std::move(v);
        }
        // ai._next_update_time = game_time + interval
        {
            Ref v(add_obj(gt, f.interval.get()));
            if (!v) return nullptr;
            if (PyObject_SetAttr(ai, n->next_update_time, v.get()) < 0) return nullptr;
        }
        // _note_due(ai._next_update_time)
        if (note_due_attr_stmt(c, ai) < 0) return nullptr;
        // the PS_* mapping on `result`
        const int mapped = map_ps(c, ai, f.result.get());
        if (mapped < 0) return nullptr;
        if (mapped) return return_status(ai, n, f);
    } else {
        // _note_due(ai._next_update_time)
        if (note_due_attr_stmt(c, ai) < 0) return nullptr;
        // last = ai._last_preprocess_status
        f.last = Ref(PyObject_GetAttr(ai, n->last_preprocess_status));
        if (!f.last) return nullptr;
        // the PS_* mapping on `last`
        const int mapped = map_ps(c, ai, f.last.get());
        if (mapped < 0) return nullptr;
        if (mapped) return return_status(ai, n, f);
    }
    // ai._status = US_ACTIVE
    if (set_attr_global(c, ai, n->status, n->us_active) < 0) return nullptr;
    // if ai._contained_ai is not None:
    //     tick_ai(ai._contained_ai, game_time)
    //     if ai._contained_ai._status == US_DONE: ai._status = US_DONE
    {
        const int has = has_contained(ai, n);
        if (has < 0) return nullptr;
        if (has) {
            if (tick_attr_stmt(c, ai, n->contained_ai, gt) < 0) return nullptr;
            if (fold_contained_done(c, ai) < 0) return nullptr;
        }
    }
    return return_status(ai, n, f);
}

// _tick_builder
PyObject* builder_impl(const Ctx& c, PyObject* ai, PyObject* gt) {
    const Names* n = c.n;
    ++g_kind_runs[kBuilder];
    // if ai._activation_failed: return US_DONE
    {
        Ref v(PyObject_GetAttr(ai, n->activation_failed));
        if (!v) return nullptr;
        const int t = PyObject_IsTrue(v.get());
        if (t < 0) return nullptr;
        if (t) return load_global(c.g, n->us_done);
    }
    // if not ai._activated:
    //     _activate_builder(ai)
    //     if ai._activation_failed: return US_DONE
    {
        int activated;
        {
            Ref v(PyObject_GetAttr(ai, n->activated));
            if (!v) return nullptr;
            activated = PyObject_IsTrue(v.get());
            if (activated < 0) return nullptr;
        }
        if (!activated) {
            {
                Ref fn(load_global(c.g, n->activate_builder));
                if (!fn) return nullptr;
                Ref r(PyObject_CallOneArg(fn.get(), ai));
                if (!r) return nullptr;
            }
            Ref v(PyObject_GetAttr(ai, n->activation_failed));
            if (!v) return nullptr;
            const int t = PyObject_IsTrue(v.get());
            if (t < 0) return nullptr;
            if (t) return load_global(c.g, n->us_done);
        }
    }
    // return _tick_preprocessing(ai, game_time)
    Ref fn(load_global(c.g, n->tick_preprocessing));
    if (!fn) return nullptr;
    const int s = stock_fn(c, n->tick_preprocessing, fn.get());
    if (s < 0) return nullptr;
    if (s) return preprocessing_impl(c, ai, gt);
    return call2(fn.get(), ai, gt);
}

PyObject* run_handler(int kind, const Ctx& c, PyObject* ai, PyObject* gt) {
    switch (kind) {
        case kPlain: return plain_impl(c, ai, gt);
        case kPriorityList: return priority_list_impl(c, ai, gt);
        case kSequence: return sequence_impl(c, ai, gt);
        case kRandom: return random_impl(c, ai, gt);
        case kConditional: return conditional_impl(c, ai, gt);
        case kPreprocessing: return preprocessing_impl(c, ai, gt);
        case kBuilder: return builder_impl(c, ai, gt);
        default: break;
    }
    PyErr_SetString(PyExc_SystemError, "aitree: unknown handler kind");
    return nullptr;
}

// _dispatch_ai's body. Owned status.
PyObject* dispatch_impl(const Ctx& c, PyObject* ai, PyObject* gt) {
    const Names* n = c.n;
    struct Frame {
        Ref ship, dead, node_id, node_type, handler;  // ship, _dead, node_id, node_type, handler
        void release() {
            ship = Ref();
            dead = Ref();
            node_id = Ref();
            node_type = Ref();
            handler = Ref();
        }
        ~Frame() { release(); }
    } f;
    auto return_done = [&]() -> PyObject* {
        Ref r(load_global(c.g, n->us_done));
        if (!r) return nullptr;
        f.release();
        return r.steal();
    };
    // if ai is None: return US_DONE
    if (ai == Py_None) return return_done();
    // ship = ai.GetShip() if hasattr(ai, "GetShip") else None
    {
        PyObject* probe = nullptr;
        const int has = lookup_attr(ai, n->get_ship, &probe);
        if (has < 0) return nullptr;
        Py_XDECREF(probe);
        Ref v(has ? PyObject_CallMethodNoArgs(ai, n->get_ship) : Py_NewRef(Py_None));
        if (!v) return nullptr;
        f.ship = std::move(v);
    }
    // if ship is not None:
    if (f.ship.get() != Py_None) {
        // if _ooa_cache[0] is ship:
        bool same;
        {
            Ref oc(load_global(c.g, n->ooa_cache));
            if (!oc) return nullptr;
            Ref s0(subscript(oc.get(), 0, n->zero));
            if (!s0) return nullptr;
            same = s0.get() == f.ship.get();
        }
        if (same) {
            // if _ooa_cache[1]: return US_DONE
            int t;
            {
                Ref oc(load_global(c.g, n->ooa_cache));
                if (!oc) return nullptr;
                Ref s1(subscript(oc.get(), 1, n->one));
                if (!s1) return nullptr;
                oc = Ref();
                t = PyObject_IsTrue(s1.get());
                if (t < 0) return nullptr;
            }
            if (t) return return_done();
        } else {
            // _dead = ship_death._out_of_action(ship)
            {
                Ref sd(load_global(c.g, n->ship_death));
                if (!sd) return nullptr;
                Ref v(PyObject_CallMethodOneArg(sd.get(), n->out_of_action, f.ship.get()));
                if (!v) return nullptr;
                sd = Ref();
                f.dead = std::move(v);
            }
            // _ooa_cache[0] = ship
            // _ooa_cache[1] = _dead
            {
                Ref oc(load_global(c.g, n->ooa_cache));
                if (!oc) return nullptr;
                if (PyObject_SetItem(oc.get(), n->zero, f.ship.get()) < 0) return nullptr;
            }
            {
                Ref oc(load_global(c.g, n->ooa_cache));
                if (!oc) return nullptr;
                if (PyObject_SetItem(oc.get(), n->one, f.dead.get()) < 0) return nullptr;
            }
            // if _dead: return US_DONE
            const int t = PyObject_IsTrue(f.dead.get());
            if (t < 0) return nullptr;
            if (t) return return_done();
        }
    }
    // node_id = id(ai)
    f.node_id = Ref(PyLong_FromVoidPtr(ai));
    if (!f.node_id) return nullptr;
    // if node_id not in _reached_this_tick_all_ids:
    //     _reached_this_tick_all_ids.add(node_id)
    //     _reached_this_tick_all.append(ai)
    {
        int in;
        {
            Ref ids(load_global(c.g, n->reached_all_ids));
            if (!ids) return nullptr;
            in = PySequence_Contains(ids.get(), f.node_id.get());
            if (in < 0) return nullptr;
        }
        if (!in) {
            {
                Ref ids(load_global(c.g, n->reached_all_ids));
                if (!ids) return nullptr;
                if (PySet_CheckExact(ids.get())) {
                    if (PySet_Add(ids.get(), f.node_id.get()) < 0) return nullptr;
                } else {
                    Ref r(PyObject_CallMethodOneArg(ids.get(), n->add, f.node_id.get()));
                    if (!r) return nullptr;
                }
            }
            if (global_append(c, n->reached_all, ai) < 0) return nullptr;
        }
    }
    // node_type = type(ai)
    f.node_type = Ref(Py_NewRef(reinterpret_cast<PyObject*>(Py_TYPE(ai))));
    // handler = _DISPATCH_BY_TYPE.get(node_type, _UNRESOLVED)
    {
        Ref table(load_global(c.g, n->dispatch_by_type));
        if (!table) return nullptr;
        Ref unresolved(load_global(c.g, n->unresolved));
        if (!unresolved) return nullptr;
        Ref v(dict_get(table.get(), f.node_type.get(), unresolved.get(), n));
        if (!v) return nullptr;
        table = Ref();
        unresolved = Ref();
        f.handler = std::move(v);
    }
    // if handler is _UNRESOLVED:
    //     handler = _DISPATCH_BY_TYPE[node_type] = _resolve_dispatch(node_type)
    {
        bool unresolved;
        {
            Ref u(load_global(c.g, n->unresolved));
            if (!u) return nullptr;
            unresolved = f.handler.get() == u.get();
        }
        if (unresolved) {
            Ref v;
            {
                Ref fn(load_global(c.g, n->resolve_dispatch));
                if (!fn) return nullptr;
                v = Ref(PyObject_CallOneArg(fn.get(), f.node_type.get()));
                if (!v) return nullptr;
            }
            f.handler = Ref(Py_NewRef(v.get()));
            Ref table(load_global(c.g, n->dispatch_by_type));
            if (!table) return nullptr;
            if (PyObject_SetItem(table.get(), f.node_type.get(), v.get()) < 0) return nullptr;
        }
    }
    // if handler is None: return ai._status
    if (f.handler.get() == Py_None) return return_status(ai, n, f);
    // if _AI_BREAKDOWN is not None: return _timed_dispatch(handler, ai, game_time)
    {
        bool timed;
        {
            Ref bd(load_global(c.g, n->ai_breakdown));
            if (!bd) return nullptr;
            timed = bd.get() != Py_None;
        }
        if (timed) {
            Ref r;
            {
                Ref fn(load_global(c.g, n->timed_dispatch));
                if (!fn) return nullptr;
                r = Ref(call3(fn.get(), f.handler.get(), ai, gt));
                if (!r) return nullptr;
            }
            f.release();
            return r.steal();
        }
    }
    // return handler(ai, game_time)
    const int kind = handler_kind(c, f.handler.get());
    if (kind < 0) return nullptr;
    Ref r(kind ? run_handler(kind, c, ai, gt) : call2(f.handler.get(), ai, gt));
    if (!r) return nullptr;
    f.release();
    return r.steal();
}

// `_focus_depth += 1` / `-= 1` (LOAD_GLOBAL, the in-place operator,
// STORE_GLOBAL). 0 / -1.
int bump_depth(const Ctx& c, int delta) {
    Ref d(load_global(c.g, c.n->focus_depth));
    if (!d) return -1;
    Ref v(delta > 0 ? PyNumber_InPlaceAdd(d.get(), c.n->one)
                    : PyNumber_InPlaceSubtract(d.get(), c.n->one));
    if (!v) return -1;
    d = Ref();
    return PyDict_SetItem(c.g, c.n->focus_depth, v.get());
}

// The oracle's `_tick_ai_python`: the native walk of one subtree. Owned status.
PyObject* tick_impl(const Ctx& c, PyObject* ai, PyObject* gt) {
    const Names* n = c.n;
    // Python would raise RecursionError on a cyclic tree; this keeps the C
    // stack from overflowing on one (one level per tick_ai, not Python's).
    if (Py_EnterRecursiveCall(" in the AI tree walk")) return nullptr;
    struct Leave {
        ~Leave() { Py_LeaveRecursiveCall(); }
    } leave;
    ++g_tick_runs;
    struct Frame {
        Ref is_root, status;
        void release() {
            is_root = Ref();
            status = Ref();
        }
        ~Frame() { release(); }
    } f;
    // is_root = _focus_depth == 0
    {
        Ref d(load_global(c.g, n->focus_depth));
        if (!d) return nullptr;
        Ref v(PyObject_RichCompare(d.get(), n->zero, Py_EQ));
        if (!v) return nullptr;
        f.is_root = std::move(v);
    }
    // if is_root:
    //     _ooa_cache[0] = None
    //     _reached_this_tick = []
    //     _reached_this_tick_all = []
    //     _reached_this_tick_all_ids = set()
    //     _pending_got_focus = []
    {
        const int root = PyObject_IsTrue(f.is_root.get());
        if (root < 0) return nullptr;
        if (root) {
            {
                Ref oc(load_global(c.g, n->ooa_cache));
                if (!oc) return nullptr;
                if (PyObject_SetItem(oc.get(), n->zero, Py_None) < 0) return nullptr;
            }
            const struct {
                PyObject* name;
                bool set;
            } fresh[] = {{n->reached, false},
                         {n->reached_all, false},
                         {n->reached_all_ids, true},
                         {n->pending, false}};
            for (const auto& x : fresh) {
                Ref v(x.set ? PySet_New(nullptr) : PyList_New(0));
                if (!v) return nullptr;
                if (PyDict_SetItem(c.g, x.name, v.get()) < 0) return nullptr;
            }
        }
    }
    // _focus_depth += 1
    if (bump_depth(c, +1) < 0) return nullptr;
    // try:
    //     status = _dispatch_ai(ai, game_time)
    // finally:
    //     _focus_depth -= 1
    {
        Ref value;
        // A std::bad_alloc from the native walk becomes MemoryError HERE, so
        // the `finally` below (the depth restore) still runs.
        try {
            Ref fn(load_global(c.g, n->dispatch_ai));
            if (fn) {
                const int s = stock_fn(c, n->dispatch_ai, fn.get());
                if (s > 0)
                    value = Ref(dispatch_impl(c, ai, gt));
                else if (s == 0)
                    value = Ref(call2(fn.get(), ai, gt));
            }
        } catch (const std::bad_alloc&) {
            value = Ref();
            PyErr_NoMemory();
        }
        if (!value) {
            // The finally body runs with the exception pending; one it
            // raises itself has the pending one as its context.
            PyObject *et, *ev, *etb;
            PyErr_Fetch(&et, &ev, &etb);
            if (bump_depth(c, -1) < 0) {
                chain_exceptions(et, ev, etb);
                return nullptr;
            }
            PyErr_Restore(et, ev, etb);
            return nullptr;
        }
        f.status = std::move(value);
    }
    if (bump_depth(c, -1) < 0) return nullptr;
    // if is_root and ai is not None:
    //     _reconcile_focus(ai, _reached_this_tick)
    //     _flush_pending_got_focus()
    //     _reconcile_active(ai, _reached_this_tick_all)
    {
        int go = PyObject_IsTrue(f.is_root.get());
        if (go < 0) return nullptr;
        if (go && ai != Py_None) {
            if (reconcile_stmt(c, n->reconcile_focus, n->reached, ai, reconcile_focus_impl) < 0)
                return nullptr;
            if (flush_stmt(c) < 0) return nullptr;
            if (reconcile_stmt(c, n->reconcile_active, n->reached_all, ai,
                               reconcile_active_impl) < 0)
                return nullptr;
        }
    }
    // return status
    Ref ret(Py_NewRef(f.status.get()));
    f.release();
    return ret.steal();
}

PyObject* tick(PyObject*, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs != 3 || !PyDict_Check(args[2])) {
        PyErr_SetString(PyExc_TypeError, "aitree_tick(ai, game_time, globals: dict)");
        return nullptr;
    }
    try {
        const Names* n = names();
        if (n == nullptr) return nullptr;
        const Ctx c{args[2], n};
        return tick_impl(c, args[0], args[1]);
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

PyObject* reconcile_counts(PyObject*, PyObject* const*, Py_ssize_t nargs) {
    if (nargs != 0) {
        PyErr_SetString(PyExc_TypeError, "aitree_reconcile_counts()");
        return nullptr;
    }
    return Py_BuildValue("(KKKK)", g_s3_runs[0], g_s3_runs[1], g_s3_runs[2],
                         g_activation_skips);
}

PyObject* walk_counts(PyObject*, PyObject* const*, Py_ssize_t nargs) {
    if (nargs != 0) {
        PyErr_SetString(PyExc_TypeError, "aitree_walk_counts()");
        return nullptr;
    }
    return Py_BuildValue("(KKKKKKKK)", g_tick_runs, g_kind_runs[kPlain],
                         g_kind_runs[kPriorityList], g_kind_runs[kSequence],
                         g_kind_runs[kRandom], g_kind_runs[kConditional],
                         g_kind_runs[kPreprocessing], g_kind_runs[kBuilder]);
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
    if (note_due_value(args[0]) < 0) return nullptr;
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

// aitree_run(name, globals, *args): the native body of one of ai_driver's
// forwarders (its `_tick_plain`, `_dispatch_ai`, `_reconcile_focus`, ...).
// The walk runs these inline while the module global is the stock forwarder;
// the forwarder itself is what a patched wrapper (or a test, or ships.py)
// reaches by calling the original, and it lands here. `name` is the Python
// function's name; globals is ai_driver's module dict.
PyObject* run(PyObject*, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs < 2 || !PyUnicode_Check(args[0]) || !PyDict_Check(args[1])) {
        PyErr_SetString(PyExc_TypeError, "aitree_run(name, globals: dict, *args)");
        return nullptr;
    }
    struct Entry {
        const char* name;
        int arity;   // positional arguments after globals
        int kind;    // a handler kind, else 0
    };
    static const Entry kEntries[] = {
        {"_tick_plain", 2, kPlain},
        {"_tick_priority_list", 2, kPriorityList},
        {"_tick_sequence", 2, kSequence},
        {"_tick_random", 2, kRandom},
        {"_tick_conditional", 2, kConditional},
        {"_tick_preprocessing", 2, kPreprocessing},
        {"_tick_builder", 2, kBuilder},
        {"_dispatch_ai", 2, 0},
        {"_dispatch_priority_child", 2, 0},
        {"_queue_got_focus", 1, 0},
        {"_focus_instance_of", 1, 0},
        {"_retain_subtree_focus", 1, 0},
        {"_dispatch_lost_focus", 1, 0},
        {"_reconcile_focus", 2, 0},
        {"_reconcile_active", 2, 0},
        {"_flush_pending_got_focus", 0, 0},
    };
    const Entry* e = nullptr;
    for (const Entry& cand : kEntries) {
        if (PyUnicode_CompareWithASCIIString(args[0], cand.name) == 0) {
            e = &cand;
            break;
        }
    }
    if (e == nullptr) {
        PyErr_Format(PyExc_ValueError, "aitree_run: unknown function %R", args[0]);
        return nullptr;
    }
    if (nargs - 2 != e->arity) {
        PyErr_Format(PyExc_TypeError, "%s() takes %d positional arguments but %zd were given",
                     e->name, e->arity, nargs - 2);
        return nullptr;
    }
    return guarded([&]() -> PyObject* {
        const Names* n = names();
        if (n == nullptr) return nullptr;
        const Ctx c{args[1], n};
        PyObject* const* a = args + 2;
        if (e->kind != 0) return run_handler(e->kind, c, a[0], a[1]);
        const std::string_view f = e->name;
        if (f == "_dispatch_ai") return dispatch_impl(c, a[0], a[1]);
        if (f == "_dispatch_priority_child") return dispatch_priority_child_impl(c, a[0], a[1]);
        if (f == "_queue_got_focus") return queue_got_focus_impl(c, a[0]);
        if (f == "_focus_instance_of") return focus_instance_of_impl(c, a[0]);
        if (f == "_retain_subtree_focus") return retain_subtree_focus_impl(c, a[0]);
        if (f == "_dispatch_lost_focus") return dispatch_lost_focus_impl(c, a[0]);
        if (f == "_reconcile_focus") return reconcile_focus_impl(c, a[0], Ref(Py_NewRef(a[1])));
        if (f == "_reconcile_active") return reconcile_active_impl(c, a[0], Ref(Py_NewRef(a[1])));
        return flush_pending_impl(c);
    });
}

PyMethodDef kDefs[] = {
    {"aitree_run", fast<run>(), METH_FASTCALL,
     "aitree_run(name, globals, *args): the native body of the ai_driver "
     "forwarder `name` (_tick_plain, _dispatch_ai, _reconcile_focus, ...)."},
    {"aitree_tick_all", fast<tick_all>(), METH_FASTCALL,
     "aitree_tick_all(game_time, globals): ai_driver's per-tick roster and "
     "sleep scheduling; each root walk is the native walk while ai_driver's "
     "tick_ai is still the stock forwarder, else tick_ai is called; "
     "`globals` is ai_driver's module dict."},
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
     "_refresh_conditional_status (the memoised EvalFunc, or the "
     "any-non-zero rule, then the contained-DONE fold)."},
    {"aitree_eval_conditional", fast<eval_conditional>(), METH_FASTCALL,
     "aitree_eval_conditional(ai, eval_fn, args, globals) -> ai_driver's "
     "_eval_conditional: the pre-fold status, through the memo."},
    {"aitree_condition_statuses", fast<condition_statuses>(), METH_FASTCALL,
     "aitree_condition_statuses(ai, globals) -> "
     "[c.GetStatus() for c in ai._conditions]."},
    {"aitree_any_condition", fast<any_condition>(), METH_FASTCALL,
     "aitree_any_condition(ai, globals) -> "
     "any(c.GetStatus() != 0 for c in ai._conditions)."},
    {"aitree_tick", fast<tick>(), METH_FASTCALL,
     "aitree_tick(ai, game_time, globals): ai_driver's tick_ai (the native "
     "walk: _dispatch_ai and every stock _tick_* handler); `globals` is "
     "ai_driver's module dict."},
    {"aitree_walk_counts", fast<walk_counts>(), METH_FASTCALL,
     "aitree_walk_counts() -> (native walks started, then native runs of each "
     "stock handler in ai_driver._STOCK_HANDLERS order)."},
    {"aitree_reconcile_counts", fast<reconcile_counts>(), METH_FASTCALL,
     "aitree_reconcile_counts() -> (native runs of _reconcile_focus, "
     "_flush_pending_got_focus and _reconcile_active, then stock SetActive / "
     "SetInactive calls skipped as no-edge)."},
    {"aitree_conditional_counts", fast<conditional_counts>(), METH_FASTCALL,
     "aitree_conditional_counts() -> (native condition-evaluation entries, "
     "stock GetStatus calls read directly)."},
};

}  // namespace

std::span<PyMethodDef> method_defs() { return kDefs; }

}  // namespace dauntless::host::aitree
