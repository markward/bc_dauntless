"""Cloak is a range contest, not an absolute — INTENTIONAL divergence from BC.

Every assertion here pins a deliberate gameplay change. If one of these starts
failing, the question is "was the change reverted?", not "what broke?".
"""
from engine.appc import sensor_detection as sd
from engine.appc.sensor_detection import can_detect
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import CloakingSubsystem, SensorSubsystem


def _observer(base_range=2000.0, condition=100.0):
    """Observer with a REAL sensor subsystem — follows
    tests/unit/test_sensor_detection.py::_ship_with_sensor. A bare ShipClass()
    has none, so effective_sensor_range would return FALLBACK_RANGE_GU (30000),
    fifteen times a Galaxy's real reach, and every assertion below would be
    measuring the fallback instead of the thing it names."""
    ship = ShipClass_Create("Galaxy")
    ship.SetName("player")
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = condition
    sensors.SetBaseSensorRange(base_range)
    ship.SetSensorSubsystem(sensors)
    return ship


def _target(x, cloaked=False, mid_cloak=False):
    """A contact at (x, 0, 0). Cloak construction follows
    tests/unit/test_select_target_drops_cloaked.py::_kitted_ship.

    ``mid_cloak`` drives the subsystem into CLOAK_CLOAKING — the transitional
    state — via the same StartCloaking() the SDK's CloakShip preprocessor
    calls. IsTryingToCloak() is then 1 while IsCloaked() is still 0.
    """
    s = ShipClass()
    s.SetName("Warbird")
    s.SetTranslateXYZ(x, 0.0, 0.0)
    if cloaked or mid_cloak:
        s.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
        if mid_cloak:
            s.GetCloakingSubsystem().StartCloaking()
        else:
            s.GetCloakingSubsystem().InstantCloak()
    return s


def test_cloaked_ship_is_detected_inside_one_percent_of_sensor_range():
    """2000 GU sensors give a 20 GU cloak bubble — one third of a Galaxy's
    60 GU phaser range. You must be effectively on top of it."""
    assert can_detect(_observer(), _target(15.0, cloaked=True)) is True


def test_cloaked_ship_is_not_detected_beyond_one_percent():
    assert can_detect(_observer(), _target(25.0, cloaked=True)) is False


def test_uncloaked_ship_at_the_same_distance_is_still_detected():
    """The multiplier must apply ONLY to cloaked targets."""
    assert can_detect(_observer(), _target(25.0)) is True


def test_cloak_reach_scales_with_sensor_condition():
    """It is a percentage of EFFECTIVE range, so damage shrinks it — this is
    what makes boosting sensor power meaningful."""
    assert can_detect(_observer(), _target(15.0, cloaked=True)) is True
    # 50% condition -> 1000 GU effective -> 10 GU cloak reach
    assert can_detect(_observer(condition=50.0),
                      _target(15.0, cloaked=True)) is False


def test_mid_cloak_ship_stays_fully_visible_with_no_multiplier():
    """The multiplier is gated on IsCloaked(), not IsTryingToCloak(): a ship
    part-way through the fade is still fully sighted at full sensor range.
    500 GU is 25x the 20 GU cloak bubble, so this only passes if no multiplier
    was applied."""
    mid = _target(500.0, mid_cloak=True)
    cloak = mid.GetCloakingSubsystem()
    assert cloak.IsTryingToCloak() == 1
    assert cloak.IsCloaked() == 0
    assert can_detect(_observer(), mid) is True


def test_offline_sensors_detect_nothing_even_point_blank():
    """20% is below the default 25% disabled threshold -> range 0."""
    assert can_detect(_observer(condition=20.0),
                      _target(1.0, cloaked=True)) is False


def test_toggle_off_restores_absolute_cloak(monkeypatch):
    """Flipping the flag must return stock BC exactly: cloak is absolute."""
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    assert can_detect(_observer(), _target(1.0, cloaked=True)) is False


def test_toggle_off_leaves_uncloaked_detection_untouched(monkeypatch):
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    assert can_detect(_observer(), _target(500.0)) is True
