# Hull Name-Cut Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Erase BC's Federation "ID" name cut at NIF load time. Each ID patch shape is merged back into its saucer shape with UVs into the original saucer texture, driven by committed per-mesh fix files.

**Architecture:** An offline Python generator (`tools/gen_mesh_fixes.py`) reads stock NIF geometry through a new read-only binding and fits the saucer's texture projection. It writes `native/assets/mesh_fixes/<fnv1a64>.json`. At runtime `assets::AssetCache::load` hashes the NIF bytes, looks up a fix file, and applies it to the parsed `nif::File` before `build_model`. A bad fix warns and loads unpatched.

**Tech Stack:** C++20 (`native/src/assets`, `libnif`), nlohmann/json via CMake FetchContent, pybind11 binding in `native/src/host/host_bindings.cc`, Python 3.11 standard library plus Pillow, GoogleTest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md`

## Global Constraints

- Branch `feat/hull-name-cut-fix`, worktree `.claude/worktrees/hull-name-cut-fix`. **Never commit to `main`.** Check `git branch --show-current` before every commit.
- **Banned git commands:** `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit paths only. To mutate a file temporarily, back it up with `cp` and restore with `cp`, then `diff` to prove the restore.
- **Never launch the game** (`./build/dauntless`). Headless tests only.
- Build: `cmake --build build -j` from the worktree root. Never run cmake inside `native/`. Never create binaries anywhere else.
- **Paths rule:** Python in `engine/`, `tools/`, `tests/` must never spell `game` or `sdk` as a path segment. Use `engine.paths` (`paths.game_root()`, `paths.game_asset(rel)`), and never capture a path at import. C++ tests find BC content only through `native/tests/support/content_root.h` (`test_support::game_root()`). Guarded by `tests/unit/test_path_indirection.py`.
- No new Python dependencies. The project has only `pillow`; **no numpy**.
- **Hash:** FNV-1a 64 over the raw NIF file bytes, as 16 lowercase hex digits. Offset `14695981039346656037`, prime `1099511628211`. Fix files are `native/assets/mesh_fixes/<hash>.json`. This replaces the spec's "sha256", per spec §9 ("reuse what the tree already has"); Task 1 updates the spec to match.
- Fix-file `format` is `1`. Stock meshes only: the 10 listed in Task 5.
- A bad or mismatched fix **never throws out of the load**. It warns once per NIF and the mesh loads unpatched.
- C++ tests run with `DAUNTLESS_GAME_DIR` set so asset-backed tests don't skip. Get the value from `uv run python -c 'from engine import paths; print(paths.game_root())'`.
- Final gate: `scripts/check_tests.sh`, **run in the foreground**, and it must not report "NO BC CONTENT ROOT".

## Review Focus

1. **Patch and target shapes with different transforms:** merged vertices must land exactly where the patch drew them. Task 2 pins this with a test where the patch has its own transform.
2. **Ambiguous mirroring:** a target region lying entirely on one side of x=0 fits both the mirrored and unmirrored projection. If the patch reaches the other side, the generator must refuse rather than guess. Task 4 pins this with a refusal test.
3. **Weld pairs that don't actually coincide** (a stale or hand-edited fix): must be refused, not silently collapsed. Task 2 pins this with a refusal test.
4. **The same NIF loaded with and without a fix directory configured** (tests, tools): must produce distinct cache entries and never cross-serve. Task 3 pins this with a cache-key test.
5. **ReplaceTexture("ID") on a patched hull:** must not spam a warning on every registry variant. Task 6 pins this with a warn-once test.

---

### Task 1: Fix-file model, parser and FNV-1a hash (C++)

**Files:**
- Modify: `native/CMakeLists.txt` (add nlohmann/json FetchContent next to pybind11)
- Modify: `native/src/assets/CMakeLists.txt` (add source, link `nlohmann_json::nlohmann_json` PRIVATE)
- Create: `native/src/assets/include/assets/mesh_fix.h`
- Create: `native/src/assets/src/mesh_fix.cc`
- Create: `native/tests/assets/cpu/mesh_fix_parse_test.cc`
- Modify: `native/tests/assets/CMakeLists.txt` (add test source)
- Modify: `docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md` (sha256 → fnv1a64 everywhere, §9 first bullet resolved)

**Interfaces:**
- Produces:
  ```cpp
  namespace assets {
  struct MeshFixShapeRef { std::uint32_t block = 0; std::string name; };
  struct MeshFixMerge {
      MeshFixShapeRef patch, target;
      std::vector<std::array<float, 2>> uvs;                    // one per patch vertex
      std::vector<std::pair<std::uint32_t, std::uint32_t>> weld; // (patch v, target v)
      std::optional<std::vector<std::array<float, 3>>> normals;  // patch-local, one per patch vertex
  };
  struct MeshFix { int format = 1; std::vector<MeshFixMerge> merges; };

  std::string fnv1a64_hex(std::string_view bytes);   // 16 lowercase hex digits
  /// Parse a fix file's JSON text. On failure returns nullopt and sets *error.
  std::optional<MeshFix> parse_mesh_fix(std::string_view json_text, std::string* error);
  }
  ```

- [ ] **Step 1: Add nlohmann/json to the build**

In `native/CMakeLists.txt`, directly after `FetchContent_MakeAvailable(pybind11)`:

```cmake
# nlohmann/json for the mesh-fix files (native/assets/mesh_fixes/*.json).
# Release tarball rather than the full git history.
FetchContent_Declare(
    nlohmann_json
    URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz
)
FetchContent_MakeAvailable(nlohmann_json)
```

In `native/src/assets/CMakeLists.txt`, add `src/mesh_fix.cc` to the `assets` library sources and `nlohmann_json::nlohmann_json` to its PRIVATE link libraries. Read the file first and follow its existing layout.

- [ ] **Step 2: Write the failing tests** in `native/tests/assets/cpu/mesh_fix_parse_test.cc` and add `cpu/mesh_fix_parse_test.cc` to `assets_tests` in `native/tests/assets/CMakeLists.txt`:

```cpp
#include <gtest/gtest.h>
#include <assets/mesh_fix.h>

namespace {
const char* kValid = R"({
  "format": 1,
  "source": "data/Models/Ships/Galaxy/Galaxy.nif",
  "generator": "tools/gen_mesh_fixes.py",
  "merges": [{
    "patch":  {"block": 61, "name": "Ent-D Saucer Section:9"},
    "target": {"block": 14, "name": "Ent-D Saucer Section:1"},
    "method": "planar-mirrored",
    "max_fit_error": 7.1e-7,
    "uvs":    [[0.5, 0.25], [0.75, 1.0]],
    "weld":   [[0, 37], [1, 52]],
    "normals": null
  }]
})";
}  // namespace

TEST(MeshFixHash, Fnv1a64KnownVectors) {
    EXPECT_EQ(assets::fnv1a64_hex(""), "cbf29ce484222325");
    EXPECT_EQ(assets::fnv1a64_hex("a"), "af63dc4c8601ec8c");
    EXPECT_EQ(assets::fnv1a64_hex("foobar"), "85944171f73967e8");
}

TEST(MeshFixParse, ValidFileRoundTrips) {
    std::string err;
    auto fix = assets::parse_mesh_fix(kValid, &err);
    ASSERT_TRUE(fix.has_value()) << err;
    ASSERT_EQ(fix->merges.size(), 1u);
    const auto& m = fix->merges[0];
    EXPECT_EQ(m.patch.block, 61u);
    EXPECT_EQ(m.patch.name, "Ent-D Saucer Section:9");
    EXPECT_EQ(m.target.block, 14u);
    ASSERT_EQ(m.uvs.size(), 2u);
    EXPECT_FLOAT_EQ(m.uvs[1][0], 0.75f);
    ASSERT_EQ(m.weld.size(), 2u);
    EXPECT_EQ(m.weld[1].first, 1u);
    EXPECT_EQ(m.weld[1].second, 52u);
    EXPECT_FALSE(m.normals.has_value());
}

TEST(MeshFixParse, NormalsArrayIsRead) {
    std::string text = kValid;
    text.replace(text.find("\"normals\": null"), 15,
                 "\"normals\": [[0,0,1],[0,1,0]]");
    std::string err;
    auto fix = assets::parse_mesh_fix(text, &err);
    ASSERT_TRUE(fix.has_value()) << err;
    ASSERT_TRUE(fix->merges[0].normals.has_value());
    EXPECT_FLOAT_EQ((*fix->merges[0].normals)[1][1], 1.0f);
}

TEST(MeshFixParse, RejectsUnknownFormat) {
    std::string text = kValid;
    text.replace(text.find("\"format\": 1"), 11, "\"format\": 2");
    std::string err;
    EXPECT_FALSE(assets::parse_mesh_fix(text, &err).has_value());
    EXPECT_NE(err.find("format"), std::string::npos) << err;
}

TEST(MeshFixParse, RejectsMalformedJson) {
    std::string err;
    EXPECT_FALSE(assets::parse_mesh_fix("{ not json", &err).has_value());
    EXPECT_FALSE(err.empty());
}

TEST(MeshFixParse, RejectsMissingFieldAndWrongShape) {
    std::string err;
    EXPECT_FALSE(assets::parse_mesh_fix(R"({"format":1})", &err).has_value());
    std::string bad_uv = kValid;
    bad_uv.replace(bad_uv.find("[0.5, 0.25]"), 11, "[0.5]");
    EXPECT_FALSE(assets::parse_mesh_fix(bad_uv, &err).has_value());
}
```

- [ ] **Step 3: Build and watch the tests fail**

Run: `cmake --build build -j 2>&1 | tail -20`
Expected: compile error, because `assets/mesh_fix.h` doesn't exist.

- [ ] **Step 4: Implement** `native/src/assets/include/assets/mesh_fix.h` (declarations exactly as in **Interfaces**, with a header comment pointing at the spec) and `native/src/assets/src/mesh_fix.cc`:

```cpp
// native/src/assets/src/mesh_fix.cc
// Parsing half of the hull name-cut fix (spec:
// docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md).
#include <assets/mesh_fix.h>

#include <cstdio>
#include <nlohmann/json.hpp>

namespace assets {

std::string fnv1a64_hex(std::string_view bytes) {
    std::uint64_t h = 14695981039346656037ull;
    for (unsigned char c : bytes) { h ^= c; h *= 1099511628211ull; }
    char buf[17];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(h));
    return buf;
}

namespace {
MeshFixShapeRef read_ref(const nlohmann::json& j) {
    return {j.at("block").get<std::uint32_t>(), j.at("name").get<std::string>()};
}
}  // namespace

std::optional<MeshFix> parse_mesh_fix(std::string_view text, std::string* error) {
    auto fail = [&](std::string msg) -> std::optional<MeshFix> {
        if (error) *error = std::move(msg);
        return std::nullopt;
    };
    try {
        auto j = nlohmann::json::parse(text);
        MeshFix fix;
        fix.format = j.at("format").get<int>();
        if (fix.format != 1)
            return fail("unsupported mesh-fix format " + std::to_string(fix.format));
        for (const auto& jm : j.at("merges")) {
            MeshFixMerge m;
            m.patch  = read_ref(jm.at("patch"));
            m.target = read_ref(jm.at("target"));
            for (const auto& uv : jm.at("uvs")) {
                if (!uv.is_array() || uv.size() != 2) return fail("uv entry is not [u, v]");
                m.uvs.push_back({uv[0].get<float>(), uv[1].get<float>()});
            }
            for (const auto& w : jm.at("weld")) {
                if (!w.is_array() || w.size() != 2) return fail("weld entry is not a pair");
                m.weld.emplace_back(w[0].get<std::uint32_t>(), w[1].get<std::uint32_t>());
            }
            const auto& jn = jm.at("normals");
            if (!jn.is_null()) {
                std::vector<std::array<float, 3>> ns;
                for (const auto& n : jn) {
                    if (!n.is_array() || n.size() != 3) return fail("normal entry is not [x, y, z]");
                    ns.push_back({n[0].get<float>(), n[1].get<float>(), n[2].get<float>()});
                }
                m.normals = std::move(ns);
            }
            fix.merges.push_back(std::move(m));
        }
        return fix;
    } catch (const std::exception& e) {
        return fail(std::string("mesh-fix parse error: ") + e.what());
    }
}

}  // namespace assets
```

- [ ] **Step 5: Build, then run the new tests**

Run: `cmake --build build -j && ./build/native/tests/assets/assets_tests --gtest_filter='MeshFix*'`
(If the binary path differs, find it with `find build -name assets_tests -type f`.)
Expected: all 6 PASS.

- [ ] **Step 6: Update the spec.** In the spec, replace every `sha256` / `<nif-sha256>` with `fnv1a64` / `<nif-fnv1a64>`, and replace the §9 first bullet with: "Resolved: FNV-1a 64 (the tree's existing content hash, used by the `.dhv` cache) and nlohmann/json via FetchContent (no JSON parser existed)."

- [ ] **Step 7: Commit**

```bash
git branch --show-current   # must print feat/hull-name-cut-fix
git add native/CMakeLists.txt native/src/assets/CMakeLists.txt \
  native/src/assets/include/assets/mesh_fix.h native/src/assets/src/mesh_fix.cc \
  native/tests/assets/cpu/mesh_fix_parse_test.cc native/tests/assets/CMakeLists.txt \
  docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md
git commit -m "feat(assets): mesh-fix file model, parser and FNV-1a content hash"
```

---

### Task 2: `apply_mesh_fix` — merge, weld and hide, all-or-nothing

**Files:**
- Modify: `native/src/assets/include/assets/mesh_fix.h`
- Modify: `native/src/assets/src/mesh_fix.cc`
- Create: `native/tests/assets/cpu/mesh_fix_apply_test.cc` (add to `native/tests/assets/CMakeLists.txt`)

