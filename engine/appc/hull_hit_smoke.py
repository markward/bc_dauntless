# engine/appc/hull_hit_smoke.py
"""SDK-faithful hull-hit smoke puffs.

Reproduces stock BC's `Effects.TorpedoHullHit` / `PhaserHullHit` smoke: a small,
transient smoke puff at a weapon's hull-impact point, emitted probabilistically
and gated on graphics-detail level. This is deliberately NOT continuous,
subsystem-state-driven, or ship-centred — that was the removed
`subsystem_emitters` plume system.

Constants are copied verbatim from `sdk/Build/scripts/Effects.py`
(`CreateWeaponSmoke` -> `CreateSmokeHigh`). See
docs/superpowers/specs/2026-07-09-hull-hit-smoke-faithful-design.md.
"""
import App
from engine import host_io
from engine.appc import particles

# Stock rolls (Effects.py): torpedo 20% (rand(10) < 2), phaser 30% (rand(10) < 3).
_HULL_SMOKE_ROLL = {"torpedo": 2, "phaser": 3}

# ── Beam throttle ──────────────────────────────────────────────────────────
# Stock's PhaserHullHit is an ET_WEAPON_HIT handler, so it rolls once per
# hull-hit EVENT. BC's beams apply damage in 0.5 s pulses (stbc_reference
# spec/ShieldFacingDamage.md, graded reviewed-not-tested), giving ~2 rolls/s
# per firing beam. Our beams apply damage — and therefore dispatch — every
# tick (host_loop's per-frame weapon loop calls combat.apply_hit with
# _phaser_damage_for_tick), so the same 30% roll ran 60x/s: 18 emitters/s
# where stock gets 0.3. Each one lives 10.3 s emitting 30 concurrent puffs, so
# ~210 emitters pile up and — being world-space (see _emit_smoke) — smear into
# a permanent gas stream along the ship's flight path.
#
# Restore stock's EVENT rate by rolling at most once per interval per
# (target, attacker) pair. Per-pair, not per-target: each attacker's beam is
# its own pulse train in stock, so five ships beaming one hull must produce
# five times the smoke.
#
# Torpedoes are NOT throttled — they already dispatch once per discrete
# impact, which is exactly stock's event rate. Throttling them would eat
# salvo hits that stock renders.
SMOKE_EMIT_INTERVAL = 0.5   # game-time seconds between rolls per (target, source)
_THROTTLED_WEAPONS = ("phaser",)
_last_smoke_roll: dict = {}  # (id(ship), id(source)) -> last roll game-time


def _now() -> float:
    """Game-time seconds, shared with the decal/carve throttles so smoke
    freezes under pause instead of accumulating on wall-clock."""
    from engine.appc import damage_decals
    return damage_decals.current_game_time()


def reset() -> None:
    """Drop the per-pair throttle state (mission swap / tests)."""
    _last_smoke_roll.clear()


def maybe_emit(ship, point, normal, weapon_type, ship_instances=None,
               source=None) -> None:
    """Emit a stock-faithful hull-hit smoke puff, or do nothing.

    `point` / `normal` are world-space TGPoint3 (`.x/.y/.z`); `weapon_type` is
    "torpedo" / "phaser" / None; `ship_instances` maps ship -> renderer instance
    id; `source` is the firing ship, used only to key the beam throttle. No-op
    unless the weapon is a torpedo/phaser, the beam throttle allows a roll, the
    probability roll passes, detail level >= MEDIUM, and the impact resolves to
    a body-frame hull anchor.
    """
    threshold = _HULL_SMOKE_ROLL.get(weapon_type)
    if threshold is None:
        return
    if (particles.EffectController_GetEffectLevel()
            < particles.EffectController.MEDIUM):
        return
    if normal is None:
        return
    # BEFORE the roll, deliberately: a throttled tick must not consume a draw.
    # Rolling first and throttling after would emit on nearly every interval
    # (60 ticks x 30% always produces a winner) instead of on 30% of them,
    # which is a different — and much hotter — distribution than stock's.
    if weapon_type in _THROTTLED_WEAPONS:
        key = (id(ship), id(source))
        now = _now()
        if now - _last_smoke_roll.get(key, -1e9) < SMOKE_EMIT_INTERVAL:
            return
        _last_smoke_roll[key] = now
    if App.g_kSystemWrapper.GetRandomNumber(10) >= threshold:
        return
    iid = ship_instances.get(ship) if ship_instances is not None else None
    if iid is None:
        return
    conv = host_io.world_to_body(
        iid, (point.x, point.y, point.z), (normal.x, normal.y, normal.z))
    if conv is None:
        return
    body_point, body_normal = conv
    _emit_smoke(ship, body_point, body_normal)


def _emit_smoke(ship, body_point, body_normal) -> None:
    """Fire the SDK CreateSmokeHigh recipe (Effects.py fSize=0.3 hull puff).

    The emitter is body-frame anchored to the ship, so it tracks the impact point
    on the moving hull; the puffs themselves are released into WORLD space, so a
    moving ship leaves a trail rather than carrying the cloud with it.

    Stock expresses that split by emitting from the ship node (`pEmitFrom`) while
    attaching the particle geometry to the set's world-space effect root
    (`pAttachTo = pSet.GetEffectRoot()`). Our particle pass has no attach-root
    concept: it encodes "particle lives in world space" as `inherit == 0`, which
    enables the `- emit_vel_world * (1 - inherit) * age` back-projection in
    particle_pass.cc. CreateSmokeHigh's own `SetInheritsVelocity(1)` cancels that
    term and pins every puff to the ship's current transform, so override it.
    """
    import Effects
    fLife = 2.0 + App.g_kSystemWrapper.GetRandomNumber(30) / 10.0
    action = Effects.CreateSmokeHigh(
        0.2, fLife, 0.3, ship, body_point, body_normal, ship)
    action.GetController().SetInheritsVelocity(0)
    action.Start()
