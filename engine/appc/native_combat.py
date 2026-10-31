"""The native combat mirror, kept in sync from Python.

The combat step's sensor query (can_detect) is moving into C++
(native/src/combat/, spec docs/superpowers/specs/2026-10-30-native-combat-step-design.md).
The C++ reads its inputs from a MIRROR: one row per Python object it looks at
(ObjectClass, ShipSubsystem, the subsystem property, SetClass), one Profile
row per system map, and one set of scalar globals (dials, flags, constants).
This module keeps all of it equal to the Python.

A Set row holds the set's ordered ship and nebula lists, pushed from
contact_index's own buckets after every mutation, and its RESOLVED profile
frame (``push_set_frame``): native never sees a set name (CDM §9.15).

How a row stays in sync: every mirrored attribute is a data descriptor with a
``__set__`` and NO ``__get__`` -- reads stay plain instance-dict reads, exactly
like passive_state.WakeField -- and each write is pushed into the row at once.
A write that does not go through ``__set__`` (an in-place ``.add`` on a set, a
``list.append``, a direct ``obj.__dict__[...] =``) is NOT seen: those sites
call ``push_ids`` themselves, and ``audit_mirror`` exists to catch a missed one.
A subclass that HIDES a mirrored attribute behind its own property (Torpedo)
is caught per class at registration (``_hidden_fields``): a hidden ref reads
REF_UNREPRESENTABLE, and an object hiding a scalar gets no row.

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

from engine.appc.passive_power import FrozenField, ThawParentWakeField
from engine.appc.passive_state import WakeField
from engine.core.ids import implements

try:
    import _dauntless_host as _h
except ImportError:
    _h = None  # bindings not built: nothing registers, Python answers.

_enabled = False
_audit = False
_failures: list = []
# Dispatched queries (sensor_detection, sensor_occlusion) the kernel answered,
# and the ones that fell back to the Python on its ValueError. Counted only on
# the native path, so the switch-off path pays nothing.
_counts = {"native_calls": 0, "fallbacks": 0}
# handle -> object, for resync and the audit. Weak: the row's lifetime is the
# object's, and its finalizer unregisters the row.
_registry: "weakref.WeakValueDictionary[int, object]" = weakref.WeakValueDictionary()
_field_ids: dict = {}
_kind_ids: dict = {}
_class_fields: dict = {}
_class_hidden: dict = {}

#: NativeField type for a flag the reader tests with ``is True`` (identity,
#: not truthiness): engine.appc.subsystems._is_offline on _radiation_out.
IS_TRUE = "is True"
#: NativeField type for an optional 3-tuple of floats (MetaNebula ``_fbm``,
#: ``_seed``): None pushes "unset".
VEC3 = "vec3"
#: NativeField type for MetaNebula ``_spheres``: a list of (x, y, z, r).
SPHERES = "spheres"
#: NativeField type for an int-or-None (``TorpedoSystem._selected_slot``):
#: None pushes -1 (slots are never negative).
OPT_INT = "opt int"

# system name -> (the map's Profile object, its Profile row handle). One row
# per system map, registered lazily at the first frame push that needs it.
_profiles: dict = {}

_KIND_SHIFT = 60


# ── The switch ───────────────────────────────────────────────────────────────

def available() -> bool:
    return _h is not None and hasattr(_h, "combat_register")


def configure(environ: Mapping[str, str] = os.environ) -> None:
    global _enabled, _audit
    audit = environ.get("DAUNTLESS_NATIVE_AUDIT") == "1"
    want = (audit or environ.get("DAUNTLESS_NATIVE_COMBAT") == "1") \
        and available()
    # The audit is on only when native ended up on: auditing rows that were
    # never pushed would record every field of every row, every tick.
    _audit = False
    if not want:
        _enabled = False
        return
    if not _enabled:
        if _self_check() is not None:
            return                  # _self_check disabled native and said why
        _enabled = True
        resync()
    _audit = audit


def enabled() -> bool:
    return _enabled


def audit_enabled() -> bool:
    return _audit


def reset() -> None:
    global _enabled, _audit
    _enabled = False
    _audit = False
    _failures.clear()
    _profiles.clear()
    _counts["native_calls"] = 0
    _counts["fallbacks"] = 0


def counts() -> dict:
    """{"native_calls": n, "fallbacks": n} since the last reset()."""
    return dict(_counts)


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
    h = obj.__dict__.get("_nslot")
    if h is None:
        return
    if _enabled and (h >> _KIND_SHIFT) == _kind("Object"):
        _hand_latch_to_python(obj, h)
    del obj.__dict__["_nslot"]
    if _registry.get(h) is obj:
        del _registry[h]
    unregister_handle(h)
    if not _enabled:
        return
    # Rows that NAME the dropped object now read it as unrepresentable (-2),
    # never as None (-1, what a freed handle reads) or as absent.
    k = h >> _KIND_SHIFT
    if k == _kind("Set"):
        for member in list(getattr(obj, "_objects", {}).values()):
            if member.__dict__.get("_containing_set") is obj:
                _repush_field(member, "_containing_set")
    elif k == _kind("Object"):
        from engine.appc import contact_index
        for pSet in contact_index.sets_holding(obj):
            push_set_members(pSet)
    if k in (_kind("Object"), _kind("Subsystem")):
        _repush_referrers(obj)


def _repush_referrers(dropped) -> None:
    """A freed handle reads as none (-1) in a ref and vanishes from a list;
    the weapon fields that NAME the dropped object must read -2 instead
    (R6), so they are re-pushed (they re-encode to -2 now that `_nslot` is
    gone). An exceptional path (a value the mirror cannot hold), so the scan
    of every row is acceptable."""
    for h, other in list(_registry.items()):
        d = other.__dict__
        if other is dropped or d.get("_nslot") != h:
            continue
        for name, field in _fields_of(type(other)):
            if not isinstance(field, NativeRefField) \
                    and not isinstance(field, NativeRefList):
                continue
            value = d.get(name)
            if value is dropped or (
                    isinstance(value, (list, dict))
                    and any(v is dropped for v in (
                        value.values() if isinstance(value, dict)
                        else value))):
                field._push(other, h, value)


def _hand_latch_to_python(obj, h: int) -> None:
    """Ruling R7 moves a pair's latch with its owner: a dropped row's pairs
    leave the native latch (unregister erases them) and the pair now belongs
    to the Python, so its broken locks are copied into sensor_detection's
    `_broken` first. The other side is the dropped object or a registered one
    (the native latch only ever holds registered pairs)."""
    try:
        pairs = _h.combat_latch_pairs(h)
    except ValueError:
        return
    if not pairs:
        return
    from engine.appc import sensor_detection

    def owner(handle):
        if handle == h:
            return obj
        other = _registry.get(handle)
        if other is None or other.__dict__.get("_nslot") != handle:
            return None
        return other
    for oh, th in pairs:
        o, t = owner(oh), owner(th)
        if o is not None and t is not None:
            sensor_detection._py_set_latched(o, t, True)


def _repush_field(obj, name: str) -> None:
    h = obj.__dict__.get("_nslot")
    if h is None or name not in obj.__dict__:
        return
    for attr, field in _fields_of(type(obj)):
        if attr == name:
            field._push(obj, h, obj.__dict__[name])
            return


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
        # The combat_dump key: the field's own name ("Subsystem._radius"
        # dumps as "_radius").
        self._dump_key = self._key.rsplit(".", 1)[-1]

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
        if t is OPT_INT:
            return -1 if value is None else int(value)
        if t is VEC3:
            if value is None:
                return []
            try:
                x, y, z = value.x, value.y, value.z     # a TGPoint3
            except AttributeError:
                x, y, z = value
            return [float(x), float(y), float(z)]
        if t is SPHERES:
            return [(float(x), float(y), float(z), float(r))
                    for (x, y, z, r) in value]
        return [int(i) for i in value]

    def _push(self, obj, h, value) -> None:
        try:
            v = self._encode(value)
        except (TypeError, ValueError, OverflowError):
            _drop(obj)  # not representable: never leave a stale row
            return
        t = self._type
        if t is SPHERES:
            _call(obj, _h.combat_set_spheres, h, v)
            return
        if t is float:
            fn = _h.combat_set_f
        elif t is list or t is set:
            fn = _h.combat_set_ids
        elif t is VEC3:
            fn = _h.combat_set_fv
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
        if self._type is VEC3:
            if mirrored is None:
                return v == []
            return _hexes(v) == _hexes(mirrored)
        if self._type is SPHERES:
            return [_hexes(s) for s in v] == [_hexes(s) for s in mirrored]
        return v == mirrored


def _hexes(values) -> tuple:
    return tuple(float(x).hex() for x in values)


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


def _handle_of(value, target: str) -> int:
    """`value`'s row handle if it is a registered row of kind `target`, else
    REF_UNREPRESENTABLE (ruling R6): the entry keeps its place."""
    t = _slot_of(value)
    if t is None or (t >> _KIND_SHIFT) != _kind(target):
        return REF_UNREPRESENTABLE
    return t


class NativeRefList(NativeField):
    """An ORDERED list of references to mirrored objects of kind `target`
    (WeaponSystem._target_list, ShipSubsystem._children). Each entry pushes
    its handle, or -2 for a referent the mirror cannot name. An in-place
    ``append`` is invisible to a descriptor: the site calls ``push_field``."""

    def __init__(self, target: str) -> None:
        super().__init__(list)
        self._target = target

    def _encode(self, value):
        return [_handle_of(v, self._target) for v in value]

    def _push(self, obj, h, value) -> None:
        try:
            v = self._encode(value)
        except (TypeError, ValueError, OverflowError):
            _drop(obj)
            return
        _call(obj, _h.combat_set_ids, h, _fid(self._key), v)

    def _matches(self, value, mirrored) -> bool:
        try:
            return self._encode(value) == mirrored
        except (TypeError, ValueError, OverflowError):
            return False


class NativeSlotMap(NativeRefList):
    """TorpedoSystem._ammo_by_slot, a {slot: ammo} dict: pushed as the
    interleaved list [slot, Ammo handle, slot, Ammo handle, ...] in dict
    order. An in-place ``d[k] = v`` / ``del d[k]`` calls ``push_field``."""

    def __init__(self) -> None:
        super().__init__("Ammo")

    def _encode(self, value):
        out = []
        for slot, ammo in value.items():
            out.append(int(slot))
            out.append(_handle_of(ammo, self._target))
        return out


class NativeWrapped:
    """Mixin for a passive_state / passive_power descriptor that also pushes:
    the base descriptor's wake or thaw first, then the push. ``_native`` is
    the NativeField that knows the type and the row key."""

    def _init_native(self, type_, key) -> None:
        self._native = NativeField(type_, key)

    def __set_name__(self, owner, name) -> None:
        super().__set_name__(owner, name)
        self._native.__set_name__(owner, name)

    def _after_set(self, obj, value) -> None:
        if _enabled:
            h = obj.__dict__.get("_nslot")
            if h is not None:
                self._native._push(obj, h, value)


class NativeFrozenField(NativeWrapped, FrozenField):
    """FrozenField's thaw (passive_power), then the push."""

    def __init__(self, type_=float, key=None) -> None:
        self._init_native(type_, key)

    def __set__(self, obj, value) -> None:
        FrozenField.__set__(self, obj, value)
        self._after_set(obj, value)


