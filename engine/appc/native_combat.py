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
``__init__``, unregistered by the object's ``weakref.finalize`` -- recorded
there and freed at the next drain point (``drain``: no row is freed while a
kernel computes). Objects are
registered whenever the bindings are built, even before ``configure()``;
nothing is PUSHED until it has run, and then it resyncs every row.

``configure()`` (called by ``GameLoop.__init__``) makes the mirror live and
reads the switch (fire control native only, spec
docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md §4.1):

- The module is REQUIRED (M2, M10): a missing binding (a stale build) or a
  failed ``_self_check()`` raises there, naming what is missing or what
  differed. Once it has run, the mirror is live and fire control (K1, the
  tractors with it) is native, whatever the switch says
  (``fire_control_native``, M9). A fire-control call before it (the host
  loads the mission before it builds the GameLoop) makes the mirror live
  itself, or raises the same way.
- The switch, ``DAUNTLESS_NATIVE_COMBAT``, is on unless ``=0`` (M1). It
  governs only the other kernels (``enabled``): K0, K2, K3 and its torpedo
  table, K4, native damage, the tick's effect scope and the dispatched
  sensor queries. ``DAUNTLESS_NATIVE_AUDIT=1`` turns the audit on and
  implies the switch on.
"""
import collections
import importlib
import math
import operator
import os
import random
import sys
import threading
import traceback
import weakref
from typing import Mapping

from engine.appc import proximity_cache
from engine.appc import effect_queue as _effect_queue
from engine.appc import passive_state as _passive_state
from engine.appc.math import TGPoint3
from engine.appc.passive_state import WakeField
from engine.core import frame_profiler as _prof
from engine.core import ids as _ids
from engine.core.ids import implements

try:
    import _dauntless_host as _h
except ImportError:
    _h = None  # bindings not built: nothing registers, Python answers.

# The mirror is live: configure() found every binding and the self-check
# passed. Fire control is native exactly then (fire_control_native).
_enabled = False
# The switch (DAUNTLESS_NATIVE_COMBAT, on unless =0) as configure() last set
# it, never True while the mirror is not live: the other kernels (enabled).
_switch = False
_audit = False
_failures: list = []
# Dispatched queries (sensor_detection, sensor_occlusion) the kernel answered,
# and the ones that fell back to the Python on its ValueError. Counted only on
# the native path, so the switch-off path pays nothing.
_counts = {"native_calls": 0, "fallbacks": 0}
# Fire control's no-fires found by this driver, not the kernel (fire control
# native only, R2, R3; k1_no_fire, summed with the kernel's by name, and each
# why logged once: _k1_no_fire): "no_row" (a weapon or system the mirror has
# no row for), "unnamed_target" (a Fire whose target the mirror cannot
# name), "sdk_can_fire" (a CanFire the mirror could not answer), "dropped"
# (a row dropped: a value it cannot encode, or a stale handle; _drop) and
# "tractor_row" (a tractor StartFiring or a tractored ship with no row).
_K1_PY_NO_FIRE = ("no_row", "unnamed_target", "sdk_can_fire", "dropped",
                  "tractor_row")
_k1_no_fire_py = dict.fromkeys(_K1_PY_NO_FIRE, 0)
# K2: `cb.phasers` steps run whole in Python (k2_phasers returned False), by
# why: "nested" (a K2 session is already open), "instances" (the step's
# ship_instances is not the session's TrackedInstances), "patched" (a
# function or class K2 stands in for differs from its snapshot), "audit"
# (DAUNTLESS_NATIVE_AUDIT=1: the kernel's can_detect would bypass the audit).
# The drain (run_k2, spec 2026-11-02 §4.4): "k2_present_python", resting
# contacts presented by the Python batch; "k2_present_gone", drained
# contacts skipped because an object they name was freed or unregistered
# before the drain. (The ones the drain presents natively, the shield
# splash, are the binding's "k2_present_native", combat_k2_counts.)
_k2_steps = {"k2_python_steps": 0, "k2_present_python": 0,
             "k2_present_gone": 0}
# The drain's native presentation constants as last sent
# (combat_k2_present_constants): (intensity, default radius), None unsent.
_k2_present_sent = [None]
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
#: NativeField type for a TGPoint3-or-None the motion kernel reads (kernel M:
#: ShipClass._current_angular_velocity, _drift_velocity,
#: _target_angular_velocity_setpoint; PhysicsObjectClass._angular_velocity).
#: None pushes [] (state 0), a TGPoint3 [x, y, z] (state 1), anything else
#: [0.0] * 4 (state 2: unrepresentable, the kernel takes the Python path).
#: Never drops the row. The row keeps ``<name>_state`` beside the vector.
#: KNOWN, NOT GUARDED: a TGPoint3's components are float()ed, so a string
#: written straight into one (``p.x = "1"``) mirrors as a number where
#: Python would raise; TGPoint3's own setters store floats, and no engine
#: writer does this.
POINT_OR_NONE = "point or none"
#: NativeField type for an int-or-None (``TorpedoSystem._selected_slot``):
#: None pushes -1 (slots are never negative).
OPT_INT = "opt int"
#: NativeField type for a value the reader uses as a SEQUENCE INDEX
#: (``PhaserSystem._power_level``, PHASER_DISCHARGE_BY_POWER_LEVEL[level]):
#: pushes ``operator.index(value)``, so a float, which the index would
#: reject (TypeError: rate 0.0), drops the row instead of reading as an int.
INDEX = "index"

# system name -> (the map's Profile object, its Profile row handle). One row
# per system map, registered lazily at the first frame push that needs it.
_profiles: dict = {}

_KIND_SHIFT = 60
_INT64_LIMIT = 1 << 63

# The one-call scalar push (combat_push_scalar, spec 2026-11-02 §4.2): a
# NativeField type -> its push code's name in combat_push_codes(). Every
# other type keeps NativeField._push.
_PUSH_CODE_NAMES = {float: "PUSH_FLOAT", int: "PUSH_INT", bool: "PUSH_BOOL",
                    IS_TRUE: "PUSH_IS_TRUE", OPT_INT: "PUSH_OPT_INT"}
_push_codes: dict = {}


# ── The switch ───────────────────────────────────────────────────────────────

#: Every binding a current build has; one missing means the .so is older
#: than this module (a stale build: configure raises, naming it).
_REQUIRED_BINDINGS = (
    "combat_register", "combat_push_scalar", "combat_apply_reset_counts",
    "combat_set_floats",
    # The phase-3 bindings too (the torpedo table, the step scan, K4 and
    # the K3 kernel).
    "combat_torp_add", "combat_step_scan", "combat_step_serial",
    "combat_k4_eligible", "combat_k3_begin", "combat_set_part_poses",
    "combat_k0_begin", "combat_k0_apply_stats", "combat_effect_take",
    "combat_effect_rebind",
    "combat_apply_hit", "combat_dmg_set_condition",
    "combat_dmg_clean_handles", "combat_k2_scan_clear",
    "combat_compute_take",
    # Tractors native (fire control native only, M4).
    "combat_k1_begin_tractor", "combat_tractor_force_step",
    # The SDK routes and the walk offset (fire control native only, M8).
    "combat_k1_begin_dumb", "combat_k1_begin_fire", "combat_k1_result",
    "combat_k1_can_fire", "combat_k1_walk_manual_offset",
    # The subsystem stage session (phase 6 A1). combat_subsys_repair_state
    # came with the cloak and repair pieces (Task 5), in the same build as
    # combat_subsys_next's third argument (dmg_ctx): a .so from before it
    # lacks the name, so the stale build is named here rather than the
    # first stage failing on the arity.
    "combat_subsys_begin", "combat_subsys_next", "combat_subsys_kinds",
    "combat_subsys_repair_state",
    # The skips and per-item repair delegation (Task 8: the four pieces are
    # native only).
    "combat_subsys_skips", "combat_subsys_skip_counts",
    "combat_subsys_skip_counts_reset", "combat_subsys_repair_complete",
)


def missing_bindings() -> list:
    """What this build lacks: ["_dauntless_host"] when the module itself
    did not import, else the names of _REQUIRED_BINDINGS it does not
    have (empty for a current build)."""
    if _h is None:
        return ["_dauntless_host"]
    return [name for name in _REQUIRED_BINDINGS if not hasattr(_h, name)]


def available() -> bool:
    """The bindings are built and current (missing_bindings is empty)."""
    h = _h
    return h is not None and all(hasattr(h, n) for n in _REQUIRED_BINDINGS)


def configure(environ: Mapping[str, str] = os.environ) -> None:
    """Make the mirror live (_go_live) and set the switch from `environ`
    (module docstring). Raises RuntimeError when the bindings are missing or
    stale (naming every missing one) or the self-check fails (naming what
    differed): fire control has no other copy to fall back to (M2, M10).
    Neither the switch nor the audit excuses it."""
    global _switch, _audit
    audit = environ.get("DAUNTLESS_NATIVE_AUDIT") == "1"
    switch = audit or environ.get("DAUNTLESS_NATIVE_COMBAT") != "0"
    # The audit is on only when the switch ended up on: auditing rows that
    # were never pushed would record every field of every row, every tick.
    _audit = False
    _go_live()
    if _switch and not switch:
        torpedo_table_mark_dirty()  # K3's table, unpushed from here on
    _switch = switch
    _audit = audit


def _go_live() -> None:
    """The mirror live: every binding present, the self-check passed, every
    registered row resynced. Raises RuntimeError otherwise (configure's
    message). A no-op once live. Leaves the switch alone: configure()'s."""
    global _enabled
    missing = missing_bindings()
    if missing:
        _disable("bindings missing")
        if _h is None:
            raise RuntimeError(
                "native combat: the _dauntless_host module did not import; "
                "fire control is native only -- build it "
                "(cmake --build build -j)")
        raise RuntimeError(
            "native combat: stale build, missing bindings: %s; fire control "
            "is native only -- rebuild (cmake --build build -j)"
            % ", ".join(missing))
    if not _enabled:
        key = _self_check_key()
        if not _self_check_passed_for(key):
            reason = _self_check()
            if reason is not None:
                raise RuntimeError(
                    "native combat: self-check failed: %s; fire control is "
                    "native only" % reason)
            _self_check_passed[:] = key
        _enabled = True
        resync()


# The self-check's verdict for the exact objects it compared: the bindings
# module, its three test bindings, math.dist and the Python density. Its
# answer is a pure function of those, so a repeat _go_live after reset() --
# the per-test reset runs one before every test, ~2 ms of seeded math each
# time, ~70 s over the full suite -- skips it while every one is the SAME
# object (`is`, never id(): the list holds them, so none can be recycled).
# Swapping any of them (a test patching math.dist, or nc._h) re-checks.
_self_check_passed: list = []


def _self_check_key() -> list:
    from engine.appc import nebula_density as nd
    h = _h
    return [h, getattr(h, "combat_k1_kinds", None),
            getattr(h, "combat_test_dist3", None),
            getattr(h, "combat_test_density", None), math.dist, nd.density]


def _self_check_passed_for(key) -> bool:
    return (len(_self_check_passed) == len(key)
            and all(a is b for a, b in zip(_self_check_passed, key)))


def enabled() -> bool:
    """The switch: whether K0, K2, K3, K4, native damage, the tick's effect
    scope and the dispatched sensor queries run natively (M9). Fire control
    does not read it (fire_control_native)."""
    return _switch


def fire_control_native() -> bool:
    """Whether fire control (K1) runs natively: the ONE predicate every
    fire-control entry gates on -- the held-weapon pump
    (host_loop._pump_held_weapons), WeaponSystem.StartFiring's session,
    the SDK's own weapon calls (Weapon.FireDumb, CanFire, Fire: fire
    control native only, M8.1, M8.6) and the tractors (k1_tractor_start,
    tractor_force_step). Always true (M9), never the switch: the first call
    before configure() makes the mirror live itself (_go_live), so a call
    in the host's mission load -- which runs before the GameLoop that calls
    configure() -- is native too, or raises RuntimeError naming the missing
    binding or the failed self-check (M10). Every entry point reaches this
    predicate, every loader therefore needs nothing of its own. Fire
    control has no other copy (M3): this never returns False."""
    if not _enabled:
        _go_live()
    return True


def audit_enabled() -> bool:
    return _audit


def reset() -> None:
    global _enabled, _switch, _audit
    _enabled = False
    _switch = False
    _audit = False
    for k in _k1_no_fire_py:
        _k1_no_fire_py[k] = 0
    _failures.clear()
    _profiles.clear()
    _logged_once.clear()
    # The part-map generation is NOT reset: it is monotonic for the process,
    # so a slot stamped before the reset can never read fresh again.
    _forget_part_caches()
    # Per-class caches: a class patched or re-based since must recompute.
    _kind_by_type.clear()
    # The field caches too: each keys its class strongly, so a class a test
    # defined would otherwise outlive the test (and every later
    # __subclasses__() walk would see it).
    _class_fields.clear()
    _class_hidden.clear()
    _quiet_setters.clear()
    _repair_bay_by_type.clear()
    _power_kind_by_type.clear()
    _dmg_classes.clear()
    for k in _dmg_counts:
        _dmg_counts[k] = 0
    if available():
        _h.combat_dmg_clean_clear()
        _h.combat_k2_scan_clear()
    _dmg_ctx[0] = None
    global _pulse_stale
    _pulse_stale = False
    _counts["native_calls"] = 0
    _counts["fallbacks"] = 0
    for k in _k2_steps:
        _k2_steps[k] = 0
    for k in _K2_STEP_REASONS:
        _k2_step_reasons[k] = 0
    _k2_flags.clear()
    _k2_iids_cache[:] = [None, -1, -1, None]
    _k2_iids_sent[:] = [_K2_UNSENT, -1, -1]
    _k2_present_sent[0] = None
    global _k2_drop_epoch
    _k2_drop_epoch += 1
    torpedo_table_mark_dirty()
    global _step
    _step = None
    for k in _K4_REASONS:
        _k4_reasons[k] = 0
    for k in _K3_REASONS:
        _k3_reasons[k] = 0
    _k3_hit_python[0] = 0
    _k3_iids_sent[:] = [_K2_UNSENT, -1, -1]
    global _apply_kinds
    _apply_kinds = None
    for k in _K0_STEP_REASONS:
        _k0_step_reasons[k] = 0
    # Entries a previous test left queued, and a scope it left open, go
    # undelivered (tests/conftest.py resets between tests; nothing in the
    # engine calls reset()).
    _effect_queue.reset()
    if available():
        _h.combat_apply_reset_counts()
        _h.combat_push_reset_counts()
        _h.combat_k1_reset_counts()
        # A leaked K2 session and its record's pending writes (the binding
        # drops them with the session), and a leaked applier context.
        if _h.combat_k2_open():
            _h.combat_k2_abandon()
        _h.combat_k2_reset_counts()
        _h.combat_set_applier(None)
        _h.combat_k4_reset_counts()
        if _h.combat_k3_open():
            _h.combat_k3_abandon()
        _h.combat_k3_reset_counts()
        if _h.combat_k0_open():
            _h.combat_k0_abandon()
        _h.combat_k0_reset_counts()
        _h.combat_step_reset()
        for k in range(len(_COMPUTE_HOME)):
            _h.combat_compute_take(k)
    # Pending frees apply to the mirror they were recorded against, before
    # a test's combat_clear rebuilds it; queued pushes go (the mirror is
    # off now).
    drain()
    _k1_compute.clear()
    # Kernel M's driver (its switch, counts and class watch). Imported here,
    # not at module scope: native_motion imports this module.
    from engine.appc import native_motion
    native_motion.reset()
    from engine.appc import native_subsystems
    native_subsystems.reset()


def counts() -> dict:
    """Since the last reset(): {"native_calls": n, "fallbacks": n} for the
    dispatched sensor queries, and the K1 kernel's {"k1_records": n}
    (sessions run: each returns one record, DONE), "k1_posed" ({"walks",
    "target_aims"}: systems of a posed ship walked, Fire decisions aimed at
    a posed target's offset), "k1_logged" ({"walk_start": walks started;
    "beam_sustain": Fires on a beam already firing and "idle_bank_stop":
    StopFirings of a bank not firing, both pure field writes; beam_edge,
    fire_failed, firing_bank_stop, system_stop: writes plus queue entries;
    tube_launch, dumb_launch, dumb_refused, pulse_launch: the launches;
    "tractor_walk" / "tractor_start": the pump's tractor walks and
    StartFiring's tractor sessions; sdk_dumb_fire, sdk_fire, sdk_can_fire:
    THE SDK ROUTES}), "k1_entries" ({K1Effect name: n}), "k1_launch_reasons"
    ({launch_unresolved, launch_uncached, launch_other: n}: the launches the
    kernel could not make) and "k1_no_fire" ({why: n}: what did not fire
    that tick because the mirror could not answer -- fire control native
    only, R2, R3; the kernel's K1NoFire names, k1_fire_control.h NO FIRE,
    summed with the driver's own, _K1_PY_NO_FIRE; every why is logged once
    per session on stderr). A launch the kernel could not make is counted
    in both k1_launch_reasons and k1_no_fire["launch"].

    "c_applied_writes": the K1/K2/K0 log writes the bindings applied
    themselves (C-applied write logs, _applier_context). "fast_pushes":
    scalar NativeField pushes stored by combat_push_scalar.

    K0 (`sim.weapons`, the charging kernel): the kernel's "k0_steps"
    (weapons stepped natively), "k0_records" ({DONE, DEPLETE_STOP,
    RELOADED, WATCH, RUN_PYTHON: n}), "k0_python_reasons" (the RUN_PYTHON
    hand-backs by K0Reason name, k0_charging.h: no_row,
    not_weapon_system, stale_row, slot_heal, override, audit, power_level,
    parent, unrepresentable, unknown_kind, watcher -- a pulse cannon whose
    charge watcher it does not own; zeros included) and
    "k0_logged_writes" (writes returned in records), "k0_logged"
    ({deplete_stop, reload, watch}: what were DEPLETE_STOP / RELOADED /
    WATCH records, now logged writes plus queue entries -- combat fire
    events Task 4; those three records are never returned; hold_stop: a
    holding tractor beam its parent's power loss stopped, fire control
    native only) and
    "k0_entries" ({LOOP_STOP, TORPEDO_RELOAD, WATCH}: the queue entries K0
    produced; a throw in next() restores these counters with the session,
    so they do not overcount), plus the driver's "k0_python_steps" /
    "k0_python_step_reasons" ({off, nested, audit}: whole steps k0_weapons
    left to the Python walk).

    K2 (`cb.phasers`): the kernel's {"k2_records", "k2_python_ships",
    "k2_asks", "k2_python_reasons": {K2Why name: n}, "k2_ask_queries":
    {query: n}, "k2_posed": {"banks", "lock_aims"},
    "k2_batched_contacts": resting contacts queued for the drain instead
    of a CONTACT record of their own, "k2_logged_system_stop": offline
    systems stopped by logged writes instead of a SYSTEM_STOP record (round
    trips Task 3; k2_records counts only the records returned), of them
    "k2_logged_firing_system_stop" those with a bank firing, and
    "k2_logged_bank_stop" the walk's stops of a firing bank logged instead
    of a BANK_STOP record, with "k2_entries" ({K1 effect name: n}: their
    LOOP_STOP entries; combat fire events Task 4). k2_batched_contacts is
    counted when the contact is queued, so a kernel throw later in the same
    next() (which restores the queue) or an abandoned session (which drops
    it) can overcount; k2_logged_system_stop, k2_logged_firing_system_stop,
    k2_logged_bank_stop and k2_entries likewise, when a throw -- or a ship
    or bank handed back to Python -- undoes the writes and entries they
    counted}
    (k2_beams.h; posed_ship retired, part_stale its successor), plus
    "k2_present_native" (drained resting contacts the drain presented
    itself: the shield splash, spec 2026-11-02 §4.4), "k2_present_python"
    (drained resting contacts the Python batch presented),
    "k2_present_gone" (drained ones skipped: an object they name was freed
    or unregistered before the drain; the three sum to the drained
    contacts), "k2_python_steps"
    (steps run whole in Python) and "k2_python_step_reasons" ({"nested",
    "instances", "patched", "audit"}: n).

    K4 (`cb.eligibility`): "k4_runs" (calls the kernel decided) and
    "k4_python_reasons" ({why: n}, the kernel's hand-backs -- scan, player,
    nonfinite, frame, set -- summed with k4_update's own: audit, patched,
    the step scan's reasons, ...).

    K3 (`cb.projectiles`): the kernel's {"k3_runs", "k3_records",
    "k3_asks": {query: n}, "k3_guide_reasons": {why: n},
    "k3_steer_reasons": {why: n} (the steer_point ASKs: unattributed,
    part_stale, ...; projectile_geometry.h SteerWhy, zeros included),
    "k3_posed_steers": n (a posed target's mount or picked spot steered
    natively)}, and
    "k3_python_steps" / "k3_python_reasons" ({why: n}): the steps run whole
    in Python, the kernel's begin reasons (scan, table, unrepresentable,
    stale_ref, torpedo_xform, ship_cache) summed with run_k3's own (off,
    audit, plain_active, scan, patched, row, guard, instances)."""
    c = dict(_counts)
    c.update(_k2_steps)
    c["k2_python_step_reasons"] = dict(_k2_step_reasons)
    c["k0_python_step_reasons"] = dict(_k0_step_reasons)
    c["k0_python_steps"] = sum(_k0_step_reasons.values())
    if available():
        c.update(_h.combat_k0_counts())
        c.update(_h.combat_apply_counts())
        c.update(_h.combat_push_counts())
        k1 = _h.combat_k1_counts()
        why = k1["k1_no_fire"]
        for k, n in _k1_no_fire_py.items():
            why[k] = why.get(k, 0) + n
        c.update(k1)
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
        # Every hit handed back ran in _k3_apply_hits; those the kernel did
        # not name a reason for are the driver's own (a torpedo instance
        # patch): "python".
        k3["k3_hit_python_reasons"]["python"] = (
            _k3_hit_python[0] - k3["k3_hit_python"])
        k3["k3_hit_python"] = _k3_hit_python[0]
        c.update(k3)
    return c


def _disable(reason: str) -> str:
    global _enabled, _switch
    _enabled = False
    _switch = False
    return reason


def _self_check():
    """Compare the native primitives with THIS interpreter's Python on fixed
    seeded inputs. The native math.dist is CPython 3.11.15's, ported; another
    interpreter may round differently, and then native cannot run (configure
    raises with this reason). Returns the reason, with the mirror left off,
    or None. Inputs stay finite: a non-finite drift/freq/seed makes the
    Python density raise where native returns NaN."""
    if not available():
        return _disable("native combat bindings missing: %s"
                        % ", ".join(missing_bindings()))
    # The kernel's record shape: one record per session, DONE (fire control
    # native only, M3). A kernel with any other kind (RUN_PYTHON, ASK, ...)
    # is a build from before the Python copy was deleted.
    kinds = dict(_h.combat_k1_kinds())
    if kinds != {"DONE": 0}:
        return _disable("K1 record kinds %r, not {'DONE': 0} (a stale "
                        "build)" % (sorted(kinds.items()),))
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


