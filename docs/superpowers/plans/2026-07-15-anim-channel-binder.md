# Per-Channel Animation Binder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the modal per-instance `AnimationState` with a BC-faithful per-bone channel table (exact-strcmp bind, last-bind-wins, unmatched bones untouched) plus BC's decomp-proven blend-in.

**Architecture:** A new `renderer::channel_binder` unit owns bind/eval/rest logic over `scenegraph::Instance::SkeletalAnim` (per-bone `BoneChannel` array + cached `rest_locals` + `last_locals` blend seeds). `update_animations` becomes a thin per-frame driver: eval channels → `build_bone_palette`. The six Python-visible host bindings keep exact names/signatures; only semantics inside change. Landing is two-stage: structural swap with blending off (Tasks 1–4), then blend-on with dev-gated dials (Task 5).

**Tech Stack:** C++20, glm, pybind11 host bindings, GoogleTest (ctest), pytest for the Python surface. Spec: `docs/superpowers/specs/2026-07-15-anim-channel-binder-design.md`.

## Global Constraints

- Work in the worktree `…/.claude/worktrees/anim-channel-binder` on branch `worktree-anim-channel-binder`. Do NOT touch the main checkout.
- **Shared-repo git rules:** never `git checkout --`/`git restore`/`git stash`/`git clean`/`git reset --hard`/`git add -A`. Stage with explicit pathspecs only. To probe-mutate a file, back it up with `cp` to the scratchpad and restore by `cp`, then `diff` to prove byte-identical restore.
- Build: `cmake --build build -j` (the tree is already configured with `-DPython3_EXECUTABLE=$PWD/.venv/bin/python3` — NEVER reconfigure without that flag; never run cmake from `native/`).
- Run ctest: `ctest --test-dir build --output-on-failure -R <regex>`. Run pytest: `uv run --no-sync pytest <path> -q`. Full gate before finishing a task that touches both suites: `scripts/check_tests.sh` (baseline is GREEN: 0 pytest failures, 0 ctest failures, 0 baselined known failures).
- BC constants (decomp-proven, do not "improve"): blend cap **0.34 s**; short-clip factor **0.75 × duration** when duration < 0.34 s; exact case-sensitive full-string node-name matching; no reverse playback; loop = re-phase, non-loop = clamp+hold.
- The Python layer (`engine/bridge_character_anim.py`, `engine/bridge_character_walk.py`, `engine/host_loop.py`, `engine/renderer.py`) must NOT change (docstring edits allowed, nothing else). Bridge-node animation (`g_bridge_node_anims`, `node_overrides`) and the lip-sync face system are out of scope — do not touch.
- Matrix convention: column-vector, right-handed; body-frame composition is `T·R·S` (matches `assets::sample_track_trs`).

---

### Task 1: Channel data model + `bind_clip` (additive — old system untouched)

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h` (add `BoneChannel`/`SkeletalAnim`; keep `AnimationState` for now)
- Create: `native/src/renderer/include/renderer/channel_binder.h`
- Create: `native/src/renderer/channel_binder.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `channel_binder.cc` next to `pose_sampler.cc`, line ~93)
- Create: `native/tests/renderer/channel_binder_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt` (add `channel_binder_test.cc` next to `animation_update_test.cc`, line ~20)

**Interfaces:**
- Consumes: `assets::AnimationClip` (`tracks[].target_node_name`, `duration_seconds`, `rest_locals`), `assets::Skeleton`/`Bone` (`name`, `local_transform`, `root_bone_index`), `assets::Model` (`skeleton`, `animations`), `renderer::sample_pose` (unchanged).
- Produces (later tasks rely on these exact signatures):
  - `scenegraph::Instance::BoneChannel` / `scenegraph::Instance::SkeletalAnim` / `Instance::anim` member
  - `renderer::BindOptions{bool loop, root_motion, use_clip_base, hold_at_start, blend}`
  - `renderer::BlendParams{float cap_s; float short_factor; int curve;}` + `renderer::blend_params()` + `renderer::set_blend_params(const BlendParams&)` + `renderer::blend_in_seconds(float dur)`
  - `int renderer::bind_clip(scenegraph::Instance&, const assets::Model&, int clip_index, const BindOptions&, double now_wall_time)`
  - `void renderer::clear_channels(scenegraph::Instance&)`
  - `void renderer::set_rest_pose(scenegraph::Instance&, const assets::Model&, int clip_index, bool at_start)`

- [ ] **Step 1: Add the channel data model to `instance.h`**

In `native/src/scenegraph/include/scenegraph/instance.h`, add `#include <glm/gtc/quaternion.hpp>` to the includes, and insert immediately BEFORE `struct AnimationState`:

```cpp
    /// ── Per-channel skeletal animation (BC TGAnimBlender-faithful) ──────────
    /// One channel per skeleton bone. clip_index < 0 = unbound: the bone shows
    /// its rest local (SkeletalAnim::rest_locals) or, without a rest pose, the
    /// skeleton bind local. Channels are (re)bound per bone by
    /// renderer::bind_clip via BC's exact case-sensitive node-name strcmp;
    /// bones a clip does not track keep their previous channel untouched
    /// (per-node last-bind-wins — every bridge animation in BC is
    /// non-exclusive). Runtime state, never serialized.
    struct BoneChannel {
        int    clip_index  = -1;   // into Model::animations
        int    track_index = -1;   // into clip.tracks (name-matched at bind)
        double start_wall_time = 0.0;
        float  blend_in_s = 0.0f;  // 0 = snap; else ramp seed→clip over this
        bool   loop = false;           // idle loops; gestures/walks clamp+hold
        bool   root_motion = false;    // root bone: APPLY track translation
        bool   use_clip_base = false;  // omitted-channel base = clip rest_locals
        bool   hold_at_start = false;  // evaluate at t=0 and settle immediately
        bool   settled = false;        // non-loop reached end AND blend done
        // Blend seed: the bone's local at bind time, decomposed once.
        glm::vec3 seed_t{0.0f};
        glm::quat seed_r{1.0f, 0.0f, 0.0f, 0.0f};
        float     seed_s = 1.0f;
    };
    struct SkeletalAnim {
        std::vector<BoneChannel> channels;   // sized to skeleton at first use
        std::vector<glm::mat4>  rest_locals; // placement pose, sampled ONCE
        std::vector<glm::mat4>  last_locals; // last evaluated pose (blend seeds)
        bool has_rest = false;
        bool dirty    = true;   // false = everything settled; skip rebuilds
    };
    SkeletalAnim anim;
```

- [ ] **Step 2: Write the failing tests for `bind_clip`**

Create `native/tests/renderer/channel_binder_test.cc`:

```cpp
// bind_clip: BC's channel join — exact case-sensitive full-string strcmp of
// clip track names against skeleton bone names; hit = rebind that bone's
// channel (seeding the blend-from pose), miss = track dropped silently;
// untouched bones keep their previous channel (last-bind-wins per node).
#include <gtest/gtest.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/epsilon.hpp>
#include <scenegraph/world.h>
#include <assets/model.h>
#include <renderer/channel_binder.h>

namespace {

// Skeleton: "Bip01" root, children "Bip01 Head" (+Y 5) and "Bip01 Spine" (+Y 2).
assets::Model three_bone_model() {
    assets::Model m;
    assets::Bone b0; b0.name = "Bip01"; b0.parent_index = -1;
    b0.local_transform = glm::mat4(1.0f);
    assets::Bone b1; b1.name = "Bip01 Head"; b1.parent_index = 0;
    b1.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 5, 0));
    assets::Bone b2; b2.name = "Bip01 Spine"; b2.parent_index = 0;
    b2.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 2, 0));
    m.skeleton.bones = {b0, b1, b2};
    m.skeleton.root_bone_index = 0;
    for (auto& b : m.skeleton.bones) b.inverse_bind_pose = glm::mat4(1.0f);
    return m;
}

assets::AnimationClip clip_tracking(std::initializer_list<const char*> names,
                                    float dur = 1.0f) {
    assets::AnimationClip c; c.name = "c"; c.duration_seconds = dur;
    glm::quat q = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    for (const char* n : names) {
        assets::AnimationClip::NodeTrack tr; tr.target_node_name = n;
        tr.rotation = {{0.0f, q}, {dur, q}};
        c.tracks.push_back(tr);
    }
    return c;
}

}  // namespace

TEST(BindClip, ExactStrcmpJoinBindsOnlyMatchedBones) {
    assets::Model m = three_bone_model();
    // Track 0 matches "Bip01 Head"; track 1 ("Kiska Head") and track 2
    // ("bip01 spine" — wrong case) are dead ballast, BC-style.
    m.animations = {clip_tracking({"Bip01 Head", "Kiska Head", "bip01 spine"})};

    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);

    int bound = renderer::bind_clip(inst, m, 0, {}, /*now=*/10.0);
    EXPECT_EQ(bound, 1);
    ASSERT_EQ(inst.anim.channels.size(), 3u);
    EXPECT_EQ(inst.anim.channels[0].clip_index, -1);   // Bip01 untouched
    EXPECT_EQ(inst.anim.channels[1].clip_index, 0);    // Bip01 Head bound
    EXPECT_EQ(inst.anim.channels[1].track_index, 0);
    EXPECT_EQ(inst.anim.channels[1].start_wall_time, 10.0);
    EXPECT_EQ(inst.anim.channels[2].clip_index, -1);   // Bip01 Spine untouched
    EXPECT_TRUE(inst.anim.dirty);
}

TEST(BindClip, ZeroMatchClipBindsNothingAndMutatesNothing) {
    assets::Model m = three_bone_model();
    m.animations = {clip_tracking({"Bip01 Head"}),      // clip 0: idle
                    clip_tracking({"Kiska Head"})};     // clip 1: dead
    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);

    ASSERT_EQ(renderer::bind_clip(inst, m, 0, {}, 1.0), 1);
    auto before = inst.anim.channels;   // copy
    inst.anim.dirty = false;            // simulate a settled frame

    EXPECT_EQ(renderer::bind_clip(inst, m, 1, {}, 2.0), 0);
    EXPECT_FALSE(inst.anim.dirty) << "dead clip must not re-dirty";
    ASSERT_EQ(inst.anim.channels.size(), before.size());
    for (std::size_t i = 0; i < before.size(); ++i)
        EXPECT_EQ(inst.anim.channels[i].clip_index, before[i].clip_index);
}

TEST(BindClip, LastBindWinsPerBoneOnly) {
    assets::Model m = three_bone_model();
    m.animations = {clip_tracking({"Bip01 Head", "Bip01 Spine"}),  // breathe
                    clip_tracking({"Bip01 Head"})};                // gesture
    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);

    renderer::BindOptions loop_opts; loop_opts.loop = true;
    ASSERT_EQ(renderer::bind_clip(inst, m, 0, loop_opts, 1.0), 2);
    ASSERT_EQ(renderer::bind_clip(inst, m, 1, {}, 5.0), 1);

    EXPECT_EQ(inst.anim.channels[1].clip_index, 1);   // head → gesture
    EXPECT_FALSE(inst.anim.channels[1].loop);
    EXPECT_EQ(inst.anim.channels[1].start_wall_time, 5.0);
    EXPECT_EQ(inst.anim.channels[2].clip_index, 0);   // spine keeps breathe
    EXPECT_TRUE(inst.anim.channels[2].loop);
    EXPECT_EQ(inst.anim.channels[2].start_wall_time, 1.0);
}

TEST(BindClip, SeedComesFromLastLocalsThenRestThenBind) {
    assets::Model m = three_bone_model();
    m.animations = {clip_tracking({"Bip01 Head"})};
    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);

    // No last_locals, no rest → seed = bind local (+Y 5).
    renderer::bind_clip(inst, m, 0, {}, 0.0);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        inst.anim.channels[1].seed_t, glm::vec3(0, 5, 0), 1e-5f)));

    // With last_locals present → seed = last evaluated local.
    inst.anim.last_locals.assign(3, glm::mat4(1.0f));
    inst.anim.last_locals[1] =
        glm::translate(glm::mat4(1.0f), glm::vec3(7, 8, 9));
    renderer::bind_clip(inst, m, 0, {}, 1.0);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        inst.anim.channels[1].seed_t, glm::vec3(7, 8, 9), 1e-5f)));
}

TEST(BindClip, BlendFlagUsesBcFormulaOtherwiseZero) {
    assets::Model m = three_bone_model();
    m.animations = {clip_tracking({"Bip01 Head"}, /*dur=*/1.0f),
                    clip_tracking({"Bip01 Head"}, /*dur=*/0.1f)};
    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);

    renderer::bind_clip(inst, m, 0, {}, 0.0);          // blend=false default
    EXPECT_EQ(inst.anim.channels[1].blend_in_s, 0.0f);

    renderer::BindOptions b; b.blend = true;
    renderer::bind_clip(inst, m, 0, b, 0.0);           // dur 1.0 ≥ cap
    EXPECT_NEAR(inst.anim.channels[1].blend_in_s, 0.34f, 1e-6f);
    renderer::bind_clip(inst, m, 1, b, 0.0);           // dur 0.1 < cap
    EXPECT_NEAR(inst.anim.channels[1].blend_in_s, 0.075f, 1e-6f);
}

TEST(SetRestPose, SamplesOnceClearsChannelsAndSetsRest) {
    assets::Model m = three_bone_model();
    // Placement clip with rest_locals only (no tracks) — the standard BC shape.
    assets::AnimationClip place; place.name = "place"; place.duration_seconds = 1.0f;
    place.rest_locals["Bip01"] =
        glm::translate(glm::mat4(1.0f), glm::vec3(33, -104, 23));
    place.rest_locals["Bip01 Head"] = m.skeleton.bones[1].local_transform;
    place.rest_locals["Bip01 Spine"] = m.skeleton.bones[2].local_transform;
    m.animations = {place, clip_tracking({"Bip01 Head"})};

    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);

    renderer::bind_clip(inst, m, 1, {}, 0.0);           // pre-existing gesture
    renderer::set_rest_pose(inst, m, 0, /*at_start=*/false);

    EXPECT_TRUE(inst.anim.has_rest);
    ASSERT_EQ(inst.anim.rest_locals.size(), 3u);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        glm::vec3(inst.anim.rest_locals[0][3]), glm::vec3(33, -104, 23), 1e-4f)));
    for (const auto& ch : inst.anim.channels)
        EXPECT_EQ(ch.clip_index, -1) << "set_rest_pose must clear all channels";
    EXPECT_TRUE(inst.anim.dirty);

    // restore semantics: clear_channels after a new bind falls back to rest.
    renderer::bind_clip(inst, m, 1, {}, 2.0);
    EXPECT_EQ(inst.anim.channels[1].clip_index, 1);
    renderer::clear_channels(inst);
    for (const auto& ch : inst.anim.channels) EXPECT_EQ(ch.clip_index, -1);
    EXPECT_TRUE(inst.anim.has_rest) << "clear_channels must keep the rest pose";
}
```

- [ ] **Step 3: Register the test and run it to verify it fails to compile**

Add `channel_binder_test.cc` to `native/tests/renderer/CMakeLists.txt` after `animation_update_test.cc` (line ~20). Run:

```bash
cmake --build build -j 2>&1 | tail -5
```
Expected: FAIL — `renderer/channel_binder.h: No such file or directory`.

- [ ] **Step 4: Implement the header**

Create `native/src/renderer/include/renderer/channel_binder.h`:

```cpp
// native/src/renderer/include/renderer/channel_binder.h
//
// BC-faithful per-bone channel binder. stbc.exe's TGAnimBlender binds clip
// channels to character nodes by an exact, case-sensitive, full-string strcmp
// join of two name-sorted tables (decomp: SetTarget 0x006C6900, LoadAnimation
// 0x006C8290, lookup FUN_006CC730): hit = rebind that node's controllers to
// the clip's keys; miss = the channel is dead ballast, silently. Every bridge
// animation in BC is NON-exclusive (TGAnimAction_Create(…, 0, 0[, 1])), so
// bones a clip does not track keep whatever drove them before — per-node
// last-bind-wins. This unit reproduces that observable machine over
// scenegraph::Instance::SkeletalAnim.
#pragma once
#include <vector>
#include <glm/glm.hpp>
#include <scenegraph/instance.h>

namespace assets { struct Model; }

namespace renderer {

struct BindOptions {
    bool loop = false;           // idle loops; gestures/walks clamp+hold
    bool root_motion = false;    // root bone: APPLY the clip's translation
    bool use_clip_base = false;  // omitted-channel base = clip's rest_locals
    bool hold_at_start = false;  // evaluate at t=0 and settle immediately
    bool blend = false;          // blend-in per blend_params() (BC default ON;
                                 // positioning paths snap)
};

/// Feel dials for the blend-in. BC (TGAnimAction::Play, 0x00704140):
/// blendTime = dur < 0.34 ? dur * 0.75 : 0.34. curve: 0 = linear (default;
/// NiAnimBlender's actual ramp is undecoded), 1 = smoothstep.
struct BlendParams {
    float cap_s = 0.34f;
    float short_factor = 0.75f;
    int   curve = 0;
};
BlendParams blend_params();
void set_blend_params(const BlendParams& p);
/// BC's blend-time formula for a clip of `clip_duration_s`, per current params.
float blend_in_seconds(float clip_duration_s);

/// Bind model.animations[clip_index] onto the instance's channel table: for
/// each clip track whose target_node_name exactly equals a bone name, overwrite
/// that bone's channel (seeding blend-from from last_locals, else rest_locals,
/// else the bind local). Unmatched tracks are dropped; untracked bones keep
/// their previous channel. Returns the number of bones bound — 0 means the
/// clip is dead ballast on this skeleton and NOTHING changed (BC's silent
/// no-op; the old play_instance_gesture gate, now emergent).
int bind_clip(scenegraph::Instance& inst, const assets::Model& model,
              int clip_index, const BindOptions& opts, double now_wall_time);

/// Unbind every channel; bones fall back to rest_locals (kept) or bind.
void clear_channels(scenegraph::Instance& inst);

/// Sample the placement clip ONCE (t=0 if at_start else t=duration) into
/// rest_locals via sample_pose, set has_rest, and clear all channels. Snap —
/// no blend (BC's positioning path bypasses blending).
void set_rest_pose(scenegraph::Instance& inst, const assets::Model& model,
                   int clip_index, bool at_start);

/// Evaluate every bone's channel at `now` into per-bone LOCAL transforms
/// (skeleton order): unbound → rest/bind local; bound → track sample at
/// fmod/clamped t over the channel's base (instance rest_locals, or the
/// clip's own rest_locals when use_clip_base), root translation from base
/// unless root_motion, then blend seed→sample while inside the blend window.
/// Side effects: updates channel settled flags, writes anim.last_locals, and
/// clears anim.dirty when nothing needs further rebuilds. Feed the result to
/// build_bone_palette.
std::vector<glm::mat4> eval_channels(scenegraph::Instance& inst,
                                     const assets::Model& model,
                                     double now_wall_time);

}  // namespace renderer
```

