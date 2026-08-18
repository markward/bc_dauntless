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
# The CTRL_/ALT_/CAPS_ modifier families are modifier BANDS OR'd onto the
# base code (base codes stay below 0x200, so the bands never collide with
# them or each other).  KeyConfig.MapScancodes registers WC_CAPS_<letter>
# with modifier=KY_SHIFT — CAPS_X means the *capital character* (Shift+X),
# NOT CapsLock state.  App.py's module __getattr__ WC_/KY_ fallback
# surfaces every name defined here.

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

# Modifier-chord families — see comment above.  MODIFIER_CHORDS feeds the
# host-loop chord poller: (modifier_name, base_name, chord_code).
MODIFIER_BANDS = {"ALT": 0x200, "CTRL": 0x400, "CAPS": 0x800}
MODIFIER_CHORDS: list = []
_MOD_BASE_NAMES = (
    [chr(_c) for _c in range(ord("A"), ord("Z") + 1)]
    + [chr(_c) for _c in range(ord("0"), ord("9") + 1)]
    + ["F%d" % _n for _n in range(1, 13)]
)
for _mod, _band in MODIFIER_BANDS.items():
    for _base in _MOD_BASE_NAMES:
        _code = _band | globals()["WC_" + _base]
        _def_key("%s_%s" % (_mod, _base), _code)
        MODIFIER_CHORDS.append((_mod, _base, _code))

KS_KEYDOWN   = TGKeyboardEvent.KS_KEYDOWN
KS_KEYUP     = TGKeyboardEvent.KS_KEYUP
KS_KEYREPEAT = TGKeyboardEvent.KS_KEYREPEAT
KS_NORMAL    = TGKeyboardEvent.KS_NORMAL


def _window_takes_raw_input(window) -> bool:
    """False only for a focused window that explicitly reports IsInteractive()
    == 0 — BC's "this window is not taking user input" state.

    Actions/CameraScriptActions.StartCinematicMode's bInteractive DEFAULTS TO 0
    (:392) and applies it via SetInteractive (:405); that runs on EVERY player
    warp (WarpSequence.py:73), plus MissionLib:1950, E3M4:1525/1904, E8M2:6530,
    HelmMenuHandlers:876, MP Mission5:1045. StopCinematicMode sets it back to 1
    (:422).

    In BC, HandleKeyboard's non-interactive branch (CinematicInterfaceHandlers
    .py:99-108) still RECEIVES the key and bubbles it on with CallNextHandler
    (its Skip-Events escape hatch aside). We dispatch to exactly one object and
    implement no bubbling, so without this gate a non-interactive cinematic
    window would win the destination for every key and then drop it — killing
    E1M1.SkipOpeningSequence, BridgeUtils.ModalKeyboardHandler and
    E3M1.FilteredKeyboardHandler for the whole of every warp. Declining the
    destination leaves the raw stream exactly where it went before focus-aware
    routing existed, which is the faithful single-destination equivalent.

    THE `isinstance(..., int)` TEST IS LOAD-BEARING, NOT DEFENSIVE PADDING.
    Most main windows have no IsInteractive at all; on the TGObject-derived
    ones the name vends a truthy _Stub whose int() is 0, so coercing the answer
    would silently classify EVERY such window as non-interactive and delete the
    focus prepend outright. Only a real int 0 closes the gate — see CLAUDE.md's
    numeric-coercion table for the bug class.
    """
    probe = getattr(window, "IsInteractive", None)
    if not callable(probe):
        return True
    value = probe()
    return not (isinstance(value, int) and value == 0)


