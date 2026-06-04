# Deferred: don't fire phasers at out-of-range targets

**Status:** RESOLVED 2026-06-02 on `feature/damage-vfx-bridge-feedback`, then **revised 2026-06-04**. Neither Option 1 nor Option 2 turned out to match BC. The stock game uses a **single engine-wide constant** for the fire gate (`PHASER_MAX_RANGE_GU = 700 GU ≈ 122.5 km`), independent of any bank's `MaxDamageDistance`. `MaxDamageDistance` controls inverse-square damage falloff shape only. See [`docs/original_game_reference/gameplay/combat-and-damage.md`](../../original_game_reference/gameplay/combat-and-damage.md#phaser-fire-range-vs-damage-falloff) and [`engine/appc/subsystems.py:PHASER_MAX_RANGE_GU`](../../../engine/appc/subsystems.py). Prior text below kept for archaeology.

**Original status:** deferred 2026-05-18.  PR 2c lets the player fire phasers at
any target the lock accepts, regardless of distance.  We render the
beam but `_phaser_damage_for_tick` returns 0 once `dist >= MaxDamageDistance`,
so the bank just discharges its capacitor for no effect.  As a stopgap
the renderer now clips the *visible* beam to `MaxDamageDistance` so it
doesn't draw a 400 wu pixel-thin line into the distance.

## Desired end state

When the player triggers phaser fire (`LBUTTON`) and the locked target
is **beyond `MaxDamageDistance`** for every otherwise-eligible bank,
the system should refuse to engage instead of:

- Draining the bank's charge for no damage.
- Playing the `Galaxy Phaser Start` + `Galaxy Phaser Loop` SFX.
- Drawing a clipped beam segment in the target's direction.

Plausible UX: a soft "out of range" tone (BC has dedicated sounds in
`LoadTacticalSounds.py`), no beam, no charge drain.  Same gate applies
to held-fire retries — they should not re-fire when the target is out
of range, even if a bank's recharge re-arms it.

## Why this is non-trivial

Per-bank range can differ (different MaxDamageDistance on each phaser
property), but BC presents weapons as a "system" group.  Two options:

1. Take the **maximum** `MaxDamageDistance` across the system's banks
   as the system-level range gate.  If the target is beyond that, fire
   nothing.  Otherwise pass to the existing alert/arc/charge gates,
   and let in-range banks fire while out-of-range banks skip.
2. Track an explicit per-system `WG_RANGE` on `PhaserSystem` and let
   bank-level gates handle the per-bank cutoff for free.

Option (1) is simpler but conservative — a phaser with a longer reach
than the others gets gated by the *fleet* minimum.  Option (2) requires
adding range to the arc/charge gate path but matches what BC does.

## Where the fix lands

- `engine/appc/subsystems.py:PhaserSystem.StartFiring` — early-out if
  the target is beyond range.
- `engine/appc/subsystems.py:PhaserSystem.retry_held_fire` — same gate.
- Optional: `engine/appc/subsystems.py:_emitter_in_arc` could grow a
  range cutoff so torpedoes can also gate by range when they grow a
  matching limit.

Bonus: the `Audio` follow-up should hook up the "phaser-system tone"
indicating "trigger pressed but nothing engaged" (probably a brief
deny click) so the player gets feedback that the trigger registered.

## Why deferred

PR 2c is shipping with player-side phasers working at engagement
ranges; the range-gate omission is a polish issue that only shows up
when the player keeps firing at far-away targets.  The renderer-side
clip stops the worst symptom (sub-pixel beam) without changing combat
behaviour.

## Related work

- [`docs/superpowers/specs/2026-05-14-phaser-combat-design.md`](../specs/2026-05-14-phaser-combat-design.md) — PR 2c spec.
- [`docs/instrumented_experiments/2026-05-15-damage-routing-investigation.md`](../../instrumented_experiments/2026-05-15-damage-routing-investigation.md)
  — once the routing instrumentation captures BC's actual range behaviour
  we'll know whether option (1) or (2) is correct.
