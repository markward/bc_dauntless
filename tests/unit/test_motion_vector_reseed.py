"""The motion law's velocity vector stays honest across hand-offs.

``ship_motion.step_vector_velocity`` keeps the world velocity in
``ship._motion_vel`` and trusts it only while ``current_speed`` equals its
``[3]`` (the re-seed contract). Two holes the final review found:

* every motion owner that is not the law (an in-system warp flight, a
  set-to-set arrival, a dash) left the PRE-warp vector standing with its
  speed unchanged, so the law resumed it after the drop-out while the nose
  pointed along the drop-out path. Each such exit invalidates the vector
  (``_motion_vel = None`` through the descriptor, so kernel M's mirror sees
  it too) and the law re-seeds along the nose;
* taking the helm from the AI seeded the helm's speed from the velocity
  projected on the nose, |v| cos(lag) != ``_motion_vel[3]``, so the vector
  re-seeded along the nose and a turning ship's sideways velocity vanished.
  The helm now resumes the vector's own speed.

Stage scenes run with kernel M on (``{}``) and off (the Python reference).
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
MODEL = 0
ON, OFF = {}, {"DAUNTLESS_NATIVE_MOTION": "0"}
ARMS = pytest.mark.parametrize("env", [ON, OFF], ids=["native", "python"])
MAX_ACCEL = 1.5


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


def _set(name="S"):
    pSet = App.SetClass_Create()
    pSet.SetName(name)
    App.g_kSetManager._sets[name] = pSet
    return pSet


def _engine(ship):
    """Galaxy-like limits: MaxSpeed 6.3, MaxAccel 1.5, turn 0.28 rad/s."""
    ies = ImpulseEngineSubsystem("Impulse Engines")
    ship.SetImpulseEngineSubsystem(ies)
    ies._max_condition = 100.0
    ies._condition = 100.0
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(MAX_ACCEL)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    ies.TurnOn()
    for i in range(3):
        pod = ShipSubsystem("pod%d" % i)
        pod.SetMaxCondition(2600.0)
        ies.AddChildSubsystem(pod)
    return ies


def _ship(name, pSet, pos=(0.0, 0.0, 0.0), engine=True):
    ship = ShipClass()
    ship.SetName(name)
    if engine:
        _engine(ship)
    ship.SetTranslateXYZ(*pos)
    pSet.AddObjectToSet(ship, name)
    return ship


def _arm(env):
    nm.reset()
    nm.configure(env)


def _vec(p):
    return (p.x, p.y, p.z)


def _norm(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _angle_deg(a, b):
    c = (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (_norm(a) * _norm(b))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _nose(ship):
    return _vec(ship.GetWorldRotation().GetCol(1))


def _mirrored_motion_vel(ship):
    """Kernel M's mirror of ``_motion_vel`` ([] for None)."""
    return list(_h.combat_dump(ship.__dict__["_nslot"])["_motion_vel"])


