import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager,
    init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.audio import bridge_ambient


def _wav():
    data = struct.pack("<h", 0) * 2
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def audio(tmp_path):
    init_audio_for_tests()
    bridge_ambient.reset_for_tests()
    wav = tmp_path / "amb.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "AmbBridge", TGSound.LS_STREAMED)
    yield TGSoundManager.instance()
    bridge_ambient.reset_for_tests()
    shutdown_audio_for_tests()


def test_set_active_false_stops_orphan_ambbridge(audio):
    # Simulate the SDK's LoadBridge.py:213 load-time play that bridge_ambient
    # does NOT own a handle for.
    snd = audio.GetSound("AmbBridge")
    snd.SetLooping(1)
    snd.Play()
    _dauntless_host.audio.clear_command_log()
    bridge_ambient.set_active(False)
    ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "stop" in ops


def test_set_active_true_starts_then_false_stops(audio):
    bridge_ambient.set_active(True)
    _dauntless_host.audio.clear_command_log()
    bridge_ambient.set_active(False)
    ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "stop" in ops