class NativeWakeField(NativeWrapped, WakeField):
    """WakeField's wake (passive_state), then the push."""

    def __init__(self, type_=float, key=None) -> None:
        self._init_native(type_, key)

    def __set__(self, obj, value) -> None:
        WakeField.__set__(self, obj, value)
        self._after_set(obj, value)


class NativeThawParentWakeField(NativeWrapped, ThawParentWakeField):
    """ThawParentWakeField's wake and parent thaw, then the push."""

    def __init__(self, type_=float, key=None) -> None:
        self._init_native(type_, key)

    def __set__(self, obj, value) -> None:
        ThawParentWakeField.__set__(self, obj, value)
        self._after_set(obj, value)


class PosedPartsField:
    """``ShipClass._articulation_poses``: a rebind can change
    ``bool(posed_part_names(ship))`` (a forced pose adds a name, dropping it
    removes one), so the ship's has_posed_parts flag is re-pushed. In-place
    ``poses[name] = pose`` writes (tick_ship) only touch rig names, which the
    flag already counts. The attribute is ABSENT until first written (the
    readers use getattr(..., None)), so unlike the other descriptors this one
    needs a __get__ that reads the instance dict."""

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        try:
            return obj.__dict__[self._name]
        except KeyError:
            raise AttributeError(self._name) from None

    def __set__(self, obj, value) -> None:
        obj.__dict__[self._name] = value
        push_posed_parts(obj)


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
                native = _native_of(attr)
                if native is not None:
                    out.append((name, native))
        fields = _class_fields[cls] = tuple(out)
    return fields


