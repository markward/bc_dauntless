"""SDK TopWindow shim.

Replaces the _NamedStub previously returned for App.TopWindow_GetTopWindow.
Owns input-gate flags, cutscene/fade/view state, the SDK UI children
list (for a future CEF mirror), and FindMainWindow lookups.

See docs/superpowers/specs/2026-06-03-top-window-shim-design.md.
"""

from engine.appc.events import (
    TGEvent,
    TGEventHandlerObject,
    ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL,
)


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
        self._letterbox_covered: float = 0.125
        self._letterbox_transition_s: float = 0.0
        self._hide_reticle: bool = False
        self._fade_active: bool = False
        self._bridge_visible: bool = True
        self._tactical_visible: bool = False
        self._edit_mode: bool = False
        self._options_disabled: bool = False
        self._last_rendered_set = None
        self._children: list[tuple[object, float, float]] = []
        self._focus = None
        from engine.appc.windows import (
            _CinematicWindow, _MainViewWindow, _OptionsWindow, _SubtitleWindow,
        )
        self._main_windows: dict[int, object] = {
            MWT_SUBTITLE: _SubtitleWindow(),
            MWT_OPTIONS: _OptionsWindow(),
            # AI/Compound/DockWithStarbase.SetupCutscene dereferences
            # FindMainWindow(MWT_CINEMATIC).GetObjID() with no None-guard
            # (unlike Actions.CameraScriptActions.Start/StopCinematicMode,
            # which check `if pCinematic:` first) — real BC always has this
            # window, so returning raw None here is the same class of gap
            # _OptionsWindow fixed for MWT_OPTIONS above. See _CinematicWindow.
            MWT_CINEMATIC: _CinematicWindow(),
            # Bridge/Tactical main windows: SDK UI re-parents the
            # TacticalControlWindow into the visible one with no None guard —
            # Tactical.Interface.TacticalControlWindow.Refresh (runs at the end
            # of the E6M2 dock via DockWithStarbase.FinishedUndocking) does
            # FindMainWindow(MWT_TACTICAL).AddChild(...). Raw None crashed. See
            # _MainViewWindow.
            MWT_BRIDGE: _MainViewWindow(),
            MWT_TACTICAL: _MainViewWindow(),
        }
        # Instance event chain (composition, not inheritance: _TopWindow
        # stays a plain class so missing methods raise AttributeError
        # instead of vending _Stubs — see the focus/z-order comment below).
        # The default toggle handler is registered HERE so every singleton
        # rebuild (mission swap via reset_for_tests) re-arms it with no
        # external wiring — spec §7 lifecycle rule.
        self._events = TGEventHandlerObject()
        self._events.AddPythonFuncHandlerForInstance(
            ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL,
            "engine.appc.top_window._default_toggle_handler",
        )

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
    def StartCutscene(self, fTimeToComeIn=1.0, fCoveredArea=0.125,
                      bHideReticle=1, *args) -> None:
        # MissionLib.StartCutscene passes (fTimeToComeIn, fCoveredArea,
        # bHideReticle). fCoveredArea is the TOTAL letterbox coverage
        # (0.125 = 6.25% per bar); bHideReticle hides the targeting
        # reticle. fTimeToComeIn is the bar slide-in duration.
        self._cutscene_active = True
        self._letterbox_covered = float(fCoveredArea)
        self._letterbox_transition_s = float(fTimeToComeIn)
        self._hide_reticle = bool(bHideReticle)

    def EndCutscene(self, fTime: float = 1.0, *args) -> None:
        # fTime is the bar slide-out duration.
        self._cutscene_active = False
        self._letterbox_transition_s = float(fTime)
        _release_camera_watch()

    def AbortCutscene(self) -> None:
        self._cutscene_active = False
        self._letterbox_transition_s = 0.0   # snap, no slide-out
        _release_camera_watch()

    def IsCutsceneMode(self) -> bool:
        return self._cutscene_active

    def reticle_hidden(self) -> bool:
        """True when the targeting reticle should be suppressed: a cutscene
        is active and it was started with bHideReticle set."""
        return self._cutscene_active and self._hide_reticle

    def letterbox_snapshot(self) -> dict:
        """Render-ready letterbox state for the CEF sdk-mirror overlay."""
        return {
            "type": "letterbox",
            "visible": self._cutscene_active,
            "covered": self._letterbox_covered,
            "transition_s": self._letterbox_transition_s,
        }

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

    # ── Event handler chain ────────────────────────────────────
    # SDK code registers per-instance handlers (E1M1/E1M2
    # TacticalToggleHandler) and swallows events by returning without
    # CallNextHandler; the chain is LIFO (see TGEventHandlerObject).
    def AddPythonFuncHandlerForInstance(
        self, event_type, qualified_name, *_extra
    ) -> None:
        self._events.AddPythonFuncHandlerForInstance(
            int(event_type), str(qualified_name))

    def RemoveHandlerForInstance(self, event_type, qualified_name) -> None:
        self._events.RemoveHandlerForInstance(
            int(event_type), str(qualified_name))

    def ProcessEvent(self, event) -> None:
        self._events.ProcessEvent(event)

    # ── Children (tracked but not rendered — see CEF mirror follow-up) ──
    def AddChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        self._children.append((child, float(x), float(y)))

    def RemoveChild(self, child) -> None:
        self._children = [(c, x, y) for (c, x, y) in self._children if c is not child]

    def PrependChild(self, child, x: float = 0.0, y: float = 0.0, *_extra) -> None:
        # Parent the child back to this TopWindow so SDK callers that later
        # do pChild.GetParent().DeleteChild(pChild) reach DeleteChild below
        # without any SDK edit. MissionLib.HideLargeLoadingScreen relies on
        # exactly this (pScreen.GetParent().DeleteChild(pScreen)) — the
        # back-ref is load-bearing independent of the (now-removed)
        # pointer-arrow overlay, which also used to call PrependChild.
        from engine.appc.tg_ui.widgets import TGPane
        if isinstance(child, TGPane):
            child._parent = self

    def DeleteChild(self, child) -> None:
        pass

    def GetNumChildren(self) -> int:
        return len(self._children)

    def GetChildren(self) -> list:
        return [c for (c, _, _) in self._children]

    # ── Focus + z-order ────────────────────────────────────────
    # Unlike the TGObject widgets, _TopWindow is a plain class with no
    # __getattr__ stub, so missing methods raise AttributeError. QuickBattle's
    # OpenConfigDialog/CloseConfigDialog/StartQuickBattle call these to raise
    # the config pane and restore focus; we have no rendered z-order or focus
    # ring, so focus is a stored value and the moves reorder _children.
    def GetFocus(self):
        return self._focus

    def SetFocus(self, child) -> None:
        self._focus = child

    def MoveToFront(self, child) -> None:
        entry = next((e for e in self._children if e[0] is child), None)
        if entry is not None:
            self._children.remove(entry)
            self._children.append(entry)

    def MoveToBack(self, child) -> None:
        entry = next((e for e in self._children if e[0] is child), None)
        if entry is not None:
            self._children.remove(entry)
            self._children.insert(0, entry)

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


