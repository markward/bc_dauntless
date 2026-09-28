"""The Helm menu during a dash (in-system-warp spec §2, "While dashing").

BC greys the whole Helm menu for a tunnel warp (WarpPressed's SetDisabled).
A dash leaves the menu itself enabled -- All Stop must stay clickable, it is
how the player drops out -- and disables only the entries that would start
another warp or a Helm order: Warp, Set Course, Orbit Planet, Intercept,
Dock and Warp on Heading. On drop-out it restores exactly the
entries it disabled; one that was already disabled (Dock away from a
starbase, Orbit Planet with no planet) stays as the SDK left it.

All Stop: an ``ET_ALL_STOP`` instance handler on the Helm menu, kept the
NEWEST so it runs first (handler chains are LIFO, engine/appc/events.py). It
drops out of the dash, then passes the event on to the SDK's
HelmMenuHandlers.AllStop -- whose MissionLib.SetPlayerAI(Stay) would
otherwise end the flight through SetAI with no drop-out of its own choosing.

Warp on Heading: ``sync`` also adds that entry once per Helm menu, right
after the Warp button, and -- out of a dash -- greys it while a mission has
disabled Set Course (ruling R15). It is offered in mapped and unmapped sets
alike. Its click runs ``_on_heading`` -> warp_button.press_heading.

``sync(player)`` runs every tick (like weapon_tactical_commands.sync) and at
dash start and drop-out. Raise-safe: it must never throw into the tick loop.
What it disabled is recorded on the menu object itself, so a rebuilt Helm
menu starts clean.
"""
from __future__ import annotations

_HANDLER = "engine.appc.dash_helm._on_all_stop"
_HEADING_HANDLER = "engine.appc.dash_helm._on_heading"
# Bridge Menus.tgl keys of the entries a dash disables.
_ENTRY_KEYS = ("Warp", "Set Course", "Orbit Planet", "Intercept", "Dock")
# Project-authored label (BC has no string for it); sync adds the entry.
WARP_ON_HEADING_LABEL = "Warp on Heading"


# The "Warp on Heading" entry's event type, allocated once (like
# weapon_tactical_commands' ET_WEAPON_TACTICAL_CMD).
_ET_WARP_ON_HEADING = None

# (helm label, entry labels, the Helm menu they were resolved for). Bridge
# Menus.tgl is parsed again only when the Helm menu object changes (a
# bridge reload builds a new one), never every frame.
_cache = None


def _labels():
    import App
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    try:
        helm = str(db.GetString("Helm"))
        entries = [str(db.GetString(k)) for k in _ENTRY_KEYS]
    finally:
        App.g_kLocalizationManager.Unload(db)
    return helm, entries + [WARP_ON_HEADING_LABEL]


def _helm_menu(helm_label):
    try:
        from engine.appc.windows import TacticalControlWindow
        menu = TacticalControlWindow.GetInstance().FindMenu(helm_label)
    except Exception:
        menu = None
    if menu is None:
        from engine.bridge_officers import _helm_menu as officer_menu
        menu = officer_menu()
    return menu or None


def _menu_and_labels():
    """The Helm menu and the dash's entry labels, re-reading the TGL only
    when the menu found is not the one the cached labels came from."""
    global _cache
    if _cache is not None:
        helm_label, entries, menu = _cache
        found = _helm_menu(helm_label)
        if found is menu:
            return found, entries
    helm_label, entries = _labels()
    menu = _helm_menu(helm_label)
    _cache = (helm_label, entries, menu)
    return menu, entries


def _ensure_handler(menu) -> None:
    """Register the All Stop handler once, and keep it the newest (handler
    chains run newest-first). Through the public calls: re-adding appends,
    which is exactly "newest", so a mission that registers its own
    ET_ALL_STOP handler later is re-overtaken on the next sync. The chain is
    only READ here, to skip the churn when we are already newest."""
    import App
    chain = menu.__dict__.get("_handlers", {}).get(App.ET_ALL_STOP, [])
    if chain and chain[-1] == _HANDLER:
        return
    menu.RemoveHandlerForInstance(App.ET_ALL_STOP, _HANDLER)
    menu.AddPythonFuncHandlerForInstance(App.ET_ALL_STOP, _HANDLER)


def _heading_event_type() -> int:
    global _ET_WARP_ON_HEADING
    if _ET_WARP_ON_HEADING is None:
        import App
        _ET_WARP_ON_HEADING = App.Game_GetNextEventType()
    return _ET_WARP_ON_HEADING


