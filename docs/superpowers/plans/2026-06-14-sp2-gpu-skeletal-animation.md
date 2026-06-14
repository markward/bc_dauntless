# SP2 — GPU Skeletal Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render BC characters deformed by a correct, time-driven GPU bone palette so bridge officers stand correctly posed at their stations and play their placement animation once-and-hold.

**Architecture:** Fix the two correctness bugs that made every palette attempt shear/explode — bake rigid-shape verts to bind-model space (gated on skeleton + no skin controller) and draw skinned models with `u_model = inst.world` instead of the per-node walk. Then the renderer samples each animated instance's clip per frame and rebuilds its palette (play-once-and-hold; freeze after settle). SP3 officer placement folds in as a held placement clip.

**Tech Stack:** C++17, GoogleTest, GLM, OpenGL (GLFW offscreen for GPU tests), embedded CPython, pybind11-style host bindings.

**Spec:** `docs/superpowers/specs/2026-06-14-sp2-gpu-skeletal-animation-design.md`
**Diagnosis context:** memory `project-bc-character-rigid-skinning`.

---

## Background the engineer needs

A BC body NIF (e.g. `BodyMaleL.NIF`) has **32 NiTriShapes**: **30 rigid** (no skin controller) parented to `Bip01` bone nodes, and **2 skinned** (a `NiTriShapeSkinController` weighting 10 and 22 bones). Two different vertex spaces are in play:

- **Rigid** shapes: `build_mesh_cpu` (`native/src/assets/src/mesh_build.cc`) bakes the shape's own `av` (T·R·S) into the verts, leaving them in **node-local** space (relative to the parent NiNode). They get bound to their parent bone with weight 255 (`model_build.cc` rigid `else` branch).
- **Skinned** shapes: verts are already in **bind-model** space, with multi-bone weights filled by `fill_skin_weights`.

The GPU skinned shader (`native/src/renderer/shaders/skinned.vert`, and the bridge variant) computes `pos = u_model · Σ wᵢ · u_bones[boneᵢ] · v`. For that to pose **both** vertex kinds with one palette of `world_pose·inverse_bind`, **all** verts must be in bind-model space and `u_model` must be the constant instance world. That is fixes 1a + 1b.

Already-correct, reused as-is:
- `compute_inverse_bind_poses` sets `inverse_bind_pose = inverse(world_bind)` per bone (`skeleton_build.cc:120`).
- `build_bone_palette(skeleton, local_pose)` → `palette[i] = world_of(i, local_pose) · inverse_bind(i)` (`bone_palette.cc:8`).
- `sample_pose(clip, skeleton, t)` → per-bone LOCAL transforms, tracks matched by node name (`pose_sampler.cc:11`, header `pose_sampler.h`).
- `load_animation_clips(nif_path)` → `std::vector<AnimationClip>` without a model build (`animation_load.cc:40`).

## File structure / responsibilities

| File | Responsibility | Change |
|---|---|---|
| `native/src/assets/src/mesh_build.cc` | NiTriShape → MeshCpu (node-local bake) | add `world_bind` arg so a rigid shape's verts can be pre-multiplied into bind-model space |
| `native/src/assets/src/model_build.cc` | model assembly, skin/rigid binding | compute each node's bind-world; for rigid shapes bake verts to bind-model space |
| `native/src/renderer/frame.cc` `draw_model` | space-pass draw (static + skinned) | `u_model = world` (not per-node) when skinned |
| `native/src/renderer/bridge_pass.cc` skinned sub-pass | bridge-pass skinned draw | `u_model = inst.world` (not per-node); per-frame palette rebuild |
| `native/src/renderer/animation_update.{h,cc}` (**new**) | per-frame: sample clip → build palette → write `inst.bone_palette` | new unit, GL-free, unit-tested |
| `native/src/scenegraph/include/scenegraph/instance.h` | instance state | add `AnimationState` (clip index, start, loop, sample_at_start, settled) |
| `native/src/scenegraph/.../world.h` + `world.cc` | instance store | `set_animation` / accessor |
| `native/src/host/host_bindings.cc` | Python bindings | `set_instance_animation`; rework `assemble_officer`; remove `sample_placement_pose` |
| `engine/bridge_officers.py` | officer placement | call `set_instance_animation` instead of node-pose |
| `native/src/assets/src/animation_load.cc`, `model_compose.cc`, `assets/animation.h`, `model_compose.h` | node-walk posing path | **remove** `load_pose_locals` / `apply_pose_to_nodes` |
| `native/tools/probe_officer_pose/probe_officer_pose.cc` | headless pose probe | add palette-path assertion |
| `native/tests/...` | tests | bind-model update, posed-palette correctness, sampling/loop, animation_update |

---

## Task 1: Bake rigid verts to bind-model space + skinned `u_model = inst.world`

