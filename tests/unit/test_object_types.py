"""BC's `CT_*` object type-tags are INTS, and every consumer must accept them.

Our shim historically bound each `CT_` name to a Python CLASS, because all of
our type dispatch filters with `isinstance`.  Task 9 of the q13 constant sweep
gives the names BC's measured integers and puts an int<->class registry
(`engine.appc.object_types`) underneath the isinstance-based consumers.

The failure mode this file exists to catch is SILENT: `SetClass.
GetClassObjectList` used to `return []` for any non-type argument, so swapping
in the ints without the registry would have emptied every class-object query --
nebulae, planets and suns quietly missing from the scene push, no exception,
no failing assertion anywhere else in the suite.  Every test below therefore
asserts a POPULATED result, never merely "does not raise".

Values are never hand-typed here: they are read back from the generated,
measured table (`engine.appc.constants_generated`), so this file cannot
disagree with the dump.
"""
import pytest

import App
from engine.appc.constants_generated import MODULE_CONSTANTS
from engine.appc.object_types import class_for, tag_for, register, resolve_class


# ── 1. The constants themselves ───────────────────────────────────────────────

def test_ct_constants_are_bcs_int_tags():
    """Spot-check three of the 37 against the measured dump.  Not hand-typed:
    the expected value comes from the generated table."""
    assert App.CT_NEBULA == MODULE_CONSTANTS["CT_NEBULA"] == 32782
    assert App.CT_SHIP == MODULE_CONSTANTS["CT_SHIP"] == 32776
    assert App.CT_ASTEROID_FIELD == MODULE_CONSTANTS["CT_ASTEROID_FIELD"] == 32788


def test_every_ct_name_app_defines_is_an_int():
    """No `CT_` may still be a class: a mixed surface is the inconsistency the
    whole sweep exists to remove."""
    non_ints = {
        n: type(getattr(App, n)).__name__
        for n in dir(App)
        if n.startswith("CT_") and not isinstance(getattr(App, n), int)
    }
    assert non_ints == {}


def test_every_ct_name_app_defines_matches_the_measured_dump():
    for name, value in MODULE_CONSTANTS.items():
        if not name.startswith("CT_"):
            continue
        assert getattr(App, name) == value, name


# ── 2. The registry ───────────────────────────────────────────────────────────

def test_tags_round_trip_to_our_classes():
    from engine.appc.nebula import Nebula
    assert class_for(App.CT_NEBULA) is Nebula
    assert tag_for(Nebula) == App.CT_NEBULA


def test_registry_covers_every_previously_class_bound_constant():
    """The 37 names that used to BE classes must all still resolve to one --
    a missing row is a silently-emptied query, not an error."""
    from engine.appc.object_types import registered_tags
    for tag in registered_tags():
        assert isinstance(class_for(tag), type), tag
    # Sanity: the registry is not trivially empty or half-populated.
    assert len(registered_tags()) == 37


# Independent copy of App.py's `_CT_CLASS_FOR_TAG` table (App.py:384-425),
# transcribed here on purpose rather than imported from App.py: importing it
# would make this test blind to exactly the bug it exists to catch (a wrong
# class typed into that table). `registered_tags()` above only proves every
# tag resolves to SOME type, not the RIGHT one -- a wrong class on any one of
# the 37 rows (e.g. CT_DEBRIS -> AsteroidTile) passed every test on the
# branch before this one. Both sides are read off App itself (never
# hand-typed classes/tags from a different source), so a rename on either
# side shows up as an AttributeError here, not a silent pass.
_EXPECTED_CT_CLASS_ATTR = {
    "CT_SUBSYSTEM_PROPERTY":            "SubsystemProperty",
    "CT_POSITION_ORIENTATION_PROPERTY": "PositionOrientationProperty",
    "CT_OBJECT_EMITTER_PROPERTY":       "ObjectEmitterProperty",
    "CT_HULL_SUBSYSTEM":                "HullProperty",
    "CT_POWER_SUBSYSTEM":               "PowerProperty",
    "CT_SHIELD_SUBSYSTEM":              "ShieldProperty",
    "CT_SENSOR_SUBSYSTEM":              "SensorProperty",
    "CT_REPAIR_SUBSYSTEM":              "RepairSubsystemProperty",
    "CT_IMPULSE_ENGINE_SUBSYSTEM":      "ImpulseEngineProperty",
    "CT_WARP_ENGINE_SUBSYSTEM":         "WarpEngineProperty",
    "CT_CLOAKING_SUBSYSTEM":            "CloakingSubsystemProperty",
    "CT_PHASER_SYSTEM":                 "PhaserProperty",
    "CT_PULSE_WEAPON_SYSTEM":           "PulseWeaponProperty",
    "CT_TORPEDO_SYSTEM":                "TorpedoSystemProperty",
    "CT_TRACTOR_BEAM_SYSTEM":           "TractorBeamProperty",
    "CT_WEAPON_SYSTEM":                 "WeaponSystemProperty",
    "CT_WEAPON":                        "WeaponProperty",
    "CT_ENERGY_WEAPON":                 "EnergyWeaponProperty",
    "CT_SHIP":                          "ShipProperty",
    "CT_SHIP_SUBSYSTEM":                "ShipSubsystem",
    "CT_OBJECT":                        "ObjectClass",
    "CT_DAMAGEABLE_OBJECT":             "DamageableObject",
    "CT_CHARACTER":                     "CharacterClass",
    "CT_BACKDROP":                      "Backdrop",
    "CT_PROXIMITY_CHECK":               "ProximityCheck",
    "CT_PLANET":                        "Planet",
    "CT_SUN":                           "Sun",
    "CT_NEBULA":                        "Nebula",
    "CT_TORPEDO":                       "Torpedo",
    "CT_DEBRIS":                        "Debris",
    "CT_ASTEROID_FIELD":                "AsteroidField",
    "CT_ASTEROID_TILE":                 "AsteroidTile",
    "CT_GRID":                          "Grid",
    "CT_PLACEMENT":                     "Placement",
    "CT_MULTIPLAYER_GAME":              "MultiplayerGame",
    "CT_ST_MENU":                       "STMenu",
    "CT_SORTED_REGION_MENU":            "SortedRegionMenu",
}


