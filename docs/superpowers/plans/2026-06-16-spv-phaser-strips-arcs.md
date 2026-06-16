# SPV Phaser Strips & Firing Arcs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render every phaser bank's emitter strip in yellow (always) and the selected bank's firing arc as a cyan wireframe, inside the developer-only Ship Property Viewer (SPV).

**Architecture:** A new pure-Python module builds strip/arc geometry as `PhaserBeamDescriptor` dicts; the SPV host-loop block pushes them through a dedicated, isolated overlay beam buffer rendered by the existing `PhaserPass` (depth-test off) only in `viewer_mode`. No new shader.

**Tech Stack:** Python (engine), pybind11 host bindings, C++/OpenGL renderer (`PhaserPass`), pytest.

**Spec:** `docs/superpowers/specs/2026-06-16-spv-phaser-strips-and-arcs-design.md`

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `engine/ui/phaser_overlay.py` | Pure-Python geometry: strip + arc beam descriptors, bank enumeration, selection | Create |
| `tests/unit/test_phaser_overlay.py` | Unit tests for the overlay geometry | Create |
| `engine/ui/ship_property_viewer_panel.py` | Expose `selected_name()` for the host loop | Modify |
| `tests/ui/test_ship_property_viewer.py` | Test `selected_name()` | Modify |
| `engine/renderer.py` | `set_spv_overlay_beams` / `clear_spv_overlay_beams` wrappers | Modify |
| `tests/.../test_renderer_spv_overlay.py` | Test the wrappers pass through `_h` | Create |
| `native/src/renderer/include/renderer/phaser_pass.h` | `depth_test` flag on `render()` | Modify |
| `native/src/renderer/phaser_pass.cc` | Honor `depth_test` flag | Modify |
| `native/src/host/host_bindings.cc` | `g_spv_overlay_beams` + bindings + viewer-mode render call + DRY helper | Modify |
| `engine/host_loop.py` | Push/clear overlay in the SPV viewer block | Modify |

---

## Task 1: Overlay module — vector math + strip beams

**Files:**
- Create: `engine/ui/phaser_overlay.py`
- Test: `tests/unit/test_phaser_overlay.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_phaser_overlay.py
"""Phaser strip/arc overlay geometry (Ship Property Viewer).
Spec: docs/superpowers/specs/2026-06-16-spv-phaser-strips-and-arcs-design.md
"""
import math

import pytest

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.properties import PhaserProperty
from engine.appc.subsystems import PhaserBank
from engine.ui import phaser_overlay as po


class _StubShip:
    """Identity rotation, origin position; iterable over its subsystems."""
    def __init__(self, subs):
        self._loc = TGPoint3(0.0, 0.0, 0.0)
        self._rot = TGMatrix3()  # identity
        self._subs = list(subs)
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetParentSubsystem(self): return None
    def GetParentShip(self): return self
    def __iter__(self): return iter(self._subs)


def _galaxy_dorsal1_bank(name="DorsalPhaser1"):
    """Galaxy-DorsalPhaser1-like bank (sdk/.../ships/Hardpoints/galaxy.py)."""
    bank = PhaserBank(name)
    prop = PhaserProperty(name)
    prop.SetPosition(0.0, 1.27, 0.5)
    prop.SetOrientation(TGPoint3(-1.0, 0.0, 0.0), TGPoint3(0.0, 0.0, 1.0))
    prop.SetLength(1.69)
    prop.SetWidth(1.35)
    prop.SetArcWidthAngles(-0.872665, 0.872665)        # ±50°
    prop.SetArcHeightAngles(-0.052360, 1.047198)
    bank.SetProperty(prop)
    return bank


def _dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def test_strip_outer_rim_lies_on_sphere_of_radius_length():
    bank = _galaxy_dorsal1_bank()
    ship = _StubShip([bank])
    bank._parent_ship = ship
    beams = po.build_strip_beams([bank], ship)
    assert beams, "expected strip beams"
    pos = (0.0, 1.27, 0.5)  # bank world Position (identity rotation)
    # Width=1.35 < Length=1.69, so an inner rim exists too. The OUTER rim
    # endpoints sit at radius=Length; assert at least those beams do.
    outer = [b for b in beams
             if _dist(b["emitter"], pos) == pytest.approx(1.69, abs=1e-5)]
    assert outer, "no outer-rim beam endpoints at radius=Length"
    for b in beams:
        assert b["color"] == po.STRIP_COLOR
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_phaser_overlay.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.ui.phaser_overlay'`

