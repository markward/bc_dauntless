"""Every checked-in system map must validate against the live SDK.

This is the gate rule: a bad regeneration fails the build here rather than
surfacing as a broken mission weeks later. It is vacuous until the first map
is committed, which is deliberate -- the file lands with Ona in the same task.
"""
import pytest

from engine.systems.map import available, load
from engine.systems.validate import validate
from tools.systems.survey import survey_system


@pytest.mark.parametrize("name", available() or ["__none__"])
def test_checked_in_map_validates(name):
    if name == "__none__":
        pytest.skip("no system maps checked in yet")
    m = load(name)
    sdk = survey_system(m.system)
    from tools.gen_system_maps import pins_from
    problems = validate(m, sdk_set_names=[r.set_name for r in sdk.regions
                                          if r.menu_listed],
                        pins=pins_from(m))
    assert problems == [], "\n".join(f"{p.rule}: {p.detail}" for p in problems)


def test_ona_is_checked_in():
    assert "ona" in available()


def test_ona_covers_all_three_bc_sets():
    m = load("ona")
    assert sorted(r.set_name for r in m.regions) == ["Ona1", "Ona2", "Ona3"]


def test_ona_has_exactly_one_sun():
    m = load("ona")
    assert len([b for b in m.bodies if b.orbits is None]) == 1


def test_ona_planets_are_large():
    m = load("ona")
    planets = [b for b in m.bodies if b.owner_region is not None]
    assert len(planets) == 3
    # BC authored these at 90 GU; the whole point is that they are now big.
    assert all(b.radius_gu >= 1000.0 for b in planets)


@pytest.mark.parametrize("name", available() or ["__none__"])
def test_regenerating_any_map_is_idempotent(name):
    """Running the generator again must reproduce the committed file byte for
    byte, so a regeneration diff shows only real changes.

    Parametrised over every committed map, not just Ona: a bug in a layout
    rule that only bites when player_start_gu is non-zero would pass under
    Ona alone, since all three of its Player Starts sit at the origin. 51 of
    the 90 real regions do not.

    Compared against the file's ACTUAL BYTES, not against
    `to_json(load(name))`. Normalising both sides through `to_json` makes the
    committed file invisible to this test: adding a field to `SystemMap` made
    `save()` start emitting a new key, and because `load()` supplies the
    default and `to_json` re-emits it, 30 stale checked-in files compared
    equal to freshly generated ones. The on-disk bytes are what the rest of
    the project reads, so they are what this test must compare."""
    if name == "__none__":
        pytest.skip("no system maps checked in yet")
    from engine.systems.map import map_dir, to_json
    from tools.gen_system_maps import generate
    committed = load(name)
    fresh, _notes = generate(committed.system)
    on_disk = (map_dir() / f"{name}.json").read_text(encoding="utf-8")
    assert to_json(fresh) == on_disk


def test_overrides_survive_regeneration():
    from tools.gen_system_maps import _merge_overrides
    from engine.systems.map import SystemMap
    old = SystemMap(system="Ona", overrides={"note": "hand tuned"})
    fresh = SystemMap(system="Ona")
    _merge_overrides(fresh, old)
    assert fresh.overrides == {"note": "hand tuned"}


def test_a_malformed_existing_map_is_never_overwritten(tmp_path, monkeypatch):
    """The overrides block is the only place hand art-direction lives, and the
    generator writes straight back over the file it read. So an unreadable map
    must stop the write, not be treated as "no prior map" -- otherwise one bad
    character silently replaces a human's work with a fresh layout."""
    import engine.systems.map as smap
    from tools.gen_system_maps import main
    maps = tmp_path / "maps"
    maps.mkdir()
    bad = maps / "ona.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(smap, "map_dir", lambda: maps)
    rc = main(["--system", "Ona"])
    assert rc != 0
    assert bad.read_text(encoding="utf-8") == "{ this is not json"


