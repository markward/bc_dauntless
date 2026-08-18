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
    TARGET_DEFAULT_DISTANCE, TARGET_DEFAULT_MINIMUM_DISTANCE,
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
    """Over-the-shoulder: the eye stands OFF the Source (never inside it),
    behind it along the source→target axis and slightly above, still looking
    toward the Target.

    This used to assert eye == the source's own origin — i.e. the camera sat
    INSIDE the source hull, which is the live F3 defect, not the behaviour.
    """
    src = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    dst = _FakeTarget((0.0, 100.0, 0.0))
    m = TargetMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", dst)
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()
    assert eye != (0.0, 0.0, 0.0)                # NOT inside the source
    assert eye[1] < 0.0                          # behind the source (away from dst)
    assert eye[2] > 0.0                          # authored UpWatchPos lift
    assert abs(fwd[1] - 1.0) < 1e-2              # still +Y toward dst
    assert up == (0.0, 0.0, 1.0)                 # source col2 (identity rot)


def test_target_mode_standoff_is_distance_times_source_radius():
    """BC authors Distance 4.0 on Target — the SAME triple ChaseMode authors
    (Minimum 2.0 / Distance 4.0 / Maximum 40.0), which is why it is read the
    same way: a multiple of the radius of the object the eye is anchored to."""
    src = _FakeTarget((0.0, 0.0, 0.0), radius=2.0)
    dst = _FakeTarget((0.0, 100.0, 0.0))
    m = TargetMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", dst)
    m.SnapToIdealPosition()
    eye, _fwd, _up = m.Update()
    reach = math.sqrt(eye[0] ** 2 + eye[1] ** 2 + eye[2] ** 2)
    assert abs(reach - TARGET_DEFAULT_DISTANCE * 2.0) < 1e-6


def test_target_mode_standoff_clamped_to_maximum_distance():
    """CinematicReverseTarget (F3) authors MaximumDistance 16.0: a starbase-
    sized Source must not push the eye 80 GU out."""
    src = _FakeTarget((0.0, 0.0, 0.0), radius=20.0)
    dst = _FakeTarget((0.0, 500.0, 0.0))
    m = TargetMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", dst)
    m.SetAttrFloat("MaximumDistance", 16.0)
    m.SnapToIdealPosition()
    eye, _fwd, _up = m.Update()
    reach = math.sqrt(eye[0] ** 2 + eye[1] ** 2 + eye[2] ** 2)
    assert abs(reach - 16.0) < 1e-6


def test_target_mode_standoff_clamped_to_minimum_distance():
    src = _FakeTarget((0.0, 0.0, 0.0), radius=0.1)
    dst = _FakeTarget((0.0, 100.0, 0.0))
    m = TargetMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", dst)
    m.SnapToIdealPosition()
    eye, _fwd, _up = m.Update()
    reach = math.sqrt(eye[0] ** 2 + eye[1] ** 2 + eye[2] ** 2)
    assert abs(reach - TARGET_DEFAULT_MINIMUM_DISTANCE) < 1e-6


def test_target_mode_look_between_blends_from_the_target_toward_the_source():
    """LookBetween interpolates FROM THE TARGET back toward the Source: the
    authored 0.05 nudges the aim 5% off the target so the source stays in
    frame. Read the other way round (source → target) the camera would aim
    5% of the way to the target — i.e. essentially AT the ship it is parked
    behind, with the target off-screen entirely.

    Assert against a strongly off-axis eye (BackWatchPos 0 / UpWatchPos 1)
    where the two readings are separable, at LookBetween 0.5.
    """
    src = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    dst = _FakeTarget((0.0, 100.0, 0.0))
    m = TargetMode()
    m.SetAttrIDObject("Source", src)
    m.SetAttrIDObject("Target", dst)
    m.SetAttrFloat("BackWatchPos", 0.0)
    m.SetAttrFloat("UpWatchPos", 1.0)
    m.SetAttrFloat("LookBetween", 0.5)
    m.SnapToIdealPosition()
    eye, fwd, _up = m.Update()
    assert abs(eye[2] - TARGET_DEFAULT_DISTANCE) < 1e-6     # straight up, 4 GU
    look = (0.0, 50.0, 0.0)                                  # halfway back
    want = (look[0] - eye[0], look[1] - eye[1], look[2] - eye[2])
    n = math.sqrt(sum(c * c for c in want))
    for got, expect in zip(fwd, (c / n for c in want)):
        assert abs(got - expect) < 1e-9
    # ...and measurably NOT aiming at the raw target, nor at the source.
    assert abs(fwd[2] - (-4.0 / math.sqrt(100.0 ** 2 + 16.0))) > 1e-3
    assert fwd[1] > 0.9


