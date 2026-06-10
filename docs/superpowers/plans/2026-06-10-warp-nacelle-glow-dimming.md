# Warp-Nacelle Glow Dimming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dim a warp nacelle's steady-state glow (flicker-then-die) when its warp engine pod is disabled or destroyed, by attenuating only the glow term inside an auto-fitted body-space capsule around the warp hardpoint.

**Architecture:** A load-time C++ vertex walk fits a fore/aft capsule to each warp nacelle from its `EP_WARP` hardpoint point+radius. The capsule is stored per render instance. Each frame, Python reads each warp pod's `IsDisabled()`/`IsDestroyed()` and pushes a dim target + disable timestamp. The opaque fragment shader tests each capsule against the body-space fragment position (machinery already used by damage decals) and multiplies the glow term down inside it, with a flicker-then-settle transition. When no capsules are active the shader loop is skipped, keeping the production render path byte-identical.

**Tech Stack:** C++17 + GLM (renderer/scenegraph), GLSL 330 (opaque.frag), pybind11 host bindings, Python 3 (engine), GoogleTest (C++), pytest (Python).

**Spec:** `docs/superpowers/specs/2026-06-10-warp-nacelle-glow-dimming-design.md`

---

## File Structure

**C++ — detection core (new):**
- `native/src/renderer/include/renderer/nacelle_region.h` — `NacelleRegion` struct + `compute_nacelle_region()` declaration.
- `native/src/renderer/nacelle_region.cc` — the vertex-walk extent fit + formula fallback.
- `native/tests/renderer/nacelle_region_test.cc` — unit tests for the fit + fallback.

**C++ — per-instance storage (modify):**
- `native/src/scenegraph/include/scenegraph/instance.h` — add a fixed-capacity `NacelleRegion` array + count to `Instance`.

**C++ — host bindings (modify):**
- `native/src/host/host_bindings.cc` — `compute_and_store_nacelle_region(...)` and `set_nacelle_dim(...)` bindings.

**C++ — render (modify):**
- `native/src/renderer/frame.cc` — upload active capsules as uniforms in `draw_model`.
- `native/src/renderer/shaders/opaque.frag` — capsule uniforms + glow-term attenuation with flicker.

**Python (new + modify):**
- `engine/renderer.py` — thin wrappers `compute_nacelle_region`, `set_nacelle_dim`.
- `engine/appc/warp_glow.py` — enumerate warp pods, register capsules at construction, compute per-frame dim targets.
- `tests/engine/appc/test_warp_glow.py` — unit tests for the pure mapping logic.
- `native/src/renderer/CMakeLists.txt`, `native/tests/renderer/CMakeLists.txt` — register the new source/test.

**Integration (modify):**
- `engine/host_loop.py` — call registration at ship-instance creation; call per-frame update in the ship loop.

---

## Conventions you must follow (read before starting)

- **Column-vector rotation** (CLAUDE.md): ship world-forward is `R.GetCol(1)` / model **+Y**. Capsule axis defaults to model +Y `(0,1,0)`.
- **Game units, not metres** (CLAUDE.md): hardpoint positions/radii are in body/model units, same frame as NIF vertices and the shader's `p_body`. The decal binding already converts a GU radius into model units via `s = |inst.world[0]|`; mirror that exactly. Never name a variable `*_m`.
- **Byte-identical production path:** when `u_nacelle_count == 0` the shader must do nothing. Verify this property in a test.
- **No save/load state:** capsules are recomputed at construction; dim state is re-derived from live condition. Never serialize.
- **pytest memory:** NEVER run the full suite (`uv run pytest`) — it OOMs the host (>100 GB). Run only the specific node IDs named in each task.

---

## Task 1: Detection core — `compute_nacelle_region`

**Files:**
- Create: `native/src/renderer/include/renderer/nacelle_region.h`
- Create: `native/src/renderer/nacelle_region.cc`
- Create: `native/tests/renderer/nacelle_region_test.cc`
- Modify: `native/src/renderer/CMakeLists.txt:66` (add `nacelle_region.cc` after `aabb.cc`)
- Modify: `native/tests/renderer/CMakeLists.txt` (add `nacelle_region_test.cc`)

- [ ] **Step 1: Write the header**

Create `native/src/renderer/include/renderer/nacelle_region.h`:

```cpp
// native/src/renderer/include/renderer/nacelle_region.h
#pragma once

#include <glm/glm.hpp>

namespace assets { struct Model; }

namespace renderer {

/// A fore/aft capsule fitted to one warp nacelle, in body/model units.
/// `axis` is unit-length; `aft <= 0 <= fore` are signed projections along
/// `axis` relative to `center`. `dim_target`/`disable_time` are live render
/// state, not produced by the fit (default to "full glow, never disabled").
struct NacelleRegion {
    glm::vec3 center{0.0f};
    glm::vec3 axis{0.0f, 1.0f, 0.0f};
    float     radius = 0.0f;       // lateral capture radius (model units)
    float     aft    = 0.0f;       // min projection (<= 0)
    float     fore   = 0.0f;       // max projection (>= 0)
    float     dim_target   = 1.0f; // 1 = full glow, ~0.08 = disabled
    float     disable_time = -1.0f;// game-time secs of last disable edge; <0 = never
    bool      active = false;
};

/// Widen factor applied to the hardpoint radius to catch the full nacelle
/// cross-section (spec §Approach.1).
inline constexpr float kNacelleRadiusWiden = 1.25f;
/// Fallback half-length as a multiple of the (widened) radius when the
/// lateral capture is degenerate (spec §Approach.1 fallback).
inline constexpr float kNacelleFallbackHalfLenFactor = 2.5f;
/// Minimum captured vertices for the mesh fit to be trusted; below this we
/// use the formula fallback.
inline constexpr int kNacelleMinCaptured = 8;

/// Fit a nacelle capsule. Walks the model's retained CPU vertices into body
/// space (same node-transform composition as compute_model_aabb), keeps those
/// within `radius * kNacelleRadiusWiden` laterally of the `axis` line through
/// `center`, and sets aft/fore to the min/max axial projection of the kept
/// vertices. Falls back to +/- kNacelleFallbackHalfLenFactor * widened radius
/// when fewer than kNacelleMinCaptured vertices are captured (or the model has
/// no CPU data). `axis` is assumed unit-length (model +Y by default).
NacelleRegion compute_nacelle_region(const assets::Model& model,
                                     const glm::vec3& center,
                                     const glm::vec3& axis,
                                     float radius);

}  // namespace renderer
```

- [ ] **Step 2: Write the failing test**

Create `native/tests/renderer/nacelle_region_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include "renderer/nacelle_region.h"
#include "assets/model.h"

namespace {
// Single-node model whose vertices we control directly in body space.
void add_cpu_mesh(assets::Model& m, std::vector<glm::vec3> positions) {
    assets::MeshCpu cpu;
    for (auto& p : positions) {
        cpu.vertices.push_back({.position = p, .normal = glm::vec3(0, 0, 1)});
    }
    assets::Mesh mesh;
    mesh.set_cpu_data(std::move(cpu));
    int mesh_idx = static_cast<int>(m.meshes.size());
    m.meshes.push_back(std::move(mesh));
    assets::Node node;
    node.name = "root";
    node.meshes.push_back(mesh_idx);
    m.nodes.push_back(std::move(node));
    m.root_node = 0;
}
}  // namespace

TEST(NacelleRegion, FitsForeAftExtentFromTubeVertices) {
    // A tube along +Y from y=-3 to y=+5, cross-section within radius 1 of the
    // axis through center (0,0,0). Plus a far-away stray vertex OUTSIDE the
    // lateral radius that must be ignored.
    assets::Model m;
    add_cpu_mesh(m, {
        {0.0f, -3.0f, 0.0f}, {0.5f, 0.0f, 0.5f}, {0.0f, 5.0f, 0.0f},
        {0.9f, 2.0f, 0.0f},
        {10.0f, 50.0f, 0.0f},   // lateral dist 10 > 1*1.25 -> ignored
    });
    auto reg = renderer::compute_nacelle_region(
        m, glm::vec3(0.0f), glm::vec3(0.0f, 1.0f, 0.0f), 1.0f);
    EXPECT_TRUE(reg.active);
    EXPECT_NEAR(reg.aft, -3.0f, 1e-4f);
    EXPECT_NEAR(reg.fore, 5.0f, 1e-4f);
    EXPECT_NEAR(reg.radius, 1.25f, 1e-4f);  // widened
}

TEST(NacelleRegion, FallsBackToFormulaWhenCaptureDegenerate) {
    // No vertices near the axis -> fewer than kNacelleMinCaptured captured.
    assets::Model m;
    add_cpu_mesh(m, {{100.0f, 0.0f, 0.0f}, {100.0f, 1.0f, 0.0f}});
    auto reg = renderer::compute_nacelle_region(
        m, glm::vec3(0.0f), glm::vec3(0.0f, 1.0f, 0.0f), 2.0f);
    EXPECT_TRUE(reg.active);
    const float widened = 2.0f * renderer::kNacelleRadiusWiden;
    const float half = renderer::kNacelleFallbackHalfLenFactor * widened;
    EXPECT_NEAR(reg.fore, half, 1e-4f);
    EXPECT_NEAR(reg.aft, -half, 1e-4f);
}
```

- [ ] **Step 3: Register the new sources in CMake**

In `native/src/renderer/CMakeLists.txt`, add `nacelle_region.cc` on the line after `aabb.cc` (line 66):

```cmake
    aabb.cc
    nacelle_region.cc
    ray_trace.cc
```

In `native/tests/renderer/CMakeLists.txt`, add `nacelle_region_test.cc` after `aabb_test.cc`:

```cmake
    aabb_test.cc
    nacelle_region_test.cc
    ray_trace_test.cc
```

- [ ] **Step 4: Run the test to verify it fails to build/link**

Run:
```bash
cmake -B build -S . -DDAUNTLESS_BUILD_TESTS=ON >/dev/null && \
cmake --build build --target renderer_tests -j 2>&1 | tail -20
```
Expected: link/compile error — `compute_nacelle_region` undefined (no `.cc` yet).

- [ ] **Step 5: Implement `nacelle_region.cc`**

Create `native/src/renderer/nacelle_region.cc`:

```cpp
// native/src/renderer/nacelle_region.cc
#include "renderer/nacelle_region.h"

#include <limits>
#include <vector>

#include <assets/mesh.h>
#include <assets/model.h>

namespace renderer {

NacelleRegion compute_nacelle_region(const assets::Model& model,
                                     const glm::vec3& center,
                                     const glm::vec3& axis,
                                     float radius) {
    NacelleRegion reg;
    reg.center = center;
    reg.axis   = axis;
    reg.radius = radius * kNacelleRadiusWiden;
    reg.active = true;

    // Compose node-world transforms (parents precede children — same
    // guarantee compute_model_aabb relies on).
    const float lat2 = reg.radius * reg.radius;
    float lo = std::numeric_limits<float>::max();
    float hi = std::numeric_limits<float>::lowest();
    int captured = 0;

    if (!model.nodes.empty()) {
        std::vector<glm::mat4> node_world(model.nodes.size(), glm::mat4(1.0f));
        node_world[model.root_node] =
            model.nodes[model.root_node].local_transform;
        for (std::size_t i = 0; i < model.nodes.size(); ++i) {
            const auto& node = model.nodes[i];
            if (node.parent_index >= 0) {
                node_world[i] =
                    node_world[node.parent_index] * node.local_transform;
            }
            for (int mesh_idx : node.meshes) {
                if (mesh_idx < 0 ||
                    mesh_idx >= static_cast<int>(model.meshes.size())) continue;
                const auto& cpu = model.meshes[mesh_idx].cpu_data();
                if (!cpu) continue;
                for (const auto& v : cpu->vertices) {
                    const glm::vec3 p =
                        glm::vec3(node_world[i] * glm::vec4(v.position, 1.0f));
                    const glm::vec3 d = p - center;
                    const float t = glm::dot(d, axis);            // axial proj
                    const glm::vec3 perp = d - t * axis;          // lateral
                    if (glm::dot(perp, perp) > lat2) continue;    // outside tube
                    lo = (t < lo) ? t : lo;
                    hi = (t > hi) ? t : hi;
                    ++captured;
                }
            }
        }
    }

    if (captured < kNacelleMinCaptured) {
        const float half = kNacelleFallbackHalfLenFactor * reg.radius;
        reg.aft  = -half;
        reg.fore =  half;
        return reg;
    }
    reg.aft  = lo;
    reg.fore = hi;
    return reg;
}

}  // namespace renderer
```

- [ ] **Step 6: Run the tests to verify they pass**

Run:
```bash
cmake --build build --target renderer_tests -j >/dev/null 2>&1 && \
GALLIUM_DRIVER=llvmpipe ./build/native/tests/renderer/renderer_tests --gtest_filter='NacelleRegion.*'
```
Expected: 2 tests PASS. (If the binary path differs, find it with `find build -name renderer_tests`.)

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/include/renderer/nacelle_region.h \
        native/src/renderer/nacelle_region.cc \
        native/tests/renderer/nacelle_region_test.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(vfx): nacelle capsule fit from warp hardpoint (compute_nacelle_region)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Per-instance capsule storage

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h`

The `NacelleRegion` type lives in `renderer`, but `Instance` lives in `scenegraph` and must not depend on `renderer`. Define a minimal storage mirror in `scenegraph` to avoid the dependency, matching how `Instance` already owns a `DamageDecalRing` without depending on the shader.

- [ ] **Step 1: Add storage to the Instance struct**

In `native/src/scenegraph/include/scenegraph/instance.h`, add after the `decals` member (line 37):

```cpp
    /// Per-instance warp-nacelle glow capsules (body frame, model units).
    /// Runtime VFX state only — never serialized. Fixed cap: a ship has at
    /// most a handful of nacelles.
    static constexpr std::size_t kMaxNacelles = 4;
    struct Nacelle {
        glm::vec3 center{0.0f};
        glm::vec3 axis{0.0f, 1.0f, 0.0f};
        float     radius = 0.0f;
        float     aft = 0.0f;
        float     fore = 0.0f;
        float     dim_target = 1.0f;
        float     disable_time = -1.0f;
        bool      active = false;
    };
    std::array<Nacelle, kMaxNacelles> nacelles{};
```

Add `#include <array>` and `#include <cstddef>` to the includes at the top of the file if not already present.

- [ ] **Step 2: Verify it compiles**

Run:
```bash
cmake --build build --target dauntless -j 2>&1 | tail -5
```
Expected: builds clean (struct-only change; no behavior yet).

- [ ] **Step 3: Commit**

```bash
git add native/src/scenegraph/include/scenegraph/instance.h
git commit -m "feat(vfx): per-instance warp-nacelle capsule storage on Instance

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Host bindings — register capsule + push dim state

**Files:**
- Modify: `native/src/host/host_bindings.cc` (near `damage_decal_add`, ~line 1048; needs `#include <renderer/nacelle_region.h>` near the existing `#include <renderer/ray_trace.h>` at line 41)
- Modify: `native/tests/...` — none (covered by Python integration + the C++ core test)

- [ ] **Step 1: Add the include**

In `native/src/host/host_bindings.cc`, after `#include <renderer/ray_trace.h>` (line 41):

```cpp
#include <renderer/nacelle_region.h>
```

- [ ] **Step 2: Add the two bindings**

In `native/src/host/host_bindings.cc`, immediately after the `damage_decal_add` binding block (ends ~line 1080), add:

```cpp
    m.def("compute_nacelle_region",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> center,
             std::tuple<float, float, float> axis,
             float radius) -> int {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return -1;
              // Resolve the model exactly as ray_trace_mesh does
              // (host_bindings.cc:1004-1031) — there is no world.model_for().
              const auto h = inst->model_handle;
              if (h == 0 || h > g_loaded_models.size()) return -1;
              const assets::Model* model = g_loaded_models[h - 1].handle.get();
              if (model == nullptr) return -1;
              // hardpoint center/radius are in game units; convert to the
              // model frame the CPU verts live in (same s as damage_decal_add).
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv = (s > 0.0f) ? 1.0f / s : 1.0f;
              const glm::vec3 c(std::get<0>(center) * inv,
                                std::get<1>(center) * inv,
                                std::get<2>(center) * inv);
              glm::vec3 a(std::get<0>(axis), std::get<1>(axis),
                          std::get<2>(axis));
              const float alen = glm::length(a);
              a = (alen > 0.0f) ? a / alen : glm::vec3(0.0f, 1.0f, 0.0f);
              const renderer::NacelleRegion fit =
                  renderer::compute_nacelle_region(*model, c, a, radius * inv);
              // find a free slot
              for (std::size_t i = 0; i < inst->nacelles.size(); ++i) {
                  if (inst->nacelles[i].active) continue;
                  auto& n = inst->nacelles[i];
                  n.center = fit.center; n.axis = fit.axis;
                  n.radius = fit.radius; n.aft = fit.aft; n.fore = fit.fore;
                  n.dim_target = 1.0f; n.disable_time = -1.0f; n.active = true;
                  return static_cast<int>(i);
              }
              return -1;  // no free slot
          },
          py::arg("instance_id"), py::arg("center"), py::arg("axis"),
          py::arg("radius"),
          "Fit and store a warp-nacelle glow capsule on the instance. "
          "center/axis/radius are in game units / body frame. Returns the "
          "region index, or -1 on failure (stale id, no model, no slot).");

    m.def("set_nacelle_dim",
          [](scenegraph::InstanceId id, int region_index,
             float dim_target, float disable_time) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;
              if (region_index < 0 ||
                  region_index >= static_cast<int>(inst->nacelles.size())) return;
              auto& n = inst->nacelles[static_cast<std::size_t>(region_index)];
              if (!n.active) return;
              n.dim_target = dim_target;
              n.disable_time = disable_time;
          },
          py::arg("instance_id"), py::arg("region_index"),
          py::arg("dim_target"), py::arg("disable_time"),
          "Update a nacelle capsule's live dim target [0,1] and the game-time "
          "seconds of the last disable edge (<0 = healthy / never disabled).");
```

- [ ] **Step 3: Confirm `g_loaded_models` is in scope at the binding site**

Run:
```bash
grep -n "g_loaded_models" native/src/host/host_bindings.cc | head
```
Expected: `g_loaded_models` is a file-scope vector already used by `ray_trace_mesh` and `load_model`; the model-resolution lines in Step 2 reference it directly (no new accessor needed).

- [ ] **Step 4: Build the host module**

Run:
```bash
cmake --build build -j 2>&1 | tail -5
```
Expected: builds clean; `_open_stbc_host` / `_dauntless_host` extension rebuilt.

- [ ] **Step 5: Smoke-test the bindings exist from Python**

Run:
```bash
uv run python -c "import _dauntless_host as h; print(hasattr(h,'compute_nacelle_region'), hasattr(h,'set_nacelle_dim'))"
```
Expected: `True True`. (If `AttributeError` on the module, the binary is stale — rebuild from `build/`, per CLAUDE.md.)

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(vfx): host bindings compute_nacelle_region + set_nacelle_dim

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Upload capsules as shader uniforms

**Files:**
- Modify: `native/src/renderer/frame.cc` (`draw_model`, after the decal upload block at lines 80-113)

- [ ] **Step 1: Add the capsule upload block**

In `native/src/renderer/frame.cc`, `draw_model` already receives the instance's decals; extend it to also receive the instance's nacelle array. First change the signature and the two call sites.

Change the `draw_model` signature (line 73-81) to add a nacelle span parameter after `decals`:

```cpp
void draw_model(const assets::Model& model,
                const glm::mat4& world,
                Shader& shader,
                GLuint white_fallback,
                GLuint black_fallback,
                bool rim_active,
                const scenegraph::DamageDecalRing& decals,
                const std::array<scenegraph::Instance::Nacelle,
                                 scenegraph::Instance::kMaxNacelles>& nacelles,
                float decal_time) {
```

At both call sites (lines 274 and 312), pass `inst.nacelles` before `decal_time`:

```cpp
        if (m) draw_model(*m, inst.world, shader, white, black, rim_active,
                          inst.decals, inst.nacelles, decal_time);
```

Add `#include <array>` and `#include <scenegraph/instance.h>` to frame.cc's includes if not already present.

Then, immediately after the closing `}` of the decal upload block (line ~113, before the node-walk comment), add:

```cpp
    // ── Warp-nacelle glow capsules ─────────────────────────────────────────
    // Dim the glow term inside an auto-fitted capsule when a warp pod is
    // disabled. u_nacelle_count == 0 makes the shader skip the loop entirely,
    // keeping the production path byte-identical.
    {
        glm::vec4 na[scenegraph::Instance::kMaxNacelles];
        glm::vec4 nb[scenegraph::Instance::kMaxNacelles];
        glm::vec4 nc[scenegraph::Instance::kMaxNacelles];
        int nn = 0;
        for (const auto& n : nacelles) {
            if (!n.active) continue;
            na[nn] = glm::vec4(n.center, n.radius);
            nb[nn] = glm::vec4(n.axis, n.aft);
            nc[nn] = glm::vec4(n.fore, n.dim_target, n.disable_time, 0.0f);
            ++nn;
        }
        shader.set_int("u_nacelle_count", nn);
        if (nn > 0) {
            shader.set_vec4_array("u_nacelle_a", na, nn);
            shader.set_vec4_array("u_nacelle_b", nb, nn);
            shader.set_vec4_array("u_nacelle_c", nc, nn);
            // Reuse the decal world->body inverse + clock; set them here too in
            // case this instance has nacelles but no active decals.
            shader.set_mat4("u_ship_world_inv", glm::inverse(world));
            shader.set_float("u_decal_time", decal_time);
        }
    }
```

- [ ] **Step 2: Build**

