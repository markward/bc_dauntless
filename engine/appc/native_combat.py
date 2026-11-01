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
import operator
import os
import random
import sys
import weakref
from typing import Mapping

from engine.appc.math import TGPoint3
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
# K2: `cb.phasers` steps run whole in Python (k2_phasers returned False), by
# why: "nested" (a K2 session is already open), "instances" (the step's
# ship_instances is not the session's TrackedInstances), "patched" (a
# function or class K2 stands in for differs from its snapshot).
_k2_steps = {"k2_python_steps": 0}
_K2_STEP_REASONS = ("nested", "instances", "patched")
_k2_step_reasons = dict.fromkeys(_K2_STEP_REASONS, 0)
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
#: NativeField type for an aim offset (`_target_offset`, `_held_offset`):
#: every Python reader tests `isinstance(offset, TGPoint3)`, so anything
#: else -- None, a plain tuple -- pushes "unset", exactly as it reads.
OFFSET = "offset"
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
    # Per-class caches: a class patched or re-based since must recompute.
    _kind_by_type.clear()
    _k1_overridden_by_type.clear()
    _k1_watch.clear()
    global _pulse_stale
    _pulse_stale = False
    _counts["native_calls"] = 0
    _counts["fallbacks"] = 0
    _k2_steps["k2_python_steps"] = 0
    for k in _K2_STEP_REASONS:
        _k2_step_reasons[k] = 0
    _k2_flags.clear()
    _k2_watch_seen[0] = -1
    _k2_iids_cache[:] = [None, -1, -1, None]
    global _k2_drop_epoch
    _k2_drop_epoch += 1
    if available():
        _h.combat_k1_reset_counts()
        _h.combat_k2_reset_counts()


def counts() -> dict:
    """Since the last reset(): {"native_calls": n, "fallbacks": n} for the
    dispatched sensor queries, and the K1 kernel's {"k1_records": n,
    "k1_python_systems": n, "k1_asks": n} (records returned, RUN_PYTHON
    hand-backs, ASKs answered by Python; counted by the kernel), plus
    "k1_python_reasons": {"pump": {...}, "system": {...}} -- the
    k1_python_systems hand-backs by K1Why name (k1_fire_control.h:
    posed_ship, overridden, instance_patch, ...; every reason, zeros
    included), for the held-weapon pump and StartFiring apart.

    K2 (`cb.phasers`): the kernel's {"k2_records", "k2_python_ships",
    "k2_asks", "k2_python_reasons": {K2Why name: n}, "k2_ask_queries":
    {query: n}} (k2_beams.h), plus "k2_python_steps" (steps run whole in
    Python) and "k2_python_step_reasons" ({"nested", "instances",
    "patched"}: n)."""
    c = dict(_counts)
    c.update(_k2_steps)
    c["k2_python_step_reasons"] = dict(_k2_step_reasons)
    if available():
        c.update(_h.combat_k1_counts())
        c.update(_h.combat_k2_counts())
    return c


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
    global _k2_drop_epoch
    _k2_drop_epoch += 1         # K2's cached ship -> iid table names handles
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
    if k in (_kind("Object"), _kind("Subsystem"), _kind("Ammo")):
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
        if t is OFFSET:
            if isinstance(value, TGPoint3):
                return [float(value.x), float(value.y), float(value.z)]
            return []
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
        elif t is VEC3 or t is OFFSET:
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
        if self._type is VEC3 or self._type is OFFSET:
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
    order; a slot holding None pushes -1 (GetCurrentAmmoType() reads None:
    no ammo, never exhausted). An in-place ``d[k] = v`` / ``del d[k]``
    calls ``push_field``."""

    def __init__(self) -> None:
        super().__init__("Ammo")

    def _encode(self, value):
        out = []
        for slot, ammo in value.items():
            out.append(int(slot))
            out.append(REF_NONE if ammo is None
                       else _handle_of(ammo, self._target))
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
    """``ShipClass._articulation_poses``: a rebind (the force_* writers, or
    tick_ship's first dict) can move a part on or off its NIF pose, so the
    ship's has_posed_parts flag (`_posed_flag`) is re-pushed. In-place
    ``poses[name] = pose`` writes (tick_ship) re-push through
    `push_posed_parts` at the end of the tick. The attribute is ABSENT until
    first written (the readers use getattr(..., None)), so unlike the other
    descriptors this one needs a __get__ that reads the instance dict."""

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


class HullBoxField(NativeField):
    """``ShipClass._shield_hull_box``: ``((cx, cy, cz), (hx, hy, hz))`` or
    absent/None. Pushed as two vectors plus ``hull_box_set``, which is 1 only
    for exactly that shape -- parsed with the same unpacking and ``float()``
    calls as ``combat._hull_box_for``, so anything that function rejects as
    malformed reads unset here. (The degenerate-extent and scale rules stay
    in the reader; the raw numbers are what is mirrored.) The attribute may
    be absent, so unlike the other fields this one needs a __get__."""

    def __init__(self) -> None:
        super().__init__(None)

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        try:
            return obj.__dict__[self._name]
        except KeyError:
            raise AttributeError(self._name) from None

    def __delete__(self, obj) -> None:
        """`del ship._shield_hull_box`: the attribute goes absent, as a plain
        attribute's would, and the row reads unset (the same encoding as a
        malformed value)."""
        try:
            del obj.__dict__[self._name]
        except KeyError:
            raise AttributeError(self._name) from None
        if _enabled:
            h = obj.__dict__.get("_nslot")
            if h is not None:
                self._push(obj, h, None)

    @staticmethod
    def _parse(value):
        if not isinstance(value, (tuple, list)) or len(value) != 2:
            return None
        try:
            centre, half = value
            c = [float(v) for v in centre]
            hh = [float(v) for v in half]
        except (TypeError, ValueError, OverflowError):
            return None
        if len(c) != 3 or len(hh) != 3:
            return None
        return c, hh

    def _push(self, obj, h, value) -> None:
        parsed = self._parse(value)
        c, hh = parsed if parsed is not None else ([0.0] * 3, [0.0] * 3)
        _call(obj, _h.combat_set_fv, h, _fid("_shield_hull_box_center"), c)
        if "_nslot" in obj.__dict__:
            _call(obj, _h.combat_set_fv, h, _fid("_shield_hull_box_half"), hh)
        if "_nslot" in obj.__dict__:
            _call(obj, _h.combat_set_i, h, _fid("hull_box_set"),
                  0 if parsed is None else 1)

    def audit(self, value, row) -> bool:
        parsed = self._parse(value)
        if parsed is None:
            return (row["hull_box_set"] == 0
                    and _hexes(row["_shield_hull_box_center"]) == _hexes(_ZERO)
                    and _hexes(row["_shield_hull_box_half"]) == _hexes(_ZERO))
        c, hh = parsed
        return (row["hull_box_set"] == 1
                and _hexes(row["_shield_hull_box_center"]) == _hexes(c)
                and _hexes(row["_shield_hull_box_half"]) == _hexes(hh))


class HasShieldsField:
    """``ShieldSubsystem._max_shields``: plain storage, but every rebind
    re-pushes the derived ``has_shields`` flag. The flag is whatever the
    subsystem's own ``HasShields()`` answers -- the expression is never
    re-typed here. The in-place ``_max_shields[f] = v`` write
    (``SetMaxShields``) cannot be seen by a descriptor and calls
    `push_has_shields` itself."""

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __set__(self, obj, value) -> None:
        obj.__dict__[self._name] = value
        push_has_shields(obj)


def push_has_shields(sub) -> None:
    """Re-push the ShieldSubsystem's has_shields flag."""
    if _enabled:
        h = sub.__dict__.get("_nslot")
        if h is not None:
            try:
                v = int(sub.HasShields())
            except (TypeError, ValueError, OverflowError):
                _drop(sub)  # not representable: never leave a stale row
                return
            _call(sub, _h.combat_set_i, h, _fid("has_shields"), v)


