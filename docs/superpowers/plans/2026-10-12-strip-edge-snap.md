# Strip Edge Snap (production) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the edge-snap spike (branch `spike/strip-edge-snap`, commits `468ca5ee`, `de12880c`) into production code: strips snap to the sharp mesh edge nearest a click, the light budget counts segments, Add Light → Strip snaps on add.

**Architecture:** The snap code moves out of `light_shapes.py` into its own pure-Python module `edge_snap.py`. `lights.py` gains one row builder, `build()`, used for both the static rows and the live colours, which counts the 32-light budget in segments and drops a light whole. The runtime switches to `build()` / `live()`. The editor passes the selecting click as the new strip's anchor. The renderer's join weighting (already in place) gets a frame test, and every `SPIKE` label becomes a spec citation.

**Tech Stack:** Python 3.11 (pytest), C++17 + GLM + GLSL 410 (gtest), pybind11, CEF JS (node-run tests).

**Spec:** `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` **§16.8** (with §16.1–16.3 for the surrounding model).

## Global Constraints

- Data stays `format: 4`. A strip may carry `anchor` `[x, y, z]`; `edge` stays required and is the fallback when no sharp edge is in reach.
- Snap constants (one block in `edge_snap.py`): `CREASE_DEG` 30, `STRAIGHT_DEG` 20, `SNAP_REACH` 20, `SNAP_TIE` 2, `SIMPLIFY_TOL` 0.5, `MAX_SEGMENTS` 6, `WASH_DEPTH` 10; weld at 0.01 units.
- Join bits: bit 0 = joined at the `-u` end, bit 1 = at `+u`; first segment `2`, middle `3`, last `1`, a lone rectangle `0`.
- Light budget: spots (1 each), strip segments and panels share **32** rows; a light that does not fit whole is dropped with a warning — never cut short.
- Warnings surface in the editor status line (`BridgeRuntime.push` → panel `_push_warnings`).
- Shared-checkout rules (CLAUDE.md): never `git checkout -- / restore / stash / clean / reset --hard / add -A / add .`; stage explicit paths. Work only in `.claude/worktrees/bridge-area-lights` on branch `spike/strip-edge-snap`.
- Commit trailer: the implementing model's own `Co-Authored-By` line (standing controller ruling).

## Review Focus

- A strip whose snap finds nothing must fall back to its edge chips AND warn — never vanish silently. (Task 2 test.)
- A light that doesn't fit the remaining budget is dropped whole, and the later, smaller lights that still fit are kept; static rows and live colours stay aligned. (Task 2 test.)
- Add Light → Strip with no click on record (the editor was opened but nothing clicked) adds an unsnapped strip, not a crash. (Task 3 test.)
- A re-snap (Snap to edge here) after clicking a *different* object must not snap to that object's geometry: `_last_hit` is the selecting click, which also changes the selection. Confirm the snap uses the selected object's mesh. (Task 3 check.)
- Shader joint weighting matches the C++ twin. (Task 4 test.)

---

### Task 1: `edge_snap` module

**Files:**
- Create: `engine/bridge_editor/edge_snap.py`
- Modify: `engine/bridge_editor/light_shapes.py` (remove the spike block; keep `Frame.vertices/eye/cache` and `Rect.joins`)
- Move: `tests/unit/test_bridge_light_snap.py` → `tests/unit/test_bridge_edge_snap.py` (`git mv`)
- Modify: `engine/bridge_editor/lights.py` (call sites only: `light_shapes.snap_edge` → `edge_snap.snap`, `light_shapes.light_rects` → `edge_snap.light_rects`)

**Interfaces:**
- Produces:
  - `edge_snap.Snap(polyline: list[Vec], surface_normal: Vec)` — frozen dataclass.
  - `edge_snap.snap(fr: light_shapes.Frame, anchor) -> Optional[Snap]` — memoised in `fr.cache`.
  - `edge_snap.strip_rects(fr, light) -> Optional[list[light_shapes.Rect]]` — one per segment, with join bits; None when `snap` is None.
  - `edge_snap.light_rects(light, fr) -> list[Rect]` — a snapped strip's rects, else `[light_shapes.light_rect(light, fr)]`.
  - The constants listed in Global Constraints.

