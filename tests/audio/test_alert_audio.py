import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_open_stbc_host = pytest.importorskip("_open_stbc_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.audio.alert_audio import AlertAudioListener


def _wav():
    data = struct.pack("<h", 0) * 4
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


class _FakeShip:
    # Mirror the real ShipClass constants from engine/appc/ships.py.
    GREEN_ALERT, YELLOW_ALERT, RED_ALERT = 0, 1, 2

    def __init__(self, level=GREEN_ALERT): self._lvl = level
    def GetAlertLevel(self): return self._lvl
    def SetAlertLevel(self, v): self._lvl = v


@pytest.fixture
def boot(tmp_path):
    init_audio_for_tests()
    mgr = TGSoundManager.instance()
    for name in ("RedAlertSound", "YellowAlertSound", "GreenAlertSound"):
        wav = tmp_path / f"{name}.wav"
        wav.write_bytes(_wav())
        mgr.LoadSound(str(wav), name, TGSound.LS_3D)
    yield
    shutdown_audio_for_tests()


def test_transition_to_red_fires_red_sound(boot):
    listener = AlertAudioListener()
    ship = _FakeShip(level=_FakeShip.GREEN_ALERT)
    listener.tick(ship)            # baseline; no transition
    _open_stbc_host.audio.clear_command_log()
    ship.SetAlertLevel(_FakeShip.RED_ALERT)
    listener.tick(ship)
    play_entries = [e for e in _open_stbc_host.audio.debug_command_log()
                    if e["op"] == "play"]
    assert len(play_entries) == 1


def test_no_transition_no_sound(boot):
    listener = AlertAudioListener()
    ship = _FakeShip(level=_FakeShip.YELLOW_ALERT)
    listener.tick(ship)
    _open_stbc_host.audio.clear_command_log()
    listener.tick(ship)
    play_entries = [e for e in _open_stbc_host.audio.debug_command_log()
                    if e["op"] == "play"]
    assert play_entries == []


def test_each_named_level_maps_to_its_sound(boot):
    listener = AlertAudioListener()
    ship = _FakeShip(level=_FakeShip.GREEN_ALERT)
    listener.tick(ship)

    cases = [
        (_FakeShip.RED_ALERT,    "RedAlertSound"),
        (_FakeShip.YELLOW_ALERT, "YellowAlertSound"),
        (_FakeShip.GREEN_ALERT,  "GreenAlertSound"),
    ]
    for lvl, expected_name in cases:
        ship.SetAlertLevel(lvl)
        _open_stbc_host.audio.clear_command_log()
        listener.tick(ship)
        play_entries = [e for e in _open_stbc_host.audio.debug_command_log()
                        if e["op"] == "play"]
        assert len(play_entries) == 1
        expected_buf = _open_stbc_host.audio.get_sound(expected_name)
        assert play_entries[0]["u"][0] == expected_buf, (
            f"Expected {expected_name} (buf {expected_buf}), "
            f"got buf {play_entries[0]['u'][0]}"
        )


def test_reset_rebaselines_so_next_tick_is_silent(boot):
    listener = AlertAudioListener()
    ship = _FakeShip(level=_FakeShip.GREEN_ALERT)
    listener.tick(ship)
    ship.SetAlertLevel(_FakeShip.RED_ALERT)
    listener.tick(ship)            # would fire RedAlertSound

    listener.reset()
    _open_stbc_host.audio.clear_command_log()
    listener.tick(ship)            # still RED; reset cleared the baseline → silent

    play_entries = [e for e in _open_stbc_host.audio.debug_command_log()
                    if e["op"] == "play"]
    assert play_entries == []


def test_handles_missing_player(boot):
    listener = AlertAudioListener()
    listener.tick(None)            # must not crash
