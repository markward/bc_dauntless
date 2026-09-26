"""The tunnel announces ET_EXITED_WARP on the PLAYER's arrival (ruling R16).

Nine SDK hooks listen for it (E1M2 FirstHavenHail, E2M6 PlayerEntersBiranu,
E8M2 Briefing, ...) and were written for tunnel arrivals; the in-system dash
posts it at every drop-out (engine/systems/handoff.post_exited_warp), so the
tunnel posting nothing was an asymmetry. It is posted AFTER the placement --
a handler reads the arrival pose and set -- with source = destination = the
player, on both the flythrough and the hard-cut branch, and never for an NPC
(the SDK hooks all test the event against the player). Where in BC's C++
chain it fires is inferred from those hooks.
"""
import sys
import types

import pytest

import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create
from tests.helpers.warp_sdk_modules import warp_missionlib


def setup_function(_):
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)


def teardown_function(_):
    warp.configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)
    App.g_kSetManager._sets.clear()


def _dest_module(name):
    def init():
        s = SetClass_Create()
        App.g_kSetManager.AddSet(s, name)
        wp = App.Waypoint_Create("Player Start", name, None)
        wp.SetTranslateXYZ(10.0, 20.0, 30.0)
        wp.Update(0)
    mod = types.ModuleType("FakeSys." + name)
    mod.Initialize = init
    sys.modules["FakeSys." + name] = mod
    return "FakeSys." + name


def _ship_in(set_name, ship_name):
    s = App.g_kSetManager.GetSet(set_name)
    if s is None:
        s = SetClass_Create()
        App.g_kSetManager.AddSet(s, set_name)
    ship = App.ShipClass_Create()
    ship.SetName(ship_name)
    s.AddObjectToSet(ship, ship_name)
    return ship


@pytest.fixture
def exits(monkeypatch):
    """Every ET_EXITED_WARP posted: (source, destination, the source's set
    name and location at that moment)."""
    seen = []
    orig = App.g_kEventManager.AddEvent

    def _add(evt):
        if evt.GetEventType() == App.ET_EXITED_WARP:
            src = evt.GetSource()
            s = src.GetContainingSet() if src is not None else None
            p = src.GetWorldLocation() if src is not None else None
            seen.append((src, evt.GetDestination(),
                         s.GetName() if s is not None else None,
                         (p.x, p.y, p.z) if p is not None else None))
        orig(evt)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", _add)
    monkeypatch.setattr(warp_missionlib(), "g_idMasterSequenceObj", None)
    return seen


def _advance(seconds, step=1.0 / 60.0):
    for _ in range(int(round(seconds / step))):
        App.g_kTimerManager.tick(step)


def test_a_hard_cut_arrival_posts_exited_warp_after_the_placement(
        exits, monkeypatch):
    player = _ship_in("Src", "player")
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: player)
    warp.configure_warp_vfx(enabled=lambda: False)
    warp.WarpSequence_Create(player, _dest_module("HCDest"), 0.0,
                             "Player Start").Play()
    _advance(1.0)
    assert exits == [(player, player, "HCDest", pytest.approx((10.0, 20.0, 30.0)))]


def test_a_flythrough_arrival_posts_exited_warp_after_the_placement(
        exits, monkeypatch):
    player = _ship_in("Src", "player")
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: player)
    warp.configure_warp_vfx(
        enabled=lambda: True, start=lambda *a, **k: None, stop=lambda: None,
        vantage_of=lambda key: None)
    warp.WarpSequence_Create(player, _dest_module("FTDest"), 0.0,
                             "Player Start").Play()
    assert exits == [], "nothing at engage"
    _advance(warp._T_ALIGN_MAX + warp._T_BASE + 1.0)
    assert exits == [(player, player, "FTDest", pytest.approx((10.0, 20.0, 30.0)))]


def test_an_npc_arrival_posts_no_exited_warp(exits, monkeypatch):
    player = _ship_in("Src", "player")
    npc = _ship_in("Src", "npc")
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: player)
    warp.configure_warp_vfx(enabled=lambda: False)
    warp.WarpSequence_Create(npc, _dest_module("NPCDest"), 0.0,
                             "Player Start").Play()
    _advance(1.0)
    assert App.g_kSetManager.GetSet("NPCDest").GetObject("npc") is npc
    assert exits == []