- [ ] **Step 1: Move the tests first (they become the RED)**

`git mv tests/unit/test_bridge_light_snap.py tests/unit/test_bridge_edge_snap.py`. In it:
- replace `from engine.bridge_editor import editing, light_shapes as ls, lighting_doc as ld, lights` with `from engine.bridge_editor import edge_snap, editing, light_shapes as ls, lighting_doc as ld, lights`;
- replace every `ls.snap_edge(` with `edge_snap.snap(` and unpack via attributes: `s = edge_snap.snap(...)`, then `s.polyline`, `s.surface_normal` (rewrite each `poly, ns = ls.snap_edge(...)` as `s = edge_snap.snap(...); poly, ns = s.polyline, s.surface_normal`);
- replace `ls.snapped_strip_rects(` with `edge_snap.strip_rects(` and `ls.light_rects(` with `edge_snap.light_rects(`;
- drop the word "SPIKE" from the module docstring; cite spec §16.8 instead.

Add one test:

```python
def test_constants_match_the_spec():
    assert (edge_snap.CREASE_DEG, edge_snap.STRAIGHT_DEG, edge_snap.SNAP_REACH, edge_snap.SNAP_TIE,
            edge_snap.SIMPLIFY_TOL, edge_snap.MAX_SEGMENTS, edge_snap.WASH_DEPTH) == \
        (30.0, 20.0, 20.0, 2.0, 0.5, 6, 10.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_edge_snap.py -q`
Expected: FAIL — `ImportError: cannot import name 'edge_snap'`.

- [ ] **Step 3: Create `edge_snap.py` by MOVING the spike code**

Move, unchanged in behaviour, everything below the line `# ── SPIKE: snap a strip to the sharp edge nearest a clicked point ───` in `light_shapes.py`, plus the spike constant block (`CREASE_DEG` … `WASH_DEPTH`), into `engine/bridge_editor/edge_snap.py`, with these renames:

| spike (light_shapes) | production (edge_snap) |
|---|---|
| `snap_edge(fr, anchor) -> (poly, ns) | None` | `snap(fr, anchor) -> Snap | None` |
| `snapped_strip_rects(fr, light)` | `strip_rects(fr, light)` |
| `light_rects(light, fr)` | `light_rects(light, fr)` |
| `_welded`, `_sharp_edges`, `_closest_on_segment`, `_surface_normal`, `_walk`, `_simplify`, `_cut` | same names, private |

Module header:

```python
"""Edge snap (spec 2026-10-08-bridge-emitters §16.8): a strip with an
`anchor` (the clicked point) sits on the mesh's sharp edge nearest it,
instead of the object's box edge -- compound meshes such as DBridge's Map 3
walls hold several alcoves in one shape, so no box edge reaches an alcove's
lip. Pure Python; the triangles and eye come from the object's
light_shapes.Frame, and every result is memoised on it."""
import math
from dataclasses import dataclass
from typing import List, Optional

from engine.bridge_editor.light_shapes import (
    ROOM_UP, STRIP_WIDTH, Rect, Vec, _add, _cross, _dot, _len, _mul, _sub, _unit,
    light_rect)

CREASE_DEG = 30.0                   # faces meeting at more than this: a sharp edge
STRAIGHT_DEG = 20.0                 # a run continues while it turns less than this
SNAP_REACH = 20.0                   # bridge units: no sharp edge this near = no snap
SNAP_TIE = 2.0                      # edges this much further than the nearest still compete
SIMPLIFY_TOL = 0.5                  # a polyline vertex is kept if this far off the chord
MAX_SEGMENTS = 6                    # each segment is one area light
WASH_DEPTH = 10.0                   # a snapped strip aims this far in across the surface


@dataclass(frozen=True)
class Snap:
    polyline: List[Vec]             # left to right as seen from the clicked surface
    surface_normal: Vec             # the clicked surface, facing the eye
```

