"""The end of a Quick Battle fight, through the music, run to completion headless.

tests/helpers/headless_frames.Frames drives what the live host drives each
frame (the GameLoop tick, ship_death.advance, the music pump), so a destroyed
ship finishes dying and leaves the set and its music path can be tested.

Measured on the original (stbc-oracle music probe, native Windows, real time):
* enemy destroyed: EnemyBlewUp at the kill; the combat track then ends on its
  fade grid (or by itself) and DynamicMusic cues a new one; Starting Ambient
  once the enemy is gone (5.1 s and 12.6 s after the kill in two runs).
* player destroyed: PlayerBlewUp at the death; a new combat track; Starting
  Ambient (6.3 to 13.3 s after); the Lose fanfare 1 s after ShipDestroyed."""
import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader
from tests.helpers.headless_frames import Frames


def _fight(monkeypatch):
    import App, DynamicMusic
    import QuickBattle.QuickBattle as QB
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.loader.load_quickbattle()
    log = []
    real_done = DynamicMusic.MusicDone

    def done(pObject, pEvent):
        log.append(("MusicDone", App.g_kUtopiaModule.GetGameTime(), pEvent.GetCString()))
        return real_done(pObject, pEvent)
    monkeypatch.setattr(DynamicMusic, "MusicDone", done)
    for fn in ("SwitchMusic", "PlayFanfare"):
        orig = getattr(DynamicMusic, fn)

        def w(*a, _o=orig, _n=fn):
            log.append((_n, App.g_kUtopiaModule.GetGameTime(), a[0]))
            return _o(*a)
        monkeypatch.setattr(DynamicMusic, fn, w)
    QB.g_kEnemyList = [("Sovereign", "Sovereign", "msg", "QuickBattle.QuickBattleAI", "Enemy", 1.0)]
    controller.loader.start_quickbattle()
    App.g_kTimerManager.tick(3.0)
    hl._fire_pending_preload_done()
    frames = Frames(lengths={".mp3": 30.04})
    player = App.Game_GetCurrentPlayer()
    enemy = [App.ShipClass_Cast(o) for o in player.GetContainingSet().GetClassObjectList(App.CT_SHIP)
             if App.ShipClass_Cast(o).GetName() != player.GetName()][0]
    p = player.GetWorldLocation()
    enemy.SetTranslateXYZ(p.x, p.y + 100.0, p.z)
    frames.run(25.0)
    assert DynamicMusic.pStateMachine.GetMusicState().startswith("Combat")
    return App, DynamicMusic, frames, player, enemy, log


def _kill(App, ship):
    ship.DamageSystem(ship.GetHull(), ship.GetHull().GetCondition() + 10.0)
    return App.g_kUtopiaModule.GetGameTime()


def test_an_enemy_kill_cues_a_new_track_then_the_ambient(monkeypatch):
    App, DM, frames, player, enemy, log = _fight(monkeypatch)
    playing = DM.sCurrentMusicType
    t_kill = _kill(App, enemy)
    frames.run(40.0)
    assert ("PlayFanfare", "EnemyBlewUp") in [(n, a) for n, _t, a in log]
    assert enemy.IsDead()
    ambient = [t for n, t, a in log if n == "SwitchMusic" and a == "Starting Ambient"]
    assert ambient and 0.0 < ambient[0] - t_kill < 20.0
    assert DM.sCurrentMusicType == "Starting Ambient"
    # The fanfare ends the playing combat track on its fade grid, long before
    # its own end, and DynamicMusic hears it (ET_MUSIC_DONE) before the switch
    # to ambient: the original cues a new track of the state here.
    ends = [t for n, t, a in log if n == "MusicDone" and t_kill < t < ambient[0]]
    assert ends and ends[0] - t_kill <= 4.0 + 1e-6
    assert playing != "Starting Ambient"


def test_a_player_death_plays_the_lose_fanfare(monkeypatch):
    App, DM, frames, player, enemy, log = _fight(monkeypatch)
    t_kill = _kill(App, player)
    frames.run(40.0)
    names = [(n, a) for n, _t, a in log]
    assert ("PlayFanfare", "PlayerBlewUp") in names
    assert ("PlayFanfare", "Lose") in names
    ambient = [t for n, t, a in log if n == "SwitchMusic" and a == "Starting Ambient"]
    lose = [t for n, t, a in log if n == "PlayFanfare" and a == "Lose"]
    assert ambient and lose and 0.0 < ambient[0] - t_kill < 20.0