def _cruise(ship, seconds=8.0):
    """Full impulse along the nose (+Y) until the vector is the target."""
    ship.SetImpulse(1.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    for _ in range(int(seconds * 60)):
        ship_motion.tick_all_ship_motion(DT)
    assert ship._current_speed > 6.0
    assert _angle_deg(_vec(ship.GetVelocity()), (0.0, 1.0, 0.0)) < 1e-6


# ── Finding 1: drop-outs re-seed the vector along the nose ──────────────────

@ARMS
def test_in_system_warp_drop_out_follows_the_drop_out_heading(env):
    """An AI in-system warp ends on a new heading (the target moved off the
    nose while the flight tracked it): the next tick's velocity follows the
    nose, not the pre-warp vector."""
    pSet = _set()
    ship = _ship("Galaxy", pSet)
    target = _ship("Target", pSet, pos=(0.0, 3000.0, 0.0), engine=False)
    _arm(env)
    _cruise(ship)
    assert ship.InSystemWarp(target, 295.0) == 1
    # The target moves off the nose; the flight turns the ship onto it.
    target.SetTranslateXYZ(3000.0, 0.0, 0.0)
    for _ in range(60 * 60):
        if ship._insystem_warp_transit is None:
            break
        ship_motion.tick_all_ship_motion(DT)
    assert ship._insystem_warp_transit is None, "flight never dropped out"
    assert ship._motion_vel is None and _mirrored_motion_vel(ship) == []
    nose = _nose(ship)
    assert _angle_deg(nose, (0.0, 1.0, 0.0)) > 45.0, "heading did not change"
    ship_motion.tick_all_ship_motion(DT)
    v = _vec(ship.GetVelocity())
    assert _norm(v) > 6.0
    assert _angle_deg(v, nose) < 1e-6, (
        "the law resumed the pre-warp vector: velocity %r, nose %r" % (v, nose))


@ARMS
def test_set_to_set_arrival_follows_the_placement_heading(env):
    """A set-to-set warp places the ship on the placement's heading at zero
    velocity: the next tick's velocity follows the new nose."""
    from engine.appc.warp import _PlacePlayerAction
    src = _set("Src")
    ship = _ship("Galaxy", src)
    _set("Dest")
    _arm(env)
    _cruise(ship)
    R = TGMatrix3()
    R.MakeZRotation(-math.pi / 2.0)         # nose +Y -> +X

    def _place(_name):
        ship.SetMatrixRotation(R)
        ship.SetTranslateXYZ(100.0, 200.0, 0.0)
    ship.PlaceObjectByName = _place
    _PlacePlayerAction(ship, "Dest", "Arrival")._do_play()
    v0 = _vec(ship.GetVelocity())
    assert v0 == (0.0, 0.0, 0.0)
    assert ship._motion_vel is None and _mirrored_motion_vel(ship) == []
    nose = _nose(ship)
    assert _angle_deg(nose, (1.0, 0.0, 0.0)) < 1e-6
    ship_motion.tick_all_ship_motion(DT)
    v = _vec(ship.GetVelocity())
    assert _norm(v) > 0.0
    assert _angle_deg(v, nose) < 1e-6, (
        "the law resumed the pre-warp vector: velocity %r, nose %r" % (v, nose))


# ── Finding 2: taking the helm keeps the vector ─────────────────────────────

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


def _player(env):
    from engine.host_loop import _PlayerControl
    _set_current_game(Game())
    player = _ship("Player", _set())
    App.Game_SetCurrentPlayer(player)
    _arm(env)
    return player, _PlayerControl(), _Reader()


@ARMS
def test_taking_the_helm_mid_turn_keeps_the_velocity_vector(env):
    """The AI turns the player at full impulse, so the course lags the nose;
    the AI lets go and the helm resumes: one helm tick moves the velocity by
    no more than one law step (MaxAccel x dt) -- no snap onto the nose."""
    player, pc, reader = _player(env)
    player.SetAI(object())
    pc.apply(player, dt=DT, h=reader)            # the AI has the conn
    assert pc._ai_owned
    player.SetImpulse(1.0, TGPoint3(0.0, 1.0, 0.0), MODEL)
    player.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.28))
    for _ in range(20 * 60):
        ship_motion.tick_all_ship_motion(DT)
    v0 = _vec(player.GetVelocity())
    lag = _angle_deg(v0, _nose(player))
    assert lag > 10.0, "the course should lag the nose in the turn (%r)" % lag
    player.ClearAI()                             # the order ends
    pc.apply(player, dt=DT, h=reader)
    assert not pc._ai_owned
    v1 = _vec(player.GetVelocity())
    dv = _norm((v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]))
    assert dv <= MAX_ACCEL * DT + 1e-9, (
        "the helm snapped the course: |dv| %r > one law step %r (v0 %r, v1 %r)"
        % (dv, MAX_ACCEL * DT, v0, v1))


@ARMS
def test_cancelled_dash_does_not_resume_the_pre_dash_vector(env, monkeypatch):
    """A dash holds the ship at rest while it swings onto the path (its
    align); cancelled there, the helm resumes from rest along the new nose,
    not from the vector the helm flew before the dash."""
    from engine.appc import dash
    player, pc, reader = _player(env)
    reader.pressed_once.add(reader.keys.KEY_9)
    for _ in range(8 * 60):
        pc.apply(player, dt=DT, h=reader)
    assert _norm(_vec(player.GetVelocity())) > 6.0
    dashing = [True]
    monkeypatch.setattr(dash, "is_dashing", lambda s: dashing[0] and s is player)
    pc.apply(player, dt=DT, h=reader)            # the dash has the ship
    # Its align: held at rest, swung onto the path.
    R = TGMatrix3()
    R.MakeZRotation(-math.pi / 2.0)
    player.SetMatrixRotation(R)
    player.SetVelocity(TGPoint3(0.0, 0.0, 0.0))
    dashing[0] = False                           # cancelled during the align
    pc.apply(player, dt=DT, h=reader)
    v = _vec(player.GetVelocity())
    assert _norm(v) <= MAX_ACCEL * DT + 1e-9, (
        "the helm resumed the pre-dash vector: %r" % (v,))


def test_warp_burst_drops_the_helm_vector():
    """The set-to-set warp burst (WarpVFX's speed override) flies the player
    without the law: the vector is dropped, in the mirror too, so a burst
    that ends at the cruise speed cannot resume the pre-warp course."""
    player, pc, reader = _player(ON)
    reader.pressed_once.add(reader.keys.KEY_9)
    for _ in range(8 * 60):
        pc.apply(player, dt=DT, h=reader)
    cruise = player._motion_vel[3]
    assert cruise > 6.0
    pc._warp_speed_override = 0.0                # the tunnel's align
    R = TGMatrix3()
    R.MakeZRotation(-math.pi / 2.0)
    player.SetMatrixRotation(R)
    pc.apply(player, dt=DT, h=reader)
    assert player._motion_vel is None and _mirrored_motion_vel(player) == []
    pc._warp_speed_override = cruise             # a burst at that speed
    pc.apply(player, dt=DT, h=reader)
    pc._warp_speed_override = None
    pc.apply(player, dt=DT, h=reader)
    v = _vec(player.GetVelocity())
    assert _angle_deg(v, _nose(player)) < 1e-6, (
        "the helm resumed the pre-warp vector: %r" % (v,))
