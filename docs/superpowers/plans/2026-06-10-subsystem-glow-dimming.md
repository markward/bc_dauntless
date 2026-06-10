# Subsystem Glow-Dimming Generalization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive hull-glow dimming from three subsystems (impulse engines, sensor array, warp engines) with one unified three-state behaviour — healthy = full glow, disabled = continuous flicker, destroyed = off — by generalizing the existing warp-nacelle glow-region machinery.

**Architecture:** Reuse the per-instance, body-frame glow-region system. Rename it `nacelle` → `glow_region`. Warp keeps capsule shape-fitting (`compute_capsule_region`); impulse/sensors use sphere regions (`add_sphere_region`) — a sphere is the existing capsule shader test with `axis=(0,0,0)`, `aft=fore=0`. Add a per-region `flicker` flag to drive the new three-state shader behaviour. Replace `warp_glow.py` with a generalized `subsystem_glow.py` (`ShipGlowController`) that registers all three regions per ship and pushes state each frame.

**Tech Stack:** C++17 + GLSL 330 (renderer/host, pybind11 bindings, GoogleTest), Python 3 (headless engine logic, pytest). Build: `cmake -B build -S . && cmake --build build -j`. Shader `.frag`/`.vert` edits require re-running `cmake -B build -S .` first (they are NOT picked up by `cmake --build` alone).

**Spec:** `docs/superpowers/specs/2026-06-10-subsystem-glow-dimming-design.md`

---

## Phase A — Mechanical rename: `nacelle` → `glow_region` (no behaviour change)

A pure rename so diffs in later phases are about behaviour, not churn. The build and all existing tests must stay green. Keep the capsule-fit logic identical; only names change.

### Task A1: Rename the C++ region module and types

**Files:**
- Rename: `native/src/renderer/include/renderer/nacelle_region.h` → `native/src/renderer/include/renderer/glow_region.h`
- Rename: `native/src/renderer/nacelle_region.cc` → `native/src/renderer/glow_region.cc`
- Modify: `native/src/scenegraph/include/scenegraph/instance.h`
- Modify: `native/src/renderer/frame.cc`
- Modify: `native/src/host/host_bindings.cc`
- Modify: `native/src/renderer/shaders/opaque.frag`
- Modify: `native/src/renderer/CMakeLists.txt:67`
- Modify: `native/tests/renderer/CMakeLists.txt:12`
- Rename: `native/tests/renderer/nacelle_region_test.cc` → `native/tests/renderer/glow_region_test.cc`

Identifier mapping (apply everywhere — these are the ONLY identifiers; remaining `nacelle` hits in `probe_shape_transforms.cc`, `target_list.js`, `deferred_work.md`, and `resolve.frag:12` are prose comments and are left alone):

| Old | New |
|---|---|
| `NacelleRegion` | `GlowRegion` (renderer type) |
| `compute_nacelle_region` | `compute_capsule_region` |
| `kNacelleRadiusWiden` | `kGlowCapsuleRadiusWiden` |
| `kNacelleFallbackHalfLenFactor` | `kGlowCapsuleFallbackHalfLenFactor` |
| `kNacelleMinCaptured` | `kGlowCapsuleMinCaptured` |
| `nacelle_region.h` (include) | `glow_region.h` |
| `Instance::Nacelle` (struct) | `Instance::GlowRegion` |
| `kMaxNacelles` | `kMaxGlowRegions` |
| `Instance::nacelles` (member) | `Instance::glow_regions` |
| `u_nacelle_count` | `u_glow_region_count` |
| `u_nacelle_a/b/c` | `u_glow_region_a/b/c` |
| `MAX_NACELLES` | `MAX_GLOW_REGIONS` |
| `NACELLE_FLICKER_SECS` | `GLOW_FLICKER_SECS` |
| `nacelle_glow_mult` | `glow_region_mult` |
| `set_nacelle_dim` (binding) | `set_glow_region_dim` |

- [ ] **Step 1: Use git mv for the four file renames**

```bash
cd native
git mv src/renderer/include/renderer/nacelle_region.h src/renderer/include/renderer/glow_region.h
git mv src/renderer/nacelle_region.cc src/renderer/glow_region.cc
git mv tests/renderer/nacelle_region_test.cc tests/renderer/glow_region_test.cc
cd ..
```

- [ ] **Step 2: Apply the identifier mapping across the modified files**