def test_wide_target_stands_further_off_than_plain_target():
    """WideTarget and CinematicReverseTarget are the same class with different
    authored numbers (CameraModes.py:75-92, :334-355); the "wide" difference
    has to survive the shared implementation."""
    def _shot(distance, minimum, maximum, up_watch):
        src = _FakeTarget((0.0, 0.0, 0.0), radius=2.0)
        dst = _FakeTarget((0.0, 400.0, 0.0))
        m = TargetMode()
        m.SetAttrIDObject("Source", src)
        m.SetAttrIDObject("Target", dst)
        for k, v in (("SweepTime", 1.0), ("PositionThreshold", 0.01),
                     ("DotThreshold", 0.98), ("MinimumDistance", minimum),
                     ("Distance", distance), ("MaximumDistance", maximum),
                     ("BackWatchPos", 8.0), ("UpWatchPos", up_watch),
                     ("LookBetween", 0.05)):
            m.SetAttrFloat(k, v)
        m.SnapToIdealPosition()
        eye, _fwd, _up = m.Update()
        return math.sqrt(sum(c * c for c in eye))

    wide = _shot(32.0, 8.0, 64.0, 1.25)          # CameraModes.WideTarget
    close = _shot(4.0, 2.0, 16.0, 0.95)          # CameraModes.CinematicReverseTarget
    assert wide > close * 4.0