def test_pins_from_reads_the_overrides_block():
    """Pins are hand-declared in overrides -- there are only two across all 89
    regions, and one of them is keyed to a waypoint no body occupies."""
    from engine.systems.map import SystemMap
    from tools.gen_system_maps import pins_from
    assert pins_from(SystemMap(system="Ona")) is None
    assert pins_from(SystemMap(system="Ona", overrides={"pins": {}})) is None
    m = SystemMap(system="Prendel",
                  overrides={"pins": {"Prendel3/Moon 2": [400.0, 5000.0, 0.0]}})
    assert pins_from(m) == {"Prendel3/Moon 2": (400.0, 5000.0, 0.0)}


def test_the_cli_enforces_declared_pins():
    """A declared pin that the layout has moved must be reported, not ignored.
    Without this wiring the pin-respected rule never fires on a real map."""
    from engine.systems.map import SystemMap
    from engine.systems.validate import validate
    from tools.gen_system_maps import pins_from
    m = load("ona")
    region = m.regions[0]
    key = f"{region.set_name}/{region.body_names[0]}"
    m.overrides = {"pins": {key: [1.0, 2.0, 3.0]}}
    problems = validate(m, pins=pins_from(m))
    assert any(p.rule == "pin-respected" for p in problems)


def test_no_committed_map_declares_a_pin_and_here_is_why():
    """`layout()` honours pins and `validate()` enforces them, but no map
    declares one -- and that is deliberate, not an oversight.

    The design spec names two pin candidates. Xi Entrades 5 turns out not to
    be one at all: E7M3 stages its Akira/Kessok fight around a waypoint,
    "Moon1" at (400, 5000, 0), that no body ever occupies -- there is nothing
    to pin, so the region's radius covers the staged content instead.

    Prendel 3's "Moon 2" is the only actual candidate -- a body a mission
    really does stage against -- but it is the case where a pin COLLIDES with
    20x body scaling. A pin preserves a body's ORIGINAL absolute offset from
    its region anchor; the planet becomes 7200 GU and the moon 1800 GU,
    needing 9000 GU between centres, but the original put the moon 5016 GU
    from the region origin -- so honouring the pin lands the moon inside its
    own planet and `body-overlap` correctly rejects it. So it is the only
    *pinnable* one, not "the only candidate" -- and even it does not hold.

    Prendel's and Xi Entrades's overrides carry the full derivation. If a
    future map ever does declare a pin, this test will fail and should be
    replaced by one asserting that pin holds.
    """
    from tools.gen_system_maps import pins_from
    declared = {name: pins_from(load(name)) for name in available()}
    assert all(p is None for p in declared.values()), \
        f"a map now declares a pin: { {k: v for k, v in declared.items() if v} }"


def test_belaruz_and_vesuvi_carry_the_stars_their_descriptions_claim():
    """The nav-map text says Belaruz's star is alive and Vesuvi's is a remnant.
    Data and prose disagreeing is exactly the drift this branch exists to stop."""
    belaruz = load("belaruz")
    star = [b for b in belaruz.bodies if b.orbits is None][0]
    assert star.appearance.star_class == "white"
    assert star.radius_gu == pytest.approx(8000.0)

    vesuvi = load("vesuvi")
    star = [b for b in vesuvi.bodies if b.orbits is None][0]
    assert star.appearance.star_class == "remnant_hot"

    assert not any(b.appearance.star_class == "brown_dwarf"
                   for name in ("belaruz", "vesuvi")
                   for b in load(name).bodies)


def test_belaruzs_description_matches_where_its_cloud_actually_is():
    """The description says the dense part of Belaruz's cloud has fallen
    inward, closer to the star than any of its three planets. BC anchors the
    profile's clump at Belaruz 1, INSIDE the orbit of every planet."""
    import math
    from engine.systems.profile import clump_radius

    m = load("belaruz")
    star = [b for b in m.bodies if b.orbits is None][0]
    planets = [b for b in m.bodies if b.orbits is not None]
    assert len(planets) == 3, "the description says 'three planets'"

    region = m.region("Belaruz1")
    pocket = clump_radius(region, star.position_gu)
    assert all(math.dist(p.position_gu, star.position_gu) > pocket for p in planets)


