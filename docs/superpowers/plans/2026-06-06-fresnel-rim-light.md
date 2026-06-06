# Fresnel Rim Light Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a runtime-toggleable Fresnel rim-light term to ship hulls in the exterior scene — a bright lit-edge highlight that reads as "atmosphere-less metal catching a star" — with no new art assets.

**Architecture:** A single extra term in `opaque.frag` (`pow(1-dot(n,V), k)`), modulated by the accumulated directional light so it only appears where a star actually hits, and scaled per-draw by a strength derived from the material's existing specular properties. Gated by (a) a process-global `RenderFresnelRim` toggle mirroring the existing `dauntless_specular` pattern, and (b) a new per-instance `rim_eligible` flag so it applies to ship hulls only — **not** planets, which share `opaque.frag`. Surfaced as an "On/Off" control under a new "Modern VFX" group in the Configuration panel (default On).

**Tech Stack:** C++17 / OpenGL 3.3 (GLSL 330) renderer, pybind11 host bindings, Python host loop + CEF (HTML/CSS/JS) configuration UI, GoogleTest (C++) + pytest (Python).

**Scope note:** This is plan 1 of 2 for the "Modern VFX" feature. Plan 2 (HDR pipeline: `RGBA16F` FBO + tonemap + bloom) is a separate document. This plan establishes the "Modern VFX" config group that HDR will later join.

**Branch:** Work on a feature branch in the main checkout — **do not use a git worktree** (`sdk/` and `game/` are gitignored and live only in the main checkout; worktrees break runtime asset deps). Create it before Task 1:
```bash
git checkout -b feat/fresnel-rim-light
```

**Build / test reminders:**
- Full build: `cmake -B build -S . && cmake --build build -j`
- **Shader (`.frag`/`.vert`) edits are NOT picked up by `cmake --build` alone** — you must re-run `cmake -B build -S .` first (the embed step is a configure-time custom command).
- **Never** run `pytest` over the whole suite (it OOMs the host) — always target specific files.
- Single binary lives at `build/dauntless`; never create alternate build trees.

---

### Task 1: Per-instance `rim_eligible` flag in the scenegraph

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h:21-26`
- Modify: `native/src/scenegraph/include/scenegraph/world.h:16`
- Modify: `native/src/scenegraph/src/world.cc:37-39`
- Test: `native/tests/scenegraph/world_test.cc`

- [ ] **Step 1: Write the failing tests**

Append to `native/tests/scenegraph/world_test.cc` (before the final close, alongside the existing `SetPassUpdatesField` test):

```cpp
TEST(World, NewInstanceDefaultsRimIneligible) {
    scenegraph::World w;
    auto id = w.create_instance(7);
    auto* inst = w.get(id);
    ASSERT_NE(inst, nullptr);
    EXPECT_FALSE(inst->rim_eligible);
}

