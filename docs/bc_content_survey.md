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

Run: `./build/native/tools/scan_nifs/scan_nifs game/data`

Result:

```
=== scanned 805 .nif files under game/data ===
  reached End Of File: 805
  walker stuck on unknown block type: 0
  threw exception during load: 0
```

**Our parser handles every block type BC ships in NIFs.** No
BC-custom RTTI names exist in the NIF asset stream — BC's customization
lives at the Appc runtime layer (per #8), not in NIFs.

The 31 currently-registered block types in our parser (per
`grep NIF_REGISTER_BLOCK native/src/nif/src/blocks/`):

```
NiAlphaProperty, NiAmbientLight, NiBinaryVoxelData, NiBinaryVoxelExtraData,
NiBone, NiCamera, NiDirectionalLight, NiFlipController, NiFloatData,
NiImage, NiKeyframeController, NiKeyframeData, NiLookAtController,
NiMaterialProperty, NiMultiTextureProperty, NiNode, NiPointLight,
NiRawImageData, NiRollController, NiSpotLight, NiStringExtraData,
NiTextureModeProperty, NiTextureProperty, NiTexturingProperty,
NiTriShape, NiTriShapeData, NiTriShapeSkinController,
NiVertexColorProperty, NiVisController, NiVisData, NiZBufferProperty
```

This is the complete BC-content NIF vocabulary.

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
