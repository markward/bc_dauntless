# Ship Property Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A developer-mode pause-menu tool that renders the player ship as a translucent blue hologram with a camera-facing billboard pin per subsystem, and a click-pin property popover.

**Architecture:** Pure-Python core (orbit camera, world→screen projection, subsystem descriptor builder, pin picking, a `Panel` lifecycle) is built and unit-tested first. Two self-contained OpenGL passes (`HologramPass`, `SubsystemPinPass`) modelled on `phaser_pass` render on top of the scene, fed descriptor lists from Python. A transparent CEF overlay draws the title bar and the property popover. Everything is inert/unconstructed unless developer mode is on and the viewer is open.

**Tech Stack:** Python 3 (engine side), pybind11 host bindings (`_open_stbc_host`), OpenGL/GLSL via the existing `Pipeline`/`Shader` infra, CEF (Chromium) for chrome. Tests: pytest (focused subsets only — the full suite OOMs the host).

**Reference spec:** `docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md`

**Conventions to respect (from CLAUDE.md):**
- Rotation matrices are **column-vector**; world-forward is `GetCol(1)`, body→world is `v.MultMatrixLeft(R)` (= `R·v`). Never use rows.
- Build only from `build/`: `cmake -B build -S . && cmake --build build -j`. Run `./build/dauntless`.
- **Shader edits require a cmake *reconfigure*** (`cmake -B build -S .`) before `cmake --build` — `.vert`/`.frag` changes are not picked up otherwise.
- Run **focused** pytest subsets, never the whole suite (it uses >100 GB RAM).
- No scale factor in subsystem mounts: `world = ship.GetWorldLocation() + GetWorldRotation()·GetPosition()`.

---

## File Structure

**New (Python):**
- `engine/ui/ship_property_viewer.py` — orbit camera, `project()`, `subsystem_world_position()`, descriptor builder, pin picking. Pure logic, no GL/CEF imports.
- `engine/ui/ship_property_viewer_panel.py` — `ShipPropertyViewerPanel(Panel)` lifecycle + render payload + input.
- `tests/ui/test_ship_property_viewer.py` — unit tests for the logic module.
- `tests/ui/test_ship_property_viewer_panel.py` — unit tests for the panel.

**New (C++/GL):**
- `native/src/renderer/include/renderer/hologram_pass.h`
- `native/src/renderer/hologram_pass.cc`
- `native/src/renderer/shaders/hologram.vert`, `hologram.frag`
- `native/src/renderer/include/renderer/subsystem_pin_pass.h`
- `native/src/renderer/subsystem_pin_pass.cc`
- `native/src/renderer/shaders/subsystem_pin.vert`, `subsystem_pin.frag`

**New (CEF):**
- `native/assets/ui-cef/js/ship_property_viewer.js`
- `native/assets/ui-cef/panels/ship_property_viewer.html` (or inline into existing index — follow the pattern used by `developer_options`)
- `native/assets/ui-cef/css/ship_property_viewer.css`

**Modified:**
- `engine/appc/subsystems.py` — extract `subsystem_world_position` and have `_emitter_world_position` delegate to it (DRY).
- `native/src/renderer/CMakeLists.txt` — add the two passes.
- `native/src/renderer/include/renderer/pipeline.h` + `pipeline.cc` — add `hologram_shader()` / `subsystem_pin_shader()` accessors (mirror `phaser_shader()`).
- `native/src/host/host_bindings.cc` — own the passes; add `set_hologram_ship`, `clear_hologram_ship`, `set_subsystem_pins`; call them in the frame render.
- `engine/renderer.py` — thin wrappers for the new bindings.
- `engine/host_loop.py` — dev-only construction + pause-menu registration + per-frame camera/descriptor push while open.
- `CLAUDE.md` — reference-table row (final task).

---

## Phase A — Python logic core (TDD)

### Task A1: Extract `subsystem_world_position` shared helper

**Files:**
- Modify: `engine/appc/subsystems.py` (the `_emitter_world_position` method near line 769)
- Create: `engine/ui/ship_property_viewer.py`
- Test: `tests/ui/test_ship_property_viewer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_ship_property_viewer.py
import math
from engine.appc.math import TGPoint3, TGMatrix3
from engine.ui.ship_property_viewer import subsystem_world_position


class _FakeShip:
    def __init__(self, loc, rot):
        self._loc, self._rot = loc, rot
    def GetWorldLocation(self):
        return self._loc
    def GetWorldRotation(self):
        return self._rot


class _FakeSub:
    """Subsystem with a model-local mount and a parent ship."""
    def __init__(self, pos, ship):
        self._pos, self._ship = pos, ship
    def GetPosition(self):
        return None if self._pos is None else TGPoint3(*self._pos)
    def _climb_to_ship(self):
        return self._ship


def test_world_position_identity_rotation_adds_offset():
    ship = _FakeShip(TGPoint3(10.0, 0.0, 0.0), TGMatrix3())  # identity
    sub = _FakeSub((0.0, 1.0, 0.5), ship)
    w = subsystem_world_position(sub)
    assert (round(w.x, 5), round(w.y, 5), round(w.z, 5)) == (10.0, 1.0, 0.5)


def test_world_position_yaw_rotates_offset_columnvec():
    rot = TGMatrix3(); rot.MakeZRotation(math.pi / 2.0)  # +90° about Z
    ship = _FakeShip(TGPoint3(0.0, 0.0, 0.0), rot)
    sub = _FakeSub((0.0, 1.0, 0.0), ship)   # body +Y
    w = subsystem_world_position(sub)
    # Column-vector R·(0,1,0): +Y maps to -X for a +90° Z rotation.
    assert round(w.x, 5) == -1.0 and round(w.y, 5) == 0.0


def test_world_position_none_mount_returns_ship_location():
    ship = _FakeShip(TGPoint3(3.0, 4.0, 5.0), TGMatrix3())
    sub = _FakeSub(None, ship)
    w = subsystem_world_position(sub)
    assert (w.x, w.y, w.z) == (3.0, 4.0, 5.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/ui/test_ship_property_viewer.py -q`
Expected: FAIL — `ModuleNotFoundError: engine.ui.ship_property_viewer` (and `TGMatrix3.MakeZRotation`/`MakeZ...` exists per CLAUDE.md).

- [ ] **Step 3: Implement the helper in the new module**