- [ ] **Step 3: Write the module (math helpers + strip beams)**

```python
# engine/ui/phaser_overlay.py
"""Phaser strip & firing-arc debug overlay geometry for the Ship Property Viewer.

Pure Python (no GL/CEF). Produces PhaserBeamDescriptor dicts consumed by the
renderer's phaser pass via engine.renderer.set_spv_overlay_beams.

Spec: docs/superpowers/specs/2026-06-16-spv-phaser-strips-and-arcs-design.md
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from engine.appc.subsystems import subsystem_world_position

Vec3 = Tuple[float, float, float]

# Sampling / sizing.
STRIP_SAMPLES = 24       # arc segments per strip rim sweep
ARC_SAMPLES = 24         # polyline segments per firing-arc edge
ARC_RADIUS_SCALE = 1.0   # firing-arc radius = Length * this (faithful = 1.0)
BEAM_WIDTH = 0.02        # thin overlay line half-width (game units)

# Colours (RGBA).
STRIP_COLOR = (1.0, 1.0, 0.0, 1.0)   # yellow
ARC_COLOR = (0.0, 1.0, 1.0, 1.0)     # cyan


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0]+b[0], a[1]+b[1], a[2]+b[2])


def _scale(a: Vec3, s: float) -> Vec3:
    return (a[0]*s, a[1]*s, a[2]*s)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def _norm(a: Vec3) -> Vec3:
    m = math.sqrt(_dot(a, a)) or 1.0
    return (a[0]/m, a[1]/m, a[2]/m)


def _rodrigues(v: Vec3, axis: Vec3, theta: float) -> Vec3:
    """Rotate v around unit `axis` by `theta` radians (right-handed)."""
    c = math.cos(theta)
    s = math.sin(theta)
    d = _dot(axis, v)
    cx = _cross(axis, v)
    k = d * (1.0 - c)
    return (v[0]*c + cx[0]*s + axis[0]*k,
            v[1]*c + cx[1]*s + axis[1]*k,
            v[2]*c + cx[2]*s + axis[2]*k)


def _beam(p0: Vec3, p1: Vec3, color) -> dict:
    """One PhaserBeamDescriptor dict for a straight overlay segment p0→p1."""
    return {
        "emitter": (p0[0], p0[1], p0[2]),
        "target":  (p1[0], p1[1], p1[2]),
        "color":   color,
        "width":   BEAM_WIDTH,
        "u_tiles": 1.0,
        "num_sides": 4,
        "taper_radius": BEAM_WIDTH,   # constant width (no endpoint taper)
        "taper_ratio": 0.0,
        "taper_min_length": 0.0,
        "taper_max_length": 1.0e6,
        "perimeter_tile": 1.0,
        "texture_speed": 0.0,
    }


def _polyline(points: List[Vec3], color) -> List[dict]:
    return [_beam(points[i], points[i+1], color) for i in range(len(points)-1)]


def _bank_world_frame(bank, ship):
    """(pos, forward, up, right) in world space for a phaser bank.

    Column-vector rotation: v_world = R · v_body via MultMatrixLeft(R).
    right = up × forward (matches engine.appc.subsystems convention)."""
    rot = ship.GetWorldRotation()
    fwd = bank.GetDirection()
    fwd.MultMatrixLeft(rot)
    up = bank.GetUp()
    up.MultMatrixLeft(rot)
    fwd_t = _norm((fwd.x, fwd.y, fwd.z))
    up_t = _norm((up.x, up.y, up.z))
    right_t = _norm(_cross(up_t, fwd_t))
    w = subsystem_world_position(bank, ship)
    return ((w.x, w.y, w.z), fwd_t, up_t, right_t)


def build_strip_beams(banks, ship) -> List[dict]:
    """Yellow beams tracing each bank's emitter strip: an arc of radius=Length
    around the mount Position swept across ArcWidthAngles around Up, plus an
    inner rim at Length−Width and two end-caps when Width>0."""
    beams: List[dict] = []
    for bank in banks:
        length = float(bank.GetLength())
        if length <= 0.0:
            continue
        pos, fwd, up, _right = _bank_world_frame(bank, ship)
        yaw_lo, yaw_hi = bank.GetArcWidthAngles()
        width = float(bank.GetWidth()) if hasattr(bank, "GetWidth") else 0.0
        inner = length - width
        outer_pts: List[Vec3] = []
        inner_pts: List[Vec3] = []
        for i in range(STRIP_SAMPLES + 1):
            yaw = yaw_lo + (yaw_hi - yaw_lo) * (i / STRIP_SAMPLES)
            radial = _rodrigues(fwd, up, yaw)
            outer_pts.append(_add(pos, _scale(radial, length)))
            if width > 0.0:
                inner_pts.append(_add(pos, _scale(radial, inner)))
        beams += _polyline(outer_pts, STRIP_COLOR)
        if width > 0.0 and inner_pts:
            beams += _polyline(inner_pts, STRIP_COLOR)
            beams.append(_beam(outer_pts[0], inner_pts[0], STRIP_COLOR))
            beams.append(_beam(outer_pts[-1], inner_pts[-1], STRIP_COLOR))
    return beams
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_phaser_overlay.py -q`
Expected: PASS

