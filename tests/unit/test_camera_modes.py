import math
from engine.appc.camera_modes import CameraMode, LockedMode, SWEEP_TAU_S
from engine.appc.math import TGPoint3, TGMatrix3


class _FakeTarget:
    """Minimal stand-in for an ObjectClass target."""
    def __init__(self, loc, rot=None, radius=1.0):
        self._loc = TGPoint3(*loc)
        self._rot = rot if rot is not None else TGMatrix3()  # identity
        self._radius = radius

    def GetWorldLocation(self):
        return TGPoint3(self._loc.x, self._loc.y, self._loc.z)

    def GetWorldRotation(self):
        return self._rot

    def GetRadius(self):
        return self._radius


def test_locked_mode_snap_identity_rotation():
    t = _FakeTarget((100.0, 0.0, 0.0))
    m = LockedMode()
    m.SetAttrIDObject("Target", t)
    m.SetAttrPoint("Position", TGPoint3(0.0, -10.0, 0.0))   # 10 GU behind (model -Y)
    m.SetAttrPoint("Forward", TGPoint3(0.0, 1.0, 0.0))
    m.SetAttrPoint("Up", TGPoint3(0.0, 0.0, 1.0))
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()                                # no dt ⇒ snap
    assert eye == (100.0, -10.0, 0.0)
    assert fwd == (0.0, 1.0, 0.0)
    assert up == (0.0, 0.0, 1.0)


def test_locked_mode_applies_target_rotation():
    # Target yawed 180° about Z: model -Y maps to world +Y; model +Y to world -Y.
    r = TGMatrix3().MakeZRotation(math.pi)
    t = _FakeTarget((0.0, 0.0, 0.0), rot=r)
    m = LockedMode()
    m.SetAttrIDObject("Target", t)
    m.SetAttrPoint("Position", TGPoint3(0.0, -10.0, 0.0))
    m.SetAttrPoint("Forward", TGPoint3(0.0, 1.0, 0.0))
    m.SetAttrPoint("Up", TGPoint3(0.0, 0.0, 1.0))
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()
    assert abs(eye[1] - 10.0) < 1e-6      # -10 model-Y → +10 world-Y
    assert abs(fwd[1] - (-1.0)) < 1e-6    # +Y model-fwd → -Y world


def test_locked_mode_invalid_without_target():
    m = LockedMode()
    assert not m.IsValid()


def test_camera_mode_obj_ids_unique():
    a, b = LockedMode(), LockedMode()
    assert a.GetObjID() != b.GetObjID()


