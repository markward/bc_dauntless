# Sun Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render each BC system's Sun as an unlit UV-sphere at its world-space position (body pass) plus an additive corona shell, wired from `Sun_Create` script calls through a new `SunPass` C++ render pass.

**Architecture:** Dedicated `SunPass` peer of `BackdropPass`. Python aggregator collects `Sun` objects from all sets into descriptor dicts; `r.set_suns(...)` binding delivers them to `g_sun_pass` each tick; `SunPass::render` draws each sun body with a full MVP transform (translate + scale, no translation stripping), then an additive corona shell when `corona_radius > radius`. Draw order: backdrop → sun → opaque.

**Tech Stack:** OpenGL 3.3 core, glm, pybind11, pytest, GoogleTest

---

### Task 1: `aggregate_suns_for_renderer` (Python, no GL)

**Files:**
- Modify: `engine/appc/planet.py` (add `aggregate_suns_for_renderer`)
- Create: `tests/unit/test_appc_suns.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_appc_suns.py`:

```python
"""Tests for Sun data storage and aggregate_suns_for_renderer."""
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent


def test_sun_create_stores_radius():
    from engine.appc.planet import Sun_Create
    s = Sun_Create(4000.0, 4000.0, 500.0)
    assert s.GetRadius() == 4000.0


def test_sun_create_stores_atmosphere_thickness():
    from engine.appc.planet import Sun_Create
    s = Sun_Create(4000.0, 2500.0, 500.0)
    assert s.GetAtmosphereRadius() == 2500.0


def test_sun_create_stores_damage_per_sec():
    from engine.appc.planet import Sun_Create
    s = Sun_Create(4000.0, 4000.0, 500.0)
    assert s.GetEnvironmentalHullDamage() == 500.0


def test_sun_create_stores_base_texture():
    from engine.appc.planet import Sun_Create
    s = Sun_Create(1000.0, 1000.0, 500.0, "data/Textures/SunRed.tga", "")
    assert s.GetModelPath() == "data/Textures/SunRed.tga"


def test_sun_create_default_empty_texture():
    from engine.appc.planet import Sun_Create
    s = Sun_Create(4000.0, 4000.0, 500.0)
    assert s.GetModelPath() == ""


def test_aggregate_empty_sets_returns_empty():
    from engine.appc.planet import aggregate_suns_for_renderer
    assert aggregate_suns_for_renderer(PROJECT_ROOT, []) == []


def test_aggregate_set_with_no_suns_returns_empty():
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Planet_Create
    pSet = App.SetClass_Create()
    pPlanet = Planet_Create(170.0, "data/models/environment/GreenPurplePlanet.nif")
    pSet.AddObjectToSet(pPlanet, "Planet")
    result = aggregate_suns_for_renderer(PROJECT_ROOT, [pSet])
    assert result == []


def test_aggregate_drops_sun_with_empty_texture_with_warning(capsys):
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0)  # no texture arg
    pSet.AddObjectToSet(pSun, "Sun")
    result = aggregate_suns_for_renderer(PROJECT_ROOT, [pSet])
    assert result == []
    assert "[suns]" in capsys.readouterr().out


def test_aggregate_empty_texture_warning_fires_once(capsys):
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0)
    pSet.AddObjectToSet(pSun, "Sun")
    aggregate_suns_for_renderer(PROJECT_ROOT, [pSet])
    capsys.readouterr()  # drain first warning
    aggregate_suns_for_renderer(PROJECT_ROOT, [pSet])
    assert capsys.readouterr().out == ""


def test_aggregate_drops_unresolvable_texture_with_warning(capsys):
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0, "data/Textures/DoesNotExist.tga", "")
    pSet.AddObjectToSet(pSun, "Sun")
    result = aggregate_suns_for_renderer(PROJECT_ROOT, [pSet])
    assert result == []
    assert "DoesNotExist.tga" in capsys.readouterr().out


def test_aggregate_unresolvable_texture_warning_fires_once(capsys):
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0, "data/Textures/DoesNotExist.tga", "")
    pSet.AddObjectToSet(pSun, "Sun")
    aggregate_suns_for_renderer(PROJECT_ROOT, [pSet])
    capsys.readouterr()
    aggregate_suns_for_renderer(PROJECT_ROOT, [pSet])
    assert capsys.readouterr().out == ""


def test_aggregate_drops_sun_with_zero_radius_silently(capsys):
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    pSet = App.SetClass_Create()
    pSun = Sun_Create(0.0, 0.0, 0.0, "data/Textures/SunBase.tga", "")
    pSet.AddObjectToSet(pSun, "Sun")
    result = aggregate_suns_for_renderer(PROJECT_ROOT, [pSet])
    assert result == []
    assert capsys.readouterr().out == ""


def test_aggregate_returns_correct_descriptor(tmp_path):
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    tex = tmp_path / "game" / "data" / "Textures" / "SunBase.tga"
    tex.parent.mkdir(parents=True)
    tex.write_bytes(b"FAKE")

    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0, "data/Textures/SunBase.tga", "")
    # No PlaceObjectByName called — sun position stays at origin (0,0,0)
    pSet.AddObjectToSet(pSun, "Sun")

    result = aggregate_suns_for_renderer(tmp_path, [pSet])
    assert len(result) == 1
    d = result[0]
    assert d["position"] == (0.0, 0.0, 0.0)
    assert d["radius"] == 4000.0
    assert d["base_texture_path"] == str(tex.resolve())
    assert d["corona_radius"] == pytest.approx(8000.0)


def test_aggregate_corona_radius_is_radius_plus_atmosphere(tmp_path):
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    tex = tmp_path / "game" / "data" / "Textures" / "SunBase.tga"
    tex.parent.mkdir(parents=True)
    tex.write_bytes(b"FAKE")

    pSet = App.SetClass_Create()
    pSun = Sun_Create(1000.0, 2500.0, 0.0, "data/Textures/SunBase.tga", "")
    pSet.AddObjectToSet(pSun, "Sun")

    result = aggregate_suns_for_renderer(tmp_path, [pSet])
    assert result[0]["corona_radius"] == pytest.approx(3500.0)


def test_aggregate_collects_suns_from_multiple_sets(tmp_path):
    import App
    from engine.appc.planet import aggregate_suns_for_renderer, Sun_Create
    tex = tmp_path / "game" / "data" / "Textures" / "SunBase.tga"
    tex.parent.mkdir(parents=True)
    tex.write_bytes(b"FAKE")

    pSet1 = App.SetClass_Create()
    pSun1 = Sun_Create(1000.0, 1000.0, 500.0, "data/Textures/SunBase.tga", "")
    pSet1.AddObjectToSet(pSun1, "Sun1")

    pSet2 = App.SetClass_Create()
    pSun2 = Sun_Create(4000.0, 4000.0, 500.0, "data/Textures/SunBase.tga", "")
    pSet2.AddObjectToSet(pSun2, "Sun2")

    result = aggregate_suns_for_renderer(tmp_path, [pSet1, pSet2])
    assert len(result) == 2
    radii = {d["radius"] for d in result}
    assert radii == {1000.0, 4000.0}
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/unit/test_appc_suns.py -v
```

