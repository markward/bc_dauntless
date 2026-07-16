import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio import hum_allocator
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)


def _wav():
    data = struct.pack("<h", 0) * 8
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


class _Loc:
    def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z


class _Prop:
    def GetEngineSound(self): return "Federation Engines"


class _Sub:
    def GetProperty(self): return _Prop()


class _Ship:
    def __init__(self, name, x):
        self._name, self._loc = name, _Loc(float(x), 0.0, 0.0)
    def GetName(self): return self._name
    def GetImpulseEngineSubsystem(self): return _Sub()
    def GetWorldLocation(self): return self._loc
    def GetNode(self): return self


class _NoEngine(_Ship):
    def GetImpulseEngineSubsystem(self): return None


@pytest.fixture
def boot(tmp_path, monkeypatch):
    hum_allocator.reset_for_tests()
    init_audio_for_tests()
    wav = tmp_path / "e.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "Federation Engines", TGSound.LS_3D)
    yield
    shutdown_audio_for_tests()
    hum_allocator.reset_for_tests()


def _stub_roster(monkeypatch, ships):
    monkeypatch.setattr(hum_allocator, "_roster", lambda: list(ships))


def test_caps_at_four_nearest_ships(boot, monkeypatch):
    """Guide §10: cap of 4 is deliberate voice economy — keep it."""
    ships = [_Ship(f"s{i}", x=i * 10) for i in range(7)]
    _stub_roster(monkeypatch, ships)

    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))

    humming = hum_allocator.humming_ship_names()
    assert len(humming) == 4
    assert humming == {"s0", "s1", "s2", "s3"}   # the four nearest


def test_ship_falling_out_of_top4_stops_humming(boot, monkeypatch):
    near = [_Ship(f"s{i}", x=i * 10) for i in range(4)]
    far = _Ship("far", x=500)
    _stub_roster(monkeypatch, near + [far])
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    assert "far" not in hum_allocator.humming_ship_names()

    # Listener travels out to the far ship; s3 (x=30) is now the odd one out.
    hum_allocator.update(listener_pos=(500.0, 0.0, 0.0))
    humming = hum_allocator.humming_ship_names()
    assert "far" in humming
    assert "s0" not in humming
    assert len(humming) == 4


def test_ships_without_an_impulse_engine_never_hum(boot, monkeypatch):
    """BC's gate: ShipClass with ship+0x2CC != 0 (the ImpulseEngine subsystem)."""
    _stub_roster(monkeypatch, [_NoEngine("rock", x=1), _Ship("ship", x=2)])
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    assert hum_allocator.humming_ship_names() == {"ship"}


def test_update_is_idempotent_for_a_stable_roster(boot, monkeypatch):
    """A ship already in the top-4 must not be restarted every frame."""
    ships = [_Ship(f"s{i}", x=i * 10) for i in range(3)]
    _stub_roster(monkeypatch, ships)
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))

    _dauntless_host.audio.clear_command_log()
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    plays = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "play"]
    assert not plays, "a stable top-4 must not re-trigger play()"
