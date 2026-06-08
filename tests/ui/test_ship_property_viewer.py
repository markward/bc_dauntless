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


from engine.ui.ship_property_viewer import OrbitCamera, project


def test_orbit_camera_eye_in_front_at_zero_angles():
    cam = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0, yaw=0.0, pitch=0.0)
    eye = cam.eye()
    # At yaw=pitch=0 the eye sits on +/-Y (BC forward) looking back at origin,
    # distance 10 -> one axis is +/-10, others ~0.
    assert round(max(abs(eye[0]), abs(eye[1]), abs(eye[2])), 4) == 10.0


def test_project_point_at_target_lands_at_screen_centre():
    cam = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0, yaw=0.0, pitch=0.0)
    sx, sy, depth, visible = project((0.0, 0.0, 0.0), cam, (800, 600))
    assert visible is True
    assert abs(sx - 400.0) < 0.5 and abs(sy - 300.0) < 0.5


def test_project_point_behind_camera_not_visible():
    cam = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0, yaw=0.0, pitch=0.0)
    # A point far on the far side beyond the target, behind the eye direction.
    far_behind = tuple(c * 1000.0 for c in cam.eye())
    sx, sy, depth, visible = project(far_behind, cam, (800, 600))
    assert visible is False


def test_project_at_extreme_pitch_is_finite_and_visible():
    import math as _m
    cam = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0, yaw=0.0,
                      pitch=_m.pi / 2.0)  # straight-down: would be degenerate
    sx, sy, depth, visible = project((0.0, 0.0, 0.0), cam, (800, 600))
    assert visible is True
    # No NaN/inf, and the target still lands near screen centre.
    assert sx == sx and sy == sy          # not NaN
    assert abs(sx - 400.0) < 1.0 and abs(sy - 300.0) < 1.0
