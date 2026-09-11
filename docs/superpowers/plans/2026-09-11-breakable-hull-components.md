# Breakable Hull Components Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a carve disconnects a piece of a breakable hull, that piece separates into a persistent, tumbling, colliding chunk rendered as the original mesh with a torn face; the death cascade cuts with swept capsules so a dying ship can part at the neck or saucer.

**Architecture:** Connectivity is a BFS in the voxel library over `baked_hull_sdf <= 0 AND damage <= 0`. A detached component becomes a second renderer instance of the same model with its own damage field (component cells copied from the parent, everything else fully carved) — the existing hull clip and interior raymarch draw both halves and the cut face with no shader change. A lightweight Python `DebrisChunk` is the physical body, integrated in Python and registered with the existing collision system. The cascade's capsule is a field-only brush: it never enters the sphere list, because plan 2c made the field the hole authority beyond tracked carves.

**Tech Stack:** C++20 (`native/src/voxel`, `native/src/renderer`, `native/src/host` pybind11), Python 3.11 (`engine/appc`), GoogleTest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-breakable-hull-components-design.md`

## Global Constraints

1. **The atlas carries DAMAGE, not hull geometry.** Every instance field cell starts at `-127`; only a brush raises it. `+127` means "fully carved". A cell is *occupied* iff `baked.dist <= 0 && damage.dist <= 0` (spec §3).
2. **The chunk is pure field — it gets NO sphere-list entries.** Do not touch `HullCarveField`, `u_carve_spheres`, or `opaque.frag`'s sphere block for anything in this plan.
3. **The capsule never enters the sphere list either.** It is carved into the instance field only.
4. **Never add a `sampler3D` to `opaque.frag`.** No shader changes are expected in this plan at all; if a task finds it needs one, STOP and report.
5. **Every brush stays monotonic:** `d_new = max(d_old, brush)`; never inspect `d_old` to decide anything.
6. **Never launch the game.** Verification is via test binaries.
7. **Shared checkout rules apply to the worktree too** — explicit pathspecs only; never `git add -A`/`.`; never restore from index/HEAD; back up a probe mutation by `cp`, restore by `cp`, prove with `diff`.
8. Build from the worktree root: `cmake --build build -j` (reconfigure `cmake -B build -S . -DPython3_EXECUTABLE=$PWD/.venv/bin/python3` only if CMakeLists change). Never run cmake inside `native/`.
9. Gate: `./scripts/check_tests.sh` — **read its OUTPUT**; it prints `NEW FAILURES (not in baseline)` on regression. Only `test_shield_level_change_announces` is baselined.
10. Never spell `game` or `sdk` as a path segment. 1 GU = 175 m; 1 model unit = `BC_MODEL_SCALE` = 0.01 GU.
11. Commit messages end with:
    `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## Where things are today (read before Task 1)

- `voxel::DistanceField` (`native/src/voxel/include/voxel/distance_field.h`): `dims`, `origin`, `cell`, `scale`, `dist` (int8, `<= 0` inside / not carved), `index(x,y,z)`, `empty()`.
- `voxel::field_carve_oblate` (`field_brush.{h,cc}`): the one brush. Constants `kCarveDepthFactor`, `kCarveRimAmp`, `kCarveDepthFloorCells`, `kCarveFieldOffsetCells`.
- `renderer::InstanceFieldCache` (`native/src/renderer/{include/renderer,}/instance_field_cache.{h,cc}`): per-instance damage fields keyed by `scenegraph::InstanceId`; `carve()`, `get()`, `forget()`; private `instances_` map of `Instance{ field, dirty, pub }`; `bake_cache_` for the shared baked hull SDF via `HullVolumeCache::get(source, authored_res, kDefaultQuality)`.
- Host binding `hull_carve_add` (`native/src/host/host_bindings.cc:4127`): resolves `inst = g_world.get(id)`, `model = resolve_model(inst->model_handle)`, `source = model->source`, `authored_res = renderer::hull_volume_resolution(source)`, uniform scale `s = length(inst->world[0])`, `world_to_body` / `world_dir_to_body`. Global `g_instance_field_cache`. `g_world.create_instance(handle)` creates a renderer instance.
- Python: `host_io.hull_carve_add` (`engine/host_io.py:287`); two emission sites — combat in `hit_feedback.py` (~line 417) and authored/cascade in `visible_damage._advance_one` (`engine/appc/visible_damage.py:106`). `death_cascade._fire` calls `ship.AddDamage`, which queues via `visible_damage.queue_world_carve`.
- Collision: `collisions.iter_collidables()` yields `ShipClass`/`Planet`; `_resolve_body` reads `GetWorldLocation/GetRadius/GetMass/GetVelocity/IsImmobile/GetWorldRotation` and the `__dict__` slots `_collision_velocity`, `_current_angular_velocity`.
- Transforms: `host_loop._world_matrix_from(loc, rot, s)` builds the row-major mat4; ships use flat `BC_MODEL_SCALE * ship.GetScale()`. `renderer.set_world_transform(iid, mat)` pushes it.
- Mission swap clears: `host_loop.py:5187` calls `ship_death.reset()`.
- Gate: `damage_geometry.breakables_allowed_for(ship)` (plan 1).

## File structure

| File | Responsibility |
|---|---|
| `native/src/voxel/{include/voxel,src}/hull_connectivity.{h,cc}` | Occupancy BFS → components (Task 1) |
| `native/src/voxel/{include/voxel,src}/field_brush.{h,cc}` | `field_carve_capsule` (Task 2) |
| `native/src/renderer/{include/renderer,}/instance_field_cache.{h,cc}` | `field()`, `split()`, `remove_cells()`, `carve_capsule()` (Task 3) |
| `native/src/host/host_bindings.cc` | `hull_split_detached`, `hull_carve_capsule` (Task 4) |
| `engine/host_io.py` | wrappers for both (Task 4) |
| `engine/appc/debris_chunk.py` (new) | `DebrisChunk`, registry, tick, cap, clear (Task 5) |
| `engine/appc/collisions.py` | `iter_collidables` yields chunks (Task 5) |
| `engine/host_loop.py` | tick + transform push; clear on swap (Task 5) |
| `engine/appc/hull_breakup.py` (new) | `after_carve()`: split, spawn, subsystems (Task 6) |
| `engine/appc/hit_feedback.py`, `engine/appc/visible_damage.py` | call `after_carve` after each carve (Task 6) |
| `engine/appc/visible_damage.py`, `engine/appc/death_cascade.py` | queued capsule cut (Task 7) |
| `tests/unit/test_breakables_gating.py` (new) | fleet gate (Task 8) |

---

### Task 1: Connectivity — occupancy BFS in the voxel library

