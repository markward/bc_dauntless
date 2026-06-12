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


# ── Constants — mirror SDK App.py keyboard constants ────────────────────────
WC_LBUTTON: int = 0x01
WC_RBUTTON: int = 0x02
WC_MBUTTON: int = 0x04
KY_LBUTTON: int = 0x01
KY_RBUTTON: int = 0x02
KY_MBUTTON: int = 0x04
# Function keys — Windows VK_F1..F5 values (KeyConfig.MapScancodes
# registers them; DefaultKeyboardBinding.py:121-125 binds them to
# ET_INPUT_TALK_TO_*). KY_ mirrors WC_ like the mouse buttons above.
WC_F1: int = 0x70
WC_F2: int = 0x71
WC_F3: int = 0x72
WC_F4: int = 0x73
WC_F5: int = 0x74
KY_F1: int = 0x70
KY_F2: int = 0x71
KY_F3: int = 0x72
KY_F4: int = 0x73
KY_F5: int = 0x74
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
