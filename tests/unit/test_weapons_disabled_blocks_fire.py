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
