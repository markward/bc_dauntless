import pytest

from engine.appc import hull_carve


def test_strength_scales_with_absorbed_hull():
    # strength = absorbed_hull * STRENGTH_PER_HULL (1:1) — accumulates gradually
    # rather than a single moderate hit one-shotting a breach.
    assert hull_carve.carve_strength(0.0) == 0.0
    assert hull_carve.carve_strength(60.0) == pytest.approx(60.0 * hull_carve.STRENGTH_PER_HULL)
    # Monotonic and never negative.
    assert hull_carve.carve_strength(-5.0) == 0.0
    assert hull_carve.carve_strength(120.0) > hull_carve.carve_strength(60.0)


def test_influ_floored_and_scaled():
    # Merge influence is floored so clustered light fire accumulates even with a
    # tiny weapon splash, and scales above the floor.
    assert hull_carve.carve_influ_gu(0.0) == hull_carve.CARVE_INFLU_MIN_GU
    big = hull_carve.carve_influ_gu(10.0)
    assert big >= hull_carve.CARVE_INFLU_MIN_GU
    assert big == max(hull_carve.CARVE_INFLU_MIN_GU,
                      10.0 * hull_carve.CARVE_INFLU_SCALE)


def test_constants_sane():
    assert hull_carve.STRENGTH_PER_HULL > 0.0
    assert hull_carve.CARVE_INFLU_MIN_GU > 0.0
    assert hull_carve.MIN_CARVE_RADIUS_GU > 0.0
    assert hull_carve.CARVE_EMIT_INTERVAL > 0.0