def _has_shields_flag(sub) -> int:
    """The flag for a row being (re)built. 0 for any subsystem that is not a
    ShieldSubsystem, and before the subsystem has its ``_max_shields`` (a
    row is registered first, before __init__ assigns anything)."""
    from engine.appc.subsystems import ShieldSubsystem
    if not isinstance(sub, ShieldSubsystem) or "_max_shields" not in sub.__dict__:
        return 0
    return int(sub.HasShields())


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
    cls = type(obj)
    if cls not in _k2_seen_set:
        _k2_seen_set.add(cls)
        _k2_seen.append(cls)
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
    return _weapon_kind_of_class(type(obj))


def _weapon_kind_of_class(cls) -> int:
    global _WEAPON_KINDS
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


# The methods K1 stands in for (it computes their answer from the mirror
# instead of calling them). A class whose MRO gives any of them a different
# function than the STOCK class of its weapon_kind had when
# weapon_subsystems defined it (the import-time snapshot, k1_snapshot_stock)
# gets k1_overridden = 1, and K1 hands its system to Python whole: a mod
# subclassing a weapon, or a patch on the stock class itself or on a base
# (`setattr(PhaserBank, "CanFire", ...)`).
_K1_LEAF_METHODS = (
    "Fire", "_fire_decide", "_fire_effect", "CanFire", "_charge_gate",
    "_shot_cost", "_aim_in_arc", "IsFiring", "IsMemberOfGroup", "IsDumbFire",
    "GetConditionPercentage", "GetDisabledPercentage", "IsDisabled",
    "_ammo_exhausted", "IsSkewFire", "GetParentSubsystem", "_climb_to_ship")
_K1_SYSTEM_METHODS = (
    "update_weapons", "try_fire_weapon", "_prune_targets",
    "_active_chain_groups", "_resolve_working_group", "_firing_weapon",
    "_reseed_all_fire_timers", "GetFiringChains", "GetNumWeapons",
    "GetWeapon", "GetNumTargets", "IsOn", "IsDisabled", "_can_engage",
    "GetParentShip", "_fired_counter", "_weapon_did_fire")
# Checked on the INSTANCE (its __dict__) at each WALK_START, for the walked
# system and each child: the cheap subset that tests and tools patch.
_K1_SYSTEM_PATCHES = ("update_weapons", "try_fire_weapon")
_K1_LEAF_PATCHES = ("Fire", "_fire_decide", "_fire_effect", "CanFire")
# weapon_kind -> (names, the stock class's resolution of them).
_k1_stock: dict = {}
# class -> its k1_overridden flag, and _k1_watch[class] -> (getter, values,
# missing): what the flag was computed on, re-checked cheaply by
# _k1_recheck_overrides at every K1 entry.
_k1_overridden_by_type: dict = {}
_k1_watch: dict = {}


def _k1_resolve(cls, names) -> tuple:
    """What each name resolves to on `cls` (None: absent). getattr on the
    class, so a staticmethod reads its function, a classmethod a bound
    method that compares equal (==) to the next one."""
    return tuple(getattr(cls, n, None) for n in names)


def k1_snapshot_stock(classes) -> None:
    """weapon_subsystems, as it finishes defining its classes, passes
    {weapon_kind: stock class}: snapshot what every K1 name resolves to on
    each, before any test, tool or mod can patch one."""
    _k1_stock.clear()
    for kind, cls in classes.items():
        names = _K1_LEAF_METHODS if kind >= 5 else _K1_SYSTEM_METHODS
        _k1_stock[kind] = (names, _k1_resolve(cls, names))
    _k1_overridden_by_type.clear()
    _k1_watch.clear()


def _k1_overridden(cls) -> int:
    hit = _k1_overridden_by_type.get(cls)
    if hit is None:
        stock = _k1_stock.get(_weapon_kind_of_class(cls))
        hit = 0
        if stock is not None:
            names, snapshot = stock
            resolved = _k1_resolve(cls, names)
            hit = int(resolved != snapshot)
            present = [(n, f) for n, f in zip(names, resolved)
                       if f is not None]
            missing = tuple(n for n, f in zip(names, resolved) if f is None)
            if len(present) > 1:
                _k1_watch[cls] = (
                    operator.attrgetter(*[n for n, _f in present]),
                    tuple(f for _n, f in present), missing)
            elif present:       # attrgetter of one name: a bare value
                _k1_watch[cls] = (operator.attrgetter(present[0][0]),
                                  present[0][1], missing)
            else:
                _k1_watch[cls] = (lambda _c: (), (), missing)
        _k1_overridden_by_type[cls] = hit
    return hit


def _k1_recheck_overrides() -> None:
    """Has a K1 method been patched on a flagged class (or a base) since its
    flag was computed? Called at every K1 entry (k1_pump, k1_system): one
    attrgetter call per class with a row, plus a getattr per name the class
    lacks -- about 1.5 us for the six stock classes. On a change the class's
    flag is recomputed against the snapshot and re-pushed to every row of
    that class (an exceptional path: a scan of the registry). A patch made
    in the middle of a K1 session is seen at the next entry."""
    changed = None
    for cls, (get, values, missing) in _k1_watch.items():
        try:
            same = get(cls) == values
        except AttributeError:          # a present name was deleted
            same = False
        if same:
            for n in missing:
                if getattr(cls, n, None) is not None:
                    same = False
                    break
        if not same:
            if changed is None:
                changed = []
            changed.append(cls)
    if changed is None:
        return
    for cls in changed:
        del _k1_overridden_by_type[cls]
        del _k1_watch[cls]
    changed = set(changed)
    fid = _fid("k1_overridden")
    for h, obj in list(_registry.items()):
        if type(obj) in changed and obj.__dict__.get("_nslot") == h:
            _call(obj, _h.combat_set_i, h, fid, _k1_overridden(type(obj)))


def _posed_flag(ship) -> int:
    """1 while some part of `ship` is drawn off its NIF pose, else 0.

    The Python mount and target-offset transforms
    (`articulation.part_transform_point`) return the authored point ITSELF
    for a part whose current pose passes `part_pose.is_identity`, so a
    rigged ship with every part there answers exactly as an unrigged one
    (Task 6b exactness check, tests/unit/test_native_posed_flag.py) and the
    native identity path may walk it. A part with no entry in
    `_articulation_poses` reads IDENTITY (`pose_for_part`), so the poses
    present are the only ones that can be off it -- no rig lookup.

    Mark's convention: a hull's natural mesh pose is its red-alert pose, so
    a Bird of Prey in a fight (an NPC with a target is in "red") reads 0.
    Mid-transition, swung for cruise, or SPV-forced off identity reads 1 and
    falls back to Python.

    Never resolves the ship's leaf: `articulation.leaf_for` on a ship whose
    script is not set yet would cache "" for good."""
    poses = ship.__dict__.get("_articulation_poses")
    if not poses:
        return 0
    from engine.appc.part_pose import is_identity
    for pose in poses.values():
        if not is_identity(pose):
            return 1
    return 0


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
            # K2: GetShields is the real method (not a stub), and the object
            # is a ship.
            "has_real_get_shields": int(implements(obj, "GetShields")),
            "is_ship_class": int(isinstance(obj, ShipClass)),
        }
    if k == _kind("Subsystem"):
        return {"has_parent_ship_getter": int(implements(obj,
                                                         "GetParentShip")),
                "weapon_kind": _weapon_kind(obj),
                "k1_overridden": _k1_overridden(type(obj)),
                "pump_self_managed": int(bool(getattr(
                    type(obj), "_pump_self_managed", False))),
                "has_shields": _has_shields_flag(obj)}
    return {}


