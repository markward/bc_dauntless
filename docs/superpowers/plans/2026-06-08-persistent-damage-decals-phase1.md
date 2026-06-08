# Persistent Damage Decals — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the per-instance object-space damage-decal store and wire weapon hits into it, with the shield-gating fix — no shader rendering yet.

**Architecture:** A pure C++ `DamageDecalRing` (24-slot, merge-then-FIFO) lives on each renderer `scenegraph::Instance`. A `host.damage_decal_add` binding transforms world-space hit data into the ship's body frame and inserts it; `host.damage_decals_tick` ages rings each frame (reclaiming cold phaser glows). On the Python side, `engine/appc/hit_feedback.py:dispatch` emits a decal **only when `absorbed_hull > 0`** (the shield-fix), mapping weapon type → decal class and hull damage → intensity. Nothing reads the ring yet; Phase 2 adds the shader.

**Tech Stack:** C++20, glm, GoogleTest (native unit tests), pybind11 (host bindings), Python + pytest (engine logic). Build tree is the single canonical `build/` (per CLAUDE.md).

**Spec:** [`docs/superpowers/specs/2026-06-08-persistent-damage-decals-design.md`](../specs/2026-06-08-persistent-damage-decals-design.md) — implements §3.1, §3.2 (storage half only), §3.3, §3.4, §3.5, §3.6, §3.7, Phase 1.

---

## File Structure

**New files:**
- `native/src/scenegraph/include/scenegraph/damage_decals.h` — `WeaponClass`, `DamageDecal`, `DamageDecalRing`, `world_to_body` / `world_dir_to_body`. One responsibility: the pure decal-store data model and insertion/aging policy.
- `native/src/scenegraph/src/damage_decals.cc` — implementation.
- `native/tests/scenegraph/damage_decals_test.cc` — GoogleTest for the ring + transforms.
- `engine/appc/damage_decals.py` — pure mappings: `weapon_class_for`, `decal_intensity`, `current_game_time`, class constants. No host dependency.
- `tests/unit/test_damage_decals.py` — tests the mappings.
- `tests/unit/test_decal_emission.py` — tests the `dispatch` emission gate with a fake host.

**Modified files:**
- `native/src/scenegraph/include/scenegraph/instance.h` — add `DamageDecalRing decals;` member.
- `native/src/scenegraph/include/scenegraph/world.h` — add mutable `for_each_alive`.
- `native/src/scenegraph/CMakeLists.txt` — add `src/damage_decals.cc`.
- `native/tests/scenegraph/CMakeLists.txt` — add `damage_decals_test.cc`.
- `native/src/host/host_bindings.cc` — bind `damage_decal_add`, `damage_decals_tick`.
- `engine/appc/hit_feedback.py` — add `radius` kwarg + decal-emission step.
- `engine/appc/combat.py` — pass `radius=r_hit` into the `dispatch` call.
- `engine/host_loop.py` — call `host.damage_decals_tick(game_time)` each tick.

---

## Task 1: DamageDecalRing pure logic (C++)

The core data model and merge-then-FIFO policy, with no GL or pybind dependency so it is unit-testable in isolation.

**Files:**
- Create: `native/src/scenegraph/include/scenegraph/damage_decals.h`
- Create: `native/src/scenegraph/src/damage_decals.cc`
- Modify: `native/src/scenegraph/CMakeLists.txt`
- Create: `native/tests/scenegraph/damage_decals_test.cc`
- Modify: `native/tests/scenegraph/CMakeLists.txt`

- [ ] **Step 1: Write the header**

Create `native/src/scenegraph/include/scenegraph/damage_decals.h`:

```cpp
// native/src/scenegraph/include/scenegraph/damage_decals.h
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <glm/glm.hpp>

namespace scenegraph {

/// Weapon class drives the decal's visual behaviour (Phase 2 shader).
/// - HeatGlow (phaser): transient emissive bloom, reclaimed when cold.
/// - Scorch  (torpedo/disruptor): persistent deposit + blackbody ember.
enum class WeaponClass : std::uint32_t {
    HeatGlow = 0,
    Scorch   = 1,
};

/// One object-space impact record, stored in the ship's body frame so it
/// tracks the hull as the ship moves and rotates.
struct DamageDecal {
    glm::vec3     point_body{0.0f};
    glm::vec3     normal_body{0.0f};
    float         radius = 0.0f;       // r_hit, game units
    float         intensity = 0.0f;    // [0,1], deposit darkness / hole threshold
    float         birth_time = 0.0f;   // seconds (game clock); drives ember cooling
    WeaponClass   weapon_class = WeaponClass::Scorch;
    bool          active = false;
    std::uint64_t seq = 0;             // FIFO insertion order (0 = never used)
};

/// Transform a world-space point into a ship's body frame.
/// Column-vector convention (CLAUDE.md): body = inverse(ship_world) * p.
glm::vec3 world_to_body(const glm::mat4& ship_world, const glm::vec3& p_world);

/// Transform a world-space direction into the ship's body frame and
/// renormalise. Returns the input length-0 vector unchanged.
glm::vec3 world_dir_to_body(const glm::mat4& ship_world, const glm::vec3& dir_world);

/// Fixed-capacity per-instance decal store with merge-then-FIFO insertion.
class DamageDecalRing {
public:
    static constexpr std::size_t kMaxDecals = 24;
    static constexpr float kMergeFactor = 0.5f;       // merge within 0.5 * radius
    static constexpr float kHeatGlowLifetime = 1.2f;  // seconds before reclaim

    /// Insert a decal (point/normal already in body frame).
    /// Merge: if a same-class active decal lies within kMergeFactor*radius,
    /// deepen its intensity and re-ignite its ember instead of allocating.
    /// Otherwise take a free slot, evicting the oldest (smallest seq) if full.
    void add(const glm::vec3& point_body, const glm::vec3& normal_body,
             float radius, float intensity, WeaponClass weapon_class, float now);

    /// Reclaim cold HeatGlow decals (age beyond kHeatGlowLifetime).
    void tick(float now);

    std::size_t count() const;                      // number of active decals
    const std::array<DamageDecal, kMaxDecals>& slots() const { return slots_; }

private:
    std::array<DamageDecal, kMaxDecals> slots_{};
    std::uint64_t next_seq_ = 1;
};

}  // namespace scenegraph
```

- [ ] **Step 2: Write the implementation**

Create `native/src/scenegraph/src/damage_decals.cc`:

```cpp
// native/src/scenegraph/src/damage_decals.cc
#include "scenegraph/damage_decals.h"

#include <algorithm>

namespace scenegraph {

glm::vec3 world_to_body(const glm::mat4& ship_world, const glm::vec3& p_world) {
    return glm::vec3(glm::inverse(ship_world) * glm::vec4(p_world, 1.0f));
}

glm::vec3 world_dir_to_body(const glm::mat4& ship_world, const glm::vec3& dir_world) {
    glm::vec3 b = glm::mat3(glm::inverse(ship_world)) * dir_world;
    float len = glm::length(b);
    return len > 0.0f ? b / len : b;
}

void DamageDecalRing::add(const glm::vec3& point_body, const glm::vec3& normal_body,
                          float radius, float intensity, WeaponClass weapon_class,
                          float now) {
    const float clamped_in = std::clamp(intensity, 0.0f, 1.0f);

    // 1. Merge into a co-located same-class decal.
    const float merge_dist = kMergeFactor * radius;
    for (auto& d : slots_) {
        if (!d.active || d.weapon_class != weapon_class) continue;
        if (glm::length(point_body - d.point_body) <= merge_dist) {
            d.intensity = std::min(1.0f, d.intensity + clamped_in);
            d.birth_time = now;          // re-ignite ember
            d.normal_body = normal_body; // freshest surface normal
            return;
        }
    }

    // 2. Allocate the first free slot, else 3. evict the oldest.
    DamageDecal* target = nullptr;
    for (auto& d : slots_) {
        if (!d.active) { target = &d; break; }
    }
    if (target == nullptr) {
        target = &slots_[0];
        for (auto& d : slots_) {
            if (d.seq < target->seq) target = &d;
        }
    }

    *target = DamageDecal{
        point_body, normal_body, radius, clamped_in,
        now, weapon_class, /*active=*/true, next_seq_++,
    };
}

void DamageDecalRing::tick(float now) {
    for (auto& d : slots_) {
        if (d.active && d.weapon_class == WeaponClass::HeatGlow
            && (now - d.birth_time) > kHeatGlowLifetime) {
            d.active = false;
        }
    }
}

std::size_t DamageDecalRing::count() const {
    std::size_t n = 0;
    for (const auto& d : slots_) if (d.active) ++n;
    return n;
}

}  // namespace scenegraph
```

- [ ] **Step 3: Register the source file in the scenegraph library**

In `native/src/scenegraph/CMakeLists.txt`, change:

```cmake
add_library(scenegraph STATIC
    src/camera.cc
    src/world.cc
)
```

