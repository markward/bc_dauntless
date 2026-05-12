# BC Content Survey

Findings from running the post-round-2 follow-up surveys (items 6–10 in the
Phase 2 prioritization list). All numbers are over the **805-NIF corpus**
under `game/data` from a stock BC installation, run on 2026-05-12.

The point of these surveys is to drive Phase 2 implementation order: don't
build features BC's content doesn't use, and weight the features it does
use by how often they appear.

---

## Headline

1. **Our NIF parser is feature-complete for BC's NIF corpus.** scan_nifs
   reports zero unknown block types, zero load failures across 805 files.
2. **BC uses only `LIN` (97.8%) and `TCB` (0.67%) rotation keys.** Zero
   `BEZ`, `EULER`, or `STEP` rotations. Phase 2 rotation interpolation
   only needs to implement slerp + Kochanek-Bartels.
3. **Translation animation is real but secondary** (~18% of NiKeyframeData
   blocks). Scale animation is essentially absent (3 blocks corpus-wide).
4. **BC has zero NIF-embedded particle systems.** No `NiParticle*` /
   `NiGravity` / `NiAutoNormal*` / `NiRotating*` class strings appear in
   any NIF anywhere in the game tree. The `NiOldParticle` library we
   asked about in cleanroom round 2 is **not what BC uses**.
5. **BC's particle effects are custom Appc classes**, called procedurally
   from Python. Top 5: `SparkEmitterProperty`, `SmokeEmitterProperty`,
   `ObjectEmitterProperty`, `ExplodeEmitterProperty`,
   `AnimTSParticleController`. ~7 distinct classes total.
6. **BC has zero standalone `.KF` / `.KFM` animation files.** Animation
   clips ship inside NIFs. BC's character animations live as
   animation-only NIFs in `game/data/Animations/` (549 files).

---

## #6 / #7 — Animation key types in use

Run probe: `./build/native/tools/probe_animation_keys/probe_animation_keys game/data`

Corpus: 805 NIFs, 545 contain at least one `NiKeyframeData`, 7806
`NiKeyframeData` blocks total.

### Rotation channel

| Type | Count | % of blocks | Notes |
|---|---|---|---|
| `LIN` (slerp) | 7629 | 97.8% | Dominant — implement first |
| `TCB` (Kochanek-Bartels) | 52 | 0.67% | Rare but used |
| (no rotation) | 125 | 1.6% | Translation-only or empty |
| `BEZ` (Hermite) | 0 | 0% | **Not used by BC** |
| `EULER` (XYZ container) | 0 | 0% | **Not used by BC** |
| `STEP` (held) | 0 | 0% | **Not used by BC** |

Total of **329,117 rotation keys** across the corpus, max 289 keys in a
single block.

### Translation channel

| Type | Count | % of blocks | Notes |
|---|---|---|---|
| (no translation) | 6411 | 82.1% | Rotation-only animations |
| `LIN` (lerp) | 1355 | 17.4% | Dominant when present |
| `BEZ` (Hermite) | 40 | 0.51% | Rare |
| `TCB` | 0 | 0% | Not used |

Total of **48,459 translation keys**, max 284 keys per block.

### Scale channel

| Type | Count | % of blocks |
|---|---|---|
| (no scale) | 7803 | 99.96% |
| `BEZ` | 3 | 0.04% |

Three scale keys total in the entire corpus. Scale animation is
**effectively a non-feature** in BC content.

### Implementation priority

1. **`LIN` rotation (slerp with shortest-arc)** — by far the most common.
2. **`LIN` translation (lerp)** — secondary, ~18% of blocks.
3. **`TCB` rotation (Kochanek-Bartels)** — small but real.
4. **`BEZ` translation (Hermite)** — rare but present.
5. **Scale channel of any type** — defer entirely; 3 keys corpus-wide.
6. **`BEZ`/`EULER`/`STEP` rotation** — BC doesn't use any. Lowest priority;
   safe to stub.

---

## #8 — Particle system inventory

BC has zero NIF-embedded particle systems. A grep across `game/data` for
every stock NetImmerse particle-class string (`NiParticle*`, `NiGravity`,
`NiAutoNormal*`, `NiRotatingParticles`, `NiBSParticle*`,
`NiSphericalCollider`, `NiPlanarCollider`) returns nothing in any of the
805 NIFs.

**`NiOldParticle` is not the surface to implement** for BC particles.
Round 2's deep-dive on that subsystem is moot for asset loading.

Instead, BC's particle effects are custom classes exposed by `Appc.dll`
and called procedurally from Python. Inventory of `App.<Class>_Create` /
`App.<Class>` references across `sdk/Build/scripts/`:

| Class | Python instantiations | Likely purpose |
|---|---|---|
| `App.SparkEmitterProperty` | 48 | Hull-damage / weapon-impact sparks |
| `App.SmokeEmitterProperty` | 29 | Hull-damage / explosion smoke |
| `App.ObjectEmitterProperty` | 29 | Generic object-anchored emitter |
| `App.ExplodeEmitterProperty` | 11 | Explosion emitter |
| `App.AnimTSParticleController` | 7 | Time-scaled animated controller |
| `App.LensFlare` | 2 | Sun / star lens flares |
| `App.SparkParticleController` | 2 | Spark particle controller |
| `App.BridgeEffectAction_Create{Sparks,Smoke,Explosion,Debris}` | 4 | Bridge interior VFX |
| `App.DebrisParticleController` | (declared, usage TBD) | Debris |
| `App.ExplodeParticleController` | (declared, usage TBD) | Explosion particles |

These class names confirm round 2's negative finding (no Trek-flavored
strings in the stock SDK source) — they are **BC engine extensions** on
top of NetImmerse, registered into Appc's class factory at engine init.

For Phase 2 particles, the work is **reimplementing these ~7 custom
classes**, not implementing the `NiOldParticle` library. The Appc
interface in [App.py](../sdk/Build/scripts/App.py) is the spec — every
method (`SetEmitFrequency`, `SetEmitVelocity`, `SetEmitLife`, etc.) is
documented as a SWIG wrapper to the C++ method.

### Notable BC-custom emitter properties (from `App.py` field surface)

Common `Set*` calls on `EmitterController` and friends:

- `SetEmitFrequency` / `SetEmitFrequencyVariance` — birth rate
- `SetEmitLife` / `SetEmitLifeVariance` — lifespan
- `SetEmitVelocity` / `SetEmitVelocityVariance` — initial velocity
- `SetEmitRadius` — emitter shape (sphere?)
- `SetEmitFromObject` / `SetDetachEmitObject` — anchor management
- `SetEmitPositionAndDirection`

The mean/variance pattern matches NetImmerse's old-particle controller
field layout (round 2 NI2-Q44), suggesting BC's emitters are derived
from / inspired by `NiParticleSystemController` — but with their own
class identity. Round 2's per-particle hybrid SoA/AoS architecture
(NI2-Q41) is a reasonable starting assumption for the implementation.

---

## #9 — Custom block-type enumeration

Run: `./build/native/tools/scan_nifs/scan_nifs game/data` then
`./build/native/tools/probe_block_inventory/probe_block_inventory game/data`

