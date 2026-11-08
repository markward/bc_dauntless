"""engine.audio.volume: the one owner of the audio channel gains.

The Audio settings tab sets a 0-100 level per channel, and the boot notice
mutes every channel while the game loads behind it. Both used to call
set_category_gain directly, and the unmute restored 1.0, which would throw the
player's levels away on every launch. Now both go through this module, which
keeps the levels and works out what each channel's gain should be.
"""
import pytest

from engine.audio import volume


class _FakeAudio:
    def __init__(self):
        self.gains = {}
        self.doppler = []

    def set_category_gain(self, category, gain):
        self.gains[category] = gain

    def set_doppler_enabled(self, on):
        self.doppler.append(on)


@pytest.fixture
def audio():
    volume.reset()
    fake = _FakeAudio()
    volume.attach(fake)
    yield fake
    volume.reset()


def test_attaching_pushes_every_channel_at_full_volume(audio):
    assert audio.gains == {"Music": 1.0, "Voice": 1.0, "SFX": 1.0,
                           "Interface": 1.0}
    assert audio.doppler == [True]


def test_a_level_follows_a_loudness_curve(audio):
    """Half way down the bar sounds about half as loud (-12 dB), rather than
    barely quieter, which is what a straight line gives."""
    volume.set_level("Music", 50)
    assert audio.gains["Music"] == pytest.approx(0.25)
    volume.set_level("Music", 0)
    assert audio.gains["Music"] == 0.0
    volume.set_level("Music", 100)
    assert audio.gains["Music"] == 1.0


def test_channels_are_independent(audio):
    volume.set_level("Voice", 20)
    assert audio.gains["Voice"] == pytest.approx(0.04)
    assert audio.gains["SFX"] == 1.0
    assert audio.gains["Interface"] == 1.0
    assert audio.gains["Music"] == 1.0


def test_levels_are_clamped_to_the_bar(audio):
    volume.set_level("SFX", 140)
    assert volume.level("SFX") == 100
    volume.set_level("SFX", -5)
    assert volume.level("SFX") == 0


def test_an_unknown_channel_is_refused(audio):
    with pytest.raises(KeyError):
        volume.set_level("Ambience", 50)


def test_unmuting_restores_the_players_levels_not_full_volume(audio):
    volume.set_level("SFX", 50)
    volume.set_muted(True)
    assert set(audio.gains.values()) == {0.0}
    volume.set_muted(False)
    assert audio.gains["SFX"] == pytest.approx(0.25)
    assert audio.gains["Voice"] == 1.0


def test_a_level_set_while_muted_is_heard_after_the_unmute(audio):
    volume.set_muted(True)
    volume.set_level("Voice", 50)
    assert audio.gains["Voice"] == 0.0
    volume.set_muted(False)
    assert audio.gains["Voice"] == pytest.approx(0.25)


def test_3d_audio_off_switches_off_doppler(audio):
    volume.set_3d_enabled(False)
    assert audio.doppler[-1] is False
    volume.set_3d_enabled(True)
    assert audio.doppler[-1] is True


def test_a_reattached_backend_gets_the_current_state(audio):
    """The backend can be shut down and brought back up; a fresh one starts at
    full gain with Doppler on, so it must be told the player's settings."""
    volume.set_level("Music", 50)
    volume.set_3d_enabled(False)
    fresh = _FakeAudio()
    volume.attach(fresh)
    assert fresh.gains["Music"] == pytest.approx(0.25)
    assert fresh.doppler == [False]


def test_nothing_is_pushed_without_a_backend():
    volume.reset()
    volume.set_level("SFX", 30)     # must not raise
    volume.set_3d_enabled(False)
    assert volume.level("SFX") == 30
    volume.reset()
