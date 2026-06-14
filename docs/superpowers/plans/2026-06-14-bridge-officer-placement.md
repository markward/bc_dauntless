# Bridge Officer Placement, Pose & Appearance (SP3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render each bridge officer as a correctly posed, placed, per-character-appearance skinned figure standing/seated at their station on both playable bridges, static (one rest-frame pose).

**Architecture:** A general interpolating pose sampler evaluates each station's placement clip at its rest frame → a per-bone local pose → a per-instance bone palette (reusing SP1's `build_bone_palette` + the SP1 bridge skinned sub-pass). Skin-controller-less shapes (and the grafted head) are bound to their parent skeleton bone so they follow the pose. Per-character appearance (body+head NIFs+textures) is captured from the SDK character configs via the App shim and assembled natively.

**Tech Stack:** C++17, OpenGL 3.3 / GLSL 330, GoogleTest, glm; Python (App shim + host wiring). Build from `build/` only.

**Spec:** `docs/superpowers/specs/2026-06-14-bridge-officer-placement-design.md`

---

## Conventions the implementer must know

- **One build tree** `build/`. Configure `cmake -B build -S .`; build a target `cmake --build build -j --target <t>`. NEVER cmake inside `native/`.
- **`host_bindings.cc` compiles into BOTH `dauntless` and `_dauntless_host`** — after editing it, `cmake --build build -j` (or `--target dauntless`) so the live binary updates, not just the module.
- Native tests: `ctest --test-dir build -R <regex> --output-on-failure`. Do NOT run full Python `pytest` (OOMs) — run only the single file you touch: `uv run pytest tests/unit/<file>.py -q`.
- Column-vector transforms: child world = `parent_world * child_local`.
- Shaders embed at configure time (not relevant to SP3 — no new shaders).
- Commit only when green. End commits with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- CPU renderer/asset tests live under `native/tests/renderer/` and `native/tests/assets/cpu/`. Targets `renderer_tests`, `assets_tests`.

### Key existing shapes (verified)
- `assets::AnimationClip { float duration_seconds; vector<NodeTrack> tracks; }`; `NodeTrack { string target_node_name; vector<TranslationKey{float time; glm::vec3 value;}> translation; vector<RotationKey{float time; glm::quat value;}> rotation; vector<ScaleKey{float time; float value;}> scale; ... }` — `native/src/assets/include/assets/animation.h`.
- `assets::Skeleton { vector<Bone> bones; int root_bone_index; }`; `Bone { string name; int parent_index; glm::mat4 local_transform; glm::mat4 inverse_bind_pose; }` — `native/src/assets/include/assets/skeleton.h`.
- `renderer::build_bone_palette(const assets::Skeleton&, const std::vector<glm::mat4>* local_pose)` → `vector<glm::mat4>` — `native/src/renderer/include/renderer/bone_palette.h`. Passing a non-null `local_pose` (per-bone local transforms) overrides the bind `local_transform`.
- `assets::Model { vector<Node> nodes; int root_node; vector<Mesh> meshes; vector<Material> materials; Skeleton skeleton; vector<AnimationClip> animations; ... }`. `Node { string name; int parent_index; glm::mat4 local_transform; vector<int> meshes; }`.
- `scenegraph::Instance` — `native/src/scenegraph/include/scenegraph/instance.h` (has `model_handle, world, visible, pass, ...`).
- Bridge skinned sub-pass palette source: `native/src/renderer/bridge_pass.cc:218` (`build_bone_palette(m->skeleton, nullptr)`).
- App shim character: `engine/appc/characters.py` — `CharacterClass` (ctor `(body_nif, head_nif)`), `ReplaceBodyAndHead(body_nif, head_nif)` (**SDK actually passes textures here**, and the current shim overwrites `_body_nif`/`_head_nif` — must be fixed in Task 5), `AddFacialImage`, `CharacterClass_Create`. `SetLocation` stores `self._data["Location"]`.
- Crew population: `LoadBridge.py:populate_bridge_crew(pBridgeSet, bridge_name)` runs each officer module's `CreateCharacter`.
- `SetPosition` location→NIF table: `sdk/Build/scripts/Bridge/Characters/CommonAnimations.py:149+`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `native/src/renderer/pose_sampler.{h,cc}` (create) | `sample_pose(clip, skeleton, t)` → per-bone local pose (interpolating) | 1 |
| `native/src/assets/src/model_build.cc` (modify) | rigid-shape → parent-bone rebind (replace bone-0 fallback) | 2 |
| `native/src/scenegraph/include/scenegraph/instance.h` (modify) | per-instance `bone_palette` field | 3 |
| `native/src/renderer/bridge_pass.cc` (modify) | use instance palette if present | 3 |
| `native/src/host/host_bindings.cc` (modify) | `set_instance_bone_palette`, `sample_placement_pose`, character-assembly + officer-enumeration bindings | 3,6,7 |
| `native/src/renderer/placement_map.{h,cc}` (create) | location string → `{nif_path, hidden}` (from SetPosition) | 4 |
| `engine/appc/characters.py` (modify) | capture body NIF, head NIF, body tex, head tex distinctly; expose appearance | 5 |
| `native/src/assets/src/model_compose.{h,cc}` (create) | graft head NIF meshes into a body Model bound to a named bone | 6 |
| `engine/bridge_officers.py` (create) | placement wiring: enumerate officers → assemble → place+pose | 7 |
| `engine/host_loop.py` (modify) | call bridge-officer placement in the bridge lifecycle | 7 |