**Files:**
- Modify: `native/src/assets/src/mesh_build.cc` (function `build_mesh_cpu`)
- Modify: `native/src/assets/include/assets/mesh.h` or the `build_mesh_cpu` declaration site (`native/src/assets/src/model_build.h` — confirm where `build_mesh_cpu` is declared; it is used in `model_build.cc:490`)
- Modify: `native/src/assets/src/model_build.cc:488-546`
- Modify: `native/src/renderer/frame.cc:168-175`
- Modify: `native/src/renderer/bridge_pass.cc` (skinned sub-pass, ~lines 224-237)
- Test: `native/tests/assets/cpu/rigid_bake_test.cc` (new), `native/tests/renderer/skinned_render_test.cc`, `native/tests/renderer/skinned_bridge_test.cc`

### Why the existing `BindPoseMatchesStaticDraw` test must change

`skinned_render_test.cc:196 BindPoseMatchesStaticDraw` currently passes because **both** the skinned and the static reference draw use the per-node walk at bind pose (identity palette), so vertex space is irrelevant. After 1b the skinned path uses `u_model = world`; the static reference still uses the per-node walk. For the **30 rigid** shapes the two stay identical (1a bakes their verts to bind-model space, so `world · v_bindmodel == world_per_node · v_nodelocal`). For the **2 skinned** shapes the static reference mis-draws them (it applies `world_bind(node)` to already-model-space verts) while the corrected skinned path draws them right — so they legitimately diverge. The static walk was never a valid reference for true skinning; it only coincided. Replace that test with a posed-correctness test (below) plus a non-empty bind render.

- [ ] **Step 1: Write the failing CPU test for the rigid bind-model bake**

Create `native/tests/assets/cpu/rigid_bake_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <nif/file.h>
#include "../../src/assets/src/model_build.h"
#include <assets/path_resolver.h>
#include <assets/model.h>
#include <filesystem>

// A rigid BC body part's vertices must be baked into BIND-MODEL space so the
// GPU palette (world_pose * inverse_bind) poses them. Proof: for a rigid shape
// on bone B, at BIND pose palette[B] == identity, so the drawn world position
// is world * v_bindmodel. v_bindmodel must equal world_bind(B) * v_nodelocal.
// We verify build_model now stores a body whose rigid mesh verts, transformed
// by the inverse bind-world of their bone, land back in a plausible node-local
// box (i.e. the bake was applied: a hand vertex is NO LONGER near the body
// centre but offset by the arm bind transform).
namespace {
const char* kBody =
    "game/data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif";
}

TEST(RigidBake, RigidVertsAreInBindModelSpace) {
    namespace fs = std::filesystem;
    if (!fs::exists(kBody)) GTEST_SKIP() << "asset missing: " << kBody;
    nif::File f = nif::load(kBody);
    assets::PathResolver resolver;
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &resolver;
    ctx.texture_search_paths = {fs::path(kBody).parent_path()};
    ctx.texture_uploader = [](const assets::Image&, bool){ return assets::Texture{}; };
    ctx.mesh_uploader = [](assets::MeshCpu c){ (void)c; return assets::Mesh{}; };
    ctx.keep_cpu_data = true;
    assets::Model m = assets::detail::build_model(f, ctx);
    ASSERT_FALSE(m.skeleton.bones.empty());

    // Find a node high up the arm and a mesh on it. Compute the body's overall
    // bind-model AABB from ALL rigid mesh verts (now in model space): an arm
    // mesh's verts should sit far from the spine in X (arm span ~±32), which is
    // ONLY true if verts are in bind-model space, not node-local (where a hand
    // shape's verts cluster near its own node origin ~|x|<5).
    float max_abs_x = 0.0f;
    for (const auto& mesh : m.meshes) {
        for (const auto& v : mesh.cpu_data().vertices)
            max_abs_x = std::max(max_abs_x, std::abs(v.position.x));
    }
    EXPECT_GT(max_abs_x, 20.0f)
        << "rigid verts look node-local (clustered), not bind-model space";
}
```

Add it to `native/tests/assets/cpu/CMakeLists.txt` (mirror an existing `add_*` entry there — confirm the test-registration macro the file uses and copy it).

- [ ] **Step 2: Run it to verify it fails**

Run: `cmake --build build -j --target assets_tests && ctest --test-dir build -R RigidBake -V`
Expected: FAIL — `max_abs_x` is small (verts still node-local) OR build error if `cpu_data()` accessor differs (confirm the accessor name on `assets::Mesh`; it is used in `probe_officer_pose` via `keep_cpu_data` — grep `cpu_data` under `native/src/assets`).

- [ ] **Step 3: Add the bind-world bake to `build_mesh_cpu`**

In `native/src/assets/src/mesh_build.cc`, extend `build_mesh_cpu` with an optional post-bake transform. Add a parameter `const glm::mat4& extra_model_transform = glm::mat4(1.0f)` to both the declaration (in `model_build.h` or wherever `build_mesh_cpu` is declared) and the definition. After the existing position/normal fill loops, apply it:

```cpp
    // SP2: for rigid character shapes the caller passes the parent node's
    // bind-world transform so verts move from node-local into BIND-MODEL space
    // (the space the GPU palette poses). Identity for everything else, so ships
    // and bridges are byte-identical.
    if (extra_model_transform != glm::mat4(1.0f)) {
        const glm::mat3 n = glm::mat3(extra_model_transform);  // BC scale is uniform/1
        for (auto& v : mesh.vertices) {
            v.position = glm::vec3(extra_model_transform * glm::vec4(v.position, 1.0f));
            v.normal   = glm::normalize(n * v.normal);
        }
    }
```

- [ ] **Step 4: Compute bind-world per node and pass it for rigid shapes in `model_build.cc`**

In `native/src/assets/src/model_build.cc`, just above the mesh loop (after `model.nodes` is populated), add a bind-world helper and a cache:

```cpp
    // Bind-world of each model node (product of node local_transforms root->node).
    // Used to bake RIGID character shapes into bind-model space (SP2).
    std::vector<glm::mat4> node_bind_world(model.nodes.size(), glm::mat4(1.0f));
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& nd = model.nodes[i];
        node_bind_world[i] = nd.parent_index >= 0
            ? node_bind_world[nd.parent_index] * nd.local_transform
            : nd.local_transform;
    }
```

Then change the `build_mesh_cpu` call. The bake must apply ONLY to rigid (no-skin-controller) shapes of a skinned model, so decide the transform before building the mesh. Restructure lines 488-490 + the skin block so the controller is resolved first:

```cpp
        int node_index = find_parent_node_index(f, i, nodes, resolver);

        // Resolve skin controller first so we know whether this shape is rigid.
        const nif::NiTriShapeSkinController* skin = nullptr;
        if (!model.skeleton.bones.empty()) {
            std::uint32_t ctrl = shape->av.obj.controller_link;
            if (ctrl != 0) {
                auto ci = resolver.resolve(ctrl);
                if (ci != LinkResolver::kInvalidIndex && ci < f.blocks.size())
                    skin = std::get_if<nif::NiTriShapeSkinController>(&f.blocks[ci]);
            }
        }
        // RIGID character shape -> bake verts into bind-model space.
        glm::mat4 bake(1.0f);
        if (!model.skeleton.bones.empty() && skin == nullptr &&
            node_index >= 0 && node_index < static_cast<int>(node_bind_world.size()))
            bake = node_bind_world[node_index];

        MeshCpu cpu = build_mesh_cpu(*shape, *data, mat_index, node_index, bake);
```

Then replace the old controller re-resolution inside `if (!model.skeleton.bones.empty())` with use of the already-resolved `skin` (keep `fill_skin_weights` for `skin != nullptr`, keep the parent-bone rigid binding for `skin == nullptr`). Do NOT bake skinned shapes (they are already model-space).

- [ ] **Step 5: Run the CPU test to verify it passes**

Run: `cmake --build build -j --target assets_tests && ctest --test-dir build -R RigidBake -V`
Expected: PASS — `max_abs_x > 20`.

- [ ] **Step 6: Apply `u_model = world` for skinned draws in `frame.cc`**

In `native/src/renderer/frame.cc`, line ~175, change the per-mesh `u_model`:

```cpp
            // SP2: skinned models carry bind-model verts posed entirely by the
            // bone palette, so the instance world is the model matrix. Static
            // (non-skinned) models keep the node-walk transform.
            prog.set_mat4("u_model", skinned ? world : world_per_node[i]);
```

(`skinned` and `world` are already in scope in `draw_model`.)

- [ ] **Step 7: Apply `u_model = inst.world` in the bridge skinned sub-pass**

In `native/src/renderer/bridge_pass.cc` skinned sub-pass (~lines 224-237), drop the per-node `world_per_node` composition for the draw and pass `inst.world` as `u_model`:

```cpp
            // SP2: bind-model verts + palette => u_model is the instance world.
            for (std::size_t i = 0; i < m->nodes.size(); ++i) {
                const auto& node = m->nodes[i];
                for (int mesh_idx : node.meshes) {
                    const auto& mesh = m->meshes[mesh_idx];
                    const auto& mat = (mesh.material_index() >= 0
                        ? m->materials[mesh.material_index()] : assets::Material{});
                    draw_mesh(*m, mesh, mat, skin_shader, inst.world, white, t);
                }
            }
```

(The node loop now only enumerates meshes; the world_per_node vector for the skinned sub-pass is removed.)

- [ ] **Step 8: Replace the GPU bind-pose test premise**

In `native/tests/renderer/skinned_render_test.cc`, replace `BindPoseMatchesStaticDraw` (the static reference is invalid for true skinning post-1b — see the note above) with a non-empty + stable bind render, and add the posed-palette correctness test:

```cpp
TEST_F(SkinnedRenderTest, BindPoseRendersNonEmpty) {
    std::vector<glm::mat4> palette =
        renderer::build_bone_palette(model_h->skeleton, /*local_pose=*/nullptr);
    auto buf = render_skinned(palette);             // existing helper
    EXPECT_GT(foreground_count(buf), 0)             // existing helper
        << "skinned bind-pose render was empty";
}

// A pure +X world translation applied to every bone shifts the whole
// silhouette right — proves the palette reaches the shader. (Adapted from the
// retired TranslatedPaletteShiftsSilhouette; KEEP if already present.)
```

