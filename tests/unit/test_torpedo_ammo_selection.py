"""TorpedoSystem selected-ammo-slot support.

Adds a settable "selected slot" so UI type-cycling changes which ammo type
GetCurrentAmmoType() returns (and therefore which power cost firing debits).
The default (no selection) must stay byte-identical to the pre-existing
"lowest populated slot" behaviour so older tests remain green.
"""
from unittest.mock import patch

from engine.appc.subsystems import TorpedoSystem, TorpedoTube
from engine.appc.weapon_subsystems import TorpedoAmmoType


def _system_with_two_types():
    t = TorpedoSystem("Torpedoes")
    t.AddAmmoType(TorpedoAmmoType("Photon", power_cost=20.0))
    t.AddAmmoType(TorpedoAmmoType("Quantum", power_cost=30.0))
    return t


def test_default_current_ammo_is_lowest_slot():
    t = _system_with_two_types()
    assert t.GetCurrentAmmoType().GetAmmoName() == "Photon"
    assert t.GetCurrentAmmoSlot() == 0


def test_set_current_ammo_slot_changes_selection():
    t = _system_with_two_types()
    t.SetCurrentAmmoSlot(1)
    assert t.GetCurrentAmmoSlot() == 1
    assert t.GetCurrentAmmoType().GetAmmoName() == "Quantum"


def test_set_invalid_slot_ignored():
    t = _system_with_two_types()
    t.SetCurrentAmmoSlot(5)  # no such slot
    assert t.GetCurrentAmmoSlot() == 0
    assert t.GetCurrentAmmoType().GetAmmoName() == "Photon"


def test_cycle_ammo_type_advances_and_wraps():
    t = _system_with_two_types()
    assert t.GetCurrentAmmoSlot() == 0
    t.CycleAmmoType()
    assert t.GetCurrentAmmoType().GetAmmoName() == "Quantum"
    t.CycleAmmoType()  # wraps back to slot 0
    assert t.GetCurrentAmmoType().GetAmmoName() == "Photon"


def test_cycle_single_type_no_op():
    t = TorpedoSystem("Torpedoes")
    t.AddAmmoType(TorpedoAmmoType("Photon", power_cost=20.0))
    t.CycleAmmoType()
    assert t.GetCurrentAmmoType().GetAmmoName() == "Photon"


def test_cycle_no_ammo_no_crash():
    t = TorpedoSystem("Torpedoes")
    t.CycleAmmoType()  # must not raise
    assert t.GetCurrentAmmoType() is None


def test_firing_debits_selected_type_power_cost():
    """The tube's _debit_power reads parent.GetCurrentAmmoType().GetPowerCost().
    Selecting slot 1 (Quantum, cost 30) must debit 30, not 20."""
    from engine.appc.ships import ShipClass_Create
    from engine.appc.math import TGPoint3
    from engine.appc.properties import WeaponSystemProperty

    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    parent = _system_with_two_types()
    parent.TurnOn()
    parent_prop = WeaponSystemProperty("Torpedoes")
    parent.SetProperty(parent_prop)
    parent._parent_ship = ship
    ship._torpedo_system = parent
    parent.SetCurrentAmmoSlot(1)  # Quantum, cost 30

    tube = TorpedoTube("Forward Torpedo 1")
    tube._max_ready = 1
    tube._num_ready = 1
    parent.AddChildSubsystem(tube)

    billed = {}

    def _fake_debit(emitter, cost):
        billed["cost"] = cost
        return 1

    with patch("engine.appc.weapon_subsystems._debit_ship_power", _fake_debit), \
         patch("engine.audio.tg_sound.TGSoundManager.instance"):
        tube.Fire(target=None, offset=None)

    assert billed["cost"] == 30.0
