# Hull Breach 2b — Dual-Contouring Interior — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 2a's see-through breaches + colored-cube splat with a real dual-contouring interior surface built from BC's fill field + plane palette — sharp hull-facet cross-sections, textured with triplanar `Damage.tga`, shown through the clipped holes.

**Architecture:** Decode the rest of the vox payload (plane palette + `bytes2` cell→plane index tree). A pure dual-contouring extractor turns the 0–127 fill (isovalue ≈63–64) into a mesh, using each surface cell's palette plane as the QEF Hermite constraint → sharp vertices. A per-instance carved copy of the fill is re-extracted on hit; the resulting interior mesh renders through the 2a fragment-clip holes with triplanar `Damage.tga`.

**Tech Stack:** C++17, OpenGL 4.1 / GLSL 330, glm, GoogleTest. Builds on the merged 2a + voxel foundation. **Read the format spec first:** `docs/original_game_reference/engine/nibinaryvoxeldata-format-v3.1.md` (§4 fill, §5 palette, §6 tree, §7 leaves, §10 extraction). Reference design: `docs/superpowers/specs/2026-06-17-hull-breach-2b-dual-contouring-interior-design.md`.

**Sequencing note:** The extractor is the novel risk, so Tasks 1–4 build and **validate it on static (uncarved) data** before any carve/render wiring (Tasks 5–7). Same "prove the core first" discipline as the decoder.

> **REFRAME (cleanroom round 3) — `bytes2` head-tree DROPPED, Path B adopted.**
> The cell→authored-plane head-tree descent (Task 2) proved hard (records are
> face-octant-major) and is **unnecessary**. We extract our **own** dual-contouring
> surface from the decoded fill + plane palette, choosing each surface cell's Hermite
> plane(s) as the **nearest palette plane(s) by point-to-plane distance** (`|n̂·p − d|`
> minimal). No tree, no leaf order; validated by **Galaxy IoU + eyeball**, not the
> byte-exact anchors. This same extractor generates `_vox` for mod ships.
> **Status:** Task 1 ✅ (container decode), Task 3 ✅ (QEF), Task 5a ✅ (`carve_sphere`).
> **Task 2 is DEFERRED** (nice-to-have for byte-faithful reads only — WIP committed,
> anchor test DISABLED). **Task 4 below is superseded by Path B** (nearest-palette-plane
> instead of the `PlaneIndexMap`); the implementer prompt carries the precise approach.

---

## File Structure
- `native/src/voxel/include/voxel/volume.h` — **modify**: add `planes` + `cell_plane` map (or a sibling `SurfaceData` struct) to the decoded data.
- `native/src/voxel/src/decode.cc` — **modify**: parse plane palette + `bytes2` (container) after the fill slab.
- `native/src/voxel/include/voxel/plane_index.h` + `src/plane_index.cc` — **create**: `bytes2` tree reader → cell→plane lookup.
- `native/src/voxel/include/voxel/dual_contour.h` + `src/dual_contour.cc` — **create**: QEF + DC extractor.
- `native/src/voxel/src/source_cache.cc` — **modify**: expose planes + cell→plane map per model.
- `native/src/scenegraph/.../hull_carve.h` — **modify**: per-instance carved scalar field (carve mutates fill).
- `native/src/renderer/breach_pass.{h,cc}` + `shaders/breach.{vert,frag}` — **modify/replace**: render the extracted interior mesh w/ triplanar `Damage.tga` (was: cube splat).
- `native/src/host/host_bindings.cc` — **modify**: carve updates the scalar field + triggers re-extract; load `Damage.tga`.
- `engine/appc/hull_carve.py` — **modify**: tone-down knobs.
- Tests under `native/tests/voxel/` and `native/tests/renderer/`.

---

## Task 1: Decode the plane palette + `bytes2` container (C++)

The 2a decoder unpacked only the fill slab; planes + `bytes2` remain in `raw_voxel_payload`. Parse the full container per format-spec §3/§5/§6.

**Files:**
- Modify: `native/src/voxel/include/voxel/volume.h` (add a `SurfaceData` struct), `native/src/voxel/src/decode.cc`
- Test: `native/tests/voxel/surface_decode_test.cc` (+ CMake)

