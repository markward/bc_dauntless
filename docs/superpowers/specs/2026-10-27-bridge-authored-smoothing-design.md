# Bridge authored smoothing — design

Status: approved by Mark 2026-10-27; built on feat/bridge-authored-smoothing.
Extends: `2026-10-09-bridge-shape-diff-design.md` (the shape diff; §6 fix file,
§7 loader, §11 runbook) and `2026-10-08-bridge-lighting-baseline-design.md` §3
(generated interior normals).

## 1. Intent

Mark sets smoothing on the DBridge in Blender (hand-marked sharp edges plus
Smooth by Angle) and wants the game to shade the bridge the way Blender shows
it. Today that smoothing is thrown away twice:

- `tools/shape_diff/obj_io.py:read_objects` ignores the edit OBJ's `vn` and `s`
  lines.
- The game ignores normals on DBridge shapes anyway. They have none in the NIF
  (the shape-edit loader refuses a shape that does, `mesh_fix.cc:609`).
  `model_build.cc` generates them for interior sets with a fixed 40° crease
  (`generate_normals_across_shapes`, `kSetNormalCreaseDeg`).

**Goal:** the hard/soft decision Mark authors on each edge inside an object
becomes the game's hard/soft decision for that edge.

**Why edge flags, not Blender's normals.** Mark uses only sharp marks and
Smooth by Angle; neither bends normals, so the whole of his intent is one bit
per edge. Storing that bit (rather than Blender's normal vectors):
- is index-only, matching the payload's copyright posture (shape-diff §6.2);
- survives later vertex moves (normals are recomputed from the moved geometry);
- keeps the engine's T-junction repair and its normal maths.

## 2. Goals, non-goals, anti-goals

Goals
- Edge-level smoothing from the edit OBJ reaches the game for every shape the
  edit carries (all 138 DBridge objects in the current export are `s 1`).
- One diff run (`bridge_shape_diff diff ... --write`) produces it, alongside the
  geometry/texture ops, cumulatively like everything else in the fix.
- The verifier proves the game's hard edges match Blender's before writing.

Non-goals
- Custom / bent normals (Weighted Normal modifier, edited split normals). Not
  used; would need stored vectors.
- Changing the base OBJ export. Mark does not need smoothing in `base.obj`
  (the export may stay normal-less).
- Any ship/hull path. Interior sets only; `generate_missing_normals` is the gate.
- EBridge or other bridges in this change (the mechanism is generic; only the
  DBridge fix gets regenerated now).

Anti-goals
- A shape Mark did not author smoothing for changes look. Shapes with no
  smoothing record keep today's 40° behaviour bit-for-bit.
- BC data in the payload. Only indices.
- A silent partial result: if the game's hard edges disagree with Blender's on
  an edited shape, the diff refuses to write (like any verifier mismatch).

## 3. Decided

### 3.1 Reading Mark's intent (diff tool)

- `read_objects` keeps each face corner's `vn` (index or value) alongside its
  position and UV.
- For each edge inside one object shared by exactly two faces: the edge is
  **hard** if the two faces' corner normals differ at either end (compare
  values with a small tolerance, not indices); otherwise **soft**.
- Edges with one face (open boundary) or 3+ faces need no flag.
- An object exported with no `vn` at all carries no smoothing record (it keeps
  the 40° rule). A face with `s off` and no `vn` is the same.
- **Every object that has `vn` is authored (Claude's call).** Blender writes
  `vn` for every object when Normals is ticked, so the tool cannot tell
  deliberate smoothing from a default; it doesn't need to. Measured on the
  current edit (2026-10-27 export, 138 objects, 6,761 two-face edges): 72
  objects have no hard edge, 59 mixed, 0 all hard; 2,111 hard edges. **No soft
  edge folds more than 40°**, and 399 hard edges fold less than 40°. So
  against today's 40° rule, honouring every object only ADDS hard edges
  (Mark's marks); it never smooths a corner the game keeps hard today. A
  flat-shaded object (`s 0` with per-face `vn`) would record all edges hard,
  which is what Blender shows; none exist today.

### 3.2 What the fix stores

- Per shape that has authored smoothing: the list of its **hard** edges as
  pairs of the shape's FINAL vertex indices (after the same fix's
  moves/adds/removes). Every other internal edge of that shape is soft.
- The presence of a record means "this shape's smoothing is authored", even
  with zero hard edges (a fully smooth object).
- Index-only. Where several NIF vertices share a position, any of them may be
  named (normal generation welds by position).

### 3.3 What the game does with it

In `smooth_normals_impl`'s per-edge decision (the place that today compares
the fold against the 40° crease):