- [ ] **Step 5: Implement `channel_binder.cc` (bind/clear/rest only — `eval_channels` stubbed)**

Create `native/src/renderer/channel_binder.cc`:

```cpp
// native/src/renderer/channel_binder.cc
#include "renderer/channel_binder.h"

#include <algorithm>
#include <cmath>

#include <glm/gtx/quaternion.hpp>

#include <assets/model.h>
#include <assets/pose_sample.h>
#include "renderer/pose_sampler.h"

namespace {

renderer::BlendParams g_blend_params{};

// Decompose a local TRS matrix (same normalization as the historical
// pose_bone): translation from column 3, uniform scale from column lengths,
// rotation from the normalized 3x3.
void decompose_trs(const glm::mat4& m, glm::vec3& out_t, glm::quat& out_r,
                   float& out_s) {
    out_t = glm::vec3(m[3]);
    glm::mat3 m3(m);
    float s = glm::length(m3[0]);
    if (s > 1e-8f) {
        m3[0] /= s;
        m3[1] /= glm::max(glm::length(m3[1]), 1e-8f);
        m3[2] /= glm::max(glm::length(m3[2]), 1e-8f);
    } else {
        s = 1.0f;
    }
    out_r = glm::quat_cast(m3);
    out_s = s;
}

// The bone's current local for blend seeding: last evaluated pose if the
// instance has one, else its rest local, else the skeleton bind local.
glm::mat4 current_local(const scenegraph::Instance& inst,
                        const assets::Skeleton& skeleton, std::size_t bone) {
    if (bone < inst.anim.last_locals.size()) return inst.anim.last_locals[bone];
    if (inst.anim.has_rest && bone < inst.anim.rest_locals.size())
        return inst.anim.rest_locals[bone];
    return skeleton.bones[bone].local_transform;
}

}  // namespace

namespace renderer {

BlendParams blend_params() { return g_blend_params; }
void set_blend_params(const BlendParams& p) { g_blend_params = p; }

float blend_in_seconds(float clip_duration_s) {
    const BlendParams& p = g_blend_params;
    if (clip_duration_s > 0.0f && clip_duration_s < p.cap_s)
        return clip_duration_s * p.short_factor;
    return p.cap_s;
}

int bind_clip(scenegraph::Instance& inst, const assets::Model& model,
              int clip_index, const BindOptions& opts, double now_wall_time) {
    const assets::Skeleton& skel = model.skeleton;
    if (clip_index < 0 ||
        clip_index >= static_cast<int>(model.animations.size()) ||
        skel.bones.empty())
        return 0;
    const assets::AnimationClip& clip = model.animations[clip_index];

    // The strcmp join: bone index per matched track, computed BEFORE any
    // mutation so a zero-match clip changes nothing at all.
    std::vector<std::pair<std::size_t, int>> hits;  // (bone, track)
    for (int ti = 0; ti < static_cast<int>(clip.tracks.size()); ++ti)
        for (std::size_t bi = 0; bi < skel.bones.size(); ++bi)
            if (skel.bones[bi].name == clip.tracks[ti].target_node_name)
                hits.emplace_back(bi, ti);
    if (hits.empty()) return 0;

    if (inst.anim.channels.size() != skel.bones.size())
        inst.anim.channels.assign(skel.bones.size(),
                                  scenegraph::Instance::BoneChannel{});

    const float blend = opts.blend ? blend_in_seconds(clip.duration_seconds)
                                   : 0.0f;
    for (auto [bi, ti] : hits) {
        scenegraph::Instance::BoneChannel& ch = inst.anim.channels[bi];
        decompose_trs(current_local(inst, skel, bi),
                      ch.seed_t, ch.seed_r, ch.seed_s);
        ch.clip_index = clip_index;
        ch.track_index = ti;
        ch.start_wall_time = now_wall_time;
        ch.blend_in_s = blend;
        ch.loop = opts.loop;
        ch.root_motion = opts.root_motion;
        ch.use_clip_base = opts.use_clip_base;
        ch.hold_at_start = opts.hold_at_start;
        ch.settled = false;
    }
    inst.anim.dirty = true;
    return static_cast<int>(hits.size());
}

void clear_channels(scenegraph::Instance& inst) {
    for (auto& ch : inst.anim.channels)
        ch = scenegraph::Instance::BoneChannel{};
    inst.anim.dirty = true;
}

void set_rest_pose(scenegraph::Instance& inst, const assets::Model& model,
                   int clip_index, bool at_start) {
    if (clip_index < 0 ||
        clip_index >= static_cast<int>(model.animations.size()))
        return;
    const assets::AnimationClip& clip = model.animations[clip_index];
    const float t = at_start ? 0.0f : clip.duration_seconds;
    inst.anim.rest_locals = sample_pose(clip, model.skeleton, t);
    inst.anim.has_rest = true;
    if (inst.anim.channels.size() != model.skeleton.bones.size())
        inst.anim.channels.assign(model.skeleton.bones.size(),
                                  scenegraph::Instance::BoneChannel{});
    clear_channels(inst);
}

std::vector<glm::mat4> eval_channels(scenegraph::Instance& inst,
                                     const assets::Model& model,
                                     double now_wall_time) {
    (void)now_wall_time;
    // Implemented in Task 2.
    return std::vector<glm::mat4>(model.skeleton.bones.size(), glm::mat4(1.0f));
}

}  // namespace renderer
```

Add `channel_binder.cc` to `native/src/renderer/CMakeLists.txt` next to `pose_sampler.cc`.

- [ ] **Step 6: Build and run the Task 1 tests**

```bash
cmake --build build -j && ctest --test-dir build --output-on-failure -R "BindClip|SetRestPose"
```
Expected: all 6 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add native/src/scenegraph/include/scenegraph/instance.h \
        native/src/renderer/include/renderer/channel_binder.h \
        native/src/renderer/channel_binder.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/channel_binder_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(renderer): per-bone channel table + BC exact-strcmp bind_clip

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `eval_channels` — per-bone evaluation with blend window

**Files:**
- Modify: `native/src/renderer/channel_binder.cc` (replace the `eval_channels` stub)
- Test: `native/tests/renderer/channel_binder_test.cc` (append)

**Interfaces:**
- Consumes: Task 1's `bind_clip`/`set_rest_pose`/`BoneChannel`, `assets::sample_track_translation/rotation/scale` (from `assets/pose_sample.h`).
- Produces: working `renderer::eval_channels` exactly as declared in Task 1's header — Task 3's `update_animations` calls it verbatim.

- [ ] **Step 1: Write the failing tests** (append to `channel_binder_test.cc`)

