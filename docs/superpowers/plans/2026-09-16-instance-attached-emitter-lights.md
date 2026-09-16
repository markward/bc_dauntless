# Instance-Attached Emitter Lights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Subsystem light emitters are resolved to world space in C++ through the hull's own per-frame world matrix, so the cast light is locked to the hull on any refresh rate and the per-frame Python producer does no transforms.

**Architecture:** `DynamicLightDescriptor` gains an `instance_id`; when set, its geometry is ship body-frame (unscaled GU). A pure `resolve_attached_dynamic_lights(world, lights)` runs once in `frame()` right after `sync_instance_transforms_from_store()` and rewrites attached entries to world space through `inst->world` (the particle-emitter pattern). Python caches each emitter's static struct at cache-build time and per frame only copies it, sets `intensity` and `instance_id`.

**Tech Stack:** C++20 / glm / gtest (`build/native/tests/renderer/renderer_tests`), pybind11 binding in `native/src/host/host_bindings.cc`, Python 3 + pytest.

**Spec:** `docs/superpowers/specs/2026-09-16-instance-attached-emitter-lights-design.md`

## Global Constraints

- One build tree: `cmake --build build -j`; C++ tests via `ctest --test-dir build -R <name>` or the `build/native/tests/renderer/renderer_tests` binary. **Never** run cmake inside `native/`.
- Shared checkout: stage with explicit pathspecs only. **Never** `git add -A`, `git checkout --`, `git stash`, `git restore`, `git reset --hard`, `git clean`.
- Rotation convention is column-vector, right-handed: `v_world = R · v_body`. `inst->world` is `[R·s | t]` with uniform scale `s`.
- Emitter offsets are **unscaled** body GU: world = `t + R·p`, never `t + R·s·p`.
- Torpedo and explosion light producers must stay byte-identical (no `instance_id` key).
- Gate before calling anything done: `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`).
- Commit messages end with: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

---

### Task 1: `resolve_attached_dynamic_lights` (renderer, pure)

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h:147-157` (`DynamicLightDescriptor`)
- Modify: `native/src/renderer/include/renderer/dynamic_lights.h`
- Modify: `native/src/renderer/dynamic_lights.cc`
- Test: `native/tests/renderer/dynamic_lights_test.cc`

**Interfaces:**
- Consumes: `scenegraph::World` (`native/src/scenegraph/include/scenegraph/world.h`: `create_instance`, `set_world_transform`, `destroy_instance`, `get`), `scenegraph::InstanceId` (`{0,0}` default = sentinel, `operator==`).
- Produces: `renderer::DynamicLightDescriptor::instance_id` (`scenegraph::InstanceId`, default sentinel) and
  `void renderer::resolve_attached_dynamic_lights(const scenegraph::World& world, std::vector<DynamicLightDescriptor>& lights);`

- [ ] **Step 1: Write the failing tests**

Append to `native/tests/renderer/dynamic_lights_test.cc`:

```cpp
// ─────────────────────────────────────────────────────────────────────────
// resolve_attached_dynamic_lights
// ─────────────────────────────────────────────────────────────────────────

#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/constants.hpp>
#include <scenegraph/world.h>

using renderer::resolve_attached_dynamic_lights;

namespace {

// T · R · S with R = 90° about +Z (maps body +X to world +Y), s = 2.5.
glm::mat4 rotated_scaled_world(const glm::vec3& t, float s) {
    const glm::mat4 T = glm::translate(glm::mat4(1.0f), t);
    const glm::mat4 R = glm::rotate(glm::mat4(1.0f), glm::half_pi<float>(),
                                    glm::vec3(0.0f, 0.0f, 1.0f));
    const glm::mat4 S = glm::scale(glm::mat4(1.0f), glm::vec3(s));
    return T * R * S;
}

void expect_vec3_near(const glm::vec3& got, const glm::vec3& want, float tol = 1e-4f) {
    EXPECT_NEAR(got.x, want.x, tol);
    EXPECT_NEAR(got.y, want.y, tol);
    EXPECT_NEAR(got.z, want.z, tol);
}

}  // namespace

TEST(ResolveAttachedDynamicLights, PointLightLandsAtTranslationPlusRotatedOffsetScaleDividedOut) {
    scenegraph::World world;
    const auto iid = world.create_instance(1);
    const glm::vec3 t(10.0f, -5.0f, 2.0f);
    world.set_world_transform(iid, rotated_scaled_world(t, 2.5f));

    DynamicLightDescriptor l;
    l.instance_id = iid;
    l.pos_a = glm::vec3(1.0f, 0.0f, 0.0f);   // body-frame, unscaled GU
    l.pos_b = l.pos_a;
    std::vector<DynamicLightDescriptor> lights{l};

    resolve_attached_dynamic_lights(world, lights);

    ASSERT_EQ(lights.size(), 1u);
    // R·(1,0,0) = (0,1,0); scale 2.5 must NOT appear in the offset.
    expect_vec3_near(lights[0].pos_a, t + glm::vec3(0.0f, 1.0f, 0.0f));
    expect_vec3_near(lights[0].pos_b, t + glm::vec3(0.0f, 1.0f, 0.0f));
}

