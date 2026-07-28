# SPV Light-Type Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The "Edit Light…" modal becomes a light-**type** picker (shape only), reused for Add Light. Edit keeps the element's size/pos/axis/orientation and only swaps shape; Add stages a light of the chosen shape and selects it.

**Architecture:** Python dispatch changes (`set_light` shape-only, `add_light` gains a shape) + a CEF modal reduced to shape buttons with an add/edit mode flag. No persistence/render change.

**Tech Stack:** Python 3, CEF (HTML/JS), pytest.

## Global Constraints

- **Developer-only, mouse-only.** No change to Scale/Rotate, persistence, or the render path.
- **Edit shape-change preserves** the element's radius/extent/scale/position/axis/orientation — only `shape` changes.
- **Same modal for Add + Edit**, routed by a `spvLightMode` flag.
- **Backward-compat**: `add_light` still accepts a bare-int payload (defaults shape to the base spec's shape).
- **Shared checkout.** Explicit pathspecs only. Never `git add -A`/`checkout`/`restore`/`stash`/`reset --hard`/`clean`. Do NOT stage `engine/appc/hardpoint_overrides.py`.
- **Test gate.** `scripts/check_tests.sh` green vs `tests/known_failures.txt` (1 baselined).
- **CEF payload is a JS-call string** — panel tests unwrap with `_payload_data`, never `json.loads` on the raw string.

## File Structure

- `engine/ui/ship_property_viewer_panel.py` — Task 1 (`set_light`/`add_light` dispatch).
- `native/assets/ui-cef/{index.html,js/ship_property_viewer.js}` — Task 2 (modal + mode flag).
- Tests under `tests/ui/`.

---

### Task 1: Panel dispatch — `set_light` shape-only, `add_light` gains shape

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_panel.py` (extend) or a new `tests/ui/test_ship_property_viewer_panel_light_modal.py` (create)

**Interfaces:**
- Consumes: `_effective_light`, `_descriptors[i]["light_region"]`, `_has_light`, `_pending_light`, `_selected_light_index`, `_expanded_groups`, `dispatch_event`.
- Produces: `set_light:` accepts `{"i", "shape"}` (shape-only, preserves size/pos/axis/orientation); `add_light:` accepts `{"i", "shape"}` (or bare int) and stages a light of that shape.

- [ ] **Step 1: Write the failing tests**

```python
# tests/ui/test_ship_property_viewer_panel_light_modal.py
"""SPV light-type modal dispatch: set_light shape-only, add_light gains shape."""
import json
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel


def _panel_with_light(shape="Cylinder", radius=(0.3,), extent=(-2.0, 2.0),
                      scale=(0.2, 0.3, 0.4)):
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Port Warp", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None, "light": True,
        "light_region": {"shape": shape, "position": (0.1, 1.0, 0.2),
                         "axis": (0.0, -1.0, 0.0), "radius": radius,
                         "extent": extent, "scale": scale,
                         "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))},
    }]
    p._selected_light_index = 0
    return p


def _panel_no_light():
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Hull", "kind": "subsystem",
        "properties": {"position": (0.0, 0.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 0.0, 0.0), "parent_index": None, "light": False,
        # from-scratch default spec (Sphere), as _light_annotation attaches:
        "light_region": {"shape": "Sphere", "position": (0.0, 0.0, 0.0),
                         "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
                         "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25),
                         "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))},
    }]
    return p


def test_set_light_changes_only_shape_preserves_size():
    p = _panel_with_light(shape="Cylinder", radius=(0.3,), extent=(-2.0, 2.0),
                          scale=(0.2, 0.3, 0.4))
    assert p.dispatch_event('set_light:' + json.dumps({"i": 0, "shape": "Box"})) is True
    spec = p._effective_light(0)
    assert spec["shape"] == "Box"
    # every non-shape field preserved
    assert spec["radius"] == (0.3,)
    assert spec["extent"] == (-2.0, 2.0)
    assert spec["scale"] == (0.2, 0.3, 0.4)
    assert spec["position"] == (0.1, 1.0, 0.2)
    assert spec["orientation"] == ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def test_set_light_rejects_unknown_shape():
    p = _panel_with_light()
    assert p.dispatch_event('set_light:' + json.dumps({"i": 0, "shape": "Blob"})) is False


