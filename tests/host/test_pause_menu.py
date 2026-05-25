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


class _RecordingCef:
    """Records cef_execute_javascript calls for assertion."""

    def __init__(self):
        self.scripts = []  # list of script strings

    def cef_execute_javascript(self, script):
        self.scripts.append(script)


def test_pause_menu_side_effects_show_uses_flex():
    """Opening the menu fires a single execute_javascript call whose
    script targets the pause-menu element and sets display to 'flex'."""
    from engine.host_loop import (_PauseMenuController,
                                  _apply_pause_menu_side_effects)
    p = _PauseMenuController()
    p.toggle()  # closed → open
    rc = _RecordingCef()
    _apply_pause_menu_side_effects(p, rc)
    assert len(rc.scripts) == 1
    assert "pause-menu" in rc.scripts[0]
    assert "'flex'" in rc.scripts[0]


def test_pause_menu_side_effects_hide_uses_none():
    """Closing the menu fires a single execute_javascript call whose
    script sets display to 'none'."""
    from engine.host_loop import (_PauseMenuController,
                                  _apply_pause_menu_side_effects)
    p = _PauseMenuController()
    p.toggle()  # closed → open
    rc = _RecordingCef()
    _apply_pause_menu_side_effects(p, rc)   # initial sync (open)
    p.toggle()  # open → closed
    _apply_pause_menu_side_effects(p, rc)   # second sync (closed)
    assert len(rc.scripts) == 2
    assert "'none'" in rc.scripts[1]


def test_pause_menu_side_effects_idempotent_within_a_state():
    """Calling the sync helper twice without toggling must not re-fire
    the JS execution — only state changes should trigger it."""
    from engine.host_loop import (_PauseMenuController,
                                  _apply_pause_menu_side_effects)
    p = _PauseMenuController()
    rc = _RecordingCef()
    _apply_pause_menu_side_effects(p, rc)   # initial sync (closed)
    _apply_pause_menu_side_effects(p, rc)   # no toggle in between
    assert len(rc.scripts) <= 1
