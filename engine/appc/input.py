"""SDK-faithful input pipeline shim.

Lays the g_kInputManager → TGKeyboardEvent → g_kKeyboardBinding → ET_*
chain that BC's input system uses.  Mission scripts that call
g_kKeyboardBinding.BindKey(...) (e.g. DefaultKeyboardBinding.py) work
unmodified once these classes are alive.
"""
from engine.core.ids import TGObject
from engine.appc.events import (
    TGBoolEvent, TGEvent, TGEventManager, TGKeyboardEvent, ET_KEYBOARD_EVENT,
)


# ── Keyboard constants — generated WC_/KY_ table ────────────────────────────
# BC's input is name-addressed: KeyConfig.MapScancodes registers each key under
# App.WC_<name>, DefaultKeyboardBinding binds (WC_code, keystate) → ET_*, and
# the host pollers call OnKeyDown(App.WC_<name>).  Any name NOT defined here
# resolves through App.py's module __getattr__ to a _NamedStub whose int() is 0,
# so every undefined key registers/binds under slot 0 (last-write-wins) and goes
# dead — the bug class that once silenced Klingon disruptor fire (WC_G → 0).
#
# This table defines every BASE single key KeyConfig references so none can
# collapse: real Windows VK codes where they exist, else a synthesized 0x100+
# band (value is arbitrary-but-stable — only internal consistency matters, since
# registration, binding, and polling all reference the same App.WC_<name>).
# Distinctness holds by construction: letters 0x41-0x5A, digits 0x30-0x39, the
# VK ranges below (all ≤ 0xFE), and the synth band (≥ 0x100) never overlap.
#
# Intentionally absent: the CTRL_/ALT_/CAPS_ modifier variants (WC_CTRL_Q,
# WC_ALT_1, WC_CAPS_K, …).  They have no wired consumer yet, so they stay stubs
# and get real codes when one lands.  App.py's module __getattr__ has a WC_/KY_
# fallback that surfaces every name defined here as App.WC_*/App.KY_*.

def _def_key(name: str, code: int) -> None:
    globals()["WC_" + name] = code
    globals()["KY_" + name] = code


# Mouse buttons — real VK codes.
_def_key("LBUTTON", 0x01)
_def_key("RBUTTON", 0x02)
_def_key("MBUTTON", 0x04)

# Letters A-Z and digits 0-9 — Windows VK == ASCII uppercase / digit.  This
# covers the weapon-fire letters F/X/G (= 0x46/0x58/0x47) the SDK binds to
# ET_INPUT_FIRE_PRIMARY/SECONDARY/TERTIARY (DefaultKeyboardBinding.py:96-103).
for _vk in list(range(ord("A"), ord("Z") + 1)) + list(range(ord("0"), ord("9") + 1)):
    _def_key(chr(_vk), _vk)

# Function keys F1-F12 — VK_F1 (0x70) .. VK_F12 (0x7B).
for _fn in range(1, 13):
    _def_key("F%d" % _fn, 0x70 + (_fn - 1))

# Numpad digits NUMPAD0-9 — VK_NUMPAD0 (0x60) .. VK_NUMPAD9 (0x69).
for _np in range(10):
    _def_key("NUMPAD%d" % _np, 0x60 + _np)

# Named keys with real Windows VK codes (US layout).
_VK_NAMED = {
    # navigation / editing
    "ESCAPE": 0x1B, "SPACE": 0x20, "TAB": 0x09, "RETURN": 0x0D,
    "BACKSPACE": 0x08, "INSERT": 0x2D, "DELETE": 0x2E,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    # modifiers / locks
    "SHIFT": 0x10, "CTRL": 0x11, "ALT": 0x12,
    "CAPSLOCK": 0x14, "NUMLOCK": 0x90, "SCROLL": 0x91,
    "PAUSE": 0x13, "PRINTSCREEN": 0x2C,
    # OEM punctuation
    "MINUS": 0xBD, "EQUALS": 0xBB, "BACKQUOTE": 0xC0,
    "OPEN_BRACKET": 0xDB, "CLOSE_BRACKET": 0xDD, "BACKSLASH": 0xDC,
    "SEMICOLON": 0xBA, "QUOTE": 0xDE,
    "COMMA": 0xBC, "PERIOD": 0xBE, "SLASH": 0xBF,
    # numpad operators
    "MULTIPLY": 0x6A, "ADD": 0x6B, "SEPARATOR": 0x6C,
    "SUBTRACT": 0x6D, "DECIMAL": 0x6E, "DIVIDE": 0x6F,
}
for _nm, _code in _VK_NAMED.items():
    _def_key(_nm, _code)

