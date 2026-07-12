# Lift-Door Coordination / Ownership (SP-D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make BC's lift doors work the way the SDK actually drives them — the *named* door clip, on the *right* door, at the *scheduled* moment, audible, and coexisting with chair animations instead of clobbering them.

**Architecture:** Six components. One native change (bridge-node animations become a per-instance *set* of clips whose sampled node overrides are merged, keyed by clip path so an aliased re-play restarts rather than stacks); the rest is Python — doors resolve by name through `AnimationManager`, `AT_MOVE` plays the SDK's builder `TGSequence` instead of mining a clip out of it, and the two support gaps that turns up (the `CS_*` completion events and the door sound) get filled.

**Tech Stack:** C++17 / pybind11 / glm / gtest (native), Python 3 / pytest (engine), BC SDK Python scripts (ground truth, read-only).

**Spec:** `docs/superpowers/specs/2026-07-12-lift-door-ownership-design.md`. Read it before Task 1 — it carries the SDK evidence behind every decision here.

## Global Constraints

- **The SDK tree is read-only.** Never edit anything under `sdk/Build/scripts/`. It is ground truth. Adapt the engine to it.
- **Never stall a mission `TGSequence`.** Every action must call `Completed()` exactly once — zero times hangs the mission, twice double-advances it. Any failure path (missing clip, no renderer, headless, exception) must still complete the action.
- **Headless-safe.** Every engine path must work with no renderer and no controller registered (that is how the test suite and the mission harness run). Degrade, never raise.
- **Both bridges.** DBridge (Galaxy) and EBridge (Sovereign) are both in scope; other sets are not.
- **Native rebuild required for Task 1 only.** `host_bindings.cc` edits need a full `dauntless` rebuild (`cmake --build build -j`), not just the Python module — a module-only rebuild leaves `./build/dauntless` stale.
- **Test gate:** `scripts/check_tests.sh` (builds C++, runs pytest **and** ctest, diffs `tests/known_failures.txt`). The only allowed pre-existing failures are the 7 headless-GL scorch/heat-glow `FrameTest`s already in that ledger. Never call a failure "pre-existing" by eyeball.
- Door clip identity is the **lower-cased clip path**, never the animation name. BC registers one door NIF under two names (`"doorl1"` and `"DB_Door_L1"`) and E1M1 fires both for the same door.
- Units: door clips are 1.0 s, 3 keys, and return to their start pose (they open *and* close themselves). No close action is ever scheduled.

## File Structure

| File | Responsibility |
|---|---|
| `native/src/renderer/include/renderer/bridge_node_anim_store.h` | **New.** Pure, GL-free store: the set of active node clips per instance, path-keyed, merged sampling. |
| `native/src/renderer/bridge_node_anim_store.cc` | **New.** Its implementation. |
| `native/tests/renderer/bridge_node_anim_store_test.cc` | **New.** gtest for coexistence, restart-not-stack, alias collapse, last-frame hold. |
| `native/src/host/host_bindings.cc` | Replace the single-slot `g_bridge_node_anims` map with the store; pass a clip key from both play bindings. |
| `engine/bridge_cutscene.py` | Doors resolve by **name** through `AnimationManager` and play the named clip; the all-doors embedded clip goes away. |
| `engine/appc/animation_manager.py` | `GetAnimationLength` returns the real clip duration via an injected duration provider. |
| `engine/appc/characters.py` | Handle `ET_CHARACTER_ANIMATION_DONE` → apply `CS_STANDING` / `CS_SEATED` / `CS_HIDDEN`. |
| `App.py` | Define the `ET_CHARACTER_ANIMATION_DONE` constant. |
| `engine/bridge_sounds.py` | **New.** Call the bridge config module's `LoadSounds()` (the `"LiftDoor"` sound nothing in the SDK loads). |
| `engine/appc/actions.py` | `TGAnimAction` routes a **marked** walk action to the walk controller. |
| `engine/appc/ai.py` | `AT_MOVE` plays the builder sequence, marks the walk action, defers its completion to the sequence. |
| `engine/host_loop.py` | Wire the asset resolver into `BridgeCutsceneController`, the duration provider into `AnimationManager`, and the bridge-sound load into the bridge-load path. |

---

### Task 1: Native — concurrent bridge-node clips (the ownership fix)

Today `g_bridge_node_anims` is `unordered_map<instance_index, BridgeNodeAnim>` — **one clip per instance** — and `update_bridge_node_anims` does `inst->node_overrides = sample_node_overrides(...)` (an assignment). So a lift door and a chair turn on the same bridge instance silently overwrite each other. Extract a pure, GL-free store that holds a **set** of clips per instance and **merges** their sampled overrides.

**Files:**
- Create: `native/src/renderer/include/renderer/bridge_node_anim_store.h`
- Create: `native/src/renderer/bridge_node_anim_store.cc`
- Create: `native/tests/renderer/bridge_node_anim_store_test.cc`
- Modify: `native/src/host/host_bindings.cc` (lines 308–318, 560–587, 1288–1335)
- Modify: `native/tests/renderer/CMakeLists.txt` (add the test source next to `node_anim_test.cc` on line 17)
- Modify: the renderer library's source list (add `bridge_node_anim_store.cc` alongside `node_anim.cc`)

**Interfaces:**
- Consumes: `renderer::sample_node_overrides(clip, model, t)` from `renderer/node_anim.h`; `assets::AnimationClip` / `assets::Model`.
- Produces: `renderer::BridgeNodeAnimStore` with `play(index, key, clip, now, loop, reverse)`, `stop(index)`, `clear()`, `empty()`, `instances()`, `active_count(index)`, `sample(index, model, now)`; and free function `renderer::normalize_clip_key(path)`.

- [ ] **Step 1: Write the failing test**