def _native_of(attr):
    if isinstance(attr, NativeField):
        return attr
    if isinstance(attr, NativeWrapped):
        return attr._native
    return None


def _hidden_fields(cls) -> tuple:
    """Mirrored attributes that a class in cls's MRO HIDES behind something
    that is not a Native descriptor (Torpedo's ``_containing_set`` and
    ``_radius`` properties): writes to them never reach the row. Returns
    (refs, scalars): ``refs`` is ((name, NativeRefField), ...), pushed as
    REF_UNREPRESENTABLE so the kernel falls back on any read of them;
    ``scalars`` is (name, ...), which have no such value, so an object with
    one gets no row at all (``register``), the rule ``NativeField._push``
    applies to an unencodable value. Computed once per class."""
    plan = _class_hidden.get(cls)
    if plan is None:
        winner, refs, scalars = {}, [], []
        for klass in cls.__mro__:
            for name, attr in vars(klass).items():
                if name not in winner:
                    winner[name] = attr
                    continue
                native = _native_of(attr)
                if native is None or _native_of(winner[name]) is not None:
                    continue
                if name in scalars or any(n == name for n, _ in refs):
                    continue
                if isinstance(native, NativeRefField):
                    refs.append((name, native))
                else:
                    scalars.append(name)
        plan = _class_hidden[cls] = (tuple(refs), tuple(scalars))
    return plan