- [ ] **Step 5: Add strip-sweep + width-gating tests**

```python
def test_strip_spans_arc_width_angles():
    import pytest
    bank = _galaxy_dorsal1_bank()
    ship = _StubShip([bank])
    bank._parent_ship = ship
    beams = po.build_strip_beams([bank], ship)
    pos = (0.0, 1.27, 0.5)
    # First outer sample at yaw_lo, last at yaw_hi. Identity rotation:
    # world forward = body (-1,0,0); up = (0,0,1). radial(yaw) = forward
    # rotated about +Z by yaw.
    fwd = (-1.0, 0.0, 0.0)
    up = (0.0, 0.0, 1.0)
    expect_lo = po._add(pos, po._scale(po._rodrigues(fwd, up, -0.872665), 1.69))
    # The very first beam's emitter is the yaw_lo outer-rim point.
    assert beams[0]["emitter"] == pytest.approx(expect_lo, abs=1e-6)


def test_inner_rim_and_caps_only_when_width_positive():
    bank = _galaxy_dorsal1_bank()
    bank.GetProperty().SetWidth(0.0)   # zero width → no inner rim / caps
    ship = _StubShip([bank])
    bank._parent_ship = ship
    beams = po.build_strip_beams([bank], ship)
    # Only the outer rim polyline: exactly STRIP_SAMPLES segments.
    assert len(beams) == po.STRIP_SAMPLES
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/unit/test_phaser_overlay.py -q`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add engine/ui/phaser_overlay.py tests/unit/test_phaser_overlay.py
git commit -m "feat(spv): phaser emitter-strip overlay geometry"
```

---

## Task 2: Overlay module — firing-arc wireframe

**Files:**
- Modify: `engine/ui/phaser_overlay.py`
- Test: `tests/unit/test_phaser_overlay.py`

- [ ] **Step 1: Write the failing test**

```python
def test_arc_wireframe_has_four_edges_at_radius_length():
    import pytest
    bank = _galaxy_dorsal1_bank()
    ship = _StubShip([bank])
    bank._parent_ship = ship
    beams = po.build_arc_beams(bank, ship)
    # 4 edges × ARC_SAMPLES segments each.
    assert len(beams) == 4 * po.ARC_SAMPLES
    pos = (0.0, 1.27, 0.5)
    radius = 1.69 * po.ARC_RADIUS_SCALE
    for b in beams:
        assert _dist(b["emitter"], pos) == pytest.approx(radius, abs=1e-5)
        assert _dist(b["target"], pos) == pytest.approx(radius, abs=1e-5)
        assert b["color"] == po.ARC_COLOR
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_phaser_overlay.py::test_arc_wireframe_has_four_edges_at_radius_length -q`
Expected: FAIL — `AttributeError: module 'engine.ui.phaser_overlay' has no attribute 'build_arc_beams'`

- [ ] **Step 3: Implement `build_arc_beams` (append to the module)**

```python
def _arc_direction(fwd: Vec3, up: Vec3, right: Vec3,
                   yaw: float, pitch: float) -> Vec3:
    """Aim direction at (yaw about Up, pitch about the yawed Right axis).
    Mirrors the yaw/pitch decomposition in engine.appc.weapon_subsystems."""
    radial = _rodrigues(fwd, up, yaw)
    right_yaw = _norm(_rodrigues(right, up, yaw))
    return _rodrigues(radial, right_yaw, pitch)


