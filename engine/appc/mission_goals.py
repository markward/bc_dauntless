"""XO 'Objectives' bridge-submenu wiring for mission goals.

BC's goal system has three entry points, all of which bottom out on the XO
("Saffi") character's "Objectives" submenu:

  * ``MissionLib.AddGoal`` -> ``Episode.RegisterGoal`` (C++) — adds a button.
  * ``MissionLib.RemoveGoal`` (pure Python) — disables the button.
  * ``MissionLib.DeleteAllGoals`` (pure Python) — ``KillChildren()``.

Our ``Episode`` never implemented ``RegisterGoal``/``RemoveGoal`` (they fell
through ``TGObject.__getattr__`` to a silent ``_Stub``), so objectives never
appeared and the mission's goal calls were no-ops. This module replicates the
``RegisterGoal`` side — the one Episode method ``AddGoal`` drives — and shares
the submenu/label lookup so the button labels match what ``RemoveGoal`` looks
up. Everything is best-effort and defensive: a missing bridge, XO, menu, or
localization DB degrades to "goal tracked but not shown" rather than raising,
because goal registration happens deep inside mission ``Initialize`` where a
throw would abort the load.
"""

_OBJECTIVES_KEY = "Objectives"
_BRIDGE_MENUS_TGL = "data/TGL/Bridge Menus.tgl"


def objectives_label():
    """Localized label of the XO 'Objectives' submenu (matches the label
    ``XOMenuHandlers.CreateMenus`` built it with), or the raw key on failure."""
    import App
    try:
        db = App.g_kLocalizationManager.Load(_BRIDGE_MENUS_TGL)
        s = db.GetString(_OBJECTIVES_KEY) if db is not None else None
        try:
            App.g_kLocalizationManager.Unload(db)
        except Exception:
            pass
        if isinstance(s, str) and s:
            return s
    except Exception:
        pass
    return _OBJECTIVES_KEY


def objectives_submenu():
    """The XO's 'Objectives' STMenu, or None if the bridge/XO/menu isn't up.
    Mirrors the lookup in ``MissionLib.RemoveGoal``/``DeleteAllGoals``."""
    import App
    pBridge = App.g_kSetManager.GetSet("bridge")
    if pBridge is None:
        return None
    pXO = App.CharacterClass_GetObject(pBridge, "XO")
    if pXO is None:
        return None
    menu = pXO.GetMenu()
    if menu is None or not hasattr(menu, "GetSubmenuW"):
        return None
    sub = menu.GetSubmenuW(objectives_label())
    # GetSubmenuW returns None (real miss) or an STMenu; never a _Stub here
    # because GetMenu already gave a real menu.
    return sub if (sub is not None and hasattr(sub, "GetButtonW")) else None


def goal_label(goal_id, *databases):
    """Display text for ``goal_id``: the first localization DB that has the
    string wins; otherwise the raw id (ugly but visible, and never a crash).
    ``RemoveGoal`` keys buttons off the episode DB's string, so the episode DB
    should be passed first to keep add/remove labels in sync."""
    for db in databases:
        if db is None:
            continue
        try:
            if db.HasString(goal_id):
                s = db.GetString(goal_id)
                if isinstance(s, str) and s:
                    return s
        except Exception:
            continue
    return str(goal_id)


def add_goal_button(label):
    """Add a goal button labelled ``label`` to the XO Objectives submenu, once.
    No-op (goal stays tracked on the Episode) if the menu isn't available."""
    import App
    menu = objectives_submenu()
    if menu is None:
        return
    if menu.GetButtonW(label) is not None:   # already shown
        return
    try:
        btn = App.STButton_CreateW(label)
        menu.AddChild(btn, 0.0, 0.0, 0)
    except Exception:
        pass


def disable_goal_button(label):
    """Strike (disable) a goal button by label. No-op if absent."""
    menu = objectives_submenu()
    if menu is None:
        return
    btn = menu.GetButtonW(label)
    if btn is not None:
        try:
            btn.SetDisabled()
        except Exception:
            pass