# CT_ASTEROID_FIELD is the one deliberate exception to strict identity: the CT_
# loop registers App.py's bare `class AsteroidField(ObjectClass): pass`, and
# `App.AsteroidField` is THEN rebound (App.py:442-443, after the loop) to the
# richer engine.appc.asteroid_field.AsteroidField subclass, specifically so
# that `from App import AsteroidField` inside that module doesn't circular-
# import -- see App.py's own comment there. isinstance (what every real
# consumer uses) still matches because the subclass IS the registered base;
# identity does not, by design, so this row is checked as a subclass
# relationship instead of `is`.
_SUBCLASS_NOT_IDENTITY = {"CT_ASTEROID_FIELD"}


def test_every_ct_row_resolves_to_its_own_declared_class():
    """Coverage hole closed by the whole-branch review: a wrong class typed
    into any one of App.py's 37 `_CT_CLASS_FOR_TAG` rows would have passed
    every other test on the branch (only the row count and two behavioural
    pairs were pinned). Check `class_for(App.CT_X) is X` for all 37 (one
    documented exception: see `_SUBCLASS_NOT_IDENTITY`)."""
    import App
    assert len(App._CT_CLASS_FOR_TAG) == 37
    assert len(_EXPECTED_CT_CLASS_ATTR) == 37
    for ct_name, cls_attr in _EXPECTED_CT_CLASS_ATTR.items():
        registered = class_for(getattr(App, ct_name))
        expected = getattr(App, cls_attr)
        if ct_name in _SUBCLASS_NOT_IDENTITY:
            assert issubclass(expected, registered), ct_name
        else:
            assert registered is expected, ct_name


def test_class_for_returns_none_for_an_unknown_tag():
    assert class_for(0x7FFF) is None


def test_resolve_class_accepts_both_representations():
    from engine.appc.nebula import Nebula
    assert resolve_class(App.CT_NEBULA) is Nebula
    assert resolve_class(Nebula) is Nebula
    assert resolve_class(0x7FFF) is None
    assert resolve_class(App.CT_NEWLY_INVENTED_THING_THAT_DOES_NOT_EXIST) is None
    assert resolve_class(None) is None


def test_bool_is_not_treated_as_a_tag():
    """`True` is an int in Python.  A stray boolean must not resolve to
    whatever class happens to sit at tag 1."""
    assert class_for(True) is None
    assert class_for(False) is None


def test_an_empty_registry_raises_instead_of_answering_no_matches():
    """`import App` SUCCEEDING is not proof the CT_ block ran.

    A present-but-partially-initialised `App` in `sys.modules` is handed back
    by the import statement without being re-executed, so the registry would
    stay empty and every consumer would answer `[]`/`0` with no exception --
    reopening, inside this module, the exact silent hole it exists to close.
    `_populating` cannot catch that: it only guards re-entry back through
    `_ensure_populated`, not re-entry via another import path.
    """
    import sys
    import types
    from engine.appc import object_types

    saved_app = sys.modules.get("App")
    saved_by_tag = dict(object_types._BY_TAG)
    saved_by_class = dict(object_types._BY_CLASS)
    try:
        sys.modules["App"] = types.ModuleType("App")   # no CT_ block
        object_types._BY_TAG.clear()
        object_types._BY_CLASS.clear()
        with pytest.raises(RuntimeError, match="before App.py's CT_ block ran"):
            object_types.class_for(App.CT_NEBULA)
    finally:
        if saved_app is not None:
            sys.modules["App"] = saved_app
        else:                                           # pragma: no cover
            sys.modules.pop("App", None)
        object_types._BY_TAG.clear()
        object_types._BY_TAG.update(saved_by_tag)
        object_types._BY_CLASS.clear()
        object_types._BY_CLASS.update(saved_by_class)
    # No residue: the real registry is back and answering.
    from engine.appc.nebula import Nebula
    assert class_for(App.CT_NEBULA) is Nebula
    assert sys.modules["App"] is App


