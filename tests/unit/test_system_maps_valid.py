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
    """The star half above was pinned; the CLOUD half was not, and that is
    why nothing failed when the committed lobe contradicted the text.

    The description used to say the cloud "can be entered out past the first
    planet; the three inner worlds are clear of it". BC anchors the dense
    pocket at Belaruz 1, INSIDE the orbit of every planet, so both halves of
    that sentence were false against the map committed alongside it.

    Both clauses of the sentence that replaced it are pinned here:

    1. "the dense part has fallen inward, closer to the star than any of the
       three planets" -- the pocket's distance from the star against every
       planet's.
    2. "the thin body of the cloud stretches out ahead of it" -- the lobe
       extends beyond the pocket along the lobe's OWN axis, which is by
       construction the direction from the star to that pocket
       (tools/systems/layout.py:_build_cloud_large_volume).
    """
    import math
    from engine.systems.descriptions import for_system

    m = load("belaruz")
    star = [b for b in m.bodies if b.orbits is None][0]
    planets = [b for b in m.bodies if b.orbits is not None]
    assert len(planets) == 3, "the description says 'three planets'"

    cloud = m.clouds[0]
    pocket = [v for v in cloud.volumes if v.origin_region is not None][0]
    pocket_distance = math.dist(pocket.geometry["center_gu"], star.position_gu)
    distances = [math.dist(b.position_gu, star.position_gu) for b in planets]

    # The dense part has fallen INWARD -- closer to the star than any planet.
    assert pocket_distance < min(distances), (
        f"pocket at {pocket_distance:.0f} GU vs innermost planet at "
        f"{min(distances):.0f} GU")

    # Clause 2: the thin body stretches out AHEAD of the dense pocket. The
    # lobe's axis is the star -> pocket direction, so the pocket's axial
    # projection is its distance from the star (perp = 0 by construction);
    # the lobe must still be going when the pocket's far edge has passed.
    #
    # Deliberately NOT asserted: that all three planets fall inside the lobe.
    # Measured against the committed map, only Belaruz 4 does. The lobe's
    # spine runs from the star toward the pocket (~+Y) and BC's orbital
    # angles scatter the planets around the star, so Belaruz 2 projects to
    # t = -47,211 (behind near_gu) and Belaruz 3 to t = 7,908 (short of it)
    # under the capsule model validate.py:_pocket_inside_large uses. That
    # discrepancy is a KNOWN OPEN DESIGN QUESTION about the lobe's shape --
    # whether it should envelop the whole system -- not an error in the
    # text, which no longer claims it does. Pinning containment here would
    # pin a fact the geometry does not support.
    lobe = [v for v in cloud.volumes if v.origin_region is None][0]
    axis = lobe.geometry["axis"]
    axis_len = math.sqrt(sum(a * a for a in axis))
    unit = [a / axis_len for a in axis]
    rel = [p - o for p, o in zip(pocket.geometry["center_gu"], star.position_gu)]
    pocket_t = sum(r * u for r, u in zip(rel, unit))
    assert lobe.geometry["far_gu"] > pocket_t + pocket.geometry["radius_gu"], (
        f"lobe ends at {lobe.geometry['far_gu']:.0f} GU along its axis but the "
        f"pocket's far edge is at {pocket_t + pocket.geometry['radius_gu']:.0f}")

    detail = for_system("belaruz")["detail"]
    assert "past the first planet" not in detail
    assert "clear of it" not in detail
    assert "whole system sits in thin material" not in detail
    assert "closer to the star than any of the three planets" in detail
    assert "stretches out ahead of it" in detail


