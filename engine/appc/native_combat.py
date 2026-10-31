"""The native combat mirror, kept in sync from Python.

The combat step's sensor query (can_detect) is moving into C++
(native/src/combat/, spec docs/superpowers/specs/2026-10-30-native-combat-step-design.md).
The C++ reads its inputs from a MIRROR: one row per Python object it looks at
(ObjectClass, ShipSubsystem, the subsystem property; Set and Profile rows are
pushed elsewhere). This module keeps those rows equal to the Python.

How a row stays in sync: every mirrored attribute is a data descriptor with a
``__set__`` and NO ``__get__`` -- reads stay plain instance-dict reads, exactly
like passive_state.WakeField -- and each write is pushed into the row at once.
A write that does not go through ``__set__`` (an in-place ``.add`` on a set, a
``list.append``, a direct ``obj.__dict__[...] =``) is NOT seen: those sites
call ``push_ids`` themselves, and ``audit_mirror`` exists to catch a missed one.

Rows live exactly as long as their Python object: ``register`` in
``__init__``, unregistered by the object's ``weakref.finalize``. Objects are
registered whenever the bindings are built, even with the switch off; nothing
is PUSHED while it is off, and turning it on resyncs every row.

The switch is read only in ``configure()`` (called by ``GameLoop.__init__``):
``DAUNTLESS_NATIVE_COMBAT=1`` on, ``=0`` or unset off;
``DAUNTLESS_NATIVE_AUDIT=1`` turns the audit on and implies native on.
"""
import math
import os
import random
import sys
import weakref
from typing import Mapping

from engine.appc.passive_power import FrozenField
from engine.core.ids import implements

try:
    import _dauntless_host as _h
except ImportError:
    _h = None  # bindings not built: nothing registers, Python answers.

_enabled = False
_audit = False
_failures: list = []
# handle -> object, for resync and the audit. Weak: the row's lifetime is the
# object's, and its finalizer unregisters the row.
_registry: "weakref.WeakValueDictionary[int, object]" = weakref.WeakValueDictionary()
_field_ids: dict = {}
_kind_ids: dict = {}
_class_fields: dict = {}

#: NativeField type for a flag the reader tests with ``is True`` (identity,
#: not truthiness): engine.appc.subsystems._is_offline on _radiation_out.
IS_TRUE = "is True"

_KIND_SHIFT = 60


# ── The switch ───────────────────────────────────────────────────────────────

def available() -> bool:
    return _h is not None and hasattr(_h, "combat_register")


def configure(environ: Mapping[str, str] = os.environ) -> None:
    global _enabled, _audit
    audit = environ.get("DAUNTLESS_NATIVE_AUDIT") == "1"
    want = (audit or environ.get("DAUNTLESS_NATIVE_COMBAT") == "1") \
        and available()
    _audit = audit and want
    if not want:
        _enabled = False
        return
    if _enabled:
        return
    if _self_check() is not None:
        return                      # _self_check disabled native and said why
    _enabled = True
    resync()


def enabled() -> bool:
    return _enabled


def audit_enabled() -> bool:
    return _audit


def reset() -> None:
    global _enabled, _audit
    _enabled = False
    _audit = False
    _failures.clear()


def _disable(reason: str) -> str:
    global _enabled
    _enabled = False
    sys.stderr.write("[native-combat] disabled: %s\n" % reason)
    return reason


