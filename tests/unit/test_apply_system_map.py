"""Applying a system map's authored radius/position when a region's set is
created.

engine.systems.resolve answers which region a set belongs to; this module
(engine.systems.apply_map) does the substitution itself: each body the map
names for that region takes the map's radius and set-local position, the
same object BC placed -- nothing created, nothing deleted, no model swapped.
"""
import pytest

import App
from engine.appc.planet import Planet_Create, Sun, Sun_Create
from engine.systems import apply_map, resolve
from engine.systems.map import load


def _loc(obj):
    p = obj.GetWorldLocation()
    return (p.x, p.y, p.z)


def _add_planet(pSet, name, radius, at):
    p = Planet_Create(radius, "")
    p.SetTranslateXYZ(*at)
    pSet.AddObjectToSet(p, name)
    return p


def _fake_set_with_planet(name, radius, at):
    pSet = App.SetClass_Create()
    _add_planet(pSet, name, radius, at)
    return pSet


def _fake_set_with_sun(at, radius):
    pSet = App.SetClass_Create()
    sun = Sun_Create(radius)
    sun.SetTranslateXYZ(*at)
    pSet.AddObjectToSet(sun, "Sun")
    return pSet


def _fake_set_with_authored_sun(radius, atmosphere, damage):
    """A set holding a Sun built the way BC's own placement scripts build one,
    with all three geometry/damage arguments passed."""
    pSet = App.SetClass_Create()
    sun = Sun_Create(radius, atmosphere, damage, "", "")
    pSet.AddObjectToSet(sun, "Sun")
    return pSet


def _only_sun(pSet):
    suns = [obj for obj in pSet._objects.values() if isinstance(obj, Sun)]
    assert len(suns) == 1, "expected exactly one Sun in the set"
    return suns[0]


def test_a_body_takes_the_maps_radius_and_set_local_position():
    """Ona 1's planet is 110 GU at 538 GU in BC, and 2,200 GU at ~6,000 GU
    here -- the same object, re-authored around the region's anchor."""
    pSet = _fake_set_with_planet("Ona 1", radius=110.0, at=(0.0, 538.0, 0.0))
    assert apply_map.apply_to_set(pSet, "Ona1") is True
    body = pSet.GetObject("Ona 1")
    m, r = resolve.for_set("Ona1")
    expected = tuple(a - b for a, b in zip(m.body("Ona 1").position_gu, r.anchor_gu))
    assert body.GetRadius() == pytest.approx(m.body("Ona 1").radius_gu)
    assert _loc(body) == pytest.approx(expected)


def test_a_set_that_is_not_a_region_is_untouched():
    pSet = _fake_set_with_planet("Whatever", radius=110.0, at=(0.0, 538.0, 0.0))
    assert apply_map.apply_to_set(pSet, "QuickBattle") is False
    assert pSet.GetObject("Whatever").GetRadius() == pytest.approx(110.0)


def test_an_existing_sun_is_moved_to_the_maps_star():
    pSet = _fake_set_with_sun(at=(70000.0, 0.0, 0.0), radius=4000.0)
    apply_map.apply_to_set(pSet, "Ona1")
    m, r = resolve.for_set("Ona1")
    star = m.body("Ona")
    assert _loc(_only_sun(pSet)) == pytest.approx(tuple(-c for c in r.anchor_gu))
    assert _only_sun(pSet).GetRadius() == pytest.approx(star.radius_gu)


def test_a_set_with_no_sun_gets_one():
    """Belaruz and Vesuvi author no Sun_Create and still light their scenes."""
    pSet = _fake_set_with_planet("Belaruz 2", radius=120.0, at=(0.0, 500.0, 0.0))
    apply_map.apply_to_set(pSet, "Belaruz2")
    sun = _only_sun(pSet)
    assert sun is not None
    assert sun.GetRadius() == pytest.approx(load("belaruz").body("Belaruz").radius_gu)


