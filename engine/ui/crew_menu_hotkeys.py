"""F1-F5 -> crew menu toggles.

The SDK pipeline (KeyConfig + DefaultKeyboardBinding, both run at host
startup) turns F-key presses into ET_INPUT_TALK_TO_* events at the
TacticalControlWindow. Stock BC's handlers (BridgeHandlers.TalkTo*) open a
bridge *character* menu -- a dead end headless (no characters in the bridge
set) -- so these handlers open the corresponding CEF crew menu instead: the
trigger chain is faithful, the effect is the dauntless re-style.

TGL keys verified against STTopLevelMenu_CreateW call sites (Step 0):
  HelmMenuHandlers.py:173     GetString("Helm")
  TacticalMenuHandlers.py:341 GetString("Tactical")
  XOMenuHandlers.py:56        GetString("Commander")   <-- NOT "XO"
  ScienceMenuHandlers.py:68   GetString("Science")
  EngineerMenuHandlers.py:74  GetString("Engineering") <-- NOT "Engineer"

Spec: docs/superpowers/specs/2026-06-12-bridge-menu-hotkeys-design.md
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

# Built lazily -- App import must stay deferred (App imports engine modules).
_EVENT_TO_TGL_KEY = None

_wired_panel = None


def _event_map():
    global _EVENT_TO_TGL_KEY
    if _EVENT_TO_TGL_KEY is None:
        import App
        _EVENT_TO_TGL_KEY = {
            App.ET_INPUT_TALK_TO_HELM:        "Helm",
            App.ET_INPUT_TALK_TO_TACTICAL:    "Tactical",
            App.ET_INPUT_TALK_TO_XO:          "Commander",
            App.ET_INPUT_TALK_TO_SCIENCE:     "Science",
            App.ET_INPUT_TALK_TO_ENGINEERING: "Engineering",
        }
    return _EVENT_TO_TGL_KEY


def wire(tcw, panel) -> None:
    """Register TALK_TO handlers on `tcw`; remember `panel` for rewire()."""
    global _wired_panel
    _wired_panel = panel
    for event_type in _event_map():
        tcw.AddPythonFuncHandlerForInstance(
            event_type, __name__ + "._on_talk_to")


def rewire() -> None:
    """Mission-swap hook: re-register on the current TCW singleton.
    No-op when wire() was never called (headless tests, early reset)."""
    if _wired_panel is None:
        return
    from engine.appc.windows import TacticalControlWindow
    wire(TacticalControlWindow.GetInstance(), _wired_panel)


def _resolve_label(tgl_key: str) -> str:
    """Menu label for a TGL key -- same lookup LoadBridge's epilogue uses.
    Headless TGL falls back to the key string, which matches the labels
    the handlers were built with."""
    import App
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    label = str(db.GetString(tgl_key))
    App.g_kLocalizationManager.Unload(db)
    return label


def _on_talk_to(dest, event) -> None:
    """Instance handler: toggle the menu matching the event type."""
    panel = _wired_panel
    if panel is None:
        return
    tgl_key = _event_map().get(event.GetEventType())
    if tgl_key is None:
        return
    from engine.appc.windows import TacticalControlWindow
    tcw = TacticalControlWindow.GetInstance()
    menu = tcw.FindMenu(_resolve_label(tgl_key))
    if menu is None:
        _logger.info("crew-menu hotkey: no '%s' menu to toggle", tgl_key)
        return
    panel.toggle_menu(menu)
