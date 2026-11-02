// native/src/host/combat_write_apply.cc -- see combat_write_apply.h.
//
// Every step mirrors a line of engine/appc/native_combat.py (`walk.obj`,
// `_apply_write`, `apply_writes`, `_apply_rest`), in the same order, so the
// same Python runs and the same exception comes out of the same place.

#include "combat_write_apply.h"

#include <algorithm>
#include <type_traits>
#include <unordered_map>
#include <utility>

namespace dauntless::host {

namespace cb = dauntless::combat;

const char* apply_kind_name(ApplyKind k) {
    switch (k) {
        case ApplyKind::PLAIN: return "PLAIN";
        case ApplyKind::REF: return "REF";
        case ApplyKind::REFS: return "REFS";
        case ApplyKind::WAKE: return "WAKE";
        case ApplyKind::PYTHON: return "PYTHON";
        case ApplyKind::SLOT: return "SLOT";
        case ApplyKind::WATCHER: return "WATCHER";
        case ApplyKind::kCount: break;
    }
    return "?";
}

WriteApplier& write_applier() {
    static WriteApplier* a = new WriteApplier;  // owns Python references
    return *a;
}

namespace {

constexpr int kPlain = static_cast<int>(ApplyKind::PLAIN);
constexpr int kRef = static_cast<int>(ApplyKind::REF);
constexpr int kRefs = static_cast<int>(ApplyKind::REFS);
constexpr int kWake = static_cast<int>(ApplyKind::WAKE);
constexpr int kPython = static_cast<int>(ApplyKind::PYTHON);

// An owned reference, released at scope exit.
class Ref {
public:
    explicit Ref(PyObject* p = nullptr) : p_(p) {}
    Ref(const Ref&) = delete;
    Ref& operator=(const Ref&) = delete;
    Ref& operator=(Ref&& o) noexcept {
        if (this != &o) {
            Py_XDECREF(p_);
            p_ = o.release();
        }
        return *this;
    }
    ~Ref() { Py_XDECREF(p_); }
    PyObject* get() const { return p_; }
    explicit operator bool() const { return p_ != nullptr; }
    PyObject* release() {
        PyObject* p = p_;
        p_ = nullptr;
        return p;
    }

private:
    PyObject* p_;
};

// Interned names, created on first use (the GIL held), never released.
struct Names {
    PyObject* dict;
    PyObject* get;
    PyObject* materialise;
    PyObject* walk;
    PyObject* nslot;
    PyObject* asleep;
    PyObject* value;
    PyObject* add_note;
    PyObject* walk_offset;
    PyObject* slot;
    PyObject* watcher;
    PyObject* minus_one;
    PyObject* handle_fmt;
    PyObject* note_fmt;
};

const Names* names() {
    static Names* n = nullptr;
    if (n != nullptr) return n;
    auto* t = new Names;
    t->dict = PyUnicode_InternFromString("__dict__");
    t->get = PyUnicode_InternFromString("get");
    t->materialise = PyUnicode_InternFromString("materialise");
    t->walk = PyUnicode_InternFromString("walk");
    t->nslot = PyUnicode_InternFromString("_nslot");
    t->asleep = PyUnicode_InternFromString("_passive_asleep");
    t->value = PyUnicode_InternFromString("_value");
    t->add_note = PyUnicode_InternFromString("add_note");
    t->walk_offset = PyUnicode_InternFromString("walk_offset");
    t->slot = PyUnicode_InternFromString("slot");
    t->watcher = PyUnicode_InternFromString("watcher");
    t->minus_one = PyLong_FromLong(-1);
    // native_combat._K1Walk.obj's and _apply_rest's messages, verbatim.
    t->handle_fmt = PyUnicode_FromString(
        "combat K1: handle %#x names no pinned or live object");
    t->note_fmt =
        PyUnicode_FromString("combat K1: walk %d's offset also raised %r");
    for (PyObject* o : {t->dict, t->get, t->materialise, t->walk, t->nslot,
                        t->asleep, t->value, t->add_note, t->walk_offset,
                        t->slot, t->watcher, t->minus_one, t->handle_fmt,
                        t->note_fmt}) {
        if (o == nullptr) return nullptr;  // error set; retried next call
    }
    n = t;
    return n;
}

// A field name as an interned str (owned by the table, never released).
PyObject* intern_field(const std::string& s) {
    static auto* table = new std::unordered_map<std::string, PyObject*>;
    auto it = table->find(s);
    if (it != table->end()) return it->second;
    PyObject* o = PyUnicode_InternFromString(s.c_str());
    if (o == nullptr) return nullptr;
    table->emplace(s, o);
    return o;
}

// The context's parts, borrowed from its tuple.
struct Ctx {
    PyObject* pins;
    PyObject* registry;
    PyObject* walk;
    PyObject* kinds;
    PyObject* wake;
    PyObject* setters;
};

Ctx unpack(PyObject* t) {
    return Ctx{PyTuple_GET_ITEM(t, 0), PyTuple_GET_ITEM(t, 1),
               PyTuple_GET_ITEM(t, 2), PyTuple_GET_ITEM(t, 3),
               PyTuple_GET_ITEM(t, 4), PyTuple_GET_ITEM(t, 5)};
}

// ── The (type, field) -> kind cache ──────────────────────────────────────
// Filled from the context's `kinds` mapping, once per (type, field), and
// emptied when a context with another `kinds` object is installed. Keys and
// setters are owned, so a cached type's address is never reused.

struct KindKey {
    PyObject* type;
    PyObject* field;
    bool operator==(const KindKey& o) const {
        return type == o.type && field == o.field;
    }
};
struct KindKeyHash {
    size_t operator()(const KindKey& k) const {
        return std::hash<const void*>()(k.type) * 31u ^
               std::hash<const void*>()(k.field);
    }
};
struct KindEntry {
    int kind = kPlain;
    int conv = kPlain;          // PYTHON: the value kind of its setter
    PyObject* setter = nullptr; // PYTHON only
};
struct KindCache {
    PyObject* kinds = nullptr;  // owned: the mapping the entries came from
    std::unordered_map<KindKey, KindEntry, KindKeyHash> map;
};

KindCache& kind_cache() {
    static auto* c = new KindCache;
    return *c;
}

void reset_kind_cache(PyObject* kinds) {
    KindCache& c = kind_cache();
    // Moved out first: a release may run Python, which must see the cache
    // already consistent.
    auto old = std::move(c.map);
    c.map.clear();
    PyObject* old_kinds = c.kinds;
    Py_INCREF(kinds);
    c.kinds = kinds;
    for (auto& kv : old) {
        Py_DECREF(kv.first.type);
        Py_DECREF(kv.first.field);
        Py_XDECREF(kv.second.setter);
    }
    Py_XDECREF(old_kinds);
}

// The kind of `field` on a `type` instance; out->setter a new reference
// (PYTHON) or nullptr. False: a Python error is set (the mapping's lookup
// raised -- _quiet_setter's TypeError for a field with no quiet write --
// or answered something that is not a kind).
bool kind_of(const Ctx& c, PyObject* type, PyObject* field, KindEntry* out) {
    KindCache& cache = kind_cache();
    auto it = cache.map.find(KindKey{type, field});
    if (it != cache.map.end()) {
        *out = it->second;
        Py_XINCREF(out->setter);
        return true;
    }
    Ref key(PyTuple_Pack(2, type, field));
    if (!key) return false;
    Ref k(PyObject_GetItem(c.kinds, key.get()));
    if (!k) return false;
    const long kind = PyLong_AsLong(k.get());
    if (kind == -1 && PyErr_Occurred()) return false;
    if (kind < kPlain || kind > kPython) {
        PyErr_Format(PyExc_ValueError,
                     "combat apply: kind %ld for %R is not PLAIN..PYTHON",
                     kind, key.get());
        return false;
    }
    KindEntry e;
    e.kind = e.conv = static_cast<int>(kind);
    if (kind == kPython) {
        Ref st(PyObject_GetItem(c.setters, key.get()));
        if (!st) return false;
        if (!PyTuple_Check(st.get()) || PyTuple_GET_SIZE(st.get()) != 2) {
            PyErr_Format(PyExc_TypeError,
                         "combat apply: python_setters[%R] is not "
                         "(setter, value kind)",
                         key.get());
            return false;
        }
        const long conv = PyLong_AsLong(PyTuple_GET_ITEM(st.get(), 1));
        if (conv == -1 && PyErr_Occurred()) return false;
        if (conv != kPlain && conv != kRef && conv != kRefs) {
            PyErr_Format(PyExc_ValueError,
                         "combat apply: value kind %ld for %R is not "
                         "PLAIN/REF/REFS",
                         conv, key.get());
            return false;
        }
        e.conv = static_cast<int>(conv);
        e.setter = PyTuple_GET_ITEM(st.get(), 0);
    }
    // Cached only against the mapping it came from (a nested session may
    // have installed another since this apply began).
    if (cache.kinds == c.kinds) {
        Py_INCREF(type);
        Py_INCREF(field);
        Py_XINCREF(e.setter);
        cache.map.emplace(KindKey{type, field}, e);
    }
    Py_XINCREF(e.setter);
    *out = e;
    return true;
}

// ── walk.obj ─────────────────────────────────────────────────────────────

// _K1Walk.obj(h) for any object `h`: None for -1; the pinned object; else
// the registry's, checked by its `_nslot`, then pinned. A new reference, or
// nullptr with the reference's RuntimeError set.
PyObject* walk_obj(const Ctx& c, PyObject* h) {
    const Names* n = names();
    if (n == nullptr) return nullptr;
    const int none = PyObject_RichCompareBool(h, n->minus_one, Py_EQ);
    if (none < 0) return nullptr;
    if (none) return Py_NewRef(Py_None);
    PyObject* o = PyDict_GetItemWithError(c.pins, h);  // self.pins.get(h)
    if (o == nullptr && PyErr_Occurred()) return nullptr;
    if (o != nullptr && o != Py_None) return Py_NewRef(o);
    Ref reg;
    if (PyDict_CheckExact(c.registry)) {
        PyObject* r = PyDict_GetItemWithError(c.registry, h);
        if (r == nullptr && PyErr_Occurred()) return nullptr;
        reg = Ref(Py_NewRef(r != nullptr ? r : Py_None));
    } else {
        reg = Ref(PyObject_CallMethodOneArg(c.registry, n->get, h));
        if (!reg) return nullptr;
    }
    bool live = reg.get() != Py_None;
    if (live) {
        Ref d(PyObject_GetAttr(reg.get(), n->dict));
        if (!d) return nullptr;
        PyObject* slot = nullptr;
        if (PyDict_Check(d.get())) {
            slot = PyDict_GetItemWithError(d.get(), n->nslot);
            if (slot == nullptr && PyErr_Occurred()) return nullptr;
            if (slot == nullptr) slot = Py_None;
        }
        Ref held;
        if (slot == nullptr) {
            held = Ref(PyObject_CallMethodObjArgs(d.get(), n->get, n->nslot,
                                                  nullptr));
            if (!held) return nullptr;
            slot = held.get();
        }
        const int ne = PyObject_RichCompareBool(slot, h, Py_NE);
        if (ne < 0) return nullptr;
        live = !ne;
    }
    if (!live) {
        Ref msg(PyUnicode_Format(n->handle_fmt, h));
        if (msg) PyErr_SetObject(PyExc_RuntimeError, msg.get());
        return nullptr;
    }
    if (PyDict_SetItem(c.pins, h, reg.get()) < 0) return nullptr;
    return reg.release();
}

PyObject* walk_obj_int(const Ctx& c, std::int64_t h) {
    if (h == -1) return Py_NewRef(Py_None);
    Ref key(PyLong_FromLongLong(h));
    if (!key) return nullptr;
    return walk_obj(c, key.get());
}

// ── Values ───────────────────────────────────────────────────────────────

template <class T, class V>
struct is_alternative;
template <class T, class... Ts>
struct is_alternative<T, std::variant<Ts...>>
    : std::bool_constant<(std::is_same_v<T, Ts> || ...)> {};

PyObject* box_scalar(const ApplyScalar& v) {
    return std::visit(
        [](const auto& x) -> PyObject* {
            using T = std::decay_t<decltype(x)>;
            if constexpr (std::is_same_v<T, std::monostate>)
                return Py_NewRef(Py_None);
            else if constexpr (std::is_same_v<T, bool>)
                return PyBool_FromLong(x ? 1 : 0);
            else if constexpr (std::is_same_v<T, std::int64_t>)
                return PyLong_FromLongLong(x);
            else
                return PyFloat_FromDouble(x);
        },
        v);
}

PyObject* int_list(const std::vector<std::int64_t>& v) {
    Ref list(PyList_New(static_cast<Py_ssize_t>(v.size())));
    if (!list) return nullptr;
    for (size_t i = 0; i < v.size(); ++i) {
        PyObject* x = PyLong_FromLongLong(v[i]);
        if (x == nullptr) return nullptr;
        PyList_SET_ITEM(list.get(), static_cast<Py_ssize_t>(i), x);
    }
    return list.release();
}

// The value as the Python-encoded log carries it.
template <class V>
PyObject* box(const V& value) {
    const Names* n = names();
    if (n == nullptr) return nullptr;
    return std::visit(
        [n](const auto& x) -> PyObject* {
            using T = std::decay_t<decltype(x)>;
            if constexpr (std::is_same_v<T, std::monostate>)
                return Py_NewRef(Py_None);
            else if constexpr (std::is_same_v<T, bool>)
                return PyBool_FromLong(x ? 1 : 0);
            else if constexpr (std::is_same_v<T, std::int64_t>)
                return PyLong_FromLongLong(x);
            else if constexpr (std::is_same_v<T, double>)
                return PyFloat_FromDouble(x);
            else if constexpr (std::is_same_v<T, cb::K1WalkOffset>)
                return Py_BuildValue("(OLL)", n->walk_offset,
                                     static_cast<long long>(x.walk),
                                     static_cast<long long>(x.system));
            else if constexpr (std::is_same_v<T, std::vector<std::int64_t>>)
                return int_list(x);
            else if constexpr (std::is_same_v<T, ApplySlot>) {
                Ref v(box_scalar(x.value));
                if (!v) return nullptr;
                return Py_BuildValue("(OLO)", n->slot,
                                     static_cast<long long>(x.index),
                                     v.get());
            } else {
                Ref v(box_scalar(x.value));
                if (!v) return nullptr;
                return Py_BuildValue("(OO)", n->watcher, v.get());
            }
        },
        value);
}

// `walk.obj(value)` (a REF field).
template <class V>
PyObject* ref_value(const Ctx& c, const V& value) {
    if (const auto* h = std::get_if<std::int64_t>(&value))
        return walk_obj_int(c, *h);
    Ref boxed(box(value));
    if (!boxed) return nullptr;
    return walk_obj(c, boxed.get());
}

// `[walk.obj(v) for v in value]` (a REF list field): a NEW list.
template <class V>
PyObject* refs_value(const Ctx& c, const V& value) {
    if (const auto* hs = std::get_if<std::vector<std::int64_t>>(&value)) {
        Ref list(PyList_New(static_cast<Py_ssize_t>(hs->size())));
        if (!list) return nullptr;
        for (size_t i = 0; i < hs->size(); ++i) {
            PyObject* o = walk_obj_int(c, (*hs)[i]);
            if (o == nullptr) return nullptr;
            PyList_SET_ITEM(list.get(), static_cast<Py_ssize_t>(i), o);
        }
        return list.release();
    }
    Ref boxed(box(value));
    if (!boxed) return nullptr;
    Ref it(PyObject_GetIter(boxed.get()));
    if (!it) return nullptr;
    Ref list(PyList_New(0));
    if (!list) return nullptr;
    while (true) {
        Ref h(PyIter_Next(it.get()));
        if (!h) {
            if (PyErr_Occurred()) return nullptr;
            break;
        }
        Ref o(walk_obj(c, h.get()));
        if (!o || PyList_Append(list.get(), o.get()) < 0) return nullptr;
    }
    return list.release();
}

PyObject* materialise(const Ctx& c, const cb::K1WalkOffset& m) {
    const Names* n = names();
    if (n == nullptr) return nullptr;
    Ref walk(PyLong_FromLongLong(m.walk));
    Ref sys(PyLong_FromLongLong(m.system));
    if (!walk || !sys) return nullptr;
    return PyObject_CallMethodObjArgs(c.walk, n->materialise, walk.get(),
                                      sys.get(), nullptr);
}

// obj.__dict__[field] = value; `dict_out` (when given) keeps the dict.
bool store(PyObject* obj, PyObject* field, PyObject* value,
           Ref* dict_out = nullptr) {
    Ref d(PyObject_GetAttr(obj, names()->dict));
    if (!d || PyObject_SetItem(d.get(), field, value) < 0) return false;
    if (dict_out != nullptr) *dict_out = Ref(d.release());
    return true;
}

bool apply_slot(PyObject* obj, PyObject* field, const ApplySlot& s) {
    Ref d(PyObject_GetAttr(obj, names()->dict));
    if (!d) return false;
    Ref list(PyObject_GetItem(d.get(), field));
    if (!list) return false;
    Ref index(PyLong_FromLongLong(s.index));
    Ref value(box_scalar(s.value));
    if (!index || !value) return false;
    return PyObject_SetItem(list.get(), index.get(), value.get()) == 0;
}

bool apply_watcher(PyObject* obj, PyObject* field, const ApplyWatcher& w) {
    const Names* n = names();
    Ref d(PyObject_GetAttr(obj, n->dict));
    if (!d) return false;
    Ref watcher(PyObject_GetItem(d.get(), field));
    if (!watcher) return false;
    Ref wd(PyObject_GetAttr(watcher.get(), n->dict));
    Ref value(box_scalar(w.value));
    if (!wd || !value) return false;
    return PyObject_SetItem(wd.get(), n->value, value.get()) == 0;
}

// ── One write: _apply_write ──────────────────────────────────────────────

template <class V>
bool apply_one(const Ctx& c, std::int64_t handle, const std::string& name,
               const V& value) {
    const Names* n = names();
    if (n == nullptr) return false;
    PyObject* field = intern_field(name);
    if (field == nullptr) return false;
    Ref obj(walk_obj_int(c, handle));               // obj = walk.obj(h)
    if (!obj) return false;
    if constexpr (is_alternative<ApplySlot, V>::value) {
        if (const auto* s = std::get_if<ApplySlot>(&value))
            return apply_slot(obj.get(), field, *s);
        if (const auto* w = std::get_if<ApplyWatcher>(&value))
            return apply_watcher(obj.get(), field, *w);
    }
    KindEntry k;                                    // _quiet_setter(...)
    if (!kind_of(c, reinterpret_cast<PyObject*>(Py_TYPE(obj.get())), field,
                 &k))
        return false;
    Ref setter(k.setter);
    const int conv = k.kind == kPython ? k.conv : k.kind;
    Ref v;
    if (conv == kRef) {
        v = Ref(ref_value(c, value));
    } else if (conv == kRefs) {
        v = Ref(refs_value(c, value));
    } else if (const auto* m = std::get_if<cb::K1WalkOffset>(&value)) {
        v = Ref(materialise(c, *m));                // ("walk_offset", n, h)
    } else {
        v = Ref(box(value));
    }
    if (!v) return false;
    if (k.kind == kPython) {
        Ref r(PyObject_CallFunctionObjArgs(setter.get(), obj.get(), v.get(),
                                           nullptr));
        return static_cast<bool>(r);
    }
    Ref d;
    if (!store(obj.get(), field, v.get(), &d)) return false;
    if (k.kind != kWake) return true;
    // WakeField.__set__: `if obj.__dict__.get("_passive_asleep", False):
    // wake(obj)`.
    PyObject* asleep = Py_False;
    Ref held;
    if (PyDict_Check(d.get())) {
        PyObject* a = PyDict_GetItemWithError(d.get(), n->asleep);
        if (a == nullptr && PyErr_Occurred()) return false;
        if (a != nullptr) asleep = a;
    } else {
        held = Ref(PyObject_CallMethodObjArgs(d.get(), n->get, n->asleep,
                                              Py_False, nullptr));
        if (!held) return false;
        asleep = held.get();
    }
    const int truth = PyObject_IsTrue(asleep);
    if (truth < 0) return false;
    if (truth) {
        Ref r(PyObject_CallOneArg(c.wake, obj.get()));
        if (!r) return false;
    }
    return true;
}

// ── The handled exception ────────────────────────────────────────────────
// Inside apply_writes' `except BaseException as e:` (and _apply_rest's
// `except Exception as e2:`) the caught exception is the one being handled:
// a raise there gets it as __context__. HandledAs makes `e` the handled
// exception of the current exception-state item for its scope, exactly what
// the bytecode's PUSH_EXC_INFO / POP_EXCEPT do.
class HandledAs {
public:
    explicit HandledAs(PyObject* e) : item_(PyThreadState_Get()->exc_info) {
        saved_ = item_->exc_value;
        item_->exc_value = Py_NewRef(e);
    }
    HandledAs(const HandledAs&) = delete;
    HandledAs& operator=(const HandledAs&) = delete;
    ~HandledAs() {
        PyObject* cur = item_->exc_value;
        item_->exc_value = saved_;
        Py_XDECREF(cur);
    }

private:
    _PyErr_StackItem* item_;
    PyObject* saved_;
};

// The raised exception, normalised, its traceback attached: (type, value,
// traceback), all owned.
struct Raised {
    PyObject* type = nullptr;
    PyObject* value = nullptr;
    PyObject* tb = nullptr;
    Raised() {
        PyErr_Fetch(&type, &value, &tb);
        PyErr_NormalizeException(&type, &value, &tb);
        if (tb != nullptr && value != nullptr)
            PyException_SetTraceback(value, tb);
    }
    Raised(const Raised&) = delete;
    Raised& operator=(const Raised&) = delete;
    ~Raised() {
        Py_XDECREF(type);
        Py_XDECREF(value);
        Py_XDECREF(tb);
    }
    void restore() {
        PyErr_Restore(type, value, tb);
        type = value = tb = nullptr;
    }
};

// _apply_rest(writes[from:to], walk, failed, exc).
template <class W>
bool apply_rest(const Ctx& c, const std::vector<W>& w, size_t from,
                size_t to, std::vector<std::int64_t>& failed, PyObject* exc,
                std::uint64_t* applied) {
    const Names* n = names();
    for (size_t j = from; j < to; ++j) {
        if (const auto* m = std::get_if<cb::K1WalkOffset>(&w[j].value)) {
            Ref walk_n(PyLong_FromLongLong(m->walk));
            if (!walk_n) return false;
            Ref cur(PyObject_GetAttr(c.walk, n->walk));
            if (!cur) return false;
            const int ne =
                PyObject_RichCompareBool(cur.get(), walk_n.get(), Py_NE);
            if (ne < 0) return false;
            if (ne) {
                if (std::find(failed.begin(), failed.end(), m->walk) !=
                    failed.end())
                    continue;
                Ref offset(materialise(c, *m));
                if (!offset) {
                    if (!PyErr_ExceptionMatches(PyExc_Exception))
                        return false;
                    Raised e2;
                    failed.push_back(m->walk);
                    HandledAs handling(e2.value);
                    Ref args(PyTuple_Pack(2, walk_n.get(), e2.value));
                    if (!args) return false;
                    Ref note(PyUnicode_Format(n->note_fmt, args.get()));
                    if (!note) return false;
                    Ref r(PyObject_CallMethodOneArg(exc, n->add_note,
                                                    note.get()));
                    if (!r) return false;
                    continue;
                }
            }
        }
        if (!apply_one(c, w[j].handle, w[j].field, w[j].value)) return false;
        ++*applied;
    }
    return true;
}

// apply_writes(writes[from:to], walk).
template <class W>
bool apply_log(const Ctx& c, const std::vector<W>& w, size_t from, size_t to,
               std::uint64_t* applied) {
    for (size_t i = from; i < to; ++i) {
        if (apply_one(c, w[i].handle, w[i].field, w[i].value)) {
            ++*applied;
            continue;
        }
        if (!PyErr_Occurred())
            PyErr_SetString(PyExc_SystemError,
                            "combat apply: a write failed with no error");
        Raised e;
        std::vector<std::int64_t> failed;
        if (const auto* m = std::get_if<cb::K1WalkOffset>(&w[i].value))
            failed.push_back(m->walk);
        bool ok;
        {
            HandledAs handling(e.value);
            ok = apply_rest(c, w, i + 1, to, failed, e.value, applied);
        }
        if (ok) e.restore();  // re-raise the first; else the rest's own
        return false;
    }
    return true;
}

// ── The Python encoding (combat_apply_log) ───────────────────────────────

bool parse_scalar(PyObject* o, ApplyScalar* out) {
    if (o == Py_None) {
        *out = std::monostate{};
    } else if (PyBool_Check(o)) {
        *out = o == Py_True;
    } else if (PyLong_Check(o)) {
        const long long v = PyLong_AsLongLong(o);
        if (v == -1 && PyErr_Occurred()) return false;
        *out = static_cast<std::int64_t>(v);
    } else if (PyFloat_Check(o)) {
        *out = PyFloat_AS_DOUBLE(o);
    } else {
        PyErr_Format(PyExc_TypeError,
                     "combat_apply_log: cannot encode the value %R", o);
        return false;
    }
    return true;
}

bool parse_int(PyObject* o, std::int64_t* out) {
    if (!PyLong_Check(o) || PyBool_Check(o)) {
        PyErr_Format(PyExc_TypeError, "combat_apply_log: %R is not an int",
                     o);
        return false;
    }
    const long long v = PyLong_AsLongLong(o);
    if (v == -1 && PyErr_Occurred()) return false;
    *out = static_cast<std::int64_t>(v);
    return true;
}

bool tagged(PyObject* t, const char* tag, Py_ssize_t size) {
    if (PyTuple_GET_SIZE(t) != size) return false;
    PyObject* first = PyTuple_GET_ITEM(t, 0);
    return PyUnicode_Check(first) &&
           PyUnicode_CompareWithASCIIString(first, tag) == 0;
}

bool parse_value(PyObject* o, ApplyValue* out) {
    if (PyList_Check(o)) {
        std::vector<std::int64_t> hs;
        for (Py_ssize_t i = 0; i < PyList_GET_SIZE(o); ++i) {
            std::int64_t h;
            if (!parse_int(PyList_GET_ITEM(o, i), &h)) return false;
            hs.push_back(h);
        }
        *out = std::move(hs);
        return true;
    }
    if (PyTuple_Check(o)) {
        if (tagged(o, "walk_offset", 3)) {
            cb::K1WalkOffset m;
            if (!parse_int(PyTuple_GET_ITEM(o, 1), &m.walk) ||
                !parse_int(PyTuple_GET_ITEM(o, 2), &m.system))
                return false;
            *out = m;
            return true;
        }
        if (tagged(o, "slot", 3)) {
            ApplySlot s;
            if (!parse_int(PyTuple_GET_ITEM(o, 1), &s.index) ||
                !parse_scalar(PyTuple_GET_ITEM(o, 2), &s.value))
                return false;
            *out = s;
            return true;
        }
        if (tagged(o, "watcher", 2)) {
            ApplyWatcher w;
            if (!parse_scalar(PyTuple_GET_ITEM(o, 1), &w.value)) return false;
            *out = w;
            return true;
        }
        PyErr_Format(PyExc_TypeError,
                     "combat_apply_log: unknown tagged value %R", o);
        return false;
    }
    ApplyScalar s;
    if (!parse_scalar(o, &s)) return false;
    std::visit([out](const auto& x) { *out = x; }, s);
    return true;
}

}  // namespace

// ── WriteApplier ─────────────────────────────────────────────────────────

PyObject* WriteApplier::set_context(PyObject* ctx) {
    PyObject* next = nullptr;
    if (ctx != Py_None) {
        if (!PyTuple_Check(ctx) || PyTuple_GET_SIZE(ctx) != 6) {
            PyErr_SetString(PyExc_TypeError,
                            "combat_set_applier: (pins, registry, walk, "
                            "kinds, wake, python_setters) or None");
            return nullptr;
        }
        if (!PyDict_CheckExact(PyTuple_GET_ITEM(ctx, 0))) {
            PyErr_SetString(PyExc_TypeError,
                            "combat_set_applier: pins must be a dict");
            return nullptr;
        }
        if (!PyCallable_Check(PyTuple_GET_ITEM(ctx, 4))) {
            PyErr_SetString(PyExc_TypeError,
                            "combat_set_applier: wake must be callable");
            return nullptr;
        }
        if (names() == nullptr) return nullptr;
        next = Py_NewRef(ctx);
        PyObject* kinds = PyTuple_GET_ITEM(ctx, 3);
        if (kind_cache().kinds != kinds) reset_kind_cache(kinds);
    }
    PyObject* prev = ctx_;
    ctx_ = next;
    return prev != nullptr ? prev : Py_NewRef(Py_None);
}

template <class W>
bool WriteApplier::apply_range(const std::vector<W>& w, size_t from,
                               size_t to) {
    if (ctx_ == nullptr) {
        PyErr_SetString(PyExc_RuntimeError,
                        "combat apply: no applier context "
                        "(combat_set_applier)");
        return false;
    }
    to = std::min(to, w.size());
    if (from >= to) return true;
    // Held for the apply: Python run inside may install another context.
    Ref ctx(Py_NewRef(ctx_));
    return apply_log(unpack(ctx.get()), w, from, to, &applied_);
}

bool WriteApplier::apply(const std::vector<cb::K1Write>& w, size_t from,
                         size_t to) {
    return apply_range(w, from, to);
}

bool WriteApplier::apply(const std::vector<cb::K2Write>& w, size_t from,
                         size_t to) {
    return apply_range(w, from, to);
}

bool WriteApplier::apply(const std::vector<ApplyWrite>& w, size_t from,
                         size_t to) {
    return apply_range(w, from, to);
}

bool WriteApplier::parse_log(PyObject* log, std::vector<ApplyWrite>* out) {
    Ref seq(PySequence_Fast(log, "combat_apply_log: a list of writes"));
    if (!seq) return false;
    const Py_ssize_t n = PySequence_Fast_GET_SIZE(seq.get());
    out->clear();
    out->reserve(static_cast<size_t>(n));
    for (Py_ssize_t i = 0; i < n; ++i) {
        PyObject* item = PySequence_Fast_GET_ITEM(seq.get(), i);
        if (!PyTuple_Check(item) || PyTuple_GET_SIZE(item) != 3) {
            PyErr_Format(PyExc_TypeError,
                         "combat_apply_log: %R is not (handle, field, "
                         "value)",
                         item);
            return false;
        }
        ApplyWrite w;
        PyObject* field = PyTuple_GET_ITEM(item, 1);
        if (!parse_int(PyTuple_GET_ITEM(item, 0), &w.handle)) return false;
        if (!PyUnicode_Check(field)) {
            PyErr_Format(PyExc_TypeError,
                         "combat_apply_log: field %R is not a str", field);
            return false;
        }
        Py_ssize_t len = 0;
        const char* s = PyUnicode_AsUTF8AndSize(field, &len);
        if (s == nullptr) return false;
        w.field.assign(s, static_cast<size_t>(len));
        if (!parse_value(PyTuple_GET_ITEM(item, 2), &w.value)) return false;
        out->push_back(std::move(w));
    }
    return true;
}

}  // namespace dauntless::host
