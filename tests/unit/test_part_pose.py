"""Pose maths for articulated parts (spec 2026-09-25 §3, §4.1, §6).

A pose (R, t) draws a body point x at R·x + t, R = Rz·Ry·Rx (degrees, body X
then Y then Z), about the body ORIGIN -- never the anchor, which is what lets
the anchor move without moving any authored pose (spec §2.3, option A).
"""
import math

import pytest

from engine.appc import part_pose as pp


def _rodrigues(point, pivot, axis, degrees):
    """The OLD hinge maths, verbatim in spirit (articulation._rotate_about):
    the reference the legacy conversion must match."""
    n = math.sqrt(sum(a * a for a in axis))
    ax, ay, az = (a / n for a in axis)
    th = math.radians(degrees)
    vx, vy, vz = (point[i] - pivot[i] for i in range(3))
    c, s = math.cos(th), math.sin(th)
    dot = ax * vx + ay * vy + az * vz
    cx, cy, cz = ay * vz - az * vy, az * vx - ax * vz, ax * vy - ay * vx
    return (pivot[0] + vx * c + cx * s + ax * dot * (1 - c),
            pivot[1] + vy * c + cy * s + ay * dot * (1 - c),
            pivot[2] + vz * c + cz * s + az * dot * (1 - c))


def test_euler_order_is_x_then_y_then_z():
    """THE convention pin. R = Rz·Ry·Rx: a point on +Y rotated 90 about X
    goes to +Z, and THEN 90 about Z leaves +Z where it is."""
    R = pp.euler_to_matrix(90.0, 0.0, 90.0)
    assert pp.apply((R, (0.0, 0.0, 0.0)), (0.0, 1.0, 0.0)) == pytest.approx(
        (0.0, 0.0, 1.0), abs=1e-12)
    # and +X: 90 about X keeps +X; 90 about Z takes it to +Y
    assert pp.apply((R, (0.0, 0.0, 0.0)), (1.0, 0.0, 0.0)) == pytest.approx(
        (0.0, 1.0, 0.0), abs=1e-12)


def test_matrix_to_euler_round_trips():
    for e in [(10.0, 20.0, 30.0), (-45.0, 0.0, 0.0), (0.0, -80.0, 170.0),
              (0.0, 0.0, 0.0)]:
        R = pp.euler_to_matrix(*e)
        R2 = pp.euler_to_matrix(*pp.matrix_to_euler(R))
        for r1, r2 in zip(R, R2):
            assert r1 == pytest.approx(r2, abs=1e-9)


def test_pose6_round_trips():
    p6 = (0.1, -0.2, 0.3, 12.0, -34.0, 56.0)
    assert pp.pose_to6(pp.pose_from6(p6)) == pytest.approx(p6, abs=1e-9)


def test_inverse_apply_undoes_apply():
    pose = pp.pose_from6((0.5, 0.0, -0.25, 30.0, 10.0, -20.0))
    x = (1.0, 2.0, 3.0)
    assert pp.inverse_apply(pose, pp.apply(pose, x)) == pytest.approx(x)


def test_vectors_rotate_but_never_translate():
    pose = pp.pose_from6((9.0, 9.0, 9.0, 0.0, 0.0, 90.0))
    assert pp.apply_vector(pose, (1.0, 0.0, 0.0)) == pytest.approx(
        (0.0, 1.0, 0.0), abs=1e-12)


def test_identity_is_identity():
    assert pp.is_identity(pp.IDENTITY)
    assert pp.is_identity(pp.pose_from6((0, 0, 0, 0, 0, 0)))
    assert not pp.is_identity(pp.pose_from6((0, 0, 0, 1e-3, 0, 0)))


@pytest.mark.parametrize("deg", [45.0, -45.0, 0.0, 17.5])
def test_legacy_hinge_matches_old_rodrigues_everywhere(deg):
    """Migration (spec §6): anchor p, R = rot(n, θ), t = p - R·p reproduces
    the old Rodrigues hinge at every point -- the BoP's numbers."""
    pivot, axis = (-0.16, 0.0, 0.05), (0.0, 1.0, 0.0)
    pose = pp.hinge_pose(pivot, axis, deg)
    for x in [(1.0, 0.45, -0.67), (-1.0, 0.0, -0.7), (0.0, 0.0, 0.0)]:
        assert pp.apply(pose, x) == pytest.approx(
            _rodrigues(x, pivot, axis, deg), abs=1e-12)


