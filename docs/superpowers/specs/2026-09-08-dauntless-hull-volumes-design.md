# Dauntless Hull Volumes — design

**Date:** 2026-09-08
**Status:** design agreed, spec under review
**Branch:** `feat/dauntless-hull-volumes`
**Supersedes:** the runtime use of BC's `*_vox.nif` (`NiBinaryVoxelData`) as the
hull damage volume.

---

## 1. What this replaces, and why

Hull damage today is carried by **two representations that disagree**:

| | What it is | Where |
|---|---|---|
| Damage state | up to 24 spheres, fixed array, merge-then-evict | `native/src/scenegraph/include/scenegraph/hull_carve.h` |
| Hull material | BC's authored `_vox.nif` occupancy grid, immutable | `voxel::SourceVolumeCache` |

The sphere list decides where the hull is cut; the voxel grid decides whether a
cut is *allowed* and where the exposed interior is drawn. Because the two are
different shapes, they drift, and every hull-damage artifact of the last several
rounds traces to that drift — see the backing-material gate and the cavity-depth
gate, both of which exist purely to stop the two from contradicting each other.

This design replaces both with **one per-instance signed-distance field that is
the authoritative state of the hull**. Everything that damages a hull is a brush
writing into that field, and everything the renderer draws is derived from it.

### The unifying claim

Combat damage, death-cascade destruction, and collision deformation are not
three features. They are one operator with different parameters:

| Event | Brush | Material removed? |
|---|---|---|
| Weapon hit | subtract a sphere | yes |
| Death-cascade blast | subtract a larger sphere, repeatedly | yes |
| Collision | displace the surface inward | no |

A dent and a hole stop being separate code paths.

---

## 2. Measured findings this design rests on

Everything in this section was measured on 2026-09-08 against the live install.
Numbers, not recollection.

### 2.1 BC's hulls are essentially watertight

Boundary edges (an edge used by exactly one triangle), after welding vertices to
0.01% of the model diagonal:

| Hull | boundary | non-manifold |
|---|---|---|
| Galaxy | 0.5% | 0.0% |
| Galor | 0.1% | 1.7% |
| Warbird | 0.0% | 2.3% |
| Akira | 0.0% | 4.0% |

**Consequence:** sign-by-flood-fill is a sound way to sign the distance field.
The geometry is good; our processing of it is what has been wrong.

### 2.2 Our voxelizer silently collapses above ~96³

Solid fraction of the grid, same hull, rising resolution:

| Hull | 48³ | 96³ | 128³ | 160³ |
|---|---|---|---|---|
| Galaxy | 13.5% | 12.9% | **2.2%** | **1.7%** |
| Sovereign | 15.4% | 12.9% | **2.4%** | **1.9%** |
| Akira | 13.5% | **4.0%** | **2.4%** | **1.7%** |
| Galor | 13.6% | **3.0%** | **1.8%** | **1.3%** |

The collapsed figures scale as n², not n³: the interior is gone and only a shell
survives. Root cause is `native/src/voxel/src/voxelize.cc:71`:

```cpp
const int N = 16;  // samples per edge; dense enough to leave no gaps at grid res
```

153 barycentric samples per triangle **regardless of triangle size or cell
size**. On a Galaxy at 128³ the samples land ~5 units apart across ~6-unit
cells, so the shell develops pinholes and `solidify`'s flood fill bleeds inward.
The comment was true at 48³ and has been false ever since.

**Consequence:** raising resolution is not currently possible. Fixing the
rasterizer is a prerequisite, not an optimisation.

### 2.3 BC authors a per-ship resolution that we ignore

`ShipProperty.SetDamageResolution` is set in every hardpoint file:

| value | ships |
|---|---|
| 6 | Shuttle, EscapePod |
| 8 | Akira, KessokHeavy |
| 10 | Galaxy, Sovereign, Vorcha, Galor, Keldon, Nebula, Ambassador, BirdOfPrey, … |
| 12 | Warbird, Marauder |
| 15 | stations, DryDock, generic `Ship` template |
| 2 | Probe2, KessokMine |

Our shim captures it at `engine/appc/ships.py:856` into `self._damage_resolution`
and **nothing ever reads it**.

It is also finer than what BC actually shipped:

