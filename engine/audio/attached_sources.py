"""Per-frame world-transform copy for node-attached 3D sounds.

Guide §7: `AttachToNode` is the only positioning mechanism BC scripts use —
they never set a position per frame. BC stores the scene node and copies its
world transform into the emitter every frame.

We have no scene graph. In the deferred-renderer model Python owns object
transforms and `ObjectClass.GetNode()` hands back an `_ObjectNodeRef` — a weak
handle to the owning object exposing `GetWorldLocation()`. So the "node" here
is that ref, and this module is BC's per-frame copy.

Weakness matters: a queued torpedo sound must never keep a dead ship alive, and
a GC'd owner must drop out of the pump rather than freeze its emitter in place.
"""
from __future__ import annotations

from typing import Optional


def node_world_position(node) -> Optional[tuple[float, float, float]]:
    """World (x, y, z) for a node ref, or None when it cannot be resolved.

    Coordinates MUST be real numbers. `TGObject.__getattr__` hands back a
    chainable `_Stub` for any unimplemented attribute; a stub coerces to 0.0
    and would silently pin the sound to the world origin, which is strictly
    worse than falling back to non-positional playback. This guard is the same
    one `TGSoundAction._node_position` documents — both call here now.
    """
    if node is None:
        return None
    getter = getattr(node, "GetWorldLocation", None)
    if getter is None:
        return None
    try:
        loc = getter()
    except Exception:
        return None
    if loc is None:
        return None
    x = getattr(loc, "x", None)
    y = getattr(loc, "y", None)
    z = getattr(loc, "z", None)
    if not all(type(c) in (int, float) for c in (x, y, z)):
        return None
    return (float(x), float(y), float(z))


class _Entry:
    __slots__ = ("handle", "node", "prev_pos")

    def __init__(self, handle, node) -> None:
        self.handle = handle
        self.node = node
        self.prev_pos: Optional[tuple[float, float, float]] = None


# Keyed by the playing-source id so a re-attached handle replaces cleanly.
_attached: dict[int, _Entry] = {}


def attach(handle, node) -> None:
    """Track `handle` against `node` until the handle stops or the node dies."""
    if handle is None or node is None or not handle._pid:
        return
    _attached[handle._pid] = _Entry(handle, node)


def detach(handle) -> None:
    if handle is not None and handle._pid:
        _attached.pop(handle._pid, None)


def pump(dt: float) -> None:
    """Copy every attached node's world position into its source.

    Called once per tick from host_loop.tick_audio, before the listener update
    so the positional math sees current source positions.
    """
    for pid, entry in list(_attached.items()):
        if not entry.handle._pid:          # explicitly stopped
            del _attached[pid]
            continue
        pos = node_world_position(entry.node)
        if pos is None:                    # owner GC'd or unresolvable
            del _attached[pid]
            continue
        entry.handle.SetPosition(*pos)
        entry.prev_pos = pos


def reset_for_tests() -> None:
    _attached.clear()
