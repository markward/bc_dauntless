"""ship_catalog.describe() -- the boot line (spec §5)."""
import pytest

from engine import ship_catalog
from engine.ship_catalog import catalog
from engine.ship_catalog.catalog import CatalogEntry, _Built


def _e(ship_id, source="stock", mod=None, complete=True):
    return CatalogEntry(
        ship_id=ship_id, icon=ship_id, source=source,
        origins=((mod, ship_id),) if mod else (), title=ship_id,
        species="Federation", era=("DS9", "DS9"), role="tactical",
        playable=True, variants=(),
        missing=() if complete else ("era",), errors=(),
        raw_name=ship_id, raw_race="Fed")


@pytest.fixture
def built(monkeypatch):
    holder = {}
    monkeypatch.setattr(catalog, "_built", lambda: holder["b"])
    def set_(entries, unresolved=(), shared=(), stock_error=None):
        holder["b"] = _Built([], {}, list(entries), list(unresolved), list(shared), stock_error)
    return set_


def test_stock_only_and_healthy_is_silent(built):
    built([_e("Galaxy"), _e("Akira")])
    assert ship_catalog.describe() == ""


def test_counts_and_incomplete_grouped_by_mod(built):
    built([_e("Galaxy"), _e("Defiant", "mod", "DCMPv2", False),
           _e("Avenger", "mod", "DCMPv2", False),
           _e("LCintrepid", "mod", "LC Intrepid Pack", False),
           _e("Fine", "mod", "Other")])
    assert ship_catalog.describe() == (
        "ship catalog: 1 stock, 4 mod; 3 incomplete "
        "(DCMPv2: 2, LC Intrepid Pack: 1)")


def test_complete_mods_omit_the_incomplete_clause(built):
    built([_e("Galaxy"), _e("Fine", "mod", "Other")])
    assert ship_catalog.describe() == "ship catalog: 1 stock, 1 mod"


def test_shared_unresolved_and_stock_error_lines(built):
    built([_e("Defiant", "mod", "ModB")],
          unresolved=[("XyzShip", "SomeMod")],
          shared=[("Defiant", ["ModA", "ModB"])],
          stock_error="SyntaxError: bad")
    assert ship_catalog.describe().splitlines() == [
        "ship catalog: 0 stock, 1 mod",
        "  shared stem 'Defiant': ModB over ModA",
        "  unresolved: XyzShip (SomeMod) -- ships/XyzShip.py not found",
        "  WARNING stock metadata failed to load: SyntaxError: bad",
    ]


def test_describe_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(catalog, "_built", boom)
    assert ship_catalog.describe() == "ship catalog: WARNING could not build: RuntimeError: x"
