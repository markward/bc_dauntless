# Hull Damage Tessellation — Plan 2: Crater Data Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the per-ship hull-deformation crater store — a `HullCraterField` (merge-accumulate-evict, body frame), an `Instance` member to hold it, and a `hull_deform_add` / `hull_deform_crater_count` host binding pair that converts world-space hits into body-frame, model-unit craters.

**Architecture:** A pure data layer, modelled closely on the existing `DamageDecalRing` but distinct: craters are persistent (no aging/tick) and accumulate `depth` on re-hit; they store an impact direction; and they have no weapon class (deformation is class-agnostic). The C++ field holds all the logic and is unit-tested without a GL context. A thin pybind binding reuses the proven `world_to_body` / `world_dir_to_body` / GU→model-scale conversion from `damage_decal_add`. No rendering, no Python game-logic wiring (that is Plans 4–6).

**Tech Stack:** C++20, GLM, GoogleTest (`scenegraph_tests`, no GL needed), pybind11 (`_dauntless_host`), Python wrapper in `engine/renderer.py`, pytest.

**Spec:** `docs/superpowers/specs/2026-06-16-hull-damage-tessellation-design.md` — §Architecture.1 (data model — `HullCraterField`), §Architecture.6 (data flow — `hull_deform_add` binding), §9 (runtime-only, POD/serialization-friendly).

**Branch:** create `feat/hull-damage-craters` off `main` (Plan 1 is already merged to `main`).

---

## Key facts for the implementer (you have zero context — read these)

- This is the bc_dauntless project, an open C++ reimplementation of Star Trek: Bridge Commander. There is **one** build tree at the project root. Always: `cmake -B build -S . && cmake --build build -j` from `/Users/mward/Documents/Projects/bc_dauntless`. **NEVER** run cmake inside `native/`.
- **Body frame / column-vector convention** (project CLAUDE.md): a ship's world transform `R`/`world` is column-vector; a world point maps to body frame via `inverse(world) * p`. Helpers already exist (do not reimplement): `scenegraph::world_to_body(world, p)` and `scenegraph::world_dir_to_body(world, dir)` in `native/src/scenegraph/src/damage_decals.cc`.
- **Game units (GU) vs model units:** gameplay positions/radii are in GU. The renderer/mesh lives in model units. The per-instance scale `s = length(world[0])` (the X-column magnitude) converts GU→model via division. The existing `damage_decal_add` binding does exactly this — mirror it.
- **The existing `DamageDecalRing`** (`native/src/scenegraph/include/scenegraph/damage_decals.h` + `src/damage_decals.cc`) is the template to follow for style, but craters differ deliberately:
  - **No `weapon_class`** — any two co-located craters merge.
  - **No `birth_time` / no `tick()`** — craters are persistent; nothing reclaims them.
  - **`depth` accumulates** on merge (capped); decals' `intensity` also accumulates, so the merge shape is familiar.
  - **Eviction is shallowest-oldest** (not pure FIFO): a deep crater outranks a shallow old one.
  - **Stores `impact_dir_body`** (decals do not).
- **`kind` is NOT stored.** The spec derives dent-vs-gouge at shade time from `depth` vs a rupture threshold (Plan 5). Do not add a `kind` field.
- **Tests:** `scenegraph_tests` (GoogleTest) run with no GL context — pure logic. Register new test files in `native/tests/scenegraph/CMakeLists.txt`'s `add_executable(scenegraph_tests ...)` list. The `_dauntless_host` pybind module is built to `build/python/` and `tests/conftest.py` makes it importable for pytest.
- **`host_bindings.cc` compiles into BOTH `build/dauntless` and the `_dauntless_host` module** (project memory). After editing it, rebuild with `cmake --build build -j` (default target) so both artifacts refresh — rebuilding only the module leaves the binary stale, and vice-versa.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `native/src/scenegraph/include/scenegraph/hull_craters.h` | `HullCrater` POD + `HullCraterField` class (capacity, merge/accumulate/evict API) | Create |
| `native/src/scenegraph/src/hull_craters.cc` | `HullCraterField::add` / `count` implementation | Create |
| `native/src/scenegraph/CMakeLists.txt` | Add `src/hull_craters.cc` to the `scenegraph` library | Modify |
| `native/src/scenegraph/include/scenegraph/instance.h` | Add a `HullCraterField craters;` member to `Instance` | Modify |
| `native/tests/scenegraph/hull_craters_test.cc` | Unit tests for the field (no GL) | Create |
| `native/tests/scenegraph/CMakeLists.txt` | Register the test file | Modify |
| `native/src/host/host_bindings.cc` | `hull_deform_add` + `hull_deform_crater_count` bindings | Modify |
| `engine/renderer.py` | `hull_deform_add` / `hull_deform_crater_count` Python wrappers (getattr-guarded) | Modify |
| `tests/unit/test_hull_deform_binding.py` | Test the Python wrappers forward/guard correctly | Create |

