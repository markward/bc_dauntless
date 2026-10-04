from engine.quickbattle import bios
from engine.ship_catalog import CatalogEntry


def _ce(ship_id, raw_name, title):
    return CatalogEntry(ship_id=ship_id, icon=ship_id, source="stock", origins=(),
                        title=title, species="Federation", era=("DS9", "DS9"),
                        role="tactical", playable=True, variants=(), missing=(),
                        errors=(), raw_name=raw_name, raw_race=None)


def test_bio_strips_rating_lines_and_falls_back(monkeypatch):
    table = {"Galaxy Description": "A big ship.\nShield Rating: 9\nHull Rating: 5\nWeapons: lots",
             "Hybrid Description": "Odd."}
    monkeypatch.setattr(bios, "_strings", lambda: table)
    assert bios.ship_bio(_ce("Galaxy", "Galaxy", "Galaxy")) == "A big ship.\nWeapons: lots"
    assert bios.ship_bio(_ce("CardHybrid", "Card Hybrid", "Hybrid")) == "Odd."
    assert bios.ship_bio(_ce("Mod", "Mod", "Mod")) is None
