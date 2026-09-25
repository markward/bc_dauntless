"""Nearest-≤4 engine-hum allocator (guide §10).

BC's most distinctive positional behaviour. Each frame, in the active space set:
take the listener position, gather ships that have an impulse-engine subsystem
(BC's gate is `ship+0x2CC != 0` — that field IS the ImpulseEngine subsystem, and
the hum is its sound), sort by distance, keep the nearest 4, and reconcile:
stop the hum on any ship that fell out, start one for any ship that entered.

The original caps this at 4; the reason is not established — keeping it is
what makes our ambient density match BC's.

The hum's sound NAME comes from the engine subsystem's property; the name carries
no distances and no gain, so the caller supplies BC's 4.375/35.0 (see engine_rumble).

Boundary hysteresis (`BOUNDARY_HYSTERESIS_FRACTION`, below) is OUR addition and
a deliberate divergence from BC. Without it, two ships hovering at near-equal
range at the #4/#5 cutoff (an ordinary combat formation) stop and restart their
looping hum from sample 0 every frame — an audible machine-gun artifact.

What the evidence actually says, and what it doesn't:
  - The decompiled `SetClass::UpdateSounds` (@0x00413CB0) shows a plain
    distance-sorted top-4 reconcile with **no deadband and no hysteresis**.
  - `SetClass::Update` (@0x0040ffb0, vtable slot 24) — which drives it — runs
    **once per frame** from the `UtopiaApp` main loop, the same cadence we run at.

So BC faced the identical thrash geometry and shipped without a guard. **We do not
know why it wasn't a problem there** — whether its proximity query gated candidates
by range first, whether restarting a voice was cheap enough to be inaudible under
Miles, or whether it simply was an artifact nobody logged. Do not invent a reason.
This constant is a Dauntless mitigation for an artifact we can hear; it is not
reproducing anything.
"""
from __future__ import annotations

import weakref

from engine.audio import attached_sources, engine_rumble
from engine.audio.engine_rumble import (
    HUM_MAX_DISTANCE, HUM_MIN_DISTANCE, _engine_sound_name_for, _node_for,
)
from engine.audio.tg_sound import TGSoundManager

# Guide §10: BC's cap. Tunable, but default 4 so the mix density matches.
MAX_HUMMING_SHIPS = 4

# Deliberate divergence from BC (see the module docstring's evidence note) — an incumbent
# already humming must be beaten by more than this fraction of squared
# distance before a challenger displaces it. 5% is small enough that a
# genuinely-closer ship still takes over promptly, but large enough to
# absorb ordinary per-frame jitter between two ships at similar range.
BOUNDARY_HYSTERESIS_FRACTION = 0.05

# ship -> _PlayingSound. Weak so the dict ENTRY drops when a ship is GC'd
# without an explicit teardown (e.g. a mission swap that tears down a set
# directly rather than going through ship_lifecycle.publish_destroyed — the
# dev mission picker's swap path does this). The entry dropping is NOT
# enough on its own to stop the looping AL source: nothing else would call
# Stop() on it, so it would hum forever, AND — because it no longer occupies
# a `_humming` slot — the allocator would happily start a 5th concurrent hum
# over it. `_start_hum` guards against that with `weakref.finalize`, which
# actually stops the source when the ship dies.
_humming: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _roster(listener_pos=None):
    """Ships in the VIEWED FRAME (system-frames plan 2 task 6 fix round 1) --
    every set sharing `frames.viewing_set()`'s frame, not the single
    `active_set()` SetClass. A sibling region of the same star system
    (Ona1/Ona2) shares one frame and must contribute hum candidates from
    BOTH sets regardless of which is rendered; a genuinely different frame
    (a left-behind system, or a space cutscene rendered somewhere the
    player's own ship is NOT) must not.

    This is also what keeps `_start_hum` from ever hitting `TGSound.Play`'s
    cross-frame refusal (see that function's own docstring) for a roster
    winner: a ship this function returns is, by construction, in a set whose
    frame equals `frames.viewing_set()`'s -- and `tick_audio` calls
    `scene_scope.set_active_frame(frames.frame_of(frames.viewing_set())...)`
    with that exact same `viewing_set()` value earlier in the SAME tick, so
    "the roster's frame" and "the active frame" a Play() call would gate on
    can never disagree. Before this fix, the roster was scoped to
    `active_set()` (always the PLAYER's own set) regardless of what was
    actually rendered, so a space cutscene pointed at another frame kept
    offering the player as a candidate every tick, `_start_hum` kept calling
    `Play()`, and `Play()` kept refusing it -- a real, wasted backend call
    every tick for the whole cutscene (see
    tests/audio/test_hum_allocator.py::
    test_player_hum_does_not_spin_during_a_cross_frame_cutscene, which
    proves ZERO such calls now, not merely that `_humming` stays empty).

    Falls back to iterating every set when no view can be determined at all
    (no player, no explicit rendered set) -- the same fallback
    `iter_active_ships` already had, preserved for load-time/headless-test
    boots with no game world yet
    (test_real_roster_finds_ship_via_iter_active_ships pins this). Seam for
    tests.

    With `listener_pos` (view coordinates), ships beyond HUM_MAX_DISTANCE of
    it are dropped (system-frames Plan 3 Task 3): a whole star system's
    regions are loaded at once, so the viewed frame routinely holds ships tens
    of thousands of GU away. See `_audible`."""
    import App
    from engine.appc.ships import ShipClass
    from engine.appc.ship_iter import iter_set_objects
    from engine.systems import frames
    view = frames.viewing_set()
    if view is None:
        sets = list(App.g_kSetManager._sets.values())
    else:
        sets = [pSet for pSet in App.g_kSetManager._sets.values()
                if frames.offset_between(view, pSet) is not None]
    out = []
    for pSet in sets:
        for obj in iter_set_objects(pSet):
            if isinstance(obj, ShipClass):
                out.append(obj)
    if listener_pos is not None:
        out = [s for s in out if _audible(_distance_sq(s, listener_pos))]
    return out