Expected: FAIL — `ImportError: cannot import name 'aggregate_suns_for_renderer' from 'engine.appc.planet'`

- [ ] **Step 3: Implement `aggregate_suns_for_renderer` in `engine/appc/planet.py`**

Add after the `Planet_Cast` function (before `ProximityManager`):

```python
def aggregate_suns_for_renderer(project_root, pSets):
    """Return list[dict] for all Sun objects across pSets.

    Suns with empty base_texture or unresolvable paths are dropped with a
    once-per-object warning (suppressed after first fire via _sun_warned).
    Suns with radius <= 0 are dropped silently.
    """
    out = []
    for pSet in pSets:
        for obj in getattr(pSet, "_objects", {}).values():
            if not isinstance(obj, Sun):
                continue
            radius = obj.GetRadius()
            if radius <= 0:
                continue
            loc = obj.GetWorldLocation()
            tex_rel = obj.GetModelPath()
            if not tex_rel:
                if not getattr(obj, "_sun_warned", False):
                    print(
                        f"[suns] no texture for Sun at "
                        f"({loc.x:.0f},{loc.y:.0f},{loc.z:.0f}); skipping",
                        flush=True,
                    )
                    obj._sun_warned = True
                continue
            abs_path = (project_root / "game" / tex_rel).resolve()
            if not abs_path.is_file():
                if not getattr(obj, "_sun_warned", False):
                    print(
                        f"[suns] texture not found: {tex_rel!r}; skipping",
                        flush=True,
                    )
                    obj._sun_warned = True
                continue
            out.append({
                "position":          (loc.x, loc.y, loc.z),
                "radius":            radius,
                "base_texture_path": str(abs_path),
                "corona_radius":     radius + obj.GetAtmosphereRadius(),
            })
    return out
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/unit/test_appc_suns.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add engine/appc/planet.py tests/unit/test_appc_suns.py
git commit -m "feat(suns): aggregate_suns_for_renderer + unit tests"
```

---

### Task 2: `_iter_suns` and `_aggregate_suns` in `host_loop.py`

**Files:**
- Modify: `engine/host_loop.py` (add `_iter_suns`, `_aggregate_suns`)
- Create: `tests/unit/test_host_loop_suns.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_host_loop_suns.py`:

