# Breakable Hull Components — design

**Status:** approved in conversation 2026-09-11; supersedes §8 of
`2026-09-08-dauntless-hull-volumes-design.md`, which was written before plan 2a
changed what the per-instance field *is*.

**Parent spec:** `docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md`
**Branch:** `feat/breakables-and-dents`

---

## 1. What this builds

When a carve severs a piece of a hull — a nacelle, a pylon, the neck, and during
the death cascade the saucer itself — that piece **separates**: it becomes its own
drifting, tumbling, colliding body, rendered as the original hull mesh with a torn
face where it parted, and it persists.

Three decisions taken in conversation, recorded here so the plan argues from them
rather than re-opening them:

| Decision | Chosen | Alternatives rejected |
|---|---|---|
| What a chunk is | **Visual debris that collides.** A physical body in the collision system — it takes impulses and a ship it strikes takes kinetic damage — but not targetable, no hull HP, no subsystems, never in the contact list. | A full game object (targetable, own HP); a visual-only chunk with no collision. |
| What may sever | **Any carve, from anything.** Weapons, collisions and the death cascade all go through the same brush; if a carve disconnects a component on a breakable ship, it comes off. | Death cascade only; a damage-accumulation threshold. |
| Cascade scale | **Swept capsule cuts in the death cascade** at a larger radius than combat, so a dying ship can part at the neck or across the saucer. | Same 0.3 GU sphere everywhere; larger spheres without a sweep. |

Chunks are **persistent** — no timer despawn. That was the specific complaint
against the old death sequence.

## 2. Why §8 had to be rewritten

§8 said "flood-fill the field for connected components." When it was written the
field was the hull's own signed distance. **Plan 2a changed that:** the
per-instance field carries *damage only* — every cell starts at `-127` and only a
brush raises it (`instance_field_cache.cc`, `hull_volume_cache.h`). It does not
know where the hull *is*. Connectivity therefore needs two inputs, and both exist:

- the **baked hull SDF** for the hull class (shared, `HullVolumeCache`), which says
  where material is;
- the **per-instance damage field**, which says where it has been removed.

Everything below follows from that correction.

## 3. Connectivity

Lives in the voxel library, in C++, because both inputs are already there and the
fill is a hot-ish path.

**Occupancy.** A cell is occupied iff `baked_sdf(cell) <= 0` **and**
`damage(cell) < iso`, where `iso` is the same threshold the hull clip uses
(`kHullFieldIsoMargin` in stored-int8 terms: `damage <= 0`).

**Fill.** Breadth-first from a **seed** — the occupied cell nearest the body-frame
origin, falling back to the occupied cell with the most occupied 6-neighbours if
the origin cell is carved. Everything reached is the **main body**. A second pass
labels every unreached occupied cell into components (6-connectivity, same as the
BFS). Output, per component: label, cell count, centroid (body frame, model
units), axis-aligned bounds (body frame), and the list of cells.

**When.** After a carve lands on an instance for which
`breakables_allowed_for(ship)` is true. Never per frame. **Throttled per ship:**
connectivity runs at most once per `kBreakupCheckInterval` (0.5 s) per ship; a
carve that arrives inside the window marks the ship *pending* and the check runs
on the next frame after the window elapses, so a burst of carves costs one fill
and the last carve is never dropped. A sever detected half a second late is
invisible; ten full-lattice fills a second on eight ships is not. (An earlier
draft proposed skipping fills whose brush touched no occupied cell; the throttle
is simpler, bounds the cost regardless of carve pattern, and needs no per-brush
bookkeeping.) The plan measures the fill on a Galaxy lattice (~512k cells) before
anything depends on its cost.

**Signature:**

```cpp
struct HullComponent {
    std::uint32_t label;
    std::size_t   cells;
    glm::vec3     centroid_body;     // model units
    glm::vec3     bounds_min_body, bounds_max_body;
    std::vector<glm::ivec3> cell_list;
};
struct ConnectivityResult {
    std::size_t main_body_cells;
    std::vector<HullComponent> detached;   // empty when nothing severed
};
ConnectivityResult hull_connectivity(const DistanceField& baked,
                                     const DistanceField& damage);
```

