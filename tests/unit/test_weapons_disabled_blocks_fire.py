"""Disabled weapon system → StartFiring is a no-op. Parent-aggregator
predicate from Project 2: all children disabled => parent disabled.
A half-crippled system (one healthy bank) still fires the healthy bank
via the existing per-emitter retry."""
from engine.appc.subsystems import (
    PhaserSystem, PhaserBank, WeaponSystem,
    TorpedoSystem, TorpedoTube, PulseWeaponSystem, PulseWeapon,
)


def _bank(name, max_charge=5.0, charge=5.0, min_firing=3.0,
          max_damage=1.0, max_damage_distance=1000.0,
          max_condition=100.0, condition=100.0,
          disabled_percentage=0.25):
    b = PhaserBank(name)
    b._max_charge = max_charge
    b._charge_level = charge
    b._min_firing_charge = min_firing
    b._max_damage = max_damage
    b._max_damage_distance = max_damage_distance
    b._max_condition = max_condition
    b._condition = condition
    b._disabled_percentage = disabled_percentage
    return b


def _target(world_x=0.0, world_y=100.0, world_z=0.0):
    """Minimal target stub straight ahead of the ship (model-Y forward).

    Positioned on +Y so PhaserBank's default emitter direction (model-Y
    via the property pipeline, or the open-arc fallback when GetDirection
    is absent) doesn't reject the aim during arc-gate checks."""
    class _T:
        def GetWorldLocation(self):
            from engine.appc.math import TGPoint3
            return TGPoint3(world_x, world_y, world_z)
        def IsDead(self): return False
    return _T()


def _firing_phaser_system():
    """A PhaserSystem turned on with four child banks; parent ship set."""
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    sys_ = PhaserSystem("Phasers")
    sys_._max_condition = 100.0
    sys_._condition = 100.0
    sys_._disabled_percentage = 0.75
    sys_.TurnOn()
    for i in range(4):
        sys_.AddChildSubsystem(_bank(f"Bank{i}"))
    ship.SetPhaserSystem(sys_)
    return ship, sys_


def test_phaser_system_all_children_disabled_blocks_startfiring():
    ship, sys_ = _firing_phaser_system()
    target = _target()
    # Disable every child.
    for i in range(4):
        sys_.GetWeapon(i)._condition = 10.0  # 10 <= 0.25 * 100 = 25
    assert sys_.IsDisabled() == 1

    sys_.StartFiring(target=target)
    # No bank should have transitioned to firing.
    for i in range(4):
        assert sys_.GetWeapon(i).IsFiring() == 0
    assert sys_._currently_firing == []


def test_phaser_system_one_healthy_child_still_fires():
    """Aggregator semantics: at least one healthy child => parent NOT
    disabled, so StartFiring works and the healthy bank fires."""
    ship, sys_ = _firing_phaser_system()
    target = _target()
    for i in range(3):
        sys_.GetWeapon(i)._condition = 10.0  # disabled
    # Bank3 stays at condition 100
    assert sys_.IsDisabled() == 0  # parent still enabled
    sys_.StartFiring(target=target)
    # SingleFire defaults to 0 on PhaserSystem unless set; check that
    # at least one bank flipped to firing.
    firing_idxs = [i for i in range(4) if sys_.GetWeapon(i).IsFiring() == 1]
    assert len(firing_idxs) >= 1


def test_phaser_system_repair_restores_firing():
    ship, sys_ = _firing_phaser_system()
    target = _target()
    for i in range(4):
        sys_.GetWeapon(i)._condition = 10.0
    sys_.StartFiring(target=target)
    assert sys_._currently_firing == []

    # Repair one child; parent re-enabled.
    sys_.GetWeapon(0)._condition = 100.0
    assert sys_.IsDisabled() == 0
    sys_.StartFiring(target=target)
    assert len(sys_._currently_firing) >= 1


def test_weapon_system_base_startfiring_gates_on_offline():
    """Cover the base WeaponSystem.StartFiring used by TorpedoSystem,
    PulseWeaponSystem, TractorBeamSystem. PhaserSystem overrides the
    method, so we exercise a non-phaser parent here."""
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    sys_ = PulseWeaponSystem("Pulse")
    sys_._max_condition = 100.0
    sys_._condition = 100.0
    sys_._disabled_percentage = 0.75
    sys_.TurnOn()
    # Build one disabled pulse-weapon child.
    child = PulseWeapon("PW0")
    child._max_condition = 100.0
    child._condition = 10.0
    child._disabled_percentage = 0.25
    sys_.AddChildSubsystem(child)
    ship.SetPulseWeaponSystem(sys_) if hasattr(ship, "SetPulseWeaponSystem") else setattr(ship, "_pulse_weapon_system", sys_)

    assert sys_.IsDisabled() == 1
    # StartFiring should be a no-op.
    sys_.StartFiring()
    assert sys_._currently_firing == []


def test_retry_held_fire_stops_on_offline_mid_burst():
    """LBUTTON held, system fires, then all children flip disabled
    mid-burst: retry_held_fire calls StopFiring (clears _fire_held)."""
    ship, sys_ = _firing_phaser_system()
    target = _target()
    sys_.StartFiring(target=target)
    assert sys_._fire_held is True

    # All children flip disabled mid-burst.
    for i in range(4):
        sys_.GetWeapon(i)._condition = 10.0
    assert sys_.IsDisabled() == 1

    sys_.retry_held_fire()
    # Held state cleared, no banks firing.
    assert sys_._fire_held is False
    for i in range(4):
        assert sys_.GetWeapon(i).IsFiring() == 0


