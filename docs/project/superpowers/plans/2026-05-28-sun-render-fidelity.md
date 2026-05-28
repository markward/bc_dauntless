# Sun Render Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the chunky polygonal corona shell with a thin 1.1× halo plus a camera-facing rotating billboard for `flare_texture`, matching BC's SunEffect layer; stop treating `atmosphere_thickness` as a visual parameter.

**Architecture:** Aggregator in `engine/appc/planet.py` stops mixing `atmosphere_thickness` into the corona size — emits `corona_radius = radius * 1.1` and a new `flare_texture_path`. C++ `SunDescriptor` gains `flare_texture_path`. `SunPass::render` removes its hardcoded `kBodyVisualScale`/`kCoronaVisualScale` fudges, drops the `0.6 → 0.54` corona opacity, and draws a new third layer: a camera-facing additive billboard sampling `flare_texture` with UVs rotating ~5°/s. A new `sun_flare.{vert,frag}` shader pair drives the billboard.

**Tech Stack:** C++20, OpenGL 3.3, GLAD, GLM, GLFW; Python 3 (`engine/appc/planet.py`, `engine/host_loop.py`); pytest; GoogleTest.

**Spec:** [`docs/project/superpowers/specs/2026-05-28-sun-render-fidelity-design.md`](../specs/2026-05-28-sun-render-fidelity-design.md)

---

## File Map

**Create:**
- `native/src/renderer/shaders/sun_flare.vert` — billboard vertex shader
- `native/src/renderer/shaders/sun_flare.frag` — additive rotating-UV fragment shader

**Modify:**
- `engine/appc/planet.py` — aggregator emits `corona_radius = radius * 1.1` and `flare_texture_path`
- `engine/renderer.py` — `set_suns` docstring lists the new key
- `tests/unit/test_host_loop_suns.py` — update `test_aggregate_suns_applies_astro_scale`, add flare-path coverage
- `native/src/renderer/include/renderer/frame.h` — add `flare_texture_path` to `SunDescriptor`
- `native/src/renderer/include/renderer/sun_pass.h` — `render` signature gains `double now_seconds`
- `native/src/renderer/include/renderer/pipeline.h` — add `sun_flare_shader()` accessor + member
- `native/src/renderer/pipeline.cc` — construct the new shader
- `native/src/renderer/CMakeLists.txt` — embed `sun_flare.vert` / `sun_flare.frag`
- `native/src/renderer/sun_pass.cc` — drop fudge constants, name new ratios, draw flare overlay
- `native/src/renderer/shaders/sun.frag` — corona alpha `0.6 → 0.54`
- `native/src/host/host_bindings.cc` — parse `flare_texture_path` from `set_suns` dicts; pass `now` to `g_sun_pass->render`
- `native/tests/renderer/sun_pass_test.cc` — extend signature calls; add overlay cases

---

## Task 1: Update aggregator test for new corona semantics (TDD red)

**Files:**
- Test: `tests/unit/test_host_loop_suns.py:78-117`

- [ ] **Step 1: Update `test_aggregate_suns_applies_astro_scale` to expect new behavior**

Edit `tests/unit/test_host_loop_suns.py`. Replace the entire `test_aggregate_suns_applies_astro_scale` function with:

```python
def test_aggregate_suns_applies_astro_scale(tmp_path):
    """Sun position, radius, corona_radius, and flare_texture_path are all
    derived correctly. corona_radius is a fixed 1.1x of body radius (the
    SDK atmosphere_thickness is gameplay-only and does not reach the
    renderer)."""
    import App
    from engine.appc.planet import Sun_Create
    from engine import host_loop
    from engine.scale import ASTRO_SCALE
    import engine.host_loop as hl
    import pytest

    tex_rel = "data/Textures/UniqueSunForAstroScaleTest.tga"
    flare_rel = "data/Textures/Effects/UniqueFlareForAstroScaleTest.tga"
    tex_abs = tmp_path / "game" / tex_rel
    flare_abs = tmp_path / "game" / flare_rel
    tex_abs.parent.mkdir(parents=True)
    flare_abs.parent.mkdir(parents=True, exist_ok=True)
    tex_abs.write_bytes(b"FAKE")
    flare_abs.write_bytes(b"FAKE")

    pSet = App.SetClass_Create()
    # atmosphere_thickness=2000.0 is intentionally != radius to prove it
    # does NOT influence corona_radius any more.
    pSun = Sun_Create(4000.0, 2000.0, 0.0, tex_rel, flare_rel)
    pSun.SetTranslateXYZ(10.0, 20.0, 30.0)
    pSet.AddObjectToSet(pSun, "Sun")
    App.g_kSetManager.AddSet(pSet, "_test_agg_suns_astro_scale")

    original_root = hl.PROJECT_ROOT
    hl.PROJECT_ROOT = tmp_path
    try:
        result = host_loop._aggregate_suns()
    finally:
        hl.PROJECT_ROOT = original_root
        App.g_kSetManager.DeleteSet("_test_agg_suns_astro_scale")

    expected_tex = str(tex_abs.resolve())
    expected_flare = str(flare_abs.resolve())
    matches = [d for d in result if d["base_texture_path"] == expected_tex]
    assert len(matches) == 1
    d = matches[0]
    assert d["position"] == pytest.approx((10.0 * ASTRO_SCALE,
                                           20.0 * ASTRO_SCALE,
                                           30.0 * ASTRO_SCALE))
    assert d["radius"]             == pytest.approx(4000.0 * ASTRO_SCALE)
    assert d["corona_radius"]      == pytest.approx(4000.0 * 1.1 * ASTRO_SCALE)
    assert d["flare_texture_path"] == expected_flare
```

