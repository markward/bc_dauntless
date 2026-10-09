# Bridge Editor Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A developer-only in-game "Bridge Emitters…" editor where you fly a free camera around the bridge, click a NIF shape to select it (stable identity across launches), see it highlighted, set its per-shape PBR material override (roughness/metalness), and save that into a per-bridge data file keyed by the NIF's content hash.

**Architecture:** C++ gains shape identity (NIF block index per mesh, NIF content hash per interior model), a ray pick that reports the hit mesh and can exclude meshes, and a dev-only selection tint in the bridge pass. Python gets pure, unit-tested modules under `engine/bridge_editor/` (fly camera, picking, the lighting document and its writer) and a `Panel` subclass driven by the host loop exactly like the other dev modals. The material override is stored and edited here but **not rendered** — the PBR plan (plan 2) consumes it.

**Tech Stack:** C++20 / GLSL 410 / pybind11 (native), Python 3 (engine), CEF HTML/JS/CSS (UI), gtest + pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` — this plan implements §4 (camera & selection), §7 (persistence) and the Selection + Material panes of §8. Programme step 1 of §5.

## Global Constraints

- ⛔ Never run `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A` / `git add .`. Stage with explicit pathspecs. To mutate a file temporarily: `cp f /tmp/bak` → edit → test → `cp /tmp/bak f` → `diff f /tmp/bak`.
- Work in the worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/bridge-emitters`, branch `spike/bridge-emitters`. Build there: `cmake -B build -S . && cmake --build build -j` (never from `native/`, never another output dir, never change `CMAKE_BUILD_TYPE`).
- Shader edits need a rebuild (`cmake --build build -j`) — shaders are embedded at configure/build time, and shader compile errors only show at RUNTIME (a GL test must draw through the shader).
- Every new GLSL sampler gets an explicit texture unit (none are added in this plan).
- Never spell `game` or `sdk` as a path segment in `engine/`, `tools/`, `native/src`; never capture a path at import (resolve at use via `engine.paths`).
- Developer-only: every new binding with a visible effect is a no-op unless `--developer` (`dauntless::is_developer_mode()`); the panel is constructed only under `dev_mode.is_enabled()`. With `--developer` off, the production render path is byte-identical.
- Bridge-local units; the bridge instance draws with an identity transform; bridge up is +Z; bridge forward at yaw 0 is +Y (`_BridgeCamera`).
- Shape identity = (NIF content hash, NIF block index, shape name). Shape key string = `f"{block}:{name}"`.
- Material defaults (spec §9.2 source C): **metalness 0, roughness 1**. Override values are floats in [0, 1].
- Data files: `native/assets/bridge_lighting/<16-hex fnv1a64>.json` (project) — mods/replacements may ship `<dir>/dauntless/bridge_lighting/<hash>.json`, searched first. Unknown keys are REJECTED at load. Writer is deterministic (sorted keys, floats rounded to 6 dp, 2-space indent, trailing newline) and atomic (`.tmp` + `os.replace`).
- Test gate before calling the plan done: `scripts/check_tests.sh` green, no new lines in `tests/known_failures.txt`.

## Review Focus

1. **Picking in the wrong space.** Cursor and viewport must both be FRAMEBUFFER pixels (`h.cursor_pos()`, `h.framebuffer_size()`), and the pick camera must be the camera actually drawn (the fly camera's pose). A pick against the captain camera while flying selects an off-screen shape. Pinned by Task 9's `test_pick_uses_the_fly_camera_pose`.
2. **Clicking the docked panel also picks the shape behind it.** CEF receives the click AND the panel's `handle_input` sees the raw button. Clicks whose x is inside the dock (right `DOCK_CSS_PX` × dsf pixels) must not pick. Pinned by Task 9's `test_click_over_the_dock_does_not_pick`.
3. **Cursor left locked.** Closing the panel (Close, ESC, mission swap) while RMB is held must unlock the cursor and clear the highlight. Pinned by Task 9's `test_close_while_flying_unlocks_cursor_and_clears_highlight`.
4. **A stale or mismatched file applied to the wrong shape.** A file whose block holds a differently-named shape must skip that entry with a warning, never apply it. Pinned by Task 7's `test_match_shapes_skips_a_name_mismatch`.
5. **Save over a file that failed to load.** A file that failed validation must not be silently overwritten by an empty document. Pinned by Task 9's `test_save_is_refused_when_the_file_failed_to_load`.

---

## File Structure

**C++ (native)**
- Modify `native/src/assets/include/assets/mesh.h` — `Mesh::source_block()`.
- Modify `native/src/assets/src/model_build.cc` — record the NiTriShape block index per mesh.
- Modify `native/src/assets/include/assets/model.h` — `Model::content_hash`.
- Modify `native/src/assets/src/cache.cc` — set `content_hash` for interior loads.
- Modify `native/src/renderer/include/renderer/ray_trace.h`, `native/src/renderer/ray_trace.cc` — `RayHit::mesh_index/triangle`, `exclude_meshes`.
- Modify `native/src/renderer/include/renderer/bridge_pass.h`, `native/src/renderer/bridge_pass.cc`, `native/src/renderer/shaders/bridge.frag` — selection tint.
- Modify `native/src/host/host_bindings.cc` — `ray_trace_mesh_pick`, `model_identity`, `set_bridge_highlight`.
- Tests: `native/tests/assets/cpu/model_build_test.cc`, `native/tests/assets/cpu/cache_test.cc`, `native/tests/renderer/ray_trace_test.cc`, new `native/tests/renderer/bridge_highlight_test.cc` (+ `native/tests/renderer/CMakeLists.txt`).

**Python (engine)**
- Modify `engine/host_io.py` — wrappers `ray_trace_mesh_pick`, `model_identity`, `set_bridge_highlight`, `nif_shape_textures`.
- Create `engine/bridge_editor/__init__.py` (empty docstring module).
- Create `engine/bridge_editor/fly_camera.py` — pure fly camera.
- Create `engine/bridge_editor/picking.py` — pure pick + identity resolution.
- Create `engine/bridge_editor/lighting_doc.py` — schema validation, lookup, shape matching.
- Create `engine/bridge_editor/lighting_writer.py` — deterministic atomic writer.
- Create `engine/ui/bridge_emitters_panel.py` — the dev panel.
- Modify `engine/host_loop.py` — registration, modal blocker, camera override.
- Create `native/assets/ui-cef/js/bridge_emitters.js`, `native/assets/ui-cef/css/bridge_emitters.css`; modify `native/assets/ui-cef/index.html`.
- Create `native/assets/bridge_lighting/.gitkeep`.
- Tests: `tests/host/test_bridge_editor_bindings.py`, `tests/unit/test_bridge_fly_camera.py`, `tests/unit/test_bridge_picking.py`, `tests/unit/test_bridge_lighting_doc.py`, `tests/unit/test_bridge_lighting_writer.py`, `tests/unit/test_bridge_emitters_panel.py`, `tests/unit/test_host_loop_bridge_emitters_registration.py`.

**Docs**
- Modify `CLAUDE.md` (reference row), the spec's §10 log.

---

### Task 1: Shape identity on meshes and interior models

**Files:**
- Modify: `native/src/assets/include/assets/mesh.h` (public accessors near `shape_name()`, private members near `shape_name_`)
- Modify: `native/src/assets/src/model_build.cc:933-939` (`PendingMesh`), `:1093` (`pm.shape_name = ...`), `:1121-1132` (final upload loop)
- Modify: `native/src/assets/include/assets/model.h` (after `std::filesystem::path source;`)
- Modify: `native/src/assets/src/cache.cc:305` (after `Model built = detail::build_model(file, ctx);`)
- Test: `native/tests/assets/cpu/model_build_test.cc`, `native/tests/assets/cpu/cache_test.cc`

**Interfaces:**
- Produces: `int assets::Mesh::source_block() const noexcept` (NIF block index of the source NiTriShape, -1 if not built from a NIF); `void assets::Mesh::set_source_block(int)`; `std::string assets::Model::content_hash` (16 lowercase hex chars = `fnv1a64_hex` of the raw NIF file bytes, set ONLY for `interior=true` NIF loads; empty otherwise).

- [ ] **Step 1: Write the failing tests**

Append to `native/tests/assets/cpu/model_build_test.cc` (inside the file, after `NodeAttachmentRecordsMeshIndex`):

```cpp
TEST_F(ModelBuildTest, MeshRecordsItsSourceNifBlock) {
    // trivial_file_with_one_trishape(): block 0 NiNode "Root",
    // block 1 NiTriShape "Saucer", block 2 NiTriShapeData.
    auto f = trivial_file_with_one_trishape();
    auto model = assets::detail::build_model(f, make_ctx());
    ASSERT_EQ(model.meshes.size(), 1u);
    EXPECT_EQ(model.meshes[0].source_block(), 1);
    EXPECT_EQ(model.meshes[0].shape_name(), "Saucer");
}

TEST(MeshDefaults, SourceBlockIsMinusOneWhenNotBuiltFromANif) {
    assets::Mesh mesh;
    EXPECT_EQ(mesh.source_block(), -1);
}
```

Append to `native/tests/assets/cpu/cache_test.cc` (after `InteriorLoadIsADistinctCachedVariant`):

```cpp
// Bridge-editor shape identity (spec 2026-10-08-bridge-emitters §4): an
// interior load carries the NIF's content hash -- the SAME fnv1a64 of the raw
// file bytes the mesh-fix lookup uses -- and every other load leaves it empty.
TEST(AssetCacheTest, InteriorLoadCarriesTheNifContentHash) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";
    if (!fs::exists(dbridge_path())) GTEST_SKIP() << "DBridge not installed";

    assets::AssetCache cache(stub_config());
    auto plain    = cache.load(dbridge_path(), {dbridge_tex_path()}, {}, {}, 1.0f, false);
    auto interior = cache.load(dbridge_path(), {dbridge_tex_path()}, {}, {}, 1.0f, false, true);

    std::ifstream in(dbridge_path(), std::ios::binary);
    std::ostringstream ss;
    ss << in.rdbuf();
    EXPECT_EQ(interior->content_hash, assets::fnv1a64_hex(ss.str()));
    EXPECT_EQ(interior->content_hash.size(), 16u);
    EXPECT_TRUE(plain->content_hash.empty());
}
```

Add at the top of `cache_test.cc` if missing: `#include <fstream>`, `#include <sstream>`, `#include <assets/mesh_fix.h>`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: compile FAIL — `no member named 'source_block'` / `no member named 'content_hash'`.

- [ ] **Step 3: Implement**

`mesh.h`, public section after `set_shape_name`:

```cpp
    /// NIF block index of the source NiTriShape, set by build_model; -1 for
    /// meshes built any other way. With shape_name() and the NIF's content
    /// hash (Model::content_hash) it is a shape's identity across launches --
    /// spec 2026-10-08-bridge-emitters §4.
    int source_block() const noexcept { return source_block_; }
    void set_source_block(int block) noexcept { source_block_ = block; }
```

private section, after `std::string shape_name_;`:

```cpp
    int source_block_ = -1;
```

`model_build.cc` — `PendingMesh` gains `int block = -1;`; where `pm.shape_name = shape->av.obj.name;` is set add `pm.block = static_cast<int>(i);` (the loop variable `i` is the block index: `for (std::uint32_t i = 0; i < f.blocks.size(); ++i)`); in BOTH branches of the final upload loop add `mesh.set_source_block(pm.block);` next to `mesh.set_shape_name(pm.shape_name);`.

`model.h`, after `std::filesystem::path source;`:

```cpp
    /// FNV-1a 64 of the raw NIF file bytes as 16 lowercase hex chars -- the
    /// same hash mesh fixes are keyed by. Set ONLY for interior (set) loads,
    /// where the bridge editor keys its per-bridge data on it; empty for every
    /// other model. Spec 2026-10-08-bridge-emitters §4/§7.
    std::string                   content_hash;
```

`cache.cc`, immediately after `Model built = detail::build_model(file, ctx);`:

```cpp
    if (interior) built.content_hash = fnv1a64_hex(read_file_bytes(nif_path));
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cmake --build build -j && ctest --test-dir build -R "ModelBuildTest.MeshRecordsItsSourceNifBlock|MeshDefaults|AssetCacheTest.InteriorLoadCarriesTheNifContentHash" --output-on-failure`
Expected: PASS (the cache test SKIPs only if no BC content root is configured).

- [ ] **Step 5: Commit**

```bash
git add native/src/assets/include/assets/mesh.h native/src/assets/src/model_build.cc native/src/assets/include/assets/model.h native/src/assets/src/cache.cc native/tests/assets/cpu/model_build_test.cc native/tests/assets/cpu/cache_test.cc
git commit -m "feat(assets): meshes record their NIF block; interior models carry the NIF content hash"
```

---

### Task 2: Ray trace reports the hit mesh and can exclude meshes

**Files:**
- Modify: `native/src/renderer/include/renderer/ray_trace.h` (`RayHit`, both `ray_trace_instance*` declarations)
- Modify: `native/src/renderer/ray_trace.cc` (`TraceTri` :53, `ensure_trace_accel` :195-229, `ray_trace_instance` :316-516, `ray_trace_instance_linear` :518)
- Test: `native/tests/renderer/ray_trace_test.cc`

**Interfaces:**
- Consumes: nothing new.
- Produces: `RayHit::mesh_index` (int, index into `Model::meshes`, -1 unknown) and `RayHit::triangle` (int, triangle index within that mesh, -1 unknown); a new trailing parameter `const std::vector<int>* exclude_meshes = nullptr` on `ray_trace_instance` and `ray_trace_instance_linear` — triangles of those mesh indices are never hit. Existing callers are unchanged (default nullptr).

- [ ] **Step 1: Write the failing tests**

Append to `ray_trace_test.cc`:

```cpp
// ── Bridge editor picking: which mesh, which triangle; exclusion ───────────

namespace {

// Two meshes on one node, stacked along +Z: mesh 0 at z = 0, mesh 1 at z = 5.
// A ray going down -Z from z = 10 hits mesh 1 first.
assets::Model two_stacked_meshes() {
    assets::Model m;
    m.nodes.push_back(assets::Node{
        .name = "root", .parent_index = -1,
        .local_transform = glm::mat4(1.0f),
        .meshes = {0, 1},
    });
    for (float z : {0.0f, 5.0f}) {
        assets::MeshCpu cpu;
        // Two triangles per mesh; the ray at (0.5, 0.5) hits triangle 1.
        cpu.vertices.push_back({.position = glm::vec3(-1, -1, z)});
        cpu.vertices.push_back({.position = glm::vec3( 1, -1, z)});
        cpu.vertices.push_back({.position = glm::vec3(-1,  1, z)});
        cpu.vertices.push_back({.position = glm::vec3( 1,  1, z)});
        cpu.indices = {0u, 1u, 2u,   1u, 3u, 2u};
        assets::Mesh mesh;
        mesh.set_cpu_data(std::move(cpu));
        m.meshes.push_back(std::move(mesh));
    }
    return m;
}

}  // namespace

TEST(RayTracePick, ReportsTheHitMeshAndTriangle) {
    const auto m = two_stacked_meshes();
    auto hit = renderer::ray_trace_instance(m, glm::mat4(1.0f),
        glm::vec3(0.5f, 0.5f, 10.0f), glm::vec3(0, 0, -1), 100.0f);
    ASSERT_TRUE(hit.has_value());
    EXPECT_EQ(hit->mesh_index, 1);
    EXPECT_EQ(hit->triangle, 1);
    EXPECT_FLOAT_EQ(hit->t, 5.0f);
}

TEST(RayTracePick, ExcludedMeshIsSeenThrough) {
    const auto m = two_stacked_meshes();
    const std::vector<int> exclude{1};
    auto hit = renderer::ray_trace_instance(m, glm::mat4(1.0f),
        glm::vec3(0.5f, 0.5f, 10.0f), glm::vec3(0, 0, -1), 100.0f,
        nullptr, &exclude);
    ASSERT_TRUE(hit.has_value());
    EXPECT_EQ(hit->mesh_index, 0);
    EXPECT_FLOAT_EQ(hit->t, 10.0f);
}

TEST(RayTracePick, ExcludingEveryMeshIsAMiss) {
    const auto m = two_stacked_meshes();
    const std::vector<int> exclude{0, 1};
    auto hit = renderer::ray_trace_instance(m, glm::mat4(1.0f),
        glm::vec3(0.5f, 0.5f, 10.0f), glm::vec3(0, 0, -1), 100.0f,
        nullptr, &exclude);
    EXPECT_FALSE(hit.has_value());
}

TEST(RayTracePick, MovedPartHitStillReportsItsMesh) {
    // root_plus_movable_child(): mesh 0 hangs off the MultiMtl node (index 2).
    // Same set-up as RayTraceOverrides.AMovedPartIsHitWhereItIsDRAWN.
    auto m = root_plus_movable_child();
    std::unordered_map<int, glm::mat4> ov;
    ov[1] = glm::translate(glm::mat4(1.0f), glm::vec3(-10.0f, 0.0f, 0.0f));
    auto hit = renderer::ray_trace_instance(
        m, glm::mat4(1.0f), glm::vec3(-10, 0, -5), glm::vec3(0, 0, 1), 100.0f,
        &ov);
    ASSERT_TRUE(hit.has_value());
    EXPECT_EQ(hit->mesh_index, 0);
    EXPECT_EQ(hit->triangle, 0);
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: compile FAIL — `no member named 'mesh_index' in 'renderer::RayHit'`.

- [ ] **Step 3: Implement**

`ray_trace.h` — `RayHit` gains:

```cpp
    int       mesh_index = -1;  // Index into Model::meshes of the hit triangle; -1 unknown.
    int       triangle = -1;    // Triangle index WITHIN that mesh (index/3); -1 unknown.
```

Both declarations gain a trailing parameter (document it: "Triangles of these mesh indices are never hit — the bridge editor's 'pick the surface behind' (spec 2026-10-08-bridge-emitters §4). nullptr or empty = none."):

```cpp
    const std::unordered_map<int, glm::mat4>* node_overrides = nullptr,
    const std::vector<int>* exclude_meshes = nullptr);
