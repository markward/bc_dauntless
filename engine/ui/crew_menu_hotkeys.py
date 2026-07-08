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

_label_cache: dict = {}     # event_type -> resolved menu label


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


# Menu label (TGL key) -> bridge CharacterClass set-object name. Two officers
# differ: menu "Commander" is character "XO"; menu "Engineering" is "Engineer".
_KEY_TO_CHARACTER = {
    "Helm": "Helm", "Tactical": "Tactical", "Commander": "XO",
    "Science": "Science", "Engineering": "Engineer",
}


def resolve_character(menu_label):
    """Map an opened top-level menu's label to its bridge CharacterClass, or
    None. Locale-safe: matches the label against GetString(key) the same way
    the hotkey layer resolves labels."""
    import App
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    try:
        for key, char_name in _KEY_TO_CHARACTER.items():
            if str(db.GetString(key)) == str(menu_label):
                bridge = App.g_kSetManager.GetSet("bridge")
                return App.CharacterClass_GetObject(bridge, char_name)
    finally:
        App.g_kLocalizationManager.Unload(db)
    return None


def wire(tcw, panel) -> None:
    """Register TALK_TO handlers on `tcw`; remember `panel` for rewire()."""
    global _wired_panel
    _wired_panel = panel
    _label_cache.clear()
    for event_type, tgl_key in _event_map().items():
        _label_cache[event_type] = _resolve_label(tgl_key)
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


def open_menu_for_label(panel, label) -> bool:
    """Toggle the top-level menu whose title is `label` via panel.toggle_menu.
    Returns True if a menu was found. Shared by the F-key handler and the
    bridge-officer click picker (engine/ui/bridge_officer_picking.py) so both
    open menus through the one canonical path (turn-to-captain + acknowledge +
    single-open invariant all live in toggle_menu)."""
    if panel is None or label is None:
        return False
    from engine.appc.windows import TacticalControlWindow
    tcw = TacticalControlWindow.GetInstance()
    menu = tcw.FindMenu(label)
    if menu is None:
        _logger.info("crew-menu: no '%s' menu to toggle", label)
        return False
    panel.toggle_menu(menu)
    return True


def _on_talk_to(dest, event) -> None:
    """Instance handler: toggle the menu matching the event type."""
    panel = _wired_panel
    # TEMP DIAGNOSTIC (E1M1 post-undock input lock RE) — proves an F-key
    # TALK_TO event reached this handler (vs being blocked upstream by
    # keyboard-input gating) and whether a menu was found. REMOVE.
    try:
        _et = event.GetEventType()
    except Exception:
        _et = "?"
    print("[INPUTLOCK] talk_to et=%s panel=%s label=%r" % (
        _et, panel is not None, _label_cache.get(_et)), flush=True)
    if panel is None:
        return
    label = _label_cache.get(event.GetEventType())
    if label is None:
        return
    open_menu_for_label(panel, label)
