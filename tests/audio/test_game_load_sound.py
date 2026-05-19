import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
pytest.importorskip("_dauntless_host")

from engine.audio.tg_sound import (
    TGSound, init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.core.game import Game


@pytest.fixture
def boot():
    init_audio_for_tests()
    yield
    shutdown_audio_for_tests()


def test_game_load_sound_registers_into_manager(boot, tmp_path):
    g = Game()
    wav_path = tmp_path / "x.wav"
    data = struct.pack("<h", 0) * 4
    wav_path.write_bytes(
        b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
        + b"fmt " + struct.pack("<I", 16)
        + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
        + b"data" + struct.pack("<I", len(data)) + data
    )
    snd = g.LoadSound(str(wav_path), "TestSfx", TGSound.LS_3D)
    assert snd is not None
    # Subsequent GetSound resolves the same name.
    from engine.audio.tg_sound import TGSoundManager
    assert TGSoundManager.instance().GetSound("TestSfx") is snd
