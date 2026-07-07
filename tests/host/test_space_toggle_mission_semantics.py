"""Mission-shaped contracts for the SPACE toggle + cutscene view restore.

Mirrors E1M1.py:1187-1204 (TacticalToggleHandler) and
MissionLib.py:788-802 (EndCutscene's restore conditional) without
importing the SDK: the shapes are copied verbatim so a regression here
means those mission code paths break live.
"""

_tutorial_active = [False]
_seen_after_callnext = []


def _mission_tactical_toggle_handler(dispatcher, event):
    # E1M1.py:1187: swallow during tutorial (return, no CallNextHandler)
    if _tutorial_active[0]:
        return
    # E1M1.py:1194: pass on, THEN read the flag — the default must have
    # run synchronously inside CallNextHandler.
    dispatcher.CallNextHandler(event)
    import engine.appc.top_window as top_window
    _seen_after_callnext.append(
        top_window.TopWindow_GetTopWindow().IsBridgeVisible())


def _install(top_window):
    top_window.TopWindow_GetTopWindow().AddPythonFuncHandlerForInstance(
        top_window.ET_INPUT_TOGGLE_BRIDGE_AND_TACTICAL,
        __name__ + "._mission_tactical_toggle_handler")


def test_tutorial_swallow_holds_bridge_view():
    import engine.appc.top_window as top_window
    top_window.reset_for_tests()
    _tutorial_active[0] = True
    _install(top_window)
    top_window.dispatch_toggle_bridge_and_tactical()
    assert top_window.TopWindow_GetTopWindow().IsBridgeVisible() is True


def test_callnexthandler_sees_flipped_flag_synchronously():
    import engine.appc.top_window as top_window
    top_window.reset_for_tests()
    _tutorial_active[0] = False
    _seen_after_callnext.clear()
    _install(top_window)
    top_window.dispatch_toggle_bridge_and_tactical()     # bridge -> tactical
    assert _seen_after_callnext == [False]
    top_window.dispatch_toggle_bridge_and_tactical()     # tactical -> bridge
    assert _seen_after_callnext == [False, True]


def test_end_cutscene_restore_conditional_shape():
    """MissionLib.py:790: if str(bridge_set) != str(rendered_set) force
    tactical, else force bridge. Both branches, driven only by view state."""
    import App
    import engine.appc.top_window as top_window
    from engine.appc.sets import SetClass

    top_window.reset_for_tests()                          # bridge visible
    App.g_kSetManager._sets.clear()
    App.g_kSetManager._rendered_set_name = None
    bridge, space = SetClass(), SetClass()
    App.g_kSetManager.AddSet(bridge, "bridge")
    App.g_kSetManager.AddSet(space, "Vesuvi6")
    App.g_kSetManager.MakeRenderedSet("Vesuvi6")

    pBridgeSet = App.g_kSetManager.GetSet("bridge")

    # Player on the bridge when the cutscene ends -> bridge branch
    # (the user-observed "always returns to bridge" for E1M1/E1M2).
    assert str(pBridgeSet) == str(App.g_kSetManager.GetRenderedSet())

    # Player toggled to tactical before the cutscene ends -> tactical branch.
    top_window.TopWindow_GetTopWindow().ForceTacticalVisible()
    assert str(pBridgeSet) != str(App.g_kSetManager.GetRenderedSet())