---

### Task 1: `sample_pose` — interpolating static pose sampler

**Files:**
- Create: `native/src/renderer/include/renderer/pose_sampler.h`, `native/src/renderer/pose_sampler.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `pose_sampler.cc`)
- Test: `native/tests/renderer/pose_sampler_test.cc` (create; register in `native/tests/renderer/CMakeLists.txt`)

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/pose_sampler_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <renderer/pose_sampler.h>
#include <assets/animation.h>
#include <assets/skeleton.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/quaternion.hpp>

namespace {
assets::Skeleton two_bone() {
    assets::Skeleton sk;
    assets::Bone root; root.name = "root"; root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    assets::Bone child; child.name = "child"; child.parent_index = 0;
    child.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 1, 0));
    sk.bones = {root, child};
    sk.root_bone_index = 0;
    return sk;
}
}

TEST(SamplePose, TracklessBoneKeepsBindLocal) {
    auto sk = two_bone();
    assets::AnimationClip clip;            // no tracks
    clip.duration_seconds = 1.0f;
    auto pose = renderer::sample_pose(clip, sk, 1.0f);
    ASSERT_EQ(pose.size(), 2u);
    EXPECT_EQ(pose[0], sk.bones[0].local_transform);
    EXPECT_EQ(pose[1], sk.bones[1].local_transform);
}

TEST(SamplePose, TranslationLerpsAtMidTime) {
    auto sk = two_bone();
    assets::AnimationClip clip; clip.duration_seconds = 2.0f;
    assets::AnimationClip::NodeTrack t; t.target_node_name = "child";
    t.translation = { {0.0f, glm::vec3(0, 0, 0)}, {2.0f, glm::vec3(0, 0, 10)} };
    clip.tracks = { t };
    auto pose = renderer::sample_pose(clip, sk, 1.0f);   // midpoint
    // child local should be a pure translation of (0,0,5).
    EXPECT_NEAR(pose[1][3].z, 5.0f, 1e-4f);
}

TEST(SamplePose, RestFrameTakesFinalKey) {
    auto sk = two_bone();
    assets::AnimationClip clip; clip.duration_seconds = 2.0f;
    assets::AnimationClip::NodeTrack t; t.target_node_name = "child";
    t.translation = { {0.0f, glm::vec3(0,0,0)}, {2.0f, glm::vec3(0,0,10)} };
    clip.tracks = { t };
    auto pose = renderer::sample_pose(clip, sk, clip.duration_seconds);
    EXPECT_NEAR(pose[1][3].z, 10.0f, 1e-4f);
}

TEST(SamplePose, RotationSlerps) {
    auto sk = two_bone();
    assets::AnimationClip clip; clip.duration_seconds = 2.0f;
    assets::AnimationClip::NodeTrack t; t.target_node_name = "child";
    glm::quat q0(1,0,0,0);                                   // identity
    glm::quat q1 = glm::angleAxis(glm::radians(90.0f), glm::vec3(0,0,1));
    t.rotation = { {0.0f, q0}, {2.0f, q1} };
    clip.tracks = { t };
    auto pose = renderer::sample_pose(clip, sk, 1.0f);       // ~45 deg
    glm::vec3 x = glm::vec3(pose[1] * glm::vec4(1, 0, 0, 0));
    EXPECT_NEAR(x.x, std::cos(glm::radians(45.0f)), 1e-3f);
    EXPECT_NEAR(x.y, std::sin(glm::radians(45.0f)), 1e-3f);
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests 2>&1 | tail -5`
Expected: FAIL — `renderer/pose_sampler.h` not found.

- [ ] **Step 3: Implement**

Create `native/src/renderer/include/renderer/pose_sampler.h`:

```cpp
// native/src/renderer/include/renderer/pose_sampler.h
#pragma once
#include <vector>
#include <glm/glm.hpp>
#include <assets/animation.h>
#include <assets/skeleton.h>

namespace renderer {

/// Sample an animation clip at time `t` into per-bone LOCAL transforms
/// (indexed by skeleton bone). Tracks are matched to bones by
/// NodeTrack::target_node_name == Bone::name. Translation/scale LERP,
/// rotation SLERP between surrounding keys; `t` is clamped to [0, duration].
/// Bones with no matching track keep their bind local_transform. Feed the
/// result to build_bone_palette(skeleton, &pose).
std::vector<glm::mat4> sample_pose(const assets::AnimationClip& clip,
                                   const assets::Skeleton& skeleton,
                                   float t);

}  // namespace renderer
```

