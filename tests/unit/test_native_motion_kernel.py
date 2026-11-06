"""Kernel M (native motion phase 2, Task 4) against Python's
``ship_motion._step_ship_motion`` (the law's acceleration included), one
branch per test.

Each differential takes a snapshot of the ships (pose, `_current_speed`,
`_current_angular_velocity`'s components, `_velocity`, `_drift_velocity`,
the motion law's `_motion_vel` and its commanded `_acceleration`),
runs the kernel through its binding (``combat_motion_compute``) and the
reference applier (``native_motion._apply_writes_py``), reads the result,
restores the snapshot through the real setters (so the mirror is restored
too), runs the Python step, and compares. Every float compares by
``float.hex()``, never a tolerance: a mismatch is a bug in the port. Which
attributes were REBOUND (a new `_velocity` / `_drift_velocity` object) is
compared too, and `_current_angular_velocity` must keep its object.

The kernel is not wired into the game loop yet (Task 5), so these call the
binding directly.
"""
import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_register"),
    reason="native combat bindings not built")

from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import native_motion as nm  # noqa: E402
from engine.appc import ship_motion  # noqa: E402
from engine.appc import warp_flight  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.appc.ships import ShipClass  # noqa: E402
from engine.appc.subsystems import (  # noqa: E402
    ImpulseEngineSubsystem, ShipSubsystem, WarpEngineSubsystem,
)
from engine.core.game import Game, _set_current_game  # noqa: E402

DT = 1.0 / 60.0
MODEL, WORLD = 0, 1
NAN = float("nan")


@pytest.fixture(autouse=True)
def _switch():
    _set_current_game(None)
    nc.reset()
    nc.configure({})
    assert nc.enabled()
    yield
    nc.reset()
    _set_current_game(None)


# ── Building ships ───────────────────────────────────────────────────────────

def _slot(obj):
    return obj.__dict__["_nslot"]


def _rotate(ship, angle=0.7, axis=(0.267, 0.534, 0.801)):
    R = TGMatrix3()
    R.MakeRotation(angle, TGPoint3(*axis))
    ship.SetMatrixRotation(R)


def _ship(name="Ship", pods=2, max_speed=6.3, accel=1.7, ang=0.31,
          ang_accel=0.11, on=True, slider=1.0):
    """A ShipClass with a healthy impulse engine of `pods` pods, rotated
    off the identity and placed just off the origin: a position of the
    same magnitude as a tick's step, so the step's last bits survive the
    add (at 10 GU they would round away and hide a mis-ordered product)."""
    ship = App.ShipClass_Create(name)
    ies = ImpulseEngineSubsystem("Impulse")
    ship.SetImpulseEngineSubsystem(ies)
    ies._max_condition = 100.0
    ies._condition = 100.0
    ies._disabled_percentage = 0.25
    ies.SetMaxSpeed(max_speed)
    ies.SetMaxAccel(accel)
    ies.SetMaxAngularVelocity(ang)
    ies.SetMaxAngularAccel(ang_accel)
    if on:
        ies.TurnOn()
    else:
        ies.TurnOff()
    ies.SetPowerPercentageWanted(slider)
    for i in range(pods):
        pod = ShipSubsystem("Pod%d" % i)
        pod._max_condition = 100.0
        pod._condition = 100.0
        pod._disabled_percentage = 0.25
        ies.AddChildSubsystem(pod)
    ship.SetTranslateXYZ(0.01, -0.02, 0.005)
    _rotate(ship)
    return ship, ies


def _kill_pods(ies):
    for i in range(ies.GetNumChildSubsystems()):
        ies.GetChildSubsystem(i)._condition = 0.0


# ── Snapshot, state, the two runs ────────────────────────────────────────────

def _hx(v):
    return float(v).hex()


def _vec(p):
    if p is None:
        return None
    if isinstance(p, TGPoint3):
        return (_hx(p.x), _hx(p.y), _hx(p.z))
    return ("unrepresentable", repr(p))


def _state(ship):
    d = ship.__dict__
    p = ship.GetTranslate()
    return {
        "pos": (_hx(p.x), _hx(p.y), _hx(p.z)),
        "rot": tuple(_hx(v) for v in ship.GetWorldRotation().as_tuple()),
        "_current_speed": _hx(d["_current_speed"]),
        "_current_angular_velocity": _vec(d["_current_angular_velocity"]),
        "_velocity": _vec(d["_velocity"]),
        "has_drift": "_drift_velocity" in d,
        "_drift_velocity": _vec(d.get("_drift_velocity")),
        "_motion_vel": _floats(d.get("_motion_vel")),
        "_acceleration": _floats(d.get("_acceleration")),
        "_target_angular_velocity_setpoint": _vec(
            d.get("_target_angular_velocity_setpoint")),
        "_target_angular_velocity_fraction": _vec(
            d.get("_target_angular_velocity_fraction")),
        "goal_owns_setpoint": _goal_owns(d),
    }