TEST(World, SetRimEligibleUpdatesField) {
    scenegraph::World w;
    auto id = w.create_instance(7);
    w.set_rim_eligible(id, true);
    EXPECT_TRUE(w.get(id)->rim_eligible);
    w.set_rim_eligible(id, false);
    EXPECT_FALSE(w.get(id)->rim_eligible);
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmake --build build -j scenegraph_tests && ctest --test-dir build -R "World.SetRimEligible|World.NewInstanceDefaultsRim" -V`
Expected: compile error — `Instance` has no member `rim_eligible`, `World` has no member `set_rim_eligible`.

- [ ] **Step 3: Add the field to `Instance`**

In `native/src/scenegraph/include/scenegraph/instance.h`, extend the `Instance` struct (after the `Pass pass` line):

```cpp
struct Instance {
    ModelHandle model_handle = 0;
    glm::mat4 world{1.0f};
    bool visible = true;
    Pass pass = Pass::Space;
    /// True for ship hulls; gates the opaque-pass Fresnel rim term so it
    /// applies to hulls only. Planets share the opaque shader but must
    /// not receive a metallic rim — they default false. The future
    /// planet-atmosphere effect will add its own per-instance params.
    bool rim_eligible = false;
};
```

- [ ] **Step 4: Declare and implement `set_rim_eligible`**

In `native/src/scenegraph/include/scenegraph/world.h`, add after the `set_pass` declaration (line 16):

```cpp
    void set_rim_eligible(InstanceId id, bool eligible);
```

In `native/src/scenegraph/src/world.cc`, add after `set_pass` (line 39):

```cpp
void World::set_rim_eligible(InstanceId id, bool eligible) {
    if (auto* inst = get(id)) inst->rim_eligible = eligible;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cmake --build build -j scenegraph_tests && ctest --test-dir build -R "World.SetRimEligible|World.NewInstanceDefaultsRim" -V`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add native/src/scenegraph/include/scenegraph/instance.h native/src/scenegraph/include/scenegraph/world.h native/src/scenegraph/src/world.cc native/tests/scenegraph/world_test.cc
git commit -m "feat(scenegraph): add per-instance rim_eligible flag

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `rim_strength_from_material` lighting helper

**Files:**
- Modify: `native/src/renderer/include/renderer/lighting.h`
- Test: `native/tests/renderer/lighting_test.cc`

This is the pure function that turns a material's existing specular color + glossiness into a rim strength scalar, so shiny hulls rim harder. No GL — a clean unit-testable anchor.

- [ ] **Step 1: Write the failing test**

Append to `native/tests/renderer/lighting_test.cc`:

```cpp
TEST(Lighting, RimStrengthFromMaterialPinnedValues) {
    using renderer::rim_strength_from_material;
    // No specular -> no rim, regardless of gloss.
    EXPECT_FLOAT_EQ(rim_strength_from_material({0.0f, 0.0f, 0.0f}, 0.0f), 0.0f);
    EXPECT_FLOAT_EQ(rim_strength_from_material({0.0f, 0.0f, 0.0f}, 1.0f), 0.0f);
    // Full white specular: gloss scales 0.25 (matte) -> 1.0 (glossy).
    EXPECT_FLOAT_EQ(rim_strength_from_material({1.0f, 1.0f, 1.0f}, 0.0f), 0.25f);
    EXPECT_FLOAT_EQ(rim_strength_from_material({1.0f, 1.0f, 1.0f}, 1.0f), 1.0f);
    // Mid specular, mid gloss: 0.5 * (0.25 + 0.75*0.5) = 0.3125.
    EXPECT_FLOAT_EQ(rim_strength_from_material({0.5f, 0.5f, 0.5f}, 0.5f), 0.3125f);
    // Strength uses the brightest specular channel (max), not luminance.
    EXPECT_FLOAT_EQ(rim_strength_from_material({0.2f, 0.8f, 0.1f}, 1.0f), 0.8f);
    // Clamp out-of-range BC outliers (gloss=4.0 appears in the corpus).
    EXPECT_FLOAT_EQ(rim_strength_from_material({2.0f, 2.0f, 2.0f}, 4.0f), 1.0f);
    // Clamp negatives.
    EXPECT_FLOAT_EQ(rim_strength_from_material({-1.0f, -1.0f, -1.0f}, -1.0f), 0.0f);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake --build build -j renderer_tests && ctest --test-dir build -R "Lighting.RimStrength" -V`
Expected: compile error — `rim_strength_from_material` not declared.

- [ ] **Step 3: Implement the helper**

In `native/src/renderer/include/renderer/lighting.h`, add `#include <glm/glm.hpp>` near the top includes, then add this function after `glossiness_to_specular_power`:

```cpp
/// Derive a Fresnel rim-light strength scalar [0,1] from a material's
/// existing specular color + glossiness. Shiny hulls rim harder; matte
/// hulls barely rim; specular-less materials (e.g. most planet NIFs) get
/// zero rim. This reuses authored material data so no new per-ship field
/// is needed (see project_modern_vfx_design memory: we deliberately do
/// NOT gate on the SDK `SpecularCoef` key, which only 2 of 51 ships set
/// and which already means SetSpecularKs).
///
///   strength = max(specular.rgb) * (0.25 + 0.75 * glossiness)
///
/// Both inputs are clamped to [0,1] first (BC authors a gloss=4.0 outlier).
inline float rim_strength_from_material(const glm::vec3& specular, float glossiness) {
    float s = std::max({specular.r, specular.g, specular.b});
    s = std::clamp(s, 0.0f, 1.0f);
    float g = std::clamp(glossiness, 0.0f, 1.0f);
    return s * (0.25f + 0.75f * g);
}
```

(`<algorithm>` for `std::max`/`std::clamp` is already included in `lighting.h`. The 3-arg `std::max({...})` initializer-list form needs `<algorithm>`, already present.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cmake --build build -j renderer_tests && ctest --test-dir build -R "Lighting.RimStrength" -V`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/lighting.h native/tests/renderer/lighting_test.cc
git commit -m "feat(renderer): rim_strength_from_material helper

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Rim term in the opaque shader + frame.cc wiring

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag`
- Modify: `native/src/renderer/frame.cc:25-31` (add `dauntless_rim` namespace), `:37-119` (`draw_model`), `:166-233` (both submit fns)
- Test: `native/tests/renderer/frame_test.cc`

The shader gets one new uniform `u_rim_strength` (0 disables). `frame.cc` computes that scalar per draw: `(global toggle && instance.rim_eligible) ? rim_strength_from_material(...) : 0`.

- [ ] **Step 1: Write the failing test**

Append to `native/tests/renderer/frame_test.cc` (inside the `FrameTest` fixture's namespace, mirroring `OpaquePassRunsWithoutGLError`):

```cpp
TEST_F(FrameTest, OpaquePassWithRimEnabledRunsWithoutGLError) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);

    scenegraph::World world;
    auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));
    world.set_rim_eligible(iid, true);

    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 0.0f, 1500.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);

    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;
    lighting.directional_count = 1;
    lighting.directional_dir_ws[0] = glm::vec3(0.0f, 0.0f, 1.0f);
    lighting.directional_color[0]  = glm::vec3(1.0f, 1.0f, 1.0f);

    auto lookup = [&](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h);
    };

    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    submitter.submit_opaque_in_pass(world, cam, *p, lookup, lighting,
                                    scenegraph::Pass::Space);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}
```

(If `renderer::Lighting`'s exact member names differ, match `OpaquePassRunsWithoutGLError` in the same file — copy its lighting setup verbatim and only add the `set_rim_eligible(iid, true)` line.)

- [ ] **Step 2: Run test to verify it fails (or is skipped without assets)**

Run: `cmake -B build -S . && cmake --build build -j renderer_tests && ctest --test-dir build -R "FrameTest.OpaquePassWithRim" -V`
Expected: with BC assets present, the test currently links/runs but the new `u_rim_strength` uniform path isn't wired — it should still pass as a smoke test only AFTER Step 3 (before Step 3 it compiles but exercises no rim code). If assets are absent it SKIPs. The real failing anchor for this task is Task 1/2's unit tests; this is a GL smoke guard. Proceed to Step 3.

- [ ] **Step 3: Add the rim term to the fragment shader**

In `native/src/renderer/shaders/opaque.frag`, add the uniform after the `u_specular_enabled` block:

```glsl
// Fresnel rim light. u_rim_strength == 0.0 disables the term (set per
// draw by frame.cc: global RenderFresnelRim toggle AND per-instance
// rim_eligible AND material specular). Tinted by the accumulated
// directional light so the rim only shows where a star hits.
uniform float u_rim_strength;
const float RIM_POWER = 3.0;
```

Then change the final `frag_color` assignment to add the rim:

```glsl
    vec3 rim = vec3(0.0);
    if (u_rim_strength > 0.0) {
        float f = pow(1.0 - max(dot(n, V), 0.0), RIM_POWER);
        rim = f * lit_dir * u_rim_strength;
    }

    frag_color = vec4(lit + u_emissive_color + glow.rgb * glow.a + spec + rim, 1.0);
```

(`n`, `V`, and `lit_dir` are all already computed earlier in `main()`.)

- [ ] **Step 4: Add the `dauntless_rim` global toggle in frame.cc**

In `native/src/renderer/frame.cc`, after the `dauntless_specular` namespace block (ends line 31), add:

```cpp
// Toggle for the opaque-pass Fresnel rim term. Default on so the
// "Modern VFX" group ships enabled. host_bindings.cc forward-declares
// set_enabled; frame.cc reads enabled() per draw when binding the
// opaque shader's u_rim_strength.
namespace dauntless_rim {
namespace {
    bool g_rim_enabled = true;
}
    bool enabled() { return g_rim_enabled; }
    void set_enabled(bool v) { g_rim_enabled = v; }
}
```

- [ ] **Step 5: Thread a `rim_active` flag through `draw_model`**

In `native/src/renderer/frame.cc`, change the `draw_model` signature (line 37) to add a trailing parameter:

```cpp
void draw_model(const assets::Model& model,
                const glm::mat4& world,
                Shader& shader,
                GLuint white_fallback,
                GLuint black_fallback,
                bool rim_active) {
```

Inside `draw_model`, immediately after the `shader.set_int("u_specular_enabled", ...)` call (line 111-112), add:

```cpp
            const float rim = rim_active
                ? renderer::rim_strength_from_material(mat.specular, mat.glossiness)
                : 0.0f;
            shader.set_float("u_rim_strength", rim);
```

(`renderer/lighting.h` is already `#include`d in frame.cc via `"renderer/lighting.h"` at line 2; confirm and add the include if missing.)

- [ ] **Step 6: Pass `rim_active` from both submit functions**

In `submit_opaque` (line 194-197), change the lambda body:

```cpp
    world.for_each_visible([&](const scenegraph::Instance& inst) {
        const assets::Model* m = lookup(inst.model_handle);
        const bool rim_active = dauntless_rim::enabled() && inst.rim_eligible;
        if (m) draw_model(*m, inst.world, shader, white, black, rim_active);
    });
```

In `submit_opaque_in_pass` (line 229-232), change the lambda body:

```cpp
    world.for_each_visible_in_pass(pass, [&](const scenegraph::Instance& inst) {
        const assets::Model* m = lookup(inst.model_handle);
        const bool rim_active = dauntless_rim::enabled() && inst.rim_eligible;
        if (m) draw_model(*m, inst.world, shader, white, black, rim_active);
    });
```

Add the forward declaration of `dauntless_rim::enabled()` at the top of `frame.cc`'s `renderer` usage — it is already defined above in the same translation unit (Step 4), so no forward decl is needed within frame.cc.

- [ ] **Step 7: Reconfigure (shader embed) + build + run the smoke test**

Run: `cmake -B build -S . && cmake --build build -j renderer_tests && ctest --test-dir build -R "FrameTest.OpaquePass" -V`
Expected: PASS or SKIP (skips only if BC assets absent). No GL errors.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag native/src/renderer/frame.cc native/tests/renderer/frame_test.cc
git commit -m "feat(renderer): Fresnel rim term in opaque pass, gated per-instance + global toggle

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Host bindings — `rim_set_enabled` + `set_rim_eligible`

**Files:**
- Modify: `native/src/host/host_bindings.cc:324-329` (forward-decl), `:370-374` (set_visible neighbourhood), `:672-675` (specular_set_enabled neighbourhood)

No new test (these are thin pybind11 shims; covered by the Python wrapper test in Task 5 and the C++ tests already written).

- [ ] **Step 1: Forward-declare the rim toggle**

In `native/src/host/host_bindings.cc`, after the `dauntless_specular` forward-decl block (lines 326-329), add:

```cpp
namespace dauntless_rim {
    void set_enabled(bool v);  // defined in frame.cc
}
```

- [ ] **Step 2: Expose `rim_set_enabled`**

After the `specular_set_enabled` definition (lines 672-675), add:

```cpp
    m.def("rim_set_enabled",
          [](bool enabled) { dauntless_rim::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle the opaque-pass Fresnel rim term. Default: on.");
```

- [ ] **Step 3: Expose `set_rim_eligible`**

After the `set_visible` definition (lines 370-374), add:

```cpp
    m.def("set_rim_eligible",
          [](scenegraph::InstanceId id, bool eligible) {
              g_world.set_rim_eligible(id, eligible);
          },
          py::arg("instance"), py::arg("eligible"),
          "Mark an instance as a ship hull eligible for the Fresnel rim "
          "term. Default false (planets stay rim-free).");
```

- [ ] **Step 4: Build the host module**

Run: `cmake --build build -j`
Expected: builds clean; `build/python/_dauntless_host.cpython-*.so` (or `_open_stbc_host`) regenerated.

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(host): expose rim_set_enabled + set_rim_eligible bindings

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Python renderer wrappers

**Files:**
- Modify: `engine/renderer.py:151-153` (after `set_specular_enabled`)
- Test: `tests/unit/test_renderer_rim.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_renderer_rim.py`:

```python
"""engine.renderer rim wrappers forward to the host module."""
from unittest.mock import MagicMock

import engine.renderer as renderer


def test_set_rim_enabled_forwards(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_rim_enabled(False)
    fake.rim_set_enabled.assert_called_once_with(False)


def test_set_rim_eligible_forwards(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_rim_eligible(7, True)
    fake.set_rim_eligible.assert_called_once_with(7, True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_renderer_rim.py -v`
Expected: FAIL — `module 'engine.renderer' has no attribute 'set_rim_enabled'`.

- [ ] **Step 3: Add the wrappers**

In `engine/renderer.py`, after `set_specular_enabled` (line 151-153), add:

```python
def set_rim_enabled(enabled: bool) -> None:
    """Toggle the opaque-pass Fresnel rim term. Default: on after init()."""
    _h.rim_set_enabled(enabled)


def set_rim_eligible(instance_id: InstanceId, eligible: bool) -> None:
    """Mark a ship-hull instance as eligible for the Fresnel rim term.
    Planets are left ineligible so they don't receive a metallic rim."""
    _h.set_rim_eligible(instance_id, eligible)
```

(`InstanceId` is already imported/aliased in renderer.py — it is used by `shield_register` etc.; confirm the existing alias and reuse it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_renderer_rim.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/renderer.py tests/unit/test_renderer_rim.py
git commit -m "feat(renderer-py): set_rim_enabled + set_rim_eligible wrappers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Tag ship instances rim-eligible + wire the panel applier in host_loop

**Files:**
- Modify: `engine/host_loop.py:1681` (after ship instance creation)
- Modify: `engine/host_loop.py:2056-2067` (ConfigurationPanel construction)

No dedicated automated test (host_loop wiring is exercised by integration/smoke runs and the visual check in Task 9). Keep the edits minimal and surgical.

- [ ] **Step 1: Tag ship hulls as rim-eligible**

In `engine/host_loop.py`, immediately after `sess.ship_instances[ship] = iid` (line 1681), add:

```python
            # Fresnel rim applies to ship hulls only — planets share the
            # opaque shader and must stay rim-free (default ineligible).
            r_.set_rim_eligible(iid, True)
```

(Do **not** add this in the planet loop at ~line 1723 — planets must remain ineligible.)

- [ ] **Step 2: Add the rim setting + applier to the ConfigurationPanel**

In `engine/host_loop.py`, in the `SettingsSnapshot(...)` constructed for the panel (lines 2057-2064), add `rim_on=True`:

```python
            initial_settings=SettingsSnapshot(
                dust_on=True,
                specular_on=True,
                rim_on=True,
                fov_deg=int(round(_math.degrees(
                    director.fov_y_rad
                ))),
            ),
```

And in the `ConfigurationPanel(...)` applier kwargs (lines 2065-2067), add `set_rim`:

```python
            set_dust=r.set_dust_enabled,
            set_specular=r.set_specular_enabled,
            set_rim=r.set_rim_enabled,
            set_fov_rad=director.set_fov,
```

- [ ] **Step 3: Smoke-import host_loop**

Run: `uv run python -c "import engine.host_loop"`
Expected: no ImportError / no SyntaxError.

- [ ] **Step 4: Commit** (after Task 7 makes `SettingsSnapshot`/`ConfigurationPanel` accept the new args — see note)

> NOTE: `SettingsSnapshot` and `ConfigurationPanel.__init__` do not yet accept `rim_on` / `set_rim`. **Do Task 7 before running the host**, then commit Task 6 + Task 7 together if you prefer, or commit Task 7 first. To keep commits atomic, reorder: implement Task 7, then Task 6. The plan lists them in dependency order for reading; commit order is Task 7 → Task 6.

```bash
git add engine/host_loop.py
git commit -m "feat(host-loop): tag ship hulls rim-eligible + wire rim toggle into config panel

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: ConfigurationPanel — `rim_on` setting + toggle (do BEFORE Task 6 commit)

**Files:**
- Modify: `engine/ui/configuration_panel.py` (dataclass, `__init__`, `render_payload`, `dispatch_event`, `_focusables`, `handle_input`)
- Test: `tests/unit/test_configuration_panel.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_configuration_panel.py` (and update the `_make` factory's `SettingsSnapshot` to include `rim_on=True` and add `set_rim=Mock()` to its kwargs):

```python
def test_toggle_rim_fires_applier_and_flips_state():
    p, kw = _make()
    assert p._settings.rim_on is True
    handled = p.dispatch_event("toggle:rim")
    assert handled is True
    kw["set_rim"].assert_called_once_with(False)
    assert p._settings.rim_on is False


def test_render_payload_includes_rim_on():
    p, _ = _make()
    p.open()
    js = p.render_payload()
    assert js is not None
    payload = json.loads(js[len("setConfigurationPanel("):-len(");")])
    assert payload["settings"]["rim_on"] is True


def test_rim_is_a_graphics_focusable():
    p, _ = _make()
    focusables = p._focusables()
    assert ("ctrl", "rim") in focusables
```

Update the `_make` factory at the top of the file:

```python
        initial_settings=SettingsSnapshot(
            dust_on=True, specular_on=True, rim_on=True, fov_deg=70,
        ),
        set_dust=Mock(),
        set_specular=Mock(),
        set_rim=Mock(),
        set_fov_rad=Mock(),
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_configuration_panel.py -v`
Expected: FAIL — `SettingsSnapshot.__init__() got an unexpected keyword argument 'rim_on'` (and the new assertions).

- [ ] **Step 3: Extend `SettingsSnapshot`**

In `engine/ui/configuration_panel.py`, add `rim_on` to the dataclass:

```python
@dataclass
class SettingsSnapshot:
    dust_on: bool
    specular_on: bool
    rim_on: bool
    fov_deg: int
```

- [ ] **Step 4: Extend `__init__`**

Add the `set_rim` parameter and store it + the setting. Change the signature (after `set_specular`):

```python
                 set_dust: Callable[[bool], None],
                 set_specular: Callable[[bool], None],
                 set_rim: Callable[[bool], None],
                 set_fov_rad: Callable[[float], None]):
```

In the body, extend the `SettingsSnapshot` copy and store the applier:

```python
        self._settings = SettingsSnapshot(
            dust_on=initial_settings.dust_on,
            specular_on=initial_settings.specular_on,
            rim_on=initial_settings.rim_on,
            fov_deg=int(initial_settings.fov_deg),
        )
        self._set_dust = set_dust
        self._set_specular = set_specular
        self._set_rim = set_rim
        self._set_fov_rad = set_fov_rad
```

- [ ] **Step 5: Include `rim_on` in `render_payload`**

Add `self._settings.rim_on` to the `snapshot` tuple (after `specular_on`):

```python
        snapshot = (
            self._visible,
            tuple(self._tabs),
            self._selected_tab,
            self._focused,
            self._settings.dust_on,
            self._settings.specular_on,
            self._settings.rim_on,
            self._settings.fov_deg,
        )
```

And add it to the payload `settings` dict:

```python
            "settings": {
                "dust_on": self._settings.dust_on,
                "specular_on": self._settings.specular_on,
                "rim_on": self._settings.rim_on,
                "fov_deg": self._settings.fov_deg,
            },
```

- [ ] **Step 6: Handle `toggle:rim` in `dispatch_event`**

After the `toggle:specular` block (line 110-114), add:

```python
        if action == "toggle:rim":
            new_val = not self._settings.rim_on
            self._set_rim(new_val)
            self._settings.rim_on = new_val
            return True
```

- [ ] **Step 7: Add `rim` to `_focusables` and `handle_input`**

In `_focusables`, append rim after fov:

```python
        if self._selected_tab == "graphics":
            out += [("ctrl", "dust"), ("ctrl", "specular"),
                    ("ctrl", "fov"), ("ctrl", "rim")]
```

In `handle_input`, add a rim activation branch next to the specular one (after the `elif activate and kind == "ctrl" and target == "specular":` block):

```python
        elif activate and kind == "ctrl" and target == "rim":
            self.dispatch_event("toggle:rim")
```

(Note: keep the existing `elif activate and kind == "tab":` branch last so tab activation still works.)

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_configuration_panel.py -v`
Expected: PASS (existing tests + 3 new).

- [ ] **Step 9: Commit**

```bash
git add engine/ui/configuration_panel.py tests/unit/test_configuration_panel.py
git commit -m "feat(ui): ConfigurationPanel Fresnel rim toggle

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

(Then return to Task 6 Step 4 and commit the host_loop wiring.)

---

### Task 8: CEF UI — "Modern VFX" group + Fresnel Rim row

**Files:**
- Modify: `native/assets/ui-cef/js/configuration_panel.js:17-27` (`_cpFocusableList`), `:48-89` (`_cpRenderGraphicsBody`)
- Modify: `native/assets/ui-cef/css/configuration_panel.css` (group header + divider styles)

No JS test infra exists; this is validated visually in Task 9. Keep the JS focusable order identical to the Python `_focusables` (tabs, dust, specular, fov, rim).

- [ ] **Step 1: Add `rim` to the JS focusable list**

In `native/assets/ui-cef/js/configuration_panel.js`, in `_cpFocusableList`, append rim after fov:

```javascript
    if (state.selected_tab === 'graphics') {
        out.push({kind: 'ctrl', target: 'dust'});
        out.push({kind: 'ctrl', target: 'specular'});
        out.push({kind: 'ctrl', target: 'fov'});
        out.push({kind: 'ctrl', target: 'rim'});
    }
```

- [ ] **Step 2: Render the Modern VFX header + Fresnel Rim row**

In `_cpRenderGraphicsBody`, after the FOV row's closing (`return html;` is just below it), insert before `return html;`:

```javascript
    // ── Modern VFX group ─────────────────────────────────────────────
    html += '<hr class="cp-divider">';
    html += '<div class="cp-group-header">Modern VFX</div>';

    // Fresnel Rim Light toggle
    html += '<div class="cp-row' + (isFoc('rim') ? ' cp-focused' : '') + '">'
          +   '<div class="cp-row__label">Fresnel Rim Light</div>'
          +   '<div class="cp-row__control">'
          +     '<button class="cp-toggle' + (s.rim_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:rim\')">'
          +       (s.rim_on ? 'On' : 'Off')
          +     '</button>'
          +   '</div>'
          + '</div>';
```

- [ ] **Step 3: Add group-header + divider CSS**

In `native/assets/ui-cef/css/configuration_panel.css`, append:

```css
.cp-divider {
    border: none;
    border-top: 1px solid rgba(120, 160, 220, 0.35);
    margin: 14px 0 10px 0;
}

.cp-group-header {
    font-size: 12px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: rgba(150, 190, 240, 0.85);
    margin: 0 0 8px 2px;
}
```

(Match the existing palette — sample an existing color from `configuration_panel.css` and align the divider/header hues to it rather than these placeholders if they clash.)

- [ ] **Step 4: Commit**

```bash
git add native/assets/ui-cef/js/configuration_panel.js native/assets/ui-cef/css/configuration_panel.css
git commit -m "feat(ui-cef): Modern VFX group + Fresnel Rim Light row

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: Full build + visual verification

**Files:** none (verification only)

- [ ] **Step 1: Clean reconfigure + build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: builds clean, `build/dauntless` produced.

- [ ] **Step 2: Run the focused test sets**

Run:
```bash
ctest --test-dir build -R "World|Lighting|FrameTest" -V
uv run pytest tests/unit/test_configuration_panel.py tests/unit/test_renderer_rim.py -v
```
Expected: all PASS (renderer GL tests SKIP only if BC assets absent).

- [ ] **Step 3: Visual check**

Run: `./build/dauntless`
Verify:
- A ship hull shows a bright lit edge facing the star (rim), strongest at the silhouette where a star grazes; no rim on the unlit side.
- Planets show **no** rim (confirm a planet in-frame stays as before).
- Open the pause menu → Configuration → Graphics: a "Modern VFX" header appears under the FOV row with a "Fresnel Rim Light: On" toggle.
- Toggling it Off removes the hull rim immediately; On restores it. (This is the "restore original look" escape hatch for the rim half of Modern VFX.)

- [ ] **Step 4: Final commit (if any visual-tuning tweaks to RIM_POWER or the strength curve were needed)**

```bash
git add -A
git commit -m "chore(renderer): tune Fresnel rim falloff after visual check

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage** (against `project_modern_vfx_design` memory + this conversation):
- "Fresnel Rim Light: On/Off toggle, default On" → Tasks 4–8 (global toggle defaults true in Task 3; panel default true in Tasks 6–7). ✓
- "term in opaque.frag, modulated by key light (lit_dir), pow(1-dot(n,V),k)" → Task 3 Step 3. ✓
- "rim strength derived from material specular" → Task 2 + Task 3 Step 5. ✓
- "hulls only; planets share opaque.frag; gate per-instance" → Task 1 (flag) + Task 3 Step 6 (gate) + Task 6 Step 1 (ships tagged, planets not). ✓
- "Modern VFX group under an hr + header in config panel" → Task 8 Steps 2–3. ✓
- "does NOT gate on SpecularCoef" → honored: strength comes from material specular, not the SDK key (documented in Task 2). ✓
- "off reproduces original look for the rim" → toggle Off sets u_rim_strength=0 → no rim term (Task 3); verified Task 9 Step 3. ✓

**HDR (out of scope here):** intentionally deferred to plan 2 — this plan is rim-only and the Modern VFX group it creates is where HDR's toggle will later be added. Not a gap.

**Placeholder scan:** No TBDs. CSS colors in Task 8 Step 3 are concrete values with a "match existing palette" caveat — acceptable (concrete fallback provided).

**Type consistency:** `rim_eligible` (bool), `set_rim_eligible(InstanceId,bool)`, `rim_set_enabled(bool)`, `set_rim_enabled`, `dauntless_rim::{enabled,set_enabled}`, `rim_strength_from_material(vec3,float)`, `u_rim_strength` (float), `rim_on` setting, `toggle:rim` action, `("ctrl","rim")` focusable — names match across C++, Python, and JS layers throughout.

**Commit-order caveat:** Task 6 depends on Task 7's `SettingsSnapshot.rim_on` / `set_rim` param. Implement Task 7 before running/committing Task 6 (flagged inline in Task 6 Step 4).
