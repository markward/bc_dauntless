"""ObjectClass transforms live in the TransformStore, not on the instance.

The three lifecycle tests near the bottom (test_slot_is_released_after_
unregister_and_collection and friends) prove slot release ONLY once an
object has been both ids.unregister()'d and garbage collected -- see each
one's docstring. They do not demonstrate that a slot is released in
production merely by dropping application-level references, because
engine/core/ids._registry keeps every TGObject alive regardless."""
import gc

import pytest

from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.objects import ObjectClass
from engine.appc.transform_store import StaleHandleError, get_store


def test_object_has_a_slot_handle():
    o = ObjectClass()
    assert isinstance(o._xform, tuple) and len(o._xform) == 2


def test_private_position_attribute_is_gone():
    o = ObjectClass()
    assert not hasattr(o, "_position")
    assert not hasattr(o, "_rotation")


def test_position_round_trips_through_accessors():
    o = ObjectClass()
    o.SetTranslateXYZ(1.5, -2.5, 3.25)
    p = o.GetTranslate()
    assert (p.x, p.y, p.z) == (1.5, -2.5, 3.25)
    w = o.GetWorldLocation()
    assert (w.x, w.y, w.z) == (1.5, -2.5, 3.25)


def test_getters_return_independent_copies():
    """Established contract: callers may mutate what they get back, and the
    mutation must not write through to the object."""
    o = ObjectClass()
    o.SetTranslateXYZ(1.0, 2.0, 3.0)
    p = o.GetTranslate()
    p.x = 99.0
    assert o.GetTranslate().x == 1.0


def test_rotation_round_trips():
    o = ObjectClass()
    m = TGMatrix3()
    m.MakeZRotation(0.5)
    o.SetMatrixRotation(m)
    assert o.GetWorldRotation().as_tuple() == m.as_tuple()


def test_set_matrix_rotation_copies_and_does_not_alias():
    """BEHAVIOUR CHANGE, pinned deliberately.

    objects.py previously did `self._rotation = matrix`, storing the caller's
    matrix BY REFERENCE, so mutating it afterwards silently re-oriented the
    object. Writing into the store copies instead. This test records that as a
    decision so nobody 'fixes' it back.
    """
    o = ObjectClass()
    m = TGMatrix3()
    m.MakeIdentity()
    o.SetMatrixRotation(m)
    m.m00 = 99.0
    assert o.GetWorldRotation().m00 == 1.0


def test_get_world_rotation_returns_a_copy():
    o = ObjectClass()
    r = o.GetWorldRotation()
    r.m00 = 42.0
    assert o.GetWorldRotation().m00 == 1.0


def test_direction_helpers_read_columns():
    """GetCol(1) is forward — never GetRow(1)."""
    o = ObjectClass()
    m = TGMatrix3()
    m.Set(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
    o.SetMatrixRotation(m)
    fwd = o.GetWorldForwardTG()
    assert (fwd.x, fwd.y, fwd.z) == (2.0, 5.0, 8.0)


def test_slot_is_released_after_unregister_and_collection():
    """NOT a demonstration of production-time release.

    engine/core/ids._registry holds every TGObject strongly for the whole
    process (nothing calls unregister() for most objects in production —
    see ids.py's own comments and tests/conftest.py's per-test
    _ids._registry.clear()), so weakref.finalize cannot fire, and the slot
    cannot be released, until that strong reference is gone. This test
    manually calls ids.unregister() first to drop it — mirroring the
    established convention in
    tests/unit/test_actions.py::test_object_node_ref_is_weak ("mirror real
    teardown before the GC check") — so what this proves is "the slot is
    released once the object is BOTH unregistered AND collected", not that
    an ordinary drop-all-references is enough on its own.
    """
    from engine.core.ids import unregister
    store = get_store()
    # A prior test's ObjectClass instances lose their _registry entry the
    # moment THIS test's autouse setup fixture clears it (tests/conftest.py),
    # but cyclic garbage (ObjectClass instances sit in cycles, see the class
    # below) isn't actually collected until the next gc.collect() -- which
    # could be the one further down in THIS test. Flush that backlog first so
    # "before" is a stable floor, not a count that a later gc.collect() call
    # would retroactively invalidate.
    gc.collect()
    before = store.live_count()
    o = ObjectClass()
    handle = o._xform
    assert store.live_count() == before + 1
    unregister(o.GetObjID())
    del o
    gc.collect()
    assert store.live_count() == before
    with pytest.raises(StaleHandleError):
        store.get_position(*handle)


def test_slot_released_even_in_a_reference_cycle_after_unregister_and_collection():
    """NOT a demonstration of production-time release -- see the sibling
    test's docstring for why ids.unregister() is called first.

    ObjectClass instances sit in cycles (they are event handlers and the
    event manager holds refs back), which is why release uses
    weakref.finalize rather than __del__: once the registry's strong
    reference is also gone, the finalizer still fires for a cyclic object,
    where a bare __del__ would not be guaranteed to."""
    from engine.core.ids import unregister
    store = get_store()
    gc.collect()  # flush any backlog from a prior test; see the sibling test
    before = store.live_count()
    o = ObjectClass()
    o._self_cycle = o          # deliberate cycle
    handle = o._xform
    unregister(o.GetObjID())
    del o
    gc.collect()
    assert store.live_count() == before
    with pytest.raises(StaleHandleError):
        store.get_position(*handle)


def test_many_objects_do_not_leak_slots_after_unregister_and_collection():
    """NOT a demonstration of production-time release -- see
    test_slot_is_released_after_unregister_and_collection's docstring for
    why ids.unregister() is called first for every object before the
    collection check."""
    from engine.core.ids import unregister
    store = get_store()
    gc.collect()  # flush any backlog from a prior test; see the sibling test
    before = store.live_count()
    objs = [ObjectClass() for _ in range(500)]
    for i in range(len(objs)):
        unregister(objs[i].GetObjID())
    del objs  # no lingering loop-variable reference (the `for o in objs`
              # form leaves the last `o` bound and alive after the loop)
    gc.collect()
    assert store.live_count() == before