```python
# engine/ui/ship_property_viewer.py
"""Ship Property Viewer — logic core (camera, projection, descriptors, picking).

Pure Python: no GL or CEF imports. See
docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from engine.appc.math import TGPoint3, TGMatrix3


def subsystem_world_position(sub) -> TGPoint3:
    """World mount point of a subsystem: ship location + body→world rotated
    local mount. No scale factor (BC stores mounts in world units relative to
    the ship centre — see engine/appc/subsystems.py:769). Returns the ship
    location if the subsystem has no 3D mount."""
    ship = sub._climb_to_ship() if hasattr(sub, "_climb_to_ship") else None
    if ship is None or not hasattr(ship, "GetWorldLocation"):
        return TGPoint3(0.0, 0.0, 0.0)
    ship_pos = ship.GetWorldLocation()
    local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
    if not isinstance(local, TGPoint3):
        return TGPoint3(ship_pos.x, ship_pos.y, ship_pos.z)
    offset = TGPoint3(local.x, local.y, local.z)
    if hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            offset.MultMatrixLeft(rot)  # R · offset (column-vector)
    return TGPoint3(ship_pos.x + offset.x,
                    ship_pos.y + offset.y,
                    ship_pos.z + offset.z)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/ui/test_ship_property_viewer.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: DRY — delegate the phaser method to the shared helper**

In `engine/appc/subsystems.py`, replace the body of `_emitter_world_position` (lines ~769-792) with a delegation, keeping the docstring:

```python
    def _emitter_world_position(self) -> TGPoint3:
        """Ship world location + emitter local position rotated into world frame.
        (Delegates to the shared engine.ui.ship_property_viewer helper.)"""
        from engine.ui.ship_property_viewer import subsystem_world_position
        return subsystem_world_position(self)
```

(The import is function-local to avoid an import cycle: `ship_property_viewer` imports only `engine.appc.math`.)

- [ ] **Step 6: Run the phaser/subsystem tests to confirm no regression**

Run: `uv run pytest tests/appc/test_subsystems.py -q` (if absent, run `uv run pytest tests/ -k "emitter or phaser or subsystem" -q`)
Expected: PASS — phaser emitter positions unchanged.

- [ ] **Step 7: Commit**

```bash
git add engine/ui/ship_property_viewer.py engine/appc/subsystems.py tests/ui/test_ship_property_viewer.py
git commit -m "feat(viewer): subsystem_world_position helper; phaser delegates to it"
```

---

### Task A2: Orbit camera + world→screen projection

**Files:**
- Modify: `engine/ui/ship_property_viewer.py`
- Test: `tests/ui/test_ship_property_viewer.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/ui/test_ship_property_viewer.py
import math
from engine.ui.ship_property_viewer import OrbitCamera, project


def test_orbit_camera_eye_in_front_at_zero_angles():
    cam = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0, yaw=0.0, pitch=0.0)
    eye = cam.eye()
    # At yaw=pitch=0 the eye sits on +Y (BC forward) looking back at origin,
    # distance 10 → one axis is ±10, others ~0.
    assert round(max(abs(eye[0]), abs(eye[1]), abs(eye[2])), 4) == 10.0


def test_project_point_at_target_lands_at_screen_centre():
    cam = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0, yaw=0.0, pitch=0.0)
    sx, sy, depth, visible = project((0.0, 0.0, 0.0), cam, (800, 600))
    assert visible is True
    assert abs(sx - 400.0) < 0.5 and abs(sy - 300.0) < 0.5


def test_project_point_behind_camera_not_visible():
    cam = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0, yaw=0.0, pitch=0.0)
    # A point far on the far side beyond the target, behind the eye direction.
    far_behind = tuple(c * 1000.0 for c in cam.eye())
    sx, sy, depth, visible = project(far_behind, cam, (800, 600))
    assert visible is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/ui/test_ship_property_viewer.py -k "orbit or project" -q`
Expected: FAIL — `cannot import name 'OrbitCamera'`.

- [ ] **Step 3: Implement the camera + projection**

```python
# add to engine/ui/ship_property_viewer.py
import math

Vec3 = Tuple[float, float, float]


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])

def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])

def _dot(a: Vec3, b: Vec3) -> float:
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

def _norm(a: Vec3) -> Vec3:
    m = math.sqrt(_dot(a, a)) or 1.0
    return (a[0]/m, a[1]/m, a[2]/m)


class OrbitCamera:
    """Orbit around a target. yaw/pitch in radians; distance in game units.

    Orientation is body-frame-agnostic world spherical coords (the viewer is a
    standalone inspection scene, not the gameplay camera, so it may use a fixed
    world basis here — this does NOT violate the no-world-up rule, which governs
    the in-game flight camera). +Y is BC forward; +Z up for the math basis."""
    def __init__(self, target: Vec3, distance: float,
                 yaw: float = 0.0, pitch: float = 0.0,
                 fov_y_rad: float = math.radians(45.0),
                 near: float = 0.05, far: float = 1.0e6):
        self.target = target
        self.distance = distance
        self.yaw = yaw
        self.pitch = pitch
        self.fov_y_rad = fov_y_rad
        self.near = near
        self.far = far

    def eye(self) -> Vec3:
        cp = math.cos(self.pitch)
        # yaw about Z (up), pitch lifts toward +Z.
        dir_to_eye = (
            -math.sin(self.yaw) * cp,
            -math.cos(self.yaw) * cp,
            math.sin(self.pitch),
        )
        return (self.target[0] + dir_to_eye[0] * self.distance,
                self.target[1] + dir_to_eye[1] * self.distance,
                self.target[2] + dir_to_eye[2] * self.distance)

    def up(self) -> Vec3:
        return (0.0, 0.0, 1.0)


def _look_at(eye: Vec3, target: Vec3, up: Vec3):
    """Right-handed view matrix as 4x4 row-list (row-major)."""
    f = _norm(_sub(target, eye))      # forward
    s = _norm(_cross(f, up))          # right
    u = _cross(s, f)                  # true up
    return [
        [ s[0],  s[1],  s[2], -_dot(s, eye)],
        [ u[0],  u[1],  u[2], -_dot(u, eye)],
        [-f[0], -f[1], -f[2],  _dot(f, eye)],
        [ 0.0,   0.0,   0.0,   1.0],
    ]


def _perspective(fov_y: float, aspect: float, near: float, far: float):
    fy = 1.0 / math.tan(fov_y / 2.0)
    fx = fy / aspect
    nf = 1.0 / (near - far)
    return [
        [fx, 0.0, 0.0, 0.0],
        [0.0, fy, 0.0, 0.0],
        [0.0, 0.0, (far + near) * nf, 2.0 * far * near * nf],
        [0.0, 0.0, -1.0, 0.0],
    ]


def _mat_vec4(m, v):
    return [sum(m[r][c] * v[c] for c in range(4)) for r in range(4)]


