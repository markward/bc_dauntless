# Ship Part Articulation — design

**Status:** phase 1 BUILT and live-verified 2026-09-23 (commit `1759bc9d`, branch
`spike-bop-wing-animation`); phase 2 designed here, not built.

**§5 was revised after a live session** — node-parts now own *appendage*
severance, with voxel connectivity keeping the hull. An earlier draft rejected
node-parts as a severance unit entirely; §2.6 records the measurement that
overturned it.

**Related specs:**
- `docs/superpowers/specs/2026-09-11-breakable-hull-components-design.md` —
  voxel-connectivity chunks. This spec does **not** replace it; see §7.
- `docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md` — `.dhv`.
- `docs/superpowers/specs/2026-07-25-spv-hardpoint-value-override-editing-design.md`
  — the SPV authoring pattern phase 2's data eventually folds into.

---

## 1. What this builds

A Klingon Bird of Prey's wings move between two positions: **down** when its
weapons are armed, **up** (flatter and wider) when they are not — the canonical
attack/cruise pair.

Generalised: a **part** — a named node in a ship's NIF — can be rotated about an
authored hinge by a sim-owned pose, and things attached to that part move with it.

**This is not a BC reconstruction.** BC never animated the Bird of Prey.
`BirdOfPrey.py` is a plain LOD load, `ships/Hardpoints/birdofprey.py` is stock
subsystems, and the wing nodes carry `Controller: None` — there is no keyframe
data anywhere in the asset. Every constant here is a **design choice**. Nothing
in this document should be cited as recovered BC behaviour.

Scope of the DATA is one hull. The mechanism is general; the Bird of Prey is the
only stock ship we author.

---

## 2. Measured facts

Everything below was read out of `BirdOfPrey.nif` and the shipped hardpoint file.
Recorded here because the numbers are the whole basis for the design, and
re-deriving them costs an afternoon.

### 2.1 BC ship models are a uniform three-level tree

```
Scene Root                     (NiNode)
+-- head                       (NiNode)   <-- a PART
|   +-- __NDL_MultiMtl_Node    (NiNode)   <-- 3ds Max exporter marker
|       +-- head:2, head:4     (NiTriShape)  <-- geometry
+-- left wing                  (NiNode)
+-- left wing01                (NiNode)
+-- birdofprey                 (NiNode)
```

**A part is "a named `NiNode` child of `Scene Root` that is not
`__NDL_MultiMtl_Node`."** Only `NiNode` blocks become `assets::Model::Node`
(`model_build.cc` `walk()` early-returns on anything else), so the `:N`
`NiTriShape` geometry never enters the node array — the distinction is already
made by the loader.

There is **no special node type** to key on. `"Top Level Object"` is a
file-format marker for the file root and appears exactly once per NIF; it does
not classify parts.

### 2.2 The part split is real but uneven across the fleet

| ship | depth-1 part nodes |
|---|---|
| Galaxy | `Ent-D Saucer Section` (one) |
| Nebula | `Nebula Hull` (one) |
| **Bird of Prey** | `head`, `left wing`, `left wing01`, `birdofprey` |
| Sovereign | `top o dish`, `Mesh02`, `Mesh03`, `Hull` |
| Warbird | `rom engine left/right`, `rom head`, `rom hull main`, `rom hull spine top`, `rom wing top left/right` |

So the classifier reliably **enumerates** parts on any hull, but names are raw
modeller names and carry no semantics (`Mesh02`; and `left wing01` is the
**starboard** wing — `01` is a Max clone suffix, not anatomy).

### 2.3 The NIF contains no hinge

Every part node in `BirdOfPrey.nif` carries the **identical** local translation
`(0, -56.3314, -6.3288)` — the shared 3ds Max scene origin. Rotating a node in
place swings it about a point common to the whole ship. **Pivots must be
authored.** The NIF also cannot say which wing is which.

### 2.4 Part geometry, model space, NIF units

| part | X | Y (fore-aft) | Z (up) |
|---|---|---|---|
| `head` | ±10.10 | 13.77 … 90.44 | −8.85 … 7.47 |
| `left wing` (port) | −102.58 … −12.36 | −67.77 … 53.44 | −71.25 … 18.62 |
| `left wing01` (starboard) | 12.36 … 102.58 | −67.77 … 53.44 | −71.25 … 18.62 |
| `birdofprey` (body) | −31.12 … 31.37 | −70.44 … 29.22 | −13.31 … 21.25 |

A wing tip sits ~41.4° below horizontal relative to a root near (|X| = 16,
Z = 5) — so ~45° brings the wings flat. **The angle was derived, not chosen.**

### 2.5 The wingtips carry weapons

`BC_MODEL_SCALE = 0.01`, so hardpoint units → NIF units is **×100**.

| hardpoint | authored | → NIF | part |
|---|---|---|---|
| `Port Cannon` | (−1.009, 0.450, −0.670) | (−100.9, 45.0, −67.0) | **`left wing`** |
| `Star Cannon` | (1.008, 0.450, −0.670) | (100.8, 45.0, −67.0) | **`left wing01`** |

Against a wing X extent of 12.36…102.58 and a Z floor of −71.25, both pulse
cannons sit just inboard of the wingtips. **This is why phase 2 exists.**

### 2.6 A wing is attached through a NECK, and it is nearly invisible

Narrowest cross-section of each wing, stepping along X (model-space vertex
cloud, 14 slabs):

| X band | Y-span | Z-span |
|---|---|---|
| 12.4 … 18.8 | 66.0 | 5.6 |
| **18.8 … 25.3** | **13.8** | **7.1** ← the neck |
| 25.3 … 31.7 | 39.1 | 31.8 |
| 31.7 … 38.1 | 56.3 | 31.1 |
| 96.1 … 102.6 | 61.9 | 18.4 |

The neck centroid is **(±22.5, −56.3, −3.8)** model units = **(±0.225, −0.563,
−0.038)** in ship/hardpoint units: **aft, tucked beside the hull at mid-height.**
At the default bake quality of 2 (`kDefaultQuality`, cell = authored 10 / 2 = 5
model units) that neck is ~1.4 cells thick — thin but representable, so a carve
of roughly one cell radius (~0.05 GU, ~180 absorbed hull) severs it.

