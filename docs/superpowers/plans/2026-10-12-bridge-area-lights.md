# Bridge Area Lights (Strips + Panels) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bridge Editor object lights gain two shapes with size -- a **strip** along one edge of the object's front rectangle and a **panel** covering (part of) it -- rendered as one-sided rectangular area lights beside the existing spots.

**Architecture:** The per-bridge file stores only parameters (`shape`, `edge`, `start`/`end`, `x`/`y` spans, `offset`, `range`, `intensity`); `engine/bridge_editor/light_shapes.py` recomputes each rectangle at load from the object's mesh (a new `bridge_mesh_geometry` host query). `lights.py` caps spots + area lights at 32 together and produces a separate area list; `runtime.py` pushes it through new `set_bridge_area_lights` / `set_bridge_area_colours` bindings to `BridgePass`, whose `bridge.frag accumulate_area_lights` shades each rectangle with the Heitz horizon-clipped Lambert edge integral (diffuse, ported from the 2026-09-04 spike) and a Karis representative-point GGX (specular). C++ twins in `bridge_pbr.h` pin the shader maths.

**Tech Stack:** Python 3.11 (pytest), C++17 + GLM + OpenGL 4.1 / GLSL 410 (gtest), pybind11, vanilla JS in CEF (node-run tests).

**Spec:** `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` **§16** (read §13.2, §13.4, §14, §15 for the surrounding model).

## Global Constraints

- Bridge data `format: 4`; `format` 1, 2, 3 upgrade on load; 3 -> 4 changes nothing but the number.
- A light's `shape` is `spot` (also when absent), `strip` or `panel`; unknown keys are REJECTED.
- `strip`: `edge` in `top` / `bottom` / `left` / `right`; `start`, `end` in 0-1, `start <= end`, defaults 0 and 1.
- `panel`: `x`, `y` each `[from, to]`, 0-1, `from <= to`, default `[0, 1]`.
- `offset` is in bridge units, out along the object's facing; `range` > 0; `intensity` >= 0 is surface brightness (radiance per unit area, before colour).
- Spots + strips + panels share ONE 32-light budget (`lights.MAX_LIGHTS`), mesh order, a warning per dropped light.
- Room up is +Z (`renderer::kBridgeUp`); `STRIP_WIDTH = 0.5` bridge units; no-facing threshold: normal sum < 5% of total area; near-vertical facing: within 25° of ±Z.
- Light colour follows the object's resolved material exactly as spots do (`^2.2`, steady white when the material sets no glow, static capture colours + per-frame live colours).
- A bridge with no strips or panels uploads `u_area_count = 0`: its frame is unchanged.
- Shared checkout rules (CLAUDE.md): never `git checkout -- / restore / stash / clean / reset --hard / add -A / add .`; stage with explicit paths. Work only inside the worktree `.claude/worktrees/bridge-area-lights` on branch `feat/bridge-area-lights`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

- A strip/panel whose object has no geometry (stale instance, mesh missing) must be skipped with a warning AND the per-frame live colours must stay aligned with the uploaded rows -- a skipped light must not shift every later light's colour. (Task 6 test.)
- A panel whose span collapses to zero (`x: [0.4, 0.4]`) must be dropped as invalid by the binding and counted, never reach the shader as a NaN normal. (Task 5 test.)
- A receiver lying exactly on the light's plane or at its centre (the host surface at `offset` 0) must give finite zeros, never NaN bloom squares. (Task 3 test.)
- A committed `format: 3` file with spots only must load, render its spots identically and save as `format: 4`. (Task 1 test.)
- Editing a span so from > to (UI typing) must drag the other end along, so a save is never refused. (Task 8 test.)

## File map

| File | Change |
|---|---|
| `engine/bridge_editor/lighting_doc.py` | `FORMAT = 4`, `LIGHT_SHAPES`, `EDGES`, strip/panel validation, 3 -> 4 upgrade |
| `engine/bridge_editor/light_shapes.py` | **new** -- frame, front rectangle, strip/panel rectangles (pure Python) |
| `native/src/renderer/include/renderer/bridge_pbr.h` | area-light twins: `range_window`, form factor, nearest/representative point, `area_light` |
| `native/src/renderer/include/renderer/bridge_lighting_tuning.h` | `kBridgeMaxAreaLights = 32` |
| `native/src/renderer/include/renderer/bridge_pass.h`, `bridge_pass.cc` | `BridgeAreaLight`, `set_area_lights`, `set_area_radiance`, uniform upload |
| `native/src/renderer/shaders/bridge.frag` | `accumulate_area_lights` in the main view and the probe capture |
| `native/src/renderer/include/renderer/ray_trace.h`, `ray_trace.cc` | `mesh_triangles_linear` |
| `native/src/host/host_bindings.cc` | `set_bridge_area_lights`, `set_bridge_area_colours`, `bridge_mesh_geometry` |
| `engine/host_io.py` | three wrappers + manifest entries |
| `engine/bridge_editor/lights.py` | shared budget, `areas()`, `live_area_colours()` |
| `engine/bridge_editor/runtime.py` | geometry cache, area push / clear / live |
| `engine/bridge_editor/editing.py` | `add_area_light`, strip/panel fields in `set_light` |
| `engine/ui/bridge_emitters_panel.py` | `light-add:<shape>`; place/aim only for spots |
| `native/assets/ui-cef/js/bridge_emitters.js` | Add Light menu; strip / panel rows |
| `CLAUDE.md`, spec §16 | as-built notes |

## Before Task 1: worktree setup (once)

The worktree already exists with `settings.json` and `mods/` copied in. Do not cd to the main checkout.

```bash
cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/bridge-area-lights
uv sync --extra dev
cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=$PWD/.venv/bin/python3
cmake --build build -j
```

Expected: the build finishes; `uv run pytest tests/unit/test_bridge_lights.py -q` passes. The renderer gtest binary is found with `find build -name renderer_tests -type f` (referred to below as `RT`; it is normally `build/native/tests/renderer/renderer_tests`). Shader edits need `cmake --build build -j` (the shaders are embedded at build time; if an edit seems ignored, re-run `cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=$PWD/.venv/bin/python3` first).

---

### Task 1: Data format 4 -- strip and panel lights

**Files:**
- Modify: `engine/bridge_editor/lighting_doc.py` (`_light`, `FORMAT`, `upgrade`, `_v2_to_v3`)
- Test: `tests/unit/test_bridge_lighting_doc.py`

**Interfaces:**
- Produces: `ld.FORMAT == 4`; `ld.LIGHT_SHAPES = ("spot", "strip", "panel")`; `ld.EDGES = ("top", "bottom", "left", "right")`; `ld.validate` accepts strip/panel lights; `ld.upgrade` maps formats 1-3 to 4.

- [ ] **Step 1: Write the failing tests** -- append to `tests/unit/test_bridge_lighting_doc.py`:

```python
# ── format 4: lights with size (spec §16.1) ─────────────────────────────────

def _with_lights(lights):
    d = ld.empty_doc("x")
    ld.object_entry(d, 5, "lip")["lights"] = lights
    return d


def test_format_is_4():
    assert ld.FORMAT == 4 and ld.empty_doc("x")["format"] == 4


def test_strip_and_panel_lights_validate():
    d = _with_lights([
        {"shape": "strip", "edge": "top", "start": 0.1, "end": 0.9, "offset": 1,
         "range": 150, "intensity": 4},
        {"shape": "panel", "x": [0, 1], "y": [0.2, 0.8], "offset": 0, "range": 400,
         "intensity": 1},
        {"shape": "strip", "edge": "left"},
        {"shape": "panel"},
        {"shape": "spot", "position": [0, 0, 0], "direction": [0, 0, -1]},
        {"position": [0, 0, 0], "direction": [0, 0, -1]}])
    assert ld.validate(d) is d


@pytest.mark.parametrize("light, where", [
    ({"shape": "tube"}, "shape"),
    ({"shape": "strip"}, "edge"),
    ({"shape": "strip", "edge": "middle"}, "edge"),
    ({"shape": "strip", "edge": "top", "start": -0.1}, "start"),
    ({"shape": "strip", "edge": "top", "end": 1.5}, "end"),
    ({"shape": "strip", "edge": "top", "start": 0.8, "end": 0.2}, "start"),
    ({"shape": "strip", "edge": "top", "x": [0, 1]}, "x"),
    ({"shape": "panel", "x": [0.5]}, "x"),
    ({"shape": "panel", "x": [0.6, 0.4]}, "x"),
    ({"shape": "panel", "y": [0, 2]}, "y"),
    ({"shape": "panel", "edge": "top"}, "edge"),
    ({"shape": "panel", "range": 0}, "range"),
    ({"shape": "panel", "intensity": -1}, "intensity"),
    ({"shape": "panel", "offset": float("nan")}, "offset"),
    ({"shape": "panel", "position": [0, 0, 0]}, "position"),
])
def test_bad_area_lights_are_rejected(light, where):
    with pytest.raises(ld.BridgeLightingError, match=where):
        ld.validate(_with_lights([light]))


def test_format_3_upgrades_to_4_unchanged_but_the_number():
    v3 = _with_lights([{"position": [1, 2, 3], "direction": [0, 0, -1], "intensity": 9}])
    v3["format"] = 3
    v3["materials"]["m"] = {"emission": 0.5}
    up = ld.validate(ld.upgrade(v3))
    assert up["format"] == 4
    assert {k: v for k, v in up.items() if k != "format"} == \
        {k: v for k, v in v3.items() if k != "format"}
    assert v3["format"] == 3                       # the input is not mutated


def test_format_2_upgrades_through_3_to_4():
    v2 = {"format": 2, "source": "x", "materials": {}, "objects": {}}
    assert ld.upgrade(v2)["format"] == 4
```

Also update the existing format-3 assertions in this file to `ld.FORMAT`: the `full_doc()` fixture's `"format": 3` (line ~13) becomes `"format": ld.FORMAT`, and `== 3` at lines ~166, ~244, ~440, ~461 becomes `== ld.FORMAT`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_bridge_lighting_doc.py -q`
Expected: FAIL (`FORMAT` is 3; strip lights rejected as `position` required).

- [ ] **Step 3: Implement** in `engine/bridge_editor/lighting_doc.py`:

Replace `_light` with a shape dispatch (the spot body is unchanged apart from allowing `shape`):

```python
LIGHT_SHAPES = ("spot", "strip", "panel")
EDGES = ("top", "bottom", "left", "right")


def _light(l, where):
    """A light (spec §13.2, §16.1): a `spot` (also when `shape` is absent),
    or a `strip` / `panel` cut from the object's front rectangle -- which
    stores parameters only, never coordinates."""
    if not isinstance(l, dict):
        _fail(where, "must be an object")
    shape = l.get("shape", "spot")
    _enum(shape, f"{where}.shape", LIGHT_SHAPES)
    if shape == "spot":
        _spot(l, where)
    else:
        _area_light(l, where, shape)


def _spot(l, where):
    _obj(l, where, {"shape", "position", "direction", "inner_deg", "outer_deg", "range",
                    "intensity", "light_scale"}, ("position", "direction"))
    _vec3(l["position"], f"{where}.position")
    _vec3(l["direction"], f"{where}.direction")
    if sum(c * c for c in l["direction"]) < 1e-12:
        _fail(f"{where}.direction", "must be non-zero")
    inner = l.get("inner_deg", 0.0)
    outer = l.get("outer_deg", 90.0)
    _num(inner, f"{where}.inner_deg", 0, 90)
    _num(outer, f"{where}.outer_deg", 0, 90)
    if inner > outer:
        _fail(f"{where}.inner_deg", "must be <= outer_deg")
    if "range" in l:
        _num(l["range"], f"{where}.range", lo=0, lo_open=True)
    for k in ("intensity", "light_scale"):
        if k in l:
            _num(l[k], f"{where}.{k}", lo=0)


def _span(v, where):
    if not isinstance(v, list) or len(v) != 2:
        _fail(where, "must be [from, to]")
    _num(v[0], f"{where}[0]", 0, 1)
    _num(v[1], f"{where}[1]", 0, 1)
    if v[0] > v[1]:
        _fail(where, "from must be <= to")


def _area_light(l, where, shape):
    common = {"shape", "offset", "range", "intensity", "light_scale"}
    if shape == "strip":
        _obj(l, where, common | {"edge", "start", "end"}, ("edge",))
        _enum(l["edge"], f"{where}.edge", EDGES)
        start, end = l.get("start", 0.0), l.get("end", 1.0)
        _num(start, f"{where}.start", 0, 1)
        _num(end, f"{where}.end", 0, 1)
        if start > end:
            _fail(f"{where}.start", "must be <= end")
    else:
        _obj(l, where, common | {"x", "y"})
        for k in ("x", "y"):
            if k in l:
                _span(l[k], f"{where}.{k}")
    if "offset" in l:
        _num(l["offset"], f"{where}.offset")
    if "range" in l:
        _num(l["range"], f"{where}.range", lo=0, lo_open=True)
    for k in ("intensity", "light_scale"):
        if k in l:
            _num(l[k], f"{where}.{k}", lo=0)
```

Set `FORMAT = 4`. In `_v2_to_v3` change the last line `doc["format"] = FORMAT` to `doc["format"] = 3`. Add after `_v2_to_v3`:

```python
def _v3_to_v4(doc) -> dict:
    """`format: 3` -> 4 (spec §16.1): lights gained `shape`; a light without
    one is a spot, which is every light a format-3 file holds."""
    doc = json.loads(json.dumps(doc))
    doc["format"] = 4
    return doc
```

Replace `upgrade`:

```python
def upgrade(doc) -> dict:
    """An older document as the current format (1 -> 2 -> 3 -> 4), or the
    document itself when it is not an older format."""
    if not isinstance(doc, dict):
        return doc
    if doc.get("format") == 1:
        return _v3_to_v4(_v2_to_v3(_v1_to_v2(doc)))
    if doc.get("format") == 2:
        return _v3_to_v4(_v2_to_v3(doc))
    if doc.get("format") == 3:
        return _v3_to_v4(doc)
    return doc
```

Update the module docstring's first line to cite §16 too: `(spec 2026-10-08-bridge-emitters §7, §13.4, §16)`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_bridge_lighting_doc.py tests/unit/test_bridge_lighting_writer.py tests/unit/test_bridge_runtime.py tests/unit/test_bridge_emitters_panel.py -q`
Expected: PASS. If another test asserts `"format": 3` (grep `rg -n '"format": 3|format.. == 3' tests`), change it to `ld.FORMAT`; a test that writes a v3 fixture to disk and expects it to load is still correct (it upgrades).

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/lighting_doc.py tests/unit/test_bridge_lighting_doc.py
git commit -m "feat(bridge): lighting data format 4 -- strip and panel lights (spec §16.1)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

(Add any other test file you had to touch to the `git add` line by name.)

---

### Task 2: `light_shapes` -- the front rectangle, strips and panels

**Files:**
- Create: `engine/bridge_editor/light_shapes.py`
- Test: `tests/unit/test_bridge_light_shapes.py`

**Interfaces:**
- Produces:
  - `light_shapes.Frame(right, up, facing, centre, half)` -- unit axes, box centre, half-extents `(along right, along up, along facing)`, all `tuple[float, float, float]`.
  - `light_shapes.Rect(centre, half_u, half_v)` with property `normal` (unit `cross(half_u, half_v)`; the side it emits toward).
  - `light_shapes.frame(vertices, normal_sum, area, eye) -> Optional[Frame]`
  - `light_shapes.strip_rect(fr, edge, start=0.0, end=1.0, offset=0.0) -> Rect`
  - `light_shapes.panel_rect(fr, x=(0.0, 1.0), y=(0.0, 1.0), offset=0.0) -> Rect`
  - `light_shapes.light_rect(light: dict, fr: Frame) -> Rect`
  - constants `ROOM_UP`, `STRIP_WIDTH = 0.5`, `NO_FACING = 0.05`, `VERTICAL_DEG = 25.0`

- [ ] **Step 1: Write the failing tests** -- `tests/unit/test_bridge_light_shapes.py`:

```python
"""Lights with size: the front rectangle and the strips / panels cut from it
(spec 2026-10-08-bridge-emitters §16.2). Synthetic meshes, no GL."""
import math

import pytest

from engine.bridge_editor import light_shapes as ls

EYE = (20.0, 0.0, 20.0)


def _mesh(quads):
    """(vertices, normal_sum, area) for quads given as 4 corners each, wound
    so cross(b - a, d - a) points where the quad faces."""
    verts, n, area = [], [0.0, 0.0, 0.0], 0.0
    for a, b, c, d in quads:
        for tri in ((a, b, c), (a, c, d)):
            p, q, r = tri
            e1 = [q[i] - p[i] for i in range(3)]
            e2 = [r[i] - p[i] for i in range(3)]
            cr = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2],
                  e1[0] * e2[1] - e1[1] * e2[0])
            for i in range(3):
                n[i] += cr[i] / 2
            area += math.sqrt(sum(c * c for c in cr)) / 2
            verts.extend(tri)
    return verts, tuple(n), area


def approx(v, w, tol=1e-6):
    return all(abs(a - b) <= tol for a, b in zip(v, w))


# A wall panel x 0..40, z 10..30 at y = 50, facing -Y (into the room).
WALL = [((0, 50, 10), (40, 50, 10), (40, 50, 30), (0, 50, 30))]


def test_a_flat_wall_panel_faces_the_room_with_room_up():
    fr = ls.frame(*_mesh(WALL), eye=EYE)
    assert approx(fr.facing, (0, -1, 0)) and approx(fr.up, (0, 0, 1))
    assert approx(fr.right, (1, 0, 0))            # the viewer's right, seen from the room
    assert approx(fr.centre, (20, 50, 20)) and approx(fr.half, (20, 10, 0))


def test_a_top_strip_runs_along_the_top_edge_aimed_at_the_centre():
    fr = ls.frame(*_mesh(WALL), eye=EYE)
    r = ls.strip_rect(fr, "top")
    assert approx(r.centre, (20, 50, 30)) and approx(r.half_u, (20, 0, 0))
    assert approx(r.normal, (0, 0, -1))           # down the panel, perpendicular to the edge
    assert math.isclose(math.sqrt(sum(c * c for c in r.half_v)), ls.STRIP_WIDTH / 2)


def test_start_and_end_cut_the_edge():
    fr = ls.frame(*_mesh(WALL), eye=EYE)
    r = ls.strip_rect(fr, "top", 0.0, 0.5)
    assert approx(r.centre, (10, 50, 30)) and approx(r.half_u, (10, 0, 0))
    r = ls.strip_rect(fr, "bottom", 0.25, 0.75)
    assert approx(r.centre, (20, 50, 10)) and approx(r.half_u, (10, 0, 0))
    assert approx(r.normal, (0, 0, 1))


def test_left_and_right_are_the_viewers():
    fr = ls.frame(*_mesh(WALL), eye=EYE)
    left, right = ls.strip_rect(fr, "left"), ls.strip_rect(fr, "right")
    assert approx(left.centre, (0, 50, 20)) and approx(left.normal, (1, 0, 0))
    assert approx(right.centre, (40, 50, 20)) and approx(right.normal, (-1, 0, 0))
    assert approx(left.half_u, (0, 0, 10))


def test_offset_moves_the_strip_out_and_tilts_it_back_onto_the_panel():
    fr = ls.frame(*_mesh(WALL), eye=EYE)
    r = ls.strip_rect(fr, "top", offset=2.0)
    assert approx(r.centre, (20, 48, 30))
    assert r.normal[1] > 0 and r.normal[2] < 0     # toward the wall and down it
    assert abs(r.normal[0]) < 1e-9                 # still perpendicular to the edge


def test_a_panel_covers_its_span_of_the_front_and_faces_out():
    fr = ls.frame(*_mesh(WALL), eye=EYE)
    r = ls.panel_rect(fr)
    assert approx(r.centre, (20, 50, 20)) and approx(r.normal, (0, -1, 0))
    assert approx(r.half_u, (20, 0, 0)) and approx(r.half_v, (0, 0, 10))
    r = ls.panel_rect(fr, x=(0.0, 0.5), y=(0.5, 1.0), offset=1.0)
    assert approx(r.centre, (10, 49, 25))
    assert approx(r.half_u, (10, 0, 0)) and approx(r.half_v, (0, 0, 5))


def test_a_sloped_console_keeps_top_as_the_higher_edge():
    # A 45° console face rising away from the room (+Y up the slope).
    s = [((0, 0, 0), (20, 0, 0), (20, 10, 10), (0, 10, 10))]
    fr = ls.frame(*_mesh(s), eye=(10, -50, 20))
    assert approx(fr.facing, (0, -math.sqrt(0.5), math.sqrt(0.5)))
    top, bottom = ls.strip_rect(fr, "top"), ls.strip_rect(fr, "bottom")
    assert top.centre[2] > bottom.centre[2]


def test_an_alcove_lights_from_its_lip_into_the_recess():
    # Open toward -Y: back wall at y = 60, top / bottom / side walls y 50..60.
    back = ((0, 60, 0), (30, 60, 0), (30, 60, 20), (0, 60, 20))                 # faces -y
    top = ((0, 50, 20), (0, 60, 20), (30, 60, 20), (30, 50, 20))       # faces down
    bottom = ((0, 50, 0), (30, 50, 0), (30, 60, 0), (0, 60, 0))        # faces up
    left = ((0, 50, 0), (0, 60, 0), (0, 60, 20), (0, 50, 20))          # faces +x
    right = ((30, 50, 0), (30, 50, 20), (30, 60, 20), (30, 60, 0))     # faces -x
    fr = ls.frame(*_mesh([back, top, bottom, left, right]), eye=(15, 0, 10))
    assert approx(fr.facing, (0, -1, 0))
    r = ls.strip_rect(fr, "top")
    assert math.isclose(r.centre[1], 50.0) and math.isclose(r.centre[2], 20.0)
    assert r.normal[1] > 0 and r.normal[2] < 0     # down and back into the alcove


def test_a_closed_shape_faces_the_eye():
    lo, hi = -5, 5
    cube = [((lo, lo, lo), (lo, hi, lo), (hi, hi, lo), (hi, lo, lo)),     # -z
            ((lo, lo, hi), (hi, lo, hi), (hi, hi, hi), (lo, hi, hi)),     # +z
            ((lo, lo, lo), (hi, lo, lo), (hi, lo, hi), (lo, lo, hi)),     # -y
            ((lo, hi, lo), (lo, hi, hi), (hi, hi, hi), (hi, hi, lo)),     # +y
            ((lo, lo, lo), (lo, lo, hi), (lo, hi, hi), (lo, hi, lo)),     # -x
            ((hi, lo, lo), (hi, hi, lo), (hi, hi, hi), (hi, lo, hi))]     # +x
    fr = ls.frame(*_mesh(cube), eye=(0, -100, 30))
    assert approx(fr.facing, (0, -1, 0)) and approx(fr.up, (0, 0, 1))


def test_a_ceiling_piece_tops_on_the_edge_farther_from_the_chair():
    ceil = [((-10, 70, 100), (-10, 90, 100), (10, 90, 100), (10, 70, 100))]   # faces down
    fr = ls.frame(*_mesh(ceil), eye=(0, 0, 20))
    assert approx(fr.facing, (0, 0, -1)) and approx(fr.up, (0, 1, 0))
    assert math.isclose(ls.strip_rect(fr, "top").centre[1], 90.0)


def test_a_ceiling_piece_right_over_the_eye_still_gets_a_frame():
    ceil = [((-10, -10, 100), (-10, 10, 100), (10, 10, 100), (10, -10, 100))]
    fr = ls.frame(*_mesh(ceil), eye=(0, 0, 20))
    assert fr is not None and abs(sum(a * b for a, b in zip(fr.up, fr.facing))) < 1e-9


def test_no_vertices_is_no_frame():
    assert ls.frame([], (0, 0, 0), 0.0, eye=EYE) is None


def test_light_rect_reads_a_lights_keys_with_their_defaults():
    fr = ls.frame(*_mesh(WALL), eye=EYE)
    assert ls.light_rect({"shape": "strip", "edge": "top"}, fr) == ls.strip_rect(fr, "top")
    assert ls.light_rect({"shape": "panel", "x": [0, 0.5], "offset": 1}, fr) == \
        ls.panel_rect(fr, x=(0, 0.5), offset=1)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_bridge_light_shapes.py -q`
Expected: FAIL with `ImportError: cannot import name 'light_shapes'`.

- [ ] **Step 3: Implement** `engine/bridge_editor/light_shapes.py`:

```python
"""Lights with size (spec 2026-10-08-bridge-emitters §16.2): an object's
front rectangle, and the strip / panel rectangles cut from it. Pure Python;
the geometry comes from host_io.bridge_mesh_geometry. Nothing here is
stored: the file holds only parameters, so a light follows its object
through mesh fixes and shape-diff edits."""
import math
from dataclasses import dataclass
from typing import Optional, Tuple

Vec = Tuple[float, float, float]

ROOM_UP: Vec = (0.0, 0.0, 1.0)      # renderer::kBridgeUp
STRIP_WIDTH = 0.5                   # bridge units; an engine constant, not edited
NO_FACING = 0.05                    # normal sum below this x area: a closed shape
VERTICAL_DEG = 25.0                 # facing this close to +-Z: a ceiling / floor piece


def _add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _mul(a, k): return (a[0] * k, a[1] * k, a[2] * k)
def _dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _len(a): return math.sqrt(_dot(a, a))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a) -> Optional[Vec]:
    n = _len(a)
    return _mul(a, 1.0 / n) if n > 1e-9 else None


def _horizontal(a) -> Optional[Vec]:
    return _unit((a[0], a[1], 0.0))


@dataclass(frozen=True)
class Frame:
    right: Vec
    up: Vec
    facing: Vec
    centre: Vec      # the object's box centre, world
    half: Vec        # half-extents along (right, up, facing)


@dataclass(frozen=True)
class Rect:
    centre: Vec
    half_u: Vec
    half_v: Vec      # cross(half_u, half_v) points where it emits

    @property
    def normal(self) -> Vec:
        return _unit(_cross(self.half_u, self.half_v)) or (0.0, 0.0, 0.0)


def frame(vertices, normal_sum, area, eye) -> Optional[Frame]:
    """The object's frame: facing = its area-weighted normal; up = room up
    without its facing part; right = up x facing (the viewer's right, seen
    from the front). A closed shape (normals cancel) faces the eye; a piece
    within VERTICAL_DEG of +-Z tops on its edge farther from the eye."""
    if not vertices:
        return None
    lo = [min(v[i] for v in vertices) for i in range(3)]
    hi = [max(v[i] for v in vertices) for i in range(3)]
    mid = tuple((lo[i] + hi[i]) / 2.0 for i in range(3))
    n = tuple(float(c) for c in normal_sum)
    if area > 0.0 and _len(n) >= NO_FACING * area:
        facing = _unit(n)
    else:
        facing = _horizontal(_sub(eye, mid)) or (0.0, -1.0, 0.0)
    if abs(_dot(facing, ROOM_UP)) > math.cos(math.radians(VERTICAL_DEG)):
        hint = _horizontal(_sub(mid, eye)) or (0.0, 1.0, 0.0)
    else:
        hint = ROOM_UP
    up = _unit(_sub(hint, _mul(facing, _dot(hint, facing))))
    if up is None:          # cannot happen for the hints above; keep a frame anyway
        up = _unit(_cross(facing, (1.0, 0.0, 0.0))) or (0.0, 1.0, 0.0)
    right = _cross(up, facing)
    axes = (right, up, facing)
    proj = [[_dot(v, a) for a in axes] for v in vertices]
    plo = [min(p[i] for p in proj) for i in range(3)]
    phi = [max(p[i] for p in proj) for i in range(3)]
    centre = (0.0, 0.0, 0.0)
    for i in range(3):
        centre = _add(centre, _mul(axes[i], (plo[i] + phi[i]) / 2.0))
    half = tuple((phi[i] - plo[i]) / 2.0 for i in range(3))
    return Frame(right, up, facing, centre, half)


def _front(fr) -> Vec:
    return _add(fr.centre, _mul(fr.facing, fr.half[2]))


def strip_rect(fr, edge, start=0.0, end=1.0, offset=0.0) -> Rect:
    """That edge of the front rectangle, cut to [start, end] (0 = the left /
    bottom end), moved out along facing by `offset`, STRIP_WIDTH wide. It
    faces the box centre with its along-edge part removed: perpendicular to
    the edge, toward the centre on average."""
    hr, hu, _hf = fr.half
    if edge in ("top", "bottom"):
        axis, span = fr.right, hr
        across = _mul(fr.up, hu if edge == "top" else -hu)
    else:
        axis, span = fr.up, hu
        across = _mul(fr.right, hr if edge == "right" else -hr)
    mid = (start + end) / 2.0
    c = _add(_add(_front(fr), across), _mul(axis, span * (2.0 * mid - 1.0)))
    c = _add(c, _mul(fr.facing, offset))
    to_centre = _sub(fr.centre, c)
    n = _unit(_sub(to_centre, _mul(axis, _dot(to_centre, axis)))) or fr.facing
    width = _cross(n, axis)
    return Rect(c, _mul(axis, span * (end - start)), _mul(width, STRIP_WIDTH / 2.0))


def panel_rect(fr, x=(0.0, 1.0), y=(0.0, 1.0), offset=0.0) -> Rect:
    """The x by y span of the front rectangle (0 = left / bottom), moved out
    along facing by `offset`, facing out."""
    hr, hu, hf = fr.half
    c = _add(fr.centre, _mul(fr.facing, hf + offset))
    c = _add(c, _mul(fr.right, hr * (x[0] + x[1] - 1.0)))
    c = _add(c, _mul(fr.up, hu * (y[0] + y[1] - 1.0)))
    return Rect(c, _mul(fr.right, hr * (x[1] - x[0])), _mul(fr.up, hu * (y[1] - y[0])))


def light_rect(light, fr) -> Rect:
    off = float(light.get("offset", 0.0))
    if light.get("shape") == "strip":
        return strip_rect(fr, light["edge"], float(light.get("start", 0.0)),
                          float(light.get("end", 1.0)), off)
    x = light.get("x", (0.0, 1.0))
    y = light.get("y", (0.0, 1.0))
    return panel_rect(fr, (float(x[0]), float(x[1])), (float(y[0]), float(y[1])), off)
```

Note `light_rect` passes floats, so `light_rect({... "x": [0, 0.5], "offset": 1}, fr)` and `panel_rect(fr, x=(0, 0.5), offset=1)` compare equal (both produce the same float tuples).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_bridge_light_shapes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/light_shapes.py tests/unit/test_bridge_light_shapes.py
git commit -m "feat(bridge): light_shapes -- front rectangle, strips and panels (spec §16.2)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: C++ twins for rectangular area lights

**Files:**
- Modify: `native/src/renderer/include/renderer/bridge_pbr.h`
- Test: `native/tests/renderer/bridge_pbr_test.cc` (append)

**Interfaces:**
- Produces (namespace `renderer::pbr`), each with a same-named GLSL twin in Task 4:
  - `float range_window(float d, float range)` -- `spot_falloff`'s window, `spot_falloff(d, r) == range_window(d, r) / (d*d + 1)`.
  - `float rect_form_factor(glm::vec3 p, glm::vec3 n, const glm::vec3 c[4])` -- one-sided by `cross(c1-c0, c3-c0)`.
  - `void rect_corners(glm::vec3 c, glm::vec3 u, glm::vec3 v, glm::vec3 out[4])` -- `c-u-v, c+u-v, c+u+v, c-u+v`.
  - `glm::vec3 rect_nearest(glm::vec3 p, glm::vec3 c, glm::vec3 u, glm::vec3 v)`
  - `glm::vec3 rect_representative(glm::vec3 p, glm::vec3 r, glm::vec3 c, glm::vec3 u, glm::vec3 v)`
  - `struct AreaTerms { glm::vec3 diffuse; glm::vec3 spec; };`
  - `AreaTerms area_light(glm::vec3 p, glm::vec3 N, glm::vec3 V, float n_dot_v, glm::vec3 albedo, float metal, float rough, glm::vec3 f0, glm::vec3 c, glm::vec3 u, glm::vec3 v, glm::vec3 radiance, float range)`

