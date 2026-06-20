# Warp-Core Breach Explosion — Design

**Date:** 2026-06-20
**Status:** Approved, pending implementation plan
**Area:** Phase 2 combat / ship death

## Summary

When a ship's **Warp Core** subsystem condition crosses from a positive value to
**0**, the ship suffers a catastrophic warp-core breach: a massive explosion at
the core's world location that deals weapon-style hull damage — shields, hull,
per-subsystem splash, decals, sparks, and audio — to **every ship** within a
blast radius of roughly **10× a photon torpedo** (1.3 GU), with no allegiance
filter. The blast fires **immediately** at the crossing.

The breach trigger is keyed strictly to the **Warp Core reaching 0**, not to the
hull. Because the warp core is `Critical(1)` in every ship hardpoint, its
crossing to 0 also begins the normal death sequence — the two run in lockstep
but are wired independently.

To make hull destruction cascade into a breach (BC's "destroy broken systems"
behaviour, not yet present in the engine), this work also adds a **1.5-second
hull-death cascade**: when the hull reaches 0, after 1.5 s every subsystem is
zeroed, which drives the warp core across 0 and arms the breach.

## Motivation

Ship destruction in the current engine is a fixed 5-second throes window
(`engine/appc/ship_death.py`) plus cosmetic explosion puffs. There is no
secondary detonation, no chain reaction, and no gameplay consequence to a
destroyed ship's warp core. A warp-core breach makes a dying capital ship
genuinely dangerous to its surroundings and produces the cinematic domino
effect of clustered ships going up in sequence.

## Trigger semantics

The breach **arms** the instant a ship's Warp Core (`PowerSubsystem`) condition
crosses from `> 0` to `0` (the "0.01 → 0" transition). It arms **at most once
per ship**. Three paths reach that crossing, all funnelled through one hook:

- **Case A — direct core kill.** Damage drives the warp core to 0 while the hull
  may still have health. The breach arms immediately.
- **Case B — hull-death cascade.** The hull crosses to 0. After a **1.5 s**
  delay, every subsystem is set to 0 (via `DestroySystem`). The warp core's
  crossing during that cascade arms the breach.
- **Chain.** A breach's area-of-effect damage drives a *neighbour's* warp core
  to 0. That neighbour arms and breaches in turn. A neighbour killed by hull
  damage whose core survives does **not** breach.

A ship with **no** `PowerSubsystem` (`GetPowerSubsystem()` returns `None`) never
arms — small craft die normally.

## Components

### 1. `engine/appc/subsystem_cascade.py` (new)

The 1.5-second hull-death cascade. Public surface:

- `schedule(ship)` — register a cascade for `ship`, gated by SDK-faithful
  `ship.IsDestroyBrokenSystems()` (default **on** when the method is absent;
  honours a mission's `SetDestroyBrokenSystems(0)` escape hatch, e.g. derelicts
  in `Maelstrom/Episode3/E3M2`). Idempotent per ship.
- `advance(dt)` — tick all pending cascades. When a timer reaches 0, iterate
  the ship's subsystems and call `ship.DestroySystem(sub)` on each. Zeroing the
  warp core flows through the objects.py hook (below) and arms the breach.
- `reset()` — clear the registry (mission swap / test teardown).

Tunable: `CASCADE_DELAY = 1.5` (seconds).

Note: the cascade does **not** own ship removal — `ship_death` still runs the
5 s throes and removes the wreck. The cascade only zeroes subsystems during
that window.

### 2. `engine/appc/warp_core_breach.py` (new)

The breach itself. Public surface:

- `arm(ship)` — add `ship` to the armed queue if not already armed/breached.
  Idempotent via a per-ship guard set. This is the single-fire guarantee.
- `advance(dt, host=None, ship_instances=None)` — drain the armed queue in a
  **non-recursive while-loop**: pop an armed ship, `detonate(...)` it, mark it
  breached. Because detonation can arm further ships (chains), the loop
  continues until the queue is empty, so an entire chain resolves **in the same
  tick**. The guard set guarantees termination (each ship detonates once;
  finite ships).
- `detonate(ship, host, ship_instances)` — the blast (see below).
- `reset()` — clear the armed queue and breached set.