def _raw_keyboard_destination():
    """First object in BC's window chain with an ET_KEYBOARD instance handler.

    BC bubbles a raw keyboard event up the window chain; our ProcessEvent
    dispatches on exactly one object, so we pick the first candidate that
    actually registered a handler.

    A focused MAIN window goes first (see the comment on the prepend below);
    that half IS established fidelity — BC routes input to the focused window.

    THE REST OF THE ORDER (root window before TopWindow) IS OUR CHOICE, NOT
    ESTABLISHED FIDELITY. It is chosen because that is where mission scripts hook
    (E1M1.CrewIntros:1971). The evidence actually points the other way: BC's
    modal handlers (BridgeUtils.ModalKeyboardHandler,
    E3M1.FilteredKeyboardHandler) exist to SetHandled() a key before it becomes
    an ET_INPUT_* action, which needs a real bubbling chain with veto. Handlers
    SDK scripts register on panes/buttons/movie panes (E1M2.py:4243-4247/5199,
    E8M2.py:6495, MainMenu, Multiplayer) are unreachable here. See
    docs/engine/e1m1-skip-intro.md § "Still open".

    Returns None when nothing registered, which is the common case; callers
    must treat that as "post nothing".
    """
    import App  # deferred: input is imported during App bootstrap
    et = App.ET_KEYBOARD
    if not isinstance(et, int):
        # Defensive: a regressed export would make every registration a fresh
        # unreachable key. Post nothing rather than pretend to dispatch.
        return None
    candidates = []
    top = App.TopWindow_GetTopWindow()
    # BC delivers the raw keystroke to the FOCUSED window first, and that is
    # the seam the cinematic camera keys live on: CinematicInterfaceHandlers
    # .HandleKeyboard is the cinematic window's ET_KEYBOARD handler, and its
    # g_dKeyToEventMapping table (:154-159) — read at :114 and nowhere else —
    # is the ONLY thing that maps WC_F1..F6 to the camera modes. Left to the
    # global binding those keys mean ET_INPUT_TALK_TO_* (bridge crew menus).
    # Only a focused MAIN window counts, exactly as in
    # KeyboardBinding._resolve_destination: QuickBattle's OpenConfigDialog
    # focuses config panes, which must not capture the raw stream. A focused
    # window that registered no ET_KEYBOARD handler falls through to the scan
    # below unchanged, so the root-window-before-TopWindow ordering below is
    # preserved for everything else (E1M1's skip-intro handler included).
    # getattr-guarded throughout: tests monkeypatch TopWindow_GetTopWindow
    # with doubles that have neither GetFocus nor _main_windows.
    if top is not None:
        get_focus = getattr(top, "GetFocus", None)
        focus = get_focus() if callable(get_focus) else None
        if focus is not None:
            mains = getattr(top, "_main_windows", None)
            if (isinstance(mains, dict)
                    and any(w is focus for w in mains.values())
                    and _window_takes_raw_input(focus)):
                candidates.append(focus)
    root = getattr(App, "g_kRootWindow", None)
    if root is not None:
        candidates.append(root)
    if top is not None:
        # _TopWindow keeps its handler chain by COMPOSITION on `_events`
        # rather than inheriting one; route through it so both the probe
        # below and AddEvent's destination check land on the same object.
        # (Same reasoning as KeyboardBinding._resolve_destination.)
        events_obj = getattr(top, "_events", None)
        candidates.append(events_obj if events_obj is not None else top)
    for cand in candidates:
        handlers = getattr(cand, "_handlers", None)
        if isinstance(handlers, dict) and handlers.get(et):
            return cand
    return None


