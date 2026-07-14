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


# ── 3b. IsTypeOf fallback: CT_* constants OUTSIDE the shared subsystem
#    table (leaf Weapon-hierarchy Property classes, e.g. CT_ENERGY_WEAPON)
#    must keep answering via the historical source-property isinstance
#    check, so leaf emitters (PhaserBank, TorpedoTube, ...) whose
#    _property genuinely IS e.g. a PhaserProperty are unaffected by this
#    task (AI/Preprocessors.py:993 RateSubsystemForTargeting,
#    loadspacehelper.py:229). ─────────────────────────────────────────────

def test_is_type_of_falls_back_to_property_for_ct_outside_the_table():
    from engine.appc.properties import PhaserProperty
    bank = PhaserBank("Dorsal Phaser 1")
    bank.SetProperty(PhaserProperty("template"))
    assert bank.IsTypeOf(App.CT_ENERGY_WEAPON) == 1
    assert bank.IsTypeOf(App.CT_WEAPON) == 1


def test_is_type_of_falls_back_to_zero_with_no_property_for_ct_outside_the_table():
    bank = PhaserBank("Dorsal Phaser 1")
    # No SetProperty called.
    assert bank.IsTypeOf(App.CT_ENERGY_WEAPON) == 0


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