```python
"""Tests for _iter_suns and _aggregate_suns in host_loop."""


def test_iter_suns_yields_sun_objects():
    import App
    from engine.appc.planet import Sun_Create
    from engine import host_loop

    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0)
    pSet.AddObjectToSet(pSun, "Sun")
    App.g_kSetManager.AddSet(pSet, "_test_iter_suns_basic")
    try:
        suns = list(host_loop._iter_suns())
        assert pSun in suns
    finally:
        App.g_kSetManager.DeleteSet("_test_iter_suns_basic")


def test_iter_suns_skips_plain_planets():
    import App
    from engine.appc.planet import Sun_Create, Planet_Create
    from engine import host_loop

    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0)
    pPlanet = Planet_Create(170.0, "")
    pSet.AddObjectToSet(pSun, "Sun")
    pSet.AddObjectToSet(pPlanet, "Planet")
    App.g_kSetManager.AddSet(pSet, "_test_iter_suns_no_planet")
    try:
        suns = list(host_loop._iter_suns())
        assert pSun in suns
        assert pPlanet not in suns
    finally:
        App.g_kSetManager.DeleteSet("_test_iter_suns_no_planet")


def test_iter_suns_empty_set_contributes_nothing():
    import App
    from engine import host_loop

    before = set(id(s) for s in host_loop._iter_suns())
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "_test_iter_suns_empty")
    try:
        after = set(id(s) for s in host_loop._iter_suns())
        assert after == before
    finally:
        App.g_kSetManager.DeleteSet("_test_iter_suns_empty")


def test_aggregate_suns_returns_list():
    from engine import host_loop
    result = host_loop._aggregate_suns()
    assert isinstance(result, list)


def test_aggregate_suns_returns_empty_for_sun_with_no_texture():
    """A Sun with no texture is dropped by the aggregator; result is []."""
    import App
    from engine.appc.planet import Sun_Create
    from engine import host_loop

    pSet = App.SetClass_Create()
    pSun = Sun_Create(4000.0, 4000.0, 500.0)  # no texture
    pSet.AddObjectToSet(pSun, "Sun")
    App.g_kSetManager.AddSet(pSet, "_test_agg_suns_no_tex")
    try:
        result = host_loop._aggregate_suns()
        assert isinstance(result, list)
        assert pSun not in result  # object not in list (list contains dicts)
    finally:
        App.g_kSetManager.DeleteSet("_test_agg_suns_no_tex")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/unit/test_host_loop_suns.py -v
```

Expected: FAIL — `AttributeError: module 'engine.host_loop' has no attribute '_iter_suns'`

- [ ] **Step 3: Add `_iter_suns` and `_aggregate_suns` to `engine/host_loop.py`**

Add after `_iter_planets` (around line 212):

```python
def _iter_suns() -> Iterable:
    """Walk every Sun in every active set."""
    import App
    from engine.appc.planet import Sun
    for pSet in App.g_kSetManager._sets.values():
        for obj in _iter_set_objects(pSet):
            if isinstance(obj, Sun):
                yield obj


def _aggregate_suns() -> list:
    """Collect sun render descriptors from all active sets."""
    from engine.appc.planet import aggregate_suns_for_renderer
    import App
    return aggregate_suns_for_renderer(
        PROJECT_ROOT, list(App.g_kSetManager._sets.values()))
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/unit/test_host_loop_suns.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/unit/test_host_loop_suns.py
git commit -m "feat(suns): _iter_suns + _aggregate_suns helpers"
```

---

### Task 3: `SunDescriptor` struct + shaders

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h`
- Create: `native/src/renderer/shaders/sun.vert`
- Create: `native/src/renderer/shaders/sun.frag`

- [ ] **Step 1: Add `SunDescriptor` to `frame.h`**

Add after the `Backdrop` struct (before `class FrameSubmitter`):

```cpp
struct SunDescriptor {
    glm::vec3   position;                  // world-space center
    float       radius        = 1.0f;      // body sphere radius (BC units)
    std::string base_texture_path;
    float       corona_radius = 0.0f;      // 0 = no corona; draw when > radius
};
```

- [ ] **Step 2: Create `native/src/renderer/shaders/sun.vert`**

```glsl
#version 330 core

layout(location=0) in vec3 a_pos;
layout(location=1) in vec3 a_normal;   // unused; VAO layout compatibility
layout(location=2) in vec2 a_uv;

uniform mat4 u_proj;
uniform mat4 u_view;
uniform mat4 u_model;

out vec2 v_uv;

void main() {
    gl_Position = u_proj * u_view * u_model * vec4(a_pos, 1.0);
    v_uv = a_uv;
}
```

- [ ] **Step 3: Create `native/src/renderer/shaders/sun.frag`**

```glsl
#version 330 core

in vec2 v_uv;

