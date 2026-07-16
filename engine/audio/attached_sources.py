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

try:
    import _dauntless_host
    _audio = _dauntless_host.audio
except (ImportError, AttributeError):
    _audio = None  # tests can still import the module shape


# Guide §3: BC's unitsPerMeter = 1.0 means the engine treats one game unit as
# one metre for doppler, regardless of the visual scale of the models (our GU is
# actually 175 m — see engine/units.py). Reproducing BC faithfully means adopting
# its convention rather than "correcting" it: raw GU in, 343.3 GU/s for c.
# alDopplerFactor stays the tuning knob if we ever want to.
SPEED_OF_SOUND_GU = 343.3


def node_world_position(node) -> Optional[tuple[float, float, float]]:
    """World (x, y, z) for a node ref, or None when it cannot be resolved.

    Coordinates MUST be real numbers. `TGObject.__getattr__` hands back a
    chainable `_Stub` for any unimplemented attribute; a stub coerces to 0.0,
    which would be indistinguishable from a legitimate world-origin position
    if we let it through. Returning None here is only half the guard: the
    caller (`TGSound.Play`) is what actually turns a None position into a
    genuinely non-positional source (`force_non_positional=True`) rather than
    falling through to a positional source at the backend's (0, 0, 0)
    default. This guard is the same one `TGSoundAction._node_position`
    documents — both call here now.
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
    # isinstance (not `type(c) in (int, float)`) is deliberate: it already
    # rejects the chainable _Stub (not a numeric subclass) while still
    # accepting bool, int/float subclasses, and numpy floats a real object
    # could legitimately return.
    if not all(isinstance(c, (int, float)) for c in (x, y, z)):
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
    """Copy every attached node's world position and velocity into its source.

    Velocity is the per-frame position delta (guide §4/§6), in raw game units
    per second. Called once per tick from host_loop.tick_audio, before the
    listener update so the positional math sees current source positions.

    Also reaps entries whose source already finished. A one-shot's C++
    AudioSystem source is reaped (`sources_.erase`) as soon as the backend
    reports it stopped, but nothing tells this Python-side pump; without this
    check every one-shot ever played (e.g. every phaser "Start" sound) would
    leave a permanent entry issuing a dead-pid set_position forever.
    """
    for pid, entry in list(_attached.items()):
        if not entry.handle._pid:          # explicitly stopped
            del _attached[pid]
            continue
        if _audio is not None and _audio.is_finished(pid):
            del _attached[pid]
            continue
        pos = node_world_position(entry.node)
        if pos is None:                    # owner GC'd or unresolvable
            del _attached[pid]
            continue
        entry.handle.SetPosition(*pos)
        if entry.prev_pos is not None and dt > 0.0:
            vx = (pos[0] - entry.prev_pos[0]) / dt
            vy = (pos[1] - entry.prev_pos[1]) / dt
            vz = (pos[2] - entry.prev_pos[2]) / dt
        else:
            vx = vy = vz = 0.0
        entry.handle.SetVelocity(vx, vy, vz)
        entry.prev_pos = pos


def reset_for_tests() -> None:
    _attached.clear()
