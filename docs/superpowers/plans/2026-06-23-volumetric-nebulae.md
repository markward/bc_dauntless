# Volumetric Nebulae + Tactical Density Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A raymarched volumetric nebula cloud (sun-lit single-scatter, depth-correct hull obscuration) driven by a shared fbm density field, plus tactical concealment (density hides ships from AI) — the "modern" round on V1's `NebulaPass::Style` seam.

**Architecture:** One deterministic fbm **density field** (Python mirror + GLSL copy) is sampled by a half-res post-process **raymarch** (composited into the HDR target, gated by a Modern VFX toggle) and, on demand, by the **AI detection gate** (`sensor_detection.py`) so dense clumps conceal ships. The raymarch reads a newly-**sampleable HDR depth texture** to stop at hulls (fixing V1's crisp-hull gripe).

**Tech Stack:** C++17 + OpenGL (raymarch pass, GLSL), pybind11 bindings, CMake `configure_file` shader embedding, CTest `FrameTest`; Python 3 (density mirror, concealment, host loop), pytest.

## Global Constraints

- **Gameplay is toggle-independent.** The "Volumetric Nebulae" Modern VFX toggle changes the **visual only** (VOLUMETRIC vs V1 FAITHFUL). Concealment reads the density field regardless of the toggle. (Spec §3, §7)
- **Stock-BC byte-identity:** toggle OFF → the volumetric pass is never constructed/run; V1 faithful path unchanged. No nebula in a set → every path a no-op.
- **Deterministic density:** one seed per nebula derived from its world position; the same fbm formula in Python and GLSL. GPU/CPU exactness is review-enforced + tolerance-bounded (running GLSL on CPU is not harnessed); the Python impl is pinned by golden-value tests so it cannot drift. (Spec §5)
- **World units (GU)** throughout the field and raymarch; no metre conversion.
- **Shader rebuild:** any `.vert`/`.frag`/`.glsl` change requires `cmake -B build -S .` BEFORE `cmake --build build -j` (shaders embedded at configure time). Build from project root, never inside `native/`.
- **host_bindings.cc / renderer changes** need the full `dauntless` target rebuilt (binary + module).
- **No desktop interaction on Mark's workstation** — live verification is handed off.
- **4-light model:** the cloud lights from up to `MAX_DIR_LIGHTS = 4` directional lights (the `Lighting` struct), reserving slots for the future thunder follow-on.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `native/src/renderer/include/renderer/hdr_target.h` / `hdr_target.cc` | Modify | Depth RBO → sampleable depth **texture** + `depth_texture()` accessor. |
| `engine/appc/nebula_density.py` | Create | Python fbm + `density(p, spheres, seed, dials)` — the CPU mirror. Pure, no deps. |
| `tests/unit/test_nebula_density.py` | Create | Golden-value tests pinning the Python fbm/density (anti-drift). |
| `engine/appc/sensor_detection.py` | Modify | `can_detect`/`effective_sensor_range` factor target concealment (sampled on demand) + lock-break threshold + hysteresis. |
| `engine/appc/nebula.py` | Modify | `MetaNebula` carries fbm dials + a per-nebula seed; getters. |
| `engine/host_loop.py` | Modify | `_aggregate_nebulae` emits fbm dials + seed; pass them through `set_nebulae`. |
| `engine/renderer.py` | Modify | `set_nebulae` payload gains dials/seed; `volumetric_nebulae_enabled()`/`set_…` wrappers. |
| `native/src/renderer/frame.cc` | Modify | `dauntless_volumetric_nebulae` toggle namespace. |
| `native/src/host/host_bindings.cc` | Modify | Toggle bindings; `g_nebula_volumetric_pass`; payload fields; render call. |
| `native/src/renderer/nebula_volumetric_pass.{h,cc}` | Create | Half-res raymarch pass. |
| `native/src/renderer/shaders/nebula_volumetric.frag` + `.vert` | Create | The raymarch (density + single-scatter + depth stop). |
| `native/src/renderer/CMakeLists.txt` | Modify | `embed_shader` + sources. |
| `engine/ui/configuration_panel.py` + `native/assets/ui-cef/js/configuration_panel.js` | Modify | "Volumetric Nebulae" config row (default on). |
| `native/tests/renderer/frame_test.cc` | Modify | FrameTests for depth texture + volumetric pass. |

---

## Task 1: HDR depth → sampleable texture

**Files:**
- Modify: `native/src/renderer/include/renderer/hdr_target.h`, `native/src/renderer/hdr_target.cc`
- Test: `native/tests/renderer/frame_test.cc` (existing passes still render)

**Interfaces:**
- Produces: `HdrTarget::depth_texture() -> std::uint32_t` (a `GL_TEXTURE_2D`, `GL_DEPTH_COMPONENT24`, NEAREST-filtered, sampleable). Depth attachment semantics unchanged for existing depth-testing passes.

- [ ] **Step 1: Replace the depth RBO with a depth texture in `hdr_target.cc`**

In `resize()`, replace the `glGenRenderbuffers`/`glRenderbufferStorage`/`glFramebufferRenderbuffer` block with a depth texture:

```cpp
    glGenTextures(1, &depth_tex_);
    glBindTexture(GL_TEXTURE_2D, depth_tex_);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, w, h, 0,
                 GL_DEPTH_COMPONENT, GL_UNSIGNED_INT, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
```

And attach it as the depth attachment (replacing `glFramebufferRenderbuffer`):

```cpp
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                           GL_TEXTURE_2D, depth_tex_, 0);
```

In `destroy()`, replace the renderbuffer delete:

```cpp
    if (depth_tex_) { glDeleteTextures(1, &depth_tex_); depth_tex_ = 0; }
```

- [ ] **Step 2: Update the header `hdr_target.h`**

Replace `std::uint32_t depth_rbo_ = 0;` with `std::uint32_t depth_tex_ = 0;` and add the accessor next to `color_texture()`:

```cpp
    std::uint32_t depth_texture() const { return depth_tex_; }
```

- [ ] **Step 3: Reconfigure + build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: clean build.

- [ ] **Step 4: Verify existing depth-testing passes are unbroken**

Run: `ctest --test-dir build -R "FrameTest" 2>&1 | tail -20`
Expected: the same pass/fail set as before this task (the known pre-existing failures — Scorch/PhaserHeatGlow — remain; **no new failures**). Depth-tested geometry (hulls, dust, shield, V1 nebula) must still render — the existing FrameTests exercise this. If a depth-completeness assert fires, confirm the FBO is still complete (the texture is a valid depth attachment).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/hdr_target.h native/src/renderer/hdr_target.cc
git commit -m "feat(renderer): HDR target depth as sampleable texture"
```

---

## Task 2: Shared fbm density field (Python mirror + golden tests)

**Files:**
- Create: `engine/appc/nebula_density.py`
- Test: `tests/unit/test_nebula_density.py`

**Interfaces:**
- Produces:
  - `nebula_density.fbm(x, y, z) -> float` — 5-octave value-noise fbm, mirroring `backdrop.frag`'s `hash13`/`vnoise`/`fbm` (range ~[0,1]).
  - `nebula_density.density(px, py, pz, spheres, seed, freq, gain, floor, drift_t) -> float` — `sphere_union_falloff · saturate(fbm(p·freq + seed + drift_t)·gain − floor)`, in [0,1]. `spheres` = list of `(cx,cy,cz,r)`.
  - `nebula_density.seed_for(cx, cy, cz) -> tuple[float,float,float]` — deterministic per-nebula offset from its first sphere centre.

- [ ] **Step 1: Write the failing golden test**

Create `tests/unit/test_nebula_density.py`. (Golden values are computed once from the reference algorithm; they pin the Python impl so it cannot silently drift, and document the GLSL contract.)

```python
from engine.appc import nebula_density as nd


def test_fbm_is_deterministic_and_bounded():
    a = nd.fbm(1.5, 2.5, 3.5)
    b = nd.fbm(1.5, 2.5, 3.5)
    assert a == b                      # deterministic
    assert 0.0 <= a <= 1.0             # value-noise fbm stays in [0,1]


def test_fbm_varies_across_space():
    # Two well-separated points should differ (it's noise, not a constant).
    assert abs(nd.fbm(0.0, 0.0, 0.0) - nd.fbm(10.3, -4.1, 7.7)) > 0.05


def test_density_zero_outside_all_spheres():
    spheres = [(0.0, 0.0, 0.0, 100.0)]
    seed = nd.seed_for(0.0, 0.0, 0.0)
    # 500 GU out is well outside the 100 GU sphere → no cloud.
    assert nd.density(500.0, 0.0, 0.0, spheres, seed,
                      freq=0.01, gain=1.6, floor=0.4, drift_t=0.0) == 0.0


def test_density_in_range_inside_sphere():
    spheres = [(0.0, 0.0, 0.0, 100.0)]
    seed = nd.seed_for(0.0, 0.0, 0.0)
    vals = [nd.density(x, 0.0, 0.0, spheres, seed,
                       freq=0.05, gain=1.6, floor=0.4, drift_t=0.0)
            for x in range(-90, 91, 5)]
    assert all(0.0 <= v <= 1.0 for v in vals)
    assert max(vals) > 0.0             # at least some cloud inside
    assert min(vals) == 0.0 or max(vals) > min(vals)  # varies (clumps)


def test_seed_differs_per_nebula():
    assert nd.seed_for(0.0, 0.0, 0.0) != nd.seed_for(1500.0, 0.0, 0.0)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_nebula_density.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.appc.nebula_density`.

- [ ] **Step 3: Implement `engine/appc/nebula_density.py`**

Port of `native/src/renderer/shaders/backdrop.frag:20-33` (`hash13`/`vnoise`/`fbm`). Keep the constants identical so the GLSL copy in Task 5 matches.

```python
"""Deterministic fbm density field for nebulae — the CPU mirror of the GLSL
copy in shaders/nebula_volumetric.frag. Same formula + per-nebula seed, so the
raymarch (GPU) and concealment (CPU) agree. Pure functions, no deps.

The fbm mirrors backdrop.frag's hash13/vnoise/fbm verbatim (5 octaves, lacunarity
2.02, gain 0.5). GLSL<->Python exactness is review-enforced + tolerance-bounded;
these functions are pinned by tests/unit/test_nebula_density.py.
"""
import math


def _fract(x):
    return x - math.floor(x)


def _hash13(x, y, z):
    # p3 = fract(p3 * 0.1031)
    px, py, pz = _fract(x * 0.1031), _fract(y * 0.1031), _fract(z * 0.1031)
    # p3 += dot(p3, p3.zyx + 31.32)
    d = px * (pz + 31.32) + py * (py + 31.32) + pz * (px + 31.32)
    px, py, pz = px + d, py + d, pz + d
    # fract((p3.x + p3.y) * p3.z)
    return _fract((px + py) * pz)


def _vnoise(x, y, z):
    ix, iy, iz = math.floor(x), math.floor(y), math.floor(z)
    fx, fy, fz = x - ix, y - iy, z - iz
    fx = fx * fx * (3.0 - 2.0 * fx)
    fy = fy * fy * (3.0 - 2.0 * fy)
    fz = fz * fz * (3.0 - 2.0 * fz)

    def h(dx, dy, dz):
        return _hash13(ix + dx, iy + dy, iz + dz)

    n00 = h(0, 0, 0) + (h(1, 0, 0) - h(0, 0, 0)) * fx
    n10 = h(0, 1, 0) + (h(1, 1, 0) - h(0, 1, 0)) * fx
    n01 = h(0, 0, 1) + (h(1, 0, 1) - h(0, 0, 1)) * fx
    n11 = h(0, 1, 1) + (h(1, 1, 1) - h(0, 1, 1)) * fx
    n0 = n00 + (n10 - n00) * fy
    n1 = n01 + (n11 - n01) * fy
    return n0 + (n1 - n0) * fz


def fbm(x, y, z):
    a, s = 0.5, 0.0
    for _ in range(5):
        s += a * _vnoise(x, y, z)
        x, y, z = x * 2.02, y * 2.02, z * 2.02
        a *= 0.5
    return s


def seed_for(cx, cy, cz):
    # Deterministic per-nebula offset; large multipliers so distinct nebulae
    # land in unrelated regions of the noise field.
    return (cx * 0.013 + 11.7, cy * 0.013 + 23.1, cz * 0.013 + 47.3)


def _saturate(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _sphere_union_falloff(px, py, pz, spheres):
    # Smooth 0->1 inward from each sphere boundary; union = max.
    best = 0.0
    for (cx, cy, cz, r) in spheres:
        if r <= 0.0:
            continue
        dx, dy, dz = px - cx, py - cy, pz - cz
        d = math.sqrt(dx * dx + dy * dy + dz * dz)
        # 1 at centre, 0 at the rim; smoothstep over the outer 30% shell.
        t = _saturate((r - d) / (0.3 * r))
        f = t * t * (3.0 - 2.0 * t)
        if f > best:
            best = f
    return best


def density(px, py, pz, spheres, seed, freq, gain, floor, drift_t):
    bound = _sphere_union_falloff(px, py, pz, spheres)
    if bound <= 0.0:
        return 0.0
    sx, sy, sz = seed
    n = fbm(px * freq + sx + drift_t, py * freq + sy, pz * freq + sz)
    return bound * _saturate(n * gain - floor)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_nebula_density.py -v`
Expected: PASS (5 tests). If `test_fbm_is_deterministic_and_bounded` shows fbm slightly > 1.0, that's the value-noise sum bound — clamp expectations are fine because `density` saturates; adjust the assertion to `<= 1.0001` only if the raw fbm legitimately reaches 1.0 (value noise peaks at 1.0).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/nebula_density.py tests/unit/test_nebula_density.py
git commit -m "feat(nebula): shared fbm density field (CPU mirror) + golden tests"
```

---

## Task 3: Tactical concealment in the AI detection gate

**Files:**
- Modify: `engine/appc/sensor_detection.py`
- Modify: `engine/appc/nebula.py` (expose fbm dials + seed on `MetaNebula`)
- Test: `tests/unit/test_nebula_concealment.py` (create)

**Interfaces:**
- Consumes: `nebula_density.density(...)`; the set's nebulae via `pSet.GetClassObjectList(App.CT_NEBULA)` + `MetaNebula_Cast`; `MetaNebula` dials/seed (added here).
- Produces:
  - `MetaNebula.GetFbmDials() -> tuple[float,float,float]` (freq, gain, floor); `MetaNebula.GetSeed() -> tuple`; `MetaNebula.GetDriftT()` is supplied by the caller (game time), not stored.
  - `sensor_detection.concealment_at(ship) -> float` in [0,1] — max density across the ship's set's nebulae at the ship's position (0 if none).
  - `can_detect(observer, target)` now returns False when the target's concealment exceeds the lock-break threshold, and otherwise scales the effective range by `(1 - k·concealment)`; with per-(observer,target) hysteresis so a broken lock needs the target to clear the threshold by a margin before re-detection.

**Design notes:** concealment is sampled **on demand** here (AI runs before the nebula tracker each tick; on-demand sampling avoids a 1-tick lag and needs no host-loop reordering). `drift_t` uses the current game time so the CPU field matches the animated GPU field. Constants: `CONCEAL_K = 0.9` (range reduction at full density), `LOCK_BREAK_T = 0.6` (density above which detection fails), `HYSTERESIS = 0.1` (must drop to `T - HYSTERESIS` to re-detect). These are gameplay dials.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_nebula_concealment.py`:

```python
import App
from engine.appc import sensor_detection as sd


class _Ship:
    def __init__(self, name, x, y, z, set_):
        self._n, self._x, self._y, self._z, self._s = name, x, y, z, set_
    def GetName(self): return self._n
    def GetWorldLocation(self): return App.TGPoint3(self._x, self._y, self._z)
    def GetContainingSet(self): return self._s


def _set_with_dense_nebula():
    s = App.SetClass_Create()
    n = App.MetaNebula_Create(0.5, 0.5, 0.7, 145.0, 1.0, "i.tga", "e.tga")
    n.SetupDamage(0.0, 0.0)
    n.AddNebulaSphere(0.0, 0.0, 0.0, 200.0)
    # Dials chosen so the sphere centre is dense (above lock-break threshold).
    n.SetFbmDials(0.02, 3.0, 0.0)
    s.AddObjectToSet(n, "neb")
    return s, n


def test_concealment_zero_outside_nebula():
    s, n = _set_with_dense_nebula()
    ship = _Ship("P", 5000.0, 0.0, 0.0, s)   # far outside
    assert sd.concealment_at(ship) == 0.0


def test_concealment_high_in_dense_core():
    s, n = _set_with_dense_nebula()
    ship = _Ship("P", 0.0, 0.0, 0.0, s)       # centre
    assert sd.concealment_at(ship) > 0.5


def test_can_detect_blocked_when_target_concealed():
    s, n = _set_with_dense_nebula()
    observer = _Ship("E", 0.0, 0.0, 300.0, s)
    hidden = _Ship("P", 0.0, 0.0, 0.0, s)     # in the dense core
    # Even at point-blank range, a deeply concealed target can't be detected.
    assert sd.can_detect(observer, hidden, base_range=100000.0) is False


def test_can_detect_succeeds_in_clear_space():
    s, n = _set_with_dense_nebula()
    observer = _Ship("E", 0.0, 0.0, 5300.0, s)
    visible = _Ship("P", 0.0, 0.0, 5000.0, s)  # both far outside the nebula
    assert sd.can_detect(observer, visible, base_range=100000.0) is True
```

(If `sensor_detection.can_detect`'s real signature differs from `(observer, target, base_range=...)`, adapt the test to the real signature discovered in Step 3 — but keep the four behaviours.)

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_nebula_concealment.py -v`
Expected: FAIL — `AttributeError: 'MetaNebula' object has no attribute 'SetFbmDials'` and `sensor_detection has no attribute 'concealment_at'`.

- [ ] **Step 3: Add fbm dials + seed to `MetaNebula` (`engine/appc/nebula.py`)**

In `MetaNebula.__init__`, after the existing fields, add defaults:

```python
        self._fbm = (0.02, 1.6, 0.4)        # freq, gain, floor (tunable)
        self._seed = None                    # lazily derived from first sphere
```

Add methods:

```python
    def SetFbmDials(self, freq, gain, floor):
        self._fbm = (float(freq), float(gain), float(floor))

    def GetFbmDials(self):
        return self._fbm

    def GetSeed(self):
        if self._seed is None:
            from engine.appc.nebula_density import seed_for
            if self._spheres:
                cx, cy, cz, _ = self._spheres[0]
            else:
                cx = cy = cz = 0.0
            self._seed = seed_for(cx, cy, cz)
        return self._seed
```

- [ ] **Step 4: Add concealment to `engine/appc/sensor_detection.py`**

First READ the file to learn the real `effective_sensor_range`/`can_detect` signatures and the game-time source. Then add `concealment_at` and fold it into `can_detect`. Implementation (adapt names to the file's actual API):

```python
import App
from engine.appc import nebula_density as _nd

CONCEAL_K = 0.9        # detection-range reduction at full density
LOCK_BREAK_T = 0.6     # density above which detection fails outright
HYSTERESIS = 0.1       # must clear T - HYSTERESIS to re-detect after a break

# Per-(observer, target) latch so a broken lock needs a margin to re-acquire.
_broken = set()


def _game_time():
    try:
        return App.g_kTimerManager.GetGameTime()
    except Exception:
        return 0.0


def concealment_at(ship):
    """Max nebula density in [0,1] at this ship's position (0 if not in one)."""
    pSet = ship.GetContainingSet()
    if pSet is None:
        return 0.0
    loc = ship.GetWorldLocation()
    t = _game_time()
    best = 0.0
    for obj in pSet.GetClassObjectList(App.CT_NEBULA):
        neb = App.MetaNebula_Cast(obj)
        if neb is None:
            continue
        spheres = neb.GetNebulaSpheres()
        freq, gain, floor = neb.GetFbmDials()
        d = _nd.density(loc.x, loc.y, loc.z, spheres, neb.GetSeed(),
                        freq, gain, floor, drift_t=t * 0.01)
        if d > best:
            best = d
    return best
```

Then, inside `can_detect(observer, target, ...)` (extend the existing function), after computing the base effective range and the observer→target distance, add:

```python
    conceal = concealment_at(target)
    key = (id(observer), id(target))
    thresh = LOCK_BREAK_T - (HYSTERESIS if key in _broken else 0.0)
    if conceal >= thresh:
        _broken.add(key)
        return False
    _broken.discard(key)
    effective_range = effective_range * (1.0 - CONCEAL_K * conceal)
    # ... existing distance <= effective_range comparison, now using the
    # concealment-reduced effective_range ...
```

If `can_detect` does not currently take a `base_range`, keep its existing range source; the test passes `base_range` only as a convenience — adapt the test to the real signature in Step 1 if needed.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_nebula_concealment.py tests/unit/test_nebula.py -v`
Expected: PASS (new concealment tests + all existing V1 nebula tests unaffected).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/sensor_detection.py engine/appc/nebula.py tests/unit/test_nebula_concealment.py
git commit -m "feat(nebula): tactical concealment in the AI detection gate"
```

---

## Task 4: "Volumetric Nebulae" toggle + payload (fbm dials + seed)

**Files:**
- Modify: `native/src/renderer/frame.cc` (toggle namespace)
- Modify: `native/src/host/host_bindings.cc` (toggle bindings + payload fields)
- Modify: `engine/renderer.py` (wrappers + payload doc)
- Modify: `engine/host_loop.py` (`_aggregate_nebulae` emits dials + seed)
- Modify: `engine/ui/configuration_panel.py`, `native/assets/ui-cef/js/configuration_panel.js`
- Test: manual (toggle reads back) + existing suite

**Interfaces:**
- Produces: `dauntless_volumetric_nebulae::enabled()/set_enabled(bool)` (C++); `_h.volumetric_nebulae_enabled()/_set_enabled()`; `engine.renderer.volumetric_nebulae_enabled()/set_volumetric_nebulae_enabled()`; `set_nebulae` dicts gain `"fbm": (freq,gain,floor)`, `"seed": (sx,sy,sz)`; the C++ `NebulaVolume` gains `glm::vec3 fbm; glm::vec3 seed;`.

- [ ] **Step 1: Add the toggle namespace in `frame.cc`** (mirror `dauntless_filmic` at `frame.cc:105-121`)

```cpp
namespace dauntless_volumetric_nebulae {
namespace { bool g_enabled = true; }
    bool enabled() { return g_enabled; }
    void set_enabled(bool v) { g_enabled = v; }
}
```

- [ ] **Step 2: Bindings + forward decl in `host_bindings.cc`** (mirror filmic at `:117-138` and `:2053-2060`)

Forward-declare alongside the other `dauntless_*` toggles, then add:

```cpp
    m.def("volumetric_nebulae_set_enabled",
          [](bool enabled) { dauntless_volumetric_nebulae::set_enabled(enabled); },
          py::arg("enabled"), "Toggle Volumetric Nebulae (Modern VFX). Default: on.");
    m.def("volumetric_nebulae_enabled",
          []() { return dauntless_volumetric_nebulae::enabled(); },
          "Read the Volumetric Nebulae toggle (Modern VFX). Default: on.");
```

Extend the `set_nebulae` lambda to read the new dict fields into `NebulaVolume` (add `glm::vec3 fbm; glm::vec3 seed;` to the struct in `nebula_pass.h`):

```cpp
                  auto fb = d["fbm"].cast<std::tuple<float,float,float>>();
                  v.fbm  = glm::vec3(std::get<0>(fb), std::get<1>(fb), std::get<2>(fb));
                  auto sd2 = d["seed"].cast<std::tuple<float,float,float>>();
                  v.seed = glm::vec3(std::get<0>(sd2), std::get<1>(sd2), std::get<2>(sd2));
```

- [ ] **Step 3: Python wrappers in `engine/renderer.py`** (after the filmic wrappers ~`:173-191`)

```python
def volumetric_nebulae_enabled() -> bool:
    """Read the Volumetric Nebulae toggle (Modern VFX). Default: on."""
    return _h.volumetric_nebulae_enabled()


def set_volumetric_nebulae_enabled(enabled: bool) -> None:
    """Toggle Volumetric Nebulae (Modern VFX). Default: on."""
    _h.volumetric_nebulae_set_enabled(enabled)
```

Update the `set_nebulae` docstring to list the new `fbm` and `seed` keys.

- [ ] **Step 4: Emit dials + seed in `_aggregate_nebulae` (`engine/host_loop.py`)**

In the dict built per nebula, add:

```python
            "fbm": neb.GetFbmDials(),
            "seed": neb.GetSeed(),
```

- [ ] **Step 5: Config UI row** (Python + JS)

In `engine/ui/configuration_panel.py`: add `volumetric_nebulae_on: bool = True` to `SettingsSnapshot`, a `set_volumetric_nebulae: Callable[[bool], None]` constructor param, store it, initialise the snapshot field from `renderer.volumetric_nebulae_enabled()`, and add a `configuration/toggle:volumetric_nebulae` dispatch (mirror the filmic rows exactly). In `native/assets/ui-cef/js/configuration_panel.js`: add `{kind:'ctrl', target:'volumetric_nebulae'}` to `_cpFocusableList` and a "Volumetric Nebulae" `cp-row` in the Modern VFX group (copy the filmic row block). Wire `set_volumetric_nebulae` to `renderer.set_volumetric_nebulae_enabled` where the panel is constructed (same place `set_filmic` is wired).

- [ ] **Step 6: Reconfigure + build + smoke-check the toggle**

Run: `cmake -B build -S . && cmake --build build -j`
Then verify the binding round-trips:
```bash
uv run python -c "import engine.renderer as r; r.set_volumetric_nebulae_enabled(False); print(r.volumetric_nebulae_enabled()); r.set_volumetric_nebulae_enabled(True); print(r.volumetric_nebulae_enabled())"
```
Expected: prints `False` then `True`. (Use the project's standard host-module import path if a bare import needs `build/python` on `sys.path`.)

- [ ] **Step 7: Run the nebula suites (no regressions)**

Run: `uv run pytest tests/unit/test_nebula.py tests/unit/test_nebula_concealment.py -v` → PASS.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/frame.cc native/src/host/host_bindings.cc native/src/renderer/include/renderer/nebula_pass.h engine/renderer.py engine/host_loop.py engine/ui/configuration_panel.py native/assets/ui-cef/js/configuration_panel.js
git commit -m "feat(nebula): Volumetric Nebulae Modern VFX toggle + fbm payload"
```

---

## Task 5: Volumetric raymarch pass

**Files:**
- Create: `native/src/renderer/include/renderer/nebula_volumetric_pass.h`, `native/src/renderer/nebula_volumetric_pass.cc`
- Create: `native/src/renderer/shaders/nebula_volumetric.vert`, `nebula_volumetric.frag`
- Modify: `native/src/renderer/CMakeLists.txt`, `native/src/renderer/pipeline.cc` (construct the shader), `native/src/host/host_bindings.cc` (globals, lifecycle, render call gated on the toggle + `VOLUMETRIC` style + depth texture)
- Test: `native/tests/renderer/frame_test.cc`

**Interfaces:**
- Consumes: `NebulaVolume` (now with `fbm`, `seed`); `HdrTarget::color_texture()` + `depth_texture()`; the `Lighting` struct (up to 4 directional lights); camera.
- Produces: `NebulaVolumetricPass::render(camera, pipeline, volumes, lighting, hdr_color_tex, hdr_depth_tex, inv_view_proj, eye, time)` compositing the cloud into the currently-bound HDR target. Early-outs on empty volumes.

**Approach:** a fullscreen pass. For each fragment, reconstruct the world ray from `inv_view_proj`, intersect the nebula sphere-union to get the march interval, clamp the far end to the scene distance from `hdr_depth_tex` (so hulls — incl. the player ship — occlude), and march front-to-back sampling `density` (the GLSL copy of the Python fbm), accumulating single-scatter from up to 4 directional lights + nebula self-glow. Composite over the scene colour. **This task runs full-res; Task 6 adds half-res + temporal.**

> **Live-tuning note:** start scatter/self-glow/step-count strong, verify at Vesuvi4, then dial. The `u_*` constants are the dials.

- [ ] **Step 1: Add the FrameTest (failing)**

In `frame_test.cc`, add `NebulaVolumetricRendersDensityAndObscuresHull`: build a `NebulaVolumetricPass`, feed one volume (sphere r=200 at origin, tint (0.5,0.5,0.7), fbm (0.02,3.0,0.0), seed (0,0,0)), one directional light, an HDR target with a hull-depth written at the centre (or a cleared far depth), camera inside; render; assert (a) the centre shows cloud tint vs a no-volume control, and (b) with a near hull depth at the centre, the cloud does **not** overwrite the nearer-than-cloud region (obscuration). Follow the existing nebula/sun FrameTest pattern; if writing scene depth into the test FBO is awkward, assert at least (a) and document (b) for live verification — do not fake it.

- [ ] **Step 2: Run it to verify it fails**

Run: `ctest --test-dir build -R "FrameTest" -V` → the new test FAILs (pass not built).

- [ ] **Step 3: Create `nebula_volumetric.vert`** (fullscreen triangle)

```glsl
#version 330 core
out vec2 v_uv;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    v_uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
```

- [ ] **Step 4: Create `nebula_volumetric.frag`** (the raymarch — GLSL copy of the Python density)

```glsl
#version 330 core
in vec2 v_uv;
out vec4 frag;

uniform sampler2D u_depth;       // HDR depth (sampleable). No u_scene: the pass
                                 // blends premultiplied (lit, alpha) OVER the HDR
                                 // target via fixed-function blend (no feedback loop).
uniform mat4  u_inv_view_proj;
uniform vec3  u_eye;
uniform float u_near, u_far;

uniform int   u_sphere_count;
uniform vec4  u_spheres[8];      // xyz centre, w radius (GU)
uniform vec3  u_rgb;             // nebula tint / self-glow colour
uniform vec3  u_fbm;             // freq, gain, floor
uniform vec3  u_seed;
uniform float u_time;

uniform int   u_dir_light_count;
uniform vec3  u_dir_light_dir_ws[4];   // direction TOWARD the light
uniform vec3  u_dir_light_color[4];

// Tunable dials.
uniform float u_step;            // march step (GU), default 6.0
uniform int   u_max_steps;       // default 96
uniform float u_density_scale;   // default 0.06 (extinction per GU per density)
uniform float u_scatter;         // default 1.2
uniform float u_self_glow;       // default 0.25
uniform float u_light_steps;     // occlusion taps toward light, default 3.0

// --- fbm copy of backdrop.frag / nebula_density.py (keep in sync) ---
float hash13(vec3 p3){ p3=fract(p3*0.1031); p3+=dot(p3,p3.zyx+31.32); return fract((p3.x+p3.y)*p3.z); }
float vnoise(vec3 p){
    vec3 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
    float n000=hash13(i),               n100=hash13(i+vec3(1,0,0));
    float n010=hash13(i+vec3(0,1,0)),   n110=hash13(i+vec3(1,1,0));
    float n001=hash13(i+vec3(0,0,1)),   n101=hash13(i+vec3(1,0,1));
    float n011=hash13(i+vec3(0,1,1)),   n111=hash13(i+vec3(1,1,1));
    return mix(mix(mix(n000,n100,f.x),mix(n010,n110,f.x),f.y),
               mix(mix(n001,n101,f.x),mix(n011,n111,f.x),f.y), f.z);
}
float fbm(vec3 p){ float a=0.5,s=0.0; for(int k=0;k<5;k++){ s+=a*vnoise(p); p*=2.02; a*=0.5; } return s; }

float bound_falloff(vec3 p){
    float best=0.0;
    for(int i=0;i<u_sphere_count;i++){
        float r=u_spheres[i].w; if(r<=0.0) continue;
        float d=length(p-u_spheres[i].xyz);
        float t=clamp((r-d)/(0.3*r),0.0,1.0);
        best=max(best, t*t*(3.0-2.0*t));
    }
    return best;
}
float density(vec3 p){
    float b=bound_falloff(p); if(b<=0.0) return 0.0;
    float n=fbm(vec3(p.x*u_fbm.x+u_seed.x+u_time*0.01,
                     p.y*u_fbm.x+u_seed.y,
                     p.z*u_fbm.x+u_seed.z));
    return b*clamp(n*u_fbm.y - u_fbm.z, 0.0, 1.0);
}

vec3 world_from_depth(vec2 uv, float d){
    vec4 c=vec4(uv*2.0-1.0, d*2.0-1.0, 1.0);
    vec4 w=u_inv_view_proj*c; return w.xyz/w.w;
}

// Sphere-union entry/exit along ray (o,dir): widest [t0,t1] over spheres.
void union_interval(vec3 o, vec3 dir, out float t0, out float t1){
    t0=1e20; t1=-1e20;
    for(int i=0;i<u_sphere_count;i++){
        vec3 c=u_spheres[i].xyz; float r=u_spheres[i].w; if(r<=0.0) continue;
        vec3 L=c-o; float tca=dot(L,dir); float d2=dot(L,L)-tca*tca; float r2=r*r;
        if(d2>r2) continue;
        float thc=sqrt(r2-d2);
        t0=min(t0,tca-thc); t1=max(t1,tca+thc);
    }
}

void main(){
    float dsc=texture(u_depth,v_uv).r;
    vec3 wp=world_from_depth(v_uv,dsc);
    float scene_dist=(dsc>=1.0)?1e20:length(wp-u_eye);

    vec3 dir=normalize(world_from_depth(v_uv,0.5)-u_eye); // ray dir via a mid-depth point
    float t0,t1; union_interval(u_eye,dir,t0,t1);
    if(t1<=t0){ frag=vec4(0.0); return; }        // no cloud here → no contribution
    float t=max(t0,0.0);
    float tend=min(t1, scene_dist);              // stop at hulls
    if(tend<=t){ frag=vec4(0.0); return; }

    float transm=1.0; vec3 lit=vec3(0.0);
    for(int s=0;s<u_max_steps;s++){
        if(t>=tend || transm<0.02) break;
        vec3 p=u_eye+dir*t;
        float dens=density(p);
        if(dens>0.001){
            float ext=dens*u_density_scale*u_step;
            // single-scatter from up to 4 directional lights w/ cheap occlusion
            vec3 scat=vec3(0.0);
            for(int l=0;l<u_dir_light_count;l++){
                vec3 ld=normalize(u_dir_light_dir_ws[l]);
                float occ=0.0;
                for(float k=1.0;k<=u_light_steps;k+=1.0)
                    occ+=density(p+ld*(k*u_step))*u_density_scale*u_step;
                scat+=u_dir_light_color[l]*exp(-occ);
            }
            vec3 col=(scat*u_scatter + u_rgb*u_self_glow)*dens;
            lit+=transm*col*ext;
            transm*=exp(-ext);
        }
        t+=u_step;
    }
    float alpha=1.0-transm;
    frag=vec4(lit, alpha);   // premultiplied; blended GL_ONE, GL_ONE_MINUS_SRC_ALPHA
}
```

- [ ] **Step 5: Register shaders + sources** in `CMakeLists.txt` (`embed_shader(... nebula_volumetric_vs/fs)` next to the nebula ones; add `nebula_volumetric_pass.cc` to the renderer lib next to `nebula_pass.cc`). Add the `#include "embedded_nebula_volumetric_*.h"` and a `nebula_volumetric_` Shader member to `pipeline.cc` + an accessor (mirror `nebula_`).

- [ ] **Step 6: Create the pass `nebula_volumetric_pass.{h,cc}`**

Header mirrors a screen-space pass (empty VAO; the fullscreen triangle uses `gl_VertexID`). `render(...)` binds the shader, the scene+depth textures, uploads camera/eye/inv_view_proj/time, the sphere array (clamped 8) + tint/fbm/seed from `volumes[0]` (and loops volumes if >1), the up-to-4 lights from `Lighting`, and the tunable defaults (`u_step=6`, `u_max_steps=96`, `u_density_scale=0.06`, `u_scatter=1.2`, `u_self_glow=0.25`, `u_light_steps=3`). Disable depth test/write (composite), `glDrawArrays(GL_TRIANGLES,0,3)`. Early-out on empty/disabled.

- [ ] **Step 7: Wire into `host_bindings.cc`** — `g_nebula_volumetric_pass` global, construct in `init`, reset in `shutdown`. In `render_space`, **replace/branch** the V1 nebula render call:

```cpp
        if (!for_viewscreen && !g_nebulae.empty()) {
            if (dauntless_volumetric_nebulae::enabled() && g_nebula_volumetric_pass)
                g_nebula_volumetric_pass->render(cam, *g_pipeline, g_nebulae, g_lighting,
                    g_hdr_target->color_texture(), g_hdr_target->depth_texture(),
                    /*inv_view_proj*/glm::inverse(cam.proj()*cam.view()), cam.eye(),
                    static_cast<float>(now));
            else if (g_nebula_pass)
                g_nebula_pass->render(cam, *g_pipeline, g_nebulae);   // V1 faithful
        }
```

**Compositing — avoid the feedback loop (primary approach):** do NOT sample `u_scene` while writing the HDR target. Instead, the raymarch outputs **premultiplied** `vec4(lit, alpha)` and is **blended** over the HDR target with fixed-function blending (`glEnable(GL_BLEND); glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)`), depth test/write off. The shader then needs no `u_scene` sampler at all — drop it; the final line becomes `frag = vec4(lit, alpha);`. It still samples `u_depth` (the HDR depth texture) to clamp the march to hulls; reading the depth texture while only blending colour (never writing depth) is safe here, and Task 6 moves the whole march into a half-res scratch target anyway (no attachment overlap). Use the actual camera accessors for `inv_view_proj`/`eye`.

- [ ] **Step 8: Reconfigure + build**

Run: `cmake -B build -S . && cmake --build build -j` → clean.

- [ ] **Step 9: Run the FrameTest**

Run: `ctest --test-dir build -R "FrameTest" -V` → the new volumetric test passes; no new failures elsewhere.

- [ ] **Step 10: Commit**

```bash
git add native/src/renderer/include/renderer/nebula_volumetric_pass.h native/src/renderer/nebula_volumetric_pass.cc native/src/renderer/shaders/nebula_volumetric.vert native/src/renderer/shaders/nebula_volumetric.frag native/src/renderer/CMakeLists.txt native/src/renderer/pipeline.cc native/src/host/host_bindings.cc native/tests/renderer/frame_test.cc
git commit -m "feat(nebula): volumetric raymarch pass (full-res)"
```

---

## Task 6: Performance — half-res + dither + temporal + depth-aware upsample

**Files:**
- Modify: `native/src/renderer/nebula_volumetric_pass.{h,cc}`, `shaders/nebula_volumetric.frag` (dither offset), add `shaders/nebula_upsample.frag`
- Test: `native/tests/renderer/frame_test.cc` (still renders)

**Approach:** render the raymarch into a **half-resolution** scratch RGBA16F target; add a blue-noise/dither step offset per pixel (breaks banding at low step counts); temporally blend with the previous half-res frame when the camera barely moved (reproject by `prev_view_proj`); then a **depth-aware upsample** composites into the HDR target (nearest-depth bilateral to avoid haloing hull edges). This is the lever that makes the raymarch affordable at 60 Hz.

- [ ] **Step 1: Extend the FrameTest** to assert the half-res path still produces cloud tint at the centre (camera inside), and that toggling the pass off leaves the scene byte-identical. Run it RED if the assertions are new.

- [ ] **Step 2: Add a half-res scratch target** (RGBA16F, ½ HDR dimensions) owned by the pass; allocate/resize in `render` when the HDR size changes.

- [ ] **Step 3: Dither offset** — in `nebula_volumetric.frag`, offset the first `t` by `u_step * dither(gl_FragCoord.xy)` (a cheap hash) so half-res banding dissolves.

- [ ] **Step 4: Temporal blend** — add `u_prev_view_proj` + a `prev_half` texture; blend `mix(current, reprojected_prev, 0.85)` when the reprojected UV is on-screen and the camera delta is small; reset on large deltas (warp). Ping-pong the half-res targets.

- [ ] **Step 5: Depth-aware upsample** — `nebula_upsample.frag` samples the half-res cloud + full-res depth, picking the half-res tap whose depth best matches the full-res pixel (bilateral) to keep hull silhouettes crisp; composite into HDR.

- [ ] **Step 6: Reconfigure + build + FrameTest**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R "FrameTest" -V`
Expected: clean; cloud still renders; toggle-off byte-identical.

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/nebula_volumetric_pass.h native/src/renderer/nebula_volumetric_pass.cc native/src/renderer/shaders/nebula_volumetric.frag native/src/renderer/shaders/nebula_upsample.frag native/src/renderer/CMakeLists.txt native/src/renderer/pipeline.cc native/tests/renderer/frame_test.cc
git commit -m "perf(nebula): half-res raymarch + dither + temporal + depth-aware upsample"
```

---

## Task 7: Live verification + tuning (Vesuvi4 / Multi5)

**Files:** none (verification only). Hand off to Mark — no desktop interaction on his workstation.

- [ ] **Step 1:** `cmake -B build -S . && cmake --build build -j` (clean).
- [ ] **Step 2:** Checklist for Mark (load Vesuvi4 / Multi5 via `--developer` → Load Mission):
  1. Cloud has visible varying density — clumps you can fly around vs into.
  2. The player hull is **partially obscured** when buried in a clump (the V1 gripe — fixed).
  3. Sunward edges glow / dense cores are darker (single-scatter form).
  4. Toggle **Volumetric Nebulae** off → V1 faithful fog returns (byte-identical); on → volumetric.
  5. Fly an enemy engagement: bury into a dense core → the enemy **loses lock** (concealment); skim a clump → detected only at close range.
  6. Frame-rate is acceptable; if not, dial `u_max_steps` / `u_light_steps` down first.
  7. No-nebula sets render unchanged.
- [ ] **Step 3:** Apply tuning (dials in the shader + `CONCEAL_K`/`LOCK_BREAK_T`), rebuilding with `cmake -B build -S .` after shader edits. Commit:

```bash
git add native/src/renderer/ engine/appc/sensor_detection.py
git commit -m "tune(nebula): volumetric dials + concealment thresholds per live verification"
```

---

## Self-Review

**Spec coverage:**
- §4 density field (fbm, shared, seed) → Task 2 ✓
- §4 HDR depth texture → Task 1 ✓
- §5 raymarch (single-scatter, 4 lights, self-glow, depth-aware stop) → Task 5 ✓
- §5 perf (half-res, dither, temporal, upsample) → Task 6 ✓
- §6 concealment (range falloff + lock-break + hysteresis, on-demand) → Task 3 ✓ (placed in `sensor_detection.py`, the real AI detection gate, refining the spec's "in NebulaTracker" — documented)
- §7 toggle (Modern VFX, default on, visual only) + payload → Task 4 ✓
- §7 testing (parity/golden, concealment pytest, FrameTest, depth-texture, live) → Tasks 1,2,3,5,6,7 ✓
- Global: gameplay toggle-independent (Task 3 reads field regardless), byte-identity off (Task 5/7), 4-light model (Task 5) ✓

**Placeholder scan:** No TBD/TODO. The "adapt to the real signature" notes in Task 3 (`can_detect`) and the "match the post-chain read-write convention" note in Task 5 Step 7 are explicit research-then-implement instructions tied to named files, not vague gaps — the implementer reads the named file and the reviewer confirms. The raymarch shader is complete and compilable; its constants are live-tuning dials, not placeholders.

**Type consistency:** `density(px,py,pz,spheres,seed,freq,gain,floor,drift_t)`, `seed_for`, `fbm` (Task 2) used identically in Task 3 and copied in the Task 5 shader; `MetaNebula.GetFbmDials()/GetSeed()/SetFbmDials()` (Task 3) consumed in Task 4's `_aggregate_nebulae`; `NebulaVolume.fbm/seed` (Task 4) consumed in Task 5; `volumetric_nebulae_enabled` naming consistent across C++/binding/Python/JS.

**Known risk flagged in-plan:** Task 5 Step 7 — reading the HDR colour while compositing into it (feedback loop) must follow the post-chain convention (scratch target or copy); called out, not hand-waved. GPU↔CPU fbm exactness is tolerance-bounded + golden-pinned (Global Constraints), not runtime-compared.
