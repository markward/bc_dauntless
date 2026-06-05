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


# ── Auto-engage Tracking on target select ───────────────────────────────────


def test_auto_engage_tracking_when_target_appears_in_chase():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    # Frame 1: no target → stays Chase.
    d.compute(player=_FakeShipWithTarget(target=None), dt=1.0/60)
    assert d.mode is CameraMode.CHASE
    # Frame 2: target appears → auto-engage Tracking.
    p_with = _FakeShipWithTarget(target=_make_target_at())
    d.compute(player=p_with, dt=1.0/60)
    assert d.mode is CameraMode.TRACKING


def test_auto_engage_on_target_change_after_durable_fallback():
    """After target loss drops us to Chase, acquiring a new target
    auto-engages Tracking again."""
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)

    p_a = _FakeShipWithTarget(target=_make_target_at())
    p_no = _FakeShipWithTarget(target=None)

    d.compute(player=p_a, dt=1.0/60)
    assert d.mode is CameraMode.TRACKING

    # Target lost.
    d.compute(player=p_no, dt=1.0/60)
    assert d.mode is CameraMode.CHASE

    # New target acquired.
    p_b = _FakeShipWithTarget(target=_make_target_at(x=5.0))
    d.compute(player=p_b, dt=1.0/60)
    assert d.mode is CameraMode.TRACKING


def test_manual_c_out_of_tracking_persists_against_same_target():
    """If the user presses C to leave Tracking while target is still
    selected, auto-engage must NOT re-fire on the next frame."""
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    tgt = _make_target_at()
    p = _FakeShipWithTarget(target=tgt)

    # Auto-engages.
    d.compute(player=p, dt=1.0/60)
    assert d.mode is CameraMode.TRACKING

    # User presses C → back to Chase.
    d.toggle_mode(player=p)
    assert d.mode is CameraMode.CHASE

    # Next frame: same target, stays in Chase (opted out).
    d.compute(player=p, dt=1.0/60)
    assert d.mode is CameraMode.CHASE
    d.compute(player=p, dt=1.0/60)
    assert d.mode is CameraMode.CHASE


def test_manual_c_out_is_defeated_when_target_changes():
    """Opt-out is scoped to one target. Switching targets re-engages."""
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)

    tgt_a = _make_target_at()
    p_a = _FakeShipWithTarget(target=tgt_a)

    d.compute(player=p_a, dt=1.0/60)
    assert d.mode is CameraMode.TRACKING
    d.toggle_mode(player=p_a)   # opt out
    assert d.mode is CameraMode.CHASE

    # Switch target.
    p_b = _FakeShipWithTarget(target=_make_target_at(x=5.0))
    d.compute(player=p_b, dt=1.0/60)
    assert d.mode is CameraMode.TRACKING


def test_manual_c_out_is_defeated_after_target_loss():
    """Opt-out is also cleared when target is lost and re-acquired."""
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)

    tgt = _make_target_at()
    p_with    = _FakeShipWithTarget(target=tgt)
    p_without = _FakeShipWithTarget(target=None)

    d.compute(player=p_with, dt=1.0/60)
    d.toggle_mode(player=p_with)
    assert d.mode is CameraMode.CHASE

    # Lose target.
    d.compute(player=p_without, dt=1.0/60)
    assert d.mode is CameraMode.CHASE

    # Re-acquire the same target — opt-out should be cleared by the
    # target-loss path, so auto-engage fires again.
    d.compute(player=p_with, dt=1.0/60)
    assert d.mode is CameraMode.TRACKING


def test_snap_clears_opt_out():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    tgt = _make_target_at()
    p = _FakeShipWithTarget(target=tgt)

    d.compute(player=p, dt=1.0/60)
    d.toggle_mode(player=p)
    assert d._opted_out_target is tgt   # implementation detail check

    d.snap()
    assert d._opted_out_target is None

    # Next compute auto-engages because opt-out is cleared.
    d.compute(player=p, dt=1.0/60)
    assert d.mode is CameraMode.TRACKING


# ── Task 4: zoom controls ────────────────────────────────────────────────────


def test_start_zoom_target_in_chase_is_noop():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.tracking.set_ship_radius(1.0)
    # mode is CHASE by default
    d.start_zoom_target(player=_FakeShipWithTarget(target=_make_target_at()))
    assert d.tracking.zoom_target_active is False


def test_start_zoom_target_in_tracking_with_target_activates():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    # Enter Tracking first (via toggle).
    p = _FakeShipWithTarget(target=_make_target_at())
    d.toggle_mode(player=p)
    assert d.mode is CameraMode.TRACKING
    d.start_zoom_target(player=p)
    assert d.tracking.zoom_target_active is True


def test_start_zoom_target_in_tracking_with_no_target_is_noop():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    # Force Tracking even though there's no target (test scaffold).
    d.mode = CameraMode.TRACKING
    p = _FakeShipWithTarget(target=None)
    d.start_zoom_target(player=p)
    assert d.tracking.zoom_target_active is False


def test_end_zoom_target_clears_unconditionally():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.tracking.set_ship_radius(1.0)
    d.tracking.zoom_target_active = True
    d.end_zoom_target()
    assert d.tracking.zoom_target_active is False
    # Called again — still False (idempotent).
    d.end_zoom_target()
    assert d.tracking.zoom_target_active is False


