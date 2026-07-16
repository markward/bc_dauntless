import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")  # prep for Task 6 init_audio helper

# These imports will succeed only after the binding lands.
_dauntless_host = pytest.importorskip("_dauntless_host")


def _make_pcm16_mono_wav(rate, samples):
    data = b"".join(struct.pack("<h", s) for s in samples)
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16) + fmt
            + b"data" + struct.pack("<I", len(data)) + data)


def test_audio_submodule_exists():
    assert hasattr(_dauntless_host, "audio")


def test_audio_load_and_play_via_null_backend():
    audio = _dauntless_host.audio
    audio.init(backend="null")
    wav = _make_pcm16_mono_wav(22050, [0, 1, -1, 2, -2])
    assert audio.load_sound("sfx/test.wav", "TestSound", wav, positional=False)
    sid = audio.get_sound("TestSound")
    assert sid != 0
    pid = audio.play("TestSound", looping=False, gain=1.0, category="SFX",
                     position=None)
    assert pid != 0
    log = audio.debug_command_log()
    assert any(entry["op"] == "play" for entry in log)
    audio.stop(pid)
    audio.shutdown()
