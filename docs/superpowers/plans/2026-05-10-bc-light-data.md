# BC Light Data Interpretation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the renderer's hardcoded ambient + single directional light with values driven by BC SDK script calls (`LightPlacement_Create` + `Config*Light` and `pSet.Create*Light`), surfacing them through the Phase-1 Appc shim, the host loop, and the opaque shader as 1 ambient + up to 4 directionals.

**Architecture:** Pull-each-tick. SDK scripts populate `SetClass._lights` via Phase-1 shim classes (`Light`, `LightPlacement`). Each tick, `engine/host_loop.run` resolves the active set (`g_kSetManager.GetRenderedSet()` → player's set → None), aggregates its lights into `(ambient_rgb, [(dir_to_light, color)] × ≤4)`, and pushes through `r.set_lighting(...)`. The native binding stores values in a file-scope `renderer::Lighting` struct that `FrameSubmitter::submit_opaque` consumes per frame; the `opaque.frag` shader sums up to 4 directionals and adds ambient.

**Tech Stack:** Python 3.12 (Phase-1 engine + tests), C++20 (renderer + bindings), pybind11, GLSL 330, GLM, glad/GLFW. Spec: [docs/superpowers/specs/2026-05-10-bc-light-data-design.md](../specs/2026-05-10-bc-light-data-design.md).

---

## File map

**Created:**
- `engine/appc/lights.py` — `Light`, `LightPlacement`, `LightPlacement_Create`
- `tests/unit/test_appc_lights.py` — Phase-1 light shim tests
- `tests/host/test_host_loop_lighting.py` — host-loop helper tests + binding round-trip

**Modified:**
- `engine/appc/sets.py` — add `_lights` / `_lights_by_name`, real `CreateAmbientLight` / `CreateDirectionalLight` / `GetLight`
- `App.py` — export `LightPlacement_Create`
- `engine/renderer.py` — add `set_lighting` wrapper
- `engine/host_loop.py` — add `_resolve_active_lighting_set` / `_aggregate_lights` / defaults, call them in `run()`
- `native/src/renderer/shaders/opaque.frag` — N=4 directional array + active count
- `native/src/renderer/include/renderer/shader.h` — add `set_vec3_array`
- `native/src/renderer/shader.cc` — implement `set_vec3_array`
- `native/src/renderer/include/renderer/frame.h` — declare `Lighting` struct; change `submit_opaque` signature
- `native/src/renderer/frame.cc` — consume `Lighting`; remove hardcoded uniform literals
- `native/src/host/host_bindings.cc` — file-scope `g_lighting`, `set_lighting` pybind11 binding, pass to `submit_opaque`
- `tests/unit/test_set.py` — extend with `_lights` / `GetLight` cases (no regression in chainable stub for unrelated names)
- `tests/host/test_host_loop_unit.py` — integration assertion: lit pixel ≠ default-lit baseline
- `native/src/host/docs/deferred_work.md` — rewrite item #2; add follow-ups
- `docs/superpowers/specs/2026-05-09-renderer-host-design.md` — same update in spec's deferred-work list
- `docs/architecture/sub_project_status.md` — record sub-project completion

---

## Task 1: Phase-1 `Light` and `LightPlacement` classes

**Files:**
- Create: `engine/appc/lights.py`
- Test: `tests/unit/test_appc_lights.py`

Refer to design spec § "Phase-1 Appc shim additions" for full body and rationale.

- [ ] **Step 1: Write failing tests for the new module**

Create `tests/unit/test_appc_lights.py`:

```python
"""Phase-1 light shim: Light objects, LightPlacement materialisation."""
import pytest


def test_light_holds_color_and_dimmer():
    from engine.appc.lights import Light
    light = Light(Light.KIND_AMBIENT, "ambient1", 0.5, 0.6, 0.7, 0.8)
    assert light._kind == Light.KIND_AMBIENT
    assert light._color == (0.5, 0.6, 0.7)
    assert light._dimmer == 0.8
    assert light.GetName() == "ambient1"
    # Default direction (overwritten by LightPlacement for directionals)
    assert light._direction_world == (0.0, 1.0, 0.0)


def test_light_add_illuminated_object_is_noop():
    from engine.appc.lights import Light
    light = Light(Light.KIND_DIRECTIONAL, "d", 1, 1, 1, 1)
    assert light.AddIlluminatedObject(object()) is None  # SDK no-op


def test_light_placement_create_registers_in_set():
    import App
    from engine.appc.lights import LightPlacement
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "TestSet")
    p = App.LightPlacement_Create("Ambient Light", "TestSet", None)
    assert isinstance(p, LightPlacement)
    assert p.GetName() == "Ambient Light"
    # Placement is in the set's object dict (added via AddObjectToSet).
    assert pSet.GetObject("Ambient Light") is p
    App.g_kSetManager.DeleteSet("TestSet")


def test_config_ambient_light_appends_to_set_lights():
    import App
    from engine.appc.lights import Light
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "TestSet")
    p = App.LightPlacement_Create("Ambient Light", "TestSet", None)
    p.ConfigAmbientLight(0.8, 0.9, 1.0, 0.1)

    assert len(pSet._lights) == 1
    light = pSet._lights[0]
    assert light._kind == Light.KIND_AMBIENT
    assert light._color == (0.8, 0.9, 1.0)
    assert light._dimmer == 0.1
    assert pSet.GetLight("Ambient Light") is light
    App.g_kSetManager.DeleteSet("TestSet")


def test_config_directional_light_captures_forward_direction():
    import App
    from engine.appc.lights import Light
    from engine.appc.math import TGPoint3
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "TestSet")
    p = App.LightPlacement_Create("Directional Light", "TestSet", None)
    forward = TGPoint3(); forward.SetXYZ(-0.1, -0.96, 0.25)
    up      = TGPoint3(); up.SetXYZ(0.02, 0.25, 0.97)
    p.AlignToVectors(forward, up)
    p.ConfigDirectionalLight(0.9, 0.8, 0.6, 0.45)

    light = pSet.GetLight("Directional Light")
    assert light._kind == Light.KIND_DIRECTIONAL
    assert light._color == (0.9, 0.8, 0.6)
    assert light._dimmer == 0.45
    dx, dy, dz = light._direction_world
    assert dx == pytest.approx(-0.1, abs=1e-5)
    assert dy == pytest.approx(-0.96, abs=1e-5)
    assert dz == pytest.approx(0.25, abs=1e-5)
    App.g_kSetManager.DeleteSet("TestSet")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_appc_lights.py -v`
Expected: All 5 tests FAIL with `ImportError: cannot import name 'Light' from 'engine.appc.lights'` (the module does not exist yet) or `AttributeError: module 'App' has no attribute 'LightPlacement_Create'`.

- [ ] **Step 3: Create `engine/appc/lights.py`**

```python
"""Phase-1 light objects: Light + LightPlacement.

BC scripts call:
    kThis = App.LightPlacement_Create(name, set_name, parent)
    kThis.SetTranslateXYZ(x, y, z)
    kThis.AlignToVectors(forward, up)
    kThis.ConfigAmbientLight(r, g, b, dimmer)        # or ConfigDirectionalLight
    kThis.Update(0)

LightPlacement inherits PlacementObject (which inherits ObjectClass) so
SetTranslateXYZ / AlignToVectors / Update / GetWorldRotation come for free.
ConfigAmbientLight / ConfigDirectionalLight materialise a Light into the
containing SetClass._lights list and _lights_by_name index.
"""
from engine.appc.objects import ObjectClass
from engine.appc.placement import PlacementObject


class Light(ObjectClass):
    KIND_AMBIENT = "ambient"
    KIND_DIRECTIONAL = "directional"

    def __init__(self, kind, name, r, g, b, dimmer):
        super().__init__()
        self.SetName(name)
        self._kind = kind
        self._color = (float(r), float(g), float(b))
        self._dimmer = float(dimmer)
        # Overwritten by LightPlacement.ConfigDirectionalLight or by
        # SetClass.CreateDirectionalLight; harmless default for ambients.
        self._direction_world = (0.0, 1.0, 0.0)

    def AddIlluminatedObject(self, _obj):
        # Phase 1 doesn't filter per-object lighting; every light affects
        # every object in its set. SDK callers chain the result; returning
        # None is fine (their next call would be on the receiver, which
        # they discard via `pLight = pSet.GetLight(...)` reassignment).
        return None


class LightPlacement(PlacementObject):
    def ConfigAmbientLight(self, r, g, b, dimmer):
        self._make_light(Light.KIND_AMBIENT, r, g, b, dimmer)

    def ConfigDirectionalLight(self, r, g, b, dimmer):
        light = self._make_light(Light.KIND_DIRECTIONAL, r, g, b, dimmer)
        # Row 1 of the world rotation is the placement's forward axis after
        # AlignToVectors. BC's directional light shines in this direction;
        # the renderer wants direction-toward-light, which the host loop
        # negates at marshalling time.
        rot = self.GetWorldRotation()
        fwd = rot.GetRow(1)
        light._direction_world = (fwd.x, fwd.y, fwd.z)

    def _make_light(self, kind, r, g, b, dimmer):
        light = Light(kind, self.GetName(), r, g, b, dimmer)
        if self._containing_set is not None:
            self._containing_set._lights.append(light)
            self._containing_set._lights_by_name[self.GetName()] = light
        return light


def LightPlacement_Create(name, set_name, parent=None):
    p = LightPlacement()
    p.SetName(name)
    import App
    s = App.g_kSetManager.GetSet(set_name)
    if s is not None:
        s.AddObjectToSet(p, name)  # populates p._containing_set
    return p
```

- [ ] **Step 4: Run tests to see partial progress**

Run: `uv run pytest tests/unit/test_appc_lights.py -v`
Expected: 2 of 5 PASS — `test_light_holds_color_and_dimmer` and
`test_light_add_illuminated_object_is_noop` (they only touch the new
`Light` class directly). The 3 placement-related tests still FAIL because
`App.LightPlacement_Create` is shadowed by `App.py`'s catch-all
`_NamedStub` (no real export until Task 3) and `SetClass._lights` doesn't
exist yet (added in Task 2). This is expected.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/lights.py tests/unit/test_appc_lights.py
git commit -m "feat(appc): Phase-1 Light + LightPlacement classes (no SetClass wiring yet)"
```

---

## Task 2: SetClass — `_lights` storage + real `CreateAmbientLight` / `CreateDirectionalLight` / `GetLight`

**Files:**
- Modify: `engine/appc/sets.py`
- Test: `tests/unit/test_set.py` (extend)

- [ ] **Step 1: Write failing tests in `tests/unit/test_set.py`**

Append to `tests/unit/test_set.py`:

```python
def test_set_lights_initially_empty():
    import App
    pSet = App.SetClass_Create()
    assert pSet._lights == []
    assert pSet._lights_by_name == {}
    assert pSet.GetLight("missing") is None


def test_set_create_ambient_light_4_arg():
    import App
    from engine.appc.lights import Light
    pSet = App.SetClass_Create()
    light = pSet.CreateAmbientLight(1.0, 1.0, 1.0, 0.7, "ambientlight1")
    assert isinstance(light, Light)
    assert light._kind == Light.KIND_AMBIENT
    assert light._color == (1.0, 1.0, 1.0)
    assert light._dimmer == 0.7
    assert pSet._lights == [light]
    assert pSet.GetLight("ambientlight1") is light


def test_set_create_directional_light_8_arg():
    import App
    from engine.appc.lights import Light
    pSet = App.SetClass_Create()
    light = pSet.CreateDirectionalLight(1, 1, 1, 1, 1, 0, 0, "light1")
    assert light._kind == Light.KIND_DIRECTIONAL
    assert light._color == (1.0, 1.0, 1.0)
    assert light._dimmer == 1.0
    assert light._direction_world == (1.0, 0.0, 0.0)
    assert pSet.GetLight("light1") is light


def test_set_unrelated_renderer_methods_still_stub():
    """Regression: catch-all _RendererStub still handles non-light methods."""
    import App
    pSet = App.SetClass_Create()
    # SetBackgroundModel is not implemented — should silently chain via stub.
    result = pSet.SetBackgroundModel("data/Models/Sets/X.nif", 0, 0, 0)
    # Result is a chainable stub; the test only checks that the call did
    # not raise AttributeError.
    assert result is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_set.py::test_set_lights_initially_empty tests/unit/test_set.py::test_set_create_ambient_light_4_arg tests/unit/test_set.py::test_set_create_directional_light_8_arg tests/unit/test_set.py::test_set_unrelated_renderer_methods_still_stub -v`
Expected: First three FAIL (`AttributeError: 'SetClass' object has no attribute '_lights'` or similar). The fourth PASSES already (catch-all chainable stub already provides this).

- [ ] **Step 3: Modify `engine/appc/sets.py`**

In `SetClass.__init__` (around line 22), add the two new fields:

```python
def __init__(self):
    super().__init__()
    self._name: str = ""
    self._objects: dict[str, object] = {}
    # ... existing _cameras / _active_camera_name code ...
    self._lights: list = []
    self._lights_by_name: dict[str, object] = {}
```

Below the existing camera methods (after `SetActiveCamera` around line 132), add:

```python
# ── Lights ──────────────────────────────────────────────────────────────
# Two SDK call paths populate _lights:
#   1. App.LightPlacement_Create + kThis.Config*Light (engine/appc/lights.py)
#   2. pSet.Create*Light (these methods, the shortcut form)
# GetLight returns the named Light or None — must be None (not a stub) so
# that scripts using `if pLight: ...` short-circuit for misses.

def CreateAmbientLight(self, r, g, b, dimmer, name):
    """SDK signature: pSet.CreateAmbientLight(r, g, b, range_or_dimmer, name).

    The 4th arg is "range" in some calls (MissionLib bridge: 19.0) and
    "dimmer" in others (LoadBridge: 0.7). For ambient light range is
    meaningless (no falloff), so we treat it as dimmer uniformly.
    Bridge-rendering follow-up (deferred-work) will revisit the
    high-dimmer bridge case once bridge interiors actually render.
    """
    from engine.appc.lights import Light
    light = Light(Light.KIND_AMBIENT, name, r, g, b, dimmer)
    self._lights.append(light)
    self._lights_by_name[name] = light
    return light

def CreateDirectionalLight(self, r, g, b, dimmer, dx, dy, dz, name):
    """SDK signature observed in DeepSpace.py:
        pSet.CreateDirectionalLight(1, 1, 1, 1, 1, 0, 0, "light1")
    i.e. (r, g, b, dimmer, dx, dy, dz, name).
    """
    from engine.appc.lights import Light
    light = Light(Light.KIND_DIRECTIONAL, name, r, g, b, dimmer)
    light._direction_world = (float(dx), float(dy), float(dz))
    self._lights.append(light)
    self._lights_by_name[name] = light
    return light

def GetLight(self, name):
    return self._lights_by_name.get(name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_set.py -v` (whole file — make sure no regression in existing set tests).
Expected: All PASS.

- [ ] **Step 5: Re-run Task 1 tests — they should now pass too**

Run: `uv run pytest tests/unit/test_appc_lights.py -v`
Expected: All 5 PASS (the placement materialisation now finds `_lights` on the set).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/sets.py tests/unit/test_set.py
git commit -m "feat(appc): SetClass owns _lights + real Create{Ambient,Directional}Light + GetLight"
```

---

## Task 3: Export `LightPlacement_Create` from `App.py`

**Files:**
- Modify: `App.py`
- Test: `tests/unit/test_appc_lights.py` (already references `App.LightPlacement_Create`; passing in Task 2 confirms wiring)

The Task 1 tests already exercise `App.LightPlacement_Create`. They passed because Python module-level `__getattr__` (`App.py:480`) returns a `_NamedStub` for any unknown name, and `App.LightPlacement_Create` happens to **work** today because Task 1's `engine.appc.lights` module is found via `App.LightPlacement_Create` — wait, that's wrong. Let me verify this concretely.

- [ ] **Step 1: Verify the Task 1 tests really did exercise the real `LightPlacement_Create`, not a stub**

Run: `uv run python -c "import App; print(type(App.LightPlacement_Create))"`
Expected (today, before this task): `<class 'App._NamedStub'>` — meaning the function isn't actually exported.

If the Task 1 tests passed without this export, that means we relied on `_NamedStub` masquerading as a callable. That's a bug in the Task 1 test design — fix it by adding the explicit export now.

- [ ] **Step 2: Add the import to `App.py`**

In `App.py`, the existing block:

```python
from engine.appc.placement import (
    PlacementObject, Waypoint, Waypoint_Create,
    Waypoint_Cast, PlacementObject_Cast,
    PlacementObject_Create,
    PlacementObject_GetObjectBySetName, PlacementObject_GetObject,
)
```

Add a new import below it:

```python
from engine.appc.lights import (
    Light, LightPlacement, LightPlacement_Create,
)
```

- [ ] **Step 3: Verify**

Run: `uv run python -c "import App; print(type(App.LightPlacement_Create))"`
Expected: `<class 'function'>`

Run: `uv run pytest tests/unit/test_appc_lights.py -v`
Expected: All 5 PASS, this time exercising the real export.

- [ ] **Step 4: Commit**

```bash
git add App.py
git commit -m "feat(appc): export Light/LightPlacement/LightPlacement_Create from App.py"
```

---

## Task 4: Update `opaque.frag` for N=4 directionals

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag`

This task only changes the shader source. No test in this task — the next two tasks add C++ infrastructure that will exercise it via the existing renderer integration test (extended in Task 11).

- [ ] **Step 1: Replace the entire shader body**

Overwrite `native/src/renderer/shaders/opaque.frag` with:

```glsl
#version 330 core

in vec3 v_normal_ws;
in vec2 v_uv;

uniform sampler2D u_base_color;
uniform vec3 u_diffuse_color;

uniform vec3 u_ambient_light;

const int MAX_DIR_LIGHTS = 4;
uniform int  u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[MAX_DIR_LIGHTS];   // direction TOWARD the light
uniform vec3 u_dir_light_color[MAX_DIR_LIGHTS];    // color × dimmer

out vec4 frag_color;

void main() {
    vec3 n = normalize(v_normal_ws);
    vec3 lit_dir = vec3(0.0);
    for (int i = 0; i < u_dir_light_count; ++i) {
        float ndotl = max(dot(n, normalize(u_dir_light_dir_ws[i])), 0.0);
        lit_dir += ndotl * u_dir_light_color[i];
    }
    vec4 tex = texture(u_base_color, v_uv);
    vec3 lit = (u_ambient_light + lit_dir) * u_diffuse_color * tex.rgb;
    frag_color = vec4(lit, 1.0);
}
```

- [ ] **Step 2: Build C++ to verify shader still compiles at link time**

Run: `cmake --build build --target renderer -j 8`
Expected: Builds without errors. (The shader is embedded as a string at build time; GLSL parse errors only surface at GL `glCompileShader` runtime, but the embedded-source generation will at least catch missing `#version` etc.)

- [ ] **Step 3: Run existing host tests to verify no GLSL runtime regression on the legacy `submit_opaque` call site (which still passes the OLD uniform names)**

Run: `OPEN_STBC_HOST_HEADLESS=1 uv run pytest tests/host/test_clear_frame.py tests/host/test_frame_robustness.py -v`
Expected: They will FAIL because `frame.cc` still sets `u_dir_light_dir_ws` (singular, no `[0]`) — that's a different uniform name now. Don't fix yet; the next two tasks resolve this.

If these tests pass anyway because of GL's "set unknown uniform location is silently ignored" behavior, great. Either way, proceed.

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag
git commit -m "feat(renderer): opaque.frag supports up to 4 directional lights"
```

---

## Task 5: Add `Shader::set_vec3_array` helper

**Files:**
- Modify: `native/src/renderer/include/renderer/shader.h`
- Modify: `native/src/renderer/shader.cc`

GLSL allows setting a uniform array with one `glUniform3fv` call passing the count. We need a method on `Shader` for this.

- [ ] **Step 1: Add the declaration to `shader.h`**

In `native/src/renderer/include/renderer/shader.h`, after `void set_int(...)`:

```cpp
    /// Set a `vec3[]` uniform with `count` consecutive elements. The data
    /// pointer must reference at least `count` glm::vec3 values. Pass the
    /// uniform name *without* the `[0]` suffix; GL accepts the bare name.
    void set_vec3_array(const std::string& name,
                        const glm::vec3* data,
                        int count) const;
```

- [ ] **Step 2: Implement in `shader.cc`**

In `native/src/renderer/shader.cc`, after `set_int`:

```cpp
void Shader::set_vec3_array(const std::string& name,
                            const glm::vec3* data,
                            int count) const {
    if (count <= 0) return;
    GLint loc = glGetUniformLocation(program_, name.c_str());
    if (loc >= 0) {
        glUniform3fv(loc, count, glm::value_ptr(*data));
    }
}
```

- [ ] **Step 3: Build to verify**

Run: `cmake --build build --target renderer -j 8`
Expected: Builds without errors.

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/include/renderer/shader.h native/src/renderer/shader.cc
git commit -m "feat(renderer): Shader::set_vec3_array for uniform vec3[N]"
```

---

## Task 6: `renderer::Lighting` struct + `submit_opaque` signature change

**Files:**
- Modify: `native/src/renderer/include/renderer/frame.h`
- Modify: `native/src/renderer/frame.cc`

This task changes the public API of `FrameSubmitter::submit_opaque`. The single caller (`host_bindings.cc`) must be updated in lockstep — split the build-fix into Task 7.

- [ ] **Step 1: Add the `Lighting` struct to `frame.h`**

In `native/src/renderer/include/renderer/frame.h`, after the `namespace renderer {` line and before `class FrameSubmitter`:

```cpp
struct Lighting {
    static constexpr int MaxDirectionals = 4;
    /// Combined color × dimmer, applied as a uniform additive term.
    glm::vec3 ambient = glm::vec3(0.1f);
    /// 0..MaxDirectionals; values past `directional_count` are ignored.
    int directional_count = 1;
    /// Direction TOWARD the light source, world space, normalized.
    glm::vec3 directional_dir_ws[MaxDirectionals] = {
        glm::normalize(glm::vec3(0.3f, 1.0f, 0.2f))
    };
    /// Color × dimmer per directional.
    glm::vec3 directional_color[MaxDirectionals] = { glm::vec3(1.0f) };
};
```

You'll need `#include <glm/glm.hpp>` at the top of the header if it isn't already there. Add it.

- [ ] **Step 2: Change `submit_opaque` signature in `frame.h`**

Replace the existing `submit_opaque` declaration:

```cpp
void submit_opaque(const scenegraph::World& world,
                   const scenegraph::Camera& camera,
                   Pipeline& pipeline,
                   const ModelLookup& lookup,
                   const Lighting& lighting);
```

- [ ] **Step 3: Update the implementation in `frame.cc`**

Replace the body of `FrameSubmitter::submit_opaque`. Replace the three hardcoded `set_vec3` calls (the lines setting `u_ambient_light`, `u_dir_light_dir_ws`, `u_dir_light_color`) with calls that consume the `Lighting` struct:

```cpp
void FrameSubmitter::submit_opaque(const scenegraph::World& world,
                                   const scenegraph::Camera& camera,
                                   Pipeline& pipeline,
                                   const ModelLookup& lookup,
                                   const Lighting& lighting) {
    auto& shader = pipeline.opaque_shader();
    shader.use();
    shader.set_mat4("u_view", camera.view_matrix());
    shader.set_mat4("u_proj", camera.proj_matrix());

    shader.set_vec3("u_ambient_light", lighting.ambient);
    shader.set_int("u_dir_light_count", lighting.directional_count);
    if (lighting.directional_count > 0) {
        shader.set_vec3_array("u_dir_light_dir_ws",
                              lighting.directional_dir_ws,
                              lighting.directional_count);
        shader.set_vec3_array("u_dir_light_color",
                              lighting.directional_color,
                              lighting.directional_count);
    }

    const GLuint white = ensure_white_texture();

    world.for_each_visible([&](const scenegraph::Instance& inst) {
        const assets::Model* m = lookup(inst.model_handle);
        if (m) draw_model(*m, inst.world, shader, white);
    });
}
```

- [ ] **Step 4: Attempt to build the renderer library**

Run: `cmake --build build --target renderer -j 8`
Expected: `renderer` library builds (it doesn't reference its caller).

- [ ] **Step 5: Attempt to build the host bindings — expect failure**

Run: `cmake --build build --target _open_stbc_host -j 8`
Expected: FAIL with a compile error about `submit_opaque` taking 5 arguments. This is fixed in Task 7.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/include/renderer/frame.h native/src/renderer/frame.cc
git commit -m "feat(renderer): Lighting struct + submit_opaque consumes it"
```

---

## Task 7: `host_bindings.cc` — `g_lighting` + `set_lighting` binding + pass to submitter

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Test: `tests/host/test_host_loop_lighting.py` (smoke binding check)

- [ ] **Step 1: Write the failing binding-smoke test**

Create `tests/host/test_host_loop_lighting.py`:

```python
"""Tests for host-loop lighting wiring (Phase-1 lights → renderer)."""
import os


def test_set_lighting_binding_smoke():
    """Calling set_lighting on the bindings module does not raise."""
    import _open_stbc_host
    _open_stbc_host.set_lighting(
        (0.2, 0.3, 0.4),
        [
            ((0.0, -1.0, 0.0), (1.0, 0.9, 0.8)),
            ((1.0, 0.0, 0.0), (0.5, 0.5, 0.5)),
        ],
    )


def test_set_lighting_accepts_empty_directionals():
    import _open_stbc_host
    _open_stbc_host.set_lighting((0.5, 0.5, 0.5), [])


def test_set_lighting_clamps_to_max_directionals():
    """Passing more than 4 directionals must not raise (truncation in C++)."""
    import _open_stbc_host
    _open_stbc_host.set_lighting(
        (0.1, 0.1, 0.1),
        [((0.0, 1.0, 0.0), (1.0, 1.0, 1.0))] * 8,
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `OPEN_STBC_HOST_HEADLESS=1 uv run pytest tests/host/test_host_loop_lighting.py::test_set_lighting_binding_smoke -v`
Expected: FAIL with `AttributeError: module '_open_stbc_host' has no attribute 'set_lighting'` (binding doesn't exist) **or** the test runs but the host extension fails to import because Task 6 left the build broken.

- [ ] **Step 3: Modify `host_bindings.cc`**

At the top of the anonymous namespace (right after `g_camera`), add the file-scope lighting state:

```cpp
renderer::Lighting g_lighting;
```

In the `init` function, reset it back to default-constructed state so a second `init()` after `shutdown()` doesn't carry stale per-mission lighting:

```cpp
void init(int width, int height, const std::string& title) {
    if (g_window) {
        throw std::runtime_error("_open_stbc_host: init called while host already initialized");
    }
    bool visible = std::getenv("OPEN_STBC_HOST_HEADLESS") == nullptr;
    g_window = std::make_unique<renderer::Window>(width, height, title, visible);
    g_pipeline = std::make_unique<renderer::Pipeline>();
    g_submitter = std::make_unique<renderer::FrameSubmitter>();
    g_world = scenegraph::World{};
    g_loaded_models.clear();
    g_lighting = renderer::Lighting{};
}
```

In `frame()`, change the `submit_opaque` call to pass `g_lighting`:

```cpp
g_submitter->submit_opaque(g_world, g_camera, *g_pipeline, lookup, g_lighting);
```

In `PYBIND11_MODULE`, after the existing `m.def("set_skybox", ...)`, add the new binding:

```cpp
m.def("set_lighting",
      [](std::tuple<float,float,float> ambient,
         const std::vector<std::tuple<
             std::tuple<float,float,float>,
             std::tuple<float,float,float>>>& directionals) {
          g_lighting.ambient = {std::get<0>(ambient),
                                std::get<1>(ambient),
                                std::get<2>(ambient)};
          int n = std::min(static_cast<int>(directionals.size()),
                           renderer::Lighting::MaxDirectionals);
          g_lighting.directional_count = n;
          for (int i = 0; i < n; ++i) {
              const auto& [dir, col] = directionals[i];
              glm::vec3 d{std::get<0>(dir), std::get<1>(dir), std::get<2>(dir)};
              float len = glm::length(d);
              g_lighting.directional_dir_ws[i] =
                  (len > 1e-6f) ? d / len : glm::vec3(0.0f, 1.0f, 0.0f);
              g_lighting.directional_color[i] = {
                  std::get<0>(col), std::get<1>(col), std::get<2>(col)};
          }
      },
      py::arg("ambient"), py::arg("directionals"),
      "Set the global lighting state used by the next frame()'s opaque pass.");
```

- [ ] **Step 4: Build everything**

Run: `cmake --build build -j 8`
Expected: Both `renderer` and `_open_stbc_host` build cleanly.

- [ ] **Step 5: Run the new tests**

Run: `OPEN_STBC_HOST_HEADLESS=1 uv run pytest tests/host/test_host_loop_lighting.py -v`
Expected: All 3 PASS.

- [ ] **Step 6: Run the existing host suite to verify no regression**

Run: `OPEN_STBC_HOST_HEADLESS=1 uv run pytest tests/host/ -v`
Expected: All existing host tests PASS (the lit Galaxy still renders because `g_lighting` defaults to the same values `frame.cc` had hardcoded).

- [ ] **Step 7: Commit**

```bash
git add native/src/host/host_bindings.cc tests/host/test_host_loop_lighting.py
git commit -m "feat(host): set_lighting binding + g_lighting fed to submit_opaque"
```

---

## Task 8: Python wrapper — `engine/renderer.py` `set_lighting`

**Files:**
- Modify: `engine/renderer.py`
- Test: piggyback on Task 7 `tests/host/test_host_loop_lighting.py`

- [ ] **Step 1: Add a smoke test for the wrapper**

Append to `tests/host/test_host_loop_lighting.py`:

```python
def test_renderer_module_set_lighting_wrapper():
    """The Python wrapper round-trips arguments to the bindings."""
    from engine import renderer
    renderer.set_lighting(
        (0.1, 0.2, 0.3),
        [((0.0, 1.0, 0.0), (1.0, 1.0, 1.0))],
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `OPEN_STBC_HOST_HEADLESS=1 uv run pytest tests/host/test_host_loop_lighting.py::test_renderer_module_set_lighting_wrapper -v`
Expected: FAIL with `AttributeError: module 'engine.renderer' has no attribute 'set_lighting'`.

- [ ] **Step 3: Add the wrapper to `engine/renderer.py`**

After the existing `set_skybox` function:

```python
def set_lighting(ambient: Tuple[float, float, float],
                 directionals: list) -> None:
    """Configure the renderer's lighting state for subsequent frame()s.

    `directionals` is a list of ((dx, dy, dz), (r, g, b)) tuples where
    (dx, dy, dz) is the direction TOWARD the light source and (r, g, b)
    is the color × dimmer product. Up to 4 entries are honored;
    additional ones are silently dropped by the bindings.
    """
    _h.set_lighting(ambient, directionals)
```

- [ ] **Step 4: Run to verify it passes**

Run: `OPEN_STBC_HOST_HEADLESS=1 uv run pytest tests/host/test_host_loop_lighting.py::test_renderer_module_set_lighting_wrapper -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/renderer.py tests/host/test_host_loop_lighting.py
git commit -m "feat(host): engine.renderer.set_lighting Python wrapper"
```

---

## Task 9: Host-loop helpers — `_resolve_active_lighting_set` + `_aggregate_lights` + defaults

**Files:**
- Modify: `engine/host_loop.py`
- Test: extend `tests/host/test_host_loop_lighting.py`

- [ ] **Step 1: Write failing tests for the helpers**

Ensure the imports at the top of `tests/host/test_host_loop_lighting.py`
include `pytest` — the tests below use `pytest.approx`. The file should
start with:

```python
"""Tests for host-loop lighting wiring (Phase-1 lights → renderer)."""
import os

import pytest
```

(Add `import pytest` if it isn't already there from earlier tasks.)

Append to `tests/host/test_host_loop_lighting.py`:

```python
def test_default_lighting_constants_present():
    from engine import host_loop
    assert isinstance(host_loop.DEFAULT_AMBIENT, tuple)
    assert len(host_loop.DEFAULT_AMBIENT) == 3
    assert isinstance(host_loop.DEFAULT_DIRECTIONALS, list)
    assert len(host_loop.DEFAULT_DIRECTIONALS) >= 1
    # First entry is ((dx, dy, dz), (r, g, b))
    direction, color = host_loop.DEFAULT_DIRECTIONALS[0]
    assert len(direction) == 3 and len(color) == 3


def test_aggregate_lights_none_returns_defaults():
    from engine import host_loop
    ambient, directionals = host_loop._aggregate_lights(None)
    assert ambient == host_loop.DEFAULT_AMBIENT
    assert directionals == host_loop.DEFAULT_DIRECTIONALS


def test_aggregate_lights_ambient_last_wins():
    import App
    from engine import host_loop
    pSet = App.SetClass_Create()
    pSet.CreateAmbientLight(0.1, 0.1, 0.1, 1.0, "a1")
    pSet.CreateAmbientLight(0.4, 0.5, 0.6, 0.5, "a2")  # last
    ambient, directionals = host_loop._aggregate_lights(pSet)
    # 0.4 * 0.5 = 0.2 etc.
    assert ambient[0] == pytest.approx(0.2)
    assert ambient[1] == pytest.approx(0.25)
    assert ambient[2] == pytest.approx(0.3)
    assert directionals == []


def test_aggregate_lights_directional_negates_forward():
    """BC's directional forward is 'where the light shines'; renderer
    wants 'direction toward the light'. host_loop must negate."""
    import App
    from engine import host_loop
    pSet = App.SetClass_Create()
    pSet.CreateDirectionalLight(1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 0.0, "d1")
    _, directionals = host_loop._aggregate_lights(pSet)
    assert len(directionals) == 1
    direction, color = directionals[0]
    assert direction == (-0.0, -1.0, -0.0)  # Python negates -0.0 cleanly
    assert color == (1.0, 1.0, 1.0)


def test_aggregate_lights_truncates_to_four():
    import App
    from engine import host_loop
    pSet = App.SetClass_Create()
    for i in range(6):
        pSet.CreateDirectionalLight(
            1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 0.0, f"d{i}")
    _, directionals = host_loop._aggregate_lights(pSet)
    assert len(directionals) == 4


def test_aggregate_lights_filters_zero_vector_directions():
    import App
    from engine import host_loop
    pSet = App.SetClass_Create()
    pSet.CreateDirectionalLight(1, 1, 1, 1, 0, 1, 0, "good")
    pSet.CreateDirectionalLight(1, 1, 1, 1, 0, 0, 0, "zero")
    _, directionals = host_loop._aggregate_lights(pSet)
    assert len(directionals) == 1


def test_resolve_active_lighting_set_prefers_rendered():
    import App
    from engine import host_loop
    pRendered = App.SetClass_Create()
    pRendered.CreateAmbientLight(1, 1, 1, 1, "a")
    App.g_kSetManager.AddSet(pRendered, "RenderedSet")
    App.g_kSetManager.MakeRenderedSet("RenderedSet")
    try:
        active = host_loop._resolve_active_lighting_set(player=None)
        assert active is pRendered
    finally:
        App.g_kSetManager.DeleteSet("RenderedSet")
        App.g_kSetManager._rendered_set_name = None


def test_resolve_active_lighting_set_falls_back_to_player_set():
    import App
    from engine import host_loop
    App.g_kSetManager._rendered_set_name = None  # explicitly unset
    pPlayer = App.SetClass_Create()
    pPlayer.CreateAmbientLight(1, 1, 1, 1, "a")
    App.g_kSetManager.AddSet(pPlayer, "PlayerSet")

    class _FakePlayer: pass
    fp = _FakePlayer()
    pPlayer.AddObjectToSet(fp, "player")
    try:
        active = host_loop._resolve_active_lighting_set(player=fp)
        assert active is pPlayer
    finally:
        App.g_kSetManager.DeleteSet("PlayerSet")


def test_resolve_active_lighting_set_returns_none_for_no_lights():
    import App
    from engine import host_loop
    App.g_kSetManager._rendered_set_name = None
    pEmpty = App.SetClass_Create()  # no lights
    App.g_kSetManager.AddSet(pEmpty, "Empty")
    try:
        active = host_loop._resolve_active_lighting_set(player=None)
        assert active is None
    finally:
        App.g_kSetManager.DeleteSet("Empty")
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `OPEN_STBC_HOST_HEADLESS=1 uv run pytest tests/host/test_host_loop_lighting.py -v`
Expected: The 9 new tests FAIL with `AttributeError: module 'engine.host_loop' has no attribute 'DEFAULT_AMBIENT'` (or `_aggregate_lights` etc.). Existing tests still PASS.

- [ ] **Step 3: Add helpers + constants to `engine/host_loop.py`**

Near the top of the module (after the existing `DEFAULT_PLAYER_SET = "Biranu1"` line):

```python
# Lighting defaults — used by both the per-tick fallback (when no active set
# has lights) and as the conceptual source of truth that the C++
# host_bindings.cc default-constructed Lighting struct mirrors.
DEFAULT_AMBIENT: tuple[float, float, float] = (0.1, 0.1, 0.1)
DEFAULT_DIRECTIONALS: list = [
    # Single top-down directional matching frame.cc's pre-Phase-1 default.
    # ((dx, dy, dz) toward light, (r, g, b))
    ((0.3, 1.0, 0.2), (1.0, 1.0, 1.0)),
]
```

After the existing `_world_matrix_row_major` helper, add:

```python
def _resolve_active_lighting_set(player):
    """Return the SetClass whose lights apply to the rendered scene.

    Order:
      1. g_kSetManager.GetRenderedSet() — set explicitly via
         MissionLib.MakeRenderedSet during scene transitions. Used when
         present and has lights.
      2. The set containing the player ship — fallback for when Phase 1
         hasn't wired MakeRenderedSet up. Used when has lights.
      3. None — caller falls through to DEFAULT_AMBIENT / DEFAULT_DIRECTIONALS.
    """
    import App
    rendered = App.g_kSetManager.GetRenderedSet()
    if rendered is not None and getattr(rendered, "_lights", None):
        return rendered
    if player is not None:
        for s in App.g_kSetManager._sets.values():
            if any(o is player for o in getattr(s, "_objects", {}).values()):
                if getattr(s, "_lights", None):
                    return s
    return None


def _aggregate_lights(pSet):
    """Collapse SetClass._lights into (ambient_rgb, [directionals × ≤4]).

    Ambient: last-wins across configured ambients, color × dimmer.
    Directionals: in insertion order, capped at 4 (with a one-shot warning
        when more were configured), filtering out zero-length directions.
        Each is ((dx_to_light, dy_to_light, dz_to_light), (r, g, b)).
    Returns (DEFAULT_AMBIENT, DEFAULT_DIRECTIONALS) when pSet is None.
    """
    if pSet is None:
        return DEFAULT_AMBIENT, DEFAULT_DIRECTIONALS

    from engine.appc.lights import Light

    ambient: tuple[float, float, float] = (0.0, 0.0, 0.0)
    found_ambient = False
    directionals: list = []
    overflowed = False

    for light in pSet._lights:
        if light._kind == Light.KIND_AMBIENT:
            r, g, b = light._color
            d = light._dimmer
            ambient = (r * d, g * d, b * d)
            found_ambient = True
        elif light._kind == Light.KIND_DIRECTIONAL:
            dx, dy, dz = light._direction_world
            mag2 = dx * dx + dy * dy + dz * dz
            if mag2 < 1e-12:
                continue  # zero-vector guard
            # BC forward = direction light shines; shader wants TOWARD light.
            dir_to_light = (-dx, -dy, -dz)
            r, g, b = light._color
            dim = light._dimmer
            color = (r * dim, g * dim, b * dim)
            if len(directionals) < 4:
                directionals.append((dir_to_light, color))
            else:
                overflowed = True

    if overflowed:
        # One log line per aggregation call — MissionLib runs this each tick
        # so we can't suppress to once-per-set without state. The print is
        # short and the case is rare (only multi-directional mods).
        print(f"[host_loop] dropped extra directional lights from set "
              f"{pSet.GetName()!r} (>4 configured)", flush=True)

    if not found_ambient and not directionals:
        # Active set was selected but had only filtered-out junk; treat as
        # "no usable lights" → defaults.
        return DEFAULT_AMBIENT, DEFAULT_DIRECTIONALS

    return ambient, directionals
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `OPEN_STBC_HOST_HEADLESS=1 uv run pytest tests/host/test_host_loop_lighting.py -v`
Expected: All PASS.

Note: `test_aggregate_lights_directional_negates_forward` asserts `(-0.0, -1.0, -0.0)`. Python's `(-0.0,) == (0.0,)` is `True` so this comparison should hold even if Python normalises the sign. If this assertion fails on some platforms, switch to `pytest.approx`.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_host_loop_lighting.py
git commit -m "feat(host): _resolve_active_lighting_set + _aggregate_lights"
```

---

## Task 10: Wire the helpers into `host_loop.run()`

**Files:**
- Modify: `engine/host_loop.py`

- [ ] **Step 1: Insert the per-tick set_lighting call**

In `run()`, locate the existing block:

```python
            r.set_camera(eye=eye, target=target, up=up_vec,
                         fov_y_rad=1.0472, near=1.0, far=100000.0)

            if verbose and ticks == 0:
                print(f"[host_loop] tick 0 camera eye={eye} target={target}", flush=True)

            r.frame()
```

Insert two new lines between `r.set_camera(...)` and `r.frame()` (above the verbose print is fine — keeping verbose-print order stable for log scrapers):

```python
            r.set_camera(eye=eye, target=target, up=up_vec,
                         fov_y_rad=1.0472, near=1.0, far=100000.0)

            ambient, directionals = _aggregate_lights(
                _resolve_active_lighting_set(player))
            r.set_lighting(ambient, directionals)

            if verbose and ticks == 0:
                print(f"[host_loop] tick 0 camera eye={eye} target={target}", flush=True)
                print(f"[host_loop] tick 0 lighting ambient={ambient} "
                      f"directionals={directionals}", flush=True)

            r.frame()
```

- [ ] **Step 2: Run the existing 5-tick smoke**

Run: `OPEN_STBC_HOST_HEADLESS=1 uv run pytest tests/host/test_host_loop_unit.py::test_run_M1_Basic_for_a_few_ticks -v`
Expected: PASS. The Galaxy still renders because `_resolve_active_lighting_set` falls back to None for M1Basic (the active set's `_lights` list is empty since stock Biranu placement scripts haven't been pulled in yet by the headless harness), which triggers the DEFAULT fallback that matches the previous hardcoded values.

- [ ] **Step 3: Run the full host suite to verify no regression**

Run: `OPEN_STBC_HOST_HEADLESS=1 uv run pytest tests/host/ -v`
Expected: All host tests PASS.

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host): per-tick set_lighting from active set in run()"
```

---

## Task 11: Integration — assert lit-pixel result matches script-configured lighting

**Files:**
- Modify: `tests/host/test_host_loop_lighting.py` (extend with end-to-end test)

- [ ] **Step 1: Write the failing integration test**

Append to `tests/host/test_host_loop_lighting.py`:

```python
def test_set_lighting_changes_rendered_pixel():
    """End-to-end: set_lighting with bright red ambient changes the
    on-screen pixel sampled at the centre of the frame, vs. set_lighting
    with black ambient + no directionals."""
    import os
    from pathlib import Path
    import pytest

    PROJECT_ROOT = Path(__file__).parent.parent.parent
    GALAXY_NIF = PROJECT_ROOT / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")

    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _open_stbc_host

    # Initialise once, render with bright red lighting, capture; render with
    # black lighting, capture. Compare red channel.
    _open_stbc_host.init(640, 360, "test_set_lighting_changes_pixel")
    try:
        tex_search = str(PROJECT_ROOT / "game" / "data" / "Models" /
                         "SharedTextures" / "FedShips" / "High")
        h = _open_stbc_host.load_model(str(GALAXY_NIF), tex_search)
        iid = _open_stbc_host.create_instance(h)
        # Position Galaxy at origin; camera 1500 units back, looking at it.
        _open_stbc_host.set_world_transform(iid, [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ])
        _open_stbc_host.set_camera(
            eye=(0.0, 0.0, 1500.0),
            target=(0.0, 0.0, 0.0),
            up=(0.0, 1.0, 0.0),
            fov_y_rad=1.0472, near=1.0, far=100000.0,
        )

        fw, fh = _open_stbc_host.framebuffer_size()
        cx, cy = fw // 2, fh // 2

        # Bright red ambient, no directionals.
        _open_stbc_host.set_lighting((1.0, 0.0, 0.0), [])
        _open_stbc_host.frame()
        red_r, red_g, red_b, _ = _open_stbc_host.read_pixel(cx, cy)

        # Black: no ambient, no directionals → fully unlit Galaxy.
        _open_stbc_host.set_lighting((0.0, 0.0, 0.0), [])
        _open_stbc_host.frame()
        dark_r, _, _, _ = _open_stbc_host.read_pixel(cx, cy)

        # The red-lit centre must have more red than the dark-lit centre,
        # confirming the ambient channel is wired through to the shader.
        assert red_r > dark_r + 50, (
            f"Expected red ambient to brighten pixel: red_r={red_r}, "
            f"dark_r={dark_r}")
    finally:
        _open_stbc_host.destroy_instance(iid)
        _open_stbc_host.shutdown()
```

- [ ] **Step 2: Run the test**

Run: `OPEN_STBC_HOST_HEADLESS=1 uv run pytest tests/host/test_host_loop_lighting.py::test_set_lighting_changes_rendered_pixel -v`
Expected: PASS — the wiring is already in place from Tasks 6/7.

If it fails because `read_pixel` returns 0 for the dark frame and the diff is below the threshold, that's **good news**: it means lighting works. Adjust the threshold (`> dark_r + 50` → smaller) if the actual dark_r is e.g. 8 (skybox clear color leaking through Galaxy thin spots) and red_r is e.g. 200.

- [ ] **Step 3: Commit**

```bash
git add tests/host/test_host_loop_lighting.py
git commit -m "test(host): set_lighting changes rendered pixel end-to-end"
```

---

## Task 12: Documentation — deferred-work updates and cross-reference

**Files:**
- Modify: `native/src/host/docs/deferred_work.md`
- Modify: `docs/superpowers/specs/2026-05-09-renderer-host-design.md`

- [ ] **Step 1: Rewrite item #2 in `native/src/host/docs/deferred_work.md`**

Find the existing entry:

```
2. **BC light data interpretation.** Read `NiAmbientLight` /
   `NiDirectionalLight` blocks from scene NIFs. Currently lighting is
   hard-coded in `frame.cc`'s `submit_opaque` (ambient 0.1, single
   directional from above).
```

Replace with:

```
2. **BC light data interpretation.** ✅ Implemented 2026-05-10.
   See [`docs/superpowers/specs/2026-05-10-bc-light-data-design.md`]
   (../../../../docs/superpowers/specs/2026-05-10-bc-light-data-design.md).

   - Phase-1 shim (`engine/appc/lights.py`) materialises BC's
     `LightPlacement` / `Config*Light` / `pSet.Create*Light` calls into
     `SetClass._lights`.
   - `engine/host_loop.run` resolves the active set
     (`g_kSetManager.GetRenderedSet()` → player's set → None) each tick,
     aggregates 1 ambient + up to 4 directionals, calls
     `r.set_lighting(...)`.
   - `opaque.frag` consumes the ambient + directional array.

   **NIF-block light parsing is intentionally not part of this work** —
   a binary survey of all 93 NIFs in the repo found zero `NiAmbient*` /
   `NiDirectional*` blocks. Stock BC stores no lighting in scene NIFs.

   Follow-up backlog (deferred-work continues below):

   - **Bridge & cinematic light rendering.** When bridge rendering
     arrives, revisit `SetClass.CreateAmbientLight`'s 4th-arg semantics
     (range vs dimmer) — bridges call it with values up to 19.0, treated
     as dimmer today.
   - **`AddIlluminatedObject` per-object filtering.** Phase 1 ignores
     it; lights affect every object in the set. Becomes relevant when
     characters render.
   - **Save/load coverage of `Light` and `SetClass._lights`.** Tracked
     under "Save/load coverage of render state" (existing item #15).
   - **Point/spot light support.** No stock content uses them. The NIF
     parser already understands `NiPointLight` / `NiSpotLight` block
     types for forward compatibility.
   - **Per-set lighting persistence across set transitions.** The
     pull-each-tick model re-aggregates every frame; cache by `_lights`
     identity if profiling later shows it matters.
```

- [ ] **Step 2: Mirror the same change in the renderer-host design spec**

Open `docs/superpowers/specs/2026-05-09-renderer-host-design.md`. Find the section that lists deferred-work item #2 (around line 344). Replace its bullet body with text equivalent to step 1 above. Adapt the relative link path so it resolves from the spec file's location:

```
2. **BC light data interpretation** — ✅ Implemented 2026-05-10. See
   [`2026-05-10-bc-light-data-design.md`](2026-05-10-bc-light-data-design.md).
   Phase-1 lights flow from BC scripts (`LightPlacement_Create` /
   `Config*Light` / `pSet.Create*Light`) through `SetClass._lights`,
   `engine/host_loop`'s per-tick aggregation, and the `set_lighting`
   binding into `opaque.frag`'s 1 ambient + up-to-4 directional uniforms.
   NIF-block parsing was deliberately scoped out (zero light blocks in
   any of the 93 NIFs surveyed across `game/data/` and `sdk/Art/`).
```

- [ ] **Step 3: Verify docs build / link sanity**

Run: `grep -n "2026-05-10-bc-light-data-design" docs/superpowers/specs/2026-05-09-renderer-host-design.md native/src/host/docs/deferred_work.md`
Expected: Two hits, both pointing at the new spec.

- [ ] **Step 4: Commit**

```bash
git add native/src/host/docs/deferred_work.md \
        docs/superpowers/specs/2026-05-09-renderer-host-design.md
git commit -m "docs: mark BC light data interpretation implemented; record follow-ups"
```

---

## Task 13: Sub-project status index update

**Files:**
- Modify: `docs/architecture/sub_project_status.md`

- [ ] **Step 1: Add a new row + update item-2 status**

In the "Renderer sub-projects" table, add a new row beneath the renderer host row:

```
| 3-6+ | BC light data interpretation (Python-script lighting) | Implemented (2026-05-10; 1 ambient + up to 4 directionals; v1 ship gate Galaxy still lit via fallback) | [2026-05-10-bc-light-data-design.md](../superpowers/specs/2026-05-10-bc-light-data-design.md) | (folded into renderer-host's `deferred_work.md`) |
```

- [ ] **Step 2: Commit**

```bash
git add docs/architecture/sub_project_status.md
git commit -m "docs(status): BC light data interpretation v1 implemented"
```

---

## Final verification

Before declaring the sub-project done, run the full suite:

- [ ] **Build everything:**

```bash
cmake --build build -j 8
```

- [ ] **All Python tests:**

```bash
OPEN_STBC_HOST_HEADLESS=1 uv run pytest tests/ -v
```

Expected: 100% pass; new tests in `tests/unit/test_appc_lights.py`,
`tests/host/test_host_loop_lighting.py`, plus extensions to
`tests/unit/test_set.py` and `tests/host/test_host_loop_unit.py` are
green; no regressions in existing 17 host-loop tests.

- [ ] **Confirm the Galaxy still renders (visual smoke):**

```bash
unset OPEN_STBC_HOST_HEADLESS
./build/bin/open_stbc_host
```

(Press a key / window close to exit.) Expected: Galaxy ship is visible,
lit, oriented correctly. Confirm that the lighting matches the previous
visible build — i.e. the fallback path still produces the same scene
when no script-configured lights are present.

- [ ] **Spot-check that lights ARE flowing for an instrumented case:**

Run with `OPEN_STBC_HOST_VERBOSE=1` and inspect the tick-0 log line. It
should print the ambient + directional values currently in effect; for
M1Basic this prints the DEFAULT values because no SDK script for that
mission populates `_lights` in the active set.