def _ensure_heading_entry(menu):
    """Add "Warp on Heading" once per Helm menu, directly after the Warp
    button (STMenu.InsertChildAfter), and return it. Its click reaches
    ``_on_heading`` through the menu's own instance handler."""
    import App
    entry = menu.__dict__.get("_heading_entry")
    if entry is not None and any(c is entry for c in menu._children):
        return entry
    et = _heading_event_type()
    evt = App.TGEvent_Create()
    evt.SetEventType(et)
    evt.SetDestination(menu)
    entry = App.STButton_CreateW(WARP_ON_HEADING_LABEL, evt)
    menu.InsertChildAfter(entry, App.SortedRegionMenu_GetWarpButton())
    menu.__dict__["_heading_entry"] = entry
    if _HEADING_HANDLER not in menu.__dict__.get("_handlers", {}).get(et, []):
        menu.AddPythonFuncHandlerForInstance(et, _HEADING_HANDLER)
    return entry


def _set_course_enabled(menu, entry_labels) -> bool:
    """Whether the Helm's "Set Course" entry is enabled (absent: True)."""
    label = entry_labels[_ENTRY_KEYS.index("Set Course")]
    for child in menu.__dict__.get("_children", []):
        if hasattr(child, "GetLabel") and child.GetLabel() == label:
            return bool(child.IsEnabled())
    return True


def sync(player) -> None:
    try:
        from engine.appc import dash
        menu, entry_labels = _menu_and_labels()
        if menu is None:
            return
        _ensure_handler(menu)
        heading = _ensure_heading_entry(menu)
        disabled = menu.__dict__.setdefault("_dash_disabled", [])
        # Edges while dashing (each sync disables every ENABLED entry not
        # yet recorded, and records it):
        # * an entry we disabled that the SDK re-enables mid-dash is already
        #   recorded, so it is left alone and STAYS ENABLED for the rest of
        #   the dash (the SDK's call wins); it is still "restored" (enabled)
        #   at the drop-out;
        # * an entry that was disabled at the press and the SDK enables
        #   mid-dash is disabled and recorded on the next sync, so the
        #   drop-out restores it to enabled -- as the SDK last set it;
        # * an entry disabled at the press, or disabled by the SDK mid-dash,
        #   is never touched, so the drop-out leaves it as the SDK wants it.
        if dash.is_dashing(player):
            for child in menu.__dict__.get("_children", []):
                if (hasattr(child, "GetLabel")
                        and child.GetLabel() in entry_labels
                        and child.IsEnabled()
                        and not any(c is child for c in disabled)):
                    child.SetDisabled()
                    disabled.append(child)
        else:
            if disabled:
                for child in disabled:
                    child.SetEnabled()
                del disabled[:]
            # Out of a dash, Warp on Heading is offered in any set, mapped
            # or not (Mark, 2026-09-27: features are consistent everywhere;
            # an unmapped set dashes on its own Planet/Sun objects). It
            # follows Set Course (ruling R15):
            # missions hold the player by disabling that entry (E1M1:4343,
            # E1M2:5991, E3M1:286), and "no course is available" bars a
            # heading dash as well. Checked after the restore above, so the
            # dash's own disabling never reads as a mission's bar.
            if _set_course_enabled(menu, entry_labels):
                heading.SetEnabled()
            else:
                heading.SetDisabled()
    except Exception as _e:
        from engine import dev_mode
        dev_mode.log_swallowed("dash helm sync", _e)


def _on_heading(pObject, pEvent) -> None:
    """The "Warp on Heading" click: BC's warp button event, with no course
    (warp_button.press_heading)."""
    try:
        import App
        from engine.appc import warp_button
        button = App.SortedRegionMenu_GetWarpButton()
        if button is not None:
            warp_button.press_heading(button)
    except Exception as _e:
        from engine import dev_mode
        dev_mode.log_swallowed("Warp on Heading", _e)


def _on_all_stop(pObject, pEvent) -> None:
    """All Stop during a dash: drop out at rest, then let the SDK's AllStop
    (and anything older) run."""
    try:
        import App
        from engine.appc import dash
        player = App.Game_GetCurrentPlayer()
        if player is not None and dash.is_dashing(player):
            dash.drop_out(player, "stopped")
    except Exception as _e:
        from engine import dev_mode
        dev_mode.log_swallowed("dash All Stop", _e)
    pObject.CallNextHandler(pEvent)