def project(world: Vec3, cam: "OrbitCamera",
            viewport: Tuple[int, int]) -> Tuple[float, float, float, bool]:
    """Project a world point to screen pixels (top-left origin).
    Returns (sx, sy, ndc_depth, visible). visible is False when the point is
    behind the camera or outside the clip volume."""
    w, h = viewport
    aspect = (w / h) if h else 1.0
    view = _look_at(cam.eye(), cam.target, cam.up())
    proj = _perspective(cam.fov_y_rad, aspect, cam.near, cam.far)
    vp = [[sum(proj[r][k] * view[k][c] for k in range(4)) for c in range(4)]
          for r in range(4)]
    clip = _mat_vec4(vp, [world[0], world[1], world[2], 1.0])
    if clip[3] <= 1e-6:
        return (0.0, 0.0, 0.0, False)
    ndc_x, ndc_y, ndc_z = clip[0]/clip[3], clip[1]/clip[3], clip[2]/clip[3]
    visible = -1.0 <= ndc_z <= 1.0
    sx = (ndc_x * 0.5 + 0.5) * w
    sy = (1.0 - (ndc_y * 0.5 + 0.5)) * h   # flip Y to top-left origin
    return (sx, sy, ndc_z, visible)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/ui/test_ship_property_viewer.py -k "orbit or project" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer.py tests/ui/test_ship_property_viewer.py
git commit -m "feat(viewer): orbit camera + world-to-screen projection"
```

---

### Task A3: Descriptor builder (walk player ship subsystems)

**Files:**
- Modify: `engine/ui/ship_property_viewer.py`
- Test: `tests/ui/test_ship_property_viewer.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/ui/test_ship_property_viewer.py
from engine.ui.ship_property_viewer import build_descriptors


class _StubSubsystem:
    def __init__(self, name, pos, cls_icon, disabled=False, condition=1.0):
        self._name, self._pos, self._icon = name, pos, cls_icon
        self._disabled, self._condition = disabled, condition
        self.parent_ship = None
    def GetName(self): return self._name
    def GetPosition(self):
        return None if self._pos is None else TGPoint3(*self._pos)
    def _climb_to_ship(self): return self.parent_ship
    def IsDisabled(self): return self._disabled
    def GetCondition(self): return self._condition


class _StubShip:
    def __init__(self, subs):
        self._subs = subs
        for s in subs:
            s.parent_ship = self
    def GetWorldLocation(self): return TGPoint3(0.0, 0.0, 0.0)
    def GetWorldRotation(self): return TGMatrix3()
    def __iter__(self): return iter(self._subs)


def test_build_descriptors_skips_subsystems_without_mount(monkeypatch):
    import engine.ui.ship_property_viewer as spv
    monkeypatch.setattr(spv, "_icon_id_for", lambda sub: 2)        # Phaser
    monkeypatch.setattr(spv, "_iter_subsystems", lambda ship: list(ship))
    mounted = _StubSubsystem("Dorsal Phaser 1", (0.0, 1.0, 0.5), 2)
    floating = _StubSubsystem("Abstract System", None, 6)
    ship = _StubShip([mounted, floating])
    descs = build_descriptors(ship)
    assert [d["name"] for d in descs] == ["Dorsal Phaser 1"]
    d = descs[0]
    assert d["icon_id"] == 2
    assert d["world_pos"] == (0.0, 1.0, 0.5)
    assert d["state"] in ("healthy", "damaged", "disabled", "destroyed")
    assert d["properties"]["name"] == "Dorsal Phaser 1"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/ui/test_ship_property_viewer.py -k descriptors -q`
Expected: FAIL — `cannot import name 'build_descriptors'`.

- [ ] **Step 3: Implement the builder**

```python
# add to engine/ui/ship_property_viewer.py

def _iter_subsystems(ship):
    """Yield damage-relevant subsystems of a ship. Mirrors
    engine.ui.ship_display_panel._iter_damage_subsystems; kept thin so a stub
    ship iterable works in tests."""
    try:
        from engine.ui.ship_display_panel import _iter_damage_subsystems
        return list(_iter_damage_subsystems(ship))
    except Exception:
        return list(ship)  # stub fallback


def _icon_id_for(sub) -> int:
    from engine.ui import damage_icons
    return damage_icons.icon_num_for_subsystem(sub)


def _state_for(sub) -> str:
    """healthy/damaged/disabled/destroyed predicate ladder (mirrors
    ship_display_panel._row_state)."""
    try:
        if hasattr(sub, "GetCondition") and sub.GetCondition() <= 0.0:
            return "destroyed"
        if hasattr(sub, "IsDisabled") and sub.IsDisabled():
            return "disabled"
        if hasattr(sub, "GetCondition") and sub.GetCondition() < 1.0:
            return "damaged"
    except Exception:
        pass
    return "healthy"


def _properties_for(sub) -> dict:
    def _safe(getter, default=None):
        try:
            return getter()
        except Exception:
            return default
    pos = _safe(sub.GetPosition) if hasattr(sub, "GetPosition") else None
    return {
        "name":      _safe(getattr(sub, "GetName", lambda: None)) or "<unnamed>",
        "type":      type(sub).__name__,
        "condition": _safe(getattr(sub, "GetCondition", lambda: None)),
        "disabled":  bool(_safe(getattr(sub, "IsDisabled", lambda: False))),
        "position":  None if pos is None else (pos.x, pos.y, pos.z),
    }


def build_descriptors(ship) -> List[dict]:
    """One descriptor per subsystem that has a 3D mount. Subsystems with no
    GetPosition() are skipped (cannot be placed in space)."""
    out: List[dict] = []
    for sub in _iter_subsystems(ship):
        local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
        if local is None:
            continue
        w = subsystem_world_position(sub)
        out.append({
            "name":       _properties_for(sub)["name"],
            "icon_id":    _icon_id_for(sub),
            "world_pos":  (w.x, w.y, w.z),
            "state":      _state_for(sub),
            "properties": _properties_for(sub),
        })
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/ui/test_ship_property_viewer.py -k descriptors -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer.py tests/ui/test_ship_property_viewer.py
git commit -m "feat(viewer): subsystem descriptor builder"
```

---

### Task A4: Pin picking

**Files:**
- Modify: `engine/ui/ship_property_viewer.py`
- Test: `tests/ui/test_ship_property_viewer.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/ui/test_ship_property_viewer.py
from engine.ui.ship_property_viewer import pick_pin, PIN_RADIUS_PX


def test_pick_returns_nearest_pin_within_radius():
    cam = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0, yaw=0.0, pitch=0.0)
    descs = [
        {"name": "A", "world_pos": (0.0, 0.0, 0.0)},   # screen centre
        {"name": "B", "world_pos": (3.0, 0.0, 0.0)},   # off to one side
    ]
    idx = pick_pin(400.0, 300.0, descs, cam, (800, 600))
    assert idx == 0


def test_pick_returns_none_when_click_misses_all_pins():
    cam = OrbitCamera(target=(0.0, 0.0, 0.0), distance=10.0, yaw=0.0, pitch=0.0)
    descs = [{"name": "A", "world_pos": (0.0, 0.0, 0.0)}]
    idx = pick_pin(400.0 + PIN_RADIUS_PX + 50.0, 300.0, descs, cam, (800, 600))
    assert idx is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/ui/test_ship_property_viewer.py -k pick -q`
Expected: FAIL — `cannot import name 'pick_pin'`.

- [ ] **Step 3: Implement picking**

```python
# add to engine/ui/ship_property_viewer.py

PIN_RADIUS_PX = 18.0  # click target radius in screen pixels