- [ ] **Step 2: Run the updated test — it should FAIL**

Run: `uv run pytest tests/unit/test_host_loop_suns.py::test_aggregate_suns_applies_astro_scale -v`

Expected: FAIL — `corona_radius` still matches the old `(4000+2000)*1` formula, and `d["flare_texture_path"]` raises `KeyError` (or the assertion mismatches). Either failure mode confirms the aggregator hasn't been updated yet.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/unit/test_host_loop_suns.py
git commit -m "test(suns): expect corona_radius=1.1*radius and new flare_texture_path"
```

---

## Task 2: Update aggregator to emit new fields (TDD green)

**Files:**
- Modify: `engine/appc/planet.py:140-181`

- [ ] **Step 1: Rewrite `aggregate_suns_for_renderer`**

Open `engine/appc/planet.py`. Replace the function body starting at line 140 (everything from `def aggregate_suns_for_renderer` through the `return out`) with:

```python
def aggregate_suns_for_renderer(project_root, pSets):
    """Return list[dict] for all Sun objects across pSets.

    Suns with no base_texture fall back to SunBase.tga (the BC engine default).
    Suns whose resolved base_texture path does not exist are dropped with a
    once-per-object warning (suppressed after first fire via _sun_warned).
    Suns with radius <= 0 are dropped silently.

    The corona is rendered as a thin 1.1x halo around the body. SDK
    atmosphere_thickness is gameplay-only (Planet.AtmosphereRadius is the
    AI keep-out / damage zone) and is NOT used for visual sizing. See
    docs/project/superpowers/specs/2026-05-28-sun-render-fidelity-design.md.

    flare_texture_path resolves the Sun's _flare_texture (5th arg to
    Sun_Create). Empty string when unset OR when the file is missing on
    disk (warned once via _flare_warned). Renderer treats empty as
    "skip the overlay layer" — body and corona still draw.
    """
    out = []
    for pSet in pSets:
        for obj in getattr(pSet, "_objects", {}).values():
            if not isinstance(obj, Sun):
                continue
            radius = obj.GetRadius()
            if radius <= 0:
                continue
            try:
                scale = float(obj.GetScale())
            except Exception:
                scale = 1.0
            loc = obj.GetWorldLocation()
            tex_rel = obj.GetModelPath() or _SUN_DEFAULT_TEXTURE
            abs_path = (project_root / "game" / tex_rel).resolve()
            if not abs_path.is_file():
                if not obj.__dict__.get("_sun_warned", False):
                    print(
                        f"[suns] texture not found: {tex_rel!r}; skipping",
                        flush=True,
                    )
                    obj.__dict__["_sun_warned"] = True
                continue

            flare_rel = getattr(obj, "_flare_texture", "") or ""
            flare_abs_str = ""
            if flare_rel:
                flare_abs = (project_root / "game" / flare_rel).resolve()
                if flare_abs.is_file():
                    flare_abs_str = str(flare_abs)
                elif not obj.__dict__.get("_flare_warned", False):
                    print(
                        f"[suns] flare texture not found: {flare_rel!r}; "
                        f"sun will render without overlay",
                        flush=True,
                    )
                    obj.__dict__["_flare_warned"] = True

            out.append({
                "position":           (loc.x, loc.y, loc.z),
                "radius":             radius * scale,
                "base_texture_path":  str(abs_path),
                "corona_radius":      radius * 1.1 * scale,
                "flare_texture_path": flare_abs_str,
            })
    return out
```

- [ ] **Step 2: Run the test — it should PASS**

Run: `uv run pytest tests/unit/test_host_loop_suns.py::test_aggregate_suns_applies_astro_scale -v`

Expected: PASS.

- [ ] **Step 3: Run the rest of the file's tests to make sure nothing else broke**

Run: `uv run pytest tests/unit/test_host_loop_suns.py -v`

Expected: All 6 tests pass. (`test_aggregate_suns_returns_empty_for_sun_with_no_texture` should still pass — that sun has no base_texture so it's dropped before the flare logic runs.)

- [ ] **Step 4: Commit**

```bash
git add engine/appc/planet.py
git commit -m "feat(suns): aggregator emits corona_radius=radius*1.1 + flare_texture_path

