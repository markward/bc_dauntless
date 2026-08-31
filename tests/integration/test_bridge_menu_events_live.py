import App

fired = []


def record(obj, evt):
    fired.append(evt)


def test_bridge_menu_button_event_reaches_its_handler():
    """CreateBridgeMenuButton stamps App.ET_X on a TGIntEvent the button posts
    (sdk Bridge/BridgeUtils.py:37-43).  While ET_X was a _NamedStub the module
    __getattr__ vended a FRESH object per access, so the button's key and the
    handler's key were different objects and the click went nowhere."""
    assert isinstance(App.ET_SHOW_MISSION_LOG, int)
    fired[:] = []
    obj = App.TGEventHandlerObject()
    obj.AddPythonFuncHandlerForInstance(App.ET_SHOW_MISSION_LOG,
                                        "tests.integration."
                                        "test_bridge_menu_events_live.record")
    evt = App.TGIntEvent_Create()
    evt.SetEventType(App.ET_SHOW_MISSION_LOG)
    evt.SetDestination(obj)
    obj.ProcessEvent(evt)
    assert fired == [evt], "the handler must actually run"


def test_undefined_event_summary_is_empty():
    from engine.appc.events import undefined_event_type_summary_lines
    assert undefined_event_type_summary_lines() == []