- [ ] **Step 1: Write the failing tests** -- append to `native/tests/renderer/bridge_pbr_test.cc` (it already includes `<renderer/bridge_pbr.h>`, gtest and glm; add `#include <cmath>` if absent):

```cpp
// ── Area lights: strips and panels (spec 2026-10-08-bridge-emitters §16.3) ──

namespace {

// Analytic form factor of a rectangle a x b, receiver on the perpendicular
// through one corner at distance h, normal pointing at the rectangle.
float corner_rect_ff(float a, float b, float h) {
    const float A = a / h, B = b / h;
    const float ra = std::sqrt(1.0f + A * A), rb = std::sqrt(1.0f + B * B);
    return (A / ra * std::atan(B / ra) + B / rb * std::atan(A / rb)) /
           (2.0f * renderer::pbr::kPi);
}

// Brute force F = (1/pi) * integral over the quad of cos_r cos_l / r^2 dA.
float quadrature_ff(const glm::vec3& p, const glm::vec3& n, const glm::vec3 c[4], int steps) {
    const glm::vec3 e1 = c[1] - c[0], e2 = c[3] - c[0];
    const glm::vec3 ln = glm::normalize(glm::cross(e1, e2));
    const float dA = glm::length(e1) * glm::length(e2) / static_cast<float>(steps * steps);
    double sum = 0.0;
    for (int i = 0; i < steps; ++i) for (int j = 0; j < steps; ++j) {
        const glm::vec3 x = c[0] + e1 * ((i + 0.5f) / steps) + e2 * ((j + 0.5f) / steps);
        const glm::vec3 d = x - p;
        const float r2 = glm::dot(d, d);
        const glm::vec3 w = d / std::sqrt(r2);
        sum += static_cast<double>(std::max(glm::dot(w, n), 0.0f) *
                                   std::max(glm::dot(-w, ln), 0.0f) / r2 * dA);
    }
    return static_cast<float>(sum / renderer::pbr::kPi);
}

bool finite3(glm::vec3 a) { return std::isfinite(a.x) && std::isfinite(a.y) && std::isfinite(a.z); }

}  // namespace

TEST(BridgePbrArea, RangeWindowIsTheSpotFalloffWindow) {
    for (float d : {0.0f, 10.0f, 99.0f, 150.0f})
        EXPECT_FLOAT_EQ(renderer::pbr::range_window(d, 120.0f) / (d * d + 1.0f),
                        renderer::pbr::spot_falloff(d, 120.0f));
}

TEST(BridgePbrArea, FormFactorMatchesTheAnalyticCornerRectangle) {
    const glm::vec3 c[4] = {{0, 0, 0}, {3, 0, 0}, {3, 2, 0}, {0, 2, 0}};   // emits +z
    EXPECT_NEAR(renderer::pbr::rect_form_factor({0, 0, 1.5f}, {0, 0, -1}, c),
                corner_rect_ff(3.0f, 2.0f, 1.5f), 2e-4f);
}

TEST(BridgePbrArea, FormFactorMatchesQuadratureWhenTheHorizonClips) {
    const glm::vec3 c[4] = {{0, 0, 0}, {3, 0, 0}, {3, 2, 0}, {0, 2, 0}};
    const glm::vec3 p(1.0f, 0.5f, 0.4f);
    for (const glm::vec3 n : {glm::vec3(1, 0, 0), glm::normalize(glm::vec3(1, 0, -1)),
                              glm::normalize(glm::vec3(-1, 1, -0.2f)), glm::vec3(0, 0, -1)}) {
        const float f = renderer::pbr::rect_form_factor(p, n, c);
        EXPECT_NEAR(f, quadrature_ff(p, n, c, 600), 4e-3f);
        EXPECT_GT(f, 0.01f);
    }
}

TEST(BridgePbrArea, FormFactorIsOneSided) {
    const glm::vec3 c[4] = {{0, 0, 0}, {3, 0, 0}, {3, 2, 0}, {0, 2, 0}};   // emits +z
    EXPECT_EQ(renderer::pbr::rect_form_factor({1, 1, -1}, {0, 0, 1}, c), 0.0f);
}

TEST(BridgePbrArea, CornersWindTowardTheNormal) {
    glm::vec3 c[4];
    renderer::pbr::rect_corners({0, 0, 5}, {2, 0, 0}, {0, -1, 0}, c);   // emits -z
    const glm::vec3 n = glm::normalize(glm::cross(c[1] - c[0], c[3] - c[0]));
    EXPECT_NEAR(n.z, -1.0f, 1e-6f);
}

TEST(BridgePbrArea, RepresentativePointFollowsTheReflectionThenClamps) {
    const glm::vec3 c{0, 0, 10}, u{5, 0, 0}, v{0, -5, 0};               // emits -z
    const glm::vec3 hit = renderer::pbr::rect_representative({2, 1, 0}, {0, 0, 1}, c, u, v);
    EXPECT_NEAR(glm::distance(hit, glm::vec3(2, 1, 10)), 0.0f, 1e-5f);
    const glm::vec3 far = renderer::pbr::rect_representative(
        {0, 0, 0}, glm::normalize(glm::vec3(1, 0, 1)), c, u, v);
    EXPECT_NEAR(glm::distance(far, glm::vec3(5, 0, 10)), 0.0f, 1e-4f);   // clamped to the edge
    // Pointing away from the light: the nearest point.
    const glm::vec3 away = renderer::pbr::rect_representative({2, 1, 0}, {0, 0, -1}, c, u, v);
    EXPECT_NEAR(glm::distance(away, glm::vec3(2, 1, 10)), 0.0f, 1e-5f);
}

// A small rectangle far away lights like a spot whose intensity is its
// radiance x area x cos (spec §16.1: intensity is surface brightness).
TEST(BridgePbrArea, ASmallRectLightsLikeASpotOfTheSameOutput) {
    using namespace renderer::pbr;
    const glm::vec3 p{0, 0, 0}, N{0, 0, 1};
    const glm::vec3 c{15, 0, 100}, u{0.5f, 0, 0}, v{0, -0.5f, 0};       // 1 x 1, emits -z
    const glm::vec3 V = glm::normalize(glm::vec3(-15, 0, 100));         // mirror ray hits c
    const glm::vec3 albedo{0.5f}, radiance{3.0f};
    const float rough = 0.5f, metal = 0.0f, range = 1000.0f;
    const glm::vec3 f0 = f0_for(albedo, metal);
    const float n_dot_v = glm::dot(N, V);
    const AreaTerms a = area_light(p, N, V, n_dot_v, albedo, metal, rough, f0, c, u, v,
                                   radiance, range);
    // The spot reference (accumulate_spots' formulas) at the rectangle's centre.
    const float d = glm::length(c - p);
    const glm::vec3 L = (c - p) / d;
    const float n_dot_l = glm::dot(N, L);
    const float cos_l = glm::dot(-L, glm::vec3(0, 0, -1));
    const glm::vec3 I = radiance * 1.0f * cos_l;                       // area 1
    const glm::vec3 H = glm::normalize(L + V);
    const glm::vec3 F = F_schlick(std::max(glm::dot(V, H), 0.0f), f0);
    const glm::vec3 rad = I * spot_falloff(d, range) * n_dot_l;
    const glm::vec3 diffuse = (glm::vec3(1.0f) - F) * (1.0f - metal) * albedo / kPi * rad;
    const glm::vec3 spec = D_ggx(std::max(glm::dot(N, H), 0.0f), rough) *
                           G_smith(n_dot_v, n_dot_l, rough) * F /
                           std::max(4.0f * n_dot_v * n_dot_l, 1e-4f) * rad;
    EXPECT_NEAR(a.diffuse.r / diffuse.r, 1.0f, 0.02f);
    EXPECT_NEAR(a.spec.r / spec.r, 1.0f, 0.05f);
}

TEST(BridgePbrArea, BehindTheLightOrBeyondItsRangeGivesNothing) {
    using namespace renderer::pbr;
    const glm::vec3 albedo{0.5f}, f0 = f0_for(albedo, 0.0f);
    const glm::vec3 c{0, 0, 10}, u{5, 0, 0}, v{0, 5, 0};                // emits +z: away
    AreaTerms a = area_light({0, 0, 0}, {0, 0, 1}, {0, 0, 1}, 1.0f, albedo, 0.0f, 0.5f, f0,
                             c, u, v, glm::vec3(10.0f), 100.0f);
    EXPECT_EQ(a.diffuse, glm::vec3(0.0f));
    EXPECT_EQ(a.spec, glm::vec3(0.0f));
    a = area_light({0, 0, 0}, {0, 0, 1}, {0, 0, 1}, 1.0f, albedo, 0.0f, 0.5f, f0,
                   c, u, -v, glm::vec3(10.0f), 9.0f);                    // facing, out of range
    EXPECT_EQ(a.diffuse, glm::vec3(0.0f));
    EXPECT_EQ(a.spec, glm::vec3(0.0f));
}

TEST(BridgePbrArea, AHugePanelIsBoundedByItsRadiance) {
    using namespace renderer::pbr;
    const glm::vec3 c{0, 0, 10}, u{1e4f, 0, 0}, v{0, -1e4f, 0};         // emits -z
    const glm::vec3 radiance{2.0f}, albedo{1.0f};
    const glm::vec3 N{0, 0, 1}, V{0, 0, 1};
    const AreaTerms metal = area_light({0, 0, 0}, N, V, 1.0f, albedo, 1.0f, 0.3f,
                                       f0_for(albedo, 1.0f), c, u, v, radiance, 1e6f);
    EXPECT_EQ(metal.diffuse, glm::vec3(0.0f));
    EXPECT_LE(metal.spec.r, radiance.r * 1.05f);
    const AreaTerms matte = area_light({0, 0, 0}, N, V, 1.0f, albedo, 0.0f, 1.0f,
                                       f0_for(albedo, 0.0f), c, u, v, radiance, 1e6f);
    EXPECT_NEAR(matte.diffuse.r, 0.96f * radiance.r, 0.05f);            // (1 - F) x albedo x L
}

TEST(BridgePbrArea, AReceiverOnTheLightIsFiniteZero) {
    using namespace renderer::pbr;
    const glm::vec3 albedo{0.5f}, f0 = f0_for(albedo, 0.0f);
    const glm::vec3 c{0, 0, 0}, u{1, 0, 0}, v{0, 1, 0};                 // emits +z
    for (const glm::vec3 p : {glm::vec3(0, 0, 0), glm::vec3(1, 1, 0), glm::vec3(0.3f, 0, 0)}) {
        const AreaTerms a = area_light(p, {0, 0, 1}, {0, 0, 1}, 1.0f, albedo, 0.0f, 0.5f, f0,
                                       c, u, v, glm::vec3(5.0f), 100.0f);
        EXPECT_TRUE(finite3(a.diffuse) && finite3(a.spec));
        EXPECT_EQ(a.diffuse, glm::vec3(0.0f));
        EXPECT_EQ(a.spec, glm::vec3(0.0f));
    }
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cmake --build build -j --target renderer_tests`
Expected: compile errors (`range_window`, `rect_form_factor`, `area_light` undeclared).

- [ ] **Step 3: Implement** -- append inside `namespace renderer::pbr` in `bridge_pbr.h`, before its closing brace:

