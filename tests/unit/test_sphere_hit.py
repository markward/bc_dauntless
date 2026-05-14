from engine.appc.math import TGPoint3
from engine.appc.combat import sphere_hit


def test_point_inside_sphere_hits():
    assert sphere_hit(TGPoint3(1, 0, 0), TGPoint3(0, 0, 0), radius=2.0) is True


def test_point_outside_sphere_misses():
    assert sphere_hit(TGPoint3(5, 0, 0), TGPoint3(0, 0, 0), radius=2.0) is False


def test_point_on_sphere_boundary_hits():
    assert sphere_hit(TGPoint3(2, 0, 0), TGPoint3(0, 0, 0), radius=2.0) is True


def test_sphere_hit_uses_squared_distance():
    assert sphere_hit(TGPoint3(3, 4, 0), TGPoint3(0, 0, 0), radius=5.0) is True
