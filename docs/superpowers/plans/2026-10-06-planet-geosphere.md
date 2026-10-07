# Planet Geosphere Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw BC planet NIFs as an icosphere whose subdivision level is picked per camera by screen-space silhouette error, with smooth per-pixel normals and analytic equirectangular texturing that lands on the same texels as BC's mesh.

**Architecture:** A geosphere is a *load variant* of the planet NIF model. `AssetCache::load(..., geosphere=true)` builds the NIF normally, then `apply_geosphere` attaches `Model::sphere_map`: four icosphere LOD meshes plus the sphere's body-frame centre. BC's original mesh stays in `meshes[]`. The opaque submitter picks a level per instance per camera and hands it to `draw_model`, which draws `sphere_map.lods[level]` in place of the original mesh and sets `u_sphere_map` so `opaque.frag` derives the normal and UV from the sphere direction. Python opts in through `_load_planet_model` behind a developer toggle (default on).

**Tech Stack:** C++20, OpenGL 4.1 / GLSL 410, GLM, GoogleTest, pybind11, Python 3.11, pytest.

**Spec:** `docs/superpowers/specs/2026-10-06-planet-geosphere-design.md`

## Global Constraints

- **Worktree:** `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/planet-geosphere`, branch `feat/planet-geosphere`. Never commit to `main`.
- **⛔ Banned git commands:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Always stage with an explicit pathspec. To mutate a file temporarily: `cp file /tmp/bak` … `cp /tmp/bak file` … `diff file /tmp/bak`.
- **Build:** `cmake --build build -j` from the worktree root. The build tree is already configured Debug, with `-DPython3_EXECUTABLE=<worktree>/.venv/bin/python3`. Never run cmake from `native/`. Never change `CMAKE_BUILD_TYPE`.
- **Shader edits need a reconfigure** to be copied: `cmake -B build -S .` (no other flags; the cache keeps them), then `cmake --build build -j`. Shader errors appear only at RUNTIME, so a render test must actually run.
- **Python tests:** `uv run pytest <path> -q` from the worktree root.
- **C++ test binaries:**
  - `./build/native/tests/assets/assets_tests --gtest_filter=<pattern>`
  - `./build/native/tests/renderer/renderer_tests --gtest_filter=<pattern>`

  If a binary path differs, find it with `find build -name assets_tests -type f`.
- **Asset-backed tests:** find BC content only through `test_support::game_root()` (`native/tests/support/content_root.h`). Planet NIFs live at `<game_root>/data/Models/Environment/<Name>.NIF`, upper-case `.NIF`. Export `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"` when running a binary by hand. A test with no asset `GTEST_SKIP`s, and the gate fails on an unbaselined skip, so the asset must resolve.
- **Measured constants (spec §2):**
  - The stock planet sphere centre in the body frame is `(-0.736648, 0.368324, 0)` and its radius is `90.0099`.
  - `u = fract(atan2(y,x)/(2π) + 0.75)` and `v = 0.5 − asin(z)/π`, applied to the unit direction from the sphere centre.
  - LOD levels are `{3,4,5,6}` (index 0..3, coarse to fine), with `max_err_px = 0.5`.
- **Byte-identical default:** with `u_sphere_map == 0`, or for any model without `sphere_map`, every existing draw must be unchanged.
- **Gate before merging:** `scripts/check_tests.sh` must pass with no new entries in `tests/known_failures.txt`.

## Review Focus

1. **The pole.** `atan(0, 0)` is undefined in GLSL. A fragment exactly at the pole must not produce NaN, because NaN feeds bloom and produces black squares. **Test:** Task 1 `SphereUv.PoleIsFinite`; Task 4 shader guard on `length(dir.xy) < 1e-6`.
2. **Bridge viewscreen RTT.** It renders the planet with a different viewport height from the main view, so the pick must use the bound viewport, not a cached main-window height. **Test:** Task 4 `GeosphereDraw.PickUsesBoundViewportHeight`.
3. **A map planet at about 20× scale.** The world radius must come from the instance's world matrix, not from `sphere_map.radius` alone, or the pick sees a 90-GU sphere and always chooses level 3. **Test:** Task 4 `GeosphereDraw.ScaledInstanceUsesWorldRadius`.
4. **A modded non-sphere planet NIF** (rings, extra shape) must render exactly as its NIF. **Test:** Task 2 `ApplyGeosphere.LeavesMultiMeshModelUntouched` and `LeavesNonSphereUntouched`.
5. **Toggling the developer switch after planets are cached.** The Python `nif_to_handle` cache must not hand a geosphere handle to a non-geosphere request, or the reverse. **Test:** Task 5 `test_planet_model_cache_key_separates_geosphere`.

---

### Task 1: Pure geosphere math: mesh builder, sphere UV, LOD pick

**Files:**
- Create: `native/src/assets/include/assets/geosphere.h`
- Create: `native/src/assets/src/geosphere.cc`
- Modify: `native/src/assets/CMakeLists.txt` (add `src/geosphere.cc` to the `assets` library sources, beside `src/tessellate.cc`)
- Create: `native/tests/assets/cpu/geosphere_test.cc`
- Modify: `native/tests/assets/CMakeLists.txt` (add `cpu/geosphere_test.cc` after `cpu/tessellate_test.cc`)

**Interfaces:**
- Consumes: `assets::MeshCpu` (`native/src/assets/include/assets/mesh.h`).
- Produces:
  ```cpp
  namespace assets {
  inline constexpr std::array<int, 4> kGeosphereLevels{3, 4, 5, 6};
  MeshCpu build_geosphere(int level, float radius, glm::vec3 center = glm::vec3(0.0f));
  glm::vec2 sphere_uv(glm::vec3 unit_dir);
  int pick_geosphere_level(float world_radius, float center_distance,
                           float focal_px, float max_err_px = 0.5f);
  }
  ```

- [ ] **Step 1: Write the failing tests**

`native/tests/assets/cpu/geosphere_test.cc`:

```cpp
// native/tests/assets/cpu/geosphere_test.cc
#include <assets/geosphere.h>

#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <glm/gtc/constants.hpp>

#include <cmath>
#include <filesystem>
#include <variant>

#include <nif/block.h>
#include <nif/file.h>

#include "support/content_root.h"

namespace fs = std::filesystem;

TEST(Geosphere, TriangleCountPerLevel) {
    for (int level = 0; level <= 6; ++level) {
        const auto m = assets::build_geosphere(level, 1.0f);
        EXPECT_EQ(m.indices.size() / 3, 20u * (1u << (2 * level))) << "level " << level;
    }
}

TEST(Geosphere, EveryVertexOnTheRadiusAroundTheCenter) {
    const glm::vec3 c(-0.736648f, 0.368324f, 0.0f);
    const auto m = assets::build_geosphere(4, 90.0099f, c);
    for (const auto& v : m.vertices) {
        EXPECT_NEAR(glm::length(v.position - c), 90.0099f, 1e-3f);
        EXPECT_NEAR(glm::length(v.normal), 1.0f, 1e-5f);
        EXPECT_NEAR(glm::dot(v.normal, glm::normalize(v.position - c)), 1.0f, 1e-5f);
    }
}

TEST(Geosphere, EveryTriangleWindsCcwOutward) {
    const auto m = assets::build_geosphere(3, 1.0f);
    for (std::size_t i = 0; i < m.indices.size(); i += 3) {
        const glm::vec3 a = m.vertices[m.indices[i]].position;
        const glm::vec3 b = m.vertices[m.indices[i + 1]].position;
        const glm::vec3 c = m.vertices[m.indices[i + 2]].position;
        EXPECT_GT(glm::dot(glm::cross(b - a, c - a), a + b + c), 0.0f) << "tri " << i / 3;
    }
}

TEST(Geosphere, VertexUvIsTheSphereUvOfItsDirection) {
    const auto m = assets::build_geosphere(2, 5.0f);
    for (const auto& v : m.vertices) {
        const glm::vec2 want = assets::sphere_uv(glm::normalize(v.position));
        EXPECT_NEAR(v.uv.x, want.x, 1e-6f);
        EXPECT_NEAR(v.uv.y, want.y, 1e-6f);
    }
}

TEST(SphereUv, MatchesTheMeasuredFormulaAtCardinalPoints) {
    // u = fract(atan2(y,x)/2pi + 0.75), v = 0.5 - asin(z)/pi
    auto uv = assets::sphere_uv({1, 0, 0});  EXPECT_NEAR(uv.x, 0.75f, 1e-6f); EXPECT_NEAR(uv.y, 0.5f, 1e-6f);
    uv = assets::sphere_uv({0, -1, 0});      EXPECT_NEAR(uv.x, 0.50f, 1e-6f);
    uv = assets::sphere_uv({-1, 0, 0});      EXPECT_NEAR(uv.x, 0.25f, 1e-6f);
    uv = assets::sphere_uv({0, 0, 1});       EXPECT_NEAR(uv.y, 0.0f, 1e-6f);
    uv = assets::sphere_uv({0, 0, -1});      EXPECT_NEAR(uv.y, 1.0f, 1e-6f);
}

TEST(SphereUv, PoleIsFinite) {
    const glm::vec2 uv = assets::sphere_uv({0, 0, 1});
    EXPECT_TRUE(std::isfinite(uv.x));
    EXPECT_TRUE(std::isfinite(uv.y));
}

TEST(SphereUv, MatchesBcPlanetNifUvs) {
    const fs::path nif = test_support::game_root() / "data/Models/Environment/IcePlanet.NIF";
    if (!fs::is_regular_file(nif)) GTEST_SKIP() << "asset missing: " << nif;
    nif::File f = nif::load(nif);
    int checked = 0;
    for (const auto& b : f.blocks) {
        const auto* d = std::get_if<nif::NiTriShapeData>(&b);
        if (!d) continue;
        ASSERT_FALSE(d->uv_sets.empty());
        for (std::size_t i = 0; i < d->vertices.size(); ++i) {
            const glm::vec3 p(d->vertices[i].x, d->vertices[i].y, d->vertices[i].z);
            const glm::vec3 dir = glm::normalize(p);
            const float bu = d->uv_sets[0][i].u, bv = d->uv_sets[0][i].v;
            // Skip the seam column (BC stores both u=0 and u=1 there) and the
            // pole rings (BC's pole fan stores out-of-range u).
            if (std::abs(dir.z) > 0.98f) continue;
            if (bu < 1e-3f || bu > 1.0f - 1e-3f) continue;
            const glm::vec2 uv = assets::sphere_uv(dir);
            EXPECT_NEAR(uv.x, bu, 1e-4f) << "vertex " << i;
            EXPECT_NEAR(uv.y, bv, 1e-4f) << "vertex " << i;
            ++checked;
        }
    }
    EXPECT_GT(checked, 500);
}

TEST(GeospherePick, OrbitAt150GuOnA3600PlanetPicksLevel5) {
    // d = R + 150; silhouette distance sqrt(d^2 - R^2) = 1050; focal 935 px.
    // Level 4 error ~1.92 px, level 5 ~0.48 px -> index 2 (level 5).
    EXPECT_EQ(assets::pick_geosphere_level(3600.0f, 3750.0f, 935.0f), 2);
}

TEST(GeospherePick, FarAwayPicksTheCoarsestLevel) {
    EXPECT_EQ(assets::pick_geosphere_level(3600.0f, 1.0e6f, 935.0f), 0);
}

TEST(GeospherePick, InsideOrOnTheSpherePicksTheFinestLevel) {
    EXPECT_EQ(assets::pick_geosphere_level(3600.0f, 3600.0f, 935.0f), 3);
    EXPECT_EQ(assets::pick_geosphere_level(3600.0f, 100.0f, 935.0f), 3);
}

TEST(GeospherePick, NeverGetsCoarserAsTheCameraApproaches) {
    int prev = 0;
    for (float d = 2.0e5f; d > 3601.0f; d *= 0.9f) {
        const int lvl = assets::pick_geosphere_level(3600.0f, d, 935.0f);
        EXPECT_GE(lvl, prev) << "d=" << d;
        prev = lvl;
    }
}
```

Check how `nif` is linked for `assets_tests`: `native/tests/assets/CMakeLists.txt` already force-loads `nif`. If `nif/block.h` doesn't resolve, add `nif` to `target_link_libraries(assets_tests ...)`; `assets` normally exports it.

- [ ] **Step 2: Add the test to CMake, build, and confirm it fails to compile** (missing header)

Run: `cmake --build build -j 2>&1 | grep -m3 "geosphere"`
Expected: `fatal error: 'assets/geosphere.h' file not found`.

- [ ] **Step 3: Implement**

`native/src/assets/include/assets/geosphere.h`:

```cpp
// native/src/assets/include/assets/geosphere.h
//
// Planet geosphere (spec docs/superpowers/specs/2026-10-06-planet-geosphere-design.md).
// Pure, GL-free: the icosphere LOD meshes that replace BC's 673-vertex planet
// sphere, BC's measured equirectangular mapping, and the per-camera LOD pick.
#pragma once

#include <array>

#include <glm/glm.hpp>

#include <assets/mesh.h>

namespace assets {

/// Subdivision levels of the four LODs, coarse to fine. Level 3 (1,280 tris)
/// matches BC's planet mesh, so the coarsest LOD is never worse than today.
inline constexpr std::array<int, 4> kGeosphereLevels{3, 4, 5, 6};

/// Icosphere of 20*4^level triangles, CCW seen from outside, every vertex at
/// `radius` from `center`. Normal = unit direction from center; uv =
/// sphere_uv(normal) (a fallback for programs that ignore u_sphere_map --
/// it wraps across the seam, which is why opaque.frag never reads it).
MeshCpu build_geosphere(int level, float radius, glm::vec3 center = glm::vec3(0.0f));

/// BC's planet mapping, measured on all 31 stock planet NIFs (spec §2):
/// u = fract(atan2(y,x)/2pi + 0.75), v = 0.5 - asin(z)/pi, Z-up, seam at +Y.
/// Finite at the poles (u = 0.75 there).
glm::vec2 sphere_uv(glm::vec3 unit_dir);

/// Index into kGeosphereLevels: the coarsest level whose silhouette sagitta,
/// R*theta^2/8 projected at the silhouette distance sqrt(d^2-R^2), is under
/// max_err_px. theta = 63.435deg / 2^level (icosphere mean edge angle).
/// d <= R, or no level meeting the bound, gives the finest index (3).
int pick_geosphere_level(float world_radius, float center_distance,
                         float focal_px, float max_err_px = 0.5f);

}  // namespace assets
```

