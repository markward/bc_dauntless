"""Transform-gizmo geometry/picking/drag (pure Python, SPV logic core)."""
import math
import pytest

from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui import ship_property_viewer as spv
from engine.ui.ship_property_viewer import OrbitCamera


def _cam():
    # Looks down -Z at the origin from +Z; up is +Y.
    return OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)


def test_gizmo_axes_are_rotation_columns():
    R = TGMatrix3()  # identity
    ax, ay, az = spv.gizmo_axes(R)
    assert ax == pytest.approx((1.0, 0.0, 0.0))
    assert ay == pytest.approx((0.0, 1.0, 0.0))
    assert az == pytest.approx((0.0, 0.0, 1.0))


def test_gizmo_length_scales_with_distance():
    far = spv.gizmo_length(OrbitCamera((0, 0, 0), 100.0, 0.0, 0.0))
    near = spv.gizmo_length(OrbitCamera((0, 0, 0), 4.0, 0.0, 0.0))
    assert far > near
    assert near >= spv.GIZMO_MIN_LENGTH


def test_world_from_body_applies_rotation_and_translation():
    class _Ship:
        def GetWorldLocation(self): return TGPoint3(5.0, 0.0, 0.0)
        def GetWorldRotation(self): return TGMatrix3()  # identity
    w = spv.world_from_body(_Ship(), (0.0, 2.0, 0.0))
    assert (w[0], w[1], w[2]) == pytest.approx((5.0, 2.0, 0.0))


def test_pick_gizmo_axis_hits_projected_shaft():
    cam, vp = _cam(), (800, 600)
    origin = (0.0, 0.0, 0.0)
    axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    length = spv.gizmo_length(cam)
    # A point on the +X shaft, projected to screen, must pick axis 0.
    tip = spv._add(origin, spv._scale(axes[0], length * 0.5))
    sx, sy, _z, vis = spv.project(tip, cam, vp)
    assert vis
    assert spv.pick_gizmo_axis(sx, sy, origin, axes, length, cam, vp) == 0


def test_pick_gizmo_axis_misses_off_shaft():
    cam, vp = _cam(), (800, 600)
    origin = (0.0, 0.0, 0.0)
    axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    length = spv.gizmo_length(cam)
    # Screen centre (origin projects there); far from any shaft midpoint edge.
    assert spv.pick_gizmo_axis(5.0, 5.0, origin, axes, length, cam, vp) is None


def test_axis_drag_param_monotonic_along_screen_axis():
    cam, vp = _cam(), (800, 600)
    origin = (0.0, 0.0, 0.0)
    axis = (1.0, 0.0, 0.0)
    length = spv.gizmo_length(cam)
    s0 = spv.project(origin, cam, vp)
    s1 = spv.project(spv._scale(axis, length), cam, vp)
    # Cursor at the projected tip → param ~= length; at origin → ~= 0.
    t_tip = spv.axis_drag_param(s1[0], s1[1], origin, axis, length, cam, vp)
    t_org = spv.axis_drag_param(s0[0], s0[1], origin, axis, length, cam, vp)
    assert t_tip == pytest.approx(length, abs=length * 0.05)
    assert t_org == pytest.approx(0.0, abs=length * 0.05)
