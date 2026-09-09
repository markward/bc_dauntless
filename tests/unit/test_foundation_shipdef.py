"""Foundation's ship-definition surface, as real mods use it."""

import pytest

from engine import foundation


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    yield
    foundation.reset()


def _make(name="LCintrepidZZ"):
    return foundation.FedShipDef(
        name, 42, {"name": "U.S.S. Intrepid", "iconName": "LCIntrepid",
                   "shipFile": name})


def test_fedshipdef_carries_the_details_dict():
    d = _make()
    assert d.name == "U.S.S. Intrepid"
    assert d.iconName == "LCIntrepid"
    assert d.shipFile == "LCintrepidZZ"
    assert d.abbrev == "LCintrepidZZ"
    assert d.species == 42
    assert d.race == "Fed"


def test_shipdef_namespace_assignment_and_dict_readback():
    # Exactly the shape generated ship scripts use.
    foundation.ShipDef.LCintrepidZZ = _make()
    foundation.ShipDef.LCintrepidZZ.desc = "a ship"
    assert foundation.ShipDef.__dict__["LCintrepidZZ"].desc == "a ship"


def test_borg_shipdef_is_a_distinct_race():
    d = foundation.BorgShipDef("Cube", 7, {"name": "Cube"})
    assert d.race == "Borg"


def test_an_unseen_race_is_synthesised_not_an_error():
    """Foundation has races we have never seen in a mod. A KlingonShipDef
    must not raise AttributeError at import and take the whole mod down."""
    d = foundation.KlingonShipDef("Vorcha", 3, {"name": "Vor'cha"})
    assert d.race == "Klingon"
    assert "KlingonShipDef" in foundation.synthesised_races()


def test_a_non_shipdef_attribute_still_raises():
    # The __getattr__ hook must not swallow genuine typos.
    with pytest.raises(AttributeError):
        foundation.TotallyUnrelatedThing


def test_details_lists_are_indexable_at_two():
    # Generated boilerplate does friendlyDetails[2] = ... unconditionally.
    d = _make()
    d.friendlyDetails[2] = "x"
    d.enemyDetails[2] = "y"
    assert d.friendlyDetails[2] == "x"
    assert d.enemyDetails[2] == "y"


def test_optional_attributes_default_and_accept():
    d = _make()
    assert d.desc == ""
    assert d.SubMenu is None and d.SubSubMenu is None
    assert d.dTechs == {}
    d.SubMenu, d.SubSubMenu = "TNG Ships", "Intrepid Class"
    d.hasTGLName, d.hasTGLDesc = 1, 1
    d.dTechs = {"AutoTargeting": {"Phaser": [2, 1]}}
    assert d.dTechs["AutoTargeting"]["Phaser"] == [2, 1]


def test_unknown_attributes_are_recorded_not_rejected():
    """A third mod will set something these two do not. Record it so the
    report can name it, rather than failing the import."""
    d = _make()
    d.someFutureFlag = 3
    assert d.unknown_attributes["someFutureFlag"] == 3


def test_shiplist_is_dict_like_with_keylist():
    # The generated tail: shipList._keyList.has_key(longName)
    foundation.shipList["U.S.S. Intrepid"] = _make()
    assert foundation.shipList._keyList.has_key("U.S.S. Intrepid")
    assert not foundation.shipList._keyList.has_key("nope")
    assert foundation.shipList.has_key("U.S.S. Intrepid")
    assert foundation.shipList["U.S.S. Intrepid"].shipFile == "LCintrepidZZ"


def test_generated_boilerplate_tail_runs_end_to_end():
    """The exact five lines every Bridge Commander Universal Tool script
    ends with. If this raises, every generated mod fails at import."""
    longName = "U.S.S. Intrepid"
    foundation.ShipDef.LCintrepidZZ = _make()
    foundation.shipList[longName] = foundation.ShipDef.LCintrepidZZ
    foundation.ShipDef.__dict__[longName] = foundation.ShipDef.LCintrepidZZ

    if foundation.shipList._keyList.has_key(longName):
        foundation.ShipDef.__dict__[longName].friendlyDetails[2] = \
            foundation.shipList[longName].friendlyDetails[2]
        foundation.ShipDef.__dict__[longName].enemyDetails[2] = \
            foundation.shipList[longName].enemyDetails[2]
