"""The flythrough warp drives the ship's WarpEngineSubsystem FSM, so BC's own
GetWarpState() consumers (WarpSequence.py:638, HelmMenuHandlers.py:2465,
ConditionInRange.py:209) see a warping ship as warping."""
import sys
import types

import App
import pytest
from engine.appc import warp, warp_state
from engine.appc.sets import SetClass_Create
from engine.appc.subsystems import WarpEngineSubsystem

WES = WarpEngineSubsystem


@pytest.fixture(autouse=True)
def _isolate():
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)
    warp_state.reset()
    yield
    App.g_kSetManager._sets.clear()
    warp_state.reset()


def _player_in_set():
    src = SetClass_Create()
    App.g_kSetManager.AddSet(src, "Src")
    player = App.ShipClass_Create()
    player.SetName("player")
    player.SetWarpEngineSubsystem(WES("Warp Engines"))
    src.AddObjectToSet(player, "player")
    mod = types.ModuleType("FakeSys.D")
    mod.Initialize = lambda: App.g_kSetManager.AddSet(SetClass_Create(), "D")
    sys.modules["FakeSys.D"] = mod
    return player


def test_flythrough_begin_marks_the_ship_warp_initiated():
    warp.configure_warp_vfx(enabled=lambda: True,
                            start=lambda *a, **k: None, stop=lambda: None,
                            vantage_of=lambda key: (1.0, 2.0, 3.0))
    player = _player_in_set()
    warp.WarpSequence_Create(player, "FakeSys.D", placement="Player Start").Play()
    # Only the align-start action has fired (the rest are time-delayed).
    assert warp_state.get_state(player) == WES.WES_WARP_INITIATED
    assert warp_state.is_ship_warping(player) is True
    assert warp_state.flythrough_ship() is player


def test_depart_action_marks_the_ship_warping():
    player = _player_in_set()
    warp._WarpDepartAction(None, player)._do_play()
    assert warp_state.get_state(player) == WES.WES_WARPING


def test_arrive_action_marks_the_ship_dewarp_ending():
    # Arrival begins the exit-decel glide: still warping (still non-collidable)
    # until the animator finishes and _WarpVfxEndAction clears it. This
    # simulates the mid-flythrough condition under which _ArriveFinalizeAction
    # actually runs in the real sequence: the flythrough ship is already
    # registered (by _WarpVfxBeginAction, at align-start) by the time arrival
    # fires — the gate that keeps the hard-cut path at WES_NOT_WARPING
    # (test_hard_cut_path_never_marks_the_ship_warping) is
    # `flythrough_ship() is self._ship`.
    player = _player_in_set()
    warp_state.begin_flythrough(player)
    warp._ArriveFinalizeAction(None, player)._do_play()
    assert warp_state.get_state(player) == WES.WES_DEWARP_ENDING
    assert warp_state.is_ship_warping(player) is True


def test_vfx_end_action_clears_the_warp_state():
    player = _player_in_set()
    warp_state.begin_flythrough(player)
    warp_state.set_state(player, WES.WES_DEWARP_ENDING)
    warp._WarpVfxEndAction(player)._do_play()
    assert warp_state.get_state(player) == WES.WES_NOT_WARPING
    assert warp_state.flythrough_ship() is None


def test_hard_cut_path_never_marks_the_ship_warping():
    # Flythrough OFF: an instant set swap, no warp-speed flight, so the ship
    # must never read as warping.
    warp.configure_warp_vfx(enabled=lambda: False)
    player = _player_in_set()
    warp.WarpSequence_Create(player, "FakeSys.D", placement="Player Start").Play()
    assert warp_state.get_state(player) == WES.WES_NOT_WARPING
    assert warp_state.flythrough_ship() is None


def test_vfx_end_action_for_one_ship_does_not_release_a_second_in_flight_ship():
    # C-1 reproduced at the warp.py level: WarpSequence_Create takes the
    # flythrough branch for ANY ship (no player check), so an NPC's own
    # flythrough can be registered while the player's is still mid-flight.
    # _WarpVfxEndAction must release only the ship its own sequence belongs
    # to — not clobber (nor be blocked by) an unrelated ship still in transit.
    player = _player_in_set()
    npc = App.ShipClass_Create()
    npc.SetName("npc")
    npc.SetWarpEngineSubsystem(WES("Warp Engines"))

    warp_state.begin_flythrough(player)
    warp_state.set_state(player, WES.WES_WARP_INITIATED)
    warp_state.begin_flythrough(npc)
    warp_state.set_state(npc, WES.WES_WARPING)

    warp._WarpVfxEndAction(npc)._do_play()

    assert warp_state.get_state(npc) == WES.WES_NOT_WARPING
    assert warp_state.is_flythrough(npc) is False
    # The player's own flythrough must be untouched.
    assert warp_state.get_state(player) == WES.WES_WARP_INITIATED
    assert warp_state.is_flythrough(player) is True
