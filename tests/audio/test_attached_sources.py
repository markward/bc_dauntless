import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio import attached_sources
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


class _FakeNode:
    """Stands in for _ObjectNodeRef: the only contract is GetWorldLocation()."""
    def __init__(self, loc): self._loc = loc
    def GetWorldLocation(self): return self._loc


class _ChainableStub:
    """Mimics TGObject.__getattr__ -> _Stub: truthy, and coerces to 0.0.

    This is the trap the whole task exists to close — a stub node must fall
    back to non-positional, never silently pin the sound to the world origin.
    """
    def __call__(self, *a, **k): return self
    def __getattr__(self, _n): return self
    def __float__(self): return 0.0


@pytest.fixture
def audio(tmp_path):
    attached_sources.reset_for_tests()
    init_audio_for_tests()
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "Torp", TGSound.LS_3D)
    yield TGSoundManager.instance()
    shutdown_audio_for_tests()
    attached_sources.reset_for_tests()


def test_node_world_position_reads_the_node():
    assert attached_sources.node_world_position(_FakeNode(_Loc(1.0, 2.0, 3.0))) == (1.0, 2.0, 3.0)


def test_node_world_position_rejects_stub_node():
    """A chainable stub must yield None, not (0.0, 0.0, 0.0)."""
    assert attached_sources.node_world_position(_ChainableStub()) is None
    assert attached_sources.node_world_position(None) is None
    assert attached_sources.node_world_position(_FakeNode(None)) is None


def test_attach_to_node_tracks_the_object_each_pump(audio):
    snd = audio.GetSound("Torp")
    loc = _Loc(10.0, 0.0, 0.0)
    snd.AttachToNode(_FakeNode(loc))
    handle = snd.Play()
    assert handle is not None

    _dauntless_host.audio.clear_command_log()
    loc.x = 25.0
    attached_sources.pump(dt=0.016)

    moves = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "set_position"]
    assert moves, "AttachToNode must move the source when the object moves"
    assert moves[-1]["f"][0] == 25.0


def test_stopped_handle_is_dropped_from_the_pump(audio):
    snd = audio.GetSound("Torp")
    snd.AttachToNode(_FakeNode(_Loc(1.0, 1.0, 1.0)))
    handle = snd.Play()

    # Positive precondition: prove the sound really was being pumped BEFORE
    # Stop() -- otherwise the "no set_position after Stop()" assertion below
    # is vacuously true even if attach() never tracked anything at all.
    _dauntless_host.audio.clear_command_log()
    attached_sources.pump(dt=0.016)
    moves = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "set_position"]
    assert moves, "sound must be attached and pumping before Stop() is called"

    handle.Stop()

    _dauntless_host.audio.clear_command_log()
    attached_sources.pump(dt=0.016)
    assert not [c for c in _dauntless_host.audio.debug_command_log()
                if c["op"] == "set_position"]


def test_dead_object_is_dropped_from_the_pump(audio):
    """_ObjectNodeRef is weak — a GC'd ship must not keep the source pumping."""
    import weakref

    class _Owner:
        def GetWorldLocation(self): return _Loc(5.0, 5.0, 5.0)

    owner = _Owner()
    ref = weakref.ref(owner)

    class _WeakNode:
        def GetWorldLocation(self):
            o = ref()
            return None if o is None else o.GetWorldLocation()

    snd = audio.GetSound("Torp")
    snd.AttachToNode(_WeakNode())
    snd.Play()

    # Positive precondition: prove the sound really was being pumped WHILE
    # the owner was still alive -- otherwise the "no set_position after
    # del owner" assertion below is vacuously true even if attach() never
    # tracked anything at all.
    _dauntless_host.audio.clear_command_log()
    attached_sources.pump(dt=0.016)
    moves = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "set_position"]
    assert moves, "sound must be attached and pumping while the owner is alive"

    del owner

    _dauntless_host.audio.clear_command_log()
    attached_sources.pump(dt=0.016)
    assert not [c for c in _dauntless_host.audio.debug_command_log()
                if c["op"] == "set_position"]


