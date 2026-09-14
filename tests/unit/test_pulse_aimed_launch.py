"""BC pulse-weapon launch: the targeted path solves an aimed, LED launch
direction; the arc is a pure fire/no-fire gate on that direction.

Behaviour (clean-room answer, 2026-09-14, read from the retail binary —
PulseWeapon vtable 0x00893318 slots +0x7C targeted / +0x80 no-target):

  aim      = target centre + local aim offset (rotated, scaled)  [0x005852A0]
  muzzle   = ship pos + mount offset rotated by ship orientation
  v_eff    = launchSpeed + (shipVel - targetVel) . unit(aim - muzzle)
  t        = |aim - muzzle| / v_eff
  pred     = aim + targetVel*t + 0.5*targetAccel*t^2 - shipVel*t   [0x005A0B50]
  dir      = unit(pred - muzzle)
  refuse if v_eff <= 0, t <= 0, t > module GetLifetime() (default 8),
            |pred - muzzle| > 30 * v_eff, or dir outside the authored arc
  velocity = dir * module GetLaunchSpeed() + shipVel

With no target on the weapon OR its ship the bolt leaves along the cannon's
OrientationForward (slot +0x80).  Every stock pulse module authors
GuidanceLifetime 0.0, so whatever direction the bolt leaves with is final —
this launch solve IS the disruptor's whole targeting.
"""
import math

import pytest

from engine.appc.math import TGPoint3


BOP_ARC_HALF = 0.436332          # birdofprey.py PortCannon: +/-25 degrees
PULSE_SPEED = 55.0               # Tactical/Projectiles/PulseDisruptor.py
PULSE_LIFETIME = 8.0


def _unit(v):
    n = v.Length()
    return TGPoint3(v.x / n, v.y / n, v.z / n)


def _angle_deg(a, b):
    ua, ub = _unit(a), _unit(b)
    return math.degrees(math.acos(max(-1.0, min(1.0, ua.Dot(ub)))))


def _cannon_ship(forward=(0.0, 1.0, 0.0)):
    """A ship with one PulseWeaponSystem holding one BoP-style cannon."""
    import App
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import PulseWeaponSystem, PulseWeapon

    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)

    prop = App.PulseWeaponProperty_Create("Port Cannon")
    prop.SetPosition(-1.009, 0.45, -0.67)
    prop.SetMaxCharge(3.8)
    prop.SetMinFiringCharge(3.6)
    prop.SetRechargeRate(0.4)
    prop.SetMaxDamage(200.0)
    prop.SetMaxDamageDistance(100.0)
    fwd = App.TGPoint3(); fwd.SetXYZ(*forward)
    up = App.TGPoint3(); up.SetXYZ(0.0, 0.0, 1.0)
    prop.SetOrientation(fwd, up)
    prop.SetArcWidthAngles(-BOP_ARC_HALF, BOP_ARC_HALF)
    prop.SetArcHeightAngles(-BOP_ARC_HALF, BOP_ARC_HALF)
    prop.SetCooldownTime(0.2)
    prop.SetModuleName("Tactical.Projectiles.PulseDisruptor")

    sys_ = PulseWeaponSystem("Pulse")
    sys_._max_condition = 100.0
    sys_._condition = 100.0
    sys_._disabled_percentage = 0.75
    sys_.TurnOn()
    cannon = PulseWeapon("Port Cannon")
    cannon.SetProperty(prop)
    cannon._max_charge = 3.8
    cannon._charge_level = 3.8
    cannon._min_firing_charge = 3.6
    cannon._max_condition = 600.0
    cannon._condition = 600.0
    cannon._disabled_percentage = 0.75
    sys_.AddChildSubsystem(cannon)
    ship.SetPulseWeaponSystem(sys_)
    return ship, sys_, cannon


def _target_at(x, y, z, vel=(0.0, 0.0, 0.0)):
    from engine.appc.ships import ShipClass
    t = ShipClass()
    t.SetTranslateXYZ(x, y, z)
    t.SetVelocity(TGPoint3(*vel))
    return t


def _fire(cannon, target, offset=None):
    from engine.appc import projectiles
    before = len(projectiles._active)
    ok = cannon.Fire(target, offset if offset is not None else TGPoint3(0, 0, 0))
    spawned = projectiles._active[before:]
    return ok, (spawned[-1] if spawned else None)


