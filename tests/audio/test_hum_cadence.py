"""Hum reallocation runs at 10 Hz (wall clock) and at once on a scene switch,
a set removal or a death; a dead hulk never hums."""
import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio import engine_rumble, hum_allocator, scene_scope
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)

LISTENER = (0.0, 0.0, 0.0)


def _wav():
    data = struct.pack("<h", 0) * 8
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


class _Loc:
    def __init__(self, x): self.x, self.y, self.z = float(x), 0.0, 0.0


class _Prop:
    def GetEngineSound(self): return "Federation Engines"


class _Sub:
    def GetProperty(self): return _Prop()


class _Ship:
    def __init__(self, name, x):
        self._name, self._loc = name, _Loc(x)
        self.dead = False
    def GetName(self): return self._name
    def GetImpulseEngineSubsystem(self): return _Sub()
    def GetWorldLocation(self): return self._loc
    def GetNode(self): return self
    def IsDead(self): return self.dead
    def IsDying(self): return False


@pytest.fixture
def boot(tmp_path):
    scene_scope.reset_for_tests()
    hum_allocator.reset_for_tests()
    engine_rumble.reset_for_tests()
    init_audio_for_tests()
    wav = tmp_path / "e.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "Federation Engines", TGSound.LS_3D)
    yield
    shutdown_audio_for_tests()
    scene_scope.reset_for_tests()
    hum_allocator.reset_for_tests()
    engine_rumble.reset_for_tests()


def _count_updates(monkeypatch):
    calls = []
    real = hum_allocator.update
    monkeypatch.setattr(hum_allocator, "update",
                        lambda pos: (calls.append(1), real(pos))[1])
    return calls


def test_maybe_update_runs_at_10hz(boot, monkeypatch):
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [])
    calls = _count_updates(monkeypatch)
    ran = [hum_allocator.maybe_update(LISTENER, 100.0 + i / 60.0) for i in range(12)]
    assert len(calls) == 2
    assert ran[0] is True and ran[1] is False


def test_scene_switch_reallocates_same_frame(boot, monkeypatch):
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [])
    calls = _count_updates(monkeypatch)
    scene_scope.set_active_frame("a")
    assert hum_allocator.maybe_update(LISTENER, 50.0)
    assert not hum_allocator.maybe_update(LISTENER, 50.01)
    scene_scope.set_active_frame("a")  # unchanged key: not a switch
    assert not hum_allocator.maybe_update(LISTENER, 50.02)
    scene_scope.set_active_frame("b")
    assert hum_allocator.maybe_update(LISTENER, 50.03)
    assert len(calls) == 2


def test_set_removal_reallocates_next_call(boot, monkeypatch):
    from engine.appc import set_index
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [])
    assert hum_allocator.maybe_update(LISTENER, 10.0)
    assert not hum_allocator.maybe_update(LISTENER, 10.01)
    monkeypatch.setattr(set_index._h, "set_index_remove", lambda *a: None)
    monkeypatch.setattr(set_index._h, "set_index_visible", lambda *a: False)
    set_index.on_removed(object(), "x", object())
    assert hum_allocator.maybe_update(LISTENER, 10.02)


def test_ship_destroyed_marks_dirty(boot, monkeypatch):
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [])
    assert hum_allocator.maybe_update(LISTENER, 10.0)
    assert not hum_allocator.maybe_update(LISTENER, 10.01)
    engine_rumble._on_ship_event("destroyed", _Ship("s", 5))
    assert hum_allocator.maybe_update(LISTENER, 10.02)


def test_reset_clears_dirty_and_deadline(boot, monkeypatch):
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [])
    hum_allocator.maybe_update(LISTENER, 10.0)
    hum_allocator.mark_dirty()
    hum_allocator.reset_for_tests()
    assert hum_allocator.maybe_update(LISTENER, 0.0)  # deadline cleared
    assert not hum_allocator.maybe_update(LISTENER, 0.01)  # dirty cleared


def test_dead_hulk_never_restarts_hum(boot, monkeypatch):
    live, hulk = _Ship("live", 20), _Ship("hulk", 10)
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [live, hulk])
    hum_allocator.update(LISTENER)
    assert hum_allocator.humming_ship_names() == {"live", "hulk"}
    hulk.dead = True
    engine_rumble._on_ship_event("destroyed", hulk)  # SetDead's publish
    hum_allocator.update(LISTENER)  # hulk stays in its set
    assert hum_allocator.humming_ship_names() == {"live"}
