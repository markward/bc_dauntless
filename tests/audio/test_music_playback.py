"""Music playback — BC crossfades. Two streams are audible at once.

Corrected 2026-08-10 from the clean-room reference. An earlier version of this
module implemented fade-out-then-in ("the conservative reading") and it was
WRONG. BC schedules TWO volume-ramp records at the same instant with the same
duration — outgoing current->0, incoming 0->1 — and both streams play for the
whole fade.

The clinching falsifier, and the reason a sequential design cannot be right:
when there is NO current track, the incoming record is built with start volume
1 and duration 0. The fade-in exists ONLY when there is something to fade out
of. A sequential design would fade in from 0 every time.

Ramp record (spec/TGMusic.md 2.1, 20 bytes, reviewed-not-tested):
handle / duration / remaining (counts down by frame delta) / startVolume /
endVolume — and "there may be more than one of them live at once".
"""
from engine.audio.music import MusicPlayer


class _FakeSound:
    def __init__(self, path):
        self.path = path
        self.gain = 1.0
        self.stopped = False
        self.playing = True
    def SetVolume(self, gain): self.gain = gain
    def Stop(self):
        self.stopped = True
        self.playing = False


def _player():
    made = []
    def factory(path):
        s = _FakeSound(path)
        made.append(s)
        return s
    return MusicPlayer(sound_factory=factory), made


# ── the falsifier: no current track means no fade-in ────────────────────────

def test_first_track_starts_at_full_volume_with_no_fade():
    """THE FALSIFIER. With nothing to fade out of, the incoming record is
    startVolume 1, duration 0 — the track is simply at full volume at once."""
    p, made = _player()
    p.play("a.mp3", fade=2.0)
    assert made[0].gain == 1.0, "no current track => no fade-in"
    assert p.volume() == 1.0


def test_first_track_needs_no_update_tick_to_reach_full():
    p, made = _player()
    p.play("a.mp3", fade=2.0)
    # Not a single update() has run.
    assert made[0].gain == 1.0


# ── the crossfade proper ───────────────────────────────────────────────────

def test_track_change_keeps_both_streams_audible():
    """Both records run concurrently, so mid-fade BOTH sounds have gain > 0.
    This is the assertion a fade-out-then-in design cannot satisfy."""
    p, made = _player()
    p.play("a.mp3", fade=2.0)
    p.play("b.mp3", fade=2.0)
    p.update(1.0)                      # halfway
    outgoing, incoming = made[0], made[1]
    assert 0.0 < outgoing.gain < 1.0
    assert 0.0 < incoming.gain < 1.0
    assert outgoing.stopped is False, "outgoing must still be playing mid-fade"


def test_outgoing_falls_while_incoming_rises_over_the_same_duration():
    p, made = _player()
    p.play("a.mp3", fade=2.0)
    p.play("b.mp3", fade=2.0)
    p.update(0.5)
    out_a, in_a = made[0].gain, made[1].gain
    p.update(0.5)
    out_b, in_b = made[0].gain, made[1].gain
    assert out_b < out_a, "outgoing must fall"
    assert in_b > in_a, "incoming must rise"
    # Same duration, mirrored ramps: the pair sums to ~1 throughout.
    assert abs((out_a + in_a) - 1.0) < 1e-6
    assert abs((out_b + in_b) - 1.0) < 1e-6


def test_outgoing_stream_is_stopped_once_its_ramp_completes():
    p, made = _player()
    p.play("a.mp3", fade=2.0)
    p.play("b.mp3", fade=2.0)
    p.update(2.0)
    assert made[0].stopped is True
    assert made[1].stopped is False
    assert made[1].gain == 1.0
    assert p.volume() == 1.0


def test_fade_duration_comes_from_the_outgoing_tracks_value():
    """Changes are quantised to the OUTGOING track's own fade grid — the third
    LoadMusic argument. The caller supplies it; a longer grid fades slower."""
    p, made = _player()
    p.play("a.mp3", fade=4.0)
    p.play("b.mp3", fade=4.0)
    p.update(2.0)                      # half of 4.0
    assert abs(made[1].gain - 0.5) < 1e-6


# ── hard stop ──────────────────────────────────────────────────────────────

def test_stop_is_a_hard_stop_and_does_not_wait_for_a_ramp():
    """StopMusic is immediate. It does not schedule a fade-out."""
    p, made = _player()
    p.play("a.mp3", fade=2.0)
    p.stop()
    assert made[0].stopped is True, "stop must be immediate, not ramped"
    assert p.volume() == 0.0


def test_stop_during_a_crossfade_kills_both_streams():
    p, made = _player()
    p.play("a.mp3", fade=2.0)
    p.play("b.mp3", fade=2.0)
    p.update(1.0)
    p.stop()
    assert made[0].stopped is True
    assert made[1].stopped is True


# ── queueing + fanfare ─────────────────────────────────────────────────────

def test_a_start_requested_during_a_transition_is_queued():
    """A third track asked for mid-crossfade does not start a second
    simultaneous fade; it waits for the current transition to finish."""
    p, made = _player()
    p.play("a.mp3", fade=2.0)
    p.play("b.mp3", fade=2.0)
    p.update(1.0)
    p.play("c.mp3", fade=2.0)
    assert len(made) == 2, "queued, not started"
    p.update(1.0)                      # transition completes, queue releases
    assert len(made) == 3
    assert made[2].path == "c.mp3"


def test_oneshot_does_not_disturb_the_current_track():
    p, made = _player()
    p.play("a.mp3", fade=2.0)
    p.play_oneshot("fanfare.mp3")
    assert made[0].stopped is False
    assert p.volume() == 1.0


# ── bookkeeping ────────────────────────────────────────────────────────────

def test_volume_is_clamped_to_the_unit_range():
    p, _ = _player()
    p.play("a.mp3", fade=2.0)
    p.play("b.mp3", fade=2.0)
    p.update(99.0)
    assert p.volume() == 1.0


def test_finished_reports_true_only_after_a_non_looping_track_ends():
    """The host polls this to fire ET_MUSIC_DONE. A looping track never
    finishes — reporting otherwise advances the SDK queue every frame."""
    p, made = _player()
    p.play("a.mp3", looping=False, fade=2.0)
    assert p.finished() is False
    made[0].playing = False
    assert p.finished() is True


def test_a_looping_track_never_reports_finished():
    p, made = _player()
    p.play("a.mp3", looping=True, fade=2.0)
    made[0].playing = False
    assert p.finished() is False
