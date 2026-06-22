import App
from engine.appc import warp, warp_gates
from engine.appc.sets import SetClass_Create


def _dest_module(name, set_name):
    import types, sys
    mod = types.ModuleType(name)
    def Initialize():
        s = SetClass_Create(); App.g_kSetManager.AddSet(s, set_name)
        wp = App.Waypoint_Create("Player Start", set_name, None)
        wp.SetTranslateXYZ(1.0, 0.0, 0.0); wp.Update(0)
    mod.Initialize = Initialize
    sys.modules[name] = mod


def test_blocked_warp_does_not_load_destination(monkeypatch):
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    # A freshly-created ShipClass has impulse power 0.0, which would trip the
    # impulse (XO) gate first; give it power so the warp-disabled gate (the one
    # this test forces) is the deciding check.
    player.GetImpulseEngineSubsystem().SetPowerPercentageWanted(1.0)
    App.Game_SetCurrentPlayer(player)
    _dest_module("FakeSys.Blocked", "BlockedDst")

    btn = App.STWarpButton_CreateW("Warp"); App.SortedRegionMenu_SetWarpButton(btn)
    btn.SetDestination("FakeSys.Blocked")

    # Force a block: warp engine disabled.
    monkeypatch.setattr(warp_gates, "_warp_disabled", lambda s: True)
    spoken = []
    monkeypatch.setattr(warp_gates, "speak_deny",
                        lambda ship, key: spoken.append(key))

    # Drive the same call on_warp_engage makes.
    result = warp_gates.warp_gate(player)
    assert result.allowed is False
    # execute_warp must NOT run when blocked: emulate on_warp_engage.
    if result.allowed:
        warp.execute_warp(btn)
    else:
        warp_gates.speak_deny(player, result.deny_line)

    assert App.g_kSetManager.GetSet("BlockedDst") is None   # never loaded
    assert App.g_kSetManager.GetSet("Src") is src           # still home
    assert spoken == ["CantWarp1"]