def _self_check():
    """Compare the native primitives with THIS interpreter's Python on fixed
    seeded inputs. The native math.dist is CPython 3.11.15's, ported; another
    interpreter may round differently, and then native must stay off. Returns
    the reason it disabled native, or None. Inputs stay finite: a non-finite
    drift/freq/seed makes the Python density raise where native returns NaN."""
    if not available():
        return _disable("native combat bindings not built")
    from engine.appc import nebula_density as nd
    from engine.appc.nebula import DEFAULT_FBM_DIALS
    rng = random.Random(20261031)
    for _ in range(256):
        a = (rng.uniform(-2e5, 2e5), rng.uniform(-2e5, 2e5),
             rng.uniform(-2e5, 2e5))
        b = (rng.uniform(-2e5, 2e5), rng.uniform(-2e5, 2e5),
             rng.uniform(-2e5, 2e5))
        native, python = _h.combat_test_dist3(a, b), math.dist(a, b)
        if float(native).hex() != float(python).hex():
            return _disable("dist3 %s != math.dist %s at %r, %r" % (
                float(native).hex(), float(python).hex(), a, b))
    spheres = [(0.0, 0.0, 0.0, 120.0), (150.0, 20.0, -30.0, 60.0)]
    seed = nd.seed_for(0.0, 0.0, 0.0)
    freq, gain, floor = DEFAULT_FBM_DIALS
    for _ in range(32):
        p = (rng.uniform(-130.0, 220.0), rng.uniform(-130.0, 130.0),
             rng.uniform(-130.0, 130.0))
        drift_t = rng.uniform(0.0, 50.0)
        native = _h.combat_test_density(*p, spheres, seed, freq, gain, floor,
                                        drift_t)
        python = nd.density(*p, spheres, seed, freq, gain, floor, drift_t)
        if float(native).hex() != float(python).hex():
            return _disable("density %s != python %s at %r" % (
                float(native).hex(), float(python).hex(), p))
    return None


# ── Ids ──────────────────────────────────────────────────────────────────────

def _fid(key: str) -> int:
    fid = _field_ids.get(key)
    if fid is None:
        _field_ids.update(_h.combat_field_names())
        fid = _field_ids[key]
    return fid


def _kind(name: str) -> int:
    k = _kind_ids.get(name)
    if k is None:
        _kind_ids.update(_h.combat_kinds())
        k = _kind_ids[name]
    return k


#: A ref field's value for a non-None referent the mirror cannot name (an
#: unregistered object, a wrong kind): kRefUnrepresentable in mirror.h. -1 is
#: None. The kernel takes the Python path on -2, never "absent".
REF_NONE = -1
REF_UNREPRESENTABLE = -2


def _slot_of(value):
    d = getattr(value, "__dict__", None)
    if d is None:
        return None
    return d.get("_nslot")


def _drop(obj) -> None:
    """Unregister `obj`: its handle went stale (a test's combat_clear), or it
    holds a value the mirror cannot represent. From then on it takes the
    Python path. Its row is freed now; the finalizer's later unregister of
    the same handle fails quietly. Silent by design (R2)."""
    h = obj.__dict__.pop("_nslot", None)
    if h is None:
        return
    if _registry.get(h) is obj:
        del _registry[h]
    unregister_handle(h)


def _live(h: int) -> bool:
    try:
        _h.combat_dump(h)
    except ValueError:
        return False
    return True


def _call(obj, fn, *args) -> None:
    try:
        fn(*args)
    except ValueError:
        _drop(obj)


# ── Descriptors ──────────────────────────────────────────────────────────────

class NativeField:
    """A mirrored attribute. ``type_``: float, int, bool (truthiness),
    IS_TRUE (``is True``), list (ordered ids) or set (unordered ids). ``key``
    names the mirror field when it differs from the attribute (the subsystem
    radius is "Subsystem._radius"). Like WakeField: no __get__."""

    def __init__(self, type_=float, key=None) -> None:
        self._type = type_
        self._key = key

    def __set_name__(self, owner, name) -> None:
        self._name = name
        if self._key is None:
            self._key = name

    def __set__(self, obj, value) -> None:
        obj.__dict__[self._name] = value
        if _enabled:
            h = obj.__dict__.get("_nslot")
            if h is not None:
                self._push(obj, h, value)

    def _encode(self, value):
        t = self._type
        if t is float:
            return float(value)
        if t is bool:
            return 1 if value else 0
        if t is IS_TRUE:
            return 1 if value is True else 0
        if t is int:
            return int(value)
        return [int(i) for i in value]

    def _push(self, obj, h, value) -> None:
        try:
            v = self._encode(value)
        except (TypeError, ValueError, OverflowError):
            _drop(obj)  # not representable: never leave a stale row
            return
        t = self._type
        if t is float:
            fn = _h.combat_set_f
        elif t is list or t is set:
            fn = _h.combat_set_ids
        else:
            fn = _h.combat_set_i
        _call(obj, fn, h, _fid(self._key), v)

    def _matches(self, value, mirrored) -> bool:
        try:
            v = self._encode(value)
        except (TypeError, ValueError, OverflowError):
            return False
        if self._type is float:
            return v.hex() == float(mirrored).hex()
        if self._type is set:
            return sorted(set(v)) == mirrored
        return v == mirrored


