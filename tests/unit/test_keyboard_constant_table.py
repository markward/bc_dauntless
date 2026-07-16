"""The base-key WC_/KY_ constant table closes the dead-key class.

KeyConfig.MapScancodes registers every key under App.WC_<name> and
DefaultKeyboardBinding binds (WC_code, keystate) → ET_*.  Any name the shim
fails to define resolves to App._NamedStub (int()==0), so every undefined key
collapses onto binding slot 0 (last-write-wins) and goes dead — the bug that
once silenced Klingon disruptor fire (WC_G → 0).

engine/appc/input.py now generates a full table of base single keys (letters,
digits, F1-F12, navigation, punctuation, numpad, mouse, scroll-wheel) and
App.py's module __getattr__ surfaces every one as App.WC_*/App.KY_*.  These
tests prove no base key the SDK references collapses to 0, that the values are
all distinct, and that a newly-defined key round-trips OnKeyDown → ET_*.
"""
import App
from engine.appc.windows import TacticalControlWindow

import string

# Every base WC_/KY_ name KeyConfig.MapScancodes references (no CTRL_/ALT_/CAPS_
# modifier variants — those stay stubs until a consumer is wired).
_BASE_NAMES = (
    list(string.ascii_uppercase)                       # A-Z
    + [str(d) for d in range(10)]                       # 0-9
    + ["F%d" % i for i in range(1, 13)]                 # F1-F12
    + ["NUMPAD%d" % i for i in range(10)]               # NUMPAD0-9
    + [
        # navigation / editing
        "ESCAPE", "SPACE", "TAB", "RETURN", "BACKSPACE", "INSERT", "DELETE",
        "HOME", "END", "PAGEUP", "PAGEDOWN", "LEFT", "UP", "RIGHT", "DOWN",
        # modifiers / locks
        "SHIFT", "CTRL", "ALT", "CAPSLOCK", "NUMLOCK", "SCROLL", "PAUSE",
        "PRINTSCREEN", "ALTGR",
        # punctuation
        "MINUS", "EQUALS", "BACKQUOTE", "OPEN_BRACKET", "CLOSE_BRACKET",
        "BACKSLASH", "SEMICOLON", "QUOTE", "COMMA", "PERIOD", "SLASH",
        # numpad operators
        "MULTIPLY", "ADD", "SEPARATOR", "SUBTRACT", "DECIMAL", "DIVIDE",
        "NUMPADENTER",
        # shifted symbols
        "TILDE", "EXCLAMATION", "AT_SIGN", "NUMBER_SIGN", "DOLLAR_SIGN",
        "PERCENT", "CARRET", "AMPERSAND", "ASTERISK", "OPEN_PAREN",
        "CLOSE_PAREN", "UNDERSCORE", "PLUS", "CURLY_BRACE_OPEN",
        "CURLY_BRACE_CLOSE", "COLON", "DOUBLE_QUOTE", "LESS_THAN",
        "GREATER_THAN", "QUESTION",
        # mouse / scroll wheel
        "LBUTTON", "RBUTTON", "MBUTTON", "SCROLL_WHEEL_UP", "SCROLL_WHEEL_DOWN",
    ]
)


def test_alphanumerics_real_distinct():
    wc = [getattr(App, "WC_" + c) for c in string.ascii_uppercase]
    wc += [getattr(App, "WC_" + str(d)) for d in range(10)]
    ky = [getattr(App, "KY_" + c) for c in string.ascii_uppercase]
    ky += [getattr(App, "KY_" + str(d)) for d in range(10)]
    assert all(type(v) is int and v != 0 for v in wc + ky)
    assert len(set(wc)) == 36 and len(set(ky)) == 36
    # Letters/digits use Windows VK == ASCII upper/digit.
    assert App.WC_A == 0x41 and App.WC_Z == 0x5A
    assert App.WC_0 == 0x30 and App.WC_9 == 0x39


def test_dead_key_class_closed():
    """Every base key the SDK references is a nonzero int with a distinct value."""
    values = []
    for name in _BASE_NAMES:
        wc = getattr(App, "WC_" + name)
        ky = getattr(App, "KY_" + name)
        assert type(wc) is int and wc != 0, "WC_" + name
        assert type(ky) is int and ky != 0, "KY_" + name
        assert wc == ky, name  # KY_ mirrors WC_
        values.append(wc)
    # No two base keys share a code → none collapse onto a shared slot.
    assert len(set(values)) == len(values), "duplicate WC_ codes: %r" % (
        sorted(v for v in set(values) if values.count(v) > 1),)


def test_widgets_overlap_values_match():
    """BACKSPACE/TAB/RETURN/SPACE equal their tg_ui.widgets Unicode values."""
    assert App.WC_BACKSPACE == 8
    assert App.WC_TAB == 9
    assert App.WC_RETURN == 13
    assert App.WC_SPACE == 32


def test_modifier_variants_are_real_codes():
    """CTRL_/ALT_/CAPS_ variants are modifier bands OR'd onto the base code."""
    assert int(App.WC_CTRL_Q) == 0x400 | int(App.WC_Q)
    assert int(App.WC_ALT_1) == 0x200 | int(App.WC_1)
    assert int(App.WC_CAPS_K) == 0x800 | int(App.WC_K)


# ── Round-trip: a newly-defined letter key reaches the TCW as an ET_* event ──

_received = []


def _record(dest, event):
    _received.append(event.GetEventType())


def setup_function(_):
    from engine.appc.input import register_input_handlers
    register_input_handlers(App.g_kEventManager)


def teardown_function(_):
    TacticalControlWindow._instance = None
    _received.clear()


def test_letter_key_round_trips_to_et():
    """WC_T survives registration → binding → dispatch as ET_INPUT_TARGET_NEXT."""
    _received.clear()
    TacticalControlWindow._instance = None
    tcw = TacticalControlWindow.GetInstance()
    App.g_kKeyboardBinding.SetDefaultDestination(tcw)
    tcw.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_TARGET_NEXT, __name__ + "._record")

    import KeyConfig
    KeyConfig.MapScancodes()
    import DefaultKeyboardBinding
    DefaultKeyboardBinding.Initialize()

    App.g_kInputManager.OnKeyDown(App.WC_T)
    assert App.ET_INPUT_TARGET_NEXT in _received
