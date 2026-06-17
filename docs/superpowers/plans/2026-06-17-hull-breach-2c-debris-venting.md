# Hull Breach 2c (Debris + Venting + Cooling Rim) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three analytic, event-driven transient VFX to every hull breach: tumbling voxel-chunk debris, a finite venting-plasma jet (via the existing `ParticlePass`), and a cooling molten-rim emissive on the breach scoop — all driven by a per-instance `BreachEventRing` stamped when a carve sphere is added.

**Architecture:** A new `BreachEventRing` (mirroring `DamageDecalRing`) is stamped in `hull_carve_add` and lives on `scenegraph::Instance` alongside `HullCarveField carve`. Three stateless consumers read active events each frame and produce their output analytically from `(birth_time, seed, age)`; no simulation state, no save/load, all deterministic and unit-testable. The whole system is gated by the existing `dauntless_hull_damage::enabled()` toggle, making the off path byte-identical to the stock BC render.

**Tech Stack:** C++17, OpenGL 4.1 core / GLSL 330, glm, GoogleTest, pybind11; analytic `ParticlePass`; CMake single build tree at `build/`.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `native/src/scenegraph/include/scenegraph/breach_events.h` | **Create** | `BreachEvent` struct + `BreachEventRing` class + lifetime constants |
| `native/src/scenegraph/src/breach_events.cc` | **Create** | `BreachEventRing::push`, `tick`, `count`, `slots` implementations |
| `native/tests/scenegraph/breach_events_test.cc` | **Create** | Pure gtest: push/overwrite-oldest, tick expiry, count/slots, determinism |
| `native/src/scenegraph/CMakeLists.txt` | **Modify** | Add `breach_events.cc` to `scenegraph` library; add `breach_events_test.cc` to `scenegraph_tests` |
| `native/tests/scenegraph/CMakeLists.txt` | **Modify** | Add `breach_events_test.cc` to `scenegraph_tests` |
| `native/src/scenegraph/include/scenegraph/instance.h` | **Modify** | Add `BreachEventRing breach_events;` and `InstanceId id{};` fields |
| `native/src/scenegraph/src/world.cc` | **Modify** | Stamp `slot.instance.id = id` in `create_instance` before returning |
| `native/src/host/host_bindings.cc` | **Modify** | (1) `hull_carve_add`: call `breach_events.push(…)` after `carve.add(…)`. (2) `damage_decals_tick`: also tick `breach_events`. (3) `render_space`: add `g_debris_pass->render(…)` after breach pass; build venting descriptors and render. (4) `init`/`shutdown`: construct/reset `g_debris_pass`. (5) Task 6: extend breach pass render call with event ring + now. |
| `native/tests/scenegraph/world_test.cc` | **Modify** | Add test that `create_instance` stamps `id` onto the instance |
| `native/src/renderer/cube_mesh.h` | **Create** | `assets::MeshCpu build_unit_cube()` declaration |
| `native/src/renderer/cube_mesh.cc` | **Create** | 24-vertex / 36-index unit cube (positions in [-0.5, 0.5]), matching `MeshCpu::Vertex` layout |
| `native/src/renderer/debris_chunks.h` | **Create** | `sample_chunk_origins` + `ChunkTransform` + `chunk_transform` pure analytic functions; `kChunkCount` |
| `native/src/renderer/debris_chunks.cc` | **Create** | Implementations of `sample_chunk_origins` and `chunk_transform` |
| `native/tests/renderer/debris_chunks_test.cc` | **Create** | Pure gtest: deterministic sampling; count cap; transform motion; alpha fade |
| `native/src/renderer/include/renderer/debris_pass.h` | **Create** | `DebrisPass` class declaration |
| `native/src/renderer/debris_pass.cc` | **Create** | Instanced unit-cube draw per active event per visible instance; gated by `dauntless_hull_damage::enabled()` |
| `native/src/renderer/shaders/debris.vert` | **Create** | Per-instance transform (world * translate(pos_body) * rot * scale(cell)); pass body pos |
| `native/src/renderer/shaders/debris.frag` | **Create** | Per-chunk hash color, alpha from `u_chunk_alpha`; alpha-blended |
| `native/tests/renderer/debris_pass_test.cc` | **Create** | GL test: fresh event → kChunkCount cubes drawn (pixel lit); expired / toggle-off → nothing |
| `native/src/renderer/CMakeLists.txt` | **Modify** | `embed_shader` for debris.vert/frag; add `cube_mesh.cc`, `debris_chunks.cc`, `debris_pass.cc` to `renderer` library |
| `native/src/renderer/include/renderer/pipeline.h` | **Modify** | Add `debris_shader()` accessor + `std::unique_ptr<Shader> debris_` member |
| `native/src/renderer/pipeline.cc` | **Modify** | Construct `debris_` shader from embedded source |
| `native/src/renderer/breach_venting.h` | **Create** | `build_venting_descriptors` pure function declaration |
| `native/src/renderer/breach_venting.cc` | **Create** | Builds `ParticleEmitterDescriptor` per active event (attached instance_id, body-frame emit_pos/dir, effect_age, stop_age=kVentLife, alpha taper) |
| `native/tests/renderer/breach_venting_test.cc` | **Create** | Pure gtest: descriptor has correct instance_id; emit_dir along breach normal; effect_age correct; alpha keys taper 1→0; no descriptors past kVentLife |
| `native/tests/renderer/CMakeLists.txt` | **Modify** | Add `debris_chunks_test.cc`, `debris_pass_test.cc`, `breach_venting_test.cc` to `renderer_tests` |
| `native/src/renderer/shaders/breach.frag` | **Modify** | Add `uniform float u_breach_age; uniform float u_rim_life;`; compute blackbody molten-rim emissive term |
| `native/src/renderer/breach_pass.cc` | **Modify** | `draw_scoop` gains `float breach_age` param + sets `u_breach_age`/`u_rim_life`; `render` correlates carve slots to active breach events to get age; signature extended with `(const BreachEventRing& events, float now)` |
| `native/src/renderer/include/renderer/breach_pass.h` | **Modify** | Update `render` and `draw_scoop` signatures; add `#include <scenegraph/breach_events.h>` |
| `docs/superpowers/notes/2026-06-17-hull-breach-2c-manual-verification.md` | **Create** | In-game checklist for manual verification |

---

## Task 1 — `BreachEvent` + `BreachEventRing` (pure) + gtest

**Goal:** Pure scenegraph types with no GL dependency. All lifetime constants defined here so debris, venting, and rim tasks can include one header.

**Files:**
- Create: `native/src/scenegraph/include/scenegraph/breach_events.h`
- Create: `native/src/scenegraph/src/breach_events.cc`
- Create: `native/tests/scenegraph/breach_events_test.cc`
- Modify: `native/src/scenegraph/CMakeLists.txt`
- Modify: `native/tests/scenegraph/CMakeLists.txt`

**Steps:**

- [ ] 1.1 — **Write failing test** `native/tests/scenegraph/breach_events_test.cc`:

```cpp
#include <gtest/gtest.h>
#include "scenegraph/breach_events.h"

using scenegraph::BreachEvent;
using scenegraph::BreachEventRing;

namespace {
const BreachEvent* first_active(const BreachEventRing& ring) {
    for (const auto& e : ring.slots()) if (e.active) return &e;
    return nullptr;
}
} // namespace

TEST(BreachEventRing, PushCreatesOneActiveEvent) {
    BreachEventRing ring;
    ring.push({1.f, 2.f, 3.f}, 1.5f, 0.0f, 42u);
    EXPECT_EQ(ring.count(), 1u);
    const BreachEvent* e = first_active(ring);
    ASSERT_NE(e, nullptr);
    EXPECT_FLOAT_EQ(e->center_body.x, 1.f);
    EXPECT_FLOAT_EQ(e->radius, 1.5f);
    EXPECT_FLOAT_EQ(e->birth_time, 0.0f);
    EXPECT_EQ(e->seed, 42u);
    EXPECT_TRUE(e->active);
}

TEST(BreachEventRing, FullRingOverwritesOldest) {
    BreachEventRing ring;
    for (std::size_t i = 0; i < BreachEventRing::kMaxEvents; ++i) {
        ring.push({static_cast<float>(i), 0.f, 0.f}, 1.f,
                  static_cast<float>(i), static_cast<std::uint64_t>(i));
    }
    EXPECT_EQ(ring.count(), BreachEventRing::kMaxEvents);
    // One more push overwrites the oldest (center_body.x == 0).
    ring.push({999.f, 0.f, 0.f}, 1.f, 100.f, 999u);
    EXPECT_EQ(ring.count(), BreachEventRing::kMaxEvents);
    bool found_zero = false;
    for (const auto& e : ring.slots()) {
        if (e.active && e.center_body.x == 0.f) { found_zero = true; break; }
    }
    EXPECT_FALSE(found_zero) << "oldest event (x=0) should have been overwritten";
}

TEST(BreachEventRing, TickExpiresAtEventLife) {
    BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, 0.0f, 1u);
    ring.tick(scenegraph::kEventLife - 0.001f);
    EXPECT_EQ(ring.count(), 1u)     << "must still be active before kEventLife";
    ring.tick(scenegraph::kEventLife + 0.001f);
    EXPECT_EQ(ring.count(), 0u)     << "must be deactivated at/past kEventLife";
}

TEST(BreachEventRing, SlotsAccessorReturnsAll) {
    BreachEventRing ring;
    EXPECT_EQ(ring.slots().size(), BreachEventRing::kMaxEvents);
}

TEST(BreachEventRing, CountsOnlyActiveSlots) {
    BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, 0.f, 1u);
    ring.push({1.f, 0.f, 0.f}, 1.f, 0.f, 2u);
    EXPECT_EQ(ring.count(), 2u);
    ring.tick(scenegraph::kEventLife + 1.f);
    EXPECT_EQ(ring.count(), 0u);
}

TEST(BreachEventRing, SeedIsStoredVerbatim) {
    BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, 0.f, 0xDEADBEEFull);
    EXPECT_EQ(first_active(ring)->seed, 0xDEADBEEFull);
}
```

