"""GameLoop's subsystem stage repairs every simulated ship.

A real ship in a real set (the native stage walks the sets itself; patching
the roster to feed it a fake ship now raises, tests/unit/
test_native_subsystems_driver.py::test_a_patched_roster_raises): one
GameLoop tick repairs its queued damage by exactly one tick's share.
"""
import App

from engine.appc import effect_queue


def test_gameloop_ticks_repair():
    from engine.appc.properties import RepairSubsystemProperty
    from engine.appc.ships import ShipClass_Create
    from engine.appc.sets import SetClass
    from engine.core.loop import GameLoop, TICK_DELTA

    pset = SetClass()
    App.g_kSetManager.AddSet(pset, "RepairTickSet")
    try:
        ship = ShipClass_Create("Repaired")
        prop = RepairSubsystemProperty("Engineering")
        prop.SetMaxRepairPoints(60.0)
        prop.SetNumRepairTeams(3)
        bay = ship.GetRepairSubsystem()
        bay.SetProperty(prop)
        bay.SetMaxCondition(1000.0)
        bay.SetCondition(1000.0)
        sensors = ship.GetSensorSubsystem()
        sensors.SetMaxCondition(8000.0)
        sensors.SetCondition(4000.0)                # damage: queued
        effect_queue.boundary()
        assert bay.IsBeingRepaired(sensors) == 1
        pset.AddObjectToSet(ship, "Repaired")

        loop = GameLoop()
        loop.tick()
        # raw = 60 * 1.0 * dt, one item of complexity 1.0.
        complexity = sensors.GetRepairComplexity()
        assert sensors.GetCondition() == 4000.0 + (
            60.0 * 1.0 * TICK_DELTA) / 1.0 / (
            complexity if complexity > 0.0 else 1.0)
    finally:
        App.g_kSetManager.DeleteSet("RepairTickSet")
