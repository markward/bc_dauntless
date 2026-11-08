"""GetVelocityTG / GetVelocity copy the velocity natively (phase 6 AI part 3,
task 3): same values, type, errors as `TGPoint3(v.x, v.y, v.z)`, and a fresh
object on every call."""
import struct

import pytest

_h = pytest.importorskip("_dauntless_host")

from engine.appc import native_motion, objects, projectiles
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass


def _bits(p):
    return tuple(struct.pack("<d", v) for v in (p.x, p.y, p.z))


def _old(v):
    return TGPoint3(v.x, v.y, v.z)


def _phys(v):
    o = PhysicsObjectClass()
    o.__dict__["_velocity"] = v
    return o


@pytest.mark.parametrize("name", ["GetVelocityTG", "GetVelocity"])
def test_velocity_copy_equals_the_old_body(name):
    for vel in [(1.5, -2.25, 3e-9), (0.0, -0.0, 1e300), (float("inf"), 1.0, 2.0)]:
        o = _phys(TGPoint3(*vel))
        new = getattr(o, name)()
        assert type(new) is TGPoint3
        assert _bits(new) == _bits(_old(o._velocity))
    # a vector written by kernel M
    o = PhysicsObjectClass()
    native_motion._store_velocity(o, 0, 0, (4.0, 5.0, 6.0), 0, 0, 0, 0)
    new = getattr(o, name)()
    assert (new.x, new.y, new.z) == (4.0, 5.0, 6.0)


@pytest.mark.parametrize("name", ["GetVelocityTG", "GetVelocity"])
def test_non_float_components_coerce_like_float(name):
    v = TGPoint3(0.0, 0.0, 0.0)
    v.x, v.y, v.z = 3, True, "2.5"
    new = getattr(_phys(v), name)()
    assert (new.x, new.y, new.z) == (3.0, 1.0, 2.5)
    assert all(type(c) is float for c in (new.x, new.y, new.z))
    v.z = "nope"
    with pytest.raises(ValueError) as old:
        _old(v)
    with pytest.raises(ValueError) as got:
        getattr(_phys(v), name)()
    assert str(got.value) == str(old.value)


@pytest.mark.parametrize("name", ["GetVelocityTG", "GetVelocity"])
def test_velocity_is_a_fresh_object(name):
    o = _phys(TGPoint3(1.0, 2.0, 3.0))
    a, b = getattr(o, name)(), getattr(o, name)()
    assert a is not b and a is not o._velocity
    a.Subtract(TGPoint3(1.0, 1.0, 1.0))
    assert (o._velocity.x, o._velocity.y, o._velocity.z) == (1.0, 2.0, 3.0)
    assert b.x == 1.0


@pytest.mark.parametrize("name", ["GetVelocityTG", "GetVelocity"])
def test_a_non_point_velocity_behaves_like_the_old_body(name):
    class P:
        x, y, z = 1, 2.5, False
    new = getattr(_phys(P()), name)()
    assert type(new) is TGPoint3 and (new.x, new.y, new.z) == (1.0, 2.5, 0.0)

    class NoZ:
        x, y = 1.0, 2.0
    with pytest.raises(AttributeError) as old:
        _old(NoZ())
    with pytest.raises(AttributeError) as got:
        getattr(_phys(NoZ()), name)()
    assert str(got.value) == str(old.value)

    class Sub(TGPoint3):
        __slots__ = ()
    s = Sub(7.0, 8.0, 9.0)
    new = getattr(_phys(s), name)()
    assert type(new) is TGPoint3 and (new.x, new.y, new.z) == (7.0, 8.0, 9.0)


def test_torpedo_velocity_copy():
    t = projectiles.Torpedo()
    t._velocity = TGPoint3(1.0, 2.0, 3.0)
    a = t.GetVelocityTG()
    assert type(a) is TGPoint3 and (a.x, a.y, a.z) == (1.0, 2.0, 3.0)
    assert a is not t.GetVelocityTG() and a is not t._velocity
    a.Subtract(TGPoint3(1.0, 1.0, 1.0))
    assert t._velocity.x == 1.0


@pytest.mark.parametrize("fn", [PhysicsObjectClass.GetVelocityTG,
                                PhysicsObjectClass.GetVelocity,
                                projectiles.Torpedo.GetVelocityTG])
def test_copy_is_native(monkeypatch, fn):
    assert hasattr(_h, "point_copy")
    is_torp = fn is projectiles.Torpedo.GetVelocityTG
    owner = projectiles.Torpedo() if is_torp else PhysicsObjectClass()
    if is_torp:
        owner._velocity = TGPoint3(1.0, 2.0, 3.0)
    else:
        owner.__dict__["_velocity"] = TGPoint3(1.0, 2.0, 3.0)

    def boom(*a, **k):
        raise AssertionError("went through TGPoint3.__init__")
    monkeypatch.setattr(TGPoint3, "__init__", boom)
    p = fn(owner)
    assert (p.x, p.y, p.z) == (1.0, 2.0, 3.0)


def test_a_stale_binary_is_an_attribute_error(monkeypatch):
    def missing(p):
        raise AttributeError(
            "module '_dauntless_host' has no attribute 'point_copy'")
    monkeypatch.setattr(objects, "_point_copy", missing)
    with pytest.raises(AttributeError, match="point_copy"):
        _phys(TGPoint3(1.0, 2.0, 3.0)).GetVelocityTG()