# Base keys the SDK binds that have no standalone Windows VK code (shifted
# symbols, numpad-enter, scroll-wheel, AltGr).  Synthesized 0x100+ band.
_SYNTH_NAMED = (
    "TILDE", "EXCLAMATION", "AT_SIGN", "NUMBER_SIGN", "DOLLAR_SIGN", "PERCENT",
    "CARRET", "AMPERSAND", "ASTERISK", "OPEN_PAREN", "CLOSE_PAREN",
    "UNDERSCORE", "PLUS", "CURLY_BRACE_OPEN", "CURLY_BRACE_CLOSE",
    "COLON", "DOUBLE_QUOTE", "LESS_THAN", "GREATER_THAN", "QUESTION",
    "NUMPADENTER", "ALTGR", "SCROLL_WHEEL_UP", "SCROLL_WHEEL_DOWN",
)
for _idx, _nm in enumerate(_SYNTH_NAMED):
    _def_key(_nm, 0x100 + _idx)

KS_KEYDOWN   = TGKeyboardEvent.KS_KEYDOWN
KS_KEYUP     = TGKeyboardEvent.KS_KEYUP
KS_KEYREPEAT = TGKeyboardEvent.KS_KEYREPEAT
KS_NORMAL    = TGKeyboardEvent.KS_NORMAL


class TGInputManager(TGObject):
    """Receives host-side key/button events and emits TGKeyboardEvents
    into the event manager.  Registration table is populated by mission
    scripts (e.g. DefaultKeyboardBinding.RegisterUnicodeKeys)."""

    def __init__(self, event_manager: TGEventManager):
        super().__init__()
        self._event_manager = event_manager
        # {WC_code: (KY_code, database_ref, name)}
        self._registered: dict[int, tuple[int, object, str]] = {}

    def RegisterUnicodeKey(self, wc_code, ky_code, database, name,
                            modifier=None) -> None:
        """Register a unicode-key entry.  Accepts optional 5th arg `modifier`
        — KeyConfig.py uses it to register modifier-augmented variants
        (App.KY_ALTGR/KY_CTRL/KY_ALT) alongside the base key.  PR 2b only
        cares about the bare-key path; modifier variants register under
        a (wc_code, modifier) key so they don't shadow the base.
        """
        if modifier is None:
            self._registered[int(wc_code)] = (int(ky_code), database, str(name))
        else:
            # Keep modifier-augmented entries separate; the base unicode key
            # stays addressable via OnKeyDown(WC_*).
            self._registered[(int(wc_code), int(modifier))] = (
                int(ky_code), database, str(name))

    def OnKeyDown(self, wc_code: int) -> None:
        self._emit(int(wc_code), KS_KEYDOWN)

    def OnKeyUp(self, wc_code: int) -> None:
        self._emit(int(wc_code), KS_KEYUP)

    def _emit(self, wc_code: int, key_state: int) -> None:
        if wc_code not in self._registered:
            return
        evt = TGKeyboardEvent()
        evt.SetUnicodeKey(wc_code)
        evt.SetKeyState(key_state)
        self._event_manager.AddEvent(evt)


