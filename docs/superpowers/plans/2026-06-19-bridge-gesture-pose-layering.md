# Bridge Gesture Pose-Layering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Play idle-gesture / hit-reaction clips *layered over* an officer's placement pose, so gesture-tracked bones override while the root and un-animated bones stay at the station — fixing officers T-posing in the bridge centre when a gesture fires.

**Architecture:** Officers are positioned solely by the root-bone (Bip01) translation baked into their placement clip (`OFFICER_TRANSFORM` is identity). Gesture/reaction NIFs are partial, root-less overlays (~31 of 41 bones, no Bip01 translation), authored to be blended onto the standing pose. Playing them standalone makes un-tracked bones fall to bind (T-pose) and the root fall to origin (bridge centre). Fix: a layered sampler that uses the placement pose's per-bone local transforms as the base for the gesture sample.

**Tech Stack:** C++ (renderer/scenegraph, GoogleTest/ctest), pybind11, Python (`engine/`, pytest), GLM.

## Global Constraints

- One build tree at `<root>/build/`; `cmake --build build -j` after any `native/` edit; host_bindings.cc edits rebuild both `build/dauntless` and the `_dauntless_host` module. Never cmake inside `native/`.
- Host module imports as `_dauntless_host`, wrapped by `engine/renderer.py` as `_h`.
- `sample_pose(clip, skeleton, t)` returns per-bone LOCAL transforms (indexed by `skeleton.bones`), using `clip.rest_locals[bone.name]` (else `bone.local_transform`) as the per-bone base and `assets::sample_track_trs` for tracked bones. `build_bone_palette(skeleton, &local_pose)` turns local transforms into the skinning palette.
- TDD: failing test first. C++ tests via `ctest --test-dir build`; Python via `uv run pytest`.
- The placement rest pose is frame 0 (`sample_at_start=True`) for every officer (fixed 2026-06-19).
- Do NOT launch the GUI (the user verifies the visual).

---

### Task 1: Native layered pose sampler + update_animations layering + binding

**Files:**
- Modify: `native/src/renderer/include/renderer/pose_sampler.h` (declare `sample_pose_over_base`)
- Modify: `native/src/renderer/pose_sampler.cc` (implement; share per-bone logic with `sample_pose`)
- Modify: `native/src/scenegraph/include/scenegraph/instance.h` (`AnimationState.layer_over_rest`)
- Modify: `native/src/renderer/animation_update.cc` (layered branch)
- Modify: `native/src/host/host_bindings.cc` (`play_instance_gesture` binding)
- Modify: `engine/renderer.py` (wrapper)
- Test: `native/tests/renderer/pose_sampler_test.cc` (layered sampler)
- Test: `native/tests/renderer/animation_update_test.cc` (layer_over_rest path)

**Interfaces:**
- Produces (C++): `std::vector<glm::mat4> renderer::sample_pose_over_base(const assets::AnimationClip& clip, const assets::Skeleton& skeleton, float t, const std::vector<glm::mat4>& base_locals);` — for each bone: if `clip` has a track for `bone.name`, sample it with that bone's base taken from `base_locals[i]` (decomposed to T/R/S); otherwise `out[i] = base_locals[i]`.
- Produces (C++): `AnimationState.layer_over_rest` (bool, default false).
- Produces (Python): `renderer.play_instance_gesture(iid, clip_index)`.

- [ ] **Step 1: Write the failing pose_sampler test**

Add to `native/tests/renderer/pose_sampler_test.cc` (reuse/define a 2-bone skeleton: root `Bip01` + child `j1`). The gesture clip animates ONLY `j1` (rotation), has NO `Bip01` track, and its own `rest_locals` would put `Bip01` at the origin. `base_locals` places `Bip01` at a station offset. Assert the layered result keeps `Bip01` at the station offset (NOT origin) and applies the gesture rotation to `j1`:

```cpp
TEST(SamplePoseOverBase, RootStaysAtBaseWhenGestureHasNoRootTrack) {
    assets::Skeleton sk;
    assets::Bone b0; b0.name = "Bip01"; b0.parent_index = -1;
    b0.local_transform = glm::mat4(1.0f);
    assets::Bone b1; b1.name = "j1"; b1.parent_index = 0;
    b1.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0,5,0));
    sk.bones = {b0, b1}; sk.root_bone_index = 0;

    // Gesture: only j1 has a rotation track; NO Bip01 track. Its own rest_locals
    // would drop Bip01 to identity/origin — the bug we are layering away from.
    assets::AnimationClip g; g.name = "g"; g.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack tj; tj.target_node_name = "j1";
    glm::quat q = glm::angleAxis(glm::radians(90.0f), glm::vec3(0,0,1));
    tj.rotation = {{0.0f, q}, {1.0f, q}};
    g.tracks = {tj};
    g.rest_locals["Bip01"] = glm::mat4(1.0f);          // origin — must be ignored
    g.rest_locals["j1"]    = b1.local_transform;

    // base_locals = the placement pose: Bip01 translated to a "station".
    std::vector<glm::mat4> base(2);
    base[0] = glm::translate(glm::mat4(1.0f), glm::vec3(33, -104, 23)); // station root
    base[1] = b1.local_transform;

    auto out = renderer::sample_pose_over_base(g, sk, 0.5f, base);
    ASSERT_EQ(out.size(), 2u);
    // Root keeps the station translation from base_locals, NOT the clip rest origin.
    EXPECT_TRUE(glm::all(glm::epsilonEqual(glm::vec3(out[0][3]),
                                           glm::vec3(33, -104, 23), 1e-4f)));
    // j1 got the gesture's 90deg-Z rotation (its column 0 rotated toward +Y).
    glm::vec3 col0 = glm::normalize(glm::vec3(out[1][0]));
    EXPECT_NEAR(col0.y, 1.0f, 1e-3f);
}

TEST(SamplePoseOverBase, UntrackedBoneTakesBaseExactly) {
    assets::Skeleton sk;
    assets::Bone b0; b0.name = "Bip01"; b0.parent_index = -1; b0.local_transform = glm::mat4(1.0f);
    assets::Bone b1; b1.name = "j1"; b1.parent_index = 0; b1.local_transform = glm::mat4(1.0f);
    sk.bones = {b0, b1}; sk.root_bone_index = 0;
    assets::AnimationClip g; g.name = "g"; g.duration_seconds = 1.0f;  // no tracks at all
    std::vector<glm::mat4> base(2);
    base[0] = glm::translate(glm::mat4(1.0f), glm::vec3(1,2,3));
    base[1] = glm::translate(glm::mat4(1.0f), glm::vec3(4,5,6));
    auto out = renderer::sample_pose_over_base(g, sk, 0.0f, base);
    EXPECT_EQ(out[0], base[0]);
    EXPECT_EQ(out[1], base[1]);
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure -R SamplePoseOverBase`
Expected: FAIL — `sample_pose_over_base` undeclared (compile error).

- [ ] **Step 3: Declare `sample_pose_over_base`**

In `native/src/renderer/include/renderer/pose_sampler.h`, after `sample_pose`:

```cpp
/// Layered sample: like sample_pose, but each bone's BASE comes from
/// `base_locals` (per-bone local transforms, same order as skeleton.bones)
/// instead of the clip's own rest_locals/bind. Bones the clip does NOT track
/// are copied verbatim from base_locals; tracked bones sample their track over
/// the decomposed base_locals value (so an omitted channel — e.g. the root
/// translation gestures never carry — falls back to base_locals, keeping the
/// officer anchored at the placement pose). base_locals.size() must equal
/// skeleton.bones.size().
std::vector<glm::mat4> sample_pose_over_base(
    const assets::AnimationClip& clip, const assets::Skeleton& skeleton,
    float t, const std::vector<glm::mat4>& base_locals);
```

- [ ] **Step 4: Implement, sharing per-bone logic with `sample_pose`**

In `native/src/renderer/pose_sampler.cc`, extract the per-bone "decompose base + sample-or-copy" into a file-local helper and use it from BOTH `sample_pose` and `sample_pose_over_base` (do NOT duplicate the decompose/sample block verbatim):

```cpp
namespace {
// Pose one bone: if `track` is null, return `base`; else sample the track with
// each omitted channel falling back to base's T/R/S.
glm::mat4 pose_bone(const assets::AnimationClip::NodeTrack* track,
                    const glm::mat4& base, float t) {
    if (!track) return base;
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
    return assets::sample_track_trs(*track, t, base_t, base_r, base_s);
}
}  // namespace
```

Refactor `sample_pose` to compute `base` (its existing rest_locals/bind choice) then `out[i] = pose_bone(track_or_null, base, t);`. Add:

```cpp
std::vector<glm::mat4> sample_pose_over_base(
    const assets::AnimationClip& clip, const assets::Skeleton& skeleton,
    float t, const std::vector<glm::mat4>& base_locals) {
    t = std::clamp(t, 0.0f, clip.duration_seconds);
    std::unordered_map<std::string, const assets::AnimationClip::NodeTrack*> by_name;
    for (const auto& tr : clip.tracks) by_name[tr.target_node_name] = &tr;

    std::vector<glm::mat4> out(skeleton.bones.size());
    for (std::size_t i = 0; i < skeleton.bones.size(); ++i) {
        const glm::mat4 base =
            i < base_locals.size() ? base_locals[i] : skeleton.bones[i].local_transform;
        auto it = by_name.find(skeleton.bones[i].name);
        out[i] = pose_bone(it == by_name.end() ? nullptr : it->second, base, t);
    }
    return out;
}
```

- [ ] **Step 5: Run pose_sampler tests (and the existing ones) to verify pass**

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure -R "SamplePose|PoseSampler"`
Expected: PASS (new `SamplePoseOverBase.*` and all pre-existing pose-sampler tests — the `sample_pose` refactor must not regress them).

- [ ] **Step 6: Add `layer_over_rest` to AnimationState**

In `native/src/scenegraph/include/scenegraph/instance.h`, inside `AnimationState` (after `sample_at_end`):

```cpp
        bool   layer_over_rest = false;  // gesture: sample OVER the rest pose
```

- [ ] **Step 7: Write the failing update_animations layering test**

Add to `native/tests/renderer/animation_update_test.cc` a model with a skeleton, a placement clip (root `Bip01` translated to a station, settles at frame 0) stored as `rest_pose`, and a gesture clip (animates `j1` only, no root track) played with `layer_over_rest=true`. Assert the resulting `bone_palette` keeps the root at the station (compare a probe point) rather than the origin. (Build a model with `m.skeleton`, `m.animations = {placement, gesture}`; set `world.set_rest_pose(id, rest_state{clip_index=0, sample_at_start=true})`; then `set_animation(id, {clip_index=1, layer_over_rest=true})`; call `update_animations`; verify the root bone's palette reflects the station translation, not origin.) Mirror the existing animation_update test style for palette probing.

- [ ] **Step 8: Run to verify it fails**

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure -R AnimationUpdate`
Expected: FAIL — `layer_over_rest` not honored yet (root collapses to gesture base / origin).

- [ ] **Step 9: Implement the layered branch in update_animations**

In `native/src/renderer/animation_update.cc`, after `t` is computed and before the existing `sample_pose` call, replace the single `sample_pose` line with:

```cpp
        std::vector<glm::mat4> pose;
        if (a.layer_over_rest && inst.has_rest_pose &&
            inst.rest_pose.clip_index >= 0 &&
            inst.rest_pose.clip_index < static_cast<int>(m->animations.size())) {
            const assets::AnimationClip& rest_clip =
                m->animations[inst.rest_pose.clip_index];
            const float rest_t =
                inst.rest_pose.sample_at_end ? rest_clip.duration_seconds : 0.0f;
            std::vector<glm::mat4> base_locals =
                sample_pose(rest_clip, m->skeleton, rest_t);
            pose = sample_pose_over_base(clip, m->skeleton, t, base_locals);
        } else {
            pose = sample_pose(clip, m->skeleton, t);
        }
        inst.bone_palette = build_bone_palette(m->skeleton, &pose);
```

(Keep the existing `settled`/`t` logic unchanged; only the sampling is layered.)

- [ ] **Step 10: Run update_animations tests to verify pass**

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure -R AnimationUpdate`
Expected: PASS (new layering test + all pre-existing AnimationUpdate tests).

- [ ] **Step 11: Add the `play_instance_gesture` binding**

In `native/src/host/host_bindings.cc`, after `set_instance_rest_pose`/`restore_rest_pose`:

```cpp
    m.def("play_instance_gesture",
          [](scenegraph::InstanceId id, int clip_index) {
              scenegraph::Instance::AnimationState st;
              st.clip_index = clip_index;
              st.loop = false;
              st.layer_over_rest = true;
              st.start_wall_time = glfwGetTime();
              g_world.set_animation(id, st);
          },
          py::arg("iid"), py::arg("clip_index"),
          "Play a transient gesture/reaction clip LAYERED over the instance's "
          "rest pose: gesture-tracked bones override, the root and untracked "
          "bones stay at the placement pose. Plays once and holds the last "
          "frame until restore_rest_pose.");