- [ ] **Step 1: failing test** — `surface_decode_test.cc`, against Galaxy (golden from spec §11):
```cpp
#include <gtest/gtest.h>
#include <voxel/voxelize.h>   // from_nif_surface
#include <nif/file.h>
#include <nif/block.h>
#include <filesystem>
TEST(SurfaceDecode, GalaxyPaletteAndBytes2) {
    auto p = std::filesystem::path(OPEN_STBC_PROJECT_ROOT)/"game/data/Models/Ships/Galaxy/Galaxy_vox.nif";
    if (!std::filesystem::exists(p)) GTEST_SKIP() << "asset absent";
    auto f = nif::load(p);
    const nif::NiBinaryVoxelData* vd=nullptr;
    for (auto& b: f.blocks) if (auto* q=std::get_if<nif::NiBinaryVoxelData>(&b)) vd=q;
    ASSERT_NE(vd,nullptr);
    voxel::SurfaceData s = voxel::from_nif_surface(*vd);
    EXPECT_EQ(s.planes.size(), 3002u);
    for (auto& pl : s.planes) {                       // all unit normals (§5)
        float m = std::sqrt(pl.x*pl.x+pl.y*pl.y+pl.z*pl.z);
        EXPECT_NEAR(m, 1.0f, 1e-2);
    }
    EXPECT_EQ(s.trailer[3], 4u*10u);                  // 4*nz, §8
    EXPECT_GT(s.bytes2.size(), 0u);
}
```

- [ ] **Step 2: run, fail** — `cmake --build build -j voxel_tests` → no `SurfaceData`/`from_nif_surface`.

- [ ] **Step 3: implement.** In `volume.h` add:
```cpp
struct SurfaceData {
    std::vector<glm::vec4> planes;      // (n̂.xyz, d) Hesse form, GU (§5)
    std::vector<std::uint8_t> bytes2;   // index tree + leaf tail (§6/§7)
    std::array<std::uint32_t,5> trailer{};
};
```
In `decode.cc` add `voxel::SurfaceData from_nif_surface(const nif::NiBinaryVoxelData& vd)` (declare in voxelize.h): compute `L = 7*ceil(N/8)` (N=(nx-1)(ny-1)(nz-1)) to skip the fill slab in `vd.raw_voxel_payload`, then read `u32 numPlanes; Vector4[numPlanes]; u32 numBytes2; byte[numBytes2]; u32[5] trailer` (little-endian, per §3). Guard against truncation (return empty on size mismatch). Reuse the existing little-endian read helpers used by the fill decode.

- [ ] **Step 4: pass** — `cmake --build build -j voxel_tests && ctest --test-dir build -R SurfaceDecode --output-on-failure`.

- [ ] **Step 5: commit** — `git add native/src/voxel native/tests/voxel && git commit -m "feat(voxel): decode plane palette + bytes2 container"`

---

## Task 2: `bytes2` cell→plane index reader

Parse the `bytes2` tree (§6) into a queryable map: `(i,j,k) → [planeIndex...]` (leaf field 0, §7). Validate against the format spec's cross-reference anchors.

**Files:**
- Create: `native/src/voxel/include/voxel/plane_index.h`, `src/plane_index.cc`
- Modify: voxel CMake; Test: `native/tests/voxel/plane_index_test.cc`

- [ ] **Step 1: failing test** — anchors from spec §7/§11:
```cpp
#include <gtest/gtest.h>
#include <voxel/plane_index.h>
// ...load Galaxy, from_nif_surface -> s, dims (31,43,10)...
TEST(PlaneIndex, GalaxyAnchors) {
    // build the map from s.bytes2 + dims
    voxel::PlaneIndexMap m = voxel::build_plane_index(s.bytes2, {31,43,10}, s.trailer);
    EXPECT_EQ(m.first_plane(13,4,0), 2247);
    EXPECT_EQ(m.first_plane(13,5,1), 417);
    EXPECT_EQ(m.first_plane(7,2,0),  270);
}
```

- [ ] **Step 2: run, fail.**