def _goal_owns(d):
    """`goal[1] is av`: the stored turn goal still owns the setpoint (it
    steers it), or None with no goal."""
    goal = d.get("_turn_goal")
    if goal is None:
        return None
    return goal[1] is d.get("_target_angular_velocity_setpoint")


def _floats(t):
    return None if t is None else tuple(_hx(v) for v in t)


class _Snap:
    """A ship's motion state, restorable through the real setters (each
    pushes, so the mirror is restored with it)."""

    def __init__(self, ship):
        d = ship.__dict__
        self.ship = ship
        p = ship.GetTranslate()
        self.pos = (p.x, p.y, p.z)
        self.rot = ship.GetWorldRotation()
        self.speed = d["_current_speed"]
        self.cav = d["_current_angular_velocity"]
        self.cav_xyz = ((self.cav.x, self.cav.y, self.cav.z)
                        if isinstance(self.cav, TGPoint3) else None)
        self.vel = d["_velocity"]
        self.has_drift = "_drift_velocity" in d
        self.drift = d.get("_drift_velocity")
        self.motion_vel = d.get("_motion_vel")
        self.has_accel = "_acceleration" in d
        self.accel = d.get("_acceleration")
        self.av = d.get("_target_angular_velocity_setpoint")
        self.frac = d.get("_target_angular_velocity_fraction")
        self.goal = d.get("_turn_goal")
        self.goal_owner = None if self.goal is None else self.goal[1]
        self.state = _state(ship)

    def objects(self):
        d = self.ship.__dict__
        return (d["_current_angular_velocity"] is self.cav,
                d["_velocity"] is self.vel,
                d.get("_drift_velocity") is self.drift,
                d.get("_target_angular_velocity_setpoint") is self.av)

    def restore(self):
        s = self.ship
        s.SetTranslateXYZ(*self.pos)
        s.SetMatrixRotation(self.rot)
        s._current_speed = self.speed
        if self.cav_xyz is not None:
            self.cav.x, self.cav.y, self.cav.z = self.cav_xyz
        s._current_angular_velocity = self.cav
        s._velocity = self.vel
        if self.has_drift:
            s._drift_velocity = self.drift
        elif "_drift_velocity" in s.__dict__:
            del s._drift_velocity
        s._motion_vel = self.motion_vel
        if self.has_accel:
            s._acceleration = self.accel
        else:
            s.__dict__.pop("_acceleration", None)
        # The goal list itself is the same object; its owned setpoint is
        # put back in place (a steer rebinds only goal[1]).
        s._target_angular_velocity_setpoint = self.av
        s._target_angular_velocity_fraction = self.frac
        if self.goal is not None:
            self.goal[1] = self.goal_owner
        s._turn_goal = self.goal
        assert _state(s) == self.state


def _native(ships, player=None, dt=DT, begin=0, resume=False):
    handles = [_slot(s) for s in ships]
    ph = -1 if player is None else _slot(player)
    stop, at, reason, writes = _h.combat_motion_compute(
        handles, ph, dt, begin, resume)
    nm._apply_writes_py(ships, writes)
    return stop, at, nm.REASONS[reason], writes


def _assert_mirror(ship):
    """The row agrees with the Python attributes the kernel writes (a
    value the mirror cannot represent dumps as four zeros)."""
    row = _h.combat_dump(_slot(ship))
    d = ship.__dict__
    assert _hx(row["_current_speed"]) == _hx(d["_current_speed"])
    want_mv = d.get("_motion_vel")
    assert [_hx(v) for v in row["_motion_vel"]] == (
        [] if want_mv is None else [_hx(v) for v in want_mv])
    want_acc = d.get("_acceleration")
    assert [_hx(v) for v in row["_acceleration"]] == (
        [] if want_acc is None else [_hx(v) for v in want_acc])
    goal = [_hx(v) for v in row["_turn_goal"]]
    assert goal == [_hx(v) for v in vars(ShipClass)["_turn_goal"]._encode(
        d.get("_turn_goal"))]
    for name in ("_current_angular_velocity", "_velocity",
                 "_drift_velocity", "_target_angular_velocity_setpoint",
                 "_target_angular_velocity_fraction"):
        got = row[name]
        got = None if got is None else tuple(_hx(v) for v in got)
        want = d.get(name)
        if want is None or isinstance(want, TGPoint3):
            want = _vec(want)
        else:
            want = (_hx(0.0),) * 4
        assert got == want, name


