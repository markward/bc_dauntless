"""Developer-only console readout for the engine-hum audio geometry.

Part 2 of the exterior-audio-fidelity live-verification pass: the user
reported no perceptible volume shift or doppler from NPC engine hums (or
torpedoes) as ships pass. The hum machinery is provably correct in
isolation -- position tracking and the doppler-cents math both check out
against a probed 20 GU/s closing speed (~104 cents) -- but nobody has
confirmed the REAL in-game geometry: in particular whether any ship ever
gets inside HUM_MAX_DISTANCE (35.0 GU / 6.12 km) before the
AL_INVERSE_DISTANCE_CLAMPED gain floors at ref/max = 0.125 and simply stops
changing no matter how far the source recedes beyond that.

This module is a DIAGNOSTIC, not a fix: it prints the live numbers once a
second so a --developer session can settle the question instead of guessing.

Toggle: F8 (registered in engine/dev_keybindings.py) while the process was
launched with --developer. Off by default. `maybe_report`'s very first line
is two cheap bool checks (`_enabled`, `dev_mode.is_enabled()`) with no
further work when either is false -- so this stays out of the 60 Hz hot path
both in production (--developer absent) and, by default, even under
--developer until a developer explicitly asks for it with F8.
"""
from __future__ import annotations

import math

from engine import dev_mode, units

# ── state ────────────────────────────────────────────────────────────────
_enabled = False
_accum_s = 0.0
REPORT_PERIOD_S = 1.0

# ship-identity -> (x, y, z) at the last report tick, for the diagnostic's
# own (coarse, ~1s-averaged) speed estimate. Deliberately separate from
# attached_sources' own per-frame prev_pos bookkeeping -- this module must
# not perturb the real audio pipeline's state, only observe it.
_prev_positions: dict = {}


def is_enabled() -> bool:
    return _enabled


def toggle() -> None:
    """Flip the readout on/off. Bound to F8 by dev_keybindings.py."""
    global _enabled, _accum_s
    _enabled = not _enabled
    _accum_s = 0.0
    _prev_positions.clear()
    print("[hum-diag] %s" % ("ON" if _enabled else "OFF"))


def reset_for_tests() -> None:
    global _enabled, _accum_s
    _enabled = False
    _accum_s = 0.0
    _prev_positions.clear()


# ── pure math (unit-tested directly) ────────────────────────────────────

def gain_for_distance(dist_gu: float) -> tuple[float, bool]:
    """AL_INVERSE_DISTANCE_CLAMPED, rolloff 1.0, using the hum's own
    ref/max (engine_rumble.HUM_MIN_DISTANCE / HUM_MAX_DISTANCE):

        d' = clamp(d, ref, max);  gain = ref / (ref + rolloff * (d' - ref))

    Returns (gain, past_floor) -- past_floor is True once dist_gu exceeds
    HUM_MAX_DISTANCE, the point beyond which gain is pinned and stops
    responding to further distance at all.
    """
    from engine.audio.engine_rumble import HUM_MIN_DISTANCE, HUM_MAX_DISTANCE
    ref, mx = HUM_MIN_DISTANCE, HUM_MAX_DISTANCE
    clamped = max(ref, min(dist_gu, mx))
    gain = ref / (ref + (clamped - ref))
    return gain, dist_gu > mx


def doppler_cents(speed_gu_s: float) -> float:
    """Cents of pitch shift a source moving at `speed_gu_s` would impart
    at OpenAL's default doppler factor: 1200 * log2(c / (c - v)).

    `speed_gu_s` is a raw scalar speed, not a radial (line-of-sight)
    projection -- this is a diagnostic estimate, not the exact per-axis
    doppler OpenAL computes internally. OUR reading of the design brief's
    probe result (20 GU/s -> ~104 cents) reproduces exactly with this
    formula and SPEED_OF_SOUND_GU as c, which is why it's used here; BC
    itself has no documented engine-hum doppler behaviour to compare against.
    """
    from engine.audio.attached_sources import SPEED_OF_SOUND_GU
    v = abs(speed_gu_s)
    if v <= 0.0 or v >= SPEED_OF_SOUND_GU:
        return 0.0
    return 1200.0 * math.log2(SPEED_OF_SOUND_GU / (SPEED_OF_SOUND_GU - v))


def _speed_gu_s(key, pos, elapsed_s: float) -> float:
    """(x, y, z) delta since this key's last report, divided by the elapsed
    real report interval -- a coarse ~1s-averaged speed, not the per-frame
    velocity attached_sources.pump feeds the backend."""
    prev = _prev_positions.get(key)
    _prev_positions[key] = pos
    if prev is None or elapsed_s <= 0.0:
        return 0.0
    dx = pos[0] - prev[0]
    dy = pos[1] - prev[1]
    dz = pos[2] - prev[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz) / elapsed_s


# ── report ───────────────────────────────────────────────────────────────

def maybe_report(*, listener_pos, player, dt: float) -> None:
    """Throttled (~once/second) console readout of the current hum geometry.

    Called every tick from host_loop.tick_audio; the throttle + the
    is_enabled()/`_enabled` gate mean the real per-ship work below only
    runs roughly once a second, and never at all unless a developer turned
    the F8 toggle on.
    """
    if not _enabled or not dev_mode.is_enabled():
        return

    global _accum_s
    _accum_s += dt
    if _accum_s < REPORT_PERIOD_S:
        return
    elapsed = _accum_s
    _accum_s = 0.0

    from engine.audio import attached_sources, hum_allocator

    lx, ly, lz = listener_pos
    print("[hum-diag] listener=(%.2f, %.2f, %.2f) GU" % (lx, ly, lz))

    player_loc = (attached_sources.node_world_position(player)
                  if player is not None else None)
    if player_loc is not None:
        dx = player_loc[0] - lx
        dy = player_loc[1] - ly
        dz = player_loc[2] - lz
        player_dist_gu = math.sqrt(dx * dx + dy * dy + dz * dz)
        print("[hum-diag] player ship dist=%.2f GU (%.4f km)" % (
            player_dist_gu, player_dist_gu * units.GU_TO_KM))

    for ship, _playing in list(hum_allocator._humming.items()):
        loc = attached_sources.node_world_position(ship)
        if loc is None:
            continue
        dx = loc[0] - lx
        dy = loc[1] - ly
        dz = loc[2] - lz
        dist_gu = math.sqrt(dx * dx + dy * dy + dz * dz)
        gain, past_floor = gain_for_distance(dist_gu)
        speed = _speed_gu_s(id(ship), loc, elapsed)
        cents = doppler_cents(speed)
        name = ship.GetName() if hasattr(ship, "GetName") else "<ship>"
        marker = "  <- PLAYER" if ship is player else ""
        print(
            "[hum-diag]   %-24s dist=%7.2f GU (%.4f km)  gain=%.4f%s  "
            "speed=%6.2f GU/s  doppler=%6.1f cents%s" % (
                name, dist_gu, dist_gu * units.GU_TO_KM, gain,
                " [PAST 35 GU FLOOR]" if past_floor else "",
                speed, cents, marker,
            )
        )