def test_register_binds_both_directions():
    """The registry is module-global, so this probe MUST clean up after
    itself -- tests run in random order here and
    test_registry_covers_every_previously_class_bound_constant pins the
    exact row count."""
    from engine.appc import object_types

    class _Probe:
        pass
    probe_tag = 0x7EEE
    register(probe_tag, _Probe)
    try:
        assert class_for(probe_tag) is _Probe
        assert tag_for(_Probe) == probe_tag
    finally:
        object_types._BY_TAG.pop(probe_tag, None)
        object_types._BY_CLASS.pop(_Probe, None)
    assert class_for(probe_tag) is None


# ── 3. SetClass.GetClassObjectList -- the silent-emptying regression ──────────

def _set_with_a_nebula():
    from engine.appc.sets import SetClass
    from engine.appc.nebula import Nebula
    s = SetClass()
    s.SetName("test")
    neb = Nebula()
    s.AddObjectToSet(neb, "neb")
    return s, neb


def test_get_class_object_list_accepts_an_int_tag():
    """The regression this task exists to prevent: sets.py used to return []
    for any non-type argument, so int tags would silently empty every query."""
    s, neb = _set_with_a_nebula()
    assert s.GetClassObjectList(App.CT_NEBULA) == [neb]


def test_get_class_object_list_still_accepts_a_class():
    """Back-compat: engine code passing a class must keep working."""
    from engine.appc.nebula import Nebula
    s, neb = _set_with_a_nebula()
    assert s.GetClassObjectList(Nebula) == [neb]


def test_unknown_tag_returns_empty_not_everything():
    s, _ = _set_with_a_nebula()
    assert s.GetClassObjectList(0x7FFF) == []


def test_get_class_object_list_ct_ship_still_yields_live_ships():
    """CT_SHIP maps to ShipProperty (the property TEMPLATE) but every SDK and
    host-loop call site wants live ShipClass instances -- host_loop.py:8063
    feeds this straight into the nebula concealment pass."""
    from engine.appc.sets import SetClass
    from engine.appc.ships import ShipClass_Create
    s = SetClass()
    s.SetName("ships")
    ship = ShipClass_Create("Ship")
    s.AddObjectToSet(ship, "Ship")
    assert s.GetClassObjectList(App.CT_SHIP) == [ship]


def test_get_class_object_list_planet_and_sun_partition_correctly():
    """The renderer scene push and the Helm orbit menu both depend on this:
    Sun(Planet), so CT_PLANET returns both and CT_SUN only the sun."""
    from engine.appc.sets import SetClass
    from engine.appc.planet import Planet, Sun
    s = SetClass()
    s.SetName("system")
    p, sun = Planet(), Sun()
    s.AddObjectToSet(p, "p")
    s.AddObjectToSet(sun, "sun")
    assert s.GetClassObjectList(App.CT_PLANET) == [p, sun]
    assert s.GetClassObjectList(App.CT_SUN) == [sun]


# ── 4. ObjectClass.IsTypeOf ───────────────────────────────────────────────────

def test_object_is_type_of_accepts_int_tags():
    from engine.appc.planet import Planet, Sun
    p, s = Planet(), Sun()
    assert s.IsTypeOf(App.CT_SUN) == 1
    assert s.IsTypeOf(App.CT_PLANET) == 1
    assert p.IsTypeOf(App.CT_SUN) == 0


def test_object_is_type_of_returns_zero_for_an_unknown_tag():
    from engine.appc.planet import Planet
    assert Planet().IsTypeOf(0x7FFF) == 0


# ── 5. Subsystem dispatch -- 104 call sites ──────────────────────────────────

def test_start_get_subsystem_match_accepts_an_int_tag():
    from engine.appc.ships import ShipClass_Create
    from engine.appc.subsystems import HullSubsystem
    ship = ShipClass_Create("Test")
    hull = HullSubsystem("Hull")
    ship.SetHull(hull)
    it = ship.StartGetSubsystemMatch(App.CT_HULL_SUBSYSTEM)
    assert ship.GetNextSubsystemMatch(it) is hull


