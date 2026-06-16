# Hull Damage Tessellation — Plan 4a: Crushability GPU Plumbing

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get the per-vertex `crushability` weight onto the GPU: upload it as vertex attribute location 7, and run `bake_crushability` at model-load time for ship meshes so the attribute carries real thickness-derived values.

**Architecture:** Two small, additive changes to the asset pipeline. (1) `mesh_upload.cc` gains one more `glVertexAttribPointer` for the existing `MeshCpu::Vertex.crushability` float at location 7. (2) `model_build.cc` calls `assets::bake_crushability(cpu)` just before GPU upload, gated on `ctx.keep_cpu_data` (true only for ray-traceable ship models) so bridge/prop/UI meshes don't pay the bake. No shader reads attribute 7 yet (that is Plan 4b), so there is no visual change — this is pure plumbing that the displacement shader will consume.

**Tech Stack:** C++20, OpenGL 4.1, GoogleTest (`assets_tests` — a GPU test via the GL fixture for the attribute; a CPU test with stub uploaders for the bake wiring).

**Spec:** `docs/superpowers/specs/2026-06-16-hull-damage-tessellation-design.md` — §Architecture.2 ("uploaded as an extra vertex attribute", bake-at-load), §Architecture.3 (mesh stays static; crushability is a per-vertex attribute the TES reads).

**Branch:** create `feat/hull-damage-crushability-upload` off `main` (Plans 1–3 merged).

---

## Scoping decisions (stated up front)

