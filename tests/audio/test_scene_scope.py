import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio import scene_scope
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
    scene_scope.reset_for_tests()
    init_audio_for_tests()
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "SpaceSfx", TGSound.LS_3D)
    yield TGSoundManager.instance()
    shutdown_audio_for_tests()
    scene_scope.reset_for_tests()


def test_switching_rendered_set_stops_the_old_scene(audio):
    """Guide §11: only the rendered set is audible."""
    scene_scope.set_rendered_set("space")
    snd = audio.GetSound("SpaceSfx")
    snd.SetLooping(True)
    handle = snd.Play()
    scene_scope.register(handle, "space")

    _dauntless_host.audio.clear_command_log()
    scene_scope.set_rendered_set("bridge")

    stops = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "stop"]
    assert stops, "leaving the space set must stop its sources"
    assert not handle._pid


def test_sources_in_the_rendered_set_survive(audio):
    scene_scope.set_rendered_set("space")
    snd = audio.GetSound("SpaceSfx")
    snd.SetLooping(True)
    handle = snd.Play()
    scene_scope.register(handle, "space")

    scene_scope.set_rendered_set("space")   # no change
    assert handle._pid


def test_same_set_twice_is_a_noop(audio):
    scene_scope.set_rendered_set("space")
    _dauntless_host.audio.clear_command_log()
    scene_scope.set_rendered_set("space")
    assert not [c for c in _dauntless_host.audio.debug_command_log()
                if c["op"] == "stop"]
