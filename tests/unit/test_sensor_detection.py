"""Sensor-damage detection scaling: range formula, detection predicate,
and the AI candidate-selection gate."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sensor_detection import (
    FALLBACK_RANGE_GU, effective_sensor_range, can_detect,
    observing, current_observing_ship,
    _wrap_active_tuple, _wrap_find_good_target,
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
    class _NoSensorShip:
        def GetSensorSubsystem(self):
            return None
    assert effective_sensor_range(_NoSensorShip()) == FALLBACK_RANGE_GU


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


def test_observing_sets_and_restores_global():
    assert current_observing_ship() is None
    with observing("SHIP_A"):
        assert current_observing_ship() == "SHIP_A"
        with observing("SHIP_B"):
            assert current_observing_ship() == "SHIP_B"
        assert current_observing_ship() == "SHIP_A"
    assert current_observing_ship() is None


def test_observing_restores_even_on_exception():
    try:
        with observing("SHIP_A"):
            raise ValueError("boom")
    except ValueError:
        pass
    assert current_observing_ship() is None


def test_wrap_find_good_target_publishes_ship_during_call():
    captured = []

    def fake_orig(self):
        captured.append(current_observing_ship())
        return "result"

    wrapped = _wrap_find_good_target(fake_orig)

    class _FakeCodeAI:
        def GetShip(self):
            return "SHIP_X"

    class _FakeSelectTarget:
        pCodeAI = _FakeCodeAI()

    assert wrapped(_FakeSelectTarget()) == "result"
    assert captured == ["SHIP_X"]
    assert current_observing_ship() is None  # cleared after the call
    assert getattr(wrapped, "_sensor_gated", False) is True


def test_wrap_find_good_target_handles_missing_codeai():
    captured = []

    def fake_orig(self):
        captured.append(current_observing_ship())
        return "ok"

    wrapped = _wrap_find_good_target(fake_orig)

    class _NoCodeAI:
        pCodeAI = None

    # pCodeAI None -> observer None -> the companion filter is a passthrough.
    assert wrapped(_NoCodeAI()) == "ok"
    assert captured == [None]


def test_install_wraps_find_good_target_on_select_target():
    from engine.appc.sensor_detection import install_ai_sensor_gate
    import AI.Preprocessors as pp
    install_ai_sensor_gate()
    assert getattr(pp.SelectTarget.FindGoodTarget, "_sensor_gated", False) is True
    # UpdateTargetInfo must NOT be wrapped — it runs after selection and never
    # enumerates candidates.
    assert getattr(pp.SelectTarget.UpdateTargetInfo, "_sensor_gated", False) is False


def test_wrap_active_tuple_filters_only_when_observer_set():
    near = ShipClass_Create("BirdOfPrey"); near.SetTranslateXYZ(500.0, 0.0, 0.0)
    far = ShipClass_Create("BirdOfPrey"); far.SetTranslateXYZ(5000.0, 0.0, 0.0)

    def fake_orig(self, pSet):
        return (near, far)

    wrapped = _wrap_active_tuple(fake_orig)

    # No observer set -> unfiltered passthrough.
    assert wrapped(object(), None) == (near, far)

    # Observer with 2000 GU range -> only the near ship survives.
    observer, _ = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    with observing(observer):
        assert wrapped(object(), None) == (near,)
    assert getattr(wrapped, "_sensor_gated", False) is True
