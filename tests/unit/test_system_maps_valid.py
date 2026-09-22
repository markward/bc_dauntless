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


def test_regenerating_ona_is_idempotent():
    """Running the generator again must reproduce the committed file byte for
    byte, so a regeneration diff shows only real changes."""
    from engine.systems.map import to_json
    from tools.gen_system_maps import generate
    fresh, _notes = generate("Ona")
    assert to_json(fresh) == to_json(load("ona"))


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

    A pin preserves a body's ORIGINAL absolute offset from its region anchor,
    while every body is scaled to 20x. The two collide for any body the
    original placed within ~20x of its planet. The only candidate, Prendel 3's
    "Moon 2", is exactly that case: the planet becomes 7200 GU and the moon
    1800 GU, needing 9000 GU between centres, but the original put the moon
    5016 GU from the region origin -- so honouring the pin lands the moon
    inside its own planet and `body-overlap` correctly rejects it.

    Prendel's overrides carry the full derivation. If a future map ever does
    declare a pin, this test will fail and should be replaced by one asserting
    that pin holds.
    """
    from tools.gen_system_maps import pins_from
    declared = {name: pins_from(load(name)) for name in available()}
    assert all(p is None for p in declared.values()), \
        f"a map now declares a pin: { {k: v for k, v in declared.items() if v} }"
