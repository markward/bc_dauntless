"""GameLoop drives RepairSubsystem.Update for every simulated ship."""


def test_gameloop_ticks_repair(monkeypatch):
    from engine.core.loop import GameLoop, TICK_DELTA

    ticked = []

    class _Bay:
        def Update(self, dt):
            ticked.append(dt)

    class _Ship:
        def GetShieldSubsystem(self): return None
        def GetPowerSubsystem(self): return None
        def GetCloakingSubsystem(self): return None
        def GetRepairSubsystem(self): return self._bay
        def __init__(self): self._bay = _Bay()

    # engine.core.loop now imports iter_non_rock_ships (rock-class Task 1):
    # rocks are excluded from this loop's subsystem/articulation walk.
    monkeypatch.setattr("engine.core.loop.iter_non_rock_ships", lambda: [_Ship()])
    GameLoop().tick()
    assert ticked == [TICK_DELTA]
