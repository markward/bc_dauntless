"""A PythonMethodProcess stops when its owner goes, with no collector pass.

The SDK keeps a process on its owner and the owner is the process's instance
(Bridge/PowerDisplay.py:73-98): a reference cycle. BC's Python 1.5 has no
cyclic collector, so dropping the owner stops the process at once; here the
process holds its instance weakly (strongly if it cannot be weakly
referenced), so the same drop works without waiting for gc. Every test
disables the collector.
"""
import gc
import weakref

import pytest

from engine.appc.time_slice import PythonMethodProcess, TimeSliceProcessManager


@pytest.fixture(autouse=True)
def _no_gc():
    gc.disable()
    try:
        yield
    finally:
        gc.enable()


class _Wrapper:
    """The ProcessWrapper shape: owner holds the process, process holds owner."""
    def __init__(self, mgr, calls, two_arg=False):
        self.calls = calls
        self.p = PythonMethodProcess(manager=mgr)
        if two_arg:
            self.p.SetFunction(self, "Fire")
        else:
            self.p.SetInstance(self)
            self.p.SetFunction("Fire")
        self.p.SetDelay(0.5)

    def Fire(self, dt):
        self.calls.append(dt)


def _run_drop_test(two_arg):
    mgr = TimeSliceProcessManager()
    calls = []
    assert not gc.isenabled()
    owner = _Wrapper(mgr, calls, two_arg=two_arg)
    mgr.tick(0.0, 0.0)
    mgr.tick(0.5, 0.5)
    assert len(calls) == 1
    assert mgr.count() == 1
    del owner
    assert mgr.count() == 0
    mgr.tick(1.0, 1.0)
    mgr.tick(1.5, 1.5)
    assert len(calls) == 1


def test_wrapper_shape_stops_when_owner_dropped():
    _run_drop_test(two_arg=False)


def test_two_arg_form_stops_when_owner_dropped():
    _run_drop_test(two_arg=True)


def test_live_owner_keeps_firing():
    mgr = TimeSliceProcessManager()
    calls = []
    owner = _Wrapper(mgr, calls)
    mgr.tick(0.0, 0.0)
    for i in range(1, 5):
        mgr.tick(0.5 * i, 0.5 * i)
    assert len(calls) == 4
    assert owner is not None


def test_non_weakrefable_instance_still_fires():
    class Slotted:
        __slots__ = ("calls",)

        def Fire(self, dt):
            self.calls += 1

    mgr = TimeSliceProcessManager()
    inst = Slotted()
    inst.calls = 0
    with pytest.raises(TypeError):
        weakref.ref(inst)       # the premise: this exercises the strong fallback
    p = PythonMethodProcess(manager=mgr)
    p.SetInstance(inst)
    p.SetFunction("Fire")
    p.SetDelay(0.5)
    mgr.tick(0.0, 0.0)
    mgr.tick(0.5, 0.5)
    assert inst.calls == 1


def test_reassigned_instance_releases_the_old_one():
    # A replacement guard (the old instance is not kept), not evidence for the
    # weak hold: it passed before the weak reference too.
    class Target:
        def __init__(self):
            self.calls = 0

        def Fire(self, dt):
            self.calls += 1

    mgr = TimeSliceProcessManager()
    a, b = Target(), Target()
    p = PythonMethodProcess(manager=mgr)
    p.SetInstance(a)
    p.SetInstance(b)
    p.SetFunction("Fire")
    p.SetDelay(0.5)
    ref_a = weakref.ref(a)
    del a
    assert ref_a() is None
    mgr.tick(0.0, 0.0)
    mgr.tick(0.5, 0.5)
    assert b.calls == 1


def test_owner_dropped_mid_tick():
    mgr = TimeSliceProcessManager()
    fired = []
    holder = {}

    class First:
        def __init__(self):
            self.p = PythonMethodProcess(manager=mgr)
            self.p.SetInstance(self)
            self.p.SetFunction("Fire")
            self.p.SetDelay(0.5)
            self.p.SetPriority(PythonMethodProcess.CRITICAL)

        def Fire(self, dt):
            fired.append("first")
            holder.pop("second")

    class Second:
        def __init__(self):
            self.p = PythonMethodProcess(manager=mgr)
            self.p.SetInstance(self)
            self.p.SetFunction("Fire")
            self.p.SetDelay(0.5)
            self.p.SetPriority(PythonMethodProcess.LOW)

        def Fire(self, dt):
            fired.append("second")

    first = First()
    holder["second"] = Second()
    mgr.tick(0.0, 0.0)
    mgr.tick(0.5, 0.5)
    assert fired == ["first"]
    assert first is not None


def test_owner_dropping_itself_in_its_callback():
    mgr = TimeSliceProcessManager()
    holder = {}
    calls = []

    class SelfDrop(_Wrapper):
        def Fire(self, dt):
            calls.append(dt)
            holder.pop("owner")

    holder["owner"] = SelfDrop(mgr, calls)
    mgr.tick(0.0, 0.0)
    mgr.tick(0.5, 0.5)
    assert len(calls) == 1
    assert mgr.count() == 0
    mgr.tick(1.0, 1.0)
    assert len(calls) == 1


def _power_display_processes():
    from engine.appc import time_slice
    import Bridge.PowerDisplay as pd
    out = []
    for p in time_slice.g_kAIManager._live():
        resolve = getattr(p, "_resolve_instance", None)
        if resolve is not None and isinstance(resolve(), pd.ProcessWrapper):
            out.append(p)
    return out


def test_sdk_power_display_one_refresh_process_per_load():
    from tests.helpers import headless_mission as hm
    assert not gc.isenabled()
    for name in ("Maelstrom.Episode3.E3M2.E3M2", "Maelstrom.Episode6.E6M1.E6M1"):
        hm.load(name)
        hm.tick(5.0)
        assert len(_power_display_processes()) == 1, name
