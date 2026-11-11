"""Foundation.BridgeDef: bridge packs register a bridge config script, a
display name and per-location officer animations.

Call shapes from real bridge packs' Custom/Autoload scripts; every fixture is
our own code, no mod content.
"""
import pytest

import Foundation
from engine import foundation
from engine.foundation import bridge


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    foundation.reset()
    yield
    foundation.reset()


def _locations():
    return {
        "XHelm": ["data/animations/x_stand_h_m.nif", "x_stand_h_m"],
        "XL1S": ["data/animations/x_L1toG3_S.nif", "x_L1toG3_S",
                 "pCharacter.SetHidden(1)"],
    }


class _AM:
    def __init__(self):
        self.loaded = []

    def LoadAnimation(self, path, name):
        self.loaded.append((path, name))


class _Seq:
    def __init__(self):
        self.actions = []

    def AppendAction(self, action):
        self.actions.append(action)


class _Character:
    def __init__(self, location="XHelm"):
        self.hidden = 0
        self.location = location

    def SetHidden(self, value):
        self.hidden = value

    def GetLocation(self):
        return self.location

    def GetAnimNode(self):
        return "node"


# -- registration ------------------------------------------------------------

def test_bridgedef_registers_by_name_and_by_config_script():
    d = Foundation.BridgeDef("Xeno Bridge", "xenobridge",
                             dict={"modes": [Foundation.MutatorDef.Stock],
                                   "locations": _locations()})
    assert (d.name, d.bridgeString) == ("Xeno Bridge", "xenobridge")
    assert Foundation.bridgeList["Xeno Bridge"] is d
    assert Foundation.bridgeList["xenobridge"] is d
    assert Foundation.bridgeList._keyList["xenobridge"] is d
    assert Foundation.bridgeList[0] is d
    assert Foundation.bridgeList._arrayList == ["Xeno Bridge"]
    assert len(Foundation.bridgeList) == 1 and d.num == 0
    assert Foundation.bridgeList.has_key("Xeno Bridge")


def test_a_bridge_registered_twice_keeps_its_place():
    Foundation.BridgeDef("A", "abridge")
    Foundation.BridgeDef("B", "bbridge")
    again = Foundation.BridgeDef("A", "abridge")
    assert again.num == 0 and Foundation.bridgeList["A"] is again
    assert Foundation.bridgeList._arrayList == ["A", "B"]


def test_by_config_script_finds_the_definition():
    d = Foundation.BridgeDef("Xeno", "XenoBridge")
    assert bridge.by_config_script("XenoBridge") is d
    assert bridge.by_config_script("xenobridge") is d     # folded, like the index
    assert bridge.by_config_script("GalaxyBridge") is None


def test_a_mod_can_subclass_bridgedef_and_mutatorelementdef():
    class Implicit(Foundation.BridgeDef):
        def __init__(self, name, dict={}):
            Foundation.BridgeDef.__init__(self, name, name, dict)
            self.IsImplicit = 1

    class Element(Foundation.MutatorElementDef):
        pass

    assert Implicit("Pick").IsImplicit == 1
    assert Element("E", {}).name == "E"


def test_settings_we_do_not_use_are_reported_once():
    Foundation.BridgeDef("A", "abridge", dict={"Maps": {}, "bridgeSound": {}})
    Foundation.BridgeDef("B", "bbridge", dict={"Maps": {}, "LoadingScreen": "x"})
    assert bridge.ignored_settings() == ["LoadingScreen", "Maps", "bridgeSound"]


def test_a_bridge_is_added_to_its_modes():
    d = Foundation.BridgeDef("A", "abridge", dict={"modes": [Foundation.MutatorDef.Stock]})
    assert Foundation.MutatorDef.Stock.elements == [d]
    assert Foundation.MutatorDef.Stock.bridgeList["A"] is d


def test_reset_forgets_bridges():
    Foundation.BridgeDef("A", "abridge", dict={"modes": [Foundation.MutatorDef.Stock]})
    foundation.reset()
    assert len(Foundation.bridgeList) == 0
    assert bridge.by_config_script("abridge") is None
    assert Foundation.MutatorDef.Stock.elements == []


# -- the current bridge and officer locations ---------------------------------

def test_the_current_bridge_is_the_loaded_bridge_sets_config(monkeypatch):
    d = Foundation.BridgeDef("Xeno", "xenobridge", dict={"locations": _locations()})
    monkeypatch.setattr(bridge, "_current_config", lambda: "xenobridge")
    assert Foundation.pCurrentBridge is d
    monkeypatch.setattr(bridge, "_current_config", lambda: "GalaxyBridge")
    assert Foundation.pCurrentBridge is None


def test_set_location_loads_and_places_the_animation():
    d = Foundation.BridgeDef("Xeno", "xenobridge", dict={"locations": _locations()})
    am, seq = _AM(), _Seq()
    assert d.SetLocation("XHelm", am, seq, "node") == 1
    assert am.loaded == [("data/animations/x_stand_h_m.nif", "x_stand_h_m")]
    assert [a.name for a in seq.actions] == ["x_stand_h_m"]


def test_a_locations_extra_statements_run_with_the_character():
    """Foundation exec'd these strings where no `pCharacter` was defined, so
    the NameError was swallowed and lift officers stayed visible. BC's own
    lift locations hide the officer; the statement says so too."""
    d = Foundation.BridgeDef("Xeno", "xenobridge", dict={"locations": _locations()})
    who = _Character("XL1S")
    assert d.SetLocation("XL1S", _AM(), _Seq(), "node", pCharacter=who) == 1
    assert who.hidden == 1


def test_an_unknown_location_is_not_handled():
    d = Foundation.BridgeDef("Xeno", "xenobridge", dict={"locations": _locations()})
    seq = _Seq()
    assert d.SetLocation("DBHelm", _AM(), seq, "node") is None
    assert seq.actions == []
    assert Foundation.BridgeDef("Bare", "barebridge").SetLocation(
        "XHelm", _AM(), _Seq(), "node") is None


def test_a_failing_extra_statement_still_places_the_officer(capsys):
    locs = {"XHelm": ["a.nif", "a", "pCharacter.NoSuchMethod()"]}
    d = Foundation.BridgeDef("Xeno", "xenobridge", dict={"locations": locs})
    seq = _Seq()
    assert d.SetLocation("XHelm", _AM(), seq, "node", pCharacter=_Character()) == 1
    assert len(seq.actions) == 1
    assert "NoSuchMethod" in capsys.readouterr().err


def test_bridge_set_location_asks_the_current_bridge(monkeypatch):
    Foundation.BridgeDef("Xeno", "xenobridge", dict={"locations": _locations()})
    monkeypatch.setattr(bridge, "_current_config", lambda: "xenobridge")
    seq = _Seq()
    assert Foundation.BridgeSetLocation("XHelm", _AM(), seq, "node") == 1
    monkeypatch.setattr(bridge, "_current_config", lambda: None)
    assert Foundation.BridgeSetLocation("XHelm", _AM(), _Seq(), "node") is None
