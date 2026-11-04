"""Kernel M, the native ship-motion step (native motion phase 2).

Task 4 part: the kernel's result codes and THE REFERENCE applier for its
write log. The kernel (native/src/combat/src/motion_step.cc, binding
``combat_motion_compute``) is a bit-exact port of
``ship_motion._step_ship_motion`` and ``drift.step``; it writes the
transform store and the mirror itself, and logs the Python attributes the
step would have written, which ``_apply_writes_py`` stores quietly (no
push: the mirror already holds them). Not wired into the game loop yet.
"""
from engine.appc.math import TGPoint3

# MotionResult.stop (motion_step.h MotionStop)
DONE, WARP_ROW, PYTHON_ROW = 0, 1, 2

# MotionResult.reason, by its int (motion_step.h MotionReason)
REASONS = ("None", "NoRow", "NotStock", "Unrepresentable", "FallBack",
           "BadTransform")

# MotionWrite.what bits (motion_step.h MotionWhat)
K_SPEED, K_ANG_VEL, K_VELOCITY, K_DRIFT_SET, K_DRIFT_CLEAR = 1, 2, 4, 8, 16


def _store_speed(ship, speed, _cav, _vel, _drift) -> None:
    ship.__dict__["_current_speed"] = speed


def _store_cav(ship, _speed, cav, _vel, _drift) -> None:
    # In place, on the existing object: Python's step ramps it in place, and
    # anything holding it (host_loop._PlayerControl's seed) must see it.
    c = ship.__dict__["_current_angular_velocity"]
    c.x, c.y, c.z = cav


def _store_velocity(ship, _speed, _cav, vel, _drift) -> None:
    ship.__dict__["_velocity"] = TGPoint3(*vel)


def _store_drift_set(ship, _speed, _cav, _vel, drift) -> None:
    ship.__dict__["_drift_velocity"] = TGPoint3(*drift)


def _store_drift_clear(ship, _speed, _cav, _vel, _drift) -> None:
    ship.__dict__["_drift_velocity"] = None


# (bit, store), in the order Python's step writes them.
_STORES = ((K_DRIFT_CLEAR, _store_drift_clear), (K_DRIFT_SET, _store_drift_set),
           (K_SPEED, _store_speed), (K_VELOCITY, _store_velocity),
           (K_ANG_VEL, _store_cav))


def _apply_writes_py(ships, writes) -> None:
    """Store the kernel's writes into the Python objects, THE REFERENCE.

    `writes` is combat_motion_compute's log, [(row, what, speed, (cx, cy,
    cz), (vx, vy, vz), (dx, dy, dz)), ...]; `ships[row]` is the ship. Each
    store is a quiet ``__dict__`` write (no push: the kernel already wrote
    the mirror, and the pose is in the transform store):
    ``_current_speed``; ``_current_angular_velocity``'s x/y/z set in place
    on its existing object; ``_velocity = TGPoint3(...)``;
    ``_drift_velocity = TGPoint3(...)`` or ``None``.

    A RAISE PART-WAY (as native_combat.apply_writes): the kernel has
    already written every value to the mirror, so when one store raises the
    rest are still applied, in order, and the first exception is then
    re-raised -- the Python objects still equal the mirror except for the
    store that raised."""
    first = None
    for row, what, speed, cav, vel, drift in writes:
        ship = ships[row]
        for bit, store in _STORES:
            if what & bit:
                try:
                    store(ship, speed, cav, vel, drift)
                except BaseException as e:       # noqa: BLE001 -- re-raised
                    if first is None:
                        first = e
    if first is not None:
        raise first