def _push_code(name: str) -> int:
    code = _push_codes.get(name)
    if code is None:
        _push_codes.update(_h.combat_push_codes())
        code = _push_codes[name]
    return code


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
    holds a value the mirror cannot represent. Its row is freed now, on the
    main thread (no kernel session is open there: none runs Python). Off
    the main thread the whole drop is queued for the next drain point
    (drain(); spec 2026-11-03 ruling R2): it re-pushes referrers and set
    members, which are mirror pushes. The finalizer's later unregister of
    the same handle fails quietly.

    What a drop costs fire control (M3: no Python copy takes over): a
    dropped weapon, system or ship never fires again, and -- the larger
    effect -- every system holding or listing the dropped object no longer
    fires either (k1_no_fire stale_row each tick) until it lets it go. The
    other kernels take their Python paths for it. Counted as fire control's
    no-fire "dropped" and logged once (fire control native only, R3)."""
    h = obj.__dict__.get("_nslot")
    if h is None:
        return
    if _off_main():
        _queue_push(obj, _drop_queued, None, "_drop")
        return
    _k1_no_fire("dropped", "a %s row was dropped (a value the mirror "
                "cannot encode, or a stale handle): every weapon system "
                "holding or listing it stalls (no_fire stale_row) until it "
                "lets it go, and it never fires itself"
                % type(obj).__name__)
    global _k2_drop_epoch
    _k2_drop_epoch += 1         # K2's cached ship -> iid table names handles
    if _enabled and (h >> _KIND_SHIFT) == _kind("Object"):
        _hand_latch_to_python(obj, h)
    del obj.__dict__["_nslot"]
    if _registry.get(h) is obj:
        del _registry[h]
    # Kernel entries naming the row and still queued would be skipped once
    # it is gone (effect_queue._resolve), losing events the Python reference
    # posts for this live object: they name the object instead (combat fire
    # events Task 4). A FREED object (the finalizer's unregister) has none.
    # Guarded like the other optional bindings: a .so without it has no
    # queue to rebind (and runs with the switch off).
    if hasattr(_h, "combat_effect_rebind"):
        _h.combat_effect_rebind(h, obj)
    _apply_free(h, None)
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


def _drop_queued(obj, _arg) -> None:
    _drop(obj)


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
    radius is "Subsystem._radius"). Like WakeField: no __get__.

    A scalar type (float, int, bool, IS_TRUE, OPT_INT) pushes in ONE call,
    combat_push_scalar, which encodes in C++ by _encode's rules
    (`_push_scalar`); _encode / _push stay the reference, and a subclass
    with its own _encode or _push keeps _push."""

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
        cls = type(self)
        own = (cls._encode is NativeField._encode
               and cls._push is NativeField._push)
        # The push code's name, or None: this field takes _push.
        self._scalar = _PUSH_CODE_NAMES.get(self._type) if own else None
        self._fast = None           # (field id, push code), at first push

    def __set__(self, obj, value) -> None:
        obj.__dict__[self._name] = value
        if _enabled:
            h = obj.__dict__.get("_nslot")
            if h is not None:
                if _get_ident() != _MAIN_IDENT:
                    _queue_push(obj, _repush_native, self, self._name)
                elif self._scalar is None:
                    self._push(obj, h, value)
                else:
                    self._push_scalar(obj, h, value)

    def _push_scalar(self, obj, h, value) -> None:
        """_push for a scalar type in one binding call: the binding raises
        TypeError / ValueError / OverflowError where _encode does, and
        ValueError for a stale handle, so the drop is _push's. (An int
        beyond int64 drops too; through _push it escaped as pybind's
        TypeError and left the row stale.)"""
        fast = self._fast
        if fast is None:
            fast = self._fast = (_fid(self._key), _push_code(self._scalar))
        try:
            _h.combat_push_scalar(h, fast[0], fast[1], value)
        except (TypeError, ValueError, OverflowError):
            _drop(obj)

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
        if t is INDEX:
            v = operator.index(value)
            # combat_set_i takes an int64: a bigger int would escape _call
            # as pybind's TypeError and leave the row stale.
            if not -_INT64_LIMIT <= v < _INT64_LIMIT:
                raise OverflowError("index %d does not fit the int64 row" % v)
            return v
        if t is OFFSET:
            if isinstance(value, TGPoint3):
                return [float(value.x), float(value.y), float(value.z)]
            return []
        if t is POINT_OR_NONE:
            if value is None:
                return []
            if isinstance(value, TGPoint3):
                try:
                    return [float(value.x), float(value.y), float(value.z)]
                except (TypeError, ValueError, OverflowError):
                    pass
            return [0.0, 0.0, 0.0, 0.0]
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
        elif t is VEC3 or t is OFFSET or t is POINT_OR_NONE:
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
        if self._type is VEC3 or self._type is OFFSET \
                or self._type is POINT_OR_NONE:
            # A point-or-none dumps by its state: None, its 3 doubles, or 4
            # zeros (combat_dump), so the vector alone decides the state.
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


class NotifiedSetField(NativeField):
    """``RepairSubsystem._cannot_complete_notified``: a set of
    subsystems._notify_key keys -- Subsystem handles, or the id() of a
    member the mirror has no row for -- mirrored as the set of its
    Subsystem handles (the native repair piece's own keys; an id() key is
    none of its members). The set is edited IN PLACE: each writer calls
    ``push_field`` after; the native repair piece writes it back through its
    C applier (REPAIR_NOTIFIED)."""

    def __init__(self) -> None:
        super().__init__(set)

    def _encode(self, value):
        sub = _kind("Subsystem")
        return sorted({k for k in value
                       if type(k) is int and k >= 0
                       and (k >> _KIND_SHIFT) == sub})


class NativeFloatList(NativeField):
    """An ordered list of floats (TorpedoTube._reload_timers /
    _reload_advanced_at), pushed whole, every bit kept. The value must be a
    list (its readers store into it by index) of ints and floats (its
    readers do arithmetic on them); anything else drops the row. An
    in-place ``list[i] = v`` is invisible to a descriptor: each such
    writer calls ``push_field`` after mutating."""

    def __init__(self, key=None) -> None:
        super().__init__(list, key)

    def _encode(self, value):
        if type(value) is not list:
            raise TypeError("not a list: %r" % type(value).__name__)
        out = []
        for x in value:
            if isinstance(x, (str, bytes)) or not isinstance(x, (int, float)):
                raise TypeError("not a number: %r" % type(x).__name__)
            out.append(float(x))
        return out

    def _push(self, obj, h, value) -> None:
        try:
            v = self._encode(value)
        except (TypeError, ValueError, OverflowError):
            _drop(obj)
            return
        _call(obj, _h.combat_set_floats, h, _fid(self._key), v)

    def _matches(self, value, mirrored) -> bool:
        try:
            v = self._encode(value)
        except (TypeError, ValueError, OverflowError):
            return False
        return _hexes(v) == _hexes(mirrored)


class VelocityField(NativeField):
    """PhysicsObjectClass._velocity: the VEC3 every kernel reads, unchanged
    (a TGPoint3 or anything unpacking to x, y, z; None still drops the
    row), plus ``_velocity_state`` beside it for kernel M (native motion
    phase 2): 1 for a TGPoint3, 2 for anything else. The VEC3 push itself
    marks 1 (set_fv); a non-TGPoint3 value is re-marked 2 after it, so
    kernel M hands a drifter whose `_velocity` is, say, a tuple to Python,
    which raises reading v.x there. The audit checks both."""

    def __init__(self) -> None:
        super().__init__(VEC3)

    @staticmethod
    def _state(value) -> int:
        return 1 if isinstance(value, TGPoint3) else 2

    def _push(self, obj, h, value) -> None:
        super()._push(obj, h, value)
        if self._state(value) != 1 and obj.__dict__.get("_nslot") == h:
            _call(obj, _h.combat_set_i, h, _fid("_velocity_state"), 2)

    def audit(self, value, row) -> bool:
        return (self._matches(value, row[self._dump_key])
                and row["_velocity_state"] == self._state(value))


class NativeOptionalField(NativeField):
    """A mirrored attribute that may be ABSENT from the instance (its readers
    use ``getattr(obj, name, default)``: ShipClass._drift_velocity,
    PhysicsObjectClass._angular_space). Without a __get__ the class's
    descriptor itself would answer such a read, so this one reads the
    instance dict and raises AttributeError when the name is absent, as a
    plain attribute would. `absent` is the value the row holds meanwhile
    (the readers' default); ``del`` pushes it again."""

    def __init__(self, type_, absent) -> None:
        super().__init__(type_)
        self._absent = absent

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        try:
            return obj.__dict__[self._name]
        except KeyError:
            raise AttributeError(self._name) from None

    def __delete__(self, obj) -> None:
        try:
            del obj.__dict__[self._name]
        except KeyError:
            raise AttributeError(self._name) from None
        if _enabled:
            h = obj.__dict__.get("_nslot")
            if h is not None:
                if _get_ident() != _MAIN_IDENT:
                    _queue_push(obj, _repush_absent, self, self._name)
                else:
                    self._push(obj, h, self._absent)


class NativeClassDefault(NativeOptionalField):
    """A class constant an instance may override (PoweredSubsystem.
    POWER_MODE, DRAWS_DIRECT_FROM_MAIN, the cloak's
    CLOAK_RESERVE_DRAIN_PER_SECOND: the native power piece reads them per
    consumer, subsystem_step.h THE POWER PIECE). A read answers the
    instance's own value, else `default` (on the class too: ``PoweredSubsystem
    .POWER_MODE`` is the constant); an instance write pushes it, and the row
    holds `default` while there is none (NativeOptionalField's absent). A
    subclass with its own default declares its own NativeClassDefault: a
    plain class attribute would hide this one (and the object would get no
    row at all, _hidden_fields)."""

    def __get__(self, obj, owner=None):
        if obj is None:
            return self._absent
        return obj.__dict__.get(self._name, self._absent)


def _repush_absent(obj, field) -> None:
    h = obj.__dict__.get("_nslot")
    if _enabled and h is not None and field._name not in obj.__dict__:
        field._push(obj, h, field._absent)


class SpeedSetpointField(NativeField):
    """ShipClass._speed_setpoint, kernel M's commanded speed: None, or
    SetSpeed's ``(speed, direction, frame)``. Pushed as a float list in one
    ``combat_set_floats`` call: None is [], the tuple
    [float(speed), float(d.x), float(d.y), float(d.z), float(frame)], and
    anything that does not unpack and convert so is [0.0] * 6
    (unrepresentable: the kernel takes the Python path, which raises there
    as today). Never drops the row. Always rebound, never mutated."""

    def __init__(self) -> None:
        super().__init__(list)

    def _encode(self, value):
        if value is None:
            return []
        try:
            speed, d, frame = value
            # Python uses the speed AS IS (compares and ramps it: a str
            # raises there, an int is compared exactly and can come back as
            # the new _current_speed), and compares the frame with
            # ``frame == DIRECTION_MODEL_SPACE`` ("0" is not 0): only a
            # float speed and a number frame (whose float() compares the
            # same) are the kernel's. The direction is float()ed by Python
            # itself (TGPoint3(direction.x, ...)), as here.
            if type(speed) is not float or type(frame) not in _NUMBERS:
                return [0.0] * 6
            return [speed, float(d.x), float(d.y), float(d.z),
                    float(frame)]
        except (TypeError, ValueError, AttributeError, OverflowError):
            return [0.0] * 6

    def _push(self, obj, h, value) -> None:
        _call(obj, _h.combat_set_floats, h, _fid(self._key),
              self._encode(value))

    def _matches(self, value, mirrored) -> bool:
        return _hexes(self._encode(value)) == _hexes(mirrored)


class MotionVelField(NativeField):
    """ShipClass._motion_vel, the motion law's velocity vector
    (ship_motion.step_vector_velocity): None, or ``(vx, vy, vz, speed)``,
    the vector and the speed it was last stepped to. Pushed as a float list
    in one ``combat_set_floats`` call: None is [], a tuple of four floats
    its four values, and anything else [0.0] * 5 (unrepresentable: the
    kernel takes the Python path). Never drops the row. Always rebound,
    never mutated."""

    def __init__(self) -> None:
        super().__init__(list)

    def _encode(self, value):
        if value is None:
            return []
        if type(value) is tuple and len(value) == 4 and \
                all(type(x) is float for x in value):
            return list(value)
        return [0.0] * 5

    def _push(self, obj, h, value) -> None:
        _call(obj, _h.combat_set_floats, h, _fid(self._key),
              self._encode(value))

    def _matches(self, value, mirrored) -> bool:
        return _hexes(self._encode(value)) == _hexes(mirrored)


class AccelerationField(NativeField):
    """ShipClass._acceleration, the motion law's commanded acceleration
    (ship_motion.step_vector_velocity / _no_thrust; GetAccelerationTG):
    None, or ``(ax, ay, az)``. Pushed as a float list in one
    ``combat_set_floats`` call: None is [], a tuple of three floats its
    three values, and anything else [0.0] * 4 (unrepresentable: the kernel
    takes the Python path). Kernel M writes it back only when its new value
    differs bitwise from this one. Never drops the row. Always rebound,
    never mutated."""

    def __init__(self) -> None:
        super().__init__(list)

    def _encode(self, value):
        if value is None:
            return []
        if type(value) is tuple and len(value) == 3 and \
                all(type(x) is float for x in value):
            return list(value)
        return [0.0] * 4

    def _push(self, obj, h, value) -> None:
        _call(obj, _h.combat_set_floats, h, _fid(self._key),
              self._encode(value))

    def _matches(self, value, mirrored) -> bool:
        return _hexes(self._encode(value)) == _hexes(mirrored)


def _goal_point(p) -> bool:
    """A TGPoint3 whose three components are floats (what kernel M reads)."""
    return (type(p) is TGPoint3 and type(p.x) is float
            and type(p.y) is float and type(p.z) is float)


class TurnGoalField(NativeField):
    """ShipClass._turn_goal, the stored turn goal kernel M steers
    (ShipClass._steer_turn_goal): None, or ``[spec, owned_setpoint]``.
    Only the SPEC is mirrored, as a float list pushed in one
    ``combat_set_floats`` call:

      []                                  None
      [1, px, py, pz]                     ("loc", TGPoint3)
      [2, pf(3), pt(3), 0]                ("dirs", body_pf, pt, None, None)
      [2, pf(3), pt(3), 1, sf(3), st(3)]  ("dirs", body_pf, pt, body_sf, st)
      [0]                                 anything else: unrepresentable,
                                          the kernel hands the row back
                                          (reason TurnGoal)

    The goal must be a list of two (Python stores ``goal[1] = target``),
    the spec a tuple of exactly that shape, every point a TGPoint3 of
    floats. Pushed on rebind only: the steering's ``goal[1] = target`` is
    in place and never changes the spec. The kernel steers a goal whenever
    it is representable and the row has a setpoint, where Python's step
    asks ``goal[1] is setpoint``; the two agree because every writer that
    rebinds the setpoint to a non-None object other than the steering
    itself also clears the goal (ShipClass.SetTargetAngularVelocityDirect,
    SetTargetAngularVelocityFraction, CompleteStop). Never drops the row."""

    def __init__(self) -> None:
        super().__init__(list)

    def _encode(self, value):
        if value is None:
            return []
        if type(value) is not list or len(value) != 2:
            return [0.0]
        spec = value[0]
        if type(spec) is not tuple or not spec or type(spec[0]) is not str:
            return [0.0]
        if spec[0] == "loc" and len(spec) == 2 and _goal_point(spec[1]):
            p = spec[1]
            return [1.0, p.x, p.y, p.z]
        if spec[0] != "dirs" or len(spec) != 5:
            return [0.0]
        _kind, pf, pt, sf, st = spec
        if not (_goal_point(pf) and _goal_point(pt)):
            return [0.0]
        out = [2.0, pf.x, pf.y, pf.z, pt.x, pt.y, pt.z]
        if sf is None and st is None:
            return out + [0.0]
        if _goal_point(sf) and _goal_point(st):
            return out + [1.0, sf.x, sf.y, sf.z, st.x, st.y, st.z]
        return [0.0]

    def _push(self, obj, h, value) -> None:
        _call(obj, _h.combat_set_floats, h, _fid(self._key),
              self._encode(value))

    def _matches(self, value, mirrored) -> bool:
        return _hexes(self._encode(value)) == _hexes(mirrored)


_NUMBERS = (int, float, bool)


class AngularSpaceField(NativeOptionalField):
    """PhysicsObjectClass._angular_space, the frame a drifter's spin was set
    in. Its one reader, drift.step, tests ``getattr(obj, "_angular_space",
    DIRECTION_WORLD_SPACE) == DIRECTION_MODEL_SPACE``, so the row holds that
    test's answer: 0 (model) or 1 (world) for an int or a bool, exact for
    any size. Anything else (0.5, "0": an int() would read model where
    Python's == reads world) is 2, unrepresentable: the kernel hands the
    row to Python (native motion phase 2, Task 5, Review Focus 4). Never
    drops the row."""

    def __init__(self) -> None:
        super().__init__(int, absent=1)

    def _encode(self, value):
        if type(value) is int or type(value) is bool:
            return 0 if value == 0 else 1
        return 2


class PresenceField(NativeField):
    """An attribute the kernel reads only as ``is not None``
    (ShipClass._insystem_warp_transit, the in-system warp flight): pushes
    ``0 if value is None else 1``."""

    def __init__(self) -> None:
        super().__init__(int)

    def _encode(self, value):
        return 0 if value is None else 1


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
    """Mixin for a passive_state descriptor that also pushes: the base
    descriptor's wake first, then the push. ``_native`` is the NativeField
    that knows the type and the row key."""

    def _init_native(self, type_, key) -> None:
        self._native = NativeField(type_, key)

    def __set_name__(self, owner, name) -> None:
        super().__set_name__(owner, name)
        self._native.__set_name__(owner, name)

    def _after_set(self, obj, value) -> None:
        if _enabled:
            h = obj.__dict__.get("_nslot")
            if h is not None:
                native = self._native
                if _get_ident() != _MAIN_IDENT:
                    _queue_push(obj, _repush_native, native, native._name)
                elif native._scalar is None:
                    native._push(obj, h, value)
                else:
                    native._push_scalar(obj, h, value)


class NativeWakeField(NativeWrapped, WakeField):
    """WakeField's wake (passive_state), then the push."""

    def __init__(self, type_=float, key=None) -> None:
        self._init_native(type_, key)

    def __set__(self, obj, value) -> None:
        WakeField.__set__(self, obj, value)
        self._after_set(obj, value)


#: `_watch_checks` of a pulse weapon whose watcher it does not own: K0 then
#: always hands the watcher line to Python (a WATCH record), whatever it is.
WATCH_ALWAYS = -1


def _owns_watcher(weapon, watcher) -> bool:
    from engine.appc.float_range_watcher import FloatRangeWatcher
    return type(watcher) is FloatRangeWatcher \
        and watcher.__dict__.get("_owner") is weapon


def push_watch_value(weapon, value) -> None:
    """A pulse weapon's owned charge watcher committed `value` as its
    `_value` (FloatRangeWatcher._update, an adoption): mirror it as the
    weapon row's `_watch_value`, the old value of K0's WATCH entry (combat
    fire events Task 4). No instance attribute: the watcher holds it."""
    if _enabled:
        h = weapon.__dict__.get("_nslot")
        if h is not None:
            if _off_main():     # the watcher's value at the drain
                _queue_push(weapon, _push_watch_value_of_arg, None,
                            "_watch_value")
                return
            _call(weapon, _h.combat_set_f, h, _fid("_watch_value"),
                  float(value))


def _push_watch_value_of_arg(weapon, _arg) -> None:
    _push_watch_value_of(weapon)


def _push_watch_value_of(weapon) -> None:
    """`_watch_value` from the watcher the weapon owns now (0.0 for one it
    does not own: K0 never reads it then, it hands the weapon back)."""
    watcher = weapon.__dict__.get("_charge_watcher")
    push_watch_value(weapon, watcher._value
                     if _owns_watcher(weapon, watcher) else 0.0)


class ChargeWatcherField:
    """PulseWeapon._charge_watcher: keeps `_watch_checks` (what K0 reads to
    decide whether the watcher line needs Python) true to the watcher the
    weapon holds, when one is assigned after construction too. No __get__:
    reads are plain instance-dict reads.

    A plain FloatRangeWatcher with no owner (or this weapon) is adopted: its
    `_owner` becomes the weapon, so each check it adds or removes pushes
    the count, and each value it commits pushes `_watch_value`. Anything
    else -- a subclass (its own `_update`, which K0's logged `_value` store
    would skip), a watcher another weapon owns -- sets WATCH_ALWAYS: K0 never stands in for it (one naming this weapon
    as its owner is released, so its checks cannot push here). A previous
    watcher this weapon owned is released (its checks no longer push here).
    Cost: only at assignment; the switch-off path stores the same
    values."""

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __set__(self, obj, value) -> None:
        from engine.appc.float_range_watcher import FloatRangeWatcher
        d = obj.__dict__
        old = d.get(self._name)
        d[self._name] = value
        if old is not None and old is not value:
            od = getattr(old, "__dict__", None)
            if od is not None and od.get("_owner") is obj:
                del od["_owner"]        # back to the class default, None
        if type(value) is FloatRangeWatcher \
                and value.__dict__.get("_owner") in (None, obj):
            if value.__dict__.get("_owner") is None:
                value._owner = obj
            obj._watch_checks = len(value._checks)
            push_watch_value(obj, value._value)
        else:
            # Not adopted: if it names this weapon as its owner anyway
            # (FloatRangeWatcher(owner=weapon)), release it, or its next
            # Add/RemoveRangeCheck would overwrite WATCH_ALWAYS.
            vd = getattr(value, "__dict__", None)
            if vd is not None and vd.get("_owner") is obj:
                del vd["_owner"]        # back to the class default
            obj._watch_checks = WATCH_ALWAYS


# ── Native damage: the mirror (spec 2026-11-02-native-damage-design.md §4.1) ─
#
# What the native hit and condition chain (native/src/combat/.../damage.h)
# read that no kernel read before: a ShieldSubsystem's face lists, the
# subsystem flags and threshold state, the repair-queue membership, each
# condition watcher's check count and value, the ship's _hurtable, and two
# class flags saying which stock rules a class follows (dmg_class,
# dmg_ship). The face lists are written IN PLACE by Python: every writer
# (damage-map-refresh §6, W1-W7) pushes after mutating, before anything it
# then posts.

#: dmg_class: a subsystem class following ShipSubsystem's leaf predicates,
#: WeaponSystem's aggregate ones, or neither (the chain hands it to Python).
DMG_PYTHON, DMG_LEAF, DMG_AGGREGATE = -1, 0, 1
#: cond_watch_checks / comb_watch_checks: no watcher in the slot, or one the
#: native chain cannot stand in for (not a plain FloatRangeWatcher, or not
#: this subsystem's own). Otherwise the watcher's check count.
COND_WATCH_NONE, COND_WATCH_FOREIGN = -2, -1
#: which (effect_queue.WATCH_*) -> (slot attribute, checks field, value
#: field).
_COND_WATCH_SLOTS = {
    _effect_queue.WATCH_CONDITION: ("_condition_watcher",
                                    "cond_watch_checks", "cond_watch_value"),
    _effect_queue.WATCH_COMBINED: ("_combined_watcher",
                                   "comb_watch_checks", "comb_watch_value"),
}


def _cond_watch_state(sub, which) -> tuple:
    """(checks, value) the row holds for `sub`'s watcher `which`."""
    w = sub.__dict__.get(_COND_WATCH_SLOTS[which][0])
    if w is None:
        return COND_WATCH_NONE, 0.0
    from engine.appc.float_range_watcher import FloatRangeWatcher
    wd = getattr(w, "__dict__", None)
    if (type(w) is not FloatRangeWatcher or wd.get("_cond_owner") is not sub
            or wd.get("_cond_which") != which):
        return COND_WATCH_FOREIGN, 0.0
    checks = wd.get("_checks")
    value = wd.get("_value")
    if type(checks) is not dict or type(value) is not float:
        return COND_WATCH_FOREIGN, 0.0
    return len(checks), value


def push_cond_watch(sub, which) -> None:
    """`sub`'s condition watcher `which` changed: assigned, or a check
    added or removed (FloatRangeWatcher, `_cond_owner`)."""
    if not _enabled:
        return
    h = sub.__dict__.get("_nslot")
    if h is None:
        return
    if _off_main():
        _queue_push(sub, push_cond_watch, which, "cond_watch")
        return
    n, v = _cond_watch_state(sub, which)
    _slot, checks_field, value_field = _COND_WATCH_SLOTS[which]
    _call(sub, _h.combat_set_i, h, _fid(checks_field), n)
    if "_nslot" in sub.__dict__:
        _call(sub, _h.combat_set_f, h, _fid(value_field), v)


