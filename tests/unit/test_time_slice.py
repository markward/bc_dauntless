from engine.appc.time_slice import (
    TimeSliceProcess, PythonMethodProcess, TimeSliceProcessManager,
)

# One 60 Hz frame. BC runs a process on the first frame PAST its delay since
# its last run, never on a frame landing exactly on it (stbc-oracle sched
# probe: 301 frames for a 5 s process at exact 60 Hz), so a tick meant to fire
# a process sits one frame past the delay.
F = 1.0 / 60.0


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
    on the manager dispatches by calling getattr(instance, method_name)(dTimeAvailable)."""
    class Holder:
        def __init__(self):
            self.calls = 0
        def Bump(self, _dt=0.0):
            self.calls += 1

    h = Holder()
    pmp = PythonMethodProcess()
    pmp.SetFunction(h, "Bump")
    pmp.SetDelay(0.1)
    pmp.SetDelayUsesGameTime(1)

    mgr = TimeSliceProcessManager()
    mgr.Add(pmp)
    mgr.tick(game_time=0.0, real_time=0.0)  # first tick just arms next_fire
    mgr.tick(game_time=0.05, real_time=0.05)
    assert h.calls == 0
    mgr.tick(game_time=0.11, real_time=0.11)
    assert h.calls == 1


def test_priority_order_normal_runs_before_low():
    order = []
    class H:
        def __init__(self, tag): self.tag = tag
        def Go(self, _dt=0.0): order.append(self.tag)

    hn = H("N"); n = PythonMethodProcess(); n.SetFunction(hn, "Go"); n.SetDelay(0.1)
    n.SetDelayUsesGameTime(1); n.SetPriority(TimeSliceProcess.NORMAL)
    hl = H("L"); l = PythonMethodProcess(); l.SetFunction(hl, "Go"); l.SetDelay(0.1)
    l.SetDelayUsesGameTime(1); l.SetPriority(TimeSliceProcess.LOW)

    mgr = TimeSliceProcessManager()
    mgr.Add(l); mgr.Add(n)  # add LOW first to prove ordering by priority
    mgr.tick(game_time=0.0, real_time=0.0)  # first tick just arms next_fire
    mgr.tick(game_time=0.11, real_time=0.11)
    assert order == ["N", "L"]


def test_game_time_vs_real_time_isolated():
    """Only the game-time process fires when game_time advances; the
    real-time process is dormant until real_time catches up."""
    fired = []
    class H:
        def __init__(self, tag): self.tag = tag
        def Go(self, _dt=0.0): fired.append(self.tag)

    hg = H("G"); g = PythonMethodProcess(); g.SetFunction(hg, "Go"); g.SetDelay(1.0)
    g.SetDelayUsesGameTime(1)
    hr = H("R"); r = PythonMethodProcess(); r.SetFunction(hr, "Go"); r.SetDelay(1.0)
    r.SetDelayUsesGameTime(0)

    mgr = TimeSliceProcessManager()
    mgr.Add(g); mgr.Add(r)
    mgr.tick(game_time=0.0, real_time=0.0)  # first tick just arms next_fire
    mgr.tick(game_time=1.0 + F, real_time=0.0)
    assert fired == ["G"]
    mgr.tick(game_time=1.0 + F, real_time=1.0 + F)
    assert fired == ["G", "R"]


def test_reschedule_after_fire():
    """After dispatch the process re-arms one delay after that run."""
    h_calls = []
    class H:
        def Go(self, _dt=0.0): h_calls.append(1)

    h = H(); p = PythonMethodProcess(); p.SetFunction(h, "Go"); p.SetDelay(1.0)
    p.SetDelayUsesGameTime(1)
    mgr = TimeSliceProcessManager()
    mgr.Add(p)
    mgr.tick(game_time=0.0, real_time=0.0)  # first tick just arms next_fire
    mgr.tick(game_time=1.0 + F, real_time=0.0)
    mgr.tick(game_time=1.5, real_time=0.0)  # not due yet
    mgr.tick(game_time=2.0 + 2 * F, real_time=0.0)
    assert len(h_calls) == 2


def test_remove_stops_dispatch():
    fired = []
    class H:
        def Go(self, _dt=0.0): fired.append(1)
    h = H(); p = PythonMethodProcess(); p.SetFunction(h, "Go"); p.SetDelay(0.5)
    p.SetDelayUsesGameTime(1)
    mgr = TimeSliceProcessManager()
    mgr.Add(p)
    mgr.tick(game_time=0.0, real_time=0.0)  # first tick just arms next_fire
    mgr.Remove(p)
    mgr.tick(game_time=1.0, real_time=0.0)
    assert fired == []


def test_bare_time_slice_process_update_does_not_raise_when_ticked():
    """A bare TimeSliceProcess (or any subclass that inherits Update rather
    than overriding it) self-registers at construction. The manager
    dispatches every live process as proc.Update(proc._delay); the base
    Update must accept that argument or GameLoop.tick() raises TypeError
    every frame for any such process left registered."""
    mgr = TimeSliceProcessManager()
    p = TimeSliceProcess(manager=mgr)
    p.SetDelay(0.1)
    p.SetDelayUsesGameTime(1)

    mgr.tick(game_time=0.0, real_time=0.0)  # first tick just arms next_fire
    mgr.tick(game_time=0.2, real_time=0.2)  # due: dispatches Update(0.1)


def test_sdk_convention_one_arg_form_receives_float_time_budget():
    """BC SDK convention: SetInstance(obj) + SetFunction("MethodName") [1-arg form].

    ProcessFunc(self, dTimeAvailable) — as in HelmMenuHandlers.ProcessWrapper:74 —
    must receive a float positional arg on each dispatch.  The value passed is
    the process delay (the configured time-slice budget).
    """
    received = []

    class ProcessWrapper:
        def ProcessFunc(self, dTimeAvailable):
            received.append(dTimeAvailable)

    wrapper = ProcessWrapper()
    pmp = PythonMethodProcess()
    pmp.SetInstance(wrapper)
    pmp.SetFunction("ProcessFunc")
    pmp.SetDelay(0.25)
    pmp.SetDelayUsesGameTime(1)

    mgr = TimeSliceProcessManager()
    mgr.Add(pmp)
    mgr.tick(game_time=0.0, real_time=0.0)  # first tick just arms next_fire
    mgr.tick(game_time=0.25 + F, real_time=0.0)

    assert len(received) == 1
    assert isinstance(received[0], float)
    assert received[0] == 0.25  # delay is passed as dTimeAvailable


def test_sdk_convention_two_arg_form_receives_float_time_budget():
    """2-arg SetFunction(instance, "MethodName") form also delivers the float."""
    received = []

    class Obj:
        def Update(self, dTimeAvailable):
            received.append(dTimeAvailable)

    obj = Obj()
    pmp = PythonMethodProcess()
    pmp.SetFunction(obj, "Update")
    pmp.SetDelay(0.5)
    pmp.SetDelayUsesGameTime(1)

    mgr = TimeSliceProcessManager()
    mgr.Add(pmp)
    mgr.tick(game_time=0.0, real_time=0.0)  # first tick just arms next_fire
    mgr.tick(game_time=0.5 + F, real_time=0.0)

    assert len(received) == 1
    assert isinstance(received[0], float)
    assert received[0] == 0.5


def test_bc_spacing_at_exact_60hz_is_one_frame_past_the_delay():
    """Measured on the original (stbc-oracle sched probe, native Windows,
    HelmMenuHandlers.CollisionAlertCheck, lockstep 1 and 2): a 5 s process
    runs every 301 frames at exact 60 Hz (5.0167 s, n=25), never catching up,
    so the collision alarm's "5 s since the last alarm" passes every check."""
    calls = []

    class H:
        def Go(self, _dt=0.0):
            calls.append(t[0])

    h = H(); p = PythonMethodProcess(); p.SetFunction(h, "Go"); p.SetDelay(5.0)
    p.SetDelayUsesGameTime(1)
    mgr = TimeSliceProcessManager()
    mgr.Add(p)
    t = [0.0]
    for i in range(60 * 31):                    # summed 1/60 steps, as the game loop does
        mgr.tick(game_time=t[0], real_time=t[0])
        t[0] += 1.0 / 60.0
    gaps = [round((b - a) * 60.0) for a, b in zip(calls, calls[1:])]
    assert gaps and all(g == 301 for g in gaps)
    assert round(calls[0] * 60.0) == 301


