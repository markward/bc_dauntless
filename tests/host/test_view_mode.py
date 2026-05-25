"""Unit tests for _ViewModeController — space-bar toggled bridge/exterior
view modality. Mirrors the fake-bindings pattern from
tests/host/test_camera_control.py."""
import pytest


class _FakeKeys:
    KEY_SPACE = 200


class _FakeKeyReader:
    keys = _FakeKeys()

    def __init__(self):
        self.held = set()
        self.pressed_once = set()

    def key_state(self, key):
        return key in self.held

    def key_pressed(self, key):
        if key in self.pressed_once:
            self.pressed_once.discard(key)
            return True
        return False


def _exterior_vm():
    from engine.host_loop import _ViewModeController
    vm = _ViewModeController()
    vm.toggle()  # bridge → exterior
    return vm


def test_view_mode_starts_in_bridge():
    from engine.host_loop import _ViewModeController
    vm = _ViewModeController()
    assert vm.is_bridge is True
    assert vm.is_exterior is False


def test_view_mode_toggle_on_space_pressed():
    from engine.host_loop import _ViewModeController
    vm = _ViewModeController()
    reader = _FakeKeyReader()

    # No space → no change.
    vm.apply(reader)
    assert vm.is_bridge is True

    # Space pressed once → exterior.
    reader.pressed_once.add(reader.keys.KEY_SPACE)
    vm.apply(reader)
    assert vm.is_exterior is True

    # No space → still exterior (edge-triggered, not held).
    vm.apply(reader)
    assert vm.is_exterior is True

    # Space pressed again → back to bridge.
    reader.pressed_once.add(reader.keys.KEY_SPACE)
    vm.apply(reader)
    assert vm.is_bridge is True


class _RecordingInputs:
    """Stand-ins for _PlayerControl / _CameraControl that record whether
    apply() was called and what reader it was handed, without doing any
    work."""
    class _Player:
        def __init__(self): self.calls = []
        def apply(self, player, dt, h): self.calls.append(h)
    class _Camera:
        def __init__(self): self.calls = 0
        def apply(self, dt, h, scroll_y): self.calls += 1

    def __init__(self):
        self.player = self._Player()
        self.camera = self._Camera()


def test_apply_input_calls_both_in_exterior_mode():
    from engine.host_loop import _ViewModeController, _apply_input
    vm = _ViewModeController()
    vm.toggle()  # bridge → exterior
    inputs = _RecordingInputs()
    reader = _FakeKeyReader()
    _apply_input(vm, inputs.player, inputs.camera,
                 player=object(), dt=1.0/60, h=reader, scroll_y=0.0)
    assert len(inputs.player.calls) == 1
    assert inputs.player.calls[0] is reader  # exterior forwards live keys
    assert inputs.camera.calls == 1


def test_apply_input_in_bridge_keeps_player_integrating_with_no_input():
    """Bridge mode calls player_control.apply with a no-input reader so
    ship physics keep integrating (engines coast) while live keys are
    ignored. The orbit camera is not stepped at all."""
    from engine.host_loop import _ViewModeController, _apply_input, _NO_INPUT
    vm = _ViewModeController()
    inputs = _RecordingInputs()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_SPACE)  # held key must not reach player
    _apply_input(vm, inputs.player, inputs.camera,
                 player=object(), dt=1.0/60, h=reader, scroll_y=0.0)
    assert len(inputs.player.calls) == 1
    assert inputs.player.calls[0] is _NO_INPUT
    assert inputs.camera.calls == 0


def test_apply_input_preserves_orbit_state_across_bridge_toggle():
    """Spec test 5: entering bridge mode must not mutate _CameraControl
    orbit state, so toggling back restores the same exterior framing."""
    from engine.host_loop import _ViewModeController, _CameraControl, _apply_input
    cc = _CameraControl()
    cc.orbit_yaw_rad = 1.234
    cc.orbit_pitch_rad = -0.5
    cc.distance = 4242.0
    saved = (cc.orbit_yaw_rad, cc.orbit_pitch_rad, cc.distance)

    vm = _ViewModeController()
    reader = _FakeKeyReader()

    # Drive a "tick" with a non-zero scroll delta. In exterior mode that
    # would shrink cc.distance via cc.apply(); in bridge mode _apply_input
    # must not call cc.apply() at all, so the orbit state stays frozen.
    class _NoopPlayer:
        def apply(self, *a, **k): pass
    _apply_input(vm, _NoopPlayer(), cc, player=object(),
                 dt=1.0/60, h=reader, scroll_y=99.0)
    assert (cc.orbit_yaw_rad, cc.orbit_pitch_rad, cc.distance) == saved


