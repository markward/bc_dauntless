# Reticle Chrome, Fore/Aft Bars & Text — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tint the GL target reticle to the UI chrome palette, add fore/aft alignment side bars with green arrows, and render the target name + range/speed as a CEF text overlay aligned to the box.

**Architecture:** Hybrid render path. The existing `TargetReticlePass` (native GL billboards) gains a per-draw `u_tint` colour and a vec2 `u_size_world` (so bars can be tall/thin), plus two new billboard elements (yellow side bars from `tilevertline.tga`, green arrows from `TargetArrow.tga`) driven by a `bar_alignment` float. Text lives in a CEF overlay: a pure-Python module projects the box top/bottom world points to screen with the same gameplay camera the GL pass uses, and pushes `setReticleText(...)` to the browser each frame.

**Tech Stack:** C++17 + OpenGL 3.3 (GLM), pybind11 host bindings, CMake (embedded-shader headers), CEF (HTML/CSS/JS overlay), Python 3 + pytest.

**Spec:** `docs/superpowers/specs/2026-06-09-reticle-chrome-bars-text-design.md`

---

## File Structure

**Create:**
- `engine/ui/reticle_text.py` — `build_reticle_text(player, camera, viewport)` + `_ReticleCam` adapter.
- `native/assets/ui-cef/js/reticle_text.js` — `setReticleText(state)` DOM positioning.
- `native/assets/ui-cef/css/reticle_text.css` — name/distance label styling.
- `tests/unit/test_reticle_text.py` — pure-Python tests for the text module.

**Modify:**
- `native/src/renderer/shaders/target_reticle.frag` — `u_tint`.
- `native/src/renderer/shaders/target_reticle.vert` — `u_size_world` float → vec2.
- `native/src/renderer/target_reticle_pass.cc` — tints, vec2 size, bars + arrows, 2 textures.
- `native/src/renderer/include/renderer/target_reticle_pass.h` — `TargetReticle` gains `has_bars`, `bar_alignment`; pass gains bar/arrow texture members.
- `native/src/host/host_bindings.cc` — `set_target_reticle` gains `bar_alignment`; new `set_reticle_text` / `clear_reticle_text` (thin wrappers over `cef_execute_javascript`).
- `engine/renderer.py` — `set_target_reticle` passes `bar_alignment`; add `set_reticle_text` / `clear_reticle_text`.
- `engine/ui/target_reticle.py` — `TargetReticlePayload.bar_alignment`; compute the metric.
- `engine/host_loop.py` — feed `set_reticle_text` (gameplay) / `clear_reticle_text` (SPV); pass `bar_alignment`.
- `native/assets/ui-cef/index.html` — link the css, include the js, add the two label `<div>`s.
- `tests/unit/test_target_reticle.py` — `bar_alignment` tests.

---

## Task 1: GL tint + vec2 billboard size

No unit test (shader/GL); verified by build + Task 6 visual. Makes the box orange and crosshair yellow.

**Files:**
- Modify: `native/src/renderer/shaders/target_reticle.frag`, `target_reticle.vert`
- Modify: `native/src/renderer/target_reticle_pass.cc`

- [ ] **Step 1: Add the tint uniform to the fragment shader**

Replace the body of `native/src/renderer/shaders/target_reticle.frag`:
```glsl
#version 330 core
in vec2 v_uv;
uniform sampler2D u_tex;   // reticle art (white/grey, tinted by u_tint)
uniform vec4 u_tint;       // multiply colour (rgb) + alpha scale
out vec4 frag;
void main() {
    vec4 t = texture(u_tex, v_uv);
    if (t.a < 0.01) discard;
    frag = t * u_tint;
}
```

- [ ] **Step 2: Generalise the vertex shader size to vec2**

