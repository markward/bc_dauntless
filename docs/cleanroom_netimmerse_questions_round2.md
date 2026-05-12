# NetImmerse / Gamebryo SDK — Clean-Room Questionnaire, Round 2

## Purpose

This is round 2 of clean-room questions for the Gamebryo 1.2.2 SDK. The
**only** artifact crossing into the contaminated side is this file; the
**only** artifact returning is your prose answer document.

Round 1 covered the architecture broadly. You returned an answers doc and a
supplementary doc that surfaced two specific files as the highest-value
remaining spec material for our BC reimplementation:

- **`CoreLibs/NiAnimation/NiOldAnimationConverter.{h,cpp}`** — the converter
  that maps BC-era animation (`NiKeyframeController` + `NiSequence` + the
  associated data and "old" controllers) to the modern
  `NiInterpController` / `NiInterpolator` / `NiControllerSequence` model.
- **`CoreLibs/NiOldParticle/`** — the entire directory implementing the
  pre-Gamebryo-1.1 particle system that BC actually uses, plus
  `NiOldParticleConversion` which forward-ports it.

These two files/directories collectively encode BC's animation and particle
data models, because the converter code has to know every field of the old
data to translate it. This round asks you to read them and describe the
old data models back to us.

## Clean-room protocol — same rules as round 1

1. **No source code paste, no struct layouts copied verbatim, no comments
   transcribed.** Describe behavior, field semantics, and algorithms in your
   own prose.
2. **Public NIF class names are fine** (they appear in every NIF file).
   Internal helper class names, file paths inside the SDK tree, and private
   API symbols are not.
3. **Behavior over implementation.** "What field does this carry and how is
   it interpreted" — not "what is the C++ initializer list."
4. **Confidence tags:** **[documented]**, **[inferred from source]**,
   **[inferred from sample]**, **[not found]**. Tag every answer.
5. **"Not found" is a valid and useful answer.** Don't skip a question — say
   it wasn't there.
6. **Number answers** with the same IDs used here (`NI2-Q##`).
7. **One answer document.** Markdown. Headline findings at the top,
   not-found list at the bottom. Same shape as round 1.

## Special directive: limit categorization

For *every* question where you describe a fixed limit, a cap, a maximum
count, or a "hard-coded N" of any kind, **tag which category it falls in**:

- **[structural]** — the limit is in the on-disk data format (e.g., 16-bit
  triangle indices). Raising it requires a parallel format.
- **[runtime-architectural]** — the limit is in the engine's runtime design
  (e.g., one property of a given type per subtree). Raising it requires
  redesign.
- **[hardware-era]** — the limit reflects DX8 / fixed-function GPU
  capabilities of 2002-2006 (e.g., 8 simultaneous hardware lights, 4 bones
  per matrix palette). A modern reimplementation on contemporary GPUs is
  free to exceed.

This matters because we intend to relax hardware-era caps where possible,
but must respect structural and runtime-architectural ones.

## Use of supplementary samples

If `Samples/Tutorials/06 - Time Controllers/` or
`Samples/Demos/CharacterAnimationDemo/` clarify any animation question,
reference them. Same for any particle-related sample. The samples often
show "how this system is meant to be used" in a way that headers don't.

## How to use this list

Questions are grouped by topic. Priority tags:

- **[P1]** — directly needed for Phase 2 implementation.
- **[P2]** — clarifies known ambiguity.
- **[P3]** — speculative or low-stakes.

Within each section, foundational questions come first.

---

## A. Animation converter — overall shape

- **NI2-Q1 [P1]** What is the top-level entry point of the animation
  converter, and in what form does it consume input (a single legacy
  object, a whole loaded scene, a stream being read)? Describe the
  flow from "BC NIF just loaded" to "modern controllers in place."
- **NI2-Q2 [P1]** Where in the load pipeline does conversion run — inside
  `NiStream::Load`, on demand when an animation is first played,
  manually by application call, or at some other point?
