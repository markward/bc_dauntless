# Bridge Officer Placement, Pose & Appearance (SP3) — Design

> Sub-project 3 of the character-rendering epic, sequenced **before** SP2
> (skeletal animation playback). Goal: render each bridge officer as a
> correctly **posed**, **placed**, and **per-character-appearance** skinned
> figure standing/seated at their station on both playable bridges — static
> (one rest-frame pose, no motion). SP2 then adds animation over time.

## Why SP3 before SP2

Debugging animation while characters float in the wrong place at the wrong
scale fights two unknowns at once. SP3 produces a correct, motionless target —
posed, placed, scaled, grounded — so SP2's motion work is an isolated problem.

The "placement = position, SP2 = pose" split does **not** survive the data:
the placement NIFs (`db_stand_t_l.nif` etc.) are **full skeletal clips** (≈24
bone tracks), so placement and pose are inseparable. SP3 therefore evaluates the
placement clip's **rest frame** to get both the station position and the settled
pose. This pulls SP2's *core* (clip → bone palette) forward as a **static**
evaluation; SP2 keeps only animation-over-time.

## Builds on SP1

SP1 shipped the skinned-mesh pipeline and a bridge skinned sub-pass that renders
`Pass::Bridge` skinned instances lit by bridge ambient, from a per-instance bone
palette. SP3 supplies *posed* palettes (instead of bind pose) and assembled
per-character models, and reuses the SP1 render path unchanged.

## Architecture decision — engine-native resolver (Approach A)

