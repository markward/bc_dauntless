"""BC's damage-geometry switches, which were truthy stubs.

App.DamageableObject_{Set,Is}{DamageGeometry,VolumeDamageGeometry,
BreakableComponents}Enabled are real Appc surface. Ours were `_NamedStub`s, so
`IsVolumeDamageGeometryEnabled()` returned a truthy stub object rather than a
flag -- the classic silent-stub bug class this project keeps a heatmap for.

E3M1.py:3001-3003 reads all three into g_pVisibleDamageState to save and
restore damage state around a cutscene.

Policy: in Dauntless damage is always on, so all three default enabled, but the
setters are honoured so a mission can still suppress damage for a cutscene.
Breakable components additionally require a hull larger than the maximum
combat carve radius.
"""
import pytest

import App
from engine.appc import damage_geometry


class FakeShip:
    def __init__(self, radius_gu):
        self._radius = radius_gu

    def GetRadius(self):
        return self._radius


@pytest.fixture(autouse=True)
def _reset():
    damage_geometry.reset()
    yield
    damage_geometry.reset()


# --- the flags themselves ---------------------------------------------------

def test_all_three_default_on():
    """In Dauntless damage is always on."""
    assert damage_geometry.is_damage_geometry_enabled() == 1
    assert damage_geometry.is_volume_damage_geometry_enabled() == 1
    assert damage_geometry.is_breakable_components_enabled() == 1


def test_setters_round_trip():
    damage_geometry.set_damage_geometry_enabled(0)
    assert damage_geometry.is_damage_geometry_enabled() == 0
    damage_geometry.set_damage_geometry_enabled(1)
    assert damage_geometry.is_damage_geometry_enabled() == 1


def test_the_three_flags_are_independent():
    """E3M1 saves and restores them separately; sharing state would restore
    the wrong values."""
    damage_geometry.set_volume_damage_geometry_enabled(0)
    assert damage_geometry.is_volume_damage_geometry_enabled() == 0
    assert damage_geometry.is_damage_geometry_enabled() == 1
    assert damage_geometry.is_breakable_components_enabled() == 1


def test_getters_return_ints_not_objects():
    """The bug being fixed: a truthy stub OBJECT passed `if x:` and was stored
    into g_pVisibleDamageState, so the restore wrote a stub back."""
    for getter in (damage_geometry.is_damage_geometry_enabled,
                   damage_geometry.is_volume_damage_geometry_enabled,
                   damage_geometry.is_breakable_components_enabled):
        assert type(getter()) is int


# --- the App-module surface -------------------------------------------------

@pytest.mark.parametrize("name", [
    "DamageableObject_SetDamageGeometryEnabled",
    "DamageableObject_IsDamageGeometryEnabled",
    "DamageableObject_SetVolumeDamageGeometryEnabled",
    "DamageableObject_IsVolumeDamageGeometryEnabled",
    "DamageableObject_SetBreakableComponentsEnabled",
    "DamageableObject_IsBreakableComponentsEnabled",
])
def test_app_surface_is_real_not_a_stub(name):
    fn = getattr(App, name)
    assert type(fn).__name__ != "_NamedStub", f"{name} is still a stub"


def test_app_setter_drives_the_flag():
    App.DamageableObject_SetVolumeDamageGeometryEnabled(0)
    assert App.DamageableObject_IsVolumeDamageGeometryEnabled() == 0
    App.DamageableObject_SetVolumeDamageGeometryEnabled(1)
    assert App.DamageableObject_IsVolumeDamageGeometryEnabled() == 1