class KeyboardBinding(TGObject):
    """Translates (unicode_key, key_state) → (event_type, value) per
    registered bindings.  Posts the resulting event to the event manager
    with destination = the default destination (TacticalControlWindow)."""

    GET_EVENT       = 0
    GET_BOOL_EVENT  = 1
    GET_INT_EVENT   = 2
    GET_FLOAT_EVENT = 3

    # Binding type flags — DefaultKeyboardBinding.Initialize passes
    # KBT_LOCKOUT_CHANGE as a 6th argument to some BindKey calls.
    KBT_MANY_TO_MANY        = 0
    KBT_SINGLE_EVENT_TO_KEY = 1
    KBT_SINGLE_KEY_TO_EVENT = 2
    KBT_LOCKOUT_CHANGE      = 3

    def __init__(self, event_manager: TGEventManager):
        super().__init__()
        self._event_manager = event_manager
        # {(wc_code, key_state): (event_type, flags, value)}
        self._bindings: dict[tuple[int, int], tuple[int, int, object]] = {}
        self._default_destination = None

    def SetDefaultDestination(self, dest) -> None:
        self._default_destination = dest

    def BindKey(self, wc_code, key_state, event_type, flags=GET_EVENT,
                value=None, kbt_type=KBT_MANY_TO_MANY) -> None:
        """Register a (wc_code, key_state) → event_type mapping.

        Accepts 3–6 positional arguments to match the range of call
        signatures in DefaultKeyboardBinding and other SDK scripts:
          BindKey(wc, ks, et)                       — no flags/value
          BindKey(wc, ks, et, flags)                — value defaults to None
          BindKey(wc, ks, et, flags, value)         — standard 5-arg form
          BindKey(wc, ks, et, flags, value, kbt)    — 6-arg form with KBT type
        """
        self._bindings[(int(wc_code), int(key_state))] = (int(event_type), int(flags), value)

    def OnKeyboardEvent(self, _obj, evt: TGKeyboardEvent) -> None:
        key = (evt.GetUnicodeKey(), evt.GetKeyState())
        binding = self._bindings.get(key)
        if binding is None:
            return
        event_type, flags, value = binding
        out = self._build_event(event_type, flags, value)
        if self._default_destination is not None:
            out.SetDestination(self._default_destination)
        self._event_manager.AddEvent(out)

    def _build_event(self, event_type: int, flags: int, value) -> TGEvent:
        if flags == self.GET_BOOL_EVENT:
            ev = TGBoolEvent()
            ev.SetBool(value)
        else:
            # GET_INT_EVENT / GET_FLOAT_EVENT not used by ET_INPUT_FIRE_*;
            # add when a real consumer needs them.
            ev = TGEvent()
        ev.SetEventType(event_type)
        return ev


# ── Module-level singletons ─────────────────────────────────────────────────
g_kInputManager:    TGInputManager   | None = None
g_kKeyboardBinding: KeyboardBinding  | None = None


def init_input_pipeline(event_manager: TGEventManager) -> tuple[TGInputManager, KeyboardBinding]:
    """Initialise the singletons.  Called from App.py at module load."""
    global g_kInputManager, g_kKeyboardBinding
    g_kInputManager   = TGInputManager(event_manager)
    g_kKeyboardBinding = KeyboardBinding(event_manager)
    return g_kInputManager, g_kKeyboardBinding


def register_input_handlers(event_manager: TGEventManager) -> None:
    """Wire KeyboardBinding.OnKeyboardEvent into the broadcast handler list.

    Must run AFTER init_input_pipeline.  AddBroadcastPythonFuncHandler
    resolves a qualified-name string, so we point at a module-level
    trampoline that reaches the singleton's bound method.
    """
    if g_kKeyboardBinding is None:
        return
    event_manager.AddBroadcastPythonFuncHandler(
        ET_KEYBOARD_EVENT,
        g_kKeyboardBinding,
        "engine.appc.input._OnKeyboardEvent_Dispatch",
    )


def _OnKeyboardEvent_Dispatch(obj, evt):
    """Trampoline so AddBroadcastPythonFuncHandler can resolve a qualified
    name and reach the singleton's bound method.

    Consults engine.appc.top_window.keyboard_input_enabled() so SDK code
    that calls TopWindow.AllowKeyboardInput(0) during a cutscene actually
    suppresses keyboard events instead of being a silent no-op."""
    # Local import — top_window depends on nothing in input, and
    # input is imported by App.py before top_window is registered as
    # a TopWindow_GetTopWindow factory; the symbol is module-level so
    # the lookup is one attribute read per event (cheap).
    from engine.appc.top_window import keyboard_input_enabled
    if not keyboard_input_enabled():
        return
    if g_kKeyboardBinding is not None:
        g_kKeyboardBinding.OnKeyboardEvent(obj, evt)
