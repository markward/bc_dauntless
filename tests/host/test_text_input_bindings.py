"""The compiled module exposes the keyboard bindings (a stale .so must fail
here, not silently leave the Mods screen un-typeable)."""
import pytest

import _dauntless_host as h

from engine import host_io


def test_bindings_exist():
    for name in ("drain_text_events", "cef_send_key_event", "request_relaunch"):
        assert hasattr(h, name), name


def test_bindings_are_required():
    assert {"drain_text_events", "cef_send_key_event", "request_relaunch"} <= host_io._REQUIRED_BINDINGS


def test_send_key_event_without_a_browser_is_a_noop():
    h.cef_send_key_event(0, ord("a"), 0, 1, 0)       # no browser alive in pytest
    h.cef_send_key_event(1, 259, 51, 1, 0)           # GLFW_KEY_BACKSPACE


def test_capture_bindings_exist_and_are_required():
    for name in ("set_key_capture", "key_capture_active"):
        assert hasattr(h, name), name
    assert {"set_key_capture", "key_capture_active"} <= host_io._REQUIRED_BINDINGS


def test_key_capture_is_inactive_without_a_window():
    assert h.key_capture_active() is False


def test_set_key_capture_without_a_window_raises():
    with pytest.raises(RuntimeError):
        h.set_key_capture(True)