`native/src/assets/src/geosphere.cc`:

```cpp
// native/src/assets/src/geosphere.cc
#include <assets/geosphere.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <unordered_map>

#include <glm/gtc/constants.hpp>

namespace assets {
namespace {

struct Builder {
    std::vector<glm::vec3> dirs;
    std::vector<std::uint32_t> tris;
    std::unordered_map<std::uint64_t, std::uint32_t> mid;

    std::uint32_t midpoint(std::uint32_t a, std::uint32_t b) {
        const std::uint64_t key = a < b ? (std::uint64_t(a) << 32) | b
                                        : (std::uint64_t(b) << 32) | a;
        auto it = mid.find(key);
        if (it != mid.end()) return it->second;
        dirs.push_back(glm::normalize(dirs[a] + dirs[b]));
        const auto i = static_cast<std::uint32_t>(dirs.size() - 1);
        mid.emplace(key, i);
        return i;
    }
};

}  // namespace

glm::vec2 sphere_uv(glm::vec3 d) {
    const float two_pi = glm::two_pi<float>();
    const float lon = (std::abs(d.x) < 1e-12f && std::abs(d.y) < 1e-12f)
                          ? 0.0f : std::atan2(d.y, d.x);
    float u = lon / two_pi + 0.75f;
    u -= std::floor(u);
    const float v = 0.5f - std::asin(std::clamp(d.z, -1.0f, 1.0f)) / glm::pi<float>();
    return {u, v};
}

MeshCpu build_geosphere(int level, float radius, glm::vec3 center) {
    const float t = (1.0f + std::sqrt(5.0f)) * 0.5f;
    Builder b;
    for (glm::vec3 p : {glm::vec3(-1, t, 0), glm::vec3(1, t, 0), glm::vec3(-1, -t, 0),
                        glm::vec3(1, -t, 0), glm::vec3(0, -1, t), glm::vec3(0, 1, t),
                        glm::vec3(0, -1, -t), glm::vec3(0, 1, -t), glm::vec3(t, 0, -1),
                        glm::vec3(t, 0, 1), glm::vec3(-t, 0, -1), glm::vec3(-t, 0, 1)})
        b.dirs.push_back(glm::normalize(p));
    b.tris = {0, 11, 5, 0, 5, 1, 0, 1, 7, 0, 7, 10, 0, 10, 11, 1, 5, 9, 5, 11, 4,
              11, 10, 2, 10, 7, 6, 7, 1, 8, 3, 9, 4, 3, 4, 2, 3, 2, 6, 3, 6, 8,
              3, 8, 9, 4, 9, 5, 2, 4, 11, 6, 2, 10, 8, 6, 7, 9, 8, 1};
    for (int l = 0; l < level; ++l) {
        std::vector<std::uint32_t> next;
        next.reserve(b.tris.size() * 4);
        for (std::size_t i = 0; i < b.tris.size(); i += 3) {
            const auto a = b.tris[i], c = b.tris[i + 1], e = b.tris[i + 2];
            const auto ab = b.midpoint(a, c), bc = b.midpoint(c, e), ca = b.midpoint(e, a);
            next.insert(next.end(), {a, ab, ca, c, bc, ab, e, ca, bc, ab, bc, ca});
        }
        b.tris = std::move(next);
    }
    // Enforce CCW-outward per triangle (the seed table's winding is not
    // trusted; the test pins the result, not the table).
    for (std::size_t i = 0; i < b.tris.size(); i += 3) {
        const glm::vec3 p0 = b.dirs[b.tris[i]], p1 = b.dirs[b.tris[i + 1]], p2 = b.dirs[b.tris[i + 2]];
        if (glm::dot(glm::cross(p1 - p0, p2 - p0), p0 + p1 + p2) < 0.0f)
            std::swap(b.tris[i + 1], b.tris[i + 2]);
    }
    MeshCpu m;
    m.vertices.reserve(b.dirs.size());
    for (const glm::vec3& d : b.dirs) {
        MeshCpu::Vertex v;
        v.position = center + d * radius;
        v.normal = d;
        v.uv = sphere_uv(d);
        m.vertices.push_back(v);
    }
    m.indices = std::move(b.tris);
    return m;
}

int pick_geosphere_level(float R, float d, float focal_px, float max_err_px) {
    constexpr int kFinest = static_cast<int>(kGeosphereLevels.size()) - 1;
    if (!(d > R) || !(R > 0.0f) || !(focal_px > 0.0f)) return kFinest;
    const float sil = std::max(std::sqrt(d * d - R * R), 1e-3f);
    const float base = glm::radians(63.435f);
    for (int i = 0; i <= kFinest; ++i) {
        const float theta = base / static_cast<float>(1 << kGeosphereLevels[i]);
        const float err_px = R * theta * theta / 8.0f / sil * focal_px;
        if (err_px < max_err_px) return i;
    }
    return kFinest;
}

}  // namespace assets
```

- [ ] **Step 4: Build and run**

Run: `cmake --build build -j && DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" ./build/native/tests/assets/assets_tests --gtest_filter='Geosphere*:SphereUv*:GeospherePick*'`
Expected: all PASS, none SKIPPED. If `MatchesBcPlanetNifUvs` fails, print the failing vertex's `(dir, bu, bv, uv)` and report it. Do NOT loosen the tolerance or change the formula: the formula is a measured spec constant.

- [ ] **Step 5: Commit**

```bash
git add native/src/assets/include/assets/geosphere.h native/src/assets/src/geosphere.cc native/src/assets/CMakeLists.txt native/tests/assets/cpu/geosphere_test.cc native/tests/assets/CMakeLists.txt
git commit -m "feat(assets): geosphere mesh builder, BC sphere UV, per-camera LOD pick"
```

---

### Task 2: `Model::sphere_map`, `apply_geosphere`, and the `AssetCache` geosphere variant

**Files:**
- Modify: `native/src/assets/include/assets/model.h` (add `SphereMap` and `Model::sphere_map`)
- Modify: `native/src/assets/include/assets/geosphere.h` and `native/src/assets/src/geosphere.cc` (add `apply_geosphere`)
- Modify: `native/src/assets/include/assets/cache.h` and `native/src/assets/src/cache.cc` (add a `bool geosphere` load overload; fold `|geosphere` into the NIF cache key)
- Create: `native/tests/assets/cpu/geosphere_apply_test.cc`
- Modify: `native/tests/assets/CMakeLists.txt`

