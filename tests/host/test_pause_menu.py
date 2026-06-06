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


class _RecordingHost:
    """Records cef_execute_javascript and set_cursor_locked calls."""

    def __init__(self):
        self.scripts = []          # list of script strings
        self.cursor_lock_calls = []  # list of bool

    def cef_execute_javascript(self, script):
        self.scripts.append(script)

    def set_cursor_locked(self, locked):
        self.cursor_lock_calls.append(locked)


def test_pause_menu_side_effects_show_uses_flex():
    """Opening the menu fires a single execute_javascript call whose
    script targets the pause-menu element and sets display to 'flex'."""
    from engine.host_loop import (_PauseMenuController,
                                  _ViewModeController,
                                  _apply_pause_menu_side_effects,
                                  _NULL_PICKER)
    p = _PauseMenuController()
    p.toggle()  # closed → open
    vm = _ViewModeController()
    rc = _RecordingHost()
    _apply_pause_menu_side_effects(p, vm, rc, [_NULL_PICKER])
    assert len(rc.scripts) == 1
    assert "pause-menu" in rc.scripts[0]
    assert "'flex'" in rc.scripts[0]


def test_pause_menu_side_effects_hide_uses_none():
    """Closing the menu fires a single execute_javascript call whose
    script sets display to 'none'."""
    from engine.host_loop import (_PauseMenuController,
                                  _ViewModeController,
                                  _apply_pause_menu_side_effects,
                                  _NULL_PICKER)
    p = _PauseMenuController()
    p.toggle()  # closed → open
    vm = _ViewModeController()
    rc = _RecordingHost()
    _apply_pause_menu_side_effects(p, vm, rc, [_NULL_PICKER])   # initial sync (open)
    p.toggle()  # open → closed
    _apply_pause_menu_side_effects(p, vm, rc, [_NULL_PICKER])   # second sync (closed)
    assert len(rc.scripts) == 2
    assert "'none'" in rc.scripts[1]


def test_pause_menu_side_effects_idempotent_within_a_state():
    """Calling the sync helper twice without toggling must not re-fire
    the JS execution — only state changes should trigger it."""
    from engine.host_loop import (_PauseMenuController,
                                  _ViewModeController,
                                  _apply_pause_menu_side_effects,
                                  _NULL_PICKER)
    p = _PauseMenuController()
    vm = _ViewModeController()
    rc = _RecordingHost()
    _apply_pause_menu_side_effects(p, vm, rc, [_NULL_PICKER])   # initial sync (closed)
    _apply_pause_menu_side_effects(p, vm, rc, [_NULL_PICKER])   # no toggle in between
    assert len(rc.scripts) <= 1


def test_pause_menu_open_unlocks_cursor():
    """While paused the cursor must be unlocked so the player can
    interact with the overlay, even from a bridge-locked starting
    state."""
    from engine.host_loop import (_PauseMenuController,
                                  _ViewModeController,
                                  _apply_pause_menu_side_effects,
                                  _NULL_PICKER)
    p = _PauseMenuController()
    p.toggle()  # closed → open
    vm = _ViewModeController()  # bridge by default — cursor would be locked
    rc = _RecordingHost()
    _apply_pause_menu_side_effects(p, vm, rc, [_NULL_PICKER])
    assert rc.cursor_lock_calls == [False]


def test_pause_menu_close_invalidates_view_mode_latch():
    """Closing the menu must clear view_mode._last_synced_is_bridge so
    the next _apply_view_mode_side_effects call re-applies cursor lock
    and bridge-pass state. Without this, a player who paused while on
    the bridge would resume with the cursor still unlocked because the
    view-mode latch still reads True."""
    from engine.host_loop import (_PauseMenuController,
                                  _ViewModeController,
                                  _apply_pause_menu_side_effects,
                                  _NULL_PICKER)
    p = _PauseMenuController()
    vm = _ViewModeController()
    vm._last_synced_is_bridge = True  # simulate prior sync into bridge
    rc = _RecordingHost()
    p.toggle()  # closed → open
    _apply_pause_menu_side_effects(p, vm, rc, [_NULL_PICKER])
    p.toggle()  # open → closed
    _apply_pause_menu_side_effects(p, vm, rc, [_NULL_PICKER])
    assert vm._last_synced_is_bridge is None