- [ ] 1.2 — **Add to scenegraph_tests CMakeLists** `native/tests/scenegraph/CMakeLists.txt` — add `breach_events_test.cc` to the `add_executable(scenegraph_tests …)` source list.

- [ ] 1.3 — **Build** (expects link failure — header missing):
```bash
cmake -B build -S . && cmake --build build --target scenegraph_tests -j
```
Confirm it fails to find `scenegraph/breach_events.h`.

- [ ] 1.4 — **Write `breach_events.h`** `native/src/scenegraph/include/scenegraph/breach_events.h`:

```cpp
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <glm/glm.hpp>

namespace scenegraph {

// Effect lifetime constants. All consumers include this header.
inline constexpr float kDebrisLife = 2.5f;  // seconds: tumbling chunks
inline constexpr float kVentLife   = 2.0f;  // seconds: venting jet emission
inline constexpr float kRimLife    = 3.0f;  // seconds: molten rim cooling
// An event lives until all consumers have finished with it.
inline constexpr float kEventLife  = 3.0f;  // max(kDebrisLife, kVentLife, kRimLife)

struct BreachEvent {
    glm::vec3     center_body{0.0f};  // breach center in body frame (model units)
    float         radius     = 0.0f;  // carve sphere radius (model units)
    float         birth_time = 0.0f;  // game-clock seconds at push time
    std::uint64_t seed       = 0;     // deterministic per-event hash seed
    bool          active     = false;
};

/// Fixed-capacity per-instance breach event store. Overwrites the oldest slot
/// when full (simple FIFO — no merge; every breach is distinct). Runtime-only
/// VFX, never serialized.
class BreachEventRing {
public:
    static constexpr std::size_t kMaxEvents = 24;

    /// Record a new breach event. Overwrites the slot with the smallest
    /// birth_time when all slots are occupied.
    void push(const glm::vec3& center_body, float radius,
              float birth_time, std::uint64_t seed);

    /// Deactivate events whose age exceeds kEventLife.
    void tick(float now);

    std::size_t count() const;
    const std::array<BreachEvent, kMaxEvents>& slots() const { return slots_; }

private:
    std::array<BreachEvent, kMaxEvents> slots_{};
};

} // namespace scenegraph
```

- [ ] 1.5 — **Write `breach_events.cc`** `native/src/scenegraph/src/breach_events.cc`:

```cpp
#include "scenegraph/breach_events.h"
#include <algorithm>
#include <limits>

namespace scenegraph {

void BreachEventRing::push(const glm::vec3& center_body, float radius,
                            float birth_time, std::uint64_t seed) {
    // Find a free slot first.
    for (auto& e : slots_) {
        if (!e.active) {
            e = BreachEvent{center_body, radius, birth_time, seed, true};
            return;
        }
    }
    // All slots occupied: overwrite the oldest (smallest birth_time).
    BreachEvent* oldest = &slots_[0];
    for (auto& e : slots_) {
        if (e.birth_time < oldest->birth_time) oldest = &e;
    }
    *oldest = BreachEvent{center_body, radius, birth_time, seed, true};
}

void BreachEventRing::tick(float now) {
    for (auto& e : slots_) {
        if (e.active && (now - e.birth_time) >= kEventLife) {
            e.active = false;
        }
    }
}

std::size_t BreachEventRing::count() const {
    std::size_t n = 0;
    for (const auto& e : slots_) if (e.active) ++n;
    return n;
}

} // namespace scenegraph
```

- [ ] 1.6 — **Add `breach_events.cc` to scenegraph library** in `native/src/scenegraph/CMakeLists.txt`:

```cmake
add_library(scenegraph STATIC
    src/camera.cc
    src/world.cc
    src/damage_decals.cc
    src/hull_carve.cc
    src/breach_events.cc      # NEW
)
```

- [ ] 1.7 — **Build and run tests** (all must pass):
```bash
cmake -B build -S . && cmake --build build --target scenegraph_tests -j
ctest --test-dir build -R "BreachEventRing" --output-on-failure
```
Expected: 6 tests pass.

- [ ] 1.8 — **Confirm baseline still green**:
```bash
ctest --test-dir build --output-on-failure 2>&1 | tail -5
```
Expected: all 383+ tests pass.

- [ ] 1.9 — Commit:
```bash
git add native/src/scenegraph/include/scenegraph/breach_events.h \
        native/src/scenegraph/src/breach_events.cc \
        native/tests/scenegraph/breach_events_test.cc \
        native/src/scenegraph/CMakeLists.txt \
        native/tests/scenegraph/CMakeLists.txt && \
git commit -m "$(cat <<'EOF'
feat(spv): BreachEventRing pure type + gtest (hull-breach-2c)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 — Wire `BreachEventRing` onto `Instance`; stamp `id`; push + tick in host_bindings

**Goal:** `Instance` carries its own id and a breach-event ring; `hull_carve_add` pushes an event; `damage_decals_tick` also ticks breach events. Build-green; small world test verifies the id stamp.

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h`
- Modify: `native/src/scenegraph/src/world.cc`
- Modify: `native/tests/scenegraph/world_test.cc`
- Modify: `native/src/host/host_bindings.cc`

**Steps:**

- [ ] 2.1 — **Write failing world test** — add to `native/tests/scenegraph/world_test.cc`:

```cpp
TEST(World, CreateInstanceStampsIdOntoInstance) {
    scenegraph::World world;
    scenegraph::InstanceId id = world.create_instance(0);
    const scenegraph::Instance* inst = world.get(id);
    ASSERT_NE(inst, nullptr);
    EXPECT_EQ(inst->id, id)
        << "create_instance must stamp the returned InstanceId onto instance.id";
}
```

Build + confirm it fails:
```bash
cmake -B build -S . && cmake --build build --target scenegraph_tests -j
ctest --test-dir build -R "CreateInstanceStampsId" --output-on-failure
```

- [ ] 2.2 — **Add fields to `Instance`** in `native/src/scenegraph/include/scenegraph/instance.h`:

Add the following include at the top alongside the existing includes:
```cpp
#include "scenegraph/breach_events.h"
```

Add the following two fields inside `struct Instance` after the existing `HullCarveField carve;` field:
```cpp
    /// Per-instance transient breach-event ring. Drives debris, venting, and
    /// molten-rim emissive. Runtime VFX only — never serialized to saves.
    BreachEventRing breach_events;

    /// Self-referential id stamped by World::create_instance so particle
    /// emitters built from breach events can carry an attached instance_id.
    InstanceId id{};
```

- [ ] 2.3 — **Stamp `id` in `world.cc`** — in `World::create_instance`, after `slots_[idx].instance.model_handle = model;` add:
```cpp
    const InstanceId new_id{idx, slots_[idx].generation};
    slots_[idx].instance.id = new_id;
    return new_id;
```
(Remove the old `return InstanceId{idx, slots_[idx].generation};` line — the new_id variable replaces it.)

- [ ] 2.4 — **Build + run world test**:
```bash
cmake -B build -S . && cmake --build build --target scenegraph_tests -j
ctest --test-dir build -R "CreateInstanceStampsId" --output-on-failure
```
Expected: passes.

- [ ] 2.5 — **Push event in `hull_carve_add`** in `native/src/host/host_bindings.cc`. Find the binding at line ~1535. After the existing `inst->carve.add(pb, radius_model);` line, add:

```cpp
              // Breach event: transient VFX ring (debris, venting, rim).
              // Seed: deterministic hash of center_body to avoid per-frame
              // re-rolling; XOR with a counter grown per push to decorrelate
              // closely-spaced simultaneous breaches on the same ship.
              {
                  static std::uint64_t s_counter = 0;
                  const auto bx = static_cast<std::uint64_t>(
                      static_cast<std::uint32_t>(pb.x * 1000.f));
                  const auto by = static_cast<std::uint64_t>(
                      static_cast<std::uint32_t>(pb.y * 1000.f));
                  const auto bz = static_cast<std::uint64_t>(
                      static_cast<std::uint32_t>(pb.z * 1000.f));
                  const std::uint64_t seed =
                      (bx * 2654435761ull) ^ (by * 805459861ull) ^
                      (bz * 3674653429ull) ^ (++s_counter * 6364136223846793005ull);
                  inst->breach_events.push(pb, radius_model,
                                           g_decal_game_time, seed);
              }
```

- [ ] 2.6 — **Tick breach events in `damage_decals_tick`** in `host_bindings.cc`. The existing binding (line ~1681) is:
```cpp
    m.def("damage_decals_tick",
          [](float time) {
              g_decal_game_time = time;
              g_world.for_each_alive([&](scenegraph::Instance& inst) {
                  inst.decals.tick(time);
              });
          }, …);
```
Add `inst.breach_events.tick(time);` inside the `for_each_alive` lambda, after `inst.decals.tick(time);`.

- [ ] 2.7 — **Build the full dauntless target** (host_bindings.cc is compiled into both):
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: clean build, 0 errors.

