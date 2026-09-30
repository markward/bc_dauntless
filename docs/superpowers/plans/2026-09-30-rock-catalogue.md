# Rock Catalogue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace BC's four stock asteroid meshes with a committed, generated rock catalogue: 13 majors and 24 fragments in four families. The catalogue is produced by an offline native tool and loaded through a new minimal glTF loader. BC's asteroid scripts draw a deterministic random rock at their authored size.

**Architecture:**
- A new `rockgen` C++ library holds the generator ported from `feat/procedural-asteroids`.
- A `rock_catalogue` CLI writes glTF + PNG + `.dvox` + a manifest into `native/assets/rocks/`.
- The engine reads glTF through a GL-free `assets::gltf::load_cpu` shared by the `Model` builder and the voxel library.
- `Model::source` carries the load scale (`<path>#s=<scale>`), so every damage-volume cache keys and reads scaled glTF correctly.
- Python redirects the four stock asteroid NIFs at the two ship-realise seams in `host_loop.py`.

**Tech Stack:** C++20, CMake, cgltf v1.15 (vendored, read side), nlohmann_json (write side, already fetched), stb_image / stb_image_write (vendored), GoogleTest, Python 3.11 + pytest, pybind11.

**Spec:** `docs/superpowers/specs/2026-09-30-rock-catalogue-design.md`. Programme context: `docs/superpowers/specs/2026-09-30-modern-asteroids-roadmap.md`.

## Global Constraints

- **Worktree only.** Work in `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/rock-catalogue` on branch `feat/rock-catalogue`. Never touch the main checkout. Never push.
- **Banned git commands:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit paths only. To mutate a file temporarily, back it up with `cp` and restore with `cp` + `diff`.
- **Never launch the game** (`./build/dauntless`). Mark does the live checks.
- **One build tree:** `build/` in the worktree root. Configure with `cmake -B build -S . -DPython3_EXECUTABLE=$PWD/.venv/bin/python3`. Never run cmake from inside `native/`. Never change `CMAKE_BUILD_TYPE` in place.
- **Never spell `game` or `sdk` as a path segment** in `engine/`, `tools/`, `tests/conftest.py` or `native/src`. Use `engine.paths`. Never capture a path at import (`tests/unit/test_path_indirection.py` enforces this).
- **glTF conventions (spec Part 3):**
  - 1 glTF unit = **1 metre**.
  - 1 BC model unit = **1.75 m**, so `kGltfMetresToModelUnits = 1.0f / 1.75f`.
  - The axis map is `(x, y, z)_glTF → (−x, z, y)_BC`. It is det +1, so winding is preserved.
  - Normal maps are +Y (OpenGL), with no `reconstruct_normal_map_z`.
