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


_chain_log = []


def _swallowing_handler(dispatcher, event):
    _chain_log.append("swallow")
    # returns WITHOUT CallNextHandler -> chain stops (E1M1 tutorial shape)


def _exterior_vm():
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController
    top_window.reset_for_tests()
    vm = _ViewModeController()
    vm.toggle()  # bridge → exterior
    return vm


def test_view_mode_starts_in_bridge():
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController
    top_window.reset_for_tests()
    vm = _ViewModeController()
    assert vm.is_bridge is True
    assert vm.is_exterior is False


def test_view_mode_toggle_on_space_pressed():
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController
    top_window.reset_for_tests()
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


def test_space_toggle_suppressed_while_keyboard_input_removed():
    """MissionLib.RemoveControl (AllowKeyboardInput(0)) must hold the
    player's current view: the SPACE bridge/tactical toggle is keyboard
    input, and the E1M1 intro removes control for the whole walk-on +
    Liu-briefing + crew-intro stretch (E1M1.py:1860, no ReturnControl
    until char-select). The natively-polled SPACE toggle must respect the
    same flag the SDK keyboard dispatch already honours."""
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController
    top_window.reset_for_tests()
    vm = _ViewModeController()
    reader = _FakeKeyReader()

    # Mission removes control (RemoveControl → AllowKeyboardInput(0)).
    top_window.TopWindow_GetTopWindow().AllowKeyboardInput(0)

    # SPACE pressed while control is removed → view held on bridge.
    reader.pressed_once.add(reader.keys.KEY_SPACE)
    vm.apply(reader)
    assert vm.is_bridge is True

    # Control returned (ReturnControl → AllowKeyboardInput(1)) → SPACE works.
    top_window.TopWindow_GetTopWindow().AllowKeyboardInput(1)
    reader.pressed_once.add(reader.keys.KEY_SPACE)
    vm.apply(reader)
    assert vm.is_exterior is True


class _RecordingInputs:
    """Stand-ins for _PlayerControl / director that record whether
    apply() was called and what reader it was handed, without doing any
    work."""
    class _Player:
        def __init__(self): self.calls = []
        def apply(self, player, dt, h): self.calls.append(h)
    class _FakeChase:
        def __init__(self): self.calls = 0
        def apply(self, dt, h): self.calls += 1
    class _FakeDirector:
        def __init__(self, chase): self.chase = chase
    class _Camera:
        """Back-compat wrapper: .calls delegates to the inner chase.calls."""
        def __init__(self):
            _chase = _RecordingInputs._FakeChase()
            self._director = _RecordingInputs._FakeDirector(_chase)
            self._chase = _chase
        @property
        def calls(self): return self._chase.calls
        # Make this object pass as director to _apply_input.
        @property
        def chase(self): return self._chase

    def __init__(self):
        self.player = self._Player()
        self.camera = self._Camera()


def test_apply_input_calls_both_in_exterior_mode():
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController, _apply_input
    top_window.reset_for_tests()
    vm = _ViewModeController()
    vm.toggle()  # bridge → exterior
    inputs = _RecordingInputs()
    reader = _FakeKeyReader()
    _apply_input(vm, inputs.player, inputs.camera,
                 player=object(), dt=1.0/60, h=reader)
    assert len(inputs.player.calls) == 1
    assert inputs.player.calls[0] is reader  # exterior forwards live keys
    assert inputs.camera.calls == 1


def test_apply_input_in_bridge_keeps_player_integrating_with_no_input():
    """Bridge mode calls player_control.apply with a no-input reader so
    ship physics keep integrating (engines coast) while live keys are
    ignored. The orbit camera is not stepped at all."""
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController, _apply_input, _NO_INPUT
    top_window.reset_for_tests()
    vm = _ViewModeController()
    inputs = _RecordingInputs()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_SPACE)  # held key must not reach player
    _apply_input(vm, inputs.player, inputs.camera,
                 player=object(), dt=1.0/60, h=reader)
    assert len(inputs.player.calls) == 1
    assert inputs.player.calls[0] is _NO_INPUT
    assert inputs.camera.calls == 0