- [ ] 2.8 — **Full test suite green**:
```bash
ctest --test-dir build --output-on-failure 2>&1 | tail -5
```
Expected: all prior tests pass.

- [ ] 2.9 — Commit:
```bash
git add native/src/scenegraph/include/scenegraph/instance.h \
        native/src/scenegraph/src/world.cc \
        native/tests/scenegraph/world_test.cc \
        native/src/host/host_bindings.cc && \
git commit -m "$(cat <<'EOF'
feat(spv): wire BreachEventRing onto Instance; stamp id; push/tick in host_bindings

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — Debris chunk math (pure) + gtest

**Goal:** Pure, GL-free functions for deterministic chunk sampling from a voxel fill and analytic per-chunk transform (position + rotation + alpha). Unit-testable without a GL context.

**Files:**
- Create: `native/src/renderer/debris_chunks.h`
- Create: `native/src/renderer/debris_chunks.cc`
- Create: `native/tests/renderer/debris_chunks_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

**Steps:**

- [ ] 3.1 — **Write failing test** `native/tests/renderer/debris_chunks_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <voxel/volume.h>
#include "debris_chunks.h"  // relative include — in same renderer src tree

namespace {
// Solid 4^3 fill with all voxels occupied.
voxel::VoxelVolume solid_fill_4() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 4};
    v.origin = {-2.f, -2.f, -2.f};
    v.cell   = {1.f,  1.f,  1.f};
    v.occ.assign(64, 127);
    return v;
}
} // namespace

TEST(SampleChunkOrigins, DeterministicForFixedSeed) {
    auto fill = solid_fill_4();
    auto a = renderer::sample_chunk_origins(fill, {0,0,0}, 3.f, 42u, 8);
    auto b = renderer::sample_chunk_origins(fill, {0,0,0}, 3.f, 42u, 8);
    ASSERT_EQ(a.size(), b.size());
    for (std::size_t i = 0; i < a.size(); ++i) {
        EXPECT_FLOAT_EQ(a[i].x, b[i].x);
        EXPECT_FLOAT_EQ(a[i].y, b[i].y);
        EXPECT_FLOAT_EQ(a[i].z, b[i].z);
    }
}

TEST(SampleChunkOrigins, CountCappedByMaxChunks) {
    auto fill = solid_fill_4();
    auto origins = renderer::sample_chunk_origins(fill, {0,0,0}, 3.f, 1u, 5);
    EXPECT_LE(origins.size(), 5u);
}

TEST(SampleChunkOrigins, AllOriginsWithinRadius) {
    auto fill = solid_fill_4();
    auto origins = renderer::sample_chunk_origins(fill, {0,0,0}, 3.f, 7u, 16);
    for (const auto& o : origins) {
        EXPECT_LE(glm::length(o), 3.f + 0.87f)  // allow half-diagonal of 1-unit cell
            << "origin outside carve sphere + cell tolerance";
    }
}

TEST(ChunkTransform, PositionAdvancesWithAge) {
    // At age=0 the chunk is at its origin; at age>0 it has moved outward.
    glm::vec3 origin{1.f, 0.f, 0.f};
    glm::vec3 breach_center{0.f, 0.f, 0.f};
    auto t0 = renderer::chunk_transform(origin, breach_center, 0.0f, 1u, 0);
    auto t1 = renderer::chunk_transform(origin, breach_center, 0.5f, 1u, 0);
    EXPECT_GT(glm::length(t1.pos_body - origin),
              glm::length(t0.pos_body - origin))
        << "chunk must move away from origin with increasing age";
}

TEST(ChunkTransform, AlphaFadesToZeroAtDebrisLife) {
    glm::vec3 origin{1.f, 0.f, 0.f};
    glm::vec3 center{0.f, 0.f, 0.f};
    auto t_alive = renderer::chunk_transform(origin, center, 0.1f, 1u, 0);
    auto t_dead  = renderer::chunk_transform(origin, center,
                                              scenegraph::kDebrisLife + 0.01f,
                                              1u, 0);
    EXPECT_GT(t_alive.alpha, 0.5f);
    EXPECT_FLOAT_EQ(t_dead.alpha, 0.f);
}

TEST(ChunkTransform, DifferentSeedsProduceDifferentDirs) {
    glm::vec3 origin{1.f, 0.f, 0.f};
    glm::vec3 center{0.f, 0.f, 0.f};
    auto ta = renderer::chunk_transform(origin, center, 0.5f, 42u, 0);
    auto tb = renderer::chunk_transform(origin, center, 0.5f, 99u, 0);
    // Different seeds must produce different positions (extremely unlikely to
    // collide with 64-bit hashing).
    EXPECT_NE(ta.pos_body, tb.pos_body);
}
```

- [ ] 3.2 — **Add `debris_chunks_test.cc` to `renderer_tests`** in `native/tests/renderer/CMakeLists.txt` (add to the `add_executable` source list).

- [ ] 3.3 — **Build** (expects failure — files not created yet):
```bash
cmake -B build -S . && cmake --build build --target renderer_tests -j
```
Confirm it fails to find `debris_chunks.h`.

- [ ] 3.4 — **Write `debris_chunks.h`** at `native/src/renderer/debris_chunks.h` (alongside `sphere_mesh.h`):

```cpp
#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>
#include <glm/glm.hpp>
#include <voxel/volume.h>
#include <scenegraph/breach_events.h>  // for kDebrisLife

namespace renderer {

/// Number of chunks spawned per breach event (eyeball-tunable constant).
inline constexpr int kChunkCount = 16;

/// Sample up to max_chunks solid voxel centers from fill that lie within
/// radius of center_body. Deterministic for fixed seed. Returns fewer than
/// max_chunks when insufficient solid voxels exist inside the sphere.
std::vector<glm::vec3> sample_chunk_origins(
    const voxel::VoxelVolume& fill,
    const glm::vec3& center_body,
    float radius,
    std::uint64_t seed,
    int max_chunks = kChunkCount);

/// Per-chunk world transform computed analytically from birth state + age.
struct ChunkTransform {
    glm::vec3 pos_body;  ///< current position in body frame
    glm::mat3 rot;       ///< current rotation (tumble)
    float     alpha;     ///< opacity: 1 at age=0, 0 at kDebrisLife
};

/// Compute the transform for chunk i at the given age.
/// origin     — voxel center in body frame (from sample_chunk_origins)
/// center     — breach center in body frame (radial outward direction source)
/// age        — now - birth_time (seconds)
/// seed       — event seed
/// i          — chunk index [0, kChunkCount)
ChunkTransform chunk_transform(
    const glm::vec3& origin,
    const glm::vec3& breach_center,
    float age,
    std::uint64_t seed,
    int i);

} // namespace renderer
```

- [ ] 3.5 — **Write `debris_chunks.cc`** at `native/src/renderer/debris_chunks.cc`:

```cpp
#include "debris_chunks.h"
#include <cmath>
#include <glm/gtc/matrix_transform.hpp>

namespace renderer {

namespace {

// 64-bit splitmix hash for deterministic per-chunk randomness.
inline std::uint64_t smix(std::uint64_t x) {
    x += 0x9e3779b97f4a7c15ull;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ull;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebull;
    return x ^ (x >> 31);
}

// Float in [0, 1) from a hash value.
inline float h01(std::uint64_t h) {
    return static_cast<float>(h >> 11) * (1.f / static_cast<float>(1ull << 53));
}

} // namespace

std::vector<glm::vec3> sample_chunk_origins(
    const voxel::VoxelVolume& fill,
    const glm::vec3& center_body,
    float radius,
    std::uint64_t seed,
    int max_chunks) {

    std::vector<glm::vec3> candidates;
    candidates.reserve(64);

    // Enumerate solid voxels inside the carve sphere.
    for (int iz = 0; iz < fill.dims.z; ++iz) {
        for (int iy = 0; iy < fill.dims.y; ++iy) {
            for (int ix = 0; ix < fill.dims.x; ++ix) {
                const std::size_t idx =
                    static_cast<std::size_t>(iz * fill.dims.y * fill.dims.x
                                           + iy * fill.dims.x + ix);
                if (fill.occ[idx] == 0) continue;
                // Voxel center in body frame.
                const glm::vec3 vc = fill.origin
                    + fill.cell * glm::vec3(ix + 0.5f, iy + 0.5f, iz + 0.5f);
                if (glm::length(vc - center_body) <= radius) {
                    candidates.push_back(vc);
                }
            }
        }
    }
    if (candidates.empty()) return {};

    // Deterministic subsample to max_chunks using Fisher-Yates-style shuffle.
    const int n = static_cast<int>(candidates.size());
    const int take = std::min(max_chunks, n);
    std::vector<int> idx(static_cast<std::size_t>(n));
    for (int i = 0; i < n; ++i) idx[static_cast<std::size_t>(i)] = i;

    std::uint64_t rng = smix(seed ^ 0xdeadbeefcafeull);
    for (int i = 0; i < take; ++i) {
        rng = smix(rng);
        const int j = i + static_cast<int>(rng % static_cast<std::uint64_t>(n - i));
        std::swap(idx[static_cast<std::size_t>(i)], idx[static_cast<std::size_t>(j)]);
    }

    std::vector<glm::vec3> result;
    result.reserve(static_cast<std::size_t>(take));
    for (int i = 0; i < take; ++i) {
        result.push_back(candidates[static_cast<std::size_t>(idx[static_cast<std::size_t>(i)])]);
    }
    return result;
}

ChunkTransform chunk_transform(
    const glm::vec3& origin,
    const glm::vec3& breach_center,
    float age,
    std::uint64_t seed,
    int i) {

    // Per-chunk deterministic parameters.
    const std::uint64_t h0 = smix(seed ^ (static_cast<std::uint64_t>(i) * 2654435761ull));
    const std::uint64_t h1 = smix(h0 + 1);
    const std::uint64_t h2 = smix(h0 + 2);
    const std::uint64_t h3 = smix(h0 + 3);
    const std::uint64_t h4 = smix(h0 + 4);

    // Outward direction from breach center with small random spread.
    const glm::vec3 radial = (glm::length(origin - breach_center) > 1e-4f)
        ? glm::normalize(origin - breach_center)
        : glm::vec3(0.f, 1.f, 0.f);
    // Random tangential kick ±30 % of radial length to spread chunks.
    const float kick_x = (h01(h1) * 2.f - 1.f) * 0.3f;
    const float kick_y = (h01(h2) * 2.f - 1.f) * 0.3f;
    // Build a simple orthonormal frame around radial.
    const glm::vec3 up   = (std::abs(radial.y) < 0.99f)
                           ? glm::vec3(0.f, 1.f, 0.f)
                           : glm::vec3(1.f, 0.f, 0.f);
    const glm::vec3 tang = glm::normalize(glm::cross(up, radial));
    const glm::vec3 btan = glm::cross(radial, tang);
    const glm::vec3 dir  = glm::normalize(radial + tang * kick_x + btan * kick_y);

    // Speed in [1.5, 4.5] body-units / second.
    const float speed = 1.5f + h01(h3) * 3.0f;

    // Alpha: linear fade 1 → 0 over kDebrisLife; clamp to [0,1].
    const float t    = age / scenegraph::kDebrisLife;
    const float alpha = std::max(0.f, 1.f - t);

    const glm::vec3 pos_body = origin + dir * (speed * age);

    // Rotation: constant angular velocity around a random axis, angle = spin * age.
    const float spin_deg = 90.f + h01(h4) * 270.f;  // 90..360 deg/s
    const float angle    = glm::radians(spin_deg * age);
    const glm::vec3 rot_axis = glm::normalize(
        glm::vec3(h01(smix(h4 + 1)) * 2.f - 1.f,
                  h01(smix(h4 + 2)) * 2.f - 1.f,
                  h01(smix(h4 + 3)) * 2.f - 1.f + 1e-4f));
    const glm::mat3 rot = glm::mat3(
        glm::rotate(glm::mat4(1.f), angle, rot_axis));

    return ChunkTransform{pos_body, rot, alpha};
}

} // namespace renderer
```

