import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
pytest.importorskip("_dauntless_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager,
    init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.core.game import Game


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


def test_game_load_sound_in_group_registers_and_groups(audio, tmp_path):
    wav = tmp_path / "v.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    g = Game()
    snd = g.LoadSoundInGroup(str(wav), "ViewOn", "BridgeGeneric")
    assert snd is not None
    snd.SetVolume(1.0)  # SDK chains .SetVolume on the return value
    assert audio.GetSound("ViewOn") is snd


def test_delete_all_sounds_in_group_removes_members(audio, tmp_path):
    wav = tmp_path / "v.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    audio.LoadSoundInGroup(str(wav), "A", "BridgeGeneric")
    audio.LoadSoundInGroup(str(wav), "B", "BridgeGeneric")
    assert audio.GetSound("A") is not None
    audio.DeleteAllSoundsInGroup("BridgeGeneric")
    assert audio.GetSound("A") is None
    assert audio.GetSound("B") is None


def test_load_sound_in_group_missing_file_returns_none(audio, tmp_path):
    snd = audio.LoadSoundInGroup(str(tmp_path / "nope.wav"), "X", "BridgeGeneric")
    assert snd is None
