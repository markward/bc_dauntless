# SPV Transform Gizmo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Blender-style 3-axis position gizmo to the Ship Property Viewer so a subsystem or light volume can be dragged along a ship-body axis to edit its XYZ location, staged and saved to `hardpoint_overrides.py`; Rotate/Scale buttons are inert stubs.

**Architecture:** Pure-Python geometry/picking/drag in `engine/ui/ship_property_viewer.py` (mirrors the existing `project`/`pick_pin`); tool + pending-position state and the drag hook in `engine/ui/ship_property_viewer_panel.py` (reuses the radius/light `pending→saved→baked` seams and the existing `handle_input` press/drag/release edges); a new native `GizmoPass` + `set_transform_gizmo` binding for the arrows; a CEF tool-button group above `#spv-tools`; host_loop pushes the gizmo each frame.

**Tech Stack:** Python 3 (engine), C++/OpenGL 3.3 (`native/`), pybind11 host bindings, CEF (HTML/CSS/JS overlay), pytest + ctest.

## Global Constraints

- **Developer-only, production byte-identical.** All new render/state paths are reachable only under `--developer` with the SPV open. An empty/cleared gizmo draws nothing. Never construct SPV state without dev mode.
- **Mouse-only.** No keyboard→CEF forwarding exists. All interaction is viewport mouse (drag) or CEF button clicks.
- **Body-frame axes.** Gizmo axes are the ship's body axes `R.GetCol(0/1/2)` (X starboard/red, Y forward/green, Z up/blue). Dragging axis `k` changes component `k` of the stored body-frame position 1:1.
- **Machine-owned file.** Positions persist to `engine/appc/hardpoint_overrides.py` only through `resolve_override_target(ship).write(leaf, edits)` — never hand-edited. Subsystem → `(name, "SetPosition", (x,y,z))`; light → the region-0 spec's `position` via the existing `__region__` route.
- **Staged + Save/confirm.** Drags stage pending edits; nothing is written until the existing Save → amend-confirm flow runs. Pending position edits count toward `pending_count` and the amend-confirm tally.
- **Shared checkout.** Commit with explicit pathspecs only. Never `git add -A`/`checkout`/`restore`/`stash`/`reset --hard`/`clean`.
- **Test gate.** `scripts/check_tests.sh` (build + pytest + ctest) must stay green against `tests/known_failures.txt` (1 baselined PowerDisplay ZeroDivisionError) between tasks.

## File Structure

- `engine/appc/hardpoint_override_writer.py` — (Task 1) confirm/repair `SetPosition` round-trip.
- `engine/ui/ship_property_viewer.py` — (Task 2) gizmo geometry, axis picking, drag mapping, body→world helper.
- `native/src/renderer/gizmo_pass.{h,cc}` — (Task 3) arrow rendering.
- `native/src/host/host_bindings.cc` — (Task 3) `set_transform_gizmo` binding + viewer-mode render call.
- `engine/renderer.py` — (Task 3) optional-binding wrapper.
- `engine/ui/ship_property_viewer_panel.py` — (Tasks 4–7) tool state, pending position, effective position, drag hook, save routing.
- `native/assets/ui-cef/{index.html,css/ship_property_viewer.css,js/ship_property_viewer.js}` — (Task 8) tool buttons.
- `engine/host_loop.py` — (Task 9) push the gizmo each SPV frame.
- Tests under `tests/unit/`, `tests/host/`.

---

### Task 1: `SetPosition` override round-trips through the writer

**Files:**
- Modify (only if the test fails): `engine/appc/hardpoint_override_writer.py`
- Test: `tests/unit/test_hardpoint_override_writer_setposition.py` (create)

**Interfaces:**
- Consumes: `read_models(module)`, `emit(models)`, `set_setter(models, leaf, subsystem, setter, args)` from `engine/appc/hardpoint_override_writer.py`.
- Produces: nothing new; proves `SetPosition(x,y,z)` survives the canonical fixed point and that a second `SetPosition` replaces the first.

**Background:** `read_models` stores multi-arg setters keyed as `(setter, args[:-1]) -> args[-1]` (writer docstring lines 12–15). This task proves a 3-arg `SetPosition` round-trips; if it doesn't, apply the minimal fix (the value store/readback must preserve all three components).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_hardpoint_override_writer_setposition.py
"""A SetPosition(x,y,z) override round-trips through the hardpoint writer.

The transform gizmo persists a subsystem's body-frame position as a 3-arg
SetPosition setter. The writer's canonical fixed point emit(read_models(m))==m
must hold with such an override present, and set_setter must replace a prior
SetPosition rather than appending a second one.
"""
import types
from engine.appc import hardpoint_override_writer as w


def _module_with(source: str):
    m = types.ModuleType("hardpoint_overrides")
    exec(compile(source, "hardpoint_overrides", "exec"), m.__dict__)
    m.__source__ = source
    return m


SRC = (
    "def galaxy(find):\n"
    "    p = find('Center Impulse')\n"
    "    p.SetPosition(0.1, 2.3, -0.4)\n"
)


def test_setposition_is_canonical_fixed_point():
    m = _module_with(SRC)
    models = w.read_models(m)
    assert w.emit(models) == SRC


def test_set_setter_replaces_prior_setposition():
    m = _module_with(SRC)
    models = w.read_models(m)
    w.set_setter(models, "galaxy", "Center Impulse", "SetPosition", (9.0, 8.0, 7.0))
    out = w.emit(models)
    assert out.count("SetPosition") == 1
    assert "SetPosition(9.0, 8.0, 7.0)" in out
```

- [ ] **Step 2: Run to see whether it passes or fails**

Run: `uv run pytest tests/unit/test_hardpoint_override_writer_setposition.py -v`
Expected: either PASS (writer already handles it — go to Step 4) or FAIL on the round-trip/replace assertion.

- [ ] **Step 3: If it failed, make the minimal writer fix**

Only if Step 2 failed: in `hardpoint_override_writer.py`, ensure multi-arg setter values preserve the full arg tuple through `read_models`/`emit`, and that `_replace_key` collapses `SetPosition` to `(setter,)` (it already returns `(setter,)` for non-`SetGlowRegion` setters — confirm). Do the smallest change that turns both assertions green; do not refactor unrelated setter handling.

- [ ] **Step 4: Run the writer suite**

Run: `uv run pytest tests/unit/test_hardpoint_override_writer.py tests/unit/test_hardpoint_override_writer_setposition.py -v`
Expected: PASS (no regression in the existing writer tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hardpoint_override_writer.py tests/unit/test_hardpoint_override_writer_setposition.py
git commit -m "test(spv): SetPosition override round-trips through the writer"
```

