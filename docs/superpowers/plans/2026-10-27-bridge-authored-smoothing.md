# Bridge Authored Smoothing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The hard/soft edge smoothing Mark authors in Blender on DBridge objects becomes the game's hard/soft decision for those edges.

**Architecture:** The diff tool reads per-corner `vn` from the edit OBJ, classifies each two-face edge hard or soft, maps it to the shape's FINAL vertex indices (via the loader-applied geometry fix), and writes a new `smoothing` key (binary "BSM1", base64) into the mesh fix. The loader validates it and attaches it to the shape's `NiTriShapeData` in memory; `model_build` hands it to the joint interior normal generator, which lets authored flags decide edges inside a shape, keeps the 40° rule elsewhere, and never lets a cross-shape join merge corners an authored hard edge separates. A new host binding reports the generator's outcome per authored edge so the diff's verifier can refuse a mismatch.

**Tech Stack:** Python 3 (tools/shape_diff, pytest), C++20 (native/src/assets, nif, gtest), pybind11 (`_dauntless_host`).

**Spec:** `docs/superpowers/specs/2026-10-27-bridge-authored-smoothing-design.md` (read it first; it extends `2026-10-09-bridge-shape-diff-design.md` §6/§7/§11).

## Global Constraints

- Work in a worktree on branch `feat/bridge-authored-smoothing` from `main`. Shared checkout: never `git checkout -- / restore / stash / clean / reset --hard / add -A / add .`; stage explicit paths. Tell every subagent the same.
- Focused tests only (the files named per task). Never run whole suites or `scripts/check_tests.sh`.
- Build: `cmake -B build -S . && cmake --build build -j` from the worktree root; never from `native/`; never change `CMAKE_BUILD_TYPE`. C++ edits need a rebuild before any Python test touching `_dauntless_host`.
- Payload is index-only: no position, normal or other value from a NIF or Mark's OBJ is encoded. Mark's OBJs (`~/Documents/dauntless-artwork/Dbridge/`) never enter the repo or a test.
- Fix file stays `"format": 1`; older fixes without `smoothing` load byte-identically; BSD1/BSD2 decoding unchanged.
- Shapes without a smoothing record, and ship (non-interior) loads, produce bit-identical normals to today.
- Loader contract: any invalid smoothing record → whole fix refused (warn once, original NIF), file untouched.
- Python and C++ agree on one hand-built golden blob (Task 2 / Task 3).
- Never commit a regenerated `native/assets/mesh_fixes/dbcdbd4a43dc5a56.json` before Mark's in-game check.

## Review Focus