Detonation, centred at the warp core world position
(`subsystems.subsystem_world_position(core, ship)`):

- **Magnitude:** `BREACH_DAMAGE_FACTOR * core.GetMaxCondition()`, with
  `BREACH_DAMAGE_FACTOR = 1.0`. A 5000-condition core (Galaxy, Akira) deals
  5000 centre damage = 10× a photon's 500. `GetMaxCondition()` is read even
  though current condition is 0.
- **Radius:** `BREACH_RADIUS_GU = 1.3` — 10× the photon torpedo damage-radius
  factor (0.13 GU). Tunable.
- **Targets:** `ship_iter.iter_ships()`, skipping `ship` itself. For each
  target compute `d` = distance from the blast centre to
  `target.GetWorldLocation()`. Weight = `combat._splash_weight(target.GetRadius(),
  BREACH_RADIUS_GU, d)` — linear falloff, 1.0 at centre to 0 at the edge. Skip
  weight ≤ 0. **No allegiance filter** — player, allies, and enemies are all hit.
- **Per-target hit:** ray-trace from the blast centre toward the target hull to
  obtain an impact `point` and surface `normal` (same approach as
  `engine/appc/projectiles.py`, via `host.ray_trace_mesh` when available;
  fallback to a sphere-facing point with an approximate normal when headless).
  Then call:

  ```python
  combat.apply_hit(
      target, magnitude * weight, point,
      source=ship, normal=normal,
      host=host, ship_instances=ship_instances,
      weapon_type="torpedo",        # broad scorch decals
      splash_radius=BREACH_RADIUS_GU,
  )
  ```

  This reuses the entire weapon damage path: shield attenuation, full hull
  damage, per-subsystem splash, plus `hit_feedback` decals / sparks / audio.
- **VFX:** one large `ExplosionA` fireball at the core location (reusing the
  `Effects.CreateExplosionPuffHigh` helper as `ship_death._spawn_explosion`
  does). Size is a tunable factor of the ship radius. Raise-safe — VFX failure
  never blocks the damage path.

Tunables: `BREACH_DAMAGE_FACTOR`, `BREACH_RADIUS_GU`, fireball size factor.

### 3. `engine/appc/objects.py` (changed)

In `DamageSystem` and `DestroySystem`, after the condition is written, detect a
`> 0 → 0` crossing for the affected subsystem and route it:

- If the subsystem **is** `ship.GetPowerSubsystem()` → `warp_core_breach.arm(ship)`.
- If the subsystem **is** `ship.GetHull()` → `subsystem_cascade.schedule(ship)`.

Crossing detection: capture `cur = subsystem.GetCondition()` before writing;
the crossing fired when `cur > 0.0 and new_cond <= 0.0`. (Condition is floored
at 0, so once a core is at 0 a later damage call has `cur == 0` and cannot
re-arm — a second guard beyond the `arm()` set.)

The existing `_is_critical → ship_death.begin` logic is unchanged and continues
to fire for both hull and warp-core deaths.

### 4. `engine/appc/combat.py` (changed)

`apply_hit` gains an optional keyword `splash_radius: float | None = None`.
When supplied it overrides the resolved `r_hit` from
`weapon_splash_radius(...)`; when `None` (the default) behaviour is byte-for-byte
identical to today. The breach passes `splash_radius=1.3` so a target's
subsystems are splashed across the full blast radius.

### 5. `engine/host_loop.py` (changed)

In `_advance_combat(ships, dt, host, ship_instances)`:

- After weapon application **and** `ship_death.advance(dt)`, call
  `subsystem_cascade.advance(dt)` then
  `warp_core_breach.advance(dt, host, ship_instances)`. Ordering matters: both
  this-tick arm sources — weapon `apply_hit` and the cascade — must run before
  the breach drain so the breach fires the same tick the crossing occurs.
- Beside the existing `ship_death.reset()` (≈ host_loop.py:2076), add
  `subsystem_cascade.reset()` and `warp_core_breach.reset()`.

`host` and `ship_instances` are already in scope at the `ship_death.advance`
call site (host_loop.py:363), so no further threading is required.

## Control flow

