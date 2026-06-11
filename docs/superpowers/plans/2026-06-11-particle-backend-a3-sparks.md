# Particle Backend A3 (Sparks) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add velocity damping + tailed-streak rendering to the analytic `ParticlePass`, a real `SparkParticleController` so SDK `Effects.py` spark factories run unmodified (un-stubbing A2's silently-dropped death-debris sparks), and reconcile `hit_vfx` impact sparks to the shared streak look.

**Architecture:** Two new emitter fields (`damping`, `tail_length`), both additive — when zero, the renderer is byte-identical to A1/A2. Damping uses the analytic `(v/c)(1−e^{−cτ})` curve already proven in `hit_vfx_pass`. Streaks are drawn by extending the **shared** `hit_vfx.vert` billboard shader with a velocity-aligned quad path (two uniforms), so both the `ParticlePass` spark mode and the `hit_vfx` spark loop produce identical streaks by construction.

**Tech Stack:** C++17 + OpenGL/GLSL (renderer, gtest), pybind11 (host binding), Python 3 + pytest (controller/factories), the `engine/appc` + `App.py` shim.

**Spec:** [`docs/superpowers/specs/2026-06-11-particle-backend-a3-sparks-design.md`](../specs/2026-06-11-particle-backend-a3-sparks-design.md) (Spec A, slice 3).

**Scope note:** A3 is the last particle slice. It does **not** touch `engine/appc/actions.py` — the death-cascade *timing* (explosions firing simultaneously) is the separate, deferred engine timed-sequencing project. A3 makes deaths *render their debris sparks*.

---

## File Structure

| File | Responsibility |
|---|---|
| `native/src/renderer/include/renderer/frame.h` (modify) | add `damping` + `tail_length` to `ParticleEmitterDescriptor`. |
| `native/src/renderer/include/renderer/particle_math.h` (modify) | add `damped_travel` + `streak_quad` pure helpers. |
| `native/tests/renderer/particle_math_test.cc` (modify) | unit-test the two new helpers. |
| `native/src/renderer/shaders/hit_vfx.vert` (modify) | add the velocity-aligned streak path (2 uniforms; length 0 = current billboard). |
| `native/src/renderer/particle_pass.cc` (modify) | apply damping to directed travel; set streak uniforms per particle from `tail_length`. |
| `native/src/renderer/hit_vfx_pass.cc` (modify) | route the spark sub-quad through the streak uniforms (reconcile); flash billboard sets streak length 0. |
| `native/src/host/host_bindings.cc` (modify) | read `damping` + `tail_length` dict keys (guarded defaults). |
| `engine/appc/particles.py` (modify) | `SparkParticleController` + `SparkParticleController_Create`; `_descriptor_for` emits `damping`/`tail_length`; `duration→stop_age`. |
| `App.py` (modify) | wire `SparkParticleController_Create`. |
| `tests/unit/test_particles_spark.py` (create) | controller + descriptor + SDK-unmodified proof. |
| `tests/integration/test_particles_host_loop.py` (modify) | end-to-end: `ObjectExploding` registers real sparks. |
| `native/tests/renderer/particle_pass_test.cc` (modify) | streak/damping FrameTests + A1 byte-identity. |

---

## Task 1: Descriptor fields + analytic helpers (`damped_travel`, `streak_quad`)

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h`
- Modify: `native/src/renderer/include/renderer/particle_math.h`
- Modify: `native/tests/renderer/particle_math_test.cc`

- [ ] **Step 1: Add the two descriptor fields to `frame.h`**

In `ParticleEmitterDescriptor`, after the A2 fields (`random_velocity_speed`), add:
```cpp
    float damping     = 0.0f;   // velocity decay rate; 0 = linear (A1/A2)
    float tail_length = 0.0f;   // streak length multiplier; 0 = camera-facing billboard