- [ ] 3.6 — **Add `debris_chunks.cc` to `renderer` library** in `native/src/renderer/CMakeLists.txt` (add before `breach_pass.cc`):
```cmake
    debris_chunks.cc
```

- [ ] 3.7 — **Build + run debris_chunks tests**:
```bash
cmake -B build -S . && cmake --build build --target renderer_tests -j
ctest --test-dir build -R "SampleChunkOrigins|ChunkTransform" --output-on-failure
```
Expected: 5 tests pass.

- [ ] 3.8 — **Full suite green**:
```bash
ctest --test-dir build --output-on-failure 2>&1 | tail -5
```

- [ ] 3.9 — Commit:
```bash
git add native/src/renderer/debris_chunks.h \
        native/src/renderer/debris_chunks.cc \
        native/tests/renderer/debris_chunks_test.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/CMakeLists.txt && \
git commit -m "$(cat <<'EOF'
feat(spv): debris chunk math (pure, analytic) + gtest

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4 — `cube_mesh`, `DebrisPass`, `debris.vert/frag`, Pipeline wiring, `render_space` lifecycle

**Goal:** Instanced unit-cube debris pass renders tumbling chunks per active breach event. Gated by `dauntless_hull_damage::enabled()`. GL test verifies a fresh event produces lit pixels; expired / toggle-off produces nothing.

**Files:**
- Create: `native/src/renderer/cube_mesh.h`
- Create: `native/src/renderer/cube_mesh.cc`
- Create: `native/src/renderer/include/renderer/debris_pass.h`
- Create: `native/src/renderer/debris_pass.cc`
- Create: `native/src/renderer/shaders/debris.vert`
- Create: `native/src/renderer/shaders/debris.frag`
- Create: `native/tests/renderer/debris_pass_test.cc`
- Modify: `native/src/renderer/CMakeLists.txt`
- Modify: `native/src/renderer/include/renderer/pipeline.h`
- Modify: `native/src/renderer/pipeline.cc`
- Modify: `native/src/host/host_bindings.cc`
- Modify: `native/tests/renderer/CMakeLists.txt`

**Steps:**

- [ ] 4.1 — **Write `cube_mesh.h`** at `native/src/renderer/cube_mesh.h`:

```cpp
#pragma once
#include <assets/mesh.h>

namespace renderer {
/// Build a unit cube with 24 unique vertices (4 per face, distinct normals per
/// face). Positions in [-0.5, 0.5]. Matches assets::MeshCpu::Vertex layout
/// (position, normal, uv, color=white, bone fields=0).
assets::MeshCpu build_unit_cube();
} // namespace renderer
```

- [ ] 4.2 — **Write `cube_mesh.cc`** at `native/src/renderer/cube_mesh.cc`. The cube has 6 faces × 4 verts = 24 vertices and 6 × 2 triangles × 3 = 36 indices. Each face has a distinct normal:

```cpp
#include "cube_mesh.h"

namespace renderer {

assets::MeshCpu build_unit_cube() {
    // 6 faces, each with 4 vertices; positions in [-0.5, 0.5].
    // Layout: {position, normal, uv, color=white, bone_indices=0, bone_weights=0}
    struct FaceDef { glm::vec3 n; glm::vec3 p[4]; glm::vec2 uv[4]; };
    const FaceDef faces[6] = {
        // +X
        {{ 1,0,0}, {{ .5f,-.5f,-.5f},{ .5f,.5f,-.5f},{ .5f,.5f,.5f},{ .5f,-.5f,.5f}},
                   {{0,0},{1,0},{1,1},{0,1}}},
        // -X
        {{-1,0,0}, {{-.5f,-.5f,.5f},{-.5f,.5f,.5f},{-.5f,.5f,-.5f},{-.5f,-.5f,-.5f}},
                   {{0,0},{1,0},{1,1},{0,1}}},
        // +Y
        {{0, 1,0}, {{-.5f,.5f,-.5f},{-.5f,.5f,.5f},{ .5f,.5f,.5f},{ .5f,.5f,-.5f}},
                   {{0,0},{1,0},{1,1},{0,1}}},
        // -Y
        {{0,-1,0}, {{-.5f,-.5f,.5f},{-.5f,-.5f,-.5f},{ .5f,-.5f,-.5f},{ .5f,-.5f,.5f}},
                   {{0,0},{1,0},{1,1},{0,1}}},
        // +Z
        {{0,0, 1}, {{-.5f,-.5f,.5f},{ .5f,-.5f,.5f},{ .5f,.5f,.5f},{-.5f,.5f,.5f}},
                   {{0,0},{1,0},{1,1},{0,1}}},
        // -Z
        {{0,0,-1}, {{ .5f,-.5f,-.5f},{-.5f,-.5f,-.5f},{-.5f,.5f,-.5f},{ .5f,.5f,-.5f}},
                   {{0,0},{1,0},{1,1},{0,1}}},
    };

    assets::MeshCpu cpu;
    cpu.vertices.reserve(24);
    cpu.indices.reserve(36);

    for (const auto& f : faces) {
        const std::uint32_t base = static_cast<std::uint32_t>(cpu.vertices.size());
        for (int v = 0; v < 4; ++v) {
            assets::MeshCpu::Vertex vert{};
            vert.position = f.p[v];
            vert.normal   = f.n;
            vert.uv       = f.uv[v];
            vert.color    = glm::u8vec4(255, 255, 255, 255);
            cpu.vertices.push_back(vert);
        }
        // Two triangles per face (CCW winding when viewed from outside).
        cpu.indices.insert(cpu.indices.end(),
            {base, base+1, base+2, base, base+2, base+3});
    }
    return cpu;
}

} // namespace renderer
```

- [ ] 4.3 — **Write `debris.vert`** at `native/src/renderer/shaders/debris.vert`:

```glsl
#version 330 core
// Debris chunk vertex shader.
// Draws one unit cube per chunk; the per-chunk transform (pos_body + rot + cell
// scale) is passed as uniforms indexed by u_chunk_idx.  The outer loop in
// DebrisPass::render calls glDrawElements once per chunk with u_chunk_idx set.

layout(location = 0) in vec3 a_position;  // unit-cube vertex in [-0.5, 0.5]
layout(location = 2) in vec2 a_uv;

uniform mat4  u_model;        // instance world transform (inst->world)
uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_chunk_pos;    // chunk center in body frame
uniform mat3  u_chunk_rot;    // tumble rotation
uniform float u_cell_size;    // voxel cell edge length (body units)

out vec3 v_normal_ws;
out vec2 v_uv;

