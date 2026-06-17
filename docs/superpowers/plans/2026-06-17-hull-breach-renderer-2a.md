# Hull Breach Renderer 2a (Carve + Breach MVP) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On a weapon hit, carve a ship's voxel volume and render a see-through breach with the authentic chunky colored "guts" behind it — one believable breach, end-to-end.

**Architecture:** Per-model **source volume** (decoded `*_vox.nif` or voxelized hull, cached) + per-instance **carve field** (24-slot body-frame spheres). The hull fragment shader discards fragments inside carve spheres (see-through holes); a new **breach pass** instance-draws the source volume's solid voxels inside each sphere as colored cubes. Carve-on-hit is wired through the existing decal hit-path. All gated by a Modern-VFX toggle (off ⇒ stock path byte-identical).

**Tech Stack:** C++17, OpenGL **4.1 core** (raised from 3.3 — macOS ceiling; gives tessellation + geometry shaders, no compute), GLSL 330, glm, GoogleTest, Python (engine host scripts), pytest. Builds on the merged `native/src/voxel/` foundation.

**Reference:** spec `docs/superpowers/specs/2026-06-17-hull-breach-renderer-2a-design.md`.

**Scavenge convention:** Several tasks adapt code from the donor branch `feat/hull-damage-hit-trigger` (the rejected tessellation-dents approach, 41 commits behind main — donor, not merge). Where a task says "scavenge", retrieve the named donor file with `git show feat/hull-damage-hit-trigger:<path>` and adapt as the task specifies (retargeting *crater/deform → carve*). The donor code is reproduced inline where it's adapted. **Do NOT bring the tessellation-displacement geometry** (`opaque_deform.*`, the deform draw path).

---

## File Structure

- `native/src/renderer/window.cc` — **modify**: GL 3.3 → 4.1 context hints.
- `native/src/renderer/include/renderer/gl_caps.h`, `native/src/renderer/gl_caps.cc` — **create** (scavenge): GL capability query.
- `native/src/scenegraph/include/scenegraph/hull_carve.h`, `native/src/scenegraph/src/hull_carve.cc` — **create**: per-instance carve-sphere field.
- `native/src/scenegraph/include/scenegraph/instance.h` — **modify**: add `HullCarveField carve;`.
- `native/src/voxel/include/voxel/source_cache.h`, `native/src/voxel/src/source_cache.cc` — **create**: `model→VoxelVolume` cache.
- `native/src/host/host_bindings.cc` — **modify**: `hull_carve_add` binding, carve-sphere uniform upload in the opaque pass, breach-pass invocation, toggle binding.
- `native/src/renderer/shaders/opaque.frag`, `skinned.frag` — **modify**: carve-sphere discard.
- `native/src/renderer/include/renderer/breach_pass.h`, `native/src/renderer/breach_pass.cc`, `native/src/renderer/shaders/breach.vert`, `breach.frag` — **create**: interior voxel splat.
- `native/src/renderer/frame.cc` — **modify**: `dauntless_hull_damage::g_enabled` flag.
- `engine/appc/damage_eligibility.py` — **create** (scavenge `deform_eligibility.py`).
- `engine/appc/hull_carve.py` — **create** (scavenge `hull_deformation.py`, retargeted).
- `engine/appc/hit_feedback.py` — **modify**: emit `hull_carve_add`.
- `engine/host_loop.py` — **modify**: per-tick eligibility refresh + mission reset.
- `engine/renderer.py` — **modify**: `set_hull_damage_enabled`.
- `engine/ui/configuration_panel.py`, `native/assets/ui-cef/js/configuration_panel.js` — **modify**: "Hull breaches" toggle.
- Tests: `native/tests/renderer/gl_caps_test.cc`, `native/tests/scenegraph/hull_carve_test.cc`, `native/tests/voxel/source_cache_test.cc`, `native/tests/renderer/breach_pass_test.cc`, `tests/unit/test_hull_carve*.py`, `tests/unit/test_damage_eligibility.py`, `tests/unit/test_configuration_panel.py`.

---

## Task 1: GL 4.1 bump + capability query (scavenge)

**Files:**
- Modify: `native/src/renderer/window.cc`
- Create: `native/src/renderer/include/renderer/gl_caps.h`, `native/src/renderer/gl_caps.cc`
- Modify: the renderer lib CMake source list (add `gl_caps.cc`) and `native/tests/renderer/CMakeLists.txt` (add `gl_caps_test.cc`)
- Test: `native/tests/renderer/gl_caps_test.cc`

- [ ] **Step 1: Write the failing test** — `native/tests/renderer/gl_caps_test.cc`:
```cpp
#include <gtest/gtest.h>
#include <renderer/gl_caps.h>
#include <renderer/window.h>

TEST(GlCaps, ReportsTessellationUnderTestContext) {
    try {
        renderer::Window w(64, 64, "gl-caps-test", /*visible=*/false);
        const renderer::GlCaps caps = renderer::query_gl_caps();
        EXPECT_GE(caps.version_major, 4);              // requested 4.1
        EXPECT_TRUE(caps.tessellation_available);      // GL 4.0+
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}
```

