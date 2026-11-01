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
REF_UNREPRESENTABLE, and an object hiding a scalar gets no row. Torpedoes are
mirrored instead by their own TABLE, kept in ``projectiles._active`` order
(the K3 section below: ``TorpedoField``, ``torpedo_row_add``).

Rows live exactly as long as their Python object: ``register`` in
``__init__``, unregistered by the object's ``weakref.finalize``. Objects are
registered whenever the bindings are built, even with the switch off; nothing
is PUSHED while it is off, and turning it on resyncs every row.

The switch is read only in ``configure()`` (called by ``GameLoop.__init__``):
``DAUNTLESS_NATIVE_COMBAT=1`` on, ``=0`` or unset off;
``DAUNTLESS_NATIVE_AUDIT=1`` turns the audit on and implies native on.
"""
import importlib
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
# function or class K2 stands in for differs from its snapshot), "audit"
# (DAUNTLESS_NATIVE_AUDIT=1: the kernel's can_detect would bypass the audit).
_k2_steps = {"k2_python_steps": 0}
_K2_STEP_REASONS = ("nested", "instances", "patched", "audit")
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
    # The phase-3 bindings too (the torpedo table, the step scan, K4 and the
    # K3 kernel): a .so older than any of them is stale.
    return (_h is not None and hasattr(_h, "combat_register")
            and hasattr(_h, "combat_torp_add")
            and hasattr(_h, "combat_step_scan")
            and hasattr(_h, "combat_step_serial")
            and hasattr(_h, "combat_k4_eligible")
            and hasattr(_h, "combat_k3_begin")
            and hasattr(_h, "combat_set_part_poses"))


def configure(environ: Mapping[str, str] = os.environ) -> None:
    global _enabled, _audit
    audit = environ.get("DAUNTLESS_NATIVE_AUDIT") == "1"
    want = (audit or environ.get("DAUNTLESS_NATIVE_COMBAT") == "1") \
        and available()
    # The audit is on only when native ended up on: auditing rows that were
    # never pushed would record every field of every row, every tick.
    _audit = False
    if not want:
        if _enabled:
            torpedo_table_mark_dirty()  # unpushed from here on: drop it
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
    # The part-map generation is NOT reset: it is monotonic for the process,
    # so a slot stamped before the reset can never read fresh again.
    _forget_part_caches()
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
    _k2_iids_sent[:] = [_K2_UNSENT, -1, -1]
    global _k2_drop_epoch
    _k2_drop_epoch += 1
    torpedo_table_mark_dirty()
    global _step
    _step = None
    for k in _K4_REASONS:
        _k4_reasons[k] = 0
    for k in _K3_REASONS:
        _k3_reasons[k] = 0
    _k3_iids_sent[:] = [_K2_UNSENT, -1, -1]
    # K3's class watch re-baselines with K2's (a watch built while a class
    # was patched must not outlive the patch).
    _k3_watch.clear()
    _k3_watch_seen[0] = -1
    if available():
        _h.combat_k1_reset_counts()
        _h.combat_k2_reset_counts()
        _h.combat_k4_reset_counts()
        if _h.combat_k3_open():
            _h.combat_k3_abandon()
        _h.combat_k3_reset_counts()
        _h.combat_step_reset()


def counts() -> dict:
    """Since the last reset(): {"native_calls": n, "fallbacks": n} for the
    dispatched sensor queries, and the K1 kernel's {"k1_records": n,
    "k1_python_systems": n, "k1_asks": n} (records returned, RUN_PYTHON
    hand-backs, ASKs answered by Python; counted by the kernel), plus
    "k1_python_reasons": {"pump": {...}, "system": {...}} -- the
    k1_python_systems hand-backs by K1Why name (k1_fire_control.h:
    part_stale, overridden, instance_patch, ...; every reason, zeros
    included), for the held-weapon pump and StartFiring apart --
    "k1_fire_ask_reasons" ({K1Why name: n}: the Fire decisions handed to
    Python, ASK fire -- part_stale, mount_unknown, no_mount,
    offset_off_mount, other) and
    "k1_posed" ({"walks", "target_aims"}: systems of a posed ship walked
    natively, Fire decisions aimed natively at a posed target's offset) and
    "k1_logged" ({"walk_start"}: walks started with no WALK_START record,
    their offset computed by the kernel -- round trips Task 1; k1_records
    counts only the records returned, so a walk start the walk check hands
    back is a WALK_START record there instead).
    posed_ship / posed_target are retired reasons, always 0 (posed parts
    run natively; spec 2026-11-01 §4.5). In k1_python_reasons,
    mount_unknown / no_mount / offset_off_mount are always 0 too: the
    pre-scan never hands a system back for a posed target's offset, which
    is decided in the walk -- those three are counted in
    k1_fire_ask_reasons only.

    K2 (`cb.phasers`): the kernel's {"k2_records", "k2_python_ships",
    "k2_asks", "k2_python_reasons": {K2Why name: n}, "k2_ask_queries":
    {query: n}, "k2_posed": {"banks", "lock_aims", "manual_aims"}}
    (k2_beams.h; posed_ship retired, part_stale its successor), plus
    "k2_python_steps" (steps run whole in Python) and
    "k2_python_step_reasons" ({"nested", "instances", "patched", "audit"}:
    n).

    K4 (`cb.eligibility`): "k4_runs" (calls the kernel decided) and
    "k4_python_reasons" ({why: n}, the kernel's hand-backs -- scan, player,
    nonfinite, frame, set -- summed with k4_update's own: audit, patched,
    the step scan's reasons, ...).

    K3 (`cb.projectiles`): the kernel's {"k3_runs", "k3_records",
    "k3_asks": {query: n}, "k3_guide_reasons": {why: n},
    "k3_steer_reasons": {why: n} (the steer_point ASKs: unattributed,
    part_stale, unbaked, ...; projectile_geometry.h SteerWhy, zeros
    included; no_mount is 0 since a picked spot steers at its launch-time
    `_baked_offset`), "k3_posed_steers": n (a posed target's mount or
    picked spot steered natively), "k3_baked_steers": n (of those, a picked
    spot at its baked point)}, and
    "k3_python_steps" / "k3_python_reasons" ({why: n}): the steps run whole
    in Python, the kernel's begin reasons (scan, table, unrepresentable,
    stale_ref, torpedo_xform, ship_cache) summed with run_k3's own (off,
    audit, plain_active, scan, patched, row, guard, instances)."""
    c = dict(_counts)
    c.update(_k2_steps)
    c["k2_python_step_reasons"] = dict(_k2_step_reasons)
    if available():
        c.update(_h.combat_k1_counts())
        c.update(_h.combat_k2_counts())
        k4 = _h.combat_k4_counts()
        why = k4["k4_python_reasons"]
        for k, n in _k4_reasons.items():
            why[k] = why.get(k, 0) + n
        c.update(k4)
        k3 = _h.combat_k3_counts()
        why = k3["k3_python_reasons"]
        for k, n in _k3_reasons.items():
            why[k] = why.get(k, 0) + n
            k3["k3_python_steps"] += n
        c.update(k3)
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


class PartKeyField(NativeField):
    """A subsystem attribute the part-slot resolution reads (``_position``:
    `part_for_mount` keys on the mount point): a write pushes like any
    NativeField and bumps the part-map generation, so every slot resolved
    before it reads stale (spec 2026-11-01 §4.3)."""

    def __set__(self, obj, value) -> None:
        NativeField.__set__(self, obj, value)
        bump_part_gen()


class PartKeyRefField(NativeRefField):
    """``ShipSubsystem._property``: `physical_parents.property_of(sub)`
    reads it, so a write bumps the part-map generation (PartKeyField)."""

    def __set__(self, obj, value) -> None:
        NativeRefField.__set__(self, obj, value)
        bump_part_gen()


class MountSlotField:
    """A ship's top-level subsystem slot (`ShipClass.GetSubsystems`) that is
    not otherwise mirrored: a write re-pushes the ship's mount order
    (`push_mount_order`). Like WakeField: no __get__, reads stay plain
    instance-dict reads."""

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __set__(self, obj, value) -> None:
        d = obj.__dict__
        old = d.get(self._name)
        d[self._name] = value
        if _enabled and old is not value:
            push_mount_order(obj)


class NativeMountRefField(NativeRefField):
    """A mirrored subsystem slot of the ship (`_hull`, `_phaser_system`,
    ...): pushes its ref, then the ship's mount order (MountSlotField)."""

    def __set__(self, obj, value) -> None:
        old = obj.__dict__.get(self._name)
        NativeRefField.__set__(self, obj, value)
        if _enabled and old is not value:
            push_mount_order(obj)


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
        h = _h.combat_register(_kind(kind), xi, xg, obj.GetObjID(), id(obj))
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


def forget_rows() -> None:
    """Test isolation, after a combat_clear(): every C++ row is gone, so
    every handle Python holds is stale. Forget them all at once. Left to
    discover it one push at a time, each stale object drops itself, re-pushes
    its referrers and rescans the registry -- a cascade quadratic in the
    objects earlier tests left alive (minutes in a full suite). The end state
    is the same: every such object takes the Python path. Generations bump on
    clear, so their finalizers cannot free a later row.

    The classes K2 has seen go too: with no row left, none has been seen. A
    test-defined class (non-engine code, flagged "whole") kept there sent
    every later test's K2/K3/K4 steps to Python as "patched"."""
    for obj in list(_registry.values()):
        obj.__dict__.pop("_nslot", None)
    _registry.clear()
    _forget_part_caches()
    bump_part_gen()     # the cleared mirror's generation is back at 1
    torpedo_table_mark_dirty()
    _k2_seen.clear()
    _k2_seen_set.clear()
    _k2_watch_seen[0] = -1


def unregister_handle(h: int) -> None:
    """Finalizer body: never raises (a combat_clear may have freed it)."""
    _forget_part_caches(h)
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
    "GetParentShip", "_fired_counter", "_weapon_did_fire",
    "_live_held_offset")
