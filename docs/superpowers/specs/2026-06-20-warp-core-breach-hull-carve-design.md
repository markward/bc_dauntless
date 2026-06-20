# Warp-Core Breach Hull Carve — Design

**Date:** 2026-06-20
**Status:** Approved, pending implementation plan
**Area:** Phase 2 — warp-core breach VFX / voxel hull-carve

## Summary

When a ship's warp core breaches, blow **one big hole through its hull from the
warp core outward** — a single large voxel carve centered at the warp core that
exposes the ship's interior, growing over ~1.5 s as the core goes critical. The
exploding ship is currently the one ship its own blast never touches (the breach
AoE skips the source); this adds the dramatic self-destruction the player
expects to see on the wreck.

Pure Python: it reuses the existing `host.hull_carve_add(...)` binding and the
existing breach render pass. **No native/C++/shader changes, no rebuild.**

## Motivation

The voxel hull-carve system is fully wired (weapon hits carve via
`hit_feedback`), but `warp_core_breach.detonate` skips the source ship
(`if target is ship: continue`), so the ship whose core breaches never shows
hull damage from the event. The player watches the ship that exploded and sees
no breach. This carves that ship directly.

## Decisions (locked during brainstorming)

| Aspect | Decision |
|---|---|
| What | **One BIG breach at the warp core** on the exploding ship (not a scatter of holes — that's deferred) |
| Size | Large, tunable: radius ≈ **0.7 × ship radius** (`ship.GetRadius()`, GU) |
| Growth | **Grows over ~1.5 s** (ease-out) so the hole tears open in step with the shockwave |
| Gate | **Bypasses** the weapon-hit gate (no eligibility / throttle / ≥60-damage) — a breach always carves its ship |
| Scope deferred | The earlier "ripped apart, many distributed breaches" idea is a later layer on top of this |

## Why a core-centered carve needs no ray-cast

The warp core sits **inside** the hull. A carve sphere centered at the core
world position with a large radius intersects the hull from the inside, punching
a hole and exposing the interior — exactly the "breach from the core" read. So
unlike a weapon hit (a surface point found by mesh trace), this carve is placed
at the core, not on the surface, and needs no `ray_trace_mesh`. The carve's
world-normal (used only for rim orientation) is the direction from the ship
centre through the core (`normalize(core_world − ship_world_loc)`), falling back
to the ship's up axis (`GetWorldRotation().GetCol(2)`) when the core is at the
centre.

## Architecture

### `engine/appc/core_breach_carve.py` (new)

A small registry of in-progress core-breach carves, advanced each tick.

- `GROW_DURATION = 1.5` — seconds the hole grows to full size.
- `MAX_RADIUS_SHIP_FRACTION = 0.7` — full carve radius as a fraction of
  `ship.GetRadius()`.
- `MIN_RADIUS_GU = 0.1` — floor so the first growing frame is visible.
- `schedule(ship)` — register `{ship, age: 0.0}` (idempotent per ship). No-op if
  the ship has no `GetPowerSubsystem()`.
- `advance(dt, host, ship_instances)` — for each entry:
  - `age += dt`; `t = min(1.0, age / GROW_DURATION)`.
  - Resolve `iid = ship_instances.get(ship)`; if `None` (ship removed / not
    rendered) drop the entry.
  - Recompute the carve center each tick from the **current** transform:
    `core_world = subsystem_world_position(core, ship)` (so it tracks the
    tumbling wreck; in body frame this is a constant offset, so every re-emit
    merges into the same growing carve).
  - `radius = MAX_RADIUS_SHIP_FRACTION * ship.GetRadius() * ease_out(t)`
    (`ease_out(t) = 1 − (1 − t)²`), floored at a small `MIN_RADIUS_GU` so the
    first frame is visible.
  - Compute the world-normal as above.
  - `host.hull_carve_add(iid, (core_world.x,y,z), (nx,ny,nz), radius, now)`.
  - When `t >= 1.0`, emit the final full-size carve once and drop the entry.
- `reset()` — clear the registry (mission swap / test teardown).

Re-emitting at the same body-frame center each tick relies on the carve field's
merge-grow behavior (`scenegraph/hull_carve.h`: a new carve coincident with an
active one merges and grows in place), so the result is a **single** growing
carve, not many stacked spheres.

### `engine/appc/warp_core_breach.py` (changed)

`detonate(ship, host, ship_instances)` calls `core_breach_carve.schedule(ship)`
(raise-safe) right after spawning the shockwave. The neighbour-AoE loop is
unchanged (still skips the source).

### `engine/host_loop.py` (changed)

In `_advance_combat`, call `core_breach_carve.advance(dt, host, ship_instances)`
beside `warp_core_breach.advance(...)`. Add `core_breach_carve.reset()` beside
`warp_core_breach.reset()` in the mission-swap reset block.

## Data flow

```
warp_core_breach.detonate(ship)            (host, ship_instances in scope)
  └─ core_breach_carve.schedule(ship)      register {ship, age:0}
        │  (each tick, host_loop _advance_combat)
        ▼
core_breach_carve.advance(dt, host, ship_instances)
   t = age/GROW_DURATION
   core_world = subsystem_world_position(core, ship)   # current transform
   radius = 0.7 * ship.GetRadius() * easeOut(t)
   host.hull_carve_add(iid, core_world, normal, radius, now)   # merges/grows
   (drop entry at t>=1 or when iid is gone)
        │
        ▼  existing breach render pass draws the growing hole (interior exposed)
```

## Error handling

- `schedule` is called from the raise-safe section of `detonate`; failure can't
  block the AoE.
- `advance` is raise-safe per entry (`dev_mode.log_swallowed`); a `hull_carve_add`
  or transform failure drops/ skips that entry without killing the tick.
- Headless / no renderer: `host` lacks `hull_carve_add` or `iid` is `None` → the
  cascade no-ops (no carve, entry drops).
- Respects the existing "Hull breaches" Modern-VFX toggle — the carve render pass
  is already gated by it, so the self-carve is hidden when the user turns hull
  breaches off, identical to weapon carves.

## Testing

Pure-Python unit tests (headless), with a fake ship (`GetWorldLocation`,
`GetWorldRotation`, `GetRadius`, `GetPowerSubsystem` → core with `GetPosition`)
and a fake host recording `hull_carve_add(iid, point, normal, radius, time)`:

- `schedule` then `advance` emits a carve at the warp-core world position with a
  radius that **increases** over successive ticks and reaches
  `~0.7 × ship.GetRadius()` by `GROW_DURATION`.
- The carve center equals the core world position each tick (constant in body
  frame), confirming a single growing hole, not scattered carves.
- The entry is dropped after `GROW_DURATION` (a later `advance` emits nothing
  more).
- A ship whose `ship_instances.get(ship)` is `None` emits no carve and is
  dropped.
- A ship with no `PowerSubsystem` is not scheduled.
- `reset` clears the registry.
- `warp_core_breach.detonate` calls `core_breach_carve.schedule(ship)` (spy).

The carve visuals (the growing hole, exposed interior) are verified in-app by the
user.

## Non-goals

- No scatter of distributed surface breaches (deferred as a later layer).
- No new carve render pass / shader (reuses the existing one).
- No change to the breach damage, radius, chains, or the shockwave ring.
- No new config toggle (rides the existing "Hull breaches" toggle).

## Affected files

| File | Change |
|---|---|
| `engine/appc/core_breach_carve.py` | New — growing core-breach carve registry |
| `engine/appc/warp_core_breach.py` | `detonate` schedules the core-breach carve |
| `engine/host_loop.py` | advance + reset wiring |
| `tests/unit/test_core_breach_carve.py` | New — registry tests |
| `tests/unit/test_warp_core_breach.py` | `detonate` schedules the carve (spy) |