- [ ] **Step 3: implement** per format-spec §6: top-level per-Z CSR (`u32[nz]` offsets, `trailer[3]=4·nz`), then recurse Z→Y→X over `node {u32 lo; u32 hi; u32 csrOffset[hi-lo+1]; u32 marker}` (marker `0x000N0000` = level tag) down to the 6-byte leaf run `{u16 planeIndex, u16 meshRefA, u16 meshRefB}`; `first_plane(i,j,k)` returns the first leaf's `planeIndex` (we ignore meshRefA/B). Build a flat `std::unordered_map<uint32_t /*flat idx*/, uint16_t>` (or `vector<int>` sized to the lattice, −1 = none) by walking the whole tree once. The anchor test is the gate: if descent is wrong, the anchors won't match — iterate the offset/base addressing until they do.

  **Fallback (if the tree descent proves intractable):** geometric palette matching — per surface cell, estimate the normal from the fill gradient and pick the palette plane best matching normal + `d≈n̂·pos` (the cross-reference method gave ≤0.02–4.3 GU residuals). Use this only if the tree resists; report which path you took. Sharp facets come from the palette either way.

- [ ] **Step 4: pass** — anchors match.

- [ ] **Step 5: commit** — `feat(voxel): bytes2 cell->plane index reader`

---

## Task 3: QEF solver (pure)

**Files:** create `native/src/voxel/include/voxel/dual_contour.h` + `src/dual_contour.cc`; test `native/tests/voxel/dual_contour_test.cc`.

- [ ] **Step 1: failing test** — three orthogonal planes meeting at a corner → that corner:
```cpp
#include <voxel/dual_contour.h>
TEST(QEF, ThreeOrthogonalPlanesGiveCorner) {
    std::vector<voxel::Plane> ps = {        // planes through (2,3,4)
        {{1,0,0}, 2.0f}, {{0,1,0}, 3.0f}, {{0,0,1}, 4.0f}};
    glm::vec3 v = voxel::solve_qef(ps, /*fallback=*/{0,0,0});
    EXPECT_NEAR(v.x,2.0f,1e-3); EXPECT_NEAR(v.y,3.0f,1e-3); EXPECT_NEAR(v.z,4.0f,1e-3);
}
TEST(QEF, UnderconstrainedFallsBackTowardSeed) {       // one plane: vertex on it, near seed
    std::vector<voxel::Plane> ps = {{{0,0,1}, 5.0f}};
    glm::vec3 v = voxel::solve_qef(ps, {1,1,1});
    EXPECT_NEAR(v.z, 5.0f, 1e-3);          // on the plane
}
```

- [ ] **Step 2: run, fail.**

- [ ] **Step 3: implement.** `struct Plane { glm::vec3 n; float d; };` `glm::vec3 solve_qef(const std::vector<Plane>&, glm::vec3 fallback)`: minimize Σ (n_i·v − d_i)² with Tikhonov regularization toward `fallback` (add small λ·I) for stability/under-constraint. Solve the 3×3 normal equations `(AᵀA + λI) v = Aᵀb + λ·fallback` with a glm 3×3 inverse (λ≈1e-3). Clamp the result to a sane bound if needed.

- [ ] **Step 4: pass.**  - [ ] **Step 5: commit** — `feat(voxel): QEF solver for dual contouring`

---

## Task 4: Dual-contouring extractor + validate on the Galaxy

**Files:** modify `dual_contour.{h,cc}`; test `native/tests/voxel/dual_contour_test.cc` (+ a real-data test).

- [ ] **Step 1: failing tests.** (a) synthetic: a small fill with a clear isosurface + a matching plane map → expected vertex count > 0 and vertices inside the grid. (b) real-data (GL-free, skip if asset absent): extract uncarved Galaxy → mesh; voxelize the mesh back and compare to the fill solid set (IoU) above a floor; dump an OBJ for eyeballing.
```cpp
TEST(DualContour, GalaxyReproducesHull) {
    // load Galaxy fill (VoxelVolume) + SurfaceData + PlaneIndexMap
    voxel::Mesh m = voxel::dual_contour(fill, /*isovalue=*/64, planes, indexMap);
    EXPECT_GT(m.positions.size(), 1000u);
    // sanity: all verts within the grid AABB
    // IoU(voxelize(m, fill grid), fill>=64) > 0.5   (DC of coarse data; floor, not perfection)
}
```