1. **Edge split by T-junction repair** inside a recorded shape: its pieces must keep the authored flag (hard stays hard). Test in Task 4.
2. **Cross-shape join chaining past a hard edge**: two faces of shape A split by an authored hard edge, both meeting shape B under 40° at the shared vertex, must stay apart. Test in Task 4.
3. **Authored soft edge over a stock exporter "twin" split** (`is_twin`): authored soft must join. Test in Task 4.
4. **Smoothing record for a block the geometry diff skipped/excluded/deleted**: no record is written for it (its edit geometry doesn't match the applied shape). Test in Task 6.
5. **Edit object exported without normals**: no record, block unchanged from today. Test in Task 1 and Task 6.

---

### Task 1: Read corner normals and classify edges (Python)

**Files:**
- Modify: `tools/shape_diff/obj_io.py` (`ObjMesh`, `read_objects`)
- Create: `tools/shape_diff/smoothing.py`
- Test: `tests/tools/test_shape_diff_smoothing.py` (new)

**Interfaces:**
- Produces: `ObjMesh.face_normals: list` — parallel to `faces`; per face a list of per-corner normals as BC-frame tuples (`frames.obj_to_bc`, like positions) or `None` when the corner has no `vn`. Empty for hand-built meshes.
- Produces: `smoothing.edge_flags(mesh: ObjMesh) -> dict | None` — `None` when any corner of the mesh lacks a normal (object not authored). Else `{(va, vb): EdgeFlag}` for every OBJ-local edge (`va < vb`) used by exactly two faces; `EdgeFlag` is a frozen dataclass `(hard: bool, same_a: bool, same_b: bool)` where `same_x` = the two faces' corner normals at vertex `x` agree within `NORMAL_TOL = 1e-4` per component, and `hard = not (same_a and same_b)`.

- [ ] **Step 1: Write the failing tests** in `tests/tools/test_shape_diff_smoothing.py`, writing tiny OBJ text to `tmp_path` (with an `.mtl` beside it; `read_objects` requires it):
  - `test_reader_keeps_corner_normals`: a two-triangle quad with `v/vt/vn` corners → `face_normals` has 2 entries of 3 tuples; an `f v/vt` face → corners `None`.
  - `test_shared_normals_make_a_soft_edge`: quad, both faces use the same `vn` at the shared vertices → one two-face edge, `hard False, same_a True, same_b True`.
  - `test_split_normals_make_a_hard_edge`: same quad, faces use different `vn` values at both shared vertices → `hard True, same_a False, same_b False`.
  - `test_hard_edge_ending_in_a_smooth_fan`: three faces around a vertex where the two faces of edge (0,1) disagree at vertex 1 only → `hard True` with one `same` True and the other False.
  - `test_no_vn_means_not_authored`: same quad with `f v/vt` → `edge_flags(...) is None`.
  - `test_open_and_three_face_edges_are_not_flagged`: boundary edges and an edge shared by 3 faces are absent from the dict.

- [ ] **Step 2: Run** `uv run pytest tests/tools/test_shape_diff_smoothing.py -v` — expect FAIL (`face_normals` / module missing).

- [ ] **Step 3: Implement.** In `read_objects` collect `vn` lines like `vt` (global list, negative indices allowed), convert with `frames.obj_to_bc`, and append each face's corner normals to `current.face_normals` alongside `faces`. Face tuples stay `(local, uv)` — `match.py` unpacks them. Write `smoothing.edge_flags`.

- [ ] **Step 4: Run** the same command — expect PASS; also `uv run pytest tests/tools/test_shape_diff.py -v -k "not dbridge and not DBRIDGE"` stays green (reader change must not disturb the diff).

- [ ] **Step 5: Commit** `tools/shape_diff/obj_io.py tools/shape_diff/smoothing.py tests/tools/test_shape_diff_smoothing.py` — `feat(shape-diff): read corner normals and classify edges hard/soft`.

### Task 2: Smoothing records and the BSM1 encoder (Python)

**Files:**
- Modify: `tools/shape_diff/smoothing.py`, `tools/shape_diff/payload.py`
- Test: `tests/tools/test_shape_diff_smoothing.py`

**Interfaces:**
- Consumes: `edge_flags` (Task 1).
- Produces: `smoothing.records(applied_shapes: list[dict], edit_meshes: dict[int, ObjMesh]) -> list[dict]` — `applied_shapes` is `_dauntless_host.nif_shapes(path, fix_json)` output (model-space `vertices`, `block`); `edit_meshes` maps block → edit mesh for blocks to record. One record per block whose `edge_flags` is not None, sorted by block: `{"block": int, "vertex_count": len(applied vertices), "hard": sorted [(a, b)], "soft": sorted [(a, b)], "ends": {(a, b): (same_at_a, same_at_b)}}` with `a < b` FINAL vertex indices. `ends` is for the verifier, never encoded.
- Produces: `payload.encode_smoothing(records) -> bytes`, `payload.encode_smoothing_b64(records) -> str`.

BSM1 layout (little-endian; spec it in the shape-diff spec in Task 7):
```
char[4] "BSM1"; u16 shape_count
per shape: u32 block; u16 vertex_count; u16 n_hard; u16 n_soft;
           n_hard × {u16 a, u16 b}; n_soft × {u16 a, u16 b}     (a < b, ascending)
```

- [ ] **Step 1: Write the failing tests:**
  - `test_smoothing_payload_matches_cpp_golden`: `encode_smoothing_b64([{"block": 7, "vertex_count": 4, "hard": [(0, 1)], "soft": [(0, 2), (1, 2)]}, {"block": 12, "vertex_count": 3, "hard": [], "soft": []}]) == "QlNNMQIABwAAAAQAAQACAAAAAQAAAAIAAQACAAwAAAADAAAAAAA="` (38 bytes).
  - `test_encoder_refuses_overflow_and_bad_pairs`: a count > 65535, `a >= b`, and an index ≥ `vertex_count` each raise `ShapeDiffError`.
  - `test_records_map_edges_to_final_indices`: a synthetic applied shape whose vertices include two copies at one position (indices 2 and 5) → the edge maps to the LOWEST index; positions off by under 1.5/1024 per coordinate still map.
  - `test_records_refuse_an_unmatched_vertex`: an edit vertex with no applied vertex within tolerance → `ShapeDiffError` naming the block.
  - `test_records_refuse_conflicting_flags`: two OBJ edges landing on one final pair with different `hard` → `ShapeDiffError`.
  - `test_object_without_normals_gets_no_record`.

- [ ] **Step 2: Run** `uv run pytest tests/tools/test_shape_diff_smoothing.py -v` — FAIL.

- [ ] **Step 3: Implement** `records` (nearest applied vertex within 1.5/1024 per coordinate, ties → lowest index; skip an edge whose ends map to the same index) and the encoder (all errors as `ShapeDiffError`, reuse `_u16`).

- [ ] **Step 4: Run** — PASS.

- [ ] **Step 5: Commit** `feat(shape-diff): smoothing records + BSM1 encoder`.

### Task 3: Loader — parse, validate, attach (C++)

**Files:**
- Modify: `native/src/nif/include/nif/block.h` (`NiTriShapeData`)
- Modify: `native/src/assets/include/assets/mesh_fix.h`, `native/src/assets/src/mesh_fix.cc`
- Create: `native/tests/assets/cpu/mesh_fix_smoothing_test.cc`; register it in `native/tests/assets/CMakeLists.txt` beside `cpu/mesh_fix_texture_test.cc`

**Interfaces:**
- Produces (nif): `struct AuthoredEdges { std::vector<std::array<std::uint16_t, 2>> hard, soft; };` and `std::optional<AuthoredEdges> authored_edges;` on `NiTriShapeData` — in-memory only, never parsed from or written to a NIF; comment says so.
- Produces (assets): `struct MeshFixSmoothing { std::uint32_t block = 0; std::uint16_t vertex_count = 0; nif::AuthoredEdges edges; };`, `MeshFix::smoothing` (vector), `std::optional<std::vector<MeshFixSmoothing>> decode_smoothing(std::string_view bytes, std::string* error);`
- `parse_mesh_fix` accepts `"smoothing"` (base64 string) and a fix holding only it.

- [ ] **Step 1: Write the failing gtests** (synthetic `nif::File` helpers from `mesh_fix_shape_edit_test.cc`):
  - `MeshFixSmoothing.DecodesTheGoldenBlob` — the Task 2 golden string decodes to blocks 7/12, counts and pairs as encoded.
  - `MeshFixSmoothing.DecodeRefusesBadMagicTruncationTrailingBytes`.
  - `MeshFixSmoothing.ParseAcceptsASmoothingOnlyFix`.
  - `MeshFixSmoothing.AttachesEdgesAfterShapeEdits` — a fix with a shape edit adding 1 vertex plus a smoothing record whose `vertex_count` = orig + 1 → `authored_edges` set with those pairs.
  - Refusals, each leaving the file unchanged and returning a non-empty reason: block out of range / not a `NiTriShape`; data has authored normals; `vertex_count` ≠ final count (orig + this fix's added vertices); index ≥ `vertex_count`; `a >= b` or not ascending; a pair in both lists; block listed twice; block's data used by a merge.

- [ ] **Step 2: Build and run** `cmake --build build -j && ctest --test-dir build -R MeshFixSmoothing --output-on-failure` — FAIL.

- [ ] **Step 3: Implement** decode (mirror `decode_shape_edits`' style), parse, validation inside `apply_mesh_fix` before any mutation (same all-or-nothing as §7), attach after shape edits.

- [ ] **Step 4: Run** the same `ctest -R MeshFixSmoothing`, plus `-R "MeshFix"` to keep the existing fix tests green — PASS.

- [ ] **Step 5: Commit** `feat(mesh-fix): BSM1 smoothing records attached to shape data`.

### Task 4: Normal generation honours authored edges (C++)

**Files:**
- Modify: `native/src/assets/src/normal_gen.h`, `native/src/assets/src/normal_gen.cc`
- Test: `native/tests/assets/cpu/normal_gen_test.cc`

**Interfaces:**
- Consumes: `nif::AuthoredEdges` (Task 3).
- Produces: `NormalGenShape::authored` (`const nif::AuthoredEdges* = nullptr`, indices into that shape's `mesh->vertices` as given, i.e. before repair).
- Produces: `struct SmoothingReport { struct Edge { std::uint32_t shape; std::uint16_t a, b; bool found, joined_a, joined_b; }; std::vector<Edge> edges; };` and `void generate_normals_across_shapes(std::vector<NormalGenShape>&, float crease_deg, SmoothingReport* report = nullptr, bool authored_joins_hard = false);` — one report row per authored edge, per shape in input order, hard then soft in record order. `authored_joins_hard` is spec §3.4's switch: true → an edge between two different shapes, at least one recorded, never unites. Task 5 passes a `constexpr bool kAuthoredShapeJoinsHard = false;` declared beside `kSetNormalCreaseDeg` in `model_build.cc`.

Rules (spec §3.3):
- A triangle's shape is `origins[first corner].shape` (as the split-back loop uses).
- Authored segments: each pair's two vertices taken to shared space BEFORE `repair_t_junctions_impl`. After repair, an edge between two faces of the same recorded shape matches a segment if its endpoints' position keys equal the segment's, else if both endpoints lie on the segment (distance to the line ≤ 1e-5 × segment length, parameter in [0, 1]) — so T-junction pieces inherit.
- Matched hard → never united. Matched soft → united whatever the angle and despite `is_twin`. Unmatched → today's 40°/twin rule.
- Phase 1: unite only edges whose two faces are in the same recorded shape. Then, for every matched hard edge and each endpoint, if the two faces' corners have different roots, forbid that root pair. Phase 2: every other edge with today's rule, skipping a union whose roots are forbidden; on union, merge the forbidden sets onto the surviving root.
- Shapes with `authored == nullptr` and no report → identical output to today.
- Report: `found` = the authored edge (or the piece touching each endpoint) has exactly two face uses; `joined_x` = those faces' corners at endpoint x share a root after phase 2.

- [ ] **Step 1: Write the failing gtests:**
  - `NormalGenAuthored.HardEdgeBelowCreaseStaysHard` — two coplanar-ish faces (10° fold) with an authored hard edge → split normals; `report` hard, `found`, `joined_a == joined_b == false`.
  - `NormalGenAuthored.SoftEdgeAboveCreaseIsSmooth` — 90° fold authored soft → one shared normal.
  - `NormalGenAuthored.SoftEdgeOverridesTwinSplit` — stock twin vertices (identical attributes) on the edge, authored soft → joined.
  - `NormalGenAuthored.TJunctionPiecesInheritHard` — a second shape's vertex splits the authored hard edge → both pieces stay hard.
  - `NormalGenAuthored.CrossShapeJoinCannotUndoHard` — Review Focus 2 → shape A's two faces keep different normals at the shared vertex; `joined_* == false`.
  - `NormalGenAuthored.UnrecordedShapesUnchanged` — the existing two-shape fixture with `authored` null on both produces byte-identical normals with and without a `report` pointer.
  - `NormalGenAuthored.EdgeNotInRecordUsesCrease` — a recorded shape whose game-only internal edge (not in either list) follows 40°.
  - `NormalGenAuthored.JoinsHardSwitch` — a 10° join between a recorded and an unrecorded shape unites with `authored_joins_hard = false` and stays split with `true`.

- [ ] **Step 2: Build and run** `ctest --test-dir build -R "NormalGen" --output-on-failure` — new ones FAIL.

- [ ] **Step 3: Implement** in `smooth_normals_impl` (it receives the authored lookup and report via `VertexChannels` or extra params; `generate_smooth_normals` passes none).

- [ ] **Step 4: Run** `ctest --test-dir build -R "NormalGen" --output-on-failure` — all PASS (existing ones unchanged).

- [ ] **Step 5: Commit** `feat(normal-gen): authored hard/soft edges, hard survives joins, outcome report`.

### Task 5: Plumb through model_build + host binding (C++)

**Files:**
- Modify: `native/src/assets/src/model_build.h` (`ModelBuildContext::smoothing_report`, `SmoothingReport*`, default nullptr), `native/src/assets/src/model_build.cc` (`PendingMesh` carries `data->authored_edges` pointer into `NormalGenShape::authored`; pass the report)
- Modify: `native/src/host/host_bindings.cc` (new `set_smoothing_report`)
- Test: `native/tests/assets/cpu/model_build_test.cc`; `tests/host/test_nif_shapes_binding.py`

**Interfaces:**
- Produces: `_dauntless_host.set_smoothing_report(abs_path: str, fix_json: str) -> list[dict]` — parse the NIF, `apply_mesh_fix`, `build_model` with `generate_missing_normals = true`, stub texture/mesh uploaders (the `cache_test.cc` pattern; no GL), and return one dict per report row: `{"block": int, "a": int, "b": int, "found": bool, "joined_a": bool, "joined_b": bool}` (`block` = the shape's NIF block, not the NormalGen index). `RuntimeError` with the loader's reason when the fix is refused; `None` when the file is missing or unparsable (as `nif_shapes`).

- [ ] **Step 1: Write the failing tests:**
  - gtest `ModelBuildAuthored.InteriorBuildUsesAttachedEdges` — synthetic file, `authored_edges` set on a shape's data, `generate_missing_normals = true` → a 10° authored hard edge renders split; the same build with `generate_missing_normals = false` ignores it.
  - pytest `test_set_smoothing_report_on_dbridge` (asset-backed; skip like the file's other DBridge tests when content is absent): a fix JSON built in the test with ONE synthetic smoothing record on a stock DBridge block (indices only — pick a block and an existing triangle's two vertex indices from `nif_shapes`, flag hard) → one row, `found True`, `joined_a`/`joined_b` False.
  - pytest `test_set_smoothing_report_refused_fix_raises` — a record with a wrong `vertex_count` → `RuntimeError`.

- [ ] **Step 2: Build, run** `ctest --test-dir build -R ModelBuildAuthored --output-on-failure` and `uv run pytest tests/host/test_nif_shapes_binding.py -v` — FAIL.

- [ ] **Step 3: Implement.** Confirm `build_mesh_cpu` keeps vertex `i` = data vertex `i` (it does today); assert it in the test rather than assume.

- [ ] **Step 4: Run** the same two commands — PASS.

- [ ] **Step 5: Commit** `feat(host): set_smoothing_report binding; model_build passes authored edges`.

### Task 6: Diff integration + verifier (Python)

**Files:**
- Modify: `tools/bridge_shape_diff.py` (`build_fix`, `make_fix_dict`, `main`, `_summary`)
- Modify: `tools/shape_diff/verify.py` (`check_smoothing`, `run_smoothing`)
- Test: `tests/tools/test_shape_diff_smoothing.py`

**Interfaces:**
- Consumes: Tasks 2 and 5.
- `build_fix(..., smoothing=None)` — `None` means "same as `verify`". When on: build the geometry fix as today; `applied = host.nif_shapes(path, fix_text(fix))`; `recs = smoothing.records(applied, edit meshes for every edit block NOT skipped, excluded or deleted)`; when `recs`, `fix["smoothing"] = payload.encode_smoothing_b64(recs)`; verify geometry as today with the full fix; then `verify.run_smoothing(nif_path, fix_text(fix), recs)`. Returns as today plus the records (`fix, edits[, skipped]` unchanged; expose records via `fix` + a new 4th return only if tests need it — prefer reading `fix`).
- `verify.check_smoothing(records, report_rows) -> int` — every recorded edge has a row with `found`, `joined_a == ends[...][0]`, `joined_b == ends[...][1]`; else `ShapeDiffError("verify: block N: edge a-b renders <soft|hard> at <end> where Blender shows <hard|soft>")`. Returns edges checked.
- `make_fix_dict` writes `shape_edits` only when there is geometry or nothing else at all; `main` treats a smoothing-only diff as a change (no "no changes" exit), and prints `smoothing: <S> shapes, <H> hard / <N> soft edges` plus `verified smoothing on <E> edges`.

- [ ] **Step 1: Write the failing tests:**
  - `test_check_smoothing_passes_matching_rows`, `test_check_smoothing_refuses_soft_where_blender_hard`, `test_check_smoothing_refuses_missing_row` (pure, synthetic rows).
  - `test_build_fix_writes_smoothing_for_an_authored_object` (asset-backed DBridge): take the tool's own export (`export` to `tmp_path`) as base; edit = the same OBJ with `vn` lines added to ONE object computed in the test from its own faces (flat per-face normals → every two-face edge hard) → `fix["smoothing"]` present, decodes to one record for that block, verification passes. No other block gets a record.
  - `test_no_record_for_skipped_or_deleted_blocks` (Review Focus 4): same setup plus `--delete` of another object and normals on it before deletion → no record for the deleted block.
  - `test_export_without_normals_writes_no_smoothing` (Review Focus 5): base = edit = the export → no `smoothing` key; existing `test_shape_diff.py` round-trip tests still pass.

- [ ] **Step 2: Run** `uv run pytest tests/tools/test_shape_diff_smoothing.py -v` — FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run** `uv run pytest tests/tools/test_shape_diff_smoothing.py tests/tools/test_shape_diff.py -v` — PASS.

- [ ] **Step 5: Commit** `feat(shape-diff): write and verify authored smoothing`.

### Task 7: Docs

**Files:**
- Modify: `docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md` — §6 (the `smoothing` key), §6.1 (BSM1 layout + golden), §7 (refusals from Task 3), §11.2 (working files now `~/Documents/dauntless-artwork/Dbridge/`), §11.3/§11.5 (smoothing lines in the dry run; the new verifier refusal and what to do: usually an edge Blender shows hard that a game-only edge joins — Merge by Distance or mark it), §11.4 (export with Normals ticked; Smooth by Angle / sharp marks are honoured, custom normals are not).
- Modify: `CLAUDE.md` — "Bridge shape diff" row: one clause on authored smoothing + spec path.
- Modify: `docs/superpowers/specs/2026-10-27-bridge-authored-smoothing-design.md` — "As built" note for any decision the builder made under §5.

- [ ] **Step 1:** Edit the three files.
- [ ] **Step 2:** `uv run pytest tests/docs/test_doc_consistency.py -v` — PASS.
- [ ] **Step 3: Commit** `docs(bridge): authored smoothing in the shape-diff spec and runbook`.

### Task 8: Regenerate the DBridge fix from Mark's latest export (controller, not a subagent)

Mark asked (2026-10-27): once built, update the DBridge with his latest `Dbridge_modified_and_enhanced_rexport.obj` (re-exported again since the design).

- [ ] **Step 1:** Rebuild in the worktree. Dry run:
  `uv run python -m tools.bridge_shape_diff diff ~/Documents/dauntless-artwork/Dbridge/Dbridge_unmodified_rexport.obj ~/Documents/dauntless-artwork/Dbridge/Dbridge_modified_and_enhanced_rexport.obj --partial`
  Add the `--delete` flags the object-set refusal asks for (round 8 used `--delete 84 --delete 90 --delete 340 --delete 343 --delete 361 --delete 364`); confirm each was deleted on purpose (runbook §11.5).
- [ ] **Step 2:** Compare the dry run's per-block summary with the committed fix (decode both payloads' block lists): every block in the committed fix is still present unless Mark removed that edit. Report any dropped block to Mark before writing. Read every `skipped` line.
- [ ] **Step 3:** `--write` (same flags) in the worktree. Ask Mark before launching anything; give him the plain launch command for the worktree build (`./build/dauntless --developer`), and point him at Developer Options → Lighting → Bridge Debug View (normals).
- [ ] **Step 4:** Only after Mark accepts in game: commit the fix (+ any new overlay textures) with explicit paths, add a §9 iteration row.
