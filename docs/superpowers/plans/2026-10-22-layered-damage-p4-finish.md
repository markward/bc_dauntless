# Layered damage production, phase 4: finish and retire the carve — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the old voxel carve and close everything left before the branch can merge to main:
- damage that moves with articulated parts;
- structure parts ready at load and cached on disk;
- the loose ends of breaking apart;
- molten rims on fresh tears;
- tuning in Developer Options;
- docs and a final measured verdict.

**Architecture:**
- **Removal first.** Python (Task 1), then native (Task 2), with each removed capability's replacement already in place from phases 1–3.
- **Rest frame (Task 3).** Records carry a node and live in that node's rest frame. The plating, mark, interior and severance all evaluate in the rest frame through `u_node_rest_fix` / `rest_corrections`, as the hull-name decals already do.
- **Then the remaining features:** Tasks 4–8, docs (Task 9) and the final measurement (Task 10).

**Tech Stack:** C++20, GLSL 410 core, pybind11, Python 3, CEF (JS) for Developer Options, GoogleTest, pytest, CMake (Debug tree `build/`).

**Spec:** `docs/superpowers/specs/2026-10-22-layered-damage-p4-finish-design.md` (the binding authority for this plan). Parent: `docs/superpowers/specs/2026-10-21-layered-hull-damage-production-design.md`. The removal inventory is the phase-3 final review; it is reproduced in Task 1 and Task 2 files.

## Global Constraints

- **Git.** Worktree `.claude/worktrees/damage-redesign`, branch `spike/damage-redesign`.
  - Never run `git checkout --`, `restore`, `stash`, `clean`, `reset --hard` or `add -A/.`.
  - Stage explicit paths. Commit with `git commit -F <file>`, ending `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
  - Never touch `main`.
- **Tests.** Focused tests only, with explicit lists; never a whole suite or the gate.
  - GL: `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" build/native/tests/renderer/renderer_tests --gtest_filter=...`.
  - Pytest: `env -u VIRTUAL_ENV uv run pytest -q -p no:cacheprovider <files>`.
  - Delete tests that only test removed code. Never leave a test that passes against a no-op.
- **`opaque.frag` rules.**
  - It is optimizer-fragile on this Mac: no new samplers, no early `return` in main, the plating discard stays ONE statement.
  - Run `ScuffTest.*`, `DecalRenderTest.*`, `PlatingRender*` and `HullInterior*` after any edit.
  - The stock program may change ONLY by losing the carve clip and its uniforms/sampler, and an undamaged hull must render identically (pinned in Task 2).
- **Shader edits.** `cmake -B build -S .` before `cmake --build build -j`. Rebuild `dauntless` and `_dauntless_host`. Keep `engine/host_io.py`'s required-bindings list in step with the bindings.
- **Writes.** Never write under `PROJECT_ROOT` outside the install-write guard's allowlist. Caches go through `engine/paths.py` (`cache_dir()`).
- **Perf captures.** Only on an idle machine (1-minute load < 3; no game, tests or builds of ours). Record them as new C-/SIG- rows only.

## Review Focus

1. **Undamaged hulls render identically after the carve removal.** Pinned in Task 2 (`UndamagedHullUnchangedByCarveRemoval`).
2. **A damaged nacelle that moves keeps its damage on the nacelle,** including interior rooms and cut holes. Pinned in Task 3 (`DamageFollowsAnArticulatedNode`).
3. **A corrupt, truncated or old-version structure-parts cache file is ignored and rebuilt,** never trusted. Pinned in Task 4 (`CorruptCacheFileIsRebuilt`).
4. **The parent stops shadowing a lost part, and the chunk shadows only its piece.** Pinned in Task 5 (`ShadowHonoursThePartMask`).
5. **Lights on a severed structure part go out.** Lights elsewhere stay on. Pinned in Task 6 (`LightsOnALostPartGoOut`).

---

### Task 1: Remove the carve (Python), re-home what it still did

