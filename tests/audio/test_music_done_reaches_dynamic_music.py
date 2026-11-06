"""A finished track reaches DynamicMusic, which cues the next one.

The original rotates a combat state's non-looping 30.04 s tracks at random,
one after another (stbc-oracle music probe, native Windows: a new track every
30.0-30.2 s). MusicManager.notify_track_finished posted ET_MUSIC_DONE with
g_kEventManager.BroadcastEvent, which the event manager does not have: the
name resolved to a no-op _Stub, so DynamicMusic never heard a track end."""
from engine.audio.music import MusicPlayer
from tests.audio.test_music_playback import _FakeSound

DT = 1.0 / 60.0


def _player():
    made = []

    def factory(path, looping=True):
        s = _FakeSound(path)
        s.looping = looping
        made.append(s)
        return s
    return MusicPlayer(sound_factory=factory), made



def test_a_finished_combat_track_reaches_dynamic_music():
    """The real event manager, no fake: a combat track ending posts
    ET_MUSIC_DONE that DynamicMusic.MusicDone receives, and it picks the next
    track of the group (the original rotates every 30.04 s track at random)."""
    from tests.helpers import headless_mission
    headless_mission.load("Maelstrom.Episode1.E1M1.E1M1")
    import App, DynamicMusic
    import QuickBattle.QuickBattleGame as QBG
    p, made = _player()
    mgr = App.g_kMusicManager
    mgr.set_backend(p)
    QBG.SetupMusic(App.Game_GetCurrentGame())
    DynamicMusic.SwitchMusic("Combat Neutral")
    first = DynamicMusic.sCurrentMusicType
    made[-1].playing = False                    # the 30 s track ends
    p.update(DT)
    assert p.finished()
    mgr.notify_track_finished()
    assert DynamicMusic.sCurrentMusicType.startswith("Cbt Neutral")
    assert DynamicMusic.sCurrentMusicType != first
