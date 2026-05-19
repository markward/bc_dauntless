"""End-to-end smoke: GoForward AI drifts a ship along +Y.

Proves the full chain: SDK script loading (Task 1 of prior slice),
AI driver (Task 3 of prior slice), motion integrator (Tasks 1-3
of this slice), SetImpulse alias (Task 2), GameLoop wiring."""
import pytest

import App
from engine.core.loop import GameLoop, TICK_RATE
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass


def _setup_ship_with_goforward(impulse: float = 50.0):
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()
    App.g_kSetManager._sets.clear()

    pSet = App.SetClass_Create()
    pSet.SetName("goforward_smoke")
    App.g_kSetManager._sets["goforward_smoke"] = pSet
    ship = ShipClass()
    pSet.AddObjectToSet(ship, "testship")

    pai = PlainAI_Create(ship, "TestGoForward")
    pai.SetScriptModule("GoForward")
    # GoForward requires a SetImpulse parameter — set it on the script
    # instance directly (SDK pattern: BaseAI.SetRequiredParams configures
    # the surface; mission scripts call SetImpulse(N) before activation).
    inst = pai.GetScriptInstance()
    inst.SetImpulse(impulse)
    ship.SetAI(pai)
    return ship, pai


def test_goforward_drifts_along_plus_y():
    """6 seconds at 50 units/s → ~300 units along ship-forward (+Y).
    Tolerance is loose because FALLBACK_MAX_ACCEL snaps on the first
    tick, so the ship effectively drifts at full speed for ~6 s. The
    first ~1/60 s tick before the AI's first Update is the only
    "ramp" loss: < 1 unit."""
    ship, pai = _setup_ship_with_goforward(impulse=50.0)
    loop = GameLoop()
    loop.advance(TICK_RATE * 6)
    p = ship.GetTranslate()
    assert p.y == pytest.approx(300.0, abs=2.0)
    assert p.x == pytest.approx(0.0, abs=1e-6)
    assert p.z == pytest.approx(0.0, abs=1e-6)


def test_goforward_stays_active():
    """GoForward returns US_ACTIVE forever (mirrors Stay)."""
    ship, pai = _setup_ship_with_goforward(impulse=50.0)
    loop = GameLoop()
    loop.advance(TICK_RATE * 6)
    assert pai.IsActive() == 1


def test_goforward_speed_setpoint_persists():
    """After GoForward's Update fires, _speed_setpoint records 50.0
    along model-forward in MODEL_SPACE frame — the setpoint survives
    across many ticks because the AI is on a 5-second cadence."""
    ship, pai = _setup_ship_with_goforward(impulse=50.0)
    loop = GameLoop()
    loop.advance(TICK_RATE * 2)  # two seconds — well before the next
                                 # 5-second AI tick
    sp = ship.GetSpeedSetpoint()
    assert sp is not None
    assert sp[0] == 50.0
    assert sp[2] == App.PhysicsObjectClass.DIRECTION_MODEL_SPACE