```

- [ ] **Step 2: Write the failing math test**

Add to `native/tests/renderer/particle_math_test.cc`:
```cpp
TEST(ParticleMath, DampedTravel) {
    // c=0 => linear
    EXPECT_FLOAT_EQ(damped_travel(2.0f, 0.0f, 0.5f), 1.0f);
    // c>0 => below linear, monotonic, asymptotes to v/c
    float t1 = damped_travel(2.0f, 1.0f, 0.5f);
    float t2 = damped_travel(2.0f, 1.0f, 1.0f);
    EXPECT_LT(t1, 1.0f);            // less than linear 2*0.5
    EXPECT_GT(t2, t1);             // monotonic increasing
    EXPECT_LT(t2, 2.0f);          // bounded by v/c = 2.0
    EXPECT_NEAR(damped_travel(2.0f, 1.0f, 100.0f), 2.0f, 1e-2f);  // asymptote
}

TEST(ParticleMath, StreakQuadDegeneratesAndAligns) {
    glm::vec3 center{0, 0, 0};
    glm::vec3 axis{0, 1, 0};
    glm::vec3 cam_right{1, 0, 0};
    glm::vec3 cam_up{0, 0, 1};
    // length 0 => a camera-facing square of half-extent = half_width
    auto sq = streak_quad(center, axis, /*length=*/0.0f, /*half_width=*/0.5f, cam_right, cam_up);
    // corner 0 is (-1,-1): center - cam_right*0.5 - cam_up*0.5
    EXPECT_NEAR(sq[0].x, -0.5f, 1e-5f);
    EXPECT_NEAR(sq[0].z, -0.5f, 1e-5f);
    // length>0 => the long edge runs along `axis`
    auto st = streak_quad(center, axis, /*length=*/2.0f, /*half_width=*/0.1f, cam_right, cam_up);
    // top corners (corner.y=+1) are offset +axis*length from bottom corners
    glm::vec3 long_edge = st[2] - st[1];   // see corner ordering in impl
    EXPECT_GT(std::abs(glm::dot(glm::normalize(long_edge), axis)), 0.9f);
}
```

- [ ] **Step 3: Run to verify it fails**

Run: `cmake --build build -j 2>&1 | tail -10`
Expected: FAIL — `damped_travel` / `streak_quad` not declared.

- [ ] **Step 4: Add the helpers to `particle_math.h`**

```cpp
/// Damped ballistic travel distance: (v/c)(1 - e^{-c*tau}); linear v*tau at c<=0.
/// Matches hit_vfx_pass's spark travel formula.
inline float damped_travel(float v, float c, float tau) {
    return (c > 1e-6f) ? (v / c) * (1.0f - std::exp(-c * tau)) : v * tau;
}

/// Four world-space corners of a particle quad. When length<=0 it is a
/// camera-facing square of half-extent `half_width`. When length>0 the quad's
/// long axis runs along `vel_axis` (length = the streak length) and its short
/// axis is the camera-facing perpendicular (half-extent `half_width`).
/// Corner order: 0=(-1,-1) 1=(+1,-1) 2=(+1,+1) 3=(-1,+1) in (right,up) space.
/// This is the GL-free reference mirrored by hit_vfx.vert's streak path.
inline std::array<glm::vec3, 4> streak_quad(const glm::vec3& center,
                                            const glm::vec3& vel_axis,
                                            float length, float half_width,
                                            const glm::vec3& cam_right,
                                            const glm::vec3& cam_up) {
    glm::vec3 right, up;
    if (length > 1e-6f && glm::length(vel_axis) > 1e-6f) {
        glm::vec3 axis = glm::normalize(vel_axis);
        glm::vec3 view = glm::normalize(glm::cross(cam_right, cam_up));  // camera forward
        glm::vec3 perp = glm::cross(axis, view);
        float pl = glm::length(perp);
        right = (pl > 1e-6f) ? (perp / pl) * half_width : cam_right * half_width;
        up    = axis * length;
    } else {
        right = cam_right * half_width;
        up    = cam_up * half_width;
    }
    return {
        center - right - up,   // (-1,-1)
        center + right - up,   // (+1,-1)
        center + right + up,   // (+1,+1)
        center - right + up,   // (-1,+1)
    };
}
```
Add `#include <array>` at the top of `particle_math.h` if absent.