atmosphere_thickness is a gameplay-only parameter (AI keep-out radius)
and must not influence visual sizing. _flare_texture (Sun_Create arg 5)
now resolves to flare_texture_path; missing-file path warns once and
emits empty string for graceful skip in the renderer."
```

---

## Task 3: Add aggregator test for flare_texture_path edge cases

**Files:**
- Test: `tests/unit/test_host_loop_suns.py` (append)

- [ ] **Step 1: Add new tests**

Append to `tests/unit/test_host_loop_suns.py`:

```python
def test_aggregate_suns_empty_flare_path_when_no_flare_texture(tmp_path):
    """A Sun created without flare_texture emits flare_texture_path == ''."""
    import App
    from engine.appc.planet import Sun_Create
    from engine import host_loop
    import engine.host_loop as hl

    tex_rel = "data/Textures/SunNoFlare.tga"
    tex_abs = tmp_path / "game" / tex_rel
    tex_abs.parent.mkdir(parents=True)
    tex_abs.write_bytes(b"FAKE")

    pSet = App.SetClass_Create()
    pSun = Sun_Create(1000.0, 1000.0, 0.0, tex_rel)  # 4 args — no flare
    pSet.AddObjectToSet(pSun, "Sun")
    App.g_kSetManager.AddSet(pSet, "_test_agg_suns_no_flare")

    original_root = hl.PROJECT_ROOT
    hl.PROJECT_ROOT = tmp_path
    try:
        result = host_loop._aggregate_suns()
    finally:
        hl.PROJECT_ROOT = original_root
        App.g_kSetManager.DeleteSet("_test_agg_suns_no_flare")

    expected_tex = str(tex_abs.resolve())
    matches = [d for d in result if d["base_texture_path"] == expected_tex]
    assert len(matches) == 1
    assert matches[0]["flare_texture_path"] == ""


def test_aggregate_suns_empty_flare_path_when_flare_texture_missing(tmp_path, capsys):
    """A Sun whose flare_texture file is absent emits flare_texture_path == ''
    and warns once. Body and corona still emit normally."""
    import App
    from engine.appc.planet import Sun_Create
    from engine import host_loop
    import engine.host_loop as hl

    tex_rel = "data/Textures/SunMissingFlare.tga"
    tex_abs = tmp_path / "game" / tex_rel
    tex_abs.parent.mkdir(parents=True)
    tex_abs.write_bytes(b"FAKE")

    pSet = App.SetClass_Create()
    pSun = Sun_Create(1000.0, 1000.0, 0.0, tex_rel,
                      "data/Textures/Effects/Nonexistent.tga")
    pSet.AddObjectToSet(pSun, "Sun")
    App.g_kSetManager.AddSet(pSet, "_test_agg_suns_missing_flare")

    original_root = hl.PROJECT_ROOT
    hl.PROJECT_ROOT = tmp_path
    try:
        result = host_loop._aggregate_suns()
        # Call twice; the warning must only fire once.
        host_loop._aggregate_suns()
    finally:
        hl.PROJECT_ROOT = original_root
        App.g_kSetManager.DeleteSet("_test_agg_suns_missing_flare")

    expected_tex = str(tex_abs.resolve())
    matches = [d for d in result if d["base_texture_path"] == expected_tex]
    assert len(matches) == 1
    assert matches[0]["flare_texture_path"] == ""
    captured = capsys.readouterr()
    # Warning appears exactly once across two aggregator runs.
    assert captured.out.count("flare texture not found") == 1
```

- [ ] **Step 2: Run the new tests — expect PASS**

Run: `uv run pytest tests/unit/test_host_loop_suns.py::test_aggregate_suns_empty_flare_path_when_no_flare_texture tests/unit/test_host_loop_suns.py::test_aggregate_suns_empty_flare_path_when_flare_texture_missing -v`

Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_host_loop_suns.py
git commit -m "test(suns): cover flare_texture_path edge cases (unset, missing file)"
```

---

## Task 4: Update Python renderer wrapper docstring

**Files:**
- Modify: `engine/renderer.py:78-83`

- [ ] **Step 1: Update the `set_suns` docstring**

Open `engine/renderer.py`. Replace the `set_suns` function body docstring:

```python
def set_suns(suns: list) -> None:
    """Configure the renderer's sun list. Each entry is a dict:
        {"position": (x,y,z), "radius": float,
         "base_texture_path": str, "corona_radius": float,
         "flare_texture_path": str}
    flare_texture_path == "" disables the flare-overlay layer for that sun
    (body + corona still draw).
    """
    _h.set_suns(suns)
```

- [ ] **Step 2: Commit**

```bash
git add engine/renderer.py
git commit -m "docs(suns): document flare_texture_path in set_suns wrapper"
```

---