In `native/src/renderer/shaders/target_reticle.vert`, change the `u_size_world` uniform from `float` to `vec2` and use per-axis extents. The full file becomes:
```glsl
#version 330 core
layout(location = 0) in vec2 a_corner;   // unit quad corner in [-0.5, 0.5]
uniform mat4  u_view_proj;
uniform vec3  u_center_world;
uniform vec3  u_camera_right;
uniform vec3  u_camera_up;
uniform vec2  u_size_world;                // world full-size (x=width, y=height)
uniform vec2  u_uv_flip;                   // (+1/-1) per axis to mirror art
out vec2 v_uv;
void main() {
    vec3 offset = u_camera_right * (a_corner.x * u_size_world.x)
                + u_camera_up    * (a_corner.y * u_size_world.y);
    // Negate the vertical component: decoded texture is top-left origin.
    v_uv = vec2(0.5) + vec2(a_corner.x, -a_corner.y) * u_uv_flip;
    gl_Position = u_view_proj * vec4(u_center_world + offset, 1.0);
}
```

- [ ] **Step 3: Update the pass to set tint + vec2 size**

In `native/src/renderer/target_reticle_pass.cc`, in the `namespace {` block add palette constants after the existing `kCrosshairSizePx`:
```cpp
// Chrome palette (rgb 0..1, a = alpha scale). From the UI config-panel gradient.
constexpr glm::vec4 kBoxTint      {0.847f, 0.518f, 0.314f, 1.0f};  // orange #d88450
constexpr glm::vec4 kCrosshairTint{1.000f, 0.860f, 0.000f, 1.0f};  // yellow
```

Replace the corner-box draw loop (the `for (const auto& c : kCornerDefs)` block) so it sets the tint and a vec2 size:
```cpp
    shader.set_vec4("u_tint", kBoxTint);
    for (const auto& c : kCornerDefs) {
        const glm::vec3 centre = reticle.ship_center
                               + cam_right * (c[0] * r)
                               + cam_up    * (c[1] * r);
        shader.set_vec3("u_center_world", centre);
        shader.set_vec2("u_size_world",   glm::vec2(corner_size, corner_size));
        shader.set_vec2("u_uv_flip",      glm::vec2(c[2], c[3]));
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }
```

Replace the crosshair draw block:
```cpp
    if (reticle.has_subtarget) {
        glBindTexture(GL_TEXTURE_2D, crosshair_tex_ ? crosshair_tex_->id() : 0);
        const float cs = world_for_px(reticle.subtarget_pos, kCrosshairSizePx);
        shader.set_vec4("u_tint",        kCrosshairTint);
        shader.set_vec3("u_center_world", reticle.subtarget_pos);
        shader.set_vec2("u_size_world",   glm::vec2(cs, cs));
        shader.set_vec2("u_uv_flip",      glm::vec2(1.0f, 1.0f));
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }
```

(`glm` is already included. `set_vec4` exists on `Shader`.)

- [ ] **Step 4: Reconfigure + build (shaders changed)**

Run from the project root:
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: `BUILD_OK` (builds `build/dauntless`). The shader change requires the `cmake -B build -S .` reconfigure to regenerate embedded headers.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/target_reticle.frag \
        native/src/renderer/shaders/target_reticle.vert \
        native/src/renderer/target_reticle_pass.cc
git commit -m "feat(renderer): tint reticle (orange box, yellow crosshair) + vec2 size

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Fore/aft `bar_alignment` metric (Python)