TEST(ResolveAttachedDynamicLights, StripEndpointBResolvedIndependently) {
    scenegraph::World world;
    const auto iid = world.create_instance(1);
    const glm::vec3 t(0.0f, 0.0f, 100.0f);
    world.set_world_transform(iid, rotated_scaled_world(t, 3.0f));

    DynamicLightDescriptor l;
    l.instance_id = iid;
    l.pos_a = glm::vec3(1.0f, 0.0f, 0.0f);
    l.pos_b = glm::vec3(-1.0f, 0.0f, 0.0f);
    std::vector<DynamicLightDescriptor> lights{l};

    resolve_attached_dynamic_lights(world, lights);

    ASSERT_EQ(lights.size(), 1u);
    expect_vec3_near(lights[0].pos_a, t + glm::vec3(0.0f,  1.0f, 0.0f));
    expect_vec3_near(lights[0].pos_b, t + glm::vec3(0.0f, -1.0f, 0.0f));
}

TEST(ResolveAttachedDynamicLights, ConeDirectionAndUpRotatedAndUnitLength) {
    scenegraph::World world;
    const auto iid = world.create_instance(1);
    world.set_world_transform(iid, rotated_scaled_world(glm::vec3(0.0f), 4.0f));

    DynamicLightDescriptor l;
    l.instance_id = iid;
    l.pos_a = l.pos_b = glm::vec3(0.0f);
    l.direction  = glm::vec3(1.0f, 0.0f, 0.0f);
    l.up         = glm::vec3(0.0f, 0.0f, 1.0f);
    l.spot_tan_x = 0.5f;
    l.spot_tan_y = 0.5f;
    std::vector<DynamicLightDescriptor> lights{l};

    resolve_attached_dynamic_lights(world, lights);

    ASSERT_EQ(lights.size(), 1u);
    expect_vec3_near(lights[0].direction, glm::vec3(0.0f, 1.0f, 0.0f));
    expect_vec3_near(lights[0].up,        glm::vec3(0.0f, 0.0f, 1.0f));
    EXPECT_NEAR(glm::length(lights[0].direction), 1.0f, 1e-5f);  // scale 4 divided out
    EXPECT_NEAR(glm::length(lights[0].up),        1.0f, 1e-5f);
}

TEST(ResolveAttachedDynamicLights, UnattachedEntriesAreUntouched) {
    scenegraph::World world;
    DynamicLightDescriptor l;                       // instance_id == sentinel
    l.pos_a = glm::vec3(7.0f, 8.0f, 9.0f);
    l.pos_b = glm::vec3(1.0f, 2.0f, 3.0f);
    l.direction = glm::vec3(0.0f, 1.0f, 0.0f);
    l.up = glm::vec3(0.0f, 0.0f, 1.0f);
    l.spot_tan_x = 0.3f;
    std::vector<DynamicLightDescriptor> lights{l};

    resolve_attached_dynamic_lights(world, lights);

    ASSERT_EQ(lights.size(), 1u);
    expect_vec3_near(lights[0].pos_a, l.pos_a, 0.0f);
    expect_vec3_near(lights[0].pos_b, l.pos_b, 0.0f);
    expect_vec3_near(lights[0].direction, l.direction, 0.0f);
    expect_vec3_near(lights[0].up, l.up, 0.0f);
}

TEST(ResolveAttachedDynamicLights, MissingInstanceIsDropped) {
    scenegraph::World world;
    const auto iid = world.create_instance(1);
    world.destroy_instance(iid);

    DynamicLightDescriptor attached;
    attached.instance_id = iid;
    DynamicLightDescriptor plain;
    plain.pos_a = plain.pos_b = glm::vec3(5.0f);
    std::vector<DynamicLightDescriptor> lights{attached, plain};

    resolve_attached_dynamic_lights(world, lights);

    ASSERT_EQ(lights.size(), 1u);
    expect_vec3_near(lights[0].pos_a, glm::vec3(5.0f), 0.0f);
}

TEST(ResolveAttachedDynamicLights, ResolvedEntryInstanceIdIsClearedToSentinel) {
    scenegraph::World world;
    const auto iid = world.create_instance(1);
    world.set_world_transform(iid, glm::mat4(1.0f));

    DynamicLightDescriptor l;
    l.instance_id = iid;
    std::vector<DynamicLightDescriptor> lights{l};

    resolve_attached_dynamic_lights(world, lights);

    ASSERT_EQ(lights.size(), 1u);
    EXPECT_TRUE(lights[0].instance_id == scenegraph::InstanceId{});
}
```

- [ ] **Step 2: Build to verify the tests fail to compile**

Run: `cmake --build build -j --target renderer_tests 2>&1 | tail -20`
Expected: compile errors — `instance_id` is not a member of `DynamicLightDescriptor`; `resolve_attached_dynamic_lights` undeclared.

- [ ] **Step 3: Add the descriptor field**

In `native/src/renderer/include/renderer/frame.h`, inside `struct DynamicLightDescriptor` after `spot_tan_y`:

```cpp
    /// Attachment. {0,0} (the default) means every position/direction above
    /// is already WORLD space. Set => pos_a, pos_b, direction and up are the
    /// instance's BODY frame in unscaled GU, and frame() resolves them to
    /// world through inst->world via resolve_attached_dynamic_lights before
    /// any draw reads the list (same pattern as ParticleEmitterDescriptor).
    scenegraph::InstanceId instance_id{};