`scan_nifs` confirms 805/805 files reach EOF with zero unknowns and zero
load failures — **our parser handles every block type BC ships in NIFs.**
No BC-custom RTTI names exist in the NIF asset stream; BC's customization
lives at the Appc runtime layer (per #8), not in NIFs.

`probe_block_inventory` walks each loaded `nif::File` and tallies the
actual usage of every block type across the corpus. Across 805 files and
92,770 blocks:

| Type | Blocks | Files | Coverage |
|---|---:|---:|---:|
| `NiNode` | 24,159 | 805 | 100.0% |
| `NiKeyframeController` | 20,151 | 580 | 72.0% |
| `NiTriShape` | 11,285 | 456 | 56.6% |
| `NiTriShapeData` | 11,283 | 456 | 56.6% |
| `NiMaterialProperty` | 11,099 | 455 | 56.5% |
| `NiKeyframeData` | 7,806 | 545 | 67.7% |
| `NiTextureModeProperty` | 2,041 | 461 | 57.3% |
| `NiVisData` | 1,130 | 46 | 5.7% |
| `NiVisController` | 1,130 | 46 | 5.7% |
| `NiVertexColorProperty` | 671 | 461 | 57.3% |
| `NiImage` | 530 | 171 | 21.2% |
| `NiTextureProperty` | 491 | 171 | 21.2% |
| `NiZBufferProperty` | 461 | 461 | 57.3% |
| `NiMultiTextureProperty` | 89 | 9 | 1.1% |
| `NiBinaryVoxelExtraData` | 84 | 84 | 10.4% |
| `NiBinaryVoxelData` | 84 | 84 | 10.4% |
| `NiAlphaProperty` | 64 | 5 | 0.6% |
| `NiLookAtController` | 47 | 22 | 2.7% |
| `NiTriShapeSkinController` | 39 | 27 | 3.4% |
| `NiSpotLight` | 25 | 13 | 1.6% |
| `NiCamera` | 21 | 21 | 2.6% |
| `NiAmbientLight` | 20 | 20 | 2.5% |
| `NiDirectionalLight` | 18 | 7 | 0.9% |
| `NiRawImageData` | 17 | 10 | 1.2% |
| `NiStringExtraData` | 12 | 8 | 1.0% |
| `NiPointLight` | 10 | 8 | 1.0% |
| `NiRollController` | 1 | 1 | 0.1% |
| `NiFloatData` | 1 | 1 | 0.1% |
| `NiFlipController` | 1 | 1 | 0.1% |

### Surprises

- **`NiTextureProperty` (singular, older), not `NiTexturingProperty`
  (newer, multi-stage), is what BC uses.** 491 blocks of the singular
  form vs **zero** of the multi-stage form. The texturing-stage features
  cleanroom round 1 described (glow slot, detail map, gloss map, bump
  map, decal stages) are not the BC texture model — BC ships one
  texture per property, period. Glow / multi-texture features must be
  handled elsewhere (per memory `project_glow_via_addlod.md`: BC attaches
  glow via runtime `AddLOD`, not via NIF texture stages).
- **Alpha-blending is rare.** Only 64 `NiAlphaProperty` blocks across 5
  files. Most BC content is opaque + Z-test.
- **`NiFlipController` is a single block in the entire corpus.** Texture
  flipbook animation is essentially absent. The 0.01 fudge constant we
  catalogued is for a corner case so rare it's almost not worth
  implementing.
- **`NiBinaryVoxelData/ExtraData` appears in 84 files (10.4%).** Voxel
  collision data is more common than animation-rare types. Worth knowing
  when collision implementation starts.
- **Skinning is rare.** Only 39 `NiTriShapeSkinController` blocks across
  27 files — likely bridge-crew character animations.

### Registered-but-unused (dead-code candidates)

One of our 31 registered types never appears in BC content:

- **`NiTexturingProperty`** — see above. Safe to remove the registration,
  the parser body, and the variant alternative; we will never see this
  block in BC.

The 31st registration — **`NiBone`** — is intentionally a class-name
alias that reuses the `NiNode` body parser, the same pattern round 2
documented for `NiKeyframeController` → `NiTransformController`. Any
`NiBone` block on disk deserializes to an `NiNode` variant value, so
this probe can't distinguish bones from regular nodes after parsing.
The 39 `NiTriShapeSkinController` blocks across 27 files imply bones
ARE present in BC's skinned character animations; they're just counted
under `NiNode`.

---

## #10 — Standalone KF/KFM files

`find game -type f \( -iname '*.kf' -o -iname '*.kfm' \)` returns
nothing. **BC has zero standalone animation-clip files.**

What BC has instead: a `game/data/Animations/` directory of **549 NIFs**
holding character animations (bridge-crew gestures, console interactions,
seated poses, etc.). These are full NIFs with header + scene-graph + block
walker terminating at EOF, not KF clips.

Implication for Phase 2: **we do not need a KF/KFM loader.** All animation
ingestion stays inside the NIF loader. The `"File Format"` detection
generalization (commit `451cbb3`) was useful future-proofing but isn't
needed for BC compatibility.

---

## Phase 2 implementation priorities (rolled-up)

Based on these surveys:

1. **Animation runtime — focus on what BC actually uses**:
   - `NiKeyframeController` + `NiTransformInterpolator` (already aliased
     in our loader).
   - LIN slerp for rotation; LIN lerp for translation; ignore scale.
   - TCB for both channels — small but real, implement after LIN.
   - Hermite (BEZ) for translation only — defer if LIN coverage isn't
     enough.
   - **Skip `BEZ`/`EULER`/`STEP` rotation and any scale interpolation
     for the first pass** — assert-fail if encountered, since BC content
     never produces these.

2. **Custom-particle reimplementation (the real Phase 2 particle work)**:
   - Start with `SparkEmitterProperty` and `SmokeEmitterProperty` (top
     two by Python usage — combined 77 instantiation sites).
   - Then `ObjectEmitterProperty` (generic — likely the base for the
     others).
   - Then `ExplodeEmitterProperty`, `AnimTSParticleController`,
     `LensFlare`.
   - Reference the round-2 doc for architectural shape (hybrid SoA/AoS,
     per-system seeded RNG via `nif::legacy::ParticleRng`).
   - **Do NOT implement the `NiOldParticle` modifier chain model** —
     BC uses a different particle architecture.

3. **NIF coverage is done.** No additional parser work needed for BC.
   New block types only become relevant if/when we add non-BC content.

4. **No KF/KFM loader required.** All animation is NIF-embedded.