**Interfaces:**
- Consumes: `build_geosphere`, `kGeosphereLevels` (Task 1).
- Produces:
  ```cpp
  // model.h
  struct SphereMap {
      int mesh_index = -1;              // index into Model::meshes of BC's sphere
      glm::vec3 center_body{0.0f};      // sphere centre, model/body frame
      float radius = 0.0f;              // model units
      std::array<Mesh, 4> lods;         // kGeosphereLevels, coarse -> fine
  };
  // in struct Model:
  std::optional<SphereMap> sphere_map;  // empty for every non-geosphere model

  // geosphere.h
  bool apply_geosphere(Model& model, const std::function<Mesh(MeshCpu)>& upload,
                       bool keep_cpu_data);   // true when the gate passed

  // cache.h -- new overload, all others unchanged:
  ModelHandle load(const std::filesystem::path& nif_path,
                   const std::vector<std::filesystem::path>& texture_search_paths,
                   const std::vector<TextureReplacement>& texture_replacements,
                   const std::vector<DecalRequest>& decals,
                   float scale, bool geosphere);
  ```
  The existing 5-arg `load(..., float scale)` forwards with `geosphere=false`.

- [ ] **Step 1: Write the failing tests**

`native/tests/assets/cpu/geosphere_apply_test.cc`. Copy the stub uploaders used by `native/tests/assets/cpu/decal_build_test.cc` (`stub_texture`, `stub_mesh`: read that file and reuse the same definitions locally in an anonymous namespace, since they are file-local there).

```cpp
// native/tests/assets/cpu/geosphere_apply_test.cc
#include <assets/cache.h>
#include <assets/geosphere.h>
#include <assets/model.h>

#include <gtest/gtest.h>
#include <glm/glm.hpp>

#include <filesystem>

#include "support/content_root.h"

namespace fs = std::filesystem;

namespace {
// <paste stub_texture / stub_mesh from decal_build_test.cc here>

assets::AssetCache::Config cpu_config() {
    assets::AssetCache::Config cfg;
    cfg.texture_uploader = stub_texture;
    cfg.mesh_uploader = stub_mesh;
    cfg.keep_cpu_data = true;
    return cfg;
}

fs::path env_dir() { return test_support::game_root() / "data/Models/Environment"; }
}  // namespace

TEST(ApplyGeosphere, StockPlanetGetsFourLodsAroundTheMeasuredCenter) {
    const fs::path nif = env_dir() / "IcePlanet.NIF";
    if (!fs::is_regular_file(nif)) GTEST_SKIP() << "asset missing: " << nif;
    assets::AssetCache cache(cpu_config());
    auto h = cache.load(nif, std::vector<fs::path>{env_dir()}, {}, {}, 1.0f, /*geosphere=*/true);
    ASSERT_TRUE(h->sphere_map.has_value());
    const auto& sm = *h->sphere_map;
    EXPECT_NEAR(sm.center_body.x, -0.736648f, 1e-3f);
    EXPECT_NEAR(sm.center_body.y, 0.368324f, 1e-3f);
    EXPECT_NEAR(sm.center_body.z, 0.0f, 1e-3f);
    EXPECT_NEAR(sm.radius, 90.0099f, 1e-2f);
    ASSERT_EQ(h->meshes.size(), 1u);
    EXPECT_EQ(sm.mesh_index, 0);
    // BC's own mesh is kept, untouched, in meshes[] (AABB / ray trace / other passes).
    EXPECT_EQ(h->meshes[0].index_count(), 1280u * 3u);
    for (std::size_t i = 0; i < 4; ++i) {
        const int level = assets::kGeosphereLevels[i];
        EXPECT_EQ(sm.lods[i].index_count(), 20u * (1u << (2 * level)) * 3u) << i;
        EXPECT_EQ(sm.lods[i].material_index(), h->meshes[0].material_index());
        EXPECT_EQ(sm.lods[i].node_index(), h->meshes[0].node_index());
    }
}

TEST(ApplyGeosphere, PlainLoadHasNoSphereMapAndIsADistinctHandle) {
    const fs::path nif = env_dir() / "IcePlanet.NIF";
    if (!fs::is_regular_file(nif)) GTEST_SKIP() << "asset missing: " << nif;
    assets::AssetCache cache(cpu_config());
    auto plain = cache.load(nif, std::vector<fs::path>{env_dir()}, {}, {}, 1.0f, false);
    auto geo   = cache.load(nif, std::vector<fs::path>{env_dir()}, {}, {}, 1.0f, true);
    EXPECT_FALSE(plain->sphere_map.has_value());
    EXPECT_TRUE(geo->sphere_map.has_value());
    EXPECT_NE(plain.get(), geo.get());
}

TEST(ApplyGeosphere, LeavesNonSphereUntouched) {
    const fs::path nif = test_support::game_root() / "data/Models/Ships/Galaxy/Galaxy.nif";
    const fs::path tex = test_support::game_root() / "data/Models/SharedTextures/FedShips/High";
    if (!fs::is_regular_file(nif)) GTEST_SKIP() << "asset missing: " << nif;
    assets::AssetCache cache(cpu_config());
    auto h = cache.load(nif, std::vector<fs::path>{tex}, {}, {}, 1.0f, true);
    EXPECT_FALSE(h->sphere_map.has_value());
}

TEST(ApplyGeosphere, LeavesMultiMeshModelUntouched) {
    // Build a stock planet model, then add a second mesh to it: the gate
    // requires exactly one mesh.
    const fs::path nif = env_dir() / "IcePlanet.NIF";
    if (!fs::is_regular_file(nif)) GTEST_SKIP() << "asset missing: " << nif;
    assets::AssetCache cache(cpu_config());
    auto h = cache.load(nif, std::vector<fs::path>{env_dir()}, {}, {}, 1.0f, false);
    assets::Model m;   // a fresh model with two copies of the planet's CPU mesh
    m.nodes = h->nodes;
    m.root_node = h->root_node;
    for (int k = 0; k < 2; ++k) {
        assets::Mesh mesh = stub_mesh(*h->meshes[0].cpu_data());
        mesh.set_cpu_data(*h->meshes[0].cpu_data());
        m.meshes.push_back(std::move(mesh));
    }
    EXPECT_FALSE(assets::apply_geosphere(m, stub_mesh, true));
    EXPECT_FALSE(m.sphere_map.has_value());
}
```

If `stub_mesh` does not preserve `material_index` / `node_index` from `MeshCpu`, have `apply_geosphere` set `MeshCpu::material_index` / `node_index` before uploading (the production `upload_mesh` reads them from `MeshCpu`; check `mesh_upload.cc`). If `stub_mesh` does not copy the CPU data, adjust the multi-mesh test to call `set_cpu_data` as written above.

- [ ] **Step 2: Build; confirm it fails** (no `sphere_map`, no 6-arg `load`).

Run: `cmake --build build -j 2>&1 | grep -m3 error`
Expected: errors naming `sphere_map` / no matching `load`.

- [ ] **Step 3: Implement**

1. In `model.h`, add `#include <array>` and `#include <optional>`, the `SphereMap` struct above `struct Model`, and `std::optional<SphereMap> sphere_map;` as the last data member before `trace_accel`. Document it: built only by `apply_geosphere` during construction; `meshes[mesh_index]` stays BC's mesh; drawn only by `draw_model` given a `sphere_level` (Task 4).

