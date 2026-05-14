import os
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
pytest.importorskip("_open_stbc_host")

from engine.audio.tg_sound import init_audio_for_tests, shutdown_audio_for_tests


@pytest.fixture
def boot():
    init_audio_for_tests()
    yield
    shutdown_audio_for_tests()


def test_app_exposes_tgsound_and_manager(boot):
    import App
    assert hasattr(App, "TGSound")
    assert App.TGSound.LS_3D == 0
    assert hasattr(App, "TGSoundManager")
    assert App.g_kSoundManager is not None


def test_impulse_engine_property_remembers_sound_name():
    import App
    prop = App.ImpulseEngineProperty_Create("Impulse Engines")
    prop.SetEngineSound("Federation Engines")
    assert prop.GetEngineSound() == "Federation Engines"


def test_tg_sound_action_create_uses_audio_module(boot, tmp_path):
    import App
    import _open_stbc_host

    # Round-trip: load a sound, fire an action, see a play in the command log.
    wav = tmp_path / "x.wav"
    import struct
    data = struct.pack("<h", 0) * 4
    wav.write_bytes(
        b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
        + b"fmt " + struct.pack("<I", 16)
        + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
        + b"data" + struct.pack("<I", len(data)) + data
    )
    App.g_kSoundManager.LoadSound(str(wav), "TestRedAlert", App.TGSound.LS_3D)
    _open_stbc_host.audio.clear_command_log()
    action = App.TGSoundAction_Create("TestRedAlert")
    action.Play()
    ops = [e["op"] for e in _open_stbc_host.audio.debug_command_log()]
    assert "play" in ops