def _audible(dist_sq: float) -> bool:
    """Within HUM_MAX_DISTANCE of the listener.

    The hum is AL_INVERSE_DISTANCE_CLAMPED with max HUM_MAX_DISTANCE: past it
    the gain is pinned at its floor (ref/max = 0.125), so a ship out there is
    no quieter at 40 GU than at 40,000. Candidates beyond it would take a
    top-4 slot and hum at that floor from across the system; this gate is
    ours, not recovered BC behaviour (see the module docstring's note on
    what BC's own proximity query may have done)."""
    return dist_sq <= HUM_MAX_DISTANCE * HUM_MAX_DISTANCE


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
        # Stop the source when the ship dies even if nobody calls _stop_hum
        # (review finding #3 — see the `_humming` comment above). The
        # finalizer callback holds only `playing`, never `ship`, so it
        # cannot keep the ship alive or create a reference cycle.
        weakref.finalize(ship, playing.Stop)
        # Bridge mute (review finding #1): a ship entering the top-4 while
        # the player is on the bridge must start silent, not at gain 1.0.
        # This mirrors what set_muted() already does to EXISTING _humming
        # entries — without it, every top-4 boundary crossing during combat
        # re-breaks the bridge mute. See engine_rumble.set_muted's own
        # docstring for the caveat that this whole mechanism is a stopgap.
        if engine_rumble._muted:
            playing.SetGain(0.0)


def _stop_hum(ship) -> None:
    playing = _humming.pop(ship, None)
    if playing is not None:
        playing.Stop()


def update(listener_pos) -> None:
    """Reconcile the humming set against the nearest MAX_HUMMING_SHIPS.

    Selection applies BOUNDARY_HYSTERESIS_FRACTION in favour of ships already
    humming — see the module docstring's divergence note — so a stable-ish
    formation at the #4/#5 cutoff doesn't stop/restart every frame.
    """
    candidates = [(s, d) for s, d in
                  ((s, _distance_sq(s, listener_pos)) for s in _roster())
                  if _audible(d) and _engine_sound_name_for(s)]
    # Liveness (`_PlayingSound.is_live`), not mere dict-key presence or a
    # bare `_pid` truthiness check (review Critical #1): a humming ship's
    # source can go dead two ways this registry cannot see on its own --
    # (a) a scene switch (scene_scope.set_active_frame) can Stop() it
    # directly, out from under this registry, in the SAME tick BEFORE this
    # call runs (host_loop.tick_audio's ordering). On an ordinary warp the
    # player's own ship stays a roster member of the newly-active frame
    # (`_roster()` is scoped to `frames.viewing_set()`'s frame, and the
    # player's own containing set defines that frame absent an in-space
    # cutscene pointed elsewhere -- see `_roster`'s own docstring for the
    # cutscene case, which this fix keeps the player OUT of the roster for
    # instead), so on every warp the player's own hum handle is dead by the
    # time we get here. (b) `AudioSystem::play`'s pool-saturation
    # eviction can steal ANY playing source -- including a looping hum -- by
    # erasing it from the C++ `sources_` map without ever zeroing this
    # handle's Python-side `_pid`; a `_pid`-only check (the bug this
    # replaced) cannot see that and leaves the ship humming silently forever,
    # since it never falls out of `_humming` and is therefore never
    # restarted. A bare `id(s) for s in _humming.keys()` check would still
    # see the dict key and treat either case as "already humming", so it
    # would never be restarted. Calling `is_live()` here both restarts a
    # dead-handle survivor below and correctly denies it the hysteresis
    # bonus (a dead handle is not a real incumbent).
    humming_ids = {id(s) for s in _humming.keys()
                   if _humming[s] is not None and _humming[s].is_live()}

    def _sort_key(pair):
        ship, dist_sq = pair
        if id(ship) in humming_ids:
            dist_sq *= (1.0 - BOUNDARY_HYSTERESIS_FRACTION)
        return dist_sq

    candidates.sort(key=_sort_key)
    winners = [s for s, _ in candidates[:MAX_HUMMING_SHIPS]]
    winner_ids = {id(s) for s in winners}

    for ship in [s for s in _humming.keys() if id(s) not in winner_ids]:
        _stop_hum(ship)
    for ship in winners:
        if id(ship) not in humming_ids:
            _start_hum(ship)


def humming_ship_names() -> set:
    return {s.GetName() for s in _humming.keys()}


def reset_for_tests() -> None:
    for ship in list(_humming.keys()):
        _stop_hum(ship)
    _humming.clear()