```cpp
// ── Area lights: strips and panels (spec 2026-10-08-bridge-emitters §16.3) ──
// A rectangle: centre c, half-axes u and v (perpendicular); it emits toward
// cross(u, v) only. Diffuse is the exact horizon-clipped Lambert edge
// integral (Heitz); specular is GGX at a representative point (Karis),
// its lobe widened by the light's size. Twins of bridge.frag's same names.

// spot_falloff's window alone: 1 inside, 0 at `range`.
inline float range_window(float d, float range) {
    const float r = d / std::max(range, 1e-4f);
    const float w = std::clamp(1.0f - r * r * r * r, 0.0f, 1.0f);
    return w * w;
}

inline void rect_corners(glm::vec3 c, glm::vec3 u, glm::vec3 v, glm::vec3 out[4]) {
    out[0] = c - u - v; out[1] = c + u - v; out[2] = c + u + v; out[3] = c - u + v;
}

inline float area_integrate_edge(glm::vec3 v1, glm::vec3 v2) {
    const float cos_t = std::clamp(glm::dot(v1, v2), -1.0f, 1.0f);
    const float theta = std::acos(cos_t);
    return glm::cross(v1, v2).z * ((theta > 0.001f) ? theta / std::sin(theta) : 1.0f);
}

// Heitz's ClipQuadToHorizon: clip L[0..3] (tangent space, z up) against
// z = 0; returns the vertex count (0, 3, 4 or 5) in L[0..n-1].
inline int area_clip_quad_to_horizon(glm::vec3 L[5]) {
    int config = 0;
    if (L[0].z > 0.0f) config += 1;
    if (L[1].z > 0.0f) config += 2;
    if (L[2].z > 0.0f) config += 4;
    if (L[3].z > 0.0f) config += 8;
    int n = 0;
    switch (config) {
        case 0: n = 0; break;
        case 1: n = 3; L[1] = -L[1].z * L[0] + L[0].z * L[1]; L[2] = -L[3].z * L[0] + L[0].z * L[3]; break;
        case 2: n = 3; L[0] = -L[0].z * L[1] + L[1].z * L[0]; L[2] = -L[2].z * L[1] + L[1].z * L[2]; break;
        case 3: n = 4; L[2] = -L[2].z * L[1] + L[1].z * L[2]; L[3] = -L[3].z * L[0] + L[0].z * L[3]; break;
        case 4: n = 3; L[0] = -L[3].z * L[2] + L[2].z * L[3]; L[1] = -L[1].z * L[2] + L[2].z * L[1]; break;
        case 5: n = 0; break;
        case 6: n = 4; L[0] = -L[0].z * L[1] + L[1].z * L[0]; L[3] = -L[3].z * L[2] + L[2].z * L[3]; break;
        case 7: n = 5; L[4] = -L[3].z * L[0] + L[0].z * L[3]; L[3] = -L[3].z * L[2] + L[2].z * L[3]; break;
        case 8: n = 3; L[0] = -L[0].z * L[3] + L[3].z * L[0]; L[1] = -L[2].z * L[3] + L[3].z * L[2]; L[2] = L[3]; break;
        case 9: n = 4; L[1] = -L[1].z * L[0] + L[0].z * L[1]; L[2] = -L[2].z * L[3] + L[3].z * L[2]; break;
        case 10: n = 0; break;
        case 11: n = 5; L[4] = L[3]; L[3] = -L[2].z * L[3] + L[3].z * L[2]; L[2] = -L[2].z * L[1] + L[1].z * L[2]; break;
        case 12: n = 4; L[1] = -L[1].z * L[2] + L[2].z * L[1]; L[0] = -L[0].z * L[3] + L[3].z * L[0]; break;
        case 13: n = 5; L[4] = L[3]; L[3] = L[2]; L[2] = -L[1].z * L[2] + L[2].z * L[1]; L[1] = -L[1].z * L[0] + L[0].z * L[1]; break;
        case 14: n = 5; L[4] = -L[0].z * L[3] + L[3].z * L[0]; L[0] = -L[0].z * L[1] + L[1].z * L[0]; break;
        default: n = 4; break;
    }
    if (n == 3) L[3] = L[0];
    if (n == 4) L[4] = L[0];
    return n;
}

// The fraction of the cosine-weighted hemisphere at (p, n) the quad covers.
inline float rect_form_factor(glm::vec3 p, glm::vec3 n, const glm::vec3 c[4]) {
    const glm::vec3 ln = glm::normalize(glm::cross(c[1] - c[0], c[3] - c[0]));
    if (glm::dot(ln, p - c[0]) <= 0.0f) return 0.0f;                  // behind: one-sided
    const glm::vec3 helper = (std::fabs(n.z) < 0.9f) ? glm::vec3(0, 0, 1) : glm::vec3(1, 0, 0);
    const glm::vec3 t1 = glm::normalize(glm::cross(helper, n));
    const glm::vec3 t2 = glm::cross(n, t1);
    glm::vec3 L[5];
    for (int i = 0; i < 4; ++i) {
        const glm::vec3 d = c[i] - p;
        L[i] = glm::vec3(glm::dot(d, t1), glm::dot(d, t2), glm::dot(d, n));
    }
    L[4] = L[0];
    const int m = area_clip_quad_to_horizon(L);
    if (m == 0) return 0.0f;
    for (int i = 0; i < 5; ++i) {
        const float len = glm::length(L[i]);
        if (len < 1e-9f) return 0.0f;                                  // on a corner
        L[i] /= len;
    }
    float s = area_integrate_edge(L[0], L[1]) + area_integrate_edge(L[1], L[2]) +
              area_integrate_edge(L[2], L[3]);
    if (m >= 4) s += area_integrate_edge(L[3], L[4]);
    if (m == 5) s += area_integrate_edge(L[4], L[0]);
    return std::clamp(std::fabs(s) / (2.0f * kPi), 0.0f, 1.0f);
}

inline glm::vec3 rect_nearest(glm::vec3 p, glm::vec3 c, glm::vec3 u, glm::vec3 v) {
    const float s = std::clamp(glm::dot(p - c, u) / std::max(glm::dot(u, u), 1e-12f), -1.0f, 1.0f);
    const float t = std::clamp(glm::dot(p - c, v) / std::max(glm::dot(v, v), 1e-12f), -1.0f, 1.0f);
    return c + u * s + v * t;
}

// Where the ray p + t r meets the rectangle's plane, clamped into it; the
// nearest point when the ray runs away from (or along) the light.
inline glm::vec3 rect_representative(glm::vec3 p, glm::vec3 r, glm::vec3 c, glm::vec3 u, glm::vec3 v) {
    const glm::vec3 n = glm::normalize(glm::cross(u, v));
    const float denom = glm::dot(r, n);
    if (denom > -1e-6f) return rect_nearest(p, c, u, v);
    const float t = glm::dot(c - p, n) / denom;
    if (t <= 0.0f) return rect_nearest(p, c, u, v);
    return rect_nearest(p + r * t, c, u, v);
}

struct AreaTerms { glm::vec3 diffuse{0.0f}; glm::vec3 spec{0.0f}; };

inline AreaTerms area_light(glm::vec3 p, glm::vec3 N, glm::vec3 V, float n_dot_v,
                            glm::vec3 albedo, float metal, float rough, glm::vec3 f0,
                            glm::vec3 c, glm::vec3 u, glm::vec3 v,
                            glm::vec3 radiance, float range) {
    AreaTerms out;
    const glm::vec3 nl = glm::normalize(glm::cross(u, v));
    if (glm::dot(nl, p - c) <= 0.0f) return out;                       // behind / on it
    const glm::vec3 near_p = rect_nearest(p, c, u, v);
    const float dn = glm::length(near_p - p);
    const float win = range_window(dn, range);
    if (win <= 0.0f) return out;
    glm::vec3 q[4];
    rect_corners(c, u, v, q);
    const float ff = rect_form_factor(p, N, q);
    const glm::vec3 Ln = (near_p - p) / std::max(dn, 1e-4f);
    const glm::vec3 Fd = F_schlick(std::max(glm::dot(V, glm::normalize(Ln + V)), 0.0f), f0);
    const glm::vec3 rad = radiance * win;
    out.diffuse = (glm::vec3(1.0f) - Fd) * (1.0f - metal) * albedo * rad * ff;
    const glm::vec3 rep = rect_representative(p, glm::reflect(-V, N), c, u, v);
    const float d = std::max(glm::length(rep - p), 1e-4f);
    const glm::vec3 L = (rep - p) / d;
    const float n_dot_l = std::max(glm::dot(N, L), 0.0f);
    if (n_dot_l <= 0.0f) return out;
    const float cos_l = std::max(glm::dot(-L, nl), 0.0f);
    const float area = 4.0f * glm::length(u) * glm::length(v);
    const float omega = std::min(area * cos_l / (d * d), 2.0f * kPi);
    const float a = rough * rough;
    const float a_eff = std::min(a + std::sqrt(area / kPi) / (2.0f * d), 1.0f);
    const glm::vec3 H = glm::normalize(L + V);
    const glm::vec3 F = F_schlick(std::max(glm::dot(V, H), 0.0f), f0);
    out.spec = D_ggx(std::max(glm::dot(N, H), 0.0f), std::sqrt(a_eff)) *
               G_smith(n_dot_v, n_dot_l, rough) * F /
               std::max(4.0f * n_dot_v * n_dot_l, 1e-4f) * rad * n_dot_l * omega;
    return out;
}
```

Ensure `#include <glm/gtc/...>` is not needed (`glm::reflect` is in `<glm/glm.hpp>`).

- [ ] **Step 4: Run tests**

Run: `cmake --build build -j --target renderer_tests && $RT --gtest_filter='BridgePbrArea.*:BridgePbr*'`
Expected: PASS. If `ASmallRectLightsLikeASpotOfTheSameOutput` misses its tolerance, print both values and check `rect_nearest` / `range_window`; do NOT widen the tolerance beyond 2% / 5%.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/bridge_pbr.h native/tests/renderer/bridge_pbr_test.cc
git commit -m "feat(bridge): rectangular area light maths, CPU twins (spec §16.3)

Diffuse: the horizon-clipped Lambert edge integral ported from the
2026-09-04 quad-area-light spike; specular: GGX at a representative point.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `BridgePass` area-light list and the shader

**Files:**
- Modify: `native/src/renderer/include/renderer/bridge_lighting_tuning.h` (next to `kBridgeMaxSpots`)
- Modify: `native/src/renderer/include/renderer/bridge_pass.h` (struct after `BridgeSpot`; methods after `set_spot_radiance`; member after `spots_`)
- Modify: `native/src/renderer/bridge_pass.cc` (`set_spots` neighbourhood; the uniform packing in `render`)
- Modify: `native/src/renderer/shaders/bridge.frag` (after `accumulate_spots`; both call sites)
- Test: `native/tests/renderer/bridge_pbr_frame_test.cc` (append after the spot tests)

**Interfaces:**
- Consumes: Task 3's maths (the GLSL is its twin).
- Produces:
  - `renderer::kBridgeMaxAreaLights = 32`
  - `struct renderer::BridgeAreaLight { glm::vec3 center; glm::vec3 half_u; glm::vec3 half_v; float range; glm::vec3 radiance; bool has_capture; glm::vec3 capture_radiance[2]; }`
  - `std::size_t BridgePass::set_area_lights(std::vector<BridgeAreaLight>)` -- keeps the first 32, returns dropped, marks the probes dirty only when the list changed.
  - `void BridgePass::set_area_radiance(const std::vector<glm::vec3>&)` -- live, never dirties probes.
  - `std::size_t BridgePass::area_light_count() const`

- [ ] **Step 1: Write the failing tests** -- append to `bridge_pbr_frame_test.cc`:

```cpp
// ── Area lights: strips and panels (spec §16.3) ──────────────────────────────

namespace {
renderer::BridgeAreaLight area(glm::vec3 c, glm::vec3 u, glm::vec3 v, float range,
                               glm::vec3 radiance) {
    renderer::BridgeAreaLight a;
    a.center = c; a.half_u = u; a.half_v = v; a.range = range; a.radiance = radiance;
    return a;
}
}  // namespace

TEST_F(BridgePbrFrame, AnAreaLightLightsTheFloorInFrontOfIt) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    const glm::vec3 dark = render_floor();
    // 20 x 20 panel over the sample point, emitting down (cross(u, v) = -z).
    pass->set_area_lights({area({70, 0, 40}, {10, 0, 0}, {0, -10, 0}, 300.0f, glm::vec3(10.0f))});
    EXPECT_GT(render_floor().r, dark.r + 0.05f);
}

TEST_F(BridgePbrFrame, AnAreaLightFacingAwayLightsNothing) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    const glm::vec3 dark = render_floor();
    pass->set_area_lights({area({70, 0, 40}, {10, 0, 0}, {0, 10, 0}, 300.0f, glm::vec3(10.0f))});
    EXPECT_NEAR(render_floor().r, dark.r, 1e-3f);
}

TEST_F(BridgePbrFrame, NoAreaLightsRendersExactlyAsBefore) {
    set_base({0.6f, 0.6f, 0.6f, 1.0f});
    const glm::vec3 before = render_floor();
    EXPECT_EQ(pass->set_area_lights({}), 0u);
    const glm::vec3 after = render_floor();
    EXPECT_EQ(before, after);
}

TEST_F(BridgePbrFrame, AreaLightsBeyondTheCapAreDroppedAndCounted) {
    std::vector<renderer::BridgeAreaLight> many(
        renderer::kBridgeMaxAreaLights + 3,
        area({0, 0, 50}, {1, 0, 0}, {0, -1, 0}, 100.0f, glm::vec3(1.0f)));
    EXPECT_EQ(pass->set_area_lights(many), 3u);
    EXPECT_EQ(pass->area_light_count(), static_cast<std::size_t>(renderer::kBridgeMaxAreaLights));
    render_floor();
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(BridgePbrFrame, SettingAreaLightsMarksTheProbesDirtyButColoursDoNot) {
    EXPECT_FALSE(pass->probe_capture_pending());
    pass->set_area_lights({area({0, 0, 50}, {1, 0, 0}, {0, -1, 0}, 100.0f, glm::vec3(1.0f))});
    EXPECT_TRUE(pass->probe_capture_pending());
    use_red_wall_corner();
    render_floor();                              // captures
    EXPECT_FALSE(pass->probe_capture_pending());
    pass->set_area_radiance({glm::vec3(5.0f)});
    EXPECT_FALSE(pass->probe_capture_pending());
    pass->set_area_lights({});
    EXPECT_TRUE(pass->probe_capture_pending());
}

TEST_F(BridgePbrFrame, AnAreaLightNeverMakesLitDiffuseBloom) {
    set_base({1, 1, 1, 1});
    set_floor_override(1.0f, 0.0f);
    pass->set_area_lights({area({70, 0, 10}, {50, 0, 0}, {0, -50, 0}, 300.0f, glm::vec3(1.0e4f))});
    EXPECT_LT(render_floor().r, renderer::kBridgeLighting.diffuse_max + 0.25f);
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cmake --build build -j --target renderer_tests`
Expected: compile errors (`BridgeAreaLight`, `set_area_lights` unknown).

- [ ] **Step 3: Implement**

`bridge_lighting_tuning.h`, after `kBridgeMaxSpots`:

```cpp
inline constexpr int kBridgeMaxAreaLights = 32;   // spec §16.3; Python caps spots + areas at 32 together
```

`bridge_pass.h`, after `struct BridgeSpot`:

```cpp
/// One static bridge area light (spec 2026-10-08-bridge-emitters §16.3): a
/// rectangle, centre + perpendicular half-axes, emitting toward
/// cross(half_u, half_v) only -- a strip or panel cut from an object's front
/// rectangle (engine/bridge_editor/light_shapes.py). `radiance` is LINEAR
/// colour x intensity (surface brightness); the capture colours follow the
/// BridgeSpot rule (§11.4).
struct BridgeAreaLight {
    glm::vec3 center{0.0f};
    glm::vec3 half_u{1.0f, 0.0f, 0.0f};
    glm::vec3 half_v{0.0f, -1.0f, 0.0f};
    float     range = 1.0f;
    glm::vec3 radiance{0.0f};
    bool      has_capture = false;
    glm::vec3 capture_radiance[2] = {glm::vec3(0.0f), glm::vec3(0.0f)};
};
```

In `class BridgePass`, after `set_spot_radiance`:

```cpp
    /// Static area lights (spec §16.3), main bridge view + its probe
    /// captures only. Keeps the first kBridgeMaxAreaLights, returns how many
    /// were dropped; marks the probes dirty only when the list changed
    /// (geometry, range or capture colours -- the set_spots rule).
    std::size_t set_area_lights(std::vector<BridgeAreaLight> lights);
    /// Live radiance in set_area_lights order; never dirties the probes.
    void set_area_radiance(const std::vector<glm::vec3>& radiance);
    std::size_t area_light_count() const { return area_lights_.size(); }
```

and after `std::vector<BridgeSpot> spots_;`:

```cpp
    /// Static area lights, at most kBridgeMaxAreaLights.
    std::vector<BridgeAreaLight> area_lights_;
```

`bridge_pass.cc`, after `set_spot_radiance`:

```cpp
std::size_t BridgePass::set_area_lights(std::vector<BridgeAreaLight> lights) {
    const std::size_t cap = static_cast<std::size_t>(kBridgeMaxAreaLights);
    const std::size_t dropped = lights.size() > cap ? lights.size() - cap : 0;
    if (dropped > 0) lights.resize(cap);
    auto same = [](const BridgeAreaLight& a, const BridgeAreaLight& b) {
        if (!(a.center == b.center && a.half_u == b.half_u && a.half_v == b.half_v &&
              a.range == b.range && a.has_capture == b.has_capture))
            return false;
        if (a.has_capture)
            return a.capture_radiance[0] == b.capture_radiance[0] &&
                   a.capture_radiance[1] == b.capture_radiance[1];
        return a.radiance == b.radiance;
    };
    const bool unchanged = lights.size() == area_lights_.size() &&
        std::equal(lights.begin(), lights.end(), area_lights_.begin(), same);
    area_lights_ = std::move(lights);
    if (!unchanged) request_probe_capture();
    return dropped;
}

void BridgePass::set_area_radiance(const std::vector<glm::vec3>& radiance) {
    const std::size_t n = std::min(radiance.size(), area_lights_.size());
    for (std::size_t i = 0; i < n; ++i) {
        const glm::vec3& r = radiance[i];
        area_lights_[i].radiance = (std::isfinite(r.x) && std::isfinite(r.y) && std::isfinite(r.z))
            ? r : glm::vec3(0.0f);
    }
}
```

In `render`, right after the spot packing loop:

```cpp
    // Static area lights (spec §16.3), packed like the spots.
    const int area_count = main_bridge ? static_cast<int>(area_lights_.size()) : 0;
    glm::vec4 area_cr[kBridgeMaxAreaLights];   // xyz centre, w range
    glm::vec3 area_u[kBridgeMaxAreaLights];
    glm::vec3 area_v[kBridgeMaxAreaLights];
    glm::vec3 area_rad[kBridgeMaxAreaLights];
    for (int i = 0; i < area_count; ++i) {
        const BridgeAreaLight& a = area_lights_[static_cast<std::size_t>(i)];
        area_cr[i] = glm::vec4(a.center, a.range);
        area_u[i] = a.half_u;
        area_v[i] = a.half_v;
        area_rad[i] = (capture_pass_ && a.has_capture)
            ? a.capture_radiance[capture_probe_] : a.radiance;
    }
```

and inside `set_frame_uniforms`, after the spot block:

```cpp
        s.set_int("u_area_count", area_count);
        if (area_count > 0) {
            s.set_vec4_array("u_area_center_range", area_cr, area_count);
            s.set_vec3_array("u_area_u", area_u, area_count);
            s.set_vec3_array("u_area_v", area_v, area_count);
            s.set_vec3_array("u_area_radiance", area_rad, area_count);
        }
```

`bridge.frag`: after the spot uniforms (line ~128) add:

```glsl
// ── Static area lights: strips and panels (spec 2026-10-08-bridge-emitters §16.3) ──
// Rectangles: centre (xyz) + range (w), perpendicular half-axes u and v;
// each emits toward cross(u, v) only. Twins of the pbr:: functions of the
// same names in bridge_pbr.h.
const int MAX_AREA_LIGHTS = 32;     // renderer::kBridgeMaxAreaLights
uniform int  u_area_count;
uniform vec4 u_area_center_range[MAX_AREA_LIGHTS];
uniform vec3 u_area_u[MAX_AREA_LIGHTS];
uniform vec3 u_area_v[MAX_AREA_LIGHTS];
uniform vec3 u_area_radiance[MAX_AREA_LIGHTS];
```

