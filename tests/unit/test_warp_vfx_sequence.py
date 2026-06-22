import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create


def setup_function(_):
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)


def test_duration_scales_with_distance():
    near = warp._transit_duration((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    far = warp._transit_duration((0.0, 0.0, 0.0), (1000.0, 0.0, 0.0))
    assert far > near
    assert warp._T_MIN <= near <= warp._T_MAX
    assert warp._T_MIN <= far <= warp._T_MAX
    # unmapped vantage -> T_BASE
    assert warp._transit_duration(None, (1.0, 0.0, 0.0)) == warp._T_BASE


def test_flythrough_disabled_is_instant(monkeypatch):
    # enabled() False -> instant Stage-1 sequence (no held swap): player warps now.
    warp.configure_warp_vfx(enabled=lambda: False)
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    import types, sys
    mod = types.ModuleType("FakeSys.D"); mod.Initialize = lambda: (
        App.g_kSetManager.AddSet(SetClass_Create(), "D"))
    sys.modules["FakeSys.D"] = mod
    warp.WarpSequence_Create(player, "FakeSys.D", placement=None).Play()
    assert App.g_kSetManager.GetSet("Src") is None   # instant swap happened


def test_flythrough_enabled_starts_vfx_and_defers_swap(monkeypatch):
    started = {}
    warp.configure_warp_vfx(
        enabled=lambda: True,
        start=lambda src, dst, dur, tdir: started.update(dur=dur),
        stop=lambda: None,
        vantage_of=lambda key: (0.0, 0.0, 0.0))
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src2")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    import types, sys
    mod = types.ModuleType("FakeSys.D2"); mod.Initialize = lambda: (
        App.g_kSetManager.AddSet(SetClass_Create(), "D2"))
    sys.modules["FakeSys.D2"] = mod
    seq = warp.WarpSequence_Create(player, "FakeSys.D2", placement="Player Start")
    seq.Play()
    # VFX started; swap is DEFERRED (held by delay) -> source still present at t=0.
    assert "dur" in started and started["dur"] > 0.0
    assert App.g_kSetManager.GetSet("Src2") is src
