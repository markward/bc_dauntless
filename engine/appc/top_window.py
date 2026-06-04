"""SDK TopWindow shim.

Replaces the _NamedStub previously returned for App.TopWindow_GetTopWindow.
Owns input-gate flags, cutscene/fade/view state, the SDK UI children
list (for a future CEF mirror), and FindMainWindow lookups.

See docs/superpowers/specs/2026-06-03-top-window-shim-design.md.
"""


# ── Main-window-type enums ────────────────────────────────────
# Real Appc exposes these via SWIG; the integer values are arbitrary
# but must be distinct so dict lookups in _main_windows don't collapse.
MWT_BRIDGE        = 0
MWT_TACTICAL      = 1
MWT_CONSOLE       = 2
MWT_EDITOR        = 3
MWT_OPTIONS       = 4
MWT_SUBTITLE      = 5
MWT_TACTICAL_MAP  = 6
MWT_CINEMATIC     = 7
MWT_MULTIPLAYER   = 8
MWT_CD_CHECK      = 9
MWT_MODAL_DIALOG  = 10


class _TopWindow:
    def __init__(self):
        self._keyboard_input_enabled: bool = True
        self._mouse_input_enabled: bool = True
        self._cutscene_active: bool = False
        self._fade_active: bool = False
        self._bridge_visible: bool = False
        self._tactical_visible: bool = True
        self._edit_mode: bool = False
        self._options_disabled: bool = False
        self._last_rendered_set = None
        self._children: list[tuple[object, float, float]] = []
        from engine.appc.windows import _SubtitleWindow
        self._main_windows: dict[int, object] = {
            MWT_SUBTITLE: _SubtitleWindow(),
        }
        self._handler_registrations: list[tuple[int, str]] = []

    # ── Input gate ─────────────────────────────────────────────
    def AllowKeyboardInput(self, enabled) -> None:
        self._keyboard_input_enabled = bool(enabled)

    def IsKeyboardInputAllowed(self) -> bool:
        return self._keyboard_input_enabled

    def AllowMouseInput(self, enabled) -> None:
        self._mouse_input_enabled = bool(enabled)

    def IsMouseInputAllowed(self) -> bool:
        return self._mouse_input_enabled

    # ── Cutscene ───────────────────────────────────────────────
    def StartCutscene(self, *args) -> None:
        # SDK passes (fTimeToComeIn, fCoveredArea, bHideReticle) via
        # MissionLib.StartCutscene; we don't render fades or reticles
        # so accept and ignore.
        self._cutscene_active = True

    def EndCutscene(self, fTime: float = 0.0) -> None:
        # fTime is the fade-out duration; we don't render fades.
        self._cutscene_active = False

    def AbortCutscene(self) -> None:
        self._cutscene_active = False

    def IsCutsceneMode(self) -> bool:
        return self._cutscene_active

    # ── Fade ───────────────────────────────────────────────────
    def FadeOut(self, fTime: float = 0.0) -> None:
        self._fade_active = True

    def FadeIn(self, fTime: float = 0.0) -> None:
        self._fade_active = False

    def AbortFade(self) -> None:
        self._fade_active = False

    def IsFading(self) -> bool:
        return self._fade_active

    # ── View state (bridge vs tactical) ────────────────────────
    def IsBridgeVisible(self) -> bool:
        return self._bridge_visible

    def IsTacticalVisible(self) -> bool:
        return self._tactical_visible

    def ForceBridgeVisible(self) -> None:
        self._bridge_visible = True
        self._tactical_visible = False

    def ForceTacticalVisible(self) -> None:
        self._bridge_visible = False
        self._tactical_visible = True

    def ToggleBridgeAndTactical(self) -> None:
        self._bridge_visible, self._tactical_visible = (
            self._tactical_visible, self._bridge_visible,
        )

    # ── Main windows ───────────────────────────────────────────
    def FindMainWindow(self, mwt):
        return self._main_windows.get(int(mwt))

    # ── Event handler registration ─────────────────────────────
    # SDK code calls pTop.AddPythonFuncHandlerForInstance(event_type, "qualified.name")
    # to register per-instance handlers (inherited from TGEventHandlerObject
    # in BC). We record the registrations but don't dispatch through them
    # yet — a future spec will route them into g_kEventManager when an
    # SDK event flow actually needs them.
    def AddPythonFuncHandlerForInstance(
        self, event_type, qualified_name, *_extra
    ) -> None:
        self._handler_registrations.append((int(event_type), str(qualified_name)))

    # ── Children (tracked but not rendered — see CEF mirror follow-up) ──
    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._children.append((child, float(x), float(y)))

    def RemoveChild(self, child) -> None:
        self._children = [(c, x, y) for (c, x, y) in self._children if c is not child]

    def GetNumChildren(self) -> int:
        return len(self._children)

    def GetChildren(self) -> list:
        return [c for (c, _, _) in self._children]

    # ── Geometry ───────────────────────────────────────────────
    def _window_size(self) -> tuple[int, int]:
        """Live window size from the C++ host. Falls back to 1920x1080
        when the host extension isn't loaded (pytest, harness) or
        hasn't initialised the window yet (very-early call)."""
        try:
            import _dauntless_host
            return _dauntless_host.window_size()
        except (ImportError, RuntimeError):
            return (1920, 1080)

    def GetWidth(self) -> int:
        return self._window_size()[0]

    def GetHeight(self) -> int:
        return self._window_size()[1]

    # ── Lifecycle (engine hooks — no-op for the Python shim) ───
    def Initialize(self) -> None:
        pass

    def Update(self) -> None:
        pass

    # ── Edit mode ──────────────────────────────────────────────
    def SetEditMode(self, enabled) -> None:
        self._edit_mode = bool(enabled)

    def IsEditModeEnabled(self) -> bool:
        return self._edit_mode

    def ToggleEditMode(self) -> None:
        self._edit_mode = not self._edit_mode

    # ── UI toggles (no UI to drive — record-only) ──────────────
    def ToggleOptionsMenu(self) -> None:
        pass

    def ToggleConsole(self) -> None:
        pass

    def ToggleMapWindow(self) -> None:
        pass

    def ToggleCinematicWindow(self) -> None:
        pass

    def ToggleWireframe(self) -> None:
        pass

    def DisableOptionsMenu(self) -> None:
        self._options_disabled = True

    def ShowBadConnectionText(self, show) -> None:
        pass

    # ── Active render set tracking ─────────────────────────────
    def SetLastRenderedSet(self, pSet) -> None:
        self._last_rendered_set = pSet

    def GetLastRenderedSet(self):
        return self._last_rendered_set


_the_top_window = _TopWindow()


def TopWindow_GetTopWindow():
    return _the_top_window


def reset_for_tests() -> None:
    """Re-initialise the singleton so cutscene/fade/view flags don't
    bleed across missions or pytest runs. Called from
    engine/host_loop.reset_sdk_globals."""
    global _the_top_window
    from engine.appc.windows import _STStylizedWindow
    _STStylizedWindow._counter = 0
    _the_top_window = _TopWindow()


def keyboard_input_enabled() -> bool:
    """Module-level helper consulted by engine/appc/input.py's keyboard
    dispatch trampoline. Defined as a function (not a constant) so the
    flag is read at event-dispatch time, not at import time."""
    return _the_top_window._keyboard_input_enabled


def mouse_input_enabled() -> bool:
    """Reserved for a future mouse-event trampoline. No consumer today."""
    return _the_top_window._mouse_input_enabled
