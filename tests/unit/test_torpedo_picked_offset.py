"""A torpedo aimed at a PICKED spot steers at that body-frame point for its
whole flight; a subsystem lock keeps following its part (fire control
native only, M5 and R5: "we dont need torpedoes to track articulated parts
moving mid flight").

Articulation is a Dauntless feature, not BC, so this is our design. A
torpedo whose target offset no subsystem mount claims (a Manual Aim pick, an
AI's random hull offset) is steered at `pos + R·(scale·offset)` --
following the ship's position, rotation and scale -- and never posed: there
is no launch-time bake, and the wing moving before or after launch does not
move the shot's aim. An offset that IS a mount (a subsystem lock) follows
the subsystem's part every tick.

An unposed target's steer point is the old per-tick transform, byte for
byte.
"""
import importlib
import math
import random
import sys

import pytest

import App

from engine.appc import articulation
from engine.appc import part_severance
from engine.appc import projectiles
from engine.appc import subsystems
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.projectiles import Torpedo


def _load_hardpoint(ship, name):
    mod_name = "ships.Hardpoints." + name
    App.g_kModelPropertyManager.ClearLocalTemplates()
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    sys.modules[mod_name].LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()


@pytest.fixture
def ships():
    made = {}

    def make(name, hardpoint, script):
        ship = App.ShipClass_Create(name)
        ship.SetScript(script)
        _load_hardpoint(ship, hardpoint)
        ship.SetTranslateXYZ(10.0, 40.0, 8.0)
        made[name] = ship
        return ship

    yield make
    App.g_kModelPropertyManager.ClearLocalTemplates()


def _hx(p):
    return tuple(float(c).hex() for c in (p.x, p.y, p.z))


def _wing_pick(bop, part="left wing", frac=(0.5, 0.5, 0.5)):
    """A point inside the wing's box the box rule gives to that wing, and
    no subsystem's mount."""
    lo, hi = articulation.part_boxes_for("birdofprey")[part]
    p = tuple(a + f * (b - a) for a, b, f in zip(lo, hi, frac))
    assert articulation._live_part(bop, None, p, False, None) == part, p
    assert part_severance.authored_mount_subsystem(bop, p) is None, p
    return p


def _wing_cannon(bop):
    """A disruptor cannon whose mount rides a wing (moves with the pose)."""
    from engine.appc import physical_parents
    cannons = bop.GetPulseWeaponSystem()
    for i in range(cannons.GetNumChildSubsystems()):
        c = cannons.GetWeapon(i)
        p = c.GetPosition()
        q = articulation.part_transform_point(
            bop, (p.x, p.y, p.z), prop=physical_parents.property_of(c))
        if tuple(q) != (p.x, p.y, p.z):
            return c
    raise AssertionError("no wing cannon moved in this pose")


def _body_world(target, point):
    """pos + R·(scale·point), in _steer_point's operand order."""
    pos = target.GetWorldLocation()
    s = float(target.GetScale())
    o = TGPoint3(point[0] * s, point[1] * s, point[2] * s)
    o.MultMatrixLeft(target.GetWorldRotation())
    return TGPoint3(pos.x + o.x, pos.y + o.y, pos.z + o.z)


def _launch(target, offset):
    """What the tube's spawn does: target first, then the offset."""
    t = Torpedo()
    t._target_ship = target
    t.SetTargetOffset(offset)
    return t


def _steer(t, target):
    return projectiles._steer_point(t, target)


def test_torpedo_at_pick_steers_to_body_point_all_flight(ships):
    bop = ships("BoP", "birdofprey", "ships.BirdOfPrey")
    articulation.force_pose(bop, "cruise")
    p = _wing_pick(bop)
    # The cruise pose would move the pick (the old launch-time bake).
    assert tuple(articulation.part_transform_point(
        bop, p, authored=False)) != p
    t = _launch(bop, TGPoint3(*p))
    assert _hx(_steer(t, bop)) == _hx(_body_world(bop, p))
    # The wing moves mid flight: the aim does not.
    for pose in (None, "warp", "cruise"):
        articulation.force_pose(bop, pose)
        assert _hx(_steer(t, bop)) == _hx(_body_world(bop, p)), pose
    # It still follows the ship's position, rotation and scale.
    bop.SetTranslateXYZ(-300.0, 25.5, 70.0)
    m = TGMatrix3()
    m.MakeZRotation(1.1)
    bop.SetMatrixRotation(m)
    bop.SetScale(2.5)
    assert _hx(_steer(t, bop)) == _hx(_body_world(bop, p))
    # The one transform: target_offset_world gives the same point.
    assert _hx(_steer(t, bop)) == _hx(subsystems.target_offset_world(
        bop, TGPoint3(*p)))
    assert "_baked_offset" not in vars(Torpedo)      # no bake to keep


def test_a_subsystem_lock_still_follows_the_wing(ships):
    bop = ships("BoP", "birdofprey", "ships.BirdOfPrey")
    articulation.force_pose(bop, "cruise")
    cannon = _wing_cannon(bop)
    off = cannon.GetPosition()
    t = _launch(bop, TGPoint3(off.x, off.y, off.z))
    at_launch = _steer(t, bop)
    articulation.force_pose(bop, None)
    got = _steer(t, bop)
    assert t._mount_key[4] is cannon
    assert _hx(got) == _hx(subsystems.target_offset_world(
        bop, TGPoint3(off.x, off.y, off.z), cannon))
    assert _hx(got) != _hx(at_launch)       # it followed the wing


def test_a_clear_offset_steers_at_the_centre(ships):
    bop = ships("BoP", "birdofprey", "ships.BirdOfPrey")
    articulation.force_pose(bop, "cruise")
    t = _launch(bop, TGPoint3(*_wing_pick(bop)))
    t.SetTargetOffset(None)
    pos = bop.GetWorldLocation()
    assert _hx(_steer(t, bop)) == _hx(pos)


def test_an_unposed_target_is_byte_identical(ships):
    """Galaxy (no rig): the steer point is target_offset_world, by .hex(),
    signed zeros and NaN included."""
    g = ships("Galaxy", "galaxy", "ships.Galaxy")
    rng = random.Random(7071)
    nan = float("nan")
    for i in range(400):
        g.SetTranslateXYZ(*(rng.uniform(-500.0, 500.0) for _ in range(3)))
        m = TGMatrix3()
        if i % 3:
            m.MakeZRotation(rng.uniform(-math.pi, math.pi))
        g.SetMatrixRotation(m)
        g.SetScale(rng.choice((1.0, rng.uniform(0.1, 5.0), 0.0)))
        o = rng.choice(((0.0, 0.0, 0.0), (-0.0, 0.0, -0.0), (nan, 1.0, 2.0),
                        tuple(rng.uniform(-3.0, 3.0) for _ in range(3))))
        off = TGPoint3(*o)
        t = _launch(g, off)
        shift = rng.choice((None, (0.0, 0.0, 0.0), (100.0, -5.0, 0.25)))
        got = projectiles._steer_point(t, g, shift)
        want = projectiles._shifted(
            subsystems.target_offset_world(g, off, None), shift)
        assert _hx(got) == _hx(want), (i, o)