- [ ] **Step 2: Run, verify it fails** — `cmake -B build -S . && cmake --build build -j renderer_tests` → FAIL (no `gl_caps.h`).

- [ ] **Step 3: Implement.** `gl_caps.h`:
```cpp
#pragma once
namespace renderer {
struct GlCaps {
    int  version_major = 0;
    int  version_minor = 0;
    bool tessellation_available = false;  // true iff context is >= GL 4.0
};
GlCaps query_gl_caps();  // requires a current GL context
}  // namespace renderer
```
`gl_caps.cc`:
```cpp
#include "renderer/gl_caps.h"
#include <glad/glad.h>
namespace renderer {
GlCaps query_gl_caps() {
    GlCaps caps;
    glGetIntegerv(GL_MAJOR_VERSION, &caps.version_major);
    glGetIntegerv(GL_MINOR_VERSION, &caps.version_minor);
    caps.tessellation_available = (caps.version_major >= 4);
    return caps;
}
}  // namespace renderer
```
In `window.cc`, change the two context hints:
```cpp
glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 4);
glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 1);
```
(Leave the `CORE_PROFILE` + `FORWARD_COMPAT` hints as-is.) Add `gl_caps.cc` to the renderer library's source list (find where `window.cc` is listed) and `gl_caps_test.cc` to `native/tests/renderer/CMakeLists.txt`.

- [ ] **Step 4: Run, verify pass** — `cmake -B build -S . && cmake --build build -j renderer_tests dauntless && ctest --test-dir build -R GlCaps --output-on-failure`. Then run the FULL renderer suite to confirm the 4.1 bump didn't regress anything: `ctest --test-dir build -R renderer --output-on-failure`. Expected: PASS (GL-context tests may SKIP in headless CI; the build linking `dauntless` must succeed).

- [ ] **Step 5: Commit** — `git add native/src/renderer native/tests/renderer/CMakeLists.txt native/tests/renderer/gl_caps_test.cc && git commit -m "feat(renderer): GL 4.1 context + gl_caps query (scavenged)"`

---

## Task 2: Carve-sphere field (per-instance state)

Adapt the donor `HullCraterField` (`git show feat/hull-damage-hit-trigger:native/src/scenegraph/src/hull_craters.cc`) into a sphere field: drop `depth`/`impact_dir`/`normal`; keep body-frame center + radius, merge-within-`kMergeFactor·radius`, evict-then-FIFO.

**Files:**
- Create: `native/src/scenegraph/include/scenegraph/hull_carve.h`, `native/src/scenegraph/src/hull_carve.cc`
- Modify: `native/src/scenegraph/CMakeLists.txt` (add `hull_carve.cc`), `native/tests/scenegraph/CMakeLists.txt` (add `hull_carve_test.cc`)
- Test: `native/tests/scenegraph/hull_carve_test.cc`

- [ ] **Step 1: Write the failing test** — `native/tests/scenegraph/hull_carve_test.cc`:
```cpp
#include <gtest/gtest.h>
#include <scenegraph/hull_carve.h>
using scenegraph::HullCarveField;

TEST(HullCarveField, AddMergeEvict) {
    HullCarveField f;
    EXPECT_EQ(f.count(), 0u);
    f.add({0,0,0}, 2.0f);
    EXPECT_EQ(f.count(), 1u);
    // Within kMergeFactor*radius (0.5*2=1.0): merges, grows radius, no new slot.
    f.add({0.5f,0,0}, 3.0f);
    EXPECT_EQ(f.count(), 1u);
    EXPECT_FLOAT_EQ(f.slots()[0].radius, 3.0f);   // grew to the wider re-hit
    // Far apart: new slot.
    f.add({100,0,0}, 2.0f);
    EXPECT_EQ(f.count(), 2u);
}

TEST(HullCarveField, EvictsSmallestWhenFull) {
    HullCarveField f;
    for (std::size_t i = 0; i < HullCarveField::kMaxCarves; ++i)
        f.add({float(i)*1000.f, 0, 0}, 5.0f);   // all far apart, all radius 5
    EXPECT_EQ(f.count(), HullCarveField::kMaxCarves);
    // One more, far away, with a tiny radius would itself be the smallest, so
    // give it a LARGE radius so an existing slot is the eviction victim.
    f.add({999000.f, 0, 0}, 50.0f);
    EXPECT_EQ(f.count(), HullCarveField::kMaxCarves);  // still capped
}
```

- [ ] **Step 2: Run, verify it fails** — `cmake --build build -j scenegraph_tests` → FAIL (`hull_carve.h` not found).

