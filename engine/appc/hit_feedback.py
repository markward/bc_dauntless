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


# ── Spark-burst policy (transient impact VFX) ──────────────────────────────
# Sparks fire on a *heavy direct hit* (absorbed_hull magnitude) OR on any
# CRITICAL subsystem transition. Magnitude-based so a single torpedo clears
# the bar while per-tick phaser dribble does not. Policy lives here; the
# renderer only renders the count it is told.
SPARK_HULL_THRESHOLD = 80.0   # game-units of hull damage in one hit (tune-by-eye)

SPARK_KIND_PHASER = 0    # cool white-blue, fewer, tight cone
SPARK_KIND_TORPEDO = 1   # hot orange, more, wide cone (also disruptor/default)

_SPARK_BASE_COUNT = {SPARK_KIND_PHASER: 6, SPARK_KIND_TORPEDO: 12}
_SPARK_CRITICAL_MULT = 1.5


def _spark_kind_for(weapon_type) -> int:
    return SPARK_KIND_PHASER if weapon_type == "phaser" else SPARK_KIND_TORPEDO


def spark_params(*, weapon_type, severity, absorbed_hull):
    """Return (spark_count, spark_kind). count == 0 means no burst.

    Pure function, tested in isolation. `severity` is a Severity.
    """
    kind = _spark_kind_for(weapon_type)
    fire = (absorbed_hull >= SPARK_HULL_THRESHOLD) or (severity == Severity.CRITICAL)
    if not fire:
        return 0, kind
    count = _SPARK_BASE_COUNT[kind]
    if severity == Severity.CRITICAL:
        count = int(count * _SPARK_CRITICAL_MULT)
    return count, kind


# Decal-emission throttle. A continuous phaser beam ticks ~60x/s; emitting a
# decal every tick saturates the 24-slot per-instance ring, so decals are
# FIFO-evicted within ~0.3 s — before they can cool over T_GLOW. Cap to a few
# decals/sec per (ship, weapon class) so a beam leaves a short cooling trail.
DECAL_EMIT_INTERVAL = 0.2  # game-time seconds between decals per (ship, class)
_last_decal_emit: dict = {}  # (id(ship), weapon_class) -> last emit game-time

