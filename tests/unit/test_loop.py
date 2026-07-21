import pytest
import App
from engine.core.loop import GameLoop

TICK = 1.0 / 60.0


@pytest.fixture(autouse=True)
def reset_timer_managers():
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()
    yield
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()


def test_game_loop_initial_time():
    loop = GameLoop()
    assert loop.game_time == 0.0


def test_game_loop_tick_advances_game_time():
    loop = GameLoop()
    loop.tick()
    assert abs(loop.game_time - TICK) < 1e-9


def test_game_loop_advance_n_ticks():
    loop = GameLoop()
    loop.advance(60)
    assert abs(loop.game_time - 1.0) < 1e-6


def test_game_loop_tick_advances_realtime_manager():
    loop = GameLoop()
    loop.tick()
    assert abs(App.g_kRealtimeTimerManager.get_time() - TICK) < 1e-9


def test_game_loop_game_time_reads_timer_manager():
    loop = GameLoop()
    App.g_kTimerManager._time = 3.14
    assert loop.game_time == 3.14
    App.g_kTimerManager._time = 0.0


def test_gameloop_ticks_time_slice_manager():
    """GameLoop.tick() should advance g_kAIManager so registered processes fire."""
    from engine.appc.time_slice import PythonMethodProcess, g_kAIManager
    fired = []
    class H:
        def Go(self, _dt=0.0): fired.append(1)
    proc = PythonMethodProcess()
    proc.SetFunction(H(), "Go")
    proc.SetDelay(0.05)
    proc.SetDelayUsesGameTime(1)
    g_kAIManager.Add(proc)
    try:
        loop = GameLoop()
        loop.advance(6)  # 6/60 = 0.1s — covers the 0.05 delay
        assert len(fired) >= 1
    finally:
        g_kAIManager.Remove(proc)


def test_gameloop_ticks_ai_driver_for_ships_with_ai():
    """GameLoop.tick() should call tick_ai on each ship's AI."""
    import App
    from engine.appc.ai import PlainAI
    from engine.appc.ships import ShipClass

    class _Leaf:
        def __init__(self):
            self.calls = 0
        def GetNextUpdateTime(self): return 1.0
        def Update(self):
            self.calls += 1
            return 0  # US_ACTIVE

    ship = ShipClass()
    pai = PlainAI(ship, "T")
    pai._script_instance = _Leaf()
    ship.SetAI(pai)

    pSet = App.SetClass_Create()
    pSet.SetName("aitest")
    pSet.AddObjectToSet(ship, "testship")
    App.g_kSetManager._sets["aitest"] = pSet
    try:
        loop = GameLoop()
        loop.tick()
        assert pai.GetScriptInstance().calls == 1
    finally:
        App.g_kSetManager._sets.pop("aitest", None)


def test_gameloop_runs_ai_before_motion_integrator():
    """Within one tick: AI scripts write setpoints, THEN the motion
    integrator reads them. If the order is reversed, the setpoint
    from this tick wouldn't move the ship until next tick.

    Three asserts:
      1. AI script Update fires (proves tick_all_ai ran).
      2. _speed_setpoint is non-None when the integrator reads it
         (proves AI ran first).
      3. _current_speed advanced from 0 -> target on this very tick
         (proves the integrator ran after AI, not before).
    """
    import App
    from engine.appc.ai import PlainAI
    from engine.appc.math import TGPoint3, TGPoint3_GetModelForward
    from engine.appc.ships import ShipClass

    setpoint_seen_during_update = []

    class _Leaf:
        def __init__(self):
            self.calls = 0
        def GetNextUpdateTime(self): return 1.0
        def Update(self):
            self.calls += 1
            # When this fires, the integrator has NOT yet run for
            # this tick — _current_speed should still be its prior
            # value (0 on first tick).
            setpoint_seen_during_update.append(ship._current_speed)
            ship.SetImpulse(50.0, TGPoint3_GetModelForward(),
                            App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)
            ship.SetTargetAngularVelocityDirect(TGPoint3(0.0, 0.0, 0.0))
            return 0  # US_ACTIVE

    ship = ShipClass()
    pai = PlainAI(ship, "T")
    pai._script_instance = _Leaf()
    ship.SetAI(pai)

    pSet = App.SetClass_Create()
    pSet.SetName("orderoftest")
    pSet.AddObjectToSet(ship, "testship")
    App.g_kSetManager._sets["orderoftest"] = pSet
    try:
        loop = GameLoop()
        loop.tick()

        # Assert 1: AI fired.
        assert pai.GetScriptInstance().calls == 1

        # Assert 2: At the moment AI ran, _current_speed was still 0
        # (integrator hadn't touched it yet on this tick).
        assert setpoint_seen_during_update == [0.0]

        # Assert 3: After tick() returned, the integrator HAS run and
        # ramped _current_speed up — FALLBACK_MAX_ACCEL snaps to 50.0
        # in one tick.
        assert ship._current_speed == 50.0
    finally:
        App.g_kSetManager._sets.pop("orderoftest", None)


def test_gameloop_drives_bridge_character_animation_queues():
    """GameLoop.tick() drives each bridge officer's CharacterClass animation
    queue (headless equivalent of the host-loop pump). A re-pointed
    CharacterAction enqueues an AnimRec whose on_complete is the mission
    TGSequence's Completed(); without this drive the record never plays and the
    sequence stalls headless. No clip-player controller exists here, so the
    record completes via ReleaseCurrentAnimation on the next drain (the
    no-controller completion guarantee)."""
    from engine.appc.characters import CharacterClass, CharacterClass_Create
    import engine.bridge_character_anim as bca
    bca.clear_controller()                       # headless: no clip-player

    officer = CharacterClass_Create()
    officer.SetActive(1)
    fired = []
    officer.GlanceAt("Left", on_complete=lambda: fired.append(1))
    assert len(officer._anim_pending) == 1       # enqueued, not yet played

    pSet = App.SetClass_Create()
    pSet.SetName("bridge")
    pSet.AddObjectToSet(officer, "helm")
    App.g_kSetManager._sets["bridge"] = pSet
    try:
        loop = GameLoop()
        loop.advance(3)                          # drive a few frames
        assert fired == [1]                      # on_complete fired -> sequence advances
        assert officer._anim_current is None     # record fully retired
    finally:
        App.g_kSetManager._sets.pop("bridge", None)


def test_gameloop_pump_is_safe_with_no_bridge_set():
    """No bridge set (typical space-combat headless run) -> the pump is a no-op,
    never raising."""
    App.g_kSetManager._sets.pop("bridge", None)
    loop = GameLoop()
    loop.tick()                                  # must not raise
