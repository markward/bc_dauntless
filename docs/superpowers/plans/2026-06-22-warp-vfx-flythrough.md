# Warp VFX — Procedural Galaxy Flythrough Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn warp into a timed transit where the procedural galaxy streams past (animated vantage origin→destination), stars streak, and a warp flash brackets entry/exit — a Modern-VFX toggle (default ON) whose OFF state is the existing Stage-1 hard cut. Transit duration scales with galaxy-map distance.

**Architecture:** A per-frame `WarpVFX` manager (Python, host_loop) animates the procedural-sky vantage and drives streak/flash intensities; `WarpSequence` (warp.py) holds a distance-derived duration `T` before the existing set-swap. Native: `backdrop.frag` streaks the procedural stars; `resolve.frag` applies the flash; a `dauntless_warp_vfx` namespace feeds per-frame params; during warp the cubemap is bypassed (direct render) so streaks + animated vantage are live.

**Tech Stack:** Python engine + pytest; native OpenGL renderer (GLSL, pybind11) with a cmake reconfigure for shader changes; CEF config UI.

## Global Constraints

- Never edit `sdk/Build/scripts/`. Run Python tests with `uv run pytest`.
- Shader/.frag/.vert edits are NOT picked up by incremental build — you MUST re-run `cmake -B build -S .` (reconfigure), then `cmake --build build -j`. Native ctest: `ctest --test-dir build`.
- `host_bindings.cc` / `frame.cc` edits compile into BOTH `build/dauntless` and the `_dauntless_host` module — rebuild the `dauntless` target (not just the module) or both are stale.
- Off-path parity: with the toggle OFF and intensities 0, rendered frames must be byte-identical to today (no regression to normal play).
- Fail-open: the VFX transit must never block the warp — the set-swap always completes (worst case as an instant cut). Mirror the warp spine's discipline.
- The flythrough is a LIVE feature: it activates only when (toggle ON) AND (renderer present) AND (procedural sky on). Headless / no renderer ⇒ flythrough off ⇒ the existing instant Stage-1 warp path runs unchanged (so existing warp tests stay green).
- No new user-facing strings beyond the "Warp Flythrough" config label.
- Mirror the `motion_blur` toggle wiring exactly (it is the template; file:line below).

**Key existing signatures (verified — mirror these):**
- Toggle namespace lives in `native/src/renderer/frame.cc` (`dauntless_motion_blur { bool g_*_enabled; enabled(); set_enabled(bool); }`, lines 117-121), DECLARED in `native/src/host/host_bindings.cc:121-124`, pybind at `host_bindings.cc:2003-2010`, read in `frame()` at `host_bindings.cc:747`.
- `engine/renderer.py:184-191` `motion_blur_enabled()` / `set_motion_blur_enabled()` → `_h.motion_blur_*`.
- `engine/ui/configuration_panel.py`: `SettingsSnapshot.motion_blur_on` (line 39), ctor param + store (57/86), dispatch (180-184), serialize (145).
- `native/assets/ui-cef/js/configuration_panel.js`: ctrl registration (line 32), HTML row (181-190), event `configuration/toggle:motion_blur`.
- `engine/host_loop.py:3462-3492`: ConfigurationPanel built with `motion_blur_on=r.motion_blur_enabled()` and `set_motion_blur=r.set_motion_blur_enabled`.
- `backdrop.frag`: `proc_stars(vec3 dir,float density)` (35-45), uniforms (6-16), `main()` (108-112). `backdrop_pass.cc` uniform block (124-134, `shader.set_*`). `render()` sig `backdrop_pass.h:31-35` `(backdrops, camera, pipeline, bool procedural, float now_seconds)`.
- `resolve.frag` `main()` (28-42) final `frag_color = vec4(c,1.0)`. `resolve_pass.cc::draw(hdr_tex, bloom_tex)` (38-77) sets uniforms via `shader_->set_*` before `glDrawArrays`; member setters `set_hdr_enabled`/`set_bloom_strength` (`resolve_pass.h:13-14`). frame() calls at `host_bindings.cc:759-760`.
- Cubemap bake: `host_bindings.cc:139 g_sky_dirty`, bake block `501-535` (`sky_use_cubemap`, `g_backdrop_pass->bake(...)` / `render_cubemap(...)` / `render(...)`).
- `engine/host_loop.py`: `_aggregate_backdrops` (1933-1947, `vantage = sp.vantage_for_set(pSet, model)` → `sp.project_sky(vantage, model)`); per-frame render `4298-4310` (`set_backdrops`/`set_suns`/`set_dust_planets`); `_aggregate_suns` (1777-1784).
- `engine/appc/sky_projection.py` `vantage_for_set(pSet, model)` (returns the system position used as the projection vantage), `project_sky(vantage, model)`. `engine/appc/sector_model.py`.
- `engine/appc/warp.py`: `WarpSequence_Create(ship, dest_module, warp_time, placement)` (184-215), `configure_warp_hooks(...)`, `_module_is_empty`. `engine/appc/actions.py` `TGSequence.AppendAction(action, *extra)` (delay via numeric extra; timer on `g_kTimerManager`).
- CMake shader embed: `native/src/renderer/CMakeLists.txt:5-12` `embed_shader()`, calls 17-18 (backdrop), 50-51 (resolve) → `embedded_*.h`.

