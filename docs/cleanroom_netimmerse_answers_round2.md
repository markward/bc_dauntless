# NetImmerse / Gamebryo SDK — Round 2 Clean-Room Answers

## Framing

This round answers questions about BC's animation and old-particle data
models, sourced from reading:

- The animation post-load fixup pass (the one named in round 1 as the
  legacy converter).
- The animation system descriptor module (SDM), which is where the
  legacy-class-name aliases live and where the post-process is registered.
- Every individual legacy controller class (`NiTransformController`,
  `NiVisController`, `NiAlphaController`, `NiUVController`, `NiFlipController`,
  `NiMaterialColorController`, `NiLightColorController`,
  `NiLookAtController`, `NiPathController`, `NiRollController`).
- The legacy data classes `NiTransformData` (formerly `NiKeyframeData`),
  `NiBoolData` (formerly `NiVisData`), `NiUVData`, `NiPosData`,
  `NiFloatData`, `NiColorData`.
- The legacy `NiSequence` and `NiKeyframeManager`.
- The entire old-particle library: `NiParticleSystemController`,
  `NiPerParticleData`, `NiParticleModifier` (base), `NiEmitterModifier`
  (base), `NiGravity`, `NiParticleBomb`, `NiParticleCollider` (base),
  `NiPlanarCollider`, `NiSphericalCollider`, `NiParticleColorModifier`,
  `NiParticleGrowFade`, `NiParticleMeshModifier`, `NiParticleRotation`.
- The old-to-new particle converter (which is a **separate tool library**
  the application opts into; not part of the engine core).
- The base `NiTimeController` for its flag-bit and time-field layout.

The single biggest correction to round 1 is buried in section Q below;
**read NI2-Q87 first** if you only have time for one thing.

---

## Headline findings

1. **There is no single "animation converter" in the round-1 sense.**
   Legacy animation loading is split across three mechanisms that all
   fire during stream load: (a) RTTI-name aliasing in the registration
   table swaps old class names for modern classes at body-construction
   time; (b) version-gated branches in each modern class's body-reader
   handle the on-disk shape of the old data; (c) a single post-process
   function does the only graph-topology fixup that's needed, and it
   only handles **three** controllers — `NiLookAtController`,
   `NiRollController`, `NiPathController` — collapsing them onto a
   single `NiTransformController` per target.

2. **The legacy class-name aliases are exactly three:**
   `"NiKeyframeController"` → modern `NiTransformController`,
   `"NiKeyframeData"` → modern `NiTransformData`,
   `"NiVisData"` → modern `NiBoolData`. Other legacy controllers
   (`NiAlphaController`, `NiVisController`, `NiUVController`,
   `NiFlipController`, `NiMaterialColorController`,
   `NiLightColorController`) **kept their original names** and are still
   first-class classes in this Gamebryo 1.2.2 SDK — but their *body
   layouts* changed at NIF 10.1.0.104, and their `LoadBinary` paths
   branch on file version to read the old layout when needed.

3. **The trigger version for legacy-format handling is NIF 10.1.0.104.**
   Every version-gated branch in every legacy-data-class reader uses
   this exact constant. Files at or above this version are read
   directly into the modern format. BC's NIFs are far below this
   threshold, so all of BC's animation goes through the old paths.

4. **Animation key data hangs off `NiTransformData` (née `NiKeyframeData`)
   as three independent channels** — rotation, position, scale — each
   with its own key count, key type enum, and stride. Channels are
   stored sequentially on disk: `[rotation count + type + key array]
   [position count + type + key array] [scale count + type + key
   array]`. The three key types are independent: rotation can be
   LINEAR while position is BEZIER and scale is TCB in the same block.
   There is a runtime assertion that **if the rotation channel uses
   the Euler key type, it must contain exactly one key** — because that
   single "Euler key" is itself a container for three independent
   float-key arrays (X, Y, Z).

5. **BC text-key tag strings are entirely application-defined.** The
   converter looks for **zero** literal text-key strings. There is
   nothing in this SDK that interprets `"start"`, `"end"`, `"sound:..."`,
   or any other tag — those interpretations are 100% BC's runtime. The
   one place specific tag strings *do* appear in the conversion path is
   completely unrelated: `NiMaterialColorController` and other channel-
   selecting controllers use a `GetCtlrID()` string ("AMB", "DIFF",
   "SPEC", "SELF_ILLUM") to identify themselves for sequence rebinding
   — but those are *controller identifiers*, not text keys.

6. **The old-particle system is a single class doing everything,
   with three parallel linked lists of modifiers.** `NiParticleSystemController`
   carries all the emitter/lifecycle parameters as direct fields,
   plus head pointers for three separate chains: emitter modifiers,
   particle modifiers, particle colliders. Each chain is a singly-linked
   list traversed in **insertion order** (or, more precisely, in
   reverse-of-attach order — modifiers are prepended at attach).

7. **The on-disk per-particle state encodes more than is needed at
   runtime.** Even though only **active** particles need state, the
   format streams `m_usNumParticles` (the capacity) per-particle records.
   The renderer slot they target is also encoded. This means BC's NIFs
   can pre-load with particle state already in mid-flight, useful for
   "scene starts with effects already going."

8. **The old-particle capacity is fixed at NIF-author time as the
   vertex count of the underlying `NiParticles` geometry object.** The
   controller hosts at most that many particles. You can't dynamically
   grow the system at runtime. This is a structural limit on the
   format, not a hardware-era one.

9. **The forward-conversion to the modern particle system is in a
   *tool library*, not the engine core.** `NiOldParticleConversion`
   has its own SDM init that registers a post-process function — meaning
   an application that doesn't link this library will simply leave old
   particles as old particles and run them via `NiOldParticle`. BC's
   engine almost certainly never converted; it ran the old system
   natively, the same way Gamebryo 1.0 did.

10. **There are exactly five fields per particle stored in
    `NiPerParticleData`**, all `NiAVObject`-space (parent-relative): a
    velocity vector, a rotation axis, age, lifespan, and a
    "last update time"; plus two `unsigned short` indices (generation
    counter and vertex-slot index into the `NiParticlesData`'s vertex
    array). **Color, size, position, rotation, and normal live in the
    `NiParticlesData` arrays, not here.** Per-particle state is split
    between the controller and the geometry data, with the geometry
    data carrying the rendered attributes and the controller carrying
    the simulation state.

---

## A. Animation converter — overall shape

- **NI2-Q1 [inferred from source]** The post-load fixup function takes a
  `NiStream` reference and a single `NiObject` pointer. It checks the
  stream's NIF version: if the file is **already at or above
  10.1.0.104**, it returns immediately with no work. Otherwise, if the
  passed object is an `NiObjectNET`, it recurses through the scene
  graph (descending into `NiAVObject` children of `NiNode`s) and for
  every `NiAVObject` it iterates the attached controller list, looking
  for one of three controller types and converting each in place.

  The flow from "BC NIF just loaded" to "modern controllers in place"
  is therefore: the loader constructs old-named blocks as modern
  classes (via name aliasing), each modern class's reader handles the
  old field layout (via version-gated branches), and finally the
  post-process function walks the loaded tree and collapses any
  remaining `NiLookAt`/`NiRoll`/`NiPath` controllers onto unified
  transform controllers. By the time control returns to the
  application, the scene graph contains only modern controller
  classes.

- **NI2-Q2 [inferred from source]** Conversion runs **at the end of
  the load pipeline**, after all bodies have been read and link IDs
  resolved, before top-level objects are returned to the caller. The
  hook is a registered "post-process function" — `NiStream` keeps an
  array of these and invokes each one on every top-level object after
  linking completes. The animation conversion is registered once at
  SDM init. Application-callable manual conversion does not appear to
  be exposed.

- **NI2-Q3 [inferred from source]** The converter recognizes **only
  three** legacy class names. The mapping is:

  - `NiLookAtController` → wraps its target object reference and axis
    into a new `NiLookAtInterpolator` driven by a fresh or existing
    `NiTransformController` on the same target. Position and scale
    tracks from the target's preexisting transform interpolator (if
    any) are migrated onto the new look-at interpolator as side
    interpolators.
  - `NiRollController` → its float-data is wrapped in a new
    `NiFloatInterpolator` and attached as the **roll sub-interpolator**
    of an existing look-at interpolator on the same target. If no
    look-at is present, the roll is dropped silently. (This is an
    asymmetric coupling — roll can only exist when look-at also exists.)
  - `NiPathController` → all of its path-shape settings (allow-flip,
    bank, bank direction enum, constant-velocity flag, follow flag,
    max bank angle, smoothing scalar, follow axis enum, flip flag,
    curve-type-open flag) plus its path-data and percentage-data
    objects are folded into a new `NiPathInterpolator`, which becomes
    the interpolator of a `NiTransformController` on the target.

  Other legacy controllers (`NiAlphaController`, `NiVisController`,
  `NiUVController`, `NiFlipController`, `NiMaterialColorController`,
  `NiLightColorController`) are **not** touched by this post-process.
  They retain their legacy class names and behave as legacy controllers
  forever after. Their data-block conversion (legacy `NiFloatData`
  pointer → modern interpolator) happens inside each class's own
  `LinkObject` step at load time.

  And `NiKeyframeController` → `NiTransformController` is handled
  entirely at the class-aliasing layer: an old `NiKeyframeController`
  block is constructed as a `NiTransformController` from the start;
  its `LoadBinary` reads the legacy `NiKeyframeData` link, and
  `LinkObject` constructs a `NiTransformInterpolator` from that
  legacy data. No post-process is involved.

