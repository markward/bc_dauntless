import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
pytest.importorskip("_dauntless_host")

from engine.audio.tg_sound import (
    TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.core.game import Game, _set_current_game


# (file, sound-name, volume) — must match sdk/Build/scripts/LoadBridge.py:358-375
_EXPECTED = [
    ("sfx/bridge2.loop.wav", "AmbBridge", 1.0),
    ("sfx/redalert.wav", "RedAlertSound", 1.0),
    ("sfx/yellowalert.wav", "YellowAlertSound", 1.0),
    ("sfx/greenalert.wav", "GreenAlertSound", 1.0),
    ("sfx/critical.wav", "CollisionAlertSound", 1.0),
    ("sfx/hail.wav", "ViewOn", 1.0),
    ("sfx/ViewscreenOff.WAV", "ViewOff", 1.0),
    ("sfx/Bridge/console_explo_01.wav", "ConsoleExplosion1", 0.5),
    ("sfx/Bridge/console_explo_02.wav", "ConsoleExplosion2", 0.5),
    ("sfx/Bridge/console_explo_03.wav", "ConsoleExplosion3", 0.5),
    ("sfx/Bridge/console_explo_04.wav", "ConsoleExplosion4", 0.5),
    ("sfx/Bridge/console_explo_05.wav", "ConsoleExplosion5", 0.5),
    ("sfx/Bridge/console_explo_06.wav", "ConsoleExplosion6", 0.5),
    ("sfx/Bridge/console_explo_07.wav", "ConsoleExplosion7", 0.5),
    ("sfx/Bridge/console_explo_08.wav", "ConsoleExplosion8", 0.5),
    ("sfx/Bridge/bridge_loop_warp.wav", "InSystemWarp", 1.0),
]


def _wav():
    data = struct.pack("<h", 0) * 2
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def game_with_assets(tmp_path, monkeypatch):
    # Point the sfx resolver at a tmp game dir and stage every bridge WAV so the
    # real LoadBridge.LoadSounds() loads from disk without needing the game/ tree.
    monkeypatch.setenv("OPEN_STBC_GAME_DIR", str(tmp_path))
    for rel, _name, _vol in _EXPECTED:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_wav())
    init_audio_for_tests()
    g = Game()
    _set_current_game(g)
    yield g
    _set_current_game(None)
    shutdown_audio_for_tests()


def test_real_loadbridge_loadsounds_registers_all(game_with_assets):
    import LoadBridge
    LoadBridge.LoadSounds()
    mgr = TGSoundManager.instance()
    for _rel, name, vol in _EXPECTED:
        snd = mgr.GetSound(name)
        assert snd is not None, f"{name} was not loaded by LoadBridge.LoadSounds()"
        assert abs(snd.GetVolume() - vol) < 1e-6, f"{name} volume {snd.GetVolume()} != {vol}"


def test_loadbridge_sounds_are_in_bridge_group(game_with_assets):
    import LoadBridge
    LoadBridge.LoadSounds()
    mgr = TGSoundManager.instance()
    # Terminate() relies on the BridgeGeneric group for unload.
    mgr.DeleteAllSoundsInGroup("BridgeGeneric")
    assert mgr.GetSound("ViewOn") is None
    assert mgr.GetSound("InSystemWarp") is None