```

(`frame.h` already includes `scenegraph/instance.h` for `ParticleEmitterDescriptor`; verify with `grep -n "scenegraph/instance.h" native/src/renderer/include/renderer/frame.h` and add the include if it is missing.)

- [ ] **Step 4: Declare and implement the resolve pass**

`native/src/renderer/include/renderer/dynamic_lights.h` — add after the `#include <renderer/frame.h>` line:

```cpp
namespace scenegraph { class World; }
```

and after `select_dynamic_lights`'s declaration (before the closing `}  // namespace renderer`):

```cpp
/// Resolve every ATTACHED light (instance_id != {0,0}) in `lights` to world
/// space through its instance's CURRENT `world` matrix, in place. Body
/// positions are unscaled GU, so the instance's uniform scale (column-0
/// length of `world`, the same recovery select_instance_dynamic_lights and
/// shield_pass.cc use) is divided back out: p_world = t + (R·s·p)/s.
/// Directions (cones only) are rotated and re-normalised. The resolved
/// entry's instance_id is reset to the sentinel so nothing downstream can
/// tell it was attached. An attached light whose instance no longer exists
/// is erased (particle_pass.cc makes the same choice). Unattached entries
/// are byte-identical before and after.
///
/// MUST run once per frame AFTER the transform-store sweep and every
/// set_world_transform push have landed (host frame(): right after
/// sync_instance_transforms_from_store()) — resolving at set_dynamic_lights
/// time would read last frame's matrices, which is the hull/light jitter
/// this exists to remove.
void resolve_attached_dynamic_lights(const scenegraph::World& world,
                                     std::vector<DynamicLightDescriptor>& lights);
```

`native/src/renderer/dynamic_lights.cc` — add `#include <scenegraph/world.h>` after the existing includes, and append inside `namespace renderer` (after `select_dynamic_lights`):

```cpp
void resolve_attached_dynamic_lights(const scenegraph::World& world,
                                     std::vector<DynamicLightDescriptor>& lights) {
    const scenegraph::InstanceId sentinel{};
    auto out = lights.begin();
    for (auto it = lights.begin(); it != lights.end(); ++it) {
        DynamicLightDescriptor l = *it;
        if (!(l.instance_id == sentinel)) {
            const scenegraph::Instance* inst = world.get(l.instance_id);
            if (inst == nullptr) continue;      // despawned between set and frame: drop
            const glm::mat4& M = inst->world;
            const glm::mat3 RS = glm::mat3(M);
            const float s = std::max(glm::length(glm::vec3(M[0])), 1e-6f);
            const glm::vec3 t = glm::vec3(M[3]);
            l.pos_a = t + (RS * l.pos_a) / s;
            l.pos_b = t + (RS * l.pos_b) / s;
            if (l.spot_tan_x >= 0.0f) {
                l.direction = glm::normalize(RS * l.direction);
                l.up        = glm::normalize(RS * l.up);
            }
            l.instance_id = sentinel;
        }
        *out++ = l;
    }
    lights.erase(out, lights.end());
}
```

(`<algorithm>` is already included for `std::max`.)

- [ ] **Step 5: Build and run the new tests**

Run: `cmake --build build -j --target renderer_tests 2>&1 | tail -5 && ./build/native/tests/renderer/renderer_tests --gtest_filter='ResolveAttachedDynamicLights.*:SelectDynamicLights.*:SegmentDistance.*'`
Expected: all `ResolveAttachedDynamicLights.*` PASS; existing `SelectDynamicLights.*` / `SegmentDistance.*` still PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h native/src/renderer/include/renderer/dynamic_lights.h native/src/renderer/dynamic_lights.cc native/tests/renderer/dynamic_lights_test.cc
git commit -m "feat(renderer): instance-attached dynamic lights resolved through inst->world

DynamicLightDescriptor gains instance_id; when set its geometry is ship
body-frame (unscaled GU) and resolve_attached_dynamic_lights rewrites it
to world space through the instance's current world matrix — the same
matrix the hull is drawn with, so an attached light cannot disagree with
its hull by construction (the particle-emitter pattern).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Binding parses `instance_id`; `frame()` resolves after the store sweep

**Files:**
- Modify: `native/src/host/host_bindings.cc:2894-2945` (`set_dynamic_lights` lambda) and `:843-848` (`frame()`, the `xform_sync` scope)
- Test: `tests/host/test_dynamic_lights_binding.py`
- Create: `tests/host/test_attached_lights_resolve_ordering.py`

