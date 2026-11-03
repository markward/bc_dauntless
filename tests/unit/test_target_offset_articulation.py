"""A target offset on an articulated part is aimed where the part IS drawn.

A subsystem lock hands its REST mount to the weapons as a target-local offset
(`GetPositionTG()`; the SDK AI and MissionLib do the same via
`SetTargetOffset(pSubsystem.GetPosition())`). Three copies of the RE'd
0x005852A0 transform -- torpedo/pulse tube aim, torpedo in-flight steering,
Manual Aim phaser aim -- turned it into a world point with no articulation,
so a torpedo locked on a raised Bird of Prey wingtip flew at where the tip
would be wings-DOWN, ~0.9 ship units off.

`subsystems.target_offset_world` articulates an offset that IS a mount on
the way to world. Anything else -- a Manual Aim pick, stored as the posed
body point it hit -- is a plain body point (fire control native only, M5,
R5), so a pick lands on the picked point without any round trip.
"""
import math
import types

import pytest

from engine.appc import articulation
from engine.appc.math import TGMatrix3, TGPoint3

STAR_CANNON = (1.008, 0.450, -0.670)     # starboard wingtip, rest pose
TARGET_POS = (0.0, 100.0, 0.0)


class _Cannon:
    """The starboard wingtip cannon: its authored mount is STAR_CANNON."""

    def GetPosition(self): return TGPoint3(*STAR_CANNON)


class _BoP:
    """A Bird of Prey target with both wings at their cruise pose, carrying
    the starboard wingtip cannon (so STAR_CANNON is an authored mount)."""

    def __init__(self, wings_up=True, leaf="birdofprey"):
        from engine.appc import part_pose
        self._cannon = _Cannon()
        self._articulation_leaf = leaf
        self._articulation_poses = {
            p.GetName(): (p.pose_for("cruise") if wings_up
                          else part_pose.IDENTITY)
            for p in articulation.rig_for("birdofprey")
        }

    def _iter_subsystems(self): return [self._cannon]
    def GetWorldLocation(self): return TGPoint3(*TARGET_POS)
    def GetWorldRotation(self): return TGMatrix3()
    def GetScale(self):         return 1.0
    def IsDead(self):           return False


def _drawn(target, rest=STAR_CANNON):
    """Where `rest` is drawn on `target`, in world space."""
    p = articulation.part_transform_point(target, rest)
    return tuple(t + v for t, v in zip(TARGET_POS, p))


def _xyz(p):
    return (p.x, p.y, p.z)


def test_the_fixture_actually_moves_the_cannon():
    """Guard: without real articulation every test below is vacuous."""
    rest_world = tuple(t + v for t, v in zip(TARGET_POS, STAR_CANNON))
    assert math.dist(_drawn(_BoP()), rest_world) > 0.5


def test_a_torpedo_tube_aims_at_the_DRAWN_cannon():
    """The tube's aim point at a stored offset that IS a mount: the shared
    target_offset_world (K2's and K3's Python copies; the tube's own aim is
    the kernel's since fire control went native only, M3, checked against
    it by tests/helpers/posed_fight.py)."""
    from engine.appc.subsystems import target_offset_world
    aim = target_offset_world(_BoP(), TGPoint3(*STAR_CANNON))
    assert _xyz(aim) == pytest.approx(_drawn(_BoP()))


def test_a_torpedo_in_flight_steers_at_the_DRAWN_cannon():
    from engine.appc.projectiles import _steer_point
    torp = types.SimpleNamespace(_target_offset=TGPoint3(*STAR_CANNON))
    assert _xyz(_steer_point(torp, _BoP())) == pytest.approx(_drawn(_BoP()))


def test_wings_down_the_offset_resolves_exactly_as_before():
    from engine.appc.projectiles import _steer_point
    torp = types.SimpleNamespace(_target_offset=TGPoint3(*STAR_CANNON))
    got = _xyz(_steer_point(torp, _BoP(wings_up=False)))
    assert got == pytest.approx(tuple(t + v for t, v in zip(TARGET_POS, STAR_CANNON)))


def test_an_unrigged_target_is_unchanged():
    from engine.appc.projectiles import _steer_point
    torp = types.SimpleNamespace(_target_offset=TGPoint3(*STAR_CANNON))
    got = _xyz(_steer_point(torp, _BoP(leaf="galaxy")))
    assert got == pytest.approx(tuple(t + v for t, v in zip(TARGET_POS, STAR_CANNON)))


# ── Manual Aim: picked off the POSED hull, stored as hit, lands there ───────

class _Tcw:
    def GetMousePickFire(self): return 1


def _pick(target, picked_world):
    from engine import manual_aim
    from engine.appc.ships import ShipClass
    manual_aim.reset()
    player = ShipClass()
    player.SetTarget(target)
    cam = manual_aim.AimCamera(eye=(0.0, -20.0, 5.0), target=TARGET_POS,
                               up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(45.0),
                               near=1.0, far=5000.0)
    live = manual_aim.update(
        player=player, tcw=_Tcw(), ship_instances={target: 7}, is_exterior=True,
        cursor_fb=(400.0, 300.0), viewport_fb=(800, 600), cam=cam,
        ray_trace=lambda *a: (picked_world, (0.0, 0.0, 1.0), 50.0))
    assert live
    return player


def test_a_manual_pick_on_a_raised_wing_is_STORED_as_the_point_hit():
    """R5: no pull-back to the rest frame."""
    target = _BoP()
    picked = _drawn(target)
    player = _pick(target, picked)
    want = tuple(v - t for v, t in zip(picked, TARGET_POS))
    assert _xyz(player.GetTargetOffsetTG()) == pytest.approx(want)
    assert math.dist(want, STAR_CANNON) > 0.5


def test_a_manual_pick_on_a_raised_wing_is_AIMED_where_it_was_picked():
    """Phasers under Manual Aim go through the same helper: the stored pick
    is a plain body point, so it lands where it was picked."""
    from engine.host_loop import _phaser_aim_point
    target = _BoP()
    picked = _drawn(target)
    player = _pick(target, picked)
    aim, _sub = _phaser_aim_point(player, target)
    assert _xyz(aim) == pytest.approx(picked)
