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


BLEW, WIN = "Transition 13.mp3", "Success-12.mp3"
BLEW_S, WIN_S = 11.47, 32.34


def _armed_kill(monkeypatch, extra_enemies=0):
    """An armed Quick Battle (battle_end), the enemy killed, music logged as
    (start time, path, stream) for every stream the player starts."""
    App, DM, frames, player, enemy, log = _fight(
        monkeypatch, lengths={".mp3": 30.04, BLEW: BLEW_S, WIN: WIN_S})
    import QuickBattle.QuickBattle as QB
    from engine.quickbattle import battle_end
    battle_end.install(QB)
    battle_end.begin(QB, None)
    QB.g_iNumEnemies += extra_enemies            # others still alive: not the final kill
    starts = []
    real_factory = frames.player._factory

    def factory(path, looping=True):
        s = real_factory(path, looping)
        starts.append((frames.t, str(path), s))
        return s
    frames.player._factory = factory
    _kill(App, enemy)
    t_kill = frames.t
    frames.run(60.0)
    return App, frames, t_kill, starts


def test_a_won_battle_ends_with_enemyblewup_then_win_alone_then_ambient(monkeypatch):
    """The user's choice for a won Quick Battle (rendered from the game's own
    files): each destroyed ship has its sound, then straight to the victory.
    At the final kill EnemyBlewUp plays in full; Win starts the moment it
    ends and plays alone; Starting Ambient starts when Win ends, fading in.
    No other track starts, and nothing plays under Win. A suggestion for
    battle_end's Win fanfare, not BC (the original never plays Win)."""
    App, frames, t_kill, starts = _armed_kill(monkeypatch)
    blew = [(t, s) for t, p, s in starts if p.endswith(BLEW)]
    win = [(t, s) for t, p, s in starts if p.endswith(WIN)]
    assert len(blew) == 1 and len(win) == 1, [(t, p) for t, p, _s in starts]
    t_blew, t_win = blew[0][0], win[0][0]
    assert abs(t_blew - t_kill) < 0.1
    assert abs(t_win - (t_blew + BLEW_S)) <= 2.0 / 60.0      # at EnemyBlewUp's end
    tracks = [(t, p, s) for t, p, s in starts if not p.endswith((BLEW, WIN))]
    after_kill = [(t, p) for t, p, _s in tracks if t > t_kill]
    assert len(after_kill) == 1, after_kill                  # only the ambient
    t_amb, p_amb = after_kill[0]
    assert abs(t_amb - (t_win + WIN_S)) <= 2.0 / 60.0         # at Win's end
    assert "Ambient" in p_amb or "EpisGen" in p_amb or "Starting" in p_amb, p_amb


def test_the_ambient_after_win_fades_in(monkeypatch):
    from engine.appc.music_manager import END_HOLD_FADE_IN_S
    App, DM, frames, player, enemy, log = _fight(
        monkeypatch, lengths={".mp3": 30.04, BLEW: BLEW_S, WIN: WIN_S})
    import QuickBattle.QuickBattle as QB
    from engine.quickbattle import battle_end
    battle_end.install(QB)
    battle_end.begin(QB, None)
    made = []
    real_factory = frames.player._factory

    def factory(path, looping=True):
        s = real_factory(path, looping)
        made.append((frames.t, str(path), s))
        return s
    frames.player._factory = factory
    _kill(App, enemy)
    t_kill = frames.t
    frames.run(BLEW_S + WIN_S + 1.0)
    amb = [s for t, p, s in made if t > t_kill and not p.endswith((BLEW, WIN))]
    assert amb, made
    assert amb[0].gain < 1.0                     # still fading in
    frames.run(END_HOLD_FADE_IN_S + 0.1)
    assert amb[0].gain == 1.0


def test_a_kill_that_is_not_the_last_is_unchanged(monkeypatch):
    """Another enemy still counted: EnemyBlewUp, and the combat track
    DynamicMusic cues at the cut starts under it, as in the original
    (3.1 s into EnemyBlewUp)."""
    App, frames, t_kill, starts = _armed_kill(monkeypatch, extra_enemies=1)
    blew = [t for t, p, _s in starts if p.endswith(BLEW)]
    assert blew and not [t for t, p, _s in starts if p.endswith(WIN)]
    under = [(t, p) for t, p, _s in starts
             if blew[0] < t < blew[0] + BLEW_S and not p.endswith((BLEW, WIN))]
    assert under, [(t, p) for t, p, _s in starts]
