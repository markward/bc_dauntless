"""Bridge ambient loop: the "AmbBridge" 2D looping sound that plays
while the player is on the bridge.

Mirrors sdk/Build/scripts/LoadBridge.py:213-217 which sets
AmbBridge.SetLooping(1) and Play() at bridge load time. We start/stop
on view-mode toggle from host_loop's bridge-side-effects sync rather
than at load time, so the sound is silent in the space scene.
"""
from __future__ import annotations

from typing import Optional

from engine.audio.tg_sound import TGSoundManager, _PlayingSound


_playing: Optional[_PlayingSound] = None


def set_active(active: bool) -> None:
    """Start the bridge ambient loop if `active` and not yet playing;
    stop it if not `active`. Idempotent.

    On deactivate we also stop the AmbBridge sound directly (not just our own
    handle), so the SDK's load-time play at LoadBridge.py:213 — which runs in
    the space scene during mission load — goes silent off-bridge.
    """
    global _playing
    if active:
        if _playing is None:
            snd = TGSoundManager.instance().GetSound("AmbBridge")
            if snd is None:
                return
            snd.SetLooping(1)
            snd.SetSFX()
            _playing = snd.Play()  # non-positional (no attach_node)
    else:
        if _playing is not None:
            _playing.Stop()
            _playing = None
        snd = TGSoundManager.instance().GetSound("AmbBridge")
        if snd is not None:
            snd.Stop()  # kill any orphan handle (e.g. SDK load-time play)


def reset_for_tests() -> None:
    global _playing
    if _playing is not None:
        _playing.Stop()
    _playing = None