Create `native/tests/renderer/bridge_node_anim_store_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <renderer/bridge_node_anim_store.h>
#include <assets/model.h>
#include <assets/animation.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/quaternion.hpp>

namespace {
// A bridge-shaped model: one door pair and one chair, as on the real DBridge.
assets::Model bridge_model() {
    assets::Model m;
    assets::Node root;  root.name = "root";  root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    assets::Node da;    da.name = "door 04a"; da.parent_index = 0;
    da.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(1, 0, 0));
    assets::Node db;    db.name = "door 04b"; db.parent_index = 0;
    db.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(2, 0, 0));
    assets::Node seat;  seat.name = "console seat 01"; seat.parent_index = 0;
    seat.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 5, 0));
    m.nodes = {root, da, db, seat};       // indices 0,1,2,3
    m.root_node = 0;
    return m;
}

// The L1 door clip: slides BOTH leaves aside over 1s and back — it opens and
// closes itself (3 keys, returns to start), exactly like DB_door_L1.NIF.
assets::AnimationClip door_clip() {
    assets::AnimationClip c; c.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack a; a.target_node_name = "door 04a";
    a.translation = {{0.0f, glm::vec3(1, 0, 0)},
                     {0.5f, glm::vec3(1, 0, 9)},
                     {1.0f, glm::vec3(1, 0, 0)}};
    assets::AnimationClip::NodeTrack b; b.target_node_name = "door 04b";
    b.translation = {{0.0f, glm::vec3(2, 0, 0)},
                     {0.5f, glm::vec3(2, 0, -9)},
                     {1.0f, glm::vec3(2, 0, 0)}};
    c.tracks = {a, b};
    return c;
}

// A chair turn: rotates the seat and HOLDS the turned pose (BC ships a separate
// reverse NIF to bring it back — the pose persists after the clip ends).
assets::AnimationClip chair_clip() {
    assets::AnimationClip c; c.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack s; s.target_node_name = "console seat 01";
    glm::quat rest = glm::angleAxis(glm::radians(0.0f),  glm::vec3(0, 0, 1));
    glm::quat turn = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    s.rotation = {{0.0f, rest}, {1.0f, turn}};
    c.tracks = {s};
    return c;
}

constexpr std::uint32_t kBridge = 7;   // arbitrary instance index
}  // namespace

// THE REGRESSION THIS TASK EXISTS TO FIX: today the second play overwrites the
// first, so a door opening during a turn-to-captain kills the chair clip.
TEST(BridgeNodeAnimStore, DoorAndChairCoexist) {
    renderer::BridgeNodeAnimStore s;
    auto m = bridge_model();
    s.play(kBridge, "data/animations/db_door_l1.nif", door_clip(), 0.0, false, false);
    s.play(kBridge, "data/animations/db_chair_h.nif", chair_clip(), 0.0, false, false);
    EXPECT_EQ(s.active_count(kBridge), 2u);

    auto ov = s.sample(kBridge, m, 0.5);      // mid-cycle: door open, chair turning
    ASSERT_EQ(ov.size(), 3u);                 // both door leaves AND the seat
    EXPECT_TRUE(ov.count(1));                 // door 04a
    EXPECT_TRUE(ov.count(2));                 // door 04b
    EXPECT_TRUE(ov.count(3));                 // console seat 01
    EXPECT_NEAR(ov[1][3].z,  9.0f, 1e-4f);    // leaf A slid open
    EXPECT_NEAR(ov[2][3].z, -9.0f, 1e-4f);    // leaf B slid open
}

// E1M1 fires the SAME door twice under two registered names. Re-playing must
// RESTART the clip, never stack a rival copy fighting over the same nodes.
TEST(BridgeNodeAnimStore, SamePathRestartsRatherThanStacks) {
    renderer::BridgeNodeAnimStore s;
    auto m = bridge_model();
    s.play(kBridge, "data/animations/db_door_l1.nif", door_clip(), 0.0, false, false);
    s.play(kBridge, "data/animations/db_door_l1.nif", door_clip(), 0.5, false, false);
    EXPECT_EQ(s.active_count(kBridge), 1u);

    // Restarted at t=0.5, so at now=0.5 the clip is at its OWN t=0 (closed).
    auto ov = s.sample(kBridge, m, 0.5);
    EXPECT_NEAR(ov[1][3].z, 0.0f, 1e-4f);
}

// "doorl1" -> db_door_l1.nif and "DB_Door_L1" -> DB_Door_L1.nif are the SAME
// file. Keying by name would let the aliases collide; keying by path collapses.
TEST(BridgeNodeAnimStore, CaseAliasesAreTheSameClip) {
    renderer::BridgeNodeAnimStore s;
    s.play(kBridge, "data/animations/DB_Door_L1.nif", door_clip(), 0.0, false, false);
    s.play(kBridge, "data/animations/db_door_l1.nif", door_clip(), 0.0, false, false);
    EXPECT_EQ(s.active_count(kBridge), 1u);
}

// One uniform rule, matching BC: a settled clip HOLDS its last frame. The chair
// stays turned; a door clip ends back at rest so holding it is invisible.
TEST(BridgeNodeAnimStore, SettledClipHoldsLastFrame) {
    renderer::BridgeNodeAnimStore s;
    auto m = bridge_model();
    s.play(kBridge, "data/animations/db_chair_h.nif", chair_clip(), 0.0, false, false);

    auto at_end  = s.sample(kBridge, m, 1.0);    // exactly the last frame
    auto way_past = s.sample(kBridge, m, 99.0);  // long after it settled
    ASSERT_TRUE(at_end.count(3) && way_past.count(3));
    for (int col = 0; col < 4; ++col)
        for (int row = 0; row < 4; ++row)
            EXPECT_NEAR(way_past[3][col][row], at_end[3][col][row], 1e-5f);
    EXPECT_EQ(s.active_count(kBridge), 1u);      // held, not evicted
}

TEST(BridgeNodeAnimStore, StopClearsTheInstanceAndSampleIsEmpty) {
    renderer::BridgeNodeAnimStore s;
    auto m = bridge_model();
    s.play(kBridge, "data/animations/db_door_l1.nif", door_clip(), 0.0, false, false);
    s.stop(kBridge);
    EXPECT_EQ(s.active_count(kBridge), 0u);
    EXPECT_TRUE(s.sample(kBridge, m, 0.5).empty());
    EXPECT_TRUE(s.empty());
}

TEST(BridgeNodeAnimStore, LoopingClipWraps) {
    renderer::BridgeNodeAnimStore s;
    auto m = bridge_model();
    s.play(kBridge, "data/animations/db_door_l1.nif", door_clip(), 0.0, true, false);
    auto a = s.sample(kBridge, m, 0.5);
    auto b = s.sample(kBridge, m, 2.5);     // 2 full cycles later == same phase
    EXPECT_NEAR(a[1][3].z, b[1][3].z, 1e-4f);
}
```

Register it in `native/tests/renderer/CMakeLists.txt` by adding `bridge_node_anim_store_test.cc` to the source list that already contains `node_anim_test.cc` (line 17).

- [ ] **Step 2: Run the test to verify it fails**

```bash
cmake -B build -S . && cmake --build build -j
```
Expected: **compile error** — `renderer/bridge_node_anim_store.h: No such file or directory`. That is the correct RED for a new module.

- [ ] **Step 3: Write the header**

Create `native/src/renderer/include/renderer/bridge_node_anim_store.h`:

```cpp
#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include <glm/glm.hpp>
#include <assets/animation.h>

namespace assets { struct Model; }

namespace renderer {

/// One active non-skinned node clip on an instance: a lift door, or a chair turn.
struct ActiveNodeClip {
    assets::AnimationClip clip;
    std::string key;                 ///< identity: lower-cased clip path
    double start_wall_time = 0.0;
    bool   loop    = false;
    bool   reverse = false;
    bool   settled = false;          ///< non-loop clip reached its end (holds last frame)
};

/// The bridge's active node animations.
///
/// BC plays MANY named animations on a set's anim node at once — lift doors and
/// chair turns both animate the bridge's node hierarchy — and the SDK never
/// arbitrates between them (there is no busy-check in any of the 1228 SDK files).
/// So an instance holds a SET of active clips whose sampled node overrides are
/// MERGED. They touch disjoint nodes ("door 04a"/"door 04b" vs "console seat NN"),
/// so the merge is unambiguous; on an overlap, insertion order decides.
///
/// Identity is the lower-cased clip PATH, not the animation name: BC registers one
/// door NIF under two names ("doorl1" from GalaxyBridge.PreloadAnimations,
/// "DB_Door_L1" from LoadBridge.PreloadCommonAnimations) and E1M1 fires BOTH for
/// the same door (the camera walk-on sequence and Picard's move builder). Keying by
/// path collapses the aliases, so the second play RESTARTS the door instead of
/// stacking a rival copy that fights over the same nodes.
///
/// Every clip HOLDS its last frame once settled — one uniform rule, matching BC: a
/// turned chair stays turned (BC ships a dedicated reverse NIF to bring it back),
/// and a door clip ends back at rest anyway, so holding it is invisible.
class BridgeNodeAnimStore {
public:
    /// Start the clip under `key` on `instance_index`, or RESTART it in place if
    /// that key is already active. Never stacks a duplicate.
    void play(std::uint32_t instance_index, const std::string& key,
              assets::AnimationClip clip, double now, bool loop, bool reverse);

    /// Drop every clip on one instance (mission reset / bridge teardown).
    void stop(std::uint32_t instance_index);

    /// Drop everything (shutdown).
    void clear();

    bool empty() const { return clips_.empty(); }
    std::vector<std::uint32_t> instances() const;
    std::size_t active_count(std::uint32_t instance_index) const;

    /// Sample every active clip on `instance_index` at wall time `now` and merge
    /// the results into one node_index -> local_transform override map.
    std::unordered_map<int, glm::mat4> sample(std::uint32_t instance_index,
                                              const assets::Model& model, double now);

private:
    std::unordered_map<std::uint32_t, std::vector<ActiveNodeClip>> clips_;
};

/// Lower-case a clip path so two case-different registrations of the same NIF
/// resolve to one identity.
std::string normalize_clip_key(const std::string& path);

}  // namespace renderer
```

