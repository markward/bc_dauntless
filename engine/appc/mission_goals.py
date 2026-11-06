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
    # Falsy covers both None and the NULL menu handle (an unattached XO's
    # GetMenu returns the falsy-but-dereferenceable _NULL_MENU).
    if not menu or not hasattr(menu, "GetSubmenuW"):
        return None
    sub = menu.GetSubmenuW(objectives_label())
    # GetSubmenuW returns None (real miss) or an STMenu; never a _Stub here
    # because GetMenu already gave a real menu.
    return sub if (sub and hasattr(sub, "GetButtonW")) else None


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


# Clicking a goal has the XO say that goal's briefing line: every campaign
# goal ``<id>`` has a spoken twin ``<id>Audio`` in the same database ("Clear
# Debris" -> "We'll need to clear away the debris in the area around the
# orbital facility.", sfx/Maelstrom/Episode 1/E1DestroyDebrisGoalAudio.mp3).
# The missions speak those lines the same way (E7M1.py:2471 Saffi,
# AT_SAY_LINE, "<id>Audio", "Captain", 1, the episode database), and
# Episode8.Initialize preloads them with LoadDatabaseSound.
_GOAL_AUDIO_SUFFIX = "Audio"
_HANDLER = __name__ + ".GoalClicked"
# Event type, allocated lazily and forgotten by reset(): App._next_event_type_id
# restarts at 1200 on every mission swap (host_loop.reset_sdk_globals), so a
# type cached across a swap could be handed to the next mission for its own
# event, and a goal click would reach that mission's handler.
_goal_event_type = None
_xo_registered = None  # (XO object, event type) our handler is registered for


def _goal_clicked_type():
    global _goal_event_type
    if _goal_event_type is None:
        import App
        _goal_event_type = App.Game_GetNextEventType()
    return _goal_event_type


def _register_handler(xo, et) -> None:
    global _xo_registered
    if (_xo_registered is not None and _xo_registered[0] is xo
            and _xo_registered[1] == et):
        return
    xo.AddPythonFuncHandlerForInstance(et, _HANDLER)
    _xo_registered = (xo, et)


def reset() -> None:
    """Mission swap / test isolation: forget the event type and the XO it was
    registered on (host_loop.reset_mission_state)."""
    global _goal_event_type, _xo_registered
    _goal_event_type = None
    _xo_registered = None


def _xo():
    import App
    pBridge = App.g_kSetManager.GetSet("bridge")
    if pBridge is None:
        return None
    return App.CharacterClass_GetObject(pBridge, "XO")


def add_goal_button(label, goal_id=None):
    """Add a goal button labelled ``label`` to the XO Objectives submenu, once.
    With ``goal_id`` a click has the XO speak the goal's ``<id>Audio`` line
    (GoalClicked). No-op (goal stays tracked on the Episode) if the menu
    isn't available."""
    import App
    menu = objectives_submenu()
    if menu is None:
        return
    if menu.GetButtonW(label) is not None:   # already shown
        return
    try:
        event = None
        xo = _xo() if goal_id else None
        if xo is not None:
            et = _goal_clicked_type()
            _register_handler(xo, et)
            event = App.TGStringEvent_Create()
            event.SetEventType(et)
            event.SetDestination(xo)
            event.SetString(str(goal_id))
        btn = (App.STButton_CreateW(label, event) if event is not None
               else App.STButton_CreateW(label))
        menu.AddChild(btn, 0.0, 0.0, 0)
    except Exception:
        pass


def goal_audio_database(goal_id):
    """The localization DB holding ``<goal_id>Audio``: the current episode's,
    then the current mission's. None when neither has it."""
    import App
    key = str(goal_id) + _GOAL_AUDIO_SUFFIX
    try:
        episode = App.Game_GetCurrentGame().GetCurrentEpisode()
    except Exception:
        return None
    dbs = []
    for getter in (lambda: episode.GetDatabase(),
                   lambda: episode.GetCurrentMission().GetDatabase()):
        try:
            dbs.append(getter())
        except Exception:
            pass
    for db in dbs:
        try:
            if db is not None and db.HasString(key):
                return db
        except Exception:
            continue
    return None


def GoalClicked(pObject, pEvent):
    """A goal button was clicked: the XO says the goal's briefing line, to the
    Captain, with its subtitle, as the missions' own goal lines play."""
    import App
    try:
        goal_id = pEvent.GetCString()
        db = goal_audio_database(goal_id)
        xo = _xo()
        if db is not None and xo is not None:
            App.CharacterAction_Create(
                xo, App.CharacterAction.AT_SAY_LINE,
                goal_id + _GOAL_AUDIO_SUFFIX, "Captain", 1, db).Play()
    except Exception:
        pass
    try:
        pObject.CallNextHandler(pEvent)
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
