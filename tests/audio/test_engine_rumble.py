import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_open_stbc_host = pytest.importorskip("_open_stbc_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.audio.engine_rumble import install_engine_rumble_listener, reset_for_tests


def _wav():
    data = struct.pack("<h", 0) * 8
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


class _FakeProperty:
    def __init__(self, name): self._name = name
    def GetEngineSound(self): return self._name


class _FakeSubsystem:
    def __init__(self, prop): self._prop = prop
    def GetProperty(self): return self._prop


class _FakeShip:
    def __init__(self, sound_name, scene_node=42):
        self._impulse = _FakeSubsystem(_FakeProperty(sound_name))
        self._scene_node = scene_node
    def GetImpulseEngineSubsystem(self):
        return self._impulse
    def GetSceneNodeId(self):
        return self._scene_node


@pytest.fixture
def boot(tmp_path):
    reset_for_tests()  # ensure clean _installed state regardless of prior tests
    init_audio_for_tests()
    wav = tmp_path / "engine.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "Federation Engines", TGSound.LS_3D)
    yield
    shutdown_audio_for_tests()


def test_engine_rumble_plays_on_publish_added(boot):
    from engine.appc import ship_lifecycle
    ship_lifecycle.reset()
    install_engine_rumble_listener()

    _open_stbc_host.audio.clear_command_log()
    ship = _FakeShip("Federation Engines")
    ship_lifecycle.publish_added(ship)

    entries = _open_stbc_host.audio.debug_command_log()
    play_entries = [e for e in entries if e["op"] == "play"]
    assert len(play_entries) == 1
    assert play_entries[0]["b"][0] is True       # looping
    assert play_entries[0]["u"][1] == 0           # category SFX


def test_engine_rumble_stops_on_destroy(boot):
    from engine.appc import ship_lifecycle
    ship_lifecycle.reset()
    install_engine_rumble_listener()
    ship = _FakeShip("Federation Engines")
    ship_lifecycle.publish_added(ship)

    _open_stbc_host.audio.clear_command_log()
    ship_lifecycle.publish_destroyed(ship)
    ops = [e["op"] for e in _open_stbc_host.audio.debug_command_log()]
    assert "stop" in ops


def test_missing_engine_sound_does_not_crash(boot):
    from engine.appc import ship_lifecycle
    ship_lifecycle.reset()
    install_engine_rumble_listener()
    ship = _FakeShip("Nonexistent Engines")
    ship_lifecycle.publish_added(ship)
    ship_lifecycle.publish_destroyed(ship)