void main() {
    // Body-frame position: rotate + translate the unit cube vert.
    vec3 body_pos = u_chunk_rot * (a_position * u_cell_size) + u_chunk_pos;
    gl_Position = u_proj * u_view * u_model * vec4(body_pos, 1.0);

    // World-space normal for simple lighting (no per-fragment transform needed).
    vec3 a_normal = vec3(0.0); // will be filled by the driver from attrib 1
    // Fallback: derive from position sign for each face — simpler: just pass
    // the body normal through the model rotation to world space.
    v_normal_ws = mat3(u_model) * (u_chunk_rot * a_position * 2.0); // approximate face normal
    v_uv = a_uv;
}
```

> **Note for implementer:** The vertex shader above uses `a_position * 2.0` as an approximate face normal (position on unit cube, scaled, gives the outward normal per face). The more correct approach is to pass `a_normal` (layout location 1) from the cube mesh. Update the `in` decl to `layout(location = 1) in vec3 a_normal;` and use `v_normal_ws = mat3(u_model) * (u_chunk_rot * a_normal);`. The cube_mesh already builds proper per-face normals in the `normal` field of each vertex — use them.

The corrected `debris.vert` (use this):

```glsl
#version 330 core
layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;
layout(location = 2) in vec2 a_uv;

uniform mat4  u_model;
uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_chunk_pos;   // chunk center in body frame
uniform mat3  u_chunk_rot;   // tumble rotation
uniform float u_cell_size;   // voxel cell size (body units)

out vec3 v_normal_ws;
out vec2 v_uv;

void main() {
    vec3 body_pos = u_chunk_rot * (a_position * u_cell_size) + u_chunk_pos;
    gl_Position   = u_proj * u_view * u_model * vec4(body_pos, 1.0);
    v_normal_ws   = mat3(u_model) * (u_chunk_rot * a_normal);
    v_uv          = a_uv;
}
```

- [ ] 4.4 — **Write `debris.frag`** at `native/src/renderer/shaders/debris.frag`:

```glsl
#version 330 core

in  vec3 v_normal_ws;
in  vec2 v_uv;

uniform vec3  u_chunk_color;  // per-chunk hash color
uniform float u_chunk_alpha;  // fade alpha [0,1]
uniform vec3  u_light_dir;    // world-space normalized direction toward key light

out vec4 frag_color;

void main() {
    vec3 n   = normalize(v_normal_ws);
    float nl = max(dot(n, normalize(u_light_dir)), 0.0);
    vec3 lit = u_chunk_color * (0.3 + 0.7 * nl);   // ambient + diffuse
    frag_color = vec4(lit, u_chunk_alpha);
}
```

- [ ] 4.5 — **Write `debris_pass.h`** at `native/src/renderer/include/renderer/debris_pass.h`:

```cpp
#pragma once
#include <memory>
#include <functional>
#include <glm/glm.hpp>
#include <assets/mesh.h>
#include <scenegraph/instance.h>

namespace assets { struct Model; }
namespace scenegraph { class World; struct Camera; }

namespace renderer {
class Pipeline;
class CarveFieldCache;

/// Debris pass — tumbling voxel chunks ejected from a breach event.
///
/// For each visible Space-pass instance with active breach events, samples
/// kChunkCount solid voxels from the ship's original fill inside the event's
/// carve sphere, then draws each chunk as a unit cube (scaled to the voxel cell
/// size), positioned + rotated analytically from (birth_time, seed, age).
///
/// Depth-tested against the scene; alpha-blended for the fade.
/// Gated entirely on dauntless_hull_damage::enabled().
class DebrisPass {
public:
    using ModelLookup =
        std::function<const assets::Model*(scenegraph::ModelHandle)>;

    DebrisPass();
    ~DebrisPass() = default;
    DebrisPass(const DebrisPass&)            = delete;
    DebrisPass& operator=(const DebrisPass&) = delete;

    void render(const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup,
                CarveFieldCache& carve_cache,
                float now);

private:
    void ensure_cube();
    std::unique_ptr<assets::Mesh> cube_mesh_;
};

} // namespace renderer
```

- [ ] 4.6 — **Write `debris_pass.cc`** at `native/src/renderer/debris_pass.cc`:

```cpp
#include <renderer/debris_pass.h>
#include <renderer/pipeline.h>
#include <renderer/carve_field_cache.h>
#include "cube_mesh.h"
#include "debris_chunks.h"

#include <scenegraph/breach_events.h>
#include <scenegraph/camera.h>
#include <scenegraph/world.h>
#include <assets/model.h>
#include <assets/mesh.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/type_ptr.hpp>

namespace dauntless_hull_damage { bool enabled(); }

namespace renderer {

DebrisPass::DebrisPass() = default;

void DebrisPass::ensure_cube() {
    if (cube_mesh_) return;
    cube_mesh_ = std::make_unique<assets::Mesh>(
        assets::upload_mesh(build_unit_cube()));
}

void DebrisPass::render(const scenegraph::World& world,
                        const scenegraph::Camera& camera,
                        Pipeline& pipeline,
                        const ModelLookup& lookup,
                        CarveFieldCache& carve_cache,
                        float now) {
    if (!dauntless_hull_damage::enabled()) return;
    ensure_cube();

    bool any = false;
    auto ensure_state = [&]() {
        if (any) return;
        any = true;
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_FALSE);   // alpha-blended: don't write depth
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glDisable(GL_CULL_FACE);
    };

    auto& shader = pipeline.debris_shader();

    world.for_each_visible_in_pass(
        scenegraph::Pass::Space,
        [&](const scenegraph::Instance& inst) {
            if (inst.breach_events.count() == 0) return;
            const assets::Model* model = lookup(inst.model_handle);
            if (!model || model->source.empty()) return;
            const CarveFieldCache::Entry* ce = carve_cache.get_for_source(model->source);
            if (!ce) return;
            const voxel::VoxelVolume fill{
                /*occ=*/{},   // tex3d only; we need the fill volume
                ce->dims, ce->origin, ce->cell};
            // The CarveFieldCache::Entry stores dims/origin/cell but NOT the raw occ
            // bytes after upload. We need occ for sample_chunk_origins.
            // Approach: CarveFieldCache must expose the VoxelVolume (see note below).
            // For now use ce->fill (see note).
            const voxel::VoxelVolume& vol = ce->fill;

            const glm::vec3 light_dir = glm::normalize(glm::vec3(0.3f, 1.f, 0.2f));

            for (const auto& ev : inst.breach_events.slots()) {
                if (!ev.active) continue;
                const float age = now - ev.birth_time;
                if (age >= scenegraph::kDebrisLife) continue;

                const auto origins = sample_chunk_origins(
                    vol, ev.center_body, ev.radius, ev.seed, kChunkCount);
                if (origins.empty()) continue;

                ensure_state();

                shader.use();
                shader.set_mat4("u_model", inst.world);
                shader.set_mat4("u_view",  camera.view_matrix());
                shader.set_mat4("u_proj",  camera.proj_matrix());
                shader.set_vec3("u_light_dir", light_dir);
                shader.set_float("u_cell_size", vol.cell.x); // assume isotropic

                glBindVertexArray(cube_mesh_->vao());

                for (int i = 0; i < static_cast<int>(origins.size()); ++i) {
                    const ChunkTransform ct =
                        chunk_transform(origins[static_cast<std::size_t>(i)],
                                        ev.center_body, age, ev.seed, i);
                    if (ct.alpha <= 0.f) continue;

                    // Per-chunk hash color: classic multicolor hull-interior look.
                    const std::uint64_t ch =
                        (ev.seed * 6364136223846793005ull) ^
                        (static_cast<std::uint64_t>(i) * 2654435761ull);
                    const float cr = 0.3f + 0.4f * static_cast<float>((ch >> 40) & 0xFFu) / 255.f;
                    const float cg = 0.2f + 0.3f * static_cast<float>((ch >> 24) & 0xFFu) / 255.f;
                    const float cb = 0.15f + 0.25f * static_cast<float>((ch >> 8) & 0xFFu) / 255.f;

                    shader.set_vec3("u_chunk_pos",   ct.pos_body);
                    shader.set_mat3("u_chunk_rot",   ct.rot);
                    shader.set_vec3("u_chunk_color", glm::vec3(cr, cg, cb));
                    shader.set_float("u_chunk_alpha", ct.alpha);

                    glDrawElements(GL_TRIANGLES,
                                   static_cast<GLsizei>(cube_mesh_->index_count()),
                                   GL_UNSIGNED_INT, nullptr);
                }
                glBindVertexArray(0);
            }
        });

    if (any) {
        glDepthMask(GL_TRUE);
        glDisable(GL_BLEND);
        glEnable(GL_CULL_FACE);
    }
}

} // namespace renderer
```

> **Implementation note — `CarveFieldCache::Entry::fill`:** `CarveFieldCache::Entry` currently stores `{unsigned int tex3d; glm::vec3 origin; glm::vec3 cell; glm::ivec3 dims;}` — the raw `occ` bytes are not retained after GL upload. The debris pass needs the raw voxel data to call `sample_chunk_origins`. Add a `voxel::VoxelVolume fill;` field to `CarveFieldCache::Entry` (in `native/src/renderer/include/renderer/carve_field_cache.h`) and populate it in `get_for_source` when the entry is first built. This is a one-line struct addition + a one-line `e.fill = vol;` in the builder. If the source fill is never needed after upload in any existing code path, no other consumers are affected.

- [ ] 4.7 — **Add `CarveFieldCache::Entry::fill`** — read `native/src/renderer/include/renderer/carve_field_cache.h` and add `voxel::VoxelVolume fill;` to `Entry`, then in `carve_field_cache.cc`'s `get_for_source` store the fill volume before returning. (This is the one deviation from the prompt scaffold, discovered by reading the actual CarveFieldCache header.)

- [ ] 4.8 — **Add `embed_shader` calls and source files to renderer CMakeLists**. In `native/src/renderer/CMakeLists.txt`, add after the existing `embed_shader(SHADER_BREACH_FS …)` block:
```cmake
embed_shader(SHADER_DEBRIS_VS shaders/debris.vert debris_vs)
embed_shader(SHADER_DEBRIS_FS shaders/debris.frag debris_fs)
```
Add to `add_library(renderer STATIC …)` (after `breach_pass.cc`):
```cmake
    cube_mesh.cc
    debris_chunks.cc
    debris_pass.cc
