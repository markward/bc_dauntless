"""
Integration tests for tools/gameloop_harness.py.

Uses M1Basic (the minimal SDK tutorial mission) as the known-good subject.
Requires the full SDK under sdk/Build/scripts/.
"""
import sys
import types
import pytest
import App
from engine.appc.timers import TGTimer_Create
from engine.appc.events import TGEvent


@pytest.fixture(scope="session", autouse=True)
def sdk_setup():
    from tools.mission_harness import setup_sdk
    setup_sdk()


def test_run_mission_with_loop_importable():
    from tools.gameloop_harness import run_mission_with_loop
    assert callable(run_mission_with_loop)


def test_zero_ticks_pass(sdk_setup):
    from tools.gameloop_harness import run_mission_with_loop
    status, exc, ticks = run_mission_with_loop(
        "Custom.Tutorial.Episode.M1Basic.M1Basic", n_ticks=0
    )
    assert status == "pass"
    assert exc is None
    assert ticks == 0


def test_sixty_ticks_pass(sdk_setup):
    from tools.gameloop_harness import run_mission_with_loop
    status, exc, ticks = run_mission_with_loop(
        "Custom.Tutorial.Episode.M1Basic.M1Basic", n_ticks=60
    )
    assert status == "pass"
    assert exc is None
    assert ticks == 60


def test_init_fail_bad_module(sdk_setup):
    from tools.gameloop_harness import run_mission_with_loop
    status, exc, ticks = run_mission_with_loop("nonexistent.MissingMission", n_ticks=60)
    assert status == "init_fail"
    assert isinstance(exc, ModuleNotFoundError)
    assert ticks == 0


def test_loop_fail_bad_timer(sdk_setup):
    """Mission whose timer handler raises is reported as loop_fail."""
    _mod_name = "_test_crashing_mission"
    _mod = types.ModuleType(_mod_name)

    def crash_handler(pObj, pEvent):
        raise RuntimeError("intentional loop crash")

    def Initialize(pMission):
        timer = TGTimer_Create()
        evt = TGEvent()
        evt.SetEventType(App.ET_AI_TIMER)
        evt.SetDestination(pMission)
        timer.SetTimerStart(1.0 / 60.0)
        timer.SetDelay(0.0)
        timer.SetEvent(evt)
        App.g_kTimerManager.AddTimer(timer)
        pMission.AddPythonFuncHandlerForInstance(
            App.ET_AI_TIMER, f"{_mod_name}.crash_handler"
        )

    _mod.Initialize = Initialize
    _mod.crash_handler = crash_handler
    sys.modules[_mod_name] = _mod

    try:
        from tools.gameloop_harness import run_mission_with_loop
        status, exc, ticks = run_mission_with_loop(_mod_name, n_ticks=300)
        assert status == "loop_fail"
        assert isinstance(exc, RuntimeError)
        assert ticks < 300
    finally:
        sys.modules.pop(_mod_name, None)


def test_idempotent(sdk_setup):
    """Two consecutive calls on the same mission produce the same result."""
    from tools.gameloop_harness import run_mission_with_loop
    s1, _, t1 = run_mission_with_loop(
        "Custom.Tutorial.Episode.M1Basic.M1Basic", n_ticks=60
    )
    s2, _, t2 = run_mission_with_loop(
        "Custom.Tutorial.Episode.M1Basic.M1Basic", n_ticks=60
    )
    assert s1 == s2 == "pass"
    assert t1 == t2 == 60


def test_profile_flag_produces_report(sdk_setup, monkeypatch):
    import App
    App._stub_tracker.clear()
    # M1Basic no longer reaches any real stub (the emitter and blinking-light
    # properties it used to hit are implemented), so make one deterministic
    # stub call inside the mission to prove the report plumbing.
    from engine.core.loop import GameLoop
    real_tick = GameLoop.tick

    def _tick_hitting_a_stub(self, *a, **kw):
        App._ProfileProbeStub_Create()
        return real_tick(self, *a, **kw)

    monkeypatch.setattr(GameLoop, "tick", _tick_hitting_a_stub)
    from tools.gameloop_harness import run_mission_with_loop
    status, exc, ticks = run_mission_with_loop(
        "Custom.Tutorial.Episode.M1Basic.M1Basic", n_ticks=60, profile=True
    )
    assert status == "pass"
    rows = App._stub_tracker.report()
    assert len(rows) > 0
    for name, mission_count, total_calls in rows:
        assert isinstance(name, str)
        assert isinstance(mission_count, int)
        assert isinstance(total_calls, int)


def test_no_object_emitter_property_create_stub_rows(sdk_setup):
    """After Task 1-7 land, sovereign / galaxy / nebula / etc. hardpoint
    loads should not produce any ObjectEmitterProperty_Create* stub-tracker
    rows during a real harness run across all discovered missions. Catches
    future regressions where someone removes the factory or the Cast.
    """
    import App
    import tools.mission_harness as mh
    from tools.gameloop_harness import run_mission_with_loop

    App._stub_tracker.clear()
    missions = mh.discover_missions()
    # Hardpoint loads happen during mission Initialize(), before the tick
    # loop. n_ticks=1 keeps the test fast (~few seconds) while still
    # exercising every mission's setup path.
    for name in missions:
        run_mission_with_loop(name, n_ticks=1, profile=True)

    leaks = [
        row for row in App._stub_tracker.report()
        if row[0].startswith("ObjectEmitterProperty_Create")
    ]
    assert leaks == [], f"ObjectEmitterProperty_Create* still in stub tracker: {leaks[:10]}"