def push_cond_watch_value(sub, which, value) -> None:
    """An owned condition watcher committed `value` (_update_queued)."""
    if _enabled:
        h = sub.__dict__.get("_nslot")
        if h is not None:
            if _off_main():     # the watcher's state at the drain
                _queue_push(sub, push_cond_watch, which, "cond_watch")
                return
            _call(sub, _h.combat_set_f, h,
                  _fid(_COND_WATCH_SLOTS[which][2]), value)


class CondWatcherField:
    """ShipSubsystem._condition_watcher / _combined_watcher: a plain
    FloatRangeWatcher assigned here is ADOPTED (its `_cond_owner` is the
    subsystem, `_cond_which` the slot), so each check it adds or removes and
    each value it commits pushes the row; anything else reads
    COND_WATCH_FOREIGN (the native chain then hands that subsystem's writes
    to Python). A watcher replaced is released. No __get__."""

    def __init__(self, which) -> None:
        self._which = which

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __set__(self, obj, value) -> None:
        from engine.appc.float_range_watcher import FloatRangeWatcher
        d = obj.__dict__
        old = d.get(self._name)
        d[self._name] = value
        if old is not None and old is not value:
            od = getattr(old, "__dict__", None)
            if od is not None and od.get("_cond_owner") is obj:
                del od["_cond_owner"]
                del od["_cond_which"]
        if (type(value) is FloatRangeWatcher
                and value.__dict__.get("_cond_owner") is None):
            value._cond_owner = obj
            value._cond_which = self._which
        push_cond_watch(obj, self._which)


class RampField(NativeField):
    """ShieldSubsystem._ramp_fraction, a list of floats or None (no charge
    tick yet: ApplyDamage reads the face live): pushed as `_ramp_fraction`
    (0.0 for None) and `_ramp_set` (1.0 where a float). Written in place by
    the charge tick, which pushes (push_field)."""

    def __init__(self) -> None:
        super().__init__(list)

    def _encode(self, value):
        if type(value) is not list:
            raise TypeError("not a list: %r" % type(value).__name__)
        vals, sets = [], []
        for x in value:
            if x is None:
                vals.append(0.0)
                sets.append(0.0)
                continue
            if isinstance(x, (str, bytes)) or not isinstance(x, (int, float)):
                raise TypeError("not a number: %r" % type(x).__name__)
            vals.append(float(x))
            sets.append(1.0)
        return vals, sets

    def _push(self, obj, h, value) -> None:
        try:
            vals, sets = self._encode(value)
        except (TypeError, ValueError, OverflowError):
            _drop(obj)
            return
        _call(obj, _h.combat_set_floats, h, _fid("_ramp_fraction"), vals)
        if "_nslot" in obj.__dict__:
            _call(obj, _h.combat_set_floats, h, _fid("_ramp_set"), sets)

    def audit(self, value, row) -> bool:
        try:
            vals, sets = self._encode(value)
        except (TypeError, ValueError, OverflowError):
            return False
        return (_hexes(vals) == _hexes(row["_ramp_fraction"])
                and _hexes(sets) == _hexes(row["_ramp_set"]))


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


class WarpSlotField(MountSlotField):
    """ShipClass._warp_engine_subsystem: a MountSlotField whose every write
    also re-pushes the ship's `arriving` flag (Weapon.FireDumb's warp-in
    hold reads the slot's slide; launch deferral)."""

    def __set__(self, obj, value) -> None:
        super().__set__(obj, value)
        push_arriving(obj)


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


#: EngageStateField's encodings: engage_kind (mirror.h).
ENGAGE_NONE, ENGAGE_HOLD, ENGAGE_TOW = 0, 1, 2
_ENGAGE_KEYS = {ENGAGE_HOLD: "hold_point", ENGAGE_TOW: "tow_offset"}


class EngageStateField(NativeField):
    """``TractorBeamSystem._engage_state``: None, ``{"hold_point": p}`` or
    ``{"tow_offset": p}`` with p a TGPoint3 -- the geometry the tractor
    force captured (tractor_force.h). Pushed as engage_kind (ENGAGE_*) and
    engage_point; anything else is not representable and drops the row.
    The force step writes the mirror itself and stores the dict quietly
    (tractor_force_step); a native StopFiring's `_engage_state = None` is a
    plain store (_quiet_setter)."""

    def __init__(self) -> None:
        super().__init__(None)

    @staticmethod
    def _parse(value):
        if value is None:
            return ENGAGE_NONE, (0.0, 0.0, 0.0)
        if type(value) is not dict or len(value) != 1:
            raise TypeError("engage state: %r" % (value,))
        for kind, key in _ENGAGE_KEYS.items():
            p = value.get(key)
            if isinstance(p, TGPoint3):
                return kind, (float(p.x), float(p.y), float(p.z))
        raise TypeError("engage state: %r" % (value,))

    def _push(self, obj, h, value) -> None:
        try:
            kind, point = self._parse(value)
        except TypeError:
            _drop(obj)
            return
        _call(obj, _h.combat_set_i, h, _fid("engage_kind"), kind)
        if "_nslot" in obj.__dict__:
            _call(obj, _h.combat_set_fv, h, _fid("engage_point"), list(point))

    def audit(self, value, row) -> bool:
        try:
            kind, point = self._parse(value)
        except TypeError:
            return False
        if row["engage_kind"] != kind:
            return False
        return kind == ENGAGE_NONE or \
            _hexes(row["engage_point"]) == _hexes(point)


class HasShieldsField(NativeFloatList):
    """``ShieldSubsystem._max_shields``: the face caps, mirrored as a list
    (the native hit's ramp reads them), and every rebind re-pushes the
    derived ``has_shields`` flag too. The flag is whatever the subsystem's
    own ``HasShields()`` answers -- the expression is never re-typed here.
    The in-place ``_max_shields[f] = v`` write (``SetMaxShields``) cannot be
    seen by a descriptor and pushes both itself."""

    def __set__(self, obj, value) -> None:
        NativeFloatList.__set__(self, obj, value)
        push_has_shields(obj)


def push_has_shields(sub) -> None:
    """Re-push the ShieldSubsystem's has_shields flag."""
    if _enabled:
        h = sub.__dict__.get("_nslot")
        if h is not None:
            if _off_main():
                _queue_push(sub, _push_has_shields_arg, None, "has_shields")
                return
            try:
                v = int(sub.HasShields())
            except (TypeError, ValueError, OverflowError):
                _drop(sub)  # not representable: never leave a stale row
                return
            _call(sub, _h.combat_set_i, h, _fid("has_shields"), v)


def _push_has_shields_arg(sub, _arg) -> None:
    push_has_shields(sub)


# ── Owned watchers: the generator's seven, the plant's two (phase 6 A1) ────
# The native shield and power pieces (subsystem_step.h THE SHIELD PIECE,
# THE POWER PIECE) decide each watcher's crossing themselves, so they need
# every watcher's committed `_value` and its checks. An owning subsystem
# ADOPTS each plain FloatRangeWatcher it holds (the watcher's `_watch_owner`
# is the subsystem, `_watch_index` its place: a generator's
# `_shield_watchers[i]` through ShieldWatchersField, a plant's main (0) and
# backup (1) battery watcher through PowerWatcherField), and an adopted
# watcher pushes its owner's row on every value it commits (`_update`) and
# every check it adds or removes (push_owned_watch). The owner's "ok" flag
# is 1 only when every watcher is a FloatRangeWatcher adopted by it at its
# index, with no owner of another kind; anything else is 0 and the piece is
# Python's. A script patching the watcher's methods is not honoured (spec §3
# "Mods and patches (Part A)").

_SHIELD_WATCHERS = 7
_NOT_READY = (0, [], [])


def _shield_watch_state(sub):
    """(ok, values, checks) as the mirror holds them (mirror.h
    shield_watch_*): each watcher's `_value`, and per watcher its check
    count then (threshold, direction code) per check -- 2 for FRW_BELOW,
    1 for FRW_ABOVE, 3 for anything else, in FloatRangeWatcher._crossed's
    order of tests."""
    ws = sub.__dict__.get("_shield_watchers")
    if type(ws) is not list or len(ws) != _SHIELD_WATCHERS:
        return _NOT_READY
    return _owned_watch_state(sub, ws)


def _owned_watch_state(sub, ws):
    """(ok, values, checks) of the watchers `ws` (a list, in index order)
    that `sub` owns: the shield generator's and the plant's encoding."""
    from engine.appc.float_range_watcher import FloatRangeWatcher
    below, above = FloatRangeWatcher.FRW_BELOW, FloatRangeWatcher.FRW_ABOVE
    values, checks = [], []
    for i, w in enumerate(ws):
        if type(w) is not FloatRangeWatcher:
            return _NOT_READY
        wd = w.__dict__
        if (wd.get("_watch_owner") is not sub
                or wd.get("_watch_index") != i
                or wd.get("_owner") is not None
                or wd.get("_cond_owner") is not None):
            return _NOT_READY
        v = wd.get("_value")
        cd = wd.get("_checks")
        if type(v) is not float or type(cd) is not dict:
            return _NOT_READY
        values.append(v)
        checks.append(float(len(cd)))
        for entry in cd.values():
            if type(entry) is not tuple or len(entry) != 3:
                return _NOT_READY
            t, d = entry[0], entry[1]
            if type(t) is not float or type(d) is not int:
                return _NOT_READY
            checks.append(t)
            checks.append(2.0 if d == below else 1.0 if d == above else 3.0)
    return 1, values, checks


def push_shield_watch(sub) -> None:
    """The generator's whole watcher state (_shield_watch_state): a watcher
    adopted or released, a check added or removed."""
    if not _enabled:
        return
    h = sub.__dict__.get("_nslot")
    if h is None:
        return
    if _off_main():
        _queue_push(sub, _push_shield_watch_arg, None, "shield_watch")
        return
    ok, values, checks = _shield_watch_state(sub)
    _call(sub, _h.combat_set_i, h, _fid("shield_watch_ok"), ok)
    if ok and "_nslot" in sub.__dict__:
        _call(sub, _h.combat_set_floats, h, _fid("shield_watch_values"),
              values)
        if "_nslot" in sub.__dict__:
            _call(sub, _h.combat_set_floats, h, _fid("shield_watch_checks"),
                  checks)


def _push_shield_watch_arg(sub, _arg) -> None:
    push_shield_watch(sub)


def push_shield_watch_values(sub) -> None:
    """An adopted watcher committed a value (FloatRangeWatcher._update):
    the seven values. Anything unexpected takes the whole push."""
    if not _enabled:
        return
    d = sub.__dict__
    h = d.get("_nslot")
    if h is None:
        return
    if _off_main():
        _queue_push(sub, _push_shield_watch_arg, None, "shield_watch")
        return
    try:
        values = [float(w.__dict__["_value"]) for w in d["_shield_watchers"]]
    except Exception:       # noqa: BLE001 -- the whole push decides
        push_shield_watch(sub)
        return
    if len(values) != _SHIELD_WATCHERS:
        push_shield_watch(sub)
        return
    _call(sub, _h.combat_set_floats, h, _fid("shield_watch_values"), values)


def _adopt_watchers(sub, ws) -> None:
    """Each plain FloatRangeWatcher of `ws` nobody adopted: `sub`'s, at its
    index (an adopted one moved in the list takes its new index)."""
    from engine.appc.float_range_watcher import FloatRangeWatcher
    if type(ws) is not list:
        return
    for i, w in enumerate(ws):
        if type(w) is not FloatRangeWatcher:
            continue
        wd = w.__dict__
        owner = wd.get("_watch_owner")
        if owner is None or owner is sub:
            wd["_watch_owner"] = sub
            wd["_watch_index"] = i


def _release_watchers(sub, old, new) -> None:
    """The watchers of the `old` list that `sub` adopted and `new` no longer
    holds: released."""
    if type(old) is not list:
        return
    keep = {id(w) for w in new} if type(new) is list else set()
    for w in old:
        wd = getattr(w, "__dict__", None)
        if (wd is not None and wd.get("_watch_owner") is sub
                and id(w) not in keep):
            del wd["_watch_owner"]
            wd.pop("_watch_index", None)


# The plant's two (THE POWER PIECE): `_main_battery_watcher` is index 0,
# `_backup_battery_watcher` index 1, encoded as power_watch_*.
_BATTERY_WATCHERS = ("_main_battery_watcher", "_backup_battery_watcher")


def _power_watch_state(plant):
    """(ok, values, checks) of the plant's battery watchers (mirror.h
    power_watch_*), as _shield_watch_state's."""
    d = plant.__dict__
    ws = [d.get(name) for name in _BATTERY_WATCHERS]
    return _owned_watch_state(plant, ws)


def push_power_watch(plant) -> None:
    """The plant's whole battery-watcher state: a watcher adopted or
    released, a check added or removed, a value committed."""
    if not _enabled:
        return
    h = plant.__dict__.get("_nslot")
    if h is None:
        return
    if _off_main():
        _queue_push(plant, _push_power_watch_arg, None, "power_watch")
        return
    ok, values, checks = _power_watch_state(plant)
    _call(plant, _h.combat_set_i, h, _fid("power_watch_ok"), ok)
    if ok and "_nslot" in plant.__dict__:
        _call(plant, _h.combat_set_floats, h, _fid("power_watch_values"),
              values)
        if "_nslot" in plant.__dict__:
            _call(plant, _h.combat_set_floats, h, _fid("power_watch_checks"),
                  checks)


def _push_power_watch_arg(plant, _arg) -> None:
    push_power_watch(plant)


def push_owned_watch(owner, values_only: bool) -> None:
    """An adopted watcher's owner (FloatRangeWatcher._watch_owner): it
    committed a value (`values_only`) or its checks changed. A shield
    generator's seven or a plant's two."""
    if "_shield_watchers" in owner.__dict__:
        if values_only:
            push_shield_watch_values(owner)
        else:
            push_shield_watch(owner)
    else:
        push_power_watch(owner)


class PowerWatcherField(NativeField):
    """``PowerSubsystem._main_battery_watcher`` (index 0) /
    ``_backup_battery_watcher`` (1): adopts the watcher (releasing the one it
    replaces) and pushes the plant's battery-watcher state."""

    def __init__(self, index: int) -> None:
        super().__init__(list, key="power_watch_ok")
        self._index = index

    def __set__(self, obj, value) -> None:
        d = obj.__dict__
        old = d.get(self._name)
        d[self._name] = value
        if old is not value:
            wd = getattr(old, "__dict__", None)
            if wd is not None and wd.get("_watch_owner") is obj:
                del wd["_watch_owner"]
                wd.pop("_watch_index", None)
        self._adopt(obj, value)
        push_power_watch(obj)

    def _adopt(self, obj, w) -> None:
        from engine.appc.float_range_watcher import FloatRangeWatcher
        if type(w) is FloatRangeWatcher:
            wd = w.__dict__
            owner = wd.get("_watch_owner")
            if owner is None or owner is obj:
                wd["_watch_owner"] = obj
                wd["_watch_index"] = self._index

    def _push(self, obj, h, value) -> None:      # _push_all / resync
        self._adopt(obj, value)
        push_power_watch(obj)

    def audit(self, value, row) -> bool:
        return True     # _audit_power_watch, which needs the plant


def _audit_power_watch(plant, row, name) -> None:
    """The battery-watcher state as the watchers hold it NOW."""
    ok, values, checks = _power_watch_state(plant)
    if row["power_watch_ok"] != ok:
        _failures.append((name, "power_watch_ok"))
    elif ok:
        if _hexes(values) != _hexes(row["power_watch_values"]):
            _failures.append((name, "power_watch_values"))
        if _hexes(checks) != _hexes(row["power_watch_checks"]):
            _failures.append((name, "power_watch_checks"))


class ShieldWatchersField(NativeField):
    """``ShieldSubsystem._shield_watchers``: adopts its watchers and pushes
    the generator's watcher state (the section comment above). An in-place
    ``_shield_watchers[i] = w`` is invisible to it; nothing writes one."""

    def __init__(self) -> None:
        super().__init__(list, key="shield_watch_ok")

    def __set__(self, obj, value) -> None:
        d = obj.__dict__
        old = d.get(self._name)
        d[self._name] = value
        _release_watchers(obj, old, value)
        _adopt_watchers(obj, value)
        push_shield_watch(obj)

    def _push(self, obj, h, value) -> None:      # _push_all / resync
        _adopt_watchers(obj, value)
        push_shield_watch(obj)

    def audit(self, value, row) -> bool:
        return True     # _audit_shield_watch, which needs the generator


def _audit_shield_watch(sub, row, name) -> None:
    """The watcher state as the watchers hold it NOW (a check added behind
    their methods is caught, not only a missed push)."""
    ok, values, checks = _shield_watch_state(sub)
    if row["shield_watch_ok"] != ok:
        _failures.append((name, "shield_watch_ok"))
    elif ok:
        if _hexes(values) != _hexes(row["shield_watch_values"]):
            _failures.append((name, "shield_watch_values"))
        if _hexes(checks) != _hexes(row["shield_watch_checks"]):
            _failures.append((name, "shield_watch_checks"))


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
    if kind == "Object":
        _part_registered(obj, h)
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

    The classes K2 has seen go too: with no row left, none has been seen
    (its class flags are pushed with the next row of it)."""
    for obj in list(_registry.values()):
        obj.__dict__.pop("_nslot", None)
    _registry.clear()
    _discard_pending_rows()
    _forget_part_caches()
    _part_pending.clear()
    _part_leafed.clear()
    _part_polled.clear()
    bump_part_gen()     # the cleared mirror's generation is back at 1
    torpedo_table_mark_dirty()
    _k2_seen.clear()
    _k2_seen_set.clear()
    # Kernel M's class watch reads _k2_seen too: it rebuilds on a new
    # generation (native_motion._watch_classes).
    global _seen_gen
    _seen_gen += 1


# ── Deferred frees and off-main pushes (spec 2026-11-03-kernels-off-the-lock
# §2 goal 2, §4, ruling R2) ────────────────────────────────────────────────
#
# Nothing may mutate the mirror tables while a kernel computes (Task 3
# computes with the GIL released). So:
#
# - FREES are recorded, never applied where they happen: a mirror row (a
#   finalizer, a replaced Profile row) and an ObjectClass's transform slot
#   (objects.py's finalizer), with the row's launch module
#   (combat_unregister's k1_launch_module_release) and its part caches. A
#   pending row stays valid, so its handle is not reused, until the drain.
#   The one exception is a _drop on the main thread: a LIVE object's row
#   leaving the mirror mid-walk is the kernels' "row gone" protocol, so it
#   frees at once, between records, as before (off the main thread the
#   whole _drop is queued, like a push).
# - PUSHES made on a thread other than the main one (a finalizer or an SDK
#   __del__ that ran there: ConditionPulseReady's RemoveRangeCheck pushes
#   `_watch_checks`) are queued. Main-thread pushes keep their direct path.
#   A queued push re-pushes what the object holds AT THE DRAIN, never the
#   value it recorded: a main-thread write in between must not be undone.
#
# drain() applies them, frees first, each in recorded order. Drain points:
# the start of each kernel session (no-op while one is open: a nested
# session's start never frees under its parent), host_loop's tick boundary,
# the GameLoop's own end-of-tick, a paused frame (host_loop.run), the
# per-tick mirror audit (DAUNTLESS_NATIVE_AUDIT, GameLoop.tick), both
# mission swaps and reset(). forget_rows() (after a test's combat_clear
# rebuilt the mirror) applies no pending row free or push, only the
# transform-slot frees.
#
# A queued push that raises at the drain is logged (once per site) and the
# drain carries on, as the push did inside the __del__ that made it (Python
# reports an exception there and carries on; roadmap decision 13's rule for
# a queued flush). Two stalls are logged once each: more than
# PENDING_FREES_WARN frees pending (no tick ran to drain them: a menu, a
# pre-boot screen), and a drain at a tick boundary skipped because a kernel
# session is still open there (a leaked session: K1 nests, so the next begin
# does not throw).
#
# Both lists are deques: append and popleft are atomic under the GIL on any
# thread, and the Python a drain runs may record more.

_get_ident = threading.get_ident
_MAIN_IDENT = threading.main_thread().ident
# (row handle or None, (store, transform handle) or None)
_pending_frees: collections.deque = collections.deque()
# (weakref to the object, re-push function, its argument, label)
_pending_pushes: collections.deque = collections.deque()
# More pending frees than this is logged once (a stalled drain).
PENDING_FREES_WARN = 10_000
# The keys _log_once has logged (reset() forgets them).
_logged_once: set = set()


def _log_once(key, message: str) -> None:
    """One stderr line per `key`, the first time."""
    if key in _logged_once:
        return
    _logged_once.add(key)
    sys.stderr.write("[native-combat] %s\n" % message)


def _k1_no_fire(why: str, message: str) -> None:
    """Fire control's driver-side no-fire (fire control native only, R2,
    R3): counted under `why` (_K1_PY_NO_FIRE) and logged once per why."""
    _k1_no_fire_py[why] += 1
    _log_once(("k1_no_fire", why), "fire control: %s -- does not fire "
              "(no_fire %s)" % (message, why))


#: What each of the kernel's K1NoFire whys means, for its one log line.
_K1_NO_FIRE_TEXT = {
    "tractor_row": "a tractor walk the mirror cannot read",
    "stale_row": "a row the walk reads is unnamed or freed",
    "stub_or_unplaced": "a ship with no real IsDead or no valid transform",
    "pulse_ship_target": "a pulse system with no live target-list entry",
    "pulse_module": "a pulse module unresolved, or its power setting out "
                    "of range",
    "ammo_row": "a torpedo ammo slot names no live ammo row",
    "part_stale": "a posed ship's part slot is not current (its part "
                  "resolution raised: retried every step)",
    "unslotted_ship": "a ship in the pump has no mirror row",
    "gate": "a pump gate the mirror could not answer",
    "structure": "a weapon system's child structure the walk cannot follow",
    "not_k1_system": "a held weapon system of no fire-control kind",
    "can_fire": "a weapon's CanFire the mirror could not answer",
    "decision": "a Fire decision the mirror could not make",
    "launch": "a launch the kernel cannot make (k1_launch_reasons)",
    "walk": "a mid-walk read the mirror could not answer",
    "reseed": "single fire's reseed with a child the mirror cannot name "
              "(skipped)",
    "retry": "a retry target the mirror cannot read (treated as gone)",
    "is_dead": "a retry target whose IsDead the mirror cannot answer "
               "(treated as gone)",
}


def _k1_log_kernel_no_fires(names) -> None:
    """The kernel's no-fire whys counted for the first time (a DONE
    record's no_fire_new): one line each (fire control native only, R2)."""
    for name in names:
        _log_once(("k1_no_fire", name), "fire control: %s -- does not fire "
                  "(no_fire %s)" % (_K1_NO_FIRE_TEXT.get(name, name), name))


def _off_main() -> bool:
    return _get_ident() != _MAIN_IDENT


def defer_free(h=None, store=None, xform=None) -> None:
    """Record a free: row `h` and/or transform slot `xform` of `store`.
    Never raises (a finalizer body)."""
    _pending_frees.append((h, None if xform is None else (store, xform)))
    if len(_pending_frees) > PENDING_FREES_WARN:
        try:
            _log_once("pending_frees",
                      "%d mirror frees pending, more than %d: nothing has "
                      "drained them (no tick ran?)"
                      % (len(_pending_frees), PENDING_FREES_WARN))
        except Exception:
            pass


def _queue_push(obj, fn, arg, label) -> None:
    """A push `fn(obj, arg)` made off the main thread, for the drain."""
    _pending_pushes.append((weakref.ref(obj), fn, arg, label))