**Files:**
- Delete: `engine/appc/hull_carve.py`, `engine/appc/core_breach_carve.py`, and every test that only tests them. Find them with grep.
- Modify:
  - `engine/appc/hit_feedback.py`: remove step 5 (carve).
  - `engine/appc/combat.py`: rename `allow_hull_carve` to `allow_structural_wear` everywhere, keeping its meaning, which gates phaser wear.
  - `engine/appc/visible_damage.py`:
    - remove the carve branch and the `hull_carving_enabled` fork, so the layered branch is the only path;
    - remove the capsule queue.
  - `engine/appc/death_cascade.py`: drop the capsule call and `kCascadeCapsuleRadiusGu`.
  - `engine/appc/hull_breakup.py`: remove `after_carve`, `_check`, the carve half of `drain`, `_pending` and `_last_check`.
  - `engine/appc/warp_core_breach.py`: the core-breach visual becomes Internal records.
  - `engine/host_io.py`: remove `hull_carving_enabled`, `hull_carve_add`, `hull_split_detached`, `hull_carve_capsule` and their manifest entries.
  - `engine/appc/hull_volume.py`, `engine/host_loop.py`, `engine/renderer.py`: remove the instance-field hull-volume calls (`prewarm_field`, `hull_volume_*`, the realize and warp-preload field prewarm, the boot cache-root push). KEEP `prefetch_hull_fill`.
  - `engine/dev_missions/damage_preview.py`: DamageTool volumes go to Internal records.
  - `tests/conftest.py` and `tools/mission_harness.py`: reset hooks for removed state. Fix both twins.
- Test: the existing files for the areas above (find them; update their expectations), plus `tests/unit/test_warp_core_breach_visual.py` (new).

**Interfaces:**
- **The core-breach visual.** `warp_core_breach.detonate` schedules three `host_io.hull_damage_add(iid, core_point, normal, radius_k, 10.0, 3)` calls at t = 0, 0.5 and 1.0 s, with radius_k = R·(0.4, 0.7, 1.0).
  - R = clamp(0.25 × `GetRadius()`, 0.1, 1.2) GU.
  - Drive it from the same per-frame advance that `core_breach_carve` used. Move that advance into `warp_core_breach`.
  - After the last record, call `hull_breakup.after_wear`.
- **Before deleting anything,** grep every consumer of each removed symbol in `engine/`, `tools/`, `tests/` and `native/`. Anything with a non-carve consumer is kept and listed in the report with its consumer.

- [ ] **Step 1: Write the failing tests:**
  - `test_core_breach_grows_three_internal_records`: wear 10, kind 3, radii 0.4/0.7/1.0 × R at the core.
  - `test_no_carve_symbols_remain`: an AST or grep-based test asserting the removed names are absent from `engine/`. Mirror the style of `tests/unit/test_path_indirection.py`.
  - Update every test that asserted carve calls to assert the layered calls instead.
- [ ] **Step 2: Run** the touched pytest files. Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the touched pytest files, plus the hit-path files (`test_hit_feedback_*`, `test_decal_emission.py`, `test_torpedo_decal_emission.py`, `test_collision_*`, `test_visible_damage*.py`, `test_death_cascade*`, `test_hull_breakup*.py`, `test_hull_wear.py`, `test_internal_blast.py`, `test_host_io_binding_manifest.py`, `test_renderer_binding_manifest.py`, `test_damage_preview_impulse_steps.py`), each named explicitly. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 2: Remove the carve (native)

**Files:**
- Delete:
  - `native/src/scenegraph/{include/scenegraph,src}/hull_carve.*`;
  - `native/src/renderer/{include/renderer,}/instance_field_cache.*`;
  - `breach_pass.*`;
  - `shaders/breach.frag`;
  - the Damage1-4 frame loading;
  - the voxel field atlas, field brush, `hull_connectivity` and `sphere_mesh`, ONLY if they have no other consumer;
  - the hull-volume `.dhv` pipeline ONLY if no non-carve consumer remains (check first);
  - every test that only tests these.
