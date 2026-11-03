"""The per-test reset must put Felix's Tactical order state back.

Bridge.TacticalMenuHandlers keeps the player's Tactical orders in module
globals (g_iOrderState, g_iTacticState, g_iManeuverState, ...), and SDK
modules stay in sys.modules for the whole session. A mission that gave Felix
an order (E1M2's tactical tutorial, a free-roam fight) or a test that sets
one by hand (test_warp_clears_target_on_arrival, test_optimized_fire_script_
identity) left it set, so the next scene's first player target change ran
UpdateOrders and installed an attack AI on the player: an extra ET_AI_DONE
at tick 57 of the k1_ops_tpf1 golden (tick 180 at tpf 6). This plants that
state by hand -- no mission booted -- and shows the reset clears it.
"""
from tests.conftest import _reset_leakable_engine_globals


def test_the_reset_clears_felixs_leaked_orders():
    import Bridge.TacticalMenuHandlers as TMH
    TMH.g_iOrderState = 0               # OrderDestroy
    TMH.g_iTacticState = 3
    TMH.g_iManeuverState = 2
    TMH.g_iAutoTargetChange = 4
    TMH.g_bIgnoreNextAIDone = 1
    TMH.g_fLastWarnTime = 99.0
    TMH.g_lPlayerFireAIs.append(7)
    TMH.g_idCurrentAI = 7
    _reset_leakable_engine_globals()
    assert TMH.g_iOrderState == -1
    assert TMH.GetHighLevelOrder() is None
    assert TMH.g_iTacticState == 0
    assert TMH.g_iManeuverState == 0
    assert TMH.g_iAutoTargetChange == 0
    assert TMH.g_bIgnoreNextAIDone == 0
    assert TMH.g_fLastWarnTime == 0
    assert TMH.g_lPlayerFireAIs == []
    assert TMH.g_idCurrentAI is None