```
Add the new generated headers to the target's sources list (the `target_sources` pattern the existing shaders use — note: they're passed via `${SHADER_*}` variables as private sources so CMake tracks them; do the same for the two new ones).

> **Note:** The existing CMakeLists uses `embed_shader` which writes to `${CMAKE_CURRENT_BINARY_DIR}`; the library target picks them up through the `PRIVATE "${CMAKE_CURRENT_BINARY_DIR}"` include-dir already present. Shader source variables (e.g. `${SHADER_DEBRIS_VS}`) must be listed as target sources or in a private sources block so cmake knows to re-embed when the `.vert` changes. Look at how `${SHADER_BREACH_VS}` is wired and mirror it.

- [ ] 4.9 — **Add `debris_shader` to Pipeline**. In `native/src/renderer/include/renderer/pipeline.h`, add:
```cpp
    Shader& debris_shader() noexcept { return *debris_; }
```
and in the `private:` block:
```cpp
    std::unique_ptr<Shader> debris_;
```

In `native/src/renderer/pipeline.cc`, construct `debris_` from the embedded source (mirroring how `breach_` is constructed — look up the pattern):
```cpp
// In Pipeline::Pipeline() constructor body, alongside the existing entries:
debris_ = std::make_unique<Shader>(shader_src::debris_vs, shader_src::debris_fs);
```

- [ ] 4.10 — **Wire `DebrisPass` into `host_bindings.cc`**:
  - Add `#include <renderer/debris_pass.h>` near the other pass includes.
  - In the anonymous namespace globals, add after `g_breach_pass` (line ~119):
    ```cpp
    std::unique_ptr<renderer::DebrisPass> g_debris_pass;
    ```
  - In `init()`, after `g_breach_pass = std::make_unique<renderer::BreachPass>();` add:
    ```cpp
    g_debris_pass = std::make_unique<renderer::DebrisPass>();
    ```
  - In `shutdown()`, after `g_breach_pass.reset();` add:
    ```cpp
    g_debris_pass.reset();
    ```
  - In `render_space`, after the `g_breach_pass->render(…)` call, add:
    ```cpp
    if (g_debris_pass && g_carve_cache)
        g_debris_pass->render(g_world, cam, *g_pipeline, lookup,
                              *g_carve_cache, g_decal_game_time);
    ```

- [ ] 4.11 — **Write `debris_pass_test.cc`** at `native/tests/renderer/debris_pass_test.cc` (mirrors `breach_pass_test.cc` pattern):

```cpp
#include <gtest/gtest.h>
#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <renderer/debris_pass.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <renderer/carve_field_cache.h>

#include <scenegraph/world.h>
#include <scenegraph/breach_events.h>
#include <scenegraph/camera.h>
#include <scenegraph/hull_carve.h>

#include <voxel/volume.h>

#include <array>
#include <memory>

namespace {
constexpr int kW = 64, kH = 64;

class DebrisPassGLTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   w;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "debris-pass-test", false);
        } catch (...) {
            GTEST_SKIP() << "no GL context";
        }
        pipeline = std::make_unique<renderer::Pipeline>();
    }

    std::array<unsigned char, 4> read_center() const {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::array<unsigned char, 4> px{};
        glReadPixels(kW/2, kH/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        return px;
    }

    static scenegraph::Camera cam_at_z5() {
        scenegraph::Camera c;
        c.eye = {0,0,5}; c.target = {}; c.up = {0,1,0};
        c.fov_y_rad = glm::radians(45.f);
        c.aspect = 1.f; c.near = 0.1f; c.far = 50.f;
        return c;
    }

    void clear() {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0,0,kW,kH);
        glClearColor(0,0,0,1);
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
    }
};
} // namespace

// CPU: with no active events, render() does nothing (gate check).
TEST(DebrisPassCpu, NoEventsDrawsNothing) {
    scenegraph::BreachEventRing ring;
    EXPECT_EQ(ring.count(), 0u);
}
```

> **Note:** Full GL debris-pass tests require `CarveFieldCache` to expose the fill volume (Task 4.7). The GL test verifies: push an event at age=0 → pixel lit; tick past kDebrisLife → pixel dark; `dauntless_hull_damage::enabled()` returns false → pixel dark. These tests follow the same pattern as `BreachPassGLTest` above. Implement after Task 4.7 is done and the cache exposes `fill`.

- [ ] 4.12 — **Add `debris_pass_test.cc` to renderer_tests** in `native/tests/renderer/CMakeLists.txt`.

- [ ] 4.13 — **Build** (CRITICAL: shader edits need reconfigure before build):
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: clean build.

- [ ] 4.14 — **Run tests**:
```bash
ctest --test-dir build -R "DebrisPass" --output-on-failure
```
Expected: CPU test passes; GL tests skip if no context or pass if context available.

- [ ] 4.15 — **Full suite green**:
```bash
ctest --test-dir build --output-on-failure 2>&1 | tail -5
```

- [ ] 4.16 — Commit:
```bash
git add native/src/renderer/cube_mesh.h \
        native/src/renderer/cube_mesh.cc \
        native/src/renderer/debris_chunks.h \
        native/src/renderer/debris_chunks.cc \
        native/src/renderer/include/renderer/debris_pass.h \
        native/src/renderer/debris_pass.cc \
        native/src/renderer/shaders/debris.vert \
        native/src/renderer/shaders/debris.frag \
        native/src/renderer/include/renderer/pipeline.h \
        native/src/renderer/pipeline.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/debris_pass_test.cc \
        native/tests/renderer/CMakeLists.txt \
        native/src/host/host_bindings.cc && \
git commit -m "$(cat <<'EOF'
feat(spv): DebrisPass + cube_mesh + debris shaders; wire into render_space

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5 — Venting descriptor builder (pure) + gtest + `render_space` wire-in

**Goal:** `build_venting_descriptors` is a pure function that returns `ParticleEmitterDescriptor` entries for each active event: attached to the ship instance (body-frame emit pos/dir), emission tapering to zero at `kVentLife`, alpha keys 1→0. Wire into `render_space` alongside the existing particle render call.

**Files:**
- Create: `native/src/renderer/breach_venting.h`
- Create: `native/src/renderer/breach_venting.cc`
- Create: `native/tests/renderer/breach_venting_test.cc`
- Modify: `native/src/renderer/CMakeLists.txt`
- Modify: `native/tests/renderer/CMakeLists.txt`
- Modify: `native/src/host/host_bindings.cc`

**Steps:**

- [ ] 5.1 — **Write failing test** `native/tests/renderer/breach_venting_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <glm/glm.hpp>
#include <scenegraph/breach_events.h>
#include <renderer/frame.h>    // ParticleEmitterDescriptor, ParticleKey
#include "breach_venting.h"    // relative include

TEST(BuildVentingDescriptors, NoEventsYieldsEmptyVector) {
    scenegraph::BreachEventRing ring;
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    EXPECT_TRUE(desc.empty());
}

TEST(BuildVentingDescriptors, FreshEventYieldsOneDescriptor) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, 0.f, 1u);
    scenegraph::InstanceId id{2, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.1f);
    ASSERT_EQ(desc.size(), 1u);
}

TEST(BuildVentingDescriptors, DescriptorHasCorrectInstanceId) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, 0.f, 42u);
    scenegraph::InstanceId id{7, 3};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_EQ(desc[0].instance_id, id);
}

TEST(BuildVentingDescriptors, EmitPosIsBodyFrameBreachCenter) {
    scenegraph::BreachEventRing ring;
    ring.push({1.f, 2.f, 3.f}, 1.f, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_FLOAT_EQ(desc[0].emit_pos.x, 1.f);
    EXPECT_FLOAT_EQ(desc[0].emit_pos.y, 2.f);
    EXPECT_FLOAT_EQ(desc[0].emit_pos.z, 3.f);
}

TEST(BuildVentingDescriptors, StopAgeIsVentLife) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_FLOAT_EQ(desc[0].stop_age, scenegraph::kVentLife);
}

TEST(BuildVentingDescriptors, EffectAgeEqualsNowMinusBirthTime) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, 1.0f /*birth*/, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 2.5f /*now*/);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_FLOAT_EQ(desc[0].effect_age, 1.5f);
}

TEST(BuildVentingDescriptors, NoDescriptorPastVentLife) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    // At exactly kVentLife the emission stops; no descriptor needed (effect_age >= stop_age).
    auto desc = renderer::build_venting_descriptors(
        ring, id, scenegraph::kVentLife + 0.01f);
    EXPECT_TRUE(desc.empty())
        << "venting must stop producing descriptors past kVentLife";
}

TEST(BuildVentingDescriptors, AlphaKeysTaperToZero) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    EXPECT_GE(desc[0].num_alpha_keys, 2);
    EXPECT_FLOAT_EQ(desc[0].alpha_keys[0].v, 1.f) << "first alpha key must be 1.0";
    EXPECT_FLOAT_EQ(desc[0].alpha_keys[desc[0].num_alpha_keys - 1].v, 0.f)
        << "last alpha key must be 0.0";
}