- **Catalogue rocks** are stored centred with LOD0's bounding radius exactly **100 m**; lower LODs share LOD0's centre and scale (radius ≤ 100 m). The bounding radius is the largest vertex distance from the origin.
- **Source string:** `Model::source` is `<path>` when `scale == 1.0f`, else `<path>#s=<scale formatted %.6g>`.
- **Redirect key:** the four stock NIF basenames, matched case-insensitively: `asteroid.nif`, `asteroid1.nif`, `asteroid2.nif`, `asteroid3.nif`, under `data/Models/Misc/Asteroids/`. Never species 712.
- **Deviation from spec D7:** the tool WRITES glTF JSON with nlohmann_json (sorted keys, deterministic) and the engine READS it with cgltf. A writer and reader from independent libraries make the round-trip test meaningful.
- **Units in Python are GU** (`*_gu`), never `*_m`, except the catalogue's own `bound_radius_m`, which is the glTF metre value by definition.
- **The gate is `scripts/check_tests.sh`**, which must exit 0 before the branch is called done.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **A glTF with a node transform** (translation + rotation + scale on the mesh's node) should load with the transform baked. Pinned in Task 1 (`NodeTransformIsBaked`).
2. **The same catalogue rock at two different stock scales** in one mission (for example Asteroid1 and Asteroid3 picking the same shape) should produce two distinct models, carve volumes and `.dhv` entries, not one shared entry. Pinned in Task 2 (`ScaleIsPartOfCacheKey`), Task 3 (`DistinctScalesDistinctVolumes`) and Task 10 (`test_same_rock_two_scales_two_handles`).
3. **A catalogue folder that is missing or unreadable** (a fresh checkout before generation, or a modder deleting it) should mean stock BC rocks keep loading, with one warning, not a crash or invisible rocks. Pinned in Task 9 (`test_missing_catalogue_falls_back_to_stock`).
4. **Uppercase and mixed-case stock paths** (`Asteroid1.NIF`, and mod overlays resolving to a different directory with the same name) should still redirect by basename plus directory. Pinned in Task 9 (`test_stock_key_is_case_insensitive`).
5. **A `.gltf` path handed to the `.dhv` baker or `SourceVolumeCache`** should voxelise the glTF, not silently produce an empty field, which today's `nif::load` try/catch would do. Pinned in Task 3 (`HullVolumeCacheBakesGltf`).

---

## File Structure

| File | Responsibility |
|---|---|
| `native/third_party/cgltf/{cgltf.h,LICENSE,UPSTREAM_VERSION,CMakeLists.txt}` | vendored cgltf v1.15, INTERFACE target `cgltf` |
| `native/src/assets/include/assets/gltf.h`, `src/gltf_load.cc` | GL-free glTF → `CpuScene` (flattened, BC frame, scaled) |
| `native/src/assets/include/assets/hull_source.h`, `src/hull_source.cc` | `hull_source_string` / `split_hull_source` |
| `native/src/assets/src/gltf_model_build.{h,cc}` | `CpuScene` → `Model` (GPU upload) |
| `native/src/assets/src/cache.cc` (modify) | extension dispatch + `scale` overload |
| `native/src/voxel/include/voxel/dvox.h`, `src/dvox.cc` | `.dvox` read/write + glTF→BC volume remap |
| `native/src/voxel/src/voxelize.cc` (modify) + `voxelize.h` | `collect_hull_triangles_from_source` |
| `native/src/voxel/src/source_cache.cc`, `hull_volume_cache.cc` (modify) | use split source + triangle source + `.dvox` |
| `native/src/host/host_bindings.cc` (modify) | `load_model(..., scale=1.0)` |
| `engine/renderer.py` (modify) | `load_model(..., scale=1.0)` |
| `native/src/rockgen/{CMakeLists.txt, include/rockgen/*.h, src/*.cc}` | recipe, shapes, surfaces, impostor |
| `native/tools/rock_catalogue/{CMakeLists.txt, main.cc, writer.{h,cc}}` | the CLI |
| `native/assets/rocks/**` | recipe + generated catalogue (committed) |
| `engine/rocks/__init__.py`, `engine/rocks/catalogue.py` | manifest reader, pick, stock redirect, toggle |
| `engine/host_loop.py` (modify) | redirect at both ship-realise seams |
| `engine/ui/developer_options_panel.py`, `native/assets/ui-cef/js/developer_options.js` (modify) | the toggle row |
| `tests/conftest.py` (modify) | reset the toggle and manifest memo |

---

### Task 1: Vendor cgltf and add the GL-free glTF reader

**Files:**
- Create: `native/third_party/cgltf/cgltf.h`, `native/third_party/cgltf/LICENSE`, `native/third_party/cgltf/UPSTREAM_VERSION`, `native/third_party/cgltf/CMakeLists.txt`
- Create: `native/src/assets/include/assets/gltf.h`, `native/src/assets/src/gltf_load.cc`
- Create: `native/src/assets/include/assets/hull_source.h`, `native/src/assets/src/hull_source.cc`
- Modify: `native/CMakeLists.txt` (`add_subdirectory(third_party/cgltf)` beside stb, line ~18), `native/src/assets/CMakeLists.txt`
- Test: `native/tests/assets/cpu/gltf_load_test.cc`, `native/tests/assets/cpu/hull_source_test.cc`, and `native/tests/assets/CMakeLists.txt` (add both)

**Interfaces:**
- Produces:

```cpp
// assets/hull_source.h
namespace assets {
struct HullSource { std::filesystem::path path; float scale = 1.0f; };
std::string hull_source_string(const std::filesystem::path& path, float scale); // "#s=%.6g" suffix iff scale != 1
HullSource split_hull_source(const std::filesystem::path& source);              // inverse; no suffix => scale 1
bool is_gltf_path(const std::filesystem::path& p);                               // ".gltf"/".glb", case-insensitive
}
// assets/gltf.h
namespace assets::gltf {
inline constexpr float kMetresToModelUnits = 1.0f / 1.75f;
glm::vec3 to_bc_frame(glm::vec3 v_gltf);            // (-x, z, y); no unit conversion
struct CpuMaterial {
    glm::vec4 base_color_factor{1.0f};
    std::filesystem::path base_color_image;        // absolute; empty if none
    std::filesystem::path normal_image;            // absolute; empty if none
};
struct CpuScene {
    std::vector<MeshCpu> meshes;                    // BC frame, model units × scale, node transforms baked;
                                                    // node_index = 0, material_index into materials (-1 if none)
    std::vector<CpuMaterial> materials;
    std::filesystem::path volume;                   // absolute path from asset.extras.dauntless_volume, or empty
};
CpuScene load_cpu(const std::filesystem::path& path, float scale = 1.0f); // throws AssetError
}
```

- [ ] **Step 1: Vendor cgltf.**

```bash
mkdir -p native/third_party/cgltf
curl -sfL https://raw.githubusercontent.com/jkuhlmann/cgltf/v1.15/cgltf.h -o native/third_party/cgltf/cgltf.h
curl -sfL https://raw.githubusercontent.com/jkuhlmann/cgltf/v1.15/LICENSE -o native/third_party/cgltf/LICENSE
printf 'jkuhlmann/cgltf v1.15 (cgltf.h only)\n' > native/third_party/cgltf/UPSTREAM_VERSION
```

`native/third_party/cgltf/CMakeLists.txt`:

```cmake
add_library(cgltf INTERFACE)
target_include_directories(cgltf INTERFACE ${CMAKE_CURRENT_SOURCE_DIR})
```

Add `add_subdirectory(third_party/cgltf)` after `add_subdirectory(third_party/stb)` in `native/CMakeLists.txt`. In `native/src/assets/CMakeLists.txt`:
- add `src/gltf_load.cc` and `src/hull_source.cc` to `add_library(assets ...)`
- add `cgltf` to `target_link_libraries(assets PRIVATE ...)`

- [ ] **Step 2: Write the failing tests.**

The fixtures are **written by the test** into a temp dir: a `.gltf` JSON with an embedded `data:application/octet-stream;base64,` buffer, so no binary fixtures are committed. Add this helper at the top of `gltf_load_test.cc`:

```cpp
#include <assets/gltf.h>
#include <assets/cache.h>   // AssetError
#include <gtest/gtest.h>
#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {
std::string b64(const std::vector<unsigned char>& in) {
    static const char* t = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out; int val = 0, bits = -6;
    for (unsigned char c : in) { val = (val << 8) + c; bits += 8;
        while (bits >= 0) { out.push_back(t[(val >> bits) & 0x3F]); bits -= 6; } }
    if (bits > -6) out.push_back(t[((val << 8) >> (bits + 8)) & 0x3F]);
    while (out.size() % 4) out.push_back('=');
    return out;
}
template <class T> void put(std::vector<unsigned char>& b, const T& v) {
    auto* p = reinterpret_cast<const unsigned char*>(&v); b.insert(b.end(), p, p + sizeof(T));
}
// One triangle with markers: v0 on +X (glTF), v1 on +Y (up), v2 on +Z (front).
// `node` is merged into nodes[0]; `extras` into asset.extras.
fs::path write_fixture(const fs::path& dir, nlohmann::json node = {},
                       nlohmann::json extras = nullptr, bool with_position = true) {
    fs::create_directories(dir);
    std::vector<unsigned char> buf;
    float pos[9] = {1,0,0, 0,2,0, 0,0,3};
    float nrm[9] = {0,0,1, 0,0,1, 0,0,1};
    for (float f : pos) put(buf, f);
    for (float f : nrm) put(buf, f);
    std::uint16_t idx[3] = {0,1,2}; for (auto i : idx) put(buf, i);
    put(buf, std::uint16_t{0});                         // pad to 4
    nlohmann::json attrs = {{"NORMAL", 1}};
    if (with_position) attrs["POSITION"] = 0;
    nlohmann::json j = {
      {"asset", {{"version", "2.0"}}},
      {"buffers", {{{"byteLength", buf.size()},
                    {"uri", "data:application/octet-stream;base64," + b64(buf)}}}},
      {"bufferViews", {{{"buffer",0},{"byteOffset",0},{"byteLength",36}},
                       {{"buffer",0},{"byteOffset",36},{"byteLength",36}},
                       {{"buffer",0},{"byteOffset",72},{"byteLength",6}}}},
      {"accessors", {{{"bufferView",0},{"componentType",5126},{"count",3},{"type","VEC3"},
                      {"min",{0,0,0}},{"max",{1,2,3}}},
                     {{"bufferView",1},{"componentType",5126},{"count",3},{"type","VEC3"}},
                     {{"bufferView",2},{"componentType",5123},{"count",3},{"type","SCALAR"}}}},
      {"meshes", {{{"primitives", {{{"attributes", attrs},{"indices",2}}}}}}},
      {"nodes", {nlohmann::json{{"mesh",0}}}},
      {"scenes", {{{"nodes",{0}}}}}, {"scene", 0}};
    for (auto& [k, v] : node.items()) j["nodes"][0][k] = v;
    if (!extras.is_null()) j["asset"]["extras"] = extras;
    auto p = dir / "fixture.gltf";
    std::ofstream(p) << j.dump();
    return p;
}
fs::path tmpdir(const char* name) {
    auto d = fs::temp_directory_path() / ("gltf_load_test_" + std::string(name));
    fs::remove_all(d); return d;
}
}  // namespace

TEST(GltfLoad, AxisMapPlacesMarkersOnBcAxes) {
    auto s = assets::gltf::load_cpu(write_fixture(tmpdir("axis")));
    ASSERT_EQ(s.meshes.size(), 1u);
    const auto& v = s.meshes[0].vertices;
    const float k = assets::gltf::kMetresToModelUnits;
    // glTF +X (1 m) -> BC -X; glTF +Y up (2 m) -> BC +Z; glTF +Z front (3 m) -> BC +Y.
    EXPECT_NEAR(v[0].position.x, -1.0f * k, 1e-6f);
    EXPECT_NEAR(v[1].position.z,  2.0f * k, 1e-6f);
    EXPECT_NEAR(v[2].position.y,  3.0f * k, 1e-6f);
    // Normal +Z (glTF front) -> BC +Y, unit length, not unit-converted.
    EXPECT_NEAR(v[0].normal.y, 1.0f, 1e-6f);
}

TEST(GltfLoad, WindingPreserved) {
    // det(+1) map: the triangle's BC-frame normal (right-hand rule over indices)
    // must equal the mapped glTF face normal.
    auto s = assets::gltf::load_cpu(write_fixture(tmpdir("wind")));
    const auto& m = s.meshes[0];
    glm::vec3 a = m.vertices[m.indices[0]].position, b = m.vertices[m.indices[1]].position,
              c = m.vertices[m.indices[2]].position;
    glm::vec3 n_bc = glm::normalize(glm::cross(b - a, c - a));
    glm::vec3 ga{1,0,0}, gb{0,2,0}, gc{0,0,3};
    glm::vec3 n_gltf = glm::normalize(glm::cross(gb - ga, gc - ga));
    glm::vec3 expect = assets::gltf::to_bc_frame(n_gltf);
    EXPECT_NEAR(glm::dot(n_bc, expect), 1.0f, 1e-5f);
}

TEST(GltfLoad, MetreCubeConvertsToModelUnits) {
    // A 1.75 m extent along glTF +X must be exactly 1 BC model unit.
    auto p = write_fixture(tmpdir("metre"), {{"scale", {1.75, 1.0, 1.0}}});
    auto s = assets::gltf::load_cpu(p);
    EXPECT_NEAR(std::abs(s.meshes[0].vertices[0].position.x), 1.0f, 1e-5f);
}

TEST(GltfLoad, ScaleMultipliesPositionsNotNormals) {
    auto s = assets::gltf::load_cpu(write_fixture(tmpdir("scale")), 2.0f);
    EXPECT_NEAR(s.meshes[0].vertices[0].position.x, -2.0f * assets::gltf::kMetresToModelUnits, 1e-6f);
    EXPECT_NEAR(glm::length(s.meshes[0].vertices[0].normal), 1.0f, 1e-5f);
}

TEST(GltfLoad, NodeTransformIsBaked) {
    // Translation (glTF) 10 m along +Y (up) -> BC +Z.
    auto s = assets::gltf::load_cpu(write_fixture(tmpdir("node"), {{"translation", {0.0, 10.0, 0.0}}}));
    EXPECT_NEAR(s.meshes[0].vertices[0].position.z, 10.0f * assets::gltf::kMetresToModelUnits, 1e-5f);
}

TEST(GltfLoad, MissingPositionThrows) {
    EXPECT_THROW(assets::gltf::load_cpu(write_fixture(tmpdir("nopos"), {}, nullptr, false)),
                 assets::AssetError);
}

TEST(GltfLoad, ExtrasVolumeResolvedRelativeToFile) {
    auto d = tmpdir("extras");
    auto s = assets::gltf::load_cpu(write_fixture(d, {}, {{"dauntless_volume", "volume.dvox"}}));
    EXPECT_EQ(s.volume, d / "volume.dvox");
}

TEST(GltfLoad, NoExtrasMeansNoVolume) {
    EXPECT_TRUE(assets::gltf::load_cpu(write_fixture(tmpdir("noextras"))).volume.empty());
}

TEST(GltfLoad, UnsupportedFeaturesWarnOnceAndStillLoad) {
    // A camera and an unknown extension are ignored with one warning per file per
    // feature, and the static mesh still loads.
    auto d = tmpdir("unsupported");
    auto p = write_fixture(d);
    auto j = nlohmann::json::parse(std::ifstream(p));
    j["cameras"] = {{{"type", "perspective"}, {"perspective", {{"yfov", 1.0}, {"znear", 0.1}}}}};
    j["extensionsUsed"] = {"KHR_materials_unlit"};
    std::ofstream(p) << j.dump();
    testing::internal::CaptureStderr();
    auto s1 = assets::gltf::load_cpu(p);
    auto s2 = assets::gltf::load_cpu(p);
    std::string err = testing::internal::GetCapturedStderr();
    EXPECT_EQ(s1.meshes.size(), 1u);
    auto count = [&](const std::string& needle) {
        size_t n = 0, at = 0; while ((at = err.find(needle, at)) != std::string::npos) { ++n; ++at; } return n; };
    EXPECT_EQ(count("ignoring cameras"), 1u);
    EXPECT_EQ(count("ignoring extensions"), 1u);
}

TEST(GltfLoad, UnreadableFileThrows) {
    EXPECT_THROW(assets::gltf::load_cpu("/nonexistent/x.gltf"), assets::AssetError);
}
```

`hull_source_test.cc`:

```cpp
#include <assets/hull_source.h>
#include <gtest/gtest.h>

TEST(HullSource, UnitScaleIsBarePath) {
    EXPECT_EQ(assets::hull_source_string("/a/b.nif", 1.0f), "/a/b.nif");
}
TEST(HullSource, RoundTripsScale) {
    auto s = assets::hull_source_string("/r/lod0.gltf", 0.402f);
    EXPECT_EQ(s, "/r/lod0.gltf#s=0.402");
    auto h = assets::split_hull_source(s);
    EXPECT_EQ(h.path, std::filesystem::path("/r/lod0.gltf"));
    EXPECT_FLOAT_EQ(h.scale, 0.402f);
}
TEST(HullSource, BarePathSplitsToScaleOne) {
    auto h = assets::split_hull_source("/a/b.NIF");
    EXPECT_EQ(h.path, std::filesystem::path("/a/b.NIF"));
    EXPECT_FLOAT_EQ(h.scale, 1.0f);
}
TEST(HullSource, GltfDetectionIsCaseInsensitive) {
    EXPECT_TRUE(assets::is_gltf_path("x/Y.GLTF"));
    EXPECT_TRUE(assets::is_gltf_path("x/y.glb"));
    EXPECT_FALSE(assets::is_gltf_path("x/y.nif"));
}
```

Add `cpu/gltf_load_test.cc` and `cpu/hull_source_test.cc` to `assets_tests` in `native/tests/assets/CMakeLists.txt`, and add `nlohmann_json::nlohmann_json` to its `target_link_libraries`.

- [ ] **Step 3: Run the tests to verify they fail.**

Run: `cmake --build build -j --target assets_tests`
Expected: compile errors (`assets/gltf.h` not found).

- [ ] **Step 4: Implement.**

`hull_source.cc`:

```cpp
#include <assets/hull_source.h>
#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>

namespace assets {
std::string hull_source_string(const std::filesystem::path& path, float scale) {
    if (scale == 1.0f) return path.string();
    char buf[32]; std::snprintf(buf, sizeof buf, "%.6g", static_cast<double>(scale));
    return path.string() + "#s=" + buf;
}
HullSource split_hull_source(const std::filesystem::path& source) {
    const std::string s = source.string();
    const auto at = s.rfind("#s=");
    if (at == std::string::npos) return {source, 1.0f};
    return {std::filesystem::path(s.substr(0, at)), std::strtof(s.c_str() + at + 3, nullptr)};
}
bool is_gltf_path(const std::filesystem::path& p) {
    std::string e = p.extension().string();
    std::transform(e.begin(), e.end(), e.begin(), [](unsigned char c) { return std::tolower(c); });
    return e == ".gltf" || e == ".glb";
}
}  // namespace assets
```

`gltf_load.cc`: define `CGLTF_IMPLEMENTATION` in this one TU, then `#include <cgltf.h>`. Algorithm:
1. `cgltf_parse_file` → `cgltf_load_buffers(options, data, path)` → `cgltf_validate`. Throw `AssetError("gltf: <path>: <reason>")` on any non-success result, and free with `cgltf_free` on every path (use a unique_ptr with a custom deleter).
2. **Warnings.** Warn once per file (a static `std::unordered_set<std::string>` keyed `path + "|" + feature`) to stderr for any of: `skins_count`, `animations_count`, `cameras_count`, a primitive with `targets_count`, a sparse accessor, and `extensions_used_count`. The message is exactly `gltf: <path>: ignoring <feature>`, where `<feature>` is one of `skins`, `animations`, `cameras`, `morph targets`, `sparse accessors`, `extensions`.
3. **Walk.** Walk the default scene (or `scenes[0]`, or every root node if there are no scenes). For each node with a mesh, get `cgltf_node_transform_world(node, float m[16])` (column-major) as `glm::mat4 W`, and the normal matrix `N = transpose(inverse(mat3(W)))`.
4. **Primitives.** For each primitive:
   - The type must be `cgltf_primitive_type_triangles`, else `AssetError("... non-triangle primitive")`.
   - `POSITION` is required, else `AssetError("... primitive without POSITION")`.
   - Read `POSITION`, `NORMAL` (optional; if absent, compute flat normals after mapping) and `TEXCOORD_0` (optional, default 0) with `cgltf_accessor_read_float`.
   - Indices come from `cgltf_accessor_read_index`, or `0..count-1` if there are none.
   - For each vertex: `p_bc = to_bc_frame(vec3(W * vec4(p, 1))) * kMetresToModelUnits * scale`, and `n_bc = normalize(to_bc_frame(N * n))`. UV is copied unchanged, since glTF UV origin is top-left, which matches GL texture upload of top-down PNG rows via `decode_image`. Assert this in the Task 2 round trip.
   - `node_index = 0`. `material_index` = the index of `primitive.material` in `data->materials`, or -1.
5. **Materials.** For each material, `base_color_factor` = `pbr_metallic_roughness.base_color_factor`. `base_color_image` / `normal_image` = `path.parent_path() / image->uri` when the texture has an image with a uri (data-URI images are unsupported: warn once and leave the path empty).
6. **Extras.** Read `data->asset.extras` with `cgltf_copy_extras_json` into a string, parse it with nlohmann, and if `"dauntless_volume"` is a string, set `volume = path.parent_path() / it`.
7. `to_bc_frame(v) = {-v.x, v.z, v.y}`.

- [ ] **Step 5: Run the tests to verify they pass.**

Run: `cmake --build build -j --target assets_tests && ./build/native/tests/assets/assets_tests --gtest_filter='GltfLoad*:HullSource*'`
Expected: all PASS.

- [ ] **Step 6: Commit.**

```bash
git add native/third_party/cgltf native/CMakeLists.txt native/src/assets/CMakeLists.txt native/src/assets/include/assets/gltf.h native/src/assets/src/gltf_load.cc native/src/assets/include/assets/hull_source.h native/src/assets/src/hull_source.cc native/tests/assets/cpu/gltf_load_test.cc native/tests/assets/cpu/hull_source_test.cc native/tests/assets/CMakeLists.txt
git commit -m "feat(assets): GL-free glTF reader (cgltf) in BC frame and metres; hull source strings"
```

---

### Task 2: Build `Model` from glTF, extension dispatch, load scale in `AssetCache`

**Files:**
- Create: `native/src/assets/src/gltf_model_build.h`, `native/src/assets/src/gltf_model_build.cc`
- Modify: `native/src/assets/src/cache.cc:149-222`, `native/src/assets/include/assets/cache.h`, `native/src/assets/CMakeLists.txt`
- Test: `native/tests/assets/gpu/gltf_model_test.cc` (add to `native/tests/assets/CMakeLists.txt`)

**Interfaces:**
- Consumes: `assets::gltf::load_cpu`, `assets::hull_source_string`, `assets::is_gltf_path` (Task 1).
- Produces:

```cpp
// cache.h — new overload; the existing 4-arg overload forwards with scale = 1.0f
ModelHandle load(const std::filesystem::path& path,
                 const std::vector<std::filesystem::path>& texture_search_paths,
                 const std::vector<TextureReplacement>& texture_replacements,
                 const std::vector<DecalRequest>& decals,
                 float scale);
// gltf_model_build.h (internal)
namespace assets::detail {
Model build_model_from_gltf(const std::filesystem::path& path, float scale,
                            const ModelBuildContext& ctx);   // Model::source = hull_source_string(path, scale)
}
```

- [ ] **Step 1: Write the failing test.** Use the existing `gl_fixture.h` (see `gpu/model_smoke_test.cc` for the fixture class name and pattern, and copy it). Reuse the Task 1 `write_fixture` helper by moving it into `native/tests/assets/cpu/gltf_fixture.h` (inline functions) and including it from both files. Extend the helper with an optional material that has a `baseColorTexture` pointing to a 2×2 PNG, written with `stb_image_write` (`stbi_write_png`), next to the `.gltf`.

```cpp
TEST_F(GlFixture, GltfLoadsThroughAssetCache) {
    auto p = write_fixture(tmpdir("cache"), {}, nullptr, true, /*with_texture=*/true);
    assets::AssetCache::Config cfg; cfg.keep_cpu_data = true;
    assets::AssetCache cache(cfg);
    auto m = cache.load(p, std::vector<std::filesystem::path>{}, {}, {}, 1.0f);
    ASSERT_TRUE(m);
    EXPECT_EQ(m->source, p);
    ASSERT_EQ(m->meshes.size(), 1u);
    ASSERT_TRUE(m->meshes[0].cpu_data().has_value());
    ASSERT_EQ(m->materials.size(), 1u);
    using S = assets::Material::StageSlot;
    EXPECT_GE(m->materials[0].stages[static_cast<size_t>(S::Base)].texture_index, 0);
}

TEST_F(GlFixture, ScaleIsPartOfCacheKey) {
    auto p = write_fixture(tmpdir("scalekey"));
    assets::AssetCache::Config cfg; cfg.keep_cpu_data = true;
    assets::AssetCache cache(cfg);
    auto a = cache.load(p, std::vector<std::filesystem::path>{}, {}, {}, 1.0f);
    auto b = cache.load(p, std::vector<std::filesystem::path>{}, {}, {}, 2.0f);
    EXPECT_NE(a.get(), b.get());
    EXPECT_EQ(b->source.string(), p.string() + "#s=2");
    const float ax = a->meshes[0].cpu_data()->vertices[0].position.x;
    const float bx = b->meshes[0].cpu_data()->vertices[0].position.x;
    EXPECT_NEAR(bx, 2.0f * ax, 1e-5f);
}

TEST_F(GlFixture, NifPathStillGoesToNifLoader) {
    // An unreadable .nif must still throw from the NIF path (not the glTF reader).
    assets::AssetCache cache;
    EXPECT_ANY_THROW(cache.load("/nonexistent/x.nif", std::vector<std::filesystem::path>{}, {}, {}, 1.0f));
}
```

- [ ] **Step 2: Run to verify failure.**

Run: `cmake --build build -j --target assets_tests`
Expected: compile error (no 5-arg `load`).

- [ ] **Step 3: Implement.**

`build_model_from_gltf`:
1. `CpuScene s = gltf::load_cpu(path, scale)`.
2. **Textures.** For each unique image path across materials, read the bytes, `decode_image(span)`, then upload via `ctx.texture_uploader` if set, else `upload_image(img, true)`. Push into `model.textures`, with a map path→index. A missing or undecodable image warns once and leaves the stage at -1.
3. **Materials.** For each `CpuMaterial`: `diffuse = vec3(base_color_factor)`, `alpha = base_color_factor.a`, `specular = vec3(0.12f)` (the branch's rock value), `glossiness = 0.0f`. `stages[Base].texture_index`, `stages[Bump].texture_index` from the map.
4. One root `Node{name="gltf_root", parent_index=-1, local_transform=identity}` holding every mesh. `model.root_node = 0`.
5. **Meshes.** For each `MeshCpu`, upload via `ctx.mesh_uploader` if set, else `upload_mesh(cpu)`, and `set_shape_name("gltf_mesh_" + i)`. If `ctx.keep_cpu_data`, then `set_cpu_data(cpu)`. Append its index to the root node's `meshes`.
6. `model.source = hull_source_string(path, scale)`.

In `cache.cc`:
- The existing 4-arg `load` forwards to the 5-arg overload with `1.0f`.
- In the 5-arg overload, **before** the mesh-fix block: `if (is_gltf_path(nif_path))`, compute `canon = fs::weakly_canonical(nif_path).string() + (scale != 1.0f ? "#s=" + fmt : "")`, then look it up, build via `build_model_from_gltf`, and store in the same entry pattern. Skip mesh fixes, texture replacements and decals for glTF: warn once if a non-empty replacement/decal list arrives.
- The NIF path is unchanged when `scale == 1.0f`. For a NIF with `scale != 1.0f`, **throw `AssetError("scale is only supported for glTF")`**: YAGNI, because no production caller needs a scaled NIF.

- [ ] **Step 4: Run to verify pass.**

Run: `cmake --build build -j --target assets_tests && ./build/native/tests/assets/assets_tests`
Expected: all PASS (the whole binary, not only the new tests).

- [ ] **Step 5: Commit.**

```bash
git add native/src/assets/src/gltf_model_build.h native/src/assets/src/gltf_model_build.cc native/src/assets/src/cache.cc native/src/assets/include/assets/cache.h native/src/assets/CMakeLists.txt native/tests/assets/gpu/gltf_model_test.cc native/tests/assets/cpu/gltf_fixture.h native/tests/assets/cpu/gltf_load_test.cc native/tests/assets/CMakeLists.txt
git commit -m "feat(assets): glTF models through AssetCache with a load scale baked into vertices"
```

---

### Task 3: `.dvox` sidecar and format/scale-aware damage-volume caches

**Files:**
- Create: `native/src/voxel/include/voxel/dvox.h`, `native/src/voxel/src/dvox.cc`
- Modify: `native/src/voxel/include/voxel/voxelize.h`, `native/src/voxel/src/voxelize.cc`, `native/src/voxel/src/source_cache.cc`, `native/src/voxel/src/hull_volume_cache.cc`, `native/src/voxel/CMakeLists.txt`
- Test: `native/tests/voxel/dvox_test.cc`, plus extend `native/tests/voxel/source_cache_test.cc` (create it if absent) and add a hull-volume test to the existing hull volume cache test file (find it with `ls native/tests/voxel`). Register the new files in `native/tests/voxel/CMakeLists.txt`.

**Interfaces:**
- Consumes: `assets::gltf::load_cpu`, `assets::split_hull_source`, `assets::is_gltf_path` (Task 1).
- Produces:

```cpp
// voxel/dvox.h
namespace voxel {
bool write_dvox(const std::filesystem::path& p, const VoxelVolume& v);   // binary occupancy (occ != 0)
bool read_dvox(const std::filesystem::path& p, VoxelVolume& out);        // occ bytes 0/1
// glTF-frame, metre volume -> BC frame, model units × scale (grid re-indexed, not resampled)
VoxelVolume remap_gltf_volume_to_bc(const VoxelVolume& v_gltf, float scale);
}
// voxel/voxelize.h
std::vector<Tri> collect_hull_triangles_from_source(const std::filesystem::path& source);
```

`.dvox` layout (little-endian): `char magic[4]="DVX1"`, `u16 version=1`, `i32 dims[3]`, `f32 origin[3]`, `f32 cell[3]`, then `ceil(N/8)` bytes of occupancy bits, x-fastest (`index = x + dx*(y + dy*z)`), bit `i` at byte `i>>3`, mask `1<<(i&7)`.

- [ ] **Step 1: Write the failing tests.**

```cpp
// dvox_test.cc
#include <voxel/dvox.h>
#include <gtest/gtest.h>
#include <filesystem>

TEST(Dvox, RoundTrip) {
    voxel::VoxelVolume v; v.dims = {3, 4, 5}; v.origin = {-1, -2, -3}; v.cell = {0.5f, 0.25f, 1.0f};
    v.occ.assign(60, 0); v.set(0,0,0,true); v.set(2,3,4,true); v.set(1,2,3,true);
    auto p = std::filesystem::temp_directory_path() / "dvox_rt.dvox";
    ASSERT_TRUE(voxel::write_dvox(p, v));
    voxel::VoxelVolume r; ASSERT_TRUE(voxel::read_dvox(p, r));
    EXPECT_EQ(r.dims, v.dims); EXPECT_EQ(r.origin, v.origin); EXPECT_EQ(r.cell, v.cell);
    EXPECT_EQ(r.solid_count(), 3u);
    EXPECT_TRUE(r.solid(2,3,4)); EXPECT_FALSE(r.solid(1,1,1));
}

TEST(Dvox, RejectsBadMagic) {
    auto p = std::filesystem::temp_directory_path() / "dvox_bad.dvox";
    { std::ofstream(p) << "NOPE"; }
    voxel::VoxelVolume r; EXPECT_FALSE(voxel::read_dvox(p, r));
}

TEST(Dvox, RemapMatchesPointMap) {
    // A single solid cell at glTF index (2,0,1) in a 4x2x3 grid, 1 m cells, origin 0.
    voxel::VoxelVolume g; g.dims = {4, 2, 3}; g.origin = {0,0,0}; g.cell = {1,1,1};
    g.occ.assign(24, 0); g.set(2, 0, 1, true);
    auto b = voxel::remap_gltf_volume_to_bc(g, 2.0f);
    const float k = (1.0f / 1.75f) * 2.0f;
    EXPECT_EQ(b.dims, glm::ivec3(4, 3, 2));                 // (dx, dz, dy)
    EXPECT_NEAR(b.cell.x, k, 1e-6f);
    ASSERT_EQ(b.solid_count(), 1u);
    // Centre of the glTF cell (2.5, 0.5, 1.5) m maps to BC (-2.5, 1.5, 0.5) * k.
    glm::vec3 want = glm::vec3(-2.5f, 1.5f, 0.5f) * k;
    for (int z = 0; z < b.dims.z; ++z) for (int y = 0; y < b.dims.y; ++y) for (int x = 0; x < b.dims.x; ++x)
        if (b.solid(x, y, z)) {
            glm::vec3 c = b.origin + (glm::vec3(x, y, z) + 0.5f) * b.cell;
            EXPECT_NEAR(glm::distance(c, want), 0.0f, 1e-5f);
        }
}
```

Source-cache and hull-volume tests. Write a glTF fixture (copy `gltf_fixture.h` from Task 2 into `native/tests/voxel/`, or add the assets test dir to the voxel test target's include path and include it). Use a closed shape: extend the helper with `write_cube_fixture(dir, half_m, extras)`, which emits a 12-triangle cube.

```cpp
TEST(SourceVolumeCache, VoxelisesGltfWhenNoSidecar) {
    auto p = write_cube_fixture(tmpdir("svc_nosidecar"), 1.75f, nullptr);   // half-extent 1 model unit
    voxel::SourceVolumeCache c;
    const auto& v = c.get_for_hull(p);
    ASSERT_FALSE(v.occ.empty());
    EXPECT_EQ(v.dims, glm::ivec3(48, 48, 48));
    EXPECT_GT(v.solid_count(), 0u);
}

TEST(SourceVolumeCache, PrefersExtrasSidecar) {
    auto d = tmpdir("svc_sidecar");
    voxel::VoxelVolume g; g.dims = {2,2,2}; g.origin = {-1,-1,-1}; g.cell = {1,1,1}; g.occ.assign(8, 1);
    fs::create_directories(d); ASSERT_TRUE(voxel::write_dvox(d / "volume.dvox", g));
    auto p = write_cube_fixture(d, 1.0f, {{"dauntless_volume", "volume.dvox"}});
    voxel::SourceVolumeCache c;
    EXPECT_EQ(c.get_for_hull(p).dims, glm::ivec3(2, 2, 2));  // sidecar, not the 48^3 fallback
}

TEST(SourceVolumeCache, DistinctScalesDistinctVolumes) {
    auto p = write_cube_fixture(tmpdir("svc_scale"), 1.75f, nullptr);
    voxel::SourceVolumeCache c;
    const auto& a = c.get_for_hull(assets::hull_source_string(p, 1.0f));
    const auto& b = c.get_for_hull(assets::hull_source_string(p, 2.0f));
    EXPECT_NEAR(b.cell.x, 2.0f * a.cell.x, 1e-4f);
}

TEST(HullVolumeCache, HullVolumeCacheBakesGltf) {
    auto root = tmpdir("hvc_root"); fs::create_directories(root);
    auto p = write_cube_fixture(tmpdir("hvc_gltf"), 1.75f * 50.0f, nullptr);   // 50 model units half-extent
    voxel::HullVolumeCache hvc(root);
    const auto& f = hvc.get(assets::hull_source_string(p, 1.0f), 10.0f, 2.0f);
    EXPECT_FALSE(f.empty());                           // today's nif::load path would yield EMPTY
}
```

- [ ] **Step 2: Run to verify failure.**

Run: `cmake --build build -j --target voxel_tests`
Expected: compile errors (`voxel/dvox.h` missing, `collect_hull_triangles_from_source` undeclared).

- [ ] **Step 3: Implement.**
- `dvox.cc`: straightforward binary I/O. Write to `p + ".tmp"` then `std::filesystem::rename` (atomic, as `dhv.cc` does). Reject a short payload, a bad magic, version != 1, or a non-positive dim.
- `remap_gltf_volume_to_bc`, with `k = kMetresToModelUnits * scale`:
  - `out.dims = {g.dx, g.dz, g.dy}`
  - `out.cell = vec3(g.cell.x, g.cell.z, g.cell.y) * k`
  - `out.origin = vec3(-(g.origin.x + g.dx * g.cell.x), g.origin.z, g.origin.y) * k`
  - For each glTF cell `(i, j, kk)`, `out(g.dx - 1 - i, kk, j) = g(i, j, kk)`.
- `collect_hull_triangles_from_source(source)`: `h = split_hull_source(source)`.
  - If `is_gltf_path(h.path)`: flatten `gltf::load_cpu(h.path, h.scale)` meshes into `Tri`s.
  - Else: `nif::load(h.path)` → `collect_hull_triangles_from_nif`, then multiply every vertex by `h.scale`.
  - Returns empty if `h.path` does not exist.
- `SourceVolumeCache::get_for_hull(source)`: `h = split_hull_source(source)`.
  - **glTF:** `s = gltf::load_cpu(h.path, h.scale)`. If `!s.volume.empty() && read_dvox(s.volume, raw)`, then `vol = remap_gltf_volume_to_bc(raw, h.scale)`. Otherwise voxelise `collect_hull_triangles_from_source(source)` at 48³. Catch `AssetError` → empty volume.
  - **NIF:** keep today's code, applied to `h.path`.
  - Keep the cache key as the full source string.
  - `planes_for_hull` returns empty for glTF.
- `hull_volume_cache.cc`: in `ensure_dhv` and `HullVolumeCache::get`, compute `h = split_hull_source(hull)`. Use `h.path` for `exists`, `file_size_of` and `mtime_of`. Keep `hull` (the full string) for `key_string`, `cache_path_for` and `meta.source_path`. In `bake_and_write`, replace `nif::load` + `collect_hull_triangles_from_nif` with `collect_hull_triangles_from_source(hull_nif)`, inside the existing try/catch.
- Add `src/dvox.cc` to `add_library(voxel ...)`.

- [ ] **Step 4: Run to verify pass.**

Run: `cmake --build build -j --target voxel_tests && ./build/native/tests/voxel/voxel_tests`
Expected: all PASS, including every pre-existing voxel test.

- [ ] **Step 5: Commit.**

```bash
git add native/src/voxel native/tests/voxel
git commit -m "feat(voxel): .dvox sidecar and glTF/scale-aware source and hull-volume caches"
```

---

### Task 4: `load_model(..., scale=)` binding and Python wrapper

**Files:**
- Modify: `native/src/host/host_bindings.cc:548-647` (`load_model_impl`) and its `m.def("load_model", ...)` (search `"load_model"` near line 2078), `engine/renderer.py:172-183`
- Test: `tests/host/test_load_model_scale.py`

**Interfaces:**
- Consumes: `AssetCache::load(..., float scale)` (Task 2).
- Produces: `_dauntless_host.load_model(path, tex, reps=None, decals=None, scale=1.0)` and `engine.renderer.load_model(path, tex, texture_replacements=None, decals=None, scale=1.0)`. The dedupe key includes the scale, so distinct scales give distinct handles.

- [ ] **Step 1: Write the failing test.** Use the host-boot pattern from `tests/host/test_bindings_smoke.py` / `test_mesh_ray_trace.py`: `os.environ["OPEN_STBC_HOST_HEADLESS"]="1"`, `init(64,64,...)`, `skip` on `RuntimeError`, `shutdown` in `finally`. Write a glTF cube fixture with Python's `json` + `base64` + `struct` (same layout as the C++ helper).

```python
def test_scale_gives_distinct_handles_and_scaled_aabb(host, tmp_path):
    p = _write_cube_gltf(tmp_path, half_m=1.75)          # half-extent 1 model unit
    a = host.load_model(str(p), [str(tmp_path)], None, None, 1.0)
    b = host.load_model(str(p), [str(tmp_path)], None, None, 2.0)
    assert a != b
    (_, ha), (_, hb) = host.model_aabb(a), host.model_aabb(b)
    assert abs(hb[0] - 2.0 * ha[0]) < 1e-4
    assert abs(ha[0] - 1.0) < 1e-4

def test_same_scale_dedupes(host, tmp_path):
    p = _write_cube_gltf(tmp_path, half_m=1.75)
    assert host.load_model(str(p), [str(tmp_path)], None, None, 0.5) == \
           host.load_model(str(p), [str(tmp_path)], None, None, 0.5)

def test_renderer_wrapper_passes_scale(monkeypatch):
    from engine import renderer
    seen = {}
    class H:
        def load_model(self, *a):
            seen["args"] = a; return 7
    monkeypatch.setattr(renderer, "_h", H())
    assert renderer.load_model("x.gltf", ["d"], scale=0.25) == 7
    assert seen["args"][-1] == 0.25
```

- [ ] **Step 2: Run to verify failure.**

Run: `cmake --build build -j && uv run pytest tests/host/test_load_model_scale.py -v`
Expected: FAIL (a TypeError on the fifth argument / unexpected keyword `scale`).

- [ ] **Step 3: Implement.**
- In `load_model_impl`, add a `float scale` parameter. Append `"|scale:" + std::to_string(scale)` to `rep_key` **only when `scale != 1.0f`**, so existing keys are byte-identical. Call `g_cache->load(nif_path, search_paths, replacements, decal_requests, scale)`.
- In the `m.def`, add `py::arg("scale") = 1.0f` after `decals`. Keep the positional order `(nif_path, texture_search_path, texture_replacements, decals, scale)`.
- In `engine/renderer.py`, add `scale: float = 1.0` and call `_h.load_model(nif_path, texture_search_path, texture_replacements, decals, scale)`. Extend the docstring: "`scale` bakes a uniform scale into the vertices (glTF only); it is part of the model's identity."

- [ ] **Step 4: Run to verify pass.**

Run: `uv run pytest tests/host/test_load_model_scale.py tests/host/test_bindings_smoke.py -v`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py tests/host/test_load_model_scale.py
git commit -m "feat(host): load_model takes a uniform scale folded into the model identity"
```

---

### Task 5: `rockgen` library — recipe and shapes

**Files:**
- Create: `native/src/rockgen/CMakeLists.txt`, `native/src/rockgen/include/rockgen/recipe.h`, `native/src/rockgen/include/rockgen/shape.h`, `native/src/rockgen/src/recipe.cc`, `native/src/rockgen/src/shape.cc`, `native/src/rockgen/src/noise.h`
- Modify: `native/CMakeLists.txt` (`add_subdirectory(src/rockgen)` after `src/voxel`), `native/tests/CMakeLists.txt` (`add_subdirectory(rockgen)`)
- Test: `native/tests/rockgen/CMakeLists.txt`, `native/tests/rockgen/shape_test.cc`, `native/tests/rockgen/recipe_test.cc`

**Source to port:** `git show feat/procedural-asteroids:native/src/assets/src/asteroid_gen.cc`, `...:native/src/assets/src/asteroid_noise.h`, `...:native/src/assets/include/assets/asteroid_gen.h`, and the tests at `...:native/tests/assets/cpu/asteroid_gen_test.cc`. Read them first. Keep the icosphere builder, the fbm value noise (`asteroid_noise.h` → `rockgen/src/noise.h`, namespace `rockgen::detail`), the smooth-normal recompute and the UV seam split. **Delete** `kAsteroidVariantCount`, `kAsteroidModelUnits`, the variant-index API and `build_asteroid_model`. Nothing from the branch's renderer, scenegraph, host or engine changes is ported.

**Interfaces:**
- Produces:

```cpp
// rockgen/recipe.h
namespace rockgen {
struct FamilyParams {
    std::string name;
    int majors = 0, fragments = 0;
    glm::vec3 color_a{0.4f}, color_b{0.5f};   // palette endpoints (linear RGB)
    float gloss = 0.12f;
    float displace = 0.35f; int octaves = 5; float noise_scale = 2.3f;
    float axis_min = 0.7f, axis_max = 1.3f;
    int craters_min = 0, craters_max = 0; float crater_radius_min = 0.1f, crater_radius_max = 0.25f;
    int detail_octaves = 3; float detail_scale = 7.0f; float normal_strength = 2.5f;
};
struct KindParams { std::vector<int> lod_subdivisions; int texture_size = 256; int cuts_min = 0, cuts_max = 0; };
struct Recipe {
    int tool_version = 1; std::uint64_t seed = 0; float bound_radius_m = 100.0f;
    int impostor_view_size = 128; int volume_dims = 48;
    KindParams major, fragment;
    std::vector<FamilyParams> families;          // order as in the JSON array
};
struct RockSpec {
    std::string id;                               // "majors/silicate_01" | "fragments/icy_03"
    bool fragment = false;
    const FamilyParams* family = nullptr;
    const KindParams* kind = nullptr;
    std::uint64_t seed = 0;                       // fnv1a64(to_string(recipe.seed) + ":" + id)
    float bound_radius_m = 100.0f;
};
Recipe parse_recipe(const std::string& json_text);          // throws std::runtime_error with the field name
std::vector<RockSpec> expand_recipe(const Recipe& r);        // families in order; majors then fragments; nn from 01
std::uint64_t fnv1a64(const std::string& s);
}
// rockgen/shape.h
namespace rockgen {
// One MeshCpu per LOD, in the glTF frame, metres, centred, bounding radius == spec.bound_radius_m.
// uv via spherical parameterisation with the seam split; node_index 0, material_index 0.
std::vector<assets::MeshCpu> generate_rock_lods(const RockSpec& spec);
float bounding_radius(const assets::MeshCpu& m);             // max |p|
}
```

`recipe.json` is a JSON object with keys: `tool_version`, `seed`, `bound_radius_m`, `impostor_view_size`, `volume_dims`, `major {lod_subdivisions, texture_size}`, `fragment {lod_subdivisions, texture_size, cuts:[min,max]}`, and `families: [ {name, majors, fragments, palette:[[r,g,b],[r,g,b]], gloss, displace, octaves, noise_scale, axis:[min,max], craters:[min,max], crater_radius:[min,max], detail_octaves, detail_scale, normal_strength} ]`. Every key is required, and parse errors name the missing key.

- [ ] **Step 1: Write the failing tests.**

```cpp
// recipe_test.cc
static const char* kMini = R"({"tool_version":1,"seed":7,"bound_radius_m":100,
 "impostor_view_size":32,"volume_dims":16,
 "major":{"lod_subdivisions":[3,2],"texture_size":64},
 "fragment":{"lod_subdivisions":[2,1],"texture_size":32,"cuts":[2,4]},
 "families":[{"name":"silicate","majors":2,"fragments":1,"palette":[[0.4,0.4,0.4],[0.5,0.5,0.5]],
   "gloss":0.12,"displace":0.35,"octaves":5,"noise_scale":2.3,"axis":[0.7,1.3],"craters":[2,4],
   "crater_radius":[0.1,0.25],"detail_octaves":3,"detail_scale":7,"normal_strength":2.5}]})";

TEST(Recipe, ExpandsIdsInOrder) {
    auto r = rockgen::parse_recipe(kMini);
    auto specs = rockgen::expand_recipe(r);
    ASSERT_EQ(specs.size(), 3u);
    EXPECT_EQ(specs[0].id, "majors/silicate_01");
    EXPECT_EQ(specs[1].id, "majors/silicate_02");
    EXPECT_EQ(specs[2].id, "fragments/silicate_01");
    EXPECT_TRUE(specs[2].fragment);
    EXPECT_NE(specs[0].seed, specs[1].seed);
}
TEST(Recipe, MissingKeyNamesIt) {
    try { rockgen::parse_recipe(R"({"tool_version":1})"); FAIL(); }
    catch (const std::runtime_error& e) { EXPECT_NE(std::string(e.what()).find("seed"), std::string::npos); }
}
```

```cpp
// shape_test.cc (use kMini from a shared test header)
TEST(Shape, Deterministic) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto a = rockgen::generate_rock_lods(s[0]), b = rockgen::generate_rock_lods(s[0]);
    ASSERT_EQ(a.size(), b.size());
    for (size_t l = 0; l < a.size(); ++l) {
        ASSERT_EQ(a[l].vertices.size(), b[l].vertices.size());
        EXPECT_EQ(0, std::memcmp(a[l].vertices.data(), b[l].vertices.data(),
                                 a[l].vertices.size() * sizeof(a[l].vertices[0])));
        EXPECT_EQ(a[l].indices, b[l].indices);
    }
}
TEST(Shape, BoundingRadiusIsExact) {
    auto r = rockgen::parse_recipe(kMini);
    for (auto& s : rockgen::expand_recipe(r))
        for (auto& m : rockgen::generate_rock_lods(s))
            EXPECT_NEAR(rockgen::bounding_radius(m), 100.0f, 1e-3f) << s.id;
}
TEST(Shape, LodTriangleCounts) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto lods = rockgen::generate_rock_lods(s[0]);                   // major, subdivisions 3,2
    EXPECT_EQ(lods[0].indices.size() / 3, 1280u);
    EXPECT_EQ(lods[1].indices.size() / 3, 320u);
}
TEST(Shape, Distinct) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto a = rockgen::generate_rock_lods(s[0])[0], b = rockgen::generate_rock_lods(s[1])[0];
    double diff = 0; // same topology (same subdivision) -> compare radii per vertex
    for (size_t i = 0; i < std::min(a.vertices.size(), b.vertices.size()); ++i)
        diff += std::abs(glm::length(a.vertices[i].position) - glm::length(b.vertices[i].position));
    EXPECT_GT(diff / a.vertices.size(), 2.0);                          // mean radial difference > 2 m
}
TEST(Shape, LodSilhouetteTracksLod0) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto lods = rockgen::generate_rock_lods(s[0]);
    // Every LOD1 vertex direction's radius is within 8% of LOD0's radius along the nearest LOD0 vertex direction.
    for (auto& v1 : lods[1].vertices) {
        glm::vec3 d = glm::normalize(v1.position); float best = -2, r0 = 0;
        for (auto& v0 : lods[0].vertices) { float c = glm::dot(d, glm::normalize(v0.position));
            if (c > best) { best = c; r0 = glm::length(v0.position); } }
        EXPECT_NEAR(glm::length(v1.position), r0, 0.08f * 100.0f);
    }
}
TEST(Shape, FragmentsHavePlanarFaces) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto m = rockgen::generate_rock_lods(s[2])[0];                   // fragment
    // Count face-normal clusters: faces whose normals agree within 2 degrees and number >= 5% of faces.
    std::vector<glm::vec3> fn;
    for (size_t i = 0; i + 2 < m.indices.size(); i += 3) {
        auto& a = m.vertices[m.indices[i]].position; auto& b = m.vertices[m.indices[i+1]].position;
        auto& c = m.vertices[m.indices[i+2]].position;
        fn.push_back(glm::normalize(glm::cross(b - a, c - a)));
    }
    std::vector<glm::vec3> centres; std::vector<int> counts;
    for (auto& n : fn) { bool placed = false;
        for (size_t k = 0; k < centres.size(); ++k) if (glm::dot(n, centres[k]) > std::cos(glm::radians(2.0f))) { ++counts[k]; placed = true; break; }
        if (!placed) { centres.push_back(n); counts.push_back(1); } }
    int big = 0; for (int c : counts) if (c >= int(fn.size() * 0.05)) ++big;
    EXPECT_GE(big, 2); EXPECT_LE(big, 4);
}
TEST(Shape, OutwardWinding) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto m = rockgen::generate_rock_lods(s[0])[0];
    int outward = 0, total = 0;
    for (size_t i = 0; i + 2 < m.indices.size(); i += 3, ++total) {
        auto& a = m.vertices[m.indices[i]].position; auto& b = m.vertices[m.indices[i+1]].position;
        auto& c = m.vertices[m.indices[i+2]].position;
        if (glm::dot(glm::cross(b - a, c - a), (a + b + c) / 3.0f) > 0) ++outward;
    }
    EXPECT_GT(outward, total * 0.97);   // CCW outward, as glTF requires
}
```

Also port the branch's UV-seam test from `asteroid_gen_test.cc` into `shape_test.cc` (`Shape.UvSeamSplit`), adapted to `generate_rock_lods`.

- [ ] **Step 2: Run to verify failure.**

Run: `cmake -B build -S . -DPython3_EXECUTABLE=$PWD/.venv/bin/python3 && cmake --build build -j --target rockgen_tests`
Expected: FAIL (target sources missing).

- [ ] **Step 3: Implement.**
- `native/src/rockgen/CMakeLists.txt`: `add_library(rockgen STATIC src/recipe.cc src/shape.cc src/surface.cc src/impostor.cc)`. (`surface.cc` and `impostor.cc` are added as empty TUs now and filled in Task 6.) Public `include`, `cxx_std_20`, link `PUBLIC assets glm`, `PRIVATE nlohmann_json::nlohmann_json`.
- `native/tests/rockgen/CMakeLists.txt`: `add_executable(rockgen_tests recipe_test.cc shape_test.cc)`, link `rockgen GTest::gtest_main`, `gtest_discover_tests(rockgen_tests)`.
- `recipe.cc`: nlohmann parse. Use a helper `req(j, "key")` that throws `std::runtime_error("recipe: missing '" + key + "'")`. `fnv1a64` is standard FNV-1a 64 (offset `1469598103934665603`, prime `1099511628211`).
- `shape.cc`, per LOD subdivision `s`:
  1. Icosphere(`s`).
  2. For each unit direction `d`, radius `h(d) = 1 + displace * (fbm(d * noise_scale, octaves, seed) - 0.5) * 2 - craters(d)`. The displacement field is evaluated on the unit direction, so every LOD samples the SAME field.
  3. Position `= d * h(d) * axes`, where `axes` is per rock from the seed in `[axis_min, axis_max]³`.
  4. **Craters:** for each crater with centre direction `c` and angular radius `a`, with `t = acos(dot(d,c))/a` and `t < 1`, subtract `depth * (1 - t²)`, where `depth = 0.35 * a`. Then add a rim bump `0.15 * depth * exp(-((t - 1) / 0.15)²)`. Count, centres and radii come from the seed.
  5. **Fragments:** pick `n ∈ [cuts_min, cuts_max]` planes `(n̂, dist)` from the seed, with `dist ∈ [0.45, 0.8] * max|p|`. For each vertex, where `dot(p, n̂) > dist`, set `p -= (dot(p, n̂) - dist) * n̂` (flatten onto the plane; no re-triangulation; star-shaped about the origin is preserved).
  6. Recentre on the bounding-sphere centre (the midpoint of the AABB is enough), then scale so `max|p| == bound_radius_m`.
  7. Recompute smooth normals (area-weighted). Faces are CCW outward.
  8. UVs: spherical on the pre-cut unit direction `d`, with the branch's seam split.
  9. `material_index = 0`, `node_index = 0`.

  All randomness comes from `std::mt19937_64(spec.seed)`, drawn in a fixed order: axes, then craters, then cuts. Never use `std::uniform_real_distribution` (its output is implementation-defined). Map `rng()` bits to `[0,1)` by hand: `(rng() >> 11) * 0x1.0p-53`.

- [ ] **Step 4: Run to verify pass.**

Run: `cmake --build build -j --target rockgen_tests && ./build/native/tests/rockgen/rockgen_tests`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add native/src/rockgen native/tests/rockgen native/CMakeLists.txt native/tests/CMakeLists.txt
git commit -m "feat(rockgen): recipe + deterministic rock shapes (majors, craters, plane-cut fragments, same-field LODs)"
```