def _muzzle(cannon):
    return cannon._emitter_world_position()


# ── Targeted path (slot +0x7C) ──────────────────────────────────────────────

def test_targeted_bolt_launches_from_muzzle_toward_a_stationary_target():
    ship, _, cannon = _cannon_ship()
    ang = math.radians(20.0)                          # inside the +/-25 arc
    target = _target_at(100.0 * math.sin(ang), 100.0 * math.cos(ang), 0.0)

    ok, bolt = _fire(cannon, target)

    assert ok and bolt is not None
    to_target = target.GetWorldLocation() - _muzzle(cannon)
    assert _angle_deg(bolt._velocity, to_target) < 0.1
    assert bolt._velocity.Length() == pytest.approx(PULSE_SPEED, abs=1e-6)


def test_targeted_bolt_leads_a_crossing_target():
    """The launch direction is BC's single-pass intercept solve (t from the
    CURRENT aim point, closing-speed adjusted; not iterated), and flying the
    unguided bolt straight must bring it within a hull's width of where the
    target WILL be -- not where it was."""
    ship, _, cannon = _cannon_ship()
    target = _target_at(0.0, 100.0, 0.0, vel=(6.0, 0.0, 0.0))   # crossing

    ok, bolt = _fire(cannon, target)

    assert ok and bolt is not None
    aim = target.GetWorldLocation()
    muzzle = _muzzle(cannon)
    u = _unit(aim - muzzle)
    v_eff = PULSE_SPEED + (TGPoint3(0, 0, 0) - target.GetVelocityTG()).Dot(u)
    t = (aim - muzzle).Length() / v_eff
    predicted = TGPoint3(aim.x + 6.0 * t, aim.y, aim.z)
    assert _angle_deg(bolt._velocity, predicted - muzzle) < 0.1
    # Physical check: closest approach of the straight-flying bolt to the
    # moving target, minimised over time.
    rel_v = bolt._velocity - target.GetVelocityTG()
    rel_p = muzzle - aim
    s = -rel_p.Dot(rel_v) / rel_v.Dot(rel_v)
    miss = TGPoint3(rel_p.x + rel_v.x * s, rel_p.y + rel_v.y * s,
                    rel_p.z + rel_v.z * s).Length()
    assert 1.5 < s < 2.5                          # ~1.8 s of flight
    assert miss < 1.0                             # a BoP is ~3 GU across
    # And it is genuinely a lead: not the line to the current position.
    assert _angle_deg(bolt._velocity, aim - muzzle) > 3.0


def test_aim_point_includes_the_local_subsystem_offset():
    ship, _, cannon = _cannon_ship()
    target = _target_at(0.0, 100.0, 0.0)
    offset = TGPoint3(0.0, 0.0, 10.0)                # e.g. a dorsal subsystem

    ok, bolt = _fire(cannon, target, offset)

    assert ok and bolt is not None
    aim = target.GetWorldLocation()
    aim = TGPoint3(aim.x, aim.y, aim.z + 10.0)       # identity rotation, scale 1
    assert _angle_deg(bolt._velocity, aim - _muzzle(cannon)) < 0.1


def test_bolt_inherits_the_firing_ships_velocity():
    ship, _, cannon = _cannon_ship()
    ship.SetVelocity(TGPoint3(0.0, 4.0, 0.0))
    target = _target_at(0.0, 100.0, 0.0)

    ok, bolt = _fire(cannon, target)

    assert ok and bolt is not None
    rel = bolt._velocity - ship.GetVelocityTG()
    assert rel.Length() == pytest.approx(PULSE_SPEED, abs=1e-6)


def test_targeted_fire_stamps_target_and_offset_on_the_bolt():
    ship, _, cannon = _cannon_ship()
    target = _target_at(0.0, 100.0, 0.0)
    offset = TGPoint3(1.0, 2.0, 3.0)

    ok, bolt = _fire(cannon, target, offset)

    assert ok and bolt is not None
    assert bolt.GetTargetID() == target.GetObjID()
    assert (bolt._target_offset.x, bolt._target_offset.y, bolt._target_offset.z) == (1.0, 2.0, 3.0)


# ── Fire/no-fire gates ──────────────────────────────────────────────────────