def test_sweep_converges_toward_ideal():
    # Gap kept below _SWEEP_BREAK_EYE_GU so this exercises the GLIDE, not the
    # discontinuity cut (a >10 GU single-frame gap is a teleport and now cuts —
    # see test_sweep_breaks_on_target_teleport).
    t = _FakeTarget((5.0, 0.0, 0.0))
    m = LockedMode()
    m.SetAttrIDObject("Target", t)
    m.SetAttrPoint("Position", TGPoint3(0.0, 0.0, 0.0))
    m.SetAttrPoint("Forward", TGPoint3(0.0, 1.0, 0.0))
    m.SetAttrPoint("Up", TGPoint3(0.0, 0.0, 1.0))
    m.set_initial_pose((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    # One small step does NOT reach the ideal...
    eye1, _, _ = m.Update(0.016)
    assert 0.0 < eye1[0] < 5.0
    # ...but many steps do.
    for _ in range(600):
        eye, _, _ = m.Update(0.016)
    assert abs(eye[0] - 5.0) < 0.1


def test_dt_zero_does_not_snap_mid_sweep():
    """Regression test for Fix 1: dt=0.0 must NOT snap; only dt=None snaps.

    A cutscene camera mid-sweep should freeze (not jump to ideal) when dt=0
    (e.g., sim paused). The buggy condition `not dt` treats 0.0 as falsy and
    incorrectly snaps to the ideal; it should test `dt is None` explicitly.
    """
    # Gap below _SWEEP_BREAK_EYE_GU so this tests the glide/freeze, not the cut.
    t = _FakeTarget((5.0, 0.0, 0.0))
    m = LockedMode()
    m.SetAttrIDObject("Target", t)
    m.SetAttrPoint("Position", TGPoint3(0.0, 0.0, 0.0))
    m.SetAttrPoint("Forward", TGPoint3(0.0, 1.0, 0.0))
    m.SetAttrPoint("Up", TGPoint3(0.0, 0.0, 1.0))

    # Seed into mid-sweep: eye starts at origin, target ideal at (5, 0, 0)
    m.set_initial_pose((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))

    # One small dt step glides partway.
    eye1, _, _ = m.Update(0.016)
    assert 0.0 < eye1[0] < 5.0

    # Now call Update(0.0) (sim paused). Should NOT snap to ideal.
    # The returned eye should be IDENTICAL to eye1 (frozen at mid-sweep point).
    eye2, _, _ = m.Update(0.0)
    assert eye2 == eye1, f"dt=0.0 must freeze the sweep; got {eye2} != {eye1}"


from engine.appc.camera_modes import (
    ChaseMode, TargetMode, CHASE_DEFAULT_DISTANCE,
)


def test_chase_mode_sits_behind_target():
    """Bare ChaseMode falls back to BC's authored Chase attrs: behind (-Y) with
    a slight up-tilt, at Distance x radius."""
    t = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)  # identity rot: fwd = +Y (GetCol(1))
    m = ChaseMode()
    m.SetAttrIDObject("Target", t)
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()
    assert eye[1] < 0.0                         # behind
    assert eye[2] > 0.0                         # authored up-tilt applied
    assert fwd[1] > 0.9                         # looking toward the ship (+Y)
    reach = math.sqrt(eye[0] ** 2 + eye[1] ** 2 + eye[2] ** 2)
    assert abs(reach - CHASE_DEFAULT_DISTANCE * 1.0) < 1e-6


def test_reverse_chase_sits_in_front():
    t = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    m = ChaseMode()
    m.SetAttrPoint("DefaultPosition", TGPoint3(0.0, 1.0, 0.1))   # ReverseChase
    m.SetAttrIDObject("Target", t)
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()
    assert eye[1] > 0.0                           # in front (+Y)
    assert fwd[1] < -0.9                          # looking back toward ship


def test_chase_mode_applies_target_rotation():
    # Target yawed 180° about Z: body -Y "behind" maps to world +Y (in front).
    r = TGMatrix3().MakeZRotation(math.pi)
    t = _FakeTarget((0.0, 0.0, 0.0), rot=r, radius=1.0)
    m = ChaseMode()
    m.SetAttrIDObject("Target", t)
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()
    assert eye[1] > 0.0                         # -Y body offset → +Y world
    assert eye[2] > 0.0                         # Z offset unaffected by Z-rotation


def test_target_mode_looks_from_source_to_target():
    src = _FakeTarget((0.0, 0.0, 0.0))
    dst = _FakeTarget((0.0, 100.0, 0.0))
    m = TargetMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", dst)
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()
    assert eye == (0.0, 0.0, 0.0)
    assert abs(fwd[1] - 1.0) < 1e-6              # +Y toward dst


def test_chase_invalid_without_target():
    assert not ChaseMode().IsValid()


def test_target_invalid_without_both():
    m = TargetMode()
    m.SetAttrIDObject("Source", _FakeTarget((0.0, 0.0, 0.0)))
    assert not m.IsValid()


from engine.appc.camera_modes import _target_alive
from engine.appc.placement import Waypoint


class _Dying:
    def IsDying(self):
        return 1


class _NotDying:
    def IsDying(self):
        return 0


def test_target_alive_waypoint_reads_alive():
    # A Waypoint does not implement IsDying (DamageableObject surface) and
    # never dies, so it must read as alive. Decided on the MRO: hasattr /
    # getattr cannot answer it, because TGObject.__getattr__ hands back a
    # truthy _Stub for any unknown engine name.
    assert _target_alive(Waypoint()) is True


def test_target_alive_none_is_dead():
    assert _target_alive(None) is False


def test_target_alive_real_is_dying():
    assert _target_alive(_Dying()) is False
    assert _target_alive(_NotDying()) is True


from engine.appc.camera_modes import PlacementMode


def test_placement_mode_eye_at_source_looks_at_target():
    src = _FakeTarget((-50.0, 0.0, 0.0))          # placement 50 GU to port
    tgt = _FakeTarget((0.0, 0.0, 0.0))            # ship at origin
    m = PlacementMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", tgt)
    eye, fwd, up = m.Update()                     # no dt => snap to ideal
    assert eye == (-50.0, 0.0, 0.0)
    assert abs(fwd[0] - 1.0) < 1e-6               # looks +X toward the ship
    assert up == (0.0, 0.0, 1.0)                  # source col2 (identity)


def test_placement_mode_target_none_looks_along_source_forward():
    src = _FakeTarget((-50.0, 0.0, 0.0))
    m = PlacementMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", None)
    eye, fwd, up = m.Update()
    assert eye == (-50.0, 0.0, 0.0)
    assert fwd == (0.0, 1.0, 0.0)                 # source col1 (identity forward)


def test_placement_mode_target_offset_world_shifts_lookat():
    src = _FakeTarget((0.0, -50.0, 0.0))          # 50 GU behind (model -Y)
    tgt = _FakeTarget((0.0, 0.0, 0.0))
    m = PlacementMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", tgt)
    m.SetAttrPoint("TargetOffsetWorld", TGPoint3(0.0, 0.0, 20.0))  # look 20 GU up
    eye, fwd, up = m.Update()
    # look-at = (0,0,20) from (0,-50,0) => mostly +Y, some +Z.
    assert fwd[1] > 0.0 and fwd[2] > 0.0


def test_placement_mode_invalid_without_source():
    m = PlacementMode()
    m.SetAttrIDObject("Target", _FakeTarget((0.0, 0.0, 0.0)))
    assert not m.IsValid()


def test_placement_mode_invalid_when_target_dead():
    m = PlacementMode()
    m.SetAttrIDObject("Source", _FakeTarget((-50.0, 0.0, 0.0)))
    m.SetAttrIDObject("Target", _Dying())
    assert not m.IsValid()


from engine.appc.camera_modes import ZoomTargetMode


def test_zoom_target_mode_eye_at_source_looks_at_target():
    src = _FakeTarget((5.0, 0.0, 0.0))
    tgt = _FakeTarget((5.0, 10.0, 0.0))
    m = ZoomTargetMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", tgt)
    eye, fwd, up = m.Update()
    assert eye == (5.0, 0.0, 0.0)
    assert abs(fwd[1] - 1.0) < 1e-6                # looks +Y toward the target


def test_zoom_target_mode_source_none_uses_owner_camera():
    tgt = _FakeTarget((0.0, 100.0, 0.0))
    m = ZoomTargetMode()
    m._owner_camera = _FakeTarget((0.0, 0.0, 0.0))  # camera at origin
    m.SetAttrIDObject("Target", tgt)
    # Source left unset => falls back to the owning camera's pose.
    eye, fwd, up = m.Update()
    assert eye == (0.0, 0.0, 0.0)
    assert abs(fwd[1] - 1.0) < 1e-6


def test_zoom_target_mode_invalid_without_source_or_owner():
    m = ZoomTargetMode()
    m.SetAttrIDObject("Target", _FakeTarget((0.0, 10.0, 0.0)))
    assert not m.IsValid()                          # no Source, no owner camera


def test_zoom_target_mode_invalid_when_target_dead():
    m = ZoomTargetMode()
    m.SetAttrIDObject("Source", _FakeTarget((0.0, 0.0, 0.0)))
    m.SetAttrIDObject("Target", _Dying())
    assert not m.IsValid()


from engine.appc.camera_modes import (
    CameraMode_Create, ChaseMode, TargetMode, PlaceByDirectionMode,
)


def test_camera_mode_create_dispatches_on_kind():
    from engine.appc.camera_modes import LockedMode
    assert isinstance(CameraMode_Create("Locked"), LockedMode)
    assert isinstance(CameraMode_Create("Chase"), ChaseMode)
    assert isinstance(CameraMode_Create("Target"), TargetMode)
    assert isinstance(CameraMode_Create("Placement"), PlacementMode)
    assert isinstance(CameraMode_Create("ZoomTarget"), ZoomTargetMode)


def test_camera_mode_create_reverse_chase_is_reversed():
    """Reversal is the DefaultPosition sign, not a constructor flag."""
    m = CameraMode_Create("ReverseChase")
    assert isinstance(m, ChaseMode)
    m.SetAttrIDObject("Target", _FakeTarget((0.0, 0.0, 0.0), radius=1.0))
    m.SnapToIdealPosition()
    eye, _fwd, _up = m.Update()
    assert eye[1] > 0.0                          # ahead of the target


def test_camera_mode_create_default_is_place_by_direction():
    assert isinstance(CameraMode_Create("PlaceByDirection"), PlaceByDirectionMode)
    assert isinstance(CameraMode_Create("Bogus"), PlaceByDirectionMode)


def test_camera_mode_create_tags_owner_camera():
    sentinel = object()
    assert CameraMode_Create("Chase", sentinel)._owner_camera is sentinel


def test_sweep_breaks_on_target_teleport():
    """A large jump in the ideal (teleport / set-swap) CUTS the sweep instead of
    gliding: the docking cutscene begins watching the ship, then the ship is
    teleported to the docking entry — smoothing that jump reads as a swoop."""
    t = _FakeTarget((0.0, 0.0, 0.0))
    m = LockedMode()
    m.SetAttrIDObject("Target", t)
    m.SetAttrPoint("Position", TGPoint3(0.0, -10.0, 0.0))
    m.SetAttrPoint("Forward", TGPoint3(0.0, 1.0, 0.0))
    m.SetAttrPoint("Up", TGPoint3(0.0, 0.0, 1.0))
    m.Update()                                  # first frame snaps to start ideal
    # Teleport the target far away.
    t._loc = TGPoint3(500.0, 300.0, -200.0)
    eye, _fwd, _up = m.Update(dt=1.0 / 60.0)    # WITH dt would glide; jump cuts
    assert eye == (500.0, 290.0, -200.0)        # cut straight to the new pose


def test_sweep_glides_on_small_tracking_motion():
    """Ordinary frame-to-frame tracking still glides — the discontinuity break
    must not turn smooth tracking into a cut."""
    t = _FakeTarget((0.0, 0.0, 0.0))
    m = LockedMode()
    m.SetAttrIDObject("Target", t)
    m.SetAttrPoint("Position", TGPoint3(0.0, -10.0, 0.0))
    m.SetAttrPoint("Forward", TGPoint3(0.0, 1.0, 0.0))
    m.SetAttrPoint("Up", TGPoint3(0.0, 0.0, 1.0))
    m.Update()                                  # snap to start
    t._loc = TGPoint3(1.0, 0.0, 0.0)            # 1 GU tracking step
    eye, _fwd, _up = m.Update(dt=1.0 / 60.0)
    assert 0.0 < eye[0] < 1.0                   # glided partway, not snapped


# ── Kind-string dispatch ──────────────────────────────────────────────────────
# CameraModes.py's builders are the SDK's own mode factories, and the kind
# string they pass to CameraMode_Create is NOT always the named-mode key that
# Camera.NewMode looks up. CameraModes.Placement (CameraModes.py:165) is
# registered under the name "Placement" but builds kind "PlacementWatch".
from engine.appc.camera_modes import CameraMode_Create


def test_camera_mode_create_placementwatch_kind_returns_placement_mode():
    """CameraModes.Placement passes kind "PlacementWatch", not "Placement"."""
    assert isinstance(CameraMode_Create("PlacementWatch"), PlacementMode)


# ── Chase geometry comes from the authored attrs ──────────────────────────────
# BC ships ONE Chase mode class. CameraModes.Chase and CameraModes.ReverseChase
# both build kind "Chase" and differ only by the sign of DefaultPosition
# (CameraModes.py:22 vs :40). Distance/Minimum/Maximum are radius multiples, as
# our own player chase camera independently is (engine/cameras/__init__.py).

def test_chase_distance_is_radius_relative():
    """Eye sits Distance x target radius along DefaultPosition, so the camera
    pulls back for a big hull instead of sitting a fixed distance from every
    ship."""
    t = _FakeTarget((0.0, 0.0, 0.0), radius=2.0)
    m = ChaseMode()
    m.SetAttrIDObject("Target", t)
    m.SetAttrPoint("DefaultPosition", TGPoint3(0.0, -1.0, 0.0))
    m.SetAttrFloat("Distance", 4.0)
    m.SnapToIdealPosition()
    eye, _fwd, _up = m.Update()
    assert abs(eye[1] + 8.0) < 1e-6          # 4.0 x radius 2.0, behind


def test_chase_scales_with_a_bigger_hull():
    """Same attrs, bigger ship, further back — the point of radius-relative."""
    m = ChaseMode()
    m.SetAttrIDObject("Target", _FakeTarget((0.0, 0.0, 0.0), radius=6.0))
    m.SetAttrPoint("DefaultPosition", TGPoint3(0.0, -1.0, 0.0))
    m.SetAttrFloat("Distance", 4.0)
    m.SnapToIdealPosition()
    eye, _fwd, _up = m.Update()
    assert abs(eye[1] + 24.0) < 1e-6


# ── DropAndWatch ──────────────────────────────────────────────────────────────
# BC's DEFAULT cinematic mode (Camera.py:641 wires
# AddModeHierarchy("InvalidCinematic", "DropAndWatch")), so bare F9 lands here.
# The camera DROPS to a fixed world point and WATCHES the ship fly past,
# re-dropping once the ship gets too far away.
from engine.appc.camera_modes import DropAndWatchMode


def test_camera_mode_create_dispatches_dropandwatch():
    """CameraModes.DropAndWatch (CameraModes.py:145) builds kind "DropAndWatch";
    it used to fall through to the always-invalid PlaceByDirection attr bag."""
    assert isinstance(CameraMode_Create("DropAndWatch"), DropAndWatchMode)


def test_drop_and_watch_invalid_without_target():
    assert not DropAndWatchMode().IsValid()


class _MovingTarget(_FakeTarget):
    """_FakeTarget plus the PhysicsObjectClass velocity surface."""
    def __init__(self, loc, vel, rot=None, radius=1.0):
        super().__init__(loc, rot=rot, radius=radius)
        self._vel = TGPoint3(*vel)

    def GetVelocityTG(self):
        return TGPoint3(self._vel.x, self._vel.y, self._vel.z)


def _authored_drop_and_watch(target):
    """A mode carrying the SDK's authored attrs (CameraModes.py:147-159)."""
    m = DropAndWatchMode()
    for name, v in (("AwayDistance", 0.0), ("RotateSpeed", 0.0),
                    ("AnticipationTime", 2.5), ("ForwardOffset", 0.5),
                    ("SideOffset", 3.0), ("AwayDistanceFactor", 1.2),
                    ("AxisAvoidAngles", 45.0), ("SlowSpeedThreshold", 0.5),
                    ("SlowRotationThreshold", 0.1), ("RotateSpeedAccel", 0.025),
                    ("MaxRotateSpeed", 0.2)):
        m.SetAttrFloat(name, v)
    m.SetAttrIDObject("Target", target)
    return m


def test_drop_and_watch_drops_off_to_the_side_of_a_stationary_target():
    """Drop point = ForwardOffset/SideOffset in the target's body frame, scaled
    by its radius (ChaseMode's radius-relative convention). A stationary target
    contributes no anticipation term."""
    t = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)   # identity: fwd +Y, right +X
    m = _authored_drop_and_watch(t)
    eye, _fwd, up = m.Update()
    assert eye == (3.0, 0.5, 0.0)                  # right*3.0 + forward*0.5
    assert up == (0.0, 0.0, 1.0)                   # target col2