- **Sidecar cache deferred.** The spec mentions caching the bake to a sidecar file. This plan does **bake-at-load only** (no cache). Rationale: the bake is gated to ship meshes (`keep_cpu_data`), so only a handful of meshes per mission pay it (~tens to low-hundreds of ms each); a binary sidecar format + staleness handling is real complexity that isn't justified until load time is measured to hurt. If it does, add the cache as a focused follow-up. This is a deliberate YAGNI call.
- **Bake gated on `keep_cpu_data`.** `ctx.keep_cpu_data` is true for models that retain CPU geometry for ray-tracing — i.e. ships (the only things that deform). Bridge interiors, props, and UI meshes set it false and are skipped, so they keep the default `crushability = 0.5` and pay no bake cost. (If a future deformable model type doesn't set `keep_cpu_data`, revisit — noted.)
- **No eligibility / no displacement here.** Whether a ship's crushability is actually *used* (the tessellation draw path) is Plan 4b; restricting which ships tessellate (player + nearest/largest) is Plan 6. Plan 4a just makes the data present and correct on the GPU.

---

## Key facts for the implementer (you have zero context — read these)

- bc_dauntless is an open C++ reimplementation of Star Trek: Bridge Commander. ONE build tree at the project root. Always: `cmake -B build -S . && cmake --build build -j` from `/Users/mward/Documents/Projects/bc_dauntless`. **NEVER** run cmake inside `native/`.
- **`MeshCpu::Vertex`** (`native/src/assets/include/assets/mesh.h`) already has a `float crushability = 0.5f` field (last member, added in Plan 3). `assets::bake_crushability(MeshCpu&)` (`native/src/assets/include/assets/crushability_bake.h`, impl in `src/crushability_bake.cc`) fills it per-vertex from inward hull thickness; it is fully unit-tested.
- **`mesh_upload.cc`** (`native/src/assets/src/mesh_upload.cc`) sets up vertex attributes 0–6 (position, normal, uv, color, bone_indices, bone_weights, uv1) using `offsetof(MeshCpu::Vertex, field)` and `sizeof(MeshCpu::Vertex)` as stride. Location 7 is free. `crushability` is a single `float` → a 1-component `GL_FLOAT` attribute, NOT normalized.
- **`model_build.cc`** (`native/src/assets/src/model_build.cc`) builds each `MeshCpu cpu` via `build_mesh_cpu(...)`, applies skinning, then uploads. The upload happens at ~lines 583–590: when `ctx.keep_cpu_data` is true it uploads a copy and retains the CPU data (`set_cpu_data`); otherwise it moves the CPU data straight into the uploader. The bake hook goes in the `keep_cpu_data` branch, before `mesh_upload`.
- **Tests:** `assets_tests` has a GPU suite under `native/tests/assets/gpu/` (uses `assets_test::GLContext` fixture, skips if no GL) and a CPU suite under `native/tests/assets/cpu/` (no GL). `model_build_test.cc` (CPU) builds synthetic `nif::File` objects with stub uploaders (`stub_mesh`, `stub_texture`) and a `make_ctx()` helper — perfect for testing the bake wiring deterministically without GL or game assets. `nif::NiTriShapeData` has `has_normals` + `normals` fields, and `build_mesh_cpu` applies them, so a synthetic shape can carry real normals.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `native/src/assets/src/mesh_upload.cc` | Add the `crushability` vertex attribute at location 7 | Modify |
| `native/tests/assets/gpu/mesh_upload_test.cc` | Update the attribute-enabled test to cover all attributes (0–7) | Modify |
| `native/src/assets/src/model_build.cc` | Call `bake_crushability(cpu)` before upload, gated on `keep_cpu_data` | Modify |
| `native/tests/assets/cpu/model_build_test.cc` | Deterministic test: a built ship model carries baked crushability | Modify |

---

## Task 1: Upload `crushability` as vertex attribute 7

**Files:**
- Modify: `native/src/assets/src/mesh_upload.cc`
- Test: `native/tests/assets/gpu/mesh_upload_test.cc`

- [ ] **Step 1: Update the failing test**

In `native/tests/assets/gpu/mesh_upload_test.cc`, replace the `AllSixAttributesEnabled` test (it currently loops `loc < 6`, which is already stale — the upload enables 0–6) with one that covers all eight attributes (0–7, including the new crushability at 7):

```cpp
TEST_F(MeshUploadTest, AllVertexAttributesEnabled) {
    assets::MeshCpu cpu;
    cpu.vertices.resize(1);
    cpu.indices = {0};

    auto mesh = assets::upload_mesh(cpu);
    glBindVertexArray(mesh.vao());
    // Locations 0-7: position, normal, uv, color, bone_indices, bone_weights,
    // uv1, crushability.
    for (int loc = 0; loc < 8; ++loc) {
        GLint enabled = 0;
        glGetVertexAttribiv(loc, GL_VERTEX_ATTRIB_ARRAY_ENABLED, &enabled);
        EXPECT_EQ(enabled, GL_TRUE) << "attribute location " << loc << " not enabled";
    }
    glBindVertexArray(0);
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j --target assets_tests && ctest --test-dir build -R "MeshUpload.AllVertexAttributesEnabled" --output-on-failure`
Expected: FAIL (location 7 not enabled) — or SKIP if no GL context. If it SKIPs in your environment, note it and proceed; Step 4 confirms the change builds and the broader suite is green. (On this macOS dev box GL is available, so it should actually FAIL then PASS.)

- [ ] **Step 3: Add the attribute to the upload**

In `native/src/assets/src/mesh_upload.cc`, after the location-6 (`uv1`) block (the last `glEnableVertexAttribArray(6)` / `glVertexAttribPointer(6, ...)`), add location 7:

```cpp
    glEnableVertexAttribArray(7);
    glVertexAttribPointer(7, 1, GL_FLOAT, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(V, crushability)));
```

- [ ] **Step 4: Run the test to verify it passes + no regression**

Run: `cmake --build build -j --target assets_tests && ctest --test-dir build -R "MeshUpload" --output-on-failure`
Expected: all MeshUpload tests PASS (or SKIP with no GL).

- [ ] **Step 5: Commit**

```bash
git add native/src/assets/src/mesh_upload.cc native/tests/assets/gpu/mesh_upload_test.cc
git commit -m "feat(assets): upload crushability as vertex attribute 7"
```

---

## Task 2: Bake crushability at model load (ship meshes)

**Files:**
- Modify: `native/src/assets/src/model_build.cc`
- Test: `native/tests/assets/cpu/model_build_test.cc`

- [ ] **Step 1: Write the failing test**

In `native/tests/assets/cpu/model_build_test.cc`, add a synthetic "facing quads" NIF builder to the `ModelBuildTest` fixture (alongside the existing `trivial_file_with_one_trishape()` helper), then a test that builds it with `keep_cpu_data = true` and asserts the bake ran.

Add this method inside the `ModelBuildTest` class (after `trivial_file_with_one_trishape()`):

```cpp
    // A small top quad (z=0, normal +z, x/y in [0,10]) over a larger bottom
    // quad (z=-1, normal -z, x/y in [-5,15]). A ray straight down from a top
    // vertex lands in the bottom's interior at thickness 1 -> high crushability;
    // bottom corners cast up and miss the smaller top quad -> no_hit_value.
    // Mirrors the crushability_bake unit-test geometry.
    nif::File facing_quads_file() {
        nif::File f;
        nif::NiNode root;
        root.av.obj.name = "Root";
        root.child_links = {1};
        f.blocks.push_back(root);

        nif::NiTriShape tri;
        tri.av.obj.name = "Hull";
        tri.data_link = 2;
        f.blocks.push_back(tri);

        nif::NiTriShapeData d;
        d.num_vertices = 8;
        d.has_vertices = true;
        d.vertices = {
            {0, 0, 0}, {10, 0, 0}, {10, 10, 0}, {0, 10, 0},        // top
            {-5, -5, -1}, {15, -5, -1}, {15, 15, -1}, {-5, 15, -1}, // bottom
        };
        d.has_normals = true;
        d.normals = {
            {0, 0, 1}, {0, 0, 1}, {0, 0, 1}, {0, 0, 1},
            {0, 0, -1}, {0, 0, -1}, {0, 0, -1}, {0, 0, -1},
        };
        d.has_uv = true;
        d.uv_sets.push_back({
            {0, 0}, {1, 0}, {1, 1}, {0, 1},
            {0, 0}, {1, 0}, {1, 1}, {0, 1},
        });
        d.num_triangles = 4;
        d.triangles = {{0, 1, 2}, {0, 2, 3}, {4, 5, 6}, {4, 6, 7}};
        f.blocks.push_back(d);
        return f;
    }
```

Then add this test (after the existing tests):

```cpp
TEST_F(ModelBuildTest, ShipModelGetsBakedCrushability) {
    auto f = facing_quads_file();
    auto ctx = make_ctx();
    ctx.keep_cpu_data = true;  // ships retain CPU data; the bake runs for them
    auto model = assets::detail::build_model(f, ctx);

    ASSERT_FALSE(model.meshes.empty());
    const auto& cpu = model.meshes[0].cpu_data();
    ASSERT_TRUE(cpu.has_value());
    ASSERT_EQ(cpu->vertices.size(), 8u);

    // The bake must have changed at least one vertex away from the 0.5 default.
    bool any_non_default = false;
    for (const auto& v : cpu->vertices) {
        if (std::abs(v.crushability - 0.5f) > 1e-4f) any_non_default = true;
    }
    EXPECT_TRUE(any_non_default) << "bake_crushability did not run at load";

    // Top-quad vertices (0..3) hit the overhanging bottom at thickness 1 -> thin
    // -> crushability above the 0.5 fallback.
    for (int i = 0; i < 4; ++i) {
        EXPECT_GT(cpu->vertices[i].crushability, 0.5f)
            << "top vertex " << i << " should bake as thin/crushable";
    }
}

TEST_F(ModelBuildTest, NonShipModelKeepsDefaultCrushability) {
    // keep_cpu_data=false (the make_ctx default): no CPU data retained AND the
    // bake is skipped. We can't read crushability without cpu_data, so this
    // test just confirms the non-retained path still builds a model cleanly.
    auto f = facing_quads_file();
    auto model = assets::detail::build_model(f, make_ctx());  // keep_cpu_data=false
    ASSERT_FALSE(model.meshes.empty());
    EXPECT_FALSE(model.meshes[0].cpu_data().has_value());
}
```

Ensure `model_build_test.cc` has `#include <cmath>` near the top for `std::abs` (add it if absent).

- [ ] **Step 2: Run to verify it fails**

Run: `cmake --build build -j --target assets_tests && ctest --test-dir build -R "ModelBuildTest.ShipModelGetsBakedCrushability" --output-on-failure`
Expected: FAIL — `any_non_default` is false (the bake isn't wired yet, so all crushability stays at the 0.5 default).

- [ ] **Step 3: Wire the bake into model build**

In `native/src/assets/src/model_build.cc`:

First, add the include near the other `assets/` includes at the top of the file:

```cpp
#include "assets/crushability_bake.h"
```

Then, in the upload section (the `if (ctx.keep_cpu_data) { ... }` branch, ~line 584), call the bake on `cpu` BEFORE the upload. The branch becomes:

```cpp
        // Avoid copying the CPU vertex data unless retention is requested.
        if (ctx.keep_cpu_data) {
            // Ships retain CPU geometry (for ray-tracing) and are the only
            // models that deform — bake per-vertex crushability here, before
            // upload, so attribute 7 carries real thickness-derived weights.
            // Non-retained models (bridge/props/UI) keep the 0.5 default.
            bake_crushability(cpu);
            Mesh mesh = mesh_upload(MeshCpu(cpu));
            mesh.set_cpu_data(std::move(cpu));
            model.meshes.push_back(std::move(mesh));
        } else {
            model.meshes.push_back(mesh_upload(std::move(cpu)));
        }
```

- [ ] **Step 4: Run to verify it passes**

Run: `cmake --build build -j --target assets_tests && ctest --test-dir build -R "ModelBuildTest" --output-on-failure`
Expected: all ModelBuildTest tests PASS (including the two new ones).

- [ ] **Step 5: Run the broader assets suite to confirm no regression**

Run: `ctest --test-dir build -R "assets|Mesh|Model|Crushability|Bake|Probe" --output-on-failure`
Expected: all PASS/SKIPPED.

- [ ] **Step 6: Commit**

```bash
git add native/src/assets/src/model_build.cc native/tests/assets/cpu/model_build_test.cc
git commit -m "feat(assets): bake crushability at load for ship meshes (keep_cpu_data)"
```

---

## Task 3: Confirm the full binary builds

The unit tests cover the upload + bake; this confirms the whole asset/render binary still links and loads with the new attribute and the load-time bake.

**Files:** none (verification only)

- [ ] **Step 1: Build the full binary**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: `build/dauntless` and `_dauntless_host` build cleanly.

- [ ] **Step 2: Run the full native test suite**

Run: `ctest --test-dir build --output-on-failure`
Expected: all PASS/SKIPPED, no regressions from the attribute addition or the load-time bake.

- [ ] **Step 3: Record the result**

No commit (no file change). If the full suite is green, Plan 4a is complete and the crushability attribute is live on the GPU (carrying real values for ships), ready for Plan 4b's tessellation shader to consume at attribute location 7.

(No manual visual check is needed: nothing reads attribute 7 yet, so the render output is unchanged. The first visual payoff is Plan 4b.)

---

## Self-Review

**Spec coverage (Plan 4a scope = spec §2 "uploaded as an extra vertex attribute" + bake-at-load):**
- §2 "stored as a new per-vertex attribute on `MeshCpu::Vertex`" (Plan 3) "uploaded as an extra vertex attribute" → Task 1 (location 7). ✓
- §2 bake runs to fill the attribute → Task 2 (`bake_crushability` at load, gated to ships). ✓
- §2 sidecar cache → **deliberately deferred** (YAGNI; stated in Scoping decisions). Noted, not silently dropped.
- §3 "mesh stays static; crushability is a per-vertex attribute the TES reads" → the attribute is now present and static in the VBO; the TES consumer is Plan 4b. ✓
- Tessellation shaders, crater uniforms, draw path, eligibility → **Plan 4b / Plan 6 by design**, not Plan 4a gaps.

**Placeholder scan:** No TBD/TODO. The `keep_cpu_data` gate and cache-deferral are documented decisions with rationale, not placeholders.

**Type consistency:** `assets::bake_crushability(MeshCpu&)` (Plan 3 signature) is called as `bake_crushability(cpu)` in Task 2 — matches. `offsetof(V, crushability)` (Task 1) references the `MeshCpu::Vertex.crushability` field added in Plan 3. The test reads `model.meshes[0].cpu_data()->vertices[i].crushability` — `cpu_data()` returns `const std::optional<MeshCpu>&` (confirmed in `mesh.h`), so `.has_value()` / `->vertices` is correct. `nif::NiTriShapeData` fields (`num_vertices`, `has_vertices`, `vertices`, `has_normals`, `normals`, `has_uv`, `uv_sets`, `num_triangles`, `triangles`) match the existing `trivial_file_with_one_trishape()` usage + `block.h`. ✓

---

## What comes next (not this plan)

- **Plan 4b (the displacement pipeline — first visible dents):** add the `deform` tessellation shaders (`opaque_deform.{vert,tesc,tese}`, `#version 410`, reusing `opaque.frag` as the fragment stage since the TES emits the same `v_normal_ws`/`v_uv`/`v_position_ws` varyings); a `Pipeline::deform_shader()` member; crater uniform upload in `draw_model` (mirroring the decal `u_decal_*` pattern, reading `inst.craters.slots()`); adaptive TCS (tess level from crater proximity + camera distance); TES displacement = Σ crater contributions along `impact_dir_body`, weighted by the barycentrically-interpolated `crushability` (attribute 7) and a radial falloff, with finite-difference normal recompute; the `GL_PATCHES` draw path gated on stored `query_gl_caps().tessellation_available` AND `inst.craters.count() > 0`; a render-and-readback test that a crater visibly displaces geometry. Also fix the two Plan-3 deferrals (demote/document `probe_thickness`; the `mesh_upload` attribute test is updated here in 4a).
- **Plan 5:** dent/gouge fragment shading (triplanar `Damage.tga` + procedural) + Modern VFX config toggles.
- **Plan 6:** eligibility manager (player + nearest/largest cap) + `engine/appc/hull_deformation.py` (GU depth/kind mapping) + `hit_feedback` dispatch hook; picks up the Plan 2 deferrals too.