def test_the_two_cloud_systems_carry_their_clouds():
    vesuvi = load("vesuvi")
    assert len(vesuvi.clouds) == 1
    cloud = vesuvi.clouds[0]
    assert cloud.kind == "debris_shell"
    assert sorted(cloud.regions) == ["Vesuvi4"]
    pocket = [v for v in cloud.volumes if v.origin_region == "Vesuvi4"][0]
    assert pocket.profile == "debris"
    assert pocket.params["damage_hull_per_s"] == pytest.approx(150.0)
    shell = [v for v in cloud.volumes if v.origin_region is None][0]
    assert shell.shape == "sphere"
    # The shell radius is DERIVED, not authored: the greatest
    # |anchor| + radius_gu across the cloud's member regions, so the shell
    # reaches exactly as far as the wreckage does
    # (tools/systems/layout.py:_build_cloud_large_volume). Assert that
    # relationship, computed from this map. The literal that stood here,
    # 61567.4 at rel=1e-3, matched neither the derived value
    # (61566.8173...) nor the design note's 61567.0 -- a magic number
    # loose enough to pass while agreeing with nothing.
    import math
    assert shell.geometry["radius_gu"] == pytest.approx(
        max(math.dist(vesuvi.region(n).anchor_gu, (0.0, 0.0, 0.0))
            + vesuvi.region(n).radius_gu for n in cloud.regions))

    belaruz = load("belaruz")
    cloud = belaruz.clouds[0]
    assert cloud.kind == "nebula_field"
    pocket = [v for v in cloud.volumes if v.origin_region == "Belaruz1"][0]
    assert pocket.profile == "nebula"
    assert pocket.params["damage_hull_per_s"] == 0.0
    assert [v for v in cloud.volumes if v.origin_region is None][0].shape == "lobe"


def test_no_other_system_grew_a_cloud():
    for name in available():
        if name in ("vesuvi", "belaruz"):
            continue
        assert load(name).clouds == [], name


def test_ambiguities_itself_reports_a_bogus_cloud_kind():
    """Documents ambiguities()'s own behaviour (a Task 4 deliverable, not new
    here): given a cloud override with an unrecognised `kind`, it reports it.

    This is NOT a substitute for
    test_a_bogus_cloud_kind_reaches_the_generators_ambiguities_output below --
    it calls ambiguities() directly, so it cannot detect a regression in
    gen_system_maps.py's call site (generate()'s `ambiguities(surveyed,
    cloud=cloud)`). Reverting that kwarg back to `ambiguities(surveyed)`
    leaves this test green. Kept only as a small, fast pin on
    ambiguities()'s own contract."""
    from tools.gen_system_maps import cloud_from
    from tools.systems.layout import ambiguities
    from tools.systems.survey import survey_system
    from engine.systems.map import SystemMap

    bogus = SystemMap(system="Vesuvi", overrides={"cloud": {
        "name": "x", "display_name": "x", "kind": "not_a_real_kind"}})
    surveyed = survey_system("Vesuvi")
    notes = ambiguities(surveyed, cloud=cloud_from(bogus))
    assert any("not_a_real_kind" in n for n in notes)


def test_a_bogus_cloud_kind_reaches_the_generators_ambiguities_output(monkeypatch, capsys):
    """The requirement: a bogus `kind` in a map's `overrides.cloud` must
    surface in the GENERATOR's `--list-ambiguities` output. Drives the real
    `main() -> generate() -> ambiguities(surveyed, cloud=cloud)` path, not a
    direct ambiguities() call -- so reverting generate()'s cloud kwarg
    (tools/gen_system_maps.py) makes this test fail, unlike the test above.

    Patches gen_system_maps.load (not the checked-in vesuvi.json) so the
    "existing map" generate() reads back carries a bogus cloud kind; --check
    keeps this from writing anything."""
    import tools.gen_system_maps as gen_system_maps
    real_load = gen_system_maps.load

    def bogus_load(system):
        m = real_load(system)
        if system.lower() == "vesuvi":
            m.overrides = dict(m.overrides)
            m.overrides["cloud"] = dict(m.overrides["cloud"])
            m.overrides["cloud"]["kind"] = "not_a_real_kind"
        return m

    monkeypatch.setattr(gen_system_maps, "load", bogus_load)
    rc = gen_system_maps.main(["--system", "Vesuvi", "--list-ambiguities", "--check"])
    out = capsys.readouterr().out
    assert "not_a_real_kind" in out
    assert rc == 0


def test_planets_orbit_at_the_doubled_scale():
    """Orbits double; radii do not (spec: "Scale"). Live feedback: the system
    read as too small because of SPACING, so the first orbit and the orbit step
    both double while every body keeps its x20 radius. The first orbit is a
    MINIMUM measured from the star's surface -- the push logic may move a
    planet further out, never nearer."""
    import math
    from engine.systems import map as system_map
    from tools.systems.layout import LayoutTuning

    t = LayoutTuning()
    assert t.first_orbit_clearance_gu == 60000.0
    assert t.orbit_step_gu == 52000.0
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