def _repush_native(obj, field) -> None:
    """A queued NativeField push: the field's value as the object holds it
    now, by the field's own push."""
    d = obj.__dict__
    h = d.get("_nslot")
    if not _enabled or h is None or field._name not in d:
        return
    if field._scalar is None:
        field._push(obj, h, d[field._name])
    else:
        field._push_scalar(obj, h, d[field._name])


def _session_open() -> bool:
    return bool(available() and (
        _h.combat_k0_open() or _h.combat_k1_depth() or _h.combat_k2_open()
        or _h.combat_k3_open()))


def _apply_free(h, slot) -> None:
    if slot is not None:
        try:
            slot[0].free(*slot[1])
        except Exception:
            # A store reset (tests) or interpreter teardown can invalidate
            # the handle first.
            pass
    if h is not None:
        _forget_part_caches(h)
        try:
            _h.combat_unregister(h)
        except Exception:
            pass        # a combat_clear may have freed it


def drain(boundary: bool = False) -> None:
    """Apply every pending free, then every queued push, in recorded order,
    on the main thread with the GIL held. Nothing while a kernel session is
    open, and nothing when called off the main thread. What a push's own
    Python records (a collection it triggers) waits for the next drain. A
    push that raises is logged once per site; the rest still apply.
    `boundary`: a tick boundary, where no session should be open, so a
    skipped drain there is logged once."""
    if not (_pending_frees or _pending_pushes) or _off_main():
        return
    if _session_open():
        if boundary:
            _log_once("boundary_session",
                      "a drain at the tick boundary was skipped: a kernel "
                      "session is still open (K0 %d, K1 depth %d, K2 %d, "
                      "K3 %d); frees and queued pushes wait until it closes"
                      % (_h.combat_k0_open(), _h.combat_k1_depth(),
                         _h.combat_k2_open(), _h.combat_k3_open()))
        return
    frees, pushes = _pending_frees, _pending_pushes
    while frees:
        _apply_free(*frees.popleft())
    for _ in range(len(pushes)):
        ref, fn, arg, label = pushes.popleft()
        obj = ref()
        if obj is not None:
            try:
                fn(obj, arg)
            except Exception as e:
                site = (getattr(fn, "__qualname__", repr(fn)), label)
                if site not in _logged_once:
                    _log_once(site, "a queued push (%s, %s) raised at the "
                              "drain: %r; the drain carries on"
                              % (site[0], label, e))
                    traceback.print_exception(e, file=sys.stderr)


def _discard_pending_rows() -> None:
    """forget_rows: the mirror was rebuilt (combat_clear), so no pending row
    free or push may reach it. Transform-slot frees still apply: the store
    was not cleared."""
    frees = _pending_frees
    _pending_pushes.clear()
    while frees:
        _apply_free(None, frees.popleft()[1])


def pending_frees() -> list:
    """(row handle or None, (store, transform handle) or None) per pending
    free, in recorded order."""
    return list(_pending_frees)


def pending_pushes() -> list:
    """(object or None if collected, label) per queued push, in recorded
    order."""
    return [(ref(), label) for ref, _fn, _arg, label in _pending_pushes]


def unregister_handle(h: int) -> None:
    """Finalizer body: records the free (drain() applies it). Never
    raises."""
    defer_free(h)


def _obj_id_findable(obj, _findable) -> None:
    """engine.core.ids' hook: `obj` left (or rejoined) the id registry.
    Python's probe walk (SensorSubsystem.probes) skips an id that does not
    resolve; native can_detect's finds its probes by obj_id in the mirror,
    where a collected object's row waits for the drain. So the row's obj_id
    lookup follows the registry. Queued off the main thread, like a push."""
    h = obj.__dict__.get("_nslot")
    if h is None or not available() or (h >> _KIND_SHIFT) != _kind("Object"):
        return
    if _off_main():
        _queue_push(obj, _push_obj_id_findable, None, "obj_id_findable")
        return
    _push_obj_id_findable(obj, None)


def _push_obj_id_findable(obj, _arg) -> None:
    """Whether `obj`'s id resolves to it now, pushed to its row."""
    h = obj.__dict__.get("_nslot")
    if h is None:
        return
    try:
        _h.combat_set_obj_id_findable(
            h, _ids.get_object_by_id(obj.GetObjID()) is obj)
    except ValueError:
        pass        # a combat_clear freed the row


_ids._findable_hook = _obj_id_findable


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


#: Kernel M's class flags (native motion phase 2): the methods motion calls on
#: a ship, on its impulse engine and on the engine's pods. A class whose
#: method is not the stock class's own function object reads 0, and the
#: kernel hands that row to Python, where the override runs. IsDying /
#: IsDead: subsystems._is_offline(ies) -> ship_death._out_of_action(ship)
#: asks them (the kernel reads the row's dying / dead state instead);
#: GetWarpEngineSubsystem: warp_state.is_arriving asks it (the kernel reads
#: the row's `arriving`). _steer_turn_goal, _turn_goal_vectors,
#: _turn_rotation, GetWorldLocation: the stored turn goal's steering, which
#: the kernel ports (a "loc" goal reads GetWorldLocation).
_MOTION_SHIP_NAMES = ("IsImmobile", "IsStatic", "IsStationary",
                      "GetImpulseEngineSubsystem", "GetTranslate",
                      "SetTranslateXYZ", "GetWorldRotation",
                      "SetMatrixRotation", "SetVelocity", "IsDying",
                      "IsDead", "GetWarpEngineSubsystem",
                      "_steer_turn_goal", "_turn_goal_vectors",
                      "_turn_rotation", "GetWorldLocation")
_MOTION_IES_NAMES = ("IsDisabled", "IsDestroyed", "IsOn",
                     "GetNumChildSubsystems", "GetChildSubsystem",
                     "GetPowerPercentageWanted", "GetParentShip",
                     "GetAuthoredMaxSpeed", "GetAuthoredMaxAccel",
                     "GetAuthoredMaxAngularVelocity",
                     "GetAuthoredMaxAngularAccel")
_MOTION_POD_NAMES = ("IsDisabled", "IsDestroyed", "GetConditionPercentage",
                     "GetMaxCondition")
_NO_ATTR = object()


def _stock_surface(cls, base, names) -> int:
    """1 when `cls` is `base` or a subclass whose every name in `names` is
    `base`'s own attribute (the same function object), else 0. Computed at
    every call (never cached), so the audit sees a class patched since."""
    if not issubclass(cls, base):
        return 0
    for name in names:
        if getattr(cls, name, _NO_ATTR) is not getattr(base, name, None):
            return 0
    return 1


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
            # Weapon.FireDumb's warp-in hold (K1's native dumb fire).
            "arriving": _arriving_flag(obj),
            # The native hit stands in for this ship class's (damage).
            "dmg_ship": _dmg_ship(type(obj)),
            # Kernel M flies this class's ships (native motion phase 2).
            "motion_stock": _stock_surface(type(obj), ShipClass,
                                           _MOTION_SHIP_NAMES),
        }
    if k == _kind("Subsystem"):
        from engine.appc.subsystems import ImpulseEngineSubsystem, \
            ShipSubsystem
        return {"has_parent_ship_getter": int(implements(obj,
                                                         "GetParentShip")),
                "weapon_kind": _weapon_kind(obj),
                "has_shields": _has_shields_flag(obj),
                # The condition chain's rules for this class (damage).
                "dmg_class": _dmg_class(type(obj)),
                # Kernel M reads this impulse engine, or this pod, natively.
                "motion_ies_stock": _stock_surface(
                    type(obj), ImpulseEngineSubsystem, _MOTION_IES_NAMES),
                "motion_pod_stock": _stock_surface(
                    type(obj), ShipSubsystem, _MOTION_POD_NAMES),
                # The native power piece's rules for this class.
                "power_kind": _power_kind(type(obj)),
                # The native repair piece runs this class's Update.
                "is_repair_bay": _is_repair_bay(type(obj))}
    return {}


_repair_bay_by_type: dict = {}


def _is_repair_bay(cls) -> int:
    """1 for a RepairSubsystem class (the native repair piece,
    subsystem_step.h THE REPAIR PIECE), by what the class IS: a subclass's
    own override is not honoured (spec §3 "Mods and patches (Part A)")."""
    k = _repair_bay_by_type.get(cls)
    if k is None:
        from engine.appc.subsystems import RepairSubsystem
        k = _repair_bay_by_type[cls] = int(issubclass(cls, RepairSubsystem))
    return k


_POWER_KINDS = None
_power_kind_by_type: dict = {}


def _power_kind(cls) -> int:
    """Which power rules a subsystem class has, for the native power piece
    (subsystem_step.h THE POWER PIECE): 3 a plant (PowerSubsystem.Update),
    2 the cloak's rules (draw from the reserve while trying to cloak), 1 the
    tractor's (a firing beam wanted, then PoweredSubsystem's draw), 0
    PoweredSubsystem's draw,
    -1 none (not a consumer: the pump hands such a ship's piece to Python).
    By what the class IS: a subclass's own override of those methods is not
    honoured (spec §3 "Mods and patches (Part A)")."""
    global _POWER_KINDS
    k = _power_kind_by_type.get(cls)
    if k is None:
        if _POWER_KINDS is None:
            from engine.appc import subsystems as ss
            from engine.appc import weapon_subsystems as ws
            _POWER_KINDS = ((ss.PowerSubsystem, 3), (ss.CloakingSubsystem, 2),
                            (ws.TractorBeamSystem, 1),
                            (ss.PoweredSubsystem, 0))
        k = -1
        for klass, kind in _POWER_KINDS:
            if issubclass(cls, klass):
                k = kind
                break
        _power_kind_by_type[cls] = k
    return k


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

# THE PENDING SET (phase 6 A3): resolve_stale_part_slots runs ~4x a tick, and
# almost always finds nothing stale, so it skips its scan of `ships` unless a
# ship may be. A ship is stale (today's test) when its handle's _resolved_gen
# is not _part_gen; resolving it does anything only once its leaf is known
# (_leaf_known). So the scan is needed only while some LEAFED handle may be
# stale, and every way one becomes so is an event:
#   * the generation moves (bump_part_gen): every leafed handle, until a
#     sweep at that generation: `_part_swept != _part_gen`;
#   * a leafed handle appears: register (a leaf already known), or the leaf
#     becomes known on a registered row -- the PartLeafField on ObjectClass,
#     or for a class shadowing it, the row polled (_part_polled);
#   * a _resolved_gen entry goes: _forget_part_caches() (every handle:
#     `_part_swept = 0`), push_mount_order (bumps too), a freed row (dead).
# A handle leaves the pending set only when its resolution stamps it fresh
# (resolve_part_slots) or it can do nothing (its leaf is unknown again; its
# row is freed). A resolution that does not stamp (it raised, its table
# could not be pushed, the row changed, the generation moved under it)
# leaves it pending, as does a ship absent from this sweep's `ships`: a
# later sweep of another list still finds it. When the generation moved, a
# sweep ends by making "every leafed handle" explicit: the ones still stale,
# by state (_part_prune). The sweep itself is the old scan, unchanged (same
# ships, same order, same test), so it resolves exactly what it did; while
# some pending ship is in no list (a dead ship a script still holds, say)
# every call sweeps, at the old cost.
_part_pending: dict = {}        # leafed handle -> None, maybe stale
_part_leafed: "weakref.WeakValueDictionary[int, object]" = \
    weakref.WeakValueDictionary()
_part_polled: "weakref.WeakValueDictionary[int, object]" = \
    weakref.WeakValueDictionary()
_part_swept = 0                 # the _part_gen the last prune ran at


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
        if _off_main():         # the generation as it stands at the drain
            _queue_push(_PART_GEN, _push_part_gen, None, "part_gen")
            return
        _h.combat_set_part_gen(_part_gen)


class _PartGen:
    """The weakly referenceable owner of a queued part-generation push."""


_PART_GEN = _PartGen()


def _push_part_gen(_owner, _arg) -> None:
    if _enabled:
        _h.combat_set_part_gen(_part_gen)


def _forget_part_caches(h=None) -> None:
    global _part_swept
    if h is None:
        _slot_names.clear()
        _resolved_gen.clear()
        _part_swept = 0         # every leafed handle is stale
    else:
        _slot_names.pop(h, None)
        _resolved_gen.pop(h, None)
        # A freed row: its handle names no object any more.
        _part_pending.pop(h, None)
        _part_leafed.pop(h, None)
        _part_polled.pop(h, None)


def _part_mark(obj) -> None:
    """`obj`'s row may have stale slots it can now resolve: its leaf became
    known (PartLeafField), or it registered with one (THE PENDING SET)."""
    h = obj.__dict__.get("_nslot")
    if h is not None and _leaf_known(obj) is not None:
        _part_leafed[h] = obj
        _part_pending[h] = None


def _part_registered(obj, h) -> None:
    """register: a new Object row. Pending if its leaf is known already;
    polled if its class shadows the leaf descriptor (a write to the leaf
    would not be seen)."""
    if not isinstance(getattr(type(obj), "_articulation_leaf", None),
                      PartLeafField):
        _part_polled[h] = obj
    _part_mark(obj)


def _part_poll() -> None:
    """Rows whose class shadows PartLeafField: one whose leaf is known now
    is pending (and polled no longer: a known leaf only changes what a
    resolution finds, never whether the slots are stale)."""
    for h, obj in list(_part_polled.items()):
        if obj.__dict__.get("_nslot") != h:
            _part_polled.pop(h, None)
        elif _leaf_known(obj) is not None:
            _part_polled.pop(h, None)
            _part_leafed[h] = obj
            _part_pending[h] = None


def _part_prune() -> None:
    """After a sweep at a generation not swept before: "every leafed handle
    is pending" becomes explicit -- the ones still stale, by state, join the
    pending set (whose own members stay: each leaves only as THE PENDING
    SET says)."""
    global _part_swept
    gen = _part_gen
    resolved = _resolved_gen
    for h, obj in list(_part_leafed.items()):
        if (obj.__dict__.get("_nslot") == h and resolved.get(h) != gen
                and _leaf_known(obj) is not None):
            _part_pending[h] = None
    _part_swept = gen


class PartLeafField:
    """``ObjectClass._articulation_leaf`` (ShipClass sets it; None until
    articulation.leaf_for caches it): a write marks the row pending for the
    part-slot resolution (THE PENDING SET), since a ship whose leaf was
    unknown was never resolved. ABSENT until first written (the readers use
    getattr(..., None) and the instance dict), as PosedPartsField."""

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
        _part_mark(obj)

    def __delete__(self, obj) -> None:
        try:
            del obj.__dict__[self._name]
        except KeyError:
            raise AttributeError(self._name) from None


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
    the resolution raised (the slot is then left stale, and resolved again
    at the next step boundary: resolve_part_slots, M8.4)."""
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
    except Exception:  # noqa: BLE001 - a no-fire, retried (M8.4)
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
        if h is not None:       # nothing to do until a leaf is written
            _part_pending.pop(h, None)
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
    raised = False
    if names:
        sub_kind = _kind("Subsystem")
        for sub in _slot_subsystems(ship):
            sh = _slot_of(sub)
            if sh is None or (sh >> _KIND_SHIFT) != sub_kind:
                continue
            slot = _part_slot(leaf, names, sub)
            if slot is None:
                _call(sub, _h.combat_set_part_slot, sh, -1, 0)  # stale
                raised = True
            else:
                _call(sub, _h.combat_set_part_slot, sh, slot, gen)
    if raised:
        # The slot stays stale -- a posed ship's walk does not fire
        # (k1_no_fire part_stale) -- and is resolved again at the next step
        # boundary, not only at the next generation (fire control native
        # only, M8.4).
        _log_once(("part_resolution", type(ship).__name__),
                  "fire control: a %s's part resolution raised: its posed "
                  "weapons do not fire until it resolves (retried every "
                  "step)" % type(ship).__name__)
    elif _part_gen == gen:  # nothing bumped while resolving
        _resolved_gen[h] = gen
        _part_pending.pop(h, None)


def resolve_stale_part_slots(ships, drop=True) -> None:
    """At a step boundary: resolve every ship of `ships` whose slots were
    resolved at an older generation (or never). `drop`: see
    resolve_part_slots. Nothing to do -- no leafed handle maybe stale (THE
    PENDING SET) -- costs no scan of `ships`."""
    if not _enabled:
        return
    if _part_polled:
        _part_poll()
    if _part_swept == _part_gen and not _part_pending:
        return
    for ship in ships:
        d = ship.__dict__
        h = d.get("_nslot")
        if h is None:
            continue
        if _resolved_gen.get(h) != _part_gen:
            resolve_part_slots(ship, drop)
    if _part_swept != _part_gen:
        _part_prune()


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


def _mount_order(ship) -> list:
    """The ship's subsystems as `part_severance.authored_mount_subsystem`
    walks them (`_mounted_subsystems`: combat._iter_subsystems order), as
    Subsystem handles; -2 for one the mirror cannot name, or whose
    GetPosition() raises (the hit hands back, and the reference raises)."""
    from engine.appc.part_severance import _mounted_subsystems
    sub_kind = _kind("Subsystem")
    out = []
    for sub, mount in _mounted_subsystems(ship, keep_raising=True):
        t = None if mount is None else _slot_of(sub)
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
    weapon_subsystems (cleared with the projectile module cache), and the
    module itself, which a kernel SPAWN of the cannon's carries (launch
    deferral, Task 3)."""
    if _enabled:
        if _pulse_stale:
            refresh_stale_pulse_params()
        h = bank.__dict__.get("_nslot")
        if h is None:
            return
        ok, speed, life = _pulse_params(bank)
        # Set before module_ok, the state that lets the kernel launch.
        from engine.appc import weapon_subsystems as ws
        _h.combat_set_launch_module(
            h, ws.pulse_module(ws.pulse_module_script(bank)) if ok else None)
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
    next K1 entry (_refresh_stale_launches: a K1 decision reads the params,
    and Python's Fire would read the module at that moment) or
    refresh_stale_pulse_params (GameLoop.tick) re-reads every built bank,
    ammo type and torpedo property. Until then -- a reset made by Python
    run in the middle of a K1 session, THE P6 WINDOW -- every row keeps the
    launch it holds and the kernel launches from it (fire control native
    only, M8.3: the cache is out of date, the shot is not impossible: not a
    hand-back, not a no-fire)."""
    global _pulse_stale
    if _enabled:
        _pulse_stale = True


# ── The per-type launch cache (launch deferral; P6 extended to tubes) ────────
# Spec docs/superpowers/specs/2026-11-02-combat-launch-deferral-design.md
# §4.1. K1 makes a tube's launch natively only from an ammo type whose
# script's launch Python has cached (weapon_subsystems._tube_launch_cache):
# its state (cached / unresolved) and launch speed, pushed to every
# Ammo row of that script. Read when the type is loaded (push_ammo_launch:
# its creation, SetTorpedoScript, the re-read after a cache reset) through
# weapon_subsystems._resolve_projectile_module and tube_launch_params. A
# type not cached does not fire (K1LaunchWhy::Uncached, a no-fire): a
# GetLaunchSpeed that raises. Forgotten with the projectile module cache
# (mark_pulse_stale) and re-read at the next K1 entry.

def _ammo_launch(ammo) -> tuple:
    """(ammo_launch_state, ammo_launch_speed) for an ammo type: its
    script's cached launch, (0, 0.0) not cached yet, unresolved when it has
    no script (its launch then does not fire: a no-fire, M6)."""
    from engine.appc import weapon_subsystems as ws
    script = ammo.__dict__.get("_script")
    if not script:
        return (ws.LAUNCH_UNRESOLVED, 0.0)
    return ws._tube_launch_cache.get(script, (ws.LAUNCH_UNCACHED, 0.0))


def _ammo_module(ammo, state):
    """The module a cached ammo type's launches use (the one Python's launch
    of its script resolved), else None."""
    from engine.appc import weapon_subsystems as ws
    if state != ws.LAUNCH_CACHED:
        return None
    return ws._projectile_modules.get(ammo.__dict__.get("_script"))


def push_ammo_launch(ammo) -> None:
    """Push the ammo type's launch (_ammo_launch) at its creation, a new
    script, a cache re-read: its script's launch is cached first
    (_cache_tube_launch), so the row is pushed cached."""
    # A type built mid-swap (_pulse_stale: the SDK tree half reloaded)
    # resolves its module now, memoizing a failed import earlier than its
    # first launch would; the next swap's reset clears it.
    if _enabled:
        if _pulse_stale:
            refresh_stale_pulse_params()    # re-pushes every type, this one too
        _cache_tube_launch(ammo.__dict__.get("_script"))
        _push_ammo_row(ammo)


def _cache_tube_launch(script) -> None:
    """Cache torpedo `script`'s launch, resolved as Python's launch resolves
    it (_resolve_projectile_module: an unimportable script is the stock
    photon, None when that fails too; it catches every import error itself,
    and tube_launch_params a raising GetLaunchSpeed, so loading never
    breaks). An uncached answer (that raise) is not stored, so the next
    re-read tries again. Mirror live only."""
    from engine.appc import weapon_subsystems as ws
    if script and script not in ws._tube_launch_cache:
        launch = ws.tube_launch_params(ws._resolve_projectile_module(script))
        if launch[0] != ws.LAUNCH_UNCACHED:
            ws._tube_launch_cache[script] = launch


def _push_ammo_row(ammo) -> None:
    """Push the ammo type's launch as cached now, resolving nothing."""
    if _enabled:
        h = ammo.__dict__.get("_nslot")
        if h is None:
            return
        state, speed = _ammo_launch(ammo)
        # The module a kernel SPAWN of this type carries (its fire-time
        # module), set before the state that lets the kernel launch.
        _h.combat_set_launch_module(h, _ammo_module(ammo, state))
        _call(ammo, _h.combat_set_i, h, _fid("ammo_launch_state"), state)
        if "_nslot" in ammo.__dict__:
            _call(ammo, _h.combat_set_f, h, _fid("ammo_launch_speed"),
                  float(speed))


def _slot0_launch(prop) -> tuple:
    """(slot0_launch_state, slot0_launch_speed, module) of a torpedo system
    property: its slot-0 script's cached launch -- the script
    the kernel launches for a tube with no ammo type
    (`parent.GetProperty().GetTorpedoScript(0)`; fire control native only,
    M8.2) -- unresolved when it has none (the launch does not fire).
    Read from the instance dict, so it is safe while the property is still
    being built."""
    from engine.appc import weapon_subsystems as ws
    scripts = prop.__dict__.get("_torpedo_scripts")
    script = scripts.get(0) if isinstance(scripts, dict) else None
    if not script:
        return (ws.LAUNCH_UNRESOLVED, 0.0, None)
    state, speed = ws._tube_launch_cache.get(script,
                                             (ws.LAUNCH_UNCACHED, 0.0))
    mod = (ws._projectile_modules.get(script)
           if state == ws.LAUNCH_CACHED else None)
    return (state, speed, mod)


def push_slot0_launch(prop) -> None:
    """Push a torpedo system property's slot-0 launch (_slot0_launch), its
    script's launch cached first (_cache_tube_launch, as an ammo type's):
    at its row's creation, its SetTorpedoScript, a cache re-read."""
    if _enabled:
        scripts = prop.__dict__.get("_torpedo_scripts")
        if isinstance(scripts, dict):
            _cache_tube_launch(scripts.get(0))
        _push_slot0_row(prop)


def _push_slot0_row(prop) -> None:
    """Push the property's slot-0 launch as cached now, resolving nothing."""
    if _enabled:
        h = prop.__dict__.get("_nslot")
        if h is None or "_torpedo_scripts" not in prop.__dict__:
            return
        state, speed, mod = _slot0_launch(prop)
        # The module a kernel SPAWN of this launch carries, set before the
        # state that lets the kernel launch.
        _h.combat_set_launch_module(h, mod)
        _call(prop, _h.combat_set_i, h, _fid("slot0_launch_state"), state)
        if "_nslot" in prop.__dict__:
            _call(prop, _h.combat_set_f, h, _fid("slot0_launch_speed"),
                  float(speed))