class NativeRefField(NativeField):
    """A reference to another mirrored object: pushes the referent's handle,
    -1 for None, or -2 (REF_UNREPRESENTABLE) for a referent the mirror cannot
    name: unregistered, or of another kind.
    ``lazy``: register an unregistered TGModelProperty referent on first push
    (subsystem properties are shared templates with no ``__init__`` hook)."""

    def __init__(self, target: str, lazy: bool = False) -> None:
        super().__init__(None)
        self._target = target
        self._lazy = lazy

    def _ref(self, value) -> int:
        if value is None:
            return REF_NONE
        t = _slot_of(value)
        if t is None and self._lazy and _enabled and _is_property(value):
            register(value, "Property")
            t = _slot_of(value)
        if t is None or (t >> _KIND_SHIFT) != _kind(self._target):
            return REF_UNREPRESENTABLE
        return t

    def _push(self, obj, h, value) -> None:
        t = self._ref(value)
        try:
            _h.combat_set_ref(h, _fid(self._key), t)
        except ValueError:
            if t >= 0 and _live(h):
                _drop(value)    # the referent is the stale one
                _call(obj, _h.combat_set_ref, h, _fid(self._key),
                      REF_UNREPRESENTABLE)
            else:
                _drop(obj)

    def _matches(self, value, mirrored) -> bool:
        return self._ref(value) == mirrored


class NativeFrozenField(FrozenField):
    """FrozenField's thaw (passive_power), then the push."""

    def __init__(self, type_=float, key=None) -> None:
        self._native = NativeField(type_, key)

    def __set_name__(self, owner, name) -> None:
        super().__set_name__(owner, name)
        self._native.__set_name__(owner, name)

    def __set__(self, obj, value) -> None:
        FrozenField.__set__(self, obj, value)
        if _enabled:
            h = obj.__dict__.get("_nslot")
            if h is not None:
                self._native._push(obj, h, value)


def _is_property(value) -> bool:
    from engine.appc.properties import TGModelProperty
    return isinstance(value, TGModelProperty)


def _fields_of(cls) -> tuple:
    """(attribute name, NativeField) for every mirrored attribute of cls."""
    fields = _class_fields.get(cls)
    if fields is None:
        seen, out = set(), []
        for klass in cls.__mro__:
            for name, attr in vars(klass).items():
                if name in seen:
                    continue
                seen.add(name)
                if isinstance(attr, NativeField):
                    out.append((name, attr))
                elif isinstance(attr, NativeFrozenField):
                    out.append((name, attr._native))
        fields = _class_fields[cls] = tuple(out)
    return fields


# ── Rows ─────────────────────────────────────────────────────────────────────

def register(obj, kind: str, finalize: bool = True) -> None:
    """Give `obj` a mirror row of `kind` ("Object", "Subsystem", "Property").
    Always registers when the bindings are built; pushes only when enabled.
    `finalize=False` when the caller's own finalizer unregisters the row
    (ObjectClass frees its transform slot and its row in one finalizer)."""
    if not available():
        return
    d = obj.__dict__
    if "_nslot" in d:
        return
    if kind == "Object":
        xi, xg = d.get("_xform", (-1, -1))
        h = _h.combat_register(_kind(kind), xi, xg, obj.GetObjID())
    else:
        h = _h.combat_register(_kind(kind))
    d["_nslot"] = h
    _registry[h] = obj
    if finalize:
        fin = weakref.finalize(obj, unregister_handle, h)
        fin.atexit = False
    if _enabled:
        _push_all(obj, h)


def unregister_handle(h: int) -> None:
    """Finalizer body: never raises (a combat_clear may have freed it)."""
    try:
        _h.combat_unregister(h)
    except Exception:
        pass