## Task 5: Add `flare_texture_path` to C++ SunDescriptor

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h:46-51`

- [ ] **Step 1: Extend the struct**

Open `native/src/renderer/include/renderer/frame.h`. Replace lines 46-51 (the `SunDescriptor` struct) with:

```cpp
struct SunDescriptor {
    glm::vec3   position;                  // world-space center
    float       radius        = 1.0f;      // body sphere radius (BC units)
    std::string base_texture_path;
    float       corona_radius = 0.0f;      // 0 = no corona; draw when > radius
    std::string flare_texture_path;        // empty = skip the SunEffect overlay
};
```

- [ ] **Step 2: Verify the project still compiles**

Run: `cmake --build build -j 2>&1 | tail -20`

Expected: SUCCESS (no consumers reference the new field yet).

- [ ] **Step 3: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h
git commit -m "feat(renderer): add flare_texture_path to SunDescriptor"
```

---

## Task 6: Parse `flare_texture_path` in host bindings

**Files:**
- Modify: `native/src/host/host_bindings.cc:486-503`

- [ ] **Step 1: Update the `set_suns` lambda**

Open `native/src/host/host_bindings.cc`. Replace the `set_suns` definition (the `m.def("set_suns", ...)` block at lines 486-503) with:

```cpp
    m.def("set_suns",
          [](const std::vector<py::dict>& descs) {
              g_suns.clear();
              g_suns.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::SunDescriptor s;
                  auto pos = d["position"].cast<std::tuple<float,float,float>>();
                  s.position           = {std::get<0>(pos),
                                          std::get<1>(pos),
                                          std::get<2>(pos)};
                  s.radius             = d["radius"].cast<float>();
                  s.base_texture_path  = d["base_texture_path"].cast<std::string>();
                  s.corona_radius      = d["corona_radius"].cast<float>();
                  s.flare_texture_path =
                      d.contains("flare_texture_path")
                          ? d["flare_texture_path"].cast<std::string>()
                          : std::string{};
                  g_suns.push_back(std::move(s));
              }
          },
          py::arg("suns"),
          "Set the active sun list, applied each frame().");
```

The `contains()` guard keeps the binding tolerant of older callers that haven't updated yet. The aggregator from Task 2 always emits the key, so in practice it's always present.

- [ ] **Step 2: Rebuild and verify**

Run: `cmake --build build -j 2>&1 | tail -10`

Expected: SUCCESS.

- [ ] **Step 3: Run python sun tests against the rebuilt binding**

Run: `uv run pytest tests/unit/test_host_loop_suns.py -v`

Expected: All 8 tests pass (6 original + 2 added in Task 3).

- [ ] **Step 4: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(host): set_suns binding accepts flare_texture_path"
```

---

## Task 7: Create the sun_flare shader pair

**Files:**
- Create: `native/src/renderer/shaders/sun_flare.vert`
- Create: `native/src/renderer/shaders/sun_flare.frag`

- [ ] **Step 1: Create `sun_flare.vert`**

Write to `native/src/renderer/shaders/sun_flare.vert`:

```glsl
#version 330 core

// Camera-aligned billboard for the BC SunEffect overlay layer.
// Drawn as 4 vertices in a TRIANGLE_STRIP with corners encoded in a_corner
// ((-1,-1), (1,-1), (-1,1), (1,1)). World-space center comes in as a
// uniform so we don't need a per-instance VBO.

layout(location=0) in vec2 a_corner;   // unit-square corner in [-1,1]^2

uniform mat4  u_proj;
uniform mat4  u_view;
uniform vec3  u_world_center;
uniform float u_half_size;

out vec2 v_uv;

void main() {
    // Right and up of the camera in world space: rows 0 and 1 of the
    // view matrix transposed (i.e. columns 0 and 1 of view^T).
    vec3 right = vec3(u_view[0][0], u_view[1][0], u_view[2][0]);
    vec3 up    = vec3(u_view[0][1], u_view[1][1], u_view[2][1]);
    vec3 world = u_world_center
               + right * (a_corner.x * u_half_size)
               + up    * (a_corner.y * u_half_size);
    gl_Position = u_proj * u_view * vec4(world, 1.0);
    v_uv = a_corner * 0.5 + 0.5;   // [-1,1]^2 → [0,1]^2
}
```

- [ ] **Step 2: Create `sun_flare.frag`**

Write to `native/src/renderer/shaders/sun_flare.frag`:

```glsl
#version 330 core

in vec2 v_uv;

uniform sampler2D u_texture;
uniform float     u_now_seconds;

out vec4 frag_color;