def test_target_mode_invalid_when_source_and_target_coincide():
    """No source→target axis ⇒ no shot. BC's authored Target → Chase edge
    handles the fallback; inventing an axis here would frame nothing."""
    same = _FakeTarget((7.0, 7.0, 7.0))
    m = TargetMode()
    m.SetAttrIDObject("Source", same)
    m.SetAttrIDObject("Target", same)
    assert not m.IsValid()


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
    function of the target's pose. Steps kept inside the re-drop radius.

    The target REPORTS the 30 GU/s it is being stepped at (0.5 GU per 60 Hz
    frame): a target that moves while reporting no velocity reads as stationary
    to the slow-orbit drift, which would then legitimately drift the drop
    point. This test is about a MOVING target, so it says so."""
    t = _MovingTarget((0.0, 0.0, 0.0), (0.0, 30.0, 0.0), radius=1.0)
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


# ── DropAndWatch: the slow-orbit drift ────────────────────────────────────────
# INFERRED behaviour (see the DropAndWatchMode docstring): when the target is
# nearly stationary the camera slowly orbits its drop point about the target's
# up axis so the shot does not freeze solid. The five authored numbers
# (RotateSpeed / RotateSpeedAccel / MaxRotateSpeed / SlowSpeedThreshold /
# SlowRotationThreshold) are SDK-sourced; everything these tests pin about how
# they are USED is our reading, not recovered BC.


class _SpinningTarget(_MovingTarget):
    """_MovingTarget plus the PhysicsObjectClass angular-velocity surface."""
    def __init__(self, loc, vel, angvel, rot=None, radius=1.0):
        super().__init__(loc, vel, rot=rot, radius=radius)
        self._angvel = TGPoint3(*angvel)

    def GetAngularVelocityTG(self):
        return TGPoint3(self._angvel.x, self._angvel.y, self._angvel.z)


def _unit3(x, y, z):
    n = math.sqrt(x * x + y * y + z * z)
    return (x / n, y / n, z / n)


def _sep(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _drop_angle(m, t):
    """Bearing of the mode's drop point about the target's up axis (+Z for an
    identity rotation), in radians — the quantity the drift advances."""
    d, loc = m._drop, t.GetWorldLocation()
    return math.atan2(d[1] - loc.y, d[0] - loc.x)


def _run(m, seconds, dt=1.0 / 60.0):
    out = None
    for _ in range(int(round(seconds / dt))):
        out = m.Update(dt)
    return out


def test_drop_and_watch_orbits_a_stationary_target():
    """THE bug this fixes: park the ship, press F9, and the frame was frozen
    solid — still camera, still subject. The camera must drift, and must keep
    looking at the target while it does."""
    t = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    m = _authored_drop_and_watch(t)
    first, _fwd, _up = m.Update()
    eye, fwd, _up = _run(m, 2.0)
    assert _sep(eye, first) > 1e-3, f"camera never moved: {eye} == {first}"
    to_target = _unit3(-eye[0], -eye[1], -eye[2])
    assert sum(fwd[i] * to_target[i] for i in range(3)) > 0.999, (
        f"drifting camera stopped looking at the target: {fwd} vs {to_target}")


def test_drop_and_watch_does_not_orbit_a_fast_target():
    """REGRESSION GUARD for the live-verified flyby: a moving ship already
    animates the shot, so the drift must stay out of it. 30 GU/s is 60x
    SlowSpeedThreshold."""
    t = _MovingTarget((0.0, 0.0, 0.0), (0.0, 30.0, 0.0), radius=1.0)
    m = _authored_drop_and_watch(t)
    m.Update()
    dropped = m._drop
    _run(m, 5.0)
    assert m._drop == dropped, f"drop point drifted on a fast target: {m._drop}"


def test_drop_and_watch_orbit_eases_in():
    """RotateSpeed 0.0 is the INITIAL rate and RotateSpeedAccel 0.025 rad/s^2
    ramps it: the drift must creep in, not snap to MaxRotateSpeed on frame one."""
    t = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    m = _authored_drop_and_watch(t)
    m.Update()

    def swept():
        a0 = _drop_angle(m, t)
        m.Update(1.0 / 60.0)
        return abs(_drop_angle(m, t) - a0)

    early = swept()
    _run(m, 4.0)
    later = swept()
    assert early < (0.2 / 60.0) * 0.1, f"drift jumped straight to speed: {early}"
    assert later > early * 10.0, f"drift never accelerated: {early} -> {later}"


def test_drop_and_watch_orbit_rate_is_capped_at_max_rotate_speed():
    """MaxRotateSpeed 0.2 rad/s ~ 11.5 deg/s: a full orbit in ~31 s. Reached
    from rest in ~8 s at RotateSpeedAccel, and never exceeded after that."""
    t = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    m = _authored_drop_and_watch(t)
    m.Update()
    _run(m, 30.0)
    assert abs(m._rotate_speed - 0.2) < 1e-12, m._rotate_speed
    a0 = _drop_angle(m, t)
    m.Update(1.0 / 60.0)
    assert abs(abs(_drop_angle(m, t) - a0) - 0.2 / 60.0) < 1e-9


def test_drop_and_watch_does_not_orbit_a_slow_but_spinning_target():
    """The slow test is an AND (INFERRED): a ship that is holding station but
    tumbling already animates the frame, so the camera must not add drift.
    0.5 rad/s is 5x SlowRotationThreshold with the linear speed at zero."""
    t = _SpinningTarget((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.5),
                        radius=1.0)
    m = _authored_drop_and_watch(t)
    m.Update()
    dropped = m._drop
    _run(m, 5.0)
    assert m._drop == dropped, f"drift ignored SlowRotationThreshold: {m._drop}"


def test_drop_and_watch_orbit_freezes_on_a_paused_sim():
    """dt=0.0 is a paused sim (test_dt_zero_does_not_snap_mid_sweep) and
    dt=None is the snap path — neither is elapsed time, so neither may advance
    the orbit or its rate."""
    t = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    m = _authored_drop_and_watch(t)
    m.Update()
    _run(m, 2.0)                       # spin the rate up so a freeze is visible
    frozen, rate = m._drop, m._rotate_speed
    assert rate > 0.0                  # the drift really is running
    for _ in range(60):
        m.Update(0.0)
    assert m._drop == frozen, f"paused sim advanced the orbit: {m._drop}"
    assert m._rotate_speed == rate, "paused sim accelerated the orbit rate"
    for _ in range(5):
        m.Update()                     # dt=None: snap, still no elapsed time
    assert m._drop == frozen, f"snap advanced the orbit: {m._drop}"
    assert m._rotate_speed == rate


def test_drop_and_watch_orbit_preserves_the_drop_distance():
    """The drift must compose with the re-drop rule rather than fight it:
    orbiting holds |drop - target| at d0, so d0 * AwayDistanceFactor is never
    tripped by the drift itself (a re-drop would reset the rate to RotateSpeed,
    so a rate still pinned at the cap proves one shot ran unbroken)."""
    t = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    m = _authored_drop_and_watch(t)
    m.Update()
    first, d0 = m._drop, m._drop_dist
    _run(m, 30.0)
    loc = t.GetWorldLocation()
    assert abs(_sep(m._drop, (loc.x, loc.y, loc.z)) - d0) < 1e-9
    assert _sep(m._drop, first) > 1e-3          # it really did orbit
    assert abs(m._rotate_speed - 0.2) < 1e-12   # ...without ever re-dropping


def test_drop_and_watch_orbits_a_target_with_no_physics_surface(monkeypatch):
    """GetVelocityTG / GetAngularVelocityTG are PhysicsObjectClass surface; a
    waypoint or placement target has neither and never moves, so it must read
    as stationary (drift ON) rather than raising. Decided on the MRO — this
    target is TGObject-derived, so hasattr is vacuously true and calling the
    vended _Stub would both lie and burn a heatmap hit every frame."""
    from engine.core import ids as _ids
    from engine.core import stub_telemetry

    class _NoPhysicsTarget(_ids.TGObject):
        def GetWorldLocation(self):  return TGPoint3(0.0, 0.0, 0.0)
        def GetWorldRotation(self):  return TGMatrix3()
        def GetRadius(self):         return 1.0

    t = _NoPhysicsTarget()
    assert hasattr(t, "GetAngularVelocityTG")      # !!! true, and it is a _Stub

    hits = []
    monkeypatch.setattr(stub_telemetry, "ENABLED", True)
    monkeypatch.setattr(stub_telemetry, "record_attr",
                        lambda owner, attr: hits.append((owner, attr)))
    m = _authored_drop_and_watch(t)
    first, _fwd, _up = m.Update()
    eye, _fwd, _up = _run(m, 2.0)
    assert _sep(eye, first) > 1e-3, f"static target never drifted: {eye}"
    assert not [h for h in hits if h[1] == "GetAngularVelocityTG"], hits


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


# ── TorpCam ───────────────────────────────────────────────────────────────────
# BC's F4 cinematic camera (CinematicInterfaceHandlers.CameraTorpCam:383 re-points
# AddModeHierarchy("InvalidCinematic", "TorpCam")). The mode's Target attr is the
# PLAYER SHIP (Camera.py:702), so the torpedo has to be found from the live
# projectile registry. The seven authored numbers are SDK-sourced
# (CameraModes.py:318-332); everything these tests pin about HOW they are used
# — absolute-GU distances, the look direction, the linear ramp, the latch — is
# inference, see the TorpCameraMode docstring.
import pytest

from engine.appc.camera_modes import (
    TorpCameraMode, TORP_DEFAULT_START_DISTANCE, TORP_DEFAULT_LATER_DISTANCE,
)
from engine.appc import projectiles as _projectiles


@pytest.fixture
def torp_registry():
    """The in-flight torpedo registry is a module global; keep it swept."""
    _projectiles._active.clear()
    yield _projectiles._active
    _projectiles._active.clear()


def _fire(source, pos=(0.0, 100.0, 0.0), vel=(0.0, 19.0, 0.0)):
    """Register an in-flight torpedo fired by `source`, as
    weapon_subsystems._spawn_projectile does (it sets _source_ship then
    register()s). 19.0 GU/s is PhotonTorpedo.GetLaunchSpeed()."""
    t = _projectiles.Torpedo()
    t._source_ship = source
    t._position = TGPoint3(*pos)
    t._velocity = TGPoint3(*vel)
    _projectiles.register(t)
    return t


def _authored_torp_cam(target):
    """A mode carrying the SDK's authored attrs (CameraModes.py:321-329)."""
    m = TorpCameraMode()
    for name, v in (("SweepTime", 2.0), ("PositionThreshold", 0.01),
                    ("DotThreshold", 0.98), ("DelayAfterTorpGone", 2.0),
                    ("StartDistance", 4.0), ("LaterDistance", 8.0),
                    ("MoveDistanceTime", 6.0)):
        m.SetAttrFloat(name, v)
    m.SetAttrIDObject("Target", target)
    return m