def test_planets_orbit_at_the_doubled_scale():
    """Orbits double; radii do not (spec: "Scale"). Live feedback: the system
    read as too small because of SPACING, so the first orbit and the orbit step
    both double while every body keeps its x20 radius -- and doubled again
    2026-09-25, when the planets still read as too close together. The first orbit is a
    MINIMUM measured from the star's surface -- the push logic may move a
    planet further out, never nearer."""
    import math
    from engine.systems import map as system_map
    from tools.systems.layout import LayoutTuning

    t = LayoutTuning()
    assert t.first_orbit_clearance_gu == 120000.0
    assert t.orbit_step_gu == 104000.0
    checked = 0
    for name in system_map.available():
        m = system_map.load(name)
        star = next(b for b in m.bodies if b.orbits is None)
        for b in m.bodies:
            if b.orbits == star.name:
                d = math.dist(b.position_gu, star.position_gu)
                assert d >= star.radius_gu + t.first_orbit_clearance_gu - 1e-6, (
                    f"{name}/{b.name} orbits at {d:.0f} GU, inside the doubled "
                    f"first orbit {star.radius_gu + t.first_orbit_clearance_gu:.0f}")
                checked += 1
    # 87 bodies orbit their star directly across the 32 maps (measured
    # 2026-09-24); the rest are moons. Exact, so a loop that silently stops
    # seeing the maps cannot pass.
    assert checked == 87, f"{checked} planets checked, expected 87"


def test_every_mapped_body_is_its_bc_radius_times_the_scale():
    from engine.systems import map as system_map
    from engine.systems.validate import validate
    from tools.systems.layout import LayoutTuning
    from tools.systems.survey import bc_radii, survey_system, system_names

    scale = LayoutTuning().planet_radius_scale
    assert LayoutTuning().moon_radius_scale == scale, (
        "the ratio rule assumes planets and moons share one scale")
    bad = []
    for name in system_names():
        m = system_map.load(name)
        bad += [p.detail for p in validate(m, bc_radii=bc_radii(survey_system(name)),
                                           radius_scale=scale)
                if p.rule == "radius-ratio"]
    assert bad == []


def test_the_ratio_rule_actually_matches_every_mapped_body():
    """Guards against a vacuous pass: if survey names stopped matching map
    names, the rule would check nothing and still be green. 118 is the
    measured count of (region, body) pairs across the 32 maps (2026-09-24);
    regeneration does not change which bodies exist, only where they are."""
    from engine.systems import map as system_map
    from tools.systems.survey import bc_radii, survey_system, system_names

    matched = 0
    for name in system_names():
        m = system_map.load(name)
        for (region_name, body_name) in bc_radii(survey_system(name)):
            if any(b.name == body_name and b.owner_region == region_name for b in m.bodies):
                matched += 1
    assert matched == 118


def test_no_staged_waypoint_is_within_clearance_of_a_body():
    """No body may have its surface within staged_clearance_gu of any point a
    region stages content at -- the region module's own waypoints (minus the
    bodies' own placement points) and every mission placement the survey
    attributes to that set. Replaces Task 3's ratchet, which saw only the
    region module and missed the E5M2/E6M4 base and Galors inside Prendel 3.
    The generator pushes a violating body group clear (layout._staged_shift),
    so this asserts NO problems anywhere."""
    from engine.systems import map as system_map
    from engine.systems.validate import validate
    from tools.systems.layout import LayoutTuning
    from tools.systems.survey import staged_points, survey_system, system_names

    clearance = LayoutTuning().staged_clearance_gu
    problems = []
    for name in system_names():
        problems += validate(system_map.load(name),
                             staged_points=staged_points(survey_system(name)),
                             staged_clearance_gu=clearance)
    assert problems == [], "\n".join(p.detail for p in problems)