# Checked on the INSTANCE (its __dict__) at each walk start, for the walked
# system and each child: the cheap subset that tests and tools patch. Made by
# the bindings' walk check (k1_walk_check, host_bindings.cc), which hands a
# walk start with one back to Python as a WALK_START record (walk_start).
_K1_SYSTEM_PATCHES = ("update_weapons", "try_fire_weapon",
                      "_live_held_offset")
_K1_LEAF_PATCHES = ("Fire", "_fire_decide", "_fire_effect", "CanFire")
# The firing ship's side of the walk offset (_live_held_offset's probe and
# its Manual Aim branch), which the kernel computes from the mirror: an
# instance attribute shadowing one, or a class resolving them to anything
# but the stock ShipClass's (k1_snapshot_ship), hands the walk start back
# too, and Python's own _live_held_offset answers it.
_K1_SHIP_PATCHES = ("is_using_target_offset", "GetTargetOffsetTG")
# (ShipClass, its raw MRO entries of _K1_SHIP_PATCHES) as ships.py defined
# them, and whether the walk check was sent to the bindings.
_k1_ship_stock = None
_k1_walk_check_sent = False
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


def _k1_raw(cls, name):
    """`name`'s entry in the first class of `cls`'s MRO that defines it (what
    CPython's _PyType_Lookup returns, the walk check's comparison), or None."""
    for klass in cls.__mro__:
        d = vars(klass)
        if name in d:
            return d[name]
    return None


def k1_snapshot_ship(ship_class) -> None:
    """ships.py, as it finishes defining ShipClass: snapshot the raw
    is_using_target_offset / GetTargetOffsetTG the walk check accepts as
    stock, before any test, tool or mod can patch one."""
    global _k1_ship_stock, _k1_walk_check_sent
    _k1_ship_stock = (ship_class, tuple(_k1_raw(ship_class, n)
                                        for n in _K1_SHIP_PATCHES))
    _k1_walk_check_sent = False


def _k1_send_walk_check() -> None:
    """Install the bindings' walk check (k1_fire_control.h, THE WALK START)
    once: the registry it maps handles through and the names it looks for."""
    global _k1_walk_check_sent
    cls, (iu, gto) = _k1_ship_stock if _k1_ship_stock is not None \
        else (None, (None, None))
    _h.combat_k1_set_walk_check(_registry.data, _K1_SYSTEM_PATCHES,
                                _K1_LEAF_PATCHES, _K1_SHIP_PATCHES,
                                iu, gto, cls)
    _k1_walk_check_sent = True


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
    Mid-transition, swung for cruise, or SPV-forced off identity reads 1:
    the kernels then read its pose table and its subsystems' part slots
    (posed parts, Task 4), and a slot that is not current falls back to
    Python (part_stale).

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
    """Re-push the ship's has_posed_parts flag (`_posed_flag`) and its pose
    table (`_push_pose_table`): its pose dict was rebound (PosedPartsField),
    tick_ship moved a part in place, SetupProperties just gave it a script,
    or a part was severed / the severed parts were forgotten
    (part_severance: the table's detached bits, synchronously -- MAP R6).
    The flag reads only the current poses (never the rig), and those are
    the only places they change."""
    if _enabled:
        h = ship.__dict__.get("_nslot")
        if h is not None:
            flag = _posed_flag(ship)
            _call(ship, _h.combat_set_i, h, _fid("has_posed_parts"), flag)
            if "_nslot" in ship.__dict__:
                _push_pose_table(ship, h, flag)


# ── Posed parts: pose tables, part slots, mount order ────────────────────────
# Spec docs/superpowers/specs/2026-11-01-native-combat-posed-parts-design.md
# §4.1-4.3, map docs/reference/engine/native-combat/posed-parts-map.md §2-3.
#
# Python is the ONLY resolver of which part a mount sits on. Per ship it
# pushes the pose table (one entry per `articulation.posed_part_names` name,
# in that order; empty while has_posed_parts is 0) and the mount order (its
# subsystems in `combat._iter_subsystems` order); per subsystem the part
# slot, stamped with the global part-map generation at resolution.
#
# Every input of the resolution bumps the generation (`bump_part_gen`):
# SetPhysicalParent, the SPV preview overlay, a leaf's model or derived boxes
# learned, a rig snapshot, a subsystem's `_position` / `_property`, and a
# change of the table's names under resolved slots. A slot stamped with an
# older generation is "not resolved": the kernel falls back. So a missed
# trigger can only cost speed, never give a wrong part. The generation is
# monotonic for the process (never reset), and starts at 1 natively, so a
# never-resolved slot (stamp 0) is stale.

_part_gen = 1
# ship handle -> the posed_part_names its slots were last resolved against
_slot_names: dict = {}
# ship handle -> the _part_gen its slots were last resolved at
_resolved_gen: dict = {}


def part_gen() -> int:
    """The current part-map generation (what a fresh slot is stamped with)."""
    return _part_gen


def bump_part_gen() -> None:
    """An input of the part-slot resolution changed: every slot resolved so
    far reads stale. Pushed at once (a kernel may run before the next step
    boundary). Counted even while native is off -- nothing is pushed then,
    and turning it on bumps again (resync)."""
    global _part_gen
    _part_gen += 1
    if _enabled:
        _h.combat_set_part_gen(_part_gen)


def _forget_part_caches(h=None) -> None:
    if h is None:
        _slot_names.clear()
        _resolved_gen.clear()
        _manual_resolved.clear()
    else:
        _slot_names.pop(h, None)
        _resolved_gen.pop(h, None)
        _manual_resolved.pop(h, None)


def _leaf_known(ship):
    """The ship's hardpoint leaf if `articulation.leaf_for` already cached a
    non-empty one, else None. Never resolves it (MAP R5: on a ship whose
    script is not set yet, leaf_for would cache "" for good)."""
    leaf = ship.__dict__.get("_articulation_leaf")
    return leaf if isinstance(leaf, str) and leaf else None


def _pose_names(ship) -> tuple:
    """`articulation.posed_part_names(ship)` once the leaf is cached (it
    then never resolves it). Before that, the names the pose dict holds,
    sorted -- what posed_part_names gives for a rig-less leaf; no slot can
    have been resolved against them (resolution needs the leaf)."""
    if isinstance(ship.__dict__.get("_articulation_leaf"), str):
        from engine.appc import articulation
        return articulation.posed_part_names(ship)
    poses = ship.__dict__.get("_articulation_poses")
    return tuple(sorted(poses)) if poses else ()


def _pose_table(ship, names) -> list:
    """One (r9, t3, identity, detached) per name, read exactly as
    `articulation.pose_for_part` and `part_severance.is_detached` read
    them: a name with no entry in the dict is IDENTITY."""
    from engine.appc import part_pose
    poses = getattr(ship, "_articulation_poses", None) or {}
    detached = getattr(ship, "_parts_detached", None) or ()
    out = []
    for name in names:
        pose = poses.get(name, part_pose.IDENTITY)
        R, t = pose
        out.append((tuple(float(R[i][j]) for i in range(3) for j in range(3)),
                    (float(t[0]), float(t[1]), float(t[2])),
                    bool(part_pose.is_identity(pose)),
                    name in detached))
    return out


def _push_pose_table(ship, h, flag, names=None, drop=True) -> bool:
    """Push the pose table: empty while `flag` (has_posed_parts) is 0 --
    the kernel never reads it then. A non-empty table whose names differ
    from the ones the ship's slots were resolved against bumps the
    generation first (R11): those slots index another table. A table that
    cannot be encoded drops the ship's row -- unless `drop` is False (the
    mid-walk heal): then nothing is pushed. True when it was pushed."""
    if not flag:
        entries = []
    else:
        try:
            if names is None:
                names = _pose_names(ship)
            entries = _pose_table(ship, names)
        except (TypeError, ValueError, OverflowError, IndexError):
            if drop:
                _drop(ship)     # not representable: never leave a stale row
            return False
        prev = _slot_names.get(h)
        if prev is not None and prev != names:
            del _slot_names[h]
            bump_part_gen()
    _call(ship, _h.combat_set_part_poses, h, entries)
    return True


def _slot_subsystems(ship) -> list:
    """Every subsystem of `ship` a slot may be read for: its top-level
    subsystems (hull included) and their children, depth first."""
    try:
        top = list(ship.GetSubsystems())
    except Exception:  # noqa: BLE001 - not a ship with subsystems
        return []
    out, seen = [], set()
    stack = list(reversed(top))
    while stack:
        sub = stack.pop()
        if sub is None or id(sub) in seen:
            continue
        seen.add(id(sub))
        out.append(sub)
        children = sub.__dict__.get("_children") if hasattr(
            sub, "__dict__") else None
        if children:
            stack.extend(reversed(list(children)))
    return out


def _part_slot(leaf, names, sub):
    """The index in `names` of the part `articulation._live_part` resolves
    for `sub`'s own mount, by the same calls minus the detached test (the
    table's detached bit carries that); -1 for no posable part; None when
    the resolution raised (the slot is then left stale)."""
    from engine.appc import part_severance, physical_parents
    try:
        local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
        if not isinstance(local, TGPoint3):
            return -1
        point = (local.x, local.y, local.z)
        prop = physical_parents.property_of(sub)
        if prop is not None:
            name = physical_parents.part_for_property(leaf, prop, point)
        else:
            name = part_severance.part_for_mount(leaf, point)
    except Exception:  # noqa: BLE001 - Python answers it (and raises) itself
        return None
    if name is None or name not in names:
        return -1
    return names.index(name)


