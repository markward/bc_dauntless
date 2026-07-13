"""Host wiring for warp state: the per-frame sync must run BEFORE collisions
(a dewarp that completes this frame is collidable this frame), and a mission
swap must not strand a mid-warp ship as permanently non-collidable."""
import inspect

import App
import pytest
from engine.appc import warp_state
from engine.appc.ships import ShipClass
from engine.appc.subsystems import WarpEngineSubsystem


@pytest.fixture(autouse=True)
def _isolate():
    App.g_kSetManager._sets.clear()
    warp_state.reset()
    yield
    App.g_kSetManager._sets.clear()
    warp_state.reset()


def test_warp_state_is_ticked_before_collisions_in_the_host_loop():
    import engine.host_loop as hl
    src = inspect.getsource(hl)
    i_sync = src.index("warp_state.tick_warp_states")
    i_coll = src.index("collisions.tick_collisions")
    assert i_sync < i_coll, (
        "warp state must be advanced before collision resolution, or a ship "
        "that leaves warp this frame stays non-collidable for one extra frame")
    assert "warp_state.sync_flythrough" in src


def test_mission_swap_clears_a_mid_warp_ship():
    # C-2: the design's "Leak safety" section requires that a mission swap
    # mid-warp leaves the ship at WES_NOT_WARPING. warp_state.reset() only
    # drops the registration WITHOUT touching the ship's own warp state —
    # it survived only by the coincidence that reset_sdk_globals() also
    # clears App.g_kSetManager._sets, making the ship (usually) unreachable.
    # Any path that keeps a reference to the ship across a swap (as this
    # test itself does) re-opens the leak. Drive the REAL swap teardown
    # (HostController._drain_pending_swap) and assert on the ACTUAL mid-warp
    # ship, not a freshly constructed stand-in.
    s = ShipClass()
    s.SetWarpEngineSubsystem(WarpEngineSubsystem("Warp Engines"))
    warp_state.begin_flythrough(s)
    warp_state.set_state(s, WarpEngineSubsystem.WES_WARPING)

    import engine.host_loop as hl
    assert "warp_state.end_flythrough()" in inspect.getsource(hl)

    class _StubLoader:
        def load(self, name):
            return None

    hc = hl.HostController()
    hc.loader = _StubLoader()
    hc.pending_swap = "SomeMission"
    hc._drain_pending_swap()

    assert warp_state.get_state(s) == WarpEngineSubsystem.WES_NOT_WARPING
    assert warp_state.flythrough_ship() is None
    # A fresh ship in the new mission is collidable.
    from engine.appc.collisions import _collisions_enabled
    fresh = ShipClass()
    fresh.SetWarpEngineSubsystem(WarpEngineSubsystem("Warp Engines"))
    assert _collisions_enabled(fresh) is True


def test_sync_flythrough_releases_the_ship_when_the_animator_stops():
    from engine.appc.collisions import _collisions_enabled
    s = ShipClass()
    s.SetWarpEngineSubsystem(WarpEngineSubsystem("Warp Engines"))
    warp_state.begin_flythrough(s)
    warp_state.set_state(s, WarpEngineSubsystem.WES_DEWARP_ENDING)
    assert _collisions_enabled(s) is False

    warp_state.sync_flythrough(False)       # what the host loop calls each frame
    assert _collisions_enabled(s) is True
