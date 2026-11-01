"""A torpedo aimed at a PICKED spot keeps the launch-time point; a subsystem
lock keeps following its part (Mark's ruling, 2026-11-01; posed-parts spec
§10).

Articulation is a Dauntless feature, not BC, so this is our design. A
torpedo whose target offset no subsystem mount claims (a Manual Aim pick, an
AI's random hull offset) fixes its aim point when it is LAUNCHED: the offset
as posed at that moment (`articulation.part_transform_point(target, offset,
authored=False)`, the box rule), kept on the torpedo as a body-frame point.
In flight it is steered at `pos + R·(scale·baked)` -- following the ship's
position, rotation and scale -- but never re-posed: the wing moving after
launch does not drag the shot with it. An offset that IS a mount (a
subsystem lock) is not baked: it follows the subsystem's part every tick.

An unposed target's bake is the offset itself, so its steer point is
byte-identical to the old per-tick transform.
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


def test_a_picked_spot_keeps_its_launch_time_point(ships):
    bop = ships("BoP", "birdofprey", "ships.BirdOfPrey")
    articulation.force_pose(bop, "cruise")
    p = _wing_pick(bop)
    launched = articulation.part_transform_point(bop, p, authored=False)
    assert tuple(launched) != p             # the cruise pose moved the pick
    t = _launch(bop, TGPoint3(*p))
    # The wing moves BEFORE the first steer: the shot keeps the launch pose.
    articulation.force_pose(bop, None)
    got = _steer(t, bop)
    assert _hx(got) == _hx(_body_world(bop, launched))
    # Not the old per-tick rule (the wing's current pose).
    old = subsystems.target_offset_world(bop, TGPoint3(*p), None)
    assert _hx(got) != _hx(old)
    # Another pose later: still the launch point.
    articulation.force_pose(bop, "warp")
    assert _hx(_steer(t, bop)) == _hx(_body_world(bop, launched))


def test_a_picked_spot_still_follows_the_ship(ships):
    bop = ships("BoP", "birdofprey", "ships.BirdOfPrey")
    articulation.force_pose(bop, "cruise")
    p = _wing_pick(bop)
    launched = articulation.part_transform_point(bop, p, authored=False)
    t = _launch(bop, TGPoint3(*p))
    articulation.force_pose(bop, None)
    bop.SetTranslateXYZ(-300.0, 25.5, 70.0)
    m = TGMatrix3()
    m.MakeZRotation(1.1)
    bop.SetMatrixRotation(m)
    bop.SetScale(2.5)
    got = _steer(t, bop)
    assert _hx(got) == _hx(_body_world(bop, launched))


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


def test_a_new_offset_or_target_bakes_again(ships):
    bop = ships("BoP", "birdofprey", "ships.BirdOfPrey")
    other = ships("BoP2", "birdofprey", "ships.BirdOfPrey")
    articulation.force_pose(bop, "cruise")
    p = _wing_pick(bop)
    t = _launch(bop, TGPoint3(*p))
    # A script re-aims after the wing moved: baked at THAT moment.
    articulation.force_pose(bop, None)
    q = _wing_pick(bop, frac=(0.25, 0.5, 0.5))
    t.SetTargetOffset(TGPoint3(*q))
    now = articulation.part_transform_point(bop, q, authored=False)
    articulation.force_pose(bop, "cruise")
    assert _hx(_steer(t, bop)) == _hx(_body_world(bop, now))
    # A new target: baked against it on the next steer.
    articulation.force_pose(other, "cruise")
    t._target_ship = other
    want = articulation.part_transform_point(other, q, authored=False)
    assert tuple(want) != q
    assert _hx(_steer(t, other)) == _hx(_body_world(other, want))
    articulation.force_pose(other, None)
    assert _hx(_steer(t, other)) == _hx(_body_world(other, want))


def test_a_clear_offset_unbakes(ships):
    bop = ships("BoP", "birdofprey", "ships.BirdOfPrey")
    articulation.force_pose(bop, "cruise")
    t = _launch(bop, TGPoint3(*_wing_pick(bop)))
    assert t._baked_offset is not None
    t.SetTargetOffset(None)
    assert t._baked_offset is None
    pos = bop.GetWorldLocation()
    assert _hx(_steer(t, bop)) == _hx(pos)


def test_an_unposed_target_is_byte_identical(ships):
    """Galaxy (no rig): the bake is the offset itself and the steer point is
    the old target_offset_world, by .hex(), signed zeros and NaN included."""
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
        if not any(map(math.isnan, o)):
            assert tuple(t._baked_offset[4]) == o
        shift = rng.choice((None, (0.0, 0.0, 0.0), (100.0, -5.0, 0.25)))
        got = projectiles._steer_point(t, g, shift)
        want = projectiles._shifted(
            subsystems.target_offset_world(g, off, None), shift)
        assert _hx(got) == _hx(want), (i, o)