- Rename:
  - `CarveFieldCache` → `HullFillCache`, in the files and every use;
  - `shaders/breach.vert` → `shaders/hull_interior.vert`, with its embed name;
  - `find_base_texture_id` moves to a small `renderer/model_textures.{h,cc}`.
- Modify:
  - `native/src/scenegraph/include/scenegraph/instance.h`: drop `carve`.
  - `native/src/renderer/frame.cc`, `frame.h`: carve uniforms, `carve_fill_entry`, `submit_carve_stencil`, `dauntless_hull_damage::enabled()`.
  - `native/src/host/host_bindings.cc`:
    - carve bindings;
    - `space.carve_stencil` / `space.breach` scopes;
    - `g_breach_pass`, `g_instance_field_cache`;
    - re-gate venting and debris on `breach_events.count() > 0` only;
    - gate `space.hull_interior` on the fill cache.
  - `native/src/renderer/shaders/opaque.frag`: remove `hull_cut_at`, `u_carve_*`, `u_carve_invert`, `u_hull_field*`, `hull_field_slice` and the carve-clip block in main.
  - CMake lists.
- Test:
  - `native/tests/renderer/plating_render_test.cc`: add `UndamagedHullUnchangedByCarveRemoval`.
  - Delete or retarget `HullClipTest`, `HullFieldClip*`, `BreachPass*` and the carve-field tests.

**Interfaces:**
- `UndamagedHullUnchangedByCarveRemoval`: before any edit, render the Ambassador undamaged through `submit_opaque_in_pass` with a fixed camera and lighting. After the removal, the same render matches it byte for byte. *(As built: the reference was first committed as `native/tests/renderer/data/undamaged_ambassador_ref.bin`, then replaced in Task 9a by a 64-bit FNV-1a hash of the read-back buffer held in the test (Ruling 3: the bytes were BC-derived pixels). The `.bin` is deleted, but it remains in branch history at `d21f0188a`: a squash decision for Mark at merge.)*
  - If the PNG cannot be stable across this Mac's driver, use a per-channel tolerance of ±1 and say so.
- `HullFillCache` keeps `prefetch`, `get_for_source` (non-blocking), `put_for_source` and `volume_for_source`, with the same behaviour.

- [ ] **Step 1: Capture the undamaged reference** with the current build, and commit it with the test. The test passes now.
- [ ] **Step 2: Remove and rename.** Reconfigure and build every target.
- [ ] **Step 3: Run** `PlatingRender*:PlatingDamage*:HullInterior*:UnevenBreach*:PartSeverance*:ScuffTest.*:DecalRenderTest.*:FrameTest.*:Shader*:Pipeline*` plus the scenegraph `HullDamage*:DamageDecal*` filter. Expect PASS. Confirm that `grep -rn "carve\|breach_pass\|InstanceFieldCache\|hull_field" native/src` returns only intended survivors, and list them in the report.
- [ ] **Step 4: Run** the Task 1 pytest list again, plus `tests/host/test_hull_damage_bindings.py` and `tests/host/test_render_space_feeds.py`. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 3: Damage moves with articulated parts

**Files:**
- Modify:
  - `native/src/scenegraph/include/scenegraph/hull_damage.h`: `HullDamageRecord::node` (int, −1 body).
  - `native/src/host/host_bindings.cc`: both wear bindings take an optional `node_name: str = ""` and resolve the index with `resolve_overridden_node` / the model's node list. They map the point and normal into that node's rest frame through `rest_corrections`. Per-node rest fixes come from `compose_node_worlds`.
  - `engine/host_io.py`, `engine/appc/hull_wear.py`, `engine/appc/internal_blast.py`: attribute each hit with `part_severance.part_for_live_point` (ship units) and pass the node name.
  - `native/src/renderer/frame.cc`: remove the articulated whole-list fallbacks in `plating_mesh_records_for` / per-mesh subsets. Per-mesh subsets use rest-frame AABBs, which they already do.
  - `native/src/renderer/shaders/opaque.frag` (PLATING): every plating evaluation uses `p_rest = (u_node_rest_fix * vec4(p_body, 1)).xyz` and `n_rest = mat3(u_node_rest_fix) * n_body`. This covers the near test, wear, hole, part, hidden part, apply_plating and the soot weight. The view vector also goes into the rest frame for the plating marches.
  - `native/src/renderer/hull_interior_pass.cc`, `shaders/hull_interior.vert` / `.frag`: per mesh, upload `u_node_rest_fix` and transform `v_body_pos` and the camera ray into the rest frame.
