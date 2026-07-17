"""Torpedo launch sounds must ride the torpedo, not play at the world origin.

Root cause (confirmed by live-play probe, see docs commit): _spawn_projectile
called TGSoundManager.PlaySound(name) with no node and no position. The sound
is registered LS_3D (positional=True), and AudioSystem::play ORs the load-time
positional flag in regardless of whether a position was actually supplied --
so every torpedo launch played positional at (0, 0, 0), with nothing tracking
it (no volume falloff, no doppler).

BC's actual sequence (sdk/Build/scripts/MissionLib.py:3284-3296, verbatim):

    pSound = App.g_kSoundManager.GetSound(pcLaunchSound)
    if pSound != None:
        pSound.AttachToNode(pTorp.GetNode())
        pSoundRegion = App.TGSoundRegion_GetRegion(pSet.GetName())
        if pSoundRegion != None:
            pSoundRegion.AddSound(pSound)
        pSound.Play()

These tests pin: the launch sound plays AT the torpedo's actual (non-origin)
launch position, and a later attached_sources.pump() follows the torpedo as
it moves -- proving AttachToNode (not a one-shot position snapshot) is what's
wired up.
"""
import os
import struct

import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.appc.math import TGPoint3
from engine.appc.projectiles import _active
from engine.appc.properties import WeaponSystemProperty
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import TorpedoSystem, TorpedoTube
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
    attached_sources.reset_for_tests()
    init_audio_for_tests()
    wav = tmp_path / "photon.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "Photon Torpedo", TGSound.LS_3D)
    yield TGSoundManager.instance()
    shutdown_audio_for_tests()
    attached_sources.reset_for_tests()


def _tube_on_ship_away_from_origin():
    """A ready PhotonTorpedo tube on a ship far from the world origin, so a
    position-at-origin bug is distinguishable from the real launch point."""
    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(1000.0, 2000.0, 3000.0))
    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    prop = WeaponSystemProperty("Torpedoes")
    prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    parent.SetProperty(prop)
    parent._parent_ship = ship
    ship._torpedo_system = parent
    tube = TorpedoTube("Forward Torpedo 1")
    tube._max_ready = 1
    tube._num_ready = 1
    tube._reload_delay = 40.0
    parent.AddChildSubsystem(tube)
    return tube, ship


def test_launch_sound_plays_at_the_torpedo_not_the_origin(audio):
    _active.clear()
    tube, ship = _tube_on_ship_away_from_origin()

    _dauntless_host.audio.clear_command_log()
    tube.Fire(target=None, offset=None)

    assert len(_active) == 1, "sanity: Fire must have spawned the torpedo"
    torp = _active[-1]

    plays = [c for c in _dauntless_host.audio.debug_command_log() if c["op"] == "play"]
    assert plays, "Fire must have played the launch sound"
    play = plays[-1]
    assert play["b"][1] is True, "Photon Torpedo is LS_3D -- must play positional"
    pos = (play["f"][1], play["f"][2], play["f"][3])
    assert pos != (0.0, 0.0, 0.0), (
        "launch sound played at the world origin -- not attached to the torpedo"
    )
    assert pos == pytest.approx((torp._position.x, torp._position.y, torp._position.z))

    _active.clear()


def test_launch_sound_tracks_the_torpedo_in_flight(audio):
    _active.clear()
    tube, ship = _tube_on_ship_away_from_origin()
    tube.Fire(target=None, offset=None)
    torp = _active[-1]

    # Advance the torpedo the way projectiles.update_all does (position +=
    # velocity * dt), then pump attached sources exactly like host_loop does.
    torp._position = torp._position + torp._velocity * 1.0

    _dauntless_host.audio.clear_command_log()
    attached_sources.pump(dt=1.0)

    moves = [c for c in _dauntless_host.audio.debug_command_log() if c["op"] == "set_position"]
    assert moves, (
        "the launch sound must be attached to (and follow) the torpedo's node, "
        "not a one-shot position snapshot"
    )
    assert moves[-1]["f"][0] == pytest.approx(torp._position.x)
    assert moves[-1]["f"][1] == pytest.approx(torp._position.y)
    assert moves[-1]["f"][2] == pytest.approx(torp._position.z)

    _active.clear()