def test_drop_and_watch_offsets_scale_with_the_hull():
    t = _FakeTarget((0.0, 0.0, 0.0), radius=4.0)
    eye, _fwd, _up = _authored_drop_and_watch(t).Update()
    assert eye == (12.0, 2.0, 0.0)


def test_drop_and_watch_point_stays_put_while_the_target_moves():
    """THE defining behaviour: the drop point is state, not a per-frame
    function of the target's pose. Steps kept inside the re-drop radius."""
    t = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    m = _authored_drop_and_watch(t)
    first, _fwd, _up = m.Update()
    for i in range(1, 6):
        t._loc = TGPoint3(0.0, 0.5 * i, 0.0)
        eye, _fwd, _up = m.Update(1.0 / 60.0)
        assert eye == first, f"drop point moved on step {i}: {eye} != {first}"


def test_drop_and_watch_keeps_looking_at_the_moving_target():
    t = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    m = _authored_drop_and_watch(t)
    m.Update()
    t._loc = TGPoint3(0.0, 2.0, 0.0)
    _eye, fwd, _up = m.Update()                    # no dt => snap to ideal
    want = math.sqrt(3.0 ** 2 + 1.5 ** 2)
    assert abs(fwd[0] - (-3.0 / want)) < 1e-9      # from (3,0.5,0) to (0,2,0)
    assert abs(fwd[1] - (1.5 / want)) < 1e-9


