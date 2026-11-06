"""Kernel M, the native ship-motion step (native motion phase 2).

The kernel (native/src/combat/src/motion_step.cc) is a bit-exact port of
``ship_motion._step_ship_motion`` (the motion law's acceleration included:
``step_vector_velocity``, ``_no_thrust``; a stored turn goal's steering:
``ShipClass._steer_turn_goal``) and ``drift.step``; it writes the
transform store and the mirror itself, and logs the Python attributes the
step would have written -- an acceleration only when it differs bitwise
from the one the ship holds, so a drifting or immobile row logs nothing
once it holds its zero (its first tick logs that zero, over the ``None``
a new ship starts with). Its two bindings: ``combat_motion_compute``
returns that log (``_apply_writes_py`` below is THE REFERENCE applier),
``combat_motion_step`` applies it by C
(native/src/host/motion_write_apply.cc, store for store the reference's).

THE DRIVER (Task 5). ``ship_motion.tick_all_ship_motion`` calls ``step_all``
while ``enabled()``: the switch (``DAUNTLESS_NATIVE_MOTION``, on unless
``=0``, set by ``configure``), the mirror live, the native transform store,
and the stock snapshot holding. Python stays the authority and the Python
loop the reference.

* The roster is ``iter_non_rock_ships``' own, taken as lazily: the sets as
  the stage begins, each set's objects when the stage reaches it, each
  object's class when its row is reached. Kernel M runs one set at a time,
  in segments, from ``begin``:
    - ``WARP_ROW``: ``warp_flight.step(ship, dt)`` in Python. True: the
      flight owned the tick (``ship_motion._no_thrust``, as
      ``_step_ship_motion``); resume at the next row. False (an "ai" flight
      holding for its parts): resume AT the row, past its warp check
      (``resume_past_warp``), where the kernel's law records the
      acceleration.
    - ``PYTHON_ROW``: ``_step_after_warp`` for the resumed row, else
      ``_step_ship_motion``; resume at the next row. ``TurnGoal``: the row's
      stored turn goal is one the mirror cannot represent
      (native_combat.TurnGoalField); a representable one the kernel steers.
  The player's handle is read before every call. After any Python ran
  (either stop), the rest of the set is re-read from that set's object
  snapshot (class, handle, per-instance scan) and the stage guards are
  checked again, so a handler inside a Python-owned row that deletes,
  retargets or creates a ship, or changes the player, is seen by the later
  rows exactly as the Python loop sees it. Later sets are read when reached.

* Rows the driver itself hands to Python (handle -1, counted "Instance"): an
  instance attribute shadowing a motion method on the ship, its impulse
  engine or a pod (``ship.SetVelocity = f``).

* The whole stage runs Python (``patched_stages``) when the STOCK SNAPSHOT,
  taken at import, differs: the functions kernel M stands in for (and the
  roster's iterators), and the motion METHOD surface as the stock classes
  resolve it (ShipClass's, so a patch on ObjectClass shows too; the impulse
  engine's; the pods'; TGPoint3/TGMatrix3's). A SUBCLASS is watched
  instead (every class with a mirror row, native_combat._k2_seen): when a
  class is first seen, or one of its motion names resolves to something
  else since, the motion class flags of its rows are pushed again, so the
  kernel hands exactly those rows back (NotStock). A patch made after the
  ships registered is therefore seen.

* A RAISE out of ``combat_motion_step`` (anything that is not a stop: a
  bad_alloc mid-walk, the GIL probe's throw, a store the C applier could not
  make) may have left rows the kernel committed -- store and mirror written
  -- without their Python attributes. The rule: every row of that call from
  ``begin`` is resynced from Python (mirror := Python; poses stay where the
  store has them, which is where Python sees them), nothing more runs this
  tick, natively or in Python (no row is ever moved twice), and the
  exception propagates, as a raise in the Python loop does (``raised``).
"""
import operator
import os
from typing import Mapping