2. In `geosphere.cc`, implement `apply_geosphere`:

```cpp
bool apply_geosphere(Model& model, const std::function<Mesh(MeshCpu)>& upload,
                     bool keep_cpu_data) {
    if (model.meshes.size() != 1) return false;
    const Mesh& src = model.meshes[0];
    if (!src.cpu_data() || src.cpu_data()->vertices.empty()) return false;
    const MeshCpu& cpu = *src.cpu_data();
    // Gate (spec §4.2): a UV set, and every vertex within 0.5% of the mean
    // distance from the centroid. Frame-agnostic: the centroid and radius are
    // taken in the mesh's own vertex frame, whatever build_model baked.
    bool has_uv = false;
    glm::vec3 c(0.0f);
    for (const auto& v : cpu.vertices) {
        c += v.position;
        has_uv = has_uv || v.uv != glm::vec2(0.0f);
    }
    if (!has_uv) return false;
    c /= static_cast<float>(cpu.vertices.size());
    float mean = 0.0f;
    for (const auto& v : cpu.vertices) mean += glm::length(v.position - c);
    mean /= static_cast<float>(cpu.vertices.size());
    if (!(mean > 0.0f)) return false;
    for (const auto& v : cpu.vertices)
        if (std::abs(glm::length(v.position - c) - mean) > 0.005f * mean) return false;

    // centre in the body frame: compose the node chain down to the mesh's node.
    glm::mat4 node_world(1.0f);
    for (int n = src.node_index(); n >= 0; n = model.nodes[n].parent_index)
        node_world = model.nodes[n].local_transform * node_world;

    SphereMap sm;
    sm.mesh_index = 0;
    sm.center_body = glm::vec3(node_world * glm::vec4(c, 1.0f));
    sm.radius = mean;
    for (std::size_t i = 0; i < kGeosphereLevels.size(); ++i) {
        MeshCpu lod = build_geosphere(kGeosphereLevels[i], mean, c);
        lod.material_index = cpu.material_index;
        lod.node_index = cpu.node_index;
        Mesh m = upload(lod);
        if (keep_cpu_data) m.set_cpu_data(std::move(lod));
        sm.lods[i] = std::move(m);
    }
    model.sphere_map = std::move(sm);
    return true;
}
```

Before relying on `src.node_index()`, check whether `Mesh` exposes `node_index()` and whether `MeshCpu::node_index` is an index into `Model::nodes`. Read `mesh.h` and `model_build.cc`. If build_model bakes node transforms into the vertices (`mesh_build.cc:80` applies an `extra_model_transform`), the node chain must not be applied twice. In that case use the chain of the node whose `meshes` list contains index 0 (the same chain `draw_model` multiplies by), because that is what places the vertices in the body frame at draw time. The test's expected centre, `(-0.736648, 0.368324, 0)`, is the arbiter.

3. In `cache.cc`, add the 6-arg overload. Make the existing 5-arg overload forward `geosphere=false`. In the NIF branch:
   - append `std::string(geosphere ? "|geosphere" : "")` to `canon`;
   - after `detail::build_model(file, ctx)`, build into a non-const `Model` first, call `apply_geosphere(model, upload, keep_cpu_data)` when `geosphere` is set, then wrap it in `shared_ptr<const Model>`. The uploader is `impl_->config.mesh_uploader` if set, else `upload_mesh`, matching how `ModelBuildContext` resolves it; read `model_build.cc` for the exact fallback.
   - The glTF branch ignores `geosphere`; leave it alone.

- [ ] **Step 4: Run**

Run: `cmake --build build -j && DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" ./build/native/tests/assets/assets_tests`
Expected: the whole binary passes, with no new SKIPs.

- [ ] **Step 5: Commit**

```bash
git add native/src/assets/include/assets/model.h native/src/assets/include/assets/geosphere.h native/src/assets/src/geosphere.cc native/src/assets/include/assets/cache.h native/src/assets/src/cache.cc native/tests/assets/cpu/geosphere_apply_test.cc native/tests/assets/CMakeLists.txt
git commit -m "feat(assets): geosphere load variant — Model::sphere_map with four icosphere LODs"
```

---

### Task 3: Host binding `load_model(..., geosphere=False)`

**Files:**
- Modify: `native/src/host/host_bindings.cc`:
  - `load_model_impl` (~line 651): new `bool geosphere` parameter;
  - fold `"|geosphere"` into `rep_key`;
  - pass it to `g_cache->load`;
  - binding (~line 2888): `py::arg("geosphere") = false`.
- Modify: `engine/renderer.py:186-201` (`load_model` wrapper gains `geosphere: bool = False` and passes it through).
- Test: `tests/host/test_load_model_geosphere.py` (new).

**Interfaces:**
- Consumes: the `AssetCache::load(..., scale, geosphere)` overload (Task 2).
- Produces: Python `engine.renderer.load_model(nif_path, texture_search_path, texture_replacements=None, decals=None, scale=1.0, geosphere=False) -> int`. Distinct handles for `geosphere` True and False on the same NIF; the same handle on a repeat call with the same flag.

- [ ] **Step 1: Write the failing test**

Find how existing host tests bring up a GL context and resolve BC content. Read one existing test under `tests/host/` that calls `load_model`: `grep -ln "load_model" tests/host/*.py`. Mirror its fixture, skip conditions and content-root lookup exactly (through `engine.paths`, never a literal `game/`). Then:

```python
def test_geosphere_load_is_a_distinct_cached_handle(<host fixture>):
    nif = str(paths.game_asset("data/Models/Environment/IcePlanet.NIF"))
    search = [str(p) for p in paths.game_asset_dirs("data/Models/Environment")]
    plain = r.load_model(nif, search)
    geo = r.load_model(nif, search, geosphere=True)
    assert plain != geo
    assert r.load_model(nif, search, geosphere=True) == geo
    assert r.load_model(nif, search) == plain
    # Same bounds: BC's own mesh is kept in the variant.
    assert r.model_aabb(geo) == pytest.approx(r.model_aabb(plain))
```

Adjust the `model_aabb` comparison to its real return shape: it returns `(center, half_extents)`, so compare it element-wise.

- [ ] **Step 2: Run it; expect FAIL** (`TypeError: unexpected keyword argument 'geosphere'`).

Run: `uv run pytest tests/host/test_load_model_geosphere.py -q`

- [ ] **Step 3: Implement** the binding parameter, the dedupe key (`if (geosphere) rep_key += "|geosphere";` after the scale fold), the `g_cache->load(..., scale, geosphere)` call, and the wrapper pass-through. Update the `load_model` docstring in `engine/renderer.py` with one sentence: `geosphere` loads the planet variant (spec 2026-10-06), and a non-sphere NIF loads unchanged.

- [ ] **Step 4: Rebuild and run**

Run: `cmake --build build -j && uv run pytest tests/host/test_load_model_geosphere.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py tests/host/test_load_model_geosphere.py
git commit -m "feat(host): load_model geosphere flag — distinct cached planet variant"
```

---