# ── Rows ─────────────────────────────────────────────────────────────────────

def register(obj, kind: str, finalize: bool = True) -> None:
    """Give `obj` a mirror row of `kind` ("Object", "Subsystem", "Property",
    "Set"; Profile rows are owned by this module, one per system map).
    Always registers when the bindings are built; pushes only when enabled.
    `finalize=False` when the caller's own finalizer unregisters the row
    (ObjectClass frees its transform slot and its row in one finalizer)."""
    if not available():
        return
    d = obj.__dict__
    if "_nslot" in d:
        return
    if _hidden_fields(type(obj))[1]:
        return      # a hidden scalar cannot read "unrepresentable": no row
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


#: Subsystem.weapon_kind by class, in isinstance order (a bank is not a
#: system: PhaserBank derives from WeaponSystem, not PhaserSystem).
_WEAPON_KINDS = None
_kind_by_type: dict = {}


def _weapon_kind(obj) -> int:
    global _WEAPON_KINDS
    cls = type(obj)
    k = _kind_by_type.get(cls)
    if k is None:
        if _WEAPON_KINDS is None:
            from engine.appc import weapon_subsystems as ws
            _WEAPON_KINDS = ((ws.PhaserSystem, 1), (ws.PulseWeaponSystem, 2),
                             (ws.TractorBeamSystem, 3), (ws.TorpedoSystem, 4),
                             (ws.PhaserBank, 5), (ws.PulseWeapon, 6),
                             (ws.TractorBeam, 7), (ws.TorpedoTube, 8))
        k = 0
        for klass, kind in _WEAPON_KINDS:
            if issubclass(cls, klass):
                k = kind
                break
        _kind_by_type[cls] = k
    return k


def _posed_flag(ship) -> int:
    """``bool(articulation.posed_part_names(ship))``, but never the call that
    would cache a rig-less leaf for a ship whose script is not set yet
    (articulation.leaf_for caches "" for good): such a ship has no weapons to
    fire either. push_posed_parts re-pushes once the script is set."""
    d = ship.__dict__
    if "_articulation_leaf" not in d and not d.get("_articulation_poses"):
        try:
            script = ship.GetScript()
        except Exception:  # noqa: BLE001 - a double without a script
            script = None
        if not script:
            return 0
    from engine.appc import articulation
    return int(bool(articulation.posed_part_names(ship)))