import App
from engine.appc import drift, native_combat, ship_death, ship_iter
from engine.appc import ship_motion, subsystems, warp_flight, warp_state
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc import ships as ships_module
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (ImpulseEngineSubsystem, ShipSubsystem,
                                    WarpEngineSubsystem)
from engine.appc.transform_store import NativeTransformStore, get_store
from engine.core import frame_profiler as _prof

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

# MotionResult.stop (motion_step.h MotionStop)
DONE, WARP_ROW, PYTHON_ROW = 0, 1, 2

# MotionResult.reason, by its int (motion_step.h MotionReason)
REASONS = ("None", "NoRow", "NotStock", "Unrepresentable", "FallBack",
           "BadTransform", "TurnGoal")
#: The driver's own reason: an instance attribute shadows a motion method.
INSTANCE = "Instance"

# MotionWrite.what bits (motion_step.h MotionWhat)
K_SPEED, K_ANG_VEL, K_VELOCITY, K_DRIFT_SET, K_DRIFT_CLEAR = 1, 2, 4, 8, 16
K_MOTION_VEL, K_ACCEL, K_STEER = 32, 64, 128

# The compute timer's kernel index (host_bindings.cc compute_kernel).
_KERNEL_M = 5


# ── The reference applier (Task 4) ───────────────────────────────────────────

def _store_speed(ship, speed, _cav, _vel, _drift, _mv, _acc, _sp) -> None:
    ship.__dict__["_current_speed"] = speed


def _store_motion_vel(ship, _speed, _cav, _vel, _drift, mv, _acc,
                      _sp) -> None:
    ship.__dict__["_motion_vel"] = tuple(mv)


def _store_accel(ship, _speed, _cav, _vel, _drift, _mv, acc, _sp) -> None:
    ship.__dict__["_acceleration"] = tuple(acc)


def _store_cav(ship, _speed, cav, _vel, _drift, _mv, _acc, _sp) -> None:
    # In place, on the existing object: Python's step ramps it in place, and
    # anything holding it (host_loop._PlayerControl's seed) must see it.
    c = ship.__dict__["_current_angular_velocity"]
    c.x, c.y, c.z = cav


def _store_velocity(ship, _speed, _cav, vel, _drift, _mv, _acc,
                    _sp) -> None:
    ship.__dict__["_velocity"] = TGPoint3(*vel)


def _store_drift_set(ship, _speed, _cav, _vel, drift, _mv, _acc,
                     _sp) -> None:
    ship.__dict__["_drift_velocity"] = TGPoint3(*drift)


def _store_drift_clear(ship, _speed, _cav, _vel, _drift, _mv, _acc,
                       _sp) -> None:
    ship.__dict__["_drift_velocity"] = None


def _store_steer(ship, _speed, _cav, _vel, _drift, _mv, _acc,
                 setpoint) -> None:
    # ShipClass._steer_turn_goal's three writes: the setpoint, a new point
    # the goal owns (goal[1] is it, so Python's next step steers it too),
    # and the keyboard turn fraction cleared.
    sp = TGPoint3(*setpoint)
    ship.__dict__["_target_angular_velocity_setpoint"] = sp
    ship.__dict__["_target_angular_velocity_fraction"] = None
    ship.__dict__["_turn_goal"][1] = sp


# (bit, store), in the order Python's step writes them -- near enough: Python
# writes `_acceleration` inside step_vector_velocity, before the speed, and
# the steered setpoint after the velocity, as here. The order decides only
# which exception surfaces first when a store raises (every store is
# applied either way); the final state is identical.
_STORES = ((K_DRIFT_CLEAR, _store_drift_clear), (K_DRIFT_SET, _store_drift_set),
           (K_MOTION_VEL, _store_motion_vel), (K_SPEED, _store_speed),
           (K_VELOCITY, _store_velocity), (K_STEER, _store_steer),
           (K_ANG_VEL, _store_cav), (K_ACCEL, _store_accel))