Create `native/src/renderer/pose_sampler.cc`:

```cpp
// native/src/renderer/pose_sampler.cc
#include "renderer/pose_sampler.h"
#include <algorithm>
#include <unordered_map>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/quaternion.hpp>

namespace renderer {
namespace {

// Find the pair of keys surrounding `t` and the [0,1] fraction between them.
template <typename Key>
void bracket(const std::vector<Key>& keys, float t, int& i0, int& i1, float& f) {
    if (keys.empty()) { i0 = i1 = -1; f = 0.0f; return; }
    if (t <= keys.front().time) { i0 = i1 = 0; f = 0.0f; return; }
    if (t >= keys.back().time)  { i0 = i1 = static_cast<int>(keys.size()) - 1; f = 0.0f; return; }
    for (std::size_t k = 1; k < keys.size(); ++k) {
        if (t < keys[k].time) {
            i0 = static_cast<int>(k) - 1; i1 = static_cast<int>(k);
            const float span = keys[i1].time - keys[i0].time;
            f = span > 1e-8f ? (t - keys[i0].time) / span : 0.0f;
            return;
        }
    }
    i0 = i1 = static_cast<int>(keys.size()) - 1; f = 0.0f;
}

glm::vec3 sample_translation(const assets::AnimationClip::NodeTrack& tr, float t,
                             const glm::vec3& fallback) {
    if (tr.translation.empty()) return fallback;
    int a, b; float f; bracket(tr.translation, t, a, b, f);
    return glm::mix(tr.translation[a].value, tr.translation[b].value, f);
}
glm::quat sample_rotation(const assets::AnimationClip::NodeTrack& tr, float t,
                          const glm::quat& fallback) {
    if (tr.rotation.empty()) return fallback;
    int a, b; float f; bracket(tr.rotation, t, a, b, f);
    return glm::normalize(glm::slerp(tr.rotation[a].value, tr.rotation[b].value, f));
}
float sample_scale(const assets::AnimationClip::NodeTrack& tr, float t, float fallback) {
    if (tr.scale.empty()) return fallback;
    int a, b; float f; bracket(tr.scale, t, a, b, f);
    return glm::mix(tr.scale[a].value, tr.scale[b].value, f);
}

}  // namespace

std::vector<glm::mat4> sample_pose(const assets::AnimationClip& clip,
                                   const assets::Skeleton& skeleton,
                                   float t) {
    t = std::clamp(t, 0.0f, clip.duration_seconds);

    std::unordered_map<std::string, const assets::AnimationClip::NodeTrack*> by_name;
    for (const auto& tr : clip.tracks) by_name[tr.target_node_name] = &tr;

    std::vector<glm::mat4> out(skeleton.bones.size());
    for (std::size_t i = 0; i < skeleton.bones.size(); ++i) {
        const auto& bone = skeleton.bones[i];
        auto it = by_name.find(bone.name);
        if (it == by_name.end()) { out[i] = bone.local_transform; continue; }
        const auto& tr = *it->second;
        // Decompose the bind local for fallback components the track omits.
        const glm::vec3 bind_t = glm::vec3(bone.local_transform[3]);
        const glm::vec3 trans = sample_translation(tr, t, bind_t);
        const glm::quat rot   = sample_rotation(tr, t, glm::quat(1, 0, 0, 0));
        const float     scl   = sample_scale(tr, t, 1.0f);
        glm::mat4 m = glm::translate(glm::mat4(1.0f), trans)
                    * glm::mat4_cast(rot)
                    * glm::scale(glm::mat4(1.0f), glm::vec3(scl));
        out[i] = m;
    }
    return out;
}

}  // namespace renderer
```

Add `pose_sampler.cc` to the renderer library in `native/src/renderer/CMakeLists.txt` (mirror `bone_palette.cc`), and `pose_sampler_test.cc` to `native/tests/renderer/CMakeLists.txt`.

- [ ] **Step 4: Run to verify it passes**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests && ctest --test-dir build -R SamplePose --output-on-failure`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/pose_sampler.h native/src/renderer/pose_sampler.cc \
        native/src/renderer/CMakeLists.txt native/tests/renderer/pose_sampler_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): interpolating pose sampler (clip -> per-bone local pose)"
```

---

### Task 2: Rigid-shape → parent-bone rebind

**Files:**
- Modify: `native/src/assets/src/model_build.cc` (the SP1 bone-0 fallback, ~lines 506-527)
- Test: `native/tests/assets/cpu/skin_weights_test.cc` (add a case)

SP1 binds skin-controller-less shapes of a skinned model entirely to **bone 0**. Replace this: bind such a shape to **its parent node's skeleton bone**, so under a pose it follows the right bone. The shape's parent node is `node_index` (already computed in the loop); map that node to a skeleton bone by the node's **name** matching a `Skeleton::bones[].name`. Keep the bone-0 fallback only when no match.

