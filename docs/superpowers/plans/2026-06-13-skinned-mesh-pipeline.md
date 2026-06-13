# Skinned-Mesh GPU Pipeline (SP1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render a skinned character NIF (e.g. `BodyMaleL.nif`) deformed by a GPU bone-matrix palette held at bind pose, with the ship/bridge render path left byte-identical.

**Architecture:** A separate skinned shader program coexists with the static `opaque` program. `draw_model` branches on `model.skeleton.bones.empty()`: empty (ships/bridge) → static program unchanged; non-empty → skinned program with an uploaded bone palette. Per-vertex bone indices/weights are filled at model-build time from the already-parsed `NiTriShapeSkinController`; the palette is `world_pose · inverse_bind`, which at bind pose is identity, so a skinned draw reproduces the static mesh.

**Tech Stack:** C++17, OpenGL 3.3 / GLSL 330, GoogleTest, glm. Build from `build/` only (`cmake -B build -S . && cmake --build build -j`).

**Spec:** `docs/superpowers/specs/2026-06-13-skinned-mesh-pipeline-design.md`

---

## Conventions the implementer must know

- **One build tree:** `build/`. Binary `build/dauntless`. Never build from inside `native/`.
- **Shaders are embedded at configure time.** A `.vert`/`.frag` becomes `renderer::shader_src::<symbol>` via `embed_shader(...)` in `native/src/renderer/CMakeLists.txt`. **Adding or editing a shader requires re-running `cmake -B build -S .`** before `cmake --build build` — a plain rebuild will NOT pick it up.
- **Rotation/transform convention:** column-vector. `glm::mat4` from `av_to_local_transform` stores translation in column 3. World transform of a child is `parent_world * child_local`.
- **Run native tests:** `ctest --test-dir build -R <regex> --output-on-failure` (or run the test binary directly). Do **not** run the Python `pytest` suite — it OOMs the machine.
- **Existing precedents to mirror:**
  - Skin bone-link resolution: `native/src/assets/src/skeleton_build.cc:gather_bone_block_indices` (`resolver.resolve(link)` → block index → bone).
  - Controller-link follow: `native/src/assets/src/model_build.cc:410-413` (NiFlipController via `prop->controller_link`).
  - Offscreen GL test harness: `native/tests/renderer/frame_test.cc` (hidden `renderer::Window`, `Pipeline`, `AssetCache`, project-root NIF paths).
  - Uniform-array setter to mirror: `native/src/renderer/shader.cc:set_vec4_array`.
  - Dev keybinding: `engine/dev_mode.py:register_dev_keybinding(key, handler, description)`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `native/src/assets/src/skeleton_build.cc` (modify) | Compute `inverse_bind_pose` per bone (world-bind compose + invert) | 1 |
| `native/src/assets/src/skin_weights.h` / `.cc` (create) | Pure `fill_skin_weights()` — controller tuples → per-vertex top-4 weights | 2 |
| `native/src/assets/src/model_build.cc` (modify) | Locate each shape's skin controller, build skin-bone→skeleton-bone map, call `fill_skin_weights` | 2 |
| `native/src/renderer/bone_palette.h` / `.cc` (create) | Pure `build_bone_palette(skeleton, pose?)` → `vector<mat4>` + 128 guard | 3 |
| `native/src/renderer/shader.h` / `.cc` (modify) | `set_mat4_array()` | 4 |
| `native/src/renderer/shaders/skinned.vert` (create) | Palette-blend vertex shader; reuses `opaque.frag` | 4 |
| `native/src/renderer/CMakeLists.txt` (modify) | `embed_shader(... skinned.vert skinned_vs)` | 4 |
| `native/src/renderer/pipeline.h` / `pipeline.cc` (modify) | `skinned_shader()` accessor + construction | 4 |
| `native/src/renderer/frame.cc` + `include/renderer/frame.h` (modify) | `draw_model` skinned branch (palette param); opaque-pass wiring | 5 |
| `native/tests/renderer/skinned_render_test.cc` (create) | Offscreen GL: bind-pose==static; palette-math centroid shift | 5 |
| `native/src/host/host_bindings.cc` (modify) | `spawn_test_character` / `despawn_test_character` bindings | 6 |
| `engine/renderer.py` (modify) | Python wrappers for the two bindings | 6 |
| `engine/dev_keybindings.py` (modify) | Register `--developer` keybinding toggling the preview | 6 |

---

### Task 1: Inverse-bind-pose computation in `build_skeleton`

**Files:**
- Modify: `native/src/assets/src/skeleton_build.cc`
- Test: `native/tests/assets/skeleton_build_test.cc` (create if absent; otherwise add cases)

Each `Bone` already has `name`, `parent_index`, `local_transform`. `inverse_bind_pose` is left identity today. Compute it as `inverse(world_bind)` where `world_bind(bone) = world_bind(parent) · local_transform(bone)`.

- [ ] **Step 1: Write the failing test**