to:

```cmake
add_library(scenegraph STATIC
    src/camera.cc
    src/world.cc
    src/damage_decals.cc
)
```

- [ ] **Step 4: Write the failing test**

Create `native/tests/scenegraph/damage_decals_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include "scenegraph/damage_decals.h"

using scenegraph::DamageDecal;
using scenegraph::DamageDecalRing;
using scenegraph::WeaponClass;

namespace {
const DamageDecal* first_active(const DamageDecalRing& ring) {
    for (const auto& d : ring.slots()) if (d.active) return &d;
    return nullptr;
}
}  // namespace

TEST(DamageDecalRing, AddCreatesOneActiveDecal) {
    DamageDecalRing ring;
    ring.add({1, 2, 3}, {0, 0, 1}, 0.2f, 0.5f, WeaponClass::Scorch, 10.0f);
    EXPECT_EQ(ring.count(), 1u);
    const DamageDecal* d = first_active(ring);
    ASSERT_NE(d, nullptr);
    EXPECT_FLOAT_EQ(d->point_body.x, 1.0f);
    EXPECT_FLOAT_EQ(d->intensity, 0.5f);
    EXPECT_EQ(d->weapon_class, WeaponClass::Scorch);
}

TEST(DamageDecalRing, IntensityClampsToOne) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 5.0f, WeaponClass::Scorch, 0.0f);
    EXPECT_FLOAT_EQ(first_active(ring)->intensity, 1.0f);
}

TEST(DamageDecalRing, CoLocatedSameClassHitsMergeNotAllocate) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 0.4f, WeaponClass::Scorch, 0.0f);
    // 0.05 < 0.5 * 0.2 = 0.1 -> merges
    ring.add({0.05f, 0, 0}, {0, 0, 1}, 0.2f, 0.3f, WeaponClass::Scorch, 1.0f);
    EXPECT_EQ(ring.count(), 1u);
    const DamageDecal* d = first_active(ring);
    EXPECT_FLOAT_EQ(d->intensity, 0.7f);   // 0.4 + 0.3
    EXPECT_FLOAT_EQ(d->birth_time, 1.0f);  // ember re-ignited
}

TEST(DamageDecalRing, DistantHitAllocatesSecondSlot) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 0.4f, WeaponClass::Scorch, 0.0f);
    ring.add({5, 0, 0}, {0, 0, 1}, 0.2f, 0.4f, WeaponClass::Scorch, 0.0f);
    EXPECT_EQ(ring.count(), 2u);
}

TEST(DamageDecalRing, DifferentClassDoesNotMerge) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 0.4f, WeaponClass::Scorch, 0.0f);
    ring.add({0.01f, 0, 0}, {0, 0, 1}, 0.2f, 0.4f, WeaponClass::HeatGlow, 0.0f);
    EXPECT_EQ(ring.count(), 2u);
}

TEST(DamageDecalRing, FullRingEvictsOldest) {
    DamageDecalRing ring;
    // Fill all 24 slots with spatially-distinct scorch decals.
    for (int i = 0; i < 24; ++i) {
        ring.add({static_cast<float>(i) * 10.0f, 0, 0}, {0, 0, 1},
                 0.2f, 0.4f, WeaponClass::Scorch, static_cast<float>(i));
    }
    EXPECT_EQ(ring.count(), 24u);
    // One more distinct hit evicts slot seq=1 (the first, at x=0).
    ring.add({999.0f, 0, 0}, {0, 0, 1}, 0.2f, 0.4f, WeaponClass::Scorch, 100.0f);
    EXPECT_EQ(ring.count(), 24u);
    for (const auto& d : ring.slots()) {
        if (d.active) EXPECT_NE(d.point_body.x, 0.0f);  // x=0 was evicted
    }
}

TEST(DamageDecalRing, TickReclaimsColdHeatGlowButKeepsScorch) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 0.9f, WeaponClass::HeatGlow, 0.0f);
    ring.add({5, 0, 0}, {0, 0, 1}, 0.2f, 0.9f, WeaponClass::Scorch, 0.0f);
    ring.tick(0.5f);              // within 1.2 s lifetime
    EXPECT_EQ(ring.count(), 2u);
    ring.tick(2.0f);             // past 1.2 s — glow reclaimed, scorch stays
    EXPECT_EQ(ring.count(), 1u);
    EXPECT_EQ(first_active(ring)->weapon_class, WeaponClass::Scorch);
}

TEST(WorldToBody, InvertsTranslationAndRotation) {
    glm::mat4 ship = glm::translate(glm::mat4(1.0f), glm::vec3(10, 0, 0));
    ship = glm::rotate(ship, glm::radians(90.0f), glm::vec3(0, 0, 1));
    glm::vec3 world_pt(10, 1, 0);             // ship origin + 1 along world-Y
    glm::vec3 body = scenegraph::world_to_body(ship, world_pt);
    // World-Y maps back to +X in body after undoing the +90° Z rotation.
    EXPECT_NEAR(body.x, 1.0f, 1e-4f);
    EXPECT_NEAR(body.y, 0.0f, 1e-4f);
    EXPECT_NEAR(body.z, 0.0f, 1e-4f);
}

TEST(WorldDirToBody, NormalisesResult) {
    glm::mat4 ship = glm::rotate(glm::mat4(1.0f), glm::radians(90.0f),
                                 glm::vec3(0, 0, 1));
    glm::vec3 body = scenegraph::world_dir_to_body(ship, glm::vec3(0, 2, 0));
    EXPECT_NEAR(glm::length(body), 1.0f, 1e-4f);
}
```

