"""engine.ship_catalog -- membership, per-key merge over stock, provenance,
memoisation. Stock is substituted through catalog._stock_definitions so each
test controls it; the fake install supplies the ships/*.py that exist."""
import pytest

from engine import foundation, mods, ship_catalog
from engine.foundation import quickbattle
from engine.foundation.shipdef import ShipDefinition, plugin_origin
from engine.ship_catalog import catalog
from engine.ship_catalog.schema import Variant
from tests.helpers.bridge_fixtures import fake_install, install_mod  # noqa: F401

FULL = {"title": "Galaxy", "species": "Federation", "era": "DS9",
        "role": "tactical", "playable": 1}
ALL_MISSING = ("era", "role", "playable", "title", "species")


@pytest.fixture(autouse=True)
def _qb_clean():
    """RegisterQBShipMenu(qb=None) still records into quickbattle._registered,
    and conftest does not reset it."""
    quickbattle.reset()
    yield
    quickbattle.reset()


def _stock_def(ship_id, **dauntless):
    d = ShipDefinition("Federation", ship_id, None,
                       {"shipFile": ship_id, "name": ship_id}, _listed=False)
    d.dauntless = dict(dauntless)
    return d


def _mod_def(ship_file, mod="M", attr=None, dauntless=None, menu=True):
    with plugin_origin(mod, "custom/ships/%s.py" % ship_file.lower()):
        d = ShipDefinition("Fed", ship_file, 103,
                           {"shipFile": ship_file, "name": "Mod " + ship_file})
    if dauntless is not None:
        d.dauntless = dauntless
    if menu:
        d.RegisterQBShipMenu("Fed Ships", qb=None)
    if attr:
        setattr(foundation.ShipDef, attr, d)
    ship_catalog.invalidate()
    return d


@pytest.fixture
def stock(fake_install, monkeypatch):
    """Stock = Galaxy (complete) + Sovereign with an Enterprise script variant."""
    defs = [_stock_def("Galaxy", **FULL),
            _stock_def("Sovereign", **dict(FULL, title="Sovereign", variants=[
                {"name": "USS Sovereign", "registry": "Sovereign"},
                {"name": "USS Enterprise", "script": "Enterprise",
                 "registry": "Enterprise"}]))]
    monkeypatch.setattr(catalog, "_stock_definitions", lambda: list(defs))
    quickbattle.reset()
    ship_catalog.invalidate()
    yield defs
    quickbattle.reset()
    ship_catalog.invalidate()


def test_stock_entries_are_complete_and_stock_sourced(stock):
    e = ship_catalog.entry("galaxy")
    assert e.ship_id == "Galaxy" and e.source == "stock" and e.origins == ()
    assert e.complete and e.era == ("DS9", "DS9") and e.playable is True
    assert [x.ship_id for x in ship_catalog.entries()] == ["Galaxy", "Sovereign"]


def test_missing_variant_script_is_dropped_with_an_error(stock):
    e = ship_catalog.entry("Sovereign")       # fake install has no Enterprise.py
    assert e.variants == (Variant("USS Sovereign", None, "Sovereign"),)
    assert any("ships/Enterprise.py not found" in x for x in e.errors)
    assert e.complete


def test_variant_script_that_exists_is_kept(stock, tmp_path):
    install_mod(tmp_path, "EntMod", {"scripts/ships/Enterprise.py": "# ship\n"})
    ship_catalog.invalidate()
    names = [v.name for v in ship_catalog.entry("Sovereign").variants]
    assert names == ["USS Sovereign", "USS Enterprise"]


def test_mod_def_over_a_stock_stem_wins_per_key(stock):
    _mod_def("Galaxy", mod="GalMod", attr="GalMod", dauntless={"title": "Galaxy Refit"})
    e = ship_catalog.entry("Galaxy")
    assert e.title == "Galaxy Refit" and e.species == "Federation" and e.complete
    assert e.source == "mod" and e.origins == (("GalMod", "GalMod"),)
    assert e.raw_name == "Mod Galaxy"


def test_mod_shipfile_case_drift_merges_onto_stock(stock):
    _mod_def("galaxy", mod="GalMod", dauntless={"role": "station"})
    e = ship_catalog.entry("GALAXY")
    assert e.ship_id == "Galaxy" and e.role == "station"
    assert len(ship_catalog.entries()) == 2


def test_mod_def_with_no_dauntless_inherits_stock_and_is_complete(stock):
    _mod_def("Galaxy", mod="GalMod")
    e = ship_catalog.entry("Galaxy")
    assert e.complete and e.title == "Galaxy" and e.source == "mod"