def push_posed_parts(ship) -> None:
    """Re-push the ship's has_posed_parts flag (`_posed_flag`): its pose
    dict was rebound (PosedPartsField), tick_ship moved a part in place, or
    SetupProperties just gave it a script. The flag reads only the current
    poses (never the rig), and those are the only places they change."""
    if _enabled:
        h = ship.__dict__.get("_nslot")
        if h is not None:
            _call(ship, _h.combat_set_i, h, _fid("has_posed_parts"),
                  _posed_flag(ship))


def push_pulse_params(bank) -> None:
    """A pulse weapon's projectile module, resolved by Python (ruling P6):
    module_ok, launch_speed and lifetime, cached per script in
    weapon_subsystems (cleared with the projectile module cache)."""
    if _enabled:
        if _pulse_stale:
            refresh_stale_pulse_params()
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


#: The projectile module cache was reset (mission swap) and the pulse banks
#: already built have not re-read their module yet.
_pulse_stale = False


def mark_pulse_stale() -> None:
    """weapon_subsystems._reset_projectile_module_cache ran. Nothing is
    resolved now (the SDK tree may be half reloaded); the next push, the
    next K1 entry (k1_pump / k1_system: a K1 decision reads the params, and
    Python's Fire would read the module at that moment) or
    refresh_stale_pulse_params (GameLoop.tick) re-reads every built bank."""
    global _pulse_stale
    if _enabled:
        _pulse_stale = True


def refresh_stale_pulse_params() -> None:
    global _pulse_stale
    if _pulse_stale:
        _pulse_stale = False
        refresh_pulse_params()


def refresh_pulse_params() -> None:
    """Every pulse bank already built re-reads its module."""
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
    cls = type(ship)
    if cls not in _k2_seen_set:
        _k2_seen_set.add(cls)
        _k2_seen.append(cls)
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


# Native Global key -> weapon_subsystems module constant (K1 geometry).
_WEAPON_CONSTANTS = (
    ("TORPEDO_CONE_HALF_ANGLE", "_TORPEDO_CONE_HALF_ANGLE"),
    ("PULSE_RANGE_GATE_SECONDS", "_PULSE_RANGE_GATE_SECONDS"),
    ("PHASER_MAX_RANGE_GU", "PHASER_MAX_RANGE_GU"),   # K1's pump range gate
)


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
    from engine.appc import weapon_subsystems as ws
    for key, attr in _WEAPON_CONSTANTS:
        g[key] = float(getattr(ws, attr))
    for i, scale in enumerate(ws.PULSE_COST_SCALE_BY_POWER_SETTING):
        g["PULSE_COST_SCALE_%d" % i] = float(scale)
    # K2: the dwell flush threshold and the shield ellipsoid scale.
    from engine.appc import combat
    g["BEAM_DWELL_FLUSH_S"] = float(ws.BEAM_DWELL_FLUSH_S)
    g["SHIELD_ELLIPSOID_AXIS_SCALE"] = float(combat.SHIELD_ELLIPSOID_AXIS_SCALE)
    # K1's 0.33 s timer gate: a class constant of WeaponSystem.
    g["FIRE_TIMER_THRESHOLD"] = float(ws.WeaponSystem.FIRE_TIMER_THRESHOLD)
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
            # Resolved afresh, NOT from the cache the push used: a stale cache
            # would otherwise agree with the stale row.
            from engine.appc import weapon_subsystems as ws
            ok, speed, life = ws.resolve_pulse_module_params(
                ws.pulse_module_script(obj))
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
            if attr not in d:
                continue
            audit = getattr(field, "audit", None)   # a field of several rows
            if audit is not None:
                ok = audit(d[attr], row)
            else:
                ok = field._matches(d[attr], row[field._dump_key])
            if not ok:
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


# ── K1: the native fire-control kernel's driver (phase 1b) ─────────────────
#
# native/src/combat/include/dauntless/combat/k1_fire_control.h is the
# contract. The kernel walks host_loop._pump_held_weapons /
# WeaponSystem.update_weapons over the mirror and returns ONE record per
# combat_k1_next(); run_k1 applies the record's write log (the decision-path
# writes the kernel already made in the mirror) and then does the one thing
# only Python may do, then asks for the next record.

#: A `_target_offset` write of the walk's own offset object (ruling P5).
_WALK_OFFSET = "walk_offset"
_k1_kind_ids = None
_ws = None
_step_memo = None


def _k1_kinds() -> tuple:
    global _k1_kind_ids
    if _k1_kind_ids is None:
        k = _h.combat_k1_kinds()
        _k1_kind_ids = tuple(k[n] for n in (
            "DONE", "WALK_START", "STOP_SYSTEM", "RUN_PYTHON", "BANK_STOP",
            "FIRE", "FIRE_FAILED", "FIRE_DUMB", "ASK"))
    return _k1_kind_ids


def _k1_clocks() -> tuple:
    """(now, use_memo, drift_now) for begin_*: the weapons' Utopia game time
    (also can_detect's occlusion clock), step_memo.active() and the nebula
    drift clock (native_combat.now(); a 1a finding: not the same clock)."""
    global _ws, _step_memo
    if _ws is None:
        from engine.appc import weapon_subsystems
        from engine.core import step_memo
        _ws, _step_memo = weapon_subsystems, step_memo
    return _ws._game_time(), _step_memo.active(), now()


class _K1Walk:
    """One run_k1 loop's pin set -- handle -> object, holding every object
    the kernel may still name alive for the walk (k1_fire_control.h,
    PINNING) -- and the current walk's offset object."""

    __slots__ = ("pins", "offset")

    def __init__(self) -> None:
        self.pins = {}
        self.offset = None

    def pin(self, obj) -> None:
        d = getattr(obj, "__dict__", None)
        h = d.get("_nslot") if d is not None else None
        if h is not None:
            self.pins[h] = obj

    def pin_system(self, system) -> None:
        """The walked system, its children and its target list as they are
        now (WALK_START, and after each later record)."""
        self.pin(system)
        d = system.__dict__
        for child in d.get("_children", ()):
            self.pin(child)
        for target in d.get("_target_list", ()):
            self.pin(target)

    def walk_start(self, system) -> bool:
        """pin_system at WALK_START, plus the instance-patch check: True when
        the system or a child has an instance attribute shadowing a method
        K1 stands in for (`tube.Fire = ...`); K1 must not decide for it. A
        patch made later in the walk (by a handler) is not seen."""
        self.pin(system)
        d = system.__dict__
        patched = False
        for name in _K1_SYSTEM_PATCHES:
            if name in d:
                patched = True
        for child in d.get("_children", ()):
            self.pin(child)
            cd = child.__dict__
            for name in _K1_LEAF_PATCHES:
                if name in cd:
                    patched = True
        for target in d.get("_target_list", ()):
            self.pin(target)
        return patched

    def obj(self, h):
        """The object a record or write names: None for -1."""
        if h == REF_NONE:
            return None
        o = self.pins.get(h)
        if o is None:
            o = _registry.get(h)
            if o is None or o.__dict__.get("_nslot") != h:
                raise RuntimeError(
                    "combat K1: handle %#x names no pinned or live object" % h)
            self.pins[h] = o
        return o


_REF, _REFS, _RAW = "ref", "refs", "raw"
_quiet_setters: dict = {}


def _quiet_setter(cls, name) -> tuple:
    """(setter(obj, value), value kind) writing `name` on a `cls` instance
    WITHOUT the mirror push: a NativeField (and its ref kinds) or a plain
    attribute goes straight into the instance dict, exactly what its
    __set__ does before pushing; a Native wake/thaw descriptor runs its
    passive-state base's __set__, so the wake or thaw still happens."""
    key = (cls, name)
    hit = _quiet_setters.get(key)
    if hit is not None:
        return hit
    attr = None
    for klass in cls.__mro__:
        if name in vars(klass):
            attr = vars(klass)[name]
            break
    kind = _RAW
    if isinstance(attr, NativeWrapped):
        setter = super(NativeWrapped, attr).__set__
    elif attr is None or isinstance(attr, NativeField) \
            or not hasattr(type(attr), "__set__"):
        if isinstance(attr, NativeSlotMap):
            raise TypeError("combat K1: no quiet write for %s.%s"
                            % (cls.__name__, name))
        if isinstance(attr, NativeRefList):
            kind = _REFS
        elif isinstance(attr, NativeRefField):
            kind = _REF

        def setter(obj, value, _name=name):
            obj.__dict__[_name] = value
    else:
        raise TypeError("combat K1: no quiet write for %s.%s"
                        % (cls.__name__, name))
    hit = _quiet_setters[key] = (setter, kind)
    return hit