- **NI2-Q4 [inferred from source]** Unrecognized controllers are
  **silently passed through** by the post-process — the converter only
  branches on three known types and does nothing for any other type.
  Combined with answer NI2-Q3, this means controllers that don't fall
  into the three categories never see the post-process function. There
  is no warning, no logging, no error.

- **NI2-Q5 [inferred from source]** The converter retains **no state**.
  It doesn't build a map of old→new conversions, it doesn't log what it
  did, and applications cannot query "what got converted in this load."
  Each conversion is destructive (the old controller is removed from
  the target's list and replaced) and the original is dropped on the
  floor.

## B. NiSequence (BC's animation clip)

- **NI2-Q6 [inferred from source]** `NiSequence` carries:
  - **Name** — a heap-allocated C string identifying the sequence.
  - **Object-name array** — a parallel array of C strings, one per
    sub-controller, naming the scene-graph node that controller
    targets. Resolution at activation time is by `GetObjectByName`.
  - **Controller array** — same length, holds smart pointers to
    `NiTransformController` objects (note: not generic
    `NiTimeController`s; the legacy sequence model is transform-only).
  - **Text-key reference index** — a `u32` that names which controller's
    timing the text keys are anchored to. Comment in the header says
    this is the index into the animation manager's controller list
    that the text-key times refer to (for cycle-type, start/end times).
  - **Text-key smart-pointer** — to an `NiTextKeyExtraData` carrying
    the text keys for the whole sequence.

- **NI2-Q7 [inferred from source]** Sub-controllers are stored **by
  smart pointer**, one entry per parallel (object-name, controller)
  pair. They are owned by the sequence. On disk they are written as
  link IDs.

- **NI2-Q8 [inferred from source]** Targets are resolved **by name
  string at activation time**, not by stored pointer at load. The
  sequence stores `(node-name, controller)` pairs; when the keyframe
  manager activates a sequence against a scene, it must look each name
  up in the scene graph. This means the same sequence can drive any
  character with matching node names — the same way modern
  `NiControllerSequence` works, just with simpler keying.

- **NI2-Q9 [inferred from source]** `NiSequence` carries text keys
  **by reference** (a smart pointer to an `NiTextKeyExtraData`). Not
  embedded. Older KF files (< NIF 4.1.0.3) stored the text keys as
  extra-data on a transient `NiSequenceStreamHelper` container; the
  conversion path moves them onto the constructed sequence.

- **NI2-Q10 [inferred from source]** **Per-controller**, not per-sequence.
  Each sub-controller of the sequence carries its own
  start/stop/frequency/phase/cycle-type fields (inherited from
  `NiTimeController`). The sequence itself has no global timing — the
  text-key-reference field names which sub-controller's timing the
  text keys are anchored to, but otherwise sequences are containers of
  independently-timed sub-controllers. This is significantly different
  from modern `NiControllerSequence`, which centralizes timing.

- **NI2-Q11 [inferred from source]** Multiple `NiSequence` objects in
  one file are routed through `NiKeyframeManager`, which is a
  `NiTimeController` subclass attached to the scene root. The manager
  owns a name-keyed map of sequences (zero or more of them, plus
  external KF file references — see Q12). Active vs inactive selection
  is a runtime API (presumably callable through manager methods), not
  a NIF field. So `NiSequence` is **not a top-level scene-graph
  object**; it's a child resource of the keyframe manager.

- **NI2-Q12 [inferred from source]** Yes, `NiSequence`'s on-disk
  layout changed at NIF 4.1.0.3. Pre-4.1.0.3, sequences inside KF
  files are encoded as a transient helper container (the
  `NiSequenceStreamHelper`) carrying a controller chain and parallel
  string-extra-data entries; on load, the converter walks the
  controller chain and the extra-data list pairwise, constructing an
  `NiSequence` on the fly. From 4.1.0.3 onward, sequences are saved
  natively. The keyframe manager *also* version-gates: pre-4.1.0.3 it
  reads a more elaborate layout (per-sequence "saved URL" flag, per-
  sequence text-key state, per-key object name + controller link)
  versus the modern layout which is just a list of sequence link IDs.

  BC's files are NIF ~4.0.x, so they fall under the pre-4.1.0.3 path —
  i.e., **BC's animation files use the helper-container path with
  parallel string-extra-data**.

## C. NiKeyframeController + NiKeyframeData

- **NI2-Q13 [inferred from source]** `NiKeyframeController` itself
  carried no fields beyond the base `NiTimeController`. In legacy
  files it appended a single link ID pointing to its `NiKeyframeData`.
  That link is the entire body extension. On load via the modern
  alias path, that link is read into the controller's modern
  interpolator slot via `NiTransformInterpolator(legacyData)`.

- **NI2-Q14 [inferred from source]** `NiKeyframeData`/`NiTransformData`
  has three independent channels stored sequentially:

  1. **Rotation channel**: `u32 numRotKeys`. If non-zero, an enum
     selecting the rotation key type (LINEAR / BEZIER / TCB / EULER /
     STEP), then `numRotKeys` keys of the appropriate size.
  2. **Position channel**: `u32 numPosKeys`. If non-zero, position key
     type enum (LINEAR / BEZIER / TCB / STEP), then keys.
  3. **Scale channel**: `u32 numScaleKeys`. If non-zero, float key type
     enum (LINEAR / BEZIER / TCB / STEP), then keys.

  Each channel is fully optional — zero keys means "no animation for
  this channel" and the target keeps its bind-pose value for that
  channel. There is no interleaving; each channel is one contiguous
  array.

- **NI2-Q15 [inferred from source]** **One key type per channel**,
  encoded immediately after the count. So rotation can be LINEAR while
  position is BEZIER and scale is TCB. The discriminator is the enum
  byte/word after each non-zero count. Within a single channel, all
  keys are the same type.

- **NI2-Q16 [inferred from source]** When a channel has zero keys,
  the modern interpolator built from this data reports "value invalid"
  for that channel on every update, and the runtime simply skips
  writing that field of the target's transform — meaning the target's
  bind-pose value for that channel is preserved untouched (translation
  stays, rotation stays, scale stays, whichever channel was empty).

- **NI2-Q17 [inferred from source]** The `NiEulerRotKey` is **not**
  stored as a normal rotation key in `NiKeyframeData`. The data block
  carries `numRotKeys == 1` and key type EULERKEY, and that single
  key's body contains three separate float-key arrays (X, Y, Z) with
  their own counts, types, and keys. Tracks **can be absent
  independently** — each axis float-array can have zero keys, meaning
  that axis isn't animated; the runtime defaults that axis to zero
  rotation contribution.

  The runtime enforces `numRotKeys == 1` for EULER via an explicit
  assertion at save time and at equality testing. It is impossible to
  have multiple Euler keys per block.

- **NI2-Q18 [inferred from source]** The base `NiKeyframeData` body
  layout itself is stable; it has not picked up version-gated extras.
  The version-gating in the family is at the `NiBoolData` layer
  (key-type enum became explicit at 10.1.0.104; before that, step keys
  were the only option) and the `NiVisController`/`NiAlphaController`/
  etc. layer (legacy data-link → modern interpolator construction
  gated on 10.1.0.104). For BC-era files (NIF 4.x), the per-key data
  layout is consistent.

- **NI2-Q19 [inferred from source]** The conversion from
  `NiKeyframeController(+Data)` to
  `NiTransformController(+NiTransformInterpolator)` is mechanical:

  - All base `NiTimeController` fields (frequency, phase, start time,
    end time, cycle-type bits, anim-type bit, active bit, play-backwards
    bit, manager-controlled bit) move 1:1 onto the new transform
    controller (via the standard base-class reader).
  - The link to the old `NiKeyframeData` is resolved during the link
    phase; the loader constructs `NiTransformInterpolator(pkLegacyData)`
    and assigns it to the controller's interpolator slot.
  - The interpolator's `Collapse()` is called to trim out unused
    channels and minimize memory.
  - Nothing is discarded; the new interpolator wraps the same key
    arrays the legacy data already carried.

  Crucially, the legacy `NiKeyframeData` object **still exists** as a
  `NiTransformData` (its modern alias) inside the new interpolator;
  the conversion is a wrapper, not a data copy.

## D. Other legacy controllers

- **NI2-Q20 [inferred from source]** `NiVisController`:
  - **Targets** any `NiAVObject` and animates its `AppCulled` flag
    (logically inverted — `true` value means "visible / not culled").
  - **Reads** at load time: a single link to legacy `NiVisData` (when
    file < 10.1.0.104). On link, that data — now aliased as `NiBoolData`
    — is wrapped in a new `NiBoolInterpolator` and stored as the
    controller's interpolator. The class itself is preserved as
    `NiVisController` in the modern model.
  - **Modern equivalent:** `NiVisController` with a `NiBoolInterpolator`;
    or for new content, the more general `NiBoolInterpController`.
  - **Visibility key encoding:** in legacy files, visibility keys are
    implicitly step boolean keys with timestamps — the on-disk layout
    is `u32 numKeys; <per-key: time(f32), bool(byte)>`. From 10.1.0.104
    onward, a key-type enum is read first (still typically `STEPKEY`),
    allowing future key shapes.

- **NI2-Q21 [inferred from source]** `NiAlphaController`:
  - **Targets** `NiMaterialProperty`; animates its alpha channel
    via `SetAlpha(float)`.
  - **Reads** at load: one link ID to legacy `NiFloatData` (when
    file < 10.1.0.104). On link, wraps that data in a new
    `NiFloatInterpolator`.
  - The float-key encoding is the standard float-key family
    (LIN/BEZ/TCB/STEP).
  - **Modern equivalent:** `NiAlphaController` with `NiFloatInterpolator`
    (same class name, modern interpolator slot).

- **NI2-Q22 [inferred from source]** `NiColorController` does not
  appear as a discrete class in this SDK — its functionality is
  subsumed by `NiPoint3InterpController` subclasses, primarily
  `NiMaterialColorController` (see Q23) and `NiLightColorController`.
  Any legacy `"NiColorController"` block would have a 1:1 modern
  equivalent in one of those two classes. The legacy data was
  `NiColorData` carrying color keys — that class still exists in the
  SDK as a first-class data block.

- **NI2-Q23 [inferred from source]** `NiMaterialColorController`:
  - **Targets** `NiMaterialProperty`; animates one of four color
    channels via a 3-bit "field" selector packed into its flags word:
    AMBIENT (0), DIFFUSE (1), SPECULAR (2), SELF_ILLUM/EMISSIVE (3).
  - **Channel selector encoding:** in legacy files (< NIF 10.0.1.2), the
    field selector was packed in higher bits of the base
    `NiTimeController` flag word; the controller's load path shifts
    those bits down into its own flag word and masks them. From
    10.0.1.2 onward, the selector is stored as a dedicated `u16`
    immediately after the base controller fields.
  - **Reads** at load: same legacy-data → modern-interp pattern as
    Q21/Q22, but using `NiPosData` (color-as-Point3) wrapped in
    `NiPoint3Interpolator`.
  - The runtime clamps each output channel to [0, 1] before writing
    to the material — important to mirror.

- **NI2-Q24 [inferred from source]** `NiUVController` + `NiUVData`:
  - **Targets** `NiGeometry` directly (not its `NiTexturingProperty`).
    The controller carries a `u16 textureSet` index naming which UV
    set on the geometry's vertex data it modifies.
  - **Fields** on the data class: four independent float-key arrays
    — U offset, V offset, U tiling, V tiling — each with its own
    count, key type, and key data. Order on disk: U-offset, then
    V-offset, then U-tiling, then V-tiling.
  - **Composition:** the runtime computes, per frame, four scalars
    (one per channel) and applies them to every vertex's UV in the
    targeted texture set. The application is: `newUV.u = scaleU·oldUV.u
    + offsetU·someDiffTerm`, computed against the previous frame's
    state because the original UVs aren't stored (this is a *stateful*
    delta accumulation — `NiUVData` remembers its last computed
    offset/tiling values to compute the delta for next frame). The
    composition is documented as "to match Max behavior, tiling is
    centered about 0.5, U offset is subtracted, V offset is added."
    Composition order is effectively `T·S` per axis, applied around
    UV-space center (0.5, 0.5).
  - **Crucially: the UV controller mutates the vertex buffer in
    place.** This is unlike modern `NiTextureTransformController`,
    which sets a per-stage transform matrix the renderer applies on
    the GPU. For a reimplementation, you'll want to translate to the
    matrix model — but BC content will have authored against the
    mutation model.
  - **Modern equivalent:** `NiTextureTransformController` on a specific
    `NiTexturingProperty::Map` stage.
  - **Limit:** tiling values of 0.0 trigger a debug assertion.

