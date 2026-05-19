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
"""


class TimeSliceProcess:
    UNSTOPPABLE = 0
    CRITICAL = 1
    NORMAL = 2
    LOW = 3
    NUM_PRIORITIES = 4

    def __init__(self):
        self._priority: int = TimeSliceProcess.NORMAL
        self._delay: float = 0.0
        self._delay_uses_game_time: int = 1
        # Set on first Add() by the manager — absolute time of next fire
        # in the relevant time stream.
        self._next_fire: float = 0.0

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
    """SDK signature: pmp.SetFunction(instance, method_name).

    On dispatch, getattr(instance, method_name)() is invoked. The two-arg
    form matches sdk/.../AI/Setup.py and is the only form Python-side SDK
    code actually uses.
    """
    def __init__(self):
        super().__init__()
        self._instance = None
        self._method_name: str = ""

    def SetFunction(self, instance, method_name: str) -> None:
        self._instance = instance
        self._method_name = method_name

    def Update(self) -> None:
        if self._instance is None or not self._method_name:
            return
        getattr(self._instance, self._method_name)()


class TimeSliceProcessManager:
    """Module-level scheduler. One instance lives as g_kAIManager.

    GameLoop ticks the manager once per frame with the current game-time
    and real-time absolute clocks. The manager dispatches every process
    whose next_fire has been reached, lowest priority-int first.
    """
    def __init__(self):
        self._procs: list = []

    def Add(self, proc: TimeSliceProcess) -> None:
        # Snap next_fire to the current time stream's "now + delay" on
        # registration so SetDelay before Add behaves intuitively.
        # Manager doesn't know "now" here, so use 0 — manager.tick() will
        # interpret next_fire == 0 as "fire on the first tick where the
        # relevant clock reaches the configured delay."
        if proc not in self._procs:
            proc._next_fire = proc._delay
            self._procs.append(proc)

    def Remove(self, proc: TimeSliceProcess) -> None:
        if proc in self._procs:
            self._procs.remove(proc)

    def tick(self, game_time: float, real_time: float) -> None:
        """Fire every due process in priority order."""
        due = []
        for proc in self._procs:
            t = game_time if proc._delay_uses_game_time else real_time
            if t >= proc._next_fire:
                due.append((proc._priority, t, proc))
        due.sort(key=lambda triple: triple[0])
        for _prio, t_at_fire, proc in due:
            proc.Update()
            # Reschedule at next_fire += delay (avoids drift under
            # variable tick lengths; same semantics as TGTimer._advance).
            if proc._delay > 0:
                proc._next_fire += proc._delay
            else:
                # One-shot: push next_fire far enough out that the process
                # never fires again unless SetDelay re-arms it.
                proc._next_fire = float("inf")


# Module-level scheduler instance — App.py re-exports as g_kAIManager.
g_kAIManager = TimeSliceProcessManager()