def pick_pin(cursor_x: float, cursor_y: float, descriptors: List[dict],
             cam: "OrbitCamera", viewport: Tuple[int, int]) -> Optional[int]:
    """Index of the nearest visible pin whose screen disc contains the cursor,
    or None. Nearest-by-screen-distance wins on overlap."""
    best_idx: Optional[int] = None
    best_d2 = PIN_RADIUS_PX * PIN_RADIUS_PX
    for i, d in enumerate(descriptors):
        sx, sy, _depth, visible = project(d["world_pos"], cam, viewport)
        if not visible:
            continue
        dx, dy = sx - cursor_x, sy - cursor_y
        d2 = dx*dx + dy*dy
        if d2 <= best_d2:
            best_d2 = d2
            best_idx = i
    return best_idx
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/ui/test_ship_property_viewer.py -k pick -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer.py tests/ui/test_ship_property_viewer.py
git commit -m "feat(viewer): pin picking by screen-space nearest hit"
```

---

### Task A5: `ShipPropertyViewerPanel` lifecycle + render payload

**Files:**
- Create: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_panel.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_ship_property_viewer_panel.py
import json
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel


def test_panel_starts_closed_and_payload_is_hide():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    assert p.is_open() is False
    payload = p.render_payload()
    assert payload is not None and "setShipPropertyViewer" in payload
    assert json.loads(payload[payload.index("(")+1:payload.rindex(")")])["visible"] is False


def test_open_builds_descriptors_and_payload_lists_subsystems(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    fake = [{"name": "Phaser 1", "icon_id": 2, "world_pos": (0, 1, 0),
             "state": "healthy", "properties": {"name": "Phaser 1"}}]
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: fake)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    assert p.is_open() is True
    payload = p.render_payload()
    data = json.loads(payload[payload.index("(")+1:payload.rindex(")")])
    assert data["visible"] is True
    assert data["pin_count"] == 1


def test_close_resets_and_emits_hide():
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p.open(); p.close()
    assert p.is_open() is False
    assert p.selected_index is None


def test_select_pin_sets_popover_payload(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    fake = [{"name": "Phaser 1", "icon_id": 2, "world_pos": (0, 1, 0),
             "state": "healthy", "properties": {"name": "Phaser 1", "type": "PhaserBank"}}]
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: fake)
    p = ShipPropertyViewerPanel(ship_getter=lambda: object())
    p.open()
    p.dispatch_event("select_pin:0")
    assert p.selected_index == 0
    data = json.loads(p.render_payload()[p.render_payload().index("(")+1:
                                          p.render_payload().rindex(")")])
    assert data["selected"]["properties"]["type"] == "PhaserBank"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the panel**

```python
# engine/ui/ship_property_viewer_panel.py
"""Ship Property Viewer pause-menu modal (Panel subclass).

Mirrors engine.ui.developer_options_panel: pumped by PanelRegistry, opened from
the dev pause menu. Snapshot-diffs its payload like the other panels.
Spec: docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md
"""
from __future__ import annotations

import json
from typing import Callable, List, Optional

from engine.ui.panel import Panel
from engine.ui.ship_property_viewer import build_descriptors, OrbitCamera


class ShipPropertyViewerPanel(Panel):
    def __init__(self, ship_getter: Callable[[], object]) -> None:
        super().__init__()
        self._ship_getter = ship_getter
        self._visible = False
        self._descriptors: List[dict] = []
        self.selected_index: Optional[int] = None
        self.camera: Optional[OrbitCamera] = None
        self._last_pushed: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "ship-property-viewer"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        ship = self._ship_getter()
        self._descriptors = build_descriptors(ship) if ship is not None else []
        self.selected_index = None
        # Frame to fit: simple heuristic — distance from the spread of mounts.
        self.camera = OrbitCamera(target=(0.0, 0.0, 0.0),
                                  distance=self._fit_distance())
        self._visible = True

    def close(self) -> None:
        self._visible = False
        self._descriptors = []
        self.selected_index = None
        self.camera = None

    def _fit_distance(self) -> float:
        if not self._descriptors:
            return 10.0
        max_r = max((sum(c*c for c in d["world_pos"])) ** 0.5
                    for d in self._descriptors)
        return max(max_r * 2.5, 5.0)

    def descriptors(self) -> List[dict]:
        return self._descriptors

    def render_payload(self) -> Optional[str]:
        snapshot = (self._visible, len(self._descriptors), self.selected_index)
        if snapshot == self._last_pushed:
            return None
        self._last_pushed = snapshot
        if not self._visible:
            return "setShipPropertyViewer(" + json.dumps({"visible": False}) + ");"
        selected = None
        if self.selected_index is not None and \
           0 <= self.selected_index < len(self._descriptors):
            selected = self._descriptors[self.selected_index]
        payload = {
            "visible": True,
            "pin_count": len(self._descriptors),
            "selected": selected,
        }
        return "setShipPropertyViewer(" + json.dumps(payload) + ");"

    def invalidate(self) -> None:
        self._last_pushed = None

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        if action.startswith("select_pin:"):
            try:
                idx = int(action.split(":", 1)[1])
            except ValueError:
                return False
            if 0 <= idx < len(self._descriptors):
                self.selected_index = idx
                self._last_pushed = None  # force re-push of popover
                return True
            return False
        if action == "deselect":
            self.selected_index = None
            self._last_pushed = None
            return True
        return False
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel.py
git commit -m "feat(viewer): ShipPropertyViewerPanel lifecycle + payload"
```

---

## Phase B — OpenGL passes (implement + run-app verify)

> These tasks cannot be pytest-driven (they render). Verify each by running `./build/dauntless` in developer mode and observing. **Remember: shader file changes require `cmake -B build -S .` (reconfigure) before `cmake --build build -j`.**

### Task B1: Pipeline shader accessors for the two passes

**Files:**
- Modify: `native/src/renderer/include/renderer/pipeline.h`, `native/src/renderer/pipeline.cc`

- [ ] **Step 1: Add accessors mirroring `phaser_shader()`**

In `pipeline.h`, next to the `phaser_shader()` declaration, add:

```cpp
    Shader& hologram_shader();
    Shader& subsystem_pin_shader();