| Ship | authored | shipped `_vox` cell_size |
|---|---|---|
| Galaxy | 10 | 15 (1.5× coarser) |
| Akira | 8 | 15 (1.9× coarser) |
| Warbird | 12 | **25 (2.1× coarser)** |

The Warbird is the worst mismatch in the fleet and is exactly the ship observed
cutting breaches into nothing. Its `kMinCavityCells = 2.0` threshold meant 50
model units there against 30 everywhere else, because the threshold is expressed
in *cells* and the Warbird's cells are 67% larger than everyone's.

### 2.4 Volume memory is not a constraint

Grid size implied by the authored resolution (the `cell` column below IS
`SetDamageResolution`, so these are @1x; the cell size at quality q is
`authored/q`), one byte per cell:

| Ship | radius (GU) | cell | grid @1× | grid @2× |
|---|---|---|---|---|
| Shuttle | 0.14 | 6 | 5×6×4 | 8×10×6 |
| BirdOfPrey | 1.34 | 10 | 23×19×12 | 44×35×21 |
| Galor | 2.38 | 10 | 25×37×8 | 48×72×13 |
| Akira | 2.55 | 8 | 42×59×13 | 81×115×24 |
| Galaxy | 3.50 | 10 | 49×67×17 | 95×131×31 |
| Sovereign | 3.81 | 10 | 26×72×11 | 49×142×19 |
| Warbird | 6.52 | 12 | 85×107×31 | 167×212×60 |
| KessokHeavy | 7.50 | 8 | 113×126×29 | 224×249×55 |

**Whole 18-ship fleet resident simultaneously: 1.0 MB at 1×, 7.2 MB at 2×.**

### 2.5 Bake cost is a first-load-only cost

Occupancy voxelization alone (Galaxy, single-threaded, including NIF parse and
triangle collection at 0.9 ms):

| grid | time |
|---|---|
| 48³ (110 k cells) | 8.1 ms |
| 128³ (2.1 M cells) | 29.7 ms |
| 192³ (7.1 M cells) | 70.7 ms |

**Measured again 2026-09-08 against the implemented signed-distance baker**, on
real hulls at authored-resolution-over-2× cells — this is the number that
matters, and it is larger than the occupancy figures above because the SDF does
strictly more work:

| hull | cell | grid | resident | bake |
|---|---|---|---|---|
| Galor | 5 | 54×78×19 | 0.08 MB | 57 ms |
| Galaxy | 5 | 101×137×37 | 0.49 MB | 120 ms |
| Warbird | 6 | 173×218×66 | 2.37 MB | 192 ms |

Still comfortably a first-load-only cost, and cached thereafter. Sign verified
correct on all three: the corner cell saturates positive (outside) and the
Galaxy and Galor bbox centres read negative (inside). The Warbird's bbox centre
reads outside, which is correct for its shape — its centre sits in open space
between the wings.

⚠️ Two consequences of the margin sizing (§3) worth carrying forward: grids are
~34% larger than the §2.4 estimates because the margin covers a full band on
every face, and **74–83% of every grid saturates as far-outside**. A dense grid
therefore spends most of its bytes on empty space; a narrow-band or sparse
representation is the obvious later win, and is not attempted here.

### 2.6 `opaque.frag` accepts `sampler2D` and rejects `sampler3D`

A `sampler3D` in that shader corrupts shading even on a branch that never
executes — a known, previously recorded hazard, re-measured and found to be
worse than recorded. Method: add a declaration plus one fetch inside the
`u_carve_enabled != 0` block (which the canary test never enters), rebuild, run.

| Variant | HullClipTest | full renderer suite |
|---|---|---|
| baseline | 5/5 pass | **0 failures** |
| `sampler3D`, default unit 0 | 5/5 **fail**, GL 1282 every draw | — |
| `sampler3D`, free unit | 5/5 pass | **16 failures** |
| `sampler2D`, identical fetch | 5/5 pass | **0 failures**, 511 passed |

The 16 are `TangentBasisTest` (6), `ConeLightFrameTest` (5),
`ExplosionLightFrameTest` (3), `CloakAmbientParityTest` (2) — i.e. general
shading corruption, well beyond the single NaN test previously recorded. The
unit-0 variant is a *different* bug (sampler-type collision with a bound 2D
texture), not the miscompile.

