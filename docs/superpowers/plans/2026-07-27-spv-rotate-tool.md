# SPV Rotate Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Rotate tool (ring gizmo + top-right degrees panel) that rotates a Cylinder light volume's axis, staged and saved through the existing light path. Inert on non-cylinder lights and everything else.

**Architecture:** Reuses the Transform/Scale gizmo plumbing. New Python rotate value-model/dispatch/ring-drag in `ship_property_viewer_panel.py`, ring-picking/angle/Rodrigues helpers in `ship_property_viewer.py`, a ring render mode (`handle_kind==2`) in `gizmo_pass.cc`, and a CEF `#spv-rotate` panel. No binding/host_loop/writer change.

**Tech Stack:** Python 3, C++/OpenGL, CEF, pytest.

## Global Constraints

- **Developer-only, production byte-identical.** Reachable only under `--developer` + SPV open + Rotate tool active + a Cylinder light selected. `rotate_values()`/`rotate_gizmo()` return `None` otherwise; the native gizmo draws nothing at length 0.
- **Cylinder lights only.** `_rotate_target()` returns a target only for a light whose effective shape is `Cylinder`. Box/Sphere lights and everything else → inert.
- **Persist via the existing light path**: a rotation writes the new unit `axis` into `_pending_light[i]["axis"]`, saved by `region_spec_to_calls`→`set_region` (`SetGlowRegionAxis`). No writer change.
- **Third button = Mirror** (negate axis X). **Copy/Paste** the axis vector, kind-matched.
- **Only one of the three tool panels/gizmos at a time** (radio).
- **Shared checkout.** Explicit pathspecs only. Never `git add -A`/`checkout`/`restore`/`stash`/`reset --hard`/`clean`.
- **Test gate.** `scripts/check_tests.sh` green vs `tests/known_failures.txt` (1 baselined).
- **CEF payload is a JS-call string** — tests unwrap with `_payload_data`, never `json.loads` on the raw string.

## File Structure

- `engine/ui/ship_property_viewer.py` — Task 2 pure helpers (`_plane_basis`, `pick_gizmo_ring`, `ring_drag_angle`, `rotate_about_axis`).
- `engine/ui/ship_property_viewer_panel.py` — Task 1 (value model/dispatch/payload) & Task 2 (gizmo + ring drag + handle_input + guard).
- `native/src/renderer/gizmo_pass.cc` — Task 3 (ring render mode).
- `native/assets/ui-cef/{index.html,css/ship_property_viewer.css,js/ship_property_viewer.js}` — Task 4.
- Tests under `tests/ui/`, `tests/host/`.

---

### Task 1: Rotate value model + dispatch + payload

**Files:**
- Modify: `engine/ui/ship_property_viewer.py` (add `rotate_about_axis`)
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_panel_rotate.py` (create)

**Interfaces:**
- Consumes: `_active_transform_target`, `_effective_light`, `_pending_light`, `dispatch_event`, `render_payload`, `math`.
- Produces: `rotate_about_axis` (in ship_property_viewer.py); `_rotate_clipboard`, `_rotate_accum`, `_rotate_target`, `rotate_values`, `_rotate_axis`, `_set_axis_absolute`; dispatch `rotate_nudge`/`rotate_copy`/`rotate_paste`/`rotate_mirror`; `"rotate_values"` payload key + snapshot members.

- [ ] **Step 1: Write the failing tests**

```python
# tests/ui/test_ship_property_viewer_panel_rotate.py
"""SPV rotate tool: rotate_values() + rotate_* dispatch (cylinder axis only)."""
import json
import math

import pytest

from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel
from engine.ui.ship_property_viewer import rotate_about_axis


def _payload_data(payload):
    return json.loads(payload[payload.index("(") + 1:payload.rindex(")")])


