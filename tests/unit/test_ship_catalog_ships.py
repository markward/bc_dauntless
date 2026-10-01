"""ShipRecord: one per ShipDef in the catalog, before class formation."""
import pytest

from engine import ship_catalog
from engine.foundation import quickbattle
from engine.ship_catalog import catalog
from tests.helpers.bridge_fixtures import fake_install, install_mod  # noqa: F401
from tests.helpers.catalog_fixtures import FULL, _mod_def, _stock_def


@pytest.fixture(autouse=True)
def _qb_clean():
    quickbattle.reset()
    yield
    quickbattle.reset()


@pytest.fixture
def stock(fake_install, monkeypatch):
    defs = [_stock_def("Galaxy", **FULL)]
    monkeypatch.setattr(catalog, "_stock_definitions", lambda: list(defs))
    ship_catalog.invalidate()
    yield defs
    ship_catalog.invalidate()


def test_stock_ship_record(stock):
    (r,) = ship_catalog.ships("stock")
    assert (r.ship_id, r.source, r.mod, r.shipdef_attr) == ("Galaxy", "stock", None, None)
    assert r.values["title"] == "Galaxy" and r.missing == ()
    assert r.variant_of is None and r.class_default is False


def test_mod_ship_record_fields(stock, tmp_path):
    install_mod(tmp_path, "DCMPv2", {"scripts/ships/DCMPAvenger.py": "# s\n"})
    _mod_def("DCMPAvenger", mod="DCMPv2", attr="DCMPAvenger", player=True,
             details={"SubMenu": "Defiant Class"},
             dauntless={"variant_of": "Defiant", "class_default": 1})
    (r,) = ship_catalog.ships("mod")
    assert (r.ship_id, r.source, r.mod, r.shipdef_attr) == ("DCMPAvenger", "mod", "DCMPv2", "DCMPAvenger")
    assert r.variant_of == "Defiant" and r.class_default is True
    assert r.sub_menu == "Defiant Class" and r.player_menu is True
    assert r.raw_name == "Mod DCMPAvenger" and r.raw_race == "Fed"
    assert r.missing == ("era", "role", "playable", "title", "species")


def test_ships_with_no_filter_lists_both(stock, tmp_path):
    install_mod(tmp_path, "M", {"scripts/ships/X.py": "# s\n"})
    _mod_def("X")
    assert {r.ship_id for r in ship_catalog.ships()} == {"Galaxy", "X"}