```cpp
namespace {
// Placement clip (rest_locals only): root at the station (33,-104,23).
// Gesture clip: rotates "Bip01 Head" 0→90° about Z over 1 s.
// Walk clip: translates "Bip01" (0,0,0)→(100,0,0) over 1 s, with clip
// rest_locals placing the head at its bind offset.
assets::Model officer_like_model() {
    assets::Model m = three_bone_model();
    assets::AnimationClip place; place.name = "place";
    place.duration_seconds = 1.0f;
    place.rest_locals["Bip01"] =
        glm::translate(glm::mat4(1.0f), glm::vec3(33, -104, 23));
    place.rest_locals["Bip01 Head"] = m.skeleton.bones[1].local_transform;
    place.rest_locals["Bip01 Spine"] = m.skeleton.bones[2].local_transform;

    assets::AnimationClip gesture; gesture.name = "gesture";
    gesture.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack g; g.target_node_name = "Bip01 Head";
    g.rotation = {{0.0f, glm::quat(1, 0, 0, 0)},
                  {1.0f, glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1))}};
    gesture.tracks = {g};

    assets::AnimationClip walk; walk.name = "walk";
    walk.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack wr; wr.target_node_name = "Bip01";
    wr.translation = {{0.0f, glm::vec3(0, 0, 0)}, {1.0f, glm::vec3(100, 0, 0)}};
    walk.tracks = {wr};
    walk.rest_locals["Bip01"] = glm::mat4(1.0f);
    walk.rest_locals["Bip01 Head"] = m.skeleton.bones[1].local_transform;
    walk.rest_locals["Bip01 Spine"] = m.skeleton.bones[2].local_transform;

    m.animations = {place, gesture, walk};
    return m;
}
}  // namespace

TEST(EvalChannels, UnboundBonesShowRestElseBind) {
    assets::Model m = officer_like_model();
    scenegraph::World w; scenegraph::Instance& inst = *w.get(w.create_instance(1));

    // No rest, no channels → bind locals.
    auto locals = renderer::eval_channels(inst, m, 0.0);
    ASSERT_EQ(locals.size(), 3u);
    EXPECT_EQ(locals[1], m.skeleton.bones[1].local_transform);

    renderer::set_rest_pose(inst, m, 0, /*at_start=*/false);
    locals = renderer::eval_channels(inst, m, 0.0);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        glm::vec3(locals[0][3]), glm::vec3(33, -104, 23), 1e-4f)));
    EXPECT_FALSE(inst.anim.dirty) << "rest-only instance settles after one eval";
}

TEST(EvalChannels, GestureRotatesItsBoneOverRestAndClampsSettles) {
    assets::Model m = officer_like_model();
    scenegraph::World w; scenegraph::Instance& inst = *w.get(w.create_instance(1));
    renderer::set_rest_pose(inst, m, 0, false);
    renderer::bind_clip(inst, m, 1, {}, /*now=*/100.0);

    // Mid-clip: head rotated ~45°, root still at station, spine at rest.
    auto locals = renderer::eval_channels(inst, m, 100.5);
    glm::quat head_r = glm::quat_cast(glm::mat3(locals[1]));
    EXPECT_NEAR(glm::degrees(glm::angle(head_r)), 45.0f, 1.0f);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        glm::vec3(locals[0][3]), glm::vec3(33, -104, 23), 1e-4f)));
    EXPECT_FALSE(inst.anim.channels[1].settled);
    EXPECT_TRUE(inst.anim.dirty);

    // Past the end: clamped at 90°, settled, dirty cleared.
    locals = renderer::eval_channels(inst, m, 200.0);
    head_r = glm::quat_cast(glm::mat3(locals[1]));
    EXPECT_NEAR(glm::degrees(glm::angle(head_r)), 90.0f, 1.0f);
    EXPECT_TRUE(inst.anim.channels[1].settled);
    EXPECT_FALSE(inst.anim.dirty);
    EXPECT_EQ(inst.anim.last_locals.size(), 3u);
}

TEST(EvalChannels, LoopWrapsViaFmodAndNeverSettles) {
    assets::Model m = officer_like_model();
    scenegraph::World w; scenegraph::Instance& inst = *w.get(w.create_instance(1));
    renderer::set_rest_pose(inst, m, 0, false);
    renderer::BindOptions o; o.loop = true;
    renderer::bind_clip(inst, m, 1, o, 0.0);

    auto at = [&](double now) {
        auto locals = renderer::eval_channels(inst, m, now);
        return glm::degrees(glm::angle(glm::quat_cast(glm::mat3(locals[1]))));
    };
    EXPECT_NEAR(at(0.25), 22.5f, 1.0f);
    EXPECT_NEAR(at(10.25), 22.5f, 1.0f);   // same phase 10 cycles later
    EXPECT_FALSE(inst.anim.channels[1].settled);
    EXPECT_TRUE(inst.anim.dirty);
}

TEST(EvalChannels, RootMotionAppliesTranslationAnchorOtherwise) {
    assets::Model m = officer_like_model();
    scenegraph::World w; scenegraph::Instance& inst = *w.get(w.create_instance(1));
    renderer::set_rest_pose(inst, m, 0, false);

    // Walk bind: root_motion applies the track translation over the CLIP base.
    renderer::BindOptions walk; walk.root_motion = true; walk.use_clip_base = true;
    renderer::bind_clip(inst, m, 2, walk, 0.0);
    auto locals = renderer::eval_channels(inst, m, 0.5);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        glm::vec3(locals[0][3]), glm::vec3(50, 0, 0), 1e-3f)));

    // Same clip WITHOUT root_motion: root translation stays at the base
    // (instance rest → the station), BC's gesture root-anchor.
    renderer::bind_clip(inst, m, 2, {}, 0.0);
    locals = renderer::eval_channels(inst, m, 0.5);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        glm::vec3(locals[0][3]), glm::vec3(33, -104, 23), 1e-3f)));
}

TEST(EvalChannels, HoldAtStartFreezesAtTZero) {
    assets::Model m = officer_like_model();
    scenegraph::World w; scenegraph::Instance& inst = *w.get(w.create_instance(1));
    renderer::BindOptions o; o.hold_at_start = true;
    o.root_motion = true; o.use_clip_base = true;
    renderer::bind_clip(inst, m, 2, o, 0.0);

    auto locals = renderer::eval_channels(inst, m, 500.0);   // way past start
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        glm::vec3(locals[0][3]), glm::vec3(0, 0, 0), 1e-4f)));
    EXPECT_TRUE(inst.anim.channels[0].settled);
    EXPECT_FALSE(inst.anim.dirty);
}

TEST(EvalChannels, BlendWindowRampsSeedToClipThenSettlesBlendDone) {
    assets::Model m = officer_like_model();
    scenegraph::World w; scenegraph::Instance& inst = *w.get(w.create_instance(1));
    renderer::set_rest_pose(inst, m, 0, false);

    // Head displaced by a previous pose: last_locals says head local is +X 40.
    inst.anim.last_locals = inst.anim.rest_locals;
    inst.anim.last_locals[1] = glm::translate(glm::mat4(1.0f), glm::vec3(40, 0, 0));

    // Bind the gesture WITH blend. Gesture has no translation channel, so its
    // sampled head translation = base (+Y 5). Blend must ramp 40→0 on X.
    renderer::BindOptions b; b.blend = true;
    renderer::bind_clip(inst, m, 1, b, /*now=*/0.0);
    ASSERT_NEAR(inst.anim.channels[1].blend_in_s, 0.34f, 1e-6f);

    auto head_x = [&](double now) {
        return renderer::eval_channels(inst, m, now)[1][3].x;
    };
    EXPECT_NEAR(head_x(0.0), 40.0f, 1e-3f);            // w=0 → pure seed
    EXPECT_NEAR(head_x(0.17), 20.0f, 0.5f);            // w=0.5 linear midpoint
    EXPECT_NEAR(head_x(0.34), 0.0f, 1e-3f);            // w=1 → pure clip
    EXPECT_NEAR(head_x(0.5), 0.0f, 1e-3f);             // past window: clip only

    // A non-loop bound bone is settled only once BOTH clip end and blend end
    // have passed; here dur (1.0) > blend (0.34), so settle at t >= 1.0.
    renderer::eval_channels(inst, m, 0.9);
    EXPECT_FALSE(inst.anim.channels[1].settled);
    renderer::eval_channels(inst, m, 1.1);
    EXPECT_TRUE(inst.anim.channels[1].settled);
}
```

- [ ] **Step 2: Build and verify the new tests fail**

```bash
cmake --build build -j && ctest --test-dir build --output-on-failure -R EvalChannels
```
Expected: FAIL — the stub returns identity locals (rest/rotation/root assertions all miss).

- [ ] **Step 3: Implement `eval_channels`**

Replace the stub in `channel_binder.cc`:

```cpp
std::vector<glm::mat4> eval_channels(scenegraph::Instance& inst,
                                     const assets::Model& model,
                                     double now_wall_time) {
    const assets::Skeleton& skel = model.skeleton;
    const std::size_t n = skel.bones.size();
    std::vector<glm::mat4> locals(n);
    bool any_live = false;   // anything still animating or blending?

    for (std::size_t i = 0; i < n; ++i) {
        // Base local: the instance placement pose, else the bind local.
        const glm::mat4& inst_base =
            (inst.anim.has_rest && i < inst.anim.rest_locals.size())
                ? inst.anim.rest_locals[i]
                : skel.bones[i].local_transform;

        scenegraph::Instance::BoneChannel* ch =
            i < inst.anim.channels.size() ? &inst.anim.channels[i] : nullptr;
        if (!ch || ch->clip_index < 0 ||
            ch->clip_index >= static_cast<int>(model.animations.size())) {
            locals[i] = inst_base;
            continue;
        }
        const assets::AnimationClip& clip = model.animations[ch->clip_index];
        if (ch->track_index < 0 ||
            ch->track_index >= static_cast<int>(clip.tracks.size())) {
            locals[i] = inst_base;
            continue;
        }
        const assets::AnimationClip::NodeTrack& tr =
            clip.tracks[ch->track_index];

        // Omitted-channel base: walks/generic clips fall back to the CLIP's
        // own rest pose (matching the historical non-layered sample_pose);
        // gestures/idles fall back to the instance placement.
        glm::mat4 base = inst_base;
        if (ch->use_clip_base) {
            auto rit = clip.rest_locals.find(skel.bones[i].name);
            base = rit != clip.rest_locals.end()
                       ? rit->second
                       : skel.bones[i].local_transform;
        }
        glm::vec3 base_t; glm::quat base_r; float base_s;
        decompose_trs(base, base_t, base_r, base_s);

        // Playback time: hold_at_start pins t=0; loop wraps; else clamp+hold.
        const float dur = clip.duration_seconds;
        double elapsed = now_wall_time - ch->start_wall_time;
        if (elapsed < 0.0) elapsed = 0.0;
        float t;
        if (ch->hold_at_start) {
            t = 0.0f;
            ch->settled = true;
        } else if (ch->loop) {
            t = dur > 0.0f ? static_cast<float>(std::fmod(elapsed, dur)) : 0.0f;
        } else if (elapsed >= dur) {
            t = dur;
        } else {
            t = static_cast<float>(elapsed);
        }

        glm::vec3 s_t = assets::sample_track_translation(tr, t, base_t);
        glm::quat s_r = assets::sample_track_rotation(tr, t, base_r);
        float     s_s = assets::sample_track_scale(tr, t, base_s);

        // BC's gesture root-anchor: keep the clip's root ROTATION but take the
        // root POSITION from the base unless this bind carries root motion.
        if (static_cast<int>(i) == skel.root_bone_index && !ch->root_motion)
            s_t = base_t;

        // Blend window: ramp the bind-time seed toward the sampled value.
        bool blending = false;
        if (ch->blend_in_s > 0.0f && elapsed < ch->blend_in_s) {
            blending = true;
            float w = static_cast<float>(elapsed) / ch->blend_in_s;
            if (blend_params().curve == 1) w = w * w * (3.0f - 2.0f * w);
            s_t = glm::mix(ch->seed_t, s_t, w);
            s_r = glm::slerp(ch->seed_r, s_r, w);
            s_s = glm::mix(ch->seed_s, s_s, w);
        }

        locals[i] = glm::translate(glm::mat4(1.0f), s_t) *
                    glm::mat4_cast(s_r) *
                    glm::scale(glm::mat4(1.0f), glm::vec3(s_s));

        // Settle bookkeeping: a channel is done when it neither advances nor
        // blends. hold_at_start settled above; loops never settle.
        if (!ch->hold_at_start && !ch->loop)
            ch->settled = (elapsed >= dur) && !blending;
        if (!ch->settled) any_live = true;
    }

    inst.anim.last_locals = locals;
    inst.anim.dirty = any_live;
    return locals;
}
```

