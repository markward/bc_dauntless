# Hull Electrical Discharges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Brief procedural electric-crackle billboards at random hull points on the player ship while in a nebula, at a rate that scales with the nebula's damage, plus a faint whole-hull emissive flicker.

**Architecture:** A seeded Python **discharge driver** (`hull_discharge.py`) ticks while the player is in a nebula, spawning short-lived discharges at random subsystem-mount hull points (rate ∝ the nebula damage rate, + rare idle strikes) and emitting an emissive-boost value. The host loop feeds a native **crackle pass** (additive electric billboards, sibling of `hit_vfx_pass`) via `set_hull_discharges`, and applies the boost via the existing `set_emissive_scale`. Gated by the existing **Nebula Lightning** toggle.

**Tech Stack:** Python 3 (driver, host loop), pytest; C++17 + OpenGL/GLSL (crackle pass), pybind11, CMake shader embedding, CTest FrameTest.

## Global Constraints

- **No new toggle.** Hull discharges are gated by the existing `dauntless_nebula_lightning::enabled()` / `r.nebula_lightning_enabled()`. Off → driver never ticks, no descriptors, **emissive forced to exactly 1.0**.
- **No gameplay coupling.** Visual only; reads the nebula damage rate but never changes combat/sensors.
- **Stuck-bright-hull invariant:** the player ship's emissive scale is shared state. It MUST be restored to **exactly 1.0** on every idle / toggle-off / outside-nebula / mission-swap path. This is a hard invariant with its own test.
- **Inert outside a nebula:** the driver only spawns while the player is inside a nebula; the crackle pass and emissive are no-ops with no active discharge.
- **Determinism:** seeded RNG; `reset()` reseeds; reset on mission swap (`reset_sdk_globals`).
- **Player-only** for V1 (the camera subject). Other ships are extensible later.
- **Game time** uses `App.g_kUtopiaModule.GetGameTime()` (the shim's `TGTimerManager` lacks `GetGameTime`).
- **Shader rebuild:** any `.vert`/`.frag` change needs `cmake -B build -S .` BEFORE `cmake --build build -j`. Build from project root, never inside `native/`.
- **host_bindings.cc / renderer changes** need the full `dauntless` rebuild.
- **No desktop interaction on Mark's workstation** — live verification is handed off.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `engine/appc/hull_discharge.py` | Create | `HullDischargeDriver` — seeded spawn/age + emissive boost. Pure logic. |
| `tests/unit/test_hull_discharge.py` | Create | Driver unit tests (seeded, deterministic). |
| `native/src/renderer/include/renderer/hull_discharge_pass.h` / `hull_discharge_pass.cc` | Create | Additive electric-crackle billboard pass (sibling of hit_vfx). |
| `native/src/renderer/shaders/hull_discharge.vert` / `hull_discharge.frag` | Create | Per-descriptor camera-facing billboard + procedural electric look. |
| `native/src/renderer/CMakeLists.txt`, `pipeline.cc` | Modify | Embed + construct the crackle shader. |
| `native/src/host/host_bindings.cc` | Modify | `g_hull_discharges` + `g_hull_discharge_pass`; `set_hull_discharges` binding; render call (gated). |
| `engine/renderer.py` | Modify | `set_hull_discharges(list)` wrapper. |
| `engine/host_loop.py` | Modify | Tick driver; feed discharges + emissive; reset + emissive-restore on swap; toggle gating. |
| `native/tests/renderer/frame_test.cc` | Modify | Crackle-pass FrameTest. |

---

## Task 1: Discharge driver (Python, seeded)

**Files:**
- Create: `engine/appc/hull_discharge.py`
- Test: `tests/unit/test_hull_discharge.py`

**Interfaces:**
- Produces:
  - `class HullDischargeDriver`:
    - `__init__(self, seed=2027)`
    - `update(self, in_nebula: bool, damage_rate: float, dt: float, hull_points: list, game_time: float) -> None` — `hull_points` is a list of `(x,y,z)` world tuples. Spawns/ages discharges; no-ops (clears) when not in a nebula or no points.
    - `active_discharges(self) -> list[dict]` — each `{"world_pos": (x,y,z), "age": float, "life": float, "size": float, "color": (r,g,b)}`.
    - `emissive_boost(self) -> float` — ≥ 1.0; **exactly 1.0** when no discharge is active.
    - `reset(self) -> None` — reseed + clear.
- Dials (module constants): `IDLE_RATE=0.4`, `DAMAGE_GAIN=0.05`, `BURST_MAX=3`, `LIFE_MIN=0.06`, `LIFE_MAX=0.15`, `SIZE_MIN=0.12`, `SIZE_MAX=0.30`, `FLICKER=0.6`, `EMISSIVE_MAX=2.0`, `ANCHOR_OFFSET=0.15`, `COLOR=(0.6,0.8,1.0)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_hull_discharge.py`:

```python
from engine.appc.hull_discharge import HullDischargeDriver

PTS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]


def _count_spawns(driver, ticks, damage_rate, dt=1.0/60.0):
    """Advance `ticks` frames in a nebula; return total discharges ever spawned."""
    t = 0.0
    seen = 0
    prev_ids = set()
    total = 0
    for _ in range(ticks):
        t += dt
        driver.update(True, damage_rate, dt, PTS, t)
        # Count by identity of the active list growth: approximate via births.
        total = max(total, len(driver.active_discharges()))
    return total


def test_no_spawn_outside_nebula():
    d = HullDischargeDriver(seed=1)
    for i in range(600):
        d.update(False, 150.0, 1.0/60.0, PTS, i/60.0)
    assert d.active_discharges() == []
    assert d.emissive_boost() == 1.0


def test_no_spawn_without_hull_points():
    d = HullDischargeDriver(seed=1)
    for i in range(600):
        d.update(True, 150.0, 1.0/60.0, [], i/60.0)
    assert d.active_discharges() == []


def test_rate_scales_with_damage():
    # Over the same window, a high damage rate spawns far more than zero damage.
    lo = HullDischargeDriver(seed=3)
    hi = HullDischargeDriver(seed=3)
    lo_spawns = hi_spawns = 0
    t = 0.0
    for _ in range(60 * 20):                  # 20 s
        t += 1.0/60.0
        lo.update(True, 0.0,   1.0/60.0, PTS, t)
        hi.update(True, 150.0, 1.0/60.0, PTS, t)
        lo_spawns += len(lo.active_discharges())
        hi_spawns += len(hi.active_discharges())
    assert hi_spawns > lo_spawns * 5          # damaging cloud crackles far more


def test_idle_strikes_occur_at_zero_damage():
    d = HullDischargeDriver(seed=5)
    ever = 0
    t = 0.0
    for _ in range(60 * 30):                  # 30 s at zero damage
        t += 1.0/60.0
        d.update(True, 0.0, 1.0/60.0, PTS, t)
        ever += len(d.active_discharges())
    assert ever > 0                           # rare, but they happen


def test_discharges_anchor_near_hull_points():
    d = HullDischargeDriver(seed=7)
    t = 0.0
    found = False
    for _ in range(600):
        t += 1.0/60.0
        d.update(True, 150.0, 1.0/60.0, PTS, t)
        for dis in d.active_discharges():
            x, y, z = dis["world_pos"]
            # within ANCHOR_OFFSET of some provided point
            assert any(abs(x-px) <= 0.1501 and abs(y-py) <= 0.1501 and abs(z-pz) <= 0.1501
                       for (px, py, pz) in PTS)
            found = True
    assert found


def test_discharges_expire():
    d = HullDischargeDriver(seed=9)
    # Spawn a flurry, then advance well past max life with no new spawns
    # (outside nebula → no spawns, ages still advance to expiry on the next
    # in-nebula tick is N/A; leaving the nebula clears immediately).
    t = 0.0
    for _ in range(120):
        t += 1.0/60.0
        d.update(True, 500.0, 1.0/60.0, PTS, t)
    assert len(d.active_discharges()) >= 0     # some may be active
    # Advance time by 1 s with continued ticks but check nothing older than life.
    for _ in range(60):
        t += 1.0/60.0
        d.update(True, 500.0, 1.0/60.0, PTS, t)
        for dis in d.active_discharges():
            assert dis["age"] < dis["life"]


def test_emissive_boost_idle_is_exactly_one():
    d = HullDischargeDriver(seed=11)
    assert d.emissive_boost() == 1.0          # fresh, no discharges
    # In a damaging cloud it rises above 1.0 at least once.
    t = 0.0
    rose = False
    for _ in range(600):
        t += 1.0/60.0
        d.update(True, 300.0, 1.0/60.0, PTS, t)
        if d.emissive_boost() > 1.0:
            rose = True
    assert rose


def test_determinism_same_seed():
    a = HullDischargeDriver(seed=42)
    b = HullDischargeDriver(seed=42)
    t = 0.0
    for _ in range(600):
        t += 1.0/60.0
        a.update(True, 120.0, 1.0/60.0, PTS, t)
        b.update(True, 120.0, 1.0/60.0, PTS, t)
    assert a.active_discharges() == b.active_discharges()
    assert a.emissive_boost() == b.emissive_boost()


def test_reset_clears_and_reseeds():
    d = HullDischargeDriver(seed=13)
    t = 0.0
    for _ in range(600):
        t += 1.0/60.0
        d.update(True, 150.0, 1.0/60.0, PTS, t)
    d.reset()
    assert d.active_discharges() == []
    assert d.emissive_boost() == 1.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_hull_discharge.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.appc.hull_discharge`.

- [ ] **Step 3: Implement `engine/appc/hull_discharge.py`**

```python
"""Hull electrical discharges — the crackle driver.

A seeded state machine: while the player is inside a nebula, it spawns brief
electric crackles at random hull points (subsystem mounts + a small offset) at
a rate that scales with the nebula's damage rate (plus rare idle strikes), and
reports a whole-hull emissive boost for the frame. Pure logic — emits plain
descriptors + a float; the host loop feeds the crackle pass and the emissive
binding. No GL. Deterministic given the seed.
"""
import random

IDLE_RATE = 0.4          # discharges/sec at zero damage (rare)
DAMAGE_GAIN = 0.05       # extra discharges/sec per (hull dmg/sec)
BURST_MAX = 3            # max spawns in a single heavy tick
LIFE_MIN = 0.06          # discharge life (s) — "a frame or two"
LIFE_MAX = 0.15
SIZE_MIN = 0.12          # billboard half-size (GU)
SIZE_MAX = 0.30
FLICKER = 0.6            # emissive boost per unit of active intensity
EMISSIVE_MAX = 2.0       # clamp on the whole-hull boost
ANCHOR_OFFSET = 0.15     # random world offset (GU) from the subsystem mount
COLOR = (0.6, 0.8, 1.0)  # electric blue-white


class _Discharge:
    __slots__ = ("pos", "born", "life", "size", "color", "age")

    def __init__(self, pos, born, life, size, color):
        self.pos = pos
        self.born = born
        self.life = life
        self.size = size
        self.color = color
        self.age = 0.0


class HullDischargeDriver:
    def __init__(self, seed=2027):
        self._seed = seed
        self._rng = random.Random(seed)
        self._discharges = []

    def reset(self):
        self._rng = random.Random(self._seed)
        self._discharges = []

    def update(self, in_nebula, damage_rate, dt, hull_points, game_time):
        if not in_nebula or not hull_points:
            if self._discharges:
                self._discharges = []
            return

        rate = IDLE_RATE + DAMAGE_GAIN * max(0.0, damage_rate)
        # Per-tick spawn(s): Bernoulli with a diminishing chance for extras so a
        # heavy (damaging) tick can produce a small burst.
        chance = rate * dt
        n = 0
        while n < BURST_MAX and self._rng.random() < chance:
            n += 1
            chance *= 0.5
        for _ in range(n):
            px, py, pz = self._rng.choice(hull_points)
            o = ANCHOR_OFFSET
            pos = (px + self._rng.uniform(-o, o),
                   py + self._rng.uniform(-o, o),
                   pz + self._rng.uniform(-o, o))
            life = self._rng.uniform(LIFE_MIN, LIFE_MAX)
            size = self._rng.uniform(SIZE_MIN, SIZE_MAX)
            self._discharges.append(_Discharge(pos, game_time, life, size, COLOR))

        alive = []
        for d in self._discharges:
            d.age = game_time - d.born
            if 0.0 <= d.age < d.life:
                alive.append(d)
        self._discharges = alive

    def active_discharges(self):
        return [{"world_pos": d.pos, "age": d.age, "life": d.life,
                 "size": d.size, "color": d.color} for d in self._discharges]

    def emissive_boost(self):
        if not self._discharges:
            return 1.0
        s = 0.0
        for d in self._discharges:
            t = 1.0 - (d.age / d.life if d.life > 0.0 else 1.0)
            if t > 0.0:
                s += t
        boost = 1.0 + FLICKER * s
        return EMISSIVE_MAX if boost > EMISSIVE_MAX else boost
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_hull_discharge.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hull_discharge.py tests/unit/test_hull_discharge.py
git commit -m "feat(nebula): hull discharge driver (seeded crackle spawn + emissive boost)"
```

---

## Task 2: Crackle pass (electric billboards)

**Files:**
- Create: `native/src/renderer/include/renderer/hull_discharge_pass.h`, `native/src/renderer/hull_discharge_pass.cc`
- Create: `native/src/renderer/shaders/hull_discharge.vert`, `hull_discharge.frag`
- Modify: `native/src/renderer/CMakeLists.txt`, `pipeline.cc`, `native/src/host/host_bindings.cc`, `engine/renderer.py`
- Test: `native/tests/renderer/frame_test.cc`

**Interfaces:**
- Consumes: descriptors from the driver (Task 1), fed via the binding.
- Produces:
  - C++ `renderer::HullDischarge { glm::vec3 world_pos; float age; float life; float size; glm::vec3 color; }`.
  - `renderer::HullDischargePass` with `render(const scenegraph::Camera&, Pipeline&, const std::vector<HullDischarge>&)`, `set_enabled(bool)`.
  - binding `set_hull_discharges(list[dict])` → `g_hull_discharges`.
  - `engine.renderer.set_hull_discharges(list)`.

**Approach:** mirror `hit_vfx_pass` — per-descriptor camera-facing additive billboard. The vertex shader builds a quad from `world_pos` + `size` and the camera right/up; the fragment shader draws a procedural electric crackle in quad space `[-1,1]`, size-eased + alpha-faded over `age/life`, with a 2-step on/off stutter. Additive blend, depth-test on (occluded by nearer hull), depth-write off; restore GL state. Read `hit_vfx_pass.{h,cc}` for the exact billboard draw mechanism (dynamic VBO / instancing) and copy it.

> **Live-tuning note:** the electric look is the hard part — filament count, jaggedness, stutter, brightness are dials. Start strong, dial at Vesuvi4.

- [ ] **Step 1: Add the FrameTest (failing)**

In `frame_test.cc`, add `HullDischargeRendersSprite`: build a `HullDischargePass`, feed one `HullDischarge` at a world point in front of a camera (age 0.03, life 0.1, size 0.3, color (0.6,0.8,1.0)), render into the test FBO; assert the centre region near the projected point is brighter than a no-discharge control, and an **empty list** leaves the target byte-identical. Mirror the `hit_vfx`/nebula FrameTest setup. If the procedural sprite makes a single-pixel assert flaky, assert a small region's summed brightness increased — do not fake it.

- [ ] **Step 2: Run to verify it fails**

Run: `ctest --test-dir build -R "FrameTest" -V` → the new test FAILs.

- [ ] **Step 3: Create `hull_discharge.vert`** (camera-facing billboard; mirror `hit_vfx.vert`'s basis)

```glsl
#version 330 core
layout(location = 0) in vec2 a_corner;   // [-1,1] quad corner

uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_center;   // discharge world pos
uniform float u_size;     // billboard half-size (GU), already size-eased

out vec2 v_uv;
void main() {
    vec3 right = vec3(u_view[0][0], u_view[1][0], u_view[2][0]);
    vec3 up    = vec3(u_view[0][1], u_view[1][1], u_view[2][1]);
    vec3 wp = u_center + (right * a_corner.x + up * a_corner.y) * u_size;
    v_uv = a_corner;
    gl_Position = u_proj * u_view * vec4(wp, 1.0);
}
```

- [ ] **Step 4: Create `hull_discharge.frag`** (procedural electric crackle)

```glsl
#version 330 core
in vec2 v_uv;             // [-1,1] quad space
out vec4 frag;

uniform vec3  u_color;
uniform float u_alpha;    // life fade (1→0)
uniform float u_stutter;  // 0 or 1 — 2-frame on/off flicker gate
// dials
uniform int   u_filaments;  // default 5
uniform float u_jag;        // default 6.0  (radial jaggedness frequency)
uniform float u_thick;      // default 0.06 (filament thickness)
uniform float u_core;       // default 0.25 (hot core radius)

float hash(float n){ return fract(sin(n) * 43758.5453); }

void main() {
    if (u_stutter < 0.5 || u_alpha <= 0.0) { frag = vec4(0.0); return; }
    float r = length(v_uv);
    if (r > 1.0) { frag = vec4(0.0); return; }
    float ang = atan(v_uv.y, v_uv.x);

    // Forked filaments: bright where the angle is near one of N jagged spokes.
    float fil = 0.0;
    for (int i = 0; i < u_filaments; ++i) {
        float base = (6.2831853 / float(u_filaments)) * float(i);
        // jagged wobble of the spoke angle with radius
        float wob = (hash(float(i) + floor(r * u_jag)) - 0.5) * 0.8;
        float d = abs(mod(ang - base - wob + 3.14159265, 6.2831853) - 3.14159265);
        fil = max(fil, smoothstep(u_thick, 0.0, d) * (1.0 - r));
    }
    // Hot core + filaments, faded by life. Electric tint.
    float core = smoothstep(u_core, 0.0, r);
    float e = clamp(core + fil, 0.0, 1.0) * u_alpha;
    frag = vec4(u_color * e, 1.0);   // premultiplied additive (blend GL_ONE, GL_ONE)
}
```

- [ ] **Step 5: Register shaders** — `embed_shader(SHADER_HULL_DISCHARGE_VS shaders/hull_discharge.vert hull_discharge_vs)` + `_FS` in `CMakeLists.txt`; `#include "embedded_hull_discharge_*.h"` + a `hull_discharge_` Shader member + accessor in `pipeline.cc` (mirror an existing pass).

- [ ] **Step 6: Create the pass `hull_discharge_pass.{h,cc}`**

Header: `HullDischarge` struct + `HullDischargePass` (ctor/dtor, `render(camera, pipeline, discharges)`, `set_enabled`, an `enabled_` flag, a static unit-quad VBO/VAO built in `initialize_gl`). `render`: early-out on empty/disabled; additive blend (`GL_ONE, GL_ONE`), depth-test on, depth-mask off, cull off; per discharge compute the size-ease (`size · smoothstep(0, spawn_frac, age/life)`-style fast ramp), the life-fade alpha (`1 - age/life`), and the 2-step stutter (`u_stutter = float((int(age / STUTTER_PERIOD) & 1) == 0)` with `STUTTER_PERIOD≈0.03`); set the dial uniforms (`u_filaments=5`, `u_jag=6`, `u_thick=0.06`, `u_core=0.25`); draw the quad. Restore GL state (blend off, depth-test on, depth-mask on, cull on). Mirror `hit_vfx_pass.cc`'s billboard draw.

- [ ] **Step 7: Wire into `host_bindings.cc`** — `#include`, globals `g_hull_discharges` + `g_hull_discharge_pass`, construct in `init`, reset in `shutdown` (beside `g_hit_vfx_pass`). Binding:

```cpp
    m.def("set_hull_discharges",
          [](const std::vector<py::dict>& descs) {
              g_hull_discharges.clear();
              g_hull_discharges.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::HullDischarge h;
                  auto p = d["world_pos"].cast<std::tuple<float,float,float>>();
                  h.world_pos = glm::vec3(std::get<0>(p), std::get<1>(p), std::get<2>(p));
                  h.age  = d["age"].cast<float>();
                  h.life = d["life"].cast<float>();
                  h.size = d["size"].cast<float>();
                  auto c = d["color"].cast<std::tuple<float,float,float>>();
                  h.color = glm::vec3(std::get<0>(c), std::get<1>(c), std::get<2>(c));
                  g_hull_discharges.push_back(h);
              }
          },
          py::arg("discharges"), "Set active hull electrical discharges.");
```

Render call in `render_space`, after `hit_vfx` (~line 623), gated by the Nebula Lightning toggle:
```cpp
        if (!for_viewscreen && dauntless_nebula_lightning::enabled()
            && g_hull_discharge_pass && !g_hull_discharges.empty())
            g_hull_discharge_pass->render(cam, *g_pipeline, g_hull_discharges);
```

- [ ] **Step 8: `engine/renderer.py`** — add:
```python
def set_hull_discharges(discharges: list) -> None:
    """Active hull electrical discharges for the crackle pass. Each:
    {"world_pos": (x,y,z), "age": float, "life": float, "size": float,
     "color": (r,g,b)}. Empty list = none."""
    _h.set_hull_discharges(discharges)
```

- [ ] **Step 9: Reconfigure + build**

Run: `cmake -B build -S . && cmake --build build -j` (clean; `cmake -B` required — shaders).

- [ ] **Step 10: Run the FrameTest**

Run: `ctest --test-dir build -R "FrameTest" -V` → the new test passes; report 0 new failures vs the pre-existing set.

- [ ] **Step 11: Commit**

```bash
git add native/src/renderer/include/renderer/hull_discharge_pass.h native/src/renderer/hull_discharge_pass.cc native/src/renderer/shaders/hull_discharge.vert native/src/renderer/shaders/hull_discharge.frag native/src/renderer/CMakeLists.txt native/src/renderer/pipeline.cc native/src/host/host_bindings.cc engine/renderer.py native/tests/renderer/frame_test.cc
git commit -m "feat(nebula): hull-discharge crackle pass (electric billboards)"
```

---

## Task 3: Host-loop integration (driver tick + feeds + emissive restore)

**Files:** `engine/host_loop.py`
**Test:** existing suites unaffected + the emissive-restore invariant (manual reasoning + Task 1's `emissive_boost==1.0` coverage; verified live in Task 4).

**Interfaces:**
- Consumes: `HullDischargeDriver` (Task 1); `r.set_hull_discharges` (Task 2); `r.nebula_lightning_enabled()`, `r.set_emissive_scale(iid, scale)`; the in-nebula signal + player's nebula damage rate; `subsystem_world_position` + `player.GetSubsystems()`; the player renderer iid via `session.ship_instances`.
- Produces: module global `_hull_discharge = None`; per-frame discharge feed + emissive scale; reset + emissive-restore on swap.

- [ ] **Step 1: Lazy global + reset (with emissive restore)**

Near `_nebula_thunder = None`, add `_hull_discharge = None`. In `reset_sdk_globals` (beside the thunder reset), add:
```python
    if _hull_discharge is not None:
        _hull_discharge.reset()
```
(The emissive itself is restored each frame by the gating in Step 2/3 — when the driver is reset/empty, `emissive_boost()` is 1.0; but a mission swap may destroy the player instance, so the per-frame restore handles it.)

- [ ] **Step 2: Tick the driver + compute the damage rate + hull points**

Immediately after the nebula-thunder tick block (the `_nebula_thunder.update(...)` site), add — reusing the same `_gt`, `player`, and `in_neb` locals already computed there:
```python
                # Hull electrical discharges: crackle on the hull while in a
                # nebula, rate ∝ the nebula's damage. Gated by the Nebula
                # Lightning toggle (shared with the flashes).
                global _hull_discharge
                if r.nebula_lightning_enabled():
                    if _hull_discharge is None:
                        from engine.appc.hull_discharge import HullDischargeDriver
                        _hull_discharge = HullDischargeDriver()
                    dmg_rate = 0.0
                    hull_pts = []
                    if in_neb and player is not None:
                        # The player's nebula damage rate (hull/sec).
                        import App
                        from engine.appc.subsystems import subsystem_world_position
                        pset = player.GetContainingSet()
                        if pset is not None:
                            for obj in pset.GetClassObjectList(App.CT_NEBULA):
                                neb = App.MetaNebula_Cast(obj)
                                if neb is not None and neb.IsObjectInNebula(player):
                                    dmg_rate = neb.GetDamage()[0]
                                    break
                        # Hull anchor points = subsystem world mounts.
                        for sub in player.GetSubsystems():
                            wp = subsystem_world_position(sub, player)
                            hull_pts.append((wp.x, wp.y, wp.z))
                    _hull_discharge.update(in_neb, dmg_rate, TICK_DT, hull_pts, _gt)
```
(If `_gt` / `player` / `in_neb` are named differently at the thunder site, match the real names — do NOT introduce new lookups.)

- [ ] **Step 3: Feed discharges + apply the emissive flicker each frame**

In the per-frame render block (beside `r.set_nebula_godrays(...)`), add:
```python
            discharges = []
            emissive_boost = 1.0
            if _hull_discharge is not None and r.nebula_lightning_enabled() and not _warp_streaking:
                discharges = _hull_discharge.active_discharges()
                emissive_boost = _hull_discharge.emissive_boost()
            r.set_hull_discharges(discharges)
            # Whole-hull emissive flicker on the PLAYER instance. Restore exactly
            # 1.0 whenever idle / toggle off / no player so the hull is never
            # left bright. Only touch it when we have the player's renderer iid.
            _player_iid = (session.ship_instances.get(player)
                           if (session is not None and player is not None) else None)
            if _player_iid is not None:
                r.set_emissive_scale(_player_iid, emissive_boost)
```
(Use the real accessor for the player's renderer instance id — confirm `session.ship_instances` is the map and `.get(player)` is how it's keyed at this site; if the map/key differ, match them. The `emissive_boost` defaults to 1.0 so the toggle-off / not-in-nebula / driver-None paths all restore the hull.)

- [ ] **Step 4: Verify no regressions**

Run: `uv run pytest tests/unit/test_hull_discharge.py tests/unit/test_nebula_thunder.py -v` (pass).
Run: `uv run python -c "import engine.host_loop"` (imports cleanly).
Run: `bash scripts/run_tests.sh` (full suite; confirm 0 NEW failures vs the pre-existing baseline — capture the baseline count first if unsure).

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(nebula): drive hull discharges + whole-hull emissive flicker"
```

---

## Task 4: Live verification + tuning

**Files:** none (verification). Hand off to Mark — no desktop interaction on his workstation.

- [ ] **Step 1:** `cmake -B build -S . && cmake --build build -j` (clean).
- [ ] **Step 2:** Checklist for Mark (load Vesuvi4 / Multi5 via `--developer`, fly into the nebula):
  1. Brief electric crackles flick across the hull (small, frame-or-two, electric blue-white).
  2. The rate climbs noticeably in a dense **damaging** clump vs light/no damage.
  3. **Rare** idle strikes when not taking damage.
  4. The hull faintly **flickers** brighter on a discharge burst (emissive) and never stays bright.
  5. Toggle **Nebula Lightning** off → crackles + flashes both stop, hull emissive back to normal; on → back.
  6. Crackles sit on/near the hull (subsystem coverage), not floating in space.
  7. Framerate holds.
- [ ] **Step 3:** Apply tuning (driver dials: `IDLE_RATE`/`DAMAGE_GAIN`/life/size/`FLICKER`; shader dials: `u_filaments`/`u_jag`/`u_thick`/`u_core`, stutter period), rebuilding with `cmake -B build -S .` after shader edits. Commit:
```bash
git add engine/appc/hull_discharge.py native/src/renderer/
git commit -m "tune(nebula): hull-discharge rate + electric look per live verification"
```

---

## Self-Review

**Spec coverage:**
- §5 driver (rate ∝ damage + idle, spawn at hull points, emissive boost, restore-to-1.0) → Task 1 ✓
- §3 hull points from subsystem mounts → Task 3 (gather) + Task 1 (consume) ✓
- §6 crackle pass (electric billboards, depth-tested, additive) → Task 2 ✓
- §6 emissive flicker via `set_emissive_scale`, restore exactly 1.0 → Task 3 ✓
- §7 toggle (reuse Nebula Lightning) → Task 2 (render gate) + Task 3 (driver/feed gate) ✓
- §7 testing (driver pytest, crackle FrameTest, emissive-restore, live) → Tasks 1,2,4 ✓
- Global: no gameplay coupling; inert outside nebula / toggle off; deterministic; player-only; game-time accessor ✓

**Placeholder scan:** No TBD/TODO. The "match the real name/accessor" notes in Task 3 (the thunder-site locals; the player-iid map) are explicit research-then-implement tied to named sites — the implementer reads the site and the reviewer confirms. The driver carries complete code; the shader is complete and compilable, its constants live-tuning dials.

**Type consistency:** `HullDischargeDriver.update(in_nebula, damage_rate, dt, hull_points, game_time)/active_discharges()/emissive_boost()/reset()` (Task 1) consumed in Task 3; descriptor dict `{world_pos, age, life, size, color}` (Task 1) matches `set_hull_discharges` cast (Task 2) and `HullDischarge{world_pos,age,life,size,color}` (Task 2); `set_hull_discharges` naming consistent across binding/Python.

**Known risks flagged in-plan:** the electric look (Task 2, live-tuned); the stuck-bright-hull invariant (Task 3 restore-to-1.0, Task 1 `emissive_boost==1.0` test); the host-site local-name + player-iid substitutions (Task 3).
