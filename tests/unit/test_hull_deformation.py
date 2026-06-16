"""Pure mappings: absorbed hull damage -> crater depth/radius (GU) and the
inward shove direction. Curve SHAPE is contractual; absolute values are
eye-calibration knobs (see plan 6 rationale)."""
import math

import pytest

from engine.appc import hull_deformation as hd


def test_should_deform_threshold():
    assert hd.should_deform(hd.MIN_DEFORM_HULL) is True
    assert hd.should_deform(hd.MIN_DEFORM_HULL + 1.0) is True
    assert hd.should_deform(hd.MIN_DEFORM_HULL - 0.001) is False
    assert hd.should_deform(0.0) is False


def test_crater_depth_monotonic_and_capped():
    assert hd.crater_depth_gu(0.0) == 0.0
    assert hd.crater_depth_gu(-5.0) == 0.0
    d_small = hd.crater_depth_gu(50.0)
    d_big = hd.crater_depth_gu(200.0)
    assert 0.0 < d_small < d_big
    assert hd.crater_depth_gu(1.0e9) == pytest.approx(hd.MAX_CRATER_DEPTH_GU)


def test_crater_radius_scales_with_floor():
    assert hd.crater_radius_gu(1.0) == pytest.approx(1.0 * hd.DEFORM_RADIUS_SCALE)
    assert hd.crater_radius_gu(0.0) == pytest.approx(hd.MIN_DEFORM_RADIUS_GU)


def test_impact_direction_falls_back_to_minus_normal():
    d = hd.impact_direction((0.0, 0.0, 1.0))
    assert d == pytest.approx((0.0, 0.0, -1.0))


def test_impact_direction_uses_inward_weapon_ray():
    d = hd.impact_direction(
        (0.0, 0.0, 1.0), source_pos=(0.0, 0.0, 10.0), hit_point=(0.0, 0.0, 2.0))
    assert d == pytest.approx((0.0, 0.0, -1.0))
    assert math.isclose(d[0] ** 2 + d[1] ** 2 + d[2] ** 2, 1.0, rel_tol=1e-6)


def test_impact_direction_rejects_outward_ray():
    d = hd.impact_direction(
        (0.0, 0.0, 1.0), source_pos=(0.0, 0.0, 2.0), hit_point=(0.0, 0.0, 10.0))
    assert d == pytest.approx((0.0, 0.0, -1.0))


def test_impact_direction_degenerate_ray_falls_back():
    d = hd.impact_direction(
        (0.0, 1.0, 0.0), source_pos=(5.0, 5.0, 5.0), hit_point=(5.0, 5.0, 5.0))
    assert d == pytest.approx((0.0, -1.0, 0.0))