Add `#include <glm/gtc/matrix_transform.hpp>` to `channel_binder.cc`'s includes.

- [ ] **Step 4: Build and run all channel-binder tests**

```bash
cmake --build build -j && ctest --test-dir build --output-on-failure -R "BindClip|SetRestPose|EvalChannels"
```
Expected: all 12 tests PASS. Note `EvalChannels.UnboundBonesShowRestElseBind` asserts `dirty=false` after one eval — an instance with no live channels must go clean (the caller rebuilds the palette that one time; see Task 3's driver, which checks `dirty` BEFORE eval).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/channel_binder.cc native/tests/renderer/channel_binder_test.cc
git commit -m "feat(renderer): eval_channels — per-bone sampling, root anchor/motion, blend window

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Cutover — rewrite `update_animations` + the six host bindings; delete the modal system (blend stays OFF)

This is the swap task. After it, `Instance::AnimationState` no longer exists; every consumer runs on the channel table. All `BindOptions.blend` stay `false` (landing commit 1: structural swap at blend = 0).

**Files:**
- Modify: `native/src/renderer/animation_update.cc` (full rewrite)
- Modify: `native/src/renderer/include/renderer/animation_update.h` (doc comment only)
- Modify: `native/src/host/host_bindings.cc:1240-1338` (six bindings) — keep `py::arg` names/defaults byte-identical
- Modify: `native/src/scenegraph/include/scenegraph/instance.h` (delete `AnimationState`, `animation`, `rest_pose`, `has_rest_pose`)
- Modify: `native/src/scenegraph/include/scenegraph/world.h` + `native/src/scenegraph/src/world.cc` (delete `set_animation`, `set_rest_pose`, `restore_rest_pose`)
- Modify: `native/src/renderer/include/renderer/pose_sampler.h` + `pose_sampler.cc` (delete `sample_pose_over_base` and `clip_drives_skeleton`; keep `sample_pose`)
- Modify: `native/tests/renderer/animation_update_test.cc` (full rewrite onto the new API)
- Modify: `native/tests/scenegraph/world_test.cc` (delete `RestPoseStoreAndRestore`, lines 132-155 — its semantics now live in `channel_binder_test.cc`)
- Modify: `native/tests/renderer/pose_sampler_test.cc` (delete tests for the two removed functions; keep `sample_pose` tests)

**Interfaces:**
- Consumes: Task 1/2's `bind_clip`, `clear_channels`, `set_rest_pose`, `eval_channels` — exact signatures from `renderer/channel_binder.h`.
- Produces: the six unchanged Python bindings (`set_instance_animation(iid, clip_index, loop=False, sample_at_start=False)`, `set_instance_rest_pose(iid, clip_index, at_start=False)`, `restore_rest_pose(iid)`, `play_instance_idle(iid, clip_index)`, `play_instance_gesture(iid, clip_index)`, `play_instance_walk(iid, clip_index)`) — now channel-table-backed. Task 5 edits only the `BindOptions` literals inside them.

- [ ] **Step 1: Rewrite `animation_update_test.cc` first (failing tests define the cutover)**

Replace the entire file body's test section (keep/adapt the fixture helpers `two_clip_layered_model`, `two_bone_model_with_clip`, `root_motion_model` verbatim — they are model-only and stay valid). The rewritten tests drive the NEW api:

```cpp
#include <gtest/gtest.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/epsilon.hpp>
#include <glm/gtx/quaternion.hpp>
#include <scenegraph/world.h>
#include <assets/model.h>
#include <renderer/animation_update.h>
#include <renderer/channel_binder.h>

// … (fixture helpers exactly as in the current file: two_clip_layered_model,
//    two_bone_model_with_clip, root_motion_model — copy them verbatim) …

TEST(AnimationUpdate, PlayOnceHoldRebuildsThenSettles) {
    assets::Model model = two_bone_model_with_clip();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };
    scenegraph::World world;
    auto id = world.create_instance(1);
    renderer::bind_clip(*world.get(id), model, 0, {}, /*now=*/100.0);

    renderer::update_animations(world, lookup, 100.5);
    EXPECT_TRUE(world.get(id)->anim.dirty);
    EXPECT_EQ(world.get(id)->bone_palette.size(), 2u);

    renderer::update_animations(world, lookup, 200.0);
    EXPECT_FALSE(world.get(id)->anim.dirty);
    auto settled_palette = world.get(id)->bone_palette;
    ASSERT_EQ(settled_palette.size(), 2u);

    // Content check — identical math to the historical test.
    glm::mat4 j1_local = glm::translate(glm::mat4(1.0f), glm::vec3(0, 10, 0));
    glm::quat q90 = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    glm::mat4 expect_skin =
        (j1_local * glm::mat4_cast(q90)) * glm::inverse(j1_local);
    glm::vec4 probe(3.0f, 4.0f, 0.0f, 1.0f);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        settled_palette[1] * probe, expect_skin * probe, 1e-4f)));

    // Settled ⇒ later frames rebuild nothing (palette bit-identical).
    renderer::update_animations(world, lookup, 300.0);
    for (std::size_t b = 0; b < settled_palette.size(); ++b)
        EXPECT_EQ(world.get(id)->bone_palette[b], settled_palette[b]);
}

TEST(AnimationUpdate, GestureBindLeavesOtherBonesOnTheirIdle) {
    // THE structural fix: a gesture binding one bone must not evict the
    // looping idle from the others. two_clip_layered_model: clip[0]=placement
    // (rest_locals station), clip[1]=gesture (j1 only).
    assets::Model model = two_clip_layered_model();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };
    scenegraph::World world;
    auto id = world.create_instance(1);
    scenegraph::Instance& inst = *world.get(id);

    renderer::set_rest_pose(inst, model, 0, /*at_start=*/false);
    renderer::BindOptions idle; idle.loop = true;
    renderer::bind_clip(inst, model, 1, idle, 0.0);      // j1 loops
    renderer::update_animations(world, lookup, 0.25);

    // Re-bind the same gesture one-shot at t=10 (simulates gesture over idle
    // on the SAME bone — last-bind-wins) and verify the root stayed at the
    // station throughout (it was never bound by either clip).
    renderer::bind_clip(inst, model, 1, {}, 10.0);
    renderer::update_animations(world, lookup, 10.5);
    glm::vec4 root_world = world.get(id)->bone_palette[0] * glm::vec4(0,0,0,1);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        glm::vec3(root_world), glm::vec3(33, -104, 23), 1e-3f)));
}

TEST(AnimationUpdate, LoopingIdleStaysAnchoredAndNeverSettles) {
    assets::Model model = two_clip_layered_model();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };
    scenegraph::World world;
    auto id = world.create_instance(1);
    scenegraph::Instance& inst = *world.get(id);
    renderer::set_rest_pose(inst, model, 0, false);
    renderer::BindOptions idle; idle.loop = true;
    renderer::bind_clip(inst, model, 1, idle, 0.0);

    auto root_world_at = [&](double now) {
        renderer::update_animations(world, lookup, now);
        return glm::vec3(world.get(id)->bone_palette[0] * glm::vec4(0,0,0,1));
    };
    glm::vec3 r1 = root_world_at(0.3);
    EXPECT_TRUE(world.get(id)->anim.dirty);
    glm::vec3 r2 = root_world_at(50.0);
    EXPECT_TRUE(world.get(id)->anim.dirty);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(r1, glm::vec3(33,-104,23), 1e-3f)));
    EXPECT_TRUE(glm::all(glm::epsilonEqual(r2, glm::vec3(33,-104,23), 1e-3f)));
}

TEST(AnimationUpdate, WalkBindAppliesRootMotionAndPlaysThrough) {
    assets::Model model = root_motion_model();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };
    scenegraph::World world;
    auto id = world.create_instance(1);
    renderer::BindOptions walk; walk.root_motion = true; walk.use_clip_base = true;
    renderer::bind_clip(*world.get(id), model, 0, walk, 100.0);

    auto root_x_at = [&](double now) {
        renderer::update_animations(world, lookup, now);
        return (world.get(id)->bone_palette[0] * glm::vec4(0, 0, 0, 1)).x;
    };
    EXPECT_NEAR(root_x_at(100.0), 0.0f, 1e-3f);
    EXPECT_TRUE(world.get(id)->anim.dirty);
    EXPECT_NEAR(root_x_at(100.5), 50.0f, 1e-3f);
    EXPECT_NEAR(root_x_at(200.0), 100.0f, 1e-3f);
    EXPECT_FALSE(world.get(id)->anim.dirty);
}

TEST(AnimationUpdate, RestPoseHoldsStartFrameWhenAtStart) {
    // Replaces SampleAtStartHoldsStartFrameAndSettles: at_start rest = t0 hold.
    assets::Model model = two_bone_model_with_clip();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };
    scenegraph::World world;
    auto id = world.create_instance(1);
    renderer::set_rest_pose(*world.get(id), model, 0, /*at_start=*/true);

    renderer::update_animations(world, lookup, 100.5);
    auto palette = world.get(id)->bone_palette;
    ASSERT_EQ(palette.size(), 2u);
    EXPECT_FALSE(world.get(id)->anim.dirty);

    // The single 90°-Z key is constant, so t=0 carries the rotation too.
    glm::mat4 j1_local = glm::translate(glm::mat4(1.0f), glm::vec3(0, 10, 0));
    glm::quat q90 = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    glm::mat4 expect_skin =
        (j1_local * glm::mat4_cast(q90)) * glm::inverse(j1_local);
    glm::vec4 probe(3.0f, 4.0f, 0.0f, 1.0f);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(
        palette[1] * probe, expect_skin * probe, 1e-4f)));

    renderer::update_animations(world, lookup, 500.0);
    for (std::size_t b = 0; b < palette.size(); ++b)
        EXPECT_EQ(world.get(id)->bone_palette[b], palette[b]);
}
```

(The historical `SampleAtEndHoldsEndFrameAndSettlesImmediately` is covered by `SetRestPose.SamplesOnceClearsChannelsAndSetsRest` + `RestPoseHoldsStartFrameWhenAtStart`'s freeze check; do not recreate it separately.)

- [ ] **Step 2: Rewrite `update_animations`**

Replace the body of `native/src/renderer/animation_update.cc`:

```cpp
#include "renderer/animation_update.h"
#include "renderer/bone_palette.h"
#include "renderer/channel_binder.h"
#include <assets/model.h>

namespace renderer {

void update_animations(scenegraph::World& world, const ModelLookup& lookup,
                       double now_wall_time) {
    world.for_each_alive([&](scenegraph::Instance& inst) {
        // Nothing bound and no rest pose ⇒ not a skeletal-animated instance.
        if (!inst.anim.dirty) return;                    // settled: skip
        if (inst.anim.channels.empty() && !inst.anim.has_rest) return;
        const assets::Model* m = lookup(inst.model_handle);
        if (!m || m->skeleton.bones.empty()) return;
        std::vector<glm::mat4> locals = eval_channels(inst, *m, now_wall_time);
        inst.bone_palette = build_bone_palette(m->skeleton, &locals);
    });
}

}  // namespace renderer
```

Update the doc comment in `animation_update.h` to match (per-bone channels; settled instances skipped via `anim.dirty`).

- [ ] **Step 3: Rewrite the six host bindings**

In `native/src/host/host_bindings.cc`, add `#include "renderer/channel_binder.h"` (with the other renderer includes) and replace the bodies at lines 1240-1338. Shared helper — place immediately before `m.def("set_instance_animation", …)`:

```cpp
    // Bind a clip onto an instance's channel table. Returns bones bound
    // (0 = dead clip on this skeleton — BC's silent no-op).
    auto bind_instance_clip = [](scenegraph::InstanceId id, int clip_index,
                                 const renderer::BindOptions& opts) -> int {
        scenegraph::Instance* in = g_world.get(id);
        if (!in) return 0;
        const assets::Model* m = resolve_model(in->model_handle);
        if (!m) return 0;
        return renderer::bind_clip(*in, *m, clip_index, opts, glfwGetTime());
    };
```

The six bindings (docstrings updated to the channel semantics; `py::arg` lists unchanged):

```cpp
    m.def("set_instance_animation",
          [bind_instance_clip](scenegraph::InstanceId id, int clip_index,
                               bool loop, bool sample_at_start) {
              renderer::BindOptions o;
              o.loop = loop;
              o.root_motion = true;
              o.use_clip_base = true;
              o.hold_at_start = sample_at_start;
              bind_instance_clip(id, clip_index, o);
          },
          py::arg("iid"), py::arg("clip_index"), py::arg("loop") = false,
          py::arg("sample_at_start") = false,
          "SP2: bind model.animations[clip_index]'s name-matched tracks onto "
          "this instance's bone channels (full clip: root motion applied, "
          "omitted channels fall back to the clip's own rest pose). loop=false "
          "plays once and holds; sample_at_start holds frame 0.");

    m.def("set_instance_rest_pose",
          [](scenegraph::InstanceId id, int clip_index, bool at_start) {
              scenegraph::Instance* in = g_world.get(id);
              if (!in) return;
              const assets::Model* m = resolve_model(in->model_handle);
              if (!m) return;
              renderer::set_rest_pose(*in, *m, clip_index, at_start);
          },
          py::arg("iid"), py::arg("clip_index"), py::arg("at_start") = false,
          "Freeze the officer's placement pose: sample the clip once "
          "(at_start=true → first frame, else last) into the per-bone rest "
          "locals and unbind every channel. Snap — no blend (BC positioning).");

    m.def("restore_rest_pose",
          [](scenegraph::InstanceId id) {
              scenegraph::Instance* in = g_world.get(id);
              if (!in || !in->anim.has_rest) return;
              renderer::clear_channels(*in);
          },
          py::arg("iid"),
          "Snap the instance back to its stored rest pose (AT_DEFAULT): "
          "unbind every channel; bones fall back to the placement locals.");

    m.def("play_instance_idle",
          [bind_instance_clip](scenegraph::InstanceId id, int clip_index) {
              renderer::BindOptions o;
              o.loop = true;
              bind_instance_clip(id, clip_index, o);
          },
          py::arg("iid"), py::arg("clip_index"),
          "Loop an idle (e.g. breathing) on the clip's name-matched bones; "
          "every other bone keeps its current channel or rest local. Loops "
          "until a later bind takes its bones (per-bone last-bind-wins).");

    m.def("play_instance_gesture",
          [bind_instance_clip](scenegraph::InstanceId id, int clip_index) {
              bind_instance_clip(id, clip_index, {});
          },
          py::arg("iid"), py::arg("clip_index"),
          "Play a transient gesture on the clip's name-matched bones only: "
          "those bones clamp+hold at the last frame until the next bind; all "
          "other bones keep running their idle (BC's non-exclusive layering). "
          "A clip matching zero bones binds nothing — BC's exact-strcmp "
          "channel join makes dead clips silent no-ops by construction.");

    m.def("play_instance_walk",
          [bind_instance_clip](scenegraph::InstanceId id, int clip_index) {
              renderer::BindOptions o;
              o.root_motion = true;
              o.use_clip_base = true;
              bind_instance_clip(id, clip_index, o);
          },
          py::arg("iid"), py::arg("clip_index"),
          "Play a walk clip WITH ROOT MOTION: the baked Bip01 root translation "
          "moves the character across the set. Plays once and settles at the "
          "last frame. Bones the clip does not track keep their channels "
          "(BC walk-ons are non-exclusive).");
```

- [ ] **Step 4: Delete the modal system**

- `instance.h`: delete `struct AnimationState`, the `animation`, `rest_pose`, `has_rest_pose` members (keep `BoneChannel`/`SkeletalAnim`/`anim` from Task 1).
- `world.h`/`world.cc`: delete `set_animation`, `set_rest_pose`, `restore_rest_pose` (declarations + definitions, `world.cc:49-68`).
- `pose_sampler.h`/`pose_sampler.cc`: delete `sample_pose_over_base` and `clip_drives_skeleton` (declarations, definitions, and the now-unused parts of the header comment). Keep `sample_pose` and the anonymous-namespace `pose_bone` (still used by `sample_pose`).
- `world_test.cc`: delete `TEST(World, RestPoseStoreAndRestore)` (lines 132-155).
- `pose_sampler_test.cc`: delete the `sample_pose_over_base` / `clip_drives_skeleton` tests (added in 3c3b25cc / earlier); keep all `sample_pose` tests.

- [ ] **Step 5: Build; fix every remaining compile error by migrating the call site**

```bash
cmake --build build -j 2>&1 | grep -E "error|Error" | head -20
```
Any compile error here is a consumer the plan missed — migrate it onto `bind_clip`/`set_rest_pose`/`clear_channels` following the six-binding mapping above (do NOT re-add `AnimationState`). Expected consumers: none beyond the files listed.

- [ ] **Step 6: Run both suites (the gate)**

```bash
scripts/check_tests.sh
```
Expected: exit 0, `0 known failure(s) still baselined`. pytest covers the Python surface (`tests/unit/test_bridge_character_anim.py`, `tests/unit/test_bridge_idle_gestures.py`, walk/placement suites) against the unchanged binding signatures.

- [ ] **Step 7: Commit (landing commit 1 — structural swap at blend = 0)**

```bash
git add native/src/renderer/animation_update.cc \
        native/src/renderer/include/renderer/animation_update.h \
        native/src/host/host_bindings.cc \
        native/src/scenegraph/include/scenegraph/instance.h \
        native/src/scenegraph/include/scenegraph/world.h \
        native/src/scenegraph/src/world.cc \
        native/src/renderer/include/renderer/pose_sampler.h \
        native/src/renderer/pose_sampler.cc \
        native/tests/renderer/animation_update_test.cc \
        native/tests/renderer/pose_sampler_test.cc \
        native/tests/scenegraph/world_test.cc
git commit -m "feat(renderer)!: officer animation cutover to per-bone channel binder (blend off)

Replaces the modal per-instance AnimationState with BC's per-node machine:
exact-strcmp bind, per-bone last-bind-wins, unmatched bones untouched.
Deletes the dead-clip gate (emergent: zero-match clips bind nothing) and
sample_pose_over_base/clip_drives_skeleton. Python surface unchanged.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Real-asset oracles (welded skeleton, shipped clips, walk reference)

**Files:**
- Create: `native/tests/renderer/channel_binder_assets_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt` (add it after `channel_binder_test.cc`)

**Interfaces:**
- Consumes: `assets::compose_officer_model(body_nif, body_tex, head_nif, head_tex, attach_bone)` (see `head_weld_seam_test.cc:160-165` for the exact pattern, including the GL-window/asset skip guards — copy that fixture's skip logic verbatim), `assets::load_animation_clips(path)`, `renderer::sample_pose`, Task 1/2 binder API.
- Produces: nothing later tasks call — this is the verification net.

**Spec §7 ordering note ("walk oracle recorded against the CURRENT system before the rebuild"):** the oracle's reference is `renderer::sample_pose`, which the cutover does not touch — so "current-system output" and "post-cutover reference" are the same function, and recording order cannot change the verdict. The pre-cutover pinning the spec wants is additionally provided by Task 2's `EvalChannels.RootMotionAppliesTranslationAnchorOtherwise` (written and passing before Task 3 swaps anything) plus the historical walk test kept green until the Task 3 rewrite.

- [ ] **Step 1: Write the oracle tests**

Create `native/tests/renderer/channel_binder_assets_test.cc`. Fixture: compose `game/data/Models/Characters/Bodies/BodyFemM/BodyFemM.NIF` + `game/data/Models/Characters/Heads/HeadKiska/kiska_head.NIF` with attach bone `"Bip01 Head"` (same `kRoot`/`kChars` path constants and `GTEST_SKIP` guards as `head_weld_seam_test.cc`: skip when `game/` assets are absent or GL window creation fails). Load clips from `game/data/Animations/`:

```cpp
// Real-asset oracles for the per-channel binder, from the 2026-07-15
// investigation:
//  1. tilt_head_left.NIF ("Bip01 Head" track) on the welded BodyFemM +
//     kiska_head skeleton moves the head palette row while every body row
//     continues its breathing loop UNINTERRUPTED across the gesture bind.
//  2. Console_Look_Down.NIF ("Kiska …"-rigged) is dead ballast: every palette
//     row stays bit-identical (BC renders nothing for it either).
//  3. Walk reference: for every TRACKED bone, channel eval reproduces
//     sample_pose(clip, skeleton, t) — the unchanged sampler is the oracle,
//     so the cutover provably preserves today's walk output.
```

The three tests (complete code):

```cpp
TEST_F(ChannelBinderAssets, TiltHeadMovesHeadWhileBodyBreathesUninterrupted) {
    int breathe = load_clip("breathing.NIF");        // helper: appends to
    int tilt    = load_clip("tilt_head_left.NIF");   // model_.animations,
    ASSERT_GE(breathe, 0); ASSERT_GE(tilt, 0);       // returns index or -1

    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);
    renderer::BindOptions idle; idle.loop = true;
    ASSERT_GT(renderer::bind_clip(inst, model_, breathe, idle, 0.0), 0);

    const int head = bone_index("Bip01 Head");
    ASSERT_GE(head, 0);
    // Bones the tilt clip will bind (by the same strcmp rule).
    std::set<int> tilt_bones;
    for (const auto& tr : model_.animations[tilt].tracks) {
        int b = bone_index(tr.target_node_name);
        if (b >= 0) tilt_bones.insert(b);
    }
    ASSERT_TRUE(tilt_bones.count(head)) << "tilt must drive the head";

    // Record breathe-only palettes over a window, then re-play the SAME window
    // with the gesture bound mid-way, and compare non-tilt rows frame by
    // frame: they must be bit-identical (same clip, same phase, untouched
    // channels) — the eviction bug would desynchronize or freeze them.
    auto lookup = [&](scenegraph::ModelHandle){ return &model_; };
    std::vector<std::vector<glm::mat4>> baseline;
    for (double t = 0.0; t < 2.0; t += 0.1) {
        renderer::update_animations(w, lookup, t);
        baseline.push_back(inst.bone_palette);
    }
    // Reset to the same idle phase and replay with a gesture bind at t=1.0.
    renderer::clear_channels(inst);
    renderer::bind_clip(inst, model_, breathe, idle, 0.0);
    bool head_moved = false;
    std::size_t frame = 0;
    for (double t = 0.0; t < 2.0; t += 0.1, ++frame) {
        if (t >= 1.0 - 1e-9 && t < 1.1 - 1e-9)
            ASSERT_GT(renderer::bind_clip(inst, model_, tilt, {}, t), 0);
        renderer::update_animations(w, lookup, t);
        for (std::size_t b = 0; b < inst.bone_palette.size(); ++b) {
            if (tilt_bones.count(static_cast<int>(b))) {
                if (t >= 1.0 && inst.bone_palette[b] != baseline[frame][b])
                    head_moved = true;
            } else {
                EXPECT_EQ(inst.bone_palette[b], baseline[frame][b])
                    << "non-gesture bone " << b << " disturbed at t=" << t;
            }
        }
    }
    EXPECT_TRUE(head_moved) << "tilt gesture produced no head motion";
}

TEST_F(ChannelBinderAssets, KiskaRiggedClipIsBitIdenticalNoOp) {
    int breathe = load_clip("breathing.NIF");
    int dead    = load_clip("Console_Look_Down.NIF");
    ASSERT_GE(breathe, 0); ASSERT_GE(dead, 0);

    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);
    renderer::BindOptions idle; idle.loop = true;
    renderer::bind_clip(inst, model_, breathe, idle, 0.0);
    auto lookup = [&](scenegraph::ModelHandle){ return &model_; };

    renderer::update_animations(w, lookup, 0.5);
    // Oracle precondition from the investigation: the clip's tracks are all
    // "Kiska …"-named — none matches a "Bip01 …" bone.
    EXPECT_EQ(renderer::bind_clip(inst, model_, dead, {}, 0.5), 0);
    auto before = inst.bone_palette;
    renderer::update_animations(w, lookup, 0.5);   // same instant: same phase
    ASSERT_EQ(inst.bone_palette.size(), before.size());
    for (std::size_t b = 0; b < before.size(); ++b)
        EXPECT_EQ(inst.bone_palette[b], before[b]);
}