def test_get_obj_type_returns_an_int_that_is_type_of_accepts():
    """AI/Preprocessors.py:153 feeds GetObjType() straight back into
    IsTypeOf(); Conditions/ConditionCriticalSystemBelow.py:76 feeds it into
    ConditionScript_Create -> StartGetSubsystemMatch.  Whatever comes out one
    end must be accepted at the other."""
    from engine.appc.weapon_subsystems import PhaserSystem
    a, b = PhaserSystem("A"), PhaserSystem("B")
    assert isinstance(a.GetObjType(), int)
    assert a.GetObjType() == App.CT_PHASER_SYSTEM
    assert b.IsTypeOf(a.GetObjType()) == 1


def test_subsystem_is_type_of_still_accepts_a_property_class():
    """Back-compat for engine callers (and this suite) that pass the Property
    class directly rather than the tag."""
    from engine.appc.subsystems import ShieldSubsystem
    from engine.appc.properties import ShieldProperty, SensorProperty
    s = ShieldSubsystem("Shields")
    assert s.IsTypeOf(ShieldProperty) == 1
    assert s.IsTypeOf(SensorProperty) == 0


# ── 6. Property-set queries ───────────────────────────────────────────────────

def test_get_properties_by_type_accepts_an_int_tag():
    from engine.appc.properties import (
        TGModelPropertySet, ObjectEmitterProperty, HullProperty)
    pset = TGModelPropertySet()
    emitter = ObjectEmitterProperty("emitter")
    pset.AddToSet("Scene Root", emitter)
    pset.AddToSet("Scene Root", HullProperty("hull"))
    assert list(pset.GetPropertiesByType(App.CT_OBJECT_EMITTER_PROPERTY)) == [emitter]
    # Back-compat: a class still works.
    assert list(pset.GetPropertiesByType(ObjectEmitterProperty)) == [emitter]


def test_get_properties_by_type_stays_loud_for_an_unresolvable_type():
    """Unlike GetClassObjectList (whose BC contract is "no matches"), this one
    raised TypeError out of isinstance() for a _NamedStub before this task and
    must keep doing so. Turning it into a silent empty list would hide an
    undefined CT_ name -- the exact bug class the sweep exists to remove."""
    from engine.appc.properties import TGModelPropertySet, HullProperty
    pset = TGModelPropertySet()
    pset.AddToSet("Scene Root", HullProperty("hull"))
    with pytest.raises(TypeError):
        pset.GetPropertiesByType(App.CT_NEWLY_INVENTED_THING_THAT_DOES_NOT_EXIST)
    with pytest.raises(TypeError):
        pset.GetPropertiesByType(0x7FFF)


# ── 7. Collision avoidance blacklist ──────────────────────────────────────────

def test_dont_avoid_types_resolves_to_real_classes():
    """SDK lDontAvoidTypes.  If this collapses to an empty tuple, proximity
    checks / torpedoes / nebulae all become avoidance obstacles -- silently."""
    from engine.appc.collision_avoidance import (
        _dont_avoid_types, _DONT_AVOID_TYPE_NAMES)
    types_ = _dont_avoid_types()
    assert len(types_) == len(_DONT_AVOID_TYPE_NAMES)
    assert all(isinstance(t, type) for t in types_)
    from engine.appc.nebula import Nebula
    assert isinstance(Nebula(), types_)


# ── 8. Memoisation ordering ───────────────────────────────────────────────────

def test_ct_table_cannot_cache_pre_correction_values():
    """`_CT_TABLE_CACHE` is memoised.  Built from live `App.CT_*` it could in
    principle be filled before the constant table was applied and then be
    wrong forever with nothing to notice.  It is built from the generated
    table directly, so every row equals the measured value by construction."""
    from engine.appc.subsystem_types import _ct_table
    for tag, _cls in _ct_table():
        assert isinstance(tag, int)
    tags = [t for t, _ in _ct_table()]
    assert tags == [MODULE_CONSTANTS[n] for n in (
        "CT_PHASER_SYSTEM", "CT_PULSE_WEAPON_SYSTEM", "CT_TRACTOR_BEAM_SYSTEM",
        "CT_TORPEDO_SYSTEM", "CT_WEAPON_SYSTEM", "CT_ENERGY_WEAPON",
        "CT_WEAPON", "CT_SENSOR_SUBSYSTEM", "CT_IMPULSE_ENGINE_SUBSYSTEM",
        "CT_WARP_ENGINE_SUBSYSTEM", "CT_SHIELD_SUBSYSTEM", "CT_HULL_SUBSYSTEM",
        "CT_POWER_SUBSYSTEM", "CT_REPAIR_SUBSYSTEM", "CT_CLOAKING_SUBSYSTEM",
        "CT_SHIP_SUBSYSTEM")]
