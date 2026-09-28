""""Enter Warp" / "Exit Warp" survive the tunnel warp's frame changes.

Mark, live: on a tunnel warp (Set Course to another system) the "Exit Warp"
wind-down is heard but not the "Enter Warp" crack. The crack sits
_SFX_ENTER_FLASH_AT (~1.5 s) into a clip started that long before the burst,
attached to the player's node. At the burst _WarpDepartAction parks the
player in BC's "warp" set -- a different FRAME from the system it left -- and
the next host_loop.tick_audio switches scene_scope's active frame, which
stopped every source tagged with the old frame: the Enter Warp clip, exactly
at its crack.

The rule these tests pin: a sound ATTACHED to an object belongs to that
object's CURRENT frame, so it follows its owner across a set change and is
stopped only if the owner is outside the viewed frame afterwards. A sound
attached to a ship left behind in the source system is still stopped when
the view leaves (system-frames plan 2 task 6).

Production order is reproduced: sim ticks (the warp's actions fire), then
tick_audio, every frame.
"""
import os
import struct
import sys
import types

import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

import App
from engine import host_loop
from engine.appc import warp
from engine.appc.sets import SetClass_Create
from engine.audio import attached_sources, scene_scope
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.core.loop import GameLoop, TICK_DELTA


def _wav():
    data = struct.pack("<h", 0) * 8
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def audio(tmp_path, monkeypatch):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    scene_scope.reset_for_tests()
    attached_sources.reset_for_tests()
    init_audio_for_tests()
    wav = tmp_path / "w.wav"
    wav.write_bytes(_wav())
    for name in ("Enter Warp", "Exit Warp", "NpcLoop"):
        TGSoundManager.instance().LoadSound(str(wav), name, TGSound.LS_3D)
    # The flythrough, as host_loop.run() configures it (the predicate is
    # always True live); the VFX itself is not under test.
    warp.configure_warp_vfx(enabled=lambda: True,
                            start=lambda *a, **k: None,
                            stop=lambda: None,
                            vantage_of=lambda key: None)
    warp.configure_warp_hooks(realize=None, teardown=None)
    from engine.appc import articulation
    monkeypatch.setattr(articulation, "time_to_reach", lambda s, st: 0.0)
    yield TGSoundManager.instance()
    warp.configure_warp_vfx(start=None, stop=None, enabled=None,
                            vantage_of=None)
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    shutdown_audio_for_tests()
    scene_scope.reset_for_tests()
    attached_sources.reset_for_tests()


def _tick_audio():
    host_loop.tick_audio(camera_position=(0.0, 0.0, 0.0),
                         camera_forward=(0.0, 1.0, 0.0),
                         camera_up=(0.0, 0.0, 1.0),
                         dt=TICK_DELTA, player=App.Game_GetCurrentPlayer())


def _tunnel(monkeypatch, tag):
    """A player in set Src<tag>, a tunnel warp to a fresh system D<tag>, and
    a spy recording every warp sound's handle as (name, handle, tick)."""
    src = SetClass_Create()
    App.g_kSetManager.AddSet(src, "Src" + tag)
    player = App.ShipClass_Create()
    player.SetName("player")
    src.AddObjectToSet(player, "player")
    from engine.core.game import Game, _set_current_game
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    App.g_kSetManager.MakeRenderedSet("Src" + tag)
    mod = types.ModuleType("FakeSys.D" + tag)
    mod.Initialize = lambda: App.g_kSetManager.AddSet(SetClass_Create(),
                                                      "D" + tag)
    monkeypatch.setitem(sys.modules, "FakeSys.D" + tag, mod)
    played = []
    tick = [0]
    real = warp._play_attached

    def _spy(name, ship):
        h = real(name, ship)
        played.append((name, h, tick[0]))
        return h
    monkeypatch.setattr(warp, "_play_attached", _spy)
    seq = warp.WarpSequence_Create(player, "FakeSys.D" + tag,
                                   placement="Player Start")
    return src, player, seq, played, tick


def _run(seq, player, tick, until, bound_s=60.0):
    loop = GameLoop()
    _tick_audio()                      # the source system is the viewed frame
    seq.Play()
    for i in range(int(round(bound_s / TICK_DELTA))):
        tick[0] = i + 1
        loop.tick()
        _tick_audio()
        if until():
            return
    raise AssertionError("condition not reached in %.0f s" % bound_s)


def test_enter_warp_survives_the_burst_into_the_warp_set(audio, monkeypatch):
    src, player, seq, played, tick = _tunnel(monkeypatch, "1")
    warp_set = []

    def _in_warp_set():
        cs = player.GetContainingSet()
        if cs is not None and cs.GetName() == warp._WARP_TRANSIT_SET_NAME:
            warp_set.append(tick[0])
        # A few ticks past the burst, with tick_audio run on each.
        return len(warp_set) >= 5

    _run(seq, player, tick, _in_warp_set)
    enter = [h for n, h, _ in played if n == "Enter Warp"]
    assert len(enter) == 1 and enter[0] is not None
    assert scene_scope.active_frame()[0] == "set" and \
        scene_scope.active_frame()[1].GetName() == warp._WARP_TRANSIT_SET_NAME
    assert enter[0].is_live(), \
        "the Enter Warp clip was cut when the player crossed into the warp set"
    # And it is still riding the ship, not left pinned at the source.
    entry = attached_sources._attached.get(enter[0]._pid)
    assert entry is not None and entry.node._owner() is player


def test_exit_warp_plays_on_arrival(audio, monkeypatch):
    src, player, seq, played, tick = _tunnel(monkeypatch, "2")

    def _exit_attempted():
        return any(n == "Exit Warp" for n, _, _ in played)

    _run(seq, player, tick, _exit_attempted)
    exit_ = [h for n, h, _ in played if n == "Exit Warp"]
    assert exit_[0] is not None, "Exit Warp was refused at arrival"
    assert exit_[0].is_live()
    assert player.GetContainingSet().GetName() == "D2"
    # Survives the tick_audio that catches the active frame up to arrival.
    _tick_audio()
    assert exit_[0].is_live()


def test_a_sound_on_a_ship_left_in_the_source_system_is_still_cut(
        audio, monkeypatch):
    """Regression guard (plan 2 task 6): only the OWNER's move carries a
    sound across frames -- an NPC left behind keeps its old frame's rule."""
    src, player, seq, played, tick = _tunnel(monkeypatch, "3")
    npc = App.ShipClass_Create()
    npc.SetName("npc")
    src.AddObjectToSet(npc, "npc")
    _tick_audio()
    snd = audio.GetSound("NpcLoop")
    snd.SetLooping(True)
    handle = snd.Play(attach_node=npc.GetNode())
    assert handle is not None and handle.is_live()

    def _in_warp_set():
        cs = player.GetContainingSet()
        return cs is not None and cs.GetName() == warp._WARP_TRANSIT_SET_NAME

    _run(seq, player, tick, _in_warp_set)
    assert not handle.is_live(), \
        "a left-behind NPC's sound must stop when the view leaves its frame"