---

### Task 6: `rockgen` surfaces and impostor

**Files:**
- Create: `native/src/rockgen/include/rockgen/surface.h`, `native/src/rockgen/include/rockgen/impostor.h`
- Modify: `native/src/rockgen/src/surface.cc`, `native/src/rockgen/src/impostor.cc`, `native/tests/rockgen/CMakeLists.txt`
- Test: `native/tests/rockgen/surface_test.cc`, `native/tests/rockgen/impostor_test.cc`

**Interfaces:**
- Consumes: `RockSpec`, `generate_rock_lods` (Task 5).
- Produces:

```cpp
// rockgen/surface.h
namespace rockgen {
struct RockSurface { assets::Image base_color; assets::Image normal; glm::vec3 avg_albedo{0}; };
RockSurface generate_rock_surface(const RockSpec& spec);       // RGB8, size kind->texture_size²
}
// rockgen/impostor.h
namespace rockgen {
struct Impostor {
    assets::Image albedo, normal;          // RGBA8, (4*view_size)², alpha = coverage
    std::vector<glm::vec3> view_dirs;      // 16, fixed (the direction the camera LOOKS FROM, glTF frame)
    int grid = 4; int view_size = 0;
};
std::vector<glm::vec3> impostor_view_dirs();                   // 16 Fibonacci-sphere directions, fixed
Impostor bake_impostor(const assets::MeshCpu& mesh, const RockSurface& s, int view_size);
}
```

