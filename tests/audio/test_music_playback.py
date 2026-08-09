"""Music playback with a volume ramp.

Per the clean-room reference (spec/TGAudio.md section 6, reviewed-not-tested):
TGMusic::StartMusic registers a fade timer, so a track change ramps rather than
cutting. Whether BC crossfades (both tracks audible) or fades out then in is NOT
established by the reference — this implements fade-out-then-in, the
conservative reading, and it needs live confirmation before being called
faithful.
"""
from engine.audio.music import MusicPlayer, FADE_SECONDS


class _FakeSound:
    def __init__(self, path):
        self.path = path
        self.gain = 1.0
        self.stopped = False
    def SetVolume(self, gain): self.gain = gain
    def Stop(self): self.stopped = True


def _player():
    made = []
    def factory(path):
        s = _FakeSound(path)
        made.append(s)
        return s
    return MusicPlayer(sound_factory=factory), made


def test_play_starts_the_track_silent_and_ramps_up():
    p, made = _player()
    p.play("data/music/a.mp3")
    assert made[0].path == "data/music/a.mp3"
    assert p.volume() == 0.0, "must start silent so the ramp is audible"
    p.update(FADE_SECONDS)
    assert p.volume() == 1.0


def test_ramp_is_partial_midway():
    p, _ = _player()
    p.play("data/music/a.mp3")
    p.update(FADE_SECONDS / 2.0)
    assert 0.0 < p.volume() < 1.0


def test_stop_ramps_down_then_stops_the_sound():
    p, made = _player()
    p.play("data/music/a.mp3")
    p.update(FADE_SECONDS)
    p.stop()
    p.update(FADE_SECONDS)
    assert p.volume() == 0.0
    assert made[0].stopped is True


def test_playing_a_second_track_stops_the_first():
    p, made = _player()
    p.play("data/music/a.mp3")
    p.update(FADE_SECONDS)
    p.play("data/music/b.mp3")
    p.update(FADE_SECONDS)
    assert made[0].stopped is True
    assert made[1].path == "data/music/b.mp3"


def test_volume_never_exceeds_one_or_drops_below_zero():
    p, _ = _player()
    p.play("data/music/a.mp3")
    p.update(FADE_SECONDS * 10.0)
    assert p.volume() == 1.0
    p.stop()
    p.update(FADE_SECONDS * 10.0)
    assert p.volume() == 0.0


def test_finished_reports_true_only_after_a_non_looping_track_ends():
    """The host polls this to know when to fire ET_MUSIC_DONE. A looping track
    never finishes — reporting otherwise would advance the queue every frame."""
    p, made = _player()
    p.play("data/music/a.mp3", looping=False)
    p.update(FADE_SECONDS)
    assert p.finished() is False
    made[0].playing = False          # backend reports the clip ran out
    assert p.finished() is True


def test_a_looping_track_never_reports_finished():
    p, made = _player()
    p.play("data/music/a.mp3", looping=True)
    p.update(FADE_SECONDS)
    made[0].playing = False
    assert p.finished() is False


def test_oneshot_does_not_disturb_the_current_track():
    p, made = _player()
    p.play("data/music/a.mp3")
    p.update(FADE_SECONDS)
    p.play_oneshot("data/music/fanfare.mp3")
    assert made[0].stopped is False, "fanfare must not stop the underlying track"
    assert p.volume() == 1.0