**Interfaces:**
- Consumes: `MeshFix`, `MeshFixMerge` (Task 1); `nif::File`, `nif::NiNode`, `nif::NiTriShape`, `nif::NiTriShapeData`, `nif::AvObjectBase` from `native/src/nif/include/nif/block.h` and `file.h`.
- Produces:
  ```cpp
  /// Apply every merge in `fix` to `file`, or none of them. Returns "" on
  /// success, otherwise the reason and leaves `file` unchanged.
  std::string apply_mesh_fix(nif::File& file, const MeshFix& fix);
  ```

**Facts the implementer needs:**
- `file.blocks[i]` is a `std::variant`. Cross-block references (`NiNode::child_links`, `NiTriShape::data_link`) hold **link IDs**; `file.block_ids[i]` is block `i`'s ID. Map ID → index by scanning `block_ids`.
- A block's local transform: `AvObjectBase` has `translation`, `rotation` (`Mat3x3`, row-major storage, column-vector maths `v' = R·v`) and uniform `scale`. `world(shape) = world(parent) · T·R·S`. The root is `file.blocks[0]`. A shape's parent is the `NiNode` whose `child_links` contains the shape's link ID.
- Vertices in `NiTriShapeData` are shape-local. A patch vertex goes to the target frame as `p_t = W_t⁻¹ · W_p · p`. Normals use only the rotation parts: `n_t = normalize(R_t⁻¹ · R_p · n)`.
- `NiTriShapeData` fields to keep consistent: `num_vertices` (uint16), `vertices`, `normals` + `has_normals`, `vertex_colors` + `has_vertex_colors`, `uv_sets` (vector per set) + `has_uv`, `num_triangles`, `num_triangle_points` (= 3 × triangles), `triangles`, `num_match_groups` + `match_groups`.
- The hidden flag is `av.flags |= 0x0001`; `build_model` already skips such shapes (`model_build.cc`, "Honor the NiAVObject hidden flag").

**Validation (all checked before any mutation; the first failure returns its reason):**
1. `patch.block` / `target.block` are in range, hold `NiTriShape`, and `av.obj.name` equals the fix's name.
2. Both shapes' `data_link` resolve to `NiTriShapeData`, and the two data blocks differ.
3. Both have exactly 1 UV set, both have normals, and `has_vertex_colors` agrees.
4. `uvs.size() == patch.num_vertices`; if `normals` is present, it has the same size.
5. Every weld pair is in range, no patch vertex appears twice, and after transforming the patch vertex into the target frame: position within `1e-3` of the target vertex, UV within `1e-5` of the target UV, and normal dot product `> 0.999`.
6. `target.num_vertices + patch.num_vertices - weld.size() <= 65535`.

- [ ] **Step 1: Write the failing tests.** Build the synthetic file with a helper in the test:

```cpp
#include <gtest/gtest.h>
#include <assets/mesh_fix.h>
#include <nif/file.h>
#include <cmath>

namespace {
// Root NiNode (id 1) with two NiTriShape children: target (id 2, data id 3)
// and patch (id 4, data id 5). The target is a unit quad at z=0 whose right
// edge x=1 is shared with the patch quad spanning x=1..2.
struct Synthetic {
    nif::File f;
    std::size_t target_idx = 1, patch_idx = 3;
};

nif::NiTriShapeData quad(float x0, float x1, float u0, float u1) {
    nif::NiTriShapeData d;
    d.num_vertices = 4;
    d.has_vertices = d.has_normals = d.has_uv = true;
    d.vertices = {{x0,0,0},{x1,0,0},{x1,1,0},{x0,1,0}};
    d.normals  = {{0,0,1},{0,0,1},{0,0,1},{0,0,1}};
    d.uv_sets  = {{{u0,0},{u1,0},{u1,1},{u0,1}}};
    d.num_triangles = 2; d.num_triangle_points = 6;
    d.triangles = {{0,1,2},{0,2,3}};
    d.num_match_groups = 1; d.match_groups = {{0,1}};
    return d;
}

Synthetic make() {
    Synthetic s;
    nif::NiNode root; root.av.obj.name = "root"; root.child_links = {2, 4};
    nif::NiTriShape target; target.av.obj.name = "saucer"; target.data_link = 3;
    nif::NiTriShape patch;  patch.av.obj.name  = "id";     patch.data_link  = 5;
    s.f.blocks = {root, target, quad(0,1,0,0.5f), patch, quad(1,2,0,1)};
    s.f.block_ids = {1, 2, 3, 4, 5};
    s.f.root = nif::BlockHandle{&s.f.blocks.front()};
    return s;
}

assets::MeshFix fix_for(const Synthetic&) {
    assets::MeshFixMerge m;
    m.patch = {3, "id"}; m.target = {1, "saucer"};
    // Rebuilt UVs continue the target's u = x/2 mapping.
    m.uvs = {{0.5f,0},{1.0f,0},{1.0f,1},{0.5f,1}};
    m.weld = {{0,1},{3,2}};   // patch x=1 edge == target x=1 edge
    assets::MeshFix fix; fix.merges = {m};
    return fix;
}

const nif::NiTriShapeData& data(const Synthetic& s, std::size_t i) {
    return std::get<nif::NiTriShapeData>(s.f.blocks[i]);
}
}  // namespace

TEST(MeshFixApply, MergesWeldsAndHidesPatch) {
    auto s = make();
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_for(s)), "");
    const auto& t = data(s, 2);
    EXPECT_EQ(t.num_vertices, 6);             // 4 + 4 - 2 welded
    EXPECT_EQ(t.vertices.size(), 6u);
    EXPECT_EQ(t.normals.size(), 6u);
    EXPECT_EQ(t.uv_sets[0].size(), 6u);
    EXPECT_EQ(t.num_triangles, 4);
    EXPECT_EQ(t.num_triangle_points, 12u);
    EXPECT_EQ(t.num_match_groups, 0);
    EXPECT_TRUE(t.match_groups.empty());
    // Appended patch triangle {0,1,2} must reference the WELDED target vertex 1.
    EXPECT_EQ(t.triangles[2][0], 1);
    EXPECT_FLOAT_EQ(t.uv_sets[0][4][0], 1.0f);   // patch v1 (x=2) got u=1
    EXPECT_TRUE(std::get<nif::NiTriShape>(s.f.blocks[3]).av.flags & 0x0001u);
}

TEST(MeshFixApply, TransformsPatchIntoTargetFrame) {
    auto s = make();
    // Patch shape carries its own transform: data authored around the origin,
    // shape translated +1 in x. Same world placement as make()'s patch.
    auto& pd = std::get<nif::NiTriShapeData>(s.f.blocks[4]);
    for (auto& v : pd.vertices) v.x -= 1.0f;
    std::get<nif::NiTriShape>(s.f.blocks[3]).av.translation = {1, 0, 0};
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_for(s)), "");
    const auto& t = data(s, 2);
    EXPECT_NEAR(t.vertices[4].x, 2.0f, 1e-6);    // patch v1 lands at world x=2
}