def build_arc_beams(bank, ship) -> List[dict]:
    """Cyan wireframe of a bank's firing envelope: 4 swept edges of the
    yaw×pitch rectangle at radius = Length × ARC_RADIUS_SCALE around the
    mount Position."""
    length = float(bank.GetLength()) * ARC_RADIUS_SCALE
    if length <= 0.0:
        return []
    pos, fwd, up, right = _bank_world_frame(bank, ship)
    yaw_lo, yaw_hi = bank.GetArcWidthAngles()
    pitch_lo, pitch_hi = bank.GetArcHeightAngles()

    def _edge(yaw_of_t, pitch_of_t) -> List[Vec3]:
        pts: List[Vec3] = []
        for i in range(ARC_SAMPLES + 1):
            t = i / ARC_SAMPLES
            d = _arc_direction(fwd, up, right, yaw_of_t(t), pitch_of_t(t))
            pts.append(_add(pos, _scale(d, length)))
        return pts

    def _yaw(t):   return yaw_lo + (yaw_hi - yaw_lo) * t
    def _pitch(t): return pitch_lo + (pitch_hi - pitch_lo) * t

    beams: List[dict] = []
    beams += _polyline(_edge(_yaw, lambda t: pitch_hi), ARC_COLOR)   # top
    beams += _polyline(_edge(_yaw, lambda t: pitch_lo), ARC_COLOR)   # bottom
    beams += _polyline(_edge(lambda t: yaw_lo, _pitch), ARC_COLOR)   # left
    beams += _polyline(_edge(lambda t: yaw_hi, _pitch), ARC_COLOR)   # right
    return beams
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_phaser_overlay.py::test_arc_wireframe_has_four_edges_at_radius_length -q`
Expected: PASS

- [ ] **Step 5: Add a degenerate-length test**

```python
def test_arc_empty_when_length_zero():
    bank = _galaxy_dorsal1_bank()
    bank.GetProperty().SetLength(0.0)
    ship = _StubShip([bank])
    bank._parent_ship = ship
    assert po.build_arc_beams(bank, ship) == []
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/unit/test_phaser_overlay.py -q`
Expected: PASS (5 tests)

- [ ] **Step 7: Commit**

```bash
git add engine/ui/phaser_overlay.py tests/unit/test_phaser_overlay.py
git commit -m "feat(spv): phaser firing-arc wireframe overlay geometry"
```

---

## Task 3: Overlay module — bank enumeration + selection

**Files:**
- Modify: `engine/ui/phaser_overlay.py`
- Test: `tests/unit/test_phaser_overlay.py`

- [ ] **Step 1: Write the failing test**

```python
def _colors(beams):
    return {b["color"] for b in beams}


def test_overlay_arc_only_for_selected_bank():
    a = _galaxy_dorsal1_bank("DorsalPhaser1")
    b = _galaxy_dorsal1_bank("DorsalPhaser2")
    ship = _StubShip([a, b])
    a._parent_ship = ship
    b._parent_ship = ship
    banks = [a, b]
    # No selection → strips only (yellow), no cyan arc.
    strips_only = po.build_phaser_overlay(ship, selected_name=None, banks=banks)
    assert po.STRIP_COLOR in _colors(strips_only)
    assert po.ARC_COLOR not in _colors(strips_only)
    # Select bank b → strips + b's arc (cyan present).
    with_arc = po.build_phaser_overlay(ship, selected_name="DorsalPhaser2",
                                       banks=banks)
    assert po.ARC_COLOR in _colors(with_arc)
    # Exactly one bank's worth of arc beams (4 × ARC_SAMPLES).
    assert sum(1 for x in with_arc if x["color"] == po.ARC_COLOR) \
        == 4 * po.ARC_SAMPLES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_phaser_overlay.py::test_overlay_arc_only_for_selected_bank -q`
Expected: FAIL — `AttributeError: ... has no attribute 'build_phaser_overlay'`

- [ ] **Step 3: Implement `phaser_banks` + `build_phaser_overlay` (append)**

```python
def phaser_banks(ship) -> List:
    """All PhaserBank subsystems on `ship` (uses the SPV's own enumeration)."""
    from engine.appc.weapon_subsystems import PhaserBank
    from engine.ui.ship_property_viewer import _iter_subsystems
    return [s for s in _iter_subsystems(ship) if isinstance(s, PhaserBank)]


