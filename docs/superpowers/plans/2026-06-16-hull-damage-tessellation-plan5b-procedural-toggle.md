# Hull Damage Tessellation — Plan 5b: Procedural Gouge + Modern VFX Toggle

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a shader-synthesized ("procedural") gouge interior as an alternative to the `Damage.tga` baseline, switchable at runtime via a new **Modern VFX → Procedural hull damage** config toggle (default off = stock `Damage.tga`).

**Architecture:** A `u_procedural_damage` int uniform selects the gouge interior in `opaque.frag`: 0 → the existing triplanar `Damage.tga` sample (Plan 5a baseline); 1 → a procedural charred-metal interior synthesized from the fragment's body position via the `fbm` noise already in the shader (no texture, consistent across ships). The flag is a new `dauntless_procedural_damage` namespace in `frame.cc` (same pattern as the existing `dauntless_rim`/`dauntless_decals` toggles), set into `u_procedural_damage` per draw, exposed to Python via a pybind setter → `engine/renderer.py` wrapper → a `ConfigurationPanel` toggle → `host_loop` wiring. Defaults **off** (the toggle's "off" = the faithful stock interior; "on" = the modern synthesized look), so out of the box the gouge looks exactly like Plan 5a.

**Tech Stack:** C++20, GLSL 330 (opaque.frag), pybind11, Python (engine/renderer.py, configuration_panel.py, host_loop.py), GoogleTest (renderer GPU readback) + pytest (config panel).

**Spec:** `docs/superpowers/specs/2026-06-16-hull-damage-tessellation-design.md` — §Config / Modern VFX ("Procedural hull damage — off (default) = stock Damage.tga; on = shader-synthesized"), §Three damage looks (gouge interior).

