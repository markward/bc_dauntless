"""TextCaptureController: page focus reports -> native key gate, the queue
forwarded only while a field holds the keyboard, and every release trigger.

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S4
"""
import pytest

from engine import host_io
from engine.ui.panel import Panel
from engine.ui.panel_registry import PanelRegistry
from engine.ui.text_capture import BLUR_SCRIPT, TextCaptureController


class _Host:
    """Stand-in for _dauntless_host's capture + text-queue bindings."""

    def __init__(self):
        self.captured = False
        self.capture_calls = []
        self.queue = []
        self.sent = []
        self.batches = []
        self.translator_resets = 0

    def set_key_capture(self, on):
        self.capture_calls.append(on)
        self.captured = on

    def key_capture_active(self):
        return self.captured

    def drain_text_events(self):
        out, self.queue = self.queue, []
        return out

    def cef_send_text_events(self, events):
        self.batches.append(list(events))
        self.sent.extend(events)

    def cef_reset_text_translator(self):
        self.translator_resets += 1


class _Owner(Panel):
    def __init__(self, name="probe", is_open=True):
        super().__init__()
        self._name = name
        self.open_ = is_open

    @property
    def name(self):
        return self._name

    def is_open(self):
        return self.open_

    def render_payload(self):
        return None

    def dispatch_event(self, action):
        return False


@pytest.fixture
def env(monkeypatch):
    host = _Host()
    monkeypatch.setattr(host_io, "_h", host)
    reg = PanelRegistry()
    owner = _Owner()
    reg.register(owner)
    cap = TextCaptureController(reg)
    reg.register(cap)
    return host, reg, owner, cap


def test_registry_find():
    reg = PanelRegistry()
    p = _Owner("x")
    reg.register(p)
    assert reg.find("x") is p
    assert reg.find("nope") is None


def test_focus_on_an_open_owner_captures(env):
    host, reg, owner, cap = env
    assert reg.dispatch("kbd/focus:probe") is True
    assert cap.owner == "probe"
    assert host.captured is True
    assert cap.render_payload() is None
    # A key held across the boundary must not replay a stale KEYUP into a
    # field that never saw its KEYDOWN.
    assert host.translator_resets == 1


@pytest.mark.parametrize("name", ["", "nope"])
def test_focus_on_an_unknown_or_untagged_owner_is_refused(env, name, caplog):
    host, _reg, _owner, cap = env
    cap.dispatch_event("focus:" + name)
    assert cap.owner is None
    assert host.captured is False
    assert cap.render_payload() == BLUR_SCRIPT
    assert cap.render_payload() is None          # exactly once
    assert "data-panel" in caplog.text


def test_focus_on_a_closed_owner_is_refused(env):
    host, _reg, owner, cap = env
    owner.open_ = False
    cap.dispatch_event("focus:probe")
    assert host.captured is False
    assert cap.render_payload() == BLUR_SCRIPT


def test_blur_releases_without_a_payload(env):
    host, _reg, _owner, cap = env
    cap.dispatch_event("focus:probe")
    cap.dispatch_event("blur")
    assert cap.owner is None
    assert host.captured is False
    assert cap.render_payload() is None


def test_blur_is_idempotent(env):
    _host, _reg, _owner, cap = env
    assert cap.dispatch_event("blur") is True
    assert cap.dispatch_event("blur") is True
    assert cap.owner is None


def test_tab_between_two_fields_keeps_capture(env):
    """Review Focus 4: focusout to another editable sends nothing, then the
    new field's focusin re-sends focus: -- capture stays on, no blur."""
    host, _reg, _owner, cap = env
    cap.dispatch_event("focus:probe")
    cap.dispatch_event("focus:probe")
    cap.tick()
    assert host.captured is True
    assert cap.owner == "probe"
    assert cap.render_payload() is None


def test_moving_to_an_untagged_field_releases(env):
    """Review Focus 4: tabbing from a tagged field to an untagged one sends no
    blur (relatedTarget is editable) -- the refusal itself must release."""
    host, _reg, _owner, cap = env
    cap.dispatch_event("focus:probe")
    cap.dispatch_event("focus:")
    assert cap.owner is None
    assert host.captured is False
    assert cap.render_payload() == BLUR_SCRIPT


def test_owner_closing_releases_with_one_blur(env):
    host, _reg, owner, cap = env
    cap.dispatch_event("focus:probe")
    owner.open_ = False
    cap.tick()
    assert cap.owner is None
    assert host.captured is False
    assert cap.render_payload() == BLUR_SCRIPT
    assert cap.render_payload() is None


def test_owner_without_is_open_uses_visible(env):
    host, reg, _owner, cap = env

    class _Plain(Panel):
        name = "plain"
        def render_payload(self): return None
        def dispatch_event(self, a): return False

    plain = _Plain()
    reg.register(plain)
    cap.dispatch_event("focus:plain")
    assert host.captured is True
    plain.visible = False
    cap.tick()
    assert host.captured is False


def test_native_reset_drops_the_owner_silently(env):
    host, _reg, _owner, cap = env
    cap.dispatch_event("focus:probe")
    host.captured = False                        # page reloaded: native cleared it
    cap.tick()
    assert cap.owner is None
    assert cap.render_payload() is None          # no page left to blur


def test_release_with_an_owner(env):
    host, _reg, _owner, cap = env
    cap.dispatch_event("focus:probe")
    cap.release()
    assert cap.owner is None
    assert host.capture_calls[-1] is False
    assert cap.render_payload() == BLUR_SCRIPT
    assert host.translator_resets == 2          # once on focus, once on release


def test_release_without_an_owner_does_nothing(env):
    host, _reg, _owner, cap = env
    cap.release()
    assert host.capture_calls == []
    assert cap.render_payload() is None
    assert host.translator_resets == 0


def test_queue_forwarded_only_while_captured(env):
    host, _reg, _owner, cap = env
    host.queue = [(0, ord("w"), 0, 1, 0)]        # typed in flight
    cap.tick()
    assert host.sent == []                        # discarded, not saved for later
    cap.dispatch_event("focus:probe")
    host.queue = [(0, ord("-"), 0, 1, 0), (1, 259, 51, 1, 0)]
    cap.tick()
    assert host.sent == [(0, ord("-"), 0, 1, 0), (1, 259, 51, 1, 0)]
    assert host.batches == [[(0, ord("-"), 0, 1, 0), (1, 259, 51, 1, 0)]]  # one call, whole list
    cap.dispatch_event("blur")
    host.queue = [(0, ord("x"), 0, 1, 0)]
    cap.tick()
    assert len(host.sent) == 2


def test_native_reset_resets_the_translator_too(env):
    host, _reg, _owner, cap = env
    cap.dispatch_event("focus:probe")
    host.translator_resets = 0                    # isolate from the focus-gain reset above
    host.captured = False                          # page reloaded: native cleared it
    cap.tick()
    assert cap.owner is None
    assert host.translator_resets == 1


def test_headless_tick_is_a_noop(monkeypatch):
    monkeypatch.setattr(host_io, "_h", None)
    reg = PanelRegistry()
    cap = TextCaptureController(reg)
    cap.tick()
    cap.release()
    assert cap.owner is None
