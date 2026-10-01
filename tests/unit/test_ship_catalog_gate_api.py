"""The gate's view of the catalog: which ships it must ask about, what it
pre-fills, and the session-only skip."""
import pytest

from engine import ship_catalog
from engine.foundation import quickbattle
from engine.ship_catalog import catalog
from tests.helpers.bridge_fixtures import fake_install, install_mod  # noqa: F401
from tests.helpers.catalog_fixtures import FULL, _mod_def, _stock_def


@pytest.fixture(autouse=True)
def _clean():
    quickbattle.reset()
    ship_catalog.reset_session()
    yield
    quickbattle.reset()
    ship_catalog.reset_session()


@pytest.fixture
def stock(fake_install, monkeypatch):
    defs = [_stock_def("Galaxy", **FULL)]
    monkeypatch.setattr(catalog, "_stock_definitions", lambda: list(defs))
    ship_catalog.invalidate()
    yield defs


def test_incomplete_ships_lists_mod_ships_missing_keys(stock, tmp_path):
    install_mod(tmp_path, "M", {"scripts/ships/A.py": "#", "scripts/ships/B.py": "#"})
    _mod_def("A")
    _mod_def("B", dauntless=dict(FULL, title="Bee"))
    assert [r.ship_id for r in ship_catalog.incomplete_ships()] == ["A"]


def test_conflicting_class_members_are_all_incomplete(stock, tmp_path):
    install_mod(tmp_path, "M", {"scripts/ships/A.py": "#", "scripts/ships/B.py": "#"})
    _mod_def("A", dauntless=dict(FULL, title="A", variant_of="K"))
    _mod_def("B", dauntless=dict(FULL, title="B", variant_of="K", species="Klingon"))
    assert sorted(r.ship_id for r in ship_catalog.incomplete_ships()) == ["A", "B"]


def test_conflict_members_listed_even_when_a_sibling_is_missing_a_key(stock, tmp_path):
    # A and B disagree on role; C is missing its era. Every member must be
    # editable or the player can never resolve the conflict.
    install_mod(tmp_path, "M", {"scripts/ships/A.py": "#", "scripts/ships/B.py": "#",
                                "scripts/ships/C.py": "#"})
    _mod_def("A", dauntless=dict(FULL, title="A", variant_of="K"))
    _mod_def("B", dauntless=dict(FULL, title="B", variant_of="K", role="station"))
    c = dict(FULL, title="C", variant_of="K")
    del c["era"]
    _mod_def("C", dauntless=c)
    assert sorted(r.ship_id for r in ship_catalog.incomplete_ships()) == ["A", "B", "C"]


def test_suggestions(stock, tmp_path):
    install_mod(tmp_path, "M", {"scripts/ships/A.py": "#"})
    _mod_def("A", player=True, details={"SubMenu": "Defiant Class"})
    (r,) = ship_catalog.incomplete_ships()
    assert ship_catalog.suggestions(r) == {
        "title": "Mod A", "species": "Federation", "playable": True,
        "role": "tactical", "variant_of": "Defiant"}


def test_suggestions_omit_what_has_no_source(stock, tmp_path):
    install_mod(tmp_path, "M", {"scripts/ships/A.py": "#"})
    d = _mod_def("A", details={"SubMenu": "Class"})
    d.race = "Borg"
    ship_catalog.invalidate()
    (r,) = ship_catalog.incomplete_ships()
    assert ship_catalog.suggestions(r) == {"title": "Mod A", "role": "tactical"}


def test_skip_hides_from_every_view(stock, tmp_path):
    install_mod(tmp_path, "M", {"scripts/ships/A.py": "#"})
    _mod_def("A")
    ship_catalog.skip_for_session(["a"])
    assert ship_catalog.skipped() == frozenset({"a"})
    assert ship_catalog.incomplete_ships() == []
    assert ship_catalog.entry("A") is None
    assert [r.ship_id for r in ship_catalog.ships("mod")] == []


def test_skipped_ship_gets_no_quickbattle_button(stock, tmp_path):
    install_mod(tmp_path, "M", {"scripts/ships/A.py": "#"})
    _mod_def("A")
    ship_catalog.skip_for_session(["A"])
    added = []

    class Menu:
        def GetButtonW(self, name): return None
        def AddChild(self, b): added.append(b)

    class QB:
        g_pShipsPane = object()
        g_pPlayerPane = None
        ET_SELECT_SHIP_TYPE = 1
        g_pXO = None
        def CreateBridgeMenuButton(self, *a): return a

    import engine.foundation.quickbattle as fq
    orig = fq._resolve_category_chain
    fq._resolve_category_chain = lambda *a: Menu()
    try:
        assert fq._inject_registered_ships(QB()) == 0
    finally:
        fq._resolve_category_chain = orig
    assert added == []
