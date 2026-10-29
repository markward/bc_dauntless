"""TransformStore.within_radius: one sphere-membership flag per handle.

Backs ProximityManager.GetNearObjects, which used to read every candidate's
position across the store boundary one at a time and compare in Python. Both
backends must answer exactly what that compare answered --
`dx*dx + dy*dy + dz*dz <= r2` in CPython doubles -- boundary included.
"""
import random

import pytest

from engine.appc.transform_store import PythonTransformStore, StaleHandleError

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

_HAS_NATIVE = _h is not None and hasattr(_h, "transform_within_radius")


def _native():
    from engine.appc.transform_store import NativeTransformStore
    return NativeTransformStore(_h)


BACKENDS = [
    pytest.param(PythonTransformStore, id="python"),
    pytest.param(_native, id="native", marks=pytest.mark.skipif(
        not _HAS_NATIVE, reason="native transform_within_radius not built")),
]


@pytest.fixture(params=BACKENDS)
def store(request):
    s = request.param()
    made = []
    yield s, made
    for h in made:
        try:
            s.free(*h)
        except StaleHandleError:
            pass


def _put(store, made, xyz):
    h = store.alloc()
    made.append(h)
    store.set_position(*h, *xyz)
    return h


def _reference(xyz, p, r2):
    dx, dy, dz = xyz[0] - p[0], xyz[1] - p[1], xyz[2] - p[2]
    return dx * dx + dy * dy + dz * dz <= r2


def test_flags_each_handle_in_order(store):
    s, made = store
    hs = [_put(s, made, xyz) for xyz in
          [(1, 0, 0), (50, 0, 0), (3, 0, 0), (-2.9, 0, 0), (0, 0, 0)]]
    assert [bool(f) for f in s.within_radius(hs, 0.0, 0.0, 0.0, 9.0)] == \
        [True, False, True, True, True]
    assert len(s.within_radius([], 0.0, 0.0, 0.0, 9.0)) == 0


def test_agrees_with_the_python_compare_on_every_boundary(store):
    s, made = store
    rng = random.Random(7)
    p = (0.1, -0.7, 0.3)
    pts = [tuple(rng.uniform(-100, 100) for _ in range(3)) for _ in range(300)]
    hs = [_put(s, made, xyz) for xyz in pts]
    for xyz in pts[:60]:
        dx, dy, dz = xyz[0] - p[0], xyz[1] - p[1], xyz[2] - p[2]
        r2 = dx * dx + dy * dy + dz * dz
        got = [bool(f) for f in s.within_radius(hs, *p, r2)]
        assert got == [_reference(q, p, r2) for q in pts]


def test_a_stale_handle_raises(store):
    s, made = store
    h = s.alloc()
    s.free(*h)
    with pytest.raises(StaleHandleError):
        s.within_radius([h], 0.0, 0.0, 0.0, 1.0)