class TGInputManager(TGObject):
    """Receives host-side key/button events and emits TGKeyboardEvents
    into the event manager.  Registration table is populated by mission
    scripts (e.g. DefaultKeyboardBinding.RegisterUnicodeKeys)."""

    def __init__(self, event_manager: TGEventManager):
        super().__init__()
        self._event_manager = event_manager
        # {WC_code: (KY_code, database_ref, name)}
        self._registered: dict[int, tuple[int, object, str]] = {}
        # Every registered WC code, bare or modifier-variant — the _emit
        # gate.  The dict keys mix ints and (wc, modifier) tuples, so a
        # bare `wc in self._registered` misses chord codes.
        self._registered_codes: set[int] = set()

    def RegisterUnicodeKey(self, wc_code, ky_code, database, name,
                            modifier=None) -> None:
        """Register a unicode-key entry.  Accepts optional 5th arg `modifier`
        — KeyConfig.py uses it to register modifier-augmented variants
        (App.KY_ALTGR/KY_CTRL/KY_ALT) alongside the base key.  Bare keys
        register under the plain int `wc_code`; modifier variants register
        under a (wc_code, modifier) tuple key so they don't shadow the base.
        Both paths feed `_registered_codes` (the set `_emit` gates on), so
        chord keys are just as live as bare keys — this is load-bearing for
        the ALT/CTRL/CAPS modifier-chord families (see MODIFIER_CHORDS
        above), not a bare-key-only path.
        """
        self._registered_codes.add(int(wc_code))
        if modifier is None:
            self._registered[int(wc_code)] = (int(ky_code), database, str(name))
        else:
            # Keep modifier-augmented entries separate; the base unicode key
            # stays addressable via OnKeyDown(WC_*).
            self._registered[(int(wc_code), int(modifier))] = (
                int(ky_code), database, str(name))

    def GetDisplayStringFromUnicode(self, wc_code):
        """Printable label for a key — BC's help-text primitive.

        RegisterUnicodeKey already carries both halves: the 4th argument is
        the label ("s", "ESC", "F1") and the 3rd is the TGL database to
        localize it through. UKConfig.py:14 documents the fallback — with no
        database, the label itself is the answer.

        Modifier-augmented entries (KeyConfig.py registers WC_CAPS_S with
        modifier=KY_SHIFT and label "S") are stored under a (wc_code,
        modifier) TUPLE key so they don't shadow the bare key — see
        RegisterUnicodeKey. A bare-int-only lookup here left every such
        entry permanently blank (WC_CAPS_S -> ""), which is what let
        Shift+S's wrong-but-truthy comparison through in E1M1's skip
        handler. WC_CAPS_S (0x853) and WC_S (0x53) are distinct codes, so
        finding the tuple entry whose [0] == wc_code is unambiguous.

        Returns _TGString so callers can chain .GetCString(), which is how
        every SDK call site consumes it (E1M1.SkipOpeningSequence:1764,
        E1M1's tactical help text:3324-3339).
        """
        from engine.appc.localization import _TGString
        wc_code = int(wc_code)
        entry = self._registered.get(wc_code)
        if entry is None:
            for key, candidate in self._registered.items():
                if isinstance(key, tuple) and key[0] == wc_code:
                    entry = candidate
                    break
        if entry is None:
            # Unregistered key: an empty label, NOT a stub. A truthy stub here
            # would make every "is this the skip key?" comparison ambiguous.
            return _TGString("")
        _ky, database, name = entry
        if database is None:
            return _TGString(name)
        return _TGString(str(database.GetString(name)))

    def OnKeyDown(self, wc_code: int) -> None:
        self._emit(int(wc_code), KS_KEYDOWN)

    def OnKeyUp(self, wc_code: int) -> None:
        self._emit(int(wc_code), KS_KEYUP)

    def OnRawKeyDown(self, wc_code: int) -> None:
        self._emit_raw(int(wc_code), KS_KEYDOWN)

    def OnRawKeyUp(self, wc_code: int) -> None:
        self._emit_raw(int(wc_code), KS_KEYUP)

    def OnChordDown(self, wc_code: int) -> None:
        """Modifier-chord press.  BC's input manager produces a character
        event (KS_NORMAL) alongside the keydown; the SDK binds each chord
        under exactly one state (KS_KEYDOWN for CTRL_D/T/I and the CAPS
        debug keys, KS_NORMAL for the ALT/CTRL number chords), so exactly
        one binding fires per press."""
        self._emit(int(wc_code), KS_KEYDOWN)
        self._emit(int(wc_code), KS_NORMAL)

    def _emit(self, wc_code: int, key_state: int) -> None:
        """Both halves of BC's keystroke delivery, in BC's ORDER.

        BC runs the focused window's raw ET_KEYBOARD handler FIRST and reaches
        the global keyboard binding only from inside it, gated on the handled
        flag: CinematicInterfaceHandlers.HandleKeyboard translates the key
        through the window's OWN table at :114 (TriggerKeyboardEvents, which
        calls pEvent.SetHandled() on a table hit — InterfaceHandlers.py:58) and
        only then, `if (pEvent.EventHandled() == 0)` (:117), calls
        g_kKeyboardBinding.LaunchEvent.

        We keep the binding on its own ET_KEYBOARD_EVENT broadcast rather than
        calling LaunchEvent inline, so the faithful equivalent is: dispatch raw
        first, broadcast only if the raw event came back unhandled. Emitting
        the broadcast first and unconditionally (the old order) made every key
        mean TWO things at once — F3 in cinematic mode ran the target-camera
        handler AND opened the XO crew menu.

        The veto bites ONLY on a genuine consume. No window handler registered,
        or a handler that looked and passed, leaves EventHandled() == 0 and the
        broadcast runs exactly as before — which is what keeps the bridge crew
        menus (F1-F5 -> ET_INPUT_TALK_TO_*) working outside cinematic mode.
        """
        if wc_code not in self._registered_codes:
            return
        if self._dispatch_raw_keyboard(wc_code, key_state):
            return
        evt = TGKeyboardEvent()
        evt.SetUnicodeKey(wc_code)
        evt.SetKeyState(key_state)
        self._event_manager.AddEvent(evt)

    def _emit_raw(self, wc_code: int, key_state: int) -> None:
        """Raw-ONLY delivery: BC's ET_KEYBOARD window event, with no
        ET_KEYBOARD_EVENT broadcast and therefore no KeyboardBinding →
        ET_INPUT_* translation.

        WHY THE HALF: dauntless drives flight, camera and throttle host-side
        off host_io.key_state (engine/input_map.py), NOT off the SDK binding
        table.  BC binds most of those same keys to ET_INPUT_* actions
        (DefaultKeyboardBinding.py:80-95 maps W/S/A/D/Q/E to
        ET_INPUT_TURN_*/ROLL_*), and TacticalInterfaceHandlers.Initialize
        registers TurnUp/TurnDown/... on the TCW for them (line 68-73).  Those
        handlers call TurnShip, which does
        MissionLib.SetPlayerAI("Captain", None) → pPlayer.ClearAI() before
        setting an angular velocity — so routing the general key stream
        through the binding layer would clear the player's AI mid-cutscene and
        add a second, fighting rotation driver.  Until flight control itself
        moves onto the SDK binding path, the general poller delivers only the
        raw window event, which is the half no other consumer duplicates.

        The four special-cased host pollers (mouse buttons, crew-talk F-keys,
        fire keys, ALT/CTRL/CAPS chords) keep using _emit and therefore keep
        BOTH halves; their ET_INPUT_* consumers are live and wanted.
        """
        if wc_code not in self._registered_codes:
            return
        self._dispatch_raw_keyboard(wc_code, key_state)

    def _dispatch_raw_keyboard(self, wc_code: int, key_state: int) -> bool:
        """Post BC's raw ET_KEYBOARD event to the window chain.

        Returns True only if a handler CONSUMED the key (called SetHandled on
        it — InterfaceHandlers.TriggerKeyboardEvents:58, BridgeUtils
        .ModalKeyboardHandler, E3M1.FilteredKeyboardHandler). `_emit` uses that
        as BC's veto over the binding translation. "No destination" is NOT
        "handled": with nothing registered for ET_KEYBOARD — the common case —
        this returns False and the binding runs untouched.

        Ahead of the ET_KEYBOARD_EVENT broadcast, not a replacement for it:
        KeyboardBinding still translates unconsumed bound keys into ET_INPUT_*
        events. Gated by _registered_codes via the caller, so unmapped keys
        stay silent. All three key states are posted — BC delivers down, up and
        character events to windows, which is why
        CinematicInterfaceHandlers.HandleKeyboard inspects GetKeyState().

        A fresh event per keystroke, so the handled flag cannot leak from one
        press to the next.
        """
        dest = _raw_keyboard_destination()
        if dest is None:
            return False
        import App
        raw = TGKeyboardEvent()
        raw.SetUnicodeKey(wc_code)
        raw.SetKeyState(key_state)
        raw.SetEventType(App.ET_KEYBOARD)
        raw.SetDestination(dest)
        self._event_manager.AddEvent(raw)
        return raw.EventHandled() != 0


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

    def event_type_for(self, evt: TGKeyboardEvent):
        """Resolve the bound event type for a keyboard event, or None if the
        (key, state) pair isn't bound. Lets the dispatch trampoline decide
        per-event whether to honour a keyboard-input lockout (SHIP/tactical
        keys) or pass through regardless (bridge crew-menu keys)."""
        binding = self._bindings.get((evt.GetUnicodeKey(), evt.GetKeyState()))
        return binding[0] if binding is not None else None

    def OnKeyboardEvent(self, _obj, evt: TGKeyboardEvent) -> None:
        key = (evt.GetUnicodeKey(), evt.GetKeyState())
        binding = self._bindings.get(key)
        if binding is None:
            return
        event_type, flags, value = binding
        out = self._build_event(event_type, flags, value)
        dest = self._resolve_destination(event_type)
        if dest is not None:
            out.SetDestination(dest)
        self._event_manager.AddEvent(out)

    def _resolve_destination(self, event_type: int):
        """BC bubbles keyboard-bound events up the window chain; our
        ProcessEvent dispatches on one object only.  Scan the known
        keyboard consumers — default destination (TCW), its tactical
        menu, TopWindow — for the first that actually registered an
        instance handler for this event type.  Fall back to the default
        destination (today's behaviour) when none did."""
        from engine.core import ids
        candidates = []
        # BC routes keyboard input to the focused window first. Only a focused
        # MAIN window counts: QuickBattle's OpenConfigDialog focuses config
        # panes, which must not start capturing keyboard events. An event type
        # the focused window did not register falls through to the scan below
        # unchanged — that is what keeps the bridge crew menus on F1-F5.
        import App as _App
        _top = _App.TopWindow_GetTopWindow()
        _focus = _top.GetFocus() if _top is not None else None
        if _focus is not None:
            _mains = getattr(_top, "_main_windows", None)
            if isinstance(_mains, dict) and any(w is _focus for w in _mains.values()):
                candidates.append(_focus)
        tcw = self._default_destination
        if tcw is not None:
            candidates.append(tcw)
            if ids.implements(tcw, "GetTacticalMenu"):
                menu = tcw.GetTacticalMenu()
                if menu is not None:
                    candidates.append(menu)
        import App  # deferred: input is imported during App bootstrap
        top = App.TopWindow_GetTopWindow()
        if top is not None:
            # The real _TopWindow (engine/appc/top_window.py) stores its
            # instance-handler chain by COMPOSITION on `_events` (a real
            # TGEventHandlerObject) rather than inheriting one directly, so
            # `top` itself has no `_handlers` dict and isinstance-fails
            # TGEventManager.AddEvent's destination check. Route through
            # `_events` when present so both the handler-probe below and the
            # eventual AddEvent dispatch land on an object that actually
            # carries the registered handlers. Tests that monkeypatch
            # TopWindow_GetTopWindow with a plain TGEventHandlerObject (no
            # `_events` attribute) fall back to using it directly.
            events_obj = getattr(top, "_events", None)
            candidates.append(events_obj if events_obj is not None else top)
        for cand in candidates:
            handlers = getattr(cand, "_handlers", None)
            if isinstance(handlers, dict) and handlers.get(int(event_type)):
                return cand
        return tcw

    def _build_event(self, event_type: int, flags: int, value):
        if flags == self.GET_BOOL_EVENT:
            ev = TGBoolEvent()
            ev.SetBool(value)
        elif flags == self.GET_INT_EVENT:
            # ManagePower/Maneuver read GetInt() for the preset/order index.
            # App._TGIntEvent does NOT subclass engine.appc.events.TGEvent —
            # it's a duck-typed App-shim class (SetEventType/GetEventType
            # only), which is why this method's return type can't be
            # honestly annotated -> TGEvent.
            import App  # deferred — _TGIntEvent lives in the App shim
            ev = App.TGIntEvent_Create()
            ev.SetInt(int(value))
        else:
            # GET_EVENT (the default flags value) and GET_FLOAT_EVENT both
            # fall through here: GET_EVENT has no payload to carry, and
            # GET_FLOAT_EVENT has no polled consumer yet (the impulse number
            # row isn't polled) — add a float-carrying event with its first
            # real consumer.
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


