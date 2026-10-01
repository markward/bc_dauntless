"""The compiled module exposes the keyboard bindings (a stale .so must fail
here, not silently leave the Mods screen un-typeable)."""
import _dauntless_host as h


def test_bindings_exist():
    for name in ("drain_text_events", "cef_send_key_event"):
        assert hasattr(h, name), name


def test_send_key_event_without_a_browser_is_a_noop():
    h.cef_send_key_event(0, ord("a"), 0, 1, 0)       # no browser alive in pytest
    h.cef_send_key_event(1, 259, 51, 1, 0)           # GLFW_KEY_BACKSPACE
