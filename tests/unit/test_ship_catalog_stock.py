"""engine/foundation/shipdef_overrides.py -- the stock seed, which must equal
the roadmap appendix (docs/superpowers/specs/2026-10-01-quickbattle-redesign-
roadmap.md). The table below is a deliberate literal copy: drift fails here."""
import ast
from pathlib import Path

import pytest

from engine import foundation
from engine.foundation import shipdef_overrides
from engine.foundation.shipdef import all_definitions
from engine.ship_catalog.schema import parse_dauntless


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    yield
    foundation.reset()


T, A, S, U = "tactical", "auxiliary", "station", "automated"
# ship_id, title, species, role, playable, era, icon, variant names
APPENDIX = [
    ("Akira", "Akira", "Federation", T, True, "DS9", "Akira", ["USS Geronimo", "USS Devore"]),
    ("Ambassador", "Ambassador", "Federation", T, True, "DS9", "Ambassador", ["USS Zhukov", "USS Excalibur"]),
    ("Galaxy", "Galaxy", "Federation", T, True, "DS9", "Galaxy", ["USS Dauntless", "USS San Francisco", "USS Venture"]),
    ("Nebula", "Nebula", "Federation", T, True, "DS9", "Nebula", ["USS Berkeley", "USS Prometheus", "USS Khitomer", "USS Nightingale"]),
    ("Sovereign", "Sovereign", "Federation", T, True, "DS9", "Sovereign", ["USS Sovereign", "USS Enterprise"]),
    ("Shuttle", "Shuttle", "Federation", A, True, "DS9", "FedShuttle", []),
    ("EscapePod", "Escape Pod", "Federation", A, False, "DS9", "LifeBoat", []),
    ("FedStarbase", "Fed Starbase", "Federation", S, False, "DS9", "FedStarbase", []),
    ("FedOutpost", "Fed Outpost", "Federation", S, False, "DS9", "FedOutpost", []),
    ("SpaceFacility", "Space Facility", "Federation", S, False, "DS9", "SpaceFacility", []),
    ("DryDock", "Dry Dock", "Federation", S, False, "DS9", "DryDock", []),
    ("CommArray", "Comm Array", "Federation", U, False, "DS9", "CommArray", []),
    ("Probe", "Probe", "Federation", U, False, "DS9", "Probe", []),
    ("Decoy", "Decoy", "Federation", U, False, "DS9", "ProbeType2", []),
    ("BirdOfPrey", "Bird of Prey", "Klingon", T, True, "DS9", "BirdOfPrey", []),
    ("Vorcha", "Vor'cha", "Klingon", T, True, "DS9", "Vorcha", []),
    ("Warbird", "Warbird", "Romulan", T, True, "DS9", "Warbird", []),
    ("Galor", "Galor", "Cardassian", T, True, "DS9", "Galor", []),
    ("Keldon", "Keldon", "Cardassian", T, True, "DS9", "Keldon", []),
    ("CardHybrid", "Hybrid", "Cardassian", T, True, "DS9", "Hybrid", []),
    ("CardFreighter", "Card Freighter", "Cardassian", A, False, "DS9", "CardFreighter", []),
    ("CardStarbase", "Card Starbase", "Cardassian", S, False, "DS9", "CardStarbase", []),
    ("CardStation", "Card Station", "Cardassian", S, False, "DS9", "CardStation", []),
    ("CardOutpost", "Card Outpost", "Cardassian", S, False, "DS9", "CardOutpost", []),
    ("CommLight", "Comm Light", "Cardassian", U, False, "DS9", "CommLight", []),
    ("Marauder", "Marauder", "Ferengi", T, True, "DS9", "Marauder", []),
    ("KessokLight", "Kessok Light", "Kessok", T, True, "DS9", "KessokLight", []),
    ("KessokHeavy", "Kessok Heavy", "Kessok", T, True, "DS9", "KessokHeavy", []),
    ("KessokMine", "Kessok Mine", "Kessok", U, False, "DS9", "KessokMine", []),
    ("Sunbuster", "Sun Buster", "Kessok", U, False, "DS9", "Sunbuster", []),
    ("Transport", "Transport", "Civilian", A, True, "DS9", "Transport", []),
    ("Freighter", "Freighter", "Civilian", A, False, "DS9", "Freighter", []),
    ("Asteroid", "Asteroid", "Neutral", U, False, "all", "Asteroid", []),
]


def _rows():
    out = []
    for d in shipdef_overrides.stock_definitions():
        p = parse_dauntless(d.dauntless)
        assert p.missing == () and p.errors == (), (d.shipFile, p)
        era = "all" if p.values["era"] == ("all",) else p.values["era"][0]
        assert p.values["era"] in (("all",), ("DS9", "DS9"))
        out.append((d.shipFile, p.values["title"], p.values["species"],
                    p.values["role"], p.values["playable"], era, d.iconName,
                    [v.name for v in p.variants]))
    return out


def test_stock_seed_equals_the_roadmap_appendix():
    assert _rows() == APPENDIX


def test_sixteen_playable_match_bridge_selection():
    from engine.bridge_selection import STOCK_PLAYER_SHIPS
    playable = {r[0] for r in APPENDIX if r[4]}
    assert playable == set(STOCK_PLAYER_SHIPS)


def test_fed_variant_registries_and_the_enterprise_script():
    by_id = {d.shipFile: parse_dauntless(d.dauntless).variants
             for d in shipdef_overrides.stock_definitions()}
    assert [(v.registry, v.script) for v in by_id["Sovereign"]] == [
        ("Sovereign", None), ("Enterprise", "Enterprise")]
    assert [v.registry for v in by_id["Galaxy"]] == ["Dauntless", "SanFrancisco", "Venture"]
    assert [v.registry for v in by_id["Nebula"]] == ["Berkeley", "Prometheus", "Khitomer", "Nightingale"]
    assert [(v.registry, v.script) for v in by_id["Akira"]] == [
        ("Geronimo", None), ("Devore", None)]
    assert [v.registry for v in by_id["Ambassador"]] == ["Zhukov", "Excalibur"]


def test_stock_definitions_are_unlisted():
    shipdef_overrides.stock_definitions()
    assert all_definitions() == []


def test_name_and_race_carry_title_and_species():
    d = {x.shipFile: x for x in shipdef_overrides.stock_definitions()}["CardHybrid"]
    assert (d.name, d.race) == ("Hybrid", "Cardassian")


def test_dict_literals_are_python_15_safe():
    """A mod author copies a section as a template into a file that must
    still load in the original BC's Python 1.5: no True/False, no f-strings
    inside any `<X>.dauntless = {...}` literal. (The module's own plumbing,
    e.g. `_listed=False`, is engine code and is not checked.)"""
    tree = ast.parse(Path(shipdef_overrides.__file__).read_text())
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Attribute) and t.attr == "dauntless"
                        for t in n.targets)]
    assert len(literals) == 33
    for lit in literals:
        for node in ast.walk(lit):
            assert not (isinstance(node, ast.Constant)
                        and isinstance(node.value, bool)), node.lineno
            assert not isinstance(node, ast.JoinedStr), node.lineno