def build_phaser_overlay(ship, selected_name: Optional[str] = None,
                         banks: Optional[List] = None) -> List[dict]:
    """Yellow strips for every phaser bank, plus a cyan firing arc for the
    bank whose GetName() matches `selected_name` (if it is a phaser bank).
    Pass `banks` to bypass enumeration (tests / pre-fetched lists)."""
    if ship is None:
        return []
    if banks is None:
        banks = phaser_banks(ship)
    beams = build_strip_beams(banks, ship)
    if selected_name:
        sel = next((b for b in banks if b.GetName() == selected_name), None)
        if sel is not None:
            beams += build_arc_beams(sel, ship)
    return beams
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_phaser_overlay.py::test_overlay_arc_only_for_selected_bank -q`
Expected: PASS

- [ ] **Step 5: Add an enumeration test (only PhaserBanks produce strips)**

```python
def test_phaser_banks_filters_non_phaser_subsystems():
    class _NotAPhaser:
        def GetName(self): return "Hull"
    a = _galaxy_dorsal1_bank("DorsalPhaser1")
    ship = _StubShip([a, _NotAPhaser()])
    a._parent_ship = ship
    banks = po.phaser_banks(ship)
    assert banks == [a]
```

- [ ] **Step 6: Run the full overlay test module**

Run: `uv run pytest tests/unit/test_phaser_overlay.py -q`
Expected: PASS (7 tests)

- [ ] **Step 7: Commit**

```bash
git add engine/ui/phaser_overlay.py tests/unit/test_phaser_overlay.py
git commit -m "feat(spv): phaser-overlay bank enumeration + selection"
```

---

## Task 4: Panel exposes `selected_name()`

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer.py`

- [ ] **Step 1: Write the failing test (append to the panel section of the test file)**

```python
def test_selected_name_returns_selected_descriptor_name():
    from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel
    p = ShipPropertyViewerPanel(ship_getter=lambda: None)
    p._descriptors = [{"name": "DorsalPhaser1"}, {"name": "VentralPhaser1"}]
    assert p.selected_name() is None          # nothing selected
    p.selected_index = 1
    assert p.selected_name() == "VentralPhaser1"
    p.selected_index = 99                     # out of range → None
    assert p.selected_name() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ui/test_ship_property_viewer.py::test_selected_name_returns_selected_descriptor_name -q`
Expected: FAIL — `AttributeError: 'ShipPropertyViewerPanel' object has no attribute 'selected_name'`

- [ ] **Step 3: Implement the methods (add after `descriptors()` at ~line 119)**

```python
    def selected_descriptor(self) -> Optional[dict]:
        """The currently-selected pin's descriptor, or None."""
        if self.selected_index is None:
            return None
        if 0 <= self.selected_index < len(self._descriptors):
            return self._descriptors[self.selected_index]
        return None

    def selected_name(self) -> Optional[str]:
        """Name of the selected subsystem (matches a phaser bank's GetName()
        for firing-arc overlay selection), or None."""
        d = self.selected_descriptor()
        return d["name"] if d else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ui/test_ship_property_viewer.py::test_selected_name_returns_selected_descriptor_name -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer.py
git commit -m "feat(spv): panel exposes selected_name() for overlay"
```

---

## Task 5: renderer.py wrappers

**Files:**
- Modify: `engine/renderer.py`
- Test: `tests/unit/test_renderer_spv_overlay.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_renderer_spv_overlay.py
"""renderer.set_spv_overlay_beams / clear_spv_overlay_beams pass through _h
and no-op when the host binding is absent."""
import engine.renderer as renderer


class _FakeHost:
    def __init__(self):
        self.beams = None
        self.cleared = False
    def set_spv_overlay_beams(self, beams): self.beams = beams
    def clear_spv_overlay_beams(self): self.cleared = True


def test_wrappers_pass_through(monkeypatch):
    fake = _FakeHost()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_spv_overlay_beams([{"x": 1}])
    renderer.clear_spv_overlay_beams()
    assert fake.beams == [{"x": 1}]
    assert fake.cleared is True


def test_wrappers_noop_without_binding(monkeypatch):
    class _Bare: pass
    monkeypatch.setattr(renderer, "_h", _Bare())
    # Must not raise when the host lacks the binding (pre-rebuild / headless).
    renderer.set_spv_overlay_beams([{"x": 1}])
    renderer.clear_spv_overlay_beams()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_renderer_spv_overlay.py -q`