---

### Task 2: Gizmo geometry, picking, and drag mapping (pure Python)

**Files:**
- Modify: `engine/ui/ship_property_viewer.py` (add helpers near `project`/`pick_pin`)
- Test: `tests/unit/test_spv_gizmo_geometry.py` (create)

**Interfaces:**
- Consumes: `project(world, cam, viewport) -> (sx, sy, ndc_z, visible)`, `OrbitCamera` (`.eye()`, `.target`, `.up()`, `.distance`, `.fov_y_rad`, `.near`, `.far`), vector helpers `_add`/`_sub`/`_scale`/`_dot`/`_norm` (add `_add`/`_scale` if absent — check the module first; `_sub`/`_dot`/`_norm` exist).
- Produces:
  - `GIZMO_LENGTH_FRAC: float`, `GIZMO_MIN_LENGTH: float`, `GIZMO_PICK_PT: float`
  - `gizmo_length(cam) -> float`
  - `gizmo_axes(R) -> tuple[Vec3, Vec3, Vec3]`
  - `world_from_body(ship, body_pos) -> Vec3`
  - `pick_gizmo_axis(cursor_x, cursor_y, origin, axes, length, cam, viewport, device_scale_factor=1.0) -> Optional[int]`
  - `axis_drag_param(cursor_x, cursor_y, origin, axis, length, cam, viewport) -> float`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_spv_gizmo_geometry.py
"""Transform-gizmo geometry/picking/drag (pure Python, SPV logic core)."""
import math
import pytest

from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui import ship_property_viewer as spv
from engine.ui.ship_property_viewer import OrbitCamera


def _cam():
    # Looks down -Z at the origin from +Z; up is +Y.
    return OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0,
                       azimuth=0.0, elevation=0.0)


def test_gizmo_axes_are_rotation_columns():
    R = TGMatrix3()  # identity
    ax, ay, az = spv.gizmo_axes(R)
    assert ax == pytest.approx((1.0, 0.0, 0.0))
    assert ay == pytest.approx((0.0, 1.0, 0.0))
    assert az == pytest.approx((0.0, 0.0, 1.0))


def test_gizmo_length_scales_with_distance():
    far = spv.gizmo_length(OrbitCamera((0, 0, 0), 100.0, 0.0, 0.0))
    near = spv.gizmo_length(OrbitCamera((0, 0, 0), 4.0, 0.0, 0.0))
    assert far > near
    assert near >= spv.GIZMO_MIN_LENGTH


def test_world_from_body_applies_rotation_and_translation():
    class _Ship:
        def GetWorldLocation(self): return TGPoint3(5.0, 0.0, 0.0)
        def GetWorldRotation(self): return TGMatrix3()  # identity
    w = spv.world_from_body(_Ship(), (0.0, 2.0, 0.0))
    assert (w[0], w[1], w[2]) == pytest.approx((5.0, 2.0, 0.0))


def test_pick_gizmo_axis_hits_projected_shaft():
    cam, vp = _cam(), (800, 600)
    origin = (0.0, 0.0, 0.0)
    axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    length = spv.gizmo_length(cam)
    # A point on the +X shaft, projected to screen, must pick axis 0.
    tip = spv._add(origin, spv._scale(axes[0], length * 0.5))
    sx, sy, _z, vis = spv.project(tip, cam, vp)
    assert vis
    assert spv.pick_gizmo_axis(sx, sy, origin, axes, length, cam, vp) == 0


def test_pick_gizmo_axis_misses_off_shaft():
    cam, vp = _cam(), (800, 600)
    origin = (0.0, 0.0, 0.0)
    axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    length = spv.gizmo_length(cam)
    # Screen centre (origin projects there); far from any shaft midpoint edge.
    assert spv.pick_gizmo_axis(5.0, 5.0, origin, axes, length, cam, vp) is None


def test_axis_drag_param_monotonic_along_screen_axis():
    cam, vp = _cam(), (800, 600)
    origin = (0.0, 0.0, 0.0)
    axis = (1.0, 0.0, 0.0)
    length = spv.gizmo_length(cam)
    s0 = spv.project(origin, cam, vp)
    s1 = spv.project(spv._scale(axis, length), cam, vp)
    # Cursor at the projected tip → param ~= length; at origin → ~= 0.
    t_tip = spv.axis_drag_param(s1[0], s1[1], origin, axis, length, cam, vp)
    t_org = spv.axis_drag_param(s0[0], s0[1], origin, axis, length, cam, vp)
    assert t_tip == pytest.approx(length, abs=length * 0.05)
    assert t_org == pytest.approx(0.0, abs=length * 0.05)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_spv_gizmo_geometry.py -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'gizmo_axes'`).

- [ ] **Step 3: Implement the helpers**

Add near the projection/picking block in `engine/ui/ship_property_viewer.py`. First confirm `_add`/`_scale` exist; if not, add them beside `_sub`:

```python
def _add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def _scale(a, s): return (a[0] * s, a[1] * s, a[2] * s)
```

Then:

```python
# --- Transform gizmo -------------------------------------------------------
GIZMO_LENGTH_FRAC = 0.22   # arrow length as a fraction of orbit distance
GIZMO_MIN_LENGTH  = 0.30   # floor so it never collapses when zoomed in close
GIZMO_PICK_PT     = 8.0    # click threshold to a projected shaft, logical pts


def gizmo_length(cam: "OrbitCamera") -> float:
    """World length of each arrow — proportional to orbit distance so the
    gizmo keeps a near-constant apparent size at any zoom (fixed FOV)."""
    return max(GIZMO_MIN_LENGTH, cam.distance * GIZMO_LENGTH_FRAC)


def gizmo_axes(R):
    """The three unit body axes in world space (column-vector convention):
    X=starboard GetCol(0), Y=forward GetCol(1), Z=up GetCol(2)."""
    def col(k):
        c = R.GetCol(k)
        return _norm((c.x, c.y, c.z))
    return (col(0), col(1), col(2))


def world_from_body(ship, body_pos):
    """ship_loc + R * body_pos (column-vector R, no scale) — the world point
    of a body-frame position. Mirrors subsystem_world_position but takes an
    explicit body position (so a pending/dragged position can be placed)."""
    from engine.appc.math import TGPoint3, TGMatrix3
    loc = ship.GetWorldLocation()
    off = TGPoint3(body_pos[0], body_pos[1], body_pos[2])
    rot = ship.GetWorldRotation() if hasattr(ship, "GetWorldRotation") else None
    if isinstance(rot, TGMatrix3):
        off.MultMatrixLeft(rot)
    return (loc.x + off.x, loc.y + off.y, loc.z + off.z)


