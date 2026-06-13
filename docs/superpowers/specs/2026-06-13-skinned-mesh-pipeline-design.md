# Skinned-Mesh GPU Pipeline (SP1) — Design

> Sub-project 1 of the character-rendering epic. Goal: render a skinned
> character NIF deformed by a GPU bone-matrix palette, held at bind pose.
> SP2 (skeletal animation playback) and SP3 (character assembly + bridge
> spawning) build on this.

## Goal

Get a skinned character NIF rendering on screen, deformed by a bone-matrix
palette. In SP1 the palette is held at **bind pose** (every matrix resolves to
identity), so a skinned draw reproduces the static mesh exactly — proving the
skinning plumbing end to end without an animation variable in play. A
`--developer`-gated hook lets the result be eyeballed in `./build/dauntless`.

## Background — what already exists

The foundation spike established that the *ingest* half is largely built:

- **Skin controller parsing.** `native/src/nif/src/blocks/animation.cc` parses
  `NiTriShapeSkinController` into per-bone `(weight, vertex_index)` tuples
  (`bone_weights[bone] = [{weight, vertex_index}, …]`) plus `bone_links`
  (block links) and `vertex_counts_per_bone`.
- **Skeleton extraction.** `native/src/assets/src/skeleton_build.cc:build_skeleton`
  walks the skin controllers, gathers referenced bones, and builds a flat
  `Skeleton{bones[]}` with `name`, `parent_index`, and `local_transform` per
  bone, plus a `nif_block_to_bone_index` map. It is **already called** from
  `model_build.cc:374`, which stores the result on `Model::skeleton`.
- **Skinned vertex format.** `mesh_upload` binds `loc 4: ivec4 bone_indices`
  (`GL_UNSIGNED_BYTE`) and `loc 5: vec4 bone_weights` (normalized). `opaque.vert`
  declares both attributes.
- **Source assets are genuinely skinned.** `BodyMaleL.nif` carries a full
  `Bip01` biped (`Bip01 Pelvis`, `Bip01 R Thigh`, …) with `NiBone` blocks.

The **gap** SP1 closes:

1. `build_skeleton` leaves `Bone::inverse_bind_pose` at **identity** — it is
   never computed.
2. `model_build.cc` never fills per-vertex `bone_indices`/`bone_weights` from
   the parsed skin tuples — the bound attributes carry zeroed data.
3. `opaque.vert` declares the bone attributes but never uses them — there is no
   skinning math and no bone-palette uniform.
4. No skinned draw path: `frame.cc:draw_model` is purely static (walks the node
   hierarchy, sets `u_model`, draws). `Model::skeleton` is consumed nowhere in
   the renderer.

## Architecture — Approach A (separate skinned program, branched in `draw_model`)

A separate skinned shader program coexists with the existing static program.
`draw_model` branches on whether the model has a skeleton:

- `model.skeleton.bones.empty()` (every ship and bridge mesh) → bind the
  existing static `Shader`, behaviour **byte-identical** to today.
- non-empty → bind the skinned program, upload a bone-matrix palette, draw.

This isolates all skinning behind the "this model has a skeleton" check and
leaves the ship/bridge render provably unchanged — matching the project's
established "production render path untouched" principle (god mode, hologram,
ship-property-viewer all follow it). The bone vertex attributes only ever feed
the skinned program.

Rejected alternatives:

- **One program, uniform-gated skinning branch in `opaque.vert`.** Every ship
  draw would run the skinning shader (short-circuited), so the ship path is no
  longer byte-identical and `opaque.vert`'s currently-dead bone attributes
  become load-bearing for all geometry. More blast radius, no gain.
- **CPU skinning.** Per-frame deformed-vertex re-upload; doesn't scale to a full
  bridge; discards the GPU attributes that already exist.

## Data flow

```
NIF load (model_build.cc)
  ├─ build_skeleton()  → Skeleton{bones[]}            [EXISTS]
  │     + NEW: compute world-bind transform per bone (compose local_transform
  │       root→leaf), set inverse_bind_pose = inverse(world_bind)
  └─ NEW: fill_skin_weights() — walk the NiTriShapeSkinController
        (bone_link, vertex_index, weight) tuples; map bone_link → skeleton
        bone index via nif_block_to_bone_index; write top-4 normalized weights
        into each vertex's bone_indices / bone_weights

draw (frame.cc:draw_model)
  ├─ model.skeleton.bones.empty()?  yes → static program (byte-identical)
  └─ no → skinned program:
        palette[b] = world_pose(b) · inverse_bind_pose(b)
        (SP1: world_pose == world_bind ⇒ palette = identity ⇒ deformed == static)
        upload palette → skinned.vert blends vertex by its ≤4 weighted bones
```

## Components

### `model_build.cc` — skeleton finalize + weight fill

Two additions after the existing `build_skeleton` call:

1. **Inverse-bind computation.** For each bone, compose the world-bind
   transform by walking `local_transform` from the root down the
   `parent_index` chain; set `inverse_bind_pose = inverse(world_bind)`.
   (Order the traversal so parents are processed before children, or memoize by
   walking up per bone.)
2. **`fill_skin_weights()`.** For each mesh produced from a NIF that has a
   `NiTriShapeSkinController`, accumulate per-vertex influences from the
   `(bone_link, vertex_index, weight)` tuples, mapping `bone_link` →
   skeleton bone index via `nif_block_to_bone_index`. Per vertex: keep the
   **top-4 weights**, **renormalize** so they sum to 1, and write them to
   `bone_indices` / `bone_weights`. A vertex with no influences gets
   `weight = (1,0,0,0)`, `index = (0,0,0,0)` — harmless because palette[0] is a
   valid matrix (identity at bind pose).

