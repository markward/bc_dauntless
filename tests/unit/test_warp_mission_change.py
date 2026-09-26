# tests/unit/test_warp_mission_change.py
"""The change runs at the after-during point of the tunnel; direct loads route
through it; a load that names the episode already current is a no-op (E5M4:
MissionWin -> LoadEpisode(Episode6), then the warp names Episode6 too)."""
import App
from engine.appc import warp
from engine.appc.actions import TGAction
from engine.appc.sets import SetClass_Create
from engine.core import mission_change
from engine.core.game import Game, _set_current_game
from tests.helpers.mission_change_fixtures import (
    log, _install, _world, _forget_world, warp_missionlib)


class _Rec(TGAction):
    def __init__(self, tag, fn=None):
        super().__init__(); self.tag = tag; self._fn = fn
    def _do_play(self):
        log.append(self.tag)
        if self._fn is not None:
            self._fn()


def _queues(**kw):
    q = {k: [] for k in ("before", "before_during", "during", "after_during", "after")}
    for k, acts in kw.items():
        q[k] = [(a, 0.0) for a in acts]
    return q


def _advance_game_time(seconds, step=1.0 / 60.0):
    for _ in range(int(round(seconds / step))):
        App.g_kTimerManager.tick(step)


def setup_function(_):
    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)


def teardown_function(_):
    warp.configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)
    App.g_kSetManager._sets.clear()
    _forget_world()


def _in_set(name, ship):
    s = App.g_kSetManager.GetSet(name)
    return s is not None and s.GetObject(ship.GetName()) is ship


def _player_warp(monkeypatch, player, dest_set, queues, **names):
    """A flythrough warp of the player from region "Src" to `dest_set`, which
    only the next mission creates. Returns (seq, t_align + t_transit)."""
    MissionLib = warp_missionlib()
    monkeypatch.setattr(MissionLib, "g_idMasterSequenceObj", None)
    warp.configure_warp_vfx(
        enabled=lambda: True, start=lambda *a, **k: None, stop=lambda: None,
        vantage_of=lambda key: None)
    App.WarpSequence_GetWarpSet().RemoveObjectFromSet(player.GetName())
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    src.AddObjectToSet(player, player.GetName())
    seq = warp.WarpSequence_Create(player, "Systems.Fake." + dest_set, 0.0,
                                   None, queues=queues, **names)
    return seq, warp._T_ALIGN_MIN + warp._T_BASE


def _mission_creating(set_name, tag="New.Initialize"):
    def _init(m):
        log.append(tag)
        App.g_kSetManager.AddSet(SetClass_Create(), set_name)
    return _init


def test_the_warp_changes_mission_after_the_during_queue(monkeypatch):
    game, player, _ = _world()
    _install("_t.Old", Terminate=lambda m: log.append("Old.Terminate"))
    _install("_t.New", Initialize=_mission_creating("QNew"))
    seq, total = _player_warp(monkeypatch, player, "QNew",
                              _queues(during=[_Rec("D")]), mission="_t.New")
    seq.Play()
    _advance_game_time(total + 1.0)
    assert log == ["D", "Old.Terminate", "New.Initialize"]
    assert _in_set("QNew", player)
    assert App.g_kSetManager.GetSet("Beol4") is None
    assert game.GetCurrentEpisode().GetCurrentMission()._module_name == "_t.New"


def test_load_episode_while_a_mission_runs_is_a_change():
    game, player, _ = _world()
    _install("_t.Old", Terminate=lambda m: log.append("Old.Terminate"))
    _install("_t.EpNew", Initialize=lambda e: log.append("EpNew.Initialize"))
    game.LoadEpisode("_t.EpNew")
    assert log == ["Old.Terminate", "EpNew.Initialize"]
    assert App.g_kSetManager.GetSet("Beol4") is None
    assert game.GetCurrentEpisode()._module_name == "_t.EpNew"
    assert game.GetPlayer() is player


def test_load_mission_while_a_mission_runs_is_a_change():
    game, _, _ = _world()
    ep = game.GetCurrentEpisode()
    _install("_t.Old", Terminate=lambda m: log.append("Old.Terminate"))
    _install("_t.New", Initialize=lambda m: log.append("New.Initialize"))
    ep.LoadMission("_t.New")
    assert log == ["Old.Terminate", "New.Initialize"]
    assert App.g_kSetManager.GetSet("Beol4") is None
    assert ep.GetCurrentMission()._module_name == "_t.New"


def test_load_episode_at_boot_is_a_raw_load():
    log.clear()
    game = Game(); _set_current_game(game)
    _install("_t.Old", Terminate=lambda m: log.append("Old.Terminate"))
    _install("_t.New", Initialize=lambda m: log.append("New.Initialize"))
    def _ep_init(e):
        log.append("EpNew.Initialize")
        e.LoadMission("_t.New")
    _install("_t.EpNew", Initialize=_ep_init)
    game.LoadEpisode("_t.EpNew")
    assert log == ["EpNew.Initialize", "New.Initialize"]
    assert game.GetCurrentEpisode().GetCurrentMission()._module_name == "_t.New"


def test_a_direct_load_then_the_warp_naming_the_same_episode_loads_once(monkeypatch):
    game, player, _ = _world()
    _install("_t.Old", Terminate=lambda m: log.append("Old.Terminate"))
    _install("_t.New", Initialize=_mission_creating("QNew"))
    def _ep_init(e):
        log.append("EpNew.Initialize")
        e.LoadMission("_t.New")
    _install("_t.EpNew", Initialize=_ep_init)
    win = _Rec("Win", fn=lambda: game.LoadEpisode("_t.EpNew"))
    seq, total = _player_warp(monkeypatch, player, "QNew",
                              _queues(before_during=[win]), episode="_t.EpNew")
    seq.Play()
    _advance_game_time(total + 1.0)
    assert log.count("EpNew.Initialize") == 1
    assert log.count("New.Initialize") == 1
    assert _in_set("QNew", player)
    assert not mission_change.in_progress()


def test_host_on_changed_names_the_new_mission_and_resyncs_the_view():
    """engine.host_loop._after_mission_change: session name, every CEF panel
    re-pushed, camera snapped -- and NOT the post-load hook, whose handlers the
    carry-over kept (re-running it would register them twice)."""
    from types import SimpleNamespace
    from engine import host_loop
    game, _, _ = _world()
    game.GetCurrentEpisode().GetCurrentMission()._module_name = "_t.New"
    calls = []
    controller = SimpleNamespace(
        session=SimpleNamespace(mission_name="_t.Old"),
        panel_registry=SimpleNamespace(
            invalidate_all=lambda: calls.append("invalidate")),
        post_load_hook=lambda: calls.append("post_load"))
    host_loop._after_mission_change(controller,
                                    snap_scene=lambda: calls.append("snap"))
    assert controller.session.mission_name == "_t.New"
    assert calls == ["invalidate", "snap"]
