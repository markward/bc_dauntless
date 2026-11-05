"""Every input the native motion kernel (kernel M, native motion phase 2)
reads, written through to the native combat mirror
(engine/appc/native_combat.py). Python stays the authority: the mirror is a
copy, kept current by the descriptors and by an explicit push after each
in-place write.

Each test writes through the real setter (or the engine's own in-place
writer) and reads the row back with combat_dump. Floats compare by
float.hex(), never with a tolerance. The expected encodings are spelled out
here, independently of native_combat's own encoders.
"""
import types

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
from engine.appc.math import TGPoint3  # noqa: E402
from engine.appc.ships import ShipClass  # noqa: E402
from engine.appc.subsystems import (  # noqa: E402
    ImpulseEngineSubsystem, ShipSubsystem,
)

DT = 1.0 / 60.0


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    nc.configure({})
    assert nc.enabled()
    yield
    nc.reset()


def _slot(obj):
    return obj.__dict__["_nslot"]


def _dump(obj):
    return _h.combat_dump(_slot(obj))


def _hex(values):
    return tuple(float(v).hex() for v in values)


# ── The encodings, spelled out independently ─────────────────────────────────

def _point(value):
    """(dumped vector, state) for a POINT_OR_NONE value."""
    if value is None:
        return None, 0
    if isinstance(value, TGPoint3):
        return _hex((value.x, value.y, value.z)), 1
    return _hex((0.0, 0.0, 0.0, 0.0)), 2


def _setpoint(value):
    if value is None:
        return ()
    try:
        speed, d, frame = value
        return _hex((float(speed), float(d.x), float(d.y), float(d.z),
                     float(frame)))
    except (TypeError, ValueError, AttributeError):
        return _hex((0.0,) * 6)


POINTS = ("_current_angular_velocity", "_drift_velocity",
          "_target_angular_velocity_setpoint", "_angular_velocity")


def _ship_expect(ship):
    """{dump key: expected} for every motion input of `ship`'s row."""
    d = ship.__dict__
    out = {}
    for name in POINTS:
        vec, state = _point(d.get(name))
        out[name] = vec
        out[name + "_state"] = state
    out["_current_speed"] = float(d["_current_speed"]).hex()
    out["_speed_setpoint"] = _setpoint(d.get("_speed_setpoint"))
    out["_angular_space"] = int(d.get("_angular_space", 1))
    out["_static"] = 1 if d["_static"] else 0
    out["_stationary"] = 1 if d["_stationary"] else 0
    out["_insystem_warp_transit"] = (
        0 if d["_insystem_warp_transit"] is None else 1)
    ies = d["_impulse_engine_subsystem"]
    out["_impulse_engine_subsystem"] = -1 if ies is None else _slot(ies)
    return out


def _ship_got(ship):
    row = _dump(ship)
    out = {}
    for name in POINTS:
        v = row[name]
        out[name] = None if v is None else _hex(v)
        out[name + "_state"] = row[name + "_state"]
    out["_current_speed"] = float(row["_current_speed"]).hex()
    out["_speed_setpoint"] = _hex(row["_speed_setpoint"])
    for name in ("_angular_space", "_static", "_stationary",
                 "_insystem_warp_transit", "_impulse_engine_subsystem"):
        out[name] = row[name]
    return out


IES_FLOATS = ("_power_percentage_wanted", "_max_speed", "_max_accel",
              "_max_angular_velocity", "_max_angular_accel")


def _ies_expect(ies):
    return {n: float(ies.__dict__[n]).hex() for n in IES_FLOATS}


def _ies_got(ies):
    row = _dump(ies)
    return {n: float(row[n]).hex() for n in IES_FLOATS}


def _check(ship):
    assert _ship_got(ship) == _ship_expect(ship)
    ies = ship.GetImpulseEngineSubsystem()
    if ies is not None:
        assert _ies_got(ies) == _ies_expect(ies)


# ── Every write pushes ───────────────────────────────────────────────────────

