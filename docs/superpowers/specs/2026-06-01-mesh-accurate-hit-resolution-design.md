# Mesh-accurate Hit Resolution — Design

**Status:** drafted, awaiting user review
**Date:** 2026-06-01
**Author:** Mark Ward (with Claude)
**Roadmap:** [`2026-06-01-combat-damage-pipeline-design.md`](./2026-06-01-combat-damage-pipeline-design.md) — Project 1 of 5.

## 1. Goal

Replace the approximate hit-point computation that currently feeds
`engine.appc.combat.apply_hit` with a real point on the target's loaded
mesh, produced by a C++ ray-vs-triangle trace exposed via a new
`_dauntless_host.ray_trace_mesh` binding. Both the torpedo and phaser
call sites in `engine.appc.projectiles.update_all` and
`engine.host_loop._advance_combat` consume the new binding.

Downstream subsystem-proximity routing, shield-face mapping,
damage VFX, and gameplay consequences are explicitly out of scope —
they are Projects 2–5 in the roadmap. This project changes only the
*input* point fed to `apply_hit`; the function itself is untouched.

## 2. What ships in this project

- A C++ helper `renderer::ray_trace_instance` that walks a model's
  `MeshCpu` records, performs a bounding-sphere coarse reject, then a
  brute-force Möller–Trumbore triangle test, and returns the closest
  world-space hit.
- A Python binding `_dauntless_host.ray_trace_mesh(instance_id, origin,
  direction, max_dist) → (point, normal, t) | None`.
- Updates to two `apply_hit` callers so the hit point passed in is a
  real surface point when the trace hits, and a bounding-sphere entry
  point when it does not.
- Unit + integration tests for the binding and updated callers.
- Visual smoke check against E1M1.

## 3. Design decisions

### 3.1 Binding shape

Single ray per call:
```
ray_trace_mesh(instance_id: InstanceId,
               origin: tuple[float, float, float],
               direction: tuple[float, float, float],  # unit length
               max_dist: float) -> tuple | None
```
Returns `((px, py, pz), (nx, ny, nz), t)` or `None`. `t` is in world
units along the ray; `point = origin + direction * t`. Normal is
outward-facing relative to the incoming ray (`dot(normal, direction) <=
0` always holds in the returned value).

Single-ray was chosen over batching because the worst case at 60 Hz is
on the order of dozens of rays per frame and the inner loop dominates
the per-call cost. Batching can be added later without changing call
sites — the single-call API is forward-compatible.

### 3.2 Multi-mesh ships