### `skinned.vert` (new) — palette blend

```glsl
#version 330 core
layout(location=0) in vec3 a_position;
layout(location=1) in vec3 a_normal;
layout(location=2) in vec2 a_uv;
layout(location=4) in ivec4 a_bone_indices;
layout(location=5) in vec4  a_bone_weights;

uniform mat4 u_model, u_view, u_proj;
uniform mat4 u_bones[128];   // palette: world_pose · inverse_bind
out vec3 v_normal_ws; out vec2 v_uv; out vec3 v_position_ws;

void main() {
    mat4 skin = a_bone_weights.x * u_bones[a_bone_indices.x]
              + a_bone_weights.y * u_bones[a_bone_indices.y]
              + a_bone_weights.z * u_bones[a_bone_indices.z]
              + a_bone_weights.w * u_bones[a_bone_indices.w];
    vec4 ws = u_model * skin * vec4(a_position, 1.0);
    v_normal_ws   = mat3(u_model) * mat3(skin) * a_normal;
    v_uv          = a_uv;
    v_position_ws = ws.xyz;
    gl_Position   = u_proj * u_view * ws;
}
```

Reuses `opaque.frag` verbatim. Skinning is applied in model space **before**
`u_model`, so the existing X-flip in `_ship_world_matrix` / `_astro_world_matrix`
composes identically for skinned and static geometry.

> **Shader rebuild note:** new/changed `.vert`/`.frag` files are not picked up by
> `cmake --build` alone — re-run `cmake -B build -S .` first.

### `frame.cc:draw_model` — skinned branch

`draw_model` gains a `Shader& skinned_shader` parameter. At the top: if the
model has no skeleton, bind the static `shader` and proceed exactly as today.
Otherwise bind `skinned_shader`, build the palette
(`palette[b] = world_pose(b) · inverse_bind_pose(b)`; SP1 `world_pose ==
world_bind`, so every entry is identity), upload via
`glUniformMatrix4fv(u_bones, n, …)`, then run the same decal / glow / rim /
draw code on the bound program. The opaque pass owns both `Shader` objects.

### Dev preview hook

A `--developer`-gated host binding `spawn_test_character(nif_name)` with a
`engine/renderer.py` wrapper, driven by a dev keybinding registered through
`dev_mode.register_dev_keybinding`. First press: load `BodyMaleL.nif`,
`create_instance`, place it ~6 GU in front of the exterior camera. Second
press: despawn. The binding is only registered under `--developer`, so the
production path is unaffected. This is the live eyeball check; correctness is
owned by the gtests below.

## A deliberate property of the bind-pose test

At rest `world_pose == world_bind`, so every palette matrix is
`world_bind · inverse(world_bind) = identity` and the skinned vertex collapses
to `Σ wᵢ · v = v`. Therefore **bind-pose-renders-identical-to-static proves the
plumbing** (attribute fill, normalization, palette upload, shader blend)
*independent of whether `inverse_bind` is derived correctly* — the inverse-bind
cancels. Inverse-bind correctness only bites once we animate, so it is a genuine
SP2 concern. To still exercise the palette math in SP1, a second GL test applies
a **synthetic non-identity pose** and asserts the expected vertices displace.

## Testing

**CPU gtests (no GL), in `native/tests/assets/`:**

- `fill_skin_weights`: synthetic controller → vertices receive top-4 normalized
  weights with correctly mapped bone indices; a vertex with >4 influences keeps
  the 4 largest and renormalizes; an unweighted vertex → `(1,0,0,0)` / index 0.
- `inverse_bind`: world-bind composed correctly up the parent chain;
  `world_bind · inverse_bind ≈ I` per bone (within epsilon).
- bone count > 128 → runtime guard (clamp + warn), asserted.

**Offscreen GL gtests (hidden window + `glReadPixels`, existing renderer-test
pattern), in `native/tests/renderer/`:**

- *Plumbing:* render a skinned body NIF at bind pose through the skinned program;
  assert the framebuffer equals the same mesh drawn through the static program.
- *Palette math:* upload a synthetic palette translating all bones by +X; assert
  the non-background pixel centroid shifts +X — proving the palette actually
  deforms, exercising the path the bind-pose test cancels out.

## Risks and deferrals

- **Old-skin per-bone bind-offset matrices** (`NiSkinData`-style per-bone
  bind rotation/translation) are not parsed today. Bind pose cancels them, so
  SP1 is unaffected; correct *animated* posing may require them — an explicit
  SP2 investigation.
- **Weight precision:** `GL_UNSIGNED_BYTE` normalized weights give ~1/255
  resolution. Acceptable for SP1; revisit only if visible artifacts appear.
- **Non-skinned mesh inside a skinned model** would rigidly follow bone 0. Fine
  at bind pose; character body NIFs are fully skinned, so this is not exercised
  in SP1.
- **Palette size 128** mat4 = 512 vec4, within the default vertex-uniform
  budget. A Bip01 biped is ~50 bones; the runtime guard catches any NIF that
  exceeds 128.

## Out of scope (later sub-projects)

- Skeletal animation playback (sampling `AnimationClip` into a live pose) — SP2.
- Character assembly (body + head + textures/uniform), bridge-station spawning,
  bridge-set lifecycle integration, and camera zoom-to-station — SP3.