def _release_camera_watch() -> None:
    """Clear any AT_LOOK_AT_ME / AT_WATCH_ME camera-framing target when a cutscene
    ends. BC scopes that framing to StartCutscene..EndCutscene (the QB intro's
    AT_LOOK_AT_ME(XO) has no AT_STOP_WATCHING_ME); without this the persistent
    target outranks the menu zoom-to-officer and locks the camera on the officer
    forever. Best-effort: headless / no controller registered -> no-op."""
    try:
        from engine import bridge_camera_watch
        ctrl = bridge_camera_watch.get_controller()
        if ctrl is not None:
            ctrl.clear()
    except Exception:
        pass


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


def _default_toggle_handler(_dispatcher, _event) -> None:
    """Bottom-of-chain default for ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL.
    Runs synchronously inside CallNextHandler — E1M1's TacticalToggleHandler
    reads IsBridgeVisible() immediately after CallNextHandler and expects
    the flip to have already happened (E1M1.py:1194-1198)."""
    _the_top_window.ToggleBridgeAndTactical()


def bridge_flag() -> bool:
    """Per-frame view selector consulted by host_loop's
    _ViewModeController. Function, not constant: read at frame time."""
    return _the_top_window._bridge_visible


def dispatch_toggle_bridge_and_tactical() -> None:
    """Host entry point for the SPACE key: routes the toggle through the
    TopWindow instance-handler chain so missions can swallow it
    (E1M1/E1M2 TacticalToggleHandler hold the player on the bridge
    during tutorials by returning without CallNextHandler)."""
    ev = TGEvent()
    ev.SetEventType(ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL)
    _the_top_window.ProcessEvent(ev)