**Interfaces:**
- Consumes: `renderer::resolve_attached_dynamic_lights(const scenegraph::World&, std::vector<DynamicLightDescriptor>&)` (Task 1); `g_world`, `g_dynamic_lights`, `sync_instance_transforms_from_store()` (existing globals/functions in `host_bindings.cc`); `scenegraph::InstanceId` is already a pybind class (`host_bindings.cc:1804`).
- Produces: `set_dynamic_lights` accepts an optional `instance_id` key (a `_dauntless_host.InstanceId` or `None`); `frame()` calls `renderer::resolve_attached_dynamic_lights(g_world, g_dynamic_lights)` inside the `xform_sync` scope immediately after `sync_instance_transforms_from_store()`.

- [ ] **Step 1: Write the failing binding tests**

Append to `tests/host/test_dynamic_lights_binding.py`:

```python
def test_instance_id_key_is_optional_and_accepts_none():
    """`instance_id` is the second optional key (after position_b). Absent or
    None => world-space light, exactly as before."""
    import _dauntless_host
    d = _point_light()
    d["instance_id"] = None
    _dauntless_host.set_dynamic_lights([d, _point_light()])


def test_instance_id_accepts_an_instance_id_object():
    import _dauntless_host
    d = _point_light()
    d["instance_id"] = _dauntless_host.InstanceId()   # the {0,0} sentinel
    _dauntless_host.set_dynamic_lights([d])


def test_instance_id_of_wrong_type_raises():
    import _dauntless_host
    d = _point_light()
    d["instance_id"] = 42
    with pytest.raises(Exception):
        _dauntless_host.set_dynamic_lights([d])
```

Create `tests/host/test_attached_lights_resolve_ordering.py`:

```python
"""Source-level ordering guard for attached dynamic lights.

`resolve_attached_dynamic_lights` rewrites body-frame lights to world space
through each instance's CURRENT `world` matrix. That is only the hull's
matrix if it runs AFTER `sync_instance_transforms_from_store()` (which
recomposes every store-bound instance at the top of frame()) and never at
`set_dynamic_lights` time (which would read last frame's matrices — the
hull/light jitter this feature removes). frame() lives in the pybind host
and needs a GL window, so this is a source-order guard in the style of
tests/host/test_camera_dt_wiring.py.
"""
import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "native" / "src" / "host" / "host_bindings.cc"


def _frame_body() -> str:
    src = _SRC.read_text()
    # The sweep call inside frame() is the one preceded by the xform_sync scope.
    m = re.search(r'DAUNTLESS_FRAME_SCOPE\("xform_sync"\);(.*?)DAUNTLESS_FRAME_SCOPE\("anim"\)',
                  src, re.S)
    assert m, "frame()'s xform_sync scope not found"
    return m.group(1)


def test_resolve_runs_inside_xform_sync_after_the_store_sweep():
    body = _frame_body()
    sweep = body.find("sync_instance_transforms_from_store();")
    resolve = body.find("renderer::resolve_attached_dynamic_lights(g_world, g_dynamic_lights);")
    assert sweep >= 0, "store sweep missing from xform_sync scope"
    assert resolve >= 0, "resolve_attached_dynamic_lights not called in xform_sync scope"
    assert resolve > sweep, "resolve must run AFTER the store sweep"


def test_resolve_is_not_called_from_the_set_dynamic_lights_binding():
    src = _SRC.read_text()
    start = src.find('m.def("set_dynamic_lights"')
    assert start >= 0
    end = src.find("m.def(", start + 1)
    binding = src[start:end]
    assert "resolve_attached_dynamic_lights" not in binding
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/host/test_dynamic_lights_binding.py tests/host/test_attached_lights_resolve_ordering.py -v`
Expected: `test_instance_id_accepts_an_instance_id_object` / `test_instance_id_key_is_optional_and_accepts_none` may pass (unknown keys are ignored today), `test_instance_id_of_wrong_type_raises` FAILS (key ignored, nothing raises), and both ordering tests FAIL (`resolve_attached_dynamic_lights not called`).

- [ ] **Step 3: Parse the key in the binding**

In `native/src/host/host_bindings.cc`, inside the `set_dynamic_lights` lambda, after the `spot_tan_y` block and before `g_dynamic_lights.push_back(l);`:

```cpp
                  // Optional attachment (second optional key after position_b).
                  // Set => the geometry above is BODY-frame and frame()
                  // resolves it through inst->world after the store sweep.
                  // Absent/None => world-space, byte-identical to before.
                  if (d.contains("instance_id") && !d["instance_id"].is_none())
                      l.instance_id = d["instance_id"].cast<scenegraph::InstanceId>();
```

Update the lambda's docstring comment on `position_b` ("the ONE optional key") to say `position_b` and `instance_id` are the two optional keys.

- [ ] **Step 4: Call the resolve pass in `frame()`**

In `frame()`, change the `xform_sync` block to:

```cpp
    {
        // Store-bound instances first: everything below (animation, culling,
        // every draw pass) reads inst->world.
        DAUNTLESS_FRAME_SCOPE("xform_sync");
        sync_instance_transforms_from_store();
        // Attached dynamic lights resolve through the SAME inst->world the
        // hull draws with this frame. Must follow the sweep (store-bound
        // ships) and every set_world_transform push (interpolated ships,
        // which landed before frame() was entered).
        renderer::resolve_attached_dynamic_lights(g_world, g_dynamic_lights);
    }
```

Confirm `host_bindings.cc` includes `renderer/dynamic_lights.h` (`grep -n "renderer/dynamic_lights.h" native/src/host/host_bindings.cc`); add `#include <renderer/dynamic_lights.h>` next to the other `renderer/` includes if not.

- [ ] **Step 5: Rebuild the host module and run the tests**

Run: `cmake --build build -j 2>&1 | tail -3 && uv run pytest tests/host/test_dynamic_lights_binding.py tests/host/test_attached_lights_resolve_ordering.py -v`
Expected: all PASS. (If `_dauntless_host` reports an `AttributeError`/stale surface, the `.so` is stale — rebuild from `build/`, do not touch Python.)

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc tests/host/test_dynamic_lights_binding.py tests/host/test_attached_lights_resolve_ordering.py
git commit -m "feat(host): set_dynamic_lights accepts instance_id; frame() resolves attached lights after the store sweep

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Cache the static emitter struct at cache-build time

**Files:**
- Modify: `engine/host_loop.py:1222-1280` (`_build_ship_emitter_cache`)
- Test: `tests/test_host_loop_emitter_lights.py` (cache tests, ~line 293-340), `tests/test_host_loop_emitter_refresh.py:123-150`

**Interfaces:**
- Consumes: `light_emitters.emitter_spec_to_struct(spec) -> dict` (existing, `engine/appc/light_emitters.py:156`).
- Produces: cache entries are 6-tuples `(sub, is_impulse, is_warp, phase, spec, struct)` where `struct` is the body-frame `emitter_spec_to_struct(spec)` result. Task 4's producer reads `struct` from index 5.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_host_loop_emitter_lights.py`:

```python
def test_cache_entries_carry_the_prebuilt_body_frame_struct(monkeypatch):
    """The static geometry is converted ONCE at cache build, not per frame.
    Entry layout: (sub, is_impulse, is_warp, phase, spec, struct)."""
    prop = _emitter_prop("strip", (1.0, 2.0, 3.0), axis=(0.0, -1.0, 0.0), length=2.0)
    sub = _Sub(prop)

    class _Ship3:
        pass
    ship = _Ship3()
    monkeypatch.setattr("engine.ui.ship_property_viewer._iter_subsystems",
                        lambda s: [sub] if s is ship else [])

    entries = _build_ship_emitter_cache(ship)
    assert len(entries) == 1
    assert len(entries[0]) == 6
    _sub, _imp, _warp, _ph, spec, struct = entries[0]
    assert struct == light_emitters.emitter_spec_to_struct(spec)
    # Body-frame strip: endpoints straddle the authored position along the axis.
    assert struct["position"] == pytest.approx((1.0, 3.0, 3.0))
    assert struct["position_b"] == pytest.approx((1.0, 1.0, 3.0))
    assert "instance_id" not in struct   # the producer adds it per frame
```

In `tests/test_host_loop_emitter_refresh.py::test_refresh_ship_emitters_success_rebuilds_iid_cache`, replace

```python
    sub, _imp, _warp, _ph, spec = rebuilt[0]
    assert sub is subA
    assert spec["position"] == (9.0, 8.0, 7.0)
```

with

```python
    sub, _imp, _warp, _ph, spec, struct = rebuilt[0]
    assert sub is subA
    assert spec["position"] == (9.0, 8.0, 7.0)
    # The cached struct is rebuilt from the NEW spec too — SPV Save refreshes
    # the geometry the renderer sees, not just the spec.
    assert struct["position"] == (9.0, 8.0, 7.0)
    assert struct["color"] == (0.0, 1.0, 0.0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_host_loop_emitter_lights.py::test_cache_entries_carry_the_prebuilt_body_frame_struct tests/test_host_loop_emitter_refresh.py::test_refresh_ship_emitters_success_rebuilds_iid_cache -v`
Expected: both FAIL (`len(entries[0]) == 5`, unpack `ValueError: not enough values`).

- [ ] **Step 3: Build the struct in the cache**

In `engine/host_loop.py:_build_ship_emitter_cache`, change the entry append:

```python
        for j, spec in enumerate(specs):
            # The static body-frame geometry (positions, cone tangents, colour,
            # radius) is converted ONCE here; the per-frame producer only copies
            # it and sets intensity + instance_id. The renderer resolves it to
            # world through the hull's own matrix (resolve_attached_dynamic_lights).
            struct = light_emitters.emitter_spec_to_struct(spec)
            entries.append((sub, is_impulse, is_warp, j * 1.7 + si, spec, struct))
```

Update the docstring's first line: "Returns a list of `(sub, is_impulse, is_warp, phase, spec, struct)` tuples" and add one sentence: "`struct` is `light_emitters.emitter_spec_to_struct(spec)`, the body-frame render dict, built here so SPV Save (`refresh_ship_emitters`) refreshes it along with the spec."