Add to `native/tests/assets/skeleton_build_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <assets/skeleton.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/epsilon.hpp>

// Helper exposed for testing: fills inverse_bind_pose for every bone from
// the bones' local_transform + parent_index chain.
namespace assets::detail { void compute_inverse_bind_poses(Skeleton&); }

namespace {
bool mat_near(const glm::mat4& a, const glm::mat4& b, float eps = 1e-4f) {
    for (int c = 0; c < 4; ++c)
        for (int r = 0; r < 4; ++r)
            if (std::abs(a[c][r] - b[c][r]) > eps) return false;
    return true;
}
}

TEST(InverseBindPose, BindPosePaletteIsIdentityPerBone) {
    // Root translated +X by 2; child translated +Y by 3 in root's local frame.
    assets::Skeleton sk;
    assets::Bone root;  root.name = "root";  root.parent_index = -1;
    root.local_transform  = glm::translate(glm::mat4(1.0f), glm::vec3(2, 0, 0));
    assets::Bone child; child.name = "child"; child.parent_index = 0;
    child.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 3, 0));
    sk.bones = {root, child};
    sk.root_bone_index = 0;

    assets::detail::compute_inverse_bind_poses(sk);

    // world_bind(child) = T(+x2) * T(+y3); palette at bind = world_bind * inverse_bind == I.
    glm::mat4 world_root  = sk.bones[0].local_transform;
    glm::mat4 world_child = world_root * sk.bones[1].local_transform;
    EXPECT_TRUE(mat_near(world_root  * sk.bones[0].inverse_bind_pose, glm::mat4(1.0f)));
    EXPECT_TRUE(mat_near(world_child * sk.bones[1].inverse_bind_pose, glm::mat4(1.0f)));
    // child inverse-bind must equal inverse of its composed world transform.
    EXPECT_TRUE(mat_near(sk.bones[1].inverse_bind_pose, glm::inverse(world_child)));
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j assets_tests && ctest --test-dir build -R InverseBindPose --output-on-failure`
Expected: FAIL to link (`compute_inverse_bind_poses` undefined).

- [ ] **Step 3: Implement**

In `native/src/assets/src/skeleton_build.cc`, add inside `namespace assets::detail` (not the anonymous namespace, so the test can link it) a function and call it at the end of `build_skeleton` before `return out;`:

```cpp
void compute_inverse_bind_poses(Skeleton& sk) {
    // world_bind(i) composed by walking up the parent chain. Bones are not
    // guaranteed to be parent-before-child ordered, so resolve each bone's
    // world transform by collecting its chain to the root.
    auto world_bind = [&](int i) {
        glm::mat4 w(1.0f);
        // Collect chain leaf..root, then multiply root..leaf.
        std::vector<int> chain;
        for (int b = i; b != -1; b = sk.bones[b].parent_index) chain.push_back(b);
        for (auto it = chain.rbegin(); it != chain.rend(); ++it)
            w = w * sk.bones[*it].local_transform;
        return w;
    };
    for (std::size_t i = 0; i < sk.bones.size(); ++i)
        sk.bones[i].inverse_bind_pose =
            glm::inverse(world_bind(static_cast<int>(i)));
}
```

Add its declaration to `native/src/assets/src/skeleton_build.h` inside `namespace assets::detail`:

```cpp
/// Fill every bone's inverse_bind_pose = inverse(world-bind transform),
/// where world-bind composes local_transform down the parent chain.
void compute_inverse_bind_poses(Skeleton& skeleton);
```

And call it at the end of `build_skeleton`, just before `return out;`:

```cpp
    compute_inverse_bind_poses(out.skeleton);
    return out;
```

Ensure `#include <glm/gtc/matrix_inverse.hpp>` or `<glm/glm.hpp>` provides `glm::inverse` (already transitively available via existing includes; add `#include <glm/gtc/matrix_transform.hpp>` only if compilation complains).

- [ ] **Step 4: Run test to verify it passes**

Run: `cmake --build build -j assets_tests && ctest --test-dir build -R InverseBindPose --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/assets/src/skeleton_build.cc native/src/assets/src/skeleton_build.h native/tests/assets/skeleton_build_test.cc
git commit -m "feat(assets): compute bone inverse-bind-pose in build_skeleton"
```

---

### Task 2: `fill_skin_weights` — per-vertex bone indices/weights

**Files:**
- Create: `native/src/assets/src/skin_weights.h`, `native/src/assets/src/skin_weights.cc`
- Modify: `native/src/assets/src/model_build.cc`, `native/src/assets/CMakeLists.txt` (add `skin_weights.cc` to the assets library sources)
- Test: `native/tests/assets/skin_weights_test.cc` (create)

`fill_skin_weights` is **pure**: it takes a parsed controller and a precomputed map from each controller-bone position to a skeleton-bone index, and writes top-4 normalized weights into the mesh vertices. The NIF/resolver glue stays in `model_build.cc`.

- [ ] **Step 1: Write the failing test**

Create `native/tests/assets/skin_weights_test.cc`:

```cpp
#include <gtest/gtest.h>
#include "skin_weights.h"
#include <assets/mesh.h>
#include <nif/block.h>

using assets::detail::fill_skin_weights;

namespace {
assets::MeshCpu make_mesh(int n) {
    assets::MeshCpu m;
    m.vertices.resize(n);
    return m;
}
}

TEST(FillSkinWeights, SingleBoneFullWeightMapsToSkeletonIndex) {
    nif::NiTriShapeSkinController skin;
    skin.num_bones = 1;
    skin.bone_weights = {{ {1.0f, /*vertex_index=*/0, {}} }};
    // controller-bone 0 -> skeleton-bone 7
    std::vector<int> skin_bone_to_skeleton = {7};

    auto mesh = make_mesh(1);
    fill_skin_weights(mesh, skin, skin_bone_to_skeleton);

    EXPECT_EQ(mesh.vertices[0].bone_indices.x, 7);
    EXPECT_EQ(mesh.vertices[0].bone_weights.x, 255);  // 1.0 -> 255 (u8 normalized)
}

TEST(FillSkinWeights, KeepsTopFourAndRenormalizes) {
    nif::NiTriShapeSkinController skin;
    skin.num_bones = 5;
    // Vertex 0 influenced by 5 bones with weights 0.1..0.5; smallest (0.1) dropped.
    skin.bone_weights = {
        {{0.10f, 0, {}}}, {{0.20f, 0, {}}}, {{0.30f, 0, {}}},
        {{0.40f, 0, {}}}, {{0.50f, 0, {}}},
    };
    std::vector<int> map = {0, 1, 2, 3, 4};

    auto mesh = make_mesh(1);
    fill_skin_weights(mesh, skin, map);

    // 4 largest are bones 4,3,2,1 (0.5,0.4,0.3,0.2) summing 1.4; renormalized to 1.0.
    int sum = mesh.vertices[0].bone_weights.x + mesh.vertices[0].bone_weights.y
            + mesh.vertices[0].bone_weights.z + mesh.vertices[0].bone_weights.w;
    EXPECT_NEAR(sum, 255, 2);                  // weights renormalize to ~1.0
    // bone 0 (weight 0.1) must NOT appear among the four indices.
    for (int k = 0; k < 4; ++k) {
        int idx = mesh.vertices[0].bone_indices[k];
        EXPECT_NE(idx, 0);
    }
}

TEST(FillSkinWeights, UnweightedVertexDefaultsToBoneZeroFullWeight) {
    nif::NiTriShapeSkinController skin;
    skin.num_bones = 1;
    skin.bone_weights = {{ {1.0f, 0, {}} }};   // only vertex 0 weighted
    std::vector<int> map = {3};

    auto mesh = make_mesh(2);                   // vertex 1 has no influence
    fill_skin_weights(mesh, skin, map);

    EXPECT_EQ(mesh.vertices[1].bone_indices.x, 0);
    EXPECT_EQ(mesh.vertices[1].bone_weights.x, 255);
    EXPECT_EQ(mesh.vertices[1].bone_weights.y, 0);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j assets_tests 2>&1 | tail -5`
Expected: FAIL — `skin_weights.h` not found / `fill_skin_weights` undefined.

- [ ] **Step 3: Implement the pure function**

Create `native/src/assets/src/skin_weights.h`:

```cpp
// native/src/assets/src/skin_weights.h
#pragma once
#include <vector>
#include <assets/mesh.h>
#include <nif/block.h>

namespace assets::detail {

/// Fill per-vertex bone_indices/bone_weights on `cpu` from a legacy
/// NiTriShapeSkinController. `skin_bone_to_skeleton[i]` maps the controller's
/// i-th bone (0..num_bones-1) to a Skeleton::bones index. Each vertex keeps its
/// 4 largest influences, renormalized so the four u8 weights sum to ~255.
/// Vertices with no influence get bone 0 at full weight.
void fill_skin_weights(MeshCpu& cpu,
                       const nif::NiTriShapeSkinController& skin,
                       const std::vector<int>& skin_bone_to_skeleton);

}  // namespace assets::detail
```

Create `native/src/assets/src/skin_weights.cc`:

```cpp
// native/src/assets/src/skin_weights.cc
#include "skin_weights.h"
#include <algorithm>
#include <array>
#include <cmath>

namespace assets::detail {

void fill_skin_weights(MeshCpu& cpu,
                       const nif::NiTriShapeSkinController& skin,
                       const std::vector<int>& skin_bone_to_skeleton) {
    struct Influence { int bone; float weight; };
    std::vector<std::vector<Influence>> per_vertex(cpu.vertices.size());

    for (std::size_t b = 0; b < skin.bone_weights.size(); ++b) {
        if (b >= skin_bone_to_skeleton.size()) continue;
        int skel_bone = skin_bone_to_skeleton[b];
        if (skel_bone < 0) continue;
        for (const auto& w : skin.bone_weights[b]) {
            if (w.vertex_index >= per_vertex.size()) continue;
            if (w.weight <= 0.0f) continue;
            per_vertex[w.vertex_index].push_back({skel_bone, w.weight});
        }
    }

    for (std::size_t v = 0; v < cpu.vertices.size(); ++v) {
        auto& infl = per_vertex[v];
        std::sort(infl.begin(), infl.end(),
                  [](const Influence& a, const Influence& b) { return a.weight > b.weight; });
        if (infl.size() > 4) infl.resize(4);

        std::array<int, 4>   idx{0, 0, 0, 0};
        std::array<float, 4> wt{0, 0, 0, 0};
        float total = 0.0f;
        for (std::size_t k = 0; k < infl.size(); ++k) {
            idx[k] = infl[k].bone;
            wt[k]  = infl[k].weight;
            total += infl[k].weight;
        }
        if (total <= 0.0f) {           // unweighted vertex -> bone 0 full
            wt[0] = 1.0f; total = 1.0f;
        }
        for (auto& w : wt) w /= total;  // renormalize so the four sum to 1

        auto to_u8 = [](float f) {
            int q = static_cast<int>(std::lround(f * 255.0f));
            return static_cast<std::uint8_t>(std::clamp(q, 0, 255));
        };
        cpu.vertices[v].bone_indices = glm::u8vec4(
            static_cast<std::uint8_t>(std::clamp(idx[0], 0, 255)),
            static_cast<std::uint8_t>(std::clamp(idx[1], 0, 255)),
            static_cast<std::uint8_t>(std::clamp(idx[2], 0, 255)),
            static_cast<std::uint8_t>(std::clamp(idx[3], 0, 255)));
        cpu.vertices[v].bone_weights = glm::u8vec4(
            to_u8(wt[0]), to_u8(wt[1]), to_u8(wt[2]), to_u8(wt[3]));
    }
}

}  // namespace assets::detail
```

Add `src/skin_weights.cc` to the assets library source list in `native/src/assets/CMakeLists.txt` (alongside `src/skeleton_build.cc`), and add `skin_weights_test.cc` to `native/tests/assets/CMakeLists.txt`'s `assets_tests` sources.

- [ ] **Step 4: Run test to verify it passes**

