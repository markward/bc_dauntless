"""Sensor range scales by GetNormalPowerPercentage (power factor); shield regen does not."""
from engine.appc.subsystems import ShieldSubsystem, SensorSubsystem


def test_shield_regen_ignores_power_factor():
    """Regen does NOT scale with the generator's power factor: measured on
    the original exe, a face at 50 % climbs at the same 9.2–9.5/s with the
    generator at 50 % power wanted (stbc-oracle bible §5.3 S5,
    `regen_power50_face50`). Sensor range still scales (below)."""
    ss = ShieldSubsystem("Shield Generator")
    ss.TurnOn()
    ss.SetMaxShields(ss.FRONT_SHIELDS, 100.0)
    ss.SetCurShields(ss.FRONT_SHIELDS, 0.0)
    ss.SetShieldChargePerSecond(ss.FRONT_SHIELDS, 10.0)
    ss._power_factor = 0.5
    ss.Update(1.0)
    assert abs(ss.GetCurShields(ss.FRONT_SHIELDS) - 10.0) < 1e-9
    ss._power_factor = 1.25
    ss.Update(1.0)
    assert abs(ss.GetCurShields(ss.FRONT_SHIELDS) - 20.0) < 1e-9


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
