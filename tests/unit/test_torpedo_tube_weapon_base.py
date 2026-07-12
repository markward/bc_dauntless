"""TorpedoTube is a BC leaf Weapon, not a powered WeaponSystem.

sdk/Build/scripts/App.py:5758  class Weapon(ShipSubsystem)
sdk/Build/scripts/App.py:5988  class TorpedoTube(Weapon)

NOTE: every assertion here walks the MRO rather than using hasattr().
TGObject.__getattr__ (engine/core/ids.py:125) returns a truthy _Stub for ANY
missing attribute, so hasattr() is vacuously True on every subsystem and would
make these tests pass even if the re-parent had not happened.
"""
from engine.appc.subsystems import (
    Weapon, WeaponSystem, PoweredSubsystem, ShipSubsystem, TorpedoTube,
)


def _mro_has(cls, name: str) -> bool:
    """True only if `name` is a REAL attribute on some class in the MRO.
    Bypasses TGObject.__getattr__'s _Stub catch-all."""
    return any(name in klass.__dict__ for klass in cls.__mro__)


def test_weapon_is_a_shipsubsystem_not_a_powered_subsystem():
    assert issubclass(Weapon, ShipSubsystem)
    assert not issubclass(Weapon, PoweredSubsystem)


def test_torpedo_tube_is_a_weapon_not_a_weapon_system():
    assert issubclass(TorpedoTube, Weapon)
    assert not issubclass(TorpedoTube, WeaponSystem)


def test_torpedo_tube_keeps_the_sdk_demanded_leaf_surface():
    # Every one of these has a real SDK call site on a tube.
    for name in ("Fire", "FireDumb", "CanFire", "StopFiring", "IsFiring",
                 "CalculateRoughDirection", "CalculateWeaponAppeal"):
        assert _mro_has(TorpedoTube, name), name


def test_torpedo_tube_drops_the_powered_aggregate_surface():
    # These are WeaponSystem/PoweredSubsystem-only. No SDK site calls any of
    # them on a tube; carrying them is what let host_loop probe for UpdateCharge.
    for name in ("StartFiring", "StopFiringAtTarget", "GetNumWeapons",
                 "GetWeapon", "IsOn", "TurnOn", "TurnOff",
                 "GetNormalPowerPercentage", "UpdateCharge", "GetMaxCharge"):
        assert not _mro_has(TorpedoTube, name), name


def test_fresh_tube_is_not_firing():
    # Weapon.__init__ must seed _firing; otherwise IsFiring() returns a truthy
    # _Stub instead of 0 and nothing raises.
    assert TorpedoTube("Forward Torpedo 1").IsFiring() == 0