---

## Task 1: `HullCraterField` skeleton + allocate-one + depth clamp

**Files:**
- Create: `native/src/scenegraph/include/scenegraph/hull_craters.h`
- Create: `native/src/scenegraph/src/hull_craters.cc`
- Modify: `native/src/scenegraph/CMakeLists.txt`
- Test: `native/tests/scenegraph/hull_craters_test.cc`
- Modify: `native/tests/scenegraph/CMakeLists.txt`

- [ ] **Step 1: Write the failing test**

Create `native/tests/scenegraph/hull_craters_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include "scenegraph/hull_craters.h"

using scenegraph::HullCrater;
using scenegraph::HullCraterField;

namespace {
const HullCrater* first_active(const HullCraterField& f) {
    for (const auto& c : f.slots()) if (c.active) return &c;
    return nullptr;
}
}  // namespace

TEST(HullCraterField, AddCreatesOneActiveCrater) {
    HullCraterField f;
    f.add(/*point*/{1, 2, 3}, /*dir*/{0, 0, -1}, /*normal*/{0, 0, 1},
          /*radius*/0.2f, /*depth*/0.3f);
    EXPECT_EQ(f.count(), 1u);
    const HullCrater* c = first_active(f);
    ASSERT_NE(c, nullptr);
    EXPECT_FLOAT_EQ(c->point_body.x, 1.0f);
    EXPECT_FLOAT_EQ(c->impact_dir_body.z, -1.0f);
    EXPECT_FLOAT_EQ(c->normal_body.z, 1.0f);
    EXPECT_FLOAT_EQ(c->radius, 0.2f);
    EXPECT_FLOAT_EQ(c->depth, 0.3f);
}

TEST(HullCraterField, DepthClampsToMaxAndFloorsAtZero) {
    HullCraterField f;
    f.add({0, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 999.0f);
    EXPECT_FLOAT_EQ(first_active(f)->depth, HullCraterField::kMaxDepth);

    HullCraterField g;
    g.add({0, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, -5.0f);
    EXPECT_FLOAT_EQ(first_active(g)->depth, 0.0f);
}
```

Register it in `native/tests/scenegraph/CMakeLists.txt` by adding `hull_craters_test.cc` to the `add_executable(scenegraph_tests ...)` source list (after `damage_decals_test.cc`).

- [ ] **Step 2: Run the test to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j --target scenegraph_tests`
Expected: FAIL to compile — `scenegraph/hull_craters.h` not found.

- [ ] **Step 3: Create the header**

Create `native/src/scenegraph/include/scenegraph/hull_craters.h`:

```cpp
// native/src/scenegraph/include/scenegraph/hull_craters.h
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <glm/glm.hpp>

namespace scenegraph {

/// One persistent hull-deformation crater, stored in the ship's body frame so
/// it tracks the hull as the ship moves. POD and self-contained: a future save
/// implementation can serialize the slot array directly (spec §9). Unlike a
/// damage decal, a crater has no weapon class and no birth time — it never ages
/// out; it only deepens when the same region is hit again. `kind` (dent vs
/// gouge) is NOT stored: it is derived at shade time from `depth` (spec).
struct HullCrater {
    glm::vec3     point_body{0.0f};       // impact location, body frame, model units
    glm::vec3     impact_dir_body{0.0f};  // unit impact/shove direction, body frame
    glm::vec3     normal_body{0.0f};      // outward surface normal, body frame
    float         radius = 0.0f;          // crater radius, model units
    float         depth = 0.0f;           // accumulated displacement depth, model units
    std::uint64_t seq = 0;                // insertion order (0 = never used)
    bool          active = false;
};

/// Fixed-capacity per-instance crater store: merge-accumulate-then-evict.
class HullCraterField {
public:
    static constexpr std::size_t kMaxCraters = 24;
    static constexpr float kMergeFactor = 0.5f;  // merge within 0.5 * radius
    /// Maximum accumulated depth (model units). Default cap; tuned in Plan 4
    /// against visual results. Caps runaway deepening from repeated hits.
    static constexpr float kMaxDepth = 1.0f;

