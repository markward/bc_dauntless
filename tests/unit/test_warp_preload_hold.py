"""The warp tunnel waits for the destination preload: the hold completes no
earlier than today's floor, then polls the preload in real time until it is
ready or PRELOAD_CAP_S has passed. Only the player's warp begins, waits for
and ends a preload; an NPC's warp and a host with no hooks behave as before."""
import sys
import types

import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create
from tests.helpers.warp_sdk_modules import warp_missionlib

_STEP = 1.0 / 60.0


def _advance(seconds, step=_STEP):
    """Advance game AND real time together, in 60 Hz ticks."""
    for _ in range(int(round(seconds / step))):
        App.g_kTimerManager.tick(step)
        App.g_kRealtimeTimerManager.tick(step)


class _Hooks:
    """Recording preload hooks."""

    def __init__(self, ready=False, pending=("planet Geki", "ship Kessok")):
        self.is_ready = ready
        self._pending = list(pending)
        self.calls = []

    def begin(self, name):
        self.calls.append(("begin", name))

    def ready(self):
        return self.is_ready

    def replan(self):
        self.calls.append(("replan",))

    def end(self):
        self.calls.append(("end",))

    def pending(self):
        return list(self._pending)

    def install(self):
        warp.configure_warp_hooks(
            preload_begin=self.begin, preload_ready=self.ready,
            preload_replan=self.replan, preload_end=self.end,
            preload_pending=self.pending)

    def count(self, kind):
        return sum(1 for c in self.calls if c[0] == kind)


def setup_function(_):
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)


def teardown_function(_):
    from engine import warp_vfx
    warp_vfx.get().stop()
    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)
    App.g_kSetManager._sets.clear()


def _flythrough_warp(name, monkeypatch, is_player=True):
    """A flythrough warp of a ship from set Src to a fake module whose
    Initialize registers set `name`. Returns (ship, seq, hold, floor) where
    floor is the hold's nominal completion, t_align + 0.9 * t_transit."""
    monkeypatch.setattr(warp_missionlib(), "g_idMasterSequenceObj", None)
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
    monkeypatch.setitem(sys.modules, "FakeSys." + name, mod)
    seq = warp.WarpSequence_Create(ship, "FakeSys." + name, 0.0, None)
    hold = next(s.action for s in seq._steps
                if isinstance(s.action, warp._HoldUntilAction))
    floor = warp._T_ALIGN_MIN + 0.9 * warp._T_BASE
    return ship, seq, hold, floor


def _track_completion(hold):
    """Record the game time at which `hold` completes."""
    done = []
    orig = hold.Completed

    def _completed():
        done.append(App.g_kUtopiaModule.GetGameTime())
        orig()
    hold.Completed = _completed
    return done


def test_hold_completes_at_floor_when_ready(monkeypatch):
    hooks = _Hooks(ready=True); hooks.install()
    _ship, seq, hold, floor = _flythrough_warp("PHReady", monkeypatch)
    done = _track_completion(hold)
    seq.Play()
    _advance(floor - 0.1)
    assert done == []
    _advance(0.2)
    assert len(done) == 1


def test_hold_waits_past_floor_until_ready(monkeypatch):
    hooks = _Hooks(ready=False); hooks.install()
    _ship, seq, hold, floor = _flythrough_warp("PHWait", monkeypatch)
    done = _track_completion(hold)
    seq.Play()
    _advance(floor + 1.9)
    assert done == []                       # floor passed, preload not ready
    hooks.is_ready = True                   # ready at floor + 2 s
    _advance(0.1 + 2 * warp.PRELOAD_POLL_S)
    assert len(done) == 1


def test_hold_releases_at_cap_and_logs_late(monkeypatch, capsys):
    assert warp.PRELOAD_CAP_S == 30.0
    assert warp.PRELOAD_POLL_S == 0.05
    hooks = _Hooks(ready=False); hooks.install()
    _ship, seq, hold, floor = _flythrough_warp("PHCap", monkeypatch)
    done = _track_completion(hold)
    seq.Play()
    _advance(floor + warp.PRELOAD_CAP_S - 0.5)
    assert done == []
    _advance(1.0)
    assert len(done) == 1
    err = capsys.readouterr().err
    assert "[warp-preload] late: planet Geki, ship Kessok" in err