def apply_writes(writes, walk=None) -> None:
    """Apply a K1 write log [(handle, field, value), ...] in order, without
    pushing (the kernel already wrote the mirror). Ref values are handles
    (-1: None), a ref list a list of handles; the marker "walk_offset" is
    the walk's own offset object. `walk` maps handles through its pin set;
    without one, through the registry.

    NOT atomic: the kernel has already written every value in the log to
    the mirror, so a raise part-way (a handle no pin or row names, a wake or
    thaw hook failing) leaves the fields after it with mirror != Python, and
    run_k1's abandon cannot undo that (the kernel's rollback covers only
    writes it has not yet delivered). Unreachable today: the logged fields
    are a fixed set of plain NativeFields on pinned rows, whose quiet write
    is a dict store, and no wrapped descriptor is in the set. A field added
    to the kernel's log must keep its quiet write unable to raise."""
    if walk is None:
        walk = _K1Walk()
    for h, field, value in writes:
        obj = walk.obj(h)
        setter, kind = _quiet_setter(type(obj), field)
        if kind is _REF:
            value = walk.obj(value)
        elif kind is _REFS:
            value = [walk.obj(v) for v in value]
        elif type(value) is str and value == _WALK_OFFSET:
            value = walk.offset
        setter(obj, value)


def _k1_decision(bank, decision, walk) -> tuple:
    """A FIRE record's decision in _fire_decide's shape: handles to objects
    (pulse (xyz, target_used, module), tube (target_used,)); a beam's
    (was_firing,) as it is."""
    kind = _weapon_kind(bank)
    if kind == 6:
        return (decision[0], walk.obj(decision[1]), _k1_pulse_module(bank))
    if kind == 8:
        return (walk.obj(decision[0]),)
    return decision


def _k1_pulse_module(bank):
    """The module PulseWeapon._fire_decide would have resolved:
    importlib.import_module of the bank's script, exactly as decide calls
    it -- a sys.modules hit, or a fresh import when the module was unloaded
    since registration (ruling P6 cached only its launch speed and
    lifetime). An ImportError is where decide refuses, before its stamps;
    after the kernel's FIRE decision (stamps applied) that cannot be
    followed, so it raises and the session abandons. Any other exception
    propagates, as it does out of Python's Fire."""
    import importlib
    from engine.appc import weapon_subsystems as ws
    script = ws.pulse_module_script(bank)
    if not script:
        raise RuntimeError("combat K1: pulse bank %r has no module"
                           % (bank.GetName(),))
    try:
        return importlib.import_module(script)
    except ImportError as e:
        raise RuntimeError("combat K1: pulse module %r does not import"
                           % (script,)) from e


def _k1_answer(rec, walk, dt):
    """An ASK record's answer: exactly the Python the kernel stands in for
    (k1_fire_control.h), run on the live objects with the walk's offset."""
    query, args = rec[1], rec[2:-1]
    offset = walk.offset
    if query == "can_fire":
        return bool(walk.obj(args[0]).CanFire())
    if query == "fire":
        system, bank = walk.obj(args[0]), walk.obj(args[1])
        before = system._fired_counter(bank)
        result = bank.Fire(walk.obj(args[2]), offset)
        return bool(system._weapon_did_fire(bank, result, before))
    if query == "retry":
        # try_fire_weapon's retry loop; its `weapon._target = None` came in
        # the write log.
        system, bank = walk.obj(args[0]), walk.obj(args[1])
        for entry in list(system._target_list):
            if entry is None or (hasattr(entry, "IsDead") and entry.IsDead()):
                continue
            before = system._fired_counter(bank)
            result = bank.Fire(entry, offset)
            if system._weapon_did_fire(bank, result, before):
                return True
        return False
    if query == "is_dead":
        entry = walk.obj(args[0])
        return bool(hasattr(entry, "IsDead") and entry.IsDead())
    if query == "is_member":
        return bool(walk.obj(args[0]).IsMemberOfGroup(args[1]))
    if query == "is_dumb":
        # update_weapons' `weapon.IsDumbFire()` (GetNumTargets() == 0 already
        # held), for a weapon whose row an effect's handler dropped.
        return bool(walk.obj(args[0]).IsDumbFire())
    if query == "group_step":
        # One pass of update_weapons' delta loop body; the kernel does the
        # success bookkeeping itself.
        system, idx, group = walk.obj(args[0]), args[1], args[2]
        target = walk.obj(args[3])
        weapon = system.GetWeapon(idx)
        if weapon is None or not weapon.IsMemberOfGroup(group):
            return 0
        walk.pin(weapon)
        if system.try_fire_weapon(weapon, dt, target, offset):
            return 1
        weapon._target = None
        if system.GetNumTargets() == 0 and weapon.IsDumbFire():
            weapon.FireDumb(0, 1)
        return 2
    if query == "reseed":
        walk.obj(args[0])._reseed_all_fire_timers()
        return None
    raise RuntimeError("combat K1: unknown ASK %r" % (query,))


def run_k1(dt, ships=(), pump_body=None, system=None) -> None:
    """Drive the kernel's top session (begun by k1_pump / k1_system) until
    DONE. Each record: apply its writes, then act -- the Fire effect, a
    StopFiring, the FIRE_FAILED post, the dumb fire, the walk's offset, a
    whole system in Python, or an ASK answered in Python. `ships` and
    `pump_body(ship, getter_index)` serve a pump's RUN_PYTHON, `system` a
    system session's. On any exception the session is abandoned (the
    kernel's mirror still equals Python) and the exception re-raised; the
    walked system's row dropped by a handler mid-walk (the kernel cannot
    follow it) re-raises as a RuntimeError naming that invariant."""
    (DONE, WALK_START, STOP_SYSTEM, RUN_PYTHON, BANK_STOP, FIRE,
     FIRE_FAILED, FIRE_DUMB, ASK) = _k1_kinds()
    walk = _K1Walk()
    walked = None
    if system is not None:
        walk.pin_system(system)
    try:
        while True:
            try:
                rec = _h.combat_k1_next()
            except (ValueError, RuntimeError) as e:
                if walked is not None and "_nslot" not in walked.__dict__:
                    # k1_fire_control.h, PROTOCOL INVARIANT: no Python
                    # resume point exists mid-update_weapons.
                    raise RuntimeError(
                        "combat K1: the walked system %r's mirror row was "
                        "dropped mid-walk (a value it cannot encode); K1 "
                        "cannot follow it (protocol invariant, "
                        "k1_fire_control.h)" % (walked.GetName(),)) from e
                raise
            kind = rec[0]
            writes = rec[-1]
            if writes:
                apply_writes(writes, walk)
            if kind == FIRE:
                bank = walk.obj(rec[1])
                bank._fire_effect(walk.obj(rec[2]), walk.offset,
                                  _k1_decision(bank, rec[3], walk))
            elif kind == WALK_START:
                # update_weapons' `offset = self._live_held_offset()`, once
                # per walk; every effect and "walk_offset" write of this walk
                # uses this very object (ruling P5).
                walked = walk.obj(rec[1])
                if walk.walk_start(walked):
                    # An instance-patched method: Python runs the walk whole
                    # (the gates already ran), the kernel writes nothing more
                    # for this system.
                    walked.update_weapons(dt)
                    _h.combat_k1_skip_walk()
                    continue
                walk.offset = offset = walked._live_held_offset()
                _h.combat_k1_set_offset(
                    (offset.x, offset.y, offset.z)
                    if isinstance(offset, TGPoint3) else None)
                continue
            elif kind == BANK_STOP or kind == STOP_SYSTEM:
                walk.obj(rec[1]).StopFiring()
            elif kind == FIRE_FAILED:
                walk.obj(rec[1])._broadcast_weapon_fire_failed()
            elif kind == FIRE_DUMB:
                walk.obj(rec[1]).FireDumb(0, 1)
            elif kind == RUN_PYTHON:
                if rec[2] >= 0:
                    pump_body(ships[rec[2]], rec[3])
                else:
                    system.update_weapons(dt)
            elif kind == ASK:
                _h.combat_k1_answer(_k1_answer(rec, walk, dt))
            elif kind == DONE:
                break
            else:
                raise RuntimeError("combat K1: unknown record %r" % (rec,))
            if walked is not None:
                walk.pin_system(walked)     # what the effect's handlers left
        _h.combat_k1_end()
    except BaseException:
        _h.combat_k1_abandon()
        raise


