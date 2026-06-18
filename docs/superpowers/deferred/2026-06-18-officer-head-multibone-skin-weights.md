# Deferred: preserve the officer head's multi-bone skin weights

**Status:** deferred 2026-06-18. The "lego skeleton" mesh-graft bug is fixed
(`model_build` now honors the NIF hidden flag; `graft_head_cpu` grafts the real
visible head mesh) — see the head-graft fix in
[model_compose.cc](../../../native/src/assets/src/model_compose.cc) and
[model_build.cc](../../../native/src/assets/src/model_build.cc). What remains is
a fidelity refinement: the grafted head is **rigid-bound** to the single
`Bip01 Head` bone, discarding the head mesh's original multi-bone skin weights.

## What ships today

`graft_head_cpu` copies each visible head mesh and overwrites every vertex with

```cpp
v.bone_indices = glm::u8vec4(attach_idx, 0, 0, 0);  // "Bip01 Head"
v.bone_weights = glm::u8vec4(255, 0, 0, 0);
```

So the entire head/face/neck moves as one rigid lump locked to `Bip01 Head`.
The head verts are already baked into character-bind-model space (matching the
body's bind pose), so at the bridge stand pose this is visually correct — the
face sits where it should and is lit/textured properly.

## Why it's only "good enough"

The real BC head mesh (e.g. `limale med head 02:0`) is **skinned across several
bones** — `Bip01 Head`, `Bip01 Neck`, and usually `Bip01 Spine2` — with the
neck/jaw region blended between them. It carries a `NiTriShapeSkinController`
(`ctrl != 0` in the NIF dump; the body meshes do too). Rigid-binding the whole
mesh to `Bip01 Head` means:

- When the **neck bends** (any animation or placement clip that rotates
  `Bip01 Neck` independent of `Bip01 Head`), the lower-neck verts follow the
  head bone instead of the neck bone → a small shear/gap where the neck meets
  the collar.
- The bridge stand clips are nearly static, so this is currently invisible.
  It will start to matter for **talking-head comm animations**, lean/turn
  idles, or any future facial/neck motion (see
  [[2026-06-18-comm-set-viewscreen-rendering-design]] — action-timing /
  dialogue is the named follow-up there, and animated comm heads are exactly
  the case that exposes this).

## Desired end state

Graft the head mesh **preserving its own skin weights**, remapped onto the body
skeleton, so one shared bone palette poses head + neck + body uniformly — the
same way the body mesh already works.

## Path forward (not yet attempted)

The head Model, after `build_model`, already has the head mesh's per-vertex
`bone_indices`/`bone_weights` filled by `fill_skin_weights` — but those indices
point into the **head NIF's own skeleton**. The graft must remap them to the
**body skeleton**:

1. In `graft_head_cpu`, instead of overwriting to `(attach,0,0,0)/(255,…)`, for
   each grafted vertex remap each non-zero influence:
   `body_bone = find_bone(body.skeleton, head.skeleton.bones[head_idx].name)`.
   Keep the weights as-is; renormalize if any influence fails to map.
2. Fall back to the current rigid `Bip01 Head` bind for any vertex whose bones
   don't all resolve (robustness — never collapse to origin).
3. Leave the vertex **positions** untouched: they're already baked into
   bind-model space by `build_mesh_cpu` (via `node_bind_world[parent]`), the
   same space the body uses, so at bind pose `palette = identity` keeps them
   exactly where the rigid path puts them today. The change is purely *which
   bones* drive each vertex under a pose.

### Preconditions / risks to verify

- **Shared bind pose.** This only works if the head NIF and body NIF were rigged
  with the same standard `Bip01` bind transforms. BC characters use the stock
  biped, so this should hold, but it must be confirmed per-vertex (compare a few
  `inverse_bind` matrices for shared bone names between a head and body model) —
  a mismatch would offset or skew the neck.
- **Name collisions / missing bones.** Some head NIFs may weight to a bone the
  body skeleton lacks (unlikely for the shared biped, but the fallback in step 2
  covers it).
- **Verification is visual, AABB won't catch it.** Per
  [[project-bc-character-rigid-skinning]], a skinning contortion stays inside
  the AABB — render and look. Re-enable the disabled PNG dump in
  `native/tests/renderer/skinned_bridge_test.cc`
  (`DISABLED_DumpPosedOfficerPNG`) and pose the head with an independent
  `Bip01 Neck` rotation to confirm the neck follows the neck bone.

## Test hooks that already exist

- `ModelComposeGpuTest.GraftRealHeadOntoBodyMaleL` currently asserts every
  grafted vertex is `bone_indices.x == head_bone, weight == 255` (the rigid
  bind). When this work lands, that assertion changes to "grafted verts are
  weighted across the head/neck bone set" — update it rather than delete it.
- A CPU-only test mirroring `GraftHeadCpu.GraftsHeadMeshNotParentedUnderAttachNode`
  can assert the remap: give the head model two bones (`Bip01 Head`, `Bip01 Neck`)
  with a vertex split 50/50, and assert the grafted vertex carries both body-bone
  indices with the weights preserved.

## Related

- [[project-bc-character-rigid-skinning]] — the rigid-skinning gotchas and the
  hidden-flag root cause this defers from.
- [[project-comm-set-viewscreen]] — animated comm heads are the case that will
  first need this.
</content>
</invoke>