// Rotate the UV around (0.5, 0.5) by u_now_seconds * 0.0873 rad/s (~5°/s)
// for the slow solar-flare animation.
void main() {
    float angle = u_now_seconds * 0.0873;
    float c = cos(angle);
    float s = sin(angle);
    vec2 centered = v_uv - vec2(0.5);
    vec2 rotated  = vec2(c * centered.x - s * centered.y,
                         s * centered.x + c * centered.y);
    vec2 uv = rotated + vec2(0.5);
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) {
        // Outside the rotated source rect — emit nothing.
        frag_color = vec4(0.0);
        return;
    }
    vec4 tex = texture(u_texture, uv);
    // Additive blend is set on the GL state; output RGB * alpha so the
    // texture's alpha channel governs intensity.
    frag_color = vec4(tex.rgb * tex.a, tex.a);
}
```

- [ ] **Step 3: Commit (files only — not yet referenced from the build)**

```bash
git add native/src/renderer/shaders/sun_flare.vert native/src/renderer/shaders/sun_flare.frag
git commit -m "feat(renderer): add sun_flare shader pair for billboard overlay"
```

---

## Task 8: Register `sun_flare` in CMake + Pipeline

**Files:**
- Modify: `native/src/renderer/CMakeLists.txt:18-19` (insert two new `embed_shader` lines after)
- Modify: `native/src/renderer/include/renderer/pipeline.h`
- Modify: `native/src/renderer/pipeline.cc`

- [ ] **Step 1: Embed the new shaders**

Open `native/src/renderer/CMakeLists.txt`. Add two lines immediately after line 19 (the `SHADER_SUN_FS` line):

```cmake
embed_shader(SHADER_SUN_FLARE_VS shaders/sun_flare.vert sun_flare_vs)
embed_shader(SHADER_SUN_FLARE_FS shaders/sun_flare.frag sun_flare_fs)
```

- [ ] **Step 2: Add the accessor in `pipeline.h`**

Open `native/src/renderer/include/renderer/pipeline.h`. After the `sun_shader()` accessor at line 16, add:

```cpp
    Shader& sun_flare_shader() noexcept  { return *sun_flare_; }
```

After the `sun_` member at line 29, add:

```cpp
    std::unique_ptr<Shader> sun_flare_;
```

- [ ] **Step 3: Wire it in `pipeline.cc`**

Open `native/src/renderer/pipeline.cc`. After the `#include "embedded_sun_fs.h"` line, add:

```cpp
#include "embedded_sun_flare_vs.h"
#include "embedded_sun_flare_fs.h"
```

After the `sun_ = std::make_unique<...>` line in the constructor, add:

```cpp
    sun_flare_ = std::make_unique<Shader>(shader_src::sun_flare_vs, shader_src::sun_flare_fs);
```

- [ ] **Step 4: Rebuild**

Run: `cmake -B build -S . 2>&1 | tail -5 && cmake --build build -j 2>&1 | tail -10`

Expected: SUCCESS. (CMake re-runs because CMakeLists.txt changed, regenerating the embedded shader headers.)

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/CMakeLists.txt native/src/renderer/include/renderer/pipeline.h native/src/renderer/pipeline.cc
git commit -m "feat(renderer): register sun_flare shader in pipeline + CMake"
```

---

## Task 9: Drop corona opacity to 0.54 in sun.frag

**Files:**
- Modify: `native/src/renderer/shaders/sun.frag:18`

- [ ] **Step 1: Update the alpha multiplier**

Open `native/src/renderer/shaders/sun.frag`. On line 18, change:

```glsl
        frag_color = vec4(tex.rgb, tex.a * fade * 0.6);
```

to:

```glsl
        frag_color = vec4(tex.rgb, tex.a * fade * 0.54);
```

- [ ] **Step 2: Rebuild**

Run: `cmake --build build -j 2>&1 | tail -5`

Expected: SUCCESS.

- [ ] **Step 3: Commit**

```bash
git add native/src/renderer/shaders/sun.frag
git commit -m "fix(renderer): drop corona opacity 0.6 -> 0.54 for softer halo"
```

---

## Task 10: Remove fudge constants and name new ratios in sun_pass

**Files:**
- Modify: `native/src/renderer/sun_pass.cc:97-114`

- [ ] **Step 1: Update the constants and the math that consumes them**

Open `native/src/renderer/sun_pass.cc`. Replace lines 97-114 (the comment block from `// Visual fudge factors:` through `const float virtual_corona = ...`) with:

```cpp
    // The aggregator passes corona_radius = body_radius * 1.1, so the
    // sphere shell sits as a thin halo just outside the body. The flare
    // overlay billboard (drawn below) provides the wider visible bulk
    // that BC's SunEffect node renders.
    constexpr float kFlareOverlayRatio = 1.5f;  // half-size relative to body radius

    for (const auto& s : suns) {
        assets::Texture* tex = ensure_texture(s.base_texture_path);
        if (!tex) continue;

        const glm::vec3 cam_to_sun = s.position - camera.eye;
        const float true_distance = glm::length(cam_to_sun);
        if (true_distance < 1e-3f) continue;
        const float scale_factor = virtual_distance / true_distance;
        const glm::vec3 virtual_pos =
            camera.eye + (cam_to_sun / true_distance) * virtual_distance;
        const float virtual_radius = s.radius        * scale_factor;
        const float virtual_corona = s.corona_radius * scale_factor;
```

This removes both `kBodyVisualScale` and `kCoronaVisualScale`. The body now draws at the SDK-authored radius; the corona at the aggregator-supplied 1.1× radius. `kFlareOverlayRatio` is declared here so it's adjacent to the other size logic and used in the new draw added in Task 11.