- [ ] **Step 5: Register the test file**

In `native/tests/scenegraph/CMakeLists.txt`, change:

```cmake
add_executable(scenegraph_tests
    camera_test.cc
    world_test.cc
)
```

to:

```cmake
add_executable(scenegraph_tests
    camera_test.cc
    world_test.cc
    damage_decals_test.cc
)
```

- [ ] **Step 6: Configure, build, and run the test**

Run (a fresh configure is needed because CMakeLists changed):

```bash
cmake -B build -S . && cmake --build build -j --target scenegraph_tests && ctest --test-dir build -R DamageDecal --output-on-failure && ctest --test-dir build -R World --output-on-failure
```

Expected: all `DamageDecalRing.*`, `WorldToBody.*`, `WorldDirToBody.*` tests PASS.

- [ ] **Step 7: Commit**

```bash
git add native/src/scenegraph/include/scenegraph/damage_decals.h \
        native/src/scenegraph/src/damage_decals.cc \
        native/src/scenegraph/CMakeLists.txt \
        native/tests/scenegraph/damage_decals_test.cc \
        native/tests/scenegraph/CMakeLists.txt
git commit -m "$(printf 'feat(renderer): DamageDecalRing object-space decal store\n\nMerge-then-FIFO 24-slot ring + world->body transforms. Pure logic,\nno GL. Phase 1 of persistent-damage-decals.\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 2: Attach the ring to instances + mutable iteration

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h`
- Modify: `native/src/scenegraph/include/scenegraph/world.h`

- [ ] **Step 1: Add the ring to `Instance`**

In `native/src/scenegraph/include/scenegraph/instance.h`, add the include after the existing includes:

```cpp
#include "scenegraph/damage_decals.h"
```

and add this member to `struct Instance` (after `bool rim_eligible = false;`):

```cpp
    /// Per-instance persistent damage decals (object space, body frame).
    /// Runtime VFX state only — never serialized to saves.
    DamageDecalRing decals;
```

- [ ] **Step 2: Add mutable `for_each_alive` to `World`**

In `native/src/scenegraph/include/scenegraph/world.h`, add after `for_each_visible_in_pass`:

```cpp
    /// Iterate every alive instance (mutable). Used to age per-instance
    /// state (e.g. decal rings) regardless of visibility.
    template <typename Fn>
    void for_each_alive(Fn&& fn) {
        for (std::size_t i = 0; i < slots_.size(); ++i) {
            if (slots_[i].alive) fn(slots_[i].instance);
        }
    }
```

- [ ] **Step 3: Build to verify it compiles**

Run:

```bash
cmake --build build -j --target scenegraph scenegraph_tests && ctest --test-dir build -R "DamageDecal|World" --output-on-failure
```

Expected: builds clean; the Task 1 tests still PASS (no behavior change, just wiring).

- [ ] **Step 4: Commit**

