# Warp-Core Breach Shockwave Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the warp-core breach's `ExplosionA` puff fireball with a procedural blue-white shockwave (camera-facing flat ring + white-hot core flash) whose ring expands to the breach damage radius, and raise that damage radius to 4.0 GU so damage matches the visual.

**Architecture:** A Python `shockwaves` registry (mirroring `hit_vfx`) is spawned by `warp_core_breach.detonate`, aged each tick, and pushed to the renderer via a new `host.set_shockwaves(...)` binding. A new GLSL pass (`ShockwavePass`, modeled on `dust_pass`/`subsystem_pin_pass`) draws one camera-facing billboard quad per shockwave; the fragment shader animates the ring and flash from a normalized-age uniform. No new art assets.

**Tech Stack:** Python 3 (engine), C++/OpenGL + GLSL (native renderer), pybind11, CMake, pytest.

## Global Constraints

Copied verbatim from the spec — every task's requirements implicitly include these:

- **Engine layer is modern Python 3.** Run Python tests with `uv run pytest <path> -v`.
- **Single source of truth for the radius:** `warp_core_breach.BREACH_RADIUS_GU` is **4.0** (raised from 1.3). It feeds BOTH the AoE damage falloff/`apply_hit(splash_radius=...)` AND the shockwave ring max radius. There is **no** separate visual-radius constant.
- `shockwaves.SHOCKWAVE_LIFETIME = 0.7` (seconds).
- Breach **damage magnitude and chain logic are unchanged**; only the radius grows.
- VFX must be raise-safe: `shockwaves.spawn` is called from the raise-safe section of `detonate`; `host.set_shockwaves` is `hasattr`-guarded.
- **Render main view only** (`if (!for_viewscreen ...)`), matching `dust_pass`.
- **Build:** new shaders + new source require a **cmake reconfigure** (`cmake -B build -S .`), THEN `cmake --build build -j`. The single build tree is `build/`; the binary is `build/dauntless`. Never build from inside `native/`.
- `host_bindings.cc` changes require rebuilding the `dauntless` target.

**Spec:** `docs/superpowers/specs/2026-06-20-warp-core-breach-shockwave-design.md`

---

### Task 1: Python `shockwaves` registry

**Files:**
- Create: `engine/appc/shockwaves.py`
- Test: `tests/unit/test_shockwaves.py` (create)

**Interfaces:**
- Produces: `shockwaves.SHOCKWAVE_LIFETIME = 0.7`; `shockwaves.spawn(center_world, max_radius_gu, lifetime)`; `shockwaves.advance(dt)`; `shockwaves.render_data() -> list[tuple]` where each tuple is `((cx, cy, cz), max_radius, age, lifetime)`; `shockwaves.reset()`.
- `center_world` is any object with `.x/.y/.z` (a `TGPoint3`) OR a 3-tuple; store the three floats.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_shockwaves.py`:

```python
"""Tests for the warp-core breach shockwave registry (engine/appc/shockwaves.py)."""
import pytest

from engine.appc import shockwaves
from engine.appc.math import TGPoint3


@pytest.fixture(autouse=True)
def _clean():
    shockwaves.reset()
    yield
    shockwaves.reset()


def test_spawn_then_render_data_has_one_entry_at_age_zero():
    shockwaves.spawn(TGPoint3(1.0, 2.0, 3.0), 4.0, 0.7)
    data = shockwaves.render_data()
    assert len(data) == 1
    center, max_radius, age, lifetime = data[0]
    assert center == (1.0, 2.0, 3.0)
    assert max_radius == 4.0
    assert age == 0.0
    assert lifetime == 0.7


def test_spawn_accepts_a_tuple_center():
    shockwaves.spawn((5.0, 6.0, 7.0), 4.0, 0.7)
    assert shockwaves.render_data()[0][0] == (5.0, 6.0, 7.0)


def test_advance_increments_age():
    shockwaves.spawn(TGPoint3(0, 0, 0), 4.0, 0.7)
    shockwaves.advance(0.1)
    assert shockwaves.render_data()[0][2] == pytest.approx(0.1)


