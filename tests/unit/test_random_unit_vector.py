"""App.TGPoint3_GetRandomUnitVector — heatmap rank 1 (80,805 hits).
Undefined, every call returned a truthy _NamedStub whose .x/.y/.z were
stubs, so Flee/EvadeTorps/Warp/AvoidObstacles scored every random
candidate as the zero vector."""
import math
import App
from engine.appc.math import TGPoint3


def test_is_real_surface_not_a_stub():
    assert not isinstance(App.TGPoint3_GetRandomUnitVector, App._NamedStub)


def test_returns_a_unit_tgpoint3():
    v = App.TGPoint3_GetRandomUnitVector()
    assert isinstance(v, TGPoint3)
    assert abs(math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z) - 1.0) < 1e-6


def test_successive_calls_differ_and_cover_every_octant():
    seen = set()
    for _ in range(400):
        v = App.TGPoint3_GetRandomUnitVector()
        seen.add((v.x > 0, v.y > 0, v.z > 0))
    assert len(seen) == 8, "not uniformly distributed over the sphere"


def test_each_call_is_a_fresh_object():
    a = App.TGPoint3_GetRandomUnitVector()
    b = App.TGPoint3_GetRandomUnitVector()
    assert a is not b