- [ ] **Step 3: Implement.** `hull_carve.h`:
```cpp
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <glm/glm.hpp>
namespace scenegraph {

/// One carve sphere, body frame, model units. A carve never ages out; it only
/// grows when the same region is re-hit. Runtime VFX only — never serialized.
struct HullCarve {
    glm::vec3     center_body{0.0f};
    float         radius = 0.0f;
    std::uint64_t seq = 0;     // insertion order (0 = never used)
    bool          active = false;
};

/// Fixed-capacity per-instance carve store: merge-grow-then-evict.
class HullCarveField {
public:
    static constexpr std::size_t kMaxCarves = 24;
    static constexpr float kMergeFactor = 0.5f;   // merge within 0.5 * radius

    /// Insert a carve sphere (body frame, model units). If an active carve lies
    /// within kMergeFactor*radius, grow it (max radius) and refresh its age
    /// instead of allocating. Otherwise take a free slot, else evict the
    /// smallest carve (tie-break: oldest).
    void add(const glm::vec3& center_body, float radius);

    std::size_t count() const;
    const std::array<HullCarve, kMaxCarves>& slots() const { return slots_; }

private:
    std::array<HullCarve, kMaxCarves> slots_{};
    std::uint64_t next_seq_ = 1;
};

}  // namespace scenegraph
```
`hull_carve.cc`:
```cpp
#include "scenegraph/hull_carve.h"
#include <algorithm>
namespace scenegraph {

void HullCarveField::add(const glm::vec3& center_body, float radius) {
    const float merge_dist = kMergeFactor * radius;
    for (auto& c : slots_) {
        if (!c.active) continue;
        if (glm::length(center_body - c.center_body) <= merge_dist) {
            c.radius = std::max(c.radius, radius);
            c.center_body = center_body;   // freshest center
            c.seq = next_seq_++;           // refresh age
            return;
        }
    }
    HullCarve* target = nullptr;
    for (auto& c : slots_) { if (!c.active) { target = &c; break; } }
    if (target == nullptr) {
        // Evict the smallest carve; tie-break on oldest (smallest seq).
        HullCarve* victim = &slots_[0];
        for (auto& c : slots_) {
            if (c.radius < victim->radius ||
                (c.radius == victim->radius && c.seq < victim->seq)) {
                victim = &c;
            }
        }
        target = victim;
    }
    *target = HullCarve{center_body, radius, next_seq_++, /*active=*/true};
}

std::size_t HullCarveField::count() const {
    std::size_t n = 0;
    for (const auto& c : slots_) if (c.active) ++n;
    return n;
}

}  // namespace scenegraph
```
Add `src/hull_carve.cc` to `native/src/scenegraph/CMakeLists.txt` and `hull_carve_test.cc` to `native/tests/scenegraph/CMakeLists.txt`.

- [ ] **Step 4: Run, verify pass** — `cmake --build build -j scenegraph_tests && ctest --test-dir build -R HullCarveField --output-on-failure` → PASS.

- [ ] **Step 5: Commit** — `git add native/src/scenegraph native/tests/scenegraph && git commit -m "feat(scenegraph): per-instance hull carve-sphere field"`

---

## Task 3: Instance integration

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h`

- [ ] **Step 1: Write the failing test** — append to `native/tests/scenegraph/hull_carve_test.cc`:
```cpp
#include <scenegraph/instance.h>
TEST(Instance, HasCarveField) {
    scenegraph::Instance inst;
    EXPECT_EQ(inst.carve.count(), 0u);
    inst.carve.add({1,2,3}, 4.0f);
    EXPECT_EQ(inst.carve.count(), 1u);
}
```

- [ ] **Step 2: Run, verify it fails** — `cmake --build build -j scenegraph_tests` → FAIL (`Instance` has no `carve`).

- [ ] **Step 3: Implement.** In `instance.h`, add the include near the existing `#include "scenegraph/damage_decals.h"`:
```cpp
#include "scenegraph/hull_carve.h"
```
and, immediately after the `DamageDecalRing decals;` member, add:
```cpp
    /// Per-instance hull carve spheres (body frame, model units). Drives the
    /// see-through breach holes and the interior voxel splat. Runtime VFX only
    /// — never serialized to saves.
    HullCarveField carve;
```

- [ ] **Step 4: Run, verify pass** — `cmake --build build -j scenegraph_tests && ctest --test-dir build -R "Instance.HasCarveField" --output-on-failure` → PASS.

- [ ] **Step 5: Commit** — `git add native/src/scenegraph && git commit -m "feat(scenegraph): Instance carries a hull carve field"`

---

## Task 4: Source-volume cache

A `ModelHandle → VoxelVolume` cache: decode the ship's `*_vox.nif` sibling if present, else voxelize the hull. `assets::Model` carries its `source` path; the `_vox.nif` sibling is `<stem>_vox.nif` next to it.

**Files:**
- Create: `native/src/voxel/include/voxel/source_cache.h`, `native/src/voxel/src/source_cache.cc`
- Modify: `native/src/voxel/CMakeLists.txt` (add `src/source_cache.cc`), `native/tests/voxel/CMakeLists.txt` (add `source_cache_test.cc`)
- Test: `native/tests/voxel/source_cache_test.cc`