TEST_F(ChannelBinderAssets, WalkChannelsReproduceSamplePoseOnTrackedBones) {
    // Any shipped placement/walk clip with a "Bip01" root translation works;
    // db_LtoH walk-family clips live in game/data/Animations. Use
    // tilt_head_left as the tracked-bone reference too — the invariant is
    // channels == sample_pose for TRACKED bones at matching t, for a
    // root-motion, clip-base bind (the walk configuration).
    int walk = load_clip("tilt_head_left.NIF");
    ASSERT_GE(walk, 0);
    const assets::AnimationClip& clip = model_.animations[walk];

    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);
    renderer::BindOptions o; o.root_motion = true; o.use_clip_base = true;
    ASSERT_GT(renderer::bind_clip(inst, model_, walk, o, 0.0), 0);

    for (float t : {0.0f, clip.duration_seconds * 0.5f, clip.duration_seconds}) {
        auto ref = renderer::sample_pose(clip, model_.skeleton, t);
        auto got = renderer::eval_channels(inst, model_, t);
        for (const auto& tr : clip.tracks) {
            int b = bone_index(tr.target_node_name);
            if (b < 0) continue;
            for (int c = 0; c < 4; ++c)
                EXPECT_TRUE(glm::all(glm::epsilonEqual(
                    got[b][c], ref[b][c], 1e-4f)))
                    << "bone " << b << " t=" << t << " col " << c;
        }
    }
}
```

Fixture helpers to implement in the file: `load_clip(name)` (calls `assets::load_animation_clips(kRoot / "game/data/Animations" / name)`, appends `clips[0]` to a mutable copy `model_.animations`, returns its index, `-1` if empty) and `bone_index(name)` (linear scan of `model_.skeleton.bones`). Includes: `<set>`, the Task 1 header, `renderer/animation_update.h`, `renderer/pose_sampler.h`, plus the compose/window includes copied from `head_weld_seam_test.cc`.

- [ ] **Step 2: Register, build, run**

```bash
cmake --build build -j && ctest --test-dir build --output-on-failure -R ChannelBinderAssets
```
Expected: 3 PASS (or 3 SKIP on a machine without `game/` assets / GL — this worktree has both, so PASS).

- [ ] **Step 3: Run the full gate, then commit**

```bash
scripts/check_tests.sh
git add native/tests/renderer/channel_binder_assets_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "test(renderer): real-asset oracles — breathe continuity, dead-clip no-op, walk reference

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Blend-on (landing commit 2) + dev-gated feel dials