- **NI2-Q3 [P1]** Enumerate every legacy class name the converter
  recognizes (the set of classes it knows how to forward-port). For each,
  state the modern class it produces.
- **NI2-Q4 [P2]** What does the converter do when it encounters a class
  it doesn't recognize? Hard error, silent skip, pass-through, or
  warning?
- **NI2-Q5 [P3]** Does the converter retain any state about what it
  converted (a map old→new, a log)? If so, who can query it?

## B. NiSequence (BC's animation clip)

- **NI2-Q6 [P1]** Field-by-field, what does `NiSequence` carry? Name each
  field and describe what it means.
- **NI2-Q7 [P1]** How are the sub-controllers (the per-target animation
  channels) stored inside a sequence — embedded by value, referenced by
  pointer, indexed into a separate table?
- **NI2-Q8 [P1]** How are target nodes resolved when a sequence is
  activated against a scene? By node name? By stored pointer? At load,
  at activation, or per-frame?
- **NI2-Q9 [P1]** Does `NiSequence` carry text keys directly, reference a
  separate `NiTextKeyExtraData`, or both?
- **NI2-Q10 [P1]** How are start/stop/frequency/phase/cycle-type
  represented on a sequence vs on the controllers it contains? Does the
  sequence own these or does each sub-controller?
- **NI2-Q11 [P2]** Can multiple `NiSequence` objects coexist in one NIF,
  and if so, how is the active one selected? Is `NiSequence` a top-level
  object or always owned by a parent?
- **NI2-Q12 [P2]** Were `NiSequence` fields stable across NIF versions
  3.x → 4.x, or did the structure grow over time? Note any version gates
  the converter checks.

## C. NiKeyframeController + NiKeyframeData

- **NI2-Q13 [P1]** Fields on `NiKeyframeController` beyond what every
  `NiTimeController` carries (start/stop/frequency/phase/cycle/anim type).
- **NI2-Q14 [P1]** `NiKeyframeData` field-by-field. The supplementary doc
  established that this block combines rotation + translation + scale
  tracks — describe exactly how they coexist: separate arrays per channel,
  one interleaved array, or something else.
- **NI2-Q15 [P1]** For each of the three channels (rotation, translation,
  scale), how is the **key type** selected — one type per channel,
  per-key-type-tag, or some other discriminator? Can rotation be LINEAR
  while translation is BEZIER in the same block?
- **NI2-Q16 [P1]** When a track has zero keys, what is the runtime
  behavior — does the bone stay at bind pose, last value, identity?
- **NI2-Q17 [P2]** How is the `NiEulerRotKey` container's three float-key
  arrays stored on disk under `NiKeyframeData`? Are all three tracks
  required, or can two be absent?
