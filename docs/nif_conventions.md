# BC NIF Conventions — Cheat Sheet

One-page lookup for the math, format, and runtime conventions BC NIFs use.
Derived from clean-room NetImmerse/Gamebryo SDK reading
([round 1](cleanroom_netimmerse_answers.md),
[supplementary](cleanroom_netimmerse_supplementary.md),
[round 2 — most accurate on BC legacy specifics](cleanroom_netimmerse_answers_round2.md)),
cross-checked against our own reverse-engineering of BC v3.1 assets.

> **Use this when** you're touching the NIF parser, renderer math,
> skinning, lighting, or animation evaluation. For the full reasoning
> read the cleanroom docs; this page is the lookup.

---

## Version

| Fact | Value |
|---|---|
| BC's primary NIF version | **3.1** (`0x03010000`) |
| BC's legacy NIF version (planets, viewscreens, Kessok head) | **3.0** (`0x03000000`) |
| Gamebryo 1.2.2 SDK loader minimum | **3.3.0.11** |
| Our SDK reference for v3.1 schema | niflib `nif.xml` + NifSkope tables; **not** the Gamebryo SDK loader |

The Gamebryo SDK source describes 3.3+ behavior and cannot load BC NIFs
directly. When SDK docs and BC reality conflict, BC wins.

---

## Math conventions

| Convention | Value |
|---|---|
| Handedness | **Right-handed** |
| Up axis at engine level | Not fixed; content-pipeline decides (BC content typically Y-up) |
| Matrix storage | **Row-major** flat array (`m[0..8]`, row-major) |
| Matrix math | **Column-vector** (`v' = M * v`); parent-to-world is left-multiplied |
| Rotation matrix | Orthonormal 3×3 |
| Quaternion struct order | `{x, y, z, w}` (named fields) |
| Quaternion **on-disk** order | **WXYZ** (W first) — `Reader::read_quat` swaps to struct order |
| Euler order (`NiEulerRotKey`) | XYZ, **radians** |
| `NiAVObject` transform composition | `parent_world * (T * R * S)` |
| Scale | **Uniform scalar only** — non-uniform must be baked into vertices |
| Light forward axis | Model-space **+X** (rotate the node to aim) |
| Camera forward axis | Local **−Z**; up = +Y, right = +X |

---

## Animation key conventions

| Key family | Interpolation | Notes |
|---|---|---|
| `LIN` | Linear (slerp for quaternions, shortest-arc) | |
| `BEZ` | **Hermite spline** (despite "Bez" name); stores in/out tangents | |
| `TCB` | Kochanek-Bartels (tension/continuity/bias) | Adds 3 floats per key |
| `STEP` | Hold previous value | |
| `EULER` (rotation only) | Three independent float tracks composed XYZ | Each track may use its own family |

Cycle types: `LOOP` (wrap), `REVERSE` (ping-pong), `CLAMP` (hold endpoints).
Animation time = `((appTime - startMoment) * frequency + phase)` mapped into
`[start, stop]`.

Text-key tag strings (`NiTextKeyExtraData`) are **100% application-defined**
— **the SDK matches zero literal strings** (verified by round 2). BC's
runtime is the sole interpreter; any `"start"` / `"end"` / `"sound:..."`
convention exists in BC's Python or C++ above the NIF layer, not in the
engine.

---

## Legacy animation handling (BC-specific)

BC's NIFs at v3.1 fall under the legacy paths. **No `NiKeyframeController`
or `NiKeyframeData` exists as a runtime class** — they're aliased on
load to `NiTransformController` and `NiTransformData`. The cutoff version
for legacy-vs-modern field layouts in the SDK is **NIF 10.1.0.104**;
everything below uses the legacy layout.

`NiTransformData` (née `NiKeyframeData`) carries three fully **independent**
channels on disk:

```
[rotation: count, type, key[]]  // type ∈ LIN/BEZ/TCB/STEP/EULER
[position: count, type, key[]]  // type ∈ LIN/BEZ/TCB/STEP
[scale:    count, type, key[]]  // type ∈ LIN/BEZ/TCB/STEP
```

