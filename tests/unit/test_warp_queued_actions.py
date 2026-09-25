"""The button's queues play at their points of the tunnel; the swap waits for
them and for the mission's master dialogue sequence (SDK WaitForQueued)."""
import sys
import types

import App
from engine.appc import warp
from engine.appc.actions import TGAction
from engine.appc.sets import SetClass_Create

log = []


class _Rec(TGAction):
    def __init__(self, tag):
        super().__init__(); self.tag = tag
    def _do_play(self):
        log.append(self.tag)


class _Long(_Rec):
    """Starts playing and does not complete until the test calls Completed()."""
    def Play(self):
        self._playing = True
        self._do_play()


def _queues(**kw):
    q = {k: [] for k in ("before", "before_during", "during", "after_during", "after")}
    for k, acts in kw.items():
        q[k] = [(a if isinstance(a, TGAction) else _Rec(a), 0.0) for a in acts]
    return q


def _advance_game_time(seconds, step=1.0 / 60.0):
    """Advance g_kTimerManager in 60 Hz ticks for `seconds` of game time
    (same helper as tests/unit/test_actions.py)."""
    for _ in range(int(round(seconds / step))):
        App.g_kTimerManager.tick(step)


def setup_function(_):
    log.clear()
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)


def teardown_function(_):
    warp.configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)
    App.g_kSetManager._sets.clear()


def _flythrough_warp(name, queues, monkeypatch, is_player=False):
    """A flythrough warp of a ship from set Src to a fake module whose
    Initialize registers set `name`; the ship is Game_GetCurrentPlayer() iff
    `is_player`. Returns (ship, seq, t_align + t_transit)."""
    warp.configure_warp_vfx(
        enabled=lambda: True, start=lambda *a, **k: None, stop=lambda: None,
        vantage_of=lambda key: None)
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    ship = App.ShipClass_Create(); ship.SetName("player")
    src.AddObjectToSet(ship, "player")
    monkeypatch.setattr(App, "Game_GetCurrentPlayer",
                        lambda: ship if is_player else None)
    mod = types.ModuleType("FakeSys." + name)
    mod.Initialize = lambda: App.g_kSetManager.AddSet(SetClass_Create(), name)
    sys.modules["FakeSys." + name] = mod
    seq = warp.WarpSequence_Create(ship, "FakeSys." + name, 0.0, None,
                                   queues=queues)
    # Unmapped vantages => T_BASE transit; identity rotation already faces the
    # default heading => the align floor.
    total = warp._T_ALIGN_MIN + warp._T_BASE
    return ship, seq, total


def _in_set(name, ship):
    s = App.g_kSetManager.GetSet(name)
    return s is not None and s.GetObject(ship.GetName()) is ship


def test_queues_play_in_bc_order_around_the_swap(monkeypatch):
    monkeypatch.setattr(warp, "ChangeRenderedSetAction_Create",
                        lambda m: _Rec("SWAP"))
    ship = App.ShipClass_Create(); ship.SetName("player")
    seq = warp.WarpSequence_Create(
        ship, "Systems.Vesuvi.Vesuvi4", 0.0, "Player Start",
        queues=_queues(before=["B"], before_during=["BD"], during=["D"],
                       after_during=["AD"], after=["A"]))
    tags = [type(s.action).__name__ if not isinstance(s.action, _Rec)
            else s.action.tag for s in seq._steps]
    # Structural: the swap is reachable only through the queue chain.
    i = tags.index
    assert i("B") < i("BD") < i("D") < i("AD") < i("SWAP") < i("A")


def test_flythrough_chain_order_and_dependencies(monkeypatch):
    """depart -> WaitForQueued (player) -> BD -> D -> AD -> _MissionChangePoint
    -> _HoldUntilAction -> _TransitReleaseAction -> swap, each step depending
    on the one before it; 'before' is a root and 'after' follows the helm
    re-enable."""
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: ship)
    monkeypatch.setattr(warp, "ChangeRenderedSetAction_Create",
                        lambda m: _Rec("SWAP"))
    warp.configure_warp_vfx(
        enabled=lambda: True, start=lambda *a, **k: None, stop=lambda: None,
        vantage_of=lambda key: None)
    ship = App.ShipClass_Create(); ship.SetName("player")
    seq = warp.WarpSequence_Create(
        ship, "Systems.Vesuvi.Vesuvi4", 0.0, "Player Start",
        queues=_queues(before=["B"], before_during=["BD"], during=["D"],
                       after_during=["AD"], after=["A"]))

    def name(a):
        if isinstance(a, _Rec):
            return a.tag
        if isinstance(a, App.TGScriptAction):
            return a._func_name
        return type(a).__name__

    by_name = {name(s.action): s for s in seq._steps}
    chain = ["_WarpDepartAction", "WaitForQueued", "BD", "D", "AD",
             "_MissionChangePoint", "_HoldUntilAction", "_TransitReleaseAction",
             "SWAP"]
    for prev, cur in zip(chain, chain[1:]):
        assert by_name[cur].dependency is by_name[prev].action, cur
    assert by_name["B"].dependency is None
    assert by_name["A"].dependency is by_name["_EnableHelmMenuAction"].action


def test_transit_holds_until_a_long_during_action_completes(monkeypatch):
    """A during-warp action that runs past t_transit delays the swap until it
    completes; the player is still in the "warp" set until then."""
    long_ = _Long("D")
    ship, seq, total = _flythrough_warp("QHold", _queues(during=[long_]),
                                        monkeypatch)
    seq.Play()
    _advance_game_time(total + 2.0)
    assert log == ["D"]                       # the during action started
    assert _in_set(warp._WARP_TRANSIT_SET_NAME, ship)
    assert not _in_set("QHold", ship)
    long_.Completed()
    _advance_game_time(1.0 / 60.0)
    assert _in_set("QHold", ship)


def test_transit_waits_for_the_mission_master_sequence(monkeypatch):
    """SDK WarpSequence.WaitForQueued (player only): while
    MissionLib.g_idMasterSequenceObj names a playing TGSequence, the swap waits
    for its completion."""
    import MissionLib
    master = App.TGSequence_Create()
    dialogue = _Long("DIALOGUE")
    master.AddAction(dialogue)
    master.Play()
    monkeypatch.setattr(MissionLib, "g_idMasterSequenceObj", master.GetObjID())
    ship, seq, total = _flythrough_warp("QMaster", _queues(), monkeypatch,
                                        is_player=True)
    seq.Play()
    _advance_game_time(total + 2.0)
    assert _in_set(warp._WARP_TRANSIT_SET_NAME, ship)
    assert not _in_set("QMaster", ship)
    dialogue.Completed()                      # master sequence finishes
    _advance_game_time(1.0 / 60.0)
    assert _in_set("QMaster", ship)


def test_no_hold_swaps_at_the_end_of_transit(monkeypatch):
    """Nothing queued, no master sequence: the swap lands at t_align +
    t_transit as before, not earlier."""
    ship, seq, total = _flythrough_warp("QPlain", _queues(), monkeypatch)
    seq.Play()
    _advance_game_time(total - 0.5)
    assert _in_set(warp._WARP_TRANSIT_SET_NAME, ship)
    _advance_game_time(1.0)
    assert _in_set("QPlain", ship)
