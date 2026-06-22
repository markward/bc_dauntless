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


def test_event_fire_with_real_warppressed_warps_player(monkeypatch):
    """Production registers TWO handlers on the warp button, in order:
    the SDK's Bridge.HelmMenuHandlers.WarpPressed (camera/cinematic +
    MissionLib.RemoveControl) FIRST, then engine.appc.warp.execute_warp
    SECOND (the handler that actually warps). This locks in the composed
    two-handler control flow: WarpPressed must run without raising and
    without aborting the handler loop, so execute_warp still warps the
    player. Mirrors test_event_fire_warps_player but with both handlers.
    """
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)

    # source set + player
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    App.Game_SetCurrentPlayer(player)

    # WarpPressed reads CharacterClass_GetObject(GetSet("bridge"), "Helm"/"XO");
    # a present (empty) bridge set keeps it on the faithful path. WarpPressed
    # tolerates a missing helm/XO character (no-character subtitle branch).
    App.g_kSetManager.AddSet(SetClass_Create(), "bridge")

    # destination module
    import types, sys
    mod = types.ModuleType("FakeSys.Dst")
    def Initialize():
        s = SetClass_Create(); App.g_kSetManager.AddSet(s, "Dst")
        _waypoint("Player Start", "Dst", 42.0)
    mod.Initialize = Initialize
    sys.modules["FakeSys.Dst"] = mod

    # a warp button registered like the SDK does, with BOTH production
    # handlers in production order: SDK WarpPressed first, execute_warp second.
    btn = App.STWarpButton_CreateW("Warp")
    App.SortedRegionMenu_SetWarpButton(btn)
    btn.AddPythonFuncHandlerForInstance(App.ET_WARP_BUTTON_PRESSED,
                                        "Bridge.HelmMenuHandlers.WarpPressed")
    btn.AddPythonFuncHandlerForInstance(App.ET_WARP_BUTTON_PRESSED,
                                        "engine.appc.warp.execute_warp")

    # host on_warp: set destination + fire event
    btn.SetDestination("FakeSys.Dst")
    ev = App.TGEvent_Create()
    ev.SetEventType(App.ET_WARP_BUTTON_PRESSED)
    ev.SetDestination(btn)
    App.g_kEventManager.AddEvent(ev)

    # Same end state as test_event_fire_warps_player: execute_warp still ran
    # and warped EVEN THOUGH WarpPressed ran first.
    assert App.g_kSetManager.GetSet("Src") is None
    dst = App.g_kSetManager.GetSet("Dst")
    assert dst.GetObject("player") is player
    assert abs(player.GetWorldLocation().x - 42.0) < 1e-3