Each channel can independently:
- have a different key type from the others
- be empty (zero keys → that channel preserves bind-pose value)

`EULER` rotation type is a special container: `count == 1`, and that single
key holds three independent float-key arrays for X, Y, Z axes (radians,
composed XYZ). Each axis float-array can independently have zero keys.

Three converter classes need topology fixup post-load (single SDK function):
- `NiLookAtController` → `NiTransformController` + `NiLookAtInterpolator`
- `NiRollController` → folded into the look-at as a roll sub-interpolator
  (silently dropped if no look-at on the same target)
- `NiPathController` → `NiTransformController` + `NiPathInterpolator`

Other legacy controllers (`NiAlphaController`, `NiVisController`,
`NiUVController`, `NiFlipController`, `NiMaterialColorController`,
`NiLightColorController`) keep their names but version-gate their body
layouts.

`NiSequence` in BC's pre-4.1.0.3 KF files uses the `NiSequenceStreamHelper`
container path with parallel string-extra-data entries. Per-controller
timing (NOT per-sequence). Target resolution by `GetObjectByName` at
activation.

## Old particle system (BC's `NiOldParticle`)

Architecture:
- One `NiParticleSystemController` per system, derives from `NiTimeController`.
- Three parallel singly-linked modifier chains: emitter modifiers,
  particle modifiers, particle colliders.
- Modifiers are **prepended on attach** → iteration order is reverse-of-attach.
- Per-particle state is split: 7 fields per particle on the controller
  (`NiPerParticleData`: velocity, rotation axis, age, lifespan, last-update,
  generation, slot-index), but position/color/normal/radius/size live in
  `NiParticlesData`'s parallel SoA arrays. The renderer iterates
  `NiParticlesData` directly.
- **Capacity is fixed at NIF-author time** = vertex count of the underlying
  `NiParticles` geometry. **Structural** cap — cannot grow at runtime.
- Death triggers swap-and-pop: dying slot is overwritten with the last
  active particle's state, active count decrements.

Modifier set (8 concrete + 3 abstract bases): `NiGravity`, `NiParticleBomb`,
`NiPlanarCollider`, `NiSphericalCollider`, `NiParticleColorModifier`,
`NiParticleGrowFade`, `NiParticleMeshModifier`, `NiParticleRotation`.

**Emitter shape is hardcoded box** (width/height/depth on the controller).
BC's non-box effects must use custom emitter modifiers or post-spawn
relocation.

**`NiParticleRotation` is silently stripped at load for non-mesh particles**
(`REMOVE_UNUSED_ROTATIONS`). BC billboard particles never rotate via this
modifier — rotation in BC billboards must come from flip-controller textures
or BC-custom logic above the NIF.

## Magic constants (match for visual/behavioral parity)

| Constant | Used by | Purpose |
|---|---|---|
| **`1.6`** | `NiGravity` strength multiplier | Units-conversion fudge — multiplied into every gravity application |
| **`0.01`** | `NiFlipController` | Index fudge before integer truncation |
| **`0.0001`** | `NiParticleSystemController`, `NiParticleGrowFade` | Size-clamp / time-comparison epsilon |
| **`0.0333…`** | Particle controller | 30 fps run-up sample rate on first update |
| **`0.10`** | Particle controller | Static-bound sampling step |
| **`1.05`** | Particle controller | Bound oversizing factor |
| **`1024`** | `NiFlipController` | `SHADER_MAP_OFFSET` — shader-map vs standard-map index discriminator |

`NiUVController` mutates the vertex buffer **in place** (unlike modern
`NiTextureTransformController` which is a per-stage matrix). Composition
is `T·S` per axis centered at UV (0.5, 0.5); U-offset is subtracted,
V-offset is added "to match Max behavior." Stateful delta accumulation
— `NiUVData` remembers its last computed values frame-to-frame.

## File format conventions

- Detect file family by the **`"File Format"`** substring in the first
  text line — covers NIF, KF, KFM, and BC custom extensions all routed
  through the same stream loader. (We currently anchor on `"Version "`;
  generalize when KF/KFM ingestion lands.)
