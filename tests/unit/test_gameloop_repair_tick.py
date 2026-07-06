"""GameLoop drives RepairSubsystem.Update for every simulated ship."""


def test_gameloop_ticks_repair(monkeypatch):
    from engine.core.loop import GameLoop, TICK_DELTA
    import engine.appc.ship_iter as ship_iter

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

    monkeypatch.setattr("engine.core.loop.iter_ships", lambda: [_Ship()])
    GameLoop().tick()
    assert ticked == [TICK_DELTA]
