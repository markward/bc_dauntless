"""Damage-impact feedback dispatch.

Called from engine.appc.combat.apply_hit after damage is routed. Classifies
the impact into SHIELD / HULL / CRITICAL based on the per-stage absorbed
amounts and any subsystem state transition this tick, then fans out to the
mutually-exclusive visual (shield_hit OR hit_vfx.spawn), per-tier audio,
and (player-only) camera shake.

Severity rule (spec §3.1):
- CRITICAL iff a non-hull subsystem flipped state this tick.
- SHIELD iff shields absorbed > 0 and nothing else absorbed anything.
- HULL otherwise.

The WeaponHitEvent broadcast in apply_hit is unchanged; dispatch runs
before it, and dispatch failures are swallowed so a renderer-binding
crash never suppresses mission-side event handlers.
"""
import time
from enum import IntEnum


class Severity(IntEnum):
    SHIELD = 0
    HULL = 1
    CRITICAL = 2


def classify(*, absorbed_shields: float, absorbed_subsystem: float,
             absorbed_hull: float, sub_transition,
             subsystem, hull) -> Severity:
    """Pure function. Tested separately from dispatch."""
    if sub_transition is not None and subsystem is not None and subsystem is not hull:
        return Severity.CRITICAL
    if absorbed_shields > 0.0 and absorbed_subsystem == 0.0 and absorbed_hull == 0.0:
        return Severity.SHIELD
    return Severity.HULL


# Per-(ship_id, severity) audio edge-trigger.
# Reason: dispatch fires every weapon-impact tick (60Hz × N beams during
# continuous phaser fire). Without gating, each tick spawns a new
# positional source and OpenAL's 256-source cap is exhausted within
# seconds — plus a 60Hz impact loop reads as noise, not as feedback.
# Audio fires on the first tick of a contiguous burst: a gap exceeding
# _AUDIO_CONTACT_GAP_S since the previous dispatch on this (ship,
# severity) marks a fresh contact. Continuous fire updates the timestamp
# each tick but only plays once at the start of the burst.
_AUDIO_CONTACT_GAP_S = 0.15

_last_dispatch_time: dict[tuple[int, "Severity"], float] = {}


def reset_audio_throttle() -> None:
    """Clear the per-(ship, severity) edge-trigger state. Called by
    tests and by view-mode transitions.

    Name kept for callers that already imported it; semantics shifted
    from rate-limit to edge-trigger but the reset contract is unchanged.
    """
    _last_dispatch_time.clear()


def _audio_should_play(ship, severity: Severity) -> bool:
    """True iff this dispatch is the first tick of a fresh contact on
    (ship, severity). Every call updates the last-dispatch timestamp;
    audio fires only when the gap since the previous dispatch exceeded
    _AUDIO_CONTACT_GAP_S (continuous fire → silent ticks, burst-start
    → fresh play).
    """
    key = (id(ship), severity)
    now = time.monotonic()
    last = _last_dispatch_time.get(key)
    _last_dispatch_time[key] = now
    if last is None:
        return True   # first contact ever for this (ship, severity)
    return (now - last) >= _AUDIO_CONTACT_GAP_S


def dispatch(*, ship, source, point, normal, damage, subsystem,
             absorbed_shields: float, absorbed_subsystem: float,
             absorbed_hull: float, sub_transition,
             host=None, ship_instances=None) -> None:
    """Per-impact fan-out: VFX + audio + camera shake.

    Severity is computed via classify(...). Exactly one visual fires per
    impact (shield_hit for SHIELD, hit_vfx.spawn for HULL/CRITICAL).
    Audio fires for every severity. Camera shake fires only when
    ship == Game_GetCurrentGame().GetPlayer().

    Headless-safe: host=None silently skips shield_hit;
    App.g_kSoundManager=None silently skips audio.
    """
    # Deferred — engine.appc.hit_vfx imports Severity from this module,
    # so a module-level import here would be circular.
    from engine.appc import hit_vfx, camera_shake

    hull = ship.GetHull() if hasattr(ship, "GetHull") else None
    severity = classify(
        absorbed_shields=absorbed_shields,
        absorbed_subsystem=absorbed_subsystem,
        absorbed_hull=absorbed_hull,
        sub_transition=sub_transition,
        subsystem=subsystem,
        hull=hull,
    )

    # 1. Visual — mutually exclusive.
    if severity == Severity.SHIELD:
        if host is not None and ship_instances is not None \
                and hasattr(host, "shield_hit"):
            iid = ship_instances.get(ship)
            if iid is not None:
                # rgba=(0,0,0,0) is the documented sentinel that tells the
                # shield_pass to substitute the ship's registered
                # ShieldGlowColor — see host.shield_register's default_color.
                host.shield_hit(
                    instance_id=iid,
                    point=(point.x, point.y, point.z),
                    rgba=(0.0, 0.0, 0.0, 0.0),
                    intensity=1.0,
                )
    else:
        # HULL or CRITICAL — hit_vfx.spawn handles both, filtered by severity.
        hit_vfx.spawn(point, normal=normal, severity=severity)

    # 2. Audio — edge-triggered per (ship, severity). Plays once at
    # the start of a contiguous burst; subsequent ticks while the same
    # beam is hitting are silent. A fresh contact (gap exceeding
    # _AUDIO_CONTACT_GAP_S since the previous tick) re-arms the play.
    if _audio_should_play(ship, severity):
        _play_audio(severity, point)

    # 3. Camera shake — player only.
    try:
        import App
        game = App.Game_GetCurrentGame() if hasattr(App, "Game_GetCurrentGame") else None
        player = game.GetPlayer() if game is not None and hasattr(game, "GetPlayer") else None
    except Exception:
        player = None
    if player is not None and ship is player:
        camera_shake.apply_kick(float(damage))


def _play_audio(severity: Severity, point) -> None:
    """Look up the tier's sound name and play positionally. Silent on
    missing sound manager or missing sound name."""
    # Deferred so test imports of hit_feedback don't require App to be
    # loaded yet (matches the App shim's lazy-load pattern elsewhere).
    import App
    mgr = getattr(App, "g_kSoundManager", None)
    if mgr is None:
        return

    if severity == Severity.SHIELD:
        name = "Shield Hit"
    elif severity == Severity.HULL:
        try:
            import LoadTacticalSounds
            name = LoadTacticalSounds.GetRandomSound(
                LoadTacticalSounds.g_lsWeaponExplosions)
        except Exception:
            return
    else:  # CRITICAL
        try:
            import LoadDamageHitSounds
            picker = LoadDamageHitSounds.GetRandomSound
            if picker is None:
                # LoadSounds() hasn't run yet — fall back to first entry.
                name = LoadDamageHitSounds.g_lsSubsystemCriticals[0]
            else:
                name = picker(LoadDamageHitSounds.g_lsSubsystemCriticals)
        except Exception:
            return

    snd = mgr.GetSound(name)
    if snd is None:
        return
    snd.Play(position=(point.x, point.y, point.z))