- [ ] **Step 1: Write the failing tests.**

```cpp
TEST(Surface, DeterministicAndSized) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto a = rockgen::generate_rock_surface(s[0]), b = rockgen::generate_rock_surface(s[0]);
    EXPECT_EQ(a.base_color.width, 64u);
    EXPECT_EQ(a.base_color.pixels, b.base_color.pixels);
    EXPECT_EQ(a.normal.pixels, b.normal.pixels);
}
TEST(Surface, AlbedoWithinPalette) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto a = rockgen::generate_rock_surface(s[0]);
    for (int c = 0; c < 3; ++c) { EXPECT_GE(a.avg_albedo[c], 0.25f); EXPECT_LE(a.avg_albedo[c], 0.65f); }
}
TEST(Surface, NormalMapIsUnitAndMostlyUp) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto a = rockgen::generate_rock_surface(s[0]);
    double z = 0; size_t n = a.normal.width * a.normal.height;
    for (size_t i = 0; i < n; ++i) z += a.normal.pixels[i * 3 + 2] / 255.0;
    EXPECT_GT(z / n, 0.75);                                    // tangent-space, +Z dominant
}
TEST(Impostor, SixteenFixedViews) {
    auto d = rockgen::impostor_view_dirs();
    ASSERT_EQ(d.size(), 16u);
    for (auto& v : d) EXPECT_NEAR(glm::length(v), 1.0f, 1e-5f);
    EXPECT_EQ(d, rockgen::impostor_view_dirs());
}
TEST(Impostor, CoverageInEveryCell) {
    auto r = rockgen::parse_recipe(kMini); auto s = rockgen::expand_recipe(r);
    auto lods = rockgen::generate_rock_lods(s[0]);
    auto surf = rockgen::generate_rock_surface(s[0]);
    auto imp = rockgen::bake_impostor(lods[1], surf, 32);
    ASSERT_EQ(imp.albedo.width, 128u);
    for (int cell = 0; cell < 16; ++cell) {
        int cx = (cell % 4) * 32 + 16, cy = (cell / 4) * 32 + 16;   // cell centre is on the rock
        EXPECT_GT(imp.albedo.pixels[(cy * 128 + cx) * 4 + 3], 0) << cell;
        EXPECT_EQ(imp.albedo.pixels[((cell / 4) * 32 * 128 + (cell % 4) * 32) * 4 + 3], 0) << cell; // corner empty
    }
}
```

