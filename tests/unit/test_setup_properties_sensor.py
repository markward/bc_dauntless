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