After `accumulate_spots` add the twins (same formulas as Task 3, GLSL):

```glsl
float range_window(float d, float range) {
    float r = d / max(range, 1e-4);
    float w = clamp(1.0 - r * r * r * r, 0.0, 1.0);
    return w * w;
}

float area_integrate_edge(vec3 v1, vec3 v2) {
    float cos_t = clamp(dot(v1, v2), -1.0, 1.0);
    float theta = acos(cos_t);
    return cross(v1, v2).z * ((theta > 0.001) ? theta / sin(theta) : 1.0);
}

// Heitz's ClipQuadToHorizon (tangent space, z up). Returns the vertex count.
int area_clip_quad_to_horizon(inout vec3 L[5]) {
    int config = 0;
    if (L[0].z > 0.0) config += 1;
    if (L[1].z > 0.0) config += 2;
    if (L[2].z > 0.0) config += 4;
    if (L[3].z > 0.0) config += 8;
    int n = 0;
    if (config == 0) { n = 0; }
    else if (config == 1) { n = 3; L[1] = -L[1].z * L[0] + L[0].z * L[1]; L[2] = -L[3].z * L[0] + L[0].z * L[3]; }
    else if (config == 2) { n = 3; L[0] = -L[0].z * L[1] + L[1].z * L[0]; L[2] = -L[2].z * L[1] + L[1].z * L[2]; }
    else if (config == 3) { n = 4; L[2] = -L[2].z * L[1] + L[1].z * L[2]; L[3] = -L[3].z * L[0] + L[0].z * L[3]; }
    else if (config == 4) { n = 3; L[0] = -L[3].z * L[2] + L[2].z * L[3]; L[1] = -L[1].z * L[2] + L[2].z * L[1]; }
    else if (config == 5) { n = 0; }
    else if (config == 6) { n = 4; L[0] = -L[0].z * L[1] + L[1].z * L[0]; L[3] = -L[3].z * L[2] + L[2].z * L[3]; }
    else if (config == 7) { n = 5; L[4] = -L[3].z * L[0] + L[0].z * L[3]; L[3] = -L[3].z * L[2] + L[2].z * L[3]; }
    else if (config == 8) { n = 3; L[0] = -L[0].z * L[3] + L[3].z * L[0]; L[1] = -L[2].z * L[3] + L[3].z * L[2]; L[2] = L[3]; }
    else if (config == 9) { n = 4; L[1] = -L[1].z * L[0] + L[0].z * L[1]; L[2] = -L[2].z * L[3] + L[3].z * L[2]; }
    else if (config == 10) { n = 0; }
    else if (config == 11) { n = 5; L[4] = L[3]; L[3] = -L[2].z * L[3] + L[3].z * L[2]; L[2] = -L[2].z * L[1] + L[1].z * L[2]; }
    else if (config == 12) { n = 4; L[1] = -L[1].z * L[2] + L[2].z * L[1]; L[0] = -L[0].z * L[3] + L[3].z * L[0]; }
    else if (config == 13) { n = 5; L[4] = L[3]; L[3] = L[2]; L[2] = -L[1].z * L[2] + L[2].z * L[1]; L[1] = -L[1].z * L[0] + L[0].z * L[1]; }
    else if (config == 14) { n = 5; L[4] = -L[0].z * L[3] + L[3].z * L[0]; L[0] = -L[0].z * L[1] + L[1].z * L[0]; }
    else { n = 4; }
    if (n == 3) L[3] = L[0];
    if (n == 4) L[4] = L[0];
    return n;
}

float rect_form_factor(vec3 p, vec3 n, vec3 c0, vec3 c1, vec3 c2, vec3 c3) {
    vec3 ln = normalize(cross(c1 - c0, c3 - c0));
    if (dot(ln, p - c0) <= 0.0) return 0.0;
    vec3 helper = (abs(n.z) < 0.9) ? vec3(0.0, 0.0, 1.0) : vec3(1.0, 0.0, 0.0);
    vec3 t1 = normalize(cross(helper, n));
    vec3 t2 = cross(n, t1);
    vec3 L[5];
    vec3 d0 = c0 - p, d1 = c1 - p, d2 = c2 - p, d3 = c3 - p;
    L[0] = vec3(dot(d0, t1), dot(d0, t2), dot(d0, n));
    L[1] = vec3(dot(d1, t1), dot(d1, t2), dot(d1, n));
    L[2] = vec3(dot(d2, t1), dot(d2, t2), dot(d2, n));
    L[3] = vec3(dot(d3, t1), dot(d3, t2), dot(d3, n));
    L[4] = L[0];
    int m = area_clip_quad_to_horizon(L);
    if (m == 0) return 0.0;
    for (int i = 0; i < 5; ++i) {
        float len = length(L[i]);
        if (len < 1e-9) return 0.0;
        L[i] /= len;
    }
    float s = area_integrate_edge(L[0], L[1]) + area_integrate_edge(L[1], L[2])
            + area_integrate_edge(L[2], L[3]);
    if (m >= 4) s += area_integrate_edge(L[3], L[4]);
    if (m == 5) s += area_integrate_edge(L[4], L[0]);
    return clamp(abs(s) / (2.0 * kPi), 0.0, 1.0);
}

vec3 rect_nearest(vec3 p, vec3 c, vec3 u, vec3 v) {
    float s = clamp(dot(p - c, u) / max(dot(u, u), 1e-12), -1.0, 1.0);
    float t = clamp(dot(p - c, v) / max(dot(v, v), 1e-12), -1.0, 1.0);
    return c + u * s + v * t;
}

vec3 rect_representative(vec3 p, vec3 r, vec3 c, vec3 u, vec3 v) {
    vec3 n = normalize(cross(u, v));
    float denom = dot(r, n);
    if (denom > -1e-6) return rect_nearest(p, c, u, v);
    float t = dot(c - p, n) / denom;
    if (t <= 0.0) return rect_nearest(p, c, u, v);
    return rect_nearest(p + r * t, c, u, v);
}

// Adds every area light's linear diffuse and GGX specular at this fragment
// (pbr::area_light). The probe capture passes its own normal/view and
// ignores `spec`.
void accumulate_area_lights(vec3 N, vec3 V, float NdotV, vec3 albedo, float metal,
                            float rough, vec3 F0, inout vec3 diffuse, inout vec3 spec) {
    for (int i = 0; i < u_area_count; ++i) {
        vec3 c = u_area_center_range[i].xyz;
        vec3 u = u_area_u[i], v = u_area_v[i];
        vec3 nl = normalize(cross(u, v));
        if (dot(nl, v_world - c) <= 0.0) continue;
        vec3 near_p = rect_nearest(v_world, c, u, v);
        float dn = length(near_p - v_world);
        float win = range_window(dn, u_area_center_range[i].w);
        if (win <= 0.0) continue;
        float ff = rect_form_factor(v_world, N, c - u - v, c + u - v, c + u + v, c - u + v);
        vec3 Ln = (near_p - v_world) / max(dn, 1e-4);
        vec3 Fd = F_schlick(max(dot(V, normalize(Ln + V)), 0.0), F0);
        vec3 rad = u_area_radiance[i] * win;
        diffuse += (vec3(1.0) - Fd) * (1.0 - metal) * albedo * rad * ff;
        vec3 rep = rect_representative(v_world, reflect(-V, N), c, u, v);
        float d = max(length(rep - v_world), 1e-4);
        vec3 L = (rep - v_world) / d;
        float NdotL = max(dot(N, L), 0.0);
        if (NdotL <= 0.0) continue;
        float cos_l = max(dot(-L, nl), 0.0);
        float area = 4.0 * length(u) * length(v);
        float omega = min(area * cos_l / (d * d), 2.0 * kPi);
        float a = rough * rough;
        float a_eff = min(a + sqrt(area / kPi) / (2.0 * d), 1.0);
        vec3 H = normalize(L + V);
        vec3 F = F_schlick(max(dot(V, H), 0.0), F0);
        spec += D_ggx(max(dot(N, H), 0.0), sqrt(a_eff)) * G_smith(NdotV, NdotL, rough) * F
              / max(4.0 * NdotV * NdotL, 1e-4) * rad * NdotL * omega;
    }
}
```

Note: `normalize(Ln + V)` where `Ln + V` is never zero for a receiver in front of the light (`V` is toward the eye, `Ln` toward the light; the one-sided test excluded the degenerate on-plane case).

Call sites. In the probe-capture branch replace `if (u_spot_count > 0) { ... }` with:

```glsl
        if (u_spot_count > 0 || u_area_count > 0) {
            float rough_c = clamp(channel(u_has_rough_map, u_rough_map, u_rough_override, 1.0), 0.04, 1.0);
            vec3 Vc = normalize(u_eye - v_world);
            vec3 spec_unused = vec3(0.0);
            accumulate_spots(nc, Vc, max(dot(nc, Vc), 1e-4), albedo_c, metal_c, rough_c,
                             f0_for(albedo_c, metal_c), lit, spec_unused);
            accumulate_area_lights(nc, Vc, max(dot(nc, Vc), 1e-4), albedo_c, metal_c, rough_c,
                                   f0_for(albedo_c, metal_c), lit, spec_unused);
        }
```

In the main view, after `accumulate_spots(N, V, NdotV, albedo, metal, rough, F0, diffuse, spec);`:

```glsl
        accumulate_area_lights(N, V, NdotV, albedo, metal, rough, F0, diffuse, spec);
```

Update the comment above it to "Static spots and area lights: direct light, never multiplied by AO."

- [ ] **Step 4: Run tests**

Run: `cmake --build build -j && $RT --gtest_filter='BridgePbrFrame.*:BridgePbrArea.*'`
Expected: PASS (the frame tests SKIP only with no GL context -- on this Mac they run). Shader compile errors appear at RUNTIME as a failing frame test with the GLSL log: read it, fix, rebuild.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/bridge_lighting_tuning.h \
        native/src/renderer/include/renderer/bridge_pass.h native/src/renderer/bridge_pass.cc \
        native/src/renderer/shaders/bridge.frag native/tests/renderer/bridge_pbr_frame_test.cc
git commit -m "feat(bridge): BridgePass area lights + bridge.frag accumulate_area_lights (spec §16.3)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Bindings -- area lights in, mesh geometry out

**Files:**
- Modify: `native/src/renderer/include/renderer/ray_trace.h`, `native/src/renderer/ray_trace.cc`
- Modify: `native/src/host/host_bindings.cc` (after `set_bridge_spot_colours`; after `ray_trace_mesh_pick`)
- Modify: `engine/host_io.py` (`_OPTIONAL_BINDINGS`; wrappers after `set_bridge_spot_colours`)
- Test: `native/tests/renderer/ray_trace_test.cc`, `tests/host/test_bridge_editor_bindings.py`, `tests/unit/test_host_io_binding_manifest.py`

**Interfaces:**
- Consumes: Task 4's `BridgeAreaLight`, `set_area_lights`, `set_area_radiance`, `kBridgeMaxAreaLights`.
- Produces:
  - C++: `std::vector<std::array<glm::vec3, 3>> renderer::mesh_triangles_linear(const assets::Model&, const glm::mat3& linear, int mesh)` -- rest-pose triangles of one mesh, instance-relative, winding kept.
  - Binding `set_bridge_area_lights(areas, captures=None) -> int` with rows `(centre3, half_u3, half_v3, range, (r,g,b), intensity)`, captures `[((r,g,b) green, (r,g,b) yellow/red)]` x intensity.
  - Binding `set_bridge_area_colours(radiance)`.
  - Binding `bridge_mesh_geometry(instance_id, mesh) -> None | (vertices, normal_sum, area)`, instance-relative.
  - `host_io.set_bridge_area_lights(areas) -> int`: rows `(centre, half_u, half_v, range, rgb, intensity[, cap_green, cap_alert])`; 0 headless.
  - `host_io.set_bridge_area_colours(colours) -> None`
  - `host_io.bridge_mesh_geometry(instance_id, mesh) -> Optional[tuple[list[Vec], Vec, float]]` -- WORLD space; None headless, stale or unknown mesh; never raises.

- [ ] **Step 1: Write the failing tests**