def test_prendel3_staged_points_include_the_missions_base_and_galors():
    """Non-vacuity for the test above: the survey really does attribute E5M2's
    and E6M4's staging to Prendel3 (the case Task 3's ratchet missed)."""
    from tools.systems.survey import survey_system

    region = next(r for r in survey_system("Prendel").regions if r.set_name == "Prendel3")
    have = {(label, name) for label, name, _xyz in region.staged_points}
    assert ("Maelstrom/Episode5/E5M2/Prendel3_P", "Base Location") in have
    assert ("Maelstrom/Episode5/E5M2/Prendel3_P", "Galor Start") in have
    assert ("Maelstrom/Episode6/E6M4/E6M4_Prendel3_P", "Base Location") in have


def test_the_cli_enforces_staged_clearance(monkeypatch, capsys):
    """The generator must pass staged points and the clearance to validate().
    A clearance no layout can meet (1e9 GU, validator side only -- layout()
    keeps its own default) must surface as staged-clearance problems."""
    import dataclasses
    import tools.gen_system_maps as gen
    from tools.systems.layout import LayoutTuning

    monkeypatch.setattr(gen, "LayoutTuning",
                        lambda: dataclasses.replace(LayoutTuning(), staged_clearance_gu=1.0e9))
    rc = gen.main(["--system", "Ona", "--check"])
    out = capsys.readouterr().out
    assert "staged-clearance" in out
    assert rc == 1


# ---- Alioth 6: a planet a mission's content surrounds keeps BC's size and place
# E5M4 stages a stealth route AROUND Alioth 6 -- four nav points in an exact
# ring 1,140 GU off its 360 GU surface. At x20 and moved 9,800 GU the ring sat
# in a fan in front of the planet and the mission could not be completed
# (live-verified 2026-09-24). See tools/systems/layout._encircled.

def _alioth6():
    from engine.systems import map as system_map
    m = system_map.load("alioth")
    region = m.region("Alioth6")
    planet = next(b for b in m.bodies
                  if b.name == "Alioth 6" and b.owner_region == "Alioth6")
    local = tuple(p - a for p, a in zip(planet.position_gu, region.anchor_gu))
    return region, planet, local


def test_exactly_one_region_across_all_maps_is_bc_scale_and_it_is_alioth6():
    from engine.systems import map as system_map
    found = [(name, r.set_name) for name in system_map.available()
             for r in system_map.load(name).regions if r.bc_scale]
    assert found == [("alioth", "Alioth6")]


def test_vesuvi6_is_not_bc_scale():
    """Vesuvi 6's content spans 195 degrees -- under the 270 threshold. It
    keeps x20 pending live evidence."""
    from engine.systems import map as system_map
    assert system_map.load("vesuvi").region("Vesuvi6").bc_scale is False


def test_alioth6_keeps_bcs_centre_and_radius():
    import pytest
    _region, planet, local = _alioth6()
    assert local == pytest.approx((0.0, 1000.0, 0.0), abs=1e-6)
    assert planet.radius_gu == 360.0


def test_e5m4s_four_nav_points_ring_alioth6_1140_gu_off_its_surface():
    import math
    from tools.systems.survey import survey_system

    _region, planet, local = _alioth6()
    sr = next(r for r in survey_system("Alioth").regions if r.set_name == "Alioth6")
    navs = {name: xyz for label, name, xyz in sr.staged_points
            if label == "Maelstrom/Episode5/E5M4/Alioth6_P"
            and name in ("Nav Alpha", "Nav Beta", "Nav Gamma", "Nav Delta")}
    assert sorted(navs) == ["Nav Alpha", "Nav Beta", "Nav Delta", "Nav Gamma"]
    for name, xyz in navs.items():
        assert abs(math.dist(local, xyz) - planet.radius_gu - 1140.0) <= 1.0, name


def test_every_bc_scale_body_sits_at_its_bc_offset():
    from engine.systems import map as system_map
    from engine.systems.validate import validate
    from tools.systems.survey import bc_offsets, survey_system, system_names

    problems = []
    for name in system_names():
        problems += validate(system_map.load(name), bc_offsets=bc_offsets(survey_system(name)))
    assert problems == [], "\n".join(p.detail for p in problems)