- [ ] **Step 1: Add the failing test**

Append to `native/tests/assets/cpu/skin_weights_test.cc` an integration assertion on `BodyMaleL` (it has rigid shapes parented to Bip01 bones). After building the model with `keep_cpu_data=true` (mirror the existing `FillSkinWeightsAsset` test), assert that **not all** rigid-shape vertices are bound to bone 0 — i.e. at least one mesh has vertices whose `bone_indices.x` maps to a bone whose `name` is not the root, and that index is a valid non-zero bone:

```cpp
TEST(RigidRebindAsset, RigidShapesBindToParentBoneNotAlwaysZero) {
    // ... load BodyMaleL with keep_cpu_data=true (see FillSkinWeightsAsset) ...
    // GTEST_SKIP() if asset missing.
    // Across model.meshes with cpu_data(), collect the set of bone_indices.x
    // used by vertices whose weight is (255,0,0,0) [the rigid-bound shapes].
    // EXPECT the set contains at least one index > 0 (i.e. not everything is
    // pinned to bone 0), proving shapes bind to their actual parent bone.
}
```

(Use the real build entry + skeleton from the existing asset test; the precise body is integration code the implementer fills against `model.skeleton` / `model.nodes`.)

- [ ] **Step 2: Run to verify it fails**

Run: `cmake --build build -j --target assets_tests && ctest --test-dir build -R RigidRebindAsset --output-on-failure`
Expected: FAIL — with SP1's bone-0 binding every rigid vertex is index 0.

- [ ] **Step 3: Implement the rebind**

In `native/src/assets/src/model_build.cc`, the SP1 `else` branch (skinned model, shape with no skin controller) currently writes `bone_indices=(0,0,0,0)`. Replace the bone-0 choice with the shape's parent-node bone. Build a node-name→bone-index map once (near where `nif_block_to_bone` is captured):

```cpp
// Map each skeleton bone's name -> its index, to bind rigid shapes to the
// bone their NIF node corresponds to (the node and bone share a name).
std::unordered_map<std::string, int> bone_by_name;
for (std::size_t b = 0; b < model.skeleton.bones.size(); ++b)
    bone_by_name[model.skeleton.bones[b].name] = static_cast<int>(b);
```

Then in the `else` (no skin controller) branch, resolve the rigid bone:

```cpp
} else {
    // Skinned model, shape has no skin controller: it is a rigid part
    // parented to a bone node. Bind every vertex to that bone so it follows
    // the pose. node_index is this shape's parent NiNode; match its name to a
    // skeleton bone. Fall back to bone 0 if unmatched (bind-pose identical).
    int rigid_bone = 0;
    if (node_index >= 0 && node_index < static_cast<int>(model.nodes.size())) {
        auto it = bone_by_name.find(model.nodes[node_index].name);
        if (it != bone_by_name.end()) rigid_bone = it->second;
    }
    const auto idx = static_cast<std::uint8_t>(std::clamp(rigid_bone, 0, 255));
    for (auto& v : cpu.vertices) {
        v.bone_indices = glm::u8vec4(idx, 0, 0, 0);
        v.bone_weights = glm::u8vec4(255, 0, 0, 0);
    }
}
```

(Keep the SP2 caveat comment but update it: rigid shapes now bind to their parent bone.) Add `#include <unordered_map>` / `<string>` if not present.

- [ ] **Step 4: Verify pass + no SP1 regression**

Run: `cmake --build build -j && ctest --test-dir build -R "RigidRebindAsset|FillSkinWeights|SkinnedRender|SkinnedBridge" --output-on-failure`
Expected: new test PASS; **SP1's `SkinnedRenderTest.BindPoseMatchesStaticDraw` still PASS** (at bind pose, binding to parent bone is identical to bone 0 since every palette entry is identity).

- [ ] **Step 5: Commit**

```bash
git add native/src/assets/src/model_build.cc native/tests/assets/cpu/skin_weights_test.cc
git commit -m "feat(assets): bind rigid character shapes to their parent bone (not bone 0)"
```

---

### Task 3: Per-instance posed palette (Instance + bridge sub-pass + binding)

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h` (add field)
- Modify: `native/src/scenegraph/include/scenegraph/world.h` (setter) — check the existing setter pattern (`set_pass`, `set_world_transform`)
- Modify: `native/src/renderer/bridge_pass.cc:218` (use instance palette)
- Modify: `native/src/host/host_bindings.cc` (`set_instance_bone_palette` binding)
- Test: `native/tests/renderer/skinned_bridge_test.cc` (add: posed palette differs from bind)

- [ ] **Step 1: Add the field + setter**

In `scenegraph::Instance` (instance.h), add:

```cpp
    /// Per-instance skinning palette (world_pose * inverse_bind per bone).
    /// Empty = the renderer falls back to the model's bind pose. Set by the
    /// placement system; SP2 rewrites it per frame. Runtime state, not saved.
    std::vector<glm::mat4> bone_palette;
