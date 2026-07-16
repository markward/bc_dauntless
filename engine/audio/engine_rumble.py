"""Per-ship engine rumble: looping 3D sound attached to each ship's scene node.

Hum START/STOP lifetime is owned by `engine.audio.hum_allocator` (guide §10 —
the nearest-≤4 allocator). This module now supplies the shared helpers the
allocator consumes (`_engine_sound_name_for`, `_node_for`, the near-field
distance constants) plus a teardown-only ship_lifecycle listener: a destroyed
ship's hum stops on the frame it dies rather than waiting for the allocator's
next reconcile.
"""
from __future__ import annotations

from engine.appc import ship_lifecycle


# Guide §5: the ship engine hum is the SOLE exception to BC's 50/700 default —
# the one C++ tuning call site in the original binary. The max of 35.0 is what
# makes the hum tight and near-field versus the 700-unit reach of weapons.
#
# Caveat: 4.375 is computed as 35.0 * 0.125 by a routine reachable only through
# a function pointer, so it could not be statically proven to run; if it does
# not, BC's real min is 0.0. The max is certain either way.
HUM_MIN_DISTANCE = 4.375
HUM_MAX_DISTANCE = 35.0


_installed = False
_unsubscribe = None


def _engine_sound_name_for(ship) -> str:
    sub_getter = getattr(ship, "GetImpulseEngineSubsystem", None)
    if sub_getter is None:
        return ""
    sub = sub_getter()
    if sub is None:
        return ""
    prop_getter = getattr(sub, "GetProperty", None)
    if prop_getter is None:
        return ""
    prop = prop_getter()
    if prop is None:
        return ""
    getter = getattr(prop, "GetEngineSound", None)
    return getter() if getter else ""


def _node_for(ship):
    getter = getattr(ship, "GetNode", None)
    return getter() if getter is not None else None


def _on_ship_event(event: str, ship) -> None:
    """Hum START/STOP is the allocator's job (guide §10 — nearest-≤4).

    This listener only handles teardown, so a destroyed ship's hum stops on the
    frame it dies rather than waiting for the next allocator reconcile.
    """
    if event == "destroyed":
        from engine.audio import hum_allocator
        hum_allocator._stop_hum(ship)


def install_engine_rumble_listener() -> None:
    """Idempotent install — safe to call from host_loop boot."""
    global _installed, _unsubscribe
    if _installed:
        return
    _unsubscribe = ship_lifecycle.subscribe(_on_ship_event)
    _installed = True


_muted = False


def set_muted(muted: bool) -> None:
    """Mute (gain 0) or unmute (gain 1) every humming source.

    Used by the bridge-view mode: from inside the bridge, the player wouldn't
    hear their own engine humming directly.

    Stopgap note: `SetClass::UpdateSounds` @0x00413CB0 gates on the global
    rendered-set pointer and flushes a non-rendered set's handles outright —
    that is the original's real mechanism, and `engine.audio.scene_scope`
    (guide §11) now reproduces it faithfully for space-to-space set changes
    (e.g. warp). BC has no per-source mute call; this function is OUR
    stopgap, predating scene_scope. It is NOT yet made redundant by
    scene_scope: host_loop drives scene_scope off `ship_iter.active_set()`,
    which tracks the player ship's own containing (space) set and does not
    change when the camera toggles to/from the bridge (the ship never leaves
    its space set just because the player is looking at the bridge). So the
    bridge-view case this function covers is still live. Kept because other
    call sites still depend on it — do not delete as part of unrelated work.
    """
    global _muted
    if _muted == muted:
        return
    _muted = muted
    from engine.audio import hum_allocator
    gain = 0.0 if muted else 1.0
    for playing in list(hum_allocator._humming.values()):
        if playing is not None:
            playing.SetGain(gain)


def reset_for_tests() -> None:
    global _installed, _unsubscribe, _muted
    _installed = False
    _muted = False
    if _unsubscribe is not None:
        _unsubscribe()
        _unsubscribe = None
