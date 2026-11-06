"""Kernel M's write log applied by C (native motion phase 2, Task 5).

``native/src/host/motion_write_apply.cc`` (``apply_motion_writes``) stores the
kernel's writes into the Python objects; ``native_motion._apply_writes_py`` is
THE REFERENCE, and the C applier must do what it does, store for store: the
same objects, value types, in-place identity (``_current_angular_velocity``
keeps its object) and exceptions (a raising store: the rest are applied,
then the first is raised). ``combat_motion_apply`` is the test-only binding
that runs the C applier alone on a Python-encoded log (the reference's).
"""
import random

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
from engine.appc.math import TGPoint3  # noqa: E402

SEED = 20261104
NAN, INF = float("nan"), float("inf")
_SPECIAL = (0.0, -0.0, NAN, INF, -INF, 1e-300, -1e300, 5e-324)
_ALL_BITS = (nm.K_SPEED | nm.K_ANG_VEL | nm.K_VELOCITY | nm.K_DRIFT_SET
             | nm.K_DRIFT_CLEAR | nm.K_MOTION_VEL | nm.K_ACCEL
             | nm.K_STEER)


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    nc.configure({})
    assert nc.enabled()
    yield
    nc.reset()


def _float(rng):
    if rng.random() < 0.15:
        return rng.choice(_SPECIAL)
    return rng.uniform(-50.0, 50.0)


def _v3(rng):
    return (_float(rng), _float(rng), _float(rng))


def _ships(seed, n=6):
    """`n` ships whose motion attributes start from the same seeded state
    (so two calls give twins): a TGPoint3 angular velocity and velocity,
    a drift velocity absent, None or a TGPoint3, and a stored turn goal
    owning a setpoint (a K_STEER store rebinds both)."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        s = App.ShipClass_Create("Apply%d" % i)
        s._current_speed = _float(rng)
        s._current_angular_velocity = TGPoint3(*_v3(rng))
        s.SetVelocity(TGPoint3(*_v3(rng)))
        kind = i % 3
        if kind == 1:
            s._drift_velocity = None
        elif kind == 2:
            s._drift_velocity = TGPoint3(*_v3(rng))
        s.TurnTowardLocation(TGPoint3(100.0 + i, -40.0, 7.0))
        out.append(s)
    return out


def _writes(seed, n_ships, n=40):
    """A seeded log in combat_motion_compute's encoding: rows in range,
    any combination of `what` bits (more than the kernel ever logs at once:
    the applier must not care); a few in the 6-tuple form, which leaves the
    motion vector, the acceleration and the setpoint zero, and a few in the
    8-tuple form, which leaves the setpoint zero."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        what = rng.randint(0, _ALL_BITS)
        w = (rng.randrange(n_ships), what, _float(rng), _v3(rng),
             _v3(rng), _v3(rng))
        if rng.random() < 0.8:
            w += (_v3(rng) + (_float(rng),), _v3(rng))
            if rng.random() < 0.8:
                w += (_v3(rng),)
        out.append(w)
    return out


def _value(v):
    """An attribute's value, its type and (for floats) its bits."""
    if isinstance(v, TGPoint3):
        return ("TGPoint3", type(v.x).__name__, float(v.x).hex(),
                type(v.y).__name__, float(v.y).hex(),
                type(v.z).__name__, float(v.z).hex())
    if isinstance(v, float):
        return ("float", v.hex())
    if isinstance(v, tuple):
        return ("tuple",) + tuple(_value(x) for x in v)
    return (type(v).__name__, repr(v))


_ATTRS = ("_current_speed", "_current_angular_velocity", "_velocity",
          "_drift_velocity", "_motion_vel", "_acceleration",
          "_target_angular_velocity_setpoint",
          "_target_angular_velocity_fraction")


def _state(ship):
    d = ship.__dict__
    out = {a: (_value(d[a]) if a in d else "absent") for a in _ATTRS}
    goal = d.get("_turn_goal")
    out["goal_owns_setpoint"] = (
        None if goal is None
        else goal[1] is d.get("_target_angular_velocity_setpoint"))
    return out


def test_c_apply_equals_the_reference():
    for k in range(25):
        c_ships = _ships(SEED + k)
        py_ships = _ships(SEED + k)
        assert [_state(s) for s in c_ships] == [_state(s) for s in py_ships]
        log = _writes(SEED * 7 + k, len(c_ships))
        cav_ids = [id(s.__dict__["_current_angular_velocity"])
                   for s in c_ships]
        old_vel = [s.__dict__["_velocity"] for s in c_ships]
        old_av = [s.__dict__["_target_angular_velocity_setpoint"]
                  for s in c_ships]
        had_drift = ["_drift_velocity" in s.__dict__ for s in c_ships]

        _h.combat_motion_apply(c_ships, log)
        nm._apply_writes_py(py_ships, log)

        assert [_state(s) for s in c_ships] == \
            [_state(s) for s in py_ships], k
        touched = {}
        for row, what, *_rest in log:
            touched[row] = touched.get(row, 0) | what
        for i, s in enumerate(c_ships):
            d = s.__dict__
            what = touched.get(i, 0)
            # In place, never rebound.
            assert id(d["_current_angular_velocity"]) == cav_ids[i]
            if what & nm.K_VELOCITY:
                assert d["_velocity"] is not old_vel[i]
                assert type(d["_velocity"]) is TGPoint3
            else:
                assert d["_velocity"] is old_vel[i]
            av = d["_target_angular_velocity_setpoint"]
            if what & nm.K_STEER:
                # A new TGPoint3, owned by the goal; the keyboard turn
                # fraction cleared.
                assert av is not old_av[i] and type(av) is TGPoint3
                assert d["_turn_goal"][1] is av
                assert d["_target_angular_velocity_fraction"] is None
            else:
                assert av is old_av[i]
            if not had_drift[i] and not what & (nm.K_DRIFT_SET
                                                | nm.K_DRIFT_CLEAR):
                assert "_drift_velocity" not in d
            if what & nm.K_SPEED:
                assert type(d["_current_speed"]) is float