`native/tests/renderer/ray_trace_test.cc`, append (reuses the file's `single_triangle_model`; put the tests after the anonymous namespace that defines it):

```cpp
TEST(MeshTrianglesLinear, ReturnsTheMeshesTrianglesInWindingOrder) {
    const auto m = single_triangle_model({0, 0, 0}, {1, 0, 0}, {0, 1, 0});
    const auto tris = renderer::mesh_triangles_linear(m, glm::mat3(1.0f), 0);
    ASSERT_EQ(tris.size(), 1u);
    EXPECT_EQ(tris[0][0], glm::vec3(0, 0, 0));
    EXPECT_EQ(tris[0][1], glm::vec3(1, 0, 0));
    EXPECT_EQ(tris[0][2], glm::vec3(0, 1, 0));
}

TEST(MeshTrianglesLinear, AppliesTheLinearPartAndSkipsOtherMeshes) {
    const auto m = single_triangle_model({0, 0, 0}, {1, 0, 0}, {0, 1, 0});
    const auto tris = renderer::mesh_triangles_linear(m, glm::mat3(2.0f), 0);
    ASSERT_EQ(tris.size(), 1u);
    EXPECT_EQ(tris[0][1], glm::vec3(2, 0, 0));
    EXPECT_TRUE(renderer::mesh_triangles_linear(m, glm::mat3(1.0f), 1).empty());
    EXPECT_TRUE(renderer::mesh_triangles_linear(m, glm::mat3(1.0f), -1).empty());
}
```

(If `single_triangle_model` places the triangle under a node with a non-identity transform, compare against what `ray_trace_instance` hits instead -- read the helper first; the assertion that matters is "same three points, same order".)

`tests/host/test_bridge_editor_bindings.py`, append:

```python
# Area lights + mesh geometry (spec 2026-10-08-bridge-emitters §16.3).

_AREA = ((0.0, 0.0, 50.0), (5.0, 0.0, 0.0), (0.0, -5.0, 0.0), 120.0, (1.0, 1.0, 1.0), 4.0)


@pytest.mark.parametrize("name", [
    "set_bridge_area_lights", "set_bridge_area_colours", "bridge_mesh_geometry"])
def test_area_binding_exists(host_module, name):
    assert hasattr(host_module, name)


def test_set_bridge_area_lights_counts_drops_and_takes_empty_before_init(host_module):
    assert host_module.set_bridge_area_lights([_AREA]) == 0
    assert host_module.set_bridge_area_lights([_AREA] * 35) == 3
    assert host_module.set_bridge_area_lights([]) == 0


def test_a_zero_size_or_non_finite_area_light_is_dropped(host_module):
    flat = ((0.0, 0.0, 50.0), (5.0, 0.0, 0.0), (0.0, 0.0, 0.0), 120.0, (1.0, 1.0, 1.0), 4.0)
    nan = ((0.0, 0.0, float("nan")), (5.0, 0.0, 0.0), (0.0, -5.0, 0.0), 120.0,
           (1.0, 1.0, 1.0), 4.0)
    no_range = ((0.0, 0.0, 50.0), (5.0, 0.0, 0.0), (0.0, -5.0, 0.0), 0.0, (1.0, 1.0, 1.0), 4.0)
    assert host_module.set_bridge_area_lights([flat, nan, no_range, _AREA]) == 3


def test_set_bridge_area_lights_on_a_live_bridge_dirties_the_probes(probe_stash_guard, dbridge):
    h, _iid = dbridge
    assert h.bridge_probe_state()["capture_pending"] is False
    assert h.set_bridge_area_lights([_AREA]) == 0
    assert h.bridge_probe_state()["capture_pending"] is True
    h.set_bridge_area_colours([(2.0, 2.0, 2.0)])          # never raises


def test_mesh_geometry_on_dbridge(dbridge, monkeypatch):
    h, iid = dbridge
    monkeypatch.setattr(host_io, "_h", h)
    verts, normal_sum, area = host_io.bridge_mesh_geometry(iid, 0)
    assert len(verts) >= 3 and len(verts) % 3 == 0 and area > 0
    assert len(normal_sum) == 3
    assert host_io.bridge_mesh_geometry(iid, 10 ** 6) is None


def test_mesh_geometry_of_a_stale_id_is_none(host_module, monkeypatch):
    monkeypatch.setattr(host_io, "_h", host_module)
    assert host_io.bridge_mesh_geometry(host_module.InstanceId(), 0) is None


def test_area_wrappers_degrade_headless(monkeypatch):
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.set_bridge_area_lights([_AREA]) == 0
    assert host_io.set_bridge_area_colours([(1.0, 1.0, 1.0)]) is None
    assert host_io.bridge_mesh_geometry(object(), 0) is None
```

`tests/unit/test_host_io_binding_manifest.py`: in the `_OPTIONAL_BINDINGS` frozenset assertion add `"set_bridge_area_lights", "set_bridge_area_colours", "bridge_mesh_geometry",`.

- [ ] **Step 2: Run to verify they fail**

Run: `cmake --build build -j --target renderer_tests` (expect `mesh_triangles_linear` undeclared), then `uv run pytest tests/unit/test_host_io_binding_manifest.py tests/host/test_bridge_editor_bindings.py -q` (expect failures).

- [ ] **Step 3: Implement**

`ray_trace.h`, after `ray_trace_instance_linear` (add `#include <array>` if missing):

```cpp
/// One mesh's rest-pose triangles (the trace accel's, so node transforms are
/// applied and the winding is the mesh's own) through `linear`
/// (Instance::world_linear): instance-relative, like the hits above. Empty
/// for an unknown mesh. The bridge editor's light shapes measure objects
/// with it (spec 2026-10-08-bridge-emitters §16.2).
std::vector<std::array<glm::vec3, 3>> mesh_triangles_linear(
    const assets::Model& model, const glm::mat3& linear, int mesh);
```

`ray_trace.cc`, after `ray_trace_instance_linear`:

```cpp
std::vector<std::array<glm::vec3, 3>> mesh_triangles_linear(
    const assets::Model& model, const glm::mat3& linear, int mesh)
{
    std::vector<std::array<glm::vec3, 3>> out;
    if (mesh < 0 || model.nodes.empty() || model.meshes.empty()) return out;
    const TraceAccel& accel = ensure_trace_accel(model);
    for (const TraceTri& t : accel.tris)
        if (t.mesh == mesh) out.push_back({linear * t.v0, linear * t.v1, linear * t.v2});
    return out;
}
```

(Check `ensure_trace_accel` copies vertices in index order v0, v1, v2; the gtest above pins it.)

`host_bindings.cc`, after the `set_bridge_spot_colours` def:

```cpp
    // Static bridge area lights (spec 2026-10-08-bridge-emitters §16.3): rows
    // (centre, half_u, half_v, range, rgb, intensity); each emits toward
    // cross(half_u, half_v). A row with any non-finite value, a zero-size
    // rectangle (|half_u x half_v| < 1e-8) or range <= 0 is dropped -- a NaN
    // normal reaching the shader becomes a NaN bloom square. Returns the
    // dropped count (invalid + over kBridgeMaxAreaLights; also before init).
    // Captures as set_bridge_spots. BridgePass marks the probes dirty itself.
    m.def("set_bridge_area_lights",
          [](const std::vector<std::tuple<std::tuple<float, float, float>,
                                          std::tuple<float, float, float>,
                                          std::tuple<float, float, float>,
                                          float,
                                          std::tuple<float, float, float>,
                                          float>>& areas,
             py::object captures) -> std::size_t {
              auto v3 = [](const std::tuple<float, float, float>& t) {
                  return glm::vec3(std::get<0>(t), std::get<1>(t), std::get<2>(t));
              };
              auto finite3 = [](const glm::vec3& a) {
                  return std::isfinite(a.x) && std::isfinite(a.y) && std::isfinite(a.z);
              };
              std::vector<std::pair<glm::vec3, glm::vec3>> caps;
              if (!captures.is_none()) {
                  try {
                      for (auto item : captures) {
                          auto pr = item.cast<std::tuple<std::tuple<float, float, float>,
                                                         std::tuple<float, float, float>>>();
                          caps.emplace_back(v3(std::get<0>(pr)), v3(std::get<1>(pr)));
                      }
                  } catch (const py::cast_error&) {
                      caps.clear();
                  }
                  if (caps.size() != areas.size()) caps.clear();
              }
              std::vector<renderer::BridgeAreaLight> v;
              v.reserve(areas.size());
              std::size_t invalid = 0, index = 0;
              for (const auto& a : areas) {
                  const std::size_t i = index++;
                  const auto& [c, u, w, range, rgb, intensity] = a;
                  const glm::vec3 hu = v3(u), hv = v3(w);
                  if (!finite3(v3(c)) || !finite3(hu) || !finite3(hv) || !finite3(v3(rgb)) ||
                      !std::isfinite(range) || !(range > 0.0f) || !std::isfinite(intensity) ||
                      !finite3(v3(rgb) * intensity) ||
                      !(glm::length(glm::cross(hu, hv)) >= 1e-8f) ||
                      (!caps.empty() && (!finite3(caps[i].first * intensity) ||
                                         !finite3(caps[i].second * intensity)))) {
                      ++invalid;
                      continue;
                  }
                  renderer::BridgeAreaLight al;
                  al.center = v3(c);
                  al.half_u = hu;
                  al.half_v = hv;
                  al.range = range;
                  al.radiance = v3(rgb) * intensity;
                  if (!caps.empty()) {
                      al.has_capture = true;
                      al.capture_radiance[0] = caps[i].first * intensity;
                      al.capture_radiance[1] = caps[i].second * intensity;
                  }
                  v.push_back(al);
              }
              const std::size_t cap = static_cast<std::size_t>(renderer::kBridgeMaxAreaLights);
              if (!g_bridge_pass) return invalid + (v.size() > cap ? v.size() - cap : 0);
              return invalid + g_bridge_pass->set_area_lights(std::move(v));
          },
          py::arg("areas"), py::arg("captures") = py::none(),
          "Static bridge area lights (strips / panels): [(centre3, half_u3, half_v3, "
          "range, (r, g, b), intensity)], emitting toward cross(half_u, half_v). "
          "Invalid rows (non-finite, zero size, range <= 0) are dropped; the rest "
          "keep the first 32. Returns the dropped count. captures as "
          "set_bridge_spots. Never raises for a stale state.");

    m.def("set_bridge_area_colours",
          [](const std::vector<std::tuple<float, float, float>>& radiance) {
              if (!g_bridge_pass) return;
              std::vector<glm::vec3> v;
              v.reserve(radiance.size());
              for (const auto& [r, g, b] : radiance) v.emplace_back(r, g, b);
              g_bridge_pass->set_area_radiance(v);
          },
          py::arg("radiance"),
          "Live LINEAR radiance per bridge area light, in set_bridge_area_lights "
          "order. Extra entries ignored, missing kept, non-finite -> 0. Never "
          "dirties the probes; no-op before init.");
```

After the `ray_trace_mesh_pick` def:

```cpp
    // One mesh's triangles for the bridge editor's light shapes (spec
    // 2026-10-08-bridge-emitters §16.2): (vertices -- three per triangle,
    // instance-relative --, the area-weighted normal sum, the total area).
    // None for a stale id or an unknown / empty mesh; never raises.
    m.def("bridge_mesh_geometry",
          [](scenegraph::InstanceId id, int mesh) -> py::object {
              auto* inst = g_world.get(id);
              if (inst == nullptr) return py::none();
              const assets::Model* model = resolve_model(inst->model_handle);
              if (model == nullptr || mesh < 0 ||
                  mesh >= static_cast<int>(model->meshes.size()))
                  return py::none();
              const auto tris = renderer::mesh_triangles_linear(*model, inst->world_linear, mesh);
              if (tris.empty()) return py::none();
              py::list verts;
              glm::vec3 nsum(0.0f);
              float area = 0.0f;
              for (const auto& t : tris) {
                  for (const auto& p : t) verts.append(py::make_tuple(p.x, p.y, p.z));
                  const glm::vec3 c = glm::cross(t[1] - t[0], t[2] - t[0]) * 0.5f;
                  nsum += c;
                  area += glm::length(c);
              }
              return py::make_tuple(verts, py::make_tuple(nsum.x, nsum.y, nsum.z), area);
          },
          py::arg("instance_id"), py::arg("mesh"),
          "One mesh's rest-pose triangles: (vertices, normal_sum, area), "
          "instance-relative; None for a stale id or unknown mesh.");
```

`engine/host_io.py`: add `"set_bridge_area_lights", "set_bridge_area_colours", "bridge_mesh_geometry",` to `_OPTIONAL_BINDINGS`; after `set_bridge_spot_colours` add:

```python
def set_bridge_area_lights(areas) -> int:
    """Bridge area lights -- strips and panels (spec 2026-10-08-bridge-emitters
    §16.3; production, not developer-gated): `areas` is [(centre3, half_u3,
    half_v3, range, (r, g, b), intensity[, capture_green3, capture_alert3])],
    each emitting toward cross(half_u, half_v). Captures as set_bridge_spots
    (every light or none). Returns how many were DROPPED (invalid + over the
    cap). 0 headless."""
    fn = getattr(_h, "set_bridge_area_lights", None) if _h is not None else None
    if fn is None:
        return 0

    def _v3(v):
        x, y, z = v
        return (float(x), float(y), float(z))

    rows, caps = [], []
    for a in areas:
        c, u, v, r, rgb, k = a[:6]
        rows.append((_v3(c), _v3(u), _v3(v), float(r), _v3(rgb), float(k)))
        if len(a) >= 8:
            caps.append((_v3(a[6]), _v3(a[7])))
    if caps and len(caps) == len(rows):
        return int(fn(rows, caps))
    return int(fn(rows))


def set_bridge_area_colours(colours) -> None:
    """Live LINEAR radiance per bridge area light, in set_bridge_area_lights
    order; never recaptures the probes. No-op headless."""
    fn = getattr(_h, "set_bridge_area_colours", None) if _h is not None else None
    if fn is not None:
        fn([(float(r), float(g), float(b)) for r, g, b in colours])


def bridge_mesh_geometry(instance_id, mesh):
    """One bridge mesh's rest-pose triangles in WORLD space (spec §16.2):
    (vertices, normal_sum, area), three vertices per triangle, the normal sum
    area-weighted and wound as drawn. None headless, for a stale id or an
    unknown mesh; never raises (the runtime asks at every bridge load)."""
    fn = getattr(_h, "bridge_mesh_geometry", None) if _h is not None else None
    if fn is None:
        return None
    try:
        got = fn(instance_id, int(mesh))
        if got is None:
            return None
        verts, n, area = got
        t = _h.instance_translation(instance_id)
    except Exception:  # noqa: BLE001 - a stale id / binary is "no geometry"
        return None
    if t is not None:
        verts = [(x + t[0], y + t[1], z + t[2]) for x, y, z in verts]
    return ([(float(x), float(y), float(z)) for x, y, z in verts],
            (float(n[0]), float(n[1]), float(n[2])), float(area))
```

- [ ] **Step 4: Run tests**

Run: `cmake --build build -j && $RT --gtest_filter='MeshTrianglesLinear.*' && uv run pytest tests/unit/test_host_io_binding_manifest.py tests/host/test_bridge_editor_bindings.py -q`
Expected: PASS (`dbridge` tests SKIP only without BC content; this machine has it via `settings.json`).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/ray_trace.h native/src/renderer/ray_trace.cc \
        native/src/host/host_bindings.cc engine/host_io.py \
        native/tests/renderer/ray_trace_test.cc tests/host/test_bridge_editor_bindings.py \
        tests/unit/test_host_io_binding_manifest.py
git commit -m "feat(bridge): area-light and mesh-geometry bindings (spec §16.2-16.3)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `lights.py` -- shared budget, area rows, live colours

**Files:**
- Modify: `engine/bridge_editor/lights.py`
- Test: `tests/unit/test_bridge_lights.py` (append)

**Interfaces:**
- Consumes: `light_shapes.light_rect`, `light_shapes.Frame`.
- Produces:
  - `lights.MAX_LIGHTS = 32` (`MAX_SPOTS` stays as an alias = `MAX_LIGHTS`).
  - `lights.DEFAULT_AREA_INTENSITY = 1.0`, `lights.DEFAULT_RANGE = 200.0`.
  - `lights.spots(doc, matched, resolved, mapped=frozenset())` -- unchanged signature; spots only, the cap counted over ALL shapes; the cap warnings are reported HERE only.
  - `lights.areas(doc, matched, resolved, frame_for, mapped=frozenset()) -> (rows, warnings)` -- `frame_for(mesh) -> Optional[Frame]`; rows `(centre, half_u, half_v, range, green_rgb, intensity, green_rgb, alert_rgb)`; warnings only for "no geometry".
  - `lights.live_area_colours(doc, matched, resolved, fade, t, frame_for, mapped=frozenset()) -> list[rgb]`, same order and same skips as `areas`.

- [ ] **Step 1: Write the failing tests** -- append to `tests/unit/test_bridge_lights.py`:

```python
# ── strips and panels (spec §16.1, §16.3) ───────────────────────────────────

from engine.bridge_editor import light_shapes as ls

PANEL_FRAME = ls.Frame(right=(1.0, 0.0, 0.0), up=(0.0, 0.0, 1.0), facing=(0.0, -1.0, 0.0),
                       centre=(20.0, 50.0, 20.0), half=(20.0, 10.0, 0.0))


def _area_doc():
    d = _doc()
    ld.object_entry(d, 6, "lamp")["lights"].append(
        {"shape": "strip", "edge": "top", "intensity": 40, "range": 150})
    ld.object_entry(d, 7, "wall")["lights"] = [{"shape": "panel", "intensity": 2}]
    return d


AREA_MATCHED = {"5:roof": 1, "6:lamp": 2, "7:wall": 3}


def test_spots_leave_out_strips_and_panels():
    d = _area_doc()
    spots, _ = lights.spots(d, AREA_MATCHED, _links(d, AREA_MATCHED))
    assert [s[0] for s in spots] == [(1, 2, 3), (4, 5, 6), (0, 0, 9)]


def test_area_rows_carry_the_rectangle_range_colour_and_intensity():
    d = _area_doc()
    rows, warnings = lights.areas(d, AREA_MATCHED, _links(d, AREA_MATCHED),
                                  lambda mesh: PANEL_FRAME)
    assert warnings == [] and len(rows) == 2
    strip, panel = rows
    want = ls.strip_rect(PANEL_FRAME, "top")
    assert strip[:3] == (want.centre, want.half_u, want.half_v)
    assert strip[3] == 150 and strip[5] == 40
    assert panel[3] == lights.DEFAULT_RANGE and panel[5] == 2
    assert panel[4] == panel[6] == (1.0, 1.0, 1.0)      # no material: steady white


def test_spots_and_area_lights_share_one_budget_in_mesh_order():
    d = ld.empty_doc("x")
    ld.object_entry(d, 1, "a")["lights"] = [
        {"position": [0, 0, i], "direction": [0, 0, -1]} for i in range(20)]
    ld.object_entry(d, 2, "b")["lights"] = [{"shape": "panel"} for _ in range(20)]
    matched = {"1:a": 1, "2:b": 2}
    resolved = _links(d, matched)
    spots, warnings = lights.spots(d, matched, resolved)
    rows, area_warnings = lights.areas(d, matched, resolved, lambda m: PANEL_FRAME)
    assert len(spots) == 20 and len(rows) == 12
    assert len(warnings) == 8 and "2:b light 13" in warnings[0]
    assert area_warnings == []                        # the cap is reported once, by spots()


def test_a_light_without_geometry_is_skipped_and_the_colours_stay_aligned():
    d = ld.empty_doc("x")
    d["materials"]["red"] = {"emission": 0, "modifiers": [
        {"type": "state", "scope": list(ld.STATES), "tint": [1, 0, 0], "level": 1}]}
    ld.object_entry(d, 1, "gone")["lights"] = [{"shape": "panel", "intensity": 1}]
    o = ld.object_entry(d, 2, "here")
    o["material"] = "red"
    o["lights"] = [{"shape": "panel", "intensity": 3}]
    matched = {"1:gone": 1, "2:here": 2}
    resolved = _links(d, matched)
    frames = {2: PANEL_FRAME}
    rows, warnings = lights.areas(d, matched, resolved, frames.get)
    assert len(rows) == 1 and warnings == ["1:gone light 1: no geometry for its object; skipped"]
    fade = bh.StateFade("green")
    live = lights.live_area_colours(d, matched, resolved, fade, 0.0, frames.get)
    assert len(live) == 1 and live[0][0] > 0 and live[0][1] == 0     # the red light's colour
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_bridge_lights.py -q`
Expected: FAIL (`light_shapes` frames not consumed; `lights.areas` missing; spots include strips).

- [ ] **Step 3: Implement** -- rewrite `engine/bridge_editor/lights.py` keeping its existing behaviour for spots:

```python
"""Object lights (spec 2026-10-08-bridge-emitters §13.2, §11.4, §14, §16). The
light LISTS are static -- every light of every matched object, mesh order,
with green and yellow/red probe-capture colours -- so a state change or a
pulse never recaptures the probes; `live_colours` / `live_area_colours`
give the radiance per frame in the same orders. Spots, strips and panels
share ONE budget of MAX_LIGHTS (§16.3). A light's colour follows the glow of
its mesh's resolved material (the object's link, else its texture's;
`mapped` = the meshes whose texture has an `_emissive` map, for the
unset-emission default), display -> linear by ^2.2; a material that sets no
glow lights steady white. A capture colour is the steady value in that
state, 0 when an animation runs there. A strip or panel's rectangle comes
from its object's frame (light_shapes, §16.2)."""
from engine.bridge_editor import behaviour, light_shapes

MAX_LIGHTS = 32
MAX_SPOTS = MAX_LIGHTS          # the old name; the budget is shared now
DEFAULT_INTENSITY = 2000.0
DEFAULT_AREA_INTENSITY = 1.0
DEFAULT_RANGE = 200.0
GAMMA = 2.2


def to_linear(rgb):
    return tuple(max(float(c), 0.0) ** GAMMA for c in rgb)


def _is_spot(light):
    return light.get("shape", "spot") == "spot"


def _intensity(light):
    default = DEFAULT_INTENSITY if _is_spot(light) else DEFAULT_AREA_INTENSITY
    return light.get("intensity", default) * light.get("light_scale", 1.0)


def _material(doc, name):
    """The material a light's colour follows: its mesh's (resolved), unless
    it sets no glow -- a finish-only material lights like no material at
    all: steady white (spec §13.2; review C1: the upgraded DBridge 299/319
    lights went dark)."""
    mat = doc["materials"].get(name) if name else None
    return mat if mat is not None and behaviour.drives_glow(mat) else behaviour.WHITE


def _lit(doc, matched, resolved, mapped):
    """Every light within the shared budget, mesh order: (light, material,
    has_map, mesh, label); plus one warning per light dropped by the cap."""
    out, warnings = [], []
    for key in sorted(matched, key=lambda k: matched[k]):
        obj = doc["objects"].get(key, {})
        mesh = matched[key]
        mat = _material(doc, resolved.get(mesh))
        for i, light in enumerate(obj.get("lights", ())):
            label = f"{key} light {i + 1}"
            if len(out) >= MAX_LIGHTS:
                warnings.append(f"{label}: dropped (more than {MAX_LIGHTS} bridge lights)")
                continue
            out.append((light, mat, mesh in mapped, mesh, label))
    return out, warnings


def _capture(mat, state, has_map):
    if any(m["type"] == "animation" and state in m["scope"]
           for m in mat.get("modifiers", ())):
        return (0.0, 0.0, 0.0)
    rgb, _ = behaviour.output(mat, state, 0.0, has_map)
    return to_linear(rgb)


def spots(doc, matched, resolved, mapped=frozenset()):
    """The spot rows, and the shared budget's drop warnings (reported here
    only, so a caller that also asks for areas() sees each once)."""
    lit, warnings = _lit(doc, matched, resolved, mapped)
    out = []
    for light, mat, has_map, _mesh, _label in lit:
        if not _is_spot(light):
            continue
        green = _capture(mat, "green", has_map)
        out.append((tuple(light["position"]), tuple(light["direction"]),
                    light.get("inner_deg", 30), light.get("outer_deg", 60),
                    light.get("range", DEFAULT_RANGE), green, _intensity(light),
                    green, _capture(mat, "yellow", has_map)))
    return out, warnings


def _areas_lit(doc, matched, resolved, frame_for, mapped):
    out, warnings = [], []
    for light, mat, has_map, mesh, label in _lit(doc, matched, resolved, mapped)[0]:
        if _is_spot(light):
            continue
        fr = frame_for(mesh)
        if fr is None:
            warnings.append(f"{label}: no geometry for its object; skipped")
            continue
        out.append((light, mat, has_map, light_shapes.light_rect(light, fr)))
    return out, warnings


def areas(doc, matched, resolved, frame_for, mapped=frozenset()):
    """The strip / panel rows: (centre, half_u, half_v, range, colour,
    intensity, capture_green, capture_alert). `frame_for(mesh)` is the
    object's light_shapes.Frame, or None -- that light is skipped with a
    warning (and live_area_colours skips it too, so colours stay aligned)."""
    lit, warnings = _areas_lit(doc, matched, resolved, frame_for, mapped)
    out = []
    for light, mat, has_map, r in lit:
        green = _capture(mat, "green", has_map)
        out.append((r.centre, r.half_u, r.half_v, light.get("range", DEFAULT_RANGE),
                    green, _intensity(light), green, _capture(mat, "yellow", has_map)))
    return out, warnings


def live_colours(doc, matched, resolved, fade, t, mapped=frozenset()):
    lit, _ = _lit(doc, matched, resolved, mapped)
    out = []
    for light, mat, has_map, _mesh, _label in lit:
        if not _is_spot(light):
            continue
        rgb, _k = fade.output(mat, t, has_map)
        k = _intensity(light)
        out.append(tuple(c * k for c in to_linear(rgb)))
    return out


def live_area_colours(doc, matched, resolved, fade, t, frame_for, mapped=frozenset()):
    lit, _ = _areas_lit(doc, matched, resolved, frame_for, mapped)
    out = []
    for light, mat, has_map, _r in lit:
        rgb, _k = fade.output(mat, t, has_map)
        k = _intensity(light)
        out.append(tuple(c * k for c in to_linear(rgb)))
    return out
```

Note `live_area_colours` calls `frame_for` every frame: the runtime (Task 7) caches frames, so it is a dict lookup. `light_rect` per frame is a few dozen float ops per light; acceptable at <= 32 lights.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_bridge_lights.py tests/unit/test_bridge_runtime.py -q`
Expected: PASS (existing spot tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/lights.py tests/unit/test_bridge_lights.py
git commit -m "feat(bridge): lights -- shared 32-light budget, strip/panel rows (spec §16.3)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Runtime pushes area lights

**Files:**
- Modify: `engine/bridge_editor/runtime.py`
- Test: `tests/unit/test_bridge_runtime.py` (append)

**Interfaces:**
- Consumes: `host_io.bridge_mesh_geometry`, `set_bridge_area_lights`, `set_bridge_area_colours` (via `self._io`); `light_shapes.frame`; `lights.areas`, `lights.live_area_colours`.
- Produces: `BridgeRuntime` clears area lights wherever it clears spots; `push` uploads the area list; `tick` pushes live area colours; frames are fetched once per mesh per `attach`.

- [ ] **Step 1: Write the failing tests** -- append to `tests/unit/test_bridge_runtime.py`:

```python
# ── strips and panels (spec §16.3) ──────────────────────────────────────────

WALL_GEOM = ([(0.0, 50.0, 10.0), (0.0, 50.0, 30.0), (40.0, 50.0, 30.0),
              (0.0, 50.0, 10.0), (40.0, 50.0, 30.0), (40.0, 50.0, 10.0)],
             (0.0, -800.0, 0.0), 800.0)


class GeomIO(FakeIO):
    def __init__(self, geom=WALL_GEOM, **kw):
        super().__init__(**kw)
        self.geom = geom
        self.geom_calls = 0

    def bridge_mesh_geometry(self, iid, mesh):
        self.geom_calls += 1
        return self.geom


def _strip_doc(proj):
    d = ld.empty_doc("x")
    ld.object_entry(d, 3, "floor")["lights"] = [
        {"shape": "strip", "edge": "top", "intensity": 40, "range": 150}]
    lw.save(d, proj / "bridge_lighting" / f"{HASH}.json")
    return d


def _last(io, name):
    return [c for c in io.calls if c[0] == name][-1]


def test_attach_clears_then_pushes_the_strip_on_its_top_edge(proj):
    _strip_doc(proj)
    io = GeomIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (20.0, 0.0, 20.0), alert=lambda: 0)
    rt.attach("iid")
    pushes = [c for c in io.calls if c[0] == "set_bridge_area_lights"]
    assert pushes[0] == ("set_bridge_area_lights", [])          # the previous bridge's cleared
    [row] = pushes[-1][1]
    assert row[0] == (20.0, 50.0, 30.0) and row[3] == 150 and row[5] == 40


