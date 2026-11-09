"""Quick Battle music, situation by situation, against the original.

Measured on the original (stbc-oracle music probe batch 5, native Windows,
real time; mission time in s):
* Q1 no enemy in range, 5 min: Starting Ambient (EpisGen2, 60.03 s) loops as
  one track; no ET_MUSIC_DONE in 300 s. Q7 (Starbase 12) the same.
* Q2 60 s on the setup screen: Starting Ambient there. The 15 s friendlies
  process has found the player alone and stronger (fw=1 fn=1), so Start goes
  to Combat Confident; the next run of that process (here 0.13 s later, on its
  15 s grid) sets Combat Neutral.
* Q4 a second fight after a win: Combat Confident 0.055 s after the restart,
  with no Panic step (the friendlies conditions keep their last value).
* Q5 Galaxy + Akira vs Sovereign: Panic, then Neutral at the first friendlies
  run. Q6 Galaxy + Sovereign vs Bird of Prey: Panic, then Confident."""
import pytest

pytest.importorskip("_dauntless_host")

from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader
from tests.helpers.headless_frames import Frames


def _session(monkeypatch):
    import App, DynamicMusic
    import QuickBattle.QuickBattle as QB
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    frames = Frames(lengths={".mp3": 30.04})
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

    def start(enemies, friends=(), at=100.0):
        """Quick Battle's own Start, through its 2 s load, with real frames;
        the enemies placed `at` GU from the player."""
        QB.g_kEnemyList = [(e, e, "msg", "QuickBattle.QuickBattleAI", "Enemy", 1.0) for e in enemies]
        QB.g_kFriendList = [(f, f, "msg", "QuickBattle.QuickBattleFriendlyAI", "Friend", 1.0)
                            for f in friends]
        controller.loader.start_quickbattle()
        game = App.Game_GetCurrentGame()
        assert frames.run(5.0, until=lambda: getattr(game, "_preload_done_event", None) is not None)
        hl._fire_pending_preload_done()
        player = App.Game_GetCurrentPlayer()
        p = player.GetWorldLocation()
        names = QB.pEnemies.GetNameTuple()
        en = [App.ShipClass_Cast(o) for o in player.GetContainingSet().GetClassObjectList(App.CT_SHIP)
              if App.ShipClass_Cast(o).GetName() in names]
        for s in en:
            s.SetTranslateXYZ(p.x, p.y + at, p.z)
        return App.g_kUtopiaModule.GetGameTime(), player, en
    return App, DynamicMusic, frames, log, start


def _switches(log, after=-1.0):
    return [(t, a) for n, t, a in log if n == "SwitchMusic" and t >= after]


def test_the_ambient_loops_as_one_track(monkeypatch):
    App, DM, frames, log, start = _session(monkeypatch)
    frames.run(300.0)
    assert DM.sCurrentMusicType == "Starting Ambient"
    assert not [e for e in log if e[0] == "MusicDone"]
    ambient = [s for s in frames.made if s.path.endswith("EpisGen2.mp3")]
    assert len(ambient) == 1 and ambient[0].looping and ambient[0].playing


def test_start_after_the_setup_screen_is_confident_until_the_friendlies_rerun(monkeypatch):
    App, DM, frames, log, start = _session(monkeypatch)
    frames.run(60.0)
    assert DM.sCurrentMusicType == "Starting Ambient"
    sm = DM.pStateMachine
    assert sm.pFriendliesWinning.GetStatus() == 1 and sm.pFriendliesNotLosing.GetStatus() == 1
    t0, player, en = start(["Sovereign"])
    frames.run(20.0)
    sw = _switches(log, after=t0 - 0.1)
    assert sw[0][1] == "Combat Confident" and sw[0][0] - t0 < 0.1
    assert sw[1][1] == "Combat Neutral" and sw[1][0] - sw[0][0] <= 15.0 + 0.1


def test_friends_even_go_from_panic_to_neutral(monkeypatch):
    App, DM, frames, log, start = _session(monkeypatch)
    t0, player, en = start(["Sovereign"], friends=["Akira"])
    frames.run(20.0)
    assert [a for _t, a in _switches(log, after=t0 - 0.1)] == ["Combat Panic", "Combat Neutral"]


def test_friends_strong_go_from_panic_to_confident(monkeypatch):
    App, DM, frames, log, start = _session(monkeypatch)
    t0, player, en = start(["BirdOfPrey"], friends=["Sovereign"])
    frames.run(20.0)
    assert [a for _t, a in _switches(log, after=t0 - 0.1)] == ["Combat Panic", "Combat Confident"]


def test_a_second_fight_goes_straight_to_combat_with_no_panic_step(monkeypatch):
    App, DM, frames, log, start = _session(monkeypatch)
    t0, player, en = start(["BirdOfPrey"])
    frames.run(20.0)
    en[0].DamageSystem(en[0].GetHull(), en[0].GetHull().GetCondition() + 10.0)
    frames.run(30.0)
    assert DM.sCurrentMusicType == "Starting Ambient"
    t1, player, en = start(["BirdOfPrey"])
    frames.run(5.0)
    sw = _switches(log, after=t1 - 0.1)
    assert sw and sw[0][1] == "Combat Confident" and sw[0][0] - t1 < 0.1
    assert "Combat Panic" not in [a for _t, a in sw]
