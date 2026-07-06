"""Shield regen and sensor range scale by GetNormalPowerPercentage (power factor)."""
from engine.appc.subsystems import ShieldSubsystem, SensorSubsystem


def test_shield_regen_scales_with_power_factor():
    ss = ShieldSubsystem("Shield Generator")
    ss.TurnOn()
    ss.SetMaxShields(ss.FRONT_SHIELDS, 100.0)
    ss.SetCurShields(ss.FRONT_SHIELDS, 0.0)
    ss.SetShieldChargePerSecond(ss.FRONT_SHIELDS, 10.0)
    ss._power_factor = 0.5
    ss.Update(1.0)
    assert abs(ss.GetCurShields(ss.FRONT_SHIELDS) - 5.0) < 1e-9
    ss._power_factor = 1.25
    ss.Update(1.0)
    # After first Update: 5.0; after second: 5.0 + 10.0 * 1.25 * 1.0 = 17.5
    assert abs(ss.GetCurShields(ss.FRONT_SHIELDS) - 17.5) < 1e-9


def test_sensor_range_scales_with_power_factor():
    from engine.appc import sensor_detection
    sen = SensorSubsystem("Sensor Array")
    sen.SetBaseSensorRange(100.0)
    sen._power_factor = 1.25

    class _Ship:
        def GetSensorSubsystem(self):
            return sen

    rng = sensor_detection.effective_sensor_range(_Ship())
    assert abs(rng - 125.0) < 1e-6


def test_shield_regen_at_full_power_unchanged():
    """At factor 1.0 regen is identical to the old formula (regression guard)."""
    ss = ShieldSubsystem("Shield Generator")
    ss.TurnOn()
    ss.SetMaxShields(ss.FRONT_SHIELDS, 100.0)
    ss.SetCurShields(ss.FRONT_SHIELDS, 0.0)
    ss.SetShieldChargePerSecond(ss.FRONT_SHIELDS, 10.0)
    # _power_factor defaults to 1.0 — do not set it explicitly
    ss.Update(1.0)
    assert abs(ss.GetCurShields(ss.FRONT_SHIELDS) - 10.0) < 1e-9


def test_sensor_range_at_full_power_unchanged():
    """At factor 1.0 sensor range is identical to base * condition (regression guard)."""
    from engine.appc import sensor_detection
    sen = SensorSubsystem("Sensor Array")
    sen.SetBaseSensorRange(100.0)
    # _power_factor defaults to 1.0 — do not set it explicitly
    rng = sensor_detection.effective_sensor_range(type("_S", (), {"GetSensorSubsystem": lambda self: sen})())
    assert abs(rng - 100.0) < 1e-6