- [ ] **Step 2: Run to verify failure.**

Run: `cmake --build build -j --target rockgen_tests`
Expected: compile errors.

- [ ] **Step 3: Implement.**
- **Surface.** Port the branch's `generate_asteroid_surface`. For texel `(u, v)`, invert the spherical UV to a unit direction and sample detail fbm (`detail_octaves`, `detail_scale`, the seed) to get a height.
  - Base colour = `mix(color_a, color_b, height)`, times a large-scale fbm tint of ±10%, clamped, in linear space, written as sRGB-free RGB8. This matches how the engine already treats BC TGAs; no sRGB conversion anywhere.
  - Normal = central differences of height in (u, v) scaled by `normal_strength`, encoded `n * 0.5 + 0.5` with +Y up.
  - `avg_albedo` = the mean of base colour over the texels, weighted by `cos(latitude)` (the sphere area element), in 0..1.
  - Parallelise rows with `std::thread` over fixed row bands. Each band writes a disjoint range, so the output is identical regardless of scheduling.
- **Impostor.** `impostor_view_dirs()`: Fibonacci sphere, `i = 0..15`, `y = 1 - 2(i + 0.5)/16`, `r = sqrt(1 - y²)`, `phi = i * 2.399963229728653`, `dir = (cos(phi) r, y, sin(phi) r)`.
  - For each view: an orthographic camera looking along `-dir`, with the up vector `(0,1,0)`, or `(1,0,0)` when `|dir.y| > 0.99`. The frame spans `[-R, R]²` with `R = bounding_radius * 1.02`.
  - Rasterise every triangle with a z-buffer, using barycentric UV into `s.base_color` (nearest texel).
  - Albedo RGB is the texel, A = 255. Normal RGB is the view-space vertex normal (interpolated, normalised), encoded `*0.5+0.5`, A = 255. Empty pixels are 0,0,0,0.
  - Cell `i` goes at `((i % 4) * view_size, (i / 4) * view_size)`.

- [ ] **Step 4: Run to verify pass.**

Run: `cmake --build build -j --target rockgen_tests && ./build/native/tests/rockgen/rockgen_tests`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add native/src/rockgen native/tests/rockgen
git commit -m "feat(rockgen): per-family surface bake, average albedo, 16-view CPU impostor"
```

---

### Task 7: `rock_catalogue` CLI

**Files:**
- Create: `native/tools/rock_catalogue/CMakeLists.txt`, `native/tools/rock_catalogue/main.cc`, `native/tools/rock_catalogue/writer.h`, `native/tools/rock_catalogue/writer.cc`
- Modify: `native/CMakeLists.txt` (`add_subdirectory(tools/rock_catalogue)` in the tools block)
- Test: `tests/tools/test_rock_catalogue_tool.py`

**Interfaces:**
- Consumes: all of `rockgen` (Tasks 5–6), `voxel::voxelize_tris` + `voxel::write_dvox` (Task 3). The Python test reads the written files directly; the C++ reader round trip is covered by Task 11's host test.
- Produces:
  - The binary `build/native/tools/rock_catalogue/rock_catalogue` (verify the exact path after the build with `find build -name rock_catalogue -type f`, and use what it prints in the test).
  - CLI: `rock_catalogue --recipe <json> --out <dir> [--only <id>]...`. Exit 0 on success, non-zero with a message on any error.
  - Output per rock, in `<out>/<id>/`: `lod<N>.gltf` + `lod<N>.bin`, `base.png`, `normal.png`, `impostor_base.png`, `impostor_normal.png`, `volume.dvox`.
  - Plus `<out>/catalogue.json` and `<out>/review/contact_sheet.png`, both skipped when `--only` is given, so a drift check never rewrites the manifest.
  - `catalogue.json` schema:

```json
{"tool_version": 1, "recipe_fnv1a64": "<16 hex>", "impostor_view_dirs": [[x,y,z], ...16],
 "rocks": [{"id": "majors/silicate_01", "kind": "major", "family": "silicate",
            "lods": ["majors/silicate_01/lod0.gltf", "..."], "bound_radius_m": 100.0,
            "avg_albedo": [r,g,b], "gloss": 0.12,
            "impostor": {"albedo": "majors/silicate_01/impostor_base.png",
                         "normal": "majors/silicate_01/impostor_normal.png", "grid": 4, "view_size": 128},
            "volume": "majors/silicate_01/volume.dvox"}]}