Expected: FAIL — `AttributeError: module 'engine.renderer' has no attribute 'set_spv_overlay_beams'`

- [ ] **Step 3: Implement the wrappers (add after `clear_subsystem_pins` at ~line 414)**

```python
def set_spv_overlay_beams(beams: list) -> None:
    """Set the Ship Property Viewer phaser strip/arc overlay beams.

    `beams` is a list of PhaserBeamDescriptor dicts (engine.ui.phaser_overlay).
    No-ops silently if the host binding is unavailable (headless / pre-rebuild).
    """
    fn = getattr(_h, "set_spv_overlay_beams", None)
    if fn is not None:
        fn(beams)


def clear_spv_overlay_beams() -> None:
    """Clear the SPV phaser overlay beams. Takes effect next frame()."""
    fn = getattr(_h, "clear_spv_overlay_beams", None)
    if fn is not None:
        fn()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_renderer_spv_overlay.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/renderer.py tests/unit/test_renderer_spv_overlay.py
git commit -m "feat(spv): renderer wrappers for overlay beams"
```

---

## Task 6: PhaserPass `depth_test` flag (C++)

**Files:**
- Modify: `native/src/renderer/include/renderer/phaser_pass.h`
- Modify: `native/src/renderer/phaser_pass.cc`

No unit test (GL pass); verification is a clean build + the existing gameplay
beam path staying byte-identical (the flag defaults to `true`).

- [ ] **Step 1: Add the parameter to the header**

In `native/src/renderer/include/renderer/phaser_pass.h`, change the `render`
declaration (currently at line 24):

```cpp
    /// depth_test=false draws the beams with depth-testing disabled (always
    /// visible — used by the Ship Property Viewer overlay so strips/arcs read
    /// through the hologram hull). Defaults to true (gameplay beams occlude
    /// behind geometry as before).
    void render(const std::vector<PhaserBeamDescriptor>& beams,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                bool depth_test = true);
```

- [ ] **Step 2: Honor the flag in the .cc**

In `native/src/renderer/phaser_pass.cc`, update the signature and the GL state.

Change the function signature (line ~111):

```cpp
void PhaserPass::render(const std::vector<PhaserBeamDescriptor>& beams,
                         const scenegraph::Camera& camera,
                         Pipeline& pipeline,
                         bool depth_test) {
```

Replace the depth-enable line (currently `glEnable(GL_DEPTH_TEST);` at line 129):

```cpp
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    if (depth_test) glEnable(GL_DEPTH_TEST);
    else            glDisable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE);
```

At the end of the function, after `glDepthMask(GL_TRUE);` (line ~155), restore
depth-test so a depth-off call leaves default state for following passes:

```cpp
    glEnable(GL_CULL_FACE);
    glDepthMask(GL_TRUE);
    glEnable(GL_DEPTH_TEST);   // restore (no-op for gameplay path)
    glDisable(GL_BLEND);
```

- [ ] **Step 3: Build**