**Files:**
- Modify: `engine/ui/target_reticle.py`
- Test: `tests/unit/test_target_reticle.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_target_reticle.py`:
```python
def test_bar_alignment_fore_abeam_aft():
    import math
    from engine.appc.math import TGPoint3, TGMatrix3
    from engine.appc.subsystems import ShipSubsystem  # noqa: F401

    R = TGMatrix3(); R.MakeIdentity()   # player forward = +Y (GetCol(1))
    # Target dead ahead (+Y) → alignment ~ +1.
    p = _ship(TGPoint3(0, 0, 0), R)
    tgt = _ship(TGPoint3(0, 100, 0), _identity()); p._t = tgt
    assert build_target_reticle(p).bar_alignment > 0.99
    # Target abeam (+X) → alignment ~ 0.
    tgt2 = _ship(TGPoint3(100, 0, 0), _identity()); p._t = tgt2
    assert abs(build_target_reticle(p).bar_alignment) < 0.01
    # Target dead astern (−Y) → alignment ~ −1.
    tgt3 = _ship(TGPoint3(0, -100, 0), _identity()); p._t = tgt3
    assert build_target_reticle(p).bar_alignment < -0.99
```
(`_ship` and `_identity` already exist at the top of this test file from iteration 1.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_target_reticle.py::test_bar_alignment_fore_abeam_aft -v`
Expected: FAIL — `AttributeError: 'TargetReticlePayload' object has no attribute 'bar_alignment'`.

- [ ] **Step 3: Implement the field + metric**

In `engine/ui/target_reticle.py`, add the field to the dataclass (after `subtarget_pos`):
```python
    bar_alignment: float = 0.0   # [-1,+1]: +1 target fore, -1 aft, 0 abeam
```

In `build_target_reticle`, after `centre = target.GetWorldLocation()` and before the `return`, compute the metric and pass it. Replace the existing `return TargetReticlePayload(...)` tail with:
```python
    bar_alignment = 0.0
    rot = player.GetWorldRotation() if hasattr(player, "GetWorldRotation") else None
    pc = player.GetWorldLocation() if hasattr(player, "GetWorldLocation") else None
    if rot is not None and pc is not None:
        fwd = rot.GetCol(1)                       # ship forward in world space
        dx, dy, dz = centre.x - pc.x, centre.y - pc.y, centre.z - pc.z
        dlen = (dx * dx + dy * dy + dz * dz) ** 0.5
        if dlen > 1e-6:
            dot = (fwd.x * dx + fwd.y * dy + fwd.z * dz) / dlen
            bar_alignment = max(-1.0, min(1.0, dot))
    return TargetReticlePayload(
        visible=True,
        ship_center=(centre.x, centre.y, centre.z),
        ship_radius=float(radius),
        subtarget_pos=subtarget,
        bar_alignment=bar_alignment,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_target_reticle.py -v`
Expected: PASS (all, incl. the new test).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/target_reticle.py tests/unit/test_target_reticle.py
git commit -m "feat(targeting): compute fore/aft bar_alignment in reticle payload

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Bars + arrows in the GL pass + binding

No unit test (GL); verified by build + Task 6. Draws the yellow side bars and green fore/aft arrows.

**Files:**
- Modify: `native/src/renderer/include/renderer/target_reticle_pass.h`
- Modify: `native/src/renderer/target_reticle_pass.cc`
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/renderer.py`

- [ ] **Step 1: Extend the struct + texture members**

In `native/src/renderer/include/renderer/target_reticle_pass.h`, add to `struct TargetReticle` after `subtarget_pos`:
```cpp
    bool      has_bars      = false;
    float     bar_alignment = 0.0f;   // [-1,+1], +1 fore, -1 aft
```
Add to the `TargetReticlePass` private members after `crosshair_tex_`:
```cpp
    std::unique_ptr<assets::Texture> bar_tex_;     // game/data/Icons/tilevertline.tga
    std::unique_ptr<assets::Texture> arrow_tex_;   // game/data/Icons/TargetArrow.tga
```

- [ ] **Step 2: Load the new textures + add palette/size constants**

In `target_reticle_pass.cc`, add file path constants in the `namespace {` block after `kCrosshairFile`:
```cpp
constexpr const char* kBarFile   = "game/data/Icons/tilevertline.tga";
constexpr const char* kArrowFile = "game/data/Icons/TargetArrow.tga";
```
Add tint/size constants after `kCrosshairTint`:
```cpp
constexpr glm::vec4 kBarTint  {1.000f, 0.860f, 0.000f, 1.0f};  // yellow
constexpr glm::vec4 kArrowTint{0.300f, 0.850f, 0.300f, 1.0f};  // green
constexpr float kBarWidthPx  = 4.0f;    // on-screen bar line width
constexpr float kArrowSizePx = 22.0f;   // on-screen arrow size
```
In `ensure_textures()`, after the existing `crosshair_tex_ = load_tga(kCrosshairFile);`:
```cpp
    bar_tex_   = load_tga(kBarFile);
    arrow_tex_ = load_tga(kArrowFile);
```

- [ ] **Step 3: Draw the bars + arrows**

In `target_reticle_pass.cc`, insert this block after the crosshair draw block (before `glBindVertexArray(0);`):
```cpp
    // --- Fore/aft side bars (tilevertline) + arrows (TargetArrow) ---
    if (reticle.has_bars) {
        const float bar_w = world_for_px(reticle.ship_center, kBarWidthPx);
        const float v = (reticle.bar_alignment < -1.0f) ? -1.0f
                      : (reticle.bar_alignment >  1.0f) ?  1.0f
                      : reticle.bar_alignment;            // arrow height in [-1,1]
        for (float side : {-1.0f, 1.0f}) {               // left, right edge
            const glm::vec3 bar_centre = reticle.ship_center + cam_right * (side * r);
            // Bar: thin, full box height.
            glBindTexture(GL_TEXTURE_2D, bar_tex_ ? bar_tex_->id() : 0);
            shader.set_vec4("u_tint",        kBarTint);
            shader.set_vec3("u_center_world", bar_centre);
            shader.set_vec2("u_size_world",   glm::vec2(bar_w, 2.0f * r));
            shader.set_vec2("u_uv_flip",      glm::vec2(1.0f, 1.0f));
            glDrawArrays(GL_TRIANGLES, 0, 6);
            // Arrow: constant px, slid to v along the bar height.
            const glm::vec3 arrow_centre = bar_centre + cam_up * (v * r);
            const float asz = world_for_px(arrow_centre, kArrowSizePx);
            glBindTexture(GL_TEXTURE_2D, arrow_tex_ ? arrow_tex_->id() : 0);
            shader.set_vec4("u_tint",        kArrowTint);
            shader.set_vec3("u_center_world", arrow_centre);
            shader.set_vec2("u_size_world",   glm::vec2(asz, asz));
            shader.set_vec2("u_uv_flip",      glm::vec2(1.0f, 1.0f));
            glDrawArrays(GL_TRIANGLES, 0, 6);
        }
    }
```

- [ ] **Step 4: Extend the host binding**

In `native/src/host/host_bindings.cc`, replace the `set_target_reticle` binding lambda + arg list so it accepts `bar_alignment` and sets `has_bars`:
```cpp
    m.def("set_target_reticle",
          [](bool visible,
             std::array<float, 3> ship_center, float ship_radius,
             py::object subtarget_pos, float bar_alignment) {
              g_target_reticle.visible     = visible;
              g_target_reticle.ship_center = {ship_center[0], ship_center[1], ship_center[2]};
              g_target_reticle.ship_radius = ship_radius;
              g_target_reticle.has_bars      = visible;
              g_target_reticle.bar_alignment = bar_alignment;
              if (subtarget_pos.is_none()) {
                  g_target_reticle.has_subtarget = false;
              } else {
                  auto s = subtarget_pos.cast<std::array<float, 3>>();
                  g_target_reticle.has_subtarget = true;
                  g_target_reticle.subtarget_pos = {s[0], s[1], s[2]};
              }
          },
          py::arg("visible"), py::arg("ship_center"), py::arg("ship_radius"),
          py::arg("subtarget_pos"), py::arg("bar_alignment"),
          "Set the target reticle: full-ship corner box, optional subtarget "
          "crosshair, and fore/aft side bars whose arrows sit at bar_alignment "
          "([-1,+1], +1 fore). Applied each frame().");
```

- [ ] **Step 5: Extend the Python wrapper**

In `engine/renderer.py`, update `set_target_reticle` to pass `bar_alignment`:
```python
def set_target_reticle(payload) -> None:
    """Feed the target reticle pass from a target_reticle.TargetReticlePayload.

    No-ops silently if the host binding is unavailable (headless tests).
    """
    fn = getattr(_h, "set_target_reticle", None)
    if fn is None:
        return
    fn(payload.visible, payload.ship_center, payload.ship_radius,
       payload.subtarget_pos, payload.bar_alignment)
```

- [ ] **Step 6: Reconfigure + build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: `BUILD_OK`. (No shader change here, but the reconfigure is harmless; a plain `cmake --build build -j` also works.)

- [ ] **Step 7: Verify the binding signature loads**

Run:
```bash
python3 -c "import sys; sys.path.insert(0,'build/python'); import _dauntless_host as m; import inspect; m.set_target_reticle(True,(0,0,0),1.0,None,0.5); print('ok')"
```
Expected: prints `ok` (the 5-arg binding accepts the call).

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/target_reticle_pass.h \
        native/src/renderer/target_reticle_pass.cc \
        native/src/host/host_bindings.cc engine/renderer.py
git commit -m "feat(renderer): fore/aft side bars + green arrows in reticle pass

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `reticle_text.py` (name + range/speed + projection)

**Files:**
- Create: `engine/ui/reticle_text.py`
- Test: `tests/unit/test_reticle_text.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_reticle_text.py`:
```python
import math
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.subsystems import ShipSubsystem
from engine.ui.reticle_text import build_reticle_text, _ReticleCam


def _identity():
    R = TGMatrix3(); R.MakeIdentity(); return R


def _ship(loc, vel=(0.0, 0.0, 0.0), name="Target", radius=5.0):
    class _Ship:
        def __init__(self):
            self._t = None; self._sub = None
        def GetWorldLocation(self): return loc
        def GetWorldRotation(self): return _identity()
        def GetRadius(self): return radius
        def GetVelocity(self, space=0): return TGPoint3(*vel)
        def GetName(self): return name
        def GetTarget(self): return self._t
        def GetTargetSubsystem(self): return self._sub
    return _Ship()


def _cam_facing_target():
    # Eye at origin looking down +Y; target ahead at +Y is on-screen.
    return _ReticleCam(eye=(0.0, -50.0, 0.0), target=(0.0, 0.0, 0.0),
                       up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(60.0),
                       near=1.0, far=5000.0)


def test_text_hidden_without_target():
    p = _ship(TGPoint3(0, 0, 0))
    out = build_reticle_text(p, _cam_facing_target(), (1280, 720))
    assert out["visible"] is False


def test_text_name_and_line2_from_ship():
    # Target 200 GU ahead, moving 1.0 GU/s. 200*0.175 = 35.00 km; 1*630 = 630 kph.
    tgt = _ship(TGPoint3(0, 0, 0), vel=(1.0, 0.0, 0.0), name="Warbird")
    p = _ship(TGPoint3(0, -200, 0)); p._t = tgt
    out = build_reticle_text(p, _cam_facing_target(), (1280, 720))
    assert out["visible"] is True
    assert out["name"] == "Warbird"
    assert out["line2"] == "35.00 km / 630 kph"
    # Positions are within the viewport.
    assert 0 <= out["name_xy"][0] <= 1280 and 0 <= out["name_xy"][1] <= 720


def test_text_name_is_subsystem_when_locked():
    tgt = _ship(TGPoint3(0, 0, 0), name="Warbird")
    sub = ShipSubsystem("Port Nacelle"); sub.SetParentShip(tgt)
    p = _ship(TGPoint3(0, -200, 0)); p._t = tgt; p._sub = sub
    out = build_reticle_text(p, _cam_facing_target(), (1280, 720))
    assert out["name"] == "Port Nacelle"


def test_text_hidden_when_target_behind_camera():
    # Camera looks down +Y but target is behind the eye (−Y) → off-clip.
    tgt = _ship(TGPoint3(0, -500, 0), name="Warbird")
    p = _ship(TGPoint3(0, -400, 0)); p._t = tgt
    cam = _ReticleCam(eye=(0.0, 0.0, 0.0), target=(0.0, 100.0, 0.0),
                      up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(60.0),
                      near=1.0, far=5000.0)
    out = build_reticle_text(p, cam, (1280, 720))
    assert out["visible"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_reticle_text.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.ui.reticle_text`.

- [ ] **Step 3: Implement the module**

Create `engine/ui/reticle_text.py`. Note `project()` calls `cam.eye()` and
`cam.up()` as **methods** but reads `cam.target` / `cam.fov_y_rad` / `cam.near`
/ `cam.far` as **attributes**, so `_ReticleCam` is a plain class (not a
dataclass — a dataclass field named `eye` would collide with the `eye()`
method):
```python
"""Target reticle text overlay (name + range/speed) — pure Python.

Projects the box top/bottom world points to screen with the gameplay camera
(the same one the GL reticle pass uses) so the labels align with the box.
Driven imperatively from host_loop; rendered by reticle_text.js in CEF.
See docs/superpowers/specs/2026-06-09-reticle-chrome-bars-text-design.md
"""
from __future__ import annotations

from engine.units import GU_TO_KM, GUPS_TO_KPH
from engine.ui.ship_property_viewer import project
from engine.ui.target_reticle import _valid_target, _valid_subsystem


class _ReticleCam:
    """Adapter exposing the interface ship_property_viewer.project expects
    (eye()/up() methods; target/fov_y_rad/near/far attributes), built from the
    gameplay camera params host_loop already computes."""
    def __init__(self, eye, target, up, fov_y_rad, near, far):
        self._eye = eye
        self.target = target
        self._up = up
        self.fov_y_rad = fov_y_rad
        self.near = near
        self.far = far

    def eye(self):
        return self._eye

    def up(self):
        return self._up


def build_reticle_text(player, camera, viewport) -> dict:
    """Return {visible, name, line2, name_xy, line2_xy}.

    name = locked subsystem name if any, else target ship name.
    line2 = "<range> km / <speed> kph". Hidden when no target or the box
    top/bottom project behind the camera / off-clip.
    """
    target = _valid_target(player)
    if target is None:
        return {"visible": False}

    centre = target.GetWorldLocation()
    pc = player.GetWorldLocation()
    dx, dy, dz = centre.x - pc.x, centre.y - pc.y, centre.z - pc.z
    dist_gu = (dx * dx + dy * dy + dz * dz) ** 0.5
    vel = target.GetVelocity() if hasattr(target, "GetVelocity") else None
    speed_gu = (vel.x * vel.x + vel.y * vel.y + vel.z * vel.z) ** 0.5 if vel else 0.0

    sub = _valid_subsystem(player)
    name = sub.GetName() if sub is not None else target.GetName()
    line2 = "%.2f km / %.0f kph" % (dist_gu * GU_TO_KM, speed_gu * GUPS_TO_KPH)

    radius = target.GetRadius() if hasattr(target, "GetRadius") else 0.0
    up = camera.up()
    top    = (centre.x + up[0] * radius, centre.y + up[1] * radius, centre.z + up[2] * radius)
    bottom = (centre.x - up[0] * radius, centre.y - up[1] * radius, centre.z - up[2] * radius)
    tsx, tsy, _td, tvis = project(top, camera, viewport)
    bsx, bsy, _bd, bvis = project(bottom, camera, viewport)
    if not (tvis and bvis):
        return {"visible": False}

    return {
        "visible": True,
        "name": name,
        "line2": line2,
        "name_xy": (tsx, tsy),
        "line2_xy": (bsx, bsy),
    }
```
The tests construct the adapter with keyword args
`_ReticleCam(eye=..., target=..., up=..., fov_y_rad=..., near=..., far=...)`,
which the `__init__` above accepts.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_reticle_text.py -v`
Expected: PASS (all 4). If `test_text_name_and_line2_from_ship` fails on the
exact string, print the actual `line2` and confirm `GU_TO_KM == 0.175` /
`GUPS_TO_KPH == 630` (engine/units.py) — the expected values are computed from
those.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/reticle_text.py tests/unit/test_reticle_text.py
git commit -m "feat(targeting): reticle_text module (name + range/speed + projection)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: CEF text overlay + host wiring

No unit test (CEF/JS + host_loop integration); verified by build + Task 6 visual.

**Files:**
- Create: `native/assets/ui-cef/js/reticle_text.js`, `native/assets/ui-cef/css/reticle_text.css`
- Modify: `native/assets/ui-cef/index.html`
- Modify: `native/src/host/host_bindings.cc`, `engine/renderer.py`
- Modify: `engine/host_loop.py`

- [ ] **Step 1: Write the JS overlay**

Create `native/assets/ui-cef/js/reticle_text.js`:
```javascript
// native/assets/ui-cef/js/reticle_text.js
// Target reticle text overlay. Driven by Python via cef_execute_javascript:
//   setReticleText({visible, name, line2, name_xy:[x,y], line2_xy:[x,y]});
// Coordinates are CEF view-space pixels (top-left origin).
function setReticleText(state) {
    var nameEl = document.getElementById('reticle-name');
    var distEl = document.getElementById('reticle-dist');
    if (!nameEl || !distEl) return;
    if (!state || !state.visible) {
        nameEl.style.display = 'none';
        distEl.style.display = 'none';
        return;
    }
    nameEl.style.display = 'block';
    distEl.style.display = 'block';
    nameEl.textContent = String(state.name == null ? '' : state.name);
    distEl.textContent = String(state.line2 == null ? '' : state.line2);
    nameEl.style.left = state.name_xy[0].toFixed(1) + 'px';
    nameEl.style.top  = state.name_xy[1].toFixed(1) + 'px';
    distEl.style.left = state.line2_xy[0].toFixed(1) + 'px';
    distEl.style.top  = state.line2_xy[1].toFixed(1) + 'px';
}
```

- [ ] **Step 2: Write the CSS**

Create `native/assets/ui-cef/css/reticle_text.css`:
```css
/* Target reticle text labels — non-interactive, anchored at projected points.
   #reticle-name sits above the box top; #reticle-dist below the box bottom. */
#reticle-name, #reticle-dist {
    position: absolute;
    display: none;
    transform: translate(-50%, -50%);
    pointer-events: none;
    white-space: nowrap;
    font-family: "Helvetica Neue", Arial, sans-serif;
    text-shadow: 0 0 3px #000, 0 0 3px #000;
    letter-spacing: 0.04em;
}
#reticle-name {
    color: #d88450;             /* chrome orange */
    font-size: 15px;
    font-style: italic;
    transform: translate(-50%, -160%);   /* lift above the box top corner */
}
#reticle-dist {
    color: #ffd;                /* pale */
    font-size: 13px;
    transform: translate(-50%, 60%);      /* drop below the box bottom corner */
}
```

- [ ] **Step 3: Wire the markup into index.html**

In `native/assets/ui-cef/index.html`, add the stylesheet link after the
`ship_property_viewer.css` link (line 13):
```html
    <link rel="stylesheet" href="css/reticle_text.css">