def _flags(obj, h) -> dict:
    k = h >> _KIND_SHIFT
    if k == _kind("Object"):
        from engine.appc.nebula import MetaNebula
        from engine.appc.ships import ShipClass
        from engine.rocks.rock import RockClass
        return {
            "has_sensor_getter": int(implements(obj, "GetSensorSubsystem")),
            "has_cloak_getter": int(
                getattr(type(obj), "GetCloakingSubsystem", None) is not None),
            "is_rock": int(isinstance(obj, RockClass)),
            "is_meta_nebula": int(isinstance(obj, MetaNebula)),
            # A stub's IsDead records telemetry; K1 hands such a target back
            # to Python (it must not call the real thing).
            "has_real_is_dead": int(implements(obj, "IsDead")),
            "has_posed_parts": (_posed_flag(obj)
                                if isinstance(obj, ShipClass) else 0),
        }
    if k == _kind("Subsystem"):
        return {"has_parent_ship_getter": int(implements(obj,
                                                         "GetParentShip")),
                "weapon_kind": _weapon_kind(obj),
                "pump_self_managed": int(bool(getattr(
                    type(obj), "_pump_self_managed", False)))}
    return {}


def push_posed_parts(ship) -> None:
    """Re-push the ship's has_posed_parts flag: its pose dict was rebound
    (PosedPartsField), its rig appeared or went (articulation.tick_ship via
    note_rig), or SetupProperties just gave it a script."""
    if _enabled:
        h = ship.__dict__.get("_nslot")
        if h is not None:
            _call(ship, _h.combat_set_i, h, _fid("has_posed_parts"),
                  _posed_flag(ship))


def note_rig(ship, key) -> None:
    """tick_ship resolved `ship`'s rig for `key` = (leaf, rig generation):
    push the flag once per key."""
    if _enabled:
        d = ship.__dict__
        if d.get("_nc_rig_key") != key:
            d["_nc_rig_key"] = key
            push_posed_parts(ship)


def push_pulse_params(bank) -> None:
    """A pulse weapon's projectile module, resolved by Python (ruling P6):
    module_ok, launch_speed and lifetime, cached per script in
    weapon_subsystems (cleared with the projectile module cache)."""
    if _enabled:
        h = bank.__dict__.get("_nslot")
        if h is None:
            return
        ok, speed, life = _pulse_params(bank)
        _call(bank, _h.combat_set_i, h, _fid("module_ok"), ok)
        if "_nslot" in bank.__dict__:
            _call(bank, _h.combat_set_f, h, _fid("launch_speed"), speed)
        if "_nslot" in bank.__dict__:
            _call(bank, _h.combat_set_f, h, _fid("lifetime"), life)


def _pulse_params(bank) -> tuple:
    from engine.appc import weapon_subsystems as ws
    return ws.pulse_module_params(ws.pulse_module_script(bank))


def refresh_pulse_params() -> None:
    """The projectile module cache was reset (mission swap): every pulse bank
    already built re-reads its module."""
    if _enabled:
        for h, obj in list(_registry.items()):
            if (obj.__dict__.get("_nslot") == h
                    and (h >> _KIND_SHIFT) == _kind("Subsystem")
                    and _weapon_kind(obj) == 6):
                push_pulse_params(obj)


def _property_values(prop) -> dict:
    pm = prop._data.get(("MaxCondition", ()))
    d = prop.__dict__
    # Only a WeaponSystemProperty carries chains (WeaponSystem.GetFiringChains
    # reads [] from any other); every WeaponProperty may carry Groups.
    chains = d.get("_firing_chains") or ()
    vals = {"_firing_chains": [[int(g) for g in groups]
                               for _label, groups in chains],
            "_groups": int(d.get("_groups", 0))}
    if pm is None:
        vals.update(MaxCondition_set=0, MaxCondition=0.0)
    else:
        vals.update(MaxCondition_set=1, MaxCondition=float(pm))
    return vals


def _push_extras(obj, h) -> None:
    for name, v in _flags(obj, h).items():
        _call(obj, _h.combat_set_i, h, _fid(name), v)
    k = h >> _KIND_SHIFT
    if k == _kind("Property"):
        push_property(obj)
    elif k == _kind("Subsystem"):
        if "_nslot" in obj.__dict__ and _weapon_kind(obj) == 6:
            push_pulse_params(obj)
    elif k == _kind("Set"):
        push_set_members(obj)
        push_set_frame(obj)


