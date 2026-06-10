"""Sensor-damage detection scaling.

A ship detects targets out to a range that scales linearly with its
sensor subsystem's condition, and detects nothing once the sensor is
offline (disabled at <= DisabledPercentage, or destroyed). Used by both
the player target list and the AI candidate-selection gate.

See docs/superpowers/specs/2026-06-10-sensor-damage-detection-scaling-design.md
"""

from engine.appc.subsystems import _is_offline, _get_xyz

# Range used when a ship models no sensor subsystem or carries no
# BaseSensorRange hardpoint data. Preserves the player target list's
# historical 30000 GU reach and keeps sensor-less fixtures fully sighted.
FALLBACK_RANGE_GU = 30000.0


def effective_sensor_range(ship) -> float:
    """Detection range (game units) for *ship* given its sensor condition.

    Full BaseSensorRange when undamaged, scaled linearly by condition
    percentage, and 0.0 once the sensor subsystem is offline (disabled or
    destroyed). Returns FALLBACK_RANGE_GU for ships that don't model a
    sensor subsystem or carry no BaseSensorRange.
    """
    sensors = (ship.GetSensorSubsystem()
               if (ship is not None and hasattr(ship, "GetSensorSubsystem"))
               else None)
    if sensors is None:
        return FALLBACK_RANGE_GU
    if _is_offline(sensors):
        return 0.0
    base = sensors.GetBaseSensorRange()
    if base <= 0.0:
        return FALLBACK_RANGE_GU
    return base * sensors.GetConditionPercentage()


def can_detect(observer, target) -> bool:
    """True iff *observer* can detect *target* within its effective sensor
    range. False when the observer is blind (range 0)."""
    r = effective_sensor_range(observer)
    if r <= 0.0:
        return False
    ox, oy, oz = _get_xyz(observer)
    tx, ty, tz = _get_xyz(target)
    dx, dy, dz = tx - ox, ty - oy, tz - oz
    return (dx * dx + dy * dy + dz * dz) <= (r * r)