- [ ] **Step 4: Run the two tests plus the neighbouring cache tests**

Run: `uv run pytest tests/test_host_loop_emitter_lights.py tests/test_host_loop_emitter_refresh.py tests/unit/test_warp_engine_glow.py -v`
Expected: the two new/updated tests PASS. The producer tests in `test_host_loop_emitter_lights.py` that hand-build 5-tuples still PASS at this point (the producer still unpacks 5 — Task 4 changes both together). `test_warp_engine_glow.py` uses `e[0..2]` and PASSES.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/test_host_loop_emitter_lights.py tests/test_host_loop_emitter_refresh.py
git commit -m "refactor(emitters): cache the body-frame render struct at cache build

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Producer emits body-frame lights tagged with `instance_id`

**Files:**
- Modify: `engine/host_loop.py:1395-1465` (`_build_emitter_light_render_data`), `:877-900` (`_advance_combat` docstring mention of world transforms)
- Test: `tests/test_host_loop_emitter_lights.py` (rewrite the pose-transform tests), `tests/unit/test_dynamic_light_render_marshal.py` (add one guard)

**Interfaces:**
- Consumes: 6-tuple cache entries from Task 3; `light_emitters.resolve_emitter_intensity(...)`, `_camera_distance_fade(...)`, `_warp_glow_envelope(...)`, `commanded_impulse_frac(...)` (all existing, unchanged).
- Produces: each emitter dict = `dict(struct)` + `intensity` + `instance_id == iid`, positions/direction/up **body-frame**. Signature unchanged: `_build_emitter_light_render_data(ship_instances, ship_emitters, player=None) -> list[dict]`.

- [ ] **Step 1: Rewrite the producer tests**

In `tests/test_host_loop_emitter_lights.py`:

(a) Change `_Ship.GetWorldRotation` so any call fails the test — the producer must never read it now:

```python
    def GetWorldRotation(self):
        raise AssertionError(
            "producer must not read GetWorldRotation: lights are body-frame and "
            "resolved by the renderer through inst->world")
```

(b) Add a helper right after the `_Ship` class, and use it in every test that builds a cache entry by hand:

```python
def _entry(sub, spec, is_impulse=False, is_warp=False, phase=0.0):
    """One cache entry in the Task-3 layout, struct prebuilt like the real cache."""
    return (sub, is_impulse, is_warp, phase, spec,
            light_emitters.emitter_spec_to_struct(spec))
```

Replace every hand-built `(sub, False, False, 0.0, spec)` / `(_Sub(prop), False, False, 0.0, spec)` tuple in the file with `_entry(sub, spec)` / `_entry(_Sub(prop), spec)` (lines ~93, 112, 136, 153, 195-196, 258 — grep `False, False, 0.0` to find them all).

(c) Replace `test_rotated_translated_ship_transforms_body_position_to_world` with:

```python
def test_rotated_translated_ship_emits_body_frame_position_and_instance_id():
    """The producer no longer transforms anything: the position stays the
    authored body-frame offset and the dict carries the ship's render
    instance id so the renderer resolves it through the hull's own matrix."""
    loc = (10.0, -5.0, 2.0)
    rot = TGMatrix3()
    rot.MakeZRotation(math.pi / 2.0)
    ship = _Ship(loc=loc, rot=rot)
    body_pos = (1.0, 0.0, 0.0)
    prop = _point_prop(body_pos)
    sub = _Sub(prop)
    spec = light_emitters.baked_emitters(prop)[0]

    ship_instances = {ship: 3}
    ship_emitters = {3: [_entry(sub, spec)]}

    out = _build_emitter_light_render_data(ship_instances, ship_emitters)
    assert len(out) == 1
    assert out[0]["position"] == pytest.approx(body_pos)
    assert out[0]["instance_id"] == 3
    assert "position_b" not in out[0]
```

(d) Replace `test_strip_and_cone_transform_correctly_on_rotated_translated_ship` and `test_elliptical_cone_up_transforms_with_direction_on_rotated_ship` with:

