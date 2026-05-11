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


def test_view_mode_starts_exterior():
    from engine.host_loop import _ViewModeController
    vm = _ViewModeController()
    assert vm.is_exterior is True
    assert vm.is_bridge is False


def test_view_mode_toggle_on_space_pressed():
    from engine.host_loop import _ViewModeController
    vm = _ViewModeController()
    reader = _FakeKeyReader()

    # No space → no change.
    vm.apply(reader)
    assert vm.is_exterior is True

    # Space pressed once → bridge.
    reader.pressed_once.add(reader.keys.KEY_SPACE)
    vm.apply(reader)
    assert vm.is_bridge is True

    # No space → still bridge (edge-triggered, not held).
    vm.apply(reader)
    assert vm.is_bridge is True

    # Space pressed again → back to exterior.
    reader.pressed_once.add(reader.keys.KEY_SPACE)
    vm.apply(reader)
    assert vm.is_exterior is True
