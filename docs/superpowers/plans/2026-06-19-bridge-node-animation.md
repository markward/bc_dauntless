# Bridge Node Animation (Chairs + Doors) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the non-skinned bridge model real node-keyframe animation so seated officers' chairs rotate (officer rides the chair, fixing the Tactical forward-turn gap) and walk-on doors lift.

**Architecture:** One new renderer capability — a per-instance `node_overrides` map (`node_index → animated local_transform`) that `walk_bridge_meshes` consults instead of the static node local. Two clip sources feed it through a host-side bridge-node animation store: **doors** play DBridge.nif's own embedded clip; **chairs** play separate externally-loaded `db_chair_*` NIF clips (the bridge model is const/cache-loaded, so external clips are held host-side, never appended to the model). A seated officer is coupled to its animated seat node in Python by re-basing the officer instance world around the seat pivot.

**Tech Stack:** C++17 (renderer/scenegraph/host via pybind11, gtest), Python 3 (engine, pytest), GLM (column-major), OpenGL.

## Global Constraints

- **Faithful to the SDK:** chairs/doors are driven by the SDK's own `TGAnimAction(pBridgeNode, clip)` calls; never invent motion the SDK doesn't author. The chair clip's baked `Camera captain` track is the zoom camera, NOT the chair — it must not move bridge geometry.
- **Byte-identical production path:** with no chair/door clip active, the bridge node-override map is empty and the bridge renders exactly as today. A coupled officer with an un-animated seat (`R_delta = I`) is byte-identical to its placement.
- **Matrices cross the C++/Python boundary ROW-MAJOR** (`set_world_transform` transposes to glm internally); `instance_node_world` returns 16 floats row-major to match.
- **Rotation convention:** column-vector, right-handed (det +1); `GetCol(1)` = forward. See CLAUDE.md.
- **Headless-safe:** every renderer/coupling call in Python is `hasattr`-guarded / try-excepted; capture + routing degrade to no-ops with no renderer. Existing suites stay green.
- **Bridge AABB stays static** (decision): `compute_model_aabb` is model-space and bridges never frustum-cull the player; do NOT make bounds track animated seats/doors.
- **No const-model mutation:** never `const_cast`/append clips to a cache-loaded (non-officer) model. External chair clips live in the host-side store only.
- **Build after native changes:** `cmake -B build -S . && cmake --build build -j` (shader/.frag changes also need the reconfigure; not relevant here). `host_bindings.cc` edits need a full `dauntless` rebuild (compiled into both the binary and the `_dauntless_host` module).

---

### Task 1: Node-world composition with per-instance overrides (renderer foundation)

Extract the bridge node-hierarchy world composition into a testable free function that honors an optional per-instance override map, add the `node_overrides` field to `Instance`, and wire `walk_bridge_meshes` to use the function. This is the foundation; nothing animates yet (no clip writes the map), so the bridge must render byte-identically.

**Files:**
- Create: `native/src/renderer/include/renderer/node_anim.h`
- Create: `native/src/renderer/node_anim.cc`
- Modify: `native/src/scenegraph/include/scenegraph/instance.h` (add `node_overrides`)
- Modify: `native/src/renderer/bridge_pass.cc:68-87` (use the new function)
- Modify: `native/src/renderer/CMakeLists.txt` (add `node_anim.cc`)
- Create: `native/tests/renderer/node_anim_test.cc`
- Modify: `native/tests/CMakeLists.txt` (register the new test, mirroring the existing `pose_sampler_test` entry)

**Interfaces:**
- Produces:
  - `Instance::node_overrides` — `std::unordered_map<int, glm::mat4>` on `scenegraph::Instance`; empty = use static node locals.
  - `std::vector<glm::mat4> renderer::compose_node_worlds(const assets::Model& model, const glm::mat4& instance_world, const std::unordered_map<int, glm::mat4>& overrides);` — world transform per node; for each node uses `overrides[i]` if present else `model.nodes[i].local_transform`, chaining `parent_world * local`. Returns empty vector if `model.nodes` is empty.

- [ ] **Step 1: Add the `node_overrides` field to Instance**

In `native/src/scenegraph/include/scenegraph/instance.h`, add `#include <unordered_map>` near the other includes (after `#include <vector>`), and add this field right after the `bone_palette` member (around line 56):

```cpp
    /// Per-instance node-local overrides for NON-SKINNED instances (the
    /// bridge): node_index -> animated local_transform. Empty = every node
    /// uses its model's static local (byte-identical to the un-animated
    /// render). Written each frame by the bridge-node animation updater;
    /// consulted by walk_bridge_meshes. Runtime state, never serialized.
    std::unordered_map<int, glm::mat4> node_overrides;
```

- [ ] **Step 2: Write the failing test for `compose_node_worlds`**

Create `native/tests/renderer/node_anim_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <renderer/node_anim.h>
#include <assets/model.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/matrix_decompose.hpp>

namespace {
// Two-node chain: root at origin, child translated +Y by 5.
assets::Model two_node() {
    assets::Model m;
    assets::Node root; root.name = "root"; root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    assets::Node child; child.name = "console seat 01"; child.parent_index = 0;
    child.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 5, 0));
    m.nodes = {root, child};
    m.root_node = 0;
    return m;
}
}

TEST(ComposeNodeWorlds, NoOverridesMatchesStaticWalk) {
    auto m = two_node();
    std::unordered_map<int, glm::mat4> empty;
    auto w = renderer::compose_node_worlds(m, glm::mat4(1.0f), empty);
    ASSERT_EQ(w.size(), 2u);
    EXPECT_EQ(w[0], glm::mat4(1.0f));
    // child world = root * child local = translate(0,5,0)
    EXPECT_NEAR(w[1][3].y, 5.0f, 1e-5f);
}

TEST(ComposeNodeWorlds, OverrideReplacesOnlyThatNodeLocal) {
    auto m = two_node();
    std::unordered_map<int, glm::mat4> ov;
    // Rotate the seat 90deg about Z in its local frame, keep its translation.
    glm::mat4 rot = glm::rotate(glm::mat4(1.0f), glm::radians(90.0f), glm::vec3(0,0,1));
    ov[1] = glm::translate(glm::mat4(1.0f), glm::vec3(0,5,0)) * rot;
    auto w = renderer::compose_node_worlds(m, glm::mat4(1.0f), ov);
    EXPECT_EQ(w[0], glm::mat4(1.0f));                 // root untouched
    EXPECT_NEAR(w[1][3].y, 5.0f, 1e-5f);             // translation preserved
    // local +X (1,0,0) rotated 90deg about Z -> +Y
    glm::vec3 col0 = glm::normalize(glm::vec3(w[1][0]));
    EXPECT_NEAR(col0.y, 1.0f, 1e-4f);
}

TEST(ComposeNodeWorlds, InstanceWorldPremultiplies) {
    auto m = two_node();
    std::unordered_map<int, glm::mat4> empty;
    glm::mat4 iw = glm::translate(glm::mat4(1.0f), glm::vec3(100,0,0));
    auto w = renderer::compose_node_worlds(m, iw, empty);
    EXPECT_NEAR(w[0][3].x, 100.0f, 1e-5f);
    EXPECT_NEAR(w[1][3].x, 100.0f, 1e-5f);
    EXPECT_NEAR(w[1][3].y, 5.0f, 1e-5f);
}
```

