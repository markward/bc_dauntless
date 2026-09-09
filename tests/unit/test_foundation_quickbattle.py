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
        # "QuickBattleAI" verbatim from the real table
        # (sdk/.../QuickBattle/QuickBattle.py:580-585) -- every stock ENEMY
        # row names that module. This double previously said
        # "QuickBattleEnemyAI", a module that does not exist, which is how
        # the same invented name reached the shipping code unchallenged.
        self.g_dEnemyShipTypeToDetails = {
            10: ["Sovereign", "Sovereign", "QBEnemySovereignDestroyed",
                 "QuickBattleAI", "Enemy"]}
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


def test_register_detects_a_name_collision_with_stock():
    """A mod naming its ship "Sovereign" must not retarget the stock
    mapping -- that is exactly the "corrupting a stock row" failure the
    stock-immutability rule exists to prevent, and the id-keyed tables'
    ST_MOD_BASE floor cannot catch it because these two tables are keyed
    by name, not id."""
    qb = _FakeQB()
    before_friendly = dict(qb.g_dFriendlyShipTypeToDetails)
    before_enemy = dict(qb.g_dEnemyShipTypeToDetails)
    before_icon = dict(qb.g_dShipTypeToIconNumber)
    before_name_icon = dict(qb.g_dShipNameToIconNumber)

    impostor = foundation.FedShipDef(
        "ImpostorSovereign", 42,
        {"name": "Sovereign", "iconName": "X", "shipFile": "ImpostorSovereign"})
    sid = quickbattle.register(impostor, "Fed Ships", qb=qb)

    # The stock id comes back unchanged -- nothing was minted for the
    # impostor -- and every table is untouched, not just the name-keyed one.
    assert sid == 10
    assert qb.g_dShipNameToType["Sovereign"] == 10
    assert qb.g_dFriendlyShipTypeToDetails == before_friendly
    assert qb.g_dEnemyShipTypeToDetails == before_enemy
    assert qb.g_dShipTypeToIconNumber == before_icon
    assert qb.g_dShipNameToIconNumber == before_name_icon
    assert ("Sovereign", 10) in quickbattle.collisions()


def test_two_mod_ships_sharing_a_name_do_not_clobber_each_other():
    qb = _FakeQB()
    first = foundation.FedShipDef(
        "modA", 1, {"name": "Enterprise", "iconName": "A", "shipFile": "modA"})
    second = foundation.FedShipDef(
        "modB", 2, {"name": "Enterprise", "iconName": "B", "shipFile": "modB"})

    sid1 = quickbattle.register(first, "Fed Ships", qb=qb)
    sid2 = quickbattle.register(second, "Fed Ships", qb=qb)

    assert sid1 == sid2
    # The first writer's row survives; the second registration did not
    # overwrite it with "modB".
    assert qb.g_dFriendlyShipTypeToDetails[sid1][0] == "modA"
    assert ("Enterprise", sid1) in quickbattle.collisions()


def test_reregistering_the_same_ship_is_not_a_collision():
    """Every ship in our mod corpus calls RegisterQBShipMenu then
    RegisterQBPlayerShipMenu -- the standard generated pattern. The second
    call's name is already in g_dShipNameToType (written by the first),
    but it must not be reported as a collision or nine real ships would
    all look like clashes in the boot report."""
    qb = _FakeQB()
    d = _ship()

    sid1 = d.RegisterQBShipMenu("Fed Ships", qb=qb)
    sid2 = d.RegisterQBPlayerShipMenu("Fed Ships", qb=qb)

    assert sid1 == sid2 == 1000
    assert quickbattle.collisions() == []


def test_detail_rows_name_ai_modules_that_actually_import():
    """QuickBattle.StartSimulation2 does `__import__(row[3])` on the AI module
    named in the detail row, so a name that does not resolve takes the whole
    battle start down with a ModuleNotFoundError.

    We shipped "QuickBattleEnemyAI" -- invented, never a real module; the
    stock enemy rows all name "QuickBattleAI". Importing here is the check
    that catches it, because no amount of shape-testing can tell a plausible
    module name from a real one.
    """
    import importlib

    qb = _FakeQB()
    sid = quickbattle.register(_ship(), "Fed Ships", qb=qb)

    for table in (qb.g_dFriendlyShipTypeToDetails,
                  qb.g_dEnemyShipTypeToDetails):
        module_name = table[sid][3]
        importlib.import_module(module_name)   # raises if we invented it


def test_enemy_rows_use_the_same_ai_module_as_stock():
    qb = _FakeQB()
    stock_enemy_ai = qb.g_dEnemyShipTypeToDetails[10][3]
    sid = quickbattle.register(_ship(), "Fed Ships", qb=qb)
    assert qb.g_dEnemyShipTypeToDetails[sid][3] == stock_enemy_ai


def test_reset_clears_collisions():
    qb = _FakeQB()
    impostor = foundation.FedShipDef(
        "ImpostorSovereign", 42,
        {"name": "Sovereign", "iconName": "X", "shipFile": "ImpostorSovereign"})
    quickbattle.register(impostor, "Fed Ships", qb=qb)
    assert quickbattle.collisions()

    quickbattle.reset()
    assert quickbattle.collisions() == []