Keep `TranslatedPaletteShiftsSilhouette` (still valid). If `render_skinned` / `foreground_count` differ in name, reuse whatever the fixture already defines (grep the file).

- [ ] **Step 9: Update the bridge skinned GPU test for the new `u_model`**

`native/tests/renderer/skinned_bridge_test.cc` tests `SkinnedCharacterRendersLitByBridgeAmbient` (non-empty) and `DarkBridgeAmbientYieldsBlackCharacter`. Both are coverage tests and should still pass (a posed/bind character still lights up). Run them; if `set_world_transform(iid, identity)` previously relied on per-node placement, confirm the character still lands on screen (the body's bind-model verts are centred near the origin; the test camera already frames it). No code change expected — just verify.

- [ ] **Step 10: Build and run the renderer GPU tests**

Run: `cmake --build build -j && ctest --test-dir build -R "Skinned|RigidBake|BonePalette" -V`
Expected: PASS (GPU tests `GTEST_SKIP` if no GL context / asset — that is acceptable in headless CI but they must pass locally where GL + `game/` exist).

- [ ] **Step 11: Commit**

```bash
git add native/src/assets/src/mesh_build.cc native/src/assets/src/model_build.cc \
        native/src/assets/src/model_build.h native/src/renderer/frame.cc \
        native/src/renderer/bridge_pass.cc native/tests/assets/cpu/rigid_bake_test.cc \
        native/tests/assets/cpu/CMakeLists.txt native/tests/renderer/skinned_render_test.cc
git commit -m "feat(sp2): bake rigid character verts to bind-model space; skinned u_model=inst.world

Rigid BC body shapes were node-local, so a posed bone palette sheared them.
Bake them into bind-model space (gated on skeleton present + no skin
controller) and draw skinned models with u_model=instance world so one palette
poses rigid + skinned shapes uniformly. Ships/bridges (no skeleton) unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Renderer-owned per-frame animation (state + palette rebuild)

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h`
- Modify: `native/src/scenegraph/include/scenegraph/world.h`, `native/src/scenegraph/world.cc` (or wherever `set_bone_palette` is defined)
- Create: `native/src/renderer/include/renderer/animation_update.h`, `native/src/renderer/animation_update.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `animation_update.cc`)
- Test: `native/tests/renderer/animation_update_test.cc` (new)

- [ ] **Step 1: Add `AnimationState` to `Instance`**

In `native/src/scenegraph/include/scenegraph/instance.h`, inside `struct Instance` (after `bone_palette`):

```cpp
    /// SP2 animation playback. clip_index < 0 means "not animated" (palette is
    /// left as set, or bind). The clip lives in the instance's Model::animations.
    /// Runtime state, never serialized.
    struct AnimationState {
        int    clip_index     = -1;
        double start_wall_time = 0.0;
        bool   loop           = false;
        bool   sample_at_start = false;  // movement clips evaluate from t=0
        bool   settled        = false;   // non-loop clip reached its end
    };
    AnimationState animation;
```

- [ ] **Step 2: Add `set_animation` to `World`**

In `native/src/scenegraph/include/scenegraph/world.h` declare, and define in the matching `.cc`:

```cpp
    void set_animation(InstanceId id, Instance::AnimationState state);
```
```cpp
void World::set_animation(InstanceId id, Instance::AnimationState state) {
    if (Instance* in = get(id)) { in->animation = state; in->animation.settled = false; }
}
```

- [ ] **Step 3: Write the failing unit test for `update_animations`**

Create `native/tests/renderer/animation_update_test.cc`. `update_animations` walks alive instances, and for each animated one samples its model's clip and writes `bone_palette`. Test with a 2-bone synthetic skeleton + a 1-track clip rotating bone 1, and a fake model-lookup:

```cpp
#include <gtest/gtest.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/epsilon.hpp>
#include <scenegraph/world.h>
#include <assets/model.h>
#include <renderer/animation_update.h>

namespace {
assets::Model two_bone_model_with_clip() {
    assets::Model m;
    // skeleton: bone0 root at origin, bone1 child translated +Y by 10.
    assets::Bone b0; b0.name = "root"; b0.parent_index = -1;
    b0.local_transform = glm::mat4(1.0f);
    assets::Bone b1; b1.name = "j1"; b1.parent_index = 0;
    b1.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0,10,0));
    m.skeleton.bones = {b0, b1};
    m.skeleton.root_bone_index = 0;
    // inverse-bind = inverse(world_bind)
    m.skeleton.bones[0].inverse_bind_pose = glm::inverse(b0.local_transform);
    m.skeleton.bones[1].inverse_bind_pose =
        glm::inverse(b0.local_transform * b1.local_transform);
    // clip: rotate j1 90deg about Z, single key at t=0 and t=1.
    assets::AnimationClip clip; clip.name = "c"; clip.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack tr; tr.target_node_name = "j1";
    glm::quat q = glm::angleAxis(glm::radians(90.0f), glm::vec3(0,0,1));
    tr.rotation = {{0.0f, q}, {1.0f, q}};
    clip.tracks = {tr};
    m.animations = {clip};
    return m;
}
}

