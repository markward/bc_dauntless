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
Part(node="left wing",   pivot=(-16.0, 0.0, 5.0), axis=(0.0, 1.0, 0.0), angle_deg=45.0),
Part(node="left wing01", pivot=( 16.0, 0.0, 5.0), axis=(0.0, 1.0, 0.0), angle_deg=-45.0),
```

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

1. **Live bug.** At full deflection a wingtip travels ~88 NIF units (~60 m, over
   half the ship's length). The cannon hardpoint does not move. Normally hidden
   because wings-up ⟺ weapons cold — but on entering red alert, weapons power on
   *instantly* while the wings take 2 s to come down, so the cannons fire from
   progressively wrong positions for those two seconds. That is precisely the
   moment combat starts.
2. **Latent bug.** `hull_breakup._destroy_subsystems_inside` tests a *static
   body-frame mount* against a severed component's bounds. For an articulated
   part that is the un-rotated position, so it would kill the wrong subsystems.

**One fix serves both.** Parent hardpoints to parts and the cannon follows the
wing *and* the existing sever-kill starts testing the right point. No new
destruction machinery is needed — see §7.

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

### 4.3 Consuming the part frame

Everything that currently bakes node→model at build time instead resolves
**which part, then works in part-local space**. One idea, applied four times:

| system | today | phase 2 |
|---|---|---|
| **hardpoint mounts** | `body · local` | `part_world · local` |
| **picking** (`ray_trace.cc`) | one model BVH, node transforms baked in (`build_node_world`) | one sub-BVH **per part**; inverse-transform the ray per part |
| **hull volume** (`.dhv`) | one baked volume per model | one volume **per part**; transform the query point per part |
| **damage carve** | entries in model/body space | entries **bound to a part**, stored part-local so a scar rides the wing |

`TraceAccel` is cached on the *Model* and shared by every instance; `.dhv` is
prebaked per model file. Neither can be posed per-instance, and re-baking per
pose is not viable. Transforming the **query** instead of the **structure**
preserves model-level sharing, so memory stays flat across a squadron and the
per-instance cost is a few matrix inverses.

**Rejected:** baking two whole-hull volumes (armed/cold) and switching. Cannot
represent mid-travel, doubles memory, and runs straight into the voxelizer
resolution ceiling already hit once (`project_voxelizer_resolution_collapse`).

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
`(±16, 0, 5)` as the BoP's wing hinge — the point the wing rotates about is
exactly the point it should shear at. No new authored data.

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

**OQ-4 — Articulation vs severance interaction.** A severed articulated part must
stop being driven by the pose. **Now reachable** (OQ-1 resolved: a BoP is
breakable), so this is live work rather than theoretical, and must be handled in
phase 2 — a detached wing still receiving a pose is a visible bug.

**OQ-5 — Should `Port Warp`/`Star Warp` be wing-parented by hand?** The margin
rule conservatively assigns them to the body. Physically they are on the wings.
Deferred to SPV authoring.

**OQ-6 — What is an appendage's damage threshold?** §5 gives node-parts
appendage severance, but not how much damage shears one. Options span a flat
per-part HP, a fraction of the parent hull's HP, and a share scaled by the
part's volume. None is measured; BC has no equivalent to recover it from. Wants
live eyes: the failure modes are "wings fall off in a skirmish" and "wings never
come off", and only one of them is visible from a test.

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