def test_in_place_replacement_without_a_shipdef_keeps_stock(stock, tmp_path):
    install_mod(tmp_path, "CG", {"scripts/ships/Galaxy.py": "# replaced\n"})
    ship_catalog.invalidate()
    e = ship_catalog.entry("Galaxy")
    assert e.source == "stock" and e.complete


def test_new_mod_ship_without_metadata_is_incomplete(stock, tmp_path):
    install_mod(tmp_path, "LC", {"scripts/ships/LCIntrepid.py": "# ship\n"})
    _mod_def("LCintrepid", mod="LC", attr="LCintrepidZZ")
    e = ship_catalog.entry("LCIntrepid")
    assert e.ship_id == "LCintrepid" and e.source == "mod"
    assert e.missing == ALL_MISSING and not e.complete
    assert e.origins == (("LC", "LCintrepidZZ"),)
    assert (e.raw_name, e.raw_race) == ("Mod LCintrepid", "Fed")
    assert ship_catalog.incomplete() == [e]


def test_partial_mod_metadata_lists_exactly_the_rest(stock, tmp_path):
    install_mod(tmp_path, "LC", {"scripts/ships/LCIntrepid.py": "# ship\n"})
    _mod_def("LCintrepid", mod="LC", dauntless={"era": "DS9", "role": "tactical"})
    assert ship_catalog.entry("LCintrepid").missing == ("playable", "title", "species")


def test_non_dict_dauntless_is_an_error_not_a_crash(stock, tmp_path):
    install_mod(tmp_path, "LC", {"scripts/ships/LCIntrepid.py": "# ship\n"})
    _mod_def("LCintrepid", mod="LC", dauntless="Federation")
    e = ship_catalog.entry("LCintrepid")
    assert e.missing == ALL_MISSING
    assert any("must be a dict" in x for x in e.errors)


def test_definition_not_on_a_qb_menu_is_not_an_entry(stock, tmp_path):
    install_mod(tmp_path, "LC", {"scripts/ships/LCIntrepid.py": "# ship\n"})
    _mod_def("LCintrepid", mod="LC", menu=False)
    assert ship_catalog.entry("LCintrepid") is None


def test_unresolved_script_is_excluded_and_recorded(stock):
    _mod_def("Ghost", mod="GhostMod")
    assert ship_catalog.entry("Ghost") is None
    assert catalog._built().unresolved == [("Ghost", "GhostMod")]


def test_two_mods_on_one_stem_merge_in_load_order_and_are_recorded(stock, tmp_path):
    install_mod(tmp_path, "A", {"scripts/ships/Defiant.py": "# ship\n"})
    _mod_def("Defiant", mod="ModA", dauntless=dict(FULL, title="A title"))
    _mod_def("Defiant", mod="ModB", dauntless={"title": "B title"})
    e = ship_catalog.entry("Defiant")
    assert e.title == "B title" and e.complete
    assert [o[0] for o in e.origins] == ["ModA", "ModB"]
    assert catalog._built().shared == [("Defiant", ["ModA", "ModB"])]


def test_entries_are_memoised_until_invalidate(stock):
    first = ship_catalog.entries()
    assert ship_catalog.entries()[0] is first[0]
    ship_catalog.invalidate()
    assert ship_catalog.entries()[0] is not first[0]


def test_a_new_mod_index_rebuilds(stock):
    first = ship_catalog.entries()
    mods.configure(mods.ModIndex(files={}, mods=[]))
    assert ship_catalog.entries()[0] is not first[0]


def test_foundation_reset_invalidates(stock):
    first = ship_catalog.entries()
    foundation.reset()
    assert ship_catalog.entries()[0] is not first[0]


def test_a_broken_stock_file_degrades_to_mod_entries_only(fake_install, monkeypatch, tmp_path):
    def boom():
        raise SyntaxError("bad stock")
    monkeypatch.setattr(catalog, "_stock_definitions", boom)
    install_mod(tmp_path, "LC", {"scripts/ships/LCIntrepid.py": "# ship\n"})
    _mod_def("LCintrepid", mod="LC")
    ship_catalog.invalidate()
    assert [e.ship_id for e in ship_catalog.entries()] == ["LCintrepid"]
    assert "SyntaxError: bad stock" in catalog._built().stock_error


@pytest.mark.parametrize("era, selected, want", [
    (("DS9", "DS9"), ("DS9",), True),
    (("MOV", "DS9"), ("TNG",), True),         # inside the span
    (("MOV", "TNG"), ("DS9", "PIC"), False),
    (("all",), ("ENT",), True),
    (None, ("DS9",), False),                  # incomplete era never matches
])
def test_in_eras(stock, era, selected, want):
    import dataclasses
    e = dataclasses.replace(ship_catalog.entry("Galaxy"), era=era)
    assert e.in_eras(selected) is want