Register it in `native/tests/CMakeLists.txt` next to the existing renderer tests. Find the line registering `pose_sampler_test.cc` (grep `pose_sampler_test`) and add `renderer/node_anim_test.cc` to the same test target's source list.

- [ ] **Step 3: Run the test to verify it fails**

Run: `cmake -B build -S . >/dev/null && cmake --build build -j 2>&1 | tail -5`
Expected: compile error — `renderer/node_anim.h` not found (function/file not yet created).

- [ ] **Step 4: Implement `compose_node_worlds`**

Create `native/src/renderer/include/renderer/node_anim.h`:

```cpp
#pragma once
#include <unordered_map>
#include <vector>
#include <glm/glm.hpp>

namespace assets { struct Model; }

namespace renderer {

/// Compose a world transform per node for a non-skinned model. For each node,
/// use `overrides[i]` as its local transform when present, else the model's
/// static `nodes[i].local_transform`; chain `parent_world * local`. The asset
/// pipeline orders nodes parent-before-child, so a single linear pass is
/// correct. Returns an empty vector when the model has no nodes. With an empty
/// `overrides` map this reproduces the static node walk exactly.
std::vector<glm::mat4> compose_node_worlds(
    const assets::Model& model, const glm::mat4& instance_world,
    const std::unordered_map<int, glm::mat4>& overrides);

}  // namespace renderer
```

Create `native/src/renderer/node_anim.cc`:

```cpp
#include "renderer/node_anim.h"
#include <assets/model.h>

namespace renderer {

std::vector<glm::mat4> compose_node_worlds(
    const assets::Model& model, const glm::mat4& instance_world,
    const std::unordered_map<int, glm::mat4>& overrides) {
    std::vector<glm::mat4> world(model.nodes.size(), glm::mat4(1.0f));
    if (model.nodes.empty()) return world;

    auto local_of = [&](int i) -> const glm::mat4& {
        auto it = overrides.find(i);
        return it != overrides.end() ? it->second
                                     : model.nodes[i].local_transform;
    };

    world[model.root_node] = instance_world * local_of(model.root_node);
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0)
            world[i] = world[node.parent_index] * local_of(static_cast<int>(i));
    }
    return world;
}

}  // namespace renderer
```

Add `node_anim.cc` to the renderer library sources in `native/src/renderer/CMakeLists.txt` (alongside `pose_sampler.cc`).

- [ ] **Step 5: Wire `walk_bridge_meshes` to use the function**

In `native/src/renderer/bridge_pass.cc`, add `#include <renderer/node_anim.h>` with the other renderer includes, then replace the manual node-world loop (lines 68-87, the `std::vector<glm::mat4> world_per_node...` block through the closing of the `for` that issues draws) with:

```cpp
            std::vector<glm::mat4> world_per_node =
                renderer::compose_node_worlds(*m, inst.world, inst.node_overrides);
            for (std::size_t i = 0; i < m->nodes.size(); ++i) {
                const auto& node = m->nodes[i];
                for (int mesh_idx : node.meshes) {
                    const auto& mesh = m->meshes[mesh_idx];
                    const auto& mat = (mesh.material_index() >= 0
                        ? m->materials[mesh.material_index()]
                        : assets::Material{});
                    if (mat.lightmap_pass != want_lightmap_pass) continue;
                    draw_one(*m, mesh, mat, world_per_node[i], inst.model_handle);
                }
            }
```

- [ ] **Step 6: Run the tests + full native ctest to verify pass + no regression**

Run: `cmake --build build -j 2>&1 | tail -3 && ctest --test-dir build --output-on-failure 2>&1 | tail -15`
Expected: `node_anim_test` PASSES (3/3); all other tests still pass except the known pre-existing `FrameTest.PhaserHeatGlow` failure (offscreen-GL artifact, unrelated — see `project_cpp_ctest_not_in_run_tests`).

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/node_anim.cc native/src/renderer/include/renderer/node_anim.h \
        native/src/renderer/bridge_pass.cc native/src/scenegraph/include/scenegraph/instance.h \
        native/src/renderer/CMakeLists.txt native/tests/renderer/node_anim_test.cc native/tests/CMakeLists.txt
git commit -m "feat(renderer): per-instance node overrides for non-skinned bridge walk"
```

---

### Task 2: Node-override sampler (clip → node overrides)

Sample an `assets::AnimationClip`'s node tracks against a model's nodes, producing the override map Task 1 consumes. Matches tracks to nodes BY NAME, so a clip targeting `console seat 01` overrides only that node and a `Camera captain` track (no matching bridge node) is silently ignored.

**Files:**
- Modify: `native/src/renderer/include/renderer/node_anim.h` (add `sample_node_overrides`)
- Modify: `native/src/renderer/node_anim.cc`
- Modify: `native/tests/renderer/node_anim_test.cc`

**Interfaces:**
- Consumes: `assets::AnimationClip`, `assets::AnimationClip::NodeTrack` (target_node_name, translation/rotation/scale keys), `assets::sample_track_trs` (used by `pose_sampler.cc` — reuse it), `assets::Model::nodes`.
- Produces: `std::unordered_map<int, glm::mat4> renderer::sample_node_overrides(const assets::AnimationClip& clip, const assets::Model& model, float t);` — for every clip track whose `target_node_name` matches a model node, the sampled local transform (omitted channels fall back to that node's static local T/R/S). Tracks with no matching node are skipped. `t` is clamped to `[0, clip.duration_seconds]`.

- [ ] **Step 1: Write the failing test**

Append to `native/tests/renderer/node_anim_test.cc`:

```cpp
#include <renderer/pose_sampler.h>   // not needed; sampler is in node_anim

TEST(SampleNodeOverrides, MatchesSeatTrackIgnoresUnknownNode) {
    auto m = two_node();   // nodes: "root", "console seat 01"
    assets::AnimationClip clip; clip.duration_seconds = 1.0f;
    // Track that rotates the seat 90deg about Z across the clip.
    assets::AnimationClip::NodeTrack seat; seat.target_node_name = "console seat 01";
    glm::quat q = glm::angleAxis(glm::radians(90.0f), glm::vec3(0,0,1));
    seat.rotation = {{0.0f, q}, {1.0f, q}};
    // Track for a node that does NOT exist in the bridge (the zoom camera).
    assets::AnimationClip::NodeTrack cam; cam.target_node_name = "Camera captain";
    cam.translation = {{0.0f, glm::vec3(0,0,0)}, {1.0f, glm::vec3(999,0,0)}};
    clip.tracks = {seat, cam};

    auto ov = renderer::sample_node_overrides(clip, m, 1.0f);
    // Only the seat node (index 1) gets an override; the camera track is ignored.
    ASSERT_EQ(ov.size(), 1u);
    ASSERT_TRUE(ov.count(1));
    // Seat keeps its static translation (0,5,0) and gains the 90deg-Z rotation.
    EXPECT_NEAR(ov[1][3].y, 5.0f, 1e-4f);
    glm::vec3 col0 = glm::normalize(glm::vec3(ov[1][0]));
    EXPECT_NEAR(col0.y, 1.0f, 1e-3f);
}

