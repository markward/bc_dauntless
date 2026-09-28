"""An NPC's warp moves the NPC, not the player's scene.

Every AI warp (AI/PlainAI/Warp.py -> WarpSequence_Create) runs the same
action spine as the player's. The player-scene effects in it -- the rendered
set, the source set's render teardown, the WarpVFX tunnel, MissionLib
Remove/ReturnControl, the helm menu, the target menu -- belong to the player
alone; the NPC still passes through "warp" into its destination set."""
import sys
import types

import pytest

import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create
from tests.helpers.warp_sdk_modules import warp_missionlib


def _advance_game_time(seconds, step=1.0 / 60.0):
    for _ in range(int(round(seconds / step))):
        App.g_kTimerManager.tick(step)


@pytest.fixture
def scene(monkeypatch):
    """The player at Home (rendered) with an NPC beside it; every
    player-scene hook records into `calls`."""
    from engine import warp_vfx
    import engine.bridge_officers as officers
    import engine.appc.target_menu as target_menu
    App.g_kSetManager._sets.clear()
    warp_vfx.get().stop()
    calls = []
    home = SetClass_Create(); App.g_kSetManager.AddSet(home, "Home")
    player = App.ShipClass_Create(); player.SetName("player")
    npc = App.ShipClass_Create(); npc.SetName("npc")
    home.AddObjectToSet(player, "player")
    home.AddObjectToSet(npc, "npc")
    App.g_kSetManager.MakeRenderedSet("Home")
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: player)
    warp.configure_warp_hooks(
        realize=lambda s: calls.append(("realize", s.GetName())),
        teardown=lambda s: calls.append(("teardown", s.GetName())))
    # The SDK WarpSequence (WaitForQueued) binds the real MissionLib first;
    # only warp.py's own Remove/ReturnControl import then sees the recorder.
    warp_missionlib()
    missionlib = types.ModuleType("MissionLib")
    missionlib.RemoveControl = lambda *a: calls.append("RemoveControl")
    missionlib.ReturnControl = lambda *a: calls.append("ReturnControl")
    monkeypatch.setitem(sys.modules, "MissionLib", missionlib)
    monkeypatch.setattr(officers, "enable_helm_menu",
                        lambda: calls.append("enable_helm_menu"))

    class _Menu:
        def ClearPersistentTarget(self):
            calls.append("ClearPersistentTarget")
    monkeypatch.setattr(target_menu, "STTargetMenu_GetTargetMenu",
                        lambda: _Menu())
    mod = types.ModuleType("FakeSys.NpcDest")
    mod.Initialize = lambda: App.g_kSetManager.AddSet(SetClass_Create(),
                                                      "NpcDest")
    monkeypatch.setitem(sys.modules, "FakeSys.NpcDest", mod)
    yield player, npc, calls
    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(start=None, stop=None, enabled=None,
                            vantage_of=None)
    warp_vfx.get().stop()
    App.g_kSetManager._sets.clear()


def _in_set(name, ship):
    s = App.g_kSetManager.GetSet(name)
    return s is not None and s.GetObject(ship.GetName()) is ship


def test_npc_flythrough_warp_leaves_the_players_scene_alone(scene):
    from engine import warp_vfx
    from engine.warp_vfx import _T_EXIT_DECEL
    player, npc, calls = scene
    warp.configure_warp_vfx(
        enabled=lambda: True,
        start=lambda *a, **k: calls.append("vfx_start"),
        stop=lambda: calls.append("vfx_stop"),
        vantage_of=lambda key: None)
    seq = warp.WarpSequence_Create(npc, "FakeSys.NpcDest", 0.0, None)
    seq.Play()
    _advance_game_time(warp._T_ALIGN_MIN + 0.5)      # past departure
    assert _in_set(warp._WARP_TRANSIT_SET_NAME, npc)
    assert warp_vfx.get().is_held() is False
    _advance_game_time(warp._T_BASE + _T_EXIT_DECEL + 2.0)
    assert _in_set("NpcDest", npc)                   # the NPC arrived
    assert not _in_set(warp._WARP_TRANSIT_SET_NAME, npc)
    assert _in_set("Home", player)
    assert App.g_kSetManager.get_explicit_rendered_set() is \
        App.g_kSetManager.GetSet("Home")
    assert calls == []
    assert warp_vfx.get().is_held() is False


def test_npc_hard_cut_warp_leaves_the_players_scene_alone(scene):
    player, npc, calls = scene
    warp.WarpSequence_Create(npc, "FakeSys.NpcDest", 0.0, None).Play()
    _advance_game_time(0.5)
    assert _in_set("NpcDest", npc)
    assert App.g_kSetManager.get_explicit_rendered_set() is \
        App.g_kSetManager.GetSet("Home")
    assert calls == []


def test_the_players_flythrough_warp_still_changes_its_scene(scene,
                                                             monkeypatch):
    """The control arm: the same hooks fire for the player's own warp."""
    from engine.warp_vfx import _T_EXIT_DECEL
    player, npc, calls = scene
    monkeypatch.setattr(warp_missionlib(), "g_idMasterSequenceObj", None)
    warp.configure_warp_vfx(
        enabled=lambda: True,
        start=lambda *a, **k: calls.append("vfx_start"),
        stop=lambda: calls.append("vfx_stop"),
        vantage_of=lambda key: None)
    warp.WarpSequence_Create(player, "FakeSys.NpcDest", 0.0, None).Play()
    _advance_game_time(warp._T_ALIGN_MIN + warp._T_BASE + _T_EXIT_DECEL + 2.0)
    assert _in_set("NpcDest", player)
    assert App.g_kSetManager.get_explicit_rendered_set() is \
        App.g_kSetManager.GetSet("NpcDest")
    for c in ("RemoveControl", "vfx_start", ("teardown", "Home"),
              ("realize", "NpcDest"), "ReturnControl", "vfx_stop",
              "enable_helm_menu", "ClearPersistentTarget"):
        assert c in calls, c