```bash
git add native/src/scenegraph/include/scenegraph/instance.h \
        native/src/scenegraph/include/scenegraph/world.h
git commit -m "$(printf 'feat(renderer): attach DamageDecalRing to Instance + for_each_alive\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 3: Host bindings — `damage_decal_add` and `damage_decals_tick`

Expose the store to Python. `damage_decal_add` does the world→body transform using the instance's current world matrix; `damage_decals_tick` ages every ring.

**Files:**
- Modify: `native/src/host/host_bindings.cc`

- [ ] **Step 1: Add the include**

Near the top of `native/src/host/host_bindings.cc`, alongside the other `scenegraph/` includes, add:

```cpp
#include "scenegraph/damage_decals.h"
```

- [ ] **Step 2: Add the two bindings**

In `host_bindings.cc`, immediately after the `ray_trace_mesh` binding's closing `);` (around line 880; find the `m.def("ray_trace_mesh", ...);` block and insert after it), add:

```cpp
    m.def("damage_decal_add",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> world_point,
             std::tuple<float, float, float> world_normal,
             float radius, float intensity,
             std::uint32_t weapon_class, float time) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;  // stale id — drop silently
              const glm::vec3 pw(std::get<0>(world_point),
                                 std::get<1>(world_point),
                                 std::get<2>(world_point));
              const glm::vec3 nw(std::get<0>(world_normal),
                                 std::get<1>(world_normal),
                                 std::get<2>(world_normal));
              const glm::vec3 pb = scenegraph::world_to_body(inst->world, pw);
              const glm::vec3 nb = scenegraph::world_dir_to_body(inst->world, nw);
              inst->decals.add(pb, nb, radius, intensity,
                               static_cast<scenegraph::WeaponClass>(weapon_class),
                               time);
          },
          py::arg("id"), py::arg("world_point"), py::arg("world_normal"),
          py::arg("radius"), py::arg("intensity"),
          py::arg("weapon_class"), py::arg("time"),
          "Record an object-space damage decal on a ship instance. World-space "
          "point/normal are transformed into the ship body frame. weapon_class: "
          "0=HeatGlow (phaser), 1=Scorch (torpedo/disruptor).");

    m.def("damage_decals_tick",
          [](float time) {
              g_world.for_each_alive([&](scenegraph::Instance& inst) {
                  inst.decals.tick(time);
              });
          },
          py::arg("time"),
          "Age every instance's decal ring; reclaim cold heat-glow decals.");
```

- [ ] **Step 3: Build the host module**

Run:

```bash
cmake --build build -j
```

Expected: builds clean. The extension module `build/python/_open_stbc_host.cpython-*.so` is rebuilt with the two new symbols.

- [ ] **Step 4: Smoke-check the binding exists**

Run:

```bash
./build/dauntless --help >/dev/null 2>&1; python3 -c "import sys; sys.path.insert(0, 'build/python'); import _open_stbc_host as h; assert hasattr(h, 'damage_decal_add'), 'missing damage_decal_add'; assert hasattr(h, 'damage_decals_tick'), 'missing damage_decals_tick'; print('bindings present')"
```

Expected: prints `bindings present`. (If it fails with `ModuleNotFoundError`, the `.so` name differs — list `build/python/` and adjust `sys.path`; do not edit Python in response to a stale `.so`, rebuild from `build/` per CLAUDE.md.)

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "$(printf 'feat(host): bind damage_decal_add + damage_decals_tick\n\nWorld->body transform at the binding boundary; tick ages all rings.\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 4: Python decal mappings (`engine/appc/damage_decals.py`)

Pure helpers with no host dependency: weapon type → class, hull damage → intensity, and a guarded game-time reader.

**Files:**
- Create: `engine/appc/damage_decals.py`
- Create: `tests/unit/test_damage_decals.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_damage_decals.py`:

```python
from engine.appc import damage_decals as dd


def test_phaser_maps_to_heat_glow():
    assert dd.weapon_class_for("phaser") == dd.WEAPON_CLASS_HEAT_GLOW


def test_torpedo_maps_to_scorch():
    assert dd.weapon_class_for("torpedo") == dd.WEAPON_CLASS_SCORCH


def test_unknown_and_none_default_to_scorch():
    assert dd.weapon_class_for(None) == dd.WEAPON_CLASS_SCORCH
    assert dd.weapon_class_for("disruptor") == dd.WEAPON_CLASS_SCORCH


def test_intensity_is_monotonic_and_clamped():
    assert dd.decal_intensity(0.0) == 0.0
    assert dd.decal_intensity(-5.0) == 0.0          # negative clamps to 0
    low = dd.decal_intensity(1.0)
    high = dd.decal_intensity(50.0)
    assert 0.0 < low <= high <= 1.0
    assert dd.decal_intensity(1e9) == 1.0           # saturates