**Consequence — a hard constraint, not a preference: the field reaches
`opaque.frag` as a 2D atlas.** A `sampler3D` is available to other shaders
(`breach.frag` already uses one) but must never be added to `opaque.frag`.

### 2.7 BC hulls are authored as named body sections

| Ship | sub-objects |
|---|---|
| Galaxy | `Ent-D Saucer Section`, `Ent-D-Hull`, `Ent-D-Neck` |
| Galor | `galor wing left`, `galor wing right` |
| Sovereign | `top o dish` |
| Warbird | `rom engine left` |

The pieces exist. The names are ad-hoc per ship, and nothing in the SDK
designates which are breakable, so this is **not** a mechanism we can key on
generically. Recorded because it supports the existence of breakable components
and may later serve as a bias for where a break looks believable.

---

## 3. The format — `.dhv`

Binary, little-endian, one file per hull, written by the baker and read at load.
Not a NIF: there is no compatibility requirement with `stbc.exe` for these, NIF
v3.1 is poorly documented, and a purpose-built container costs less than bending
an obsolete one.

```
offset  size  field
0       4     magic            'D','H','V','1'
4       2     format_version   currently 1
6       2     baker_version    bumped whenever bake output changes
8       4     source_size      hull nif size in bytes    ) fingerprint
12      8     source_mtime     hull nif mtime, RAW FILESYSTEM-CLOCK TICKS --
                                NOT unix seconds; implementation-defined unit
                                and epoch, only ever compared for equality  )
20      12    dims             int32 x, y, z
32      12    origin           float32, body frame, model units
44      12    cell             float32, model units per cell (uniform)
56      4     authored_res     float32, SetDamageResolution as given
60      4     quality          float32, multiplier applied (cell = authored/quality)
64      4     dist_scale       float32, model units per quantisation step
68      4     source_path_len  uint32
72      N     source_path      UTF-8, for diagnosis only, never for lookup
--            payload          int8 per cell, x-fastest
```

**Payload.** One signed byte per cell holding the distance to the hull surface in
units of `dist_scale`, negative inside, positive outside, saturating at ±127.
`dist_scale` is set so ±127 spans roughly ±4 cells, which is the deepest any
consumer probes; beyond that the exact value carries no information any consumer
uses.

**Why signed distance rather than occupancy.** Every threshold becomes a real
length instead of a cell count. `kMinCavityCells = 2.0` — the constant that
misbehaved on the Warbird precisely because cells differ per ship — becomes a
depth in model units that means the same thing on every hull. The surface is
also reconstructible below cell size by interpolation, so a modest grid reads
smoother than a much larger occupancy grid, and surface normals come from the
gradient instead of being inferred.

**Resolution.** `cell = authored_res / quality`, `quality` defaulting to **2**.
BC's authored value is treated as the per-ship *ratio* it evidently is (a Shuttle
finer than a starbase); the multiplier sets absolute fidelity globally. At 1× a
maximum-size carve on a Galaxy has a 3-cell radius, which cannot read as a torn
hole; at 2× it has 6. Exposed as a setting; both the value and its effect are
recorded in the header so a cache entry can never be misread.

---

## 4. Bake and cache

**When.** On first use of a hull, during model load.

**Where.** `<project_root>/cache/hull_volumes/<fingerprint>.dhv`, matching the
existing `cache/icons/...` convention (`engine/ui/weapon_icons.py`). Already
covered by the `cache/` line in `.gitignore`; no gitignore change needed.

**Key.** Hull path, source size, source mtime, cell size, quality, and
`baker_version`. Any change invalidates. Bumping `baker_version` invalidates the
whole cache without anyone having to remember to clear it.

**Cost.** Measured 8–70 ms at grids larger than any authored resolution
produces; a few ms per ship class in practice, once, then free. Corrupt or
short files are discarded and rebaked rather than trusted.

**Path discipline.** The cache root is resolved through `engine/paths.py` at use,
never captured at import, per the project rule. The literal segments `game` and
`sdk` appear nowhere in this subsystem.