TEST(MeshFixApply, AppliesNormalOverride) {
    auto s = make();
    auto fix = fix_for(s);
    fix.merges[0].weld.clear();
    fix.merges[0].normals = std::vector<std::array<float,3>>(4, {0, 1, 0});
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix), "");
    EXPECT_NEAR(data(s, 2).normals[5].y, 1.0f, 1e-6);
}

// Each refusal leaves the file untouched.
void expect_refused(assets::MeshFix fix, const char* why) {
    auto s = make();
    auto before = data(s, 2);
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "") << why;
    EXPECT_EQ(data(s, 2).num_vertices, before.num_vertices) << why;
    EXPECT_EQ(data(s, 2).match_groups.size(), 1u) << why;
    EXPECT_FALSE(std::get<nif::NiTriShape>(s.f.blocks[3]).av.flags & 0x0001u) << why;
}

TEST(MeshFixApply, RefusalsLeaveFileUntouched) {
    auto s = make();
    auto f = fix_for(s);
    { auto x = f; x.merges[0].patch.name = "other";      expect_refused(x, "name mismatch"); }
    { auto x = f; x.merges[0].patch.block = 99;          expect_refused(x, "block out of range"); }
    { auto x = f; x.merges[0].target.block = 0;          expect_refused(x, "not a trishape"); }
    { auto x = f; x.merges[0].uvs.pop_back();            expect_refused(x, "uv count"); }
    { auto x = f; x.merges[0].normals = std::vector<std::array<float,3>>(2, {0,0,1});
                                                         expect_refused(x, "normal count"); }
    { auto x = f; x.merges[0].weld.push_back({0, 2});    expect_refused(x, "patch vertex welded twice"); }
    { auto x = f; x.merges[0].weld = {{0, 9}};           expect_refused(x, "weld out of range"); }
    { auto x = f; x.merges[0].weld = {{0, 0}};           expect_refused(x, "weld positions differ"); }
    { auto x = f; x.merges[0].uvs[0] = {0.9f, 0};        expect_refused(x, "weld uv differs"); }
}

TEST(MeshFixApply, RefusesVertexOverflow) {
    auto s = make();
    auto& t = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
    t.num_vertices = 65534;
    t.vertices.resize(65534, {5,5,5});
    t.normals.resize(65534, {0,0,1});
    t.uv_sets[0].resize(65534, {0,0});
    auto fix = fix_for(s);
    fix.merges[0].weld.clear();
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "");
}
```

- [ ] **Step 2: Build and watch it fail**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: compile error, because `apply_mesh_fix` isn't declared.

- [ ] **Step 3: Implement `apply_mesh_fix`** in `mesh_fix.cc`. Structure:
  1. `index_of(file, link_id)`: linear scan of `block_ids`, or `SIZE_MAX`.
  2. `parent_of(file, idx)`: the NiNode whose `child_links` resolve to `idx`.
  3. `world_of(file, idx)`: a 4×4 matrix (use `glm::mat4`, which the assets library already includes) that composes `T·R·S` up the parent chain. The NIF `Mat3x3` is row-major, so `glm` element `[col][row] = m[row*3+col]`.
  4. Phase 1: validate every merge in `fix` against rules 1–6 above and collect a plan. Return the first error message, prefixed `"merge N: "`.
  5. Phase 2 (only if all pass): for each merge, build a patch→target index map (welded → target index, others → appended index in order), append transformed positions, normals (the override if present, else transformed), fix UVs and vertex colours, append remapped triangles, update counts, clear match groups, and set the patch's hidden flag.

- [ ] **Step 4: Build, then run the tests**

Run: `cmake --build build -j && ./build/native/tests/assets/assets_tests --gtest_filter='MeshFix*'`
Expected: all PASS (Task 1's 6 plus Task 2's 5).

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add native/src/assets/include/assets/mesh_fix.h native/src/assets/src/mesh_fix.cc \
  native/tests/assets/cpu/mesh_fix_apply_test.cc native/tests/assets/CMakeLists.txt
git commit -m "feat(assets): apply_mesh_fix merges an ID patch into its saucer, all-or-nothing"
```

---

### Task 3: Wire fixes into `AssetCache::load` and the host

**Files:**
- Modify: `native/src/assets/include/assets/cache.h` (Config field)
- Modify: `native/src/assets/src/cache.cc:70-106`
- Modify: `native/src/host/host_bindings.cc:526-533` (set the config field)
- Modify: `native/tests/assets/cpu/cache_test.cc`

**Interfaces:**
- Consumes: `fnv1a64_hex`, `parse_mesh_fix`, `apply_mesh_fix` (Tasks 1–2); `renderer::project_asset_root()` (`native/src/renderer/include/renderer/asset_path.h`).
- Produces:
  ```cpp
  // in AssetCache::Config
  /// Directory holding mesh-fix files, evaluated at EACH load (resolve at use;
  /// the project asset root can be set after the cache is built). Empty
  /// function or empty path ⇒ no fixes.
  std::function<std::filesystem::path()> mesh_fix_dir;
  ```
  The cache key gains the suffix `"|fix:<hash>"` when, and only when, a fix file exists for the NIF and **parses**. This is decided before `nif::load`, so a cache hit never re-parses the NIF. A fix that parses but then fails to apply is stored under that key with the unpatched model, which stays consistent for the life of the process.

- [ ] **Step 1: Write the failing tests** (append to `cache_test.cc`; they reuse its `galaxy_path()`, `fed_high_path()`, `stub_config()`):

```cpp
#include <assets/mesh_fix.h>
#include <fstream>
#include <sstream>

namespace {
std::string file_bytes(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    std::ostringstream ss; ss << in.rdbuf(); return ss.str();
}
fs::path temp_fix_dir(const char* tag) {
    auto d = fs::temp_directory_path() / (std::string("dauntless_mesh_fix_") + tag);
    fs::remove_all(d); fs::create_directories(d); return d;
}
}  // namespace

TEST(AssetCacheMeshFix, EmptyFixFileAppliesAndChangesCacheKey) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    auto dir = temp_fix_dir("empty");
    std::ofstream(dir / (assets::fnv1a64_hex(file_bytes(galaxy_path())) + ".json"))
        << R"({"format":1,"merges":[]})";

    assets::AssetCache plain(stub_config());
    auto cfg = stub_config();
    cfg.mesh_fix_dir = [dir] { return dir; };
    assets::AssetCache fixed(cfg);
    auto a = plain.load(galaxy_path(), fed_high_path());
    auto b = fixed.load(galaxy_path(), fed_high_path());
    // An empty merge list changes nothing visible...
    EXPECT_EQ(a->meshes.size(), b->meshes.size());
    // ...and two loads through the fixed cache share one entry.
    EXPECT_EQ(b.get(), fixed.load(galaxy_path(), fed_high_path()).get());
}

TEST(AssetCacheMeshFix, RefusedFixLoadsUnpatched) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    auto dir = temp_fix_dir("refused");
    std::ofstream(dir / (assets::fnv1a64_hex(file_bytes(galaxy_path())) + ".json"))
        << R"({"format":1,"merges":[{"patch":{"block":0,"name":"nope"},
              "target":{"block":1,"name":"nope"},"uvs":[],"weld":[],"normals":null}]})";
    assets::AssetCache plain(stub_config());
    auto cfg = stub_config();
    cfg.mesh_fix_dir = [dir] { return dir; };
    assets::AssetCache fixed(cfg);
    EXPECT_EQ(plain.load(galaxy_path(), fed_high_path())->meshes.size(),
              fixed.load(galaxy_path(), fed_high_path())->meshes.size());
}

TEST(AssetCacheMeshFix, MalformedFixFileLoadsUnpatched) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    auto dir = temp_fix_dir("malformed");
    std::ofstream(dir / (assets::fnv1a64_hex(file_bytes(galaxy_path())) + ".json")) << "{ nope";
    auto cfg = stub_config();
    cfg.mesh_fix_dir = [dir] { return dir; };
    assets::AssetCache fixed(cfg);
    EXPECT_NO_THROW(fixed.load(galaxy_path(), fed_high_path()));
}

TEST(AssetCacheMeshFix, NoFixDirConfiguredIsTodayBehaviour) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    auto cfg = stub_config();
    cfg.mesh_fix_dir = [] { return fs::path(); };
    assets::AssetCache c(cfg);
    EXPECT_NO_THROW(c.load(galaxy_path(), fed_high_path()));
}
```

