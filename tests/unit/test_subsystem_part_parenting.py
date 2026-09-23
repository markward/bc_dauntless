"""A subsystem mounted on an articulated part must move with that part.

THE LIVE BUG THIS FIXES: a Bird of Prey's Port/Star Cannon are authored at
(±1.008, 0.450, -0.670) — measured to be on the wingtips. The mount was
computed against the model's REST pose, so with the wings raised the beam
fired from ~0.9 ship units (~150 m) away from the drawn gun.

Normally hidden, because wings-up ⟺ weapons cold. But entering RED alert
powers weapons instantly while the wings take 2 s to come down, so the
cannons fire from progressively wrong positions for those two seconds —
exactly when combat starts.
"""
import math

import pytest

from engine.appc.articulation import part_transform_point
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.subsystems import subsystem_world_position


class _Sub:
    def __init__(self, pos):
        self._p = TGPoint3(*pos)

    def GetPosition(self):
        return self._p

    def _climb_to_ship(self):
        return None


class _Ship:
    """Identity rotation at the origin, so world == body and the assertions
    read as the body-frame offsets they are."""

    def __init__(self, deflection, leaf="birdofprey"):
        self._articulation_leaf = leaf
        self._d = deflection

    def GetArticulationDeflection(self):
        return self._d

    def GetWorldLocation(self):
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        return TGMatrix3()


STAR_CANNON = (1.008, 0.450, -0.670)


def test_at_rest_the_mount_is_unchanged():
    w = subsystem_world_position(_Sub(STAR_CANNON), _Ship(0.0))
    assert (w.x, w.y, w.z) == pytest.approx(STAR_CANNON)


def test_with_the_wings_up_the_cannon_follows_the_wing():
    w = subsystem_world_position(_Sub(STAR_CANNON), _Ship(1.0))
    assert w.z > STAR_CANNON[2], "the cannon must rise with the wing"
    moved = math.dist((w.x, w.y, w.z), STAR_CANNON)
    assert moved > 0.5, "this is the ~150 m error the fix removes"


def test_a_body_mount_is_unaffected_at_any_deflection():
    warp_core = (0.0, -0.33, 0.0)
    w = subsystem_world_position(_Sub(warp_core), _Ship(1.0))
    assert (w.x, w.y, w.z) == pytest.approx(warp_core)


def test_an_unrigged_ship_is_byte_identical():
    w = subsystem_world_position(_Sub(STAR_CANNON), _Ship(1.0, "galaxy"))
    assert (w.x, w.y, w.z) == pytest.approx(STAR_CANNON)


def test_a_ship_without_articulation_support_still_works():
    """A prop or test double with no GetArticulationDeflection must not raise —
    this function is on the firing path for every weapon in the game."""
    class _Bare:
        def GetWorldLocation(self):
            return TGPoint3(0.0, 0.0, 0.0)

        def GetWorldRotation(self):
            return TGMatrix3()

    w = subsystem_world_position(_Sub(STAR_CANNON), _Bare())
    assert (w.x, w.y, w.z) == pytest.approx(STAR_CANNON)


def test_ship_rotation_is_applied_after_the_part_transform():
    """The order matters: articulate in body frame, THEN rotate into world.

    Every test above uses an identity ship rotation, so R . v == v for any v
    -- they cannot tell "articulate then rotate" apart from "rotate then
    articulate". Articulation is itself a body-frame motion (a rotation about
    the part's own hinge), so it must compose INSIDE the ship's world
    rotation R, not outside it. This test uses a non-identity rotation about
    +X -- an axis unrelated to the wing's own hinge axis (+Y) -- so the two
    orderings provably diverge, and hand-computes the expected point in the
    same two explicit steps the implementation must take.
    """
    angle = math.radians(30.0)
    rot = TGMatrix3().MakeXRotation(angle)

    class _RotatedShip(_Ship):
        def GetWorldRotation(self):
            return rot

    ship = _RotatedShip(1.0)

    # Step 1: articulate the mount in BODY frame (wings up, deflection 1.0).
    ax, ay, az = part_transform_point(ship, STAR_CANNON)
    # Step 2: THEN rotate the articulated point into world space.
    expected = TGPoint3(ax, ay, az)
    expected.MultMatrixLeft(rot)

    w = subsystem_world_position(_Sub(STAR_CANNON), ship)
    assert (w.x, w.y, w.z) == pytest.approx((expected.x, expected.y, expected.z))