```

In `pipeline.cc`, mirror exactly how `phaser_shader()` is implemented (lazy-compile from the shader paths). Use shader paths `shaders/hologram.vert`/`.frag` and `shaders/subsystem_pin.vert`/`.frag`. Match the existing member/storage pattern used for the phaser shader (find it with `grep -n "phaser_shader" native/src/renderer/pipeline.cc`).

- [ ] **Step 2: Create placeholder shader files so the build links**

`native/src/renderer/shaders/hologram.vert`:

```glsl
#version 330 core
layout(location = 0) in vec3 a_pos;
layout(location = 1) in vec3 a_normal;
uniform mat4 u_model;
uniform mat4 u_view_proj;
uniform vec3 u_camera_pos;
out vec3 v_world_pos;
out vec3 v_world_normal;
void main() {
    vec4 wp = u_model * vec4(a_pos, 1.0);
    v_world_pos = wp.xyz;
    v_world_normal = mat3(u_model) * a_normal;
    gl_Position = u_view_proj * wp;
}
```

`native/src/renderer/shaders/hologram.frag`:

```glsl
#version 330 core
in vec3 v_world_pos;
in vec3 v_world_normal;
uniform vec3 u_camera_pos;
uniform vec3 u_color;          // holographic blue
uniform float u_opacity_facing;  // 0.05
uniform float u_opacity_grazing; // 0.50
out vec4 frag;
void main() {
    vec3 N = normalize(v_world_normal);
    vec3 V = normalize(u_camera_pos - v_world_pos);
    float d = abs(dot(N, V));
    float opacity = u_opacity_grazing - (u_opacity_grazing - u_opacity_facing) * d;
    frag = vec4(u_color * opacity, opacity);
}
```

`native/src/renderer/shaders/subsystem_pin.vert`:

```glsl
#version 330 core
// Per-vertex unit quad corner in [-0.5,0.5]; instance center via uniform.
layout(location = 0) in vec2 a_corner;
uniform mat4 u_view_proj;
uniform vec3 u_center_world;
uniform vec3 u_camera_right;   // camera basis for billboarding
uniform vec3 u_camera_up;
uniform float u_size_world;    // quad size, distance-compensated on CPU
out vec2 v_uv;
void main() {
    vec3 offset = (u_camera_right * a_corner.x + u_camera_up * a_corner.y) * u_size_world;
    v_uv = a_corner + vec2(0.5);
    gl_Position = u_view_proj * vec4(u_center_world + offset, 1.0);
}
```

`native/src/renderer/shaders/subsystem_pin.frag`:

```glsl
#version 330 core
in vec2 v_uv;
uniform sampler2D u_glyph;     // black ink on transparent
out vec4 frag;
void main() {
    // White circular disc; black glyph composited on top.
    vec2 c = v_uv - vec2(0.5);
    float r = length(c);
    if (r > 0.5) discard;            // circular pin
    float ink = texture(u_glyph, v_uv).a;   // glyph coverage
    vec3 col = mix(vec3(1.0), vec3(0.0), ink);  // white disc, black glyph
    frag = vec4(col, 1.0);
}
```

- [ ] **Step 3: Reconfigure + build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: links cleanly (passes not yet wired; accessors compile).

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/include/renderer/pipeline.h native/src/renderer/pipeline.cc native/src/renderer/shaders/hologram.vert native/src/renderer/shaders/hologram.frag native/src/renderer/shaders/subsystem_pin.vert native/src/renderer/shaders/subsystem_pin.frag
git commit -m "feat(renderer): hologram + subsystem-pin shaders and pipeline accessors"
```

---

### Task B2: `HologramPass`

**Files:**
- Create: `native/src/renderer/include/renderer/hologram_pass.h`, `native/src/renderer/hologram_pass.cc`
- Modify: `native/src/renderer/CMakeLists.txt`

- [ ] **Step 1: Header**

```cpp
// native/src/renderer/include/renderer/hologram_pass.h
#pragma once
#include <glm/glm.hpp>
#include <scenegraph/camera.h>

namespace scenegraph { class World; }

namespace renderer {
class Pipeline;

struct HologramShip {
    bool      active = false;
    int       instance_id = -1;     // scenegraph instance to re-draw
    glm::vec3 color = glm::vec3(0.30f, 0.62f, 1.0f);
    float     opacity_facing = 0.05f;
    float     opacity_grazing = 0.50f;
};

class HologramPass {
public:
    void render(const HologramShip& ship,
                const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline);
};
}  // namespace renderer
```

- [ ] **Step 2: Implementation**

```cpp
// native/src/renderer/hologram_pass.cc
#include "renderer/hologram_pass.h"
#include "renderer/pipeline.h"
#include <scenegraph/world.h>
#include <glad/glad.h>

namespace renderer {

void HologramPass::render(const HologramShip& ship,
                          const scenegraph::World& world,
                          const scenegraph::Camera& camera,
                          Pipeline& pipeline) {
    if (!ship.active || ship.instance_id < 0) return;
    const auto* inst = world.find_instance(ship.instance_id);  // see note
    if (inst == nullptr) return;

    auto& shader = pipeline.hologram_shader();
    shader.use();
    const glm::mat4 vp = camera.proj_matrix() * camera.view_matrix();
    shader.set_mat4 ("u_view_proj", vp);
    shader.set_mat4 ("u_model",     inst->world_matrix());      // see note
    shader.set_vec3 ("u_camera_pos", camera.eye());             // see note
    shader.set_vec3 ("u_color",      ship.color);
    shader.set_float("u_opacity_facing",  ship.opacity_facing);
    shader.set_float("u_opacity_grazing", ship.opacity_grazing);

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);     // additive, like phaser_pass
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);

    inst->draw_geometry();                  // see note: reuse mesh VAO draw

    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
}
}  // namespace renderer
```

> **Implementation note for the engineer:** `world.find_instance`, `inst->world_matrix()`, `inst->draw_geometry()`, and `camera.eye()` are placeholders for whatever the scenegraph already exposes. Before writing this, run:
> `grep -n "world_matrix\|draw\|class Instance\|find_instance\|render_instance" native/src/scenegraph/include/scenegraph/world.h`
> and `grep -n "eye\|position\|view_matrix" native/src/scenegraph/include/scenegraph/camera.h`
> Use the **actual** mesh-draw entry point the main opaque pass uses (see `pipeline.cc` where it iterates `g_world` instances). The hologram pass re-draws the *same* mesh with the hologram shader bound — do not duplicate VAO setup.

- [ ] **Step 3: Add to CMake**

In `native/src/renderer/CMakeLists.txt`, add `hologram_pass.cc` to the renderer sources list (next to `phaser_pass.cc`).

- [ ] **Step 4: Reconfigure + build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: compiles. (Not yet wired into a frame; verified in B4/Phase D.)

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/hologram_pass.h native/src/renderer/hologram_pass.cc native/src/renderer/CMakeLists.txt
git commit -m "feat(renderer): HologramPass (Fresnel translucent ship)"
```

---

### Task B3: `SubsystemPinPass`

**Files:**
- Create: `native/src/renderer/include/renderer/subsystem_pin_pass.h`, `native/src/renderer/subsystem_pin_pass.cc`
- Modify: `native/src/renderer/CMakeLists.txt`

- [ ] **Step 1: Header**

```cpp
// native/src/renderer/include/renderer/subsystem_pin_pass.h
#pragma once
#include <cstdint>
#include <memory>
#include <vector>
#include <glm/glm.hpp>
#include <scenegraph/camera.h>

namespace assets { class Texture; }