def test_camera_mode_create_dispatches_torpcam():
    """CameraModes.TorpCam (CameraModes.py:319) builds kind "TorpCam"; it used
    to fall through to the always-invalid PlaceByDirection attr bag."""
    assert isinstance(CameraMode_Create("TorpCam"), TorpCameraMode)


def test_torp_cam_invalid_without_target():
    assert not TorpCameraMode().IsValid()


def test_torp_cam_invalid_without_an_in_flight_torpedo(torp_registry):
    """A player with nothing in the air has no shot to ride — the mode reports
    invalid and BC's TorpCam->Chase edge takes over (Camera.py:642)."""
    m = _authored_torp_cam(_FakeTarget((0.0, 0.0, 0.0)))
    assert not m.IsValid()


def test_torp_cam_rides_behind_the_players_torpedo(torp_registry):
    """Eye sits StartDistance BEHIND the torpedo along its velocity, looking
    along the flight path — which puts the torpedo dead centre."""
    ship = _FakeTarget((0.0, 0.0, 0.0))
    _fire(ship, pos=(0.0, 100.0, 0.0), vel=(0.0, 19.0, 0.0))
    m = _authored_torp_cam(ship)
    eye, fwd, up = m.Update()                      # dt=None => snap to ideal
    assert eye == (0.0, 100.0 - TORP_DEFAULT_START_DISTANCE, 0.0)
    assert fwd == (0.0, 1.0, 0.0)
    assert up == (0.0, 0.0, 1.0)                   # firing ship's col2


