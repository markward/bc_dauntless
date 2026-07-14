"""ShipSubsystem.GetObjType() — the subsystem type-token.

Conditions/ConditionCriticalSystemBelow.py:73-76 builds one child
ConditionSystemBelow per critical subsystem, passing pSubsystem.GetObjType()
as the system type. GetObjType was implemented nowhere, so the child got a
_Stub, StartGetSubsystemMatch(stub) matched zero subsystems, and the
composite watched nothing forever.

The CT_* constants are Property classes, not subsystem classes, so a naive
GetObjType/IsTypeOf can't just return/compare the subsystem's own class --
it must go through the shared CT_ <-> subsystem-class table in
engine.appc.subsystem_types (engine/appc/subsystem_types.py).
"""
import pytest

import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem
from engine.appc.weapon_subsystems import PhaserSystem, TorpedoSystem, PhaserBank


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate_app_state():
    _reset_app_state()
    yield
    _reset_app_state()


def _built_ship():
    ship = ShipClass_Create("Test")
    hull = HullSubsystem("Hull")
    hull.SetCritical(1)
    ship.SetHull(hull)
    ship.SetShieldSubsystem(ShieldSubsystem("Shields"))
    ship.SetPhaserSystem(PhaserSystem("Phasers"))
    ship.SetTorpedoSystem(TorpedoSystem("Torpedoes"))
    return ship


# ── 1. Round-trip: GetObjType() fed back into StartGetSubsystemMatch finds
#    the SAME subsystem — the exact contract ConditionCriticalSystemBelow
#    depends on. ──────────────────────────────────────────────────────────

def test_get_obj_type_round_trips_through_start_get_subsystem_match():
    ship = _built_ship()
    for sub in ship.GetSubsystems():
        ct = sub.GetObjType()
        assert ct is not None, "GetObjType() returned None for %r" % sub
        it = ship.StartGetSubsystemMatch(ct)
        matches = []
        found = ship.GetNextSubsystemMatch(it)
        while found is not None:
            matches.append(found)
            found = ship.GetNextSubsystemMatch(it)
        assert sub in matches, (
            "%r.GetObjType() = %r did not round-trip via "
            "StartGetSubsystemMatch" % (sub, ct))


# ── 2. Most-specific: a PhaserSystem is CT_PHASER_SYSTEM, not the more
#    general CT_WEAPON_SYSTEM it also IsTypeOf. ─────────────────────────────

def test_get_obj_type_is_most_specific_for_phaser_system():
    phaser = PhaserSystem("Phasers")
    assert phaser.GetObjType() is App.CT_PHASER_SYSTEM
    assert phaser.GetObjType() is not App.CT_WEAPON_SYSTEM


def test_get_obj_type_is_most_specific_for_torpedo_system():
    torps = TorpedoSystem("Torpedoes")
    assert torps.GetObjType() is App.CT_TORPEDO_SYSTEM


def test_get_obj_type_for_hull_and_shield():
    assert HullSubsystem("Hull").GetObjType() is App.CT_HULL_SUBSYSTEM
    assert ShieldSubsystem("Shields").GetObjType() is App.CT_SHIELD_SUBSYSTEM


# ── 3. IsTypeOf for subsystems — the AI/Preprocessors.py:153 shape. ────────

def test_phaser_system_is_type_of_weapon_system():
    phaser = PhaserSystem("Phasers")
    assert phaser.IsTypeOf(App.CT_WEAPON_SYSTEM) == 1


def test_phaser_system_is_not_type_of_torpedo_system():
    phaser = PhaserSystem("Phasers")
    assert phaser.IsTypeOf(App.CT_TORPEDO_SYSTEM) == 0


def test_is_type_of_matches_another_subsystem_of_the_same_type():
    """AI/Preprocessors.py:153 shape:
        if pSystem.IsTypeOf(pExistingSystem.GetObjType()):
    Two independent subsystems of the same concrete type must match."""
    phaser_a = PhaserSystem("Phasers A")
    phaser_b = PhaserSystem("Phasers B")
    assert phaser_a.IsTypeOf(phaser_b.GetObjType()) == 1

    torps = TorpedoSystem("Torpedoes")
    assert torps.IsTypeOf(phaser_b.GetObjType()) == 0


# ── 3b. Leaf CT_WEAPON / CT_ENERGY_WEAPON: PhaserBank/PulseWeapon/
#    TractorBeam are leaf emitters (real SDK: EnergyWeapon(Weapon)), NOT
#    weapon systems, even though this engine's PhaserBank/PulseWeapon/
#    TractorBeam happen to inherit WeaponSystem (see
#    engine/appc/subsystem_types.py). Task 3b fix: these are now a
#    class-identity check via the shared table, independent of whether
#    SetProperty has run (same contract as every other CT_* — see
#    test_subsystem_istypeof.py:test_is_type_of_one_with_no_property) —
#    NOT a fallback to the historical source-property isinstance check,
#    which is retired. ─────────────────────────────────────────────────────

def test_is_type_of_leaf_energy_weapon_matches_ct_energy_weapon_and_ct_weapon():
    from engine.appc.properties import PhaserProperty
    bank = PhaserBank("Dorsal Phaser 1")
    bank.SetProperty(PhaserProperty("template"))
    assert bank.IsTypeOf(App.CT_ENERGY_WEAPON) == 1
    assert bank.IsTypeOf(App.CT_WEAPON) == 1