def test_fire_refused_when_time_of_flight_exceeds_module_lifetime():
    ship, _, cannon = _cannon_ship()
    target = _target_at(0.0, PULSE_SPEED * PULSE_LIFETIME + 20.0, 0.0)

    ok, bolt = _fire(cannon, target)

    assert not ok and bolt is None
    assert cannon._charge_level == 3.8               # nothing was spent


def test_fire_refused_when_target_outruns_the_bolt():
    ship, _, cannon = _cannon_ship()
    target = _target_at(0.0, 100.0, 0.0, vel=(0.0, PULSE_SPEED + 5.0, 0.0))

    ok, bolt = _fire(cannon, target)

    assert not ok and bolt is None


def test_arc_gate_applies_to_the_led_direction_not_the_current_bearing():
    """Target sits INSIDE the arc now, but its predicted position is outside
    it: BC tests the solved launch direction, so the shot is refused."""
    ship, _, cannon = _cannon_ship()
    ang = math.radians(22.0)
    target = _target_at(100.0 * math.sin(ang), 100.0 * math.cos(ang), 0.0,
                        vel=(6.0, 0.0, 0.0))            # drifting outward

    ok, bolt = _fire(cannon, target)

    assert not ok and bolt is None


# ── No-target path (slot +0x80) ─────────────────────────────────────────────

def test_no_target_anywhere_fires_along_the_cannons_orientation_forward():
    ship, _, cannon = _cannon_ship(forward=(0.0, 0.8, 0.6))
    ship.SetTarget(None)

    ok, bolt = _fire(cannon, None)

    assert ok and bolt is not None
    assert _angle_deg(bolt._velocity, TGPoint3(0.0, 0.8, 0.6)) < 1e-6
    assert bolt._target_ship is None


def test_weapon_without_target_falls_back_to_the_ships_current_target():
    ship, _, cannon = _cannon_ship()
    ang = math.radians(15.0)
    target = _target_at(100.0 * math.sin(ang), 100.0 * math.cos(ang), 0.0)
    ship.SetTarget(target)

    ok, bolt = _fire(cannon, None)

    assert ok and bolt is not None
    to_target = target.GetWorldLocation() - _muzzle(cannon)
    assert _angle_deg(bolt._velocity, to_target) < 0.1


# ── Through the system tick (the path the SDK's StartFiring drives) ─────────

def test_start_firing_threads_target_and_offset_to_the_launch_solve():
    from engine.appc import projectiles
    ship, sys_, cannon = _cannon_ship()
    target = _target_at(0.0, 100.0, 0.0)
    offset = TGPoint3(0.0, 0.0, 10.0)

    before = len(projectiles._active)
    sys_.StartFiring(target, offset)
    spawned = projectiles._active[before:]

    assert len(spawned) == 1
    aim = target.GetWorldLocation()
    aim = TGPoint3(aim.x, aim.y, aim.z + 10.0)
    assert _angle_deg(spawned[0]._velocity, aim - _muzzle(cannon)) < 0.1


# ── ShipClass.GetTargetOffsetTG (was a heatmap stub, rank 21) ───────────────

def test_ship_target_offset_is_the_locked_subsystems_local_position():
    """SDK TacticalInterfaceHandlers.py:362 hands this straight to
    StartFiring as the aim offset; MissionLib.py:3245 and the AI both build
    the same offset from pSubsystem.GetPosition()."""
    from engine.appc.ships import ShipClass
    from engine.appc.subsystems import ShipSubsystem
    ship = ShipClass()
    sub = ShipSubsystem("Warp Core")
    sub.SetPosition(0.5, -2.0, 1.5) if hasattr(sub, "SetPosition") else None
    sub._position = TGPoint3(0.5, -2.0, 1.5)
    ship.SetTargetSubsystem(sub)

    o = ship.GetTargetOffsetTG()

    assert isinstance(o, TGPoint3)
    assert (o.x, o.y, o.z) == (0.5, -2.0, 1.5)


def test_ship_target_offset_is_zero_without_a_subsystem_lock():
    from engine.appc.ships import ShipClass
    ship = ShipClass()

    o = ship.GetTargetOffsetTG()

    assert isinstance(o, TGPoint3)
    assert (o.x, o.y, o.z) == (0.0, 0.0, 0.0)
