"""Officers on a bridge pack's bridge stand where its BridgeDef says.

BC's officer placement (Bridge/Characters/CommonAnimations.SetPosition)
knows only the stock bridges' location names; Foundation asked the current
bridge's BridgeDef first. engine/bridge_positions wraps SetPosition to do
the same. Fixtures are our own code.
"""
import types

import pytest

import Foundation
from engine import bridge_positions, foundation
from engine.foundation import bridge


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    yield
    foundation.reset()


class _Character:
    def __init__(self, location):
        self.location = location
        self.hidden = 0

    def GetLocation(self):
        return self.location

    def GetAnimNode(self):
        return "node"

    def SetHidden(self, value):
        self.hidden = value


def _stock_module():
    calls = []

    def SetPosition(pCharacter):
        calls.append(pCharacter.GetLocation())
        return "stock sequence"

    return types.SimpleNamespace(SetPosition=SetPosition), calls


def _pack(monkeypatch, loaded="xenobridge"):
    Foundation.BridgeDef("Xeno", "xenobridge", dict={"locations": {
        "XHelm": ["data/animations/x_h.nif", "x_h"],
        "XL1S": ["data/animations/x_l1.nif", "x_l1", "pCharacter.SetHidden(1)"],
    }})
    monkeypatch.setattr(bridge, "_current_config", lambda: loaded)


def test_a_pack_location_is_placed_by_the_bridgedef(monkeypatch):
    _pack(monkeypatch)
    module, calls = _stock_module()
    assert bridge_positions.install(module) is True
    seq = module.SetPosition(_Character("XHelm"))
    assert [seq.GetAction(i).name for i in range(seq.GetNumActions())] == ["x_h"]
    assert calls == []


def test_a_pack_lift_location_hides_the_officer(monkeypatch):
    _pack(monkeypatch)
    module, _ = _stock_module()
    bridge_positions.install(module)
    who = _Character("XL1S")
    module.SetPosition(who)
    assert who.hidden == 1


def test_a_stock_location_still_goes_to_bc(monkeypatch):
    _pack(monkeypatch)
    module, calls = _stock_module()
    bridge_positions.install(module)
    assert module.SetPosition(_Character("DBHelm")) == "stock sequence"
    assert calls == ["DBHelm"]


def test_a_stock_bridge_goes_to_bc(monkeypatch):
    _pack(monkeypatch, loaded="GalaxyBridge")
    module, calls = _stock_module()
    bridge_positions.install(module)
    assert module.SetPosition(_Character("XHelm")) == "stock sequence"
    assert calls == ["XHelm"]


def test_install_is_idempotent(monkeypatch):
    _pack(monkeypatch)
    module, calls = _stock_module()
    assert bridge_positions.install(module) is True
    assert bridge_positions.install(module) is False
    module.SetPosition(_Character("DBHelm"))
    assert calls == ["DBHelm"]


def test_capture_placement_installs_the_wrap():
    import Bridge.Characters.CommonAnimations as common
    from engine.appc import bridge_placement
    try:
        # Our stand-in is no CharacterClass, so BC's own SetPosition may
        # refuse it; the wrap is installed before that call either way.
        bridge_placement.capture_placement(_Character(""))
    except AttributeError:
        pass
    assert getattr(common.SetPosition, "_dauntless_bridge_positions_orig", None)