- [ ] **Step 2: Build and run; watch them fail**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: compile error, because `Config::mesh_fix_dir` doesn't exist.

- [ ] **Step 3: Implement.** In `cache.cc`'s three-argument `load`, before the cache lookup:
  1. Read the NIF bytes (`std::ifstream`, binary). Compute `hash = fnv1a64_hex(bytes)`.
  2. If `impl_->config.mesh_fix_dir` is set and returns a non-empty dir containing `<hash>.json`, read and `parse_mesh_fix` it.
  3. Build `canon` as today, plus `"|fix:" + hash` if a fix parsed. On a parse error, warn (below) and use no suffix.
  4. Do the existing cache-entry lookup with that key and return on a hit, exactly as today (the search-path-mismatch check is unchanged).
  5. On a miss, `nif::load(nif_path)`. If a fix parsed, call `apply_mesh_fix(file, *fix)`. On an apply error, warn and build unpatched.
  The warning prints once per hash to stderr:
     `mesh fix <hash>.json for <nif_path> refused: <reason>; loading unpatched`
     Use a function-local `static std::unordered_set<std::string> warned;`.
  Reading and hashing the NIF bytes on every `load` call is accepted: `host_bindings.cc` already dedupes repeat loads before they reach the cache.

  In `host_bindings.cc` where `g_cache` is constructed, add:
  ```cpp
  cfg.mesh_fix_dir = [] {
      return std::filesystem::path(renderer::project_asset_root()) / "mesh_fixes";
  };
  ```

- [ ] **Step 4: Build and run**

Run: `cmake --build build -j && DAUNTLESS_GAME_DIR="$(uv run python -c 'from engine import paths; print(paths.game_root())')" ./build/native/tests/assets/assets_tests --gtest_filter='AssetCache*:MeshFix*'`
Expected: all PASS, none SKIPPED.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add native/src/assets/include/assets/cache.h native/src/assets/src/cache.cc \
  native/src/host/host_bindings.cc native/tests/assets/cpu/cache_test.cc
git commit -m "feat(assets): AssetCache applies hash-keyed mesh fixes before build"
```

---

### Task 4: `nif_shapes` binding and the generator's pure core

**Files:**
- Modify: `native/src/host/host_bindings.cc` (new `m.def("nif_shapes", ...)` next to `parse_set_camera`)
- Create: `tools/gen_mesh_fixes.py`
- Create: `tests/tools/test_gen_mesh_fixes.py`
- Create: `tests/host/test_nif_shapes_binding.py`

**Interfaces:**
- Produces (binding): `_dauntless_host.nif_shapes(abs_path: str) -> list[dict]`. There is one dict per `NiTriShape` block, in block order, with keys `block` (int), `name` (str), `textures` (list[str], image file basenames from `NiTextureProperty` / `NiMultiTextureProperty` stages), `vertices` (list of `(x, y, z)` in **world** space), `normals` (world-rotated, normalised), `uvs` (UV set 0, list of `(u, v)`), `triangles` (list of `(a, b, c)`), `hidden` (bool). It returns `None` if the file doesn't exist or doesn't parse.
- Produces (Python, `tools/gen_mesh_fixes.py`):
  ```python
  STOCK_MESHES: tuple[str, ...]            # 10 game-relative paths (Task 5)
  def fnv1a64_hex(data: bytes) -> str
  def to_f32(x: float) -> float            # round-trip through float32
  def regions(shape: dict) -> list[int]    # per-vertex region label (pos+uv weld, triangle union)
  def fit_projection(points, uvs) -> tuple[str, list, float] | None
      # tries (mirrored, xy), (mirrored, xyz), (unmirrored, xy), (unmirrored, xyz);
      # returns (method, coeffs, max_err) for the first with max_err < 1e-4
  def apply_projection(method, coeffs, point) -> tuple[float, float]
  def seam_copy(patch, known: dict[int, tuple[float, float]]) -> list[tuple[float, float]]
      # interior UVs by inverse-edge-length Laplace, 2000 Gauss-Seidel sweeps
  def build_fix(shapes: list[dict], rel: str, target_override: str | None) -> tuple[dict, dict]
      # -> (fix_json_dict, review_info{"target_texture": str, "uvs": [...], "patch_tris": [...],
      #                                  "target_uvs": [...], "target_tris": [...]})
  def dumps(fix: dict) -> str               # json.dumps(fix, indent=2) + "\n"
  ```

- [ ] **Step 1: Write the failing binding test** `tests/host/test_nif_shapes_binding.py`:

```python
import pytest
from engine import paths


def _host():
    return pytest.importorskip("_dauntless_host")


def test_galaxy_has_one_id_shape_with_consistent_arrays():
    nif = paths.game_asset("data/Models/Ships/Galaxy/Galaxy.nif")
    if nif is None or not nif.exists():
        pytest.skip("BC content not configured")
    shapes = _host().nif_shapes(str(nif))
    ids = [s for s in shapes if any("ID" in t for t in s["textures"])]
    assert len(ids) == 1
    s = ids[0]
    assert s["name"] == "Ent-D Saucer Section:9"
    assert len(s["vertices"]) == len(s["normals"]) == len(s["uvs"]) == 25
    assert len(s["triangles"]) == 30
    assert not s["hidden"]


def test_missing_file_returns_none():
    assert _host().nif_shapes("/nonexistent/x.nif") is None
```

Before writing the test, check how `paths.game_asset` behaves in `engine/paths.py`, since its return type decides the skip condition. Adjust the two `nif` lines to match its real signature; keep the skip-when-absent behaviour.

- [ ] **Step 2: Write the failing generator tests** `tests/tools/test_gen_mesh_fixes.py` (synthetic, no BC content):

```python
import json
import math

import pytest

