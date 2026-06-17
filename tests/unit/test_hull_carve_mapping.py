from engine.appc import hull_carve


def test_should_carve_threshold():
    assert hull_carve.should_carve(70.0) is True   # input bumped 50→70 (threshold raised to 60)
    assert hull_carve.should_carve(5.0) is False


def test_carve_radius_floored_and_scaled():
    assert hull_carve.carve_radius_gu(0.0) == hull_carve.MIN_CARVE_RADIUS_GU
    assert hull_carve.carve_radius_gu(1.0) >= hull_carve.MIN_CARVE_RADIUS_GU


def test_toned_down_values():
    # Tone-down (Mark: 2a effect too strong): smaller holes, carve less readily.
    assert hull_carve.CARVE_RADIUS_SCALE <= 1.0      # was 1.5 -> smaller holes
    assert hull_carve.MIN_CARVE_HULL >= 60.0         # was 40  -> carve less readily


def test_carve_radius_still_scales_and_floors():
    # floor still applies, scaling still monotonic
    assert hull_carve.carve_radius_gu(0.0) == hull_carve.MIN_CARVE_RADIUS_GU
    big = hull_carve.carve_radius_gu(10.0)
    assert big >= hull_carve.MIN_CARVE_RADIUS_GU
    assert big == max(hull_carve.MIN_CARVE_RADIUS_GU, 10.0 * hull_carve.CARVE_RADIUS_SCALE)
