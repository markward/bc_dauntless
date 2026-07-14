"""A TimeSliceProcess registers itself with g_kAIManager at construction.

Real Appc's C++ ctor self-registers and its dtor unregisters; SDK scripts rely
on both (Conditions/ConditionFacingToward.py:118-121 constructs a
PythonMethodProcess, calls SetDelay AFTER construction, and never calls Add;
it stops the process by dropping the reference).
"""
import gc

from engine.appc.time_slice import PythonMethodProcess, TimeSliceProcessManager


class _Counter:
    def __init__(self):
        self.calls = 0

    def PeriodicCheck(self, dTimeAvailable):
        self.calls += 1


def test_process_self_registers_and_fires_on_its_delay():
    mgr = TimeSliceProcessManager()
    target = _Counter()

    proc = PythonMethodProcess(manager=mgr)
    proc.SetInstance(target)
    proc.SetFunction("PeriodicCheck")
    proc.SetDelay(0.5)          # NOTE: set AFTER construction, as the SDK does

    assert mgr.count() == 1

    mgr.tick(game_time=0.0, real_time=0.0)
    assert target.calls == 0, "must not fire before its delay has elapsed"

    mgr.tick(game_time=0.4, real_time=0.4)
    assert target.calls == 0

    mgr.tick(game_time=0.5, real_time=0.5)
    assert target.calls == 1, "first fire is at construction-time + delay"

    mgr.tick(game_time=1.0, real_time=1.0)
    assert target.calls == 2, "re-arms every delay"


def test_dropping_the_last_reference_unregisters_the_process():
    mgr = TimeSliceProcessManager()
    target = _Counter()

    proc = PythonMethodProcess(manager=mgr)
    proc.SetInstance(target)
    proc.SetFunction("PeriodicCheck")
    proc.SetDelay(0.1)
    assert mgr.count() == 1

    del proc
    gc.collect()

    assert mgr.count() == 0, "manager must hold a weak ref, not pin the process"
    mgr.tick(game_time=5.0, real_time=5.0)
    assert target.calls == 0