**Files:**
- Create: `native/src/voxel/include/voxel/hull_connectivity.h`
- Create: `native/src/voxel/src/hull_connectivity.cc`
- Modify: `native/src/voxel/CMakeLists.txt` (add the .cc to the `voxel` target's sources)
- Test: `native/tests/voxel/hull_connectivity_test.cc` (new; add to `native/tests/voxel/CMakeLists.txt`'s `voxel_tests` sources)

**Interfaces:**
- Consumes: `voxel::DistanceField`.
- Produces:
  ```cpp
  namespace voxel {
  struct HullComponent {
      std::uint32_t label;              // 1..N; 0 is the main body
      std::size_t   cells;
      glm::vec3     centroid_body;      // model units
      glm::vec3     bounds_min_body;    // model units, cell-centre extents
      glm::vec3     bounds_max_body;
      std::vector<glm::ivec3> cell_list;
  };
  struct ConnectivityResult {
      std::size_t main_body_cells = 0;
      std::vector<HullComponent> detached;   // empty when nothing severed
  };
  ConnectivityResult hull_connectivity(const DistanceField& baked,
                                       const DistanceField& damage);
  }
  ```

**Background.** A cell is occupied iff `baked.dist[i] <= 0 && damage.dist[i] <= 0`. Seed = the occupied cell whose centre is nearest the body-frame origin; if no occupied cell exists, return empty. BFS with 6-connectivity marks the main body. A second pass labels every unreached occupied cell into components. Dimensions must match exactly (`baked.dims == damage.dims`) or the function returns an empty result — the instance field copies the baked lattice by construction (`instance_field_cache.cc`), so a mismatch is a caller bug, not a case to tolerate silently; assert it in debug and return empty in release.

- [ ] **Step 1: Write the failing test**

```cpp
// native/tests/voxel/hull_connectivity_test.cc
#include <gtest/gtest.h>
#include <voxel/hull_connectivity.h>

namespace {

// A dumbbell: two 5x5x5 blobs on the x axis joined by a one-cell neck.
// Everything else is "outside" (+127 in the baked field).
voxel::DistanceField make_dumbbell_baked() {
    voxel::DistanceField f;
    f.dims = glm::ivec3(17, 7, 7);
    f.cell = glm::vec3(1.0f);
    f.origin = glm::vec3(0.0f);
    f.scale = 1.0f;
    f.dist.assign(17u * 7u * 7u, static_cast<std::int8_t>(127));
    auto inside = [&](int x, int y, int z) { f.dist[f.index(x, y, z)] = -10; };
    for (int z = 1; z <= 5; ++z)
    for (int y = 1; y <= 5; ++y) {
        for (int x = 1; x <= 5; ++x)   inside(x, y, z);      // left blob
        for (int x = 11; x <= 15; ++x) inside(x, y, z);      // right blob
    }
    for (int x = 6; x <= 10; ++x) inside(x, 3, 3);            // the neck
    return f;
}

voxel::DistanceField undamaged_like(const voxel::DistanceField& baked) {
    voxel::DistanceField d = baked;
    d.dist.assign(baked.dist.size(), static_cast<std::int8_t>(-127));
    return d;
}

}  // namespace

TEST(HullConnectivity, IntactDumbbellIsOneBody) {
    const auto baked = make_dumbbell_baked();
    const auto damage = undamaged_like(baked);
    const auto r = voxel::hull_connectivity(baked, damage);
    EXPECT_EQ(r.main_body_cells, 125u + 125u + 5u);
    EXPECT_TRUE(r.detached.empty());
}

TEST(HullConnectivity, SeveringTheNeckDetachesTheFarBlob) {
    const auto baked = make_dumbbell_baked();
    auto damage = undamaged_like(baked);
    damage.dist[damage.index(8, 3, 3)] = 127;   // cut the neck at its middle
    const auto r = voxel::hull_connectivity(baked, damage);
    // Seed is nearest the origin -> the LEFT blob plus its half of the neck
    // is the main body; the right blob plus its half of the neck detaches.
    EXPECT_EQ(r.main_body_cells, 125u + 2u);
    ASSERT_EQ(r.detached.size(), 1u);
    const auto& c = r.detached[0];
    EXPECT_EQ(c.cells, 125u + 2u);
    EXPECT_EQ(c.cell_list.size(), c.cells);
    // Centroid of the right blob (x 11..15, centres 11.5..15.5 -> 13.5) is
    // pulled slightly left by the two neck cells at x=9,10.
    EXPECT_NEAR(c.centroid_body.x, (125.0f * 13.5f + 9.5f + 10.5f) / 127.0f, 1e-4f);
    EXPECT_NEAR(c.centroid_body.y, 3.5f, 1e-4f);
    EXPECT_NEAR(c.centroid_body.z, 3.5f, 1e-4f);
    EXPECT_FLOAT_EQ(c.bounds_min_body.x, 9.5f);
    EXPECT_FLOAT_EQ(c.bounds_max_body.x, 15.5f);
}

TEST(HullConnectivity, CarvedSeedFallsBackToAnOccupiedCell) {
    // Carve everything near the origin; the fill must still find the body.
    const auto baked = make_dumbbell_baked();
    auto damage = undamaged_like(baked);
    for (int z = 1; z <= 5; ++z) for (int y = 1; y <= 5; ++y)
        damage.dist[damage.index(1, y, z)] = 127;
    const auto r = voxel::hull_connectivity(baked, damage);
    EXPECT_EQ(r.main_body_cells, 100u + 125u + 5u);
    EXPECT_TRUE(r.detached.empty());
}

TEST(HullConnectivity, MismatchedLatticesReturnEmpty) {
    const auto baked = make_dumbbell_baked();
    voxel::DistanceField damage = undamaged_like(baked);
    damage.dims = glm::ivec3(16, 7, 7);
    damage.dist.resize(16u * 7u * 7u);
    const auto r = voxel::hull_connectivity(baked, damage);
    EXPECT_EQ(r.main_body_cells, 0u);
    EXPECT_TRUE(r.detached.empty());
}
```

- [ ] **Step 2: Register the test and run it to verify it fails**

Add `hull_connectivity_test.cc` to the `voxel_tests` source list in `native/tests/voxel/CMakeLists.txt`. Then:

```bash
cmake --build build -j --target voxel_tests 2>&1 | tail -5
```

Expected: build FAILS — `voxel/hull_connectivity.h` not found.

- [ ] **Step 3: Implement**

`native/src/voxel/include/voxel/hull_connectivity.h`:

```cpp
// native/src/voxel/include/voxel/hull_connectivity.h
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include <glm/glm.hpp>

#include <voxel/distance_field.h>

namespace voxel {

/// One detached piece of hull: every occupied cell NOT reachable from the
/// main body's seed by 6-connectivity.
struct HullComponent {
    std::uint32_t label = 0;                 // 1..N (0 is the main body)
    std::size_t   cells = 0;
    glm::vec3     centroid_body{0.0f};       // model units, body frame
    glm::vec3     bounds_min_body{0.0f};     // cell-centre extents
    glm::vec3     bounds_max_body{0.0f};
    std::vector<glm::ivec3> cell_list;
};

struct ConnectivityResult {
    std::size_t main_body_cells = 0;
    std::vector<HullComponent> detached;     // empty when nothing severed
};

/// Connected components of the hull that remains after damage.
///
/// A cell is OCCUPIED iff `baked.dist <= 0` (inside the authored hull) AND
/// `damage.dist <= 0` (not carved -- the same "not past the iso" test the
/// hull clip makes, in stored int8 units). The main body is the 6-connected
/// region containing the seed: the occupied cell whose centre is nearest the
/// body-frame origin. Everything occupied but unreached is a detached
/// component.
///
/// Both fields MUST share one lattice (dims/origin/cell). The per-instance
/// damage field copies the baked field's lattice by construction
/// (renderer/instance_field_cache.cc), so a mismatch is a caller bug: this
/// returns an empty result rather than reading out of bounds.
ConnectivityResult hull_connectivity(const DistanceField& baked,
                                     const DistanceField& damage);

}  // namespace voxel
```

`native/src/voxel/src/hull_connectivity.cc`:

```cpp
// native/src/voxel/src/hull_connectivity.cc
#include <voxel/hull_connectivity.h>

#include <cassert>
#include <limits>
#include <vector>

namespace voxel {

namespace {

inline bool occupied(const DistanceField& baked, const DistanceField& damage,
                     std::size_t i) {
    return baked.dist[i] <= 0 && damage.dist[i] <= 0;
}

// 6-connected flood from `seed`, writing `label` into `labels` for every
// occupied, unlabelled cell reached. Returns the count. Iterative -- a
// recursive fill would overflow the stack on a Warbird-sized lattice.
std::size_t flood(const DistanceField& baked, const DistanceField& damage,
                  std::vector<std::uint32_t>& labels, std::vector<std::size_t>& stack,
                  std::size_t seed, std::uint32_t label,
                  HullComponent* out) {
    const glm::ivec3 d = baked.dims;
    std::size_t count = 0;
    glm::vec3 sum(0.0f);
    glm::vec3 mn(std::numeric_limits<float>::max());
    glm::vec3 mx(std::numeric_limits<float>::lowest());

    stack.clear();
    stack.push_back(seed);
    labels[seed] = label;
    while (!stack.empty()) {
        const std::size_t i = stack.back();
        stack.pop_back();
        ++count;
        const int x = static_cast<int>(i % static_cast<std::size_t>(d.x));
        const int y = static_cast<int>((i / static_cast<std::size_t>(d.x)) % static_cast<std::size_t>(d.y));
        const int z = static_cast<int>(i / (static_cast<std::size_t>(d.x) * static_cast<std::size_t>(d.y)));
        if (out != nullptr) {
            const glm::vec3 c = baked.origin + (glm::vec3(x, y, z) + 0.5f) * baked.cell;
            sum += c;
            mn = glm::min(mn, c);
            mx = glm::max(mx, c);
            out->cell_list.emplace_back(x, y, z);
        }
        const int nx[6] = {x - 1, x + 1, x, x, x, x};
        const int ny[6] = {y, y, y - 1, y + 1, y, y};
        const int nz[6] = {z, z, z, z, z - 1, z + 1};
        for (int k = 0; k < 6; ++k) {
            if (nx[k] < 0 || ny[k] < 0 || nz[k] < 0 ||
                nx[k] >= d.x || ny[k] >= d.y || nz[k] >= d.z) continue;
            const std::size_t j = baked.index(nx[k], ny[k], nz[k]);
            if (labels[j] != 0) continue;
            if (!occupied(baked, damage, j)) continue;
            labels[j] = label;
            stack.push_back(j);
        }
    }
    if (out != nullptr && count > 0) {
        out->cells = count;
        out->centroid_body = sum / static_cast<float>(count);
        out->bounds_min_body = mn;
        out->bounds_max_body = mx;
    }
    return count;
}

}  // namespace

ConnectivityResult hull_connectivity(const DistanceField& baked,
                                     const DistanceField& damage) {
    ConnectivityResult r;
    if (baked.empty() || damage.empty()) return r;
    if (baked.dims != damage.dims || baked.dist.size() != damage.dist.size()) {
        assert(false && "hull_connectivity: baked and damage lattices differ");
        return r;
    }

    const std::size_t n = baked.dist.size();
    // 0 = unlabelled. Main body gets a sentinel label that is never a
    // component label; components are numbered 1..N afterwards.
    constexpr std::uint32_t kMainBody = std::numeric_limits<std::uint32_t>::max();
    std::vector<std::uint32_t> labels(n, 0);
    std::vector<std::size_t> stack;
    stack.reserve(4096);

    // Seed: occupied cell nearest the body-frame origin.
    std::size_t seed = n;
    float best = std::numeric_limits<float>::max();
    const glm::ivec3 d = baked.dims;
    for (int z = 0; z < d.z; ++z)
    for (int y = 0; y < d.y; ++y)
    for (int x = 0; x < d.x; ++x) {
        const std::size_t i = baked.index(x, y, z);
        if (!occupied(baked, damage, i)) continue;
        const glm::vec3 c = baked.origin + (glm::vec3(x, y, z) + 0.5f) * baked.cell;
        const float dd = glm::dot(c, c);
        if (dd < best) { best = dd; seed = i; }
    }
    if (seed == n) return r;   // nothing occupied at all

    r.main_body_cells = flood(baked, damage, labels, stack, seed, kMainBody, nullptr);

    std::uint32_t next = 1;
    for (std::size_t i = 0; i < n; ++i) {
        if (labels[i] != 0) continue;
        if (!occupied(baked, damage, i)) continue;
        HullComponent comp;
        comp.label = next;
        flood(baked, damage, labels, stack, i, next, &comp);
        r.detached.push_back(std::move(comp));
        ++next;
    }
    return r;
}

}  // namespace voxel
```

Add `src/hull_connectivity.cc` to the `voxel` library's sources in `native/src/voxel/CMakeLists.txt`.

- [ ] **Step 4: Run the tests**

```bash
cmake --build build -j --target voxel_tests && \
  ./build/native/tests/voxel/voxel_tests --gtest_filter='HullConnectivity.*'
```

Expected: 4 PASS.

- [ ] **Step 5: Measure the cost on a real lattice, and record it**

Add one more test that bakes a Galaxy-sized synthetic lattice (101×137×37, the measured Galaxy grid from spec §2.5 of the parent spec), fills ~25% of it as occupied in a solid block, and times `hull_connectivity` with `std::chrono::steady_clock`. Assert it completes under **50 ms** in a Release build (a generous ceiling; the point is to catch a pathological regression, not to tune) and print the measured time with `std::cout` so the number lands in the test log:

```cpp
TEST(HullConnectivity, GalaxySizedLatticeIsFastEnough) {
    voxel::DistanceField baked;
    baked.dims = glm::ivec3(101, 137, 37);
    baked.cell = glm::vec3(5.0f);
    baked.origin = glm::vec3(0.0f);
    baked.scale = 1.0f;
    baked.dist.assign(101u * 137u * 37u, static_cast<std::int8_t>(127));
    for (int z = 5; z < 32; ++z) for (int y = 20; y < 120; ++y) for (int x = 10; x < 90; ++x)
        baked.dist[baked.index(x, y, z)] = -10;
    voxel::DistanceField damage = baked;
    damage.dist.assign(baked.dist.size(), static_cast<std::int8_t>(-127));

    const auto t0 = std::chrono::steady_clock::now();
    const auto r = voxel::hull_connectivity(baked, damage);
    const auto ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - t0).count();
    std::cout << "[hull_connectivity] Galaxy-sized lattice: " << ms << " ms, "
              << r.main_body_cells << " cells\n";
    EXPECT_EQ(r.main_body_cells, 80u * 100u * 27u);
    EXPECT_LT(ms, 50.0);
}
```

Run it and **write the measured number into the commit message**.

- [ ] **Step 6: Commit**

```bash
git add native/src/voxel/include/voxel/hull_connectivity.h \
        native/src/voxel/src/hull_connectivity.cc \
        native/src/voxel/CMakeLists.txt \
        native/tests/voxel/hull_connectivity_test.cc \
        native/tests/voxel/CMakeLists.txt
git commit -m "feat(voxel): hull connectivity -- occupancy BFS over baked SDF minus damage

A cell is occupied iff inside the baked hull AND not carved. BFS from the
occupied cell nearest the body origin marks the main body; every other
occupied cell is labelled into a detached component with cell count,
centroid, bounds and cell list. Iterative fill (a Warbird lattice would
overflow a recursive one). Galaxy-sized lattice measured at <N> ms.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The capsule brush

**Files:**
- Modify: `native/src/voxel/include/voxel/field_brush.h`
- Modify: `native/src/voxel/src/field_brush.cc`
- Test: `native/tests/voxel/field_brush_test.cc`

**Interfaces:**
- Consumes: `kCarveDepthFloorCells`, `kCarveFieldOffsetCells` (already in `field_brush.h`), and the file's existing `trilinear_int8` test helper.
- Produces:
  ```cpp
  void field_carve_capsule(DistanceField& f, const glm::vec3& p0_body,
                           const glm::vec3& p1_body, float radius);
  ```

**Background.** A capsule is the set of points within `radius` of the segment `p0–p1`. Its signed distance is `|p - closest_point_on_segment(p)| - radius`, exactly 1-Lipschitz, so the conservative treatment is simpler than the oblate's: floor the radius at `kCarveDepthFloorCells * min_cell` and add the constant offset `kCarveFieldOffsetCells * min_cell` before the CSG `max()`. Same quantisation, same guards, same monotonicity.

- [ ] **Step 1: Write the failing test**

Append to `native/tests/voxel/field_brush_test.cc`:

```cpp
// A capsule cut must be backed by the field everywhere inside its nominal
// radius, across the authored cell range and the cascade's radius range --
// the same representability invariant plan 2c established for the oblate.
TEST(FieldBrushCapsule, CutIsAlwaysBackedAcrossTheParameterRange) {
    const float cells[] = {3.0f, 5.0f, 7.5f};
    const float radii[] = {30.0f, 60.0f, 100.0f};   // 0.3, 0.6, 1.0 GU
    for (float cell : cells)
    for (float radius : radii) {
        const int n = int(std::ceil((200.0f + radius * 4.0f + cell * 8.0f) / cell)) + 4;
        voxel::DistanceField f;
        f.dims = glm::ivec3(n, n / 2 + 8, n / 2 + 8);
        f.cell = glm::vec3(cell);
        f.scale = 4.0f * cell / 127.0f;
        f.origin = glm::vec3(-0.5f * float(n) * cell,
                             -0.5f * float(n / 2 + 8) * cell,
                             -0.5f * float(n / 2 + 8) * cell)
                 + glm::vec3(0.37f * cell);   // off-centre placement
        f.dist.assign(std::size_t(f.dims.x) * f.dims.y * f.dims.z,
                      static_cast<std::int8_t>(-127));

        const glm::vec3 p0(-100.0f, 0.0f, 0.0f), p1(100.0f, 0.0f, 0.0f);
        voxel::field_carve_capsule(f, p0, p1, radius);

        int total = 0, undamaged = 0;
        for (int i = 0; i <= 40; ++i) {              // along the segment
            const float t = float(i) / 40.0f;
            const glm::vec3 axis = p0 + (p1 - p0) * t;
            for (int j = 0; j < 12; ++j) {           // around it
                const float th = 6.28318530718f * float(j) / 12.0f;
                for (int k = 1; k <= 4; ++k) {       // out to the nominal radius
                    const float rad = radius * float(k) / 4.0f;
                    const glm::vec3 p = axis + glm::vec3(0.0f, rad * std::cos(th), rad * std::sin(th));
                    ++total;
                    if (trilinear_int8(f, p) <= 0.5f) ++undamaged;
                }
            }
        }
        EXPECT_EQ(undamaged, 0) << "cell=" << cell << " radius=" << radius
                                << ": " << undamaged << " of " << total
                                << " capsule points have no damage";
    }
}

TEST(FieldBrushCapsule, IsMonotonicAndLeavesFarCellsUntouched) {
    voxel::DistanceField f;
    f.dims = glm::ivec3(40, 20, 20);
    f.cell = glm::vec3(5.0f);
    f.scale = 4.0f * 5.0f / 127.0f;
    f.origin = glm::vec3(-100.0f, -50.0f, -50.0f);
    f.dist.assign(40u * 20u * 20u, static_cast<std::int8_t>(-127));
    voxel::field_carve_capsule(f, glm::vec3(-40, 0, 0), glm::vec3(40, 0, 0), 10.0f);
    // A cell far from the capsule is untouched.
    EXPECT_EQ(f.dist[f.index(39, 19, 19)], -127);
    // Carving the same capsule again changes nothing (idempotent under max).
    const auto before = f.dist;
    voxel::field_carve_capsule(f, glm::vec3(-40, 0, 0), glm::vec3(40, 0, 0), 10.0f);
    EXPECT_EQ(f.dist, before);
    // A smaller capsule inside it cannot restore material.
    voxel::field_carve_capsule(f, glm::vec3(-10, 0, 0), glm::vec3(10, 0, 0), 2.0f);
    for (std::size_t i = 0; i < f.dist.size(); ++i) EXPECT_GE(f.dist[i], before[i]);
}
```

- [ ] **Step 2: Run to verify it fails**

```bash
cmake --build build -j --target voxel_tests 2>&1 | grep -E 'error|Error' | head -3
```

Expected: compile error — `field_carve_capsule` undeclared.

- [ ] **Step 3: Declare and implement**

In `field_brush.h`, after `field_carve_oblate`'s declaration:

```cpp
/// Subtract a CAPSULE -- every point within `radius` of the segment
/// p0_body..p1_body -- from the field. The death cascade's swept cut: a line
/// of material removed, so a dying hull can part at the neck or across the
/// saucer, which no 0.3 GU sphere can do.
///
/// Same conservative treatment as the oblate (kCarveDepthFloorCells floors
/// the radius, kCarveFieldOffsetCells dilates it), same CSG max(), same
/// quantisation. The capsule's distance is exactly 1-Lipschitz, so the
/// offset dilates it uniformly. It NEVER enters the sphere list: beyond
/// tracked carves the field is the hole authority (plan 2c), so a capsule is
/// cut, rimmed and given an interior entirely by machinery that exists.
///
/// Body frame, MODEL UNITS. Empty field, non-positive/non-finite radius,
/// non-finite endpoints, or a capsule wholly off-grid are no-ops.
void field_carve_capsule(DistanceField& f,
                         const glm::vec3& p0_body,
                         const glm::vec3& p1_body,
                         float radius);
```

In `field_brush.cc`, after `field_carve_oblate`:

```cpp
void field_carve_capsule(DistanceField& f,
                         const glm::vec3& p0_body,
                         const glm::vec3& p1_body,
                         float radius) {
    if (f.empty()) return;
    if (!(radius > 0.0f) || !std::isfinite(radius)) return;
    if (!(f.scale > 0.0f)) return;
    for (int k = 0; k < 3; ++k) {
        if (!std::isfinite(p0_body[k]) || !std::isfinite(p1_body[k])) return;
    }

    const float min_cell = std::min(f.cell.x, std::min(f.cell.y, f.cell.z));
    const float r      = std::max(radius, kCarveDepthFloorCells * min_cell);
    const float offset = kCarveFieldOffsetCells * min_cell;
    const float reach  = r + offset;

    const glm::vec3 lo = glm::min(p0_body, p1_body) - glm::vec3(reach);
    const glm::vec3 hi = glm::max(p0_body, p1_body) + glm::vec3(reach);
    auto to_cell = [&](const glm::vec3& p) {
        const glm::vec3 g = (p - f.origin) / f.cell;
        return glm::ivec3(int(std::floor(g.x)), int(std::floor(g.y)),
                          int(std::floor(g.z)));
    };
    glm::ivec3 c0 = glm::max(to_cell(lo), glm::ivec3(0));
    glm::ivec3 c1 = glm::min(to_cell(hi), f.dims - 1);
    if (c0.x > c1.x || c0.y > c1.y || c0.z > c1.z) return;

    const glm::vec3 ab = p1_body - p0_body;
    const float ab2 = glm::dot(ab, ab);

    for (int z = c0.z; z <= c1.z; ++z)
    for (int y = c0.y; y <= c1.y; ++y)
    for (int x = c0.x; x <= c1.x; ++x) {
        const glm::vec3 p = f.origin + (glm::vec3(x, y, z) + 0.5f) * f.cell;
        // Closest point on the segment.
        const float t = (ab2 > 0.0f)
            ? std::max(0.0f, std::min(1.0f, glm::dot(p - p0_body, ab) / ab2))
            : 0.0f;
        const glm::vec3 q = p0_body + ab * t;
        const float d_brush = glm::length(p - q) - r;   // signed: <0 inside

        const std::size_t i = f.index(x, y, z);
        const float d_old = static_cast<float>(f.dist[i]) * f.scale;
        const float d_new = std::max(d_old, -d_brush + offset);

        float q8 = std::round(d_new / f.scale);
        q8 = std::max(-127.0f, std::min(127.0f, q8));
        f.dist[i] = static_cast<std::int8_t>(q8);
    }
}
```

- [ ] **Step 4: Run the tests**

```bash
cmake --build build -j --target voxel_tests && \
  ./build/native/tests/voxel/voxel_tests --gtest_filter='FieldBrush*'
```

Expected: all PASS, including every pre-existing `FieldBrush*` test.

- [ ] **Step 5: Commit**

```bash
git add native/src/voxel/include/voxel/field_brush.h \
        native/src/voxel/src/field_brush.cc \
        native/tests/voxel/field_brush_test.cc
git commit -m "feat(voxel): capsule brush for the death cascade's swept cuts

Every point within radius of a segment, CSG-subtracted with the same
conservative floor and offset as the oblate, so a cut thinner than the
lattice can hold cannot recreate plan 2c's un-backed hole. Sweep-tested
across cell 3.0-7.5 and radius 0.3-1.0 GU.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `InstanceFieldCache` — read access, split, remove, capsule

**Files:**
- Modify: `native/src/renderer/include/renderer/instance_field_cache.h`
- Modify: `native/src/renderer/instance_field_cache.cc`
- Test: `native/tests/renderer/instance_field_cache_test.cc`

**Interfaces:**
- Consumes: Task 2's `voxel::field_carve_capsule`.
- Produces, as public members of `renderer::InstanceFieldCache`:
  ```cpp
  /// The instance's current damage field, or nullptr when it has none.
  const voxel::DistanceField* field(scenegraph::InstanceId id) const;

  /// Move `cells` out of `parent`'s field into a NEW entry for `child` on
  /// the same lattice. child = parent's values on `cells`, +127 elsewhere;
  /// parent = +127 on `cells`. Both marked dirty. False if parent has no
  /// field or child already has one.
  bool split(scenegraph::InstanceId parent, scenegraph::InstanceId child,
             const std::vector<glm::ivec3>& cells);

  /// Set `cells` to +127 on `id`'s field (a sub-floor component: the
  /// material is gone, no chunk is made). False if no field.
  bool remove_cells(scenegraph::InstanceId id, const std::vector<glm::ivec3>& cells);

  /// Capsule counterpart of carve(): same lazy entry creation, same lattice.
  void carve_capsule(scenegraph::InstanceId id, const std::filesystem::path& source,
                     float authored_res, const glm::vec3& p0_body,
                     const glm::vec3& p1_body, float radius);
  ```

**Background.** `carve()` lazily creates an `Instance` from the baked lattice with `dist` all `-127`. `split()` needs the same construction for the child. Factor the lattice-only construction into a private helper `Instance make_blank_like(const voxel::DistanceField& lattice)` and use it from both `carve()` and `split()` — do not duplicate the "LATTICE ONLY, not the values" block; move it.

- [ ] **Step 1: Write the failing tests**

This file's convention (read its header comment): every test builds its OWN
`voxel::HullVolumeCache bake_cache(scratch_root() / "<unique>")`, seeds a baked
field with `seed_baked_field(bake_cache, src, kAuthoredRes, voxel::kDefaultQuality, make_baked_field())`,
constructs `InstanceFieldCache cache(&bake_cache)`, and creates an entry with
`cache.carve(id, src, kAuthoredRes, centre, kUp, radius)`. `TEST_F(InstanceFieldCacheTest, ...)`
supplies the GL context (skips without one). Copy that shape exactly. Add:

```cpp
TEST_F(InstanceFieldCacheTest, SplitMovesComponentCellsToChildAndOutOfParent) {
    voxel::HullVolumeCache bake_cache(scratch_root() / "cache_split_cells");
    const auto src = make_source("hull_split_cells.nif", "hull");
    const voxel::DistanceField baked = make_baked_field();
    ASSERT_TRUE(seed_baked_field(bake_cache, src, kAuthoredRes,
                                 voxel::kDefaultQuality, baked));
    InstanceFieldCache cache(&bake_cache);
    const scenegraph::InstanceId parent{1, 0};
    const scenegraph::InstanceId child{2, 0};
    cache.carve(parent, src, kAuthoredRes, glm::vec3(5, 5, 5), kUp, 3.0f);

    const voxel::DistanceField* before = cache.field(parent);
    ASSERT_NE(before, nullptr);
    const std::vector<std::int8_t> snapshot = before->dist;

    std::vector<glm::ivec3> cells;                     // a 2x2x2 block
    for (int z = 0; z < 2; ++z) for (int y = 0; y < 2; ++y) for (int x = 0; x < 2; ++x)
        cells.emplace_back(x, y, z);
    ASSERT_TRUE(cache.split(parent, child, cells));

    const voxel::DistanceField* p = cache.field(parent);
    const voxel::DistanceField* c = cache.field(child);
    ASSERT_NE(p, nullptr);
    ASSERT_NE(c, nullptr);
    ASSERT_EQ(c->dims, p->dims);
    ASSERT_EQ(c->origin, p->origin);
    ASSERT_EQ(c->cell, p->cell);
    std::vector<bool> in_comp(snapshot.size(), false);
    for (const auto& cc : cells) in_comp[before->index(cc.x, cc.y, cc.z)] = true;
    for (std::size_t i = 0; i < snapshot.size(); ++i) {
        if (in_comp[i]) {
            EXPECT_EQ(c->dist[i], snapshot[i]) << "child component cell " << i;
            EXPECT_EQ(p->dist[i], 127)        << "parent component cell " << i;
        } else {
            EXPECT_EQ(c->dist[i], 127)        << "child non-component cell " << i;
            EXPECT_EQ(p->dist[i], snapshot[i]) << "parent non-component cell " << i;
        }
    }
    EXPECT_EQ(cache.size(), 2u);
}

TEST_F(InstanceFieldCacheTest, SplitRefusesMissingParentOrExistingChild) {
    voxel::HullVolumeCache bake_cache(scratch_root() / "cache_split_refuse");
    const auto src = make_source("hull_split_refuse.nif", "hull");
    ASSERT_TRUE(seed_baked_field(bake_cache, src, kAuthoredRes,
                                 voxel::kDefaultQuality, make_baked_field()));
    InstanceFieldCache cache(&bake_cache);
    const scenegraph::InstanceId parent{1, 0}, child{2, 0}, absent{9, 0};
    std::vector<glm::ivec3> cells{glm::ivec3(0, 0, 0)};
    EXPECT_FALSE(cache.split(absent, child, cells));     // no such parent
    cache.carve(parent, src, kAuthoredRes, glm::vec3(5, 5, 5), kUp, 3.0f);
    ASSERT_TRUE(cache.split(parent, child, cells));
    EXPECT_FALSE(cache.split(parent, child, cells));     // child already exists
}

TEST_F(InstanceFieldCacheTest, RemoveCellsSetsThemFullyCarved) {
    voxel::HullVolumeCache bake_cache(scratch_root() / "cache_remove_cells");
    const auto src = make_source("hull_remove_cells.nif", "hull");
    ASSERT_TRUE(seed_baked_field(bake_cache, src, kAuthoredRes,
                                 voxel::kDefaultQuality, make_baked_field()));
    InstanceFieldCache cache(&bake_cache);
    const scenegraph::InstanceId id{1, 0};
    cache.carve(id, src, kAuthoredRes, glm::vec3(5, 5, 5), kUp, 3.0f);
    std::vector<glm::ivec3> cells{glm::ivec3(1, 1, 1), glm::ivec3(2, 1, 1)};
    ASSERT_TRUE(cache.remove_cells(id, cells));
    const voxel::DistanceField* f = cache.field(id);
    EXPECT_EQ(f->dist[f->index(1, 1, 1)], 127);
    EXPECT_EQ(f->dist[f->index(2, 1, 1)], 127);
    EXPECT_EQ(f->dist[f->index(0, 0, 0)], -127);         // untouched
    EXPECT_FALSE(cache.remove_cells(scenegraph::InstanceId{9, 0}, cells));
}
```

- [ ] **Step 2: Build to verify it fails**

```bash
cmake --build build -j --target renderer_tests 2>&1 | grep -E 'error' | head -3
```

Expected: `field`, `split`, `remove_cells` are not members.

- [ ] **Step 3: Implement**

In the header, add the four public declarations from Interfaces above, and a private `static Instance make_blank_like(const voxel::DistanceField& lattice);`.

In the .cc:

```cpp
InstanceFieldCache::Instance InstanceFieldCache::make_blank_like(
        const voxel::DistanceField& lattice) {
    // LATTICE ONLY -- see the class comment: an instance field takes the
    // baked field's dims/origin/cell/scale and NOT its values. Every cell
    // starts at -127, "no damage anywhere"; only brushes raise a cell.
    Instance inst;
    inst.field.dims   = lattice.dims;
    inst.field.origin = lattice.origin;
    inst.field.cell   = lattice.cell;
    inst.field.scale  = lattice.scale;
    inst.field.dist.assign(
        static_cast<std::size_t>(lattice.dims.x)
            * static_cast<std::size_t>(lattice.dims.y)
            * static_cast<std::size_t>(lattice.dims.z),
        static_cast<std::int8_t>(-127));
    return inst;
}
```

Replace the inline construction in `carve()` with `Instance inst = make_blank_like(baked);`.

```cpp
const voxel::DistanceField* InstanceFieldCache::field(scenegraph::InstanceId id) const {
    auto it = instances_.find(id);
    return it == instances_.end() ? nullptr : &it->second.field;
}

bool InstanceFieldCache::split(scenegraph::InstanceId parent,
                               scenegraph::InstanceId child,
                               const std::vector<glm::ivec3>& cells) {
    auto pit = instances_.find(parent);
    if (pit == instances_.end()) return false;
    if (instances_.find(child) != instances_.end()) return false;

    Instance c = make_blank_like(pit->second.field);
    // The chunk is what the parent WAS on the component and nothing
    // anywhere else: +127 ("fully carved") outside the component, so the
    // hull clip discards every fragment that is not part of this piece.
    std::fill(c.field.dist.begin(), c.field.dist.end(), static_cast<std::int8_t>(127));
    voxel::DistanceField& pf = pit->second.field;
    for (const auto& cc : cells) {
        if (cc.x < 0 || cc.y < 0 || cc.z < 0 ||
            cc.x >= pf.dims.x || cc.y >= pf.dims.y || cc.z >= pf.dims.z) continue;
        const std::size_t i = pf.index(cc.x, cc.y, cc.z);
        c.field.dist[i] = pf.dist[i];   // keep the holes it already had
        pf.dist[i] = 127;               // and it is gone from the parent
    }
    c.dirty = true;
    pit->second.dirty = true;
    instances_.emplace(child, std::move(c));
    return true;
}

bool InstanceFieldCache::remove_cells(scenegraph::InstanceId id,
                                      const std::vector<glm::ivec3>& cells) {
    auto it = instances_.find(id);
    if (it == instances_.end()) return false;
    voxel::DistanceField& f = it->second.field;
    for (const auto& cc : cells) {
        if (cc.x < 0 || cc.y < 0 || cc.z < 0 ||
            cc.x >= f.dims.x || cc.y >= f.dims.y || cc.z >= f.dims.z) continue;
        f.dist[f.index(cc.x, cc.y, cc.z)] = 127;
    }
    it->second.dirty = true;
    return true;
}

void InstanceFieldCache::carve_capsule(scenegraph::InstanceId id,
                                       const std::filesystem::path& source,
                                       float authored_res,
                                       const glm::vec3& p0_body,
                                       const glm::vec3& p1_body,
                                       float radius) {
    auto it = instances_.find(id);
    if (it == instances_.end()) {
        voxel::HullVolumeCache& cache =
            bake_cache_ != nullptr ? *bake_cache_ : renderer::hull_volume_cache();
        const voxel::DistanceField& baked =
            cache.get(source, authored_res, voxel::kDefaultQuality);
        if (baked.empty()) return;
        it = instances_.emplace(id, make_blank_like(baked)).first;
    }
    voxel::field_carve_capsule(it->second.field, p0_body, p1_body, radius);
    it->second.dirty = true;
}
```

- [ ] **Step 4: Run the full renderer suite**

```bash
cmake --build build -j && ./build/native/tests/renderer/renderer_tests
```

Expected: PASS, whole binary. No shader changed, but `renderer_tests` is the binary these live in.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/instance_field_cache.h \
        native/src/renderer/instance_field_cache.cc \
        native/tests/renderer/instance_field_cache_test.cc
git commit -m "feat(renderer): split a component out of an instance field into a chunk's field

split() moves the component's cells into a new entry on the same lattice
-- the chunk keeps the holes it had, everything else is +127 so the hull
clip discards it -- and sets those cells +127 on the parent. Asserted
cell by cell. Also read access, remove_cells for sub-floor components,
and carve_capsule mirroring carve().

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Host bindings and `host_io` wrappers

**Files:**
- Modify: `native/src/host/host_bindings.cc` (beside `hull_carve_add`, ~line 4127)
- Modify: `engine/host_io.py` (beside `hull_carve_add`, line 287)
- Test: `tests/host/test_hull_breakup_bindings.py` (new; follow the existing `tests/host/` files' pattern for skipping when `_dauntless_host` is absent)

**Interfaces:**
- Consumes: Task 1's `voxel::hull_connectivity`, Task 3's `field/split/remove_cells/carve_capsule`.
- Produces (Python, via `host_io`):
  ```python
  def hull_split_detached(instance_id, min_cells: int) -> list[dict]:
      """[] when headless or nothing severed. Each dict:
      {"instance_id": InstanceId | None, "cells": int,
       "centroid": (x, y, z), "bounds_min": (x, y, z), "bounds_max": (x, y, z),
       "radius_gu": float}  -- all positions BODY FRAME, GAME UNITS."""

  def hull_carve_capsule(instance_id, p0_world, p1_world, radius_gu: float) -> None:
      """No-op when headless."""
  ```

**Background.** `hull_split_detached` is where C++ owns the split: resolve the instance's model/source/authored_res exactly as `hull_carve_add` does (copy that resolution block; do not re-derive it differently), fetch the baked field from `renderer::hull_volume_cache().get(source, authored_res, voxel::kDefaultQuality)`, fetch the damage field via `g_instance_field_cache->field(id)`, run connectivity, and for each detached component: if `cells >= min_cells`, `g_world.create_instance(inst->model_handle)`, copy the parent's `world` matrix onto it, `split(id, child, cells)`; else `remove_cells(id, cells)`. Return dicts with positions converted from model units to **body-frame GU** by multiplying by `s = length(inst->world[0])`. `radius_gu` = half the bounds diagonal × `s`.

- [ ] **Step 1: Write the failing Python test**

```python
# tests/host/test_hull_breakup_bindings.py
"""The two bindings the breakup path needs exist on the native module and
degrade to no-ops through host_io when it is absent."""
import pytest

from engine import host_io


def test_host_io_split_is_empty_when_headless(monkeypatch):
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.hull_split_detached(1, 8) == []


def test_host_io_capsule_is_a_noop_when_headless(monkeypatch):
    monkeypatch.setattr(host_io, "_h", None)
    host_io.hull_carve_capsule(1, (0, 0, 0), (1, 0, 0), 0.6)   # must not raise


def test_native_module_exposes_both_bindings():
    h = pytest.importorskip("_dauntless_host")
    assert callable(getattr(h, "hull_split_detached", None))
    assert callable(getattr(h, "hull_carve_capsule", None))
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/host/test_hull_breakup_bindings.py -q
```

Expected: FAIL — `host_io` has no `hull_split_detached`.

- [ ] **Step 3: Add the `host_io` wrappers**

After `hull_carve_add` in `engine/host_io.py`:

```python
def hull_split_detached(instance_id: int, min_cells: int) -> list:
    """Run hull connectivity on `instance_id`'s damage field and split every
    detached component out. Components with at least `min_cells` cells get a
    new renderer instance (a chunk) and their own field; smaller ones are
    simply removed from the parent. Returns a list of dicts (body-frame GAME
    UNITS): instance_id (None for sub-floor), cells, centroid, bounds_min,
    bounds_max, radius_gu. Empty when headless or nothing severed."""
    if _h is None:
        return []
    return list(_h.hull_split_detached(instance_id, int(min_cells)))


def hull_carve_capsule(
    instance_id: int,
    p0_world: Tuple[float, float, float],
    p1_world: Tuple[float, float, float],
    radius_gu: float,
) -> None:
    """Field-only swept cut between two WORLD points at `radius_gu`. Never
    enters the sphere list. No-op when headless."""
    if _h is None:
        return
    _h.hull_carve_capsule(instance_id, p0_world, p1_world, float(radius_gu))
```

Add both names to `engine/renderer.py`'s `_REQUIRED_BINDINGS` if that list exists there (grep for it); `validate_bindings()` then fails loudly on a stale `.so` instead of the feature going silently inert — the failure mode CLAUDE.md's stub-hardening ratchet exists for.

- [ ] **Step 4: Add the bindings**

In `host_bindings.cc`, after `hull_carve_add`'s `m.def` block:

```cpp
    m.def("hull_split_detached",
          [](scenegraph::InstanceId id, int min_cells) {
              py::list out;
              auto* inst = g_world.get(id);
              if (inst == nullptr || !g_instance_field_cache) return out;
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr || model->source.empty()) return out;
              const std::filesystem::path& source = model->source;
              const float authored_res = renderer::hull_volume_resolution(source);
              if (authored_res <= 0.0f) return out;

              const voxel::DistanceField* damage = g_instance_field_cache->field(id);
              if (damage == nullptr) return out;   // never carved: nothing to sever
              const voxel::DistanceField& baked =
                  renderer::hull_volume_cache().get(source, authored_res,
                                                    voxel::kDefaultQuality);
              if (baked.empty()) return out;

              const voxel::ConnectivityResult r = voxel::hull_connectivity(baked, *damage);
              if (r.detached.empty()) return out;

              const float s = glm::length(glm::vec3(inst->world[0]));   // model->GU
              for (const voxel::HullComponent& c : r.detached) {
                  py::dict d;
                  d["cells"] = c.cells;
                  d["centroid"] = py::make_tuple(c.centroid_body.x * s,
                                                 c.centroid_body.y * s,
                                                 c.centroid_body.z * s);
                  d["bounds_min"] = py::make_tuple(c.bounds_min_body.x * s,
                                                   c.bounds_min_body.y * s,
                                                   c.bounds_min_body.z * s);
                  d["bounds_max"] = py::make_tuple(c.bounds_max_body.x * s,
                                                   c.bounds_max_body.y * s,
                                                   c.bounds_max_body.z * s);
                  d["radius_gu"] = 0.5f * glm::length(c.bounds_max_body - c.bounds_min_body) * s;
                  if (static_cast<int>(c.cells) >= min_cells) {
                      const scenegraph::InstanceId child =
                          g_world.create_instance(inst->model_handle);
                      auto* cinst = g_world.get(child);
                      if (cinst != nullptr) cinst->world = inst->world;
                      if (g_instance_field_cache->split(id, child, c.cell_list)) {
                          d["instance_id"] = child;
                      } else {
                          g_world.destroy_instance(child);
                          d["instance_id"] = py::none();
                          g_instance_field_cache->remove_cells(id, c.cell_list);
                      }
                  } else {
                      g_instance_field_cache->remove_cells(id, c.cell_list);
                      d["instance_id"] = py::none();
                  }
                  out.append(std::move(d));
              }
              return out;
          },
          py::arg("instance_id"), py::arg("min_cells"),
          "Split every detached hull component out of an instance's damage "
          "field. Components with >= min_cells cells become a new renderer "
          "instance of the same model on a copied transform, with their own "
          "field; smaller ones are removed from the parent. Positions are "
          "body-frame GAME UNITS.");

    m.def("hull_carve_capsule",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> p0_world,
             std::tuple<float, float, float> p1_world,
             float radius_gu) {
              auto* inst = g_world.get(id);
              if (inst == nullptr || !g_instance_field_cache) return;
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr || model->source.empty()) return;
              const float authored_res = renderer::hull_volume_resolution(model->source);
              const glm::vec3 a(std::get<0>(p0_world), std::get<1>(p0_world), std::get<2>(p0_world));
              const glm::vec3 b(std::get<0>(p1_world), std::get<1>(p1_world), std::get<2>(p1_world));
              const glm::vec3 pa = scenegraph::world_to_body(inst->world, a);
              const glm::vec3 pb = scenegraph::world_to_body(inst->world, b);
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv_s = (s > 0.0f) ? 1.0f / s : 1.0f;
              g_instance_field_cache->carve_capsule(id, model->source, authored_res,
                                                    pa, pb, radius_gu * inv_s);
          },
          py::arg("instance_id"), py::arg("p0_world"), py::arg("p1_world"),
          py::arg("radius_gu"),
          "Field-only swept cut between two world points. Never enters the "
          "sphere list -- beyond tracked carves the field is the hole "
          "authority (plan 2c).");
```

Add `#include <voxel/hull_connectivity.h>` at the top of the file with the other voxel includes.

- [ ] **Step 5: Build and run**

```bash
cmake --build build -j 2>&1 | grep -E 'error' | head; \
  uv run pytest tests/host/test_hull_breakup_bindings.py -q
```

Expected: build clean; 3 PASS (the third skips only if the native module genuinely isn't importable).

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc engine/host_io.py engine/renderer.py \
        tests/host/test_hull_breakup_bindings.py
git commit -m "feat(host): hull_split_detached and hull_carve_capsule bindings

C++ owns the split: connectivity over baked SDF minus damage, a new
renderer instance of the same model on the parent's transform for every
component above the floor, its field split out cell for cell; sub-floor
components are removed from the parent. Positions returned in body-frame
game units. The capsule carves the instance field only.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `DebrisChunk` — the body, the registry, integration, collision

**Files:**
- Create: `engine/appc/debris_chunk.py`
- Modify: `engine/appc/collisions.py` (`iter_collidables`, line ~577)
- Modify: `engine/host_loop.py` (tick + transform push beside `tick_collisions` ~line 8965; clear beside `ship_death.reset()` line 5187)
- Test: `tests/unit/test_debris_chunk.py` (new)

**Interfaces:**
- Consumes: `engine.appc.math.TGPoint3`, `TGMatrix3`; `host_loop._world_matrix_from(loc, rot, s)`; `renderer.set_world_transform`, `renderer.destroy_instance`; `collisions._resolve_body`'s surface.
- Produces (`engine/appc/debris_chunk.py`):
  ```python
  kChunkMinCells = 8
  kMaxLiveChunks = 32
  kChunkSeparationSpeed = 0.15   # GU/s
  kChunkTumbleRate = 0.4         # rad/s

  class DebrisChunk:
      # attributes: iid, origin_ship, component_cells, mass, radius, scale,
      #             _loc (TGPoint3), _rot (TGMatrix3), _vel (TGPoint3),
      #             _current_angular_velocity (TGPoint3), _obj_id
      def GetWorldLocation(self) -> TGPoint3
      def GetTranslate(self) -> TGPoint3
      def SetTranslateXYZ(self, x, y, z) -> None
      def GetWorldRotation(self) -> TGMatrix3
      def GetRadius(self) -> float
      def GetMass(self) -> float
      def GetVelocity(self) -> TGPoint3
      def GetScale(self) -> float
      def IsImmobile(self) -> bool      # False
      def GetObjID(self) -> int
      def GetHull(self)                  # None -- apply_hit on a chunk is a no-op

  def spawn(iid, origin_ship, cells: int, centroid_gu, radius_gu, parent_mass,
            parent_occupied_cells, rng=None) -> DebrisChunk
  def live() -> list[DebrisChunk]
  def tick(dt: float, renderer) -> None      # integrate + push transforms
  def clear(renderer) -> None                 # destroy all instances, empty registry
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_debris_chunk.py
"""A detached hull chunk is a persistent, tumbling, colliding body."""
import math
import pytest

from engine.appc.math import TGPoint3, TGMatrix3


class _FakeRenderer:
    def __init__(self):
        self.transforms = {}
        self.destroyed = []

    def set_world_transform(self, iid, mat):
        self.transforms[iid] = mat

    def destroy_instance(self, iid):
        self.destroyed.append(iid)


class _Parent:
    def __init__(self):
        self._loc = TGPoint3(10.0, 0.0, 0.0)
        self._rot = TGMatrix3()
        self._vel = TGPoint3(1.0, 0.0, 0.0)

    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetVelocity(self): return self._vel
    def GetMass(self): return 120.0
    def GetScale(self): return 1.0


@pytest.fixture(autouse=True)
def _clean():
    from engine.appc import debris_chunk as dc
    dc.clear(_FakeRenderer())
    yield
    dc.clear(_FakeRenderer())


def _spawn(dc, iid=101, cells=200, centroid=(2.0, 0.0, 0.0), radius=0.5, rng=None):
    return dc.spawn(iid, _Parent(), cells, centroid, radius,
                    parent_mass=120.0, parent_occupied_cells=1000, rng=rng)


def test_spawn_places_the_chunk_on_the_parent_and_pushes_it_away():
    from engine.appc import debris_chunk as dc
    c = _spawn(dc)
    assert c.GetWorldLocation().x == 10.0            # parent's position
    assert c.GetMass() == pytest.approx(120.0 * 200 / 1000)
    assert c.GetRadius() == 0.5
    v = c.GetVelocity()
    # parent velocity (1,0,0) + separation along centre->centroid (+x)
    assert v.x == pytest.approx(1.0 + dc.kChunkSeparationSpeed)
    assert v.y == 0.0 and v.z == 0.0
    w = c._current_angular_velocity
    assert math.sqrt(w.x * w.x + w.y * w.y + w.z * w.z) == pytest.approx(dc.kChunkTumbleRate)
    assert c.IsImmobile() is False
    assert c.GetHull() is None


def test_tick_integrates_position_and_pushes_a_transform():
    from engine.appc import debris_chunk as dc
    r = _FakeRenderer()
    c = _spawn(dc)
    x0 = c.GetWorldLocation().x
    dc.tick(0.5, r)
    assert c.GetWorldLocation().x == pytest.approx(x0 + 0.5 * (1.0 + dc.kChunkSeparationSpeed))
    assert c.iid in r.transforms


def test_tick_rotates_by_angular_velocity():
    from engine.appc import debris_chunk as dc
    c = _spawn(dc)
    c._current_angular_velocity = TGPoint3(0.0, 0.0, math.pi / 2)   # yaw 90deg/s
    before = c.GetWorldRotation().GetCol(1)
    dc.tick(1.0, _FakeRenderer())
    after = c.GetWorldRotation().GetCol(1)
    # forward has rotated ~90 degrees about the body Z axis
    dot = before.x * after.x + before.y * after.y + before.z * after.z
    assert abs(dot) < 1e-3


def test_cap_evicts_the_oldest_and_destroys_its_instance():
    from engine.appc import debris_chunk as dc
    r = _FakeRenderer()
    first = _spawn(dc, iid=1000)
    for i in range(dc.kMaxLiveChunks):
        _spawn(dc, iid=2000 + i)
    dc.tick(0.0, r)   # eviction is applied on tick so the renderer is in hand
    assert first not in dc.live()
    assert 1000 in r.destroyed
    assert len(dc.live()) == dc.kMaxLiveChunks


def test_clear_destroys_every_instance():
    from engine.appc import debris_chunk as dc
    r = _FakeRenderer()
    _spawn(dc, iid=1); _spawn(dc, iid=2)
    dc.clear(r)
    assert dc.live() == []
    assert sorted(r.destroyed) == [1, 2]


def test_chunks_are_collidable_and_take_impulses():
    from engine.appc import debris_chunk as dc
    from engine.appc.collisions import _resolve_body, _respond_pair
    c = _spawn(dc, centroid=(0.0, 0.0, 0.0))
    c._loc = TGPoint3(0.0, 0.0, 0.0)
    c._vel = TGPoint3(+2.0, 0.0, 0.0)
    ship = _Parent()
    ship._loc = TGPoint3(0.8, 0.0, 0.0)
    ship._vel = TGPoint3(-2.0, 0.0, 0.0)
    ship.GetRadius = lambda: 0.5
    ship.IsImmobile = lambda: False
    ship.GetTranslate = lambda: ship._loc
    ship.SetTranslateXYZ = lambda x, y, z: setattr(ship, "_loc", TGPoint3(x, y, z))
    ship.GetObjID = lambda: 7
    hit = _respond_pair(_resolve_body(c), _resolve_body(ship))
    assert hit is not None
    assert c.__dict__.get("_collision_velocity") is not None   # impulse landed


def test_iter_collidables_yields_live_chunks():
    from engine.appc import debris_chunk as dc
    from engine.appc.collisions import iter_collidables
    c = _spawn(dc)
    assert c in list(iter_collidables())
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/unit/test_debris_chunk.py -q
```

Expected: FAIL — `engine.appc.debris_chunk` does not exist.

- [ ] **Step 3: Implement the module**

```python
# engine/appc/debris_chunk.py
"""Detached hull chunks: persistent, tumbling, COLLIDING debris.

When a carve severs a component of a breakable hull (spec: docs/superpowers/
specs/2026-09-11-breakable-hull-components-design.md), the native side has
already made a renderer instance for it and split its damage field out
(host_io.hull_split_detached). This module is the BODY: position,
orientation, velocity, tumble, mass and radius, integrated in Python each
frame and registered with the collision system so a chunk can be struck and
can strike. Deliberately NOT a ShipClass -- it carries exactly the surface
collisions._resolve_body reads, and GetHull() returns None so combat.apply_hit
on a chunk is a no-op: it never carves and never dies.

Chunks are persistent (no timer despawn -- that was the complaint against the
old death sequence), bounded instead by kMaxLiveChunks with oldest-first
eviction, and cleared on mission swap.
"""
import math
import random

import engine.dev_mode as dev_mode
from engine.appc.math import TGPoint3, TGMatrix3

# -- Tuning (Python: turnable live without a rebuild) ------------------------
kChunkMinCells = 8            # smaller components vanish as particles instead
kMaxLiveChunks = 32
kChunkSeparationSpeed = 0.15  # GU/s, along parent-centre -> component-centroid
kChunkTumbleRate = 0.4        # rad/s about a random body axis

_live: list = []
_next_obj_id = 0x7C000000     # far above any SDK ObjID band
_X_AXIS = TGPoint3(1.0, 0.0, 0.0)
_Y_AXIS = TGPoint3(0.0, 1.0, 0.0)
_Z_AXIS = TGPoint3(0.0, 0.0, 1.0)


class DebrisChunk:
    def __init__(self, iid, origin_ship, component_cells, mass, radius,
                 scale, loc, rot, vel, angular, obj_id):
        self.iid = iid
        self.origin_ship = origin_ship
        self.component_cells = int(component_cells)
        self.mass = float(mass)
        self.radius = float(radius)
        self.scale = float(scale)
        self._loc = loc
        self._rot = rot
        self._vel = vel
        # Same slot name ship_motion uses, body frame, so collisions.
        # _resolve_body picks it up for the contact-point velocity.
        self._current_angular_velocity = angular
        self._obj_id = obj_id

    # -- the surface collisions._resolve_body reads --------------------------
    def GetWorldLocation(self): return self._loc
    def GetTranslate(self): return self._loc
    def SetTranslateXYZ(self, x, y, z): self._loc = TGPoint3(float(x), float(y), float(z))
    def GetWorldRotation(self): return self._rot
    def GetRadius(self): return self.radius
    def GetMass(self): return self.mass
    def GetVelocity(self): return self._vel
    def GetScale(self): return 1.0
    def IsImmobile(self): return False
    def GetObjID(self): return self._obj_id
    def GetHull(self): return None   # no hull: apply_hit is a no-op on us


def spawn(iid, origin_ship, cells, centroid_gu, radius_gu,
          parent_mass, parent_occupied_cells, rng=None):
    """Create the body for a chunk the native side has already instanced.
    `centroid_gu` is BODY frame of the parent; the separation push is that
    direction rotated into world. Registered immediately; eviction past the
    cap happens on the next tick, when a renderer is in hand."""
    global _next_obj_id
    rng = rng or random
    loc = origin_ship.GetWorldLocation()
    rot = origin_ship.GetWorldRotation()
    pv = origin_ship.GetVelocity()

    push = TGPoint3(*centroid_gu)
    n = math.sqrt(push.x * push.x + push.y * push.y + push.z * push.z)
    if n > 1e-6:
        push = TGPoint3(push.x / n, push.y / n, push.z / n)
        push.MultMatrixLeft(rot)                      # body -> world
    else:
        push = TGPoint3(0.0, 0.0, 0.0)
    vel = TGPoint3(pv.x + push.x * kChunkSeparationSpeed,
                   pv.y + push.y * kChunkSeparationSpeed,
                   pv.z + push.z * kChunkSeparationSpeed)

    ax = TGPoint3(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
    an = math.sqrt(ax.x * ax.x + ax.y * ax.y + ax.z * ax.z) or 1.0
    angular = TGPoint3(ax.x / an * kChunkTumbleRate,
                       ax.y / an * kChunkTumbleRate,
                       ax.z / an * kChunkTumbleRate)

    frac = (float(cells) / float(parent_occupied_cells)) if parent_occupied_cells else 0.0
    mass = max(1.0, float(parent_mass) * frac)

    _next_obj_id += 1
    chunk = DebrisChunk(iid, origin_ship, cells, mass, radius_gu,
                        float(origin_ship.GetScale()) if hasattr(origin_ship, "GetScale") else 1.0,
                        TGPoint3(loc.x, loc.y, loc.z),
                        _copy_rot(rot), vel, angular, _next_obj_id)
    _live.append(chunk)
    return chunk


def live():
    return list(_live)


def _copy_rot(rot):
    m = TGMatrix3()
    for c in range(3):
        col = rot.GetCol(c)
        m.SetCol(c, TGPoint3(col.x, col.y, col.z))
    return m


def _integrate_rotation(chunk, dt):
    cav = chunk._current_angular_velocity
    if not (cav.x or cav.y or cav.z):
        return
    # Body-frame delta POST-multiplies (R . D) -- CLAUDE.md rotation convention,
    # same construction as ship_motion._integrate_rotation.
    R = chunk._rot
    Rp = TGMatrix3(); Rp.MakeRotation(cav.x * dt, _X_AXIS)
    Ry = TGMatrix3(); Ry.MakeRotation(cav.z * dt, _Z_AXIS)
    Rr = TGMatrix3(); Rr.MakeRotation(cav.y * dt, _Y_AXIS)
    delta = Rp.MultMatrix(Ry).MultMatrix(Rr)
    chunk._rot = R.MultMatrix(delta)


def tick(dt, renderer):
    """Integrate every live chunk and push its transform. Applies cap
    eviction first so the renderer instance is destroyed here, not left
    dangling."""
    while len(_live) > kMaxLiveChunks:
        old = _live.pop(0)
        _destroy(old, renderer)
    from engine.host_loop import _world_matrix_from, BC_MODEL_SCALE
    for c in _live:
        v = c._vel
        c._loc = TGPoint3(c._loc.x + v.x * dt, c._loc.y + v.y * dt, c._loc.z + v.z * dt)
        _integrate_rotation(c, dt)
        try:
            renderer.set_world_transform(
                c.iid, _world_matrix_from(c._loc, c._rot, BC_MODEL_SCALE * c.scale))
        except Exception as _e:
            dev_mode.log_swallowed("debris chunk transform push", _e)


def _destroy(chunk, renderer):
    try:
        renderer.destroy_instance(chunk.iid)
    except Exception as _e:
        dev_mode.log_swallowed("debris chunk destroy_instance", _e)


def clear(renderer):
    """Mission swap / teardown: destroy every chunk's instance and empty the
    registry."""
    for c in _live:
        _destroy(c, renderer)
    _live.clear()
```

`BC_MODEL_SCALE` is defined at `engine/host_loop.py:4497` — import it from there (`from engine.host_loop import BC_MODEL_SCALE, _world_matrix_from`), NOT from `hull_carve`. `TGMatrix3.SetCol(i, v)` and `GetCol(i)` exist at `engine/appc/math.py:269-278`; `MakeRotation(angle, axis)` at 232 and `MultMatrix(other)` at 311 return a new matrix, matching the code above.

- [ ] **Step 4: Extend `iter_collidables`**

In `engine/appc/collisions.py`, in `iter_collidables()`, after the set loop:

```python
    # Detached hull chunks are bodies too: they can be struck and can
    # strike. Not ShipClass on purpose -- see debris_chunk.py.
    from engine.appc import debris_chunk
    for chunk in debris_chunk.live():
        yield chunk
```

- [ ] **Step 5: Hook the host loop**

In `engine/host_loop.py`, immediately **before** the `collisions.tick_collisions(` call (~line 8965), inside the same `with frame_profiler.scope(...)` structure or its own scope:

```python
                with frame_profiler.scope("sim.debris_chunks"):
                    from engine.appc import debris_chunk as _debris_chunk
                    _debris_chunk.tick(_player_dt, r)
```

(`r` is the renderer facade module already in scope there — confirm the name used at that call site and use the same.) And beside `ship_death.reset()` at line 5187:

```python
        from engine.appc import debris_chunk as _debris_chunk
        _debris_chunk.clear(r)
```

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/unit/test_debris_chunk.py tests/unit/test_collisions.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/debris_chunk.py engine/appc/collisions.py engine/host_loop.py \
        tests/unit/test_debris_chunk.py
git commit -m "feat(debris): DebrisChunk -- persistent, tumbling, colliding hull pieces

The body for a chunk the native side has already instanced: parent
position and orientation, parent velocity plus a separation push, a
random tumble, mass by cell fraction. Integrated in Python each frame,
transform pushed explicitly. Registered with iter_collidables so it takes
impulses and can strike; GetHull() is None so apply_hit on it is a no-op.
Persistent, capped at 32 oldest-first, cleared on mission swap.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The trigger — `hull_breakup.after_carve`, gating, subsystems

**Files:**
- Create: `engine/appc/hull_breakup.py`
- Modify: `engine/appc/hit_feedback.py` (after the `host_io.hull_carve_add(` call in the carve block, ~line 417)
- Modify: `engine/appc/visible_damage.py` (after `host_io.hull_carve_add(` in `_advance_one`, ~line 132)
- Test: `tests/unit/test_hull_breakup.py` (new)

**Interfaces:**
- Consumes: `host_io.hull_split_detached`, `debris_chunk.spawn/kChunkMinCells`, `damage_geometry.breakables_allowed_for`, `subsystems.subsystem_world_position` (body-frame variant below), `hit_feedback`'s existing breach-debris burst.
- Produces:
  ```python
  def after_carve(ship, iid, ship_instances=None) -> list:
      """Run after ANY carve lands on `iid`. Returns the DebrisChunks spawned
      (possibly empty). No-op unless breakables_allowed_for(ship)."""
  ```

**Background.** One function, called from both emission sites, so combat, authored and cascade carves all sever the same way. It: gates; calls `host_io.hull_split_detached(iid, kChunkMinCells)`; for each component with an `instance_id`, spawns a `DebrisChunk`; for each without, fires the existing breach-debris particle burst at the centroid; and for every component, destroys any subsystem whose **body-frame** mount lies inside the component's bounds. Parent occupied cells for the mass fraction: not returned by the binding — use `ship.GetMass()` × (component cells / total cells of all components + a nominal main body); simpler and adequate: `parent_occupied_cells = max(cells * 4, 1)` is NOT acceptable (invented). Instead extend Task 4's binding to also return `"main_body_cells"` on each dict (the same value repeated) — add that one line to the C++ (`d["main_body_cells"] = r.main_body_cells;`) and to the host_io docstring, in this task, and use `parent_occupied_cells = main_body_cells + sum(all component cells)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_hull_breakup.py
"""after_carve: the one place a severing carve becomes chunks."""
import pytest

from engine import host_io
from engine.appc.math import TGPoint3, TGMatrix3


class _Sub:
    def __init__(self, pos, name):
        self._pos = pos; self.name = name; self.condition = 100.0
    def GetPosition(self): return self._pos
    def GetName(self): return self.name
    def SetCondition(self, v): self.condition = v
    def IsDestroyed(self): return self.condition <= 0.0


class _Ship:
    def __init__(self, radius=3.5, subs=()):
        self._r = radius; self._subs = list(subs)
        self._loc = TGPoint3(0, 0, 0); self._rot = TGMatrix3()
    def GetRadius(self): return self._r
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetVelocity(self): return TGPoint3(0, 0, 0)
    def GetMass(self): return 120.0
    def GetScale(self): return 1.0
    def GetHull(self): return None
    def _iter_subsystems(self): return iter(self._subs)


@pytest.fixture(autouse=True)
def _clean():
    from engine.appc import debris_chunk as dc, damage_geometry as dg
    class _R:
        def set_world_transform(self, *a): pass
        def destroy_instance(self, *a): pass
    dc.clear(_R()); dg.reset()
    yield
    dc.clear(_R()); dg.reset()


def _component(iid, cells, centroid, lo, hi):
    return {"instance_id": iid, "cells": cells, "centroid": centroid,
            "bounds_min": lo, "bounds_max": hi, "radius_gu": 0.5,
            "main_body_cells": 1000}


def test_a_galor_never_sheds(monkeypatch):
    from engine.appc import hull_breakup
    monkeypatch.setattr(host_io, "hull_split_detached",
                        lambda iid, m: [_component(9, 500, (1, 0, 0), (0.5, -.5, -.5), (1.5, .5, .5))])
    ship = _Ship(radius=2.38)                     # Galor: below the gate
    assert hull_breakup.after_carve(ship, 11) == []


def test_a_severed_component_becomes_a_chunk(monkeypatch):
    from engine.appc import hull_breakup, debris_chunk as dc
    monkeypatch.setattr(host_io, "hull_split_detached",
                        lambda iid, m: [_component(9, 500, (1, 0, 0), (0.5, -.5, -.5), (1.5, .5, .5))])
    ship = _Ship(radius=3.5)                      # Galaxy: above the gate
    chunks = hull_breakup.after_carve(ship, 11)
    assert len(chunks) == 1 and chunks[0].iid == 9
    assert chunks[0].GetMass() == pytest.approx(120.0 * 500 / 1500)
    assert chunks[0] in dc.live()


def test_sub_floor_component_bursts_instead_of_spawning(monkeypatch):
    from engine.appc import hull_breakup, debris_chunk as dc
    monkeypatch.setattr(host_io, "hull_split_detached",
                        lambda iid, m: [_component(None, 3, (1, 0, 0), (0.9, -.1, -.1), (1.1, .1, .1))])
    bursts = []
    monkeypatch.setattr(hull_breakup, "_burst", lambda ship, iid, c: bursts.append(c))
    assert hull_breakup.after_carve(_Ship(radius=3.5), 11) == []
    assert bursts == [(1, 0, 0)]
    assert dc.live() == []


def test_subsystem_inside_the_component_is_destroyed_outside_untouched(monkeypatch):
    from engine.appc import hull_breakup
    inside = _Sub(TGPoint3(1.0, 0.0, 0.0), "Port Nacelle")
    outside = _Sub(TGPoint3(-1.0, 0.0, 0.0), "Bridge")
    ship = _Ship(radius=3.5, subs=[inside, outside])
    monkeypatch.setattr(host_io, "hull_split_detached",
                        lambda iid, m: [_component(9, 500, (1, 0, 0), (0.5, -.5, -.5), (1.5, .5, .5))])
    hull_breakup.after_carve(ship, 11)
    assert inside.IsDestroyed()
    assert not outside.IsDestroyed()


def test_nothing_severed_is_a_noop(monkeypatch):
    from engine.appc import hull_breakup, debris_chunk as dc
    monkeypatch.setattr(host_io, "hull_split_detached", lambda iid, m: [])
    assert hull_breakup.after_carve(_Ship(radius=3.5), 11) == []
    assert dc.live() == []
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/unit/test_hull_breakup.py -q
```

Expected: FAIL — `engine.appc.hull_breakup` does not exist.

- [ ] **Step 3: Implement**

```python
# engine/appc/hull_breakup.py
"""After a carve lands: did it sever anything, and if so, what comes off.

The single hook for every carve emission site (combat in hit_feedback,
authored / cascade in visible_damage), so weapons, collisions and the death
cascade all sever the same way. Spec: docs/superpowers/specs/
2026-09-11-breakable-hull-components-design.md.
"""
import engine.dev_mode as dev_mode
from engine import host_io
from engine.appc import damage_geometry, debris_chunk
from engine.appc.math import TGPoint3


def after_carve(ship, iid, ship_instances=None):
    """Run after ANY carve on `iid`. No-op unless the ship may shed chunks.
    Returns the DebrisChunks spawned."""
    if iid is None or not damage_geometry.breakables_allowed_for(ship):
        return []
    try:
        comps = host_io.hull_split_detached(iid, debris_chunk.kChunkMinCells)
    except Exception as _e:
        dev_mode.log_swallowed("hull_split_detached", _e)
        return []
    if not comps:
        return []

    main_cells = int(comps[0].get("main_body_cells", 0))
    total_cells = main_cells + sum(int(c["cells"]) for c in comps)
    parent_mass = float(ship.GetMass()) if hasattr(ship, "GetMass") else 1.0

    spawned = []
    for c in comps:
        _destroy_subsystems_inside(ship, c["bounds_min"], c["bounds_max"])
        if c.get("instance_id") is None:
            _burst(ship, iid, tuple(c["centroid"]))
            continue
        try:
            spawned.append(debris_chunk.spawn(
                c["instance_id"], ship, int(c["cells"]), tuple(c["centroid"]),
                float(c["radius_gu"]), parent_mass, total_cells))
        except Exception as _e:
            dev_mode.log_swallowed("debris_chunk.spawn", _e)
    return spawned


def _destroy_subsystems_inside(ship, lo, hi):
    """A nacelle that has physically left the ship cannot remain a working
    warp engine: destroy every subsystem whose BODY-frame mount lies in the
    component's bounds (GU, body frame -- GetPosition() is already that)."""
    it = getattr(ship, "_iter_subsystems", None)
    if it is None:
        from engine.appc.combat import _iter_subsystems as it_fn
        subs = it_fn(ship)
    else:
        subs = it()
    for sub in subs:
        pos = sub.GetPosition() if hasattr(sub, "GetPosition") else None
        if not isinstance(pos, TGPoint3):
            continue
        if (lo[0] <= pos.x <= hi[0] and lo[1] <= pos.y <= hi[1]
                and lo[2] <= pos.z <= hi[2]):
            try:
                if hasattr(sub, "IsDestroyed") and sub.IsDestroyed():
                    continue
                sub.SetCondition(0.0)
            except Exception as _e:
                dev_mode.log_swallowed("severed subsystem destroy", _e)


def _burst(ship, iid, centroid_gu):
    """Sub-floor component: the material is gone; show the existing breach-
    debris particle burst at its centroid rather than a full instance."""
    from engine.appc import hit_feedback
    fn = getattr(hit_feedback, "breach_debris_burst_at", None)
    if fn is None:
        return
    try:
        fn(ship, iid, centroid_gu)
    except Exception as _e:
        dev_mode.log_swallowed("severed component burst", _e)
```

`_iter_subsystems`: `combat.py` has one (used in `apply_hit`) — reuse it, do not write another.

**The burst is C++-driven** — `hull_carve_add` pushes `inst->breach_events.push(pb, radius, nb, g_decal_game_time, seed)` (`host_bindings.cc` ~line 4235). Python cannot reach it, so `_burst` calls a new `host_io.breach_burst(iid, body_point_gu, radius_gu)` wrapper over a binding you add beside `hull_split_detached`:

```cpp
    m.def("breach_burst",
          [](scenegraph::InstanceId id, std::tuple<float, float, float> body_point_gu,
             float radius_gu) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv_s = (s > 0.0f) ? 1.0f / s : 1.0f;
              const glm::vec3 pb(std::get<0>(body_point_gu) * inv_s,
                                 std::get<1>(body_point_gu) * inv_s,
                                 std::get<2>(body_point_gu) * inv_s);
              const glm::vec3 nb = (glm::length(pb) > 1e-4f) ? glm::normalize(pb)
                                                              : glm::vec3(0.f, 0.f, 1.f);
              static std::uint64_t s_counter = 0;
              inst->breach_events.push(pb, radius_gu * inv_s, nb, g_decal_game_time,
                                       ++s_counter * 6364136223846793005ull);
          },
          py::arg("instance_id"), py::arg("body_point_gu"), py::arg("radius_gu"),
          "Transient breach VFX (debris, venting, rim) at a body-frame point, "
          "for a sub-floor severed component that becomes no chunk.");
```

and in `host_io.py`:

```python
def breach_burst(instance_id: int, body_point_gu, radius_gu: float) -> None:
    if _h is None:
        return
    _h.breach_burst(instance_id, tuple(body_point_gu), float(radius_gu))
```

`_burst` then becomes:

```python
def _burst(ship, iid, centroid_gu):
    try:
        host_io.breach_burst(iid, centroid_gu, 0.1)
    except Exception as _e:
        dev_mode.log_swallowed("severed component burst", _e)
```

and the test's monkeypatch target stays `hull_breakup._burst`.

**Destroying a subsystem** must go through the real damage path so its destroyed-event fires: read `subsystems.py:571` (`SetCondition`) and `ships.py`'s `DamageSystem`; use `ship.DamageSystem(sub, sub.GetCondition(), None)` if `DamageSystem` is what fires the event, else `SetCondition(0.0)` — check which one broadcasts, and use that. State which in the commit message.

**Throttle.** The spec's "skip when the carve touched no occupied cell" is hard to get right; a per-ship interval is simpler and bounds the cost regardless: connectivity runs at most once per `kBreakupCheckInterval = 0.5` s per ship, and a carve that arrives inside the interval marks the ship *pending* so the check still happens on the next `drain()`. A sever detected half a second late is invisible; ten fills a second on eight ships is not. Add to the module:

```python
kBreakupCheckInterval = 0.5   # s; connectivity is a full-lattice BFS

_last_check: dict = {}        # id(ship) -> game time of last split
_pending: dict = {}           # id(ship) -> (ship, iid, ship_instances)


def _now():
    from engine.appc import damage_decals
    return damage_decals.current_game_time()


def drain(now=None):
    """Per frame: run the split for every ship that took a carve inside its
    throttle window, once the window has elapsed."""
    now = _now() if now is None else now
    for key, (ship, iid, si) in list(_pending.items()):
        if now - _last_check.get(key, -1e9) >= kBreakupCheckInterval:
            del _pending[key]
            _check(ship, iid, si, now)


def reset():
    _last_check.clear(); _pending.clear()
```

Restructure `after_carve` so the body above becomes `_check(ship, iid, ship_instances, now)`, and `after_carve` is:

```python
def after_carve(ship, iid, ship_instances=None, now=None):
    if iid is None or not damage_geometry.breakables_allowed_for(ship):
        return []
    now = _now() if now is None else now
    key = id(ship)
    if now - _last_check.get(key, -1e9) < kBreakupCheckInterval:
        _pending[key] = (ship, iid, ship_instances)
        return []
    return _check(ship, iid, ship_instances, now)
```

with `_check` recording `_last_check[key] = now` before calling the binding. Call `hull_breakup.drain()` from `host_loop.py` right after `_debris_chunk.tick(...)` (Task 5's hook), and `hull_breakup.reset()` beside `_debris_chunk.clear(r)`. Add this test:

```python
def test_a_second_carve_inside_the_window_is_deferred_then_drained(monkeypatch):
    from engine.appc import hull_breakup, debris_chunk as dc
    calls = []
    monkeypatch.setattr(host_io, "hull_split_detached",
                        lambda iid, m: calls.append(iid) or [])
    ship = _Ship(radius=3.5)
    hull_breakup.after_carve(ship, 11, now=100.0)
    hull_breakup.after_carve(ship, 11, now=100.1)      # inside the window
    assert calls == [11]                               # only the first ran
    hull_breakup.drain(now=100.3)
    assert calls == [11]                               # still inside
    hull_breakup.drain(now=100.6)
    assert calls == [11, 11]                           # drained exactly once
    hull_breakup.drain(now=100.7)
    assert calls == [11, 11]                           # nothing left pending
```

and add `hull_breakup.reset()` to the test file's autouse fixture.

Add the `main_body_cells` line to the Task 4 binding and docstring as described in Background.

- [ ] **Step 4: Call it from both emission sites**

`hit_feedback.py`, immediately after the `host_io.hull_carve_add(...)` call inside the carve block:

```python
                    from engine.appc import hull_breakup
                    hull_breakup.after_carve(ship, iid, ship_instances)
```

`visible_damage.py`, after `host_io.hull_carve_add(...)` in `_advance_one`, before `return False`:

```python
    from engine.appc import hull_breakup
    hull_breakup.after_carve(ship, iid, ship_instances)
```

- [ ] **Step 5: Run the tests and the two suites it touches**

```bash
uv run pytest tests/unit/test_hull_breakup.py tests/unit/test_hull_carve_emission.py \
              tests/unit/test_visible_damage.py tests/unit/test_hit_feedback_dispatch.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/hull_breakup.py engine/appc/hit_feedback.py engine/appc/visible_damage.py \
        native/src/host/host_bindings.cc engine/host_io.py tests/unit/test_hull_breakup.py
git commit -m "feat(damage): after_carve -- a severing carve spawns chunks and kills what left

One hook for every carve site, so weapons, collisions and the cascade
sever identically. Gated on breakables_allowed_for. Components above
the floor become DebrisChunks; below it they burst as particles. Any
subsystem whose body-frame mount sits inside the severed component is
destroyed -- a nacelle that has left the ship is not a warp engine.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The cascade's swept cut

**Files:**
- Modify: `engine/appc/visible_damage.py` (`queue_world_capsule` + emission in `_advance_one`)
- Modify: `engine/appc/death_cascade.py` (`_fire`, line ~173)
- Test: `tests/unit/test_death_cascade_capsule.py` (new)

**Interfaces:**
- Consumes: `host_io.hull_carve_capsule`, `hull_breakup.after_carve`, `damage_geometry.breakables_allowed_for`.
- Produces:
  ```python
  # visible_damage.py
  def queue_world_capsule(ship, p0_world, p1_world, radius_gu) -> None
  # death_cascade.py
  kCascadeCapsuleRadiusGu = 0.6
  ```

**Background.** The cascade has no instance map (`_fire` calls `ship.AddDamage`, which queues via `visible_damage`), so the capsule goes through the same deferred queue and is emitted when the ship is realised — same pattern, same `_advance_one`. Entries get a `"kind"`: existing entries are `"carve"`; the new ones are `"capsule"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_death_cascade_capsule.py
"""The death cascade's 30% branch also carves a swept capsule on a
breakable ship, so a dying hull can part where no sphere could cut it."""
import pytest

from engine import host_io
from engine.appc.math import TGPoint3


class _Ship:
    def __init__(self, radius):
        self._r = radius; self.damage_calls = []
        self._pts = iter([TGPoint3(1, 0, 0), TGPoint3(-1, 0, 0), TGPoint3(0, 1, 0)])
    def GetRadius(self): return self._r
    def GetRandomPointOnModel(self): return next(self._pts)
    def AddDamage(self, p, r, s): self.damage_calls.append((p, r, s))
    def GetContainingSet(self): return None
    def GetWorldLocation(self): return TGPoint3(0, 0, 0)


@pytest.fixture(autouse=True)
def _clean():
    from engine.appc import visible_damage, damage_geometry as dg
    visible_damage._pending.clear() if hasattr(visible_damage, "_pending") else None
    dg.reset()
    yield
    dg.reset()


def _fire_once(ship, roll):
    from engine.appc import death_cascade as dc
    state = {"ship": ship, "rand": lambda n: roll}
    dc._fire(state, sound_ok=False)


def test_breakable_ship_queues_a_capsule_on_the_damage_branch(monkeypatch):
    from engine.appc import visible_damage
    queued = []
    monkeypatch.setattr(visible_damage, "queue_world_capsule",
                        lambda ship, a, b, r: queued.append((a, b, r)))
    ship = _Ship(radius=3.5)
    _fire_once(ship, roll=0)                  # 0 < DAMAGE_CHANCE_IN_10: damage branch
    assert len(ship.damage_calls) == 1        # AddDamage still happens
    assert len(queued) == 1
    (a, b, r), = queued
    from engine.appc.death_cascade import kCascadeCapsuleRadiusGu
    assert r == kCascadeCapsuleRadiusGu
    assert (a.x, b.x) == (1.0, -1.0)          # two DIFFERENT model points


def test_unbreakable_ship_never_queues_a_capsule(monkeypatch):
    from engine.appc import visible_damage
    queued = []
    monkeypatch.setattr(visible_damage, "queue_world_capsule",
                        lambda *a: queued.append(a))
    _fire_once(_Ship(radius=2.38), roll=0)    # Galor
    assert queued == []


def test_capsule_entry_is_emitted_through_host_io_and_then_checks_breakup(monkeypatch):
    from engine.appc import visible_damage, hull_breakup
    emitted, checked = [], []
    monkeypatch.setattr(host_io, "hull_carve_capsule",
                        lambda iid, a, b, r: emitted.append((iid, a, b, r)))
    monkeypatch.setattr(hull_breakup, "after_carve",
                        lambda ship, iid, si=None: checked.append(iid) or [])
    ship = _Ship(radius=3.5)
    visible_damage.queue_world_capsule(ship, TGPoint3(1, 0, 0), TGPoint3(-1, 0, 0), 0.6)
    visible_damage.advance(0.0, ship_instances={ship: 42})
    assert emitted == [(42, (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), 0.6)]
    assert checked == [42]
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/unit/test_death_cascade_capsule.py -q
```

Expected: FAIL — `queue_world_capsule` / `kCascadeCapsuleRadiusGu` missing.

- [ ] **Step 3: Implement the queue entry**

In `visible_damage.py`, beside `queue_world_carve`:

```python
def queue_world_capsule(ship, p0_world, p1_world, radius_gu) -> None:
    """Queue a swept capsule cut between two WORLD points, emitted when the
    ship is realised. Field-only: never enters the sphere list."""
    _pending.append({"kind": "capsule", "ship": ship,
                     "p0": TGPoint3(p0_world.x, p0_world.y, p0_world.z),
                     "p1": TGPoint3(p1_world.x, p1_world.y, p1_world.z),
                     "radius": float(radius_gu), "age": 0.0})
```

(`_pending` is whatever list `queue_world_carve` appends to — use the same name.) In `_advance_one`, after the `iid is None` age/keep block and **before** `_resolve`:

```python
    if entry.get("kind") == "capsule":
        p0, p1 = entry["p0"], entry["p1"]
        host_io.hull_carve_capsule(iid, (p0.x, p0.y, p0.z), (p1.x, p1.y, p1.z),
                                   entry["radius"])
        from engine.appc import hull_breakup
        hull_breakup.after_carve(ship, iid, ship_instances)
        return False
```

- [ ] **Step 4: Fire it from the cascade**

In `death_cascade.py`, add the constant near the other tuning constants:

```python
# Swept cut radius for the death cascade's damage branch on a BREAKABLE
# ship. Larger than combat's kHullCarveRadiusMaxGu (0.3) on purpose: no
# 0.3 GU sphere can sever a 3.5 GU saucer, and a capsule between two random
# points on the hull is a crack, not a dimple. Field-only (plan 2c).
kCascadeCapsuleRadiusGu = 0.6
```

In `_fire`, inside the `if rand(10) < DAMAGE_CHANCE_IN_10:` block, after `ship.AddDamage(...)`:

```python
            from engine.appc import damage_geometry
            if damage_geometry.breakables_allowed_for(ship):
                from engine.appc import visible_damage
                point2 = ship.GetRandomPointOnModel()
                visible_damage.queue_world_capsule(ship, point, point2,
                                                   kCascadeCapsuleRadiusGu)
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/unit/test_death_cascade_capsule.py tests/unit/test_visible_damage.py \
              tests/unit/test_ship_death.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/visible_damage.py engine/appc/death_cascade.py \
        tests/unit/test_death_cascade_capsule.py
git commit -m "feat(death): the cascade slashes a breakable hull with swept capsules

On its 30% damage branch, on a breakable ship, the cascade also queues a
0.6 GU capsule between two random model points. Emitted through the same
deferred queue as its carves, field-only, followed by a breakup check --
so a dying Galaxy can part at the neck or across the saucer.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Fleet gating test, gate, briefing

**Files:**
- Create: `tests/unit/test_breakables_gating.py`
- Modify: `docs/superpowers/specs/2026-09-11-breakable-hull-components-design.md` (append "Status: built" line + any deviations)

- [ ] **Step 1: Write the gating test**

```python
# tests/unit/test_breakables_gating.py
"""Which stock ships may shed chunks -- pinned, with plan 1's caveat.

Radii are LITERALS from the spec's table (parent spec section 2.4, measured
2026-09-08), not read from GetRadius or a hull asset. So this test detects a
change to BREAKABLE_MIN_RADIUS_GU -- it names exactly which ships moved
sides -- but NOT a change to how GetRadius itself is derived. That would
re-sort the fleet silently; see the parent spec's section 8 for why.
"""
import pytest

from engine.appc import damage_geometry as dg


class _Ship:
    def __init__(self, r): self._r = r
    def GetRadius(self): return self._r


FLEET = {
    "Shuttle": 0.14, "BirdOfPrey": 1.34, "Freighter": 1.96, "CardFreighter": 2.00,
    "Marauder": 2.02, "Galor": 2.38,
    "Nebula": 2.42, "Akira": 2.55, "Ambassador": 3.14, "Keldon": 3.16,
    "Transport": 3.24, "KessokLight": 3.34, "Galaxy": 3.50, "Vorcha": 3.52,
    "Sovereign": 3.81, "CardHybrid": 4.96, "Warbird": 6.52, "KessokHeavy": 7.50,
}
BREAKABLE = {"Nebula", "Akira", "Ambassador", "Keldon", "Transport", "KessokLight",
             "Galaxy", "Vorcha", "Sovereign", "CardHybrid", "Warbird", "KessokHeavy"}


@pytest.fixture(autouse=True)
def _reset():
    dg.reset(); yield; dg.reset()


@pytest.mark.parametrize("name,radius", sorted(FLEET.items()))
def test_fleet_falls_on_the_documented_side_of_the_gate(name, radius):
    assert dg.breakables_allowed_for(_Ship(radius)) is (name in BREAKABLE), (
        f"{name} (radius {radius}) is on the wrong side of "
        f"BREAKABLE_MIN_RADIUS_GU={dg.BREAKABLE_MIN_RADIUS_GU}")


def test_the_sdk_flag_still_switches_it_off():
    dg.set_breakable_components_enabled(0)
    assert dg.breakables_allowed_for(_Ship(3.5)) is False
```

- [ ] **Step 2: Run it**

```bash
uv run pytest tests/unit/test_breakables_gating.py -q
```

Expected: PASS (plan 1 built the gate). If `Nebula` fails, the constant has drifted — do not move the literal; report.

- [ ] **Step 3: Full gate**

```bash
./scripts/check_tests.sh
```

Read the output. Expected: `OK — no new failures`.

- [ ] **Step 4: Record deviations and commit**

Append to the spec, under a new `## 12. Built` heading: the commit range, the measured connectivity time from Task 1, and any place the implementation deviated from §3–§9 with the reason.

```bash
git add tests/unit/test_breakables_gating.py \
        docs/superpowers/specs/2026-09-11-breakable-hull-components-design.md
git commit -m "test(damage): pin which stock ships may shed chunks; spec marked built

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Live verification briefing

Green tests cannot see any of this. Bring the branch to the main checkout, **rebuild** (C++ changed), run `DAUNTLESS_MISSION=engine.dev_missions.combat_stress ./build/dauntless --developer`, and check in order:

1. **Kill a Galaxy-class ship and watch the cascade.** Expect slashes, not dimples, and at least one piece — nacelle, pylon, neck, or a saucer section — coming away and drifting with a tumble. This is the headline.
2. **The cut face.** Look at where a chunk parted. It should read as torn hull material (the raymarched interior), not a black smear and not see-through. See-through here would be a real failure of the split, not tuning.
3. **A chunk is physical.** Fly into one. It should shove, and you should take a small hit. It must not be targetable and must not appear in the contact list.
4. **Shoot a nacelle off a live ship.** Sustained fire on a Galaxy pylon. When it comes away, the ship's warp engine on that side should read destroyed.
5. **A Galor sheds nothing**, however hard it's hit — the material still vanishes, but no chunk.
6. **Grind a friendly and let chunks hit friendlies.** The mission must not end.

Tuning knobs, all Python, no rebuild: `kChunkSeparationSpeed`, `kChunkTumbleRate` (spin like tops → lower it), `kChunkMinCells`, `kMaxLiveChunks` in `debris_chunk.py`; `kCascadeCapsuleRadiusGu` in `death_cascade.py` (trench instead of crack → lower it).
