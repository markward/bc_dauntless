import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")

_open_stbc_host = pytest.importorskip("_open_stbc_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager, TGSoundAction, TGSoundAction_Create,
    init_audio_for_tests, shutdown_audio_for_tests,
)


def _wav(rate, samples):
    data = b"".join(struct.pack("<h", s) for s in samples)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, rate, rate*2, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def audio():
    init_audio_for_tests()
    yield TGSoundManager.instance()
    shutdown_audio_for_tests()


def test_load_then_get(audio, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0, 0, 0]))
    snd = audio.LoadSound(str(wav), "MySfx", TGSound.LS_3D)
    assert snd is not None
    assert audio.GetSound("MySfx") is not None
    assert audio.GetSound("MissingName") is None


def test_play_sound_via_manager(audio, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    audio.LoadSound(str(wav), "OneShot", TGSound.LS_3D)
    _open_stbc_host.audio.clear_command_log()
    audio.PlaySound("OneShot")
    ops = [e["op"] for e in _open_stbc_host.audio.debug_command_log()]
    assert "play" in ops


def test_sound_action_play_routes_to_manager(audio, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    audio.LoadSound(str(wav), "AlertSnd", TGSound.LS_3D)
    _open_stbc_host.audio.clear_command_log()
    action = TGSoundAction_Create("AlertSnd")
    action.Play()
    ops = [e["op"] for e in _open_stbc_host.audio.debug_command_log()]
    assert "play" in ops


def test_play_returns_handle_we_can_stop(audio, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    snd = audio.LoadSound(str(wav), "LoopySnd", TGSound.LS_3D)
    snd.SetLooping(1)
    playing = snd.Play()
    assert playing is not None
    _open_stbc_host.audio.clear_command_log()
    playing.Stop()
    ops = [e["op"] for e in _open_stbc_host.audio.debug_command_log()]
    assert "stop" in ops