def test_descriptor_dropped_when_age_reaches_lifetime():
    shockwaves.spawn(TGPoint3(0, 0, 0), 4.0, 0.7)
    shockwaves.advance(0.7)            # age >= lifetime -> pruned
    assert shockwaves.render_data() == []


def test_descriptor_survives_just_under_lifetime():
    shockwaves.spawn(TGPoint3(0, 0, 0), 4.0, 0.7)
    shockwaves.advance(0.69)
    assert len(shockwaves.render_data()) == 1


def test_reset_clears_registry():
    shockwaves.spawn(TGPoint3(0, 0, 0), 4.0, 0.7)
    shockwaves.reset()
    assert shockwaves.render_data() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_shockwaves.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.appc.shockwaves'`.

- [ ] **Step 3: Write the module**

Create `engine/appc/shockwaves.py`:

```python
# engine/appc/shockwaves.py
"""Warp-core breach shockwave registry.

A transient, age-driven world-VFX registry mirroring engine/appc/hit_vfx.py.
warp_core_breach.detonate spawns one shockwave at the warp core's world
position; host_loop ages the registry each tick and pushes render_data() to the
renderer via host.set_shockwaves(...). The native ShockwavePass draws a
camera-facing ring + core flash whose size/animation derive from (max_radius,
age, lifetime).

See docs/superpowers/specs/2026-06-20-warp-core-breach-shockwave-design.md.
"""

SHOCKWAVE_LIFETIME = 0.7   # seconds — total ring/flash lifetime

_active: list[dict] = []


def _center_xyz(center):
    """Accept a TGPoint3-like (.x/.y/.z) or a 3-tuple; return (x, y, z) floats."""
    if hasattr(center, "x"):
        return (float(center.x), float(center.y), float(center.z))
    return (float(center[0]), float(center[1]), float(center[2]))


def spawn(center_world, max_radius_gu, lifetime) -> None:
    """Register a shockwave centered at `center_world` (world space) that
    expands to `max_radius_gu` over `lifetime` seconds."""
    _active.append({
        "center": _center_xyz(center_world),
        "max_radius": float(max_radius_gu),
        "age": 0.0,
        "lifetime": float(lifetime),
    })


def advance(dt: float) -> None:
    """Age every shockwave by dt; drop those that have reached their lifetime."""
    dt = float(dt)
    survivors = []
    for entry in _active:
        new_age = entry["age"] + dt
        if new_age < entry["lifetime"]:
            entry["age"] = new_age
            survivors.append(entry)
    _active[:] = survivors


def render_data() -> list:
    """Return [((cx, cy, cz), max_radius, age, lifetime), ...] for the host."""
    return [
        (entry["center"], entry["max_radius"], entry["age"], entry["lifetime"])
        for entry in _active
    ]


def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""
    _active.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_shockwaves.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/shockwaves.py tests/unit/test_shockwaves.py
git commit -m "feat(vfx): warp-core breach shockwave registry

Transient age-driven registry (spawn/advance/render_data/reset) mirroring
hit_vfx; feeds the native shockwave pass.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Bump breach radius to 4.0 GU and spawn the shockwave

**Files:**
- Modify: `engine/appc/warp_core_breach.py` (`BREACH_RADIUS_GU` line 18; `detonate` line 64; delete `_spawn_fireball` ~line 114)
- Test: `tests/unit/test_warp_core_breach.py` (add asserts)

**Interfaces:**
- Consumes: `shockwaves.spawn(center, max_radius, lifetime)` and `shockwaves.SHOCKWAVE_LIFETIME` (Task 1).
- Produces: `warp_core_breach.BREACH_RADIUS_GU == 4.0`; `detonate` spawns exactly one shockwave at the core center with `max_radius == BREACH_RADIUS_GU` and no longer calls `_spawn_fireball` (which is removed).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_warp_core_breach.py` (it already imports `warp_core_breach` and has the `_Core`/`_Ship` fakes + `_patch_ships`/`_clean` from earlier tasks — reuse them):