namespace renderer {
class Pipeline;

struct SubsystemPin {
    glm::vec3 world_pos;
    int       icon_id = 6;     // DamageIcons enum 0..9
    bool      highlighted = false;
};

class SubsystemPinPass {
public:
    SubsystemPinPass();
    ~SubsystemPinPass();
    void render(const std::vector<SubsystemPin>& pins,
                const scenegraph::Camera& camera,
                Pipeline& pipeline);
private:
    void ensure_quad();
    void ensure_glyphs();
    unsigned int quad_vao_ = 0, quad_vbo_ = 0;
    std::vector<std::unique_ptr<assets::Texture>> glyphs_;  // index = icon_id
    bool glyphs_loaded_ = false;
};
}  // namespace renderer
```

- [ ] **Step 2: Implementation**

```cpp
// native/src/renderer/subsystem_pin_pass.cc
#include "renderer/subsystem_pin_pass.h"
#include "renderer/pipeline.h"
#include <assets/texture.h>
#include <glad/glad.h>
#include <fstream>
#include <cstdio>

namespace renderer {
namespace {
// DamageIcons enum order (see engine/ui/damage_icons.py ICON_REGISTRY).
constexpr const char* kGlyphFiles[10] = {
    "game/data/Icons/Damage/Hull.tga",     "game/data/Icons/Damage/Impulse.tga",
    "game/data/Icons/Damage/Phaser.tga",   "game/data/Icons/Damage/Power.tga",
    "game/data/Icons/Damage/Sensor.tga",   "game/data/Icons/Damage/Shield.tga",
    "game/data/Icons/Damage/System.tga",   "game/data/Icons/Damage/Torpedo.tga",
    "game/data/Icons/Damage/Warp.tga",     "game/data/Icons/Damage/Disruptor.tga",
};
// World-space pin size: pins scale with zoom/distance (a fixed size in game
// units anchored to the hull) rather than holding a constant pixel size. Tune
// in-app. To switch to constant-screen-size instead, multiply by
// glm::length(world_pos - eye) (see commented line in render()).
constexpr float kPinWorldSize = 0.6f;
}

SubsystemPinPass::SubsystemPinPass() = default;
SubsystemPinPass::~SubsystemPinPass() {
    if (quad_vbo_) glDeleteBuffers(1, &quad_vbo_);
    if (quad_vao_) glDeleteVertexArrays(1, &quad_vao_);
}

void SubsystemPinPass::ensure_quad() {
    if (quad_vao_) return;
    const float corners[12] = {
        -0.5f,-0.5f,  0.5f,-0.5f,  0.5f,0.5f,
        -0.5f,-0.5f,  0.5f,0.5f,  -0.5f,0.5f,
    };
    glGenVertexArrays(1, &quad_vao_);
    glGenBuffers(1, &quad_vbo_);
    glBindVertexArray(quad_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, quad_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(corners), corners, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2*sizeof(float), nullptr);
    glBindVertexArray(0);
}

void SubsystemPinPass::ensure_glyphs() {
    if (glyphs_loaded_) return;
    glyphs_loaded_ = true;
    glyphs_.resize(10);
    for (int i = 0; i < 10; ++i) {
        std::ifstream in(kGlyphFiles[i], std::ios::binary);
        if (!in) { glyphs_[i] = std::make_unique<assets::Texture>(); continue; }
        std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(in)), {});
        try {
            assets::Image img = assets::decode_tga(bytes);
            glyphs_[i] = std::make_unique<assets::Texture>(
                assets::upload_image(img, /*mipmaps=*/true));
        } catch (const std::exception& e) {
            std::fprintf(stderr, "[subsystem_pin] glyph %d: %s\n", i, e.what());
            glyphs_[i] = std::make_unique<assets::Texture>();
        }
    }
}

void SubsystemPinPass::render(const std::vector<SubsystemPin>& pins,
                              const scenegraph::Camera& camera,
                              Pipeline& pipeline) {
    if (pins.empty()) return;
    ensure_quad();
    ensure_glyphs();

    auto& shader = pipeline.subsystem_pin_shader();
    shader.use();
    const glm::mat4 view = camera.view_matrix();
    const glm::mat4 vp = camera.proj_matrix() * view;
    shader.set_mat4("u_view_proj", vp);
    // Billboard basis from the inverse view rotation (rows of view = world axes).
    const glm::vec3 cam_right(view[0][0], view[1][0], view[2][0]);
    const glm::vec3 cam_up   (view[0][1], view[1][1], view[2][1]);
    shader.set_vec3("u_camera_right", cam_right);
    shader.set_vec3("u_camera_up",    cam_up);
    shader.set_int ("u_glyph", 0);

    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);  // normal alpha for icons
    glDisable(GL_DEPTH_TEST);     // pins always visible through the hull
    glDisable(GL_CULL_FACE);

    glBindVertexArray(quad_vao_);
    glActiveTexture(GL_TEXTURE0);
    for (const auto& p : pins) {
        const int id = (p.icon_id >= 0 && p.icon_id < 10) ? p.icon_id : 6;
        const auto& tex = glyphs_[id];
        glBindTexture(GL_TEXTURE_2D, (tex && tex->id()) ? tex->id() : 0);
        // World-scaled pin size (scales with zoom/distance). For constant
        // screen size instead: size *= glm::length(p.world_pos - camera.eye()).
        const float size = kPinWorldSize * (p.highlighted ? 1.3f : 1.0f);
        shader.set_vec3 ("u_center_world", p.world_pos);
        shader.set_float("u_size_world",   size);
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }
    glBindVertexArray(0);

    glEnable(GL_DEPTH_TEST);
    glEnable(GL_CULL_FACE);
    glDisable(GL_BLEND);
}
}  // namespace renderer
```

- [ ] **Step 3: Add to CMake**

Add `subsystem_pin_pass.cc` to `native/src/renderer/CMakeLists.txt` sources.

- [ ] **Step 4: Reconfigure + build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: compiles.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/subsystem_pin_pass.h native/src/renderer/subsystem_pin_pass.cc native/src/renderer/CMakeLists.txt
git commit -m "feat(renderer): SubsystemPinPass (billboard pins, Damage glyphs)"
```

---

### Task B4: Host bindings + frame wiring

**Files:**
- Modify: `native/src/host/host_bindings.cc`

- [ ] **Step 1: Own the passes and state (mirror the phaser globals near line 94)**

```cpp
#include <renderer/hologram_pass.h>
#include <renderer/subsystem_pin_pass.h>
// ... near g_phaser_pass:
renderer::HologramShip                     g_hologram_ship;
std::unique_ptr<renderer::HologramPass>    g_hologram_pass;
std::vector<renderer::SubsystemPin>        g_subsystem_pins;
std::unique_ptr<renderer::SubsystemPinPass> g_subsystem_pin_pass;
```

In renderer init (where `g_phaser_pass = std::make_unique...`):

```cpp
    g_hologram_pass     = std::make_unique<renderer::HologramPass>();
    g_subsystem_pin_pass = std::make_unique<renderer::SubsystemPinPass>();
```