def test_each_motion_input_is_pushed_on_write():
    from engine.appc import warp_flight
    ship = App.ShipClass_Create("Mover")
    _check(ship)
    ies = ImpulseEngineSubsystem("Impulse")
    ship.SetImpulseEngineSubsystem(ies)
    assert _dump(ship)["_impulse_engine_subsystem"] == _slot(ies)
    _check(ship)
    writes = (
        lambda: ship.SetSpeed(3.5, TGPoint3(0.25, 1.0, -0.5), 1),
        lambda: ship.SetTargetAngularVelocityDirect(TGPoint3(0.1, -0.2, 0.3)),
        lambda: setattr(ship, "_current_speed", 2.25),
        lambda: setattr(ship, "_drift_velocity", TGPoint3(1.0, 2.0, 3.0)),
        lambda: setattr(ship, "_drift_velocity", None),
        lambda: ship.SetAngularVelocity(TGPoint3(0.01, 0.02, 0.03), 0),
        lambda: ship.SetAngularVelocity(TGPoint3(0.04, 0.05, 0.06), 1),
        lambda: ship.SetStatic(1),
        lambda: ship.SetStatic(0),
        lambda: ship.SetStationary(1),
        lambda: ship.SetStationary(0),
        lambda: ies.SetPowerPercentageWanted(0.75),
        lambda: ies.SetMaxSpeed(6.3),
        lambda: ies.SetMaxAccel(1.7),
        lambda: ies.SetMaxAngularVelocity(0.31),
        lambda: ies.SetMaxAngularAccel(0.11),
        lambda: ship.begin_warp_flight(
            warp_flight.WarpFlight(heading=(0.0, 1.0, 0.0),
                                   speed_policy="heading")),
        lambda: ship._end_in_system_warp("stopped"),
        lambda: ship.CompleteStop(),
        lambda: ship.SetImpulseEngineSubsystem(None),
    )
    for i, write in enumerate(writes):
        write()
        assert _ship_got(ship) == _ship_expect(ship), "after write %d" % i
        assert _ies_got(ies) == _ies_expect(ies), "after write %d" % i
    assert _dump(ship)["_impulse_engine_subsystem"] == -1


def test_point_or_none_states():
    ship = App.ShipClass_Create("Points")
    assert "_drift_velocity" not in ship.__dict__
    assert _dump(ship)["_drift_velocity"] is None
    assert _dump(ship)["_drift_velocity_state"] == 0
    ship._drift_velocity = TGPoint3(1.5, -2.5, 3.5)
    assert _hex(_dump(ship)["_drift_velocity"]) == _hex((1.5, -2.5, 3.5))
    assert _dump(ship)["_drift_velocity_state"] == 1
    ship._drift_velocity = (1.0, 2.0, 3.0)      # not a TGPoint3
    assert _dump(ship)["_drift_velocity_state"] == 2
    assert _hex(_dump(ship)["_drift_velocity"]) == _hex((0.0,) * 4)
    ship._drift_velocity = None
    assert _dump(ship)["_drift_velocity"] is None
    assert _dump(ship)["_drift_velocity_state"] == 0
    # Never a drop: every value is representable as one of the states.
    assert "_nslot" in ship.__dict__
    for name in POINTS:
        setattr(ship, name, (0.0, 0.0, 0.0))
        assert _dump(ship)[name + "_state"] == 2
        setattr(ship, name, TGPoint3(0.0, 0.0, 0.0))
        assert _dump(ship)[name + "_state"] == 1
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()