def _push_all(obj, h) -> None:
    _push_extras(obj, h)
    d = obj.__dict__
    for name, field in _fields_of(type(obj)):
        if "_nslot" not in d:
            return              # dropped by a stale push
        if name in d:
            field._push(obj, h, d[name])
    for name, field in _hidden_fields(type(obj))[0]:
        if "_nslot" not in d:
            return
        _call(obj, _h.combat_set_ref, h, _fid(field._key), REF_UNREPRESENTABLE)


def reclassify(ship) -> None:
    """`ship.__class__` changed (engine.rocks.rock): re-push its class flags."""
    if _enabled:
        h = ship.__dict__.get("_nslot")
        if h is not None:
            _push_extras(ship, h)


def push_field(obj, name: str) -> None:
    """A mirrored attribute was mutated IN PLACE (MetaNebula._spheres'
    ``append``): re-push its current value through its descriptor."""
    if _enabled:
        _repush_field(obj, name)


def push_ids(obj, field: str, ids) -> None:
    """An id list or set was mutated IN PLACE (``.add``, ``.append``,
    ``.clear``), which a descriptor cannot see: push the whole thing."""
    if _enabled:
        h = obj.__dict__.get("_nslot")
        if h is not None:
            _call(obj, _h.combat_set_ids, h, _fid(field), [int(i) for i in ids])


def push_property(prop) -> None:
    """A property value the mirror holds was written: the MaxCondition
    data-bag entry, SetGroups or SetFiringChainString."""
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
        if "_nslot" in prop.__dict__:
            _call(prop, _h.combat_set_i, h, _fid("_groups"), vals["_groups"])
        if "_nslot" in prop.__dict__:
            _call(prop, _h.combat_set_id_lists, h, _fid("_firing_chains"),
                  vals["_firing_chains"])


# ── Sets, profiles and globals ───────────────────────────────────────────────

def _list_entry(obj) -> int:
    """A ship / nebula list entry: the Object handle, or -2 for an object the
    mirror cannot name (its row was dropped). It keeps its place: the list
    order IS contact_index's order, which occlusion iterates."""
    t = _slot_of(obj)
    if t is None or (t >> _KIND_SHIFT) != _kind("Object"):
        return REF_UNREPRESENTABLE
    return t


def _members(pSet) -> tuple:
    from engine.appc import contact_index
    return ([_list_entry(o) for o in contact_index.ships_in(pSet)],
            [_list_entry(o) for o in contact_index.nebulae_in(pSet)])


def push_set_members(pSet) -> None:
    """Push the set's ordered ship and nebula lists, exactly
    contact_index.ships_in / nebulae_in. contact_index calls this after every
    mutation of the set's buckets."""
    if not _enabled:
        return
    h = _slot_of(pSet)
    if h is None:
        return
    ships, nebulae = _members(pSet)
    _call(pSet, _h.combat_set_ids, h, _fid("ships"), ships)
    if "_nslot" in pSet.__dict__:
        _call(pSet, _h.combat_set_ids, h, _fid("nebulae"), nebulae)


_ZERO = (0.0, 0.0, 0.0)
_UNRESOLVABLE = object()


def _resolve_frame(pSet):
    """What profile.locate resolves for any object in `pSet`, without the
    object: (system, Profile, anchor_gu, star position_gu), all floats, or
    None (unmapped, unresolvable, or a map without a profile, which
    concealment_at treats exactly like unmapped), or _UNRESOLVABLE when the
    Python lookup raised (native takes the Python path, which raises again).
    The same frames / resolve calls, in the same order, as profile.locate."""
    from engine.systems import frames, resolve
    try:
        f = frames.frame_of(pSet)
        if f is None or f.key[0] != "system":
            return None
        m = resolve.map_of(f.key[1])
        if m is None:
            return None
        star = next((b for b in m.bodies if b.orbits is None), None)
        if star is None or m.profile is None:
            return None
        anchor = tuple(float(c) for c in f.anchor_gu)
        sx, sy, sz = star.position_gu
        return f.key[1], m.profile, anchor, (float(sx), float(sy), float(sz))
    except Exception:  # noqa: BLE001 - the Python path re-raises it at use
        return _UNRESOLVABLE


def _profile_rows(prof) -> tuple:
    return ([(float(r.distance_gu), float(r.sensors)) for r in prof.rows],
            float(prof.full_concealment))