- **NI2-Q25 [inferred from source]** `NiPathController` + `NiPathData`:
  - **Path representation:** a `NiPosData` carrying position keys
    (the path's control points / shape, in the chosen interpolation
    type — typically TCB or BEZIER for smooth paths) **plus** a
    separate `NiFloatData` carrying the "percentage-traversed" curve
    (how far along the path the controlled object is at each time).
    Two animation-key arrays driving the same animation: one is the
    path's geometry, the other is the parameterization.
  - **Orientation rules** (all booleans/scalars stored as fields):
    - `AllowFlip` — whether the controlled object can flip its
      orientation along the path.
    - `Follow` — if true, orient the object along the path tangent;
      if false, just translate without orientation change.
    - `FollowAxis` — `i16`, naming which axis (X/Y/Z, signed) of the
      controlled object aligns with the path tangent.
    - `Flip` — explicit orientation flip flag.
    - `ConstVelocity` — if true, reparameterize the path so the
      object moves at constant speed regardless of the percentage
      curve's shape (uses a precomputed arc-length lookup).
    - `Smoothing` — float scalar, the path-smoothing factor.
    - `CurveTypeOpen` — open vs closed path (loop).
  - **Banking:**
    - `Bank` — boolean, whether to bank into turns.
    - `BankDir` — enum `NEGATIVE = -1, POSITIVE = +1`, banking sense.
    - `MaxBankAngle` — float, in radians, cap on bank.
  - **Modern equivalent:** `NiPathInterpolator` driving an
    `NiTransformController`. The post-process function does the
    rebinding.

- **NI2-Q26 [inferred from source]** `NiLookAtController`:
  - **Target:** any `NiAVObject`; orients it to face a separate
    `NiAVObject` "look-at target" stored as a raw pointer field.
  - **Axis selector:** enum `X, Y, Z` (3 values), naming which axis
    of the controlled object points at the look-at target.
  - **Flip:** boolean, inverts the orientation.
  - **Up-vector:** not stored as an explicit field; the implementation
    uses world up implicitly (or the controlled object's own up axis
    depending on the configuration — the look-at code is in the
    interpolator, not the controller).
  - **Modern equivalent:** `NiLookAtInterpolator` driving an
    `NiTransformController`. The post-process function:
    1. Finds or creates a `NiTransformController` on the target.
    2. If a transform controller already exists with a transform
       interpolator, peels off its position and scale tracks and
       attaches them as side interpolators of the look-at interp.
       (This is so a node can both look-at and translate.)
    3. Removes the old `NiLookAtController` from the target.

- **NI2-Q27 [inferred from source]** `NiFlipController`:
  - **Targets** an `NiTexturingProperty`; animates the texture pointer
    on one of its map slots (and supports shader-map slots via an
    offset-encoded index: `affectedMap < 1024` means standard map
    slots; `affectedMap >= 1024` selects shader maps at index
    `affectedMap - 1024`).
  - **Texture array:** carries an array of smart pointers to
    `NiTexture` objects — one per "frame" of the flipbook.
  - **Legacy timing (< NIF 10.1.0.104):** two floats encode the
    animation: `startTime` (when frame 0 begins) and `secondsPerFrame`
    (uniform frame duration). The loader synthesizes step-keyed
    float keys from these: one key per texture frame plus one
    duplicate final key for clamp/loop endpoint stability.
  - **Modern timing:** an explicit `NiFloatInterpolator` with
    user-defined keys.
  - **Modern equivalent:** still called `NiFlipController`; the
    interpolator wrapping is invisible to the user. No external
    conversion needed.
  - **Pinning behavior:** the index is computed by clamping the
    interpolated float plus a 0.01 fudge to the texture array's
    size minus one. Out-of-range values stick to the last frame.

- **NI2-Q28 [inferred from source]** Additional legacy controllers
  noted while reading:
  - `NiLightColorController` — animates a light's ambient or diffuse
    color (boolean selector flag in flags word). Legacy data → modern
    `NiPoint3Interpolator` wrapping, same pattern as
    `NiMaterialColorController`. Targets `NiLight`.
  - `NiFloatController` — generic base for legacy float-keyed
    controllers. `NiAlphaController` and `NiRollController` derive
    from it; both load their legacy `NiFloatData` link into a modern
    float interpolator at link time.
  - `NiKeyframeManager` itself — see B/Q11.

  These are not transformed by the post-process function; they are
  fully resolved during stream load.

## E. Old-to-modern mapping table

- **NI2-Q29 [inferred from source]**

  | Legacy class | Modern class(es) | Cardinality | Where converted |
  | --- | --- | --- | --- |
  | `NiKeyframeController` | `NiTransformController` + `NiTransformInterpolator` | 1:1 (class swap + wrap) | RTTI alias + `LoadBinary` version branch |
  | `NiKeyframeData` | `NiTransformData` | 1:1 (rename only) | RTTI alias |
  | `NiVisData` | `NiBoolData` | 1:1 (rename only) | RTTI alias |
  | `NiVisController` | `NiVisController` + `NiBoolInterpolator` | 1:1 (wrap legacy data) | `LinkObject` version branch |
  | `NiAlphaController` | `NiAlphaController` + `NiFloatInterpolator` | 1:1 (wrap legacy data) | `LinkObject` version branch |
  | `NiMaterialColorController` | `NiMaterialColorController` + `NiPoint3Interpolator` | 1:1 (wrap + flag-bit reshuffle) | `LoadBinary` version branch |
  | `NiLightColorController` | `NiLightColorController` + `NiPoint3Interpolator` | 1:1 (wrap) | `LoadBinary` version branch |
  | `NiFlipController` | `NiFlipController` + synthesized `NiFloatInterpolator` (step keys from start+rate) | 1:N (synthesizes key array) | `LoadBinary` version branch |
  | `NiUVController` | `NiUVController` (deprecated but kept) — **or** `NiTextureTransformController` for new content | 1:1 (no conversion in this SDK) | none (legacy preserved) |
  | `NiLookAtController` | `NiTransformController` + `NiLookAtInterpolator` (+ optional position/scale side interpolators) | N:1 (combines with existing transform ctlr) | post-process function |
  | `NiRollController` | Roll sub-interpolator on a `NiLookAtInterpolator` | N:1 (folded into look-at; dropped if no look-at) | post-process function |
  | `NiPathController` | `NiTransformController` + `NiPathInterpolator` | 1:1 (with field-by-field copy) | post-process function |
  | `NiSequence` (helper-container form) | `NiSequence` (native form) | 1:1 (helper-container assembly) | `CreateFromKFFile`/`ConvertSequence` |
  | `NiKeyframeManager` (old per-key layout) | `NiKeyframeManager` (link-ID layout) | 1:1 | `LoadBinary`/`LinkObject` version branch |

