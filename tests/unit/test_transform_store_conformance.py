"""One contract, run against every TransformStore backend.

Two backends that are never live at the same time are only safe if something
proves they agree. This is that something.

The native store is a process-wide singleton (there is exactly one
dauntless::transform_store() per process), so every test using it must free
every handle it allocates — a leaked slot inflates live_count()/capacity()
for every later test in the session. The two count-based tests below measure
deltas from a baseline captured at the start of the test for the same reason.
"""
import sys

import pytest

from engine.appc.transform_store import (
    NativeTransformStore, PythonTransformStore, StaleHandleError)

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

_HAS_NATIVE = _h is not None and hasattr(_h, "transform_alloc")

STORE_FACTORIES = [
    pytest.param(PythonTransformStore, id="python"),
    pytest.param(
        lambda: NativeTransformStore(_h), id="native",
        marks=pytest.mark.skipif(
            not _HAS_NATIVE,
            reason="native _dauntless_host transform bindings not built")),
]

IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


@pytest.fixture(params=STORE_FACTORIES)
def store(request):
    return request.param()


def test_new_slot_is_identity_at_origin(store):
    i, g = store.alloc()
    assert store.get_position(i, g) == (0.0, 0.0, 0.0)
    assert store.get_rotation(i, g) == IDENTITY
    store.free(i, g)


def test_position_round_trips(store):
    i, g = store.alloc()
    store.set_position(i, g, 1.5, -2.5, 3.25)
    assert store.get_position(i, g) == (1.5, -2.5, 3.25)
    store.free(i, g)


def test_rotation_round_trips(store):
    # The native backend stores C++ `double`, matching Python's `float`
    # exactly (bit-for-bit), so both backends must agree here without any
    # tolerance — that agreement is the whole point of running one
    # conformance suite against two implementations.
    i, g = store.alloc()
    src = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
    store.set_rotation(i, g, src)
    assert store.get_rotation(i, g) == src
    store.free(i, g)


def test_rotation_col_reads_columns(store):
    """Column-vector convention: col 1 is forward."""
    i, g = store.alloc()
    store.set_rotation(i, g, (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0))
    assert store.get_rotation_col(i, g, 0) == (1.0, 4.0, 7.0)
    assert store.get_rotation_col(i, g, 1) == (2.0, 5.0, 8.0)
    assert store.get_rotation_col(i, g, 2) == (3.0, 6.0, 9.0)
    store.free(i, g)


def test_slots_are_independent(store):
    a_i, a_g = store.alloc()
    b_i, b_g = store.alloc()
    store.set_position(a_i, a_g, 1.0, 1.0, 1.0)
    store.set_position(b_i, b_g, 2.0, 2.0, 2.0)
    assert store.get_position(a_i, a_g) == (1.0, 1.0, 1.0)
    assert store.get_position(b_i, b_g) == (2.0, 2.0, 2.0)
    store.free(a_i, a_g)
    store.free(b_i, b_g)


def test_freed_handle_is_stale(store):
    i, g = store.alloc()
    store.free(i, g)
    with pytest.raises(StaleHandleError):
        store.get_position(i, g)
    with pytest.raises(StaleHandleError):
        store.set_position(i, g, 0.0, 0.0, 0.0)
    with pytest.raises(StaleHandleError):
        store.get_rotation(i, g)


def test_double_free_raises(store):
    i, g = store.alloc()
    store.free(i, g)
    with pytest.raises(StaleHandleError):
        store.free(i, g)


def test_reused_index_gets_a_new_generation(store):
    """The whole point of the generation counter: a stale handle must not
    silently read whatever object recycled its index."""
    i1, g1 = store.alloc()
    store.free(i1, g1)
    i2, g2 = store.alloc()
    assert i2 == i1, "expected the free list to reuse the index"
    assert g2 != g1
    store.set_position(i2, g2, 5.0, 5.0, 5.0)
    with pytest.raises(StaleHandleError):
        store.get_position(i1, g1)
    store.free(i2, g2)


def test_live_count_tracks_alloc_and_free(store):
    # The native store is a process-wide singleton, so live_count() does not
    # start at zero across tests — measure the delta from a baseline instead
    # of an absolute count.
    base = store.live_count()
    handles = [store.alloc() for _ in range(10)]
    assert store.live_count() - base == 10
    for i, g in handles[:4]:
        store.free(i, g)
    assert store.live_count() - base == 6
    for i, g in handles[4:]:
        store.free(i, g)


def test_many_alloc_free_cycles_do_not_leak(store):
    """Torpedoes churn hard; the free list must actually be reused."""
    base_live = store.live_count()
    base_capacity = store.capacity()
    for _ in range(1000):
        i, g = store.alloc()
        store.free(i, g)
    assert store.live_count() == base_live
    grown = store.capacity() - base_capacity
    assert grown <= 4, (
        "free list is not being reused; capacity grew by %d" % grown)


