# Bridge Shape Diff — Iteration 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close gaps in DBridge by moving vertices only: export the set to OBJ, diff Mark's Blender edit against an unaltered Blender export, store only the diff (an opaque binary payload in the existing mesh-fix file), and apply it at load.

**Architecture:** The C++ loader gets the full `shape_edits` op (decode + validate + apply, all-or-nothing) inside the existing mesh-fix mechanism, so the payload format is fixed once. The Python side (`tools/shape_diff/` + CLI `tools/bridge_shape_diff.py`) exports OBJ, identifies Blender's vertices against the original NIF, and classifies **moves only** in this iteration — any topology change is refused with a message pointing at iteration 2.

**Tech Stack:** C++20 (`native/src/assets`, nlohmann/json, gtest), pybind11 (`host_bindings.cc`), Python 3.11 stdlib only (struct, base64, json), pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md`

## Global Constraints

- Branch `spike/bridge-shape-diff`, worktree `.claude/worktrees/bridge-shape-diff`. All commands run from the worktree root.
- ⛔ Never run `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit pathspecs only. To mutate a file temporarily: `cp f /tmp/bak` … `cp /tmp/bak f` … `diff f /tmp/bak`.
- ⛔ BC content (OBJ exports, renders) never enters the repo. OBJs live in the session scratchpad `/private/tmp/claude-501/-Users-mward-Documents-Projects-bc-dauntless/2b5bc370-31ee-43b4-89f9-7c639d1efaf4/scratchpad/`.
- ⛔ The payload holds NO original position, UV, colour or triangle — only indices into them plus authored geometry.
- Never spell `game` or `sdk` as a path segment in `tools/`/`tests/`; resolve via `engine.paths` (`paths.game_root()` — stock only, never `game_asset`). Never capture a path at import (no module-level path constants). `tests/unit/test_path_indirection.py` enforces this.
- Fix files resolve to `native/assets/mesh_fixes/<fnv1a64>.json`; stock DBridge NIF is `data/Models/Sets/DBridge/Dbridge.NIF` under `paths.game_root()`.
- Payload magic `"BSD1"`, little-endian, layout exactly as spec §6.1.
- Position match tolerance 1e-4 model units; UV tolerance 1e-5; export weld grid 1/1024.
- OBJ axes: write BC `(x, y, z)` as OBJ `(x, z, -y)`; read OBJ `(x, y, z)` as BC `(x, -z, y)`. OBJ `vt` = `(u, 1 - v)` of NIF UVs.
- Build: `cmake --build build -j` (configured Debug in Task 1). ⛔ Never cmake from `native/`; never change `CMAKE_BUILD_TYPE`.
- Gate before declaring done: `scripts/check_tests.sh`. `tests/known_failures.txt` must stay free of failure entries.
- Ask Mark before launching the game. Launch commands are plain, no `#` comments.

## Review Focus