- Test: `native/tests/renderer/plating_render_test.cc`, `hull_interior_test.cc`, `native/tests/scenegraph/hull_damage_test.cc`, `tests/host/test_hull_damage_bindings.py`, `tests/unit/test_hull_wear.py`

**Interfaces:**
- **Store merging.** Records of different `node` never merge. Add a store test.
- **Severance stays off for rigged ships** through `after_wear`'s rig gate. Unchanged.

- [ ] **Step 1: Write the failing tests:**
  - `DamageFollowsAnArticulatedNode` (GL), on a two-node model:
    - hit node 1 at rest;
    - pose node 1 (rotate 30° and translate);
    - the cut hole and its interior pixel move with the node. The hole's screen position follows the posed node.
    - the unposed node is unchanged.
  - `RecordsOnDifferentNodesNeverMerge` (scenegraph).
  - `test_wear_hit_on_a_posed_part_records_its_node` (host / pytest).
- [ ] **Step 2: Reconfigure, build, run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the Task 2 GL filter, the scenegraph filter and the pytest files. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 4: Structure parts at load, cached on disk

**Files:**
- Modify:
  - `native/src/renderer/structure_parts_cache.{h,cc}`: add a disk read/write on the worker.
  - `native/src/host/host_bindings.cc`: `prefetch_structure_parts(handle)` and `structure_parts_set_cache_root(path)`.
  - `engine/renderer.py`, `engine/host_io.py` and their manifests.
  - `engine/paths.py`: `structure_parts_cache_root()` = `cache_dir() / "structure_parts"`.
  - `engine/appc/hull_volume.py` `prewarm_for_model` (or its successor after Task 1) and `engine/host_loop.py` (the boot push, plus the prefetch at realize and in the warp preload, beside `prefetch_hull_fill`).
- Create: `native/src/voxel/{include/voxel,src}/structure_parts_io.*` (format read/write; add it to CMake).
- Test: `native/tests/voxel/structure_parts_io_test.cc` (new), `tests/unit/test_hull_volume_prewarm_model.py` (or its successor), `tests/unit/test_install_write_guard.py` (it must keep passing)

**Interfaces:**
- **The file.** `<root>/<fnv1a64 hex of the source file bytes>-v<kStructurePartsVersion>.sps`, where `kStructurePartsVersion` starts at 1.
  - **Layout:** magic `"SPS1"`, version, dims (3 × i32), origin (3 × f32), cell (3 × f32), label count, then RLE labels as (i16 value, u32 run) pairs, then part count and the parts' fields. Little-endian. A trailing FNV-1a 64 of the payload follows.
  - **The source hash** is of the NIF on disk (`assets::split_hull_source` path; `fnv1a64_hex`).
  - **Reading.** A bad magic, version or checksum, or a short read, is ignored: detect, then rewrite.
  - **Writing.** Write to `<file>.tmp` and rename. A write failure prints `[dauntless] could not write <path>: <why>` once per path; share the existing helper rather than copying it.
- `voxel::write_structure_parts(path, seg)` / `std::optional<StructureSegmentation> read_structure_parts(path)`.

- [ ] **Step 1: Write the failing tests:**
  - `RoundTripsASegmentation`;
  - `CorruptCacheFileIsRebuilt` (bad checksum, truncated, wrong version → nullopt);
  - `WriteFailureIsReportedOnce`;
  - pytest: realize / prewarm calls `prefetch_structure_parts` with the handle; the boot push calls `structure_parts_set_cache_root` with `paths.structure_parts_cache_root()`.
