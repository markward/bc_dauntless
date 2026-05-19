"""End-to-end smoke: Stay AI ticks at 5 s cadence and writes zero motion setpoints.

Proves Tasks 1+3+4+5 work together: real script loading (Task 1),
tree-walk driver (Task 3), ShipClass motion stubs (Task 4), GameLoop
wiring (Task 5). Task 2 (TimeSliceProcess) is exercised by its own unit
tests — Stay doesn't use it.
"""
import App
from engine.core.loop import GameLoop, TICK_RATE
from engine.appc.ai import PlainAI_Create
from engine.appc.ships import ShipClass


def _setup_ship_with_stay():
    """Build a fresh set, place a ship with PlainAI('Stay') attached,
    and return (ship, plain_ai)."""
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()
    App.g_kSetManager._sets.clear()

    pSet = App.SetClass_Create()
    pSet.SetName("stay_smoke")
    App.g_kSetManager._sets["stay_smoke"] = pSet
    ship = ShipClass()
    pSet.AddObjectToSet(ship, "testship")

    pai = PlainAI_Create(ship, "TestStay")
    pai.SetScriptModule("Stay")
    ship.SetAI(pai)
    return ship, pai


def test_stay_update_fires_at_five_second_cadence():
    """Run 11 in-game seconds; Stay.Update should fire at t≈0, 5, 10 → 3 calls."""
    ship, pai = _setup_ship_with_stay()
    stay = pai.GetScriptInstance()

    # Decorate Update so we can count calls without touching engine internals.
    original_update = stay.Update
    stay.call_count = 0
    def counting_update():
        stay.call_count += 1
        return original_update()
    stay.Update = counting_update

    loop = GameLoop()
    loop.advance(TICK_RATE * 11)  # 11 seconds at 60 Hz

    assert stay.call_count == 3, f"expected 3 fires (t=0,5,10), got {stay.call_count}"


def test_stay_zeros_ship_motion_setpoints():
    """After Stay runs, the ship's speed setpoint and target angular velocity
    are both zero — Stay's contract is 'don't move, don't turn.'"""
    ship, pai = _setup_ship_with_stay()
    loop = GameLoop()
    loop.advance(TICK_RATE * 6)  # one full Update cycle

    sp = ship.GetSpeedSetpoint()
    assert sp is not None, "Stay never called SetSpeed"
    assert sp[0] == 0.0, f"Stay should drive speed to 0, got {sp[0]}"

    av = ship.GetTargetAngularVelocitySetpoint()
    assert av is not None, "Stay never called SetTargetAngularVelocityDirect"
    assert (av.x, av.y, av.z) == (0.0, 0.0, 0.0)


def test_stay_ai_remains_active():
    """Stay returns US_ACTIVE forever; PlainAI.IsActive should stay 1."""
    ship, pai = _setup_ship_with_stay()
    loop = GameLoop()
    loop.advance(TICK_RATE * 11)
    assert pai.IsActive() == 1