def test_npc_warp_never_waits(monkeypatch):
    hooks = _Hooks(ready=False); hooks.install()
    _ship, seq, hold, floor = _flythrough_warp("PHNpc", monkeypatch,
                                               is_player=False)
    done = _track_completion(hold)
    seq.Play()
    _advance(floor - 0.1)
    assert done == []
    _advance(0.2)
    assert len(done) == 1
    assert hooks.calls == []                # never begun, never ended


def test_no_hooks_behaves_as_today(monkeypatch):
    _ship, seq, hold, floor = _flythrough_warp("PHNone", monkeypatch)
    done = _track_completion(hold)
    seq.Play()
    _advance(floor - 0.1)
    assert done == []
    _advance(0.2)
    assert len(done) == 1


def test_abort_ends_the_preload(monkeypatch):
    polls = []
    orig_poll = warp._HoldUntilAction._poll

    def _counting_poll(self):
        polls.append(1)
        orig_poll(self)
    monkeypatch.setattr(warp._HoldUntilAction, "_poll", _counting_poll)
    hooks = _Hooks(ready=False); hooks.install()
    _ship, seq, hold, floor = _flythrough_warp("PHAbort", monkeypatch)
    done = _track_completion(hold)
    seq.Play()
    _advance(floor + 1.0)
    assert polls                            # it is waiting on the preload
    seq.Abort()
    assert hooks.count("end") == 1
    n = len(polls)
    _advance(warp.PRELOAD_CAP_S + 1.0)
    assert len(polls) == n                  # no poll after the abort
    assert done == []
    assert hooks.count("end") == 1


def test_completed_warp_ends_the_preload(monkeypatch):
    hooks = _Hooks(ready=True); hooks.install()
    _ship, seq, _hold, floor = _flythrough_warp("PHDone", monkeypatch)
    seq.Play()
    _advance(warp._T_ALIGN_MIN + warp._T_BASE + 10.0)
    assert not seq._playing
    assert hooks.count("end") == 1


def test_mission_change_replans(monkeypatch):
    from engine.core import mission_change
    order = []
    monkeypatch.setattr(mission_change, "change",
                        lambda **kw: order.append(("change", kw)))
    hooks = _Hooks()
    hooks.replan = lambda: order.append(("replan",))
    hooks.install()

    class _Seq:
        def GetDestinationMission(self):  return "Maelstrom.Episode2.E2M1"
        def GetDestinationEpisode(self):  return None

    warp._MissionChangePoint(_Seq()).Play()
    assert order == [("change", {"mission": "Maelstrom.Episode2.E2M1",
                                 "episode": None}),
                     ("replan",)]


def test_depart_begins_for_player_only(monkeypatch):
    hooks = _Hooks(ready=True); hooks.install()
    _ship, seq, _hold, _floor = _flythrough_warp("PHBegin", monkeypatch)
    seq.Play()
    _advance(warp._T_ALIGN_MIN - 0.1)
    assert hooks.calls == []                # not before the burst
    _advance(0.2)
    assert hooks.calls == [("begin", "PHBegin")]

    seq.Abort()
    App.g_kSetManager._sets.clear()
    npc_hooks = _Hooks(ready=True); npc_hooks.install()
    _ship, seq, _hold, _floor = _flythrough_warp("PHBeginNpc", monkeypatch,
                                                 is_player=False)
    seq.Play()
    _advance(warp._T_ALIGN_MIN + 1.0)
    assert npc_hooks.calls == []