- [ ] **Step 2: Build and run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new and touched tests, plus `PartSeverance*:PlatingRender*` and the install-write guard. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 5: Shadows, cloak and dead chunks

**Files:**
- Create: `native/src/renderer/shaders/shadow_parts.vert` / `.frag`, a part-mask variant. The vert passes `p_rest`; the frag holds `plating_part` (a copy, labelled as a twin of opaque.frag's) and one discard.
- Modify:
  - `native/src/renderer/frame.cc` `submit_shadow_depth`: instances with `severed_parts != 0` or `shown_parts != 0` draw with the variant, with parts, masks and rest fixes uploaded. Remove the chunk skip.
  - `cloak_pass.cc`: skip chunks.
  - `part_severance_check.cc` / the binding: chunk `emissive_scale = 0` at spawn.
  - `pipeline.{h,cc}` and CMake.
- Test: `native/tests/renderer/plating_render_test.cc` (or a shadow test file)

- [ ] **Step 1: Write the failing tests:**
  - `ShadowHonoursThePartMask`: the parent's depth has no texels from its hidden part; the chunk's depth has texels only from its shown parts.
  - `CloakSkipsChunks`.
  - `SeveredChunkIsDark`: `emissive_scale == 0`.
- [ ] **Step 2: Reconfigure, build, run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the Task 2 GL filter plus `Shadow*:Cloak*`. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 6: Lights and emitters on a lost part go out

**Files:**
- Modify:
  - `native/src/host/host_bindings.cc`: `instance_severed_parts(iid) -> int`, read-only.
  - `engine/host_io.py`.
  - `engine/host_loop.py`: `_part_pose_at` returns `_PART_SEVERED` when the point's `structure_part_at` bit is set in `instance_severed_parts`. That covers running lights and emitter lights.
  - `engine/appc/hull_breakup.py`: on spawn, silence the particle emitters of subsystems inside the chunk's parts, mirroring `part_severance._silence_emitters_on`.
- Test: `tests/unit/test_severed_structure_part_lights.py` (new)

- [ ] **Step 1: Write the failing tests** (`LightsOnALostPartGoOut` and the emitter silencing), using fake host_io masks and positions.
- [ ] **Step 2: Run.** Expect FAIL.
- [ ] **Step 3: Implement.** Rebuild `dauntless` and `_dauntless_host`.
- [ ] **Step 4: Run** the new file plus the running-light and emitter tests (find them). Expect PASS.
- [ ] **Step 5: Commit.**

### Task 7: Molten rims on fresh tears

**Files:**
- Modify:
  - `native/src/renderer/frame.cc` `upload_plating`: `u_rim_count`, `u_rim_a[4]` (centre.xyz, radius) and `u_rim_b[4]` (age, _, _, _), from the four freshest `breach_events` with age < `kRimLife`, in the rest frame (body frame for node −1).
  - `hull_interior_pass.cc`: the same uniforms.
  - `opaque.frag` (PLATING): the torn rim (`under_glow`) and the far-wreck rim add `blackbody(0.55 + 0.35·heat)·heat·1.5`, where heat = (1 − age/kRimLife) × (1 − smoothstep(r, 3r, distance)).
  - `hull_interior.frag`: the plate char-edge glow takes the same heat.
- Test: `plating_render_test.cc`, `hull_interior_test.cc`

- [ ] **Step 1: Write the failing tests:**
  - `FreshTearRimGlows`: the rim pixel is redder at age 0 than at age kRimLife + 1.
  - `OldTearsStayCold`: an event older than kRimLife adds nothing.
- [ ] **Step 2–4:** Reconfigure, build and run the Task 2 GL filter. Expect FAIL, then PASS.
- [ ] **Step 5: Commit.**

### Task 8: Hull damage tuning in Developer Options

**Files:**
- Modify:
  - `native/src/host/host_bindings.cc`: `plating_param_defaults() -> list[float]` (kParamCount values from the C++ defaults).
  - `engine/appc/plating_dials.py`: `DEFAULTS` stays as the headless fallback. At register it reads the native defaults when available.
  - `engine/ui/developer_options_panel.py`, `native/assets/ui-cef/js/developer_options.js`: a "Hull damage" section of value-cycling rows (the `_doValueRow` pattern), each cycling through 5 presets around the default. It covers:
    - strip, breach and deck-break wear;
    - toughness spread and lumps;
    - soot;
    - `hull_wear.PHASER_RATE` and `COLLISION_MIN_HULL_DAMAGE`;
    - the death size tiers' big-tier chance;
    - the interior toggle;
    - the rooms near distance (`InteriorPolicy::near_gu`, which needs a setter binding);
    - "Reset hull damage dials".
- Test: `tests/host/test_plating_defaults_drift.py` (new, `plating_dials.DEFAULTS == plating_param_defaults()` in DIAL_ORDER), `tests/ui/` (find the developer-options panel tests; add row and action tests)

- [ ] **Step 1: Write the failing tests:** the drift test, the panel rows present only under `--developer`, an action cycling a value pushes it, and reset restores defaults.
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS), rebuilding `_dauntless_host`.
- [ ] **Step 5: Commit.**