def test_torp_cam_ignores_another_ships_torpedo(torp_registry):
    """_source_ship is the filter (projectiles._matches_source's idiom): an
    enemy salvo in the same registry must not hijack the player's TorpCam."""
    ship = _FakeTarget((0.0, 0.0, 0.0))
    _fire(_FakeTarget((500.0, 0.0, 0.0)), pos=(500.0, 0.0, 0.0))
    m = _authored_torp_cam(ship)
    assert not m.IsValid()


def test_torp_cam_picks_the_most_recently_fired_torpedo(torp_registry):
    ship = _FakeTarget((0.0, 0.0, 0.0))
    _fire(ship, pos=(0.0, 100.0, 0.0))
    _fire(ship, pos=(0.0, 20.0, 0.0))              # newest: higher _id
    eye, _fwd, _up = _authored_torp_cam(ship).Update()
    assert eye == (0.0, 20.0 - TORP_DEFAULT_START_DISTANCE, 0.0)


def test_torp_cam_latches_and_does_not_hop_to_a_newer_torpedo(torp_registry):
    """THE defining statefulness: once riding, keep riding THAT torpedo. Firing
    the rest of the salvo mid-ride must not make the camera hop."""
    ship = _FakeTarget((0.0, 0.0, 0.0))
    first = _fire(ship, pos=(0.0, 100.0, 0.0))
    m = _authored_torp_cam(ship)
    m.Update()
    assert m._torp is first
    _fire(ship, pos=(0.0, 20.0, 0.0))              # second tube, same salvo
    m.Update(1.0 / 60.0)
    assert m._torp is first
    eye, _fwd, _up = m._ideal()
    assert eye[1] < 100.0 and eye[1] > 20.0        # still on the first torpedo


