import App

TICK_RATE = 60
TICK_DELTA = 1.0 / TICK_RATE


class GameLoop:
    """Drives App.g_kTimerManager and App.g_kRealtimeTimerManager at 60 Hz.

    Phase 1: both managers advance at the same fixed rate (no time scaling).
    """

    def tick(self) -> None:
        App.g_kTimerManager.tick(TICK_DELTA)
        App.g_kRealtimeTimerManager.tick(TICK_DELTA)

    def advance(self, n: int) -> None:
        for _ in range(n):
            self.tick()

    @property
    def game_time(self) -> float:
        return App.g_kTimerManager.get_time()
