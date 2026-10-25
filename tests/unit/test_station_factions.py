from engine.systems import home_stations as hs
from engine.systems import station_factions as sf


def _row(set_name, name):
    return next(s for s in hs.table()
                if s.set_name == set_name and s.name == name)


def test_every_standing_station_names_its_faction_by_system():
    hs.reset()
    assert sf.factions_by_system() == {
        "tauceti": ("Federation",),
        "savoy": ("Federation",),
        "albirea": ("Federation",),
        "chambana": ("Cardassian",),
        "cebalrai": ("Cardassian",),
        "ascella": ("Cardassian",),
        "alioth": ("Cardassian",),
        "prendel": ("Cardassian",),
    }


def test_a_station_with_no_catalog_faction_shows_nothing():
    # Biranu's station is not in the ship catalog (BC lists it Neutral).
    hs.reset()
    assert "biranu" not in sf.factions_by_system()


def test_a_destroyed_stations_faction_leaves_its_system():
    hs.reset()
    try:
        hs._destroyed.add(("Prendel3", "Outpost"))
        assert "prendel" not in sf.factions_by_system()
    finally:
        hs.reset()


def test_a_faction_stays_while_any_of_its_stations_stands():
    # Tau Ceti holds Starbase 12 and four dry-dock stations.
    hs.reset()
    try:
        hs._destroyed.add(("Starbase12", "Starbase 12"))
        assert sf.factions_by_system()["tauceti"] == ("Federation",)
        for s in hs.stations_for_set("DryDock"):
            hs._destroyed.add((s.set_name, s.name))
        assert "tauceti" not in sf.factions_by_system()
    finally:
        hs.reset()


def test_federation_comes_first_then_alphabetical(monkeypatch):
    monkeypatch.setattr(sf, "_faction_of_script", lambda script: {
        "FedStarbase": "Federation", "DryDock": "Romulan",
        "SpaceFacility": "Cardassian"}.get(script))
    hs.reset()
    assert sf.factions_by_system()["tauceti"] == (
        "Federation", "Cardassian", "Romulan")


def test_an_unknown_script_is_skipped_not_fatal(monkeypatch):
    def boom(script):
        raise RuntimeError("catalog unavailable")
    monkeypatch.setattr(sf, "_faction_of_script", boom)
    hs.reset()
    assert sf.factions_by_system() == {}