- Both faces in the SAME shape, and that shape has a smoothing record →
  the authored flag decides: hard = never join; soft = always join, whatever
  the angle.
- Otherwise (shapes without a record, or an edge **between** two shapes) →
  today's 40° crease, unchanged.
- **Edges the game sees inside a recorded shape that were not two-face edges
  in Blender (Claude's call)** -- T-junction-repaired joins, unwelded mirror
  seams (shape-diff §11.6), edges with 3+ faces -- have no authored intent:
  they fall back to the 40° crease. The verifier ignores them.

T-junction repair runs before smoothing and can split an authored edge; the
pieces of a hard edge stay hard.

**An authored hard edge must survive joins (Claude's call).** Smoothing groups
chain transitively: two faces of shape A split by a hard edge could still be
joined at a shared vertex through a neighbouring shape B whose joins are under
40°. That would render Mark's hard edge soft at that vertex, which Blender can
never show. Rule: corners an authored hard edge separates never end up in one
group, whatever path the joins offer. Mechanism is the builder's (e.g. a
cannot-link check when uniting groups, or treating a join as hard at a vertex
that ends an authored hard edge if the constraint proves impractical -- say
which in the plan). The verifier measures the OUTCOME, not just the per-edge
decision.

### 3.4 Joins between objects — Claude's call

Blender always shows a hard seam where two separate objects meet; the game
smooths across shape joins under 40°. Mark: "not sure if the joining will be a
problem but let's try it". **Claude's call:** joins keep the 40° rule. Make it
one obvious switch (a constant beside `kSetNormalCreaseDeg`) so it can become
"always hard between shapes with authored smoothing" if the game shows
blending at joins Mark doesn't want.

### 3.5 Normal weighting — Claude's call

Blender weights a smooth vertex normal by corner angle; the engine weights by
face area. On smooth curved surfaces the two can differ slightly. **Claude's
call:** keep area weighting (no change to the engine's maths); only the
hard/soft decision is authored. Revisit only if Mark sees a shading difference
he cares about.

## 4. Constraints

- Shared checkout rules (CLAUDE.md): work on a feature branch/worktree; no
  destructive git. **Overlap:** `worktree-ebridge-shape-diff` (another
  session, locked, uncommitted-until-checked) edits `tools/shape_diff/obj_io.py`
  and `match.py`. Branch from `main`; expect a small merge there.
- Fix file stays `format` 1 JSON at `native/assets/mesh_fixes/<fnv1a64>.json`.
  New data needs a new payload version or a new key; the loader keeps reading
  every older payload (BSD1/BSD2) and older fix files without the new data.
- Python encoder and C++ decoder pinned by one hand-built golden blob, as BSD2
  is (`tests/tools/test_shape_diff.py`, `native/tests/assets/cpu/mesh_fix_parse_test.cc`).
- All-or-nothing loader contract (§7): any invalid smoothing record → warn
  once, load the original NIF with no fix at all.
- Mark's OBJs live in `~/Documents/dauntless-artwork/Dbridge/` (the runbook's
  `~/Documents/dauntless-blender/` path is stale — fix §11.2). Never copy them
  or any value from them into the repo or a test.
- Focused tests only during development; no gate (CLAUDE.md "Test gate").
- Commit a regenerated DBridge fix only after Mark's in-game check (runbook
  §11.3 step 4).

## 5. Left to the builder

- Payload shape: a BSD3 per-shape section vs a separate base64 key in the fix
  JSON; record layout; refusal messages.
- How the smoothing record travels from `apply_mesh_fix` (which edits a
  `nif::File`) into `model_build`'s `NormalGenShape` (an in-memory side field
  on the shape data is fine — it is not written anywhere).
- How the hard-edge lookup survives T-junction splits (e.g. test sub-edges for
  collinearity with an authored hard segment in model space).
- Normal-comparison tolerance in the reader.
- The verifier extension (shape-diff §5.4): after applying the fix through the
  real loader with interior normal generation, the set of hard edges inside
  each shape with a record must equal the edit OBJ's. Compare hard/soft per
  edge, not normal values (weighting differs, §3.5). A mismatch refuses
  `--write`.