- [ ] **Step 2: Rebuild and run the sun tests**

Run: `cmake --build build -j 2>&1 | tail -5 && ./build/native/tests/renderer/renderer_tests --gtest_filter='SunPassTest.*' 2>&1 | tail -20`

Expected: All 4 existing `SunPassTest` cases pass. Visuals will change in a follow-up task; the GL-error harness is the regression gate here.

> **If the test binary path differs:** find it with `find build -name 'renderer_tests' -type f 2>/dev/null`. Substitute the correct path everywhere it appears below.

- [ ] **Step 3: Commit**

```bash
git add native/src/renderer/sun_pass.cc
git commit -m "fix(renderer): drop kBodyVisualScale/kCoronaVisualScale fudge constants

Body draws at SDK radius; corona at aggregator-supplied 1.1x. Introduces
kFlareOverlayRatio=1.5 for the next task's billboard."
```

---

## Task 11: Thread `now_seconds` through SunPass::render

**Files:**
- Modify: `native/src/renderer/include/renderer/sun_pass.h:26-28`
- Modify: `native/src/renderer/sun_pass.cc:69-72`
- Modify: `native/src/host/host_bindings.cc:238` (and the `now` computation order)
- Modify: `native/tests/renderer/sun_pass_test.cc` (every `pass.render(...)` call)

- [ ] **Step 1: Update the header signature**

Open `native/src/renderer/include/renderer/sun_pass.h`. Replace lines 26-28 with:

```cpp
    void render(const std::vector<SunDescriptor>& suns,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                double now_seconds);
```

- [ ] **Step 2: Update the implementation signature**

Open `native/src/renderer/sun_pass.cc`. Replace lines 69-72 (the `void SunPass::render` declaration and opening brace) with:

```cpp
void SunPass::render(const std::vector<SunDescriptor>& suns,
                     const scenegraph::Camera& camera,
                     Pipeline& pipeline,
                     double now_seconds) {
    (void)now_seconds;  // used by the flare-overlay draw in Task 12
    if (suns.empty()) return;
```

- [ ] **Step 3: Update the host_bindings call site**

Open `native/src/host/host_bindings.cc`. Find the existing block at lines 237-245:

```cpp
    g_world.propagate();
    g_backdrop_pass->render(g_backdrops, g_camera, *g_pipeline);
    g_sun_pass->render(g_suns, g_camera, *g_pipeline);
    g_submitter->submit_opaque_in_pass(
        g_world, g_camera, *g_pipeline, lookup, g_lighting,
        scenegraph::Pass::Space);

    const double now = glfwGetTime();
    const float  dt  = static_cast<float>(now - g_prev_frame_time_seconds);
    g_prev_frame_time_seconds = now;
```

Reorder so `now` is computed before the sun-pass call, and pass it in:

```cpp
    g_world.propagate();
    g_backdrop_pass->render(g_backdrops, g_camera, *g_pipeline);

    const double now = glfwGetTime();
    const float  dt  = static_cast<float>(now - g_prev_frame_time_seconds);
    g_prev_frame_time_seconds = now;

    g_sun_pass->render(g_suns, g_camera, *g_pipeline, now);
    g_submitter->submit_opaque_in_pass(
        g_world, g_camera, *g_pipeline, lookup, g_lighting,
        scenegraph::Pass::Space);
```

- [ ] **Step 4: Update every `pass.render(...)` call in the test file**

Open `native/tests/renderer/sun_pass_test.cc`. Replace each of the five calls of the form `pass.render({...}, cam, *pipeline);` with `pass.render({...}, cam, *pipeline, 0.0);` — the test cases don't care about animation, so passing `0.0` is fine.

Use the Edit tool with these exact replacements (one per call site):

- `pass.render({}, cam, *pipeline);` → `pass.render({}, cam, *pipeline, 0.0);`
- `pass.render({s}, cam, *pipeline);` → `pass.render({s}, cam, *pipeline, 0.0);` (replace_all is safe here — every occurrence carries the same single-descriptor argument)
- `pass.render({s, s}, cam, *pipeline);` → `pass.render({s, s}, cam, *pipeline, 0.0);`

- [ ] **Step 5: Rebuild and run sun tests + python sun tests**

Run: `cmake --build build -j 2>&1 | tail -10`

Expected: SUCCESS.

Run: `./build/native/tests/renderer/renderer_tests --gtest_filter='SunPassTest.*' 2>&1 | tail -20`

Expected: 4 PASS.

Run: `uv run pytest tests/unit/test_host_loop_suns.py -v 2>&1 | tail -15`

Expected: 8 PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/sun_pass.h native/src/renderer/sun_pass.cc native/src/host/host_bindings.cc native/tests/renderer/sun_pass_test.cc
git commit -m "feat(renderer): thread now_seconds into SunPass::render