def test_add_light_stages_chosen_shape_and_selects():
    p = _panel_no_light()
    assert p.dispatch_event('add_light:' + json.dumps({"i": 0, "shape": "Cylinder"})) is True
    assert p._selected_light_index == 0
    assert p.selected_index is None
    assert p._effective_light(0)["shape"] == "Cylinder"


def test_add_light_bare_int_still_works():
    p = _panel_no_light()
    assert p.dispatch_event("add_light:0") is True     # legacy payload
    assert p._selected_light_index == 0
    assert p._effective_light(0)["shape"] == "Sphere"  # base spec's own shape


def test_add_light_guarded_when_already_lit():
    p = _panel_with_light()
    assert p.dispatch_event('add_light:' + json.dumps({"i": 0, "shape": "Box"})) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel_light_modal.py -v`
Expected: FAIL (`set_light` with no size args currently returns False on the `float(arg["radius"])` KeyError path; `add_light` with a JSON payload fails the `int(...)` parse).

- [ ] **Step 3: Implement**

Replace the `set_light:` dispatch body with a shape-only version:
```python
if action.startswith("set_light:"):
    try:
        arg = json.loads(action.split(":", 1)[1])
        idx = int(arg["i"]); shape = str(arg["shape"])
    except (ValueError, KeyError, TypeError):
        return False
    if not (0 <= idx < len(self._descriptors)) or shape not in ("Sphere", "Cylinder", "Box"):
        return False
    base = dict(self._effective_light(idx)
                or self._descriptors[idx].get("light_region") or {})
    spec = {"shape": shape,
            "position": tuple(base.get("position") or (0.0, 0.0, 0.0)),
            "axis": tuple(base.get("axis") or (0.0, -1.0, 0.0)),
            "radius": base.get("radius") or (0.25,),
            "extent": base.get("extent") or (0.0, 2.0),
            "scale": base.get("scale") or (0.25, 0.25, 0.25),
            "orientation": base.get("orientation") or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))}
    self._pending_light[idx] = spec
    self._last_pushed = None
    return True
```

Update the `add_light:` dispatch to accept `{"i", "shape"}` or a bare int:
```python
if action.startswith("add_light:"):
    payload = action.split(":", 1)[1]
    shape = None
    try:
        arg = json.loads(payload)
        idx = int(arg["i"]); shape = str(arg["shape"])
    except (ValueError, KeyError, TypeError):
        try:
            idx = int(payload)          # legacy bare-int payload
        except ValueError:
            return False
    if not (0 <= idx < len(self._descriptors)) or self._has_light(idx):
        return False
    base = self._descriptors[idx].get("light_region")
    if not base:
        return False
    spec = dict(base)
    if shape in ("Sphere", "Cylinder", "Box"):
        spec["shape"] = shape
    self._pending_light[idx] = spec
    self._selected_light_index = idx
    self.selected_index = None
    self._expanded_groups.add(self._descriptors[idx].get("name", ""))
    self._last_pushed = None
    return True
