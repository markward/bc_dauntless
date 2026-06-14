# SP2 — GPU Skeletal Animation — Design

> Part of the character-rendering epic: **SP1** (skinned mesh at bind pose) ✅ ·
> **SP3** (officer placement / appearance infrastructure) ✅ except rendering ·
> **SP2** (this doc — make the bone palette actually *pose*, then animate it).

## Goal

Render BC characters deformed by a **correct, time-driven GPU bone palette**, so
bridge officers stand **correctly posed** at their stations *and* play ambient
animation. SP3's static placement becomes the same code path with a clip that
loops or holds. One palette poses both the 30 rigid and 2 skinned shapes of a BC
body uniformly.

## Background — why the SP3 node-walk failed

SP3 tried to pose a static officer by overwriting each body bone-node's
`local_transform` with the placement clip's rest transform and **clearing the
skeleton**, so the model routed to the bridge **static node-walk**. This poses
the **30 rigid** shapes correctly (their verts are node-local → `node_world · v`
is right), but **explodes the 2 skinned shapes** per body (skin controllers
weighting 10 and 22 bones). Those carry **bind-model-space** verts positioned by
a bone palette, not by one node, so `node_world · v_model` double-transforms them
to infinity (the "exploding arm shards"). A headless probe
(`native/tools/probe_officer_pose`) confirmed the composed model's bone *nodes*
posed correctly (L-Hand world Z=23) while the render stayed bind — proving the
problem is **mesh vertex space**, not node pose.

Conclusion: correctly posing a BC body **requires real GPU bone-palette
skinning**, not node posing. That is SP2. See memory
`project-bc-character-rigid-skinning`.

## What already exists (do not rebuild)

- `compute_inverse_bind_poses` (`skeleton_build.cc:120`) sets
  `inverse_bind_pose = inverse(world_bind)` per bone — **correct already**.
- `build_bone_palette(skeleton, local_pose)` (`bone_palette.cc:8`) computes
  `palette[i] = world_of(i, local_pose) · inverse_bind(i)` — pass it posed bone
  locals and it yields a **posed palette**.
- `renderer::sample_pose` / `sample_track_trs` (`pose_sample.cc`) sample a clip
  into bone locals.
- `set_instance_bone_palette(iid, palette)` → `g_world.set_bone_palette`, and
  `Instance::bone_palette` plumbing.
- `load_animation_clips(nif_path)` parses keyframe clips without a model build.
- `skinned.vert` palette-blends `Σ wᵢ · u_bones[boneᵢ] · v`; **unchanged** by SP2.

The earlier palette attempt sheared **because of the two correctness bugs below**
(vertex space + per-node `u_model`), not because the palette machinery was
missing. SP2 fixes those bugs, then drives the existing palette path per frame.

## Architecture

Renderer-owned animation (brainstorm approach **A+**): the C++ renderer holds
per-instance animation state and rebuilds the palette each frame; a Python
binding sets/switches the active clip once. Bridge-officer idle motion is
ambient, not gameplay-scripted, so it belongs in the renderer with a single
frame budget.

### Correctness fix 1a — rigid verts → bind-model space

