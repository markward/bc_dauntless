import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create


def _waypoint(name, set_name, x):
    wp = App.Waypoint_Create(name, set_name, None)
    wp.SetTranslateXYZ(x, 0.0, 0.0); wp.Update(0)


def test_event_fire_warps_player(monkeypatch):
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)

    # source set + player
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    App.Game_SetCurrentPlayer(player)

    # destination module
    import types, sys
    mod = types.ModuleType("FakeSys.Dst")
    def Initialize():
        s = SetClass_Create(); App.g_kSetManager.AddSet(s, "Dst")
        _waypoint("Player Start", "Dst", 42.0)
    mod.Initialize = Initialize
    sys.modules["FakeSys.Dst"] = mod

    # a warp button registered like the SDK does
    btn = App.STWarpButton_CreateW("Warp")
    App.SortedRegionMenu_SetWarpButton(btn)
    btn.AddPythonFuncHandlerForInstance(App.ET_WARP_BUTTON_PRESSED,
                                        "engine.appc.warp.execute_warp")

    # host on_warp: set destination + fire event
    btn.SetDestination("FakeSys.Dst")
    ev = App.TGEvent_Create()
    ev.SetEventType(App.ET_WARP_BUTTON_PRESSED)
    ev.SetDestination(btn)
    App.g_kEventManager.AddEvent(ev)

    assert App.g_kSetManager.GetSet("Src") is None
    dst = App.g_kSetManager.GetSet("Dst")
    assert dst.GetObject("player") is player
    assert abs(player.GetWorldLocation().x - 42.0) < 1e-3