```python
def test_strip_and_cone_stay_body_frame_and_carry_instance_id():
    rot = TGMatrix3()
    rot.MakeZRotation(math.pi / 2.0)
    ship = _Ship(loc=(4.0, 4.0, 4.0), rot=rot)
    strip_prop = _emitter_prop("strip", (1.0, 2.0, 3.0), axis=(0.0, -1.0, 0.0), length=2.0)
    cone_prop = _emitter_prop("cone", (0.0, 0.0, 0.0), axis=(1.0, 0.0, 0.0),
                              length=2.0, radius=1.0)
    strip_spec = light_emitters.baked_emitters(strip_prop)[0]
    cone_spec = light_emitters.baked_emitters(cone_prop)[0]
    ship_instances = {ship: 9}
    ship_emitters = {9: [_entry(_Sub(strip_prop), strip_spec),
                         _entry(_Sub(cone_prop), cone_spec)]}

    out = _build_emitter_light_render_data(ship_instances, ship_emitters)
    assert len(out) == 2
    strip, cone = out
    assert strip["position"] == pytest.approx((1.0, 3.0, 3.0))
    assert strip["position_b"] == pytest.approx((1.0, 1.0, 3.0))
    assert strip["instance_id"] == 9
    assert cone["direction"] == pytest.approx((1.0, 0.0, 0.0))
    assert cone["up"] == pytest.approx(light_emitters.emitter_spec_to_struct(cone_spec)["up"])
    assert cone["instance_id"] == 9


def test_producer_does_not_mutate_the_cached_struct():
    """Per-frame output is a COPY: intensity/instance_id must never leak
    back into the cache entry shared across frames."""
    ship = _Ship()
    prop = _point_prop((1.0, 2.0, 3.0), intensity=2.0)
    spec = light_emitters.baked_emitters(prop)[0]
    entry = _entry(_Sub(prop), spec)
    out = _build_emitter_light_render_data({ship: 5}, {5: [entry]})
    assert out[0]["instance_id"] == 5
    assert "instance_id" not in entry[5]
    assert entry[5]["intensity"] == 2.0
```

(e) Fix the identity test's expectations: `test_healthy_point_emitter_identity_pose_produces_one_light` keeps its asserts and gains `assert d["instance_id"] == 42`.

Add to `tests/unit/test_dynamic_light_render_marshal.py` (at the end):

```python
def test_torpedo_lights_are_world_space_and_carry_no_instance_id():
    """Torpedo lights are genuinely world-space; only ship emitters attach.
    A stray instance_id here would make the renderer re-transform a world
    position through some ship's matrix."""
    _make_photon()          # registers one photon (same setup as
                            # test_mixed_registry_emits_one_light_for_the_photon_only)
    out = _build_dynamic_light_render_data()
    assert len(out) == 1
    assert "instance_id" not in out[0]
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `uv run pytest tests/test_host_loop_emitter_lights.py tests/unit/test_dynamic_light_render_marshal.py -v`
Expected: the body-frame/instance_id tests FAIL with `len(out) == 0` (the producer still calls `GetWorldRotation`, whose `AssertionError` it swallows under "emitter light ship transform", so the ship yields nothing). `test_producer_does_not_mutate_the_cached_struct` FAILS the same way. The marshal guard PASSES already (torpedo producer untouched).

- [ ] **Step 3: Rewrite the producer body**

Replace the body of `_build_emitter_light_render_data` from `now = App.g_kUtopiaModule.GetGameTime()` to the end with:

```python
    now = App.g_kUtopiaModule.GetGameTime()
    # Warp-nacelle brightening is player-only and only during a cross-system
    # warp; computed once per frame rather than per ship.
    warp_glow = _warp_glow_envelope(player)
    for ship, iid in ship_instances.items():
        entries = ship_emitters.get(iid)
        if not entries:
            continue
        try:
            loc = ship.GetWorldLocation()
            frac = commanded_impulse_frac(ship)
        except Exception as _e:
            dev_mode.log_swallowed("emitter light ship transform", _e)
            continue
        # Camera-distance gate, per SHIP rather than per emitter: emitters sit
        # within a couple of GU of hull centre, so hull-centre distance decides
        # the whole ship's emitters at once — one test instead of N, and no
        # chance of one nacelle fading a frame before the other. The early-out
        # is the point: a gated-out ship skips every emitter below. The LIVE
        # location is fine here: a one-tick error on the ~86 GU cull band is
        # invisible, and it is the only pose read left in this producer.
        fade = _camera_distance_fade((loc.x, loc.y, loc.z))
        if fade is None:
            continue
        _wg = warp_glow if ship is player else None
        for (sub, is_impulse, is_warp, phase, spec, struct) in entries:
            try:
                inten = light_emitters.resolve_emitter_intensity(
                    spec, sub, now, throttle_frac=frac, is_impulse=is_impulse,
                    powered=True, phase=phase, is_warp=is_warp, warp_glow=_wg)
                if inten is None:
                    continue
                # BODY-frame geometry, straight from the cache. No transform
                # here: the renderer resolves it through the hull's own
                # inst->world after the store sweep (resolve_attached_dynamic_
                # lights), so the light and the hull share one pose per frame
                # — interpolated, live or mid-handover alike. Shallow copy is
                # enough: every value in `struct` is an immutable tuple/float.
                d = dict(struct)
                d["intensity"] = inten * fade
                d["instance_id"] = iid
                out.append(d)
            except Exception as _e:
                dev_mode.log_swallowed("emitter light produce", _e)
                continue
    return out