- [ ] **Step 2: run, fail.**

- [ ] **Step 3: implement** `voxel::Mesh dual_contour(const VoxelVolume& fill, int isovalue, const std::vector<glm::vec4>& planes, const PlaneIndexMap& idx)` per format-spec §10: for each cell straddling `isovalue` (a corner <iso, another ≥iso) place one vertex via `solve_qef` using the cell's palette plane(s) (`idx.first_plane` → `planes[...]` → `Plane{n̂, d}`; Hermite point = `d·n̂`), seeded at the cell-center GU (`aabbMin+(i+1,j+1,k+1)*cell`); normal = the plane n̂ (or averaged). Generate quads: for each grid edge with a sign change, connect the 4 adjacent cells' vertices (standard DC face generation). Output positions+normals+indices. If a straddling cell has no plane in the map, fall back to the fill-gradient normal (so the mesh stays watertight). Provide a debug `write_obj(mesh, path)`.

- [ ] **Step 4: pass + eyeball.** Run the real-data test; open the OBJ — it should read as the Galaxy hull with flat panels/edges. Tune isovalue/QEF λ if needed.

- [ ] **Step 5: commit** — `feat(voxel): dual-contouring extractor (sharp facets from plane palette)`

---

## Task 5: Per-instance carved scalar field + carve-on-hit

2a stored carve spheres only. 2b needs the carved 0–127 field to re-extract. Per damaged instance, keep a carved copy of the source fill; a hit subtracts a smooth radial falloff.

**Files:** modify `native/src/scenegraph/include/scenegraph/hull_carve.h` (+ src), `native/src/host/host_bindings.cc` (`hull_carve_add` also carves the field); test `native/tests/scenegraph/hull_carve_test.cc`.

- [ ] **Step 1: failing test** — carving reduces fill inside the sphere, smoothly:
```cpp
TEST(CarvedField, SubtractsSmoothFalloff) {
    voxel::VoxelVolume f; /* small solid field, all 127 */
    scenegraph::carve_sphere(f, /*center_body=*/{...}, /*radius=*/r);
    // center voxel -> 0; a voxel near the rim -> partial (between 0 and 127); outside -> 127
}
```

