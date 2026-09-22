"""A guided torpedo steers to the AIMED SUBSYSTEM, not the hull centre.

BC stamps a target-local aim offset on the torpedo itself
(`Torpedo.SetTargetOffset`, App.py:5931, torp+0x11C..+0x124) and MissionLib
passes the aimed subsystem's local position into it (MissionLib.py:3245).
An offset carried by a guided projectile is a steering target: the tube's
own copy is only a fire-cone gate, so the torpedo is where it has to be
read while the shot is in flight.

Live report: torpedoes stopped steering to the locked subsystem. They were
homing on `target.GetWorldLocation()` and never reading the offset they
carry, so the locked subsystem took damage only when it happened to fall
inside the splash radius of a hit at the hull centre.
"""
import math

import pytest

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc import projectiles


class _FakeTarget:
    """A ship 100 GU ahead whose local +Z is world +Z (identity rotation)."""
    def __init__(self, x=0.0, y=100.0, z=0.0, scale=1.0):
        self._loc = TGPoint3(x, y, z)
        self._rot = TGMatrix3()
        self._scale = scale

    def GetWorldLocation(self):  return self._loc
    def GetWorldRotation(self):  return self._rot
    def GetScale(self):          return self._scale
    def GetVelocityTG(self):     return TGPoint3(0.0, 0.0, 0.0)
    def IsDead(self):            return 0
    def GetName(self):           return "Target"


def _torpedo_flying_at(target, offset=None, speed=20.0):
    """A torpedo 100 GU short of the target, flying straight at its centre,
    with plenty of guidance left."""
    t = projectiles.Torpedo()
    t.SetTranslateXYZ(0.0, 0.0, 0.0)
    t._velocity = TGPoint3(0.0, speed, 0.0)
    t._target_ship = target
    t._guidance_lifetime = 10.0
    t._guidance_initial = 10.0
    t._age = 0.0
    t._max_angular_accel = 5.0          # generous turn budget
    if offset is not None:
        t.SetTargetOffset(offset)
    return t


def _settle(torpedo, ticks=30):
    """Guide for half a second. The turn is budget-limited per step
    (max_angular_accel × dt), so a bearing change takes a few ticks; the
    torpedo does not move here, so it converges on the true bearing."""
    for _ in range(ticks):
        projectiles._guide(torpedo, dt=1.0 / 60)


def _aim_elevation_deg(torpedo):
    """Angle of the torpedo's velocity above the XY plane."""
    v = torpedo._velocity
    return math.degrees(math.atan2(v.z, math.hypot(v.x, v.y)))


def test_a_torpedo_with_an_aim_offset_steers_to_the_subsystem():
    """The offset is a point in the TARGET's frame: a subsystem 10 GU above
    the hull centre must pull the torpedo's nose up."""
    target = _FakeTarget()
    t = _torpedo_flying_at(target, offset=TGPoint3(0.0, 0.0, 10.0))
    _settle(t)
    # 10 GU up at 100 GU out ≈ 5.7°.
    assert _aim_elevation_deg(t) == pytest.approx(5.71, abs=0.5)


def test_a_torpedo_with_no_aim_offset_still_steers_to_the_centre():
    target = _FakeTarget()
    t = _torpedo_flying_at(target, offset=None)
    _settle(t)
    assert _aim_elevation_deg(t) == pytest.approx(0.0, abs=0.01)


def test_the_aim_offset_is_expressed_in_the_targets_own_frame():
    """A target rolled 90° about its forward axis carries its subsystems
    round with it: the same local +Z offset must now pull the torpedo to
    the side, not up."""
    target = _FakeTarget()
    r = TGMatrix3()
    r.SetCol(0, TGPoint3(0.0, 0.0, -1.0))   # right  -> world -Z
    r.SetCol(1, TGPoint3(0.0, 1.0, 0.0))    # forward-> world +Y
    r.SetCol(2, TGPoint3(1.0, 0.0, 0.0))    # up     -> world +X
    target._rot = r
    t = _torpedo_flying_at(target, offset=TGPoint3(0.0, 0.0, 10.0))
    _settle(t)
    assert _aim_elevation_deg(t) == pytest.approx(0.0, abs=0.5)
    assert t._velocity.x > 0.5              # pulled toward world +X


def test_the_offset_is_scaled_by_the_targets_scale():
    """Subsystem positions are model-local; the target's scale converts them
    (the same transform the tube's fire-cone gate applies)."""
    target = _FakeTarget(scale=2.0)
    t = _torpedo_flying_at(target, offset=TGPoint3(0.0, 0.0, 10.0))
    _settle(t)
    assert _aim_elevation_deg(t) == pytest.approx(11.31, abs=0.5)   # 20 GU up