def _refresh_stale_launches() -> None:
    """Every K1 entry's re-push of a stale launch cache (fire control native
    only, M8.3): the projectile-cache reset's re-read
    (refresh_stale_pulse_params), and a cannon module re-imported since its
    params were read -- `sys.modules` no longer holds the module the
    cannons' launches carry (the cannon decision imported its script
    at every shot) -- whose script is read again and pushed to every cannon
    of it. Between the staleness and this (Python run in the middle of a
    session) the kernel launches from the cache it has. Neither is a
    no-fire, and neither is counted."""
    if _pulse_stale:
        refresh_stale_pulse_params()
    from engine.appc import weapon_subsystems as ws
    modules = sys.modules
    stale = None
    for script, mod in ws._pulse_modules.items():
        if modules.get(script) is not mod:
            if stale is None:
                stale = []
            stale.append(script)
    if stale is None:
        return
    for script in stale:
        ws._pulse_modules.pop(script, None)
        ws._pulse_params_cache.pop(script, None)
    stale = set(stale)
    for h, obj in list(_registry.items()):
        if (obj.__dict__.get("_nslot") == h
                and (h >> _KIND_SHIFT) == _kind("Subsystem")
                and _weapon_kind(obj) == 6
                and ws.pulse_module_script(obj) in stale):
            push_pulse_params(obj)


def _arriving_flag(ship) -> int:
    """warp_state.is_arriving(ship) (Weapon.FireDumb's warp-in hold), read
    from the instance dicts: safe while the ship is still being built."""
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import WarpEngineSubsystem
    if not isinstance(ship, ShipClass):
        return 0
    sub = ship.__dict__.get("_warp_engine_subsystem")
    return int(isinstance(sub, WarpEngineSubsystem)
               and sub.__dict__.get("_dewarp_drive") is not None)


def push_arriving(ship) -> None:
    """The ship's warp-in slide began or ended
    (WarpEngineSubsystem._begin_dewarp_drive / _end_dewarp_drive)."""
    if _enabled and ship is not None:
        h = ship.__dict__.get("_nslot")
        if h is not None and (h >> _KIND_SHIFT) == _kind("Object"):
            _call(ship, _h.combat_set_i, h, _fid("arriving"),
                  _arriving_flag(ship))


def refresh_stale_pulse_params() -> None:
    global _pulse_stale
    if _pulse_stale:
        _pulse_stale = False
        refresh_pulse_params()


def refresh_pulse_params() -> None:
    """Every pulse bank, ammo type and torpedo property already built
    re-reads its module."""
    if _enabled:
        for h, obj in list(_registry.items()):
            if obj.__dict__.get("_nslot") != h:
                continue
            k = h >> _KIND_SHIFT
            if k == _kind("Subsystem") and _weapon_kind(obj) == 6:
                push_pulse_params(obj)
            elif k == _kind("Ammo"):
                push_ammo_launch(obj)
            elif k == _kind("Property"):
                push_slot0_launch(obj)


#: The PowerProperty values PowerSubsystem._prop_f reads every tick (its
#: getter names less "Get"), mirrored on every Property row (mirror.h).
POWER_PROPERTY_FIELDS = ("PowerOutput", "MainBatteryLimit",
                         "BackupBatteryLimit", "MainConduitCapacity",
                         "BackupConduitCapacity")
#: The RepairSubsystemProperty values RepairSubsystem reads every tick
#: (GetMaxRepairPoints, GetNumRepairTeams), mirrored on every Property row.
REPAIR_PROPERTY_FIELDS = ("MaxRepairPoints", "NumRepairTeams")
#: Every data-bag field a Property row mirrors: their setters push
#: (properties.TGModelProperty.__getattr__).
MIRRORED_PROPERTY_FIELDS = frozenset(("MaxCondition",)
                                     + POWER_PROPERTY_FIELDS
                                     + REPAIR_PROPERTY_FIELDS)

_INT64_MAX = (1 << 63) - 1


def _repair_property_values(prop) -> dict:
    """The two values as RepairSubsystem's getters read them --
    ``float(v)`` / ``int(v)`` of the data-bag value, 0.0 / 0 for None --
    and repair_props_ok: 1 only when both are read that way (no class
    getter of the name) and convert without raising (an int that fits the
    row)."""
    cls = type(prop)
    ok = 1
    for name in REPAIR_PROPERTY_FIELDS:
        if getattr(cls, "Get" + name, None) is not None:
            ok = 0
    points, teams = 0.0, 0
    try:
        v = prop._data.get(("MaxRepairPoints", ()), None)
        if v is not None:
            points = float(v)
        v = prop._data.get(("NumRepairTeams", ()), None)
        if v is not None:
            teams = int(v)
        if not -_INT64_MAX <= teams <= _INT64_MAX:
            raise OverflowError(teams)
    except (TypeError, ValueError, OverflowError):
        ok, points, teams = 0, 0.0, 0
    return {"MaxRepairPoints": points, "NumRepairTeams": teams,
            "repair_props_ok": ok}


def _power_property_values(prop) -> dict:
    """The five values as _prop_f reads them, `float(value or 0.0)` from the
    data bag, and power_props_ok: 1 only when every one is read that way
    (no class getter of its name: _prop_f's own probe) and is a float."""
    vals = {}
    cls = type(prop)
    ok = 1
    for name in POWER_PROPERTY_FIELDS:
        v = 0.0
        if getattr(cls, "Get" + name, None) is not None:
            ok = 0
        else:
            try:
                v = float(prop._data.get((name, ()), None) or 0.0)
            except (TypeError, ValueError, OverflowError):
                ok = 0
                v = 0.0
        vals[name] = v
    vals["power_props_ok"] = ok
    return vals


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
    vals.update(_power_property_values(prop))
    vals.update(_repair_property_values(prop))
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
        if "_nslot" in obj.__dict__:
            push_slot0_launch(obj)
    elif k == _kind("Subsystem"):
        if "_nslot" in obj.__dict__ and _weapon_kind(obj) == 6:
            push_pulse_params(obj)
            if "_nslot" in obj.__dict__:
                _push_watch_value_of(obj)
        for which in _COND_WATCH_SLOTS:
            if "_nslot" in obj.__dict__:
                push_cond_watch(obj, which)
    elif k == _kind("Set"):
        push_set_members(obj)
        push_set_frame(obj)
    elif k == _kind("Ammo"):
        push_ammo_launch(obj)


def _push_all(obj, h) -> None:
    _push_extras(obj, h)
    d = obj.__dict__
    for name, field in _fields_of(type(obj)):
        if "_nslot" not in d:
            return              # dropped by a stale push
        if name in d:
            field._push(obj, h, d[name])
        elif isinstance(field, NativeOptionalField):
            field._push(obj, h, field._absent)  # a resync: the absent value
    for name, field in _hidden_fields(type(obj))[0]:
        if "_nslot" not in d:
            return
        _call(obj, _h.combat_set_ref, h, _fid(field._key), REF_UNREPRESENTABLE)


def reclassify(ship) -> None:
    """`ship.__class__` changed (engine.rocks.rock): re-push its class flags."""
    proximity_cache.bump()
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
    """A property value the mirror holds was written: a data-bag entry of
    MIRRORED_PROPERTY_FIELDS (MaxCondition, the five power values, the two
    repair values), SetGroups or SetFiringChainString."""
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
        for name in POWER_PROPERTY_FIELDS:
            if "_nslot" in prop.__dict__:
                _call(prop, _h.combat_set_f, h, _fid(name), vals[name])
        if "_nslot" in prop.__dict__:
            _call(prop, _h.combat_set_i, h, _fid("power_props_ok"),
                  vals["power_props_ok"])
        for name, setter in (("MaxRepairPoints", _h.combat_set_f),
                             ("NumRepairTeams", _h.combat_set_i),
                             ("repair_props_ok", _h.combat_set_i)):
            if "_nslot" in prop.__dict__:
                _call(prop, setter, h, _fid(name), vals[name])


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


# engine/appc/tractor.py's force constants, pushed by their own names.
_TRACTOR_CONSTANTS = (
    "TRACTOR_REFERENCE_MASS", "TRACTOR_REFERENCE_SPEED_GUPS",
    "TRACTOR_MAX_SPEED_GUPS", "TRACTOR_FALLBACK_MASS",
    "TRACTOR_TOW_DRAG_FRACTION", "TRACTOR_DOCK_GENTLE_FRACTION",
    "TRACTOR_STANDOFF_MARGIN_GU")


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
    # A cannon's native launch (launch deferral, Task 3): GetDamageScale.
    for i, scale in enumerate(ws.PULSE_DAMAGE_SCALE_BY_POWER_SETTING):
        g["PULSE_DAMAGE_SCALE_%d" % i] = float(scale)
    # K2: the dwell flush threshold and the shield ellipsoid scale.
    from engine.appc import combat
    g["BEAM_DWELL_FLUSH_S"] = float(ws.BEAM_DWELL_FLUSH_S)
    g["SHIELD_ELLIPSOID_AXIS_SCALE"] = float(combat.SHIELD_ELLIPSOID_AXIS_SCALE)
    # K3: the guidance lead term.
    from engine.appc import projectiles
    g["LEAD_ACCEL_K"] = float(projectiles._LEAD_ACCEL_K)
    # K1's 0.33 s timer gate: a class constant of WeaponSystem.
    g["FIRE_TIMER_THRESHOLD"] = float(ws.FIRE_TIMER_THRESHOLD)
    # K1's beam edge: the lit bank's beam-on countdown (combat fire events).
    g["BEAM_ON_DELAY_S"] = float(ws.BEAM_ON_DELAY_S)
    # K0: the phaser drain by power level, read at use (a module constant a
    # test may patch). Three entries, 0.0 past the table's end, and its
    # length: the kernel answers only the indices Python's table would.
    table = ws.PHASER_DISCHARGE_BY_POWER_LEVEL
    for i in range(3):
        g["PHASER_DISCHARGE_%d" % i] = (float(table[i]) if i < len(table)
                                        else 0.0)
    g["PHASER_DISCHARGE_LEN"] = len(table)
    # Tractors native (fire control native only, R7): the force constants
    # and K1's engage range, each read from its one Python home.
    from engine.appc import tractor
    for name in _TRACTOR_CONSTANTS:
        g[name] = float(getattr(tractor, name))
    g["TRACTOR_EPS"] = float(tractor._EPS)
    g["TRACTOR_MAX_RANGE_GU"] = float(ws.TRACTOR_MAX_RANGE_GU)
    # The native shield piece's 0.5 s cadence (phase 6 A1, Task 3).
    from engine.appc import subsystems
    g["SHIELD_CHARGE_PERIOD_S"] = float(subsystems.SHIELD_CHARGE_PERIOD_S)
    # The native power piece's 1.0 s interval (phase 6 A1, Task 4).
    g["POWER_INTERVAL"] = float(subsystems.PowerSubsystem.POWER_INTERVAL)
    # The native cloak piece's starvation threshold (phase 6 A1, Task 5).
    g["MIN_RESERVE_TO_HOLD_CLOAK"] = float(
        subsystems.CloakingSubsystem.MIN_RESERVE_TO_HOLD_CLOAK)
    # The native articulation piece's rigless key (phase 6 A1, Task 6).
    from engine.appc import articulated_part
    g["ARTICULATION_GEN"] = int(articulated_part.generation())
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
    # The hit K3 applies at DONE (native damage Task 4).
    "_damage": (lambda t, v: _num(v), "f", "damage"),
    "_damage_radius_factor": (lambda t, v: _num(v), "f",
                              "damage_radius_factor"),
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
        else:
            _torp_push_mount(t, h, value, v)
    except ValueError:
        _torp_lost(t)
        return
    if name == "_target_ship":
        # `_mount_key`'s attributed flag is `key[0] is _target_ship`.
        _torp_push(t, h, "_mount_key", t.__dict__.get("_mount_key"))


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
        if _switch:
            h = d.get("_k3_row")
            if h is not None:
                _torp_push(obj, h, self._name, value)


def push_torpedo_field(t, name: str, value) -> None:
    """A Torpedo property (`_velocity`, `_source_ship`, `_containing_set`)
    was written: push it if the torpedo has a row. Callers test `_switch`
    first (K3's table follows the switch), so the switch-off cost is that
    read."""
    h = t.__dict__.get("_k3_row")
    if h is not None:
        _torp_push(t, h, name, value)


def _torp_put(t) -> None:
    xi, xg = t.__dict__.get("_xform", (-1, -1))
    h = _h.combat_torp_add(xi, xg)
    t.__dict__["_k3_row"] = h
    _k3_rows[h] = t
    for name in _TORP_FIELDS:
        value = _torp_value(t, name)
        if value is not _UNSET_FIELD and t.__dict__.get("_k3_row") == h:
            _torp_push(t, h, name, value)


def torpedo_row_add(t) -> None:
    """`_active.append(t)`: a row at the end, unless the table is dirty (the
    rebuild will include it) or `t` already has one (appended twice: the
    list now holds it twice, so the table is rebuilt)."""
    if not _switch or _k3_dirty:
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
    if available():
        _h.combat_torp_clear()


def torpedo_table_rebuild(active) -> None:
    """Refill the table from `active` (projectiles._active), in list order.
    A no-op with the switch off. A torpedo in the list TWICE (update_all
    advances it twice a tick) leaves the table dirty and empty: one row
    cannot stand for it, so K3 hands the step to Python until it is gone."""
    global _k3_dirty
    if not _switch:
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
        if (h >> _KIND_SHIFT) == _kind("Property") and not _pulse_stale \
                and "_torpedo_scripts" in d:
            # As an ammo type's (below); not inside THE P6 WINDOW, where the
            # row keeps the launch it had until the next K1 entry (M8.3).
            from engine.appc import weapon_subsystems as ws
            scripts = d.get("_torpedo_scripts")
            script = scripts.get(0) if isinstance(scripts, dict) else None
            if not script:
                state, speed = ws.LAUNCH_UNRESOLVED, 0.0
            elif script in ws._tube_launch_cache:
                state, speed = ws.tube_launch_params(
                    ws._projectile_modules.get(script))
            else:
                state, speed = ws.LAUNCH_UNCACHED, 0.0
            expected.update(slot0_launch_state=state,
                            slot0_launch_speed=float(speed))
        if (h >> _KIND_SHIFT) == _kind("Ammo") and not _pulse_stale:
            # Resolved afresh from the module the cache entry was read from
            # (a stale cache entry would otherwise agree with a stale row).
            # Not inside THE P6 WINDOW (the property's note above).
            from engine.appc import weapon_subsystems as ws
            script = d.get("_script")
            if not script:
                state, speed = ws.LAUNCH_UNRESOLVED, 0.0
            elif script in ws._tube_launch_cache:
                state, speed = ws.tube_launch_params(
                    ws._projectile_modules.get(script))
            else:
                state, speed = ws.LAUNCH_UNCACHED, 0.0
            expected.update(ammo_launch_state=state,
                            ammo_launch_speed=float(speed))
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
            if attr in d:
                value = d[attr]
            elif isinstance(field, NativeOptionalField):
                value = field._absent           # the row holds the default
            else:
                continue
            audit = getattr(field, "audit", None)   # a field of several rows
            if audit is not None:
                ok = audit(value, row)
            else:
                ok = field._matches(value, row[field._dump_key])
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
            if "_watch_checks" in d:
                _audit_watch_checks(obj, row, name)
            _audit_cond_watch(obj, row, name)
            if "_shield_watchers" in d:
                _audit_shield_watch(obj, row, name)
            if "_main_battery_watcher" in d:
                _audit_power_watch(obj, row, name)
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


def _audit_watch_checks(weapon, row, name) -> None:
    """A pulse weapon's `_watch_checks` is its charge watcher's check
    count, kept by the watcher (FloatRangeWatcher._owner): the row must hold
    the count the watcher has NOW, so a check added or removed behind the
    watcher's methods is caught, not only a missed push. A watcher the
    weapon does not own (ChargeWatcherField) holds WATCH_ALWAYS. An owned
    watcher's `_value` must be the row's `_watch_value`."""
    watcher = weapon.__dict__.get("_charge_watcher")
    owned = _owns_watcher(weapon, watcher)
    if not owned:
        want = WATCH_ALWAYS
    else:
        checks = getattr(watcher, "_checks", None)
        want = len(checks) if isinstance(checks, dict) else None
    if want is None or row["_watch_checks"] != want:
        _failures.append((name, "_watch_checks"))
    # Its value, K0's WATCH old value (an unowned watcher's is never read).
    if owned and float(watcher._value).hex() \
            != float(row["_watch_value"]).hex():
        _failures.append((name, "_watch_value"))


def _audit_cond_watch(sub, row, name) -> None:
    """Each condition watcher's check count and (an adopted one's) value,
    as the watcher holds them NOW: a check added behind its methods is
    caught, not only a missed push."""
    for which, (_slot, cf, vf) in _COND_WATCH_SLOTS.items():
        n, v = _cond_watch_state(sub, which)
        if row[cf] != n:
            _failures.append((name, cf))
        if n >= 0 and v.hex() != float(row[vf]).hex():
            _failures.append((name, vf))


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


# ── The compute timers (kernels off the lock, Task 1) ──────────────────────
#
# The binding times exactly each kernel's compute call (ComputeSpan in
# host_bindings.cc: K0-K3's next(), K3's apply_hits, K4's k4_eligible) into
# one accumulator per kernel; combat_compute_take(k) reads and zeroes it.
# K0-K3 compute with the GIL released (THE GIL RELEASE there: kernels off
# the lock, Task 3). Each driver takes its kernel's once a session (K3: once
# more after its hits; K4: once a call) and reports it to the frame
# profiler as `k<k>.compute`, a child of the scope the session ran in. That
# scope is the kernel's home row (_COMPUTE_HOME) in the tick's own step; a
# session run under any other scope -- K1's AI-started system sessions
# (StartFiring inside gl.ai), or one started by an effect delivered in
# sim.effects -- reports as `k<k>.compute@<scope>`, so no row is ever
# recorded under two parents (frame_profiler.record) and each reads at most
# its parent. The take runs whether the profiler is on or not, so the
# accumulator never carries a session's time into another.
#
# K1 sessions nest (a handler a record runs may start one): a session's own
# compute is what the accumulator gained while it was the innermost one, so
# entering a nested session first banks the accumulator into the enclosing
# session's tally (_k1_compute: [scope, ms, calls] per open session).
# K0, K2 and K3 refuse to nest, and their accumulators are their own.

_COMPUTE_HOME = ("sim.weapons", "cb.held_weapons", "cb.phasers",
                 "cb.projectiles", "cb.eligibility")
_k1_compute: list = []


def _compute_record(k, where, ms, n) -> None:
    """Report kernel `k`'s compute (`n` calls, `ms`) run under `where`."""
    if n and _prof._enabled:
        if where == _COMPUTE_HOME[k]:
            _prof.record("k%d.compute" % k, ms, n)
        else:
            _prof.record("k%d.compute@%s" % (k, where), ms, n)


def _compute_taken(k) -> None:
    """A K0/K2/K3 session or a K4 call is over: its compute, to the scope
    open around it."""
    ms, n = _h.combat_compute_take(k)
    _compute_record(k, _prof.open_scope(), ms, n)


def _k1_compute_enter() -> None:
    """A K1 session starts: bank what the enclosing one computed so far."""
    if _k1_compute:
        ms, n = _h.combat_compute_take(1)
        top = _k1_compute[-1]
        top[1] += ms
        top[2] += n
    _k1_compute.append([_prof.open_scope(), 0.0, 0])


def _k1_compute_exit() -> None:
    """A K1 session ends: its own compute, to the scope it started in."""
    ms, n = _h.combat_compute_take(1)
    if not _k1_compute:         # reset() mid-session (tests)
        return
    where, ms0, n0 = _k1_compute.pop()
    _compute_record(1, where, ms0 + ms, n0 + n)


# ── K1: the native fire-control kernel's driver (phase 1b) ─────────────────
#
# native/src/combat/include/dauntless/combat/k1_fire_control.h is the
# contract, and the kernel fire control's one copy of its rules (fire
# control native only, M3): it walks the held-weapon pump and each weapon
# system's update over the mirror and runs a session WHOLE in one
# combat_k1_next(), whose one record (DONE) carries the session's writes;
# the binding applies them (C-applied write logs, below apply_writes) and
# appends its queue entries. No Python runs inside a session. Whatever the
# mirror cannot answer does not fire that tick (k1_fire_control.h, NO FIRE),
# counted in k1_no_fire and logged once per why.

_k1_kind_ids = None
_ws = None
_step_memo = None


def _k1_kinds() -> tuple:
    global _k1_kind_ids
    if _k1_kind_ids is None:
        _k1_kind_ids = (_h.combat_k1_kinds()["DONE"],)
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
    """One K1 session's pin set -- handle -> object, holding every object a
    write may name alive until the session's record is applied
    (k1_fire_control.h, PINNING) -- and its materialised walk: its number
    in the session, its system and its offset object."""

    __slots__ = ("pins", "offset", "walk", "walked", "result")

    def __init__(self) -> None:
        self.pins = {}
        self.offset = None
        self.walk = None
        self.walked = None
        self.result = 0

    def materialise(self, n, h):
        """The offset OBJECT of the session's walk `n`, of the system with
        handle `h` (ruling P5: every bank the walk stamps holds this one
        object): made once per walk, on the first logged write naming it
        (("walk_offset", n, h); the write apply, the binding's or
        apply_writes). Built from what the kernel recorded for the walk
        (k1_fire_control.h, THE WALK OFFSET; fire control native only,
        M8.8): the system's own `_held_offset` object when the walk's
        offset came from it, else a new TGPoint3 of the Manual Aim pick the
        walk took (ShipClass.GetTargetOffsetTG's copy)."""
        if self.walk == n:
            return self.offset
        system = self.obj(h)
        self.pin_system(system)
        manual = _h.combat_k1_walk_manual_offset(n)
        self.offset = (system.__dict__.get("_held_offset") if manual is None
                       else TGPoint3(*manual))
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
        now (materialise, and after each later record). A walk that logs
        no stamp (phase 6 A3: a sustained beam already holding its held
        offset object) is never materialised, so nothing pins its system:
        every object its other writes name is found live through the
        registry (`live`), held by the system's own lists, and no Python
        runs between the kernel's walk and the apply to release one."""
        self.pin(system)
        d = system.__dict__
        for child in d.get("_children", ()):
            self.pin(child)
        for target in d.get("_target_list", ()):
            self.pin(target)

    def live(self, h):
        """The object `h` names, as obj(), or None when it names no pinned
        or live object (a row freed since)."""
        if h == REF_NONE:
            return None
        o = self.pins.get(h)
        if o is None:
            o = _registry.get(h)
            if o is None or o.__dict__.get("_nslot") != h:
                return None
            self.pins[h] = o
        return o

    def obj(self, h):
        """The object a record or write names: None for -1."""
        o = self.live(h)
        if o is None and h != REF_NONE:
            raise RuntimeError(
                "combat K1: handle %#x names no pinned or live object" % h)
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
        setter._plain_store = True      # _ApplyKinds: the C path's store
    else:
        raise TypeError("combat K1: no quiet write for %s.%s"
                        % (cls.__name__, name))
    hit = _quiet_setters[key] = (setter, kind)
    return hit


