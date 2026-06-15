# Viewscreen render-to-texture (step 5c) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In bridge view, render the forward space scene into an offscreen texture and map it onto the viewscreen instance, so the bridge's main screen shows a live picture-in-picture view of what's ahead.

**Architecture:** Reuse the existing bridge-mode space camera `g_camera` (already forward-from-ship) and the already-running space passes, redirected into one new offscreen `HdrTarget`. The bridge pass binds that HDR texture as the viewscreen instance's base color (matched by model handle) and draws it full-bright; the single main tonemap exposes it once. The player ship is hidden in bridge view. On/off honors the viewscreen object's `IsOn()`, default-on at realize.

**Tech Stack:** C++ / OpenGL (renderer + `host_bindings.cc`), Python host loop, pybind11, pytest. **Requires a full `dauntless` rebuild.**

**Spec:** `docs/superpowers/specs/2026-06-15-sdk-driven-bridge-viewscreen-rtt-step5c-design.md`

> ⚠️ **NEVER run the full pytest suite** (`uv run pytest` with no path) — it uses >100 GB RAM and freezes macOS. Always pass explicit test paths (every `Run:` below does). Warn any subagent.
>
> ⚠️ **Build from the project root only:** `cmake --build build -j` (and `cmake -B build -S .` first if `build/` isn't configured this session). **Never** run cmake from inside `native/`. `host_bindings.cc` compiles into BOTH `./build/dauntless` and the `_dauntless_host` module, so always rebuild the `dauntless` target. No new source files or shaders are added, so no `-B` reconfigure is needed for the edits themselves.
>
> ⚠️ **C++/GL correctness is not unit-testable here.** C++ tasks are verified by a clean compile; visual correctness is Mark's live-verify in Task 4. Do NOT fabricate a passing GL test.

---

## File Structure

- **Modify** `native/src/renderer/include/renderer/bridge_pass.h` — add viewscreen model-handle + texture setters/members.
- **Modify** `native/src/renderer/bridge_pass.cc` — thread a per-instance base-texture override (matched by model handle) through `walk_bridge_meshes` → `draw_mesh`; force emissive on the override draw.
- **Modify** `native/src/host/host_bindings.cc` — new `g_viewscreen_hdr` target + `g_viewscreen_enabled` flag + RTT-size constants; init/shutdown; two bindings (`set_viewscreen_model`, `set_viewscreen_enabled`); extract a `render_space` lambda in `frame()`; restructure `frame()` to render the space scene into the RTT in bridge view and feed the bridge pass.
- **Modify** `engine/renderer.py` — `set_viewscreen_model` / `set_viewscreen_enabled` wrappers.
- **Modify** `engine/host_loop.py` — `_realize_viewscreen` registers the model handle + defaults the screen on + caches the viewscreen object; two small pure helpers (`_viewscreen_feed_on`, `_apply_bridge_player_visibility`); per-frame wiring in `run()`; `controller.viewscreen_obj` slot.
- **Modify** `tests/unit/test_realize_viewscreen.py` — extend fake renderer/controller; assert model-handle registration + default-on.
- **Create** `tests/unit/test_viewscreen_rtt_host.py` — unit-test the two pure helpers.

---

## Task 1: BridgePass per-instance viewscreen texture override (C++)

**Files:**
- Modify: `native/src/renderer/include/renderer/bridge_pass.h`
- Modify: `native/src/renderer/bridge_pass.cc`

- [ ] **Step 1: Add setters + members to `bridge_pass.h`.**

In `native/src/renderer/include/renderer/bridge_pass.h`, add to the `public:` section after `set_wall_time` (line 41):

```cpp
    /// Identify the viewscreen instance by its model handle and supply the
    /// render-to-texture color texture to draw on it. When a Pass::Bridge
    /// instance's model_handle matches the registered viewscreen handle and
    /// the texture is non-zero, the base sub-pass binds `tex` as u_base_color
    /// and forces full emissive (so the feed isn't dimmed by bridge ambient).
    /// tex==0 (the default) restores the instance's authored NIF texture —
    /// the step-5b blank panel.
    void set_viewscreen_model(unsigned long long model_handle) {
        viewscreen_model_handle_ = model_handle;
    }
    void set_viewscreen_texture(unsigned int tex) { viewscreen_tex_ = tex; }
```

and to the `private:` section after `double wall_time_ = 0.0;` (line 50):

```cpp
    unsigned long long viewscreen_model_handle_ = 0;
    unsigned int       viewscreen_tex_ = 0;
```

- [ ] **Step 2: Thread the instance model handle through `walk_bridge_meshes`'s callback in `bridge_pass.cc`.**

In `native/src/renderer/bridge_pass.cc`, find the `DrawOne` typedef (just above `walk_bridge_meshes`, ~line 50). It currently is:

```cpp
using DrawOne = std::function<void(const assets::Model&, const assets::Mesh&,
                                   const assets::Material&, const glm::mat4&)>;
```

Replace it with (adds the instance's model handle):

```cpp
using DrawOne = std::function<void(const assets::Model&, const assets::Mesh&,
                                   const assets::Material&, const glm::mat4&,
                                   unsigned long long)>;
```

Then in `walk_bridge_meshes`, change the draw_one invocation (line 81) from:

```cpp
                    draw_one(*m, mesh, mat, world_per_node[i]);
```

to:

```cpp
                    draw_one(*m, mesh, mat, world_per_node[i], inst.model_handle);
```

> If the exact `DrawOne` typedef text differs, match on the `std::function<void(...)>` alias used by `walk_bridge_meshes`; the only change is appending `unsigned long long` and passing `inst.model_handle`.

- [ ] **Step 3: Add a `base_override` parameter to `draw_mesh` and use it.**

In `draw_mesh` (line 87), change the signature from:

```cpp
void draw_mesh(const assets::Model& model,
               const assets::Mesh& mesh,
               const assets::Material& mat,
               Shader& shader,
               const glm::mat4& world,
               GLuint white_fallback,
               double wall_time) {
```

to add a trailing `GLuint base_override`:

```cpp
void draw_mesh(const assets::Model& model,
               const assets::Mesh& mesh,
               const assets::Material& mat,
               Shader& shader,
               const glm::mat4& world,
               GLuint white_fallback,
               double wall_time,
               GLuint base_override) {
```

Then replace the base-texture bind block (lines 125-130) — currently:

```cpp
    glActiveTexture(GL_TEXTURE0);
    if (base_tex >= 0) {
        glBindTexture(GL_TEXTURE_2D, model.textures[base_tex].id());
    } else {
        glBindTexture(GL_TEXTURE_2D, white_fallback);
    }
```

with (override wins, and forces full emissive so bridge ambient doesn't dim the feed):

```cpp
    glActiveTexture(GL_TEXTURE0);
    if (base_override != 0) {
        // Viewscreen RTT feed: ignore the NIF base texture and draw the
        // offscreen scene full-bright (BC's emissive=(1,1,1) screen
        // convention -> FragColor = feed, unaffected by bridge ambient).
        glBindTexture(GL_TEXTURE_2D, base_override);
        shader.set_vec3("u_emissive", glm::vec3(1.0f));
    } else if (base_tex >= 0) {
        glBindTexture(GL_TEXTURE_2D, model.textures[base_tex].id());
    } else {
        glBindTexture(GL_TEXTURE_2D, white_fallback);
    }
```

- [ ] **Step 4: Pass the override from the base sub-pass; pass 0 from the skinned sub-pass.**

In `BridgePass::render`, the two base-pass `walk_bridge_meshes` calls (lines 185-194) have lambdas `[&](const assets::Model& m, const assets::Mesh& mesh, const assets::Material& mat, const glm::mat4& w) { draw_mesh(m, mesh, mat, base_shader, w, white, t); }`. Update BOTH lambdas to accept the new handle arg and compute the override:

```cpp
    walk_bridge_meshes(world, lookup, /*want_lightmap_pass=*/false,
        [&](const assets::Model& m, const assets::Mesh& mesh,
            const assets::Material& mat, const glm::mat4& w,
            unsigned long long mh) {
            const GLuint ov = (viewscreen_model_handle_ != 0
                               && mh == viewscreen_model_handle_)
                              ? viewscreen_tex_ : 0u;
            draw_mesh(m, mesh, mat, base_shader, w, white, t, ov);
        });
    walk_bridge_meshes(world, lookup, /*want_lightmap_pass=*/true,
        [&](const assets::Model& m, const assets::Mesh& mesh,
            const assets::Material& mat, const glm::mat4& w,
            unsigned long long mh) {
            const GLuint ov = (viewscreen_model_handle_ != 0
                               && mh == viewscreen_model_handle_)
                              ? viewscreen_tex_ : 0u;
            draw_mesh(m, mesh, mat, base_shader, w, white, t, ov);
        });
```

The skinned sub-pass calls `draw_mesh` directly (~line 237): `draw_mesh(*m, mesh, mat, skin_shader, inst.world, white, t);`. Append `, 0u` (characters never receive the viewscreen override):

```cpp
                    draw_mesh(*m, mesh, mat, skin_shader, inst.world, white, t, 0u);
```

- [ ] **Step 5: Build and verify it compiles.**

Run: `cmake --build build -j 2>&1 | tail -20`  (run `cmake -B build -S .` first if `build/` isn't configured this session)
Expected: builds the `dauntless` target and the `_dauntless_host` module with no errors. (Behavior is unchanged at runtime — `viewscreen_tex_` defaults to 0, so the override never fires until Tasks 2-3 wire it.)

- [ ] **Step 6: Commit.**

```bash
git add native/src/renderer/include/renderer/bridge_pass.h native/src/renderer/bridge_pass.cc
git commit -m "feat(bridge): per-instance viewscreen texture override in BridgePass (step 5c)

Match the viewscreen instance by model handle; when a non-zero RTT
texture is set, bind it as u_base_color and force emissive=(1,1,1) so
the feed draws full-bright. Defaults to 0 (no override) -> step-5b blank
panel, so runtime behavior is unchanged until the host wires it.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2a: Extract the space-scene passes into a `render_space` lambda (C++ refactor)

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`frame()`)

This is a **pure refactor** — identical runtime behavior. It isolates the space-pass list so Task 2b can call it with a second camera/target.

- [ ] **Step 1: Replace the inline space block with a lambda + call.**

In `native/src/host/host_bindings.cc::frame()`, the current block (lines 339-365) is:

```cpp
    if (!viewer_mode) {
        g_backdrop_pass->render(g_backdrops, g_camera, *g_pipeline);
        g_sun_pass->render(g_suns, g_camera, *g_pipeline, now);
        g_submitter->submit_opaque_in_pass(
            g_world, g_camera, *g_pipeline, lookup, g_lighting,
            scenegraph::Pass::Space, g_decal_game_time);

        if (g_shield_pass) g_shield_pass->submit(g_world, g_camera, *g_pipeline,
                                                  now, lookup);

        if (g_dust_pass) g_dust_pass->render(g_camera, dt, *g_pipeline,
                                             g_suns, g_dust_planets);

        if (g_lens_flare_pass) {
            g_lens_flare_pass->render(g_lens_flares, g_camera, *g_pipeline,
                                      fw, fh, now);
        }

        if (g_torpedo_pass) g_torpedo_pass->render(g_torpedoes,    g_camera, *g_pipeline);
        if (g_phaser_pass)  g_phaser_pass ->render(g_phaser_beams, g_camera, *g_pipeline);
        if (g_hit_vfx_pass) g_hit_vfx_pass->render(g_hit_vfx, g_world, g_camera, *g_pipeline);
        if (g_particle_pass) g_particle_pass->render(g_particle_emitters, g_world, g_camera, *g_pipeline);
    }
```

Replace it with (the lambda preserves the EXACT original pass order; the `!for_viewscreen` guards are always true here because the only call passes `false`, so behavior is identical):

```cpp
    // Renders the space scene from `cam` into the currently-bound FBO.
    // for_viewscreen=true skips the cockpit/screen-space effects that make no
    // sense on (or would corrupt state for) the viewscreen RTT: dust (camera-
    // anchored smear with cross-frame prev_eye state), lens flares (screen-
    // space, sized to the main framebuffer), and particles. Order is otherwise
    // identical to the historical inline block.
    auto render_space = [&](const scenegraph::Camera& cam, bool for_viewscreen) {
        g_backdrop_pass->render(g_backdrops, cam, *g_pipeline);
        g_sun_pass->render(g_suns, cam, *g_pipeline, now);
        g_submitter->submit_opaque_in_pass(
            g_world, cam, *g_pipeline, lookup, g_lighting,
            scenegraph::Pass::Space, g_decal_game_time);
        if (g_shield_pass) g_shield_pass->submit(g_world, cam, *g_pipeline, now, lookup);
        if (!for_viewscreen && g_dust_pass)
            g_dust_pass->render(cam, dt, *g_pipeline, g_suns, g_dust_planets);
        if (!for_viewscreen && g_lens_flare_pass)
            g_lens_flare_pass->render(g_lens_flares, cam, *g_pipeline, fw, fh, now);
        if (g_torpedo_pass) g_torpedo_pass->render(g_torpedoes,    cam, *g_pipeline);
        if (g_phaser_pass)  g_phaser_pass ->render(g_phaser_beams, cam, *g_pipeline);
        if (g_hit_vfx_pass) g_hit_vfx_pass->render(g_hit_vfx, g_world, cam, *g_pipeline);
        if (!for_viewscreen && g_particle_pass)
            g_particle_pass->render(g_particle_emitters, g_world, cam, *g_pipeline);
    };

    if (!viewer_mode) {
        render_space(g_camera, /*for_viewscreen=*/false);
    }
```

- [ ] **Step 2: Build and verify it compiles.**

Run: `cmake --build build -j 2>&1 | tail -20`
Expected: clean build. Runtime behavior is byte-identical (same passes, same order, same camera, same target).

- [ ] **Step 3: Commit.**

```bash
git add native/src/host/host_bindings.cc
git commit -m "refactor(host): extract frame() space-scene passes into render_space lambda (step 5c)

Pure refactor, no behavior change. Isolates the space-pass list (with a
for_viewscreen flag that skips dust/lens-flares/particles) so the next
step can render it into the viewscreen RTT with a second camera/target.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2b: Viewscreen RTT target, bindings, and frame() restructure (C++)

**Files:**
- Modify: `native/src/host/host_bindings.cc`

- [ ] **Step 1: Add the RTT target global, enabled flag, and size constants.**

In `native/src/host/host_bindings.cc`, after the `g_hdr_target` declaration (line 122):

```cpp
std::unique_ptr<renderer::HdrTarget>       g_viewscreen_hdr;
```

After `bool g_bridge_pass_enabled = false;` (line 135):

```cpp
bool g_viewscreen_enabled = false;

// Fixed resolution of the viewscreen render-to-texture feed (16:9). The screen
// quad is small, so this is plenty and keeps the second scene render cheap.
constexpr int kViewscreenRttW = 640;
constexpr int kViewscreenRttH = 360;
```

- [ ] **Step 2: Create/destroy the RTT target in init/shutdown.**

In `init` (after `g_hdr_target = std::make_unique<renderer::HdrTarget>();`, line 236):

```cpp
    g_viewscreen_hdr = std::make_unique<renderer::HdrTarget>();
```

In `shutdown` (after `g_hdr_target.reset();`, line 284):

```cpp
    g_viewscreen_hdr.reset();
```

Also in `shutdown`, after `g_bridge_pass_enabled = false;` (line 294):

```cpp
    g_viewscreen_enabled = false;
```

- [ ] **Step 3: Add the two Python bindings.**

In the bindings block, after the `bridge_pass_set_enabled` def (line 728-729):

```cpp
    m.def("set_viewscreen_model",
          [](unsigned long long h) { if (g_bridge_pass) g_bridge_pass->set_viewscreen_model(h); });
    m.def("set_viewscreen_enabled",
          [](bool on) { g_viewscreen_enabled = on; });
```

- [ ] **Step 4: Restructure `frame()` to render the RTT and feed the bridge pass.**

This builds on Task 2a's `render_space` lambda. The goal flow: compute `bridge_active`/`viewscreen_on`; in bridge view render the space scene into `g_viewscreen_hdr` from `g_camera` (the forward view) and hand its texture to the bridge pass; render the main-HDR space scene ONLY in non-bridge view (it was wasted in bridge view); leave hologram/reticle/bridge/post-process otherwise unchanged.

Concretely, edit `frame()` as follows.

(a) **Move the main-HDR bind/clear to AFTER world propagation, and add the RTT block.** Currently lines 314-321 bind+clear the main HDR target, then lines 331-337 propagate the world + update animations, then Task 2a's `render_space` lambda + `if (!viewer_mode) render_space(...)`. Replace that whole region — from the `g_hdr_target->resize(fw, fh);` at line 314 through the `if (!viewer_mode) { render_space(g_camera, false); }` added in Task 2a — with:

```cpp
    auto lookup = resolve_model;

    const double now = glfwGetTime();
    const float  dt  = static_cast<float>(now - g_prev_frame_time_seconds);
    g_prev_frame_time_seconds = now;

    g_world.propagate();
    // SP2: rebuild each animated instance's bone palette for this frame BEFORE
    // anything consumes it (the space skinned draw and the bridge pass). Shares
    // the `now` wall clock with draw_model / flip controllers.
    renderer::update_animations(g_world, lookup, now);

    const bool bridge_active = !viewer_mode && g_bridge_pass_enabled && g_bridge_pass;
    const bool viewscreen_on = bridge_active && g_viewscreen_enabled;

    // render_space lambda (from Task 2a) — keep its definition here.
    auto render_space = [&](const scenegraph::Camera& cam, bool for_viewscreen) {
        g_backdrop_pass->render(g_backdrops, cam, *g_pipeline);
        g_sun_pass->render(g_suns, cam, *g_pipeline, now);
        g_submitter->submit_opaque_in_pass(
            g_world, cam, *g_pipeline, lookup, g_lighting,
            scenegraph::Pass::Space, g_decal_game_time);
        if (g_shield_pass) g_shield_pass->submit(g_world, cam, *g_pipeline, now, lookup);
        if (!for_viewscreen && g_dust_pass)
            g_dust_pass->render(cam, dt, *g_pipeline, g_suns, g_dust_planets);
        if (!for_viewscreen && g_lens_flare_pass)
            g_lens_flare_pass->render(g_lens_flares, cam, *g_pipeline, fw, fh, now);
        if (g_torpedo_pass) g_torpedo_pass->render(g_torpedoes,    cam, *g_pipeline);
        if (g_phaser_pass)  g_phaser_pass ->render(g_phaser_beams, cam, *g_pipeline);
        if (g_hit_vfx_pass) g_hit_vfx_pass->render(g_hit_vfx, g_world, cam, *g_pipeline);
        if (!for_viewscreen && g_particle_pass)
            g_particle_pass->render(g_particle_emitters, g_world, cam, *g_pipeline);
    };

    // ── Viewscreen render-to-texture (bridge view, screen on) ──────────────
    // The forward space view (g_camera is already forward-from-ship in bridge
    // mode — see host_loop._compute_camera) renders into an offscreen HDR
    // target, which the bridge pass samples onto the viewscreen instance.
    if (viewscreen_on) {
        g_viewscreen_hdr->resize(kViewscreenRttW, kViewscreenRttH);
        g_viewscreen_hdr->bind();   // sets viewport to RTT size
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        scenegraph::Camera vcam = g_camera;
        vcam.aspect = static_cast<float>(kViewscreenRttW)
                    / static_cast<float>(kViewscreenRttH);
        render_space(vcam, /*for_viewscreen=*/true);
        g_bridge_pass->set_viewscreen_texture(g_viewscreen_hdr->color_texture());
    } else if (g_bridge_pass) {
        g_bridge_pass->set_viewscreen_texture(0);   // off -> step-5b blank panel
    }

    // ── Main HDR target ────────────────────────────────────────────────────
    g_hdr_target->resize(fw, fh);
    g_hdr_target->bind();   // sets viewport to fw x fh
    if (viewer_mode) {
        glClearColor(g_hologram_bg.r, g_hologram_bg.g, g_hologram_bg.b, 1.0f);
    } else {
        glClearColor(0.05f, 0.07f, 0.10f, 1.0f);
    }
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    if (fh > 0) g_camera.aspect = static_cast<float>(fw) / static_cast<float>(fh);

    // Space scene goes to the main view only outside bridge view (in bridge
    // view it went to the RTT above, or nowhere when the screen is off — the
    // bridge pass fills the screen either way). This also retires the old
    // "wasted space render in bridge mode".
    if (!viewer_mode && !bridge_active) {
        render_space(g_camera, /*for_viewscreen=*/false);
    }
```

> Note: this removes the original early `g_hdr_target->resize/bind/clear` (lines 314-321) and the original `now/dt/propagate/update_animations` block (lines 327-337) from their old positions — they are reproduced above in the new order. Do not leave the originals behind (that would double-bind / double-propagate). The `if (fh > 0) g_camera.aspect = ...` line that was at 323 is also folded into the new main-HDR block above; remove the old one.

(b) **The bridge-pass block stays, but gate it on the precomputed `bridge_active`.** Replace the condition at line 383 (`if (!viewer_mode && g_bridge_pass_enabled && g_bridge_pass)`) with `if (bridge_active)`. The body (clear + aspect + `g_bridge_pass->render(...)`) is unchanged.

(c) The hologram/pins/reticle block (lines 367-372) and the bloom/resolve/FXAA block (lines 391-417) are unchanged.

- [ ] **Step 5: Build and verify it compiles.**

Run: `cmake --build build -j 2>&1 | tail -20`
Expected: clean build of `dauntless` + `_dauntless_host`. (Runtime: the RTT path only activates once the host calls `set_viewscreen_model` + `set_viewscreen_enabled(True)` — wired in Task 3 — so until then the screen stays the 5b blank panel and exterior view is unchanged.)

- [ ] **Step 6: Commit.**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(host): render the space scene into the viewscreen RTT in bridge view (step 5c)

Add g_viewscreen_hdr (offscreen HdrTarget) + set_viewscreen_model/
set_viewscreen_enabled bindings. In bridge view with the screen on, the
forward space view (existing g_camera) renders into the RTT and the
bridge pass samples it onto the viewscreen instance; the wasted main-HDR
space render in bridge view is retired. Exterior/SPV paths unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Host wiring + on/off + hide player ship (Python, TDD)

**Files:**
- Modify: `engine/renderer.py`
- Modify: `engine/host_loop.py`
- Modify: `tests/unit/test_realize_viewscreen.py`
- Create: `tests/unit/test_viewscreen_rtt_host.py`

- [ ] **Step 1: Write the failing helper tests.**

Create `tests/unit/test_viewscreen_rtt_host.py`:

```python
"""Pure host-side helpers for the viewscreen RTT feed (step 5c). No renderer
or GL — they decide on/off and player-ship visibility from plain inputs."""
from engine.host_loop import _viewscreen_feed_on, _apply_bridge_player_visibility


class _FakeVS:
    def __init__(self, on):
        self._on = on
    def IsOn(self):
        return self._on


class _FakeRenderer:
    def __init__(self):
        self.visibility = []   # (iid, visible)
    def set_visible(self, iid, visible):
        self.visibility.append((iid, visible))


def test_feed_on_true_when_viewscreen_is_on():
    assert _viewscreen_feed_on(_FakeVS(1)) is True


def test_feed_off_when_viewscreen_off_or_missing():
    assert _viewscreen_feed_on(_FakeVS(0)) is False
    assert _viewscreen_feed_on(None) is False


def test_player_hidden_in_bridge_view():
    r = _FakeRenderer()
    _apply_bridge_player_visibility(r, 42, is_bridge=True, spv_open=False)
    assert r.visibility == [(42, False)]


def test_player_visible_in_exterior_view():
    r = _FakeRenderer()
    _apply_bridge_player_visibility(r, 42, is_bridge=False, spv_open=False)
    assert r.visibility == [(42, True)]


def test_no_visibility_change_while_spv_owns_frame():
    r = _FakeRenderer()
    _apply_bridge_player_visibility(r, 42, is_bridge=True, spv_open=True)
    assert r.visibility == []


def test_no_op_without_player_instance():
    r = _FakeRenderer()
    _apply_bridge_player_visibility(r, None, is_bridge=True, spv_open=False)
    assert r.visibility == []
```

- [ ] **Step 2: Run the helper tests to verify they fail.**

Run: `uv run pytest tests/unit/test_viewscreen_rtt_host.py -q`
Expected: FAIL with `ImportError: cannot import name '_viewscreen_feed_on' from 'engine.host_loop'`.

- [ ] **Step 3: Add the two pure helpers to `host_loop.py`.**

In `engine/host_loop.py`, add these module-level functions next to `_realize_viewscreen` (after it):

```python
def _viewscreen_feed_on(viewscreen_obj) -> bool:
    """The viewscreen RTT feed is on iff a realized viewscreen object reports
    IsOn(). Off (or no viewscreen) -> the step-5b blank panel."""
    return bool(viewscreen_obj is not None and viewscreen_obj.IsOn())


def _apply_bridge_player_visibility(r, player_iid, *, is_bridge, spv_open) -> None:
    """Hide the player ship while in bridge view so it doesn't appear on its
    own viewscreen feed (and the centre-mounted forward cam doesn't clip its
    hull). No-op while the Ship Property Viewer owns the frame (it manages
    visibility itself). Idempotent — safe to call every frame."""
    if spv_open or player_iid is None:
        return
    r.set_visible(player_iid, not is_bridge)
```

- [ ] **Step 4: Run the helper tests to verify they pass.**

Run: `uv run pytest tests/unit/test_viewscreen_rtt_host.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Add the renderer wrappers.**

In `engine/renderer.py`, add near the other bridge wrappers (e.g. after `set_bridge_camera`):

```python
def set_viewscreen_model(handle: int) -> None:
    """Register which loaded model handle is the bridge viewscreen surface, so
    the bridge pass binds the RTT feed texture there. No-op until
    set_viewscreen_enabled(True)."""
    _h.set_viewscreen_model(handle)


def set_viewscreen_enabled(on: bool) -> None:
    """Enable/disable the viewscreen render-to-texture feed. When on (and in
    bridge view), the renderer renders the forward space scene into the
    offscreen target and maps it onto the viewscreen instance."""
    _h.set_viewscreen_enabled(on)
```

- [ ] **Step 6: Register the model handle + default the screen on + cache the object in `_realize_viewscreen` (TDD: update its test first).**

In `tests/unit/test_realize_viewscreen.py`:
- Add `set_viewscreen_model` to `_FakeRenderer` (record the handle):
  ```python
      def set_viewscreen_model(self, handle):
          self.viewscreen_model = handle
  ```
  and initialise `self.viewscreen_model = None` in its `__init__`.
- Add `self.viewscreen_obj = None` to `_FakeController.__init__`.
- In `test_realizes_instance_and_harvests_iid`, after the existing assertions, add:
  ```python
      # Step 5c: the realized model handle is registered with the renderer,
      # the screen defaults on, and the object is cached for the per-frame
      # on/off poll.
      assert r.viewscreen_model == r.created[0]
      assert vs.IsOn() == 1
      assert ctl.viewscreen_obj is vs
  ```

Run: `uv run pytest tests/unit/test_realize_viewscreen.py -q`
Expected: FAIL (`_realize_viewscreen` doesn't call `set_viewscreen_model`, doesn't `SetIsOn(1)`, doesn't set `controller.viewscreen_obj`; and the fake controller now has `viewscreen_obj`).

Then in `engine/host_loop.py`, in `_realize_viewscreen`, replace the harvest tail:

```python
    vs.render_instance = iid
    controller.viewscreen_instance = iid
    controller.nif_to_handle[nif_abs] = handle
```

with:

```python
    vs.render_instance = iid
    controller.viewscreen_instance = iid
    controller.nif_to_handle[nif_abs] = handle
    # Step 5c: register the model handle so the bridge pass maps the RTT feed
    # onto this instance, default the screen on (the SDK doesn't call SetIsOn
    # on a fresh load), and cache the object for the per-frame on/off poll.
    r.set_viewscreen_model(handle)
    vs.SetIsOn(1)
    controller.viewscreen_obj = vs
```

Also add the controller slot: in `HostController.__init__` (next to `self.viewscreen_instance` from step 5b, ~line 1773), add:

```python
        self.viewscreen_obj: Optional[Any] = None  # set by _realize_viewscreen
```

Run: `uv run pytest tests/unit/test_realize_viewscreen.py -q`
Expected: PASS.

- [ ] **Step 7: Wire the per-frame on/off + player visibility into `run()`.**

In `engine/host_loop.py`, in the render block, immediately after the line `_spv_was_open = _spv_open` (~line 3098), add:

```python
            # Step 5c: drive the viewscreen RTT feed on/off from the realized
            # viewscreen object, and hide the player ship while in bridge view
            # so it doesn't show on its own screen.
            _vs_obj = getattr(controller, "viewscreen_obj", None)
            r.set_viewscreen_enabled(_viewscreen_feed_on(_vs_obj))
            _player_iid_vs = (session.ship_instances.get(player)
                              if session is not None and player is not None else None)
            _apply_bridge_player_visibility(
                r, _player_iid_vs,
                is_bridge=view_mode.is_bridge, spv_open=_spv_open)
```

> `session`, `player`, `view_mode`, `controller`, and `r` are all in scope in the render block (the SPV code just above uses `session.ship_instances`, `player`, `dev_mode`, and `r`). If `set_viewscreen_enabled` / `set_visible` aren't present on `r` (e.g. a renderer wrapper without them), that's a real wiring gap — do NOT hasattr-guard it away; the wrappers were added in Step 5.

- [ ] **Step 8: Run the host unit tests.**

Run: `uv run pytest tests/unit/test_viewscreen_rtt_host.py tests/unit/test_realize_viewscreen.py -q`
Expected: PASS (all). (The `run()` wiring in Step 7 is integration-level and verified live in Task 4; the logic it calls is unit-tested via the helpers.)

- [ ] **Step 9: Commit.**

```bash
git add engine/renderer.py engine/host_loop.py tests/unit/test_viewscreen_rtt_host.py tests/unit/test_realize_viewscreen.py
git commit -m "feat(bridge): wire viewscreen RTT feed on/off + hide player ship (step 5c)

_realize_viewscreen registers the model handle, defaults the screen on,
and caches the object; per-frame the host drives set_viewscreen_enabled
from IsOn() and hides the player ship in bridge view. Two pure helpers
(_viewscreen_feed_on, _apply_bridge_player_visibility) are unit-tested.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Full rebuild, focused tests, live-verify handoff

**Files:** none (verification only)

- [ ] **Step 1: Full rebuild.**

Run: `cmake -B build -S . && cmake --build build -j 2>&1 | tail -20`
Expected: clean build of `./build/dauntless` and `build/python/_open_stbc_host.cpython-*.so`.

- [ ] **Step 2: Run the touched Python tests together.**

Run: `uv run pytest tests/unit/test_viewscreen_rtt_host.py tests/unit/test_realize_viewscreen.py tests/unit/test_bridge_set_stubs.py tests/integration/test_sdk_bridge_load.py -q`
Expected: PASS (all). **Do NOT run the bare `uv run pytest`.**

- [ ] **Step 3: Officer/bridge regression guard (no step 3-5b regression).**

Run: `uv run pytest tests/integration/test_officer_placement_sdk.py -q`
Expected: PASS.

- [ ] **Step 4: Hand off to Mark for live verification.**

Mark drives all visual verification (no synthetic desktop input / full-screen capture). Ask him to run `./build/dauntless`, enter a mission, switch to bridge view, and confirm:
1. The front viewscreen shows a live forward view of space (stars, sun, any ships/weapons fire ahead), exposed correctly (not washed-out or black).
2. His own ship does not appear on the screen.
3. Switching to exterior view is unchanged; switching back to bridge restores the feed.
4. No crash; bridge mesh + officers unchanged.

Notes for Mark: the feed is fixed at 640×360 (tune `kViewscreenRttW/H` if it looks soft). If the image is distorted/cropped, that's a "room screen" UV finding to record (tune via the RTT aspect, don't invent UVs). If a mission turns the viewscreen off (`SetIsOn(0)`), the screen should blank to the 5b panel.

---

## Self-Review

**Spec coverage:**
- Offscreen HDR target + frame() redirect using existing `g_camera` → Task 2b. ✓
- `render_space(camera, for_viewscreen)` helper, skipping dust/lens-flares/particles → Task 2a + 2b. ✓
- HDR-direct feed + forced emissive (no double tonemap) → Task 1 (Step 3) + Task 2b. ✓
- Per-instance texture override matched by model handle → Task 1. ✓
- Player ship hidden in bridge view → Task 3 (`_apply_bridge_player_visibility`). ✓
- On/off via `IsOn()`, default-on at realize → Task 3 (`_viewscreen_feed_on`, `SetIsOn(1)`). ✓
- Bindings `set_viewscreen_model` / `set_viewscreen_enabled` + renderer wrappers → Task 2b + Task 3. ✓
- Full rebuild required + live verify → Task 4. ✓
- Tests: helper unit tests + extended realize test → Task 3; C++ build-verified per task. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; every `Run:` has explicit path + expected result; C++ tasks are honestly build-verified (no fabricated GL test). ✓

**Type consistency:** `set_viewscreen_model(unsigned long long)` matches `BridgePass::ModelLookup`'s `unsigned long long` and `inst.model_handle`; `set_viewscreen_texture(unsigned int)`/`GLuint base_override` consistent; `viewscreen_model_handle_`/`viewscreen_tex_`/`g_viewscreen_hdr`/`g_viewscreen_enabled`/`kViewscreenRttW/H` names match across tasks; Python `set_viewscreen_model`/`set_viewscreen_enabled`/`_viewscreen_feed_on`/`_apply_bridge_player_visibility`/`controller.viewscreen_obj` consistent between renderer.py, host_loop.py, and the tests. ✓