⚠️ **Unexercised by plan 1.** `HullVolumeCache` is native-only C++
(`native/src/voxel/`), tested only by `native/tests/voxel/hull_volume_cache_test.cc`
with a `std::filesystem::path` cache root passed directly by the test -- no
Python code in `engine/` constructs a `HullVolumeCache` yet, so nothing in
this branch resolves the cache root through `engine/paths.py` at all. This
requirement is real but untested end-to-end until plan 2 wires the cache root
from Python through to the native cache.

---

## 5. Prerequisite: fix the voxelizer

Before any of the above is meaningful, `surface_voxelize` must stop point-sampling
at a fixed density (§2.2). Sample count per triangle derives from edge length
against cell size, or the rasterizer becomes a proper conservative triangle-box
overlap test.

**Locked down by a test that asserts solid fraction stays stable as resolution
rises** — the exact regression measured in §2.2, which no existing test catches
because nothing ever asked for a resolution above 48³.

Then the distance field: exact distance to the nearest triangle within a narrow
band (grid-accelerated), sign from flood fill, far field saturated.

---

## 6. The field API

One per-instance mutable field. Three operations, all in body-frame model units:

```
carve(center, radius, softness)          // weapons, death cascade
dent (center, radius, direction, depth)  // collisions
reset()                                  // DamageableObject.RemoveVisibleDamage() -- DEFERRED, not built
```

`carve` subtracts; `dent` displaces the surface inward without removing material;
`reset` would restore the pristine baked field, but neither `reset()` nor a
`RemoveVisibleDamage` mapping to it exists yet (see §9, §13) — `carve` is the
only operation this design actually shipped. The field is therefore monotonic
in practice: nothing can clear it. `visible_damage.clear_for` still only drops
*pending* (not-yet-applied) volumes, which is a different thing.

The 24-carve ceiling disappears. That matters immediately: the death cascade
currently lands enough blasts to evict its own earlier damage mid-sequence, so a
ship can visibly *heal* while dying.

Per-ship scale continues to come from `SetVisibleDamageRadiusModifier` /
`SetVisibleDamageStrengthModifier`, which already work.

---

## 7. Rendering

**Transport.** Field → `sampler2D` atlas (§2.6), uploaded when an instance's
field is dirty, not per frame.

**Hull.** `opaque.frag` clips against the field. Arbitrary connected carved
regions become possible, including ones that reach the silhouette. An undamaged
instance takes the stock path with zero added per-fragment cost, exactly as
`u_carve_enabled == 0` does today.

⚠️ **Corrected 2026-09-09 (plan 2c), measured.** This section originally said the
field clip *replaces* the `u_carve_spheres[24]` loop, and that baking the rim
noise into the brush would let the sphere list be retired. **That is not
achievable at this lattice resolution and the plan deliberately does not attempt
it.** The rim perturbation is ±25% of the carve radius (0.75–7.5 model units) and
the framework struts are thinner still, while the cell is 3.0–7.5 model units
across the fleet. Both are *sub-cell*: baking them into the field would not
sharpen the hole, it would **erase** the jagged rim and the struts.

The two representations divide as:

- **The field is the admission authority.** A hole may exist only where the field
  reads damaged. This is what guarantees every hole has an interior behind it,
  because the interior is raymarched from the same field.
- **The sphere list is the sub-cell detail layer.** Within the region the field
  admits, it supplies the noise rim and the strut lattice. It is not retired.

**The brush is deliberately conservative** — `voxel::kCarveDepthFloorCells` and
`kCarveFieldOffsetCells`, both 1.25 cells — so that a carve is rounded *up* to
the smallest shape the lattice can hold. That is what makes the containment hold.
Without it a carve's half-depth is `0.45 × radius`, thinner than one cell for
every radius below ~11 model units, and the brush does not survive trilinear
reconstruction at all: measured worst-case coverage of the analytically cut hole
was **0% for every carve radius up to 10**, and a sweep of all 72
cell × radius × sub-cell-placement combinations failed against the pre-2c brush.
With the conservative brush it is **100%** across cell 3.0–7.5 and radius 3–30.
`FieldBrushConservative.HoleIsAlwaysBackedAcrossTheParameterRange` holds it there.