def k1_pump(ships, dt, pump_body) -> None:
    """host_loop._pump_held_weapons(ships, dt) through K1. `ships` is a
    list; a ship with no Object row is passed as -1, and the kernel hands
    each of its getters back (RUN_PYTHON) to `pump_body(ship, getter)`."""
    _k1_recheck_overrides()
    if _pulse_stale:            # a mission swap's reset, before GameLoop.tick
        refresh_stale_pulse_params()
    handles = []
    for ship in ships:
        h = slot(ship)
        handles.append(REF_NONE if h is None else h)
    t, use_memo, drift = _k1_clocks()
    _h.combat_k1_begin_pump(handles, dt, t, use_memo, drift)
    run_k1(dt, ships=ships, pump_body=pump_body)


def k1_system(system, dt) -> None:
    """WeaponSystem.StartFiring's immediate update_weapons(dt) through K1.
    A system with no Subsystem row runs its Python update_weapons, as the
    kernel's RUN_PYTHON would."""
    h = system.__dict__.get("_nslot")
    if h is None or (h >> _KIND_SHIFT) != _kind("Subsystem"):
        system.update_weapons(dt)
        return
    _k1_recheck_overrides()
    if _pulse_stale:            # a mission swap's reset, before GameLoop.tick
        refresh_stale_pulse_params()
    t, use_memo, drift = _k1_clocks()
    _h.combat_k1_begin_system(h, dt, t, use_memo, drift)
    run_k1(dt, system=system)


# ── K2: the native beam kernel's driver (phase 2) ───────────────────────────
#
# native/src/combat/include/dauntless/combat/k2_beams.h is the contract. The
# kernel walks host_loop's `cb.phasers` loop (host_loop._phaser_step_ship)
# over the mirror and returns ONE record per combat_k2_next(); run_k2 applies
# the record's write log (the `_dwell` writes the kernel already made in the
# mirror), then does the one thing only Python may do: a StopFiring, a
# contact's effect (host_loop._phaser_contact: beam_contact or apply_hit, the
# damage arithmetic included), a whole ship or one bank of the loop body, or
# the answer to a question. After each it re-sends the per-step context the
# effect may have changed (_K2Context.resend).
#
# WHAT K2 STANDS IN FOR. The kernel computes, from the mirror, what these
# Python functions and methods would answer. A test, tool or mod that
# replaces one must still be obeyed, so the entry (k2_phasers) compares each
# against its import-time snapshot (k2_snapshot_stock, taken when host_loop
# finishes defining the loop) and runs the WHOLE step in Python on any
# difference:
#   module functions  _K2_FUNCTIONS (and host_io._h: the real bindings or
#                     None; anything else is a test double the trace must
#                     go through);
#   stock classes     _K2_ROLES: every name of a role, resolved on its stock
#                     class (a patch on PhaserBank, ShipClass, ... itself or
#                     a base).
# A CLASS WITH A ROW whose role name resolves to a method defined outside the
# engine package (a mod's subclass, a test's patch), or to anything but what
# it resolved to when K2 first saw the class (_k2_flag): a bank or phaser
# system class overriding only its own names -> its ship runs in Python (ctx
# python_ships, RUN_PYTHON "overridden"); anything else (a ship, a target, a
# shield, a cloak, a locked subsystem) -> the whole step (it can be any
# bank's target). The engine's own classes override one another freely
# (DamageableObject adds IsDead): the kernel ports those. Flags are cached
# per class and re-checked at every entry (the K1 watch, _k1_overridden).
# An INSTANCE attribute shadowing a method the loop calls by name on the
# walked ship, its phaser system or a bank (_K2_*_PATCHES) -> that ship runs
# in Python. (One on a TARGET is not looked for: it would cost a dict probe
# of every target, every tick.)

_k2_kind_ids = None
_k2_hl = None
_k2_cheats = None

#: (module, names) the kernel stands in for; host_loop's are the names its
#: loop body calls (its own imports of the helpers included).
_K2_FUNCTIONS = (
    ("engine.host_io", ("ray_trace_mesh",)),
    ("engine.appc.combat", ("_resolve_hit_point", "ray_sphere_entry",
                            "shields_block", "shield_bubble_entry",
                            "cloak_shields_suspended", "_hull_box_for",
                            "_body_frame_delta")),
    ("engine.appc.collisions", ("world_radius",)),
    ("engine.host_loop", ("_phaser_aim_point", "_phaser_step_ship",
                          "_phaser_step_bank", "can_detect", "_same_set",
                          "_emitter_in_arc", "_resolve_bank_aim_world",
                          "_is_offline")),
    ("engine.systems.frames", ("view_offset", "shifted", "containing_set")),
    ("engine.appc.subsystems", ("subsystem_world_position",
                                "target_offset_world", "_is_offline")),
    ("engine.appc.weapon_subsystems", ("_resolve_bank_aim_world",
                                       "_emitter_in_arc", "_same_set")),
    ("engine.appc.sensor_detection", ("can_detect",)),
)

_K2_SUBSYSTEM_NAMES = ("GetWorldLocation", "GetPosition", "_climb_to_ship")
_K2_OBJECT_NAMES = ("IsDead", "GetWorldLocation", "GetWorldRotation",
                    "GetContainingSet", "GetScale", "GetRadius", "GetShields")
#: role -> (module, stock class name, the names it stands in for), in
#: isinstance order (a bank is a WeaponSystem, not a PhaserSystem).
_K2_ROLES = (
    ("bank", "engine.appc.weapon_subsystems", "PhaserBank",
     _K2_SUBSYSTEM_NAMES + (
         "IsFiring", "IsBeamOn", "take_dwell", "accumulate_dwell",
         "_strip_emit_position", "_emitter_world_position", "GetLength",
         "GetDirection", "GetUp", "GetArcWidthAngles", "GetArcHeightAngles",
         "IsDisabled", "IsDestroyed")),
    ("system", "engine.appc.weapon_subsystems", "PhaserSystem",
     _K2_SUBSYSTEM_NAMES + (
         "GetNumWeapons", "GetWeapon", "GetNumChildSubsystems",
         "GetChildSubsystem", "IsOn", "IsDisabled", "IsDestroyed")),
    ("shield", "engine.appc.subsystems", "ShieldSubsystem",
     _K2_SUBSYSTEM_NAMES + ("HasShields", "IsOn", "IsDisabled",
                            "IsDestroyed")),
    ("cloak", "engine.appc.subsystems", "CloakingSubsystem",
     _K2_SUBSYSTEM_NAMES + ("IsCloaking", "IsDecloaking")),
    ("subsystem", "engine.appc.subsystems", "ShipSubsystem",
     _K2_SUBSYSTEM_NAMES),
    ("ship", "engine.appc.ships", "ShipClass",
     _K2_OBJECT_NAMES + ("GetPhaserSystem", "GetTargetSubsystem",
                         "is_using_target_offset", "GetTargetOffsetTG",
                         "GetCloakingSubsystem")),
    ("object", "engine.appc.objects", "ObjectClass", _K2_OBJECT_NAMES),
)
_K2_NAMES = {role: names for role, _m, _c, names in _K2_ROLES}
# The INSTANCE attributes looked for on the walked ship, its phaser system and
# each bank: the methods the loop calls on them by name. A narrower set than
# the class check's (a dict probe per bank per tick is the cost: ~90 ns).
_K2_SHIP_PATCHES = frozenset((
    "GetPhaserSystem", "GetTargetSubsystem", "is_using_target_offset",
    "GetTargetOffsetTG", "GetShields", "IsDead", "GetWorldLocation",
    "GetWorldRotation"))