- [ ] **Step 4: Write the implementation**

Create `native/src/renderer/bridge_node_anim_store.cc`:

```cpp
#include <renderer/bridge_node_anim_store.h>

#include <renderer/node_anim.h>
#include <assets/model.h>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <utility>

namespace renderer {

std::string normalize_clip_key(const std::string& path) {
    std::string out(path);
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return out;
}

void BridgeNodeAnimStore::play(std::uint32_t instance_index, const std::string& key,
                               assets::AnimationClip clip, double now,
                               bool loop, bool reverse) {
    const std::string k = normalize_clip_key(key);
    auto& list = clips_[instance_index];
    for (auto& a : list) {
        if (a.key == k) {                       // restart in place, never stack
            a.clip = std::move(clip);
            a.start_wall_time = now;
            a.loop = loop;
            a.reverse = reverse;
            a.settled = false;
            return;
        }
    }
    ActiveNodeClip a;
    a.clip = std::move(clip);
    a.key = k;
    a.start_wall_time = now;
    a.loop = loop;
    a.reverse = reverse;
    list.push_back(std::move(a));
}

void BridgeNodeAnimStore::stop(std::uint32_t instance_index) {
    clips_.erase(instance_index);
}

void BridgeNodeAnimStore::clear() { clips_.clear(); }

std::vector<std::uint32_t> BridgeNodeAnimStore::instances() const {
    std::vector<std::uint32_t> out;
    out.reserve(clips_.size());
    for (const auto& kv : clips_) out.push_back(kv.first);
    return out;
}

std::size_t BridgeNodeAnimStore::active_count(std::uint32_t instance_index) const {
    auto it = clips_.find(instance_index);
    return it == clips_.end() ? 0u : it->second.size();
}

std::unordered_map<int, glm::mat4> BridgeNodeAnimStore::sample(
        std::uint32_t instance_index, const assets::Model& model, double now) {
    std::unordered_map<int, glm::mat4> merged;
    auto it = clips_.find(instance_index);
    if (it == clips_.end()) return merged;

    for (auto& a : it->second) {
        const float dur = a.clip.duration_seconds;
        double elapsed = now - a.start_wall_time;
        if (elapsed < 0.0) elapsed = 0.0;

        float t;
        if (a.loop) {
            t = dur > 0.0f ? static_cast<float>(std::fmod(elapsed, dur)) : 0.0f;
        } else if (elapsed >= static_cast<double>(dur)) {
            t = dur;
            a.settled = true;                   // HOLD the last frame
        } else {
            t = static_cast<float>(elapsed);
        }
        if (a.reverse) t = dur - t;

        // Merge: clips touch disjoint nodes; on overlap, insertion order wins.
        for (const auto& kv : sample_node_overrides(a.clip, model, t))
            merged[kv.first] = kv.second;
    }
    return merged;
}

}  // namespace renderer
```

Add `bridge_node_anim_store.cc` to the renderer library's source list in `native/CMakeLists.txt` (or `native/src/renderer/CMakeLists.txt` — wherever `node_anim.cc` is listed; grep for it).

- [ ] **Step 5: Run the test to verify it passes**

```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R BridgeNodeAnimStore --output-on-failure
```
Expected: **6/6 PASS**.

- [ ] **Step 6: Rewire `host_bindings.cc` onto the store**

In `native/src/host/host_bindings.cc`:

Replace the struct + map at lines 308–318 with:

```cpp
#include <renderer/bridge_node_anim_store.h>   // with the other renderer includes

// Bridge-node animation store: the active non-skinned node clips (doors, chairs).
// A SET per instance, merged on sample — doors and chairs animate the same bridge
// node hierarchy and BC never arbitrates between them.
renderer::BridgeNodeAnimStore g_bridge_node_anims;
```

`scenegraph::World` exposes only `get(InstanceId)` — there is **no** index lookup, and
this task must not add one. The store stays scenegraph-free (that is what makes it
unit-testable), so `host_bindings` keeps the `InstanceId` for each live index beside it.
Add next to the store declaration:

```cpp
// The store is keyed by InstanceId::index (it must not depend on scenegraph, so it
// stays GL-free and unit-testable). World lookups need the full id, so keep it here.
std::unordered_map<std::uint32_t, scenegraph::InstanceId> g_bridge_node_ids;
```

Replace `update_bridge_node_anims` (lines 564–587) with:

```cpp
void update_bridge_node_anims(double now) {
    for (std::uint32_t index : g_bridge_node_anims.instances()) {
        auto id_it = g_bridge_node_ids.find(index);
        if (id_it == g_bridge_node_ids.end()) { g_bridge_node_anims.stop(index); continue; }
        scenegraph::Instance* inst = g_world.get(id_it->second);
        if (!inst) {                                  // instance destroyed
            g_bridge_node_anims.stop(index);
            g_bridge_node_ids.erase(id_it);
            continue;
        }
        const assets::Model* m = resolve_model(inst->model_handle);
        if (!m) continue;
        inst->node_overrides = g_bridge_node_anims.sample(index, *m, now);
    }
}
```

In `play_instance_node_anim` (line 1288), replace the `BridgeNodeAnim a; …; g_bridge_node_anims[id.index] = std::move(a);` tail with:

```cpp
              g_bridge_node_ids[id.index] = id;
              g_bridge_node_anims.play(id.index,
                                       "embedded:" + std::to_string(clip_index),
                                       m->animations[clip_index],   // owned copy
                                       glfwGetTime(), loop, reverse);
```

In `play_instance_node_clip` (line 1307), key by the clip's **path** (that is what
collapses BC's two registered names for the same door NIF):

```cpp
              auto clips = assets::load_animation_clips(
                  renderer::resolve_asset_path(path));
              if (clips.empty()) return;               // NIF had no clips
              g_bridge_node_ids[id.index] = id;
              g_bridge_node_anims.play(id.index, path, std::move(clips[0]),
                                       glfwGetTime(), loop, reverse);
```

In `stop_instance_node_anim` (line 1331):

```cpp
              g_bridge_node_anims.stop(id.index);
              g_bridge_node_ids.erase(id.index);
```

At the two teardown sites (lines 415, 481), replace `g_bridge_node_anims.clear();` with:

```cpp
    g_bridge_node_anims.clear();
    g_bridge_node_ids.clear();
```

- [ ] **Step 7: Rebuild and run the full native suite**

```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure
```
Expected: all tests pass except the 7 headless-GL `FrameTest`s already listed in `tests/known_failures.txt`.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/bridge_node_anim_store.h \
        native/src/renderer/bridge_node_anim_store.cc \
        native/tests/renderer/bridge_node_anim_store_test.cc \
        native/tests/renderer/CMakeLists.txt native/CMakeLists.txt \
        native/src/host/host_bindings.cc
git commit -m "feat(bridge): concurrent bridge-node clips — doors and chairs stop clobbering each other"
```

---

### Task 2: Doors play the named clip, not the bridge's all-doors clip

`BridgeCutsceneController._update_doors` throws the door name away and plays the bridge model's **embedded** clip 0 — 12 tracks on DBridge (all six door pairs), 10 on EBridge (all doors **plus both commander chairs**). Resolve the name through `AnimationManager` and play that clip instead, exactly as `BridgeNodeAnimController` already does for chairs.

**Files:**
- Modify: `engine/bridge_cutscene.py` (lines 26–33 constructor, 39–40 `request_object_anim`, 58–71 `_update_doors`)
- Modify: `engine/host_loop.py:5110` (pass the asset resolver)
- Test: `tests/host/test_bridge_doors.py` (new)

**Interfaces:**
- Consumes: `AnimationManager.path_for(name) -> str | None`; `renderer.play_instance_node_clip(iid, path, loop, reverse)`; `_game_asset_path(rel) -> str` (host_loop's resolver, already passed to `BridgeCharacterAnimController` and `BridgeNodeAnimController`).
- Produces: `BridgeCutsceneController(asset_resolver=None)`; `_update_doors(renderer, anim_mgr)`.

- [ ] **Step 1: Write the failing test**

Create `tests/host/test_bridge_doors.py`:

```python
"""Lift doors play the NAMED door clip, not the bridge's all-doors clip.

BC registers each door as its own external keyframe NIF (GalaxyBridge:
kAM.LoadAnimation("data/animations/db_door_l1.nif", "doorl1")) and each clip
drives exactly ONE door pair, opening and closing itself over 1s.

The bridge model's own embedded clip animates EVERY door (and, on EBridge, both
commander chairs), so playing it for a single lift cue is wrong.
"""
from engine.bridge_cutscene import BridgeCutsceneController