def _seg_dist2(px, py, ax, ay, bx, by):
    """Squared distance from point p to segment a-b, in screen pixels."""
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 1e-9:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


def pick_gizmo_axis(cursor_x, cursor_y, origin, axes, length, cam, viewport,
                    device_scale_factor: float = 1.0):
    """Axis index (0/1/2) whose projected shaft is within the click threshold
    of the cursor, nearest wins; None if none. Cursor/viewport are framebuffer
    pixels (as in pick_pin), so the logical threshold is scaled by DSF."""
    thresh = GIZMO_PICK_PT * (device_scale_factor if device_scale_factor > 0 else 1.0)
    best_d2, best = thresh * thresh, None
    s0x, s0y, _z0, v0 = project(origin, cam, viewport)
    if not v0:
        return None
    for k, axis in enumerate(axes):
        tip = _add(origin, _scale(axis, length))
        s1x, s1y, _z1, v1 = project(tip, cam, viewport)
        if not v1:
            continue
        d2 = _seg_dist2(cursor_x, cursor_y, s0x, s0y, s1x, s1y)
        if d2 < best_d2:
            best_d2, best = d2, k
    return best


def axis_drag_param(cursor_x, cursor_y, origin, axis, length, cam, viewport):
    """World distance along `axis` (from origin) of the cursor's projection
    onto the screen-projected shaft. Reuses project() only (no unprojection):
    robust for the near-frontal views the SPV orbit produces. The caller keeps
    the drag-start origin fixed and applies (param_now - param_grab)."""
    s0x, s0y, _z0, v0 = project(origin, cam, viewport)
    tip = _add(origin, _scale(axis, length))
    s1x, s1y, _z1, v1 = project(tip, cam, viewport)
    if not (v0 and v1):
        return 0.0
    ax, ay = s1x - s0x, s1y - s0y
    l2 = ax * ax + ay * ay
    if l2 <= 1e-9:
        return 0.0
    f = ((cursor_x - s0x) * ax + (cursor_y - s0y) * ay) / l2  # fraction of length
    return f * length
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_spv_gizmo_geometry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer.py tests/unit/test_spv_gizmo_geometry.py
git commit -m "feat(spv): gizmo geometry, axis picking, and drag mapping"
```

---

### Task 3: Native `GizmoPass` + `set_transform_gizmo` binding

**Files:**
- Create: `native/src/renderer/gizmo_pass.h`, `native/src/renderer/gizmo_pass.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (or the renderer sources list — mirror how `debug_volume_pass.cc` is listed)
- Modify: `native/src/host/host_bindings.cc` (global gizmo state, viewer-mode render call, `set_transform_gizmo`/`clear_transform_gizmo` bindings)
- Modify: `engine/renderer.py` (optional-binding wrapper)
- Test: `tests/host/test_transform_gizmo_binding.py` (create)

**Interfaces:**
- Consumes: `scenegraph::Camera` (`proj_matrix()`, `view_matrix()`), `renderer::Shader`, the `viewer_mode` flag and `g_camera` in `host_bindings.cc` (as `DebugVolumePass` does).
- Produces:
  - C++: `renderer::GizmoPass` with `struct Gizmo { glm::vec3 origin; glm::vec3 axis[3]; float length; int highlight; }` and `void render(const Gizmo&, const scenegraph::Camera&)`.
  - Python binding `set_transform_gizmo(origin, axis_x, axis_y, axis_z, length, highlight_axis)` and `clear_transform_gizmo()`.
  - `engine/renderer.py`: `Renderer.set_transform_gizmo(...)` / `clear_transform_gizmo()` no-op-guarded wrappers.

- [ ] **Step 1: Write the failing host test**

```python
# tests/host/test_transform_gizmo_binding.py
"""set_transform_gizmo / clear_transform_gizmo exist and accept the payload.
Headless: we only assert the bindings are present and callable (no GL)."""
import pytest

_h = pytest.importorskip("_dauntless_host")


def test_transform_gizmo_bindings_present():
    assert hasattr(_h, "set_transform_gizmo")
    assert hasattr(_h, "clear_transform_gizmo")


def test_set_transform_gizmo_accepts_payload():
    # origin, three axes, length, highlight — must not raise.
    _h.set_transform_gizmo((0.0, 0.0, 0.0),
                           (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                           1.5, 1)
    _h.clear_transform_gizmo()
```

- [ ] **Step 2: Run to verify failure**

Run: `cmake --build build -j && uv run pytest tests/host/test_transform_gizmo_binding.py -v`
Expected: FAIL (`assert hasattr(_h, "set_transform_gizmo")`).

- [ ] **Step 3: Implement `gizmo_pass.h`**

```cpp
// native/src/renderer/gizmo_pass.h
#pragma once
#include <glm/glm.hpp>
#include <memory>

namespace scenegraph { class Camera; }

namespace renderer {

class Shader;

class GizmoPass {
public:
    struct Gizmo {
        glm::vec3 origin{0.0f};
        glm::vec3 axis[3]{{1,0,0},{0,1,0},{0,0,1}};
        float length{1.0f};
        int highlight{-1};   // 0/1/2 = brightened axis, -1 = none
    };

    GizmoPass();
    ~GizmoPass();

    // Draws three coloured arrows (shaft + head), depth-test off. No-op when
    // length <= 0.
    void render(const Gizmo& g, const scenegraph::Camera& camera);

private:
    void ensure_resources();
    std::unique_ptr<Shader> shader_;
    unsigned int vao_{0}, vbo_{0};
    int vertex_count_{0};
};

}  // namespace renderer
```

- [ ] **Step 4: Implement `gizmo_pass.cc`**

Model it on `debug_volume_pass.cc`. Build a unit arrow along +Z once (shaft as a line 0→0.85, a small cone of `GL_LINES` spokes from a base ring at z=0.85,r=0.05 to the tip at z=1.0). In `render`, for each axis `k` build a model matrix that rotates +Z onto `g.axis[k]` and scales by `g.length`, translate to `g.origin`, set `u_mvp = vp * model`, set `u_color` (X=`(0.9,0.25,0.25)`, Y=`(0.35,0.9,0.35)`, Z=`(0.35,0.55,1.0)`), brighten when `k==g.highlight` (e.g. `mix(color, vec3(1), 0.4)` on the CPU side), and draw `GL_LINES`. Disable depth test and cull, restore after. Reuse the trivial VS/FS pattern from `debug_volume_pass.cc` (`u_mvp`, `u_color`; no `u_alpha` needed — always opaque). Guard `if (g.length <= 0.0f) return;`.