TEST(AnimationUpdate, PlayOnceHoldRebuildsThenSettles) {
    assets::Model model = two_bone_model_with_clip();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };

    scenegraph::World world;
    auto id = world.create_instance(/*model=*/1);
    scenegraph::Instance::AnimationState st;
    st.clip_index = 0; st.start_wall_time = 100.0; st.loop = false;
    world.set_animation(id, st);

    // Before the clip ends: palette rebuilt, not settled.
    renderer::update_animations(world, lookup, /*now=*/100.5);
    ASSERT_TRUE(world.get(id));
    EXPECT_FALSE(world.get(id)->animation.settled);
    EXPECT_EQ(world.get(id)->bone_palette.size(), 2u);

    // After duration: clamped to end, marked settled.
    renderer::update_animations(world, lookup, /*now=*/200.0);
    EXPECT_TRUE(world.get(id)->animation.settled);
    auto settled_palette = world.get(id)->bone_palette;

    // A later call must NOT rebuild a settled, non-looping instance: palette
    // identical and still settled.
    renderer::update_animations(world, lookup, /*now=*/300.0);
    EXPECT_TRUE(world.get(id)->animation.settled);
    EXPECT_EQ(world.get(id)->bone_palette.size(), 2u);
}
```

Register it in `native/tests/renderer/CMakeLists.txt` (copy an existing `add_*`/`target_link_libraries` entry; link `renderer`, `assets`, `scenegraph`, `gtest_main`). This is a CPU/no-GL test.

- [ ] **Step 4: Run it to verify it fails**

Run: `cmake --build build -j --target renderer_tests 2>&1 | tail -5`
Expected: FAIL to compile — `renderer/animation_update.h` and `update_animations` do not exist yet.

- [ ] **Step 5: Implement `animation_update`**

Create `native/src/renderer/include/renderer/animation_update.h`:

```cpp
#pragma once
#include <functional>
#include <scenegraph/world.h>
namespace assets { struct Model; }
namespace renderer {
/// Per-frame: for every alive instance with animation.clip_index >= 0, sample
/// its model's clip at (now - start) and rebuild bone_palette. Play-once-hold:
/// non-looping clips clamp at duration and set settled=true; a settled
/// non-looping instance is skipped on later frames. Looping clips wrap via fmod
/// and never settle. `lookup` resolves an instance's model_handle to its Model.
using ModelLookup = std::function<const assets::Model*(scenegraph::ModelHandle)>;
void update_animations(scenegraph::World& world, const ModelLookup& lookup,
                       double now_wall_time);
}
```

Create `native/src/renderer/animation_update.cc`:

```cpp
#include "renderer/animation_update.h"
#include "renderer/bone_palette.h"
#include "renderer/pose_sampler.h"
#include <assets/model.h>
#include <cmath>

namespace renderer {

void update_animations(scenegraph::World& world, const ModelLookup& lookup,
                       double now_wall_time) {
    world.for_each_alive([&](scenegraph::Instance& inst) {
        auto& a = inst.animation;
        if (a.clip_index < 0) return;
        if (a.settled && !a.loop) return;            // frozen after hold
        const assets::Model* m = lookup(inst.model_handle);
        if (!m || a.clip_index >= static_cast<int>(m->animations.size())) return;
        const assets::AnimationClip& clip = m->animations[a.clip_index];
        const float dur = clip.duration_seconds;
        double elapsed = now_wall_time - a.start_wall_time;
        if (elapsed < 0.0) elapsed = 0.0;
        float t;
        if (a.loop) {
            t = dur > 0.0f ? static_cast<float>(std::fmod(elapsed, dur)) : 0.0f;
        } else if (elapsed >= dur) {
            t = dur;
            a.settled = true;                        // last rebuild, then freeze
        } else {
            t = static_cast<float>(elapsed);
        }
        std::vector<glm::mat4> pose = sample_pose(clip, m->skeleton, t);
        inst.bone_palette = build_bone_palette(m->skeleton, &pose);
    });
}

}  // namespace renderer
```

Add `src/animation_update.cc` to the `renderer` library sources in `native/src/renderer/CMakeLists.txt`.

- [ ] **Step 6: Run the unit test to verify it passes**

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R AnimationUpdate -V`
Expected: PASS.

- [ ] **Step 7: Call `update_animations` each frame before the bridge/skinned passes**

In `native/src/host/host_bindings.cc` `frame()` (the per-frame submit, where `lookup`/`resolve_model` and `g_world` and the wall clock are in scope — see `frame.cc` callers and `lookup` at host_bindings.cc:325), call it once per frame before `BridgePass::render` and the space skinned draw:

```cpp
    renderer::update_animations(g_world, lookup, /*now=*/<the same wall_time
        passed to draw_model / flip controllers>);
```

