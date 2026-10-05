"""Sensor dials: identification time, near band, sweep period (RE'd defaults)."""
from engine.appc import sensor_dials
from engine import dev_dial_groups
from engine.appc.subsystems import SensorSubsystem


def test_defaults_are_bcs_recovered_values():
    sensor_dials.reset()
    assert sensor_dials.get("identification_time_s") == 4.0
    assert sensor_dials.get("near_fraction") == 0.5
    assert sensor_dials.get("sweep_period_s") == 1.0
    assert sensor_dials.DIAL_ORDER[:3] == (
        "identification_time_s", "near_fraction", "sweep_period_s")


def test_step_is_pure_additive_and_clamped():
    d = dict(sensor_dials.DEFAULTS)
    up = sensor_dials.step(d, "identification_time_s", +1)
    assert up["identification_time_s"] == 4.5
    assert d["identification_time_s"] == 4.0          # pure
    assert sensor_dials.step(d, "near_fraction", +1)["near_fraction"] == 0.55
    low = dict(d, identification_time_s=0.5, near_fraction=0.05,
               sweep_period_s=0.25, continuity_window_s=0.5,
               min_blocker_radius_gu=0.25, field_unknown_threshold=0.05,
               nebula_unknown_threshold=0.01)
    for name in sensor_dials.DIAL_ORDER:
        assert sensor_dials.step(low, name, -1)[name] == low[name]
    high = dict(d, near_fraction=1.0, field_unknown_threshold=1.0,
                nebula_unknown_threshold=1.0)
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


def test_continuity_and_occlusion_dials_defaults_and_order():
    sensor_dials.reset()
    assert sensor_dials.get("continuity_window_s") == 5.0
    assert sensor_dials.get("min_blocker_radius_gu") == 2.0
    assert sensor_dials.get("field_unknown_threshold") == 0.5
    assert sensor_dials.get("nebula_unknown_threshold") == 0.14
    assert sensor_dials.DIAL_ORDER[:3] == (
        "identification_time_s", "near_fraction", "sweep_period_s")
    assert set(sensor_dials.DIAL_ORDER[3:]) == {
        "continuity_window_s", "min_blocker_radius_gu",
        "field_unknown_threshold", "nebula_unknown_threshold"}


def test_new_dials_step_and_clamp():
    d = dict(sensor_dials.DEFAULTS)
    assert sensor_dials.step(d, "continuity_window_s", +1)["continuity_window_s"] == 5.5
    assert sensor_dials.step(d, "min_blocker_radius_gu", -1)["min_blocker_radius_gu"] == 1.75
    assert sensor_dials.step(d, "field_unknown_threshold", +1)["field_unknown_threshold"] == 0.55
    assert sensor_dials.step(d, "nebula_unknown_threshold", +1)["nebula_unknown_threshold"] == 0.15
    low = dict(d, continuity_window_s=0.5, min_blocker_radius_gu=0.25,
               field_unknown_threshold=0.05, nebula_unknown_threshold=0.01)
    for name in ("continuity_window_s", "min_blocker_radius_gu",
                 "field_unknown_threshold", "nebula_unknown_threshold"):
        assert sensor_dials.step(low, name, -1)[name] == low[name]
    high = dict(d, field_unknown_threshold=1.0, nebula_unknown_threshold=1.0)
    assert sensor_dials.step(high, "field_unknown_threshold", +1)["field_unknown_threshold"] == 1.0
    assert sensor_dials.step(high, "nebula_unknown_threshold", +1)["nebula_unknown_threshold"] == 1.0