def resolve_part_slots(ship, drop=True) -> None:
    """Resolve and push the part slot of every subsystem of `ship`, stamped
    with the current generation, with the pose table built from the SAME
    `posed_part_names` call (R11). Only for a ship whose leaf is already
    cached (R5); an unrigged ship has no names and pushes no slot.

    `drop=False` (the mid-walk heal, _heal_part_slots) never drops the
    ship's row: a table it cannot encode is left as last pushed and the
    slots stay stale (the kernels' fallback), where a boundary would drop
    the row (the "unrepresentable" rule)."""
    if not _enabled:
        return
    h = ship.__dict__.get("_nslot")
    leaf = _leaf_known(ship)
    if h is None or leaf is None:
        return
    from engine.appc import articulation
    gen = _part_gen
    names = articulation.posed_part_names(ship)
    _slot_names[h] = names
    if not _push_pose_table(ship, h, _posed_flag(ship), names, drop):
        _slot_names.pop(h, None)
        return
    if ship.__dict__.get("_nslot") != h:
        return
    if names:
        sub_kind = _kind("Subsystem")
        for sub in _slot_subsystems(ship):
            sh = _slot_of(sub)
            if sh is None or (sh >> _KIND_SHIFT) != sub_kind:
                continue
            slot = _part_slot(leaf, names, sub)
            if slot is None:
                _call(sub, _h.combat_set_part_slot, sh, -1, 0)  # stale
            else:
                _call(sub, _h.combat_set_part_slot, sh, slot, gen)
    if _part_gen == gen:    # nothing bumped while resolving
        _resolved_gen[h] = gen


def resolve_stale_part_slots(ships, drop=True) -> None:
    """At a step boundary: resolve every ship of `ships` whose slots were
    resolved at an older generation (or never), and every Manual Aim slot
    whose (target, offset, generation) moved (Task 4b). `drop`: see
    resolve_part_slots."""
    if not _enabled:
        return
    for ship in ships:
        d = ship.__dict__
        h = d.get("_nslot")
        if h is None:
            continue
        if _resolved_gen.get(h) != _part_gen:
            resolve_part_slots(ship, drop)
        if d.get("_manual_target_offset") is not None \
                or h in _manual_resolved:
            _resolve_manual_slot(ship, h, drop)


def _heal_part_slots(ships, gen) -> None:
    """After Python answered a K2 ASK: if the answer moved the part-map
    generation (any trigger may fire in Python), re-resolve before the
    answer goes back, so the bank's GEOMETRY that follows -- which cannot
    fall back once its bank has a record (k2_beams.h protocol invariant) --
    reads freshly stamped slots. Never drops a row: the kernel is mid-walk
    over these objects. (K1 and K3 need none: a slot they read after an ASK
    falls back to another, counted ASK.)"""
    if _part_gen != gen:
        resolve_stale_part_slots(ships, drop=False)


# ── Manual Aim slots (posed parts, Task 4b) ──────────────────────────────────
#
# A Manual Aim pick is a NON-authored point: subsystems.target_offset_world
# attributes its part by the box rule (`articulation._live_part(target, None,
# offset, authored=False)` -> part_severance.part_for_point) on every call.
# Its answer depends only on the target's leaf, the offset and the leaf's part
# boxes / model -- every one an input the part-map generation already
# covers -- so Python resolves it ONCE per (target, offset, generation) and
# pushes it as the firing ship's Manual Aim slot. The kernels read it for an
# authored=False offset on a posed target only when its target and offset
# are exactly the ones asked about (and the stamp is current), so a pick
# moved or a target changed since the last boundary reads "no slot", never a
# wrong part. The target is `ship.GetTarget()` and the offset its
# `_manual_target_offset` (the value GetTargetOffsetTG copies under Manual
# Aim, and the walk's offset K1 stamps into its banks and K3's torpedoes).

#: ship handle -> (target handle, offset xyz, generation) last pushed
_manual_resolved: dict = {}


def _manual_slot(ship, drop=True, cached=None, gen=None):
    """(target, offset xyz, slot) of `ship`'s Manual Aim pick: the index of
    the part `_live_part(target, None, offset, authored=False)` resolves in
    the target's resolved names (-1: none), detachment ignored (the table's
    bit carries it). None when there is no pick, no target with a row, or a
    target whose leaf and names are not resolved (R5: never leaf_for).
    When `cached` (the last pushed key) already equals (target, offset, gen)
    the box rule is skipped and the slot is None: nothing to push."""
    off = ship.__dict__.get("_manual_target_offset")
    target = ship.__dict__.get("_target")
    if not isinstance(off, TGPoint3) or target is None:
        return None
    th = target.__dict__.get("_nslot") if hasattr(target, "__dict__") \
        else None
    leaf = _leaf_known(target) if th is not None else None
    if leaf is None:
        return None
    names = _slot_names.get(th)
    if names is None or _resolved_gen.get(th) != _part_gen:
        resolve_part_slots(target, drop)
        names = _slot_names.get(th)
        if names is None or target.__dict__.get("_nslot") != th:
            return None
    point = (off.x, off.y, off.z)
    if cached is not None and cached == (th, point, gen):
        return th, point, None
    from engine.appc import part_severance
    try:
        name = part_severance.part_for_point(leaf, point)
    except Exception:  # noqa: BLE001 - Python answers (and raises) itself
        return None
    slot = names.index(name) if name is not None and name in names else -1
    return th, point, slot


def _resolve_manual_slot(ship, h, drop=True) -> None:
    gen = _part_gen
    found = _manual_slot(ship, drop, _manual_resolved.get(h), gen)
    if found is None:
        if _manual_resolved.get(h, False) is not None:
            _manual_resolved[h] = None
            _call(ship, _h.combat_set_manual_slot, h, -1, (0.0, 0.0, 0.0),
                  -1, 0)
        return
    th, point, slot = found
    if slot is None:
        return
    key = (th, point, gen)
    _call(ship, _h.combat_set_manual_slot, h, th, point, slot, gen)
    _manual_resolved[h] = key if _part_gen == gen else None


def _mount_order(ship) -> list:
    """The ship's subsystems as `part_severance.authored_mount_subsystem`
    walks them (`_mounted_subsystems`: combat._iter_subsystems order), as
    Subsystem handles; -2 for one the mirror cannot name."""
    from engine.appc.part_severance import _mounted_subsystems
    sub_kind = _kind("Subsystem")
    out = []
    for sub, _mount in _mounted_subsystems(ship):
        t = _slot_of(sub)
        out.append(t if t is not None and (t >> _KIND_SHIFT) == sub_kind
                   else REF_UNREPRESENTABLE)
    return out


def push_mount_order(ship) -> None:
    """Push the ship's mount order: a subsystem slot of the ship was written
    (MountSlotField / NativeMountRefField) or a subsystem gained a child
    (ShipSubsystem.AddChildSubsystem). Also bumps the part-map generation:
    the subsystem attached may have come from another ship, and its slot,
    resolved against THAT ship's leaf and names, must not read fresh here.
    Its slots are re-resolved at the next step boundary."""
    if not _enabled:
        return
    h = ship.__dict__.get("_nslot")
    if h is None or (h >> _KIND_SHIFT) != _kind("Object"):
        return
    _call(ship, _h.combat_set_mount_order, h, _mount_order(ship))
    _resolved_gen.pop(h, None)
    bump_part_gen()


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
    try:
        flags = _flags(obj, h)
    except (TypeError, ValueError, OverflowError):
        _drop(obj)  # has_shields not representable: never leave a stale row
        return
    for name, v in flags.items():
        _call(obj, _h.combat_set_i, h, _fid(name), v)
    k = h >> _KIND_SHIFT
    if k == _kind("Object"):
        if flags.get("is_ship_class") and "_nslot" in obj.__dict__:
            _push_pose_table(obj, h, flags["has_posed_parts"])
    elif k == _kind("Property"):
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
    # K3: the guidance lead term.
    from engine.appc import projectiles
    g["LEAD_ACCEL_K"] = float(projectiles._LEAD_ACCEL_K)
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
    # Slots resolved before the switch went off are not trusted: the
    # generation moves on (and is pushed), and every ship re-resolves.
    _forget_part_caches()
    bump_part_gen()
    # Torpedoes in flight have no rows yet: K3 rebuilds the table first.
    torpedo_table_mark_dirty()
    rows = [(h, obj) for h, obj in list(_registry.items())
            if obj.__dict__.get("_nslot") == h]
    set_kind = _kind("Set")
    rows.sort(key=lambda row: (row[0] >> _KIND_SHIFT) != set_kind)
    for h, obj in rows:
        if obj.__dict__.get("_nslot") == h:
            _push_all(obj, h)
    from engine.appc.ships import ShipClass
    for h, obj in rows:
        if obj.__dict__.get("_nslot") == h and isinstance(obj, ShipClass):
            push_mount_order(obj)


# ── K3: the torpedo table ────────────────────────────────────────────────────
# One native row per in-flight torpedo, in projectiles._active order
# (torpedo_table.h). Torpedoes have no Object row (they hide `_radius` and
# `_containing_set` behind properties, _hidden_fields), so they are their own
# kind, synced at the _ActiveList hooks beside the TorpedoScan rows:
# torpedo_row_add at append, torpedo_row_drop at remove/pop, and every other
# list mutation marks the table dirty (torpedo_table_mark_dirty), which
# EMPTIES it until torpedo_table_rebuild re-reads `_active` from Python.
#
# A torpedo's row handle is `_k3_row` in its __dict__. Every field the kernel
# reads pushes while the torpedo has one: the plain fields through
# TorpedoField, `_velocity` / `_source_ship` / `_containing_set` from their
# Torpedo properties (push_torpedo_field). A value the row cannot hold sets
# the field's "unrepresentable" bit instead (the kernel hands such a torpedo
# to Python); a later good push clears it.

_k3_dirty = True
# handle -> torpedo, for every row in the table.
_k3_rows: dict = {}
# handle -> class, for every row whose torpedo is not of the stock Torpedo
# class (a mod's subclass): run_k3 checks those classes ("guard").
_k3_odd_rows: dict = {}
_k3_torpedo_cls = None
_torp_fids: dict = {}


class _Unrepresentable(Exception):
    pass