_K2_SYSTEM_PATCHES = frozenset((
    "GetNumWeapons", "GetWeapon", "IsOn", "IsDisabled", "IsDestroyed"))
_K2_BANK_PATCHES = frozenset((
    "IsFiring", "IsBeamOn", "take_dwell", "accumulate_dwell",
    "_strip_emit_position", "_emitter_world_position", "GetLength"))

# The snapshot (k2_snapshot_stock): [(module, getter, values), ...] for the
# functions; [(role, stock class, resolution), ...] for the classes; the
# host_io._h it saw. None until taken: K2 never runs before it.
_k2_fn_snapshot = None
_k2_role_snapshot = None
_k2_stock_by_role = {}
_k2_host = None
_k2_host_io = None
_k2_stock_bank = None
_k2_stock_system = None
# class -> (overridden, whole, resolution): a class's flags (_k2_flag) and
# its role's names as K2 first saw them resolve (re-checked at every entry).
_k2_flags: dict = {}
# Classes with a row, in first-registration order (register, reclassify),
# and the ones with a role as _k2_unchanged re-checks them (rebuilt when
# _k2_seen grows: _k2_watch_seen[0] is the length it was built at).
_k2_seen: list = []
_k2_seen_set: set = set()
_k2_watch: list = []
_k2_watch_seen = [-1]
# [ship_instances, its version, _k2_drop_epoch, the iids table built on them]
_k2_iids_cache = [None, -1, -1, None]
_k2_drop_epoch = 0


def _k2_resolution(cls, names) -> tuple:
    """(getter of the names `cls` has, their values, the names it lacks):
    what `_k2_same` compares later."""
    present = [n for n in names if getattr(cls, n, None) is not None]
    missing = tuple(n for n in names if getattr(cls, n, None) is None)
    if not present:
        return (lambda _c: (), (), missing)
    getter = operator.attrgetter(*present)
    values = getter(cls)
    if len(present) == 1:
        values = (values,)
        one = getter
        getter = lambda c, _g=one: (_g(c),)  # noqa: E731
    return (getter, values, missing)


def _k2_same(cls, res) -> bool:
    getter, values, missing = res
    try:
        # A tuple compare: identity first, and a function equals only
        # itself, so this is "every name resolves to the same object".
        if getter(cls) != values:
            return False
    except AttributeError:          # a present name was deleted
        return False
    for n in missing:
        if getattr(cls, n, None) is not None:
            return False
    return True


def k2_snapshot_stock(host_loop_module) -> None:
    """Called by host_loop once it has defined the `cb.phasers` loop body:
    snapshot every function and stock-class method K2 stands in for, before
    any test, tool or mod can replace one."""
    global _k2_fn_snapshot, _k2_role_snapshot, _k2_host, _k2_host_io
    global _k2_hl, _k2_cheats, _k2_stock_bank, _k2_stock_system
    import importlib
    snap = []
    for module, names in _K2_FUNCTIONS:
        mod = (host_loop_module if module == "engine.host_loop"
               else importlib.import_module(module))
        getter = operator.attrgetter(*names)
        values = getter(mod)
        if len(names) == 1:
            values = (values,)
        snap.append((mod, names, values))
    _k2_fn_snapshot = snap
    roles = []
    _k2_stock_by_role.clear()
    for role, module, clsname, names in _K2_ROLES:
        cls = getattr(importlib.import_module(module), clsname)
        _k2_stock_by_role[role] = (cls, _k2_resolution(cls, names))
        roles.append((role, cls, _k2_stock_by_role[role][1]))
    _k2_role_snapshot = roles
    _k2_stock_bank = _k2_stock_by_role["bank"][0]
    _k2_stock_system = _k2_stock_by_role["system"][0]
    from engine import host_io
    import engine.dev_combat_cheats as cheats
    _k2_host_io, _k2_host = host_io, host_io._h
    _k2_hl, _k2_cheats = host_loop_module, cheats
    _k2_flags.clear()
    _k2_watch_seen[0] = -1


def _k2_role_of(cls):
    for role, _m, _c, _n in _K2_ROLES:
        if issubclass(cls, _k2_stock_by_role[role][0]):
            return role
    return None


def _k2_foreign(value) -> bool:
    """A resolved method that is not the engine's own: defined outside the
    engine package (a test's patch, a tool's, a mod's subclass)."""
    if value is None:
        return False
    module = getattr(value, "__module__", None)
    return not (isinstance(module, str)
                and (module == "engine" or module.startswith("engine.")))


def _k2_flag(cls) -> tuple:
    """(overridden, whole) for `cls`, a class with a row (or a walked bank's
    or system's): does a name of its role resolve to a method from outside
    the engine package, or to anything other than what it resolved to when
    K2 first saw the class (a patch since)? And must that send the WHOLE
    step to Python? A bank or phaser system class overriding only its own
    names concerns only its ship (whole False); one overriding a subsystem
    name (it can be a locked target), and any other class (a ship, a
    target, a shield, a cloak, a locked subsystem), concerns every bank.

    The engine's own classes override one another freely (DamageableObject
    adds IsDead, WeaponSystem aggregates IsDisabled): the kernel ports
    those, and its class flags (has_real_is_dead, ...) say which applies."""
    hit = _k2_flags.get(cls)
    if hit is None:
        role = _k2_role_of(cls)
        if role is None:
            hit = _k2_flags[cls] = (False, False, None)
        else:
            names = _K2_NAMES[role]
            foreign = [n for n in names
                       if _k2_foreign(getattr(cls, n, None))]
            over = bool(foreign)
            if role in ("bank", "system"):
                whole = any(n in _K2_SUBSYSTEM_NAMES for n in foreign)
            else:
                whole = over
            hit = _k2_flags[cls] = (over, whole,
                                    _k2_resolution(cls, names))
    if hit[2] is not None and not _k2_same(cls, hit[2]):
        return True, True               # patched since K2 first saw it
    return hit[0], hit[1]


def _k2_unchanged() -> bool:
    """Every stood-in function and every stock class as snapshotted, no
    class seen with a row flagged "whole" or patched since K2 first saw it
    (_k2_flag), and host_io._h the bindings or None. The whole-step check:
    one attrgetter per module and per class with a role."""
    for mod, names, values in _k2_fn_snapshot:
        try:
            now = operator.attrgetter(*names)(mod)
        except AttributeError:
            return False
        if len(names) == 1:
            now = (now,)
        if now != values:
            return False
    for _role, cls, res in _k2_role_snapshot:
        if not _k2_same(cls, res):
            return False
    if len(_k2_seen) != _k2_watch_seen[0]:
        _k2_rebuild_watch()
    for cls, res, whole in _k2_watch:
        if whole or not _k2_same(cls, res):
            return False
    h = _k2_host_io._h
    return h is None or h is _k2_host