Run: `cmake -B build -S . && cmake --build build -j assets_tests && ctest --test-dir build -R FillSkinWeights --output-on-failure`
Expected: PASS (3 tests).

- [ ] **Step 5: Wire into `model_build.cc`**

In the shape loop in `build_model` (around `native/src/assets/src/model_build.cc:479`, right after `MeshCpu cpu = build_mesh_cpu(...)` and before the mesh is uploaded/pushed), locate the shape's skin controller and apply weights. Add a `#include "skin_weights.h"` at the top, and thread the bone-index map out of `build_skeleton` by keeping the full result:

Change the skeleton step (`model_build.cc:373-375`) from:

```cpp
    auto skel = build_skeleton(f);
    model.skeleton = std::move(skel.skeleton);
```

to keep the map available later:

```cpp
    auto skel = build_skeleton(f);
    const auto nif_block_to_bone = skel.nif_block_to_bone_index;  // copy for weight fill
    model.skeleton = std::move(skel.skeleton);
```

Then, inside the shape loop after `MeshCpu cpu = build_mesh_cpu(*shape, *data, mat_index, node_index);`:

```cpp
        // Skinning: if this shape carries a NiTriShapeSkinController (directly
        // or via its controller chain), map its bones to skeleton indices and
        // fill per-vertex weights. Mirrors gather_bone_block_indices' resolve.
        if (!model.skeleton.bones.empty()) {
            const nif::NiTriShapeSkinController* skin = nullptr;
            std::uint32_t ctrl = shape->controller_link;
            while (ctrl != 0) {
                auto ci = resolver.resolve(ctrl);
                if (ci == LinkResolver::kInvalidIndex || ci >= f.blocks.size()) break;
                if ((skin = std::get_if<nif::NiTriShapeSkinController>(&f.blocks[ci])))
                    break;
                // Follow the controller chain via next_controller_link.
                ctrl = std::visit([](const auto& blk) -> std::uint32_t {
                    if constexpr (requires { blk.next_controller_link; })
                        return blk.next_controller_link;
                    else return 0u;
                }, f.blocks[ci]);
            }
            if (skin) {
                std::vector<int> skin_bone_to_skeleton(skin->bone_links.size(), -1);
                for (std::size_t b = 0; b < skin->bone_links.size(); ++b) {
                    auto blk = resolver.resolve(skin->bone_links[b]);
                    auto it = nif_block_to_bone.find(blk);
                    if (it != nif_block_to_bone.end())
                        skin_bone_to_skeleton[b] = it->second;
                }
                fill_skin_weights(cpu, *skin, skin_bone_to_skeleton);
            }
        }
```

> Note: `shape` is the `const nif::NiTriShape*` already obtained in the loop; `shape->controller_link` is its controller link (`block.h:22`). If the `std::visit`/`requires` chain-follow does not compile against this toolchain, simplify by checking only the direct `shape->controller_link` target — BC character shapes attach the skin controller directly — and follow `next_controller_link` only on `NiTriShapeSkinController` itself, which is rare. Verify against `BodyMaleL.nif` in Step 6.

- [ ] **Step 6: Add an integration assertion against a real asset**

Add to `native/tests/assets/skin_weights_test.cc` (guard on the game asset's presence, mirroring `frame_test.cc`'s project-root path style):

```cpp
#include <assets/model.h>
#include <assets/model_build.h>   // build_model entry (confirm actual header)
#include <nif/file.h>
#include <filesystem>

TEST(FillSkinWeightsAsset, BodyMaleLHasNonTrivialWeights) {
    namespace fs = std::filesystem;
    const fs::path root = fs::path(__FILE__).parent_path()
        .parent_path().parent_path().parent_path();
    const fs::path nif = root / "game" / "data" / "Models" / "Characters"
        / "BodyMaleL.nif";   // confirm exact path during impl
    if (!fs::exists(nif)) GTEST_SKIP() << "BodyMaleL.nif not present";

    // Load + build with keep_cpu_data so vertices are retained, then assert at
    // least one vertex references a non-zero bone with a non-zero weight.
    // (Use the project's standard model-load helper; see model_build.h.)
    // ... build model with ctx.keep_cpu_data = true ...
    // EXPECT that some mesh has a vertex with bone_weights.x > 0 and an index
    // pointing within skeleton.bones.size().
}
```

Fill in the load call using the real `build_model` entry and a `ModelBuildContext` with `keep_cpu_data = true` (see how `frame_test.cc` / `AssetCache` constructs models). The assertion: across `model.meshes`, at least one retained `cpu_data()` vertex has `bone_weights.x > 0` and `bone_indices.x < model.skeleton.bones.size()`. This proves the controller-location glue works on a real character NIF.

- [ ] **Step 7: Run + commit**

Run: `cmake --build build -j assets_tests && ctest --test-dir build -R "FillSkinWeights|FillSkinWeightsAsset" --output-on-failure`
Expected: PASS (asset test PASS or SKIP if `game/` absent).

```bash
git add native/src/assets/src/skin_weights.h native/src/assets/src/skin_weights.cc \
        native/src/assets/src/model_build.cc native/src/assets/CMakeLists.txt \
        native/tests/assets/skin_weights_test.cc native/tests/assets/CMakeLists.txt
git commit -m "feat(assets): fill per-vertex skin weights from NiTriShapeSkinController"
```

---

### Task 3: `build_bone_palette` + 128-bone guard