def _tfid(name: str) -> int:
    fid = _torp_fids.get(name)
    if fid is None:
        _torp_fids.update(_h.combat_torp_field_names())
        fid = _torp_fids[name]
    return fid


def _num(v) -> float:
    """A number Python's own arithmetic and compares treat as this double:
    a float, or an int / bool that converts exactly. Anything else (a str,
    None, a huge int) the row cannot hold."""
    if type(v) is float:
        return v
    if isinstance(v, (int, float)):
        try:
            f = float(v)
        except OverflowError:
            raise _Unrepresentable
        if f == v:
            return f
    raise _Unrepresentable


def _point(v) -> tuple:
    if not isinstance(v, TGPoint3):
        raise _Unrepresentable
    return (_num(v.x), _num(v.y), _num(v.z))


_NO_POINT = (0.0, 0.0, 0.0)


def _enc_velocity(t, v):
    return (True,) + _point(v)


def _enc_offset(t, v):
    """Read by `isinstance(v, TGPoint3)` (`_target_offset` in _steer_point,
    `_last_target_vel` in _guide): anything else is unset."""
    if isinstance(v, TGPoint3):
        return (True,) + _point(v)
    return (False,) + _NO_POINT


def _enc_none_or_point(t, v):
    """`_last_seen_target_pos`: _guide tests `is None`, then does point
    arithmetic on anything else, which only a TGPoint3 matches."""
    if v is None:
        return (False,) + _NO_POINT
    return (True,) + _point(v)


def _enc_ref(target):
    def enc(t, v):
        if v is None:
            return REF_NONE
        return _handle_of(v, target)
    return enc


def _enc_mount(t, key):
    """(attributed, subsystem ref, x, y, z). attributed is _steer_point's
    `key[0] is target` for the torpedo's CURRENT `_target_ship`."""
    if key is None:
        return (False, REF_NONE) + _NO_POINT
    try:
        target, x, y, z, sub = key
    except (TypeError, ValueError):
        raise _Unrepresentable
    sub_ref = REF_NONE if sub is None else _handle_of(sub, "Subsystem")
    return ((target is t.__dict__.get("_target_ship")), sub_ref,
            _num(x), _num(y), _num(z))


def _enc_baked(t, key):
    """(attributed, key x, y, z, baked x, y, z). attributed is
    _steer_point's `baked[0] is target` for the torpedo's CURRENT
    `_target_ship`."""
    if key is None:
        return (False,) + _NO_POINT + _NO_POINT
    try:
        target, x, y, z, (bx, by, bz) = key
    except (TypeError, ValueError):
        raise _Unrepresentable
    return ((target is t.__dict__.get("_target_ship")),
            _num(x), _num(y), _num(z), _num(bx), _num(by), _num(bz))


# Python attribute -> (encoder, row setter kind, combat_torp_dump key).
_TORP_FIELDS = {
    "_age": (lambda t, v: _num(v), "f", "age"),
    "_ttl": (lambda t, v: _num(v), "f", "ttl"),
    "_guidance_lifetime": (lambda t, v: _num(v), "f", "guidance_lifetime"),
    "_guidance_initial": (lambda t, v: _num(v), "f", "guidance_initial"),
    "_max_angular_accel": (lambda t, v: _num(v), "f", "max_angular_accel"),
    "_velocity": (_enc_velocity, "v", "vel"),
    "_target_offset": (_enc_offset, "v", "target_offset"),
    "_last_seen_target_pos": (_enc_none_or_point, "v", "last_seen"),
    "_last_target_vel": (_enc_offset, "v", "last_tvel"),
    "_target_ship": (_enc_ref("Object"), "r", "target"),
    "_source_ship": (_enc_ref("Object"), "r", "source"),
    "_containing_set": (_enc_ref("Set"), "r", "cset"),
    "_mount_key": (_enc_mount, "m", None),
    "_baked_offset": (_enc_baked, "b", None),
}
# The fields kept in the torpedo's __dict__ (TorpedoField); the other three
# are Torpedo properties over the `_vel` / `_src` / `_cset` slots.
_TORP_DICT_FIELDS = tuple(n for n in _TORP_FIELDS
                          if n not in ("_velocity", "_source_ship",
                                       "_containing_set"))


_UNSET_FIELD = object()


def _torp_value(t, name):
    """The Python value a field mirrors, or _UNSET_FIELD."""
    if name == "_velocity":
        return getattr(t, "_vel", None)
    if name == "_source_ship":
        return getattr(t, "_src", None)
    if name == "_containing_set":
        return getattr(t, "_cset", None)
    return t.__dict__.get(name, _UNSET_FIELD)


def _torp_live(h: int) -> bool:
    try:
        _h.combat_torp_dump(h)
    except ValueError:
        return False
    return True


def _torp_lost(t) -> None:
    """The torpedo's row is gone under it (a combat_clear): it has no row,
    and the table no longer matches the list."""
    h = t.__dict__.pop("_k3_row", None)
    if _k3_rows.get(h) is t:
        del _k3_rows[h]
        _k3_odd_rows.pop(h, None)
    torpedo_table_mark_dirty()


def _torp_push(t, h, name, value) -> None:
    enc, how, _ = _TORP_FIELDS[name]
    fid = _tfid(name)
    try:
        v = enc(t, value)
    except _Unrepresentable:
        try:
            _h.combat_torp_set_unrepresentable(h, fid)
        except ValueError:
            _torp_lost(t)
        return
    try:
        if how == "f":
            _h.combat_torp_set_f(h, fid, v)
        elif how == "v":
            _h.combat_torp_set_v(h, fid, *v)
        elif how == "r":
            _torp_push_ref(t, h, fid, value, v)
        elif how == "b":
            _h.combat_torp_set_baked(h, *v)
        else:
            _torp_push_mount(t, h, value, v)
    except ValueError:
        _torp_lost(t)
        return
    if name == "_target_ship":
        # `_mount_key`'s and `_baked_offset`'s attributed flags are
        # `key[0] is _target_ship`.
        _torp_push(t, h, "_mount_key", t.__dict__.get("_mount_key"))
        _torp_push(t, h, "_baked_offset", t.__dict__.get("_baked_offset"))


def _torp_push_ref(t, h, fid, value, ref) -> None:
    try:
        _h.combat_torp_set_ref(h, fid, ref)
    except ValueError:
        if ref < 0 or not _torp_live(h):
            raise
        _drop(value)            # the referent's handle is the stale one
        _h.combat_torp_set_ref(h, fid, REF_UNREPRESENTABLE)


def _torp_push_mount(t, h, key, v) -> None:
    try:
        _h.combat_torp_set_mount(h, *v)
    except ValueError:
        if v[1] < 0 or not _torp_live(h):
            raise
        _drop(key[4])
        _h.combat_torp_set_mount(h, v[0], REF_UNREPRESENTABLE, *v[2:])


class TorpedoField:
    """A Torpedo attribute the K3 kernel reads: like NativeField (no
    __get__, the value lives in the instance dict) but pushed into the
    torpedo's TABLE row, `_k3_row`. Switch off: one __set__ and a global
    read.

    With no __get__, reading a field never set on the instance returns
    this descriptor object (the class attribute) instead of raising
    AttributeError. Torpedo.__init__ sets all ten, so a real
    torpedo never reads one unset; code that hasattr/getattr-probes a
    half-built torpedo must not rely on AttributeError."""

    __slots__ = ("_name",)

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __set__(self, obj, value) -> None:
        d = obj.__dict__
        d[self._name] = value
        if _enabled:
            h = d.get("_k3_row")
            if h is not None:
                _torp_push(obj, h, self._name, value)


def push_torpedo_field(t, name: str, value) -> None:
    """A Torpedo property (`_velocity`, `_source_ship`, `_containing_set`)
    was written: push it if the torpedo has a row. Callers test `_enabled`
    first, so the switch-off cost is that read."""
    h = t.__dict__.get("_k3_row")
    if h is not None:
        _torp_push(t, h, name, value)


def _torp_put(t) -> None:
    xi, xg = t.__dict__.get("_xform", (-1, -1))
    h = _h.combat_torp_add(xi, xg)
    t.__dict__["_k3_row"] = h
    _k3_rows[h] = t
    if type(t) is not _k3_torpedo_cls:
        _k3_odd_rows[h] = type(t)
    for name in _TORP_FIELDS:
        value = _torp_value(t, name)
        if value is not _UNSET_FIELD and t.__dict__.get("_k3_row") == h:
            _torp_push(t, h, name, value)


def torpedo_row_add(t) -> None:
    """`_active.append(t)`: a row at the end, unless the table is dirty (the
    rebuild will include it) or `t` already has one (appended twice: the
    list now holds it twice, so the table is rebuilt)."""
    if not _enabled or _k3_dirty:
        return
    h = t.__dict__.get("_k3_row")
    if h is not None and _k3_rows.get(h) is t:
        torpedo_table_mark_dirty()
        return
    _torp_put(t)


def torpedo_row_drop(t) -> None:
    """`_active.remove(t)` / `pop`: drop its row."""
    d = getattr(t, "__dict__", None)
    if d is None:
        return
    h = d.pop("_k3_row", None)
    if h is None:
        return
    if _k3_rows.get(h) is t:
        del _k3_rows[h]
        _k3_odd_rows.pop(h, None)
        _h.combat_torp_drop(h)


def torpedo_table_mark_dirty() -> None:
    """`_active` changed in a way the rows cannot follow one at a time:
    empty the table; torpedo_table_rebuild refills it in list order."""
    global _k3_dirty
    if _k3_dirty and not _k3_rows:
        return          # already empty (always so with the switch off)
    _k3_dirty = True
    for t in _k3_rows.values():
        t.__dict__.pop("_k3_row", None)
    _k3_rows.clear()
    _k3_odd_rows.clear()
    if available():
        _h.combat_torp_clear()


