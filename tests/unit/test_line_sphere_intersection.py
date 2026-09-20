"""App.TGGeomUtils_LineSphereIntersection — AI/PlainAI/Intercept.py:326.

The SDK passes (vStart, vRay, centre, radius, vNearPoint, vFarPoint) and
reads vNearPoint back. Undefined, the truthy stub made every candidate
"intersect" with vNearPoint left at the origin, so Intercept dodged the
FIRST obstacle in its list rather than the nearest."""
import App
from engine.appc.math import TGPoint3


def _p(x, y, z):
    return TGPoint3(float(x), float(y), float(z))


def test_is_real_surface():
    assert not isinstance(App.TGGeomUtils_LineSphereIntersection, App._NamedStub)


def test_segment_through_sphere_reports_entry_and_exit():
    near, far = TGPoint3(), TGPoint3()
    hit = App.TGGeomUtils_LineSphereIntersection(
        _p(0, 0, 0), _p(0, 100, 0), _p(0, 50, 0), 10.0, near, far)
    assert hit == 1
    assert (near.x, round(near.y, 6), near.z) == (0.0, 40.0, 0.0)
    assert (far.x, round(far.y, 6), far.z) == (0.0, 60.0, 0.0)


def test_segment_missing_sphere_reports_zero_and_leaves_outputs():
    near, far = _p(9, 9, 9), _p(8, 8, 8)
    hit = App.TGGeomUtils_LineSphereIntersection(
        _p(0, 0, 0), _p(0, 100, 0), _p(50, 50, 0), 10.0, near, far)
    assert hit == 0
    assert (near.x, near.y, near.z) == (9.0, 9.0, 9.0)
    assert (far.x, far.y, far.z) == (8.0, 8.0, 8.0)


def test_sphere_beyond_segment_end_is_a_miss():
    near, far = TGPoint3(), TGPoint3()
    hit = App.TGGeomUtils_LineSphereIntersection(
        _p(0, 0, 0), _p(0, 10, 0), _p(0, 50, 0), 10.0, near, far)
    assert hit == 0


def test_start_inside_sphere_reports_start_as_entry():
    near, far = TGPoint3(), TGPoint3()
    hit = App.TGGeomUtils_LineSphereIntersection(
        _p(0, 0, 0), _p(0, 100, 0), _p(0, 0, 0), 10.0, near, far)
    assert hit == 1
    assert (near.x, near.y, near.z) == (0.0, 0.0, 0.0)
    assert round(far.y, 6) == 10.0


def test_sphere_behind_segment_start_is_a_miss():
    near, far = TGPoint3(), TGPoint3()
    hit = App.TGGeomUtils_LineSphereIntersection(
        _p(0, 0, 0), _p(0, 100, 0), _p(0, -50, 0), 10.0, near, far)
    assert hit == 0


def test_zero_length_ray_is_a_miss():
    """Degenerate ray (no direction) is a miss; this is the plan's stated choice."""
    near, far = _p(5, 5, 5), _p(6, 6, 6)
    hit = App.TGGeomUtils_LineSphereIntersection(
        _p(0, 0, 0), _p(0, 0, 0), _p(0, 0, 0), 10.0, near, far)
    assert hit == 0
    assert (near.x, near.y, near.z) == (5.0, 5.0, 5.0)
    assert (far.x, far.y, far.z) == (6.0, 6.0, 6.0)
