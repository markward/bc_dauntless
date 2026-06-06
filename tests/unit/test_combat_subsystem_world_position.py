"""Tests for combat._subsystem_world_position — body->world via column R."""

from engine.appc.combat import _subsystem_world_position
from engine.appc.math import TGMatrix3, TGPoint3


class _FakeSub:
    def __init__(self, pos):
        self._pos = pos

    def GetPosition(self):
        return self._pos


class _FakeShip:
    def __init__(self, location, rotation=None):
        self._loc = location
        self._rot = rotation

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return self._rot


def test_identity_rotation_passes_position_through_plus_ship_origin():
    ship = _FakeShip(location=TGPoint3(10.0, 20.0, 30.0),
                     rotation=TGMatrix3())  # identity
    sub = _FakeSub(TGPoint3(1.0, 2.0, 3.0))

    p = _subsystem_world_position(ship, sub)

    assert p.x == 11.0
    assert p.y == 22.0
    assert p.z == 33.0


def test_y_rotation_90deg_maps_body_x_to_world_minus_z():
    """Column-vector convention: R · v_body = v_world.
    MakeYRotation(+pi/2) rotates body-X onto world-(-Z).
    """
    import math
    R = TGMatrix3()
    R.MakeYRotation(math.pi / 2.0)
    ship = _FakeShip(location=TGPoint3(0.0, 0.0, 0.0), rotation=R)
    sub = _FakeSub(TGPoint3(1.0, 0.0, 0.0))

    p = _subsystem_world_position(ship, sub)

    assert abs(p.x - 0.0) < 1e-6
    assert abs(p.y - 0.0) < 1e-6
    assert abs(p.z - (-1.0)) < 1e-6


def test_no_rotation_attribute_treats_R_as_identity():
    """Legacy fakes without GetWorldRotation: body == world."""
    class _NoRotShip:
        def GetWorldLocation(self):
            return TGPoint3(5.0, 5.0, 5.0)

    sub = _FakeSub(TGPoint3(1.0, 1.0, 1.0))
    p = _subsystem_world_position(_NoRotShip(), sub)

    assert p.x == 6.0
    assert p.y == 6.0
    assert p.z == 6.0