def _k2_rebuild_watch() -> None:
    """The seen classes with a role, with their first-sight resolution and
    whole flag (a new class registered since the last entry)."""
    watch = []
    for cls in _k2_seen:
        _k2_flag(cls)
        _over, whole, res = _k2_flags[cls]
        if res is not None:
            watch.append((cls, res, whole))
    _k2_watch[:] = watch
    _k2_watch_seen[0] = len(_k2_seen)


def _k2_kinds() -> tuple:
    global _k2_kind_ids
    if _k2_kind_ids is None:
        k = _h.combat_k2_kinds()
        _k2_kind_ids = tuple(k[n] for n in (
            "DONE", "SYSTEM_STOP", "BANK_STOP", "CONTACT", "RUN_PYTHON",
            "ASK"))
    return _k2_kind_ids


def _k2_unseen(cls) -> int:
    """0 when K2 has seen `cls` (an object of it registered or was
    reclassified, so its row's class flags are its own and _k2_unchanged
    watches it); else 2 when it is flagged "whole" (_k2_flag), else 1: a
    class swapped in under a row (`obj.__class__ = ...` without reclassify)
    left that row's class flags stale."""
    if cls in _k2_seen_set:
        return 0
    return 2 if _k2_flag(cls)[1] else 1


def _k2_python_ship(ship) -> int:
    """0: K2 may walk `ship`'s phaser step; 1: its ship must run in Python
    (an instance attribute shadowing a stood-in name on it, its phaser
    system or a bank, a bank or system class overriding one of its own
    names, or the ship's class or a bank's target's class one K2 never
    saw); 2: the whole step must (a bank or system class overriding a
    subsystem name, or a never-seen class flagged "whole"). k2_phasers
    inlines the common case (stock classes, no instance attribute, seen
    classes) and calls this for the rest."""
    d = ship.__dict__
    why = _k2_unseen(type(ship))
    if why == 2:
        return 2
    if not d.keys().isdisjoint(_K2_SHIP_PATCHES):
        why = 1
    sys_ = d.get("_phaser_system")
    if sys_ is None:
        return why
    if type(sys_) is not _k2_stock_system:
        over, whole = _k2_flag(type(sys_))
        if whole:
            return 2
        if over:
            why = 1
    sd = getattr(sys_, "__dict__", None)
    if sd is None:
        return why
    if not sd.keys().isdisjoint(_K2_SYSTEM_PATCHES):
        why = 1
    for b in sd.get("_children", ()):
        if type(b) is not _k2_stock_bank:
            over, whole = _k2_flag(type(b))
            if whole:
                return 2
            if over:
                why = 1
        bd = getattr(b, "__dict__", None)
        if bd is None:
            continue
        if not bd.keys().isdisjoint(_K2_BANK_PATCHES):
            why = 1
        target = bd.get("_target")
        if target is not None:
            unseen = _k2_unseen(type(target))
            if unseen == 2:
                return 2
            why = max(why, unseen)
    return why


def _k2_ship_handles(ships):
    """(handles, python_ships, whole) for begin: each ship's Object handle
    (-1: no row), the ships _k2_python_ship sends to Python, and whether one
    sends the whole step. The common case -- a stock phaser system of stock
    banks, no instance attribute -- is decided inline: this loop runs every
    tick over every bank (~90 ns a bank)."""
    handles = []
    python_ships = []
    obj_kind = _kind("Object")
    stock_sys, stock_bank = _k2_stock_system, _k2_stock_bank
    ship_patches, sys_patches, bank_patches = (
        _K2_SHIP_PATCHES, _K2_SYSTEM_PATCHES, _K2_BANK_PATCHES)
    seen = _k2_seen_set
    for ship in ships:
        d = getattr(ship, "__dict__", None)
        h = d.get("_nslot") if d is not None else None
        if h is None or (h >> _KIND_SHIFT) != obj_kind:
            handles.append(REF_NONE)
            continue
        handles.append(h)
        sys_ = d.get("_phaser_system")
        clean = type(ship) in seen and d.keys().isdisjoint(ship_patches)
        if clean and sys_ is not None:
            if type(sys_) is stock_sys:
                sd = sys_.__dict__
                clean = sd.keys().isdisjoint(sys_patches)
                if clean:
                    for b in sd.get("_children", ()):
                        if type(b) is not stock_bank:
                            clean = False
                            break
                        bd = b.__dict__
                        target = bd.get("_target")
                        if not bd.keys().isdisjoint(bank_patches) or (
                                target is not None
                                and type(target) not in seen):
                            clean = False
                            break
            else:
                clean = False
        if not clean:
            why = _k2_python_ship(ship)
            if why == 2:
                return handles, python_ships, True
            if why == 1:
                python_ships.append(h)
    return handles, python_ships, False


class _K2Walk(_K1Walk):
    """run_k2's pin set (k2_beams.h, PINNING): every object a record or an
    ASK names, plus, before a bank's StopFiring, the objects the Python
    loop holds in its locals for that bank -- its target and its system --
    so a handle the kernel still carries maps back even if the StopFiring's
    side effects drop the last other reference."""

    __slots__ = ()

    def pin_bank(self, bank) -> None:
        self.pin(bank)
        d = bank.__dict__
        for ref in (d.get("_target"), d.get("_parent_subsystem")):
            if ref is not None:
                self.pin(ref)


def _k2_player_handle() -> int:
    """combat.shields_block's player, as a handle (-1: None, or an object
    with no Object row, which never equals a walked target's)."""
    import App
    try:
        game = (App.Game_GetCurrentGame()
                if hasattr(App, "Game_GetCurrentGame") else None)
        player = (game.GetPlayer()
                  if game is not None and hasattr(game, "GetPlayer")
                  else None)
    except Exception:
        player = None
    h = slot(player) if player is not None else None
    return REF_NONE if h is None else h


def _k2_iids(ship_instances) -> dict:
    """{Object handle: iid} for a TrackedInstances, cached on (the map, its
    version, the drop epoch): a key's handle changes only through _drop."""
    c = _k2_iids_cache
    if c[0] is ship_instances and c[1] == ship_instances.version \
            and c[2] == _k2_drop_epoch:
        return c[3]
    table = {}
    for ship, iid in ship_instances.items():
        h = slot(ship)
        if h is not None:
            table[h] = iid
    c[:] = [ship_instances, ship_instances.version, _k2_drop_epoch, table]
    return table


_UNSET = object()


class _K2Context:
    """The per-step context the kernel cannot read from the mirror
    (k2_beams.h, K2Context): what was sent, so `resend` sends only what an
    effect changed. Cheap when nothing did: an int compare, the cheat flag
    (and the player only while it is on), and the viewing set only while
    some ship has an instance (no instance: the kernel never asks for a
    view offset)."""

    __slots__ = ("instances", "version", "iids", "cheat", "player", "view",
                 "asked_shields")

    def __init__(self, ship_instances) -> None:
        self.instances = ship_instances
        self.version = -1
        self.iids = None
        self.cheat = None
        self.player = None
        self.view = _UNSET
        self.asked_shields = False

    def delta(self) -> dict:
        d = {}
        si = self.instances
        if si is not None and si.version != self.version:
            self.version = si.version
            self.iids = _k2_iids(si)
            d["iids"] = self.iids
        cheat = bool(_k2_cheats.disable_npc_shields_active())
        player = _k2_player_handle() if cheat else REF_NONE
        if cheat != self.cheat or player != self.player:
            self.cheat, self.player = cheat, player
            d["npc_shields_off"] = cheat
            d["player"] = player
        if self.iids:
            from engine.systems import frames
            view = frames.viewing_set()
            if view is not self.view:
                self.view = view
                h = _slot_of(view) if view is not None else None
                d["view_offsets"] = (
                    {} if h is None or (h >> _KIND_SHIFT) != _kind("Set")
                    else {h: frames.view_offset(view)})
        return d

    def resend(self) -> None:
        d = self.delta()
        if d:
            _h.combat_k2_set_ctx(d)