⚠️ **Sampling caveat:** 8 of the 14 slabs held too few vertices to measure and
were skipped, so bands other than the neck are indicative only. A second narrow
band may exist around X ≈ 38–45; that number is NOT trustworthy and nothing
should be built on it without a finer measurement.

**This measurement is why §5 changed.** See below.

---

## 3. Phase 1 — articulation (BUILT)

### 3.1 Shape

The pose is **sim-owned**; the renderer reads it. This is the load-bearing
decision: a renderer-side animation would have to be rebuilt from scratch for
phase 2, whereas a sim-owned pose is simply consumed by more readers.

- `ShipClass._articulation_deflection` ∈ [0, 1], eased on the 60 Hz tick
  (`engine/core/loop.py` → `articulation.tick_ship`).
- Target from alert level: **RED → 0, anything else → 1**. Red is the only armed
  level (`ShipClass.SetAlertLevel` powers weapons on at RED and off otherwise),
  so this keys off exactly the armed condition rather than re-deriving it.
- **0 is the model's authored rest pose** (wings down, armed). At 0 the override
  map is empty and `draw_model` takes the original inline node walk, so combat
  rendering and every unrigged hull are byte-identical.

### 3.2 Transform

`local' = T(pivot) · R(axis, θ) · T(−pivot) · local`, in the part's **parent**
space (`Scene Root`, which is identity in every BC ship NIF, so: model space).
`θ = deflection × angle_deg`.

Composed in C++ (`set_instance_node_rotation`), which takes pivot/axis/angle —
the same three values an SPV gizmo would author — rather than a baked matrix.
`θ == 0` **erases** the override rather than storing an identity, which is what
keeps the rest-pose map empty.

### 3.3 Renderer

`Instance::node_overrides` already existed for the bridge. Phase 1 threads it
through `draw_model` as a defaulted trailing pointer and passes it at the four
ship call sites (opaque ×2, breach interior, and the carve-invert pass). When
absent or empty the original inline walk runs; otherwise `compose_node_worlds`
does the identical chain with locals swapped in.

### 3.4 Rig data

`engine/appc/articulation.py`, keyed by **hardpoint leaf** (matching
`hardpoint_overrides.apply(leaf)`):

```python
Part(node="left wing",   pivot=(-0.16, 0.0, 0.05), axis=(0.0, 1.0, 0.0), angle_deg=45.0),
Part(node="left wing01", pivot=( 0.16, 0.0, 0.05), axis=(0.0, 1.0, 0.0), angle_deg=-45.0),
```

