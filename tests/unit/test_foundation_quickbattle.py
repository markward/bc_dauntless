"""Registration into QuickBattle's five static ship tables."""

import pytest

from engine import foundation
from engine.foundation import quickbattle


class _FakeQB:
    """Stands in for the SDK QuickBattle module.

    Mirrors the real module's five tables and stock id range so the test
    exercises the same shapes without importing the SDK.
    """

    def __init__(self):
        self.g_dShipNameToType = {"Sovereign": 10, "Galaxy": 9}
        self.g_dShipNameToIconNumber = {"Sovereign": 1, "Galaxy": 2}
        self.g_dFriendlyShipTypeToDetails = {
            10: ["Sovereign", "Sovereign", "QBFriendlySovereignDestroyed",
                 "QuickBattleFriendlyAI", "Friendly"]}
        self.g_dEnemyShipTypeToDetails = {
            10: ["Sovereign", "Sovereign", "QBEnemySovereignDestroyed",
                 "QuickBattleEnemyAI", "Enemy"]}
        self.g_dShipTypeToIconNumber = {10: 1, 9: 2}


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    quickbattle.reset()
    yield
    foundation.reset()
    quickbattle.reset()


def _ship(name="LCintrepidZZ"):
    return foundation.FedShipDef(
        name, 42, {"name": "U.S.S. Intrepid", "iconName": "LCIntrepid",
                   "shipFile": name})


def test_allocated_ids_cannot_collide_with_stock():
    # Stock occupies 0..30. Anything we mint must be far clear of it.
    ids = [quickbattle.allocate_ship_type("s%d" % i) for i in range(50)]
    assert min(ids) >= quickbattle.ST_MOD_BASE == 1000
    assert len(set(ids)) == 50


def test_the_same_ship_keeps_its_id():
    a = quickbattle.allocate_ship_type("LCintrepidZZ")
    b = quickbattle.allocate_ship_type("LCintrepidZZ")
    assert a == b


def test_register_populates_all_five_tables():
    qb = _FakeQB()
    d = _ship()
    sid = quickbattle.register(d, "Fed Ships", qb=qb)

    assert qb.g_dShipNameToType["U.S.S. Intrepid"] == sid
    assert "U.S.S. Intrepid" in qb.g_dShipNameToIconNumber
    assert sid in qb.g_dShipTypeToIconNumber
    for table, side in ((qb.g_dFriendlyShipTypeToDetails, "Friendly"),
                        (qb.g_dEnemyShipTypeToDetails, "Enemy")):
        row = table[sid]
        assert row[0] == "LCintrepidZZ"        # ship script
        assert row[1] == "U.S.S. Intrepid"     # label
        assert row[4] == side


def test_register_does_not_disturb_stock_rows():
    qb = _FakeQB()
    before = dict(qb.g_dFriendlyShipTypeToDetails)
    quickbattle.register(_ship(), "Fed Ships", qb=qb)
    assert qb.g_dFriendlyShipTypeToDetails[10] == before[10]
    assert qb.g_dShipNameToType["Sovereign"] == 10


def test_registration_is_recorded_for_the_report():
    qb = _FakeQB()
    quickbattle.register(_ship(), "Fed Ships", qb=qb)
    assert ("U.S.S. Intrepid", 1000) in quickbattle.registered()


def test_shipdef_methods_register():
    qb = _FakeQB()
    d = _ship()
    d.RegisterQBShipMenu("Fed Ships", qb=qb)
    d.RegisterQBPlayerShipMenu("Fed Ships", qb=qb)
    assert d.name in qb.g_dShipNameToType


def test_absent_quickbattle_module_is_not_fatal():
    """QuickBattle may not be importable in every context (a bridge-only
    mission, a tool). Registration must record the intent and move on."""
    d = _ship()
    d.RegisterQBShipMenu("Fed Ships", qb=None)
    assert ("U.S.S. Intrepid", 1000) in quickbattle.registered()
