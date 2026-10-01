"""Classes are names: ships naming the same `variant_of` form ONE entry; each
member is a variant spawning its own script; one starred default."""
import pytest

from engine import ship_catalog
from engine.foundation import quickbattle
from engine.ship_catalog import catalog
from engine.ship_catalog.catalog import combine_class, resolve_class_default
from engine.ship_catalog.schema import Variant
from tests.helpers.bridge_fixtures import fake_install, install_mod  # noqa: F401
from tests.helpers.catalog_fixtures import FULL, _mod_def, _stock_def


@pytest.fixture(autouse=True)
def _qb_clean():
    quickbattle.reset()
    yield
    quickbattle.reset()


@pytest.fixture
def stock(fake_install, monkeypatch):
    defs = [_stock_def("Nebula", **dict(FULL, title="Nebula", variants=[
        {"name": "USS Berkeley", "registry": "Berkeley"}]))]
    monkeypatch.setattr(catalog, "_stock_definitions", lambda: list(defs))
    ship_catalog.invalidate()
    yield defs
    ship_catalog.invalidate()


def _ship(title, **kw):
    return dict(FULL, title=title, **kw)


def _mods(tmp_path, mod, files):
    install_mod(tmp_path, mod, {"scripts/ships/%s.py" % f: "# s\n" for f in files})


def test_resolve_class_default_order():
    assert resolve_class_default([("Avenger", False), ("Defiant", True)]) == 1
    assert resolve_class_default([("Avenger", False), ("Defiant", False)]) == 0
    # several marked: title match among the marked wins, else the first marked
    assert resolve_class_default([("A", True), ("B", True)]) == 0
    # none marked: exact title match, then whole word, then first
    assert resolve_class_default([("Avenger", False), ("Defiant", False)], "defiant") == 1
    assert resolve_class_default([("USS Bellerophon LC", False), ("USS Intrepid LC", False)], "intrepid") == 1
    assert resolve_class_default([("Avenger", False), ("Lynx", False)], "defiant") == 0


def test_combine_class_era_union_and_conflicts():
    a = ("A", {"era": ("TNG", "DS9"), "role": "tactical", "species": "Federation", "playable": False}, ())
    b = ("B", {"era": ("DS9", "PIC"), "role": "station", "species": "Federation", "playable": True}, ())
    values, missing, errors = combine_class([a, b])
    assert values["era"] == ("TNG", "PIC")
    assert values["playable"] is True and values["species"] == "Federation"
    assert missing == ("role",)
    assert errors == ("role: tactical (A) vs station (B)",)
    c = ("C", {"era": ("all",), "role": "tactical", "species": "Federation", "playable": False}, ())
    assert combine_class([a, c])[0]["era"] == ("all",)


def test_named_class_is_one_entry(stock, tmp_path):
    _mods(tmp_path, "DCMPv2", ["DCMPAvenger", "DCMPDefiant", "DCMPLynx"])
    for f, t in (("DCMPAvenger", "Avenger"), ("DCMPDefiant", "Defiant"), ("DCMPLynx", "Lynx")):
        _mod_def(f, mod="DCMPv2", attr=f, dauntless=_ship(t, variant_of="Defiant"))
    e = ship_catalog.entry("DCMPDefiant")
    assert e.title == "Defiant" and e.source == "mod" and e.complete
    assert e.variants == (Variant("Defiant", playable=True),
                          Variant("Avenger", "DCMPAvenger", playable=True),
                          Variant("Lynx", "DCMPLynx", playable=True))
    assert ship_catalog.entry("DCMPAvenger") is None
    assert len([x for x in ship_catalog.entries() if x.source == "mod"]) == 1


def test_class_default_flag_moves_the_default(stock, tmp_path):
    _mods(tmp_path, "M", ["A", "B"])
    _mod_def("A", dauntless=_ship("Avenger", variant_of="Defiant"))
    _mod_def("B", dauntless=_ship("Bravo", variant_of="Defiant", class_default=1))
    e = [x for x in ship_catalog.entries() if x.title == "Defiant"][0]
    assert e.ship_id == "B" and e.variants[0] == Variant("Bravo", playable=True)


def test_class_spans_two_mods(stock, tmp_path):
    _mods(tmp_path, "ModA", ["A"])
    _mods(tmp_path, "ModB", ["B"])     # install_mod reconfigures with BOTH mods present
    _mod_def("A", mod="ModA", dauntless=_ship("Alpha", variant_of="Shared"))
    _mod_def("B", mod="ModB", dauntless=_ship("Beta", variant_of="shared "))
    (e,) = [x for x in ship_catalog.entries() if x.source == "mod"]
    assert e.title == "Shared" and [o[0] for o in e.origins] == ["ModA", "ModB"]


def test_stock_class_join_appends_and_keeps_stock_default(stock, tmp_path):
    _mods(tmp_path, "LC", ["LCvoyagerZZ"])
    _mod_def("LCvoyagerZZ", mod="LC", dauntless=_ship("USS Voyager LC", variant_of="nebula", class_default=1))
    e = ship_catalog.entry("Nebula")
    assert e.source == "mod"
    assert e.variants == (Variant("USS Berkeley", None, "Berkeley"),
                          Variant("USS Voyager LC", "LCvoyagerZZ", playable=True))
    assert any("class_default ignored" in x for x in e.errors)
    assert ship_catalog.entry("LCvoyagerZZ") is None


def test_role_conflict_makes_class_incomplete(stock, tmp_path):
    _mods(tmp_path, "M", ["A", "B"])
    _mod_def("A", dauntless=_ship("Alpha", variant_of="K"))
    _mod_def("B", dauntless=_ship("Beta", variant_of="K", role="station"))
    e = [x for x in ship_catalog.entries() if x.title == "K"][0]
    assert "role" in e.missing and not e.complete


def test_member_missing_a_key_makes_class_incomplete(stock, tmp_path):
    _mods(tmp_path, "M", ["A"])
    _mod_def("A", dauntless={"variant_of": "K", "title": "Alpha"})
    e = [x for x in ship_catalog.entries() if x.title == "K"][0]
    assert e.missing == ("era", "role", "playable", "species")


def test_own_class_unchanged(stock, tmp_path):
    _mods(tmp_path, "M", ["X"])
    _mod_def("X", dauntless=_ship("Xeno"))
    e = ship_catalog.entry("X")
    assert e.title == "Xeno" and e.variants == () and e.complete