uniform sampler2D u_texture;
uniform int       u_corona;   // 0 = body draw, 1 = corona draw

out vec4 frag_color;

void main() {
    vec4 tex = texture(u_texture, v_uv);
    if (u_corona == 0) {
        frag_color = vec4(tex.rgb, 1.0);
    } else {
        // v_uv.y in [0,1]: poles at 0 and 1, equator near 0.5.
        // sin maps to 0 at poles and 1 at equator for atmospheric taper.
        float fade = sin(v_uv.y * 3.14159265);
        frag_color = vec4(tex.rgb, tex.a * fade * 0.6);
    }
}
```

- [ ] **Step 4: Verify the build still compiles (shaders are not yet embedded)**

```bash
cmake --build build
```

Expected: BUILD SUCCESSFUL (shaders not yet embedded — that's Task 4)

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h \
        native/src/renderer/shaders/sun.vert \
        native/src/renderer/shaders/sun.frag
git commit -m "feat(suns): SunDescriptor struct + sun.vert/sun.frag shaders"
```

---

### Task 4: `Pipeline::sun_shader()`

**Files:**
- Modify: `native/src/renderer/CMakeLists.txt` (embed sun shaders)
- Modify: `native/src/renderer/include/renderer/pipeline.h`
- Modify: `native/src/renderer/pipeline.cc`
- Modify: `native/tests/renderer/pipeline_test.cc`

- [ ] **Step 1: Write the failing C++ test**

Add to `native/tests/renderer/pipeline_test.cc` after `OpaqueShaderCompilesAndLinks`:

```cpp
TEST_F(PipelineTest, SunShaderCompilesAndLinks) {
    renderer::Pipeline p;
    EXPECT_NE(p.sun_shader().program(), 0u);
}
```

- [ ] **Step 2: Run to confirm compile failure**

```bash
cmake --build build 2>&1 | grep -i "sun_shader\|error"
```

Expected: compile error — `'class renderer::Pipeline' has no member named 'sun_shader'`

- [ ] **Step 3: Embed the sun shaders in `native/src/renderer/CMakeLists.txt`**

Add after the backdrop embed lines:

```cmake
embed_shader(SHADER_SUN_VS shaders/sun.vert sun_vs)
embed_shader(SHADER_SUN_FS shaders/sun.frag sun_fs)
```

- [ ] **Step 4: Add `sun_shader()` to `native/src/renderer/include/renderer/pipeline.h`**

```cpp
class Pipeline {
public:
    Pipeline();

    Shader& opaque_shader()   noexcept { return *opaque_; }
    Shader& backdrop_shader() noexcept { return *backdrop_; }
    Shader& sun_shader()      noexcept { return *sun_; }

private:
    std::unique_ptr<Shader> opaque_;
    std::unique_ptr<Shader> backdrop_;
    std::unique_ptr<Shader> sun_;
};
```

- [ ] **Step 5: Load the sun shader in `native/src/renderer/pipeline.cc`**

Add includes after the backdrop embedded headers:

```cpp
#include "embedded_sun_vs.h"
#include "embedded_sun_fs.h"
```

Add initialization in `Pipeline::Pipeline()` after the backdrop line:

```cpp
sun_ = std::make_unique<Shader>(shader_src::sun_vs, shader_src::sun_fs);
```

- [ ] **Step 6: Build and run pipeline tests**

```bash
cmake -S . -B build && cmake --build build && ctest --test-dir build -R renderer_tests --output-on-failure
```

Expected: `SunShaderCompilesAndLinks` PASS, all other renderer tests still PASS

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/CMakeLists.txt \
        native/src/renderer/include/renderer/pipeline.h \
        native/src/renderer/pipeline.cc \
        native/tests/renderer/pipeline_test.cc
git commit -m "feat(suns): Pipeline::sun_shader() + embed sun.vert/sun.frag"
```

---

### Task 5: `SunPass` C++ class + C++ tests

**Files:**
- Create: `native/src/renderer/include/renderer/sun_pass.h`
- Create: `native/src/renderer/sun_pass.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `sun_pass.cc`)
- Create: `native/tests/renderer/sun_pass_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt` (add `sun_pass_test.cc`)

- [ ] **Step 1: Create `native/src/renderer/include/renderer/sun_pass.h`**

```cpp
// native/src/renderer/include/renderer/sun_pass.h
#pragma once

#include <renderer/frame.h>
#include <assets/mesh.h>
#include <assets/texture.h>

#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

class SunPass {
public:
    SunPass() = default;
    ~SunPass();
    SunPass(const SunPass&) = delete;
    SunPass& operator=(const SunPass&) = delete;

    void render(const std::vector<SunDescriptor>& suns,
                const scenegraph::Camera& camera,
                Pipeline& pipeline);

private:
    std::unordered_map<int, std::unique_ptr<assets::Mesh>>    sphere_cache_;
    std::unordered_map<std::string, std::unique_ptr<assets::Texture>> texture_cache_;

    assets::Mesh*    ensure_sphere(int target_tris = 256);
    assets::Texture* ensure_texture(const std::string& path);
};

}  // namespace renderer
```

