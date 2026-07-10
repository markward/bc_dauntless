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


def maybe_emit(ship, point, normal, weapon_type, ship_instances=None) -> None:
    """Emit a stock-faithful hull-hit smoke puff, or do nothing.

    `point` / `normal` are world-space TGPoint3 (`.x/.y/.z`); `weapon_type` is
    "torpedo" / "phaser" / None; `ship_instances` maps ship -> renderer instance
    id. No-op unless the weapon is a torpedo/phaser, the probability roll passes,
    detail level >= MEDIUM, and the impact resolves to a body-frame hull anchor.
    """
    threshold = _HULL_SMOKE_ROLL.get(weapon_type)
    if threshold is None:
        return
    if (particles.EffectController_GetEffectLevel()
            < particles.EffectController.MEDIUM):
        return
    if normal is None:
        return
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