_bridge_menu_event_types = None


def _bridge_menu_events():
    """The bridge crew-menu ('talk to officer') event types — F1-F5. Built
    lazily so App need not be imported at module load."""
    global _bridge_menu_event_types
    if _bridge_menu_event_types is None:
        import App
        _bridge_menu_event_types = frozenset(
            t for t in (
                getattr(App, "ET_INPUT_TALK_TO_HELM", None),
                getattr(App, "ET_INPUT_TALK_TO_TACTICAL", None),
                getattr(App, "ET_INPUT_TALK_TO_XO", None),
                getattr(App, "ET_INPUT_TALK_TO_SCIENCE", None),
                getattr(App, "ET_INPUT_TALK_TO_ENGINEERING", None),
            ) if isinstance(t, int))
    return _bridge_menu_event_types


def _OnKeyboardEvent_Dispatch(obj, evt):
    """Trampoline so AddBroadcastPythonFuncHandler can resolve a qualified
    name and reach the singleton's bound method.

    Consults engine.appc.top_window.keyboard_input_enabled() so SDK code that
    calls TopWindow.AllowKeyboardInput(0) actually suppresses keyboard events
    instead of being a silent no-op.

    EXCEPTION — the bridge crew-menu keys (F1-F5 -> ET_INPUT_TALK_TO_*) are
    bridge UI, not ship control, and must still work while ship control is
    removed: E1M1's character-selection tutorial runs the whole beat with
    RemoveControl (AllowKeyboardInput(0)) in effect, and the player opens each
    officer's menu with F1-F5. BC's RemoveControl disables helm/tactical keys,
    not the bridge menus. So a keyboard lockout drops everything EXCEPT the
    crew-menu keys."""
    # Local import — top_window depends on nothing in input, and input is
    # imported by App.py before top_window is registered; the symbol is
    # module-level so the lookup is one attribute read per event (cheap).
    from engine.appc.top_window import keyboard_input_enabled
    if g_kKeyboardBinding is None:
        return
    if not keyboard_input_enabled():
        et = g_kKeyboardBinding.event_type_for(evt)
        if et not in _bridge_menu_events():
            return
    g_kKeyboardBinding.OnKeyboardEvent(obj, evt)