def test_apply_pushes_nothing():
    """The apply alone stores quietly: every row dumps the same before and
    after it (the kernel writes the mirror itself; a push here would be a
    second, redundant write -- or, with a value the kernel did not write,
    a lie)."""
    ships = _ships(SEED)
    log = _writes(SEED + 1, len(ships))
    before = [repr(_h.combat_dump(s.__dict__["_nslot"])) for s in ships]
    _h.combat_motion_apply(ships, log)
    assert [_state(s) for s in ships] != [_state(s) for s in _ships(SEED)]
    after = [repr(_h.combat_dump(s.__dict__["_nslot"])) for s in ships]
    assert after == before


class _Frozen:
    """An angular velocity whose components cannot be set."""
    __slots__ = ()


def _raising_ships():
    ships = _ships(SEED + 99, n=3)
    # Ship 0: no angular velocity at all (KeyError reading it).
    del ships[0].__dict__["_current_angular_velocity"]
    # Ship 1: one that refuses its x (AttributeError).
    ships[1].__dict__["_current_angular_velocity"] = _Frozen()
    return ships


def test_apply_raise_applies_the_rest_then_raises_the_first():
    log = [
        (0, nm.K_ANG_VEL | nm.K_SPEED, 1.5, (1.0, 2.0, 3.0), (0.0,) * 3,
         (0.0,) * 3),
        (1, nm.K_ANG_VEL | nm.K_VELOCITY, 2.5, (4.0, 5.0, 6.0),
         (7.0, 8.0, 9.0), (0.0,) * 3),
        (2, nm.K_SPEED | nm.K_DRIFT_SET, 3.5, (0.0,) * 3, (0.0,) * 3,
         (-1.0, -2.0, -3.0)),
    ]
    c_ships, py_ships = _raising_ships(), _raising_ships()
    with pytest.raises(BaseException) as c_err:
        _h.combat_motion_apply(c_ships, log)
    with pytest.raises(BaseException) as py_err:
        nm._apply_writes_py(py_ships, log)
    assert c_err.type is py_err.type is KeyError
    assert c_err.value.args == py_err.value.args
    states = [{a: (_value(s.__dict__[a]) if a in s.__dict__ else "absent")
               for a in ("_current_speed", "_velocity", "_drift_velocity")}
              for s in c_ships]
    assert states == [{a: (_value(s.__dict__[a]) if a in s.__dict__
                           else "absent")
                       for a in ("_current_speed", "_velocity",
                                 "_drift_velocity")} for s in py_ships]
    # The rest were applied: ship 0's speed (after its raising store, in
    # the reference's order), ship 1's velocity, ship 2's whole write.
    assert c_ships[0].__dict__["_current_speed"] == 1.5
    assert _value(c_ships[1].__dict__["_velocity"]) == _value(
        TGPoint3(7.0, 8.0, 9.0))
    assert c_ships[2].__dict__["_current_speed"] == 3.5
    assert _value(c_ships[2].__dict__["_drift_velocity"]) == _value(
        TGPoint3(-1.0, -2.0, -3.0))


def test_apply_with_a_row_outside_the_ships_raises_index_error():
    """`ships[row]` outside the list raises at once, as the reference's
    unguarded index does."""
    ships = _ships(SEED, n=2)
    log = [(5, nm.K_SPEED, 1.0, (0.0,) * 3, (0.0,) * 3, (0.0,) * 3)]
    with pytest.raises(IndexError):
        nm._apply_writes_py(ships, log)
    with pytest.raises(IndexError):
        _h.combat_motion_apply(ships, log)


def test_apply_steer_raise_keeps_its_earlier_stores():
    """K_STEER's three stores in the reference's order: the setpoint, the
    fraction, then ``_turn_goal[1]``. A ship with no goal list raises at the
    third (TypeError), after the first two; the later stores (K_ACCEL) are
    still applied, then the first exception is raised, in both appliers."""
    def ships():
        out = _ships(SEED + 5, n=2)
        out[0].__dict__["_turn_goal"] = None
        return out

    log = [(0, nm.K_STEER | nm.K_ACCEL, 0.0, (0.0,) * 3, (0.0,) * 3,
            (0.0,) * 3, (0.0,) * 4, (1.0, 2.0, 3.0), (0.25, -0.5, 0.75)),
           (1, nm.K_STEER, 0.0, (0.0,) * 3, (0.0,) * 3, (0.0,) * 3,
            (0.0,) * 4, (0.0,) * 3, (-1.0, 0.0, 1.0))]
    c_ships, py_ships = ships(), ships()
    with pytest.raises(BaseException) as c_err:
        _h.combat_motion_apply(c_ships, log)
    with pytest.raises(BaseException) as py_err:
        nm._apply_writes_py(py_ships, log)
    assert c_err.type is py_err.type is TypeError
    assert [_state(s) for s in c_ships] == [_state(s) for s in py_ships]
    d = c_ships[0].__dict__
    assert _value(d["_target_angular_velocity_setpoint"]) == _value(
        TGPoint3(0.25, -0.5, 0.75))
    assert d["_target_angular_velocity_fraction"] is None
    assert d["_acceleration"] == (1.0, 2.0, 3.0)
    assert c_ships[1].__dict__["_turn_goal"][1] is \
        c_ships[1].__dict__["_target_angular_velocity_setpoint"]