**Files:**
- Modify: `native/src/host/host_bindings.cc` (flip `blend=true` in the three play bindings; add `anim_blend_set`)
- Test: `native/tests/renderer/channel_binder_test.cc` (append params test)
- Modify: `engine/renderer.py` (docstring touch ONLY if pyright/pytest complains — otherwise untouched)

**Interfaces:**
- Consumes: Task 1's `BlendParams`/`set_blend_params`/`blend_params`; `dauntless::is_developer_mode()` from `native/src/host/developer_mode.h` (already included in `host_bindings.cc`).
- Produces: `anim_blend_set(cap_s=0.34, short_factor=0.75, curve=0)` host binding (dev-gated).

- [ ] **Step 1: Append the failing params test**

```cpp
TEST(BlendParams, SetParamsDrivesFormulaAndCurve) {
    auto saved = renderer::blend_params();
    renderer::set_blend_params({/*cap_s=*/0.5f, /*short_factor=*/0.5f, /*curve=*/1});
    EXPECT_NEAR(renderer::blend_in_seconds(1.0f), 0.5f, 1e-6f);
    EXPECT_NEAR(renderer::blend_in_seconds(0.2f), 0.1f, 1e-6f);
    renderer::set_blend_params(saved);   // don't leak into other tests
    EXPECT_NEAR(renderer::blend_in_seconds(1.0f), 0.34f, 1e-6f);
}
```

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure -R BlendParams` — expected: PASS already (Task 1 implemented the params; this pins them). If it fails, the Task 1 implementation drifted — fix `channel_binder.cc`, not the test.

- [ ] **Step 2: Flip the three play bindings to blend and add the dial binding**

In `host_bindings.cc`: in `play_instance_idle`, `play_instance_gesture`, `play_instance_walk` set `o.blend = true;` (for the gesture binding, replace the default-constructed `{}` with an explicit `renderer::BindOptions o; o.blend = true;`). `set_instance_animation`, `set_instance_rest_pose`, `restore_rest_pose` stay snap. Then add, next to the other dev-facing defs:

```cpp
    m.def("anim_blend_set",
          [](float cap_s, float short_factor, int curve) {
              if (!dauntless::is_developer_mode()) return;
              renderer::set_blend_params({cap_s, short_factor, curve});
          },
          py::arg("cap_s") = 0.34f, py::arg("short_factor") = 0.75f,
          py::arg("curve") = 0,
          "DEV ONLY (--developer; no-op otherwise): live-tune the animation "
          "blend-in dials. BC defaults: cap 0.34 s, short-clip factor 0.75, "
          "curve 0 = linear (1 = smoothstep). anim_blend_set(0, 0, 0) disables "
          "blending entirely for A/B against the structural swap.");
