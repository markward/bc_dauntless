"""The native TGPoint3 constructor (phase 6 AI part 3, task 1)."""
import math
import struct

import pytest

_h = pytest.importorskip("_dauntless_host")

from engine.appc.math import TGPoint3


def _bits(v):
    return struct.pack("<d", v)


VALUES = [
    (1.5, -2.25, 3.125),
    (-0.0, 0.0, -0.0),
    (math.nan, math.inf, -math.inf),
    (1e-320, 1.7976931348623157e308, 0.1),
]


@pytest.mark.parametrize("xyz", VALUES)
def test_make_point_equals_the_python_constructor(xyz):
    native = _h.point_make(*xyz)
    ref = TGPoint3(*xyz)
    assert type(native) is TGPoint3
    for name in ("x", "y", "z"):
        n, r = getattr(native, name), getattr(ref, name)
        assert type(n) is float
        assert float.hex(n) == float.hex(r)
        assert _bits(n) == _bits(r)
    assert not hasattr(native, "__dict__")


def test_make_point_returns_a_fresh_object_each_call():
    a = _h.point_make(1.0, 2.0, 3.0)
    b = _h.point_make(1.0, 2.0, 3.0)
    assert a is not b
    a.x = 99.0
    a.SetXYZ(7.0, 8.0, 9.0)
    assert (b.x, b.y, b.z) == (1.0, 2.0, 3.0)
    assert (a.x, a.y, a.z) == (7.0, 8.0, 9.0)
    assert a.Length() > 0 and b == TGPoint3(1.0, 2.0, 3.0)


def test_make_point_is_garbage_collectable_like_the_python_one():
    import gc
    import weakref  # TGPoint3 has no __weakref__ slot: must stay that way
    p = _h.point_make(1.0, 2.0, 3.0)
    with pytest.raises(TypeError):
        weakref.ref(p)
    assert gc.is_tracked(p) == gc.is_tracked(TGPoint3(1.0, 2.0, 3.0))


def test_register_rejects_a_class_with_another_layout():
    class Wrong:
        __slots__ = ("a", "b", "c")

        def __init__(self, a=0.0, b=0.0, c=0.0):
            pass

    class Extra:
        __slots__ = ("x", "y", "z", "w")

    class NoSlots:
        pass

    class OwnNew:
        __slots__ = ("x", "y", "z")

        def __new__(cls, *a):
            return object.__new__(cls)

    for bad in (Wrong, Extra, NoSlots, OwnNew):
        with pytest.raises(ValueError):
            _h.point_register(bad)
    p = _h.point_make(1.0, 2.0, 3.0)
    assert type(p) is TGPoint3