```
Warp core condition > 0 → 0  (Case A direct, Case B cascade, or Chain)
        │  (objects.py DamageSystem/DestroySystem hook)
        ▼
warp_core_breach.arm(ship)        ship_death.begin(ship)  [critical, unchanged]
        │                                  │
        │  (next _advance_combat)          ▼  5 s throes, then removal
        ▼
warp_core_breach.advance() drains queue:
        detonate(ship): big fireball + AoE apply_hit to all ships in 1.3 GU
        │
        ├─ neighbour core → 0  → arm(neighbour) → drained same tick (chain)
        └─ neighbour hull → 0  → ship_death.begin + subsystem_cascade.schedule
                                   (breaches only if its core later reaches 0)
```

Hull-death path:

```
Hull condition > 0 → 0
        │  (objects.py hook, gated by IsDestroyBrokenSystems)
        ▼
subsystem_cascade.schedule(ship)   ship_death.begin(ship)  [critical, unchanged]
        │  +1.5 s
        ▼
subsystem_cascade.advance(): DestroySystem every subsystem
        │  (warp core crosses 0)
        ▼
warp_core_breach.arm(ship) → detonate (as above)
```

## Reentrancy & termination

- Arming never detonates synchronously inside a damage call; detonation happens
  only in `warp_core_breach.advance`, which drains via an explicit work-list
  loop. No stack recursion regardless of chain depth.
- The per-ship guard set means each ship detonates at most once. With a finite
  ship count the drain loop always terminates.
- Ship removal happens in `ship_death.advance` (5 s throes), never inside the
  breach drain, so `iter_ships()` is not mutated mid-detonation.

## Tunables (by feel, like `ship_death`)

| Constant | Value | Meaning |
|---|---|---|
| `subsystem_cascade.CASCADE_DELAY` | 1.5 s | Hull-0 → all-subsystems-0 delay |
| `warp_core_breach.BREACH_DAMAGE_FACTOR` | 1.0 | Centre damage = factor × core max condition |
| `warp_core_breach.BREACH_RADIUS_GU` | 1.3 | Blast radius (10× photon DRF 0.13) |
| fireball size factor | TBD by feel | Explosion VFX scale vs ship radius |

## Testing (TDD)

Unit tests mirroring `tests/unit/test_ship_death.py`, using fake
ships/cores/subsystems:

- Warp core crossing `> 0 → 0` arms the breach exactly once; a second damage
  call to the already-0 core does not re-arm.
- A ship with no `PowerSubsystem` never arms.
- Hull crossing to 0 schedules a cascade; `IsDestroyBrokenSystems()` returning 0
  suppresses it.
- After `CASCADE_DELAY`, the cascade zeroes every subsystem and arms the breach.
- Detonate applies falloff-scaled damage to ships in range; a ship just outside
  `BREACH_RADIUS_GU + radius` is untouched.
- Chain: a neighbour whose core is driven to 0 arms and breaches; a neighbour
  whose core survives (hull-only kill) does not breach.
- No allegiance filter: a friendly/player ship inside the radius is hit.
- `apply_hit(splash_radius=...)` overrides `r_hit`; omitting it leaves existing
  behaviour unchanged.
- Same-tick chain drain terminates (no infinite loop) and resolves a multi-ship
  chain within a single `advance`.

## Non-goals

- Debris fields, hull fragments, or shockwave-distortion VFX.
- Variable cascade timing per ship class (fixed 1.5 s for now).
- Tuning the magnitude/radius beyond the stated defaults (left as tunables).
- Physics impulse / knockback from the blast (damage only, matching the
  existing weapon model).

## Affected files

| File | Change |
|---|---|
| `engine/appc/subsystem_cascade.py` | New — 1.5 s hull-death subsystem cascade |
| `engine/appc/warp_core_breach.py` | New — arm/advance/detonate breach |
| `engine/appc/objects.py` | Hook core/hull `>0→0` crossings |
| `engine/appc/combat.py` | `apply_hit` gains `splash_radius` override |
| `engine/host_loop.py` | `_advance_combat` advance + reset wiring |
| `tests/unit/test_subsystem_cascade.py` | New tests |
| `tests/unit/test_warp_core_breach.py` | New tests |
| `tests/unit/test_combat_splash_radius_override.py` | New test |