```

(add `#include <vector>`).

`ray_trace.cc`:
- `TraceTri` gains `int mesh = -1;` and `int tri = -1;` (comment: "Source mesh and its triangle index, for picking.").
- In `ensure_trace_accel`, inside the triangle loop set `t.mesh = mesh_idx; t.tri = static_cast<int>(k / 3);`.
- In `ray_trace_instance`, add the parameter; before the BVH walk:

```cpp
    const bool has_ex = (exclude_meshes != nullptr && !exclude_meshes->empty());
    const auto excluded = [&](int mesh) -> bool {
        if (!has_ex) return false;
        for (int e : *exclude_meshes) if (e == mesh) return true;
        return false;
    };
```

  In the BVH leaf loop, right after `if (is_moved(t.node)) continue;` add `if (excluded(t.mesh)) continue;`. In the moved-parts loop, after `if (mt.node < 0) continue;` add `if (excluded(mt.mesh)) continue;`, and record the winner: add `int moved_mesh = -1, moved_tri = -1;` beside `moved_hit`, set `moved_mesh = mt.mesh; moved_tri = mt.tri;` where `moved_hit = true;` is set.
- In the two `return RayHit{...}` sites, set the new fields: the moved branch uses `moved_mesh/moved_tri`; the BVH branch uses `t.mesh/t.tri`. Write them as:

```cpp
        RayHit out{glm::vec3(instance_world * glm::vec4(hit_local, 1.0f)),
                   n_world, best_t / d_local_len};
        out.mesh_index = moved_mesh;
        out.triangle = moved_tri;
        return out;
```

  (and the same shape with `best_normal`, `t.mesh`, `t.tri`).
- `ray_trace_instance_linear` gains the parameter and forwards it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cmake --build build -j && ctest --test-dir build -R "RayTrace|IntersectTriangle" --output-on-failure`
Expected: all PASS (old `RayTraceOverrides.*` still pass — behaviour unchanged with no exclusion).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/ray_trace.h native/src/renderer/ray_trace.cc native/tests/renderer/ray_trace_test.cc
git commit -m "feat(renderer): ray trace reports hit mesh + triangle and can exclude meshes"
```

---

### Task 3: Bindings — pick, model identity — and host_io wrappers

**Files:**
- Modify: `native/src/host/host_bindings.cc` (new `m.def`s directly after `ray_trace_mesh` at :6216-6270)
- Modify: `engine/host_io.py` (after `ray_trace_mesh`, :495-520)
- Test: `tests/host/test_bridge_editor_bindings.py`

**Interfaces:**
- Consumes: Task 1 `Mesh::source_block`, `Model::content_hash`; Task 2 `RayHit::mesh_index/triangle`, `exclude_meshes`.
- Produces (Python):
  - `_h.ray_trace_mesh_pick(instance_id, origin_rel, direction, max_dist, exclude_meshes: list[int]) -> ((x,y,z), (nx,ny,nz), t, mesh_index, triangle) | None` (instance-relative, like `ray_trace_mesh`).
  - `_h.model_identity(instance_id) -> {"source": str, "content_hash": str, "meshes": [{"mesh": int, "block": int, "name": str, "node_chain": [str, ...] (root→owner), "material": int}, ...]} | None`.
  - `host_io.ray_trace_mesh_pick(instance_id, origin, direction, max_dist, exclude_meshes=()) -> Optional[Tuple[Vec3, Vec3, float, int, int]]` (world in/out).
  - `host_io.model_identity(instance_id) -> Optional[dict]`.
  - `host_io.nif_shape_textures(abs_path: str) -> dict[int, list[str]]` (block → texture basenames; `{}` when unavailable).

- [ ] **Step 1: Write the failing tests**

Create `tests/host/test_bridge_editor_bindings.py`:

```python
"""Bridge editor bindings (spec 2026-10-08-bridge-emitters §4): they exist,
and their host_io wrappers degrade to None/{} instead of raising when the
host is absent or the id is stale."""
import pytest


@pytest.fixture
def host_module():
    pytest.importorskip("_dauntless_host")
    import _dauntless_host as h
    return h


@pytest.mark.parametrize("name", [
    "ray_trace_mesh_pick", "model_identity", "set_bridge_highlight",
])
def test_binding_exists(host_module, name):
    assert hasattr(host_module, name)


def test_model_identity_of_a_stale_id_is_none(host_module):
    stale = host_module.InstanceId()
    assert host_module.model_identity(stale) is None


def test_host_io_wrappers_degrade_headless(monkeypatch):
    from engine import host_io
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.ray_trace_mesh_pick(0, (0, 0, 0), (0, 0, 1), 10.0) is None
    assert host_io.model_identity(0) is None
    assert host_io.nif_shape_textures("/nope.nif") == {}
    host_io.set_bridge_highlight(None, -1, -1)   # no raise


def test_nif_shape_textures_maps_block_to_textures(monkeypatch):
    from engine import host_io

    class FakeHost:
        @staticmethod
        def nif_shapes(abs_path):
            return [{"block": 4, "name": "wall", "textures": ["Map 3.tga"]},
                    {"block": 9, "name": "floor", "textures": []}]

    monkeypatch.setattr(host_io, "_h", FakeHost)
    assert host_io.nif_shape_textures("/x.nif") == {4: ["Map 3.tga"], 9: []}


def test_nif_shape_textures_handles_a_failed_parse(monkeypatch):
    from engine import host_io

    class FakeHost:
        @staticmethod
        def nif_shapes(abs_path):
            return None

    monkeypatch.setattr(host_io, "_h", FakeHost)
    assert host_io.nif_shape_textures("/x.nif") == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/host/test_bridge_editor_bindings.py -v`
Expected: FAIL — `AttributeError: module 'engine.host_io' has no attribute 'ray_trace_mesh_pick'`, and the binding-exists cases fail.

- [ ] **Step 3: Implement the bindings**

In `host_bindings.cc`, directly after the `ray_trace_mesh` `m.def(...)` block:

```cpp
    // Bridge editor pick (spec 2026-10-08-bridge-emitters §4): ray_trace_mesh
    // plus WHICH mesh and triangle were hit, with meshes to see through (the
    // "pick the surface behind" click). Same instance-relative convention.
    m.def("ray_trace_mesh_pick",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> origin,
             std::tuple<float, float, float> direction,
             float max_dist,
             std::vector<int> exclude_meshes) -> py::object {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return py::none();
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr) return py::none();
              const glm::vec3 o(std::get<0>(origin), std::get<1>(origin),
                                std::get<2>(origin));
              glm::vec3 d(std::get<0>(direction), std::get<1>(direction),
                          std::get<2>(direction));
              const float dlen = glm::length(d);
              if (dlen < 1e-9f) return py::none();
              d /= dlen;
              if (!std::isfinite(max_dist) || max_dist <= 0.0f) return py::none();
              auto hit = renderer::ray_trace_instance_linear(
                  *model, inst->world_linear, o, d, max_dist,
                  &inst->node_overrides, &exclude_meshes);
              if (!hit) return py::none();
              return py::make_tuple(
                  py::make_tuple(hit->point.x, hit->point.y, hit->point.z),
                  py::make_tuple(hit->normal.x, hit->normal.y, hit->normal.z),
                  hit->t, hit->mesh_index, hit->triangle);
          },
          py::arg("instance_id"), py::arg("origin"), py::arg("direction"),
          py::arg("max_dist"), py::arg("exclude_meshes") = std::vector<int>{},
          "ray_trace_mesh plus (mesh_index, triangle) of the hit; triangles of "
          "exclude_meshes are never hit. Instance-relative origin/point. None "
          "on a miss or a stale id (never raises: the editor polls it).");

    // Per-mesh shape identity of an instance's model (spec
    // 2026-10-08-bridge-emitters §4): NIF block, shape name, node chain
    // (root -> owning node), material index; plus the model's source path and
    // content hash (empty unless loaded as an interior).
    m.def("model_identity",
          [](scenegraph::InstanceId id) -> py::object {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return py::none();
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr) return py::none();
              std::vector<int> owner(model->meshes.size(), -1);
              for (std::size_t n = 0; n < model->nodes.size(); ++n)
                  for (int mi : model->nodes[n].meshes)
                      if (mi >= 0 && mi < static_cast<int>(owner.size()))
                          owner[mi] = static_cast<int>(n);
              py::list meshes;
              for (std::size_t i = 0; i < model->meshes.size(); ++i) {
                  const auto& mesh = model->meshes[i];
                  std::vector<std::string> chain;
                  for (int n = owner[i]; n >= 0 &&
                       n < static_cast<int>(model->nodes.size());
                       n = model->nodes[n].parent_index) {
                      chain.push_back(model->nodes[n].name);
                      if (chain.size() > model->nodes.size()) break;  // cycle guard
                  }
                  std::reverse(chain.begin(), chain.end());
                  py::dict d;
                  d["mesh"] = static_cast<int>(i);
                  d["block"] = mesh.source_block();
                  d["name"] = mesh.shape_name();
                  d["node_chain"] = py::cast(chain);
                  d["material"] = mesh.material_index();
                  meshes.append(std::move(d));
              }
              py::dict out;
              out["source"] = model->source.string();
              out["content_hash"] = model->content_hash;
              out["meshes"] = std::move(meshes);
              return out;
          },
          py::arg("instance_id"),
          "{source, content_hash, meshes:[{mesh, block, name, node_chain, "
          "material}]} for an instance's model, or None for a stale id.");
```

(`<algorithm>` is already included in host_bindings.cc; add it if the build says otherwise.)

Add a stub `set_bridge_highlight` binding now so the test passes; Task 4 gives it its body:

```cpp
    m.def("set_bridge_highlight",
          [](py::object /*instance_id*/, int /*selected*/, int /*hover*/) {},
          py::arg("instance_id"), py::arg("selected"), py::arg("hover"),
          "Developer-only selection tint on the bridge (Task 4).");
```

- [ ] **Step 4: Implement the host_io wrappers**

In `engine/host_io.py`, after `ray_trace_mesh`:

```python
def ray_trace_mesh_pick(instance_id, origin, direction, max_dist,
                        exclude_meshes=()):
    """Bridge editor pick: ray_trace_mesh plus (mesh_index, triangle).

    World ray in, world hit out, like ray_trace_mesh. Triangles of
    `exclude_meshes` are never hit. Unlike ray_trace_mesh this never raises:
    the editor calls it every frame for the hover tint, so a stale id or a
    stale binary is just "no hit"."""
    fn = getattr(_h, "ray_trace_mesh_pick", None) if _h is not None else None
    if fn is None:
        return None
    t = _h.instance_translation(instance_id)
    rel = origin if t is None else _relative_to(t, origin)
    hit = fn(instance_id, rel, direction, max_dist, list(exclude_meshes))
    if hit is None:
        return None
    (px, py, pz), normal, dist, mesh, tri = hit
    if t is not None:
        px, py, pz = px + t[0], py + t[1], pz + t[2]
    return (px, py, pz), normal, dist, mesh, tri


def model_identity(instance_id):
    """{source, content_hash, meshes:[{mesh, block, name, node_chain,
    material}]} for an instance's model; None headless or for a stale id."""
    fn = getattr(_h, "model_identity", None) if _h is not None else None
    return None if fn is None else fn(instance_id)


def set_bridge_highlight(instance_id, selected, hover) -> None:
    """Developer-only selection tint on the bridge: `selected` / `hover` are
    mesh indices into the instance's model (-1 = none). No-op headless."""
    fn = getattr(_h, "set_bridge_highlight", None) if _h is not None else None
    if fn is not None:
        fn(instance_id, int(selected), int(hover))


def nif_shape_textures(abs_path) -> dict:
    """NIF block index -> texture basenames, from the parse-only nif_shapes
    binding. {} headless, for a missing file, or on a parse failure."""
    fn = getattr(_h, "nif_shapes", None) if _h is not None else None
    if fn is None:
        return {}
    shapes = fn(str(abs_path))
    if not shapes:
        return {}
    return {int(s["block"]): list(s["textures"]) for s in shapes}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cmake --build build -j && uv run pytest tests/host/test_bridge_editor_bindings.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc engine/host_io.py tests/host/test_bridge_editor_bindings.py
git commit -m "feat(host): bridge editor pick + model identity bindings and host_io wrappers"
```

---

### Task 4: Developer-only selection tint in the bridge pass

**Files:**
- Modify: `native/src/renderer/include/renderer/bridge_pass.h` (public setter after `set_debug_view`; private state after `debug_view_`)
- Modify: `native/src/renderer/bridge_pass.cc` (`draw_mesh` signature :110-127; sub-pass A lambda :285-294; set `u_highlight_time` beside `u_debug_view` :244)
- Modify: `native/src/renderer/shaders/bridge.frag`
- Modify: `native/src/host/host_bindings.cc` (replace the Task 3 stub `set_bridge_highlight`)
- Create: `native/tests/renderer/bridge_highlight_test.cc`; Modify: `native/tests/renderer/CMakeLists.txt` (add after `bridge_ao_test.cc`)

**Interfaces:**
- Consumes: Task 3's binding name `set_bridge_highlight(instance_id, selected, hover)`.
- Produces: `void renderer::BridgePass::set_highlight(unsigned long long model_handle, int selected_mesh, int hover_mesh)`; `void renderer::BridgePass::clear_highlight()`. Shader uniforms `int u_highlight` (0 none, 1 hover, 2 selected) and `float u_highlight_time` (seconds).

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/bridge_highlight_test.cc` — reuse the `bridge_ao_test.cc` corner fixture verbatim for `append_quad`, `make_corner`, `corner_camera`, `lookup_fn` (copy them into this file's anonymous namespace), then:

```cpp
// native/tests/renderer/bridge_highlight_test.cc
//
// Bridge editor selection tint (spec 2026-10-08-bridge-emitters §4): the
// selected mesh of the selected model is tinted toward cyan, a hovered one
// faintly, every other draw untouched. Skips cleanly without a GL context.
// (includes: as bridge_ao_test.cc)

class BridgeHighlightFrame : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<renderer::BridgePass> pass;
    std::unique_ptr<assets::Model> model;
    renderer::HdrTarget target;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kWin, kWin, "bridge-highlight-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        pass = std::make_unique<renderer::BridgePass>();
        pass->set_ao_enabled(false);
        model = make_corner();
    }

    /// Mean RGB over a 9x9 block centred on the open floor.
    glm::vec3 render_floor() {
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model.get()));
        world.set_world_transform(iid, glm::mat4(1.0f));
        world.set_pass(iid, scenegraph::Pass::Bridge);
        const scenegraph::Camera cam = corner_camera(kWin, kWin);
        renderer::Lighting lighting;
        lighting.ambient = {0.6f, 0.6f, 0.6f};
        target.resize(kWin, kWin);
        target.bind();
        glViewport(0, 0, kWin, kWin);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        pass->render(world, cam, *p, lookup_fn, lighting, scenegraph::Pass::Bridge, 0);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
        std::vector<float> px(static_cast<std::size_t>(kWin) * kWin * 4);
        glReadPixels(0, 0, kWin, kWin, GL_RGBA, GL_FLOAT, px.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        const glm::vec4 clip = cam.proj_matrix() * cam.view_matrix() *
                               glm::vec4(70.0f, 0.0f, 0.0f, 1.0f);
        const glm::vec2 ndc = glm::vec2(clip) / clip.w;
        const int cx = static_cast<int>((ndc.x * 0.5f + 0.5f) * kWin);
        const int cy = static_cast<int>((ndc.y * 0.5f + 0.5f) * kWin);
        glm::vec3 sum(0.0f);
        int n = 0;
        for (int y = cy - 4; y <= cy + 4; ++y)
            for (int x = cx - 4; x <= cx + 4; ++x) {
                const std::size_t i = (static_cast<std::size_t>(y) * kWin + x) * 4;
                sum += glm::vec3(px[i], px[i + 1], px[i + 2]);
                ++n;
            }
        return sum / static_cast<float>(n);
    }

    unsigned long long handle() const {
        return reinterpret_cast<unsigned long long>(model.get());
    }
};

}  // namespace

TEST_F(BridgeHighlightFrame, NoHighlightIsTheLitColour) {
    const glm::vec3 plain = render_floor();
    pass->set_highlight(handle(), -1, -1);
    const glm::vec3 none = render_floor();
    EXPECT_EQ(plain, none);
}

TEST_F(BridgeHighlightFrame, SelectedMeshIsTintedTowardCyan) {
    const glm::vec3 plain = render_floor();
    pass->set_highlight(handle(), 0, -1);
    const glm::vec3 sel = render_floor();
    EXPECT_GT(sel.b - sel.r, plain.b - plain.r + 0.05f);
}

TEST_F(BridgeHighlightFrame, HoverIsFainterThanSelection) {
    const glm::vec3 plain = render_floor();
    pass->set_highlight(handle(), -1, 0);
    const glm::vec3 hov = render_floor();
    pass->set_highlight(handle(), 0, -1);
    const glm::vec3 sel = render_floor();
    EXPECT_GT(hov.b - hov.r, plain.b - plain.r + 0.01f);
    EXPECT_LT(hov.b - hov.r, sel.b - sel.r);
}

TEST_F(BridgeHighlightFrame, AnotherModelsMeshIndexDoesNotTint) {
    const glm::vec3 plain = render_floor();
    pass->set_highlight(handle() + 1, 0, 0);   // a different model handle
    EXPECT_EQ(render_floor(), plain);
    pass->clear_highlight();
    EXPECT_EQ(render_floor(), plain);
}
```

Add `bridge_highlight_test.cc` to `native/tests/renderer/CMakeLists.txt` on the line after `bridge_ao_test.cc`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j 2>&1 | tail -5`
Expected: compile FAIL — `no member named 'set_highlight' in 'renderer::BridgePass'`.

- [ ] **Step 3: Implement**

`bridge_pass.h`, public after `debug_view()`:

```cpp
    /// Developer-only bridge editor selection tint (spec
    /// 2026-10-08-bridge-emitters §4): mesh `selected_mesh` of the model
    /// `model_handle` pulses cyan, `hover_mesh` gets a faint tint. -1 = none.
    /// Mesh indices are into Model::meshes. Default (none) is byte-identical.
    void set_highlight(unsigned long long model_handle, int selected_mesh,
                       int hover_mesh) {
        highlight_model_ = model_handle;
        highlight_selected_ = selected_mesh;
        highlight_hover_ = hover_mesh;
    }
    void clear_highlight() { set_highlight(0, -1, -1); }
```

private, after `debug_view_`:

```cpp
    unsigned long long highlight_model_ = 0;
    int                highlight_selected_ = -1;
    int                highlight_hover_ = -1;
```

