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


def _fight(monkeypatch, lengths=None):
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
    frames = Frames(lengths=lengths or {".mp3": 30.04})
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


def test_after_a_loss_the_music_stays_ambient(monkeypatch):
    """Q9/Q4 on the original: after the Lose fanfare, Starting Ambient for the
    60 s (Q9) and 555 s (Q4) the runs went on; never combat again.
    EndSimulation deletes every ship but the player (SetDeleteMe), so the
    recreated player has no enemy in range."""
    App, DM, frames, player, enemy, log = _fight(monkeypatch)
    _kill(App, player)
    frames.run(20.0)
    lose = [t for n, t, a in log if n == "PlayFanfare" and a == "Lose"]
    assert lose
    frames.run(60.0)
    # The switch to the ambient comes with the battle's end (in Dauntless the
    # dead hull stays in the set until EndSimulation clears it, so one tick
    # after Lose rather than 1 s before it); nothing but the ambient after.
    assert set(a for n, t, a in log if n == "SwitchMusic" and t > lose[0]) <= {"Starting Ambient"}
    assert DM.sCurrentMusicType == "Starting Ambient"
    assert enemy.GetContainingSet() is None


def test_a_won_battle_plays_the_win_cleanly(monkeypatch):
    """The user heard another track start just before the Win fanfare, or play
    over it. EnemyBlewUp (Transition 13, 11.47 s) plays at the kill; Quick
    Battle's Win (engine/quickbattle/battle_end.py, 1 s after ShipDestroyed)
    comes 7-15 s later depending on how the ship dies.
    * Every track DynamicMusic asks for starts when asked (the original's next
      combat track started 3.1 s into EnemyBlewUp): holding one until the
      fanfare ended started a combat track just before Win.
    * When Win starts, EnemyBlewUp has ended or fades out within 0.5 s, so the
      two fanfares never play on top of each other."""
    App, DM, frames, player, enemy, log = _fight(
        monkeypatch, lengths={".mp3": 30.04, "Transition 13.mp3": 11.47})
    import QuickBattle.QuickBattle as QB
    from engine.quickbattle import battle_end
    battle_end.install(QB)
    battle_end.begin(QB, None)
    starts, asked = [], []
    real_factory = frames.player._factory

    def factory(path, looping=True):
        s = real_factory(path, looping)
        starts.append((frames.t, str(path), s))
        return s
    frames.player._factory = factory
    real_play = frames.player.play

    def play(path, *a, **k):
        asked.append((frames.t, str(path)))
        return real_play(path, *a, **k)
    frames.player.play = play
    stopped_at = {}
    real_frame = frames.frame

    def frame():
        real_frame()
        for t, p, s in starts:
            if s.stopped and id(s) not in stopped_at:
                stopped_at[id(s)] = frames.t
    frames.frame = frame
    _kill(App, enemy)
    frames.run(40.0)
    blew = [(t, s) for t, p, s in starts if p.endswith("Transition 13.mp3")]
    win = [t for t, p, _s in starts if p.endswith("Success-12.mp3")]
    assert blew and win, starts
    (t_blew, blew_s), t_win = blew[0], win[0]
    # No track start is held back: each starts in the frame it is asked for.
    for t, p in asked:
        assert any(abs(ts - t) < 1e-6 and ps == p for ts, ps, _s in starts), (t, p, starts)
    # The two fanfares never overlap for more than the 0.5 s hand-over.
    blew_gone = stopped_at.get(id(blew_s), t_blew + 11.47)
    assert blew_gone <= t_win + 0.5 + 2.0 / 60.0, (t_blew, t_win, blew_gone)