def test_is_type_of_leaf_energy_weapon_matches_even_without_property():
    """Class identity, not "has SetProperty run" — see
    test_subsystem_istypeof.py:test_is_type_of_one_with_no_property for the
    same contract on a top-level subsystem. A PhaserBank genuinely IS a
    CT_ENERGY_WEAPON the instant it's constructed."""
    bank = PhaserBank("Dorsal Phaser 1")
    # No SetProperty called.
    assert bank.IsTypeOf(App.CT_ENERGY_WEAPON) == 1
    assert bank.IsTypeOf(App.CT_WEAPON) == 1


def test_is_type_of_leaf_energy_weapon_is_not_a_weapon_system():
    """Minor 1 fix: PhaserBank/PulseWeapon/TractorBeam inherit WeaponSystem
    in this engine's class hierarchy (see engine/appc/weapon_subsystems.py),
    but they
    are leaf emitters INSIDE a weapon system, not weapon systems themselves
    — App.CT_WEAPON_SYSTEM must not match them."""
    from engine.appc.weapon_subsystems import PulseWeapon, TractorBeam
    assert PhaserBank("Dorsal Phaser 1").IsTypeOf(App.CT_WEAPON_SYSTEM) == 0
    assert PulseWeapon("Pulse 1").IsTypeOf(App.CT_WEAPON_SYSTEM) == 0
    assert TractorBeam("Tractor 1").IsTypeOf(App.CT_WEAPON_SYSTEM) == 0
    # The containing systems still answer 1.
    assert PhaserSystem("Phasers").IsTypeOf(App.CT_WEAPON_SYSTEM) == 1


def test_is_type_of_torpedo_tube_is_ct_weapon_not_ct_energy_weapon():
    """A TorpedoTube is a leaf Weapon, but not an EnergyWeapon (real SDK:
    TorpedoTube(Weapon), sibling of EnergyWeapon(Weapon), not a descendant
    of it) — torpedoes have no charge."""
    from engine.appc.weapon_subsystems import TorpedoTube
    tube = TorpedoTube("Tube 1")
    assert tube.IsTypeOf(App.CT_WEAPON) == 1
    assert tube.IsTypeOf(App.CT_ENERGY_WEAPON) == 0


def test_get_obj_type_for_leaf_weapon_emitters():
    """GetObjType() on a leaf emitter must resolve to its own leaf CT_*
    constant, not the containing system's CT_WEAPON_SYSTEM (the bug this
    task fixes: all three leaf classes used to collapse onto one type)."""
    from engine.appc.weapon_subsystems import PulseWeapon, TractorBeam, TorpedoTube
    assert PhaserBank("Dorsal Phaser 1").GetObjType() is App.CT_ENERGY_WEAPON
    assert PulseWeapon("Pulse 1").GetObjType() is App.CT_ENERGY_WEAPON
    assert TractorBeam("Tractor 1").GetObjType() is App.CT_ENERGY_WEAPON
    assert TorpedoTube("Tube 1").GetObjType() is App.CT_WEAPON


# ── 4. Non-regression: planet/sun IsTypeOf (ObjectClass.IsTypeOf) is
#    untouched by this change — see tests/unit/test_object_istypeof.py for
#    the full suite; spot-check the two headline assertions here too. ──────

def test_sun_is_type_of_planet_and_sun_unaffected():
    from engine.appc.planet import Planet, Sun
    p = Planet()
    s = Sun()
    assert p.IsTypeOf(App.CT_SUN) == 0
    assert s.IsTypeOf(App.CT_SUN) == 1
    assert s.IsTypeOf(App.CT_PLANET) == 1


# ── 5. End-to-end: the real SDK ConditionCriticalSystemBelow script,
#    against a real ship with a critical subsystem, flips status on damage
#    and clears it on repair. This is the point of the task. ──────────────

# ── 6. Minor 2 fix: the CT_* table is memoised, not rebuilt (and App
#    re-imported) on every IsTypeOf/GetObjType call. ────────────────────────

def test_ct_table_is_memoised_across_calls():
    from engine.appc.subsystem_types import _ct_table
    first = _ct_table()
    second = _ct_table()
    assert first is second, "_ct_table() rebuilt the table instead of caching it"


def test_condition_critical_system_below_flips_on_hull_damage_and_repair():
    _reset_app_state()
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    ship = ShipClass_Create("Test")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(100.0)
    hull.SetCondition(100.0)
    hull.SetCritical(1)
    ship.SetHull(hull)
    pSet.AddObjectToSet(ship, "Test Ship")
    App.g_kSetManager._sets["S"] = pSet

    cs = App.ConditionScript_Create(
        "Conditions.ConditionCriticalSystemBelow", "ConditionCriticalSystemBelow",
        "Test Ship", 0.5)
    assert cs._instance is not None, cs._init_error

    # Healthy hull, fraction 1.0 >= 0.5 threshold -> status starts false.
    assert cs.GetStatus() == 0

    # Damage the critical hull below the 0.5 fraction threshold -> flips true.
    hull.SetCondition(30.0)
    assert cs.GetStatus() == 1

    # Repair it back above the threshold -> status returns false.
    hull.SetCondition(80.0)
    assert cs.GetStatus() == 0
