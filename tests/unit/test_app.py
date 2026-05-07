import App


def test_null_id():
    assert App.NULL_ID == 0


def test_constants():
    import math
    assert abs(App.PI - math.pi) < 1e-6
    assert abs(App.HALF_PI - math.pi / 2) < 1e-6
    assert abs(App.TWO_PI - 2 * math.pi) < 1e-6


def test_timer_manager_exists():
    assert App.g_kTimerManager is not None


def test_realtime_timer_manager_exists():
    assert App.g_kRealtimeTimerManager is not None


def test_event_manager_exists():
    assert App.g_kEventManager is not None


def test_tgevent_create():
    from engine.appc.events import TGEvent
    ev = App.TGEvent_Create()
    assert isinstance(ev, TGEvent)


def test_tgtimer_create():
    from engine.appc.timers import TGTimer
    t = App.TGTimer_Create()
    assert isinstance(t, TGTimer)


def test_stub_unknown_attribute_does_not_raise():
    thing = App.SomeClassThatDoesNotExist
    assert thing is not None


def test_stub_call_does_not_raise():
    result = App.SomeClassThatDoesNotExist()
    assert result is not None


def test_et_entered_set_is_int():
    assert isinstance(App.ET_ENTERED_SET, int)


def test_et_object_exploding_is_int():
    assert isinstance(App.ET_OBJECT_EXPLODING, int)


def test_game_get_next_event_type_increments():
    t1 = App.Game_GetNextEventType()
    t2 = App.Game_GetNextEventType()
    assert isinstance(t1, int)
    assert t2 == t1 + 1


def test_utopia_get_game_time_returns_float():
    t = App.g_kUtopiaModule.GetGameTime()
    assert isinstance(t, float)


def test_utopia_get_game_time_reflects_timer_manager():
    original = App.g_kTimerManager._time
    App.g_kTimerManager._time = 5.0
    assert App.g_kUtopiaModule.GetGameTime() == 5.0
    App.g_kTimerManager._time = original


def test_stub_is_truthy():
    # Stubs are truthy: they represent valid-but-unimplemented objects so that
    # SDK guards like `if not pSet: return None` don't short-circuit Phase 1.
    stub = App.SomeUnimplementedThing()
    assert stub
