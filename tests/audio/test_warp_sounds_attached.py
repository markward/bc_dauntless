""""Enter Warp" / "Exit Warp" ride the warping ship's node.

BC attaches both to the ship (sdk WarpSequence.py:79-89, 285-297:
``pWarpSoundAction.SetNode(pShip.GetNode())``). Both are loaded LS_3D
(LoadTacticalSounds.py:79-80), so an UNattached play is a positional source
pinned where it started -- which a dash leaves at 10,000+ GU/s before the
crack, ~1.5 s into the clip, is heard (Mark, live: "I can hear the wind down
noise but not the crack").
"""
import os
import struct
import sys
import types

import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
pytest.importorskip("_dauntless_host")

import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create
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


@pytest.fixture
def audio(tmp_path):
    init_audio_for_tests()
    wav = tmp_path / "w.wav"
    wav.write_bytes(_wav())
    for name in ("Enter Warp", "Exit Warp"):
        TGSoundManager.instance().LoadSound(str(wav), name, TGSound.LS_3D)
    App.g_kSetManager._sets.clear()
    yield TGSoundManager.instance()
    App.g_kSetManager._sets.clear()
    warp.configure_warp_vfx(start=None, stop=None, enabled=None,
                            vantage_of=None)
    shutdown_audio_for_tests()


def _ship(set_name):
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, set_name)
    ship = App.ShipClass_Create()
    ship.SetName("ship")
    s.AddObjectToSet(ship, "ship")
    return ship


def _attached_owner(handle):
    entry = attached_sources._attached.get(handle._pid)
    return None if entry is None else entry.node._owner()


@pytest.mark.parametrize("name", ["Enter Warp", "Exit Warp"])
def test_play_attached_rides_the_ship_node(audio, name):
    ship = _ship("S1")
    handle = warp._play_attached(name, ship)
    assert handle is not None
    assert _attached_owner(handle) is ship


def test_play_attached_is_fail_open_for_a_missing_sound(audio):
    assert warp._play_attached("No Such Sound", _ship("S2")) is None


def test_the_tunnels_warp_sounds_are_attached_to_the_warping_ship(
        audio, monkeypatch):
    """Both of the tunnel's _WarpSoundActions carry the warping ship, and
    "Enter Warp" is still scheduled _SFX_ENTER_FLASH_AT before the burst."""
    from engine.appc import articulation
    monkeypatch.setattr(articulation, "time_to_reach", lambda s, st: 0.0)
    # An NPC's tunnel (BC plays both sounds for any warping ship).
    monkeypatch.setattr(warp, "_parts_warp_time", lambda s: 5.0)
    warp.configure_warp_vfx(
        enabled=lambda: True,
        start=lambda *a, **k: None,
        stop=lambda: None,
        vantage_of=lambda key: (1.0, 2.0, 3.0))
    ship = _ship("Src9")
    mod = types.ModuleType("FakeSys.D9")
    mod.Initialize = lambda: App.g_kSetManager.AddSet(SetClass_Create(), "D9")
    monkeypatch.setitem(sys.modules, "FakeSys.D9", mod)
    seq = warp.WarpSequence_Create(ship, "FakeSys.D9", placement="Player Start")
    sounds = [(s.action, s.delay) for s in seq._steps
              if isinstance(s.action, warp._WarpSoundAction)]
    assert [a._name for a, _ in sounds] == ["Enter Warp", "Exit Warp"]
    burst = [s.delay for s in seq._steps
             if isinstance(s.action, warp._WarpDepartAction)]
    assert len(burst) == 1 and burst[0] > warp._SFX_ENTER_FLASH_AT
    assert sounds[0][1] == pytest.approx(burst[0] - warp._SFX_ENTER_FLASH_AT)
    for action, _ in sounds:
        assert action._ship is ship
        before = set(attached_sources._attached)
        action._do_play()
        new = set(attached_sources._attached) - before
        assert len(new) == 1
        assert attached_sources._attached[new.pop()].node._owner() is ship
