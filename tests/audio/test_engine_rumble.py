import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

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


class _FakeLoc:
    def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z


class _FakeShip:
    def __init__(self, sound_name, loc=(0.0, 0.0, 0.0)):
        self._impulse = _FakeSubsystem(_FakeProperty(sound_name))
        self._loc = _FakeLoc(*loc)
    def GetImpulseEngineSubsystem(self):
        return self._impulse
    def GetWorldLocation(self):
        return self._loc
    def GetNode(self):
        # Mirrors ObjectClass.GetNode(): a handle resolving GetWorldLocation.
        return self


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

    _dauntless_host.audio.clear_command_log()
    ship = _FakeShip("Federation Engines")
    ship_lifecycle.publish_added(ship)

    entries = _dauntless_host.audio.debug_command_log()
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

    _dauntless_host.audio.clear_command_log()
    ship_lifecycle.publish_destroyed(ship)
    ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "stop" in ops


def test_missing_engine_sound_does_not_crash(boot):
    from engine.appc import ship_lifecycle
    ship_lifecycle.reset()
    install_engine_rumble_listener()
    ship = _FakeShip("Nonexistent Engines")
    ship_lifecycle.publish_added(ship)
    ship_lifecycle.publish_destroyed(ship)


def test_attached_sources_pumps_ship_world_location(boot):
    """AttachToNode (via GetNode()) supersedes the old update_positions
    poller: engine_rumble.Play(attach_node=ship.GetNode()) registers with
    engine.audio.attached_sources, and attached_sources.pump() is what
    copies the ship's world position into the source now."""
    from engine.appc import ship_lifecycle
    from engine.audio import attached_sources
    attached_sources.reset_for_tests()
    reset_for_tests()
    ship_lifecycle.reset()
    install_engine_rumble_listener()

    ship = _FakeShip("Federation Engines", loc=(100.0, 200.0, 300.0))
    ship_lifecycle.publish_added(ship)

    _dauntless_host.audio.clear_command_log()
    attached_sources.pump(dt=0.016)

    pos_entries = [e for e in _dauntless_host.audio.debug_command_log()
                   if e["op"] == "set_position"]
    assert len(pos_entries) == 1
    assert pos_entries[0]["f"][0] == 100.0
    assert pos_entries[0]["f"][1] == 200.0
    assert pos_entries[0]["f"][2] == 300.0

    # Tear down: ship_lifecycle.snapshot() is global; remove the partial
    # test object so later tests that iterate ships (e.g. target_list) don't
    # see a ship without GetName and crash.
    ship_lifecycle.reset()
    attached_sources.reset_for_tests()


def test_install_listener_replays_existing_live_ships(boot):
    """Mission load fires publish_added BEFORE init_audio in host_loop, so
    install_engine_rumble_listener must replay the current live set so rumble
    starts for ships that are already on stage by the time we subscribe.
    """
    from engine.appc import ship_lifecycle
    reset_for_tests()
    ship_lifecycle.reset()

    # Ship is added BEFORE the listener subscribes — typical of the host_loop
    # boot ordering (mission load → init_audio → install_engine_rumble_listener).
    ship = _FakeShip("Federation Engines")
    ship_lifecycle.publish_added(ship)

    _dauntless_host.audio.clear_command_log()
    install_engine_rumble_listener()

    play_entries = [e for e in _dauntless_host.audio.debug_command_log()
                    if e["op"] == "play"]
    assert len(play_entries) == 1
    assert play_entries[0]["b"][0] is True  # looping

    ship_lifecycle.reset()