Run:
```bash
cmake --build build --target dauntless -j 2>&1 | tail -8
```
Expected: builds clean. (Shader uniform `u_nacelle_*` will be optimized out until Task 5 adds it; setting an absent uniform is a silent no-op in this codebase's `Shader::set_*`.)

- [ ] **Step 3: Commit**

```bash
git add native/src/renderer/frame.cc
git commit -m "feat(vfx): upload warp-nacelle capsules as opaque-pass uniforms

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Shader — attenuate glow term inside capsules

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag`

**IMPORTANT (CLAUDE.md):** shader changes are NOT picked up by `cmake --build` alone — you MUST re-run `cmake -B build -S .` first to re-copy shaders.

- [ ] **Step 1: Declare the capsule uniforms**

In `native/src/renderer/shaders/opaque.frag`, after the decal uniform block (the `uniform float u_decal_time;` line, ~line 50), add:

```glsl
// ── Warp-nacelle glow dimming ───────────────────────────────────────────
const int MAX_NACELLES = 4;
uniform int  u_nacelle_count;            // 0 disables the loop entirely
uniform vec4 u_nacelle_a[MAX_NACELLES];  // center.xyz, radius (model units)
uniform vec4 u_nacelle_b[MAX_NACELLES];  // axis.xyz, aft
uniform vec4 u_nacelle_c[MAX_NACELLES];  // fore, dim_target, disable_time, _
const float NACELLE_FLICKER_SECS = 0.4;  // electrical stutter window on disable
```

- [ ] **Step 2: Add the attenuation function**

After the `stutter()` function definition (~line 88), add:

```glsl
// Multiplier applied to the ship's glow term from all active nacelle
// capsules. 1.0 = untouched. Inside a capsule, ramps from 1.0 toward
// dim_target, with a brief flicker for the first NACELLE_FLICKER_SECS after
// the disable edge (reuses stutter()). p_body is the body-frame fragment
// position; now is the game clock (u_decal_time).
float nacelle_glow_mult(vec3 p_body, float now) {
    float mult = 1.0;
    for (int i = 0; i < u_nacelle_count; ++i) {
        vec3  center = u_nacelle_a[i].xyz;
        float radius = u_nacelle_a[i].w;
        vec3  axis   = u_nacelle_b[i].xyz;
        float aft    = u_nacelle_b[i].w;
        float fore   = u_nacelle_c[i].x;
        float target = u_nacelle_c[i].y;
        float dtime  = u_nacelle_c[i].z;

        vec3  d = p_body - center;
        float t = dot(d, axis);
        vec3  perp = d - t * axis;
        // Inside the capsule? lateral within radius AND axial within [aft,fore].
        if (dot(perp, perp) > radius * radius) continue;
        if (t < aft || t > fore) continue;
        if (dtime < 0.0) continue;  // healthy — no dimming

        float age = max(now - dtime, 0.0);
        // Flicker-then-die: during the stutter window, oscillate between full
        // and target; afterward settle to target.
        float settled = target;
        float flicker = mix(target, 1.0, 0.5 + 0.5 * stutter(age));
        float w = clamp(age / NACELLE_FLICKER_SECS, 0.0, 1.0);
        float region_mult = mix(flicker, settled, w);
        mult = min(mult, region_mult);  // overlapping capsules: darkest wins
    }
    return mult;
}
```

- [ ] **Step 3: Apply it to the glow term**

Find the final color composition (`native/src/renderer/shaders/opaque.frag:254`):

```glsl
    frag_color = vec4(lit + u_emissive_color + glow.rgb * glow.a * gf + spec + rim + decal_emissive, 1.0);
```

The shader already reconstructs `p_body` for decals. Locate that reconstruction (it computes `p_body` from `u_ship_world_inv * vec4(v_position_ws,1.0)` inside the `u_decal_count > 0` guard). Hoist `p_body` so it is available whenever either decals OR nacelles are active, then multiply the glow term:

```glsl
    float nac = 1.0;
    if (u_nacelle_count > 0) {
        vec3 p_body_n = (u_ship_world_inv * vec4(v_position_ws, 1.0)).xyz;
        nac = nacelle_glow_mult(p_body_n, u_decal_time);
    }
    frag_color = vec4(lit + u_emissive_color + glow.rgb * glow.a * gf * nac + spec + rim + decal_emissive, 1.0);
```

Note: `u_emissive_color` (material self-illumination) is intentionally left untouched — only the glow-map term is dimmed (spec: "glow term only"). If a nacelle's glow is authored via `u_emissive_color` rather than the glow map on some ship, that is a follow-up; the spec scopes this to the glow map.

- [ ] **Step 4: Reconfigure (re-copy shaders) and build**

Run:
```bash
cmake -B build -S . >/dev/null && cmake --build build --target dauntless -j 2>&1 | tail -5
```
Expected: builds clean, shader recompiles at runtime without link errors.

- [ ] **Step 5: Confirm the shader compiles at runtime (headless)**

Run:
```bash
OPEN_STBC_HOST_HEADLESS=1 uv run python -c "import _dauntless_host as h; h.init(64,64,'t'); print('shader-ok'); h.shutdown()" 2>&1 | tail -3
```
Expected: prints `shader-ok` with no GLSL compile error. (If `shutdown` isn't a binding, drop it — the import+init is what exercises shader compilation.)

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag
git commit -m "feat(vfx): dim glow term inside warp-nacelle capsules (flicker-then-die)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Python renderer wrappers

**Files:**
- Modify: `engine/renderer.py` (alongside `set_rim_eligible` ~line 187)

- [ ] **Step 1: Add the wrappers**

In `engine/renderer.py`, after `set_rim_eligible` (~line 190):

```python
def compute_nacelle_region(instance_id: InstanceId,
                           center, axis, radius: float) -> int:
    """Fit and store a warp-nacelle glow capsule on the instance.

    center/axis are 3-tuples in game units / body frame; radius in game units.
    Returns the region index (>=0) or -1 on failure.
    """
    return _h.compute_nacelle_region(
        instance_id, tuple(center), tuple(axis), float(radius))


def set_nacelle_dim(instance_id: InstanceId, region_index: int,
                    dim_target: float, disable_time: float) -> None:
    """Update a nacelle capsule's dim target [0,1] and disable timestamp.

    disable_time is game-time seconds of the last disable edge; <0 = healthy.
    """
    _h.set_nacelle_dim(instance_id, int(region_index),
                       float(dim_target), float(disable_time))
```

- [ ] **Step 2: Smoke-test the wrappers import**

Run:
```bash
uv run python -c "import engine.renderer as r; print(r.compute_nacelle_region.__name__, r.set_nacelle_dim.__name__)"
```
Expected: `compute_nacelle_region set_nacelle_dim`.

- [ ] **Step 3: Commit**

```bash
git add engine/renderer.py
git commit -m "feat(vfx): renderer.py wrappers for nacelle glow dimming

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Python driver — enumerate pods, compute dim targets

**Files:**
- Create: `engine/appc/warp_glow.py`
- Create: `tests/engine/appc/test_warp_glow.py`

This module is pure logic + thin orchestration: it must be unit-testable with no host/renderer dependency for the mapping parts. Mirror the structure of `engine/appc/damage_decals.py` (constants + pure functions, host calls isolated).

- [ ] **Step 1: Write the failing test**

Create `tests/engine/appc/test_warp_glow.py`:

```python
from engine.appc import warp_glow


def test_dim_target_healthy_is_full():
    assert warp_glow.dim_target(disabled=False) == 1.0


def test_dim_target_disabled_is_residual():
    assert warp_glow.dim_target(disabled=True) == warp_glow.DISABLED_RESIDUAL


def test_disable_time_tracks_falling_edge():
    # healthy -> no edge
    t = warp_glow.disable_edge(prev_disabled=False, now_disabled=False,
                               prev_time=-1.0, now=10.0)
    assert t == -1.0
    # falling edge stamps now
    t = warp_glow.disable_edge(prev_disabled=False, now_disabled=True,
                               prev_time=-1.0, now=10.0)
    assert t == 10.0
    # still disabled -> keep original stamp
    t = warp_glow.disable_edge(prev_disabled=True, now_disabled=True,
                               prev_time=10.0, now=12.0)
    assert t == 10.0
    # repair -> clear
    t = warp_glow.disable_edge(prev_disabled=True, now_disabled=False,
                               prev_time=10.0, now=13.0)
    assert t == -1.0


def test_warp_pods_enumerates_children_then_falls_back_to_aggregator():
    class _Pod:
        def __init__(self, name):
            self._n = name
        def GetName(self):
            return self._n

    class _Agg:
        def __init__(self, kids):
            self._kids = kids
        def GetNumChildSubsystems(self):
            return len(self._kids)
        def GetChildSubsystem(self, i):
            return self._kids[i]

    kids = [_Pod("Port Warp"), _Pod("Star Warp")]
    assert warp_glow.warp_pods(_Agg(kids)) == kids
    # no children -> the aggregator itself is the single "pod"
    agg = _Agg([])
    assert warp_glow.warp_pods(agg) == [agg]
    # None aggregator -> empty
    assert warp_glow.warp_pods(None) == []
```

- [ ] **Step 2: Run to verify it fails**

Run:
```bash
uv run pytest tests/engine/appc/test_warp_glow.py -q
```
Expected: FAIL — `ModuleNotFoundError: engine.appc.warp_glow`.

- [ ] **Step 3: Implement the driver module**

Create `engine/appc/warp_glow.py`:

```python
"""Warp-nacelle glow dimming driver.

Pure mapping logic (dim targets, disable-edge tracking, pod enumeration)
plus a thin per-ship orchestration object that registers capsules at
construction and pushes dim state each frame. The C++ side owns the capsule
geometry and the shader attenuation; this module only decides *when* and
*how dark* (see docs/superpowers/specs/2026-06-10-warp-nacelle-glow-dimming-design.md).
"""

# Faint residual so a disabled nacelle reads as a dark ember, not a hole.
DISABLED_RESIDUAL = 0.08

# Capsule axis: ship-forward is model +Y under the column-vector convention.
NACELLE_AXIS = (0.0, 1.0, 0.0)


def dim_target(disabled: bool) -> float:
    """Glow multiplier target for a pod: full when healthy, residual when off."""
    return DISABLED_RESIDUAL if disabled else 1.0


def disable_edge(prev_disabled: bool, now_disabled: bool,
                 prev_time: float, now: float) -> float:
    """Track the game-time of the most recent healthy->disabled edge.

    Returns now on a falling edge, the prior stamp while still disabled, and
    -1.0 while healthy. The shader uses this to time the flicker.
    """
    if not now_disabled:
        return -1.0
    if not prev_disabled:        # falling edge
        return now
    return prev_time             # still disabled — keep original stamp


def warp_pods(warp_subsystem):
    """Return the per-nacelle pods to drive.

    Prefers the aggregator's child pods (Galaxy: Port/Star Warp). If the
    aggregator has no children, treats the aggregator itself as a single pod.
    None -> empty list.
    """
    if warp_subsystem is None:
        return []
    n = warp_subsystem.GetNumChildSubsystems()
    if n > 0:
        return [warp_subsystem.GetChildSubsystem(i) for i in range(n)]
    return [warp_subsystem]


def _is_disabled(pod) -> bool:
    """True when the pod is disabled or destroyed (live condition)."""
    return bool(pod.IsDisabled()) or bool(pod.IsDestroyed())


def _pod_position(pod):
    """Body-frame (x, y, z) of the pod's hardpoint, or None."""
    if not hasattr(pod, "GetPosition"):
        return None
    p = pod.GetPosition()
    if p is None:
        return None
    return (p.GetX(), p.GetY(), p.GetZ())


def _pod_radius(pod) -> float:
    """Hardpoint radius in game units (default 1.0 if unspecified)."""
    if hasattr(pod, "GetRadius"):
        r = pod.GetRadius()
        if r:
            return float(r)
    return 1.0


class WarpGlowController:
    """Per-ship: register capsules once, push dim state each frame.

    Holds (pod, region_index, prev_disabled, disable_time) per nacelle.
    `renderer` is engine.renderer (injected for testability).
    """

    def __init__(self, renderer, instance_id, warp_subsystem):
        self._r = renderer
        self._iid = instance_id
        self._regions = []  # list of dicts: pod, idx, prev_disabled, dtime
        for pod in warp_pods(warp_subsystem):
            pos = _pod_position(pod)
            if pos is None:
                continue
            idx = self._r.compute_nacelle_region(
                instance_id, pos, NACELLE_AXIS, _pod_radius(pod))
            if idx < 0:
                continue
            self._regions.append(
                {"pod": pod, "idx": idx, "prev": False, "dtime": -1.0})

    def update(self, now: float) -> None:
        """Read each pod's live condition and push the dim state for `now`."""
        for reg in self._regions:
            disabled = _is_disabled(reg["pod"])
            dtime = disable_edge(reg["prev"], disabled, reg["dtime"], now)
            self._r.set_nacelle_dim(
                self._iid, reg["idx"], dim_target(disabled), dtime)
            reg["prev"] = disabled
            reg["dtime"] = dtime
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
uv run pytest tests/engine/appc/test_warp_glow.py -q
```
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/warp_glow.py tests/engine/appc/test_warp_glow.py
git commit -m "feat(vfx): warp-glow driver (pod enumeration, dim targets, edge tracking)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Wire the driver into the host loop

**Files:**
- Modify: `engine/host_loop.py` (ship-instance creation ~line 1687-1701; per-frame ship loop ~line 2580-2603)

This task connects construction-time registration and per-frame updates. Because `host_loop.py` is large and the exact local variable names around the integration points matter, read the two regions first and follow the existing pattern (the way `set_rim_eligible(iid, True)` is called at construction, and the way per-ship state is updated each frame).

- [ ] **Step 1: Read the integration regions**

Run:
```bash
sed -n '1680,1740p' engine/host_loop.py
sed -n '2575,2610p' engine/host_loop.py
```
Identify: (a) the construction site where `iid` and the `ship` are both in scope (near line 1687-1701), and (b) the per-frame loop over live ships where the ship and its `iid` are available (near 2580-2603) and a game-time `now` is available.

- [ ] **Step 2: Construct a WarpGlowController per ship at instance creation**

At the construction site (after `r_.set_rim_eligible(iid, True)`, ~line 1692), add — guarded so a ship with no warp subsystem is a clean no-op:

```python
            try:
                from engine.appc.warp_glow import WarpGlowController
                _warp_glow = WarpGlowController(
                    r_, iid, ship.GetWarpEngineSubsystem())
                session.warp_glow_controllers[iid] = _warp_glow
            except Exception:
                pass  # nacelle dimming is best-effort VFX; never block spawn
```

Find where `session` per-ship dicts are initialized (search for `ship_instances` definition) and add a sibling dict:

```python
        self.warp_glow_controllers = {}
```

- [ ] **Step 3: Update controllers each frame**

In the per-frame ship loop (near line 2580-2603, where `now`/game-time and live iids are available), add:

```python
                _wg = session.warp_glow_controllers.get(iid)
                if _wg is not None:
                    _wg.update(now)
```

Use whatever the loop's existing game-time variable is named (match the clock the decals use — search for `decal_time` / the game-time read near that loop). If the loop prunes dead instances (`_xform_buf.prune(_live_ship_iids)`), also drop stale controllers:

```python
            for _dead in list(session.warp_glow_controllers.keys()):
                if _dead not in _live_ship_iids:
                    del session.warp_glow_controllers[_dead]
```

- [ ] **Step 4: Build and run a focused smoke test**

Run (focused — never the full suite):
```bash
cmake -B build -S . >/dev/null && cmake --build build -j >/dev/null 2>&1
uv run pytest tests/engine/appc/test_warp_glow.py -q
```
Expected: builds clean; warp_glow tests still PASS.

- [ ] **Step 5: Visual confirmation (manual, if a display is available)**

Run the app, spawn/observe a Galaxy, disable one warp engine (dev combat tools or a mission script), and confirm only that nacelle's glow flickers then dims while the other stays lit, and that it restores on repair.

```bash
./build/dauntless
```
Expected: per-nacelle independent dimming; opposite nacelle unaffected; non-glowing hull around the nacelle unchanged.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(vfx): drive warp-nacelle glow dimming from the host loop

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Production-path safety regression

**Files:**
- Modify: `native/tests/renderer/frame_test.cc` (or the nearest existing frame/uniform test)

- [ ] **Step 1: Add a test asserting zero capsules = no nacelle uniforms bound**

Inspect `native/tests/renderer/frame_test.cc` for the existing pattern that drives `draw_model`/`frame` and inspects uniform state or output. Add a test that builds an instance with `nacelles` all `active=false` and asserts `u_nacelle_count` is set to 0 and no `u_nacelle_a/b/c` arrays are uploaded (mirror however the decal-count-zero case is already asserted, if present; if frame_test has no such hook, assert at the `draw_model` level that the rendered output for an all-inactive-nacelle instance is identical to one with the nacelle array default-constructed).

```cpp
TEST(Frame, NacelleCountZeroWhenNoneActive) {
    // ... build a minimal instance/model as the existing frame tests do ...
    // All nacelles default active=false.
    // Drive draw_model and assert the shader's u_nacelle_count == 0 path,
    // confirming the production glow term is unchanged.
}
```

If `frame_test.cc` has no uniform-introspection harness, instead extend `nacelle_region_test.cc` with a pure test that an all-`active=false` array yields `nn == 0` by replicating the small counting loop from frame.cc — keeping the byte-identical guarantee covered without GL.

- [ ] **Step 2: Run the test**

Run:
```bash
cmake --build build --target renderer_tests -j >/dev/null 2>&1 && \
GALLIUM_DRIVER=llvmpipe ./build/native/tests/renderer/renderer_tests --gtest_filter='*Nacelle*'
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add native/tests/renderer/
git commit -m "test(vfx): nacelle dimming leaves production glow path untouched

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Run all renderer + scenegraph + warp_glow tests (focused, never full pytest):**

```bash
cmake --build build -j >/dev/null 2>&1
GALLIUM_DRIVER=llvmpipe ./build/native/tests/renderer/renderer_tests --gtest_filter='NacelleRegion.*:*Nacelle*'
uv run pytest tests/engine/appc/test_warp_glow.py -q
```
Expected: all PASS.

- [ ] **Confirm production path byte-identical:** a ship with no warp subsystem, and a ship whose warp pods are all healthy, render with `dim_target == 1.0` and (for healthy) `disable_time < 0`, so `nacelle_glow_mult` returns 1.0 everywhere — glow unchanged.

---

## Notes for the implementer

- **`set_vec4_array` / `set_int` / `set_mat4`** are existing `Shader` methods (used by the decal block in frame.cc). Setting a uniform the shader optimized out is a silent no-op here — that is why Task 4 (upload) can land before Task 5 (shader) without crashing.
- **Coordinate frame:** the one risk flagged in the spec is whether hardpoint positions need the instance-scale division. Task 3 applies `inv = 1/s` to match `damage_decal_add`. If the Galaxy nacelles end up mis-placed in the manual check (Task 8 step 5), that conversion is the first thing to revisit.
- **Axis upgrade (deferred):** if a specific ship's angled nacelle looks wrong, replace the fixed `NACELLE_AXIS` with a PCA of the captured cluster inside `compute_nacelle_region` (covariance + 3×3 symmetric eigensolve). The capsule storage and shader need no changes — only the axis the fit returns.
```