```
Add the two label divs just inside `<body>` (near the top, before the panels — pick a spot adjacent to the sensors panel container). Insert:
```html
    <div id="reticle-name"></div>
    <div id="reticle-dist"></div>
```
Add the script include alongside the others (after `js/sensors.js`, line 258):
```html
    <script src="js/reticle_text.js"></script>
```

- [ ] **Step 4: Add the host binding wrappers**

In `native/src/host/host_bindings.cc`, after the `clear_target_reticle` binding (it ends at the line with `"Hide the target reticle. Takes effect next frame()."`), add:
```cpp
    m.def("set_reticle_text",
          [](const std::string& json) {
              dauntless::ui_cef::execute_javascript("setReticleText(" + json + ");");
          },
          py::arg("json"),
          "Push a setReticleText(json) call to the CEF overlay.");
```
Confirm the surrounding file already calls `dauntless::ui_cef::execute_javascript`
(the `cef_execute_javascript` binding at host_bindings.cc:1324 does). If the
no-CEF stub build path (host_bindings.cc:1399 region) defines a second
`cef_execute_javascript`, add a matching no-op `set_reticle_text` there too so
both build configs link.

- [ ] **Step 5: Add the Python wrappers**

In `engine/renderer.py`, after `clear_target_reticle` (around line 351), add:
```python
def set_reticle_text(payload) -> None:
    """Push the reticle text overlay state (a build_reticle_text dict).

    No-ops silently when the host/CEF binding is unavailable (headless tests).
    """
    import json as _json
    fn = getattr(_h, "set_reticle_text", None)
    if fn is None:
        return
    fn(_json.dumps(payload))


