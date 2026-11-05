// native/src/host/combat_write_apply.cc -- see combat_write_apply.h.
//
// Every step mirrors a line of engine/appc/native_combat.py (`walk.obj`,
// `_apply_write`, `apply_writes`, `_apply_rest`), in the same order, so the
// same Python runs and the same exception comes out of the same place.

#include "combat_write_apply.h"

#include <algorithm>
#include <cstring>
#include <string_view>
#include <type_traits>
#include <unordered_map>
#include <unordered_set>
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

// The applier runs once per logged write: its small helpers are forced
// inline, as the K0 scan's are (a Debug, -O0 build otherwise pays a call for
// each, every write).
#if defined(__clang__) || defined(__GNUC__)
#define APPLY_INLINE inline __attribute__((always_inline))
#else
#define APPLY_INLINE inline
#endif

// An owned reference, released at scope exit.
class Ref {
public:
    APPLY_INLINE explicit Ref(PyObject* p = nullptr) : p_(p) {}
    Ref(const Ref&) = delete;
    Ref& operator=(const Ref&) = delete;
    APPLY_INLINE Ref& operator=(Ref&& o) noexcept {
        if (this != &o) {
            Py_XDECREF(p_);
            p_ = o.release();
        }
        return *this;
    }
    APPLY_INLINE ~Ref() { Py_XDECREF(p_); }
    APPLY_INLINE PyObject* get() const { return p_; }
    APPLY_INLINE explicit operator bool() const { return p_ != nullptr; }
    APPLY_INLINE PyObject* release() {
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
    PyObject* data;
    PyObject* minus_one;
    PyObject* handle_fmt;
    PyObject* note_fmt;
};

Names* g_names = nullptr;
const Names* make_names();

APPLY_INLINE const Names* names() {
    return g_names != nullptr ? g_names : make_names();
}

const Names* make_names() {
    Names*& n = g_names;
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
    t->data = PyUnicode_InternFromString("data");
    t->minus_one = PyLong_FromLong(-1);
    // native_combat._K1Walk.obj's and _apply_rest's messages, verbatim.
    t->handle_fmt = PyUnicode_FromString(
        "combat K1: handle %#x names no pinned or live object");
    t->note_fmt =
        PyUnicode_FromString("combat K1: walk %d's offset also raised %r");
    for (PyObject* o : {t->dict, t->get, t->materialise, t->walk, t->nslot,
                        t->asleep, t->value, t->add_note, t->walk_offset,
                        t->slot, t->watcher, t->data, t->minus_one,
                        t->handle_fmt, t->note_fmt}) {
        if (o == nullptr) return nullptr;  // error set; retried next call
    }
    n = t;
    return n;
}

// A field name as an interned str (owned by the table, never released).
// Names are views of static or pooled storage (write_log.h), so the answer
// is cached by the view's address in a direct-mapped table in front of the
// by-name table; a hit is confirmed by length and content (an address can
// only be reused by a name that is not static -- never in the kernels --
// and then the content check sends it to the by-name table).
PyObject* intern_field(std::string_view s) {
    struct Slot {
        const char* p = nullptr;
        size_t n = 0;
        PyObject* o = nullptr;
    };
    static Slot by_addr[128];
    Slot& e = by_addr[(reinterpret_cast<std::uintptr_t>(s.data()) >> 3) & 127u];
    if (e.o != nullptr && e.p == s.data() && e.n == s.size() &&
        std::memcmp(PyUnicode_AsUTF8(e.o), s.data(), s.size()) == 0)
        return e.o;
    static auto* table = new std::unordered_map<std::string, PyObject*>;
    std::string key(s);
    auto it = table->find(key);
    PyObject* o;
    if (it != table->end()) {
        o = it->second;
    } else {
        o = PyUnicode_InternFromString(key.c_str());
        if (o == nullptr) return nullptr;
        table->emplace(std::move(key), o);
    }
    e = Slot{s.data(), s.size(), o};
    return o;
}

// A parsed Python log's field name, as a view of the never-freed pool (one
// copy per distinct name).
std::string_view pooled_name(const char* s, size_t n) {
    static auto* pool = new std::unordered_set<std::string>;
    return *pool->emplace(s, n).first;
}

// A K0 write's attribute: its Field's name, or the watcher's.
PyObject* k0_field(const cb::K0FieldWrite& w) {
    constexpr size_t kWatcher = static_cast<size_t>(cb::Field::kCount);
    static PyObject* table[kWatcher + 1] = {};
    const bool watcher = w.type == cb::K0FieldWrite::Type::Watcher;
    const size_t i = watcher ? kWatcher : static_cast<size_t>(w.field);
    // A non-watcher write's id must name a Field: kWatcher is the watcher's
    // slot, never a field's.
    if (!watcher && i >= kWatcher) {
        PyErr_SetString(PyExc_SystemError, "combat apply: K0 write field");
        return nullptr;
    }
    PyObject*& o = table[i];
    if (o == nullptr)
        o = PyUnicode_InternFromString(i == kWatcher ? "_charge_watcher"
                                                     : cb::field_name(w.field));
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
    // A direct-mapped table in front of `map` for the kinds with no setter
    // (PLAIN .. WAKE): an entry is valid while its epoch is the cache's
    // (every reset bumps it). Keys borrowed: `map` owns them.
    struct Front {
        PyObject* type = nullptr;
        PyObject* field = nullptr;
        std::uint64_t epoch = 0;
        int kind = kPlain;
    };
    Front front[256];
    std::uint64_t epoch = 1;
};

std::size_t front_slot(PyObject* type, PyObject* field) {
    const std::uint64_t h =
        (static_cast<std::uint64_t>(reinterpret_cast<std::uintptr_t>(type)) ^
         (static_cast<std::uint64_t>(reinterpret_cast<std::uintptr_t>(field))
          << 1)) *
        0x9E3779B97F4A7C15ull;
    return static_cast<std::size_t>(h >> 56);
}

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
    ++c.epoch;  // every front entry stale
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
    KindCache::Front& f = cache.front[front_slot(type, field)];
    if (f.epoch == cache.epoch && f.type == type && f.field == field &&
        cache.kinds == c.kinds) {
        out->kind = out->conv = f.kind;
        out->setter = nullptr;
        return true;
    }
    auto it = cache.map.find(KindKey{type, field});
    if (it != cache.map.end()) {
        *out = it->second;
        Py_XINCREF(out->setter);
        if (it->second.kind != kPython && cache.kinds == c.kinds)
            f = KindCache::Front{type, field, cache.epoch, it->second.kind};
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

// weakref.WeakValueDictionary (borrowed from the module, kept alive by it);
// nullptr when it cannot be found (every registry then takes `.get`).
PyTypeObject* weak_value_dict_type() {
    static PyTypeObject* t = [] {
        PyObject* mod = PyImport_ImportModule("weakref");
        PyObject* type =
            mod != nullptr ? PyObject_GetAttrString(mod, "WeakValueDictionary")
                           : nullptr;
        Py_XDECREF(mod);
        if (type == nullptr || !PyType_Check(type)) {
            PyErr_Clear();
            Py_XDECREF(type);
            return static_cast<PyTypeObject*>(nullptr);
        }
        return reinterpret_cast<PyTypeObject*>(type);  // kept: never freed
    }();
    return t;
}

// `registry.get(h)` (a new reference; nullptr with an error set). For an
// exact WeakValueDictionary, its own lines in C -- `wr = self.data[h]`
// (KeyError -> None), `o = wr()` (a dead KeyedRef -> None) -- with no
// Python call. One difference no caller can see: `.get` first commits the
// removals deferred while the dict is being iterated (dead refs whose keys
// it drops); the C read finds those keys too and answers None for them,
// as `.get` would. Anything else -- a plain dict, a subclass, a `data`
// that is not a dict or an entry that is not a weakref -- is asked as the
// reference asks it.
PyObject* registry_get(PyObject* registry, PyObject* h) {
    const Names* n = names();
    if (PyDict_CheckExact(registry)) {
        PyObject* r = PyDict_GetItemWithError(registry, h);
        if (r == nullptr && PyErr_Occurred()) return nullptr;
        return Py_NewRef(r != nullptr ? r : Py_None);
    }
    PyTypeObject* wvd = weak_value_dict_type();
    if (wvd != nullptr && Py_TYPE(registry) == wvd) {
        PyObject* data = PyObject_GetAttr(registry, n->data);  // self.data
        if (data == nullptr) return nullptr;
        if (PyDict_CheckExact(data)) {
            PyObject* wr = PyDict_GetItemWithError(data, h);
            if (wr == nullptr) {
                Py_DECREF(data);
                if (PyErr_Occurred()) return nullptr;
                return Py_NewRef(Py_None);
            }
            if (PyWeakref_CheckRef(wr)) {
                // Borrowed; Py_None when the referent is gone.
                PyObject* o = PyWeakref_GetObject(wr);
                Py_INCREF(o);
                Py_DECREF(data);
                return o;
            }
        }
        Py_DECREF(data);
    }
    return PyObject_CallMethodOneArg(registry, n->get, h);
}

// _K1Walk.live(h) for any object `h`: None for -1 (`*minus_one` set); the
// pinned object; else the registry's, checked by its `_nslot`, then pinned;
// else None (a row freed since). A new reference, or nullptr with an error
// set.
PyObject* walk_live(const Ctx& c, PyObject* h, bool* minus_one) {
    const Names* n = names();
    if (n == nullptr) return nullptr;
    const int none = PyObject_RichCompareBool(h, n->minus_one, Py_EQ);
    if (none < 0) return nullptr;
    *minus_one = none != 0;
    if (none) return Py_NewRef(Py_None);
    PyObject* o = PyDict_GetItemWithError(c.pins, h);  // self.pins.get(h)
    if (o == nullptr && PyErr_Occurred()) return nullptr;
    if (o != nullptr && o != Py_None) return Py_NewRef(o);
    Ref reg(registry_get(c.registry, h));
    if (!reg) return nullptr;
    bool live = reg.get() != Py_None;
    if (live) {
        Ref d(PyObject_GetAttr(reg.get(), n->dict));
        if (!d) return nullptr;
        // Owned: the compare can run Python that mutates the dict.
        Ref slot;
        if (PyDict_Check(d.get())) {
            PyObject* s = PyDict_GetItemWithError(d.get(), n->nslot);
            if (s == nullptr && PyErr_Occurred()) return nullptr;
            slot = Ref(Py_NewRef(s != nullptr ? s : Py_None));
        } else {
            slot = Ref(PyObject_CallMethodObjArgs(d.get(), n->get, n->nslot,
                                                  nullptr));
            if (!slot) return nullptr;
        }
        const int ne = PyObject_RichCompareBool(slot.get(), h, Py_NE);
        if (ne < 0) return nullptr;
        live = !ne;
    }
    if (!live) return Py_NewRef(Py_None);
    if (PyDict_SetItem(c.pins, h, reg.get()) < 0) return nullptr;
    return reg.release();
}

// _K1Walk.obj(h): walk.live(h), but a handle (other than -1) naming no
// pinned or live object raises the reference's RuntimeError. A new
// reference, or nullptr with an error set.
PyObject* walk_obj(const Ctx& c, PyObject* h) {
    bool minus_one = false;
    PyObject* o = walk_live(c, h, &minus_one);
    if (o != Py_None || minus_one) return o;
    Py_DECREF(o);
    Ref msg(PyUnicode_Format(names()->handle_fmt, h));
    if (msg) PyErr_SetObject(PyExc_RuntimeError, msg.get());
    return nullptr;
}

PyObject* walk_obj_int(const Ctx& c, std::int64_t h) {
    if (h == -1) return Py_NewRef(Py_None);
    Ref key(PyLong_FromLongLong(h));
    if (!key) return nullptr;
    return walk_obj(c, key.get());
}

// One log's last handle: consecutive writes on the same handle (a weapon's
// several fields) share one int key, and -- where the pins dict's PEP 509
// version proves it unchanged since (CPython 3.11, as the K0 scan's object
// cache) -- the object walk.obj found: `pins.get(h)` is then that object
// still (pins holds it, so it is alive), exactly what walk.obj answers.
#if PY_VERSION_HEX >= 0x030B0000 && PY_VERSION_HEX < 0x030C0000
constexpr bool kPinsVersion = true;
APPLY_INLINE std::uint64_t pins_version(PyObject* pins) {
    return reinterpret_cast<PyDictObject*>(pins)->ma_version_tag;
}
#else
constexpr bool kPinsVersion = false;
APPLY_INLINE std::uint64_t pins_version(PyObject*) { return 0; }
#endif

struct KeyCache {
    std::int64_t h = -1;
    PyObject* key = nullptr;  // owned
    PyObject* obj = nullptr;  // borrowed from pins (valid at `version`)
    std::uint64_t version = 0;
    KeyCache() = default;
    KeyCache(const KeyCache&) = delete;
    KeyCache& operator=(const KeyCache&) = delete;
    ~KeyCache() { Py_XDECREF(key); }
};

PyObject* walk_obj_keyed(const Ctx& c, std::int64_t h, KeyCache& kc) {
    if (h == -1) return Py_NewRef(Py_None);
    if (kc.key != nullptr && kc.h == h) {
        if (kPinsVersion && kc.obj != nullptr &&
            pins_version(c.pins) == kc.version)
            return Py_NewRef(kc.obj);
    } else {
        PyObject* key = PyLong_FromLongLong(h);
        if (key == nullptr) return nullptr;
        Py_XSETREF(kc.key, key);
        kc.h = h;
    }
    kc.obj = nullptr;
    PyObject* o = walk_obj(c, kc.key);
    // Pinned now (walk.obj pins every object it answers): reusable while
    // the pins dict stays as it is.
    if (o != nullptr && o != Py_None) {
        kc.obj = o;
        kc.version = pins_version(c.pins);
    }
    return o;
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

// obj.__dict__[field][index] = value (steals `value`; nullptr: an error is
// set).
bool slot_store(PyObject* obj, PyObject* field, std::int64_t index,
                PyObject* value) {
    Ref v(value);
    if (!v) return false;
    Ref d(PyObject_GetAttr(obj, names()->dict));
    if (!d) return false;
    Ref list(PyObject_GetItem(d.get(), field));
    if (!list) return false;
    if (PyList_CheckExact(list.get()) && index >= 0 &&
        index < PyList_GET_SIZE(list.get()))
        // list.__setitem__ itself, without boxing the index.
        return PyList_SetItem(list.get(), static_cast<Py_ssize_t>(index),
                              v.release()) == 0;
    Ref i(PyLong_FromLongLong(index));
    if (!i) return false;
    return PyObject_SetItem(list.get(), i.get(), v.get()) == 0;
}

// obj.__dict__[field].__dict__["_value"] = value (steals `value`).
bool watcher_store(PyObject* obj, PyObject* field, PyObject* value) {
    const Names* n = names();
    Ref v(value);
    if (!v) return false;
    Ref d(PyObject_GetAttr(obj, n->dict));
    if (!d) return false;
    Ref watcher(PyObject_GetItem(d.get(), field));
    if (!watcher) return false;
    Ref wd(PyObject_GetAttr(watcher.get(), n->dict));
    if (!wd) return false;
    return PyObject_SetItem(wd.get(), n->value, v.get()) == 0;
}

bool apply_slot(PyObject* obj, PyObject* field, const ApplySlot& s) {
    return slot_store(obj, field, s.index, box_scalar(s.value));
}

bool apply_watcher(PyObject* obj, PyObject* field, const ApplyWatcher& w) {
    return watcher_store(obj, field, box_scalar(w.value));
}

// The PLAIN / WAKE store: obj.__dict__[field] = v, then (WAKE)
// WakeField.__set__'s `if obj.__dict__.get("_passive_asleep", False):
// wake(obj)`.
bool store_and_wake(const Ctx& c, PyObject* obj, PyObject* field,
                    PyObject* v, bool wake) {
    const Names* n = names();
    Ref d;
    if (!store(obj, field, v, &d)) return false;
    if (!wake) return true;
    // Owned: the truth test can run Python that mutates the dict.
    Ref asleep;
    if (PyDict_Check(d.get())) {
        PyObject* a = PyDict_GetItemWithError(d.get(), n->asleep);
        if (a == nullptr && PyErr_Occurred()) return false;
        asleep = Ref(Py_NewRef(a != nullptr ? a : Py_False));
    } else {
        asleep = Ref(PyObject_CallMethodObjArgs(d.get(), n->get, n->asleep,
                                                Py_False, nullptr));
        if (!asleep) return false;
    }
    const int truth = PyObject_IsTrue(asleep.get());
    if (truth < 0) return false;
    if (truth) {
        Ref r(PyObject_CallOneArg(c.wake, obj));
        if (!r) return false;
    }
    return true;
}

// ── One write: _apply_write ──────────────────────────────────────────────

// `value` stored on `obj` by the kind `k` (kind_of's answer for its type
// and `field`, asked once: its setter reference is taken over).
template <class V>
bool apply_value_as(const Ctx& c, PyObject* obj, PyObject* field,
                    const V& value, const KindEntry& k) {
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
        Ref r(PyObject_CallFunctionObjArgs(setter.get(), obj, v.get(),
                                           nullptr));
        return static_cast<bool>(r);
    }
    return store_and_wake(c, obj, field, v.get(), k.kind == kWake);
}

// `value` stored on `obj` (walk.obj(h), resolved) as _apply_write does.
template <class V>
bool apply_value(const Ctx& c, PyObject* obj, PyObject* field,
                 const V& value) {
    // K1's log carries slot writes (a tube's launch), K0's both.
    if constexpr (is_alternative<ApplySlot, V>::value) {
        if (const auto* s = std::get_if<ApplySlot>(&value))
            return apply_slot(obj, field, *s);
    }
    if constexpr (is_alternative<ApplyWatcher, V>::value) {
        if (const auto* w = std::get_if<ApplyWatcher>(&value))
            return apply_watcher(obj, field, *w);
    }
    KindEntry k;                                    // _quiet_setter(...)
    if (!kind_of(c, reinterpret_cast<PyObject*>(Py_TYPE(obj)), field, &k))
        return false;
    return apply_value_as(c, obj, field, value, k);
}

template <class V>
bool apply_one(const Ctx& c, std::int64_t handle, std::string_view name,
               const V& value, KeyCache& kc) {
    if (names() == nullptr) return false;
    PyObject* field = intern_field(name);
    if (field == nullptr) return false;
    Ref obj(walk_obj_keyed(c, handle, kc));         // obj = walk.obj(h)
    if (!obj) return false;
    return apply_value(c, obj.get(), field, value);
}

// A K0 write as the encoded value it stands for (the general path).
ApplyValue k0_value(const cb::K0FieldWrite& w) {
    switch (w.type) {
        case cb::K0FieldWrite::Type::Float: return w.d;
        case cb::K0FieldWrite::Type::Flag: return w.i != 0;
        case cb::K0FieldWrite::Type::Int: return static_cast<std::int64_t>(w.i);
        case cb::K0FieldWrite::Type::Slot:
            return ApplySlot{w.index, ApplyScalar{w.d}};
        case cb::K0FieldWrite::Type::Watcher:
            return ApplyWatcher{ApplyScalar{w.d}};
        case cb::K0FieldWrite::Type::Ref:   // a handle, -1 None (REF kind)
            return static_cast<std::int64_t>(w.i);
        case cb::K0FieldWrite::Type::Null:
            return std::monostate{};
    }
    return std::monostate{};
}

// One K0 write: the same as apply_one on k0_value(w), without building the
// variant for the kinds a K0 write meets (a PLAIN or WAKE scalar field, a
// slot, the watcher); any other kind (a test's Python setter), and a stop's
// Ref / Null write, takes the general path.
bool apply_k0(const Ctx& c, const cb::K0Write& kw, KeyCache& kc) {
    const cb::K0FieldWrite& w = kw.w;
    if (names() == nullptr) return false;
    PyObject* field = k0_field(w);
    if (field == nullptr) return false;
    PyObject* obj = walk_obj_keyed(c, kw.handle, kc);  // obj = walk.obj(h)
    if (obj == nullptr) return false;
    bool ok;
    switch (w.type) {
        case cb::K0FieldWrite::Type::Slot:
            ok = slot_store(obj, field, w.index, PyFloat_FromDouble(w.d));
            break;
        case cb::K0FieldWrite::Type::Watcher:
            ok = watcher_store(obj, field, PyFloat_FromDouble(w.d));
            break;
        default: {
            KindEntry k;
            ok = kind_of(c, reinterpret_cast<PyObject*>(Py_TYPE(obj)), field,
                         &k);
            if (!ok) break;
            if ((k.kind != kPlain && k.kind != kWake) ||
                w.type == cb::K0FieldWrite::Type::Ref ||
                w.type == cb::K0FieldWrite::Type::Null) {
                // The general path with the kind already asked (once, as
                // _apply_write asks _quiet_setter once).
                ok = apply_value_as(c, obj, field, k0_value(w), k);
                break;
            }
            PyObject* v =
                w.type == cb::K0FieldWrite::Type::Float ? PyFloat_FromDouble(w.d)
                : w.type == cb::K0FieldWrite::Type::Flag
                    ? PyBool_FromLong(w.i != 0 ? 1 : 0)
                    : PyLong_FromLongLong(w.i);
            ok = v != nullptr &&
                 store_and_wake(c, obj, field, v, k.kind == kWake);
            Py_XDECREF(v);
            break;
        }
    }
    Py_DECREF(obj);
    return ok;
}

// A write's walk-offset marker, if it is one (K0 logs none).
template <class W>
const cb::K1WalkOffset* marker_of(const W& w) {
    return std::get_if<cb::K1WalkOffset>(&w.value);
}
const cb::K1WalkOffset* marker_of(const cb::K0Write&) { return nullptr; }

template <class W>
bool apply_write(const Ctx& c, const W& w, KeyCache& kc) {
    return apply_one(c, w.handle, w.field, w.value, kc);
}
bool apply_write(const Ctx& c, const cb::K0Write& w, KeyCache& kc) {
    return apply_k0(c, w, kc);
}

// ── The handled exception ────────────────────────────────────────────────
// Inside apply_writes' `except BaseException as e:` (and _apply_rest's
// `except Exception as e2:`) the caught exception is the one being handled:
// a raise there gets it as __context__. HandledAs makes `e` the handled
// exception for its scope, as the bytecode's PUSH_EXC_INFO / POP_EXCEPT do,
// through the public 3.11 API (PyErr_Get/SetHandledException). One
// difference from swapping the item's own field: the getter answers the
// TOPMOST handled exception, so when the apply runs inside a generator or
// coroutine whose own item held none while its caller was handling one,
// the restore leaves the caller's exception in the generator's item; it
// shows only if that generator later yields and resumes outside the
// caller's except block.
class HandledAs {
public:
    explicit HandledAs(PyObject* e) : saved_(PyErr_GetHandledException()) {
        PyErr_SetHandledException(e);
    }
    HandledAs(const HandledAs&) = delete;
    HandledAs& operator=(const HandledAs&) = delete;
    ~HandledAs() {
        PyErr_SetHandledException(saved_);
        Py_XDECREF(saved_);
    }

private:
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
bool apply_rest(const Ctx& c, const W* w, size_t from, size_t to,
                std::vector<std::int64_t>& failed, PyObject* exc,
                std::uint64_t* applied, KeyCache& kc) {
    const Names* n = names();
    for (size_t j = from; j < to; ++j) {
        if (const auto* m = marker_of(w[j])) {
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
        if (!apply_write(c, w[j], kc)) return false;
        ++*applied;
    }
    return true;
}

// apply_writes(writes[from:to], walk).
template <class W>
bool apply_log(const Ctx& c, const W* w, size_t from, size_t to,
               std::uint64_t* applied) {
    KeyCache kc;
    for (size_t i = from; i < to; ++i) {
        if (apply_write(c, w[i], kc)) {
            ++*applied;
            continue;
        }
        if (!PyErr_Occurred())
            PyErr_SetString(PyExc_SystemError,
                            "combat apply: a write failed with no error");
        Raised e;
        std::vector<std::int64_t> failed;
        if (const auto* m = marker_of(w[i])) failed.push_back(m->walk);
        bool ok;
        {
            HandledAs handling(e.value);
            ok = apply_rest(c, w, i + 1, to, failed, e.value, applied, kc);
        }
        if (ok) e.restore();  // re-raise the first; else the rest's own
        return false;
    }
    return true;
}

// ── THE LEAN K0 APPLY (phase 6 A2; combat_write_apply.h) ─────────────────

// A run's per-type kinds: kind_of's answer for (type, field), kept by the
// type so a run asks it once per field, not per write. An entry is valid
// while the kind cache's epoch and mapping are the ones it was filled
// under (a reset empties the map that owns the type; the epoch then
// changes). kUnknown: not asked yet; kGeneral: a kind the lean path does
// not store itself (REF, REFS, PYTHON).
constexpr std::int8_t kUnknown = -1;
constexpr std::int8_t kGeneral = -2;
constexpr size_t kK0Fields = static_cast<size_t>(cb::Field::kCount);

struct K0TypeKinds {
    PyObject* type = nullptr;   // borrowed: kind_cache().map owns it
    PyObject* kinds = nullptr;  // the mapping it was filled from
    std::uint64_t epoch = 0;
    std::int8_t kind[kK0Fields];
};

K0TypeKinds& k0_type_kinds(PyObject* type, PyObject* kinds) {
    static auto* table = new K0TypeKinds[32];
    K0TypeKinds& e = table[(static_cast<std::uint64_t>(
                                reinterpret_cast<std::uintptr_t>(type)) *
                            0x9E3779B97F4A7C15ull) >>
                           59];
    const KindCache& cache = kind_cache();
    if (e.type != type || e.kinds != kinds || e.epoch != cache.epoch) {
        e.type = type;
        e.kinds = kinds;
        e.epoch = cache.epoch;
        std::memset(e.kind, kUnknown, sizeof e.kind);
    }
    return e;
}

// One run of consecutive writes to one handle: its object and its dict,
// looked up once (the registry's live object carrying the handle as its
// `_nslot`, as walk.obj answers it -- no pins dict: K0's apply runs no
// Python between the kernel's write and this store but the wake hook,
// which cannot free a row), or `slow`: the run takes apply_k0's path
// (walk.obj with its pins, its errors).
struct K0Run {
    std::int64_t h = -1;
    bool open = false;
    bool slow = false;
    // `_passive_asleep` read falsy and no Python run since (a wake, a
    // general-path write): a later WAKE write of the run needs no probe.
    bool awake = false;
    Ref obj;
    Ref dict;
    K0TypeKinds* kinds = nullptr;
};

// The run's object's dict again, after Python ran (it may have replaced
// it): false with nothing set and the run slow when it is no exact dict.
void k0_refresh_dict(K0Run& r) {
    r.awake = false;
    Ref d(PyObject_GetAttr(r.obj.get(), names()->dict));
    if (!d || !PyDict_CheckExact(d.get())) {
        PyErr_Clear();
        r.slow = true;
        r.dict = Ref();
        return;
    }
    r.dict = std::move(d);
}

void k0_open_run(const Ctx& c, std::int64_t h, K0Run& r, K0ApplyStats& st) {
    r.obj = Ref();
    r.dict = Ref();
    r.kinds = nullptr;
    r.awake = false;
    r.h = h;
    r.open = true;
    ++st.runs;
    const Names* n = names();
    r.slow = true;
    if (h < 0) return;
    Ref key(PyLong_FromLongLong(h));
    if (!key) {
        PyErr_Clear();
        return;
    }
    Ref o(registry_get(c.registry, key.get()));
    if (!o || o.get() == Py_None) {
        PyErr_Clear();
        return;
    }
    Ref d(PyObject_GetAttr(o.get(), n->dict));
    if (!d || !PyDict_CheckExact(d.get())) {
        PyErr_Clear();
        return;
    }
    PyObject* s = PyDict_GetItemWithError(d.get(), n->nslot);
    if (s == nullptr || !PyLong_CheckExact(s)) {
        PyErr_Clear();
        return;
    }
    int overflow = 0;
    const long long v = PyLong_AsLongLongAndOverflow(s, &overflow);
    if (overflow != 0 || v != h) {
        PyErr_Clear();
        return;
    }
    r.slow = false;
    r.obj = std::move(o);
    r.dict = std::move(d);
    r.kinds = &k0_type_kinds(reinterpret_cast<PyObject*>(Py_TYPE(r.obj.get())),
                             c.kinds);
}

APPLY_INLINE bool k0_same_float(PyObject* cur, double d) {
    if (cur == nullptr || !PyFloat_CheckExact(cur)) return false;
    const double v = PyFloat_AS_DOUBLE(cur);
    return std::memcmp(&v, &d, sizeof v) == 0;
}

// The write's field kind for the run's type (asked once per type and
// field): kPlain, kWake or kGeneral. False: a Python error is set.
bool k0_run_kind(const Ctx& c, K0Run& r, PyObject* field, cb::Field f,
                 int* out) {
    const size_t i = static_cast<size_t>(f);
    std::int8_t k = r.kinds->kind[i];
    if (k == kUnknown) {
        KindEntry e;
        if (!kind_of(c, reinterpret_cast<PyObject*>(Py_TYPE(r.obj.get())),
                     field, &e))
            return false;
        Py_XDECREF(e.setter);
        k = (e.kind == kPlain || e.kind == kWake)
                ? static_cast<std::int8_t>(e.kind)
                : kGeneral;
        // Kept only while the cache owns the type (its mapping is this one).
        if (kind_cache().kinds == c.kinds) r.kinds->kind[i] = k;
    }
    *out = k;
    return true;
}

// WakeField.__set__'s `if obj.__dict__.get("_passive_asleep", False):
// wake(obj)`, on the run's dict.
bool k0_wake(const Ctx& c, K0Run& r) {
    if (r.awake) return true;
    PyObject* a = PyDict_GetItemWithError(r.dict.get(), names()->asleep);
    if (a == nullptr) {
        if (PyErr_Occurred()) return false;
        r.awake = true;
        return true;
    }
    if (a == Py_False) {
        r.awake = true;
        return true;
    }
    Ref held(Py_NewRef(a));  // the truth test can run Python
    const bool exact = PyBool_Check(a);
    const int truth = PyObject_IsTrue(a);
    if (truth < 0) return false;
    if (!truth) {
        if (exact) r.awake = true;
        else k0_refresh_dict(r);
        return true;
    }
    Ref res(PyObject_CallOneArg(c.wake, r.obj.get()));
    if (!res) return false;
    k0_refresh_dict(r);
    return true;
}

bool apply_k0_lean(const Ctx& c, const cb::K0Write& kw, K0Run& r,
                   KeyCache& kc, K0ApplyStats& st) {
    ++st.writes;
    const cb::K0FieldWrite& w = kw.w;
    if (names() == nullptr) return false;
    PyObject* field = k0_field(w);
    if (field == nullptr) return false;
    if (!r.open || kw.handle != r.h) k0_open_run(c, kw.handle, r, st);
    // apply_k0 itself: walk.obj (pins, registry), the field's kind, its
    // store -- for a run the lean path cannot name, a kind it does not
    // store (REF, REFS, PYTHON), a stop's Ref / Null write, and any shape
    // it does not expect (that path raises what the reference raises).
    auto general = [&]() {
        ++st.general;
        const bool ok = apply_k0(c, kw, kc);
        if (ok && !r.slow) k0_refresh_dict(r);  // its Python may have run
        return ok;
    };
    if (r.slow) return general();
    PyObject* d = r.dict.get();
    switch (w.type) {
        case cb::K0FieldWrite::Type::Slot: {
            PyObject* list = PyDict_GetItemWithError(d, field);
            if (list == nullptr || !PyList_CheckExact(list) || w.index < 0 ||
                w.index >= PyList_GET_SIZE(list)) {
                PyErr_Clear();
                return general();  // slot_store's own errors
            }
            const Py_ssize_t i = static_cast<Py_ssize_t>(w.index);
            if (k0_same_float(PyList_GET_ITEM(list, i), w.d)) {
                ++st.identical;
                return true;
            }
            PyObject* v = PyFloat_FromDouble(w.d);
            if (v == nullptr) return false;
            Ref held(Py_NewRef(list));
            const bool ok = PyList_SetItem(list, i, v) == 0;  // steals v
            r.awake = false;  // the old element's release could run Python
            return ok;
        }
        case cb::K0FieldWrite::Type::Watcher: {
            PyObject* watcher = PyDict_GetItemWithError(d, field);
            Ref wd;
            if (watcher != nullptr) {
                Ref held(Py_NewRef(watcher));
                wd = Ref(PyObject_GetAttr(watcher, names()->dict));
            }
            if (!wd || !PyDict_CheckExact(wd.get())) {
                PyErr_Clear();
                return general();  // watcher_store's own errors
            }
            if (k0_same_float(
                    PyDict_GetItemWithError(wd.get(), names()->value), w.d)) {
                ++st.identical;
                return true;
            }
            if (PyErr_Occurred()) return false;
            Ref v(PyFloat_FromDouble(w.d));
            if (!v) return false;
            r.awake = false;
            return PyDict_SetItem(wd.get(), names()->value, v.get()) == 0;
        }
        case cb::K0FieldWrite::Type::Float:
        case cb::K0FieldWrite::Type::Flag:
        case cb::K0FieldWrite::Type::Int:
            break;
        default:
            return general();  // a stop's Ref / Null write
    }
    int kind;
    if (!k0_run_kind(c, r, field, w.field, &kind)) return false;
    if (kind == kGeneral) return general();
    PyObject* cur = PyDict_GetItemWithError(d, field);
    if (cur == nullptr && PyErr_Occurred()) return false;
    bool same;
    switch (w.type) {
        case cb::K0FieldWrite::Type::Float:
            same = k0_same_float(cur, w.d);
            break;
        case cb::K0FieldWrite::Type::Flag:
            same = cur == (w.i != 0 ? Py_True : Py_False);
            break;
        default: {
            same = false;
            if (cur != nullptr && PyLong_CheckExact(cur)) {
                int overflow = 0;
                const long long v = PyLong_AsLongLongAndOverflow(cur, &overflow);
                if (v == -1 && PyErr_Occurred()) return false;
                same = overflow == 0 && v == w.i;
            }
            break;
        }
    }
    if (same) {
        ++st.identical;
    } else {
        PyObject* v = w.type == cb::K0FieldWrite::Type::Float
                          ? PyFloat_FromDouble(w.d)
                      : w.type == cb::K0FieldWrite::Type::Flag
                          ? PyBool_FromLong(w.i != 0 ? 1 : 0)
                          : PyLong_FromLongLong(w.i);
        if (v == nullptr) return false;
        // A scalar's release runs no Python; anything else's may.
        const bool plain = cur == nullptr || PyFloat_CheckExact(cur) ||
                           PyLong_CheckExact(cur) || PyBool_Check(cur);
        const bool ok = PyDict_SetItem(d, field, v) == 0;
        Py_DECREF(v);
        if (!ok) return false;
        if (!plain) r.awake = false;
    }
    if (kind == kWake) return k0_wake(c, r);
    return true;
}

// apply_log for a K0 record's writes, through the lean path; a raise is
// handled exactly as apply_log handles it (the rest by the general path).
bool apply_k0_log(const Ctx& c, const cb::K0Write* w, size_t from, size_t to,
                  std::uint64_t* applied) {
    KeyCache kc;
    K0Run run;
    K0ApplyStats& st = k0_apply_stats();
    for (size_t i = from; i < to; ++i) {
        if (apply_k0_lean(c, w[i], run, kc, st)) {
            ++*applied;
            continue;
        }
        if (!PyErr_Occurred())
            PyErr_SetString(PyExc_SystemError,
                            "combat apply: a write failed with no error");
        Raised e;
        std::vector<std::int64_t> failed;
        bool ok;
        {
            HandledAs handling(e.value);
            ok = apply_rest(c, w, i + 1, to, failed, e.value, applied, kc);
        }
        if (ok) e.restore();
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

PyObject* registry_lookup(PyObject* registry, PyObject* h) {
    return registry_get(registry, h);
}

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
bool WriteApplier::apply_range(const W* w, size_t size, size_t from,
                               size_t to) {
    if (ctx_ == nullptr) {
        PyErr_SetString(PyExc_RuntimeError,
                        "combat apply: no applier context "
                        "(combat_set_applier)");
        return false;
    }
    to = std::min(to, size);
    if (from >= to) return true;
    // Held for the apply: Python run inside may install another context.
    Ref ctx(Py_NewRef(ctx_));
    return apply_log(unpack(ctx.get()), w, from, to, &applied_);
}

PyObject* WriteApplier::live(std::int64_t h) {
    if (ctx_ == nullptr) {
        PyErr_SetString(PyExc_RuntimeError,
                        "combat apply: no applier context "
                        "(combat_set_applier)");
        return nullptr;
    }
    Ref ctx(Py_NewRef(ctx_));
    Ref key(PyLong_FromLongLong(h));
    if (!key) return nullptr;
    bool minus_one = false;
    return walk_live(unpack(ctx.get()), key.get(), &minus_one);
}

bool WriteApplier::apply(const std::vector<cb::K1Write>& w, size_t from,
                         size_t to) {
    return apply_range(w.data(), w.size(), from, to);
}

bool WriteApplier::apply(const std::vector<cb::K2Write>& w, size_t from,
                         size_t to) {
    return apply_range(w.data(), w.size(), from, to);
}

bool WriteApplier::apply(const std::vector<ApplyWrite>& w, size_t from,
                         size_t to) {
    return apply_range(w.data(), w.size(), from, to);
}

bool WriteApplier::apply(std::span<const cb::K0Write> w) {
    if (ctx_ == nullptr) {
        PyErr_SetString(PyExc_RuntimeError,
                        "combat apply: no applier context "
                        "(combat_set_applier)");
        return false;
    }
    if (w.empty()) return true;
    // Held for the apply: Python run inside may install another context.
    Ref ctx(Py_NewRef(ctx_));
    return apply_k0_log(unpack(ctx.get()), w.data(), 0, w.size(), &applied_);
}

K0ApplyStats& k0_apply_stats() {
    static K0ApplyStats s;
    return s;
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
        w.field = pooled_name(s, static_cast<size_t>(len));
        if (!parse_value(PyTuple_GET_ITEM(item, 2), &w.value)) return false;
        out->push_back(std::move(w));
    }
    return true;
}

PyObject* k0_field_name(const cb::K0FieldWrite& w) { return k0_field(w); }

}  // namespace dauntless::host