Required for the flare-overlay billboard's UV rotation. Host computes
glfwGetTime once before the sun pass and reuses for dust + lens flare."
```

---

## Task 12: Draw the flare-overlay billboard

**Files:**
- Modify: `native/src/renderer/sun_pass.cc` (add billboard draw inside the per-sun loop)
- Modify: `native/src/renderer/sun_pass.cc` (add VAO/VBO setup for a unit quad)
- Modify: `native/src/renderer/include/renderer/sun_pass.h` (private members for the quad)

- [ ] **Step 1: Add the quad-mesh members in the header**

Open `native/src/renderer/include/renderer/sun_pass.h`. Inside the `private:` section (after the existing `texture_cache_` member), add:

```cpp
    // Lazily-created unit-quad mesh for the flare-overlay billboard.
    // Layout: 4 vec2 corners ((-1,-1),(1,-1),(-1,1),(1,1)), drawn as a
    // GL_TRIANGLE_STRIP. The shader expands corners to world-space using
    // the camera view matrix and a uniform world center + half-size.
    std::uint32_t flare_quad_vao_ = 0;
    std::uint32_t flare_quad_vbo_ = 0;
    void ensure_flare_quad();
```

Also remove the stale `int target_tris = 256` default arg from `ensure_sphere` if you want — not required.

- [ ] **Step 2: Drop the `(void)now_seconds;` placeholder from Task 11**

Open `native/src/renderer/sun_pass.cc`. Remove the line `(void)now_seconds;` added in Task 11 Step 2.

- [ ] **Step 3: Add the quad setup and flare-overlay draw**

Open `native/src/renderer/sun_pass.cc`.

At the top of the file (after the existing includes), nothing changes.

In the destructor `SunPass::~SunPass()`, add quad cleanup just before the closing brace:

```cpp
SunPass::~SunPass() {
    if (flare_quad_vbo_) glDeleteBuffers(1, &flare_quad_vbo_);
    if (flare_quad_vao_) glDeleteVertexArrays(1, &flare_quad_vao_);
}
```

After `SunPass::ensure_texture(...)` (and before `SunPass::render`), add the new helper:

```cpp
void SunPass::ensure_flare_quad() {
    if (flare_quad_vao_ != 0) return;
    constexpr float kCorners[8] = {
        -1.0f, -1.0f,
         1.0f, -1.0f,
        -1.0f,  1.0f,
         1.0f,  1.0f,
    };
    glGenVertexArrays(1, &flare_quad_vao_);
    glBindVertexArray(flare_quad_vao_);
    glGenBuffers(1, &flare_quad_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, flare_quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(kCorners), kCorners, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, sizeof(float) * 2, nullptr);
    glEnableVertexAttribArray(0);
    glBindVertexArray(0);
}
```

Inside `SunPass::render`, **after** the corona-draw block (the `if (virtual_corona > virtual_radius) { ... }` that closes at what was line 144) and **before** the closing brace of the per-sun `for` loop, add the flare-overlay draw:

```cpp
        // Flare overlay: camera-facing additive billboard, slow UV rotation.
        // Skipped when flare_texture_path is empty or the texture fails to load.
        if (!s.flare_texture_path.empty()) {
            assets::Texture* flare_tex = ensure_texture(s.flare_texture_path);
            if (flare_tex) {
                ensure_flare_quad();
                auto& flare_shader = pipeline.sun_flare_shader();
                flare_shader.use();
                flare_shader.set_mat4("u_proj", camera.proj_matrix());
                flare_shader.set_mat4("u_view", camera.view_matrix());
                flare_shader.set_vec3("u_world_center", virtual_pos);
                flare_shader.set_float("u_half_size",
                    s.radius * scale_factor * kFlareOverlayRatio);
                flare_shader.set_float("u_now_seconds",
                    static_cast<float>(now_seconds));
                flare_shader.set_int("u_texture", 0);

                glEnable(GL_BLEND);
                glBlendFunc(GL_SRC_ALPHA, GL_ONE);
                glDepthMask(GL_FALSE);
                glDisable(GL_CULL_FACE);
                glActiveTexture(GL_TEXTURE0);
                glBindTexture(GL_TEXTURE_2D, flare_tex->id());
                glBindVertexArray(flare_quad_vao_);
                glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

                // Restore the sphere pass's state for the next iteration
                // of the suns loop. The outer cleanup at the end of
                // render() handles the final restore.
                glEnable(GL_CULL_FACE);
                glCullFace(GL_FRONT);
                glDepthMask(GL_TRUE);
                glDisable(GL_BLEND);
                glBindVertexArray(sphere->vao());
                shader.use();   // rebind sun shader for next iteration's body draw
            }
        }
```

- [ ] **Step 4: Rebuild and run all sun tests**

Run: `cmake --build build -j 2>&1 | tail -10`

Expected: SUCCESS.

Run: `./build/native/tests/renderer/renderer_tests --gtest_filter='SunPassTest.*' 2>&1 | tail -20`

Expected: 4 PASS. (The existing tests pass an empty `flare_texture_path` so the new code path is skipped.)

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/sun_pass.h native/src/renderer/sun_pass.cc
git commit -m "feat(renderer): draw rotating flare-overlay billboard from flare_texture

Third layer on top of body + corona. Camera-facing additive quad sized
to radius * 1.5; UVs rotate ~5 deg/s for the wispy SunEffect animation."
```

