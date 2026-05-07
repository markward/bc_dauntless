from engine.core.ids import TGObject
from engine.appc.events import TGEvent, TGEventManager


class TGTimer(TGObject):
    def __init__(self):
        super().__init__()
        self._start: float = 0.0
        self._delay: float = 0.0
        self._duration: float = -1.0
        self._event: TGEvent | None = None
        self._elapsed: float = 0.0
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

    def tick(self, delta: float) -> None:
        if self._done:
            return
        self._elapsed += delta
        while self._elapsed >= self._next_fire:
            if self._event is not None:
                self._fire_pending = True
            if self._delay <= 0:
                self._done = True
                break
            self._next_fire += self._delay
        # duration > 0: stop when total elapsed time reaches the duration limit
        if self._duration > 0 and self._elapsed >= self._duration:
            self._done = True


def TGTimer_Create() -> TGTimer:
    return TGTimer()


class TGTimerManager:
    def __init__(self, event_manager: TGEventManager):
        self._event_manager = event_manager
        self._timers: dict[int, TGTimer] = {}

    def AddTimer(self, timer: TGTimer) -> None:
        timer._fire_pending = False
        self._timers[timer.GetObjID()] = timer

    def RemoveTimer(self, timer: TGTimer) -> None:
        self._timers.pop(timer.GetObjID(), None)

    def DeleteTimer(self, obj_id: int) -> None:
        self._timers.pop(obj_id, None)

    def tick(self, delta: float) -> None:
        to_remove = []
        for obj_id, timer in list(self._timers.items()):
            timer._fire_pending = False
            timer.tick(delta)
            if timer._fire_pending and timer._event is not None:
                self._event_manager.AddEvent(timer._event)
            if timer._done:
                to_remove.append(obj_id)
        for obj_id in to_remove:
            self._timers.pop(obj_id, None)