def test_director_zoom_in_in_tracking_delegates():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.mode = CameraMode.TRACKING
    seed = d.tracking.d_chase_tracking
    d.zoom_in()
    assert d.tracking.d_chase_tracking == pytest.approx(
        seed * d.tracking.ZOOM_FACTOR_PER_PRESS)


def test_director_zoom_out_in_tracking_delegates():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.mode = CameraMode.TRACKING
    seed = d.tracking.d_chase_tracking
    d.zoom_out()
    assert d.tracking.d_chase_tracking == pytest.approx(
        seed / d.tracking.ZOOM_FACTOR_PER_PRESS)


# ── Task 5: ZoomTarget cleanup on Tracking → Chase transitions ───────────────


def test_target_lost_in_tracking_with_zoom_target_active_clears_both():
    """Durable target-loss fallback must clear ZoomTarget sub-mode
    in addition to flipping mode to CHASE."""
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)

    p_with = _FakeShipWithTarget(target=_make_target_at())
    p_without = _FakeShipWithTarget(target=None)

    d.toggle_mode(player=p_with)
    assert d.mode is CameraMode.TRACKING
    d.start_zoom_target(player=p_with)
    assert d.tracking.zoom_target_active is True

    # Target lost.
    d.compute(player=p_without, dt=1.0/60)
    assert d.mode is CameraMode.CHASE
    assert d.tracking.zoom_target_active is False


def test_c_toggle_tracking_to_chase_clears_zoom_target():
    """C-key explicit Tracking → Chase must also clear ZoomTarget."""
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)

    p = _FakeShipWithTarget(target=_make_target_at())
    d.toggle_mode(player=p)
    d.start_zoom_target(player=p)
    assert d.tracking.zoom_target_active is True

    # C pressed.
    d.toggle_mode(player=p)
    assert d.mode is CameraMode.CHASE
    assert d.tracking.zoom_target_active is False


def test_director_zoom_in_in_chase_delegates_to_chase():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    seed_chase = d.chase.distance
    seed_tracking = d.tracking.d_chase_tracking
    d.zoom_in()
    assert d.chase.distance == pytest.approx(
        seed_chase * d.chase.ZOOM_FACTOR_PER_NOTCH)
    assert d.tracking.d_chase_tracking == pytest.approx(seed_tracking)


def test_director_zoom_out_in_chase_delegates_to_chase():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    seed_chase = d.chase.distance
    seed_tracking = d.tracking.d_chase_tracking
    d.zoom_out()
    assert d.chase.distance == pytest.approx(
        seed_chase / d.chase.ZOOM_FACTOR_PER_NOTCH)
    assert d.tracking.d_chase_tracking == pytest.approx(seed_tracking)


# ── Task 6: start/end_reverse + Tracking-entry cleanup ──────────────────────


def test_director_start_reverse_in_chase_sets_flag():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.start_reverse()
    assert d.chase.reverse_active is True


def test_director_start_reverse_in_tracking_is_noop():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.mode = CameraMode.TRACKING
    d.start_reverse()
    assert d.chase.reverse_active is False


def test_director_end_reverse_clears_unconditionally():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.chase.reverse_active = True
    d.end_reverse()
    assert d.chase.reverse_active is False
    # Idempotent.
    d.end_reverse()
    assert d.chase.reverse_active is False


def test_c_toggle_chase_to_tracking_clears_reverse():
    """C-key explicit CHASE → TRACKING must clear reverse_active."""
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    p = _FakeShipWithTarget(target=_make_target_at())
    d.chase.reverse_active = True
    d.toggle_mode(player=p)
    assert d.mode is CameraMode.TRACKING
    assert d.chase.reverse_active is False


def test_target_auto_engage_clears_reverse():
    """Auto-engage Tracking on target acquisition must clear
    reverse_active so a future return to Chase doesn't surprise the
    user with leftover flip."""
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.chase.reverse_active = True

    p_with_target = _FakeShipWithTarget(target=_make_target_at())
    d.compute(player=p_with_target, dt=1.0/60)  # auto-engage
    assert d.mode is CameraMode.TRACKING
    assert d.chase.reverse_active is False


def test_director_snap_resets_chase_reverse():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.chase.reverse_active = True
    d.snap()
    assert d.chase.reverse_active is False


# ── FOV mutator ────────────────────────────────────────────────────────


def test_director_fov_seeded_from_constant():
    from engine.cameras.director import _CameraDirector
    from engine.cameras           import EXTERIOR_FOV_Y_RAD
    d = _CameraDirector()
    assert d.fov_y_rad == pytest.approx(EXTERIOR_FOV_Y_RAD)
    assert d.tracking.v_fov_rad == pytest.approx(EXTERIOR_FOV_Y_RAD)


def test_director_set_fov_updates_self_and_tracking():
    import math
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    new_fov = math.radians(75.0)
    d.set_fov(new_fov)
    assert d.fov_y_rad == pytest.approx(new_fov)
    assert d.tracking.v_fov_rad == pytest.approx(new_fov)


def test_director_set_fov_changes_tracking_projection():
    """After set_fov, the tracking solver's screen-Y → angle conversion
    must use the new FOV."""
    import math
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.set_fov(math.radians(90.0))
    # _screen_y_to_angle(y) = atan(y × tan(v_fov/2))
    expected = math.atan(0.5 * math.tan(math.radians(45.0)))
    assert d.tracking._screen_y_to_angle(0.5) == pytest.approx(expected, abs=1e-12)