---

## Task 13: Add C++ tests for the new overlay path

**Files:**
- Modify: `native/tests/renderer/sun_pass_test.cc` (append two new tests before the closing `}` of the anonymous namespace)

- [ ] **Step 1: Append new test cases**

Open `native/tests/renderer/sun_pass_test.cc`. Just before the closing `}  // namespace`, add:

```cpp
TEST_F(SunPassTest, FlareTexturePathMissingFileProducesNoGLError) {
    renderer::SunPass pass;
    scenegraph::Camera cam;
    cam.eye    = {0, 0, 10000};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;

    renderer::SunDescriptor s;
    s.position           = {0.0f, 0.0f, 0.0f};
    s.radius             = 4000.0f;
    s.base_texture_path  = "/dev/null";
    s.corona_radius      = 4400.0f;
    s.flare_texture_path = "/dev/null/definitely/not-a-tga";

    pass.render({s}, cam, *pipeline, 0.0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(SunPassTest, EmptyFlareTexturePathSkipsOverlayWithoutError) {
    renderer::SunPass pass;
    scenegraph::Camera cam;
    cam.eye    = {0, 0, 10000};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;

    renderer::SunDescriptor s;
    s.position           = {0.0f, 0.0f, 0.0f};
    s.radius             = 4000.0f;
    s.base_texture_path  = "/dev/null";
    s.corona_radius      = 4400.0f;
    s.flare_texture_path = "";  // explicit: no overlay

    pass.render({s}, cam, *pipeline, 0.0);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}
```

- [ ] **Step 2: Build and run all SunPass tests**

Run: `cmake --build build -j 2>&1 | tail -5 && ./build/native/tests/renderer/renderer_tests --gtest_filter='SunPassTest.*' 2>&1 | tail -20`

Expected: 6 PASS (4 original + 2 new).

- [ ] **Step 3: Commit**

```bash
git add native/tests/renderer/sun_pass_test.cc
git commit -m "test(suns): cover flare_texture_path missing-file and empty paths"
```

---

## Task 14: Run full focused test pass + visual verification

**Files:** (none — verification only)

- [ ] **Step 1: Run all sun-related Python tests**

Run: `uv run pytest tests/unit/test_host_loop_suns.py tests/unit/test_appc_suns.py -v 2>&1 | tail -25`

Expected: All PASS. (`test_appc_suns.py` exercises the `Sun_Create` factory; verify it's unaffected.)

- [ ] **Step 2: Run renderer test binary's sun pass + lens flare suites**

Run: `./build/native/tests/renderer/renderer_tests --gtest_filter='SunPassTest.*:LensFlarePassTest.*' 2>&1 | tail -25`

Expected: All PASS.

- [ ] **Step 3: Launch the app and inspect a sun visually**

Per CLAUDE.md, the binary lives at `./build/dauntless`. Launch:

```bash
./build/dauntless
```

Pick a scene with an authored flare_texture (Tevron, Cebalrai, Artrus — see the SDK Systems list). Confirm:
- Body reads as a textured disc at roughly the size BC's screenshots show (smaller than the previous build's 2× fudge).
- Halo immediately around the body is soft, no visible facets.
- Wispy flare overlay drifts at a slow, visible-but-not-distracting rate.
- Lens flare's bright outer halo is unchanged (existing pass untouched).

For the Biranu scene (no flare_texture authored), confirm the sun still renders cleanly — body + thin corona only, no overlay, no warning spam after the first frame.

- [ ] **Step 4: Note any tuning observations**

If `kCoronaShellRatio` (now hardcoded `1.1` in the aggregator) or `kFlareOverlayRatio` (`1.5` in sun_pass.cc) reads visibly wrong, log the observation in the commit message of an immediate tuning follow-up — do not bury the value-change in this plan's commits.

- [ ] **Step 5: No code change here — nothing to commit**

If everything verifies, the branch is ready to merge or hand back to the user.

---

## Self-review notes (post-write, pre-execution)

- **Spec coverage:** All four §3 items mapped (Tasks 9-13 cover them). Layer table from spec §1 lines up with Tasks 5/7/8/12. Data flow §2 covered by Tasks 2/5/6.
- **Type consistency:** `flare_texture_path` is the field name everywhere (Python dict key, C++ struct, host binding key, shader uniform `u_texture` is unrelated). `kFlareOverlayRatio` and the `1.1` ratio in the aggregator are named at their respective levels; no name drift.
- **Placeholder scan:** None — every step has either complete code or an exact command.
- **Shader helpers confirmed:** `Shader::set_vec3`, `set_float`, `set_mat4`, `set_int`, `set_vec2` all exist on the header (`native/src/renderer/include/renderer/shader.h`). Task 12 uses each one as written.
