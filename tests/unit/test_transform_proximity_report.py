"""TransformStore.proximity_report: which proximity pairs Python must look at.

Backs engine.appc.proximity_table. Each pair is (anchor handle, object handle,
radius squared, want); the report lists, in order from `start`, every pair
whose want is 2 (always), whose handles are stale, or whose object is inside
(want 0) / outside (want 1) the anchor's sphere -- inside meaning
`dx*dx + dy*dy + dz*dz <= r2` in CPython doubles, as
ProximityCheck._evaluate_one tests it. Want 3 never reports a live pair.
"""
import random
from array import array

import pytest

from engine.appc.transform_store import PythonTransformStore, StaleHandleError

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

_HAS_NATIVE = _h is not None and hasattr(_h, "transform_proximity_report")


def _native():
    from engine.appc.transform_store import NativeTransformStore
    return NativeTransformStore(_h)


BACKENDS = [
    pytest.param(PythonTransformStore, id="python"),
    pytest.param(_native, id="native", marks=pytest.mark.skipif(
        not _HAS_NATIVE, reason="native transform_proximity_report not built")),
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


def _pack(pairs):
    """pairs: [(anchor_handle, object_handle, r2, want)] -> the four buffers."""
    anchors, objects, r2s, wants = array("I"), array("I"), array("d"), bytearray()
    for a, o, r2, w in pairs:
        anchors.extend(a)
        objects.extend(o)
        r2s.append(r2)
        wants.append(w)
    return anchors, objects, r2s, wants


def test_reports_inside_for_want_0_and_outside_for_want_1(store):
    s, made = store
    centre = _put(s, made, (10.0, 0.0, 0.0))
    near = _put(s, made, (12.0, 0.0, 0.0))
    far = _put(s, made, (50.0, 0.0, 0.0))
    on_edge = _put(s, made, (13.0, 0.0, 0.0))
    bufs = _pack([
        (centre, near, 9.0, 0),      # inside, wants inside   -> report
        (centre, far, 9.0, 0),       # outside, wants inside  -> no
        (centre, near, 9.0, 1),      # inside, wants outside  -> no
        (centre, far, 9.0, 1),       # outside, wants outside -> report
        (centre, on_edge, 9.0, 0),   # exactly on the sphere is inside
        (centre, on_edge, 9.0, 1),
        (centre, far, 9.0, 2),       # always
        (centre, near, 9.0, 3),      # never
        (centre, far, 9.0, 3),
    ])
    assert list(s.proximity_report(*bufs, 0)) == [0, 3, 4, 6]


def test_starts_at_start(store):
    s, made = store
    centre = _put(s, made, (0.0, 0.0, 0.0))
    near = _put(s, made, (1.0, 0.0, 0.0))
    bufs = _pack([(centre, near, 4.0, 0)] * 5)
    assert list(s.proximity_report(*bufs, 3)) == [3, 4]
    assert list(s.proximity_report(*bufs, 5)) == []


def test_always_rows_never_read_their_handles(store):
    s, made = store
    centre = _put(s, made, (0.0, 0.0, 0.0))
    bufs = _pack([((0, 0), (0, 0), 0.0, 2), (centre, centre, 1.0, 1)])
    assert list(s.proximity_report(*bufs, 0)) == [0]


def test_a_stale_handle_is_reported_not_raised(store):
    """Python re-runs the pair and fails exactly as it always did."""
    s, made = store
    centre = _put(s, made, (0.0, 0.0, 0.0))
    gone = s.alloc()
    s.free(*gone)
    bufs = _pack([(centre, gone, 1.0, 3), (gone, centre, 1.0, 3),
                  (centre, centre, 1.0, 3)])
    assert list(s.proximity_report(*bufs, 0)) == [0, 1]


def test_agrees_with_the_python_compare_on_every_boundary(store):
    s, made = store
    rng = random.Random(11)
    pts = [tuple(rng.uniform(-100, 100) for _ in range(3)) for _ in range(40)]
    hs = [_put(s, made, xyz) for xyz in pts]
    pairs, expect = [], []
    for k in range(400):
        ai, oi = rng.randrange(40), rng.randrange(40)
        a, o = pts[ai], pts[oi]
        dx, dy, dz = o[0] - a[0], o[1] - a[1], o[2] - a[2]
        d2 = dx * dx + dy * dy + dz * dz
        # Half the radii sit exactly on the object, the rest either side.
        r2 = d2 if k % 2 else d2 * rng.choice((0.999999, 1.000001))
        want = k % 2 if k % 4 < 2 else (k // 2) % 2
        pairs.append((hs[ai], hs[oi], r2, want))
        inside = d2 <= r2
        if inside == (want == 0):
            expect.append(k)
    assert list(s.proximity_report(*_pack(pairs), 0)) == expect
