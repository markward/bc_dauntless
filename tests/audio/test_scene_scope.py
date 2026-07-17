import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio import scene_scope
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)


def _wav():
    data = struct.pack("<h", 0) * 8
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def audio(tmp_path):
    scene_scope.reset_for_tests()
    init_audio_for_tests()
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "SpaceSfx", TGSound.LS_3D)
    yield TGSoundManager.instance()
    shutdown_audio_for_tests()
    scene_scope.reset_for_tests()


def test_switching_rendered_set_stops_the_old_scene(audio):
    """Guide §11: only the rendered set is audible."""
    scene_scope.set_rendered_set("space")
    snd = audio.GetSound("SpaceSfx")
    snd.SetLooping(True)
    handle = snd.Play()
    scene_scope.register(handle, "space")

    _dauntless_host.audio.clear_command_log()
    scene_scope.set_rendered_set("bridge")

    stops = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "stop"]
    assert stops, "leaving the space set must stop its sources"
    assert not handle._pid


def test_sources_in_the_rendered_set_survive(audio):
    scene_scope.set_rendered_set("space")
    snd = audio.GetSound("SpaceSfx")
    snd.SetLooping(True)
    handle = snd.Play()
    scene_scope.register(handle, "space")

    scene_scope.set_rendered_set("space")   # no change
    assert handle._pid


def test_register_reaps_naturally_finished_one_shots(audio):
    """Important #2: a naturally-finished one-shot (e.g. every phaser "Start"
    sound) must not be retained in `_by_set` forever -- unbounded growth, and
    register() rebuilding that list on every Play() would be O(n^2) on the
    audio hot path. The C++ AudioSystem reaps a finished source's backend
    slot on its own, but nothing zeroes the Python-side `_pid`; scene_scope
    must notice via `is_finished`, the same way attached_sources.pump does.

    `TGSound.Play()` auto-registers with scene_scope (see its own call to
    `scene_scope.register`), so plain `Play()` calls -- not a manual
    `scene_scope.register()` -- are what a real one-shot going through
    `_by_set` looks like; a second explicit register() here would just
    double-count the same handle and mask what's being tested."""
    scene_scope.set_rendered_set("space")
    snd = audio.GetSound("SpaceSfx")

    finished = snd.Play()
    assert finished._pid
    assert scene_scope._by_set["space"] == [finished]
    _dauntless_host.audio.debug_mark_finished(finished._pid)

    still_live = snd.Play()

    assert scene_scope._by_set["space"] == [still_live], \
        "the finished handle must be reaped, not retained forever"


def test_same_set_twice_is_a_noop(audio):
    """Mutation-proven: with a handle actually registered under "space",
    deleting EITHER the early-return guard OR the same-set `continue` makes
    this fail -- with nothing registered, "no stop ops" was trivially true
    regardless of whether the noop path was exercised at all."""
    scene_scope.set_rendered_set("space")
    snd = audio.GetSound("SpaceSfx")
    snd.SetLooping(True)
    handle = snd.Play()
    scene_scope.register(handle, "space")

    _dauntless_host.audio.clear_command_log()
    scene_scope.set_rendered_set("space")
    assert not [c for c in _dauntless_host.audio.debug_command_log()
                if c["op"] == "stop"]
    assert handle._pid, "the handle must survive re-asserting the same set"
