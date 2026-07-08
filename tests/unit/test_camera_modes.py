import math
from engine.appc.camera_modes import CameraMode, LockedMode, SWEEP_TAU_S
from engine.appc.math import TGPoint3, TGMatrix3


class _FakeTarget:
    """Minimal stand-in for an ObjectClass target."""
    def __init__(self, loc, rot=None):
        self._loc = TGPoint3(*loc)
        self._rot = rot if rot is not None else TGMatrix3()  # identity

    def GetWorldLocation(self):
        return TGPoint3(self._loc.x, self._loc.y, self._loc.z)

    def GetWorldRotation(self):
        return self._rot


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
    t = _FakeTarget((100.0, 0.0, 0.0))
    m = LockedMode()
    m.SetAttrIDObject("Target", t)
    m.SetAttrPoint("Position", TGPoint3(0.0, 0.0, 0.0))
    m.SetAttrPoint("Forward", TGPoint3(0.0, 1.0, 0.0))
    m.SetAttrPoint("Up", TGPoint3(0.0, 0.0, 1.0))
    m.set_initial_pose((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    # One small step does NOT reach the ideal...
    eye1, _, _ = m.Update(0.016)
    assert 0.0 < eye1[0] < 100.0
    # ...but many steps do.
    for _ in range(600):
        eye, _, _ = m.Update(0.016)
    assert abs(eye[0] - 100.0) < 1.0


def test_dt_zero_does_not_snap_mid_sweep():
    """Regression test for Fix 1: dt=0.0 must NOT snap; only dt=None snaps.

    A cutscene camera mid-sweep should freeze (not jump to ideal) when dt=0
    (e.g., sim paused). The buggy condition `not dt` treats 0.0 as falsy and
    incorrectly snaps to the ideal; it should test `dt is None` explicitly.
    """
    t = _FakeTarget((100.0, 0.0, 0.0))
    m = LockedMode()
    m.SetAttrIDObject("Target", t)
    m.SetAttrPoint("Position", TGPoint3(0.0, 0.0, 0.0))
    m.SetAttrPoint("Forward", TGPoint3(0.0, 1.0, 0.0))
    m.SetAttrPoint("Up", TGPoint3(0.0, 0.0, 1.0))

    # Seed into mid-sweep: eye starts at origin, target ideal at (100, 0, 0)
    m.set_initial_pose((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))

    # One small dt step glides partway: eye1[0] should be ~25
    eye1, _, _ = m.Update(0.016)
    assert 0.0 < eye1[0] < 100.0

    # Now call Update(0.0) (sim paused). Should NOT snap to ideal.
    # The returned eye should be IDENTICAL to eye1 (frozen at mid-sweep point).
    eye2, _, _ = m.Update(0.0)
    assert eye2 == eye1, f"dt=0.0 must freeze the sweep; got {eye2} != {eye1}"


from engine.appc.camera_modes import ChaseMode, TargetMode, CHASE_DIST_GU, CHASE_UP_GU


def test_chase_mode_sits_behind_target():
    t = _FakeTarget((0.0, 0.0, 0.0))           # identity rot: fwd = +Y (GetCol(1))
    m = ChaseMode()
    m.SetAttrIDObject("Target", t)
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()
    # Behind = -Y of forward, so eye.y is negative ~ -CHASE_DIST_GU; looks +Y.
    assert eye[1] < 0.0
    assert abs(eye[1] + CHASE_DIST_GU) < 1e-6
    assert fwd[1] > 0.9                         # looking toward the ship (+Y)
    # Check that the up-offset is applied: under identity rotation, eye.z should equal CHASE_UP_GU.
    assert abs(eye[2] - CHASE_UP_GU) < 1e-6


def test_reverse_chase_sits_in_front():
    t = _FakeTarget((0.0, 0.0, 0.0))
    m = ChaseMode(reverse=True)
    m.SetAttrIDObject("Target", t)
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()
    assert abs(eye[1] - CHASE_DIST_GU) < 1e-6  # in front (+Y), exact value
    assert fwd[1] < -0.9                          # looking back toward ship


def test_chase_mode_applies_target_rotation():
    # Target yawed 180° about Z: body -Y "behind" maps to world +Y (in front).
    r = TGMatrix3().MakeZRotation(math.pi)
    t = _FakeTarget((0.0, 0.0, 0.0), rot=r)
    m = ChaseMode()
    m.SetAttrIDObject("Target", t)
    m.SnapToIdealPosition()
    eye, fwd, up = m.Update()
    # Under 180° yaw, -Y offset becomes +Y in world: eye should be at +CHASE_DIST_GU
    assert abs(eye[1] - CHASE_DIST_GU) < 1e-6  # in front (not behind)
    # Z offset unaffected by Z-rotation
    assert abs(eye[2] - CHASE_UP_GU) < 1e-6


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
    # A Waypoint has no real IsDying; TGObject.__getattr__ hands back a truthy
    # _Stub, which must read as "not dying" (placements never die).
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