```

Add `#include <vector>` and `#include <glm/glm.hpp>` if not already present. In `scenegraph::World`, add a setter mirroring `set_world_transform`:

```cpp
    void set_bone_palette(InstanceId id, std::vector<glm::mat4> palette);
```

and define it (in world.h inline or world.cc, matching the existing setter location) to assign `slots_[...].instance.bone_palette = std::move(palette)` with the same validity guard `set_world_transform` uses.

- [ ] **Step 2: Use it in the bridge sub-pass**

In `native/src/renderer/bridge_pass.cc`, replace the line that builds a bind-pose palette per instance (`build_bone_palette(m->skeleton, nullptr)`, ~:218) with:

```cpp
            std::vector<glm::mat4> palette = inst.bone_palette.empty()
                ? build_bone_palette(m->skeleton, nullptr)
                : inst.bone_palette;
```

(Everything else in the sub-pass is unchanged.)

- [ ] **Step 3: Host binding**

In `host_bindings.cc`, add a binding to set an instance's palette from Python (a flat list of 16-float row/col-major matrices, or accept a list of lists). Mirror existing instance bindings:

```cpp
    m.def("set_instance_bone_palette",
          [](scenegraph::InstanceId id, const std::vector<std::array<float,16>>& mats) {
              std::vector<glm::mat4> palette;
              palette.reserve(mats.size());
              for (const auto& a : mats) palette.push_back(glm::make_mat4(a.data()));
              g_world.set_bone_palette(id, std::move(palette));
          },
          py::arg("id"), py::arg("matrices"),
          "Set an instance's skinning palette (list of column-major mat4 as 16 floats).");
```

Confirm `glm::make_mat4` include (`<glm/gtc/type_ptr.hpp>`). Decide column-major and document it (glm is column-major; the Python side must send columns).

- [ ] **Step 4: GL test — posed differs from bind pose**

In `native/tests/renderer/skinned_bridge_test.cc`, add a test: load BodyMaleL, create a `Pass::Bridge` instance, render once with bind palette (foreground centroid/coverage A), then `set_bone_palette` to a non-identity palette (e.g. `build_bone_palette` with a `local_pose` that rotates a bone), render again (B), and assert the silhouettes differ (coverage or centroid changes). Mirrors SP1's `TranslatedPaletteShiftsSilhouette`.

- [ ] **Step 5: Build, run, commit**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R "SkinnedBridge|Bridge" --output-on-failure`
Expected: new test PASS; existing bridge tests PASS.

```bash
git add native/src/scenegraph/include/scenegraph/instance.h native/src/scenegraph/include/scenegraph/world.h \
        native/src/scenegraph/src/world.cc native/src/renderer/bridge_pass.cc \
        native/src/host/host_bindings.cc native/tests/renderer/skinned_bridge_test.cc
git commit -m "feat(renderer): per-instance bone palette for posed bridge characters"
```

(Adjust the `world.cc` path to wherever `set_world_transform` is defined.)

---

### Task 4: Location → placement-NIF map

**Files:**
- Create: `native/src/renderer/include/renderer/placement_map.h`, `native/src/renderer/placement_map.cc`
- Modify: `native/src/renderer/CMakeLists.txt`
- Test: `native/tests/renderer/placement_map_test.cc` (create; register)

- [ ] **Step 1: Write the failing test**

```cpp
#include <gtest/gtest.h>
#include <renderer/placement_map.h>

TEST(PlacementMap, ResolvesKnownStations) {
    auto db_tac = renderer::placement_for_location("DBTactical");
    ASSERT_TRUE(db_tac.has_value());
    EXPECT_EQ(db_tac->nif_path, "data/animations/db_stand_t_l.nif");
    EXPECT_FALSE(db_tac->hidden);

    auto eb_helm = renderer::placement_for_location("EBHelm");
    ASSERT_TRUE(eb_helm.has_value());
    EXPECT_EQ(eb_helm->nif_path, "data/animations/EB_stand_h_m.nif");
}

TEST(PlacementMap, StagingLocationsAreHidden) {
    auto staging = renderer::placement_for_location("DBL1S");
    ASSERT_TRUE(staging.has_value());
    EXPECT_TRUE(staging->hidden);
}

TEST(PlacementMap, UnknownReturnsNullopt) {
    EXPECT_FALSE(renderer::placement_for_location("Nowhere").has_value());
}
```

- [ ] **Step 2: Run to verify it fails** — `renderer/placement_map.h` not found.

- [ ] **Step 3: Implement** (transcribe the full `SetPosition` table)

Create `native/src/renderer/include/renderer/placement_map.h`:

```cpp
#pragma once
#include <optional>
#include <string>
#include <string_view>