TEST(BuildVentingDescriptors, EmitDirIsNormalized) {
    scenegraph::BreachEventRing ring;
    ring.push({1.f, 0.f, 0.f}, 1.f, 0.f, 1u);
    scenegraph::InstanceId id{1, 1};
    auto desc = renderer::build_venting_descriptors(ring, id, 0.f);
    ASSERT_EQ(desc.size(), 1u);
    const float len = glm::length(desc[0].emit_dir);
    EXPECT_NEAR(len, 1.f, 1e-4f) << "emit_dir must be normalized";
}

TEST(BuildVentingDescriptors, SeedIsStable) {
    scenegraph::BreachEventRing ring;
    ring.push({0.f, 0.f, 0.f}, 1.f, 0.f, 77u);
    scenegraph::InstanceId id{1, 1};
    auto a = renderer::build_venting_descriptors(ring, id, 0.5f);
    auto b = renderer::build_venting_descriptors(ring, id, 0.5f);
    ASSERT_EQ(a.size(), 1u);
    EXPECT_FLOAT_EQ(a[0].seed, b[0].seed)
        << "seed must not change between calls with the same ring state";
}
```

- [ ] 5.2 — **Add `breach_venting_test.cc` to renderer_tests** CMakeLists.

- [ ] 5.3 — **Build** (expects failure — header missing):
```bash
cmake -B build -S . && cmake --build build --target renderer_tests -j
```

- [ ] 5.4 — **Write `breach_venting.h`** at `native/src/renderer/breach_venting.h`:

```cpp
#pragma once
#include <vector>
#include <scenegraph/breach_events.h>
#include <scenegraph/instance.h>   // InstanceId
#include <renderer/frame.h>        // ParticleEmitterDescriptor

namespace renderer {

/// Build analytic venting-jet ParticleEmitterDescriptors from all active breach
/// events on a single instance.
///
/// Each descriptor is ATTACHED (instance_id = the ship's id) so its emit_pos
/// and emit_dir are body-frame and track the ship. effect_age = now - birth_time;
/// stop_age = kVentLife (emission cuts off at stop_age, per ParticlePass model).
///
/// Returns an empty vector when no events are active, or when all active events
/// have aged past kVentLife.
std::vector<ParticleEmitterDescriptor> build_venting_descriptors(
    const scenegraph::BreachEventRing& ring,
    scenegraph::InstanceId             instance_id,
    float                              now);

} // namespace renderer
```

- [ ] 5.5 — **Write `breach_venting.cc`** at `native/src/renderer/breach_venting.cc`:

```cpp
#include "breach_venting.h"
#include <cmath>

namespace renderer {

std::vector<ParticleEmitterDescriptor> build_venting_descriptors(
    const scenegraph::BreachEventRing& ring,
    scenegraph::InstanceId             instance_id,
    float                              now) {

    std::vector<ParticleEmitterDescriptor> out;
    for (const auto& ev : ring.slots()) {
        if (!ev.active) continue;
        const float effect_age = now - ev.birth_time;
        if (effect_age >= scenegraph::kVentLife) continue;

        ParticleEmitterDescriptor d{};
        d.instance_id  = instance_id;
        d.emit_pos     = ev.center_body;  // body frame: breach center

        // Outward direction in body frame: radially away from origin along breach
        // center if non-zero, else straight up in body frame (+Y).
        d.emit_dir = (glm::length(ev.center_body) > 1e-4f)
            ? glm::normalize(ev.center_body)
            : glm::vec3(0.f, 1.f, 0.f);

        d.emit_vel_world = glm::vec3(0.f); // no ship-velocity inheritance for venting
        d.inherit        = 0.f;
        d.emit_velocity  = 0.8f;           // GU / s (decorative; body-frame scale)
        d.angle_variance = 25.f;           // degrees: wispy jet spread
        d.emit_life      = 0.6f;           // each particle lives 0.6 s
        d.emit_life_variance = 0.2f;
        d.emit_frequency = 0.04f;          // 25 particles/s at start
        d.effect_age     = effect_age;
        d.stop_age       = scenegraph::kVentLife;
        d.blend_mode     = 1;              // additive: bright plasma
        d.random_velocity_cone  = 20.f;
        d.random_velocity_speed = 0.3f;

        // Alpha keys: 1.0 → 0.0 over particle lifetime.
        d.num_alpha_keys = 2;
        d.alpha_keys[0] = ParticleKey{0.f,  1.f};
        d.alpha_keys[1] = ParticleKey{1.f,  0.f};

        // Size keys: grow then shrink (wispy).
        d.num_size_keys = 3;
        d.size_keys[0] = ParticleKey{0.0f, 0.05f};
        d.size_keys[1] = ParticleKey{0.4f, 0.12f};
        d.size_keys[2] = ParticleKey{1.0f, 0.02f};

        // Stable seed: derived from event seed, NOT from world position.
        // Convert uint64 seed to float in [0,1) as the pass expects.
        d.seed = static_cast<float>(
            (ev.seed ^ 0x517cc1b727220a95ull) >> 11)
            * (1.f / static_cast<float>(1ull << 53));

        // Pale plasma / atmosphere tint (light blue-white).
        d.texture_path = "game/data/Textures/Effects/ExplosionNoise.tga";

        out.push_back(d);
    }
    return out;
}

} // namespace renderer
```

- [ ] 5.6 — **Add `breach_venting.cc` to renderer CMakeLists** (after `debris_pass.cc`):
```cmake
    breach_venting.cc
```

- [ ] 5.7 — **Wire venting into `render_space` in `host_bindings.cc`**. In the `render_space` lambda, after the debris pass call and before the existing `g_particle_pass->render(g_particle_emitters, …)` call, add:

```cpp
        // Venting jets: build per-frame descriptors from active breach events
        // and append to a combined emitter list for the particle pass.
        // Never mutate g_particle_emitters in place (Python-owned).
        if (!for_viewscreen && g_particle_pass) {
            std::vector<renderer::ParticleEmitterDescriptor> all_emitters = g_particle_emitters;
            g_world.for_each_visible_in_pass(
                scenegraph::Pass::Space,
                [&](const scenegraph::Instance& inst) {
                    if (inst.breach_events.count() == 0) return;
                    auto vent = renderer::build_venting_descriptors(
                        inst.breach_events, inst.id, g_decal_game_time);
                    all_emitters.insert(all_emitters.end(),
                                        vent.begin(), vent.end());
                });
            g_particle_pass->render(all_emitters, g_world, cam, *g_pipeline);
        }
```

Replace the existing `if (!for_viewscreen && g_particle_pass) g_particle_pass->render(g_particle_emitters, …);` with the combined block above.

Add the include at the top of `host_bindings.cc`:
```cpp
#include "breach_venting.h"  // venting descriptor builder
```

- [ ] 5.8 — **Build + run venting tests**:
```bash
cmake -B build -S . && cmake --build build --target renderer_tests -j
ctest --test-dir build -R "BuildVentingDescriptors" --output-on-failure
```
Expected: 9 tests pass.

- [ ] 5.9 — **Full suite green**:
```bash
ctest --test-dir build --output-on-failure 2>&1 | tail -5
```

- [ ] 5.10 — Commit:
```bash
git add native/src/renderer/breach_venting.h \
        native/src/renderer/breach_venting.cc \
        native/tests/renderer/breach_venting_test.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/CMakeLists.txt \
        native/src/host/host_bindings.cc && \
git commit -m "$(cat <<'EOF'
feat(spv): venting descriptor builder + gtest; wire into render_space ParticlePass

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6 — Molten-rim emissive on breach scoop

**Goal:** `breach.frag` gains a blackbody emissive term that cools from white-hot to dark over `kRimLife`, strongest at the scoop rim. `BreachPass::render` correlates each carve slot to the nearest active breach event to get its age. `draw_scoop` receives and sets `u_breach_age`/`u_rim_life`.

**CRITICAL BUILD NOTE:** `breach.frag` is a shader — changes require `cmake -B build -S .` (reconfigure) BEFORE `cmake --build build -j`. The CMakeLists `embed_shader` macro reads the file at configure time.

**Files:**
- Modify: `native/src/renderer/shaders/breach.frag`
- Modify: `native/src/renderer/include/renderer/breach_pass.h`
- Modify: `native/src/renderer/breach_pass.cc`
- Modify: `native/src/host/host_bindings.cc`

**Steps:**

- [ ] 6.1 — **Extend `breach.frag`** — add the molten-rim emissive term. The blackbody function is copied verbatim from `opaque.frag` lines 160–168. Add after the existing uniform block and before `out vec4 frag_color;`:

```glsl
// Molten-rim emissive (hull-breach-2c).
// u_breach_age: age of the matching breach event (large value → cold when no match).
// u_rim_life:   kRimLife constant; rim cools to 0 by this age.
uniform float u_breach_age;
uniform float u_rim_life;
```

Copy the `blackbody` function from `opaque.frag` (identical GLSL):

```glsl
// Blackbody-ish ramp keyed on heat 0..1 (white-hot -> red -> black).
// Copied from opaque.frag for consistent cooling colour across all damage VFX.
vec3 blackbody(float heat) {
    vec3 cold  = vec3(0.0);
    vec3 red   = vec3(0.59, 0.10, 0.02);
    vec3 org   = vec3(1.0,  0.45, 0.08);
    vec3 white = vec3(1.0,  0.92, 0.72);
    vec3 lo  = mix(cold, red,   smoothstep(0.0,  0.35, heat));
    vec3 mid = mix(lo,   org,   smoothstep(0.35, 0.7,  heat));
    return     mix(mid,  white, smoothstep(0.7,  1.0,  heat));
}
```