def apply_writes(writes, walk=None) -> None:
    """Apply a K1 write log [(handle, field, value), ...] in order, without
    pushing (the kernel already wrote the mirror). Ref values are handles
    (-1: None), a ref list a list of handles, ("slot", index, value) an
    in-place write of one element of the object's own list (K1's launch:
    a tube's slot cooldown); the marker ("walk_offset",
    walk, system) is that walk's own offset object (_K1Walk.materialise:
    the first write naming a walk not yet materialised fetches it). `walk`
    maps handles through its pin set; without one, through the registry.

    THE REFERENCE: the K1/K2 drivers no longer call this -- the bindings
    apply each record's log themselves through the applier context
    (_applier_context, native/src/host/combat_write_apply.h), which must
    equal this function write for write, exceptions included
    (tests/unit/test_native_write_apply.py). It stays for the tests and for
    a binding with no context installed.

    A RAISE PART-WAY: the kernel has already written every value in the
    log to the mirror, and run_k1's abandon cannot undo a delivered write
    (the kernel's rollback covers only writes it has not yet delivered). So
    when one write raises, every write after it is still applied, in order
    (_apply_rest), and then the exception is re-raised: the mirror still
    equals Python except for the write that raised. One Python call sits in
    the log: materialise (a dict read or a TGPoint3; THE WALK OFFSET, M8.8),
    which a patched TGPoint3 could make raise. A later "walk_offset" write
    of the walk whose materialise raised is then skipped, not retried, and
    the bank keeps its previous offset object; a later walk's is fetched as
    usual. The
    plain writes cannot raise: the logged fields are a fixed set
    on pinned rows -- plain NativeFields, whose quiet write is a dict store,
    and a bank's `_firing` (round trips Task 2), a NativeWakeField whose
    quiet write is WakeField.__set__: a dict store, then passive_state.wake
    on a sleeping bank, whose hook (passive_weapons.on_wake) is a dict read
    and an insort. A field added to the kernel's log must keep its quiet
    write unable to raise. K2's log (run_k2) uses the same
    encoding: `_dwell`, and an offline phaser
    system's stop (round trips Task 3) -- the system's `_fire_held`,
    `_held_target`, `_held_offset`, `_target_list` (a NEW list every time,
    built here) and `_last_group_fired`, each bank's `_firing` and
    `_beam_on_countdown`: plain NativeFields and the same WakeField. K1's
    beam edge and pump stop (combat fire events Task 3) log only those
    fields too: a bank's `_beam_on_countdown` and `_dwell`, the system
    stop's five."""
    if walk is None:
        walk = _K1Walk()
    i = 0
    try:
        for i, (h, field, value) in enumerate(writes):
            _apply_write(walk, h, field, value)
    except BaseException as e:
        failed = writes[i][2]
        _apply_rest(writes[i + 1:], walk,
                    {failed[1]} if (type(failed) is tuple
                                    and failed[0] == "walk_offset")
                    else set(), e)
        raise


def _apply_write(walk, h, field, value) -> None:
    """One logged write (apply_writes)."""
    obj = walk.obj(h)
    if type(value) is tuple and value[0] == "slot":
        # ("slot", index, value): in place, on the object's own list (a
        # tube's _reload_timers / _reload_advanced_at: K1's launch).
        obj.__dict__[field][value[1]] = value[2]
        return
    setter, kind = _quiet_setter(type(obj), field)
    if kind is _REF:
        value = walk.obj(value)
    elif kind is _REFS:
        value = [walk.obj(v) for v in value]
    elif type(value) is tuple:              # ("walk_offset", walk, system)
        value = walk.materialise(value[1], value[2])
    setter(obj, value)


def _apply_rest(writes, walk, failed, exc) -> None:
    """apply_writes after a write raised `exc`: the rest, in order. A
    "walk_offset" write of a walk in `failed` (its materialise raised) is
    skipped; another walk's materialise raising adds it to `failed` and a
    note to `exc` (re-raised by the caller). Any other raise propagates,
    with `exc` as its __context__."""
    for h, field, value in writes:
        if (type(value) is tuple and value[0] == "walk_offset"
                and walk.walk != value[1]):
            if value[1] in failed:
                continue
            try:
                walk.materialise(value[1], value[2])
            except Exception as e2:
                failed.add(value[1])
                exc.add_note("combat K1: walk %d's offset also raised "
                             "%r" % (value[1], e2))
                continue
        _apply_write(walk, h, field, value)


# ── C-applied write logs (native weapon state, Task 1) ──────────────────────
#
# native/src/host/combat_write_apply.h is the contract. The drivers install
# an applier context for each session (combat_set_applier) and the bindings
# apply every record's write log themselves, exactly as apply_writes above
# (kept: the reference, and the path with no context). The apply kinds
# (combat_apply_kinds):
APPLY_PLAIN, APPLY_REF, APPLY_REFS, APPLY_WAKE, APPLY_PYTHON, APPLY_SLOT, \
    APPLY_WATCHER = range(7)


class _ApplyKinds(dict):
    """(class, field) -> apply kind, computed on first ask from the
    `_quiet_setter` in force when this mapping was made (`source`): its
    plain store is PLAIN / REF / REFS by its value kind, a WakeField's own
    __set__ is WAKE (C stores, then passive_state.wake), any other setter
    PYTHON, kept in `setters` as (setter, value kind) for the binding to
    call. A lookup that raises (no quiet write) is not cached, as in
    _quiet_setter."""

    __slots__ = ("source", "setters")

    def __init__(self, source) -> None:
        super().__init__()
        self.source = source
        self.setters = {}

    def __missing__(self, key):
        cls, name = key
        setter, vkind = self.source(cls, name)
        conv = (APPLY_REF if vkind is _REF else
                APPLY_REFS if vkind is _REFS else APPLY_PLAIN)
        if getattr(setter, "_plain_store", False):
            kind = conv
        elif (conv == APPLY_PLAIN
              and getattr(setter, "__func__", None) is WakeField.__set__
              and getattr(setter.__self__, "_name", None) == name):
            kind = APPLY_WAKE
        else:
            kind = APPLY_PYTHON
            self.setters[key] = (setter, conv)
        self[key] = kind
        return kind


_apply_kinds = None


def _applier_context(walk) -> tuple:
    """combat_set_applier's context for a session walking with `walk`:
    (pins, registry, walk, kinds, wake, python_setters). The kinds mapping
    lives until reset() or until `_quiet_setter` is replaced (a test's
    tracing wrapper); the binding caches its answers per (type, field)
    until it is handed another one.

    So the apply kinds are FIXED for the session (in practice for the
    process): a descriptor patched onto a class after its (type, field)
    was first asked keeps the old kind, exactly as Python's own
    `_quiet_setters` cache keeps the old setter per class."""
    global _apply_kinds
    kinds = _apply_kinds
    if kinds is None or kinds.source is not _quiet_setter:
        kinds = _apply_kinds = _ApplyKinds(_quiet_setter)
    return (walk.pins, _registry, walk, kinds, _passive_state.wake,
            kinds.setters)


# run_k1's `offset` when the session has no pre-made walk.
_NO_OFFSET = object()


def run_k1(dt, system=None, offset=_NO_OFFSET) -> int:
    """Run the kernel's top session (begun by k1_pump, k1_system,
    k1_tractor_start or THE SDK ROUTES) whole: its one record's writes are
    applied by the binding before it is returned (the session's applier
    context, _applier_context; the previous context -- an outer session's
    -- is restored at the end) and its queue entries appended. `system`, a
    system session's, is pinned. `offset` (a tractor StartFiring session, a
    Fire session): the session's walk 1 is already materialised, its offset
    object this one. Returns the session's result (combat_k1_result: a Fire
    session's). The kernel's no-fire whys counted for the first time are
    logged, one line each.

    THE EFFECT QUEUE (spec 2026-11-02-combat-fire-events §4.1, ruling F3):
    begun while nothing defers (StartFiring from gl.ai, from a delivered
    event's handler), the session opens its own deferral
    (effect_queue.session) and delivers everything it produced at its end,
    in emission order; inside the tick's scope (or an enclosing session)
    that one delivers.

    On any exception the session is abandoned (the kernel's mirror still
    equals Python) and the exception re-raised."""
    _k1_compute_enter()
    try:
        with _effect_queue.session():
            return _run_k1(system, offset)
    finally:
        _k1_compute_exit()


def _run_k1(system, offset=_NO_OFFSET) -> int:
    """run_k1's one call, inside the session's deferral."""
    walk = _K1Walk()
    if system is not None:
        walk.pin_system(system)
    if offset is not _NO_OFFSET:
        walk.walk, walk.offset, walk.walked = 1, offset, system
    prev = _UNSET
    try:
        prev = _h.combat_set_applier(_applier_context(walk))
        rec = _h.combat_k1_next()
        walk.result = _h.combat_k1_result()
        _h.combat_k1_end()
    except BaseException:
        _h.combat_k1_abandon()
        raise
    finally:
        if prev is not _UNSET:
            _h.combat_set_applier(prev)
    if rec[2]:
        _k1_log_kernel_no_fires(rec[2])
    return walk.result


def _k1_entry(ships) -> tuple:
    """Every K1 session's start: the drain point (ruling R2), a stale
    launch cache re-pushed (M8.3: a mission swap's reset, a re-imported
    cannon module), and every part slot the walk reads fresh (a step
    boundary: hits, deaths and damage may have bumped the generation; a
    resolution that raised is retried, M8.4). Returns the clocks. The
    mirror is made live first (fire_control_native: a call before
    configure(), or a loud failure)."""
    fire_control_native()
    drain()
    _refresh_stale_launches()
    resolve_stale_part_slots(ships)
    return _k1_clocks()


def k1_pump(ships, dt) -> None:
    """host_loop._pump_held_weapons(ships, dt): one native session (fire
    control native only, M3). `ships` is a list; a ship with no Object row
    is passed as -1 and does not fire (k1_no_fire unslotted_ship)."""
    t, use_memo, drift = _k1_entry(ships)   # live before reading slots
    handles = []
    for ship in ships:
        h = slot(ship)
        handles.append(REF_NONE if h is None else h)
    _h.combat_k1_begin_pump(handles, dt, t, use_memo, drift)
    run_k1(dt)


def k1_system(system, dt) -> None:
    """WeaponSystem.StartFiring's immediate update (dt 0) as one native
    session. A system with no Subsystem row does not fire (k1_no_fire
    no_row, logged once)."""
    fire_control_native()       # live before reading the row (a resync)
    h = system.__dict__.get("_nslot")
    if h is None or (h >> _KIND_SHIFT) != _kind("Subsystem"):
        _k1_no_fire("no_row", "a weapon system with no mirror row")
        return
    # StartFiring runs inside gl.ai, an effect's handler, ...: the walk reads
    # the parent ship's slots and, aiming at a posed target's offset, the
    # target's.
    t, use_memo, drift = _k1_entry(_k1_system_ships(system))
    _h.combat_k1_begin_system(h, dt, t, use_memo, drift)
    run_k1(dt, system=system)


def k1_tractor_start(system, target, offset) -> None:
    """TractorBeamSystem.StartFiring after its gates (fire control native
    only, M4; k1_fire_control.h, THE TRACTOR WALK): the engage intent is
    recorded here, in Python, before the engage-range check -- so the pump
    re-acquires when the geometry allows -- and the engage itself is a
    native system session: the range check, the engage at `offset`, the
    firing edge's event (an effect-queue entry, ruling R8). Every write the
    kernel logs lands on the live objects (a projector's `_firing` through
    its NativeWakeField setter: the passive weapons wake). A system with no
    mirror row engages nothing (k1_no_fire tractor_row, logged once)."""
    system._add_target(target)
    system._fire_held = True
    system._held_target = target
    system._held_offset = offset
    fire_control_native()       # the mirror live (or a loud failure)
    h = system.__dict__.get("_nslot")
    if h is None or (h >> _KIND_SHIFT) != _kind("Subsystem"):
        _k1_no_fire("tractor_row", "a tractor system with no mirror row "
                    "engages nothing")
        return
    t, use_memo, drift = _k1_entry(_k1_system_ships(system))
    th = REF_NONE if target is None else _handle_of(target, "Object")
    _h.combat_k1_begin_tractor(
        h, th, (offset.x, offset.y, offset.z)
        if isinstance(offset, TGPoint3) else None, t, use_memo, drift)
    run_k1(0.0, system=system, offset=offset)


# ── THE SDK ROUTES (k1_fire_control.h; fire control native only, M8.1,
# M8.6): the SDK's own Weapon.FireDumb, Fire and CanFire as the native rule.

def _sdk_leaf(weapon, kinds):
    """`weapon`'s Subsystem handle for its SDK call: a live row of a leaf
    kind in `kinds`. Else None, a no-fire (k1_no_fire no_row, logged once):
    fire control has no other copy (M3). Makes the mirror live first
    (fire_control_native)."""
    fire_control_native()
    h = weapon.__dict__.get("_nslot")
    if h is None or (h >> _KIND_SHIFT) != _kind("Subsystem") \
            or _weapon_kind_of_class(type(weapon)) not in kinds:
        _k1_no_fire("no_row", "a weapon with no mirror row")
        return None
    return h


def _weapon_ship(weapon):
    ship = weapon._climb_to_ship() if hasattr(weapon, "_climb_to_ship") \
        else None
    return [] if ship is None else [ship]


def k1_dumb_fire(tube) -> None:
    """Weapon.FireDumb(0, 1) as a one-tube native session (M8.1): the
    kernel's dumb fire -- the warp-in hold, the tube's Fire decision with
    no target, the launch logged with its SPAWN. A weapon that is not a
    torpedo tube (the SDK dumb-fires tubes only) is, past the same warp-in
    hold, its own Fire(None, None): native for every fire-control kind, and
    a Weapon subclass that never implemented Fire still raises
    NotImplementedError (loud)."""
    if _weapon_kind_of_class(type(tube)) != 8:
        from engine.appc import weapon_subsystems as ws
        if not ws._dewarp_blocks_fire(tube):    # the warp-in hold, as a tube's
            tube.Fire(target=None, offset=None)
        return
    h = _sdk_leaf(tube, (8,))
    if h is None:
        return
    t, use_memo, drift = _k1_entry(_weapon_ship(tube))
    _h.combat_k1_begin_dumb(h, t, use_memo, drift)
    run_k1(0.0)


def k1_fire(weapon, target, offset) -> bool:
    """weapon.Fire(target, offset) as a one-weapon native session (M8.6):
    the decision and its effect. Returns Fire's bool: False for a weapon
    with no row, a target the mirror cannot name, or a decision or launch
    the mirror cannot make (each a counted no-fire, its writes rolled
    back): never Python's Fire, so a shot is never made twice."""
    h = _sdk_leaf(weapon, (5, 6, 7, 8))
    if h is None:
        return False
    th = REF_NONE if target is None else _handle_of(target, "Object")
    if th == REF_UNREPRESENTABLE:
        _k1_no_fire("unnamed_target", "a Fire whose target the mirror "
                    "cannot name")
        return False
    ships = _weapon_ship(weapon)
    if target is not None:
        ships.append(target)
    # The cannon decision's `ship.GetTarget()` fallback (target None, no
    # stamped _target): SDK state the mirror does not hold, read here.
    ship_target = None
    if (target is None and weapon.__dict__.get("_target") is None
            and ships and hasattr(ships[0], "GetTarget")):
        st = ships[0].GetTarget()
        ship_target = REF_NONE if st is None else _handle_of(st, "Object")
    t, use_memo, drift = _k1_entry(ships)
    _h.combat_k1_begin_fire(
        h, th, (offset.x, offset.y, offset.z)
        if isinstance(offset, TGPoint3) else None, ship_target,
        t, use_memo, drift)
    return bool(run_k1(0.0, offset=offset))


def k1_can_fire(weapon) -> int:
    """weapon.CanFire() from the mirror (M8.6): the native rule's answer as
    an int, its `_depleted = False` made through the field's own setter (so
    the mirror, already answering as if it were made, agrees). 0 for a
    weapon with no row or one the mirror cannot answer for (a counted
    no-fire)."""
    h = _sdk_leaf(weapon, (5, 6, 7, 8))
    if h is None:
        return 0
    from engine.appc import weapon_subsystems as ws
    now = ws._game_time() if _weapon_kind(weapon) == 8 else 0.0
    try:
        ok, clear = _h.combat_k1_can_fire(h, now)
    except ValueError:
        _k1_no_fire("sdk_can_fire", "a CanFire the mirror cannot answer")
        return 0
    if clear:
        weapon._depleted = False
    return 1 if ok else 0


def tractor_force_step(ships, dt) -> None:
    """engine.appc.tractor.advance_tractors(ships, dt): one native step of
    the tractor force (tractor_force.h; fire control native only, R7), in
    the motion stage (`motion.tractors`, ship_motion.tick_tractors). The kernel writes the transform store itself; Python then
    applies what it hands back: HOLD's damped targets (SetVelocity(0)) and
    the engage geometry it captured (`_engage_state`, stored quietly: the
    mirror already holds it). A ship with no Object row does nothing
    (k1_no_fire tractor_row, logged once); a tractor the mirror cannot name
    moves nothing (logged once). Never the switch: the mirror is made live
    first (fire_control_native)."""
    fire_control_native()
    handles = []
    for ship in ships:
        h = ship.__dict__.get("_nslot") if hasattr(ship, "__dict__") else None
        if h is None or (h >> _KIND_SHIFT) != _kind("Object"):
            if getattr(ship, "GetTractorBeamSystem", None) is not None:
                _k1_no_fire("tractor_row", "a ship with no mirror row: its "
                            "tractor moves nothing")
            continue
        handles.append(h)
    zero, captures, _applied, skipped = _h.combat_tractor_force_step(
        handles, dt)
    for h, kind, xyz in captures:
        system = _registry.get(h)
        if system is not None and system.__dict__.get("_nslot") == h:
            system.__dict__["_engage_state"] = {
                _ENGAGE_KEYS[kind]: TGPoint3(*xyz)}
    for h in zero:
        obj = _registry.get(h)
        if obj is not None and obj.__dict__.get("_nslot") == h \
                and hasattr(obj, "SetVelocity"):
            obj.SetVelocity(TGPoint3(0.0, 0.0, 0.0))
    if skipped:
        _log_once("tractor_force_skipped", "a tractor the mirror cannot "
                  "name moved nothing")


def _k1_system_ships(system) -> list:
    """The ships a system session's walk may read part slots of: the
    parent ship and every entry of the system's target list."""
    ship = system.GetParentShip()
    ships = [] if ship is None else [ship]
    for t in system.__dict__.get("_target_list") or ():
        if t is not None and hasattr(t, "__dict__"):
            ships.append(t)
    return ships


# ── K0: the native charging kernel's driver (native weapon state) ─────────
#
# native/src/combat/include/dauntless/combat/k0_charging.h is the contract;
# spec docs/superpowers/specs/2026-11-02-native-weapon-state-design.md §4.3.
# host_loop._advance_weapons(ships, dt) asks k0_weapons first: K0 steps
# every weapon of every ship from the mirror (the per-tick model: the awake
# list is never consulted or changed, and nothing is put to sleep) and
# stops at each thing only Python may do; the binding applies the record's
# write log (C-applied write logs, _applier_context) before returning it,
# and run_k0 does that one thing:
#   RUN_PYTHON    a weapon's UpdateCharge / UpdateReload (isinstance
#                 dispatch, as step_every_weapon), or a whole ship: what
#                 the passive walk runs for it (passive_weapons.advance of
#                 that ship with passive state on, step_every_weapon off)
# A firing bank drained dry, a reload and a pulse cannon's watcher line are
# no longer records (combat fire events Task 4; k0_charging.h, THE EFFECT
# QUEUE): the kernel logs what StopFiring / ReloadTorpedo / the watcher's
# `_update` write, and the binding appends their LOOP_STOP / TORPEDO_RELOAD
# / WATCH to the combat effect queue, delivered at the tick boundary -- or,
# for a session begun while nothing defers, at its end (run_k0 opens
# effect_queue.session(), ruling F3), Python's own producers in it too.
#
# WHO A RECORD NAMES. A record names its weapon by handle and by position
# in the begin snapshot (ship_pos, group, index: the ship list run_k0 holds,
# the group getter, GetWeapon(index)). A handle with a live row (or one the
# walk already pinned) is that object. A weapon the mirror cannot name (-2:
# unregistered, or None in `_children`) or whose row went stale is found by
# position, through the same getters the passive walk calls -- the object
# at that index at begin unless a handler re-ordered that system's children
# mid-walk (no live trigger does; the passive walk's stale-registry rule has
# the same blind spot).
#
# NO OVERRIDE GUARD (phase 6 A2; spec
# 2026-11-05-phase6-engine-stages-native-design.md §3, Part A: a stage never
# falls back to Python because an App method was patched). K0 steps every
# weapon from the mirror: a class or instance patch of a method the walk
# calls (UpdateCharge, UpdateReload, StopFiring, _broadcast_reload, a
# system's IsOn, a ship's group getters, FloatRangeWatcher._update, ...) is
# not called while K0 runs; only the Python walk (k0_weapons' stand-downs
# below, DAUNTLESS_NATIVE_COMBAT=0) and a RUN_PYTHON record's own Python
# honour one. The hand-backs left are the kernel's representability reasons
# (k0_charging.h K0Reason): no_row, not_weapon_system, stale_row,
# slot_heal, power_level, parent, unrepresentable, unknown_kind, watcher.

# k0_weapons' own stand-downs: "off" (native off), "nested" (a K0 session is
# already open: a record's handler re-entered the weapons step), "audit"
# (DAUNTLESS_NATIVE_AUDIT or DAUNTLESS_PASSIVE_AUDIT: the audits compare the
# Python walk, which K0 would bypass).
_K0_STEP_REASONS = ("off", "nested", "audit")
_k0_step_reasons = dict.fromkeys(_K0_STEP_REASONS, 0)
_k0_kind_ids = None


def _k0_kinds() -> tuple:
    global _k0_kind_ids
    if _k0_kind_ids is None:
        k = _h.combat_k0_kinds()
        _k0_kind_ids = tuple(k[n] for n in (
            "DONE", "DEPLETE_STOP", "RELOADED", "WATCH", "RUN_PYTHON"))
    return _k0_kind_ids


def _k0_python(why: str) -> bool:
    _k0_step_reasons[why] += 1
    return False


def k0_weapons(ships, dt) -> bool:
    """host_loop._advance_weapons(ships, dt) through K0. False: K0 did not
    run (counts()["k0_python_step_reasons"]) and the caller runs today's
    Python walk; True: every weapon of every ship was stepped."""
    if not _switch:
        return _k0_python("off")
    if _audit or _passive_state.audit_enabled():
        return _k0_python("audit")
    if _h.combat_k0_open():
        return _k0_python("nested")
    drain()                     # a session start (ruling R2)
    global _ws, _step_memo
    if _ws is None:
        from engine.appc import weapon_subsystems
        from engine.core import step_memo
        _ws, _step_memo = weapon_subsystems, step_memo
    if type(ships) is not list:
        ships = list(ships)
    # The clock every tube of this step reads (WSM D5): one read, Python's
    # own _game_time (its failure is its 0.0 and its log, WSM A10).
    _h.combat_k0_begin(ships, dt, _ws._game_time())
    run_k0(ships, dt)
    return True


def _k0_weapon(rec, ships, walk):
    """The weapon a record names (see WHO A RECORD NAMES), or None."""
    a = rec[1]
    if a >= 0:
        o = walk.pins.get(a)
        if o is not None:
            return o
        o = _registry.get(a)
        if o is not None and o.__dict__.get("_nslot") == a:
            walk.pins[a] = o
            return o
    from engine.appc import passive_weapons
    group = passive_weapons._groups(ships[rec[2]])[rec[3]]
    if group is None:
        return None
    return group.GetWeapon(rec[4])


def _k0_ship_python(ship, dt) -> None:
    """What host_loop._advance_weapons' Python runs for this one ship."""
    from engine.appc import passive_weapons
    if _passive_state.enabled():
        passive_weapons.advance((ship,), dt)
    else:
        passive_weapons.step_every_weapon(ship, dt)


def run_k0(ships, dt) -> None:
    """Drive the open K0 session to DONE (see the section comment). On any
    exception the session is abandoned (the records already returned were
    applied; the kernel undoes what it had not returned) and re-raised --
    the setup before the first record included, or the open session would
    stand every later tick down as `nested`. The applier context in force
    before (an outer K1 session's) is restored.

    THE EFFECT QUEUE (ruling F3): begun while nothing defers (a caller
    stepping weapons outside the tick's scope), the session opens its own
    deferral and delivers what it produced -- its kernel's entries and its
    RUN_PYTHON records' Python alike -- at its end, in emission order;
    inside the tick's scope that one delivers. An abandoned session keeps
    the entries already queued (ruling F5)."""
    try:
        with _effect_queue.session():
            _run_k0(ships, dt)
    finally:
        _compute_taken(0)