def test_growth_preserves_existing_slots(store):
    handles = []
    for n in range(200):
        i, g = store.alloc()
        store.set_position(i, g, float(n), 0.0, 0.0)
        handles.append((i, g, n))
    for i, g, n in handles:
        assert store.get_position(i, g) == (float(n), 0.0, 0.0)
    for i, g, n in handles:
        store.free(i, g)


def test_recycled_slot_does_not_inherit_prior_transform(store):
    """A reused slot must never inherit the prior occupant's transform."""
    i1, g1 = store.alloc()
    store.set_position(i1, g1, 42.0, -7.0, 3.5)
    distinctive = (2.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 2.0)
    store.set_rotation(i1, g1, distinctive)
    store.free(i1, g1)

    i2, g2 = store.alloc()
    assert store.get_position(i2, g2) == (0.0, 0.0, 0.0)
    assert store.get_rotation(i2, g2) == IDENTITY
    store.free(i2, g2)


def test_get_rotation_col_out_of_range_raises_index_error(store):
    i, g = store.alloc()
    with pytest.raises(IndexError):
        store.get_rotation_col(i, g, -1)
    with pytest.raises(IndexError):
        store.get_rotation_col(i, g, 3)
    store.free(i, g)


def test_get_positions_bulk_matches_individual_reads(store):
    handles = []
    for n in range(50):
        i, g = store.alloc()
        store.set_position(i, g, float(n), float(-n), 0.5)
        handles.append((i, g))
    bulk = store.get_positions(handles)
    assert len(bulk) == len(handles)
    for (i, g), got in zip(handles, bulk):
        assert got == store.get_position(i, g)
    for i, g in handles:
        store.free(i, g)


def test_get_positions_rejects_a_stale_handle(store):
    i, g = store.alloc()
    store.free(i, g)
    with pytest.raises(StaleHandleError):
        store.get_positions([(i, g)])


def test_get_positions_empty_is_empty(store):
    assert store.get_positions([]) == []


def test_get_store_selects_python_backend_for_objectclass(monkeypatch):
    """get_store()'s Python-backend branch is otherwise never exercised: the
    fixture above instantiates PythonTransformStore directly, bypassing
    get_store()'s own selection logic, so nothing proves an ObjectClass
    actually works end-to-end when the native extension is unavailable.

    Force native-detection to fail (as if _dauntless_host were absent) and
    prove a real ObjectClass round-trips position and rotation through the
    resulting PythonTransformStore. Both monkeypatches are undone by the
    fixture on teardown, so later tests see the original singleton.
    """
    import engine.appc.transform_store as ts
    from engine.appc.math import TGMatrix3, TGPoint3
    from engine.appc.objects import ObjectClass

    monkeypatch.setattr(ts, "_STORE", None)
    monkeypatch.setitem(sys.modules, "_dauntless_host", None)

    store = ts.get_store()
    assert isinstance(store, ts.PythonTransformStore)

    o = ObjectClass()
    try:
        o.SetTranslateXYZ(1.5, -2.5, 3.25)
        loc = o.GetWorldLocation()
        assert (loc.x, loc.y, loc.z) == pytest.approx((1.5, -2.5, 3.25))

        axis = TGPoint3(1.0, 2.0, 3.0)
        axis.Scale(1.0 / (14.0 ** 0.5))
        rot = TGMatrix3()
        rot.MakeRotation(0.7, axis)
        o.SetMatrixRotation(rot)
        got = o.GetWorldRotation()
        assert got.as_tuple() == pytest.approx(rot.as_tuple())
    finally:
        # Force the finalizer now rather than relying on gc timing, so the
        # slot is freed from the temporary store before it goes away.
        o._xform_finalizer()


def test_negative_index_raises_stale_handle_error(store):
    """A negative index must surface as StaleHandleError on BOTH backends.

    The native backend's bound functions take std::uint32_t, so a negative
    Python int fails the pybind11 argument conversion with a TypeError
    before the C++ store's own bounds check ever runs — a different
    exception type than the RuntimeError a valid-but-stale handle raises.
    NativeTransformStore must catch both so callers see one contract.
    """
    with pytest.raises(StaleHandleError):
        store.get_position(-1, 0)
    with pytest.raises(StaleHandleError):
        store.set_position(-1, 0, 0.0, 0.0, 0.0)
    with pytest.raises(StaleHandleError):
        store.get_rotation(-1, 0)
    with pytest.raises(StaleHandleError):
        store.set_rotation(-1, 0, IDENTITY)
    with pytest.raises(StaleHandleError):
        store.free(-1, 0)