```python
def test_breach_radius_is_four_gu():
    # Single source of truth for damage AoE and the visual ring.
    assert warp_core_breach.BREACH_RADIUS_GU == 4.0


def test_detonate_spawns_one_shockwave_at_core_center(monkeypatch):
    from engine.appc import shockwaves
    spawned = []
    monkeypatch.setattr(shockwaves, "spawn",
                        lambda center, max_radius, lifetime:
                        spawned.append((center, max_radius, lifetime)))
    # No neighbours needed; we only assert the shockwave spawn.
    import engine.appc.ship_iter as ship_iter
    src = _Ship("Doomed", TGPoint3(2.0, 0.0, 0.0), core=_Core(5000.0))
    monkeypatch.setattr(ship_iter, "iter_ships", lambda *a, **k: [src])

    warp_core_breach.detonate(src)

    assert len(spawned) == 1
    center, max_radius, lifetime = spawned[0]
    # Core is at body origin on a ship at (2,0,0) with identity rotation, so the
    # world center is the ship location.
    assert (round(center.x, 5), round(center.y, 5), round(center.z, 5)) == (2.0, 0.0, 0.0)
    assert max_radius == warp_core_breach.BREACH_RADIUS_GU
    assert lifetime == shockwaves.SHOCKWAVE_LIFETIME


def test_detonate_no_longer_has_spawn_fireball():
    assert not hasattr(warp_core_breach, "_spawn_fireball")
```