- **NI2-Q30 [inferred from source]** Irreversible losses observed:
  - **`NiRollController` without a sibling `NiLookAtController`** is
    dropped silently. Roll is asymmetrically coupled.
  - **For pre-10.0.1.2 `NiMaterialColorController` files**, the flag-bit
    reshuffle masks out bits unused by the new layout, but it's a
    well-defined transformation, not a loss.
  - **For pre-10.1.0.109 files**, the "manager-controlled" bit on
    every `NiTimeController` is forcibly cleared. The bit was
    repurposed in newer versions; if BC's content uses that bit for
    its own purpose, the meaning differs.
  - **`NiFlipController` step-key synthesis** discards the legacy
    `startTime`/`secondsPerFrame` fields after building the
    synthesized float-key array. Cannot round-trip.

- **NI2-Q31 [inferred from source]** Defaults filled in:
  - The synthesized flip-controller end-key duplicates the last
    texture index, fudged with one extra frame's worth of time.
  - The look-at conversion default-constructs a transform controller
    if none existed on the target, with all base timing fields copied
    from the look-at controller via the "synchronize time controllers"
    helper (anim-type, cycle-type, play-backwards, frequency, phase,
    begin-key-time, end-key-time, active).
  - The path conversion does the same when no transform controller
    pre-exists, plus re-orders the controller list so the new transform
    controller comes immediately after the old path controller in the
    target's list.
  - **No defaults are invented from thin air** — every field copy has
    a source.

## F. Quirks, gotchas, version gates

- **NI2-Q32 [inferred from source]** Version gates observed in
  legacy paths:
  - **NIF 10.1.0.104** — the universal "old vs new" cutoff. Every
    legacy data class (`NiTransformController`, `NiVisController`,
    `NiAlphaController`, `NiMaterialColorController`,
    `NiLightColorController`, `NiFlipController`) version-gates its
    body on this constant. Files at or above this version read the
    interpolator-based modern layout; files below read the legacy
    data-link layout. The post-process function itself bails out at
    this version. **BC's files are below.**
  - **NIF 10.1.0.109** — when the "manager-controlled" flag bit was
    repurposed. Files below have that bit force-cleared.
  - **NIF 10.0.1.2** — when `NiMaterialColorController`'s field
    selector moved from base-flag-bits into its own flag word.
  - **NIF 10.0.1.1** — when the `NiTimeController` "play-backwards"
    bit was added. Files below: a complex flag-bit shift to insert the
    new bit. Files exactly at 10.0.1.1: a separate boolean appears in
    the body after the standard fields.
  - **NIF 10.0.1.16** — when geometry-modifying controllers started
    requiring their target geometry to be marked `VOLATILE`. Older
    files retroactively set this flag at link time.
  - **NIF 4.1.0.3** — when `NiSequence` stopped using
    `NiSequenceStreamHelper`-based KF files. Files below the
    threshold go through the helper conversion path.
  - **NIF 3.3.0.15** — the particle controller's static-bound flag
    was added (see section H).

- **NI2-Q33 [inferred from source]** Hints of compromise:
  - In the animation post-process recursion, a chunk of property-list
    walking is commented out as conditional: "If we ever need to
    convert property time controllers, this code should be uncommented."
    This suggests an open hole — property-attached legacy controllers
    are not visited by the post-process walk. If BC ever attached a
    `NiLookAtController` to a `NiProperty` (unlikely but not
    impossible), it would not be converted. Property-attached legacy
    controllers are handled only by the per-class load-time path.
  - In the particle library, the comment "old system reversed
    direction of gravity" appears next to a multiplication by 1.0 — a
    no-op factor that hints at a past sign flip the code is preserving
    as a placeholder. Worth knowing if BC's gravity directions look
    inverted versus expectations.
  - In `NiParticleSystemController::PostLinkObject` there's a
    `#define REMOVE_UNUSED_ROTATIONS` block that strips
    `NiParticleRotation` modifiers from non-mesh particle systems
    because the renderer never honored rotation for billboard
    particles (note dated "Ni4.0 final release, 4/30/2001"). For BC
    this means rotation modifiers on point/billboard particles are
    silently dropped at load.

- **NI2-Q34 [inferred from source]** Hard-coded constants:
  - **`0.01f`** — fudge added to `NiFlipController`'s interpolated
    index before integer truncation, to round-down correctly.
  - **`0.0001f`** — epsilon in `NiParticleSystemController` and
    `NiParticleGrowFade` for size-clamping and time-comparison.
  - **`0.0333333333f`** — explicit 30 fps run-up sampling for
    particle initialization on first update.
  - **`0.10f`** — sampling step for computing the static bound of a
    particle system.
  - **`1.05f`** — over-size factor for the computed static bound
    ("inflate slightly for safety").
  - **`1.6f`** — strength multiplier in `NiGravity` Update. A
    units-conversion fudge factor (likely tied to a historical "what
    is 1 unit" interpretation).
  - **`12`** — default array initial size and growBy for sequence
    storage in `NiSequence` and `NiKeyframeManager`.
  - **`1024`** — `SHADER_MAP_OFFSET` in `NiFlipController` to
    distinguish standard map indices from shader map indices.
  - **`SHRT_MAX` implicit** — particle counts are stored in `u16`.

- **NI2-Q35 [inferred from source]** Nothing in either file path
  suggests BC-specific data shapes. There are no hardcoded
  named-node checks (no `"Bip01"`, no Trek vocabulary, no fallback
  paths for non-stock blocks). The converter is purely class-
  identity-driven. BC's customization must live entirely outside
  these files — in BC's own block registrations or in custom
  controllers that the converter doesn't recognize (which it
  silently passes through, per Q4).

## G. Text key conventions

- **NI2-Q36 [inferred from source]** The converter looks for **zero**
  literal text-key strings. It does not inspect `NiTextKeyExtraData`
  contents at all. The references to text keys in the legacy code are
  about *passing them through* (copying them from the helper container
  onto the sequence, or carrying the text-key-reference index), never
  about interpreting them.

- **NI2-Q37 [n/a]** No tags are recognized.

- **NI2-Q38 [inferred from source]** No documented conventions in
  this SDK. The text-key system is application-defined throughout —
  BC's runtime is the sole interpreter. The closest thing to a
  documented convention is the controller-identifier strings used by
  `NiMaterialColorController` (`"AMB"`, `"DIFF"`, `"SPEC"`,
  `"SELF_ILLUM"`) and `NiFlipController` (a decimal-encoded map index)
  via `GetCtlrID()` — these are used at sequence rebinding time to
  disambiguate "which of the four material-color controllers on this
  node is this sequence interpolator for", but they're controller
  metadata, not text keys.

  **Round 1's NI-Q74 was correct.** The converter confirms it.

## H. Old particle system — architecture

- **NI2-Q39 [inferred from source]** Per-frame data flow when
  `NiParticleSystemController::Update(time)` runs:

  1. Standard `NiTimeController` time-scaling produces `scaledTime`.
  2. If `scaledTime` < last frame's scaled time **and** the reset
     flag is set, the system clears (active count → 0, first-time
     flag re-set).
  3. **Emitter modifier chain** is updated first
     (`m_spEmitterModifiers->Update(scaledTime)`). Each emitter
     modifier updates and then forwards to its next via the base
     class's chain-walking helper.
  4. On the first call ever, a run-up loop pre-simulates the system
     at 30 fps from emit-start up to current time so the system isn't
     "empty" when first shown.
  5. **`UpdateParticles(scaledTime)`** does the heavy work:
     - Computes a wrap-around time modifier if `scaledTime` looped
       backward.
     - **Iterates every active particle:**
       - Advances age.
       - If age ≥ lifespan: optional spawn-on-death cascade, then
         remove particle (swap with last active, decrement count).
       - Otherwise: applies **particle modifier chain**
         (`m_spParticleModifiers->Update(time, particle)`), each
         modifier mutates the particle's per-particle state and/or
         vertex array entry, then forwards to its next.
       - **Collider chain** (`m_spParticleColliders->Resolve(...)`)
         finds the earliest collision in the frame, if any; if one
         occurred, that collider's `Update` resolves the response
         (which may kill the particle by returning false).
       - Integrates position: `pos += velocity · (frameEnd -
         collisionTime)`. This means position update happens *after*
         collision response.
     - **Emits new particles:** computes a birth budget for this
       frame from birth rate (or implicit rate when explicit is off),
       calls `AddNewParticle` in a loop up to capacity.
     - Recomputes the model bound (live or static-precomputed).
  6. Marks the target's vertex/normal/color arrays as changed so the
     renderer repacks them.

- **NI2-Q40 [inferred from source]** Modifier ordering **is
  significant** and is **chain-insertion-order**. There is no
  priority and no category-grouping within a chain (but emitters,
  particle modifiers, and colliders live on *separate* chains, so
  they are inherently category-grouped at that coarser level).
  Modifiers are *prepended* on attach (`SetTarget` calls `AddToTarget`
  which prepends to the head), so the iteration order is
  **reverse-of-attach**. This matters: BC's content effectively
  encodes "later-attached modifier runs first."

