"""The one-active-scene rule (guide §11).

Only the rendered set is audible. On a set/view change every source belonging
to the now-inactive set stops (BC flushes handles in UpdateSounds). In BC,
this is what makes the bridge↔space switch silence the other world, and why
the viewscreen — space rendered *visually* on the bridge — carries no audio:
the space set is not the active sound scene. See the "Current wiring note"
below for what this module actually does in Dauntless today, which is
narrower than that.

Scope note: this covers the space side. 2D bridge/UI/music sources are not
registered here and are unaffected.

Current wiring note: `engine.host_loop.tick_audio` drives `set_rendered_set`
from `engine.appc.ship_iter.active_set()` — the player ship's own containing
(space) set. That name changes on a real space-to-space transition (e.g. warp
to another system), which is what this gate actually covers today. It does
NOT change when the camera toggles to/from the bridge: the player's ship
never leaves its space set just because the player is looking at the bridge.
So bridge muting is still handled by `engine.audio.engine_rumble.set_muted`
(see its docstring), not by this module, until/unless a future task drives
this from a bridge-aware source such as `App.g_kSetManager.GetRenderedSet()`.
"""
from __future__ import annotations

from typing import Optional

_rendered: Optional[str] = None
# set name -> list of _PlayingSound
_by_set: dict[str, list] = {}


def _is_live(handle) -> bool:
    """True if `handle` still has a live backend source.

    Delegates to `_PlayingSound.is_live` -- the one shared liveness check
    every registry (this one, `attached_sources.pump`, `hum_allocator.update`,
    `TGSound.Play`'s `_active` prune) must call, not reimplement. Without
    this check every positional one-shot ever played -- every phaser
    "Start", every torpedo, every hit_feedback impact -- would be retained
    in `_by_set` for the whole mission (unbounded growth), and `register()`
    rebuilding that list on every `Play()` would be O(n^2) on the audio hot
    path.
    """
    return handle.is_live()


def set_rendered_set(name: Optional[str]) -> None:
    """Make `name` the active sound scene, stopping every other set's sources."""
    global _rendered
    if name == _rendered:
        return
    _rendered = name
    for set_name, handles in list(_by_set.items()):
        if set_name == name:
            continue
        for h in handles:
            if h._pid:
                h.Stop()
        _by_set[set_name] = []


def register(handle, set_name: str) -> None:
    """Tag `handle` as belonging to `set_name`, so a scene change stops it.

    Also reaps every already-dead or naturally-finished entry already
    tracked under `set_name` (see `_is_live`) -- this is the only place
    `_by_set` is pruned outside of a scene switch, so it must not skip
    finished one-shots or the list grows without bound for the whole
    mission.

    Known proxy, not the real thing (guide §11 says "track each Sound's
    owning set"): the sole caller (`TGSound.Play`) always passes
    `scene_scope.rendered_set()` -- the CURRENTLY-rendered set -- not the
    set the sound's emitting object actually belongs to. Those are the same
    set for every real call site today (a ship only ever plays a sound for
    itself, in its own set), but if that ever stops holding, a sound played
    for an object in a non-rendered set would be mis-tagged as belonging to
    the rendered set and would never be stopped by a later scene change.
    """
    if handle is None or not handle._pid or not set_name:
        return
    live = [h for h in _by_set.setdefault(set_name, []) if _is_live(h)]
    live.append(handle)
    _by_set[set_name] = live


def rendered_set() -> Optional[str]:
    return _rendered


def reset_for_tests() -> None:
    global _rendered
    _rendered = None
    _by_set.clear()