def test_apply_input_in_bridge_keeps_ship_moving_under_real_player_control():
    """Regression: pressing space while engines are engaged must NOT
    freeze the ship — it should keep coasting forward at its current
    speed. Drives the real _PlayerControl against a fake ship to prove
    that the integration step still runs in bridge mode."""
    from engine.host_loop import _ViewModeController, _PlayerControl, _apply_input
    from engine.appc.math import TGPoint3, TGMatrix3

    class _FakeShip:
        def __init__(self):
            self._loc = TGPoint3(0.0, 0.0, 0.0)
            self._rot = TGMatrix3()
        def GetWorldRotation(self): return self._rot
        def GetTranslate(self):     return self._loc
        def SetMatrixRotation(self, R): self._rot = R
        def SetTranslateXYZ(self, x, y, z):
            self._loc = TGPoint3(x, y, z)
        # No ImpulseEngineSubsystem → _PlayerControl falls back to legacy
        # IMPULSE_UNIT * level for target speed.
        GetImpulseEngineSubsystem = None

    pc = _PlayerControl()
    pc.impulse_level = 5
    pc._current_speed = 5 * _PlayerControl.IMPULSE_UNIT  # already at target
    ship = _FakeShip()

    vm = _ViewModeController()

    class _NoopCam:
        def apply(self, *a, **k): pass

    reader = _FakeKeyReader()
    # Tick a few times in bridge mode. The ship must move forward.
    for _ in range(10):
        _apply_input(vm, pc, _NoopCam(),
                     player=ship, dt=1.0/60, h=reader, scroll_y=0.0)

    # Ship-Y is forward in body frame. Identity rotation → world +Y.
    # 10 ticks × (1/60 s) × 250 units/s ≈ 41.67 units along Y.
    assert ship._loc.y > 40.0
    # Throttle setting is preserved across bridge toggle.
    assert pc.impulse_level == 5


class _RecordingRenderer:
    """Stand-in for the _dauntless_host bindings module. Records calls
    to bridge-pass-related functions so toggle wiring can be asserted
    without booting the real renderer."""
    def __init__(self):
        self.bridge_pass_calls = []   # list of bool
        self.cursor_lock_calls = []   # list of bool

    def bridge_pass_set_enabled(self, enabled):
        self.bridge_pass_calls.append(enabled)

    def set_cursor_locked(self, locked):
        self.cursor_lock_calls.append(locked)


def test_toggle_to_bridge_enables_pass_and_locks_cursor():
    """Toggling exterior → bridge fires bridge_pass_set_enabled(True)
    and set_cursor_locked(True) exactly once each."""
    from engine.host_loop import _apply_view_mode_side_effects
    vm = _exterior_vm()
    rr = _RecordingRenderer()
    vm.toggle()  # exterior → bridge
    _apply_view_mode_side_effects(vm, rr)
    assert rr.bridge_pass_calls == [True]
    assert rr.cursor_lock_calls == [True]


def test_toggle_to_exterior_disables_pass_and_releases_cursor():
    from engine.host_loop import _apply_view_mode_side_effects
    vm = _exterior_vm()
    vm.toggle()  # bridge
    rr = _RecordingRenderer()
    _apply_view_mode_side_effects(vm, rr)  # one true call
    vm.toggle()  # back to exterior
    _apply_view_mode_side_effects(vm, rr)
    assert rr.bridge_pass_calls == [True, False]
    assert rr.cursor_lock_calls == [True, False]


def test_apply_view_mode_side_effects_idempotent_within_a_mode():
    """Calling _apply_view_mode_side_effects twice without toggling
    must not re-fire the renderer calls — bridge_pass_set_enabled is a
    cheap setter but cursor lock has visible side-effects we don't want
    to spam."""
    from engine.host_loop import _ViewModeController, _apply_view_mode_side_effects
    vm = _ViewModeController()
    rr = _RecordingRenderer()
    _apply_view_mode_side_effects(vm, rr)
    _apply_view_mode_side_effects(vm, rr)  # no toggle in between
    # Both lists should have at most 1 entry (the initial-sync call).
    assert len(rr.bridge_pass_calls) <= 1
    assert len(rr.cursor_lock_calls) <= 1