### Task 4: Draw the geosphere — per-camera LOD pick, sphere-mapped shading

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h:284` (`draw_model` gains a trailing `int sphere_level = -1`)
- Modify: `native/src/renderer/frame.cc`:
  - `draw_model` (~520–880);
  - `FrameSubmitter::submit_opaque` (~1080–1115) and `submit_opaque_in_pass` (~1119–1185): compute and pass the level.
- Modify: `native/src/renderer/shaders/opaque.frag` (uniforms plus the sphere-map branch in `main`)
- Create: `native/tests/renderer/geosphere_draw_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

**Interfaces:**
- Consumes: `Model::sphere_map` and `SphereMap::lods` (Task 2), and `assets::pick_geosphere_level` and `assets::sphere_uv` (Task 1).
- Produces: a renderer-local helper declared in `frame.h` for the tests:
  ```cpp
  /// Per-camera LOD for a sphere-mapped model, or -1 when the model has none.
  /// world radius = sphere_map.radius * length(world[0]); focal from proj and
  /// the CURRENTLY BOUND viewport height (glGetIntegerv(GL_VIEWPORT)).
  int geosphere_level_for(const assets::Model& m, const glm::mat4& world,
                          const scenegraph::Camera& cam);
  ```

- [ ] **Step 1: Write the failing tests**

`native/tests/renderer/geosphere_draw_test.cc`. Model the fixture on `FrameTest` in `native/tests/renderer/frame_test.cc:127-162`: a `renderer::Window`, a `renderer::Pipeline`, an `assets::AssetCache` with the default config (real GL upload), the same `TearDown` resets, and a skip when `IcePlanet.NIF` is absent. Use `test_support::game_root()`, as that file does through its `game_root()` helper.

```cpp
// Instance-world helper: uniform scale s at the origin.
static glm::mat4 scaled(float s) { return glm::scale(glm::mat4(1.0f), glm::vec3(s)); }

TEST_F(GeosphereDrawTest, NonSphereModelHasNoLevel) {
    auto galaxy = cache->load(kGalaxyNif, kGalaxyTex);   // reuse frame_test's constants
    scenegraph::Camera cam; cam.eye = {0, 0, 1500}; cam.target = {0, 0, 0}; cam.aspect = 1.0f;
    EXPECT_EQ(renderer::geosphere_level_for(*galaxy, glm::mat4(1.0f), cam), -1);
}

TEST_F(GeosphereDrawTest, ScaledInstanceUsesWorldRadius) {
    auto geo = load_planet(/*geosphere=*/true);
    glViewport(0, 0, 256, 256);
    scenegraph::Camera cam; cam.aspect = 1.0f;
    // A 20x planet (world radius ~1800) viewed from 100 GU above its surface:
    // a 90-GU-radius pick would say level 3; the world radius demands finer.
    const float R = 90.0099f * 20.0f;
    cam.eye = {0, 0, R + 100.0f}; cam.target = {0, 0, 0};
    const int at_scale = renderer::geosphere_level_for(*geo, scaled(20.0f), cam);
    cam.eye = {0, 0, 90.0099f + 5.0f};   // same ratio of altitude, unscaled
    const int unscaled = renderer::geosphere_level_for(*geo, scaled(1.0f), cam);
    EXPECT_GT(at_scale, unscaled);
}

TEST_F(GeosphereDrawTest, PickUsesBoundViewportHeight) {
    auto geo = load_planet(true);
    scenegraph::Camera cam; cam.aspect = 1.0f;
    cam.eye = {0, 0, 90.0099f * 20.0f + 150.0f}; cam.target = {0, 0, 0};
    glViewport(0, 0, 64, 64);
    const int small = renderer::geosphere_level_for(*geo, scaled(20.0f), cam);
    glViewport(0, 0, 4096, 4096);
    const int big = renderer::geosphere_level_for(*geo, scaled(20.0f), cam);
    EXPECT_GT(big, small);
}

TEST_F(GeosphereDrawTest, SphereMappedPlanetDrawsLitAndFinite) {
    // Fill the 256x256 view with the planet; every covered pixel is finite and
    // the centre is lit. Read back as float from an RGBA16F/32F FBO, as
    // RimEnabledPassProducesNoNonFiniteTexels (frame_test.cc:242) does.
    // Submit via FrameSubmitter::submit_opaque with a world of one instance.
    // ... (copy that test's FBO + readback scaffolding verbatim) ...
    // Assert: no NaN/Inf texel; centre pixel luminance > 0.
}

TEST_F(GeosphereDrawTest, NoSeamDiscontinuityAcrossThePlusYMeridian) {
    // Camera on +Y looking at the planet, so the u=0/1 seam runs vertically
    // through the screen centre. Along the centre row, the colour difference
    // between neighbouring pixels at the seam column must be no larger than the
    // largest neighbour difference elsewhere on the row (x 1.5). This catches a
    // mip-0-to-smallest-mip seam line, which shows up as a 1-px stripe much
    // darker or brighter than its neighbours.
}

TEST_F(GeosphereDrawTest, SphereMapFlagOffMatchesThePlainNif) {
    // Draw the PLAIN load (no sphere_map) and read the centre pixel. It must be
    // identical to what main's code draws: the existing FrameTest suite
    // passing unchanged is the real guard. Here assert only that the plain
    // model draws with u_sphere_map == 0 (glGetUniformiv on the opaque program
    // after the submit) and produces no GL error.
}
```

`load_planet(bool geosphere)` is a fixture helper:

```cpp
assets::ModelHandle load_planet(bool geosphere) {
    const auto dir = test_support::game_root() / "data/Models/Environment";
    return cache->load(dir / "IcePlanet.NIF", std::vector<std::filesystem::path>{dir},
                       {}, {}, 1.0f, geosphere);
}
```

The three bodies left as comments must be written out in full by the implementer, copying the named frame_test.cc scaffolding. A test body that only contains comments is a plan failure, and a reviewer must reject it.

- [ ] **Step 2: Build and run; expect FAIL** (`geosphere_level_for` undeclared).

- [ ] **Step 3: Implement C++**

1. `geosphere_level_for` in `frame.cc`:

```cpp
int geosphere_level_for(const assets::Model& m, const glm::mat4& world,
                        const scenegraph::Camera& cam) {
    if (!m.sphere_map) return -1;
    GLint vp[4] = {0, 0, 0, 0};
    glGetIntegerv(GL_VIEWPORT, vp);
    const float focal_px = cam.proj_matrix()[1][1] * 0.5f * static_cast<float>(vp[3]);
    const float scale = glm::length(glm::vec3(world[0]));
    const glm::vec3 c = glm::vec3(world * glm::vec4(m.sphere_map->center_body, 1.0f));
    const glm::vec3 eye = glm::vec3(glm::inverse(cam.view_matrix())[3]);
    return assets::pick_geosphere_level(m.sphere_map->radius * scale,
                                        glm::length(eye - c), focal_px);
}
```

`world` is render-space (camera-relative origin) and the eye is too, so the distance is consistent.

2. In both `submit_opaque` and `submit_opaque_in_pass`, pass `geosphere_level_for(*m, inst.world, camera)` as the new last argument of `draw_model`. Spell out every defaulted argument up to it, keeping the existing values.