def _profile_handle(system: str, prof) -> int:
    """The Profile row for a system map, registered at first use. A new map
    object for the system (resolve.reset_cache) replaces the row."""
    ent = _profiles.get(system)
    if ent is not None and ent[0] is prof:
        return ent[1]
    if ent is not None:
        del _profiles[system]
        unregister_handle(ent[1])
    try:
        rows, full = _profile_rows(prof)
    except (TypeError, ValueError, OverflowError):
        return REF_UNREPRESENTABLE
    ph = _h.combat_register(_kind("Profile"))
    _h.combat_set_profile_rows(ph, rows, full)
    _profiles[system] = (prof, ph)
    return ph


def push_set_frame(pSet) -> None:
    """Push the set's RESOLVED profile frame. Called whenever an input of
    frames.frame_of changes: SetClass.SetName and region_hooks.mark_mapped."""
    if not _enabled:
        return
    h = _slot_of(pSet)
    if h is None:
        return
    found = _resolve_frame(pSet)
    if found is None:
        _call(pSet, _h.combat_set_frame, h, REF_NONE, _ZERO, _ZERO)
        return
    if found is _UNRESOLVABLE:
        _call(pSet, _h.combat_set_frame, h, REF_UNREPRESENTABLE, _ZERO, _ZERO)
        return
    system, prof, anchor, star = found
    ph = _profile_handle(system, prof)
    try:
        _h.combat_set_frame(h, ph, anchor, star)
    except ValueError:
        if ph >= 0 and _live(h):
            _profiles.pop(system, None)   # the profile row is the stale one
            ph = _profile_handle(system, prof)
            _call(pSet, _h.combat_set_frame, h, ph, anchor, star)
        else:
            _drop(pSet)


_SENSOR_DIALS = ("sensorless_range_gu", "cloak_bubble_cap_gu",
                 "overboost_threshold", "min_blocker_radius_gu")
_CONSTANTS = ("CONCEAL_K", "LOCK_BREAK_T", "HYSTERESIS",
              "PROFILE_CONCEALMENT_CAP", "CLOAK_RANGE_FACTOR",
              "CLOAK_DETECTION_BASE_GU")


def _globals() -> dict:
    """Every global can_detect reads, by Python name, from the Python's own
    values: the constants too, so no number is re-typed in C++."""
    import engine.dev_mode as dev_mode
    from engine import dev_nebula_dials
    from engine.appc import sensor_detection as sd
    from engine.appc import sensor_dials
    from engine.appc import sensor_occlusion as occ
    g = {name: sensor_dials.get(name) for name in _SENSOR_DIALS}
    g["conceal_cap"] = float(dev_nebula_dials.conceal_cap())
    g["dev_mode"] = 1 if dev_mode.is_enabled() else 0
    g["occ_enabled"] = 1 if occ.enabled() else 0
    g["enhanced_sensor_contest"] = 1 if sd.ENHANCED_SENSOR_CONTEST else 0
    for name in _CONSTANTS:
        g[name] = float(getattr(sd, name))
    return g


def push_globals() -> None:
    """Push every dial, flag and constant. Called by each writer of a dial
    (sensor_dials, dev_nebula_dials, sensor_occlusion) and by resync."""
    if _enabled:
        _h.combat_set_globals(_globals())


def resync() -> None:
    """Push every registered row and the globals (the switch just turned
    on). Sets go first, so their frames' profile rows exist; every object's
    _containing_set is re-pushed with them, including objects whose set
    registered after them."""
    push_globals()
    rows = [(h, obj) for h, obj in list(_registry.items())
            if obj.__dict__.get("_nslot") == h]
    set_kind = _kind("Set")
    rows.sort(key=lambda row: (row[0] >> _KIND_SHIFT) != set_kind)
    for h, obj in rows:
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
        if ((h >> _KIND_SHIFT) == _kind("Subsystem")
                and expected["weapon_kind"] == 6):
            ok, speed, life = _pulse_params(obj)
            expected.update(module_ok=ok, launch_speed=speed, lifetime=life)
        for field, v in expected.items():
            got = row[field]
            if isinstance(v, float):
                ok = v.hex() == float(got).hex()
            else:
                ok = v == got
            if not ok:
                _failures.append((name, field))
        for attr, field in _fields_of(type(obj)):
            if attr in d and not field._matches(d[attr],
                                                row[field._dump_key]):
                _failures.append((name, attr))
        for attr, field in _hidden_fields(type(obj))[0]:
            if row[field._dump_key] != REF_UNREPRESENTABLE:
                _failures.append((name, attr))
        if (h >> _KIND_SHIFT) == _kind("Set"):
            _audit_set(obj, row, name)
    _audit_globals()