def test_torp_cam_distance_ramps_from_start_toward_later(torp_registry):
    """StartDistance 4.0 -> LaterDistance 8.0 over MoveDistanceTime 6.0 s of
    ride time: the camera eases back as the torpedo runs (linear ramp is our
    inference)."""
    ship = _FakeTarget((0.0, 0.0, 0.0))
    _fire(ship, pos=(0.0, 100.0, 0.0))
    m = _authored_torp_cam(ship)
    eye, _fwd, _up = m._ideal()
    assert abs((100.0 - eye[1]) - 4.0) < 1e-9
    for _ in range(6):
        m.Update(0.5)                              # 3.0 s = half the ramp
    eye, _fwd, _up = m._ideal()
    assert abs((100.0 - eye[1]) - 6.0) < 1e-9


def test_torp_cam_distance_clamps_at_later_distance(torp_registry):
    ship = _FakeTarget((0.0, 0.0, 0.0))
    _fire(ship, pos=(0.0, 100.0, 0.0))
    m = _authored_torp_cam(ship)
    for _ in range(40):
        m.Update(0.5)                              # 20 s, way past MoveDistanceTime
    eye, _fwd, _up = m._ideal()
    assert abs((100.0 - eye[1]) - TORP_DEFAULT_LATER_DISTANCE) < 1e-9


def test_torp_cam_holds_the_final_pose_after_the_torpedo_is_gone(torp_registry):
    """DelayAfterTorpGone 2.0 exists so you SEE the hit: the pose the shot ended
    on is held after update_all drops the torpedo out of _active."""
    ship = _FakeTarget((0.0, 0.0, 0.0))
    torp = _fire(ship, pos=(0.0, 100.0, 0.0))
    m = _authored_torp_cam(ship)
    final, _fwd, _up = m.Update()
    _projectiles.expire(torp)                      # impact
    assert m.IsValid()
    eye, _fwd, _up = m._ideal()
    assert eye == final


def test_torp_cam_goes_invalid_after_the_delay(torp_registry):
    ship = _FakeTarget((0.0, 0.0, 0.0))
    torp = _fire(ship, pos=(0.0, 100.0, 0.0))
    m = _authored_torp_cam(ship)
    m.Update()
    _projectiles.expire(torp)
    for _ in range(3):
        m.Update(0.5)                              # 1.5 s < DelayAfterTorpGone
    assert m.IsValid()
    m.Update(0.5)                                  # 2.0 s
    assert not m.IsValid()


def test_torp_cam_reacquires_after_the_hold_expires(torp_registry):
    """The latch is released once the hold is over, so the NEXT shot gets its
    own ride (F4 stays selected across a whole engagement)."""
    ship = _FakeTarget((0.0, 0.0, 0.0))
    torp = _fire(ship, pos=(0.0, 100.0, 0.0))
    m = _authored_torp_cam(ship)
    m.Update()
    _projectiles.expire(torp)
    for _ in range(4):
        m.Update(0.5)
    assert not m.IsValid()
    nxt = _fire(ship, pos=(0.0, 30.0, 0.0))
    assert m.IsValid()
    assert m._torp is nxt
    eye, _fwd, _up = m._ideal()
    assert abs((30.0 - eye[1]) - TORP_DEFAULT_START_DISTANCE) < 1e-9


