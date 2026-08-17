"""Sensor-damage detection scaling: the range formula and the detection
predicate, including where the player's target list reads them.

The AI candidate-selection gate that used to be tested here moved with its
module to tests/unit/test_ai_sensor_gate.py; nothing was dropped."""
import pytest

import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.perception import perceived_by
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
    class _NoSensorShip:
        def GetSensorSubsystem(self):
            return None
    assert effective_sensor_range(_NoSensorShip()) == FALLBACK_RANGE_GU


def test_a_tgobject_that_models_no_sensor_subsystem_reaches_the_fallback():
    """The capability probe must be `ids.implements`, not `hasattr`.

    `TGObject.__getattr__` vends a truthy `_Stub` for any undefined method, so
    `hasattr(obj, "GetSensorSubsystem")` is True for EVERY engine object.
    An ObjectClass therefore used to get a `_Stub` back, `_is_offline(_Stub)`
    answered truthy, and the function returned 0.0 — "blind" — for an object
    that simply does not model sensors. The documented answer for that is
    FALLBACK_RANGE_GU, which is already what the sensor-less test fixtures
    above get; the 0.0 was an artifact of the vacuous probe, not a decision.

    No production caller is affected: every `can_detect` / `perceived_by`
    observer in the tree is a ShipClass (player, `pCodeAI.GetShip()`,
    StarbaseAttack's `pShip`, a torpedo's source ship, a weapon system's parent
    ship), and ShipClass really does define `GetSensorSubsystem`, so both
    probes answered True for it before and after.
    """
    from engine.appc.objects import ObjectClass

    assert effective_sensor_range(ObjectClass()) == FALLBACK_RANGE_GU


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


def test_can_detect_refuses_positional_optional_arguments():
    """The two optional parameters are KEYWORD-ONLY, and that is a bug fix.

    `bool` is a subclass of `int`, so the natural misreading
    `can_detect(observer, target, False)` — read as "don't apply concealment" —
    used to bind `dist_sq_gu=False`. `False <= r * r` is True for any positive
    range, i.e. a silent always-detect that no assertion anywhere would catch.
    Keyword-only turns that misreading into a TypeError at the call site.
    """
    observer, _ = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(2500.0, 0.0, 0.0)  # OUTSIDE the 2000 GU reach

    with pytest.raises(TypeError):
        can_detect(observer, target, False)

    # The keyword spelling of the same intent still works and still answers
    # from the real geometry.
    assert can_detect(observer, target, apply_concealment=False) is False


# ── The predicate reaching the player's target list ──────────────────────────


def _set_with(*named_ships):
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    for name, ship in named_ships:
        ship.SetName(name)
        pSet.AddObjectToSet(ship, name)
    return pSet


def _menu_visible(menu, ship):
    """Is *ship* drawable on the player's target list / radar?

    Both surfaces walk the menu's children and keep IsVisible() == 1 rows, so
    a contact leaves the display either by losing its row or by having it
    flagged not-visible. The single perception push decides both from one
    record, so a contact out of sensor reach now loses the row outright — the
    stronger of the two outcomes.
    """
    row = menu.GetObjectEntry(ship)
    return row is not None and row.IsVisible() == 1


def test_player_list_uses_scaled_range():
    App._reset_target_menu_singleton()
    player, sensors = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    enemy = ShipClass_Create("BirdOfPrey")
    enemy.SetTranslateXYZ(1000.0, 0.0, 0.0)
    _set_with(("Player", player), ("Enemy", enemy))

    menu = App.STTargetMenu_CreateW("Targets")

    # Undamaged: 2000 GU range, enemy at 1000 GU -> visible.
    menu.set_contacts(perceived_by(player))
    assert _menu_visible(menu, enemy) is True

    # Damaged to 40% -> 800 GU range, enemy at 1000 GU now out of range.
    sensors.SetCondition(40.0)
    menu.set_contacts(perceived_by(player))
    assert _menu_visible(menu, enemy) is False

    # Repaired: visible again.
    sensors.SetCondition(100.0)
    menu.set_contacts(perceived_by(player))
    assert _menu_visible(menu, enemy) is True


def test_player_list_reach_comes_from_the_sensor_alone():
    """Was test_player_list_explicit_range_units_still_honored.

    It pinned the `range_units=30000.0` override argument on the retired
    update_target_list_visibility. That parameter had no production caller —
    the host loop always passed the scaled range — and it died with the
    module. The value it asserted survives unchanged: with 30000 GU of reach,
    a contact 2500 GU out is listed and drawable. The contrast below is the
    replacement for "override": the SAME contact at the SAME place vanishes on
    a 2000 GU sensor, so reach now comes from the sensor and nowhere else.
    """
    App._reset_target_menu_singleton()
    player, sensors = _ship_with_sensor(30000.0, at=(0.0, 0.0, 0.0))
    enemy = ShipClass_Create("BirdOfPrey")
    enemy.SetTranslateXYZ(2500.0, 0.0, 0.0)  # beyond 2000 base, inside 30000
    _set_with(("Player", player), ("Enemy", enemy))

    menu = App.STTargetMenu_CreateW("Targets")
    menu.set_contacts(perceived_by(player))
    assert _menu_visible(menu, enemy) is True

    sensors.SetBaseSensorRange(2000.0)
    menu.set_contacts(perceived_by(player))
    assert _menu_visible(menu, enemy) is False