def torpedo_table_rebuild(active) -> None:
    """Refill the table from `active` (projectiles._active), in list order.
    A no-op with the switch off. A torpedo in the list TWICE (update_all
    advances it twice a tick) leaves the table dirty and empty: one row
    cannot stand for it, so K3 hands the step to Python until it is gone."""
    global _k3_dirty
    if not _enabled:
        return
    torpedo_table_mark_dirty()
    from engine.appc.projectiles import Torpedo
    torps, seen = [], set()
    for t in active:
        if isinstance(t, Torpedo):
            if id(t) in seen:
                return
            seen.add(id(t))
            torps.append(t)
    _k3_dirty = False
    for t in torps:
        _torp_put(t)


def _audit_torpedoes() -> None:
    """Every torpedo row against its Python object, and (when the table is
    not dirty) the row order against `_active`."""
    proj = sys.modules.get("engine.appc.projectiles")
    if proj is None:
        return
    torps, seen = [], set()
    for t in proj._active:
        if isinstance(t, proj.Torpedo) and id(t) not in seen:
            seen.add(id(t))
            torps.append(t)
    if not _k3_dirty and list(_h.combat_torp_handles()) != [
            t.__dict__.get("_k3_row") for t in torps]:
        _failures.append(("Torpedo", "order"))
    for t in torps:
        h = t.__dict__.get("_k3_row")
        if h is None:
            continue
        try:
            row = _h.combat_torp_dump(h)
        except ValueError:
            _failures.append(("Torpedo", "row"))
            continue
        for name, (enc, how, key) in _TORP_FIELDS.items():
            value = _torp_value(t, name)
            if value is _UNSET_FIELD:
                continue
            try:
                want = enc(t, value)
            except _Unrepresentable:
                if name not in row["unrepresentable"]:
                    _failures.append(("Torpedo", name))
                continue
            if name in row["unrepresentable"] or \
                    not _torp_matches(how, key, want, row):
                _failures.append(("Torpedo", name))


def _torp_matches(how, key, want, row) -> bool:
    if how == "f":
        return want.hex() == float(row[key]).hex()
    if how == "r":
        return want == row[key]
    if how == "v":
        got = row[key]
        if not want[0]:
            return got is None
        return got is not None and _hexes(got) == _hexes(want[1:])
    if how == "b":
        return (int(want[0]), _hexes(want[1:4]), _hexes(want[4:])) == (
            row["baked_attributed"], _hexes(row["baked_key"]),
            _hexes(row["baked"]))
    return (int(want[0]), want[1], _hexes(want[2:])) == (
        row["mount_attributed"], row["mount_sub"],
        _hexes(row["mount_offset"]))


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
        try:
            expected = dict(_flags(obj, h))
        except (TypeError, ValueError, OverflowError):
            _failures.append((name, "has_shields"))
            continue
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
        if (h >> _KIND_SHIFT) == _kind("Object") and row["py_id"] != id(obj):
            _failures.append((name, "py_id"))
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
        elif (h >> _KIND_SHIFT) == _kind("Object"):
            if expected.get("is_ship_class"):
                _audit_posed(obj, row, name, expected["has_posed_parts"])
        elif (h >> _KIND_SHIFT) == _kind("Subsystem"):
            _audit_slot(obj, row, name)
    _audit_torpedoes()
    _audit_globals()
    if _h.combat_part_gen() != _part_gen:
        _failures.append(("globals", "part_gen"))


def _pose_rows(entries) -> list:
    return [(_hexes(r), _hexes(t), bool(i), bool(d))
            for r, t, i, d in entries]


def _audit_posed(ship, row, name, flag) -> None:
    """The pose table (MAP R10: a tick_ship that raised mid-loop leaves its
    in-place writes unpushed) and the mount order."""
    try:
        want = (_pose_table(ship, _pose_names(ship)) if flag else [])
    except (TypeError, ValueError, OverflowError, IndexError):
        _failures.append((name, "part_poses"))
    else:
        if _pose_rows(want) != _pose_rows(row["part_poses"]):
            _failures.append((name, "part_poses"))
    if row["mount_order"] != _mount_order(ship):
        _failures.append((name, "mount_order"))
    _audit_manual_slot(ship, row, name)


def _audit_manual_slot(ship, row, name) -> None:
    """A Manual Aim slot stamped with the current generation, for a target
    whose names are resolved, must name the part the box rule gives for its
    own (target, offset) now. A stale stamp, or a pick moved since, is never
    read (the kernel compares target and offset)."""
    th, offset, slot, gen = row["manual_slot"]
    if th == -1 or gen != _part_gen:
        return
    target = _registry.get(th)
    leaf = _leaf_known(target) if target is not None else None
    names = _slot_names.get(th)
    if leaf is None or names is None:
        return
    from engine.appc import part_severance
    try:
        found = part_severance.part_for_point(leaf, tuple(offset))
    except Exception:  # noqa: BLE001
        _failures.append((name, "manual_slot"))
        return
    want = names.index(found) if found is not None and found in names else -1
    if want != slot:
        _failures.append((name, "manual_slot"))