### Task 9: Docs and carry-over minors

**Files:**
- Modify:
  - `CLAUDE.md`: a new row "Layered hull damage" covering:
    - files, the four phases' mechanisms and the dials;
    - Damage Preview knobs `FIRST_S`/`SEED`;
    - the perf rule;
    - the opaque.frag driver rules;
    - "no merge to main without Mark".

    Also correct the "DamageTool & hull-damage gaps", "Rock class" and "Collision scuff decals" rows. Keep the CLAUDE.md style: one dense row.
  - `docs/reference/engine/damagetool-and-hull-damage-gaps.md`: a "Superseded" header pointing at the layered docs.
  - `docs/superpowers/specs/2026-10-21-layered-hull-damage-production-design.md`: a status line marking it implemented.
- Carry-overs, each with its test:
  - the far-rock test pins rock albedo vs wreck paint (lower brightness bound);
  - a forced-merge `HullDamageAddResult` scenegraph test;
  - `PartSeverance.SplitKeepsAnUnhideablePartInTheConnectivity` can no longer fail, because the I4 early return fires with an empty `DamageList`. Break one far unlabelled voxel so the flood runs, then mutation-check it.
  - Piece size, centroid and bounds include only the voxels of member parts (phase-3 review minor).
- Test: the two tests above. Docs need no tests beyond `tests/docs/test_doc_consistency.py`, if it covers CLAUDE.md; run it.

- [ ] **Steps:** write the two tests (they should pass; mutation-check one), edit the docs, run the doc consistency test, commit.

### Task 10: Final measurement and the live-check list

**Files:**
- Modify: `docs/reference/engine/perf-register.md` (new C-/SIG- rows; the P-12 verdict).
- Create: `docs/superpowers/specs/2026-10-22-layered-damage-live-check.md` (the list for Mark).

- [ ] **Step 1: Captures (machine idle).**
  - DP with `DAUNTLESS_DAMAGE_PREVIEW_FIRST_S=20`, `DAUNTLESS_DAMAGE_PREVIEW_SEED=7`, at the default distance and at 1.5 GU.
  - CPU-only and GPU-focus (`space.opaque,space.hull_interior`).
  - One more run where a part severs, if DP's death severs one. Read `hb.split_parts`.
- [ ] **Step 2: Record:**
  - the ratios (alive ≤ 2× undamaged);
  - the dying window against the legacy death (SIG-090 / SIG-098);
  - the severed-ship cost;
  - `hb.split_parts`;
  - the P-12 verdict.
- [ ] **Step 3: Write the live-check list.** Use the phase-3 final review's list, updated for phase 4: articulated damage, rims, dark chunks, shadows, the Developer Options section, the stock look unchanged.
- [ ] **Step 4: Commit.**
