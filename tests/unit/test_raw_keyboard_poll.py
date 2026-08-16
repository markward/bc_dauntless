"""The host-side poller that forwards ordinary keystrokes as BC's raw
ET_KEYBOARD window event.

Before this poller existed the ONLY keys the host forwarded into
g_kInputManager were mouse buttons, the crew-talk F-keys, the fire keys and
the ALT/CTRL/CAPS chords -- so an SDK script that hooks App.ET_KEYBOARD
(E1M1.CrewIntros:1971 registers SkipOpeningSequence that way) never heard a
single keystroke.
"""
import App
import pytest

from engine import host_io, host_loop
from engine.host_loop import _poll_raw_keyboard
from engine.input_map import InputMap


class _FakeKeys:
    # A deliberately small stand-in for the native `keys` submodule: the
    # letters the real one exports, the fire keys, a crew-talk F-key, and the
    # modifier keys.  GLFW codes for letters/digits are ord().
    KEY_S = ord("S")
    KEY_W = ord("W")
    KEY_F = ord("F")          # owned by _poll_fire_keys
    KEY_X = ord("X")          # owned by _poll_fire_keys
    KEY_G = ord("G")          # owned by _poll_fire_keys
    KEY_F1 = 290              # owned by _poll_function_keys
    KEY_LEFT_ALT = 342
    KEY_RIGHT_ALT = 346
    KEY_LEFT_CONTROL = 341
    KEY_RIGHT_CONTROL = 345
    KEY_LEFT_SHIFT = 340
    KEY_RIGHT_SHIFT = 344


class _FakeHost:
    keys = _FakeKeys()

    def __init__(self):
        self.down = set()

    def key_state(self, key):
        return key in self.down


_SEEN: list = []
_HANDLER = __name__ + "._on_keyboard"


def _on_keyboard(obj, event):
    """Stand-in for E1M1.SkipOpeningSequence — an SDK-style raw ET_KEYBOARD
    instance handler registered on the root window."""
    _SEEN.append((event.GetUnicode(), event.GetKeyState()))


@pytest.fixture
def wired(monkeypatch):
    """Register a raw ET_KEYBOARD handler on the root window + a fake host."""
    import KeyConfig
    KeyConfig.MapScancodes()
    _SEEN.clear()
    # Reach the level cache through the MODULE, never a from-import: several
    # tests importlib.reload(host_loop) (tests/host/test_bc_model_scale.py:28),
    # which rebinds _fn_key_prev to a fresh dict and leaves a from-imported
    # name pointing at the orphan.
    host_loop._fn_key_prev.clear()
    host_loop._raw_key_pairs_host = None
    App.g_kRootWindow.AddPythonFuncHandlerForInstance(App.ET_KEYBOARD, _HANDLER)
    host = _FakeHost()
    monkeypatch.setattr(host_io, "_h", host)
    yield host, _SEEN, InputMap()
    App.g_kRootWindow.RemoveHandlerForInstance(App.ET_KEYBOARD, _HANDLER)
    _SEEN.clear()
    host_loop._fn_key_prev.clear()
    host_loop._raw_key_pairs_host = None


def test_pressing_a_key_delivers_a_raw_et_keyboard_event(wired):
    host, seen, im = wired
    _poll_raw_keyboard(host, im)
    assert seen == []
    host.down.add(_FakeKeys.KEY_S)
    _poll_raw_keyboard(host, im)                 # rising edge
    assert seen == [(App.WC_S, App.TGKeyboardEvent.KS_KEYDOWN)]
    _poll_raw_keyboard(host, im)                 # held: no repeat
    assert len(seen) == 1
    host.down.clear()
    _poll_raw_keyboard(host, im)                 # falling edge
    assert seen[-1] == (App.WC_S, App.TGKeyboardEvent.KS_KEYUP)


def test_keys_owned_by_the_fire_and_crew_pollers_are_not_double_forwarded(wired):
    """_poll_fire_keys / _poll_function_keys already push their keys through
    _emit, which raw-dispatches. Forwarding them here too would deliver the
    same keystroke twice AND fight over the shared _fn_key_prev cache."""
    host, seen, im = wired
    for glfw in (_FakeKeys.KEY_F, _FakeKeys.KEY_X, _FakeKeys.KEY_G,
                 _FakeKeys.KEY_F1):
        host.down = {glfw}
        _poll_raw_keyboard(host, im)
    assert seen == []