namespace renderer {
struct Placement { std::string nif_path; bool hidden; };
/// Resolve a CharacterClass GetLocation() string to its placement-animation
/// NIF and whether the location is a hidden staging spot. nullopt if unknown.
std::optional<Placement> placement_for_location(std::string_view location);
}  // namespace renderer
```

Create `native/src/renderer/placement_map.cc` with the **full** table from `CommonAnimations.SetPosition` (both bridges; mark the `SetHidden(1)` ones hidden):

```cpp
#include "renderer/placement_map.h"
#include <unordered_map>

namespace renderer {
std::optional<Placement> placement_for_location(std::string_view loc) {
    static const std::unordered_map<std::string, Placement> kMap = {
        // DBridge
        {"DBHelm",      {"data/animations/db_stand_h_m.nif", false}},
        {"DBTactical",  {"data/animations/db_stand_t_l.nif", false}},
        {"DBCommander", {"data/animations/db_stand_c_m.nif", false}},
        {"DBCommander1",{"data/animations/DB_C1toC_M.nif",   false}},
        {"DBScience",   {"data/animations/db_StoL1_S.nif",   false}},
        {"DBEngineer",  {"data/animations/db_EtoL1_s.nif",   false}},
        {"DBGuest",     {"data/animations/Seated_P.nif",     false}},
        {"DBL1S",       {"data/animations/DB_L1toE_S.nif",   true}},
        {"DBL1M",       {"data/animations/DB_L1toG1_M.nif",  true}},
        {"DBL1L",       {"data/animations/DB_L1toT_L.nif",   true}},
        // EBridge
        {"EBHelm",      {"data/animations/EB_stand_h_m.nif", false}},
        {"EBTactical",  {"data/animations/EB_stand_t_l.nif", false}},
        {"EBCommander", {"data/animations/EB_stand_c_m.nif", false}},
        {"EBCommander1",{"data/animations/EB_C1toC_M.nif",   false}},
        {"EBScience",   {"data/animations/EB_stand_s_s.nif", false}},
        {"EBEngineer",  {"data/animations/EB_stand_e_s.nif", false}},
    };
    auto it = kMap.find(std::string(loc));
    if (it == kMap.end()) return std::nullopt;
    return it->second;
}
}  // namespace renderer
```

> Read `CommonAnimations.py:149+` in full and transcribe EVERY location case (including any `EBGuest`/`EBL1*` and other entries below the snippet) — do not stop at the lines quoted here.

- [ ] **Step 4: Run to verify pass** — `ctest -R PlacementMap`.
- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/placement_map.h native/src/renderer/placement_map.cc \
        native/src/renderer/CMakeLists.txt native/tests/renderer/placement_map_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): location -> placement-NIF map (from CommonAnimations.SetPosition)"
```

---

### Task 5: Appearance capture (App shim)

**Files:**
- Modify: `engine/appc/characters.py`
- Test: `tests/unit/test_character_appearance.py` (create)

The SDK config calls `CharacterClass_Create(bodyNIF, headNIF)` then `ReplaceBodyAndHead(bodyTex, headTex)`. The current shim's `ReplaceBodyAndHead` overwrites `_body_nif`/`_head_nif` with the **texture** paths, losing the NIFs. Fix: capture all four distinctly and expose them.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_character_appearance.py`:

```python
from engine.appc.characters import CharacterClass_Create

def test_appearance_captures_nifs_and_textures_separately():
    c = CharacterClass_Create("Bodies/BodyFemM/BodyFemM.nif",
                              "Heads/HeadLiu/liu_head.nif")
    c.ReplaceBodyAndHead("Bodies/BodyFemS/FedFemRed_body.tga",
                         "Heads/HeadLiu/liu_head.tga")
    ap = c.appearance()
    assert ap["body_nif"] == "Bodies/BodyFemM/BodyFemM.nif"
    assert ap["head_nif"] == "Heads/HeadLiu/liu_head.nif"
    assert ap["body_tex"] == "Bodies/BodyFemS/FedFemRed_body.tga"
    assert ap["head_tex"] == "Heads/HeadLiu/liu_head.tga"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_character_appearance.py -q`
Expected: FAIL — `ReplaceBodyAndHead` overwrites the NIF fields / no `appearance()`.

- [ ] **Step 3: Implement**

In `engine/appc/characters.py`: in `CharacterClass.__init__`, store the ctor NIFs as `self._body_nif`/`self._head_nif` and init `self._body_tex = ""`, `self._head_tex = ""`. Change `ReplaceBodyAndHead` to write the **texture** fields (and rename its params for clarity), NOT the NIF fields:

```python
    def ReplaceBodyAndHead(self, body_tex: str, head_tex: str) -> None:
        # SDK passes TEXTURE paths here (e.g. FedFemRed_body.tga); the NIFs
        # came from CharacterClass_Create. Keep them distinct.
        self._body_tex = str(body_tex)
        self._head_tex = str(head_tex)

    def appearance(self) -> dict:
        return {
            "body_nif": self._body_nif, "head_nif": self._head_nif,
            "body_tex": self._body_tex, "head_tex": self._head_tex,
        }
```