def clear_reticle_text() -> None:
    """Hide the reticle text overlay. Takes effect next CEF pump."""
    fn = getattr(_h, "set_reticle_text", None)
    if fn is not None:
        fn('{"visible": false}')
```

- [ ] **Step 6: Feed it from host_loop**

In `engine/host_loop.py`, add the import next to the existing reticle import
(line 22, `from engine.ui.target_reticle import build_target_reticle`):
```python
from engine.ui.reticle_text import build_reticle_text, _ReticleCam
```
In the gameplay `else:` branch, replace the reticle feed block (currently
`if player is not None: r.set_target_reticle(build_target_reticle(player)) else: r.clear_target_reticle()` at host_loop.py:2702-2705) with:
```python
                if player is not None:
                    r.set_target_reticle(build_target_reticle(player))
                    _rcam = _ReticleCam(eye=eye, target=target, up=up_vec,
                                        fov_y_rad=director.fov_y_rad,
                                        near=1.0, far=5000.0)
                    r.set_reticle_text(build_reticle_text(
                        player, _rcam, (_CEF_VIEW_W, _CEF_VIEW_H)))
                else:
                    r.clear_target_reticle()
                    r.clear_reticle_text()
```
In the SPV-open branch, after the existing `r.clear_target_reticle()` (host_loop.py:2688), add:
```python
                r.clear_reticle_text()