**Files:**
- Create: `native/src/renderer/bone_palette.h`, `native/src/renderer/bone_palette.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `bone_palette.cc` to the renderer library)
- Test: `native/tests/renderer/bone_palette_test.cc` (create; CPU-only, no GL)

`build_bone_palette` is the function the skinned draw uploads. SP1 calls it with the bind pose (no overrides) → all-identity palette; SP2 will pass animated local transforms. This keeps the math in one tested unit.

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/bone_palette_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <renderer/bone_palette.h>
#include <assets/skeleton.h>
#include <glm/gtc/matrix_transform.hpp>

namespace {
assets::Skeleton two_bone_skeleton() {
    assets::Skeleton sk;
    assets::Bone root; root.parent_index = -1;
    root.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(2, 0, 0));
    assets::Bone child; child.parent_index = 0;
    child.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 3, 0));
    sk.bones = {root, child};
    sk.root_bone_index = 0;
    // bind-pose inverse: inverse of composed world transform.
    sk.bones[0].inverse_bind_pose = glm::inverse(sk.bones[0].local_transform);
    sk.bones[1].inverse_bind_pose =
        glm::inverse(sk.bones[0].local_transform * sk.bones[1].local_transform);
    return sk;
}
bool near_identity(const glm::mat4& m, float eps = 1e-4f) {
    glm::mat4 I(1.0f);
    for (int c = 0; c < 4; ++c) for (int r = 0; r < 4; ++r)
        if (std::abs(m[c][r] - I[c][r]) > eps) return false;
    return true;
}
}

TEST(BonePalette, BindPoseYieldsIdentityPerBone) {
    auto sk = two_bone_skeleton();
    auto palette = renderer::build_bone_palette(sk, nullptr);
    ASSERT_EQ(palette.size(), 2u);
    EXPECT_TRUE(near_identity(palette[0]));
    EXPECT_TRUE(near_identity(palette[1]));
}

TEST(BonePalette, TranslatedRootPosePropagatesToChild) {
    auto sk = two_bone_skeleton();
    // Pose: shift root +X by 10, child unchanged in local frame.
    std::vector<glm::mat4> pose = {
        glm::translate(glm::mat4(1.0f), glm::vec3(10, 0, 0)) * sk.bones[0].local_transform,
        sk.bones[1].local_transform,
    };
    auto palette = renderer::build_bone_palette(sk, &pose);
    // A bind-pose child vertex at composed world position should translate +X10.
    glm::vec4 world_bind_child = sk.bones[0].local_transform
                               * sk.bones[1].local_transform * glm::vec4(0, 0, 0, 1);
    glm::vec4 moved = palette[1] * world_bind_child;
    EXPECT_NEAR(moved.x, world_bind_child.x + 10.0f, 1e-3f);
    EXPECT_NEAR(moved.y, world_bind_child.y, 1e-3f);
}

TEST(BonePalette, ClampsToMaxBones) {
    assets::Skeleton sk;
    for (int i = 0; i < 200; ++i) {
        assets::Bone b; b.parent_index = (i == 0 ? -1 : i - 1);
        b.local_transform = glm::mat4(1.0f);
        b.inverse_bind_pose = glm::mat4(1.0f);
        sk.bones.push_back(b);
    }
    sk.root_bone_index = 0;
    auto palette = renderer::build_bone_palette(sk, nullptr);
    EXPECT_EQ(palette.size(), renderer::kMaxBones);  // clamped to 128
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j renderer_tests 2>&1 | tail -5`
Expected: FAIL — `renderer/bone_palette.h` not found.

- [ ] **Step 3: Implement**

Create `native/src/renderer/include/renderer/bone_palette.h` (match where other renderer headers live; if renderer headers are under `native/src/renderer/include/renderer/`, put it there):

```cpp
// native/src/renderer/include/renderer/bone_palette.h
#pragma once
#include <vector>
#include <glm/glm.hpp>
#include <assets/skeleton.h>

namespace renderer {

/// Maximum bones in the skinning palette (matches u_bones[128] in skinned.vert).
inline constexpr std::size_t kMaxBones = 128;

/// Build the skinning palette: palette[b] = world_pose(b) * inverse_bind_pose(b).
/// `local_pose`, if non-null, supplies a local transform per bone (same order as
/// skeleton.bones); when null, each bone's bind local_transform is used (so the
/// palette is identity per bone). Result clamped to kMaxBones with a warning.
std::vector<glm::mat4> build_bone_palette(
    const assets::Skeleton& skeleton,
    const std::vector<glm::mat4>* local_pose);

}  // namespace renderer
```

Create `native/src/renderer/bone_palette.cc`:

```cpp
// native/src/renderer/bone_palette.cc
#include "renderer/bone_palette.h"
#include <cstdio>

namespace renderer {

std::vector<glm::mat4> build_bone_palette(
    const assets::Skeleton& sk,
    const std::vector<glm::mat4>* local_pose) {

    const std::size_t n = std::min(sk.bones.size(), kMaxBones);
    if (sk.bones.size() > kMaxBones) {
        std::fprintf(stderr,
            "[bone_palette] skeleton has %zu bones; clamping to %zu\n",
            sk.bones.size(), kMaxBones);
    }

    auto local_of = [&](std::size_t i) -> glm::mat4 {
        if (local_pose && i < local_pose->size()) return (*local_pose)[i];
        return sk.bones[i].local_transform;
    };

    // world_pose(i) = product of local transforms down the parent chain.
    std::vector<glm::mat4> world(n);
    auto world_of = [&](int i) {
        glm::mat4 w(1.0f);
        std::vector<int> chain;
        for (int b = i; b != -1 && b < static_cast<int>(n); b = sk.bones[b].parent_index)
            chain.push_back(b);
        for (auto it = chain.rbegin(); it != chain.rend(); ++it)
            w = w * local_of(static_cast<std::size_t>(*it));
        return w;
    };

    std::vector<glm::mat4> palette(n);
    for (std::size_t i = 0; i < n; ++i)
        palette[i] = world_of(static_cast<int>(i)) * sk.bones[i].inverse_bind_pose;
    return palette;
}

}  // namespace renderer
```

