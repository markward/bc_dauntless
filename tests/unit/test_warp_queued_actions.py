"""The button's queues play at their points of the tunnel; the swap waits for
them and for the mission's master dialogue sequence (SDK WaitForQueued)."""
import sys
import types

import App
from engine.appc import warp
from engine.appc.actions import TGAction
from engine.appc.sets import SetClass_Create
from tests.helpers.mission_change_fixtures import warp_missionlib

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


def _flythrough_warp(name, queues, monkeypatch, is_player=False,
                     start=lambda *a, **k: None):
    """A flythrough warp of a ship from set Src to a fake module whose
    Initialize registers set `name`; the ship is Game_GetCurrentPlayer() iff
    `is_player`. Returns (ship, seq, t_align + t_transit)."""
    warp.configure_warp_vfx(
        enabled=lambda: True, start=start, stop=lambda: None,
        vantage_of=lambda key: None)
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    ship = App.ShipClass_Create(); ship.SetName("player")
    src.AddObjectToSet(ship, "player")
    monkeypatch.setattr(App, "Game_GetCurrentPlayer",
                        lambda: ship if is_player else None)
    mod = types.ModuleType("FakeSys." + name)
    mod.Initialize = lambda: App.g_kSetManager.AddSet(SetClass_Create(), name)
    monkeypatch.setitem(sys.modules, "FakeSys." + name, mod)
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
    assert not _in_set("QHold", ship)            # the exit flash plays first
    _advance_game_time(0.1 * warp._T_BASE)
    assert _in_set("QHold", ship)


def test_transit_waits_for_the_mission_master_sequence(monkeypatch):
    """SDK WarpSequence.WaitForQueued (player only): while
    MissionLib.g_idMasterSequenceObj names a playing TGSequence, the swap waits
    for its completion."""
    MissionLib = warp_missionlib()
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
    assert not _in_set("QMaster", ship)            # the exit flash plays first
    _advance_game_time(0.1 * warp._T_BASE)
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


def test_unheld_swap_lands_at_transit_end_under_the_exit_flash(monkeypatch):
    """Nothing to wait for: the hold releases at 90 % of transit and the swap
    follows 0.1 * t_transit later -- at t_align + t_transit, never earlier,
    with the exit flash peaking to mask it. WarpVFX puts e == t_align +
    t_transit itself in the "exit" phase (flash 0), so the flash is read on
    the last 60 Hz frame before the swap -- the frame the swap replaces."""
    MissionLib = warp_missionlib()
    from engine import warp_vfx
    monkeypatch.setattr(MissionLib, "g_idMasterSequenceObj", None)
    vfx = warp_vfx.get()
    vfx.stop()
    seen = {}

    def _start(heading, t_align, t_transit, vantage=None, dst_vantage=None):
        vfx.start(heading, t_align, t_transit,
                  App.g_kUtopiaModule.GetGameTime(), vantage, dst_vantage)

    def _realize(pSet):
        now = App.g_kUtopiaModule.GetGameTime()
        vfx.tick(now - 1.0 / 60.0)
        seen.update(t=now, flash=vfx.flash_intensity())
        vfx.tick(now)

    ship, seq, total = _flythrough_warp("QFlash", _queues(), monkeypatch,
                                        is_player=True, start=_start)
    warp.configure_warp_hooks(realize=_realize, teardown=None)
    try:
        t0 = App.g_kUtopiaModule.GetGameTime()
        seq.Play()
        _advance_game_time(total + 1.0)
        assert "t" in seen
        assert seen["t"] - t0 >= total - 1e-6
        assert seen["flash"] > 0.9
    finally:
        vfx.stop()


def test_npc_flythrough_does_not_hold_the_shared_vfx(monkeypatch):
    """The WarpVFX singleton is the player's tunnel; an NPC warp through the
    flythrough path must not freeze it."""
    from engine import warp_vfx
    warp_vfx.get().stop()
    ship, seq, total = _flythrough_warp("QNpc", _queues(), monkeypatch,
                                        is_player=False)
    seq.Play()
    _advance_game_time(warp._T_ALIGN_MIN + 1.0)     # past departure
    assert _in_set(warp._WARP_TRANSIT_SET_NAME, ship)
    assert warp_vfx.get().is_held() is False