The residual cost is that the field's damaged region is ~1.7× the nominal rim
(up to 3.3× for a tiny carve on a coarse lattice). It is suppressed wherever a
tracked carve governs, so it shows only as slightly generous holes cut beyond the
24-carve ring. Raising `kDefaultQuality` from 2 to 4 shrinks it proportionally at
8× field memory per instance — the lever to reach for if a live pass says those
holes read badly.

**Dents.** Vertex displacement along the field gradient, which preserves UVs and
therefore all authored texture detail.

⚠️ **Known limitation, stated up front:** BC hulls are low-poly (Galaxy: 1,833
welded vertices across 806 model units, ~20 units between vertices). Vertex-level
deformation at that density gives a broad sag, not a crisp dent. Hardware
tessellation would solve it but `glad` is generated at GL 3.3 in this build, so
the 4.x entry points do not exist. The answer within this design is CPU
subdivision of the damaged region of a damaged instance only, so cost falls on
ships that have actually been hit. **Collision deformation is therefore expected
to land coarse in the first live round.**

**Breach interior.** Derived from the field, replacing the sphere-inner-surface
scoop — built in plan 2b, and the scoop mesh is gone.

⚠️ **Corrected 2026-09-09 (plan 2c).** `carve_has_backing` was **not** deleted and
`carve_cavity_depth_cells` was **not** replaced by a single distance query. Both
still exist. The premise — that they exist only to reconcile two disagreeing
representations — no longer holds now that the two representations are in a
containment relation rather than a race: `carve_has_backing` is a whole-brush
*admission* gate (does this carve have material behind it at all), which is a
different question from the interior's own shape. Removing them is a behaviour
change needing its own live pass, not a cleanup.

A hull with **no** baked field now cuts **no** holes. Before plan 2c the sphere
path cut holes regardless while `breach_pass` returned early on a null field
entry, so a hull whose bake failed was unconditionally see-through. All 52 stock
hardpoints bake successfully, so this only ever affected mods and bake failures —
but "if we cannot draw what is behind it, we do not cut it" is the rule now.

---

## 8. Breakable components

After a brush lands, flood-fill the field for connected components. If the hull
has separated, the smaller component becomes its own object with its own
transform and its own field.

**A detached chunk needs no new geometry.** It renders as the *original hull
mesh*, on its own transform, clipped to its component's region of the field. Full
textures, correct panel lines, no remesh, no UV problem.

### Gating

Enabled where the ship's radius exceeds a **Galor's**, i.e. **2.381 GU**
(measured §2.4). Stock fleet either side of that line:

| Breakable | Not breakable |
|---|---|
| Akira 2.55, Nebula 2.42, Ambassador 3.14, Keldon 3.16, Transport 3.24, KessokLight 3.34, Galaxy 3.50, Vorcha 3.52, Sovereign 3.81, CardHybrid 4.96, Warbird 6.52, KessokHeavy 7.50 | Shuttle 0.14, BirdOfPrey 1.34, Freighter 1.96, CardFreighter 2.00, Marauder 2.02, Galor 2.38 |

⚠️ **Nebula clears the bar by 1.5%** (2.416 vs 2.381), and our radius derivation
has an open question against the clean-room reference (which puts a Galaxy near
4 GU where our AABB derivation gives 3.5). The threshold is therefore pinned as a
named constant **and** guarded by a test asserting which stock ships fall either
side of it, so a change to the *threshold constant* surfaces as a failing test
naming exactly which ships moved sides. That test's fleet radii are literals
hardcoded in the test file, not read from `GetRadius` or a hull asset — it does
**not** detect a change to how `GetRadius` itself is derived; that would
re-sort the fleet silently.

### Scale reality check

Maximum carve radius is `kHullCarveRadiusMaxGu = 0.3` GU = 30 model units
(`BC_MODEL_SCALE = 0.01`). **No single carve can sever a 350-unit Galaxy
saucer.** It can sever a neck, a pylon or a nacelle — which is most of what reads
as a ship coming apart. Saucer-scale separation requires the death cascade to use
a larger or swept brush (a capsule rather than a sphere). Recorded as an explicit
tuning item so it is not discovered in a live test.

---

## 9. SDK compatibility

Damage geometry has a real SDK surface, and missions use it. Current state was
verified live, not assumed:

| SDK surface | Today | Under this design |
|---|---|---|
| `ShipProperty.SetDamageResolution` | captured, **never read** | bake resolution; cell size is `authored/quality` |
| `DamageableObject.RemoveVisibleDamage` | implemented (drops *pending* volumes only, via `visible_damage.clear_for`) | **DEFERRED** — `field.reset()` does not exist; the per-instance field is monotonic and cannot be cleared. Not on this design's out-of-scope list (§13), so it reads as done when it is not; tracked here until a later plan builds it |
| `SetVisibleDamage{Radius,Strength}Modifier` | implemented | brush scale (unchanged) |
| `DamageableObject_IsDamageGeometryEnabled` | **`_NamedStub`** (truthy) | real flag, default on, round-trips faithfully |
| `DamageableObject_SetDamageGeometryEnabled` | **`_NamedStub`** | real setter, round-trips faithfully |
| `DamageableObject_IsVolumeDamageGeometryEnabled` | **`_NamedStub`** (truthy) | real flag, default on, round-trips faithfully |
| `DamageableObject_SetVolumeDamageGeometryEnabled` | **`_NamedStub`** | real setter, round-trips faithfully |
| `DamageableObject_IsBreakableComponentsEnabled` | **`_NamedStub`** (truthy) | real flag, default on, round-trips faithfully; `breakables_allowed_for` additionally radius-gates, as a standalone helper |
| `DamageableObject_SetBreakableComponentsEnabled` | **`_NamedStub`** | real setter, round-trips faithfully |

`Maelstrom/Episode3/E3M1/E3M1.py:3001-3003` reads all three getters into
`g_pVisibleDamageState` to save and restore damage state around a cutscene. The
matching setters are commented out in the shipped SDK, so the practical damage
today is limited — but these are the SDK's real switches for this subsystem, and
they are currently truthy stubs, which is a live bug class in this project.

**Policy:** in Dauntless damage is always on — all three default enabled. The
getters/setters (`engine/appc/damage_geometry.py`) round-trip faithfully — a
mission's `Get.../Set...` pair reads back exactly what it wrote, closing the
truthy-stub bug above — but **nothing yet consults these flags to actually
suppress damage.** There is no production call site that checks
`is_damage_geometry_enabled()`, `is_volume_damage_geometry_enabled()`, or
`breakables_allowed_for()` before carving, decaling, or breaking a ship apart;
a mission that calls `Set...Enabled(0)` around a cutscene gets the value back
unchanged, but damage still happens exactly as before. Wiring that gating is
real behaviour change needing live verification and is deferred to a later
plan (tracked alongside `field.reset()` above); this design's scope was the
honest round-trip, not the gate.

`HasClonedModel` / `GetClonedModelCount` / `GetClonedModelRadius` are related
surface (`Conditions/ConditionInRange.py:211` swaps to the cloned radius when a
ship has one) and are candidates for reporting a broken ship's changed extent.
Not committed to in this design; see open questions.

---

## 10. Settings

| Key | Default | Effect |
|---|---|---|
| hull volume quality | `2` | `cell = authored_res / quality` |

Persisted through `engine/settings_store.py`. Changing it invalidates cache
entries by header comparison, not by deletion.

---

## 11. Testing

- **Voxelizer:** solid fraction stable across rising resolution (§2.2's exact
  regression); watertight synthetic solids fill correctly.
- **Field:** distance sign correct inside/outside; `carve` removes and `dent`
  does not; `reset` restores the pristine field byte-for-byte.
- **Format:** round-trip; truncated, wrong-magic and wrong-`baker_version` files
  are rejected and rebaked rather than trusted.
- **Cache:** a stale mtime or a changed quality invalidates; a matching key hits.
- **Breakables:** the radius gate places each stock ship on the expected side of
  the line (§8); a severing carve yields two components, a non-severing one
  yields one.
- **SDK:** each of the six toggles round-trips faithfully (§9 -- gating
  behaviour is explicitly deferred to a later plan, not tested here); a ship
  whose `SetDamageResolution` differs bakes a different cell size.
- **Shader:** `opaque.frag` carries no `sampler3D` — asserted by a test, because
  §2.6 is a driver constraint no reviewer will infer from reading the file.