- **NI2-Q41 [inferred from source]** Per-particle state is **hybrid
  SoA + AoS, split across two objects**:
  - **The controller** owns an `AoS` array of `NiPerParticleData`
    (5 fields per particle, see Q54), sized at capacity.
  - **The target `NiParticlesData`** (a geometry-data subclass) owns
    parallel `SoA` arrays: vertex positions, normals, colors, radii,
    sizes, and (for mesh particles) rotations. These arrays are
    sized at capacity too.
  - A particle's `m_usIndex` field bridges: it's the vertex-array
    slot index in `NiParticlesData` that this particle "owns."

  This split is why rendering is so cheap — the renderer reads
  `NiParticlesData`'s vertex array directly without touching the
  controller's per-particle records.

- **NI2-Q42 [inferred from source]** Memory is a **fixed pool with
  reuse**. Capacity is `NiParticles::GetVertexCount()` — i.e., the
  number of vertex slots in the underlying particle geometry. Sized
  once at `SetTarget`-time. Reuse is via a "swap with last active"
  pattern: dying particles are replaced by the last active particle's
  state, and the active count is decremented. Slots above the active
  count are stale memory.

  Cap: **[structural]** — capacity is encoded into the NIF as the
  vertex count of the particle geometry. Runtime cannot grow it.

- **NI2-Q43 [inferred from source]** **Each `NiParticleSystemController`
  is self-contained** — no global old-particle manager exists. Every
  particle system is independently driven by its own controller. The
  only thing that's shared is the global stream-loader registry.

## I. NiParticleSystemController

- **NI2-Q44 [inferred from source]** Direct fields on the controller
  beyond base `NiTimeController`:
  - **Velocity defaults:** mean speed + variance; mean declination +
    variance; mean planar angle + variance. (Speed in units/sec;
    declination and planar angle in radians.)
  - **Initial visual state:** normal direction (`NiPoint3`), color
    (`NiColorA`), size scalar.
  - **Emit gating:** emit-start time, emit-stop time, reset flag.
  - **Birth/death:** birth rate (used if `useBirthRate=true`), lifespan
    mean + variance, two booleans (`useBirthRate`, `spawnOnDeath`).
  - **Emitter volume:** width, height, depth (a box in the emitter's
    local space — emitters are always boxes in the old system, see
    NI2-Q58).
  - **Emitter reference:** raw pointer to an `NiAVObject` whose
    transform defines emitter location/orientation in world.
  - **Spawn-cascade params:** generation cap (`u16`), spawn percentage
    (chance per death), spawn multiplier (count per spawn event),
    speed chaos (random speed perturbation), direction chaos (random
    dir cone).
  - **State:** total capacity, active count, current iteration cursor,
    pointer to the per-particle state array.
  - **Modifier chain heads:** smart pointers to the first emitter
    modifier, particle modifier, and particle collider.
  - **Bounding:** static bound flag + cached static model bound.
  - **Bookkeeping:** scaled last-time, last-emit time, first-time
    flag.

- **NI2-Q45 [inferred from source]** Birth rate is **on the
  controller**, controlled by the `useBirthRate` boolean:
  - If `true`: use the explicit `m_fBirthRate` field (particles per
    second).
  - If `false`: compute implicitly as
    `capacity / (emitStop - emitStart)` if lifespan ≥ animation cycle
    length, or `capacity / lifespan` otherwise.

  Per-particle initial parameters (speed range, direction cone, color,
  size, lifespan) are all on the controller too. The emitter modifiers
  themselves (the chain) are *augmentations* of the basic box-shaped
  emitter — they can apply additional per-frame updates to emitter
  state but don't override the basic spawn parameters.

- **NI2-Q46 [inferred from source]** Lifespan is **on the controller
  as mean + variance**. Each particle's individual lifespan is
  `m_fLifeSpan + m_fLifeSpanVar · (uniformRandom - 0.5)` — uniform
  random in [-0.5, 0.5] scaled by variance. So variance is "total
  spread" not "stddev".

- **NI2-Q47 [inferred from source]** Initial velocity is computed at
  spawn time as:
  - Speed: `m_fSpeed + m_fSpeedVar · (uniformRandom - 0.5)`.
  - Direction: spherical coordinates from `(declination ± declVar,
    planarAngle ± planarVar)`, both ranges symmetric (using a
    [-1, +1] symmetric random).
  - Result: `velocity = speed · sphericalToCartesian(dec, planar)`.
  - Direction is in **target-local space** by default; if an emitter
    object is set, direction is rotated through the emitter→target
    transform.

  All these parameters live on the controller. No per-emitter-shape
  variation — see Q58 for why.

- **NI2-Q48 [inferred from source]** Initial color is a single
  `NiColorA` field on the controller (no per-channel variance).
  Initial size is a single float field. Per-particle color and size
  are then mutated over lifetime by the color and grow/fade modifiers
  (Q64, Q65). No random distribution on initial color/size.

- **NI2-Q49 [inferred from source]** Random numbers come from
  **global engine helpers** (`NiUnitRandom`, `NiSymmetricRandom`).
  The controller carries no seed and does not look deterministic.
  This means BC's particle systems are **not reproducible frame-to-
  frame** across sessions — a save/load with active particles will
  diverge in the random rolls used to spawn future particles. For a
  modern reimplementation, this is something to fix.

  Cap: random behavior is **[runtime-architectural]** — the code
  assumes a global RNG; a clean-room reimpl can make it per-system.

## J. NiAutoNormalParticles and NiRotatingParticles

- **NI2-Q50 [inferred from source]** Both classes are not present
  by name in this SDK's main library — the modern `NiParticles` /
  `NiParticleMeshes` / `NiParticleMeshesData` / `NiParticlesData`
  classes have absorbed the older renderable particle types. Looking
  at how they're constructed:
  - `NiParticles` is the general "billboard-rendered set of points"
    class. The default rendering is camera-aligned billboards using
    the per-particle size from `NiParticlesData`.
  - `NiParticleMeshes` (derives from `NiParticles`) carries an array
    of mesh references in its `NiParticleMeshesData`; each active
    particle is rendered as one of those meshes (which one is chosen
    by particle index modulo mesh count, or per-particle assignment).

  When a NIF contains `"NiAutoNormalParticles"` or
  `"NiRotatingParticles"` blocks, they would be loaded as the modern
  equivalents (via the same RTTI-aliasing mechanism described in
  section A). What distinguished them in the original NetImmerse era:
  - **`NiAutoNormalParticles`**: each particle's normal is
    automatically recomputed each frame to face the camera (used for
    lit billboard particles — sparks, glow points).
  - **`NiRotatingParticles`**: each particle has its own rotation
    state (axis + angle, evolved by a `NiParticleRotation` modifier)
    — used for spinning sparks, flame puffs.

  BC content would use `NiAutoNormalParticles` for non-rotating
  emissive effects and `NiRotatingParticles` for spinning sparks.

- **NI2-Q51 [inferred from source]** They derive from `NiParticles`
  which derives from `NiTriBasedGeom` (i.e., they ARE triangle-based
  geometry, just rendered differently). The renderer's choice of
  "draw as billboard quad per vertex" vs "draw as triangle list"
  depends on the data class type, not the geometry class. The
  override is in the rendering pipeline's geometry-group selection —
  particles go through a particle-specific draw path.

- **NI2-Q52 [inferred from source]** For non-mesh particles, billboard
  orientation is implicit in the renderer: each particle position is
  treated as the center of a screen-aligned quad sized by the
  particle's `radius` (from `NiParticlesData`'s radii array). The
  quad's corners are generated in view-space such that the quad is
  always camera-facing. The per-particle normal (if present) is
  recomputed to point at the camera (in `NiAutoNormalParticles`
  semantics) — the rendering effectively does
  `normal = normalize(cameraPos - particlePos)` for lit billboards.

  This happens in the renderer, not in the controller. The controller
  only ensures positions and (for lit billboards) normals are up to
  date.

- **NI2-Q53 [inferred from source]** Per-particle rotation: the
  rotation axis lives in `NiPerParticleData::m_kRotationAxis` (one
  `NiPoint3` per particle, in target space). The rotation **angle**
  is not stored per-particle in the controller's state — it's
  recomputed from age and the `NiParticleRotation` modifier's
  `m_fRotationSpeed` field at update time. So:
  - Per-particle: axis (vector).
  - Shared (on the modifier): scalar rotation speed (radians/sec).
  - Computed at frame time: angle = age · speed.

  The result is written to `NiParticlesData`'s rotation array
  (`NiQuaternion` per particle) for mesh particles. For non-mesh
  particles the rotation field is dropped at load time (see Q33's
  `REMOVE_UNUSED_ROTATIONS` note).

## K. NiPerParticleData

- **NI2-Q54 [inferred from source]** Per-particle state on the
  controller side (`NiPerParticleData`), exactly:
  - **`m_kVelocity`** — `NiPoint3`. Linear velocity vector.
  - **`m_kRotationAxis`** — `NiPoint3`. Rotation axis (used only by
    `NiParticleRotation` for mesh particles).
  - **`m_fAge`** — float. Time since spawn.
  - **`m_fLifeSpan`** — float. Death threshold.
  - **`m_fLastUpdate`** — float. Scaled time of the previous update;
    used to compute delta-time for velocity-dependent forces.
  - **`m_usGeneration`** — `u16`. How many spawn cascades deep this
    particle is.
  - **`m_usIndex`** — `u16`. Which slot in the parallel
    `NiParticlesData` arrays this particle owns.

  Fields **not** stored here (because they live in `NiParticlesData`):
  position, color, normal, radius, size, rotation quaternion.