3. In `draw_model`:
   - Before the node loop: `const bool sphere = sphere_level >= 0 && model.sphere_map.has_value();`. If `sphere`, set `prog.set_mat4("u_ship_world_inv", glm::inverse(world))` and `prog.set_vec3("u_sphere_center_body", model.sphere_map->center_body)`.
   - Inside the mesh loop, select the mesh to draw:
     ```cpp
     const bool this_sphere = sphere && mesh_idx == model.sphere_map->mesh_index;
     const auto& draw_mesh = this_sphere
         ? model.sphere_map->lods[static_cast<std::size_t>(std::clamp(sphere_level, 0, 3))]
         : mesh;
     prog.set_int("u_sphere_map", this_sphere ? 1 : 0);
     ```
     Then use `draw_mesh.vao()` and `draw_mesh.index_count()` in the final `glBindVertexArray` / `glDrawElements`. The material, textures and decal mask still come from `mesh`.
   - Set `u_sphere_map` to 0 on **every** mesh draw that is not sphere-mapped. Uniforms persist between draws, so skipping it would leak 1 onto the next ship.

4. Check every other program that links `opaque.frag` (`pipeline.cc:95-114`: minors, far impostors, skinned). An unset `int` uniform defaults to 0, which is the correct value, but confirm those passes never inherit a 1 from a previous opaque draw on the same program object. They are separate program objects; verify that in `pipeline.cc`.

- [ ] **Step 4: Implement the shader**

In `opaque.frag`, next to `u_ship_world_inv` (line ~124):

```glsl
uniform int  u_sphere_map;          // 1 = planet geosphere draw (spec 2026-10-06 §4.4)
uniform vec3 u_sphere_center_body;  // sphere centre, body frame
```

At the top of `main()`, **before** the coverage cutout line (`if (u_coverage_cutout != 0 && texture(u_base_color, v_uv)...`):

```glsl
    // Planet geosphere: normal + UV from the sphere direction. Derivatives
    // are taken here, unconditionally, at the top of main -- never inside a
    // branch and never after a discard (see the dFdx/discard note above).
    vec3 sp_body = (u_ship_world_inv * vec4(v_position_ws, 1.0)).xyz - u_sphere_center_body;
    vec3 sp_dir  = normalize(sp_body + vec3(0.0, 0.0, 1e-20));
    float sp_xy  = length(sp_dir.xy);
    float sp_lon = sp_xy > 1e-6 ? atan(sp_dir.y, sp_dir.x) : 0.0;
    float sp_lat = asin(clamp(sp_dir.z, -1.0, 1.0));
    // Two u parameterisations with seams 180 deg apart; take derivatives
    // from whichever is continuous at this fragment (Tarini) so the seam
    // column samples the right mip instead of the smallest one.
    float sp_u0 = fract(sp_lon * 0.15915494 + 0.75);
    float sp_u1 = fract(sp_lon * 0.15915494 + 0.25);
    vec2  sp_uv = vec2(sp_u0, 0.5 - sp_lat * 0.31830989);
    vec2  sp_du0 = vec2(dFdx(sp_u0), dFdy(sp_u0));
    vec2  sp_du1 = vec2(dFdx(sp_u1), dFdy(sp_u1));
    vec2  sp_du  = dot(sp_du0, sp_du0) <= dot(sp_du1, sp_du1) ? sp_du0 : sp_du1;
    vec2  sp_dx  = vec2(sp_du.x, dFdx(sp_uv.y));
    vec2  sp_dy  = vec2(sp_du.y, dFdy(sp_uv.y));
    vec2  g_uv   = (u_sphere_map != 0) ? sp_uv : v_uv;
```

Then:
- In the coverage cutout line, replace `v_uv` with `g_uv`.
- Replace `vec3 n = normalize(v_normal_ws);` with:
  ```glsl
      vec3 n = (u_sphere_map != 0)
          ? normalize(transpose(mat3(u_ship_world_inv)) * sp_dir)
          : normalize(v_normal_ws);
  ```
  (For rotation × uniform scale, `transpose(mat3(W⁻¹)) = mat3(W) / s²`, so this is the body→world direction up to scale, which the normalize removes. No per-fragment `inverse()`.)
- In `perturb_normal(n, v_position_ws, v_uv, n_sigma)`, replace `v_uv` with `g_uv`.
- Replace the non-impostor base fetch `vec4 base = texture(u_base_color, v_uv);` with:
  ```glsl
      vec4 base = (u_sphere_map != 0)
          ? textureGrad(u_base_color, g_uv, sp_dx, sp_dy)
          : texture(u_base_color, v_uv);
  ```
- In the glow fetch (~1549) and the specular fetch (~1564), replace `v_uv` with `g_uv`.

When `u_sphere_map == 0`, `g_uv == v_uv` and `n` is unchanged, so the output is byte-identical. The extra derivative ops run for every fragment but feed nothing.

⚠️ This shader is known to be fragile on this driver: a discard placed after the derivative block once broke a NaN guard. After the edit you MUST run the whole renderer suite (Step 5), not just the new tests. If `HullClipTest` or `HullFieldClipTest.DegenerateNormalWithGradientOnStaysFinite` fails, report it as BLOCKED rather than reshuffling unrelated shader code.

- [ ] **Step 5: Reconfigure (shader copy), build, and run everything renderer-side**

Run: `cmake -B build -S . && cmake --build build -j && DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" ./build/native/tests/renderer/renderer_tests`
Expected: the whole binary passes, including every pre-existing `FrameTest`, `HullClipTest`, `HullFieldClipTest`, `MinorPass*` and `FarPass*`, plus the new `GeosphereDrawTest.*`. No new SKIPs.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h native/src/renderer/frame.cc native/src/renderer/shaders/opaque.frag native/tests/renderer/geosphere_draw_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): draw planet geosphere LOD per camera with sphere-mapped normal + UV"
```

---

### Task 5: Python opt-in — the `planet_geosphere` toggle, `_load_planet_model`, Developer Options row

**Files:**
- Create: `engine/planet_geosphere.py`
- Modify: `engine/host_loop.py:5275-5304` (`_load_planet_model`)
- Modify: `engine/ui/developer_options_panel.py` (import at ~25; `__init__` ~104; `open`; `render_payload` snapshot + settings; `dispatch_event` toggle; focusables list at ~329)
- Modify: `native/assets/ui-cef/js/developer_options.js` (focusables at ~36; Environments body at ~168)
- Modify: `tests/conftest.py` (~1563, beside the `rock_catalogue` reset: reset `planet_geosphere._enabled = True`)
- Modify: any fake renderer whose `load_model` lacks `**kwargs` and whose test realizes a planet (find them with `uv run pytest tests -q -x`; at least `tests/unit/test_realize_set.py:12`). Add `geosphere=False` to the fake's signature so the doubles mirror the real surface.
- Test: `tests/unit/test_planet_geosphere.py` (new); `tests/unit/test_developer_options_panel.py` (extend)

**Interfaces:**
- Consumes: `engine.renderer.load_model(..., geosphere=...)` (Task 3).
- Produces: `engine.planet_geosphere.enabled() -> bool` and `set_enabled(value: bool) -> None`, defaulting to `True`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_planet_geosphere.py`:

```python
"""Planet geosphere opt-in (spec docs/superpowers/specs/2026-10-06-planet-geosphere-design.md §4.5)."""
from types import SimpleNamespace

from engine import host_loop, planet_geosphere


class _Renderer:
    def __init__(self):
        self.calls = []

    def load_model(self, path, search, texture_replacements=None, decals=None,
                   scale=1.0, geosphere=False):
        self.calls.append((path, geosphere))
        return 100 + len(self.calls)

    def model_aabb(self, handle):
        return (0.0, 0.0, 0.0), (90.0, 90.0, 90.0)


def _cache():
    return SimpleNamespace(nif_to_handle={}, nif_to_extent={}, nif_to_sphere_radius={})


def test_toggle_defaults_on():
    assert planet_geosphere.enabled() is True


def test_load_planet_model_requests_geosphere_when_enabled():
    r = _Renderer()
    host_loop._load_planet_model(r, "/x/IcePlanet.NIF", cache=None)
    assert r.calls == [("/x/IcePlanet.NIF", True)]


def test_load_planet_model_requests_plain_when_disabled():
    planet_geosphere.set_enabled(False)
    r = _Renderer()
    host_loop._load_planet_model(r, "/x/IcePlanet.NIF", cache=None)
    assert r.calls == [("/x/IcePlanet.NIF", False)]


def test_planet_model_cache_key_separates_geosphere():
    r, cache = _Renderer(), _cache()
    on = host_loop._load_planet_model(r, "/x/IcePlanet.NIF", cache=cache)
    planet_geosphere.set_enabled(False)
    off = host_loop._load_planet_model(r, "/x/IcePlanet.NIF", cache=cache)
    assert on[0] != off[0]
    planet_geosphere.set_enabled(True)
    again = host_loop._load_planet_model(r, "/x/IcePlanet.NIF", cache=cache)
    assert again[0] == on[0]
    assert len(r.calls) == 2
```

In `tests/unit/test_developer_options_panel.py`, extend the existing environments-tab tests. Copy the existing `rock_catalogue` test's shape:
- the Environments focusables include `("ctrl", "planet_geosphere")`;
- `dispatch_event("toggle:planet_geosphere")` flips `planet_geosphere.enabled()`;
- the payload's `settings["planet_geosphere"]` follows it;
- the existing `test_every_setting_is_in_the_render_snapshot` passes, so the new field must be in the snapshot.

- [ ] **Step 2: Run; expect FAIL** (`ModuleNotFoundError: engine.planet_geosphere`).

Run: `uv run pytest tests/unit/test_planet_geosphere.py tests/unit/test_developer_options_panel.py -q`

- [ ] **Step 3: Implement**

`engine/planet_geosphere.py`:

```python
"""Developer toggle for the planet geosphere (spec
docs/superpowers/specs/2026-10-06-planet-geosphere-design.md §4.5).

On (default): planet/moon NIFs load as the geosphere variant -- icosphere LODs
picked per camera, sphere-mapped normal + UV. Off: BC's own 673-vertex mesh.
Read at USE by host_loop._load_planet_model, so it applies to planets realized
after toggling. Exists for live A/B comparison only; not persisted.
"""

_enabled = True


def enabled() -> bool:
    return _enabled


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)
```

`_load_planet_model` in `engine/host_loop.py`:
- read `geo = _planet_geosphere.enabled()` once at the top (import `from engine import planet_geosphere as _planet_geosphere` inside the function, or at module top beside the other engine imports, matching how `host_loop` imports `engine.rocks.catalogue`);
- key every cache dict by `key = (nif_path, geo)` instead of `nif_path`;
- call `r_.load_model(nif_path, planet_tex_search, geosphere=geo)`.

Grep `host_loop.py` for any other reader of `nif_to_handle` / `nif_to_extent` / `nif_to_sphere_radius` (`grep -n "nif_to_" engine/host_loop.py`). Each one that looks up a planet NIF must use the same `(nif_path, geo)` key. Update its tests too if they seed those dicts by bare path.

Developer Options: in every place `rock_catalogue` appears in `developer_options_panel.py` and `developer_options.js`, add a `planet_geosphere` sibling directly after it. The JS row label is exactly:
`'Geosphere Planets (off = BC mesh; applies to planets realized after toggling)'`.

`tests/conftest.py`: beside the `_rock_catalogue._enabled = True` reset, add:

```python
        from engine import planet_geosphere as _planet_geosphere
        _planet_geosphere._enabled = True
```

- [ ] **Step 4: Run the targeted tests, then the full Python suite**

Run: `uv run pytest tests/unit/test_planet_geosphere.py tests/unit/test_developer_options_panel.py -q && uv run pytest tests -q -x`
Expected: PASS. A fake renderer raising `TypeError: ... unexpected keyword argument 'geosphere'` means its signature needs `geosphere=False` added; do that in the same task.

- [ ] **Step 5: Commit**

```bash
git add engine/planet_geosphere.py engine/host_loop.py engine/ui/developer_options_panel.py native/assets/ui-cef/js/developer_options.js tests/conftest.py tests/unit/test_planet_geosphere.py tests/unit/test_developer_options_panel.py <each fake-renderer test file you changed>
git commit -m "feat(planets): opt planets into the geosphere variant behind a dev toggle (default on)"
```

---

### Task 6: Gate and docs

**Files:**
- Modify: `CLAUDE.md` (one row in the "Key reference material" table, after the "Rock catalogue" row)

- [ ] **Step 1: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0, with no new failures and no unbaselined skips. Fix any failure in the task that owns it. Never add it to `tests/known_failures.txt`.

- [ ] **Step 2: Add the CLAUDE.md row**

```markdown
| Planet geosphere — icosphere LODs for planet NIFs | `native/src/assets/{include/assets,src}/geosphere.*`, `native/src/renderer/frame.cc:geosphere_level_for`, `native/src/renderer/shaders/opaque.frag` (`u_sphere_map`), `engine/planet_geosphere.py`, `docs/superpowers/specs/2026-10-06-planet-geosphere-design.md` | All 31 stock planet NIFs are ONE 673-vert UV sphere (r 90.0099, centre (−0.736648, 0.368324, 0) via the `planet` node) with an exact equirectangular map, u = fract(atan2(y,x)/2π+0.75), v = 0.5−asin(z)/π. `load_model(..., geosphere=True)` keeps BC's mesh in `meshes[]` (AABB/trace/other passes unchanged) and adds `Model::sphere_map` = 4 icosphere LODs (levels 3–6); the opaque submitter picks one PER CAMERA by 0.5 px silhouette sagitta and `opaque.frag` derives normal + UV from the sphere direction (Tarini dual-seam gradients). Gate: one mesh, all verts within 0.5% of the mean radius — modded non-sphere planets load unchanged. Toggle: Developer Options → Environments → Geosphere Planets (default on). ⚠️ **Not live-verified.** |
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md row for the planet geosphere"
```