```

Update the function docstring: replace "Body-frame specs are transformed to world via the ship's world loc + rotation (column-vector R·v)" with "Body-frame structs (cached at spawn by `_build_ship_emitter_cache`) are emitted as-is, tagged with the ship's render `instance_id`; the renderer resolves them to world through the hull's own matrix after the transform sweep, so the cast light is locked to the hull on any refresh rate."

In `_advance_combat`'s docstring (`host_loop.py:~892`), change "cached body-frame ... transformed to world" wording if present to say the emitters are emitted body-frame + `instance_id`.

- [ ] **Step 4: Run the emitter, marshal, budget, fade, scope and integration tests**

Run: `uv run pytest tests/test_host_loop_emitter_lights.py tests/test_host_loop_emitter_refresh.py tests/unit/test_dynamic_light_render_marshal.py tests/unit/test_dynamic_light_budget.py tests/unit/test_dynamic_light_scope.py tests/unit/test_dynamic_light_camera_fade.py tests/unit/test_warp_engine_glow.py tests/integration/test_combat_vfx_routes_through_host_io.py -v`
Expected: all PASS, after the following edit to `tests/unit/test_dynamic_light_camera_fade.py`, which hand-builds 5-tuple entries at lines ~184 and ~218-219 (it tests the fade gate, not the transform; `test_dynamic_light_scope.py` builds no entries and needs no change):

```python
# line ~184, in _emitter_lights_for_ship_at:
        {ship: 1}, {1: [(sub, False, False, 0.0, spec,
                         light_emitters.emitter_spec_to_struct(spec))]})

# lines ~218-219, in test_emitter_gate_is_per_ship_so_a_near_ship_is_unaffected:
        {1: [(_Sub(near_prop), False, False, 0.0, near_spec,
              light_emitters.emitter_spec_to_struct(near_spec))],
         2: [(_Sub(far_prop), False, False, 0.0, far_spec,
              light_emitters.emitter_spec_to_struct(far_spec))]})
```

Its `_Ship.GetWorldRotation` may stay as is (an unused getter is harmless); the file already imports `light_emitters`.

- [ ] **Step 5: Confirm the world-transform helpers still have callers**

Run: `grep -n "_world_from_body\|_rotate_body" engine/host_loop.py engine/ui/*.py`
Expected: at least one non-definition caller remains for each (they predate this feature). If a helper has NO remaining caller, delete it and its definition in this commit; do not leave dead code.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/test_host_loop_emitter_lights.py tests/unit/test_dynamic_light_render_marshal.py tests/unit/test_dynamic_light_camera_fade.py
git commit -m "fix(emitters): emit body-frame lights tagged with instance_id

The producer built world positions from the LIVE 60 Hz sim pose while the
hull rendered interpolated, so cast light jittered against the hull on
high-refresh displays. Lights now leave Python body-frame and the renderer
resolves them through the hull's own matrix. No transforms per frame.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Gate, docs, and live-verification handoff

**Files:**
- Modify: `docs/superpowers/specs/2026-09-16-instance-attached-emitter-lights-design.md` (status line)
- Modify: `CLAUDE.md` (one row in the key-reference table)

- [ ] **Step 1: Run the full gate**

Run: `scripts/check_tests.sh 2>&1 | tail -30`
Expected: exit 0; the only pytest failure is the baselined `test_engineer_emitters.py::test_shield_level_change_announces` (check `cat tests/known_failures.txt`); zero ctest failures. Any other failure is a regression from Tasks 1-4 — fix it before continuing, do not add it to the ledger.

- [ ] **Step 2: Update the spec status**

Change the spec's `**Status:**` line to `implemented 2026-09-16 (gate green); awaiting live verification on a 144 Hz display`.

- [ ] **Step 3: Add the CLAUDE.md pointer row**

Add to the key-reference table in `CLAUDE.md`, after the "Shield face + impact splash" row:

```
| Ship-attached dynamic lights — resolved in C++ | `native/src/renderer/dynamic_lights.cc:resolve_attached_dynamic_lights`, `host_loop.py:_build_emitter_light_render_data`, `docs/superpowers/specs/2026-09-16-instance-attached-emitter-lights-design.md` | Subsystem emitter lights leave Python **body-frame** with an `instance_id` and are resolved through the hull's own `inst->world` in `frame()` right after the transform-store sweep, so light and hull share one pose per frame (the particle-emitter pattern). ⚠️ Do NOT rebuild world positions in Python from `GetWorldLocation/Rotation` — that is the live 60 Hz pose, and the hull renders interpolated; the mismatch is a visible jitter at 144 Hz. ⚠️ Do NOT resolve at `set_dynamic_lights` time — that reads last frame's matrices (`tests/host/test_attached_lights_resolve_ordering.py` guards both). Emitter offsets are unscaled GU: world = `t + R·p`, scale divided out. Torpedo/explosion lights stay world-space. |
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-09-16-instance-attached-emitter-lights-design.md CLAUDE.md
git commit -m "docs: instance-attached emitter lights — status + CLAUDE.md pointer

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Hand off for live verification**

Report to Mark: build `cmake --build build -j`, run `./build/dauntless`, and on the 144 Hz display check (a) an AI ship's nacelle/impulse cast light is locked to its hull with no step-jitter, (b) the same during a waypoint-driven player cutscene, (c) the manually flown player's cast light still tracks the hull, (d) SPV → edit an emitter → Save still refreshes the light live. Do NOT launch the game from the agent session.