def test_bridge_camera_anchors_at_ship_origin_looking_forward():
    """Spec test 4: bridge camera eye = ship loc, target along ship
    forward (row 1), up along ship up (row 2)."""
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.appc.math import TGPoint3, TGMatrix3

    class _FakePlayer:
        def __init__(self, loc, rot):
            self._loc, self._rot = loc, rot
        def GetWorldLocation(self): return self._loc
        def GetWorldRotation(self): return self._rot

    loc = TGPoint3(100.0, 200.0, 300.0)
    rot = TGMatrix3()  # identity — forward = (0,1,0), up = (0,0,1)
    player = _FakePlayer(loc, rot)

    vm = _ViewModeController()

    eye, target, up_vec = _compute_camera(
        vm, cam_control=None, player=player, dt=1.0/60)

    assert eye    == (100.0, 200.0, 300.0)
    assert target == (100.0, 201.0, 300.0)  # +1 along world-Y (= ship forward)
    assert up_vec == (0.0,   0.0,   1.0)


def test_exterior_camera_delegates_to_cam_control():
    """Sanity check: exterior mode still routes through _CameraControl."""
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.appc.math import TGPoint3, TGMatrix3

    class _FakePlayer:
        def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
        def GetWorldRotation(self): return TGMatrix3()

    class _RecordingCam:
        def __init__(self): self.calls = []
        def compute_camera(self, loc, rot, dt):
            self.calls.append((loc, rot, dt))
            return ((1, 2, 3), (4, 5, 6), (0, 0, 1))

    cam = _RecordingCam()
    eye, target, up_vec = _compute_camera(
        _exterior_vm(), cam_control=cam,
        player=_FakePlayer(), dt=1.0/60)
    assert len(cam.calls) == 1
    assert (eye, target, up_vec) == ((1, 2, 3), (4, 5, 6), (0, 0, 1))


def test_exterior_camera_lock_bias_zero_aims_at_target():
    """target_lock_bias=0.0 puts the look-at directly on the target,
    centring it in the frame (the previous behaviour)."""
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.appc.math import TGPoint3, TGMatrix3

    class _Target:
        def GetWorldLocation(self): return TGPoint3(50.0, 60.0, 70.0)

    class _FakePlayer:
        def __init__(self, target): self._target = target
        def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
        def GetWorldRotation(self): return TGMatrix3()
        def GetTarget(self): return self._target

    class _StubCam:
        target_lock_enabled = True
        target_lock_bias    = 0.0
        def compute_camera(self, loc, rot, dt):
            return ((1, 2, 3), (4, 5, 6), (0, 0, 1))

    tgt = _Target()
    eye, target, up_vec = _compute_camera(
        _exterior_vm(), cam_control=_StubCam(),
        player=_FakePlayer(tgt), dt=1.0/60)
    # With bias=0 the look-at sits directly on the target.
    assert target == (50.0, 60.0, 70.0)
    # up_vec is reprojected perpendicular to the ship→target axis so the
    # camera up stays orthogonal to the view direction. The original
    # (0, 0, 1) had a component along the target ray; only the
    # orthogonal part survives. Magnitude must be unit and dot with the
    # view direction must be ≈ 0.
    import math
    tlen = math.sqrt(50*50 + 60*60 + 70*70)
    t_hat = (50/tlen, 60/tlen, 70/tlen)
    assert math.isclose(sum(c*c for c in up_vec), 1.0, rel_tol=1e-9)
    assert abs(sum(a*b for a, b in zip(up_vec, t_hat))) < 1e-9
    # The stub's eye (1, 2, 3) is on the SAME side of the ship as the
    # target — target lock must relocate it to the far side so the ship
    # sits between camera and target. Verify the ship-between invariant
    # rather than pinning a specific eye coordinate.
    ex, ey, ez = eye
    tx, ty, tz = target
    dx, dy, dz = tx - ex, ty - ey, tz - ez
    t_param = (-ex*dx + -ey*dy + -ez*dz) / (dx*dx + dy*dy + dz*dz)
    assert 0.0 < t_param < 1.0