def _audit_set(pSet, row, name) -> None:
    ships, nebulae = _members(pSet)
    if row["ships"] != ships:
        _failures.append((name, "ships"))
    if row["nebulae"] != nebulae:
        _failures.append((name, "nebulae"))
    found = _resolve_frame(pSet)
    if found is None or found is _UNRESOLVABLE:
        want = (REF_NONE if found is None else REF_UNREPRESENTABLE, 0,
                _ZERO, _ZERO)
    else:
        system, prof, anchor, star = found
        ent = _profiles.get(system)
        ph = ent[1] if ent is not None and ent[0] is prof else None
        want = (ph, 1, anchor, star)
        if ph is not None:
            try:
                prow = _h.combat_dump(ph)
                rows, full = _profile_rows(prof)
            except (TypeError, ValueError, OverflowError):
                prow = None
            if prow is None or (
                    [_hexes(r) for r in prow["rows"]]
                    != [_hexes(r) for r in rows]
                    or float(prow["full_concealment"]).hex()
                    != full.hex()):
                _failures.append((name, "profile.rows"))
    got = (row["profile"], row["mapped"], row["anchor"], row["star"])
    if got[:2] != want[:2]:
        _failures.append((name, "profile"))
    if _hexes(got[2]) != _hexes(want[2]):
        _failures.append((name, "anchor"))
    if _hexes(got[3]) != _hexes(want[3]):
        _failures.append((name, "star"))


def _audit_globals() -> None:
    got = _h.combat_dump_globals()
    for key, v in _globals().items():
        g = got[key]
        ok = (v.hex() == float(g).hex()) if isinstance(v, float) else v == g
        if not ok:
            _failures.append(("globals", key))


def audit_failures() -> list:
    return _failures


def _describe(obj) -> str:
    get_id = getattr(type(obj), "GetObjID", None)
    tag = get_id(obj) if get_id is not None else id(obj)
    return "%s#%s" % (type(obj).__name__, tag)


def record_call_failure(fn_name, observer, target, python_answer,
                        native_answer) -> None:
    """Under audit, a dispatched call whose native answer differs from the
    Python's: (fn_name, observer, target, python, native). The objects are
    named, never held."""
    _failures.append((fn_name, _describe(observer), _describe(target),
                      python_answer, native_answer))


# ── Dispatch (engine/appc/sensor_detection.py, sensor_occlusion.py) ──────────

_object_kind = None
_App = None


def slot(obj):
    """`obj`'s Object row handle, or None: not registered (a test fake, a
    plain object, None) or a row of another kind. The caller then takes the
    Python path. A stale handle is returned; the kernel's ValueError on it
    sends the call to the Python too."""
    global _object_kind
    d = getattr(obj, "__dict__", None)
    if d is None:
        return None
    h = d.get("_nslot")
    if h is None:
        return None
    if _object_kind is None:
        _object_kind = _kind("Object")
    return h if (h >> _KIND_SHIFT) == _object_kind else None


def now() -> float:
    """The nebula drift clock, today's sensor_detection._game_time() value:
    App.g_kTimerManager.GetGameTime(), or 0.0 when that fails. The shim's
    TGTimerManager has no GetGameTime, so this is 0.0 today -- NOT the
    occlusion cache's clock (sensor_occlusion._now, the Utopia game time).
    The getattr default spares the native path a raised AttributeError per
    call; the value is the same."""
    global _App
    try:
        if _App is None:
            import App
            _App = App
        get = getattr(_App.g_kTimerManager, "GetGameTime", None)
        if get is None:
            return 0.0
        return float(get())
    except Exception:
        return 0.0


if available():
    # step_memo.forget() (every hit, the step's forget points, the outermost
    # block's exit) empties the native memo with the Python tables.
    from engine.core import step_memo as _step_memo
    _step_memo.on_forget(_h.combat_memo_clear)
