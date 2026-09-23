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
    problems = validate(m, sdk_set_names=[r.set_name for r in sdk.regions],
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
    the 90 real regions do not."""
    if name == "__none__":
        pytest.skip("no system maps checked in yet")
    from engine.systems.map import to_json
    from tools.gen_system_maps import generate
    committed = load(name)
    fresh, _notes = generate(committed.system)
    assert to_json(fresh) == to_json(committed)


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
    assert shell.geometry["radius_gu"] == pytest.approx(61567.4, rel=1e-3)

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


def test_a_bogus_cloud_kind_surfaces_in_ambiguities():
    """A typo'd or unrecognised `overrides.cloud.kind` must not silently
    degrade to a pockets-only cloud -- gen_system_maps.py must actually pass
    the cloud override through to ambiguities(), not just to layout()."""
    from tools.gen_system_maps import cloud_from
    from tools.systems.layout import ambiguities
    from tools.systems.survey import survey_system
    from engine.systems.map import SystemMap

    bogus = SystemMap(system="Vesuvi", overrides={"cloud": {
        "name": "x", "display_name": "x", "kind": "not_a_real_kind"}})
    surveyed = survey_system("Vesuvi")
    notes = ambiguities(surveyed, cloud=cloud_from(bogus))
    assert any("not_a_real_kind" in n for n in notes)