To rotate +Z onto an arbitrary unit axis `a`: if `dot(z,a) > 0.9999` use identity; if `< -0.9999` rotate 180° about X; else `axis = normalize(cross(z,a)); angle = acos(dot(z,a)); model = rotate(angle, axis)`.

- [ ] **Step 5: Add to the build**

Add `gizmo_pass.cc` to the same sources list `debug_volume_pass.cc` appears in (grep the `native/` CMake files for `debug_volume_pass`). Reconfigure: `cmake -B build -S .`.

- [ ] **Step 6: Wire host bindings**

In `native/src/host/host_bindings.cc`, mirroring the debug-volume globals (~line 231) and render (~line 909) and defs (~line 2422):

```cpp
renderer::GizmoPass::Gizmo               g_transform_gizmo;      // length 0 => hidden
std::unique_ptr<renderer::GizmoPass>     g_gizmo_pass;
```
Create `g_gizmo_pass = std::make_unique<renderer::GizmoPass>();` where `g_debug_volume_pass` is created, and `g_gizmo_pass.reset();` where it is reset. In the viewer-mode render block (after the debug volumes, ~line 914):
```cpp
if (viewer_mode && g_gizmo_pass && g_transform_gizmo.length > 0.0f)
    g_gizmo_pass->render(g_transform_gizmo, g_camera);
```
Bindings (near line 2422):
```cpp
m.def("set_transform_gizmo",
      [](std::array<float,3> o,
         std::array<float,3> ax, std::array<float,3> ay, std::array<float,3> az,
         float length, int highlight) {
          g_transform_gizmo.origin = {o[0], o[1], o[2]};
          g_transform_gizmo.axis[0] = {ax[0], ax[1], ax[2]};
          g_transform_gizmo.axis[1] = {ay[0], ay[1], ay[2]};
          g_transform_gizmo.axis[2] = {az[0], az[1], az[2]};
          g_transform_gizmo.length = length;
          g_transform_gizmo.highlight = highlight;
      });
m.def("clear_transform_gizmo", []() { g_transform_gizmo.length = 0.0f; });
```
Include `<renderer/gizmo_pass.h>` at the top (near the `debug_volume_pass.h` include). Confirm `<array>` is available (it is, via other bindings).

- [ ] **Step 7: Add the `engine/renderer.py` wrapper**

Add `"set_transform_gizmo"` and `"clear_transform_gizmo"` to `_OPTIONAL_BINDINGS`, and wrappers:
```python
def set_transform_gizmo(self, origin, ax, ay, az, length, highlight):
    fn = getattr(_h, "set_transform_gizmo", None)
    if fn is not None:
        fn(origin, ax, ay, az, float(length), int(highlight))

def clear_transform_gizmo(self):
    fn = getattr(_h, "clear_transform_gizmo", None)
    if fn is not None:
        fn()
```

- [ ] **Step 8: Build and run the host test + gate**

Run: `cmake --build build -j && uv run pytest tests/host/test_transform_gizmo_binding.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add native/src/renderer/gizmo_pass.h native/src/renderer/gizmo_pass.cc native/src/host/host_bindings.cc engine/renderer.py tests/host/test_transform_gizmo_binding.py
git add native/src/renderer/CMakeLists.txt   # or whichever CMake sources file you edited
git commit -m "feat(spv): native GizmoPass + set_transform_gizmo binding"
```

---

### Task 4: Panel tool state (Transform/Rotate/Scale radio)

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/unit/test_ship_property_viewer_panel_tool.py` (create)

**Interfaces:**
- Consumes: `dispatch_event(action)`, `render_payload()`, `open()`/`close()` reset points.
- Produces: `self.active_tool: Optional[str]` (`None|"transform"|"rotate"|"scale"`, default `None`); dispatch `set_tool:<name>` toggling it; `render_payload()` key `"active_tool"`; reset to `None` in `open`/`close`; `render_payload` snapshot includes `active_tool` (so a tool change re-pushes).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_ship_property_viewer_panel_tool.py
"""SPV transform-tool radio state."""
import json
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel


def _panel():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.open()
    return p


def test_default_tool_is_none():
    assert _panel().active_tool is None


def test_set_tool_activates_and_toggles_off():
    p = _panel()
    assert p.dispatch_event("set_tool:transform") is True
    assert p.active_tool == "transform"
    # Selecting the active tool again clears it.
    assert p.dispatch_event("set_tool:transform") is True
    assert p.active_tool is None


def test_set_tool_is_mutually_exclusive():
    p = _panel()
    p.dispatch_event("set_tool:transform")
    p.dispatch_event("set_tool:rotate")
    assert p.active_tool == "rotate"


def test_unknown_tool_rejected():
    p = _panel()
    assert p.dispatch_event("set_tool:bogus") is False
    assert p.active_tool is None


def test_render_payload_carries_active_tool():
    p = _panel()
    p.dispatch_event("set_tool:transform")
    payload = json.loads(p.render_payload())
    assert payload["active_tool"] == "transform"


def test_close_resets_tool():
    p = _panel()
    p.dispatch_event("set_tool:scale")
    p.close()
    assert p.active_tool is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_ship_property_viewer_panel_tool.py -v`
Expected: FAIL (`AttributeError: 'ShipPropertyViewerPanel' object has no attribute 'active_tool'`).

- [ ] **Step 3: Implement**

In `__init__` (beside `self.selected_index`): `self.active_tool = None`. In `open()` and `close()` (beside `self.selected_index = None`): `self.active_tool = None`. Add the dispatch case (place near the other toggles, before `save`):
```python
if action.startswith("set_tool:"):
    name = action.split(":", 1)[1]
    if name not in ("transform", "rotate", "scale"):
        return False
    self.active_tool = None if self.active_tool == name else name
    self._last_pushed = None
    return True
```
Add `"active_tool": self.active_tool` to the `render_payload()` dict, and add `self.active_tool` to the `snapshot` tuple so a tool change invalidates the push.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_ship_property_viewer_panel_tool.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/unit/test_ship_property_viewer_panel_tool.py
git commit -m "feat(spv): Transform/Rotate/Scale tool radio state"
```

---

### Task 5: Effective position + subsystem position persistence

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/unit/test_ship_property_viewer_panel_position.py` (create)