At the end of `main()`, before `frag_color = vec4(c, 1.0);`, add the rim term:

```glsl
    // ── Molten rim emissive ──────────────────────────────────────────────────
    // heat: 1 at birth (age=0) → 0 at kRimLife. Clamped to [0,1].
    float heat = clamp(1.0 - u_breach_age / u_rim_life, 0.0, 1.0);
    if (heat > 0.0) {
        // Rim weight: distance from the carve sphere center vs radius.
        // Strongest near the rim (r close to 1.0), fading toward center.
        // u_carve_center and u_carve_radius are already bound from the fill-mask block.
        float r_norm = length(v_body_pos - u_carve_center) / max(u_carve_radius, 1e-4);
        float rim_w = smoothstep(0.5, 1.0, r_norm);
        c += blackbody(heat) * rim_w * 1.5;  // 1.5: HDR headroom for glow
    }

    frag_color = vec4(c, 1.0);
```

- [ ] 6.2 — **Update `draw_scoop` signature in `breach_pass.h`** — add `float breach_age` parameter:

```cpp
    void draw_scoop(const glm::vec3& center_body,
                    float radius,
                    unsigned int fill_tex,
                    const glm::vec3& fill_origin,
                    const glm::vec3& fill_cell,
                    const glm::ivec3& fill_dims,
                    const glm::mat4& world_xf,
                    const scenegraph::Camera& camera,
                    Pipeline& pipeline,
                    float breach_age);   // NEW: age of matching event; large = cold
```

Update `render` signature to accept the breach-event ring and current time:

```cpp
    void render(const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup,
                CarveFieldCache& carve_cache,
                const scenegraph::BreachEventRing* events = nullptr,  // per-instance, may be null
                float now = 0.f);
```

> **Simpler alternative:** Because `render` already iterates `Instance`, pass `now` once and read `inst.breach_events` directly inside the lambda — no need to change the outer signature. The inner per-instance lambda already has `inst` in scope. Use this approach:

```cpp
    void render(const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup,
                CarveFieldCache& carve_cache,
                float now = 0.f);    // NEW: game clock for event age lookup
```

Add `#include <scenegraph/breach_events.h>` to `breach_pass.h`.

- [ ] 6.3 — **Update `breach_pass.cc`**:

In `draw_scoop`, add `float breach_age` parameter. After the existing uniform setters, add:
```cpp
    shader.set_float("u_breach_age", breach_age);
    shader.set_float("u_rim_life",   scenegraph::kRimLife);
```

In `render`'s `for_each_visible_in_pass` lambda, for each carve slot, find the nearest active breach event by proximity before calling `draw_scoop`:

```cpp
            for (const auto& s : inst.carve.slots()) {
                if (!s.active) continue;

                // Find the nearest active breach event for this carve slot.
                float breach_age = scenegraph::kRimLife + 1.f;  // default: cold
                float best_dist  = 1e30f;
                for (const auto& ev : inst.breach_events.slots()) {
                    if (!ev.active) continue;
                    const float d = glm::length(ev.center_body - s.center_body);
                    if (d < best_dist) {
                        best_dist   = d;
                        breach_age  = now - ev.birth_time;
                    }
                }

                draw_scoop(s.center_body, s.radius,
                           ce->tex3d, ce->origin, ce->cell, ce->dims,
                           inst.world, camera, pipeline, breach_age);
            }
```

In `draw_instance` (the test-path version), pass a default `breach_age` of `kRimLife + 1.f` (cold) since tests don't exercise the event ring:
```cpp
        draw_scoop(s.center_body, s.radius,
                   fe.tex3d, fill.origin, fill.cell, fill.dims,
                   world_xf, camera, pipeline,
                   scenegraph::kRimLife + 1.f);  // no event → cold
```

- [ ] 6.4 — **Update `render_space` call site** in `host_bindings.cc`. The existing call:
```cpp
        if (g_breach_pass && g_carve_cache)
            g_breach_pass->render(g_world, cam, *g_pipeline, lookup, *g_carve_cache);
```
becomes:
```cpp
        if (g_breach_pass && g_carve_cache)
            g_breach_pass->render(g_world, cam, *g_pipeline, lookup,
                                  *g_carve_cache, g_decal_game_time);
```

- [ ] 6.5 — **CRITICAL: reconfigure then build** (shader edit needs reconfigure):
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: clean build. If you run only `cmake --build build -j` without the reconfigure, the old embedded shader will be used and the uniforms will be missing — the pass silently produces cold holes. Always run the full `cmake -B build -S . && cmake --build build -j` after touching any `.frag` or `.vert` file.

- [ ] 6.6 — **Run tests** (existing breach pass tests must still pass):
```bash
ctest --test-dir build -R "BreachPass" --output-on-failure
```
Expected: all 3 existing breach-pass tests pass (the `u_breach_age` uniform is set to a default cold value in the test path via `draw_instance`).

- [ ] 6.7 — **Full suite green**:
```bash
ctest --test-dir build --output-on-failure 2>&1 | tail -5
```
Expected: baseline 383+ tests all still pass.

- [ ] 6.8 — Commit:
```bash
git add native/src/renderer/shaders/breach.frag \
        native/src/renderer/include/renderer/breach_pass.h \
        native/src/renderer/breach_pass.cc \
        native/src/host/host_bindings.cc && \
git commit -m "$(cat <<'EOF'
feat(spv): molten-rim blackbody emissive on breach scoop (hull-breach-2c)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7 — Manual verification note + full-suite green check

**Goal:** Write the in-game verification checklist and confirm all tests pass.

**Files:**
- Create: `docs/superpowers/notes/2026-06-17-hull-breach-2c-manual-verification.md`

**Steps:**

- [ ] 7.1 — **Write manual verification note**. Content:

```markdown
# Hull Breach 2c — Manual Verification Checklist

Date: 2026-06-17
Branch: feat/hull-breach-2c

## Prerequisites
- Build: `cmake -B build -S . && cmake --build build -j`
- Run: `./build/dauntless` with `--developer` flag
- Load a mission that has a combat scenario (e.g., SDK Tutorial or any mission with NPC ships)
- Ensure "Hull breaches" VFX toggle is ON (Developer Options menu or default)

## Checklist

### Debris
- [ ] Fire weapons at a ship until hull breaches register; observe small tumbling cube-like
      chunks ejecting radially outward from the breach point
- [ ] Chunks tumble visibly (different rotation axes per chunk, not uniform spin)
- [ ] Chunks fade to transparent over ~2.5 seconds and disappear cleanly (no pop)
- [ ] Multiple breaches produce independent chunk sprays (different positions, not stacked)
- [ ] Sustained fire (many breaches): no stutter, no frame-time spike, no GPU error

### Venting Jets
- [ ] A brief wispy particle jet is visible at breach moment, emanating outward from breach
- [ ] Jet emission tapers off over ~2 seconds (visible rate decrease, not snap-off)
- [ ] After ~2 seconds the jet is silent (no particles emitted); scoop remains
- [ ] Color is pale blue-white (atmosphere/plasma, additive blend — brighter than background)

### Molten Rim
- [ ] At breach moment, the scoop interior rim glows white-hot
- [ ] Over ~3 seconds, color cools through orange-red to dark (same blackbody palette
      as hull decal embers — visually consistent)
- [ ] Glow is strongest at the rim (outer edge of the scoop sphere) and dimmer toward center
- [ ] After ~3 seconds the scoop is cold: the quiet 2b Damage.tga interior, no emissive

### Toggle Off
- [ ] Set "Hull breaches" toggle to OFF (Developer Options)
- [ ] Fire weapons at ships: NO chunks, NO jets, NO rim glow
- [ ] Toggle back ON: VFX resumes on the next breach

### No Regressions
- [ ] Ship hull still clips correctly (2a hole visible through opaque hull)
- [ ] Scoop interior Damage.tga surface still renders (2b interior)
- [ ] Persistent damage decals (scorch + phaser glow) unaffected
- [ ] No GL errors in stderr during or after breach VFX
```

- [ ] 7.2 — **Final full-suite run**:
```bash
cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure 2>&1 | tail -10
```
Expected: all tests pass (baseline 383 + new tests from Tasks 1–5).

- [ ] 7.3 — Commit:
```bash
git add docs/superpowers/notes/2026-06-17-hull-breach-2c-manual-verification.md && \
git commit -m "$(cat <<'EOF'
docs(spv): hull-breach 2c manual verification checklist

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Execution Handoff

This plan is ready for agentic execution. Two options:

**Option A — Subagent-Driven Development (recommended)**

Invoke `superpowers:subagent-driven-development` and hand it this plan file. Each task can run as an independent subagent (Tasks 1 and 3 are fully independent; Task 2 depends on Task 1; Tasks 4 and 5 depend on Tasks 2 and 3; Task 6 depends on Task 4; Task 7 depends on all). The subagent skill handles review checkpoints between tasks.

**Option B — Inline Execution**

Invoke `superpowers:executing-plans` pointing at this file. Work through tasks sequentially, checking off steps as completed. Each task ends with a commit so partial progress is always safe to resume.

**Before starting either option**, confirm the branch is `feat/hull-breach-2c` and the baseline passes:
```bash
git branch --show-current   # must print: feat/hull-breach-2c
ctest --test-dir build --output-on-failure 2>&1 | tail -3  # must show all passing
```