- [ ] **Step 5: Run to verify it passes**

Run: `cmake --build build -j 2>&1 | tail -5 && ctest --test-dir build -R ParticleMath --output-on-failure 2>&1 | tail -20`
Expected: build clean; all `ParticleMath.*` tests pass (incl. the two new).

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h \
        native/src/renderer/include/renderer/particle_math.h \
        native/tests/renderer/particle_math_test.cc
git commit -m "feat(particles): damping + tail_length fields; damped_travel + streak_quad math"
```

---

## Task 2: Streak shader path + ParticlePass damping/streak

**Files:**
- Modify: `native/src/renderer/shaders/hit_vfx.vert`
- Modify: `native/src/renderer/particle_pass.cc`
- Modify: `native/tests/renderer/particle_pass_test.cc`

**SHADER NOTE:** editing `.vert` requires a **cmake reconfigure** (`cmake -B build -S .`), not just `--build` (per CLAUDE.md — shaders are embedded at configure time).

- [ ] **Step 1: Extend the shared billboard shader**

Replace `native/src/renderer/shaders/hit_vfx.vert` with the streak-capable version (adds `u_streak_axis` + `u_streak_length`; length 0 = the exact current billboard):
```glsl
#version 330 core
layout(location = 0) in vec2 a_corner;   // unit-quad corner: (-1,-1)..(+1,+1)

uniform mat4  u_view_proj;
uniform vec3  u_camera_right;
uniform vec3  u_camera_up;
uniform vec3  u_world_position;
uniform float u_size;
uniform vec3  u_streak_axis;    // world-space velocity direction (streak long axis)
uniform float u_streak_length;  // 0 => camera-facing billboard (default)

out vec2 v_uv;

void main() {
    vec3 right;
    vec3 up;
    if (u_streak_length > 0.0 && length(u_streak_axis) > 1e-6) {
        vec3 axis = normalize(u_streak_axis);
        vec3 view = normalize(cross(u_camera_right, u_camera_up));  // camera forward
        vec3 perp = cross(axis, view);
        float pl = length(perp);
        right = (pl > 1e-6) ? (perp / pl) * u_size : u_camera_right * u_size;
        up    = axis * u_streak_length;
    } else {
        right = u_camera_right * u_size;
        up    = u_camera_up    * u_size;
    }
    vec3 world_pos = u_world_position + right * a_corner.x + up * a_corner.y;
    gl_Position = u_view_proj * vec4(world_pos, 1.0);
    v_uv = a_corner * 0.5 + 0.5;
}
```

- [ ] **Step 2: Apply damping + streak in `particle_pass.cc`**

In the per-particle loop:
(a) Change the directed-travel term to use `damped_travel`. The current code is:
```cpp
glm::vec3 pos = particle_world_pos(emit_pos_world, dir, e.emit_vel_world,
                                   e.emit_velocity, e.inherit, tau);
```
`particle_world_pos` uses `emit_velocity * tau` internally. To apply damping without changing that helper's other callers, compute the directed displacement here instead. Replace the directed term: pass an **effective velocity** so the directed part is damped. Simplest correct approach — add a damped variant call:
```cpp
const float directed = damped_travel(e.emit_velocity, e.damping, tau);
glm::vec3 pos = emit_pos_world + dir * directed
              - e.emit_vel_world * ((1.0f - e.inherit) * tau);   // A2 inherit trail
