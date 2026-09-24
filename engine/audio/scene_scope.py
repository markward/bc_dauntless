"""The one-active-scene rule (guide §11), keyed by FRAME (system-frames plan
2 task 6), not by set name.

Only the viewed FRAME is audible. On a frame change every source belonging
to a now-inactive frame stops (BC flushes handles in UpdateSounds). In BC,
this is what makes the bridge↔space switch silence the other world, and why
the viewscreen — space rendered *visually* on the bridge — carries no audio:
the space set is not the active sound scene. See the "Current wiring note"
below for what this module actually does in Dauntless today, which is
narrower than that.

Keying by frame rather than by set name is what fixes the Plan-1 carried
bug: a set left behind when the player warps out keeps fighting, and a
positional sound tagged by set NAME would stop firing across the warp
regardless of whether the two sets are even the same frame -- two regions of
one star system (e.g. Ona1/Ona2) are DIFFERENT sets sharing ONE frame, so a
sound started in Ona2 must survive a scene switch to Ona1, and a sound
started in a truly left-behind system must not. See
`engine.systems.frames` for what a frame key is.

Scope note: this covers the space side. 2D bridge/UI/music sources are not
registered here and are unaffected.

Current wiring note: `engine.host_loop.tick_audio` drives `set_active_frame`
from `frames.frame_of(frames.viewing_set())` -- the frame of the set the
world scene is drawn in (the player's own space set, or an in-space
cutscene's explicit rendered set). That frame changes on a real space-to-
space transition (e.g. warp to another system), which is what this gate
actually covers today. It does NOT change when the camera toggles to/from
the bridge: `frames.viewing_set()` itself falls back to the player's set
when the explicit rendered set is a bridge/interior scene (see its
docstring), so the player's ship never "leaves" its frame just because the
player is looking at the bridge. So bridge muting is still handled by
`engine.audio.engine_rumble.set_muted` (see its docstring), not by this
module.
"""
from __future__ import annotations

from typing import Optional

_active_frame: Optional[tuple] = None
# frame key -> list of _PlayingSound
_by_frame: dict[object, list] = {}


def _is_live(handle) -> bool:
    """True if `handle` still has a live backend source.

    Delegates to `_PlayingSound.is_live` -- the one shared liveness check
    every registry (this one, `attached_sources.pump`, `hum_allocator.update`,
    `TGSound.Play`'s `_active` prune) must call, not reimplement. Without
    this check every positional one-shot ever played -- every phaser
    "Start", every torpedo, every hit_feedback impact -- would be retained
    in `_by_frame` for the whole mission (unbounded growth), and `register()`
    rebuilding that list on every `Play()` would be O(n^2) on the audio hot
    path.
    """
    return handle.is_live()


def set_active_frame(key) -> None:
    """Make `key` the active sound scene, stopping every other frame's sources."""
    global _active_frame
    if key == _active_frame:
        return
    _active_frame = key
    for frame_key, handles in list(_by_frame.items()):
        if frame_key == key:
            continue
        for h in handles:
            if h._pid:
                h.Stop()
        _by_frame[frame_key] = []


def register(handle, key) -> None:
    """Tag `handle` as belonging to frame `key`, so a scene change stops it.

    Also reaps every already-dead or naturally-finished entry already
    tracked under `key` (see `_is_live`) -- this is the only place
    `_by_frame` is pruned outside of a scene switch, so it must not skip
    finished one-shots or the list grows without bound for the whole
    mission.

    `key` is the sound's owning frame (guide §11: "track each Sound's
    owning set" -- generalised to frame): `TGSound.Play` passes the
    EMITTER's frame (its attach node's containing set's frame) when there is
    a node, and the currently-active frame (`active_frame()`) for a sound
    with only an explicit position and no node. This is the real thing, not
    a proxy for it -- a sound played for an object in a non-viewed frame is
    tagged under ITS frame, and a later scene change away from that frame
    still stops it (see `tests/audio/test_audio_frames.py`).
    """
    if handle is None or not handle._pid or key is None:
        return
    live = [h for h in _by_frame.setdefault(key, []) if _is_live(h)]
    live.append(handle)
    _by_frame[key] = live


def active_frame():
    return _active_frame


def reset_for_tests() -> None:
    global _active_frame
    _active_frame = None
    _by_frame.clear()