Verify the ctor sets `_body_nif`/`_head_nif` from its args (it does today via `CharacterClass(body_nif, head_nif)`).

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/unit/test_character_appearance.py -q`.
- [ ] **Step 5: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_character_appearance.py
git commit -m "feat(appc): capture body/head NIFs and textures distinctly for SP3 appearance"
```

---

### Task 6: Native body/head assembly

**Files:**
- Create: `native/src/assets/src/model_compose.h`, `native/src/assets/src/model_compose.cc`
- Modify: `native/src/assets/CMakeLists.txt`
- Modify: `native/src/host/host_bindings.cc` (assembly binding)
- Test: `native/tests/assets/cpu/model_compose_test.cc` (create; register)

Graft a head NIF's meshes into a body `Model`, rigid-bound to the body skeleton's `Bip01 Head` bone, so they share one skeleton + palette.

- [ ] **Step 1: Write the failing test (synthetic)**

Build a minimal body `Model` (2 bones incl. one named `"Bip01 Head"`, one mesh) and a minimal head `Model` (1 mesh), call `graft_head(body, head, "Bip01 Head")`, and assert: body gains the head's mesh; the grafted mesh's vertices are bound to the body bone index whose name is `"Bip01 Head"` (weights `(255,0,0,0)`); head materials/textures are appended and the grafted mesh references one. (Pure CPU, construct `assets::Model` directly — no GL.)

- [ ] **Step 2: Run to verify it fails** — header not found.

- [ ] **Step 3: Implement**

Create `native/src/assets/src/model_compose.{h,cc}` with:

```cpp
// graft_head: append head.meshes (+ their materials/textures, with index
// remapping) into body.meshes, binding every grafted vertex to the body
// skeleton bone whose name == attach_bone (rigid). Returns false (and leaves
// body unchanged) if the bone is not found.
bool graft_head(assets::Model& body, const assets::Model& head,
                std::string_view attach_bone);
```

Implementation: find `attach_bone` index in `body.skeleton`. For each head mesh: deep-copy its `MeshCpu` (requires `keep_cpu_data`), set every vertex `bone_indices=(idx,0,0,0)`, `bone_weights=(255,0,0,0)`, remap `material_index` to a newly-appended copy of the head material (and append head textures, remapping the material's texture-stage indices by the offset `body.textures.size()` before pushing). Append the new mesh to `body.meshes`. (Heads are authored to the standard Bip01, so the head's own root offset positions it at the neck; no geometric fitting.)

> Texture/material remapping detail: read `assets::Material` (`stages[].texture_index`) and append head `model.textures` to body, offsetting each grafted material's stage `texture_index` by the original `body.textures.size()`. The host loads both models with `keep_cpu_data=true` (load_model_impl already sets it) and re-uploads the grafted body model's GL meshes after grafting — OR graft at the CPU level before the GL upload. Choose: graft on CPU `MeshCpu` then `upload_mesh` the new meshes, appending GL `Mesh` to `body.meshes`. Confirm `assets::upload_mesh` is callable here (it is — public in `mesh.h`).

- [ ] **Step 4: Host binding** — `assemble_officer(body_nif, head_nif, body_tex, head_tex)` → ModelHandle: load body (skinned), apply body_tex to body base stages, load head, apply head_tex, `graft_head(body, head, "Bip01 Head")`, return a handle to the composed body model. Mirror `load_model_impl`/`spawn_test_character`. Texture application: replace the base-stage texture of the body/head materials with the loaded `body_tex`/`head_tex` (load via the same texture path the model uses).

- [ ] **Step 5: GL/asset test** — load real `BodyMaleL` + a real head NIF (find one under `game/data/Models/Characters/Heads/`), graft, assert the composed model has more meshes than the body alone and renders foreground pixels. SKIP if assets absent.

- [ ] **Step 6: Build, run, commit**

```bash
git add native/src/assets/src/model_compose.h native/src/assets/src/model_compose.cc \
        native/src/assets/CMakeLists.txt native/src/host/host_bindings.cc \
        native/tests/assets/cpu/model_compose_test.cc native/tests/assets/cpu/CMakeLists.txt
git commit -m "feat(assets): graft head NIF onto body skeleton for composed officers"
```

---

### Task 7: Placement wiring (host / Python)

**Files:**
- Create: `engine/bridge_officers.py`
- Modify: `engine/host_loop.py` (call into the bridge lifecycle)
- Modify: `native/src/host/host_bindings.cc` (`sample_placement_pose` binding if pose eval is native)
- Test: `tests/unit/test_bridge_officers.py` (create; logic-level, host stubbed)

Tie it together: enumerate populated officers with a location + appearance, assemble each, place + pose, and register the bridge instance.

- [ ] **Step 1: Pose-eval binding (native)**