class _FakeAnimMgr:
    def __init__(self, paths):
        self._paths = paths

    def path_for(self, name):
        return self._paths.get(str(name))


class _RecordingRenderer:
    def __init__(self):
        self.node_clips = []      # (iid, path, loop, reverse)
        self.node_anims = []      # (iid, clip_index) — the WRONG path

    def play_instance_node_clip(self, iid, path, loop, reverse):
        self.node_clips.append((iid, path, loop, reverse))

    def play_instance_node_anim(self, iid, clip_index, loop=False, reverse=False):
        self.node_anims.append((iid, clip_index))


class _FakeAction:
    def __init__(self):
        self.completed = 0

    def Completed(self):
        self.completed += 1


class _FakeNode:
    def __init__(self, owner):
        self.owner = owner
        self.kind = "object"


class _FakeBridge:
    render_instance = 42


def _ctrl():
    return BridgeCutsceneController(asset_resolver=lambda rel: "/game/" + rel)


def test_named_door_clip_is_played_and_the_all_doors_clip_is_not():
    ctrl, r = _ctrl(), _RecordingRenderer()
    anim = _FakeAnimMgr({"doorl1": "data/animations/db_door_l1.nif"})
    act = _FakeAction()
    ctrl.request_object_anim(act, _FakeNode(_FakeBridge()), "doorl1")

    ctrl._update_doors(r, anim)

    assert r.node_clips == [(42, "/game/data/animations/db_door_l1.nif", False, False)]
    assert r.node_anims == [], "the bridge's embedded all-doors clip must never be played"
    assert act.completed == 1, "LiftDoorAction is fire-and-forget: complete exactly once"


def test_the_door_name_selects_the_clip():
    """L2 must open L2's door, not L1's."""
    ctrl, r = _ctrl(), _RecordingRenderer()
    anim = _FakeAnimMgr({"doorl1": "data/animations/db_door_l1.nif",
                         "EB_Door_L2": "data/animations/EB_door_L2.nif"})
    ctrl.request_object_anim(_FakeAction(), _FakeNode(_FakeBridge()), "EB_Door_L2")
    ctrl._update_doors(r, anim)
    assert r.node_clips[0][1] == "/game/data/animations/EB_door_L2.nif"


def test_unresolvable_door_name_completes_and_plays_nothing():
    """Never stall a mission TGSequence on a door we cannot resolve."""
    ctrl, r = _ctrl(), _RecordingRenderer()
    act = _FakeAction()
    ctrl.request_object_anim(act, _FakeNode(_FakeBridge()), "NoSuchDoor")
    ctrl._update_doors(r, _FakeAnimMgr({}))
    assert r.node_clips == [] and r.node_anims == []
    assert act.completed == 1


def test_door_waits_for_the_bridge_instance_to_be_realized():
    """No render instance yet -> stay pending, do not complete, do not play."""
    class _Unrealized:
        render_instance = None

    ctrl, r = _ctrl(), _RecordingRenderer()
    anim = _FakeAnimMgr({"doorl1": "data/animations/db_door_l1.nif"})
    act = _FakeAction()
    ctrl.request_object_anim(act, _FakeNode(_Unrealized()), "doorl1")
    ctrl._update_doors(r, anim)
    assert r.node_clips == [] and act.completed == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/host/test_bridge_doors.py -v`
Expected: FAIL — `BridgeCutsceneController.__init__() got an unexpected keyword argument 'asset_resolver'`.

- [ ] **Step 3: Implement**

In `engine/bridge_cutscene.py`, take a resolver in the constructor and store the clip name on the request:

```python
    def __init__(self, asset_resolver=None):
        # Pending camera request: (action, clip_name) before the clip loads.
        self._pending_camera = None
        # Active camera playback: dict(action, track, duration, t).
        self._active_camera = None
        # Pending door requests: list of (action, owner, clip_name).
        self._pending_doors = []
        self._resolve = asset_resolver or (lambda p: p)

    def request_object_anim(self, action, anim_node, clip_name):
        self._pending_doors.append(
            (action, getattr(anim_node, "owner", None), str(clip_name)))
```

Thread `anim_mgr` into the door pump (`update` already receives it):

```python
    def update(self, dt, *, bridge_camera, view_mode, renderer, anim_mgr):
        self._update_doors(renderer, anim_mgr)
        self._update_camera(dt, bridge_camera, view_mode, renderer, anim_mgr)

    def _update_doors(self, renderer, anim_mgr):
        still_pending = []
        for action, owner, clip_name in self._pending_doors:
            iid = getattr(owner, "render_instance", None)
            if iid is None:
                still_pending.append((action, owner, clip_name))   # wait for realize
                continue
            # BC's doors are NAMED external keyframe NIFs registered on the
            # AnimationManager (GalaxyBridge.PreloadAnimations: "doorl1" ->
            # db_door_l1.nif). Each clip drives exactly ONE door pair and opens
            # and closes itself over 1s -- which is why no LiftDoorAction call
            # site in the SDK ever passes the optional close clip.
            #
            # NOT the bridge model's embedded clip: that one animates all six
            # door pairs at once (and, on EBridge, both commander chairs).
            path = anim_mgr.path_for(clip_name) if anim_mgr is not None else None
            if path:
                try:
                    renderer.play_instance_node_clip(
                        iid, self._resolve(path), False, False)
                except Exception:
                    _logger.debug("door play failed: %r", clip_name, exc_info=True)
            else:
                _logger.warning("door clip %r not registered", clip_name)
            action.Completed()      # fire-and-forget: LiftDoorAction returns 0
        self._pending_doors = still_pending
```

Add at the top of the module: `import logging` and `_logger = logging.getLogger(__name__)`.

In `engine/host_loop.py:5110`, pass the resolver:

```python
        cutscene = BridgeCutsceneController(asset_resolver=_game_asset_path)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/host/test_bridge_doors.py -v`
Expected: **4 passed**.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_cutscene.py engine/host_loop.py tests/host/test_bridge_doors.py
git commit -m "fix(bridge): play the NAMED door clip, not the bridge's all-doors clip"
```

---

### Task 3: `GetAnimationLength` returns the real clip duration

The SDK schedules the walk-**off** door relative to the walk clip's length —
`fTime = kAM.GetAnimationLength("db_PtoL1_P"); AddAction(pDoorAction, pStand, fTime - 1.25)`
(`PicardAnimations.py:145`). Ours returns `0.0`, making that offset **−1.25 s**.

`AnimationManager` is pure name→path bookkeeping with no renderer, so the host injects a duration provider.

**Files:**
- Modify: `engine/appc/animation_manager.py`
- Modify: `engine/host_loop.py` (wire the provider where `AnimationManager` is constructed / reset — grep `g_kAnimationManager`)
- Test: `tests/unit/test_animation_manager.py` (create if absent; else extend)

**Interfaces:**
- Consumes: `renderer.load_animation_clips(path) -> list[dict]`, each clip dict carrying `"tracks"` with `"translation"` / `"rotation"` key lists of `(time, ...)` tuples.
- Produces: `AnimationManager.set_duration_provider(fn)` where `fn(path: str) -> float`; `GetAnimationLength(name) -> float` (cached).

- [ ] **Step 1: Write the failing test**

Create/extend `tests/unit/test_animation_manager.py`:

```python
"""GetAnimationLength must return the REAL clip length.

The SDK schedules the walk-off lift door relative to it:
    fTime = kAM.GetAnimationLength("db_PtoL1_P")
    pSequence.AddAction(pDoorAction, pAnimAction_Stand, fTime - 1.25)
Returning 0.0 makes that offset -1.25s, so the door timing is meaningless.
"""
from engine.appc.animation_manager import AnimationManager


def test_get_animation_length_uses_the_duration_provider():
    am = AnimationManager()
    am.LoadAnimation("data/animations/db_PtoL1_P.nif", "db_PtoL1_P")
    am.set_duration_provider(lambda path: 4.5 if path.endswith("db_PtoL1_P.nif") else 0.0)
    assert am.GetAnimationLength("db_PtoL1_P") == 4.5


def test_walk_off_door_offset_is_positive():
    """The whole point: fTime - 1.25 must land INSIDE the walk, not before it."""
    am = AnimationManager()
    am.LoadAnimation("data/animations/db_PtoL1_P.nif", "db_PtoL1_P")
    am.set_duration_provider(lambda path: 4.5)
    assert am.GetAnimationLength("db_PtoL1_P") - 1.25 > 0.0


def test_duration_is_cached_per_name():
    calls = []

    def provider(path):
        calls.append(path)
        return 2.0

    am = AnimationManager()
    am.LoadAnimation("data/animations/x.nif", "x")
    am.set_duration_provider(provider)
    assert am.GetAnimationLength("x") == 2.0
    assert am.GetAnimationLength("x") == 2.0
    assert len(calls) == 1, "the clip must be measured once, not once per query"


def test_unknown_name_and_no_provider_return_zero_not_raise():
    am = AnimationManager()
    assert am.GetAnimationLength("nope") == 0.0        # no provider, headless
    am.set_duration_provider(lambda path: 3.0)
    assert am.GetAnimationLength("nope") == 0.0        # name never registered


def test_provider_failure_degrades_to_zero():
    def boom(path):
        raise RuntimeError("no renderer")

    am = AnimationManager()
    am.LoadAnimation("data/animations/x.nif", "x")
    am.set_duration_provider(boom)
    assert am.GetAnimationLength("x") == 0.0


def test_freeing_an_animation_drops_its_cached_duration():
    am = AnimationManager()
    am.LoadAnimation("data/animations/x.nif", "x")
    am.set_duration_provider(lambda path: 2.0)
    assert am.GetAnimationLength("x") == 2.0
    am.FreeAnimation("x")
    assert am.GetAnimationLength("x") == 0.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_animation_manager.py -v`
Expected: FAIL — `AttributeError: 'AnimationManager' object has no attribute 'set_duration_provider'`.

- [ ] **Step 3: Implement**

In `engine/appc/animation_manager.py`:

```python
class AnimationManager:
    def __init__(self) -> None:
        self._paths: dict[str, str] = {}        # animation name -> NIF path
        self._durations: dict[str, float] = {}  # animation name -> clip length (s)
        self._duration_provider = None          # (path) -> float, injected by the host

    def set_duration_provider(self, fn) -> None:
        """Host-injected clip measurer. AnimationManager itself loads nothing;
        the host owns the renderer that can read a NIF's keyframe times."""
        self._duration_provider = fn
        self._durations.clear()

    def GetAnimationLength(self, name) -> float:
        """The clip's real length in seconds, or 0.0 when it cannot be measured.

        The SDK schedules the walk-off lift door at `GetAnimationLength(walk) - 1.25`
        (PicardAnimations.py:145), so a 0.0 here makes the door fire 1.25s BEFORE the
        sequence starts. Headless (no provider) still returns 0.0 — safe-fail, and
        the door simply fires at the sequence root.
        """
        key = str(name)
        if key in self._durations:
            return self._durations[key]
        path = self._paths.get(key)
        if not path or self._duration_provider is None:
            return 0.0
        try:
            length = float(self._duration_provider(path))
        except Exception:
            length = 0.0
        self._durations[key] = length
        return length

    def FreeAnimation(self, name) -> None:
        self._paths.pop(str(name), None)
        self._durations.pop(str(name), None)
```

In `engine/host_loop.py`, right after the renderer is up and `g_kAnimationManager` exists, wire the provider (grep `g_kAnimationManager` for the construction/reset site):

```python
def _clip_duration(renderer, rel_path) -> float:
    """Max keyframe time across a clip's tracks — the clip's real length."""
    try:
        clips = renderer.load_animation_clips(_game_asset_path(rel_path))
    except Exception:
        return 0.0
    if not clips:
        return 0.0
    longest = 0.0
    for track in clips[0].get("tracks", []):
        for channel in ("translation", "rotation"):
            keys = track.get(channel) or []
            if keys:
                longest = max(longest, float(keys[-1][0]))
    return longest

# at bridge/mission setup, once the renderer exists:
App.g_kAnimationManager.set_duration_provider(
    lambda rel: _clip_duration(renderer, rel))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_animation_manager.py -v`
Expected: **6 passed**.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/animation_manager.py engine/host_loop.py tests/unit/test_animation_manager.py
git commit -m "fix(bridge): GetAnimationLength returns the real clip length (walk-off door timing)"
```

---

### Task 4: `ET_CHARACTER_ANIMATION_DONE` → character state

This event is handled **nowhere** in our engine. It does not matter today because nothing plays the builder sequences — but Task 6 makes it load-bearing. `MoveFromPToL1` (`PicardAnimations.py:151`) carries `SetInt(CS_HIDDEN)` under the SDK's own comment *"Add event to hide character after it gets into the turbolift"*. Without this, **every officer who walks off stands in the turbolift forever**.

**Files:**
- Modify: `App.py` (event-type constant block near line 787)
- Modify: `engine/appc/characters.py` (`CharacterClass.ProcessEvent`)
- Test: `tests/unit/test_character_animation_done.py` (new)

**Interfaces:**
- Consumes: `App.ET_CHARACTER_ANIMATION_DONE` (new int constant); `TGIntEvent.GetInt()`, `event.GetDestination()`.
- Produces: `CharacterClass.ProcessEvent(event)` applying `CS_STANDING` / `CS_SEATED` / `CS_HIDDEN`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_character_animation_done.py`:

```python
"""ET_CHARACTER_ANIMATION_DONE applies the carried character state.

Every SDK move builder ends with one, e.g. PicardAnimations.MoveFromPToL1:

    pEvent = App.TGIntEvent_Create()   # "Add event to hide character after it
    pEvent.SetEventType(App.ET_CHARACTER_ANIMATION_DONE)   #  gets into the turbolift"
    pEvent.SetDestination(pCharacter)
    pEvent.SetInt(App.CharacterClass.CS_HIDDEN)
    pSequence.AddCompletedEvent(pEvent)

BC's native engine consumes it and applies the state. Without it a walking-off
officer never hides.
"""
import App
from engine.appc.characters import CharacterClass


def _event(character, state):
    ev = App.TGIntEvent_Create()
    ev.SetEventType(App.ET_CHARACTER_ANIMATION_DONE)
    ev.SetDestination(character)
    ev.SetInt(state)
    return ev


def test_cs_hidden_hides_the_character():
    ch = CharacterClass()
    ch.SetHidden(0)
    ch.ProcessEvent(_event(ch, CharacterClass.CS_HIDDEN))
    assert ch.IsHidden() == 1


def test_cs_standing_reveals_and_stands():
    ch = CharacterClass()
    ch.SetHidden(1)
    ch.ProcessEvent(_event(ch, CharacterClass.CS_STANDING))
    assert ch.IsHidden() == 0
    assert ch.IsStanding() == 1


def test_cs_seated_reveals_and_seats():
    ch = CharacterClass()
    ch.SetHidden(1)
    ch.ProcessEvent(_event(ch, CharacterClass.CS_SEATED))
    assert ch.IsHidden() == 0
    assert ch.IsStanding() == 0


def test_the_constant_is_a_real_int_not_a_stub():
    """An undefined App constant collapses to a _NamedStub whose int() is 0, which
    would silently alias every other event type. Guard against that."""
    assert isinstance(App.ET_CHARACTER_ANIMATION_DONE, int)
    assert App.ET_CHARACTER_ANIMATION_DONE != 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_character_animation_done.py -v`
