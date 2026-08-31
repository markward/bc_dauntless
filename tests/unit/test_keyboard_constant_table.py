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

q13 sweep Task 7: WC_ and KY_ are BC's real values, and are TWO DISTINCT
NAMESPACES, not aliases of each other.  BC's WC_ are character codes
(lowercase ASCII for letters, e.g. WC_F == 102), while BC's KY_ are a small,
unrelated key-index enum (KY_F == 33).  Before this task both were Windows VK
codes and therefore identical (App.KY_F == App.WC_F == 70) -- that
conflation is now closed; see test_ky_is_a_separate_namespace_from_wc below.
"""
import App
import engine.appc.input as appc_input
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
    # BC's WC_ letters are LOWERCASE ASCII (character codes), not Windows VK.
    assert App.WC_A == ord("a") and App.WC_Z == ord("z")
    assert App.WC_0 == ord("0") and App.WC_9 == ord("9")
    # BC's KY_ is a small, unrelated key-index enum -- NOT an alias of WC_.
    assert App.KY_A == 30 and App.KY_Z == 44
    assert App.KY_A != App.WC_A


def test_dead_key_class_closed():
    """Every base key the SDK references is a nonzero int in each namespace,
    and every WC_ value is distinct (KY_ is not: BC's own measured table has
    one legitimate duplicate, KY_SEPARATOR == KY_EU_RIGHT == 43 -- harmless,
    since RegisterUnicodeKey's ky_code is stored but never compared)."""
    wc_values = []
    for name in _BASE_NAMES:
        wc = getattr(App, "WC_" + name)
        ky = getattr(App, "KY_" + name)
        assert type(wc) is int and wc != 0, "WC_" + name
        assert type(ky) is int and ky != 0, "KY_" + name
        wc_values.append(wc)
    # No two base keys share a WC_ code → none collapse onto a shared slot.
    assert len(set(wc_values)) == len(wc_values), "duplicate WC_ codes: %r" % (
        sorted(v for v in set(wc_values) if wc_values.count(v) > 1),)


def test_widgets_overlap_values_match():
    """BACKSPACE/TAB/RETURN/SPACE equal their tg_ui.widgets Unicode values."""
    assert App.WC_BACKSPACE == 8
    assert App.WC_TAB == 9
    assert App.WC_RETURN == 13
    assert App.WC_SPACE == 32


def test_modifier_variants_are_real_codes():
    """CTRL_/ALT_/CAPS_ variants are BC's own measured values, not a
    band|base formula -- see test_wc_modifier_constants.py for the full
    collision-free/no-duplicate proof of the mechanism that produces them."""
    assert App.WC_CTRL_Q == 57457
    assert App.WC_ALT_1 == 57419
    assert App.WC_CAPS_K == 75  # BC's Shift+K character code (uppercase 'K')


def test_wc_are_character_codes_not_vk_codes():
    """BC's WC_ are LOWERCASE ASCII; ours were Windows VK codes.

    Reads engine.appc.input directly, not App -- App's module __getattr__
    would resolve/memoize the same value, but a test that wants to catch a
    regression AT THE DEFINITION SITE must not go through that path."""
    assert appc_input.WC_F == 102 and appc_input.WC_G == 103 and appc_input.WC_X == 120


def test_wc_function_keys_live_in_bcs_high_band():
    assert appc_input.WC_F1 == 57365 and appc_input.WC_F6 == 57370
    assert appc_input.WC_F9 == 57373
    assert appc_input.WC_CURSOR == 57496


def test_ky_is_a_separate_namespace_from_wc():
    """KY_ is a small key-index enum, NOT an alias of WC_."""
    assert appc_input.KY_F == 33 and appc_input.KY_F1 == 59 and appc_input.KY_X == 45
    assert appc_input.KY_LBUTTON == 241 and appc_input.KY_RBUTTON == 242
    assert appc_input.KY_F != appc_input.WC_F, "the two namespaces must not be conflated"


def test_kbt_constants_are_a_bitmask():
    """BC's KBT_ are flag bits; ours were sequential 0-3, so every & test
    against them was meaningless."""
    kb = App.KeyboardBinding
    assert (kb.KBT_MANY_TO_MANY, kb.KBT_SINGLE_EVENT_TO_KEY,
            kb.KBT_SINGLE_KEY_TO_EVENT, kb.KBT_LOCKOUT_CHANGE) == (1, 2, 4, 8)
    assert kb.KBT_MANY_TO_MANY | kb.KBT_LOCKOUT_CHANGE == 9


def test_key_state_constants_are_the_measured_values():
    ke = App.TGKeyboardEvent
    assert (ke.KS_NORMAL, ke.KS_KEYDOWN, ke.KS_KEYUP) == (0, 1, 2)


def test_get_event_flags_are_the_measured_values():
    """GET_BOOL_EVENT/GET_INT_EVENT were swapped in our invented numbering."""
    kb = App.KeyboardBinding
    assert (kb.GET_EVENT, kb.GET_BOOL_EVENT,
            kb.GET_INT_EVENT, kb.GET_FLOAT_EVENT) == (0, 2, 1, 3)


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