---

### Task 1: Native warp-VFX state + bindings + renderer setters + config toggle

The plumbing only — a `dauntless_warp_vfx` namespace (streak/flash/travel/enabled), pybind setters, Python wrappers, and the "Warp Flythrough" config toggle. No visual change yet (frame() doesn't consume the values until Task 2).

**Files:**
- Modify: `native/src/renderer/frame.cc` (namespace impl), `native/src/host/host_bindings.cc` (decl + pybind)
- Modify: `engine/renderer.py` (wrappers)
- Modify: `engine/ui/configuration_panel.py`, `native/assets/ui-cef/js/configuration_panel.js`, `engine/host_loop.py` (config wiring)
- Test: `tests/unit/test_configuration_panel.py` (extend)

**Interfaces produced:**
- C++/pybind: `warp_flythrough_set_enabled(bool)`, `warp_flythrough_enabled() -> bool`, `set_warp_streak_intensity(float)`, `set_warp_flash_intensity(float)`, `set_warp_travel_dir(x,y,z)`. Namespace `dauntless_warp_vfx` with getters `enabled()`, `streak_intensity()`, `flash_intensity()`, `travel_dir()` (a `glm::vec3`).
- Python: `engine/renderer.py` `warp_flythrough_enabled()`, `set_warp_flythrough_enabled(bool)`, `set_warp_streak_intensity(float)`, `set_warp_flash_intensity(float)`, `set_warp_travel_dir(tuple)`.
- Config: `SettingsSnapshot.warp_flythrough_on` + the toggle row.

- [ ] **Step 1: Add the namespace impl in `frame.cc`** (mirror `dauntless_motion_blur`, lines 117-121):

```cpp
namespace dauntless_warp_vfx {
    bool  g_enabled = true;        // Modern-VFX toggle (default on)
    float g_streak  = 0.0f;        // 0..1 star-streak intensity
    float g_flash   = 0.0f;        // 0..1 warp-flash intensity
    glm::vec3 g_travel(0.0f, 1.0f, 0.0f);  // world-space travel direction
    bool  enabled()           { return g_enabled; }
    void  set_enabled(bool v)  { g_enabled = v; }
    float streak_intensity()  { return g_streak; }
    float flash_intensity()   { return g_flash; }
    glm::vec3 travel_dir()    { return g_travel; }
    void  set_streak(float v) { g_streak = v; }
    void  set_flash(float v)  { g_flash = v; }
    void  set_travel(glm::vec3 v) { g_travel = v; }
}
```

(Ensure `#include <glm/glm.hpp>` is present in frame.cc — it is, used elsewhere.)

- [ ] **Step 2: Declare + bind in `host_bindings.cc`** — declaration near the `dauntless_motion_blur` block (~121):

```cpp
namespace dauntless_warp_vfx {
    bool enabled(); void set_enabled(bool);
    float streak_intensity(); float flash_intensity();
    glm::vec3 travel_dir();
    void set_streak(float); void set_flash(float); void set_travel(glm::vec3);
}
```

pybind defs near the motion_blur defs (~2003-2010):

```cpp
m.def("warp_flythrough_set_enabled", [](bool e){ dauntless_warp_vfx::set_enabled(e); }, py::arg("enabled"));
m.def("warp_flythrough_enabled", [](){ return dauntless_warp_vfx::enabled(); });
m.def("set_warp_streak_intensity", [](float i){ dauntless_warp_vfx::set_streak(i); }, py::arg("intensity"));
m.def("set_warp_flash_intensity", [](float i){ dauntless_warp_vfx::set_flash(i); }, py::arg("intensity"));
m.def("set_warp_travel_dir", [](float x, float y, float z){ dauntless_warp_vfx::set_travel(glm::vec3(x,y,z)); },
      py::arg("x"), py::arg("y"), py::arg("z"));
```

- [ ] **Step 3: Python wrappers in `engine/renderer.py`** (after the motion_blur wrappers):

```python
def warp_flythrough_enabled() -> bool:
    """Read the Warp Flythrough toggle (Modern VFX). Default: on."""
    return _h.warp_flythrough_enabled()

def set_warp_flythrough_enabled(enabled: bool) -> None:
    """Toggle the warp flythrough VFX (Modern VFX). Off = instant hard cut."""
    _h.warp_flythrough_set_enabled(enabled)

def set_warp_streak_intensity(intensity: float) -> None:
    _h.set_warp_streak_intensity(float(intensity))

def set_warp_flash_intensity(intensity: float) -> None:
    _h.set_warp_flash_intensity(float(intensity))

def set_warp_travel_dir(direction) -> None:
    x, y, z = direction
    _h.set_warp_travel_dir(float(x), float(y), float(z))
```

Each wrapper must be a no-op-safe when `_h` is None (headless): guard with `if _h is None: return` / `return False` mirroring the surrounding wrappers (read how `set_motion_blur_enabled` handles a missing `_h` and match it — likely `_h` is always present where these are called, but match the file's convention).

- [ ] **Step 4: Config toggle (mirror motion_blur).**
- `engine/ui/configuration_panel.py`: add `warp_flythrough_on: bool = True` to `SettingsSnapshot`; ctor param `set_warp_flythrough: Callable[[bool], None]` + store `self._set_warp_flythrough`; dispatch branch `if action == "toggle:warp_flythrough": ...`; serialize `"warp_flythrough_on": self._settings.warp_flythrough_on`.
- `native/assets/ui-cef/js/configuration_panel.js`: `out.push({kind:'ctrl', target:'warp_flythrough'})` and an HTML row mirroring the motion_blur row (label "Warp Flythrough", event `configuration/toggle:warp_flythrough`).
- `engine/host_loop.py` (~3462-3492): pass `warp_flythrough_on=r.warp_flythrough_enabled()` and `set_warp_flythrough=r.set_warp_flythrough_enabled` into `ConfigurationPanel`.

- [ ] **Step 5: Reconfigure + build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: builds clean (dauntless + _dauntless_host).

- [ ] **Step 6: Smoke-test the bindings + config test**

Run: `PYTHONPATH=build/python uv run python -c "import _dauntless_host as h; h.warp_flythrough_set_enabled(False); print(h.warp_flythrough_enabled()); h.set_warp_streak_intensity(0.5); h.set_warp_travel_dir(0,1,0); print('ok')"`
Expected: prints `False` then `ok`.
Run: `uv run pytest tests/unit/test_configuration_panel.py -q`
Expected: PASS (extend it with a `toggle:warp_flythrough` round-trip test mirroring the motion_blur test).

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/frame.cc native/src/host/host_bindings.cc engine/renderer.py engine/ui/configuration_panel.py native/assets/ui-cef/js/configuration_panel.js engine/host_loop.py tests/unit/test_configuration_panel.py
git commit -m "feat(warp-vfx): dauntless_warp_vfx state + bindings + Warp Flythrough toggle"
```

---

### Task 2: Streak shader + flash shader + frame() feed + cubemap bypass

Make the native renderer consume the warp-vfx state: stretch procedural stars along the travel direction, flash the resolve output, and bypass the cubemap while warp is active so streaks + animated vantage render live. Intensity-0 path stays byte-identical.

**Files:**
- Modify: `native/src/renderer/shaders/backdrop.frag`, `native/src/renderer/backdrop_pass.cc` (+ `.h` if adding setters)
- Modify: `native/src/renderer/shaders/resolve.frag`, `native/src/renderer/resolve_pass.{cc,h}`
- Modify: `native/src/host/host_bindings.cc` (frame() feed + cubemap bypass)
- Test: native ctest (shaders compile), visual off-parity (manual)

**Interfaces consumed:** `dauntless_warp_vfx::streak_intensity/flash_intensity/travel_dir/enabled` (Task 1).

- [ ] **Step 1: Streak uniforms in `backdrop.frag`.** Add uniforms (near 6-16):

```glsl
uniform float u_warp_streak;        // 0..1
uniform vec3  u_warp_travel;        // world-space travel dir (normalized)
```

In `proc_stars`, elongate the star falloff along the apparent radial-streak direction. Replace the `float d = length(g - starPos);` line with an anisotropic distance that compresses ALONG the streak axis (so the blob stretches into a line):

```glsl
    vec3 delta = g - starPos;
    if (u_warp_streak > 0.0) {
        // Streak axis = the star's screen-radial direction from the travel
        // vanishing point (stars stream outward as you fly forward). Compress
        // distance along that axis so the blob elongates into a line.
        vec3 t = normalize(u_warp_travel);
        vec3 radial = normalize(g - dot(g, t) * t + 1e-5);
        float along = dot(delta, radial);
        float perp  = length(delta - along * radial);
        float stretch = 1.0 + 6.0 * u_warp_streak;   // tunable elongation
        delta = vec3(perp, along / stretch, 0.0);
    }
    float d = length(delta);
```

(The `6.0` is a starting elongation factor — Mark tunes live. Keep `proc_stars` otherwise unchanged so `u_warp_streak == 0` is identical to today.)

- [ ] **Step 2: Set the streak uniforms in `backdrop_pass.cc`.** In the uniform block (124-134), add (read the globals; declare `namespace dauntless_warp_vfx { float streak_intensity(); glm::vec3 travel_dir(); }` at the top of backdrop_pass.cc, or pass via `render()` args — choose the lower-churn option). Simplest: pass two new params into `render()`:

`backdrop_pass.h` `render(...)` signature gains `float warp_streak, glm::vec3 warp_travel`; in the body:

```cpp
shader.set_float("u_warp_streak", warp_streak);
shader.set_vec3("u_warp_travel", warp_travel);
```

Set them to `0.0f` / `vec3(0,1,0)` in `render_cubemap()` and `bake()` (streaks only apply on the live direct path).

- [ ] **Step 3: Flash uniform in `resolve.frag`.** Add `uniform float u_warp_flash;` (near 4-7) and, at the end of `main()`, before the write:

```glsl
    c = mix(c, vec3(1.0), clamp(u_warp_flash, 0.0, 1.0));
    frag_color = vec4(c, 1.0);
```

- [ ] **Step 4: Flash setter in `resolve_pass`.** Add `void set_warp_flash(float v) { warp_flash_ = v; }` + `float warp_flash_ = 0.0f;` member (`resolve_pass.h`); in `draw()` set `shader_->set_float("u_warp_flash", warp_flash_);` before `glDrawArrays`.

- [ ] **Step 5: Feed + cubemap bypass in `host_bindings.cc frame()`.**
- In the bake block (~501-535): force the live direct path while warp is active so the animated vantage + streak render every frame:

```cpp
const bool warp_active = dauntless_warp_vfx::streak_intensity() > 0.0f
                         || dauntless_warp_vfx::flash_intensity() > 0.0f;
// ... existing sky_use_cubemap computation ...
if (warp_active) sky_use_cubemap = false;   // direct render so stars streak + vantage animates
```

- Pass streak/travel into the direct `render()` call (~530-535):

```cpp
g_backdrop_pass->render(g_backdrops, cam, *g_pipeline,
                        dauntless_procedural_sky::enabled(),
                        static_cast<float>(now),
                        dauntless_warp_vfx::streak_intensity(),
                        dauntless_warp_vfx::travel_dir());
```

- Feed the flash before the resolve draw (~759-760):

```cpp
g_resolve_pass->set_warp_flash(dauntless_warp_vfx::flash_intensity());
g_resolve_pass->draw(g_hdr_target->color_texture(), bloom_tex);
```

- [ ] **Step 6: Reconfigure + build + ctest**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure`
Expected: shaders compile; renderer ctests pass (the pre-existing scorch/heat-glow FrameTest failures are unrelated — see `[[project_cpp_ctest_not_in_run_tests]]`; confirm no NEW failures vs the base).

- [ ] **Step 7: Off-parity smoke** — with streak/flash 0, a rendered frame is unchanged. (Manual/visual; or a FrameTest that renders with intensities 0 and compares to the existing baseline if such a harness exists.)

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/shaders/backdrop.frag native/src/renderer/backdrop_pass.cc native/src/renderer/include/renderer/backdrop_pass.h native/src/renderer/shaders/resolve.frag native/src/renderer/resolve_pass.cc native/src/renderer/include/renderer/resolve_pass.h native/src/host/host_bindings.cc
git commit -m "feat(warp-vfx): star-streak in backdrop.frag + warp flash in resolve.frag + frame feed"
```

---

### Task 3: WarpVFX manager + vantage override + per-frame feed (Python)

A per-frame manager that animates the vantage origin→destination and drives streak/flash envelopes; host_loop overrides the sky vantage and feeds the renderer + drops local objects during transit.

**Files:**
- Create: `engine/warp_vfx.py`
- Modify: `engine/host_loop.py` (instantiate, tick, vantage override, per-frame feed, local-object drop)
- Test: `tests/unit/test_warp_vfx.py`

**Interfaces produced:**
- `engine/warp_vfx.py`: `class WarpVFX` — `start(src_vantage, dst_vantage, duration, travel_dir, now)`, `tick(now)`, `stop()`, `is_active() -> bool`, `vantage()`, `streak_intensity() -> float`, `flash_intensity() -> float`, `travel_dir()`, `progress(now)`. Module-level `get()` returning a singleton (so warp.py's sequence action and host_loop share one).
- host_loop: vantage override in `_aggregate_backdrops`; per-frame `tick` + renderer feed; local sun/planet drop while active.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_warp_vfx.py
from engine.warp_vfx import WarpVFX


def test_inactive_by_default():
    w = WarpVFX()
    assert w.is_active() is False


def test_vantage_lerps_src_to_dst():
    w = WarpVFX()
    w.start((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), duration=4.0,
            travel_dir=(1.0, 0.0, 0.0), now=100.0)
    assert w.is_active() is True
    w.tick(100.0); assert abs(w.vantage()[0] - 0.0) < 1e-6
    w.tick(102.0); assert abs(w.vantage()[0] - 5.0) < 1e-6   # halfway
    w.tick(104.0); assert abs(w.vantage()[0] - 10.0) < 1e-6  # end
    w.tick(104.0); assert w.is_active() is False             # done at/after duration


def test_streak_and_flash_envelopes():
    w = WarpVFX()
    w.start((0,0,0), (1,0,0), duration=4.0, travel_dir=(1,0,0), now=0.0)
    w.tick(0.0)
    # flash pulses high at entry, streak ramps in
    assert w.flash_intensity() > 0.5
    w.tick(2.0)
    assert w.streak_intensity() > 0.5      # streaking mid-transit
    assert w.flash_intensity() < 0.2       # entry flash faded
    w.tick(3.9)
    assert w.flash_intensity() > 0.3       # exit flash rising near the end


def test_stop_resets():
    w = WarpVFX()
    w.start((0,0,0), (1,0,0), 4.0, (1,0,0), 0.0)
    w.stop()
    assert w.is_active() is False
    assert w.streak_intensity() == 0.0 and w.flash_intensity() == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_warp_vfx.py -v`
Expected: FAIL (`engine.warp_vfx` missing).

- [ ] **Step 3: Implement `engine/warp_vfx.py`**

```python
"""WarpVFX — per-frame warp-transit animator (Stage 2 warp VFX).

Owns the timed flythrough state: interpolates the procedural-sky vantage
origin->destination and drives the star-streak + warp-flash envelopes. Ticked
each frame by the host loop; started/stopped by the WarpSequence. Headless-safe
(pure math; no renderer dependency).

Spec: docs/superpowers/specs/2026-06-22-warp-vfx-flythrough-design.md
"""


def _lerp3(a, b, t):
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def _smooth(t):  # smoothstep ease
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3.0 - 2.0 * t)


class WarpVFX:
    def __init__(self):
        self._active = False
        self._src = (0.0, 0.0, 0.0)
        self._dst = (0.0, 0.0, 0.0)
        self._dur = 0.0
        self._t0 = 0.0
        self._travel = (0.0, 1.0, 0.0)
        self._vantage = (0.0, 0.0, 0.0)
        self._streak = 0.0
        self._flash = 0.0

    def start(self, src_vantage, dst_vantage, duration, travel_dir, now):
        self._src = tuple(src_vantage)
        self._dst = tuple(dst_vantage)
        self._dur = max(0.01, float(duration))
        self._t0 = float(now)
        self._travel = tuple(travel_dir)
        self._vantage = self._src
        self._active = True
        self._streak = 0.0
        self._flash = 1.0   # entry flash peak

    def progress(self, now):
        return min(1.0, max(0.0, (now - self._t0) / self._dur))

    def tick(self, now):
        if not self._active:
            return
        p = self.progress(now)
        self._vantage = _lerp3(self._src, self._dst, _smooth(p))
        # streak: ramp in over the first 20%, hold, ramp out over the last 15%.
        ramp_in = _smooth(p / 0.2)
        ramp_out = _smooth((1.0 - p) / 0.15)
        self._streak = min(ramp_in, ramp_out)
        # flash: entry pulse (decays over first 15%) + exit pulse (rises in last 8%).
        entry = max(0.0, 1.0 - p / 0.15)
        exit_ = max(0.0, (p - 0.92) / 0.08)
        self._flash = min(1.0, entry + exit_)
        if p >= 1.0:
            self._active = False
            self._streak = 0.0
            self._flash = 0.0

    def stop(self):
        self._active = False
        self._streak = 0.0
        self._flash = 0.0

    def is_active(self):       return self._active
    def vantage(self):         return self._vantage
    def streak_intensity(self): return self._streak
    def flash_intensity(self):  return self._flash
    def travel_dir(self):      return self._travel


_singleton = WarpVFX()


def get():
    return _singleton
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_warp_vfx.py -v`
Expected: PASS.

- [ ] **Step 5: Wire into host_loop — vantage override, per-frame tick + feed, local-object drop.**
- In `_aggregate_backdrops` (1933-1947), after computing `vantage`, override during warp:

```python
        from engine import warp_vfx as _wv
        _w = _wv.get()
        if vantage is not None and _w.is_active():
            vantage = _w.vantage()
        if vantage is not None:
            return sp.project_sky(vantage, model)
```

- In the per-frame render section (~4298, near `set_backdrops`): tick the manager and feed the renderer; drop local suns/planets while active:

```python
        from engine import warp_vfx as _wv
        _w = _wv.get()
        if _w.is_active():
            _w.tick(_now_game_time())   # use the same clock the sequence delay uses
            r.set_warp_streak_intensity(_w.streak_intensity())
            r.set_warp_flash_intensity(_w.flash_intensity())
            r.set_warp_travel_dir(_w.travel_dir())
        else:
            r.set_warp_streak_intensity(0.0)
            r.set_warp_flash_intensity(0.0)
```

  For the local-object drop, gate `_aggregate_suns()` / `_aggregate_planets()` so they return `[]` while `_w.is_active()` (the entry flash masks the pop). Read the exact aggregation call sites (4302-4306) and wrap them.

> Implementer: find the real "current game time" accessor host_loop already uses for the frame (the same `now`/`game_time` the loop computes each tick — grep the per-frame block); use it for both `tick()` and confirm it matches the `g_kTimerManager` clock the sequence delay runs on. If they differ, the transit visuals and the swap won't line up.

- [ ] **Step 6: Run the host/regression**

Run: `uv run pytest tests/unit/test_warp_vfx.py tests/ -k "host_loop or backdrop or warp" -q`
Expected: PASS (no regression).
Run: `PYTHONPATH=build/python uv run python -c "import engine.host_loop"`
Expected: no error.

- [ ] **Step 7: Commit**

```bash
git add engine/warp_vfx.py engine/host_loop.py tests/unit/test_warp_vfx.py
git commit -m "feat(warp-vfx): WarpVFX manager + vantage override + per-frame feed"
```

---

### Task 4: Sequence integration — distance-based duration + timed transit

Make `WarpSequence_Create` build a timed transit (when the flythrough is live), with duration scaled by galaxy distance; start/stop the WarpVFX manager via hooks; otherwise keep the instant Stage-1 path.

**Files:**
- Modify: `engine/appc/warp.py` (sequence + duration + vfx hooks), `engine/host_loop.py` (wire vfx start/stop hooks + flythrough-enabled predicate)
- Test: `tests/unit/test_warp_spine.py` (extend), `tests/unit/test_warp_vfx_sequence.py` (create)

**Interfaces produced:**
- `warp.py`: `configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)` — host supplies: `start(src, dst, duration, travel_dir)`, `stop()`, `enabled() -> bool` (toggle AND renderer AND procedural sky), `vantage_of(set_or_module) -> (x,y,z)|None`. `WarpSequence_Create` uses them to decide instant vs timed, compute `T`, and drive the manager.
- Duration: `T = clamp(T_MIN, T_MAX, T_BASE + K * dist)` with module constants `T_MIN=2.0, T_MAX=10.0, T_BASE=2.0, K=...` (start value tuned so a mid-galaxy hop ≈ 4–5 s).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_warp_vfx_sequence.py
import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create


def setup_function(_):
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)


def test_duration_scales_with_distance():
    near = warp._transit_duration((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    far = warp._transit_duration((0.0, 0.0, 0.0), (1000.0, 0.0, 0.0))
    assert far > near
    assert warp._T_MIN <= near <= warp._T_MAX
    assert warp._T_MIN <= far <= warp._T_MAX
    # unmapped vantage -> T_BASE
    assert warp._transit_duration(None, (1.0, 0.0, 0.0)) == warp._T_BASE


def test_flythrough_disabled_is_instant(monkeypatch):
    # enabled() False -> instant Stage-1 sequence (no held swap): player warps now.
    warp.configure_warp_vfx(enabled=lambda: False)
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    import types, sys
    mod = types.ModuleType("FakeSys.D"); mod.Initialize = lambda: (
        App.g_kSetManager.AddSet(SetClass_Create(), "D"))
    sys.modules["FakeSys.D"] = mod
    warp.WarpSequence_Create(player, "FakeSys.D", placement=None).Play()
    assert App.g_kSetManager.GetSet("Src") is None   # instant swap happened


def test_flythrough_enabled_starts_vfx_and_defers_swap(monkeypatch):
    started = {}
    warp.configure_warp_vfx(
        enabled=lambda: True,
        start=lambda src, dst, dur, tdir: started.update(dur=dur),
        stop=lambda: None,
        vantage_of=lambda key: (0.0, 0.0, 0.0))
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src2")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    import types, sys
    mod = types.ModuleType("FakeSys.D2"); mod.Initialize = lambda: (
        App.g_kSetManager.AddSet(SetClass_Create(), "D2"))
    sys.modules["FakeSys.D2"] = mod
    seq = warp.WarpSequence_Create(player, "FakeSys.D2", placement="Player Start")
    seq.Play()
    # VFX started; swap is DEFERRED (held by delay) -> source still present at t=0.
    assert "dur" in started and started["dur"] > 0.0
    assert App.g_kSetManager.GetSet("Src2") is src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_warp_vfx_sequence.py -v`
Expected: FAIL (`configure_warp_vfx` / `_transit_duration` missing).

- [ ] **Step 3: Implement in `engine/appc/warp.py`.** Add the vfx hook config + duration + branch:

```python
import math

_T_MIN, _T_MAX, _T_BASE, _K = 2.0, 10.0, 2.0, 0.02   # tunable

_vfx_start = None
_vfx_stop = None
_vfx_enabled = None     # () -> bool
_vfx_vantage_of = None  # (set_or_module) -> (x,y,z) | None


def configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None):
    global _vfx_start, _vfx_stop, _vfx_enabled, _vfx_vantage_of
    _vfx_start, _vfx_stop, _vfx_enabled, _vfx_vantage_of = start, stop, enabled, vantage_of


def _transit_duration(src_vantage, dst_vantage):
    if src_vantage is None or dst_vantage is None:
        return _T_BASE
    dx = dst_vantage[0] - src_vantage[0]
    dy = dst_vantage[1] - src_vantage[1]
    dz = dst_vantage[2] - src_vantage[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    t = _T_BASE + _K * dist
    return _T_MIN if t < _T_MIN else (_T_MAX if t > _T_MAX else t)
```

In `WarpSequence_Create`, after capturing `source` and resolving `dest_name`, branch on the flythrough being live:

```python
    flythrough = bool(_vfx_enabled and _vfx_enabled()) and not _module_is_empty(dest_module)
    if flythrough:
        src_v = _vfx_vantage_of(source) if (_vfx_vantage_of and source) else None
        dst_v = _vfx_vantage_of(dest_module) if _vfx_vantage_of else None
        dur = _transit_duration(src_v, dst_v)
        travel = (0.0, 1.0, 0.0)  # ship-forward in world; refine from ship rotation if available
        seq.AddAction(_WarpVfxBeginAction(src_v, dst_v, dur, travel))
        # the swap is held until the transit completes (masked by the exit flash)
        seq.AppendAction(ChangeRenderedSetAction_Create(dest_module), dur)
        seq.AppendAction(_PlacePlayerAction(ship, dest_name, placement))
        seq.AppendAction(_ArriveFinalizeAction(source, ship))
        seq.AppendAction(_WarpVfxEndAction())
        return seq
    # ... existing instant path unchanged ...
```

Add the two tiny actions:

```python
class _WarpVfxBeginAction(TGAction):
    def __init__(self, src_v, dst_v, dur, travel):
        super().__init__()
        self._a = (src_v, dst_v, dur, travel)
    def _do_play(self):
        if _vfx_start is not None:
            try: _vfx_start(*self._a)
            except Exception: pass

class _WarpVfxEndAction(TGAction):
    def _do_play(self):
        if _vfx_stop is not None:
            try: _vfx_stop()
            except Exception: pass
```

(`AppendAction(action, dur)` passes the numeric delay — confirm `TGSequence.AppendAction`'s `*extra` treats a number as the delay, per `actions.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_warp_vfx_sequence.py tests/unit/test_warp_spine.py -v`
Expected: PASS (warp_spine tests still green — they don't configure vfx, so `_vfx_enabled` is None ⇒ instant path).

- [ ] **Step 5: Wire the host hooks.** In `engine/host_loop.py` near the warp-hooks config (where `configure_warp_hooks` is called, ~3201):

```python
        from engine.appc import warp as _wp
        from engine import warp_vfx as _wv
        from engine.appc import sky_projection as _sp

        def _flythrough_enabled():
            return bool(r.warp_flythrough_enabled()) and r.procedural_sky_enabled()

        def _vantage_of(key):
            # key is a SetClass (source) or a module string (destination).
            try:
                model = _sp.load_sector_model()
                pSet = key if hasattr(key, "GetName") else _set_for_module(key)
                v = _sp.vantage_for_set(pSet, model) if pSet is not None else None
                return v if v is None else (v[0], v[1], v[2])
            except Exception:
                return None

        def _vfx_start(src, dst, dur, travel):
            _wv.get().start(src or (0, 0, 0), dst or (0, 0, 0), dur, travel, _now_game_time())

        _wp.configure_warp_vfx(start=_vfx_start, stop=_wv.get().stop,
                               enabled=_flythrough_enabled, vantage_of=_vantage_of)
```

> Implementer: `vantage_for_set` needs a SetClass. For the DESTINATION (a module string), resolve the set name (`warp._set_name_from_module`) and look it up — but the destination set isn't loaded until the swap. Two options: (a) derive the destination vantage from `sector_model` by the module's system id directly (preferred — no set needed), or (b) accept `dst=None` (⇒ `T_BASE`, no parallax) for the first cut. Implement (a) if a `system_id`→position lookup is cheap (`sector_model` has positions keyed by system id; map the module → system id via the same path the Set Course catalog uses). Document which you used.

- [ ] **Step 6: Run the warp suites + host import**

Run: `uv run pytest tests/ -k "warp" -q`
Expected: PASS.
Run: `PYTHONPATH=build/python uv run python -c "import engine.host_loop"` → no error.

- [ ] **Step 7: Commit**

```bash
git add engine/appc/warp.py engine/host_loop.py tests/unit/test_warp_vfx_sequence.py
git commit -m "feat(warp-vfx): distance-based timed transit + WarpVFX sequence integration"
```

---

## Final verification

- [ ] `cmake -B build -S . && cmake --build build -j && ctest --test-dir build` → builds; no NEW ctest failures (scorch/heat-glow pre-existing).
- [ ] `uv run pytest tests/ -k "warp or configuration or backdrop" -q` → green (modulo documented pre-existing failures).
- [ ] `bash scripts/run_tests.sh` → green.
- [ ] **Human gate (Mark):** relaunch `./build/dauntless`. Warp from exterior view → the galaxy streams past (vantage animates), stars streak along travel, entry/exit flash, arrive in the new system; far systems take visibly longer than near ones. Toggle "Warp Flythrough" OFF under Modern VFX → instant hard cut. Tune elongation (`backdrop.frag` `6.0`), `K`/`T_*`, and flash envelope to taste (bias strong first).

## Self-review notes

- **Spec coverage:** toggle + OFF=hard-cut (Task 1+4), streak shader (Task 2), flash shader (Task 2), vantage animation + manager (Task 3), distance-based duration (Task 4), cubemap bypass during warp (Task 2), local-object drop (Task 3), fail-open (Task 4 try/excepts), procedural-sky dependency (Task 4 `_flythrough_enabled`). Out-of-scope (ship stretch, SFX, viewscreen) untouched.
- **No-placeholder:** concrete shader + binding + Python code per step; the three "verify the real API" notes (renderer.py `_h`-None convention; host_loop game-time accessor; destination-vantage lookup) instruct reading a real signature, flagged because the investigation didn't quote them verbatim.
- **Type consistency:** `dauntless_warp_vfx` getters/setters match the pybind defs and `renderer.py` wrappers; `WarpVFX` API (`start/tick/stop/is_active/vantage/streak_intensity/flash_intensity/travel_dir`) used identically in host_loop and warp hooks; `configure_warp_vfx(start, stop, enabled, vantage_of)` signature matches the host wiring.
- **Test isolation:** headless tests never hit the renderer (flythrough off unless `enabled()` is supplied), so existing warp tests stay green; the timed-transit test asserts deferral structurally (swap not fired at t=0) rather than waiting real time.