def test_tick_pushes_live_area_colours(proj):
    _strip_doc(proj)
    io = GeomIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (20.0, 0.0, 20.0), alert=lambda: 0)
    rt.attach("iid")
    rt.tick(0.016)
    assert len(_last(io, "set_bridge_area_colours")[1]) == 1


def test_geometry_is_fetched_once_per_mesh_per_attach(proj):
    _strip_doc(proj)
    io = GeomIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (20.0, 0.0, 20.0), alert=lambda: 0)
    rt.attach("iid")
    for _ in range(5):
        rt.tick(0.016)
    rt.push(rt._doc)
    assert io.geom_calls == 1
    rt.attach("iid")
    assert io.geom_calls == 2


def test_a_strip_with_no_geometry_is_warned_and_not_pushed(proj):
    _strip_doc(proj)
    io = GeomIO(geom=None)
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (20.0, 0.0, 20.0), alert=lambda: 0)
    rt.attach("iid")
    assert _last(io, "set_bridge_area_lights")[1] == []
    warnings = rt.push(rt._doc)
    assert any("no geometry" in w for w in warnings)


def test_detach_clears_the_area_lights(proj):
    _strip_doc(proj)
    io = GeomIO()
    rt = runtime.BridgeRuntime(io=io, eye=lambda: (20.0, 0.0, 20.0), alert=lambda: 0)
    rt.attach("iid")
    rt.detach()
    assert _last(io, "set_bridge_area_lights") == ("set_bridge_area_lights", [])
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_bridge_runtime.py -q`
Expected: FAIL (no `set_bridge_area_lights` calls).

- [ ] **Step 3: Implement** in `engine/bridge_editor/runtime.py`:

- Import: `from engine.bridge_editor import behaviour, glow, light_shapes, lights, materials`.
- In `__init__` add `self._frames = {}`.
- In `attach`, in the first guarded clear block add `self._io.set_bridge_area_lights([])` after `set_bridge_spots([])`; and reset `self._frames = {}` on the line that resets `self._meshes, ...`.
- In `detach`, add `self._io.set_bridge_area_lights([])` after `set_bridge_spots([])`, and `self._frames = {}` in the `finally`.
- Add:

```python
    def _frame_for(self, mesh):
        """The object's light_shapes.Frame (spec §16.2), fetched once per mesh
        per attach: the geometry is static, the eye is the bridge camera's."""
        if mesh not in self._frames:
            got = self._io.bridge_mesh_geometry(self._iid, mesh) if self._iid is not None else None
            self._frames[mesh] = (light_shapes.frame(*got, eye=tuple(self._eye()))
                                  if got else None)
        return self._frames[mesh]
```

- In `push`, after the `dropped = self._io.set_bridge_spots(spot_list)` block:

```python
            area_list, area_warnings = lights.areas(
                doc, self._matched, self._resolved, self._frame_for, self._mapped)
            for w in area_warnings:
                dev_mode.log_swallowed("bridge lighting emitters", ld.BridgeLightingError(w))
            warnings += area_warnings
            dropped = self._io.set_bridge_area_lights(area_list)
            if dropped:
                msg = (f"{dropped} bridge area light(s) dropped as invalid "
                       "(zero size or non-finite values)")
                warnings.append(msg)
                dev_mode.log_swallowed(
                    "bridge lighting area lights dropped", ld.BridgeLightingError(msg))
```

- In `_push_live`, after `set_bridge_spot_colours(...)`:

```python
            self._io.set_bridge_area_colours(
                lights.live_area_colours(self._doc, self._matched, self._resolved,
                                         self._fade, self._t, self._frame_for, self._mapped))
```

- Update the `push` docstring's first sentence to "Re-push overrides, the static spot and area-light lists (geometry + probe-capture colours) and the glow table ...".

Note `FakeIO.__getattr__` returns `0` for unknown calls, so `bridge_mesh_geometry` on a plain `FakeIO` is `0` (falsy) -> no frame: existing tests keep passing.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_bridge_runtime.py tests/unit/test_bridge_emitters_panel.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/runtime.py tests/unit/test_bridge_runtime.py
git commit -m "feat(bridge): runtime pushes strip and panel lights (spec §16.3)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Editor edits -- add strip / panel, edit their fields

**Files:**
- Modify: `engine/bridge_editor/editing.py`
- Modify: `engine/ui/bridge_emitters_panel.py` (`_edit_action`'s `light-add` branch; `_light_action`)
- Test: `tests/unit/test_bridge_editing.py`, `tests/unit/test_bridge_emitters_panel.py` (append)

**Interfaces:**
- Consumes: `ld.EDGES`.
- Produces:
  - `editing.STRIP_INTENSITY = 40.0`, `editing.PANEL_INTENSITY = 2.0`, `editing.STRIP_OFFSET = 1.0`
  - `editing.add_area_light(doc, block, name, shape)` -- appends a strip (`edge "top"`, start 0, end 1, offset 1, range 200, intensity 40) or panel (`x [0,1]`, `y [0,1]`, offset 0, range 200, intensity 2).
  - `editing.set_light(light, field, raw)` also handles `edge`, `start`, `end`, `x0`, `x1`, `y0`, `y1`, `offset`.
  - Panel actions: `light-add` (spot, unchanged), `light-add:spot|strip|panel`; `light:<i>:<field>:<value>`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_bridge_editing.py`, append:

```python
# ── strips and panels (spec §16.4) ──────────────────────────────────────────

def test_add_area_light_appends_a_strip_or_a_panel_with_defaults():
    d = ld.empty_doc("x")
    editing.add_area_light(d, 5, "lip", "strip")
    editing.add_area_light(d, 5, "lip", "panel")
    strip, panel = d["objects"]["5:lip"]["lights"]
    assert strip == {"shape": "strip", "edge": "top", "start": 0.0, "end": 1.0,
                     "offset": editing.STRIP_OFFSET, "range": editing.LIGHT_RANGE,
                     "intensity": editing.STRIP_INTENSITY}
    assert panel == {"shape": "panel", "x": [0.0, 1.0], "y": [0.0, 1.0], "offset": 0.0,
                     "range": editing.LIGHT_RANGE, "intensity": editing.PANEL_INTENSITY}
    ld.validate(d)


def test_strip_fields_clamp_and_keep_start_le_end():
    light = {"shape": "strip", "edge": "top", "start": 0.0, "end": 1.0}
    editing.set_light(light, "edge", "left")
    editing.set_light(light, "edge", "middle")          # ignored
    assert light["edge"] == "left"
    editing.set_light(light, "start", "0.8")
    editing.set_light(light, "end", "0.5")              # drags start down with it
    assert (light["start"], light["end"]) == (0.5, 0.5)
    editing.set_light(light, "end", "7")
    assert light["end"] == 1.0
    editing.set_light(light, "offset", "-2.5")
    assert light["offset"] == -2.5


def test_panel_span_ends_drag_each_other_and_stay_valid():
    light = {"shape": "panel", "x": [0.0, 1.0], "y": [0.0, 1.0]}
    editing.set_light(light, "x0", "0.7")
    editing.set_light(light, "x1", "0.2")
    assert light["x"] == [0.2, 0.2]
    editing.set_light(light, "y1", "-1")
    assert light["y"] == [0.0, 0.0]
    d = ld.empty_doc("x")
    ld.object_entry(d, 5, "lip")["lights"] = [light]
    ld.validate(d)
```

