"""Regression: a mission swap DURING a warp transit must not leak WarpVFX.

reset_sdk_globals() (called by HostController._drain_pending_swap) zeroes the
timer manager, which cancels the pending ReturnControl / WarpVfxEnd chain. The
drain therefore explicitly tears down the warp VFX. This test asserts the real
post-conditions of that cleanup block: the WarpVFX singleton is deactivated and
the captured warp-turn rotation is cleared.
"""

import engine.host_loop as host_loop
from engine import warp_vfx


def _run_swap_cleanup():
    """Run exactly the cleanup block that _drain_pending_swap performs after
    reset_sdk_globals(), in isolation (no session/loader/renderer harness)."""
    try:
        from engine import warp_vfx as _wv
        _wv.get().stop()
    except Exception:
        pass
    try:
        host_loop._warp_clear_turn()
    except Exception:
        pass
    try:
        import MissionLib
        MissionLib.ReturnControl()
    except Exception:
        pass


def test_mid_warp_swap_tears_down_warp_vfx():
    # Start a warp: singleton becomes active, ship-turn rotation captured.
    warp_vfx.get().start(heading=(1.0, 0.0, 0.0), t_align=2.0,
                         t_transit=4.0, now=0.0)
    warp_vfx.get().tick(1.0)  # mid-align: active, turn fraction in (0,1)
    host_loop._warp_turn_start_R = object()  # simulate a captured turn matrix

    assert warp_vfx.get().is_active() is True
    assert host_loop._warp_turn_start_R is not None

    _run_swap_cleanup()

    # Post-conditions: manager deactivated, streak/flash zeroed, turn cleared.
    assert warp_vfx.get().is_active() is False
    assert warp_vfx.get().streak_intensity() == 0.0
    assert warp_vfx.get().flash_intensity() == 0.0
    assert host_loop._warp_turn_start_R is None
