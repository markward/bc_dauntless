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
    # 60 ticks @ 60 Hz = 1.0s of game time; charge 60/s -> +60
    loop.advance(TICK_RATE)
    assert ship.GetShields().GetCurrentShields(ShieldProperty.FRONT_SHIELDS) == 60.0


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