`snap()` returns `Snap(simple, ns)` where the spike returned `(simple, ns)` (and caches that object). `strip_rects` reads `s = snap(fr, light["anchor"])`, then `poly, ns = s.polyline, s.surface_normal`. Every comment that said "SPIKE" says what the code does and cites §16.8. In `light_shapes.py`: delete the moved block and the spike constants; reword the `Frame` field comment to `# the triangles and eye the frame was built from, and a per-frame memo -- used by edge_snap (§16.8)`; reword the `Rect.joins` comment to `# bit 0 / 1: joined to a neighbour at the -u / +u end (§16.8)`; remove `field` from the import only if unused (it is still used by `Frame`). In `lights.py` change the two call sites to `edge_snap.snap(...)` and `edge_snap.light_rects(...)` and import `edge_snap`; reword its `SPIKE` comment.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_bridge_edge_snap.py tests/unit/test_bridge_light_shapes.py tests/unit/test_bridge_lights.py tests/unit/test_bridge_runtime.py -q`
Expected: PASS. Then `grep -rn "SPIKE" engine/bridge_editor tests/unit/test_bridge_edge_snap.py` must print nothing.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/edge_snap.py engine/bridge_editor/light_shapes.py engine/bridge_editor/lights.py tests/unit/test_bridge_edge_snap.py tests/unit/test_bridge_light_snap.py
git commit -m "refactor(bridge): edge snap moves into its own module (spec §16.8)"
```

---

### Task 2: One row builder; the budget counts segments

**Files:**
- Modify: `engine/bridge_editor/lights.py`
- Modify: `engine/bridge_editor/runtime.py` (`push`, `_push_live`, docstrings)
- Modify: `tests/unit/test_bridge_lights.py`, `tests/unit/test_bridge_edge_snap.py`, `tests/unit/test_bridge_runtime.py` (call sites)

**Interfaces:**
- Consumes: `edge_snap.snap`, `edge_snap.light_rects`.
- Produces:
  - `lights.Built` (dataclass): `spot_rows: list`, `area_rows: list`, `warnings: list[str]`, `spot_lit: list` and `area_lit: list` of `(light, material, has_map)`, index-aligned with the rows.
  - `lights.build(doc, matched, resolved, frame_for=lambda mesh: None, mapped=frozenset()) -> Built`
  - `lights.live(built, fade, t) -> (spot_colours, area_colours)`
  - `spots()`, `areas()`, `live_colours()`, `live_area_colours()` and `_lit()`, `_areas_lit()` are REMOVED; `MAX_SPOTS` alias removed (grep first; nothing outside lights.py should use it).

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_bridge_lights.py`:

```python
# ── one builder, the budget in segments (spec §16.8) ────────────────────────

def _rects(n):
    return [ls.Rect((float(i), 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, -0.25, 0.0), 0) for i in range(n)]


def test_the_budget_counts_segments_and_drops_a_strip_whole(monkeypatch):
    from engine.bridge_editor import edge_snap
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "a")["lights"] = [
        {"position": [0, 0, i], "direction": [0, 0, -1]} for i in range(28)]
    ld.object_entry(d, 2, "b")["lights"] = [
        {"shape": "strip", "edge": "top", "anchor": [0, 0, 0]},     # 6 segments: does not fit
        {"shape": "panel"}]                                          # 1: fits
    monkeypatch.setattr(edge_snap, "light_rects",
                        lambda light, fr: _rects(6 if light["shape"] == "strip" else 1))
    monkeypatch.setattr(edge_snap, "snap", lambda fr, anchor: object())
    matched = {"1:a": 1, "2:b": 2}
    b = lights.build(d, matched, _links(d, matched), lambda m: PANEL_FRAME)
    assert len(b.spot_rows) == 28 and len(b.area_rows) == 1
    assert any("2:b light 1" in w and "dropped" in w for w in b.warnings)
    assert len(b.area_lit) == len(b.area_rows) and len(b.spot_lit) == len(b.spot_rows)


def test_live_colours_follow_the_built_rows(monkeypatch):
    d = _area_doc()
    built = lights.build(d, AREA_MATCHED, _links(d, AREA_MATCHED), lambda m: PANEL_FRAME)
    spot_cols, area_cols = lights.live(built, bh.StateFade("green"), 0.0)
    assert len(spot_cols) == len(built.spot_rows) and len(area_cols) == len(built.area_rows)


