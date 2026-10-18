# Articulated Hull Decals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hull name decals on an articulated ship part follow the part through every pose and leave with it when it is shot off; the SPV places such decals at rest and restricts them to the clicked shape.

**Architecture:** The opaque shader already receives `u_node_rest_fix` (C_i = rest · posed⁻¹ per node) on every mesh draw for the glow-region test; the hull-decal loop is fed the same rest-frame position/normal/gradients. The SPV's Decals pane holds the NIF pose while active and derives each placement's `shape` from the mesh under its centre whenever that mesh sits under a part this ship's rig articulates.

**Tech Stack:** GLSL 4.10 (`opaque.frag`), C++17 gtest (`renderer_tests`), Python 3.11 pytest.

**Spec:** `docs/superpowers/specs/2026-10-18-articulated-hull-decals-design.md`

## Global Constraints

- Work in worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/articulated-hull-decals`, branch `fix/articulated-hull-decals`. Never `cd` to the main checkout.
- ⛔ Never run `scripts/check_tests.sh` or a whole pytest suite (`tests`, `tests/unit`, `tests/ui`). Run ONLY the focused test files/filters named in your task. The machine is used for performance testing.
- ⛔ No destructive git: no `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit paths. To mutate a file temporarily, back it up with `cp` and restore with `cp`, then `diff` to prove the restore.
- ⛔ Do not launch the game (`./build/dauntless`), not even headless. Shader compile is proven by `renderer_tests`, which drive the real opaque shader through the real submit path.
- Shader edits need `cmake -B build -S .` BEFORE `cmake --build build -j` (the embedded shader header regenerates only at configure); then `grep -n "<new snippet>" build/native/src/renderer/embedded_opaque_fs.h` (or the matching `embedded_*opaque*` header) proves it landed.
- Unarticulated ships and articulated ships at their rest pose must render byte-identically to before (spec §3.4, §5).
- No `decals.json` format change and no new correction matrix (spec §5).
- Commit messages via `git commit -F <file>`, ending with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Uniform persistence across draws** — an articulated ship drawn before a plain one must not shift the plain ship's decal (u_node_rest_fix is per-draw state). Pinned in Task 1 (test 3).
2. **Gradient frame mismatch** — rotating the position but not the `dFdx/dFdy` gradients gives a wrong mip on a rotated part (blurred or aliased lettering). Pinned in Task 1 by the rotated-node test comparing painted pixel count against the unrotated render (within 10%).
3. **Severed node (zero-matrix override)** — the singular posed matrix must not produce NaN or ghost lettering on the ship, while the chunk instance still shows it. Pinned in Task 1 (test 4).
4. **Mirror of a part decal** — must land restricted to the mirrored shape, not the source shape (would paint nothing). Pinned in Task 3.
5. **A trace that misses** (centre floated off the hull by a paste) — must keep the old `shape`, never blank it. Pinned in Task 3.

---