**Interfaces:**
- Consumes: `_effective_radius`/`_saved_radius` pattern; `_descriptors[i]` with `properties.position` (baked body position) and `world_pos`; `world_from_body`, `descriptors()`; `region_spec_to_calls`, `resolve_override_target`, `hardpoint_leaf_for_ship` (already imported); `selected_subsystem_sphere`, `subsystem_pins`, `_pending_edits`, `_subsystem_rows`, `render_payload`, the `save` case.
- Produces:
  - `self._pending_pos: dict[int,(x,y,z)]`, `self._saved_pos: dict[int,(x,y,z)]` (subsystem descriptor index → body pos), reset in `open`/`close`.
  - `_effective_pos(index) -> (x,y,z)` (pending → saved → baked `properties.position`).
  - `_effective_world_pos(index) -> Vec3` (ship_loc + R·effective body pos) using `world_from_body`.
  - `set_subsystem_position(index, body_pos)` (stages `_pending_pos`).
  - `subsystem_pins()` and `selected_subsystem_sphere()` use `_effective_world_pos(selected)` for the selected subsystem so it follows a staged/dragged position.
  - `pending_count`, `_pending_edits`, `_subsystem_rows` dirty, and the `save` edit list all include `_pending_pos` (→ `(name, "SetPosition", (x,y,z))`), and `_saved_pos` retains the just-saved value post-Save (mirroring `_saved_radius`).

**Note for the implementer:** confirm the baked body position lives at `_descriptors[i]["properties"]["position"]` (built by `_properties_for`/`build_descriptors`). If a descriptor lacks it, `_effective_pos` falls back to the descriptor's stored `local`/`(0,0,0)` — read the descriptor builder in `ship_property_viewer.py` and use whatever field carries the body-frame mount; do NOT invent a new one.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_ship_property_viewer_panel_position.py
"""SPV effective position + subsystem SetPosition persistence."""
import pytest
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel


class _FakeTarget:
    def __init__(self): self.written = None
    def write(self, leaf, edits): self.written = (leaf, list(edits))


def _panel_with_one_subsystem(monkeypatch, baked_pos=(0.0, 1.0, 0.0)):
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": baked_pos, "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
    }]
    return p


def test_effective_pos_prefers_pending_then_saved_then_baked(monkeypatch):
    p = _panel_with_one_subsystem(monkeypatch, baked_pos=(0.0, 1.0, 0.0))
    assert p._effective_pos(0) == (0.0, 1.0, 0.0)
    p._saved_pos[0] = (0.0, 2.0, 0.0)
    assert p._effective_pos(0) == (0.0, 2.0, 0.0)
    p._pending_pos[0] = (0.0, 3.0, 0.0)
    assert p._effective_pos(0) == (0.0, 3.0, 0.0)


def test_set_subsystem_position_stages_pending_and_counts(monkeypatch):
    p = _panel_with_one_subsystem(monkeypatch)
    p.set_subsystem_position(0, (1.5, 1.0, 0.0))
    assert p._pending_pos[0] == (1.5, 1.0, 0.0)
    import json
    payload = json.loads(p.render_payload())
    assert payload["pending_count"] == 1


