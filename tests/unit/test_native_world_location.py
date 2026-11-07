"""GetWorldLocation / GetTranslate build their point natively (phase 6 AI
part 3, task 2): same values, same type, same errors as the old body."""
import random
import struct

import pytest

_h = pytest.importorskip("_dauntless_host")

from engine.appc import ai_native, native_motion, objects
from engine.appc.math import TGPoint3
from engine.appc.objects import ObjectClass
from engine.appc.transform_store import (
    NativeTransformStore, PythonTransformStore, StaleHandleError, get_store)


def _native_only():
    if type(get_store()) is not NativeTransformStore:
        pytest.skip("native transform store not active")


def _bits(p):
    return tuple(struct.pack("<d", v) for v in (p.x, p.y, p.z))


def _old_body(obj):
    x, y, z = get_store().get_position(*obj._xform)
    return TGPoint3(x, y, z)


@pytest.mark.parametrize("name", ["GetWorldLocation", "GetTranslate"])
def test_world_location_values_and_type_match_the_old_body(name):
    _native_only()
    rng = random.Random(7)
    objs = []
    for _ in range(50):
        o = ObjectClass()
        o.SetTranslateXYZ(rng.uniform(-1e6, 1e6), rng.uniform(-1, 1) * 1e-9,
                          rng.choice([0.0, -0.0, rng.uniform(-5, 5)]))
        objs.append(o)
    for o in objs:
        new, old = getattr(o, name)(), _old_body(o)
        assert type(new) is TGPoint3
        assert all(type(v) is float for v in (new.x, new.y, new.z))
        assert [float.hex(v) for v in (new.x, new.y, new.z)] == \
               [float.hex(v) for v in (old.x, old.y, old.z)]
        assert _bits(new) == _bits(old)


@pytest.mark.parametrize("name", ["GetWorldLocation", "GetTranslate"])
def test_a_stale_handle_raises_the_same_error(name):
    _native_only()
    o = ObjectClass()
    with pytest.raises(StaleHandleError) as old:
        get_store().get_position(o._xform[0], o._xform[1] + 1)
    o._xform = (o._xform[0], o._xform[1] + 1)
    with pytest.raises(StaleHandleError) as new:
        getattr(o, name)()
    assert type(new.value) is type(old.value)
    assert str(new.value) == str(old.value)
    assert type(new.value.__cause__) is type(old.value.__cause__)
    assert str(new.value.__cause__) == str(old.value.__cause__)


def test_the_python_store_backend_takes_the_old_path(monkeypatch):
    store = PythonTransformStore()
    monkeypatch.setattr(objects, "get_store", lambda: store)
    o = ObjectClass.__new__(ObjectClass)
    o._xform = store.alloc()
    store.set_position(*o._xform, 1.0, 2.0, 3.0)
    for name in ("GetWorldLocation", "GetTranslate"):
        p = getattr(o, name)()
        assert type(p) is TGPoint3 and (p.x, p.y, p.z) == (1.0, 2.0, 3.0)


def test_a_patched_objects_get_store_is_honoured(monkeypatch):
    class Fake:
        def get_position(self, i, g):
            return (4.0, 5.0, 6.0)
    monkeypatch.setattr(objects, "get_store", lambda: Fake())
    o = ObjectClass.__new__(ObjectClass)
    o._xform = (0, 0)
    for name in ("GetWorldLocation", "GetTranslate"):
        p = getattr(o, name)()
        assert (p.x, p.y, p.z) == (4.0, 5.0, 6.0)


def test_fresh_point_each_call():
    o = ObjectClass()
    o.SetTranslateXYZ(1.0, 2.0, 3.0)
    for name in ("GetWorldLocation", "GetTranslate"):
        a, b = getattr(o, name)(), getattr(o, name)()
        assert a is not b
        a.x = 99.0
        assert getattr(o, name)().x == 1.0 and b.x == 1.0


def test_kernel_m_and_reader_snapshots_still_hold():
    assert native_motion._stock_holds() is True
    from engine.appc.ships import ShipClass
    ship = ShipClass.__new__(ShipClass)
    contract = ai_native.reader_contract("GetWorldLocation")
    assert ai_native.object_reads_are_stock(ship, contract)


@pytest.mark.parametrize("name", ["GetWorldLocation", "GetTranslate"])
def test_the_native_store_path_builds_the_point_natively(monkeypatch, name):
    _native_only()
    assert hasattr(_h, "transform_point")

    def boom(self, i, g):
        raise AssertionError("went through get_position")
    monkeypatch.setattr(NativeTransformStore, "get_position", boom)
    o = ObjectClass()
    o.SetTranslateXYZ(1.0, 2.0, 3.0)
    p = getattr(o, name)()
    assert type(p) is TGPoint3 and (p.x, p.y, p.z) == (1.0, 2.0, 3.0)