In teardown (where `g_phaser_pass.reset()`):

```cpp
    g_subsystem_pins.clear();
    g_hologram_ship = renderer::HologramShip{};
    g_hologram_pass.reset();
    g_subsystem_pin_pass.reset();
```

- [ ] **Step 2: Frame render — draw after phaser (near line 304)**

```cpp
    if (g_hologram_pass && g_hologram_ship.active)
        g_hologram_pass->render(g_hologram_ship, g_world, g_camera, *g_pipeline);
    if (g_subsystem_pin_pass && !g_subsystem_pins.empty())
        g_subsystem_pin_pass->render(g_subsystem_pins, g_camera, *g_pipeline);
```

- [ ] **Step 3: Bindings (mirror `set_phaser_beams` near line 714)**

```cpp
    m.def("set_hologram_ship",
          [](int instance_id, std::array<float,3> color,
             float opacity_facing, float opacity_grazing) {
              g_hologram_ship.active = true;
              g_hologram_ship.instance_id = instance_id;
              g_hologram_ship.color = {color[0], color[1], color[2]};
              g_hologram_ship.opacity_facing = opacity_facing;
              g_hologram_ship.opacity_grazing = opacity_grazing;
          });
    m.def("clear_hologram_ship", []() { g_hologram_ship = renderer::HologramShip{}; });
    m.def("set_subsystem_pins",
          [](const std::vector<std::tuple<std::array<float,3>, int, bool>>& pins) {
              g_subsystem_pins.clear();
              g_subsystem_pins.reserve(pins.size());
              for (const auto& [pos, icon, hi] : pins) {
                  renderer::SubsystemPin p;
                  p.world_pos = {pos[0], pos[1], pos[2]};
                  p.icon_id = icon;
                  p.highlighted = hi;
                  g_subsystem_pins.push_back(p);
              }
          });
    m.def("clear_subsystem_pins", []() { g_subsystem_pins.clear(); });
```

> **Note:** match the actual pybind argument style used by `set_phaser_beams` (it may take a list of dicts or a custom caster). Run `grep -n "set_phaser_beams" -A 25 native/src/host/host_bindings.cc` and mirror that exact descriptor-unpacking style rather than the tuple form above if it differs.

- [ ] **Step 4: Reconfigure + build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: `_open_stbc_host` rebuilds, exports the four new symbols.

- [ ] **Step 5: Smoke-check the symbols exist**

Run: `uv run python -c "import sys; sys.path.insert(0,'build/python'); import _open_stbc_host as h; print(hasattr(h,'set_hologram_ship'), hasattr(h,'set_subsystem_pins'))"`
Expected: `True True`

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(host): hologram + subsystem-pin pass bindings and frame wiring"
```

---

### Task B5: `renderer.py` wrappers

**Files:**
- Modify: `engine/renderer.py`

- [ ] **Step 1: Add thin wrappers (mirror the existing `set_*` wrappers)**

```python
def set_hologram_ship(instance_id: int,
                      color=(0.30, 0.62, 1.0),
                      opacity_facing: float = 0.05,
                      opacity_grazing: float = 0.50) -> None:
    _h.set_hologram_ship(instance_id, tuple(color),
                         float(opacity_facing), float(opacity_grazing))


def clear_hologram_ship() -> None:
    _h.clear_hologram_ship()


def set_subsystem_pins(pins: list) -> None:
    """pins: list of (world_pos:(x,y,z), icon_id:int, highlighted:bool)."""
    _h.set_subsystem_pins(pins)


def clear_subsystem_pins() -> None:
    _h.clear_subsystem_pins()
```

- [ ] **Step 2: Smoke-check import**

Run: `uv run python -c "import engine.renderer as r; print(r.set_hologram_ship, r.set_subsystem_pins)"`
Expected: prints two function objects (no import error).

- [ ] **Step 3: Commit**

```bash
git add engine/renderer.py
git commit -m "feat(renderer-py): wrappers for hologram + subsystem-pin bindings"
```

---

## Phase C — CEF chrome + popover

### Task C1: CEF view (title bar + property popover)

**Files:**
- Create: `native/assets/ui-cef/js/ship_property_viewer.js`, `native/assets/ui-cef/css/ship_property_viewer.css`
- Modify: the CEF HTML host page to include them (follow exactly how `developer_options.js`/`.css` are registered — `grep -rn "developer_options" native/assets/ui-cef/`)

- [ ] **Step 1: Implement the renderer-side view**

```javascript
// native/assets/ui-cef/js/ship_property_viewer.js
// Global entry called from Python via render_payload (mirrors setDeveloperOptions).
(function () {
  function el(id) { return document.getElementById(id); }

  window.setShipPropertyViewer = function (data) {
    const root = el("spv-root");
    if (!root) return;
    if (!data || !data.visible) { root.style.display = "none"; return; }
    root.style.display = "block";
    el("spv-pincount").textContent = data.pin_count + " subsystems";

    const pop = el("spv-popover");
    if (data.selected) {
      const p = data.selected.properties || {};
      pop.style.display = "block";
      pop.innerHTML =
        '<div class="spv-pop-title">' + (data.selected.name || "") + "</div>" +
        Object.keys(p).map(function (k) {
          return '<div class="spv-row"><span>' + k + "</span><span>" +
                 String(p[k]) + "</span></div>";
        }).join("");
    } else {
      pop.style.display = "none";
    }
  };
})();
```

- [ ] **Step 2: Markup + CSS**

Add a `#spv-root` overlay block to the CEF host page (transparent full-viewport, `display:none` initially) with a title bar ("Ship Property Viewer"), a Close button that calls the panel's `cancel` action via the existing JS→Python event bridge (copy the bridge call `developer_options.js` uses for its cancel), a `#spv-pincount` label, and an absolutely-positioned `#spv-popover`. Style with the shared `cp-*` tokens / pause-menu modal CSS already used by Developer Options.

- [ ] **Step 3: Run the app and verify the overlay toggles**