**Branch:** STACK on `feat/hull-damage-gouge` (Plan 5a's branch) — these commits go on top of 5a, NOT a fresh branch off main.

---

## Key facts for the implementer (you have zero context — read these)

- bc_dauntless is an open C++ reimplementation of Star Trek: Bridge Commander. ONE build tree at the project root: `cmake -B build -S . && cmake --build build -j` from `/Users/mward/Documents/Projects/bc_dauntless`. **NEVER** run cmake inside `native/`.
- **Plan 5a (already on this branch)** added the gouge block to `opaque.frag`: where `v_deform_depth > RUPTURE_MIN`, it triplanar-samples `u_damage_texture` (unit 3) in body space → `interior` → charred-ring blend → `lit = mix(lit, gouge_color, gouge)`. **This task makes the `interior` source switchable.** `opaque.frag` already has `fbm(vec2)`, `vnoise`, `dhash` noise helpers (used by the decal system) you can reuse for the procedural interior.
- **Modern VFX toggle pattern (5 places)** — replicate exactly how `dauntless_rim` / `dauntless_decals` work:
  1. `native/src/renderer/frame.cc` top: `namespace dauntless_X { bool g_*_enabled = <default>; bool enabled(){return g_*_enabled;} void set_enabled(bool v){g_*_enabled=v;} }`.
  2. `native/src/host/host_bindings.cc`: forward-declare the namespace's `enabled`/`set_enabled`, then `m.def("X_set_enabled", [](bool e){ dauntless_X::set_enabled(e); }, py::arg("enabled"), "...")`.
  3. `engine/renderer.py`: `def set_X_enabled(enabled: bool) -> None: _h.X_set_enabled(enabled)`.
  4. `engine/ui/configuration_panel.py`: a `SettingsSnapshot` bool field + a `toggle:X` action that calls the injected setter then mutates state (+ render it in the panel's payload).
  5. `engine/host_loop.py`: pass the initial state + wire `set_X=r.set_X_enabled` into the `ConfigurationPanel` constructor.
- **How a flag reaches the shader:** `frame.cc` reads `dauntless_X::enabled()` and uploads a uniform. For this feature, set `u_procedural_damage` to 0/1 in `draw_model` alongside the existing `u_damage_texture` bind (which Plan 5a added at unit 3).
- **The flag DEFAULT is `false`** (unlike rim/hdr/decals which default true): the spec says procedural is OFF by default so the stock `Damage.tga` interior is the out-of-the-box look. `g_procedural_enabled = false`.
- **Config panel tests:** `tests/unit/test_configuration_panel.py` exercises `ConfigurationPanel` with fake injected setters. Mirror its style. `SettingsSnapshot` is a dataclass holding the toggle bools; the panel calls the setter BEFORE mutating local state.
- **Renderer GPU test:** the gouge effect is driven via the deform program + a deep crater + `glVertexAttrib1f(7, 1.0f)` (see `gouge_shading_test.cc` from Plan 5a). To test the procedural path, set `u_procedural_damage = 1` and assert the deep region is NOT the base color (no damage texture needed — procedural synthesizes its own).

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `native/src/renderer/shaders/opaque.frag` | `u_procedural_damage` uniform + procedural interior fn; select interior source | Modify |
| `native/src/renderer/frame.cc` | `dauntless_procedural_damage` namespace + set `u_procedural_damage` in draw_model | Modify |
| `native/src/host/host_bindings.cc` | pybind `procedural_damage_set_enabled` | Modify |
| `engine/renderer.py` | `set_procedural_damage_enabled` wrapper | Modify |
| `engine/ui/configuration_panel.py` | `procedural_damage_on` setting + toggle action | Modify |
| `engine/host_loop.py` | wire the toggle into ConfigurationPanel | Modify |
| `native/tests/renderer/gouge_shading_test.cc` | procedural-path render test | Modify |
| `tests/unit/test_configuration_panel.py` | toggle unit test | Modify |

---

## Task 1: Procedural interior + `u_procedural_damage` selector in `opaque.frag`

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag`
- Test: `native/tests/renderer/gouge_shading_test.cc` (append)

- [ ] **Step 1: Write the failing test**

Append to `native/tests/renderer/gouge_shading_test.cc` a test that renders the deform program with a deep crater and `u_procedural_damage = 1` (NO damage texture bound) and asserts the deeply-displaced centre is NOT the lit base color (the procedural interior is dark charred metal, so the centre is much darker than the lit-white base):

```cpp
TEST(GougeShading, ProceduralInteriorDiffersFromBase) {
    try {
        renderer::Window w(64, 64, "gouge-proc-test", /*visible=*/false);
        renderer::Pipeline pipeline;
        ASSERT_TRUE(pipeline.tessellation_available());
        renderer::Shader& prog = pipeline.deform_shader();

        const float verts[] = {
            -0.9f, -0.9f, 0.0f,  0.9f,  0.9f, 0.0f,  0.9f, -0.9f, 0.0f,  // CW
            -0.9f, -0.9f, 0.0f, -0.9f,  0.9f, 0.0f,  0.9f,  0.9f, 0.0f,
        };
        GLuint vao = 0, vbo = 0;
        glGenVertexArrays(1, &vao);
        glGenBuffers(1, &vbo);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
        glEnableVertexAttribArray(0);
        glVertexAttrib1f(7, 1.0f);

        glViewport(0, 0, 64, 64);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);

        prog.use();
        glm::mat4 I(1.0f);
        prog.set_mat4("u_model", I);
        prog.set_mat4("u_view", I);
        prog.set_mat4("u_proj", I);
        prog.set_mat4("u_ship_world", I);
        prog.set_mat4("u_ship_world_inv", I);
        prog.set_vec3("u_ambient_light", glm::vec3(1.0f));
        prog.set_int("u_dir_light_count", 0);
        prog.set_vec3("u_diffuse_color", glm::vec3(1.0f));
        prog.set_float("u_emissive_scale", 0.0f);
        prog.set_int("u_decal_count", 0);
        prog.set_int("u_glow_region_count", 0);
        prog.set_int("u_procedural_damage", 1);   // procedural interior
        prog.set_int("u_crater_count", 1);
        glm::vec4 ca(0.0f, 0.0f, 0.0f, 0.6f);
        glm::vec4 cb(0.0f, 0.0f, -1.0f, 0.5f);
        prog.set_vec4_array("u_crater_a", &ca, 1);
        prog.set_vec4_array("u_crater_b", &cb, 1);

        while (glGetError() != GL_NO_ERROR) {}
        glPatchParameteri(GL_PATCH_VERTICES, 3);
        glDrawArrays(GL_PATCHES, 0, 6);

        unsigned char center[4] = {0, 0, 0, 0};
        glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, center);
        EXPECT_EQ(glGetError(), GLenum(GL_NO_ERROR));
        // Procedural charred-metal interior is dark; the lit base is white.
        // The gouged centre must be much darker than full-white base.
        EXPECT_LT(center[0], 150) << "procedural gouge centre should be dark charred metal, not lit base";

        glDeleteBuffers(1, &vbo);
        glDeleteVertexArrays(1, &vao);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests && ctest --test-dir build -R "GougeShading.ProceduralInteriorDiffersFromBase" --output-on-failure`
Expected: FAIL — `opaque.frag` has no `u_procedural_damage`; the gouge centre samples the (unbound→white) `u_damage_texture`, so it's NOT dark → `EXPECT_LT(center[0], 150)` fails. (With no damage texture bound, unit 3 reads white → centre ~white.)

- [ ] **Step 3: Add the procedural interior + selector to `opaque.frag`**

(a) Add the uniform near the other gouge constants (added in Plan 5a):
```glsl
uniform int u_procedural_damage;   // 0 = sample Damage.tga (baseline); 1 = procedural interior
```

(b) Add a procedural interior helper function above `main()` (reuse the existing `fbm`):
```glsl
// Procedural torn-hull interior: charred dark metal with fbm-broken exposed
// structure. Body-position-driven so it's stable on the hull and needs no
// texture asset. The "Modern VFX -> Procedural hull damage" alternative to the
// stock Damage.tga interior.
vec3 procedural_gouge_interior(vec3 p_body) {
    float n = fbm(p_body.xy * 0.4 + p_body.z * vec2(0.3, 0.5));
    vec3 charred = vec3(0.05, 0.045, 0.040);   // burnt edge
    vec3 metal   = vec3(0.18, 0.165, 0.150);   // exposed structural metal
    return mix(charred, metal, smoothstep(0.4, 0.7, n));
}
```

(c) In the gouge block (Plan 5a), replace the `interior` computation so it selects the source. The Plan 5a code computes the triplanar `interior` unconditionally; wrap it:
```glsl
        vec3 interior;
        if (u_procedural_damage != 0) {
            interior = procedural_gouge_interior(p_body);
        } else {
            vec3 bw = abs(n_body);
            bw /= (bw.x + bw.y + bw.z + 1e-5);
            vec3 dx = texture(u_damage_texture, p_body.yz * DAMAGE_TEX_SCALE).rgb;
            vec3 dy = texture(u_damage_texture, p_body.zx * DAMAGE_TEX_SCALE).rgb;
            vec3 dz = texture(u_damage_texture, p_body.xy * DAMAGE_TEX_SCALE).rgb;
            interior = dx * bw.x + dy * bw.y + dz * bw.z;
        }
```
(Keep the rest of the gouge block — the `ring`/`gouge_color`/`lit = mix(...)` — unchanged below this.)

- [ ] **Step 4: Run to verify it passes**

Run: `cmake --build build -j --target renderer_tests && ctest --test-dir build -R "GougeShading|DeformPipeline" --output-on-failure`
Expected: the new procedural test PASSES (dark centre); the Plan 5a `DeepDisplacementShowsDamageTexture` test still PASSES (it doesn't set `u_procedural_damage` → defaults to 0 → texture path). Confirm the baseline test still binds + samples the texture (u_procedural_damage uniform defaults to 0 when unset in a fresh program).

- [ ] **Step 5: Full suite**

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure`
Expected: full suite PASS/SKIPPED. Static path (no gouge) unaffected.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag native/tests/renderer/gouge_shading_test.cc
git commit -m "feat(renderer): procedural gouge interior selectable via u_procedural_damage"
```

---

## Task 2: `dauntless_procedural_damage` flag + uniform upload + pybind setter

**Files:**
- Modify: `native/src/renderer/frame.cc`
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/renderer.py`

- [ ] **Step 1: Add the flag namespace in frame.cc**

In `native/src/renderer/frame.cc`, near the other `dauntless_*` toggle namespaces (e.g. after `dauntless_decals`), add:
```cpp
// "Modern VFX -> Procedural hull damage": when ON, gouge interiors are
// shader-synthesized instead of sampling Damage.tga. Defaults OFF so the stock
// texture interior is the out-of-the-box look (spec §Config).
namespace dauntless_procedural_damage {
    bool g_enabled = false;
    bool enabled() { return g_enabled; }
    void set_enabled(bool v) { g_enabled = v; }
}
```

- [ ] **Step 2: Upload `u_procedural_damage` in draw_model**

In `draw_model`, where Plan 5a binds the damage texture (the unit-3 block setting `u_damage_texture`), add right after it:
```cpp
    prog.set_int("u_procedural_damage", dauntless_procedural_damage::enabled() ? 1 : 0);
```
(Free function call to the namespace; `draw_model` is in the same translation unit as the namespace.)

- [ ] **Step 3: Build + confirm no regression**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure`
Expected: full suite PASS/SKIPPED. The flag defaults off → `u_procedural_damage = 0` → texture path → render unchanged from Plan 5a. (The Task 1 procedural test sets the uniform directly, bypassing the flag, so it's unaffected.)

- [ ] **Step 4: Commit the C++ flag**

```bash
git add native/src/renderer/frame.cc
git commit -m "feat(renderer): dauntless_procedural_damage flag drives u_procedural_damage"
```

- [ ] **Step 5: Add the pybind setter**

In `native/src/host/host_bindings.cc`, near the other `dauntless_*` forward-decls (e.g. by `dauntless_decals`), add:
```cpp
namespace dauntless_procedural_damage {
    bool enabled();
    void set_enabled(bool v);
}
```
and near the other `*_set_enabled` defs (e.g. by `decals_set_enabled`):
```cpp
    m.def("procedural_damage_set_enabled",
          [](bool enabled) { dauntless_procedural_damage::set_enabled(enabled); },
          py::arg("enabled"),
          "Toggle procedural (shader-synthesized) hull-damage gouge interiors. "
          "Default off = stock Damage.tga interior.");
```

- [ ] **Step 6: Add the renderer.py wrapper**

In `engine/renderer.py`, near `set_decals_enabled`, add:
```python
def set_procedural_damage_enabled(enabled: bool) -> None:
    """Toggle procedural (shader-synthesized) hull-damage gouge interiors.
    Default off = stock Damage.tga interior."""
    fn = getattr(_h, "procedural_damage_set_enabled", None)
    if fn is not None:
        fn(enabled)
```
(getattr-guarded so it degrades gracefully if the binding is absent, matching the established optional-binding pattern.)

- [ ] **Step 7: Build both artifacts + smoke-check the binding**

Run: `cmake -B build -S . && cmake --build build -j`
Then: `PYTHONPATH=build/python python3 -c "import _dauntless_host as h; print(hasattr(h,'procedural_damage_set_enabled'))"` (expect `True`; if the bare import fails for shim reasons, rely on the clean build + Task 3's pytest).

- [ ] **Step 8: Commit the binding + wrapper**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py
git commit -m "feat(host): expose procedural_damage_set_enabled to Python"
```

---

## Task 3: Config panel toggle + host_loop wiring

**Files:**
- Modify: `engine/ui/configuration_panel.py`
- Modify: `engine/host_loop.py`
- Test: `tests/unit/test_configuration_panel.py`

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_configuration_panel.py`, mirror an existing toggle test (e.g. the decals one). Add a test that constructs the panel with a recording `set_procedural_damage` setter and a `procedural_damage_on=False` initial state, fires the `toggle:procedural_damage` action, and asserts the setter was called with `True` and the snapshot flipped:

```python
def test_toggle_procedural_damage_calls_setter_and_flips_state():
    calls = []
    panel = _make_panel(set_procedural_damage=lambda v: calls.append(v))  # adapt to the fixture
    handled = panel.handle_action("toggle:procedural_damage")
    assert handled is True
    assert calls == [True]
    assert panel.settings().procedural_damage_on is True
```
(Adapt the panel construction + accessor names to match the existing tests in the file — read them first; the existing decals toggle test is the template.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_configuration_panel.py -k procedural_damage -v`
Expected: FAIL — no `procedural_damage` setting / action / setter.

- [ ] **Step 3: Add the setting + toggle to ConfigurationPanel**

In `engine/ui/configuration_panel.py`:
- Add `procedural_damage_on: bool` to the `SettingsSnapshot` dataclass (default `False`).
- Add a constructor param `set_procedural_damage` (an injected callable), stored as `self._set_procedural_damage`, mirroring `set_decals`.
- Add the toggle branch in the action handler (mirroring `toggle:decals`):
```python
    if action == "toggle:procedural_damage":
        new_val = not self._settings.procedural_damage_on
        self._set_procedural_damage(new_val)
        self._settings.procedural_damage_on = new_val
        return True
```
- Add the toggle to the panel's rendered payload/rows under the Modern VFX group (mirror how `decals`/`rim` rows are emitted), so the UI shows it.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/unit/test_configuration_panel.py -v`
Expected: the new test PASSES; existing config-panel tests still pass.

- [ ] **Step 5: Wire it in host_loop.py**

In `engine/host_loop.py`, where the `ConfigurationPanel` is constructed (the `SettingsSnapshot(...)` initial state + the `set_rim=`/`set_decals=` wiring), add:
- `procedural_damage_on=False` to the initial `SettingsSnapshot`.
- `set_procedural_damage=r.set_procedural_damage_enabled` to the constructor call.
(Match the exact existing call shape; `r` is the `engine.renderer` module.)

- [ ] **Step 6: Run the broader Python suite**

Run: `python -m pytest tests/unit/test_configuration_panel.py tests/unit/test_decal_emission.py -q` (and any host_loop test if present).
Expected: PASS. Optionally run the full pytest: `python -m pytest -q` (expect green).

- [ ] **Step 7: Commit**

```bash
git add engine/ui/configuration_panel.py engine/host_loop.py tests/unit/test_configuration_panel.py
git commit -m "feat(config): Modern VFX 'Procedural hull damage' toggle"
```

---

## Task 4: Full build + suite

**Files:** none (verification)

- [ ] **Step 1: Build + full native + Python suites**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure && python -m pytest -q`
Expected: both binaries build; native suite + pytest green (modulo pre-existing skips).

- [ ] **Step 2: Record the result**

No commit. The gouge interior is now switchable: default (toggle off) = stock `Damage.tga`; Modern VFX → Procedural hull damage on = synthesized charred-metal interior. Like the rest of the chain, only visible in battle once Plan 6 wires the crater trigger.

---

## Self-Review

**Spec coverage (Plan 5b scope = spec §Config Modern VFX procedural toggle):**
- §Config "Procedural hull damage — off (default) = stock Damage.tga; on = shader-synthesized" → `dauntless_procedural_damage` defaults false (Task 2); `u_procedural_damage` selects procedural vs triplanar texture in opaque.frag (Task 1). ✓
- §Config "joins the existing Modern VFX group … off/off = stock BC" → the toggle follows the 5-place rim/decals pattern; default off keeps the stock interior (Tasks 2/3). ✓
- §3 procedural interior "charred metal, exposed ribbing" → `procedural_gouge_interior` (fbm-driven charred→metal) (Task 1). ✓ (Embers at edges: the charred ring from Plan 5a + the decal ember system already composite over the gouge; a dedicated procedural ember is YAGNI unless the visual review calls for it.)
- §Config "the displacement (TES) is identical either way; only the FS gouge-fill branch differs" → only opaque.frag's `interior` source branches on `u_procedural_damage`; the TES/TCS are untouched. ✓

**Placeholder scan:** No TBD/TODO. The procedural color constants + fbm scale are documented tunables. The getattr-guard on the renderer.py wrapper matches the established optional-binding convention.

**Type consistency:** `u_procedural_damage` (int) is declared in opaque.frag (Task 1), set in the Task 1 test directly, and set in `draw_model` from `dauntless_procedural_damage::enabled()` (Task 2). The `dauntless_procedural_damage` namespace (`enabled`/`set_enabled`) is defined in frame.cc (Task 2), forward-declared + bound in host_bindings.cc as `procedural_damage_set_enabled` (Task 2), wrapped as `set_procedural_damage_enabled` in renderer.py (Task 2), and wired as `set_procedural_damage` into ConfigurationPanel (Task 3). `procedural_damage_on` is the SettingsSnapshot field + `toggle:procedural_damage` the action (Task 3). Consistent across all layers. ✓

---

## What comes next (not this plan)

- **Plan 6:** eligibility manager (player always-tessellated + capped nearest/largest) + `engine/appc/hull_deformation.py` (GU depth/kind mapping — and **calibrate `RUPTURE_MIN/MAX` to the real crater depths produced here**) + the `hit_feedback` dispatch hook calling `renderer.hull_deform_add` — the trigger that finally makes dents + gouges appear in battle. Plus carried-forward deferrals (Plan 2 M1/M3, Plan 3 probe_thickness exposure).
