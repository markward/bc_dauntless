# SPV Transform Coordinate Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A top-right SPV panel, shown while transforming, that lists the selected element's XYZ on mouse-only nudge steppers with Copy/Paste/Mirror, all staging into the same pending position the gizmo uses.

**Architecture:** Panel state + dispatch in `engine/ui/ship_property_viewer_panel.py` reusing the gizmo's transform-target plumbing; a click-guard for the new top-right region; a CEF panel driven off a `transform_coords` payload field. No host-loop or native change.

**Tech Stack:** Python 3 (engine), CEF (HTML/CSS/JS), pytest.

## Global Constraints

- **Developer-only, production byte-identical.** All new state/UI is reachable only under `--developer` with the SPV open. `transform_coords()` returns `None` unless the Transform tool is active AND a subsystem/light node is selected.
- **Mouse-only.** Nudge steppers and Copy/Paste/Mirror are CEF button clicks.
- **Mirror negates X** (port/starboard), not Y.
- **In-SPV clipboard** — a Python variable (`_coord_clipboard`), session-scoped, reset on open/close.
- **Staged + Save/confirm.** Every edit routes through `set_subsystem_position` / `set_light_position` into `_pending_pos` / `_pending_light`, saved by the existing flow. Nothing new touches persistence.
- **Shared checkout.** Explicit pathspecs only. Never `git add -A`/`checkout`/`restore`/`stash`/`reset --hard`/`clean`.
- **Test gate.** `scripts/check_tests.sh` stays green against `tests/known_failures.txt` (1 baselined `engineer_emitters`).
- **CEF payload is a JS-call string.** `render_payload()` returns `setShipPropertyViewer({...});` — tests unwrap with the `_payload_data` helper from `tests/ui/test_ship_property_viewer_panel.py`, never `json.loads` on the raw string.
- **Panel geometry constants must match** between the Python click-guard (Task 2) and the CEF CSS (Task 3): `right:12px  top:46px  width:220px  height≈172px`.

## File Structure

- `engine/ui/ship_property_viewer_panel.py` — Tasks 1 (state/dispatch/payload) & 2 (click-guard).
- `native/assets/ui-cef/{index.html,css/ship_property_viewer.css,js/ship_property_viewer.js}` — Task 3.
- Tests under `tests/ui/`.

---

### Task 1: Panel state, dispatch, and `transform_coords` payload

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_panel_coords.py` (create)

**Interfaces:**
- Consumes: `_active_transform_target()`, `_effective_pos(i)`, `_effective_light(i)`, `set_subsystem_position(i,xyz)`, `set_light_position(i,xyz)`, `active_tool`, `render_payload` snapshot/dict, `dispatch_event`.
- Produces: `self._coord_clipboard`; `_transform_target_pos()`, `_set_transform_target_pos(xyz)`, `transform_coords()`; dispatch cases `coord_nudge:`/`coord_copy`/`coord_paste`/`coord_mirror`; `"transform_coords"` payload key + `_coord_clipboard` in the snapshot.

- [ ] **Step 1: Write the failing tests**

```python
# tests/ui/test_ship_property_viewer_panel_coords.py
"""SPV transform coordinate panel: transform_coords() + coord_* dispatch."""
import json
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel


def _payload_data(payload):
    # payload is "setShipPropertyViewer({...});" — slice the JSON argument.
    start = payload.index("(") + 1
    end = payload.rindex(")")
    return json.loads(payload[start:end])


def _panel_subsystem(baked_pos=(0.0, 1.0, 0.0)):
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Center Impulse", "kind": "subsystem",
        "properties": {"position": baked_pos, "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None,
    }]
    p.dispatch_event("set_tool:transform")
    p.selected_index = 0
    return p