def test_a_snap_with_nothing_in_reach_warns_and_keeps_the_box_edge():
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "w")["lights"] = [
        {"shape": "strip", "edge": "top", "anchor": [900.0, 900.0, 900.0], "intensity": 4}]
    verts = [(0.0, 50.0, 10.0), (40.0, 50.0, 10.0), (40.0, 50.0, 30.0),
             (0.0, 50.0, 10.0), (40.0, 50.0, 30.0), (0.0, 50.0, 30.0)]
    eye = (20.0, 0.0, 20.0)
    fr = ls.frame(verts, ls.oriented_normal_sum(verts, eye), 800.0, eye)
    b = lights.build(d, {"1:w": 1}, {}, lambda m: fr)
    assert len(b.area_rows) == 1
    assert b.area_rows[0][0] == ls.strip_rect(fr, "top", offset=0.0).centre
    assert any("no sharp edge" in w for w in b.warnings)
```

Migrate every existing call in `test_bridge_lights.py`, `test_bridge_edge_snap.py` (its `lights.areas(...)` call) to the new API:
- `spots, warnings = lights.spots(d, m, r[, mapped=...])` → `b = lights.build(d, m, r, mapped=...); spots, warnings = b.spot_rows, b.warnings`
- `rows, warnings = lights.areas(d, m, r, frame_for)` → `b = lights.build(d, m, r, frame_for); rows, warnings = b.area_rows, b.warnings`
- `lights.live_colours(d, m, r, fade, t[, mapped=])` → `lights.live(lights.build(d, m, r, mapped=...), fade, t)[0]`
- `lights.live_area_colours(d, m, r, fade, t, frame_for)` → `lights.live(lights.build(d, m, r, frame_for), fade, t)[1]`
- `test_spots_and_area_lights_share_one_budget_in_mesh_order`: the warnings are now one list — assert `len([w for w in b.warnings if "dropped" in w]) == 8` and the first names `2:b light 13`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_bridge_lights.py -q` — Expected: FAIL (`lights.build` missing).

- [ ] **Step 3: Implement** — in `lights.py` replace `_lit`, `spots`, `_areas_lit`, `areas`, `live_colours`, `live_area_colours` (keep `to_linear`, `_is_spot`, `_intensity`, `_material`, `_capture`, `_cross_len`, the constants minus `MAX_SPOTS`) with:

```python
@dataclass
class Built:
    """The static rows for one push, and what their live colours follow."""
    spot_rows: list = field(default_factory=list)
    area_rows: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    spot_lit: list = field(default_factory=list)    # (light, material, has_map) per spot row
    area_lit: list = field(default_factory=list)    # (light, material, has_map) per area row


def build(doc, matched, resolved, frame_for=lambda mesh: None, mapped=frozenset()) -> Built:
    """Every light of every matched object, mesh order, as renderer rows (spec
    §16.3, §16.8). The budget of MAX_LIGHTS counts ROWS: a spot is one, a
    strip or panel one per rectangle (a snapped strip one per edge segment).
    A light that does not fit whole is dropped with a warning -- never cut
    short -- and a later light that still fits is kept. A strip or panel
    needs its object's frame (`frame_for(mesh)`); without one it is skipped
    with a warning."""
    out = Built()
    for key in sorted(matched, key=lambda k: matched[k]):
        obj = doc["objects"].get(key, {})
        mesh = matched[key]
        mat = _material(doc, resolved.get(mesh))
        has_map = mesh in mapped
        for i, light in enumerate(obj.get("lights", ())):
            label = f"{key} light {i + 1}"
            rects = None
            if not _is_spot(light):
                fr = frame_for(mesh)
                if fr is None:
                    out.warnings.append(f"{label}: no geometry for its object; skipped")
                    continue
                if light.get("anchor") and edge_snap.snap(fr, light["anchor"]) is None:
                    out.warnings.append(
                        f"{label}: no sharp edge near its snap point; using its edge chips")
                rects = []
                for r in edge_snap.light_rects(light, fr):
                    if _cross_len(r.half_u, r.half_v) < MIN_AREA:
                        out.warnings.append(f"{label}: zero size; skipped")
                    else:
                        rects.append(r)
                if not rects:
                    continue
            cost = 1 if rects is None else len(rects)
            used = len(out.spot_rows) + len(out.area_rows)
            if used + cost > MAX_LIGHTS:
                out.warnings.append(f"{label}: dropped (needs {cost} of the {MAX_LIGHTS} "
                                    f"bridge lights, {MAX_LIGHTS - used} left)")
                continue
            green = _capture(mat, "green", has_map)
            alert = _capture(mat, "yellow", has_map)
            if rects is None:
                out.spot_rows.append((tuple(light["position"]), tuple(light["direction"]),
                                      light.get("inner_deg", 30), light.get("outer_deg", 60),
                                      light.get("range", DEFAULT_RANGE), green,
                                      _intensity(light), green, alert))
                out.spot_lit.append((light, mat, has_map))
                continue
            for r in rects:
                out.area_rows.append((r.centre, r.half_u, r.half_v,
                                      light.get("range", DEFAULT_RANGE), green,
                                      _intensity(light), green, alert, r.joins))
                out.area_lit.append((light, mat, has_map))
    return out


def live(built, fade, t):
    """This frame's LINEAR radiance per spot row and per area row, in the
    rows' own order (spec §11.4): the material's output through the state
    fade, ^2.2, x the light's intensity."""
    def colours(lit):
        out = []
        for light, mat, has_map in lit:
            rgb, _k = fade.output(mat, t, has_map)
            k = _intensity(light)
            out.append(tuple(c * k for c in to_linear(rgb)))
        return out
    return colours(built.spot_lit), colours(built.area_lit)
```