`Galaxy` and similar ships are several `Mesh` records under one
`Model`. The binding iterates every mesh whose `cpu_data()` is
populated, chains node-local transforms to world space (one-pass walk
matching [`renderer/aabb.cc:30-37`](../../../native/src/renderer/aabb.cc#L30-L37)),
and returns the globally closest hit. Caller sees one shape: one
`InstanceId` in, one optional hit out.

### 3.3 Miss fallback — bounding-sphere entry point

When the mesh trace returns `None`, the caller computes the entry
point of the ray segment on the ship's bounding sphere and uses that
as the hit point. This guarantees that:

- No hit that the current bounding-sphere logic would have applied is
  silently dropped.
- The replacement point is always *closer* to the real hull than
  `target.GetWorldLocation()` (ship centre), so downstream Project 2
  proximity picking still benefits.

When the ray segment also misses the bounding sphere (genuine miss),
the caller skips the hit entirely — same as today's behaviour.

The fallback is instrumented with a debug counter so we notice if mesh
geometry has gaps that cause frequent fallbacks in practice.

### 3.4 Ray construction

**Torpedoes** ([`engine/appc/projectiles.py:109-151`](../../../engine/appc/projectiles.py#L109-L151)):
- `origin = prev_pos` (the position before the per-tick advance).
- `direction = velocity_normalized`.
- `max_dist = |velocity| * dt`.

This casts exactly the per-tick segment the torpedo traversed, so the
trace returns the first surface the torpedo intersected on its way to
its post-advance position.

**Phasers** ([`engine/host_loop.py:_advance_combat`](../../../engine/host_loop.py#L207)):
- `origin = emitter_pos` (output of `bank._strip_emit_position`).
- `direction = (target_pos - emitter_pos) / dist`.
- `max_dist = dist * 1.5`.

The 1.5× overshoot lets the trace find a surface in front of an aim
point that sits slightly inside the hull (which is common when the
player has locked a subsystem — subsystem world positions live inside
the hull). 1.5× is bounded so the ray doesn't pick up the far-side
hull behind a hollow ship.

Damage falloff continues to use `dist` (emitter→aim), not the trace
`t`. The aim point is what the player asked for; the trace just
relocates the *visible* impact onto the hull. Firing math is
unchanged.

### 3.5 Algorithm

**Coarse reject — bounding sphere.** Per call, build a world-space
sphere from the instance's world transform applied to
`compute_model_aabb(model)`; sphere radius =
`length(world_half_extents)`. Ray-vs-sphere segment test; miss → return
`None`.

**Inner loop — Möller–Trumbore.** For each `Mesh` with
`cpu_data()`:
1. Compute `node_world` for the mesh's owning node (chain
   `node.local_transform` from root via `node.parent_index`, same
   one-pass walk as `aabb.cc`).
2. Compose `mesh_world = instance_world * node_world`.
3. Transform the ray into mesh-local space:
   `origin_local = inverse(mesh_world) * origin`,
   `direction_local = inverse_3x3(mesh_world) * direction`.
   Re-normalise direction; scale `max_dist` by the local-direction's
   pre-normalisation length so `t` measured in local space maps back
   to world units (in practice models have uniform scale and this is
   a no-op, but the math is explicit).
4. Walk indices in triples; per triangle run Möller–Trumbore,
   double-sided (no backface culling); keep the smallest valid
   `t_local ∈ [ε, max_dist_local]`.

**Result reconstruction.**
- `point_world = mesh_world * (origin_local + direction_local *
  t_local)`.
- `normal_local = normalize(cross(v1 - v0, v2 - v0))`.
- `normal_world = normalize(normal_matrix * normal_local)` where
  `normal_matrix = transpose(inverse(mesh_world_3x3))`.
- Flip: `if dot(normal_world, direction) > 0: normal_world =
  -normal_world` so the returned normal always faces the incoming ray.
- Return `t` measured back in world units along the original ray
  direction.

**Failure modes.**
- Invalid `InstanceId` → raises (programmer error).
- Instance valid but no mesh has `cpu_data()` → returns `None`
  (recoverable; should not happen with the existing
  `keep_cpu_data = true` config but is handled defensively).
- Degenerate triangles (zero-area, NaN positions) → skipped silently.

## 4. Caller wiring

### 4.1 Torpedo path

`projectiles.update_all` signature becomes
`update_all(dt, all_ships, *, ship_instances=None, host=None)`. New
behaviour inside the loop:

```python
prev_pos = TGPoint3(t._position.x, t._position.y, t._position.z)
t._position = t._position + t._velocity * dt
# ... TTL check, sphere broad-phase per ship ...
if sphere_hit(t._position, ship.GetWorldLocation(), ship.GetRadius()):
    seg = t._position - prev_pos
    seg_len = seg.Length()
    aim_unit = TGPoint3(seg.x/seg_len, seg.y/seg_len, seg.z/seg_len) if seg_len > 1e-9 else None
    hit_point = _resolve_hit_point(
        host, ship_instances, ship,
        ray_origin=prev_pos,
        ray_direction=aim_unit,
        max_dist=seg_len,
        ship_pos=ship.GetWorldLocation(),
        ship_radius=ship.GetRadius(),
        fallback_point=t._position,
    )
    # ... pick_target_subsystem and emit (t, ship, subsystem, hit_point) ...
```

`_resolve_hit_point` lives in `engine.appc.combat` (next to
`sphere_hit`) and encapsulates the three-tier fallback chain:

1. If `host` is available, call `host.ray_trace_mesh`; on hit, return
   the mesh point.
2. On mesh miss (or if `host` exists but the binding isn't there), if
   the ray segment intersects the bounding sphere, return the
   ray-vs-sphere entry point.
3. Otherwise return `fallback_point` — today's pre-project behaviour,
   passed in by each caller so the no-host headless path matches
   exactly what that caller used to do.

`update_all` returns `(torpedo, ship, subsystem, hit_point)` tuples
instead of three-tuples; `_advance_combat` consumes the new field.

### 4.2 Phaser path

Inside the existing `for bank in ...` loop in `_advance_combat`, after
`target_pos`, `emitter_pos`, and `dist` are computed and the arc
check has passed, before `apply_hit`:

```python
impact_point = _resolve_hit_point(
    host, ship_instances, target,
    ray_origin=emitter_pos,
    ray_direction=aim_unit,
    max_dist=dist * 1.5,
    ship_pos=target.GetWorldLocation(),
    ship_radius=target.GetRadius(),
    fallback_point=target_pos,
)
# ... damage falloff still uses dist, not the trace t ...
apply_hit(target, damage, impact_point, source=ship, subsystem=target_sub)
# ... shield_hit at impact_point ...
```

Headless / no-binding case: `_resolve_hit_point` returns
`fallback_point = target_pos` (today's value), so behavioural
compatibility is preserved when no renderer is attached.

## 5. File layout

### 5.1 New files

| Path | Purpose |
|---|---|
| `native/src/renderer/ray_trace.h` | Declares `struct RayHit`, `ray_trace_instance`. |
| `native/src/renderer/ray_trace.cc` | Sphere reject, node walk, triangle test, closest-hit selection. |
| `tests/integration/test_mesh_ray_trace.py` | C++ binding tests. |
| `tests/integration/test_torpedo_hit_point_on_mesh.py` | Torpedo path test. |

### 5.2 Edited files

| Path | Change |
|---|---|
| `native/src/renderer/CMakeLists.txt` | Add `ray_trace.cc`. |
| `native/src/host/host_bindings.cc` | Bind `ray_trace_mesh`. |
| `engine/appc/projectiles.py` | Ray construction; new `update_all` signature; emit `hit_point` in result tuples. |
| `engine/appc/combat.py` | Add `_resolve_hit_point` helper. |
| `engine/host_loop.py` | Pass `ship_instances` + `host` to `update_all`; phaser-loop ray construction; consume new `hit_point` from torpedo tuples. |
| `tests/integration/test_phaser_damage_applied_through_apply_hit.py` | Update hit-point assertions. |

## 6. Tests

### 6.1 Binding tests (`test_mesh_ray_trace.py`)

1. **Synthetic single-triangle mesh.** Build via the existing `upload_mesh` path (or a minimal in-test NIF if simpler). Trace through the centroid; assert returned point ≈ centroid, normal matches the triangle's geometric normal, `t` ≈ ray distance.
2. **Miss returns None.** Same triangle, ray that passes outside.
3. **Max-dist clip.** Triangle at `t=10`, `max_dist=5` → `None`.
4. **Closest-hit on multi-mesh model.** Real Galaxy NIF; trace from in front of the saucer outward; assert hit lies in the saucer region (z > some saucer threshold), not the engineering hull behind it.
5. **Ray from inside hull.** Origin inside a closed mesh, direction outward; assert hit returned and `dot(normal, direction) ≤ 0`.
6. **Instance world transform respected.** Translate the instance by `(100, 0, 0)`; expected hit point shifts by the same amount.
7. **Invalid InstanceId raises.**

### 6.2 Updated integration test

`tests/integration/test_phaser_damage_applied_through_apply_hit.py` — read the file first to see its assertion style, then add:
- The `hit_point` recorded by the `WeaponHitEvent` listener (or extracted from `apply_hit`'s captured args) lies within the target's bounding sphere.
- The `hit_point` differs from `target.GetWorldLocation()` (proves the mesh-trace path fired, not the ship-centre fallback).

### 6.3 New torpedo test (`test_torpedo_hit_point_on_mesh.py`)

Spawn a torpedo on collision course; advance ticks until impact;
assert the recorded impact point differs from the torpedo's
post-advance `_position` (the value today's code would have used).

### 6.4 Headless fallback

In both the torpedo and phaser integration tests, also exercise the
no-host branch (pass `host=None`) and assert: no exception, hit point
equals the `fallback_point` the caller supplied (`t._position` for
torpedoes, `target_pos` for phasers) — preserved pre-project
behaviour.

### 6.5 Visual smoke

Manual, post-implementation:
```
cmake -B build -S . && cmake --build build -j
./build/dauntless
```
Load E1M1, fire phasers at the Warbird. Observe: beam terminus on
hull surface, not at ship centre. Repeat for torpedoes: detonation
point on hull, not at the bounding-sphere boundary.

## 7. Performance

Galaxy ≈ 20k triangles. Worst case ~10 simultaneous rays at 60 Hz =
~12M triangle tests/sec — measurable, not catastrophic. The
bounding-sphere coarse reject keeps the inner-loop cost zero for
non-impacting beams, which is the overwhelmingly common case.

BVH acceleration is parked per the roadmap (§6). Revisit only after a
profiler points at this hot loop.

## 8. Non-goals

Reaffirming the roadmap's project boundaries:

- `pick_target_subsystem` semantics are not touched. It still receives
  a hit point and walks `_children`; what changes is just the
  *quality* of that input point.
- Shield face mapping stays world-axis-dominant for now (Project 3).
- No surface-normal consumption by damage VFX yet (Project 4); the
  binding returns a normal because the data is free, but no caller
  reads it in this project.
- No subsystem-failure gameplay (Project 5).

## 9. Open items at implementation time

- Exact assertion form for the updated phaser test depends on the
  file's current shape — read it during planning before writing the
  diff.
- The synthetic-mesh test path may need either a tiny test-only
  helper to build a `MeshCpu` from Python, or a minimal hand-crafted
  NIF on disk. Decided at plan time, after grepping for existing
  test fixtures that load custom geometry.