def _panel_light(baked_pos=(0.0, 1.0, 0.0)):
    p = _panel_subsystem(baked_pos)
    p._descriptors[0]["light"] = True
    p._descriptors[0]["light_region"] = {
        "shape": "Sphere", "position": baked_pos, "axis": (0.0, -1.0, 0.0),
        "radius": (0.25,), "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25)}
    p.selected_index = None
    p._selected_light_index = 0
    return p


def test_transform_coords_none_off_tool():
    p = _panel_subsystem()
    p.dispatch_event("set_tool:transform")   # toggles OFF (already transform)
    assert p.active_tool is None
    assert p.transform_coords() is None


def test_transform_coords_none_without_selection():
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p.dispatch_event("set_tool:transform")
    assert p.transform_coords() is None


def test_transform_coords_reports_subsystem_xyz():
    p = _panel_subsystem((0.1, 2.3, -0.4))
    c = p.transform_coords()
    assert (c["x"], c["y"], c["z"]) == (0.1, 2.3, -0.4)
    assert c["has_clipboard"] is False


def test_coord_nudge_moves_only_that_axis():
    p = _panel_subsystem((0.0, 1.0, 0.0))
    assert p.dispatch_event('coord_nudge:' + json.dumps({"axis": 1, "delta": -0.1})) is True
    c = p.transform_coords()
    assert round(c["y"], 6) == 0.9 and c["x"] == 0.0 and c["z"] == 0.0


def test_coord_nudge_on_light_target():
    p = _panel_light((0.0, 1.0, 0.0))
    p.dispatch_event('coord_nudge:' + json.dumps({"axis": 0, "delta": 0.5}))
    assert round(p.transform_coords()["x"], 6) == 0.5


def test_coord_copy_then_paste_roundtrips():
    p = _panel_subsystem((1.0, 2.0, 3.0))
    assert p.dispatch_event("coord_copy") is True
    assert p.transform_coords()["has_clipboard"] is True
    # move away, then paste restores
    p.dispatch_event('coord_nudge:' + json.dumps({"axis": 0, "delta": 5.0}))
    assert p.transform_coords()["x"] == 6.0
    p.dispatch_event("coord_paste")
    c = p.transform_coords()
    assert (c["x"], c["y"], c["z"]) == (1.0, 2.0, 3.0)


def test_coord_paste_noop_without_clipboard():
    p = _panel_subsystem((1.0, 2.0, 3.0))
    assert p.dispatch_event("coord_paste") is True   # handled, but no change
    c = p.transform_coords()
    assert (c["x"], c["y"], c["z"]) == (1.0, 2.0, 3.0)


def test_coord_mirror_negates_x_only():
    p = _panel_subsystem((0.065, -1.25, -0.17))
    p.dispatch_event("coord_mirror")
    c = p.transform_coords()
    assert round(c["x"], 6) == -0.065
    assert round(c["y"], 6) == -1.25 and round(c["z"], 6) == -0.17


def test_render_payload_carries_coords_and_clipboard():
    p = _panel_subsystem((0.0, 1.0, 0.0))
    data = _payload_data(p.render_payload())
    assert data["transform_coords"]["y"] == 1.0
    assert data["transform_coords"]["has_clipboard"] is False
    p.dispatch_event("coord_copy")
    data2 = _payload_data(p.render_payload())   # snapshot changed -> re-push
    assert data2 is not None
    assert data2["transform_coords"]["has_clipboard"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel_coords.py -v`
Expected: FAIL (`AttributeError: ... 'transform_coords'`).

- [ ] **Step 3: Implement**

In `__init__`, `open()`, `close()` add `self._coord_clipboard = None` (beside `_pending_pos`). Add the methods (near `transform_gizmo`):

```python
def _transform_target_pos(self):
    t = self._active_transform_target()
    if t is None:
        return None
    kind, i = t
    if kind == "light":
        spec = self._effective_light(i)
        if not spec:
            return None
        return tuple(float(c) for c in spec["position"])
    return tuple(float(c) for c in self._effective_pos(i))

def _set_transform_target_pos(self, xyz):
    t = self._active_transform_target()
    if t is None:
        return
    kind, i = t
    if kind == "light":
        self.set_light_position(i, xyz)
    else:
        self.set_subsystem_position(i, xyz)

def transform_coords(self):
    if self.active_tool != "transform":
        return None
    pos = self._transform_target_pos()
    if pos is None:
        return None
    return {"x": pos[0], "y": pos[1], "z": pos[2],
            "has_clipboard": self._coord_clipboard is not None}
```

Add the dispatch cases (place before the `save` case):

```python
if action.startswith("coord_nudge:"):
    try:
        arg = json.loads(action.split(":", 1)[1])
        axis = int(arg["axis"]); delta = float(arg["delta"])
    except (ValueError, KeyError, TypeError):
        return False
    if axis not in (0, 1, 2):
        return False
    pos = self._transform_target_pos()
    if pos is None:
        return False
    p = list(pos); p[axis] += delta
    self._set_transform_target_pos(tuple(p))
    self._last_pushed = None
    return True
if action == "coord_copy":
    pos = self._transform_target_pos()
    if pos is not None:
        self._coord_clipboard = pos
        self._last_pushed = None
    return True
if action == "coord_paste":
    if self._coord_clipboard is not None and self._transform_target_pos() is not None:
        self._set_transform_target_pos(self._coord_clipboard)
        self._last_pushed = None
    return True
if action == "coord_mirror":
    pos = self._transform_target_pos()
    if pos is not None:
        p = list(pos); p[0] = -p[0]
        self._set_transform_target_pos(tuple(p))
        self._last_pushed = None
    return True
```

In `render_payload`: add `"transform_coords": self.transform_coords()` to the payload dict, and add `self._coord_clipboard` to the `snapshot` tuple.

- [ ] **Step 4: Run to verify pass + regression**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel_coords.py tests/ui/test_ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel_gizmo.py tests/ui/test_ship_property_viewer_panel_position.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel_coords.py
git commit -m "feat(spv): transform coordinate panel state (nudge/copy/paste/mirror)"
```

---

### Task 2: Click-guard for the top-right coord panel

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_panel.py` (extend)

**Interfaces:**
- Consumes: the `TOOLS_*`/`TITLEBAR_H_PT` constants block; `_cursor_over_chrome`; `handle_input`'s `over_chrome` computation.
- Produces: `COORDS_MARGIN_PT`/`COORDS_TOP_PT`/`COORDS_W_PT`/`COORDS_H_PT`; `_cursor_over_coords(x, y, dsf, fb_w, fb_h)`; inclusion in `handle_input`'s chrome guard.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/ui/test_ship_property_viewer_panel.py
def test_cursor_over_coords_guards_top_right_box():
    _mod = __import__("engine.ui.ship_property_viewer_panel",
                      fromlist=["ShipPropertyViewerPanel"])
    fb_w, fb_h, dsf = 800.0, 600.0, 1.0
    # A point inside the top-right coords box.
    x_in = fb_w - _mod.COORDS_MARGIN_PT - 20
    y_in = _mod.COORDS_TOP_PT + 20
    assert _mod.ShipPropertyViewerPanel._cursor_over_coords(x_in, y_in, dsf, fb_w, fb_h) is True
    # A point in the centre (not the box).
    assert _mod.ShipPropertyViewerPanel._cursor_over_coords(
        fb_w/2, fb_h/2, dsf, fb_w, fb_h) is False
    # Unknown viewport → False.
    assert _mod.ShipPropertyViewerPanel._cursor_over_coords(
        x_in, y_in, dsf, 0.0, 0.0) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel.py::test_cursor_over_coords_guards_top_right_box -v`
Expected: FAIL (`AttributeError: ... 'COORDS_MARGIN_PT'` / `_cursor_over_coords`).

- [ ] **Step 3: Implement**

Add constants near the `TOOLS_*` block:

```python
# Top-right transform coordinate panel (#spv-coords). Anchored right:12/top:46
# with width 220 / height ~172 (three coord rows + Copy/Paste/Mirror). Clicks
# here belong to the CEF panel, so they never start an orbit or gizmo drag.
COORDS_MARGIN_PT = 12
COORDS_TOP_PT = 46
COORDS_W_PT = 220
COORDS_H_PT = 172
```

Add the guard (staticmethod, beside `_cursor_over_tools`):

```python
@staticmethod
def _cursor_over_coords(x: float, y: float, dsf: float,
                        fb_w: float, fb_h: float) -> bool:
    """Cursor (framebuffer px) inside the top-right coord panel box. Returns
    False when the viewport width is unknown."""
    if fb_w <= 0:
        return False
    s = dsf or 1.0
    px, py = x / s, y / s
    w_pt = fb_w / s
    x1 = w_pt - COORDS_MARGIN_PT
    x0 = x1 - COORDS_W_PT
    y0 = COORDS_TOP_PT
    y1 = y0 + COORDS_H_PT
    return x0 <= px <= x1 and y0 <= py <= y1
```

In `handle_input`, where `over_chrome` is computed (currently
`over_chrome = self._cursor_over_chrome(x, y, dsf) or over_tools`), also OR in
the coords box:

```python
over_coords = self._cursor_over_coords(x, y, dsf, fb_w, fb_h)
over_chrome = self._cursor_over_chrome(x, y, dsf) or over_tools or over_coords
```

(`fb_w`/`fb_h` are already computed earlier in `handle_input` for `_cursor_over_tools`.)

- [ ] **Step 4: Run to verify pass + regression**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel.py
git commit -m "feat(spv): click-guard the top-right coord panel region"
```

---

### Task 3: CEF coordinate panel

**Files:**
- Modify: `native/assets/ui-cef/index.html`
- Modify: `native/assets/ui-cef/css/ship_property_viewer.css`
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js`
- Test: none automated (CEF DOM verified in-game); panel state is covered by Task 1.

**Interfaces:**
- Consumes: `payload.transform_coords` (`{x,y,z,has_clipboard}` or `null`) from Task 1; the `dauntlessEvent('ship-property-viewer/<action>')` channel used by the existing toggles/tools; the render-apply function `setShipPropertyViewer`.
- Produces: `#spv-coords` panel; `shipPropertyViewerCoordNudge(axis, delta)` / `shipPropertyViewerCoordCopy|Paste|Mirror`; render-apply that shows/hides + fills the panel and enables/disables Paste.

- [ ] **Step 1: Add the panel to `index.html`**

Inside `#spv-root` (near the other SPV overlays, e.g. after `#spv-tools`), add:

```html
<!-- Transform coordinate panel (top-right). Shown only while the Transform
     tool is active and something is selected; driven by payload.transform_coords.
     Mouse-only steppers (no keyboard->CEF). -->
<div id="spv-coords" class="spv-coords dev-only" style="display:none;">
  <div class="spv-coords__title">Position</div>
  <div class="spv-coords__row">
    <span class="spv-coords__axis">X</span>
    <button class="spv-step" onclick="shipPropertyViewerCoordNudge(0,-0.1)">&minus;0.1</button>
    <button class="spv-step" onclick="shipPropertyViewerCoordNudge(0,-0.01)">&minus;0.01</button>
    <span id="spv-coord-x" class="spv-coords__val">0.00</span>
    <button class="spv-step" onclick="shipPropertyViewerCoordNudge(0,0.01)">+0.01</button>
    <button class="spv-step" onclick="shipPropertyViewerCoordNudge(0,0.1)">+0.1</button>
  </div>
  <div class="spv-coords__row">
    <span class="spv-coords__axis">Y</span>
    <button class="spv-step" onclick="shipPropertyViewerCoordNudge(1,-0.1)">&minus;0.1</button>
    <button class="spv-step" onclick="shipPropertyViewerCoordNudge(1,-0.01)">&minus;0.01</button>
    <span id="spv-coord-y" class="spv-coords__val">0.00</span>
    <button class="spv-step" onclick="shipPropertyViewerCoordNudge(1,0.01)">+0.01</button>
    <button class="spv-step" onclick="shipPropertyViewerCoordNudge(1,0.1)">+0.1</button>
  </div>
  <div class="spv-coords__row">
    <span class="spv-coords__axis">Z</span>
    <button class="spv-step" onclick="shipPropertyViewerCoordNudge(2,-0.1)">&minus;0.1</button>
    <button class="spv-step" onclick="shipPropertyViewerCoordNudge(2,-0.01)">&minus;0.01</button>
    <span id="spv-coord-z" class="spv-coords__val">0.00</span>
    <button class="spv-step" onclick="shipPropertyViewerCoordNudge(2,0.01)">+0.01</button>
    <button class="spv-step" onclick="shipPropertyViewerCoordNudge(2,0.1)">+0.1</button>
  </div>
  <div class="spv-coords__actions">
    <button class="spv-coords__btn" onclick="shipPropertyViewerCoordCopy()">Copy</button>
    <button id="spv-coord-paste" class="spv-coords__btn" onclick="shipPropertyViewerCoordPaste()">Paste</button>
    <button class="spv-coords__btn" onclick="shipPropertyViewerCoordMirror()">Mirror</button>
  </div>
</div>
```

- [ ] **Step 2: Add the JS handlers + render-apply**

In `js/ship_property_viewer.js`:

```javascript
window.shipPropertyViewerCoordNudge = function (axis, delta) {
    dauntlessEvent('ship-property-viewer/coord_nudge:' + JSON.stringify({axis: axis, delta: delta}));
};
window.shipPropertyViewerCoordCopy = function () {
    dauntlessEvent('ship-property-viewer/coord_copy');
};
window.shipPropertyViewerCoordPaste = function () {
    dauntlessEvent('ship-property-viewer/coord_paste');
};
window.shipPropertyViewerCoordMirror = function () {
    dauntlessEvent('ship-property-viewer/coord_mirror');
};
```

(Use whatever helper the existing `shipPropertyViewerToggle`/`shipPropertyViewerSetTool` uses to fire events — mirror it exactly.)

In `setShipPropertyViewer` (the render-apply function), after the existing tool/button state, add:

```javascript
var coords = data.transform_coords;
var coordsEl = document.getElementById('spv-coords');
if (coords) {
    document.getElementById('spv-coord-x').textContent = coords.x.toFixed(3);
    document.getElementById('spv-coord-y').textContent = coords.y.toFixed(3);
    document.getElementById('spv-coord-z').textContent = coords.z.toFixed(3);
    var pasteBtn = document.getElementById('spv-coord-paste');
    pasteBtn.disabled = !coords.has_clipboard;
    pasteBtn.classList.toggle('spv-coords__btn--disabled', !coords.has_clipboard);
    coordsEl.style.display = 'block';
} else {
    coordsEl.style.display = 'none';
}
```

(Match the exact place/idiom where the render-apply reads other `data.*` fields; `data` is whatever variable that function already binds the payload to.)

- [ ] **Step 3: Style `#spv-coords` in the CSS**

In `css/ship_property_viewer.css`, add rules matching the Task-2 geometry
constants exactly (`right:12px; top:46px; width:220px`; total height ≈ 172px):

```css
#spv-coords {
  position: absolute;
  right: 12px;
  top: 46px;
  width: 220px;
  padding: 8px 10px;
  box-sizing: border-box;
  background: rgba(0, 0, 0, 0.55);
  border: 1px solid rgba(255, 230, 160, 0.4);
  color: #ffd;
  pointer-events: auto;
  font-size: 12px;
}
.spv-coords__title { font-weight: bold; margin-bottom: 6px; }
.spv-coords__row { display: flex; align-items: center; gap: 4px; margin-bottom: 4px; }
.spv-coords__axis { width: 12px; color: #ffd; }
.spv-coords__val { flex: 1; text-align: center; font-variant-numeric: tabular-nums; }
.spv-coords__actions { display: flex; gap: 6px; margin-top: 8px; }
.spv-coords__btn { flex: 1; cursor: pointer; background: rgba(0,0,0,0.35);
  border: 1px solid rgba(255,230,160,0.4); color: #ffd; padding: 4px 0; }
.spv-coords__btn--disabled { opacity: 0.4; pointer-events: none; }
```

Reuse the existing `.spv-step` rule for the nudge buttons (it already styles the
radius stepper). If `.spv-step` sizing makes the panel wider than 220px, shrink
its padding within `#spv-coords` or bump `COORDS_W_PT` (Task 2) AND `width` here
together so the click-guard still matches — keep the two numbers equal.

- [ ] **Step 4: Verify build + gate**

Run: `scripts/check_tests.sh`
Expected: "OK — no new failures. 1 known failure(s) still baselined." (CEF assets load from source; no native change.)

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/css/ship_property_viewer.css native/assets/ui-cef/js/ship_property_viewer.js
git commit -m "feat(spv): CEF transform coordinate panel (steppers + Copy/Paste/Mirror)"
```

---

## Self-Review

**Spec coverage:** panel visibility gate (Task 1 `transform_coords`), XYZ steppers (Tasks 1+3), Copy/Paste/Mirror (Task 1 dispatch + Task 3 buttons), Mirror=X (Task 1), in-SPV clipboard + Paste-enable (Task 1 `has_clipboard` + Task 3 disable), live preview via shared pending position (Task 1 reuses gizmo setters), click-guard (Task 2), top-right placement (Tasks 2+3 matched constants).

**Placeholder scan:** every code step carries real code; the only "match the existing idiom" notes point at concrete existing symbols (`shipPropertyViewerToggle`, the render-apply `data` binding, `.spv-step`).

**Type consistency:** `transform_coords()` dict shape (`x/y/z/has_clipboard`) matches the Task-3 consumer; `coord_nudge` JSON (`axis`/`delta`) matches producer (JS) and consumer (dispatch); `_transform_target_pos`/`_set_transform_target_pos` reuse the gizmo's `_active_transform_target`/`_effective_pos`/`_effective_light`/`set_subsystem_position`/`set_light_position` (all present on the branch); `COORDS_*` constants shared by Task 2 (guard) and Task 3 (CSS).
