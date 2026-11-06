"""A fanfare ends the current track on its fade grid; DynamicMusic cues the next.

Measured on the original (stbc-oracle music probe, native Windows, real time,
Quick Battle loss): PlayerBlewUp started 20.79 s into a 30.04 s combat track
(LoadMusic fade grid 2.0) and that track reported done 24.04 s in -- the next
2 s boundary (22.0) plus a 2 s fade, 6 s before its end -- and DynamicMusic
cued a new track of the same state. In the win run the fanfare started 28.85 s
in and the track simply ran to its own end (30.09 s): the cut would have
fallen after it."""
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


def _run(p, seconds, made=None, end_at=None):
    """Advance; a non-looping track 'ends' (playing False) at end_at seconds."""
    t = 0.0
    done_at = None
    while t < seconds - 1e-9:
        p.update(DT)
        t += DT
        if end_at is not None and made is not None:
            for s, at in end_at:
                if t >= at and s.playing:
                    s.playing = False
        if done_at is None and p.finished():
            done_at = t
    return done_at


def test_the_track_ends_at_the_next_grid_boundary_plus_a_fade():
    p, made = _player()
    p.play("Panic-9a.mp3", looping=False, fade=0.0)
    track = made[0]
    _run(p, 20.79)
    p.play_fanfare("Transition 14.mp3", grid=2.0)
    fanfare = made[1]
    done = _run(p, 6.0)
    # 20.79 + 1.21 to the 22.0 boundary + 2.0 fade = 24.0 s into the track.
    assert done is not None and abs((20.79 + done) - 24.0) < 2 * DT
    assert track.stopped
    assert fanfare.stopped is False             # the fanfare plays on


def test_a_fanfare_near_the_end_leaves_the_track_to_end_by_itself():
    p, made = _player()
    p.play("Confident-11a.mp3", looping=False, fade=0.0)
    track = made[0]
    _run(p, 28.85)
    p.play_fanfare("Transition 13.mp3", grid=2.0)
    # Its own end (30.04 s) comes before the 30.0 boundary's fade would finish.
    done = _run(p, 3.0, made, end_at=[(track, 30.04 - 28.85)])
    assert done is not None and abs((28.85 + done) - 30.04) < 2 * DT


def test_the_next_track_starts_under_the_fanfare_at_full_volume():
    """The original: the next combat track started 3.1 s into EnemyBlewUp
    (an 11.47 s fanfare), so a track cued during a fanfare does not wait."""
    p, made = _player()
    p.play("Panic-9a.mp3", looping=False, fade=0.0)
    _run(p, 20.79)
    p.play_fanfare("Transition 14.mp3", grid=2.0)
    fanfare = made[1]
    _run(p, 4.0)                                # the interrupted track is done
    p.play("Panic-9g.mp3", looping=False, fade=2.0)   # DynamicMusic's next track
    assert len(made) == 3 and made[2].path == "Panic-9g.mp3"   # at once
    assert made[2].gain == 1.0                  # nothing to fade from: full at once
    assert fanfare.playing is not False and fanfare.stopped is False   # the fanfare plays on


def test_a_newer_fanfare_fades_out_a_still_playing_one():
    """Quick Battle's Win can start while EnemyBlewUp still plays: the newer
    fanfare takes over and the earlier one fades out over 0.5 s (not
    measured: the original Quick Battle never plays Win)."""
    from engine.audio.music import FANFARE_HANDOVER_S
    p, made = _player()
    p.play("Confident-11a.mp3", looping=False, fade=0.0)
    _run(p, 3.0)
    p.play_fanfare("Transition 13.mp3", grid=2.0)
    first = made[1]
    _run(p, 5.0)
    p.play_fanfare("Success-12.mp3", grid=2.0)
    second = made[-1]
    _run(p, FANFARE_HANDOVER_S / 2)
    assert 0.0 < first.gain < 1.0 and not first.stopped   # fading
    _run(p, FANFARE_HANDOVER_S)
    assert first.stopped                        # gone
    assert second.stopped is False and second.gain == 1.0  # the newer one plays on


def test_with_no_track_playing_a_fanfare_just_plays():
    p, made = _player()
    p.play_fanfare("Success-12.mp3", grid=2.0)
    assert len(made) == 1 and made[0].looping is False
    assert p.finished() is False


def test_the_manager_hands_the_current_tracks_grid_to_the_player():
    from engine.appc.music_manager import MusicManager
    calls = []

    class _Backend:
        def play(self, path, looping=True, fade=0.0): calls.append(("play", path))
        def play_fanfare(self, path, grid=0.0): calls.append(("fanfare", path, grid))
        def play_oneshot(self, path): calls.append(("oneshot", path))
        def stop(self): pass
    m = MusicManager()
    m.set_backend(_Backend())
    m.LoadMusic("sfx/Music/Panic-9a.mp3", "Cbt Panic 1", 2.0)
    m.LoadMusic("sfx/Music/Transition 14.mp3", "PlayerBlewUp", 2.0)
    m.StartMusic("Cbt Panic 1", 0)
    m.PlayFanfare("PlayerBlewUp")
    assert calls[-1] == ("fanfare", "sfx/Music/Transition 14.mp3", 2.0)
    assert m.current() == "Cbt Panic 1"         # the fanfare never becomes current


def test_dynamic_music_cues_a_new_track_of_the_same_state_after_a_fanfare():
    """End to end through the SDK's DynamicMusic: Combat Panic playing, the
    PlayerBlewUp fanfare, the host's pump (update + finished -> notify) --
    DynamicMusic's MusicDone then picks a different Combat Panic track."""
    from tests.helpers import headless_mission
    headless_mission.load("Maelstrom.Episode1.E1M1.E1M1")
    import App, DynamicMusic
    import QuickBattle.QuickBattleGame as QBG
    p, made = _player()
    mgr = App.g_kMusicManager
    mgr.set_backend(p)
    QBG.SetupMusic(App.Game_GetCurrentGame())
    DynamicMusic.SwitchMusic("Combat Panic")
    first = DynamicMusic.sCurrentMusicType
    assert first.startswith("Cbt Panic")

    def pump(seconds):
        t = 0.0
        while t < seconds:
            p.update(DT)
            if p.finished():
                mgr.notify_track_finished()
            t += DT
    pump(20.79)
    DynamicMusic.PlayFanfare("PlayerBlewUp")
    pump(4.0)
    assert DynamicMusic.sCurrentMusicType.startswith("Cbt Panic")
    assert DynamicMusic.sCurrentMusicType != first

