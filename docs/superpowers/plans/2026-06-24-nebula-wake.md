# Nebula Ship Wake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A luminous, churning turbulent wake behind the player ship as it flies through a volumetric nebula — the cloud is energized and stirred (not cleared) along the recent path, fading as it settles.

**Architecture:** A seeded-free Python **wake tracker** (`nebula_wake.py`) records the player's recent positions (sampled by distance moved) into a fading, bounded trail. The host feeds the trail to the volumetric pass via `set_nebula_wake`; the pass uploads `u_wake[N]` and the existing raymarch shader adds animated turbulence + a self-glow lift near the trail. GPU-only/visual; gated by the existing Volumetric Nebulae toggle.

**Tech Stack:** Python 3 (tracker, host loop), pytest; C++17 + OpenGL/GLSL (extend the volumetric pass + shader), pybind11, CMake shader embedding, CTest FrameTest.

## Global Constraints

- **No new toggle.** The wake is part of the volumetric cloud — gated by `dauntless_volumetric_nebulae::enabled()`. Off → no cloud, no wake; host feeds an empty trail.
- **Visual only / GPU-only.** The wake never touches the CPU concealment field (`nebula_density.py`) — your own wake is behind you, not where you hide.
- **Inert** outside a nebula, when stationary (no movement → no new points), and when the toggle is off (empty trail → shader byte-identical to the plain cloud).
- **Bounded cost.** `u_wake[N]` with `N = 24` (matches the shader array size); the per-sample wake loop is the perf risk (spec §8). The `u_wake_count == 0` and per-sample `wake == 0` early-outs keep the common path cheap.
- **Determinism:** the tracker is driven by the position history (no RNG); reset on mission swap (`reset_sdk_globals`).
- **Game time** via `App.g_kUtopiaModule.GetGameTime()` (the shim's `TGTimerManager` lacks `GetGameTime`).
- **Shader rebuild:** any `.frag` change needs `cmake -B build -S .` BEFORE `cmake --build build -j` (shaders embedded at configure). Build from project root, never inside `native/`.
- **No desktop interaction on Mark's workstation** — live verification is handed off.
- **Plan B** (spec §8) is a live-verification decision, NOT part of this plan's tasks. If the in-raymarch wake can't hold 60 Hz after tuning `N`/`u_wake_radius`, fall back to a decoupled additive wake — but only after live frame-times say so.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `engine/appc/nebula_wake.py` | Create | `NebulaWakeTracker` — distance-sampled fading trail ring buffer. Pure logic. |
| `tests/unit/test_nebula_wake.py` | Create | Tracker unit tests. |
| `native/src/renderer/shaders/nebula_volumetric.frag` | Modify | `u_wake[N]` + `wake_at(p)` + churn (turbulence) + glow lift in the march loop. |
| `native/src/renderer/nebula_volumetric_pass.{h,cc}` | Modify | `render()` gains a `wake` param; upload `u_wake`/`u_wake_count` + dial uniforms. |
| `native/src/host/host_bindings.cc` | Modify | `g_nebula_wake` + `set_nebula_wake` binding; pass `g_nebula_wake` to the render call. |
| `engine/renderer.py` | Modify | `set_nebula_wake(points)` wrapper. |
| `engine/host_loop.py` | Modify | Tick the tracker; feed `set_nebula_wake`; reset on swap. |
| `native/tests/renderer/frame_test.cc` | Modify | Wake FrameTest. |

---

## Task 1: Wake tracker (Python)

**Files:**
- Create: `engine/appc/nebula_wake.py`
- Test: `tests/unit/test_nebula_wake.py`

**Interfaces:**
- Produces: `class NebulaWakeTracker`:
  - `__init__(self)`
  - `update(self, in_nebula: bool, pos, game_time: float) -> None` — `pos` is `(x,y,z)` world or None. Records a new trail point only when the ship has moved ≥ `SPACING` GU since the last; ages/expires points; caches the output list.
  - `trail_points(self) -> list[dict]` — `[{"pos": (x,y,z), "strength": float}]`, ≤ `N`, strength age-faded `1→0` (with a front-rise ease-in), freshest last.
  - `reset(self) -> None`.
- Dials (module constants): `SPACING=6.0`, `N=24`, `LIFETIME=4.0`, `FRONT_RISE=0.2`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_nebula_wake.py`:

```python
from engine.appc.nebula_wake import NebulaWakeTracker, SPACING, N, LIFETIME


def test_no_points_outside_nebula():
    w = NebulaWakeTracker()
    for i in range(100):
        w.update(False, (float(i) * 100.0, 0.0, 0.0), i / 60.0)
    assert w.trail_points() == []


def test_no_points_when_pos_none():
    w = NebulaWakeTracker()
    for i in range(100):
        w.update(True, None, i / 60.0)
    assert w.trail_points() == []


def test_records_by_distance_not_per_tick():
    w = NebulaWakeTracker()
    # Move a tiny amount each tick (< SPACING) → only the first point lands.
    t = 0.0
    for i in range(50):
        t += 1.0 / 60.0
        w.update(True, (i * 0.1, 0.0, 0.0), t)   # 0.1 GU/tick << SPACING
    assert len(w.trail_points()) == 1            # only the initial drop


def test_records_a_new_point_each_spacing():
    w = NebulaWakeTracker()
    t = 0.0
    # Jump SPACING GU each tick → a new point every tick (until the cap).
    for i in range(10):
        t += 1.0 / 60.0
        w.update(True, (i * SPACING, 0.0, 0.0), t)
    assert len(w.trail_points()) == 10


def test_stationary_lays_no_trail_growth():
    w = NebulaWakeTracker()
    t = 0.0
    w.update(True, (0.0, 0.0, 0.0), t)           # first point
    for _ in range(120):
        t += 1.0 / 60.0
        w.update(True, (0.0, 0.0, 0.0), t)       # never moves
    # No new points from standing still (the one point fades out over LIFETIME).
    assert len(w.trail_points()) <= 1


def test_caps_at_N():
    w = NebulaWakeTracker()
    t = 0.0
    for i in range(N * 3):
        t += 1.0 / 60.0
        w.update(True, (i * SPACING, 0.0, 0.0), t)
    assert len(w.trail_points()) <= N


def test_strength_fades_and_points_expire():
    w = NebulaWakeTracker()
    # Drop one point at t=0, then keep ticking in place past LIFETIME.
    w.update(True, (0.0, 0.0, 0.0), 0.0)
    s0 = w.trail_points()
    assert s0 and 0.0 < s0[0]["strength"] <= 1.0
    # Halfway through life: strength has dropped.
    w.update(True, (0.0, 0.0, 0.0), LIFETIME * 0.5)
    mid = w.trail_points()
    assert mid and mid[0]["strength"] < s0[0]["strength"]
    # Past life: the point is gone.
    w.update(True, (0.0, 0.0, 0.0), LIFETIME + 0.1)
    assert w.trail_points() == []


def test_clears_on_leaving_nebula():
    w = NebulaWakeTracker()
    t = 0.0
    for i in range(10):
        t += 1.0 / 60.0
        w.update(True, (i * SPACING, 0.0, 0.0), t)
    assert w.trail_points()
    w.update(False, (999.0, 0.0, 0.0), t + 0.1)
    assert w.trail_points() == []


def test_reset_clears():
    w = NebulaWakeTracker()
    t = 0.0
    for i in range(10):
        t += 1.0 / 60.0
        w.update(True, (i * SPACING, 0.0, 0.0), t)
    w.reset()
    assert w.trail_points() == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_nebula_wake.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.appc.nebula_wake`.

- [ ] **Step 3: Implement `engine/appc/nebula_wake.py`**

```python
"""Nebula ship wake — the trail tracker.

Records the player's recent world positions (sampled by distance moved) into a
fading, bounded ring buffer while the player is in a nebula. Emits trail points
{pos, strength} (strength age-faded 1→0) that the volumetric raymarch uses to
churn + energize the cloud behind the ship. Pure logic, no GL. Driven entirely
by where the ship went — no RNG.
"""
import math

SPACING = 6.0       # GU the ship must move before a new trail point is laid
N = 24              # max trail points (matches u_wake[24]); bounds length + cost
LIFETIME = 4.0      # seconds for a point's strength to fade 1 → 0
FRONT_RISE = 0.2    # seconds the newest point eases in (no pop)


class _Point:
    __slots__ = ("pos", "born")

    def __init__(self, pos, born):
        self.pos = pos
        self.born = born


def _dist2(a, b):
    dx, dy, dz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return dx * dx + dy * dy + dz * dz


class NebulaWakeTracker:
    def __init__(self):
        self._points = []      # oldest first
        self._last = None      # last recorded position
        self._out = []

    def reset(self):
        self._points = []
        self._last = None
        self._out = []

    def update(self, in_nebula, pos, game_time):
        if not in_nebula or pos is None:
            if self._points or self._out:
                self._points = []
                self._out = []
            self._last = None
            return

        # Record a new point only when the ship has moved >= SPACING.
        if self._last is None or _dist2(pos, self._last) >= SPACING * SPACING:
            self._points.append(_Point((pos[0], pos[1], pos[2]), game_time))
            self._last = (pos[0], pos[1], pos[2])
            if len(self._points) > N:
                self._points = self._points[-N:]

        # Expire + build the output with age-faded strength.
        alive = []
        out = []
        for p in self._points:
            age = game_time - p.born
            if age < 0.0 or age >= LIFETIME:
                continue
            alive.append(p)
            fade = 1.0 - age / LIFETIME
            rise = (age / FRONT_RISE) if (FRONT_RISE > 0.0 and age < FRONT_RISE) else 1.0
            s = fade * rise
            if s > 0.0:
                out.append({"pos": p.pos, "strength": s})
        self._points = alive
        self._out = out

    def trail_points(self):
        return self._out
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_nebula_wake.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/nebula_wake.py tests/unit/test_nebula_wake.py
git commit -m "feat(nebula): ship-wake trail tracker (distance-sampled, fading)"
```

---

## Task 2: Churn+glow in the volumetric raymarch (shader + pass + feed)

**Files:**
- Modify: `native/src/renderer/shaders/nebula_volumetric.frag`
- Modify: `native/src/renderer/include/renderer/nebula_volumetric_pass.h`, `native/src/renderer/nebula_volumetric_pass.cc`
- Modify: `native/src/host/host_bindings.cc`, `engine/renderer.py`
- Test: `native/tests/renderer/frame_test.cc`

**Interfaces:**
- Produces:
  - Python `engine.renderer.set_nebula_wake(points: list)` — each `{"pos": (x,y,z), "strength": float}`.
  - C++ `g_nebula_wake` (`std::vector<glm::vec4>`, xyz=pos, w=strength); binding `set_nebula_wake`.
  - `NebulaVolumetricPass::render(...)` gains `const std::vector<glm::vec4>& wake` (appended to the existing signature); uploads `u_wake[24]` / `u_wake_count` + dial uniforms.
- Consumes: the existing volumetric march loop + `u_time`; the `vnoise`/`fbm` already defined in the shader (reuse for the turbulence).

**Approach:** per march sample compute one `wake = max over points of (strength · smoothstep(radius,0,dist))`; where `wake>0`, add animated turbulence to the density and a hot self-glow lift. `wake==0` and `u_wake_count==0` early-outs keep the common path cheap. Empty wake → byte-identical to the plain cloud.

> **Live-tuning note:** the churn look is procedural — `u_wake_radius`, `u_turb_freq`, `u_turb_amt`, `u_swirl`, `u_wake_glow` are the dials (and `N`/`u_wake_radius` are the perf levers per spec §8).

- [ ] **Step 1: Add the FrameTest (failing)**

In `frame_test.cc`, add `NebulaWakeBrightensTrail`: render a seeded volume (camera inside) twice — once with an empty wake list, once with one wake point `{pos = a world point on the camera ray, strength = 1.0}`. Assert the centre-region brightness with the wake exceeds the no-wake control (the energized churn lifts it), and that the **empty-wake** render is byte-identical to the plain-cloud render (so a no-wake frame is unchanged). Mirror the existing volumetric FrameTest setup; if exact byte-identity is awkward because the wake path adds uniforms, assert pixel-equality of the empty-wake vs a build with the wake uniforms defaulted — do NOT fake it.

- [ ] **Step 2: Run to verify it fails**

Run: `ctest --test-dir build -R "FrameTest" -V` → the new test FAILs.

- [ ] **Step 3: Extend `nebula_volumetric.frag`**

Add the uniforms (near the other dials):
```glsl
uniform int   u_wake_count;
uniform vec4  u_wake[24];       // xyz world pos, w = age-faded strength
uniform float u_wake_radius;    // GU falloff radius around each trail point
uniform float u_turb_freq;      // wake turbulence frequency
uniform float u_turb_amt;       // wake density agitation amount
uniform float u_swirl;          // wake turbulence advection speed (× u_time)
uniform float u_wake_glow;      // wake self-glow lift (energized)
```

Add the wake lookup (after the `density` function):
```glsl
// Strongest wake influence at p: max over the trail of strength × radial falloff.
float wake_at(vec3 p){
    float w = 0.0;
    for(int i=0;i<u_wake_count;i++){
        float d = length(p - u_wake[i].xyz);
        w = max(w, u_wake[i].w * smoothstep(u_wake_radius, 0.0, d));
    }
    return w;
}
```

In the march loop, replace the `float dens=density(p);` ... `col=(scat*u_scatter + u_self_glow)*base*dens;` region with the wake-aware version:
```glsl
        vec3 p=u_eye+dir*t;
        float dens=density(p);
        // Ship wake: churn (agitate density) + energize (glow lift) near the trail.
        float wk = (u_wake_count > 0) ? wake_at(p) : 0.0;
        if(wk > 0.0){
            float turb = fbm(p * u_turb_freq + vec3(u_time * u_swirl, 0.0, 0.0));
            dens += wk * turb * u_turb_amt;     // stir the cloud up (don't clear)
        }
        if(dens>0.001){
            float ext=dens*u_density_scale*u_step;
            vec3 scat=vec3(0.0);
            for(int l=0;l<u_dir_light_count;l++){
                vec3 ld=normalize(u_dir_light_dir_ws[l]);
                float occ=0.0;
                if(l==0){
                    for(float k=1.0;k<=u_light_steps;k+=1.0)
                        occ+=density(p+ld*(k*u_step))*u_density_scale*u_step;
                }
                scat+=u_dir_light_color[l]*exp(-occ);
            }
            float cvar = vnoise(p*(u_fbm.x*0.4) + u_seed.yzx + 13.0);
            vec3 tintmul = mix(vec3(0.70,0.92,1.30), vec3(1.30,1.02,0.70),
                               clamp(cvar,0.0,1.0));
            vec3 base = u_rgb * mix(vec3(1.0), tintmul, u_color_var);
            vec3 col=(scat*u_scatter + u_self_glow)*base*dens;
            // Energized charged-particle glow in the wake (hot blue-white).
            col += wk * u_wake_glow * vec3(0.6,0.8,1.0) * dens;
            lit+=transm*col*ext;
            transm*=exp(-ext);
        }
        t+=u_step;
```
(This preserves the existing scatter/tint logic verbatim — only the `wk` computation, the density agitation, and the `col +=` glow line are new.)

- [ ] **Step 4: Extend the pass (`nebula_volumetric_pass.h` + `.cc`)**

In the header, add `const std::vector<glm::vec4>& wake` as the LAST parameter of `render(...)`. In `.cc`, near the `u_spheres` upload, add (define `constexpr int kMaxWake = 24;` next to `kMaxSpheres`):
```cpp
    const int wake_count = std::min(static_cast<int>(wake.size()), kMaxWake);
    march.set_int("u_wake_count", wake_count);
    if (wake_count > 0)
        march.set_vec4_array("u_wake", wake.data(), wake_count);
    march.set_float("u_wake_radius", 8.0f);
    march.set_float("u_turb_freq",  0.08f);
    march.set_float("u_turb_amt",   0.6f);
    march.set_float("u_swirl",      0.4f);
    march.set_float("u_wake_glow",  0.6f);
```

- [ ] **Step 5: Binding + render call (`host_bindings.cc`) + wrapper (`renderer.py`)**

Add the global `std::vector<glm::vec4> g_nebula_wake;` near `g_nebulae`; clear it in `init`/`shutdown` beside `g_nebulae.clear()`. Binding (near `set_nebulae`):
```cpp
    m.def("set_nebula_wake",
          [](const std::vector<py::dict>& pts) {
              g_nebula_wake.clear();
              g_nebula_wake.reserve(pts.size());
              for (const auto& d : pts) {
                  auto p = d["pos"].cast<std::tuple<float,float,float>>();
                  float s = d["strength"].cast<float>();
                  g_nebula_wake.emplace_back(std::get<0>(p), std::get<1>(p),
                                             std::get<2>(p), s);
              }
          },
          py::arg("points"), "Set the player's nebula wake trail points.");
```
At the volumetric render call (host_bindings.cc ~613), pass `g_nebula_wake` as the new last arg:
```cpp
                g_nebula_volumetric_pass->render(
                    cam, *g_pipeline, g_nebulae, g_lighting,
                    /* ...existing args... */,
                    g_nebula_wake);
```
(Read the actual call at ~613 and append `g_nebula_wake` to match the new signature.)

In `engine/renderer.py`:
```python
def set_nebula_wake(points: list) -> None:
    """Player nebula wake trail points for the volumetric cloud's churn+glow.
    Each: {"pos": (x,y,z), "strength": float}. Empty = no wake."""
    _h.set_nebula_wake(points)
```

- [ ] **Step 6: Reconfigure + build**

Run: `cmake -B build -S . && cmake --build build -j` (clean; `cmake -B` required — shader changed).

- [ ] **Step 7: Run the FrameTest**

Run: `ctest --test-dir build -R "FrameTest" -V` → the new wake test passes; the empty-wake byte-identity holds; report 0 new failures vs the pre-existing set.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/shaders/nebula_volumetric.frag native/src/renderer/include/renderer/nebula_volumetric_pass.h native/src/renderer/nebula_volumetric_pass.cc native/src/host/host_bindings.cc engine/renderer.py native/tests/renderer/frame_test.cc
git commit -m "feat(nebula): churn+glow ship wake in the volumetric raymarch"
```

---

## Task 3: Host-loop integration

**Files:** `engine/host_loop.py`
**Test:** existing suites unaffected + verified live in Task 4.

**Interfaces:**
- Consumes: `NebulaWakeTracker` (Task 1); `r.set_nebula_wake` (Task 2); the in-nebula signal + `player.GetWorldLocation()`; `r.volumetric_nebulae_enabled()`.
- Produces: module global `_nebula_wake = None`; per-frame wake feed; reset on swap.

- [ ] **Step 1: Lazy global + reset**

Near `_nebula_thunder = None` / `_hull_discharge = None`, add `_nebula_wake = None`. In `reset_sdk_globals` (beside the other nebula resets), add:
```python
    if _nebula_wake is not None:
        _nebula_wake.reset()
```

- [ ] **Step 2: Tick the tracker each sim tick**

Immediately after the hull-discharge tick block (search for `_hull_discharge.update(`), add — reusing the same `in_neb`, `player`, `_gt` locals:
```python
                # Nebula ship wake: record the player's path while in a nebula.
                # Gated by Volumetric Nebulae (the wake lives in the volumetric
                # cloud). Visual only.
                global _nebula_wake
                if r.volumetric_nebulae_enabled():
                    if _nebula_wake is None:
                        from engine.appc.nebula_wake import NebulaWakeTracker
                        _nebula_wake = NebulaWakeTracker()
                    _wpos = None
                    if in_neb and player is not None:
                        _loc = player.GetWorldLocation()
                        _wpos = (_loc.x, _loc.y, _loc.z)
                    _nebula_wake.update(in_neb, _wpos, _gt)
```
(Match the real indentation of the surrounding block; `in_neb`/`player`/`_gt` are the locals from the thunder/hull-discharge tick.)

- [ ] **Step 3: Feed the wake each frame**

In the per-frame render block beside `r.set_nebulae(...)` / `r.set_nebula_godrays(...)`, add:
```python
            wake_pts = []
            if (_nebula_wake is not None and r.volumetric_nebulae_enabled()
                    and not _warp_streaking):
                wake_pts = _nebula_wake.trail_points()
            r.set_nebula_wake(wake_pts)
```

- [ ] **Step 4: Verify no regressions**

Run: `uv run pytest tests/unit/test_nebula_wake.py tests/unit/test_nebula.py -v` (pass).
Run: `uv run python -c "import engine.host_loop"` (imports cleanly).
Run: `bash scripts/run_tests.sh` (full suite; confirm 0 NEW failures vs the pre-existing baseline — capture it first if unsure).

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(nebula): drive the ship wake into the volumetric cloud"
```

---

## Task 4: Live verification + tuning (incl. the Plan B decision)

**Files:** none (verification). Hand off to Mark — no desktop interaction on his workstation.

- [ ] **Step 1:** `cmake -B build -S . && cmake --build build -j` (clean).
- [ ] **Step 2:** Checklist for Mark (load Vesuvi4 / Multi5 via `--developer`, fly through the nebula):
  1. A luminous, churning, swirling trail forms **behind** the ship and settles back over a few seconds.
  2. The wake is strongest right behind the ship and fades down the trail.
  3. Stationary → no growing wake; moving fast → a longer trail.
  4. Toggle **Volumetric Nebulae** off → the wake disappears with the cloud; on → back.
  5. **Frame-rate holds.** This is the Plan-B gate: if the wake tanks the framerate, first try lowering `N` (engine/appc/nebula_wake.py) and `u_wake_radius` (the pass); if still heavy, escalate to spec §8 Plan B #1 (decoupled additive wake) — a separate follow-up, not this branch.
  6. The churn look reads as an *energized wake*, not a noisy smear.
- [ ] **Step 3:** Apply tuning (tracker: `SPACING`/`N`/`LIFETIME`; shader: `u_wake_radius`/`u_turb_freq`/`u_turb_amt`/`u_swirl`/`u_wake_glow`), rebuilding with `cmake -B build -S .` after shader edits. Commit:
```bash
git add engine/appc/nebula_wake.py native/src/renderer/
git commit -m "tune(nebula): ship-wake trail + churn/glow dials per live verification"
```

---

## Self-Review

**Spec coverage:**
- §5 tracker (distance-sampled, capped `N`, fade `LIFETIME`, front-rise, clears on leaving) → Task 1 ✓
- §6 churn+glow shader (wake_at, turbulence agitation, glow lift) + feed (`u_wake`/`u_wake_count`) → Task 2 ✓
- §7 integration (tick, feed, reset) + toggle gating (Volumetric Nebulae) → Task 3 ✓
- §7 testing (tracker pytest, wake FrameTest, live) → Tasks 1,2,4 ✓
- §8 perf Plan B → Task 4 Step 2.5 (the live decision gate; Plan B itself is a deliberate non-task) ✓
- Global: no new toggle; visual-only (no concealment touch); inert off-paths; deterministic; game-time accessor ✓

**Placeholder scan:** No TBD/TODO. The "match the real call/locals" notes in Tasks 2-3 (the render-call arg append; the thunder/hull-discharge tick locals) are explicit research-then-implement tied to named sites. The tracker carries complete code; the shader changes are complete and compilable; the churn constants are live-tuning dials. Plan B is intentionally NOT a task (spec §8 says it's a live-frametime decision).

**Type consistency:** `NebulaWakeTracker.update(in_nebula, pos, game_time)/trail_points()/reset()` (Task 1) consumed in Task 3; trail dict `{pos, strength}` (Task 1) matches the `set_nebula_wake` cast (Task 2) and `g_nebula_wake` vec4 packing; `render(...wake)` param (Task 2) matches the render-call append (Task 2 Step 5); `set_nebula_wake` naming consistent across binding/Python.
