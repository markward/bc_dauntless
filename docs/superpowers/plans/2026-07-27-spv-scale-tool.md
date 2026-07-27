# SPV Scale Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A shape-aware Scale tool (gizmo + top-right panel) for the SPV, editing the selected element's size (subsystem/sphere radius, cylinder radius+length, box XYZ), staged and saved through the existing flow.

**Architecture:** Reuses the Transform gizmo + coord-panel plumbing. New Python scale value-model/dispatch/gizmo-drag in `ship_property_viewer_panel.py`; a cube-handle mode on the native `GizmoPass`; a shape-aware CEF `#spv-scale` panel. No new persistence path.

**Tech Stack:** Python 3, C++/OpenGL, pybind11, CEF, pytest.

## Global Constraints

- **Developer-only, production byte-identical.** Reachable only under `--developer` + SPV open + Scale tool active. `scale_values()`/`scale_gizmo()` return `None` otherwise; the native gizmo draws nothing when length 0.
- **Mouse-only.** Nudge steppers + Copy/Paste/Uniform are CEF clicks; the gizmo is a viewport drag.
- **Shape-aware size** (subsystem→Radius; Sphere→Radius; Cylinder→Radius,Length; Box→X,Y,Z). Persist: subsystem radius → `_pending_radius`/`SetRadius`; light size → `_pending_light` spec → `set_region`. **No new persistence path.**
- **Uniform = largest of X/Y/Z (Box only)**; no-op elsewhere. **Copy/Paste are kind-matched** (Paste only when clipboard kind == current kind). **No Mirror** for scale.
- **Only one of Transform/Scale active** (radio); the two top-right panels never render together.
- **SCALE_MIN floor** on every size set (> 0), so a drag/nudge can't zero a dimension.
- **Shared checkout.** Explicit pathspecs only. Never `git add -A`/`checkout`/`restore`/`stash`/`reset --hard`/`clean`.
- **Test gate.** `scripts/check_tests.sh` green vs `tests/known_failures.txt` (1 baselined).
- **CEF payload is a JS-call string** — tests unwrap with `_payload_data`, never `json.loads` on the raw string.

## File Structure

- `engine/ui/ship_property_viewer_panel.py` — Tasks 1 (value model/dispatch/payload) & 2 (gizmo + drag + guard).
- `native/src/renderer/gizmo_pass.{cc,h}`, `native/src/host/host_bindings.cc`, `engine/renderer.py`, `engine/host_loop.py` — Task 3.
- `native/assets/ui-cef/{index.html,css/ship_property_viewer.css,js/ship_property_viewer.js}` — Task 4.
- Tests under `tests/ui/`, `tests/host/`.

---

### Task 1: Scale value model, dispatch, and payload

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_panel_scale.py` (create)

**Interfaces:**
- Consumes: `_active_transform_target()`, `_effective_radius(i, baked)`, `_effective_light(i)`, `_pending_radius`, `_pending_light`, `dispatch_event`, `render_payload`.
- Produces: `SCALE_MIN`; `self._scale_clipboard`; `_scale_kind_and_fields`, `scale_values`, `_set_scale_field`; dispatch `scale_nudge`/`scale_copy`/`scale_paste`/`scale_uniform`; `"scale_values"` payload key + `_scale_clipboard` in snapshot.

- [ ] **Step 1: Write the failing tests**

```python
# tests/ui/test_ship_property_viewer_panel_scale.py
"""SPV scale tool: scale_values() + scale_* dispatch (shape-aware)."""
import json
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel


def _payload_data(payload):
    return json.loads(payload[payload.index("(") + 1:payload.rindex(")")])


def _panel_subsystem(radius=0.3):
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": radius},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
    }]
    p.dispatch_event("set_tool:scale")
    p.selected_index = 0
    return p