Edit each file in the list, replacing every occurrence per the table. Notes:
- `glow_region.h`: update the `// native/src/renderer/nacelle_region.h` header comment path too; the doc comment on the struct can drop the "warp nacelle" wording in favour of "glow region (capsule or sphere)".
- `glow_region.cc`: update the `#include "renderer/nacelle_region.h"` and the `// native/src/renderer/nacelle_region.cc` path comment.
- `instance.h`: rename the struct, the `kMaxNacelles` constant, and the `nacelles` array member. Keep all field defaults exactly as they are (this task adds NO new field — that is Task B1).
- `frame.cc`: the `draw_model` signature param `const std::array<...Nacelle, ...kMaxNacelles>& nacelles` and the two call sites (`inst.nacelles`) and the packing block (`na/nb/nc`, `u_nacelle_*`, `u_nacelle_count`). The `nc[nn] = glm::vec4(n.fore, n.dim_target, n.disable_time, 0.0f)` line keeps its `0.0f` for now (Task B2 replaces it).
- `host_bindings.cc`: the `#include <renderer/nacelle_region.h>`, both `m.def(...)` binding names (`compute_nacelle_region`→`compute_capsule_region`, `set_nacelle_dim`→`set_glow_region_dim`), the `renderer::NacelleRegion`/`renderer::compute_nacelle_region` calls, the `inst->nacelles` references, and the docstrings. Do NOT change the binding parameters yet (Task B3 adds the flicker arg).
- `opaque.frag`: the uniform block (`MAX_NACELLES`, `u_nacelle_count`, `u_nacelle_a/b/c`), `NACELLE_FLICKER_SECS`, the `nacelle_glow_mult` function name + its comment, and the two call-site references in `main()` (`if (u_nacelle_count > 0)` and `nac = nacelle_glow_mult(...)`).
- `glow_region_test.cc`: rename `#include`, `compute_nacelle_region`→`compute_capsule_region`, `NacelleRegion`/`kNacelle*` constants, `Instance::kMaxNacelles`→`kMaxGlowRegions`, `inst.nacelles`→`inst.glow_regions`, and the `TEST(NacelleRegion, ...)` / `TEST(NacelleProductionPath, ...)` suite names → `TEST(GlowRegion, ...)` / `TEST(GlowRegionProductionPath, ...)`. The assertions are unchanged.
- `CMakeLists.txt` (both): `nacelle_region.cc`→`glow_region.cc`, `nacelle_region_test.cc`→`glow_region_test.cc`.

- [ ] **Step 3: Reconfigure (shader + new filenames) and build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: clean build, no `nacelle`-related compile errors.

- [ ] **Step 4: Run the renamed C++ test**

Run: `ctest --test-dir build -R GlowRegion --output-on-failure`
Expected: PASS (the capsule-fit + production-path tests, unchanged logic).

- [ ] **Step 5: Run the Python suite that still references the old binding names**

The Python side (`engine/renderer.py`, `engine/appc/warp_glow.py`) still calls `compute_nacelle_region` / `set_nacelle_dim`, which no longer exist. Update `engine/renderer.py` ONLY (rename the two wrapper functions + their `_h.` calls to `compute_capsule_region` / `set_glow_region_dim`, parameters unchanged) so the module imports. Leave `warp_glow.py` calling the renamed `compute_capsule_region` / `set_glow_region_dim` — update those two call sites in `warp_glow.py` too (it is removed in Phase C, but must import cleanly until then).

Run: `uv run pytest tests/unit/test_warp_glow.py -q`
Expected: the fake-renderer test still references `compute_nacelle_region`/`set_nacelle_dim` method names on `_FakeRenderer` — update those two method names in `tests/unit/test_warp_glow.py` to `compute_capsule_region`/`set_glow_region_dim` and assert PASS. (This whole test file is replaced in Phase C; this is the minimal keep-green edit.)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(renderer): rename nacelle glow-region infra to glow_region

Mechanical rename only; capsule-fit logic and behaviour unchanged.
Prepares the machinery to also serve impulse + sensor sphere regions.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Phase B — Sphere regions + per-region flicker + three-state shader

