"""An NPC that warps "blindly" (no destination: AI Warp's WarpBlindly) leaves
its set for BC's "warp" set and stays parked there, hidden in BC (the SDK's
WarpSequence.SetupSequence HideShip). A mission change keeps the warp set, so
without a rule every blind warp would ride into every later mission: E2M0's
two Warbirds into E2M1, and so on.

Chosen behaviour (BC's own handling is unknown): a blind-warped NPC still
parked in the warp set is dropped at the mission change, after the old
mission's handlers are gone, so no mission script hears about it. Anything
else in the warp set (the player, ships a mission placed there itself, as
E6M1 does with the Artrus ships) is kept."""
import App
from engine.core import mission_change
from engine.core.loop import GameLoop
from engine.appc import warp
from tests.helpers.mission_change_fixtures import (
    log, _install, _world, _forget_world)


def teardown_function(_):
    _forget_world()


def _npc_in(set_name, name):
    ship = App.ShipClass_Create()
    ship.SetName(name)
    App.g_kSetManager.GetSet(set_name).AddObjectToSet(ship, name)
    return ship


def _blind_warp(ship):
    App.WarpSequence_Create(ship, None, 1.0, None).Play()
    loop = GameLoop()
    for _ in range(60 * 5):
        loop.tick()
    assert App.g_kSetManager.GetSet("warp").GetObject(ship.GetName()) is ship


def _change():
    _install("_t.Old", Terminate=lambda m: None)
    _install("_t.New", Initialize=lambda m: None)
    assert mission_change.change(mission="_t.New") is True


def test_a_blind_warped_npc_is_dropped_at_the_mission_change():
    _game, player, _ = _world()
    warbird = _npc_in("Beol4", "Warbird 1")
    _blind_warp(warbird)
    _change()
    warp_set = App.g_kSetManager.GetSet("warp")
    assert warp_set.GetObject("Warbird 1") is None
    assert warbird.GetContainingSet() is None
    assert warp_set.GetObject("player") is player


def test_a_ship_a_mission_parked_in_the_warp_set_is_kept():
    _world()
    artrus = _npc_in("warp", "Artrus 1")
    _change()
    assert App.g_kSetManager.GetSet("warp").GetObject("Artrus 1") is artrus


def test_a_blind_warper_that_later_leaves_for_a_destination_is_kept():
    """Mid-transit on a real warp at the change: it is on its way somewhere,
    not parked."""
    _world()
    warbird = _npc_in("Beol4", "Warbird 1")
    _blind_warp(warbird)
    warp._WarpDepartAction(App.g_kSetManager.GetSet("warp"), warbird,
                           hard_cut=True).Play()
    _change()
    assert App.g_kSetManager.GetSet("warp").GetObject("Warbird 1") is warbird


def test_the_old_mission_never_hears_the_drop():
    game, _player, _ = _world()
    warbird = _npc_in("Beol4", "Warbird 1")
    _blind_warp(warbird)
    heard = []
    _install("_t.Old", Terminate=lambda m: None,
             Exited=lambda obj, ev: heard.append(ev.GetCString()))
    _install("_t.New", Initialize=lambda m: None)
    old_mission = game.GetCurrentEpisode().GetCurrentMission()
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_EXITED_SET, old_mission, "_t.Old.Exited")
    assert mission_change.change(mission="_t.New") is True
    assert App.g_kSetManager.GetSet("warp").GetObject("Warbird 1") is None
    assert "warp" not in heard
