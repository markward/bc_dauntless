"""SetupProperties copies SensorProperty fields onto the SensorSubsystem."""
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import SensorProperty


def test_sensor_property_propagation():
    ship = ShipClass_Create("Galaxy")
    sp = SensorProperty("Sensor Array")
    sp.SetMaxCondition(8000.0)
    sp.SetNormalPowerPerSecond(100.0)
    sp.SetBaseSensorRange(2000.0)
    sp.SetMaxProbes(10)

    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()

    sensor = ship.GetSensorSubsystem()
    assert sensor is not None
    assert sensor.GetMaxCondition() == 8000.0
    assert sensor.GetNormalPowerPerSecond() == 100.0
    assert sensor.GetBaseSensorRange() == 2000.0
    assert sensor.GetMaxProbes() == 10


def test_sensor_disabled_percentage_propagates_from_hardpoint():
    """Regression: the sensor's disabled threshold must come from the hardpoint
    (Galaxy sensor = 0.50), not the engine default 0.25. Otherwise the AI /
    detection 'offline' gate disagrees with the rest of the game and the UI:
    a sensor the game shows as disabled at <=50% would still 'see' for us."""
    from engine.appc.sensor_detection import effective_sensor_range

    ship = ShipClass_Create("Galaxy")
    sp = SensorProperty("Sensor Array")
    sp.SetMaxCondition(100.0)
    sp.SetBaseSensorRange(2000.0)
    sp.SetDisabledPercentage(0.50)
    ship.GetPropertySet().AddToSet("Scene Root", sp)
    ship.SetupProperties()

    sensor = ship.GetSensorSubsystem()
    assert sensor.GetDisabledPercentage() == 0.50

    # At 26% condition the game considers the sensor disabled (<=50%), so the
    # detection gate must treat it as blind (effective range 0).
    sensor.SetCondition(26.0)
    assert sensor.IsDisabled() == 1
    assert effective_sensor_range(ship) == 0.0