def _panel_light(shape, **spec):
    base = {"shape": shape, "position": (0.0, 1.0, 0.0), "axis": (0.0, -1.0, 0.0),
            "radius": (0.25,), "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25)}
    base.update(spec)
    p = _panel_subsystem()
    p._descriptors[0]["light"] = True
    p._descriptors[0]["light_region"] = base
    p.selected_index = None
    p._selected_light_index = 0
    return p


def test_scale_values_none_off_tool():
    p = _panel_subsystem()
    p.dispatch_event("set_tool:scale")   # toggle OFF
    assert p.scale_values() is None


def test_subsystem_scale_is_radius():
    p = _panel_subsystem(0.3)
    v = p.scale_values()
    assert v["kind"] == "radius"
    assert [f["label"] for f in v["fields"]] == ["Radius"]
    assert v["fields"][0]["value"] == 0.3


def test_box_scale_is_xyz():
    p = _panel_light("Box", scale=(0.15, 0.2, 0.05))
    v = p.scale_values()
    assert v["kind"] == "xyz"
    assert [f["value"] for f in v["fields"]] == [0.15, 0.2, 0.05]


def test_cylinder_scale_is_radius_length():
    p = _panel_light("Cylinder", radius=(0.3,), extent=(0.0, 2.0))
    v = p.scale_values()
    assert v["kind"] == "radius_length"
    assert [f["label"] for f in v["fields"]] == ["Radius", "Length"]
    assert v["fields"][1]["value"] == 2.0   # fore - aft


def test_scale_nudge_moves_only_that_field_and_floors():
    p = _panel_light("Box", scale=(0.15, 0.2, 0.05))
    p.dispatch_event('scale_nudge:' + json.dumps({"index": 1, "delta": 0.1}))
    assert round(p.scale_values()["fields"][1]["value"], 6) == 0.3
    # Floor: nudging the tiny Z far negative clamps at SCALE_MIN, not <= 0.
    p.dispatch_event('scale_nudge:' + json.dumps({"index": 2, "delta": -5.0}))
    from engine.ui.ship_property_viewer_panel import SCALE_MIN
    assert p.scale_values()["fields"][2]["value"] == SCALE_MIN


def test_scale_copy_paste_kind_matched():
    p = _panel_light("Box", scale=(0.15, 0.2, 0.05))
    p.dispatch_event("scale_copy")
    v = p.scale_values()
    assert v["has_clipboard"] is True and v["can_paste"] is True
    p.dispatch_event('scale_nudge:' + json.dumps({"index": 0, "delta": 0.5}))
    p.dispatch_event("scale_paste")
    assert [f["value"] for f in p.scale_values()["fields"]] == [0.15, 0.2, 0.05]


def test_scale_paste_disabled_across_kinds():
    p = _panel_light("Box", scale=(0.15, 0.2, 0.05))
    p.dispatch_event("scale_copy")           # clipboard kind = xyz
    q = _panel_light("Sphere", radius=(0.4,))
    q._scale_clipboard = p._scale_clipboard  # simulate shared clipboard
    v = q.scale_values()
    assert v["has_clipboard"] is True and v["can_paste"] is False


def test_scale_uniform_sets_box_axes_to_max():
    p = _panel_light("Box", scale=(0.15, 0.2, 0.05))
    p.dispatch_event("scale_uniform")
    assert [f["value"] for f in p.scale_values()["fields"]] == [0.2, 0.2, 0.2]


def test_scale_uniform_noop_on_sphere():
    p = _panel_light("Sphere", radius=(0.4,))
    assert p.dispatch_event("scale_uniform") is True
    assert p.scale_values()["fields"][0]["value"] == 0.4


def test_render_payload_carries_scale_values():
    p = _panel_light("Box", scale=(0.15, 0.2, 0.05))
    data = _payload_data(p.render_payload())
    assert data["scale_values"]["kind"] == "xyz"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel_scale.py -v`
Expected: FAIL (`AttributeError: ... 'scale_values'` / `SCALE_MIN`).

- [ ] **Step 3: Implement**

Add a module constant `SCALE_MIN = 0.01` (near the other SPV constants). Add `self._scale_clipboard = None` in `__init__`/`open`/`close` (beside `_coord_clipboard`). Add the methods:

```python
def _scale_kind_and_fields(self, target):
    kt, i = target
    if kt == "subsystem":
        r = self._effective_radius(i, self._descriptors[i].get("properties", {}).get("radius"))
        try:
            r = float(r)
        except (TypeError, ValueError):
            r = 0.0
        return "radius", [{"label": "Radius", "value": r}]
    spec = self._effective_light(i)
    if not spec:
        return "radius", [{"label": "Radius", "value": 0.0}]
    shape = spec.get("shape", "Sphere")
    if shape == "Box":
        sx, sy, sz = spec.get("scale", (0.25, 0.25, 0.25))
        return "xyz", [{"label": "X", "value": float(sx)},
                       {"label": "Y", "value": float(sy)},
                       {"label": "Z", "value": float(sz)}]
    if shape == "Cylinder":
        r = spec.get("radius", (0.25,))[0]
        aft, fore = spec.get("extent", (0.0, 2.0))
        return "radius_length", [{"label": "Radius", "value": float(r)},
                                 {"label": "Length", "value": float(fore) - float(aft)}]
    return "radius", [{"label": "Radius", "value": float(spec.get("radius", (0.25,))[0])}]

def scale_values(self):
    if self.active_tool != "scale":
        return None
    t = self._active_transform_target()
    if t is None:
        return None
    kind, fields = self._scale_kind_and_fields(t)
    clip = self._scale_clipboard
    return {"kind": kind, "fields": fields,
            "has_clipboard": clip is not None,
            "can_paste": clip is not None and clip[0] == kind}

def _set_scale_field(self, index, value):
    t = self._active_transform_target()
    if t is None:
        return
    value = max(SCALE_MIN, float(value))
    kt, i = t
    kind, fields = self._scale_kind_and_fields(t)
    if not (0 <= index < len(fields)):
        return
    if kt == "subsystem":
        self._pending_radius[i] = value
        self._last_pushed = None
        return
    spec = dict(self._effective_light(i) or {})
    if not spec:
        return
    shape = spec.get("shape", "Sphere")
    if shape == "Box":
        sc = list(spec.get("scale", (0.25, 0.25, 0.25)))
        sc[index] = value
        spec["scale"] = tuple(sc)
    elif shape == "Cylinder":
        if index == 0:
            spec["radius"] = (value,)
        else:
            aft = spec.get("extent", (0.0, 2.0))[0]
            spec["extent"] = (aft, aft + value)
    else:
        spec["radius"] = (value,)
    self._pending_light[i] = spec
    self._last_pushed = None
```

Dispatch cases (before `save`):

```python
if action.startswith("scale_nudge:"):
    try:
        arg = json.loads(action.split(":", 1)[1])
        index = int(arg["index"]); delta = float(arg["delta"])
    except (ValueError, KeyError, TypeError):
        return False
    t = self._active_transform_target()
    if t is None:
        return False
    kind, fields = self._scale_kind_and_fields(t)
    if not (0 <= index < len(fields)):
        return False
    self._set_scale_field(index, fields[index]["value"] + delta)
    return True
if action == "scale_copy":
    t = self._active_transform_target()
    if t is not None:
        kind, fields = self._scale_kind_and_fields(t)
        self._scale_clipboard = (kind, tuple(f["value"] for f in fields))
        self._last_pushed = None
    return True
if action == "scale_paste":
    t = self._active_transform_target()
    if t is not None and self._scale_clipboard is not None:
        kind, fields = self._scale_kind_and_fields(t)
        if self._scale_clipboard[0] == kind:
            for idx, v in enumerate(self._scale_clipboard[1]):
                self._set_scale_field(idx, v)
    return True
if action == "scale_uniform":
    t = self._active_transform_target()
    if t is not None:
        kind, fields = self._scale_kind_and_fields(t)
        if kind == "xyz":
            m = max(f["value"] for f in fields)
            for idx in range(3):
                self._set_scale_field(idx, m)
    return True
```

`render_payload`: add `"scale_values": self.scale_values()` to the dict, and add `self._scale_clipboard` to the `snapshot` tuple.

- [ ] **Step 4: Run to verify pass + regression**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel_scale.py tests/ui/test_ship_property_viewer_panel_coords.py tests/ui/test_ship_property_viewer_panel_gizmo.py tests/ui/test_ship_property_viewer_panel.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel_scale.py
git commit -m "feat(spv): shape-aware scale value model + dispatch (nudge/copy/paste/uniform)"
```

---

### Task 2: Scale gizmo + multiplicative drag + guard generalization

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_panel_scale.py` (extend)

**Interfaces:**
- Consumes: `transform_gizmo()`, `_handle_gizmo_input`, `_begin_axis_drag`/`_apply_axis_drag`/`_end_axis_drag`, `_axis_grab_origin`, `_active_transform_target`, `_set_scale_field`, `_scale_kind_and_fields`, `gizmo_length`, `pick_gizmo_axis`, `axis_drag_param`; the `over_coords` gate in `handle_input`.
- Produces: `scale_gizmo()`, `_active_gizmo()`, `transform_gizmo()` gains `"handle_kind": 0`; `_begin_scale_drag`/`_apply_scale_drag`; `_handle_gizmo_input` uses `_active_gizmo()` and dispatches drag by tool; the `over_coords` gate also fires for `scale_values()`.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/ui/test_ship_property_viewer_panel_scale.py
import pytest
from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui.ship_property_viewer import OrbitCamera


class _Ship:
    def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
    def GetWorldRotation(self): return TGMatrix3()


def _panel_box_gizmo():
    p = ShipPropertyViewerPanel(ship_getter=lambda: _Ship())
    p.open()
    p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": (0.0, 0.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 0.0, 0.0), "parent_index": None,
        "light": True,
        "light_region": {"shape": "Box", "position": (0.0, 0.0, 0.0),
                         "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
                         "extent": (0.0, 2.0), "scale": (0.2, 0.2, 0.2)},
    }]
    p.dispatch_event("set_tool:scale")
    p._selected_light_index = 0
    return p


def test_scale_gizmo_gate_and_handle_kind():
    p = _panel_box_gizmo()
    g = p.scale_gizmo()
    assert g is not None and g["handle_kind"] == 1
    assert p.transform_gizmo() is None          # wrong tool
    assert p._active_gizmo() is g or p._active_gizmo()["handle_kind"] == 1


def test_transform_gizmo_handle_kind_zero():
    p = _panel_box_gizmo()
    p.dispatch_event("set_tool:transform")
    assert p.transform_gizmo()["handle_kind"] == 0


def test_scale_drag_multiplies_box_axis():
    p = _panel_box_gizmo()
    # Grab X (axis 0) with grab param = length, then drag to 1.5x that param.
    from engine.ui.ship_property_viewer import gizmo_length
    L = gizmo_length(p.camera)
    p._begin_scale_drag(0, L)
    p._apply_scale_drag(1.5 * L)
    assert round(p.scale_values()["fields"][0]["value"], 6) == 0.3   # 0.2 * 1.5
    assert round(p.scale_values()["fields"][1]["value"], 6) == 0.2   # Y unchanged


def test_scale_drag_uniform_radius_on_sphere():
    p = _panel_box_gizmo()
    p._descriptors[0]["light_region"] = {"shape": "Sphere", "position": (0, 0, 0),
        "axis": (0, -1, 0), "radius": (0.4,), "extent": (0, 2), "scale": (0.25, 0.25, 0.25)}
    from engine.ui.ship_property_viewer import gizmo_length
    L = gizmo_length(p.camera)
    p._begin_scale_drag(2, L)          # any axis -> radius
    p._apply_scale_drag(2.0 * L)
    assert round(p.scale_values()["fields"][0]["value"], 6) == 0.8   # 0.4 * 2
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel_scale.py -k "gizmo or drag or handle_kind" -v`
Expected: FAIL (`AttributeError: ... 'scale_gizmo'`).

- [ ] **Step 3: Implement**

Add `"handle_kind": 0` to the dict `transform_gizmo()` returns. Add:

```python
def scale_gizmo(self):
    if self.active_tool != "scale" or self.camera is None:
        return None
    if self._active_transform_target() is None:
        return None
    ship = self._ship_getter()
    if ship is None or not hasattr(ship, "GetWorldRotation"):
        return None
    from engine.ui.ship_property_viewer import gizmo_axes, gizmo_length
    t = self._active_transform_target()
    kt, i = t
    if kt == "light":
        from engine.ui.ship_property_viewer import world_from_body
        origin = world_from_body(ship, self._effective_light(i)["position"])
    else:
        origin = self._effective_world_pos(i)
    return {"origin": origin, "axes": gizmo_axes(ship.GetWorldRotation()),
            "length": gizmo_length(self.camera), "highlight": self._gizmo_hover,
            "handle_kind": 1}

def _active_gizmo(self):
    if self.active_tool == "transform":
        return self.transform_gizmo()
    if self.active_tool == "scale":
        return self.scale_gizmo()
    return None

def _begin_scale_drag(self, axis, grab_param):
    self._axis_drag = axis
    self._axis_grab_param = grab_param
    g = self._active_gizmo()
    self._axis_grab_origin = g["origin"] if g else (0.0, 0.0, 0.0)
    t = self._active_transform_target()
    kind, fields = self._scale_kind_and_fields(t)
    if kind == "xyz":
        self._scale_grab = (axis, fields[axis]["value"])   # per-axis
    else:
        self._scale_grab = (0, fields[0]["value"])          # uniform -> field 0 (radius)

def _apply_scale_drag(self, t_now):
    if self._axis_drag is None:
        return
    from engine.ui.ship_property_viewer import gizmo_length
    L = gizmo_length(self.camera)
    ratio = t_now / max(self._axis_grab_param, 0.25 * L)
    idx, grab_val = self._scale_grab
    self._set_scale_field(idx, grab_val * ratio)
```

Initialise `self._scale_grab = (0, 0.0)` in `__init__`/`open`/`close`.

In `_handle_gizmo_input`, replace both `self.transform_gizmo()` reads with `self._active_gizmo()`, and dispatch grab/drag by tool:
- In the active-drag branch: after computing `t`, `if self.active_tool == "scale": self._apply_scale_drag(t)` else `self._apply_axis_drag(t)`.
- In the press-edge grab branch: after `t_grab = axis_drag_param(...)`, `if self.active_tool == "scale": self._begin_scale_drag(axis, t_grab)` else `self._begin_axis_drag(axis, t_grab)`. Keep the existing `self._axis_grab_origin` handling for the transform path (its `_begin_axis_drag` already sets it); `_begin_scale_drag` sets it for scale.

In `handle_input`, generalize the `over_coords` gate (added for the coord panel) so it also fires while the scale panel is up:
```python
over_coords = ((self.transform_coords() is not None or self.scale_values() is not None)
               and self._cursor_over_coords(x, y, dsf, fb_w, fb_h))
```

Add a test that the guard fires for scale (mirror the coord-panel guard test with the Scale tool active).

- [ ] **Step 4: Run to verify pass + regression**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel_scale.py tests/ui/test_ship_property_viewer_panel_gizmo.py tests/ui/test_ship_property_viewer_panel_coords.py tests/ui/test_ship_property_viewer_panel.py -v`
Expected: PASS (the transform gizmo drag + orbit/pin still green).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel_scale.py
git commit -m "feat(spv): scale gizmo accessor + multiplicative shape-aware drag"
```

---

### Task 3: Native cube-handle mode + gizmo push

**Files:**
- Modify: `native/src/renderer/include/renderer/gizmo_pass.h`, `native/src/renderer/gizmo_pass.cc`
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/renderer.py`
- Modify: `engine/host_loop.py`
- Test: `tests/host/test_transform_gizmo_binding.py` (extend)

**Interfaces:**
- Consumes: the `GizmoPass::Gizmo` struct + `render`, `set_transform_gizmo` binding, the `engine/renderer.py` wrapper, the host_loop SPV gizmo push.
- Produces: `Gizmo::handle_kind`; cube tips when `handle_kind==1`; `set_transform_gizmo(..., handle_kind)`; wrapper + push forward it; host_loop pushes `_active_gizmo()`.

- [ ] **Step 1: Extend the host test**

Add to `tests/host/test_transform_gizmo_binding.py`:
```python
def test_set_transform_gizmo_accepts_handle_kind():
    _h.set_transform_gizmo((0.0, 0.0, 0.0),
                           (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                           1.5, 1, 1)   # trailing handle_kind = cube
    _h.clear_transform_gizmo()
```

- [ ] **Step 2: Build + run to verify failure**

Run: `cmake --build build -j && uv run pytest tests/host/test_transform_gizmo_binding.py::test_set_transform_gizmo_accepts_handle_kind -v`
Expected: FAIL (binding takes 6 args, not 7).

- [ ] **Step 3: Implement native + wiring**

- `gizmo_pass.h`: add `int handle_kind{0};` to `Gizmo`.
- `gizmo_pass.cc`: read `native/src/renderer/gizmo_pass.cc`'s `render`. For each axis, when `g.handle_kind == 1` draw a small **cube** (12 `GL_LINES` edges of an axis-aligned box, side ≈ 0.12·length, centred at the axis tip `origin + axis*length`) instead of the cone; use a distinct scale colour (e.g. desaturated/brighter than the move colours). Keep the shaft line. `handle_kind == 0` keeps the existing cone.
- `host_bindings.cc` (~line 2517): add a 7th param `int handle_kind` to the `set_transform_gizmo` lambda + `py::arg("handle_kind")`, and set `g_transform_gizmo.handle_kind = handle_kind;`. (Give it no default so callers pass it explicitly; the Python wrapper supplies it.)
- `engine/renderer.py` (`set_transform_gizmo` wrapper): add a `handle_kind=0` param and forward it: `fn(origin, ax, ay, az, float(length), int(highlight), int(handle_kind))`.
- `engine/host_loop.py` (~line 7345): change `_gizmo = ship_property_viewer.transform_gizmo()` to `_gizmo = ship_property_viewer._active_gizmo()`, and pass the kind:
  ```python
  r.set_transform_gizmo((ox, oy, oz), ax, ay, az,
                        _gizmo["length"], _gizmo["highlight"],
                        _gizmo.get("handle_kind", 0))
  ```

- [ ] **Step 4: Build + run test + gate**

Run: `cmake --build build -j && uv run pytest tests/host/test_transform_gizmo_binding.py -v && ctest --test-dir build --output-on-failure | tail -3`
Expected: PASS; ctest no new failures.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/gizmo_pass.h native/src/renderer/gizmo_pass.cc native/src/host/host_bindings.cc engine/renderer.py engine/host_loop.py tests/host/test_transform_gizmo_binding.py
git commit -m "feat(spv): cube-handle gizmo mode for Scale + active-gizmo push"
```

---

### Task 4: CEF scale panel

**Files:**
- Modify: `native/assets/ui-cef/index.html`, `native/assets/ui-cef/css/ship_property_viewer.css`, `native/assets/ui-cef/js/ship_property_viewer.js`
- Test: none automated (CEF DOM verified in-game); panel state covered by Task 1.

**Interfaces:**
- Consumes: `payload.scale_values` (`{kind, fields:[{label,value}], has_clipboard, can_paste}` or null); the `dauntlessEvent` channel; `setShipPropertyViewer`.
- Produces: `#spv-scale` panel; `shipPropertyViewerScaleNudge(index, delta)` / `...ScaleCopy|Paste|Uniform`; render-apply that builds the dynamic rows, shows/hides the panel, gates Paste, and suppresses the popover when either transform OR scale panel is up.

- [ ] **Step 1: Add `#spv-scale` to `index.html`**

Near `#spv-coords`, add a sibling with the SAME top-right geometry (it reuses `.spv-coords*` structure but its rows are built by JS):
```html
<!-- Scale panel (top-right). Shown only while the Scale tool is active and
     something is selected; rows are shape-aware (built from scale_values.fields).
     Shares the top-right slot with #spv-coords (radio: never both). -->
<div id="spv-scale" class="spv-coords dev-only" style="display:none;">
  <div class="spv-coords__title">Scale</div>
  <div id="spv-scale-rows"></div>
  <div class="spv-coords__actions">
    <button class="spv-coords__btn" onclick="shipPropertyViewerScaleCopy()">Copy</button>
    <button id="spv-scale-paste" class="spv-coords__btn" onclick="shipPropertyViewerScalePaste()">Paste</button>
    <button class="spv-coords__btn" onclick="shipPropertyViewerScaleUniform()">Uniform</button>
  </div>
</div>
```

- [ ] **Step 2: JS handlers + dynamic-row render**

Add handlers (mirror the coord handlers' `dauntlessEvent` idiom):
```javascript
window.shipPropertyViewerScaleNudge = function (index, delta) {
    dauntlessEvent('ship-property-viewer/scale_nudge:' + JSON.stringify({index: index, delta: delta}));
};
window.shipPropertyViewerScaleCopy = function () { dauntlessEvent('ship-property-viewer/scale_copy'); };
window.shipPropertyViewerScalePaste = function () { dauntlessEvent('ship-property-viewer/scale_paste'); };
window.shipPropertyViewerScaleUniform = function () { dauntlessEvent('ship-property-viewer/scale_uniform'); };
```

In `setShipPropertyViewer`, after the coord-panel block, add a scale block that builds one row per field:
```javascript
var scale = data.scale_values;
var scaleEl = document.getElementById('spv-scale');
if (scaleEl) {
    if (scale) {
        var rows = scale.fields.map(function (f, i) {
            return '<div class="spv-coords__row">'
                 + '<span class="spv-coords__axis">' + escapeHtmlSPV(f.label) + '</span>'
                 + '<button class="spv-step" onclick="shipPropertyViewerScaleNudge(' + i + ',-0.1)">&minus;0.1</button>'
                 + '<button class="spv-step" onclick="shipPropertyViewerScaleNudge(' + i + ',-0.01)">&minus;0.01</button>'
                 + '<span class="spv-coords__val">' + f.value.toFixed(3) + '</span>'
                 + '<button class="spv-step" onclick="shipPropertyViewerScaleNudge(' + i + ',0.01)">+0.01</button>'
                 + '<button class="spv-step" onclick="shipPropertyViewerScaleNudge(' + i + ',0.1)">+0.1</button>'
                 + '</div>';
        }).join('');
        document.getElementById('spv-scale-rows').innerHTML = rows;
        var sp = document.getElementById('spv-scale-paste');
        sp.disabled = !scale.can_paste;
        sp.classList.toggle('spv-coords__btn--disabled', !scale.can_paste);
        scaleEl.style.display = 'block';
    } else {
        scaleEl.style.display = 'none';
    }
}
```

(Label text comes from `f.label` — X/Y/Z, Radius, Length — so the same markup serves every shape. The nudge labels stay `∓0.1/∓0.01/+0.01/+0.1`; if a field wants finer control later that's a follow-up.)

- [ ] **Step 3: Popover suppression + CSS**

- In `setShipPropertyViewer`, the popover branch (already `if (data.selected && !data.transform_coords)`) → change to `if (data.selected && !data.transform_coords && !data.scale_values)` so the popover also steps aside for the scale panel.
- CSS: `#spv-scale` reuses the `.spv-coords*` rules (it already carries `class="spv-coords"`), so no new geometry rule is needed — it inherits `right:12/top:46/width:220`. Confirm the shared `.spv-coords .spv-step` shrink still applies (it's an id-scoped `#spv-coords .spv-step` rule from the coord task — if so, add `#spv-scale .spv-step` with the same shrink, or broaden that selector to `.spv-coords .spv-step`). Keep width 220 so the click-guard (COORDS_W_PT) still matches.

- [ ] **Step 4: Build + gate**

Run: `scripts/check_tests.sh`
Expected: "OK — no new failures. 1 known failure(s) still baselined."

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/css/ship_property_viewer.css native/assets/ui-cef/js/ship_property_viewer.js
git commit -m "feat(spv): CEF shape-aware scale panel (steppers + Copy/Paste/Uniform)"
```

---

## Self-Review

**Spec coverage:** shape-aware size model + rows (Task 1 `_scale_kind_and_fields`/`scale_values`), nudge/copy/paste/uniform (Task 1 dispatch + Task 4 buttons), kind-matched paste (Task 1 `can_paste`), Uniform=max box (Task 1), scale gizmo + cube handles + multiplicative shape-aware drag (Tasks 2+3), guard + popover generalization (Tasks 2+4), persistence via existing radius/light paths (Task 1 `_set_scale_field`), one-panel-at-a-time (radio, Tasks 2+4).

**Placeholder scan:** every code step carries real code; native cube-render and the CSS shrink point at concrete existing structures to mirror.

**Type consistency:** `scale_values()` shape (`kind`/`fields[{label,value}]`/`has_clipboard`/`can_paste`) matches the Task-4 consumer; `scale_nudge` JSON (`index`/`delta`) matches producer/consumer; `_active_gizmo()`/`scale_gizmo()` dict adds `handle_kind` consumed by Task 3's host_loop push and the extended `set_transform_gizmo(..., handle_kind)` binding/wrapper; `_scale_kind_and_fields` reused by dispatch, drag (Task 2), and payload.
