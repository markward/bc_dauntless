import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create


def setup_function(_):
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)


def test_heading_is_normalized_src_to_dst():
    h = warp._warp_heading((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    assert abs(h[0] - 1.0) < 1e-6 and abs(h[1]) < 1e-6
    # Unmapped SOURCE (mission sets aren't galaxy-mapped) -> heading toward the
    # destination from the galaxy origin, so the ship still turns to the system.
    h2 = warp._warp_heading(None, (0.0, 0.0, 5.0))
    assert abs(h2[2] - 1.0) < 1e-6 and abs(h2[0]) < 1e-6
    # Missing DESTINATION -> default ship-forward.
    assert warp._warp_heading((0.0, 0.0, 0.0), None) == (0.0, 1.0, 0.0)


def test_flythrough_on_holds_swap_and_starts_vfx():
    started = {}
    warp.configure_warp_vfx(
        enabled=lambda: True,
        start=lambda heading, t_align, t_transit: started.update(
            align=t_align, transit=t_transit, heading=heading),
        stop=lambda: None,
        vantage_of=lambda key: (0.0, 0.0, 0.0))
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    import types, sys
    mod = types.ModuleType("FakeSys.D"); mod.Initialize = lambda: (
        App.g_kSetManager.AddSet(SetClass_Create(), "D"))
    sys.modules["FakeSys.D"] = mod
    warp.WarpSequence_Create(player, "FakeSys.D", placement="Player Start").Play()
    assert started.get("align") == warp._T_ALIGN
    assert started.get("transit") > 0.0
    assert App.g_kSetManager.GetSet("Src") is src   # swap DEFERRED


def test_flythrough_off_is_instant():
    warp.configure_warp_vfx(enabled=lambda: False)
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src2")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    import types, sys
    mod = types.ModuleType("FakeSys.D2"); mod.Initialize = lambda: (
        App.g_kSetManager.AddSet(SetClass_Create(), "D2"))
    sys.modules["FakeSys.D2"] = mod
    warp.WarpSequence_Create(player, "FakeSys.D2", placement=None).Play()
    assert App.g_kSetManager.GetSet("Src2") is None   # instant swap
