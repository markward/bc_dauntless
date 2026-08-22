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

# Guest characters, in BC's own hunt order (BridgeHandlers.TalkToGuest,
# sdk/.../BridgeHandlers.py:933-937). A guest is a non-station bridge character
# with a mission-made menu (Bridge/PicardMenuHandlers and its two siblings);
# missions add at most one, so first-found wins.
_GUEST_NAMES = ("Picard", "Data", "Saalek")


def resolve_guest():
    """The guest character aboard, or None. BC's TalkToGuest hunt.

    Uses CharacterClass_GetObjectStrict, NOT CharacterClass_GetObject: the
    latter auto-vivifies a character for whatever name it is asked about (a
    headless convenience for mission scripts that chain GetMenu() unguarded),
    which would report a phantom Picard aboard every ship and stamp him into
    the bridge set as a side effect. BC's `if not (pCharacter)` fallthrough
    needs a real null.

    Imported from engine.appc.characters rather than read off App: the strict
    variant is OURS, not Appc surface, so `App.CharacterClass_GetObjectStrict`
    resolves through the module __getattr__ to a truthy _NamedStub — which
    would make the very first name always "found".
    """
    import App
    from engine.appc.characters import CharacterClass_GetObjectStrict
    bridge = App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        return None
    for name in _GUEST_NAMES:
        guest = CharacterClass_GetObjectStrict(bridge, name)
        if guest is not None:
            return guest
    return None


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


def station_name_for(officer):
    """The bridge set-object name for `officer` ("Helm"/"Tactical"/"XO"/
    "Science"/"Engineer"), or None. That name is exactly the SDK's
    <prefix>UpdateToolTip prefix (BridgeHandlers.HelmUpdateToolTip, ...), so the
    tooltip dispatcher (host loop) maps officer -> handler through this. Resolves
    by identity against the live "bridge" set."""
    if officer is None:
        return None
    try:
        import App
        bridge = App.g_kSetManager.GetSet("bridge")
        if bridge is None:
            return None
        for _key, char_name in _KEY_TO_CHARACTER.items():
            if App.CharacterClass_GetObject(bridge, char_name) is officer:
                return char_name
    except Exception:
        return None
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
    # F6 -> the guest, if one is aboard. Separate from the five station events:
    # a guest has no station and no fixed TGL menu label (their menu is titled
    # from Names.tgl by Bridge/PicardMenuHandlers), so they are reached through
    # the character, not through a label.
    import App
    tcw.AddPythonFuncHandlerForInstance(
        App.ET_INPUT_TALK_TO_GUEST, __name__ + "._on_talk_to_guest")


def get_panel():
    """The CrewMenuPanel wired by wire(), or None (headless / no UI).
    The seam CharacterClass.MenuUp uses to reach the view."""
    return _wired_panel


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


def open_menu_for_character(panel, character) -> bool:
    """Toggle `character`'s OWN menu (GetMenu()) via panel.toggle_menu.
    Returns True if there was a menu to toggle.

    The by-character twin of open_menu_for_label, for bridge characters that
    hold a menu but have no station label to look up: guests, and mission
    officers like E8M2's Liu. toggle_menu resolves the owner off the menu, so
    the raise still goes through CharacterClass.MenuUp() — the turn, the
    ET_CHARACTER_MENU signal and the acknowledgement all come with it."""
    if panel is None or character is None:
        return False
    menu = character.GetMenu()
    if not menu:
        # An unattached character holds the falsy NULL-menu handle. Nothing to
        # raise — BC's MenuUp() returns 0 here too.
        return False
    panel.toggle_menu(menu)
    return True


def _on_talk_to(dest, event) -> None:
    """Instance handler: toggle the menu matching the event type."""
    panel = _wired_panel
    if panel is None:
        return
    label = _label_cache.get(event.GetEventType())
    if label is None:
        return
    open_menu_for_label(panel, label)


def _on_talk_to_guest(dest, event) -> None:
    """Instance handler for ET_INPUT_TALK_TO_GUEST (F6).

    BridgeHandlers.TalkToGuest without the parts that are ours already: it
    hunts the same three names, and toggling through the panel covers BC's
    IsMenuUp()/DropMenusTurnBack() branch (single-open lives in toggle_menu ->
    MenuUp). Most missions carry no guest — then this is a no-op, and notably
    NOT a menu-drop: BC drops the open menus there, but it does so from a
    handler that also owns the tooltip/manual-fire teardown we do not run, and
    stealing the player's open station menu on a dead key would be a worse
    outcome than doing nothing."""
    panel = _wired_panel
    if panel is None:
        return
    open_menu_for_character(panel, resolve_guest())
