"""Per-ship engine rumble: looping 3D sound attached to each ship's scene node.

Hooks into ship_lifecycle pub/sub; starts the sound on `added`, stops it on
`destroyed`. Approximates Appc's behavior where engine rumble auto-starts when
an ImpulseEngineProperty binds to a ship.
"""
from __future__ import annotations

import weakref

from engine.appc import ship_lifecycle
from engine.audio.tg_sound import TGSoundManager


_installed = False
_unsubscribe = None
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


def _scene_node_for(ship) -> int:
    getter = getattr(ship, "GetSceneNodeId", None)
    return int(getter()) if getter else 0


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
        playing = snd.Play(attach_node=_scene_node_for(ship))
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


def update_positions() -> None:
    """Push each tracked ship's world position to its rumble source.

    Called per tick from host_loop.tick_audio. Real ships have
    GetWorldLocation() returning a vec3 with .x/.y/.z attributes.
    """
    for ship, playing in list(_active.items()):
        loc_getter = getattr(ship, "GetWorldLocation", None)
        if loc_getter is None:
            continue
        try:
            loc = loc_getter()
        except Exception:
            continue
        if loc is None:
            continue
        x = getattr(loc, "x", None)
        y = getattr(loc, "y", None)
        z = getattr(loc, "z", None)
        if x is None or y is None or z is None:
            continue
        playing.SetPosition(float(x), float(y), float(z))


def reset_for_tests() -> None:
    global _installed, _unsubscribe
    _installed = False
    _active.clear()
    if _unsubscribe is not None:
        _unsubscribe()
        _unsubscribe = None
