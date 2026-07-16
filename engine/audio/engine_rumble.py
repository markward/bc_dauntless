"""Per-ship engine rumble: looping 3D sound attached to each ship's scene node.

Hooks into ship_lifecycle pub/sub; starts the sound on `added`, stops it on
`destroyed`. Approximates Appc's behavior where engine rumble auto-starts when
an ImpulseEngineProperty binds to a ship.
"""
from __future__ import annotations

import weakref

from engine.appc import ship_lifecycle
from engine.audio.tg_sound import TGSoundManager


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
# WeakKeyDictionary: if a ship is GC'd without publish_destroyed firing
# (e.g. a mission swap that nukes the set without explicit teardown),
# the entry vanishes and the looping AL source plays until
# shutdown_audio. Acceptable for current single-mission runs; future
# mission-swap paths should call publish_destroyed for each removed ship.
_active: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


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
    if event == "added":
        name = _engine_sound_name_for(ship)
        if not name:
            return
        snd = TGSoundManager.instance().GetSound(name)
        if snd is None:
            return
        snd.SetLooping(1)
        snd.SetSFX()
        snd.SetMinMaxDistance(HUM_MIN_DISTANCE, HUM_MAX_DISTANCE)
        playing = snd.Play(attach_node=_node_for(ship))
        if playing is not None:
            _active[ship] = playing
    elif event == "destroyed":
        playing = _active.pop(ship, None)
        if playing is not None:
            playing.Stop()


def install_engine_rumble_listener() -> None:
    """Idempotent install — safe to call from host_loop boot.

    Mission loading happens before init_audio() in host_loop, so by the time we
    subscribe, the `added` events for the player and AI ships have already
    fired with no listeners. Replay them from ship_lifecycle.snapshot() so
    rumble starts for everything currently live.
    """
    global _installed, _unsubscribe
    if _installed:
        return
    _unsubscribe = ship_lifecycle.subscribe(_on_ship_event)
    _installed = True
    # host_loop's mission load fires publish_added before init_audio
    # subscribes, so replay the current live set so rumble starts for
    # ships that are already on stage.
    for ship in ship_lifecycle.snapshot():
        _on_ship_event("added", ship)


_muted = False


def set_muted(muted: bool) -> None:
    """Mute (gain 0) or unmute (gain 1) every tracked engine-rumble source.

    Idempotent — repeat calls with the same value are no-ops. Used by the
    bridge-view mode: from inside the bridge, the player wouldn't hear
    their own engine humming directly.
    """
    global _muted
    if _muted == muted:
        return
    _muted = muted
    gain = 0.0 if muted else 1.0
    for ship, playing in list(_active.items()):
        if playing is not None:
            playing.SetGain(gain)


def reset_for_tests() -> None:
    global _installed, _unsubscribe, _muted
    _installed = False
    _muted = False
    _active.clear()
    if _unsubscribe is not None:
        _unsubscribe()
        _unsubscribe = None
