"""Sensor-damage detection scaling: range formula, detection predicate,
and the AI candidate-selection gate."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sensor_detection import (
    FALLBACK_RANGE_GU, effective_sensor_range, can_detect,
)


def _ship_with_sensor(base_range, condition=100.0, max_condition=100.0,
                      at=(0.0, 0.0, 0.0)):
    ship = ShipClass_Create("Galaxy")
    ship.SetTranslateXYZ(*at)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = max_condition
    sensors._condition = condition
    sensors.SetBaseSensorRange(base_range)
    ship.SetSensorSubsystem(sensors)
    return ship, sensors


def test_undamaged_sensor_returns_full_base_range():
    ship, _ = _ship_with_sensor(2000.0)
    assert effective_sensor_range(ship) == 2000.0


def test_range_scales_linearly_with_condition():
    ship, _ = _ship_with_sensor(2000.0, condition=60.0)
    assert effective_sensor_range(ship) == 1200.0


def test_disabled_sensor_returns_zero():
    # 20% condition is below the default 25% disabled threshold -> offline.
    ship, _ = _ship_with_sensor(2000.0, condition=20.0)
    assert effective_sensor_range(ship) == 0.0


def test_destroyed_sensor_returns_zero():
    ship, sensors = _ship_with_sensor(2000.0)
    sensors.SetCondition(0.0)
    assert effective_sensor_range(ship) == 0.0


def test_no_sensor_subsystem_returns_fallback():
    ship = ShipClass_Create("Galaxy")  # no sensor attached
    assert effective_sensor_range(ship) == FALLBACK_RANGE_GU


def test_zero_base_range_returns_fallback():
    ship, _ = _ship_with_sensor(0.0)
    assert effective_sensor_range(ship) == FALLBACK_RANGE_GU


def test_can_detect_true_inside_range():
    observer, _ = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(1000.0, 0.0, 0.0)
    assert can_detect(observer, target) is True


def test_can_detect_false_outside_range():
    observer, _ = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(2500.0, 0.0, 0.0)
    assert can_detect(observer, target) is False


def test_can_detect_false_when_observer_blind():
    observer, sensors = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    sensors.SetCondition(0.0)  # offline -> range 0
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(10.0, 0.0, 0.0)
    assert can_detect(observer, target) is False