from tools import gen_mesh_fixes as g


def _grid_shape(block, name, x0, x1, mirrored, tex="Hull_glow.tga", n=4, y0=0.0, y1=1.0):
    """A flat n×n grid over x∈[x0,x1], y∈[y0,y1] whose UVs are an exact
    projection: u = 0.1 + 0.4*f(x), v = 0.2 + 0.5*y, f = |x| if mirrored."""
    verts, uvs, tris = [], [], []
    for j in range(n + 1):
        for i in range(n + 1):
            x = x0 + (x1 - x0) * i / n
            y = y0 + (y1 - y0) * j / n
            verts.append((x, y, 0.0))
            fx = abs(x) if mirrored else x
            uvs.append((0.1 + 0.4 * fx, 0.2 + 0.5 * y))
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            tris += [(a, a + 1, a + n + 2), (a, a + n + 2, a + n + 1)]
    return {"block": block, "name": name, "textures": [tex], "vertices": verts,
            "normals": [(0.0, 0.0, 1.0)] * len(verts), "uvs": uvs,
            "triangles": tris, "hidden": False}


def test_fnv_known_vectors():
    assert g.fnv1a64_hex(b"") == "cbf29ce484222325"
    assert g.fnv1a64_hex(b"foobar") == "85944171f73967e8"


@pytest.mark.parametrize("mirrored", [True, False])
def test_fit_projection_recovers_exact_mapping(mirrored):
    s = _grid_shape(1, "saucer", -1.0, 1.0, mirrored)
    method, coeffs, err = g.fit_projection(s["vertices"], s["uvs"])
    assert err < 1e-6
    assert ("mirrored" in method) == mirrored
    u, v = g.apply_projection(method, coeffs, (-0.5, 0.5, 0.0))
    assert math.isclose(u, 0.1 + 0.4 * (0.5 if mirrored else -0.5), abs_tol=1e-6)


def test_fit_projection_rejects_non_planar():
    s = _grid_shape(1, "saucer", -1.0, 1.0, False)
    s["uvs"] = [(u + 0.3 * y * y, v) for (u, v), (_, y, _) in zip(s["uvs"], s["vertices"])]
    assert g.fit_projection(s["vertices"], s["uvs"]) is None


def test_regions_split_on_uv_seams_and_join_flat_shading():
    s = _grid_shape(1, "saucer", 0.0, 1.0, False, n=2)
    labels = g.regions(s)
    assert len(set(labels)) == 1
    # Duplicate one vertex with a different UV: a seam, still one region per side.
    s2 = dict(s, vertices=s["vertices"] + [s["vertices"][0]],
              uvs=s["uvs"] + [(0.9, 0.9)], normals=s["normals"] + [(0, 0, 1)])
    assert len(set(g.regions(s2))) == 2


def _saucer_and_patch():
    # Saucer spans both sides of x=0 (as real mirrored saucers do); the patch
    # sits above it (y∈[1,2]) sharing the y=1 edge, crossing the centreline.
    target = _grid_shape(1, "saucer", -2.0, 2.0, True)
    patch = _grid_shape(2, "idpatch", -1.0, 1.0, True, tex="Hull_ID_glow.tga", y0=1.0, y1=2.0)
    patch["uvs"] = [(0.0, 0.0)] * len(patch["uvs"])   # the ID texture's own UVs
    return target, patch


def test_build_fix_merges_patch_with_exact_uvs_and_welds():
    target, patch = _saucer_and_patch()
    fix, review = g.build_fix([target, patch], "data/Models/Ships/X/X.nif", None)
    m = fix["merges"][0]
    assert m["patch"] == {"block": 2, "name": "idpatch"}
    assert m["target"] == {"block": 1, "name": "saucer"}
    assert "mirrored" in m["method"]
    assert len(m["uvs"]) == len(patch["vertices"])
    # Patch vertex at x=1,y=2 continues the saucer mapping: u=0.1+0.4*|1|, v=0.2+0.5*2.
    idx = patch["vertices"].index((1.0, 2.0, 0.0))
    assert m["uvs"][idx] == pytest.approx([0.5, 1.2], abs=1e-6)
    # Mirror side: the x=-1 vertex gets the same u.
    idx_neg = patch["vertices"].index((-1.0, 2.0, 0.0))
    assert m["uvs"][idx_neg][0] == pytest.approx(0.5, abs=1e-6)
    # Shared y=1 edge: patch x∈{-1,-.5,0,.5,1} vs saucer x∈{-2,-1,0,1,2} → 3 coincide.
    assert len(m["weld"]) == 3
    assert m["normals"] is None


def test_build_fix_refuses_ambiguous_mirroring():
    # Saucer region wholly on x<=0 fits BOTH projections; a patch reaching x>0
    # cannot be resolved without guessing.
    target = _grid_shape(1, "saucer", -2.0, 0.0, True)
    patch = _grid_shape(2, "idpatch", -1.0, 1.0, True, tex="Hull_ID_glow.tga", y0=1.0, y1=2.0)
    with pytest.raises(ValueError, match="ambiguous"):
        g.build_fix([target, patch], "r", None)


def test_seam_copy_interpolates_interior():
    patch = _grid_shape(2, "idpatch", 0.0, 1.0, False, n=2)
    known = {i: uv for i, uv in enumerate(patch["uvs"]) if i != 4}  # 4 = centre
    out = g.seam_copy(patch, known)
    assert out[4] == pytest.approx(patch["uvs"][4], abs=1e-4)


def test_dumps_is_deterministic_and_float32():
    target, patch = _saucer_and_patch()
    a = g.dumps(g.build_fix([target, patch], "r", None)[0])
    b = g.dumps(g.build_fix([target, patch], "r", None)[0])
    assert a == b and a.endswith("\n")
    for u, v in json.loads(a)["merges"][0]["uvs"]:
        assert g.to_f32(u) == u and g.to_f32(v) == v


def test_build_fix_refuses_mesh_without_id_shape():
    with pytest.raises(ValueError):
        g.build_fix([_grid_shape(1, "saucer", 0, 1, False)], "r", None)