(Note: `shockwaves.spawn` receives the `centre` object built inside `detonate`, which is a `TGPoint3`, so `center.x/.y/.z` are valid in the assertion above.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_warp_core_breach.py -k "radius_is_four or spawns_one_shockwave or no_longer_has_spawn_fireball" -v`
Expected: FAIL — `BREACH_RADIUS_GU` is still 1.3, `detonate` still calls `_spawn_fireball`, and `_spawn_fireball` still exists.

- [ ] **Step 3: Change the radius constant**

In `engine/appc/warp_core_breach.py`, change line 18 from:

```python
BREACH_RADIUS_GU       = 1.3   # 10x photon torpedo DRF (0.13 GU)
```

to:

```python
BREACH_RADIUS_GU       = 4.0   # shared AoE damage radius AND shockwave ring max
                               # radius; tuned to the dramatic visual (was 1.3)
```

- [ ] **Step 4: Swap the fireball for a shockwave in `detonate`**

In `engine/appc/warp_core_breach.py` `detonate`, replace the line (currently line 64):

```python
    _spawn_fireball(ship, core)
```

with:

```python
    try:
        from engine.appc import shockwaves
        shockwaves.spawn(centre, BREACH_RADIUS_GU, shockwaves.SHOCKWAVE_LIFETIME)
    except Exception as _e:
        dev_mode.log_swallowed("spawn warp core shockwave", _e)
```

(`centre` is the warp core world position already computed two lines above; `dev_mode` is already imported at the top of the module.)

- [ ] **Step 5: Delete `_spawn_fireball`**

In `engine/appc/warp_core_breach.py`, delete the entire `_spawn_fireball(ship, core)` function (the `def _spawn_fireball(...)` block, ~lines 114–138, including its docstring and the `import Effects` body). Nothing else references it after Step 4.

- [ ] **Step 6: Run the new tests AND the full breach suite to confirm no regression**

Run: `uv run pytest tests/unit/test_warp_core_breach.py tests/unit/test_warp_core_breach_integration.py -v`
Expected: all PASS — the new three pass, and the existing AoE tests (`test_damage_scales_with_core_and_falls_off_with_distance`, `test_ship_outside_radius_untouched`, the chain/single-fire tests) still pass at the 4.0 radius (they assert against `BREACH_RADIUS_GU` / use distances valid at both radii: `near` at d=0.5 → weight clamps to 1.0; `far` at d=10 → still outside 4.0).

- [ ] **Step 7: Commit**

```bash
git add engine/appc/warp_core_breach.py tests/unit/test_warp_core_breach.py
git commit -m "feat(vfx): breach radius 4.0 GU + spawn shockwave instead of puffs

BREACH_RADIUS_GU 1.3 -> 4.0 (single source for damage AoE and ring max);
detonate spawns a shockwave at the core center; _spawn_fireball removed.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Host-loop wiring (advance + push + reset)

**Files:**
- Modify: `engine/host_loop.py` (combat hub near `hit_vfx.update_ages(dt)`; frame build near `host.set_torpedoes(...)`; reset block near `ship_death.reset()`)
- Verify: grep + `py_compile`

**Interfaces:**
- Consumes: `shockwaves.advance(dt)`, `shockwaves.render_data()`, `shockwaves.reset()` (Task 1).
- Produces: nothing new — wiring that ages the registry each tick, pushes it to the renderer, and clears it on mission swap.

- [ ] **Step 1: Find the three wiring sites**

Run:
```bash
grep -n "hit_vfx.update_ages\|set_torpedoes\|warp_core_breach.reset\|shockwaves" engine/host_loop.py
```
Expected: a `hit_vfx.update_ages(dt)` call in the combat hub, a `host.set_torpedoes(...)` push in the frame build, and `warp_core_breach.reset()` in the reset block. (No existing `shockwaves` references.)

- [ ] **Step 2: Advance the registry each tick**

In `engine/host_loop.py`, immediately after the `hit_vfx.update_ages(dt)` line, add:

```python
    from engine.appc import shockwaves
    shockwaves.advance(dt)
```

- [ ] **Step 3: Push the render data to the host**

In `engine/host_loop.py`, immediately after the existing `host.set_torpedoes(...)` push (in the frame-build section that talks to `host`), add:

```python
    from engine.appc import shockwaves as _shockwaves
    if hasattr(host, "set_shockwaves"):
        host.set_shockwaves(_shockwaves.render_data())
```

(Use the alias `_shockwaves` here to avoid shadowing if the surrounding scope differs from Step 2's; both import the same module.)

- [ ] **Step 4: Reset on mission swap**

In `engine/host_loop.py`, immediately after the `warp_core_breach.reset()` line in the reset block, add:

```python
        from engine.appc import shockwaves
        shockwaves.reset()
```

- [ ] **Step 5: Verify wiring present and the module still compiles**

Run:
```bash
grep -n "shockwaves.advance\|set_shockwaves\|shockwaves.reset" engine/host_loop.py
uv run python -m py_compile engine/host_loop.py && echo "SYNTAX OK"
```
Expected: three grep hits (advance, push, reset) and `SYNTAX OK`. (`import engine.host_loop` fails headless on the native `_dauntless_host` module — that is pre-existing and unrelated; `py_compile` is the correct check here.)

- [ ] **Step 6: Confirm the registry tests still pass (the wired functions)**

Run: `uv run pytest tests/unit/test_shockwaves.py -v`
Expected: PASS (unchanged — this step just confirms the wired API is intact).

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(vfx): pump breach shockwave registry each tick

Advance shockwaves beside hit_vfx, push render_data via host.set_shockwaves
(hasattr-guarded), reset beside the other VFX registries on mission swap.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Native descriptor + `set_shockwaves` binding

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h` (add `ShockwaveDescriptor` near `TorpedoDescriptor`, line 79)
- Modify: `native/src/host/host_bindings.cc` (global near line 129; `set_shockwaves` binding near the `set_torpedoes` binding at line 1500; clear in `shutdown` near line 361)
- Verify: build

**Interfaces:**
- Produces: `renderer::ShockwaveDescriptor { glm::vec3 world_center; float max_radius; float age; float lifetime; }`; a global `std::vector<renderer::ShockwaveDescriptor> g_shockwaves;`; a `set_shockwaves` pybind binding accepting `[((cx,cy,cz), max_radius, age, lifetime), ...]`.
- Consumed by Task 5's render call.

- [ ] **Step 1: Add the descriptor struct**

In `native/src/renderer/include/renderer/frame.h`, immediately after the `struct TorpedoDescriptor { ... };` block (starts line 79), add:

```cpp
// One warp-core breach shockwave: a camera-facing ring + core flash centered
// at world_center, expanding to max_radius over lifetime. age/lifetime drive
// the shader animation (same age-based shape as TorpedoDescriptor).
struct ShockwaveDescriptor {
    glm::vec3 world_center;
    float max_radius;
    float age;
    float lifetime;
};
```

- [ ] **Step 2: Add the global and clear it in shutdown**

In `native/src/host/host_bindings.cc`, immediately after the `std::vector<renderer::TorpedoDescriptor> g_torpedoes;` line (129), add:

```cpp
std::vector<renderer::ShockwaveDescriptor> g_shockwaves;
```

Then in `shutdown()`, immediately after the `g_torpedoes.clear();` line (361), add:

```cpp
    g_shockwaves.clear();
```

- [ ] **Step 3: Add the `set_shockwaves` binding**

In `native/src/host/host_bindings.cc`, read the existing `set_torpedoes` binding (lines 1500–1529) to match its parameter-conversion idiom, then add this binding immediately after it:

```cpp
    m.def("set_shockwaves",
          [](const std::vector<std::tuple<std::tuple<float, float, float>,
                                          float, float, float>>& descs) {
              g_shockwaves.clear();
              g_shockwaves.reserve(descs.size());
              for (const auto& d : descs) {
                  const auto& c = std::get<0>(d);
                  renderer::ShockwaveDescriptor s;
                  s.world_center = glm::vec3(std::get<0>(c), std::get<1>(c),
                                             std::get<2>(c));
                  s.max_radius = std::get<1>(d);
                  s.age        = std::get<2>(d);
                  s.lifetime   = std::get<3>(d);
                  g_shockwaves.push_back(s);
              }
          },
          py::arg("shockwaves"),
          "Replace the active warp-core breach shockwaves: a list of "
          "((cx,cy,cz), max_radius, age, lifetime).");
```

If `set_torpedoes` uses a different conversion style (e.g. `py::list` + manual `.cast<>()` instead of `std::vector<std::tuple<...>>`), mirror THAT style instead, substituting the four `ShockwaveDescriptor` fields — the goal is to match the file's established idiom so pybind's STL casters are configured the same way.

- [ ] **Step 4: Reconfigure and build**

Run:
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: configures and compiles cleanly with no errors referencing `ShockwaveDescriptor`, `g_shockwaves`, or `set_shockwaves`.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h native/src/host/host_bindings.cc
git commit -m "feat(renderer): ShockwaveDescriptor + set_shockwaves binding

Data plumbing for the breach shockwave: descriptor struct, g_shockwaves global,
set_shockwaves pybind binding (mirrors set_torpedoes), cleared on shutdown.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Native `ShockwavePass` + shaders + render wiring

**Files:**
- Create: `native/src/renderer/include/renderer/shockwave_pass.h`
- Create: `native/src/renderer/shockwave_pass.cc`
- Create: `native/src/renderer/shaders/shockwave.vert`, `native/src/renderer/shaders/shockwave.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (embed_shader + add `shockwave_pass.cc` to the renderer sources)
- Modify: `native/src/renderer/include/renderer/pipeline.h` (accessor + member), `native/src/renderer/pipeline.cc` (include + construct)
- Modify: `native/src/host/host_bindings.cc` (global pass ptr + init/shutdown + `frame()` render call)
- Verify: build; then USER visual verification in-app

**Interfaces:**
- Consumes: `renderer::ShockwaveDescriptor` / `g_shockwaves` (Task 4); `Pipeline::shockwave_shader()`.
- Produces: `renderer::ShockwavePass` with `void render(const scenegraph::Camera& cam, const std::vector<ShockwaveDescriptor>& shockwaves, Pipeline& pipeline);`

- [ ] **Step 1: Write the shaders**

Create `native/src/renderer/shaders/shockwave.vert`:

```glsl
#version 330 core
layout(location = 0) in vec2 a_corner;   // unit quad corners in [-1, 1]

uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_center;       // world-space blast center
uniform float u_max_radius;   // ring max radius (world units)

out vec2 v_uv;                // == a_corner; radial coord in [-1, 1]

void main() {
    // World-space camera right/up are the first two columns of the view
    // matrix's rotation (view maps world->camera; its transpose's columns are
    // world axes). Same billboard basis used by subsystem_pin / dust.
    vec3 cam_right = vec3(u_view[0][0], u_view[1][0], u_view[2][0]);
    vec3 cam_up    = vec3(u_view[0][1], u_view[1][1], u_view[2][1]);
    vec3 world = u_center
               + a_corner.x * cam_right * u_max_radius
               + a_corner.y * cam_up    * u_max_radius;
    v_uv = a_corner;
    gl_Position = u_proj * u_view * vec4(world, 1.0);
}
```

Create `native/src/renderer/shaders/shockwave.frag`:

```glsl
#version 330 core
in vec2 v_uv;                 // radial coord; length 0 at center, ~1 at edge
uniform float u_t;            // age / lifetime, 0..1
out vec4 frag;

const float kBand      = 0.10; // ring band half-width (normalized radius)
const float kFlashFrac = 0.20; // core flash lives while t < kFlashFrac
const float kFlashSize = 0.18; // core flash radius (normalized)

void main() {
    float r = length(v_uv);
    float t = clamp(u_t, 0.0, 1.0);

    // Ring expands with ease-out (fast then decelerating): 0 -> 1.
    float ring_r = 1.0 - (1.0 - t) * (1.0 - t);
    // Thin bright band centered on the current ring radius, soft edges.
    float band = 1.0 - smoothstep(0.0, kBand, abs(r - ring_r));
    float ring_alpha = band * (1.0 - t);          // fade as it ages

    // Core flash: bright center, only early, gone by kFlashFrac.
    float flash_life = 1.0 - smoothstep(0.0, kFlashFrac, t);
    float flash = (1.0 - smoothstep(0.0, kFlashSize, r)) * flash_life;

    // White-hot core/flash; ring cools white-blue -> blue as it grows.
    vec3 ring_col  = mix(vec3(0.70, 0.90, 1.0), vec3(0.30, 0.60, 1.0), t);
    vec3 flash_col = vec3(1.0, 1.0, 1.0);

    vec3 col = ring_col * ring_alpha + flash_col * flash;
    float a  = clamp(ring_alpha + flash, 0.0, 1.0);
    if (a <= 0.002) discard;
    frag = vec4(col, a);
}
```

- [ ] **Step 2: Embed the shaders + add the source in CMake**

In `native/src/renderer/CMakeLists.txt`, add after the dust `embed_shader` lines (24):

```cmake
embed_shader(SHADER_SHOCKWAVE_VS shaders/shockwave.vert shockwave_vs)
embed_shader(SHADER_SHOCKWAVE_FS shaders/shockwave.frag shockwave_fs)
```

Then find where the renderer library lists its `.cc` sources (the same list that contains `dust_pass.cc`) and add `shockwave_pass.cc` to it. Also wherever the `SHADER_*` variables are aggregated into the target (the list that includes `SHADER_DUST_VS`/`SHADER_DUST_FS`), add `SHADER_SHOCKWAVE_VS` and `SHADER_SHOCKWAVE_FS`. (Search the file: `grep -n "dust_pass.cc\|SHADER_DUST_VS" native/src/renderer/CMakeLists.txt` to locate both lists.)

- [ ] **Step 3: Add the pipeline shader accessor**

In `native/src/renderer/include/renderer/pipeline.h`, after the `Shader& dust_shader()...` line (19) add:

```cpp
    Shader& shockwave_shader() noexcept { return *shockwave_; }
```

and after the `std::unique_ptr<Shader> dust_;` member (41) add:

```cpp
    std::unique_ptr<Shader> shockwave_;
```

In `native/src/renderer/pipeline.cc`, after the `#include "embedded_dust_vs.h"` / `..._fs.h` includes (15–16) add:

```cpp
#include "embedded_shockwave_vs.h"
#include "embedded_shockwave_fs.h"
```

and where `dust_` is constructed (`dust_ = std::make_unique<Shader>(shader_src::dust_vs, shader_src::dust_fs);`) add immediately after:

```cpp
    shockwave_ = std::make_unique<Shader>(shader_src::shockwave_vs,
                                          shader_src::shockwave_fs);
```

- [ ] **Step 4: Write the pass header**

Create `native/src/renderer/include/renderer/shockwave_pass.h`:

```cpp
#pragma once

#include <renderer/frame.h>

#include <vector>

namespace scenegraph { class Camera; }

namespace renderer {

class Pipeline;

// Draws warp-core breach shockwaves: one additive, camera-facing billboard
// quad per descriptor; the fragment shader animates a ring + core flash from
// the descriptor's normalized age. Modeled on subsystem_pin_pass (quad) with
// dust_pass additive/depth state.
class ShockwavePass {
public:
    ShockwavePass() = default;
    ~ShockwavePass();

    ShockwavePass(const ShockwavePass&) = delete;
    ShockwavePass& operator=(const ShockwavePass&) = delete;

    void render(const scenegraph::Camera& cam,
                const std::vector<ShockwaveDescriptor>& shockwaves,
                Pipeline& pipeline);

private:
    void initialize_gl();

    bool initialized_ = false;
    unsigned int vao_ = 0;
    unsigned int vbo_ = 0;
};

}  // namespace renderer
```

- [ ] **Step 5: Write the pass implementation**

Create `native/src/renderer/shockwave_pass.cc`. Model the VAO/VBO setup and the `Shader::use`/`set_mat4`/`set_vec3`/`set_float` calls on `native/src/renderer/subsystem_pin_pass.cc` (the simplest quad pass) — read it first to match the exact `Shader` and `Camera` accessor names (`pipeline.shockwave_shader()`, `cam.view()`, `cam.projection()` or the equivalents that file uses). The structure:

```cpp
// native/src/renderer/shockwave_pass.cc
#include "renderer/shockwave_pass.h"

#include "renderer/pipeline.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>

namespace renderer {

ShockwavePass::~ShockwavePass() {
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void ShockwavePass::initialize_gl() {
    // Unit quad in [-1, 1], two triangles, one vec2 attribute (location 0).
    static const float kQuad[] = {
        -1.0f, -1.0f,   1.0f, -1.0f,   1.0f, 1.0f,
        -1.0f, -1.0f,   1.0f,  1.0f,  -1.0f, 1.0f,
    };
    glGenVertexArrays(1, &vao_);
    glGenBuffers(1, &vbo_);
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(kQuad), kQuad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindVertexArray(0);
    initialized_ = true;
}

void ShockwavePass::render(const scenegraph::Camera& cam,
                           const std::vector<ShockwaveDescriptor>& shockwaves,
                           Pipeline& pipeline) {
    if (shockwaves.empty()) return;
    if (!initialized_) initialize_gl();

    // Additive, camera-facing, depth-tested but not depth-writing (dust state).
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    glDepthFunc(GL_LEQUAL);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    Shader& sh = pipeline.shockwave_shader();
    sh.use();
    // Match the matrix accessor names used by subsystem_pin_pass.cc.
    sh.set_mat4("u_view", cam.view());
    sh.set_mat4("u_proj", cam.projection());

    glBindVertexArray(vao_);
    for (const auto& s : shockwaves) {
        const float t = (s.lifetime > 0.0f) ? (s.age / s.lifetime) : 1.0f;
        sh.set_vec3("u_center", s.world_center);
        sh.set_float("u_max_radius", s.max_radius);
        sh.set_float("u_t", t);
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }
    glBindVertexArray(0);

    // Restore default state (dust_pass restore block).
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glDisable(GL_BLEND);
}

}  // namespace renderer
```

If `subsystem_pin_pass.cc` uses different `Shader` setter names (e.g. `setMat4`/`setFloat`) or different `Camera` accessors (e.g. `cam.view_matrix()`), use those exact names instead — the names above are the expected idiom but the template file is authoritative.

- [ ] **Step 6: Wire the pass into the host**

In `native/src/host/host_bindings.cc`:

1. Add the include near the other pass includes (e.g. after `#include <renderer/hit_vfx_pass.h>`, line 32):
   ```cpp
   #include <renderer/shockwave_pass.h>
   ```
2. Add the global near `g_dust_pass` (125):
   ```cpp
   std::unique_ptr<renderer::ShockwavePass> g_shockwave_pass;
   ```
3. In `init()`, after `g_dust_pass = std::make_unique<renderer::DustPass>();` (308):
   ```cpp
   g_shockwave_pass = std::make_unique<renderer::ShockwavePass>();
   ```
4. In `shutdown()`, after `g_dust_pass.reset();` (357):
   ```cpp
   g_shockwave_pass.reset();
   ```
5. In the `render_space` lambda in `frame()`, immediately after the hit-VFX render line (489, `if (g_hit_vfx_pass) g_hit_vfx_pass->render(...)`) add:
   ```cpp
           if (!for_viewscreen && g_shockwave_pass)
               g_shockwave_pass->render(cam, g_shockwaves, *g_pipeline);
   ```

- [ ] **Step 7: Reconfigure, build, and confirm it compiles**

Run:
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: configures (picking up the new shaders + `shockwave_pass.cc`) and links cleanly. The `build/dauntless` binary and `_dauntless_host` module rebuild.

- [ ] **Step 8: Run the Python suites that touch this path**

Run: `uv run pytest tests/unit/test_shockwaves.py tests/unit/test_warp_core_breach.py tests/unit/test_warp_core_breach_integration.py -v`
Expected: all PASS (native changes don't affect the headless Python tests; this confirms nothing regressed).

- [ ] **Step 9: USER visual verification**

This pass has no headless GL test (consistent with `dust_pass` and the other passes). Hand off to the user (Mark) to launch `./build/dauntless`, trigger a warp-core breach, and confirm the blue-white ring + white-hot flash appears and expands. Note tunables for feel: `kBand`/`kFlashFrac`/`kFlashSize`/colors in `shockwave.frag`, `SHOCKWAVE_LIFETIME` in `shockwaves.py`, `BREACH_RADIUS_GU` in `warp_core_breach.py`.

- [ ] **Step 10: Commit**

```bash
git add native/src/renderer/include/renderer/shockwave_pass.h native/src/renderer/shockwave_pass.cc \
        native/src/renderer/shaders/shockwave.vert native/src/renderer/shaders/shockwave.frag \
        native/src/renderer/CMakeLists.txt \
        native/src/renderer/include/renderer/pipeline.h native/src/renderer/pipeline.cc \
        native/src/host/host_bindings.cc
git commit -m "feat(renderer): procedural warp-core breach shockwave pass

Camera-facing billboard quad per shockwave; fragment shader animates a
blue-white expanding ring + white-hot core flash from normalized age. Additive,
depth-tested no-write, main view only. Replaces the ExplosionA puff fireball.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- Python `shockwaves` registry (spawn/advance/render_data/reset, SHOCKWAVE_LIFETIME) → Task 1. ✓
- `detonate` spawns shockwave, `_spawn_fireball` removed → Task 2. ✓
- `BREACH_RADIUS_GU` 1.3 → 4.0, single source for damage + ring → Task 2 (constant + spawn uses it). ✓
- host_loop advance + `set_shockwaves` push (hasattr-guarded) + reset → Task 3. ✓
- `ShockwaveDescriptor` + `set_shockwaves` binding → Task 4. ✓
- `ShockwavePass` + shaders (ring ease-out + core flash + blue-white) + pipeline accessor + CMake embed + main-view-only render call → Task 5. ✓
- Additive / depth-test-no-write / camera-facing → Task 5 render state + vertex billboard. ✓
- Raise-safe spawn + hasattr-guarded push → Task 2 (try/except) + Task 3 (hasattr). ✓
- Build reconfigure called out → Global Constraints + Tasks 4/5 build steps. ✓
- Tests: registry unit tests + detonate-spawns-shockwave + radius-pin → Tasks 1, 2. Native = build + visual → Task 5. ✓

**2. Placeholder scan:** No TBD/TODO. Native steps that depend on the codebase's exact idiom (CMake source list location, `Shader`/`Camera` accessor names, `set_torpedoes` conversion style) name the authoritative template file and the grep to locate it, with concrete best-idiom code — not vague "wire it up" instructions. ✓

**3. Type consistency:** `SHOCKWAVE_LIFETIME`, `BREACH_RADIUS_GU`, `shockwaves.spawn(center, max_radius, lifetime)`, `render_data()` tuple shape `((cx,cy,cz), max_radius, age, lifetime)`, `set_shockwaves`, `ShockwaveDescriptor{world_center,max_radius,age,lifetime}`, and the shader uniforms `u_view/u_proj/u_center/u_max_radius/u_t` are named identically across the Python registry (Task 1), the binding (Task 4), the descriptor (Task 4), and the pass/shaders (Task 5). The render-data tuple consumed by the binding matches the tuple produced by `render_data`. ✓