def test_finished_one_shot_is_dropped_from_the_pump(audio):
    """A one-shot that finishes naturally must not pump a dead pid forever.

    The C++ AudioSystem reaps a finished one-shot's source, but nothing tells
    Python -- without this, every one-shot ever played (e.g. every phaser
    "Start" sound) would leave a permanent _attached entry.
    """
    snd = audio.GetSound("Torp")
    snd.AttachToNode(_FakeNode(_Loc(1.0, 1.0, 1.0)))
    handle = snd.Play()
    assert handle is not None

    # Positive precondition: prove the sound really was being pumped before
    # it finishes.
    _dauntless_host.audio.clear_command_log()
    attached_sources.pump(dt=0.016)
    moves = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "set_position"]
    assert moves, "sound must be attached and pumping before it finishes"

    _dauntless_host.audio.debug_mark_finished(handle._pid)

    _dauntless_host.audio.clear_command_log()
    attached_sources.pump(dt=0.016)
    assert not [c for c in _dauntless_host.audio.debug_command_log()
                if c["op"] == "set_position"], \
        "a finished one-shot must be reaped from the pump"
    assert not attached_sources._attached, \
        "the finished handle's entry must be dropped, not just skipped"


def test_node_world_position_stub_still_rejected(audio):
    """Reaffirms the isinstance guard: a chainable-stub-shaped node still
    yields None even after relaxing `type(c) in (...)` back to isinstance."""
    assert attached_sources.node_world_position(_ChainableStub()) is None


def test_stub_node_falls_back_to_non_positional_play(audio):
    """A node that fails to resolve must not silently pin to world-origin.

    Play() must force a genuinely non-positional source (not merely omit the
    position argument, which would still play POSITIONAL at (0,0,0) for any
    sound loaded LS_3D).
    """
    snd = audio.GetSound("Torp")
    snd.AttachToNode(_ChainableStub())

    _dauntless_host.audio.clear_command_log()
    handle = snd.Play()
    assert handle is not None

    plays = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "play"]
    assert plays, "Play() must have issued a play command"
    assert plays[-1]["b"][1] is False, \
        "a stub node must degrade to a non-positional source, not (0,0,0)"


def test_pump_feeds_source_velocity_from_position_delta(audio):
    """Guide §6: a moving emitter needs AL_VELOCITY or doppler is dead."""
    snd = audio.GetSound("Torp")
    loc = _Loc(0.0, 0.0, 0.0)
    snd.AttachToNode(_FakeNode(loc))
    snd.Play()

    attached_sources.pump(dt=0.5)   # first pump seeds prev_pos
    _dauntless_host.audio.clear_command_log()
    loc.x = 10.0
    attached_sources.pump(dt=0.5)   # 10 GU in 0.5 s -> 20 GU/s

    vels = [c for c in _dauntless_host.audio.debug_command_log()
            if c["op"] == "set_velocity"]
    assert vels, "attached sources must report velocity for doppler"
    assert vels[-1]["f"][0] == pytest.approx(20.0)


def test_first_pump_reports_zero_velocity(audio):
    """No prev_pos yet — must not invent a velocity from a null origin."""
    snd = audio.GetSound("Torp")
    snd.AttachToNode(_FakeNode(_Loc(500.0, 0.0, 0.0)))
    snd.Play()

    _dauntless_host.audio.clear_command_log()
    attached_sources.pump(dt=0.5)

    vels = [c for c in _dauntless_host.audio.debug_command_log()
            if c["op"] == "set_velocity"]
    assert vels, "first pump should still report a (zero) velocity"
    assert vels[-1]["f"][0] == pytest.approx(0.0)


def test_zero_dt_does_not_divide_by_zero(audio):
    snd = audio.GetSound("Torp")
    loc = _Loc(0.0, 0.0, 0.0)
    snd.AttachToNode(_FakeNode(loc))
    snd.Play()
    attached_sources.pump(dt=0.016)
    loc.x = 1.0
    attached_sources.pump(dt=0.0)   # paused frame — must not raise