def test_ownership_follows_a_remap(wired):
    """The exclusion is computed from the live InputMap, so remapping fire to
    another key moves the exclusion with it."""
    host, seen, im = wired
    im.set("fire_primary", "S")      # fire is now S; F is free
    host.down = {_FakeKeys.KEY_S}
    _poll_raw_keyboard(host, im)
    assert seen == []                # S is owned by _poll_fire_keys now
    host.down = {_FakeKeys.KEY_F}
    _poll_raw_keyboard(host, im)
    assert seen == [(App.WC_F, App.TGKeyboardEvent.KS_KEYDOWN)]


def test_alt_or_ctrl_suppresses_the_base_key(wired):
    """Same discipline as the other pollers: while ALT/CTRL is held the chord
    poller owns the key, so the base key must read as UP."""
    host, seen, im = wired
    host.down = {_FakeKeys.KEY_S, _FakeKeys.KEY_LEFT_ALT}
    _poll_raw_keyboard(host, im)
    assert seen == []
    host.down = {_FakeKeys.KEY_S, _FakeKeys.KEY_LEFT_CONTROL}
    _poll_raw_keyboard(host, im)
    assert seen == []


def test_shift_also_suppresses_the_base_key(wired):
    """Unlike _poll_fire_keys / _poll_crew_talk_keys (which map a physical
    key to a fixed WC slot and intentionally still fire under Shift), the raw
    poller's job is to report WHICH CHARACTER the SDK should see -- and under
    Shift that is a different WC code (WC_CAPS_S, not WC_S). The chord poller
    already owns shifted presses and emits the correct code via OnChordDown;
    if the raw poller also emitted the bare WC_S here, E1M1's skip prompt
    would fire on Shift+S -- BC's own WC_CAPS_S is a distinct code with its
    own ("S") label, so BC does not skip on Shift+S."""
    host, seen, im = wired
    host.down = {_FakeKeys.KEY_S, _FakeKeys.KEY_LEFT_SHIFT}
    _poll_raw_keyboard(host, im)
    assert seen == []
    host.down = {_FakeKeys.KEY_S, _FakeKeys.KEY_RIGHT_SHIFT}
    _poll_raw_keyboard(host, im)
    assert seen == []


def test_raw_forwarding_does_not_drive_the_sdk_turn_handlers(wired, monkeypatch):
    """VERIFICATION POINT: BC binds WC_S -> ET_INPUT_TURN_DOWN
    (DefaultKeyboardBinding.py:84) and TacticalInterfaceHandlers.Initialize
    registers TurnDown for it on the TCW (line 72), where TurnShip calls
    MissionLib.SetPlayerAI("Captain", None) -> pPlayer.ClearAI().  Our flight
    controls are driven host-side from host_io.key_state (input_map: S ->
    pitch_up), so letting the binding layer fire too would clear the player's
    AI and double-drive pitch.  The raw poller must deliver ONLY the raw
    ET_KEYBOARD window event.
    """
    import DefaultKeyboardBinding
    DefaultKeyboardBinding.Initialize()
    tcw = App.TacticalControlWindow_GetTacticalControlWindow()
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)
    import TacticalInterfaceHandlers as TIH
    TIH.Initialize(tcw)
    turns = []
    monkeypatch.setattr(TIH, "TurnDown",
                        lambda obj, ev: turns.append(ev.GetBool()))
    host, seen, im = wired
    host.down.add(_FakeKeys.KEY_S)
    _poll_raw_keyboard(host, im)
    assert seen == [(App.WC_S, App.TGKeyboardEvent.KS_KEYDOWN)]
    assert turns == [], "raw forwarding leaked into the SDK turn binding"


def test_absent_host_is_a_noop():
    im = InputMap()
    _poll_raw_keyboard(None, im)          # must not raise

    class _NoKeys:
        pass

    _poll_raw_keyboard(_NoKeys(), im)     # must not raise