- [ ] **Step 1: Write the failing test** — `native/tests/voxel/source_cache_test.cc`:
```cpp
#include <gtest/gtest.h>
#include <voxel/source_cache.h>
#include <filesystem>

// The vox-path derivation is pure and unit-testable without assets:
TEST(SourceCache, DerivesVoxSiblingPath) {
    namespace fs = std::filesystem;
    EXPECT_EQ(voxel::vox_sibling_path("data/Models/Ships/Galaxy/Galaxy.nif"),
              fs::path("data/Models/Ships/Galaxy/Galaxy_vox.nif"));
    EXPECT_EQ(voxel::vox_sibling_path("a/b/Foo.NIF"),
              fs::path("a/b/Foo_vox.NIF"));   // preserve original extension case
}

TEST(SourceCache, GalaxyDecodesFromVoxSibling) {
    namespace fs = std::filesystem;
    fs::path hull = fs::path(OPEN_STBC_PROJECT_ROOT)
        / "game/data/Models/Ships/Galaxy/Galaxy.nif";
    if (!fs::exists(hull)) GTEST_SKIP() << "BC asset absent";
    voxel::SourceVolumeCache cache;
    const voxel::VoxelVolume& v = cache.get_for_hull(hull);
    // Galaxy has a _vox.nif → decoded interior-node lattice (30,42,9).
    EXPECT_EQ(v.dims.x, 30);
    EXPECT_EQ(v.dims.y, 42);
    EXPECT_EQ(v.dims.z, 9);
    // Cached: second call returns the same object.
    const voxel::VoxelVolume& v2 = cache.get_for_hull(hull);
    EXPECT_EQ(&v, &v2);
}
```

- [ ] **Step 2: Run, verify it fails** — `cmake --build build -j voxel_tests` → FAIL (`source_cache.h` not found).

- [ ] **Step 3: Implement.** `source_cache.h`:
```cpp
#pragma once
#include <filesystem>
#include <unordered_map>
#include <string>
#include <voxel/volume.h>
namespace voxel {

/// "<stem>_vox<ext>" sibling of a hull nif path (preserves extension case).
std::filesystem::path vox_sibling_path(const std::filesystem::path& hull_nif);

/// Caches one intact source VoxelVolume per hull nif path. Decodes the
/// ship's *_vox.nif when present (exact BC volume); otherwise voxelizes the
/// hull mesh (mod-ship fallback). Built lazily, shared across instances.
class SourceVolumeCache {
public:
    const VoxelVolume& get_for_hull(const std::filesystem::path& hull_nif);
private:
    std::unordered_map<std::string, VoxelVolume> by_path_;
};

}  // namespace voxel
```
`source_cache.cc`:
```cpp
#include "voxel/source_cache.h"
#include <voxel/voxelize.h>
#include <nif/file.h>
#include <nif/block.h>
#include <assets/model.h>          // build_model
#include <assets/model_build.h>    // adjust include to the real build_model header

namespace voxel {

std::filesystem::path vox_sibling_path(const std::filesystem::path& hull_nif) {
    std::filesystem::path p = hull_nif;
    const std::string ext = p.extension().string();          // ".nif" / ".NIF"
    p.replace_filename(p.stem().string() + "_vox" + ext);
    return p;
}

const VoxelVolume& SourceVolumeCache::get_for_hull(
        const std::filesystem::path& hull_nif) {
    const std::string key = hull_nif.string();
    auto it = by_path_.find(key);
    if (it != by_path_.end()) return it->second;

    VoxelVolume vol;
    const std::filesystem::path vox = vox_sibling_path(hull_nif);
    if (std::filesystem::exists(vox)) {
        nif::File f = nif::load(vox);
        const nif::NiBinaryVoxelData* vd = nullptr;
        for (const auto& b : f.blocks)
            if (auto* q = std::get_if<nif::NiBinaryVoxelData>(&b)) vd = q;
        if (vd) vol = from_nif_voxel_data(*vd);
    }
    if (vol.occ.empty()) {
        // Fallback: voxelize the hull mesh. Use the foundation's GL-free
        // tri walk + an explicit grid matching BC's resolution rule. For 2a,
        // a default resolution is acceptable (see spec); reuse voxelize().
        nif::File hf = nif::load(hull_nif);
        auto tris = collect_hull_triangles_from_nif(hf);
        // Pick a reasonable default grid (e.g. 48^3) — refined in 2b.
        vol = voxelize_tris(tris, glm::ivec3(48, 48, 48));   // see note below
    }
    auto [ins, _] = by_path_.emplace(key, std::move(vol));
    return ins->second;
}

}  // namespace voxel
```
NOTE: the foundation exposes `voxelize(const assets::Model&, glm::ivec3)` and `collect_hull_triangles_from_nif(const nif::File&)` and `voxelize_into(tris, dims, origin, cell)`. There is no `voxelize_tris(tris, dims)` free function yet. EITHER (a) add a tiny `voxelize_tris(tris, dims)` overload to `voxelize.cc` that computes the bbox like `voxelize()` does then calls `voxelize_into`, OR (b) build an `assets::Model` and call `voxelize(model, dims)`. Prefer (a) — it reuses `collect_hull_triangles_from_nif` (GL-free) and avoids needing a full model build. Add `voxelize_tris` declaration to `voxelize.h` and implement it by factoring the bbox logic out of `voxelize()`. Keep `voxelize()` behavior unchanged (delegate).

Add `src/source_cache.cc` to `native/src/voxel/CMakeLists.txt` and `source_cache_test.cc` to `native/tests/voxel/CMakeLists.txt`.

- [ ] **Step 4: Run, verify pass** — `cmake --build build -j voxel_tests && ctest --test-dir build -R "SourceCache|Voxel" --output-on-failure` → PASS (the decode test runs against the real Galaxy asset; the derive test always runs).