Add `bone_palette.cc` to the renderer library sources in `native/src/renderer/CMakeLists.txt`, and `bone_palette_test.cc` to `native/tests/renderer/CMakeLists.txt`'s test sources.

- [ ] **Step 4: Run test to verify it passes**

Run: `cmake -B build -S . && cmake --build build -j renderer_tests && ctest --test-dir build -R BonePalette --output-on-failure`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/bone_palette.h native/src/renderer/bone_palette.cc \
        native/src/renderer/CMakeLists.txt native/tests/renderer/bone_palette_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): build_bone_palette (world-pose x inverse-bind, 128-bone guard)"
```

---

### Task 4: `set_mat4_array`, `skinned.vert`, and `Pipeline::skinned_shader()`

**Files:**
- Modify: `native/src/renderer/include/renderer/shader.h`, `native/src/renderer/shader.cc`
- Create: `native/src/renderer/shaders/skinned.vert`
- Modify: `native/src/renderer/CMakeLists.txt`, `native/src/renderer/include/renderer/pipeline.h`, `native/src/renderer/pipeline.cc`
- Test: `native/tests/renderer/skinned_program_test.cc` (create; needs GL context)

- [ ] **Step 1: Add `set_mat4_array` (mirror `set_vec4_array`)**

In `native/src/renderer/include/renderer/shader.h`, after `set_vec4_array`:

```cpp
    void set_mat4_array(const std::string& name,
                        const glm::mat4* data, int count) const;
```

In `native/src/renderer/shader.cc`, after the `set_vec4_array` impl:

```cpp
void Shader::set_mat4_array(const std::string& name,
                            const glm::mat4* data, int count) const {
    GLint loc = glGetUniformLocation(program_, name.c_str());
    if (loc >= 0 && count > 0)
        glUniformMatrix4fv(loc, count, GL_FALSE, glm::value_ptr(*data));
}
```

(Confirm the member is `program_` by checking the existing setters; match it.)

- [ ] **Step 2: Create `skinned.vert`**

Create `native/src/renderer/shaders/skinned.vert`:

```glsl
#version 330 core
layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;
layout(location = 2) in vec2 a_uv;
layout(location = 4) in ivec4 a_bone_indices;
layout(location = 5) in vec4  a_bone_weights;

uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_proj;
uniform mat4 u_bones[128];

out vec3 v_normal_ws;
out vec2 v_uv;
out vec3 v_position_ws;

void main() {
    mat4 skin = a_bone_weights.x * u_bones[a_bone_indices.x]
              + a_bone_weights.y * u_bones[a_bone_indices.y]
              + a_bone_weights.z * u_bones[a_bone_indices.z]
              + a_bone_weights.w * u_bones[a_bone_indices.w];
    vec4 ws = u_model * skin * vec4(a_position, 1.0);
    v_normal_ws   = mat3(u_model) * mat3(skin) * a_normal;
    v_uv          = a_uv;
    v_position_ws = ws.xyz;
    gl_Position   = u_proj * u_view * ws;
}
```

> The fragment stage is the existing `opaque.frag`. Its declared inputs (`v_normal_ws`, `v_uv`, `v_position_ws`) match the outputs above — confirm by reading `opaque.frag` and keep names identical.

- [ ] **Step 3: Embed the shader + add to the pipeline**

In `native/src/renderer/CMakeLists.txt`, beside the opaque embeds:

```cmake
embed_shader(SHADER_SKINNED_VS shaders/skinned.vert skinned_vs)
```

Ensure `${SHADER_SKINNED_VS}` is added to the generated-headers list the renderer target depends on (mirror exactly how `SHADER_OPAQUE_VS` is threaded into the target — search the file for `SHADER_OPAQUE_VS` and replicate every place it appears).

In `native/src/renderer/pipeline.cc`, add the include beside the others:

```cpp
#include "embedded_skinned_vs.h"
```

and construct it next to `opaque_` (reusing the opaque fragment source):

```cpp
    skinned_ = std::make_unique<Shader>(shader_src::skinned_vs, shader_src::opaque_fs);
```

In `native/src/renderer/include/renderer/pipeline.h`, add the accessor and member:

```cpp
    Shader& skinned_shader() noexcept { return *skinned_; }
```
```cpp
    std::unique_ptr<Shader> skinned_;
```

- [ ] **Step 4: Write a program-link test**

Create `native/tests/renderer/skinned_program_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <renderer/window.h>
#include <renderer/pipeline.h>

// Constructing the Pipeline compiles+links every shader, including skinned.vert.
// A link failure throws in the Shader ctor, failing this test.
TEST(SkinnedProgram, LinksSuccessfully) {
    auto w = renderer::Window::create_hidden(64, 64);  // confirm hidden-window API
    renderer::Pipeline p;                               // throws on shader error
    SUCCEED();
}
```

> Use whatever hidden/offscreen window factory `frame_test.cc` uses (it constructs a `renderer::Window`); copy that construction verbatim. Add the test file to `native/tests/renderer/CMakeLists.txt`.

- [ ] **Step 5: Reconfigure, build, run**

Run: `cmake -B build -S . && cmake --build build -j renderer_tests && ctest --test-dir build -R SkinnedProgram --output-on-failure`
Expected: PASS (the `cmake -B build -S .` reconfigure is required so the new `skinned.vert` is embedded).

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/shader.h native/src/renderer/shader.cc \
        native/src/renderer/shaders/skinned.vert native/src/renderer/CMakeLists.txt \
        native/src/renderer/include/renderer/pipeline.h native/src/renderer/pipeline.cc \
        native/tests/renderer/skinned_program_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): skinned.vert program + set_mat4_array palette uniform"
```

