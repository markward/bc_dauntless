# tests/unit/test_fx_api_lib.py
"""Custom.NanoFXv2.NanoFX_Lib + script actions on Dauntless systems
(spec 2026-10-16 §8.2, §8.4)."""
import importlib

import pytest

import App
import Foundation
from engine import foundation, ship_catalog
from engine.appc import glow_maps

ACTIONS = "Custom.NanoFXv2.NanoFX_ScriptActions"


@pytest.fixture
def lib():
    m = importlib.import_module("Custom.NanoFXv2.NanoFX_Lib")
    m.g_FlickerControl = 0
    del m.g_LightsOff[:]
    return m


@pytest.fixture
def acts():
    return importlib.import_module(ACTIONS)


@pytest.fixture(autouse=True)
def _foundation():
    foundation.reset()
    yield
    foundation.reset()


class _ScriptedShip:
    """Mirrors the one ShipClass method these helpers read."""
    def __init__(self, script):
        self._script = script

    def GetScript(self):
        return self._script


def _script_steps(seq):
    """(func_name, args, delay) of each TGScriptAction step, in order."""
    return [(s.action._func_name, s.action._args, s.delay) for s in seq._steps]


def test_flicker_ends_on_requested_state_and_caps_concurrency(lib, monkeypatch):
    monkeypatch.setattr(App.g_kSystemWrapper, "GetRandomNumber", lambda n: 0)
    ship = App.ShipClass_Create("F")
    seq = lib.CreateFlickerSeq(ship, 1.0, 0.2, "Off")
    steps = _script_steps(seq)
    glow = [s for s in steps if s[0] == "SetShipGlow"]
    assert glow[-1] == ("SetShipGlow", (ship, 0), 1.0)
    assert {s[1][1] for s in glow[:-1]} == {0, 1}           # it actually flickers
    assert ("ControlFlickers", (-1,), 1.0) in steps
    assert lib.g_FlickerControl == 1
    lib.CreateFlickerSeq(ship, 1.0)
    assert lib.g_FlickerControl == 2
    third = lib.CreateFlickerSeq(ship, 1.0)
    assert third._steps == [] and lib.g_FlickerControl == 2
    assert "F" in lib.g_LightsOff


def test_set_ship_glow_toggles_one_ship(acts):
    ship = App.ShipClass_Create("G")
    assert acts.SetShipGlow(None, ship, 0) == 0
    assert glow_maps.is_dark(ship)
    acts.SetShipGlow(None, ship, 1)
    assert not glow_maps.is_dark(ship)
    assert acts.SetShipGlow(None, None, 0) == 0     # a ship gone mid-sequence


def test_turn_off_and_on_lights(acts):
    ship = App.ShipClass_Create("L")
    acts.TurnOffLights(None, ship)
    assert glow_maps.is_dark(ship)
    acts.TurnOnLights(None)
    assert not glow_maps.is_dark(ship)
    assert App.g_kLODModelManager.AreGlowMapsEnabled() == 1


def test_set_nano_rotation_sets_spin_magnitude(acts, monkeypatch):
    monkeypatch.setattr(App.g_kSystemWrapper, "GetRandomNumber", lambda n: n - 1)
    ship = App.ShipClass_Create("Rot")
    acts.SetNanoRotation(None, ship, 90.0, None)
    w = ship.GetAngularVelocityTG()
    mag = (w.x ** 2 + w.y ** 2 + w.z ** 2) ** 0.5
    assert mag == pytest.approx(90.0 * App.HALF_PI / 180.0, rel=1e-4)


def test_rotation_seq_schedules_set_nano_rotation(lib, monkeypatch):
    monkeypatch.setattr(App.g_kSystemWrapper, "GetRandomNumber", lambda n: 0)
    ship = App.ShipClass_Create("RS")
    seq = lib.CreateRotationSeq(ship, 200)
    (name, args, _delay), = _script_steps(seq)
    assert name == "SetNanoRotation" and args == (ship, 2.0, None)


def test_special_fx_seq_returns_none(lib):
    assert lib.CreateSpecialFXSeq(None, None, "PlasmaFX") is None
    assert lib.CreateSpecialFXSeq(None, None, "PlasmaFX", 1) is None


def test_species_from_catalog_then_shipdef(lib, monkeypatch):
    class _E:
        species = "Klingon"
    monkeypatch.setattr(ship_catalog, "entry",
                        lambda sid: _E() if sid == "BirdOfPrey" else None)
    assert lib.GetSpeciesName(_ScriptedShip("ships.BirdOfPrey")) == "Klingon"
    Foundation.ShipDef.ZZFoo = Foundation.FedShipDef("ZZFoo", 1, {"name": "ZZFoo", "shipFile": "ZZFoo"})
    assert lib.GetSpeciesName(_ScriptedShip("ships.ZZFoo")) == "Federation"
    assert lib.GetSpeciesName(_ScriptedShip("ships.Nothing")) == "Default"


def test_override_color_reads_the_shipdef_hook(lib):
    d = Foundation.FedShipDef("ZZBar", 1, {"name": "ZZBar", "shipFile": "ZZBar"})
    Foundation.ShipDef.ZZBar = d
    d.OverrideWarpFXColor = lambda _self: (1.0, 2.0, 3.0)
    ship = _ScriptedShip("ships.ZZBar")
    assert lib.GetOverrideColor(ship, "WarpFX") == (1.0, 2.0, 3.0)
    assert lib.GetOverrideColor(ship, "PlasmaFX") is None


def test_race_texture_colour_table(lib):
    assert lib.GetRaceTextureColor("Federation") == (55.0, 120.0, 255.0)
    assert lib.GetRaceTextureColor("Nobody") == (155.0, 120.0, 255.0)