pos += emit_radius_offset(e.emit_radius, jit, i);
if (e.random_velocity_speed > 0.0f) {
    const glm::vec2 rv_hash = hash3(emit_pos_world, i + 7919);
    const glm::vec3 rv_dir  = random_cone_dir(emit_dir_world, e.random_velocity_cone, rv_hash);
    pos += rv_dir * (damped_travel(e.random_velocity_speed, e.damping, tau));  // random also damped
}
```
(This reproduces A1/A2 exactly when `damping==0`, since `damped_travel(v,0,τ)==v*τ`.)

(b) Before the `glDrawArrays`, set the streak uniforms:
```cpp
if (e.tail_length > 0.0f) {
    const float speed = e.emit_velocity * std::exp(-e.damping * tau);  // damped speed
    shader.set_vec3 ("u_streak_axis",   dir);
    shader.set_float("u_streak_length", e.tail_length * speed);
} else {
    shader.set_float("u_streak_length", 0.0f);
}
```
Set `u_streak_length` to 0 once before the emitter loop too (so non-streak emitters that never set it are safe), and reset to 0 for `tail_length==0` emitters as shown.

- [ ] **Step 3: Add streak + damping + byte-identity FrameTests**

Add to `native/tests/renderer/particle_pass_test.cc` (mirror the existing fixture):
```cpp
TEST(ParticlePass, StreakAndDampingRenderCleanly) {
    // [same offscreen fixture as RendersWithoutGlError]
    // Emitter A: tail_length>0 + damping>0 + emit_velocity>0 => streaks, no GL error.
    //   emitters[0].tail_length = 0.2f; emitters[0].damping = 1.0f;
    //   emitters[0].emit_velocity = 2.0f; emitters[0].effect_age = 0.3f;
    //   pass.render(...); EXPECT_EQ(glGetError(), GL_NO_ERROR);
    // Emitter B (separate render): tail_length=0 && damping=0 => identical draw path
    //   to A1 (no crash; this is the byte-identity guard).
    GTEST_SKIP() << "fill offscreen fixture per RendersWithoutGlError";
}
```
Implementer: replace the `GTEST_SKIP` with the real fixture (copy from `RendersWithoutGlError`), asserting `GL_NO_ERROR` for a streak+damped emitter and for a `tail_length=0,damping=0` emitter. Keep the skip predicate for asset-less environments.

- [ ] **Step 4: Reconfigure (shader changed), build, test**

Run: `cmake -B build -S . >/dev/null 2>&1 && cmake --build build -j 2>&1 | tail -8 && ctest --test-dir build -R "Particle" --output-on-failure 2>&1 | tail -20`
Expected: build clean; `ParticleMath` + `ParticlePass` tests pass or skip. The existing `RendersWithoutGlError` / `EmptyListProducesNoGlError` must still pass (additive change).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/hit_vfx.vert native/src/renderer/particle_pass.cc native/tests/renderer/particle_pass_test.cc
git commit -m "feat(particles): damped travel + velocity-aligned streak rendering (shared shader)"
```

---

## Task 3: Host binding fields

**Files:**
- Modify: `native/src/host/host_bindings.cc`

- [ ] **Step 1: Read the two new keys in `set_particle_emitters`**

After the A2 field reads (`random_velocity_speed`), add:
```cpp
e.damping     = d.contains("damping") ? d["damping"].cast<float>() : 0.0f;
e.tail_length = d.contains("tail_length") ? d["tail_length"].cast<float>() : 0.0f;
```

- [ ] **Step 2: Build + verify binding accepts the keys**

Run: `cmake --build build -j 2>&1 | tail -5 && uv run python -c "import sys; sys.path.insert(0,'build/python'); import _dauntless_host as h; h.set_particle_emitters([{'emit_pos':(0,0,0),'emit_dir':(0,-1,0),'emit_vel_world':(0,0,0),'inherit':1.0,'emit_velocity':1.0,'angle_variance':0.0,'emit_life':1.0,'emit_life_variance':0.0,'emit_frequency':0.05,'effect_age':0.0,'stop_age':1e30,'draw_old_to_new':1,'texture_path':'','damping':1.0,'tail_length':0.2}]); print('OK')"`
Expected: prints `OK` (the binding accepts the new keys; module name is `_dauntless_host`).

