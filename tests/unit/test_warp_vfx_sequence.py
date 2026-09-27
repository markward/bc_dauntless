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
        start=lambda heading, t_align, t_transit, vantage=None, dst_vantage=None,
            t_hold=0.0:
            started.update(align=t_align, transit=t_transit, heading=heading,
                           vantage=vantage, dst_vantage=dst_vantage),
        stop=lambda: None,
        vantage_of=lambda key: (1.0, 2.0, 3.0))
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    import types, sys
    mod = types.ModuleType("FakeSys.D"); mod.Initialize = lambda: (
        App.g_kSetManager.AddSet(SetClass_Create(), "D"))
    sys.modules["FakeSys.D"] = mod
    warp.WarpSequence_Create(player, "FakeSys.D", placement="Player Start").Play()
    # Align duration is derived from the turn angle / max angular velocity,
    # clamped to [_T_ALIGN_MIN, _T_ALIGN_MAX].
    assert warp._T_ALIGN_MIN <= started.get("align") <= warp._T_ALIGN_MAX
    assert started.get("transit") > 0.0
    # Both the source and destination vantages are handed to the VFX so the sky
    # can travel src->dst and arrive (destination nebula envelops on exit).
    assert started.get("vantage") == (1.0, 2.0, 3.0)
    assert started.get("dst_vantage") == (1.0, 2.0, 3.0)
    assert App.g_kSetManager.GetSet("Src") is src   # swap DEFERRED


def test_align_duration_scales_with_turn_angle():
    # A bigger turn (180 deg) takes longer than a small one, both at the ship's
    # max angular velocity, clamped to the band.
    class _IES:
        def GetMaxAngularVelocity(self): return 0.5
    class _Ship:
        def __init__(self, fwd):
            self._fwd = fwd
        def GetWorldRotation(self):
            class _R:
                def __init__(s, f): s._f = f
                def GetCol(s, i):
                    class _P: pass
                    p = _P(); p.x, p.y, p.z = s._f; return p
            return _R(self._fwd)
        def GetImpulseEngineSubsystem(self): return _IES()
    facing = warp._align_duration(_Ship((0.0, 1.0, 0.0)), (0.0, 1.0, 0.0))   # ~0 angle
    opposite = warp._align_duration(_Ship((0.0, 1.0, 0.0)), (0.0, -1.0, 0.0))  # 180 deg
    assert facing == warp._T_ALIGN_MIN          # tiny turn -> floor
    assert opposite > facing                    # 180 deg takes longer
    assert opposite <= warp._T_ALIGN_MAX


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


def test_burst_waits_for_the_parts_to_reach_their_warp_pose(monkeypatch):
    """The ship turns at its own rate (t_align unchanged), then HOLDS aligned
    until its articulated parts have reached the warp pose, then bursts. A rig
    slower than any turn (9 s > _T_ALIGN_MAX) always needs a hold."""
    import pytest
    from engine.appc import articulation
    from engine.core.loop import TICK_DELTA
    monkeypatch.setattr(articulation, "time_to_reach",
                        lambda ship, state: 9.0 if state == "warp" else 0.0)
    started = {}
    warp.configure_warp_vfx(
        enabled=lambda: True,
        start=lambda heading, t_align, t_transit, vantage=None,
            dst_vantage=None, t_hold=0.0:
            started.update(align=t_align, hold=t_hold, heading=heading),
        stop=lambda: None,
        vantage_of=lambda key: (1.0, 2.0, 3.0))
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src3")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    import types, sys
    mod = types.ModuleType("FakeSys.D3"); mod.Initialize = lambda: (
        App.g_kSetManager.AddSet(SetClass_Create(), "D3"))
    sys.modules["FakeSys.D3"] = mod
    seq = warp.WarpSequence_Create(player, "FakeSys.D3", placement="Player Start")
    seq.Play()
    # The turn is the ship's own: unchanged by the rig.
    assert started["align"] == warp._align_duration(player, started["heading"])
    burst = 9.0 + TICK_DELTA
    assert started["align"] + started["hold"] == pytest.approx(burst)
    departs = [d for (a, d) in _scheduled(seq) if isinstance(a, warp._WarpDepartAction)]
    assert departs == [pytest.approx(burst)]


def test_no_rig_means_no_hold(monkeypatch):
    from engine.appc import articulation
    monkeypatch.setattr(articulation, "time_to_reach", lambda ship, state: 0.0)
    started = {}
    warp.configure_warp_vfx(
        enabled=lambda: True,
        start=lambda heading, t_align, t_transit, vantage=None,
            dst_vantage=None, t_hold=0.0: started.update(align=t_align, hold=t_hold),
        stop=lambda: None,
        vantage_of=lambda key: (1.0, 2.0, 3.0))
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src4")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    import types, sys
    mod = types.ModuleType("FakeSys.D4"); mod.Initialize = lambda: (
        App.g_kSetManager.AddSet(SetClass_Create(), "D4"))
    sys.modules["FakeSys.D4"] = mod
    seq = warp.WarpSequence_Create(player, "FakeSys.D4", placement="Player Start")
    seq.Play()
    assert started["hold"] == 0.0
    departs = [d for (a, d) in _scheduled(seq) if isinstance(a, warp._WarpDepartAction)]
    assert departs == [started["align"]]


def _scheduled(seq):
    """(action, delay) for every step the sequence was built with."""
    return [(s.action, s.delay) for s in seq._steps]