def test_bc_offsets_are_bcs_set_local_body_offsets():
    from tools.systems.survey import bc_offsets, survey_system
    offsets = bc_offsets(survey_system("Alioth"))
    assert offsets[("Alioth6", "Alioth 6")] == (0.0, 1000.0, 0.0)
    assert not any(name == "Sun" for _region, name in offsets)


def test_the_cli_enforces_bc_scale_position(monkeypatch, capsys):
    """The generator must pass BC offsets to validate(): an offset the layout
    never used must surface as a bc-scale-position problem."""
    import tools.gen_system_maps as gen

    monkeypatch.setattr(gen, "bc_offsets",
                        lambda surveyed: {("Alioth6", "Alioth 6"): (0.0, 999.0, 0.0)})
    rc = gen.main(["--system", "Alioth", "--check"])
    out = capsys.readouterr().out
    assert "bc-scale-position" in out
    assert rc == 1


def test_every_committed_map_carries_a_profile_with_star_radiation():
    from engine.systems.profile import evaluate
    for name in available():
        m = load(name)
        assert m.profile is not None, name
        star = [b for b in m.bodies if b.orbits is None][0]
        assert evaluate(m.profile, star.radius_gu).radiation == 1.0, name
        assert evaluate(m.profile, 3.0 * star.radius_gu + 1.0).radiation < 1.0, name


def test_no_region_sits_inside_its_stars_radiation():
    """Star radiation reaches 3 star radii; every region must clear it."""
    import math
    for name in available():
        m = load(name)
        star = [b for b in m.bodies if b.orbits is None][0]
        for r in m.regions:
            d = math.dist(r.anchor_gu, star.position_gu) - r.radius_gu
            assert d > 3.0 * star.radius_gu, (name, r.set_name)


def test_multi_systems_have_no_cloud_rows():
    from engine.systems.profile import evaluate
    for name in available():
        if not name.startswith("multi"):
            continue
        m = load(name)
        star = [b for b in m.bodies if b.orbits is None][0]
        for row in m.profile.rows:
            assert (row.nebula, row.dust, row.sensors, row.asteroids) == (0, 0, 0, 0), name
        assert m.profile.color is None


def test_belaruz_profile_peaks_at_its_clump_and_does_not_burn():
    from engine.systems.profile import clump_radius, evaluate
    m = load("belaruz")
    star = [b for b in m.bodies if b.orbits is None][0]
    R = clump_radius(m.region("Belaruz1"), star.position_gu)
    s = evaluate(m.profile, R)
    assert s.nebula == pytest.approx(6.5 / 10.5, abs=1e-3)
    assert s.radiation == 0.0


def test_vesuvi_profile_is_its_override_composed_with_the_star():
    from engine.systems.profile import evaluate
    from tools.systems.profile_builder import override_rows, star_rows, compose_max
    from engine.systems.profile import Profile
    m = load("vesuvi")
    star = [b for b in m.bodies if b.orbits is None][0]
    expected = Profile(rows=compose_max(override_rows(m.overrides["profile"]),
                                        star_rows(star.radius_gu)))
    for r in (0.0, 3000.0, 6000.0, 100000.0, 123500.0, 175000.0, 250000.0, 335000.0, 1e7):
        assert evaluate(m.profile, r) == evaluate(expected, r), r
    s = evaluate(m.profile, 150000.0)
    assert s.radiation >= 0.4 and s.dust >= 0.2 and s.asteroids >= 0.05
    assert evaluate(m.profile, 280000.0).asteroids == pytest.approx(0.5)
    assert evaluate(m.profile, 229620.0).radiation == 0.0   # Vesuvi 5 colonies clear


def test_vesuvi_4_sphere_constant_matches_the_survey():
    from tools.systems.profile_builder import VESUVI_4_SPHERES
    assert [tuple(s) for s in load("vesuvi").region("Vesuvi4").nebula["spheres"]] == \
        [tuple(s) for s in VESUVI_4_SPHERES]
