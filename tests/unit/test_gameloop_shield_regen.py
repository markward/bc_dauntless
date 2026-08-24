"""GameLoop.tick drives shield regen on registered ships."""
import App
from engine.appc.properties import ShieldProperty
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.core.loop import GameLoop, TICK_RATE


def test_tick_regens_shields_on_set_managed_ship():
    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    App.g_kSetManager.AddSet(pSet, "test_set")

    ship = ShipClass_Create("Galaxy")
    ship.SetScript("test_script")  # makes iter_ships find it
    sp = ShieldProperty("Shield Generator")
    sp.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 100.0)
    sp.SetShieldChargePerSecond(ShieldProperty.FRONT_SHIELDS, 60.0)
    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()
    # Raise shields — regen requires the generator to be powered.
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    # Drain so regen has somewhere to go
    ship.GetShields().SetCurShields(ShieldProperty.FRONT_SHIELDS, 0.0)

    pSet.AddObjectToSet(ship, "ship_1")

    loop = GameLoop()
    shields = ship.GetShields()

    # BC charges shields once per 0.5 s of ACCUMULATED time, not per frame
    # (spec/ShieldFacingDamage.md section 6.1; threshold 0x008E529C). So there
    # is no regen at all until the accumulator first crosses the period.
    loop.advance(TICK_RATE // 4)          # 0.25 s
    assert shields.GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 0.0

    # Crossing the threshold charges for the WHOLE accumulated interval at the
    # authored rate, so the step is ~0.5 s x 60/s = ~30.
    loop.advance(TICK_RATE // 4 + 1)      # ~0.52 s total
    after_first = shields.GetCurrentShields(ShieldProperty.FRONT_SHIELDS)
    assert 29.0 <= after_first <= 32.0, after_first

    # BC RESETS the accumulator on a crossing rather than subtracting the
    # period (section 6.1 step 3), so applied time trails elapsed time by up to
    # one period -- the remainder is not lost, it lands on the next crossing.
    # At 1.5 s elapsed the total is rate x (1.5 - leftover), leftover < 0.5.
    # Deliberately stopped short of 100/60 s so the max-shields clamp does not
    # mask the cadence this test is about.
    elapsed_ticks = TICK_RATE // 2 + 1
    loop.advance((TICK_RATE * 3) // 2 - elapsed_ticks)
    total = shields.GetCurrentShields(ShieldProperty.FRONT_SHIELDS)
    assert 60.0 * (1.5 - 0.5) <= total <= 60.0 * 1.5, total
    assert total < 100.0, "clamped at max; widen the headroom, not the band"


def test_tick_skips_ship_with_no_shield_subsystem():
    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    App.g_kSetManager.AddSet(pSet, "test_set")
    ship = ShipClass_Create("Galaxy")
    ship.SetScript("test_script")
    ship.SetShieldSubsystem(None)  # explicitly no shields (e.g. shuttlecraft)
    pSet.AddObjectToSet(ship, "ship_1")

    loop = GameLoop()
    loop.tick()  # must not raise