---

### Task 5: `draw_model` skinned branch + offscreen GL verification

**Files:**
- Modify: `native/src/renderer/frame.cc`, `native/src/renderer/include/renderer/frame.h`
- Test: `native/tests/renderer/skinned_render_test.cc` (create)

`draw_model` gains a palette parameter and a skinned branch. The opaque pass computes the palette for skinned models and passes it; for static models it passes an empty palette and the existing static shader.

- [ ] **Step 1: Extend `draw_model`'s signature (declare in `frame.h`)**

Make `draw_model` callable from tests by declaring it in `native/src/renderer/include/renderer/frame.h` (if it is currently file-local in `frame.cc`, move the declaration to the header). New signature adds two trailing params:

```cpp
void draw_model(const assets::Model& model,
                const glm::mat4& world,
                Shader& shader,
                Shader& skinned_shader,
                GLuint white_fallback,
                GLuint black_fallback,
                bool rim_active,
                const scenegraph::DamageDecalRing& decals,
                const std::array<scenegraph::Instance::GlowRegion,
                                 scenegraph::Instance::kMaxGlowRegions>& glow_regions,
                float decal_time,
                float emissive_scale,
                const std::vector<glm::mat4>& bone_palette);
```

- [ ] **Step 2: Implement the branch**

At the top of `draw_model` in `frame.cc`, choose the program and upload the palette:

```cpp
    const bool skinned = !model.skeleton.bones.empty() && !bone_palette.empty();
    Shader& prog = skinned ? skinned_shader : shader;
    prog.use();
    if (skinned) {
        prog.set_mat4_array("u_bones", bone_palette.data(),
                            static_cast<int>(bone_palette.size()));
    }
```

Then ensure every subsequent uniform/draw call in the function uses `prog` instead of the captured `shader` reference. Crucially, the per-frame uniforms currently set on `pipeline.opaque_shader()` in the pass (view/proj/lights/camera/ambient — `frame.cc:321-340`) must ALSO be set on the skinned program when it is used. The simplest correct approach: in the opaque pass, after binding and configuring the static shader, **also** configure the skinned shader with the same per-frame uniforms once per frame (view, proj, camera pos, ambient, dir-light arrays, specular toggle). Add a small local lambda `configure_common(Shader&)` in the pass that sets these, and call it for both `pipeline.opaque_shader()` and `pipeline.skinned_shader()`.

- [ ] **Step 3: Wire the opaque-pass call sites**

At the two `draw_model(...)` call sites (`frame.cc:308` and `frame.cc:347`), pass the skinned shader and palette. Before each call:

```cpp
    std::vector<glm::mat4> palette;
    if (m && !m->skeleton.bones.empty())
        palette = build_bone_palette(m->skeleton, /*local_pose=*/nullptr);
    if (m) draw_model(*m, inst.world, shader, pipeline.skinned_shader(),
                      white, black, rim_active, /*…existing args…*/,
                      decal_time, emissive_scale, palette);
```

Add `#include "renderer/bone_palette.h"` to `frame.cc`. For static models `palette` is empty → the static branch runs, byte-identical to today.

- [ ] **Step 4: Write the offscreen render tests**

Create `native/tests/renderer/skinned_render_test.cc`. Model the fixture on `frame_test.cc` (hidden `Window`, `Pipeline`, `AssetCache`, project-root paths). Two tests:

```cpp
// Test A — PLUMBING: a skinned model at bind pose renders identically whether
// drawn through the skinned program (identity palette) or the static program.
TEST_F(SkinnedRenderTest, BindPoseMatchesStaticDraw) {
    // 1. Load BodyMaleL.nif (SKIP if game/ absent).
    // 2. Render once forcing the STATIC program (pass empty palette so draw_model
    //    takes the static branch) into an offscreen target; read pixels -> bufA.
    // 3. Render once through the SKINNED program with palette =
    //    build_bone_palette(skeleton, nullptr) (all identity); read pixels -> bufB.
    // 4. EXPECT bufA == bufB (allow a tiny per-channel tolerance, e.g. <=1).
}

// Test B — PALETTE MATH: a palette translating every bone +X shifts the
// rendered silhouette's non-background centroid in +screen-X.
TEST_F(SkinnedRenderTest, TranslatedPaletteShiftsSilhouette) {
    // 1. Load BodyMaleL.nif (SKIP if game/ absent).
    // 2. Render skinned with identity palette; compute centroid_x of non-background
    //    pixels via glReadPixels.
    // 3. Build palette where every entry = translate(+X) * identity (a large GU
    //    shift along camera-right); render again; compute centroid_x2.
    // 4. EXPECT centroid_x2 > centroid_x (silhouette moved right).
}
```

Implement the pixel read-back the same way other renderer tests do (`glReadPixels` over the offscreen target; see `host_bindings.cc:1462` and existing renderer tests for the exact target binding). Background pixels are the clear color; "non-background" = any pixel differing from the clear color beyond a small threshold. Add the file to `native/tests/renderer/CMakeLists.txt`.

- [ ] **Step 5: Reconfigure, build, run**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R "SkinnedRender|FrameTest|frame" --output-on-failure`
Expected: skinned tests PASS (or SKIP without `game/`); **existing frame/render tests still PASS** (proves the static path is unchanged).

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/frame.cc native/src/renderer/include/renderer/frame.h \
        native/tests/renderer/skinned_render_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): skinned draw branch in draw_model with bone palette"
```

---

