"""engine.ship_catalog.tables -- the display data mod files never spell."""
from engine.ship_catalog import tables as t


def test_eras_are_the_roadmaps_seven_in_order():
    assert t.ERA_IDS == ("ENT", "TOS", "MOV", "TNG", "DS9", "PIC", "DISC")
    ds9 = t.ERAS[4]
    assert (ds9.name, ds9.tag, ds9.start, ds9.end) == (
        "Quadrant Wars", "DS9 · VOY", 2367, 2399)
    # A boundary year belongs to the later era: each era starts where the
    # previous one ends, except the 2499/2500 gap the roadmap authored.
    assert t.ERAS[0].start == 2140 and t.ERAS[-1].end == 3200
    assert t.DEFAULT_ERAS == ("DS9",)
    assert t.ALL_ERAS == "all"


def test_roles_ids_and_labels():
    assert t.ROLE_IDS == ("tactical", "auxiliary", "station", "automated")
    assert [r.label for r in t.ROLES] == [
        "Tactical", "Auxiliary", "Station", "Automated / Unmanned"]


def test_stock_species_pill_order_and_flagships():
    assert [(s.name, s.flagship) for s in t.STOCK_SPECIES] == [
        ("Federation", "Sovereign"), ("Klingon", "Vorcha"),
        ("Romulan", "Warbird"), ("Cardassian", "Keldon"),
        ("Ferengi", "Marauder"), ("Kessok", "KessokHeavy"),
        ("Civilian", "Freighter"), ("Neutral", "Asteroid")]
    assert all(s.insignia is None for s in t.STOCK_SPECIES)  # resolved at use


def test_mandatory_order():
    assert t.MANDATORY == ("era", "role", "playable", "title", "species")