### Task B1: Add the `flicker` field to the GlowRegion struct

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h`
- Test: `native/tests/renderer/glow_region_test.cc`

- [ ] **Step 1: Write the failing test for the new default**

Add to `glow_region_test.cc`:

```cpp
TEST(GlowRegionProductionPath, DefaultGlowRegionHasFlickerOff) {
    scenegraph::Instance inst{};
    for (std::size_t i = 0; i < scenegraph::Instance::kMaxGlowRegions; ++i) {
        EXPECT_FLOAT_EQ(inst.glow_regions[i].flicker, 0.0f)
            << "glow region " << i << " must default flicker=0 so an "
               "untouched instance keeps the production glow path";
    }
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cmake --build build -j && ctest --test-dir build -R GlowRegion --output-on-failure`
Expected: FAIL to compile — `glow_regions[i].flicker` has no member `flicker`.

- [ ] **Step 3: Add the field**

In `instance.h`, inside `struct GlowRegion`, after `float disable_time = -1.0f;`:

```cpp
        float     flicker = 0.0f;   // 1 = disabled (continuous flicker), 0 = solid settle
```

- [ ] **Step 4: Build + test**

Run: `cmake --build build -j && ctest --test-dir build -R GlowRegion --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/scenegraph/include/scenegraph/instance.h native/tests/renderer/glow_region_test.cc
git commit -m "feat(renderer): add flicker field to GlowRegion (default off)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task B2: Pack `flicker` into the shader uniform

**Files:**
- Modify: `native/src/renderer/frame.cc` (the glow-region packing block, ~line 130)

- [ ] **Step 1: Pack the field**

Replace the packing line:

```cpp
            nc[nn] = glm::vec4(n.fore, n.dim_target, n.disable_time, 0.0f);
```

with:

```cpp
            nc[nn] = glm::vec4(n.fore, n.dim_target, n.disable_time, n.flicker);
```

- [ ] **Step 2: Build**

Run: `cmake --build build -j`
Expected: clean build. (No test here — covered end-to-end by Task B5's shader logic and in-app verification; the value is inert until the shader reads it.)

- [ ] **Step 3: Commit**

```bash
git add native/src/renderer/frame.cc
git commit -m "feat(renderer): pass GlowRegion.flicker to the shader (.w slot)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task B3: Extend `set_glow_region_dim` with the flicker argument

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`set_glow_region_dim` binding)
- Modify: `engine/renderer.py` (`set_glow_region_dim` wrapper)

- [ ] **Step 1: Add the flicker arg to the binding**

Replace the `set_glow_region_dim` lambda body + signature so it also writes `flicker`:

```cpp
    m.def("set_glow_region_dim",
          [](scenegraph::InstanceId id, int region_index,
             float dim_target, float disable_time, float flicker) {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return;
              if (region_index < 0 ||
                  region_index >= static_cast<int>(inst->glow_regions.size())) return;
              auto& n = inst->glow_regions[static_cast<std::size_t>(region_index)];
              if (!n.active) return;
              n.dim_target = dim_target;
              n.disable_time = disable_time;
              n.flicker = flicker;
          },
          py::arg("instance_id"), py::arg("region_index"),
          py::arg("dim_target"), py::arg("disable_time"), py::arg("flicker"),
          "Update a glow region's live dim target [0,1], the game-time seconds "
          "of the last state-change edge (<0 = healthy), and the flicker flag "
          "(1 = disabled/continuous flicker, 0 = solid settle to dim_target).");
```

- [ ] **Step 2: Update the Python wrapper**

In `engine/renderer.py`, replace the `set_glow_region_dim` wrapper (renamed in A5) with:

```python
def set_glow_region_dim(instance_id: InstanceId, region_index: int,
                        dim_target: float, disable_time: float,
                        flicker: float) -> None:
    """Update a glow region's dim target [0,1], last state-change edge time
    (game-time secs; <0 = healthy), and flicker flag (1 = disabled/continuous
    flicker, 0 = solid settle)."""
    _h.set_glow_region_dim(instance_id, int(region_index),
                           float(dim_target), float(disable_time), float(flicker))
```

- [ ] **Step 3: Build**

Run: `cmake --build build -j`
Expected: clean build. (Python callers are added in Phase C.)

- [ ] **Step 4: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py
git commit -m "feat(host): set_glow_region_dim gains flicker arg

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task B4: Add `add_sphere_region` (C++ + host binding + Python wrapper)

**Files:**
- Modify: `native/src/renderer/include/renderer/glow_region.h`
- Modify: `native/src/renderer/glow_region.cc`
- Test: `native/tests/renderer/glow_region_test.cc`
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/renderer.py`

- [ ] **Step 1: Write the failing C++ test**

Add to `glow_region_test.cc`:

```cpp
TEST(GlowRegion, SphereRegionHasNoAxisAndZeroFoaAft) {
    auto reg = renderer::add_sphere_region(glm::vec3(1.0f, 2.0f, 3.0f), 0.5f);
    EXPECT_TRUE(reg.active);
    EXPECT_FLOAT_EQ(reg.center.x, 1.0f);
    EXPECT_FLOAT_EQ(reg.center.y, 2.0f);
    EXPECT_FLOAT_EQ(reg.center.z, 3.0f);
    EXPECT_FLOAT_EQ(reg.radius, 0.5f);   // no widen for spheres
    EXPECT_FLOAT_EQ(reg.axis.x, 0.0f);
    EXPECT_FLOAT_EQ(reg.axis.y, 0.0f);
    EXPECT_FLOAT_EQ(reg.axis.z, 0.0f);
    EXPECT_FLOAT_EQ(reg.aft, 0.0f);
    EXPECT_FLOAT_EQ(reg.fore, 0.0f);
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cmake --build build -j`
Expected: FAIL to compile — `renderer::add_sphere_region` undeclared.

- [ ] **Step 3: Declare and implement `add_sphere_region`**

In `glow_region.h`, after the `compute_capsule_region` declaration:

```cpp
/// Build a sphere glow region: the capsule test degenerates to a sphere when
/// axis == (0,0,0) and aft == fore == 0 (then the axial bound 0<=0<=0 always
/// holds and the lateral test becomes dot(d,d) > radius^2). No vertex fit and
/// no widen — impulse/sensor glow is a compact spot, not a long tube. center /
/// radius are in body/model units.
GlowRegion add_sphere_region(const glm::vec3& center, float radius);
```

In `glow_region.cc`, add:

```cpp
GlowRegion add_sphere_region(const glm::vec3& center, float radius) {
    GlowRegion reg;
    reg.center = center;
    reg.axis   = glm::vec3(0.0f);
    reg.radius = radius;
    reg.aft    = 0.0f;
    reg.fore   = 0.0f;
    reg.active = true;
    return reg;
}
```

- [ ] **Step 4: Build + test**

Run: `cmake --build build -j && ctest --test-dir build -R GlowRegion --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Add the host binding**

In `host_bindings.cc`, after the `compute_capsule_region` binding, add (mirrors the game-unit→model conversion `inv = 1/s` and the free-slot search):

```cpp
    m.def("add_sphere_region",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> center, float radius) -> int {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return -1;
              // hardpoint center/radius are in game units; convert to model
              // frame (same s as compute_capsule_region / damage_decal_add).
              const float s = glm::length(glm::vec3(inst->world[0]));
              const float inv = (s > 0.0f) ? 1.0f / s : 1.0f;
              const glm::vec3 c(std::get<0>(center) * inv,
                                std::get<1>(center) * inv,
                                std::get<2>(center) * inv);
              const renderer::GlowRegion reg =
                  renderer::add_sphere_region(c, radius * inv);
              for (std::size_t i = 0; i < inst->glow_regions.size(); ++i) {
                  if (inst->glow_regions[i].active) continue;
                  auto& n = inst->glow_regions[i];
                  n.center = reg.center;
                  n.axis = reg.axis;
                  n.radius = reg.radius;
                  n.aft = reg.aft;
                  n.fore = reg.fore;
                  n.dim_target = 1.0f;
                  n.disable_time = -1.0f;
                  n.flicker = 0.0f;
                  n.active = true;
                  return static_cast<int>(i);
              }
              return -1;  // no free slot
          },
          py::arg("instance_id"), py::arg("center"), py::arg("radius"),
          "Store a sphere glow region at a hardpoint (game units / body frame). "
          "Returns the region index, or -1 on failure (stale id, no slot).");
```

- [ ] **Step 6: Add the Python wrapper**

In `engine/renderer.py`, after `compute_capsule_region`:

```python
def add_sphere_region(instance_id: InstanceId, center, radius: float) -> int:
    """Store a sphere glow region at a hardpoint. center is a 3-tuple in game
    units / body frame; radius in game units. Returns the region index (>=0) or
    -1 on failure. Used for impulse engines and sensor arrays (compact spots);
    warp nacelles use compute_capsule_region for their elongated shape."""
    return _h.add_sphere_region(instance_id, tuple(center), float(radius))
```

- [ ] **Step 7: Build + test**

Run: `cmake --build build -j && ctest --test-dir build -R GlowRegion --output-on-failure`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/glow_region.h native/src/renderer/glow_region.cc native/tests/renderer/glow_region_test.cc native/src/host/host_bindings.cc engine/renderer.py
git commit -m "feat(renderer): add_sphere_region for impulse/sensor glow regions

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task B5: Three-state behaviour in the shader

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag` (`glow_region_mult` + constants)

- [ ] **Step 1: Replace the constant and the region-mult body**

Change the flicker constant block (where `GLOW_FLICKER_SECS` lives) to add the disabled floor:

```glsl
const float GLOW_FLICKER_SECS = 0.4;   // blow-out window when a region is destroyed
const float DISABLED_FLOOR    = 0.0;   // flicker troughs reach dark while disabled
```

In `glow_region_mult`, read the new flag and replace the per-region settle math. The region geometry test (capsule/sphere) and `dtime < 0.0` healthy skip are UNCHANGED; replace only from the `float age = ...` line onward:

```glsl
        float flick  = u_glow_region_c[i].w;   // 1 = disabled (continuous), 0 = destroyed
        if (dtime < 0.0) continue;             // healthy

        float age = max(now - dtime, 0.0);
        float region_mult;
        if (flick > 0.5) {
            // Disabled: continuous oscillation between floor and full.
            region_mult = mix(DISABLED_FLOOR, 1.0, 0.5 + 0.5 * stutter(age));
        } else {
            // Destroyed: brief blow-out flicker, then settle to target (0 = off).
            float blow = mix(target, 1.0, 0.5 + 0.5 * stutter(age));
            float w    = clamp(age / GLOW_FLICKER_SECS, 0.0, 1.0);
            region_mult = mix(blow, target, w);
        }
        mult = min(mult, region_mult);  // overlapping regions: darkest wins
```

Make sure `target` (`u_glow_region_c[i].y`) and `dtime` (`u_glow_region_c[i].z`) are still read above this block (they are, from the existing unpacking).

- [ ] **Step 2: Reconfigure (shader change) and build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: clean build, shader compiles.

- [ ] **Step 3: Verify production path unaffected (C++ data-level lock still green)**

Run: `ctest --test-dir build -R GlowRegion --output-on-failure`
Expected: PASS (the `count == 0` short-circuit and default-inactive locks are unchanged).

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag
git commit -m "feat(renderer): three-state glow_region_mult (flicker/destroyed/off)

Disabled regions flicker continuously between dark and full; destroyed
regions blow out then settle to dim_target (0). Healthy still inert.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Phase C — Generalized Python driver

### Task C1: Pure helpers in `subsystem_glow.py`

**Files:**
- Create: `engine/appc/subsystem_glow.py`
- Test: `tests/unit/test_subsystem_glow.py`

- [ ] **Step 1: Write the failing tests for the pure helpers**

Create `tests/unit/test_subsystem_glow.py`:

```python
from engine.appc import subsystem_glow as sg


class _Sub:
    def __init__(self, disabled=False, destroyed=False):
        self._disabled, self._destroyed = disabled, destroyed
    def IsDisabled(self):
        return self._disabled
    def IsDestroyed(self):
        return self._destroyed


def test_glow_state_classifies_all_cases():
    assert sg.glow_state(None) == sg.HEALTHY
    assert sg.glow_state(_Sub()) == sg.HEALTHY
    assert sg.glow_state(_Sub(disabled=True)) == sg.DISABLED
    assert sg.glow_state(_Sub(destroyed=True)) == sg.DESTROYED
    # destroyed dominates even if also flagged disabled
    assert sg.glow_state(_Sub(disabled=True, destroyed=True)) == sg.DESTROYED


def test_dim_and_flicker_per_state():
    assert sg.dim_and_flicker(sg.HEALTHY) == (1.0, 0.0)
    assert sg.dim_and_flicker(sg.DISABLED) == (0.0, 1.0)
    assert sg.dim_and_flicker(sg.DESTROYED) == (0.0, 0.0)


def test_glow_edge_tracks_state_changes():
    # healthy -> -1
    assert sg.glow_edge(sg.HEALTHY, sg.HEALTHY, -1.0, 10.0) == -1.0
    # healthy -> disabled stamps now
    assert sg.glow_edge(sg.HEALTHY, sg.DISABLED, -1.0, 10.0) == 10.0
    # still disabled keeps stamp
    assert sg.glow_edge(sg.DISABLED, sg.DISABLED, 10.0, 12.0) == 10.0
    # disabled -> destroyed re-stamps (fresh blow-out)
    assert sg.glow_edge(sg.DISABLED, sg.DESTROYED, 10.0, 15.0) == 15.0
    # still destroyed keeps stamp
    assert sg.glow_edge(sg.DESTROYED, sg.DESTROYED, 15.0, 20.0) == 15.0
    # repaired -> clear
    assert sg.glow_edge(sg.DESTROYED, sg.HEALTHY, 15.0, 25.0) == -1.0


def test_warp_pods_children_then_aggregator_then_empty():
    class _Agg:
        def __init__(self, kids):
            self._kids = kids
        def GetNumChildSubsystems(self):
            return len(self._kids)
        def GetChildSubsystem(self, i):
            return self._kids[i]
    kids = ["port", "star"]
    assert sg.warp_pods(_Agg(kids)) == kids
    agg = _Agg([])
    assert sg.warp_pods(agg) == [agg]
    assert sg.warp_pods(None) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_subsystem_glow.py -q`
Expected: FAIL — `ModuleNotFoundError: engine.appc.subsystem_glow`.

- [ ] **Step 3: Write the module's pure helpers**

Create `engine/appc/subsystem_glow.py`:

```python
"""Subsystem glow-dimming driver (impulse, sensors, warp).

Pure mapping logic (state classification, edge tracking, dim/flicker mapping,
warp-pod enumeration) plus a thin per-ship orchestration object that registers
glow regions at construction and pushes state each frame. The C++ side owns the
region geometry and the shader attenuation; this module only decides *when* and
*how* a region dims. See
docs/superpowers/specs/2026-06-10-subsystem-glow-dimming-design.md.
"""

HEALTHY = "healthy"
DISABLED = "disabled"
DESTROYED = "destroyed"

# Capsule axis for warp nacelles: ship-forward is model +Y (column-vector).
WARP_AXIS = (0.0, 1.0, 0.0)


def glow_state(sub) -> str:
    """Three-state classification. Destroyed dominates disabled; None=healthy."""
    if sub is None:
        return HEALTHY
    if sub.IsDestroyed():
        return DESTROYED
    if sub.IsDisabled():
        return DISABLED
    return HEALTHY


def dim_and_flicker(state) -> tuple:
    """(dim_target, flicker) pushed to the shader for a state.

    healthy   -> (1.0, 0.0)  region is inert (edge_time -1 also set)
    disabled  -> (0.0, 1.0)  continuous flicker (shader ignores dim_target)
    destroyed -> (0.0, 0.0)  blow-out then settle to 0 (off)
    """
    if state == DISABLED:
        return (0.0, 1.0)
    if state == DESTROYED:
        return (0.0, 0.0)
    return (1.0, 0.0)


def glow_edge(prev_state, cur_state, prev_time, now) -> float:
    """Game-time of the most recent state-change edge.

    -1.0 while healthy; `now` whenever the state changes to a different
    non-healthy state (healthy->disabled, healthy->destroyed, disabled->
    destroyed); otherwise keep prev_time (same non-healthy state persists).
    """
    if cur_state == HEALTHY:
        return -1.0
    if cur_state != prev_state:
        return now
    return prev_time


def warp_pods(warp_subsystem):
    """Per-nacelle pods to drive: children, else [aggregator], else []."""
    if warp_subsystem is None:
        return []
    n = warp_subsystem.GetNumChildSubsystems()
    if n > 0:
        return [warp_subsystem.GetChildSubsystem(i) for i in range(n)]
    return [warp_subsystem]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_subsystem_glow.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystem_glow.py tests/unit/test_subsystem_glow.py
git commit -m "feat(glow): pure helpers for subsystem glow state/edge mapping

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task C2: `ShipGlowController` registration + per-frame update

**Files:**
- Modify: `engine/appc/subsystem_glow.py`
- Test: `tests/unit/test_subsystem_glow.py`

- [ ] **Step 1: Write the failing controller test**

Append to `tests/unit/test_subsystem_glow.py`:

```python
class _Point:
    def __init__(self, x, y, z):
        self._x, self._y, self._z = x, y, z
    def GetX(self): return self._x
    def GetY(self): return self._y
    def GetZ(self): return self._z


class _Pod:
    def __init__(self, pos, radius=2.0):
        self._pos, self._radius = pos, radius
        self.disabled = self.destroyed = False
    def GetPosition(self): return self._pos
    def GetRadius(self): return self._radius
    def IsDisabled(self): return self.disabled
    def IsDestroyed(self): return self.destroyed


class _WarpAgg:
    def __init__(self, kids): self._kids = kids
    def GetNumChildSubsystems(self): return len(self._kids)
    def GetChildSubsystem(self, i): return self._kids[i]


class _Ship:
    def __init__(self, warp, impulse, sensor):
        self._warp, self._impulse, self._sensor = warp, impulse, sensor
    def GetWarpEngineSubsystem(self): return self._warp
    def GetImpulseEngineSubsystem(self): return self._impulse
    def GetSensorSubsystem(self): return self._sensor


class _FakeRenderer:
    def __init__(self, results):
        self._results = list(results)
        self.capsule_calls = []
        self.sphere_calls = []
        self.dim_calls = []
    def compute_capsule_region(self, iid, center, axis, radius):
        self.capsule_calls.append((iid, center, axis, radius))
        return self._results.pop(0)
    def add_sphere_region(self, iid, center, radius):
        self.sphere_calls.append((iid, center, radius))
        return self._results.pop(0)
    def set_glow_region_dim(self, iid, idx, dim_target, edge_time, flicker):
        self.dim_calls.append((iid, idx, dim_target, edge_time, flicker))


def test_controller_registers_capsule_for_warp_and_spheres_for_impulse_sensor():
    warp = _WarpAgg([_Pod(_Point(-3.0, 1.0, 0.0))])
    impulse = _Pod(_Point(0.0, -0.98, -0.45), radius=0.25)
    sensor = _Pod(_Point(0.0, -0.45, -0.5), radius=0.28)
    ship = _Ship(warp, impulse, sensor)
    rend = _FakeRenderer(results=[0, 1, 2])  # capsule, impulse sphere, sensor sphere

    ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)

    assert rend.capsule_calls == [(7, (-3.0, 1.0, 0.0), sg.WARP_AXIS, 2.0)]
    assert rend.sphere_calls == [
        (7, (0.0, -0.98, -0.45), 0.25),
        (7, (0.0, -0.45, -0.5), 0.28),
    ]
    assert len(ctrl._regions) == 3


