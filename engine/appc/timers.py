from engine.core.ids import TGObject
from engine.appc.events import TGEvent, TGEventManager


class TGTimer(TGObject):
    def __init__(self):
        super().__init__()
        self._start: float = 0.0
        self._delay: float = -1.0
        self._duration: float = -1.0
        self._event: TGEvent | None = None
        self._next_fire: float = 0.0
        self._done: bool = False
        self._fire_pending: bool = False

    def SetTimerStart(self, start: float) -> None:
        self._start = start
        self._next_fire = start

    def GetTimerStart(self) -> float:
        return self._start

    def SetDelay(self, delay: float) -> None:
        self._delay = delay

    def GetDelay(self) -> float:
        return self._delay

    def SetDuration(self, duration: float) -> None:
        self._duration = duration

    def GetDuration(self) -> float:
        return self._duration

    def SetEvent(self, event: TGEvent) -> None:
        self._event = event

    def GetEvent(self) -> TGEvent | None:
        return self._event

    def _advance(self, abs_time: float) -> None:
        """Fire if abs_time has reached or passed _next_fire."""
        if self._done:
            return
        while abs_time >= self._next_fire:
            self._fire_pending = True
            if self._delay <= 0:
                self._done = True
                return
            self._next_fire += self._delay
        # _duration > 0: stop when total manager time reaches the duration limit
        if self._duration > 0 and abs_time >= self._duration:
            self._done = True


def TGTimer_Create() -> TGTimer:
    return TGTimer()


class TGTimerManager:
    def __init__(self, event_manager: TGEventManager):
        self._event_manager = event_manager
        self._timers: dict[int, TGTimer] = {}
        self._time: float = 0.0

    def get_time(self) -> float:
        return self._time

    def AddTimer(self, timer: TGTimer) -> None:
        timer._fire_pending = False
        self._timers[timer.GetObjID()] = timer

    def RemoveTimer(self, timer: "TGTimer | int") -> None:
        # Real Appc's RemoveTimer accepts either a TGTimer object or its
        # GetObjID() int. Conditions/ConditionTimer.py:73 -- the only SDK call
        # site -- passes the int; internal engine callers pass the object.
        obj_id = timer if isinstance(timer, int) else timer.GetObjID()
        self._timers.pop(obj_id, None)

    def DeleteTimer(self, obj_id: int) -> None:
        self._timers.pop(obj_id, None)

    def tick(self, delta: float) -> None:
        self._time += delta
        for obj_id, timer in list(self._timers.items()):
            timer._fire_pending = False
            timer._advance(self._time)
            if timer._fire_pending and timer._event is not None:
                self._event_manager.AddEvent(timer._event)
            if timer._done:
                self._timers.pop(obj_id, None)
