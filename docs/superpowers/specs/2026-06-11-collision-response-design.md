# Collision Response — kinematic impulse overlay + KE impact damage

**Date:** 2026-06-11
**Status:** Design approved, pre-implementation
**Author:** brainstorming session (Mark Ward + Claude)

## 1. Problem & scope

Flight behaviour is working, but ships, asteroids, moons, and planets pass
through one another with no consequence. We want two behaviours on contact:

- **A — Impact damage.** A ship takes significant, speed-dependent damage at the
  collision point.
- **B — Newtonian response.** Both colliding bodies have their velocity and
  heading altered, roughly approximating conservation of momentum.

### No physics overhaul required

There is **no rigid-body physics engine in the live path.** PyBullet was a
Phase-1 *headless* artefact only. The C++/host runtime moves everything with a
kinematic integrator — `engine/appc/ship_motion.py` for AI ships and
`_PlayerControl` for the player. Position is `pos += velocity·dt`, where
velocity comes from an impulse-setpoint ramp. There is no broadphase, no contact
solver, nothing to replace.

Both halves of the feature already exist as **reusable primitives**, built for
the weapons system:

- **Collision detection** — `engine/appc/combat.py` has
  `sphere_hit(point, center, radius)` and `ray_trace_mesh` (precise hull surface
  contact point + normal). Ships expose `GetRadius()`, `GetWorldLocation()`,
  `GetMass()`, `GetVelocity()`.
- **Damage at a contact point** — `combat.apply_hit(ship, damage, hit_point,
  source, normal=…, host=…, ship_instances=…)` already routes shields →
  subsystems → hull, spawns decals/VFX, and broadcasts `WeaponHitEvent`. This is
  exactly how torpedoes apply damage at `engine/host_loop.py:262`.

So this is **plumbing on top of two existing systems**, not a new system: one
new module, a per-tick broadphase pass (O(n²) sphere-overlap, n is a handful of
objects → negligible cost), and one small additive hook in the integrator.

### Out of scope (orthogonal, untouched)

Planets/suns already carry an `EnvironmentalHullDamage` + `AtmosphereRadius`
proximity-damage zone (`engine/appc/planet.py`) — BC's native "you're in the
corona" effect. That is a *soft proximity* effect and is independent of
hard-surface collision. This spec leaves it entirely untouched; we collide
against a body's solid `GetRadius()` sphere.

## 2. The core mechanism: collision-impulse overlay

The integrator has no free world-space velocity *state* to bounce. A ship's
motion is `_current_speed` along a facing-derived direction (plus
`_drift_velocity` when powerless). Rather than rewrite that, we add a
**collision-impulse overlay**:

- Each ship gains an optional world-space vector `_collision_velocity` (absent /
  `None` by default → zero).
- When a collision occurs, an impulse is injected into this vector.
- Each tick, the integrator *adds* `_collision_velocity·dt` to the ship's
  displacement and decays `_collision_velocity` toward zero (exponential, time
  constant `COLLISION_DECAY_TAU ≈ 0.5 s`).

Engine thrust still runs normally; the collision shove is layered on top and
bleeds off. This is the smallest change that produces a real Newtonian kick
without touching the thrust-ramp logic, and it is fully backward-compatible:
anything without a `_collision_velocity` attribute behaves byte-identically to
today.

## 3. New module: `engine/appc/collisions.py`

Single public entry point:

```python
def tick_collisions(dt: float, host=None, ship_instances=None) -> list[tuple]:
    """Detect and resolve all collisions for this tick.

    Returns the list of (a, b, contact_point, v_rel) pairs that collided
    this tick (for tests / debugging). host & ship_instances are forwarded
    to combat.apply_hit; when None (headless), VFX/renderer pushes are
    skipped but damage + impulse logic still runs.
    """
```

### Collidable inventory

A new helper enumerates collidables:

```python
def iter_collidables() -> Iterable:
    """Yield every object with GetWorldLocation + GetRadius across all
    active sets: ships (ShipClass) plus immovable space bodies
    (planets, moons, asteroids)."""
```

Implementation walks `App.g_kSetManager._sets` via the existing
`engine/appc/ship_iter.py:iter_set_objects`, yielding any object that exposes
both `GetWorldLocation()` and a positive `GetRadius()`. Ships are identified by
`isinstance(obj, ShipClass)`; everything else with a radius is treated as a
space body.

### Movable vs immovable

Each collidable resolves to `(center, radius, inv_mass, is_movable)`:

- **Ships** (`ShipClass`): `inv_mass = 1 / GetMass()` (guard `GetMass() > 0`;
  fall back to a nominal mass if zero), `is_movable = True`.
