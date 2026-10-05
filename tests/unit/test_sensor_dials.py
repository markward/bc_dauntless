"""Sensor dials: identification time, near band, sweep period (RE'd defaults)."""
from engine.appc import sensor_dials
from engine import dev_dial_groups
from engine.appc.subsystems import SensorSubsystem


def test_defaults_are_bcs_recovered_values():
    sensor_dials.reset()
    assert sensor_dials.get("identification_time_s") == 4.0
    assert sensor_dials.get("near_fraction") == 0.5
    assert sensor_dials.get("sweep_period_s") == 1.0
    assert sensor_dials.DIAL_ORDER == (
        "identification_time_s", "near_fraction", "sweep_period_s")


def test_step_is_pure_additive_and_clamped():
    d = dict(sensor_dials.DEFAULTS)
    up = sensor_dials.step(d, "identification_time_s", +1)
    assert up["identification_time_s"] == 4.5
    assert d["identification_time_s"] == 4.0          # pure
    assert sensor_dials.step(d, "near_fraction", +1)["near_fraction"] == 0.55
    low = dict(d, identification_time_s=0.5, near_fraction=0.05,
               sweep_period_s=0.25)
    for name in sensor_dials.DIAL_ORDER:
        assert sensor_dials.step(low, name, -1)[name] == low[name]
    high = dict(d, near_fraction=1.0)
    assert sensor_dials.step(high, "near_fraction", +1)["near_fraction"] == 1.0


def test_registered_group_steps_the_live_dial():
    dev_dial_groups.reset()
    sensor_dials.reset()
    sensor_dials.register()
    assert "sensors" in dev_dial_groups.groups()
    assert dev_dial_groups.set_active("sensors") is True
    dev_dial_groups.push(+1)       # selected dial is the first: identification time
    assert sensor_dials.get("identification_time_s") == 4.5


def test_sensor_subsystem_reports_the_dial():
    sensor_dials.reset()
    assert SensorSubsystem("Sensors").GetIdentificationTime() == 4.0
    sensor_dials._dials["identification_time_s"] = 2.5
    assert SensorSubsystem("Sensors").GetIdentificationTime() == 2.5