(Use the file's existing imports; it already imports `editing` and `lighting_doc as ld` -- check its header and add what is missing.)

`tests/unit/test_bridge_emitters_panel.py`, append:

```python
def test_light_add_strip_and_panel_need_no_hit(env_rt):
    p, io, h, *_ = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add:strip")
    p.dispatch_event("light-add:panel")
    shapes = [l["shape"] for l in payload(p)["selected"]["lights"]]
    assert shapes == ["strip", "panel"]


def test_strip_fields_edit_through_light_actions(env_rt):
    p, io, h, *_ = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add:strip")
    p.dispatch_event("light:0:edge:bottom")
    p.dispatch_event("light:0:start:0.9")
    p.dispatch_event("light:0:end:0.4")
    light = payload(p)["selected"]["lights"][0]
    assert (light["edge"], light["start"], light["end"]) == ("bottom", 0.4, 0.4)


def test_place_and_aim_do_nothing_to_an_area_light(env_rt):
    p, io, h, *_ = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add:panel")
    before = payload(p)["selected"]["lights"]
    p.dispatch_event("light-place:0")
    p.dispatch_event("light-aim:0")
    light = payload(p)["selected"]["lights"][0]
    assert "position" not in light and "direction" not in light
    assert payload(p)["selected"]["lights"] == before


def test_saved_area_lights_validate(env_rt):
    p, io, h, t, tmp, rt = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add:strip")
    p.dispatch_event("light-add:panel")
    p.dispatch_event("light:1:x1:0.3")
    doc, _matched = rt.pushes[-1]
    ld.validate(json.loads(doc))
```

(`payload`, `click`, `env_rt`, `json`, `ld` are the file's existing helpers / imports; check the top of the file and import `lighting_doc as ld` if it is not there.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_bridge_editing.py tests/unit/test_bridge_emitters_panel.py -q`
Expected: FAIL (`add_area_light` missing; `light-add:strip` does nothing).

- [ ] **Step 3: Implement**

`editing.py`, after `LIGHT_INTENSITY`:

```python
STRIP_INTENSITY = 40.0        # surface brightness (spec §16.1): a thin strip needs a lot
PANEL_INTENSITY = 2.0
STRIP_OFFSET = 1.0            # out from the surface, so a strip on a flat panel lights it
```

After `add_light`:

```python
def add_area_light(doc, block, name, shape):
    """A strip along the top edge, or a panel over the whole front (spec
    §16.4); the rectangle is recomputed from the object at load."""
    o = ld.object_entry(doc, block, name)
    if shape == "strip":
        light = {"shape": "strip", "edge": "top", "start": 0.0, "end": 1.0,
                 "offset": STRIP_OFFSET, "range": LIGHT_RANGE, "intensity": STRIP_INTENSITY}
    elif shape == "panel":
        light = {"shape": "panel", "x": [0.0, 1.0], "y": [0.0, 1.0], "offset": 0.0,
                 "range": LIGHT_RANGE, "intensity": PANEL_INTENSITY}
    else:
        return
    o.setdefault("lights", []).append(light)
```

Replace `set_light`:

```python
def set_light(light, field, raw):
    if field == "edge":
        if raw in ld.EDGES:
            light["edge"] = raw
        return
    v = _num(raw)
    if v is None:
        return
    if field in ("inner_deg", "outer_deg"):
        v = min(90.0, max(0.0, v))
        light[field] = v
        if field == "inner_deg" and light.get("outer_deg", 90.0) < v:
            light["outer_deg"] = v
        elif field == "outer_deg" and v < light.get("inner_deg", 0.0):
            light["inner_deg"] = v
    elif field in ("start", "end"):
        v = min(1.0, max(0.0, v))
        light[field] = v
        if field == "start" and light.get("end", 1.0) < v:
            light["end"] = v
        elif field == "end" and v < light.get("start", 0.0):
            light["start"] = v
    elif field in ("x0", "x1", "y0", "y1"):
        axis, i = field[0], int(field[1])
        span = [float(c) for c in light.get(axis, [0.0, 1.0])]
        span[i] = min(1.0, max(0.0, v))
        if span[0] > span[1]:
            span[1 - i] = span[i]
        light[axis] = span
    elif field == "offset":
        light[field] = v
    elif field == "range":
        light[field] = max(_LIGHT_MIN_RANGE, v)
    elif field == "intensity":
        light[field] = max(0.0, v)
```

`bridge_emitters_panel.py` `_edit_action`: replace the `elif action == "light-add":` branch with:

```python
        elif head == "light-add":
            shape = rest or "spot"
            if shape == "spot":
                if self._last_hit is not None:
                    pos, normal = self._last_hit
                    self._edit(lambda: editing.add_light(self._doc, b, n, pos, normal))
            elif shape in ld.LIGHT_SHAPES:
                self._edit(lambda: editing.add_area_light(self._doc, b, n, shape))
```

In `_light_action`, after `light = lights[i]`:

```python
        if head in ("light-place", "light-aim") and light.get("shape", "spot") != "spot":
            return                     # a strip / panel is placed by its object (spec §16.2)
```

Confirm `"light-add"` reaches `_edit_action` for the `:shape` form: `_EDIT_PREFIXES` already contains `"light"`, which matches by prefix -- verify by reading `dispatch_event`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_bridge_editing.py tests/unit/test_bridge_emitters_panel.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_editor/editing.py engine/ui/bridge_emitters_panel.py \
        tests/unit/test_bridge_editing.py tests/unit/test_bridge_emitters_panel.py
git commit -m "feat(bridge): editor adds and edits strip and panel lights (spec §16.4)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Editor page -- Add Light menu, strip and panel rows

**Files:**
- Modify: `native/assets/ui-cef/js/bridge_emitters.js` (`_beObjectTab`; new helpers beside `_beAddModifier`)
- Test: `tests/ui/test_bridge_emitters_js.py` (append)

**Interfaces:**
- Consumes: panel actions from Task 8 (`light-add:<shape>`, `light:<i>:<field>:<value>`).
- Produces: `_beToggleAddLight()`, `_beAddLightOpen`, `_BE_LIGHTS`; per-shape light rows.

- [ ] **Step 1: Write the failing tests** -- append to `tests/ui/test_bridge_emitters_js.py`:

```python
# ── Lights with size (spec §16.4) ───────────────────────────────────────────

def test_add_light_is_one_menu_button_until_opened():
    closed, opened, again = _run([{"state": _state(selected=_sel())},
                                  {"call": "_beToggleAddLight()"},
                                  {"call": "_beToggleAddLight()"}])
    assert "Add Light" in closed["body"] and "light-add:strip" not in closed["body"]
    body = opened["body"]
    for kind, words in (("spot", "cone"), ("strip", "edge"), ("panel", "front")):
        assert f"light-add:{kind}" in body and words in body
    assert "<select" not in body
    assert "light-add:strip" not in again["body"]


def test_picking_a_light_closes_the_menu():
    _c, opened = _run([{"state": _state(selected=_sel())}, {"call": "_beToggleAddLight()"}])
    i = opened["body"].index("light-add:strip")
    onclick = opened["body"][opened["body"].rindex("onclick=", 0, i):opened["body"].index(">", i)]
    assert "_beAddLightOpen = false" in onclick


def test_a_strip_shows_edge_chips_and_start_end_sliders_not_place_and_aim():
    strip = {"shape": "strip", "edge": "left", "start": 0.2, "end": 0.9, "offset": 1,
             "range": 200, "intensity": 40}
    [out] = _run([{"state": _state(selected=_sel(lights=[strip], expanded=["light:0"]))}])
    body = out["body"]
    assert "Strip" in body
    for e in ("top", "bottom", "left", "right"):
        assert f"light:0:edge:{e}" in body
    assert 'be-chip active"' in body.split("light:0:edge:left")[0].rsplit("<button", 1)[1]
    assert "light:0:start" in body and "light:0:end" in body
    assert "light:0:offset:" in body and "light:0:intensity:" in body
    assert "light-place:0" not in body and "light-aim:0" not in body


def test_a_panel_shows_x_and_y_spans():
    panel = {"shape": "panel", "x": [0, 0.5], "y": [0, 1], "offset": 0, "range": 200,
             "intensity": 2}
    [out] = _run([{"state": _state(selected=_sel(lights=[panel], expanded=["light:0"]))}])
    body = out["body"]
    assert "Panel" in body
    for f in ("x0", "x1", "y0", "y1", "offset", "range", "intensity"):
        assert f"light:0:{f}" in body
    assert "light:0:edge:" not in body


def test_a_spot_entry_is_unchanged():
    spot = {"position": [1, 2, 3], "direction": [0, 0, -1], "inner_deg": 30,
            "outer_deg": 60, "range": 200, "intensity": 2000}
    [out] = _run([{"state": _state(selected=_sel(lights=[spot], expanded=["light:0"]))}])
    assert "light-place:0" in out["body"] and "light:0:inner_deg:" in out["body"]
```

The chip assertion checks the `left` chip carries `active`; if `_beChip`'s markup differs, assert on the substring `be-chip active` immediately preceding `light:0:edge:left` the same way the existing chip tests in this file do.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/ui/test_bridge_emitters_js.py -q`
Expected: FAIL (`_beToggleAddLight` undefined; no strip rows).

- [ ] **Step 3: Implement** in `bridge_emitters.js`.

Below `_beAddModifier` add:

```js
// Add Light (spec §16.4): one menu, like Add Modifier. A spot is placed
// where you clicked; a strip or panel is cut from the object's front.
let _beAddLightOpen = false;

const _BE_LIGHTS = [
    ['spot', 'Spot', 'A cone from a point: placed where you clicked'],
    ['strip', 'Strip', 'A line of light along one edge of the object'],
    ['panel', 'Panel', 'The object\'s front, or part of it, as a soft light']];

function _beToggleAddLight() {
    _beAddLightOpen = !_beAddLightOpen;
    if (_beLast) setBridgeEmitters(_beLast);
}

function _beAddLight() {
    let html = '<div class="be-add"><button class="be-add-button" onclick="_beToggleAddLight()">'
        + 'Add Light ' + (_beAddLightOpen ? '▴' : '▾') + '</button>';
    if (_beAddLightOpen) {
        html += '<div class="be-menu">';
        _BE_LIGHTS.forEach(function (m) {
            html += '<button class="be-menu-item" onclick="_beAddLightOpen = false; '
                + 'dauntlessEvent(\'bridge-emitters/light-add:' + m[0] + '\')">'
                + '<span class="be-menu-name">' + m[1] + '</span>'
                + '<span class="be-menu-help">' + m[2] + '</span></button>';
        });
        html += '</div>';
    }
    return html + '</div>';
}

const _BE_EDGES = [['top', 'Top'], ['bottom', 'Bottom'], ['left', 'Left'], ['right', 'Right']];

function _beLightFields(l, i) {
    const a = 'light:' + i + ':';
    const shape = l.shape || 'spot';
    const tail = _beNumberRow('range', a + 'range', l.range, 0.1)
        + _beNumberRow('intensity', a + 'intensity', l.intensity, shape === 'spot' ? 1 : 0.1);
    if (shape === 'strip') {
        let edges = '<div class="be-row"><label>edge</label><div class="be-list">';
        _BE_EDGES.forEach(function (e) {
            edges += _beChip(e[1], a + 'edge:' + e[0], (l.edge || 'top') === e[0], false);
        });
        return edges + '</div></div>'
            + _beSlider('start', a + 'start', l.start === undefined ? 0 : l.start, 1, 1)
            + _beSlider('end', a + 'end', l.end === undefined ? 1 : l.end, 1, 1)
            + _beNumberRow('offset', a + 'offset', l.offset || 0, 0.1) + tail;
    }
    if (shape === 'panel') {
        const x = l.x || [0, 1], y = l.y || [0, 1];
        return _beSlider('x from', a + 'x0', x[0], 1, 1) + _beSlider('x to', a + 'x1', x[1], 1, 1)
            + _beSlider('y from', a + 'y0', y[0], 1, 1) + _beSlider('y to', a + 'y1', y[1], 1, 1)
            + _beNumberRow('offset', a + 'offset', l.offset || 0, 0.1) + tail;
    }
    return '<div class="be-row">'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/light-place:' + i + '\')">Place here</button>'
        + '<button onclick="dauntlessEvent(\'bridge-emitters/light-aim:' + i + '\')">Aim where I\'m looking</button>'
        + '</div>'
        // HALF-angles from the axis; CEF OSR shows no tooltips, so say so.
        + _beNumberRow('inner half-angle°', a + 'inner_deg', l.inner_deg, 0.1)
        + _beNumberRow('outer half-angle°', a + 'outer_deg', l.outer_deg, 0.1) + tail;
}
```

In `_beObjectTab` replace the lights loop and the Add light row with:

```js
    (s.lights || []).forEach(function (l, i) {
        const shape = l.shape || 'spot';
        const title = 'Light ' + (i + 1)
            + (shape === 'spot' ? '' : ' · ' + shape.charAt(0).toUpperCase() + shape.slice(1));
        html += _beEntry('light:' + i, title, open('light:' + i), null,
                         'light-remove:' + i, _beLightFields(l, i));
    });
    html += _beAddLight();
    return html;
```

`_beSlider` and `_beAddModifier` are defined further down the file than `_beObjectTab`; function declarations hoist, but the `let`/`const` (`_beAddLightOpen`, `_BE_LIGHTS`, `_BE_EDGES`) must be declared before `setBridgeEmitters` first runs -- they are top-level, so they are initialised when the script loads, before any call.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ui/test_bridge_emitters_js.py -q`
Expected: PASS (all old tests too; `test_object_tab_lights_are_indexed_entries` still sees `light-place:1` for spots).

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/js/bridge_emitters.js tests/ui/test_bridge_emitters_js.py
git commit -m "feat(bridge): editor page -- Add Light menu, strip and panel rows (spec §16.4)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Gate, as-built notes

**Files:**
- Modify: `CLAUDE.md` (the "Bridge PBR" row), `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` (§16, an "As built" line)

- [ ] **Step 1: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0 with no new failure or skip. Any failure it names is a regression from this branch: fix it (never add it to `tests/known_failures.txt`).

- [ ] **Step 2: Notes**

In `CLAUDE.md`'s "Bridge PBR" row replace `≤32 spot lights, no shadows, no AO.` with `≤32 lights shared by spots and strip/panel AREA lights (§16: rectangles recomputed from the object's front at load, Heitz diffuse + representative-point GGX, twins in bridge_pbr.h), no shadows, no AO.` In the spec, append to §16:

```markdown
### 16.7 As built

Built on `feat/bridge-area-lights` (plan
`docs/superpowers/plans/2026-10-12-bridge-area-lights.md`). **Not live-verified**
-- Mark's DBridge check (a strip on an alcove lip, a panel on the dome) is owed,
and the defaults (`STRIP_INTENSITY` 40, `PANEL_INTENSITY` 2, `STRIP_OFFSET` 1 in
`engine/bridge_editor/editing.py`) are first guesses to tune there.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md
git commit -m "docs(bridge): area lights as built; live check owed

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Hand over for the live check** -- the live run happens in the MAIN checkout (memory: live-test in the worktree is fine too if Mark asks); give Mark the plain launch command only after asking.
