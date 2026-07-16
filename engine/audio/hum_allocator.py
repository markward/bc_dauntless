"""Nearest-≤4 engine-hum allocator (guide §10).

BC's most distinctive positional behaviour. Each frame, in the active space set:
take the listener position, gather ships that have an impulse-engine subsystem
(BC's gate is `ship+0x2CC != 0` — that field IS the ImpulseEngine subsystem, and
the hum is its sound), sort by distance, keep the nearest 4, and reconcile:
stop the hum on any ship that fell out, start one for any ship that entered.

The cap of 4 is deliberate voice economy from the original — keeping it is what
makes our ambient density match BC's.

The hum's sound NAME comes from the engine subsystem's property; the name carries
no distances and no gain, so the caller supplies BC's 4.375/35.0 (see engine_rumble).
"""
from __future__ import annotations

import weakref

from engine.audio import attached_sources
from engine.audio.engine_rumble import (
    HUM_MAX_DISTANCE, HUM_MIN_DISTANCE, _engine_sound_name_for, _node_for,
)
from engine.audio.tg_sound import TGSoundManager

# Guide §10: BC's cap. Tunable, but default 4 so the mix density matches.
MAX_HUMMING_SHIPS = 4

# ship -> _PlayingSound. Weak so a ship GC'd without an explicit teardown
# drops out rather than humming until shutdown.
_humming: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _roster():
    """Ships in the ACTIVE (rendered) set. Seam for tests."""
    from engine.appc.ship_iter import iter_active_ships
    return list(iter_active_ships())


def _distance_sq(ship, listener_pos) -> float:
    loc = attached_sources.node_world_position(ship)
    if loc is None:
        return float("inf")
    dx = loc[0] - listener_pos[0]
    dy = loc[1] - listener_pos[1]
    dz = loc[2] - listener_pos[2]
    return dx * dx + dy * dy + dz * dz


def _start_hum(ship) -> None:
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
        _humming[ship] = playing


def _stop_hum(ship) -> None:
    playing = _humming.pop(ship, None)
    if playing is not None:
        playing.Stop()


def update(listener_pos) -> None:
    """Reconcile the humming set against the nearest MAX_HUMMING_SHIPS."""
    candidates = [s for s in _roster() if _engine_sound_name_for(s)]
    candidates.sort(key=lambda s: _distance_sq(s, listener_pos))
    winners = candidates[:MAX_HUMMING_SHIPS]
    winner_ids = {id(s) for s in winners}

    for ship in [s for s in _humming.keys() if id(s) not in winner_ids]:
        _stop_hum(ship)
    for ship in winners:
        if ship not in _humming:
            _start_hum(ship)


def humming_ship_names() -> set:
    return {s.GetName() for s in _humming.keys()}


def reset_for_tests() -> None:
    for ship in list(_humming.keys()):
        _stop_hum(ship)
    _humming.clear()