def test_apply_input_preserves_orbit_state_across_bridge_toggle():
    """Spec test 5: entering bridge mode must not mutate _CameraControl
    orbit state, so toggling back restores the same exterior framing."""
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController, _CameraControl, _apply_input
    top_window.reset_for_tests()

    class _FakeDirectorWithChase:
        def __init__(self, chase): self.chase = chase

    cc = _CameraControl()
    cc.orbit_yaw_rad = 1.234
    cc.orbit_pitch_rad = -0.5
    cc.distance = 4242.0
    saved = (cc.orbit_yaw_rad, cc.orbit_pitch_rad, cc.distance)

    vm = _ViewModeController()
    reader = _FakeKeyReader()

    # Drive a "tick" in bridge mode: _apply_input must not call cc.apply()
    # at all, so the orbit state (yaw/pitch/distance) stays frozen.
    class _NoopPlayer:
        def apply(self, *a, **k): pass
    _apply_input(vm, _NoopPlayer(), _FakeDirectorWithChase(cc),
                 player=object(), dt=1.0/60, h=reader)
    assert (cc.orbit_yaw_rad, cc.orbit_pitch_rad, cc.distance) == saved


def test_apply_input_in_bridge_keeps_ship_moving_under_real_player_control():
    """Regression: pressing space while engines are engaged must NOT
    freeze the ship — it should keep coasting forward at its current
    speed. Drives the real _PlayerControl against a fake ship to prove
    that the integration step still runs in bridge mode."""
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController, _PlayerControl, _apply_input
    from engine.appc.math import TGPoint3, TGMatrix3
    top_window.reset_for_tests()

    class _FakeShip:
        def __init__(self):
            self._loc = TGPoint3(0.0, 0.0, 0.0)
            self._rot = TGMatrix3()
            self._vel = TGPoint3(0.0, 0.0, 0.0)
        def GetWorldRotation(self): return self._rot
        def GetTranslate(self):     return self._loc
        def SetMatrixRotation(self, R): self._rot = R
        def SetTranslateXYZ(self, x, y, z):
            self._loc = TGPoint3(x, y, z)
        def SetVelocity(self, v): self._vel = TGPoint3(v.x, v.y, v.z)
        def GetVelocity(self):    return self._vel
        # No ImpulseEngineSubsystem → _PlayerControl falls back to legacy
        # IMPULSE_UNIT * level for target speed.
        GetImpulseEngineSubsystem = None

    pc = _PlayerControl()
    pc.impulse_level = 5
    pc._current_speed = 5 * _PlayerControl.IMPULSE_UNIT  # already at target
    ship = _FakeShip()

    vm = _ViewModeController()

    class _NoopChase:
        def apply(self, *a, **k): pass
    class _NoopDirector:
        chase = _NoopChase()

    reader = _FakeKeyReader()
    # Tick a few times in bridge mode. The ship must move forward.
    for _ in range(10):
        _apply_input(vm, pc, _NoopDirector(),
                     player=ship, dt=1.0/60, h=reader)

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
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController, _apply_view_mode_side_effects
    top_window.reset_for_tests()
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
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController, _compute_camera
    from engine.cameras import _CameraDirector
    from engine.appc.math import TGPoint3, TGMatrix3
    top_window.reset_for_tests()

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


def test_space_edge_dispatches_through_top_window_chain():
    """SPACE must route through the SDK event chain (missions swallow it),
    not flip state directly."""
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController
    top_window.reset_for_tests()
    _chain_log.clear()
    top_window.TopWindow_GetTopWindow().AddPythonFuncHandlerForInstance(
        top_window.ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL,
        __name__ + "._swallowing_handler")
    vm = _ViewModeController()
    assert vm.is_bridge

    class _H:
        class keys: KEY_SPACE = 32
        def key_pressed(self, code): return code == self.keys.KEY_SPACE
    vm.apply(_H())
    assert _chain_log == ["swallow"]
    assert vm.is_bridge                      # held on bridge by the mission


def test_controller_reads_top_window_truth():
    """ForceBridgeVisible from SDK code must be visible to the host with
    no listener wiring — the pull model's core promise."""
    import engine.appc.top_window as top_window
    from engine.host_loop import _ViewModeController
    top_window.reset_for_tests()
    vm = _ViewModeController()
    top_window.TopWindow_GetTopWindow().ForceTacticalVisible()
    assert vm.is_exterior
    top_window.TopWindow_GetTopWindow().ForceBridgeVisible()
    assert vm.is_bridge


