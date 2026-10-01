"""A temp mod with two metadata-less ships sharing a SubMenu: load plugins,
gate panel opens with suggestions, fill era, Continue writes + re-runs, the
catalog is complete with one class and the right default. Skip leaves them
out of the QuickBattle injection."""
import pytest

from engine import foundation, mods, ship_catalog
from engine.foundation import quickbattle
from engine.ui import mods_screen

SHIP = ("import Foundation\n"
        "Foundation.ShipDef.{a} = Foundation.FedShipDef('{a}', 103, "
        "{{'name': '{n}', 'shipFile': '{a}', 'SubMenu': 'Defiant Class'}})\n"
        "Foundation.ShipDef.{a}.RegisterQBShipMenu('Fed Ships')\n"
        "Foundation.ShipDef.{a}.RegisterQBPlayerShipMenu('Fed Ships')\n")


@pytest.fixture
def mod(tmp_path, monkeypatch):
    foundation.reset(); quickbattle.reset(); ship_catalog.reset_session()
    root = tmp_path / "mods" / "DCMPv2" / "scripts"
    (root / "Custom" / "Ships").mkdir(parents=True)
    (root / "ships").mkdir(parents=True)
    for a, n in (("DCMPDefiant", "Defiant"), ("DCMPAvenger", "Avenger")):
        (root / "Custom" / "Ships" / ("%s.py" % a)).write_text(SHIP.format(a=a, n=n))
        (root / "ships" / ("%s.py" % a)).write_text("#")
    mods.configure(mods.build_index(tmp_path / "mods"))
    monkeypatch.setattr("engine.foundation.quickbattle._resolve_qb", lambda: None)
    foundation.load_plugins()
    ship_catalog.invalidate()
    yield root
    foundation.reset(); quickbattle.reset(); ship_catalog.reset_session(); mods.configure(None)


def test_gate_continue_makes_one_complete_class(mod):
    assert mods_screen.decide_mode([]) == "gate"

    def fill_and_continue(panel):
        for f in ("DCMPDefiant", "DCMPAvenger"):
            panel.dispatch_event("set:%s:era:all" % f)
        panel.dispatch_event("continue")

    assert mods_screen.run_mods_screen(fill_and_continue, argv=[]) == "boot"
    assert (mod / "Custom" / "Ships" / "zz_Dauntless_DCMPAvenger.py").is_file()
    assert ship_catalog.incomplete_ships() == []
    e = ship_catalog.entry("DCMPDefiant")
    assert e.title == "Defiant" and e.complete
    assert [v.name for v in e.variants] == ["Defiant", "Avenger"]


def test_skip_hides_both_ships(mod):
    assert mods_screen.run_mods_screen(lambda p: p.dispatch_event("skip"), argv=[]) == "boot"
    assert ship_catalog.skipped() == frozenset({"dcmpdefiant", "dcmpavenger"})
    assert ship_catalog.entry("DCMPDefiant") is None


AUTHORED = ("import Foundation\n"
            "Foundation.ShipDef.{a} = Foundation.FedShipDef('{a}', 103, "
            "{{'name': '{n}', 'shipFile': '{a}'}})\n"
            "Foundation.ShipDef.{a}.dauntless = {d}\n"
            "Foundation.ShipDef.{a}.RegisterQBShipMenu('Fed Ships')\n")


@pytest.fixture
def authored(tmp_path, monkeypatch):
    """Build a mod whose ships carry author dauntless dicts (no era, so the
    gate asks); yields a function taking {attr: (name, dict-source)}."""
    foundation.reset(); quickbattle.reset(); ship_catalog.reset_session()
    root = tmp_path / "mods" / "M" / "scripts"
    (root / "Custom" / "Ships").mkdir(parents=True)
    (root / "ships").mkdir(parents=True)
    monkeypatch.setattr("engine.foundation.quickbattle._resolve_qb", lambda: None)

    def build(ships):
        for a, (n, d) in ships.items():
            (root / "Custom" / "Ships" / ("%s.py" % a)).write_text(AUTHORED.format(a=a, n=n, d=d))
            (root / "ships" / ("%s.py" % a)).write_text("#")
        mods.configure(mods.build_index(tmp_path / "mods"))
        foundation.load_plugins()
        ship_catalog.invalidate()
        return root
    yield build
    foundation.reset(); quickbattle.reset(); ship_catalog.reset_session(); mods.configure(None)


_BASE = "'species':'Federation','role':'tactical','playable':1"


def test_starring_another_ship_unmarks_the_authors_class_default(authored):
    authored({
        "ShA": ("Alpha", "{'title':'Alpha',%s,'variant_of':'Defiant','class_default':1}" % _BASE),
        "ShB": ("Bravo", "{'title':'Bravo',%s,'variant_of':'Defiant'}" % _BASE),
    })

    def star_b(panel):
        for f in ("ShA", "ShB"):
            panel.dispatch_event("set:%s:era:all" % f)
        panel.dispatch_event("star:ShB")
        panel.dispatch_event("continue")

    assert mods_screen.run_mods_screen(star_b, argv=[]) == "boot"
    e = next(x for x in ship_catalog.entries() if x.title == "Defiant")
    assert e.ship_id == "ShB"
    assert not any("several" in err for err in e.errors), e.errors


def test_clearing_variant_of_returns_the_ship_to_its_own_class(authored):
    authored({"ShA": ("Alpha", "{'title':'Alpha',%s,'variant_of':'Defiant'}" % _BASE)})

    def clear(panel):
        panel.dispatch_event("set:ShA:era:all")
        panel.dispatch_event("set:ShA:variant_of:")
        panel.dispatch_event("continue")

    assert mods_screen.run_mods_screen(clear, argv=[]) == "boot"
    assert ship_catalog.incomplete_ships() == []
    e = ship_catalog.entry("ShA")
    assert e is not None and e.title == "Alpha" and e.complete