### Task 1: Hull decals use the rest-frame correction (renderer)

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag` (the hull-decal loop, ~line 1646, and the comment block above `apply_hull_decal`, ~line 140)
- Test: `native/tests/renderer/decal_render_test.cc` (append a new section)

**Interfaces:**
- Consumes: existing `uniform mat4 u_node_rest_fix;` (declared ~line 399; already set per mesh draw by `frame.cc:922`, identity unless articulated). `apply_hull_decal(int i, vec3 p_body, vec3 n_body, vec3 dpdx, vec3 dpdy, inout vec3 base_rgb, inout float cover_a, inout vec3 cover_rgb)` — signature unchanged.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing tests** in `decal_render_test.cc`, using the file's existing fixture, Ambassador loader, masks and pixel counters, and the node-override pattern of `frame_test.cc:GlowRegionFollowsARotatedNode` (`world.get(iid)->node_overrides[node] = model.nodes[node].local_transform * R`). Use an asymmetric opaque-red mask placed over ONE half of the saucer top (body +X half), restricted to the saucer shape.
  1. `DecalRenderTest.DecalFollowsANodeRotatedAboutUp` — override the root (or the saucer shape's node) with its rest local × 180° about body +Z (up), so the saucer top still faces the camera but the +X half moves to screen-left. Assert: red pixels in the screen-left half ≥ 0.8 × red pixels in the screen-right half of the unrotated render; red pixels in the screen-right half of the rotated render ≤ 0.1 × that same baseline; total red count within 10% of the unrotated total.
  2. `DecalRenderTest.RestPoseOverrideRendersDecalIdentically` — an override equal to the node's own rest local vs no override: `differing_texels == 0` (add a local helper if the file has none).
  3. `DecalRenderTest.ArticulatedShipDrawnFirstDoesNotShiftAPlainShipsDecal` — as `frame_test.cc:GlowRegionOnPlainShipUnaffectedByArticulatedShipDrawnFirst`: a rotated, shrunk ship created first in a corner, then the plain decaled ship; its red count and red mean row equal the plain-alone render exactly.
  4. `DecalRenderTest.SeveredNodeTakesItsDecalToTheChunk` — ship instance with the saucer's part node set to `glm::mat4(0.0f)` (what `set_instance_node_hidden` writes): zero red pixels and no NaN-black hole beyond the hidden part (assert `glGetError()==GL_NO_ERROR` and red == 0). Chunk instance with every OTHER Scene Root child hidden the same way: red count within 5% of the plain render. Find the part nodes by walking `model.nodes` for the node named "Scene Root" and taking its children (the rule in `renderer/model_parts.h`).

- [ ] **Step 2: Build and run to verify tests 1 fails (tests 2-4 may already pass — that is expected; they pin behaviour the change must keep)**

Run: `cmake --build build -j --target renderer_tests && ./build/native/tests/renderer/renderer_tests --gtest_filter='DecalRenderTest.*'` (locate the binary with `find build -name renderer_tests -type f` if the path differs)
Expected: `DecalFollowsANodeRotatedAboutUp` FAILS (red stays screen-right); all pre-existing `DecalRenderTest.*` pass.

- [ ] **Step 3: Implement in `opaque.frag`**: in the hull-decal loop, compute once, outside the loop and outside any branch, `p_dec = (u_node_rest_fix * vec4(p_body, 1.0)).xyz`, `n_dec = mat3(u_node_rest_fix) * n_body` (no `normalize` — same rigid-correction reasoning as the glow path's comment ~line 1932), `dpdx_dec = mat3(u_node_rest_fix) * dpdx_d`, `dpdy_dec = mat3(u_node_rest_fix) * dpdy_d`, and pass those to `apply_hull_decal`. Leave `p_body`, `n_body`, `dpdx_d`, `dpdy_d` untouched for every other consumer. Update the comment block above `apply_hull_decal` to say decals are tested in the REST frame via `u_node_rest_fix` and cite the spec.

- [ ] **Step 4: Reconfigure, rebuild, prove the shader landed, run tests**

Run: `cmake -B build -S . && cmake --build build -j && grep -rn "u_node_rest_fix \* vec4(p_body" build/native/src/renderer/embedded_*opaque*fs*.h | head`
Expected: grep shows the decal line AND the existing glow line.
Run: `./build/native/tests/renderer/renderer_tests --gtest_filter='DecalRenderTest.*:FrameTest.GlowRegion*:FrameTest.RestPoseOverride*'`
Expected: all PASS.

- [ ] **Step 5: Commit** `native/src/renderer/shaders/opaque.frag native/tests/renderer/decal_render_test.cc` — `fix(decals): hull decals use u_node_rest_fix so they follow articulated parts`.

---

### Task 2: The SPV holds the NIF pose while the Decals pane is active

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py` (`_sync_part_pose`, ~line 726)
- Modify (only if needed): `engine/ui/spv_decals_pane.py` (`_decal_enter` / `_decal_leave`)
- Test: `tests/ui/test_spv_decals_pane.py`

**Interfaces:**
- Consumes: `self._decals_active: bool` (set by `_decal_enter`/`_decal_leave` in `spv_decals_pane.py`); `_selected_state_node()`; `articulation.force_pose(ship, None)` / `force_state_poses`.
- Produces: invariant relied on by Task 3 — while `_decals_active` is True, every articulated part of the SPV ship is at the NIF pose, so a trace and `world_to_body` give REST-frame body points.

