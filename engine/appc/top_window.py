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
        self._main_windows: dict[int, object] = {}

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
    def StartCutscene(self) -> None:
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


_the_top_window = _TopWindow()


def TopWindow_GetTopWindow():
    return _the_top_window


def reset_for_tests() -> None:
    """Re-initialise the singleton so cutscene/fade/view flags don't
    bleed across missions or pytest runs. Called from
    engine/host_loop.reset_sdk_globals."""
    global _the_top_window
    _the_top_window = _TopWindow()


def keyboard_input_enabled() -> bool:
    """Module-level helper consulted by engine/appc/input.py's keyboard
    dispatch trampoline. Defined as a function (not a constant) so the
    flag is read at event-dispatch time, not at import time."""
    return _the_top_window._keyboard_input_enabled


def mouse_input_enabled() -> bool:
    """Reserved for a future mouse-event trampoline. No consumer today."""
    return _the_top_window._mouse_input_enabled
