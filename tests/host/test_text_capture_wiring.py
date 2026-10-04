"""While a CEF text field holds the keyboard, the game's own key consumers
hear nothing -- and they get clean releases at the boundaries.

The fake host below reproduces the native contract exactly: KeyGate
(native/src/renderer/key_gate.cc) filtering every level read, plus
key_pressed's prev snapshot taken at end of frame (host_bindings.cc frame()).
The pollers, pause controller and modal-ESC router are the REAL ones.

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S7.5
"""
import App
import pytest

from engine import host_io, host_loop
from engine.host_loop import (_PauseMenuController, _dispatch_modal_esc,
                              _poll_fire_keys, _poll_raw_keyboard)
from engine.input_map import GLFW_KEYS, InputMap
from engine.ui.panel import Panel
from engine.ui.panel_registry import PanelRegistry
from engine.ui.text_capture import TextCaptureController


class _Keys:
    KEY_SPACE = 32
    KEY_1 = 49
    KEY_S = ord("S")
    KEY_W = ord("W")
    KEY_F = ord("F")
    KEY_X = ord("X")
    KEY_G = ord("G")
    KEY_ESCAPE = 256
    KEY_F1 = 290
    KEY_F6 = 295
    KEY_F9 = 298
    KEY_LEFT_SHIFT = 340
    KEY_LEFT_CONTROL = 341
    KEY_LEFT_ALT = 342
    KEY_RIGHT_SHIFT = 344
    KEY_RIGHT_CONTROL = 345
    KEY_RIGHT_ALT = 346


class _GatedHost:
    """Native contract: KeyGate + polled-key mask + end-of-frame prev snapshot."""
    keys = _Keys()

    def __init__(self):
        self.raw = set()           # physically held
        self._captured = False
        self._mask = set()
        self._polled = set()
        self._prev = {}
        self.queue = []
        self.sent = []
        self.translator_resets = 0

    # KeyGate::report
    def key_state(self, k):
        self._polled.add(k)
        raw = k in self.raw
        if self._captured:
            return False
        if k in self._mask:
            if raw:
                return False
            self._mask.discard(k)
        return raw

    def key_pressed(self, k):
        # Mirrors native exactly (host_bindings.cc ~6221-6235): `prev` is
        # read from the map BEFORE any insert, defaulting to False when the
        # key has never been queried -- so a key already held on its FIRST
        # query IS reported as a rising edge (`now && !prev` == `now`).
        # Only on that first query does this write `now` into the map; every
        # later query reads whatever end_frame()'s pre-poll snapshot left.
        now = self.key_state(k)
        prev = self._prev.get(k, False)
        if k not in self._prev:
            self._prev[k] = now
        return now and not prev

    def end_frame(self):
        for k in self._prev:
            self._prev[k] = self.key_state(k)

    # Window::set_key_capture
    def set_key_capture(self, on):
        if on:
            self._captured = True
            self._mask.clear()
        elif self._captured:
            self._captured = False
            self._mask |= {k for k in self._polled if k in self.raw}

    def key_capture_active(self):
        return self._captured

    def drain_text_events(self):
        out, self.queue = self.queue, []
        return out

    def cef_send_text_events(self, events):
        self.sent.extend(events)

    def cef_reset_text_translator(self):
        self.translator_resets += 1


class _Owner(Panel):
    name = "probe"

    def __init__(self):
        super().__init__()
        self.esc_calls = 0

    def is_open(self):
        return True

    def handle_key_esc(self):
        self.esc_calls += 1

    def render_payload(self):
        return None

    def dispatch_event(self, action):
        return False


class _NoCrewMenu:
    def has_open_menu(self):
        return False


_RAW_SEEN = []
_HANDLER = __name__ + "._on_raw_keyboard"


def _on_raw_keyboard(obj, event):
    _RAW_SEEN.append(event.GetUnicode())