Use the existing per-frame wall time already threaded into `draw_model` (`now`/`wall_time` at host_bindings.cc:337/345). Add `#include <renderer/animation_update.h>`.

- [ ] **Step 8: Build the whole renderer + host and run renderer tests**

Run: `cmake --build build -j 2>&1 | grep -iE "error:|Built target dauntless$" | tail -3 && ctest --test-dir build -R "AnimationUpdate|Skinned" 2>&1 | tail -3`
Expected: builds clean; tests pass.

- [ ] **Step 9: Commit**

```bash
git add native/src/scenegraph/include/scenegraph/instance.h \
        native/src/scenegraph/include/scenegraph/world.h native/src/scenegraph/world.cc \
        native/src/renderer/include/renderer/animation_update.h \
        native/src/renderer/animation_update.cc native/src/renderer/CMakeLists.txt \
        native/src/host/host_bindings.cc \
        native/tests/renderer/animation_update_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(sp2): renderer-owned per-frame animation; play-once-hold + freeze

Instance carries AnimationState (clip, start, loop, settled). update_animations
samples each animated instance's clip at now-start and rebuilds its bone palette
via the existing sample_pose + build_bone_palette; non-looping clips clamp at
duration and freeze (settled) so held officers cost nothing per frame.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `set_instance_animation` binding + `assemble_officer` rework + remove node-walk posing

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`assemble_officer`, add `set_instance_animation`, remove `sample_placement_pose`)
- Modify: `native/src/assets/src/animation_load.cc`, `native/src/assets/include/assets/animation.h` (remove `load_pose_locals`)
- Modify: `native/src/assets/src/model_compose.cc`, `native/src/assets/include/assets/model_compose.h` (remove `apply_pose_to_nodes`)
- Modify/remove: `native/tests/assets/cpu/apply_pose_to_nodes_test.cc`
- Test: `native/tests/assets/cpu/officer_clip_load_test.cc` (new — assemble loads the placement clip into `model.animations`)

- [ ] **Step 1: Write the failing test — `assemble_officer` puts the placement clip in `model.animations`**

`assemble_officer` requires a GL context (it uploads), so test the underlying contract at the asset layer instead: a composed officer model with the placement clip loaded into `animations`. Create `native/tests/assets/cpu/officer_clip_load_test.cc` exercising `load_animation_clips` + assignment (the exact operation `assemble_officer` will do):

```cpp
#include <gtest/gtest.h>
#include <assets/animation.h>
#include <filesystem>

TEST(OfficerClipLoad, PlacementClipLoadsNonEmpty) {
    namespace fs = std::filesystem;
    const char* clip = "game/data/animations/db_stand_t_l.nif";
    if (!fs::exists(clip)) GTEST_SKIP() << "asset missing: " << clip;
    auto clips = assets::load_animation_clips(clip);
    ASSERT_FALSE(clips.empty());
    EXPECT_GT(clips.front().duration_seconds, 0.0f);
    EXPECT_FALSE(clips.front().tracks.empty());
}
```

Register in `native/tests/assets/cpu/CMakeLists.txt`.

- [ ] **Step 2: Run it to verify it builds/fails appropriately**

Run: `cmake --build build -j --target assets_tests && ctest --test-dir build -R OfficerClipLoad -V`
Expected: PASS if asset present (this documents the contract); SKIP otherwise. (It exercises an existing function, so it should pass — its purpose is to pin the behaviour `assemble_officer` relies on.)

- [ ] **Step 3: Rework `assemble_officer` to keep the skeleton and load the clip**

In `native/src/host/host_bindings.cc`, replace the placement block (the `if (!placement.empty())` node-walk posing) with clip loading; keep the skeleton intact:

```cpp
              // SP2: keep the skeleton; load the placement clip so the per-frame
              // animation updater can pose it. No node-walk, no skeleton clear.
              const std::filesystem::path placement = as_path(placement_nif);
              if (!placement.empty()) {
                  composed.animations = assets::load_animation_clips(placement);
              }
```

Remove the now-unused `sample_at_start` handling here (it moves to `set_instance_animation`). Keep the `placement_nif` / `sample_at_start` parameters on `assemble_officer` for source compatibility, but `sample_at_start` is now unused inside it (the Python caller forwards it to `set_instance_animation`). Update the binding docstring accordingly.

- [ ] **Step 4: Add the `set_instance_animation` binding**

In `native/src/host/host_bindings.cc`, near `set_instance_bone_palette`:

```cpp
    m.def("set_instance_animation",
          [](scenegraph::InstanceId id, int clip_index, bool loop,
             bool sample_at_start) {
              auto* in = g_world.get(id);
              if (!in) return;
              scenegraph::Instance::AnimationState st;
              st.clip_index = clip_index;
              st.loop = loop;
              st.sample_at_start = sample_at_start;
              st.start_wall_time = g_last_frame_wall_time;  // see note
              g_world.set_animation(id, st);
          },
          py::arg("iid"), py::arg("clip_index"), py::arg("loop") = false,
          py::arg("sample_at_start") = false,
          "SP2: play model.animations[clip_index] on this instance. loop=false "
          "(default) plays once and holds the last frame; the renderer rebuilds "
          "the bone palette each frame until it settles.");