- [ ] **Step 1: Write the failing tests** (reuse the file's `env` fixture; give the fake ship a one-part rig and select that part's `warp` state node the way `tests/ui/test_spv_part_nodes.py` does — copy its setup helper rather than inventing one):
  1. `test_entering_the_decals_pane_returns_a_posed_ship_to_the_nif_pose` — with a `{warp}` state node selected and the ship posed (`_applied_part_pose` not None), dispatch `decal-pane`: afterwards `articulation.pose_for_part(ship, part)` is the identity pose and `_applied_part_pose is None`.
  2. `test_leaving_the_decals_pane_restores_the_selected_state_pose` — then dispatch `decal-pane` again: the state pose is re-applied (`_applied_part_pose` names `warp`).
  3. `test_selecting_a_state_node_while_the_decals_pane_is_active_keeps_the_nif_pose` — if the selection model allows selecting a state node while the pane is active; if it does not (selecting leaves the pane), assert THAT instead and name the test `..._leaves_the_decals_pane`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/ui/test_spv_decals_pane.py -k "nif_pose or state_pose or decals_pane" -v`
Expected: test 1 FAILS (ship stays posed).

- [ ] **Step 3: Implement**: in `_sync_part_pose`, treat an active Decals pane as "no state selected" (`want = None` when `getattr(self, "_decals_active", False)`), so the existing change-detection snaps to the NIF pose on entry and re-applies the selected state on leave. Make sure `_sync_part_pose` runs after the `decal-pane` action (it runs after every dispatched action — verify; if `_decal_enter` is reachable outside dispatch, call it there too).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ui/test_spv_decals_pane.py tests/ui/test_spv_part_nodes.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit** the touched files — `fix(spv): hold the NIF pose while the Decals pane is active`.

---

### Task 3: Shape derived from the mesh under a decal on articulated parts, plus docs

**Files:**
- Modify: `engine/ui/spv_decals_pane.py` (new helper; `decal_click`; `_decal_apply`)
- Modify: `engine/ui/spv_edit_targets.py` (`DecalTarget.mirror`, ~line 1205)
- Modify: docs — `docs/superpowers/specs/2026-09-28-hull-name-decals-design.md` (§7 line ~312), `docs/superpowers/specs/2026-09-28-spv-decal-editing-design.md` (non-goal ~line 254), `docs/superpowers/specs/2026-10-17-subsystem-physical-parents-design.md` (~line 339), `CLAUDE.md` (the "Hull name decals" row)
- Test: `tests/ui/test_spv_decals_pane.py`, `tests/ui/test_spv_decal_clipboard_mirror.py`

**Interfaces:**
- Consumes: Task 2's invariant (rest pose while the pane is active). `host_io.ray_trace_mesh_pick(iid, origin, direction, max_dist, exclude_meshes=())` → hit tuple including `(mesh_index, triangle)` or None (read its exact return shape in `engine/host_io.py:545`). `host_io.model_identity(iid)` → `{"meshes": [{"mesh", "name", "node_chain", ...}], ...}` or None. `articulation.parts_for_ship(ship)` → tuple of part properties; part name via `articulation._part_name(part)` (or the public equivalent if one exists). `decal_editor.centre(p)`, `Placement.normal`, `Placement.shape`, `dataclasses.replace`.
- Produces: `DecalsPaneMixin._decal_shape_at(self, body_point: Vec3, body_normal: Vec3) -> Optional[str]` — `None` = the trace missed (caller keeps the old shape); `""` = hit a mesh not under an articulated part; else the hit mesh's shape name. And `DecalsPaneMixin._decal_with_derived_shape(self, p: Placement) -> Placement` — `p` with `shape` from `_decal_shape_at(centre(p), p.normal)`, or `p` unchanged on a miss.

- [ ] **Step 1: Verify the name match** before writing code: confirm `model_identity`'s mesh `name` is the string `model_build.cc:apply_decals` compares with `Mesh::shape_name()` (the committed Ambassador entry is `amb saucer:0`). Read `host_bindings.cc`'s `model_identity` binding. If they differ, derive the shape string the way `apply_decals` expects and note it in the commit message.

- [ ] **Step 2: Write the failing tests.** Stub `host_io.ray_trace_mesh_pick` and `host_io.model_identity` in the test (fake meshes: `0` = `"hull:0"` with node_chain `["Scene Root", "hull"]`; `1` = `"wing left:0"` chain `["Scene Root", "wing left", "__NDL_MultiMtl_Node"]`; `2` = `"wing right:0"` chain `["Scene Root", "wing right", ...]`); give the fake ship a rig with parts `wing left` and `wing right` (monkeypatch `articulation.parts_for_ship`). The stub picks the mesh from the sign of the trace origin's body X (beyond ±X threshold → wing, else hull) so Mirror is testable. Tests:
  1. `test_a_click_on_an_articulated_part_fills_the_shape` — Add + click on the left wing → placement `shape == "wing left:0"`.
  2. `test_a_click_on_the_hull_leaves_the_shape_empty` → `shape == ""`.
  3. `test_a_part_on_a_ship_without_a_rig_leaves_the_shape_empty` — `parts_for_ship` returns `()`; click on the wing mesh → `""`.
  4. `test_reposition_onto_the_hull_clears_the_shape` and `test_reposition_onto_the_other_wing_replaces_the_shape`.
  5. `test_a_gizmo_move_onto_the_hull_clears_the_shape` (drive `axis_drag_apply` as the existing move-gizmo test does).
  6. `test_a_paste_whose_trace_misses_keeps_the_shape` — stub returns None for the pasted centre.
  7. `test_rotate_and_scale_do_not_retrace` — count stub calls: a roll nudge and a width nudge make zero `ray_trace_mesh_pick` calls.
  8. In `test_spv_decal_clipboard_mirror.py`: `test_mirroring_a_left_wing_decal_restricts_the_copy_to_the_right_wing` → copy `shape == "wing right:0"`, source unchanged.
  9. `test_headless_trace_keeps_todays_behaviour` — `ray_trace_mesh_pick` returning None everywhere: Add gives `shape == ""` exactly as before.

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/ui/test_spv_decals_pane.py tests/ui/test_spv_decal_clipboard_mirror.py -v`
Expected: the new tests FAIL; every pre-existing test PASSES.