def test_advance_combat_stops_disabled_system_mid_tick():
    """_advance_combat called against a ship whose PhaserSystem flipped
    disabled mid-frame — must call StopFiring on any active banks and
    skip the damage loop. No apply_hit invocations."""
    from engine.host_loop import _advance_combat
    import engine.appc.combat as combat_mod

    ship, sys_ = _firing_phaser_system()
    from engine.appc.ships import ShipClass_Create
    target = ShipClass_Create("Galaxy")
    target.SetTranslateXYZ(0.0, 100.0, 0.0)  # straight ahead (model-Y forward)
    sys_.StartFiring(target=target)
    # At least one bank firing.
    assert any(sys_.GetWeapon(i).IsFiring() == 1 for i in range(4))

    # Disable mid-burst.
    for i in range(4):
        sys_.GetWeapon(i)._condition = 10.0
    assert sys_.IsDisabled() == 1

    # Spy on apply_hit so we can prove it's not called.
    calls = []
    original = combat_mod.apply_hit
    combat_mod.apply_hit = lambda *a, **kw: calls.append((a, kw))
    try:
        _advance_combat([ship, target], dt=1.0/60,
                        ship_instances=None)
    finally:
        combat_mod.apply_hit = original

    assert calls == []
    # All banks stopped.
    for i in range(4):
        assert sys_.GetWeapon(i).IsFiring() == 0


def _firing_ship_with_sensor(condition):
    """A firing PhaserSystem ship that also carries a sensor subsystem
    (BaseSensorRange 2000, disabled at <=50%) at the given condition."""
    from engine.appc.subsystems import SensorSubsystem
    ship, sys_ = _firing_phaser_system()
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = condition
    sensors._disabled_percentage = 0.5
    sensors.SetBaseSensorRange(2000.0)
    ship.SetSensorSubsystem(sensors)
    return ship, sys_, sensors


def _run_advance_combat(ship, target):
    """Run _advance_combat with apply_hit spied; return the call list."""
    from engine.host_loop import _advance_combat
    import engine.appc.combat as combat_mod
    calls = []
    original = combat_mod.apply_hit
    combat_mod.apply_hit = lambda *a, **kw: calls.append((a, kw))
    try:
        _advance_combat([ship, target], dt=1.0 / 60,
                        ship_instances=None)
    finally:
        combat_mod.apply_hit = original
    return calls


def test_advance_combat_fires_when_sensors_healthy():
    """Positive control: with healthy sensors and the target in range, the
    continuous-fire tick applies damage (apply_hit called)."""
    from engine.appc.ships import ShipClass_Create
    ship, sys_, _ = _firing_ship_with_sensor(condition=100.0)
    target = ShipClass_Create("Galaxy")
    target.SetTranslateXYZ(0.0, 100.0, 0.0)  # 100 GU ahead, within 2000 range
    sys_.StartFiring(target=target)
    assert any(sys_.GetWeapon(i).IsFiring() == 1 for i in range(4))

    calls = _run_advance_combat(ship, target)
    assert calls != []  # damage applied


def test_advance_combat_stops_firing_when_sensors_offline():
    """The bug: banks left IsFiring by an AI that stopped updating keep
    dealing damage via _advance_combat with no sensor check. A ship whose
    sensors are offline must not keep firing — banks stop, no apply_hit."""
    from engine.appc.ships import ShipClass_Create
    ship, sys_, sensors = _firing_ship_with_sensor(condition=100.0)
    target = ShipClass_Create("Galaxy")
    target.SetTranslateXYZ(0.0, 100.0, 0.0)
    sys_.StartFiring(target=target)
    assert any(sys_.GetWeapon(i).IsFiring() == 1 for i in range(4))

    # Knock the firing ship's sensors offline (10 <= 0.5 * 100).
    sensors.SetCondition(10.0)

    calls = _run_advance_combat(ship, target)
    assert calls == []  # no damage applied
    for i in range(4):
        assert sys_.GetWeapon(i).IsFiring() == 0


def test_advance_combat_stops_firing_when_weapons_powered_off():
    """Power slider to 0% calls TurnOff().  Already-firing phaser banks must
    be stopped by the _advance_combat loop (not just prevented from starting).

    Root cause: the existing gate is ``_is_offline`` (disabled OR destroyed),
    which does NOT check ``IsOn()``.  A powered-down but otherwise healthy
    system kept dealing damage until charge ran out naturally.
    """
    from engine.appc.ships import ShipClass_Create
    ship, sys_ = _firing_phaser_system()
    target = ShipClass_Create("Galaxy")
    target.SetTranslateXYZ(0.0, 100.0, 0.0)  # straight ahead

    # System is ON and healthy — start firing.
    assert sys_.IsOn() == 1
    sys_.StartFiring(target=target)
    assert any(sys_.GetWeapon(i).IsFiring() == 1 for i in range(4)), \
        "pre-condition: at least one bank must be firing before power-off"

    # Power slider to 0% → TurnOff.  System is healthy (not disabled).
    sys_.TurnOff()
    assert sys_.IsOn() == 0
    assert sys_.IsDisabled() == 0  # confirm: _is_offline would NOT catch this

    calls = _run_advance_combat(ship, target)
    # No damage must have been applied and all banks must be stopped.
    assert calls == [], "apply_hit must not be called while weapons are powered off"
    for i in range(4):
        assert sys_.GetWeapon(i).IsFiring() == 0, \
            f"bank {i} still firing after weapons powered off"
