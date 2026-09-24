"""A positional sound belongs to its EMITTER's frame, not the player's.

spec Sec 6 / the Plan-1 carried bug: two regions of one star system share a
coordinate FRAME offset by their anchors; a set left behind when the player
warps out keeps fighting. Positional audio used to tag every sound with the
PLAYER's/rendered SET NAME, so a left-behind ship's weapon fire registered
under -- and could be heard in -- the scene the player is actually in. These
tests pin the fix: scene_scope keys sources by FRAME, not by set name, and
attached_sources positions an emitter in the VIEWED set's local coordinates.
"""
import os
import struct

import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

import App
from engine.appc.sets import SetClass_Create
from engine.audio import attached_sources, scene_scope
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.systems import frames
from tests.helpers.mapped_regions import load_region


def _wav():
    data = struct.pack("<h", 0) * 8
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


def _ship(pSet, name, xyz):
    s = App.ShipClass_Create()
    s.SetName(name)
    pSet.AddObjectToSet(s, name)
    s.SetTranslateXYZ(*xyz)
    return s


def _plain_set(name):
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    return s


def setup_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()


@pytest.fixture
def audio(tmp_path):
    scene_scope.reset_for_tests()
    attached_sources.reset_for_tests()
    init_audio_for_tests()
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "SpaceSfx", TGSound.LS_3D)
    yield TGSoundManager.instance()
    shutdown_audio_for_tests()
    scene_scope.reset_for_tests()
    attached_sources.reset_for_tests()


def test_a_sound_is_tagged_with_its_emitters_frame_not_the_players(audio):
    """spec Sec 6 / the Plan-1 carried bug: an NPC in a left-behind set that
    fires after the player warps out must not register under the player's
    scene."""
    starbase = _plain_set("Starbase12")
    App.g_kSetManager.MakeRenderedSet("Starbase12")
    ona1 = load_region("Ona", "Ona1")
    npc = _ship(ona1, "npc", (0.0, 0.0, 0.0))

    snd = audio.GetSound("SpaceSfx")
    snd.SetLooping(True)
    handle = snd.Play(attach_node=npc.GetNode())
    assert handle is not None and handle._pid

    key = frames.frame_of(ona1).key
    assert scene_scope._by_frame[key] == [handle], \
        "the sound must be registered under the EMITTER's frame (Ona), not Starbase12"

    scene_scope.set_active_frame(frames.frame_of(starbase).key)
    assert not handle._pid, \
        "a left-behind NPC's fire must be stopped by a scene change away from its frame"


def test_a_sound_in_another_region_of_the_same_system_keeps_playing_at_the_right_place(audio):
    ona1 = load_region("Ona", "Ona1")
    ona2 = load_region("Ona", "Ona2")
    App.g_kSetManager.MakeRenderedSet("Ona1")
    emitter = _ship(ona2, "npc", (0.0, 0.0, 0.0))

    snd = audio.GetSound("SpaceSfx")
    _dauntless_host.audio.clear_command_log()
    handle = snd.Play(attach_node=emitter.GetNode())
    assert handle is not None and handle._pid

    off = frames.offset_between(ona1, ona2)
    plays = [c for c in _dauntless_host.audio.debug_command_log() if c["op"] == "play"]
    assert plays, "Play() must have issued a play command"
    launch_pos = (plays[-1]["f"][1], plays[-1]["f"][2], plays[-1]["f"][3])
    assert launch_pos == pytest.approx(off)

    _dauntless_host.audio.clear_command_log()
    attached_sources.pump(dt=0.016)
    moves = [c for c in _dauntless_host.audio.debug_command_log() if c["op"] == "set_position"]
    assert moves, "the source must keep pumping -- it is in the same star system, not another frame"
    pumped_pos = (moves[-1]["f"][0], moves[-1]["f"][1], moves[-1]["f"][2])
    assert pumped_pos == pytest.approx(off)

    # Same-system, different-region source must survive a scene switch to
    # the OTHER region -- both share the "Ona" frame.
    scene_scope.set_active_frame(frames.frame_of(ona1).key)
    assert handle._pid, "a same-system source must not be stopped by a same-frame scene switch"


def test_same_set_sound_position_is_unchanged(audio):
    ona1 = load_region("Ona", "Ona1")
    App.g_kSetManager.MakeRenderedSet("Ona1")
    emitter = _ship(ona1, "npc", (10.0, 20.0, 30.0))

    snd = audio.GetSound("SpaceSfx")
    _dauntless_host.audio.clear_command_log()
    handle = snd.Play(attach_node=emitter.GetNode())
    assert handle is not None and handle._pid

    plays = [c for c in _dauntless_host.audio.debug_command_log() if c["op"] == "play"]
    assert plays, "Play() must have issued a play command"
    launch_pos = (plays[-1]["f"][1], plays[-1]["f"][2], plays[-1]["f"][3])
    assert launch_pos == pytest.approx((10.0, 20.0, 30.0)), \
        "same-set positions must be byte-identical to today -- no offset applied"
