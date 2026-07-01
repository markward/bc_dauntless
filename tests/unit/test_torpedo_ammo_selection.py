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


# ── Ammo-type reserve state (SDK GetMaxTorpedoes / GetNumAvailableTorpsToType) ──

def test_ammo_type_seeds_available_to_declared_max():
    a = TorpedoAmmoType("Photon", max_torpedoes=200)
    assert a.GetMaxTorpedoes() == 200
    assert a.GetAvailable() == 200  # spawns fully loaded


def test_add_available_clamps_to_range():
    a = TorpedoAmmoType("Photon", max_torpedoes=10)
    a.AddAvailable(-3)
    assert a.GetAvailable() == 7
    a.AddAvailable(+100)          # clamp up to max
    assert a.GetAvailable() == 10
    a.AddAvailable(-999)          # clamp down to 0
    assert a.GetAvailable() == 0


def test_undeclared_max_is_unlimited_no_op():
    # max_torpedoes=None (the undeclared-slot / legacy fallback) => reserve is
    # inert: AddAvailable never changes anything, so firing can't run it dry.
    a = TorpedoAmmoType("Photon")  # no max declared
    a.AddAvailable(-5)
    assert a.GetAvailable() == 0   # unlimited types report 0 available, unchanged
    assert a.GetMaxTorpedoes() == 0


def test_set_max_torpedoes_makes_finite():
    a = TorpedoAmmoType("Photon")  # unlimited
    a.SetMaxTorpedoes(5)
    a.SetAvailable(5)
    a.AddAvailable(-2)
    assert a.GetAvailable() == 3   # now finite and decrementing


def test_ammo_type_script_round_trip():
    a = TorpedoAmmoType("Photon", script="Tactical.Projectiles.PhotonTorpedo")
    assert a.GetTorpedoScript() == "Tactical.Projectiles.PhotonTorpedo"


# ── System curation API (RemoveAmmoType / LoadAmmoType / GetNumAvailable...) ──

def _system_with_finite_types():
    t = TorpedoSystem("Torpedoes")
    t.AddAmmoType(TorpedoAmmoType("Photon", power_cost=20.0, max_torpedoes=200))
    t.AddAmmoType(TorpedoAmmoType("Quantum", power_cost=30.0, max_torpedoes=60))
    return t


def test_load_ammo_type_and_query_available():
    t = _system_with_finite_types()
    assert t.GetNumAvailableTorpsToType(0) == 200
    t.LoadAmmoType(0, -50)                       # fire/deduct 50
    assert t.GetNumAvailableTorpsToType(0) == 150
    t.LoadAmmoType(0, +1000)                     # clamp to max
    assert t.GetNumAvailableTorpsToType(0) == 200


def test_get_available_missing_slot_is_zero():
    t = _system_with_finite_types()
    assert t.GetNumAvailableTorpsToType(9) == 0


def test_remove_ammo_type_drops_slot_and_fixes_count():
    t = TorpedoSystem("Torpedoes")
    t.AddAmmoType(TorpedoAmmoType("Photon", max_torpedoes=200))
    t.AddAmmoType(TorpedoAmmoType("Quantum", max_torpedoes=60))
    t.AddAmmoType(TorpedoAmmoType("Phased", max_torpedoes=0))
    # QuickBattle prunes everything past index 1.
    for i in range(t.GetNumAmmoTypes()):
        if i >= 2:
            t.RemoveAmmoType(i)
    assert t.GetNumAmmoTypes() == 2
    assert [t.GetAmmoType(i).GetAmmoName() for i in range(2)] == ["Photon", "Quantum"]


def test_remove_selected_slot_clears_selection():
    t = _system_with_finite_types()
    t.SetCurrentAmmoSlot(1)
    t.RemoveAmmoType(1)
    # Selection falls back to the lowest remaining slot.
    assert t.GetCurrentAmmoSlot() == 0


def test_fill_ammo_type_restores_to_max():
    t = _system_with_finite_types()
    t.LoadAmmoType(0, -100)
    t.FillAmmoType(0)
    assert t.GetNumAvailableTorpsToType(0) == 200


def test_ammo_type_number_aliases_current_slot():
    t = _system_with_finite_types()
    t.SetCurrentAmmoSlot(1)
    assert t.GetCurrentAmmoTypeNumber() == 1
    assert t.GetAmmoTypeNumber() == 1


# ── Fire -> reserve wiring ────────────────────────────────────────────────────

def _firing_system_with_reserve(max_torpedoes):
    """A 1-tube TorpedoSystem at the origin with a single finite Photon type,
    reusing the spread-volley harness geometry so StartFiring actually fires."""
    from engine.appc.ships import ShipClass_Create
    from engine.appc.math import TGPoint3, TGMatrix3
    from engine.appc.properties import WeaponSystemProperty
    from engine.appc.subsystems import TorpedoTube

    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    R = TGMatrix3(); R.MakeIdentity()
    ship.SetMatrixRotation(R)

    class _Tgt:
        def __init__(self): self._loc = TGPoint3(0, 100, 0)
        def GetWorldLocation(self): return self._loc
        def IsDead(self): return 0
    tgt = _Tgt()
    ship._target = tgt
    ship._target_subsystem = None

    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    prop = WeaponSystemProperty("Torpedoes")
    prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    parent.SetProperty(prop)
    parent._parent_ship = ship
    ship._torpedo_system = parent
    parent.AddAmmoType(TorpedoAmmoType(
        "Photon", power_cost=20.0, max_torpedoes=max_torpedoes))

    tube = TorpedoTube("Torpedo 0")
    tube._max_ready = 99
    tube._num_ready = 99
    tube._reload_delay = 40.0
    parent.AddChildSubsystem(tube)
    return parent, tgt


def test_firing_decrements_finite_reserve():
    from engine.appc import projectiles
    projectiles._active.clear()
    parent, tgt = _firing_system_with_reserve(max_torpedoes=3)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target=tgt, offset=None)
    assert parent.GetNumAvailableTorpsToType(0) == 2
    projectiles._active.clear()


def test_finite_reserve_blocks_fire_at_zero():
    from engine.appc import projectiles
    projectiles._active.clear()
    parent, tgt = _firing_system_with_reserve(max_torpedoes=1)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target=tgt, offset=None)   # fires the last torp
        assert parent.GetNumAvailableTorpsToType(0) == 0
        n_after_empty = len(projectiles._active)
        parent.StartFiring(target=tgt, offset=None)   # out of ammo -> no fire
    assert len(projectiles._active) == n_after_empty
    projectiles._active.clear()


def test_unlimited_reserve_never_decrements_on_fire():
    from engine.appc import projectiles
    projectiles._active.clear()
    # max_torpedoes=None => unlimited: firing must not touch the reserve, so the
    # legacy/undeclared firing path stays byte-identical.
    parent, tgt = _firing_system_with_reserve(max_torpedoes=None)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target=tgt, offset=None)
    assert parent.GetNumAvailableTorpsToType(0) == 0  # unchanged, no gate
    assert len(projectiles._active) == 1              # still fired
    projectiles._active.clear()


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