Expected: FAIL — `test_the_constant_is_a_real_int_not_a_stub` fails (the name resolves to a `_NamedStub`), and the state tests fail because nothing applies the state.

- [ ] **Step 3: Implement**

In `App.py`, in the event-type constant block (near `ET_ENTERED_SET = 105`):

```python
# Fired by every SDK character-move builder's completed-event (PicardAnimations,
# MediumAnimations, ...) carrying a CS_* state as its int. BC's native engine
# consumes it and applies that state to the destination character — that is how an
# officer HIDES after walking into the turbolift (CS_HIDDEN) and how a walk-on ends
# STANDING / SEATED.
ET_CHARACTER_ANIMATION_DONE = 106
```

Pick the next free integer in that block — grep the block first and do not reuse an existing value.

In `engine/appc/characters.py`, on `CharacterClass`:

```python
    def ProcessEvent(self, event) -> None:
        import App
        try:
            et = event.GetEventType()
        except Exception:
            et = None
        if et == App.ET_CHARACTER_ANIMATION_DONE:
            try:
                state = int(event.GetInt())
            except Exception:
                state = None
            if state == self.CS_HIDDEN:
                self.SetHidden(1)
            elif state == self.CS_STANDING:
                self.SetHidden(0)
                self.SetStanding(1)
            elif state == self.CS_SEATED:
                self.SetHidden(0)
                self.SetStanding(0)
            return
        super().ProcessEvent(event)
```

Check `CharacterClass`'s existing `SetStanding` signature before writing this — it toggles `CS_STANDING` when called bare (`characters.py:533`). Match the real API; if `SetStanding` does not take an int, use the `_states` add/discard the class already uses for `SetHidden`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_character_animation_done.py -v`
Expected: **4 passed**.

- [ ] **Step 5: Commit**

```bash
git add App.py engine/appc/characters.py tests/unit/test_character_animation_done.py
git commit -m "feat(bridge): ET_CHARACTER_ANIMATION_DONE applies CS_STANDING/CS_SEATED/CS_HIDDEN"
```

---

### Task 5: Load the bridge module's `LiftDoor` sound

`"LiftDoor"` (`sfx/door.wav`) is loaded **only** by `GalaxyBridge.LoadSounds()` / `SovereignBridge.LoadSounds()` — and **nothing in the SDK calls them**. `LoadBridge.Load` calls `CreateBridgeModel`, `ConfigureCharacters` and `PreloadAnimations` but not `LoadSounds`, while its *unload* path **does** call `UnloadSounds()`. The SDK unloads a sound it never loads.

We cannot tell from the SDK whether BC's native engine calls it or whether this is a shipped BC bug, and this plan does not pretend to know. Either way the sound must be loaded or `TGSoundAction("LiftDoor")` resolves to nothing and the door is silent. This is a **documented deviation**. `GalaxyBridge.LoadSounds()` loads exactly one sound, so the blast radius is nil.

**Files:**
- Create: `engine/bridge_sounds.py`
- Modify: `engine/host_loop.py` (call it right after `LoadBridge.Load` — grep `LoadBridge`)
- Test: `tests/unit/test_bridge_sounds.py` (new)