- **NI2-Q18 [P2]** Does `NiKeyframeData` store any version-gated extras
  (e.g., per-key flags added in 4.x that weren't in 3.x)?
- **NI2-Q19 [P2]** Describe the conversion from
  `NiKeyframeController(+Data)` to `NiTransformController(+
  NiTransformInterpolator)` — which fields move where, what's defaulted,
  what's discarded.

## D. Other legacy controllers

For each of these, give: what it animates, the fields it carries, the data
class it references (if separate), and the modern equivalent the converter
produces.

- **NI2-Q20 [P1]** `NiVisController` + `NiVisData`. How are visibility
  key arrays encoded (boolean step keys with timestamps)?
- **NI2-Q21 [P1]** `NiAlphaController`. Target field on
  `NiMaterialProperty`, key encoding.
- **NI2-Q22 [P2]** `NiColorController`. Color-channel target, key encoding.
- **NI2-Q23 [P1]** `NiMaterialColorController`. Channel selector
  (ambient / diffuse / specular / emissive), and how that selector is
  encoded in the legacy form.
- **NI2-Q24 [P1]** `NiUVController` + `NiUVData`. UV transform parameters
  (translate U/V, rotate, scale U/V): how are they stored, what's the
  composition order, and which texture stage / UV set is targeted.
- **NI2-Q25 [P2]** `NiPathController` + `NiPathData`. Path curve
  representation (control points, knots, parameterization), orientation
  rules, banking.
- **NI2-Q26 [P2]** `NiLookAtController`. Target resolution, axis-lock
  configuration, up-vector source.
- **NI2-Q27 [P2]** `NiFlipController` + `NiFlipData` (texture flipbook).
  Per-frame texture sequence, timing, looping.
- **NI2-Q28 [P3]** Any other legacy controllers in the converter that
  don't fit the above categories? List them with one-line summaries.

## E. Old-to-modern mapping table

- **NI2-Q29 [P1]** Produce a single mapping table:
  `legacy class → modern class(es)`. For each row, note whether the
  mapping is 1:1, 1:N (one old becomes several modern), or N:1 (several
  old combine into one modern).
- **NI2-Q30 [P2]** Are there any **irreversible losses** in conversion —
  legacy fields that don't have a modern home and are dropped? List them.
- **NI2-Q31 [P2]** Are there any cases where the converter **fills in
  defaults** for modern fields that weren't represented in legacy? List
  what defaults are used.

## F. Quirks, gotchas, version gates

- **NI2-Q32 [P1]** NIF-version-gated branches in the converter — what
  versions does it special-case, and what differences does each version
  introduce?
- **NI2-Q33 [P2]** TODO / FIXME comments, or any "this is wrong but we
  ship it anyway" hints in the converter. Paraphrase the issue, not the
  comment text.
- **NI2-Q34 [P2]** Hard-coded numeric constants in the converter
  (epsilons, magic timestamps, sentinel values). What does each
  represent?
- **NI2-Q35 [P3]** Anything in the converter that suggests BC-specific
  data shapes — e.g., special handling of named nodes like `"Bip01"`,
  recognition of specific text-key strings, or fallbacks for non-stock
  blocks.

## G. Text key conventions

- **NI2-Q36 [P1]** Does the converter look for specific tag strings in
  `NiTextKeyExtraData` (e.g., `"start"`, `"end"`, `"sound:..."`)? List
  every literal string it matches against.
- **NI2-Q37 [P2]** For each recognized tag, what action does the
  converter take when it sees one?
- **NI2-Q38 [P2]** Are there documented conventions in the SDK for tags
  the converter doesn't recognize but the runtime is expected to honor
  (loop markers, sound triggers)?

## H. Old particle system — architecture

- **NI2-Q39 [P1]** Top-level data flow per frame: who calls whom, in
  what order. Specifically: when `Update(time)` is called on the scene,
  what path does it take through `NiParticleSystemController` and its
  modifier chain?
- **NI2-Q40 [P1]** Is modifier ordering significant? Does the controller
  walk modifiers in insertion order, in priority order, or in
  category-grouped order (emitters first, then forces, then colliders)?
- **NI2-Q41 [P1]** Per-particle state — is it Structure-of-Arrays
  (parallel `vector<Pos>`, `vector<Vel>`, etc.) or Array-of-Structures
  (one `struct Particle` per slot)? Where does that data live —
  on the controller, on the renderer node, on a separate data block?
- **NI2-Q42 [P2]** Memory management — fixed pool with reuse, dynamic
  growth, capacity hint? Where is the maximum particle count specified?
  Tag the cap with **[structural / runtime / hardware-era]**.
- **NI2-Q43 [P2]** Is there a global "old particle system manager" or
  is each `NiParticleSystemController` self-contained?

## I. NiParticleSystemController

- **NI2-Q44 [P1]** Field-by-field — what does the controller carry
  beyond the base `NiTimeController` fields?
- **NI2-Q45 [P1]** Where is the emit-rate / spawn-rate specified — on
  the controller, on the emitter modifier, or split between?
- **NI2-Q46 [P1]** How is "particle lifetime" specified — on the
  controller as a default, per-particle from the emitter, or both?
- **NI2-Q47 [P2]** Initial velocity distribution — direction, speed
  range, angular spread (declination / azimuth). Where stored?
- **NI2-Q48 [P2]** Initial color and size — defaults, ranges, random
  distribution.
- **NI2-Q49 [P2]** Random number source — does the controller carry a
  seed, use a global RNG, or use a deterministic per-frame sequence?

## J. NiAutoNormalParticles and NiRotatingParticles

- **NI2-Q50 [P1]** What distinguishes the two — fields, behavior,
  rendering. When would BC content use one vs the other?
- **NI2-Q51 [P1]** Are these `NiTriShape`-derived (i.e., they reuse the
  general geometry pipeline) or a separate primitive type? If derived,
  what's overridden.
- **NI2-Q52 [P1]** Billboard orientation — `NiAutoNormalParticles`
  presumably orients each particle's quad to face the camera; describe
  the exact algorithm (centroid-to-camera, view-plane-aligned, etc.).
- **NI2-Q53 [P2]** `NiRotatingParticles` — does each particle carry its
  own rotation axis and angle, or is rotation shared across the set?
  Where is the per-particle rotation state stored?

## K. NiPerParticleData

- **NI2-Q54 [P1]** Field-by-field per-particle state. Specifically:
  position, velocity, age, lifespan, color, size, rotation, rotation
  speed, any others.
- **NI2-Q55 [P2]** Is per-particle state in mesh-local space, parent-node
  space, or world space?
- **NI2-Q56 [P2]** How is "particle alive vs dead" represented — explicit
  flag, sentinel age value, separate alive-list?

## L. Modifiers — field-by-field

For each modifier: list fields, describe semantics, note any tunable
behavior, flag whether the modifier mutates per-particle state or controller
state.

- **NI2-Q57 [P1]** `NiParticleModifier` (base). What's the common
  protocol — what virtual functions, what shared fields, what's the
  intended subclass contract?
- **NI2-Q58 [P1]** `NiEmitterModifier`. Emission shape (point / box /
  sphere / mesh / other?), birth rate, initial particle state setup,
  spawn budget, any "burst" mode.
- **NI2-Q59 [P1]** `NiGravity`. Gravity modes (directional / point /
  vortex?), strength, falloff, axis encoding.
- **NI2-Q60 [P2]** `NiParticleBomb`. Trigger condition, position,
  magnitude, falloff curve, duration.
- **NI2-Q61 [P1]** `NiParticleCollider` (base). Collision-response
  protocol, restitution / friction model.
- **NI2-Q62 [P1]** `NiPlanarCollider`. Plane representation,
  one-sided vs two-sided, response parameters.
- **NI2-Q63 [P2]** `NiSphericalCollider`. Sphere position/radius,
  inside-vs-outside semantics, response parameters.
- **NI2-Q64 [P1]** `NiParticleColorModifier`. Color-over-lifetime keys
  — key count limits, interpolation mode, key value encoding.
- **NI2-Q65 [P1]** `NiParticleGrowFade`. Size-over-lifetime keys —
  same questions.
- **NI2-Q66 [P2]** `NiParticleMeshModifier`. Mesh reference, how mesh
  particles differ from billboards, scale evolution.
- **NI2-Q67 [P2]** `NiParticleRotation`. Per-particle rotation axis,
  initial angle, rotation rate, randomization.
- **NI2-Q68 [P3]** Any modifiers I haven't listed that you encounter in
  the directory? List them with one-line summaries.

## M. Particle lifecycle

- **NI2-Q69 [P1]** Spawn: when a new particle is born, walk through the
  step-by-step initialization (which fields are set, by which modifier,
  with what defaults).
- **NI2-Q70 [P1]** Update step: walk through one frame of integration
  for a single particle (position += velocity·dt, modifier passes,
  collision response, age advance, color/size key evaluation).
- **NI2-Q71 [P1]** Death: what triggers death (age ≥ lifespan, collision,
  bomb), and what happens (slot reused immediately, deferred, freed)?
- **NI2-Q72 [P2]** Pool reuse: when a dead slot is recycled, is the
  state zeroed first or just overwritten?

## N. Particle rendering

- **NI2-Q73 [P1]** How does the renderer iterate live particles —
  through the per-particle data array directly, via an indirection,
  via a render-time gather?
- **NI2-Q74 [P1]** Billboard quad construction: where does the quad's
  vertex generation happen (geometry-shader-style at render, CPU-side
  in the particle update, pre-allocated and updated in place)?
- **NI2-Q75 [P2]** Sort order within a particle set — back-to-front,
  insertion order, none?
- **NI2-Q76 [P2]** Property stack interaction: what properties does the
  particle node typically carry, and does the renderer honor them
  identically to ordinary geometry?
- **NI2-Q77 [P3]** Mesh-particle rendering path — does each mesh
  particle get its own draw call, are they instanced, or batched
  somehow?

## O. Limit categorization (load-bearing for our renderer design)

For every fixed cap you've described above, return here and re-tag it.

- **NI2-Q78 [P1]** **Maximum particles per system.** Where is it
  enforced (data, controller, renderer)? Tag with **[structural /
  runtime / hardware-era]**.
- **NI2-Q79 [P1]** **Maximum color/size keys per modifier.** Tag.
- **NI2-Q80 [P1]** **Maximum simultaneous lights per object.** Where
  is the 8-light cap from round 1 enforced — in the on-disk format,
  in the scene-graph `AttachEffect` machinery, in the renderer? Tag.
- **NI2-Q81 [P1]** **Maximum bones per skin partition.** Where is
  the 4-bone default from round 1 enforced — in `NiSkinData`, in
  `NiSkinPartition`'s schema, in the renderer? Tag.
- **NI2-Q82 [P1]** **Maximum UV sets per vertex.** Format limit or
  renderer limit? Tag.
- **NI2-Q83 [P1]** **Maximum multitexture stages per pass.** Tag.
- **NI2-Q84 [P2]** Any other caps you encounter while reading these
  files — list them with the same tag.

## P. BC custom blocks hints (low-stakes but valuable if present)

- **NI2-Q85 [P3]** While reading the converter code or the old-particle
  directory, did you see any reference to class names that look
  BC-specific (not in the stock `Ni*` hierarchy)? Names containing
  "Engine", "Phaser", "Torpedo", "Hardpoint", "Wash", "Trail", or other
  Trek-flavored vocabulary. List any you see.
- **NI2-Q86 [P3]** Any conversion-time fallback paths that look like they
  exist specifically to accommodate unusual content — e.g., "if class
  name starts with X, treat as Y"?

## Q. Cross-cutting clarifications from round 1

While you're in the SDK, three follow-ups from round 1 that turned out to
matter more than anticipated:

- **NI2-Q87 [P2]** `NiOldAnimationConverter` was named in round 1 but
  not described. After reading it, **what did it teach you that the
  round-1 answers got wrong or oversimplified?** Be specific.
- **NI2-Q88 [P2]** Round-1 Q74 said text-key tag strings are
  "application-defined" and listed `"start"` and `"end"` as the only
  ones the converter looks for. Re-verify this from inside the
  converter and list **every** literal text-key string the converter
  matches, even if it just logs them.
- **NI2-Q89 [P2]** Round-1 Q149 noted there are no documented
  3.x → 4.x → 1.0 conversion notes in the docs. Does the converter's
  *code* (vs the docs) reveal anything about that transition that the
  doc tree doesn't?

---

## Answer return format

Same as round 1:

1. **Match the IDs.** `NI2-Q42 [documented] [hardware-era] <prose>`.
2. **Group by section.** Sections A–Q.
3. **Headline findings** at the top (5–10 bullets of most load-bearing
   facts).
4. **Limit-tag summary table** at the end: a single table of every
   cap mentioned with its category tag, so we have a one-page lookup
   when designing the renderer.
5. **Not-found list** at the end.
6. **No code, no struct layouts, no internal symbols.** Public class
   names are fine.

If ambiguous, answer your best guess and flag the ambiguity — don't skip
asking for clarification, since you only get one round.

Thank you. As before, this is the only artifact crossing the threshold;
everything downstream depends on the care you take.