def _differential(ships, ticks=1, player=None, dt=DT, begin=0, resume=False,
                  python=None):
    """Run the kernel and the Python step from the same snapshot for
    `ticks` ticks (continuing from the Python result, which equals the
    kernel's) and compare. Returns the kernel's writes per tick."""
    python = python or ship_motion._step_ship_motion
    log = []
    for t in range(ticks):
        snaps = [_Snap(s) for s in ships]
        stop, at, reason, writes = _native(ships, player, dt, begin, resume)
        assert (stop, at, reason) == (nm.DONE, len(ships), "None"), t
        got = [(_state(s), sn.objects()) for s, sn in zip(ships, snaps)]
        for s in ships:
            _assert_mirror(s)
        for sn in reversed(snaps):
            sn.restore()
        for s in ships[begin:]:
            python(s, dt)
        want = [(_state(s), sn.objects()) for s, sn in zip(ships, snaps)]
        assert got == want, "tick %d" % t
        log.append(writes)
    return log


def _motion(ship):
    """_state without the acceleration: what a row the kernel passes over
    keeps (it still records a zero acceleration, _no_thrust)."""
    st = _state(ship)
    del st["_acceleration"]
    return st


def _kinds(log):
    """Each tick's writes as their `what` bits."""
    return [[w[1] for w in writes] for writes in log]


def _moved(before, ship):
    now = _state(ship)
    return now["pos"] != before["pos"], now["rot"] != before["rot"]


# ── Powered flight ───────────────────────────────────────────────────────────

def test_powered_ramp_model_space():
    ship, _ies = _ship()
    ship.SetSpeed(5.0, TGPoint3(0.3, 1.0, -0.2), MODEL)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.05, -0.1, 0.2))
    before = _state(ship)
    _differential([ship], ticks=40)
    assert _moved(before, ship) == (True, True)


def test_powered_ramp_world_space():
    ship, _ies = _ship()
    ship.SetSpeed(4.0, TGPoint3(1.0, 2.0, -0.5), WORLD)
    ship.SetTargetAngularVelocityDirect(TGPoint3(-0.07, 0.02, 0.11))
    before = _state(ship)
    _differential([ship], ticks=40)
    assert _moved(before, ship) == (True, True)