Both fields share one lattice by construction (the instance field copies the
baked field's `dims/origin/cell/scale` — `instance_field_cache.cc`); the function
asserts that and returns an empty result on mismatch rather than reading out of
bounds.

## 4. The chunk

A detached component becomes:

**A second renderer instance of the same model.** `create_instance(handle)` on
the parent's model handle — shared geometry and textures, its own world
transform. This is the renderer facade call `host_loop.py` already uses to
realise a ship (`engine/renderer.py`).

**Its own `InstanceFieldCache` entry**, on the same lattice, built as:

```
chunk.damage[c]  = parent.damage[c]   for c in component cells
chunk.damage[c]  = +127               otherwise      ("fully carved")
parent.damage[c] = +127               for c in component cells
```

The chunk keeps any holes it already had. Both instances then render through the
**existing** hull clip and interior raymarch, unchanged: the parent no longer
draws the component's surface, the chunk draws only it, and the **cut face** —
where the field jumps from intact to carved across one cell — is what the
raymarch paints as torn interior. No new geometry, no remesh, no UV work, and no
shader change.

**No sphere list.** The chunk is pure field. Plan 2c made the field the hole
authority beyond tracked carves, with its own noisy rim, so a chunk needs none of
the analytic machinery.

**Size floor.** A component below `kChunkMinCells` (initial value **8**) is not
spawned. Its cells are still set carved on the parent (the material is gone) and
the existing breach-debris particle burst fires at its centroid. Full instances
for specks would be cost for nothing.

**Failure to create.** If `create_instance` fails, the component's cells are still
carved from the parent — the hull must not keep phantom material — and the
absence of the chunk is logged through `dev_mode.log_swallowed`, never silent.

## 5. Body and collision

`engine/appc/debris_chunk.py` — a new class `DebrisChunk`, deliberately **not** a
`ShipClass`. It carries exactly the surface `collisions.py` reads from a movable
body, and nothing else:

`GetWorldLocation`, `GetTranslate`, `SetTranslateXYZ`, `GetWorldRotation`,
`GetRadius`, `GetMass`, `GetVelocity`, `IsImmobile` (always false), `GetObjID`,
and the instance `__dict__` slots the collision overlay and `_current_angular_velocity`
use. `iter_collidables()` is extended to yield live chunks.

It then participates in `_respond_pair` like any movable body: it takes impulses
and de-penetration, and a ship it strikes takes kinetic damage through the normal
path. `apply_hit` on the chunk itself is a no-op — `GetHull()` returns `None`, so
`absorbed_hull` stays zero and nothing carves. Grinding on a chunk posts no
collision event, for the same mission-ending reason the grind channel never does
(`MissionLib.FriendlyFireCollisionHandler`).

**Initial state at separation:**

| | |
|---|---|
| position / orientation | the parent's, so the chunk is exactly where the component was |
| velocity | parent velocity **+** `kChunkSeparationSpeed` (initial **0.15 GU/s**) along parent-centre → component-centroid |
| angular velocity | random unit axis × `kChunkTumbleRate` (initial **0.4 rad/s**), body frame |
| mass | `parent_mass × component_cells / parent_occupied_cells` |
| radius | component bounding-sphere radius, model units × `BC_MODEL_SCALE` |

**Integration.** Each frame on `_player_dt`, in Python: position by velocity;
orientation by post-multiplying the body-frame angular delta (CLAUDE.md rotation
convention); collision overlay applied and decayed by the existing
`_apply_overlay_all`. World transform pushed to the renderer via
`set_world_transform`, as ships are. A handful of chunks is not a cost worth
moving to C++.

## 6. Cascade capsule brush

`field_carve_capsule(field, p0_body, p1_body, radius)` in the voxel library: the
signed distance to a capsule (segment `p0–p1` with radius), CSG-subtracted with
the same `max()` monotonicity, the same **conservative floor and offset**
(`kCarveDepthFloorCells`, `kCarveFieldOffsetCells`) and the same int8
quantisation as `field_carve_oblate`. A capsule thinner than the lattice can
hold is the precise defect plan 2c fixed for spheres; the same sweep test
guards it here.

**Use.** In `death_cascade.py`, the 30% `AddDamage` branch — when the ship is
breakable — picks two random points on the model (`GetRandomPointOnModel`, which
the cascade already calls) and carves a capsule between them at
`kCascadeCapsuleRadiusGu` (initial **0.6 GU**; combat carves stay at
`kHullCarveRadiusMaxGu` 0.3). The `AddDamage` itself still happens, so hull HP,
subsystems and the SDK's damage events are untouched.

**The capsule never enters the 24-slot sphere list.** It is field-only: cut by
the field block, rimmed by its body-space noise, interior by the raymarch. No
shader change. This is the direct payoff of 2c.

## 7. Subsystems on a severed component

When a component detaches, every subsystem whose hardpoint position (body frame,
via the existing `subsystem_world_position` mount logic run in body space) lies
inside one of the component's cells is **destroyed** — condition set to zero
through the normal subsystem-damage path, so its usual events fire. A nacelle
that has physically left the ship cannot remain a working warp engine. This is
the single place a chunk touches gameplay state, and it is cheap: the component's
cell list is the fill's output.

## 8. Gating, lifecycle, limits

**Gating.** A ship sheds a chunk only when `breakables_allowed_for(ship)` is true
— plan 1's gate: radius above a Galor's (`BREAKABLE_MIN_RADIUS_GU = 2.381`)
**and** `DamageableObject_IsBreakableComponentsEnabled`, which defaults on in
Dauntless. Below the gate a severing carve still removes the material; the
component vanishes rather than becoming a chunk.

**Cap.** `kMaxLiveChunks` = **32**. When a 33rd is needed, the oldest is removed
(instance destroyed, field entry forgotten, body unregistered). The new component
is still carved from its parent regardless.

**Clearing.** All chunks are removed on mission swap, through the same hook the
death cascade uses to clear itself.

**Parent death.** A parent ship dying does not remove its chunks — they are
independent bodies. Its own field and instance are cleaned up as today.

## 9. Constants and where they live

| Constant | Initial | Where | Rebuild? |
|---|---|---|---|
| `kChunkMinCells` | 8 | `engine/appc/debris_chunk.py` | no |
| `kMaxLiveChunks` | 32 | `engine/appc/debris_chunk.py` | no |
| `kChunkSeparationSpeed` | 0.15 GU/s | `engine/appc/debris_chunk.py` | no |
| `kChunkTumbleRate` | 0.4 rad/s | `engine/appc/debris_chunk.py` | no |
| `kCascadeCapsuleRadiusGu` | 0.6 GU | `engine/appc/death_cascade.py` | no |
| capsule floor / offset | shared with oblate | `voxel/field_brush.h` | yes |

Every tuning knob a live pass is likely to turn is Python.

## 10. Testing

Each test names what would make it fail.

- **Connectivity** — a synthetic dumbbell: two blobs joined by a one-cell neck.
  Unsevered → one component, zero detached. Neck carved → one detached component
  with the exact cell count and centroid of the far blob. Mutation: skip the BFS
  → must fail.
- **Chunk field construction** — after separation, asserted cell by cell: every
  component cell of the chunk's field equals the parent's pre-separation value;
  every other cell is `+127`; every component cell of the parent is `+127`. Not
  "looks damaged".
- **Body** — a chunk registered with `iter_collidables`, struck by a ship,
  deposits kinetic damage on the ship and none on itself; grinding on it posts
  no collision event.
- **Capsule brush** — the same conservative-brush sweep plan 2c ran for the
  oblate: every point along and around a capsule cut reads damaged in the field
  across cell 3.0–7.5 and radius 0.3–1.0 GU.
- **Gating** — a Galor sheds no chunk; an Akira does. Fleet radii are literals
  with plan 1's stated caveat.
- **Subsystem coupling** — a subsystem positioned inside the severed component
  is destroyed; one outside is untouched.
- **Cap and clear** — the 33rd chunk evicts the oldest; mission swap leaves zero.

**What tests cannot see — the live briefing:** whether the cut face reads as
torn hull or a black smear; whether chunks tumble plausibly or spin like tops;
whether a 0.6 GU capsule reads as a crack or a trench; whether a separated
saucer's mass and separation speed feel right. All are Python constants.

## 11. Out of scope

- Dents / deformation (the `dent` brush). Still unbuilt; next slice.
- Chunks as game objects (targetable, own HP). The `DebrisChunk` carries its
  origin ship and component id so promoting it later is additive.
- Biasing breaks toward authored hull sections (§2.7 of the parent spec, open
  question 4). The fill is emergent; sections can weight it later.
- Chunk-on-chunk collision refinement beyond the sphere broad phase.