def _panel_light(shape="Cylinder", axis=(0.0, -1.0, 0.0)):
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p._descriptors = [{
        "name": "Port Warp", "kind": "subsystem",
        "properties": {"position": (0.0, 1.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 1.0, 0.0), "parent_index": None, "light": True,
        "light_region": {"shape": shape, "position": (0.0, 1.0, 0.0), "axis": axis,
                         "radius": (0.3,), "extent": (-2.0, 2.0),
                         "scale": (0.25, 0.25, 0.25)},
    }]
    p.dispatch_event("set_tool:rotate")
    p._selected_light_index = 0
    return p


def test_rotate_about_axis_z_90deg():
    # +Y rotated +90 deg about +Z -> -X (right-handed).
    out = rotate_about_axis((0.0, 1.0, 0.0), 2, math.radians(90.0))
    assert out == pytest.approx((-1.0, 0.0, 0.0), abs=1e-6)


def test_rotate_values_none_off_tool():
    p = _panel_light()
    p.dispatch_event("set_tool:rotate")   # toggle OFF
    assert p.rotate_values() is None


def test_rotate_values_none_for_box_light():
    p = _panel_light(shape="Box")
    assert p.rotate_values() is None       # rotate is cylinder-only


def test_rotate_values_present_for_cylinder():
    p = _panel_light()
    v = p.rotate_values()
    assert [f["label"] for f in v["fields"]] == ["X", "Y", "Z"]
    assert [f["value"] for f in v["fields"]] == [0.0, 0.0, 0.0]


def test_rotate_nudge_rotates_axis_and_bumps_accumulator():
    p = _panel_light(axis=(0.0, 1.0, 0.0))
    p.dispatch_event('rotate_nudge:' + json.dumps({"axis": 2, "delta": 90.0}))
    ax = p._effective_light(0)["axis"]
    assert ax == pytest.approx((-1.0, 0.0, 0.0), abs=1e-6)   # +Y about +Z 90 -> -X
    assert p.rotate_values()["fields"][2]["value"] == 90.0    # Z accumulator


def test_rotate_mirror_negates_axis_x_and_zeroes_accum():
    p = _panel_light(axis=(0.6, 0.8, 0.0))
    p.dispatch_event('rotate_nudge:' + json.dumps({"axis": 2, "delta": 10.0}))
    p.dispatch_event("rotate_mirror")
    ax = p._effective_light(0)["axis"]
    assert ax[0] < 0.0                                        # X negated
    assert p.rotate_values()["fields"] [2]["value"] == 0.0    # accumulator reset


def test_rotate_copy_paste_roundtrips_axis():
    p = _panel_light(axis=(0.0, 1.0, 0.0))
    p.dispatch_event("rotate_copy")
    assert p.rotate_values()["can_paste"] is True
    p.dispatch_event('rotate_nudge:' + json.dumps({"axis": 2, "delta": 45.0}))
    p.dispatch_event("rotate_paste")
    assert p._effective_light(0)["axis"] == pytest.approx((0.0, 1.0, 0.0), abs=1e-6)


def test_render_payload_carries_rotate_values():
    p = _panel_light()
    assert _payload_data(p.render_payload())["rotate_values"]["fields"][0]["label"] == "X"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel_rotate.py -v`
Expected: FAIL (`ImportError`/`AttributeError: rotate_about_axis` / `rotate_values`).

- [ ] **Step 3: Implement `rotate_about_axis` in `ship_property_viewer.py`**

Add near the other gizmo helpers (uses `math`, already imported):
```python
def rotate_about_axis(vec, k, angle_rad):
    """Rodrigues rotation of body-frame `vec` about basis axis e_k (k in 0/1/2),
    returned normalized. Falls back to the normalized input on a degenerate
    result."""
    kx = (1.0 if k == 0 else 0.0, 1.0 if k == 1 else 0.0, 1.0 if k == 2 else 0.0)
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    dot = kx[0]*vec[0] + kx[1]*vec[1] + kx[2]*vec[2]
    cross = (kx[1]*vec[2] - kx[2]*vec[1],
             kx[2]*vec[0] - kx[0]*vec[2],
             kx[0]*vec[1] - kx[1]*vec[0])
    out = (vec[0]*c + cross[0]*s + kx[0]*dot*(1.0 - c),
           vec[1]*c + cross[1]*s + kx[1]*dot*(1.0 - c),
           vec[2]*c + cross[2]*s + kx[2]*dot*(1.0 - c))
    n = math.sqrt(out[0]**2 + out[1]**2 + out[2]**2)
    if n < 1e-9:
        vn = math.sqrt(vec[0]**2 + vec[1]**2 + vec[2]**2) or 1.0
        return (vec[0]/vn, vec[1]/vn, vec[2]/vn)
    return (out[0]/n, out[1]/n, out[2]/n)
```

- [ ] **Step 4: Implement the panel value model + dispatch**

`__init__`/`open`/`close`: add `self._rotate_clipboard = None` and `self._rotate_accum = {}` (beside `_scale_clipboard`). Add methods:

```python
def _rotate_target(self):
    t = self._active_transform_target()
    if t is None:
        return None
    kt, i = t
    if kt != "light":
        return None
    spec = self._effective_light(i)
    if not spec or spec.get("shape") != "Cylinder":
        return None
    return ("light", i)

def rotate_values(self):
    if self.active_tool != "rotate":
        return None
    t = self._rotate_target()
    if t is None:
        return None
    _, i = t
    acc = self._rotate_accum.get(i, [0.0, 0.0, 0.0])
    clip = self._rotate_clipboard
    return {"fields": [{"label": "X", "value": acc[0]},
                       {"label": "Y", "value": acc[1]},
                       {"label": "Z", "value": acc[2]}],
            "has_clipboard": clip is not None,
            "can_paste": clip is not None}

def _rotate_axis(self, index, delta_deg):
    t = self._rotate_target()
    if t is None:
        return
    _, i = t
    from engine.ui.ship_property_viewer import rotate_about_axis
    spec = dict(self._effective_light(i) or {})
    if not spec:
        return
    axis = spec.get("axis") or (0.0, -1.0, 0.0)
    spec["axis"] = rotate_about_axis(axis, index, math.radians(delta_deg))
    self._pending_light[i] = spec
    self._rotate_accum.setdefault(i, [0.0, 0.0, 0.0])[index] += delta_deg
    self._last_pushed = None

def _set_axis_absolute(self, i, axis):
    spec = dict(self._effective_light(i) or {})
    if not spec:
        return
    n = math.sqrt(sum(a*a for a in axis)) or 1.0
    spec["axis"] = (axis[0]/n, axis[1]/n, axis[2]/n)
    self._pending_light[i] = spec
    self._rotate_accum[i] = [0.0, 0.0, 0.0]
    self._last_pushed = None
```

Dispatch cases (before `save`):
```python
if action.startswith("rotate_nudge:"):
    try:
        arg = json.loads(action.split(":", 1)[1])
        axis = int(arg["axis"]); delta = float(arg["delta"])
    except (ValueError, KeyError, TypeError):
        return False
    if axis not in (0, 1, 2) or self._rotate_target() is None:
        return False
    self._rotate_axis(axis, delta)
    return True
if action == "rotate_copy":
    t = self._rotate_target()
    if t is not None:
        _, i = t
        axis = (self._effective_light(i) or {}).get("axis") or (0.0, -1.0, 0.0)
        self._rotate_clipboard = ("cylinder_axis", tuple(axis))
        self._last_pushed = None
    return True
if action == "rotate_paste":
    t = self._rotate_target()
    if t is not None and self._rotate_clipboard is not None:
        _, i = t
        self._set_axis_absolute(i, self._rotate_clipboard[1])
    return True
if action == "rotate_mirror":
    t = self._rotate_target()
    if t is not None:
        _, i = t
        axis = list((self._effective_light(i) or {}).get("axis") or (0.0, -1.0, 0.0))
        axis[0] = -axis[0]
        self._set_axis_absolute(i, axis)
    return True
```

`render_payload`: add `"rotate_values": self.rotate_values()` to the dict, and add both `self._rotate_clipboard` and `tuple(sorted((k, tuple(v)) for k, v in self._rotate_accum.items()))` to the `snapshot` tuple.

- [ ] **Step 5: Run to verify pass + regression**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel_rotate.py tests/ui/test_ship_property_viewer_panel_scale.py tests/ui/test_ship_property_viewer_panel_coords.py tests/ui/test_ship_property_viewer_panel.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/ui/ship_property_viewer.py engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel_rotate.py
git commit -m "feat(spv): rotate value model + dispatch (cylinder axis, nudge/copy/paste/mirror)"
```

---

### Task 2: Ring gizmo + angular drag + handle_input branch

**Files:**
- Modify: `engine/ui/ship_property_viewer.py` (ring helpers)
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_panel_rotate.py` (extend)

**Interfaces:**
- Consumes: `_add`/`_scale`/`_sub`/`_norm`/`_seg_dist2`/`project`/`gizmo_axes`/`gizmo_length` (ship_property_viewer.py); `_active_gizmo`, `_handle_gizmo_input`, `_rotate_target`, `_effective_light`, `_pending_light`, `_rotate_accum`, `_end_axis_drag`, camera; the `over_coords` guard.
- Produces: `_plane_basis`, `pick_gizmo_ring`, `ring_drag_angle` (ship_property_viewer.py); `rotate_gizmo`, `_active_gizmo` rotate branch, `_begin_ring_drag`/`_apply_ring_drag`, `_handle_gizmo_input` rotate branch, guard/popover generalization.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/ui/test_ship_property_viewer_panel_rotate.py
from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui.ship_property_viewer import OrbitCamera, gizmo_length


class _Ship:
    def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
    def GetWorldRotation(self): return TGMatrix3()


def _panel_ring():
    p = ShipPropertyViewerPanel(ship_getter=lambda: _Ship())
    p.open()
    p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
    p._descriptors = [{
        "name": "Port Warp", "kind": "subsystem",
        "properties": {"position": (0.0, 0.0, 0.0), "radius": 0.3},
        "world_pos": (0.0, 0.0, 0.0), "parent_index": None, "light": True,
        "light_region": {"shape": "Cylinder", "position": (0.0, 0.0, 0.0),
                         "axis": (0.0, 1.0, 0.0), "radius": (0.3,),
                         "extent": (-2.0, 2.0), "scale": (0.25, 0.25, 0.25)},
    }]
    p.dispatch_event("set_tool:rotate")
    p._selected_light_index = 0
    return p


def test_rotate_gizmo_gate_and_handle_kind():
    p = _panel_ring()
    g = p.rotate_gizmo()
    assert g is not None and g["handle_kind"] == 2
    assert p._active_gizmo()["handle_kind"] == 2


def test_ring_drag_rotates_axis():
    # Grab the Z ring; simulate a screen-angle sweep and assert the axis moved
    # off its start and stayed unit-length.
    p = _panel_ring()
    p._begin_ring_drag(2, 0.0)          # grab angle 0 rad on ring Z
    p._apply_ring_drag_angle(math.radians(30.0))   # test seam: apply a raw body angle
    ax = p._effective_light(0)["axis"]
    assert abs(math.sqrt(sum(a*a for a in ax)) - 1.0) < 1e-6
    assert ax != (0.0, 1.0, 0.0)
```

(Add a `_apply_ring_drag_angle(self, d_body)` test seam that applies a raw body-frame delta angle — the same core `_apply_ring_drag` uses after computing the screen delta — so the drag math is unit-testable without a fake cursor.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel_rotate.py -k "ring or rotate_gizmo" -v`
Expected: FAIL (`AttributeError: rotate_gizmo`).

- [ ] **Step 3: Implement the ring helpers (`ship_property_viewer.py`)**

```python
def _plane_basis(n):
    """Two orthonormal vectors spanning the plane perpendicular to unit `n`."""
    n = _norm(n)
    seed = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = _norm(_sub(seed, _scale(n, _dot(seed, n))))
    v = (n[1]*u[2] - n[2]*u[1], n[2]*u[0] - n[0]*u[2], n[0]*u[1] - n[1]*u[0])
    return u, v


def pick_gizmo_ring(cursor_x, cursor_y, origin, axes, length, cam, viewport,
                    device_scale_factor=1.0, samples=48):
    """Ring index (0/1/2) whose projected circle (in the plane perpendicular to
    axes[k]) is nearest the cursor, or None. Nearest within the click threshold."""
    thresh = GIZMO_PICK_PT * (device_scale_factor if device_scale_factor > 0 else 1.0)
    best_d2, best = thresh * thresh, None
    for k in range(3):
        u, v = _plane_basis(axes[k])
        pts = []
        for sidx in range(samples):
            a = 2.0 * math.pi * sidx / samples
            p = _add(origin, _add(_scale(u, length*math.cos(a)),
                                  _scale(v, length*math.sin(a))))
            sx, sy, _z, vis = project(p, cam, viewport)
            pts.append((sx, sy) if vis else None)
        for sidx in range(samples):
            a0, a1 = pts[sidx], pts[(sidx + 1) % samples]
            if a0 is None or a1 is None:
                continue
            d2 = _seg_dist2(cursor_x, cursor_y, a0[0], a0[1], a1[0], a1[1])
            if d2 < best_d2:
                best_d2, best = d2, k
    return best


def ring_drag_angle(cursor_x, cursor_y, origin, cam, viewport):
    """Cursor's screen angle around the projected gizmo centre (radians)."""
    ox, oy, _z, _vis = project(origin, cam, viewport)
    return math.atan2(cursor_y - oy, cursor_x - ox)
```

- [ ] **Step 4: Implement the panel gizmo + ring drag**

Add `rotate_gizmo` (mirror `scale_gizmo`, `handle_kind: 2`, gated on `_rotate_target()`), extend `_active_gizmo()` with the `rotate` branch. Init `self._ring_grab_angle = 0.0`, `self._ring_grab_axis = (0.0, -1.0, 0.0)`, `self._ring_grab_accum = [0.0, 0.0, 0.0]`, `self._ring_sign = 1.0` in `__init__`/`open`/`close`. Add:

```python
def _begin_ring_drag(self, ring, grab_angle):
    g = self._active_gizmo()
    self._axis_drag = ring
    self._axis_grab_origin = g["origin"] if g else (0.0, 0.0, 0.0)
    self._ring_grab_angle = grab_angle
    t = self._rotate_target()
    if t is None:
        self._ring_grab_axis = (0.0, -1.0, 0.0)
        self._ring_grab_accum = [0.0, 0.0, 0.0]
        self._ring_sign = 1.0
        return
    _, i = t
    self._ring_grab_axis = tuple((self._effective_light(i) or {}).get("axis")
                                 or (0.0, -1.0, 0.0))
    self._ring_grab_accum = list(self._rotate_accum.get(i, [0.0, 0.0, 0.0]))
    eye, tgt = self.camera.eye(), self.camera.target
    fwd = (tgt[0]-eye[0], tgt[1]-eye[1], tgt[2]-eye[2])
    wa = g["axes"][ring] if g else (0.0, 0.0, 1.0)
    d = wa[0]*fwd[0] + wa[1]*fwd[1] + wa[2]*fwd[2]
    # Screen-CCW should rotate about the axis toward the camera. If it feels
    # inverted in-game, flip this comparison.
    self._ring_sign = -1.0 if d > 0.0 else 1.0

def _apply_ring_drag_angle(self, d_body):
    """Apply a body-frame delta angle (radians) about the grabbed ring axis to
    the grab-start axis. Shared core for the cursor-driven drag + tests."""
    t = self._rotate_target()
    if t is None or self._axis_drag is None:
        return
    _, i = t
    from engine.ui.ship_property_viewer import rotate_about_axis
    k = self._axis_drag
    spec = dict(self._effective_light(i) or {})
    if not spec:
        return
    spec["axis"] = rotate_about_axis(self._ring_grab_axis, k, d_body)
    self._pending_light[i] = spec
    self._rotate_accum.setdefault(i, [0.0, 0.0, 0.0])
    self._rotate_accum[i][k] = self._ring_grab_accum[k] + math.degrees(d_body)
    self._last_pushed = None

def _apply_ring_drag(self, x, y, fb_size):
    from engine.ui.ship_property_viewer import ring_drag_angle
    ang = ring_drag_angle(x, y, self._axis_grab_origin, self.camera, fb_size())
    d = ang - self._ring_grab_angle
    while d > math.pi:
        d -= 2.0 * math.pi
    while d < -math.pi:
        d += 2.0 * math.pi
    self._apply_ring_drag_angle(d * self._ring_sign)
```

- [ ] **Step 5: Hook into `_handle_gizmo_input`**

Read the current method (move/scale three-way). Extend to a rotate branch at three points, leaving move/scale byte-for-byte:
- **Active-drag branch**: `if self.active_tool == "rotate": self._apply_ring_drag(x, y, fb_size)` else the existing `t = axis_drag_param(...)` + scale/axis apply.
- **Press-edge grab**: `if self.active_tool == "rotate":` `ring = pick_gizmo_ring(x, y, g["origin"], g["axes"], g["length"], self.camera, fb_size(), dsf); if ring is None: return False; self._begin_ring_drag(ring, ring_drag_angle(x, y, g["origin"], self.camera, fb_size())); self._gizmo_hover = ring` — else the existing `pick_gizmo_axis` + scale/axis begin. Keep the shared `_chrome_press`/`_lmb_down`/`_drag_last`/`_press_pos`/`_drag_dist` bookkeeping and the `return True`.
- **Hover branch**: `if self.active_tool == "rotate": hov = pick_gizmo_ring(...)` else `pick_gizmo_axis(...)`; set `_gizmo_hover`.
Import `pick_gizmo_ring, ring_drag_angle` alongside the existing `pick_gizmo_axis, axis_drag_param, gizmo_length` import.

Generalize the `over_coords` guard (and note the popover suppression is CEF, Task 4):
```python
over_coords = ((self.transform_coords() is not None
                or self.scale_values() is not None
                or self.rotate_values() is not None)
               and self._cursor_over_coords(x, y, dsf, fb_w, fb_h))
```
Add a test that the guard fires for rotate (mirror the scale guard test with the Rotate tool + a cylinder light selected).

- [ ] **Step 6: Run to verify pass + regression**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel_rotate.py tests/ui/test_ship_property_viewer_panel_scale.py tests/ui/test_ship_property_viewer_panel_gizmo.py tests/ui/test_ship_property_viewer_panel_coords.py tests/ui/test_ship_property_viewer_panel.py -v`
Expected: PASS (move + scale drag + orbit/pin intact).

- [ ] **Step 7: Commit**

```bash
git add engine/ui/ship_property_viewer.py engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel_rotate.py
git commit -m "feat(spv): rotate ring gizmo + angular drag + handle_input branch"
```

---

### Task 3: Native ring render mode

**Files:**
- Modify: `native/src/renderer/gizmo_pass.cc`
- Test: `tests/host/test_transform_gizmo_binding.py` (extend)

**Interfaces:**
- Consumes: the `Gizmo` struct (already has `handle_kind`), `render`, the existing per-axis model-matrix + `rotation_onto` helper.
- Produces: a `handle_kind == 2` branch drawing three rings (one per body-axis plane), coloured X/Y/Z, hovered ring brightened; no shafts/tips.

- [ ] **Step 1: Extend the host test**

```python
# add to tests/host/test_transform_gizmo_binding.py
def test_set_transform_gizmo_accepts_ring_handle_kind():
    _h.set_transform_gizmo((0.0, 0.0, 0.0),
                           (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                           1.5, 1, 2)   # handle_kind 2 = rings
    _h.clear_transform_gizmo()
```

- [ ] **Step 2: Build + run to verify it passes trivially (binding already takes handle_kind)**

Run: `cmake --build build -j && uv run pytest tests/host/test_transform_gizmo_binding.py -v`
Expected: PASS (the binding already accepts `handle_kind`; this pins that `2` is accepted). The ring RENDER is verified in-game.

- [ ] **Step 3: Implement the ring mesh + branch in `gizmo_pass.cc`**

Read the existing `render`/`ensure_resources`. Build a **unit ring mesh** once in `ensure_resources` (a segmented circle in the XY plane, radius 1, as `GL_LINES` segment pairs or `GL_LINE_LOOP`). In `render`, when `g.handle_kind == 2`: for each axis k, build a model matrix that rotates the ring's plane-normal (+Z) onto `g.axis[k]` (reuse the existing `rotation_onto(+Z, axis)` helper the cones use), scales by `g.length`, translates to `g.origin`; set `u_color` per axis (reuse the axis colour table), brighten when `k == g.highlight`; draw the ring mesh. No shaft, no tip. Keep the depth-test-off + cull + state save/restore identical to the other modes. `handle_kind` 0/1 branches unchanged.

- [ ] **Step 4: Build + run test + ctest**

Run: `cmake --build build -j && uv run pytest tests/host/test_transform_gizmo_binding.py -v && ctest --test-dir build --output-on-failure | tail -3`
Expected: PASS; ctest no new failures.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/gizmo_pass.cc tests/host/test_transform_gizmo_binding.py
git commit -m "feat(spv): ring-handle gizmo mode for Rotate"
```

---

### Task 4: CEF rotate panel

**Files:**
- Modify: `native/assets/ui-cef/index.html`, `native/assets/ui-cef/css/ship_property_viewer.css`, `native/assets/ui-cef/js/ship_property_viewer.js`
- Test: none automated (CEF DOM verified in-game); panel state covered by Task 1.

**Interfaces:**
- Consumes: `payload.rotate_values` (`{fields:[{label,value}], has_clipboard, can_paste}` or null); the `dauntlessEvent` channel; `setShipPropertyViewer`.
- Produces: `#spv-rotate` panel; `shipPropertyViewerRotateNudge(axis, delta)` / `...RotateCopy|Paste|Mirror`; render-apply that fills the three degree readouts, gates Paste, shows/hides the panel, and suppresses the popover when any tool panel is up.

- [ ] **Step 1: Add `#spv-rotate` to `index.html`**

Sibling of `#spv-coords`/`#spv-scale` inside `#spv-root` (class `spv-coords dev-only`, hidden). Title "Rotate", three rows X/Y/Z each `−5° −1° <value>° +1° +5°` calling `shipPropertyViewerRotateNudge(k, ∓5/∓1/1/5)`, and a `#spv-rotate-rows` is not needed (fixed 3 rows; give each value span an id `spv-rotate-x/y/z`). Actions row: Copy / `#spv-rotate-paste` Paste / Mirror. Use the degree suffix `°` on the readout.

- [ ] **Step 2: JS handlers + render-apply**

```javascript
window.shipPropertyViewerRotateNudge = function (axis, delta) {
    dauntlessEvent('ship-property-viewer/rotate_nudge:' + JSON.stringify({axis: axis, delta: delta}));
};
window.shipPropertyViewerRotateCopy = function () { dauntlessEvent('ship-property-viewer/rotate_copy'); };
window.shipPropertyViewerRotatePaste = function () { dauntlessEvent('ship-property-viewer/rotate_paste'); };
window.shipPropertyViewerRotateMirror = function () { dauntlessEvent('ship-property-viewer/rotate_mirror'); };
```

In `setShipPropertyViewer`, after the scale block, add a rotate block: read `data.rotate_values`; null → hide `#spv-rotate`; else set `#spv-rotate-x/y/z` textContent to `fields[0/1/2].value.toFixed(1)`, disable `#spv-rotate-paste` when `!can_paste`, show the panel. (Fixed X/Y/Z rows, so no innerHTML rebuild — just fill three spans.)

- [ ] **Step 3: Popover suppression + CSS**

- Popover branch → `if (data.selected && !data.transform_coords && !data.scale_values && !data.rotate_values)`.
- `#spv-rotate` reuses `.spv-coords` geometry (class `spv-coords`) — no new geometry rule; confirm `.spv-coords .spv-step` shrink applies. Width stays 220.

- [ ] **Step 4: Build + gate**

Run: `scripts/check_tests.sh`
Expected: "OK — no new failures. 1 known failure(s) still baselined."

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/css/ship_property_viewer.css native/assets/ui-cef/js/ship_property_viewer.js
git commit -m "feat(spv): CEF rotate panel (degree steppers + Copy/Paste/Mirror)"
```

---

## Self-Review

**Spec coverage:** cylinder-only gate (Task 1 `_rotate_target`), axis rotation + accumulator (Task 1 `_rotate_axis`), Mirror/Copy/Paste (Task 1 dispatch + Task 4 buttons), ring gizmo + angular drag (Tasks 2+3), guard/popover generalization (Tasks 2+4), persistence via `_pending_light` axis (Task 1), one-panel-at-a-time (radio).

**Placeholder scan:** real code for the Python; native ring mesh + CEF point at concrete existing structures (`rotation_onto`, the `.spv-coords` panel, the scale block).

**Type consistency:** `rotate_values()` shape matches Task-4 consumer; `rotate_nudge` JSON (`axis`/`delta`) matches producer/consumer; `rotate_gizmo` `handle_kind:2` consumed by host_loop's existing push + Task-3 render; `rotate_about_axis`/`pick_gizmo_ring`/`ring_drag_angle` signatures match Task-2 uses; `_apply_ring_drag_angle` shared by the cursor drag and the test seam.