`build_mesh_cpu` bakes each shape's `av` (T·R·S) into vertices, leaving them in
**node-local** space (`mesh_build.cc:27` comment: "the renderer only sees
node-local geometry and applies the node's world transform"). A palette of
`world_pose · inverse_bind` only poses vertices in **bind-model** space.

Fix: when the model has a skeleton **and the shape has no skin controller**
(the rigid branch in `model_build.cc`, currently lines ~515–545), additionally
transform the shape's vertices (and normals) by `world_bind(parent_node)` — the
product of node `local_transform`s from root to the shape's parent NiNode at bind
— so they land in **bind-model** space. Keep the existing parent-bone binding
(`bone_indices = (parent_bone,0,0,0)`, `bone_weights = (255,0,0,0)`).

- **Skinned** shapes (with a `NiTriShapeSkinController`) are *already* in
  bind-model space and keep their multi-bone weights via `fill_skin_weights` —
  **not** re-baked.
- **No-skeleton** models (every ship and bridge) are untouched: verts stay
  node-local, drawn by the static node-walk. The bake is gated on
  `!model.skeleton.bones.empty()`.

Math check (rigid shape on bone P, vert now in bind-model space `v_m`):
`pos = u_model · palette[P] · v_m = inst.world · world_pose(P) · inverse(world_bind(P)) · v_m`.
`inverse(world_bind(P)) · v_m` = vert in P's bind-local frame; `world_pose(P)`
poses it. Correct. At bind, `world_pose==world_bind` ⇒ `palette[P]=I` ⇒
`pos = inst.world · v_m` (undeformed). Skinned shapes already satisfied this.

### Correctness fix 1b — skinned pass `u_model = inst.world`

Both skinned paths currently set `u_model` from a **per-node walk**
(`bridge_pass.cc` skinned sub-pass lines ~224–237; the main `frame.cc`
`draw_model` skinned path). With bind-model verts + a posed palette that
double-transforms (`inst.world · world_bind(node) · palette · v`).

Fix: for skinned models, draw **every** mesh with `u_model = inst.world`; the
palette does all per-bone placement. The per-node walk is removed from the
skinned paths (it stays for the static, non-skinned node-walk). 1a and 1b are
**coupled** — neither is correct alone; they land together.

### Animation playback (approach A+)

- **Instance animation state** (new): `{ int clip_index, double start_wall_time,
  bool loop, bool sample_at_start }`, stored on `Instance` (or a renderer
  side-table keyed by instance id). `clip_index < 0` ⇒ no animation (use bind /
  an explicitly-set static palette, as today).
- **Clip storage:** `assemble_officer` loads the placement clip via
  `load_animation_clips(placement_nif)` into the **composed model's**
  `animations` vector, and sets the instance's `clip_index = 0`.
- **Per-frame, before the bridge skinned sub-pass** (and the main skinned pass):
  for each animated instance, compute `t`:
  - `loop`: `t = fmod(now − start, duration)`.
  - not `loop`: `t = min(now − start, duration)` (hold last frame).
  - `sample_at_start` movement clips evaluate from the clip START (officer at the
    station at t=0), so `start` is set so `t` begins at 0.

  Then `pose = sample_pose(model.animations[clip_index], t)` → bone locals;
  `inst.bone_palette = build_bone_palette(model.skeleton, &pose)`. Reuses every
  existing helper; the only new code is the per-frame loop + `t` arithmetic.
  **Freeze optimization:** once a non-looping clip has reached its end
  (`t >= duration`), the palette is final — mark the instance "settled" and skip
  its rebuild on subsequent frames until its animation is changed. With
  play-once-hold the default, held officers cost nothing per frame after settling.
- **Binding:** `set_instance_animation(iid, clip_index, loop, sample_at_start)`
  sets the state; Python calls it once at placement. (Future clip-switching —
  combat reactions, sit/stand — reuses it.)

### SP3 placement folds in

`assemble_officer` **drops** the node-walk posing (`apply_pose_to_nodes` +
skeleton-clear). Instead it keeps the skeleton, loads the placement clip into
`model.animations`, and the Python caller calls `set_instance_animation`.

**Default playback is play-once-and-hold (`loop=False`):** the clip runs to its
end and the officer holds the last frame. For **stand** clips this settles into
the standing pose and stays — exactly SP3's "correctly posed static officer",
now via the proper skinning path. For **movement** clips (`db_*toL1_*`,
`sample_at_start=True`) the officer plays the walk-to-station once and holds at
the station. This avoids loop-seam jumps on clips not authored to loop. Seamless
**idle looping** (`loop=True`) is a deliberate later refinement, once dedicated
idle-loop clips are wired — not part of SP2.

Officers render through the skinned pass, correctly posed *and* animated. No more
node-walk for characters. `assemble_officer` keeps its `placement_nif` argument
(it now loads the clip into `model.animations` instead of node-posing); the
`sample_at_start` flag moves to `set_instance_animation`. The orphaned
`sample_placement_pose` binding and `apply_pose_to_nodes` / `load_pose_locals`
node-walk path are **removed** — the palette path supersedes them.

## Data flow

```
assemble_officer(body, head, …, placement_nif):
   composed = compose_officer_model(...)          # body+head, skeleton kept
   composed.animations = load_animation_clips(placement_nif)
   handle = register(composed)                     # skeleton NOT cleared
   return handle
place_one (Python):
   iid = create_bridge_instance(handle)
   set_instance_animation(iid, clip_index=0, loop=…, sample_at_start=…)
   set_world_transform(iid, BRIDGE_IDENTITY)       # station offset is in the clip root

per frame (C++, before skinned sub-pass):
   for inst with clip_index >= 0:
     t = wrap(now - inst.start, dur, inst.loop)
     pose = sample_pose(model.animations[clip_index], t)
     inst.bone_palette = build_bone_palette(model.skeleton, &pose)

skinned sub-pass:
   u_model = inst.world
   draw each mesh: pos = u_model · Σ wᵢ·bone_palette[boneᵢ] · v_bindmodel
```

## Testing

- **CPU (GoogleTest):** clip sampling at `t=0`, `t=dur`, and a looped wrap
  (`fmod`) returns the expected bone locals; `build_bone_palette` from posed
  locals yields `world_pose·inverse_bind` per bone (extend existing
  `pose_sample` / `bone_palette` tests).
- **GPU:** update SP1's `BindPoseMatchesStaticDraw` to the **bind-model** vertex
  space (verts now model-space; static reference draws via `u_model=inst.world`).
  Add a **posed-palette** test: a known single-bone rotation moves a known vertex
  to its analytically-expected world position — asserting **no shear, no
  explosion** (the failure mode this whole effort hit).
- **Headless probe:** extend `probe_officer_pose` to also build the **palette**
  from the placement clip and push a hand vertex through
  `inst.world · palette[bone] · v_bindmodel`; assert it lands at the same world
  position the node-walk computed for the hand node (Z≈23 for `db_stand_t_l`).
  This closes the loop that the node-walk path silently broke.
- **Python:** `bridge_officers` calls `set_instance_animation`; existing focused
  `tests/unit/test_bridge_officers.py` stays green. Do **not** run the full
  pytest suite (OOMs the host — use focused subsets).

## Files touched

| File | Change |
|---|---|
| `native/src/assets/src/mesh_build.cc` / `model_build.cc` | 1a: bake rigid verts to bind-model space (skeleton present, no skin controller) |
| `native/src/renderer/bridge_pass.cc` | 1b: `u_model = inst.world` in skinned sub-pass; per-frame palette rebuild for animated instances |
| `native/src/renderer/frame.cc` | 1b: `u_model = inst.world` in main `draw_model` skinned path; per-frame palette rebuild |
| `native/src/scenegraph/include/scenegraph/instance.h` (+ `world.*`) | instance animation state + accessors |
| `native/src/host/host_bindings.cc` | `set_instance_animation` binding; `assemble_officer` keeps skeleton + loads clip into `model.animations`; remove node-walk posing |
| `engine/bridge_officers.py` | after placing, call `set_instance_animation(iid, 0, loop, sample_at_start)`; `assemble_officer` still receives `placement_nif` (now loads the clip, no longer node-poses) |
| `native/tests/assets/gpu/*`, `native/tests/assets/cpu/*` | bind-model update + posed-palette + sampling tests |
| `native/tools/probe_officer_pose/probe_officer_pose.cc` | add palette-path assertion |

## Non-goals (YAGNI)

- Animation **blending / transitions** between clips.
- Per-character animation **scripting from SDK** (bridge idle is ambient).
- Facial / lip-sync animation; secondary motion (cloth, hair physics).
- Animation for non-bridge (in-space) characters — none exist yet.

## Risks

- **Regressing ships/bridge:** the 1a bake is gated on a non-empty skeleton; ships
  and bridges have none, so they keep node-local verts + the static walk. Verify
  with an existing ship/bridge render test after 1a/1b.
- **F7 dev preview:** uses the main skinned path; the 1a/1b change must keep it
  correct at bind (now via `u_model=inst.world` + bind-model verts). Covered by
  the updated GPU bind-pose test.
- **Frame budget:** ~5 officers × (sample ~28-bone clip + build palette) per
  frame is trivial; revisit only if many characters render at once.