def test_absent_optional_fields_read_like_plain_attributes():
    """`_drift_velocity` and `_angular_space` are ABSENT until first written,
    and their readers use getattr's default: the descriptor must not answer
    such a read itself (it did, once: ship_motion called .Length() on it).
    `del` returns the row to the absent value."""
    from engine.appc.objects import PhysicsObjectClass
    ship = App.ShipClass_Create("Absent")
    for name, default in (("_drift_velocity", None), ("_angular_space", 7)):
        assert name not in ship.__dict__
        assert getattr(ship, name, default) == default
        assert not hasattr(ship, name)
    ship._drift_velocity = TGPoint3(1.0, 2.0, 3.0)
    ship.SetAngularVelocity(TGPoint3(0.0, 0.0, 0.1),
                            PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    assert _dump(ship)["_drift_velocity_state"] == 1
    assert _dump(ship)["_angular_space"] == 0
    del ship._drift_velocity
    del ship._angular_space
    assert getattr(ship, "_drift_velocity", None) is None
    assert _dump(ship)["_drift_velocity_state"] == 0
    assert _dump(ship)["_angular_space"] == \
        PhysicsObjectClass.DIRECTION_WORLD_SPACE
    with pytest.raises(AttributeError):
        del ship._drift_velocity
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()


def test_speed_setpoint_none_tuple_and_garbage():
    ship = App.ShipClass_Create("Setpoint")
    assert _dump(ship)["_speed_setpoint"] == []
    ship.SetSpeed(-1.25, TGPoint3(0.0, 1.0, 0.0), 0)
    assert _hex(_dump(ship)["_speed_setpoint"]) == _hex(
        (-1.25, 0.0, 1.0, 0.0, 0.0))
    for garbage in ("garbage", (1.0, 2.0), (1.0, (0.0, 1.0, 0.0), 0),
                    (1.0, TGPoint3(0.0, 1.0, 0.0), "model"), 7):
        ship._speed_setpoint = garbage
        assert _hex(_dump(ship)["_speed_setpoint"]) == _hex((0.0,) * 6), \
            garbage
        assert "_nslot" in ship.__dict__
    ship._speed_setpoint = None
    assert _dump(ship)["_speed_setpoint"] == []
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()


def test_angular_space_defaults_to_world_and_rock_setdefault_agrees():
    from engine.appc.objects import PhysicsObjectClass
    from engine.rocks.rock import RockClass, maybe_become_rock
    world = PhysicsObjectClass.DIRECTION_WORLD_SPACE
    ship = App.ShipClass_Create("Spaceless")
    assert "_angular_space" not in ship.__dict__
    assert _dump(ship)["_angular_space"] == world
    ship.SetGenus(App.GENUS_ASTEROID)
    assert maybe_become_rock(ship)
    assert isinstance(ship, RockClass)
    assert ship.__dict__["_angular_space"] == world
    assert _dump(ship)["_angular_space"] == world
    ship.SetAngularVelocity(TGPoint3(0.0, 0.0, 0.1),
                            PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    assert _dump(ship)["_angular_space"] == \
        PhysicsObjectClass.DIRECTION_MODEL_SPACE
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()


# ── In-place writers push ────────────────────────────────────────────────────

def _cav_matches(ship):
    cav = ship.__dict__["_current_angular_velocity"]
    row = _dump(ship)
    assert row["_current_angular_velocity_state"] == 1
    assert _hex(row["_current_angular_velocity"]) == _hex((cav.x, cav.y, cav.z))
    assert float(row["_current_speed"]).hex() == \
        float(ship.__dict__["_current_speed"]).hex()


def test_in_place_angular_velocity_writes_are_pushed():
    from engine import host_loop
    from engine.appc import ship_motion
    ship = App.ShipClass_Create("InPlace")
    cav = ship.__dict__["_current_angular_velocity"]

    host_loop._PlayerControl._apply_body_rotation(ship, 0.1, 0.2, 0.3, DT)
    assert ship.__dict__["_current_angular_velocity"] is cav    # in place
    assert (cav.x, cav.y, cav.z) == (0.1, -0.3, -0.2)
    _cav_matches(ship)

    control = types.SimpleNamespace(
        _current_speed=1.5, _current_pitch_rate=-0.05,
        _current_yaw_rate=0.07, _current_roll_rate=0.11)
    host_loop._PlayerControl._sync_ship_integrator_from_control(control, ship)
    assert ship.__dict__["_current_angular_velocity"] is cav
    assert (cav.x, cav.y, cav.z) == (-0.05, -0.11, -0.07)
    _cav_matches(ship)

    ship.SetTargetAngularVelocityDirect(TGPoint3(0.4, 0.5, -0.6))
    ship.SetSpeed(2.0, TGPoint3(0.0, 1.0, 0.0), 0)
    before = (cav.x, cav.y, cav.z)
    ship_motion._step_ship_motion(ship, DT)
    assert ship.__dict__["_current_angular_velocity"] is cav
    assert (cav.x, cav.y, cav.z) != before                      # it ramped
    _cav_matches(ship)
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()


# ── Class flags ──────────────────────────────────────────────────────────────

class _ModShip(ShipClass):
    def SetVelocity(self, v) -> None:
        super().SetVelocity(v)


class _ModImpulse(ImpulseEngineSubsystem):
    def IsOn(self) -> int:
        return super().IsOn()


class _ModPod(ShipSubsystem):
    def GetConditionPercentage(self) -> float:
        return super().GetConditionPercentage()


def test_motion_stock_flags():
    from engine.appc.objects import PhysicsObjectClass
    assert _dump(App.ShipClass_Create("Stock"))["motion_stock"] == 1
    assert _dump(_ModShip())["motion_stock"] == 0
    assert _dump(PhysicsObjectClass())["motion_stock"] == 0  # not a ship

    stock = ImpulseEngineSubsystem("Impulse")
    assert _dump(stock)["motion_ies_stock"] == 1
    assert _dump(stock)["motion_pod_stock"] == 1
    assert _dump(_ModImpulse("Impulse"))["motion_ies_stock"] == 0
    assert _dump(ShipSubsystem("Pod"))["motion_ies_stock"] == 0  # not an IES
    assert _dump(ShipSubsystem("Pod"))["motion_pod_stock"] == 1
    assert _dump(_ModPod("Pod"))["motion_pod_stock"] == 0
    nc.audit_mirror()
    assert nc.audit_failures() == [], nc.audit_failures()


# ── The net: a headless fight audits clean ───────────────────────────────────

def test_audit_clean_after_a_headless_fight(monkeypatch, tmp_path):
    """120 GameLoop ticks of combat_stress (8 ships) under
    DAUNTLESS_NATIVE_AUDIT=1, which audits the mirror at the end of every
    tick: a motion input written without a push shows up here."""
    from tests.helpers import bc_assets, headless_mission
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    monkeypatch.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
    monkeypatch.setenv("DAUNTLESS_NATIVE_AUDIT", "1")
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", "8")
    nc.reset()
    App.g_kTimerManager._time = 0.0
    import random
    random.seed(0)
    headless_mission.load("engine.dev_missions.combat_stress")
    from engine import host_loop
    from engine.appc.ship_iter import iter_ships
    from engine.core import step_memo
    from engine.core.loop import GameLoop
    host_loop._reset_sensor_state()
    step_memo.forget()
    loop = GameLoop()
    assert nc.audit_enabled()
    ships = list(iter_ships())
    assert len(ships) >= 8
    speeds = {id(s): s.__dict__["_current_speed"] for s in ships}
    for _ in range(120):
        loop.tick()
    assert nc.audit_failures() == [], nc.audit_failures()
    # The fight moved ships: the audit saw motion inputs change.
    assert any(s.__dict__["_current_speed"] != speeds[id(s)] for s in ships)


def test_velocity_state_beside_the_vec3():
    """`_velocity` keeps its VEC3 encoding (the other kernels read the
    vector) and gains `_velocity_state` beside it for kernel M: 1 for a
    TGPoint3, 2 for anything else the VEC3 accepts (a tuple). The row is
    kept, and the audit checks both."""
    ship = App.ShipClass_Create("Vel")
    assert _dump(ship)["_velocity_state"] == 1
    ship.SetVelocity(TGPoint3(1.5, -2.5, 3.5))
    row = _dump(ship)
    assert (_hex(row["_velocity"]), row["_velocity_state"]) == (
        _hex((1.5, -2.5, 3.5)), 1)
    ship._velocity = (4.0, 5.0, 6.0)
    row = _dump(ship)
    assert "_nslot" in ship.__dict__
    assert (_hex(row["_velocity"]), row["_velocity_state"]) == (
        _hex((4.0, 5.0, 6.0)), 2)
    nc.audit_mirror()
    assert list(nc.audit_failures()) == []
    ship.SetVelocity(TGPoint3(0.0, 1.0, 0.0))
    assert _dump(ship)["_velocity_state"] == 1
    # A row whose state disagrees is an audit failure.
    _h.combat_set_i(_slot(ship), nc._fid("_velocity_state"), 2)
    nc.audit_mirror()
    assert ("ShipClass", "_velocity") in list(nc.audit_failures())
