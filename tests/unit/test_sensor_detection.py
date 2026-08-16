"""Sensor-damage detection scaling: range formula, detection predicate,
and the AI candidate-selection gate."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.perception import perceived_by
from engine.appc.sensor_detection import (
    FALLBACK_RANGE_GU, effective_sensor_range, can_detect,
    observing, current_observing_ship,
    _wrap_active_tuple, _wrap_find_good_target, _wrap_get_targets,
    install_ai_sensor_gate,
)
from engine.appc.objects import ObjectGroup


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


# ── Installed-gate integration tests ─────────────────────────────────────────


def _set_with(*named_ships):
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    for name, ship in named_ships:
        ship.SetName(name)
        pSet.AddObjectToSet(ship, name)
    return pSet


def test_installed_gate_filters_active_tuple_by_sensor_range():
    install_ai_sensor_gate()

    near = ShipClass_Create("BirdOfPrey"); near.SetTranslateXYZ(500.0, 0.0, 0.0)
    far = ShipClass_Create("BirdOfPrey"); far.SetTranslateXYZ(5000.0, 0.0, 0.0)
    pSet = _set_with(("Near", near), ("Far", far))

    group = ObjectGroup()
    group.AddName("Near"); group.AddName("Far")

    # No observer -> both contacts returned (non-AI callers unaffected).
    assert set(group.GetActiveObjectTupleInSet(pSet)) == {near, far}

    # Observer with 2000 GU range -> only the near contact survives.
    observer, sensors = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    with observing(observer):
        assert group.GetActiveObjectTupleInSet(pSet) == (near,)


def test_installed_gate_blinds_observer_with_offline_sensors():
    install_ai_sensor_gate()

    enemy = ShipClass_Create("BirdOfPrey"); enemy.SetTranslateXYZ(100.0, 0.0, 0.0)
    pSet = _set_with(("Enemy", enemy))
    group = ObjectGroup(); group.AddName("Enemy")

    observer, sensors = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    sensors.SetCondition(0.0)  # offline -> range 0
    with observing(observer):
        assert group.GetActiveObjectTupleInSet(pSet) == ()


def test_install_is_idempotent():
    install_ai_sensor_gate()
    first = ObjectGroup.GetActiveObjectTupleInSet
    install_ai_sensor_gate()
    second = ObjectGroup.GetActiveObjectTupleInSet
    # Second install must not re-wrap (same function object, no double filter).
    assert first is second
    assert getattr(second, "_sensor_gated", False) is True


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


def test_bootstrap_installs_sensor_gate():
    """The host bootstrap installs the AI sensor gate. We first verify the
    installer wraps the method (real traceback on failure), then confirm the
    bootstrap path triggers it too. Later pipeline steps may need fuller host
    state, so only those are tolerated as failures."""
    from engine import host_loop

    # Direct install must succeed and wrap the method (surfaces real errors).
    install_ai_sensor_gate()
    assert getattr(ObjectGroup.GetActiveObjectTupleInSet, "_sensor_gated", False) is True

    # And the bootstrap hook calls it as its first statement.
    try:
        host_loop._bootstrap_firing_pipeline()
    except Exception:
        pass
    assert getattr(ObjectGroup.GetActiveObjectTupleInSet, "_sensor_gated", False) is True


def test_wrap_get_targets_publishes_ship_arg_during_call():
    captured = []

    def fake_orig(self, pShip):
        captured.append(current_observing_ship())
        return "result"

    wrapped = _wrap_get_targets(fake_orig)

    observer, _ = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))

    class _FakeStarbaseAttack:
        pass

    assert wrapped(_FakeStarbaseAttack(), observer) == "result"
    assert captured == [observer]
    assert current_observing_ship() is None  # cleared after the call
    assert getattr(wrapped, "_sensor_gated", False) is True


def test_install_wraps_starbase_attack_get_targets():
    install_ai_sensor_gate()
    import AI.PlainAI.StarbaseAttack as sba
    assert getattr(sba.StarbaseAttack.GetTargets, "_sensor_gated", False) is True


def test_fire_script_target_visible_gated_by_firing_ship_sensors():
    """FireScript drives AI firing; stock BC stubs TargetVisible to always-true.
    After install, it must gate on the firing ship's sensor reach so a
    sensor-disabled ship stops firing at its locked target."""
    install_ai_sensor_gate()
    import AI.Preprocessors as pp

    fs = pp.FireScript("Enemy")
    observer, sensors = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(500.0, 0.0, 0.0)

    class _FakeCodeAI:
        def GetShip(self):
            return observer

    fs.pCodeAI = _FakeCodeAI()

    # Healthy sensors, target within range -> visible (fires).
    assert fs.TargetVisible(target) == 1
    assert fs.bTargetVisible == 1

    # Disabled sensors -> not visible (firing gate trips).
    sensors.SetCondition(0.0)
    assert fs.TargetVisible(target) == 0
    assert fs.bTargetVisible == 0

    # Target beyond the (healthy) sensor reach -> not visible either.
    sensors.SetCondition(100.0)
    target.SetTranslateXYZ(5000.0, 0.0, 0.0)
    assert fs.TargetVisible(target) == 0

    assert getattr(pp.FireScript.TargetVisible, "_sensor_gated", False) is True


def _fire_script_at(distance_gu):
    """A gated FireScript whose firing ship has 2000 GU sensors (a 20 GU cloak
    bubble) locked onto a fully cloaked BirdOfPrey at *distance_gu*."""
    from engine.appc.subsystems import CloakingSubsystem
    install_ai_sensor_gate()
    import AI.Preprocessors as pp

    fs = pp.FireScript("Enemy")
    observer, _sensors = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(float(distance_gu), 0.0, 0.0)
    target.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    target.GetCloakingSubsystem().InstantCloak()

    class _FakeCodeAI:
        def GetShip(self):
            return observer

    fs.pCodeAI = _FakeCodeAI()
    return fs, target


def test_fire_script_engages_a_cloaked_target_inside_the_bubble():
    """INTENTIONAL stage-4 gameplay change (ENHANCED_SENSOR_CONTEST, default on).

    FireScript.TargetVisible is the AI's firing gate and runs through
    can_detect, so the contest is symmetric: an AI ship keeps engaging a target
    that cloaks inside its 20 GU bubble, exactly as the player's phaser gate now
    does (tests/unit/test_phaser_cloaked_target_no_fire.py). A cloaked attack
    run is detectable close in. Deliberate divergence from BC.

    NOTE this covers the *firing* half only. The AI cannot ACQUIRE a cloaked
    contact from cold: SelectTarget.FindGoodTarget carries its own absolute
    cloak skip in the SDK (AI/Preprocessors.py:1446-1450), downstream of the
    can_detect candidate filter. See test_select_target_drops_cloaked.py.
    """
    fs, target = _fire_script_at(15.0)
    assert fs.TargetVisible(target) == 1
    assert fs.bTargetVisible == 1


def test_fire_script_stops_at_a_cloaked_target_outside_the_bubble():
    """The bubble boundary holds: at 30 GU — inside the 2000 GU sensor reach but
    outside the 20 GU cloak bubble — the firing gate trips, as in stock BC."""
    fs, target = _fire_script_at(30.0)
    assert fs.TargetVisible(target) == 0
    assert fs.bTargetVisible == 0


def test_fire_script_cloak_gate_is_absolute_with_the_contest_off(monkeypatch):
    """STOCK-BC BEHAVIOUR, held under ENHANCED_SENSOR_CONTEST = False: cloak is
    absolute, so even the 15 GU target the contest engages stops the AI firing."""
    import engine.appc.sensor_detection as sd
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    fs, target = _fire_script_at(15.0)
    assert fs.TargetVisible(target) == 0
    assert fs.bTargetVisible == 0