def test_torp_cam_paused_sim_does_not_advance_the_ramp(torp_registry):
    """dt=0.0 is a paused sim and dt=None is the snap path — neither is elapsed
    time, so neither may advance the ride timer (same rule as DropAndWatch's
    orbit, test_drop_and_watch_orbit_freezes_on_a_paused_sim)."""
    ship = _FakeTarget((0.0, 0.0, 0.0))
    _fire(ship, pos=(0.0, 100.0, 0.0))
    m = _authored_torp_cam(ship)
    for _ in range(4):
        m.Update(0.5)
    ridden = m._ride_t
    assert ridden > 0.0
    for _ in range(60):
        m.Update(0.0)
    assert m._ride_t == ridden, f"paused sim advanced the ramp: {m._ride_t}"
    for _ in range(5):
        m.Update()
    assert m._ride_t == ridden, f"snap advanced the ramp: {m._ride_t}"


def test_torp_cam_paused_sim_does_not_advance_the_gone_timer(torp_registry):
    """A paused sim must not burn the hold — freeze on the hit, do not cut."""
    ship = _FakeTarget((0.0, 0.0, 0.0))
    torp = _fire(ship, pos=(0.0, 100.0, 0.0))
    m = _authored_torp_cam(ship)
    m.Update()
    _projectiles.expire(torp)
    m.Update(0.5)
    gone = m._gone_t
    assert gone > 0.0
    for _ in range(60):
        m.Update(0.0)
    assert m._gone_t == gone, f"paused sim advanced the hold: {m._gone_t}"
    for _ in range(5):
        m.Update()
    assert m._gone_t == gone, f"snap advanced the hold: {m._gone_t}"
    assert m.IsValid()


def test_torp_cam_distance_is_absolute_game_units_not_radius_relative(
        torp_registry):
    """The judgement call, pinned: StartDistance/LaterDistance are ABSOLUTE GU.
    The Target attr is the FIRING SHIP, not the framed object, so ChaseMode's
    radius-relative reading would put the camera 4 x a Galaxy's radius behind a
    ~1 GU torpedo. A bigger firing hull must not change the ride distance."""
    small = _FakeTarget((0.0, 0.0, 0.0), radius=1.0)
    big = _FakeTarget((0.0, 0.0, 0.0), radius=40.0)
    _fire(small, pos=(0.0, 100.0, 0.0))
    a, _fwd, _up = _authored_torp_cam(small)._ideal()
    _projectiles._active.clear()
    _fire(big, pos=(0.0, 100.0, 0.0))
    b, _fwd, _up = _authored_torp_cam(big)._ideal()
    assert a == b


def test_torp_cam_follows_the_torpedos_heading(torp_registry):
    """The ride axis is the torpedo's VELOCITY, so a homing torpedo that turns
    swings the camera round behind it."""
    ship = _FakeTarget((0.0, 0.0, 0.0))
    torp = _fire(ship, pos=(0.0, 100.0, 0.0), vel=(19.0, 0.0, 0.0))
    m = _authored_torp_cam(ship)
    _eye, fwd, _up = m._ideal()
    assert fwd == (1.0, 0.0, 0.0)
    torp._velocity = TGPoint3(0.0, 0.0, 19.0)
    eye, fwd, _up = m._ideal()
    assert fwd == (0.0, 0.0, 1.0)
    assert eye == (0.0, 100.0, -TORP_DEFAULT_START_DISTANCE)


def test_torp_cam_does_not_probe_stub_surface_on_the_torpedo(
        torp_registry, monkeypatch):
    """A Torpedo is TGObject-derived, so hasattr is vacuously true for every
    engine name — the mode must decide optional surface on the MRO
    (engine.core.ids.implements) instead of burning heatmap hits every frame."""
    from engine.core import stub_telemetry
    ship = _FakeTarget((0.0, 0.0, 0.0))
    _fire(ship, pos=(0.0, 100.0, 0.0))
    hits = []
    monkeypatch.setattr(stub_telemetry, "ENABLED", True)
    monkeypatch.setattr(stub_telemetry, "record_attr",
                        lambda owner, attr: hits.append((owner, attr)))
    m = _authored_torp_cam(ship)
    m.Update()
    m.Update(1.0 / 60.0)
    assert not hits, hits