Add `sample_placement_pose(model_handle, placement_nif)` → list of column-major mat4 (the palette): load the placement NIF, take its single `AnimationClip` (`model.animations[0]`), `sample_pose(clip, body_model.skeleton, clip.duration_seconds)`, `build_bone_palette(skeleton, &pose)`, return as a list of 16-float arrays. (The placement clip's bones match the body skeleton by name.) This keeps pose math native; Python only orchestrates.

- [ ] **Step 2: Write the failing logic test**

Create `tests/unit/test_bridge_officers.py` with a fake host exposing `assemble_officer`, `create_bridge_instance`, `sample_placement_pose`, `set_instance_bone_palette`, `set_world_transform`, and a fake officer (`appearance()`, `GetLocation()`). Assert `place_officers([officer], host)`:
- skips officers whose location is hidden or unknown,
- for a visible officer: calls `assemble_officer` with the 4 appearance paths, creates a bridge instance, calls `sample_placement_pose` with the resolved NIF, and sets the returned palette on the instance.

- [ ] **Step 3: Implement `engine/bridge_officers.py`**

```python
"""SP3: place populated bridge officers at their stations (posed + appearance)."""
import engine.renderer as renderer
# location->placement is resolved natively (placement_for_location is C++); the
# host exposes resolve_placement(location)->(nif, hidden) or returns None.

def place_officers(officers, host):
    placed = []
    for off in officers:
        loc = off.GetLocation()
        placement = host.resolve_placement(loc) if loc else None
        if not placement or placement.get("hidden"):
            continue
        ap = off.appearance()
        if not ap.get("body_nif"):
            continue
        model = host.assemble_officer(ap["body_nif"], ap["head_nif"],
                                      ap["body_tex"], ap["head_tex"])
        iid = host.create_bridge_instance(model)
        palette = host.sample_placement_pose(model, placement["nif"])
        host.set_instance_bone_palette(iid, palette)
        host.set_world_transform(iid, _bridge_space_identity())
        placed.append(iid)
    return placed
```

Provide `resolve_placement` as a host binding wrapping `placement_for_location` (returns dict or None) + the data-root-prefixed absolute NIF path. `_bridge_space_identity()` returns the officer's world transform in the bridge set's space (start with identity / the bridge instance transform; the clip's root track carries the station offset). Officer enumeration: gather the populated `CharacterClass` instances (from the bridge set / crew registry — wire to `LoadBridge`/`populate_bridge_crew`'s created characters; expose a `bridge_officers()` accessor there if none exists).

- [ ] **Step 4: Run the logic test** — `uv run pytest tests/unit/test_bridge_officers.py -q`.

- [ ] **Step 5: Integrate into the bridge lifecycle**

In `engine/host_loop.py`, after `populate_bridge_crew` runs for a bridge, call `engine.bridge_officers.place_officers(...)` with the populated officers and the host module. Ensure cleanup on bridge swap / mission reset destroys the officer instances (mirror how bridge geometry instances are torn down).

- [ ] **Step 6: Build, live-verify, commit**

Run: `cmake -B build -S . && cmake --build build -j` then `./build/dauntless --developer` on a mission that loads a bridge. Expected (USER verifies): officers stand/seated, posed, at their stations, distinct per character, on DBridge and EBridge. Coordinate alignment is tuned by feel — the most likely live fixes are the bridge-space transform and any Z-up/X-flip parity in `_bridge_space_identity()` / the officer instance transform.

```bash
git add engine/bridge_officers.py engine/host_loop.py native/src/host/host_bindings.cc tests/unit/test_bridge_officers.py
git commit -m "feat(bridge): place posed per-character officers at their stations (SP3)"
```

---

## Self-Review

**Spec coverage:** sample_pose → Task 1; rigid rebind → Task 2; per-instance palette → Task 3; location→NIF map → Task 4; appearance capture → Task 5; body/head assembly → Task 6; placement wiring + coordinate alignment → Task 7. Testing (CPU sampler/rebind/map/graft, GL posed-differs, live) distributed across tasks. All spec components covered.

**Placeholder scan:** Tasks 2/5/6/7 contain integration steps that say "fill against the real skeleton/registry" — each names the concrete type, the precedent file, and a complete test defining done. The algorithmic tasks (1,3,4) carry full code. No bare TODOs.

**Type consistency:** `sample_pose(clip, skeleton, t)` (Task 1) feeds `build_bone_palette(skeleton, &pose)` (existing). `Instance::bone_palette` / `World::set_bone_palette` / `set_instance_bone_palette` (Task 3) used consistently in Task 7. `placement_for_location → Placement{nif_path,hidden}` (Task 4) consumed via `resolve_placement` (Task 7). `appearance()` keys `body_nif/head_nif/body_tex/head_tex` (Task 5) consumed identically in Task 7. `graft_head(body, head, "Bip01 Head")` (Task 6) used by `assemble_officer` (Task 7).

**Known live-iteration point:** Task 7 coordinate alignment — flagged in the spec as the headline risk; resolved by feel against the running bridge, not provable by gtest.