```

- [ ] **Step 3: Full gate**

```bash
scripts/check_tests.sh
```
Expected: exit 0. The Task 4 continuity oracle must still pass — blend-in only affects REBOUND bones inside their window; untouched bones' channels carry `blend_in_s` from their own bind and identical phase, so baseline-vs-replay rows stay bit-identical.

- [ ] **Step 4: Commit (landing commit 2)**

```bash
git add native/src/host/host_bindings.cc native/tests/renderer/channel_binder_test.cc
git commit -m "feat(renderer): BC blend-in on (0.34s / 0.75×dur) + dev-gated anim_blend_set dials

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Debug readbacks (temporary live-verification instruments) + final gate

**Files:**
- Modify: `native/src/host/host_bindings.cc` (two readbacks + make `InstanceId` default-constructible from Python)
- Test: `tests/unit/test_anim_debug_readbacks.py` (create)

**Interfaces:**
- Consumes: `g_world`, `resolve_model`, `dauntless::is_developer_mode()`; pytest reaches `_dauntless_host` the way `tests/audio/test_alert_audio.py:6` does (`pytest.importorskip("_dauntless_host")`).
- Produces: `debug_instance_anim(iid) -> list[dict]`, `debug_bone_palette_row(iid, bone_name) -> list[float] | None`. These are the live acceptance instruments (spec §7): run `./build/dauntless --developer` from the MAIN tree later and grep stdout during a LookDown chain — body rows keep oscillating, head row plays the look.

- [ ] **Step 1: Write the failing pytest**

Create `tests/unit/test_anim_debug_readbacks.py`:

```python
"""Dev readbacks for the channel binder exist and return the documented shape.
They are dev-mode-gated at the point of USE in the live game; the bindings
themselves return data whenever called (they are read-only introspection)."""
import pytest

_h = pytest.importorskip("_dauntless_host")


def test_debug_readbacks_exist_and_handle_bad_ids():
    assert hasattr(_h, "debug_instance_anim")
    assert hasattr(_h, "debug_bone_palette_row")
    bad = _h.InstanceId()          # default id: never alive
    assert _h.debug_instance_anim(bad) == []
    assert _h.debug_bone_palette_row(bad, "Bip01 Head") is None
```

Run: `uv run --no-sync pytest tests/unit/test_anim_debug_readbacks.py -q` — expected: FAIL (`AttributeError`-shaped assert on `hasattr`).

- [ ] **Step 2: Implement the readbacks**

First, in `host_bindings.cc:1157`, make `InstanceId` constructible from Python (the test's "never-alive id"; `{0,0}` never matches a live instance because generations start at 1):

```cpp
    py::class_<scenegraph::InstanceId>(m, "InstanceId")
        .def(py::init<>())
        .def_readonly("index", &scenegraph::InstanceId::index)
        .def_readonly("generation", &scenegraph::InstanceId::generation);
```

(If `world.cc`'s generation seeding turns out to start at 0, have the test obtain its bad id as the value-mutated copy of a real one instead — check `World::create_instance` while there.) Then add, next to `anim_blend_set`:

```cpp
    m.def("debug_instance_anim",
          [](scenegraph::InstanceId id) {
              py::list out;
              scenegraph::Instance* in = g_world.get(id);
              if (!in) return out;
              const assets::Model* m = resolve_model(in->model_handle);
              for (std::size_t i = 0; i < in->anim.channels.size(); ++i) {
                  const auto& ch = in->anim.channels[i];
                  if (ch.clip_index < 0) continue;
                  py::dict d;
                  d["bone"] = (m && i < m->skeleton.bones.size())
                                  ? m->skeleton.bones[i].name
                                  : std::to_string(i);
                  d["clip"] = ch.clip_index;
                  d["start"] = ch.start_wall_time;
                  d["loop"] = ch.loop;
                  d["settled"] = ch.settled;
                  d["blend_in_s"] = ch.blend_in_s;
                  out.append(d);
              }
              return out;
          },
          py::arg("iid"),
          "DEV: list this instance's BOUND bone channels "
          "[{bone, clip, start, loop, settled, blend_in_s}]. Empty for a bad "
          "id or an instance with no bound channels.");

    m.def("debug_bone_palette_row",
          [](scenegraph::InstanceId id, const std::string& bone_name)
              -> py::object {
              scenegraph::Instance* in = g_world.get(id);
              if (!in) return py::none();
              const assets::Model* m = resolve_model(in->model_handle);
              if (!m) return py::none();
              for (std::size_t i = 0; i < m->skeleton.bones.size(); ++i) {
                  if (m->skeleton.bones[i].name != bone_name) continue;
                  if (i >= in->bone_palette.size()) return py::none();
                  const glm::mat4& p = in->bone_palette[i];
                  py::list row;
                  for (int c = 0; c < 4; ++c)
                      for (int r = 0; r < 4; ++r) row.append(p[c][r]);
                  return row;
              }
              return py::none();
          },
          py::arg("iid"), py::arg("bone_name"),
          "DEV: the named bone's current 4x4 palette matrix as 16 floats "
          "(column-major), or None if the id/bone/palette is missing. Live "
          "oracle: grep stdout while printing this per frame — body bones "
          "keep oscillating through a gesture, the gesture bone plays it.");
```

- [ ] **Step 3: Build, run the pytest, then the full gate**

```bash
cmake --build build -j
uv run --no-sync pytest tests/unit/test_anim_debug_readbacks.py -q   # expected: 1 passed
scripts/check_tests.sh                                                # expected: exit 0
```

- [ ] **Step 4: Commit**

```bash
git add native/src/host/host_bindings.cc tests/unit/test_anim_debug_readbacks.py
git commit -m "feat(host): debug_instance_anim + debug_bone_palette_row readbacks for live anim verification

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## After the plan (NOT tasks — session-level follow-ups)

1. Hand the branch to Mark: rename off the worktree prefix (`git branch -m worktree-anim-channel-binder feat/anim-channel-binder`), then Mark checks it out in the MAIN tree, rebuilds, and runs `./build/dauntless --developer` for the live pass: smooth idles, no pops at gesture start/end, LookDown chain with continuous breathing (verify numerically via the Task 6 readbacks), E1M1 walk-on spine intact, feel dials via `anim_blend_set`.
2. The debug readbacks are temporary instruments — remove or keep by Mark's call after live verification.