    /// Insert a crater (point/dir/normal already in body frame, radius/depth in
    /// model units). If an active crater lies within kMergeFactor*radius, deepen
    /// it (accumulation, capped at kMaxDepth) and refresh its direction/normal/
    /// age instead of allocating. Otherwise take a free slot, else evict the
    /// shallowest crater (tie-break: oldest). `depth` is clamped to
    /// [0, kMaxDepth]; negative input floors to 0.
    void add(const glm::vec3& point_body, const glm::vec3& impact_dir_body,
             const glm::vec3& normal_body, float radius, float depth);

    std::size_t count() const;  // number of active craters
    const std::array<HullCrater, kMaxCraters>& slots() const { return slots_; }

private:
    std::array<HullCrater, kMaxCraters> slots_{};
    std::uint64_t next_seq_ = 1;
};

}  // namespace scenegraph
```

- [ ] **Step 4: Create the implementation (allocate-only; merge & evict added later)**

Create `native/src/scenegraph/src/hull_craters.cc`:

```cpp
// native/src/scenegraph/src/hull_craters.cc
#include "scenegraph/hull_craters.h"

#include <algorithm>

namespace scenegraph {

void HullCraterField::add(const glm::vec3& point_body,
                          const glm::vec3& impact_dir_body,
                          const glm::vec3& normal_body,
                          float radius, float depth) {
    const float clamped_depth = std::clamp(depth, 0.0f, kMaxDepth);

    // Allocate the first free slot. (Merge and eviction are added in later
    // tasks; for now an over-full field silently drops the crater.)
    HullCrater* target = nullptr;
    for (auto& c : slots_) {
        if (!c.active) { target = &c; break; }
    }
    if (target == nullptr) return;

    *target = HullCrater{
        point_body, impact_dir_body, normal_body,
        radius, clamped_depth, next_seq_++, /*active=*/true,
    };
}

std::size_t HullCraterField::count() const {
    std::size_t n = 0;
    for (const auto& c : slots_) if (c.active) ++n;
    return n;
}

}  // namespace scenegraph
```

- [ ] **Step 5: Add `hull_craters.cc` to the scenegraph library**

In `native/src/scenegraph/CMakeLists.txt`, add `src/hull_craters.cc` to the `add_library(scenegraph STATIC ...)` source list (after `src/damage_decals.cc`).

- [ ] **Step 6: Build and run the test to verify it passes**

Run: `cmake -B build -S . && cmake --build build -j --target scenegraph_tests && ctest --test-dir build -R HullCraterField --output-on-failure`
Expected: both tests PASS.

- [ ] **Step 7: Commit**

```bash
git add native/src/scenegraph/include/scenegraph/hull_craters.h \
        native/src/scenegraph/src/hull_craters.cc \
        native/src/scenegraph/CMakeLists.txt \
        native/tests/scenegraph/hull_craters_test.cc \
        native/tests/scenegraph/CMakeLists.txt
