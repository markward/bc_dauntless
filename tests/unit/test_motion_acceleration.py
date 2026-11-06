"""GetAccelerationTG is the motion law's own output, not dv/dt.

Mark's ruling 2026-11-06: a ship's acceleration is what its controller
commands this tick -- the law's step / dt (``ship_motion.step_vector_velocity``)
-- so a direct velocity write (a warp drop-out, a dash stop, a test) gives no
one-tick spike, the manually flown player (whose helm runs the law outside
the motion stage) reports its real acceleration, and kernel M writes back an
acceleration only when it changed (a drifting or immobile row appends no
write, as before the motion law).

Every scene runs with kernel M on (``{}``) and off (the Python reference);
both must report the same.
"""
import math

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
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.appc.ships import ShipClass  # noqa: E402
from engine.appc.subsystems import (  # noqa: E402
    ImpulseEngineSubsystem, ShipSubsystem,
)
from engine.core.game import Game, _set_current_game  # noqa: E402

DT = 1.0 / 60.0
MODEL, WORLD = 0, 1
ON, OFF = {}, {"DAUNTLESS_NATIVE_MOTION": "0"}
ARMS = pytest.mark.parametrize("env", [ON, OFF], ids=["native", "python"])


@pytest.fixture(autouse=True)
def _clean():
    _set_current_game(None)
    App.g_kSetManager._sets.clear()
    nc.reset()
    nc.configure({})
    yield
    App.g_kSetManager._sets.clear()
    nc.reset()
    _set_current_game(None)


# ── Building ships (as test_native_motion_driver) ────────────────────────────

def _set(name="S"):
    pSet = App.SetClass_Create()
    pSet.SetName(name)
    App.g_kSetManager._sets[name] = pSet
    return pSet


def _engine(ship, pods=3):
    """Galaxy-like limits: MaxSpeed 6.3, MaxAccel 1.5."""
    ies = ImpulseEngineSubsystem("Impulse Engines")
    ship.SetImpulseEngineSubsystem(ies)
    ies._max_condition = 100.0
    ies._condition = 100.0
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    ies.TurnOn()
    for i in range(pods):
        pod = ShipSubsystem("pod%d" % i)
        pod.SetMaxCondition(2600.0)
        ies.AddChildSubsystem(pod)
    return ies


def _ship(name, pSet, pos=(0.01, 0.02, -0.005), engine=True):
    ship = ShipClass()
    ship.SetName(name)
    if engine:
        _engine(ship)
    ship.SetTranslateXYZ(*pos)
    R = TGMatrix3()
    R.MakeRotation(0.7, TGPoint3(0.267, 0.534, 0.801))
    ship.SetMatrixRotation(R)
    pSet.AddObjectToSet(ship, name)
    return ship


def _arm(env):
    nm.reset()
    nm.configure(env)


def _accel(ship):
    a = ship.GetAccelerationTG()
    return (a.x, a.y, a.z)