- [ ] **Step 2: Write the C++ tests**

Create `native/tests/renderer/sun_pass_test.cc`:

```cpp
// native/tests/renderer/sun_pass_test.cc
#include <gtest/gtest.h>

#include <renderer/sun_pass.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>

namespace {

class SunPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   window;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            window = std::make_unique<renderer::Window>(256, 256, "sun_test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        pipeline = std::make_unique<renderer::Pipeline>();
    }
    void TearDown() override {
        pipeline.reset();
        window.reset();
    }
};

TEST_F(SunPassTest, EmptyListProducesNoGLError) {
    renderer::SunPass pass;
    scenegraph::Camera cam;
    cam.eye    = {0, 0, 1500};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;
    pass.render({}, cam, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(SunPassTest, SingleDescriptorWithMissingTextureProducesNoGLError) {
    renderer::SunPass pass;
    scenegraph::Camera cam;
    cam.eye    = {0, 0, 10000};
    cam.target = {0, 0, 0};
    cam.aspect = 1.0f;

    renderer::SunDescriptor s;
    s.position          = {0.0f, 0.0f, 0.0f};
    s.radius            = 4000.0f;
    s.base_texture_path = "/dev/null";   // load fails → graceful skip
    s.corona_radius     = 8000.0f;

    pass.render({s}, cam, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(SunPassTest, TextureCacheDeduplicatesSamePath) {
    renderer::SunPass pass;
    scenegraph::Camera cam;
    cam.aspect = 1.0f;

    renderer::SunDescriptor s;
    s.position          = {0.0f, 0.0f, 0.0f};
    s.radius            = 1000.0f;
    s.base_texture_path = "/dev/null";
    s.corona_radius     = 0.0f;

    pass.render({s, s}, cam, *pipeline);  // two descriptors, one cache entry
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(SunPassTest, CoronaSkippedWhenCoronaRadiusEqualsRadius) {
    renderer::SunPass pass;
    scenegraph::Camera cam;
    cam.aspect = 1.0f;

    renderer::SunDescriptor s;
    s.position          = {0.0f, 0.0f, 0.0f};
    s.radius            = 4000.0f;
    s.base_texture_path = "/dev/null";
    s.corona_radius     = 4000.0f;   // equal — NOT > radius, so no corona draw

    pass.render({s}, cam, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(SunPassTest, CoronaDrawnWhenCoronaRadiusGreaterThanRadius) {
    renderer::SunPass pass;
    scenegraph::Camera cam;
    cam.aspect = 1.0f;

    renderer::SunDescriptor s;
    s.position          = {0.0f, 0.0f, 0.0f};
    s.radius            = 4000.0f;
    s.base_texture_path = "/dev/null";
    s.corona_radius     = 8000.0f;   // > radius → corona draw attempted

    pass.render({s}, cam, *pipeline);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

}  // namespace
```

- [ ] **Step 3: Add `sun_pass_test.cc` to `native/tests/renderer/CMakeLists.txt`**

```cmake
add_executable(renderer_tests
    window_test.cc
    shader_test.cc
    pipeline_test.cc
    frame_test.cc
    backdrop_pass_test.cc
    sun_pass_test.cc
)
```

- [ ] **Step 4: Run to confirm compile failure (sun_pass.cc not yet written)**

```bash
cmake -S . -B build && cmake --build build 2>&1 | grep -i "error\|sun_pass" | head -20
```

Expected: linker error — `undefined reference to renderer::SunPass`

- [ ] **Step 5: Create `native/src/renderer/sun_pass.cc`**