- [ ] **Step 3: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(particles): host binding reads damping + tail_length"
```

---

## Task 4: `SparkParticleController` + descriptor emission

**Files:**
- Modify: `engine/appc/particles.py`
- Test: `tests/unit/test_particles_spark.py`

- [ ] **Step 1: Write the failing test (create the file)**

```python
# tests/unit/test_particles_spark.py
from engine.appc import particles as P
from engine.appc.particles import SparkParticleController, AnimTSParticleController


def test_spark_constructor_maps_three_args():
    c = SparkParticleController(3.2, 1.0, 0.005)
    assert c._effect_life_time == 3.2     # total_life
    assert c._emit_frequency == 0.005     # emit_rate
    assert c._duration == 1.0             # duration


def test_spark_setters_round_trip():
    c = SparkParticleController(1.0, 1.0, 0.005)
    c.SetDamping(0.3); c.SetTailLength(0.2)
    c.SetEmitVelocity(2.5); c.AddColorKey(0.0, 1.0, 1.0, 0.8)
    assert c._damping == 0.3 and c._tail_length == 0.2
    assert c._emit_velocity == 2.5
    assert c._color_keys == [(0.0, 1.0, 1.0, 0.8)]


def test_descriptor_emits_damping_and_tail_for_spark():
    P.reset()
    c = SparkParticleController(2.0, 1.0, 0.005)
    c.SetDamping(0.3); c.SetTailLength(0.1)
    c.SetEmitPositionAndDirection((0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    c.CreateTarget("data/rough.tga"); c.AddSizeKey(0.0, 0.04)
    P.EffectAction_Create(c).Start()
    P.advance(0.1)
    d = P.snapshot_descriptors()[0]
    assert d["damping"] == 0.3
    assert d["tail_length"] == 0.1


def test_descriptor_zero_damping_tail_for_plain_controller():
    P.reset()
    c = AnimTSParticleController()
    c.SetEmitPositionAndDirection((0.0, 0.0, 0.0), (0.0, -1.0, 0.0))
    c.CreateTarget("data/Textures/Effects/ExplosionB.tga"); c.AddSizeKey(0.0, 1.0)
    P.EffectAction_Create(c).Start()
    P.advance(0.1)
    d = P.snapshot_descriptors()[0]
    assert d["damping"] == 0.0 and d["tail_length"] == 0.0


def test_duration_caps_emission_stop_age():
    # emission stops at `duration`; controller lives to total_life.
    c = SparkParticleController(5.0, 1.0, 0.005)
    c.SetEmitLife(0.5)
    c._effect_age = 2.0
    # effective stop should be <= duration (1.0), so by age 2.0 emission has ceased
    assert c._effective_stop_age() <= 1.0
```

Run: `uv run pytest tests/unit/test_particles_spark.py -q` → expect FAIL (ImportError SparkParticleController).

- [ ] **Step 2: Implement `SparkParticleController` + descriptor + duration mapping**

In `engine/appc/particles.py`:

(a) Add the class (after `AnimTSParticleController`):
```python
class SparkParticleController(AnimTSParticleController):
    """Spark/debris particles: damped ballistic motion + a motion-streak tail.
    SDK ctor is SparkParticleController_Create(total_life, duration, emit_rate)."""
    def __init__(self, total_life=1.0, duration=1.0, emit_rate=0.005):
        super().__init__()
        self._effect_life_time = total_life   # ctor arg 1
        self._emit_frequency = emit_rate      # ctor arg 3
        self._duration = duration             # ctor arg 2 — emission window
        self._damping = 0.0
        self._tail_length = 0.0

    def SetDamping(self, d):    self._damping = d
    def SetTailLength(self, l): self._tail_length = l


def SparkParticleController_Create(total_life=1.0, duration=1.0, emit_rate=0.005):
    return SparkParticleController(total_life, duration, emit_rate)
```

(b) Make `_effective_stop_age` honor `duration`. The current `AnimTSParticleController._effective_stop_age` is:
```python
    def _effective_stop_age(self):
        explicit = self._stop_age if self._stop_age is not None else float("inf")
        return min(explicit, self._effect_life_time)
```
Change it to also fold in an optional `_duration` (present only on sparks):
```python
    def _effective_stop_age(self):
        explicit = self._stop_age if self._stop_age is not None else float("inf")
        cap = min(explicit, self._effect_life_time)
        duration = getattr(self, "_duration", None)
        if duration is not None:
            cap = min(cap, duration)
        return cap
```
(Non-spark controllers have no `_duration`, so `getattr` returns None and behavior is unchanged.)

(c) In `_descriptor_for`, add the two keys (use `getattr` with 0.0 default so plain controllers emit zeros):
```python
        "damping":     float(getattr(c, "_damping", 0.0)),
        "tail_length": float(getattr(c, "_tail_length", 0.0)),
```

Run: `uv run pytest tests/unit/test_particles_spark.py -q` → expect 5 passed.

- [ ] **Step 3: Regression (focused only — NEVER the whole suite; it OOMs)**

Run: `uv run pytest tests/unit/test_particles_controller.py tests/unit/test_particles_registry.py tests/unit/test_particles_explosion_fields.py tests/unit/test_particle_backend.py tests/integration/test_particles_host_loop.py -q`
Expected: all pass (the `_effective_stop_age` change is backward-compatible; new descriptor keys are additive).

- [ ] **Step 4: Commit**

```bash
git add engine/appc/particles.py tests/unit/test_particles_spark.py
git commit -m "feat(particles): SparkParticleController (damping, tail, duration->stop_age) + descriptor fields"
```

---

## Task 5: App wiring + SDK-unmodified proof + death-debris end-to-end

**Files:**
- Modify: `App.py`
- Modify: `tests/unit/test_particles_spark.py`
- Modify: `tests/integration/test_particles_host_loop.py`

- [ ] **Step 1: Write the failing SDK-unmodified + end-to-end tests**

Append to `tests/unit/test_particles_spark.py`:
```python
def test_create_weapon_sparks_runs_unmodified():
    import App, Effects
    App._stub_tracker.clear()
    P.reset()
    class FakeNode: pass
    class FakeTarget:
        def GetNode(self): return FakeNode()
    class FakeEvent:
        def GetTargetObject(self): return FakeTarget()
        def GetObjectHitPoint(self): return (0.0, 0.0, 0.0)
        def GetObjectHitNormal(self): return (0.0, 1.0, 0.0)
    action = Effects.CreateWeaponSparks(1.0, FakeEvent(), object())
    action.Start()
    assert P.active_count() == 1
    ctrl = P._active[0]
    assert isinstance(ctrl, SparkParticleController)
    assert ctrl._tail_length > 0.0          # SetTailLength was honoured
    assert ctrl._damping == 0.3             # CreateWeaponSparks sets SetDamping(0.3)
    names = {row[0] for row in App._stub_tracker.report()}
    assert "SparkParticleController_Create" not in names


def test_create_debris_sparks_runs_unmodified():
    import Effects
    P.reset()
    action = Effects.CreateDebrisSparks(1.0, object(), 0, object())
    action.Start()
    assert P.active_count() == 1
    ctrl = P._active[0]
    assert isinstance(ctrl, SparkParticleController)
    assert ctrl._texture_path.endswith("smooth.tga")
    assert ctrl._tail_length > 0.0
```
Run: `uv run pytest tests/unit/test_particles_spark.py -q` → the two new tests FAIL (`SparkParticleController_Create` is still the App `_NamedStub`, so `CreateDebrisSparks` builds a stub, not a `SparkParticleController`).

- [ ] **Step 2: Wire `SparkParticleController_Create` into `App.py`**

Add it to the existing `from engine.appc.particles import (...)` block:
```python
from engine.appc.particles import (
    AnimTSParticleController_Create,
    ExplosionPlumeController_Create,
    SparkParticleController_Create,
    EffectAction_Create,
    TGSequence_Create,
    TGAction_CreateNull,
    EffectController_GetEffectLevel,
    EffectController,
)
```
(Keep whatever names are already imported; just add `SparkParticleController_Create`.)

Run: `uv run pytest tests/unit/test_particles_spark.py -q` → expect 7 passed.

- [ ] **Step 3: End-to-end — `ObjectExploding` now registers real sparks**

There is already a death-sequence probe at `tests/unit/test_particles_death_probe.py`. Add a focused assertion there (or in `test_particles_host_loop.py`). Append to `tests/integration/test_particles_host_loop.py`:
```python
def test_object_exploding_registers_real_debris_sparks():
    import App, Effects
    from engine.appc import particles as P
    from engine.appc.particles import SparkParticleController
    P.reset()
    class FakeNode: pass
    class FakeSet:
        def GetName(self): return "test"
        def GetEffectRoot(self): return FakeNode()
        def GetNode(self): return FakeNode()
    class FakeObj:
        def GetRandomPointOnModel(self): return (0.0, 0.0, 0.0)
        def GetRadius(self): return 10.0
        def GetObjID(self): return 1
        def GetNode(self): return FakeNode()
        def GetContainingSet(self): return FakeSet()
        def GetLifeTime(self): return 5.0
        def SetLifeTime(self, t): pass
    # DamageableObject_Cast(FakeObj) must return the object; if the SDK cast
    # returns None for a non-engine object, the death path early-returns. Use the
    # same FakeObj the existing death-probe test uses if it differs.
    Effects.ObjectExploding(FakeObj())
    # At least one real SparkParticleController is now live (debris sparks),
    # proving the A2 silent-stub gap is closed.
    assert any(isinstance(c, SparkParticleController) for c in P._active)
```
IMPORTANT: reuse the exact `FakeObj`/`FakeSet` shape from `tests/unit/test_particles_death_probe.py` (it already drives `ObjectExploding` successfully) so this test doesn't diverge. If `DamageableObject_Cast` rejects the fake, copy the probe's working fake verbatim.

Run: `uv run pytest tests/integration/test_particles_host_loop.py -q` → expect pass.

- [ ] **Step 4: Regression**

Run: `uv run pytest tests/unit/test_particles_spark.py tests/unit/test_particles_death_probe.py tests/unit/test_particles_sequence.py tests/integration/test_host_loop_m3gameflow.py -q`
Expected: all pass (m3gameflow now additionally spawns real spark controllers on deaths — must not raise).

- [ ] **Step 5: Commit**

```bash
git add App.py tests/unit/test_particles_spark.py tests/integration/test_particles_host_loop.py
git commit -m "feat(particles): wire SparkParticleController_Create; CreateWeaponSparks/DebrisSparks unmodified; death debris renders"
```

---

## Task 6: Reconcile `hit_vfx` impact sparks to the shared streak look

**Files:**
- Modify: `native/src/renderer/hit_vfx_pass.cc`
- Modify: `native/tests/renderer/` (re-baseline the hit_vfx spark GL test if one asserts spark shape)

- [ ] **Step 1: Route the `hit_vfx` spark draw through the streak uniforms**

In `hit_vfx_pass.cc`'s spark loop, the current per-spark draw is:
```cpp
const glm::vec3 pos = origin + dir * travel;
const float spark_size  = kSparkSize * (1.0f - life_t);
const float spark_alpha = 1.0f - life_t;
shader.set_vec3 ("u_world_position", pos);
shader.set_float("u_size",           spark_size);
shader.set_float("u_alpha",          spark_alpha);
glDrawArrays(GL_TRIANGLES, 0, 6);
```
Make it a streak: set the streak axis to the spark's travel direction `dir` and a length proportional to the damped speed. Add a `kSparkTailLength` constant near the other `kSpark*` constants:
```cpp
constexpr float kSparkTailLength = 0.15f;   // streak length per unit speed (tune-by-eye)
```
Then in the draw:
```cpp
const glm::vec3 pos = origin + dir * travel;
const float spark_size  = kSparkSize * (1.0f - life_t);
const float spark_alpha = 1.0f - life_t;
const float speed = kSparkSpeed * std::exp(-kSparkDamping * age);  // damped speed
shader.set_vec3 ("u_world_position", pos);
shader.set_float("u_size",           spark_size);
shader.set_float("u_alpha",          spark_alpha);
shader.set_vec3 ("u_streak_axis",    dir);
shader.set_float("u_streak_length",  kSparkTailLength * speed);
glDrawArrays(GL_TRIANGLES, 0, 6);
```

- [ ] **Step 2: Ensure the impact-flash billboard is NOT a streak**

Earlier in `HitVfxPass::render`, before/at the main impact-flash billboard draw (the `glBindTexture(... texture_->id())` block that draws the flash quad), set:
```cpp
shader.set_float("u_streak_length", 0.0f);
```
so the flash quad stays a camera-facing billboard (only the spark sub-quads become streaks). Set it once before the flash draw; the spark loop overrides per spark.

- [ ] **Step 3: Reconfigure (shader was changed in Task 2), build, run hit_vfx + particle tests**

Run: `cmake -B build -S . >/dev/null 2>&1 && cmake --build build -j 2>&1 | tail -6 && ctest --test-dir build -R "Particle|HitVfx|hit_vfx" --output-on-failure 2>&1 | tail -25`
Expected: build clean; particle + hit_vfx GL tests pass. If a hit_vfx test asserted the spark sub-quad's exact shape/extent (square), re-baseline it to accept the streak (the tests assert `GL_NO_ERROR` + presence per the suite's convention — update any exact-extent assertion with a comment noting the A3 streak reconciliation).

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/hit_vfx_pass.cc native/tests/renderer/
git commit -m "feat(particles): reconcile hit_vfx impact sparks to shared damped-streak look"
```

---

## Final verification

- [ ] **Python focused suite + Spec B/A2 regression (NEVER the whole suite — it OOMs >100GB):**

Run:
```
uv run pytest tests/unit/test_particles_controller.py tests/unit/test_particles_registry.py \
  tests/unit/test_particles_explosion_fields.py tests/unit/test_particles_spark.py \
  tests/unit/test_particle_backend.py tests/unit/test_particles_sequence.py \
  tests/unit/test_particles_death_probe.py tests/integration/test_particles_host_loop.py \
  tests/unit/test_subsystem_emitters_transitions.py tests/integration/test_host_loop_m3gameflow.py -q
```
Expected: ALL PASS.

- [ ] **Native build + renderer particle/hit_vfx tests:**

Run: `cmake -B build -S . >/dev/null 2>&1 && cmake --build build -j 2>&1 | tail -3 && ctest --test-dir build -R "Particle|HitVfx|hit_vfx" 2>&1 | tail -4`
Expected: build clean; all pass.

---

## Notes for the implementer

- **Test memory:** never run the bare `uv run pytest` — it uses >100 GB RAM and freezes macOS. Use the focused lists above.
- **Shader reconfigure:** Tasks 2 & 6 change `hit_vfx.vert`, which is embedded at configure time — run `cmake -B build -S .` before `--build`, not just `--build` (CLAUDE.md).
- **Additive guarantee:** `damping=0` && `tail_length=0` ⇒ the `ParticlePass` and `hit_vfx` flash are byte-identical to pre-A3. The only intended visual change is `hit_vfx` *sparks* becoming streaks (Task 6) — the accepted reconciliation blast radius.
- **No `actions.py` changes.** Death explosions still fire simultaneously (Phase-1 synchronous model); A3 only makes them render real debris sparks. Timed cascades are the separate, deferred engine project.
- **Art is tune-by-eye:** `kSparkTailLength`, the spark `tail_length`/`damping` from the SDK factories, sprite choices — all parking-lot.
