import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager, TGSoundRegion,
    TGSoundRegion_GetRegion, TGSoundRegion_Create,
    init_audio_for_tests, shutdown_audio_for_tests,
)


def _wav(rate, samples):
    data = b"".join(struct.pack("<h", s) for s in samples)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def audio():
    init_audio_for_tests()
    yield TGSoundManager.instance()
    shutdown_audio_for_tests()


def test_get_region_is_singleton_per_name(audio):
    r1 = TGSoundRegion_GetRegion("bridge")
    r2 = TGSoundRegion_GetRegion("bridge")
    r3 = TGSoundRegion_GetRegion("other")
    assert r1 is r2
    assert r1 is not r3
    assert TGSoundRegion_Create("bridge") is r1


def test_set_filter_mutes_then_restores_playing_member(audio, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    snd = audio.LoadSound(str(wav), "Hum", TGSound.LS_STREAMED)
    snd.SetVolume(1.0)
    snd.SetLooping(1)
    region = TGSoundRegion_GetRegion("bridge")
    region.SetFilter(TGSoundRegion.FT_NONE)
    region.AddSound(snd)
    snd.Play()

    _dauntless_host.audio.clear_command_log()
    region.SetFilter(TGSoundRegion.FT_MUTE)
    muted = [e for e in _dauntless_host.audio.debug_command_log()
             if e["op"] == "set_gain"]
    assert muted and muted[-1]["f"][0] == 0.0

    _dauntless_host.audio.clear_command_log()
    region.SetFilter(TGSoundRegion.FT_NONE)
    restored = [e for e in _dauntless_host.audio.debug_command_log()
                if e["op"] == "set_gain"]
    assert restored and restored[-1]["f"][0] == 1.0


def test_add_sound_tolerates_none(audio):
    region = TGSoundRegion_GetRegion("bridge")
    region.AddSound(None)  # a failed LoadSoundInGroup returns None