**Interfaces:**
- Consumes: `BridgeSet.GetConfig() -> str` (e.g. `"GalaxyBridge"`), set by `LoadBridge.Load`.
- Produces: `engine.bridge_sounds.load_bridge_module_sounds(bridge_set) -> bool` (True when a module's `LoadSounds()` ran).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bridge_sounds.py`:

```python
"""The bridge module's LoadSounds() — a documented deviation from the SDK.

"LiftDoor" (sfx/door.wav) is loaded ONLY by GalaxyBridge.LoadSounds() /
SovereignBridge.LoadSounds(), and NOTHING in the 1228 SDK files calls them:
LoadBridge.Load calls CreateBridgeModel/ConfigureCharacters/PreloadAnimations but
not LoadSounds -- while its UNLOAD path does call UnloadSounds(). The SDK unloads a
sound it never loads. We cannot tell from the SDK whether BC's native engine calls
it or whether this is a shipped BC bug; either way, without it every lift door is
silent, so we call it ourselves.
"""
import sys
import types

from engine.bridge_sounds import load_bridge_module_sounds


class _FakeSet:
    def __init__(self, config):
        self._config = config

    def GetConfig(self):
        return self._config


def _install_fake_bridge_module(monkeypatch, name, calls):
    mod = types.ModuleType("Bridge." + name)
    mod.LoadSounds = lambda: calls.append(name)
    pkg = types.ModuleType("Bridge")
    setattr(pkg, name, mod)
    monkeypatch.setitem(sys.modules, "Bridge", pkg)
    monkeypatch.setitem(sys.modules, "Bridge." + name, mod)


def test_calls_the_configured_bridge_modules_loadsounds(monkeypatch):
    calls = []
    _install_fake_bridge_module(monkeypatch, "GalaxyBridge", calls)
    assert load_bridge_module_sounds(_FakeSet("GalaxyBridge")) is True
    assert calls == ["GalaxyBridge"]


def test_sovereign_bridge_loads_its_own_sounds(monkeypatch):
    calls = []
    _install_fake_bridge_module(monkeypatch, "SovereignBridge", calls)
    assert load_bridge_module_sounds(_FakeSet("SovereignBridge")) is True
    assert calls == ["SovereignBridge"]


def test_missing_config_is_a_no_op():
    assert load_bridge_module_sounds(_FakeSet("")) is False
    assert load_bridge_module_sounds(None) is False


def test_a_module_without_loadsounds_does_not_raise(monkeypatch):
    mod = types.ModuleType("Bridge.CardassianBridge")   # no LoadSounds attribute
    pkg = types.ModuleType("Bridge")
    pkg.CardassianBridge = mod
    monkeypatch.setitem(sys.modules, "Bridge", pkg)
    monkeypatch.setitem(sys.modules, "Bridge.CardassianBridge", mod)
    assert load_bridge_module_sounds(_FakeSet("CardassianBridge")) is False


def test_a_raising_loadsounds_degrades_to_false(monkeypatch):
    def boom():
        raise RuntimeError("no audio device")

    mod = types.ModuleType("Bridge.GalaxyBridge")
    mod.LoadSounds = boom
    pkg = types.ModuleType("Bridge")
    pkg.GalaxyBridge = mod
    monkeypatch.setitem(sys.modules, "Bridge", pkg)
    monkeypatch.setitem(sys.modules, "Bridge.GalaxyBridge", mod)
    assert load_bridge_module_sounds(_FakeSet("GalaxyBridge")) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_sounds.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.bridge_sounds'`.

- [ ] **Step 3: Implement**

Create `engine/bridge_sounds.py`:

```python
"""Load the bridge config module's own sounds — a documented SDK deviation.

"LiftDoor" (sfx/door.wav), the sound every one of BC's 19 LiftDoorAction call sites
names, is loaded ONLY by GalaxyBridge.LoadSounds() / SovereignBridge.LoadSounds() --
and NOTHING in the SDK calls them. LoadBridge.Load calls the module's
CreateBridgeModel, ConfigureCharacters and PreloadAnimations, but not LoadSounds;
its UNLOAD path, however, does call UnloadSounds(). So the SDK unloads a sound it
never loads.

Whether BC's native engine calls it, or whether this is a bug in BC's shipped
scripts, is not determinable from the SDK -- and this module does not pretend to
know. What is certain is that without the call, TGSoundAction("LiftDoor") resolves
to nothing and every lift door is silent. GalaxyBridge.LoadSounds() loads exactly
one sound, so restoring the pairing the unload path already assumes costs nothing.
"""
import importlib
import logging

_logger = logging.getLogger(__name__)


def load_bridge_module_sounds(bridge_set) -> bool:
    """Call LoadSounds() on the bridge config module named by the set's config
    (e.g. "GalaxyBridge"). Returns True when a module's LoadSounds() actually ran.
    Best-effort: any failure degrades to False, never raises."""
    if bridge_set is None:
        return False
    try:
        config = str(bridge_set.GetConfig() or "")
    except Exception:
        return False
    if not config:
        return False
    try:
        module = importlib.import_module("Bridge." + config)
        fn = getattr(module, "LoadSounds", None)
        if fn is None:
            return False
        fn()
        return True
    except Exception:
        _logger.debug("bridge LoadSounds failed for %r", config, exc_info=True)
        return False
```

In `engine/host_loop.py`, immediately after the `LoadBridge.Load(...)` call (grep `LoadBridge`), add:

```python
        from engine import bridge_sounds
        bridge_sounds.load_bridge_module_sounds(
            App.g_kSetManager.GetSet("bridge"))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_sounds.py -v`
Expected: **5 passed**.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_sounds.py engine/host_loop.py tests/unit/test_bridge_sounds.py
git commit -m "fix(bridge): load the bridge module's LiftDoor sound (documented SDK deviation)"
```

---

### Task 6: `AT_MOVE` plays the SDK builder sequence

`_queue_move` extracts one clip out of the builder's `TGSequence` and drops everything else — including the `LiftDoorAction`. Play the sequence instead, so BC's own authoring drives the scene: the walk clip, the door **at its scheduled offset**, the door sound, the trailing `AT_SET_LOCATION_NAME`, and the `CS_*` completion events (Task 4).

**The walk action is marked explicitly.** Only the action `AT_MOVE` tags routes to the walk controller. This is load-bearing, not laziness: `EyesOpenMouthClosed` is **also** a character-node `TGAnimAction` (a 0.1 s facial clip) and is the very dependency the door is scheduled off (`AddAction(pDoorAction, pOpenEyes, 0.125)`). Routing every character-node action to root-motion playback would drive the officer's whole skeleton from an eyes-and-mouth clip and stall the walk behind facial animation **we do not support at all**. Eyes and twitch keep today's instant-complete behaviour.

**Files:**
- Modify: `engine/appc/actions.py` (`TGAnimAction._do_play`, lines 640–655)
- Modify: `engine/appc/ai.py` (`_queue_move`, lines 1239–1262)
- Test: `tests/unit/test_at_move_sequence.py` (new)

**Interfaces:**
- Consumes: `bridge_placement._resolve_builder_sequence(character, suffix) -> TGSequence | None`; `bridge_character_walk.get_controller().request_move(character, clip_nif, end_location, on_complete)`; `App.TGObjPtrEvent_Create()` / `App.ET_ACTION_COMPLETED` / `App.g_kTGActionManager` (the SDK's own deferred-completion route: `TGActionManager.ProcessEvent` calls `owner.Completed()` for an `ET_ACTION_COMPLETED` whose ObjPtr is the owner — `actions.py:730`).
- Produces: `TGAnimAction._walk_move` (bool marker, default False); `bridge_placement.walk_action_of(seq) -> TGAnimAction | None`.

> **Deviation from the spec, deliberately:** the spec proposed "an engine-internal completion hook on `TGSequence`". None is needed — the SDK already has this exact pattern (`ViewscreenOn` / `PlayDialog` defer completion by posting `ET_ACTION_COMPLETED` to `g_kTGActionManager` with the owner as ObjPtr, and `TGActionManager.ProcessEvent` routes it to `owner.Completed()`). Use that; add no new engine surface.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_at_move_sequence.py`:

```python
"""AT_MOVE plays the SDK's builder TGSequence instead of mining a clip from it.

MoveFromL1ToP1 (PicardAnimations.py:86) returns a TGSequence that walks the
character, fires LiftDoorAction on "doorl1" 0.125s after the eyes-open action, sets
the end location, and fires CS_STANDING on completion. Extracting only the walk clip
(the old capture_move path) dropped the door, the sound and the events on the floor.

Only the WALK action routes to the walk controller. EyesOpenMouthClosed is also a
character-node TGAnimAction (a 0.1s facial clip) -- and it is the dependency the door
is scheduled off. Routing it to root-motion playback would drive the officer's whole
skeleton from an eyes-and-mouth clip.
"""
import App
from engine.appc.ai import CharacterAction


def _picard_at_the_lift():
    """A character standing at the turbolift with Picard's real move registered
    (mirrors Picard.py:143). Same idiom as tests/unit/test_bridge_registered_clip.py."""
    c = App.CharacterClass_Create(
        "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif",
        "data/Models/Characters/Heads/HeadFelix/felix_head.nif",
    )
    c.SetCharacterName("Picard")
    c.SetLocation("DBL1M")
    c.AddAnimation("DBL1MToP1", "Bridge.Characters.PicardAnimations.MoveFromL1ToP1")
    return c


class _FakeWalkController:
    def __init__(self):
        self.moves = []                 # (character, clip_nif, end_location)
        self._on_complete = None

    def request_move(self, character, clip_nif, end_location, on_complete):
        self.moves.append((character, clip_nif, end_location))
        self._on_complete = on_complete

    def finish(self):
        self._on_complete()


class _RecordingCutscene:
    """Stands in for BridgeCutsceneController: records the door clip NAMES that the
    builder's LiftDoorAction plays on the bridge (object) anim node."""
    def __init__(self):
        self.doors = []                 # clip names

    def request_object_anim(self, action, anim_node, clip_name):
        self.doors.append(str(clip_name))
        action.Completed()              # fire-and-forget, as the real door does

    def request_camera_path(self, action, anim_node, clip_name):
        action.Completed()


def test_at_move_plays_the_builder_sequence_so_the_door_fires(monkeypatch):
    """The builder's LiftDoorAction must actually be played, not dropped."""
    walk, cutscene = _FakeWalkController(), _RecordingCutscene()
    monkeypatch.setattr("engine.bridge_character_walk.get_controller", lambda: walk)
    monkeypatch.setattr("engine.bridge_cutscene.get_controller", lambda: cutscene)

    act = App.CharacterAction_Create(
        _picard_at_the_lift(), CharacterAction.AT_MOVE, "P1")
    act.Play()

    assert walk.moves, "the walk action must reach the walk controller"
    assert "doorl1" in cutscene.doors, \
        "the builder's LiftDoorAction must be played, not dropped"


def test_only_the_walk_action_routes_to_the_walk_controller(monkeypatch):
    """EyesOpenMouthClosed is ALSO a character-node TGAnimAction (a 0.1s facial clip).
    It must NOT be driven as a root-motion body clip."""
    walk, cutscene = _FakeWalkController(), _RecordingCutscene()
    monkeypatch.setattr("engine.bridge_character_walk.get_controller", lambda: walk)
    monkeypatch.setattr("engine.bridge_cutscene.get_controller", lambda: cutscene)

    act = App.CharacterAction_Create(
        _picard_at_the_lift(), CharacterAction.AT_MOVE, "P1")
    act.Play()

    assert len(walk.moves) == 1, "exactly one action is the walk: the marked one"
    clip_nif = walk.moves[0][1]
    assert "db_L1toP_P" in clip_nif                     # the walk clip
    assert "eyes_open_mouth_close" not in clip_nif      # not the facial clip


def test_at_move_completes_exactly_once_when_the_sequence_finishes(monkeypatch):
    walk, cutscene = _FakeWalkController(), _RecordingCutscene()
    monkeypatch.setattr("engine.bridge_character_walk.get_controller", lambda: walk)
    monkeypatch.setattr("engine.bridge_cutscene.get_controller", lambda: cutscene)

    act = App.CharacterAction_Create(
        _picard_at_the_lift(), CharacterAction.AT_MOVE, "P1")
    completions = []
    real_completed = act.Completed

    def counting_completed():
        completions.append(1)
        real_completed()

    act.Completed = counting_completed
    act.Play()
    walk.finish()                      # the walk clip settles -> sequence completes

    assert len(completions) == 1, "zero completions hangs the mission; two double-advance it"


def test_unresolvable_builder_completes_inline(monkeypatch):
    """No registered <location>To<detail> builder -> complete, never stall."""
    monkeypatch.setattr("engine.bridge_character_walk.get_controller",
                        lambda: _FakeWalkController())
    act = App.CharacterAction_Create(
        _picard_at_the_lift(), CharacterAction.AT_MOVE, "NoSuchMark")
    act.Play()
    assert act.IsPlaying() == 0


def test_headless_no_walk_controller_still_completes(monkeypatch):
    """No renderer/controller (the harness + most of the suite) -> never stall."""
    monkeypatch.setattr("engine.bridge_character_walk.get_controller", lambda: None)
    monkeypatch.setattr("engine.bridge_cutscene.get_controller", lambda: None)
    act = App.CharacterAction_Create(
        _picard_at_the_lift(), CharacterAction.AT_MOVE, "P1")
    act.Play()
    assert act.IsPlaying() == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_at_move_sequence.py -v`
Expected: FAIL — the door name never appears in `played` (today `capture_move` drops the `LiftDoorAction`).

- [ ] **Step 3: Mark the walk action and route only it**

In `engine/appc/actions.py`, `TGAnimAction`:

```python
    def __init__(self, anim_node=None, clip_name=""):
        super().__init__()
        self._anim_node = anim_node
        self._clip = str(clip_name)
        self._deferred = False
        # Set by AT_MOVE on the ONE action in a move builder that is the walk (the
        # last character-node action). Only a marked action plays as a root-motion
        # body clip. Every other character-node TGAnimAction in these builders is a
        # facial/idle clip -- EyesOpenMouthClosed, Twitch -- which we do not play at
        # all, and which the door's schedule depends on completing promptly.
        self._walk_move = False

    def _do_play(self) -> None:
        kind = getattr(self._anim_node, "kind", None)
        if kind not in ("camera", "object"):
            if not self._walk_move:
                return                     # facial/gesture clip: instant-complete
            from engine.bridge_character_walk import get_controller as walk_ctrl
            ctrl = walk_ctrl()
            character = getattr(self._anim_node, "owner", None)
            if ctrl is None or character is None:
                return                     # headless: instant-complete, never stall
            from engine.appc.bridge_placement import _nif_path_for_clip
            clip_nif = _nif_path_for_clip(self._clip)
            if not clip_nif:
                return
            # end_location=None: the builder's own trailing AT_SET_LOCATION_NAME
            # sets it (that is the SDK's mechanism; do not duplicate it here).
            ctrl.request_move(character, clip_nif, None, self.Completed)
            self._deferred = True
            return
        from engine.bridge_cutscene import get_controller
        ctrl = get_controller()
        if ctrl is None:
            return
        if kind == "camera":
            ctrl.request_camera_path(self, self._anim_node, self._clip)
        else:
            ctrl.request_object_anim(self, self._anim_node, self._clip)
        self._deferred = True
```

In `engine/appc/bridge_placement.py`, add the walk-action finder (it is the same rule
`capture_move` already used — the LAST action targeting the character anim node):

```python
def walk_action_of(seq):
    """The builder sequence's WALK action: the last action targeting the CHARACTER
    anim node. A move builder also carries set/door actions, and its FIRST
    character-node action is EyesOpenMouthClosed (a facial clip), never the walk."""
    for i in range(seq.GetNumActions() - 1, -1, -1):
        a = seq.GetAction(i)
        if getattr(getattr(a, "_anim_node", None), "kind", None) == "character":
            return a
    return None
```

- [ ] **Step 4: Play the sequence from `AT_MOVE`**

In `engine/appc/ai.py`, replace `_queue_move`:

```python
    def _queue_move(self) -> None:
        """Play the SDK's registered move builder, exactly as BC does.

        The builder's TGSequence carries everything: the walk clip, the
        LiftDoorAction at its scheduled offset (with the door sound), the trailing
        AT_SET_LOCATION_NAME, and the CS_STANDING / CS_SEATED / CS_HIDDEN completion
        event. Mining a single clip out of it -- the old capture_move path -- dropped
        the door, the sound and the events on the floor.

        Best-effort throughout: an unresolved builder, a missing controller (headless)
        or any exception completes the action inline, so a mission TGSequence can
        never stall on a move.
        """
        from engine.appc import bridge_placement
        from engine.appc.characters import CharacterClass_Cast
        try:
            cc = CharacterClass_Cast(self._character) if self._character is not None else None
            seq = (bridge_placement._resolve_builder_sequence(cc, "To" + str(self._detail))
                   if cc is not None else None)
            if seq is None:
                self.Completed()          # nothing registered -> advance immediately
                return

            walk = bridge_placement.walk_action_of(seq)
            if walk is not None:
                walk._walk_move = True    # the ONE action that plays as a body clip

            # Defer our completion to the sequence's, via the SDK's own route:
            # TGActionManager.ProcessEvent calls owner.Completed() for an
            # ET_ACTION_COMPLETED whose ObjPtr is the owner (actions.py:730) --
            # the same mechanism ViewscreenOn and PlayDialog use.
            import App
            ev = App.TGObjPtrEvent_Create()
            ev.SetEventType(App.ET_ACTION_COMPLETED)
            ev.SetDestination(App.g_kTGActionManager)
            ev.SetObjPtr(self)
            seq.AddCompletedEvent(ev)

            seq.Play()
        except Exception:
            self.Completed()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_at_move_sequence.py tests/host/test_bridge_doors.py -v`
Expected: all pass.

- [ ] **Step 6: Run the walk-on regression tests**

Run: `uv run pytest tests/ -k "walk or move or character_anim or placement" -v`
Expected: all pass. The E1M1 walk-on must still work — this task rewires *how* the walk starts, not what it does. If `capture_move` is now unused, delete it and its tests in this commit (do not leave an orphan).

- [ ] **Step 7: Commit**

```bash
git add engine/appc/ai.py engine/appc/actions.py engine/appc/bridge_placement.py \
        tests/unit/test_at_move_sequence.py
git commit -m "feat(bridge): AT_MOVE plays the SDK builder sequence (door, sound, events)"
```

---

### Task 7: Full gate + GUI verification

- [ ] **Step 1: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. The only failures allowed are the 7 headless-GL scorch/heat-glow `FrameTest`s already in `tests/known_failures.txt`. **Any other failure is a regression this branch introduced** — fix it, do not rationalise it. If a baselined test now passes, delete its line from the ledger.

- [ ] **Step 2: GUI verify (hand to the user — do not attempt to drive the desktop)**

Report these checks for the user to run:

1. **E1M1 opening walk-on** — lift 1's door opens **once**, the **other five door pairs do not move**, the chairs do not move, and the door is **audible**.
2. **A crew walk-off to the turbolift** — the door opens on time (not before the sequence starts) and the officer **disappears** into the lift rather than standing in it.
3. **A turn-to-captain overlapping a door cycle** — both animate; neither is cut short.

- [ ] **Step 3: Commit any fixes, then finish the branch**

Use `superpowers:finishing-a-development-branch`.

---

## Notes for the implementer

- **`_nif_path_for_clip(clip_name)`** already exists at `engine/appc/bridge_placement.py:106` (it is what `capture_move` uses) and maps an animation name to its NIF path through `AnimationManager`. Use it; do not write a second one.
- **The `_clip` trap.** `getattr(action, "_clip", "")` on a `CharacterAction` never returns the default: `TGObject.__getattr__` hands back a truthy `_Stub` for any missing attribute, so `or`-fallbacks after it are dead code. `TGAnimAction` *does* have `_clip`; `CharacterAction` does **not** (it has `_detail`). Do not copy that idiom.
- **BC double-drives E1M1's L1 door by design** — the camera walk-on sequence fires `LiftDoorAction(pBridge, "DB_Door_L1")` and Picard's builder fires `LiftDoorAction(pBridge, "doorl1")`, the same physical door under two registered names. Do not "fix" this by suppressing one. Task 1's path-keyed restart is what makes it benign.
