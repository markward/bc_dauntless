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


# ── Mode hierarchy (AddModeHierarchy for real) ───────────────────────────────
# BC pushes an always-invalid marker mode and resolves the EFFECTIVE mode by
# walking name->name hierarchy edges (Camera.py:630-646). The cinematic F-keys
# re-point one edge (CinematicInterfaceHandlers.CameraChase:339) — the
# hierarchy IS the camera selector. GetCurrentCameraMode(0) is the raw top
# (NewMode's identity compare, Camera.py:463); no-arg is resolved
# (Camera.py:478 "may not be the mode we pushed").

def _valid_chase(cam, ship):
    m = cam.GetNamedCameraMode("Chase")
    m.SetAttrIDObject("Target", ship)
    return m


def test_add_named_camera_mode_preempts_the_builder():
    c = _cam()
    marker = ChaseMode()                     # bare: no Target -> never valid
    c.AddNamedCameraMode("InvalidCinematic", marker)
    assert c.GetNamedCameraMode("InvalidCinematic") is marker
    assert marker._named == "InvalidCinematic"


def test_resolution_walks_an_edge_to_a_valid_mode():
    c = _cam()
    ship = _FakeShip()
    marker = ChaseMode()
    c.AddNamedCameraMode("InvalidCinematic", marker)
    chase = _valid_chase(c, ship)
    c.AddModeHierarchy("InvalidCinematic", "Chase")
    c.PushCameraMode(marker)
    assert c.GetCurrentCameraMode(0) is marker          # raw
    assert c.GetCurrentCameraMode() is chase            # resolved


def test_edges_replace_not_append():
    c = _cam()
    ship = _FakeShip()
    marker = ChaseMode()
    c.AddNamedCameraMode("InvalidCinematic", marker)
    chase = _valid_chase(c, ship)
    target = c.GetNamedCameraMode("Target")
    target.SetAttrIDObject("Source", ship)
    target.SetAttrIDObject("Target", ship)
    c.AddModeHierarchy("InvalidCinematic", "Chase")
    c.AddModeHierarchy("InvalidCinematic", "Target")    # F-key re-point
    c.PushCameraMode(marker)
    assert c.GetCurrentCameraMode() is target


def test_resolution_dead_end_returns_the_invalid_tail():
    """A chain that never reaches a valid mode returns the last (invalid) mode
    — callers gate on IsValid(), so the director keeps the frame."""
    c = _cam()
    marker = ChaseMode()
    c.AddNamedCameraMode("InvalidCinematic", marker)
    c.PushCameraMode(marker)
    resolved = c.GetCurrentCameraMode()
    assert resolved is marker and not resolved.IsValid()


def test_resolution_survives_an_edge_cycle():
    c = _cam()
    a, b = ChaseMode(), ChaseMode()
    c.AddNamedCameraMode("A", a)
    c.AddNamedCameraMode("B", b)
    c.AddModeHierarchy("A", "B")
    c.AddModeHierarchy("B", "A")
    c.PushCameraMode(a)
    resolved = c.GetCurrentCameraMode()      # must terminate
    assert resolved in (a, b)


def test_camera_without_edges_resolves_to_raw_top():
    """Cameras nobody seeds (mission CutsceneCam) behave exactly as today."""
    c = _cam()
    m = c.GetNamedCameraMode("Locked")
    c.PushCameraMode(m)
    assert c.GetCurrentCameraMode() is m


def test_invalid_torpcam_falls_back_to_chase_through_the_hierarchy():
    """F4 (CinematicInterfaceHandlers.CameraTorpCam:387) re-points
    InvalidCinematic -> TorpCam, and BC authors TorpCam -> Chase
    (Camera.py:642). So with nothing in the air the composition — NOT any
    fallback of TorpCameraMode's own — must land on the Chase camera. Verified
    rather than assumed, because "report invalid and let the hierarchy do it"
    is only correct if the hierarchy really does it."""
    from engine.appc.camera_modes import TorpCameraMode
    c = _cam()
    ship = _FakeShip()
    marker = ChaseMode()
    c.AddNamedCameraMode("InvalidCinematic", marker)
    c.AddModeHierarchy("InvalidCinematic", "TorpCam")
    c.AddModeHierarchy("TorpCam", "Chase")
    torpcam = c.GetNamedCameraMode("TorpCam")        # via CameraModes.TorpCam
    assert isinstance(torpcam, TorpCameraMode)
    torpcam.SetAttrIDObject("Target", ship)          # the player, per Camera.py:702
    chase = _valid_chase(c, ship)
    c.PushCameraMode(marker)
    assert not torpcam.IsValid()                     # no torpedo in flight
    assert c.GetCurrentCameraMode() is chase


def test_named_torpcam_carries_the_sdk_authored_attrs():
    """The named-mode path runs CameraModes.TorpCam, which is where BC keeps the
    seven authored numbers — a bare class would silently lose them."""
    m = _cam().GetNamedCameraMode("TorpCam")
    assert m.GetAttrFloat("StartDistance") == 4.0
    assert m.GetAttrFloat("LaterDistance") == 8.0
    assert m.GetAttrFloat("MoveDistanceTime") == 6.0
    assert m.GetAttrFloat("DelayAfterTorpGone") == 2.0


def test_resolution_walks_two_hops_through_builder_modes():
    """InvalidSpace -> Target -> Chase: builder-created modes must carry a
    _named tag or the walk dead-ends at its first hop (the bug this pins:
    GetNamedCameraMode's builder path once stored modes untagged)."""
    c = _cam()
    ship = _FakeShip()
    marker = ChaseMode()
    c.AddNamedCameraMode("InvalidSpace", marker)
    c.AddModeHierarchy("InvalidSpace", "Target")
    c.AddModeHierarchy("Target", "Chase")
    c.GetNamedCameraMode("Target")               # built, but never made valid
    chase = c.GetNamedCameraMode("Chase")
    chase.SetAttrIDObject("Target", ship)
    c.PushCameraMode(marker)
    assert c.GetCurrentCameraMode() is chase