Run: `cmake --build build -j 2>&1 | grep -v "ld: warning" | tail -5`
Expected: `Built target _dauntless_host` and `Built target dauntless`, no errors.

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/include/renderer/phaser_pass.h native/src/renderer/phaser_pass.cc
git commit -m "feat(renderer): optional depth-test-off on PhaserPass::render"
```

---

## Task 7: Host bindings — overlay buffer, bindings, viewer-mode render (C++)

**Files:**
- Modify: `native/src/host/host_bindings.cc`

No unit test (host glue / GL); verification is a clean build.

- [ ] **Step 1: Declare the overlay buffer**

In `native/src/host/host_bindings.cc`, next to `g_phaser_beams` (search for
`g_phaser_beams`), add:

```cpp
std::vector<renderer::PhaserBeamDescriptor> g_spv_overlay_beams;
```

- [ ] **Step 2: Extract a DRY dict→descriptor helper and reuse it**

Above the pybind `m.def("set_phaser_beams", …)` (line ~1073), add a file-local
helper:

```cpp
static renderer::PhaserBeamDescriptor beam_from_dict(const py::dict& d) {
    renderer::PhaserBeamDescriptor b;
    auto e = d["emitter"].cast<std::tuple<float, float, float>>();
    auto t = d["target"].cast<std::tuple<float, float, float>>();
    auto c = d["color"].cast<std::tuple<float, float, float, float>>();
    b.emitter_world = {std::get<0>(e), std::get<1>(e), std::get<2>(e)};
    b.target_world  = {std::get<0>(t), std::get<1>(t), std::get<2>(t)};
    b.color         = {std::get<0>(c), std::get<1>(c), std::get<2>(c), std::get<3>(c)};
    b.width         = d["width"].cast<float>();
    b.u_tiles       = d.contains("u_tiles") ? d["u_tiles"].cast<float>() : 1.0f;
    b.num_sides        = d.contains("num_sides")        ? d["num_sides"].cast<int>()          : 6;
    b.taper_radius     = d.contains("taper_radius")     ? d["taper_radius"].cast<float>()     : 0.01f;
    b.taper_ratio      = d.contains("taper_ratio")      ? d["taper_ratio"].cast<float>()      : 0.25f;
    b.taper_min_length = d.contains("taper_min_length") ? d["taper_min_length"].cast<float>() : 5.0f;
    b.taper_max_length = d.contains("taper_max_length") ? d["taper_max_length"].cast<float>() : 30.0f;
    b.perimeter_tile   = d.contains("perimeter_tile")   ? d["perimeter_tile"].cast<float>()   : 1.0f;
    b.texture_speed    = d.contains("texture_speed")    ? d["texture_speed"].cast<float>()    : 0.0f;
    return b;
}
```

Replace the body of `set_phaser_beams` to use it:

```cpp
    m.def("set_phaser_beams",
          [](const std::vector<py::dict>& descs) {
              g_phaser_beams.clear();
              g_phaser_beams.reserve(descs.size());
              for (const auto& d : descs)
                  g_phaser_beams.push_back(beam_from_dict(d));
          },
          py::arg("beams"),
          "Set the active phaser-beam list, applied each frame().");
```

- [ ] **Step 3: Add the overlay bindings**

Immediately after the `set_phaser_beams` def, add:

```cpp
    m.def("set_spv_overlay_beams",
          [](const std::vector<py::dict>& descs) {
              g_spv_overlay_beams.clear();
              g_spv_overlay_beams.reserve(descs.size());
              for (const auto& d : descs)
                  g_spv_overlay_beams.push_back(beam_from_dict(d));
          },
          py::arg("beams"),
          "Set the Ship Property Viewer phaser strip/arc overlay beams "
          "(rendered depth-test-off in viewer_mode). Applied each frame().");

    m.def("clear_spv_overlay_beams",
          []() { g_spv_overlay_beams.clear(); },
          "Clear the SPV phaser overlay beams. Takes effect next frame().");
```

- [ ] **Step 4: Clear the buffer in the shutdown/reset path**

Find the reset block that does `g_subsystem_pins.clear();` (search
`g_subsystem_pins.clear`) and add alongside it:

```cpp
    g_spv_overlay_beams.clear();
```

- [ ] **Step 5: Render the overlay in viewer_mode**

In `frame()`, between the hologram render and the subsystem-pin render (after
the `g_hologram_pass->render(...)` block ending ~line 401, before the
`if (g_subsystem_pin_pass && !g_subsystem_pins.empty())` block), add:

```cpp
    if (viewer_mode && g_phaser_pass && !g_spv_overlay_beams.empty())
        g_phaser_pass->render(g_spv_overlay_beams, g_camera, *g_pipeline,
                              /*depth_test=*/false);
```

- [ ] **Step 6: Build**

Run: `cmake --build build -j 2>&1 | grep -v "ld: warning" | tail -5`
Expected: `Built target _dauntless_host` and `Built target dauntless`, no errors.

- [ ] **Step 7: Sanity-check the binding is present**

Run: `./build/dauntless --help >/dev/null 2>&1; python3 -c "import sys; sys.path.insert(0,'build/python'); import _dauntless_host as h; print('set_spv_overlay_beams', hasattr(h,'set_spv_overlay_beams')); print('clear_spv_overlay_beams', hasattr(h,'clear_spv_overlay_beams'))"`
Expected: both `True` (if import fails due to GL/runtime init, skip — the build success in Step 6 is the gate).

- [ ] **Step 8: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(host): SPV overlay beam buffer + bindings + viewer-mode render"
```