- **NI2-Q55 [inferred from source]** Position (in `NiParticlesData`)
  is in the **target `NiParticles` object's model-local space** —
  i.e., the same space that the target's `NiAVObject` transform would
  bring into world. Velocity (in `NiPerParticleData`) is in the same
  space. When an explicit emitter object is set, the spawn-time
  transformations rotate from the emitter's space into the target's
  space, then integration proceeds in target-space throughout the
  particle's life. So a particle remains spatially attached to the
  emitter through the target's transform — moving the target node
  moves all its particles.

- **NI2-Q56 [inferred from source]** Alive vs dead is **implicit via
  the active count**: `m_usNumActiveParticles` names how many slots
  at the front of the per-particle array are alive; everything from
  that index up to capacity is stale. There is no explicit alive flag
  and no sentinel age. On death, the dying particle's slot is
  overwritten with the last active particle's data, and the active
  count decrements. The vertex-data slot index follows: the killed
  particle's `NiParticlesData` vertex slot is reused for the swapped-
  in particle's data.

## L. Modifiers — field-by-field

- **NI2-Q57 [inferred from source]** `NiParticleModifier` (base):
  - **Fields:** smart pointer to the next modifier (`m_spNext`), raw
    pointer to the owning controller (`m_pkTarget`).
  - **Virtual contract:**
    - `Update(time, particle)` returns bool: true → particle stays
      alive, false → particle was killed by this modifier. Default
      implementation forwards to the next modifier in the chain.
    - `Initialize(particle)` runs once when a new particle is spawned;
      default forwards to next.
  - **Attachment:** `SetTarget` is the public API; internally it
    calls `AddToTarget` which prepends to the controller's
    `m_spParticleModifiers` chain. So modifier *attach order* differs
    from *chain order* — last attached runs first.
  - **Subclass contract:** override `Update` to do per-frame
    per-particle mutation; chain to base afterward to forward.
    Override `Initialize` for spawn-time setup.

- **NI2-Q58 [inferred from source]** `NiEmitterModifier` (base):
  - **NOT a shape source.** The basic emitter shape is **fixed as a
    box** in the controller (using the width/height/depth fields plus
    the optional `m_pkEmitter` reference). `NiEmitterModifier` is a
    *modifier on the emitter's state over time* — its `Update` method
    is called once per frame, not once per particle. Subclasses would
    animate the emitter's parameters (changing emit rate over time,
    changing emitter dimensions, etc.).
  - The old SDK appears to ship **zero concrete `NiEmitterModifier`
    subclasses**. The chain head is always null or carries
    application-supplied subclasses. BC almost certainly uses
    custom emitter modifiers for its specific effects (engine washes
    that pulse, weapon-impact bursts with timed shape changes, etc.).
  - **Initial particle state setup**: handled entirely by the
    controller in `AddNewParticle`, not delegated to the emitter
    modifier chain.
  - **Birth rate**: on the controller, not on emitter modifiers.
  - **Spawn budget**: on the controller (via emit-start, emit-stop,
    birth rate).
  - **Burst mode**: not a stock concept. Achievable by attaching an
    emitter modifier that adjusts the controller's birth rate over
    a short interval.

  Cap: emitter is hardcoded as box-shaped. **[structural]** — to
  use a sphere/mesh emitter in old-particle BC content, the asset
  pipeline would have had to invent a custom emitter modifier that
  reshapes particles after spawn (or BC ran custom logic on top).