@pytest.fixture
def rig(monkeypatch):
    import KeyConfig
    KeyConfig.MapScancodes()
    host_loop._fn_key_prev.clear()
    host_loop._raw_key_pairs_host = None
    _RAW_SEEN.clear()
    App.g_kRootWindow.AddPythonFuncHandlerForInstance(App.ET_KEYBOARD, _HANDLER)
    host = _GatedHost()
    monkeypatch.setattr(host_io, "_h", host)
    downs, ups = [], []
    monkeypatch.setattr(App.g_kInputManager, "OnKeyDown", lambda wc: downs.append(wc))
    monkeypatch.setattr(App.g_kInputManager, "OnKeyUp", lambda wc: ups.append(wc))
    reg = PanelRegistry()
    owner = _Owner()
    reg.register(owner)
    cap = TextCaptureController(reg)
    reg.register(cap)
    im = InputMap()
    pause = _PauseMenuController()

    def frame(blockers=()):
        """One host frame's worth of the real key consumers, then the
        native end-of-frame snapshot."""
        cap.tick()
        _dispatch_modal_esc(list(blockers), _NoCrewMenu(), pause, host)
        _poll_fire_keys(host, im)
        _poll_raw_keyboard(host, im)
        host.end_frame()

    yield host, cap, owner, pause, downs, ups, frame
    App.g_kRootWindow.RemoveHandlerForInstance(App.ET_KEYBOARD, _HANDLER)
    _RAW_SEEN.clear()
    host_loop._fn_key_prev.clear()
    host_loop._raw_key_pairs_host = None


def test_nothing_reaches_the_game_while_a_field_is_focused(rig):
    host, cap, owner, pause, downs, ups, frame = rig
    frame()                                       # register keys, idle
    cap.dispatch_event("focus:probe")
    host.raw |= {_Keys.KEY_W, _Keys.KEY_SPACE, GLFW_KEYS["F"], _Keys.KEY_1,
                 _Keys.KEY_ESCAPE}
    for _ in range(3):
        frame(blockers=[owner])
    assert downs == []                            # no fire, no input-manager press
    assert _RAW_SEEN == []                        # no raw ET_KEYBOARD
    assert owner.esc_calls == 0                   # Esc never reached the panel
    frame()                                       # no blockers: pause path
    assert pause.is_open is False


def test_a_fire_key_held_when_focus_arrives_gets_a_clean_release(rig):
    """Review Focus 3."""
    host, cap, _owner, _pause, downs, ups, frame = rig
    host.raw.add(GLFW_KEYS["F"])
    frame()
    assert downs == [App.WC_F]                    # firing
    cap.dispatch_event("focus:probe")
    frame()
    assert ups == [App.WC_F]                      # firing stops
    frame()
    assert downs == [App.WC_F] and ups == [App.WC_F]   # and stays stopped


def test_the_esc_that_blurred_the_field_does_not_open_pause(rig):
    """Review Focus 5: Esc reverts+blurs in the page, and the same physical
    press is still down on the following frames."""
    host, cap, _owner, pause, _downs, _ups, frame = rig
    frame()
    cap.dispatch_event("focus:probe")
    host.raw.add(_Keys.KEY_ESCAPE)
    frame()
    cap.dispatch_event("blur")                    # page handled Esc
    frame()
    frame()
    assert pause.is_open is False                 # still held: masked
    host.raw.discard(_Keys.KEY_ESCAPE)
    frame()
    assert pause.is_open is False
    host.raw.add(_Keys.KEY_ESCAPE)                # a NEW press
    frame()
    assert pause.is_open is True


def test_typed_text_reaches_cef_only_while_focused(rig):
    host, cap, _owner, _pause, _downs, _ups, frame = rig
    host.queue = [(0, ord("w"), 0, 1, 0)]
    frame()
    assert host.sent == []
    cap.dispatch_event("focus:probe")
    host.queue = [(0, ord("-"), 0, 1, 0)]
    frame()
    assert host.sent == [(0, ord("-"), 0, 1, 0)]