Run: `cmake --build build -j && ./build/dauntless --developer`
In game: pause → confirm the overlay is hidden until the viewer opens (it won't open until Phase D wiring, so for now temporarily call `setShipPropertyViewer({visible:true,pin_count:0})` from the devtools console, or defer this visual check to Phase D).
Expected: overlay shows/hides; no console errors.

- [ ] **Step 4: Commit**

```bash
git add native/assets/ui-cef/js/ship_property_viewer.js native/assets/ui-cef/css/ship_property_viewer.css native/assets/ui-cef/*.html native/assets/ui-cef/panels/ 2>/dev/null
git commit -m "feat(ui-cef): Ship Property Viewer overlay + property popover"
```

---

## Phase D — Integration

### Task D1: Register the panel + per-frame drive in host_loop

**Files:**
- Modify: `engine/host_loop.py` (dev block near line 2051; PanelRegistry near line 2100; the per-frame update loop)

- [ ] **Step 1: Construct + register the panel (dev-only)**

In the `if dev_mode.is_enabled():` block (right after the Developer Options registration, ~line 2058):

```python
            from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel
            ship_property_viewer = ShipPropertyViewerPanel(
                ship_getter=lambda: controller.player_ship(),  # see note
            )
            dev_mode.register_dev_pause_menu_entry(
                "Ship Property Viewer", ship_property_viewer.open,
            )
```

> **Note:** use the actual accessor for the current player ship. Find it with `grep -n "player_ship\|GetPlayer\|g_kPlayer\|self.player" engine/host_loop.py`. If it is a attribute rather than a method, adjust the lambda.

Register with PanelRegistry next to the other dev panels (~line 2108):

```python
            registry.register(ship_property_viewer)
```

- [ ] **Step 2: Per-frame: when open, feed camera + descriptors to the renderer**

In the main loop where panels are pumped / camera is set, add (guarded so it is a no-op when closed):

```python
        if dev_mode.is_enabled() and ship_property_viewer.is_open():
            cam = ship_property_viewer.camera
            eye = cam.eye()
            renderer.set_camera(eye, cam.target, cam.up(),
                                cam.fov_y_rad, cam.near, cam.far)
            # Hologram: the player ship's render instance id.
            iid = controller.player_instance_id()   # see note
            if iid is not None:
                renderer.set_hologram_ship(iid)
            renderer.set_subsystem_pins([
                (d["world_pos"], d["icon_id"],
                 i == ship_property_viewer.selected_index)
                for i, d in enumerate(ship_property_viewer.descriptors())
            ])
        elif dev_mode.is_enabled():
            # Closed this frame → ensure passes are cleared once.
            renderer.clear_hologram_ship()
            renderer.clear_subsystem_pins()
```

> **Note:** `controller.player_instance_id()` is a placeholder — use the real mapping from the player ship to its scenegraph instance id (grep `instance_id`, `create_instance`, `iid` in host_loop.py to find how ships map to render instances). The hologram re-draws *that* instance.

- [ ] **Step 3: Mouse input → orbit/zoom/pick while open**

Where the panel's `handle_input` is called (or in the controller input dispatch), add handling so that, while the viewer is open: drag updates `camera.yaw/pitch`, scroll updates `camera.distance`, and a click runs `pick_pin(cursor_x, cursor_y, descriptors, camera, viewport)` → `dispatch_event("select_pin:%d" % idx)` or `"deselect"`. Use the existing cursor-position binding (`grep -n "cursor\|mouse" engine/host_loop.py engine/renderer.py`) and window-size binding for the viewport. Keep this logic in `ShipPropertyViewerPanel.handle_input(h)` so it stays testable; pass the viewport size in.

- [ ] **Step 4: Run end-to-end**

Run: `cmake --build build -j && ./build/dauntless --developer`
In game: start a mission with the player ship → pause → "Ship Property Viewer".
Expected: ship appears as a translucent blue hologram; white pins with black glyphs sit on subsystem mounts and stay visible through the hull; drag orbits, scroll zooms; clicking a pin shows its property popover; ESC/Close returns to the pause menu; reopening works; closing clears the hologram and pins.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host): wire Ship Property Viewer into the dev pause menu"
```

---

### Task D2: Tune constants + verify production is untouched

- [ ] **Step 1:** In-app, tune `OPACITY_FACING/GRAZING` (hologram look), `kPinWorldSize` (world-scaled pin size), and `PIN_RADIUS_PX` (click tolerance) until the hologram reads like brainstorm option C and pins are comfortably clickable. Note that with world-scaled pins, `PIN_RADIUS_PX` is the *click* tolerance only — the rendered pin grows/shrinks with zoom, so confirm the click target still feels right across the zoom range. Edit the constants, reconfigure if shaders changed, rebuild, re-observe.

- [ ] **Step 2:** Verify **production mode** is byte-identical: run `./build/dauntless` (no `--developer`) → confirm no "Ship Property Viewer" row, no hologram/pin passes ever active. The passes are constructed but only render when `g_hologram_ship.active` / `g_subsystem_pins` are set, which only the dev panel does.

- [ ] **Step 3:** Run the focused Python suite once more:

Run: `uv run pytest tests/ui/test_ship_property_viewer.py tests/ui/test_ship_property_viewer_panel.py -q`
Expected: all PASS.

- [ ] **Step 4: Commit any tuning**

```bash
git add -A
git commit -m "tune(viewer): hologram opacity, pin size, click tolerance"
```

---

### Task D3: Documentation

**Files:**
- Modify: `CLAUDE.md` (reference table)

- [ ] **Step 1:** Add a row to the CLAUDE.md reference table:

```
| Ship Property Viewer | `engine/ui/ship_property_viewer.py`, `engine/ui/ship_property_viewer_panel.py`, `native/src/renderer/{hologram_pass,subsystem_pin_pass}.cc`, `native/assets/ui-cef/js/ship_property_viewer.js`, `docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md` | Developer-only "Ship Property Viewer" pause-menu modal: player ship rendered as a Fresnel hologram (opacity 0.05 facing → 0.50 grazing, blue back-face glow) with camera-facing billboard pins per subsystem (white disc + class Damage glyph) at `subsystem_world_position` mounts. Click a pin → property popover. Two GL passes parameterised by `(camera, viewport_rect)` for a future render-to-texture windowed mode. Dev-mode gated; production render path untouched. |
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record Ship Property Viewer in CLAUDE.md reference table"
```

---

## Self-Review notes (addressed)

- **Spec coverage:** full-viewport hologram (B2/B4/D1), Fresnel opacity 0.05→0.50 (B1 frag), back-face blue glow (B1), billboard pins white-disc+black-glyph from Damage TGAs (B3), pins-on-top depth-off (B3), descriptor builder from player ship reusing status-panel pattern (A3), `subsystem_world_position` no-scale shared helper (A1), pick math in pure Python (A2/A4), `(camera, viewport_rect)` A→B seam (cameras owned in Python + passes take camera; viewport read for projection), click-pin popover (C1/A5/D1), dev-only pause-menu registration (D1), world pauses / frozen snapshot (open() builds once), neutral pins + state in readout (A3/C1), production untouched (D2). All covered.
- **Edge cases:** subsystems without a mount skipped (A3); missing glyph TGA → white disc only (B3); no player ship → empty hologram (A5 `open` guards `ship is None`).
- **Type consistency:** `set_subsystem_pins` takes `(world_pos, icon_id, highlighted)` tuples in both the binding (B4) and the host_loop caller (D1); `SubsystemPin.icon_id`/`DamageIcons` enum 0..9 consistent across B3/A3; `setShipPropertyViewer` payload keys (`visible`, `pin_count`, `selected`) match between A5 and C1.
- **Placeholders:** scenegraph mesh-draw / player-instance / cursor accessors are explicitly flagged as "find the real symbol" notes with the exact grep to run, because those names live in code not quoted in this plan — not silent TODOs.