TEST(SampleNodeOverrides, EmptyClipProducesNoOverrides) {
    auto m = two_node();
    assets::AnimationClip clip; clip.duration_seconds = 0.0f;   // no tracks
    auto ov = renderer::sample_node_overrides(clip, m, 0.0f);
    EXPECT_TRUE(ov.empty());
}
```

Ensure the test file's includes cover `<glm/gtx/quaternion.hpp>` (for `glm::angleAxis`); add it if absent. Remove the stray `#include <renderer/pose_sampler.h>` comment line if it does not compile — the sampler lives in `node_anim.h`.

- [ ] **Step 2: Run to verify it fails**

Run: `cmake --build build -j 2>&1 | tail -5`
Expected: compile error — `sample_node_overrides` not declared.

- [ ] **Step 3: Implement `sample_node_overrides`**

Add the declaration to `native/src/renderer/include/renderer/node_anim.h` (after `compose_node_worlds`):

```cpp
/// Sample a clip's node tracks against a model at time `t`, returning a
/// node_index -> local_transform override for every track whose
/// target_node_name matches a model node. Tracks with no matching node (e.g. a
/// chair clip's baked "Camera captain" view-path) are skipped. Each omitted
/// channel (T/R/S) falls back to the node's static local. `t` is clamped to
/// [0, clip.duration_seconds].
std::unordered_map<int, glm::mat4> sample_node_overrides(
    const assets::AnimationClip& clip, const assets::Model& model, float t);
```