def test_cap_keep_does_not_brake():
    ship, _ies = _ship()
    ship._current_speed = 9.0           # above max 6.3
    ship.SetSpeed(12.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    _differential([ship], ticks=5)
    assert ship._current_speed == 9.0


def test_reverse():
    ship, _ies = _ship()
    ship.SetSpeed(-3.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    _differential([ship], ticks=30)
    assert ship._current_speed < 0.0


def test_switched_off_engine_snaps_down():
    ship, ies = _ship()
    ship._current_speed = 4.0
    ies.TurnOff()
    ship.SetSpeed(2.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    # Output 0: the cap keeps 4.0 (it does not brake), the commanded 2.0
    # is under it, and the zeroed accel falls back to FALLBACK_MAX_ACCEL,
    # so the closure rate alone brings the speed down toward 2.0.
    _differential([ship], ticks=3)
    assert 2.0 < ship._current_speed < 4.0


def test_angular_caps():
    ship, _ies = _ship()
    ship.SetSpeed(1.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship.SetTargetAngularVelocityDirect(TGPoint3(1.0, -2.0, 3.0))
    # Each axis capped at 0.31; the law then closes the rate vector's gap
    # at 0.11/s, then with tau = 1 s: within 1e-6 after 20 s.
    _differential([ship], ticks=1200)
    cav = ship._current_angular_velocity
    for got, want in zip((cav.x, cav.y, cav.z), (0.31, -0.31, 0.31)):
        assert abs(got - want) < 1e-6


# ── The motion law ───────────────────────────────────────────────────────────

def test_turning_at_speed_the_course_lags_the_nose():
    """The law on the velocity vector: turning at speed, the velocity trails
    the nose and the speed bleeds; the acceleration has a sideways part."""
    ship, _ies = _ship()
    ship.SetSpeed(6.3, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship._current_speed = 6.3
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.31))
    log = _differential([ship], ticks=240)
    assert all(w[1] & nm.K_MOTION_VEL for writes in log for w in writes)
    nose = ship.GetWorldRotation().GetCol(1)
    v = ship._velocity
    along = v.x * nose.x + v.y * nose.y + v.z * nose.z
    assert along < v.Length() - 1e-6            # off the nose
    assert ship._current_speed < 6.3            # the speed bled
    ax, ay, az = ship._acceleration
    assert (ax * ax + ay * ay + az * az) > 0.0


def test_a_set_speed_reseeds_the_vector():
    ship, _ies = _ship()
    ship.SetSpeed(5.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.2))
    _differential([ship], ticks=30)
    ship._current_speed = 2.0       # someone set the speed directly
    _differential([ship], ticks=30)


def test_keyboard_turn_fraction_of_the_live_rate():
    ship, ies = _ship(slider=0.8)
    ship.SetSpeed(3.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship.SetTargetAngularVelocityFraction(TGPoint3(0.707, 0.0, -0.707))
    assert _h.combat_dump(_slot(ship))[
        "_target_angular_velocity_fraction_state"] == 1
    _differential([ship], ticks=60)
    cav = ship._current_angular_velocity
    assert cav.x > 0.0 > cav.z


def _steering(ship):
    """The kernel steers this row's goal: every tick logs K_STEER."""
    return ship.__dict__["_turn_goal"][1] is \
        ship.__dict__["_target_angular_velocity_setpoint"]


def test_a_loc_goal_is_steered_natively():
    """A stored TurnTowardLocation goal is the kernel's (kernel M ports
    ShipClass._steer_turn_goal): each tick re-plans the setpoint, written
    as K_STEER, bit-exact with Python's step -- at speed, so the direction
    to the point is re-taken from the moved ship."""
    ship, _ies = _ship()
    ship.SetSpeed(3.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship.TurnTowardLocation(TGPoint3(100.0, 0.0, 0.0))
    assert _h.combat_dump(_slot(ship))["_turn_goal"] == [1.0, 100.0, 0.0,
                                                         0.0]
    log = _differential([ship], ticks=240)
    assert all(w[1] & nm.K_STEER for writes in log for w in writes)
    assert _steering(ship)
    # Another angular command ends the goal: no more K_STEER.
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.1))
    assert _h.combat_dump(_slot(ship))["_turn_goal"] == []
    log = _differential([ship], ticks=3)
    assert not any(w[1] & nm.K_STEER for writes in log for w in writes)


def test_an_about_face_is_steered_natively():
    """A point exactly astern: the collinear-opposite branch turns about
    the ship's own up."""
    ship, _ies = _ship()
    R = ship.GetWorldRotation()
    f, p = R.GetCol(1), ship.GetWorldLocation()
    ship.SetSpeed(0.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship.TurnTowardLocation(TGPoint3(p.x - 50.0 * f.x, p.y - 50.0 * f.y,
                                     p.z - 50.0 * f.z))
    log = _differential([ship], ticks=120)
    assert all(w[1] & nm.K_STEER for writes in log for w in writes)


def test_dirs_goals_are_steered_natively():
    """TurnDirectionsToDirections without and with secondaries (the
    TurnTowardOrientation roll constraint, and TurnTowardDirection's zero
    secondaries), and the bare ship's no-accel branch."""
    cases = (
        lambda s: s.TurnDirectionsToDirections(
            TGPoint3(0.0, 1.0, 0.0), TGPoint3(0.3, -0.2, 0.9)),
        lambda s: s.TurnTowardOrientation(TGPoint3(-0.6, 0.7, 0.1),
                                          TGPoint3(0.1, 0.0, 1.0)),
        lambda s: s.TurnTowardDirection(TGPoint3(1.0, 1.0, -1.0)),
        lambda s: s.TurnDirectionsToDirections(
            TGPoint3(1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0),
            TGPoint3(0.0, 1.0, 0.0), TGPoint3(-1.0, 0.0, 0.0)),
    )
    for k, turn in enumerate(cases):
        ship, _ies = _ship("Dirs%d" % k)
        ship.SetSpeed(2.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
        turn(ship)
        assert _h.combat_dump(_slot(ship))["_turn_goal"][0] == 2.0, k
        log = _differential([ship], ticks=150)
        assert all(w[1] & nm.K_STEER for writes in log for w in writes), k
    bare = App.ShipClass_Create("Bare")
    bare.SetTranslateXYZ(0.01, -0.02, 0.005)
    _rotate(bare)
    bare.TurnTowardOrientation(TGPoint3(-0.6, 0.7, 0.1),
                               TGPoint3(0.1, 0.0, 1.0))
    _differential([bare], ticks=20)


def test_a_half_turn_frame_is_steered_natively():
    """TurnTowardOrientation onto the frame turned 180 degrees about the
    ship's up: _frame_rotation's angle-pi branch (the axis from the
    symmetric part), then the turn as it eases off pi."""
    ship, _ies = _ship()
    # An orthonormal rotation (a unit axis), so the goal frame is the
    # half turn to rounding: _ship's own axis is not quite unit.
    axis = TGPoint3(0.267, 0.534, 0.801)
    axis.Unitize()
    _rotate(ship, 0.7, (axis.x, axis.y, axis.z))
    R = ship.GetWorldRotation()
    f, u = R.GetCol(1), R.GetCol(2)
    ship.TurnTowardOrientation(TGPoint3(-f.x, -f.y, -f.z), u)
    log = _differential([ship], ticks=60)
    assert all(w[1] & nm.K_STEER for writes in log for w in writes)


def test_patched_steering_hands_back(monkeypatch):
    """A patch of the steering the kernel stands in for: the stage runs
    Python, so the patch is called for the steering row, and every row is
    Python's."""
    saved = dict(App.g_kSetManager._sets)
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create()
    pSet.SetName("Steer")
    App.g_kSetManager._sets["Steer"] = pSet
    try:
        ship, _ies = _ship("Steerer")
        other, _ = _ship("Other")
        pSet.AddObjectToSet(ship, "Steerer")
        pSet.AddObjectToSet(other, "Other")
        ship.SetSpeed(3.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
        other.SetSpeed(3.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
        ship.TurnTowardLocation(TGPoint3(100.0, 0.0, 0.0))
        nm.reset()
        nm.configure({})
        real = ShipClass._steer_turn_goal
        calls = []

        def wrapper(self, dt, max_aa):
            calls.append(self.GetName())
            return real(self, dt, max_aa)

        monkeypatch.setattr(ShipClass, "_steer_turn_goal", wrapper)
        for _ in range(3):
            ship_motion.tick_all_ship_motion(DT)
        assert calls == ["Steerer"] * 3
        counts = nm.counts()
        assert counts["patched_stages"] == 3, counts
        assert counts["native_calls"] == 0, counts
    finally:
        App.g_kSetManager._sets.clear()
        App.g_kSetManager._sets.update(saved)


def test_unrepresentable_goal_hands_back():
    """A goal the mirror cannot represent is Python's (TurnGoal), with
    nothing written."""
    ship, _ies = _ship()
    ship.SetSpeed(3.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.1))
    ship._turn_goal = [("loc", "not a point"), None]
    assert _h.combat_dump(_slot(ship))["_turn_goal"] == [0.0]
    before = _state(ship)
    row = _h.combat_dump(_slot(ship))
    assert _native([ship]) == (nm.PYTHON_ROW, 0, "TurnGoal", [])
    assert _state(ship) == before
    assert _h.combat_dump(_slot(ship)) == row


def test_a_turn_goal_without_a_setpoint_is_flown():
    """`steering` needs a setpoint: with it cleared the goal cannot own it,
    and the row is the kernel's."""
    ship, _ies = _ship()
    ship.SetSpeed(3.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship.TurnTowardLocation(TGPoint3(100.0, 0.0, 0.0))
    ship._target_angular_velocity_setpoint = None
    _differential([ship], ticks=3)


def test_unrepresentable_acceleration_is_pythons():
    """A held `_acceleration` the mirror cannot represent (ints, a list):
    the kernel cannot tell whether Python's write would change it, so the
    row is Python's."""
    for odd in ((1, 2, 3), [0.0, 0.0, 0.0]):
        ship, _ies = _ship()
        ship.SetSpeed(3.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
        ship._acceleration = odd
        assert len(_h.combat_dump(_slot(ship))["_acceleration"]) == 4
        assert _native([ship]) == (nm.PYTHON_ROW, 0, "Unrepresentable", [])
        ship_motion._step_ship_motion(ship, DT)
        assert type(ship._acceleration) is tuple
        _differential([ship], ticks=2)


def test_unrepresentable_motion_vel_is_pythons():
    ship, _ies = _ship()
    ship.SetSpeed(3.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship._motion_vel = (1, 2, 3, 4)            # ints: not the kernel's
    assert len(_h.combat_dump(_slot(ship))["_motion_vel"]) == 5
    assert _native([ship]) == (nm.PYTHON_ROW, 0, "Unrepresentable", [])


# ── Every pod out: inertial drift ────────────────────────────────────────────

def test_total_loss_snapshot_then_hold():
    ship, ies = _ship()
    ship.SetSpeed(3.0, TGPoint3(0.2, 1.0, 0.1), MODEL)
    ship._current_speed = 3.0
    ship._current_angular_velocity = TGPoint3(0.01, 0.02, -0.03)
    _kill_pods(ies)
    assert "_drift_velocity" not in ship.__dict__
    log = _differential([ship], ticks=3)
    kinds = [[w[1] for w in writes] for writes in log]
    # The zero acceleration is written once (the mirror's was None), then
    # held: never written back again.
    snap = nm.K_DRIFT_SET | nm.K_VELOCITY | nm.K_ACCEL
    held = nm.K_VELOCITY
    assert kinds == [[snap], [held], [held]]
    assert isinstance(ship._drift_velocity, TGPoint3)


def test_total_loss_with_no_speed_setpoint_drifts_world_y():
    ship, ies = _ship()
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.1))
    assert ship._speed_setpoint is None
    ship._current_speed = 2.5
    _kill_pods(ies)
    _differential([ship], ticks=2)
    d = ship._drift_velocity
    assert (d.x, d.y, d.z) == (0.0, 2.5, 0.0)


def test_repair_reseeds_speed_from_drift_length():
    ship, _ies = _ship()
    ship.SetSpeed(5.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship._drift_velocity = TGPoint3(1.0, 2.0, 2.0)      # length 3
    log = _differential([ship], ticks=2)
    first = log[0][0][1]
    assert first & nm.K_DRIFT_CLEAR and first & nm.K_SPEED
    assert "_drift_velocity" in ship.__dict__
    assert ship._drift_velocity is None
    assert not log[1][0][1] & nm.K_DRIFT_CLEAR


# ── No real limits: the FALLBACK_MAX_ACCEL snap ──────────────────────────────

def test_fallback_limits_bare_ship():
    # ShipClass_Create attaches an empty impulse engine (authored limits
    # 0, no pods); a ShipClass built bare has none at all.
    ship = ShipClass()
    assert ship.GetImpulseEngineSubsystem() is None
    _rotate(ship)
    ship.SetSpeed(7.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.5, 0.0, -0.25))
    _differential([ship], ticks=3)
    assert ship._current_speed == 7.0
    cav = ship._current_angular_velocity
    assert (cav.x, cav.y, cav.z) == (0.5, 0.0, -0.25)


def test_fallback_limits_zero_authored():
    # Every authored limit 0: no real limits at all.
    ship, _ies = _ship(max_speed=0.0, accel=0.0, ang=0.0, ang_accel=0.0)
    ship.SetSpeed(7.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.5, 0.0, -0.25))
    _differential([ship], ticks=3)
    assert ship._current_speed == 7.0
    # Real speed and rate caps, but accelerations 0: each falls back to
    # FALLBACK_MAX_ACCEL.
    ship2, _ies2 = _ship("Ship2", accel=0.0, ang_accel=0.0)
    ship2.SetSpeed(5.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship2.SetTargetAngularVelocityDirect(TGPoint3(0.5, 0.0, -0.25))
    _differential([ship2], ticks=3)
    assert ship2._current_angular_velocity.x == 0.31


# ── No setpoints ─────────────────────────────────────────────────────────────

def test_setpointless_drift_model_and_world_spin():
    for space in (MODEL, WORLD):
        ship = App.ShipClass_Create("Drifter%d" % space)
        _rotate(ship)
        ship.SetVelocity(TGPoint3(1.0, 2.0, -3.0))
        ship.SetAngularVelocity(TGPoint3(0.1, 0.2, 0.3), space)
        before = _state(ship)
        log = _differential([ship], ticks=5)
        # drift.step sets no attribute: only the zero acceleration, once
        # (the mirror's was None); then nothing at all.
        assert _kinds(log) == [[nm.K_ACCEL]] + [[]] * 4
        assert _moved(before, ship) == (True, True)


def test_setpointless_player_is_untouched():
    g = Game()
    _set_current_game(g)
    player = App.ShipClass_Create("Player")
    App.Game_SetCurrentPlayer(player)
    assert App.Game_GetCurrentPlayer() is player
    player.SetVelocity(TGPoint3(0.0, 10.0, 0.0))
    player.SetAngularVelocity(TGPoint3(0.0, 0.0, 1.0), WORLD)
    before = _state(player)
    log = _differential([player], ticks=2, player=player)
    # Its helm owns the acceleration: nothing written, not even zeros.
    assert _kinds(log) == [[]] * 2
    assert _state(player) == before
    assert player._acceleration is None


# ── Rows the kernel passes over ──────────────────────────────────────────────

def test_immobile_skips():
    a, _ = _ship("Static")
    a.SetStatic(1)
    b, _ = _ship("Stationary")
    b.SetStationary(1)
    for s in (a, b):
        s.SetSpeed(5.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
        s.SetTargetAngularVelocityDirect(TGPoint3(0.1, 0.0, 0.0))
        s.SetVelocity(TGPoint3(1.0, 0.0, 0.0))
    before = [_motion(a), _motion(b)]
    log = _differential([a, b], ticks=2)
    assert _kinds(log) == [[nm.K_ACCEL] * 2, []]
    assert [_motion(a), _motion(b)] == before


def test_arriving_skips():
    ship, _ = _ship("Arriver")
    wes = WarpEngineSubsystem("Warp")
    ship.SetWarpEngineSubsystem(wes)
    wes._dewarp_drive = object()        # the slide is in progress
    nc.push_arriving(ship)
    assert _h.combat_dump(_slot(ship))["arriving"] == 1
    ship.SetSpeed(5.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    before = _motion(ship)
    log = _differential([ship], ticks=2)
    assert _kinds(log) == [[nm.K_ACCEL], []]
    assert _motion(ship) == before


# ── Odd values ───────────────────────────────────────────────────────────────

def test_nan_setpoint_takes_pythons_branch():
    """Review Focus 4: a NaN commanded speed, direction component or
    angular setpoint takes the branch Python's comparisons take (a NaN
    compares False everywhere) and gives the same bits."""
    cases = (
        lambda s: s.SetSpeed(NAN, TGPoint3(0.0, 1.0, 0.0), MODEL),
        lambda s: s.SetSpeed(2.0, TGPoint3(NAN, 1.0, 0.0), MODEL),
        lambda s: s.SetSpeed(2.0, TGPoint3(0.0, NAN, 0.0), WORLD),
        lambda s: s.SetTargetAngularVelocityDirect(TGPoint3(NAN, 0.1, 0.0)),
        lambda s: setattr(s, "_current_speed", NAN),
    )
    for i, case in enumerate(cases):
        ship, _ = _ship("Nan%d" % i)
        ship.SetSpeed(2.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
        ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.05))
        case(ship)
        _differential([ship], ticks=3)


def test_rows_python_raises_on_are_handed_back_untouched():
    """Review Focus 4: math.cos(inf) raises ValueError (an infinite spin
    angle), and a spin whose squares underflow divides by a zero rate
    (ZeroDivisionError). The kernel hands each such row to Python with
    nothing written, so Python raises there as it does today."""
    # A ship with no angular limits keeps the per-axis ramp, so an infinite
    # rate stays infinite (under the law's vector step it becomes a NaN).
    spinner = ShipClass()
    spinner.SetSpeed(1.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    spinner._current_angular_velocity = TGPoint3(float("inf"), 0.0, 0.0)
    drifter = App.ShipClass_Create("Tiny")
    drifter.SetAngularVelocity(TGPoint3(1e-200, 0.0, 0.0), WORLD)
    for ship, exc in ((spinner, ValueError), (drifter, ZeroDivisionError)):
        before = _state(ship)
        row = _h.combat_dump(_slot(ship))
        assert _native([ship]) == (nm.PYTHON_ROW, 0, "FallBack", [])
        assert _state(ship) == before
        assert _h.combat_dump(_slot(ship)) == row
        with pytest.raises(exc):
            ship_motion._step_ship_motion(ship, DT)


def test_unrepresentable_angular_velocity_stops_python_row_and_writes_nothing():
    ship, _ = _ship()
    ship.SetSpeed(5.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship._current_angular_velocity = (0.1, 0.2, 0.3)   # not a TGPoint3
    assert _h.combat_dump(_slot(ship))[
        "_current_angular_velocity_state"] == 2
    before = _state(ship)
    row = _h.combat_dump(_slot(ship))
    stop, at, reason, writes = _native([ship])
    assert (stop, at, reason, writes) == (
        nm.PYTHON_ROW, 0, "Unrepresentable", [])
    assert _state(ship) == before
    assert _h.combat_dump(_slot(ship)) == row


def test_warp_row_stops_and_resume_past_warp_runs_it(monkeypatch):
    ship, _ = _ship("Warper")
    ship.SetSpeed(5.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.05))
    ship.begin_warp_flight(warp_flight.WarpFlight(
        heading=(0.0, 1.0, 0.0), speed_policy="heading"))
    assert _h.combat_dump(_slot(ship))["_insystem_warp_transit"] == 1
    before = _state(ship)
    assert _native([ship]) == (nm.WARP_ROW, 0, "None", [])
    assert _state(ship) == before
    # Resumed past the warp check (Python's warp_flight.step returned
    # False): the rest of the row is the ordinary step.
    monkeypatch.setattr(warp_flight, "step", lambda s, dt: False)
    _differential([ship], ticks=3, resume=True,
                  python=ship_motion._step_after_warp)
    assert _moved(before, ship)[0]
    # resume_past_warp covers only the row it resumes at.
    other, _ = _ship("Warper2")
    other.SetSpeed(5.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    other.begin_warp_flight(warp_flight.WarpFlight(
        heading=(0.0, 1.0, 0.0), speed_policy="heading"))
    stop, at, reason, writes = _native([ship, other], resume=True)
    assert (stop, at, reason) == (nm.WARP_ROW, 1, "None")
    assert [w[0] for w in writes] == [0]


def test_rows_before_a_stop_are_committed_and_after_untouched():
    a, _ = _ship("A")
    b, _ = _ship("B")
    c, _ = _ship("C")
    for s in (a, b, c):
        s.SetSpeed(5.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
        s.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.05))
    b._current_angular_velocity = (0.0, 0.0, 0.0)   # unrepresentable
    snap_a = _Snap(a)
    before_b, before_c = _state(b), _state(c)
    stop, at, reason, writes = _native([a, b, c])
    assert (stop, at, reason) == (nm.PYTHON_ROW, 1, "Unrepresentable")
    assert [w[0] for w in writes] == [0]
    got_a = _state(a)
    assert _state(b) == before_b and _state(c) == before_c
    snap_a.restore()
    ship_motion._step_ship_motion(a, DT)
    assert got_a == _state(a)
    # The driver resumes past Python's row: C alone is the kernel's.
    _differential([a, b, c], begin=2)


def test_handles_out_of_range_begin_raises():
    ship, _ = _ship()
    with pytest.raises(ValueError):
        _h.combat_motion_compute([_slot(ship)], -1, DT, 2, False)


def test_constants():
    assert (nm.DONE, nm.WARP_ROW, nm.PYTHON_ROW) == (0, 1, 2)
    assert nm.REASONS == ("None", "NoRow", "NotStock", "Unrepresentable",
                          "FallBack", "BadTransform", "TurnGoal")
    assert (nm.K_SPEED, nm.K_ANG_VEL, nm.K_VELOCITY, nm.K_DRIFT_SET,
            nm.K_DRIFT_CLEAR, nm.K_MOTION_VEL, nm.K_ACCEL, nm.K_STEER) == (
                1, 2, 4, 8, 16, 32, 64, 128)


def test_compute_runs_with_the_gil_released_and_is_timed_as_kernel_m():
    """The binding's one released_compute (its source is guarded by
    test_native_k1_holds_gil.py): the probe sees the call at the Motion
    site (index 5) with the GIL released, and the compute timer counts it
    as kernel 5."""
    ship, _ = _ship()
    ship.SetSpeed(1.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    _h.combat_gil_probe_arm(False)
    _h.combat_gil_probe_take()
    _h.combat_compute_take(5)
    _h.combat_gil_probe_arm(True)
    try:
        _native([ship])
    finally:
        _h.combat_gil_probe_arm(False)
    got = _h.combat_gil_probe_take()
    assert got["calls"] == [0, 0, 0, 0, 0, 1], got
    assert got["released"] == got["calls"], got
    assert _h.combat_compute_take(5)[1] == 1


# ── Review fix round 1 ───────────────────────────────────────────────────────

def test_tuple_velocity_takes_pythons_path_and_raises():
    """Review Focus 4: `_velocity` holding a tuple mirrors its vector for
    the other kernels (VEC3 is unchanged) with `_velocity_state` 2, so a
    drifter -- the one branch that READS `_velocity` -- is Python's, where
    `v.x` raises as today. A powered ship only rebinds `_velocity`, so the
    kernel flies it and leaves a TGPoint3 (state 1), as Python does."""
    drifter = App.ShipClass_Create("TupleV")
    drifter._velocity = (1.0, 2.0, 3.0)
    row = _h.combat_dump(_slot(drifter))
    assert row["_velocity_state"] == 2
    assert row["_velocity"] == (1.0, 2.0, 3.0)
    before = _state(drifter)
    assert _native([drifter]) == (nm.PYTHON_ROW, 0, "Unrepresentable", [])
    assert _state(drifter) == before
    assert _h.combat_dump(_slot(drifter)) == row
    with pytest.raises(AttributeError):
        ship_motion._step_ship_motion(drifter, DT)
    powered, _ = _ship("TupleP")
    powered.SetSpeed(2.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    powered._velocity = (1.0, 2.0, 3.0)
    _differential([powered], ticks=1)
    assert isinstance(powered._velocity, TGPoint3)
    assert _h.combat_dump(_slot(powered))["_velocity_state"] == 1


def test_large_angle_drift_differential():
    """Big per-tick angles about an axis on no coordinate axis, in both
    frames: every Rodrigues term (t*x*y, s*z, ...) carries its own bits.
    The small-rate tests cannot see an association change there."""
    for space in (MODEL, WORLD):
        for dt, w in ((0.7, (1.1, -0.6, 0.45)), (0.85, (-2.3, 1.7, 0.9)),
                      (0.9, (0.31, 2.6, -1.4))):
            ship = App.ShipClass_Create("Big%d" % space)
            _rotate(ship, 1.3, (0.6, -0.2, 0.77))
            ship.SetVelocity(TGPoint3(0.4, -0.3, 0.2))
            ship.SetAngularVelocity(TGPoint3(*w), space)
            _differential([ship], ticks=6, dt=dt)


def test_far_out_high_speed_powered_with_large_rates():
    ship, _ = _ship("Far", max_speed=60.0, accel=25.0, ang=2.5,
                    ang_accel=1.9)
    ship.SetTranslateXYZ(5012.375, -4987.25, 3001.0625)
    ship.SetSpeed(55.0, TGPoint3(0.31, 1.0, -0.47), MODEL)
    ship.SetTargetAngularVelocityDirect(TGPoint3(2.2, -1.6, 2.4))
    before = _state(ship)
    _differential([ship], ticks=30, dt=0.25)
    assert _moved(before, ship) == (True, True)


def test_setpointless_drift_with_angular_space_absent():
    """No SetAngularVelocity ever ran, so `_angular_space` is absent:
    drift.step's getattr default (world space) and the row's default (1)
    agree."""
    ship = App.ShipClass_Create("NoSpace")
    _rotate(ship)
    ship._angular_velocity = TGPoint3(0.4, -0.2, 0.9)
    ship.SetVelocity(TGPoint3(0.1, 0.0, -0.3))
    assert "_angular_space" not in ship.__dict__
    assert _h.combat_dump(_slot(ship))["_angular_space"] == 1
    before = _state(ship)
    _differential([ship], ticks=4, dt=0.5)
    assert _moved(before, ship) == (True, True)


def test_twin_constants_equal_pythons():
    """motion_step.h's kFallbackMaxAccel / kBcImpulseTau are twins of
    ship_motion's FALLBACK_MAX_ACCEL / BC_IMPULSE_TAU: pinned by value."""
    fallback, tau = _h.combat_motion_constants()
    assert _hx(fallback) == _hx(ship_motion.FALLBACK_MAX_ACCEL)
    assert _hx(tau) == _hx(ship_motion.BC_IMPULSE_TAU)