`bridge_pass.cc`:
- `draw_mesh` gains a trailing `int highlight = 0` parameter and, next to `u_mesh_id`, sets `shader.set_int("u_highlight", highlight);` and `shader.set_float("u_highlight_time", static_cast<float>(wall_time));` (`wall_time` is draw_mesh's existing parameter; render() passes `t = wall_time_`).
- In the sub-pass A lambda (:285-294), compute the flag and pass it:

```cpp
            int hl = 0;
            if (highlight_model_ != 0 && mh == highlight_model_) {
                const int mi = static_cast<int>(&mesh - m.meshes.data());
                if (mi == highlight_selected_) hl = 2;
                else if (mi == highlight_hover_) hl = 1;
            }
            draw_mesh(m, mesh, mat, base_shader, w, white, t, ov, flip,
                      viewscreen_brightness_, viewscreen_flash_,
                      /*face_blend=*/false, /*face_a=*/0u, /*face_b=*/0u,
                      /*face_mix=*/0.0f, mesh_id_counter++, hl);
```

  The skinned sub-pass call (:342) keeps the default 0.

`bridge.frag` — uniforms beside `u_mesh_id`:

```glsl
// Developer-only bridge editor selection tint (spec
// 2026-10-08-bridge-emitters §4): 0 none (production), 1 hover, 2 selected.
uniform int   u_highlight;
uniform float u_highlight_time;
```

helper before `main()`:

```glsl
vec3 apply_highlight(vec3 c) {
    if (u_highlight == 0) return c;
    float a = (u_highlight == 2)
        ? 0.35 + 0.15 * sin(u_highlight_time * 6.2831853)
        : 0.15;
    return mix(c, vec3(0.2, 0.9, 1.0), a);
}
```

In `main()`: in the `u_unlit` branch replace `FragColor = vec4(col, 1.0);` with `FragColor = vec4(apply_highlight(col), 1.0);`; at the end of the lit path likewise `FragColor = vec4(apply_highlight(col), 1.0);`. Debug views and the normal pre-pass are untouched.

`host_bindings.cc` — replace the Task 3 stub with:

```cpp
    m.def("set_bridge_highlight",
          [](py::object instance_id, int selected, int hover) {
              if (!dauntless::is_developer_mode() || !g_bridge_pass) return;
              if (instance_id.is_none()) { g_bridge_pass->clear_highlight(); return; }
              auto* inst = g_world.get(instance_id.cast<scenegraph::InstanceId>());
              if (inst == nullptr) { g_bridge_pass->clear_highlight(); return; }
              g_bridge_pass->set_highlight(inst->model_handle, selected, hover);
          },
          py::arg("instance_id"), py::arg("selected"), py::arg("hover"),
          "Developer-only bridge editor selection tint: mesh indices into the "
          "instance's model, -1 = none; None clears. No-op without --developer.");
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cmake --build build -j && ctest --test-dir build -R "BridgeHighlightFrame|BridgeAoFrame|BridgePass" --output-on-failure && uv run pytest tests/host/test_bridge_editor_bindings.py -v`
Expected: PASS (AO and bridge-pass tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/bridge_pass.h native/src/renderer/bridge_pass.cc native/src/renderer/shaders/bridge.frag native/src/host/host_bindings.cc native/tests/renderer/bridge_highlight_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): developer-only bridge selection tint"
```

---

### Task 5: Fly camera

**Files:**
- Create: `engine/bridge_editor/__init__.py`, `engine/bridge_editor/fly_camera.py`
- Test: `tests/unit/test_bridge_fly_camera.py`

**Interfaces:**
- Produces: `class FlyCamera` with `FlyCamera.from_pose(eye, target) -> FlyCamera`, `.look(dx, dy) -> None`, `.move(dt, forward, strafe, lift, fast=False, slow=False) -> None` (axes are -1/0/+1), `.forward() -> Vec3`, `.right() -> Vec3`, `.pose() -> (eye, target, up, fov_y_rad)`, attribute `.eye`. Module constants `FOV_Y_RAD`, `BASE_SPEED`, `FAST_MULT`, `SLOW_MULT`, `SENSITIVITY`, `PITCH_LIMIT_RAD`, `UP`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bridge_fly_camera.py`:

```python
"""Bridge editor fly camera (spec 2026-10-08-bridge-emitters §4). Conventions
match _BridgeCamera: bridge up +Z, forward at yaw 0 is +Y, +dx looks right,
+dy (screen down) looks down."""
import math

import pytest

from engine.bridge_editor import fly_camera as fc


def approx(v, w, tol=1e-6):
    return all(abs(a - b) < tol for a, b in zip(v, w))


def test_from_pose_round_trips_the_look_direction():
    cam = fc.FlyCamera.from_pose(eye=(10, 20, 50), target=(10, 10, 50))
    eye, target, up, fov = cam.pose()
    assert approx(eye, (10, 20, 50))
    assert approx(target, (10, 19, 50))          # unit step along -Y
    assert up == fc.UP
    assert fov == fc.FOV_Y_RAD


def test_from_pose_keeps_pitch():
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 1))
    assert approx(cam.forward(), (0, math.sqrt(0.5), math.sqrt(0.5)))


def test_degenerate_pose_looks_forward():
    cam = fc.FlyCamera.from_pose(eye=(1, 2, 3), target=(1, 2, 3))
    assert approx(cam.forward(), (0, 1, 0))


def test_right_is_forward_cross_up():
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 0))
    assert approx(cam.right(), (1, 0, 0))


def test_positive_dx_looks_right_and_positive_dy_looks_down():
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 0))
    cam.look(100, 0)
    assert cam.forward()[0] > 0
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 0))
    cam.look(0, 100)
    assert cam.forward()[2] < 0


def test_pitch_clamps():
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 0))
    cam.look(0, -1e6)
    assert math.asin(cam.forward()[2]) == pytest.approx(fc.PITCH_LIMIT_RAD)


def test_move_forward_strafe_and_lift():
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 0))
    cam.move(1.0, forward=1, strafe=0, lift=0)
    assert approx(cam.eye, (0, fc.BASE_SPEED, 0))
    cam.move(1.0, forward=0, strafe=1, lift=0)
    assert approx(cam.eye, (fc.BASE_SPEED, fc.BASE_SPEED, 0))
    cam.move(1.0, forward=0, strafe=0, lift=-1)            # Q = down
    assert approx(cam.eye, (fc.BASE_SPEED, fc.BASE_SPEED, -fc.BASE_SPEED))


def test_fast_and_slow_scale_speed():
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 0))
    cam.move(1.0, forward=1, strafe=0, lift=0, fast=True)
    assert cam.eye[1] == pytest.approx(fc.BASE_SPEED * fc.FAST_MULT)
    cam = fc.FlyCamera.from_pose(eye=(0, 0, 0), target=(0, 1, 0))
    cam.move(1.0, forward=1, strafe=0, lift=0, slow=True)
    assert cam.eye[1] == pytest.approx(fc.BASE_SPEED * fc.SLOW_MULT)


def test_zero_dt_does_not_move():
    cam = fc.FlyCamera.from_pose(eye=(1, 2, 3), target=(1, 3, 3))
    cam.move(0.0, forward=1, strafe=1, lift=1, fast=True)
    assert approx(cam.eye, (1, 2, 3))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_fly_camera.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.bridge_editor'`.

- [ ] **Step 3: Implement**

`engine/bridge_editor/__init__.py`:

```python
"""Developer-only bridge editor: selection, materials and (later) emitters.
Spec: docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md."""
```

`engine/bridge_editor/fly_camera.py`:

```python
"""Free fly camera for the bridge editor (spec 2026-10-08-bridge-emitters §4).

Hold RMB to look; W/S forward/back, A/D strafe, Q/E down/up; Shift fast, Alt
slow. Pure: the panel feeds it mouse deltas and key axes. Conventions match
host_loop._BridgeCamera -- bridge-local units, up +Z, forward at yaw 0 is +Y,
+dx looks right, +dy (screen down) looks down."""
import math

FOV_Y_RAD = math.radians(45.0)        # _BridgeCamera.FOV_Y_RAD
BASE_SPEED = 60.0                     # bridge units / s; a DBridge is ~400 across
FAST_MULT = 4.0
SLOW_MULT = 0.25
SENSITIVITY = 0.0015                  # rad per pixel, _BridgeCamera's
PITCH_LIMIT_RAD = math.radians(85.0)
UP = (0.0, 0.0, 1.0)


class FlyCamera:
    def __init__(self, eye, yaw, pitch):
        self.eye = (float(eye[0]), float(eye[1]), float(eye[2]))
        self.yaw = float(yaw)
        self.pitch = max(-PITCH_LIMIT_RAD, min(PITCH_LIMIT_RAD, float(pitch)))

    @classmethod
    def from_pose(cls, eye, target):
        fx, fy, fz = (target[0] - eye[0], target[1] - eye[1], target[2] - eye[2])
        n = math.sqrt(fx * fx + fy * fy + fz * fz)
        if n < 1e-9:
            return cls(eye, 0.0, 0.0)
        fx, fy, fz = fx / n, fy / n, fz / n
        pitch = math.asin(max(-1.0, min(1.0, fz)))
        yaw = math.atan2(-fx, fy)
        return cls(eye, yaw, pitch)

    def forward(self):
        cp = math.cos(self.pitch)
        return (-math.sin(self.yaw) * cp, math.cos(self.yaw) * cp,
                math.sin(self.pitch))

    def right(self):
        # forward x UP, horizontal: (cos yaw, sin yaw, 0).
        return (math.cos(self.yaw), math.sin(self.yaw), 0.0)

    def look(self, dx, dy):
        self.yaw -= dx * SENSITIVITY
        self.pitch -= dy * SENSITIVITY
        self.pitch = max(-PITCH_LIMIT_RAD, min(PITCH_LIMIT_RAD, self.pitch))

    def move(self, dt, forward, strafe, lift, fast=False, slow=False):
        if dt <= 0.0:
            return
        speed = BASE_SPEED * (FAST_MULT if fast else 1.0) * (SLOW_MULT if slow else 1.0)
        f, r = self.forward(), self.right()
        step = speed * dt
        self.eye = tuple(
            self.eye[i] + (f[i] * forward + r[i] * strafe + UP[i] * lift) * step
            for i in range(3))

    def pose(self):
        f = self.forward()
        target = (self.eye[0] + f[0], self.eye[1] + f[1], self.eye[2] + f[2])
        return self.eye, target, UP, FOV_Y_RAD
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_fly_camera.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/__init__.py engine/bridge_editor/fly_camera.py tests/unit/test_bridge_fly_camera.py
git commit -m "feat(bridge-editor): fly camera"
```

---

### Task 6: Picking and shape identity resolution

**Files:**
- Create: `engine/bridge_editor/picking.py`
- Test: `tests/unit/test_bridge_picking.py`

**Interfaces:**
- Consumes: the shapes of Task 3 (`model_identity` dict, `ray_trace_mesh_pick` 5-tuple, `nif_shape_textures` dict); `engine.manual_aim.cursor_ray(cursor_xy, viewport, cam)` and `AimCamera(eye, target, up, fov_y_rad, near, far)`.
- Produces:
  - `@dataclass(frozen=True) class ShapeIdentity: mesh: int; block: int; name: str; node_chain: tuple; textures: tuple; content_hash: str` with property `key -> str` (`f"{block}:{name}"`).
  - `MAX_PICK_DIST = 2000.0`, `NEAR = 1.0`, `FAR = 800.0`.
  - `pick_mesh(trace, cursor_xy, viewport, pose, exclude=()) -> Optional[int]` — `trace(origin, direction, max_dist, exclude) -> 5-tuple | None`; `pose = (eye, target, up, fov)`.
  - `identity_for(model_info: dict, mesh: int, textures_by_block: dict) -> Optional[ShapeIdentity]`.
  - `class PickCycle` with `.next_exclusion(cursor_xy, current_mesh, slop_px=4.0) -> tuple` and `.reset()` — Alt+click "surface behind": at the same spot, excludes every mesh already picked there; anywhere else, starts again.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bridge_picking.py`:

```python
"""Bridge editor picking (spec 2026-10-08-bridge-emitters §4)."""
from engine.bridge_editor import picking

POSE = ((0.0, 0.0, 50.0), (0.0, 1.0, 50.0), (0.0, 0.0, 1.0), 0.785398)

INFO = {
    "source": "/abs/Dbridge.NIF",
    "content_hash": "0123456789abcdef",
    "meshes": [
        {"mesh": 0, "block": 3, "name": "floor", "node_chain": ["Scene Root"], "material": 0},
        {"mesh": 1, "block": 7, "name": "redalertpanel",
         "node_chain": ["Scene Root", "Red On GlowAlpha"], "material": 1},
    ],
}


def test_pick_traces_the_ray_through_the_cursor():
    seen = {}

    def trace(origin, direction, max_dist, exclude):
        seen.update(origin=origin, direction=direction, max_dist=max_dist,
                    exclude=tuple(exclude))
        return ((0, 10, 50), (0, -1, 0), 10.0, 1, 0)

    assert picking.pick_mesh(trace, (400, 300), (800, 600), POSE) == 1
    assert seen["origin"] == (0.0, 0.0, 50.0)
    dx, dy, dz = seen["direction"]
    assert abs(dx) < 1e-6 and dy > 0.999 and abs(dz) < 1e-6   # screen centre = forward
    assert seen["max_dist"] == picking.MAX_PICK_DIST
    assert seen["exclude"] == ()


def test_pick_miss_is_none():
    assert picking.pick_mesh(lambda *a: None, (1, 1), (800, 600), POSE) is None


def test_pick_with_a_degenerate_viewport_is_none():
    assert picking.pick_mesh(lambda *a: 1 / 0, (1, 1), (0, 0), POSE) is None


def test_pick_forwards_the_exclusion():
    got = []
    picking.pick_mesh(lambda o, d, m, ex: got.append(tuple(ex)) or None,
                      (1, 1), (800, 600), POSE, exclude=(4, 5))
    assert got == [(4, 5)]


def test_identity_for_resolves_block_name_chain_textures_and_hash():
    ident = picking.identity_for(INFO, 1, {7: ["redalertpanel.tga"]})
    assert ident.key == "7:redalertpanel"
    assert ident.node_chain == ("Scene Root", "Red On GlowAlpha")
    assert ident.textures == ("redalertpanel.tga",)
    assert ident.content_hash == "0123456789abcdef"


def test_identity_for_unknown_mesh_or_block_is_none():
    assert picking.identity_for(INFO, 9, {}) is None
    info = {"source": "", "content_hash": "", "meshes": [
        {"mesh": 0, "block": -1, "name": "x", "node_chain": [], "material": 0}]}
    assert picking.identity_for(info, 0, {}) is None


def test_pick_cycle_excludes_previous_picks_at_the_same_spot():
    cyc = picking.PickCycle()
    assert cyc.next_exclusion((100, 100), current_mesh=1) == (1,)
    assert cyc.next_exclusion((101, 100), current_mesh=0) == (1, 0)
    assert cyc.next_exclusion((300, 100), current_mesh=2) == (2,)   # moved: restart
    cyc.reset()
    assert cyc.next_exclusion((300, 100), current_mesh=2) == (2,)


def test_pick_cycle_without_a_current_selection_excludes_nothing():
    assert picking.PickCycle().next_exclusion((5, 5), current_mesh=-1) == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_picking.py -v`
Expected: FAIL — `ImportError: cannot import name 'picking'`.

- [ ] **Step 3: Implement**

`engine/bridge_editor/picking.py`:

```python
"""Bridge editor picking and shape identity (spec 2026-10-08-bridge-emitters §4).

A pick is the ray through the cursor of the camera ACTUALLY drawn (the fly
camera while the editor is open), traced against the bridge instance. A shape's
identity across launches is (NIF content hash, block index, shape name)."""
from dataclasses import dataclass
from typing import Optional

from engine.manual_aim import AimCamera, cursor_ray

MAX_PICK_DIST = 2000.0
NEAR = 1.0      # _BridgeCamera.NEAR
FAR = 800.0     # _BridgeCamera.FAR


@dataclass(frozen=True)
class ShapeIdentity:
    mesh: int
    block: int
    name: str
    node_chain: tuple
    textures: tuple
    content_hash: str

    @property
    def key(self) -> str:
        return f"{self.block}:{self.name}"


def pick_mesh(trace, cursor_xy, viewport, pose, exclude=()) -> Optional[int]:
    """Mesh index under `cursor_xy` (framebuffer pixels, top-left origin) for
    the camera `pose` = (eye, target, up, fov_y_rad), or None."""
    if viewport[0] <= 0 or viewport[1] <= 0:
        return None
    eye, target, up, fov = pose
    ray = cursor_ray(cursor_xy, viewport, AimCamera(eye, target, up, fov, NEAR, FAR))
    if ray is None:
        return None
    origin, direction = ray
    hit = trace(origin, direction, MAX_PICK_DIST, tuple(exclude))
    if hit is None:
        return None
    return int(hit[3])


def identity_for(model_info, mesh, textures_by_block) -> Optional[ShapeIdentity]:
    """Resolve a mesh index to its ShapeIdentity; None if the mesh is unknown
    or was not built from a NIF shape (block < 0)."""
    for m in model_info.get("meshes", ()):
        if m["mesh"] != mesh:
            continue
        if m["block"] < 0:
            return None
        return ShapeIdentity(
            mesh=int(mesh), block=int(m["block"]), name=str(m["name"]),
            node_chain=tuple(m["node_chain"]),
            textures=tuple(textures_by_block.get(m["block"], ())),
            content_hash=str(model_info.get("content_hash", "")))
    return None


class PickCycle:
    """Alt+click = the surface behind: at the same spot, exclude every mesh
    already picked there; a click anywhere else starts again."""

    def __init__(self):
        self._xy = None
        self._excluded = ()

    def reset(self):
        self._xy = None
        self._excluded = ()

    def next_exclusion(self, cursor_xy, current_mesh, slop_px=4.0) -> tuple:
        if current_mesh < 0:
            self.reset()
            return ()
        same = (self._xy is not None
                and abs(cursor_xy[0] - self._xy[0]) <= slop_px
                and abs(cursor_xy[1] - self._xy[1]) <= slop_px)
        if not same:
            self._excluded = ()
        self._xy = (cursor_xy[0], cursor_xy[1])
        if current_mesh not in self._excluded:
            self._excluded = self._excluded + (current_mesh,)
        return self._excluded
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_picking.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/picking.py tests/unit/test_bridge_picking.py
git commit -m "feat(bridge-editor): cursor picking and stable shape identity"
```

---

### Task 7: Bridge lighting document — validation, lookup, shape matching

**Files:**
- Create: `engine/bridge_editor/lighting_doc.py`, `native/assets/bridge_lighting/.gitkeep`
- Test: `tests/unit/test_bridge_lighting_doc.py`

**Interfaces:**
- Consumes: `engine.paths.project_asset_root()`, `engine.paths.game_asset_dirs(rel)`.
- Produces:
  - `FORMAT = 1`, `MOD_REL = "dauntless/bridge_lighting"`, `class BridgeLightingError(ValueError)`.
  - `project_dir() -> Path`, `candidate_paths(content_hash) -> list[Path]`, `find(content_hash) -> Optional[Path]`.
  - `empty_doc(source: str) -> dict`.
  - `validate(doc: dict) -> dict` (returns `doc`; raises `BridgeLightingError` naming the JSON path of the fault).
  - `@dataclass class LoadResult: doc: dict; path: Optional[Path]; error: Optional[str]` and `load(content_hash, source) -> LoadResult`.
  - `match_shapes(doc, meshes) -> tuple[dict, list]` — `meshes` is `model_identity()["meshes"]`; returns (`{shape_key: mesh_index}`, `[warning str, ...]`).
  - `shape_entry(doc, block, name) -> dict` (get-or-create `doc["shapes"][f"{block}:{name}"]` with `block`/`name`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bridge_lighting_doc.py`:

```python
"""Per-bridge lighting document (spec 2026-10-08-bridge-emitters §7)."""
import json

import pytest

from engine.bridge_editor import lighting_doc as ld

HASH = "0123456789abcdef"


def full_doc():
    return {
        "format": 1,
        "source": "data/Models/Sets/DBridge/DBridge.nif",
        "profiles": {
            "red_bar": {
                "fade_s": 0.5,
                "green": {"tint": [1, 0.2, 0.1], "level": 0},
                "yellow": {"tint": [1, 0.6, 0.1], "level": 2,
                           "wave": {"shape": "sine", "period_s": 2.0, "min": 0.3}},
                "red": {"tint": [1, 0.1, 0.05], "level": 4,
                        "wave": {"shape": "square", "period_s": 1.0,
                                 "duty": 0.5, "soft": 0.1}},
            }
        },
        "shapes": {
            "137:wall inset slot left": {
                "block": 137, "name": "wall inset slot left",
                "material": {"roughness": 0.4, "metalness": 0.0},
                "emitter": {
                    "profile": "red_bar", "phase": 0.0,
                    "glow": {"src": "flat", "mask": "whole", "scale": 1.0},
                    "light": {"position": [191, 0, 40], "direction": [-1, 0, 0],
                              "inner_deg": 30, "outer_deg": 60, "range": 120,
                              "intensity": 1.0, "light_scale": 1.0},
                },
            }
        },
    }


def test_the_spec_example_validates():
    assert ld.validate(full_doc())["format"] == 1


def test_empty_doc_validates():
    assert ld.validate(ld.empty_doc("x.nif"))["shapes"] == {}


@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d.update(extra=1), "extra"),
    (lambda d: d.update(format=2), "format"),
    (lambda d: d["shapes"]["137:wall inset slot left"].update(colour=1), "colour"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["material"].update(roughness=1.5), "roughness"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["material"].update(shine=1), "shine"),
    (lambda d: d["shapes"]["137:wall inset slot left"].update(name="other"), "key"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["emitter"].update(profile="nope"), "nope"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["emitter"]["glow"].update(mask="map"), "map"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["emitter"]["glow"].update(src="neon"), "src"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["emitter"]["light"].update(direction=[0, 0, 0]), "direction"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["emitter"]["light"].update(inner_deg=70), "inner_deg"),
    (lambda d: d["shapes"]["137:wall inset slot left"]["emitter"]["light"].update(range=0), "range"),
    (lambda d: d["profiles"]["red_bar"]["red"]["wave"].update(shape="saw"), "shape"),
    (lambda d: d["profiles"]["red_bar"]["yellow"]["wave"].update(duty=0.5), "duty"),
    (lambda d: d["profiles"]["red_bar"]["red"]["wave"].pop("period_s"), "period_s"),
    (lambda d: d["profiles"]["red_bar"]["green"].update(tint=[1, 1]), "tint"),
    (lambda d: d["profiles"]["red_bar"].update(blue={}), "blue"),
])
def test_invalid_documents_are_rejected_naming_the_fault(mutate, fragment):
    d = full_doc()
    mutate(d)
    with pytest.raises(ld.BridgeLightingError, match=fragment):
        ld.validate(d)


def test_booleans_are_not_numbers():
    d = full_doc()
    d["shapes"]["137:wall inset slot left"]["material"]["roughness"] = True
    with pytest.raises(ld.BridgeLightingError, match="roughness"):
        ld.validate(d)


def test_lookup_prefers_mod_dirs_then_project(tmp_path, monkeypatch):
    mod = tmp_path / "mod" / "dauntless" / "bridge_lighting"
    proj = tmp_path / "proj"
    monkeypatch.setattr(ld.paths, "game_asset_dirs",
                        lambda rel: [tmp_path / "mod" / rel, tmp_path / "stock" / rel])
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: proj)
    assert ld.candidate_paths(HASH) == [
        mod / f"{HASH}.json", proj / "bridge_lighting" / f"{HASH}.json"]
    assert ld.find(HASH) is None
    (proj / "bridge_lighting").mkdir(parents=True)
    (proj / "bridge_lighting" / f"{HASH}.json").write_text("{}")
    assert ld.find(HASH) == proj / "bridge_lighting" / f"{HASH}.json"
    mod.mkdir(parents=True)
    (mod / f"{HASH}.json").write_text("{}")
    assert ld.find(HASH) == mod / f"{HASH}.json"


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ld.paths, "game_asset_dirs", lambda rel: [tmp_path / "stock" / rel])
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: tmp_path)
    (tmp_path / "bridge_lighting").mkdir()
    return tmp_path / "bridge_lighting" / f"{HASH}.json"


def test_load_without_a_file_is_an_empty_doc(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = ld.load(HASH, "x.nif")
    assert r.doc == ld.empty_doc("x.nif") and r.path is None and r.error is None


def test_load_reads_a_valid_file(tmp_path, monkeypatch):
    p = _isolate(tmp_path, monkeypatch)
    p.write_text(json.dumps(full_doc()))
    r = ld.load(HASH, "x.nif")
    assert r.error is None and r.path == p
    assert "137:wall inset slot left" in r.doc["shapes"]


@pytest.mark.parametrize("text", ["{not json", json.dumps({"format": 1, "shapes": {}, "bogus": 1})])
def test_load_reports_a_bad_file_and_keeps_its_path(tmp_path, monkeypatch, text):
    p = _isolate(tmp_path, monkeypatch)
    p.write_text(text)
    r = ld.load(HASH, "x.nif")
    assert r.error and r.path == p
    assert r.doc == ld.empty_doc("x.nif")


MESHES = [
    {"mesh": 0, "block": 137, "name": "wall inset slot left", "node_chain": [], "material": 0},
    {"mesh": 1, "block": 140, "name": "renamed", "node_chain": [], "material": 0},
]


def test_match_shapes_maps_keys_to_meshes():
    matched, warnings = ld.match_shapes(full_doc(), MESHES)
    assert matched == {"137:wall inset slot left": 0}
    assert warnings == []


def test_match_shapes_skips_a_name_mismatch():
    d = ld.empty_doc("x")
    ld.shape_entry(d, 140, "original")["material"] = {"roughness": 0.5}
    matched, warnings = ld.match_shapes(d, MESHES)
    assert matched == {}
    assert len(warnings) == 1 and "140" in warnings[0] and "renamed" in warnings[0]


def test_match_shapes_warns_on_a_missing_block():
    d = ld.empty_doc("x")
    ld.shape_entry(d, 999, "ghost")
    matched, warnings = ld.match_shapes(d, MESHES)
    assert matched == {} and "999" in warnings[0]


def test_shape_entry_creates_once():
    d = ld.empty_doc("x")
    e = ld.shape_entry(d, 5, "a")
    assert e == {"block": 5, "name": "a"}
    assert ld.shape_entry(d, 5, "a") is e
    ld.validate(d)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_lighting_doc.py -v`
Expected: FAIL — `ImportError: cannot import name 'lighting_doc'`.

- [ ] **Step 3: Implement**

`engine/bridge_editor/lighting_doc.py`:

```python
"""Per-bridge lighting document (spec 2026-10-08-bridge-emitters §7).

One JSON file per bridge NIF, keyed by the NIF's content hash, holding
per-shape `material` and `emitter` sections plus shared `profiles`. Only
references and parameters -- never BC geometry. Unknown keys are REJECTED:
a typo must fail loudly, not be silently ignored."""
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from engine import paths

FORMAT = 1
MOD_REL = "dauntless/bridge_lighting"

_STATES = ("green", "yellow", "red")


class BridgeLightingError(ValueError):
    pass


def project_dir() -> Path:
    return paths.project_asset_root() / "bridge_lighting"


def candidate_paths(content_hash) -> list:
    """Mod and replacement dirs first, then the project. The stock install
    (game_asset_dirs' LAST entry) is never searched -- it holds no such data."""
    mod_dirs = paths.game_asset_dirs(MOD_REL)[:-1]
    return ([Path(d) / f"{content_hash}.json" for d in mod_dirs]
            + [project_dir() / f"{content_hash}.json"])


def find(content_hash) -> Optional[Path]:
    for p in candidate_paths(content_hash):
        if p.is_file():
            return p
    return None


def empty_doc(source) -> dict:
    return {"format": FORMAT, "source": str(source), "profiles": {}, "shapes": {}}


def shape_entry(doc, block, name) -> dict:
    key = f"{block}:{name}"
    entry = doc["shapes"].get(key)
    if entry is None:
        entry = {"block": int(block), "name": str(name)}
        doc["shapes"][key] = entry
    return entry


# ── validation ──────────────────────────────────────────────────────────────

def _fail(where, msg):
    raise BridgeLightingError(f"{where}: {msg}")


def _obj(v, where, allowed, required=()):
    if not isinstance(v, dict):
        _fail(where, "must be an object")
    for k in v:
        if k not in allowed:
            _fail(f"{where}.{k}", "unknown key")
    for k in required:
        if k not in v:
            _fail(f"{where}.{k}", "required")


def _num(v, where, lo=None, hi=None, lo_open=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        _fail(where, "must be a finite number")
    if lo is not None and (v <= lo if lo_open else v < lo):
        _fail(where, f"must be {'>' if lo_open else '>='} {lo}")
    if hi is not None and v > hi:
        _fail(where, f"must be <= {hi}")


def _vec3(v, where, lo=None):
    if not isinstance(v, list) or len(v) != 3:
        _fail(where, "must be a list of 3 numbers")
    for i, c in enumerate(v):
        _num(c, f"{where}[{i}]", lo=lo)


def _enum(v, where, options):
    if v not in options:
        _fail(where, f"must be one of {', '.join(options)}")


def _wave(w, where):
    _obj(w, where, {"shape", "period_s", "duty", "soft", "min"}, ("shape",))
    _enum(w["shape"], f"{where}.shape", ("steady", "sine", "square"))
    if w["shape"] != "steady":
        if "period_s" not in w:
            _fail(f"{where}.period_s", "required unless steady")
        _num(w["period_s"], f"{where}.period_s", lo=0, lo_open=True)
    for k in ("duty", "soft"):
        if k in w:
            if w["shape"] != "square":
                _fail(f"{where}.{k}", "only for square")
            _num(w[k], f"{where}.{k}", 0, 1)
    if "min" in w:
        _num(w["min"], f"{where}.min", 0, 1)


def _profile(p, where):
    _obj(p, where, {"fade_s", *_STATES})
    if "fade_s" in p:
        _num(p["fade_s"], f"{where}.fade_s", lo=0)
    for s in _STATES:
        if s in p:
            st = p[s]
            _obj(st, f"{where}.{s}", {"tint", "level", "wave"}, ("tint", "level"))
            _vec3(st["tint"], f"{where}.{s}.tint", lo=0)
            _num(st["level"], f"{where}.{s}.level", lo=0)
            if "wave" in st:
                _wave(st["wave"], f"{where}.{s}.wave")


def _glow(g, where):
    _obj(g, where, {"src", "mask", "scale", "luma_threshold", "luma_soft", "map"},
         ("src", "mask"))
    _enum(g["src"], f"{where}.src", ("texture", "flat"))
    _enum(g["mask"], f"{where}.mask", ("whole", "base_alpha", "luma", "map"))
    if "scale" in g:
        _num(g["scale"], f"{where}.scale", lo=0)
    for k in ("luma_threshold", "luma_soft"):
        if k in g:
            _num(g[k], f"{where}.{k}", 0, 1)
    if g["mask"] == "map" and not isinstance(g.get("map"), str):
        _fail(f"{where}.map", "required (a texture name) when mask is map")


def _light(l, where):
    _obj(l, where, {"position", "direction", "inner_deg", "outer_deg", "range",
                    "intensity", "light_scale"}, ("position", "direction"))
    _vec3(l["position"], f"{where}.position")
    _vec3(l["direction"], f"{where}.direction")
    if sum(c * c for c in l["direction"]) < 1e-12:
        _fail(f"{where}.direction", "must be non-zero")
    inner = l.get("inner_deg", 0.0)
    outer = l.get("outer_deg", 90.0)
    _num(inner, f"{where}.inner_deg", 0, 90)
    _num(outer, f"{where}.outer_deg", 0, 90)
    if inner > outer:
        _fail(f"{where}.inner_deg", "must be <= outer_deg")
    if "range" in l:
        _num(l["range"], f"{where}.range", lo=0, lo_open=True)
    for k in ("intensity", "light_scale"):
        if k in l:
            _num(l[k], f"{where}.{k}", lo=0)


def validate(doc) -> dict:
    _obj(doc, "$", {"format", "source", "profiles", "shapes"},
         ("format", "profiles", "shapes"))
    if doc["format"] != FORMAT:
        _fail("$.format", f"must be {FORMAT}")
    if "source" in doc and not isinstance(doc["source"], str):
        _fail("$.source", "must be a string")
    if not isinstance(doc["profiles"], dict):
        _fail("$.profiles", "must be an object")
    for name, p in doc["profiles"].items():
        _profile(p, f"$.profiles.{name}")
    if not isinstance(doc["shapes"], dict):
        _fail("$.shapes", "must be an object")
    for key, s in doc["shapes"].items():
        where = f"$.shapes.{key}"
        _obj(s, where, {"block", "name", "material", "emitter"}, ("block", "name"))
        if isinstance(s["block"], bool) or not isinstance(s["block"], int) or s["block"] < 0:
            _fail(f"{where}.block", "must be a non-negative integer")
        if not isinstance(s["name"], str):
            _fail(f"{where}.name", "must be a string")
        if key != f"{s['block']}:{s['name']}":
            _fail(where, "key must be '<block>:<name>'")
        if "material" in s:
            _obj(s["material"], f"{where}.material", {"roughness", "metalness"})
            for k, v in s["material"].items():
                _num(v, f"{where}.material.{k}", 0, 1)
        if "emitter" in s:
            e = s["emitter"]
            _obj(e, f"{where}.emitter", {"profile", "phase", "glow", "light"})
            if "profile" in e and e["profile"] not in doc["profiles"]:
                _fail(f"{where}.emitter.profile", f"no profile named {e['profile']!r}")
            if "phase" in e:
                _num(e["phase"], f"{where}.emitter.phase", 0, 1)
            if "glow" in e:
                _glow(e["glow"], f"{where}.emitter.glow")
            if "light" in e:
                _light(e["light"], f"{where}.emitter.light")
    return doc


# ── load + match ────────────────────────────────────────────────────────────

@dataclass
class LoadResult:
    doc: dict
    path: Optional[Path]
    error: Optional[str]


def load(content_hash, source) -> LoadResult:
    """The bridge's document, an empty one when no file exists, or -- when the
    file exists but is unreadable or invalid -- an empty one WITH the path and
    the error, so the editor can refuse to overwrite it."""
    path = find(content_hash)
    if path is None:
        return LoadResult(empty_doc(source), None, None)
    try:
        doc = validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:      # JSONDecodeError and BridgeLightingError are ValueErrors
        return LoadResult(empty_doc(source), path, f"{path.name}: {e}")
    return LoadResult(doc, path, None)


def match_shapes(doc, meshes):
    """{shape_key: mesh_index} for every entry whose block holds a shape of
    the same name; one warning per entry that does not -- never applied to a
    different shape."""
    by_block = {m["block"]: m for m in meshes if m["block"] >= 0}
    matched, warnings = {}, []
    for key, s in doc["shapes"].items():
        m = by_block.get(s["block"])
        if m is None:
            warnings.append(f"{key}: no shape at block {s['block']}; skipped")
        elif m["name"] != s["name"]:
            warnings.append(f"{key}: block {s['block']} is {m['name']!r}, "
                            f"file says {s['name']!r}; skipped")
        else:
            matched[key] = m["mesh"]
    return matched, warnings
```

Create the empty file `native/assets/bridge_lighting/.gitkeep`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_lighting_doc.py tests/unit/test_path_indirection.py -v`
Expected: PASS (the path guard stays green: no `game`/`sdk` segment, nothing captured at import).

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/lighting_doc.py native/assets/bridge_lighting/.gitkeep tests/unit/test_bridge_lighting_doc.py
git commit -m "feat(bridge-editor): per-bridge lighting document — schema, lookup, shape matching"
```

---

### Task 8: Deterministic atomic writer

**Files:**
- Create: `engine/bridge_editor/lighting_writer.py`
- Test: `tests/unit/test_bridge_lighting_writer.py`

**Interfaces:**
- Consumes: Task 7 `validate`, `project_dir`, `empty_doc`, `shape_entry`.
- Produces: `dumps(doc) -> str`; `target_path(found: Optional[Path], content_hash) -> Path`; `save(doc, path) -> None` (validates first; raises `BridgeLightingError` without touching the file on an invalid doc).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bridge_lighting_writer.py`:

```python
"""Bridge lighting writer (spec 2026-10-08-bridge-emitters §7): deterministic,
atomic, round-trip byte-identical."""
import json

import pytest

from engine.bridge_editor import lighting_doc as ld
from engine.bridge_editor import lighting_writer as lw


def doc():
    d = ld.empty_doc("data/Models/Sets/DBridge/DBridge.nif")
    ld.shape_entry(d, 12, "roof light")["material"] = {"roughness": 0.123456789, "metalness": 1}
    ld.shape_entry(d, 3, "floor")["material"] = {"roughness": 0.5}
    return d


def test_dumps_is_sorted_rounded_and_newline_terminated():
    text = lw.dumps(doc())
    assert text.endswith("\n")
    assert "0.123457" in text and "0.123456789" not in text
    assert text.index('"12:roof light"') > text.index('"3:floor"')   # sorted keys
    assert text.splitlines()[1].startswith("  ")                    # 2-space indent


def test_round_trip_is_byte_identical(tmp_path):
    p = tmp_path / "x.json"
    lw.save(doc(), p)
    first = p.read_text()
    lw.save(ld.validate(json.loads(first)), p)
    assert p.read_text() == first


def test_save_is_atomic_and_leaves_no_tmp(tmp_path):
    p = tmp_path / "sub" / "x.json"
    lw.save(doc(), p)
    assert p.is_file()
    assert [f.name for f in p.parent.iterdir()] == ["x.json"]


def test_save_refuses_an_invalid_doc_without_touching_the_file(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("original")
    bad = doc()
    bad["shapes"]["3:floor"]["material"]["roughness"] = 7
    with pytest.raises(ld.BridgeLightingError):
        lw.save(bad, p)
    assert p.read_text() == "original"


def test_target_path_keeps_where_it_was_found(tmp_path, monkeypatch):
    found = tmp_path / "mod" / "abc.json"
    assert lw.target_path(found, "abc") == found
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: tmp_path)
    assert lw.target_path(None, "abc") == tmp_path / "bridge_lighting" / "abc.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_lighting_writer.py -v`
Expected: FAIL — `ImportError: cannot import name 'lighting_writer'`.

- [ ] **Step 3: Implement**

`engine/bridge_editor/lighting_writer.py`:

```python
"""Deterministic, atomic writer for the per-bridge lighting document (spec
2026-10-08-bridge-emitters §7): sorted keys, floats rounded to 6 dp, 2-space
indent, trailing newline; written to `<path>.tmp` then os.replace'd, so a
crash never leaves half a file. load -> save is byte-identical."""
import json
import os
from pathlib import Path
from typing import Optional

from engine.bridge_editor import lighting_doc as ld

_DP = 6


def _norm(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        r = round(v, _DP)
        return int(r) if r.is_integer() else r
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    return v


def dumps(doc) -> str:
    return json.dumps(_norm(doc), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def target_path(found: Optional[Path], content_hash) -> Path:
    """Save where the file was found; a bridge with no file saves to the
    project directory (the decals_writer target rule)."""
    return found if found is not None else ld.project_dir() / f"{content_hash}.json"


def save(doc, path) -> None:
    ld.validate(doc)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dumps(doc), encoding="utf-8")
    os.replace(tmp, path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_lighting_writer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/lighting_writer.py tests/unit/test_bridge_lighting_writer.py
git commit -m "feat(bridge-editor): deterministic atomic lighting writer"
```

---

### Task 9: The Bridge Emitters panel

**Files:**
- Create: `engine/ui/bridge_emitters_panel.py`
- Create: `native/assets/ui-cef/js/bridge_emitters.js`, `native/assets/ui-cef/css/bridge_emitters.css`
- Modify: `native/assets/ui-cef/index.html` (stylesheet link beside `css/ai_inspector.css` :17; markup after the AI inspector `</section>` ~:174; script after `js/ai_inspector.js` :1084)
- Test: `tests/unit/test_bridge_emitters_panel.py`

**Interfaces:**
- Consumes: Task 3 `host_io.ray_trace_mesh_pick`, `model_identity`, `set_bridge_highlight`, `nif_shape_textures`; Task 5 `FlyCamera`; Task 6 `pick_mesh`, `identity_for`, `PickCycle`; Task 7 `load`, `match_shapes`, `shape_entry`; Task 8 `save`, `target_path`; `engine.ui.panel.Panel`.
- Produces: `class BridgeEmittersPanel(Panel)` with constructor `BridgeEmittersPanel(pose_provider, instance_provider, in_bridge_provider, clock=time.monotonic, io=host_io)`; name `"bridge-emitters"`; `open()`, `close()`, `is_open()`, `handle_key_esc()`, `handle_input(h)`, `camera_pose() -> Optional[(eye, target, up, fov)]`, `render_payload() -> Optional[str]`, `dispatch_event(action) -> bool`, `invalidate()`. Module constants `DOCK_CSS_PX = 360`, `CLICK_SLOP_PX = 4.0`, `DEFAULT_ROUGHNESS = 1.0`, `DEFAULT_METALNESS = 0.0`. JS entry `setBridgeEmitters(state)`; events `bridge-emitters/<action>` with actions `close`, `save`, `revert`, `undo`, `material:<roughness|metalness>:<float>`, `material-clear:<roughness|metalness>`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bridge_emitters_panel.py`:

```python
"""Bridge Emitters dev panel (spec 2026-10-08-bridge-emitters §4, §7, §8)."""
import json

import pytest

from engine.bridge_editor import lighting_doc as ld
from engine.ui import bridge_emitters_panel as bep

HASH = "0123456789abcdef"
INFO = {
    "source": "/abs/Dbridge.NIF", "content_hash": HASH,
    "meshes": [
        {"mesh": 0, "block": 3, "name": "floor", "node_chain": ["Scene Root"], "material": 0},
        {"mesh": 1, "block": 7, "name": "redalertpanel",
         "node_chain": ["Scene Root", "Red On GlowAlpha"], "material": 1},
    ],
}
POSE = ((0.0, 0.0, 50.0), (0.0, 1.0, 50.0), (0.0, 0.0, 1.0), 0.785398)


class FakeIO:
    def __init__(self, hit_mesh=1):
        self.hit_mesh = hit_mesh
        self.highlights = []
        self.traces = []

    def model_identity(self, iid):
        return INFO

    def nif_shape_textures(self, path):
        return {7: ["redalertpanel.tga"]}

    def ray_trace_mesh_pick(self, iid, origin, direction, max_dist, exclude=()):
        self.traces.append((origin, direction, tuple(exclude)))
        if self.hit_mesh is None or self.hit_mesh in exclude:
            return None
        return ((0, 10, 50), (0, -1, 0), 10.0, self.hit_mesh, 0)

    def set_bridge_highlight(self, iid, selected, hover):
        self.highlights.append((iid, selected, hover))


class FakeKeys:
    MOUSE_BUTTON_LEFT, MOUSE_BUTTON_RIGHT = 0, 1
    KEY_W, KEY_S, KEY_A, KEY_D, KEY_Q, KEY_E = 10, 11, 12, 13, 14, 15
    KEY_LEFT_SHIFT, KEY_RIGHT_SHIFT, KEY_LEFT_ALT, KEY_RIGHT_ALT = 20, 21, 22, 23


class FakeH:
    keys = FakeKeys

    def __init__(self):
        self.buttons = set()
        self.held = set()
        self.cursor = (400.0, 300.0)
        self.delta = (0.0, 0.0)
        self.locked = []

    def mouse_button_state(self, b):
        return b in self.buttons

    def key_state(self, k):
        return k in self.held

    def cursor_pos(self):
        return self.cursor

    def framebuffer_size(self):
        return (1600, 1200)

    def window_size(self):
        return (800, 600)          # dsf 2

    def consume_mouse_delta(self):
        d, self.delta = self.delta, (0.0, 0.0)
        return d

    def set_cursor_locked(self, on):
        self.locked.append(bool(on))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(ld.paths, "game_asset_dirs", lambda rel: [tmp_path / "stock" / rel])
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: tmp_path)
    t = [0.0]
    io = FakeIO()
    p = bep.BridgeEmittersPanel(pose_provider=lambda: POSE,
                                instance_provider=lambda: "iid",
                                in_bridge_provider=lambda: True,
                                clock=lambda: t[0], io=io)
    return p, io, FakeH(), t, tmp_path


