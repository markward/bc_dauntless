import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)


def _wav():
    data = struct.pack("<h", 0) * 8
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def audio(tmp_path):
    init_audio_for_tests()
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "P", TGSound.LS_3D)
    yield TGSoundManager.instance()
    shutdown_audio_for_tests()


def test_priority_reaches_the_backend_and_not_the_gain(audio):
    """Guide §8/footgun #7: 0.9/0.6/0.5 are a voice-stealing RANK.

    Mapping them to AL_GAIN would make every remote phaser 33% quieter than the
    original and leave priority flat.
    """
    snd = audio.GetSound("P")
    snd.SetPriority(0.6)
    snd.SetVolume(1.0)

    _dauntless_host.audio.clear_command_log()
    snd.Play()

    plays = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "play"]
    assert len(plays) == 1
    assert plays[0]["f"][0] == 1.0, "gain must be untouched by priority"
    assert plays[0]["f"][4] == pytest.approx(0.6), "priority must reach the backend"


def test_weapon_fire_priorities_match_bc():
    from engine.appc import weapon_subsystems as ws
    assert ws.LOCAL_FIRE_PRIORITY == 0.9
    assert ws.REMOTE_PHASER_PRIORITY == 0.6
    assert ws.REMOTE_PULSE_PRIORITY == 0.5
    assert ws.CO_FIRED_PRIORITY_STEP == 0.01