git commit -m "feat(scenegraph): add HullCraterField skeleton (allocate + depth clamp)"
```

---

## Task 2: Merge & accumulate on co-located hits

**Files:**
- Modify: `native/src/scenegraph/src/hull_craters.cc`
- Test: `native/tests/scenegraph/hull_craters_test.cc` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `native/tests/scenegraph/hull_craters_test.cc`:

```cpp
TEST(HullCraterField, CoLocatedHitDeepensExistingCrater) {
    HullCraterField f;
    f.add({0, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.3f);
    // 0.05 < 0.5 * 0.2 = 0.1 -> merges into the first crater.
    f.add({0.05f, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.4f);
    EXPECT_EQ(f.count(), 1u);
    EXPECT_FLOAT_EQ(first_active(f)->depth, 0.7f);  // 0.3 + 0.4
}

TEST(HullCraterField, AccumulatedDepthClampsToMax) {
    HullCraterField f;
    f.add({0, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.8f);
    f.add({0.0f, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.8f);  // 1.6 -> caps at 1.0
    EXPECT_EQ(f.count(), 1u);
    EXPECT_FLOAT_EQ(first_active(f)->depth, HullCraterField::kMaxDepth);
}

TEST(HullCraterField, MergeGrowsRadiusAndRefreshesDirection) {
    HullCraterField f;
    f.add({0, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.3f);
    f.add({0.0f, 0, 0}, {1, 0, 0}, {0, 1, 0}, 0.5f, 0.1f);  // bigger radius, new dir/normal
    const HullCrater* c = first_active(f);
    EXPECT_FLOAT_EQ(c->radius, 0.5f);             // grew to max
    EXPECT_FLOAT_EQ(c->impact_dir_body.x, 1.0f);  // freshest direction
    EXPECT_FLOAT_EQ(c->normal_body.y, 1.0f);      // freshest normal
}

TEST(HullCraterField, DistantHitAllocatesSecondCrater) {
    HullCraterField f;
    f.add({0, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.3f);
    f.add({5, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.3f);  // far -> separate
    EXPECT_EQ(f.count(), 2u);
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cmake --build build -j --target scenegraph_tests && ctest --test-dir build -R HullCraterField --output-on-failure`
Expected: `CoLocatedHitDeepensExistingCrater`, `AccumulatedDepthClampsToMax`, `MergeGrowsRadiusAndRefreshesDirection` FAIL (the allocate-only impl creates a 2nd crater / never deepens); `DistantHitAllocatesSecondCrater` already passes.

- [ ] **Step 3: Add the merge branch to `add`**

In `native/src/scenegraph/src/hull_craters.cc`, replace the body of `HullCraterField::add` with the version below (adds the merge scan before allocation):

```cpp
void HullCraterField::add(const glm::vec3& point_body,
                          const glm::vec3& impact_dir_body,
                          const glm::vec3& normal_body,
                          float radius, float depth) {
    const float clamped_depth = std::clamp(depth, 0.0f, kMaxDepth);

    // 1. Merge into a co-located crater: deepen it (accumulation). Deformation
    //    is weapon-class-agnostic, so any active crater in range is a merge
    //    target — a torpedo, a phaser, or a collision all cave the same spot.
    const float merge_dist = kMergeFactor * radius;
    for (auto& c : slots_) {
        if (!c.active) continue;
        if (glm::length(point_body - c.point_body) <= merge_dist) {
            c.depth = std::min(kMaxDepth, c.depth + clamped_depth);
            c.radius = std::max(c.radius, radius);   // a wider re-hit grows it
            c.impact_dir_body = impact_dir_body;     // freshest shove direction
            c.normal_body = normal_body;             // freshest surface normal
            c.seq = next_seq_++;                     // refresh age (a reinforced
                                                     // crater survives eviction)
            return;
        }
    }

    // 2. Allocate the first free slot. (Eviction is added in the next task; an
    //    over-full field silently drops the crater for now.)
    HullCrater* target = nullptr;
    for (auto& c : slots_) {
        if (!c.active) { target = &c; break; }
    }
    if (target == nullptr) return;

    *target = HullCrater{
        point_body, impact_dir_body, normal_body,
        radius, clamped_depth, next_seq_++, /*active=*/true,
    };
}
```

- [ ] **Step 4: Run to verify all pass**

Run: `cmake --build build -j --target scenegraph_tests && ctest --test-dir build -R HullCraterField --output-on-failure`
Expected: all HullCraterField tests PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/scenegraph/src/hull_craters.cc native/tests/scenegraph/hull_craters_test.cc
git commit -m "feat(scenegraph): merge & accumulate co-located hull craters"
```

---

## Task 3: Eviction (shallowest-oldest) when full

**Files:**
- Modify: `native/src/scenegraph/src/hull_craters.cc`
- Test: `native/tests/scenegraph/hull_craters_test.cc` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `native/tests/scenegraph/hull_craters_test.cc`:

```cpp
TEST(HullCraterField, FullFieldEvictsShallowestCrater) {
    HullCraterField f;
    // Fill all slots with distinct, far-apart, deep craters (depth 0.5).
    for (std::size_t i = 0; i < HullCraterField::kMaxCraters; ++i) {
        f.add({static_cast<float>(i) * 10.0f, 0, 0}, {0, 0, -1}, {0, 0, 1},
              0.2f, 0.5f);
    }
    EXPECT_EQ(f.count(), HullCraterField::kMaxCraters);

    // Make slot 0 the shallowest by leaving it at 0.5 and... instead, add one
    // markedly shallow crater by overwriting an existing one is not possible;
    // so: add a NEW far-apart crater. The field is full, so it must evict the
    // shallowest. All existing are 0.5; the new one is deeper (0.9). After
    // eviction the count stays at capacity and a 0.9 crater exists.
    f.add({999.0f, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.9f);
    EXPECT_EQ(f.count(), HullCraterField::kMaxCraters);

    bool found_deep = false;
    for (const auto& c : f.slots()) {
        if (c.active && c.depth > 0.8f) found_deep = true;
    }
    EXPECT_TRUE(found_deep);  // the new deep crater displaced a shallow one
}

TEST(HullCraterField, EvictionPrefersShallowOverOld) {
    HullCraterField f;
    // One shallow OLD crater first (seq smallest), then fill the rest deep.
    f.add({0, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.1f);  // shallow, oldest
    for (std::size_t i = 1; i < HullCraterField::kMaxCraters; ++i) {
        f.add({static_cast<float>(i) * 10.0f, 0, 0}, {0, 0, -1}, {0, 0, 1},
              0.2f, 0.6f);  // deep
    }
    // Field full. New far crater must evict the shallow (0.1) one, not a deep one.
    f.add({999.0f, 0, 0}, {0, 0, -1}, {0, 0, 1}, 0.2f, 0.6f);

    bool shallow_gone = true;
    for (const auto& c : f.slots()) {
        if (c.active && c.depth < 0.2f) shallow_gone = false;
    }
    EXPECT_TRUE(shallow_gone);  // shallow crater was the eviction victim
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cmake --build build -j --target scenegraph_tests && ctest --test-dir build -R HullCraterField --output-on-failure`
Expected: the two new tests FAIL (the over-full field currently drops the new crater, so neither the deep crater appears nor the shallow one is evicted).

- [ ] **Step 3: Replace the drop-on-full with eviction**

In `native/src/scenegraph/src/hull_craters.cc`, replace this block:

```cpp
    HullCrater* target = nullptr;
    for (auto& c : slots_) {
        if (!c.active) { target = &c; break; }
    }
    if (target == nullptr) return;
```

with:

```cpp
    HullCrater* target = nullptr;
    for (auto& c : slots_) {
        if (!c.active) { target = &c; break; }
    }
    if (target == nullptr) {
        // Evict the shallowest crater; tie-break on oldest (smallest seq). A
        // deep crater is more visually important than a shallow old one, so
        // depth dominates the victim choice (differs from the decal ring's
        // pure-FIFO eviction).
        HullCrater* victim = &slots_[0];
        for (auto& c : slots_) {
            if (c.depth < victim->depth ||
                (c.depth == victim->depth && c.seq < victim->seq)) {
                victim = &c;
            }
        }
        target = victim;
    }
```

(The `*target = HullCrater{...}` assignment below it is unchanged.)

- [ ] **Step 4: Run to verify all pass**

Run: `cmake --build build -j --target scenegraph_tests && ctest --test-dir build -R HullCraterField --output-on-failure`
Expected: all HullCraterField tests PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/scenegraph/src/hull_craters.cc native/tests/scenegraph/hull_craters_test.cc
git commit -m "feat(scenegraph): evict shallowest-oldest crater when field is full"
```

---

## Task 4: Add the crater field to `Instance`

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h`
- Test: `native/tests/scenegraph/hull_craters_test.cc` (append one test)

- [ ] **Step 1: Write the failing test**

Append to `native/tests/scenegraph/hull_craters_test.cc`. Add `#include "scenegraph/instance.h"` near the top of the file (below the existing `#include "scenegraph/hull_craters.h"`), then:

```cpp
TEST(Instance, HasEmptyCraterFieldByDefault) {
    scenegraph::Instance inst;
    EXPECT_EQ(inst.craters.count(), 0u);
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cmake --build build -j --target scenegraph_tests`
Expected: FAIL to compile — `Instance` has no member `craters`.

- [ ] **Step 3: Add the member**

In `native/src/scenegraph/include/scenegraph/instance.h`:

First, add the include near the top alongside the existing decals include (line 9 is `#include "scenegraph/damage_decals.h"`):

```cpp
#include "scenegraph/hull_craters.h"
```

Then, inside `struct Instance`, directly after the `DamageDecalRing decals;` member (and its comment, around line 63), add:

```cpp
    /// Per-instance persistent hull-deformation craters (object space, body
    /// frame). Runtime VFX state only — never serialized to saves (spec §9).
    HullCraterField craters;
```

- [ ] **Step 4: Run to verify it passes**

Run: `cmake --build build -j --target scenegraph_tests && ctest --test-dir build -R "HullCraterField|Instance" --output-on-failure`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/scenegraph/include/scenegraph/instance.h native/tests/scenegraph/hull_craters_test.cc
git commit -m "feat(scenegraph): add per-instance HullCraterField member"
```

---

## Task 5: Host bindings — `hull_deform_add` + `hull_deform_crater_count`

Add the pybind bindings that turn a world-space hit into a body-frame, model-unit crater (mirroring `damage_decal_add`), plus a count query that Plan 4/6 use to decide whether a ship needs the tessellation path.

**Files:**
- Modify: `native/src/host/host_bindings.cc`

- [ ] **Step 1: Locate the existing `damage_decal_add` binding**

Open `native/src/host/host_bindings.cc` and find the `m.def("damage_decal_add", ...)` block (it transforms world point/normal to body frame and converts radius GU→model via `s = length(world[0])`). The new bindings go directly after it, following the same shape.

- [ ] **Step 2: Add the two bindings**

Insert after the closing `);` of the `damage_decal_add` def:

```cpp
    m.def("hull_deform_add",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> world_point,
             std::tuple<float, float, float> world_normal,
             std::tuple<float, float, float> world_impact_dir,
             float radius, float depth) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;  // stale id — drop silently
              const glm::vec3 pw(std::get<0>(world_point),
                                 std::get<1>(world_point),
                                 std::get<2>(world_point));
              const glm::vec3 nw(std::get<0>(world_normal),
                                 std::get<1>(world_normal),
                                 std::get<2>(world_normal));
              const glm::vec3 dw(std::get<0>(world_impact_dir),
                                 std::get<1>(world_impact_dir),
                                 std::get<2>(world_impact_dir));
              const glm::vec3 pb = scenegraph::world_to_body(inst->world, pw);
              const glm::vec3 nb = scenegraph::world_dir_to_body(inst->world, nw);
              const glm::vec3 db = scenegraph::world_dir_to_body(inst->world, dw);
              // radius and depth are GU lengths; convert to model units (the
              // space pb lives in). s = |world's X column| = NIF->world scale.
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv = (s > 0.0f) ? 1.0f / s : 1.0f;
              inst->craters.add(pb, db, nb, radius * inv, depth * inv);
          },
          py::arg("instance_id"), py::arg("world_point"), py::arg("world_normal"),
          py::arg("world_impact_dir"), py::arg("radius"), py::arg("depth"),
          "Record a persistent hull-deformation crater on a ship instance. "
          "World-space point/normal/impact-direction are transformed into the "
          "ship body frame; radius and depth (game units) are converted to model "
          "units. Re-hitting a region deepens an existing crater.");

    m.def("hull_deform_crater_count",
          [](scenegraph::InstanceId id) -> int {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return 0;  // stale id -> no craters
              return static_cast<int>(inst->craters.count());
          },
          py::arg("instance_id"),
          "Number of active hull-deformation craters on an instance (0 for a "
          "stale id). Used to decide whether a ship needs the tessellation path.");
```

- [ ] **Step 3: Build BOTH artifacts (binary + module)**

`host_bindings.cc` compiles into both `build/dauntless` and the `_dauntless_host` Python module. Build the default target so both refresh:

Run: `cmake -B build -S . && cmake --build build -j`
Expected: clean build of `_dauntless_host` and `dauntless`.

- [ ] **Step 4: Smoke-check the bindings exist in the module**

Run:
```bash
PYTHONPATH=build/python python3 -c "import _dauntless_host as h; print(hasattr(h,'hull_deform_add'), hasattr(h,'hull_deform_crater_count'), h.hull_deform_crater_count(h.InstanceId()))"
```
Expected: `True True 0` — both bindings are present and `hull_deform_crater_count` on a default (stale) `InstanceId` returns 0 without throwing.

(If `import _dauntless_host` fails in your shell because the module needs the repo's import shims, instead rely on the pytest in Task 6, which uses `tests/conftest.py` to make the module importable. In that case note it and proceed — Step 3's clean build is the binding's compile-time guarantee.)

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(host): add hull_deform_add and hull_deform_crater_count bindings"
```

---

## Task 6: Python wrappers + wrapper test

Expose the bindings through `engine/renderer.py` (the Pythonic wrapper layer) with the getattr-guard pattern used for optional bindings, so callers degrade gracefully if the binding is absent (stale `.so`). Test the wrapper contract without needing a GL context or a real instance.

**Files:**
- Modify: `engine/renderer.py`
- Test: `tests/unit/test_hull_deform_binding.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_hull_deform_binding.py`:

```python
"""engine.renderer wrappers for hull deformation must forward to the native
binding when present and no-op / return 0 when it is absent."""
import types

from engine import renderer


class _RecordingHost:
    def __init__(self):
        self.add_calls = []
        self.count_return = 7

    def hull_deform_add(self, iid, world_point, world_normal,
                        world_impact_dir, radius, depth):
        self.add_calls.append(
            (iid, world_point, world_normal, world_impact_dir, radius, depth))

    def hull_deform_crater_count(self, iid):
        return self.count_return


def test_hull_deform_add_forwards_to_binding(monkeypatch):
    host = _RecordingHost()
    monkeypatch.setattr(renderer, "_h", host)
    renderer.hull_deform_add(
        iid="IID", world_point=(1, 2, 3), world_normal=(0, 0, 1),
        world_impact_dir=(0, 0, -1), radius=0.2, depth=0.3)
    assert host.add_calls == [
        ("IID", (1, 2, 3), (0, 0, 1), (0, 0, -1), 0.2, 0.3)]


def test_hull_deform_crater_count_forwards(monkeypatch):
    host = _RecordingHost()
    monkeypatch.setattr(renderer, "_h", host)
    assert renderer.hull_deform_crater_count("IID") == 7


def test_wrappers_noop_when_binding_absent(monkeypatch):
    # A host module without the bindings (e.g. a stale .so) must not raise.
    empty = types.SimpleNamespace()
    monkeypatch.setattr(renderer, "_h", empty)
    renderer.hull_deform_add(
        iid="IID", world_point=(0, 0, 0), world_normal=(0, 0, 1),
        world_impact_dir=(0, 0, -1), radius=0.1, depth=0.1)  # no raise
    assert renderer.hull_deform_crater_count("IID") == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_hull_deform_binding.py -v`
Expected: FAIL — `renderer` has no attribute `hull_deform_add` / `hull_deform_crater_count`.

- [ ] **Step 3: Add the wrappers**

In `engine/renderer.py`, add these functions (place them after the `damage_decals_tick` wrapper around line 106-113, following the `getattr(_h, name, None)` guard style already used by `spawn_test_character`):

```python
def hull_deform_add(*, iid: InstanceId,
                    world_point: Tuple[float, float, float],
                    world_normal: Tuple[float, float, float],
                    world_impact_dir: Tuple[float, float, float],
                    radius: float, depth: float) -> None:
    """Record a persistent hull-deformation crater on a ship instance.

    World-space point/normal/impact-direction are transformed to the ship
    body frame natively; radius and depth are game units. No-ops if the
    native binding is absent (e.g. a stale extension module)."""
    fn = getattr(_h, "hull_deform_add", None)
    if fn is not None:
        fn(iid, world_point, world_normal, world_impact_dir, radius, depth)


def hull_deform_crater_count(iid: InstanceId) -> int:
    """Number of active hull-deformation craters on an instance (0 if the
    binding is absent or the id is stale)."""
    fn = getattr(_h, "hull_deform_crater_count", None)
    return fn(iid) if fn is not None else 0
```

Note: the test calls `hull_deform_add` with keyword arguments and the `_RecordingHost.hull_deform_add` takes positionals — the wrapper forwards positionally to `fn(...)`, which matches both the recording stub and the native binding's `py::arg` order. Keep the wrapper's own parameters keyword-only (`*,`) as shown.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/unit/test_hull_deform_binding.py -v`
Expected: all three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/renderer.py tests/unit/test_hull_deform_binding.py
git commit -m "feat(renderer): add hull_deform_add/crater_count Python wrappers"
```

---

## Self-Review

**Spec coverage (Plan 2 scope = spec §Architecture.1 data model, §Architecture.6 binding, §9 persistence-friendliness):**
- §1 crater record fields `point_body, impact_dir_body, normal_body, radius, depth, seq` → Task 1 `HullCrater`. ✓ (`kind` deliberately NOT stored — derived at shade time, Plan 5.)
- §1 "re-hit deepens an existing crater (accumulation)" / "single big impact deposits deep crater" → Task 2 merge-accumulate. ✓
- §1 "bounded array (~16–24); evict shallowest-oldest" → `kMaxCraters = 24`, Task 3 eviction. ✓
- §1 "merge regardless of weapon class" → no `weapon_class` field; Task 2 merges any in-range crater. ✓
- §1 "persistent (no transient reclaim)" → no `tick()`/`birth_time`. ✓
- §1 `Instance` member → Task 4. ✓
- §6 `hull_deform_add(world_point, world_normal, world_impact_dir, radius, depth)` with world→body transform + GU→model radius (and depth) → Task 5. ✓
- §4 "crater-count gates the displacement path" dependency → `hull_deform_crater_count` (Task 5) provided for Plan 4/6. ✓
- §9 runtime-only, POD/serialization-friendly → `HullCrater` is POD, documented; no serialization added. ✓
- Displacement shaders, thickness bake, eligibility, hit_feedback dispatch, depth/kind Python mapping → **Plans 3–6 by design**, not Plan 2 gaps.

**Placeholder scan:** No TBD/TODO. `kMaxDepth = 1.0f` is a documented default with explicit "tuned in Plan 4" note (a real value, not a placeholder). The Task 5 Step 4 fallback ("if import fails in your shell, rely on Task 6 pytest") names the concrete alternative rather than hand-waving.

**Type consistency:** `HullCrater` field names (`point_body`, `impact_dir_body`, `normal_body`, `radius`, `depth`, `seq`, `active`) are identical across the header (Task 1), the aggregate-init in `add` (Tasks 1–3), the tests, and the `Instance.craters` usage (Task 4). `HullCraterField::add(point_body, impact_dir_body, normal_body, radius, depth)` signature matches across header, impl, tests, and the binding call `inst->craters.add(pb, db, nb, radius*inv, depth*inv)` (Task 5) — note the binding passes args in (point, dir, normal, radius, depth) order, matching the signature. `hull_deform_add` py::arg order (instance_id, world_point, world_normal, world_impact_dir, radius, depth) matches the renderer.py wrapper's positional forwarding and the test's recording stub. `kMaxCraters`, `kMergeFactor`, `kMaxDepth` referenced consistently. ✓

---

## What comes next (not this plan)

- **Plan 3:** offline thickness bake → per-vertex crushability attribute + sidecar cache.
- **Plan 4:** displacement pipeline (adaptive TCS, TES displacement from the crater field + normal recompute, crater uniform upload, `frame.cc` patch draw path gated on `query_gl_caps().tessellation_available` and `hull_deform_crater_count > 0`).
- **Plan 5:** dent/gouge FS shading (triplanar `Damage.tga` + procedural) + Modern VFX config toggles.
- **Plan 6:** eligibility manager + `engine/appc/hull_deformation.py` (GU depth/kind mapping) + `hit_feedback` dispatch hook calling `renderer.hull_deform_add`.
