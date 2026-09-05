"""One contract, run against every TransformStore backend.

Two backends that are never live at the same time are only safe if something
proves they agree. This is that something. Task 3 adds the native backend to
STORE_FACTORIES; until then it runs against the Python one alone.
"""
import pytest

from engine.appc.transform_store import PythonTransformStore, StaleHandleError

STORE_FACTORIES = [pytest.param(PythonTransformStore, id="python")]

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
    assert store.live_count() == 0
    handles = [store.alloc() for _ in range(10)]
    assert store.live_count() == 10
    for i, g in handles[:4]:
        store.free(i, g)
    assert store.live_count() == 6
    for i, g in handles[4:]:
        store.free(i, g)


def test_many_alloc_free_cycles_do_not_leak(store):
    """Torpedoes churn hard; the free list must actually be reused."""
    for _ in range(1000):
        i, g = store.alloc()
        store.free(i, g)
    assert store.live_count() == 0
    assert store.capacity() <= 4, (
        "free list is not being reused; capacity grew to %d" % store.capacity())


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