def _run_k0(ships, dt) -> None:
    """run_k0's loop, inside the session's deferral."""
    prev = _UNSET
    try:
        DONE, _DEPLETE_STOP, _RELOADED, _WATCH, RUN_PYTHON = _k0_kinds()
        walk = _K1Walk()
        prev = _h.combat_set_applier(_applier_context(walk))
        while True:
            rec = _h.combat_k0_next()
            kind = rec[0]
            if kind == DONE:
                break
            if kind != RUN_PYTHON:
                # DEPLETE_STOP, RELOADED and WATCH are writes plus queue
                # entries (k0_charging.h): never returned.
                raise RuntimeError("combat K0: unknown record %r" % (rec,))
            if rec[3] < 0:
                _k0_ship_python(ships[rec[2]], dt)
                continue
            w = _k0_weapon(rec, ships, walk)
            # step_every_weapon's dispatch: None (a None child) and anything
            # else are skipped.
            if isinstance(w, _ws.TorpedoTube):
                w.UpdateReload(dt)
            elif isinstance(w, _ws._EnergyWeaponFireMixin):
                w.UpdateCharge(dt)
        _h.combat_k0_end()
    except BaseException:
        if _h.combat_k0_open():
            _h.combat_k0_abandon()
        raise
    finally:
        if prev is not _UNSET:
            _h.combat_set_applier(prev)


# ── K2: the native beam kernel's driver (phase 2) ───────────────────────────
#
# native/src/combat/include/dauntless/combat/k2_beams.h is the contract. The
# kernel walks host_loop's `cb.phasers` loop (host_loop._phaser_step_ship)
# over the mirror and returns ONE record per combat_k2_next(); the binding
# applies the record's write log (the `_dwell` writes the kernel already
# made in the mirror, and a firing bank's logged stop), then run_k2 does the
# one thing only Python may do: a damage pulse (host_loop._phaser_contact:
# apply_hit, the damage arithmetic included), a whole ship or one bank of
# the loop body, the answer to a question, or a StopFiring the kernel could
# not log (a fallback). A firing bank's stop is logged writes plus a
# LOOP_STOP queue entry since combat fire events Task 4 (k2_beams.h, THE
# EFFECT QUEUE). After each it re-sends the per-step context the
# effect may have changed (_K2Context.resend). After DONE it drains the
# resting contacts the kernel queued: the drain presents the shield splashes
# it can itself (spec 2026-11-02 §4.4, with the constants
# _k2_send_present_constants sent) and returns the rest, which run_k2
# presents in one batch (_k2_present_batch).
#
# WHAT K2 STANDS IN FOR. The kernel computes, from the mirror, what
# host_loop's loop body and the functions and methods it calls would answer
# (k2_beams.h). A module function or stock-class method patched since is NOT
# obeyed (spec Part A, phase 6 A3: a stage never falls back to Python
# because a method was patched); the walk's only whole-step fallbacks are
# representability (nested, instances, audit) and a ship's own:
# A CLASS WITH A ROW whose role name resolves to a method defined outside the
# engine package (a mod's subclass, a test's), or to anything but what it
# resolved to when K2 first saw the class (_k2_flag), read when the ship's
# phaser system or banks are not of the stock class (_k2_python_ship): a
# bank or phaser system class overriding only its own names -> its ship
# runs in Python (ctx python_ships, RUN_PYTHON "overridden"); one
# overriding a subsystem name, or an unseen target or walked-ship class
# flagged "whole" -> the whole step ("patched"). The engine's own classes
# override one another freely (DamageableObject adds IsDead): the kernel
# ports those (tests/unit/test_native_k2_override_guard.py, statically).
# An INSTANCE attribute shadowing a method the loop calls by name on the
# walked ship, its phaser system or a bank (_K2_*_PATCHES) -> that ship runs
# in Python. (One on a TARGET is not looked for: it would cost a dict probe
# of every target, every tick.)
# Presentation internals are not a mod surface either (ruling Q5, spec
# 2026-11-02-combat-effect-queue; roadmap decision 2): hit_feedback.
# beam_contact, hit_feedback._mesh_xyz, host_io.shield_hit and combat.
# weapon_splash_radius. The drain's native shield splash stands in for
# them, so a patch of one is not obeyed for a splash the drain presents (it
# still is for every entry the drain returns to the Python batch). The
# differentials spy them and compare the native splashes through
# combat_present_capture.

_k2_kind_ids = None
_k2_hl = None
_k2_cheats = None

_K2_SUBSYSTEM_NAMES = ("GetWorldLocation", "GetPosition", "_climb_to_ship")
_K2_OBJECT_NAMES = ("IsDead", "GetWorldLocation", "GetWorldRotation",
                    "GetContainingSet", "GetScale", "GetRadius", "GetBaseRadius",
                    "GetShields")
