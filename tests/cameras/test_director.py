"""Unit tests for _CameraDirector — mode dispatch shim that owns the
mode flag and forwards compute() to the appropriate camera class."""
import math
import pytest


def _make_ship_pose():
    from engine.appc.math import TGPoint3, TGMatrix3
    return TGPoint3(0.0, 0.0, 0.0), TGMatrix3()


class _FakePlayer:
    def __init__(self):
        self._loc, self._rot = _make_ship_pose()

    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetTarget(self):        return None  # no target → stays in Chase


def test_director_starts_in_chase_mode():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    assert d.mode is CameraMode.CHASE


def test_director_compute_matches_chase_camera_when_in_chase():
    from engine.cameras.director import _CameraDirector
    from engine.cameras.chase    import _ChaseCamera

    d  = _CameraDirector()
    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    d.chase.set_ship_radius(1.0)

    player = _FakePlayer()
    eye_d, look_d, up_d = d.compute(player=player, dt=1.0/60)
    eye_c, look_c, up_c = cc.compute_camera(
        player.GetWorldLocation(), player.GetWorldRotation(), dt=1.0/60,
    )

    for got, want in zip(eye_d, eye_c):  assert got == pytest.approx(want, abs=1e-6)
    for got, want in zip(look_d, look_c): assert got == pytest.approx(want, abs=1e-6)
    for got, want in zip(up_d, up_c):    assert got == pytest.approx(want, abs=1e-6)


# ── Task 10: mode transitions, toggle, target-loss fallback ─────────────────


class _FakeShipWithTarget:
    def __init__(self, target):
        from engine.appc.math import TGPoint3, TGMatrix3
        self._loc = TGPoint3(0.0, 0.0, 0.0)
        self._rot = TGMatrix3()
        self._target = target
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetTarget(self):        return self._target


def _make_target_at(x=0.0, y=20.0, z=0.0):
    from engine.appc.math import TGPoint3, TGMatrix3
    class _T:
        def __init__(self):
            self._loc = TGPoint3(x, y, z); self._rot = TGMatrix3()
        def GetWorldLocation(self): return self._loc
        def GetWorldRotation(self): return self._rot
    return _T()


def test_toggle_chase_to_tracking_flips_mode_and_snaps_tracking():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0)
    d.tracking.set_ship_radius(1.0)
    # Warm up tracking spring state so we can verify snap clears it.
    d.tracking._smoothed_eye = [1.0, 2.0, 3.0]
    d.toggle_mode(player=_FakeShipWithTarget(target=_make_target_at()))
    assert d.mode is CameraMode.TRACKING
    assert d.tracking._smoothed_eye is None


def test_toggle_tracking_to_chase_flips_mode_preserving_chase_state():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.toggle_mode(player=_FakeShipWithTarget(target=_make_target_at()))
    d.chase.orbit_yaw_rad = 1.2
    d.toggle_mode(player=_FakeShipWithTarget(target=_make_target_at()))
    assert d.mode is CameraMode.CHASE
    assert d.chase.orbit_yaw_rad == pytest.approx(1.2)


def test_toggle_in_chase_with_no_target_stays_in_chase():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.toggle_mode(player=_FakeShipWithTarget(target=None))
    assert d.mode is CameraMode.CHASE


def test_target_lost_mid_tracking_falls_back_to_chase_on_compute():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)

    p_with    = _FakeShipWithTarget(target=_make_target_at())
    p_without = _FakeShipWithTarget(target=None)

    d.toggle_mode(player=p_with)
    assert d.mode is CameraMode.TRACKING

    # Player loses target.
    eye, look_at, up = d.compute(player=p_without, dt=1.0/60)
    assert d.mode is CameraMode.CHASE   # durable switch (spec §5)


def test_snap_propagates_to_both_cameras():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.chase._smoothed_rot = "non-None placeholder"
    d.tracking._smoothed_eye = [1.0, 2.0, 3.0]
    d.tracking._smoothed_basis = "non-None placeholder"
    d.snap()
    assert d.chase._smoothed_rot     is None
    assert d.tracking._smoothed_eye  is None
    assert d.tracking._smoothed_basis is None


def test_tracking_dispatch_returns_solver_output_when_target_present():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    p = _FakeShipWithTarget(target=_make_target_at())
    d.toggle_mode(player=p)
    eye, look_at, up = d.compute(player=p, dt=1.0/60)
    # Just check finiteness — geometry covered in Task 6–8.
    for v in (*eye, *look_at, *up):
        assert math.isfinite(v)