```

If there is no `g_last_frame_wall_time` global, use the same wall-clock source `frame()` reads (grep the clock used for flip controllers / `update_animations`); set `start_wall_time` to "now". The exact value only sets the animation's t=0 origin.

- [ ] **Step 5: Remove `sample_placement_pose`, `load_pose_locals`, `apply_pose_to_nodes`**

Delete:
- `sample_placement_pose` binding in `host_bindings.cc`.
- `load_pose_locals` (decl in `assets/animation.h`, def in `animation_load.cc`) — keep `load_animation_clips` and the `av_to_local` helper if `load_animation_clips` still needs it; if `av_to_local` becomes unused, remove it too.
- `apply_pose_to_nodes` (decl in `model_compose.h`, def in `model_compose.cc`).
- `native/tests/assets/cpu/apply_pose_to_nodes_test.cc` (the function is gone) — remove the file and its `CMakeLists.txt` registration.

- [ ] **Step 6: Build and fix fallout**

Run: `cmake --build build -j 2>&1 | grep -iE "error:" | head`
Expected: no errors. Fix any remaining references to the removed symbols (e.g. `pose_sample.h` include in `animation_load.cc` if now unused; the `<assets/pose_sample.h>` include and `sample_track_trs` use inside `load_pose_locals` go away with it — but `sample_track_trs` itself stays, it is used by `sample_pose`).

- [ ] **Step 7: Run the focused asset + host tests**

Run: `cmake --build build -j --target assets_tests && ctest --test-dir build -R "OfficerClipLoad|Compose|RigidBake|LoadAnimation" 2>&1 | tail -4`
Expected: PASS (no `ApplyPose` target remains).

- [ ] **Step 8: Commit**

```bash
git add native/src/host/host_bindings.cc native/src/assets/src/animation_load.cc \
        native/src/assets/include/assets/animation.h native/src/assets/src/model_compose.cc \
        native/src/assets/include/assets/model_compose.h \
        native/tests/assets/cpu/officer_clip_load_test.cc native/tests/assets/cpu/CMakeLists.txt
git rm native/tests/assets/cpu/apply_pose_to_nodes_test.cc
git commit -m "feat(sp2): assemble_officer loads placement clip; set_instance_animation; drop node-walk posing

assemble_officer keeps the skeleton and loads the placement clip into
model.animations. New set_instance_animation binding selects the clip + play
mode per instance. Removes the dead node-walk posing path (sample_placement_pose,
load_pose_locals, apply_pose_to_nodes) superseded by GPU palette skinning.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Wire `bridge_officers.py`, extend the probe, live-verify

**Files:**
- Modify: `engine/bridge_officers.py`
- Modify: `native/tools/probe_officer_pose/probe_officer_pose.cc`
- Test: `tests/unit/test_bridge_officers.py`

- [ ] **Step 1: Update the Python test for the new placement contract**

In `tests/unit/test_bridge_officers.py`, the fake host must accept `set_instance_animation`. Update the fake/host double so `_place_one` calls `assemble_officer(...)`, `create_bridge_instance`, `set_world_transform`, then `set_instance_animation(iid, 0, loop=False, sample_at_start=<from placement>)`. Add an assertion that `set_instance_animation` was called once per placed officer with `clip_index == 0`:

```python
def test_place_one_sets_animation(monkeypatch):
    calls = []
    host = _FakeHost(record=calls)           # extend the existing fake
    place_officers([_fake_officer("DBTactical")], host, _DATA_ROOT)
    anim = [c for c in calls if c[0] == "set_instance_animation"]
    assert len(anim) == 1
    assert anim[0][2] == 0                    # clip_index
```

(Match the existing fake-host structure in the file; the key point is recording the new call.)

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_officers.py -q 2>&1 | tail -8`
Expected: FAIL — `bridge_officers` does not call `set_instance_animation` yet (or the fake lacks it).
**Do NOT run the full suite (OOMs the host).**

- [ ] **Step 3: Call `set_instance_animation` in `_place_one`**

In `engine/bridge_officers.py` `_place_one`, after `set_world_transform`:

```python
        host.set_world_transform(iid, _BRIDGE_IDENTITY_MAT4)
        # SP2: play the placement clip once and hold (clip is animations[0] of
        # the assembled model). sample_at_start = the placement's movement flag.
        host.set_instance_animation(
            iid, 0, False, bool(placement.get("sample_at_start")))
```

- [ ] **Step 4: Run the focused Python test to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_officers.py -q 2>&1 | tail -5`
Expected: PASS.

- [ ] **Step 5: Extend the probe with the palette-path assertion**

