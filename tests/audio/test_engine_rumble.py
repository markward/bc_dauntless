import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.audio.engine_rumble import install_engine_rumble_listener, reset_for_tests
from engine.audio import hum_allocator


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
    hum_allocator.reset_for_tests()
    init_audio_for_tests()
    wav = tmp_path / "engine.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "Federation Engines", TGSound.LS_3D)
    yield
    shutdown_audio_for_tests()
    hum_allocator.reset_for_tests()


def test_hum_allocator_starts_hum_for_ship_with_engine(boot, monkeypatch):
    """Hum START ownership moved to hum_allocator (guide §10) — the lifecycle
    listener no longer starts anything on `added`."""
    ship = _FakeShip("Federation Engines")
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [ship])

    _dauntless_host.audio.clear_command_log()
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))

    entries = _dauntless_host.audio.debug_command_log()
    play_entries = [e for e in entries if e["op"] == "play"]
    assert len(play_entries) == 1
    assert play_entries[0]["b"][0] is True       # looping
    assert play_entries[0]["u"][1] == 0           # category SFX


def test_engine_rumble_stops_on_destroy(boot, monkeypatch):
    """Hum STOP stays on the lifecycle listener: a destroyed ship's hum stops
    on the frame it dies rather than waiting for the allocator's next
    reconcile (see engine_rumble._on_ship_event)."""
    from engine.appc import ship_lifecycle
    ship_lifecycle.reset()
    install_engine_rumble_listener()

    ship = _FakeShip("Federation Engines")
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [ship])
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    assert ship in hum_allocator._humming  # sanity: hum is live before destroy

    _dauntless_host.audio.clear_command_log()
    ship_lifecycle.publish_destroyed(ship)
    ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "stop" in ops
    assert ship not in hum_allocator._humming

    ship_lifecycle.reset()


def test_missing_engine_sound_does_not_crash(boot):
    from engine.appc import ship_lifecycle
    ship_lifecycle.reset()
    install_engine_rumble_listener()
    ship = _FakeShip("Nonexistent Engines")
    ship_lifecycle.publish_added(ship)
    ship_lifecycle.publish_destroyed(ship)


def test_attached_sources_pumps_ship_world_location(boot, monkeypatch):
    """AttachToNode (via GetNode()) supersedes the old update_positions
    poller: hum_allocator.Play(attach_node=ship.GetNode()) registers with
    engine.audio.attached_sources, and attached_sources.pump() is what
    copies the ship's world position into the source now."""
    from engine.audio import attached_sources
    attached_sources.reset_for_tests()

    ship = _FakeShip("Federation Engines", loc=(100.0, 200.0, 300.0))
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [ship])
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))

    _dauntless_host.audio.clear_command_log()
    attached_sources.pump(dt=0.016)

    pos_entries = [e for e in _dauntless_host.audio.debug_command_log()
                   if e["op"] == "set_position"]
    assert len(pos_entries) == 1
    assert pos_entries[0]["f"][0] == 100.0
    assert pos_entries[0]["f"][1] == 200.0
    assert pos_entries[0]["f"][2] == 300.0

    attached_sources.reset_for_tests()


def test_hum_uses_bc_near_field_distances(boot, monkeypatch):
    """Guide §5: the hum is the sole exception to 50/700 — 4.375/35.0.

    The max of 35.0 is the certain half and the one that matters: it makes the
    hum a tight near-field sound instead of reaching 700 units like weapons do.
    """
    from engine.audio import engine_rumble
    ship = _FakeShip("Federation Engines")
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [ship])

    _dauntless_host.audio.clear_command_log()
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))

    mm = [c for c in _dauntless_host.audio.debug_command_log()
          if c["op"] == "set_min_max_distance"]
    assert mm, "hum must push its own min/max, not inherit the 50/700 default"
    assert mm[-1]["f"][0] == 4.375
    assert mm[-1]["f"][1] == 35.0
    assert engine_rumble.HUM_MIN_DISTANCE == 4.375
    assert engine_rumble.HUM_MAX_DISTANCE == 35.0