Add `from dataclasses import dataclass, field` and `from engine.bridge_editor import behaviour, edge_snap` (drop `light_shapes` if now unused). Update the module docstring: the lists are built once per push by `build()`, live colours come from `live(built, ...)`, the budget counts rows.

In `runtime.py`:
- `push`: replace the `lights.spots(...)` and `lights.areas(...)` calls with one `built = lights.build(doc, self._matched, self._resolved, self._frame_for, self._mapped)`; store `self._built = built`; `spot_list, area_list = built.spot_rows, built.area_rows`; `warnings = ld.link_mismatches(...) + built.warnings + glow_warnings` (log each as before); keep both "dropped as invalid" native-count warnings.
- `_push_live`: `spot_cols, area_cols = lights.live(self._built, self._fade, self._t)` then `set_bridge_spot_colours(spot_cols)` and `set_bridge_area_colours(area_cols)`; if `self._built` is None push empty lists.
- `__init__`, `attach` (with `_meshes` reset), `detach`'s `finally`: `self._built = None`.
- Fix the `push` docstring paragraph that says `lights.spots already caps the list` → `lights.build already caps the rows`.
- Update `test_bridge_runtime.py`'s comment at ~line 271 the same way (text only).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit -q -k "bridge"` — Expected: PASS. Then `grep -rn "lights\.\(spots\|areas\|live_colours\|live_area_colours\|MAX_SPOTS\)" engine tests` prints nothing.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/lights.py engine/bridge_editor/runtime.py tests/unit/test_bridge_lights.py tests/unit/test_bridge_edge_snap.py tests/unit/test_bridge_runtime.py
git commit -m "feat(bridge): one row builder; the light budget counts segments (spec §16.8)"
```

---

### Task 3: Add Light → Strip snaps on add

**Files:**
- Modify: `engine/bridge_editor/editing.py` (`add_area_light`, `snap_light` docstrings)
- Modify: `engine/ui/bridge_emitters_panel.py` (`light-add` branch; `light-snap` comment)
- Modify: `native/assets/ui-cef/js/bridge_emitters.js` (strip help text; drop "SPIKE")
- Test: `tests/unit/test_bridge_editing.py`, `tests/unit/test_bridge_emitters_panel.py`, `tests/ui/test_bridge_emitters_js.py`

**Interfaces:**
- Produces: `editing.add_area_light(doc, block, name, shape, anchor=None)` — a strip with `anchor` given carries `"anchor": [x, y, z]`; panels ignore it.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_bridge_editing.py`:

