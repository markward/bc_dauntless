"""Looping SFX are swept at a battle's end and at a mission load.

A weapon's sustained fire sound ("<weapon> Loop") is a looping source held
ONLY by its bank (`_loop_handle`) and stopped only by StopFiring. Any path
that removes the bank's ship, or drops a queued LOOP_STOP, without calling
StopFiring leaves that loop playing forever: Quick Battle's End Combat
deletes the firing NPCs, and a mission swap resets the effect queue. The
sweep (`tg_sound.stop_sfx_loops`) stops every looping SFX at those
boundaries; loops an owner reconciles itself (engine hums, the bridge
ambient) are left to that owner, and music is not SFX.
"""
import os
import struct
import types

import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio import tg_sound, bridge_ambient
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)


def _wav():
    data = struct.pack("<h", 0) * 2
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def audio(tmp_path):
    init_audio_for_tests()
    bridge_ambient.reset_for_tests()
    mgr = TGSoundManager.instance()
    for name, spec in (("Galaxy Phaser Loop", TGSound.LS_3D),
                       ("Galaxy Phaser Start", TGSound.LS_3D),
                       ("AmbBridge", TGSound.LS_STREAMED),
                       ("Track", TGSound.LS_STREAMED)):
        wav = tmp_path / (name.replace(" ", "_") + ".wav")
        wav.write_bytes(_wav())
        mgr.LoadSound(str(wav), name, spec)
    yield mgr
    bridge_ambient.reset_for_tests()
    tg_sound.stop_sfx_loops()
    shutdown_audio_for_tests()


def _rogue_loop(mgr):
    snd = mgr.GetSound("Galaxy Phaser Loop")
    snd.SetLooping(True)
    handle = snd.Play()
    assert handle is not None and handle.is_live()
    return handle


def _ops():
    return [e["op"] for e in _dauntless_host.audio.debug_command_log()]


# ── the sweep itself ────────────────────────────────────────────────────────

def test_sweep_stops_a_looping_sfx(audio):
    handle = _rogue_loop(audio)
    _dauntless_host.audio.clear_command_log()
    assert tg_sound.stop_sfx_loops() == 1
    assert not handle.is_live()
    assert "stop" in _ops()


def test_sweep_leaves_one_shots_alone(audio):
    audio.GetSound("Galaxy Phaser Start").Play()
    _dauntless_host.audio.clear_command_log()
    assert tg_sound.stop_sfx_loops() == 0
    assert "stop" not in _ops()


def test_sweep_leaves_music_playing(audio):
    snd = audio.GetSound("Track")
    snd.SetLooping(1)
    snd.SetMusic()
    handle = snd.Play()
    tg_sound.stop_sfx_loops()
    assert handle.is_live()


def test_a_loop_already_stopped_is_not_counted(audio):
    handle = _rogue_loop(audio)
    handle.Stop()
    assert tg_sound.stop_sfx_loops() == 0


def test_sweep_leaves_the_bridge_ambient_to_its_owner(audio):
    bridge_ambient.set_active(True)
    playing = bridge_ambient._playing
    assert playing is not None and playing.is_live()
    tg_sound.stop_sfx_loops()
    assert playing.is_live()


def test_sweep_leaves_engine_hums_to_the_allocator(audio, monkeypatch):
    from engine.audio import hum_allocator

    class _Ship:
        pass
    ship = _Ship()
    monkeypatch.setattr(hum_allocator, "_engine_sound_name_for",
                        lambda s: "Galaxy Phaser Loop")
    monkeypatch.setattr(hum_allocator, "_node_for", lambda s: None)
    hum_allocator._start_hum(ship)
    playing = hum_allocator._humming[ship]
    tg_sound.stop_sfx_loops()
    assert playing.is_live()
    hum_allocator._stop_hum(ship)


# ── the boundaries that call it ─────────────────────────────────────────────

def test_a_mission_swap_stops_rogue_loops(audio):
    from engine import host_loop
    handle = _rogue_loop(audio)
    host_loop.reset_mission_state()
    assert not handle.is_live()


def test_a_mission_change_stops_rogue_loops(audio):
    from engine.core import mission_change
    from tests.helpers.mission_change_fixtures import (
        _install, _world, _forget_world)
    try:
        _world()
        _install("_t.Old", Terminate=lambda m: None)
        _install("_t.New", Initialize=lambda m: None)
        handle = _rogue_loop(audio)
        assert mission_change.change(mission="_t.New") is True
        assert not handle.is_live()
    finally:
        _forget_world()


def test_quick_battle_end_simulation_stops_rogue_loops(audio):
    import App
    from engine.quickbattle import spawn
    calls = []
    qb = types.SimpleNamespace(g_idTimer=App.NULL_ID)
    qb.EndSimulation = lambda *a: calls.append("EndSimulation")
    assert spawn.install_end_simulation_hook(qb) is True
    handle = _rogue_loop(audio)
    qb.EndSimulation()
    assert calls == ["EndSimulation"]
    assert not handle.is_live()


def test_a_deleted_ship_has_its_weapons_silenced(monkeypatch):
    """End Combat flags the battle's ships SetDeleteMe(1); a flagged ship
    can fire again before the host removes it, after the EndSimulation
    sweep. Removing it must stop its banks."""
    import App
    from engine import host_loop
    from engine.appc import warp
    from engine.appc.sets import SetClass_Create

    silenced = []
    monkeypatch.setattr(warp, "_silence_ship_weapons",
                        lambda obj: silenced.append(obj))
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "SweepTestSet")
    try:
        from engine.appc.objects import ObjectClass
        doomed = ObjectClass()
        kept = ObjectClass()
        pSet.AddObjectToSet(doomed, "Doomed")
        pSet.AddObjectToSet(kept, "Kept")
        doomed.SetDeleteMe(1)
        host_loop._process_object_deletions()
        assert silenced == [doomed]
    finally:
        App.g_kSetManager.DeleteSet("SweepTestSet")