def test_a_raising_ready_hook_fails_open_at_the_floor(monkeypatch):
    def _boom():
        raise RuntimeError("boom")
    hooks = _Hooks(); hooks.ready = _boom; hooks.install()
    _ship, seq, hold, floor = _flythrough_warp("PHBoom", monkeypatch)
    done = _track_completion(hold)
    seq.Play()
    _advance(floor + 0.1)
    assert len(done) == 1                   # never blocks the warp


def test_an_older_warp_never_ends_a_newer_warps_preload(monkeypatch):
    hooks = _Hooks(ready=True); hooks.install()
    _ship, first, _hold, _floor = _flythrough_warp("PHFirst", monkeypatch)
    first.Play()
    _advance(warp._T_ALIGN_MIN + 0.1)       # first warp began its preload
    App.g_kSetManager._sets.clear()
    _ship, second, _hold, _floor = _flythrough_warp("PHSecond", monkeypatch)
    second.Play()
    _advance(warp._T_ALIGN_MIN + 0.1)       # second warp began its own
    assert hooks.count("begin") == 2
    first.Abort()
    assert hooks.count("end") == 0          # the running preload is second's
    second.Abort()
    assert hooks.count("end") == 1


def test_a_raising_pending_hook_still_releases_at_the_cap(monkeypatch, capsys):
    def _boom():
        raise RuntimeError("boom")
    hooks = _Hooks(ready=False); hooks.pending = _boom; hooks.install()
    _ship, seq, hold, floor = _flythrough_warp("PHPendBoom", monkeypatch)
    done = _track_completion(hold)
    seq.Play()
    _advance(floor + warp.PRELOAD_CAP_S + 0.5)
    assert len(done) == 1
    assert "[warp-preload] late:" in capsys.readouterr().err


# -- F1: a stale preload never holds a warp it does not belong to -------------

def test_a_hold_whose_sequence_is_not_the_owner_completes_at_its_floor(
        monkeypatch):
    """A stale preload (left running by a mission swap) is not ready; this
    warp's own begin did not run, so it is not the owner -- it must not wait
    on someone else's preload."""
    def _no_begin(name):
        raise RuntimeError("begin failed")
    hooks = _Hooks(ready=False); hooks.begin = _no_begin; hooks.install()
    _ship, seq, hold, floor = _flythrough_warp("PHNotOwner", monkeypatch)
    done = _track_completion(hold)
    seq.Play()
    _advance(floor - 0.1)
    assert done == []
    assert warp._preload_owner is not seq
    _advance(0.2)
    assert len(done) == 1


def test_stop_ends_the_owned_preload(monkeypatch):
    hooks = _Hooks(ready=False); hooks.install()
    _ship, seq, hold, floor = _flythrough_warp("PHStop", monkeypatch)
    seq.Play()
    _advance(floor + 1.0)                   # owner, waiting on the preload
    assert warp._preload_owner is seq
    seq.Stop()
    assert hooks.count("end") == 1
    assert warp._preload_owner is None
    seq.Stop()                              # owner-gated: ends it once
    assert hooks.count("end") == 1


def test_stop_never_ends_a_newer_warps_preload(monkeypatch):
    hooks = _Hooks(ready=True); hooks.install()
    _ship, first, _hold, _floor = _flythrough_warp("PHStopA", monkeypatch)
    first.Play()
    _advance(warp._T_ALIGN_MIN + 0.1)
    App.g_kSetManager._sets.clear()
    _ship, second, _hold, _floor = _flythrough_warp("PHStopB", monkeypatch)
    second.Play()
    _advance(warp._T_ALIGN_MIN + 0.1)
    first.Stop()
    assert hooks.count("end") == 0
    second.Abort()


def test_reset_preload_state_clears_the_owner(monkeypatch):
    hooks = _Hooks(ready=False); hooks.install()
    _ship, seq, _hold, floor = _flythrough_warp("PHReset", monkeypatch)
    seq.Play()
    _advance(floor + 0.5)
    assert warp._preload_owner is seq
    warp.reset_preload_state()
    assert warp._preload_owner is None
    seq.Abort()                             # no longer the owner: no end
    assert hooks.count("end") == 0