```
(`_CEF_VIEW_W` / `_CEF_VIEW_H` are module-locals set at host_loop.py:1924; `eye`,
`target`, `up_vec` are the camera tuple computed just above the `set_camera`
call; `director.fov_y_rad` is already used at the adjacent `set_camera`.)

- [ ] **Step 7: Build + import check**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: `BUILD_OK`.
Then: `python3 -c "import sys; sys.path.insert(0,'build/python'); import engine.host_loop; print('ok')"`
Expected: prints `ok` (no import/circular error; CEF assets are loaded at runtime, not import).

- [ ] **Step 8: Commit**

```bash
git add native/assets/ui-cef/js/reticle_text.js \
        native/assets/ui-cef/css/reticle_text.css \
        native/assets/ui-cef/index.html \
        native/src/host/host_bindings.cc engine/renderer.py engine/host_loop.py
git commit -m "feat(hud): CEF reticle text overlay (name + range/speed) + host wiring

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Build, focused tests, manual verification

**Files:** none (verification only)

- [ ] **Step 1: Reconfigure + full build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: `BUILD_OK`.

- [ ] **Step 2: Focused Python test sweep (NEVER the full suite — it OOMs)**

Run:
```bash
uv run pytest tests/unit/test_target_reticle.py \
              tests/unit/test_reticle_text.py \
              tests/unit/test_subsystems.py \
              tests/cameras/ -q
```
Expected: all PASS.