#: role -> (module, stock class name, the names it stands in for), in
#: isinstance order (a bank is a WeaponSystem, not a PhaserSystem).
_K2_ROLES = (
    ("bank", "engine.appc.weapon_subsystems", "PhaserBank",
     _K2_SUBSYSTEM_NAMES + (
         "IsFiring", "IsBeamOn", "take_dwell", "accumulate_dwell",
         "_strip_emit_position", "_emitter_world_position", "GetLength",
         "GetDirection", "GetUp", "GetArcWidthAngles", "GetArcHeightAngles",
         "IsDisabled", "IsDestroyed",
         # THE DAMAGE PULSE (native damage Task 4) reads their values.
         "GetMaxDamage", "GetMaxDamageDistance", "GetDamageRadiusFactor")),
    ("system", "engine.appc.weapon_subsystems", "PhaserSystem",
     _K2_SUBSYSTEM_NAMES + (
         "GetNumWeapons", "GetWeapon", "GetNumChildSubsystems",
         "GetChildSubsystem", "IsOn", "IsDisabled", "IsDestroyed",
         "GetPowerLevel", "PP_LOW")),
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
# StopFiring (system and bank): an offline system's stop is logged writes
# when its banks are idle (round trips Task 3). GetPowerLevel: a resting
# contact carries the mirror's `_power_level` (spec 2026-11-02 §4.3).
# PP_LOW, and a bank's GetMaxDamage, GetMaxDamageDistance and
# GetDamageRadiusFactor: THE DAMAGE PULSE reads the mirrored values (native
# damage Task 4). The bank's three (_K2_BANK_PULSE_PATCHES) are read by the
# pulse alone, so one on a bank's instance hands THAT bank's pulses to
# Python (pulse "python_banks"), not its ship: the walk and the drain, which
# calls the bank's own GetDamageRadiusFactor, stay native.
_K2_SYSTEM_PATCHES = frozenset((
    "GetNumWeapons", "GetWeapon", "IsOn", "IsDisabled", "IsDestroyed",
    "StopFiring", "GetPowerLevel", "PP_LOW"))
_K2_BANK_PATCHES = frozenset((
    "IsFiring", "IsBeamOn", "take_dwell", "accumulate_dwell",
    "_strip_emit_position", "_emitter_world_position", "GetLength",
    "StopFiring", "GetMaxDamage", "GetMaxDamageDistance",
    "GetDamageRadiusFactor"))
_K2_BANK_PULSE_PATCHES = frozenset((
    "GetMaxDamage", "GetMaxDamageDistance", "GetDamageRadiusFactor"))
_K2_BANK_WALK_PATCHES = _K2_BANK_PATCHES - _K2_BANK_PULSE_PATCHES

# The snapshot (k2_snapshot_stock): [(role, stock class, resolution), ...]
# for the role classes (the stock classes _k2_flag and the scans compare a
# class against), and host_io. None until taken: K2 never runs before it.
_k2_role_snapshot = None
_k2_stock_by_role = {}
_k2_host_io = None
_k2_stock_bank = None
_k2_stock_system = None
# class -> (overridden, whole, resolution): a class's flags (_k2_flag) and
# its role's names as K2 first saw them resolve (re-checked at every entry).
_k2_flags: dict = {}
# Classes with a row, in first-registration order (register, reclassify):
# the classes whose flags the mirror holds (representability: a row of a
# class not in _k2_seen_set has stale class flags).
_k2_seen: list = []
_k2_seen_set: set = set()
# Bumped whenever _k2_seen is cleared (forget_rows): a reader that keeps a
# position in it (native_motion's class watch) starts again.
_seen_gen = 0
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
    the stock role classes (_k2_flag's and the scans' reference), before
    any test, tool or mod can replace a method."""
    global _k2_role_snapshot, _k2_host_io
    global _k2_hl, _k2_cheats, _k2_stock_bank, _k2_stock_system
    import importlib
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
    _k2_host_io = host_io
    _k2_hl, _k2_cheats = host_loop_module, cheats
    _k2_flags.clear()


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
    reclassified, so the mirror holds its class flags); else 2 when it is
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


def _k2_python_ship(ship, pulse_banks=None) -> int:
    """0: K2 may walk `ship`'s phaser step; 1: its ship must run in Python
    (an instance attribute shadowing a stood-in name on it, its phaser
    system or a bank, a bank or system class overriding one of its own
    names, or the ship's class or a bank's target's class one K2 never
    saw); 2: the whole step must (a bank or system class overriding a
    subsystem name, or a never-seen class flagged "whole"). k2_phasers
    inlines the common case (stock classes, no instance attribute, seen
    classes) and calls this for the rest. A bank whose instance shadows
    only names the pulse reads (_K2_BANK_PULSE_PATCHES) leaves the ship
    walkable: its handle is appended to `pulse_banks` (its pulses are
    Python's); a bank with no Subsystem handle sends the ship instead."""
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
        keys = bd.keys()
        if not keys.isdisjoint(_K2_BANK_PATCHES):
            h = bd.get("_nslot")
            if (not keys.isdisjoint(_K2_BANK_WALK_PATCHES)
                    or pulse_banks is None or type(h) is not int
                    or (h >> _KIND_SHIFT) != _kind("Subsystem")):
                why = 1
            else:
                pulse_banks.append(h)
        target = bd.get("_target")
        if target is not None:
            unseen = _k2_unseen(type(target))
            if unseen == 2:
                return 2
            why = max(why, unseen)
    return why


def _k2_ship_handles(ships):
    """(handles, python_ships, whole, pulse_banks) for begin: each ship's
    Object handle (-1: no row), the ships _k2_python_ship sends to Python,
    whether one sends the whole step, and the banks of walked ships whose
    pulses are Python's. The common case -- a stock phaser system of stock
    banks, no instance attribute, seen classes -- is decided in the binding
    (combat_k2_scan_ships, a C loop over the instance dicts: this runs every
    tick over every bank); only the ships it could not call clean come back
    here, in order, for _k2_python_ship."""
    handles, unclean = _h.combat_k2_scan_ships(
        ships, _kind("Object"), _KIND_SHIFT, _k2_seen_set,
        _k2_stock_system, _k2_stock_bank, _K2_SHIP_PATCHES,
        _K2_SYSTEM_PATCHES, _K2_BANK_PATCHES)
    python_ships = []
    pulse_banks = []
    for ship, h in unclean:
        banks = []
        why = _k2_python_ship(ship, banks)
        if why == 2:
            return handles, python_ships, True, []
        if why == 1:
            python_ships.append(h)
        else:
            pulse_banks.extend(banks)
    return handles, python_ships, False, pulse_banks


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
                 "staged", "sent")

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


def _k2_contact(rec, walk, dt, ship_instances) -> None:
    """A CONTACT record (a damage pulse): _k2_run_contact on its fields."""
    _k2_run_contact(rec[1:15], walk, dt, ship_instances)


def _k2_present_batch(entries, walk, dt, ship_instances) -> None:
    """The drained resting contacts (combat_k2_drain), in queue order: each
    presented by _k2_run_contact with the power level and shields answer
    the kernel took at contact time (k2_beams.h, RESTING CONTACTS). An
    entry naming an object freed or unregistered since it was queued is
    skipped (counted "k2_present_gone"): Python would have presented it
    before then. A presentation that raises does not stop the others:
    every entry is presented, then the first exception is re-raised, each
    later one noted on it (its type and message)."""
    err = None
    for e in entries:
        if any(walk.live(h) is None for h in e[:4]):
            _k2_steps["k2_present_gone"] += 1
            continue
        _k2_steps["k2_present_python"] += 1
        try:
            _k2_run_contact(e[:14], walk, dt, ship_instances, level=e[14])
        except Exception as x:
            if err is None:
                err = x
            else:
                err.add_note("combat K2: a later resting contact's "
                             "presentation raised %s: %s"
                             % (type(x).__name__, x))
    if err is not None:
        raise err


def _k2_run_contact(c, walk, dt, ship_instances, level=None) -> None:
    """One contact: host_loop._phaser_contact on the rebuilt points. `level`
    is the power level the kernel carried (a drained rest); None reads it
    from the loop's own system now (a damage pulse's CONTACT record). The
    shields_block answer rides along unless it is None -- the loop never
    evaluated it, or (a CONTACT record) Python answered it -- when
    beam_contact evaluates its own, as the Python path does. (A damage
    pulse never reads it.)"""
    (bh, th, sh, yh, emitter, target_pos, dist, _aim, impact, normal,
     tier, bubble, shields, flush) = c
    bank, target, ship, sys_ = (walk.obj(bh), walk.obj(th), walk.obj(sh),
                                walk.obj(yh))
    _e, _t, point, n, b = _k2_points(emitter, target_pos, impact, normal,
                                     tier, bubble)
    hl = _k2_hl
    if level is None:
        level = hl._phaser_level(sys_)
    if shields is None:
        hl._phaser_contact(ship, sys_, bank, target, dist, dt, flush, level,
                           point, n, b, ship_instances)
    else:
        hl._phaser_contact(ship, sys_, bank, target, dist, dt, flush, level,
                           point, n, b, ship_instances, shields_block=shields)


def _k2_answer(rec, walk, cx, dt, ship_instances):
    """An ASK record's answer: exactly the Python the kernel stands in for
    (k2_beams.h, the ASK table), on the live objects."""
    query, args = rec[1], rec[2:-1]         # (..., writes)
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
    """Drive the open K2 session until DONE. Each record: its writes are
    applied by the binding (the session's applier context,
    _applier_context) before it is returned, and its queue entries (a
    firing bank's LOOP_STOP: k2_beams.h, THE EFFECT QUEUE) appended; then
    act -- a damage pulse, a whole ship in Python, an ASK answered in
    Python, or a StopFiring the kernel could not log (a row gone, the
    documented fallback) -- then re-send whatever context the Python
    changed. After DONE, before the session ends, the resting contacts the
    kernel queued are drained: the drain presents a shielded one whose
    instance and view offset the kernel knew itself (the shield splash,
    natively), and the rest are presented in one batch (_k2_present_batch).
    On any exception the session is abandoned (the kernel's mirror still
    equals Python; an abandoned walk's queue of resting contacts is dropped
    unpresented, its effect-queue entries kept: ruling F5) and the
    exception re-raised; the kernel's own protocol-invariant RuntimeError
    (k2_beams.h) included, and a raise in the batch, after the batch.

    THE EFFECT QUEUE (ruling F3): begun while nothing defers (a caller
    stepping `cb.phasers` outside the tick's scope), the session opens its
    own deferral and delivers what it produced -- its kernel's entries and
    its records' Python alike -- at its end, in emission order."""
    try:
        with _effect_queue.session():
            _run_k2(ships, dt, ship_instances, cx)
    finally:
        _compute_taken(2)


def _run_k2(ships, dt, ship_instances, cx) -> None:
    """run_k2's loop, inside the session's deferral."""
    DONE, SYSTEM_STOP, BANK_STOP, CONTACT, RUN_PYTHON, ASK = _k2_kinds()
    walk = _K2Walk()
    prev = _UNSET
    try:
        prev = _h.combat_set_applier(_applier_context(walk))
        while True:
            rec = _h.combat_k2_next()
            if _h.combat_k2_take_hits():
                _kernel_hits_landed(ship_instances)
            kind = rec[0]
            if kind == ASK:
                gen = _part_gen
                answer = _k2_answer(rec, walk, cx, dt, ship_instances)
                _heal_part_slots(ships, gen)
                _h.combat_k2_answer(answer)
            elif kind == CONTACT:
                _k2_contact(rec, walk, dt, ship_instances)
            elif kind == BANK_STOP:
                # Only a stop the kernel cannot log (k2_beams.h, RECORDS).
                bank = walk.obj(rec[1])
                walk.pin_bank(bank)
                bank.StopFiring()
            elif kind == SYSTEM_STOP:
                # Only a system whose children it cannot stand in for.
                walk.obj(rec[1]).StopFiring()
            elif kind == RUN_PYTHON:
                _k2_hl._phaser_step_ship(ships[rec[2]], dt, ship_instances)
            elif kind == DONE:
                break
            else:
                raise RuntimeError("combat K2: unknown record %r" % (rec,))
            cx.resend()
        entries = _h.combat_k2_drain()
        if entries:
            _k2_present_batch(entries, walk, dt, ship_instances)
        _h.combat_k2_end()
    except BaseException:
        _h.combat_k2_abandon()
        raise
    finally:
        if prev is not _UNSET:
            _h.combat_set_applier(prev)


def _k2_step_fallback(ship_instances):
    """Why this `cb.phasers` step must run whole in Python, or None. Only
    representability: a patched function or stock-class method is not a
    reason (Part A)."""
    if _k2_role_snapshot is None or _h.combat_k2_open():
        return "nested"
    if ship_instances is not None \
            and type(ship_instances) is not _tracked_instances():
        return "instances"
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


def _k2_send_present_constants() -> None:
    """The drain's native shield splash takes beam_contact's intensity and
    its default radius from here, never from C++ literals: sent when they
    differ from what was last sent (spec 2026-11-02 §4.4)."""
    from engine.appc import combat, hit_feedback
    consts = (float(hit_feedback.shield_impact_intensity("phaser")),
              float(combat.PHASER_DEFAULT_DAMAGE_RADIUS))
    if consts != _k2_present_sent[0]:
        _h.combat_k2_present_constants(*consts)
        _k2_present_sent[0] = consts


def k2_phasers(ships, dt, ship_instances) -> bool:
    """host_loop's `cb.phasers` step through K2: True when it ran, False when
    the caller must run the step in Python whole (counted by why in
    counts()["k2_python_step_reasons"])."""
    drain()                     # a session start (ruling R2)
    why = _k2_step_fallback(ship_instances)
    if why is None:
        handles, python_ships, whole, pulse_banks = _k2_ship_handles(ships)
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
    _k2_send_present_constants()
    cx = _K2Context(ship_instances)
    ctx = cx.delta()
    ctx["python_ships"] = python_ships
    ctx["trace"] = _k2_host_io._h is not None
    ctx["pulse"] = _k2_pulse_ctx(handles, ship_instances, pulse_banks)
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
# representable set; and no ship is listed twice. A class method patched
# since is not a reason (spec Part A, phase 6 A3).

#: Instance attributes that send the step to Python: the methods K3/K4 stand
#: in for on a ship (spec §7's override list).
_STEP_SHIP_PATCHES = (
    "GetContainingSet", "GetTranslate", "SetTranslateXYZ", "GetVelocityTG",
    "IsDead", "GetWorldLocation", "GetRadius", "GetBaseRadius",
    "GetScale")


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
    _compute_taken(4)
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
# WHAT K3 STANDS IN FOR: update_all's decision steps and the module
# functions, constants and Torpedo / ship methods they call, computed from
# the mirror. A module function, constant or class method patched since is
# NOT obeyed (spec Part A, phase 6 A3); a constant reaches the kernel when it
# is pushed (push_globals, resync). The whole-step fallbacks left are
# representability (off, audit, plain_active, instances, scan, row; "patched"
# now only before the snapshot). The static guard that no ENGINE class
# overrides a stood-in method is tests/unit/test_native_k3_override_guard.py.

# "guard" is no longer emitted (the class watch is gone): kept as a key.
_K3_REASONS = ("off", "audit", "plain_active", "scan", "patched", "row",
               "guard", "instances")
_k3_reasons = dict.fromkeys(_K3_REASONS, 0)
# The key of the iids table the K3 kernel holds (it keeps its own, apart from
# K2's): as _k2_iids_sent.
_k3_iids_sent = [_K2_UNSENT, -1, -1]
_k3_proj = None
_k3_ask = None


def k3_snapshot_stock() -> None:
    """Called by host_loop right after k2_snapshot_stock (projectiles is
    imported by then): the module run_k3 drives."""
    global _k3_proj
    _k3_proj = importlib.import_module("engine.appc.projectiles")


def _k3_python(why: str):
    _k3_reasons[why] += 1
    return None


def _k3_fallback(all_ships, ship_instances):
    """Why this `cb.projectiles` step must run whole in Python, or None."""
    if not _switch:
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
    if _k3_dirty:
        # A list mutation the rows could not follow (a reorder, a slice, a
        # clear): never hand the kernel a stale table.
        torpedo_table_rebuild(proj._active)
        if _k3_dirty:
            return "row"        # a torpedo listed twice: no row can hold it
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
    drain()                     # a session start (ruling R2)
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
    finally:
        _compute_taken(3)
    _kind, writes, expired, hits = rec
    rows = _k3_rows
    # Every handle to its object BEFORE any expire(): `_active.remove` drops
    # the torpedo's row (and its _k3_rows entry).
    hit_objs = [(rows[th], walk.obj(sh), point, normal, bubble, is_bubble)
                for th, sh, point, _tier, normal, bubble, is_bubble in hits]
    expiring = [rows[h] for h in expired]
    _k3_apply(writes, rows, walk)
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
    # THE HITS: applied here, after every ET_TORPEDO_EXITED_SET (K3M §A6),
    # each fully before the next; none is handed to host_loop.
    if out:
        _k3_apply_hits(out, ship_instances, walk)
    return []


def _k3_apply(writes, rows, walk) -> None:
    """The DONE write log into the torpedoes' Python attributes, WITHOUT the
    TorpedoField / `_velocity` pushes (the row holds every value already) --
    except the incoming-torpedo table's velocity, which gets exactly the
    write the `_velocity` setter makes (projectiles.Torpedo._velocity).

    A `mount` (the kernel attributed the shot's mount: round trips, Task 4)
    is `_steer_point`'s `_mount_key = (target, x, y, z, mount or None)` of
    the live objects; x, y, z are the offset's own doubles (a TGPoint3
    stores float()s, pushed as they are). Written before every other
    field, as `_steer_point` runs first in `_guide`, and -- like them --
    before run_k3 calls any expire()."""
    proj = _k3_proj
    for h, age, seen, tvel, vel, mount in writes:
        t = rows[h]
        d = t.__dict__
        if mount is not None:
            target, (x, y, z), sub = mount
            d["_mount_key"] = (walk.obj(target), x, y, z, walk.obj(sub))
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


# ── Native damage: the class rules (spec 2026-11-02-native-damage §4.2) ─────
#
# The native hit and condition chain (damage.h) stand in for these methods.
# A class follows the stock rules when each name resolves to what the stock
# class's did at the snapshot (_dmg_snapshot) and none to code outside the
# engine package (_k2_foreign: a test's, a tool's, a mod's); its rows then
# carry dmg_class / dmg_ship, which the native chain reads, and a class that
# does not is handed to Python: the class mirror flags, computed at a
# class's first sight. A class (stock or flagged) patched after that is NOT
# obeyed (spec Part A, phase 6 A3), nor is a module function the chain
# stands in for.

#: ShipSubsystem methods the condition chain stands in for.
_DMG_SUB_NAMES = ("GetCondition", "SetCondition", "SetConditionPercentage",
                  "_set_condition", "_condition_changed",
                  "_threshold_state_now", "GetConditionPercentage",
                  "GetMaxCondition", "IsCritical", "IsInvincible",
                  "_owning_ship", "GetPosition", "GetRadius")
#: The state predicates: ShipSubsystem's leaf rules or WeaponSystem's
#: aggregate ones (dmg_class), nothing else.
_DMG_PREDICATES = ("IsDamaged", "IsDisabled", "IsDestroyed")
#: ShieldSubsystem methods the hit stands in for.
_DMG_SHIELD_NAMES = ("ApplyDamage", "GetCurrentShields", "HasShields",
                     "IsOn", "IsDisabled", "IsDestroyed")
#: ShipClass methods the hit stands in for (`_iter_subsystems` must stay
#: absent: part_severance's mount order, the hit's walk, would follow it).
_DMG_SHIP_NAMES = ("DamageSystem", "IsImmuneToDamage", "GetShields",
                   "GetHull", "GetSubsystems", "GetWorldLocation",
                   "GetWorldRotation", "GetScale", "GetCloakingSubsystem",
                   "_iter_subsystems")
#: CloakingSubsystem methods the hit stands in for (cloak_shields_suspended
#: calls them; the native shields_block reads the mirrored `_cloak_state`).
_DMG_CLOAK_NAMES = ("IsCloaking", "IsDecloaking")
_dmg_stock = None
_dmg_classes: dict = {}


def _dmg_resolve(cls, names) -> tuple:
    return tuple(getattr(cls, n, None) for n in names)


def _dmg_snapshot() -> dict:
    """The stock classes' resolutions, taken once (before any test, tool or
    mod can patch them: at the first row's flags, or host_loop's start)."""
    global _dmg_stock
    if _dmg_stock is None:
        from engine.appc.ships import ShipClass
        from engine.appc.subsystems import (CloakingSubsystem,
                                            ShieldSubsystem, ShipSubsystem)
        from engine.appc.weapon_subsystems import WeaponSystem
        _dmg_stock = {
            "classes": (ShipSubsystem, WeaponSystem, ShieldSubsystem,
                        ShipClass),
            "cloak_class": CloakingSubsystem,
            "cloak": _dmg_resolve(CloakingSubsystem, _DMG_CLOAK_NAMES),
            "sub": _dmg_resolve(ShipSubsystem, _DMG_SUB_NAMES),
            "leaf": _dmg_resolve(ShipSubsystem, _DMG_PREDICATES),
            "aggregate": _dmg_resolve(WeaponSystem, _DMG_PREDICATES),
            "shield": _dmg_resolve(ShieldSubsystem, _DMG_SHIELD_NAMES),
            "ship": _dmg_resolve(ShipClass, _DMG_SHIP_NAMES),
        }
    return _dmg_stock


def damage_snapshot_stock() -> None:
    """host_loop, beside k3_snapshot_stock: take the stock classes' rules
    and the stock combat.apply_hit now, before any test, tool or mod can
    replace one."""
    _dmg_snapshot()
    _kdmg_apply_hit_stock()


def _dmg_class(cls) -> int:
    """dmg_class for a subsystem class: DMG_LEAF, DMG_AGGREGATE or
    DMG_PYTHON (cached per class until reset())."""
    hit = _dmg_classes.get(("sub", cls))
    if hit is None:
        hit = _dmg_classes[("sub", cls)] = _dmg_class_of(cls)
    return hit


def _dmg_class_of(cls) -> int:
    st = _dmg_snapshot()
    ship_subsystem, _ws, shield, _ship = st["classes"]
    if not issubclass(cls, ship_subsystem):
        return DMG_PYTHON
    names = _dmg_resolve(cls, _DMG_SUB_NAMES)
    preds = _dmg_resolve(cls, _DMG_PREDICATES)
    if names != st["sub"] or any(_k2_foreign(v) for v in names + preds):
        return DMG_PYTHON
    if preds == st["leaf"]:
        rule = DMG_LEAF
    elif preds == st["aggregate"]:
        rule = DMG_AGGREGATE
    else:
        return DMG_PYTHON
    if issubclass(cls, shield):
        values = _dmg_resolve(cls, _DMG_SHIELD_NAMES)
        if values != st["shield"] or any(_k2_foreign(v) for v in values):
            return DMG_PYTHON
    if issubclass(cls, st["cloak_class"]):
        # A ship's cloak: the hit reads its state natively (damage.cc
        # apply_hit hands back a DMG_PYTHON cloak).
        values = _dmg_resolve(cls, _DMG_CLOAK_NAMES)
        if values != st["cloak"] or any(_k2_foreign(v) for v in values):
            return DMG_PYTHON
    return rule


def _dmg_ship(cls) -> int:
    """dmg_ship for an object class: 1 for a ShipClass whose hit the native
    chain stands in for, else 0 (cached per class, as _dmg_class)."""
    hit = _dmg_classes.get(("ship", cls))
    if hit is None:
        hit = _dmg_classes[("ship", cls)] = _dmg_ship_of(cls)
    return hit


def _dmg_ship_of(cls) -> int:
    st = _dmg_snapshot()
    if issubclass(cls, st["classes"][3]):
        values = _dmg_resolve(cls, _DMG_SHIP_NAMES)
        if values == st["ship"] and not any(_k2_foreign(v) for v in values):
            return 1
    return 0


# ── Native damage: the callers (spec 2026-11-02-native-damage §3 goal 4) ─────
#
# With the switch on, every NON-kernel caller of the hit and the condition
# chain runs the native one (damage.h) through these, synchronously: the
# hit (combat.apply_hit: collisions, AddDamage and the death cascade, the
# death splash at its SPLASH delivery, scenery contact, direct calls), the
# DamageSystem (radiation, the SDK), the condition write (SetCondition,
# SetConditionPercentage, DestroySystem, repairs, severance). Each returns
# True when the native chain did it, False when the caller must run the
# Python reference (a class flagged DMG_PYTHON, an instance attribute
# shadowing a method the chain stands in for, an object the mirror cannot
# name, a value it cannot hold -- the native call then changed nothing).
# The binding applies the writes through an applier context installed here,
# and queues the entries holding their objects (damage.h, Held; the
# bindings' damage_append_entries).

_dmg_counts = {"hits": 0, "conditions": 0, "damage_systems": 0,
               "fallbacks": 0}


def damage_counts() -> dict:
    """Since the last reset(): the native hits, condition writes and
    DamageSystem calls, and the calls handed back to Python (a native
    call's fallback). `conditions` counts the condition writes made
    through set_condition (a SetCondition from Python); the
    native subsystem stage's repair writes (subsystem_step.h THE REPAIR
    PIECE) call damage.h's set_condition directly and are not counted."""
    return dict(_dmg_counts)


def _dmg_handle(obj, kind: str):
    """`obj`'s row handle when it is a registered row of `kind`, -1 for None,
    else None (the native chain cannot name it)."""
    if obj is None:
        return REF_NONE
    h = _slot_of(obj)
    if h is None or (h >> _KIND_SHIFT) != _kind(kind):
        return None
    return h


def _dmg_held(obj) -> int:
    """An H operand's handle (damage.h, Held): -1 None, the row of a
    registered object, -2 one the mirror cannot name (its object is still
    the one the entry holds)."""
    if obj is None:
        return REF_NONE
    h = _slot_of(obj)
    return REF_UNREPRESENTABLE if h is None else h


def _dmg_patched(obj, names) -> bool:
    """An instance attribute shadows a method the chain stands in for."""
    d = getattr(obj, "__dict__", None)
    return d is not None and any(n in d for n in names)


#: The one applier context the native damage calls reuse (_dmg_context).
_dmg_ctx = [None]


def _dmg_context() -> tuple:
    """The native damage calls' applier context, made once and reused
    (each call used to make its own _K1Walk's): rebuilt whenever what
    _applier_context reads has changed since -- the kinds mapping (reset(),
    a replaced _quiet_setter), the registry, passive_state.wake. Its pins
    are emptied after every call (_dmg_call; the binding's THE FAST DAMAGE
    ENTRIES), so between calls it holds nothing alive and each call
    resolves its handles afresh, as a fresh walk did."""
    ctx = _dmg_ctx[0]
    kinds = _apply_kinds
    if (ctx is None or kinds is None or ctx[3] is not kinds
            or kinds.source is not _quiet_setter or ctx[1] is not _registry
            or ctx[4] is not _passive_state.wake):
        ctx = _dmg_ctx[0] = _applier_context(_K1Walk())
    return ctx


def _dmg_call(fn, *args) -> bool:
    """`fn(*args)` (a native damage binding) under the reused applier
    context (the previous one restored: a K1/K2 session's), its pins
    emptied after. A call made while it is already installed (an enclosing
    native call's) gets a fresh one of its own."""
    ctx = _dmg_context()
    prev = _h.combat_set_applier(ctx)
    if prev is ctx:
        _h.combat_set_applier(_applier_context(_K1Walk()))
        try:
            return fn(*args)
        finally:
            _h.combat_set_applier(prev)
    try:
        return fn(*args)
    finally:
        _h.combat_set_applier(prev)
        ctx[0].clear()


def _dmg_point(p):
    """A TGPoint3 as three floats (float() of each, as effect_queue._xyz),
    or None."""
    if p is None:
        return None
    return (float(p.x), float(p.y), float(p.z))


def apply_hit(ship, damage, hit_point, source, *, normal=None,
              ship_instances=None, weapon_type=None, hardpoint_weapon=None,
              payload_template=None, splash_radius=None, damage_hull=True,
              bypass_shields=False, shield_point=None, hit_tangent=None,
              decal_radius=None, decal_dent=0.0, single_impact=False,
              shield_radius=None) -> bool:
    """combat._apply_hit natively (its arguments; True: done). The values
    the native hit takes as given are computed here exactly as the
    reference computes them: R_hit (weapon_splash_radius, the splash_radius
    override), the player, the cheats, each operand's float()/bool()."""
    if hit_point is None or _dmg_patched(ship, _DMG_SHIP_NAMES):
        _dmg_counts["fallbacks"] += 1
        return False
    ship_h = _dmg_handle(ship, "Object")
    if ship_h is None or ship_h == REF_NONE:
        _dmg_counts["fallbacks"] += 1
        return False
    # An instance attribute on a subsystem the hit can reach shadowing a
    # method it stands in for (override-guard gap 1): the reference obeys it.
    if not _kdmg_clean([ship])[0]:
        _dmg_counts["fallbacks"] += 1
        return False
    import App
    from engine.appc import combat
    import engine.dev_combat_cheats as cheats
    try:
        game = (App.Game_GetCurrentGame()
                if hasattr(App, "Game_GetCurrentGame") else None)
        player = (game.GetPlayer()
                  if game is not None and hasattr(game, "GetPlayer")
                  else None)
    except Exception:
        player = None
    player_h = _dmg_handle(player, "Object")
    source_h = _dmg_handle(source, "Object")
    if source_h is None:
        source_h = REF_UNREPRESENTABLE      # never the player's
    try:
        r_hit = combat.weapon_splash_radius(hardpoint_weapon,
                                            payload_template)
        if splash_radius is not None:
            r_hit = float(splash_radius)
        args = (
            ship_h, source, source_h, float(damage), _dmg_point(hit_point),
            _dmg_point(normal), float(r_hit), bool(damage_hull),
            bool(bypass_shields), _dmg_point(shield_point),
            shield_point is not None and shield_point is hit_point,
            _dmg_point(hit_tangent),
            None if decal_radius is None else float(decal_radius),
            float(decal_dent), bool(single_impact),
            None if shield_radius is None else float(shield_radius),
            _effect_queue._HIT_WEAPON_CODES.get(weapon_type,
                                                _effect_queue.HIT_WEAPON_NONE),
            int(combat._WEAPON_TYPE_IDS.get(
                weapon_type, _effect_queue.WEAPON_HIT_NON_WEAPON)),
            ship_instances is not None)
    except (TypeError, ValueError, AttributeError, OverflowError):
        _dmg_counts["fallbacks"] += 1
        return False                # the reference raises it
    if player_h is None:
        _dmg_counts["fallbacks"] += 1
        return False
    if ship_instances is not None:
        # The map HIT_PRESENT's delivery presents with (R13).
        from engine.appc import hit_feedback
        hit_feedback.use_instances(ship_instances)
    done = _dmg_call(_h.combat_apply_hit, *args, player_h,
                     bool(cheats.god_mode_active()),
                     bool(cheats.double_player_weapons_active()),
                     bool(cheats.disable_npc_shields_active()))
    _dmg_counts["hits" if done else "fallbacks"] += 1
    return done


#: The instance attributes that hand a condition write back (_dmg_patched).
_DMG_SUB_PATCHES = _DMG_SUB_NAMES + _DMG_PREDICATES
_dmg_ship_subsystem = [None]


def set_condition(sub, value, killer=None, ship=None) -> bool:
    """ShipSubsystem._set_condition natively (True: done): the binding's
    one-call path (THE FAST DAMAGE ENTRIES), else -- None: a case it does
    not decide -- _set_condition_py, the same steps in Python."""
    done = _h.combat_dmg_set_condition(sub, value, killer, ship,
                                       _dmg_context(), _DMG_SUB_PATCHES)
    if done is None:
        return _set_condition_py(sub, value, killer, ship)
    _dmg_counts["conditions" if done else "fallbacks"] += 1
    return done


def _set_condition_py(sub, value, killer=None, ship=None) -> bool:
    """set_condition's steps in Python."""
    if _dmg_patched(sub, _DMG_SUB_PATCHES):
        _dmg_counts["fallbacks"] += 1
        return False
    sub_h = _dmg_handle(sub, "Subsystem")
    ship_h = _dmg_handle(ship, "Object")
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        _dmg_counts["fallbacks"] += 1
        return False                # the reference raises it
    if sub_h is None or sub_h == REF_NONE or ship_h is None:
        _dmg_counts["fallbacks"] += 1
        return False
    done = _dmg_call(_h.combat_set_condition, sub_h, v, _dmg_held(killer),
                     ship_h, killer)
    _dmg_counts["conditions" if done else "fallbacks"] += 1
    return done


def damage_system(ship, sub, amount: float, source=None) -> bool:
    """DamageableObject.DamageSystem natively, past its None and `amt <= 0`
    returns (`amount` already float()); True: done. The binding's one-call
    path, else (None) _damage_system_py."""
    cls = _dmg_ship_subsystem[0]
    if cls is None:
        from engine.appc.subsystems import ShipSubsystem
        cls = _dmg_ship_subsystem[0] = ShipSubsystem
    done = _h.combat_dmg_damage_system(ship, sub, amount, source,
                                       _dmg_context(), _DMG_SUB_PATCHES, cls)
    if done is None:
        return _damage_system_py(ship, sub, amount, source)
    _dmg_counts["damage_systems" if done else "fallbacks"] += 1
    return done


def _damage_system_py(ship, sub, amount: float, source=None) -> bool:
    """damage_system's steps in Python."""
    from engine.appc.subsystems import ShipSubsystem
    if (not isinstance(sub, ShipSubsystem)
            or _dmg_patched(sub, _DMG_SUB_PATCHES)):
        _dmg_counts["fallbacks"] += 1
        return False
    ship_h = _dmg_handle(ship, "Object")
    sub_h = _dmg_handle(sub, "Subsystem")
    if ship_h is None or ship_h == REF_NONE or sub_h is None:
        _dmg_counts["fallbacks"] += 1
        return False
    done = _dmg_call(_h.combat_damage_system, ship_h, sub_h, amount,
                     _dmg_held(source), source)
    _dmg_counts["damage_systems" if done else "fallbacks"] += 1
    return done


# ── Native damage in the kernels (spec 2026-11-02-native-damage §3 goal 2;
# Task 4) ───────────────────────────────────────────────────────────────────
#
# K2 applies each damage pulse in its walk (k2_beams.h, THE DAMAGE PULSE) and
# K3 its hits after the step's expiries (k3_projectiles.h, THE HITS): no
# record hands the damage to Python. What they read that the mirror does not
# hold rides a context (_kdmg_ctx): the player and the cheats, the module
# constants of the arithmetic, the weapon's codes, and the targets the
# override guard scanned clean. A pulse or hit the kernel cannot apply
# (counted by why: k2_pulse_python_reasons, k3_hit_python_reasons) goes to
# Python as before -- K2's CONTACT record, K3's hand-back here.
#
# NOT OK. The context is "not ok" -- every pulse and hit to Python -- when
# combat.apply_hit is not the engine's own (_kdmg_apply_hit_stock), or the
# player is an object the mirror cannot name. A patch of anything else the
# hit stands in for is NOT obeyed (spec Part A, phase 6 A3). combat.apply_hit
# is kept on purpose: it is the hit's OBSERVATION seam -- the golden fights'
# and the dispatch tests' spy records every hit through it (their "calls"),
# so a kernel that applied a hit past the spy would change a recorded golden.
# A target is "clean" when neither it nor any subsystem its hit can reach
# (its mount order, hull, shield generator) has
# an instance attribute shadowing a method the hit stands in for
# (combat_dmg_clean; override-guard gap 1, Task 3's report §8.3, closed the
# K1 way: scanned at the entry point -- K2's begin, K3's apply, the
# non-kernel apply_hit -- ruling L8). A patch made later in the step is seen
# at the next entry.

#: The instance attributes combat_dmg_clean looks for: on the target ship
#: (_DMG_SHIP_NAMES) and on each subsystem its hit can reach (the condition
#: chain's names, the predicates, the shield names).
_KDMG_SUB_NAMES = tuple(dict.fromkeys(_DMG_SUB_NAMES + _DMG_PREDICATES
                                      + _DMG_SHIELD_NAMES
                                      + _DMG_CLOAK_NAMES))
#: A torpedo's: weapon_splash_radius reads GetDamageRadiusFactor on it.
_KDMG_TORP_NAMES = ("GetDamageRadiusFactor",)
_kdmg_apply_hit = [None]


def _kdmg_apply_hit_stock() -> bool:
    """combat.apply_hit is the engine's own, as the first call saw it
    (damage_snapshot_stock takes it at host_loop's start): False for a
    test's spy, which the kernels then obey by handing every hit back (NOT
    OK above)."""
    from engine.appc import combat
    now = combat.apply_hit
    stock = _kdmg_apply_hit[0]
    if stock is None:
        if _k2_foreign(now):
            return False
        stock = _kdmg_apply_hit[0] = now
    return now is stock


def _kdmg_clean(objs) -> list:
    """combat_dmg_clean on `objs` (None reads not clean). Each object's
    answer is cached on its dict's version (THE CLEAN CACHE)."""
    return _h.combat_dmg_clean(objs, _registry.data, _DMG_SHIP_NAMES,
                               _KDMG_SUB_NAMES)


def _kdmg_clean_handles(handles) -> list:
    """The clean ones of Object `handles`, in order: _kdmg_clean on each
    one's `_registry.get(h)`, in the binding."""
    return _h.combat_dmg_clean_handles(handles, _registry.data,
                                       _DMG_SHIP_NAMES, _KDMG_SUB_NAMES)


def _kdmg_ctx(weapon: str, ship_instances, clean) -> dict:
    """The kernels' damage context (the binding's k2_pulse_ctx keys) for a
    `weapon` ("phaser" / "torpedo") step: computed exactly as combat.
    apply_hit and host_loop._phaser_contact read them."""
    import App
    from engine.appc import combat
    from engine.appc.weapon_subsystems import PhaserSystem
    import engine.dev_combat_cheats as cheats
    ok = _kdmg_apply_hit_stock()
    try:
        game = (App.Game_GetCurrentGame()
                if hasattr(App, "Game_GetCurrentGame") else None)
        player = (game.GetPlayer()
                  if game is not None and hasattr(game, "GetPlayer")
                  else None)
    except Exception:
        player = None
    player_h = _dmg_handle(player, "Object")
    if player_h is None:
        ok, player_h = False, REF_NONE
    scale = _k2_hl.PHASER_INTENSITY_SCALE
    try:
        intensity = tuple(float(x) for x in scale)
        if len(intensity) != 3 or any(
                type(x) not in (int, float) for x in scale):
            raise TypeError
    except (TypeError, ValueError, OverflowError):
        ok, intensity = False, (0.0, 0.0, 0.0)
    radius = combat.PHASER_DEFAULT_DAMAGE_RADIUS
    pp_low = PhaserSystem.PP_LOW
    if (type(radius) not in (int, float) or type(pp_low) is not int):
        ok, radius, pp_low = False, 0.0, 0
    return {
        "ok": ok, "player": player_h,
        "god_mode": bool(cheats.god_mode_active()),
        "double_damage": bool(cheats.double_player_weapons_active()),
        "npc_shields_off": bool(cheats.disable_npc_shields_active()),
        "intensity": intensity, "default_radius": float(radius),
        "pp_low": pp_low,
        "hit_weapon": _effect_queue._HIT_WEAPON_CODES[weapon],
        "weapon_hit_type": int(combat._WEAPON_TYPE_IDS[weapon]),
        "has_instances": ship_instances is not None,
        "clean": clean,
    }


def _k2_pulse_ctx(handles, ship_instances, python_banks=()) -> dict:
    """THE DAMAGE PULSE's context for this step: the targets of the banks
    that can pulse, scanned (combat_dmg_clean), and the banks whose pulses
    are Python's (_k2_ship_handles' pulse_banks)."""
    targets = _h.combat_k2_pulse_targets(handles)
    clean = _kdmg_clean_handles(targets) if targets else []
    ctx = _kdmg_ctx("phaser", ship_instances, clean)
    ctx["python_banks"] = list(python_banks)
    return ctx


def _kernel_hits_landed(ship_instances) -> None:
    """A kernel applied hits in its compute since its last record: clear the
    step memo's Python tables before Python reads them (combat.apply_hit
    forgets on every hit; the kernel cleared its own memo, DM H13), and make
    the hits' map the one their HIT_PRESENT delivers with (R13)."""
    from engine.core import step_memo
    step_memo.forget_tables()
    if ship_instances is not None:
        from engine.appc import hit_feedback
        hit_feedback.use_instances(ship_instances)


def _k3_apply_hits(hits, ship_instances, walk) -> None:
    """THE HITS (k3_projectiles.h): host_loop's hit loop, natively, after
    the step's expiries. `hits` is _k3_walk's list of (torpedo, ship,
    hit_point, hit_normal); a hit the kernel hands back runs here, in its
    place, exactly as host_loop runs it (counted "k3_hit_python")."""
    from engine.appc import combat
    ships = [h[1] for h in hits]
    clean = [nc_h for nc_h, c in
             zip((_slot_of(s) for s in ships), _kdmg_clean(ships)) if c]
    pulse = _kdmg_ctx("torpedo", ship_instances, clean)
    # A torpedo shadowing GetDamageRadiusFactor: its hit is Python's.
    python = [i for i, h in enumerate(hits)
              if _dmg_patched(h[0], _KDMG_TORP_NAMES)]
    prev = _h.combat_set_applier(_applier_context(walk))
    try:
        i = 0
        while i < len(hits):
            k = _h.combat_k3_apply_hits(i, pulse, python)
            if k > i:
                _kernel_hits_landed(ship_instances)
            if k >= len(hits):
                break
            _k3_hit_python[0] += 1
            t, ship, point, normal = hits[k]
            combat.apply_hit(ship, t._damage, point,
                             source=t._source_ship, normal=normal,
                             ship_instances=ship_instances,
                             weapon_type="torpedo", hardpoint_weapon=t,
                             shield_point=t._bubble_entry)
            i = k + 1
    finally:
        _h.combat_set_applier(prev)
        # apply_hits' compute is K3's (released and timed with next()'s):
        # into k3.compute, beside the walk's, never the next session's.
        _compute_taken(3)


#: K3 hits run here in Python (_k3_apply_hits' hand-backs).
_k3_hit_python = [0]


if available():
    # step_memo.forget() (every hit, the step's forget points, the outermost
    # block's exit) empties the native memo with the Python tables.
    from engine.core import step_memo as _step_memo
    _step_memo.on_forget(_h.combat_memo_clear)