```python
def test_a_strip_added_with_an_anchor_is_snapped():
    d = ld.empty_doc("x")
    editing.add_area_light(d, 5, "lip", "strip", anchor=(1, 2, 3))
    editing.add_area_light(d, 5, "lip", "panel", anchor=(1, 2, 3))
    strip, panel = d["objects"]["5:lip"]["lights"]
    assert strip["anchor"] == [1.0, 2.0, 3.0] and "anchor" not in panel
    ld.validate(d)
```

`tests/unit/test_bridge_emitters_panel.py`:

```python
def test_add_strip_snaps_at_the_selecting_click(env_rt):
    p, io, h, *_ = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add:strip")
    assert payload(p)["selected"]["lights"][0]["anchor"] == [0, 10, 50]   # FakeIO's hit point


def test_add_strip_with_no_click_on_record_is_unsnapped(env_rt):
    p, io, h, *_ = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p._last_hit = None
    p.dispatch_event("light-add:strip")
    light = payload(p)["selected"]["lights"][0]
    assert "anchor" not in light and light["edge"] == "top"
```

(If `_last_hit` is reset by a different mechanism, read `_click` / `dispatch_event` and set up "no click on record" the way the panel does; the assertion is what matters.)

`tests/ui/test_bridge_emitters_js.py` — update the two edge-snap tests' docstrings (drop "SPIKE") and add:

```python
def test_the_snap_help_says_strips_snap_on_add():
    strip = {"shape": "strip", "edge": "top", "range": 200, "intensity": 40}
    [out] = _run([{"state": _state(selected=_sel(lights=[strip], expanded=["light:0"]))}])
    assert "Not snapped" in out["body"]
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/unit/test_bridge_editing.py tests/unit/test_bridge_emitters_panel.py tests/ui/test_bridge_emitters_js.py -q`.

- [ ] **Step 3: Implement**

`editing.add_area_light`:

```python
def add_area_light(doc, block, name, shape, anchor=None):
    """A strip or a panel (spec §16.4). A strip given `anchor` -- the click
    that selected the object -- snaps to the sharp edge nearest it (§16.8);
    without one it sits on the object's top box edge. The rectangles are
    recomputed from the object at load."""
    o = ld.object_entry(doc, block, name)
    if shape == "strip":
        light = {"shape": "strip", "edge": "top", "start": 0.0, "end": 1.0,
                 "offset": STRIP_OFFSET, "range": LIGHT_RANGE, "intensity": STRIP_INTENSITY}
        if anchor is not None:
            light["anchor"] = [float(c) for c in anchor]
    elif shape == "panel":
        light = {"shape": "panel", "x": [0.0, 1.0], "y": [0.0, 1.0], "offset": 0.0,
                 "range": LIGHT_RANGE, "intensity": PANEL_INTENSITY}
    else:
        return
    o.setdefault("lights", []).append(light)
```

Reword `snap_light`'s docstring to cite §16.8 (no "SPIKE").

Panel `_edit_action`, the area branch of `light-add`:

```python
            elif shape in ld.LIGHT_SHAPES:
                anchor = self._last_hit[0] if self._last_hit is not None else None
                self._edit(lambda: editing.add_area_light(self._doc, b, n, shape, anchor))
```

Review-focus check (no code unless it fails): confirm `_last_hit` is only set by a click that also selects the clicked object (read `_click`), so a re-snap always snaps on the selected object's own mesh — state what you found in the report.

JS strip help (in `_beLightFields`): replace the two help strings with
`'Snapped to the edge nearest your click; start / end / offset still apply.'` (snapped) and
`'Not snapped: on the object\'s box edge. Click the surface to light, near its edge, then Snap.'` (unsnapped); replace the `SPIKE (edge snap)` comment with `// Edge snap (spec §16.8).`