def test_bc_spacing_under_uneven_frames_never_runs_early():
    """In real time the original's 5 s process ran 5.000-5.012 s apart: the
    first frame past the delay, so never under it and less than a frame over."""
    import random
    rng = random.Random(7)
    calls = []

    class H:
        def Go(self, _dt=0.0):
            calls.append(now[0])

    h = H(); p = PythonMethodProcess(); p.SetFunction(h, "Go"); p.SetDelay(5.0)
    p.SetDelayUsesGameTime(1)
    mgr = TimeSliceProcessManager()
    mgr.Add(p)
    now = [0.0]
    worst = 0.0
    while now[0] < 120.0:
        mgr.tick(game_time=now[0], real_time=now[0])
        step = rng.uniform(0.010, 0.020)
        worst = max(worst, step)
        now[0] += step
    gaps = [b - a for a, b in zip(calls, calls[1:])]
    assert gaps and min(gaps) > 5.0 and max(gaps) <= 5.0 + worst + 1e-9


def test_add_does_not_scan_the_process_list():
    """Add used to walk every registered process twice (a liveness sweep and
    an identity scan), so a burst of timer starts cost the square of the
    queue: SDK ConditionIncomingTorps starts one per instance per torpedo
    launch. Counted, not timed."""
    from engine.appc import time_slice

    mgr = TimeSliceProcessManager()
    kept = [TimeSliceProcess(manager=mgr) for _ in range(200)]

    class _CountingList(list):
        walks = 0

        def __iter__(self):
            _CountingList.walks += 1
            return super().__iter__()

    mgr._procs = _CountingList(mgr._procs)
    extra = TimeSliceProcess(manager=mgr)
    mgr.Add(extra)                     # a repeat Add stays a no-op
    assert _CountingList.walks == 0
    assert mgr.count() == 201
    del kept


def test_add_after_remove_registers_again():
    mgr = TimeSliceProcessManager()
    proc = TimeSliceProcess(manager=mgr)
    mgr.Remove(proc)
    assert mgr.count() == 0
    mgr.Add(proc)
    mgr.Add(proc)
    assert mgr.count() == 1


def test_clear_lets_a_surviving_process_register_again():
    mgr = TimeSliceProcessManager()
    proc = TimeSliceProcess(manager=mgr)
    mgr.clear()
    assert mgr.count() == 0
    mgr.Add(proc)
    assert mgr.count() == 1