```

- [ ] **Step 12: Add the Python wrapper**

In `engine/renderer.py`, after `restore_rest_pose`:

```python
def play_instance_gesture(iid: InstanceId, clip_index: int) -> None:
    """Play a transient gesture/reaction clip layered over the officer's rest
    pose (root + un-animated bones stay at the station; only gesture-tracked
    bones move). Plays once and holds the last frame until restore_rest_pose."""
    _h.play_instance_gesture(iid, clip_index)
```

- [ ] **Step 13: Rebuild and confirm the binding is importable**

Run: `cmake --build build -j && uv run python -c "import _dauntless_host as h; print(hasattr(h,'play_instance_gesture'))"`
Expected: `True`.

- [ ] **Step 14: Commit**

```bash
git add native/src engine/renderer.py native/tests/renderer/pose_sampler_test.cc native/tests/renderer/animation_update_test.cc
git commit -m "feat(native): layered gesture sampling over the placement rest pose"
```

---

### Task 2: Wire the controller to play gestures layered

**Files:**
- Modify: `engine/bridge_character_anim.py` (`_start_clip` → `play_instance_gesture`)
- Test: `tests/unit/test_bridge_character_anim.py` (FakeRenderer records gesture playback)

**Interfaces:**
- Consumes: `renderer.play_instance_gesture(iid, clip_index)` (Task L1).

- [ ] **Step 1: Update the controller test's FakeRenderer + assertions**

In `tests/unit/test_bridge_character_anim.py`, change the `_FakeRenderer` to expose `play_instance_gesture(self, iid, clip_index)` recording `(iid, clip_index)` into `self.played`, and (keep `load_instance_clip`). Update the two tests that assert on `r.played` so they expect the gesture-playback call (same `(iid, clip_index)` tuples as before — only the method name changes). Run them to confirm they now FAIL against the current controller (which still calls `set_instance_animation`):

Run: `uv run pytest tests/unit/test_bridge_character_anim.py -q`
Expected: FAIL (controller calls `set_instance_animation`, FakeRenderer no longer records it).

- [ ] **Step 2: Switch the controller to layered gesture playback**

In `engine/bridge_character_anim.py`, in `_start_clip`, replace the playback call:

```python
        clip_index = renderer.load_instance_clip(act.iid, path)
        if clip_index is not None and clip_index >= 0:
            renderer.play_instance_gesture(act.iid, clip_index)
```

Update the `hasattr` guard so the method probed is `play_instance_gesture` (the gesture path no-ops cleanly on a renderer lacking it). Keep `restore_rest_pose` (AT_DEFAULT) unchanged.

- [ ] **Step 3: Run the controller tests to verify pass**

Run: `uv run pytest tests/unit/test_bridge_character_anim.py -q`
Expected: PASS (clip-order, preempt, busy tests — now asserting `play_instance_gesture`).

- [ ] **Step 4: Run the full bridge-anim suite (no regression)**

Run: `uv run pytest tests/unit/test_bridge_character_anim.py tests/unit/test_bridge_idle_gestures.py tests/unit/test_bridge_hit_reactions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_character_anim.py tests/unit/test_bridge_character_anim.py
git commit -m "feat(bridge): play gestures layered over the rest pose (no centre-jump / T-pose)"
```

---

## Self-Review

- **Spec coverage:** layered sampler (L1 Steps 1-5), instance flag + update_animations layering (L1 Steps 6-10), binding + wrapper (L1 Steps 11-13), controller wiring (L2). The root-stays-at-station and untracked-bone-takes-base behaviors are directly asserted (L1 Step 1).
- **Type consistency:** `sample_pose_over_base(clip, skeleton, t, base_locals)`, `AnimationState.layer_over_rest`, `play_instance_gesture(iid, clip_index)` — names/signatures match across L1 and L2.
- **No verbatim duplication:** the per-bone decompose/sample logic is extracted into `pose_bone` and shared by `sample_pose` and `sample_pose_over_base` (L1 Step 4).
- **GUI gate:** the user verifies that a fired gesture animates the officer in place at their station (no centre-jump, no T-pose) and returns to rest.
