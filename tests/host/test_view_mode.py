"""Unit tests for _ViewModeController — space-bar toggled bridge/exterior
view modality. Mirrors the fake-bindings pattern from
tests/host/test_camera_control.py."""
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
    from engine.cameras import _CameraDirector
    from engine.appc.math import TGPoint3, TGMatrix3

    class _FakePlayer:
        def __init__(self, loc, rot):
            self._loc, self._rot = loc, rot
        def GetWorldLocation(self): return self._loc
        def GetWorldRotation(self): return self._rot

    loc = TGPoint3(100.0, 200.0, 300.0)
    rot = TGMatrix3()  # identity — forward = (0,1,0), up = (0,0,1)
    player = _FakePlayer(loc, rot)

    vm = _ViewModeController()  # starts in bridge mode
    director = _CameraDirector()

    eye, target, up_vec = _compute_camera(
        vm, director, player=player, dt=1.0/60)

    assert eye    == (100.0, 200.0, 300.0)
    assert target == (100.0, 201.0, 300.0)  # +1 along world-Y (= ship forward)
    assert up_vec == (0.0,   0.0,   1.0)


def test_exterior_camera_delegates_to_director():
    """Sanity check: exterior mode routes through the director."""
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.cameras import _CameraDirector
    from engine.appc.math import TGPoint3, TGMatrix3

    class _FakePlayer:
        def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
        def GetWorldRotation(self): return TGMatrix3()

    director = _CameraDirector()
    eye, target, up_vec = _compute_camera(
        _exterior_vm(), director,
        player=_FakePlayer(), dt=1.0/60)
    # director.compute returns a 3-tuple of 3-tuples; just verify shape
    assert len(eye) == 3
    assert len(target) == 3
    assert len(up_vec) == 3