def test_current_game_time_is_float_and_safe_without_app(monkeypatch):
    # With no usable App clock, returns 0.0 rather than raising.
    monkeypatch.setattr(dd, "_game_time_source", lambda: (_ for _ in ()).throw(RuntimeError()))
    assert dd.current_game_time() == 0.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/unit/test_damage_decals.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'engine.appc.damage_decals'`.

- [ ] **Step 3: Write the implementation**

Create `engine/appc/damage_decals.py`:

```python
"""Pure mappings for the persistent damage-decal store.

No host / renderer dependency: weapon type -> decal class, hull damage ->
decal intensity, and a guarded game-time reader. The C++ DamageDecalRing
owns the actual records (see native/src/scenegraph/damage_decals.*); this
module only computes the scalar inputs the emission path feeds to
host.damage_decal_add.
"""

# Mirror of scenegraph::WeaponClass (native/src/scenegraph/damage_decals.h).
WEAPON_CLASS_HEAT_GLOW = 0   # phaser — transient emissive bloom
WEAPON_CLASS_SCORCH = 1      # torpedo / disruptor — persistent deposit + ember

# Hull damage that maps to a full-intensity (1.0) decal. Tuning constant;
# spec §3.6 fixes only the contract (monotonic, clamped). Revisit in Phase 2.
INTENSITY_REFERENCE_DAMAGE = 8.0


def weapon_class_for(weapon_type):
    """Map a weapon_type string ("phaser" / "torpedo" / ...) to a decal class.

    Only "phaser" produces the transient heat-glow class; everything else
    (torpedo, disruptor, None, unknown) deposits persistent scorch.
    """
    if weapon_type == "phaser":
        return WEAPON_CLASS_HEAT_GLOW
    return WEAPON_CLASS_SCORCH


def decal_intensity(absorbed_hull: float) -> float:
    """Map hull damage actually dealt to a clamped [0,1] decal intensity.

    Monotonic in absorbed_hull, saturating at INTENSITY_REFERENCE_DAMAGE.
    """
    if absorbed_hull <= 0.0:
        return 0.0
    return min(1.0, float(absorbed_hull) / INTENSITY_REFERENCE_DAMAGE)


def _game_time_source() -> float:
    """Read the canonical game clock. Isolated so tests can monkeypatch it."""
    import App
    return float(App.g_kUtopiaModule.GetGameTime())


def current_game_time() -> float:
    """Game-time seconds for decal birth_time / aging, or 0.0 if unavailable.

    The decal clock must match the value passed to host.damage_decals_tick
    (host_loop uses the same App.g_kUtopiaModule.GetGameTime()).
    """
    try:
        return _game_time_source()
    except Exception:
        return 0.0
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/unit/test_damage_decals.py -v
```

Expected: all five tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/damage_decals.py tests/unit/test_damage_decals.py
git commit -m "$(printf 'feat(combat): decal weapon-class + intensity mappings\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 5: Emit decals from the hit path (the shield-fix)

Wire `dispatch` to call `host.damage_decal_add` only when hull damage was dealt, and pass `r_hit` through from `apply_hit`.

**Files:**
- Modify: `engine/appc/hit_feedback.py:79` (the `dispatch` signature + body)
- Modify: `engine/appc/combat.py:413-423` (the `dispatch` call)
- Create: `tests/unit/test_decal_emission.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_decal_emission.py`:

```python
"""dispatch must emit a decal exactly when hull damage was dealt, and never
when shields fully absorbed the hit (the shield-gating fix)."""
import types
import pytest

from engine.appc import hit_feedback
from engine.appc import damage_decals as dd


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _FakeHost:
    def __init__(self):
        self.decal_calls = []

    def damage_decal_add(self, *, id, world_point, world_normal,
                         radius, intensity, weapon_class, time):
        self.decal_calls.append(dict(
            id=id, world_point=world_point, world_normal=world_normal,
            radius=radius, intensity=intensity, weapon_class=weapon_class,
            time=time))


class _Hull:
    def IsDestroyed(self):
        return 0


class _Ship:
    def GetHull(self):
        return _Hull()


@pytest.fixture
def patched(monkeypatch):
    # Make dispatch's downstream side-effects inert so the test isolates
    # decal emission: no real App, no audio, no camera shake.
    monkeypatch.setattr(dd, "current_game_time", lambda: 42.0)
    return monkeypatch


def _dispatch(host, *, absorbed_hull, weapon_type="torpedo", normal=_Pt(0, 0, 1)):
    ship = _Ship()
    hit_feedback.dispatch(
        ship=ship, source=None, point=_Pt(1, 2, 3), normal=normal,
        damage=10.0, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=absorbed_hull, sub_transition=None,
        host=host, ship_instances={ship: "IID"},
        weapon_type=weapon_type, radius=0.2,
    )