- **Space bodies** (planets/moons/asteroids): treated as **immovable / infinite
  mass** → `inv_mass = 0`, `is_movable = False`. They deal damage and provide a
  collision surface but never move and never receive `apply_hit`. *(Asteroids
  modelled as `ShipClass` props with a real mass are movable ships and follow
  the ship path — the radius-based enumeration handles both uniformly.)*

### Velocity accessor

A body's current world velocity for the response math is
`GetVelocity()` **plus** its current `_collision_velocity` overlay (so
multi-body / repeated contacts in one frame compose correctly). Immovable bodies
report zero velocity.

## 4. Broadphase + narrowphase (one pass)

For every unordered pair `(A, B)` of collidables:

1. `d = centerB − centerA`; `dist = |d|`.
2. **Overlap test:** `dist < rA + rB` (skip if not overlapping, or if `dist`
   is ~0 to avoid division-by-zero degeneracy).
3. Contact normal `n = d / dist` (unit, A→B).

n is small (a few ships + a few bodies), so the O(n²) double loop is trivially
cheap. No spatial acceleration structure is warranted (YAGNI).

## 5. Response per overlapping pair (B)

1. **Closing speed** along the normal: `v_rel = (vB − vA) · n`, where `vA`/`vB`
   are the velocity accessors from §3.
2. **Approach gate (debounce):** respond only if `v_rel < 0` (bodies
   approaching). Once the impulse reverses relative velocity, later ticks read
   receding and produce no further hits while the spheres still overlap. This is
   the physical debounce — no cooldown bookkeeping needed.
3. **Mass-weighted impulse** (restitution `e = COLLISION_RESTITUTION ≈ 0.2`,
   mostly inelastic — ships crunch, not bounce like billiards):

   ```
   j = -(1 + e) * v_rel / (inv_mass_A + inv_mass_B)
   ```

   Apply into each body's `_collision_velocity`:

   ```
   collision_velocity_A -= (j * inv_mass_A) * n
   collision_velocity_B += (j * inv_mass_B) * n
   ```

   Immovable bodies have `inv_mass = 0`, so `(inv_mass_A + inv_mass_B)` is just
   the movable ship's `inv_mass`; the ship absorbs the full kick and the world
   body is unmoved. The asymmetric (ship-vs-planet) case is the same formula.
4. **Positional de-penetration:** push the movable body(ies) apart along `n` by
   the overlap depth `pen = (rA + rB) − dist`, distributed by inverse mass, so
   bodies don't sink in and re-trigger:

   ```
   correction = pen * n
   move_A -= correction * inv_mass_A / (inv_mass_A + inv_mass_B)
   move_B += correction * inv_mass_B / (inv_mass_A + inv_mass_B)
   ```

   Applied via `SetTranslateXYZ` on each movable body.

## 6. Impact damage (A)

For an approaching pair (same `v_rel < 0` gate):

```
mu = 1 / (inv_mass_A + inv_mass_B)        # reduced mass; → ship mass vs immovable
KE = 0.5 * mu * v_rel**2
damage = COLLISION_DAMAGE_COEFF * KE
```

- `COLLISION_DAMAGE_COEFF` is a tunable constant calibrated so a typical
  full-impulse ram does catastrophic (multi-hundred-point) hull damage and a
  slow dock-bump is trivial. Tuned by feel against ground-truth ship hull
  strengths.
- **Both ships take damage** from the same impact (symmetric). Each movable ship
  receives `apply_hit`; immovable bodies deal damage but never receive it.
- **Contact point & normal:** midpoint on the contact line
  `contact = centerA + n * rA`. Where a precise hull surface point is wanted
  (matching the projectile path), trace `ray_trace_mesh` along the centre line;
  otherwise the sphere-surface point + `n` is sufficient for decal/VFX placement.
- **Routing:** reuse the existing path verbatim —

  ```python
  combat.apply_hit(ship, damage, contact_point, source=other_body,
                   normal=n, host=host, ship_instances=ship_instances,
                   weapon_type=None)
  ```

  Shields → subsystems → hull, decals, VFX, and `WeaponHitEvent` all come for
  free. `weapon_type=None` (not phaser/torpedo) so audio routing treats it as a
  generic impact. *(A dedicated collision SFX/`weapon_type="collision"` is a
  possible follow-up, not in this spec.)*

## 7. Integrator hook

In `engine/appc/ship_motion.py`, after the existing thrust displacement is
applied (both the powered-flight branch and the `f <= 0` drift branch), add the
collision overlay and decay it:

```python
cv = getattr(ship, "_collision_velocity", None)
if cv is not None and (cv.x or cv.y or cv.z):
    p = ship.GetTranslate()
    ship.SetTranslateXYZ(p.x + cv.x * dt, p.y + cv.y * dt, p.z + cv.z * dt)
    decay = math.exp(-dt / COLLISION_DECAY_TAU)
    cv.x *= decay; cv.y *= decay; cv.z *= decay
```

Guarded by `getattr(..., None)` so existing tests and any ship that has never
collided are byte-identical. The player ship (driven by `_PlayerControl`, which
also integrates its own transform) gets the same overlay applied where it
integrates position — the hook lives wherever the per-tick displacement is
written for that path, so player rams also recoil.

## 8. Host-loop call site

Call `collisions.tick_collisions(dt, host, ship_instances)` once per tick in
`engine/host_loop.py`, **after** both `tick_all_ship_motion(dt)` and
`_PlayerControl.apply(...)` have run for the frame, so every body's post-thrust
position is current before overlap testing. It sits alongside the existing
torpedo/phaser damage tick in the same per-frame block.

## 9. Tuning constants (single home in `collisions.py`)

| Constant | Default | Meaning |
|---|---|---|
| `COLLISION_RESTITUTION` | `0.2` | Bounciness `e`; mostly inelastic crunch. |
| `COLLISION_DAMAGE_COEFF` | `5.0` | KE → hull-damage-points scale; calibrated below. |
| `COLLISION_DECAY_TAU` | `0.5` s | Collision-velocity overlay decay time constant. |
| `COLLISION_FALLBACK_MASS` | `1.0e4` | Nominal mass for a ship reporting `GetMass() == 0` (test ships built without `SetupProperties`). |

All live in `collisions.py` (and the one integrator constant referenced from
`ship_motion.py`); no magic numbers scattered across call sites.

**Calibrating `COLLISION_DAMAGE_COEFF` (done):** derived from Galaxy
ground-truth — mass 120, hull `MaxCondition` 15000, impulse `MaxSpeed`
6.3 GU/s (`sdk/.../ships/Hardpoints/Galaxy.py`). With `KE = ½·μ·v_rel²` and
`COEFF = 5.0`:

| Scenario | μ | v_rel (GU/s) | KE | damage | % of 15000 hull |
|---|---|---|---|---|---|
| Head-on, both full impulse | 60 | 12.6 | 4763 | 23814 | >100% — instant kill |
| Full-impulse ram into planet | 120 | 6.3 | 2381 | 11905 | 79% — near-fatal |
| Ram a stationary ship | 60 | 6.3 | 1190 | 5953 | 40% — heavy |
| Slow dock bump | 60 | 0.1 | 0.3 | 1.5 | trivial |

This matches the design intent: high-speed planet impact near-fatal, full
head-on ram devastating, gentle contact negligible. The constant remains a
single in-engine "feel" knob — adjust after the manual fly-test if the band
needs shifting.

## 10. Testing (headless, no renderer)

`apply_hit` and the whole response run with `host=None`, so all tests are
headless:

1. **Symmetric head-on:** two equal-mass ships closing along a line → equal,
   opposite collision impulses; total momentum conserved within restitution;
   both take equal damage.
2. **Mismatched mass:** light ship vs heavy ship → light ship's
   `_collision_velocity` magnitude is larger by the mass ratio.
3. **Ship vs immovable body:** ship bounces (gets impulse + KE damage), planet
   position unchanged, planet receives no `apply_hit`.
4. **Glancing / low closing speed:** small `v_rel` → trivial damage (KE ∝ v²).
5. **Overlap persistence:** keep two bodies overlapping across several ticks →
   damage + impulse applied on the approaching tick only, not every tick (the
   `v_rel < 0` gate + de-penetration verified).
6. **Backward-compatibility:** a ship that never collides has no
   `_collision_velocity` attribute and its motion output is unchanged from the
   pre-feature integrator.

## 11. Files touched

- **New:** `engine/appc/collisions.py` (~150 lines).
- **Edit:** `engine/appc/ship_motion.py` — additive overlay hook in
  `_step_ship_motion` (both branches).
- **Edit:** `engine/host_loop.py` — one `tick_collisions(...)` call in the
  per-frame block; same overlay hook on the `_PlayerControl` integration path.
- **New tests:** `tests/...` covering §10.

## 12. Explicit non-goals (YAGNI)

- No spatial broadphase acceleration (n is tiny).
- No angular impulse / spin-up from off-centre hits (linear response only;
  heading changes come from the velocity overlay, not torque).
- No per-material restitution/friction.
- No dedicated collision audio cue (possible follow-up).
- No change to the planet/sun environmental proximity-damage zone.