def _flags(obj, h) -> dict:
    k = h >> _KIND_SHIFT
    if k == _kind("Object"):
        from engine.appc.nebula import MetaNebula
        from engine.rocks.rock import RockClass
        return {
            "has_sensor_getter": int(implements(obj, "GetSensorSubsystem")),
            "has_cloak_getter": int(
                getattr(type(obj), "GetCloakingSubsystem", None) is not None),
            "is_rock": int(isinstance(obj, RockClass)),
            "is_meta_nebula": int(isinstance(obj, MetaNebula)),
        }
    if k == _kind("Subsystem"):
        return {"has_parent_ship_getter": int(implements(obj,
                                                         "GetParentShip"))}
    return {}


def _property_values(prop) -> dict:
    pm = prop._data.get(("MaxCondition", ()))
    if pm is None:
        return {"MaxCondition_set": 0, "MaxCondition": 0.0}
    return {"MaxCondition_set": 1, "MaxCondition": float(pm)}


def _push_extras(obj, h) -> None:
    for name, v in _flags(obj, h).items():
        _call(obj, _h.combat_set_i, h, _fid(name), v)
    if (h >> _KIND_SHIFT) == _kind("Property"):
        push_property(obj)


def _push_all(obj, h) -> None:
    _push_extras(obj, h)
    d = obj.__dict__
    for name, field in _fields_of(type(obj)):
        if "_nslot" not in d:
            return              # dropped by a stale push
        if name in d:
            field._push(obj, h, d[name])


def reclassify(ship) -> None:
    """`ship.__class__` changed (engine.rocks.rock): re-push its class flags."""
    if _enabled:
        h = ship.__dict__.get("_nslot")
        if h is not None:
            _push_extras(ship, h)


def push_ids(obj, field: str, ids) -> None:
    """An id list or set was mutated IN PLACE (``.add``, ``.append``,
    ``.clear``), which a descriptor cannot see: push the whole thing."""
    if _enabled:
        h = obj.__dict__.get("_nslot")
        if h is not None:
            _call(obj, _h.combat_set_ids, h, _fid(field), [int(i) for i in ids])


def push_property(prop) -> None:
    """The property's MaxCondition data-bag entry was written."""
    if _enabled:
        h = prop.__dict__.get("_nslot")
        if h is None:
            return
        try:
            vals = _property_values(prop)
        except (TypeError, ValueError, OverflowError):
            _drop(prop)  # not representable: never leave a stale row
            return
        _call(prop, _h.combat_set_i, h, _fid("MaxCondition_set"),
              vals["MaxCondition_set"])
        if "_nslot" in prop.__dict__:
            _call(prop, _h.combat_set_f, h, _fid("MaxCondition"),
                  vals["MaxCondition"])


def resync() -> None:
    """Push every registered object's fields (the switch just turned on)."""
    # Task 4: Set and Profile structures are pushed here too.
    for h, obj in list(_registry.items()):
        if obj.__dict__.get("_nslot") == h:
            _push_all(obj, h)


# ── Audit ────────────────────────────────────────────────────────────────────

def audit_mirror() -> None:
    """Compare every live row with its Python object; each disagreeing field
    appends (type name, field) to the failures."""
    for h, obj in list(_registry.items()):
        d = obj.__dict__
        if d.get("_nslot") != h:
            continue
        try:
            row = _h.combat_dump(h)
        except ValueError:
            continue
        name = type(obj).__name__
        expected = dict(_flags(obj, h))
        if (h >> _KIND_SHIFT) == _kind("Property"):
            try:
                expected.update(_property_values(obj))
            except (TypeError, ValueError, OverflowError):
                _failures.append((name, "MaxCondition"))
        for field, v in expected.items():
            got = row[field]
            if isinstance(v, float):
                ok = v.hex() == float(got).hex()
            else:
                ok = v == got
            if not ok:
                _failures.append((name, field))
        for attr, field in _fields_of(type(obj)):
            if attr in d and not field._matches(d[attr], row[attr]):
                _failures.append((name, attr))


def audit_failures() -> list:
    return _failures
