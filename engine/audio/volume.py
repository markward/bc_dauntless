"""The one owner of the audio channel gains and the Doppler switch.

Two things want a say in a channel's gain: the Audio settings tab (a 0-100
level per channel) and the boot notice, which mutes everything while the game
loads behind it. If both called set_category_gain, the unmute would have to
guess what to restore. Here they don't: the levels and the mute are kept, and
the gain each channel gets is worked out from both.

Channels are the native audio categories: "Music" (the music player),
"Voice" (crew lines, hails, cutscene dialogue), "SFX" (everything in the
world) and "Interface" (the settings tab's "UI" row: menu and button sounds).

3D audio off switches off Doppler pitch shift only. Panning and distance
falloff stay, so the player still hears where a sound is and how far away.

Session state, not mission state: a mission swap must keep the player's
levels, so this is NOT in host_loop.reset_mission_state. Tests reset it with
reset() (tests/conftest.py).
"""
from __future__ import annotations

CHANNELS = ("Music", "Voice", "SFX", "Interface")
LEVEL_MIN = 0
LEVEL_MAX = 100

_levels = {c: LEVEL_MAX for c in CHANNELS}
_muted = False
_3d_enabled = True
_audio = None          # the native audio module, once the backend is up


def gain_for_level(level: int) -> float:
    """0-100 slider position -> linear gain, on a square-law curve.

    A straight line puts half the bar at -6 dB, which sounds barely quieter
    than full, and squeezes all the audible change into the bottom of the bar.
    The square puts half the bar at -12 dB, close to "half as loud"."""
    return (level / LEVEL_MAX) ** 2


def attach(audio_mod) -> None:
    """Hand over the live audio module (after its backend init). A fresh
    backend starts at full gain with Doppler on, so push the whole state."""
    global _audio
    _audio = audio_mod
    _push_all()


def reset() -> None:
    """Back to defaults with no backend attached. Tests only. The attached
    backend (if any) is handed the defaults first, so a test cannot leave the
    shared null backend quieter for the next one."""
    global _levels, _muted, _3d_enabled, _audio
    _levels = {c: LEVEL_MAX for c in CHANNELS}
    _muted = False
    _3d_enabled = True
    _push_all()
    _audio = None


def level(channel: str) -> int:
    return _levels[channel]


def set_level(channel: str, value) -> None:
    if channel not in _levels:
        raise KeyError(channel)
    _levels[channel] = max(LEVEL_MIN, min(LEVEL_MAX, int(value)))
    _push(channel)


def set_muted(muted: bool) -> None:
    global _muted
    _muted = bool(muted)
    for channel in CHANNELS:
        _push(channel)


def set_3d_enabled(on: bool) -> None:
    global _3d_enabled
    _3d_enabled = bool(on)
    if _audio is not None:
        _audio.set_doppler_enabled(_3d_enabled)


def _push(channel: str) -> None:
    if _audio is None:
        return
    gain = 0.0 if _muted else gain_for_level(_levels[channel])
    _audio.set_category_gain(channel, gain)


def _push_all() -> None:
    for channel in CHANNELS:
        _push(channel)
    if _audio is not None:
        _audio.set_doppler_enabled(_3d_enabled)
