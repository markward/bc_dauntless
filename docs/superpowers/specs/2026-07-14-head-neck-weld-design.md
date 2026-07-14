# Head attachment and the neck seam — the shared-skeleton weld

**Date:** 2026-07-14
**Status:** approved design, implementation not started (starts after
`feat/character-action-verb-table` wraps)
**Ground truth:** §3.5 "Head attachment and the neck seam" in the decompilation
project's `bridge-character-system.md`
(`STBC-Reverse-Engineering-1/docs/gameplay/`, added 2026-07-14). Per the
evidence-tiers rule, that document outranks SDK inference for engine behaviour.

## What BC does (§3.5, condensed)

BC characters are a body NIF + a separate head NIF, and the neck seam never
splits — yet **there is no weld code**. Both meshes are skinned to one shared
`Bip01` skeleton; head attachment is a bind-by-name scene-graph graft done once
at creation (`FUN_00668A20`):

1. **Match by node name** against the body tree (`GetObjectByName`), never by
   geometry.
2. **Bone rebinding — the actual "weld".** Walk the head skin's bone array and
   re-point each entry at the body skeleton's identically-named node. Head and
   body neck vertices are then driven by the same physical `NiNode`s; the head
   skin keeps its own per-bone bind offsets.
3. **Reparent** the head geometry (`AttachChild`).
4. **Texture fixup only:** `strstr(path, "head.tga")` → assign the
   `ReplaceBodyAndHead` head texture. No vertex data is ever touched.

Deterministic CPU skinning then keeps coincident, identically-weighted seam
vertices bit-identical every frame. Positional and lighting continuity at the
seam are **authoring invariants** of the exported NIFs (matched seam-ring
positions, weights, normals), not engine features. The per-frame head-look
system (`UpdateHeadLookAt`, `0x0066A2E0`) rotates the shared `"Bip01 Head"`
bone; the body's collar vertices are weighted to that same bone, which is why
the neck follows.

## Audit: Dauntless vs BC (evidence, 2026-07-14)

Probes used the project nif parser (`libnif.a`) against the shipped `game/`
NIF corpus; SDK pairs extracted from `CharacterClass_Create` call sites.

| Mechanism | BC | Dauntless today | Verdict |
|---|---|---|---|
| Name match | every head node vs body tree | only the attach bone (`find_bone`/`choose_attach_node`, `native/src/assets/src/model_compose.cc:87-100,149,171`) | partial — missing bones never handled |
| Bone rebinding | re-point head skin's bone array at body skeleton; weights kept | **weights discarded**; all head verts rigid-bound to `Bip01 Head` with weight 255 (`model_compose.cc:232-234`) | **the bug** |
| Reparent | `AttachChild` into body tree | meshes appended under attach node (`model_compose.cc:245-283`) | equivalent |
| Texture fixup | replace textures whose path contains `head.tga` | `set_base_texture(body, head_mesh_indices, head_tex)` (`model_compose.cc:370`) | equivalent in effect (see below) |
| Bind mismatch | absorbed per-bone via the head controller's own bind offsets | translation-only vertex rebase (`model_compose.cc:208-218,227`) | approximation; replace |
| Light re-registration | re-register body root into head-tree lights | absent | N/A — head NIFs carry no `NiDynamicEffect` (block-inventory probe) |
| Root normalization | wrapper node with negated root translation | placement transform + clips handle it | N/A |
| Head-look | `UpdateHeadLookAt` rotates shared `Bip01 Head` | absent everywhere | follow-up (out of scope) |

Key corpus facts:

- `miguel_head.NIF` face mesh (`grmale med head 01:0`): skinned to **6 bones**
  — `Bip01 Head` (178 weight records), `Neck` (39), `R Clavicle` (10),
  `Ponytail1` (27), `L Clavicle` (7), `Spine2` (9); 51 of 143 verts multi-bone;
  **all 143 verts weighted** (no coverage gap). `fem3_head.nif` matches the
  shape (6 bones, 64 multi-bone verts). Rigid-binding all of that to
  `Bip01 Head` flattens the collar blend → the seam shears whenever the neck
  bends relative to the head (every nod gesture; any future head-look).
