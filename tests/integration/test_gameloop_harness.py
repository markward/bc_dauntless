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