def click(p, h, xy, alt=False):
    h.cursor = xy
    if alt:
        h.held.add(FakeKeys.KEY_LEFT_ALT)
    h.buttons.add(FakeKeys.MOUSE_BUTTON_LEFT)
    p.handle_input(h)
    h.buttons.discard(FakeKeys.MOUSE_BUTTON_LEFT)
    p.handle_input(h)
    h.held.discard(FakeKeys.KEY_LEFT_ALT)


def payload(p):
    js = p.render_payload()
    assert js.startswith("setBridgeEmitters(") and js.endswith(");")
    return json.loads(js[len("setBridgeEmitters("):-2])


def test_closed_panel_has_no_camera_and_hides(env):
    p, *_ = env
    assert p.camera_pose() is None
    assert payload(p)["visible"] is False


def test_open_seeds_the_fly_camera_from_the_bridge_camera(env):
    p, io, h, *_ = env
    p.open()
    p.handle_input(h)
    eye, target, up, fov = p.camera_pose()
    assert eye == POSE[0]
    assert abs(target[1] - 1.0) < 1e-6


def test_click_selects_and_highlights_the_shape(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    st = payload(p)
    assert st["selected"]["key"] == "7:redalertpanel"
    assert st["selected"]["node_chain"] == ["Scene Root", "Red On GlowAlpha"]
    assert st["selected"]["textures"] == ["redalertpanel.tga"]
    assert io.highlights[-1] == ("iid", 1, 1)


def test_pick_uses_the_fly_camera_pose(env):
    p, io, h, t, _ = env
    p.open()
    p.handle_input(h)
    h.buttons.add(FakeKeys.MOUSE_BUTTON_RIGHT)
    h.held.add(FakeKeys.KEY_W)
    p.handle_input(h)                      # RMB edge: lock
    t[0] = 1.0
    p.handle_input(h)                      # fly 1 s forward
    h.buttons.clear(); h.held.clear()
    p.handle_input(h)
    click(p, h, (800.0, 600.0))
    origin = io.traces[-1][0]
    assert origin[1] > 1.0                 # traced from where we flew to (eye started at y = 0)


def test_click_over_the_dock_does_not_pick(env):
    p, io, h, *_ = env
    p.open()
    # dsf 2: the dock covers the right DOCK_CSS_PX*2 framebuffer pixels.
    click(p, h, (1600.0 - 10.0, 300.0))
    assert payload(p)["selected"] is None


def test_drag_is_not_a_click(env):
    p, io, h, *_ = env
    p.open()
    h.cursor = (400.0, 300.0)
    h.buttons.add(FakeKeys.MOUSE_BUTTON_LEFT)
    p.handle_input(h)
    h.cursor = (450.0, 300.0)
    p.handle_input(h)
    h.buttons.clear()
    p.handle_input(h)
    assert payload(p)["selected"] is None


def test_alt_click_picks_the_surface_behind(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    io.hit_mesh = 0                         # what lies behind mesh 1
    click(p, h, (400.0, 300.0), alt=True)
    assert io.traces[-1][2] == (1,)
    assert payload(p)["selected"]["key"] == "3:floor"


def test_material_override_edit_and_sources(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    st = payload(p)["selected"]["material"]
    assert st == {"roughness": {"value": 1.0, "source": "default"},
                  "metalness": {"value": 0.0, "source": "default"}}
    assert p.dispatch_event("material:roughness:0.35")
    st = payload(p)
    assert st["selected"]["material"]["roughness"] == {"value": 0.35, "source": "override"}
    assert st["dirty"] is True
    assert p.dispatch_event("material-clear:roughness")
    assert payload(p)["selected"]["material"]["roughness"]["source"] == "default"


def test_material_value_is_clamped_and_garbage_ignored(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material:metalness:7")
    assert payload(p)["selected"]["material"]["metalness"]["value"] == 1.0
    assert p.dispatch_event("material:metalness:abc") is True    # handled, no change
    assert payload(p)["selected"]["material"]["metalness"]["value"] == 1.0
    assert p.dispatch_event("material:shine:0.5") is True
    assert "shine" not in payload(p)["selected"]["material"]


def test_undo_restores_the_previous_document(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material:roughness:0.2")
    p.dispatch_event("material:roughness:0.4")
    p.dispatch_event("undo")
    assert payload(p)["selected"]["material"]["roughness"]["value"] == 0.2
    p.dispatch_event("undo")
    assert payload(p)["selected"]["material"]["roughness"]["source"] == "default"


def test_save_writes_the_project_file_and_revert_reloads(env):
    p, io, h, t, tmp = env
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material:roughness:0.25")
    p.dispatch_event("save")
    path = tmp / "bridge_lighting" / f"{HASH}.json"
    saved = json.loads(path.read_text())
    assert saved["shapes"]["7:redalertpanel"]["material"] == {"roughness": 0.25}
    assert payload(p)["dirty"] is False
    p.dispatch_event("material:roughness:0.9")
    p.dispatch_event("revert")
    assert payload(p)["selected"]["material"]["roughness"]["value"] == 0.25


def test_save_is_refused_when_the_file_failed_to_load(env):
    p, io, h, t, tmp = env
    (tmp / "bridge_lighting").mkdir()
    bad = tmp / "bridge_lighting" / f"{HASH}.json"
    bad.write_text("{broken")
    p.open()
    click(p, h, (400.0, 300.0))
    st = payload(p)
    assert st["can_save"] is False
    assert st["status"]
    p.dispatch_event("material:roughness:0.5")
    p.dispatch_event("save")
    assert bad.read_text() == "{broken"


def test_close_while_flying_unlocks_cursor_and_clears_highlight(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    h.buttons.add(FakeKeys.MOUSE_BUTTON_RIGHT)
    p.handle_input(h)
    assert h.locked[-1] is True
    p.dispatch_event("close")
    assert h.locked[-1] is False
    assert io.highlights[-1] == (None, -1, -1)
    assert p.camera_pose() is None
    assert p.is_open() is False


def test_outside_the_bridge_view_the_panel_says_so_and_does_nothing(env):
    p, io, h, *_ = env
    p._in_bridge = lambda: False
    p.open()
    click(p, h, (400.0, 300.0))
    st = payload(p)
    assert st["in_bridge"] is False and st["selected"] is None
    assert p.camera_pose() is None


def test_a_swapped_bridge_reattaches_and_drops_the_selection(env):
    p, io, h, *_ = env
    iid = ["iid"]
    p._iid = lambda: iid[0]
    p.open()
    click(p, h, (400.0, 300.0))
    assert payload(p)["selected"] is not None
    iid[0] = "other"
    p.handle_input(h)
    assert payload(p)["selected"] is None
    assert io.highlights[-1][0] == "other"


def test_esc_closes(env):
    p, *_ = env
    p.open()
    p.handle_key_esc()
    assert p.is_open() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_emitters_panel.py -v`
Expected: FAIL — `ImportError: cannot import name 'bridge_emitters_panel'`.

- [ ] **Step 3: Implement the panel**

`engine/ui/bridge_emitters_panel.py`:

```python
"""Bridge Emitters -- developer-only bridge editor panel (spec
docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md §4, §7, §8).

Foundation scope: fly camera (hold RMB to look, WASDQE to move, Shift fast,
Alt slow), click-to-pick a NIF shape (Alt+click = the surface behind), a
selection tint, and the per-shape PBR material override (§9.2 source B) saved
to the per-bridge lighting document. The override is stored, not yet rendered:
the bridge PBR plan consumes it.

Driven like every dev modal: a pause-menu row opens it, the host keeps the
pause menu open-but-hidden (sim frozen) while it is open, calls handle_input(h)
each frame, and draws the bridge from camera_pose()."""
import copy
import json
import time
from typing import Optional

from engine import host_io
from engine.bridge_editor import lighting_doc as ld
from engine.bridge_editor import lighting_writer as lw
from engine.bridge_editor.fly_camera import FlyCamera
from engine.bridge_editor.picking import PickCycle, identity_for, pick_mesh
from engine.ui.panel import Panel

DOCK_CSS_PX = 360          # width of the docked panel, CSS px (bridge_emitters.css)
CLICK_SLOP_PX = 4.0
DEFAULT_ROUGHNESS = 1.0    # spec §9.2 source C
DEFAULT_METALNESS = 0.0
_CHANNELS = {"roughness": DEFAULT_ROUGHNESS, "metalness": DEFAULT_METALNESS}
_UNDO_LIMIT = 100


class BridgeEmittersPanel(Panel):
    def __init__(self, pose_provider, instance_provider, in_bridge_provider,
                 clock=time.monotonic, io=host_io):
        super().__init__()
        self._pose = pose_provider
        self._iid = instance_provider
        self._in_bridge = in_bridge_provider
        self._clock = clock
        self._io = io
        self._visible = False
        self._last_pushed = None
        self._reset_session()

    def _reset_session(self):
        self._camera = None
        self._last_t = None
        self._rmb = False
        self._left = False
        self._press_xy = None
        self._press_alt = False
        self._drag = 0.0
        self._info = None
        self._attached_iid = None
        self._textures = None
        self._load = None
        self._doc = None
        self._saved_text = None
        self._undo = []
        self._selected = None          # ShapeIdentity
        self._hover_mesh = -1
        self._cycle = PickCycle()
        self._status = ""
        self._pushed_highlight = None
        self._h_for_release = None

    # ── Panel ────────────────────────────────────────────────────────────
    @property
    def name(self) -> str:
        return "bridge-emitters"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        self._reset_session()
        self._last_pushed = None
        self.visible = True

    def close(self) -> None:
        h = self._h_for_release
        if self._rmb and h is not None:
            h.set_cursor_locked(False)
        self._io.set_bridge_highlight(None, -1, -1)
        self._reset_session()
        self.visible = False

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    def invalidate(self) -> None:
        self._last_pushed = None

    def camera_pose(self):
        return self._camera.pose() if (self._visible and self._camera) else None

    # ── per-frame input ──────────────────────────────────────────────────
    def handle_input(self, h) -> None:
        if not self._visible:
            return
        self._h_for_release = h
        if not self._in_bridge():
            self._camera = None
            return
        iid = self._iid()
        if iid is None:
            return
        if self._camera is None:
            eye, target, _up, _fov = self._pose()
            self._camera = FlyCamera.from_pose(eye, target)
        if self._info is None or iid != self._attached_iid:
            # First frame, or the bridge was swapped under an open panel
            # (QuickBattle DBridge -> EBridge): a different NIF, a different
            # document. The old selection means nothing on the new model.
            self._attach(iid)
            self._selected = None
            self._cycle.reset()

        now = self._clock()
        dt = 0.0 if self._last_t is None else min(max(now - self._last_t, 0.0), 0.1)
        self._last_t = now
        keys = h.keys

        rmb = bool(h.mouse_button_state(keys.MOUSE_BUTTON_RIGHT))
        if rmb and not self._rmb:
            h.set_cursor_locked(True)
            h.consume_mouse_delta()
        elif not rmb and self._rmb:
            h.set_cursor_locked(False)
        self._rmb = rmb
        if rmb:
            dx, dy = h.consume_mouse_delta()
            self._camera.look(dx, dy)
            ks = h.key_state
            self._camera.move(
                dt,
                forward=int(ks(keys.KEY_W)) - int(ks(keys.KEY_S)),
                strafe=int(ks(keys.KEY_D)) - int(ks(keys.KEY_A)),
                lift=int(ks(keys.KEY_E)) - int(ks(keys.KEY_Q)),
                fast=ks(keys.KEY_LEFT_SHIFT) or ks(keys.KEY_RIGHT_SHIFT),
                slow=ks(keys.KEY_LEFT_ALT) or ks(keys.KEY_RIGHT_ALT))
            self._push_highlight(iid)
            return

        x, y = h.cursor_pos()
        fb = h.framebuffer_size()
        over_dock = x >= fb[0] - DOCK_CSS_PX * self._dsf(h, fb)
        trace = lambda o, d, m, ex: self._io.ray_trace_mesh_pick(iid, o, d, m, ex)
        pose = self._camera.pose()
        hover = None if over_dock else pick_mesh(trace, (x, y), fb, pose)
        self._hover_mesh = -1 if hover is None else hover

        left = bool(h.mouse_button_state(keys.MOUSE_BUTTON_LEFT))
        if left and not self._left:                      # press edge
            # A press that starts over the dock is the panel's, never a pick.
            self._press_xy = None if over_dock else (x, y)
            self._press_alt = bool(h.key_state(keys.KEY_LEFT_ALT)
                                   or h.key_state(keys.KEY_RIGHT_ALT))
            self._drag = 0.0
        elif left and self._press_xy is not None:        # held: measure drag
            self._drag = max(self._drag, abs(x - self._press_xy[0]) + abs(y - self._press_xy[1]))
        elif not left and self._left and self._press_xy is not None:   # release
            if self._drag <= CLICK_SLOP_PX:
                self._click(trace, (x, y), fb, pose)
            self._press_xy = None
        self._left = left
        self._push_highlight(iid)

    @staticmethod
    def _dsf(h, fb):
        try:
            _w, win_h = h.window_size()
            return float(fb[1]) / float(win_h) if win_h > 0 else 1.0
        except (AttributeError, TypeError, ValueError, ZeroDivisionError):
            return 1.0

    def _attach(self, iid):
        self._attached_iid = iid
        self._info = self._io.model_identity(iid) or {"source": "", "content_hash": "", "meshes": []}
        self._textures = self._io.nif_shape_textures(self._info["source"]) if self._info["source"] else {}
        h = self._info["content_hash"]
        if not h:
            self._status = "This bridge has no content hash (not an interior load); nothing can be saved."
            self._load = ld.LoadResult(ld.empty_doc(self._info["source"]), None, "no content hash")
        else:
            self._load = ld.load(h, self._info["source"])
            self._status = self._load.error or ""
            if not self._load.error:
                _m, warnings = ld.match_shapes(self._load.doc, self._info["meshes"])
                if warnings:
                    self._status = "; ".join(warnings)
        self._doc = self._load.doc
        self._saved_text = lw.dumps(self._doc)
        self._undo = []

    def _click(self, trace, xy, fb, pose):
        exclude = ()
        if self._press_alt:
            current = self._selected.mesh if self._selected else -1
            exclude = self._cycle.next_exclusion(xy, current)
        else:
            self._cycle.reset()
        mesh = pick_mesh(trace, xy, fb, pose, exclude)
        self._selected = (None if mesh is None
                          else identity_for(self._info, mesh, self._textures))

    def _push_highlight(self, iid):
        sel = self._selected.mesh if self._selected else -1
        state = (iid, sel, self._hover_mesh)
        if state != self._pushed_highlight:
            self._io.set_bridge_highlight(iid, sel, self._hover_mesh)
            self._pushed_highlight = state

    # ── actions ──────────────────────────────────────────────────────────
    def dispatch_event(self, action: str) -> bool:
        if action == "close":
            self.close()
            return True
        if self._doc is None:
            return action in ("save", "revert", "undo") or action.startswith("material")
        if action == "save":
            self._save()
        elif action == "revert":
            self._attach_reload()
        elif action == "undo":
            if self._undo:
                self._doc = self._undo.pop()
        elif action.startswith("material:"):
            self._edit_material(action[len("material:"):])
        elif action.startswith("material-clear:"):
            self._clear_material(action[len("material-clear:"):])
        else:
            return False
        self._last_pushed = None
        return True

    def _snapshot(self):
        self._undo.append(copy.deepcopy(self._doc))
        del self._undo[:-_UNDO_LIMIT]

    def _edit_material(self, arg):
        ch, _, raw = arg.partition(":")
        if ch not in _CHANNELS or self._selected is None:
            return
        try:
            v = float(raw)
        except ValueError:
            return
        v = min(1.0, max(0.0, v))
        current = (self._doc["shapes"].get(self._selected.key, {})
                   .get("material", {}).get(ch))
        if current == v:
            return
        self._snapshot()
        entry = ld.shape_entry(self._doc, self._selected.block, self._selected.name)
        entry.setdefault("material", {})[ch] = v

    def _clear_material(self, ch):
        if ch not in _CHANNELS or self._selected is None:
            return
        entry = self._doc["shapes"].get(self._selected.key)
        if not entry or ch not in entry.get("material", {}):
            return
        self._snapshot()
        entry = self._doc["shapes"][self._selected.key]
        del entry["material"][ch]
        if not entry["material"]:
            del entry["material"]
        if set(entry) == {"block", "name"}:
            del self._doc["shapes"][self._selected.key]

    def _can_save(self):
        return bool(self._load and self._load.error is None and self._info["content_hash"])

    def _save(self):
        if not self._can_save():
            self._status = "Save refused: " + (self._load.error if self._load else "no document")
            return
        path = lw.target_path(self._load.path, self._info["content_hash"])
        try:
            lw.save(self._doc, path)
        except (OSError, ld.BridgeLightingError) as e:
            self._status = f"Save failed: {e}"
            return
        self._load = ld.LoadResult(self._doc, path, None)
        self._saved_text = lw.dumps(self._doc)
        self._status = f"Saved {path.name}"

    def _attach_reload(self):
        iid = self._iid()
        sel = self._selected
        self._info = None
        if iid is not None:
            self._attach(iid)
        self._selected = sel

    # ── payload ──────────────────────────────────────────────────────────
    def _material_state(self):
        entry = self._doc["shapes"].get(self._selected.key, {}) if self._doc else {}
        mat = entry.get("material", {})
        return {ch: ({"value": mat[ch], "source": "override"} if ch in mat
                     else {"value": default, "source": "default"})
                for ch, default in _CHANNELS.items()}

    def render_payload(self) -> Optional[str]:
        if not self._visible:
            state = {"visible": False}
        else:
            sel = None
            if self._selected is not None and self._doc is not None:
                sel = {"key": self._selected.key, "block": self._selected.block,
                       "name": self._selected.name,
                       "node_chain": list(self._selected.node_chain),
                       "textures": list(self._selected.textures),
                       "material": self._material_state()}
            hover = None
            if self._info and self._hover_mesh >= 0:
                ident = identity_for(self._info, self._hover_mesh, self._textures or {})
                hover = ident.key if ident else None
            state = {
                "visible": True,
                "in_bridge": bool(self._in_bridge()),
                "selected": sel,
                "hover": hover,
                "dirty": (self._doc is not None and lw.dumps(self._doc) != self._saved_text),
                "can_save": self._can_save(),
                "can_undo": bool(self._undo),
                "status": self._status,
            }
        js = "setBridgeEmitters(" + json.dumps(state) + ");"
        if js == self._last_pushed:
            return None
        self._last_pushed = js
        return js
```

Note on the closed state: `render_payload` returns the hide payload once and `None` afterwards; `open()` clears `_last_pushed` so the first open frame always pushes.

- [ ] **Step 4: Implement the UI**

`native/assets/ui-cef/css/bridge_emitters.css`:

```css
/* Bridge Emitters (developer-only) -- a DOCKED editor over the live bridge,
   like #spv-root: the root covers the viewport but takes no pointer events,
   so clicks reach the 3D view; only the dock column is interactive. Width
   must match DOCK_CSS_PX in engine/ui/bridge_emitters_panel.py.
   Not a centred modal: deliberately not in tests/ui/test_pause_modal_overlays.py. */
#bridge-emitters-root {
    display: none;
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 60;
}
#bridge-emitters-root .be-dock {
    pointer-events: auto;
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    width: 360px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
}
#bridge-emitters-root .be-dock .cp-content { flex: 1; overflow-y: auto; }
#bridge-emitters-root .be-help { opacity: 0.75; font-size: 12px; margin-bottom: 8px; }
#bridge-emitters-root .be-row { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
#bridge-emitters-root .be-row label { width: 90px; }
#bridge-emitters-root .be-row input[type=range] { flex: 1; }
#bridge-emitters-root .be-source { width: 60px; font-size: 11px; opacity: 0.8; }
#bridge-emitters-root .be-chain { font-size: 11px; opacity: 0.8; word-break: break-word; }
#bridge-emitters-root .be-status { font-size: 12px; min-height: 16px; color: #f0b060; }
```

`native/assets/ui-cef/index.html` — add `<link rel="stylesheet" href="css/bridge_emitters.css">` after the `css/ai_inspector.css` link; add after the AI inspector `</section>`:

```html
    <!-- Bridge Emitters (developer-only, spec 2026-10-08-bridge-emitters §8).
         setBridgeEmitters({visible, in_bridge, selected, hover, dirty,
         can_save, can_undo, status}) drives it; actions are
         dauntlessEvent('bridge-emitters/<action>'). Docked right, the 3D view
         stays clickable. data-panel routes text-field keyboard capture. -->
    <div id="bridge-emitters-root" class="dev-only" data-panel="bridge-emitters">
      <div class="be-dock cp-modal">
        <div class="cp-header">Bridge Emitters</div>
        <div class="cp-content"><div class="cp-body" id="bridge-emitters-body"></div></div>
        <div class="cp-footer">
          <button class="cp-done-button" id="be-undo" onclick="dauntlessEvent('bridge-emitters/undo')">Undo</button>
          <button class="cp-done-button" onclick="dauntlessEvent('bridge-emitters/revert')">Revert</button>
          <button class="cp-done-button" id="be-save" onclick="dauntlessEvent('bridge-emitters/save')">Save</button>
          <button class="cp-done-button" onclick="dauntlessEvent('bridge-emitters/close')">Close</button>
        </div>
      </div>
    </div>
```

and `<script src="js/bridge_emitters.js"></script>` after `js/ai_inspector.js`.

`native/assets/ui-cef/js/bridge_emitters.js`:

```javascript
// Bridge Emitters dev panel (spec 2026-10-08-bridge-emitters §8).
// Python pushes setBridgeEmitters(state); actions go back through
// dauntlessEvent('bridge-emitters/<action>'). Sliders commit on `change`.

function _beEsc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
        return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
}

function _beMaterialRow(ch, m) {
    const v = Number(m.value).toFixed(2);
    return '<div class="be-row">'
        + '<label>' + ch + '</label>'
        + '<input type="range" min="0" max="1" step="0.01" value="' + v + '"'
        + ' onchange="dauntlessEvent(\'bridge-emitters/material:' + ch + ':\' + this.value)">'
        + '<input type="number" min="0" max="1" step="0.01" value="' + v + '" style="width:56px"'
        + ' onchange="dauntlessEvent(\'bridge-emitters/material:' + ch + ':\' + this.value)">'
        + '<span class="be-source">' + _beEsc(m.source) + '</span>'
        + (m.source === 'override'
            ? '<button onclick="dauntlessEvent(\'bridge-emitters/material-clear:' + ch + '\')">×</button>'
            : '')
        + '</div>';
}

function setBridgeEmitters(state) {
    const root = document.getElementById('bridge-emitters-root');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const body = document.getElementById('bridge-emitters-body');
    let html = '';
    if (!state.in_bridge) {
        html += '<div class="be-help">Switch to the bridge view to edit it.</div>';
    } else {
        html += '<div class="be-help">Hold right mouse to look · WASD move · Q/E down/up · '
              + 'Shift fast · Alt slow · Click to select · Alt+click: the surface behind</div>';
        html += '<div class="be-row"><label>Hover</label><span>'
              + _beEsc(state.hover || '—') + '</span></div>';
        const s = state.selected;
        if (!s) {
            html += '<div class="be-help">Nothing selected.</div>';
        } else {
            html += '<div class="cp-section-title">Selection</div>';
            html += '<div class="be-row"><label>Shape</label><span>' + _beEsc(s.name) + '</span></div>';
            html += '<div class="be-row"><label>Block</label><span>' + s.block + '</span></div>';
            html += '<div class="be-row"><label>Textures</label><span>'
                  + _beEsc((s.textures || []).join(', ') || '—') + '</span></div>';
            html += '<div class="be-chain">' + _beEsc((s.node_chain || []).join(' › ')) + '</div>';
            html += '<div class="cp-section-title">Material</div>';
            html += _beMaterialRow('roughness', s.material.roughness);
            html += _beMaterialRow('metalness', s.material.metalness);
        }
    }
    html += '<div class="be-status">' + _beEsc(state.status || '')
          + (state.dirty ? ' (unsaved)' : '') + '</div>';
    if (body) body.innerHTML = html;
    const save = document.getElementById('be-save');
    if (save) save.disabled = !state.can_save;
    const undo = document.getElementById('be-undo');
    if (undo) undo.disabled = !state.can_undo;
    root.style.display = 'block';
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_bridge_emitters_panel.py tests/ui -v`
Expected: PASS (the UI suite still passes — the new root is not a centred modal).

- [ ] **Step 6: Commit**

```bash
git add engine/ui/bridge_emitters_panel.py native/assets/ui-cef/js/bridge_emitters.js native/assets/ui-cef/css/bridge_emitters.css native/assets/ui-cef/index.html tests/unit/test_bridge_emitters_panel.py
git commit -m "feat(bridge-editor): Bridge Emitters dev panel — fly, pick, material override, save"
```

---

### Task 10: Host-loop wiring

**Files:**
- Modify: `engine/host_loop.py` — a `_register_bridge_emitters` helper beside `_register_ai_inspector` (:3512); its call after `ai_inspector = _register_ai_inspector(registry)` (:10241); `_modal_blockers` (:10594); the bridge camera push (:11858-11864)
- Test: `tests/unit/test_host_loop_bridge_emitters_registration.py`

**Interfaces:**
- Consumes: Task 9 `BridgeEmittersPanel(pose_provider, instance_provider, in_bridge_provider)`, `.camera_pose()`; `_NULL_PICKER`; `bridge_camera.compute_camera()`; `controller.bridge_instance`; `view_mode.is_bridge`.
- Produces: `_register_bridge_emitters(registry, bridge_camera, controller, view_mode)` returning the panel or `_NULL_PICKER`; `_bridge_camera_pose(editor, bridge_camera, shake)` returning `(eye, target, up, fov)` — the editor's fly pose when it has one (no shake), else the bridge camera shaken.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_host_loop_bridge_emitters_registration.py`:

```python
"""Host-loop wiring of the Bridge Emitters dev panel."""
import pytest

from engine.ui.panel_registry import PanelRegistry


@pytest.fixture
def dev_env():
    import _dauntless_host
    import engine.dev_mode as dev_mode
    original_dev = getattr(_dauntless_host, "developer_mode", False)
    original_entries = list(dev_mode._dev_pause_menu_entries)
    dev_mode._dev_pause_menu_entries.clear()
    try:
        yield _dauntless_host, dev_mode
    finally:
        dev_mode._dev_pause_menu_entries.clear()
        dev_mode._dev_pause_menu_entries.extend(original_entries)
        _dauntless_host.developer_mode = original_dev


class _Cam:
    def compute_camera(self):
        return ((0, 0, 50), (0, 1, 50), (0, 0, 1), 0.7)


class _Ctl:
    bridge_instance = None


class _View:
    is_bridge = True


def test_registered_under_developer_mode(dev_env):
    h, dev_mode = dev_env
    h.developer_mode = True
    from engine import host_loop
    reg = PanelRegistry()
    panel = host_loop._register_bridge_emitters(reg, _Cam(), _Ctl(), _View())
    assert reg.find("bridge-emitters") is panel
    labels = [label for label, _ in dev_mode._dev_pause_menu_entries]
    assert "Bridge Emitters…" in labels


def test_not_registered_without_developer_mode(dev_env):
    h, dev_mode = dev_env
    h.developer_mode = False
    from engine import host_loop
    reg = PanelRegistry()
    panel = host_loop._register_bridge_emitters(reg, _Cam(), _Ctl(), _View())
    assert panel is host_loop._NULL_PICKER
    assert reg.find("bridge-emitters") is None
    assert dev_mode._dev_pause_menu_entries == []


def test_bridge_camera_pose_prefers_the_editor_and_skips_shake():
    from engine import host_loop

    class Editor:
        def camera_pose(self):
            return ((1, 2, 3), (1, 3, 3), (0, 0, 1), 0.5)

    shaken = []

    def shake(e, t, u):
        shaken.append(True)
        return e, t, u

    assert host_loop._bridge_camera_pose(Editor(), _Cam(), shake) == \
        ((1, 2, 3), (1, 3, 3), (0, 0, 1), 0.5)
    assert shaken == []


def test_bridge_camera_pose_falls_back_to_the_shaken_bridge_camera():
    from engine import host_loop

    def shake(e, t, u):
        return (e[0] + 1, e[1], e[2]), t, u

    eye, target, up, fov = host_loop._bridge_camera_pose(
        host_loop._NULL_PICKER, _Cam(), shake)
    assert eye == (1, 0, 50) and fov == 0.7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_host_loop_bridge_emitters_registration.py -v`
Expected: FAIL — `AttributeError: module 'engine.host_loop' has no attribute '_register_bridge_emitters'`.

- [ ] **Step 3: Implement**

In `engine/host_loop.py`, after `_register_ai_inspector`:

```python
def _register_bridge_emitters(registry, bridge_camera, controller, view_mode):
    """Developer-only Bridge Emitters editor (spec
    2026-10-08-bridge-emitters §4): a pause-menu row and a panel that joins
    the modal blockers. Returns _NULL_PICKER without --developer."""
    if not dev_mode.is_enabled():
        return _NULL_PICKER
    from engine.ui.bridge_emitters_panel import BridgeEmittersPanel
    panel = BridgeEmittersPanel(
        pose_provider=bridge_camera.compute_camera,
        instance_provider=lambda: controller.bridge_instance,
        in_bridge_provider=lambda: bool(view_mode.is_bridge))
    registry.register(panel)
    dev_mode.register_dev_pause_menu_entry("Bridge Emitters…", panel.open)
    return panel


def _bridge_camera_pose(editor, bridge_camera, shake):
    """The bridge camera to draw: the editor's fly camera while it has one
    (unshaken -- you are aiming at shapes), else the captain camera shaken."""
    pose = getattr(editor, "camera_pose", lambda: None)()
    if pose is not None:
        return pose
    eye, target, up, fov = bridge_camera.compute_camera()
    eye, target, up = shake(eye, target, up)
    return eye, target, up, fov
```

After `ai_inspector = _register_ai_inspector(registry)` (:10241):

```python
        bridge_emitters = _register_bridge_emitters(registry, bridge_camera,
                                                    controller, view_mode)
```

In `_modal_blockers` (:10594) append `bridge_emitters` after `ai_inspector`.

Replace the bridge camera block (:11858 `b_eye, b_target, b_up, b_fov = bridge_camera.compute_camera()` through the `camera_shake.perturb(...)` line) so that the push reads:

```python
                    b_eye, b_target, b_up, b_fov = _bridge_camera_pose(
                        bridge_emitters, bridge_camera, camera_shake.perturb)
                    r.set_bridge_camera(
                        eye=b_eye, target=b_target, up=b_up,
                        fov_y_rad=b_fov,
                        near=_BridgeCamera.NEAR,
                        far=_BridgeCamera.FAR,
                    )
```

Keep the existing comment block above the shake call, moved onto `_bridge_camera_pose`'s call. Do not touch `bridge_camera.apply(...)` (it does not run while paused).

(`view_mode` is bound at :10069 and `bridge_camera` at :10122, both before the registry at :10240.) A bridge swap needs no extra hook: `handle_input` re-reads `instance_provider()` every frame and re-attaches when the instance changes (Task 9).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_host_loop_bridge_emitters_registration.py tests/unit/test_host_loop_ai_inspector_registration.py tests/unit/test_pause_menu_model.py -v`
Expected: PASS.

- [ ] **Step 5: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0, no failure outside `tests/known_failures.txt`, no unbaselined skip.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/unit/test_host_loop_bridge_emitters_registration.py
git commit -m "feat(bridge-editor): wire the Bridge Emitters panel into the host loop"
```

- [ ] **Step 7: Live check (ASK MARK BEFORE LAUNCHING)**

Ask Mark for permission to launch. Then give him these plain commands (no `#` comments):

```bash
cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/bridge-emitters
./build/dauntless --developer
```

Live checklist for Mark, on DBridge and EBridge (use the dev mission picker for EBridge if needed):
1. Pause → "Bridge Emitters…" opens a docked panel on the right; the pause menu hides; the sim is frozen.
2. Hold RMB: mouse looks, W/S/A/D/Q/E move, Shift fast, Alt slow; release RMB: free cursor.
3. Hover tints a shape faintly; click selects it with a pulsing cyan tint; the panel shows shape, block, textures and the node chain (EBridge red alert panels show `Red On GlowAlpha`).
4. Alt+click on an EBridge wall-top steps to the surface behind.
5. Roughness/metalness sliders show "override"; × clears back to "default"; Undo steps back.
6. Save writes `native/assets/bridge_lighting/<hash>.json`; close and reopen the panel → the override is still there.
7. Close (button or ESC) returns to the pause menu with the captain's view exactly as before; resume play is unaffected.

Record the verdict in the spec's §10 log (Task 11).

---

### Task 11: Docs

**Files:**
- Modify: `CLAUDE.md` (Key reference material table — new row after "Bridge lighting baseline")
- Modify: `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` (§10 log)

- [ ] **Step 1: Add the CLAUDE.md row**

```markdown
| Bridge editor — pick shapes, per-bridge lighting data | `engine/bridge_editor/`, `engine/ui/bridge_emitters_panel.py`, `native/assets/bridge_lighting/`, `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` | `--developer` → pause → **Bridge Emitters…**: hold RMB + WASDQE to fly (Shift/Alt), click to select a NIF shape (Alt+click = the surface behind). Identity = (NIF content hash, block, name) — `Model::content_hash` is set for INTERIOR loads only. Per-bridge data `native/assets/bridge_lighting/<fnv1a64>.json` (mods: `<dir>/dauntless/bridge_lighting/`), per-shape `material` + `emitter`; unknown keys REJECTED; writer deterministic + atomic. ⚠️ The material override is stored but NOT rendered until bridge PBR lands. A name mismatch at a block is skipped with a warning, never applied. |
```

- [ ] **Step 2: Log the iteration in the spec**

Append to §10:

```markdown
| F1 | 2026-10-09 | Foundation built: fly camera, pick + identity, selection tint, lighting doc + writer, panel (plan 2026-10-09-bridge-editor-foundation) | <Mark's live verdict> | 4, 7, 8 |
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md
git commit -m "docs: bridge editor foundation — reference row and spec log"
```