```

- [ ] **Step 4: Run to verify pass + regression**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel_light_modal.py tests/ui/test_ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel_scale.py tests/ui/test_ship_property_viewer_panel_rotate.py -v`
Expected: PASS. (If an existing test drove `set_light` with size args and asserted the size landed, it now conflicts with the new shape-only contract — update it to the new behaviour: the size comes from the current spec, not the modal. Note any such update in the report.)

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel_light_modal.py
# add tests/ui/test_ship_property_viewer_panel.py ONLY if you had to update an existing set_light test
git commit -m "feat(spv): light modal dispatch — set_light shape-only, add_light gains shape"
```

---

### Task 2: CEF light-type modal

**Files:**
- Modify: `native/assets/ui-cef/index.html`, `native/assets/ui-cef/js/ship_property_viewer.js`
- Test: none automated (CEF DOM verified in-game); dispatch covered by Task 1.

**Interfaces:**
- Consumes: the `dauntlessEvent` channel; the `set_light`/`add_light` dispatch (Task 1); the existing `spvLight`/`spvCtxIndex`/`spvRowLight` state and `shipPropertyViewerLightShape`/`Apply`/`CtxLight`/`CtxAddLight` handlers.
- Produces: the modal shows only shape buttons + Cancel/Apply (no size fields); a `spvLightMode` flag; Add opens the modal; Apply routes to `add_light`/`set_light` with `{i, shape}`.

- [ ] **Step 1: Reduce the modal in `index.html`**

Remove the `<div id="spv-light-fields"></div>` line from `#spv-light` (the size steppers container). Give the title an id so the JS can set it:
`<div id="spv-light-title" class="spv-modal__title">Edit Light</div>`. Keep the shape-button row + Cancel/Apply.

- [ ] **Step 2: JS — type-only picker + add/edit mode**

- Add near the other SPV state: `var spvLightMode = 'edit';`
- `shipPropertyViewerLightShape(shape)`: keep `spvLight.shape = shape` + the active-button highlight loop; **delete** the `#spv-light-fields` innerHTML population (and the `spvStepperHtml` calls). (Leave `spvStepperHtml` defined if the radius modal still uses it; only stop calling it here.)
- `shipPropertyViewerCtxLight` (Edit): set `spvLightMode = 'edit'`; set `#spv-light-title` textContent = 'Edit Light'; seed `spvLight.shape` from the row's `light_region.shape` (as today) and call `shipPropertyViewerLightShape(spvLight.shape)` to highlight; show the modal. Keep the existing `select_light` fire.
- `shipPropertyViewerCtxAddLight` (Add): set `spvLightMode = 'add'`; set `#spv-light-title` = 'Add Light'; default `spvLight.shape` from `spvRowLight[spvCtxIndex]?.shape || 'Sphere'`; call `shipPropertyViewerLightShape(spvLight.shape)`; **open the `#spv-light` modal** (replace the current direct `dauntlessEvent('add_light:'+...)` + `spvHideOverlays()`). Fire `overlay:1` like the other modals if that's the pattern (mirror `shipPropertyViewerCtxLight`).
- `shipPropertyViewerLightApply`: 
  ```javascript
  var action = (spvLightMode === 'add') ? 'add_light:' : 'set_light:';
  dauntlessEvent('ship-property-viewer/' + action + JSON.stringify({i: spvCtxIndex, shape: spvLight.shape}));
  spvHideOverlays();
  ```

- [ ] **Step 3: Build + gate**

Run: `scripts/check_tests.sh`
Expected: "OK — no new failures. 1 known failure(s) still baselined." (CEF assets load from source.)

- [ ] **Step 4: Commit**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/js/ship_property_viewer.js
git commit -m "feat(spv): Edit/Add Light modal is a light-type picker (no size fields)"
```

---

## Self-Review

**Spec coverage:** Edit shape-only (Task 1 `set_light` + Task 2 modal), Add uses the same picker (Task 1 `add_light` shape + Task 2 mode flag), size preserved on shape change (Task 1), size fields removed (Task 2), backward-compat bare-int add (Task 1).

**Placeholder scan:** real code for the Python dispatch; the CEF task points at concrete existing handlers to modify.

**Type consistency:** `set_light`/`add_light` payloads `{i, shape}` match producer (JS Apply) and consumer (dispatch); the modal's `spvLightMode` gates which action fires; the preserved-spec field set (position/axis/radius/extent/scale/orientation) matches `region_spec_to_calls`/`_effective_light`.