def test_save_routes_setposition(monkeypatch):
    p = _panel_with_one_subsystem(monkeypatch)
    tgt = _FakeTarget()
    monkeypatch.setattr(
        "engine.ui.ship_property_viewer_panel.resolve_override_target",
        lambda ship: tgt)
    monkeypatch.setattr(
        "engine.ui.ship_property_viewer_panel.hardpoint_leaf_for_ship",
        lambda ship: "galaxy")
    p.set_subsystem_position(0, (1.5, 1.0, 0.0))
    assert p.dispatch_event("save") is True
    assert tgt.written is not None
    leaf, edits = tgt.written
    assert ("Center Impulse", "SetPosition", (1.5, 1.0, 0.0)) in edits
    # Saved value retained for in-session preview; no longer pending.
    assert p._pending_pos == {}
    assert p._saved_pos[0] == (1.5, 1.0, 0.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_ship_property_viewer_panel_position.py -v`
Expected: FAIL (`AttributeError: ... '_effective_pos'`).

- [ ] **Step 3: Implement**

- `__init__`, `open`, `close`: add `self._pending_pos = {}` and `self._saved_pos = {}` (reset alongside `_pending_radius`/`_saved_radius`).
- Add:
```python
def _effective_pos(self, index):
    if index in self._pending_pos:
        return self._pending_pos[index]
    if index in self._saved_pos:
        return self._saved_pos[index]
    props = self._descriptors[index].get("properties", {})
    return tuple(props.get("position") or (0.0, 0.0, 0.0))

def _effective_world_pos(self, index):
    from engine.ui.ship_property_viewer import world_from_body
    ship = self._ship_getter()
    if ship is None:
        return self._descriptors[index].get("world_pos", (0.0, 0.0, 0.0))
    return world_from_body(ship, self._effective_pos(index))

def set_subsystem_position(self, index, body_pos):
    if 0 <= index < len(self._descriptors):
        self._pending_pos[index] = (float(body_pos[0]), float(body_pos[1]),
                                    float(body_pos[2]))
        self._last_pushed = None
```
- `selected_subsystem_sphere`: replace the `center` source for the selected subsystem with `self._effective_world_pos(sel)`.
- `subsystem_pins`: when returning the selected subsystem's pin, use `self._effective_world_pos(sel)` for its world position (only the selected pin needs this — others are hidden during selection).
- `_pending_edits`, `pending_count` (`render_payload`), and `_subsystem_rows` dirty: include `_pending_pos` in the `set(...)` unions (each becomes `set(self._pending_radius) | set(self._pending_light) | set(self._pending_pos)`; the per-name count adds `+ (1 if i in self._pending_pos else 0)`).
- `save` case: extend the `edits` list with
  `[(self._descriptors[i]["name"], "SetPosition", tuple(v)) for i, v in sorted(self._pending_pos.items())]`, include `_pending_pos` in the early `if not ... : return True` guard, and in the post-write "keep just-saved" block move `_pending_pos` into `_saved_pos` and clear `_pending_pos` (mirror exactly what the code does for `_pending_radius`/`_saved_radius`).

- [ ] **Step 4: Run to verify pass + regression**

Run: `uv run pytest tests/unit/test_ship_property_viewer_panel_position.py tests/unit/test_ship_property_viewer_panel.py -v`
Expected: PASS (existing panel tests still green).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/unit/test_ship_property_viewer_panel_position.py
git commit -m "feat(spv): effective position + subsystem SetPosition persistence"
```

---

### Task 6: Gizmo accessor + axis-drag hook in `handle_input` (subsystems)

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/unit/test_ship_property_viewer_panel_gizmo.py` (create)

**Interfaces:**
- Consumes: `active_tool`, `selected_index`, `_effective_pos`, `_effective_world_pos`, `set_subsystem_position`, camera, `_ship_getter`; gizmo helpers from Task 2 (`gizmo_axes`, `gizmo_length`, `pick_gizmo_axis`, `axis_drag_param`, `world_from_body`); the existing `handle_input` press/drag/release structure.
- Produces:
  - `transform_gizmo() -> Optional[dict]` = `{"origin": Vec3, "axes": (ax,ay,az), "length": float, "highlight": int}` when `active_tool == "transform"` and a subsystem is selected; else `None`.
  - Drag state: `self._axis_drag` (None or 0/1/2), `self._axis_grab_param`, `self._axis_grab_pos`, `self._axis_grab_origin`, `self._gizmo_hover` (int, -1 default).
  - `handle_input` picks a gizmo axis on the press edge (transform tool + subsystem selected + not over chrome); drags move the subsystem along the axis via `set_subsystem_position`; release ends the drag; orbit is suppressed while an axis is grabbed; hover highlight is updated when not dragging.

**Note:** keep the light-node case out of this task — `transform_gizmo()`/drag here handle a selected **subsystem** (`selected_index`). Task 7 adds the light-node branch.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_ship_property_viewer_panel_gizmo.py
"""SPV transform gizmo accessor + drag application (subsystem target)."""
import pytest
from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel
from engine.ui.ship_property_viewer import OrbitCamera


class _Ship:
    def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
    def GetWorldRotation(self): return TGMatrix3()  # identity


def _panel():
    p = ShipPropertyViewerPanel(ship_getter=lambda: _Ship())
    p.open()
    p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
    }]
    return p


def test_no_gizmo_without_transform_tool():
    p = _panel()
    p.selected_index = 0
    assert p.transform_gizmo() is None       # tool is None
    p.dispatch_event("set_tool:transform")
    g = p.transform_gizmo()
    assert g is not None
    assert g["origin"] == pytest.approx((0.0, 1.0, 0.0))
    assert g["length"] > 0.0


def test_no_gizmo_without_selection():
    p = _panel()
    p.dispatch_event("set_tool:transform")
    assert p.transform_gizmo() is None       # nothing selected


def test_gizmo_origin_follows_pending_position():
    p = _panel()
    p.selected_index = 0
    p.dispatch_event("set_tool:transform")
    p.set_subsystem_position(0, (0.0, 4.0, 0.0))
    assert p.transform_gizmo()["origin"] == pytest.approx((0.0, 4.0, 0.0))


def test_apply_axis_drag_moves_only_that_component():
    p = _panel()
    p.selected_index = 0
    p.dispatch_event("set_tool:transform")
    # Simulate a grab on axis Y (1) then a move of +2.0 world units along it.
    p._begin_axis_drag_for_test(axis=1, grab_param=0.0)
    p._apply_axis_drag(2.0)   # param delta = 2.0 along +Y
    x, y, z = p._effective_pos(0)
    assert (x, z) == pytest.approx((0.0, 0.0))
    assert y == pytest.approx(3.0)   # baked 1.0 + 2.0
```

For the two test helpers, add small internal methods usable by tests and by `handle_input`:
`_begin_axis_drag_for_test(axis, grab_param)` sets `self._axis_drag=axis`, `self._axis_grab_param=grab_param`, `self._axis_grab_pos=self._effective_pos(self.selected_index)`, `self._axis_grab_origin=self._effective_world_pos(self.selected_index)`; and `_apply_axis_drag(param_now)` computes `delta = param_now - self._axis_grab_param` and calls `set_subsystem_position(self.selected_index, grab_pos with component axis += delta)`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_ship_property_viewer_panel_gizmo.py -v`
Expected: FAIL (`AttributeError: ... 'transform_gizmo'`).

- [ ] **Step 3: Implement the accessor + drag application**

```python
def transform_gizmo(self):
    if self.active_tool != "transform" or self.camera is None:
        return None
    if self.selected_index is None:
        return None
    ship = self._ship_getter()
    if ship is None or not hasattr(ship, "GetWorldRotation"):
        return None
    from engine.ui.ship_property_viewer import gizmo_axes, gizmo_length
    return {
        "origin": self._effective_world_pos(self.selected_index),
        "axes": gizmo_axes(ship.GetWorldRotation()),
        "length": gizmo_length(self.camera),
        "highlight": self._gizmo_hover,
    }

def _begin_axis_drag(self, axis, grab_param):
    self._axis_drag = axis
    self._axis_grab_param = grab_param
    self._axis_grab_pos = self._effective_pos(self.selected_index)

def _begin_axis_drag_for_test(self, axis, grab_param):   # test seam
    self._begin_axis_drag(axis, grab_param)

def _apply_axis_drag(self, param_now):
    if self._axis_drag is None or self.selected_index is None:
        return
    k = self._axis_drag
    base = list(self._axis_grab_pos)
    base[k] += (param_now - self._axis_grab_param)
    self.set_subsystem_position(self.selected_index, tuple(base))

def _end_axis_drag(self):
    self._axis_drag = None
```
Initialise in `__init__`/`open`/`close`: `self._axis_drag = None`, `self._axis_grab_param = 0.0`, `self._axis_grab_pos = (0.0, 0.0, 0.0)`, `self._gizmo_hover = -1`.

- [ ] **Step 4: Hook into `handle_input`**

In `handle_input`, after computing `x, y`, `dsf`, `over_chrome` and the gizmo helpers import, and BEFORE the existing orbit press/drag/release block:

- Compute the current gizmo (once): `g = self.transform_gizmo()`.
- **Hover** (only when not dragging and `g` and not `over_chrome`): `self._gizmo_hover = pick_gizmo_axis(x, y, g["origin"], g["axes"], g["length"], self.camera, fb_size(), dsf)` mapped to `-1` when `None`; else `self._gizmo_hover = -1`.
- **Press edge** (`down and not self._lmb_down`): if `g` and not `over_chrome`, `axis = pick_gizmo_axis(...)`; if `axis is not None`: set `self._chrome_press = False`, start the axis drag —
  `t_grab = axis_drag_param(x, y, g["origin"], g["axes"][axis], g["length"], self.camera, fb_size())`, `self._begin_axis_drag(axis, t_grab)`, `self._axis_grab_origin = g["origin"]`, and set `self._lmb_down = True`, `self._drag_last = (x, y)`, then **return** (do not fall into orbit-press).
- **Drag** (`down and self._lmb_down`): if `self._axis_drag is not None`: `t = axis_drag_param(x, y, self._axis_grab_origin, self.transform_gizmo()["axes"][self._axis_drag], gizmo_length(self.camera), self.camera, fb_size())`; `self._apply_axis_drag(t)`; update `self._drag_last`; **return** (skip orbit). (Use the fixed `self._axis_grab_origin` captured at press, not the moving effective origin, so the mapping is stable.)
- **Release** (`not down and self._lmb_down`): if `self._axis_drag is not None`: `self._end_axis_drag()`, reset `self._lmb_down=False`, `self._drag_last=None`, and **return** (no pin pick).

Keep all existing orbit/pin behaviour when `self._axis_drag is None` and no axis was grabbed. Guard the whole gizmo path so a missing binding / `None` camera degrades to today's behaviour.

- [ ] **Step 5: Run to verify pass + regression**

Run: `uv run pytest tests/unit/test_ship_property_viewer_panel_gizmo.py tests/unit/test_ship_property_viewer_panel.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/unit/test_ship_property_viewer_panel_gizmo.py
git commit -m "feat(spv): gizmo accessor + axis-drag hook for subsystems"
```

---

### Task 7: Light-volume transform target

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: extend `tests/unit/test_ship_property_viewer_panel_gizmo.py`

**Interfaces:**
- Consumes: `_selected_light_index`, `_effective_light(index)` (spec dict with `position`), `_pending_light`, `subsystem_world_position`/`world_from_body`, `region_spec_to_calls` save path (already routes `_pending_light`).
- Produces:
  - `transform_gizmo()` also returns a gizmo when `active_tool == "transform"` and a light node is selected (`_selected_light_index is not None`), with `origin = world_from_body(ship, effective_light.position)`.
  - The drag application writes the dragged position into the light's effective spec: `set_light_position(subsys_index, body_pos)` stages `_pending_light[i]` = `dict(effective_light, position=body_pos)`. No new save routing (the existing `__region__` path already emits `SetGlowRegionPosition`).
  - `_apply_axis_drag` branches on which selection is active (light vs subsystem).

- [ ] **Step 1: Write the failing tests**

```python
def _panel_with_light():
    # Builds on _panel(): give the descriptor a baked light region.
    p = _panel()
    p._descriptors[0]["light_region"] = {
        "shape": "Sphere", "position": (0.0, 1.0, 0.0), "axis": (0.0, -1.0, 0.0),
        "radius": (0.25,), "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25)}
    return p


def test_gizmo_targets_selected_light_node():
    p = _panel_with_light()
    p.dispatch_event("set_tool:transform")
    p._selected_light_index = 0     # light node selected (subsystem not)
    g = p.transform_gizmo()
    assert g is not None
    assert g["origin"] == pytest.approx((0.0, 1.0, 0.0))


def test_axis_drag_moves_light_position():
    p = _panel_with_light()
    p.dispatch_event("set_tool:transform")
    p._selected_light_index = 0
    p._begin_axis_drag_for_test(axis=0, grab_param=0.0)  # +X (starboard)
    p._apply_axis_drag(1.5)
    spec = p._effective_light(0)
    assert spec["position"] == pytest.approx((1.5, 1.0, 0.0))
```

(`_begin_axis_drag` must capture the grab position from the light spec when a light is selected — see Step 3.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_ship_property_viewer_panel_gizmo.py -v`
Expected: FAIL on the two new tests.

- [ ] **Step 3: Implement the light branch**

- Add a small selector: `_active_transform_target()` returns `("light", i)` when `self._selected_light_index is not None`, else `("subsystem", self.selected_index)` when set, else `None`.
- `transform_gizmo()`: compute origin from the active target — subsystem → `_effective_world_pos(i)`; light → `world_from_body(ship, self._effective_light(i)["position"])`. Return `None` if neither is selected. Axes/length/highlight unchanged.
- `set_light_position(i, body_pos)`: `spec = dict(self._effective_light(i) or {}); spec["position"] = tuple(body_pos); self._pending_light[i] = spec; self._last_pushed = None`.
- `_begin_axis_drag(axis, grab_param)`: capture `self._axis_grab_pos` from the active target — subsystem → `_effective_pos(i)`; light → `self._effective_light(i)["position"]`.
- `_apply_axis_drag(param_now)`: apply the delta to `_axis_grab_pos[k]` and dispatch by active target — subsystem → `set_subsystem_position`; light → `set_light_position`.

- [ ] **Step 4: Run to verify pass + regression**

Run: `uv run pytest tests/unit/test_ship_property_viewer_panel_gizmo.py tests/unit/test_ship_property_viewer_panel.py tests/unit/test_ship_property_viewer_panel_position.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/unit/test_ship_property_viewer_panel_gizmo.py
git commit -m "feat(spv): transform gizmo targets light-volume nodes"
```

---

### Task 8: CEF tool buttons (Transform/Rotate/Scale)

**Files:**
- Modify: `native/assets/ui-cef/index.html`
- Modify: `native/assets/ui-cef/css/ship_property_viewer.css`
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js`
- Test: none automated (CEF DOM is covered by Mark's in-game pass; the panel state is already tested in Task 4). Verify by reading the diff for correctness.

**Interfaces:**
- Consumes: the panel `active_tool` field surfaced in `render_payload()` (Task 4); the `set_tool:<name>` dispatch action; the existing SPV event channel used by `shipPropertyViewerToggle` (find how toggles fire `ship-property-viewer/...` events and mirror it).
- Produces: a `#spv-transform-tools` button group rendered **above** `#spv-tools`; three buttons (Transform=move glyph, Rotate=circular-arrow glyph, Scale=corner-handles glyph) that fire `set_tool:transform|rotate|scale`; the active button reflects `active_tool` (`.active` class driven off the render payload, same mechanism the glow/arcs/hull buttons use for their active state).

- [ ] **Step 1: Add the button group to `index.html`**

Immediately before `<div id="spv-tools">` (line ~202), add:
```html
<!-- Transform tools (position gizmo). Rotate/Scale are inert stubs this
     pass. Mutually exclusive; the active tool carries .active. -->
<div id="spv-transform-tools">
  <button id="spv-tool-transform" class="spv-tool"
          title="Move" onclick="shipPropertyViewerSetTool('transform')">
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none"
         stroke="currentColor" stroke-width="2" stroke-linecap="round"
         stroke-linejoin="round">
      <path d="M12 2v20M2 12h20M12 2l-3 3M12 2l3 3M12 22l-3-3M12 22l3-3M2 12l3-3M2 12l3 3M22 12l-3-3M22 12l-3 3"/>
    </svg>
  </button>
  <button id="spv-tool-rotate" class="spv-tool"
          title="Rotate" onclick="shipPropertyViewerSetTool('rotate')">
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none"
         stroke="currentColor" stroke-width="2" stroke-linecap="round">
      <path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v5h-5"/>
    </svg>
  </button>
  <button id="spv-tool-scale" class="spv-tool"
          title="Scale" onclick="shipPropertyViewerSetTool('scale')">
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none"
         stroke="currentColor" stroke-width="2" stroke-linecap="round"
         stroke-linejoin="round">
      <path d="M3 21h6M3 21v-6M3 21l7-7M21 3h-6M21 3v6M21 3l-7 7"/>
    </svg>
  </button>
</div>
```

- [ ] **Step 2: Add the JS handler + active-state sync**

In `js/ship_property_viewer.js`: add
```javascript
function shipPropertyViewerSetTool(name) {
  // mirror shipPropertyViewerToggle's event dispatch mechanism
  dauntlessEvent('ship-property-viewer/dispatch', 'set_tool:' + name);
}
```
(Use whatever helper `shipPropertyViewerToggle` uses to fire its action — read that function and copy its channel exactly.) In the render-payload apply function (where the glow/arcs/hull buttons get their `.active` class from the payload), set each tool button's `.active` from `payload.active_tool`:
```javascript
var at = payload.active_tool;
setActive('spv-tool-transform', at === 'transform');
setActive('spv-tool-rotate',    at === 'rotate');
setActive('spv-tool-scale',     at === 'scale');
```
(Reuse the existing active-toggle helper; if the existing code sets `classList.toggle('active', cond)` inline, match that.)

- [ ] **Step 3: Style the group in the CSS**

In `css/ship_property_viewer.css`, position `#spv-transform-tools` directly above `#spv-tools` (same right margin, same column layout, stacked). Reuse the existing `#spv-tools`/`.spv-tool`/`.spv-tool.active` rules; add only the container position:
```css
#spv-transform-tools {
  position: absolute;
  right: 16px;                     /* match #spv-tools right */
  bottom: calc(16px + 3 * 44px + 12px);  /* above the 3 render buttons; tune to real sizes */
  display: flex;
  flex-direction: column;
  gap: 6px;
}
```
Read the real `#spv-tools` `bottom`/button sizes and set `#spv-transform-tools`'s `bottom` so the group sits just above the glow/arcs/hull cluster with a small gap. Extend `_cursor_over_tools` coverage in the panel if the click-guard box must include the new group — check `TOOLS_H_PT`/`TOOLS_MARGIN_PT` and widen the guarded region so clicks on the transform buttons are treated as chrome (they must NOT start an orbit/gizmo drag). If widening is needed, do it in `ship_property_viewer_panel.py` and add a `_cursor_over_tools` assertion to the panel tests.

- [ ] **Step 4: Verify the render path builds and the gate is green**

Run: `scripts/check_tests.sh`
Expected: OK — no new failures (CEF assets are copied from source; no C++ change here).

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/css/ship_property_viewer.css native/assets/ui-cef/js/ship_property_viewer.js
git add engine/ui/ship_property_viewer_panel.py tests/unit/test_ship_property_viewer_panel.py  # only if the click-guard was widened
git commit -m "feat(spv): Transform/Rotate/Scale tool buttons above the render tools"
```

---

### Task 9: Host-loop wiring — push the gizmo each SPV frame

**Files:**
- Modify: `engine/host_loop.py`
- Test: none new (integration; the gizmo accessor is unit-tested, the binding is host-tested). Verify by reading the diff and running the gate.

**Interfaces:**
- Consumes: `ship_property_viewer.transform_gizmo()`; `r.set_transform_gizmo(...)` / `r.clear_transform_gizmo()` (Task 3 wrappers); the existing SPV render block (~lines 7283–7360) that already pushes pins/sphere/overlay and, on the closed edge, clears them.
- Produces: each frame the SPV is open, push the gizmo (or clear it when `transform_gizmo()` is `None`); on the SPV close edge, `clear_transform_gizmo()`.

- [ ] **Step 1: Push the gizmo in the open branch**

In the `if _spv_open:` block, alongside the `r.set_subsystem_pins(...)` / `r.set_spv_overlay_beams(...)` / sphere push, add:
```python
_gizmo = ship_property_viewer.transform_gizmo()
if _gizmo is not None:
    ox, oy, oz = _gizmo["origin"]
    ax, ay, az = _gizmo["axes"]
    r.set_transform_gizmo((ox, oy, oz), ax, ay, az,
                          _gizmo["length"], _gizmo["highlight"])
else:
    r.clear_transform_gizmo()
```

- [ ] **Step 2: Clear on the close edge**

In the `if _spv_was_open:` cleanup branch (where `r.clear_spv_overlay_beams()` etc. run), add `r.clear_transform_gizmo()`.

- [ ] **Step 3: Run the gate**

Run: `scripts/check_tests.sh`
Expected: OK — no new failures.

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(spv): push transform gizmo to the renderer each SPV frame"
```

---

## Self-Review

**Spec coverage:**
- Toolbar above `#spv-tools`, radio, inert Rotate/Scale → Tasks 4, 8.
- Body-frame axes, gizmo visible only when Transform active + selection → Tasks 2, 6, 7.
- Ray/screen drag along an axis, live preview → Tasks 2, 6 (subsystem), 7 (light).
- Persistence via `SetPosition` (subsystem) and region-0 `position` (light) through the staged Save/confirm flow → Tasks 5, 7.
- Native arrow rendering, empty=byte-identical → Task 3.
- Host push each frame → Task 9.
- Writer round-trip risk → Task 1.

**Placeholder scan:** every code step carries real code or a precise, file-anchored instruction (CSS `bottom` and the JS event channel are the only "read the real value / mirror the existing helper" steps — both point at a concrete existing symbol to copy, not an open-ended TODO).

**Type consistency:** `gizmo_axes`/`gizmo_length`/`pick_gizmo_axis`/`axis_drag_param`/`world_from_body` signatures match between Task 2 (definition) and Tasks 6–7 (use); `transform_gizmo()` dict shape (`origin`/`axes`/`length`/`highlight`) matches Task 6/7 producer and Task 9 consumer and the Task 3 binding arg order (`origin, ax, ay, az, length, highlight`); `set_transform_gizmo` Python wrapper arg order matches the pybind def; `_pending_pos`/`_saved_pos` mirror `_pending_radius`/`_saved_radius` usage everywhere they're unioned.