- [ ] **Step 4: Run tests** — the Step 2 command plus `uv run pytest tests/unit -q -k bridge` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/editing.py engine/ui/bridge_emitters_panel.py native/assets/ui-cef/js/bridge_emitters.js tests/unit/test_bridge_editing.py tests/unit/test_bridge_emitters_panel.py tests/ui/test_bridge_emitters_js.py
git commit -m "feat(bridge): Add Light -> Strip snaps at the selecting click (spec §16.8)"
```

---

### Task 4: Renderer — pin the joint weighting, drop the spike labels

**Files:**
- Test: `native/tests/renderer/bridge_pbr_frame_test.cc` (append)
- Modify (comments only): `native/src/renderer/include/renderer/bridge_pbr.h`, `native/src/renderer/shaders/bridge.frag`, `native/src/renderer/include/renderer/bridge_pass.h`, `native/src/host/host_bindings.cc`, `engine/host_io.py`, `native/tests/renderer/bridge_pbr_test.cc`

**Interfaces:**
- Consumes: `renderer::BridgeAreaLight::joins`, `pbr::area_join_weight` (already present).

- [ ] **Step 1: Write the failing frame test** — append to `bridge_pbr_frame_test.cc` (it has the `area(...)` helper from the area-light tests; give it a `joins` overload or set `.joins` after constructing):

```cpp
// Spec §16.8: two JOINED halves of a strip light the floor under their joint
// like the one strip they replace; unjoined, their highlights add.
TEST_F(BridgePbrFrame, JoinedStripHalvesMatchOneStripAtTheJoint) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    set_floor_override(0.3f, 0.0f);                       // glossy enough to show the highlight
    // The camera (eye (60, 0, 90)) sees the sample (70, 0, 0) mirrored toward
    // +x: the reflected ray reaches z = 20 at x = 70 + 20 x 10/90 = 72.2, so
    // the strip runs along y there, its joint on that ray, emitting down.
    auto strip = [&](glm::vec3 c, float half_len, int joins) {
        renderer::BridgeAreaLight a = area(c, {0, half_len, 0}, {0.25f, 0, 0}, 300.0f,
                                           glm::vec3(40.0f));
        a.joins = joins;
        return a;
    };
    pass->set_area_lights({strip({72.2f, 0, 20}, 20.0f, 0)});
    const float one = render_floor().r;
    pass->set_area_lights({strip({72.2f, -10, 20}, 10.0f, 2), strip({72.2f, 10, 20}, 10.0f, 1)});
    const float joined = render_floor().r;
    pass->set_area_lights({strip({72.2f, -10, 20}, 10.0f, 0), strip({72.2f, 10, 20}, 10.0f, 0)});
    const float unjoined = render_floor().r;
    EXPECT_NEAR(joined, one, 0.02f);
    EXPECT_GT(unjoined, joined + 0.01f);                  // the doubling this guards against
}
```

Check the emitting side before trusting it: `cross(half_u, half_v)` = `cross((0, L, 0), (0.25, 0, 0))` = `(0, 0, -0.25 L)` → emits down (good). Read `corner_camera` / `eye_` / `sample_` in the fixture to confirm the eye and sample used above; if they differ, recompute the x where the mirror ray reaches z = 20 and say so in the report. Do NOT widen the tolerances beyond 0.02 / 0.01 without reporting the measured values.

- [ ] **Step 2: Run to verify** — `cmake --build build -j --target renderer_tests && build/native/tests/renderer/renderer_tests --gtest_filter='BridgePbrFrame.JoinedStripHalvesMatchOneStripAtTheJoint'`. It should PASS straight away (the weighting already exists). Prove it guards something: back up `bridge.frag` with `cp`, replace the `* area_join_weight(...)` factor in `accumulate_area_lights` with `* 1.0`, rebuild, see the test FAIL, restore with `cp`, `diff` to prove byte-identical, rebuild, PASS. Record all of it.

- [ ] **Step 3: Replace every `SPIKE` comment** in the files listed above with a plain description citing `spec §16.8` (e.g. `// Spec §16.8: a snapped strip is a chain of rectangles; ...`). No code changes. `grep -rn "SPIKE" native/src engine native/tests tests` must print nothing.