---

## Task 8: Wire the overlay into the SPV host-loop block

**Files:**
- Modify: `engine/host_loop.py`

- [ ] **Step 1: Push overlay beams in the open branch**

In `engine/host_loop.py`, inside the `if _spv_open:` block, immediately after
the `r.set_subsystem_pins([...])` call (the list comprehension ending just
before `r.clear_target_reticle()`), add:

```python
                # Phaser strip (always) + firing-arc (selected) overlay.
                from engine.ui.phaser_overlay import build_phaser_overlay
                r.set_spv_overlay_beams(
                    build_phaser_overlay(player,
                                         ship_property_viewer.selected_name())
                )
```

- [ ] **Step 2: Clear overlay on the open→closed edge**

In the `else:` branch's `if _spv_was_open:` block, alongside
`r.clear_subsystem_pins()`, add:

```python
                    r.clear_spv_overlay_beams()
```

- [ ] **Step 3: Run the SPV / host-loop test suites for regressions**

Run: `uv run pytest tests/ui/test_ship_property_viewer.py tests/unit/test_phaser_overlay.py -q`
Expected: PASS (all).

Run: `uv run pytest -q -k "host_loop or spv or ship_property" 2>&1 | tail -15`
Expected: PASS / no new failures.

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(spv): render phaser strips + selected firing arc in viewer"
```

---

## Task 9: Full-suite verification + manual check

- [ ] **Step 1: Run the (watchdog-capped) full test suite**

Run: `scripts/run_tests.sh 2>&1 | tail -20`
Expected: all pass (full suite ~290 MB peak per project notes).

- [ ] **Step 2: Confirm the binary is freshly built**

Run: `ls -l build/dauntless build/python/_dauntless_host.cpython-*.so`
Expected: timestamps newer than Task 7's build.

- [ ] **Step 3: Manual visual check (user-driven — not automatable)**

Launch `./build/dauntless` with `--developer`, open the Ship Property Viewer
from the pause menu. Verify:
- Yellow emitter strips appear on every phaser bank, visible through the
  hologram hull.
- Clicking a phaser bank's pin draws a cyan wireframe firing arc for that bank;
  deselecting / selecting a non-phaser pin removes the arc.
- Closing the viewer removes all overlay geometry and the gameplay scene is
  unchanged.

(No automated GL/visual test, consistent with the rest of the renderer.)

---

## Self-Review Notes

- **Spec coverage:** strips always-on yellow (Tasks 1, 8) ✓; arc on selection cyan wireframe (Tasks 2, 3, 4, 8) ✓; faithful radius=Length via `ARC_RADIUS_SCALE` (Task 2) ✓; emitter-strip-only, no mount markers (Task 1) ✓; dedicated isolated overlay buffer (Task 7) ✓; depth-off always-visible (Tasks 6, 7) ✓; renderer.py wrappers per the hasattr gotcha (Task 5) ✓; reset/clear path (Tasks 7, 8) ✓; production byte-identical when SPV closed (viewer_mode-gated render, getattr-guarded push) ✓; tests per spec's test list (Tasks 1–5) ✓.
- **Type/name consistency:** `build_strip_beams(banks, ship)`, `build_arc_beams(bank, ship)`, `build_phaser_overlay(ship, selected_name, banks)`, `phaser_banks(ship)`, `STRIP_COLOR`/`ARC_COLOR`/`ARC_RADIUS_SCALE`/`STRIP_SAMPLES`/`ARC_SAMPLES`/`BEAM_WIDTH`, panel `selected_name()`/`selected_descriptor()`, renderer `set_spv_overlay_beams`/`clear_spv_overlay_beams`, host `set_spv_overlay_beams`/`clear_spv_overlay_beams`, C++ `g_spv_overlay_beams`/`beam_from_dict`/`render(..., depth_test)` — all consistent across tasks.
- **Build gates:** every C++ task ends with the canonical `cmake --build build -j` from the project root (never `native/`); host-bindings change rebuilds both `dauntless` and `_dauntless_host`.