def test_decal_emitted_when_hull_damaged(patched):
    host = _FakeHost()
    _dispatch(host, absorbed_hull=5.0)
    assert len(host.decal_calls) == 1
    call = host.decal_calls[0]
    assert call["id"] == "IID"
    assert call["world_point"] == (1, 2, 3)
    assert call["weapon_class"] == dd.WEAPON_CLASS_SCORCH
    assert call["radius"] == 0.2
    assert call["time"] == 42.0
    assert 0.0 < call["intensity"] <= 1.0


def test_no_decal_when_shields_absorbed(patched):
    host = _FakeHost()
    _dispatch(host, absorbed_hull=0.0)        # shields ate it
    assert host.decal_calls == []


def test_phaser_emits_heat_glow_class(patched):
    host = _FakeHost()
    _dispatch(host, absorbed_hull=3.0, weapon_type="phaser")
    assert host.decal_calls[0]["weapon_class"] == dd.WEAPON_CLASS_HEAT_GLOW


def test_no_decal_without_normal(patched):
    # No surface normal (sphere-entry / fallback hit) -> no decal; we don't
    # have a reliable orientation for normal-aware falloff.
    host = _FakeHost()
    _dispatch(host, absorbed_hull=5.0, normal=None)
    assert host.decal_calls == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/unit/test_decal_emission.py -v
```

Expected: FAIL — `dispatch()` got an unexpected keyword argument `radius` (the kwarg doesn't exist yet).

- [ ] **Step 3: Add the `radius` kwarg and emission step to `dispatch`**

In `engine/appc/hit_feedback.py`, change the `dispatch` signature (line 79-83) from:

```python
def dispatch(*, ship, source, point, normal, damage, subsystem,
             absorbed_shields: float, absorbed_subsystem: float,
             absorbed_hull: float, sub_transition,
             host=None, ship_instances=None,
             weapon_type: str | None = None) -> None:
```

to (add `radius`):

```python
def dispatch(*, ship, source, point, normal, damage, subsystem,
             absorbed_shields: float, absorbed_subsystem: float,
             absorbed_hull: float, sub_transition,
             host=None, ship_instances=None,
             weapon_type: str | None = None, radius: float = 0.0) -> None:
```

Then, at the **end** of the `dispatch` body (after the camera-shake block that ends at line 151 `camera_shake.apply_kick(float(damage))`), append:

```python

    # 4. Persistent damage decal — Phase 1 of persistent-damage-decals.
    # Emit ONLY when hull damage was actually dealt: a hit fully absorbed
    # by shields must NOT leave a scar (the shield-gating fix). Requires a
    # surface normal (mesh trace) for normal-aware falloff; sphere-entry
    # fallbacks (normal=None) are skipped.
    if (absorbed_hull > 0.0 and normal is not None
            and host is not None and ship_instances is not None
            and hasattr(host, "damage_decal_add")):
        iid = ship_instances.get(ship)
        if iid is not None:
            from engine.appc import damage_decals
            host.damage_decal_add(
                id=iid,
                world_point=(point.x, point.y, point.z),
                world_normal=(normal.x, normal.y, normal.z),
                radius=float(radius),
                intensity=damage_decals.decal_intensity(absorbed_hull),
                weapon_class=damage_decals.weapon_class_for(weapon_type),
                time=damage_decals.current_game_time(),
            )
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/unit/test_decal_emission.py -v
```

Expected: all four tests PASS.

- [ ] **Step 5: Pass `radius=r_hit` from `apply_hit`**

In `engine/appc/combat.py`, the `hit_feedback.dispatch(...)` call inside `apply_hit` (around line 414-423) currently ends with `weapon_type=weapon_type,`. Add `radius=r_hit` to that call:

```python
        hit_feedback.dispatch(
            ship=ship, source=source, point=hit_point, normal=normal,
            damage=damage, subsystem=primary_subsystem,
            absorbed_shields=absorbed_shields,
            absorbed_subsystem=absorbed_subsystem_total,
            absorbed_hull=absorbed_hull,
            sub_transition=primary_transition,
            host=host, ship_instances=ship_instances,
            weapon_type=weapon_type,
            radius=r_hit,
        )