- [ ] **Step 2: run, fail.**  - [ ] **Step 3: implement** `scenegraph::carve_sphere(VoxelVolume& fill, glm::vec3 center_body, float radius)`: for voxels within `radius`, multiply/subtract by a smoothstep falloff (`fill *= smoothstep(0, radius, dist)` clamped to [0,127]) so the cut surface is smooth (§ design "smooth falloff"). Store a per-instance carved `VoxelVolume` (lazily copied from the model's source fill on first carve) on the carve field / instance. The existing `hull_carve_add` binding, in addition to adding the sphere (kept for the clip), applies `carve_sphere` to the instance's carved field and marks it dirty for re-extract.

- [ ] **Step 4: pass.**  - [ ] **Step 5: commit** — `feat(scenegraph): carved scalar field (smooth falloff) on hit`

---

## Task 6: Breach interior render (DC mesh, triplanar Damage.tga)

Replace the 2a cube-splat breach pass: extract the (carved) interior mesh, upload, render through the clipped holes with triplanar `Damage.tga` lit by the DC normals.

**Files:** modify `native/src/renderer/breach_pass.{h,cc}`, `shaders/breach.vert`, `shaders/breach.frag`; `native/src/host/host_bindings.cc` (load `Damage.tga`); test `native/tests/renderer/breach_pass_test.cc`.
**SHADER GOTCHA:** `cmake -B build -S .` (reconfigure) before building after any shader edit.

- [ ] **Step 1: failing test** — GL readback (skip headless), mirroring the 2a breach GL test: feed a small DC mesh, render through a hole, assert a non-background, `Damage.tga`-toned pixel. Plus a CPU test that the pass requests re-extract only for dirty instances.

- [ ] **Step 2: run, fail.**

- [ ] **Step 3: implement.** `BreachPass` now: per damaged instance, if its carved field is dirty, `dual_contour(...)` → mesh, upload to the instance's mesh VBO (cache; re-extract only on dirty). Draw the mesh (positions+normals) with `breach.vert/frag`: `breach.vert` transforms by `inst.world`, passes body-frame position + normal; `breach.frag` does **triplanar projection** of `u_damage_tex` (3 axis projections blended by `abs(normal)`), modulates by simple N·L lighting from the scene light + ambient, muted. Bind `Damage.tga` (load once in host init via the existing texture loader; `game/data/Textures/Effects/Damage.tga`). Depth-test ON. Remove the old cube-splat path (the `select_breach_voxels` splat). Keep gating on `dauntless_hull_damage::enabled()` and the GL-state restore (incl. `GL_DEPTH_TEST`).

- [ ] **Step 4: pass + manual.** GL test green; full renderer suite green (no regression).

- [ ] **Step 5: commit** — `feat(renderer): DC interior surface w/ triplanar Damage.tga (replaces cube splat)`

---

## Task 7: Tone-down (carve knobs + muted shading)

**Files:** modify `engine/appc/hull_carve.py`; `breach.frag` (muted) if not already; tests `tests/unit/test_hull_carve_mapping.py`.

- [ ] **Step 1: failing test** — assert the reduced knob values:
```python
def test_toned_down_radius():
    assert hull_carve.CARVE_RADIUS_SCALE <= 1.0     # was 1.5
    assert hull_carve.MIN_CARVE_HULL >= 60.0        # was 40 (carve less readily)
```

- [ ] **Step 2: run, fail.**  - [ ] **Step 3: implement** — lower `CARVE_RADIUS_SCALE` (e.g. 1.5→1.0), raise `MIN_CARVE_HULL` (40→60), keep `MIN_CARVE_RADIUS_GU`/`CARVE_EMIT_INTERVAL`; ensure `breach.frag` shading is muted (low saturation, moderate brightness). These are eye-calibration knobs — values above are the starting point, finalize against the manual check.

- [ ] **Step 4: pass.**  - [ ] **Step 5: commit** — `feat(damage): tone down breach size/frequency + muted interior`

---

## Task 8: End-to-end + manual verification

**Files:** create `docs/superpowers/notes/2026-06-17-hull-breach-2b-manual-verification.md`.

- [ ] **Step 1: full suites.** `cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure` and `bash scripts/run_tests.sh`. All green (GL tests may SKIP headless).
- [ ] **Step 2: manual (Mark drives).** Breach a Galaxy: confirm a **solid, sharp-faceted** interior cross-section (no see-through to stars), textured with `Damage.tga`, muted, toned-down size; toggle off ⇒ stock. Record observations + screenshot path.
- [ ] **Step 3: commit** — `docs(damage): hull-breach 2b manual verification`

---

## Self-Review

**Spec coverage:** bytes2 reader → T2; DC extractor (QEF, isovalue) → T3/T4; planes/palette decode → T1; carved scalar field → T5; render through holes + triplanar Damage.tga → T6; tone-down/muted → T7; cube-splat removed → T6; extractor-validated-first → T1–T4 ordering. ✓ Non-goals (bytes2 writer, debris, classic toggle) correctly absent.

**Placeholder scan:** the geometric-matching fallback in T2 is a real documented alternative (with a method), not a lazy placeholder; the QEF/DC internals cite format-spec §6/§10 for exhaustive detail while showing the core code + tests. Hard-algorithm tasks (T2 tree descent, T4 DC) are gated by anchor/IoU tests so correctness is verifiable, not assumed.

**Type consistency:** `SurfaceData{planes,bytes2,trailer}`, `from_nif_surface`, `PlaneIndexMap::first_plane`, `Plane{n,d}`, `solve_qef`, `dual_contour`, `carve_sphere`, `dauntless_hull_damage::enabled()` are consistent across tasks. `VoxelVolume` (dims/origin/cell/occ 0–127) from the foundation is reused throughout.