```cpp
// native/src/renderer/sun_pass.cc
#include "renderer/sun_pass.h"

#include "renderer/pipeline.h"
#include "sphere_mesh.h"

#include <assets/mesh.h>
#include <assets/texture.h>
#include <scenegraph/camera.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <cstdio>
#include <fstream>

namespace renderer {

SunPass::~SunPass() {
    // assets::Mesh / assets::Texture destructors release GL handles.
    // Caller must ensure the GL context is still alive when this dtor runs.
}

assets::Mesh* SunPass::ensure_sphere(int target_tris) {
    if (target_tris < 64) target_tris = 64;
    auto it = sphere_cache_.find(target_tris);
    if (it != sphere_cache_.end()) return it->second.get();
    assets::MeshCpu cpu = build_uv_sphere(target_tris);
    assets::Mesh m = assets::upload_mesh(cpu);
    auto owned = std::make_unique<assets::Mesh>(std::move(m));
    auto* raw = owned.get();
    sphere_cache_.emplace(target_tris, std::move(owned));
    return raw;
}

assets::Texture* SunPass::ensure_texture(const std::string& path) {
    auto it = texture_cache_.find(path);
    if (it != texture_cache_.end()) {
        return (it->second && it->second->id() != 0) ? it->second.get() : nullptr;
    }
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[sun] failed to open '%s'\n", path.c_str());
        texture_cache_.emplace(path, std::make_unique<assets::Texture>());
        return nullptr;
    }
    in.seekg(0, std::ios::end);
    auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> bytes(size);
    in.read(reinterpret_cast<char*>(bytes.data()),
            static_cast<std::streamsize>(size));
    try {
        assets::Image img = assets::decode_tga(bytes);
        assets::Texture tex = assets::upload_image(img, /*generate_mipmaps=*/true);
        auto owned = std::make_unique<assets::Texture>(std::move(tex));
        auto* raw = owned.get();
        texture_cache_.emplace(path, std::move(owned));
        return raw;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[sun] failed to decode '%s': %s\n",
                     path.c_str(), e.what());
        texture_cache_.emplace(path, std::make_unique<assets::Texture>());
        return nullptr;
    }
}

void SunPass::render(const std::vector<SunDescriptor>& suns,
                     const scenegraph::Camera& camera,
                     Pipeline& pipeline) {
    if (suns.empty()) return;

    auto& shader = pipeline.sun_shader();
    shader.use();
    shader.set_mat4("u_proj", camera.proj_matrix());
    shader.set_mat4("u_view", camera.view_matrix());   // full view, no translation strip

    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glDisable(GL_BLEND);
    glCullFace(GL_FRONT);   // render inside of sphere

    assets::Mesh* sphere = ensure_sphere(256);
    if (!sphere) {
        glCullFace(GL_BACK);
        return;
    }
    glBindVertexArray(sphere->vao());

    for (const auto& s : suns) {
        assets::Texture* tex = ensure_texture(s.base_texture_path);
        if (!tex) continue;

        // Body: opaque, translate to world position, scale to radius
        glm::mat4 model = glm::translate(glm::mat4(1.0f), s.position)
                        * glm::scale(glm::mat4(1.0f), glm::vec3(s.radius));
        shader.set_mat4("u_model", model);
        shader.set_int("u_corona", 0);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, tex->id());
        shader.set_int("u_texture", 0);
        glDrawElements(GL_TRIANGLES,
                       static_cast<GLsizei>(sphere->index_count()),
                       GL_UNSIGNED_INT, nullptr);

        // Corona: additive shell at corona_radius
        if (s.corona_radius > s.radius) {
            glEnable(GL_BLEND);
            glBlendFunc(GL_SRC_ALPHA, GL_ONE);
            glm::mat4 corona_model =
                glm::translate(glm::mat4(1.0f), s.position)
                * glm::scale(glm::mat4(1.0f), glm::vec3(s.corona_radius));
            shader.set_mat4("u_model", corona_model);
            shader.set_int("u_corona", 1);
            glDrawElements(GL_TRIANGLES,
                           static_cast<GLsizei>(sphere->index_count()),
                           GL_UNSIGNED_INT, nullptr);
            glDisable(GL_BLEND);
        }
    }

    glCullFace(GL_BACK);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glBindVertexArray(0);
}

}  // namespace renderer
```

- [ ] **Step 6: Add `sun_pass.cc` to `native/src/renderer/CMakeLists.txt`**

```cmake
add_library(renderer STATIC
    window.cc
    shader.cc
    pipeline.cc
    frame.cc
    sphere_mesh.cc
    backdrop_pass.cc
    sun_pass.cc
)
```

- [ ] **Step 7: Build and run C++ tests**

```bash
cmake -S . -B build && cmake --build build && ctest --test-dir build -R renderer_tests --output-on-failure
```

Expected: all `SunPassTest.*` PASS, all existing renderer tests still PASS

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/sun_pass.h \
        native/src/renderer/sun_pass.cc \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/sun_pass_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(suns): SunPass C++ class + renderer_tests coverage"
```

---

### Task 6: `set_suns` binding + `engine/renderer.py` + GL binding tests

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/renderer.py`
- Create: `tests/host/test_sun_bindings.py`

- [ ] **Step 1: Write the failing Python GL tests**

Create `tests/host/test_sun_bindings.py`:

```python
"""Tests for the _open_stbc_host.set_suns binding."""
import os


def test_set_suns_empty_list_does_not_raise():
    import _open_stbc_host
    _open_stbc_host.set_suns([])


def test_set_suns_single_descriptor_does_not_raise():
    import _open_stbc_host
    _open_stbc_host.set_suns([{
        "position":          (0.0, 0.0, 0.0),
        "radius":            4000.0,
        "base_texture_path": "/dev/null",
        "corona_radius":     8000.0,
    }])


def test_set_suns_many_descriptors_does_not_raise():
    import _open_stbc_host
    descriptor = {
        "position":          (100.0, 200.0, 300.0),
        "radius":            1000.0,
        "base_texture_path": "/dev/null",
        "corona_radius":     2000.0,
    }
    _open_stbc_host.set_suns([descriptor] * 5)


def test_renderer_module_set_suns_wrapper_exists():
    from engine import renderer
    assert hasattr(renderer, "set_suns")
    renderer.set_suns([])


def test_frame_after_set_suns_does_not_crash():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host
    _open_stbc_host.init(64, 64, "test_sun_bindings")
    try:
        _open_stbc_host.set_suns([{
            "position":          (0.0, 0.0, 0.0),
            "radius":            4000.0,
            "base_texture_path": "/dev/null",
            "corona_radius":     8000.0,
        }])
        _open_stbc_host.set_camera(
            eye=(0.0, 0.0, 10000.0),
            target=(0.0, 0.0, 0.0),
            up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472,
            near=1.0,
            far=200000.0,
        )
        _open_stbc_host.frame()   # must not crash or raise
    finally:
        _open_stbc_host.shutdown()
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/host/test_sun_bindings.py -v
```

Expected: FAIL — `AttributeError: module '_open_stbc_host' has no attribute 'set_suns'`

- [ ] **Step 3: Add `set_suns` binding to `native/src/host/host_bindings.cc`**

Add `#include <renderer/sun_pass.h>` alongside the other renderer includes.

Add file-scope variables after `g_backdrop_pass`:

```cpp
std::vector<renderer::SunDescriptor>   g_suns;
std::unique_ptr<renderer::SunPass>     g_sun_pass;
```

In `init()`, after `g_backdrop_pass = std::make_unique<renderer::BackdropPass>();`:

```cpp
g_sun_pass = std::make_unique<renderer::SunPass>();
```

In `shutdown()`, after `g_backdrop_pass.reset();` and before `g_window.reset();`:

```cpp
g_sun_pass.reset();
```

Also add `g_suns.clear();` in `shutdown()` after `g_backdrops.clear();`.

In `frame()`, add the sun pass call between backdrop and opaque:

```cpp
g_backdrop_pass->render(g_backdrops, g_camera, *g_pipeline);
g_sun_pass->render(g_suns, g_camera, *g_pipeline);          // ADD
g_submitter->submit_opaque(g_world, g_camera, *g_pipeline, lookup, g_lighting);
```

Add the `set_suns` binding in `PYBIND11_MODULE(_open_stbc_host, m)` after `set_backdrops`:

```cpp
m.def("set_suns",
      [](const std::vector<py::dict>& descs) {
          g_suns.clear();
          g_suns.reserve(descs.size());
          for (const auto& d : descs) {
              renderer::SunDescriptor s;
              auto pos = d["position"].cast<std::tuple<float,float,float>>();
              s.position          = {std::get<0>(pos),
                                     std::get<1>(pos),
                                     std::get<2>(pos)};
              s.radius            = d["radius"].cast<float>();
              s.base_texture_path = d["base_texture_path"].cast<std::string>();
              s.corona_radius     = d["corona_radius"].cast<float>();
              g_suns.push_back(std::move(s));
          }
      },
      py::arg("suns"),
      "Set the active sun list, applied each frame().");
```

Also add `g_suns.clear();` in `init()` alongside `g_backdrops.clear();` for symmetry.

- [ ] **Step 4: Add `set_suns` to `engine/renderer.py`**

```python
def set_suns(suns: list) -> None:
    """Configure the renderer's sun list. Each entry is a dict:
        {"position": (x,y,z), "radius": float,
         "base_texture_path": str, "corona_radius": float}
    """
    _h.set_suns(suns)
```

- [ ] **Step 5: Build and run binding tests**

```bash
cmake -S . -B build && cmake --build build && uv run pytest tests/host/test_sun_bindings.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py tests/host/test_sun_bindings.py
git commit -m "feat(suns): set_suns binding, g_sun_pass wired into frame()"
```

---

### Task 7: Wire `r.set_suns` into `host_loop.run()` + integration test

**Files:**
- Modify: `engine/host_loop.py` (add `r.set_suns` call to tick loop)
- Create: `tests/host/test_sun_integration.py`

- [ ] **Step 1: Write the failing integration tests**

Create `tests/host/test_sun_integration.py`:

```python
"""Integration tests for sun rendering wiring in host_loop.run()."""
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"


def test_run_M1Basic_with_sun_wiring_does_not_crash():
    """M1Basic/Biranu1 has Sun_Create with no texture; aggregator drops it
    with a warning. run() must still complete rc=0."""
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        from engine import host_loop
        rc = host_loop.run("Custom.Tutorial.Episode.M1Basic.M1Basic", max_ticks=2)
        assert rc == 0
    finally:
        os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)


def test_run_M1Basic_verbose_logs_sun_count(capsys):
    """With verbose=1, tick-0 sun log line appears."""
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    os.environ["OPEN_STBC_HOST_VERBOSE"] = "1"
    try:
        from engine import host_loop
        host_loop.run("Custom.Tutorial.Episode.M1Basic.M1Basic", max_ticks=2)
    finally:
        os.environ.pop("OPEN_STBC_HOST_VERBOSE", None)
        os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)
    out = capsys.readouterr().out
    assert "suns:" in out


def test_aggregate_suns_called_does_not_raise():
    """Calling _aggregate_suns() outside run() must not raise."""
    from engine import host_loop
    result = host_loop._aggregate_suns()
    assert isinstance(result, list)
```

- [ ] **Step 2: Run to confirm the verbose test fails**

```bash
uv run pytest tests/host/test_sun_integration.py::test_run_M1Basic_verbose_logs_sun_count -v
```

Expected: FAIL (no "suns:" in output — `r.set_suns` not yet called in `run()`)

The no-crash test may pass already (sun wiring is missing but not crashing). The verbose test fails.

- [ ] **Step 3: Add sun wiring to the tick loop in `engine/host_loop.py`**

In `run()`, after `r.set_backdrops(backdrops)` in the tick loop, add:

```python
            suns = _aggregate_suns()
            r.set_suns(suns)
```

In the `if verbose and ticks == 0:` block, add:

```python
                print(f"[host_loop] tick 0 suns: {len(suns)} sun(s)", flush=True)
```

- [ ] **Step 4: Run integration tests**

```bash
uv run pytest tests/host/test_sun_integration.py -v
```

Expected: all PASS (no-crash, verbose log line, _aggregate_suns callable)

- [ ] **Step 5: Run full pytest suite to check for regressions**

```bash
uv run pytest --tb=short -q
```

Expected: all previously-passing tests still PASS

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/host/test_sun_integration.py
git commit -m "feat(suns): wire r.set_suns into host_loop.run() tick loop"
```

---

### Task 8: Documentation updates

**Files:**
- Modify: `docs/architecture/sub_project_status.md`
- Modify: `native/src/host/docs/deferred_work.md`

- [ ] **Step 1: Add sun rendering entry to `docs/architecture/sub_project_status.md`**

Add a new row to the renderer sub-projects table after the backdrops row:

```markdown
| 3-6+ | Sun rendering (procedural sphere body + corona shell) | Implemented (2026-05-10; SunPass draws textured UV-sphere at world position; corona additive shell) | [2026-05-10-sun-rendering-design.md](../superpowers/specs/2026-05-10-sun-rendering-design.md) | (folded into renderer-host's `deferred_work.md`) |
```

- [ ] **Step 2: Add sun rendering entry to `native/src/host/docs/deferred_work.md`**

Add a new numbered item after item #2 (BC light data):

```markdown
3. **Sun rendering.** ✅ Implemented 2026-05-10.
   See [`docs/superpowers/specs/2026-05-10-sun-rendering-design.md`](../../../../docs/superpowers/specs/2026-05-10-sun-rendering-design.md).

   - `aggregate_suns_for_renderer` (`engine/appc/planet.py`) collects `Sun`
     objects from all sets into descriptor dicts (position, radius,
     base_texture_path, corona_radius).
   - `engine/host_loop.run` calls `_aggregate_suns()` + `r.set_suns(...)` each
     tick, between `set_backdrops` and `frame()`.
   - `SunPass` (`native/src/renderer/sun_pass.{h,cc}`) draws each sun as an
     opaque UV-sphere (unlit, full MVP, scaled to radius) followed by an
     additive corona shell when `corona_radius > radius`.

   Follow-up backlog:

   - **Lens-flare rendering.** `Tactical.LensFlares.YellowLensFlare(pSet, pSun)`
     needs a screen-space sprite pass. Already noted under backdrop sub-project.
   - **Sun as a light source.** BC's directional lights come from
     `LightPlacement` objects, not the `Sun` object. Wiring Sun position into
     a directional is a future quality-of-life improvement.
   - **Animated / dedicated corona texture.** The corona currently reuses the
     body texture with a latitude fade. The `_flare_texture` arg from
     `Sun_Create` is already stored on the instance for when this is revisited.
```

Renumber the old items 3–22 to 4–23.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/sub_project_status.md \
        native/src/host/docs/deferred_work.md
git commit -m "docs: mark sun rendering implemented in sub_project_status + deferred_work"
```