def test_exterior_camera_lock_shifts_look_at_down_along_image_up():
    """Non-zero bias shifts the look-at along -up by bias × eye→target
    distance, so the target projects above image centre."""
    import math
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.appc.math import TGPoint3, TGMatrix3

    class _Target:
        def GetWorldLocation(self): return TGPoint3(0.0, 1000.0, 0.0)

    class _FakePlayer:
        def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
        def GetWorldRotation(self): return TGMatrix3()
        def GetTarget(self): return _Target()

    class _StubCam:
        target_lock_enabled = True
        target_lock_bias    = 0.15
        def compute_camera(self, loc, rot, dt):
            return ((0.0, -150.0, 50.0), (0.0, 0.0, 20.0), (0.0, 0.0, 1.0))

    eye, target, _ = _compute_camera(
        _exterior_vm(), cam_control=_StubCam(),
        player=_FakePlayer(), dt=1.0/60)
    # Target lock relocates the eye onto the line target→ship extended;
    # compute the bias shift from the relocated eye, not the stub's.
    dist = math.sqrt(
        (1000.0 - eye[1])**2 + eye[0]**2 + eye[2]**2)
    expected_z = 0.0 - 0.15 * dist * 1.0
    assert target[0] == 0.0
    assert target[1] == 1000.0
    assert target[2] == pytest.approx(expected_z, rel=1e-6)


def test_exterior_camera_lock_disabled_keeps_chase_target():
    """When cam_control.target_lock_enabled is False, the chase look-at
    point is preserved even if the player has a target."""
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.appc.math import TGPoint3, TGMatrix3

    class _Target:
        def GetWorldLocation(self): return TGPoint3(50.0, 60.0, 70.0)

    class _FakePlayer:
        def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
        def GetWorldRotation(self): return TGMatrix3()
        def GetTarget(self): return _Target()

    class _StubCam:
        target_lock_enabled = False
        def compute_camera(self, loc, rot, dt):
            return ((1, 2, 3), (4, 5, 6), (0, 0, 1))

    eye, target, up_vec = _compute_camera(
        _exterior_vm(), cam_control=_StubCam(),
        player=_FakePlayer(), dt=1.0/60)
    assert (eye, target, up_vec) == ((1, 2, 3), (4, 5, 6), (0, 0, 1))


def test_exterior_camera_unchanged_when_no_target():
    """GetTarget() returning None should leave the chase cam output alone."""
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.appc.math import TGPoint3, TGMatrix3

    class _FakePlayer:
        def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
        def GetWorldRotation(self): return TGMatrix3()
        def GetTarget(self): return None

    class _StubCam:
        def compute_camera(self, loc, rot, dt):
            return ((1, 2, 3), (4, 5, 6), (0, 0, 1))

    eye, target, up_vec = _compute_camera(
        _exterior_vm(), cam_control=_StubCam(),
        player=_FakePlayer(), dt=1.0/60)
    assert (eye, target, up_vec) == ((1, 2, 3), (4, 5, 6), (0, 0, 1))


def test_target_lock_places_ship_between_eye_and_target_when_target_behind_ship():
    """Bug case: target sits behind the player's ship (along body -Y).
    Default chase eye is also behind the ship — so looking at the target
    aims the camera further behind, leaving the ship behind the camera
    and off-screen.

    Contract: in target-lock mode, the eye must end up on the far side
    of the ship from the target, so the line eye→target passes through
    the ship's neighbourhood (ship between camera and target).
    """
    import math
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.appc.math import TGPoint3, TGMatrix3

    class _Target:
        def GetWorldLocation(self): return TGPoint3(0.0, -1000.0, 0.0)

    class _FakePlayer:
        def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
        def GetWorldRotation(self): return TGMatrix3()
        def GetTarget(self): return _Target()

    class _StubCam:
        target_lock_enabled = True
        target_lock_bias    = 0.0
        def compute_camera(self, loc, rot, dt):
            # Default chase eye: behind ship along body-Y, lifted along
            # body-Z. With target also behind ship, the old code would
            # leave this eye untouched and the ship would vanish.
            return ((0.0, -150.0, 50.0), (0.0, 0.0, 20.0), (0.0, 0.0, 1.0))

    eye, target, _ = _compute_camera(
        _exterior_vm(), cam_control=_StubCam(),
        player=_FakePlayer(), dt=1.0/60)

    # Ship at origin must project onto the eye→target segment with
    # 0 < t < 1 (strictly between, not at the endpoints).
    ex, ey, ez = eye
    tx, ty, tz = target
    dx, dy, dz = tx - ex, ty - ey, tz - ez
    sx, sy, sz = -ex, -ey, -ez   # ship - eye
    denom = dx*dx + dy*dy + dz*dz
    t = (sx*dx + sy*dy + sz*dz) / denom
    assert 0.0 < t < 1.0, (
        "ship must lie between eye and target; got t=%r, eye=%r, target=%r"
        % (t, eye, target))


