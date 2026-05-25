"""Unit tests for _PauseMenuController — ESC-toggled pause overlay.
Mirrors the fake-bindings pattern from tests/host/test_view_mode.py."""


class _FakeKeys:
    KEY_ESCAPE = 256


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


def test_pause_menu_starts_closed():
    from engine.host_loop import _PauseMenuController
    p = _PauseMenuController()
    assert p.is_open is False


def test_pause_menu_toggle_on_escape_pressed():
    from engine.host_loop import _PauseMenuController
    p = _PauseMenuController()
    reader = _FakeKeyReader()

    # No esc → no change.
    p.apply(reader)
    assert p.is_open is False

    # Esc pressed once → open.
    reader.pressed_once.add(reader.keys.KEY_ESCAPE)
    p.apply(reader)
    assert p.is_open is True

    # No esc → still open (edge-triggered, not held).
    p.apply(reader)
    assert p.is_open is True

    # Esc pressed again → closed.
    reader.pressed_once.add(reader.keys.KEY_ESCAPE)
    p.apply(reader)
    assert p.is_open is False


def test_pause_menu_held_escape_does_not_re_toggle():
    """Held ESC must not flicker the menu — only edge presses toggle."""
    from engine.host_loop import _PauseMenuController
    p = _PauseMenuController()
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_ESCAPE)  # held but no edge
    for _ in range(10):
        p.apply(reader)
    assert p.is_open is False
