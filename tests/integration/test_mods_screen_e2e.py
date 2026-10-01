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