_NO_VALUES = ((0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
_NO_SETPOINT = (0.0, 0.0, 0.0)


def _apply_writes_py(ships, writes) -> None:
    """Store the kernel's writes into the Python objects, THE REFERENCE.

    `writes` is combat_motion_compute's log, [(row, what, speed, (cx, cy,
    cz), (vx, vy, vz), (dx, dy, dz), (mx, my, mz, mspeed), (ax, ay, az),
    (sx, sy, sz)), ...] (a 6-tuple leaves the last three zero, an 8-tuple
    the setpoint); `ships[row]` is the ship. Each store is a quiet
    ``__dict__`` write (no push: the kernel already wrote the mirror, and
    the pose is in the transform store): ``_motion_vel = (mx, my, mz,
    mspeed)``; ``_current_speed``; ``_current_angular_velocity``'s x/y/z
    set in place on its existing object; ``_velocity = TGPoint3(...)``;
    ``_drift_velocity = TGPoint3(...)`` or ``None``; the steered setpoint
    (``_target_angular_velocity_setpoint = sp = TGPoint3(sx, sy, sz)``,
    the fraction ``None``, ``_turn_goal[1] = sp``); ``_acceleration = (ax,
    ay, az)``.

    A RAISE PART-WAY (as native_combat.apply_writes): the kernel has
    already written every value to the mirror, so when one store raises the
    rest are still applied, in order, and the first exception is then
    re-raised -- the Python objects still equal the mirror except for the
    store that raised."""
    first = None
    for entry in writes:
        row, what, speed, cav, vel, drift = entry[:6]
        mv, acc = entry[6:8] if len(entry) >= 8 else _NO_VALUES
        sp = entry[8] if len(entry) == 9 else _NO_SETPOINT
        ship = ships[row]
        for bit, store in _STORES:
            if what & bit:
                try:
                    store(ship, speed, cav, vel, drift, mv, acc, sp)
                except BaseException as e:       # noqa: BLE001 -- re-raised
                    if first is None:
                        first = e
    if first is not None:
        raise first


# ── The switch and the counts ────────────────────────────────────────────────

_switch = False
_counts = {"native_calls": 0, "warp_rows": 0, "patched_stages": 0,
           "raised": 0}
_python_rows: dict = {}


def configure(environ: Mapping[str, str] = os.environ) -> None:
    """The switch from `environ`: DAUNTLESS_NATIVE_MOTION, on unless "0".
    Called by GameLoop.__init__ after native_combat.configure()."""
    global _switch
    _switch = environ.get("DAUNTLESS_NATIVE_MOTION") != "0"


def enabled() -> bool:
    """Kernel M flies the motion stage: the switch is on, the mirror is live
    (native_combat._enabled), the transform store is the native one, and the
    stock snapshot holds (else ``patched_stages`` counts the stage)."""
    if not _switch or not native_combat._enabled or _h is None:
        return False
    if not isinstance(get_store(), NativeTransformStore):
        return False
    if not _stock_holds():
        _note_patched()
        return False
    return True


def _note_patched() -> None:
    """A stage runs in Python because the motion surface is patched: count
    it, and say so once per patched name on stderr."""
    _counts["patched_stages"] += 1
    name = _patched_name()
    native_combat._log_once(
        ("motion-patched", name),
        "kernel M: %s is patched; the motion stage runs in Python while it "
        "is" % name)


def reset() -> None:
    """The switch off, the counts zeroed, the class watch forgotten, kernel
    M's compute timer drained (native_combat.reset calls this)."""
    global _switch
    _switch = False
    for k in _counts:
        _counts[k] = 0
    _python_rows.clear()
    _tick_reset()
    _watch.clear()
    _watch_seen[:] = [0, -1]
    if _h is not None and hasattr(_h, "combat_compute_take"):
        _h.combat_compute_take(_KERNEL_M)


# ── The published-pose buffer (Task 6) ───────────────────────────────────────

_tick = 0


def _tick_reset() -> None:
    global _tick
    _tick = 0
    if _h is not None and hasattr(_h, "combat_motion_published_clear"):
        _h.combat_motion_published_clear()


def publish(handles) -> None:
    """Copy each ship row's pose and ``_velocity`` into the native
    published-pose buffer (published_poses.h), tagged with a per-process
    counter that increments once per call (once per motion stage): NOT the
    GameLoop tick, and not comparable with it. The roster is the non-rock
    ships in set-iteration order, read at publish time. -1, stale handles,
    invalid transforms and a non-TGPoint3 ``_velocity`` are skipped
    natively. It opens the READ WINDOW (close_published). It changes no
    state. Runs on the main thread with the GIL held (one short copy; the
    mirror is not written), so nothing here needs the off-main queue."""
    global _tick
    _tick += 1
    _h.combat_motion_publish(handles, _tick)


def close_published() -> None:
    """Close the published-pose READ WINDOW (phase 4, Task 4;
    published_poses.h) that publish opened: from here until the next
    publish the combat kernels and the gameplay hit pose read the live
    transform store. Called at the top of every ``GameLoop.tick`` (a window
    a driver left open never reaches the AI stage), in a ``finally`` around
    ``host_loop._advance_combat``'s body, and in ``GameLoop.tick`` before
    ``effect_queue.boundary()`` when the loop owns its boundary. So the
    window is [publish, end of _advance_combat]: AI-stage K1 calls, the
    frame-start fire keys, effect handlers, collisions and a headless
    boundary-owning loop's combat read live."""
    if _h is not None:
        _h.combat_motion_published_close()


def publish_stage() -> None:
    """The end of ``ship_motion.tick_all_ship_motion``, in both switch
    states, whenever the mirror is live: publish the roster's ships."""
    if not native_combat._enabled or _h is None:
        return
    handles = []
    for ship in ship_iter.iter_non_rock_ships():
        d = getattr(ship, "__dict__", None)
        h = -1 if d is None else d.get("_nslot", -1)
        handles.append(h if type(h) is int else -1)
    publish(handles)


def counts() -> dict:
    """Since the last reset(): ``native_calls`` (combat_motion_step calls),
    ``warp_rows`` (warp_flight.step run for a warp row), ``python_rows``
    ({reason: rows run in Python}, only reasons that happened),
    ``patched_stages`` (stages run whole in Python: the snapshot differed),
    ``raised`` (combat_motion_step raised: resynced, re-raised)."""
    out = dict(_counts)
    out["python_rows"] = dict(_python_rows)
    return out


# ── The stock snapshot ───────────────────────────────────────────────────────

def _getter(names):
    """A callable giving the tuple of `names` read off its argument."""
    get = operator.attrgetter(*names)
    if len(names) == 1:
        return lambda owner, _g=get: (_g(owner),)
    return get


_SHIP_NAMES = native_combat._MOTION_SHIP_NAMES
_IES_NAMES = native_combat._MOTION_IES_NAMES
_POD_NAMES = native_combat._MOTION_POD_NAMES

#: (owner, names): the functions and constants kernel M stands in for, the
#: roster's iterators, and the method surface as the stock classes resolve
#: it (through their MRO: a patch on ObjectClass shows on ShipClass).
_SURFACE = (
    (ship_motion, ("_step_ship_motion", "_step_after_warp",
                   "_integrate_rotation", "_effective_motion", "_cap_keep",
                   "_ramp_toward", "step_vector_velocity",
                   "law_step_vector", "_no_thrust", "impulse_fractions",
                   "impulse_output_fraction", "FALLBACK_MAX_ACCEL",
                   "BC_IMPULSE_TAU")),
    (drift, ("step",)),
    (warp_state, ("is_arriving",)),
    (subsystems, ("_is_offline",)),
    (ship_death, ("_out_of_action",)),
    (ship_iter, ("iter_ships", "iter_non_rock_ships", "iter_set_objects")),
    # The steering's methods (_steer_turn_goal, _turn_goal_vectors,
    # _turn_rotation, GetWorldLocation) are among _SHIP_NAMES, so a
    # subclass or an instance overriding one is seen too (_ROLES,
    # _overridden); its module functions are ships_module's below.
    (ShipClass, _SHIP_NAMES),
    (ImpulseEngineSubsystem, _IES_NAMES),
    (ShipSubsystem, _POD_NAMES),
    (WarpEngineSubsystem, ("is_dewarp_driving",)),
    (ships_module, ("_frame_rotation", "_to_body")),
    (TGMatrix3, ("MakeRotation", "MultMatrix", "GetCol")),
    (TGPoint3, ("MultMatrixLeft", "Unitize", "Length", "Cross", "Dot",
                "Scale")),
)


def _take_snapshot() -> list:
    out = []
    for owner, names in _SURFACE:
        get = _getter(names)
        out.append((owner, get, get(owner)))
    return out


#: Taken at import, before any test, tool or mod can replace a name.
_SNAPSHOT = _take_snapshot()


def _stock_holds() -> bool:
    """Every name of the surface is what it was at import. A tuple compare:
    identity first, and a function equals only itself."""
    for owner, get, values in _SNAPSHOT:
        try:
            if get(owner) != values:
                return False
        except AttributeError:              # a name was deleted
            return False
    return True


def _patched_name() -> str:
    """The first surface name that is not what it was at import."""
    for owner, _get, values in _SNAPSHOT:
        names = next(n for o, n in _SURFACE if o is owner)
        for name, value in zip(names, values):
            if getattr(owner, name, _GONE) is not value:
                return "%s.%s" % (getattr(owner, "__name__", owner), name)
    return "?"


# ── The class watch: subclasses of the motion roles ──────────────────────────

#: (role base, its names, their getter, the class flags it decides)
_ROLES = (
    (ShipClass, native_combat._MOTION_SHIP_NAMES,
     _getter(native_combat._MOTION_SHIP_NAMES)),
    (ImpulseEngineSubsystem, _IES_NAMES, _getter(_IES_NAMES)),
    (ShipSubsystem, _POD_NAMES, _getter(_POD_NAMES)),
)
#: [cls, getter, the resolution its rows' flags were last pushed from]
_watch: list = []
#: [len(native_combat._k2_seen) watched, native_combat._seen_gen it was]
_watch_seen = [0, -1]
_GONE = object()


def _resolve(get, cls):
    try:
        return get(cls)
    except AttributeError:
        return _GONE


def _watch_classes() -> None:
    """Classes first seen, or whose motion names resolve to something else
    since their rows' flags were pushed: push those flags again (the
    kernel then hands exactly their rows back)."""
    seen = native_combat._k2_seen
    n = len(seen)
    fresh = set()
    start = _watch_seen[0]
    gen = native_combat._seen_gen
    if gen != _watch_seen[1] or n < start:
        _watch.clear()          # the seen list was rebuilt (forget_rows)
        start = 0
    for cls in seen[start:n]:
        for base, _names, get in _ROLES:
            if cls is not base and issubclass(cls, base):
                _watch.append([cls, get, _resolve(get, cls)])
                fresh.add(cls)
    _watch_seen[:] = [n, gen]
    for entry in _watch:
        now = _resolve(entry[1], entry[0])
        if now != entry[2]:
            entry[2] = now
            fresh.add(entry[0])
    if fresh:
        _repush_motion_flags(fresh)


def _repush_motion_flags(classes) -> None:
    """The motion class flags of every live row whose object's class is in
    `classes`, pushed as native_combat._flags computes them."""
    nc = native_combat
    obj_kind, sub_kind = nc._kind("Object"), nc._kind("Subsystem")
    set_i = _h.combat_set_i
    for h, obj in list(nc._registry.items()):
        if type(obj) not in classes or obj.__dict__.get("_nslot") != h:
            continue
        cls = type(obj)
        k = h >> nc._KIND_SHIFT
        if k == obj_kind:
            nc._call(obj, set_i, h, nc._fid("motion_stock"),
                     nc._stock_surface(cls, ShipClass,
                                       nc._MOTION_SHIP_NAMES))
        elif k == sub_kind:
            nc._call(obj, set_i, h, nc._fid("motion_ies_stock"),
                     nc._stock_surface(cls, ImpulseEngineSubsystem,
                                       _IES_NAMES))
            if obj.__dict__.get("_nslot") == h:
                nc._call(obj, set_i, h, nc._fid("motion_pod_stock"),
                         nc._stock_surface(cls, ShipSubsystem, _POD_NAMES))


# ── The roster ───────────────────────────────────────────────────────────────

_ROCK = []


def _rock_class():
    if not _ROCK:
        from engine.rocks.rock import RockClass
        _ROCK.append(RockClass)
    return _ROCK[0]


def _sets_now() -> list:
    """The sets, as iter_ships takes them when the stage begins."""
    return [pSet for _name, pSet in list(App.g_kSetManager._sets.items())]


def _set_objects(pSet) -> list:
    """One set's objects, as iter_set_objects takes them when reached."""
    return list(getattr(pSet, "_objects", {}).values())


def _is_motion_ship(obj, rock) -> bool:
    return isinstance(obj, ShipClass) and not isinstance(obj, rock)


def _ships_of(objs) -> list:
    rock = _rock_class()
    return [o for o in objs if _is_motion_ship(o, rock)]


_SHIP_SET = frozenset(_SHIP_NAMES)
_IES_SET = frozenset(_IES_NAMES)
_POD_SET = frozenset(_POD_NAMES)
#: warp_state.is_arriving's last call, as WarpEngineSubsystem resolves it
#: (the snapshot holds it too: a patch of the base sends the stage).
_DEWARP = "is_dewarp_driving"
_STOCK_DEWARP = WarpEngineSubsystem.is_dewarp_driving


def _overridden(d) -> bool:
    """The row's motion surface is not stock where the class flags cannot
    see it: an instance attribute shadowing a motion method on the ship (its
    __dict__ `d`), its impulse engine or one of the engine's pods; or a warp
    engine whose ``is_dewarp_driving`` (warp_state.is_arriving's question,
    which the kernel answers from the row's `arriving`) is not the stock one,
    by its class or by an instance attribute."""
    if not d.keys().isdisjoint(_SHIP_SET):
        return True
    we = d.get("_warp_engine_subsystem")
    if we is not None:
        t = type(we)
        if t is not WarpEngineSubsystem and \
                getattr(t, _DEWARP, None) is not _STOCK_DEWARP:
            return True
        wd = getattr(we, "__dict__", None)
        if wd is not None and _DEWARP in wd:
            return True
    ies = d.get("_impulse_engine_subsystem")
    if ies is None:
        return False
    idd = getattr(ies, "__dict__", None)
    if idd is None:
        return False
    if not idd.keys().isdisjoint(_IES_SET):
        return True
    for pod in idd.get("_children", ()):
        pdd = getattr(pod, "__dict__", None)
        if pdd is not None and not pdd.keys().isdisjoint(_POD_SET):
            return True
    return False


def _handle(ship, i, forced) -> int:
    d = ship.__dict__
    h = d.get("_nslot", -1)
    if type(h) is not int:
        return -1
    if h != -1 and _overridden(d):
        forced.add(i)
        return -1
    return h


def _player_handle() -> int:
    p = App.Game_GetCurrentPlayer()
    if p is None:
        return -1
    d = getattr(p, "__dict__", None)
    h = -1 if d is None else d.get("_nslot", -1)
    return h if type(h) is int else -1


# ── The stage ────────────────────────────────────────────────────────────────

def step_all(dt: float) -> None:
    """One motion stage by kernel M (module docstring)."""
    try:
        with _prof.scope("motion.prep"):
            _watch_classes()
            sets = _sets_now()
        for k, pSet in enumerate(sets):
            if not _step_set(_set_objects(pSet), dt):
                # The surface changed mid-stage: the rest is Python's.
                for later in sets[k + 1:]:
                    _python_rest(_set_objects(later), 0, dt)
                return
    finally:
        ms, n = _h.combat_compute_take(_KERNEL_M)
        if n and _prof._enabled:
            where = _prof.open_scope()
            _prof.record("motion.kernel" if where == "gl.motion"
                         else "motion.kernel@%s" % where, ms, n)


def _step_set(objs, dt) -> bool:
    """One set's rows. False: the stock surface changed while a Python row
    ran; the rest of this set has been run in Python, and so must the rest
    of the stage be."""
    rock = _rock_class()
    pos = [i for i, o in enumerate(objs) if _is_motion_ship(o, rock)]
    if not pos:
        return True
    ships = [objs[i] for i in pos]
    forced: set = set()
    with _prof.scope("motion.prep"):
        handles = [_handle(s, i, forced) for i, s in enumerate(ships)]
    begin, resume = 0, False
    step = _h.combat_motion_step
    while True:
        try:
            # Includes the kernel's compute (motion.kernel) and the C
            # write-back into each ship's __dict__.
            with _prof.scope("motion.step"):
                stop, at, reason = step(ships, handles, _player_handle(), dt,
                                        begin, resume)
        except BaseException:
            _counts["raised"] += 1
            _resync(ships[begin:])
            raise
        _counts["native_calls"] += 1
        if stop == DONE:
            return True
        ship = ships[at]
        if stop == WARP_ROW:
            _counts["warp_rows"] += 1
            if warp_flight.step(ship, dt):
                ship_motion._no_thrust(ship)
                begin, resume = at + 1, False
            else:
                begin, resume = at, True
        else:
            why = INSTANCE if at in forced else REASONS[reason]
            _python_rows[why] = _python_rows.get(why, 0) + 1
            if resume and at == begin:
                ship_motion._step_after_warp(ship, dt)
            else:
                ship_motion._step_ship_motion(ship, dt)
            begin, resume = at + 1, False
        # Python ran: what it may have changed is read again -- the stock
        # surface, the classes, and the rest of this set from its object
        # snapshot (each object's class, handle and instance attributes).
        if not _stock_holds():
            _note_patched()
            if resume:
                ship_motion._step_after_warp(ship, dt)
            _python_rest(objs, pos[at] + 1, dt)
            return False
        _watch_classes()
        keep = at + 1           # rows [0, keep) stay; the resumed row too
        tail = [i for i in range(pos[at] + 1, len(objs))
                if _is_motion_ship(objs[i], rock)]
        del ships[keep:], pos[keep:], handles[keep:]
        ships.extend(objs[i] for i in tail)
        pos.extend(tail)
        forced = {i for i in forced if i < at}
        if resume:
            handles[at] = _handle(ship, at, forced)
        handles.extend(_handle(ships[i], i, forced)
                       for i in range(keep, len(ships)))


def _python_rest(objs, start, dt) -> None:
    """objs[start:] run as the Python loop runs them: each object's class
    tested when its turn comes."""
    rock = _rock_class()
    for i in range(start, len(objs)):
        if _is_motion_ship(objs[i], rock):
            ship_motion._step_ship_motion(objs[i], dt)


def _resync(ships) -> None:
    """Every row of `ships` pushed again from its Python object (a raise out
    of combat_motion_step: module docstring)."""
    nc = native_combat
    for ship in ships:
        h = ship.__dict__.get("_nslot")
        if h is None or nc._registry.get(h) is not ship:
            continue
        try:
            nc._push_all(ship, h)
        except Exception as e:      # noqa: BLE001 -- the raise in flight wins
            nc._log_once(("motion-resync", type(e)),
                         "native motion: a resync after a kernel raise "
                         "raised %r" % (e,))