- **Gate:** `scripts/check_tests.sh` (both suites) green before merge.

---

## 12. Open questions

1. **Was BC's `BreakableComponents` ever functional, and how did it choose
   pieces?** Hulls carry named sections (§2.7) but the names are ad-hoc and
   nothing in the SDK designates breakability. Needs the `stbc-reference` server,
   which was unreachable while this was written. Does not block: field-derived
   components need no authored data and work for mod ships.
2. **Does our `GetRadius` match BC's?** Bears directly on §8's threshold. Open
   from prior work; the test in §8 contains the blast radius either way.
3. **Is 2× the right default quality?** Chosen on the argument that a
   maximum-size carve needs more than a 3-cell radius, and on memory being a
   non-issue. Wants one live round to confirm.
4. **Should authored sub-object boundaries bias where breaks occur?** Deferred;
   §2.7 records the data if we want it.
5. ✅ **RESOLVED 2026-09-11 — collisions now damage the hull (plan 3, first
   slice).** The path was never broken; two mechanisms made sustained contact
   inert: angular velocity was absent from the collision system entirely
   (`_resolve_body` read only linear `GetVelocity()`, so a spinning ship in
   contact reported velocity zero), and the `v_rel >= 0` debounce discarded a
   resting contact outright (120 frames of pressing in registered ONE hit).
   Fixed with a dt-scaled grind channel beside the debounce — the debounce
   still governs impulse, since an impulse that cannot change omega would
   re-fire every frame — and grinding deliberately posts NO
   `ET_OBJECT_COLLISION`, because `FriendlyFireCollisionHandler` makes one a
   game over. A follow-up fixed the grind landing on the bounding sphere
   instead of the mesh, which is the likely cause of one live see-through
   sighting that has not reproduced since. Live-verified: grinding gouges.
   **What remains is that it gouges — a hole — because the `carve` brush is
   the only brush that exists. The dent brush is the actual answer for
   collisions and is still unbuilt.** Original text follows for the record.

   ~~**Why does a collision produce no visible hole?**~~ Live-observed 2026-09-09,
   deferred to plan 3 by agreement. Dents are simply not built — there is no
   `dent` brush — but *carves* from collisions should already work: `collisions.py`
   routes kinetic impacts through `combat.apply_hit` with `bypass_shields=True`
   and `damage_hull` left True, which reaches `hit_feedback`'s carve gate with
   `allow_hull_carve=True`, and that gate does not inspect `weapon_type`. The
   plumbing has been read, not watched. Three candidate causes, needing different
   fixes: (a) `_ke_damage` is **quadratic** in closing speed with
   `COLLISION_DAMAGE_COEFF = 5.0`, so a gentle bump does almost no hull damage
   while a hard one is "instantly lethal" per that module's own comment — the
   visible band may be narrow, which would be tuning, not a defect;
   (b) `carve_has_backing` correctly refusing thin leading-edge structures
   (nacelles, pylons) — exactly where a ramming contact lands; (c) a real break.
   Discriminate by ramming at moderate speed and watching hull integrity first:
   damage registering with no hole means (b) or (c).

---

## 13. Out of scope

- Reconstructing torn rims as real geometry (ragged edges rather than a clipped
  surface). Wants the field to prove itself first.
- Persisting hull damage across save/load. Carves are runtime VFX today and stay
  that way here.
- **Wiring the six damage-geometry toggles to actually gate behaviour.** §9's
  getters/setters round-trip faithfully but are not consulted anywhere; a
  mission that suppresses damage for a cutscene gets its flag back unchanged
  while damage keeps happening. This is a live behaviour change needing a live
  verification pass, deferred to a follow-up plan.
- **`field.reset()` / `DamageableObject.RemoveVisibleDamage`.** §6 lists
  `reset()` as one of the field's three operations; it does not exist. The
  per-instance field is monotonic (only `carve` is implemented) and cannot be
  cleared today — `RemoveVisibleDamage` still only drops pending volumes via
  `visible_damage.clear_for`. Deferred to a follow-up plan.
- BC's `bytes2` plane index and `dual_contour`'s palette path. `planes_for_hull`
  is decoded but has zero consumers, and this design gives it none; it and the
  `_vox.nif` decode path retire once nothing reads them.
