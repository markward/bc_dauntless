import math
from engine.appc.math import TGPoint3, TGMatrix3
from engine.ui.ship_property_viewer import subsystem_world_position


class _FakeShip:
    def __init__(self, loc, rot):
        self._loc, self._rot = loc, rot
    def GetWorldLocation(self):
        return self._loc
    def GetWorldRotation(self):
        return self._rot


class _FakeSub:
    """Subsystem with a model-local mount and a parent ship."""
    def __init__(self, pos, ship):
        self._pos, self._ship = pos, ship
    def GetPosition(self):
        return None if self._pos is None else TGPoint3(*self._pos)
    def _climb_to_ship(self):
        return self._ship


def test_world_position_identity_rotation_adds_offset():
    ship = _FakeShip(TGPoint3(10.0, 0.0, 0.0), TGMatrix3())  # identity
    sub = _FakeSub((0.0, 1.0, 0.5), ship)
    w = subsystem_world_position(sub)
    assert (round(w.x, 5), round(w.y, 5), round(w.z, 5)) == (10.0, 1.0, 0.5)


def test_world_position_yaw_rotates_offset_columnvec():
    rot = TGMatrix3(); rot.MakeZRotation(math.pi / 2.0)  # +90 deg about Z
    ship = _FakeShip(TGPoint3(0.0, 0.0, 0.0), rot)
    sub = _FakeSub((0.0, 1.0, 0.0), ship)   # body +Y
    w = subsystem_world_position(sub)
    # Column-vector R.(0,1,0): +Y maps to -X for a +90 deg Z rotation.
    assert round(w.x, 5) == -1.0 and round(w.y, 5) == 0.0


def test_world_position_none_mount_returns_ship_location():
    ship = _FakeShip(TGPoint3(3.0, 4.0, 5.0), TGMatrix3())
    sub = _FakeSub(None, ship)
    w = subsystem_world_position(sub)
    assert (w.x, w.y, w.z) == (3.0, 4.0, 5.0)