```

All paths are relative to the catalogue root.

- **glTF written per LOD** (nlohmann JSON, `dump(1)`, sorted keys):
  - `asset {version "2.0", generator "dauntless rock_catalogue <tool_version>", extras {dauntless_volume "volume.dvox"}}`
  - one buffer `lodN.bin`
  - bufferViews/accessors for POSITION (with min/max), NORMAL, TEXCOORD_0, and uint32 indices
  - one mesh, one node, one scene
  - one material: `pbrMetallicRoughness {baseColorTexture {index 0}, metallicFactor 0, roughnessFactor 1}`, `normalTexture {index 1}`
  - images `base.png` and `normal.png`, one sampler, two textures

  Floats in the JSON are the only non-integer values (accessor min/max), and nlohmann prints them with shortest round-trip, which is deterministic.

- [ ] **Step 1: Write the failing test.**

```python
"""rock_catalogue CLI: determinism, layout, manifest, round-trip through the glTF files."""
import hashlib, json, subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "build" / "native" / "tools" / "rock_catalogue" / "rock_catalogue"

MINI = {"tool_version": 1, "seed": 7, "bound_radius_m": 100, "impostor_view_size": 32,
        "volume_dims": 16,
        "major": {"lod_subdivisions": [3, 2], "texture_size": 64},
        "fragment": {"lod_subdivisions": [2, 1], "texture_size": 32, "cuts": [2, 4]},
        "families": [{"name": "silicate", "majors": 1, "fragments": 1,
                      "palette": [[0.4, 0.4, 0.4], [0.5, 0.5, 0.5]], "gloss": 0.12,
                      "displace": 0.35, "octaves": 5, "noise_scale": 2.3, "axis": [0.7, 1.3],
                      "craters": [2, 4], "crater_radius": [0.1, 0.25], "detail_octaves": 3,
                      "detail_scale": 7, "normal_strength": 2.5}]}

def _run(tmp, *extra):
    recipe = tmp / "recipe.json"; recipe.write_text(json.dumps(MINI))
    out = tmp / "out"
    r = subprocess.run([str(BIN), "--recipe", str(recipe), "--out", str(out), *extra],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    return out

def _digest(d: Path):
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(d.rglob("*")) if p.is_file()}

def test_binary_exists():
    assert BIN.is_file(), f"build the tool first: {BIN}"