- [ ] **Step 3: Manual verification in the developer build**

Run: `./build/dauntless --developer`. Lock a target (and a subsystem) and confirm:
1. Corner box renders **orange**; crosshair **yellow**.
2. Two **yellow vertical bars** flank the box; each has a **green arrow**.
3. Fly the player past the target: the arrows sweep **top (fore) → centre (abeam) → bottom (aft)**.
4. The **name** (subsystem when locked, else ship) sits above the box; the **range/speed** line sits below it, both tracking the box as the camera moves.
5. No target → reticle + text both hidden. Open the Ship Property Viewer → reticle + text hidden; closing restores them.

- [ ] **Step 4: Final commit (only if a tuning tweak was needed)**

If Step 3 needed constant tweaks (palette, `kBarWidthPx`, `kArrowSizePx`, CSS offsets):
```bash
git add -A
git commit -m "tune(hud): reticle palette / bar / text offsets

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review notes

- **Spec coverage:** §Component 1 (tint+vec2)→Task 1; §Component 2 (bars/arrows)→Task 3; §Component 3 (metric)→Task 2; §Component 4 (text module)→Task 4; §Component 4 (CEF overlay) + §Component 5 (host wiring)→Task 5; §Testing→Tasks 2,4,6; palette/edge-cases covered across Tasks 1,3,4. All covered.
- **Type/name consistency:** `bar_alignment` (payload field, struct field, binding arg) and `has_bars` (struct, set from `visible`) match across Tasks 2/3. `build_reticle_text` returns `{visible, name, line2, name_xy, line2_xy}` consumed identically by `reticle_text.js` (Task 5) and asserted in tests (Task 4). `_ReticleCam(eye, target, up, fov_y_rad, near, far)` constructed identically in Task 4 tests and Task 5 host_loop. `set_reticle_text(payload_dict)` wrapper json-encodes; binding takes the json string.
- **Projection caveat (called out in spec):** CEF view (1280×720) and framebuffer share 16:9, so `project()`'s aspect matches the GL camera; text aligns with the box.
- **Placeholder scan:** the `_ReticleCam` dataclass-vs-class clash is explicitly resolved inline in Task 4 Step 3 (use the `__init__` class form). No TBDs.
