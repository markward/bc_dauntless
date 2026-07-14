"""TimeSliceProcess + PythonMethodProcess shim + scheduler.

Mirrors sdk/Build/scripts/App.py:4468-4511 — the per-tick scheduler the C++
engine uses to drive Python callbacks at game-time or real-time delays
with NORMAL/LOW priority bands (CRITICAL/UNSTOPPABLE are C++-internal,
exposed as constants for SDK code that references them).

Phase 1 model: a single TimeSliceProcessManager owns every registered
process. GameLoop.tick() calls manager.tick(game_time, real_time) once
per 60 Hz frame; the manager fires every process whose next_fire has
been reached, in priority order (UNSTOPPABLE=0 first, LOW=3 last —
lower int == higher priority, matching SDK enum order).

Real Appc's C++ TimeSliceProcess ctor self-registers with the scheduler
and its dtor unregisters. SDK scripts rely on both: they construct a
process, call SetDelay AFTER construction, never call Add() themselves,
and stop the process by dropping the reference. TimeSliceProcess.__init__
mirrors that self-registration here; the manager holds weak references so
dropping the last Python reference unregisters the process.
"""
import weakref


class TimeSliceProcess:
    UNSTOPPABLE = 0
    CRITICAL = 1
    NORMAL = 2
    LOW = 3
    NUM_PRIORITIES = 4

    def __init__(self, manager=None):
        self._priority: int = TimeSliceProcess.NORMAL
        self._delay: float = 0.0
        self._delay_uses_game_time: int = 1
        # None = "not yet scheduled". The manager computes the first fire
        # time on the first tick that sees this process, because the SDK
        # calls SetDelay AFTER construction (Conditions/ConditionFacingToward.py:118).
        self._next_fire = None
        # Real Appc's C++ ctor registers the process with the scheduler; SDK
        # scripts never call Add() themselves. The manager holds a weak ref, so
        # dropping the last Python reference (the SDK's way of stopping a
        # process: `self.pTimerProcess = None`) unregisters it.
        (manager if manager is not None else g_kAIManager).Add(self)

    def SetPriority(self, p) -> None:
        self._priority = int(p)

    def GetPriority(self) -> int:
        return self._priority

    def SetDelay(self, d) -> None:
        self._delay = float(d)

    def GetDelay(self) -> float:
        return self._delay

    def SetDelayUsesGameTime(self, v) -> None:
        self._delay_uses_game_time = 1 if int(v) else 0

    def GetDelayUsesGameTime(self) -> int:
        return self._delay_uses_game_time

    def Update(self) -> None:
        """Default Update — overridden by PythonMethodProcess."""
        pass


class PythonMethodProcess(TimeSliceProcess):
    """SDK signature: pmp.SetFunction(instance, method_name) [2-arg]
    or pmp.SetInstance(instance); pmp.SetFunction(method_name) [1-arg].

    On dispatch, getattr(instance, method_name)(dTimeAvailable) is invoked.
    The two-arg form matches sdk/.../AI/Setup.py; the one-arg + SetInstance
    form is used by HelmMenuHandlers.ProcessWrapper (py:56-70).
    """
    def __init__(self, manager=None):
        super().__init__(manager)
        self._instance = None
        self._method_name: str = ""

    def SetInstance(self, instance) -> None:
        # HelmMenuHandlers.ProcessWrapper:69 — separate instance setter used
        # with the 1-arg SetFunction form.
        self._instance = instance

    def SetFunction(self, instance_or_name, method_name: str = "") -> None:
        if method_name:
            # 2-arg form: SetFunction(instance, "MethodName")
            self._instance = instance_or_name
            self._method_name = method_name
        else:
            # 1-arg form: SetFunction("MethodName") after SetInstance()
            self._method_name = str(instance_or_name)

    def Update(self, dTimeAvailable: float = 0.0) -> None:
        if self._instance is None or not self._method_name:
            return
        # BC passes the process delay as the time-available budget.  The
        # original Appc.dll uses the configured delay as the representative
        # slice length (HelmMenuHandlers.ProcessWrapper.ProcessFunc confirms
        # the signature: def ProcessFunc(self, dTimeAvailable)).  We mirror
        # that here so SDK callbacks receive a meaningful float, not zero.
        getattr(self._instance, self._method_name)(dTimeAvailable)


class TimeSliceProcessManager:
    """Module-level scheduler. One instance lives as g_kAIManager.

    GameLoop ticks the manager once per frame with the current game-time and
    real-time absolute clocks. The manager dispatches every process whose
    next_fire has been reached, lowest priority-int first.

    Processes are held WEAKLY. Real Appc unregisters a process in its C++
    destructor, and SDK scripts rely on that: they stop a periodic check by
    dropping the reference (`self.pTimerProcess = None`,
    Conditions/ConditionFacingToward.py:100). A strong list would keep every
    condition's process firing forever.
    """
    def __init__(self):
        self._procs: list = []          # list[weakref.ref[TimeSliceProcess]]

    def _live(self) -> list:
        """Deref, dropping dead entries. The only way to read the queue."""
        live = []
        keep = []
        for ref in self._procs:
            proc = ref()
            if proc is not None:
                live.append(proc)
                keep.append(ref)
        self._procs = keep
        return live

    def count(self) -> int:
        return len(self._live())

    def Add(self, proc: TimeSliceProcess) -> None:
        if any(p is proc for p in self._live()):
            return
        self._procs.append(weakref.ref(proc))

    def Remove(self, proc: TimeSliceProcess) -> None:
        self._procs = [r for r in self._procs if r() is not None and r() is not proc]

    def tick(self, game_time: float, real_time: float) -> None:
        """Fire every due process in priority order."""
        due = []
        for proc in self._live():
            t = game_time if proc._delay_uses_game_time else real_time
            if proc._next_fire is None:
                # First tick that sees this process: SetDelay has run by now.
                proc._next_fire = t + proc._delay
                continue
            if t >= proc._next_fire:
                due.append((proc._priority, proc))
        due.sort(key=lambda pair: pair[0])
        for _prio, proc in due:
            proc.Update(proc._delay)
            if proc._delay > 0:
                # Advance rather than restamp: no drift under variable ticks.
                proc._next_fire += proc._delay
            else:
                # One-shot: never fires again unless SetDelay re-arms it.
                proc._next_fire = float("inf")


# Module-level scheduler instance — App.py re-exports as g_kAIManager.
g_kAIManager = TimeSliceProcessManager()