```

- [ ] **Step 3: Run both test files and watch them fail**

Run: `uv run pytest tests/tools/test_gen_mesh_fixes.py tests/host/test_nif_shapes_binding.py -q`
Expected: ImportError on `tools.gen_mesh_fixes`, and AttributeError on `nif_shapes`.

- [ ] **Step 4: Implement the binding** in `host_bindings.cc`. Follow `parse_set_camera_impl`'s style: `nif::load` in try/catch, return `py::none()` on failure. Compute world matrices exactly as Task 2's `world_of`. If Task 2 put it in an anonymous namespace, expose it from `assets/mesh_fix.h` as `glm::mat4 nif_block_world(const nif::File&, std::size_t)` and reuse it, rather than writing a second copy. Texture basenames come from walking each shape's `av.property_links` for `NiTextureProperty::image_link` and each `NiMultiTextureProperty::elements[i].image_link` with `has_image`, resolving to `NiImage::file_name` and keeping the part after the last `/` or `\`.

- [ ] **Step 5: Implement `tools/gen_mesh_fixes.py`**: the pure functions listed in **Interfaces**, plus a `main()` that isn't run by the tests (Task 5 fills in its CLI). Implementation notes:
  - `fit_projection`: features per candidate are `[f(x), y, 1]` or `[f(x), y, z, 1]`, where `f = abs` for mirrored. Solve the normal equations for u and v separately with Gaussian elimination and partial pivoting. Skip a candidate if any pivot is `< 1e-12`. Method names: `planar-mirrored`, `planar-mirrored-xyz`, `planar`, `planar-xyz`.
  - `regions`: key each vertex by `(round(x,4), round(y,4), round(z,4), round(u,5), round(v,5))`. Union all vertices with equal keys and all three vertices of each triangle (union-find).
  - `build_fix`:
    1. The patch is the only shape with a texture basename containing `"ID"` (case-sensitive). Raise `ValueError` if there are zero or several.
    2. For every other shape, find twins: shape vertices within `1e-3` of a patch vertex.
    3. Candidate regions are `(shape, region label)` pairs that own at least one twin. Rank them by (fit succeeds, number of distinct patch vertices twinned, region vertex count), descending. `target_override` (a shape name) restricts candidates to that shape.
    4. **Ambiguity check:** if the chosen region's vertices all have `x >= -1e-3`, or all have `x <= 1e-3`, both mirrored and unmirrored fits succeed on it. If the patch then has any vertex strictly on the other side (`|x| > 1e-3`, opposite sign), raise `ValueError("ambiguous mirroring: ...")`. (Every real stock saucer region spans both sides, so this only fires on a genuinely underdetermined mesh.)
    5. With a fit, UVs are `to_f32(apply_projection(...))` for each patch vertex. Without one, use `method = "seam-copy"` and `max_fit_error = None`: `known` holds the twins' UVs within the chosen region, and `seam_copy` fills the rest.
    6. Weld pairs are `(patch vi, target vi)` where the positions match within `1e-3`, the UVs match within `1e-6` after `to_f32`, and the normals' dot product is `> 0.9999`. Sort by patch vi, and take the lowest target index when several qualify.
    7. `fix = {"format": 1, "source": rel, "generator": "tools/gen_mesh_fixes.py", "merges": [ {patch, target, method, max_fit_error, uvs, weld, normals: None} ]}` with keys in exactly that order.
  - `to_f32(x) = struct.unpack("f", struct.pack("f", x))[0]`.

- [ ] **Step 6: Build and run**

Run: `cmake --build build -j && uv run pytest tests/tools/test_gen_mesh_fixes.py tests/host/test_nif_shapes_binding.py tests/unit/test_path_indirection.py -q`
Expected: all PASS, and the binding test doesn't skip.

- [ ] **Step 7: Commit**

```bash
git branch --show-current
git add native/src/host/host_bindings.cc tools/gen_mesh_fixes.py \
  tests/tools/test_gen_mesh_fixes.py tests/host/test_nif_shapes_binding.py
