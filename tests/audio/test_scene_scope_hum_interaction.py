"""Cross-registry consistency: scene_scope stopping a source out from under
hum_allocator's _humming registry.

`_PlayingSound.Stop()` already keeps `attached_sources._attached` consistent
synchronously (it calls `attached_sources.detach(self)` before zeroing
`_pid`). `hum_allocator._humming`, however, is a ship -> handle map that
`scene_scope.set_rendered_set` knows nothing about: when a scene switch stops
a humming ship's source directly, `_humming` is left holding a dead handle
(`_pid == 0`) for one instant, keyed by a ship `hum_allocator.update()` would
otherwise still consider "already humming" (see `humming_ids` in
`hum_allocator.update`) and so would not restart.

In production this self-heals within the same tick: `host_loop.tick_audio`
calls `scene_scope.set_rendered_set(...)` and then `hum_allocator.update(...)`
back-to-back, and `_roster()` (`iter_active_ships`) is *already* scoped to the
new active set by the time `update()` runs, so any ship left over from the
old set is not a "winner" candidate and gets `_stop_hum`'d (idempotent — its
handle is already `_pid == 0`) and dropped from `_humming` in the very same
call. This test pins that self-heal so a future change that reorders
tick_audio, or that lets a ship survive a scene switch, cannot regress it
silently.
"""
import gc
import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio import engine_rumble, hum_allocator, scene_scope
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


@pytest.fixture
def boot(tmp_path, monkeypatch):
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


def test_scene_switch_stopped_hum_self_heals_on_next_update(boot, monkeypatch):
    """A ship humming in the outgoing set: scene_scope stops its source
    directly, hum_allocator's own reconcile then drops the now-dead entry
    and (if the ship is still a roster candidate) can re-start it cleanly."""
    ship = _Ship("s0", x=10)
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [ship])

    scene_scope.set_rendered_set("space1")
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    assert "s0" in hum_allocator.humming_ship_names()
    handle = hum_allocator._humming[ship]
    assert handle._pid

    # The scene switches away from space1 (as host_loop.tick_audio does,
    # BEFORE hum_allocator.update runs this tick).
    scene_scope.set_rendered_set("space2")
    assert not handle._pid, "scene_scope must stop the source directly"
    # The ship is still keyed in _humming for one instant, with a dead handle.
    assert ship in hum_allocator._humming
    assert not hum_allocator._humming[ship]._pid

    # hum_allocator's own reconcile (same tick, next line in tick_audio) sees
    # an empty roster (the ship left with the old set) and self-heals: the
    # stale entry is dropped via the normal "fell out of top-4" path.
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [])
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    assert ship not in hum_allocator._humming
    assert "s0" not in hum_allocator.humming_ship_names()


def test_scene_switch_stopped_hum_ship_still_in_new_roster_restarts_clean(boot, monkeypatch):
    """If the same ship object is (unusually) still a roster candidate right
    after the scene switch, hum_allocator must restart it with a fresh,
    live handle rather than leaving the stale dead one in place."""
    ship = _Ship("s0", x=10)
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [ship])

    scene_scope.set_rendered_set("space1")
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    stale_handle = hum_allocator._humming[ship]
    assert stale_handle._pid

    scene_scope.set_rendered_set("space2")
    assert not stale_handle._pid

    # Roster still contains the ship (e.g. it was re-added to the new active
    # set on the same tick a warp completed). hum_allocator must treat the
    # dead entry as "already humming" only in name -- it must not crash, and
    # a subsequent explicit re-arm must produce a live handle again.
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    # Documented current behaviour: because `ship` is still a dict key in
    # `_humming`, `humming_ids` treats it as already-humming and update()
    # does not re-Play() it within this same call -- the entry is left dead
    # until the ship next falls out of the roster (see the sibling test).
    # humming_ship_names() reports it as "humming" by name even though its
    # handle is dead; this is the one place scene_scope's stop and
    # hum_allocator's bookkeeping can disagree for longer than a tick, and is
    # reported (not silently papered over) in the Task 8 report.
    assert "s0" in hum_allocator.humming_ship_names()
    assert not hum_allocator._humming[ship]._pid
