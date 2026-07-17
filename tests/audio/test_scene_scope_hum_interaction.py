"""Cross-registry consistency: scene_scope stopping a source out from under
hum_allocator's _humming registry.

`_PlayingSound.Stop()` already keeps `attached_sources._attached` consistent
synchronously (it calls `attached_sources.detach(self)` before zeroing
`_pid`). `hum_allocator._humming`, however, is a ship -> handle map that
`scene_scope.set_rendered_set` knows nothing about: when a scene switch stops
a humming ship's source directly, `_humming` is left holding a dead handle
(`_pid == 0`) for one instant, keyed by a ship `hum_allocator.update()` used
to consider "already humming" purely by dict-key presence.

In production this self-heals within the same tick: `host_loop.tick_audio`
calls `scene_scope.set_rendered_set(...)` and then `hum_allocator.update(...)`
back-to-back, and `_roster()` (`iter_active_ships`) is *already* scoped to the
new active set by the time `update()` runs.

Two cases follow from that ordering, and they are NOT symmetric:

1. A ship that only belonged to the outgoing set is simply absent from the
   new roster -- `_humming.keys() - winner_ids` catches it, `_stop_hum` is
   called (idempotent -- the handle's `_pid` is already 0), and the stale
   entry is dropped. This is an ordinary "fell out of top-4" reconcile.
2. The PLAYER ship is the guaranteed exception to case 1, not a rare edge
   case: `active_set()` IS `player.GetContainingSet()`, so the player is
   ALWAYS a roster member of the newly-active set -- it is the ship that
   DEFINES which set becomes active. On every warp, the player's own hum
   handle is therefore stopped by `scene_scope` and then immediately
   re-offered as a "winner" candidate by the very same `_roster()` call
   that no longer contains it under the old set. A dict-key-only
   `humming_ids` check treated this as "already humming" and never
   restarted it -- the player's engine hum went silent for the rest of the
   mission after the first warp (task 8 review Critical #1). `update()`
   now checks handle liveness (`_pid`), not just key presence, so case 2
   restarts cleanly within the same call instead of requiring the ship to
   fall out of a *later* roster first. This test file pins both cases so a
   future change to `hum_allocator.update`'s candidate filter, or to
   `tick_audio`'s ordering, cannot regress either one silently.
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
    """If the same ship object is still a roster candidate right after the
    scene switch (the ordinary case -- see the module docstring's case 2),
    hum_allocator must restart it with a fresh, live handle within the SAME
    call rather than leaving the stale dead one in place until some later
    roster reconcile."""
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
    # dead entry as not-actually-humming and restart it, not merely see the
    # dict key and skip it.
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    assert "s0" in hum_allocator.humming_ship_names()
    fresh_handle = hum_allocator._humming[ship]
    assert fresh_handle._pid, "must be a live handle, not the stale dead one"
    assert fresh_handle is not stale_handle


def test_player_warp_restarts_engine_hum_live_not_just_by_name(boot, monkeypatch):
    """CRITICAL regression (task 8 review Critical #1): the player's own
    engine hum must not die permanently on the first warp.

    active_set() IS player.GetContainingSet() -- the player is ALWAYS a
    roster member of the newly-active set; it is the ship that DEFINES it.
    On a warp (engine/appc/warp.py removes the ship from the old set, then
    adds it to the destination), scene_scope.set_rendered_set stops the
    player's old-set hum handle, and hum_allocator.update must restart it
    in that same tick's reconcile -- not merely continue reporting it as
    "humming" by dict-key while the handle stays dead, which was the
    reviewer-proven bug (silence for the rest of the mission)."""
    player = _Ship("player", x=0)
    monkeypatch.setattr(hum_allocator, "_roster", lambda: [player])

    scene_scope.set_rendered_set("space1")
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    assert "player" in hum_allocator.humming_ship_names()
    assert hum_allocator._humming[player]._pid

    # The warp: the player leaves space1 and enters space2. active_set()
    # now resolves to space2 (the player's new containing set) -- the
    # player is a roster member of it by construction.
    scene_scope.set_rendered_set("space2")
    assert not hum_allocator._humming[player]._pid, \
        "scene_scope must stop the old-set source"

    # host_loop.tick_audio's next line, same tick.
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))

    assert "player" in hum_allocator.humming_ship_names()
    assert hum_allocator._humming[player]._pid, (
        "the player's engine hum must be LIVE again after the warp -- a "
        "real _pid, not just a surviving dict key"
    )