# plus native/src/assets/include/assets/mesh_fix.h + src/mesh_fix.cc if nif_block_world was exposed
git commit -m "feat(tools): nif_shapes binding and mesh-fix generator core"
```

---

### Task 5: Generate the 10 fix files — ⛔ HUMAN REVIEW CHECKPOINT

**Files:**
- Modify: `tools/gen_mesh_fixes.py` (CLI + review PNGs)
- Create: `native/assets/mesh_fixes/<hash>.json` × up to 10

**Interfaces:**
- Consumes: everything from Task 4.
- `STOCK_MESHES` (game-relative, resolved with `paths.game_asset`; `Nebula.NIF` has an upper-case extension on disk, so the resolver's case handling must find it):
  ```
  data/Models/Ships/Galaxy/Galaxy.nif        data/Models/Ships/Galaxy/GalaxyMed.nif
  data/Models/Ships/Nebula/Nebula.nif        data/Models/Ships/Nebula/NebulaMed.nif
  data/Models/Ships/Sovereign/Sovereign.nif  data/Models/Ships/Sovereign/SovereignMed.nif
  data/Models/Ships/Akira/Akira.nif          data/Models/Ships/Akira/AkiraMed.nif
  data/Models/Ships/Ambassador/Ambassador.nif data/Models/Ships/Ambassador/AmbassadorMed.nif
  ```

- [ ] **Step 1: Add the CLI.** Usage: `uv run python tools/gen_mesh_fixes.py [--only <rel>] [--target <rel>=<shape name>]... [--review-dir DIR] [--write]`. For each mesh:
  1. Resolve it with `paths.game_asset(rel)`.
  2. Hash its bytes, call `nif_shapes`, then `build_fix`.
  3. Print one summary line: `rel  hash  patch→target  method  max_err  uvs=N welds=N`.
  4. Write the review PNG to `--review-dir` (default: a `mesh_fix_review` folder under `tempfile.gettempdir()`, never under `native/assets`).
  5. With `--write`, write `native/assets/mesh_fixes/<hash>.json` using `dumps`.

  **Review PNG:** load the target texture, preferring the project replacement. Resolve `data/Models/Ships/<Ship>/High/<name>` and `data/Models/SharedTextures/FedShips/High/<name>` through `engine.mods.game_override(rel)` first, then `paths.game_asset(rel)`. Scale it to 512 px. Draw the target's triangles in blue and the patch's rebuilt UV triangles in red, with v not flipped. This matches the orientation of the overlays already reviewed in the brainstorm.

- [ ] **Step 2: Dry run (no `--write`)**

Run: `uv run python tools/gen_mesh_fixes.py`
Expected, from the spec's measurements:
- Galaxy, Nebula, Sovereign and Akira High get a `planar*` method with `max_err < 1e-4`.
- Ambassador High gets `seam-copy` or a `planar*` fit.
- The Galaxy High target is `Ent-D Saucer Section:1`, and the Sovereign High target is `top o dish:1`.

**If any High result disagrees with these, STOP and report BLOCKED with the summary lines.** Don't tune thresholds to force agreement.

- [ ] **Step 3: ⛔ STOP — hand the review to the controller.** Report the 10 summary lines and the path to every review PNG. The controller shows them to Mark. **Mark decides:**
  - the Medium-LOD targets, which the controller passes back as `--target` overrides;
  - whether the Akira and Ambassador overlays land on painted hull.

  Don't write fix files before this decision comes back.

- [ ] **Step 4: Write the approved set**

Run: `uv run python tools/gen_mesh_fixes.py --write <approved --target overrides> [--only ... for approved meshes only]`
Then: `ls native/assets/mesh_fixes/` should show exactly the approved count.

- [ ] **Step 5: Record the overrides in the tool.** Put the approved `--target` decisions into a module-level `TARGET_OVERRIDES: dict[str, str]` in `gen_mesh_fixes.py` that the CLI applies by default, and the approved mesh list into `STOCK_MESHES`. Plain `--write` must then reproduce the committed files exactly (Task 6's drift guard depends on this).

- [ ] **Step 6: Commit**

```bash
git branch --show-current
git add tools/gen_mesh_fixes.py native/assets/mesh_fixes/*.json
git commit -m "feat(assets): mesh fixes for the stock Fed hulls (High + Medium LODs)"
```

---

### Task 6: Real-asset proofs, drift guard, warn-once, audit and docs

**Files:**
- Modify: `native/tests/assets/cpu/cache_test.cc` (real Galaxy merge through the cache)
- Create: `tests/tools/test_mesh_fixes_drift.py`
- Modify: `native/src/assets/src/model_build.cc:500-515` (warn once for a no-match)
- Modify: `native/tests/assets/cpu/model_build_test.cc` (warn-once test)
- Modify: `CLAUDE.md` (reference-table row)

**Interfaces:**
- Consumes: the committed fix files (Task 5), `AssetCache::Config::mesh_fix_dir` (Task 3), `tools.gen_mesh_fixes` (Tasks 4–5).

- [ ] **Step 1: Write the failing real-asset test** (append to `cache_test.cc`):

```cpp
TEST(AssetCacheMeshFix, RealGalaxyLosesItsIdPatch) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    const fs::path fixes = fs::path(OPEN_STBC_PROJECT_ROOT) / "native/assets/mesh_fixes";
    ASSERT_TRUE(fs::exists(fixes / (assets::fnv1a64_hex(file_bytes(galaxy_path())) + ".json")))
        << "committed Galaxy fix missing";
    auto cfg = stub_config();
    cfg.keep_cpu_data = true;
    assets::AssetCache plain(cfg);
    cfg.mesh_fix_dir = [fixes] { return fixes; };
    assets::AssetCache fixed(cfg);
    auto a = plain.load(galaxy_path(), fed_high_path());
    auto b = fixed.load(galaxy_path(), fed_high_path());

    // One mesh fewer: the ID patch shape is hidden and skipped.
    EXPECT_EQ(b->meshes.size() + 1, a->meshes.size());
    // No surviving texture was loaded from an "ID" source. Use the model's
    // texture-source bookkeeping if it exposes one; otherwise count materials
    // (the patch's material is gone).
    EXPECT_EQ(b->materials.size() + 1, a->materials.size());
    // Total vertices = old total − welded seam vertices.
    auto verts = [](const assets::Model& m) {
        std::size_t n = 0;
        for (const auto& mesh : m.meshes) if (auto c = mesh.cpu_data()) n += c->vertices.size();
        return n;
    };
    EXPECT_LT(verts(*b), verts(*a));
}
```

Read `assets/mesh.h` for the real `cpu_data()` accessor names before building. Keep the three assertions.

- [ ] **Step 2: Write the drift guard** `tests/tools/test_mesh_fixes_drift.py`:

```python
from pathlib import Path

import pytest

from engine import paths
from tools import gen_mesh_fixes as g

FIX_DIR = Path(__file__).resolve().parents[2] / "native" / "assets" / "mesh_fixes"


def test_committed_fixes_match_generator_output():
    host = pytest.importorskip("_dauntless_host")
    produced = {}
    for rel in g.STOCK_MESHES:
        nif = paths.game_asset(rel)
        if nif is None or not Path(nif).exists():
            pytest.skip("BC content not configured")
        data = Path(nif).read_bytes()
        fix, _ = g.build_fix(host.nif_shapes(str(nif)), rel, g.TARGET_OVERRIDES.get(rel))
        produced[g.fnv1a64_hex(data) + ".json"] = g.dumps(fix)
    committed = {p.name: p.read_text() for p in FIX_DIR.glob("*.json")}
    assert committed == produced
```

- [ ] **Step 3: Write the failing warn-once test.** In `model_build_test.cc`, build the same synthetic model twice with a `TextureReplacement{"ID", "x.tga"}` that matches nothing, capturing stderr with `testing::internal::CaptureStderr()`. The "no texture matching 'ID'" line must appear exactly once across both builds. Use the existing fixture's `make_ctx()` and a minimal file from the helpers already in that test file.

- [ ] **Step 4: Run and watch the new tests fail**

Run: `cmake --build build -j && DAUNTLESS_GAME_DIR="$(uv run python -c 'from engine import paths; print(paths.game_root())')" ./build/native/tests/assets/assets_tests --gtest_filter='AssetCacheMeshFix.RealGalaxy*:*WarnOnce*'`
Expected: the warn-once test FAILS (it warns twice). The Galaxy test should already PASS if Tasks 3 and 5 are right; if it fails, that's a real bug, so report it.

- [ ] **Step 5: Implement warn-once** in `apply_texture_replacements`: a function-local `static std::unordered_set<std::string> warned;` keyed by `model.source.string() + '|' + rep.old_substring`. Print only on first insert.

- [ ] **Step 6: Mesh-index audit.** Run:
  `grep -rn "meshes\[" native/src engine --include='*.cc' --include='*.py' | grep -v "for\|size()"`
  and check whether any **persisted** data (JSON, settings, save files) stores a mesh index. Report the result in the task summary. If something does persist one, report BLOCKED rather than working around it.

- [ ] **Step 7: CLAUDE.md row.** Add to the "Key reference material" table, after the "Collision scuff decals" row:

```
| Hull name-cut fix — ID patches merged at load | `native/src/assets/src/mesh_fix.cc`, `tools/gen_mesh_fixes.py`, `native/assets/mesh_fixes/`, `docs/superpowers/specs/2026-09-28-hull-name-cut-fix-design.md` | BC cuts each Fed hull's registry into a separate "ID" patch shape with its own texture. We merge that patch back into its saucer shape at load, with UVs into the ORIGINAL saucer texture, driven by per-mesh fix files keyed by the NIF's **FNV-1a 64 content hash** (a mod-edited mesh never matches). Applied in `AssetCache::load` before `build_model`; a bad fix warns once and loads unpatched. ⚠️ Consequence: `ReplaceTexture("ID")` now matches nothing on stock Fed hulls, so **they render nameless until the projected-decal follow-up lands** — deliberate. ⚠️ Never hand-edit a fix file: regenerate with `tools/gen_mesh_fixes.py --write`; `tests/tools/test_mesh_fixes_drift.py` fails on any drift. |
```

- [ ] **Step 8: Full gate, in the foreground**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures`, and **no** "NO BC CONTENT ROOT" banner. If the banner appears, re-run with `DAUNTLESS_GAME_DIR` exported explicitly, and report that in the summary.

- [ ] **Step 9: Commit**

```bash
git branch --show-current
git add native/tests/assets/cpu/cache_test.cc tests/tools/test_mesh_fixes_drift.py \
  native/src/assets/src/model_build.cc native/tests/assets/cpu/model_build_test.cc CLAUDE.md
git commit -m "test(assets): real-asset mesh-fix proof, drift guard, ID no-match warns once"
```

---

## After the plan

Live check is **Mark's**: each hull at High and Medium LOD, looking for no seam and no lighting line across the saucer. The Sovereign result decides whether its fix needs a `normals` override. Until then the status is "merged, not live-verified".