def _audit_slot(sub, row, name) -> None:
    """A slot stamped with the current generation must name the part Python
    resolves now, as an index into the owning ship's current table. A stale
    stamp is never read, and neither is any slot of a ship whose table is
    empty (has_posed_parts 0)."""
    if row["part_gen"] != _part_gen:
        return
    ship = sub._climb_to_ship() if hasattr(type(sub), "_climb_to_ship") \
        else None
    if ship is None or _slot_of(ship) is None or not _posed_flag(ship):
        return
    leaf = _leaf_known(ship)
    if leaf is None or _part_slot(leaf, _pose_names(ship), sub) \
            != row["part_slot"]:
        _failures.append((name, "part_slot"))


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
    PINNING) -- and the materialised walk: its number in the session, its
    system and its offset object."""

    __slots__ = ("pins", "offset", "walk", "walked")

    def __init__(self) -> None:
        self.pins = {}
        self.offset = None
        self.walk = None
        self.walked = None

    def materialise(self, n, h):
        """THE hook for "this walk's Python side" (round trips, ruling D5):
        the walk numbered `n` in this session, of the system with handle
        `h`. The kernel started it with no record (k1_fire_control.h, THE
        WALK START); the first Python that reaches it calls this -- run_k1
        on the walk's first record, before that record's own Python, and
        apply_writes on a logged write naming the walk's offset
        (("walk_offset", n, h)), whichever comes first. Once per walk:
        pins the walk (pin_system) and fetches update_weapons' `offset =
        self._live_held_offset()` -- today's walk-start Python, in today's
        order, later but with no Python in between. Returns the offset
        object (ruling P5: every effect and stamp of the walk uses it)."""
        if self.walk == n:
            return self.offset
        system = self.obj(h)
        self.pin_system(system)
        self.offset = system._live_held_offset()
        self.walk = n
        self.walked = system
        return self.offset

    def pin(self, obj) -> None:
        d = getattr(obj, "__dict__", None)
        h = d.get("_nslot") if d is not None else None
        if h is not None:
            self.pins[h] = obj

    def pin_system(self, system) -> None:
        """The walked system, its children and its target list as they are
        now (materialise, and after each later record)."""
        self.pin(system)
        d = system.__dict__
        for child in d.get("_children", ()):
            self.pin(child)
        for target in d.get("_target_list", ()):
            self.pin(target)

    def walk_start(self, system) -> bool:
        """pin_system at a handed-back WALK_START (the walk check found an
        instance attribute or a ship class it cannot stand in for), plus the
        instance-patch check: True when the system or a child has an
        instance attribute shadowing a method K1 stands in for (`tube.Fire =
        ...`); K1 must not decide for it. A patch made later in the walk (by
        a handler) is not seen."""
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
    (-1: None), a ref list a list of handles; the marker ("walk_offset",
    walk, system) is that walk's own offset object (_K1Walk.materialise:
    the first write naming a walk not yet materialised fetches it). `walk`
    maps handles through its pin set; without one, through the registry.

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
        elif type(value) is tuple:          # ("walk_offset", walk, system)
            value = walk.materialise(value[1], value[2])
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
    DONE. Each record: apply its writes, materialise the walk on its first
    record (_K1Walk.materialise), then act -- the Fire effect, a StopFiring,
    the FIRE_FAILED post, the dumb fire, a handed-back walk start, a whole
    system in Python, or an ASK answered in Python. `ships` and
    `pump_body(ship, getter_index)` serve a pump's RUN_PYTHON, `system` a
    system session's. On any exception the session is abandoned (the
    kernel's mirror still equals Python) and the exception re-raised; the
    walked system's row dropped by a handler mid-walk (the kernel cannot
    follow it) re-raises as a RuntimeError naming that invariant."""
    (DONE, WALK_START, STOP_SYSTEM, RUN_PYTHON, BANK_STOP, FIRE,
     FIRE_FAILED, FIRE_DUMB, ASK) = _k1_kinds()
    walk = _K1Walk()
    if system is not None:
        walk.pin_system(system)
    try:
        while True:
            try:
                rec = _h.combat_k1_next()
            except (ValueError, RuntimeError) as e:
                walked = walk.walked
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
            tag = rec[-2]
            if kind == WALK_START:
                # A walk start the walk check handed back (an instance
                # attribute or a ship class it cannot stand in for):
                # update_weapons' `offset = self._live_held_offset()` here,
                # Python's own; every effect and "walk_offset" write of this
                # walk uses this very object (ruling P5).
                walk.walked = walked = walk.obj(rec[1])
                if walk.walk_start(walked):
                    # An instance-patched method: Python runs the walk whole
                    # (the gates already ran), the kernel writes nothing more
                    # for this system.
                    walked.update_weapons(dt)
                    _h.combat_k1_skip_walk()
                    continue
                walk.offset = offset = walked._live_held_offset()
                walk.walk = tag[0]
                _h.combat_k1_set_offset(
                    (offset.x, offset.y, offset.z)
                    if isinstance(offset, TGPoint3) else None)
                continue
            if tag is not None:
                # The walk's first record: its Python side before any of
                # the record's own (Review Focus 1).
                walk.materialise(tag[0], tag[1])
            if kind == FIRE:
                bank = walk.obj(rec[1])
                bank._fire_effect(walk.obj(rec[2]), walk.offset,
                                  _k1_decision(bank, rec[3], walk))
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
                # No heal here (cf. run_k2): every K1 slot read after an ASK
                # is inside a Fire decision, whose PartStale is an ASK fire.
                _h.combat_k1_answer(_k1_answer(rec, walk, dt))
            elif kind == DONE:
                break
            else:
                raise RuntimeError("combat K1: unknown record %r" % (rec,))
            if walk.walked is not None:
                walk.pin_system(walk.walked)    # what the handlers left
        _h.combat_k1_end()
    except BaseException:
        _h.combat_k1_abandon()
        raise


def k1_pump(ships, dt, pump_body) -> None:
    """host_loop._pump_held_weapons(ships, dt) through K1. `ships` is a
    list; a ship with no Object row is passed as -1, and the kernel hands
    each of its getters back (RUN_PYTHON) to `pump_body(ship, getter)`."""
    if not _k1_walk_check_sent:
        _k1_send_walk_check()
    _k1_recheck_overrides()
    if _pulse_stale:            # a mission swap's reset, before GameLoop.tick
        refresh_stale_pulse_params()
    # A step boundary: every slot the walk reads is fresh (the torpedo hits,
    # deaths and damage before the pump may have bumped the generation).
    resolve_stale_part_slots(ships)
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
    if not _k1_walk_check_sent:
        _k1_send_walk_check()
    _k1_recheck_overrides()
    if _pulse_stale:            # a mission swap's reset, before GameLoop.tick
        refresh_stale_pulse_params()
    # A step boundary (StartFiring runs inside gl.ai, an effect's handler,
    # ...): the walk reads the parent ship's slots and, aiming at a posed
    # target's offset, the target's.
    resolve_stale_part_slots(_k1_system_ships(system))
    t, use_memo, drift = _k1_clocks()
    _h.combat_k1_begin_system(h, dt, t, use_memo, drift)
    run_k1(dt, system=system)


def _k1_system_ships(system) -> list:
    """The ships a system session's walk may read part slots of: the
    parent ship and every entry of the system's target list."""
    ship = system.GetParentShip()
    ships = [] if ship is None else [ship]
    for t in system.__dict__.get("_target_list") or ():
        if t is not None and hasattr(t, "__dict__"):
            ships.append(t)
    return ships


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
# the class check's (a dict probe per name per bank per tick, in the binding:
# combat_k2_scan_ships, ~85 ns a bank in a Debug build).
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
# The key of the iids table the kernel holds (it keeps it across sessions):
# [ship_instances or None, version, drop epoch]; _K2_UNSENT before any.
_K2_UNSENT = object()
_k2_iids_sent = [_K2_UNSENT, -1, -1]


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
    if not _k2_classes_unchanged():
        return False
    h = _k2_host_io._h
    return h is None or h is _k2_host


def _k2_classes_unchanged() -> bool:
    """The class half of _k2_unchanged (the K3/K4 step scan shares it):
    every stock role class as snapshotted, and no class seen with a row
    flagged "whole" or patched since K2 first saw it."""
    for _role, cls, res in _k2_role_snapshot:
        if not _k2_same(cls, res):
            return False
    if len(_k2_seen) != _k2_watch_seen[0]:
        _k2_rebuild_watch()
    for cls, res, whole in _k2_watch:
        if whole or not _k2_same(cls, res):
            return False
    return True


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
    """0 when K2 has seen `cls` (some object of it registered or was
    reclassified, so _k2_unchanged watches the class); else 2 when it is
    flagged "whole" (_k2_flag), else 1: a class swapped in under a row
    (`obj.__class__ = ...` without reclassify) left that row's class flags
    stale.

    PER CLASS, not per row: once any object of `cls` has been seen, a row
    whose object was swapped to `cls` without reclassify reads 0 here and
    keeps its OLD class's flags, undetected. Swapping a class under a row
    needs reclassify (the rocks call it: engine/rocks/rock.py)."""
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
    banks, no instance attribute, seen classes -- is decided in the binding
    (combat_k2_scan_ships, a C loop over the instance dicts: this runs every
    tick over every bank); only the ships it could not call clean come back
    here, in order, for _k2_python_ship."""
    handles, unclean = _h.combat_k2_scan_ships(
        ships, _kind("Object"), _KIND_SHIFT, _k2_seen_set,
        _k2_stock_system, _k2_stock_bank, _K2_SHIP_PATCHES,
        _K2_SYSTEM_PATCHES, _K2_BANK_PATCHES)
    python_ships = []
    for ship, h in unclean:
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
                 "asked_shields", "staged", "sent")

    def __init__(self, ship_instances, sent=None) -> None:
        # The key of the iids table the kernel holds: K2's (_k2_iids_sent),
        # or K3's own (_k3_iids_sent): each kernel keeps its own table.
        self.sent = _k2_iids_sent if sent is None else sent
        self.instances = ship_instances
        self.version = -1
        self.iids = None
        self.cheat = None
        self.player = None
        self.view = _UNSET
        self.asked_shields = False
        self.staged = None

    def delta(self) -> dict:
        """The context keys to send. "iids" only when the table's key
        differs from the one the kernel holds (`sent`): the caller commits
        the staged key once the kernel took it (commit)."""
        d = {}
        si = self.instances
        if si is not None:
            if si.version != self.version:
                self.version = si.version
                self.iids = _k2_iids(si)
                c, sent = _k2_iids_cache, self.sent
                if (sent[0] is not c[0] or sent[1] != c[1]
                        or sent[2] != c[2]):
                    d["iids"] = self.iids
                    self.staged = c[:3]
        elif self.sent[0] is not None:
            d["iids"] = {}
            self.staged = [None, -1, -1]
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

    def commit(self) -> None:
        """The kernel took the last delta: its table's key is the staged one."""
        if self.staged is not None:
            self.sent[:] = self.staged
            self.staged = None

    def resend(self) -> None:
        d = self.delta()
        if d:
            _h.combat_k2_set_ctx(d)
            self.commit()


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
                gen = _part_gen
                answer = _k2_answer(rec, walk, cx, dt, ship_instances)
                _heal_part_slots(ships, gen)
                _h.combat_k2_answer(answer)
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
    # The audit compares every can_detect's native and Python answers
    # (sensor_detection._audit_can_detect); the kernel's own can_detect would
    # bypass it, so the audited step is Python's.
    if _audit:
        return "audit"
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
    # A step boundary: the K1 pump's effects may have bumped the generation.
    resolve_stale_part_slots(ships)
    cx = _K2Context(ship_instances)
    ctx = cx.delta()
    ctx["python_ships"] = python_ships
    ctx["trace"] = _k2_host_io._h is not None
    t, use_memo, drift = _k1_clocks()
    _h.combat_k2_begin(handles, dt, t, use_memo, drift, ctx)
    cx.commit()
    run_k2(ships, dt, ship_instances, cx)
    return True


# ── The per-step scan and frame table (phase 3: shared by K4 and K3) ────────
#
# native/src/combat/include/dauntless/combat/step_scan.h is the contract.
# host_loop calls step_scan(ships_list) once, at the top of `cb.eligibility`
# (spec 2026-11-01 §4.1; ruling A3: K3 reuses it, never scans again). The
# binding fills the native ship-handle array in list order and returns the
# distinct sets in play; this module then resolves frames.frame_of(set) for
# each of them -- EVERY step, never cached, so a set's frame changing between
# steps (mark_mapped, an in-system hand-off) is read at once -- and sends the
# frame table. A step is representable only when every ship has an Object
# row of a class K2 has seen, no instance attribute shadowing one of
# _STEP_SHIP_PATCHES, a real IsDead, is a ShipClass (an engine ObjectClass
# subclass may override a read method: ProximityCheck.GetRadius) and has a
# representable set; no ship is listed twice; and no class K2 watches is
# patched (_k2_classes_unchanged, ruling C2).

#: Instance attributes that send the step to Python: the methods K3/K4 stand
#: in for on a ship (spec §7's override list).
_STEP_SHIP_PATCHES = (
    "GetContainingSet", "GetTranslate", "SetTranslateXYZ", "GetVelocityTG",
    "IsDead", "GetWorldLocation", "GetRadius", "GetScale")


class _StepScan:
    """One step's scan, as K4 and K3 read it: `ships` (the list scanned),
    `ok`, `reason` (why not ok, else None), `sets` (Set handles in play),
    `frames` (the table sent), `keys` (frame key -> the id interned for this
    step) and `serial` (the native scan's, combat_step_serial: K3's begin
    refuses a scan taken since). `k4_fresh` is True until K4 has used it."""

    __slots__ = ("ships", "ok", "reason", "sets", "frames", "keys",
                 "k4_fresh", "serial")

    def __init__(self, ships) -> None:
        self.ships = ships
        self.serial = -1
        self.ok = False
        self.reason = None
        self.sets = []
        self.frames = []
        self.keys = {}
        self.k4_fresh = True


_step = None
_frames_mod = None


def _frames():
    global _frames_mod
    if _frames_mod is None:
        from engine.systems import frames
        _frames_mod = frames
    return _frames_mod


def _step_frames(sets, keys) -> list:
    """[(set_handle, key_id, ax, ay, az), ...]: frames.frame_of for each set
    handle, the frame key interned in `keys` (this step's; -1: frame_of
    returned None). A handle with no live object gets no entry (the kernel
    then hands any compare needing it back to Python)."""
    frame_of = _frames().frame_of
    table = []
    for h in sets:
        pSet = _registry.get(h)
        if pSet is None:
            continue
        f = frame_of(pSet)
        if f is None:
            table.append((h, -1, 0.0, 0.0, 0.0))
            continue
        k = keys.get(f.key)
        if k is None:
            k = keys[f.key] = len(keys)
        a = f.anchor_gu
        table.append((h, k, a[0], a[1], a[2]))
    return table


def step_scan(ships) -> _StepScan:
    """Scan `ships` (the step's ships_list) into the native step state and
    send this step's frame table; returns the _StepScan K4 and K3 read."""
    global _step
    # A step boundary: K3 (and the kernels after it) read fresh part slots.
    resolve_stale_part_slots(ships)
    st = _StepScan(ships)
    _step = st
    # A dirty torpedo table is rebuilt BEFORE the native scan checks the
    # rows, so every torpedo's set is framed now, not asked for later.
    # (_k3_fallback's own rebuild stays as a safety: a no-op by then.)
    proj = _k3_proj
    if _k3_dirty and proj is not None \
            and type(proj._active) is proj._ActiveList:
        torpedo_table_rebuild(proj._active)
    if _k2_role_snapshot is None:
        why = "unsnapped"
    elif not _k2_classes_unchanged():
        why = "patched"
    else:
        ok, why, sets = _h.combat_step_scan(
            ships, _kind("Object"), _KIND_SHIFT, _k2_seen_set,
            _STEP_SHIP_PATCHES)
        if ok:
            try:
                table = _step_frames(sets, st.keys)
            except Exception:
                why = "frame"   # Python's own compare raises the same way
            else:
                _h.combat_step_frames(table)
                st.ok = True
                st.sets = sets
                st.frames = table
                st.serial = _h.combat_step_serial()
                return st
    st.reason = why
    _h.combat_step_reset()
    return st


def clear_step() -> None:
    """The combat step is over (host_loop._advance_combat_step's finally) or
    the mission is being swapped: drop the step's scan, so its ships_list
    does not outlive the step (it would delay every ship's finalizer), and
    empty the native step state, so nothing later reads it as current."""
    global _step
    if _step is not None:
        _step = None
        if available():
            _h.combat_step_reset()


# ── K4: damage eligibility (phase 3) ────────────────────────────────────────
#
# native/src/combat/include/dauntless/combat/k4_eligibility.h is the
# contract. damage_eligibility.update resolves the player as it always has,
# then (switch on) calls k4_update: the kernel returns the indices of the
# ships select_eligible would add after the player, and this builds the same
# id set. select_eligible stays the reference: k4_update returns False (the
# caller runs it) when the step stands down (audit), a function K4 stands in
# for is patched (_K4_FUNCTIONS, snapshotted when damage_eligibility is
# defined), the step scan is not representable, the player has no usable
# row, max_count or a weight is not a plain number -- or the kernel hands
# back (a non-finite radius, position or score, a missing frame).

#: (module name, names) K4 stands in for; damage_eligibility's own are
#: added by k4_snapshot_stock.
_K4_FUNCTIONS = (
    ("engine.systems.frames", ("system_distance", "offset_between",
                               "frame_of", "containing_set", "local_in",
                               "_xyz")),
    ("engine.core.ids", ("implements",)),
    ("math", ("dist",)),
)
_K4_REASONS = ("audit", "patched", "unsnapped", "ships", "player",
               "max_count", "weights", "frame", "no_row", "unseen",
               "instance_patch", "stale", "is_dead", "not_ship",
               "duplicate", "set")
_k4_reasons = dict.fromkeys(_K4_REASONS, 0)
_k4_snapshot = None
_k4_de = None
_K4_EXACT = float(2 ** 53)


def k4_snapshot_stock(de_module) -> None:
    """Called by engine.appc.damage_eligibility once it is defined: the
    identity snapshot k4_update compares against."""
    global _k4_snapshot, _k4_de
    mods = [(de_module, ("select_eligible", "_radius"))]
    for name, names in _K4_FUNCTIONS:
        mods.append((importlib.import_module(name), names))
    snap = []
    for mod, names in mods:
        get = operator.attrgetter(*names)
        values = get(mod)
        if len(names) == 1:
            values = (values,)
        snap.append((mod, get, len(names) == 1, values))
    _k4_snapshot = snap
    _k4_de = de_module


def _k4_unchanged() -> bool:
    for mod, get, one, values in _k4_snapshot:
        try:
            now = get(mod)
        except AttributeError:
            return False
        if one:
            now = (now,)
        if now != values:
            return False
    return True


def _k4_python(why: str) -> bool:
    _k4_reasons[why] += 1
    return False


def _k4_weight(w):
    """A weight as the double Python's `w * x` uses, or None (not a float or
    an int a double holds exactly)."""
    t = type(w)
    if t is float:
        return w
    if t is int and -_K4_EXACT <= w <= _K4_EXACT:
        return float(w)
    return None


def _k4_player_frame(st, player) -> bool:
    """A player outside ships_list may sit in a set the scan never met: add
    its frame to this step's table (False if frame_of raised)."""
    h = _slot_of(player.__dict__.get("_containing_set"))
    if h is None or h in st.sets or (h >> _KIND_SHIFT) != _kind("Set"):
        return True
    try:
        more = _step_frames((h,), st.keys)
    except Exception:
        return False
    st.sets.append(h)
    st.frames.extend(more)
    _h.combat_step_frames(st.frames)
    return True


def k4_update(player, ships) -> bool:
    """damage_eligibility.update's body through K4: True when the kernel
    decided (the eligible set is stored), False when the caller must run
    select_eligible (counted by why in counts()["k4_python_reasons"])."""
    if _audit:
        return _k4_python("audit")
    if _k4_snapshot is None or not _k4_unchanged():
        return _k4_python("patched")
    t = type(ships)
    if t is not list and t is not tuple:
        return _k4_python("ships")
    st = _step
    if st is None or not st.k4_fresh or st.ships is not ships:
        st = step_scan(ships)
    st.k4_fresh = False
    if not st.ok:
        return _k4_python(st.reason)
    if player is None:
        ph = REF_NONE
    else:
        ph = slot(player)
        if ph is None or type(player) not in _k2_seen_set \
                or not player.__dict__.keys().isdisjoint(_STEP_SHIP_PATCHES):
            return _k4_python("player")
        if not _k4_player_frame(st, player):
            return _k4_python("frame")
    de = _k4_de
    kw = de.select_eligible.__kwdefaults__
    max_count = kw.get("max_count") if kw else None
    if type(max_count) is not int:
        return _k4_python("max_count")
    # `len(eligible) >= max_count`: any value past the list's length (or
    # below 0) decides the same as this clamp.
    max_count = max(-1, min(max_count, 1 << 62))
    pw, sw = _k4_weight(de.PROX_WEIGHT), _k4_weight(de.SIZE_WEIGHT)
    if pw is None or sw is None:
        return _k4_python("weights")
    idx = _h.combat_k4_eligible(ph, max_count, pw, sw)
    if idx is None:
        return False            # counted by the kernel, by why
    ids = {id(player)} if player is not None else set()
    for i in idx:
        ids.add(id(ships[i]))
    de.set_current(ids)
    return True

# ── K3: the native torpedo kernel's driver (phase 3) ────────────────────────
#
# native/src/combat/include/dauntless/combat/k3_projectiles.h is the contract.
# projectiles.update_all (switch on, `_active` not empty) calls run_k3: the
# kernel walks update_all's decision steps 0-3 over the torpedo table and this
# step's scan (the one `cb.eligibility` took for the same ships_list) and
# returns ASKs -- each answered here by exactly the Python it stands for --
# then one DONE, which this applies: the write log into the torpedoes'
# Python attributes (not pushed back: the row already holds every value), the
# hits built with Python's object identities, expire() in the kernel's order.
#
# WHAT K3 STANDS IN FOR, checked before begin (a difference sends the WHOLE
# step to Python, so a test's, tool's or mod's replacement is obeyed):
#   module functions and constants  _K3_FUNCTIONS (map §A8.3.9's patch points
#                     and the functions the kernel replaces), against
#                     k3_snapshot_stock's identity snapshot, plus host_io._h
#                     the real bindings or None              -> "patched";
#   classes           the stock Torpedo's _K3_TORPEDO_NAMES, any odd torpedo
#                     class (a subclass) resolving one differently, and every
#                     ship/object class K2 has seen resolving _K3_SHIP_NAMES
#                     to non-engine code or to anything other than at first
#                     sight (K2's ruling C2)                  -> "guard".
# The ship methods K2 already watches (IsDead, GetWorldLocation,
# GetContainingSet, GetRadius, GetScale, GetShields, GetCloakingSubsystem) are
# re-checked by the step scan (_k2_classes_unchanged) earlier in this step.
# The static twin is tests/unit/test_native_k3_override_guard.py.

#: (module, names) K3 stands in for. Constants compare by value (the kernel
#: was pushed them at resync: a change since is not in the mirror).
_K3_FUNCTIONS = (
    ("engine.appc.projectiles", ("_guide", "_steer_point", "_target_visible",
                                 "_broadphase", "_shifted", "_LEAD_ACCEL_K")),
    ("engine.appc.combat", ("sphere_hit", "_resolve_hit_point",
                            "shield_bubble_entry", "shields_block",
                            "bubble_bound_radius", "ray_sphere_entry",
                            "cloak_shields_suspended", "_hull_box_for",
                            "_body_frame_delta")),
    ("engine.appc.collisions", ("world_radius",)),
    ("engine.systems.frames", ("offset_between", "containing_set",
                               "shifted")),
    ("engine.appc.subsystems", ("target_offset_world", "_is_offline")),
    ("engine.appc.part_severance", ("authored_mount_subsystem",
                                    "_mounted_subsystems")),
    ("engine.appc.sensor_detection", ("can_detect",
                                      "ENHANCED_SENSOR_CONTEST")),
    ("engine.host_io", ("ray_trace_mesh",)),
    ("engine.core.ids", ("implements",)),
)
#: Torpedo methods the kernel stands in for: the store read and write of the
#: position, and frames.containing_set's GetContainingSet.
_K3_TORPEDO_NAMES = ("GetTranslate", "SetTranslateXYZ", "GetContainingSet")
#: Ship methods K3 reads that K2's roles do not list: the target's lead.
_K3_SHIP_NAMES = ("GetVelocityTG",)
_K3_REASONS = ("off", "audit", "plain_active", "scan", "patched", "row",
               "guard", "instances")
_k3_reasons = dict.fromkeys(_K3_REASONS, 0)
# The key of the iids table the K3 kernel holds (it keeps its own, apart from
# K2's): as _k2_iids_sent.
_k3_iids_sent = [_K2_UNSENT, -1, -1]
_k3_snapshot = None
_k3_proj = None
_k3_torp_res = None
# [(cls, resolution, foreign)] for the seen ship/object classes, rebuilt when
# _k2_seen grows (_k3_watch_seen[0] is the length it was built at).
_k3_watch: list = []
_k3_watch_seen = [-1]
_k3_ask = None


def k3_snapshot_stock() -> None:
    """Called by host_loop right after k2_snapshot_stock (projectiles and
    every module K3 stands in for are imported by then): the identity
    snapshot run_k3 compares against, before any test, tool or mod can
    replace a function."""
    global _k3_snapshot, _k3_proj, _k3_torp_res, _k3_torpedo_cls
    snap = []
    for name, names in _K3_FUNCTIONS:
        mod = importlib.import_module(name)
        get = operator.attrgetter(*names)
        values = get(mod)
        if len(names) == 1:
            values = (values,)
        snap.append((mod, get, len(names) == 1, values))
    _k3_snapshot = snap
    _k3_proj = importlib.import_module("engine.appc.projectiles")
    _k3_torpedo_cls = _k3_proj.Torpedo
    _k3_torp_res = _k2_resolution(_k3_torpedo_cls, _K3_TORPEDO_NAMES)
    # Rows made before the snapshot were filed against no stock class.
    for h, t in _k3_rows.items():
        if type(t) is _k3_torpedo_cls:
            _k3_odd_rows.pop(h, None)
    _k3_watch_seen[0] = -1


def _k3_unchanged() -> bool:
    for mod, get, one, values in _k3_snapshot:
        try:
            now = get(mod)
        except AttributeError:
            return False
        if one:
            now = (now,)
        if now != values:
            return False
    h = _k2_host_io._h
    return h is None or h is _k2_host


def _k3_rebuild_watch() -> None:
    watch = []
    for cls in _k2_seen:
        if _k2_role_of(cls) in ("ship", "object"):
            foreign = any(_k2_foreign(getattr(cls, n, None))
                          for n in _K3_SHIP_NAMES)
            watch.append((cls, _k2_resolution(cls, _K3_SHIP_NAMES), foreign))
    _k3_watch[:] = watch
    _k3_watch_seen[0] = len(_k2_seen)


def _k3_classes_ok() -> bool:
    """The class half: the stock Torpedo, and every odd torpedo class (a
    subclass with a row), resolving _K3_TORPEDO_NAMES to what the stock
    Torpedo did at the snapshot; and no seen ship/object class resolving
    _K3_SHIP_NAMES to non-engine code or to anything other than at first
    sight."""
    if not _k2_same(_k3_torpedo_cls, _k3_torp_res):
        return False
    if _k3_odd_rows:
        for cls in set(_k3_odd_rows.values()):
            if not _k2_same(cls, _k3_torp_res):
                return False
    if len(_k2_seen) != _k3_watch_seen[0]:
        _k3_rebuild_watch()
    for cls, res, foreign in _k3_watch:
        if foreign or not _k2_same(cls, res):
            return False
    return True


def _k3_python(why: str):
    _k3_reasons[why] += 1
    return None


def _k3_fallback(all_ships, ship_instances):
    """Why this `cb.projectiles` step must run whole in Python, or None."""
    if not _enabled:
        return "off"
    # The kernel's own can_detect would bypass the audit (as K2).
    if _audit:
        return "audit"
    proj = _k3_proj
    if proj is None or _k2_role_snapshot is None:
        return "patched"
    if type(proj._active) is not proj._ActiveList:
        return "plain_active"
    if ship_instances is not None \
            and type(ship_instances) is not _tracked_instances():
        return "instances"
    st = _step
    if st is None or st.ships is not all_ships or not st.ok:
        return "scan"
    if not _k3_unchanged():
        return "patched"
    if _k3_dirty:
        # A list mutation the rows could not follow (a reorder, a slice, a
        # clear): never hand the kernel a stale table. Before the class
        # check, which reads the rows' classes.
        torpedo_table_rebuild(proj._active)
        if _k3_dirty:
            return "row"        # a torpedo listed twice: no row can hold it
    if not _k3_classes_ok():
        return "guard"
    return None


def run_k3(dt, all_ships, ship_instances):
    """projectiles.update_all's body through K3: the `hits` list it returns,
    or None when the caller must run the Python body (counted by why in
    counts()["k3_python_reasons"]).

    EXCEPTIONS. Any exception between begin and DONE (an ASK's Python
    raising: a target's GetVelocityTG inside an ASK guide, say) abandons the
    session and re-raises. Nothing has been applied then -- the kernel writes
    every age and position at DONE -- whereas the Python body would already
    have advanced, aged and TTL-placed the torpedoes before the one that
    raised. Exceptions propagate exactly as today otherwise (`cb.projectiles`
    is only a profiler scope); an exception from expire() (an
    ET_TORPEDO_EXITED_SET handler) comes after every write was applied, as in
    Python."""
    why = _k3_fallback(all_ships, ship_instances)
    if why is not None:
        return _k3_python(why)
    proj = _k3_proj
    st = _step
    cx = _K2Context(ship_instances, _k3_iids_sent)
    ctx = cx.delta()
    ctx["trace"] = _k2_host_io._h is not None
    ctx["n_active"] = len(proj._active)
    ctx["scan_serial"] = st.serial
    now_, use_memo, drift = _k1_clocks()
    # Everything the walk needs is made BEFORE begin: from begin on, only
    # _k3_walk's try (which abandons) may raise, or the session leaks and
    # every later begin throws.
    global _k3_ask
    if _k3_ask is None:
        _k3_ask = _h.combat_k3_kinds()["ASK"]
    walk = _K1Walk()
    why = _h.combat_k3_begin(dt, (now_, drift), use_memo, ctx)
    cx.commit()                 # begin takes the context, reason or not
    if why is not None:
        return None             # counted by the kernel
    return _k3_walk(dt, ship_instances, st, walk, _k3_ask)


def _k3_walk(dt, ship_instances, st, walk, ask):
    try:
        rec = _h.combat_k3_next()
        while rec[0] == ask:
            # No heal here (cf. run_k2): a K3 slot read after an ASK is a
            # steer point, whose PartStale is a steer_point ASK.
            _h.combat_k3_answer(_k3_answer(rec, walk, dt, ship_instances, st))
            rec = _h.combat_k3_next()
        _h.combat_k3_end()
    except BaseException:
        if _h.combat_k3_open():
            _h.combat_k3_abandon()
        raise
    _kind, writes, expired, hits = rec
    rows = _k3_rows
    # Every handle to its object BEFORE any expire(): `_active.remove` drops
    # the torpedo's row (and its _k3_rows entry).
    hit_objs = [(rows[th], walk.obj(sh), point, normal, bubble, is_bubble)
                for th, sh, point, _tier, normal, bubble, is_bubble in hits]
    expiring = [rows[h] for h in expired]
    _k3_apply(writes, rows)
    out = []
    for t, ship, point, normal, bubble, is_bubble in hit_objs:
        # update_all's identities (map §A5): on a fallback-tier bubble hit,
        # hit_point, seg_cur and _bubble_entry are ONE object.
        if is_bubble:
            b = p = TGPoint3(*bubble)
        else:
            b = None if bubble is None else TGPoint3(*bubble)
            p = TGPoint3(*point)
        t._bubble_entry = b
        out.append((t, ship, p, None if normal is None else TGPoint3(*normal)))
    expire = _k3_proj.expire
    for t in expiring:
        expire(t)
    return out


def _k3_apply(writes, rows) -> None:
    """The DONE write log into the torpedoes' Python attributes, WITHOUT the
    TorpedoField / `_velocity` pushes (the row holds every value already) --
    except the incoming-torpedo table's velocity, which gets exactly the
    write the `_velocity` setter makes (projectiles.Torpedo._velocity)."""
    proj = _k3_proj
    for h, age, seen, tvel, vel in writes:
        t = rows[h]
        d = t.__dict__
        if seen is not None:
            d["_last_seen_target_pos"] = TGPoint3(*seen)
        if tvel is not None:
            d["_last_target_vel"] = TGPoint3(*tvel)
        if vel is not None:
            v = TGPoint3(*vel)
            t._vel = v
            if t._scan_live == proj._scan_gen and not proj._scan_dirty:
                proj._scan_table().set_velocity(t.GetObjID(), v.x, v.y, v.z)
        d["_age"] = age


def _k3_answer(rec, walk, dt, ship_instances, st):
    """An ASK's answer: exactly the Python the kernel stands in for
    (k3_projectiles.h, RECORDS), on the live objects."""
    query, args = rec[1], rec[2:]
    if query == "guide":
        _k3_proj._guide(_k3_rows[args[0]], dt)
        return None
    if query == "steer_point":
        p = _k3_proj._steer_point(_k3_rows[args[0]], walk.obj(args[1]),
                                  args[2])
        return (p.x, p.y, p.z)
    if query == "frame":
        # Interned in THIS step's keys, so ids match the table K4 sent. A set
        # with no live object has no entry: None (frame_of None).
        entry = _step_frames((args[0],), st.keys)
        return entry[0][1:] if entry else None
    from engine.appc import combat
    if query == "shields_block":
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
    raise RuntimeError("combat K3: unknown ASK %r" % (query,))


if available():
    # step_memo.forget() (every hit, the step's forget points, the outermost
    # block's exit) empties the native memo with the Python tables.
    from engine.core import step_memo as _step_memo
    _step_memo.on_forget(_h.combat_memo_clear)
