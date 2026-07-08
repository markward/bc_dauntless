"""PhysicsObjectClass.LineCollides(p1, p2): does the segment cross the object's
bounding-sphere surface? Backs AI.Compound.DockWithStarbase.IsInViewOfInsidePoints
(sdk/.../DockWithStarbase.py:368). Was an unimplemented silent truthy _NamedStub."""
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass


def _obj_at(x, y, z, radius):
    o = PhysicsObjectClass()
    o.SetTranslateXYZ(x, y, z)
    o.SetRadius(radius)
    return o


def test_interior_point_to_outside_crosses_surface():
    """One endpoint inside the sphere, one outside -> crosses -> collides."""
    o = _obj_at(0.0, 0.0, 0.0, 100.0)
    inside = TGPoint3(10.0, 0.0, 0.0)      # inside radius 100
    outside = TGPoint3(500.0, 0.0, 0.0)    # well outside
    assert o.LineCollides(inside, outside) == 1


def test_both_endpoints_inside_no_crossing():
    """Both endpoints inside the sphere -> no surface crossing -> clear."""
    o = _obj_at(0.0, 0.0, 0.0, 100.0)
    a = TGPoint3(10.0, 0.0, 0.0)
    b = TGPoint3(-20.0, 30.0, 0.0)
    assert o.LineCollides(a, b) == 0


def test_segment_passing_through_sphere_collides():
    """Both endpoints outside but the segment passes through -> collides."""
    o = _obj_at(0.0, 0.0, 0.0, 100.0)
    a = TGPoint3(-500.0, 0.0, 0.0)
    b = TGPoint3(500.0, 0.0, 0.0)
    assert o.LineCollides(a, b) == 1


def test_segment_clear_of_sphere_misses():
    """Both endpoints outside and the segment never nears the sphere -> clear."""
    o = _obj_at(0.0, 0.0, 0.0, 100.0)
    a = TGPoint3(-500.0, 400.0, 0.0)
    b = TGPoint3(500.0, 400.0, 0.0)        # closest approach y=400 > r=100
    assert o.LineCollides(a, b) == 0


def test_degenerate_zero_length_segment_inside():
    """A zero-length segment inside the sphere does not cross the surface."""
    o = _obj_at(0.0, 0.0, 0.0, 100.0)
    p = TGPoint3(5.0, 0.0, 0.0)
    assert o.LineCollides(p, p) == 0