# Hull-carve emission throttle, parallel to _last_decal_emit. Keyed by
# id(ship) only (a carve is weapon-agnostic geometry, unlike a decal class).
_last_carve_time: dict = {}  # id(ship) -> last emit game-time


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
             host=None, ship_instances=None,
             weapon_type: str | None = None, radius: float = 0.0,
             persist_decal: bool = True) -> None:
    """Per-impact fan-out: VFX + audio + camera shake.

    Severity is computed via classify(...). Exactly one visual fires per
    impact (shield_hit for SHIELD, hit_vfx.spawn for HULL/CRITICAL).
    Audio fires for every severity. Camera shake fires only when
    ship == Game_GetCurrentGame().GetPlayer().

    Headless-safe: host=None silently skips shield_hit;
    App.g_kSoundManager=None silently skips audio.

    `weapon_type` is "phaser" / "torpedo" / None. Used by _play_audio to
    match SDK Effects.py semantics: phaser-on-shields is silent (stock BC
    has no PhaserShieldHit handler); torpedo-on-shields plays from
    g_lsWeaponExplosions (matching Effects.TorpedoShieldHit). HULL and
    CRITICAL fire regardless of weapon_type.
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
        # Spark policy + hull anchor (sparks are independent of decals).
        spark_count, weapon_kind = spark_params(
            weapon_type=weapon_type, severity=severity,
            absorbed_hull=absorbed_hull)
        body_point = body_normal = None
        instance_id = None
        # Bail to flash-only (no sparks) when any of: no host (headless),
        # no instance map, no surface normal (sphere-entry fallback), the
        # host can't convert, the ship has no instance, or the id is stale.
        # Sparks need a hull anchor; the impact-flash billboard fires regardless.
        if (spark_count > 0 and host is not None and ship_instances is not None
                and normal is not None and hasattr(host, "world_to_body")):
            instance_id = ship_instances.get(ship)
            if instance_id is not None:
                conv = host.world_to_body(
                    instance_id=instance_id,
                    world_point=(point.x, point.y, point.z),
                    world_normal=(normal.x, normal.y, normal.z))
                if conv is not None:
                    body_point, body_normal = conv
                else:
                    instance_id = None  # stale id; render flash only, no sparks
        # body_point is None unless the world->body conversion succeeded;
        # force spark_count=0 in every no-anchor path so the renderer never
        # anchors a burst at the default (0,0,0) body origin.
        hit_vfx.spawn(
            point, normal=normal, severity=severity,
            instance_id=instance_id, body_point=body_point,
            body_normal=body_normal, weapon_kind=weapon_kind,
            spark_count=(spark_count if body_point is not None else 0))

    # 2. Audio — edge-triggered per (ship, severity). Plays once at
    # the start of a contiguous burst; subsequent ticks while the same
    # beam is hitting are silent. A fresh contact (gap exceeding
    # _AUDIO_CONTACT_GAP_S since the previous tick) re-arms the play.
    if _audio_should_play(ship, severity):
        _play_audio(severity, point, weapon_type)

    # 3. Camera shake — player only, and only for hits the shields
    # didn't fully absorb. Shields-up impacts deflect the energy by
    # design; the bubble splash visual is the player cue.
    try:
        import App
        game = App.Game_GetCurrentGame() if hasattr(App, "Game_GetCurrentGame") else None
        player = game.GetPlayer() if game is not None and hasattr(game, "GetPlayer") else None
    except Exception:
        player = None
    if (player is not None and ship is player
            and severity != Severity.SHIELD):
        camera_shake.apply_kick(float(damage))

    # 4. Persistent damage decal — Phase 1 of persistent-damage-decals.
    # Emit ONLY when hull damage was actually dealt: a hit fully absorbed
    # by shields must NOT leave a scar (the shield-gating fix). Requires a
    # surface normal (mesh trace) for normal-aware falloff; sphere-entry
    # fallbacks (normal=None) are skipped.
    # `persist_decal` is False under god mode: the transient spark/shake above
    # still fire (severity is unchanged), but no permanent scar is written.
    if (persist_decal and absorbed_hull > 0.0 and normal is not None
            and host is not None and ship_instances is not None
            and hasattr(host, "damage_decal_add")):
        iid = ship_instances.get(ship)
        if iid is not None:
            from engine.appc import damage_decals
            now = damage_decals.current_game_time()
            wclass = damage_decals.weapon_class_for(weapon_type)
            key = (id(ship), wclass)
            if now - _last_decal_emit.get(key, -1e9) >= DECAL_EMIT_INTERVAL:
                _last_decal_emit[key] = now
                host.damage_decal_add(
                    instance_id=iid,
                    world_point=(point.x, point.y, point.z),
                    world_normal=(normal.x, normal.y, normal.z),
                    radius=float(radius) * damage_decals.decal_radius_scale(wclass),
                    intensity=damage_decals.decal_intensity(absorbed_hull),
                    weapon_class=wclass,
                    time=now,
                )

    # 5. Hull carve (breach): heavier than scorch; eligible ships only; throttled.
    # Same hull-absorbing, mesh-normal, renderer-present, committed-hit gating
    # as the decal, PLUS: the hit must clear MIN_CARVE_HULL and the target must
    # be damage-eligible (player + capped nearest/largest; see
    # engine.appc.damage_eligibility).
    if (absorbed_hull > 0.0 and normal is not None and persist_decal
            and host is not None and ship_instances is not None
            and hasattr(host, "hull_carve_add")):
        from engine.appc import hull_carve, damage_eligibility, damage_decals
        if (hull_carve.should_carve(absorbed_hull)
                and damage_eligibility.is_eligible(ship)):
            iid = ship_instances.get(ship)
            if iid is not None:
                now = damage_decals.current_game_time()
                ship_key = id(ship)
                if now - _last_carve_time.get(ship_key, -1e9) >= hull_carve.CARVE_EMIT_INTERVAL:
                    _last_carve_time[ship_key] = now
                    host.hull_carve_add(
                        iid,
                        (point.x, point.y, point.z),
                        (normal.x, normal.y, normal.z),
                        hull_carve.carve_radius_gu(radius),
                        now,
                    )


def _play_audio(severity: Severity, point, weapon_type: str | None = None) -> None:
    """Look up the tier's sound name and play positionally. Silent on
    missing sound manager or missing sound name.

    SDK semantics (Effects.py):
        SHIELD + phaser  → silent (no PhaserShieldHit handler exists)
        SHIELD + torpedo → g_lsWeaponExplosions (TorpedoShieldHit)
        SHIELD + None    → silent (safe default for unknown sources)
        HULL              → g_lsWeaponExplosions
        CRITICAL          → g_lsSubsystemCriticals (Project 4 extension)
    """
    # Deferred so test imports of hit_feedback don't require App to be
    # loaded yet (matches the App shim's lazy-load pattern elsewhere).
    import App
    mgr = getattr(App, "g_kSoundManager", None)
    if mgr is None:
        return

    if severity == Severity.SHIELD:
        if weapon_type != "torpedo":
            return
        try:
            import LoadTacticalSounds
            name = LoadTacticalSounds.GetRandomSound(
                LoadTacticalSounds.g_lsWeaponExplosions)
        except Exception:
            return
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