Resolve location → placement pose in **engine code**, not by running the SDK's
`CommonAnimations.SetPosition` playback. Transcribe the small, stable
location→NIF table from `SetPosition`, load the NIF via the existing asset path,
and evaluate its clip with a new static pose-sampler. No new
sequence/action/playback shim surface (that's playback semantics → SP2). The
sampler is built **general and interpolating** (LERP translation, SLERP
rotation) and merely *called* at the rest frame, so SP2 reuses it verbatim for
playback. Estimated ≈90% of SP3's machinery is reused by SP2; only the ~30-line
location→NIF map is potentially superseded if SP2 later routes placement through
the authentic SDK path (Approach B) — and even then the SDK path drives this same
evaluator.

Appearance is captured the same engine-native way SP1's crew speech/menus capture
SDK output: the real SDK config (`CreateCharacter`/`ReplaceBodyAndHead`/
`ModelManager.LoadModel`) runs during crew population, and shim methods **record**
the per-officer asset paths it produces. The host then loads + assembles +
renders natively.

## Data flow

```
populated officer (GetLocation() + appearance from SDK config)
  ├─ APPEARANCE:
  │   SDK CreateCharacter/ReplaceBodyAndHead/ModelManager.LoadModel run →
  │     shim captures (bodyNIF, headNIF, bodyTex, headTex) per officer
  │   → load body NIF (skinned, Bip01) + head NIF
  │   → graft head meshes into the body model, rigid-bound to "Bip01 Head" bone
  │   → apply bodyTex to body meshes, headTex to head meshes
  │   → one composite skinned bridge instance per officer
  └─ PLACEMENT + POSE:
      location → placement-NIF (SetPosition map, honor SetHidden) → load clip
      → sample_pose(clip, t = clip duration)  → local_pose[]
      → build_bone_palette(skeleton, local_pose) → per-instance palette
      → set instance world transform (bridge space) + per-instance palette
  → SP1 bridge skinned sub-pass renders the posed, placed, textured officer
```

## Components

### 1. Static pose sampler (new, native)

`sample_pose(const assets::AnimationClip& clip, const assets::Skeleton& skel,
float t) → std::vector<glm::mat4> local_pose` (indexed by skeleton bone):

- For each `NodeTrack`, find its time interval around `t` and interpolate:
  translation **LERP**, rotation **SLERP**, scale **LERP** (default 1). Compose a
  local TRS matrix.
- Match each track to a skeleton bone by `target_node_name` == bone `name`.
- Bones with no track keep their bind `local_transform`.
- Clamp `t` to `[0, duration]`; a single-key track yields that key at all `t`.

Built general (arbitrary `t`, interpolating) so SP2 reuses it for playback. SP3
calls it once at `t = clip.duration_seconds` (the settled station pose). The
result feeds the **existing** `build_bone_palette(skeleton, &local_pose)` (its
`local_pose` override already exists from SP1).

### 2. Rigid-shape → parent-bone rebind (`model_build.cc`)

Replace SP1's bone-0 fallback for skin-controller-less shapes. Bind every vertex
of such a shape to **its parent node's skeleton bone** (resolve the shape's
parent node → the skeleton bone with that node's name/block). The grafted head
meshes use the same path (parent = `Bip01 Head`). At bind pose the result is
identical to SP1 (palette is identity per bone), so no regression; under a pose
the rigid part follows the correct bone instead of the root. If a shape's parent
node maps to no skeleton bone, fall back to bone 0 (prior behavior) and warn.

### 3. Per-instance pose (scenegraph `Instance` + bridge sub-pass)

Store an optional per-instance bone palette on the `Instance` (a
`std::vector<glm::mat4>`, empty = use bind pose). The SP1 bridge skinned sub-pass
uploads the instance's palette if present, else falls back to
`build_bone_palette(skeleton, nullptr)` as today. A host binding sets an
instance's palette. SP2-foundational: SP2 rewrites this palette per frame.

### 4. Location → placement-NIF map (new native data)

Transcribe the `CommonAnimations.SetPosition` table: `GetLocation()` string →
`{ nif_path, hidden }`. Covers DBridge (`DBHelm`→`db_stand_h_m`, `DBTactical`→
`db_stand_t_l`, `DBCommander`→`db_stand_c_m`, `DBScience`→`db_StoL1_S`,
`DBEngineer`→`db_EtoL1_s`, `DBGuest`→`Seated_P`, staging `DBL1*`→hidden) and
EBridge (`EBHelm`→`EB_stand_h_m`, `EBTactical`→`EB_stand_t_l`, `EBCommander`→
`EB_stand_c_m`, `EBScience`→`EB_stand_s_s`, `EBEngineer`→`EB_stand_e_s`, …).
Locations flagged `hidden` (the `SetHidden(1)` staging spots) are not rendered.

### 5. Appearance capture (App shim)

Implement the shim methods the SDK character configs call, to record per officer:
- `ModelManager.LoadModel(path, skeletonRoot)` — note body/head NIF paths.
- `CharacterClass_Create(bodyNIF, headNIF)` — the (body, head) pair.
- `ReplaceBodyAndHead(bodyTex, headTex)` — the texture pair.
- `AddFacialImage(name, tex)` — **captured but unused** in SP3 (lip-sync → SP2).

These run during the existing crew-population path; SP3 stores the captured
appearance keyed by officer so the host can assemble it.

### 6. Character assembly (native)

Build one composite skinned model per officer:
- Load body NIF (skinned, `Bip01`); apply `bodyTex` to its base stage.
- Load head NIF; **graft its meshes into the body model**, rigid-bound (via
  component 2) to the body skeleton's `Bip01 Head` bone, resolved by name; apply
  `headTex` to the head meshes.
- One skinned bridge instance (`create_bridge_instance`) draws body + head with a
  single skeleton + palette, so the head follows the pose automatically.

### 7. Placement wiring (host / Python)

For each populated officer with a non-hidden location: resolve placement NIF →
load clip → `sample_pose` at rest → `build_bone_palette` → set the officer
instance's palette + world transform. Integrate with the crew-population
lifecycle (mission load, bridge swap, cleanup) — reuse that path.

### 8. Coordinate alignment

Officer instances live in the **bridge set's coordinate space and transform
convention**; the placement clip's root track positions/orients each officer
within it. Getting the conventions right (Z-up feet-origin character, the
renderer's X-flip parity with the bridge) is the headline implementation risk —
verified live and tuned by feel, like the SP1 camera/framing work.

## Testing

**CPU gtests:** `sample_pose` interpolation (LERP/SLERP at a mid-time; `t =
duration` == last keyframe; track-less bone → bind `local_transform`; single-key
track); rigid-shape parent-bone rebind (skinless shape → parent node's bone
index, not 0; bind-pose unchanged); location→NIF map (correct NIF + hidden flag);
head graft (head meshes added to body model, bound to `Bip01 Head` bone index).

**Offscreen GL gtests:** a posed officer's silhouette **differs from bind pose**
(proves the pose is applied, mirroring SP1's palette-shift test); the assembled
body+head model renders (mesh/coverage check).

**Live:** officers posed, placed, oriented, grounded, textured, and distinct per
character at every station on DBridge + EBridge. User verification, tuned by feel.

## Risks

- **Coordinate alignment** (Z-up character + clip root + bridge convention +
  X-flip parity) — main risk; verified live.
- **Rest-frame assumption** (`t = duration` = settled pose) holds for stand/
  walk-on clips; revisit per-clip if any ends mid-motion.
- **Head attach fallback**: no clean `Bip01 Head` match → skip head + warn
  (officer still placed/posed) rather than crash.
- **SP1 regression**: the rigid-rebind change must keep bind-pose render
  byte-identical — covered by the existing SP1 GL bind-pose==static test.

## Out of scope (→ SP2 or later)

- Animation over time: idle loops, walk-on **motion**, transitions, blending.
- Facial animation / lip-sync (`AddFacialImage`, SpeakA/E/U), blinks, breathing.
- Authentic SDK `SetPosition` *playback* path (Approach B) — natural SP2 upgrade.
- Non-bridge characters (away teams, NPCs).