In `native/src/renderer/node_anim.cc`, add the includes and implementation. Reuse the same per-channel-fallback decomposition `pose_sampler.cc` uses (`assets::sample_track_trs` with the node's static local decomposed into base T/R/S):

```cpp
#include <algorithm>
#include <string>
#include <glm/gtx/quaternion.hpp>
#include <assets/pose_sample.h>   // assets::sample_track_trs

// ... inside namespace renderer ...

std::unordered_map<int, glm::mat4> sample_node_overrides(
    const assets::AnimationClip& clip, const assets::Model& model, float t) {
    t = std::clamp(t, 0.0f, clip.duration_seconds);

    // node name -> index, for matching tracks to nodes.
    std::unordered_map<std::string, int> index_of;
    index_of.reserve(model.nodes.size());
    for (std::size_t i = 0; i < model.nodes.size(); ++i)
        index_of[model.nodes[i].name] = static_cast<int>(i);

    std::unordered_map<int, glm::mat4> overrides;
    for (const auto& tr : clip.tracks) {
        auto it = index_of.find(tr.target_node_name);
        if (it == index_of.end()) continue;            // e.g. "Camera captain"
        const glm::mat4& base = model.nodes[it->second].local_transform;
        const glm::vec3 base_t = glm::vec3(base[3]);
        glm::mat3 m3(base);
        float base_s = glm::length(m3[0]);
        if (base_s > 1e-8f) {
            m3[0] /= base_s;
            m3[1] /= glm::max(glm::length(m3[1]), 1e-8f);
            m3[2] /= glm::max(glm::length(m3[2]), 1e-8f);
        } else {
            base_s = 1.0f;
        }
        const glm::quat base_r = glm::quat_cast(m3);
        overrides[it->second] =
            assets::sample_track_trs(tr, t, base_t, base_r, base_s);
    }
    return overrides;
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cmake --build build -j 2>&1 | tail -3 && ctest --test-dir build -R node_anim --output-on-failure 2>&1 | tail -10`
Expected: all `node_anim` tests pass (5 total now).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/node_anim.cc native/src/renderer/include/renderer/node_anim.h \
        native/tests/renderer/node_anim_test.cc
git commit -m "feat(renderer): sample clip node tracks into per-node overrides"
```

---

### Task 3: Host bridge-node animation store, updater, and bindings

Add a host-side store of active bridge-node clips (embedded door clip OR externally-loaded chair clip), an updater that samples them into `inst.node_overrides` each frame, and the bindings Python uses to play/stop them and to read an animated node's world transform. External chair clips are held here, NEVER appended to the const bridge model.

**Files:**
- Modify: `native/src/host/host_bindings.cc` (store + updater + 4 bindings; call updater in `frame()` after `update_animations`)
- Modify: `engine/renderer.py` (thin Python wrappers)

**Interfaces:**
- Consumes: `renderer::sample_node_overrides`, `renderer::compose_node_worlds` (Task 1/2), `assets::load_animation_clips`, `renderer::resolve_asset_path`, `g_world`, `resolve_model` lookup, `glfwGetTime()`.
- Produces (pybind bindings + `engine/renderer.py` wrappers):
  - `play_instance_node_anim(iid, clip_index: int, loop: bool=False, reverse: bool=False)` — play the instance model's embedded `animations[clip_index]` on its node hierarchy (doors).
  - `play_instance_node_clip(iid, path: str, loop: bool=False, reverse: bool=False)` — load (cached) an external NIF's first clip and play it on this instance's node hierarchy (chairs). No-op if the NIF has no clips.
  - `stop_instance_node_anim(iid)` — clear the instance's active bridge-node clip and its `node_overrides` (snaps back to static).
  - `instance_node_world(iid, node_name: str, animated: bool=True) -> list[float] | None` — 16 floats ROW-MAJOR of the named node's world transform; `animated=True` applies the current overrides, `False` composes static locals. `None` if the instance/node is absent.

- [ ] **Step 1: Add the store, updater, and `frame()` call**

Near the top of `native/src/host/host_bindings.cc` (by `g_loaded_models`, ~line 198), add the store and a reverse/forward sampler state:

```cpp
struct BridgeNodeAnim {
    assets::AnimationClip clip;     // owned copy (embedded clip 0 or external NIF)
    double start_wall_time = 0.0;
    bool   loop = false;
    bool   reverse = false;         // play t from dur -> 0
    bool   settled = false;         // non-loop reached its end
};
// Keyed by InstanceId.index (bridge instances only; a handful at most).
std::unordered_map<std::uint32_t, BridgeNodeAnim> g_bridge_node_anims;
```

Add the updater (place it above `register_bindings`/the `frame()` body, after `resolve_model` is defined):

```cpp
void update_bridge_node_anims(double now) {
    for (auto it = g_bridge_node_anims.begin(); it != g_bridge_node_anims.end(); ) {
        auto& a = it->second;
        scenegraph::InstanceId id{it->first, 0};
        // Resolve by index (generation-agnostic): find the live instance.
        scenegraph::Instance* inst = g_world.get_by_index(it->first);
        if (!inst) { it = g_bridge_node_anims.erase(it); continue; }
        const assets::Model* m = resolve_model(inst->model_handle);
        if (!m) { ++it; continue; }

        const float dur = a.clip.duration_seconds;
        double elapsed = now - a.start_wall_time;
        if (elapsed < 0.0) elapsed = 0.0;
        float t;
        if (a.loop) {
            t = dur > 0.0f ? static_cast<float>(std::fmod(elapsed, dur)) : 0.0f;
        } else if (elapsed >= dur) {
            t = dur; a.settled = true;
        } else {
            t = static_cast<float>(elapsed);
        }
        if (a.reverse) t = dur - t;
        inst->node_overrides = renderer::sample_node_overrides(a.clip, *m, t);
        ++it;
    }
}
```

If `g_world` has no `get_by_index`, use the existing `get(InstanceId)` with the generation the play binding stored (store the full `InstanceId` in `BridgeNodeAnim` instead of just the index — adjust the struct + key accordingly). Confirm which exists by grepping `world.h` for `get_by_index`; prefer storing the full `InstanceId` if not.

In `frame()`, immediately after the existing `renderer::update_animations(g_world, lookup, now);` (host_bindings.cc:397), add:

```cpp
    update_bridge_node_anims(now);
```

- [ ] **Step 2: Add the four bindings**

In the bindings registration block (near `set_instance_animation`, ~line 733), add:

```cpp
    m.def("play_instance_node_anim",
          [](scenegraph::InstanceId id, int clip_index, bool loop, bool reverse) {
              auto* in = g_world.get(id);
              if (!in) return;
              const assets::Model* m = resolve_model(in->model_handle);
              if (!m || clip_index < 0 ||
                  clip_index >= static_cast<int>(m->animations.size())) return;
              BridgeNodeAnim a;
              a.clip = m->animations[clip_index];      // owned copy
              a.start_wall_time = glfwGetTime();
              a.loop = loop; a.reverse = reverse;
              g_bridge_node_anims[id.index] = std::move(a);
          },
          py::arg("iid"), py::arg("clip_index"), py::arg("loop") = false,
          py::arg("reverse") = false,
          "Play the instance model's embedded animations[clip_index] on its "
          "node hierarchy (non-skinned; e.g. bridge doors baked into DBridge.nif).");

    m.def("play_instance_node_clip",
          [](scenegraph::InstanceId id, const std::string& path, bool loop,
             bool reverse) {
              auto* in = g_world.get(id);
              if (!in) return;
              auto clips = assets::load_animation_clips(
                  renderer::resolve_asset_path(path));
              if (clips.empty()) return;               // NIF had no clips
              BridgeNodeAnim a;
              a.clip = std::move(clips[0]);            // external chair clip
              a.start_wall_time = glfwGetTime();
              a.loop = loop; a.reverse = reverse;
              g_bridge_node_anims[id.index] = std::move(a);
          },
          py::arg("iid"), py::arg("path"), py::arg("loop") = false,
          py::arg("reverse") = false,
          "Load an EXTERNAL NIF's first clip and play it on this instance's node "
          "hierarchy (e.g. db_chair_*_face_capt.nif rotating a 'console seat NN' "
          "node). The clip is held host-side; the const bridge model is never "
          "mutated.");

    m.def("stop_instance_node_anim",
          [](scenegraph::InstanceId id) {
              g_bridge_node_anims.erase(id.index);
              auto* in = g_world.get(id);
              if (in) in->node_overrides.clear();      // snap back to static
          },
          py::arg("iid"),
          "Stop any bridge-node clip on this instance and clear its node "
          "overrides (snaps the geometry back to its static pose).");

    m.def("instance_node_world",
          [](scenegraph::InstanceId id, const std::string& node_name,
             bool animated) -> py::object {
              auto* in = g_world.get(id);
              if (!in) return py::none();
              const assets::Model* m = resolve_model(in->model_handle);
              if (!m) return py::none();
              int idx = -1;
              for (std::size_t i = 0; i < m->nodes.size(); ++i)
                  if (m->nodes[i].name == node_name) { idx = static_cast<int>(i); break; }
              if (idx < 0) return py::none();
              static const std::unordered_map<int, glm::mat4> kEmpty;
              auto worlds = renderer::compose_node_worlds(
                  *m, in->world, animated ? in->node_overrides : kEmpty);
              const glm::mat4& w = worlds[idx];
              std::vector<float> out(16);              // ROW-MAJOR for Python
              for (int r = 0; r < 4; ++r)
                  for (int c = 0; c < 4; ++c) out[r * 4 + c] = w[c][r];
              return py::cast(out);
          },
          py::arg("iid"), py::arg("node_name"), py::arg("animated") = true,
          "Return the named node's world transform as 16 floats (row-major), "
          "or None if the instance/node is absent. animated=True applies the "
          "current node overrides; False composes the static locals (rest).");
```

Ensure `#include <renderer/node_anim.h>` and `<unordered_map>` and `<cmath>` are present at the top of `host_bindings.cc`.

- [ ] **Step 3: Add Python wrappers in `engine/renderer.py`**

After the existing `set_instance_animation` wrapper (~line 328), add:

```python
def play_instance_node_anim(iid: InstanceId, clip_index: int,
                            loop: bool = False, reverse: bool = False) -> None:
    """Play a non-skinned instance's embedded clip on its node hierarchy
    (bridge doors). No-op without the host binding (headless)."""
    fn = getattr(_h, "play_instance_node_anim", None)
    if fn is not None:
        fn(iid, clip_index, loop, reverse)


def play_instance_node_clip(iid: InstanceId, path: str,
                            loop: bool = False, reverse: bool = False) -> None:
    """Play an external NIF clip on a non-skinned instance's node hierarchy
    (chair turn). No-op without the host binding (headless)."""
    fn = getattr(_h, "play_instance_node_clip", None)
    if fn is not None:
        fn(iid, path, loop, reverse)


def stop_instance_node_anim(iid: InstanceId) -> None:
    """Clear any bridge-node clip + overrides on this instance."""
    fn = getattr(_h, "stop_instance_node_anim", None)
    if fn is not None:
        fn(iid)


def instance_node_world(iid: InstanceId, node_name: str,
                        animated: bool = True):
    """16 floats (row-major) of the named node's world transform, or None."""
    fn = getattr(_h, "instance_node_world", None)
    return fn(iid, node_name, animated) if fn is not None else None
```

- [ ] **Step 4: Build and smoke-test the bindings exist**

Run: `cmake --build build -j 2>&1 | tail -3`
Expected: clean build.

Run: `./build/dauntless --help >/dev/null 2>&1; python3 -c "import sys; sys.path.insert(0,'build/python'); import _open_stbc_host as h; print([n for n in ('play_instance_node_anim','play_instance_node_clip','stop_instance_node_anim','instance_node_world') if hasattr(h,n)])"`
Expected: all four names printed. (If the module name differs, use `build/python/_open_stbc_host.cpython-*.so`'s actual module name; grep `PYBIND11_MODULE` in host_bindings.cc to confirm.)

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py
git commit -m "feat(host): bridge-node clip store, updater, and play/stop/read bindings"
```

---

### Task 4: Capture the chair (bridge-node) clip in bridge_placement

`capture_registered_clip` currently picks the last `kind=="character"` action and discards the bridge-node chair action from the multi-action `TurnCaptain` builders. Add a companion that returns the `kind=="object"` (bridge-node) action's clip, so the chair half is available to the controller.

**Files:**
- Modify: `engine/appc/bridge_placement.py`
- Test: `tests/unit/test_bridge_placement_chair.py` (create; confirm the unit test dir — grep `test_bridge` to match the existing location, e.g. `tests/unit/`)

**Interfaces:**
- Consumes: the same SDK builder resolution `capture_registered_clip` uses (the `<location>+suffix` → builder → `TGSequence` of `TGAnimAction`s; each action carries `_anim_node` with `.kind` and a `_clip`/`name`).
- Produces: `capture_chair_clip(character, suffix) -> dict | None` in `engine/appc/bridge_placement.py`, returning `{"clip_nif": <path>}` for the LAST `kind=="object"` action of the `<location>+suffix` builder (the chair clip on the bridge node), or `None` if there is no object action or no resolvable path. Mirrors `capture_registered_clip`'s return shape.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bridge_placement_chair.py`:

```python
from engine.appc import bridge_placement as bp


class _AnimNode:
    def __init__(self, kind):
        self.kind = kind


class _Action:
    def __init__(self, kind, clip):
        self._anim_node = _AnimNode(kind)
        self._clip = clip


class _Seq:
    def __init__(self, actions):
        self._actions = actions
    def GetNumActions(self):
        return len(self._actions)
    def GetAction(self, i):
        return self._actions[i]


def test_capture_chair_clip_returns_object_action(monkeypatch):
    # Builder produces a body (character) clip AND a chair (object) clip.
    seq = _Seq([_Action("character", "db_face_capt_h"),
                _Action("object", "db_chair_H_face_capt")])
    monkeypatch.setattr(bp, "_resolve_builder_sequence",
                        lambda character, suffix: seq)
    monkeypatch.setattr(bp, "_nif_path_for_clip",
                        lambda name: f"data/animations/{name}.nif")
    out = bp.capture_chair_clip(object(), "TurnCaptain")
    assert out == {"clip_nif": "data/animations/db_chair_H_face_capt.nif"}


def test_capture_chair_clip_none_when_no_object_action(monkeypatch):
    seq = _Seq([_Action("character", "db_face_capt_h")])
    monkeypatch.setattr(bp, "_resolve_builder_sequence",
                        lambda character, suffix: seq)
    monkeypatch.setattr(bp, "_nif_path_for_clip",
                        lambda name: f"data/animations/{name}.nif")
    assert bp.capture_chair_clip(object(), "TurnCaptain") is None
```

> Before implementing, read `engine/appc/bridge_placement.py:73-130` and align the helper names: this test assumes `capture_registered_clip` is refactored to call two small helpers, `_resolve_builder_sequence(character, suffix) -> seq | None` (the builder lookup + invocation) and `_nif_path_for_clip(clip_name) -> path | None` (the existing path resolution). If those seams don't exist yet, extract them in Step 3 from the current `capture_registered_clip` body WITHOUT changing its behavior, then build `capture_chair_clip` on them. If extraction is undesirable, rewrite the test to monkeypatch whatever seam the real code exposes — but both `capture_registered_clip` and `capture_chair_clip` MUST share the builder resolution (DRY).

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/unit/test_bridge_placement_chair.py -v`
Expected: FAIL — `AttributeError: module 'engine.appc.bridge_placement' has no attribute 'capture_chair_clip'` (and/or the helper seams).

- [ ] **Step 3: Implement**

Refactor `capture_registered_clip` in `engine/appc/bridge_placement.py` to expose `_resolve_builder_sequence(character, suffix)` and `_nif_path_for_clip(clip_name)` (extract from the existing body; keep `capture_registered_clip`'s behavior identical — it still selects the last `kind=="character"` action). Then add:

```python
def capture_chair_clip(character, suffix):
    """The CHAIR clip from a multi-action TurnCaptain/BackCaptain builder: the
    last action whose anim node is the BRIDGE node (kind=="object"), e.g.
    db_chair_H_face_capt. Returns {"clip_nif": path} or None when the builder
    has no object action or no resolvable path. Shares builder resolution with
    capture_registered_clip (DRY)."""
    seq = _resolve_builder_sequence(character, suffix)
    if seq is None:
        return None
    action = None
    for i in range(seq.GetNumActions() - 1, -1, -1):
        a = seq.GetAction(i)
        if getattr(getattr(a, "_anim_node", None), "kind", None) == "object":
            action = a
            break
    if action is None:
        return None
    clip_name = getattr(action, "_clip", "") or getattr(action, "name", "")
    path = _nif_path_for_clip(clip_name)
    if not path:
        _logger.warning("capture_chair_clip: no path for %r", clip_name)
        return None
    return {"clip_nif": path}
```

- [ ] **Step 4: Run to verify pass + no regression in placement**

Run: `python3 -m pytest tests/unit/test_bridge_placement_chair.py tests/unit/test_bridge_character_anim.py -q`
Expected: PASS. Also run any existing bridge_placement test file (grep for it): `python3 -m pytest -k bridge_placement -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/bridge_placement.py tests/unit/test_bridge_placement_chair.py
git commit -m "feat(bridge): capture the chair (bridge-node) clip from TurnCaptain builders"
```

---

### Task 5: Bridge-node controller — chair playback + officer-seat coupling

A small controller that, on menu-up, plays the chair clip on the bridge instance and couples the seated officer to the animated seat node each tick; on menu-down, reverses the chair and clears coupling. The coupling re-bases the officer instance world around the seat pivot so the chair carries the officer (fixing Tactical's forward turn). Body clip continues to play on the officer via the existing character controller.

**Files:**
- Create: `engine/bridge_node_anim.py`
- Modify: `engine/bridge_character_anim.py` (`_process_turn` delegates the chair half)
- Modify: `engine/host_loop.py` (construct the controller, give it the bridge-iid getter + asset resolver, pump it; wire reset on mission swap)
- Test: `tests/unit/test_bridge_node_anim.py` (create)

**Interfaces:**
- Consumes: `engine.renderer.play_instance_node_clip / stop_instance_node_anim / instance_node_world / set_world_transform`; `bridge_placement.capture_chair_clip` (Task 4); the bridge instance id (`controller.bridge_instance` in host_loop); a seated officer's `_render_instance`.
- Produces: `engine/bridge_node_anim.py`:
  - `class BridgeNodeAnimController(bridge_iid_getter=None, asset_resolver=None)`
  - `.turn_chair(officer, chair_clip: dict, *, renderer)` — play `chair_clip["clip_nif"]` (resolved) on the bridge instance (forward), discover the seat node from the clip, register `officer` for coupling.
  - `.unturn_chair(officer, chair_clip: dict, *, renderer)` — play the chair clip in reverse, keep coupling until it settles, then clear (simplest: clear coupling immediately and let reverse run; see Step 3).
  - `.update(renderer)` — for each coupled officer, read the seat node animated + rest world, compute `R_delta = anim · inverse(rest)`, and `set_world_transform(officer_iid, R_delta)` (row-major list). `R_delta` already encodes the seat's world pivot (rest world contains the seat translation); do NOT conjugate by the pivot again.
  - `.reset(renderer=None)` — clear coupling + stop the bridge-node clip (mission swap).
  - Pure-Python 4x4 helpers `mat_mul`, `mat_inverse_rigid`, `identity4` (rigid = rotation+translation only, sufficient here) for testability without a renderer.
  - Seat-node name is DISCOVERED from the chair clip at play time (the single track named `console seat NN`); `capture_chair_clip` does not provide it.
  - Coupling is dropped only on `reset()` or when an officer is re-turned (dict overwrite) — never per-menu-close, so the officer rides the chair back to rest.

- [ ] **Step 1: Write the failing test (coupling math + routing, with fakes)**

Create `tests/unit/test_bridge_node_anim.py`:

```python
import math
from engine.bridge_node_anim import (
    BridgeNodeAnimController, mat_mul, mat_inverse_rigid, identity4,
)


def _rot_z(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [c, -s, 0, 0,  s, c, 0, 0,  0, 0, 1, 0,  0, 0, 0, 1]


def _trans(x, y, z):
    return [1, 0, 0, x,  0, 1, 0, y,  0, 0, 1, z,  0, 0, 0, 1]


class _FakeRenderer:
    def __init__(self, seat_rest, seat_animated):
        self._rest = seat_rest
        self._anim = seat_animated
        self.node_clips = []        # (iid, path, loop, reverse)
        self.stopped = []
        self.world_sets = {}        # officer_iid -> 16 floats
    def play_instance_node_clip(self, iid, path, loop=False, reverse=False):
        self.node_clips.append((iid, path, loop, reverse))
    def stop_instance_node_anim(self, iid):
        self.stopped.append(iid)
    def instance_node_world(self, iid, node_name, animated=True):
        return self._anim if animated else self._rest
    def set_world_transform(self, iid, mat):
        self.world_sets[iid] = list(mat)


class _Officer:
    def __init__(self, iid):
        self._render_instance = iid


def test_rest_delta_is_identity_leaves_officer_unchanged():
    # seat animated == seat rest -> R_delta = I -> coupling = identity.
    seat = _trans(0, 5, 0)
    r = _FakeRenderer(seat_rest=seat, seat_animated=seat)
    ctrl = BridgeNodeAnimController(bridge_iid_getter=lambda: 1)
    off = _Officer(7)
    ctrl.turn_chair(off, {"clip_nif": "db_chair_H_face_capt.nif",
                          "seat_node": "console seat 01"}, renderer=r)
    ctrl.update(r)
    # Officer world set to identity (within tolerance).
    got = r.world_sets[7]
    for i, v in enumerate(identity4()):
        assert abs(got[i] - v) < 1e-6


def test_chair_rotation_rotates_officer_about_seat_pivot():
    # Seat rotates 90deg about Z at pivot (0,5,0). Officer should be rotated
    # about that pivot, NOT about the origin.
    pivot = (0.0, 5.0, 0.0)
    seat_rest = _trans(*pivot)
    seat_anim = mat_mul(_trans(*pivot), _rot_z(90))   # rotate in place at pivot
    r = _FakeRenderer(seat_rest=seat_rest, seat_animated=seat_anim)
    ctrl = BridgeNodeAnimController(bridge_iid_getter=lambda: 1)
    off = _Officer(7)
    ctrl.turn_chair(off, {"clip_nif": "c.nif", "seat_node": "console seat 01"},
                    renderer=r)
    ctrl.update(r)
    coupling = r.world_sets[7]
    # The pivot point must be a fixed point of the coupling transform.
    px, py, pz = pivot
    tx = coupling[0]*px + coupling[1]*py + coupling[2]*pz + coupling[3]
    ty = coupling[4]*px + coupling[5]*py + coupling[6]*pz + coupling[7]
    assert abs(tx - px) < 1e-5 and abs(ty - py) < 1e-5


def test_turn_chair_plays_forward_clip_on_bridge_instance():
    r = _FakeRenderer(_trans(0,0,0), _trans(0,0,0))
    ctrl = BridgeNodeAnimController(bridge_iid_getter=lambda: 9,
                                    asset_resolver=lambda p: "/abs/" + p)
    ctrl.turn_chair(_Officer(7), {"clip_nif": "c.nif",
                                  "seat_node": "console seat 01"}, renderer=r)
    assert r.node_clips[-1] == (9, "/abs/c.nif", False, False)


def test_unturn_reverses_then_reset_clears():
    r = _FakeRenderer(_trans(0,0,0), _trans(0,0,0))
    ctrl = BridgeNodeAnimController(bridge_iid_getter=lambda: 9)
    off = _Officer(7)
    ctrl.turn_chair(off, {"clip_nif": "c.nif", "seat_node": "s"}, renderer=r)
    ctrl.unturn_chair(off, {"clip_nif": "c.nif", "seat_node": "s"}, renderer=r)
    assert r.node_clips[-1] == (9, "c.nif", False, True)   # reverse
    ctrl.reset(renderer=r)
    assert 9 in r.stopped


def test_no_bridge_instance_is_graceful():
    r = _FakeRenderer(_trans(0,0,0), _trans(0,0,0))
    ctrl = BridgeNodeAnimController(bridge_iid_getter=lambda: None)
    ctrl.turn_chair(_Officer(7), {"clip_nif": "c.nif", "seat_node": "s"},
                    renderer=r)
    ctrl.update(r)            # no crash, nothing set
    assert r.world_sets == {}
```

> The test threads `seat_node` in the chair_clip dict for determinism (the fake renderer has no `load_animation_clips`). In real use `capture_chair_clip` does NOT provide `seat_node` — `turn_chair` DISCOVERS it from the clip's tracks (the single track whose name starts with `console seat`, per BC's node naming; the `Camera captain` track is excluded by that filter). `turn_chair` uses `chair_clip.get("seat_node") or self._discover_seat_node(renderer, path)`, so the threaded value short-circuits discovery in tests and discovery runs in production.

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/unit/test_bridge_node_anim.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.bridge_node_anim'`.

- [ ] **Step 3: Implement `engine/bridge_node_anim.py`**

```python
"""BridgeNodeAnimController — plays chair clips on the bridge (non-skinned)
instance and couples a seated officer to the animated 'console seat NN' node so
the chair carries the officer. This is the chair half of the turn-to-captain
flow; the officer's BODY clip still plays via BridgeCharacterAnimController.

Coupling math (row-major 4x4): with the officer placed at OFFICER_TRANSFORM
(identity), the coupled world is just
    R_delta = seat_animated_world · inverse(seat_rest_world)
R_delta already encodes the seat's world pivot (rest world contains the seat's
world translation), so a point riding the seat at rest position p moves to
R_delta · p; do NOT conjugate by the pivot again. At rest R_delta = I ->
identity -> byte-identical to placement.

See docs/superpowers/specs/2026-06-19-bridge-node-animation-design.md.
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)


def identity4():
    return [1.0, 0, 0, 0,  0, 1.0, 0, 0,  0, 0, 1.0, 0,  0, 0, 0, 1.0]


def mat_mul(a, b):
    """Row-major 4x4 multiply (a · b)."""
    out = [0.0] * 16
    for r in range(4):
        for c in range(4):
            out[r * 4 + c] = sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
    return out


def mat_inverse_rigid(m):
    """Inverse of a rigid (rotation R + translation t) row-major 4x4:
    [Rᵀ | -Rᵀ t]. Sufficient: seat transforms are rotation+translation."""
    r00, r01, r02 = m[0], m[1], m[2]
    r10, r11, r12 = m[4], m[5], m[6]
    r20, r21, r22 = m[8], m[9], m[10]
    tx, ty, tz = m[3], m[7], m[11]
    # transpose rotation
    inv = [r00, r10, r20, 0,
           r01, r11, r21, 0,
           r02, r12, r22, 0,
           0,   0,   0,   1.0]
    # -Rᵀ t
    inv[3]  = -(inv[0] * tx + inv[1] * ty + inv[2] * tz)
    inv[7]  = -(inv[4] * tx + inv[5] * ty + inv[6] * tz)
    inv[11] = -(inv[8] * tx + inv[9] * ty + inv[10] * tz)
    return inv


class BridgeNodeAnimController:
    def __init__(self, bridge_iid_getter=None, asset_resolver=None):
        self._bridge_iid_getter = bridge_iid_getter or (lambda: None)
        self._resolve = asset_resolver or (lambda p: p)
        # officer_iid -> dict(officer, seat_node)
        self._coupled = {}

    def _bridge_iid(self):
        try:
            return self._bridge_iid_getter()
        except Exception:
            return None

    @staticmethod
    def _discover_seat_node(renderer, path):
        """The chair clip animates one bridge node ('console seat NN') plus the
        non-bridge 'Camera captain' track. Return the seat node name by the BC
        naming convention, or None."""
        fn = getattr(renderer, "load_animation_clips", None)
        if fn is None:
            return None
        try:
            clips = fn(path)
        except Exception:
            return None
        if not clips:
            return None
        for tr in clips[0].get("tracks", []):
            name = tr.get("target_node_name") or tr.get("name") or ""
            if name.lower().startswith("console seat"):
                return name
        return None

    def turn_chair(self, officer, chair_clip, *, renderer):
        bridge = self._bridge_iid()
        if bridge is None or chair_clip is None:
            return
        path = self._resolve(chair_clip["clip_nif"])
        seat_node = chair_clip.get("seat_node") or \
            self._discover_seat_node(renderer, path)
        try:
            renderer.play_instance_node_clip(bridge, path, False, False)
        except Exception:
            _logger.debug("turn_chair play failed", exc_info=True)
            return
        iid = getattr(officer, "_render_instance", None)
        if iid is not None and seat_node:
            self._coupled[iid] = {"officer": officer, "seat_node": seat_node}

    def unturn_chair(self, officer, chair_clip, *, renderer):
        bridge = self._bridge_iid()
        if bridge is not None and chair_clip is not None:
            try:
                renderer.play_instance_node_clip(
                    bridge, self._resolve(chair_clip["clip_nif"]), False, True)
            except Exception:
                _logger.debug("unturn_chair play failed", exc_info=True)
        # Coupling continues to track the reversing seat until reset/settle;
        # simplest correct behavior is to keep the officer coupled while the
        # reverse plays (the seat returns to rest -> R_delta -> I -> identity).

    def update(self, renderer):
        for iid, rec in list(self._coupled.items()):
            bridge = self._bridge_iid()
            if bridge is None:
                continue
            try:
                anim = renderer.instance_node_world(bridge, rec["seat_node"], True)
                rest = renderer.instance_node_world(bridge, rec["seat_node"], False)
            except Exception:
                continue
            if anim is None or rest is None:
                continue
            # R_delta already encodes the seat's world pivot (rest world holds
            # the seat translation); applying it directly rides the officer on
            # the seat. Conjugating by the pivot again would rotate about 2·pivot.
            coupling = mat_mul(list(anim), mat_inverse_rigid(list(rest)))
            try:
                renderer.set_world_transform(iid, coupling)
            except Exception:
                _logger.debug("coupling set_world_transform failed", exc_info=True)

    def reset(self, *, renderer=None):
        bridge = self._bridge_iid()
        if renderer is not None and bridge is not None:
            try:
                renderer.stop_instance_node_anim(bridge)
            except Exception:
                pass
        self._coupled.clear()
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/unit/test_bridge_node_anim.py -v`
Expected: all PASS.

- [ ] **Step 5: Delegate the chair half from the character controller**

In `engine/bridge_character_anim.py`, `_process_turn` currently submits/handles only the body clip. Give the controller an optional `node_ctrl` (the `BridgeNodeAnimController`) set by the host, and in `_process_turn`, after handling the body clip, call the chair:

```python
        # Chair half: rotate the seat + couple the seated officer (delegated to
        # the bridge-node controller). Standing officers have no chair action
        # (capture_chair_clip returns None) -> no-op, body turn only.
        node_ctrl = getattr(self, "_node_ctrl", None)
        if node_ctrl is not None:
            chair = capture_chair_clip(character, "TurnCaptain" if turn
                                       else "BackCaptain")
            if turn:
                node_ctrl.turn_chair(character, chair, renderer=renderer)
            else:
                node_ctrl.unturn_chair(character, chair, renderer=renderer)
                # Do NOT release coupling here: the officer must keep riding the
                # seat as the reverse clip plays back. The coupling self-heals to
                # identity when the chair settles at rest (R_delta -> I -> the
                # officer's placement) and stays there harmlessly. Coupling is
                # dropped only on reset() (mission swap) or when re-turned (the
                # _coupled dict entry is overwritten). Releasing now would freeze
                # the officer at the turned pose while the chair animates back.
```

Import `capture_chair_clip` from `engine.appc.bridge_placement` at the top (alongside the existing `capture_registered_clip` import). Add a setter or constructor param so the host can attach `_node_ctrl` (a one-line `self._node_ctrl = None` in `__init__` plus a `set_node_controller(ctrl)` method). Add a focused test in `tests/unit/test_bridge_character_anim.py` that a fake node controller's `turn_chair`/`unturn_chair` are called on request_turn / request_turn_back (monkeypatch `capture_chair_clip` to return a dict / None).

- [ ] **Step 6: Wire into host_loop**

In `engine/host_loop.py`: construct `node_anim = BridgeNodeAnimController(bridge_iid_getter=lambda: controller.bridge_instance, asset_resolver=_game_asset_path)` near the existing `char_anim = BridgeCharacterAnimController(...)` construction; call `char_anim.set_node_controller(node_anim)`; pump `node_anim.update(r)` in the same bridge/not-paused block that pumps `char_anim.update(...)`; and call `node_anim.reset(renderer=r)` wherever `char_anim`/cutscene state is reset on mission swap. Grep `char_anim` in host_loop.py to find all three sites. (No new test here — covered by the controller's own tests + GUI acceptance; verify host imports cleanly: `python3 -c "import engine.host_loop"`.)

- [ ] **Step 7: Run the bridge suites + commit**

Run: `python3 -m pytest tests/unit/test_bridge_node_anim.py tests/unit/test_bridge_character_anim.py tests/unit/test_bridge_placement_chair.py -q && python3 -c "import engine.host_loop"`
Expected: PASS; host imports clean.

```bash
git add engine/bridge_node_anim.py engine/bridge_character_anim.py engine/host_loop.py \
        tests/unit/test_bridge_node_anim.py tests/unit/test_bridge_character_anim.py
git commit -m "feat(bridge): chair playback + officer-seat coupling on station select"
```

---

### Task 6: Make doors actually lift (walk-on cutscene)

`bridge_cutscene._update_doors` already routes the door action but calls the inert `set_instance_animation`. Switch it to the new `play_instance_node_anim(iid, 0, ...)` so the embedded door clip animates the door-leaf nodes during the merged E1M1 walk-on.

**Files:**
- Modify: `engine/bridge_cutscene.py:58-68`
- Test: `tests/unit/test_bridge_cutscene*.py` (modify the existing door test; grep `bridge_cutscene` under tests/)

**Interfaces:**
- Consumes: `engine.renderer.play_instance_node_anim` (Task 3). The door keyframes are the bridge model's embedded clip 0 (`DBridge.nif`).
- Produces: `_update_doors` calls `renderer.play_instance_node_anim(iid, 0, loop=False, reverse=False)` (was `renderer.set_instance_animation(iid, 0, False)`), then `action.Completed()`.

- [ ] **Step 1: Update the existing door test to assert the new call**

Find the door test (grep `set_instance_animation` and `request_object_anim` under `tests/`). Change its fake renderer to record `play_instance_node_anim(iid, clip_index, loop, reverse)` and assert `_update_doors` calls `play_instance_node_anim` with `(iid, 0, False, False)` and fires `action.Completed()`. If no such test exists, create `tests/unit/test_bridge_cutscene_doors.py`:

```python
from engine.bridge_cutscene import BridgeCutsceneController


class _Action:
    def __init__(self):
        self.completed = False
    def Completed(self):
        self.completed = True


class _Owner:
    def __init__(self, iid):
        self.render_instance = iid


class _AnimNode:
    def __init__(self, owner):
        self.owner = owner


class _FakeRenderer:
    def __init__(self):
        self.node_anims = []
    def play_instance_node_anim(self, iid, clip_index, loop=False, reverse=False):
        self.node_anims.append((iid, clip_index, loop, reverse))


def test_door_request_plays_embedded_clip_zero_and_completes():
    ctrl = BridgeCutsceneController()
    act = _Action()
    owner = _Owner(5)
    ctrl.request_object_anim(act, _AnimNode(owner), "DB_Door_L1")
    r = _FakeRenderer()
    ctrl._update_doors(r)
    assert r.node_anims == [(5, 0, False, False)]
    assert act.completed is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/unit/test_bridge_cutscene_doors.py -v`
Expected: FAIL — `_FakeRenderer` has no `set_instance_animation` (current code calls that), so `AttributeError`, or the assertion on `node_anims` fails.

- [ ] **Step 3: Implement**

In `engine/bridge_cutscene.py`, change `_update_doors` (line 66) from:

```python
            renderer.set_instance_animation(iid, 0, False)
```
to:
```python
            # Door keyframes are the bridge model's embedded clip 0 (DBridge.nif's
            # NiKeyframeControllers). play_instance_node_anim animates the
            # non-skinned door-leaf nodes (set_instance_animation only built a
            # bone palette, which the bridge — having no skeleton — ignored).
            renderer.play_instance_node_anim(iid, 0, loop=False, reverse=False)
```

Update the module docstring line referencing `set_instance_animation` to `play_instance_node_anim`.

- [ ] **Step 4: Run to verify pass + no cutscene regression**

Run: `python3 -m pytest -k bridge_cutscene -q`
Expected: PASS (the camera-path tests are untouched; only the door call changed).

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_cutscene.py tests/unit/test_bridge_cutscene_doors.py
git commit -m "fix(bridge): walk-on doors play the embedded node clip (actually lift)"
```

---

### Task 7: Mission-swap reset robustness + docs/deferred-work update

Ensure the bridge-node clip store and coupling are cleared on mission swap (no stale chair/door state leaks into the next mission — the MissionLib-global-leak discipline), close out deferred_work #38, and update the followup spec pointer.

**Files:**
- Modify: `native/src/host/host_bindings.cc` (clear `g_bridge_node_anims` wherever `g_loaded_models`/world is reset on mission swap — grep the existing `g_loaded_models.clear()` sites at ~272 and ~318)
- Modify: `native/src/host/docs/deferred_work.md` (#38 → done/superseded)
- Modify: `docs/superpowers/specs/2026-06-19-bridge-chair-node-animation-followup.md` (mark superseded by this design)
- Test: `tests/unit/test_bridge_node_anim.py` (reset already covered; add a host-reset note only if a Python seam exists)

**Interfaces:**
- Consumes: existing mission-swap reset path (`reset_sdk_globals` / world teardown).
- Produces: no new API; `g_bridge_node_anims.clear()` at each model/world reset site.

- [ ] **Step 1: Clear the store on world/model reset**

In `native/src/host/host_bindings.cc`, at each site that does `g_loaded_models.clear();` (grep — there are two, ~line 272 and ~318), add immediately after:

```cpp
    g_bridge_node_anims.clear();
```

- [ ] **Step 2: Build + full native ctest**

Run: `cmake --build build -j 2>&1 | tail -3 && ctest --test-dir build --output-on-failure 2>&1 | tail -15`
Expected: green except the known pre-existing `FrameTest.PhaserHeatGlow`.

- [ ] **Step 3: Update deferred_work #38 and the followup spec**

In `native/src/host/docs/deferred_work.md`, mark item #38 done: non-skinned node animation landed (chairs + doors); note doors now lift in the walk-on, chairs rotate on station-select, and engine flares were dropped as ungrounded. In `docs/superpowers/specs/2026-06-19-bridge-chair-node-animation-followup.md`, add a top line: `**SUPERSEDED by docs/superpowers/specs/2026-06-19-bridge-node-animation-design.md (implemented).**`

- [ ] **Step 4: Commit**

```bash
git add native/src/host/host_bindings.cc native/src/host/docs/deferred_work.md \
        docs/superpowers/specs/2026-06-19-bridge-chair-node-animation-followup.md
git commit -m "chore(bridge): clear node-anim store on swap; close deferred_work #38"
```

- [ ] **Step 5: Full Python suite (watchdog-capped) + GUI acceptance handoff**

Run: `scripts/run_tests.sh 2>&1 | tail -20`
Expected: full suite passes (memory-safe per `feedback_pytest_memory`).

GUI acceptance (Mark, manual): launch `./build/dauntless`, load D-bridge. (1) Select **Tactical** → chair + officer rotate to face the captain (the forward-turn gap, fixed). (2) Select **Helm** → body turns AND the seat rotates together. (3) Close each → chair + officer reverse. (4) Run the E1M1 walk-on → the L1 door lifts. (5) With nothing selected and no cutscene, the bridge looks identical to before. Report any deviation for a fix loop before merge.

---

## Notes for the implementer

- **Build discipline:** after ANY `native/` change rebuild with `cmake --build build -j` from the repo root; `host_bindings.cc` is compiled into BOTH `./build/dauntless` and the `_dauntless_host`/`_open_stbc_host` module, so rebuild the whole `dauntless` target (see `feedback_host_bindings_build_target`). A stale binary surfaces as `AttributeError: module ... has no attribute X`.
- **Module name:** confirm the host module name via `grep PYBIND11_MODULE native/src/host/host_bindings.cc` before writing the Step-4 smoke in Task 3 (`engine/renderer.py` imports it as `_h`).
- **`get_by_index`:** Task 3 Step 1 assumes a generation-agnostic instance lookup. If `world.h` lacks it, store the full `InstanceId` in `BridgeNodeAnim` and use `g_world.get(id)` — do NOT add a new World method just for this unless it's trivially symmetric with the existing API.
- **Seat node discovery:** the chair clip animates exactly one bridge node (`console seat NN`) plus the non-bridge `Camera captain` track. Discover the seat node name by loading the clip (`renderer.load_animation_clips`) and taking the single track whose `target_node_name` matches a bridge node — or thread it via the chair_clip dict from `capture_chair_clip` if simpler. Either way the sampler already ignores `Camera captain` (no matching node), so no special-casing of the camera is needed at draw time.
- **Do not regress** the standing-officer/Helm BODY turns, the `sample_pose_over_base` root anchor, or the byte-identical static bridge render. The rapid-open/close eviction in `bridge_character_anim` (turn-to-captain Minor #1) must extend to the chair: a fast open+close should not strand a rotated chair. `unturn_chair` issues the reverse clip and coupling stays live, so the officer rides the chair back to rest even if open/close are adjacent ticks; verify with the existing eviction test pattern. The single-active-clip store means a second officer turning overwrites the first's chair clip — fine under the single-open-menu invariant (the first officer's now-unanimated seat reads rest → identity).