- [ ] **Step 4: Implement.**
  - `_decal_shape_at`: build a ray that starts a short distance outside the surface along `body_normal` and points along `−body_normal`, through the SAME frame chain `_decal_hull_hit` uses (`body_to_world` → `frames.view_offset(frames.containing_set(ship))` shift into VIEW coords; direction via `body_dir_to_world`). Start offset and max distance: `max(p.depth, 1.0)` body units scaled to GU with `instance_scale(ship)` — read `_decal_hull_hit`, `body_to_world` and `instance_scale` and match their units exactly. Mesh → entry from `model_identity` (cache per iid for the pane's lifetime; drop the cache in `_decal_leave`). Under an articulated part ⇔ the entry's `node_chain` shares a name with `{part names of parts_for_ship(ship)}`. Swallow binding exceptions via `dev_mode.log_swallowed` and return None.
  - `decal_click`: after building the placement (Add) or re-seating it (Reposition), pass it through `_decal_with_derived_shape`.
  - `_decal_apply`: when `decal_editor.centre(new_p)` differs from the current placement's centre, pass `new_p` through `_decal_with_derived_shape` first. Rotate and Scale keep the centre, so they never re-trace.
  - `DecalTarget.mirror`: pass the new placement `q` through `pane._decal_with_derived_shape` before appending.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/ui/test_spv_decals_pane.py tests/ui/test_spv_decal_clipboard_mirror.py tests/ui/test_spv_edit_target_characterisation.py -v`
Expected: all PASS.

- [ ] **Step 6: Docs.** Point the two 2026-09-28 specs' articulated-decal lines and the physical-parents spec's decal-slide note at `2026-10-18-articulated-hull-decals-design.md` as resolved. In `CLAUDE.md`'s "Hull name decals" row, replace `⚠️ No \`u_node_rest_fix\`: an ARTICULATED-shape decal slides with the part.` with `Articulated parts: decals test in the rest frame via \`u_node_rest_fix\`; the SPV places at the NIF pose and fills \`shape\` on rigged parts (spec 2026-10-18).` — keep the row no longer than it is now (trim elsewhere in the row if needed). Then run `uv run pytest tests/docs/test_doc_consistency.py -q` if that file exists.

- [ ] **Step 7: Commit** the touched code, test and doc files — `feat(spv): derive decal shape on articulated parts; docs`.