def _norm(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


# ── The law's step ───────────────────────────────────────────────────────────

@ARMS
def test_straight_line_acceleration_is_the_law_step(env):
    """From rest at full impulse the MaxAccel cap binds: one tick's
    acceleration is the nose times 1.5."""
    ship = _ship("Galaxy", _set())
    _arm(env)
    assert ship.GetImpulseEngineSubsystem().GetMaxAccel() == 1.5
    # The law's direction is the nose unitized (the scene's rotation axis
    # is not quite unit, so neither is the column).
    fwd = ship.GetWorldRotation().GetCol(1)
    fwd.Unitize()
    ship.SetImpulse(1.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ship_motion.tick_all_ship_motion(DT)
    for got, want in zip(_accel(ship), (fwd.x * 1.5, fwd.y * 1.5,
                                         fwd.z * 1.5)):
        assert abs(got - want) < 1e-12


@ARMS
def test_external_velocity_write_gives_no_spike(env):
    """A direct `_current_speed` write (a warp drop-out) re-seeds the vector;
    the next tick's acceleration is the law's, never the jump over dt."""
    ship = _ship("Galaxy", _set())
    _arm(env)
    ship.SetImpulse(1.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    for _ in range(5 * 60):
        ship_motion.tick_all_ship_motion(DT)
    assert ship._current_speed > 3.0
    ship._current_speed = 0.0
    ship_motion.tick_all_ship_motion(DT)
    assert _norm(_accel(ship)) <= 1.5 + 1e-9


@ARMS
def test_drift_and_immobile_rows_report_zero(env):
    pSet = _set()
    drifter = _ship("Drifter", pSet)
    drifter.SetSpeed(3.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    drifter._current_speed = 3.0
    ies = drifter.GetImpulseEngineSubsystem()
    for i in range(ies.GetNumChildSubsystems()):
        ies.GetChildSubsystem(i)._condition = 0.0
    anchor = _ship("Anchor", pSet, pos=(0.3, 0.0, 0.0))
    anchor.SetStatic(1)
    anchor.SetSpeed(3.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    anchor.SetVelocity(TGPoint3(1.0, 0.0, 0.0))
    _arm(env)
    ship_motion.tick_all_ship_motion(DT)
    # The drifter really is drifting on its snapshot velocity.
    assert drifter._drift_velocity is not None
    assert _norm((drifter._velocity.x, drifter._velocity.y,
                  drifter._velocity.z)) > 2.9
    assert _accel(drifter) == (0.0, 0.0, 0.0)
    assert _accel(anchor) == (0.0, 0.0, 0.0)


# ── The manually flown player ────────────────────────────────────────────────

class _Keys:
    KEY_W = 87; KEY_S = 83; KEY_A = 65; KEY_D = 68; KEY_Q = 81; KEY_E = 69
    KEY_R = 82
    KEY_0 = 48; KEY_1 = 49; KEY_2 = 50; KEY_3 = 51; KEY_4 = 52
    KEY_5 = 53; KEY_6 = 54; KEY_7 = 55; KEY_8 = 56; KEY_9 = 57


class _Reader:
    keys = _Keys()

    def __init__(self):
        self.held = set()
        self.pressed_once = set()

    def key_state(self, key):
        return key in self.held

    def key_pressed(self, key):
        if key in self.pressed_once:
            self.pressed_once.discard(key)
            return True
        return False


def test_player_helm_records_controller_acceleration():
    """The helm (_PlayerControl) runs the law outside the motion stage; the
    stage then passes the setpoint-less player over and must leave the
    helm's acceleration standing (kernel M on)."""
    from engine.host_loop import _PlayerControl
    g = Game()
    _set_current_game(g)
    player = _ship("Player", _set())
    App.Game_SetCurrentPlayer(player)
    assert App.Game_GetCurrentPlayer() is player
    _arm(ON)
    assert nm.enabled()
    pc = _PlayerControl()
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_9)
    pc.apply(player, dt=DT, h=reader)
    mv = player._motion_vel
    assert mv is not None
    # From rest: the helm stepped from (0, 0, 0).
    want = ((mv[0] - 0.0) / DT, (mv[1] - 0.0) / DT, (mv[2] - 0.0) / DT)
    assert _norm(want) > 1.0
    assert _accel(player) == want
    ship_motion.tick_all_ship_motion(DT)
    assert nm.counts()["native_calls"] >= 1
    assert _accel(player) == want


def _helm_after_powered_tick(monkeypatch=None):
    """A manually flown player after one powered helm tick from rest: its
    acceleration is the helm's (nonzero)."""
    from engine.host_loop import _PlayerControl
    _set_current_game(Game())
    player = _ship("Player", _set())
    App.Game_SetCurrentPlayer(player)
    _arm(ON)
    pc = _PlayerControl()
    reader = _Reader()
    reader.pressed_once.add(reader.keys.KEY_9)
    pc.apply(player, dt=DT, h=reader)
    assert _norm(_accel(player)) > 1.0
    return player, pc, reader


def _then_stage_stays_zero(player):
    """The motion stage (kernel M on) passes the setpoint-less player over:
    the helm's zero stands."""
    assert _accel(player) == (0.0, 0.0, 0.0)
    ship_motion.tick_all_ship_motion(DT)
    assert _accel(player) == (0.0, 0.0, 0.0)


def test_player_helm_engines_out_drift_reports_zero():
    """The player's pods die mid-acceleration: the helm drifts it on
    inertia (no law), so its acceleration is zero, not the last thrust."""
    player, pc, reader = _helm_after_powered_tick()
    ies = player.GetImpulseEngineSubsystem()
    for i in range(ies.GetNumChildSubsystems()):
        ies.GetChildSubsystem(i)._condition = 0.0
    before = player.GetTranslate()
    pc.apply(player, dt=DT, h=reader)
    assert pc._drift_velocity is not None           # really drifting
    assert player.GetTranslate().x != before.x
    _then_stage_stays_zero(player)


def test_player_helm_warp_override_reports_zero():
    """The set-to-set warp burst (WarpVFX's speed override) moves the
    player without the law: zero."""
    player, pc, reader = _helm_after_powered_tick()
    pc._warp_speed_override = 5.0
    pc.apply(player, dt=DT, h=reader)
    _then_stage_stays_zero(player)


def test_player_helm_dash_reports_zero(monkeypatch):
    """A dash owns the ship (dash.tick flies it): the helm's own frame
    applies no law, so zero."""
    from engine.appc import dash
    player, pc, reader = _helm_after_powered_tick()
    monkeypatch.setattr(dash, "is_dashing", lambda s: s is player)
    pc.apply(player, dt=DT, h=reader)
    assert pc._dash_owned
    _then_stage_stays_zero(player)


# ── No zero write-backs ──────────────────────────────────────────────────────

def test_zero_acceleration_rows_append_no_write():
    """Kernel M: an acceleration equal to the mirror's is not written back,
    so after the first tick 3 setpoint-less drifters and 1 immobile ship
    append no entry at all."""
    pSet = _set()
    ships = []
    for i in range(3):
        s = _ship("Drifter%d" % i, pSet, pos=(0.01 * i, 0.0, 0.0),
                  engine=False)
        s.SetVelocity(TGPoint3(0.5, -0.25, 0.125 * i))
        s.SetAngularVelocity(TGPoint3(0.1, 0.05, 0.2), MODEL)
        ships.append(s)
    anchor = _ship("Anchor", pSet, pos=(0.3, 0.0, 0.0))
    anchor.SetStatic(1)
    anchor.SetSpeed(3.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    ships.append(anchor)
    handles = [s.__dict__["_nslot"] for s in ships]
    logs = []
    for _ in range(2):
        stop, at, reason, writes = _h.combat_motion_compute(
            handles, -1, DT, 0, False)
        assert (stop, at, nm.REASONS[reason]) == (nm.DONE, len(ships), "None")
        nm._apply_writes_py(ships, writes)
        logs.append(writes)
    # Tick 1: each row's zeros differ from the mirror's None.
    assert [w[1] for w in logs[0]] == [nm.K_ACCEL] * 4
    # Tick 2: nothing changed, nothing written.
    assert logs[1] == []
    for s in ships:
        assert s._acceleration == (0.0, 0.0, 0.0)