def test_drop_and_watch_anticipates_the_targets_motion():
    """The drop point leads the target by velocity * AnticipationTime, so the
    ship flies INTO the shot: 10 GU/s * 2.5 s = 25 GU ahead, + ForwardOffset."""
    t = _MovingTarget((0.0, 0.0, 0.0), (0.0, 10.0, 0.0), radius=1.0)
    eye, _fwd, _up = _authored_drop_and_watch(t).Update()
    assert abs(eye[1] - 25.5) < 1e-9        # 25 lead + 0.5 forward offset


def test_drop_and_watch_avoids_a_dead_astern_view():
    """AxisAvoidAngles 45.0: a target flying straight along its own forward axis
    must not end up framed dead-astern / dead-ahead — the anticipation term is
    ALONG that axis, so this is the degenerate case of the placement."""
    t = _MovingTarget((0.0, 0.0, 0.0), (0.0, 10.0, 0.0), radius=1.0)
    eye, fwd, _up = _authored_drop_and_watch(t).Update()
    axis = (0.0, 1.0, 0.0)                  # identity rotation => forward is +Y
    along = abs(fwd[0] * axis[0] + fwd[1] * axis[1] + fwd[2] * axis[2])
    assert along <= math.cos(math.radians(45.0)) + 1e-9, (
        f"view direction {fwd} is only "
        f"{math.degrees(math.acos(min(1.0, along))):.1f}deg off the flight axis")