def test_controller_drives_three_state_across_edges():
    impulse = _Pod(_Point(0.0, -0.98, -0.45), radius=0.25)
    ship = _Ship(warp=None, impulse=impulse, sensor=None)
    rend = _FakeRenderer(results=[0])  # only the impulse sphere registers
    ctrl = sg.ShipGlowController(rend, instance_id=7, ship=ship)
    assert len(ctrl._regions) == 1

    # healthy -> full, edge -1, flicker 0
    ctrl.update(now=10.0)
    assert rend.dim_calls[-1] == (7, 0, 1.0, -1.0, 0.0)

    # disabled -> dim 0, edge stamps 20, flicker 1
    impulse.disabled = True
    ctrl.update(now=20.0)
    assert rend.dim_calls[-1] == (7, 0, 0.0, 20.0, 1.0)

    # still disabled -> keep stamp 20
    ctrl.update(now=25.0)
    assert rend.dim_calls[-1] == (7, 0, 0.0, 20.0, 1.0)

    # destroyed -> dim 0, edge re-stamps 30, flicker 0
    impulse.disabled, impulse.destroyed = False, True
    ctrl.update(now=30.0)
    assert rend.dim_calls[-1] == (7, 0, 0.0, 30.0, 0.0)

    # repaired -> full, edge -1, flicker 0
    impulse.destroyed = False
    ctrl.update(now=40.0)
    assert rend.dim_calls[-1] == (7, 0, 1.0, -1.0, 0.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_subsystem_glow.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'ShipGlowController'`.

- [ ] **Step 3: Implement the controller**

Append to `engine/appc/subsystem_glow.py`:

```python
def _position_tuple(sub):
    """Body-frame (x, y, z) of a subsystem's hardpoint, or None."""
    if sub is None or not hasattr(sub, "GetPosition"):
        return None
    p = sub.GetPosition()
    if p is None:
        return None
    return (p.GetX(), p.GetY(), p.GetZ())


def _radius(sub) -> float:
    """Hardpoint radius in game units (default 1.0 if unspecified)."""
    if hasattr(sub, "GetRadius"):
        r = sub.GetRadius()
        if r:
            return float(r)
    return 1.0


class ShipGlowController:
    """Per-ship: register glow regions once, push state each frame.

    Capsule region per warp pod (elongated nacelles); sphere region for the
    impulse engine and the sensor array (compact spots). Holds
    (subsystem, region_index, prev_state, edge_time) per region. `renderer` is
    engine.renderer (injected for testability).
    """

    def __init__(self, renderer, instance_id, ship):
        self._r = renderer
        self._iid = instance_id
        self._regions = []  # dicts: sub, idx, prev, etime

        # Warp nacelles -> capsule regions (fit the elongated shape).
        for pod in warp_pods(ship.GetWarpEngineSubsystem()):
            pos = _position_tuple(pod)
            if pos is None:
                continue
            idx = self._r.compute_capsule_region(
                instance_id, pos, WARP_AXIS, _radius(pod))
            if idx < 0:
                continue
            self._regions.append(
                {"sub": pod, "idx": idx, "prev": HEALTHY, "etime": -1.0})

        # Impulse + sensors -> sphere regions (compact hardpoint spots).
        for sub in (ship.GetImpulseEngineSubsystem(),
                    ship.GetSensorSubsystem()):
            pos = _position_tuple(sub)
            if pos is None:
                continue
            idx = self._r.add_sphere_region(instance_id, pos, _radius(sub))
            if idx < 0:
                continue
            self._regions.append(
                {"sub": sub, "idx": idx, "prev": HEALTHY, "etime": -1.0})

    def update(self, now: float) -> None:
        """Read each region's live state and push dim/edge/flicker for `now`."""
        for reg in self._regions:
            state = glow_state(reg["sub"])
            etime = glow_edge(reg["prev"], state, reg["etime"], now)
            dim, flick = dim_and_flicker(state)
            self._r.set_glow_region_dim(self._iid, reg["idx"], dim, etime, flick)
            reg["prev"] = state
            reg["etime"] = etime
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_subsystem_glow.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystem_glow.py tests/unit/test_subsystem_glow.py
git commit -m "feat(glow): ShipGlowController registers + drives 3 subsystem regions

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task C3: Wire `ShipGlowController` into the host loop

**Files:**
- Modify: `engine/host_loop.py` (session field, spawn block ~1714, update loop ~2614, prune ~2642)

- [ ] **Step 1: Rename the session field**

At `engine/host_loop.py:1570-1572`, rename the field and its docstring:

```python
    # Subsystem glow-dimming controllers, keyed by render instance id.
    # Best-effort VFX; ships without the relevant subsystems get fewer regions.
    ship_glow_controllers: dict[int, Any] = field(default_factory=dict)
```

And the clear at ~line 1587: `self.ship_glow_controllers.clear()`.

- [ ] **Step 2: Update the spawn block**

Replace the spawn block at ~1710-1718:

```python
            # Subsystem glow dimming (best-effort VFX). Ships missing a warp /
            # impulse / sensor subsystem simply register fewer regions; any
            # failure must never block spawning the ship instance.
            try:
                from engine.appc.subsystem_glow import ShipGlowController
                sess.ship_glow_controllers[iid] = ShipGlowController(
                    r_, iid, ship)
            except Exception:
                pass  # glow dimming is best-effort VFX; never block spawn
```

- [ ] **Step 3: Update the per-frame update + prune**

At ~2614 rename the lookup:

```python
                        _wg = session.ship_glow_controllers.get(iid)
                        if _wg is not None:
                            _wg.update(_wg_now)
```

At ~2642 rename the prune loop target:

```python
                    for _dead in list(session.ship_glow_controllers.keys()):
                        if _dead not in _wg_live_iids:
                            del session.ship_glow_controllers[_dead]
```

- [ ] **Step 4: Verify host_loop imports and the engine smoke path is green**

Run: `uv run pytest tests/unit/test_subsystem_glow.py tests/unit/test_subsystems.py -q`
Expected: PASS. (Targeted subset — never run the full suite; it OOMs the host.)

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(glow): wire ShipGlowController into the host loop (all ships)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task C4: Remove the superseded `warp_glow.py`

**Files:**
- Delete: `engine/appc/warp_glow.py`
- Delete: `tests/unit/test_warp_glow.py`
- Check: `grep -rn "warp_glow\|WarpGlowController" engine/ tests/ native/`

- [ ] **Step 1: Confirm no remaining references**

Run: `grep -rn "warp_glow\|WarpGlowController\|warp_glow_controllers" engine/ tests/ native/`
Expected: no hits (host_loop migrated in C3; renderer.py never imported it).

- [ ] **Step 2: Delete the files**

```bash
git rm engine/appc/warp_glow.py tests/unit/test_warp_glow.py
```

- [ ] **Step 3: Verify the targeted suite still passes**

Run: `uv run pytest tests/unit/test_subsystem_glow.py tests/unit/test_subsystems.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(glow): remove warp_glow.py (superseded by subsystem_glow)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Phase D — In-app verification

### Task D1: Verify the three subsystems in the running engine

**Files:** none (manual/observational).

- [ ] **Step 1: Build clean (shader + native)**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: clean build.

- [ ] **Step 2: Run the engine**

Run: `./build/dauntless`
Load a mission with the player Galaxy (or any ship with impulse/sensor/warp hardpoints).

- [ ] **Step 3: Observe each state per subsystem**

Using dev combat cheats / applied damage, drive each of the impulse engine, sensor array, and a warp nacelle through: healthy → disabled → destroyed → repaired. Confirm:
- Healthy: glow unchanged from before the feature.
- Disabled: the glow within that hardpoint region flickers continuously between dark and full.
- Destroyed: the region blows out briefly then goes dark and stays dark.
- Repaired: full glow returns.
- The warp nacelle dims along its full elongated length (capsule), while impulse/sensor dim as compact spots (sphere).
- An undamaged NPC ship in the same scene shows no glow change.

- [ ] **Step 4: If a region is mis-sized or the flicker reads wrong**

Tune in `native/src/renderer/shaders/opaque.frag`: `DISABLED_FLOOR` (how dark the flicker troughs go), `GLOW_FLICKER_SECS` (blow-out duration), `STUTTER_FREQ` (flicker rate). Re-run `cmake -B build -S . && cmake --build build -j` after any shader edit. No code/logic changes expected.

---

## Self-Review

**Spec coverage:**
- Rename nacelle→glow_region → Task A1. ✓
- Keep warp capsule shape-detection → `compute_capsule_region` unchanged (A1), capsule used for warp pods in `ShipGlowController` (C2). ✓
- Sphere regions for impulse/sensors → `add_sphere_region` (B4), used in C2. ✓
- Three-state behaviour (healthy/disabled-flicker/destroyed-off) → `flicker` field (B1), packed (B2), bound (B3), shader (B5), Python mapping `glow_state`/`dim_and_flicker`/`glow_edge` (C1). ✓
- Unify warp onto the new behaviour → warp pods register through the same `ShipGlowController` + shader path (C2/C3); `warp_glow.py` removed (C4). ✓
- All ships → host_loop constructs a controller per ship instance (C3). ✓
- Stock-BC parity → default-inactive + flicker-default-0 C++ locks (A1/B1), `count == 0` short-circuit preserved (A1). ✓
- Tests → C++ `glow_region_test.cc` (A1/B1/B4), Python `test_subsystem_glow.py` (C1/C2), in-app (D1). ✓

**Placeholder scan:** none — every code step shows full code; every run step shows the command + expected result.

**Type/name consistency:** `compute_capsule_region`, `add_sphere_region`, `set_glow_region_dim` (5-arg with `flicker`), `Instance::GlowRegion`/`glow_regions`/`kMaxGlowRegions`/`flicker`, `u_glow_region_a/b/c`/`u_glow_region_count`/`glow_region_mult`, and the Python `glow_state`/`dim_and_flicker`/`glow_edge`/`warp_pods`/`ShipGlowController`/`WARP_AXIS` are used identically across all tasks. Renderer fake-method names in the Python tests (`compute_capsule_region`, `add_sphere_region`, `set_glow_region_dim`) match the wrappers. ✓