- All 22 SDK body/head pairs swept for bind-pose agreement: **18 bit-identical**
  (BC's authoring invariant), **4 mismatched** by ~4.85–5.9 units —
  `BodyMaleM`+`miguel_head`, `BodyMaleM`+`ferengi_head`,
  `BodyFemM`+`fem3_head`, `BodyFemM`+`femromulan_head`. The deltas are pure
  translations but **per-bone-different** (e.g. `Spine2` 4.85 vs `Head` 5.48),
  so no single-translation rebase can be exact. BC absorbs this because its
  skinning composes the body's posed nodes with the head controller's own
  per-bone bind offsets.
- Body skeletons (checked `BodyMaleS`, `BodyFemM`) have **no
  `Bip01 Ponytail1`** node, yet head skins weight 27–28 verts to it. A correct
  fix must append head-only bones, not just remap.
- Every head NIF's single embedded texture is the literal placeholder basename
  `head.tga` (checked miguel, felix), which never resolves on disk. That is why
  BC's fixup keys on that string, and why a head with no override renders
  untextured. Our plumbing (SDK `ReplaceBodyAndHead` texture paths →
  `CharacterClass.appearance()` → `assemble_officer` →
  `set_base_texture`) is intact and paths resolve
  (`GetImageDetail()==2` → `Heads/` root, files exist on disk). The
  project-memory line "heads render untextured" predates the texture-override,
  hidden-flag, and comm-head fixes and is believed stale — confirm live,
  update the memory; code changes only if it reproduces.

## Design

### 1. `graft_head_cpu` remaps bone indices; never rebinds, never moves verts

In `native/src/assets/src/model_compose.cc`, replace the rigid-bind block and
the rebase block with a name-keyed bone remap:

1. Build `body_bone_by_name` from `body.skeleton`.
2. For each bone of `head.skeleton` (only those actually referenced by grafted
   meshes need entries, but mapping all is simpler and harmless), produce a
   body-palette index:
   - **Name found, binds equal** (compare `inverse_bind_pose`, max-abs
     component epsilon `1e-4`): the body bone's own index.
   - **Name found, binds differ:** append an **alias bone** to
     `body.skeleton.bones`: `parent_index` = matched body bone,
     `local_transform` = identity, `inverse_bind_pose` = the **head's**,
     `name` = body bone name + `"@head-bind"`. The suffix guarantees
     `sample_pose`/`sample_pose_over_base` by-name track and `rest_locals`
     lookups never drive it, so its posed local stays identity and
     `build_bone_palette` yields
     `posed_body_bone_world · head_inverse_bind` — exactly BC's semantics —
     with **zero renderer/shader/palette changes**
     (`native/src/renderer/bone_palette.cc:33-45`,
     `native/src/renderer/pose_sampler.cc:44-61`).
   - **Name missing** (e.g. `Bip01 Ponytail1`): append a **real bone**:
     name kept verbatim (clips may drive it), `local_transform` = the head
     NIF's local, `inverse_bind_pose` = the head's, `parent_index` = the
     mapped index of its head-skeleton parent (process bones in head-skeleton
     hierarchical order so parents map first).
3. Rewrite each grafted vertex's `bone_indices` through that table;
   `bone_weights` are byte-preserved. This uniformly covers skinned **and**
   rigid head shapes — `build_model` already gave rigid verts a parent-bone
   binding (`model_build.cc:673-684`), which remaps through the same table.
4. Delete the rebase block (`model_compose.cc:208-218`) and the
   `v.position += rebase` line — the alias-bone mechanism subsumes it exactly,
   per-bone instead of single-translation.

Untouched: reparenting/attach-node choice, the body-head-subtree mesh clear
(no-op today; kept), material/texture merge and `animation_index` drop,
`head_mesh_begin`, face-texture slots, `assemble_officer`'s signature, and all
Python callers.

Headroom: body skeletons are ~40 bones; appends are ≤7 per officer
(`kMaxBones` = 128, `bone_palette.h:11`). `bone_palette` already warns and
clamps if ever exceeded.

### 2. Texturing

No code change. `set_base_texture` on the grafted mesh indices is equivalent in
effect to BC's `head.tga` fixup because the placeholder is the head NIF's only
texture. Live-verify; if untextured heads still reproduce, diagnose then (the
one known-plausible gap: a material whose Base stage never had a texture may
take a different draw path — check only if the symptom is real).

### 3. Tests (gate: `scripts/check_tests.sh` — C++ + pytest + ledger diff)

C++ (assets suite), synthetic skeletons:
- bind-equal pair → direct remap, no bones appended, weights byte-identical;
- bind-differ pair → alias appended with the head's `inverse_bind_pose`,
  parent = matched body bone, suffixed name, verts point at the alias;
- head-only bone → appended with correct name/parent/local;
- rigid head shape → parent-bone binding remapped through the same table.

C++ (real NIFs, mirroring `ModelComposeGpuTest.GraftRealHeadOntoBodyMaleL`):
- **Seam invariant, matched pair** (§3.5 restated as a test): graft
  `BodyMaleS` + `miguel_head` (bind-identical pair). Find body-mesh/head-mesh
  vertex pairs whose CPU-skinned positions coincide at bind and whose
  bone-index/weight bytes are equal after the remap (the authoring invariant —
  on a matched pair both sides reference the *same* palette entries), build a
  palette with a non-trivially rotated `Bip01 Neck`, CPU-skin both sides,
  assert the pairs stay **bit-identical** — the arithmetic is literally the
  same, exactly BC's guarantee.
- **Seam invariant, mismatched pair**: same construction on
  `BodyMaleM` + `miguel_head`, but pairs are found by skinned-at-bind
  coincidence (raw head verts sit ~5 GU low; the alias palette lifts them),
  and the posed assertion uses a tight epsilon (~1e-4 GU) rather than bit
  equality — body verts skin through `W·O_body`, head verts through
  `W·O_head`, mathematically equal on the seam ring but distinct float paths.
- **Placement regression** (replaces the deleted rebase's coverage): at bind
  pose, the grafted head's *skinned* vertex AABB sits at the body's head
  height for the mismatched pair (no head-in-chest telescoping).

Existing suites must stay green; any test asserting the old rigid-bind
behaviour is updated in the same change (never orphaned).

### 4. Live GUI verification (Mark runs; no synthetic input/capture)

`./build/dauntless --developer`:
- bridge officers: heads textured; neck unbroken through hit reactions and
  nod gestures;
- one **mismatched-pair** character and one matched-pair character checked;
- a comm hail (comm characters share `assemble_officer`) — head textured,
  lip-sync face swaps still work (`set_officer_face` path untouched).

### 5. Branch / sequencing

Implementation starts only after `feat/character-action-verb-table` wraps, on
a fresh branch off it (or off `main` once it merges). This spec is committed to
the current branch (explicit pathspec — shared checkout, no branch switching
while the sibling session is active). Files owned by the sibling branch
(`engine/appc/*.py` character/anim modules, `engine/bridge_character_anim.py`)
are not touched by this design at all — the whole change lives in
`native/src/assets/` + tests.

### 6. Explicit non-goals / follow-ups

- **Head-look** (`UpdateHeadLookAt`): not built. Gated on the decompilation
  project publishing that function's internals (engage conditions, targets,
  limits, blend rates). This weld is its hard prerequisite: afterwards,
  head-look is "rotate one shared bone", zero graft rework. Never load-bearing
  for mission logic — cosmetic bridge polish.
- **Light re-registration**: nothing to do on this corpus (no lights in head
  NIFs). If a modded head NIF ever carries one, that's new work.
- **Seam lighting continuity**: an authoring invariant of the NIFs; we rely on
  it exactly like BC does. Not engineered.
- Officer `model_aabb` note: head verts stay in head-bind space (no rebase
  shift), so a mismatched pair's raw CPU-vert union is ~5 GU off at the head.
  Officers are never shield-registered (the only `model_aabb` consumer), so
  this is cosmetic-null today; noted for whoever next reuses `model_aabb`.