In `native/tools/probe_officer_pose/probe_officer_pose.cc`, after building the body, add a pass that: loads the placement clip (`load_animation_clips`), samples it (`sample_pose(clip, skeleton, dur)`), builds the palette (`build_bone_palette`), and computes the L-Hand vertex/joint world via `inst.world(identity) · palette[handBone] · v` — then prints it. The goal: the palette-path L-Hand world matches the node-walk's posed L-Hand (Z≈23 for `db_stand_t_l`), proving the palette path reproduces the intended pose. (Link `renderer` for `build_bone_palette`/`sample_pose`; add to the probe's `target_link_libraries`.)

```cpp
    // SP2 palette-path check: world of bone "Bip01 L Hand" via the GPU formula.
    {
        auto clips = assets::load_animation_clips(place_nif);
        if (!clips.empty()) {
            auto pose = renderer::sample_pose(clips.front(), fresh().skeleton,
                                              clips.front().duration_seconds);
            auto palette = renderer::build_bone_palette(fresh().skeleton, &pose);
            for (std::size_t b = 0; b < /*skeleton*/ fresh().skeleton.bones.size(); ++b)
                if (fresh().skeleton.bones[b].name == "Bip01 L Hand") {
                    glm::vec4 origin = palette[b] * glm::vec4(0,0,0,1);  // bone origin
                    std::printf("PALETTE L-Hand bone origin world = (%.1f %.1f %.1f)\n",
                                origin.x, origin.y, origin.z);
                }
        }
    }
```

(Note: `palette[b] * (0,0,0,1)` gives `world_pose(b) · inverse_bind(b) · 0` = `world_pose(b)` translation = the posed bone origin — directly comparable to the node-walk's posed hand node world.)

- [ ] **Step 6: Build the probe and verify the palette path matches the node-walk pose**

Run:
```bash
cmake -B build -S . >/dev/null && cmake --build build -j --target probe_officer_pose 2>&1 | grep -iE "error:" 
./build/native/tools/probe_officer_pose/probe_officer_pose \
  game/data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif \
  game/data/animations/db_stand_t_l.nif 2>&1 | grep -E "PALETTE|POSED"
```
Expected: `PALETTE L-Hand bone origin world ≈ (-33-ish, -106-ish, 23-ish)` — the posed hand at hip height, matching the node-walk POSED hand (Z≈23). If it instead shows bind (Z≈64), the palette/inverse-bind wiring is wrong — debug before the live cycle.

- [ ] **Step 7: Rebuild `dauntless` and hand off for live verification**

Run: `cmake --build build -j 2>&1 | grep -iE "error:|Built target dauntless$" | tail -2`
Then ask the user to run `./build/dauntless --developer`, load a bridge, and confirm: officers stand **correctly posed** at their stations — arms at sides, no exploding shards, both rigid and skinned shapes coherent; movement-station officers (Science/Engineer) play their walk-in once and hold. **The user performs the live visual check** (no synthetic input/screenshots on their workstation).

- [ ] **Step 8: Commit**

```bash
git add engine/bridge_officers.py native/tools/probe_officer_pose/probe_officer_pose.cc \
        native/tools/probe_officer_pose/CMakeLists.txt tests/unit/test_bridge_officers.py
git commit -m "feat(sp2): officers play placement clip via set_instance_animation; probe palette assertion

bridge_officers wires each placed officer to play its placement clip once-and-
hold. probe_officer_pose now also drives the GPU palette path and prints the
posed L-Hand world so the palette pose can be checked headlessly against the
node-walk reference.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-review checklist (completed by plan author)

- **Spec coverage:** 1a bind-model bake → Task 1 (steps 1-5); 1b u_model → Task 1 (steps 6-7); posed-palette correctness → Task 1 step 8 + Task 4 probe; animation state + per-frame rebuild + freeze → Task 2; clip into `model.animations` + `set_instance_animation` + remove node-walk → Task 3; bridge_officers wiring + probe + live verify → Task 4. CPU sampling/loop test → Task 2 step 3. ✓
- **Skinned-vs-static test premise:** explicitly addressed (Task 1 step 8 replaces the now-invalid `BindPoseMatchesStaticDraw`).
- **Risks from spec:** ships/bridge regression guarded by the skeleton gate (Task 1) — verify via existing ship/bridge render tests in Task 1 step 10; F7 preview covered by the main-pass `u_model` change (Task 1 step 6) + bind render test.
- **Type consistency:** `AnimationState{clip_index,start_wall_time,loop,sample_at_start,settled}`, `World::set_animation`, `update_animations(world, lookup, now)`, `set_instance_animation(iid, clip_index, loop, sample_at_start)` used consistently across Tasks 2-4.

## Verification constraints (apply throughout)

- **Never** run the full pytest suite — it OOMs the host (>100 GB RAM). Use focused files/`-k`.
- Rebuild **`dauntless`** (or full `cmake --build build -j`), not just the `_dauntless_host` module — `host_bindings.cc` compiles into both, and the live binary is `./build/dauntless`.
- Shader files are unchanged here; if that changes, re-run `cmake -B build -S .` before `--build` (shader edits aren't picked up otherwise).
- The **user** performs all live visual verification — no synthetic desktop input or full-screen capture on their workstation.
