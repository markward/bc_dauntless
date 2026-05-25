"""Tests for engine.ui.pause_menu — model, navigation, render payload."""

import json
import pytest

from engine.ui.pause_menu import PauseMenuModel, default_pause_menu


class _FakeKeys:
    KEY_UP = 1
    KEY_DOWN = 2
    KEY_ENTER = 3


class _FakeKeysNoEnter:
    """Pre-KEY_ENTER bindings, to verify the model degrades cleanly."""
    KEY_UP = 1
    KEY_DOWN = 2


class _FakeReader:
    def __init__(self, keys_cls=_FakeKeys):
        self.keys = keys_cls()
        self._pressed = set()

    def press(self, key):
        self._pressed.add(key)

    def key_pressed(self, key):
        if key in self._pressed:
            self._pressed.discard(key)
            return True
        return False


# ---- item management ----------------------------------------------------

def test_default_pause_menu_has_exit_and_cancel():
    exited = []
    cancelled = []
    m = default_pause_menu(on_exit=lambda: exited.append(1),
                           on_cancel=lambda: cancelled.append(1))
    assert [it.action_id for it in m.items] == ["exit", "cancel"]


def test_initial_state_has_no_row_focused():
    """The menu must paint with nothing highlighted before the user
    signals intent — otherwise the player sees what looks like Exit
    Program already pre-selected and may misread it as one-click-away."""
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    assert m.focused_index == -1


def test_activate_with_no_focus_is_noop():
    """Pressing Enter before any arrow key must not fire any handler."""
    fired = []
    m = default_pause_menu(on_exit=lambda: fired.append("exit"),
                           on_cancel=lambda: fired.append("cancel"))
    m.activate()
    assert fired == []


def test_first_focus_next_lands_on_row_zero():
    """Down from the unfocused initial state goes to the top row."""
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    m.focus_next()
    assert m.focused_index == 0


def test_first_focus_prev_lands_on_last_row():
    """Up from the unfocused initial state goes to the bottom row —
    matches macOS / GTK list-nav convention."""
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    m.focus_prev()
    assert m.focused_index == 1  # last row in a 2-item list


def test_invalidate_resets_focus():
    """Closing the pause menu (which calls invalidate) must reset focus
    so the next open starts from the unfocused state again."""
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    m.focus_next()  # focus = 0
    m.invalidate()
    assert m.focused_index == -1


def test_add_item_rejects_duplicate_action_id():
    m = PauseMenuModel()
    m.add_item("Foo", "foo", lambda: None)
    with pytest.raises(ValueError):
        m.add_item("Foo again", "foo", lambda: None)


# ---- navigation ---------------------------------------------------------

def test_focus_wraps_top_and_bottom():
    """Once focus has landed, ↑/↓ wraps the list circularly."""
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    m.focus_next()  # -1 → 0
    assert m.focused_index == 0
    m.focus_next()  # 0 → 1
    assert m.focused_index == 1
    m.focus_next()  # wrap 1 → 0
    assert m.focused_index == 0
    m.focus_prev()  # wrap 0 → 1
    assert m.focused_index == 1


def test_navigation_on_empty_model_is_a_noop():
    m = PauseMenuModel()
    m.focus_next()
    m.focus_prev()
    m.activate()
    assert m.focused_index == -1


# ---- input glue ---------------------------------------------------------

def test_handle_input_arrows_and_enter():
    exited = []
    cancelled = []
    m = default_pause_menu(on_exit=lambda: exited.append(1),
                           on_cancel=lambda: cancelled.append(1))
    r = _FakeReader()
    r.press(r.keys.KEY_DOWN)
    m.handle_input(r)
    assert m.focused_index == 0  # first ↓ from -1 lands on row 0
    r.press(r.keys.KEY_DOWN)
    m.handle_input(r)
    assert m.focused_index == 1  # second ↓ moves to cancel
    r.press(r.keys.KEY_ENTER)
    m.handle_input(r)
    assert cancelled == [1] and exited == []


def test_handle_input_without_key_enter_skips_activation():
    """Older bindings without KEY_ENTER should still allow navigation
    without crashing; activation is simply unavailable."""
    activated = []
    m = PauseMenuModel()
    m.add_item("A", "a", lambda: activated.append("a"))
    r = _FakeReader(keys_cls=_FakeKeysNoEnter)
    r.press(r.keys.KEY_DOWN)
    m.handle_input(r)  # must not raise
    assert activated == []


# ---- render payload -----------------------------------------------------

def test_render_payload_first_call_emits_full_state():
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    out = m.render_payload()
    assert out is not None
    assert out.startswith("setPauseMenu(") and out.endswith(");")
    body = out[len("setPauseMenu("):-len(");")]
    payload = json.loads(body)
    # Initial state paints nothing focused — JS reads -1 (or missing) as
    # "no row keyboard-focused" so the menu opens neutral.
    assert payload["focused"] == -1
    assert [it["action"] for it in payload["items"]] == ["exit", "cancel"]
    assert [it["label"] for it in payload["items"]] == ["Exit Program", "Cancel"]


def test_render_payload_idempotent_when_state_unchanged():
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    assert m.render_payload() is not None
    assert m.render_payload() is None  # no change → no re-emit


def test_render_payload_re_emits_after_focus_change():
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    m.render_payload()
    m.focus_next()  # -1 → 0
    out = m.render_payload()
    assert out is not None
    assert '"focused": 0' in out


def test_render_payload_re_emits_after_invalidate():
    """invalidate() simulates a CEF page reload — Python must re-push
    its model to repopulate the DOM."""
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    m.render_payload()
    assert m.render_payload() is None
    m.invalidate()
    assert m.render_payload() is not None


def test_render_payload_re_emits_after_item_added():
    m = default_pause_menu(on_exit=lambda: None, on_cancel=lambda: None)
    m.render_payload()
    m.add_item("Save Game", "save", lambda: None)
    out = m.render_payload()
    assert out is not None and '"save"' in out


# ---- event dispatch (CEF click channel) ---------------------------------

def test_dispatch_event_fires_matching_handler_regardless_of_focus():
    """A click can target any row, not just the focused one — and
    works even from the initial unfocused state."""
    exited = []
    cancelled = []
    m = default_pause_menu(on_exit=lambda: exited.append(1),
                           on_cancel=lambda: cancelled.append(1))
    assert m.focused_index == -1
    assert m.dispatch_event("cancel") is True
    assert cancelled == [1] and exited == []


def test_dispatch_event_unknown_action_is_noop():
    fired = []
    m = PauseMenuModel()
    m.add_item("A", "a", lambda: fired.append("a"))
    assert m.dispatch_event("ghost") is False
    assert fired == []