def test_target_lock_eye_trajectory_is_smooth_as_target_orbits():
    """As the target rotates around the ship, the eye position must
    change continuously — no large jumps between adjacent angles. This
    guards against the kinked transition where the camera was anchored
    behind the ship until the target crossed some threshold, then
    snapped to the opposite side."""
    import math
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.appc.math import TGPoint3, TGMatrix3

    class _Target:
        def __init__(self, pos): self.pos = pos
        def GetWorldLocation(self): return TGPoint3(*self.pos)

    class _FakePlayer:
        def __init__(self): self._target = None
        def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
        def GetWorldRotation(self): return TGMatrix3()
        def GetTarget(self): return self._target

    class _StubCam:
        target_lock_enabled = True
        target_lock_bias    = 0.0
        def compute_camera(self, loc, rot, dt):
            # Default-ish chase: behind ship along body-Y, lifted in Z.
            return ((0.0, -150.0, 50.0), (0.0, 0.0, 20.0), (0.0, 0.0, 1.0))

    player = _FakePlayer()
    cam = _StubCam()
    vm = _exterior_vm()

    # Sample target position at small angular steps around the ship in
    # the XY plane and verify successive eye positions are close.
    N = 360
    R = 1000.0
    prev_eye = None
    max_step = 0.0
    for i in range(N + 1):
        theta = 2.0 * math.pi * i / N
        player._target = _Target((R * math.cos(theta), R * math.sin(theta), 0.0))
        eye, _, _ = _compute_camera(vm, cam_control=cam, player=player, dt=1.0/60)
        if prev_eye is not None:
            d = math.sqrt(sum((a - b)**2 for a, b in zip(eye, prev_eye)))
            if d > max_step:
                max_step = d
        prev_eye = eye

    # |eye - ship| is ≈ sqrt(150² + 50²) ≈ 158. A full revolution takes
    # ~2π × 158 ≈ 993 in arc length, so each of 360 steps averages ~2.76.
    # Allow generous slack but flag any jump >10× the average step.
    assert max_step < 30.0, "max step between adjacent eye positions: %r" % max_step


def test_target_lock_places_eye_on_target_ship_line_extended():
    """Camera should sit on the line target→ship, extended past the
    ship, then lifted along world-Z by cam_control.target_lock_z_lift.
    Verify the line invariant after subtracting the lift, and verify
    eye[2] == on_line[2] + z_lift."""
    import math
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.appc.math import TGPoint3, TGMatrix3

    class _Target:
        def __init__(self, pos): self.pos = pos
        def GetWorldLocation(self): return TGPoint3(*self.pos)

    class _FakePlayer:
        def __init__(self): self._target = None
        def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
        def GetWorldRotation(self): return TGMatrix3()
        def GetTarget(self): return self._target

    Z_LIFT = 50.0

    class _StubCam:
        target_lock_enabled = True
        target_lock_bias    = 0.0
        target_lock_z_lift  = Z_LIFT
        def compute_camera(self, loc, rot, dt):
            return ((0.0, -75.0, 22.5), (0.0, 0.0, 10.0), (0.0, 0.0, 1.0))

    player = _FakePlayer()
    cam = _StubCam()
    vm = _exterior_vm()
    chase_dist = math.sqrt(75.0**2 + 22.5**2)

    for tx, ty, tz in [(0.0, 1000.0, 0.0),     # target in front
                       (0.0, -1000.0, 0.0),    # target directly behind
                       (1000.0, 0.0, 0.0),     # target to the side
                       (500.0, -500.0, 200.0)]:# target arbitrary direction
        player._target = _Target((tx, ty, tz))
        eye, _, _ = _compute_camera(vm, cam_control=cam, player=player, dt=1.0/60)

        # Undo the z-lift to recover the on-line position.
        on_line = (eye[0], eye[1], eye[2] - Z_LIFT)
        ex, ey, ez = on_line
        bx, by, bz = -tx, -ty, -tz   # ship - target (ship at origin)
        bm = math.sqrt(bx*bx + by*by + bz*bz)
        em = math.sqrt(ex*ex + ey*ey + ez*ez)
        cos_a = (ex*bx + ey*by + ez*bz) / (em * bm)
        assert math.isclose(cos_a, 1.0, abs_tol=1e-9), (
            "eye not on the extended line after subtracting z_lift; "
            "cos=%r for target=%r" % (cos_a, (tx, ty, tz)))
        assert math.isclose(em, chase_dist, rel_tol=1e-9)