- [ ] **Step 4: Run tests** — `cmake --build build -j && build/native/tests/renderer/renderer_tests --gtest_filter='BridgePbr*'` and `uv run pytest tests/host/test_bridge_editor_bindings.py -q` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/tests/renderer/bridge_pbr_frame_test.cc native/src/renderer/include/renderer/bridge_pbr.h native/src/renderer/shaders/bridge.frag native/src/renderer/include/renderer/bridge_pass.h native/src/host/host_bindings.cc engine/host_io.py native/tests/renderer/bridge_pbr_test.cc
git commit -m "test(bridge): pin the shader's joint weighting; spike labels become spec §16.8"
```

---

### Task 5: DBridge regression — the Map 3 alcove lip

**Files:**
- Test: `tests/host/test_bridge_editor_bindings.py` (append; reuse its `dbridge` fixture)

- [ ] **Step 1: Write the test**

```python
def test_a_click_under_a_map_3_alcove_lip_snaps_to_the_curved_lip(dbridge, monkeypatch):
    """Spec §16.8: DBridge's Map 3 left wall (block 652) holds three alcoves
    in one mesh. A click under an alcove's top lip snaps to the curved lip
    run (measured 2026-10-12: 116 units, y -37..79, z 88.7..89.6)."""
    from engine.bridge_editor import edge_snap, light_shapes as ls
    h, iid = dbridge
    monkeypatch.setattr(host_io, "_h", h)
    info = host_io.model_identity(iid)
    [mesh] = [m["mesh"] for m in info["meshes"] if m["block"] == 652]
    verts, _n, area = host_io.bridge_mesh_geometry(iid, mesh)
    eye = (0.0, 0.0, 50.0)
    fr = ls.frame(verts, ls.oriented_normal_sum(verts, eye), area, eye)
    pts, tris, _normals = edge_snap._welded(fr.vertices, eye)
    target = (-170.5, 28.9, 88.6)              # just under the lip, on the wall
    centroids = [tuple(sum(pts[i][k] for i in t) / 3.0 for k in range(3)) for t in tris]
    anchor = min(centroids, key=lambda c: sum((c[k] - target[k]) ** 2 for k in range(3)))
    s = edge_snap.snap(fr, anchor)
    assert s is not None
    length = sum(ls._len(ls._sub(b, a)) for a, b in zip(s.polyline, s.polyline[1:]))
    assert length > 100 and 2 <= len(s.polyline) - 1 <= edge_snap.MAX_SEGMENTS
    assert all(88.0 < p[2] < 90.5 for p in s.polyline)
```

- [ ] **Step 2: Run** — `uv run pytest tests/host/test_bridge_editor_bindings.py -q -k map_3` — Expected: PASS (it SKIPs only without BC content; on this machine it must RUN — check with `-rs` and say so).

- [ ] **Step 3: Falsify** — back up `engine/bridge_editor/edge_snap.py` with `cp`, set `SNAP_TIE = 0.0`, run: if it still passes, the tie rule is not what saves it on this point; record that. Then set `MAX_SEGMENTS = 1`: the test must FAIL (`2 <=` segments). Restore with `cp`, `diff` byte-identical, re-run PASS. Record.

- [ ] **Step 4: Commit**

```bash
git add tests/host/test_bridge_editor_bindings.py
git commit -m "test(bridge): DBridge Map 3 alcove lip snaps to its curved run (spec §16.8)"
```

---

### Task 6: Docs and gate

**Files:**
- Modify: `CLAUDE.md` ("Bridge editor" row), the spec's §16.7 "As built"

- [ ] **Step 1: Gate** — `scripts/check_tests.sh > <workspace>/gate.log 2>&1` (run it in the foreground of a background shell and WAIT for it; do not detach with nohup — a detached run dies with your shell). Expected: exit 0, "OK — no new failures".

- [ ] **Step 2: Docs**
- `CLAUDE.md` "Bridge editor" row: after `objects (same-texture link, lights)` add `; a strip snaps to the sharp edge nearest the selecting click (§16.8)`. The row has a 1200-character budget (`tests/docs/test_doc_consistency.py`) — trim within the row if needed, never drop a fact without moving it to the spec, and say what you trimmed.
- Spec §16.7: append `Edge snap (§16.8) built on \`spike/strip-edge-snap\` (plan \`docs/superpowers/plans/2026-10-12-strip-edge-snap.md\`). Not live-verified beyond Mark's spike check ("looks much better").`
- `uv run pytest tests/docs -q` — PASS.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md
git commit -m "docs(bridge): edge snap as built"
```