1. **Blender drops or merges faces on import** (DBridge's `wall inset main` has exact-duplicate triangles; degenerate triangles appear after welding). Expected: identity still succeeds if every *vertex* matches; face-count mismatches are reported, not fatal. → Task 7 test `test_identify_tolerates_missing_duplicate_faces`.
2. **Blender writes vertex colours (`v x y z r g b`) or normals (`vn`) or `s`/`usemtl` lines.** Expected: reader ignores the extras. → Task 6 test `test_read_objects_ignores_colours_normals_and_groups`.
3. **A moved vertex lands on a seam (several original duplicates welded into one OBJ vertex).** Expected: every duplicate moves together. → Task 8 test `test_move_moves_every_welded_duplicate`.
4. **Parent node has a translation** (all DBridge shapes do). Expected: moves are stored in shape-local frame (`inverse(world) · p`), not model space. → Task 8 test `test_move_is_stored_in_shape_local_frame`.
5. **A committed shape-edit fix next to the 5 hull merge fixes** breaks the existing "exactly 5 / one fewer mesh" assertion and the drift guard. Expected: both learn the second kind. → Task 3 (`EveryCommittedFixApplies`) and Task 9 (drift test).

---

## File map

| File | Responsibility |
|---|---|
| `native/src/assets/include/assets/mesh_fix.h` | add `ShapeEdit`, `ShapeEditAddVertex`, `MeshFix::shape_edits`, `base64_decode`, `decode_shape_edits` |
| `native/src/assets/src/mesh_fix.cc` | parse (optional `merges` / `shape_edits`), decode, validate + apply edits |
| `native/tests/assets/cpu/mesh_fix_parse_test.cc` | golden payload decode, parse-level refusals |
| `native/tests/assets/cpu/mesh_fix_shape_edit_test.cc` (new) | apply + refusals on a synthetic `nif::File` |
| `native/tests/assets/CMakeLists.txt` | register the new test file |
| `native/tests/assets/cpu/cache_test.cc` | `EveryCommittedFixApplies` handles both fix kinds |
| `native/src/host/host_bindings.cc` | `nif_shapes` gains `world`, `parent`, `data_block`, `colors`, `uvs1` |
| `tests/host/test_nif_shapes_binding.py` | new-keys test on DBridge |
| `tools/shape_diff/__init__.py` (new) | package marker + `ShapeDiffError` |
| `tools/shape_diff/payload.py` (new) | binary encoder + base64 |
| `tools/shape_diff/frames.py` (new) | axis swaps, 4×4 apply + affine inverse |
| `tools/shape_diff/obj_io.py` (new) | OBJ/MTL writer, OBJ reader |
| `tools/shape_diff/match.py` (new) | identity (base↔NIF), move-only diff |
| `tools/bridge_shape_diff.py` (new) | CLI: `export`, `diff [--write]` |
| `tests/tools/test_shape_diff.py` (new) | payload, frames, obj_io, match, CLI |
| `tests/tools/test_mesh_fixes_drift.py` | only compare files generated by `tools/gen_mesh_fixes.py` |
| `docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md` | iteration log + as-built notes |

---

### Task 1: Worktree runtime setup

**Files:** none committed (`settings.json` is gitignored).

- [ ] **Step 1: Copy settings, sync deps, configure, build**

```bash
cp /Users/mward/Documents/Projects/bc_dauntless/settings.json .
uv sync --extra dev
cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=$PWD/.venv/bin/python3
cmake --build build -j
```

Expected: build succeeds; `ls build/dauntless build/python/_dauntless_host*.so` lists both.

- [ ] **Step 2: Smoke the existing mesh-fix tests**

```bash
uv run pytest tests/tools/test_gen_mesh_fixes.py tests/tools/test_mesh_fixes_drift.py tests/host/test_nif_shapes_binding.py -q
build/native/tests/assets/assets_tests --gtest_filter='MeshFix*:AssetCacheMeshFix*'
```

Expected: all pass (none skipped for content — `settings.json` points at the install). If the gtest binary path differs, find it with `find build -name assets_tests -type f`.

---

### Task 2: C++ — payload decode and fix-file parse

**Files:**
- Modify: `native/src/assets/include/assets/mesh_fix.h`
- Modify: `native/src/assets/src/mesh_fix.cc` (`parse_mesh_fix`, new `base64_decode`, `decode_shape_edits`)
- Test: `native/tests/assets/cpu/mesh_fix_parse_test.cc`

**Interfaces — Produces:**
```cpp
namespace assets {
struct ShapeEditAddVertex {
    std::array<float, 3> pos;     // shape-local
    std::array<float, 2> uv0;
    std::array<float, 2> uv1;     // ignored if the shape has 1 UV set
    std::array<float, 4> color;   // ignored if the shape has no colours
};
struct ShapeEdit {
    std::uint32_t block = 0;
    std::uint16_t orig_vertex_count = 0;
    std::uint16_t orig_triangle_count = 0;
    std::vector<std::pair<std::uint16_t, std::array<float, 3>>> moves;
    std::vector<std::pair<std::uint16_t, std::array<float, 2>>> uvs;
    std::vector<ShapeEditAddVertex> add_vertices;
    std::vector<std::uint16_t> remove_triangles;
    std::vector<std::array<std::uint16_t, 3>> add_triangles;
};
// MeshFix gains:  std::vector<ShapeEdit> shape_edits;
std::optional<std::string> base64_decode(std::string_view text);
std::optional<std::vector<ShapeEdit>> decode_shape_edits(std::string_view bytes, std::string* error);
}
```

Golden payload (shared with Task 5), base64:
`QlNEMQEABwAAAAQAAgABAAEAAQABAAEAAgAAAIA/AAAAQAAAQEAAAAAAgD4AAEA/AAAAPwAAAD8AAAAAzczMPc3MTD6amZk+zczMPgAAgD8AAAA/AACAPgAAgD8BAAAAAgAEAA==`
It encodes one shape: block 7, orig counts 4 / 2; move vertex 2 → (1, 2, 3); uv vertex 0 → (0.25, 0.75); one added vertex pos (0.5, 0.5, 0), uv0 (0.1, 0.2), uv1 (0.3, 0.4), colour (1, 0.5, 0.25, 1); remove triangle 1; add triangle (0, 2, 4). 100 bytes.

- [ ] **Step 1: Write the failing tests** — append to `mesh_fix_parse_test.cc`:

```cpp
namespace {
constexpr const char* kGoldenB64 =
    "QlNEMQEABwAAAAQAAgABAAEAAQABAAEAAgAAAIA/AAAAQAAAQEAAAAAAgD4AAEA/AAAAPwAAAD8"
    "AAAAAzczMPc3MTD6amZk+zczMPgAAgD8AAAA/AACAPgAAgD8BAAAAAgAEAA==";
}

TEST(MeshFixShapeEditDecode, Base64RoundTripsKnownString) {
    auto d = assets::base64_decode("QlNEMQ==");
    ASSERT_TRUE(d.has_value());
    EXPECT_EQ(*d, "BSD1");
    EXPECT_FALSE(assets::base64_decode("Ql*EMQ==").has_value());
    EXPECT_FALSE(assets::base64_decode("QlNEM").has_value());   // bad length
}

TEST(MeshFixShapeEditDecode, DecodesGoldenPayload) {
    auto bytes = assets::base64_decode(kGoldenB64);
    ASSERT_TRUE(bytes.has_value());
    ASSERT_EQ(bytes->size(), 100u);
    std::string err;
    auto edits = assets::decode_shape_edits(*bytes, &err);
    ASSERT_TRUE(edits.has_value()) << err;
    ASSERT_EQ(edits->size(), 1u);
    const auto& e = (*edits)[0];
    EXPECT_EQ(e.block, 7u);
    EXPECT_EQ(e.orig_vertex_count, 4);
    EXPECT_EQ(e.orig_triangle_count, 2);
    ASSERT_EQ(e.moves.size(), 1u);
    EXPECT_EQ(e.moves[0].first, 2);
    EXPECT_FLOAT_EQ(e.moves[0].second[2], 3.0f);
    ASSERT_EQ(e.uvs.size(), 1u);
    EXPECT_FLOAT_EQ(e.uvs[0].second[1], 0.75f);
    ASSERT_EQ(e.add_vertices.size(), 1u);
    EXPECT_FLOAT_EQ(e.add_vertices[0].uv1[1], 0.4f);
    EXPECT_FLOAT_EQ(e.add_vertices[0].color[2], 0.25f);
    ASSERT_EQ(e.remove_triangles.size(), 1u);
    EXPECT_EQ(e.remove_triangles[0], 1);
    ASSERT_EQ(e.add_triangles.size(), 1u);
    EXPECT_EQ(e.add_triangles[0][2], 4);
}

TEST(MeshFixShapeEditDecode, RefusesBadMagicTruncationAndTrailingBytes) {
    auto good = *assets::base64_decode(kGoldenB64);
    std::string err;
    { auto b = good; b[0] = 'X';
      EXPECT_FALSE(assets::decode_shape_edits(b, &err).has_value()); }
    { auto b = good.substr(0, good.size() - 1);
      EXPECT_FALSE(assets::decode_shape_edits(b, &err).has_value()); }
    { auto b = good + "x";
      EXPECT_FALSE(assets::decode_shape_edits(b, &err).has_value()); }
}

TEST(MeshFixShapeEditParse, ShapeEditsOnlyFileParses) {
    std::string text = std::string(R"({"format":1,"shape_edits":")") + kGoldenB64 + "\"}";
    std::string err;
    auto fix = assets::parse_mesh_fix(text, &err);
    ASSERT_TRUE(fix.has_value()) << err;
    EXPECT_TRUE(fix->merges.empty());
    EXPECT_EQ(fix->shape_edits.size(), 1u);
}

TEST(MeshFixShapeEditParse, RefusesFileWithNeitherOp) {
    std::string err;
    EXPECT_FALSE(assets::parse_mesh_fix(R"({"format":1})", &err).has_value());
    EXPECT_FALSE(assets::parse_mesh_fix(
        R"({"format":1,"shape_edits":"!!!!"})", &err).has_value());
}
```

- [ ] **Step 2: Run to verify failure**

Run: `cmake --build build -j --target assets_tests`
Expected: compile error — `base64_decode` / `decode_shape_edits` / `shape_edits` not declared.

- [ ] **Step 3: Implement**

In `mesh_fix.h`, add the two structs above `struct MeshFix`, add `std::vector<ShapeEdit> shape_edits;` to `MeshFix`, and declare `base64_decode` and `decode_shape_edits` after `parse_mesh_fix`, with comments:

```cpp
// Standard base64 (RFC 4648, '=' padding, no whitespace). nullopt on any
// illegal character or a length that is not a multiple of 4.
std::optional<std::string> base64_decode(std::string_view text);

// Decode a "BSD1" shape-edit payload (spec 2026-10-09-bridge-shape-diff
// §6.1). Structural checks only -- range checks against a NIF happen in
// apply_mesh_fix. Refuses bad magic, truncation and trailing bytes.
std::optional<std::vector<ShapeEdit>> decode_shape_edits(std::string_view bytes,
                                                         std::string* error);
```

Also update the header's top comment: a fix file now carries `merges`, `shape_edits`, or both.

In `mesh_fix.cc` add (needs `#include <bit>` and `#include <cstring>`):

```cpp
std::optional<std::string> base64_decode(std::string_view text) {
    if (text.size() % 4 != 0) return std::nullopt;
    auto val = [](char c) -> int {
        if (c >= 'A' && c <= 'Z') return c - 'A';
        if (c >= 'a' && c <= 'z') return c - 'a' + 26;
        if (c >= '0' && c <= '9') return c - '0' + 52;
        if (c == '+') return 62;
        if (c == '/') return 63;
        return -1;
    };
    std::string out;
    out.reserve(text.size() / 4 * 3);
    for (std::size_t i = 0; i < text.size(); i += 4) {
        int v[4];
        int pad = 0;
        for (int k = 0; k < 4; ++k) {
            const char c = text[i + k];
            if (c == '=' && i + 4 == text.size() && k >= 2) { v[k] = 0; ++pad; continue; }
            if (pad) return std::nullopt;            // data after padding
            v[k] = val(c);
            if (v[k] < 0) return std::nullopt;
        }
        const std::uint32_t n = (v[0] << 18) | (v[1] << 12) | (v[2] << 6) | v[3];
        out.push_back(static_cast<char>((n >> 16) & 0xFF));
        if (pad < 2) out.push_back(static_cast<char>((n >> 8) & 0xFF));
        if (pad < 1) out.push_back(static_cast<char>(n & 0xFF));
    }
    return out;
}

namespace {
static_assert(std::endian::native == std::endian::little,
              "shape-edit payload decoder assumes a little-endian host");

/// Bounds-checked little-endian reader over the payload bytes.
struct PayloadReader {
    std::string_view s;
    std::size_t pos = 0;
    bool ok = true;
    template <class T> T get() {
        T v{};
        if (!ok || pos + sizeof(T) > s.size()) { ok = false; return v; }
        std::memcpy(&v, s.data() + pos, sizeof(T));
        pos += sizeof(T);
        return v;
    }
};
}  // namespace

std::optional<std::vector<ShapeEdit>> decode_shape_edits(std::string_view bytes,
                                                         std::string* error) {
    auto fail = [&](std::string msg) -> std::optional<std::vector<ShapeEdit>> {
        if (error) *error = std::move(msg);
        return std::nullopt;
    };
    if (bytes.size() < 4 || bytes.substr(0, 4) != "BSD1")
        return fail("shape_edits: bad magic");
    PayloadReader r{bytes, 4};
    const auto shape_count = r.get<std::uint16_t>();
    std::vector<ShapeEdit> out;
    for (std::uint16_t s = 0; s < shape_count && r.ok; ++s) {
        ShapeEdit e;
        e.block = r.get<std::uint32_t>();
        e.orig_vertex_count = r.get<std::uint16_t>();
        e.orig_triangle_count = r.get<std::uint16_t>();
        const auto n_move = r.get<std::uint16_t>();
        const auto n_uv = r.get<std::uint16_t>();
        const auto n_addv = r.get<std::uint16_t>();
        const auto n_remt = r.get<std::uint16_t>();
        const auto n_addt = r.get<std::uint16_t>();
        for (int i = 0; i < n_move && r.ok; ++i) {
            const auto idx = r.get<std::uint16_t>();
            std::array<float, 3> p{r.get<float>(), r.get<float>(), r.get<float>()};
            e.moves.emplace_back(idx, p);
        }
        for (int i = 0; i < n_uv && r.ok; ++i) {
            const auto idx = r.get<std::uint16_t>();
            std::array<float, 2> uv{r.get<float>(), r.get<float>()};
            e.uvs.emplace_back(idx, uv);
        }
        for (int i = 0; i < n_addv && r.ok; ++i) {
            ShapeEditAddVertex v;
            for (auto& c : v.pos) c = r.get<float>();
            for (auto& c : v.uv0) c = r.get<float>();
            for (auto& c : v.uv1) c = r.get<float>();
            for (auto& c : v.color) c = r.get<float>();
            e.add_vertices.push_back(v);
        }
        for (int i = 0; i < n_remt && r.ok; ++i) e.remove_triangles.push_back(r.get<std::uint16_t>());
        for (int i = 0; i < n_addt && r.ok; ++i)
            e.add_triangles.push_back({r.get<std::uint16_t>(), r.get<std::uint16_t>(),
                                       r.get<std::uint16_t>()});
        out.push_back(std::move(e));
    }
    if (!r.ok) return fail("shape_edits: payload truncated");
    if (r.pos != bytes.size()) return fail("shape_edits: trailing bytes after payload");
    return out;
}
```

NOTE: the brace-init `{r.get<float>(), r.get<float>(), ...}` evaluates left-to-right (braced-init-list sequencing is guaranteed), so field order is safe.

Replace the `merges` loop in `parse_mesh_fix` so both keys are optional but at least one is required:

```cpp
        const bool has_merges = j.contains("merges");
        const bool has_edits = j.contains("shape_edits");
        if (!has_merges && !has_edits)
            return fail("mesh fix has neither \"merges\" nor \"shape_edits\"");
        if (has_merges) {
            for (const auto& jm : j.at("merges")) {
                // ... existing merge body unchanged ...
            }
        }
        if (has_edits) {
            auto bytes = base64_decode(j.at("shape_edits").get<std::string>());
            if (!bytes) return fail("shape_edits: invalid base64");
            std::string err;
            auto edits = decode_shape_edits(*bytes, &err);
            if (!edits) return fail(err);
            fix.shape_edits = std::move(*edits);
        }
```

- [ ] **Step 4: Run tests**

Run: `cmake --build build -j --target assets_tests && build/native/tests/assets/assets_tests --gtest_filter='MeshFix*'`
Expected: all `MeshFix*` pass, including the 5 new ones and every pre-existing parse/apply test.

- [ ] **Step 5: Commit**

```bash
git add native/src/assets/include/assets/mesh_fix.h native/src/assets/src/mesh_fix.cc native/tests/assets/cpu/mesh_fix_parse_test.cc
git commit -m "feat(mesh_fix): decode BSD1 shape-edit payloads; merges now optional"
```

---

### Task 3: C++ — validate and apply shape edits

**Files:**
- Modify: `native/src/assets/src/mesh_fix.cc` (`apply_mesh_fix` + new `validate_edit` / `apply_edit`)
- Create: `native/tests/assets/cpu/mesh_fix_shape_edit_test.cc`
- Modify: `native/tests/assets/CMakeLists.txt` (add `cpu/mesh_fix_shape_edit_test.cc` after `cpu/mesh_fix_apply_test.cc`)
- Modify: `native/tests/assets/cpu/cache_test.cc` (`EveryCommittedFixApplies`)

**Interfaces:** Consumes Task 2's `ShapeEdit` / `MeshFix::shape_edits`. `apply_mesh_fix` signature unchanged; it now validates merges, then edits, then cross-checks, then applies merges, then edits.

Apply semantics (spec §6.1, §7):
- moves overwrite `vertices[i]`; uvs overwrite `uv_sets[0][i]`;
- added vertex k gets index `orig_vertex_count + k`; appended to `vertices`, `uv_sets[0]`, `uv_sets[1]` if the shape has ≥2 UV sets (any further sets get a copy of uv1), `vertex_colors` if `has_vertex_colors`;
- final triangles = original triangles not removed, in original order, then added triangles;
- update `num_vertices`, `num_triangles`, `num_triangle_points`; clear match groups; recompute `bound_center` (AABB centre) and `bound_radius` (max distance from it).

- [ ] **Step 1: Write the failing tests** — create `mesh_fix_shape_edit_test.cc`:

```cpp
// Tests for apply_mesh_fix's shape_edits op (spec:
// docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md §6-§7).
#include <gtest/gtest.h>
#include <assets/mesh_fix.h>
#include <nif/file.h>

namespace {
// Root NiNode (id 1) with one NiTriShape (id 2, data id 3): a unit quad,
// no normals, vertex colours, two UV sets -- the DBridge shape profile.
struct Synthetic { nif::File f; };

nif::NiTriShapeData quad() {
    nif::NiTriShapeData d;
    d.num_vertices = 4;
    d.has_vertices = d.has_uv = true;
    d.has_normals = false;
    d.vertices = {{0,0,0},{1,0,0},{1,1,0},{0,1,0}};
    d.has_vertex_colors = true;
    d.vertex_colors = {{1,1,1,1},{1,1,1,1},{1,1,1,1},{1,1,1,1}};
    d.uv_sets = {{{0,0},{1,0},{1,1},{0,1}}, {{0,0},{1,0},{1,1},{0,1}}};
    d.num_triangles = 2; d.num_triangle_points = 6;
    d.triangles = {{0,1,2},{0,2,3}};
    d.num_match_groups = 1; d.match_groups = {{0,1}};
    return d;
}

Synthetic make() {
    Synthetic s;
    nif::NiNode root; root.av.obj.name = "root"; root.child_links = {2};
    nif::NiTriShape shape; shape.data_link = 3;
    s.f.blocks = {root, shape, quad()};
    s.f.block_ids = {1, 2, 3};
    s.f.root = nif::BlockHandle{&s.f.blocks.front()};
    return s;
}

const nif::NiTriShapeData& data(const Synthetic& s) {
    return std::get<nif::NiTriShapeData>(s.f.blocks[2]);
}

assets::ShapeEdit base_edit() {
    assets::ShapeEdit e;
    e.block = 1; e.orig_vertex_count = 4; e.orig_triangle_count = 2;
    return e;
}

assets::MeshFix fix_of(assets::ShapeEdit e) {
    assets::MeshFix f; f.shape_edits = {e}; return f;
}
}  // namespace

TEST(MeshFixShapeEdit, MoveOnlyChangesPositionsAndNothingElse) {
    auto s = make();
    auto e = base_edit();
    e.moves = {{2, {1.5f, 1.25f, 0.5f}}};
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    const auto& d = data(s);
    EXPECT_FLOAT_EQ(d.vertices[2].x, 1.5f);
    EXPECT_FLOAT_EQ(d.vertices[2].z, 0.5f);
    EXPECT_EQ(d.num_vertices, 4);
    EXPECT_EQ(d.num_triangles, 2);
    EXPECT_EQ(d.triangles[1][2], 3);
    EXPECT_FLOAT_EQ(d.uv_sets[0][2].u, 1.0f);
    EXPECT_FALSE(d.has_normals);
    EXPECT_TRUE(d.match_groups.empty());
    EXPECT_EQ(d.num_match_groups, 0);
}

TEST(MeshFixShapeEdit, AddsVerticesTrianglesAndRemovesInOrder) {
    auto s = make();
    auto e = base_edit();
    e.uvs = {{0, {0.25f, 0.75f}}};
    e.add_vertices = {{{0.5f, 0.5f, 1.0f}, {0.1f, 0.2f}, {0.3f, 0.4f}, {1.0f, 0.5f, 0.25f, 1.0f}}};
    e.remove_triangles = {0};
    e.add_triangles = {{0, 1, 4}};
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    const auto& d = data(s);
    EXPECT_EQ(d.num_vertices, 5);
    ASSERT_EQ(d.vertices.size(), 5u);
    ASSERT_EQ(d.uv_sets[0].size(), 5u);
    ASSERT_EQ(d.uv_sets[1].size(), 5u);
    ASSERT_EQ(d.vertex_colors.size(), 5u);
    EXPECT_FLOAT_EQ(d.uv_sets[0][0].u, 0.25f);
    EXPECT_FLOAT_EQ(d.uv_sets[1][4].v, 0.4f);
    EXPECT_FLOAT_EQ(d.vertex_colors[4].g, 0.5f);
    ASSERT_EQ(d.num_triangles, 2);
    EXPECT_EQ(d.num_triangle_points, 6u);
    EXPECT_EQ(d.triangles[0], (std::array<std::uint16_t, 3>{0, 2, 3}));   // survivor first
    EXPECT_EQ(d.triangles[1], (std::array<std::uint16_t, 3>{0, 1, 4}));   // then added
    EXPECT_NEAR(d.bound_center.z, 0.5f, 1e-6);                            // AABB z 0..1
}

TEST(MeshFixShapeEdit, NoColoursAndOneUvSetIgnoresThoseFields) {
    auto s = make();
    auto& d0 = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
    d0.has_vertex_colors = false; d0.vertex_colors.clear();
    d0.uv_sets.resize(1);
    auto e = base_edit();
    e.add_vertices = {{{0.5f, 0.5f, 1.0f}, {0.1f, 0.2f}, {0.3f, 0.4f}, {1, 1, 1, 1}}};
    e.add_triangles = {{0, 1, 4}};
    ASSERT_EQ(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    EXPECT_TRUE(data(s).vertex_colors.empty());
    EXPECT_EQ(data(s).uv_sets.size(), 1u);
    EXPECT_EQ(data(s).uv_sets[0].size(), 5u);
}

namespace {
void expect_refused(assets::MeshFix fix, const char* why,
                    void (*mutate)(Synthetic&) = nullptr) {
    auto s = make();
    if (mutate) mutate(s);
    const auto before = data(s).vertices;
    const auto before_tris = data(s).triangles;
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix), "") << why;
    EXPECT_EQ(data(s).vertices.size(), before.size()) << why;
    EXPECT_FLOAT_EQ(data(s).vertices[2].x, before[2].x) << why;
    EXPECT_EQ(data(s).triangles, before_tris) << why;
    EXPECT_EQ(data(s).match_groups.size(), 1u) << why;
}
}  // namespace

TEST(MeshFixShapeEdit, RefusalsLeaveFileUntouched) {
    auto ok = base_edit();
    ok.moves = {{2, {9, 9, 9}}};
    { auto e = ok; e.block = 99;                   expect_refused(fix_of(e), "block out of range"); }
    { auto e = ok; e.block = 0;                    expect_refused(fix_of(e), "not a trishape"); }
    { auto e = ok; e.orig_vertex_count = 5;        expect_refused(fix_of(e), "vertex count mismatch"); }
    { auto e = ok; e.orig_triangle_count = 3;      expect_refused(fix_of(e), "triangle count mismatch"); }
    { auto e = ok; e.moves.push_back({4, {0,0,0}}); expect_refused(fix_of(e), "move out of range"); }
    { auto e = ok; e.uvs = {{7, {0,0}}};           expect_refused(fix_of(e), "uv out of range"); }
    { auto e = ok; e.remove_triangles = {2};       expect_refused(fix_of(e), "remove out of range"); }
    { auto e = ok; e.remove_triangles = {1, 1};    expect_refused(fix_of(e), "removed twice"); }
    { auto e = ok; e.add_triangles = {{0, 1, 4}};  expect_refused(fix_of(e), "add index out of range"); }
    { auto e = ok; e.add_triangles = {{0, 1, 1}};  expect_refused(fix_of(e), "repeated index"); }
    { auto e = base_edit();
      e.add_vertices = {{{2, 0, 0}, {0,0}, {0,0}, {1,1,1,1}}};
      e.add_triangles = {{0, 1, 4}};               expect_refused(fix_of(e), "zero area (collinear)"); }
    { auto f = fix_of(ok); f.shape_edits.push_back(ok);
                                                   expect_refused(f, "same block twice"); }
    expect_refused(fix_of(ok), "authored normals", [](Synthetic& s) {
        auto& d = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
        d.has_normals = true;
        d.normals.assign(4, {0, 0, 1});
    });
}

TEST(MeshFixShapeEdit, RefusesVertexOverflow) {
    auto s = make();
    auto& d = std::get<nif::NiTriShapeData>(s.f.blocks[2]);
    d.num_vertices = 65535;
    d.vertices.resize(65535, {5, 5, 5});
    d.vertex_colors.resize(65535, {1, 1, 1, 1});
    d.uv_sets[0].resize(65535, {0, 0});
    d.uv_sets[1].resize(65535, {0, 0});
    auto e = base_edit();
    e.orig_vertex_count = 65535;
    e.add_vertices = {{{0, 0, 1}, {0,0}, {0,0}, {1,1,1,1}}};
    EXPECT_NE(assets::apply_mesh_fix(s.f, fix_of(e)), "");
    EXPECT_EQ(data(s).vertices.size(), 65535u);
}
```

Note the "zero area (collinear)" case: vertices 0 (0,0,0), 1 (1,0,0) and the added (2,0,0) are collinear.

- [ ] **Step 2: Register the test file and verify failure**

Add `cpu/mesh_fix_shape_edit_test.cc` to `native/tests/assets/CMakeLists.txt` directly after `cpu/mesh_fix_apply_test.cc`.

Run: `cmake --build build -j --target assets_tests && build/native/tests/assets/assets_tests --gtest_filter='MeshFixShapeEdit*'`
Expected: tests compile and FAIL (edits are parsed but never applied: positions unchanged, refusals return "").

- [ ] **Step 3: Implement** — in `mesh_fix.cc`, inside the anonymous namespace after `apply_merge`:

```cpp
/// One shape edit, validated: the data block it mutates.
struct EditPlan {
    std::size_t data_idx = 0;
};

/// Validate edit `e` (index `edit_idx`) against the UNMODIFIED file. Returns
/// "" and fills `*plan`, else the refusal reason ("shape edit N: ...").
std::string validate_edit(const nif::File& file, const ShapeEdit& e,
                          std::size_t edit_idx, EditPlan* plan) {
    const std::string prefix = "shape edit " + std::to_string(edit_idx) + ": ";
    if (e.block >= file.blocks.size()) return prefix + "block out of range";
    const auto* shape = std::get_if<nif::NiTriShape>(&file.blocks[e.block]);
    if (!shape) return prefix + "block is not a NiTriShape";
    const std::size_t data_idx = index_of(file, shape->data_link);
    if (data_idx == kNoIndex || data_idx >= file.blocks.size())
        return prefix + "data_link unresolved";
    const auto* d = std::get_if<nif::NiTriShapeData>(&file.blocks[data_idx]);
    if (!d) return prefix + "data_link does not point at NiTriShapeData";
    if (d->has_normals) return prefix + "shape has authored normals (unsupported)";
    if (!d->has_vertices || d->vertices.size() != d->num_vertices)
        return prefix + "shape vertex array inconsistent";
    if (d->uv_sets.empty()) return prefix + "shape has no UV set";
    if (d->num_vertices != e.orig_vertex_count)
        return prefix + "original vertex count mismatch";
    if (d->num_triangles != e.orig_triangle_count ||
        d->triangles.size() != d->num_triangles)
        return prefix + "original triangle count mismatch";

    const std::size_t final_v = std::size_t{e.orig_vertex_count} + e.add_vertices.size();
    if (final_v > 65535) return prefix + "final vertex count exceeds 65535";
    for (const auto& [i, p] : e.moves)
        if (i >= e.orig_vertex_count) return prefix + "move index out of range";
    for (const auto& [i, uv] : e.uvs)
        if (i >= e.orig_vertex_count) return prefix + "uv index out of range";

    std::vector<bool> removed(e.orig_triangle_count, false);
    for (std::uint16_t t : e.remove_triangles) {
        if (t >= e.orig_triangle_count) return prefix + "removed triangle out of range";
        if (removed[t]) return prefix + "triangle removed twice";
        removed[t] = true;
    }
    const std::size_t final_t =
        std::size_t{e.orig_triangle_count} - e.remove_triangles.size() + e.add_triangles.size();
    if (final_t > 65535) return prefix + "final triangle count exceeds 65535";

    // Final positions, for the degenerate-triangle check.
    std::vector<glm::vec3> pos;
    pos.reserve(final_v);
    for (const auto& v : d->vertices) pos.emplace_back(v.x, v.y, v.z);
    for (const auto& [i, p] : e.moves) pos[i] = glm::vec3(p[0], p[1], p[2]);
    for (const auto& av : e.add_vertices) pos.emplace_back(av.pos[0], av.pos[1], av.pos[2]);
    for (const auto& t : e.add_triangles) {
        if (t[0] >= final_v || t[1] >= final_v || t[2] >= final_v)
            return prefix + "added triangle index out of range";
        if (t[0] == t[1] || t[1] == t[2] || t[0] == t[2])
            return prefix + "added triangle repeats an index";
        const glm::vec3 n = glm::cross(pos[t[1]] - pos[t[0]], pos[t[2]] - pos[t[0]]);
        if (glm::length(n) <= 1e-10f) return prefix + "added triangle has zero area";
    }
    plan->data_idx = data_idx;
    return "";
}

void apply_edit(nif::File& file, const ShapeEdit& e, const EditPlan& plan) {
    auto& d = std::get<nif::NiTriShapeData>(file.blocks[plan.data_idx]);
    for (const auto& [i, p] : e.moves) d.vertices[i] = {p[0], p[1], p[2]};
    for (const auto& [i, uv] : e.uvs) d.uv_sets[0][i] = {uv[0], uv[1]};
    for (const auto& av : e.add_vertices) {
        d.vertices.push_back({av.pos[0], av.pos[1], av.pos[2]});
        d.uv_sets[0].push_back({av.uv0[0], av.uv0[1]});
        for (std::size_t s = 1; s < d.uv_sets.size(); ++s)
            d.uv_sets[s].push_back({av.uv1[0], av.uv1[1]});
        if (d.has_vertex_colors)
            d.vertex_colors.push_back({av.color[0], av.color[1], av.color[2], av.color[3]});
    }
    std::vector<bool> removed(d.triangles.size(), false);
    for (std::uint16_t t : e.remove_triangles) removed[t] = true;
    std::vector<std::array<std::uint16_t, 3>> tris;
    tris.reserve(d.triangles.size() - e.remove_triangles.size() + e.add_triangles.size());
    for (std::size_t t = 0; t < d.triangles.size(); ++t)
        if (!removed[t]) tris.push_back(d.triangles[t]);
    for (const auto& t : e.add_triangles) tris.push_back(t);
    d.triangles = std::move(tris);

    d.num_vertices = static_cast<std::uint16_t>(d.vertices.size());
    d.num_triangles = static_cast<std::uint16_t>(d.triangles.size());
    d.num_triangle_points = static_cast<std::uint32_t>(d.triangles.size()) * 3;
    d.num_match_groups = 0;
    d.match_groups.clear();

    glm::vec3 lo(std::numeric_limits<float>::max()), hi(-std::numeric_limits<float>::max());
    for (const auto& v : d.vertices) {
        lo = glm::min(lo, glm::vec3(v.x, v.y, v.z));
        hi = glm::max(hi, glm::vec3(v.x, v.y, v.z));
    }
    const glm::vec3 c = (lo + hi) * 0.5f;
    float r = 0.0f;
    for (const auto& v : d.vertices) r = std::max(r, glm::length(glm::vec3(v.x, v.y, v.z) - c));
    d.bound_center = {c.x, c.y, c.z};
    d.bound_radius = r;
}
```

(Add `#include <algorithm>` for `std::max`.) Then in `apply_mesh_fix`, after the merge cross-check loop and before the merge apply loop:

```cpp
    std::vector<EditPlan> edit_plans(fix.shape_edits.size());
    for (std::size_t i = 0; i < fix.shape_edits.size(); ++i) {
        std::string err = validate_edit(file, fix.shape_edits[i], i, &edit_plans[i]);
        if (!err.empty()) return err;
        // A data block may be edited once, and never by a merge too.
        auto [it, inserted] = data_block_owner.try_emplace(edit_plans[i].data_idx,
                                                           plans.size() + i);
        if (!inserted) {
            return "shape edit " + std::to_string(i) + ": data block " +
                   std::to_string(edit_plans[i].data_idx) +
                   " is already used by another merge or shape edit";
        }
    }
```

and after the merge apply loop:

```cpp
    for (std::size_t i = 0; i < fix.shape_edits.size(); ++i)
        apply_edit(file, fix.shape_edits[i], edit_plans[i]);
```

Update the `apply_mesh_fix` doc comment in the header: "Apply every merge and shape edit in `fix` to `file`, or none of them."

- [ ] **Step 4: Generalise `EveryCommittedFixApplies`** in `native/tests/assets/cpu/cache_test.cc`:
  - Replace `ASSERT_EQ(fix_files.size(), 5u) ...` with a count, made after parsing, of files whose fix has non-empty `merges`: `EXPECT_EQ(merge_fixes, 5u) << "expected exactly 5 committed hull merge fixes (High LOD only)";` (declare `std::size_t merge_fixes = 0;` before the loop; increment when `!fix->merges.empty()`; assert after the loop).
  - Replace the mesh-count assertion with:

```cpp
        const std::size_t hidden = fix->merges.size();   // one hidden patch per merge
        EXPECT_EQ(b->meshes.size() + hidden, a->meshes.size())
            << "fixed model should lose exactly one mesh per merge (the hidden patch)";
```
  - The `search` paths: keep `{nif_path.parent_path() / "High", fed_high_path()}` — DBridge textures are in `DBridge/High`, so it already resolves.

- [ ] **Step 5: Run tests**

Run: `cmake --build build -j --target assets_tests && build/native/tests/assets/assets_tests --gtest_filter='MeshFix*:AssetCacheMeshFix*'`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add native/src/assets/src/mesh_fix.cc native/src/assets/include/assets/mesh_fix.h native/tests/assets/cpu/mesh_fix_shape_edit_test.cc native/tests/assets/CMakeLists.txt native/tests/assets/cpu/cache_test.cc
git commit -m "feat(mesh_fix): apply shape edits (moves, uvs, added verts/tris, removals), all-or-nothing"
```

---

### Task 4: `nif_shapes` returns frame, parent, colours and UV set 1

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`nif_shapes_impl`, its `m.def` docstring)
- Test: `tests/host/test_nif_shapes_binding.py`

**Interfaces — Produces** (new keys on every shape dict; existing keys unchanged):
- `world`: list of 16 floats, column-major, data frame → model (`assets::nif_block_world(f, i)`)
- `parent`: str, name of the parent `NiNode` ("" if none)
- `data_block`: int, block index of its `NiTriShapeData` (-1 if unresolved)
- `colors`: list of `(r, g, b, a)` per vertex, or `[]`
- `uvs1`: list of `(u, v)` (UV set 1), or `[]`

- [ ] **Step 1: Write the failing test** — append to `tests/host/test_nif_shapes_binding.py`:

```python
def test_dbridge_shapes_carry_frame_parent_colours_and_uv1():
    nif = paths.game_root() / "data/Models/Sets/DBridge/Dbridge.NIF"
    if not nif.exists():
        pytest.skip("BC content not configured")
    shapes = _host().nif_shapes(str(nif))
    assert len(shapes) == 145
    by_block = {s["block"]: s for s in shapes}
    walls = by_block[468]
    assert walls["parent"] == "Material: D walls 1"
    assert walls["data_block"] >= 0
    w = walls["world"]
    assert len(w) == 16 and w[15] == 1.0
    assert sum(1 for s in shapes if s["colors"]) == 123
    assert sum(1 for s in shapes if s["uvs1"]) == 17
    for s in shapes:
        n = len(s["vertices"])
        assert len(s["colors"]) in (0, n)
        assert len(s["uvs1"]) in (0, n)
        assert all(len(c) == 4 for c in s["colors"])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/host/test_nif_shapes_binding.py -q`
Expected: FAIL with `KeyError: 'parent'`.

- [ ] **Step 3: Implement** — in `nif_shapes_impl`, inside the per-shape loop:

```cpp
        // Parent NiNode name (label only; identity is the block index).
        std::string parent_name;
        for (std::size_t p = 0; p < f.blocks.size() && parent_name.empty(); ++p) {
            const auto* node = std::get_if<nif::NiNode>(&f.blocks[p]);
            if (!node) continue;
            for (std::uint32_t link : node->child_links)
                if (nif_shapes_index_of(f, link) == i) { parent_name = node->av.obj.name; break; }
        }
        d["parent"] = parent_name;
        d["data_block"] = (data_idx != std::string::npos && data_idx < f.blocks.size())
                              ? static_cast<int>(data_idx) : -1;
        {
            const glm::mat4 w = assets::nif_block_world(f, i);
            py::list wl;
            for (int c = 0; c < 4; ++c)
                for (int r = 0; r < 4; ++r) wl.append(w[c][r]);
            d["world"] = wl;
        }
```

(place after `data_idx` is computed), and inside the `if (data)` block:

```cpp
            if (data->has_vertex_colors) {
                for (const auto& c : data->vertex_colors)
                    colors.append(py::make_tuple(c.r, c.g, c.b, c.a));
            }
            if (data->uv_sets.size() >= 2) {
                for (const auto& uv : data->uv_sets[1]) uvs1.append(py::make_tuple(uv.u, uv.v));
            }
```

declaring `py::list colors, uvs1;` next to `vertices, normals, ...` and setting `d["colors"] = colors; d["uvs1"] = uvs1;` next to the other assignments. Append to the `m.def("nif_shapes", ...)` docstring: `"Also: world (16 floats, column-major, data frame -> model), parent node name, data_block, per-vertex colors (or []), UV set 1 (or [])."`

- [ ] **Step 4: Rebuild and run**

Run: `cmake --build build -j && uv run pytest tests/host/test_nif_shapes_binding.py tests/tools/test_gen_mesh_fixes.py tests/tools/test_mesh_fixes_drift.py -q`
Expected: all pass. If `walls["parent"]` is not `"Material: D walls 1"`, STOP and report — the agent-measured tree (`[463] 'walls' → [465] 'Material: D walls 1' → [468]`) would be wrong.

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc tests/host/test_nif_shapes_binding.py
git commit -m "feat(host): nif_shapes reports world matrix, parent, data block, colours, UV set 1"
```

---

### Task 5: Python payload encoder and frame helpers

**Files:**
- Create: `tools/shape_diff/__init__.py`, `tools/shape_diff/payload.py`, `tools/shape_diff/frames.py`
- Create: `tests/tools/test_shape_diff.py`

**Interfaces — Produces:**
```python
# tools/shape_diff/__init__.py
class ShapeDiffError(Exception): ...

# tools/shape_diff/payload.py
def encode(edits: list[dict]) -> bytes
def encode_b64(edits: list[dict]) -> str
# edit dict keys: block:int, orig_vertex_count:int, orig_triangle_count:int,
#   moves:[(int,(x,y,z))], uvs:[(int,(u,v))],
#   add_vertices:[{"pos":(x,y,z),"uv0":(u,v),"uv1":(u,v),"color":(r,g,b,a)}],
#   remove_triangles:[int], add_triangles:[(a,b,c)]   (missing lists = empty)

# tools/shape_diff/frames.py
def bc_to_obj(p) -> tuple      # (x, z, -y)
def obj_to_bc(p) -> tuple      # (x, -z, y)
def apply(m16, p) -> tuple     # column-major 4x4 * (p, 1)
def affine_inverse(m16) -> list[float]   # inverse of an affine column-major 4x4
```

- [ ] **Step 1: Write the failing tests** — create `tests/tools/test_shape_diff.py`:

```python
import base64

import pytest

from tools.shape_diff import ShapeDiffError, frames, payload

GOLDEN_B64 = (
    "QlNEMQEABwAAAAQAAgABAAEAAQABAAEAAgAAAIA/AAAAQAAAQEAAAAAAgD4AAEA/AAAAPwAAAD8"
    "AAAAAzczMPc3MTD6amZk+zczMPgAAgD8AAAA/AACAPgAAgD8BAAAAAgAEAA=="
)

GOLDEN_EDIT = {
    "block": 7, "orig_vertex_count": 4, "orig_triangle_count": 2,
    "moves": [(2, (1.0, 2.0, 3.0))],
    "uvs": [(0, (0.25, 0.75))],
    "add_vertices": [{"pos": (0.5, 0.5, 0.0), "uv0": (0.1, 0.2),
                      "uv1": (0.3, 0.4), "color": (1.0, 0.5, 0.25, 1.0)}],
    "remove_triangles": [1],
    "add_triangles": [(0, 2, 4)],
}


def test_payload_matches_cpp_golden():
    assert payload.encode_b64([GOLDEN_EDIT]) == GOLDEN_B64
    assert len(base64.b64decode(GOLDEN_B64)) == 100


def test_payload_missing_lists_are_empty():
    raw = payload.encode([{"block": 1, "orig_vertex_count": 3, "orig_triangle_count": 1}])
    assert raw == b"BSD1" + bytes([1, 0, 1, 0, 0, 0, 3, 0, 1, 0]) + bytes(10)


def test_payload_refuses_index_overflow():
    with pytest.raises(ShapeDiffError):
        payload.encode([{"block": 1, "orig_vertex_count": 70000, "orig_triangle_count": 1}])


def test_axis_swap_round_trips():
    p = (1.5, -2.25, 3.125)
    assert frames.bc_to_obj(p) == (1.5, 3.125, 2.25)
    assert frames.obj_to_bc(frames.bc_to_obj(p)) == p


def test_affine_inverse_undoes_translation_rotation_scale():
    # column-major: rotate 90 deg about z, scale 2, translate (10, 20, 30)
    m = [0, 2, 0, 0,  -2, 0, 0, 0,  0, 0, 2, 0,  10, 20, 30, 1]
    p = (1.0, 2.0, 3.0)
    q = frames.apply(m, p)
    assert q == pytest.approx((10 - 4.0, 20 + 2.0, 36.0))
    back = frames.apply(frames.affine_inverse(m), q)
    assert back == pytest.approx(p, abs=1e-12)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/tools/test_shape_diff.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.shape_diff'`.

- [ ] **Step 3: Implement**

`tools/shape_diff/__init__.py`:

```python
"""Shape-geometry diffs for BC set NIFs (spec:
docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md).

Only diffs are committed: indices into the player's own NIF plus geometry
Mark authored. OBJ exports of BC geometry stay in a scratch directory."""


class ShapeDiffError(Exception):
    """A refusal with a message meant for the person running the tool."""
```

`tools/shape_diff/payload.py`:

```python
"""Encoder for the opaque "BSD1" shape-edit payload (spec §6.1). The C++
decoder is native/src/assets/src/mesh_fix.cc:decode_shape_edits; both are
pinned by the same golden blob in their tests."""
import base64
import struct

from tools.shape_diff import ShapeDiffError

_MAGIC = b"BSD1"


def _u16(n: int, what: str) -> bytes:
    if not 0 <= n <= 0xFFFF:
        raise ShapeDiffError(f"{what} {n} does not fit in 16 bits")
    return struct.pack("<H", n)


def encode(edits: list) -> bytes:
    out = bytearray(_MAGIC)
    out += _u16(len(edits), "shape count")
    for e in edits:
        moves = e.get("moves", [])
        uvs = e.get("uvs", [])
        addv = e.get("add_vertices", [])
        remt = e.get("remove_triangles", [])
        addt = e.get("add_triangles", [])
        out += struct.pack("<I", e["block"])
        out += _u16(e["orig_vertex_count"], "vertex count")
        out += _u16(e["orig_triangle_count"], "triangle count")
        for n, what in ((moves, "moves"), (uvs, "uvs"), (addv, "added vertices"),
                        (remt, "removed triangles"), (addt, "added triangles")):
            out += _u16(len(n), what)
        for i, p in moves:
            out += _u16(i, "move index") + struct.pack("<3f", *p)
        for i, uv in uvs:
            out += _u16(i, "uv index") + struct.pack("<2f", *uv)
        for v in addv:
            out += struct.pack("<11f", *v["pos"], *v["uv0"], *v["uv1"], *v["color"])
        for t in remt:
            out += _u16(t, "removed triangle")
        for t in addt:
            out += b"".join(_u16(i, "triangle index") for i in t)
    return bytes(out)


def encode_b64(edits: list) -> str:
    return base64.b64encode(encode(edits)).decode("ascii")
```

`tools/shape_diff/frames.py`:

```python
"""Axis conventions and 4x4 helpers. Matrices are column-major lists of 16
floats, as `_dauntless_host.nif_shapes` returns `world`."""


def bc_to_obj(p):
    """BC model (Z-up) -> OBJ file axes that Blender's default import shows Z-up."""
    return (p[0], p[2], -p[1])


def obj_to_bc(p):
    """Inverse of bc_to_obj: OBJ (x, y, z) is BC (x, -z, y)."""
    return (p[0], -p[2], p[1])


def apply(m, p):
    x, y, z = p
    return (m[0] * x + m[4] * y + m[8] * z + m[12],
            m[1] * x + m[5] * y + m[9] * z + m[13],
            m[2] * x + m[6] * y + m[10] * z + m[14])


def affine_inverse(m):
    """Inverse of an affine column-major 4x4 (general 3x3 part)."""
    a, b, c = m[0], m[4], m[8]
    d, e, f = m[1], m[5], m[9]
    g, h, i = m[2], m[6], m[10]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        raise ValueError("singular transform")
    inv = [(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det,
           (f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det,
           (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]
    # inv is row-major 3x3: inv[r*3 + c]
    t = (m[12], m[13], m[14])
    tt = [-(inv[r * 3] * t[0] + inv[r * 3 + 1] * t[1] + inv[r * 3 + 2] * t[2]) for r in range(3)]
    return [inv[0], inv[3], inv[6], 0.0,
            inv[1], inv[4], inv[7], 0.0,
            inv[2], inv[5], inv[8], 0.0,
            tt[0], tt[1], tt[2], 1.0]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/tools/test_shape_diff.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/shape_diff/__init__.py tools/shape_diff/payload.py tools/shape_diff/frames.py tests/tools/test_shape_diff.py
git commit -m "feat(tools): shape_diff payload encoder + frame helpers (golden-pinned with C++)"
```

---

### Task 6: OBJ writer and reader

**Files:**
- Create: `tools/shape_diff/obj_io.py`
- Modify: `tests/tools/test_shape_diff.py`

**Interfaces:**
- Consumes: `frames.bc_to_obj`, `frames.obj_to_bc`; shape dicts as returned by `nif_shapes` (keys `block`, `parent`, `vertices` (model space), `uvs`, `colors`, `triangles`, `textures`, `hidden`).
- Produces:
```python
WELD = 1024.0
def object_name(shape: dict) -> str         # "b0468_Material_D_walls_1" (+ "_hidden")
def block_of(name: str) -> int               # parses the "b%04d_" prefix; ShapeDiffError otherwise
def write_obj(shapes, obj_path: Path, mtl_path: Path, texture_path_for) -> None
    # texture_path_for(basename) -> Path | None ; writes map_Kd only when found
def read_objects(path: Path) -> dict[str, ObjMesh]
class ObjMesh:   # per object, in file order
    positions: list[tuple]      # BC model space (axis already undone)
    faces: list[list[tuple]]    # each corner (local_vertex_index, (u, v) NIF-convention | None)
```

Writer rules: per shape, weld by `round(c * WELD)` on the model-space position, keeping first-seen order; one `v` per welded vertex (with colour `r g b` from the first original vertex welded there, if the shape has colours); one `vt` per original vertex (`u, 1 - v`); one `f` per original triangle using the welded `v` index and the original vertex's `vt`; skip triangles whose welded indices repeat (degenerate after welding). Values `%.6f`. One `usemtl` per shape named after its first texture basename (or `none`). Hidden shapes are written too.

- [ ] **Step 1: Write the failing tests** — append to `tests/tools/test_shape_diff.py`:

```python
from pathlib import Path

from tools.shape_diff import obj_io


def _shape(block=11, parent="wall side pnls 01", offset=(0.0, 0.0, 0.0)):
    """A unit quad with a UV seam: vertices 1 and 4 share a position but not a UV."""
    ox, oy, oz = offset
    verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (1, 0, 0)]
    return {
        "block": block, "parent": parent, "hidden": False,
        "vertices": [(x + ox, y + oy, z + oz) for x, y, z in verts],
        "uvs": [(0, 0), (0.5, 0), (0.5, 1), (0, 1), (1.0, 0)],
        "colors": [(1, 1, 1, 1)] * 5, "uvs1": [],
        "triangles": [(0, 1, 2), (0, 2, 3), (4, 2, 1)],
        "textures": ["Map 1.tga"],
        "world": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, ox, oy, oz, 1],
    }


def test_object_name_and_block_round_trip():
    assert obj_io.object_name(_shape(468, "Material: D walls 1")) == "b0468_Material_D_walls_1"
    assert obj_io.block_of("b0468_Material_D_walls_1") == 468
    with pytest.raises(ShapeDiffError):
        obj_io.block_of("Cube")


def test_write_then_read_welds_by_position_and_keeps_uvs(tmp_path):
    obj, mtl = tmp_path / "s.obj", tmp_path / "s.mtl"
    obj_io.write_obj([_shape()], obj, mtl, lambda name: None)
    objs = obj_io.read_objects(obj)
    m = objs["b0011_wall_side_pnls_01"]
    assert len(m.positions) == 4                 # seam duplicate welded
    assert m.positions[1] == pytest.approx((1, 0, 0))
    assert len(m.faces) == 2                     # (4,2,1) is degenerate after welding
    uvs = sorted(uv for f in m.faces for _, uv in f)
    assert (0.5, 1.0) in [tuple(round(c, 6) for c in uv) for uv in uvs]
    assert "usemtl Map_1.tga" in obj.read_text()


def test_read_objects_ignores_colours_normals_and_groups(tmp_path):
    p = tmp_path / "b.obj"
    p.write_text(
        "# Blender\nmtllib b.mtl\no b0003_x\n"
        "v 0 0 0 1 0 0\nv 1 0 0 1 0 0\nv 1 1 0 1 0 0\n"
        "vn 0 1 0\nvt 0 1\nvt 1 1\nvt 1 0\ns 0\nusemtl m\n"
        "f 1/1/1 2/2/1 3/3/1\n"
        "o b0004_y\nv 5 5 5\nv 6 5 5\nv 6 6 5\nf 4 5 6\n")
    objs = obj_io.read_objects(p)
    a, b = objs["b0003_x"], objs["b0004_y"]
    assert a.positions[1] == pytest.approx((1, 0, 0))     # OBJ (1,0,0) -> BC (1,-0,0)
    assert a.faces == [[(0, (0.0, 0.0)), (1, (1.0, 0.0)), (2, (1.0, 1.0))]]
    assert b.faces == [[(0, None), (1, None), (2, None)]]  # global -> local indices
    assert b.positions[0] == pytest.approx((5, -5, 5))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/tools/test_shape_diff.py -q`
Expected: FAIL — `ImportError: cannot import name 'obj_io'`.

- [ ] **Step 3: Implement** `tools/shape_diff/obj_io.py`:

```python
"""OBJ/MTL writer and reader for shape diffs. The writer exports BC model
space with OBJ axes (x, z, -y) so Blender's DEFAULT import shows Z-up; the
reader undoes that. UV v is flipped (OBJ origin bottom-left, NIF top-left)."""
import re
from dataclasses import dataclass, field
from pathlib import Path

from tools.shape_diff import ShapeDiffError, frames

WELD = 1024.0
_NAME_RE = re.compile(r"^b(\d{4,})_")


def object_name(shape: dict) -> str:
    label = re.sub(r"[^A-Za-z0-9]+", "_", shape.get("parent") or "").strip("_")
    name = f"b{shape['block']:04d}_{label}" if label else f"b{shape['block']:04d}"
    return name + "_hidden" if shape.get("hidden") else name


def block_of(name: str) -> int:
    m = _NAME_RE.match(name + "_")
    if not m:
        raise ShapeDiffError(f"object {name!r} is not a shape export (expected b<block>_...)")
    return int(m.group(1))


def _mat_name(shape: dict) -> str:
    tex = shape.get("textures") or []
    return re.sub(r"\s+", "_", tex[0]) if tex else "none"


def write_obj(shapes, obj_path: Path, mtl_path: Path, texture_path_for) -> None:
    lines = [f"mtllib {mtl_path.name}"]
    mats = {}
    v_base = vt_base = 0
    for s in shapes:
        weld, order = {}, []
        welded_of = []
        for i, p in enumerate(s["vertices"]):
            key = tuple(round(c * WELD) for c in p)
            if key not in weld:
                weld[key] = len(order)
                order.append(i)
            welded_of.append(weld[key])
        lines.append(f"o {object_name(s)}")
        cols = s.get("colors") or []
        for i in order:
            x, y, z = frames.bc_to_obj(s["vertices"][i])
            if cols:
                r, g, b, _ = cols[i]
                lines.append(f"v {x:.6f} {y:.6f} {z:.6f} {r:.6f} {g:.6f} {b:.6f}")
            else:
                lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
        for u, v in s["uvs"]:
            lines.append(f"vt {u:.6f} {1.0 - v:.6f}")
        mat = _mat_name(s)
        mats.setdefault(mat, (s.get("textures") or [None])[0])
        lines.append(f"usemtl {mat}")
        for t in s["triangles"]:
            w = [welded_of[k] for k in t]
            if len(set(w)) < 3:
                continue
            lines.append("f " + " ".join(f"{v_base + w[j] + 1}/{vt_base + t[j] + 1}"
                                         for j in range(3)))
        v_base += len(order)
        vt_base += len(s["uvs"])
    obj_path.write_text("\n".join(lines) + "\n")

    mtl = []
    for mat, tex in mats.items():
        mtl += [f"newmtl {mat}", "Kd 1 1 1"]
        path = texture_path_for(tex) if tex else None
        if path is not None:
            mtl.append(f"map_Kd {path}")
    mtl_path.write_text("\n".join(mtl) + "\n")


@dataclass
class ObjMesh:
    positions: list = field(default_factory=list)
    faces: list = field(default_factory=list)


def read_objects(path: Path) -> dict:
    objs = {}
    owner = []          # global v index -> (mesh, local index)
    uvs = []
    current = None
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        tag = parts[0]
        if tag == "o":
            name = " ".join(parts[1:])
            current = objs.setdefault(name, ObjMesh())
        elif tag == "v":
            if current is None:
                raise ShapeDiffError("vertex before any 'o' line")
            p = tuple(float(c) for c in parts[1:4])
            owner.append((current, len(current.positions)))
            current.positions.append(frames.obj_to_bc(p))
        elif tag == "vt":
            u, v = float(parts[1]), float(parts[2])
            uvs.append((u, 1.0 - v))
        elif tag == "f":
            face = []
            for tok in parts[1:]:
                fields = tok.split("/")
                vi = int(fields[0])
                vi = vi - 1 if vi > 0 else len(owner) + vi
                mesh, local = owner[vi]
                if mesh is not current:
                    raise ShapeDiffError("face references another object's vertex")
                uv = None
                if len(fields) > 1 and fields[1]:
                    ti = int(fields[1])
                    uv = uvs[ti - 1 if ti > 0 else len(uvs) + ti]
                face.append((local, uv))
            current.faces.append(face)
    return objs
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/tools/test_shape_diff.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tools/shape_diff/obj_io.py tests/tools/test_shape_diff.py
git commit -m "feat(tools): shape_diff OBJ writer (welded, Z-up for Blender defaults) and reader"
```

---

### Task 7: Identity — map base.obj vertices back to original NIF vertices

**Files:**
- Create: `tools/shape_diff/match.py`
- Modify: `tests/tools/test_shape_diff.py`

**Interfaces:**
- Consumes: `ObjMesh`, `block_of`.
- Produces:
```python
POS_TOL = 1e-4
def identify(shape: dict, mesh: ObjMesh) -> list[list[int]]
    # per OBJ vertex: every original vertex index of `shape` within POS_TOL
    # (its welded seam duplicates). Raises ShapeDiffError naming the first
    # OBJ vertex with no match.
```
Face mismatches are NOT fatal (Review Focus 1).

- [ ] **Step 1: Write the failing tests** — append:

```python
from tools.shape_diff import match


def _permute(mesh, perm):
    """Simulate Blender reordering: new index k holds old vertex perm[k]."""
    inv = {old: new for new, old in enumerate(perm)}
    out = obj_io.ObjMesh()
    out.positions = [mesh.positions[o] for o in perm]
    out.faces = [[(inv[v], uv) for v, uv in f] for f in mesh.faces]
    return out


def _export_read(tmp_path, shapes):
    obj, mtl = tmp_path / "x.obj", tmp_path / "x.mtl"
    obj_io.write_obj(shapes, obj, mtl, lambda n: None)
    return obj_io.read_objects(obj)


def test_identify_maps_every_vertex_including_seam_duplicates(tmp_path):
    s = _shape(offset=(10.0, -4.0, 2.0))
    m = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    m = _permute(m, [3, 1, 0, 2])
    ids = match.identify(s, m)
    assert ids == [[3], [1, 4], [0], [2]]


def test_identify_refuses_unknown_vertex(tmp_path):
    s = _shape()
    m = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    m.positions[2] = (7.0, 7.0, 7.0)
    with pytest.raises(ShapeDiffError, match="vertex 2"):
        match.identify(s, m)


def test_identify_tolerates_missing_duplicate_faces(tmp_path):
    s = _shape()
    s["triangles"] = s["triangles"] + [(0, 1, 2)]      # exact duplicate triangle
    m = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    m.faces = m.faces[:1]                               # Blender dropped faces
    assert len(match.identify(s, m)) == 4
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/tools/test_shape_diff.py -q`
Expected: FAIL — `ImportError: cannot import name 'match'`.

- [ ] **Step 3: Implement** `tools/shape_diff/match.py`:

```python
"""Identity and diff between Blender OBJ exports and the original NIF shapes.

Blender does not preserve vertex order across import, so identity goes by
position (POS_TOL), never by index. Between base.obj and edit.obj (both
written by Blender from the same mesh) the vertex index IS stable for
surviving vertices; diff_shape relies on that and checks it."""
from tools.shape_diff import ShapeDiffError

POS_TOL = 1e-4
_CELL = 1e-3   # spatial hash cell; > POS_TOL so a 3x3x3 probe suffices


def _grid(points):
    g = {}
    for i, p in enumerate(points):
        g.setdefault(tuple(int(c // _CELL) for c in p), []).append(i)
    return g


def _near(grid, points, p):
    cx, cy, cz = (int(c // _CELL) for c in p)
    out = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for i in grid.get((cx + dx, cy + dy, cz + dz), ()):
                    q = points[i]
                    if max(abs(q[0] - p[0]), abs(q[1] - p[1]), abs(q[2] - p[2])) <= POS_TOL:
                        out.append(i)
    return sorted(out)


def identify(shape: dict, mesh) -> list:
    pts = shape["vertices"]
    grid = _grid(pts)
    ids = []
    for k, p in enumerate(mesh.positions):
        found = _near(grid, pts, p)
        if not found:
            raise ShapeDiffError(
                f"block {shape['block']}: OBJ vertex {k} at {p} matches no original "
                f"vertex (was base.obj exported unaltered with default axes?)")
        ids.append(found)
    return ids
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/tools/test_shape_diff.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tools/shape_diff/match.py tests/tools/test_shape_diff.py
git commit -m "feat(tools): shape_diff identity — Blender vertices back to NIF vertices by position"
```

---

### Task 8: Move-only diff

**Files:**
- Modify: `tools/shape_diff/match.py`
- Modify: `tests/tools/test_shape_diff.py`

**Interfaces:**
- Consumes: `identify`, `frames.apply`, `frames.affine_inverse`, `obj_io.block_of`.
- Produces:
```python
def diff_shape(shape: dict, base, edit) -> dict | None
    # None when nothing moved; else an edit dict (payload.encode keys) with
    # only "moves" populated, sorted by original vertex index, positions in
    # shape-local frame (inverse(world) applied in float64).
def diff(shapes: list[dict], base_objs: dict, edit_objs: dict) -> list[dict]
    # edits sorted by block; ShapeDiffError on object-set mismatch,
    # vertex-count change, or any face change (iteration 2 territory).
```

- [ ] **Step 1: Write the failing tests** — append:

```python
def _moved(mesh, k, p):
    out = obj_io.ObjMesh()
    out.positions = list(mesh.positions)
    out.positions[k] = p
    out.faces = [list(f) for f in mesh.faces]
    return out


def test_unchanged_edit_produces_no_edits(tmp_path):
    s = _shape()
    objs = _export_read(tmp_path, [s])
    assert match.diff([s], objs, objs) == []


def test_move_moves_every_welded_duplicate(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    edit = _moved(base, 1, (1.25, 0.0, 0.5))           # the seam vertex
    e = match.diff_shape(s, base, edit)
    assert e["block"] == 11 and e["orig_vertex_count"] == 5 and e["orig_triangle_count"] == 3
    assert [i for i, _ in e["moves"]] == [1, 4]
    assert e["moves"][0][1] == pytest.approx((1.25, 0.0, 0.5))
    assert not e.get("add_vertices") and not e.get("add_triangles")


def test_move_is_stored_in_shape_local_frame(tmp_path):
    s = _shape(offset=(100.0, 50.0, 10.0))
    base = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    edit = _moved(base, 2, (101.0, 51.0, 10.75))        # model space
    e = match.diff_shape(s, base, edit)
    assert e["moves"] == [(2, pytest.approx((1.0, 1.0, 0.75)))]


def test_topology_change_is_refused_for_iteration_1(tmp_path):
    s = _shape()
    base = _export_read(tmp_path, [s])["b0011_wall_side_pnls_01"]
    edit = _moved(base, 0, base.positions[0])
    edit.faces = edit.faces[:1]
    with pytest.raises(ShapeDiffError, match="iteration 2"):
        match.diff_shape(s, base, edit)
    edit2 = _moved(base, 0, base.positions[0])
    edit2.positions.append((9.0, 9.0, 9.0))
    with pytest.raises(ShapeDiffError, match="vertex count"):
        match.diff_shape(s, base, edit2)


def test_diff_refuses_renamed_or_missing_objects(tmp_path):
    s = _shape()
    objs = _export_read(tmp_path, [s])
    with pytest.raises(ShapeDiffError, match="objects differ"):
        match.diff([s], objs, {"b0011_renamed": objs["b0011_wall_side_pnls_01"]})
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/tools/test_shape_diff.py -q`
Expected: FAIL — `AttributeError: module 'tools.shape_diff.match' has no attribute 'diff_shape'`.

- [ ] **Step 3: Implement** — append to `match.py` (add `from tools.shape_diff import frames, obj_io` to the imports):

```python
def _face_key(face):
    """Rotation-invariant, winding-preserving key over vertex indices."""
    vs = [v for v, _ in face]
    k = vs.index(min(vs))
    return tuple(vs[k:] + vs[:k])


def diff_shape(shape: dict, base, edit):
    block = shape["block"]
    if len(edit.positions) != len(base.positions):
        raise ShapeDiffError(
            f"block {block}: vertex count changed ({len(base.positions)} -> "
            f"{len(edit.positions)}); adding/deleting vertices is iteration 2+")
    if sorted(map(_face_key, edit.faces)) != sorted(map(_face_key, base.faces)):
        raise ShapeDiffError(
            f"block {block}: faces changed; topology edits are iteration 2 "
            f"(this iteration is move-only)")
    ids = identify(shape, base)
    inv = frames.affine_inverse(shape["world"])
    moves = {}
    for k, (bp, ep) in enumerate(zip(base.positions, edit.positions)):
        if max(abs(a - b) for a, b in zip(bp, ep)) <= POS_TOL:
            continue
        local = frames.apply(inv, ep)
        for orig in ids[k]:
            moves[orig] = local
    if not moves:
        return None
    return {
        "block": block,
        "orig_vertex_count": len(shape["vertices"]),
        "orig_triangle_count": len(shape["triangles"]),
        "moves": sorted(moves.items()),
    }


def diff(shapes: list, base_objs: dict, edit_objs: dict) -> list:
    if set(base_objs) != set(edit_objs):
        missing = sorted(set(base_objs) ^ set(edit_objs))
        raise ShapeDiffError(f"objects differ between base and edit: {missing[:5]} "
                             f"(don't join, split or rename objects)")
    by_block = {s["block"]: s for s in shapes}
    edits = []
    for name in sorted(base_objs, key=obj_io.block_of):
        block = obj_io.block_of(name)
        if block not in by_block:
            raise ShapeDiffError(f"object {name}: block {block} is not a shape in this NIF")
        e = diff_shape(by_block[block], base_objs[name], edit_objs[name])
        if e is not None:
            edits.append(e)
    return edits
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/tools/test_shape_diff.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tools/shape_diff/match.py tests/tools/test_shape_diff.py
git commit -m "feat(tools): shape_diff move-only diff (welded duplicates move together, shape-local)"
```

---

### Task 9: CLI, drift-guard update, real-DBridge round trip

**Files:**
- Create: `tools/bridge_shape_diff.py`
- Modify: `tests/tools/test_mesh_fixes_drift.py`
- Modify: `tests/tools/test_shape_diff.py`

**Interfaces:**
- Consumes: everything above; `engine.paths.game_root()`; `_dauntless_host.nif_shapes`; `tools.gen_mesh_fixes.fnv1a64_hex`.
- Produces CLI:
```
uv run python -m tools.bridge_shape_diff export --out DIR [--nif REL]
uv run python -m tools.bridge_shape_diff diff BASE.obj EDIT.obj [--nif REL] [--write]
```
and functions `build_fix(rel, base_path, edit_path) -> (fix_dict, edits)` and `fix_text(fix_dict) -> str` (`json.dumps(fix, indent=2) + "\n"`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/tools/test_shape_diff.py`:

```python
from engine import paths

DBRIDGE = "data/Models/Sets/DBridge/Dbridge.NIF"


def test_fix_text_is_opaque_and_well_formed():
    from tools import bridge_shape_diff as cli
    fix = cli.make_fix_dict(DBRIDGE, [GOLDEN_EDIT])
    text = cli.fix_text(fix)
    assert '"generator": "tools/bridge_shape_diff.py"' in text
    assert '"shape_edits": "' + GOLDEN_B64 + '"' in text
    assert "merges" not in text


def test_real_dbridge_export_round_trips_with_no_edits(tmp_path):
    host = pytest.importorskip("_dauntless_host")
    nif = paths.game_root() / DBRIDGE
    if not nif.exists():
        pytest.skip("BC content not configured")
    from tools import bridge_shape_diff as cli
    cli.export(DBRIDGE, tmp_path)
    obj = tmp_path / "Dbridge.obj"
    objs = obj_io.read_objects(obj)
    assert len(objs) == 145
    shapes = host.nif_shapes(str(nif))
    for s in shapes:
        match.identify(s, objs[obj_io.object_name(s)])      # every vertex identified
    fix, edits = cli.build_fix(DBRIDGE, obj, obj)
    assert edits == []


def test_real_dbridge_move_lands_in_local_frame(tmp_path):
    host = pytest.importorskip("_dauntless_host")
    nif = paths.game_root() / DBRIDGE
    if not nif.exists():
        pytest.skip("BC content not configured")
    from tools import bridge_shape_diff as cli
    cli.export(DBRIDGE, tmp_path)
    base = tmp_path / "Dbridge.obj"
    edit = tmp_path / "edit.obj"
    lines = base.read_text().splitlines()
    i = lines.index("o b0468_Material_D_walls_1") + 1
    x, y, z = map(float, lines[i].split()[1:4])
    lines[i] = f"v {x:.6f} {y + 0.5:.6f} {z:.6f}" + "".join(
        " " + c for c in lines[i].split()[4:])
    edit.write_text("\n".join(lines) + "\n")
    _, edits = cli.build_fix(DBRIDGE, base, edit)
    assert [e["block"] for e in edits] == [468]
    s = {d["block"]: d for d in host.nif_shapes(str(nif))}[468]
    for orig, local in edits[0]["moves"]:
        model = frames.apply(s["world"], local)
        assert model[2] == pytest.approx(s["vertices"][orig][2] + 0.5, abs=1e-4)  # OBJ +y is BC +z
```

Modify `tests/tools/test_mesh_fixes_drift.py`: replace the `committed = ...` line with

```python
    committed = {
        p.name: p.read_text() for p in FIX_DIR.glob("*.json")
        # Only gen_mesh_fixes' own files can be regenerated here; shape-edit
        # fixes (tools/bridge_shape_diff.py) come from OBJs that are never
        # committed, and are guarded by AssetCacheMeshFix.EveryCommittedFixApplies.
        if json.loads(p.read_text()).get("generator") == "tools/gen_mesh_fixes.py"
    }
```

and add `import json` at the top.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/tools/test_shape_diff.py tests/tools/test_mesh_fixes_drift.py -q`
Expected: the three new tests FAIL with `ImportError` (no `tools.bridge_shape_diff`); drift test passes.

- [ ] **Step 3: Implement** `tools/bridge_shape_diff.py`:

```python
"""Shape-geometry diff for BC set NIFs: export to OBJ for Blender, diff an
edited export against an unaltered one, write ONLY the diff as a mesh fix.

Spec: docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md

    uv run python -m tools.bridge_shape_diff export --out <scratch dir>
    uv run python -m tools.bridge_shape_diff diff <base.obj> <edit.obj> [--write]

OBJ files contain BC geometry: keep them OUT of the repo. Blender: import the
exported OBJ with default settings; export base.obj before editing and
edit.obj after, both with default settings. Don't join, split or rename
objects. Iteration 1 accepts vertex MOVES only."""
import argparse
import json
import sys
from pathlib import Path

from engine import paths
from tools.gen_mesh_fixes import fnv1a64_hex
from tools.shape_diff import ShapeDiffError, match, obj_io, payload

GENERATOR = "tools/bridge_shape_diff.py"
DEFAULT_NIF = "data/Models/Sets/DBridge/Dbridge.NIF"


def _nif_path(rel: str) -> Path:
    # Stock only (name-cut spec §10.3): never paths.game_asset, which prefers mods.
    return paths.game_root() / rel


def _shapes(rel: str):
    import _dauntless_host
    shapes = _dauntless_host.nif_shapes(str(_nif_path(rel)))
    if shapes is None:
        raise ShapeDiffError(f"cannot read {_nif_path(rel)}")
    return shapes


def _fix_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "native" / "assets" / "mesh_fixes"


def export(rel: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(rel).stem
    tex_dir = _nif_path(rel).parent / "High"

    def texture_path_for(name):
        p = tex_dir / name
        return p if p.exists() else None

    obj = out_dir / f"{stem}.obj"
    obj_io.write_obj(_shapes(rel), obj, out_dir / f"{stem}.mtl", texture_path_for)
    return obj


def make_fix_dict(rel: str, edits: list) -> dict:
    return {"format": 1, "source": rel, "generator": GENERATOR,
            "shape_edits": payload.encode_b64(edits)}


def fix_text(fix: dict) -> str:
    return json.dumps(fix, indent=2) + "\n"


def build_fix(rel: str, base_path: Path, edit_path: Path):
    edits = match.diff(_shapes(rel), obj_io.read_objects(base_path),
                       obj_io.read_objects(edit_path))
    return make_fix_dict(rel, edits), edits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bridge_shape_diff")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("--out", type=Path, required=True)
    ex.add_argument("--nif", default=DEFAULT_NIF)
    df = sub.add_parser("diff")
    df.add_argument("base", type=Path)
    df.add_argument("edit", type=Path)
    df.add_argument("--nif", default=DEFAULT_NIF)
    df.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "export":
            print(export(a.nif, a.out))
            return 0
        fix, edits = build_fix(a.nif, a.base, a.edit)
        for e in edits:
            print(f"block {e['block']}: {len(e['moves'])} vertices moved")
        if not edits:
            print("no changes")
            return 0
        target = _fix_dir() / (fnv1a64_hex(_nif_path(a.nif).read_bytes()) + ".json")
        if target.exists() and json.loads(target.read_text()).get("generator") != GENERATOR:
            raise ShapeDiffError(f"{target.name} is owned by another generator; refusing to overwrite")
        if a.write:
            target.write_text(fix_text(fix))
            print(f"wrote {target}")
        else:
            print(f"dry run; --write to write {target}")
        return 0
    except ShapeDiffError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/tools/test_shape_diff.py tests/tools/test_mesh_fixes_drift.py tests/unit/test_path_indirection.py -q`
Expected: all pass. If `test_path_indirection` flags `tools/bridge_shape_diff.py` or `tests/tools/test_shape_diff.py`, the cause is a literal path segment — keep the `DBRIDGE`/`DEFAULT_NIF` strings as data-relative paths (`data/Models/...`), which is what `gen_mesh_fixes.STOCK_MESHES` already does.

- [ ] **Step 5: Commit**

```bash
git add tools/bridge_shape_diff.py tests/tools/test_shape_diff.py tests/tools/test_mesh_fixes_drift.py
git commit -m "feat(tools): bridge_shape_diff CLI (export, move-only diff, --write); drift guard skips shape-edit fixes"
```

---

### Task 10: Gate, then Mark's first real edit (human-in-the-loop)

**Files:**
- Create (by `--write`): `native/assets/mesh_fixes/<dbridge hash>.json`
- Modify: `docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md` (§9 log, as-built notes)

- [ ] **Step 1: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. Any new failure is a regression from this branch — fix it, never baseline it.

- [ ] **Step 2: Export for Mark** (scratchpad, never the repo)

```bash
uv run python -m tools.bridge_shape_diff export --out /private/tmp/claude-501/-Users-mward-Documents-Projects-bc-dauntless/2b5bc370-31ee-43b4-89f9-7c639d1efaf4/scratchpad/dbridge
```

Hand Mark the path and the Blender rules: import with defaults; export `base.obj` unaltered first; move vertices only; export `edit.obj`; same export settings both times; don't join/split/rename objects.

- [ ] **Step 3: Diff Mark's files (dry run, then write)**

```bash
uv run python -m tools.bridge_shape_diff diff <scratch>/dbridge/base.obj <scratch>/dbridge/edit.obj
uv run python -m tools.bridge_shape_diff diff <scratch>/dbridge/base.obj <scratch>/dbridge/edit.obj --write
```

Expected: a per-block "N vertices moved" summary, then the fix file written. If identity fails, read the message (axis settings / unaltered export) before touching code.

- [ ] **Step 4: Prove the committed file applies to the real NIF**

Run: `build/native/tests/assets/assets_tests --gtest_filter='AssetCacheMeshFix.EveryCommittedFixApplies'`
Expected: PASS (6 files: 5 merge fixes + DBridge shape edits).

- [ ] **Step 5: Ask Mark before launching; give him plain commands**

```bash
cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/bridge-shape-diff
./build/dauntless --developer
```

Mark checks the gaps in game (Developer Options → Lighting → Bridge Debug View: mesh id / normals).

- [ ] **Step 6: On acceptance, commit the fix and update the living spec**

In the spec: set §9 row 1 to `accepted <date>` with the block list and vertex counts; add an "As built (iteration 1)" section noting (a) the diff tool refuses any topology change in iteration 1, (b) `preview` was dropped — Blender's own `edit.obj` is the preview, (c) any deviation found live.

```bash
git add native/assets/mesh_fixes/<hash>.json docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md
git commit -m "feat(bridge): DBridge gap closing via shape-edit diff (iteration 1, live-verified)"
```