def test_a_body_the_map_does_not_name_is_left_alone():
    pSet = _fake_set_with_planet("Ona 1", radius=110.0, at=(0.0, 538.0, 0.0))
    _add_planet(pSet, "Mystery Rock", radius=40.0, at=(10.0, 20.0, 30.0))
    apply_map.apply_to_set(pSet, "Ona1")
    rock = pSet.GetObject("Mystery Rock")
    assert rock.GetRadius() == pytest.approx(40.0)
    assert _loc(rock) == pytest.approx((10.0, 20.0, 30.0))


def test_a_body_lookup_is_scoped_to_its_own_region_not_the_whole_system():
    """"Moon 1" names a body in BOTH Geble3 and Geble4, at different radii
    and positions. Applying Geble4's map to a set must use Geble4's Moon 1,
    never fall through to Geble3's just because it comes first in the
    system's body list."""
    pSet = _fake_set_with_planet("Geble 4", radius=200.0, at=(0.0, 0.0, 0.0))
    _add_planet(pSet, "Moon 1", radius=50.0, at=(1.0, 2.0, 3.0))
    assert apply_map.apply_to_set(pSet, "Geble4") is True

    m, r = resolve.for_set("Geble4")
    geble4_moon = next(
        b for b in m.bodies if b.name == "Moon 1" and b.owner_region == "Geble4")
    geble3_moon = next(
        b for b in m.bodies if b.name == "Moon 1" and b.owner_region == "Geble3")
    assert geble4_moon.radius_gu != geble3_moon.radius_gu

    moon = pSet.GetObject("Moon 1")
    expected = tuple(a - b for a, b in zip(geble4_moon.position_gu, r.anchor_gu))
    assert moon.GetRadius() == pytest.approx(geble4_moon.radius_gu)
    assert _loc(moon) == pytest.approx(expected)


def test_apply_to_set_degrades_to_false_for_a_none_set():
    assert apply_map.apply_to_set(None, "Ona1") is False


def test_apply_to_set_degrades_to_false_for_an_object_with_no_getobject():
    class _NotASet:
        pass
    assert apply_map.apply_to_set(_NotASet(), "Ona1") is False


# ── A created star gets ALL of Sun_Create's arguments ────────────────────────
#
# Belaruz and Vesuvi are the two systems BC never gave a Sun_Create, so theirs
# is the only star this code constructs. Sun_Create(radius) alone drops four of
# five arguments: no atmosphere radius (no keep-out band), zero environmental
# damage (flying into the star is free, where every authored BC sun does 500/s)
# and no textures. The values below are SURVEYED from BC's own authored calls
# under the SDK's Systems/ tree, read as text -- see apply_map's own comments.

def test_a_created_star_gets_bcs_authored_atmosphere_and_damage():
    """82 of BC's 84 fully-specified Sun_Create calls pass atmosphere ==
    radius; 83 of 84 pass 500 damage/sec. A created star must do the same or
    it is a decorative light with no physics around it."""
    pSet = _fake_set_with_planet("Belaruz 2", radius=120.0, at=(0.0, 500.0, 0.0))
    apply_map.apply_to_set(pSet, "Belaruz2")
    sun = _only_sun(pSet)
    star = load("belaruz").body("Belaruz")
    assert sun.GetAtmosphereRadius() == pytest.approx(star.radius_gu)
    assert sun.GetEnvironmentalHullDamage() == pytest.approx(500.0)


def test_a_created_stars_textures_come_from_the_maps_star_class():
    """Vesuvi's override declares a "remnant_hot" blue-white star and that is
    the whole visual point of the override. It must reach the renderer."""
    pSet = _fake_set_with_planet("Geki", radius=200.0, at=(0.0, 500.0, 0.0))
    assert apply_map.apply_to_set(pSet, "Vesuvi5") is True
    sun = _only_sun(pSet)
    assert sun.GetModelPath() == "data/Textures/SunBlueWhite.tga"
    assert sun._flare_texture == "data/Textures/Effects/SunFlaresWhite.tga"


