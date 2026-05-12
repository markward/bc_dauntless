"""SensorSubsystem identity fields: BaseSensorRange + MaxProbes."""
from engine.appc.subsystems import SensorSubsystem


def test_defaults():
    s = SensorSubsystem("Sensor Array")
    assert s.GetBaseSensorRange() == 0.0
    assert s.GetMaxProbes() == 0


def test_setters_persist():
    s = SensorSubsystem("Sensor Array")
    s.SetBaseSensorRange(2000.0)
    s.SetMaxProbes(10)
    assert s.GetBaseSensorRange() == 2000.0
    assert s.GetMaxProbes() == 10