```

- [ ] **Step 6: Verify the existing combat + dispatch tests still pass**

Run (focused subset — never the full suite; it OOMs the host per CLAUDE.md):

```bash
uv run pytest tests/unit/test_decal_emission.py tests/unit/test_hit_feedback_dispatch.py tests/unit/test_apply_hit_routing.py tests/unit/test_apply_hit_splash.py -v
```

Expected: all PASS (the new `radius` kwarg defaults to 0.0, so pre-existing dispatch callers are unaffected; `apply_hit` now supplies it).

- [ ] **Step 7: Commit**

```bash
git add engine/appc/hit_feedback.py engine/appc/combat.py tests/unit/test_decal_emission.py
git commit -m "$(printf 'feat(combat): emit damage decals on hull hits, gated on absorbed_hull\n\nShields fully absorbing a hit no longer paints a decal (the shield-fix).\nPlumbs r_hit through dispatch as radius.\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 6: Age the rings each tick from the host loop

**Files:**
- Modify: `engine/host_loop.py:2588` (near the existing `set_bridge_wall_time` per-tick call)

- [ ] **Step 1: Read the surrounding context**

Run:

```bash
sed -n '2580,2592p' engine/host_loop.py
```

Confirm line ~2588 reads `r.set_bridge_wall_time(_App.g_kUtopiaModule.GetGameTime())`. This is the per-frame point where game time is already pulled; the decal tick goes alongside it using the **same** clock value so `birth_time` and aging agree.

- [ ] **Step 2: Add the decal tick call**

Immediately after the `r.set_bridge_wall_time(...)` line, add (guarded with `hasattr`, matching the codebase's stale-`.so` tolerance pattern at host_loop.py:2124):

```python
            # Age every ship's persistent damage-decal ring on the same game
            # clock used for decal birth_time (engine.appc.damage_decals).
            # hasattr-guarded so an older _open_stbc_host.so still runs.
            if hasattr(r, "damage_decals_tick"):
                r.damage_decals_tick(_App.g_kUtopiaModule.GetGameTime())
```

Match the surrounding indentation exactly (the `set_bridge_wall_time` line's leading whitespace).

- [ ] **Step 3: Verify host_loop still imports cleanly**

Run:

```bash
uv run python -c "import ast; ast.parse(open('engine/host_loop.py').read()); print('host_loop parses')"
```

Expected: prints `host_loop parses`.

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py
git commit -m "$(printf 'feat(host): age damage-decal rings each tick\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 7: Full Phase 1 verification

No new code — confirm the whole vertical slice builds and the relevant tests pass together.

- [ ] **Step 1: Clean reconfigure + build the canonical tree**

Run:

```bash
cmake -B build -S . && cmake --build build -j
```

Expected: `build/dauntless` and `build/python/_open_stbc_host.cpython-*.so` build with no errors.

- [ ] **Step 2: Run all native tests touched by this phase**

Run:

```bash
ctest --test-dir build -R "DamageDecal|World|RayTrace" --output-on-failure
```

Expected: all PASS.

- [ ] **Step 3: Run the focused Python test set**

Run (focused — do NOT run the whole suite; it OOMs the host per CLAUDE.md):

```bash
uv run pytest tests/unit/test_damage_decals.py tests/unit/test_decal_emission.py tests/unit/test_hit_feedback_dispatch.py tests/unit/test_apply_hit_routing.py tests/unit/test_apply_hit_splash.py tests/unit/test_combat_hit_resolution.py -v
```

Expected: all PASS.

- [ ] **Step 4: Confirm bindings present on the freshly-built module**

Run:

```bash
python3 -c "import sys; sys.path.insert(0, 'build/python'); import _open_stbc_host as h; print('add:', hasattr(h, 'damage_decal_add'), 'tick:', hasattr(h, 'damage_decals_tick'))"
```

Expected: `add: True tick: True`.

- [ ] **Step 5: Final commit (if any uncommitted changes remain)**

```bash
git status --short
# If clean, Phase 1 is complete. Otherwise stage + commit the remainder.
```

---

## Done criteria

- `DamageDecalRing` (24-slot, merge-then-FIFO, heat-glow reclaim) is covered by passing GoogleTests.
- `host.damage_decal_add` transforms world→body and inserts; `host.damage_decals_tick` ages all rings.
- `dispatch` emits a decal **iff** `absorbed_hull > 0` and a surface normal is present; shield-absorbed hits emit nothing.
- Phaser hits map to `HeatGlow`, torpedo/disruptor to `Scorch`; intensity is monotonic and clamped.
- No shader change — nothing renders the ring yet. That is Phase 2.

When Phase 1 merges, annotate the spec's Phase 1 section with `shipped <date>`.
```