### Task 6: `--developer` preview hook

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/renderer.py`, `engine/dev_keybindings.py`
- Test: manual smoke test in `./build/dauntless --developer` + a Python unit test for the wrapper guard

This exposes a binding to spawn a single skinned body NIF in front of the exterior camera and a dev keybinding to toggle it. Production builds never register the keybinding.

- [ ] **Step 1: Add host bindings**

In `native/src/host/host_bindings.cc`, beside the existing `create_instance` / `load_model` bindings (~line 468-519), add:

```cpp
    m.def("spawn_test_character",
          [](const std::string& nif_path, std::array<float,3> world_pos) {
              auto h = load_model_impl(nif_path, /*texture dir defaulting as load_model does*/);
              auto id = g_world.create_instance(h);
              // Place at world_pos with identity rotation; reuse the same world-
              // matrix setter create_instance/instance transforms use elsewhere.
              // (Mirror how host_bindings sets an instance's world transform.)
              return id;
          },
          "Developer-only: load a skinned NIF and spawn one instance at world_pos.");
```

> Match `load_model_impl`'s real signature (it takes the nif path and resolves textures — see `host_bindings.cc:158`). For setting the instance transform, mirror the existing instance-transform binding (search `set_instance_transform` / how `inst.world` is assigned). `despawn` can reuse the existing `destroy_instance` binding — no new C++ needed.

- [ ] **Step 2: Add `renderer.py` wrappers**

In `engine/renderer.py`, add thin wrappers that no-op safely when the binding is absent (mirror the documented `r.<binding>` wrapper pattern — see the damage-decal note: hasattr-guarded host calls silently no-op without a wrapper, so a real wrapper is required):

```python
def spawn_test_character(nif_path, world_pos):
    """Dev-only: spawn a skinned NIF instance; returns InstanceId or None."""
    host = _host()
    if host is None or not hasattr(host, "spawn_test_character"):
        return None
    return host.spawn_test_character(nif_path, tuple(world_pos))
```

(Use the module's existing `_host()`/binding-access convention — match the surrounding wrappers exactly.)

- [ ] **Step 3: Register the dev keybinding**

In `engine/dev_keybindings.py`, register a toggle under `--developer` (mirror existing `register_dev_keybinding` calls). Pick an unused key (verify against existing dev bindings):

```python
import engine.renderer as renderer
from engine import dev_mode

_test_char_id = None

def _toggle_test_character():
    global _test_char_id
    if _test_char_id is None:
        # ~6 GU in front of the exterior camera; use a fixed world point for SP1.
        _test_char_id = renderer.spawn_test_character(
            "data/Models/Characters/BodyMaleL.nif", (0.0, 0.0, 6.0))
    else:
        renderer.destroy_instance(_test_char_id)  # existing wrapper
        _test_char_id = None

dev_mode.register_dev_keybinding(
    key=ord('K'), handler=_toggle_test_character,
    description="Spawn/despawn skinned test character (SP1)")
```

> Confirm the exact NIF path, the `destroy_instance` wrapper name in `renderer.py`, and that key `K` is free. Place the registration wherever other dev keybindings are registered so it only runs under `--developer`.

- [ ] **Step 4: Python guard test**

Add a focused test (run it alone — never the full suite) asserting the wrapper no-ops without a host. Example `tests/unit/test_renderer_test_character.py`:

```python
def test_spawn_test_character_without_host_returns_none(monkeypatch):
    import engine.renderer as renderer
    monkeypatch.setattr(renderer, "_host", lambda: None, raising=False)
    assert renderer.spawn_test_character("x.nif", (0, 0, 6)) is None
```

Run ONLY this file: `uv run pytest tests/unit/test_renderer_test_character.py -q`
Expected: PASS. (Do not run the whole suite — it OOMs.)

- [ ] **Step 5: Build + manual smoke test**

Run: `cmake -B build -S . && cmake --build build -j && ./build/dauntless --developer`
Then press `K`. Expected: a skinned humanoid body appears ~6 GU ahead in exterior view, correctly shaded (bind pose). Press `K` again to despawn. (The user performs this verification; do not synthesize input or screen-capture.)

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py engine/dev_keybindings.py \
        tests/unit/test_renderer_test_character.py
git commit -m "feat(dev): --developer hook to spawn a skinned test character (SP1)"
```

---

## Self-Review

**Spec coverage:**
- Inverse-bind computation → Task 1. ✓
- Per-vertex weight fill + thread `nif_block_to_bone_index` → Task 2. ✓
- `build_bone_palette` + 128 guard → Task 3. ✓
- `skinned.vert` + reuse `opaque.frag` + program in pipeline + `set_mat4_array` → Task 4. ✓
- `draw_model` skinned branch + byte-identical static path → Task 5. ✓
- CPU gtests (weights, inverse-bind, palette/guard) → Tasks 1–3. ✓
- Offscreen GL gtests (bind-pose==static; palette-math shift) → Task 5. ✓
- `--developer` preview hook → Task 6. ✓
- Risks (old-skin bind offsets, weight precision, non-skinned-mesh-in-skinned-model) are SP2/deferred per spec; no SP1 task needed. ✓

**Placeholder scan:** Steps that say "confirm exact path / API during impl" are integration-glue confirmations against real headers, each paired with the precedent file:line to copy from — not unspecified work. All code-bearing steps include complete code.

**Type consistency:** `fill_skin_weights(MeshCpu&, const NiTriShapeSkinController&, const std::vector<int>&)`, `build_bone_palette(const Skeleton&, const std::vector<glm::mat4>*)`, `kMaxBones`, `set_mat4_array(name, const glm::mat4*, int)`, and the extended `draw_model(... Shader& skinned_shader ... const std::vector<glm::mat4>& bone_palette)` are used identically across tasks. `compute_inverse_bind_poses(Skeleton&)` matches between Task 1 def and use.