def test_fallback_waits_for_the_mission_master_sequence(monkeypatch):
    """No flythrough: the swap still waits on SDK WaitForQueued (player only)
    for MissionLib's master sequence."""
    MissionLib = warp_missionlib()
    master = App.TGSequence_Create()
    dialogue = _Long("DIALOGUE")
    master.AddAction(dialogue)
    master.Play()
    monkeypatch.setattr(MissionLib, "g_idMasterSequenceObj", master.GetObjID())
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    ship = App.ShipClass_Create(); ship.SetName("player")
    src.AddObjectToSet(ship, "player")
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: ship)
    mod = types.ModuleType("FakeSys.QFall")
    mod.Initialize = lambda: App.g_kSetManager.AddSet(SetClass_Create(), "QFall")
    monkeypatch.setitem(sys.modules, "FakeSys.QFall", mod)
    seq = warp.WarpSequence_Create(ship, "FakeSys.QFall", 0.0, None,
                                   queues=_queues())
    seq.Play()
    _advance_game_time(1.0)
    assert _in_set("Src", ship)
    assert not _in_set("QFall", ship)
    dialogue.Completed()
    _advance_game_time(1.0 / 60.0)
    assert _in_set("QFall", ship)


def test_unheld_release_is_continuous(monkeypatch):
    """An ordinary player warp (nothing queued) passes through the hold and
    release without a visible seam: between consecutive 60 Hz ticks the
    streak and the travel progress change by no more than one tick's normal
    change -- no freeze-then-jump at the release."""
    MissionLib = warp_missionlib()
    from engine import warp_vfx
    monkeypatch.setattr(MissionLib, "g_idMasterSequenceObj", None)
    vfx = warp_vfx.get()
    vfx.stop()

    def _start(heading, t_align, t_transit, vantage=None, dst_vantage=None):
        # Unit src->dst vantages: sky_vantage()[0] IS the travel progress.
        vfx.start(heading, t_align, t_transit,
                  App.g_kUtopiaModule.GetGameTime(),
                  (0.0, 0.0, 0.0), (1.0, 0.0, 0.0))

    ship, seq, total = _flythrough_warp("QSeam", _queues(), monkeypatch,
                                        is_player=True, start=_start)
    step = 1.0 / 60.0
    tick_progress = step / warp._T_BASE
    samples = []
    try:
        seq.Play()
        for _ in range(int(round((total + 0.5) / step))):
            App.g_kTimerManager.tick(step)
            vfx.tick(App.g_kUtopiaModule.GetGameTime())
            samples.append((vfx.phase(), vfx.streak_intensity(),
                            vfx.sky_vantage(0.0)[0]))
    finally:
        vfx.stop()
    transit = [(a, b) for a, b in zip(samples, samples[1:])
               if a[0] == "transit" and b[0] == "transit"]
    assert len(transit) > 100
    for (_, s0, p0), (_, s1, p1) in transit:
        assert 0.0 < p1 - p0 <= 1.5 * tick_progress + 1e-9, (p0, p1)
        assert abs(s1 - s0) <= 0.05, (s0, s1)


def test_release_lets_go_only_of_a_hold_this_warp_took(monkeypatch):
    """_TransitReleaseAction releases iff this sequence's departure took the
    hold -- not by re-asking who the player is at release time."""
    from engine import warp_vfx
    vfx = warp_vfx.get()
    vfx.stop()
    ship, seq, total = _flythrough_warp("QRel", _queues(), monkeypatch,
                                        is_player=False)
    vfx.hold()                     # someone else's hold (e.g. the player's)
    seq.Play()
    try:
        _advance_game_time(warp._T_ALIGN_MIN + 0.5)     # departed, as an NPC
        # The player changes to this ship mid-transit: still not our hold.
        monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: ship)
        _advance_game_time(total)
        assert _in_set("QRel", ship)                    # release ran
        assert vfx.is_held() is True
    finally:
        vfx.stop()