def test_drop_and_watch_avoidance_falls_back_to_the_right_axis():
    """With no SideOffset the drop lands exactly on the target's track, so the
    sideways nudge has no direction of its own and uses the body right axis."""
    t = _MovingTarget((0.0, 0.0, 0.0), (0.0, 10.0, 0.0), radius=1.0)
    m = _authored_drop_and_watch(t)
    m.SetAttrFloat("SideOffset", 0.0)
    eye, _fwd, _up = m.Update()
    assert abs(eye[0] - 25.5) < 1e-9        # pushed out along +X (right)
    assert abs(eye[1] - 25.5) < 1e-9        # along-track component preserved


def test_drop_and_watch_target_without_velocity_surface_drops_at_its_position(
        monkeypatch):
    """GetVelocityTG is PhysicsObjectClass surface — a waypoint / placement
    target has none, and must simply drop with no anticipation term instead of
    raising. Decided on the MRO: this target is TGObject-derived, so
    hasattr/getattr are vacuously true and calling the vended _Stub would both
    lie (its arithmetic collapses to 0) and burn a heatmap hit every frame."""
    from engine.core import ids as _ids
    from engine.core import stub_telemetry

    class _NoVelocityTarget(_ids.TGObject):
        def __init__(self):
            super().__init__()
            self._pos = TGPoint3(0.0, 0.0, 0.0)

        def GetWorldLocation(self):  return TGPoint3(self._pos.x, self._pos.y, self._pos.z)
        def GetWorldRotation(self):  return TGMatrix3()
        def GetRadius(self):         return 1.0

    t = _NoVelocityTarget()
    assert hasattr(t, "GetVelocityTG")             # !!! true, and it is a _Stub

    hits = []
    monkeypatch.setattr(stub_telemetry, "ENABLED", True)
    monkeypatch.setattr(stub_telemetry, "record_attr",
                        lambda owner, attr: hits.append((owner, attr)))
    eye, _fwd, _up = _authored_drop_and_watch(t).Update()
    assert eye == (3.0, 0.5, 0.0)                  # no anticipation term
    assert not [h for h in hits if h[1] == "GetVelocityTG"], hits


