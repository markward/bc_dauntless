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
    prop_getter = getattr(ship, "GetImpulseEngineProperty", None)
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
    """Idempotent install — safe to call from host_loop boot."""
    global _installed, _unsubscribe
    if _installed:
        return
    _unsubscribe = ship_lifecycle.subscribe(_on_ship_event)
    _installed = True


def reset_for_tests() -> None:
    global _installed, _unsubscribe
    _installed = False
    _active.clear()
    if _unsubscribe is not None:
        _unsubscribe()
        _unsubscribe = None