- Dry-run report: per block, "smoothing: N hard edges", and a summary count.
- Tests: synthetic OBJ round-trip (a cube with some hard edges; a fully smooth
  object; `s off`; no `vn`), decoder refusals, the 40° fallback unchanged for
  shapes without a record, cross-shape edges unchanged, a hard edge split by a
  T-junction stays hard; an asset-backed check on real `Dbridge.NIF` with a
  synthetic record.
- Updating the shape-diff spec (§6.1 layout, §7 refusals, §11 runbook) and its
  CLAUDE.md row.

## 6. Done when

**Which edit.** `~/Documents/dauntless-artwork/Dbridge/Dbridge_modified_and_enhanced_rexport.obj`
is the CURRENT edit: Mark exported it 2026-10-27 18:41 from `fixed-8.blend`
(saved 18:40), the live `.blend` after round 8 (`Dbridge_CEILING_replaced.obj`,
2026-10-17, is older). Every object in it is already named `bNNNN_...`, so
round 8's scratch renames are not needed. Base is
`Dbridge_unmodified_rexport.obj` in the same folder. Round 8's
`--delete 84 90 340 343 361 364` likely still applies (deleted objects stay
deleted); confirm from the dry run's object-set report. Before `--write`,
compare the dry run's per-block summary against the committed fix so no
accepted round-8 work is dropped.

- `diff <base> <edit> --partial [--delete ...]` reports smoothing for the
  edited objects and verifies.
- In game (`--developer`, Developer Options → Lighting → Bridge Debug View,
  normals), the DBridge shows Mark's hard edges where Blender does; shapes and
  joins without authored smoothing look as before.
- Mark accepts it in game; then the fix is committed.

## 7. As built (2026-10-27)

Where the builder's code differs from, or settles, the text above. Layout and
golden: shape-diff spec §6.1; refusals §7; runbook §11.

- **Payload.** A separate fix key, `smoothing` (base64 BSM1), alone or beside
  any other key; not a BSD3. The merge check runs ahead of the
  authored-normals refusal in the loader (the old order left the merge branch
  dead).
- **Duplicate faces are one surface.** Stock DBridge has 3838 of 8580 triangles
  duplicating another triangle's welded position set (seam, reversed and UV
  twins in 123 of 145 shapes), while Blender shows one face per set. Inside a
  recorded shape, faces with the same welded position set are ONE face for
  authored decisions: hard/soft applies between distinct sets, `found` counts
  distinct position sets, and a pair of duplicates always unites (orientation
  from the normal sign).
- **`found`** = exactly two position sets of the authored edge's OWN shape on
  the edge (other shapes' faces along it are ignored, per §3.3). The
  verifier checks each end separately (`joined_a`, `joined_b`).
- **Hard survives joins** by a cannot-link check when uniting groups: corners
  an authored hard edge separates never end in one group, including across
  shapes and across both duplicate sets.
- **Sub-edge matching** after T-junction repair uses collinearity within
  1e-3 x the segment length (the repair's own acceptance, 1/1024 snapping),
  not 1e-5, and only for repair-cut pieces; unlisted edges use the 40° rule.
- **Cross-shape joins** keep the 40° rule; the switch is
  `kAuthoredShapeJoinsHard` in `model_build.cc` (false).
- **`--partial`** drops the record of any block whose smoothing fails
  verification, lists it under `smoothing skipped:`, and re-verifies the rest;
  without `--partial` the CLI refuses and lists every failing block.
- **Known limitation (runbook §11.6).** On Mark's 2026-10-27 export, 11 of 138 objects
  (blocks 145 200 224 255 411 420 438 468 563 575 652; 1-4 failing edges
  each) were refused, 127 recorded (1601 hard / 3433 soft edges), because the T-junction repair's 0.1% tolerance cuts more than
  Blender did (double cuts at a corner, sliver third faces, same-shape
  T-junctions on open borders). They keep the 40° rule under `--partial`.
  A block without a record (including `smoothing skipped` ones) keeps the 40° rule for its own internal edges, but its vertices on a seam with a recorded neighbour can shade differently (cannot-link and authored joins reach across the seam); the verifier does not check unrecorded blocks.
  A fold-back guard for a forced soft join is parked until real data shows it.
