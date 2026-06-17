from engine.appc import hull_carve


def test_should_carve_threshold():
    assert hull_carve.should_carve(50.0) is True
    assert hull_carve.should_carve(5.0) is False


def test_carve_radius_floored_and_scaled():
    assert hull_carve.carve_radius_gu(0.0) == hull_carve.MIN_CARVE_RADIUS_GU
    assert hull_carve.carve_radius_gu(1.0) >= hull_carve.MIN_CARVE_RADIUS_GU