def test_layout_and_manifest(tmp_path):
    out = _run(tmp_path)
    man = json.loads((out / "catalogue.json").read_text())
    ids = [r["id"] for r in man["rocks"]]
    assert ids == ["majors/silicate_01", "fragments/silicate_01"]
    assert len(man["impostor_view_dirs"]) == 16
    for rock in man["rocks"]:
        for rel in rock["lods"] + [rock["volume"], rock["impostor"]["albedo"], rock["impostor"]["normal"]]:
            assert (out / rel).is_file(), rel
        g = json.loads((out / rock["lods"][0]).read_text())
        assert g["asset"]["extras"]["dauntless_volume"] == "volume.dvox"
        pos = g["accessors"][g["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
        radius = max(max(abs(v) for v in pos["max"]), max(abs(v) for v in pos["min"]))
        assert 50.0 < radius <= 100.0 + 1e-3        # axis extent <= bounding radius
    assert (out / "review" / "contact_sheet.png").is_file()

def test_deterministic(tmp_path):
    a = _digest(_run(tmp_path / "a")); b = _digest(_run(tmp_path / "b"))
    assert a == b

def test_only_writes_just_that_rock(tmp_path):
    out = _run(tmp_path, "--only", "fragments/silicate_01")
    assert (out / "fragments/silicate_01/lod0.gltf").is_file()
    assert not (out / "majors").exists()
    assert not (out / "catalogue.json").exists()

def test_bad_recipe_fails_loudly(tmp_path):
    recipe = tmp_path / "bad.json"; recipe.write_text("{}")
    r = subprocess.run([str(BIN), "--recipe", str(recipe), "--out", str(tmp_path / "o")],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "missing" in r.stderr
```

Create `tests/tools/__init__.py` if `tests/tools/` has none (check the existing layout first).

- [ ] **Step 2: Run to verify failure.**

Run: `uv run pytest tests/tools/test_rock_catalogue_tool.py -v`
Expected: FAIL (`test_binary_exists`).

- [ ] **Step 3: Implement.**
- `CMakeLists.txt`: `add_executable(rock_catalogue main.cc writer.cc)`, linked `PRIVATE rockgen voxel nif assets stb_image nlohmann_json::nlohmann_json`. Include the force-load block copied from `native/tools/voxel_inspect/CMakeLists.txt` (voxel pulls nif).
- `writer.cc`:
  - PNGs via `stbi_write_png_to_func` into a `std::vector<uint8_t>`, then written with `std::ofstream` binary. Call `stbi_write_png_compression_level = 8;` once. The `STB_IMAGE_WRITE_IMPLEMENTATION` define goes in `writer.cc` only; check first that no other target in the link set already defines it (grep `STB_IMAGE_WRITE_IMPLEMENTATION native/src`).
  - The `.bin` layout is positions, normals, uvs, indices, each 4-byte aligned.
  - **Volume:** triangles from LOD0 in the glTF frame and metres (no conversion; `.dvox` is in its glTF's units per spec), then `voxel::voxelize_tris(tris, {dims, dims, dims})` and `write_dvox`.
  - **Contact sheet:** each rock's impostor cell 0, a 4-column grid, with a 12 px strip under each tile filled with the family colour `color_b` (no text rendering; the id order matches `catalogue.json`, documented in the manifest as `"contact_sheet_order": [ids]`).
- `main.cc`: parse args, read the recipe, `expand_recipe`, filter by `--only` (an unknown id is an error), then generate per rock. Parallelism is allowed across rocks, but files are written in a fixed order after generation. Write the manifest unless `--only` was given. `recipe_fnv1a64` = `fnv1a64(recipe file bytes)` in hex.

- [ ] **Step 4: Run to verify pass.**

Run: `cmake --build build -j --target rock_catalogue && uv run pytest tests/tools/test_rock_catalogue_tool.py -v`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add native/tools/rock_catalogue native/CMakeLists.txt tests/tools/test_rock_catalogue_tool.py
git commit -m "feat(tools): rock_catalogue CLI writes glTF/PNG/.dvox rocks, manifest and contact sheet"
```

---

### Task 8: Generate and commit the catalogue, plus a drift test

**Files:**
- Create: `native/assets/rocks/recipe.json`, `native/assets/rocks/**` (generated), `tests/tools/test_rock_catalogue_drift.py`, `native/assets/rocks/README.md`

**Interfaces:**
- Consumes: the CLI (Task 7).
- Produces: `native/assets/rocks/catalogue.json` and 37 rock directories, as the spec's Part 1 table lays out.

- [ ] **Step 1: Write `native/assets/rocks/recipe.json`** (starting values; the families follow the spec's Part 1 table):

```json
{
  "tool_version": 1,
  "seed": 20260930,
  "bound_radius_m": 100.0,
  "impostor_view_size": 128,
  "volume_dims": 48,
  "major":    {"lod_subdivisions": [4, 3, 2], "texture_size": 1024},
  "fragment": {"lod_subdivisions": [3, 2], "texture_size": 256, "cuts": [2, 4]},
  "families": [
    {"name": "silicate", "majors": 5, "fragments": 8,
     "palette": [[0.36, 0.34, 0.31], [0.52, 0.49, 0.45]], "gloss": 0.12,
     "displace": 0.35, "octaves": 5, "noise_scale": 2.3, "axis": [0.7, 1.3],
     "craters": [3, 7], "crater_radius": [0.08, 0.25],
     "detail_octaves": 3, "detail_scale": 7.0, "normal_strength": 2.5},
    {"name": "carbonaceous", "majors": 3, "fragments": 6,
     "palette": [[0.10, 0.09, 0.08], [0.20, 0.18, 0.16]], "gloss": 0.06,
     "displace": 0.40, "octaves": 5, "noise_scale": 2.0, "axis": [0.65, 1.35],
     "craters": [4, 9], "crater_radius": [0.08, 0.3],
     "detail_octaves": 4, "detail_scale": 8.0, "normal_strength": 3.0},
    {"name": "icy", "majors": 3, "fragments": 6,
     "palette": [[0.62, 0.68, 0.74], [0.86, 0.90, 0.94]], "gloss": 0.35,
     "displace": 0.22, "octaves": 4, "noise_scale": 1.8, "axis": [0.75, 1.25],
     "craters": [0, 2], "crater_radius": [0.1, 0.2],
     "detail_octaves": 3, "detail_scale": 5.0, "normal_strength": 1.6},
    {"name": "metallic", "majors": 2, "fragments": 4,
     "palette": [[0.33, 0.30, 0.27], [0.55, 0.50, 0.44]], "gloss": 0.55,
     "displace": 0.25, "octaves": 4, "noise_scale": 2.6, "axis": [0.8, 1.2],
     "craters": [1, 3], "crater_radius": [0.06, 0.15],
     "detail_octaves": 3, "detail_scale": 9.0, "normal_strength": 2.0}
  ]
}
```

- [ ] **Step 2: Write the failing drift test.**

```python
"""The committed catalogue is exactly what the tool produces from the committed recipe.

Regenerates two rocks (one major, one fragment) with --only and compares bytes. A
generator change that alters output fails here; the fix is to regenerate and commit the
catalogue deliberately (see native/assets/rocks/README.md).
"""
import hashlib, json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "build" / "native" / "tools" / "rock_catalogue" / "rock_catalogue"
ROCKS = ROOT / "native" / "assets" / "rocks"
SAMPLES = ["majors/silicate_01", "fragments/icy_01"]

def _files(d): return {p.relative_to(d): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}

def test_manifest_lists_every_rock_dir():
    man = json.loads((ROCKS / "catalogue.json").read_text())
    assert len([r for r in man["rocks"] if r["kind"] == "major"]) == 13
    assert len([r for r in man["rocks"] if r["kind"] == "fragment"]) == 24
    for r in man["rocks"]:
        assert (ROCKS / r["lods"][0]).is_file()

def test_samples_regenerate_byte_identical(tmp_path):
    args = [str(BIN), "--recipe", str(ROCKS / "recipe.json"), "--out", str(tmp_path)]
    for s in SAMPLES: args += ["--only", s]
    r = subprocess.run(args, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr
    for s in SAMPLES:
        assert _files(tmp_path / s) == _files(ROCKS / s), f"{s} drifted from the committed catalogue"

def test_manifest_recipe_hash_matches_recipe():
    man = json.loads((ROCKS / "catalogue.json").read_text())
    h = 1469598103934665603
    for b in (ROCKS / "recipe.json").read_bytes():
        h ^= b; h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    assert man["recipe_fnv1a64"] == f"{h:016x}"
```

- [ ] **Step 3: Run to verify failure.**

Run: `uv run pytest tests/tools/test_rock_catalogue_drift.py -v`
Expected: FAIL (no `catalogue.json`).

- [ ] **Step 4: Generate.**

Run: `./build/native/tools/rock_catalogue/rock_catalogue --recipe native/assets/rocks/recipe.json --out native/assets/rocks`
Then check the size: `du -sh native/assets/rocks`. Report the number in the commit message. If it is over 150 MB, STOP and report BLOCKED with the size; do not trim on your own.

Write `native/assets/rocks/README.md` (≤ 25 lines): what the catalogue is, the regenerate command above, "never hand-edit a generated file; change `recipe.json` or the generator and regenerate", the units (metres, 100 m radius), and that `tests/tools/test_rock_catalogue_drift.py` guards it.

- [ ] **Step 5: Run to verify pass.**

Run: `uv run pytest tests/tools/test_rock_catalogue_drift.py -v`
Expected: PASS.

- [ ] **Step 6: Look at the contact sheet** (`native/assets/rocks/review/contact_sheet.png`) with the Read tool and describe it in the task report: do the four families read as distinct, and do fragments look broken? That description goes to Mark. Do not tune the recipe unless a rock is visibly degenerate (for example a flat disc or a spike); if one is, report it rather than guessing.

- [ ] **Step 7: Commit.**

```bash
git add native/assets/rocks tests/tools/test_rock_catalogue_drift.py
git commit -m "assets(rocks): generated rock catalogue (13 majors, 24 fragments, 4 families) + drift test"
```

---

### Task 9: `engine/rocks/catalogue.py`

**Files:**
- Create: `engine/rocks/__init__.py` (empty docstring module), `engine/rocks/catalogue.py`
- Test: `tests/unit/test_rock_catalogue.py`, `tests/unit/test_rock_stock_radius.py`

**Interfaces:**
- Consumes: `native/assets/rocks/catalogue.json` (Task 8), `engine.paths.project_asset_root()`, and `_dauntless_host.nif_shapes` (test only).
- Produces:

```python
MODEL_UNITS_PER_METRE: float = 1.0 / 1.75
STOCK_RADIUS_MU: dict[str, float]          # lowercase basename -> bounding radius (model units), 4 entries
@dataclass(frozen=True)
class Rock:
    id: str; kind: str; family: str; lod_paths: tuple[str, ...]; bound_radius_m: float
    avg_albedo: tuple[float, float, float]; gloss: float
    impostor_albedo: str; impostor_normal: str; volume: str
def catalogue_root() -> Path
def load() -> tuple[Rock, ...]              # () when missing/unreadable (warns once)
def pick(key: str, kind: str = "major", family: str = "silicate") -> Optional[Rock]
def stock_key(nif_path) -> Optional[str]     # lowercase basename iff a stock asteroid NIF
def load_scale(rock: Rock, stock: str) -> float
def ship_model_source(ship_name: str, nif_path: str) -> tuple[str, float]   # (path, scale)
def enabled() -> bool
def set_enabled(value: bool) -> None
```

- [ ] **Step 1: Measure the stock radii.** In the worktree:

```bash
uv run python - <<'PY'
import sys; sys.path[:0] = ["build/python", "."]
import _dauntless_host as h
from engine import paths
paths.configure(paths.resolve())
for n in ["asteroid", "asteroid1", "asteroid2", "asteroid3"]:
    p = paths.game_asset(f"data/Models/Misc/Asteroids/{n}.NIF")
    shapes = h.nif_shapes(str(p))
    print(n, type(shapes), (shapes[0].keys() if isinstance(shapes[0], dict) else type(shapes[0])))
PY
```

Read how `nif_shapes` returns vertices (it is documented in `host_bindings.cc` near line 1901; follow that). Compute `max(|v|)` over every vertex of every shape for each NIF. Those four numbers are `STOCK_RADIUS_MU`, rounded to 3 decimals. Sanity check: they should be near 74 / 23 / 55 / 478; the branch recorded AABB half-extents, and a bounding radius is ≥ that.

- [ ] **Step 2: Write the failing tests.**

```python
# tests/unit/test_rock_catalogue.py
import json
from pathlib import Path
import pytest
from engine.rocks import catalogue as rc

def _fake_root(tmp_path, rocks):
    root = tmp_path / "rocks"; root.mkdir()
    (root / "catalogue.json").write_text(json.dumps({"tool_version": 1, "recipe_fnv1a64": "0" * 16,
        "impostor_view_dirs": [[0, 1, 0]] * 16, "rocks": rocks}))
    return root

def _rock(i, kind="major", family="silicate"):
    rid = f"{kind}s/{family}_{i:02d}"
    return {"id": rid, "kind": kind, "family": family, "lods": [f"{rid}/lod0.gltf"],
            "bound_radius_m": 100.0, "avg_albedo": [0.4, 0.4, 0.4], "gloss": 0.12,
            "impostor": {"albedo": f"{rid}/impostor_base.png", "normal": f"{rid}/impostor_normal.png",
                         "grid": 4, "view_size": 128}, "volume": f"{rid}/volume.dvox"}

@pytest.fixture
def fake(monkeypatch, tmp_path):
    root = _fake_root(tmp_path, [_rock(i) for i in range(1, 6)] + [_rock(1, family="icy")])
    monkeypatch.setattr(rc, "catalogue_root", lambda: root)
    rc._memo.clear()
    return root

def test_pick_is_deterministic_and_filtered(fake):
    a = rc.pick("Unknown Debris 4"); b = rc.pick("Unknown Debris 4")
    assert a == b and a.family == "silicate" and a.kind == "major"
    assert Path(a.lod_paths[0]).is_absolute()

def test_pick_covers_every_candidate(fake):
    seen = {rc.pick(f"Asteroid {i}").id for i in range(200)}
    assert len(seen) == 5

def test_stock_key_is_case_insensitive():
    assert rc.stock_key("/x/data/Models/Misc/Asteroids/Asteroid1.NIF") == "asteroid1.nif"
    assert rc.stock_key("/x/DATA/models/misc/asteroids/asteroid.nif") == "asteroid.nif"
    assert rc.stock_key("/x/data/Models/Ships/Galaxy/Galaxy.nif") is None
    assert rc.stock_key("/mods/foo/data/Models/Misc/Asteroids/myrock.nif") is None

def test_load_scale_hits_stock_radius(fake):
    rock = rc.pick("A")
    s = rc.load_scale(rock, "asteroid3.nif")
    assert abs(rock.bound_radius_m * rc.MODEL_UNITS_PER_METRE * s - rc.STOCK_RADIUS_MU["asteroid3.nif"]) < 1e-6

def test_ship_model_source_redirects_stock(fake):
    path, scale = rc.ship_model_source("Debris1", "/g/data/Models/Misc/Asteroids/asteroid2.NIF")
    assert path.endswith("lod0.gltf") and scale > 0 and scale != 1.0

def test_ship_model_source_leaves_others(fake):
    assert rc.ship_model_source("Galaxy", "/g/data/Models/Ships/Galaxy/Galaxy.nif") == \
           ("/g/data/Models/Ships/Galaxy/Galaxy.nif", 1.0)

def test_disabled_leaves_stock(fake):
    rc.set_enabled(False)
    p = "/g/data/Models/Misc/Asteroids/asteroid.NIF"
    assert rc.ship_model_source("A", p) == (p, 1.0)

def test_missing_catalogue_falls_back_to_stock(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(rc, "catalogue_root", lambda: tmp_path / "nope")
    rc._memo.clear()
    p = "/g/data/Models/Misc/Asteroids/asteroid.NIF"
    assert rc.ship_model_source("A", p) == (p, 1.0)
    assert rc.ship_model_source("B", p) == (p, 1.0)
    assert capsys.readouterr().err.count("rock catalogue") == 1       # warned once

def test_catalogue_root_resolved_at_use(monkeypatch, tmp_path):
    from engine import paths
    monkeypatch.setattr(paths, "project_asset_root", lambda: tmp_path)
    assert rc.catalogue_root() == tmp_path / "rocks"

def test_real_catalogue_loads():
    rc._memo.clear()
    rocks = rc.load()
    assert len([r for r in rocks if r.kind == "major"]) == 13
    assert {r.family for r in rocks} == {"silicate", "carbonaceous", "icy", "metallic"}
```

```python
# tests/unit/test_rock_stock_radius.py
"""STOCK_RADIUS_MU matches the real stock NIFs (asset-backed; BC content via engine.paths)."""
import pytest
from engine.rocks import catalogue as rc

h = pytest.importorskip("_dauntless_host")

@pytest.mark.parametrize("name", ["asteroid", "asteroid1", "asteroid2", "asteroid3"])
def test_stock_radius_matches_nif(name):
    from engine import paths
    p = paths.game_asset(f"data/Models/Misc/Asteroids/{name}.NIF")
    assert p.is_file(), f"BC content not configured: {p}"
    radius = _max_vertex_radius(h.nif_shapes(str(p)))     # implement per nif_shapes' return shape (Step 1)
    assert abs(radius - rc.STOCK_RADIUS_MU[f"{name}.nif"]) < 0.01 * radius
```

Write `_max_vertex_radius` in the test file to match what Step 1 found.

- [ ] **Step 3: Run to verify failure.**

Run: `uv run pytest tests/unit/test_rock_catalogue.py tests/unit/test_rock_stock_radius.py -v`
Expected: FAIL (`ModuleNotFoundError: engine.rocks`).

- [ ] **Step 4: Implement `engine/rocks/catalogue.py`.**

```python
"""The rock catalogue: committed, generated rocks under native/assets/rocks.

Spec: docs/superpowers/specs/2026-09-30-rock-catalogue-design.md. The manifest is
read at USE (never at import) because the project asset root is resolved through
engine.paths. Stock BC asteroid NIFs are redirected to a deterministic catalogue
pick at the stock mesh's size; everything else loads unchanged.
"""
from __future__ import annotations

import json
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Optional

MODEL_UNITS_PER_METRE = 1.0 / 1.75

# Bounding radius (largest vertex distance from the model origin, BC model units)
# of each stock asteroid mesh. Measured from the NIFs; tests/unit/test_rock_stock_radius.py
# re-measures them. The h-variants and Amagon load these same files.
STOCK_RADIUS_MU: dict[str, float] = {
    "asteroid.nif": 0.0,     # <- Step 1 measurement
    "asteroid1.nif": 0.0,
    "asteroid2.nif": 0.0,
    "asteroid3.nif": 0.0,
}

_STOCK_DIR = ("data", "models", "misc", "asteroids")

_enabled = True
_memo: dict[str, tuple] = {}
_warned: set[str] = set()


@dataclass(frozen=True)
class Rock:
    id: str
    kind: str
    family: str
    lod_paths: tuple[str, ...]
    bound_radius_m: float
    avg_albedo: tuple[float, float, float]
    gloss: float
    impostor_albedo: str
    impostor_normal: str
    volume: str


def enabled() -> bool:
    return _enabled


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)


def catalogue_root() -> Path:
    from engine import paths
    return Path(paths.project_asset_root()) / "rocks"


def load() -> tuple[Rock, ...]:
    root = catalogue_root()
    key = str(root)
    if key in _memo:
        return _memo[key]
    rocks: tuple[Rock, ...] = ()
    try:
        man = json.loads((root / "catalogue.json").read_text())
        rocks = tuple(
            Rock(id=r["id"], kind=r["kind"], family=r["family"],
                 lod_paths=tuple(str(root / p) for p in r["lods"]),
                 bound_radius_m=float(r["bound_radius_m"]),
                 avg_albedo=tuple(float(c) for c in r["avg_albedo"]),
                 gloss=float(r["gloss"]),
                 impostor_albedo=str(root / r["impostor"]["albedo"]),
                 impostor_normal=str(root / r["impostor"]["normal"]),
                 volume=str(root / r["volume"]))
            for r in man["rocks"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        if key not in _warned:
            _warned.add(key)
            print(f"[rocks] rock catalogue unavailable at {root}: {e}; "
                  f"stock BC asteroid models will load", file=sys.stderr)
    _memo[key] = rocks
    return rocks


def pick(key: str, kind: str = "major", family: str = "silicate") -> Optional[Rock]:
    candidates = [r for r in load() if r.kind == kind and r.family == family]
    if not candidates:
        return None
    return candidates[zlib.crc32(key.encode("utf-8")) % len(candidates)]


def stock_key(nif_path) -> Optional[str]:
    parts = [p.lower() for p in PurePath(str(nif_path).replace("\\", "/")).parts]
    if len(parts) < 5 or tuple(parts[-5:-1]) != _STOCK_DIR:
        return None
    name = parts[-1]
    return name if name in STOCK_RADIUS_MU else None


def load_scale(rock: Rock, stock: str) -> float:
    return STOCK_RADIUS_MU[stock] / (rock.bound_radius_m * MODEL_UNITS_PER_METRE)


def ship_model_source(ship_name: str, nif_path: str) -> tuple[str, float]:
    if not _enabled:
        return nif_path, 1.0
    stock = stock_key(nif_path)
    if stock is None:
        return nif_path, 1.0
    rock = pick(ship_name)
    if rock is None:
        return nif_path, 1.0
    return rock.lod_paths[0], load_scale(rock, stock)
```

Fill in `STOCK_RADIUS_MU` from the Step 1 measurements.

- [ ] **Step 5: Run to verify pass.**

Run: `uv run pytest tests/unit/test_rock_catalogue.py tests/unit/test_rock_stock_radius.py tests/unit/test_path_indirection.py -v`
Expected: PASS. If `test_path_indirection` flags the `_STOCK_DIR` tuple, add a `# paths-guard: stock asteroid NIF directory, a match pattern not a built path` comment on that line (see CLAUDE.md, BC content paths).

- [ ] **Step 6: Commit.**

```bash
git add engine/rocks tests/unit/test_rock_catalogue.py tests/unit/test_rock_stock_radius.py
git commit -m "feat(rocks): catalogue reader, deterministic pick and stock asteroid redirect"
```

---

### Task 10: Redirect at both ship-realise seams, plus the developer toggle

**Files:**
- Modify: `engine/host_loop.py` (`realize_set_objects` ~5959-5991, `_realize_session` ~7030-7064, `_ship_load_key` ~5465)
- Modify: `engine/ui/developer_options_panel.py`, `native/assets/ui-cef/js/developer_options.js`, `tests/conftest.py` (`_reset_leakable_engine_globals`, line ~873)
- Test: `tests/unit/test_rock_redirect_realise.py`, `tests/unit/test_developer_options_panel.py` (extend)

**Interfaces:**
- Consumes: `engine.rocks.catalogue.ship_model_source`, `enabled`, `set_enabled` (Task 9) and `renderer.load_model(..., scale=)` (Task 4).
- Produces: `host_loop._ship_model_source(ship, nif_path) -> tuple[str, float]`, a thin wrapper so both seams share one call.

- [ ] **Step 1: Write the failing tests.** Find how existing unit tests drive `realize_set_objects` with a fake renderer: `grep -rln "realize_set_objects" tests/`. Copy the fixture pattern of the closest existing test. The fake renderer records `load_model` calls including kwargs, returns increasing handles, `model_aabb` returns `((0,0,0),(1,1,1))`, and the other methods are no-ops.

```python
def test_stock_asteroid_realises_as_catalogue_rock(fake_renderer, stock_asteroid_ship, session):
    host_loop.realize_set_objects(stock_asteroid_ship.GetContainingSet(), session,
                                  ships=[stock_asteroid_ship])
    call = fake_renderer.load_calls[-1]
    assert call.path.endswith("lod0.gltf")
    assert call.kwargs["scale"] == pytest.approx(
        catalogue.load_scale(catalogue.pick(stock_asteroid_ship.GetName()), "asteroid1.nif"))

def test_non_asteroid_load_is_unchanged(fake_renderer, galaxy_ship, session):
    host_loop.realize_set_objects(galaxy_ship.GetContainingSet(), session, ships=[galaxy_ship])
    call = fake_renderer.load_calls[-1]
    assert call.path.lower().endswith(".nif") and "scale" not in call.kwargs

def test_toggle_off_loads_stock(fake_renderer, stock_asteroid_ship, session):
    catalogue.set_enabled(False)
    host_loop.realize_set_objects(stock_asteroid_ship.GetContainingSet(), session,
                                  ships=[stock_asteroid_ship])
    assert fake_renderer.load_calls[-1].path.lower().endswith("asteroid1.nif")

def test_same_rock_two_scales_two_handles(fake_renderer, controller):
    # Two ships whose names pick the same rock but whose scripts use different stock
    # meshes must not share a nif_to_handle entry (Review Focus #2).
    k1 = host_loop._ship_load_key(*_src("lod0.gltf", 0.4), None)
    k2 = host_loop._ship_load_key(*_src("lod0.gltf", 3.1), None)
    assert k1 != k2
```

Here `_src(path, scale)` returns the `(path, reps)` shape that the new `_ship_load_key(model_path, reps, decals=None, scale=1.0)` signature takes. Adapt it to the final signature, and keep one call with no scale to prove the legacy key is unchanged: `_ship_load_key("a.nif", None) == "a.nif"`.

Build the `stock_asteroid_ship` fixture with the SDK's `loadspacehelper.CreateShip("Asteroid1", pSet, "Debris1", ...)` if the existing realise tests do that; otherwise use a fake ship whose `GetScript()` resolves to `ships.Asteroid1` and whose stats have `FilenameHigh = data/Models/Misc/Asteroids/asteroid1.NIF`. Either way, `_ship_nif_path` must resolve through the real `paths.game_asset`, so the test uses real BC content (configured in the worktree via `settings.json`).

Developer panel test: extend `tests/unit/test_developer_options_panel.py` following the existing `normal_maps` toggle tests:
- the `rock_catalogue` key appears in the payload
- the `toggle:rock_catalogue` action flips `catalogue.enabled()`
- the ctrl appears in the Lighting-tab focusables

- [ ] **Step 2: Run to verify failure.**

Run: `uv run pytest tests/unit/test_rock_redirect_realise.py tests/unit/test_developer_options_panel.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement.**

In `host_loop.py`:

```python
def _ship_model_source(ship, nif_path: str) -> tuple[str, float]:
    """(model path, load scale) for a ship: the rock catalogue's pick for a stock
    BC asteroid NIF (engine/rocks/catalogue.py), else (nif_path, 1.0)."""
    from engine.rocks import catalogue as rock_catalogue
    try:
        return rock_catalogue.ship_model_source(ship.GetName(), nif_path)
    except Exception as e:  # never block spawn on the catalogue
        dev_mode.log_swallowed("rock catalogue redirect", e)
        return nif_path, 1.0
```

- `_ship_load_key(nif_path, reps, decals=None, scale=1.0)`: when `scale != 1.0`, append `f"#s={scale:.6g}"` to the string key before the reps and decals are folded in. That is the same suffix the native `Model::source` uses, so the Python and C++ keys agree.
- In **both** seams, right after `nif_path = _ship_nif_path(...)` and its `None` check:

```python
            model_path, model_scale = _ship_model_source(ship, nif_path)
            load_kwargs = {"scale": model_scale} if model_scale != 1.0 else {}
```

- Replace `r_.load_model(nif_path, tex_search, reps, decals=decals or None)` with `r_.load_model(model_path, tex_search, reps, decals=decals or None, **load_kwargs)`.
- In `_realize_session`, `load_key = _ship_load_key(model_path, reps, decals, model_scale)`, and key `nif_to_extent` by `extent_key = nif_path if model_scale == 1.0 else f"{model_path}#s={model_scale:.6g}"` (all three uses).
- Leave `tex_search`, `reps` and `decals` computed from `nif_path` as today; the glTF path ignores them.

In `developer_options_panel.py`, following the `normal_maps` pattern exactly:
- import `from engine.rocks import catalogue as rock_catalogue`
- `self._rock_catalogue = rock_catalogue.enabled()` in `__init__`
- add it to the snapshot tuple
- `"rock_catalogue": self._rock_catalogue` in the payload
- the action `"toggle:rock_catalogue"`, which calls `rock_catalogue.set_enabled(not self._rock_catalogue)` and flips the flag
- `("ctrl", "rock_catalogue")` appended to the Lighting-tab focusables

In `developer_options.js`, following the normal_maps rows:
- `out.push({kind: 'ctrl', target: 'rock_catalogue'});` in `_doFocusableList`'s lighting block
- `html += _doToggleRow('Catalogue Rocks (off = stock BC; applies on mission load)', 'rock_catalogue', s.rock_catalogue, isFoc('rock_catalogue'));` in `_doRenderLightingBody`

In `tests/conftest.py` `_reset_leakable_engine_globals`, add:

```python
    from engine.rocks import catalogue as _rock_catalogue
    _rock_catalogue._enabled = True
    _rock_catalogue._memo.clear()
    _rock_catalogue._warned.clear()
```

- [ ] **Step 4: Run to verify pass.**

Run: `uv run pytest tests/unit/test_rock_redirect_realise.py tests/unit/test_developer_options_panel.py tests/unit/test_rock_catalogue.py -v`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add engine/host_loop.py engine/ui/developer_options_panel.py native/assets/ui-cef/js/developer_options.js tests/conftest.py tests/unit/test_rock_redirect_realise.py tests/unit/test_developer_options_panel.py
git commit -m "feat(rocks): stock asteroid NIFs realise as catalogue rocks at their authored size; dev toggle"
```

---

### Task 11: Host smoke test, docs, and the gate

**Files:**
- Create: `tests/host/test_rock_catalogue_load.py`
- Modify: `CLAUDE.md` (add a Key reference row after "Hull name decals"), `docs/superpowers/specs/2026-09-30-modern-asteroids-roadmap.md` (mark sub-project 1 "built, awaiting live check")

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the host test.** It uses the real committed catalogue and a hidden GL window (the pattern from `tests/host/test_bindings_smoke.py`).

```python
def test_catalogue_rock_loads_at_stock_size(host):
    from engine.rocks import catalogue as rc
    rock = rc.pick("Unknown Debris 4")
    s = rc.load_scale(rock, "asteroid1.nif")
    handle = host.load_model(rock.lod_paths[0], [str(Path(rock.lod_paths[0]).parent)], None, None, s)
    (_c, half) = host.model_aabb(handle)
    assert max(half) <= rc.STOCK_RADIUS_MU["asteroid1.nif"] * 1.001
    assert max(half) >= rc.STOCK_RADIUS_MU["asteroid1.nif"] * 0.5
```

- [ ] **Step 2: Run it.**

Run: `uv run pytest tests/host/test_rock_catalogue_load.py -v`
Expected: PASS.

- [ ] **Step 3: Add a docs row to `CLAUDE.md`'s Key reference table:**

`| Rock catalogue — generated rocks + glTF loader | engine/rocks/catalogue.py, native/assets/rocks/, native/tools/rock_catalogue/, native/src/assets/src/gltf_load.cc, docs/superpowers/specs/2026-09-30-rock-catalogue-design.md | BC's four stock asteroid NIFs (asteroid, asteroid1-3; the h-variants and Amagon share them) realise as a deterministic catalogue pick (crc32 of the ship NAME) scaled to the stock mesh's bounding radius (STOCK_RADIUS_MU). Catalogue is GENERATED and committed: change native/assets/rocks/recipe.json or native/src/rockgen and re-run the tool; never hand-edit; tests/tools/test_rock_catalogue_drift.py guards it. ⚠️ glTF convention (future mods inherit it): 1 unit = 1 m, BC model unit = 1.75 m, axes (x,y,z)→(−x,z,y). ⚠️ A scaled model's Model::source is "<path>#s=<scale>" — every damage-volume cache keys on it and splits it via assets::split_hull_source; never fs::exists() a raw source. Dev toggle: Developer Options → Lighting → Catalogue Rocks (applies on mission load). Programme: docs/superpowers/specs/2026-09-30-modern-asteroids-roadmap.md. |`

- [ ] **Step 4: Run the gate.**

Run: `scripts/check_tests.sh`
Expected: exit 0. Any failure not in `tests/known_failures.txt` is a regression from this branch: fix it (do not baseline it). A new unbaselined ctest SKIP also fails the gate; an asset-backed test must find content via `native/tests/support/content_root.h`.

- [ ] **Step 5: Commit.**

```bash
git add tests/host/test_rock_catalogue_load.py CLAUDE.md docs/superpowers/specs/2026-09-30-modern-asteroids-roadmap.md
git commit -m "test+docs(rocks): host load smoke test, CLAUDE.md row, roadmap status"
```

---

### Task 12: Embedded glTF textures (`.glb` binary chunk and data URIs)

Added 2026-09-30 at Mark's request. Blender's default glTF export is `.glb` with textures embedded in the binary chunk. Today `load_cpu` reads only images referenced by an external URI. An embedded image (`image.buffer_view`, or a `data:` URI) warns once and loads **untextured**, so a modder's first export would arrive with no textures.

**Files:**
- Modify: `native/src/assets/include/assets/gltf.h`, `native/src/assets/src/gltf_load.cc`, `native/src/assets/src/gltf_model_build.cc`, `docs/superpowers/specs/2026-09-30-rock-catalogue-design.md` (the Part 3 "Supported" list gains "embedded images (`.glb` buffer views and base64 data URIs)")
- Test: `native/tests/assets/cpu/gltf_load_test.cc`, `native/tests/assets/gpu/gltf_model_test.cc`, `native/tests/assets/cpu/gltf_fixture.h`

**Interfaces:**
- Consumes: Tasks 1–2 (`load_cpu`, `build_model_from_gltf`).
- Produces: `CpuMaterial`'s two image fields become a `CpuImage`:

```cpp
namespace assets::gltf {
struct CpuImage {
    std::filesystem::path path;         // absolute, for an external URI; empty otherwise
    std::vector<std::uint8_t> bytes;    // encoded PNG/JPEG bytes, for an embedded image; empty otherwise
    std::string key;                    // dedupe key: path.string(), or "<gltf path>#image<N>" when embedded
    bool empty() const { return path.empty() && bytes.empty(); }
};
struct CpuMaterial {
    glm::vec4 base_color_factor{1.0f};
    CpuImage base_color_image;
    CpuImage normal_image;
};
}
```

- [ ] **Step 1: Write the failing tests.**
  - In `gltf_fixture.h`, add `write_glb_fixture(dir, embed_texture)`. It writes the Task 1 triangle as a `.glb`: 12-byte header `glTF`, version 2, total length; a JSON chunk (type `0x4E4F534A`, padded with spaces to 4 bytes); a BIN chunk (type `0x004E4942`, padded with zeros), holding geometry plus, when `embed_texture`, a 2×2 PNG from `stbi_write_png_to_func` referenced by `images[0] = {bufferView, mimeType "image/png"}`.
  - Also add a `with_data_uri_texture` option to `write_fixture` that embeds the same PNG as `data:image/png;base64,...`.
  - `GltfLoad.GlbEmbeddedImageIsRead`: `load_cpu` of the `.glb` gives `materials[0].base_color_image.bytes` non-empty, `path` empty, and `key` ending in `#image0`.
  - `GltfLoad.DataUriImageIsRead`: same, for the data-URI fixture.
  - `GltfLoad.ExternalImageStillUsesPath`: the Task 2 external-PNG fixture still yields a non-empty `path` and empty `bytes`.
  - `TEST_F(GLContext, GlbEmbeddedTextureBindsBaseStage)`: `AssetCache::load` of the `.glb` gives `stages[Base].texture_index >= 0`, and no "ignoring data-uri image" warning is printed (capture stderr).
- [ ] **Step 2: Run to verify failure.** Run: `cmake --build build -j --target assets_tests && ./build/native/tests/assets/assets_tests --gtest_filter='GltfLoad*:*Glb*'`. Expected: FAIL (no `bytes` member / empty texture).
- [ ] **Step 3: Implement.**
  - In `load_cpu`, for a texture's image:
    - if `image->buffer_view`, copy `cgltf_buffer_view_data(view)` for `view->size` bytes (cgltf has already loaded the GLB BIN chunk / buffers);
    - else if `image->uri` starts with `data:`, decode it with `cgltf_load_buffer_base64` (size from the base64 length; strip the `data:...;base64,` prefix);
    - else keep today's external path.
  - Remove the "ignoring data-uri image" warning; keep a one-time warning only if decoding fails.
  - In `build_model_from_gltf`, key the texture map by `CpuImage::key`, and decode from `bytes` when present, else read the file at `path`.
- [ ] **Step 4: Run to verify pass.** Run: the whole `assets_tests` binary plus a full `cmake --build build -j`. Expected: all PASS.
- [ ] **Step 5: Commit.**

```bash
git add native/src/assets/include/assets/gltf.h native/src/assets/src/gltf_load.cc native/src/assets/src/gltf_model_build.cc native/tests/assets/cpu/gltf_load_test.cc native/tests/assets/gpu/gltf_model_test.cc native/tests/assets/cpu/gltf_fixture.h docs/superpowers/specs/2026-09-30-rock-catalogue-design.md
git commit -m "feat(assets): embedded glTF textures (.glb buffer views and data URIs)"
```

After this task, re-run `scripts/check_tests.sh` (it must exit 0).