- **Two-pass load**: each block writes scalar fields + integer link IDs
  in pass 1 (`LoadBinary`); pointers resolve in pass 2 (`LinkObject`).
  This is what allows cycles and arbitrary block ordering.
- Block-type references are **32-bit integer link IDs** into the file's
  flat block array. `NULL_LINKID` represents null.
- **RTTI table at file head** is the schema directory — every distinct
  class name appears once, each block body carries a `u16` index into
  it. Pre-scan to detect unsupported classes.
- Unknown block types are **fatal** in the stock loader. Our loader
  can be more lenient.
- Triangle indices are 16-bit unsigned. ≥ 65535-vertex geometry must be
  split.

---

## Renderer property conventions

- **Property stack: closer wins.** Only one property of any given type
  is active per subtree. Properties do **not** combine.
- Alpha sort: back-to-front by **bounding-sphere center depth** via
  `NiAlphaAccumulator`. `NiAlphaProperty` `NoSort` flag opts out.
- Texturing stage slots: `Base`, `Dark`, `Detail`, `Gloss`, `Glow`, `Bump`,
  `Decal[0..N]`. Glow is **additive emissive** independent of light
  direction and independent of `NiMaterialProperty::emissive`.
- Environment maps attach via `NiTextureEffect` (a `NiDynamicEffect`,
  alongside lights), **not** via the property stack. Modes:
  `WORLD_PARALLEL`, `WORLD_PERSPECTIVE`, `SPHERE_MAP`, `SPECULAR_CUBE`,
  `DIFFUSE_CUBE`.

---

## Skinning conventions

- Linear-blend skinning.
- Per-bone **skin-to-bone** transform (inverse-bind) stored in
  `NiSkinData::BoneData`.
- Per-vertex weights stored **per-bone** as `(vertex_index, weight)` pairs
  with explicit count. Vertex can have arbitrarily many influences at
  the format level.
- **No runtime renormalization** — exporter does it; weights must sum to
  1 in the data.
- Math: `v_world = Σᵢ wᵢ * (Bᵢ_world * Sᵢ * v_skin)` where `Sᵢ` is the
  inverse-bind for bone i.
- `NiSkinPartition` partitions for hardware skinning, default 4 bones per
  partition (DX8 era; we are free to exceed).

---

## Content-envelope limits (DX8-era; not architectural)

BC's content was authored inside these caps. Our renderer should load
content that respects them but **must not bake them in as hard limits** —
the point of rebuilding on modern GPUs is partly to exceed them.

| Limit | Value | Origin |
|---|---|---|
| Simultaneous lights per object | 8 | DX8 fixed-function T&L |
| UV sets per vertex | 8 | DX8 |
| Bones per skin partition | 4 (default) | DX8 matrix palette |
| Multitexture stages per pass | hardware-dependent | DX8 era |
| Triangle indices | 16-bit unsigned | **Format-structural** (must respect) |

See [feedback_dx8_envelope_not_ceiling.md](../../.claude/projects/-Users-mward-Documents-Projects-open-stbc/memory/feedback_dx8_envelope_not_ceiling.md) — the discrimination
between structural / runtime-architectural / hardware-era limits drives
how we model each.

---

## BC engine extensions (NOT in stock SDK)

These behaviors are BC-specific Python/C++ layered on top of NIF, not
features of the underlying engine:

- **Glow attach by filename substring** (`AddLOD("..._glow", ...)`) — no
  stock SDK equivalent.
- **Sun corona / lens flare** — no `NiCorona` / `NiLensFlare` block class.
  BC builds these from `NiBillboardNode` + additive geometry +
  `App.LensFlare`.
- **Center-of-geometry / pivot offset** — no field on `NiAVObject`. NIF
  origin is the only documented anchor; centroid offsets live in custom
  extra data or are baked at export.
- **Stretched/speed-elongated billboard particles** — not stock.
- **Distance-attenuated emissive** — not in any property.
- **Decal projection at runtime** — `Decal` texture slot is UV-driven, not
  screen/world projected.

When BC behavior doesn't map cleanly to a stock SDK feature, suspect BC
extensions before suspecting an obscure engine knob.
