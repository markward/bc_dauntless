from engine.appc.time_slice import (
    TimeSliceProcess, PythonMethodProcess, TimeSliceProcessManager,
)


def test_priority_constants_distinct():
    p = {TimeSliceProcess.UNSTOPPABLE, TimeSliceProcess.CRITICAL,
         TimeSliceProcess.NORMAL, TimeSliceProcess.LOW}
    assert len(p) == 4


def test_delay_round_trip():
    proc = TimeSliceProcess()
    proc.SetDelay(2.5)
    assert proc.GetDelay() == 2.5


def test_priority_round_trip():
    proc = TimeSliceProcess()
    proc.SetPriority(TimeSliceProcess.LOW)
    assert proc.GetPriority() == TimeSliceProcess.LOW


def test_delay_uses_game_time_round_trip():
    proc = TimeSliceProcess()
    proc.SetDelayUsesGameTime(1)
    assert proc.GetDelayUsesGameTime() == 1
    proc.SetDelayUsesGameTime(0)
    assert proc.GetDelayUsesGameTime() == 0


def test_python_method_process_set_function_invokes_method():
    """SDK signature: pmp.SetFunction(instance, method_name). Update()
    on the manager dispatches by calling getattr(instance, method_name)()."""
    class Holder:
        def __init__(self):
            self.calls = 0
        def Bump(self):
            self.calls += 1

    h = Holder()
    pmp = PythonMethodProcess()
    pmp.SetFunction(h, "Bump")
    pmp.SetDelay(0.1)
    pmp.SetDelayUsesGameTime(1)

    mgr = TimeSliceProcessManager()
    mgr.Add(pmp)
    mgr.tick(game_time=0.05, real_time=0.05)
    assert h.calls == 0
    mgr.tick(game_time=0.11, real_time=0.11)
    assert h.calls == 1


def test_priority_order_normal_runs_before_low():
    order = []
    class H:
        def __init__(self, tag): self.tag = tag
        def Go(self): order.append(self.tag)

    n = PythonMethodProcess(); n.SetFunction(H("N"), "Go"); n.SetDelay(0.1)
    n.SetDelayUsesGameTime(1); n.SetPriority(TimeSliceProcess.NORMAL)
    l = PythonMethodProcess(); l.SetFunction(H("L"), "Go"); l.SetDelay(0.1)
    l.SetDelayUsesGameTime(1); l.SetPriority(TimeSliceProcess.LOW)

    mgr = TimeSliceProcessManager()
    mgr.Add(l); mgr.Add(n)  # add LOW first to prove ordering by priority
    mgr.tick(game_time=0.11, real_time=0.11)
    assert order == ["N", "L"]


def test_game_time_vs_real_time_isolated():
    """Only the game-time process fires when game_time advances; the
    real-time process is dormant until real_time catches up."""
    fired = []
    class H:
        def __init__(self, tag): self.tag = tag
        def Go(self): fired.append(self.tag)

    g = PythonMethodProcess(); g.SetFunction(H("G"), "Go"); g.SetDelay(1.0)
    g.SetDelayUsesGameTime(1)
    r = PythonMethodProcess(); r.SetFunction(H("R"), "Go"); r.SetDelay(1.0)
    r.SetDelayUsesGameTime(0)

    mgr = TimeSliceProcessManager()
    mgr.Add(g); mgr.Add(r)
    mgr.tick(game_time=1.0, real_time=0.0)
    assert fired == ["G"]
    mgr.tick(game_time=1.0, real_time=1.0)
    assert fired == ["G", "R"]


def test_reschedule_after_fire():
    """After dispatch the process re-arms at next_fire += delay."""
    h_calls = []
    class H:
        def Go(self): h_calls.append(1)

    p = PythonMethodProcess(); p.SetFunction(H(), "Go"); p.SetDelay(1.0)
    p.SetDelayUsesGameTime(1)
    mgr = TimeSliceProcessManager()
    mgr.Add(p)
    mgr.tick(game_time=1.0, real_time=0.0)
    mgr.tick(game_time=1.5, real_time=0.0)  # not due yet
    mgr.tick(game_time=2.0, real_time=0.0)
    assert len(h_calls) == 2


def test_remove_stops_dispatch():
    fired = []
    class H:
        def Go(self): fired.append(1)
    p = PythonMethodProcess(); p.SetFunction(H(), "Go"); p.SetDelay(0.5)
    p.SetDelayUsesGameTime(1)
    mgr = TimeSliceProcessManager()
    mgr.Add(p)
    mgr.Remove(p)
    mgr.tick(game_time=1.0, real_time=0.0)
    assert fired == []