def test_e3m1_save_and_restore_round_trips():
    """The exact shape of E3M1.py:2998-3022."""
    saved = [App.DamageableObject_IsDamageGeometryEnabled(),
             App.DamageableObject_IsVolumeDamageGeometryEnabled(),
             App.DamageableObject_IsBreakableComponentsEnabled()]
    App.DamageableObject_SetDamageGeometryEnabled(0)
    App.DamageableObject_SetVolumeDamageGeometryEnabled(0)
    App.DamageableObject_SetBreakableComponentsEnabled(0)
    App.DamageableObject_SetDamageGeometryEnabled(saved[0])
    App.DamageableObject_SetVolumeDamageGeometryEnabled(saved[1])
    App.DamageableObject_SetBreakableComponentsEnabled(saved[2])
    assert App.DamageableObject_IsDamageGeometryEnabled() == 1
    assert App.DamageableObject_IsVolumeDamageGeometryEnabled() == 1
    assert App.DamageableObject_IsBreakableComponentsEnabled() == 1


# --- the radius gate --------------------------------------------------------

# Bounding radii MEASURED from the stock hull NIFs, 2026-09-08, in GU.
#
# The floor was 2.381 (a Cardassian Galor) until 2026-09-23 and is now 0.6,
# derived from the carve curve rather than a reference ship -- a hull must be
# meaningfully larger than the maximum combat carve (kHullCarveRadiusMaxGu,
# 0.15 GU). Five ships moved into BREAKABLE: BirdOfPrey, Freighter,
# CardFreighter, Marauder and Galor.
BREAKABLE = [
    ("BirdOfPrey", 1.335), ("Freighter", 1.955), ("CardFreighter", 2.002),
    ("Marauder", 2.020), ("Galor", 2.381), ("Nebula", 2.416),
    ("Akira", 2.552), ("Ambassador", 3.144),
    ("Keldon", 3.160), ("Transport", 3.238), ("KessokLight", 3.340),
    ("Galaxy", 3.500), ("Vorcha", 3.523), ("Sovereign", 3.807),
    ("CardHybrid", 4.960), ("Warbird", 6.516), ("KessokHeavy", 7.500),
]
# The Shuttle alone stays out: its whole hull is a 5x6x4 voxel grid, too few
# cells for connectivity to yield a component worth spawning.
NOT_BREAKABLE = [
    ("Shuttle", 0.141),
]


@pytest.mark.parametrize("name,radius", BREAKABLE)
def test_ships_above_the_carve_derived_floor_are_breakable(name, radius):
    assert damage_geometry.breakables_allowed_for(FakeShip(radius)), name


@pytest.mark.parametrize("name,radius", NOT_BREAKABLE)
def test_hulls_no_larger_than_a_worked_breach_are_not(name, radius):
    assert not damage_geometry.breakables_allowed_for(FakeShip(radius)), name


def test_the_floor_is_pinned_and_the_bird_of_prey_clears_it():
    """Pins the THRESHOLD CONSTANT itself, so changing BREAKABLE_MIN_RADIUS_GU
    fails here and names the value that moved.

    The Bird of Prey is called out by name because it is the ship this floor
    was lowered FOR -- it sits at 1.335, a bit over twice the floor, and a
    regression that restored the old 2.381 would silently make it unbreakable
    again while every larger ship kept working.

    This does NOT guard how GetRadius is derived: the radii above are literals
    hardcoded in this file, not read from GetRadius or a hull asset, so a
    change to the derivation of GetRadius (an open question against the
    clean-room reference) would not be caught here or by any other test in
    this file -- re-sorting the fleet would happen silently."""
    assert damage_geometry.BREAKABLE_MIN_RADIUS_GU == pytest.approx(0.6)
    assert damage_geometry.breakables_allowed_for(FakeShip(1.335))   # BirdOfPrey
    assert not damage_geometry.breakables_allowed_for(FakeShip(0.6))  # exclusive
    assert not damage_geometry.breakables_allowed_for(FakeShip(0.141))  # Shuttle


def test_the_global_flag_overrides_the_radius_gate():
    """A mission disabling breakables must disable them for a Sovereign too."""
    damage_geometry.set_breakable_components_enabled(0)
    assert not damage_geometry.breakables_allowed_for(FakeShip(3.807))


def test_a_ship_without_a_radius_is_not_breakable():
    assert not damage_geometry.breakables_allowed_for(object())
