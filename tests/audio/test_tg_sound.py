import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")

_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager,
    init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.appc.actions import TGSoundAction, TGSoundAction_Create


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
    _dauntless_host.audio.clear_command_log()
    audio.PlaySound("OneShot")
    ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "play" in ops


def test_sound_action_play_routes_to_manager(audio, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    audio.LoadSound(str(wav), "AlertSnd", TGSound.LS_3D)
    _dauntless_host.audio.clear_command_log()
    action = TGSoundAction_Create("AlertSnd")
    action.Play()
    ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "play" in ops


def test_play_returns_handle_we_can_stop(audio, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    snd = audio.LoadSound(str(wav), "LoopySnd", TGSound.LS_3D)
    snd.SetLooping(1)
    playing = snd.Play()
    assert playing is not None
    _dauntless_host.audio.clear_command_log()
    playing.Stop()
    ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "stop" in ops


def test_tgsound_stop_stops_active_loop(audio, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    snd = audio.LoadSound(str(wav), "AmbLoop", TGSound.LS_STREAMED)
    snd.SetLooping(1)
    snd.Play()
    _dauntless_host.audio.clear_command_log()
    snd.Stop()  # TGSound.Stop (not the per-handle _PlayingSound.Stop)
    ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "stop" in ops


def test_bc_default_min_max_distance(audio, tmp_path):
    """Guide §5: BC's TGSound::SetupFromFile defaults are 50/700, not 100/100000.

    The max matters most: AL_INVERSE_DISTANCE_CLAMPED floors gain at
    ref/(ref+(max-ref)) past max and holds it there. At max=100000 the floor
    never engages and distant ships fade to nothing, which is the one thing
    guide §5 says makes BC sound like BC.
    """
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    audio.LoadSound(str(wav), "Ranged", TGSound.LS_3D)
    snd = audio.GetSound("Ranged")

    assert snd._min_dist == 50.0
    assert snd._max_dist == 700.0
    assert TGSound.BC_DEFAULT_MIN_DISTANCE == 50.0
    assert TGSound.BC_DEFAULT_MAX_DISTANCE == 700.0

    _dauntless_host.audio.clear_command_log()
    snd.Play()
    log = _dauntless_host.audio.debug_command_log()
    mm = [c for c in log if c["op"] == "set_min_max_distance"]
    assert len(mm) == 1, f"expected one set_min_max_distance, got {log}"
    assert mm[0]["f"][0] == 50.0
    assert mm[0]["f"][1] == 700.0


def test_bc_default_priority_is_half(audio, tmp_path):
    """Guide §8: TGSound+0x68 default priority is 0.5, not 0.0."""
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    audio.LoadSound(str(wav), "Prio", TGSound.LS_3D)
    assert audio.GetSound("Prio").GetPriority() == 0.5
