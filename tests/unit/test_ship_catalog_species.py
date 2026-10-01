"""Species list and insignia resolution (spec §4.4): committed SVG, then the
asset overlay (a mod-introduced species), then None (flagship icon)."""
from pathlib import Path

import pytest

from engine import paths, ship_catalog
from engine.foundation import quickbattle
from engine.foundation.shipdef import ShipDefinition, plugin_origin
from engine.ship_catalog import catalog
from tests.helpers.bridge_fixtures import fake_install, install_mod  # noqa: F401


@pytest.fixture(autouse=True)
def _qb_clean():
    quickbattle.reset()
    yield
    quickbattle.reset()


def test_the_five_committed_insignias_exist():
    root = paths.project_asset_root() / "insignias"
    for s in ("Federation", "Klingon", "Romulan", "Cardassian", "Ferengi"):
        assert ship_catalog.insignia_path(s) == root / ("%s.svg" % s.lower())
        assert (root / ("%s.svg" % s.lower())).stat().st_size > 0


def test_no_insignia_for_kessok_civilian_neutral(fake_install):
    for s in ("Kessok", "Civilian", "Neutral", "", None):
        assert ship_catalog.insignia_path(s) is None


def test_overlay_supplies_a_mod_species_emblem(fake_install):
    _sdk, game_root = fake_install       # fake_install's game_asset -> game_root/rel
    emblem = game_root / "data" / "Icons" / "Species" / "Borg.png"
    emblem.parent.mkdir(parents=True)
    emblem.write_bytes(b"png")
    assert ship_catalog.insignia_path("Borg") == emblem


def test_committed_svg_beats_the_overlay(fake_install):
    _sdk, game_root = fake_install
    p = game_root / "data" / "Icons" / "Species" / "Federation.png"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"png")
    assert ship_catalog.insignia_path("Federation").suffix == ".svg"


def test_species_lists_stock_then_mod_introduced_alphabetically(
        fake_install, monkeypatch, tmp_path):
    monkeypatch.setattr(catalog, "_stock_definitions", lambda: [])
    install_mod(tmp_path, "M", {"scripts/ships/Cube.py": "# s\n",
                                "scripts/ships/Bug.py": "# s\n"})
    quickbattle.reset()
    for ship, sp in (("Cube", "Borg"), ("Bug", "Dominion")):
        with plugin_origin("M", "custom/ships/x.py"):
            d = ShipDefinition("Fed", ship, 103, {"shipFile": ship})
        d.dauntless = {"species": sp}
        d.RegisterQBShipMenu("Fed Ships", qb=None)
    ship_catalog.invalidate()
    got = ship_catalog.species()
    assert [s.name for s in got] == [
        "Federation", "Klingon", "Romulan", "Cardassian", "Ferengi",
        "Kessok", "Civilian", "Neutral", "Borg", "Dominion"]
    assert got[0].insignia is not None and got[0].flagship == "Sovereign"
    assert got[-1].flagship is None and got[-1].insignia is None
    quickbattle.reset()
