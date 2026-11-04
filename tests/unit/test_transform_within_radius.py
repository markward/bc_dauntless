"""TransformStore.within_radius: one sphere-membership flag per handle.

Backs ProximityManager.GetNearObjects, which used to read every candidate's
position across the store boundary one at a time and compare in Python. Both
backends must answer exactly what that compare answered --
`dx*dx + dy*dy + dz*dz <= r2` in CPython doubles -- boundary included.
"""
import random
from array import array

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


def _pack(hs):
    flat = array("I")
    for index, generation in hs:
        flat.append(index)
        flat.append(generation)
    return flat


def test_near_indices_matches_within_radius_flags(store):
    s, made = store
    rng = random.Random(11)
    p = (0.1, -0.7, 0.3)
    pts = [tuple(rng.uniform(-100, 100) for _ in range(3)) for _ in range(200)]
    hs = [_put(s, made, xyz) for xyz in pts]
    packed = _pack(hs)
    radii = [rng.uniform(1, 150) ** 2 for _ in range(20)]
    for xyz in pts[:40]:
        dx, dy, dz = xyz[0] - p[0], xyz[1] - p[1], xyz[2] - p[2]
        radii.append(dx * dx + dy * dy + dz * dz)
    for r2 in radii:
        flags = s.within_radius(hs, *p, r2)
        assert list(s.near_indices(packed, *p, r2)) == \
            [k for k, f in enumerate(flags) if f]


def test_near_indices_is_ascending(store):
    s, made = store
    hs = [_put(s, made, (float(i % 5), 0.0, 0.0)) for i in range(30)]
    got = list(s.near_indices(_pack(hs), 0.0, 0.0, 0.0, 4.0))
    assert got == sorted(got) and len(got) == 18


def test_near_indices_stale_handle_raises(store):
    s, made = store
    h = s.alloc()
    s.free(*h)
    with pytest.raises(StaleHandleError):
        s.near_indices(_pack([h]), 0.0, 0.0, 0.0, 1.0)


def test_near_indices_empty_buffer(store):
    s, made = store
    assert list(s.near_indices(array("I"), 0.0, 0.0, 0.0, 1.0)) == []


# ── near_indices_sized: BC's size rule (native proximity phase 1, Task 7) ────
# Position k is kept when its centre lies within r + max(radii[k], 0) of the
# point: `dx*dx + dy*dy + dz*dz <= reach*reach`, rounded as CPython rounds it.

def _sized_reference(xyz, p, r, rad):
    reach = r + (rad if rad > 0.0 else 0.0)
    dx, dy, dz = xyz[0] - p[0], xyz[1] - p[1], xyz[2] - p[2]
    return dx * dx + dy * dy + dz * dz <= reach * reach


def test_near_indices_sized_matches_brute_force(store):
    s, made = store
    rng = random.Random(23)
    p = (0.1, -0.7, 0.3)
    pts = [tuple(rng.uniform(-100, 100) for _ in range(3)) for _ in range(200)]
    hs = [_put(s, made, xyz) for xyz in pts]
    packed = _pack(hs)
    radii = array("d", [rng.choice([0.0, -3.0, rng.uniform(0, 60)])
                        for _ in pts])
    rs = [0.0, 1.0, 12.5, 40.0, 150.0]
    for k, xyz in enumerate(pts[:40]):
        # The boundary itself: the query radius that puts k's surface on it.
        dx, dy, dz = xyz[0] - p[0], xyz[1] - p[1], xyz[2] - p[2]
        rs.append((dx * dx + dy * dy + dz * dz) ** 0.5
                  - (radii[k] if radii[k] > 0.0 else 0.0))
    for r in rs:
        want = [k for k, xyz in enumerate(pts)
                if _sized_reference(xyz, p, r, radii[k])]
        assert list(s.near_indices_sized(packed, radii, *p, r)) == want, r


def test_near_indices_sized_reach_adds_the_radius(store):
    s, made = store
    hs = [_put(s, made, (x, 0.0, 0.0)) for x in (350.0, 350.0, 35.0, 8.0)]
    packed = _pack(hs)
    radii = array("d", [296.0, 0.0, 30.0, -10.0])

    def near(r):
        return list(s.near_indices_sized(packed, radii, 0.0, 0.0, 0.0, r))

    assert near(54.0) == [0, 2, 3]    # 350 - 296 == 54: on the boundary
    assert near(53.0) == [2, 3]
    assert near(5.0) == [2]           # 35 - 30 == 5: on the boundary
    assert near(10.0) == [2, 3]       # a negative radius counts as 0


def test_near_indices_sized_with_zero_radii_equals_near_indices(store):
    s, made = store
    rng = random.Random(5)
    pts = [tuple(float(rng.randint(-20, 20)) for _ in range(3))
           for _ in range(100)]
    hs = [_put(s, made, xyz) for xyz in pts]
    packed = _pack(hs)
    zeros = array("d", [0.0] * len(pts))
    for r in (0.0, 1.0, 3.0, 7.5, 20.0):
        assert list(s.near_indices_sized(packed, zeros, 0.0, 0.0, 0.0, r)) == \
            list(s.near_indices(packed, 0.0, 0.0, 0.0, r * r))


def test_near_indices_sized_stale_handle_raises(store):
    s, made = store
    h = s.alloc()
    s.free(*h)
    with pytest.raises(StaleHandleError):
        s.near_indices_sized(_pack([h]), array("d", [1.0]),
                             0.0, 0.0, 0.0, 1.0)


def test_near_indices_sized_empty_buffer(store):
    s, made = store
    assert list(s.near_indices_sized(array("I"), array("d"),
                                     0.0, 0.0, 0.0, 1.0)) == []


def test_near_indices_sized_radii_length_mismatch_raises(store):
    s, made = store
    hs = [_put(s, made, (0.0, 0.0, 0.0)) for _ in range(3)]
    with pytest.raises(ValueError):
        s.near_indices_sized(_pack(hs), array("d", [1.0, 2.0]),
                             0.0, 0.0, 0.0, 1.0)