- **NI2-Q59 [inferred from source]** `NiGravity`:
  - **Mode enum:** `FORCE_PLANAR` (uniform directional force,
    optionally distance-attenuated through a plane), `FORCE_SPHERICAL`
    (radial force from/towards a point).
  - **Fields:** decay scalar (exponential decay rate; 0 = no decay),
    strength scalar (units/sec² magnitude — described as "specified in
    units/seconds²"), mode enum, position vector, direction vector.
  - **Planar update**: `velocity += direction · exp(-decay · projDist)
    · strength · 1.6 · deltaT`, where `projDist` is the particle's
    distance from the position projected along the direction. If
    `decay` is 0, no exponential applied.
  - **Spherical update**: `velocity += (position - particlePos)norm
    · exp(-decay · dist) · strength · 1.6 · deltaT`. Always pulls
    toward the position (negative strength for push).
  - **The 1.6 factor** is a magic units-conversion constant.
  - **Mutates:** per-particle velocity (additive). Does not affect
    controller state.

- **NI2-Q60 [inferred from source]** `NiParticleBomb`:
  - **Trigger:** time-window. `m_fStart` names the bomb start time;
    `m_fDuration` names how long it remains active.
  - **DecayType enum:** `NONE`, `LINEAR`, `EXPONENTIAL` — selects the
    falloff curve of bomb intensity with distance.
  - **SymmType enum:** `SPHERICAL`, `CYLINDRICAL`, `PLANAR` — selects
    the falloff geometry.
  - **Fields:** decay scalar, delta-V magnitude (the "kick" applied
    to a particle right at the bomb), duration, start time, decay
    type, symmetry type, position, direction.
  - **Mutates:** per-particle velocity (additive impulse).
  - **Note:** the conversion to the modern system encodes the
    active-time window as a boolean step-key sequence on a
    `NiPSysModifierActiveCtlr`, mirroring start + duration as
    `(true at start, false at start+duration)` keys.

- **NI2-Q61 [inferred from source]** `NiParticleCollider` (base):
  - **Fields:** bounce scalar (restitution), spawn-on-collide bool,
    die-on-collide bool, cached collision point, cached collision time.
  - **Virtual contract:**
    - `Resolve(initialTime, &collisionTime, particle)`: scans the
      collider's geometry to find when (if ever) the particle's
      current trajectory intersects within the time interval. Returns
      a pointer to itself if a collision occurs; null otherwise.
      Updates the `collisionTime` ref.
    - `Update(time, particle)`: applies the collision response —
      reflects velocity with bounce, optionally spawns a cascade,
      optionally kills the particle (returns false).
  - **Friction model**: there is no separate friction parameter; the
    bounce scalar is the only response coefficient. Velocity along
    the surface is preserved, velocity into the surface is reflected
    and scaled by `bounce`.
  - **Chain semantics:** colliders live on their own chain
    (`m_spParticleColliders`), separate from non-collision modifiers.
    Only the **first** collider returning a hit is acted on per frame
    per particle (the controller comments "Potential for multiple
    collisions?" suggesting this is a known limitation).

- **NI2-Q62 [inferred from source]** `NiPlanarCollider`:
  - **Plane representation:** a `NiPlane` (normal + signed distance)
    plus a position, an X-axis vector, and a Y-axis vector — together
    defining a finite **rectangular patch** on the infinite plane.
  - **Bounds:** width and height scalars name the rectangle's extents
    along the X- and Y-axes from the position.
  - **One-sided:** the collider responds to particles approaching
    from the positive-normal side; particles passing from behind
    are not stopped.
  - **Response params:** inherited from base (bounce, spawn-on-collide,
    die-on-collide).

- **NI2-Q63 [inferred from source]** `NiSphericalCollider`:
  - **Sphere:** position + radius (and a cached squared radius for
    fast tests).
  - **Inside-vs-outside:** the implementation appears to treat the
    sphere as a solid boundary — particles outside that try to
    enter get bounced/stopped. (Inside-only mode is not explicitly
    a switch.)
  - **Response params:** inherited.

- **NI2-Q64 [inferred from source]** `NiParticleColorModifier`:
  - **Color-over-lifetime keys:** a smart pointer to a `NiColorData`
    block carrying `NiColorKey` array (any of LIN/BEZ/TCB/STEP key
    types) — the same key-array machinery used by ordinary color
    animation.
  - **Key count:** no fixed limit. **[structural]** — at the array
    level, indices are unsigned int.
  - **Interpolation mode:** whatever the color-key type encodes;
    `GenInterp` is dispatched by type.
  - **Time normalization:** the modifier clamps the particle's age
    to `[m_fLoKeyTime, m_fHiKeyTime]` (the data block's actual
    timestamp range) before interpolating. So if your keys are
    written in [0, 1] for normalized lifetime, they'll work; if in
    seconds matching lifespan, they'll work — but key times are
    **absolute scaled-time-style values**, not auto-mapped to
    [0, 1].
  - **Mutation:** writes the interpolated color into the particle's
    `NiParticlesData` color array slot, with clamping to [0, 1] per
    channel.

- **NI2-Q65 [inferred from source]** `NiParticleGrowFade`:
  - **Fields:** `growFor` (seconds at start of life for the size to
    ramp up from 0 → 1) and `fadeFor` (seconds at end of life for
    size to ramp down from 1 → 0).
  - **Per-particle, per-generation behavior:**
    - Grow ramp applies **only to first-generation particles**
      (those directly spawned by the emitter, not by death-cascade).
    - Fade ramp applies **only to last-generation particles** (where
      generation equals the controller's `m_usNumGenerations`).
    - Mid-generation particles maintain size 1.0.
  - **Final scale:** `min(grow, fade)` — whichever is currently more
    restrictive — clamped to at least `epsilon` to avoid degenerate
    zero-size particles.
  - **No key array** — just two scalars. This is a structural
    simplification vs the modern grow-fade modifier.

- **NI2-Q66 [inferred from source]** `NiParticleMeshModifier`:
  - **Meshes:** an array of smart pointers to `NiAVObject` (typically
    `NiTriShape` or similar).
  - **Per-particle mesh assignment:** each particle is rendered with
    the mesh at index `m_usIndex % meshCount` (i.e., round-robin
    distributed by particle slot index).
  - **Initialization** on spawn: assigns the appropriate mesh to the
    particle's slot in the `NiParticleMeshesData`.
  - **Scale evolution:** uses the standard per-particle size from
    `NiParticlesData` (driven by grow/fade or stayed at 1.0); the
    renderer multiplies the mesh by that scale.
  - **Limit:** mesh count is bounded by `NiTArray` size (32-bit).
    **[structural — generous]**

- **NI2-Q67 [inferred from source]** `NiParticleRotation`:
  - **Per-particle:** rotation axis (in `NiPerParticleData`).
  - **Modifier fields:** random-initial-axis flag, initial axis
    vector (used when random is off), rotation speed (radians/sec).
  - **Initialize behavior:** when a new particle spawns, if the
    modifier's `m_bRandomInitialAxis` is true, the particle's axis
    gets a uniform random unit vector; otherwise it gets the
    modifier's stored initial axis.
  - **Update behavior:** writes a fresh quaternion to the particle's
    `NiParticlesData` rotation slot:
    `rotation = quat(axis = particle.axis, angle = age · speed)`.
  - **Caveat (Q33):** for non-mesh particles, this modifier is
    silently stripped at load time. So BC's billboard particles never
    actually rotate via this modifier — any rotation visible in BC
    billboards must come from animated textures (flip controllers) or
    from BC-custom logic.

- **NI2-Q68 [inferred from source]** I encountered no other
  particle modifiers in the old-particle library beyond those listed.
  The complete set is: `NiGravity`, `NiParticleBomb`,
  `NiParticleCollider` (base) + `NiPlanarCollider` +
  `NiSphericalCollider`, `NiParticleColorModifier`, `NiParticleGrowFade`,
  `NiParticleMeshModifier`, `NiParticleRotation`. Eight concrete
  classes, three abstract bases.

## M. Particle lifecycle

- **NI2-Q69 [inferred from source]** Spawn (`AddNewParticle` path):
  1. Locate the next slot in the per-particle array at
     `m_usNumActiveParticles`.
  2. Assign the slot's vertex-data index to the current active count
     in `NiParticlesData` (the new particle gets the next vertex
     slot), then increment the active count.
  3. **First-generation particle path** (no parent):
     - Random age in `[0, frameDelta]` — newly spawned particles get
       a small head-start so they don't all visibly emerge in
       lockstep.
     - Speed: `m_fSpeed + m_fSpeedVar · (uniform - 0.5)`.
     - Direction: spherical from `(declination ± declVar,
       planarAngle ± planarVar)`.
     - Position: random within box `[-w/2, w/2] × [-h/2, h/2] ×
       [-d/2, d/2]`.
     - If emitter object is set, rotate direction and offset position
       by the emitter→target transform.
     - Lifespan: `m_fLifeSpan + m_fLifeSpanVar · (uniform - 0.5)`.
     - Generation: 0.
     - Rotation axis: `(1, 0, 0)` by default.
     - Vertex/normal/color/radius/size fields in `NiParticlesData`
       initialized to controller defaults.
  4. **Death-cascade spawn path** (parent particle):
     - Age computed from spawn time delta (not random).
     - Speed perturbed by `m_fSpeedChaos` factor from parent speed.
     - Direction perturbed by `m_fDirChaos` cone from parent direction.
     - Lifespan: same formula as primary spawn.
     - Generation: parent + 1.
     - Rotation axis: copied from parent.
     - Vertex/normal/color/radius/size: copied from parent's slot.
  5. `m_fLastUpdate` set to `currentTime - age` (so first integration
     covers the random head-start interval).
  6. Walk the particle-modifier chain's `Initialize` on the new
     particle — gives modifiers a chance to set per-particle state
     (e.g., random rotation axis).

- **NI2-Q70 [inferred from source]** Update one frame for one
  particle (`ParticleUpdate`):
  1. Advance age by `frameEnd - lastTimeStep`.
  2. If `age > lifespan`: optionally spawn cascade, then remove
     particle (`RemoveParticle`), return.
  3. Walk the **particle-modifier chain**: each modifier runs its
     `Update` (color, grow-fade, gravity, bomb, rotation), each
     mutating its piece of state.
  4. Walk the **collider chain** via `Resolve` to find the earliest
     collision in this frame. If hit, run the collider's `Update` to
     reflect velocity; if the collider returns false (die-on-collide),
     bail out.
  5. **Integrate position**: `pos[m_usIndex] += velocity · (frameEnd
     - collisionTime)` (so if no collision, `collisionTime ==
     frameStart` and the full step is integrated; if collision,
     only the post-collision sub-step is integrated — pre-collision
     motion was already done in `Resolve`).
  6. Update `m_fLastUpdate`.

- **NI2-Q71 [inferred from source]** Death triggers:
  - **Age threshold:** `age > lifespan` at the start of update.
  - **Collision:** any collider whose `Update` returns false
    (typically a planar/spherical with `die-on-collide` set).
  - **System reset:** time wrapped backward and the reset flag was
    set — clears the entire active set.

  On death:
  - **Slot reuse is immediate.** The dying particle's slot is
    overwritten with the last active particle's state (a swap-and-pop).
  - The dying particle's `NiParticlesData` vertex slot is freed via
    `pkParticlesData->RemoveParticle(m_usIndex)`.
  - The iteration cursor (`m_usCurrentParticle`) is decremented so
    the swapped-in particle gets visited this frame.
  - No deferred death list. No two-phase mark-then-sweep.

- **NI2-Q72 [inferred from source]** Slot state is **overwritten,
  not zeroed**, on reuse. Both the per-particle controller state
  and the `NiParticlesData` vertex/normal/color slots are written
  with new values before they're used. No memset.

## N. Particle rendering

- **NI2-Q73 [inferred from source]** The renderer iterates **`NiParticlesData`'s
  vertex array directly** through `GetActiveVertexCount()` — it does
  not touch the controller's per-particle state. This is what allows
  particles to render as if they were normal triangle geometry: the
  vertex data is "live" and renormalized per frame by the controller's
  mutation.

- **NI2-Q74 [inferred from source]** Billboard quad construction
  happens **on the GPU side** (or in the renderer's vertex pre-pass)
  — the controller writes one position per particle, and the renderer
  expands that into a screen-aligned quad using the size/radius and a
  view-space basis. There's no CPU-side quad generation in the
  controller path. This is why marking the vertex/normal/color arrays
  as changed each frame is sufficient — the renderer regenerates the
  per-quad vertices.

- **NI2-Q75 [inferred from source]** No documented sort within a
  particle set. Particles render in slot order (insertion-order, with
  the swap-on-death scrambling). If the particle set's enclosing
  `NiAVObject` has alpha blending on, the whole set is back-to-front-
  sorted **by its bounding-sphere center** against other alpha objects
  in the scene (as documented in round 1 for the alpha accumulator) —
  but per-particle sorting is not done. This is why dense alpha
  particle systems can have visible draw-order artifacts inside the
  cloud.

- **NI2-Q76 [inferred from source]** Particle nodes are normal
  `NiTriBasedGeom` descendants and carry the full property stack —
  `NiAlphaProperty`, `NiTexturingProperty`, `NiMaterialProperty`,
  `NiZBufferProperty` etc. The renderer honors them identically to
  ordinary geometry. Typical BC particle configuration is alpha-blend
  on with `ALPHA_SRCALPHA`/`ALPHA_ONE` (additive) for emissive effects,
  Z-test on with Z-write off.

- **NI2-Q77 [inferred from source]** Mesh particles render with one
  draw call per particle — there's no instancing in the
  fixed-function pipeline of the era. The renderer iterates particles
  and for each emits a draw call against the mesh assigned to that
  particle's index, transformed by the particle's position and
  (optional) rotation. This is expensive for dense mesh-particle
  systems and was one of the reasons the modern particle system was
  introduced.

## O. Limit categorization

- **NI2-Q78 [structural]** **Maximum particles per system** =
  vertex count of the underlying `NiParticles` geometry block.
  Stored as a `u16` (so the absolute upper bound is 65,535), but
  more importantly the count is fixed at NIF-author time and cannot
  grow at runtime. To exceed it, the modern reimplementation must
  either re-author the geometry with a larger vertex slot pool or
  introduce a dynamic-growth path that didn't exist in the original.

- **NI2-Q79 [structural — generous]** **Maximum color/size keys per
  modifier:** unsigned int. No practical limit. The structural
  constraint is the `NiAnimationKey` indexing API which uses 32-bit
  indices; the on-disk format uses `u32` counts.

- **NI2-Q80 [hardware-era]** **Maximum simultaneous lights per
  object** = 8 (the DirectX 8 / fixed-function T&L pipeline limit).
  Enforced in the **renderer**, not in `AttachEffect`. The scene
  graph accepts unlimited light attachments; the renderer silently
  drops lights beyond the cap with no documented selection
  algorithm (no distance, no influence, no priority). A modern
  GPU-based reimplementation can lift this trivially.

- **NI2-Q81 [hardware-era]** **Maximum bones per skin partition** =
  4 by default (DX8/Xbox fixed-function matrix-palette skinning
  limit). Enforced in `NiSkinPartition`'s build-time
  `bonesPerPartition` parameter and reflected in the renderer's
  vertex shader binding. Configurable up to ~20+ with a custom
  palette-skinning vertex shader. **[hardware-era]** for the default
  4; **[runtime-architectural]** for the partitioning scheme itself
  (NiSkinPartition is required for hardware skinning regardless of
  bone count).

- **NI2-Q82 [hardware-era]** **Maximum UV sets per vertex** = 8
  (DX8 renderer limit per the renderer's documented limitation).
  The on-disk format itself stores a `u16` count, so the structural
  limit is 65535. Renderer enforces the lower bound.

- **NI2-Q83 [hardware-era]** **Maximum multitexture stages per pass**
  = whatever the GPU reports. Renderer adapts at startup; combinations
  exceeding the pass cap split into multiple passes via alpha blend.
  The format does not encode a per-object pass count.

- **NI2-Q84 [inferred from source]** Additional caps observed in
  the legacy code while reading:
  - **`NiParticleSystemController::m_usNumGenerations`** is `u16` —
    spawn cascade depth. **[structural]** but `u16` is generous.
  - **`NiParticleSystemController::m_usMultiplier`** is `u16` — kids
    per spawn event. **[structural]**.
  - **`NiFlipController` shader-map index** capped at
    `1024 + N_shader_maps`. **[runtime-architectural]** — the magic
    1024 offset encodes the standard-vs-shader-map split. Don't try
    to flip more than 1024 standard maps on a single texturing
    property; very unlikely but worth knowing.
  - **`NiSequence`** initial array size and growBy are both 12.
    **[runtime — soft]**: array grows on add, just less memory
    efficient if BC has many sub-controllers per sequence.
  - **`NiTimeController` flag word** is `u16` (the engine
    occasionally widens to `u32` via shifts at load); BC's controllers
    won't use bits beyond bit 5. **[runtime-architectural]**.
  - **Animation key type enum** fits in one byte (5 LIN/BEZ/TCB/STEP/
    EULER values plus NOINTERP). **[structural]**.

## P. BC custom blocks hints

- **NI2-Q85 [not found]** No BC-flavored or Trek-flavored class
  names appear in either the converter source or the old-particle
  directory. Every class name is stock `Ni*`. BC's custom blocks
  must be registered exclusively at BC's runtime startup, not
  referenced anywhere in the SDK source.

- **NI2-Q86 [not found]** No fallback paths keyed on class-name
  patterns. The converter's class checks are all exact `NiIsKindOf`
  matches against stock types. There is no "if name starts with X"
  logic anywhere in either source tree.

## Q. Cross-cutting clarifications from round 1

- **NI2-Q87 [important — round 1 oversimplification]**

  Reading `NiOldAnimationConverter` revealed that **round 1's
  description of legacy animation conversion was misleading**.
  Specifically:

  1. **Round 1 implied there was a single converter file that
     described all legacy animation.** There isn't. There are three
     conversion mechanisms running at different points in the load
     pipeline, and the post-process function (`NiOldAnimationConverter`)
     handles only three controller types — `NiLookAtController`,
     `NiRollController`, and `NiPathController`. The bulk of legacy
     animation conversion happens silently inside each modern class's
     `LoadBinary` / `LinkObject`, gated on file version 10.1.0.104.

  2. **Round 1 said BC uses `NiKeyframeController` heavily.** This
     is true *as written in BC's NIFs*, but **at runtime, after
     load, no `NiKeyframeController` objects exist** — they have all
     become `NiTransformController` objects with `NiTransformInterpolator`s
     wrapping their legacy `NiTransformData` (formerly `NiKeyframeData`)
     blocks. The class name in the NIF's RTTI table is
     `"NiKeyframeController"`, but the constructor invoked is
     `NiTransformController::CreateObject`. So when reverse-engineering
     BC's runtime, you'll see modern class types in the object graph
     — the legacy names only appear in the on-disk file.

  3. **Round 1 said `NiKeyframeData` carries combined channels and
     I described it as "the classic single-controller-per-node
     design."** The data block itself is single-block, but the three
     channels (rotation, position, scale) are fully independent on
     disk and at runtime. They can have different key types, different
     counts, and any can be empty. This is more flexible than my
     round-1 description suggested.

  4. **Round 1 said the post-process function handles "every
     legacy controller."** It doesn't. It handles three. The other
     legacy controllers are handled at the class level, transparently.

  5. **Round 1 said the converter is the single most informative
     file for BC-era animation.** This is only partly true. The
     post-process function is small and only covers three controllers.
     The *system descriptor module* (the file that registers RTTI
     aliases and post-process hooks) is more informative for
     understanding the conversion architecture as a whole. And the
     individual controller class `.cpp` files — particularly
     `NiTransformController.cpp`, `NiVisController.cpp`, and
     `NiUVController.cpp` — encode the actual legacy field layouts.

  None of this changes the high-level architectural picture; it
  refines the implementation strategy. For a clean-room
  reimplementation, the practical guidance is:

  - Implement the modern data classes only (`NiTransformData`,
    `NiBoolData`, etc.).
  - In your loader, register class-name aliases (`"NiKeyframeController"`
    → your `NiTransformController` factory, `"NiKeyframeData"` → your
    `NiTransformData` factory, `"NiVisData"` → your `NiBoolData`
    factory).
  - In each modern class's body reader, version-gate on file ≥
    10.1.0.104 to decide whether to read the modern or legacy field
    layout.
  - Implement the small post-process function for the three
    controllers that need topology fixup.
  - Don't implement `NiKeyframeController` or `NiKeyframeData` as
    distinct classes — they don't exist as classes in the modern
    SDK either.

- **NI2-Q88 [verified]** The converter matches **zero literal
  text-key strings**. Round 1's claim that the converter looked for
  `"start"` and `"end"` was incorrect — those were a community
  convention I attributed to the SDK. The actual code does not
  inspect `NiTextKeyExtraData` strings at all. Tag strings are
  100% application-defined.

  The corrected list of literal strings the converter does match is:
  none.

- **NI2-Q89 [inferred from source]** The converter code reveals
  one transition detail not documented in the doc tree: at NIF
  version exactly 10.0.1.1 (and *only* that single point version),
  the `play-backwards` bit on `NiTimeController` was encoded as a
  separate boolean after the standard fields, rather than as a flag
  bit. This is a single-point-version quirk — files at exactly
  10.0.1.1 need a special read path, files below need a flag-bit
  shift, files above pack the bit into flags normally. This kind of
  thing is exactly what a NIF-version field-by-field test suite
  would catch, and exactly what's missing from the docs.

  Also revealed: the 10.0.1.16 transition where
  `IsVertexController()` controllers (`NiUVController`,
  `NiGeomMorpherController`) started marking their target geometry
  as `VOLATILE` for renderer-side dynamic-VB management — a
  performance hint that older files didn't carry.

  Other than these two, nothing about BC-era versions (3.x → 4.x)
  is revealed by the code that isn't in NifSkope's tables.

---

## Limit-tag summary table

One-page lookup of every cap mentioned. Columns: limit, value,
where enforced, category.

| Limit | Value | Where enforced | Category |
| --- | --- | --- | --- |
| Particles per system | `u16` count, capped at geometry vertex count | `NiParticles::GetVertexCount()` at SetTarget time | **structural** |
| Spawn-cascade generations | `u16` | `m_usNumGenerations` field | **structural** |
| Kids per spawn event | `u16` | `m_usMultiplier` field | **structural** |
| Particle modifier list | unbounded | linked list | runtime |
| Particle collider list | unbounded | linked list | runtime |
| Emitter shape | box only | `NiParticleSystemController` direct fields | **structural** (would need new emitter modifier subclass to do otherwise) |
| Per-particle attributes stored | 7 (vel, rotAxis, age, lifespan, lastUpdate, generation, slotIdx) | `NiPerParticleData` layout | **structural** |
| Color keys per color modifier | `u32` | `NiColorData::m_uiNumKeys` | **structural — generous** |
| Animation key type | one of 5 (LIN/BEZ/TCB/STEP/EULER) | enum | **structural** |
| Euler key count per channel | exactly 1 | runtime assertion in `NiTransformData` | **runtime-architectural** |
| Animation channels per `NiTransformData` | 3 (rotation, position, scale) | direct fields | **structural** |
| Lights per object | 8 simultaneous | renderer | **hardware-era** |
| Bones per skin partition | 4 default, ≤20 with custom shader | `NiSkinPartition` builder + renderer | **hardware-era** |
| UV sets per vertex | 8 | renderer | **hardware-era** |
| Texture stages per pass | GPU-reported | renderer | **hardware-era** |
| `NiFlipController` shader-map magic offset | 1024 | direct constant | **runtime-architectural** |
| `NiTimeController` flag bits used | 6 (animType, cycleType×2, active, direction, manager-controlled) | bit masks | **runtime-architectural** |
| Sequence initial array growth | 12 entries | `NiSequence` constructor | runtime — soft |
| Static-bound sampling rate | 0.10 s | hardcoded | runtime — soft |
| Particle run-up rate | 30 fps (`0.0333...`) | hardcoded | runtime — soft |
| Gravity unit conversion factor | 1.6 | hardcoded | runtime — magic |
| Bound over-size factor | 1.05 | hardcoded | runtime — soft |
| Tiling-zero assertion | epsilon | `NiUVController::OnPreDisplay` | runtime — debug only |

## Not-found list

Items where I have nothing useful to add or where the source did
not answer:

- **NI2-Q4** — converter behavior on unknown classes: no error or
  warning, just pass-through. (This *is* the answer, but it's a
  negative finding.)
- **NI2-Q28** — list of "other" legacy controllers was complete from
  enumeration; nothing additional was hidden.
- **NI2-Q36 / NI2-Q37 / NI2-Q38** — text-key tag interpretation:
  none in this SDK. Application-defined.
- **NI2-Q85 / NI2-Q86** — BC-specific hints: none in either
  source tree.
- **NI2-Q49** — RNG seed: not present; uses global RNG, undocumented
  determinism.

These are all "negative answers" — useful information about what
the SDK does *not* contain, but null results for purposes of porting
non-stock content.