⚠️ **These are SHIP units** (the code's actual values since `fd6d0c60`), the same
frame `PART_BOXES` and subsystem mounts use — a wingtip hardpoint is authored at
`x = 1.008`, not `100.8`. The rig is converted to MODEL (raw NIF) units, a factor
of 100 larger, **only** at the one C++ call site,
`host_loop._sync_ship_articulation`, via `MODEL_TO_SHIP`. This section is the
TUNING reference: an earlier draft printed the model-units figures (`±16, 0, 5`)
here, which is a 100x error if copied into a live edit — exactly the mix-up that
made part attribution silently never fire once (see `part_severance`'s module
docstring). Tune from the ship-units numbers above.

Angle **signs are load-bearing** and shipped wrong on the first pass: rotating
right-handed about +Y, a positive angle lifts the port wing and *sinks* the
starboard one. `tests/unit/test_articulation.py` rotates the real tip coordinate
and asserts it rises — that test caught it before it ever rendered.

**Tuning:** pure Python, so no rebuild. Because the hinge axis *is* the Y axis, a
pivot's **Y component is inert** — only X, Z and the angle are live. Dev key
**K** cycles `follow-alert / 0 / 0.5 / 1`; judge pivots at **0.5**, where a wrong
hinge shows as the wing sweeping through the hull.

### 3.5 Why the data lives here, not in `hardpoint_overrides.py`

That file is machine-owned ("the SPV regenerates this file on save") and shaped
around subsystem properties. A hinge is neither. The **keying matches**, so this
folds into the SPV-authored file once the gizmo can place a pivot — which is the
intended end state, because authoring hinges by hand-tuning floats is miserable
and the SPV already has translate/rotate gizmos, oriented boxes and undo.

### 3.6 Status

Gate clean (`scripts/check_tests.sh`: ctest 0 failures, pytest 1 — the baselined
`test_engineer_emitters` entry). 17 unit tests. Live-verified 2026-09-23.

---

## 4. Phase 2 — parts as frames (NOT BUILT)

### 4.1 The defect

A hardpoint's world position is computed against the **body**. It should be
computed against its **part**. Two symptoms, one cause:

1. **RESOLVED 2026-09-23.** At full deflection a wingtip travelled ~0.85 ship
   units (~150 m) while the cannon hardpoint did not move. Normally hidden
   (wings-up <-> weapons cold), but entering red alert powers weapons instantly
   while the wings take 2 s to come down, so the cannons fired from
   progressively wrong positions for those two seconds — exactly when combat
   starts. Fixed by routing mounts through `articulation.part_transform_point`
   inside `subsystem_world_position`, the single choke point that firing
   origins, the SPV pins, `phaser_overlay` and `target_reticle` all share.
2. **WITHDRAWN 2026-09-23 — this was never a defect.** An earlier draft claimed
   `hull_breakup._destroy_subsystems_inside` and
   `part_severance._destroy_subsystems_on_part` were broken because they test a
   "static body-frame mount". They are correct: `PART_BOXES` are authored in the
   REST pose, the voxel side never sees `node_overrides`, and the `.dhv` SDF is
   baked from the NIF. **The structures these two functions compare against
   stay rest-pose.** Transforming the mount there would mismatch frames
   and misattribute. Pinned by
   `test_subsystem_kill_uses_the_REST_mount_even_mid_travel`.

   **Evaluated 2026-09-23 — did not arrive.** §4.3's collision pieces do
   articulate now, but neither of these two functions reads them: they
   compare against `PART_BOXES` and the damage field, both of which the
   design keeps rest-pose by transforming the QUERY, never the baked
   structure. See §4.3.1 for the full argument.

**One fix, one symptom.** Parenting hardpoints to parts fixes the firing origin
(symptom 1): the cannon now follows the wing. The sever-kill path needed no
fix — it already reuses the same part-assignment rule (`part_for_point`), just
applied to the authored REST mount rather than the articulated one, which is
exactly right because those two comparisons stay rest-pose-consistent
throughout (§4.3.1). No new destruction machinery is needed — see §7.

### 4.2 Hardpoint → part assignment

**Proximity proposes; a margin decides; ambiguity falls back to the body.**

For each hardpoint, take the minimum distance to each part's vertex cloud. Assign
to the nearest part **only when the runner-up is ≥5× further**; otherwise assign
to the body.

Measured on the Bird of Prey (NIF units):

| subsystem | nearest | dist | runner-up | dist | margin | assigned |
|---|---|---|---|---|---|---|
| `Fwd Torpedo` | head | 0.5 | body | 52.5 | 105× | head |
| **`Port Cannon`** | **left wing** | **1.4** | body | 111.6 | **80×** | **left wing** |
| **`Star Cannon`** | **left wing01** | **1.4** | body | 111.5 | **80×** | **left wing01** |
| `Disruptor Cannons` | head | 3.1 | body | 35.9 | 12× | head |
| `Torpedoes` | head | 3.9 | body | 36.0 | 9× | head |
| `Hull` | body | 2.9 | left wing01 | 15.7 | 5.4× | body |
| `Shield Generator` | body | 3.4 | left wing01 | 16.7 | 4.9× | body (fallback) |
| `Cloaking Device` | head | 2.9 | body | 7.8 | 2.7× | body (fallback) |
| `Port`/`Star Warp` | wings | 5.6 | body | 8.5 | 1.5× | body (fallback) |
| `Impulse Engines` | ⚠ left wing | 9.4 | body | 12.6 | 1.3× | body (fallback) |
| `Warp Engines` | body | 9.6 | left wing01 | 9.8 | 1.02× | body (fallback) |

Two properties make this safe:

- **The cases that matter are not close calls.** Both cannons are 80× decisive.
  No tolerance tuning is required to get the thing this feature exists for.
- **The fallback is free.** Body-attached *is* today's behaviour, so an
  unresolved hardpoint is a no-op, never a regression.

Nearest-wins alone would be actively wrong: `Impulse Engines` would land on the
**port wing** (9.4 vs 12.6) — asymmetric nonsense for a single centreline-ish
subsystem. The margin rule rejects it.

Conservative by design: `Port Warp`/`Star Warp` fall back to the body even though
a BoP's nacelles genuinely *are* on the wings. That is the rule declining to
guess, and exactly the case for a hand override once the SPV can author one.

Assignment is computed **once at load** and cached per ship, never per tick.

### 4.3 Consuming the part frame — TRANSFORM THE QUERY, NEVER THE STRUCTURE

**Revised 2026-09-23.** An earlier draft of this section said "one sub-BVH per
part" and "one `.dhv` volume **per part**". That is the wrong design: it
multiplies memory by the part count and runs into the voxelizer's resolution
ceiling (`project_voxelizer_resolution_collapse`), which is why this section
previously carried an unmeasured risk. The risk is not worth measuring, because
the bake does not need to change at all.

**Every baked structure stays WHOLE-HULL and REST-POSE, shared across instances
exactly as today. Only the QUERY moves into part-local space.**

| system | today | fix |
|---|---|---|
| **hardpoint mounts** | `body · local` | ✅ BUILT — `part_world · local` via `articulation.part_transform_point` |
| **render passes** — `cloak_pass`, `hologram_pass`, `model_draw_helpers` (shadow pre-pass, breach) | static node walk | thread `node_overrides`, identical to what `draw_model` already does |
| **picking** (`ray_trace.cc`) | ✅ BUILT — each `TraceTri` carries its node index; the BVH walk SKIPS overridden nodes and one linear sweep re-tests them with the **RAY** transformed into each part's rest frame. NO partitioning, no sub-BVH: the BVH build reorders `tris`, so a node's triangles are not a contiguous range, and the sweep runs only for a rigged hull away from rest. ⚠️ The coarse bounding-sphere reject had to be SKIPPED when overrides are present — its AABB is measured at rest, so it rejected rays aimed at a moved part before any triangle was tested. |
| **collision pieces** (`aabb.cc` → `hull_bounds.py`) | pieces in model space | tag each piece with its part at build; transform per instance at query, where `hull_bounds.py` already applies position + rotation + scale |
| **hull volume** (`.dhv`) | whole-hull rest-pose SDF | **NO SEPARATE WORK.** There is no sim-side point query against the .dhv — it is baked by `hull_volume.py` and sampled on the GPU in model space. The only thing that WRITES into it is a carve — and a carve is NOT written into the `.dhv` at all: it goes into the separate per-instance carve field, in posed space, needing no transform (see the damage-carve row; the rest-space pullback this row used to describe was reverted). The `.dhv` itself is only READ, by `fill_for_gate`, with a posed point — a pre-existing rest-vs-posed mismatch this work did not introduce and did not fix. Keeping the field rest-pose preserves model-level sharing AND keeps §4.3.1's rest-pose comparisons valid. |
| **glow regions** (`glow_region.cc`) | authored model-space positions | **Not transformed — silenced instead.** Anything emitting from a DETACHED part stops: cast light already did (emitter intensity is gated on the parent subsystem's glow state, which severance zeroes), and particle controllers now do too (`part_severance._silence_emitters_on`). Transforming glow capsules into the live pose buys nothing today — no rigged hull has one — and is re-openable if one ever does. |
| **damage carve** | entries in body space | **NOTHING TO DO — measured 2026-09-23.** The carve field is sampled in **POSED body space**, so a carve struck on a moved part already lands where the shader looks for it. The field is per-INSTANCE and mutable (`instance_field_cache.h:19` — explicitly contrasted with the per-SOURCE immutable `HullVolumeCache`), so there is no sharing to protect. `opaque.vert:19-22` builds `v_position_ws = u_model * a_position` where `u_model` is `world_per_node[i]` from `compose_node_worlds(model, world, *node_overrides)` (`frame.cc:652`) — overrides INCLUDED — while `opaque.frag:1122` reconstructs `p_body = u_ship_world_inv * v_position_ws` with `u_ship_world_inv = inverse(inst->world)` (`frame.cc:431/474/546`), the INSTANCE inverse with NO override. Deposit at `world_to_body(inst->world, pw)` is the same posed point, so the two already agree. A rest-space pullback was built (eb6fedc8) and **REVERTED**: depositing at rest coords while the shader samples posed coords writes where nothing reads — no hole on the struck wing, and a spurious hole wherever the rest coordinates land. ⚠️ Separately, the SOURCE-keyed `.dhv` backing-material gate (`fill_for_gate`) IS rest-pose and is handed that same posed point — a real mismatch, but **PRE-EXISTING and unchanged by this work**, and the one thing a future per-draw rest transform would actually fix. |

**Why this is strictly better than per-part bakes.** No re-bake, no extra
memory, no resolution risk, and model-level sharing survives — a squadron of
Birds of Prey costs one set of structures, as now. The per-instance cost is a
handful of matrix inverses.

**Two facts that make it viable, both checked:**

- `trace_accel` is `mutable std::shared_ptr<void>` on `assets::Model`
  (`model.h:127`) — shared by every instance of that hull. Partitioning its
  triangles by part keeps that sharing; posing it per instance would destroy it.
- The opaque pass already draws **per node**
  (`prog.set_mat4("u_model", world_per_node[i])`), so a per-draw uniform can
  carry a part's inverse transform without the shader needing to know node
  identity. This matters because **`sampler3D` in `opaque.frag` miscompiles on
  this Mac's GL driver** — measured and bisected, see
  `project_opaque_frag_sampler3d_miscompile` — so anything field-related must
  stay CPU-side or per-draw.

**Rejected:** baking two whole-hull volumes (armed/cold) and switching between
them. Cannot represent mid-travel, doubles memory, and hits the same ceiling.

**⚠️ THE PREMISE ABOVE CONFLATED TWO DIFFERENT CACHES — recorded so it is not
repeated.** "Every baked structure stays WHOLE-HULL and REST-POSE, shared
across instances" is true of some of them and false of the one this section
then reasoned about. There are two kinds:

- **SOURCE-keyed, immutable, genuinely shared** — `voxel::HullVolumeCache`
  (the `.dhv` SDF) and `assets::Model::trace_accel` (the BVH). One per hull
  MODEL, reused by every Galaxy in the sector. A live-pose query against one
  of these really does have to be pulled back into rest space, which is what
  `ray_trace.cc` does for the RAY and what `renderer::part_frame.h` would do
  for a POINT.
- **INSTANCE-keyed, mutable, NOT shared** — `renderer::InstanceFieldCache`,
  the damage carve field. Its own header opens by contrasting itself with the
  above: one battle-scarred field per ship, copying only the baked LATTICE.
  Nothing here is shared, so nothing here needs protecting by a rest-space
  pullback — and it is sampled posed anyway.

Reading "baked" as "shared and therefore rest-pose" across both is the error
that produced eb6fedc8, a fix for a bug that did not exist which introduced a
real one. **Check which cache a structure lives in, and check what space the
consumer samples it in, before transforming anything.**

### ✅ 4.3.1 Ruling 1 STANDS — this section's earlier prediction was wrong

**Superseded 2026-09-23, before implementation.** This section previously
predicted that §4.3 would reverse Ruling 1 and require inverting
`test_subsystem_kill_uses_the_REST_mount_even_mid_travel` in both
`tests/unit/test_part_severance.py` and `tests/unit/test_hull_breakup.py`.

**It does not, and they must not be touched.** The prediction assumed the
sim's BOUNDS would move into the live pose. Under "transform the query, never
the structure" they do not:

- `part_severance._destroy_subsystems_on_part` tests a rest mount against
  `PART_BOXES`, authored rest-pose and unchanged. Which part a subsystem sits
  on is a STATIC property of the hull, not a function of where the part
  currently happens to be.
- `hull_breakup._destroy_subsystems_inside` tests a rest mount against a
  carved component from `hull_split_detached` — the damage field. ⚠️
  **CORRECTED 2026-09-23:** that field is per-INSTANCE and is written AND
  sampled in POSED body space (see the damage-carve row of §4.3), not rest
  space; an earlier draft here claimed carves were pulled back to rest, which
  was built and then reverted. So on a rigged hull away from rest this test
  compares a REST mount against a POSED component. That is a real mismatch —
  but it is the same rest-vs-posed gap `record_hit` and the `.dhv` gate carry,
  pre-dates this work, and is out of its scope. It bites only a hull that is
  both rigged and deflected, i.e. a Bird of Prey with its wings up.

Collision pieces (`hull_bounds.py`) genuinely do articulate, but no subsystem
kill reads them: `hull_spheres_world` / `hull_spheres_near` /
`point_is_inside_hull` have exactly two consumers, `collisions.py:248` and
`collision_avoidance.py:600`, neither of which touches subsystems.

So both tests remain correct as written, and their docstrings stay as the
record of why. The one claim inside them that is now too broad is "the sim
never articulates" — narrow it in place to "the structures these compare
against are never articulated", and leave everything else alone.

**The general lesson, worth more than the ruling:** a design that moves
queries instead of structures keeps every rest-pose comparison in the codebase
valid for free. That is the property to preserve when this is extended.

### 4.4 Ordering

Hardpoint parenting (§4.2 + row 1 of §4.3) is independently valuable and fixes
the live bug. Picking, hull volume and carve can follow separately. They are one
design but need not be one change.

---

## 5. Severance: which mechanism owns what

**Revised 2026-09-23 after a live session.** An earlier draft of this section
rejected node-parts as a severance unit outright, on the grounds that voxel
connectivity yields *emergent* damage shapes an authored split cannot. That
reasoning holds **for the hull**. It does not hold for appendages, and §2.6 is
why.

**The evidence.** A Bird of Prey's wing attaches through a 14 × 7-unit neck at
(±0.225, −0.563, −0.038) — aft, against the hull, at mid-height. Under voxel
connectivity that neck is the ONLY place a wing can be severed. Shooting the
wing itself — its visible span, its tip, the cannon mounted on it — can only
punch holes *in* it. Confirmed live: repeated fire at the wing span never
detached anything, because nothing there is load-bearing.

That makes the mechanic unusable in practice. The weak point is the least
visible part of the ship, nothing about the hull signals it, and a player has to
know the mesh topology to exploit it. **A mechanic that requires reading the
model is not a mechanic.**

### The split

| | mechanism | governs | why |
|---|---|---|---|
| **hull** | voxel connectivity (shipped, unchanged) | emergent chunks from wherever damage landed | arbitrary shapes; no authoring |
| **appendages** | **node-parts** | a part accumulates damage and shears at its **authored break point** | the break point is visible, expected, and already authored |

Shoot a wing anywhere → it detaches at the hinge → the cannon on it dies with it
(§4.1's existing `_destroy_subsystems_inside` path, once hardpoints are
parented).

### Why this is nearly free

**The articulation pivot IS the break point.** Phase 1 already authors
`(±0.16, 0, 0.05)` (ship units) as the BoP's wing hinge — the point the wing
rotates about is exactly the point it should shear at. No new authored data.

**Damage attribution comes from §4.2.** The proximity-with-margin rule that
assigns hardpoints to parts assigns *hits* to parts by the same measure, so
"damage to the left wing" is a quantity phase 2 computes anyway.

So what appendage severance adds over phase 2 is a per-part damage accumulator
and a threshold — not a new decomposition.

### What does NOT change

Voxel connectivity keeps the hull, exactly as
`2026-09-11-breakable-hull-components-design.md` specifies. Chunks remain what
that spec decided they are: visual debris that collides — not targetable, no
hull HP, no subsystems of their own. A severed node-part becomes the same kind
of chunk, so nothing downstream learns a new object type.

---

## 5a. Phase 2a — appendage severance by damage share (BUILT)

**The rule.** Each authored detachable part accumulates the hull damage
attributed to it. At its authored share of the ship's MAX hull it shears off.
Cumulative, never decaying — chip at a wing across a whole battle and it still
comes off. Currently **0.20** for both BoP wings: 800 damage on a 4000-hull
ship, so both wings cost 40% of the hull.

A part total is an **attribution, not a second HP pool**: the hit still does its
normal hull damage. The total only decides when the part gives way.

**Attribution** (`part_severance.part_for_point`). Authored per-part AABBs in
ship units (`articulation.PART_BOXES`). Inside exactly one box wins; inside
several is **ambiguous and resolves to None**; outside all, the nearest wins
only by a 5× margin. None means unattributed — the hit behaves exactly as it
did before this existed.

The ambiguous case is the norm near the hull, by design: a BoP's wing boxes
overlap the body box from |x| 0.1236 to 0.31 because the roots are embedded.
So only OUTBOARD wing hits count — which is also where a player naturally aims.

**Detachable parts are authored** (`articulation.DETACHABLE`), never derived.
The body must never detach and the head is deliberately excluded. A part absent
from that table accumulates nothing and can never be lost.

**On sever** (`part_severance.sever`), in this order:
1. mark detached FIRST — a re-entrant hit (from a subsystem-destruction event)
   cannot shear the same part twice and spawn two chunks;
2. destroy subsystems whose mount lies on the part — `SetCondition(0.0)` through
   the normal damage path, mirroring `hull_breakup._destroy_subsystems_inside`.
   The Star Cannon dies with the starboard wing;
3. hand to the renderer, **best-effort**: a part gone from the sim but still
   drawn beats an exception unwinding through combat.

**Rendering** (`part_detach_render`). The ship hides the part; a second INSTANCE
OF THE SAME MODEL hides every part except it. Both use the new
`set_instance_node_hidden` binding, which writes the zero matrix as a node's
local so its subtree collapses. No mesh splitting, no generated geometry, and
models are shared by handle — a severed wing costs a transform and a draw.
Mass comes from the part's AABB volume share (`debris_chunk.spawn` uses its
cell counts only as a ratio).

**The hook** sits in `hit_feedback` **outside the carve throttle**. That
throttle drops ~14 ticks in 15 to bound carve emissions and breach VFX;
inheriting it would make a wing need ~15× the fire. It is also not gated on the
carve itself — severance asks "has this wing taken enough", which is true
whether or not hull geometry happened to break there.

⚠️ **Known couplings, accepted for 2a:** the hook lives inside the block gated
on `allow_hull_carve and persist_decal and damage_eligibility.is_eligible`, so
god mode and decal-suppressed hits also suppress severance. Defensible (god mode
should not shed the player's wings) but not deliberate design.

⚠️ **The cut is CLEAN, not torn.** Voxel chunks get a ragged face free from the
carve field; a node-part sheared at an authored boundary has none. Carving the
stump is the follow-up if it reads wrong at close range.

**Status:** gate clean, 17 unit tests. ✅ **Live-verified 2026-09-23** — a wing
shears off, and the scenario reads well in play.

⚠️ One part of 5a is fixed by construction but **never observed**: the
one-frame chunk-at-origin artefact (a collision-triggered severance used to draw
the wing at the world origin at 100× scale for a single frame, because
`Instance::world` defaults to identity — model units). `part_detach_render`
now sets the world transform before the chunk can be drawn, and review verified
the ordering against `debris_chunk.tick` / `collisions.tick_collisions`. But a
one-frame flash is not realistically observable, so this rests on reasoning, not
on eyes.

---

## 5c. Live verification log

**2026-09-23, QuickBattle, player Bird of Prey.**

| checked | result |
|---|---|
| Wing articulation follows alert level | ✅ confirmed, and read as accurate to the films first time |
| Hull damage / crater size after the carve retune | ✅ confirmed ("looking better now") |
| A wing shears off at its damage share | ✅ confirmed |
| Cannons follow the wings (§4 hardpoint parenting) | ✅ confirmed — beams leave the moving guns |
| A severed wing is NOT re-posed on an alert change (C1) | ✅ confirmed — "handled well by the game" |
| The severed wing carries the hull's Fresnel rim (I2) | ✅ confirmed |
| One-frame chunk-at-origin artefact (I2) | ⚠️ **not observable**; fixed by construction only |

**2026-09-23, second session — plan 1 (node overrides in the render passes).**

| checked | result |
|---|---|
| Cloak with the wings UP — they stay up through the fade | ✅ confirmed |
| Cloak with a wing SEVERED — it stays gone through the fade | ✅ confirmed |
| NPC wings follow a target (OQ-11) | not yet isolated |
| Shadows follow a moved wing | not yet isolated |
| Breach drawn against the live wing pose | not yet isolated |

The two cloak checks are the ones that mattered: the Bird of Prey is BC's only
cloaking ship, so the rest-pose snap had nowhere to hide. Before plan 1 a
cloaking BoP snapped its wings DOWN for the whole fade and regrew a severed
one.

**A FATAL crash was also found in that session, and it was PRE-EXISTING.**
`GetParentShip()` returned the bare `_parent_ship` field, which
`ShipClass._attach_subsystem` sets only on TOP-LEVEL subsystems — so on a
pulse-weapon EMITTER (a child of its weapon system) it was always None.
`ConditionPulseReady` stamps that onto an event source and immediately
dereferences it, and the AttributeError unwinds out of the host frame loop.

It needed a sustained pulse-weapon fight to trigger, which is exactly what
testing this feature produces. It had been recorded as a known gap in TWO
places — the stbc-oracle ledger, and a docstring in `weapon_subsystems.py`
warning readers to use `_climb_to_ship()` instead — and still reached a fatal
in play. **A BC-facing method that is PRESENT BUT WRONG is caught by neither
the constant surface nor the stub heatmap**, which both guard against surface
that is MISSING. Fixed in `df897e19`.

**2026-09-23, third session — plan 2 (picking).**

| checked | result |
|---|---|
| A raised wing is hit where it is DRAWN | ✅ confirmed (after one fix) |
| Manual aim (H) picks the live wing pose | ✅ confirmed |

⚠️ **Failed live on the first attempt**, and the cause is worth keeping. An
override NAMES a part node, but the MESH hangs off that node's CHILD —
`model_build`'s `find_parent_node_index` attaches geometry to its immediate
`NiNode` parent, and BC ships interpose a `__NDL_MultiMtl_Node` between a part
and its shapes (§2.1 of this very document). So a wing's triangles carry the
MultiMtl node's index and a filter keyed on the triangle's own node never
matched. The renderer was always right because `compose_node_worlds`
propagates an override down the chain.

**The unit tests passed while the game was broken** because the synthetic
model put the mesh DIRECTLY on the overridden node — two levels where a real
BC ship has three. Rebuilding the fixture to mirror the real hierarchy turned
three tests red at once, including "a severed part cannot be hit", so severed
wings had been hittable in play as well.

**Three failures were found live that no test caught**, which is why this log
exists rather than a bare "verified":

1. **Craters stopped appearing entirely.** `STRENGTH_PER_HULL` was cut 1.0 →
   0.25 against a ship's TOTAL hull HP, but carve strength accumulates PER SITE
   — the only denominator that matters is damage at one point. Reverted; see
   §7 OQ-1.
2. **Part attribution never fired once.** `world_to_body` returns MODEL units and
   `PART_BOXES` are SHIP units, so every hit arrived 100× too large and matched
   nothing. The tests missed it because they were written in the same wrong units
   as the code.
3. **A wing could not be shot off at all.** Voxel connectivity runs on the UNION
   of body and wing, where the root is embedded in the hull — so the only
   severable cross-section is invisible and, in practice, unhittable. That
   measurement is what produced §5.

Each was invisible to a green suite. The `--developer` severance readout
(`[severance] left wing01: 400/800 (50%)`) exists because of (2): attribution
failing looks exactly like a player missing.

---

## 5b. Phase 2b — authoring detachability in the SPV (NOT BUILT)

Phase 2a's data is two hand-written dicts in `articulation.py`. This is where
they are meant to end up, recorded here because it was an assumption carried in
conversation rather than a plan.

### What is derivable and what is not

| | source |
|---|---|
| the part list | the NIF — named `NiNode` children of `Scene Root` |
| **part AABBs** | **derivable** — a `model_part_bounds` binding gives these at runtime for every ship, no markup and no drift (OQ-9) |
| **which parts detach** | **authored** — a genuine design decision |
| threshold | authored, defaulting to 0.20 |

So per ship the human act is: tick two parts, accept a default. Measuring
geometry by hand — which is what the Bird of Prey actually cost — is busywork
that should not survive.

### A geometric heuristic CANNOT decide detachability

Recorded so it is not re-derived. Define **clean %** as the share of a part's
AABB lying inside no other part's AABB — the fraction of hits that can
attribute to it. Measured across six stock hulls:

| ship | part | clean % |
|---|---|---|
| Bird of Prey | `left wing` / `left wing01` | **94%** |
| | `head` | 80% |
| | `birdofprey` (body) | 43% |
| Akira | `OuterWing02` / `OuterWing03` (nacelles) | **90%** |
| | `Middle Wing` | 82% |
| | `Saucer` | 78% |
| | `Arm02` / `Arm03` | **30%** |
| Warbird | `rom head` | 95% |
| | `rom engine left` / `right` | 86–87% |
| | `rom wing top left` / `right` | 60% |
| Sovereign | `Mesh02` / `Mesh03` | 96% |
| | `top o dish` | 93% |
| | `Hull` | 74% |
| Galaxy | `Ent-D Saucer Section` (sole part) | 100% |
| Keldon | `hull top box` | 92% |
| | **`wing left`** | **88%** |
| | **`wing right`** | **59.5%** |

The rule *"detachable = clean % ≥ 85% and not the largest part"* reproduces the
hand-authored Bird of Prey and Akira answers **exactly** — and is nonetheless
wrong. It was fitted to those two ships and fails on the next two:

- **The Keldon's mirror-image wings score 88% and 59.5%.** Two identical parts,
  opposite verdicts. That alone disqualifies the metric as a decision rule.
- The Keldon would also shed `hull top box` (92%) and `tail mid` (89%) —
  structural centre sections.
- The Warbird would shed `rom head` (95%), the command prow, while EXCLUDING
  both top wings (60%) — the parts one would actually want to shoot off.
- The Sovereign would shed `top o dish` (93%), the deflector.

Clean % measures **AABB tidiness**, not "is this an appendage". The two
coincided twice by luck. Detachability is a design judgement and stays authored.

### Clean % keeps a job — as a WARNING

It does predict how a part will FEEL once marked. A part at 30% attributes only
~30% of hits, so it takes ~3× the fire and reads as arbitrary. The SPV should
say so at author time rather than let it be discovered live — which is how the
Akira's arms would otherwise be found out.

### The panel

Over existing plumbing: `hardpoint_override_writer.py` and the SPV
hardpoint-value editing (`2026-07-25-spv-hardpoint-value-override-editing-design.md`)
already regenerate the machine-owned per-ship file. Detachability is a new
panel on that, not new plumbing.

1. `model_part_bounds` binding — parts and boxes at runtime.
2. SPV panel — part list, detachable toggle, threshold, writing through the
   existing override writer.
3. Clean-% advisory on each part.

### Ordering, deliberately

**Author a second ship BY HAND first** (the Akira nacelles: 90% clean, and
`Port Warp`/`Star Warp` resolve to them at a 5.7× margin, so losing one costs
a warp engine). Only then build the binding and the panel.

Building the editor before the second ship means designing a UI for a data
shape that has been validated exactly once. The Bird of Prey alone did not
reveal that boxes should be derived rather than authored; a second ship is what
makes that obvious.

---

## 6. Testing

Phase 1 ships `tests/unit/test_articulation.py` (17 tests): rig shape, mirroring,
alert→pose mapping, ease behaviour, rest-pose identity, degenerate-axis safety,
and two geometry assertions that pin the pivots to the measured hull (pivot |X|
within the wing-root band; full deflection raises the real tip coordinate).

**What tests cannot see: whether the pivots look right.** That is why phase 1 was
built as a spike with a dev key before this spec was written — the numbers were
confirmed on screen first, and this document records settled values rather than
guesses.

Phase 2 additions: assignment margin behaviour (including that `Impulse Engines`
lands on the body, not a wing); mount position under articulation; a seam-hit
picking case; and a two-site realize test for the cached assignment, following
`test_hull_bounds_wiring.py` — per the rule that any per-ship realize side effect
goes in ONE helper called from BOTH `realize_set_objects` and
`_MissionLoader._realize_session`.

---

## 7. Open questions

**OQ-1 — RESOLVED 2026-09-23.** The Bird of Prey could not shed chunks at all:
`breakables_allowed_for` gated on `radius > 2.381` (a Galor) and the BoP sits at
~1.34 GU. That figure carried no technical rationale. The floor is now **0.6 GU**,
derived from the carve curve — a hull must be meaningfully larger than the
maximum combat carve (`kHullCarveRadiusMaxGu`). Five ships became breakable:
BirdOfPrey, Freighter, CardFreighter, Marauder, Galor. Only the Shuttle
(0.141 GU, a 5×6×4 voxel grid) stays out.

Done alongside a **carve size reduction**: `kHullCarveRadiusMaxGu` 0.3 →
**0.15 GU** (26.25 m, ~4% of a Galaxy's length, where 0.3 was ~8% and exceeded
an entire shuttle). The Shuttle is excluded on the voxel-grid argument alone
(5×6×4 cells).

⚠️ **A second change was attempted and REVERTED the same day:**
`STRENGTH_PER_HULL` 1.0 → 0.25, intended to make hulls carve less readily.
Craters then stopped appearing entirely across three live battles. The error was
a category mistake — it was calibrated against a ship's TOTAL hull HP, but carve
strength accumulates **per site** (merged within ~0.09 GU), so the only
denominator that matters is damage delivered at ONE POINT. One full hit is
~200–250 absorbed hull against a C++ iso of 150; at 0.25 it takes four hits
within ~15 m of each other. **Hole SIZE is `kHullCarveRadiusMaxGu`; hole
READINESS is `STRENGTH_PER_HULL`, and readiness must stay within reach of a
single hit.** Guarded by `test_one_full_strength_hit_can_open_a_hole`.

**OQ-2 — Seam hits mid-travel.** How a hit landing between wing and hull resolves
when the wing is part-way through its travel is unknown. Expected to need
handling; cannot be predicted from reading.

**OQ-3 — Per-part `.dhv` resolution.** Each part is smaller than the whole hull,
so per-part bakes *should* sit further from the ~96³ collapse threshold. That is
reasoning, not a measurement.

**OQ-4 — RESOLVED 2026-09-23 (final review, finding C1).** A severed articulated
part was still being driven by the pose: `host_loop._sync_ship_articulation`
pushed a rotation for every rigged part on every deflection change with no
regard for severance, overwriting the same `node_overrides` slot
`set_instance_node_hidden` used to hide it — a shot-off wing snapped back onto
the hull and re-animated with the good one, and a subsequent `theta == 0` push
erased the hide permanently. Fixed by consulting `part_severance.is_detached`
in both `_sync_ship_articulation` (skip the part entirely) and
`articulation.part_transform_point` (leave a detached part's mount point
unmoved). See `tests/unit/test_part_severance.py`'s render-sync regression
test.

**OQ-5 — Should `Port Warp`/`Star Warp` be wing-parented by hand?** The margin
rule conservatively assigns them to the body. Physically they are on the wings.
Deferred to SPV authoring.

**OQ-6 — RESOLVED as a first cut, 2026-09-23.** A fraction of the ship's MAX
hull, authored per part, at **0.20**. Built as §5a. Still wants live eyes: the
failure modes are "wings fall off in a skirmish" and "wings never come off", and
neither is visible from a test. The number lives in `articulation.DETACHABLE`
and tunes with no rebuild.

**OQ-10 — Should detachability have a default at all?** Phase 2b keeps it
authored per ship, so a hull nobody has marked up sheds nothing. That is safe
and also means the feature is invisible on most of the fleet until someone does
the work. Whether an unmarked ship should stay inert or get some conservative
default is unresolved; §5b only establishes that a GEOMETRIC default cannot be
trusted to pick the parts.

**OQ-9 — Per-part AABBs are AUTHORED, not derived.** `model_bounds` returns
unnamed per-shape spheres that cannot be mapped to a named node, so §5a's boxes
were measured offline and written into `articulation.PART_BOXES`. A
`model_part_bounds` binding would derive them and remove the chance of the data
drifting from the mesh. Not worth a new boundary against a data set of one ship;
revisit at the second.

**OQ-7 — Carve radius vs bake quality.** `kDefaultQuality = 2` was chosen
because *"a maximum-size carve is 0.3 GU = 30 model units, which at a Galaxy's
authored cell of 10 is a 3-CELL radius — too coarse to read as a torn hole. At
2x it is 6."* Halving the max carve to 0.15 GU (OQ-1) puts it **back to a 3-cell
radius**, i.e. exactly the coarseness that comment rejects. Craters may now read
blocky. Untested. If they do, raising `kDefaultQuality` to 4 restores the 6-cell
ratio at ~8× bake cost and ~58 MB fleet-resident (from 7.2 MB) — both one-off
and affordable, but not free.

**OQ-8 — Is there a second narrow band on the wing?** §2.6's slab probe hints at
one around X ≈ 38–45, which would mean a mid-wing shot could shed the outboard
section (and the cannon with it). The sampling was too coarse to trust — 8 of 14
slabs were skipped. Needs a finer measurement before anything relies on it.

**OQ-11 — RESOLVED 2026-09-23. The driving signal differs by who flies the
ship.**

*The problem.* `ShipClass.__init__` defaults `_alert_level` to `RED_ALERT` and
nothing ever calls `SetAlertLevel` on an NPC — only the player's alert keybind
and `engine.dev_missions.combat_stress`. So keying wings off alert level left
every AI Bird of Prey permanently attack-posed, and the transition was reachable
only on a player-flown ship.

*Why the obvious fix is wrong.* The RED spawn default is not arbitrary: it is
**measured on the original exe** across eleven campaign missions (stbc-oracle
bible §13 N2 — every non-player ship, station and asteroid reads alert 2 from
the first snapshot, and `MissionLib.CreatePlayerShip` explicitly sets the player
GREEN, an instruction that only makes sense against a red default). Lowering it
to make wings work would trade a verified BC behaviour for a cosmetic one.

*The resolution.* `articulation.deflection_target_for(ship)`:

| ship | signal | why |
|---|---|---|
| **player** | alert level | the alert keys are how a human tells the ship to brace |
| **NPC** | **does it have a target** | the SDK's `SelectTarget` preprocessor sets one at runtime (`ai_driver.py:1452`), so it is the one signal that actually varies |

The asymmetry is deliberate. Alert level is left exactly as measured; we simply
stop treating it as a combat signal for ships it was never a combat signal for.
An NPC BoP now cruises with its wings up until it acquires a target, then drops
them — which is the canon beat, and costs no AI work.

Falls back to alert level for any object without `GetTarget`, so a prop or test
double holds its spawn pose rather than raising on the 60 Hz tick.

⚠️ **Not yet live-verified.** And note it interacts with OQ-12: shooting a
*raised* NPC wing still resolves against rest-pose geometry, so until picking is
fixed the NPC-side transition is watchable but its raised wing is not reliably
hittable.

**OQ-12 — Added 2026-09-23 (final review, finding G2). Node overrides are
honoured in exactly one draw path.** `Instance::node_overrides` (articulation's
rotations and severance's hides) is read by `draw_model` only. Eight other
places walk `nodes[i].local_transform` statically and never see an override,
notably:

- `cloak_pass.cc` — the Bird of Prey is BC's one cloaking ship, so cloaking with
  wings up snaps them back to the rest (down) pose for the whole cloak fade, and
  a severed wing grows back for it.
- the shadow depth pre-pass — a severed or deflected wing casts its REST-pose
  shadow.
- `breach_pass.cc` — a hull breach on an articulated/severed ship is drawn
  against the wrong wing pose.
- `ray_trace.cc` — weapon impact points resolve against rest-pose geometry, so
  a shot at a deflected or severed wing can trace against where the wing
  *would* be at rest rather than where it is drawn.

None of these were touched by that fix wave.

**DESIGNED §4.3. RENDER HALF BUILT AND LIVE-VERIFIED 2026-09-23** (plan
`docs/superpowers/plans/2026-09-23-node-overrides-render-passes.md`): the
shadow pre-pass, cloak, hologram and breach passes now all honour
`node_overrides`. Confirmed live that a cloaking Bird of Prey keeps its raised
wings through the fade, and a severed wing stays gone through it — the two
cases where the rest-pose snap was most visible, since the BoP is BC's only
cloaking ship.

**Picking IS built and live-verified** (successor to
`docs/superpowers/plans/2026-09-23-node-overrides-render-passes.md` — the
ray-trace work; commit message "an override moves a part's CHILDREN too — the
mesh is a child"). Confirmed live by the project owner.

**Collision pieces and carve entries are built by THIS plan**
(`docs/superpowers/plans/2026-09-23-part-aware-sim-geometry.md`): pieces carry
a part tag, a severed part's pieces stop colliding, and pieces follow a part
mid-travel. The carve half of that plan was built and then **REVERTED** — the
carve field turned out to be per-instance and sampled posed, so a carve on a
moved part already lands correctly (§4.3). `renderer::part_frame.h` survives
as a tested primitive with NO production caller. **Not yet live-verified.**

**The hull volume needed no separate work** — there is no sim-side point
query against the `.dhv`; it is baked in Python and sampled on the GPU in
model space. Its only writer is a carve, covered above.

**Glow regions were not transformed** — emitters on a detached part are
silenced instead (`part_severance._silence_emitters_on`). These last two match
the corrected §4.3 table rows above.

Threading `node_overrides` is the right answer for the four RENDER paths, and
mirrors §3.3. It is NOT the answer for picking, collision pieces, the hull
volume or glow regions: those consume structures that are cached PER MODEL and
shared across instances (`trace_accel` is a `mutable shared_ptr<void>` on
`assets::Model`), so they cannot be posed per instance at all. Those transform
the QUERY into part-local space instead, leaving every bake untouched — which
also removes the per-part-volume resolution risk an earlier draft of §4.3
carried.

**Ruling 1 STANDS** — see the corrected §4.3.1: the bounds a subsystem kill
compares against never moved into the live pose, so neither
characterisation test needed inverting.
