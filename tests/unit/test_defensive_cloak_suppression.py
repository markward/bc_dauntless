"""tick_all_ai must skip the SDK AI of a ship the defensive-cloak controller has
marked DEFENSIVE (so the SDK CloakShip/focus lifecycle doesn't fight the engine
controller). Normal ships still tick."""
import App
from engine.appc.ships import ShipClass
from engine.appc.subsystems import CloakingSubsystem, HullSubsystem
from engine.appc import defensive_cloak
from engine.appc.ai_driver import tick_all_ai


class _CountingAI:
    """Minimal AI marker whose GetShip()/tick is observable."""
    def __init__(self, ship):
        self._ship = ship
        self.ticks = 0
    def GetShip(self):
        return self._ship


def _reset():
    defensive_cloak.reset_defensive_cloak_state()
    App.g_kSetManager._sets.clear()


def test_defensive_ship_sdk_ai_is_suppressed(monkeypatch):
    _reset()
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass(); pSet.AddObjectToSet(ship, "S1")
    ai = _CountingAI(ship); ship.SetAI(ai)

    # Count tick_ai dispatches per ship via monkeypatch on the driver's tick_ai.
    import engine.appc.ai_driver as drv
    seen = []
    monkeypatch.setattr(drv, "tick_ai", lambda a, game_time: seen.append(a) or 0)

    # NORMAL: ship's AI is ticked.
    tick_all_ai(game_time=0.0)
    assert ai in seen

    # DEFENSIVE: ship's AI is skipped.
    defensive_cloak._defensive.add(id(ship))
    seen.clear()
    tick_all_ai(game_time=1.0)
    assert ai not in seen
    _reset()