def _k2_points(emitter_xyz, target_xyz, impact_xyz, normal_xyz, tier,
               bubble_xyz) -> tuple:
    """A CONTACT's points as the Python loop held them: (emitter_pos,
    target_pos, impact_point, impact_normal, bubble_entry). The impact IS
    target_pos on the "fallback" tier and IS emitter_pos on the "origin"
    tier (combat._resolve_hit_point / ray_sphere_entry return the very
    object they were given); the mesh and sphere tiers made their own."""
    emitter = TGPoint3(*emitter_xyz)
    target_pos = TGPoint3(*target_xyz)
    if tier == "fallback":
        point = target_pos
    elif tier == "origin":
        point = emitter
    else:
        point = TGPoint3(*impact_xyz)
    normal = None if normal_xyz is None else TGPoint3(*normal_xyz)
    bubble = None if bubble_xyz is None else TGPoint3(*bubble_xyz)
    return emitter, target_pos, point, normal, bubble


def _k2_contact(rec, walk, cx, dt, ship_instances) -> None:
    """A CONTACT record: host_loop._phaser_contact on the rebuilt points,
    the power level read from the loop's own system. The loop's
    shields_block answer rides along unless the loop never evaluated it
    (None: no aim direction) or Python answered it (an ASK): beam_contact
    then evaluates its own, as the Python path does."""
    (_k, bh, th, sh, yh, emitter, target_pos, dist, _aim, impact, normal,
     tier, bubble, shields, flush, _writes) = rec
    bank, target, ship, sys_ = (walk.obj(bh), walk.obj(th), walk.obj(sh),
                                walk.obj(yh))
    _e, _t, point, n, b = _k2_points(emitter, target_pos, impact, normal,
                                     tier, bubble)
    hl = _k2_hl
    level = hl._phaser_level(sys_)
    if shields is None or cx.asked_shields:
        hl._phaser_contact(ship, sys_, bank, target, dist, dt, flush, level,
                           point, n, b, ship_instances)
    else:
        hl._phaser_contact(ship, sys_, bank, target, dist, dt, flush, level,
                           point, n, b, ship_instances, shields_block=shields)


def _k2_answer(rec, walk, cx, dt, ship_instances):
    """An ASK record's answer: exactly the Python the kernel stands in for
    (k2_beams.h, the ASK table), on the live objects."""
    query, args = rec[1], rec[2:-1]
    if query == "is_dead":
        target = walk.obj(args[0])
        return bool(hasattr(target, "IsDead") and target.IsDead())
    if query == "can_detect":
        # sensor_detection.can_detect's own fallback after its native call
        # raised ValueError (re-calling can_detect would re-run the native
        # call and its latch write).
        from engine.appc import sensor_detection
        _counts["fallbacks"] += 1
        return bool(sensor_detection._py_can_detect(walk.obj(args[0]),
                                                    walk.obj(args[1])))
    if query == "aim_point":
        p, sub = _k2_hl._phaser_aim_point(walk.obj(args[0]),
                                          walk.obj(args[1]))
        return ((p.x, p.y, p.z), sub is not None)
    from engine.appc import combat
    if query == "shields_block":
        cx.asked_shields = True
        return bool(combat.shields_block(walk.obj(args[0])))
    if query == "bubble":
        p = combat.shield_bubble_entry(walk.obj(args[0]), TGPoint3(*args[1]),
                                       TGPoint3(*args[2]), args[3])
        return None if p is None else (p.x, p.y, p.z)
    if query == "resolve_hit":
        target = walk.obj(args[0])
        origin = TGPoint3(*args[1])
        fallback = TGPoint3(*args[4])
        direction = None if args[2] is None else TGPoint3(*args[2])
        p, n = combat._resolve_hit_point(
            ship_instances=ship_instances, ship=target, ray_origin=origin,
            ray_direction=direction, max_dist=args[3],
            fallback_point=fallback)
        tier = ("origin" if p is origin else "fallback" if p is fallback
                else "mesh" if n is not None else "sphere")
        return ((p.x, p.y, p.z),
                None if n is None else (n.x, n.y, n.z), tier)
    if query == "bank_step":
        _k2_hl._phaser_step_bank(walk.obj(args[0]), walk.obj(args[1]),
                                 args[2], dt, ship_instances)
        return None
    raise RuntimeError("combat K2: unknown ASK %r" % (query,))


def run_k2(ships, dt, ship_instances, cx) -> None:
    """Drive the open K2 session until DONE. Each record: apply its writes,
    then act -- a StopFiring, a contact's effect, a whole ship in Python, or
    an ASK answered in Python -- then re-send whatever context the Python
    changed. On any exception the session is abandoned (the kernel's mirror
    still equals Python) and the exception re-raised; the kernel's own
    protocol-invariant RuntimeError (k2_beams.h) included."""
    DONE, SYSTEM_STOP, BANK_STOP, CONTACT, RUN_PYTHON, ASK = _k2_kinds()
    walk = _K2Walk()
    try:
        while True:
            rec = _h.combat_k2_next()
            kind = rec[0]
            writes = rec[-1]
            if writes:
                apply_writes(writes, walk)
            if kind == ASK:
                _h.combat_k2_answer(_k2_answer(rec, walk, cx, dt,
                                               ship_instances))
            elif kind == CONTACT:
                _k2_contact(rec, walk, cx, dt, ship_instances)
                cx.asked_shields = False
            elif kind == BANK_STOP:
                bank = walk.obj(rec[1])
                walk.pin_bank(bank)
                bank.StopFiring()
                cx.asked_shields = False
            elif kind == SYSTEM_STOP:
                walk.obj(rec[1]).StopFiring()
                cx.asked_shields = False
            elif kind == RUN_PYTHON:
                _k2_hl._phaser_step_ship(ships[rec[2]], dt, ship_instances)
                cx.asked_shields = False
            elif kind == DONE:
                break
            else:
                raise RuntimeError("combat K2: unknown record %r" % (rec,))
            cx.resend()
        _h.combat_k2_end()
    except BaseException:
        _h.combat_k2_abandon()
        raise


def _k2_step_fallback(ship_instances):
    """Why this `cb.phasers` step must run whole in Python, or None."""
    if _k2_fn_snapshot is None or _h.combat_k2_open():
        return "nested"
    if ship_instances is not None \
            and type(ship_instances) is not _tracked_instances():
        return "instances"
    if not _k2_unchanged():
        return "patched"
    return None


_tracked_cls = None


def _tracked_instances():
    global _tracked_cls
    if _tracked_cls is None:
        from engine.core.tracked_instances import TrackedInstances
        _tracked_cls = TrackedInstances
    return _tracked_cls


def k2_phasers(ships, dt, ship_instances) -> bool:
    """host_loop's `cb.phasers` step through K2: True when it ran, False when
    the caller must run the step in Python whole (counted by why in
    counts()["k2_python_step_reasons"])."""
    why = _k2_step_fallback(ship_instances)
    if why is None:
        handles, python_ships, whole = _k2_ship_handles(ships)
        if whole:
            why = "patched"
    if why is not None:
        _k2_steps["k2_python_steps"] += 1
        _k2_step_reasons[why] += 1
        return False
    if _pulse_stale:            # a mission swap's reset, before GameLoop.tick
        refresh_stale_pulse_params()
    cx = _K2Context(ship_instances)
    ctx = cx.delta()
    ctx["python_ships"] = python_ships
    ctx["trace"] = _k2_host_io._h is not None
    t, use_memo, drift = _k1_clocks()
    _h.combat_k2_begin(handles, dt, t, use_memo, drift, ctx)
    run_k2(ships, dt, ship_instances, cx)
    return True

if available():
    # step_memo.forget() (every hit, the step's forget points, the outermost
    # block's exit) empties the native memo with the Python tables.
    from engine.core import step_memo as _step_memo
    _step_memo.on_forget(_h.combat_memo_clear)