def test_camera_control_sets_target_lock_z_lift_from_ship_radius():
    """set_ship_radius must populate target_lock_z_lift as
    CAM_TARGET_LOCK_LIFT_RADII × radius so the host-loop's z-lift
    scales with the player ship."""
    from engine.host_loop import _CameraControl, CAM_TARGET_LOCK_LIFT_RADII
    cc = _CameraControl()
    cc.set_ship_radius(42.0)
    assert cc.target_lock_z_lift == CAM_TARGET_LOCK_LIFT_RADII * 42.0


def test_target_lock_z_lift_raises_eye_in_world_z():
    """With z_lift > 0, the eye z-coordinate equals the on-line z plus
    the lift exactly — no horizontal displacement, no orbit-dependent
    bob (constant lift)."""
    import math
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.appc.math import TGPoint3, TGMatrix3

    class _Target:
        def GetWorldLocation(self): return TGPoint3(0.0, -1000.0, 0.0)

    class _FakePlayer:
        def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
        def GetWorldRotation(self): return TGMatrix3()
        def GetTarget(self): return _Target()

    class _StubCam:
        target_lock_enabled = True
        target_lock_bias    = 0.0
        target_lock_z_lift  = 0.0
        def compute_camera(self, loc, rot, dt):
            return ((0.0, -75.0, 22.5), (0.0, 0.0, 10.0), (0.0, 0.0, 1.0))

    cam = _StubCam()
    player = _FakePlayer()
    vm = _exterior_vm()

    cam.target_lock_z_lift = 0.0
    eye_no_lift, _, _ = _compute_camera(vm, cam_control=cam, player=player, dt=1.0/60)

    cam.target_lock_z_lift = 50.0
    eye_lifted, _, _ = _compute_camera(vm, cam_control=cam, player=player, dt=1.0/60)

    assert eye_lifted[0] == eye_no_lift[0]
    assert eye_lifted[1] == eye_no_lift[1]
    assert math.isclose(eye_lifted[2], eye_no_lift[2] + 50.0, rel_tol=1e-9)


def test_target_lock_keeps_eye_behind_ship_when_target_in_front():
    """Regression guard: if the chase eye is already on the far side of
    the ship from the target, target-lock must not flip it to the wrong
    side. Ship at origin, target at +Y, eye at -Y → eye stays at -Y."""
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.appc.math import TGPoint3, TGMatrix3

    class _Target:
        def GetWorldLocation(self): return TGPoint3(0.0, 1000.0, 0.0)

    class _FakePlayer:
        def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
        def GetWorldRotation(self): return TGMatrix3()
        def GetTarget(self): return _Target()

    class _StubCam:
        target_lock_enabled = True
        target_lock_bias    = 0.0
        def compute_camera(self, loc, rot, dt):
            return ((0.0, -150.0, 50.0), (0.0, 0.0, 20.0), (0.0, 0.0, 1.0))

    eye, target, _ = _compute_camera(
        _exterior_vm(), cam_control=_StubCam(),
        player=_FakePlayer(), dt=1.0/60)

    # Eye should remain behind ship (negative Y), target-side component
    # along ship→target axis (0,1,0) must be non-positive.
    assert eye[1] <= 0.0
    # And ship is still between eye and target.
    ex, ey, ez = eye
    tx, ty, tz = target
    dx, dy, dz = tx - ex, ty - ey, tz - ez
    t = (-ex*dx + -ey*dy + -ez*dz) / (dx*dx + dy*dy + dz*dz)
    assert 0.0 < t < 1.0