def test_a_white_star_takes_bcs_default_texture_not_a_guess():
    """BC's five white-star systems -- Biranu, Nepenthe, Itari, Riha, Poseidon
    -- all call Sun_Create with NO texture arguments, so the engine's own
    SunBase.tga fallback is what "white" is supposed to look like. Belaruz is
    white. Empty is the authored answer here, not a missing one."""
    pSet = _fake_set_with_planet("Belaruz 2", radius=120.0, at=(0.0, 500.0, 0.0))
    apply_map.apply_to_set(pSet, "Belaruz2")
    sun = _only_sun(pSet)
    assert sun.GetModelPath() == ""
    assert sun._flare_texture == ""


def test_every_star_class_in_the_maps_has_an_explicit_texture_entry():
    """The table falls back to BC's default for an unknown class, which is
    safe but silent. A class that the maps actually use must be a deliberate
    row, so regenerating the maps with a new star class fails here instead of
    quietly rendering a generic sun."""
    from engine.systems.map import available

    classes = {
        b.appearance.star_class
        for system in available()
        for b in load(system).bodies
        if b.orbits is None and b.appearance.star_class
    }
    assert classes, "no star classes found in the maps"
    missing = sorted(c for c in classes if c not in apply_map.STAR_TEXTURES)
    assert not missing, f"star classes with no texture decision: {missing}"


# ── A REPOSITIONED star keeps its atmosphere proportional ───────────────────
#
# The celestial rescale is ours, not BC's: Ona's authored sun goes 5,000 ->
# 10,000 GU here. BC's own data was self-consistent before we touched it --
# 82 of 84 authored Sun_Create calls pass atmosphere EXACTLY equal to radius --
# so leaving the atmosphere at its authored value after doubling the body puts
# the keep-out band INSIDE the star, across roughly thirty authored systems.
# The ratio is preserved rather than forced to 1.0, because two of the 84 are
# deliberately not 1.0 and BC's authoring is what this module follows.
#
# Environmental damage is deliberately NOT touched on a repositioned sun. BC
# authored those values and rescaling geometry is no reason to restate them.

def test_a_repositioned_sun_keeps_its_atmosphere_proportional_to_its_radius():
    """Ona1_S authors Sun_Create(5000.0, 5000, 500, ...) and the map makes the
    star 10,000 GU. An atmosphere left at 5,000 is a keep-out band buried
    inside the star it is supposed to keep ships out of."""
    pSet = _fake_set_with_authored_sun(radius=5000.0, atmosphere=5000.0,
                                       damage=500.0)
    assert apply_map.apply_to_set(pSet, "Ona1") is True
    sun = _only_sun(pSet)
    star = load("ona").body("Ona")
    assert sun.GetRadius() == pytest.approx(star.radius_gu)
    assert sun.GetAtmosphereRadius() == pytest.approx(star.radius_gu)


def test_a_repositioned_sun_preserves_a_ratio_that_is_not_one():
    """Itari2_S is one of BC's two exceptions: Sun_Create(5000.0, 6000, 500),
    an atmosphere 1.2x the body. Rescaling to the map's 14,000 GU star must
    carry that authored 1.2 through, not flatten it to the 1.0 majority."""
    pSet = _fake_set_with_authored_sun(radius=5000.0, atmosphere=6000.0,
                                       damage=500.0)
    assert apply_map.apply_to_set(pSet, "Itari2") is True
    sun = _only_sun(pSet)
    star = load("itari").body("Itari")
    assert sun.GetRadius() == pytest.approx(star.radius_gu)
    assert sun.GetAtmosphereRadius() == pytest.approx(star.radius_gu * 1.2)


def test_a_repositioned_sun_keeps_bcs_own_environmental_damage():
    """OmegaDraconis1_S is BC's other exception -- Sun_Create(360.0, 180, 360),
    half-atmosphere AND 360 damage/sec. Both are authored. Geometry rescales;
    the damage value is BC's and stays exactly as written."""
    pSet = _fake_set_with_authored_sun(radius=360.0, atmosphere=180.0,
                                       damage=360.0)
    assert apply_map.apply_to_set(pSet, "OmegaDraconis1") is True
    sun = _only_sun(pSet)
    star = load("omegadraconis").body("OmegaDraconis")
    assert sun.GetAtmosphereRadius() == pytest.approx(star.radius_gu * 0.5)
    assert sun.GetEnvironmentalHullDamage() == pytest.approx(360.0)