- [ ] **Step 5: Commit** — `git add native/src/voxel native/tests/voxel && git commit -m "feat(voxel): source-volume cache (decode _vox sibling, voxelize fallback)"`

---

## Task 5: `hull_carve_add` host binding

Mirror `damage_decal_add` (`host_bindings.cc` ~1446–1478): world→body transform, divide by instance scale to model units, push to the instance's carve field.

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Test: `tests/unit/test_hull_carve_binding.py` (Python, drives the binding via `_dauntless_host`)

- [ ] **Step 1: Write the failing test** — `tests/unit/test_hull_carve_binding.py`:
```python
import pytest
_h = pytest.importorskip("_dauntless_host")

def test_hull_carve_add_present_and_callable():
    # Binding exists with the documented signature; calling on an invalid id
    # must not crash (mirrors damage_decal_add's tolerance).
    assert hasattr(_h, "hull_carve_add")
    _h.hull_carve_add((0, 0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 10.0, 0.0)
```
(If the project's binding tests use a different import/fixture for `_dauntless_host`, follow that existing pattern — see `tests/unit/test_hull_deform_binding.py` on the donor branch for the shape.)

- [ ] **Step 2: Run, verify it fails** — `uv run pytest tests/unit/test_hull_carve_binding.py -q` → FAIL (`_dauntless_host` has no `hull_carve_add`), or SKIP if the module isn't built. Build first: `cmake --build build -j dauntless`.

- [ ] **Step 3: Implement.** In `host_bindings.cc`, next to `damage_decal_add`, add (adapt names to the real `g_world` / `world_to_body` helpers used by `damage_decal_add`):
```cpp
m.def("hull_carve_add",
      [](scenegraph::InstanceId id,
         std::tuple<float,float,float> world_point,
         std::tuple<float,float,float> world_normal,   // accepted for symmetry; unused in 2a (sphere carve)
         float radius, float /*time*/) {
          auto* inst = g_world.get(id);
          if (!inst) return;
          const glm::vec3 pw{std::get<0>(world_point), std::get<1>(world_point), std::get<2>(world_point)};
          const glm::vec3 pb = scenegraph::world_to_body(inst->world, pw);
          const float s = glm::length(glm::vec3(inst->world[0]));   // instance scale
          const float radius_model = (s > 0.0f) ? radius / s : radius;
          inst->carve.add(pb, radius_model);
      },
      py::arg("instance_id"), py::arg("world_point"), py::arg("world_normal"),
      py::arg("radius"), py::arg("time"));
```
(The `world_normal` and `time` args are kept so the Python emission path mirrors `damage_decal_add`; 2a carves a sphere centered at the impact point and ignores them. A 2b refinement may offset the sphere inward along the normal.)

- [ ] **Step 4: Run, verify pass** — `cmake --build build -j dauntless && uv run pytest tests/unit/test_hull_carve_binding.py -q` → PASS.

- [ ] **Step 5: Commit** — `git add native/src/host/host_bindings.cc tests/unit/test_hull_carve_binding.py && git commit -m "feat(host): hull_carve_add binding (world->body sphere carve)"`

---

## Task 6: Carve trigger (engine, scavenged + retargeted)

Scavenge the eligibility selector verbatim and the damage→radius mapping retargeted (no depth), then emit from `hit_feedback`.

**Files:**
- Create: `engine/appc/damage_eligibility.py` (scavenge `deform_eligibility.py`, rename module)
- Create: `engine/appc/hull_carve.py` (scavenge `hull_deformation.py`, drop depth)
- Modify: `engine/appc/hit_feedback.py` (emit), `engine/host_loop.py` (per-tick refresh + mission reset)
- Test: `tests/unit/test_damage_eligibility.py`, `tests/unit/test_hull_carve_mapping.py`, `tests/unit/test_hull_carve_emission.py`

- [ ] **Step 1: Write the failing tests.** `tests/unit/test_hull_carve_mapping.py`:
```python
from engine.appc import hull_carve

def test_should_carve_threshold():
    assert hull_carve.should_carve(50.0) is True
    assert hull_carve.should_carve(5.0) is False

def test_carve_radius_floored_and_scaled():
    assert hull_carve.carve_radius_gu(0.0) == hull_carve.MIN_CARVE_RADIUS_GU
    assert hull_carve.carve_radius_gu(1.0) >= hull_carve.MIN_CARVE_RADIUS_GU
```
`tests/unit/test_damage_eligibility.py` — scavenge the donor `test_deform_eligibility.py` (`git show feat/hull-damage-hit-trigger:tests/unit/test_deform_eligibility.py`), rename imports to `engine.appc.damage_eligibility`. It already covers player-always, the cap, size-only fallback, and determinism.

- [ ] **Step 2: Run, verify they fail** — `uv run pytest tests/unit/test_hull_carve_mapping.py tests/unit/test_damage_eligibility.py -q` → FAIL (modules missing).

- [ ] **Step 3: Implement.**
  - `engine/appc/damage_eligibility.py`: copy donor `deform_eligibility.py` verbatim (it's approach-agnostic — "which ships may accumulate damage = player + capped nearest/largest"). Rename only the module docstring's "deformation/crater" wording to "damage/carve". Keep `select_eligible/set_current/current/is_eligible/reset/update`.
  - `engine/appc/hull_carve.py`: copy donor `hull_deformation.py` but DROP depth (carving is a sphere; no displacement depth). Keep:
```python
MIN_CARVE_HULL = 40.0          # below this: scorch decal only, no carve
CARVE_RADIUS_SCALE = 1.5
MIN_CARVE_RADIUS_GU = 0.25
CARVE_EMIT_INTERVAL = 0.25     # game-seconds between carves on one ship

def should_carve(absorbed_hull: float) -> bool:
    return float(absorbed_hull) >= MIN_CARVE_HULL

def carve_radius_gu(splash_radius_gu: float) -> float:
    return max(MIN_CARVE_RADIUS_GU, float(splash_radius_gu) * CARVE_RADIUS_SCALE)
```
  (Drop `crater_depth_gu`, `MAX_CRATER_DEPTH_GU`, `DEPTH_GU_PER_HULL`, and `impact_direction` — not needed for a centered sphere carve in 2a.)
  - `engine/appc/hit_feedback.py`: in `dispatch()`, in the same block that adds the scorch decal (after `host.damage_decal_add(...)`), add a carve emission. Mirror the donor `hit_feedback.py` diff (`git show feat/hull-damage-hit-trigger:engine/appc/hit_feedback.py`), retargeted:
```python
        # Hull carve (breach): heavier than scorch, eligible ships only, throttled.
        if (absorbed_hull > 0.0 and normal is not None and persist_decal
                and hull_carve.should_carve(absorbed_hull)
                and damage_eligibility.is_eligible(target)
                and _hull_carve_enabled()):
            now = damage_decals.current_game_time()
            last = _last_carve_time.get((ship_id,), -1e9)
            if now - last >= hull_carve.CARVE_EMIT_INTERVAL:
                _last_carve_time[(ship_id,)] = now
                host.hull_carve_add(
                    instance_id, world_point, world_normal,
                    hull_carve.carve_radius_gu(r_hit), now)
```
  Wire `_hull_carve_enabled()` to read the renderer toggle state (Task 7 exposes it; for now a module flag defaulting True, set by the config path). Add the `_last_carve_time` dict and imports (`from engine.appc import hull_carve, damage_eligibility`).
  - `engine/host_loop.py`: where combat advances per tick, call `damage_eligibility.update(ships)` once per combat tick before hits are processed (mirror the donor `host_loop.py` diff), and call `damage_eligibility.reset()` on mission swap (alongside the existing decal/VFX resets).

- [ ] **Step 4: Run, verify pass** — `uv run pytest tests/unit/test_hull_carve_mapping.py tests/unit/test_damage_eligibility.py tests/unit/test_hull_carve_emission.py -q` → PASS. For emission, scavenge/retarget the donor `test_deform_emission.py` (gated on threshold + eligibility + throttle; asserts `host.hull_carve_add` called with expected radius, and NOT called when ineligible / below threshold / throttled / toggle off).

- [ ] **Step 5: Commit** — `git add engine/appc/damage_eligibility.py engine/appc/hull_carve.py engine/appc/hit_feedback.py engine/host_loop.py tests/unit/test_damage_eligibility.py tests/unit/test_hull_carve_mapping.py tests/unit/test_hull_carve_emission.py && git commit -m "feat(damage): carve-on-hit trigger + eligibility (scavenged, retargeted)"`

---

## Task 7: "Hull breaches" Modern-VFX toggle (scavenged)

Scavenge the donor "Procedural hull damage" toggle full stack, renamed "Hull breaches". Pattern mirrors `dauntless_specular`/`rim`/`hdr`.

**Files:**
- Modify: `native/src/renderer/frame.cc` (add `namespace dauntless_hull_damage { bool g_enabled = true; }` + accessor, mirroring `dauntless_decals`)
- Modify: `native/src/host/host_bindings.cc` (`hull_damage_set_enabled` binding → sets the flag)
- Modify: `engine/renderer.py` (`set_hull_damage_enabled(bool)` → `_h.hull_damage_set_enabled`)
- Modify: `engine/ui/configuration_panel.py` (add `hull_damage_on` to `SettingsSnapshot`, the toggle row, dispatch handler), `native/assets/ui-cef/js/configuration_panel.js` (render the toggle)
- Modify: `engine/host_loop.py` (pass `set_hull_damage=r.set_hull_damage_enabled` into the panel init, mirroring `set_decals`)
- Test: extend `tests/unit/test_configuration_panel.py` (toggle round-trips), mirroring the donor diff.

- [ ] **Step 1: Write the failing test** — extend `tests/unit/test_configuration_panel.py` with a `hull_damage` toggle case mirroring the existing `decals` toggle test (scavenge the donor `test_configuration_panel.py` diff: `git show feat/hull-damage-hit-trigger:tests/unit/test_configuration_panel.py`). Assert toggling emits the `set_hull_damage` applier with the new value.

- [ ] **Step 2: Run, verify it fails** — `uv run pytest tests/unit/test_configuration_panel.py -q` → FAIL.

- [ ] **Step 3: Implement** the full stack mirroring the existing `decals` toggle end-to-end (use the donor diffs as the template for each file; rename "procedural_damage"/"Procedural hull damage" → "hull_damage"/"Hull breaches"). The C++ flag defaults true; the Python emission gate `_hull_carve_enabled()` (Task 6) reads it via the config path.

- [ ] **Step 4: Run, verify pass** — `cmake --build build -j dauntless && uv run pytest tests/unit/test_configuration_panel.py -q` → PASS.

- [ ] **Step 5: Commit** — `git add native/src/renderer/frame.cc native/src/host/host_bindings.cc engine/renderer.py engine/ui/configuration_panel.py native/assets/ui-cef/js/configuration_panel.js engine/host_loop.py tests/unit/test_configuration_panel.py && git commit -m "feat(config): Modern-VFX 'Hull breaches' toggle (scavenged)"`

---

## Task 8: Hole clip in the hull shader

Add a carve-sphere uniform array to `opaque.frag` + `skinned.frag` and `discard` fragments inside any active sphere. Reconstruct `p_body` from the existing `v_position_ws` + `u_ship_world_inv` (already uploaded for decals). Upload the carve spheres per-instance in the opaque draw path, gated by the toggle.

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag`, `native/src/renderer/shaders/skinned.frag`
- Modify: `native/src/host/host_bindings.cc` or `native/src/renderer/frame.cc` (wherever per-instance decal uniforms are uploaded in `draw_model` — upload carve uniforms beside them)
- Test: `native/tests/renderer/breach_pass_test.cc` (a clip-render test) OR a focused shader/uniform test; plus manual.

- [ ] **Step 1: Write the failing test** — a GL render test (skip without context), `native/tests/renderer/hull_clip_test.cc`: render a unit quad/cube with the opaque shader, one carve sphere covering the center, assert the center pixel is background (discarded) and a corner pixel is not. Follow the existing renderer GL-test pattern (`GTEST_SKIP` on no context; offscreen FBO readback — see `sun_pass_test.cc`/`bloom_pass_test.cc`). Add to `native/tests/renderer/CMakeLists.txt`.

- [ ] **Step 2: Run, verify it fails** — `cmake --build build -j renderer_tests` → FAIL (uniforms/clip not present).

- [ ] **Step 3: Implement.** In `opaque.frag`, mirroring the decal uniform block (`MAX_DECALS`/`u_decal_count`/`u_ship_world_inv`):
```glsl
const int MAX_CARVES = 24;
uniform int  u_carve_count;             // 0 disables the loop entirely
uniform vec4 u_carve[MAX_CARVES];       // center_body.xyz, radius (model units)
```
In `main()`, after `p_body` is computed (the decal path already derives `vec3 p_body = (u_ship_world_inv * vec4(v_position_ws,1.0)).xyz;` — reuse that exact value; if it's local to the decal call, hoist it), add BEFORE lighting:
```glsl
for (int i = 0; i < u_carve_count; ++i) {
    if (distance(p_body, u_carve[i].xyz) < u_carve[i].w) { discard; }
}
```
Apply the identical block to `skinned.frag` (skinned ships can also be carved). Upload, in the per-instance opaque draw (where `u_decal_count`/`u_decal_a..c` are set): set `u_carve_count` and `u_carve[i] = vec4(center_body, radius)` from `inst.carve.slots()` (active only), but ONLY when `dauntless_hull_damage::g_enabled` is true — otherwise set `u_carve_count = 0` (stock path). Cap at `MAX_CARVES`.

- [ ] **Step 4: Run, verify pass** — `cmake --build build -j renderer_tests dauntless && ctest --test-dir build -R "HullClip|renderer" --output-on-failure` → PASS (clip test PASS or SKIP headless; full renderer suite green).

- [ ] **Step 5: Commit** — `git add native/src/renderer native/src/host/host_bindings.cc native/tests/renderer && git commit -m "feat(renderer): carve-sphere fragment discard (see-through holes)"`

---

## Task 9: Breach pass (classic-voxel interior splat)

A new pass that, per damaged instance, instance-draws the source volume's solid voxels inside each carve sphere as small colored cubes (the BC guts look). Follow the `particle_pass` / `hologram_pass` GL plumbing (instanced draw, look up instance→model→source volume).

**Files:**
- Create: `native/src/renderer/include/renderer/breach_pass.h`, `native/src/renderer/breach_pass.cc`, `native/src/renderer/shaders/breach.vert`, `native/src/renderer/shaders/breach.frag`
- Modify: `native/src/host/host_bindings.cc` (instantiate + invoke in `frame()` after the opaque pass, before bloom), `native/src/renderer/pipeline.cc` (register the `breach` program), the renderer CMake list
- Test: `native/tests/renderer/breach_pass_test.cc`

- [ ] **Step 1: Write the failing test** — `native/tests/renderer/breach_pass_test.cc`: construct a `BreachPass`, feed a synthetic `VoxelVolume` (small, a few solid voxels) + one carve sphere, and assert the pass selects the expected number of voxel instances within the sphere (a pure `select_breach_voxels(volume, sphere) -> std::vector<glm::vec3>` helper, unit-tested without GL). Add a GL render test (skip without context) that draws and reads back a non-background pixel. Add to CMake.

- [ ] **Step 2: Run, verify it fails** — `cmake --build build -j renderer_tests` → FAIL.

- [ ] **Step 3: Implement.**
  - Pure helper (unit-testable): `std::vector<glm::vec4> select_breach_voxels(const voxel::VoxelVolume& v, glm::vec3 center_body, float radius)` — for each solid voxel whose body-frame center `origin+(i+.5)*cell` is within `radius` of `center`, emit `vec4(center_body, voxel_color_seed)`. (Color seed = a hash of the voxel index → the multicolor speckle, computed in the shader.)
  - `BreachPass::render(world, camera, lookup_model, source_cache, pipeline)`: for each instance with `carve.count() > 0` (and `dauntless_hull_damage::g_enabled`), get its source volume from the cache (via the model's hull nif path), gather breach voxels across its carve spheres, upload as instanced data, draw unit cubes scaled to `cell`, transformed by `instance.world`. Depth-test ON, depth-write ON (so guts occlude correctly and are visible only through the clipped holes). Follow `particle_pass.cc` for the instanced-VAO mechanics and `hologram_pass.cc` for the per-instance lookup + camera wiring.
  - `breach.vert`: place each instance cube at its body-frame center via `u_model` (instance.world); size = `cell`. `breach.frag`: color from the per-voxel seed → BC multicolor (a cheap hash→rgb), optionally modulated by `Damage.tga` if bound. Keep it `#version 330 core`.
  - Invoke `g_breach_pass->render(...)` in `frame()` immediately AFTER `submit_opaque_in_pass()` (so the clipped hull's holes reveal the guts) and before shields/bloom.

- [ ] **Step 4: Run, verify pass** — `cmake --build build -j renderer_tests dauntless && ctest --test-dir build -R "Breach|renderer" --output-on-failure` → PASS (pure selection test PASS; GL test PASS or SKIP).

- [ ] **Step 5: Commit** — `git add native/src/renderer native/src/host/host_bindings.cc native/tests/renderer && git commit -m "feat(renderer): breach pass — classic colored-voxel interior splat"`

---

## Task 10: End-to-end smoke + manual verification

**Files:**
- Create: `docs/superpowers/notes/2026-06-17-hull-breach-2a-manual-verification.md` (record the manual check)

- [ ] **Step 1: Full build + full native + python suites.** `cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure` and `scripts/run_tests.sh` (watchdog-capped pytest per the project memory). Expected: all green (GL tests may SKIP headless).

- [ ] **Step 2: Manual in-game check.** Run `./build/dauntless`, load a combat mission, damage a Galaxy. Confirm: a see-through hole appears at the impact point with chunky colored guts behind it; soot decal frames it; repeated hits grow/accumulate breaches (≤24); toggling "Hull breaches" off in the config panel removes holes and guts (stock look). Record observations + a screenshot path in the notes file. (Per project memory: do NOT synthetic-click or full-screen-capture Mark's workstation — describe what to look for; Mark drives the manual check.)

- [ ] **Step 3: Commit** — `git add docs/superpowers/notes/2026-06-17-hull-breach-2a-manual-verification.md && git commit -m "docs(damage): hull-breach 2a manual verification notes"`

---

## Self-Review

**Spec coverage:**
- Source-volume cache (decode/voxelize) → Task 4. ✓
- Carve field (per-instance) → Tasks 2–3. ✓
- Carve trigger (eligibility, mapping, emit, throttle, mission-reset) → Task 6. ✓
- Hole clip (fragment discard) → Task 8. ✓
- Classic-voxel interior splat → Task 9. ✓
- Scorch ring reuse → Task 6 (the existing decal add in the same block; carve hits pass through it). ✓
- Config toggle (off ⇒ stock byte-identical) → Tasks 7, 8 (count=0), 9 (skip). ✓
- GL 4.1 bump → Task 1. ✓
- Frame alignment → Task 5 (world→body /scale, mirroring decals) + Task 8 (reuse `u_ship_world_inv` `p_body`) + Task 9 (`origin+(i+.5)*cell`). Verified manually in Task 10. ✓
- Non-goals (rims/remesh, modern interior, debris, serialization) → none present. ✓

**Placeholder scan:** Task 4 flags a real choice (add `voxelize_tris` vs build a Model) with a concrete recommendation — not a placeholder. Tasks 8/9 reference existing templates (`particle_pass`, decal uniform block) the implementer must open; the new code (uniforms, discard loop, selection helper) is shown concretely. The GL render-test readback specifics defer to the existing `sun_pass_test`/`bloom_pass_test` pattern (cited) rather than reproducing FBO boilerplate.

**Type consistency:** `HullCarveField` (`add(center_body, radius)`, `count()`, `slots()`, `kMaxCarves`, `kMergeFactor`) consistent across Tasks 2/3/5/8. `VoxelVolume` (`dims`,`origin`,`cell`,`occ`,`solid`) from the foundation, used in Tasks 4/9. `from_nif_voxel_data`, `collect_hull_triangles_from_nif`, `voxelize_into`/`voxelize_tris` consistent in Task 4. `hull_carve_add` signature consistent across Tasks 5/6. `dauntless_hull_damage::g_enabled` consistent across Tasks 7/8/9.