def test_drop_and_watch_redrops_once_the_target_gets_too_far():
    """d0 = drop→target distance at drop time (3.041 here); the camera re-drops
    once the target passes d0 * AwayDistanceFactor."""
    t = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    m = _authored_drop_and_watch(t)
    first, _fwd, _up = m.Update()
    assert first == (3.0, 0.5, 0.0)
    t._loc = TGPoint3(0.0, 50.0, 0.0)              # far past d0 * 1.2
    eye, _fwd, _up = m.Update()
    assert eye != first
    assert eye == (3.0, 50.5, 0.0)                 # dropped beside the new pose


def test_drop_and_watch_redrop_cuts_instead_of_gliding():
    """The base sweep already handles this: a new drop point is a big jump, so
    _pose_discontinuity cuts. Verified, not assumed — no cut logic of our own."""
    t = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    m = _authored_drop_and_watch(t)
    m.Update()
    t._loc = TGPoint3(0.0, 50.0, 0.0)
    eye, _fwd, _up = m.Update(1.0 / 60.0)          # WITH dt: would glide
    assert eye == (3.0, 50.5, 0.0)                 # cut straight to the new drop


def test_drop_and_watch_away_distance_floors_the_redrop_radius():
    """WarpSequence.py:252 re-authors AwayDistance 100000.0 for its arrival
    shot — read as a floor on d0, that pins the camera for the whole arrival."""
    t = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    m = _authored_drop_and_watch(t)
    m.SetAttrFloat("AwayDistance", 1000.0)
    first, _fwd, _up = m.Update()
    t._loc = TGPoint3(0.0, 500.0, 0.0)             # way past the un-floored d0
    eye, _fwd, _up = m.Update()
    assert eye == first


def test_drop_and_watch_redrops_when_the_target_changes():
    """A new Target is a new shot even if the old drop point is still in range
    (3.041 away here, under the 3.650 re-drop radius)."""
    t = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    m = _authored_drop_and_watch(t)
    first, _fwd, _up = m.Update()
    m.SetAttrIDObject("Target", _FakeTarget((0.0, 1.0, 0.0), radius=1.0))
    eye, _fwd, _up = m.Update()
    assert first == (3.0, 0.5, 0.0)
    assert eye == (3.0, 1.5, 0.0)


def test_reverse_chase_is_default_position_sign_not_a_flag():
    """ReverseChase is +Y DefaultPosition, no constructor argument."""
    t = _FakeTarget((0.0, 0.0, 0.0), radius=2.0)
    m = ChaseMode()
    m.SetAttrIDObject("Target", t)
    m.SetAttrPoint("DefaultPosition", TGPoint3(0.0, 1.0, 0.0))
    m.SetAttrFloat("Distance", 4.0)
    m.SnapToIdealPosition()
    eye, fwd, _up = m.Update()
    assert abs(eye[1] - 8.0) < 1e-6          # ahead of the target
    assert fwd[1] < -0.9                     # looking back at it