def test_interpolation_hits_both_end_poses_for_any_anchor():
    p0 = pp.pose_from6((0, 0, 0, 0, 0, 0))
    p1 = pp.pose_from6((0.2, 0.1, 0.0, 0.0, 30.0, 0.0))
    x = (1.0, 0.5, -0.5)
    for anchor in [(0, 0, 0), (-0.16, 0, 0.05), (3.0, -2.0, 1.0)]:
        assert pp.apply(pp.interpolate(p0, p1, anchor, 0.0), x) == pytest.approx(
            pp.apply(p0, x))
        assert pp.apply(pp.interpolate(p0, p1, anchor, 1.0), x) == pytest.approx(
            pp.apply(p1, x))


def test_the_midpoint_swings_on_the_arc_not_the_chord():
    """A hinge about the anchor: halfway, the tip is on the circle about the
    anchor, not on the straight line between its end positions."""
    anchor, axis = (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    p0, p1 = pp.hinge_pose(anchor, axis, 0.0), pp.hinge_pose(anchor, axis, 90.0)
    tip = (1.0, 0.0, 0.0)
    mid = pp.apply(pp.interpolate(p0, p1, anchor, 0.5), tip)
    assert math.dist(mid, anchor) == pytest.approx(1.0, abs=1e-9)
    chord_mid = tuple((a + b) / 2 for a, b in zip(pp.apply(p0, tip),
                                                  pp.apply(p1, tip)))
    assert math.dist(mid, chord_mid) > 0.2


def test_legacy_hinge_interpolation_is_the_old_linear_angle_ease():
    """With the anchor on the hinge axis, the swing IS the old linear angle
    ease: halfway between 0 and 45 degrees is exactly 22.5 degrees."""
    pivot, axis = (-0.16, 0.0, 0.05), (0.0, 1.0, 0.0)
    mid = pp.interpolate(pp.hinge_pose(pivot, axis, 0.0),
                         pp.hinge_pose(pivot, axis, 45.0), pivot, 0.5)
    x = (-1.0, 0.45, -0.67)
    assert pp.apply(mid, x) == pytest.approx(_rodrigues(x, pivot, axis, 22.5),
                                             abs=1e-9)


def test_moving_the_anchor_leaves_end_poses_unchanged():
    """Spec §2.3 option A, at the maths level: the anchor changes the path
    only. Same end poses, two anchors, different midpoints."""
    p0 = pp.pose_from6((0, 0, 0, 0, 0, 0))
    p1 = pp.pose_from6((0.0, 0.0, 0.3, 0.0, 40.0, 0.0))
    x = (1.0, 0.0, 0.0)
    a, b = (0.0, 0.0, 0.0), (0.8, 0.0, 0.0)
    assert pp.apply(pp.interpolate(p0, p1, a, 1.0), x) == pytest.approx(
        pp.apply(pp.interpolate(p0, p1, b, 1.0), x))
    assert pp.apply(pp.interpolate(p0, p1, a, 0.5), x) != pytest.approx(
        pp.apply(pp.interpolate(p0, p1, b, 0.5), x))


def test_model_matrix_is_column_major_and_scales_translation():
    """The native binding's matrix: M·[x_model,1] must equal the pose applied
    in ship units, rescaled to model units."""
    pose = pp.pose_from6((0.3, -0.1, 0.2, 10.0, 20.0, 30.0))
    m = pp.matrix4_model(pose, 0.01)
    assert len(m) == 16
    x_ship = (0.5, 0.25, -0.75)
    x_model = tuple(c / 0.01 for c in x_ship)
    col = lambda j: m[4 * j:4 * j + 4]               # column-major columns
    out = tuple(col(0)[r] * x_model[0] + col(1)[r] * x_model[1]
                + col(2)[r] * x_model[2] + col(3)[r] for r in range(3))
    want = tuple(c / 0.01 for c in pp.apply(pose, x_ship))
    assert out == pytest.approx(want, abs=1e-6)
    assert (m[3], m[7], m[11], m[15]) == (0.0, 0.0, 0.0, 1.0)
