import App
from engine.appc.bridge_set import CameraObjectClass_Create
from engine.appc.camera_modes import LockedMode, ChaseMode, TargetMode
from engine.appc.camera_modes import PlacementMode, ZoomTargetMode
from engine.appc.math import TGPoint3


def _cam():
    return CameraObjectClass_Create(1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0, "CutsceneCam")


def test_get_named_mode_builds_and_caches():
    c = _cam()
    m = c.GetNamedCameraMode("Locked")
    assert isinstance(m, LockedMode)
    assert c.GetNamedCameraMode("Locked") is m          # cached, same instance
    assert isinstance(c.GetNamedCameraMode("Chase"), ChaseMode)
    assert isinstance(c.GetNamedCameraMode("ReverseChase"), ChaseMode)
    assert isinstance(c.GetNamedCameraMode("Target"), TargetMode)


def test_get_named_mode_unknown_is_none():
    assert _cam().GetNamedCameraMode("Bogus") is None


def test_push_pop_current():
    c = _cam()
    assert c.GetCurrentCameraMode() is None
    m = c.GetNamedCameraMode("Locked")
    c.PushCameraMode(m)
    assert c.GetCurrentCameraMode() is m
    assert c.GetCurrentCameraMode(0) is m               # NewMode calls with arg 0
    c.PopCameraMode()
    assert c.GetCurrentCameraMode() is None


def test_push_seeds_initial_pose_from_camera():
    c = _cam()                                           # position (1,2,3)
    m = c.GetNamedCameraMode("Locked")
    c.PushCameraMode(m)
    assert m._cur is not None
    assert m._cur[0] == (1.0, 2.0, 3.0)                  # seeded eye = camera pos


def test_camera_new_mode_pushes_live_mode():
    """End-to-end through the SDK's Camera.NewMode."""
    import Camera
    c = _cam()
    ship = App.ShipClass_Create("Galaxy")
    ship.SetTranslate(TGPoint3(0.0, 0.0, 0.0))
    ok = Camera.NewMode(c, "Chase", 0, 1, [("Target", ship)])
    assert ok == 1
    assert isinstance(c.GetCurrentCameraMode(), ChaseMode)
    assert c.GetCurrentCameraMode().GetAttrIDObject("Target") is ship


def test_factory_builds_placement_and_zoomtarget():
    c = _cam()
    assert isinstance(c.GetNamedCameraMode("Placement"), PlacementMode)
    assert isinstance(c.GetNamedCameraMode("ZoomTarget"), ZoomTargetMode)


def test_get_named_mode_tags_owner_camera():
    c = _cam()
    m = c.GetNamedCameraMode("Placement")
    assert m._owner_camera is c


def test_pop_camera_mode_by_name_string():
    c = _cam()
    m = c.GetNamedCameraMode("Placement")
    c.PushCameraMode(m)
    assert c.GetCurrentCameraMode() is m
    popped = c.PopCameraMode("Placement")            # Camera.LowPop passes a str
    assert popped is m
    assert c.GetCurrentCameraMode() is None


def test_pop_camera_mode_unknown_name_is_none():
    c = _cam()
    c.PushCameraMode(c.GetNamedCameraMode("Placement"))
    assert c.PopCameraMode("NeverPushed") is None


# ── BC-convention name resolution ─────────────────────────────────────────────
# BC expects 18 named modes on the player camera (Camera.py:685-703); our
# _MODE_FACTORY table carried 7. The rest resolve through the SDK's own builders
# in CameraModes.py, which is where BC keeps each mode's authored attrs.

def test_named_mode_firstperson_resolves_to_locked():
    """CameraModes.FirstPerson builds kind "Locked" with a zeroed Position."""
    assert isinstance(_cam().GetNamedCameraMode("FirstPerson"), LockedMode)


def test_named_mode_widetarget_resolves_to_target():
    assert isinstance(_cam().GetNamedCameraMode("WideTarget"), TargetMode)


def test_viewscreen_directions_differ_by_forward_attr():
    """The six Viewscreen* directions are all LockedMode; only their authored
    Forward attr distinguishes them. Resolving them to a bare class would make
    forward and left identical."""
    c = _cam()
    fwd = c.GetNamedCameraMode("ViewscreenForward").GetAttrPoint("Forward")
    left = c.GetNamedCameraMode("ViewscreenLeft").GetAttrPoint("Forward")
    assert (fwd.x, fwd.y, fwd.z) != (left.x, left.y, left.z)


def test_reverse_chase_still_looks_ahead_of_target():
    """REGRESSION GUARD, not a new behaviour: CameraModes.ReverseChase builds
    kind "Chase" and differs from Chase only by a DefaultPosition attr that
    ChaseMode does not read. Resolving it through CameraModes would silently
    flip it to a normal chase, so _MODE_FACTORY must stay authoritative here."""
    c = _cam()
    m = c.GetNamedCameraMode("ReverseChase")
    m.SetAttrIDObject("Target", _FakeShip())
    eye, _fwd, _up = m.Update()
    assert eye[1] > 0.0            # ahead of the target (+Y), not behind


class _FakeShip:
    def GetWorldLocation(self):
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        from engine.appc.math import TGMatrix3
        return TGMatrix3()
