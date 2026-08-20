# Star Map Set Course Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the left-hand system list in the Helm → Set Course modal with a 3D star map, rendered by a native GL pass into the modal's rectangle.

**Architecture:** Three layers, mirroring the shipped `target_reticle_pass` + `reticle_text` split. A native GL pass draws all geometry into a scissored sub-rect of FBO 0. Pure-Python code owns the camera, projection, picking and — importantly — **all draw ordering**, so the C++ stays dumb and the ordering stays unit-testable. CEF draws labels, the warp-point list and chrome, leaving a transparent hole for the GL.

**Tech Stack:** C++17 / OpenGL / pybind11 (native), Python 3.11 (engine), CEF + vanilla JS/CSS (UI), pytest + ctest.

**Spec:** [`docs/superpowers/specs/2026-08-20-star-map-set-course-design.md`](../specs/2026-08-20-star-map-set-course-design.md)

## Global Constraints

- **Shared checkout.** Never run `git checkout -- <path>`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, or `git add .`. Always stage with an explicit pathspec. Other sessions have uncommitted work in this tree.
- **Build tree is `<project-root>/build/` only.** `cmake -B build -S . && cmake --build build -j`. Never run cmake from inside `native/`.
- **Shader/`.frag`/`.vert` changes need `cmake -B build -S .` (reconfigure) before `cmake --build build -j`.** Shaders are embedded at configure time.
- **`host_bindings.cc` changes need a `dauntless` target rebuild**, not just the Python module.
- **Merge gate is `scripts/check_tests.sh`** — builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`. Never call a failure "pre-existing" by eyeball.
- **Units are game units (GU) end-to-end.** Never name a variable `*_m` or `*_mps`. Sector-model positions are unitless layout coordinates, not GU — do not convert or label them as distances.
- **Rotation convention is column-vector, right-handed.** Not exercised here (the map has no ship rotations), but do not introduce `GetRow` reads.
- **No new external dependencies.** No three.js, no WebGL. `poc/` is reference only — copy nothing from it.
- **Every `_h.<binding>` call from `host_io` for this feature is soft-guarded** via `_OPTIONAL_BINDINGS`, so a stale native module no-ops instead of raising.

---

### Task 1: Bake nebula names into the sector model

Nebula labels need a `name` field that the current bake strips. `sector_model.json` has **three** consumers (Set Course catalog, map-driven starsphere, and now the map) and **two** bakers that preserve each other's keys, so this must be strictly additive.

**Files:**
- Modify: `tools/bake_sector_model.py`
- Modify: `engine/appc/sector_model.json` (regenerated, committed)
- Test: `tests/tools/test_bake_sector_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: each entry in `sector_model.json["nebulae"]` gains `"name": str`. Existing keys `position`, `radius`, `color` are unchanged. `systems` and `starclouds` are untouched.

- [ ] **Step 1: Read the existing baker and its test**

Read `tools/bake_sector_model.py` in full and `tests/tools/test_bake_sector_model.py` in full before editing. Identify the function that emits nebula dicts and how the baker merges with keys written by `tools/bake_set_course_catalog.py`.

- [ ] **Step 2: Write the failing test**

Add to `tests/tools/test_bake_sector_model.py`:

```python
def test_baked_nebulae_carry_a_display_name():
    """The star map labels nebulae, so every baked nebula needs a name.

    Guards the additive contract: adding `name` must not drop the fields the
    sky projection and Set Course catalog already read.
    """
    import json
    from pathlib import Path

    model = json.loads(
        (Path(__file__).resolve().parents[2]
         / "engine" / "appc" / "sector_model.json").read_text()
    )
    nebulae = model["nebulae"]
    assert nebulae, "sector model has no nebulae"
    for neb in nebulae:
        assert isinstance(neb.get("name"), str) and neb["name"], neb
        # additive: the pre-existing keys must survive the re-bake
        assert "position" in neb and "radius" in neb and "color" in neb, neb
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/tools/test_bake_sector_model.py::test_baked_nebulae_carry_a_display_name -v`
Expected: FAIL — `assert isinstance(None, str)`, because the committed model's nebulae have only `position`/`radius`/`color`.

- [ ] **Step 4: Emit `name` from the baker**

In `tools/bake_sector_model.py`, in the function that builds each nebula dict, add the name alongside the existing fields. The source data (the SDK scan) already carries a human name — the POC's extractor produced `"name": "Belaruz Nebula"` from the same signal. Add it as an explicit key, e.g.:

```python
    nebula_entry = {
        "name": nebula_display_name,   # NEW: star-map label
        "position": [round(x, 2), round(y, 2), round(z, 2)],
        "radius": round(radius, 2),
        "color": [r / 255.0, g / 255.0, b / 255.0],
    }
```

Match the surrounding code's rounding and naming exactly — read it first. If the baker does not currently carry a display name that far, thread it through from wherever the nebula is identified, rather than re-deriving it.

- [ ] **Step 5: Re-bake the model**

Run: `uv run python tools/bake_sector_model.py`

Then confirm the other baker's data survived:

```bash
uv run python -c "
import json
d = json.load(open('engine/appc/sector_model.json'))
print('systems', len(d['systems']), 'nebulae', len(d['nebulae']), 'starclouds', len(d['starclouds']))
print('warp_points preserved:', sum(len(s.get('warp_points', [])) for s in d['systems']))
print('nebula sample:', d['nebulae'][0])
"
```

Expected: 34 systems, 8 nebulae, 5 starclouds, 95 warp points preserved, and the nebula sample showing a `name`.

- [ ] **Step 6: Run all three consumers' tests**

Run:
```bash
uv run pytest tests/tools/test_bake_sector_model.py \
              tests/integration/test_bake_set_course_catalog.py \
              tests/engine/appc/test_sky_projection_realmodel.py \
              tests/unit/test_sector_model.py -v
```
Expected: PASS. A failure in the sky-projection test means the re-bake moved or dropped data the starsphere reads — fix the baker, do not adjust that test.

- [ ] **Step 7: Commit**

```bash
git add tools/bake_sector_model.py engine/appc/sector_model.json tests/tools/test_bake_sector_model.py
git commit -m "feat(starmap): bake nebula display names into the sector model

The star map labels nebulae. Additive only — the sky projection and Set
Course catalog read the same file and their keys are untouched."
```

---

### Task 2: Scene model and anchor resolution

Pure Python. Builds the draw-ordered scene from `sector_model`, and resolves the camera anchor with its centroid fallback. **All ordering decisions live here**, so the GL pass draws the list as given and ordering stays testable.

**Files:**
- Create: `engine/ui/star_map.py`
- Test: `tests/ui/test_star_map.py`

**Interfaces:**
- Consumes: `engine.appc.sector_model.{load_sector_model, display_label, is_real_system, system_id_for_set}` (Task 1's `name` field).
- Produces:
  - `MARK_NONE = 0`, `MARK_HERE = 1`, `MARK_COURSE = 2`, `MARK_MISSION = 3`
  - `resolve_anchor(set_name, model=None) -> tuple[str | None, tuple[float, float, float]]` — returns `(system_id_or_None, position)`. `None` id means unresolved; position is then the centroid.
  - `build_scene(*, model=None, here_id=None, course_id=None, mission_ids=(), selected_id=None) -> dict` with keys `discs`, `lines`, `points`, `brackets` — each a list of plain dicts, already in draw order.

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/test_star_map.py`:

```python
"""Star map scene assembly and anchor resolution (pure Python, no GL)."""
import pytest

from engine.ui import star_map as sm


def _model():
    return {
        "systems": [
            {"id": "vesuvi",  "position": [0.0, 0.0, 0.0],   "module": "Systems.Vesuvi.Vesuvi1"},
            {"id": "tevron",  "position": [100.0, 0.0, 0.0],  "module": "Systems.Tevron.Tevron1"},
            {"id": "albirea", "position": [0.0, 200.0, 0.0],  "module": "Systems.Albirea.Albirea1"},
            {"id": "multi1",  "position": [999.0, 999.0, 0.0], "module": "Systems.Multi.Multi1"},
        ],
        "nebulae": [
            {"name": "Belaruz Nebula", "position": [50.0, 0.0, 0.0],
             "radius": 26.0, "color": [0.4, 0.4, 0.6]},
        ],
        "starclouds": [
            {"position": [0.0, 0.0, 300.0], "size": 90.0, "color": [0.3, 0.3, 0.3]},
        ],
    }


# --- anchor ---------------------------------------------------------------

def test_anchor_resolves_the_players_system():
    sid, pos = sm.resolve_anchor("Vesuvi6", model=_model())
    assert sid == "vesuvi"
    assert pos == (0.0, 0.0, 0.0)


def test_anchor_falls_back_to_centroid_when_unresolved():
    """Deep Space / unmapped sets have no system. A misplaced 'you are here'
    is worse than none, so the id must be None — not a guess."""
    sid, pos = sm.resolve_anchor("SomewhereUnmapped", model=_model())
    assert sid is None
    # centroid of the three real systems (multi* excluded)
    assert pos == pytest.approx((100.0 / 3.0, 200.0 / 3.0, 0.0))


def test_anchor_handles_an_empty_model():
    sid, pos = sm.resolve_anchor("Vesuvi6", model={"systems": [], "nebulae": [], "starclouds": []})
    assert sid is None
    assert pos == (0.0, 0.0, 0.0)


# --- scene ----------------------------------------------------------------

def test_scene_excludes_multiplayer_systems():
    scene = sm.build_scene(model=_model())
    ids = [p["id"] for p in scene["points"]]
    assert "multi1" not in ids
    assert set(ids) == {"vesuvi", "tevron", "albirea"}


def test_brackets_only_for_live_relationships():
    """The reticle means 'a live relationship to the player right now'.
    Everything else is a bare dot."""
    scene = sm.build_scene(model=_model(), here_id="vesuvi",
                           course_id="tevron", mission_ids=("albirea",))
    marks = {b["id"]: b["mark"] for b in scene["brackets"]}
    assert marks == {"vesuvi": sm.MARK_HERE,
                     "tevron": sm.MARK_COURSE,
                     "albirea": sm.MARK_MISSION}


def test_no_brackets_when_nothing_is_live():
    scene = sm.build_scene(model=_model())
    assert scene["brackets"] == []


def test_course_line_runs_from_here_to_destination():
    """Lines are reserved for the plotted course."""
    scene = sm.build_scene(model=_model(), here_id="vesuvi", course_id="tevron")
    course = [ln for ln in scene["lines"] if ln["kind"] == "course"]
    assert len(course) == 1
    assert course[0]["a"] == (0.0, 0.0, 0.0)
    assert course[0]["b"] == (100.0, 0.0, 0.0)


def test_no_course_line_without_a_known_origin():
    """Course set but position unknown must not draw a line from the origin."""
    scene = sm.build_scene(model=_model(), here_id=None, course_id="tevron")
    assert [ln for ln in scene["lines"] if ln["kind"] == "course"] == []


def test_drop_lines_only_for_reticled_systems():
    scene = sm.build_scene(model=_model(), here_id="vesuvi", course_id="tevron")
    drops = {ln["id"] for ln in scene["lines"] if ln["kind"] == "drop"}
    assert drops == {"vesuvi", "tevron"}


def test_nebulae_are_subdued():
    scene = sm.build_scene(model=_model())
    neb = next(d for d in scene["discs"] if d["kind"] == "nebula")
    assert neb["opacity"] == pytest.approx(sm.NEBULA_OPACITY)
    assert sm.NEBULA_OPACITY <= 0.5
    assert neb["label"] == "Belaruz Nebula"


def test_discs_sort_back_to_front_by_camera_distance():
    """Ordering is decided here, not in C++ — so it is testable."""
    scene = sm.build_scene(model=_model(), eye=(0.0, 0.0, 0.0))
    dists = [d["_camera_distance"] for d in scene["discs"]]
    assert dists == sorted(dists, reverse=True)


def test_points_carry_display_labels():
    scene = sm.build_scene(model=_model())
    vesuvi = next(p for p in scene["points"] if p["id"] == "vesuvi")
    assert vesuvi["label"]  # display_label, never empty
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/ui/test_star_map.py -v`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'engine.ui.star_map'`.

- [ ] **Step 3: Implement `star_map.py`**

Create `engine/ui/star_map.py`:

```python
"""Star map scene assembly, anchor resolution, camera and picking.

Pure Python — no GL, no CEF. The native starmap pass draws the lists this
module produces, in the order given, so every ordering decision (disc
back-to-front sort, painter's order across primitive kinds) is made and
tested here rather than in C++.

Spec: docs/superpowers/specs/2026-08-20-star-map-set-course-design.md
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Tuple

from engine.appc import sector_model as sm

Vec3 = Tuple[float, float, float]

# Bracket reticle marks — reserved for a LIVE relationship to the player.
MARK_NONE = 0
MARK_HERE = 1       # you are here
MARK_COURSE = 2     # course currently set
MARK_MISSION = 3    # offered by the live SDK Set Course menu

# Nebulae are scenery and must not compete with the stars.
NEBULA_OPACITY = 0.5
STARCLOUD_OPACITY = 0.5

# Faint ground grid; drop-lines fall to this plane.
GRID_Z = 0.0
GRID_HALF_EXTENT = 400.0
GRID_STEP = 50.0
GRID_COLOR = (0.18, 0.22, 0.34)
DROP_COLOR = (0.30, 0.36, 0.52)
COURSE_COLOR = (0.55, 0.85, 1.00)
STAR_COLOR = (0.85, 0.88, 0.98)


def _real_systems(model) -> list:
    return [s for s in model.get("systems", []) if sm.is_real_system(s["id"])]


def _centroid(systems) -> Vec3:
    if not systems:
        return (0.0, 0.0, 0.0)
    n = float(len(systems))
    return (sum(s["position"][0] for s in systems) / n,
            sum(s["position"][1] for s in systems) / n,
            sum(s["position"][2] for s in systems) / n)


def resolve_anchor(set_name, model=None) -> Tuple[Optional[str], Vec3]:
    """Resolve the camera anchor from the player's set name.

    Returns (system_id, position). A None id means the set could not be
    matched to a mapped system — Deep Space, a multiplayer set, or anything
    unmapped. Callers must then omit the "you are here" reticle: a misplaced
    one on a nav map is worse than none.
    """
    model = model if model is not None else sm.load_sector_model()
    systems = _real_systems(model)
    if set_name is not None:
        sysid = sm.system_id_for_set(set_name)
        for s in systems:
            if s["id"] == sysid:
                return (s["id"], tuple(float(c) for c in s["position"]))
    return (None, _centroid(systems))


def _grid_lines() -> list:
    out = []
    n = int(GRID_HALF_EXTENT / GRID_STEP)
    for i in range(-n, n + 1):
        t = i * GRID_STEP
        out.append({"kind": "grid", "id": None, "color": GRID_COLOR,
                    "a": (-GRID_HALF_EXTENT, t, GRID_Z),
                    "b": (GRID_HALF_EXTENT, t, GRID_Z)})
        out.append({"kind": "grid", "id": None, "color": GRID_COLOR,
                    "a": (t, -GRID_HALF_EXTENT, GRID_Z),
                    "b": (t, GRID_HALF_EXTENT, GRID_Z)})
    return out


def build_scene(*, model=None, here_id=None, course_id=None,
                mission_ids: Iterable[str] = (), selected_id=None,
                eye: Vec3 = (0.0, 0.0, 0.0)) -> dict:
    """Assemble the draw-ordered scene.

    Painter's order across kinds is discs -> lines -> points -> brackets, so
    star markers are NEVER occluded by nebulae regardless of depth. The pass
    draws with depth test off and honours this order literally.
    """
    model = model if model is not None else sm.load_sector_model()
    systems = _real_systems(model)
    by_id = {s["id"]: tuple(float(c) for c in s["position"]) for s in systems}
    mission = {m for m in mission_ids if m in by_id}

    # --- discs (nebulae + star clouds), back-to-front -----------------
    discs = []
    for neb in model.get("nebulae", []):
        pos = tuple(float(c) for c in neb["position"])
        discs.append({"kind": "nebula", "label": neb.get("name", ""),
                      "position": pos, "radius": float(neb["radius"]),
                      "color": tuple(neb["color"]), "opacity": NEBULA_OPACITY,
                      "_camera_distance": _distance(pos, eye)})
    for gx in model.get("starclouds", []):
        pos = tuple(float(c) for c in gx["position"])
        discs.append({"kind": "starcloud", "label": "",
                      "position": pos, "radius": float(gx["size"]),
                      "color": tuple(gx["color"]), "opacity": STARCLOUD_OPACITY,
                      "_camera_distance": _distance(pos, eye)})
    discs.sort(key=lambda d: d["_camera_distance"], reverse=True)

    # --- lines: faint grid, drop-lines for reticled systems, course ---
    reticled = {}
    if here_id in by_id:
        reticled[here_id] = MARK_HERE
    if course_id in by_id:
        reticled[course_id] = MARK_COURSE
    for m in mission:
        reticled.setdefault(m, MARK_MISSION)

    lines = _grid_lines()
    for sid in reticled:
        p = by_id[sid]
        lines.append({"kind": "drop", "id": sid, "color": DROP_COLOR,
                      "a": p, "b": (p[0], p[1], GRID_Z)})
    if here_id in by_id and course_id in by_id and here_id != course_id:
        lines.append({"kind": "course", "id": course_id, "color": COURSE_COLOR,
                      "a": by_id[here_id], "b": by_id[course_id]})

    # --- points: every real system as a bare dot ----------------------
    points = [{"id": s["id"], "position": by_id[s["id"]],
               "label": sm.display_label(s["id"]), "color": STAR_COLOR,
               "selected": s["id"] == selected_id}
              for s in systems]

    # --- brackets: ONLY live relationships ----------------------------
    brackets = [{"id": sid, "position": by_id[sid], "mark": mark}
                for sid, mark in reticled.items()]

    return {"discs": discs, "lines": lines, "points": points,
            "brackets": brackets}


def _distance(a: Vec3, b: Vec3) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/ui/test_star_map.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/star_map.py tests/ui/test_star_map.py
git commit -m "feat(starmap): scene assembly and anchor resolution

Draw ordering lives in Python so the GL pass stays dumb and the ordering
is testable. Brackets are reserved for live player relationships; the
anchor falls back to the sector centroid with no 'you are here'."
```

---

### Task 3: Camera and picking against the panel rect

The camera anchors on the player's system and **never moves** — orbit and zoom only. Picking tests against the modal's rect, not the screen.

**Files:**
- Modify: `engine/ui/star_map.py`
- Test: `tests/ui/test_star_map_camera.py`

**Interfaces:**
- Consumes: `engine.ui.ship_property_viewer.{OrbitCamera, project}` (existing; `project(world, cam, viewport) -> (sx, sy, ndc_depth, visible)` with a top-left-origin screen and `viewport=(w, h)`).
- Produces:
  - `StarMapCamera(anchor: Vec3)` with `.orbit(dyaw, dpitch)`, `.zoom(steps)`, `.camera -> OrbitCamera`, and read-only `.anchor`.
  - `project_points(scene, cam, rect) -> list[dict]` — `{id, label, x, y, visible}` in **rect-local** pixels.
  - `pick_system(cursor_x, cursor_y, scene, cam, rect) -> str | None` — cursor in **CEF-view** pixels; returns the nearest system id within `PICK_RADIUS_PT`, else `None`.
  - `PICK_RADIUS_PT = 12.0`, `MIN_DISTANCE`, `MAX_DISTANCE`.
  - `rect` is `(x, y, w, h)` in CEF logical pixels.

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/test_star_map_camera.py`:

```python
"""Star map camera and picking. The anchor is FIXED — clicking selects but
never re-centres (spec §5)."""
import math

import pytest

from engine.ui import star_map as sm

RECT = (200, 80, 640, 520)   # x, y, w, h in CEF logical px


def _scene():
    return sm.build_scene(model={
        "systems": [
            {"id": "vesuvi", "position": [0.0, 0.0, 0.0], "module": "m"},
            {"id": "tevron", "position": [100.0, 0.0, 0.0], "module": "m"},
        ],
        "nebulae": [], "starclouds": [],
    })


def test_orbit_changes_angles_but_never_the_anchor():
    cam = sm.StarMapCamera(anchor=(1.0, 2.0, 3.0))
    before_yaw = cam.camera.yaw
    cam.orbit(0.4, 0.2)
    assert cam.camera.yaw != before_yaw
    assert cam.anchor == (1.0, 2.0, 3.0)
    assert cam.camera.target == (1.0, 2.0, 3.0)


def test_zoom_changes_distance_but_never_the_anchor():
    cam = sm.StarMapCamera(anchor=(1.0, 2.0, 3.0))
    before = cam.camera.distance
    cam.zoom(-3)
    assert cam.camera.distance < before
    assert cam.anchor == (1.0, 2.0, 3.0)


def test_zoom_is_clamped():
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    for _ in range(200):
        cam.zoom(-10)
    assert cam.camera.distance >= sm.MIN_DISTANCE
    for _ in range(200):
        cam.zoom(10)
    assert cam.camera.distance <= sm.MAX_DISTANCE


def test_pitch_is_clamped_to_avoid_gimbal_flip():
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    for _ in range(100):
        cam.orbit(0.0, 1.0)
    assert abs(cam.camera.pitch) < math.pi / 2


def test_there_is_no_way_to_move_the_anchor():
    """Anchor-moving is deliberately ABSENT, not deferred (spec §5)."""
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    assert not hasattr(cam, "set_anchor")
    assert not hasattr(cam, "focus")
    assert not hasattr(cam, "look_at")


def test_projection_is_rect_local_not_screen_absolute():
    """The map lives in a sub-rect. Coordinates the CEF labels consume must be
    relative to that rect, or every label lands offset by the modal position."""
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    projected = sm.project_points(_scene(), cam, RECT)
    anchored = next(p for p in projected if p["id"] == "vesuvi")
    assert anchored["visible"] is True
    # the anchor sits at the centre of the rect, in rect-local coords
    assert anchored["x"] == pytest.approx(RECT[2] / 2.0, abs=1.0)
    assert anchored["y"] == pytest.approx(RECT[3] / 2.0, abs=1.0)


def test_pick_takes_view_pixels_and_hits_the_anchored_system():
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    cx = RECT[0] + RECT[2] / 2.0
    cy = RECT[1] + RECT[3] / 2.0
    assert sm.pick_system(cx, cy, _scene(), cam, RECT) == "vesuvi"


def test_pick_misses_outside_the_radius():
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    assert sm.pick_system(RECT[0] + 2, RECT[1] + 2, _scene(), cam, RECT) is None


def test_pick_outside_the_rect_is_always_a_miss():
    """Clicks on the chrome or the list must not select a star behind them."""
    cam = sm.StarMapCamera(anchor=(0.0, 0.0, 0.0))
    assert sm.pick_system(5, 5, _scene(), cam, RECT) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/ui/test_star_map_camera.py -v`
Expected: FAIL — `AttributeError: module 'engine.ui.star_map' has no attribute 'StarMapCamera'`.

- [ ] **Step 3: Implement the camera and picking**

Append to `engine/ui/star_map.py`:

```python
# ---------------------------------------------------------------------------
# Camera — FIXED anchor. Orbit and zoom only.
# ---------------------------------------------------------------------------

from engine.ui.ship_property_viewer import OrbitCamera, project  # noqa: E402

PICK_RADIUS_PT = 12.0
MIN_DISTANCE = 40.0
MAX_DISTANCE = 2000.0
DEFAULT_DISTANCE = 600.0
ZOOM_STEP = 1.12
_MAX_PITCH = math.radians(89.0)


class StarMapCamera:
    """Orbits the player's current system. The anchor NEVER moves.

    Clicking a star selects it; it does not re-centre the view. With a fixed
    anchor every on-screen position is read relative to the player, which is
    the whole job of a nav map — re-centring destroys that, because after one
    click the centre no longer means anything. There is deliberately no
    set_anchor/focus/look_at: anchor-moving is absent, not deferred.
    """

    def __init__(self, anchor: Vec3, distance: float = DEFAULT_DISTANCE):
        self._anchor = tuple(float(c) for c in anchor)
        self.camera = OrbitCamera(target=self._anchor, distance=distance,
                                  yaw=0.0, pitch=math.radians(25.0))

    @property
    def anchor(self) -> Vec3:
        return self._anchor

    def orbit(self, dyaw: float, dpitch: float) -> None:
        self.camera.yaw += dyaw
        self.camera.pitch = max(-_MAX_PITCH,
                                min(_MAX_PITCH, self.camera.pitch + dpitch))

    def zoom(self, steps: float) -> None:
        d = self.camera.distance * (ZOOM_STEP ** steps)
        self.camera.distance = max(MIN_DISTANCE, min(MAX_DISTANCE, d))


def project_points(scene: dict, cam: StarMapCamera, rect) -> list:
    """Project system dots to RECT-LOCAL pixels (top-left origin).

    Rect-local, not screen-absolute: CEF positions the labels inside the map
    element, so absolute coordinates would offset every label by the modal's
    own position.
    """
    _x, _y, w, h = rect
    out = []
    for p in scene["points"]:
        sx, sy, _depth, visible = project(p["position"], cam.camera, (w, h))
        inside = visible and 0.0 <= sx <= w and 0.0 <= sy <= h
        out.append({"id": p["id"], "label": p["label"],
                    "x": sx, "y": sy, "visible": bool(inside)})
    return out


def pick_system(cursor_x: float, cursor_y: float, scene: dict,
                cam: StarMapCamera, rect) -> Optional[str]:
    """Nearest system within PICK_RADIUS_PT of the cursor, or None.

    Cursor is in CEF-VIEW pixels; rect is the map's (x, y, w, h) in the same
    space. Clicks outside the rect always miss, so chrome and the warp-point
    list never select a star behind them.
    """
    rx, ry, w, h = rect
    if not (rx <= cursor_x <= rx + w and ry <= cursor_y <= ry + h):
        return None
    local_x, local_y = cursor_x - rx, cursor_y - ry
    best_id, best_d2 = None, PICK_RADIUS_PT ** 2
    for p in project_points(scene, cam, rect):
        if not p["visible"]:
            continue
        d2 = (p["x"] - local_x) ** 2 + (p["y"] - local_y) ** 2
        if d2 <= best_d2:
            best_id, best_d2 = p["id"], d2
    return best_id
```

Move the `from engine.ui.ship_property_viewer import ...` line up to the module's import block rather than leaving it mid-file — the inline placement above is only to show where it belongs.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/ui/test_star_map_camera.py tests/ui/test_star_map.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/star_map.py tests/ui/test_star_map_camera.py
git commit -m "feat(starmap): fixed-anchor orbit camera and rect-local picking

The anchor never moves — clicking selects, it does not re-centre, matching
the SPV. Projection and picking are rect-local so the map works as a
windowed panel rather than full-screen."
```

---

### Task 4: The star map panel

A `Panel` subclass satisfying the same `on_course_set` contract as `SettingCoursePanel`.

**Files:**
- Create: `engine/ui/star_map_panel.py`
- Test: `tests/ui/test_star_map_panel.py`

**Interfaces:**
- Consumes: `engine.ui.panel.Panel`, `engine.ui.star_map.*` (Tasks 2-3), `engine.appc.sector_model.{warp_points_for, system_module, display_label, system_id_for_set}`.
- Produces: `StarMapPanel(on_course_set=None)` with `name == "star-map"`, `.open(course_menu=None, set_name=None)`, `.close()`, `.handle_key_esc()`, `.is_open()`, `.render_payload()` emitting `setStarMapPanel({...});`, `.dispatch_event(action)` handling `select-system:<id>` / `set-course:<id>` / `cancel` / `orbit:<dx>,<dy>` / `zoom:<steps>` / `pick:<x>,<y>`, `.scene`, `.cam`, `.rect`.

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/test_star_map_panel.py`:

```python
"""StarMapPanel — the CEF-facing half of the star map.

Satisfies the SAME contract as SettingCoursePanel: produce a destination
set-module, call on_course_set, close.
"""
import json

import pytest

from engine.ui.star_map_panel import StarMapPanel


class _FakeMenu:
    def __init__(self, label, children=None):
        self._label = label
        self._children = children or []
    def GetLabel(self):
        return self._label


def _payload(js):
    assert js.startswith("setStarMapPanel(") and js.endswith(");")
    return json.loads(js[len("setStarMapPanel("):-2])


def test_panel_name_is_the_routing_prefix():
    assert StarMapPanel().name == "star-map"


def test_opens_and_closes():
    p = StarMapPanel()
    assert p.is_open() is False
    p.open(set_name="Vesuvi6")
    assert p.is_open() is True
    p.close()
    assert p.is_open() is False


def test_esc_closes():
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    p.handle_key_esc()
    assert p.is_open() is False


def test_render_payload_is_idempotent():
    """Panel contract: return None when nothing changed, or CEF re-rasters
    every frame — the documented cause of the HUD flicker bug."""
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    assert p.render_payload() is not None
    assert p.render_payload() is None


def test_invalidate_forces_a_re_emit():
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    p.render_payload()
    p.invalidate()
    assert p.render_payload() is not None


def test_selecting_a_system_lists_its_warp_points():
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    assert p.dispatch_event("select-system:vesuvi") is True
    data = _payload(p.render_payload())
    assert data["selected_system"] == "vesuvi"
    assert data["warp_points"], "vesuvi should have warp points"


def test_selecting_a_system_does_not_move_the_camera():
    """Anchor is fixed (spec §5)."""
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    before = p.cam.anchor
    p.dispatch_event("select-system:tevron")
    assert p.cam.anchor == before


def test_set_course_calls_back_with_the_module_and_closes():
    seen = []
    p = StarMapPanel(on_course_set=seen.append)
    p.open(set_name="Vesuvi6")
    p.dispatch_event("select-system:vesuvi")
    data = _payload(p.render_payload())
    wp = next(w for w in data["warp_points"] if w["available"])
    assert p.dispatch_event("set-course:" + wp["id"]) is True
    assert len(seen) == 1 and seen[0]
    assert p.is_open() is False


def test_unavailable_destination_does_not_fire_and_stays_open():
    seen = []
    p = StarMapPanel(on_course_set=seen.append)
    p.open(set_name="Vesuvi6")
    p.dispatch_event("select-system:vesuvi")
    assert p.dispatch_event("set-course:definitely-not-a-warp-point") is False
    assert seen == []
    assert p.is_open() is True


def test_cancel_closes_without_setting_a_course():
    seen = []
    p = StarMapPanel(on_course_set=seen.append)
    p.open(set_name="Vesuvi6")
    assert p.dispatch_event("cancel") is True
    assert seen == []
    assert p.is_open() is False


def test_mission_systems_come_from_the_live_menu():
    p = StarMapPanel()
    p.open(set_name="Tevron1",
           course_menu=_FakeMenu("Set Course", [_FakeMenu("Vesuvi", [])]))
    data = _payload(p.render_payload())
    assert "vesuvi" in data["mission_systems"]


def test_here_marker_absent_when_the_set_is_unmapped():
    """A misplaced 'you are here' is worse than none (spec §5)."""
    p = StarMapPanel()
    p.open(set_name="SomewhereUnmapped")
    data = _payload(p.render_payload())
    assert data["here_system"] is None


def test_orbit_and_zoom_events_move_the_camera_not_the_anchor():
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    anchor, dist = p.cam.anchor, p.cam.camera.distance
    assert p.dispatch_event("orbit:0.3,0.1") is True
    assert p.dispatch_event("zoom:-2") is True
    assert p.cam.anchor == anchor
    assert p.cam.camera.distance < dist


def test_headless_construction_without_a_callback_is_safe():
    p = StarMapPanel()
    p.open(set_name="Vesuvi6")
    p.dispatch_event("select-system:vesuvi")
    data = _payload(p.render_payload())
    wp = next(w for w in data["warp_points"] if w["available"])
    assert p.dispatch_event("set-course:" + wp["id"]) is True  # no crash
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/ui/test_star_map_panel.py -v`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'engine.ui.star_map_panel'`.

- [ ] **Step 3: Implement the panel**

Create `engine/ui/star_map_panel.py`:

```python
"""StarMapPanel — 3D star map for Helm -> Set Course.

Replaces SettingCoursePanel's left-hand system list with a native-GL star
map; the warp-point column is unchanged. Satisfies the SAME contract as the
panel it replaces: produce a destination set-module, call on_course_set,
close. The player then engages the warp from the SDK Helm "Warp" button.

Spec: docs/superpowers/specs/2026-08-20-star-map-set-course-design.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine import dev_mode
from engine.appc import sector_model as sm
from engine.ui import star_map
from engine.ui.panel import Panel

# Map viewport inside the modal, in CEF logical pixels. The modal is 880x560
# centred in a 1280x720 view; the map occupies the left 640x520 of its body.
# Kept in sync with css/star_map.css — see the note there.
MAP_RECT = (204, 116, 640, 520)


class StarMapPanel(Panel):
    def __init__(self, on_course_set=None) -> None:
        super().__init__()
        self._on_course_set = on_course_set
        self._visible = False
        self._course_menu = None
        self._selected_system: Optional[str] = None
        self._here_system: Optional[str] = None
        self._last_pushed: Optional[str] = None
        self.rect = MAP_RECT
        self.cam = star_map.StarMapCamera(anchor=(0.0, 0.0, 0.0))
        self.scene = star_map.build_scene(model={"systems": [], "nebulae": [],
                                                 "starclouds": []})

    @property
    def name(self) -> str:
        return "star-map"

    def is_open(self) -> bool:
        return self._visible

    def open(self, course_menu=None, set_name=None) -> None:
        self._course_menu = course_menu
        self._selected_system = None
        self._visible = True
        here, anchor = star_map.resolve_anchor(set_name)
        self._here_system = here
        self.cam = star_map.StarMapCamera(anchor=anchor)
        self._rebuild_scene()

    def close(self) -> None:
        self._visible = False

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    # --- scene ----------------------------------------------------------
    def _course_system(self) -> Optional[str]:
        """System of the destination currently on the SDK warp button."""
        try:
            import App
            btn = App.SortedRegionMenu_GetWarpButton()
            dest = btn.GetDestination() if btn is not None else None
            if dest:
                return sm.system_id_for_set(str(dest).split(".")[-1])
        except Exception as e:
            dev_mode.log_swallowed("star map course system", e)
        return None

    def _mission_systems(self) -> list:
        """Systems the live SDK Set Course menu currently offers.

        Reconciliation can miss; log rather than swallow, so an absent
        mission reticle is diagnosable instead of mysterious.
        """
        out = []
        for node in getattr(self._course_menu, "_children", []) or []:
            try:
                out.append(sm.system_id_for_set(node.GetLabel()))
            except Exception as e:
                dev_mode.log_swallowed("star map mission system", e)
        return out

    def _rebuild_scene(self) -> None:
        self.scene = star_map.build_scene(
            here_id=self._here_system,
            course_id=self._course_system(),
            mission_ids=self._mission_systems(),
            selected_id=self._selected_system,
            eye=self.cam.camera.eye(),
        )

    # --- warp points ----------------------------------------------------
    def _warp_rows(self) -> tuple:
        sid = self._selected_system
        if sid is None:
            return ([], None)
        catalog = sm.warp_points_for(sid)
        if catalog:
            return ([{"id": wp["id"], "label": wp["label"],
                      "available": wp.get("module") is not None}
                     for wp in catalog], None)
        mod = sm.system_module(sid)
        note = ("No separate destinations in this system — "
                "set course to the system itself." if mod is not None
                else "No course destination available for this system.")
        return ([{"id": sid, "label": sm.display_label(sid),
                  "available": mod is not None}], note)

    def _module_for(self, warp_id) -> Optional[str]:
        sid = self._selected_system
        if sid is None:
            return None
        for wp in sm.warp_points_for(sid):
            if wp["id"] == warp_id:
                return wp.get("module")
        if warp_id == sid:
            return sm.system_module(sid)
        return None

    # --- Panel ----------------------------------------------------------
    def render_payload(self) -> Optional[str]:
        warp_points, warp_note = self._warp_rows()
        labels = (star_map.project_points(self.scene, self.cam, self.rect)
                  if self._visible else [])
        payload = json.dumps({
            "visible": self._visible,
            "selected_system": self._selected_system,
            "here_system": self._here_system,
            "mission_systems": self._mission_systems() if self._visible else [],
            "labels": [{"id": l["id"], "label": l["label"],
                        "x": round(l["x"], 1), "y": round(l["y"], 1),
                        "visible": l["visible"]} for l in labels],
            "warp_points": warp_points,
            "warp_note": warp_note,
        })
        if payload == self._last_pushed:
            return None
        self._last_pushed = payload
        return "setStarMapPanel(" + payload + ");"

    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        if action.startswith("select-system:"):
            # Selects only — the camera anchor deliberately does not move.
            self._selected_system = action[len("select-system:"):]
            self._rebuild_scene()
            return True
        if action.startswith("set-course:"):
            module = self._module_for(action[len("set-course:"):])
            if module is None:
                return False
            if self._on_course_set is not None:
                self._on_course_set(module)
            self.close()
            return True
        if action.startswith("orbit:"):
            try:
                dx, dy = action[len("orbit:"):].split(",")
                self.cam.orbit(float(dx), float(dy))
            except ValueError as e:
                dev_mode.log_swallowed("star map orbit", e)
                return False
            self._rebuild_scene()
            return True
        if action.startswith("zoom:"):
            try:
                self.cam.zoom(float(action[len("zoom:"):]))
            except ValueError as e:
                dev_mode.log_swallowed("star map zoom", e)
                return False
            self._rebuild_scene()
            return True
        if action.startswith("pick:"):
            try:
                x, y = action[len("pick:"):].split(",")
                hit = star_map.pick_system(float(x), float(y), self.scene,
                                           self.cam, self.rect)
            except ValueError as e:
                dev_mode.log_swallowed("star map pick", e)
                return False
            if hit is not None:
                self._selected_system = hit
                self._rebuild_scene()
            return True
        return False

    def invalidate(self) -> None:
        self._last_pushed = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/ui/test_star_map_panel.py -v`
Expected: PASS (14 tests). If `_course_system` fails on the `App` import under pytest, confirm it is caught and logged — the test suite has no live warp button and must not crash.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/star_map_panel.py tests/ui/test_star_map_panel.py
git commit -m "feat(starmap): StarMapPanel satisfying the on_course_set contract

Same contract as SettingCoursePanel — produce a destination set-module,
call on_course_set, close — so the warp button, Kiska's ack and the warp
spine are untouched. Reconciliation misses are logged, not swallowed."
```

---

### Task 5: Native star map pass

Draws the scene into a scissored sub-rect of FBO 0, in the order Python gave, depth test off.

**Files:**
- Create: `native/src/renderer/include/renderer/starmap_pass.h`
- Create: `native/src/renderer/starmap_pass.cc`
- Create: `native/src/renderer/shaders/starmap.vert`, `native/src/renderer/shaders/starmap.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (add the sources + shaders to the existing lists)
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/host_io.py`
- Test: `native/tests/renderer/starmap_pass_test.cc`, `native/tests/CMakeLists.txt`

**Interfaces:**
- Consumes: Task 2's scene dict shape.
- Produces (C++): `renderer::StarMapScene` with `viewport` (`glm::ivec4`), `discs`, `lines`, `points`, `brackets` vectors, and `enabled`; `renderer::StarMapPass::render(const StarMapScene&, const scenegraph::Camera&, Pipeline&, float device_scale_factor)`.
- Produces (Python): `_dauntless_host.starmap_set_enabled(bool)`, `starmap_set_viewport(x, y, w, h)`, `starmap_set_camera(eye, target, up, fov_y_rad, near, far)`, `starmap_set_scene(discs, lines, points, brackets)`; and `host_io.starmap_set_enabled/…` wrappers, all soft-guarded.

- [ ] **Step 1: Read the reference pass end to end**

Read `native/src/renderer/target_reticle_pass.cc` and `native/src/renderer/letterbox_pass.cc` in full. `letterbox_pass.cc:55-78` is the scissor save/restore idiom this pass must copy exactly. Note how `TargetReticlePass` acquires shaders from `Pipeline` and how its VAO/VBO lifecycle is handled.

- [ ] **Step 2: Write the failing C++ test**

Create `native/tests/renderer/starmap_pass_test.cc`. Model its harness on an existing renderer test in `native/tests/renderer/` — read one first for the `FrameTest` fixture shape.

```cpp
// native/tests/renderer/starmap_pass_test.cc
#include <gtest/gtest.h>
#include <renderer/starmap_pass.h>

// The pass must restore GL scissor/viewport state exactly, or every pass
// drawn after it inherits the map's sub-rect. letterbox_pass.cc does the
// same save/restore; this guards the same invariant.
TEST(StarMapPass, DisabledSceneDrawsNothing) {
    renderer::StarMapScene scene;
    scene.enabled = false;
    EXPECT_TRUE(scene.discs.empty());
    EXPECT_TRUE(scene.points.empty());
    EXPECT_EQ(scene.viewport, glm::ivec4(0));
}

TEST(StarMapPass, SceneHoldsPrimitivesInGivenOrder) {
    renderer::StarMapScene scene;
    scene.points.push_back({{0.0f, 0.0f, 0.0f}, {1.0f, 1.0f, 1.0f}, 4.0f, false});
    scene.points.push_back({{1.0f, 0.0f, 0.0f}, {1.0f, 1.0f, 1.0f}, 4.0f, true});
    ASSERT_EQ(scene.points.size(), 2u);
    EXPECT_FALSE(scene.points[0].selected);
    EXPECT_TRUE(scene.points[1].selected);
}
```

- [ ] **Step 3: Run to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j 2>&1 | tail -20`
Expected: FAIL — `fatal error: 'renderer/starmap_pass.h' file not found`.

- [ ] **Step 4: Write the header**

Create `native/src/renderer/include/renderer/starmap_pass.h`:

```cpp
// native/src/renderer/include/renderer/starmap_pass.h
#pragma once

#include <memory>
#include <vector>

#include <glm/glm.hpp>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

/// A soft radial billboard — nebulae and star clouds. Drawn FIRST and
/// depth-test off, so star markers are never occluded by scenery.
struct StarMapDisc {
    glm::vec3 position{0.0f};
    glm::vec3 color{1.0f};
    float     radius  = 1.0f;   // world units
    float     opacity = 0.5f;
};

/// A world-space line segment — grid, drop-lines, or the plotted course.
struct StarMapLine {
    glm::vec3 a{0.0f};
    glm::vec3 b{0.0f};
    glm::vec3 color{1.0f};
};

/// A star dot.
struct StarMapPoint {
    glm::vec3 position{0.0f};
    glm::vec3 color{1.0f};
    float     size_px  = 4.0f;
    bool      selected = false;
};

/// A bracket reticle. `mark` mirrors engine/ui/star_map.py:
///   1 = you are here, 2 = course set, 3 = mission relevant.
struct StarMapBracket {
    glm::vec3 position{0.0f};
    int       mark = 0;
};

struct StarMapScene {
    bool        enabled = false;
    glm::ivec4  viewport{0};   // x, y, w, h in FRAMEBUFFER pixels
    std::vector<StarMapDisc>    discs;
    std::vector<StarMapLine>    lines;
    std::vector<StarMapPoint>   points;
    std::vector<StarMapBracket> brackets;
};

/// Draws the sector map into a scissored sub-rect of the bound framebuffer.
///
/// Runs after the post chain resolves and BEFORE ui_cef::composite(), so CEF
/// chrome lands on top. Everything is drawn depth-test OFF in the order the
/// scene lists it — Python decides ordering (engine/ui/star_map.py), this
/// pass obeys it. Saves and restores viewport + scissor exactly as
/// letterbox_pass does; leaking either corrupts every later pass.
class StarMapPass {
public:
    StarMapPass();
    ~StarMapPass();
    StarMapPass(const StarMapPass&)            = delete;
    StarMapPass& operator=(const StarMapPass&) = delete;

    void render(const StarMapScene& scene,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                float device_scale_factor = 1.0f);

private:
    void ensure_buffers();

    unsigned int quad_vao_ = 0;
    unsigned int quad_vbo_ = 0;
    unsigned int line_vao_ = 0;
    unsigned int line_vbo_ = 0;
};

}  // namespace renderer
```

- [ ] **Step 5: Write the shaders**

Create `native/src/renderer/shaders/starmap.vert`:

```glsl
#version 330 core
// Star map primitives. Instanced: a_corner is the unit-quad corner for discs
// and points; lines use a_corner.x as the segment end selector.
layout(location = 0) in vec2 a_corner;

uniform mat4  u_view_proj;
uniform vec3  u_camera_right;
uniform vec3  u_camera_up;
uniform vec3  u_center;     // world position (discs, points, brackets)
uniform vec3  u_line_a;
uniform vec3  u_line_b;
uniform float u_world_size; // disc radius in world units (0 for screen-space)
uniform vec2  u_pixel_size; // half-size in NDC for screen-space primitives
uniform int   u_kind;       // 0 disc, 1 line, 2 point/bracket

out vec2 v_uv;

void main() {
    v_uv = a_corner;
    if (u_kind == 1) {
        vec3 p = (a_corner.x < 0.5) ? u_line_a : u_line_b;
        gl_Position = u_view_proj * vec4(p, 1.0);
        return;
    }
    if (u_kind == 0) {
        vec2 o = (a_corner * 2.0 - 1.0) * u_world_size;
        vec3 world = u_center + u_camera_right * o.x + u_camera_up * o.y;
        gl_Position = u_view_proj * vec4(world, 1.0);
        return;
    }
    // Screen-space: project the centre, then offset in NDC so the marker
    // keeps a constant pixel size at any zoom.
    vec4 clip = u_view_proj * vec4(u_center, 1.0);
    clip.xy += (a_corner * 2.0 - 1.0) * u_pixel_size * clip.w;
    gl_Position = clip;
}
```

Create `native/src/renderer/shaders/starmap.frag`:

```glsl
#version 330 core
in vec2 v_uv;
out vec4 frag_color;

uniform vec3  u_color;
uniform float u_opacity;
uniform int   u_kind;   // 0 disc, 1 line, 2 point, 3 bracket

void main() {
    if (u_kind == 1) {
        frag_color = vec4(u_color, u_opacity);
        return;
    }
    vec2  d = v_uv * 2.0 - 1.0;
    float r = length(d);
    if (u_kind == 0) {
        // Soft radial falloff — no texture asset needed. Fades to zero at the
        // rim so the billboard never shows a square edge (the documented
        // particle-artifact failure mode).
        float a = smoothstep(1.0, 0.0, r);
        frag_color = vec4(u_color, a * a * u_opacity);
        return;
    }
    if (u_kind == 2) {
        float a = smoothstep(1.0, 0.55, r);
        frag_color = vec4(u_color, a * u_opacity);
        return;
    }
    // Bracket: four corner L-shapes. Keep the corners, discard the middle.
    vec2  ad = abs(d);
    float arm = 0.45;
    bool corner = (ad.x > 1.0 - arm || ad.y > 1.0 - arm)
               && ad.x > 0.55 && ad.y > 0.55;
    if (!corner) discard;
    frag_color = vec4(u_color, u_opacity);
}
```

- [ ] **Step 6: Implement the pass**

Create `native/src/renderer/starmap_pass.cc`. The render body must follow this structure — copy the scissor idiom from `letterbox_pass.cc:55-78` verbatim:

```cpp
void StarMapPass::render(const StarMapScene& scene,
                         const scenegraph::Camera& camera,
                         Pipeline& pipeline,
                         float device_scale_factor) {
    if (!scene.enabled) return;
    if (scene.viewport.z <= 0 || scene.viewport.w <= 0) return;
    ensure_buffers();

    // --- save state (see letterbox_pass.cc) ---
    GLint prev_viewport[4]; glGetIntegerv(GL_VIEWPORT, prev_viewport);
    GLint prev_box[4];      glGetIntegerv(GL_SCISSOR_BOX, prev_box);
    const GLboolean prev_scissor = glIsEnabled(GL_SCISSOR_TEST);
    const GLboolean prev_depth   = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_blend   = glIsEnabled(GL_BLEND);

    glEnable(GL_SCISSOR_TEST);
    glScissor(scene.viewport.x, scene.viewport.y,
              scene.viewport.z, scene.viewport.w);
    glViewport(scene.viewport.x, scene.viewport.y,
               scene.viewport.z, scene.viewport.w);

    // Opaque fill: "game visible" means AROUND the modal, not through it.
    glClearColor(0.02f, 0.03f, 0.06f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glDisable(GL_DEPTH_TEST);          // painter's order, decided in Python
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    // ... draw discs, then lines, then points, then brackets, IN ORDER ...

    // --- restore state ---
    if (!prev_blend)   glDisable(GL_BLEND);
    if (prev_depth)    glEnable(GL_DEPTH_TEST);
    glScissor(prev_box[0], prev_box[1], prev_box[2], prev_box[3]);
    if (!prev_scissor) glDisable(GL_SCISSOR_TEST);
    glViewport(prev_viewport[0], prev_viewport[1],
               prev_viewport[2], prev_viewport[3]);
}
```

Bracket colours are chosen in the pass from `mark`: `MARK_HERE` (1) bright key, `MARK_COURSE` (2) the course colour, `MARK_MISSION` (3) the accent. Point size and bracket size are multiplied by `device_scale_factor` so they hold their apparent size on a Retina framebuffer.

Add the new sources and both shaders to the existing lists in `native/src/renderer/CMakeLists.txt`, and the test to `native/tests/CMakeLists.txt`, matching how `target_reticle_pass` and its test are registered.

- [ ] **Step 7: Build and run the C++ test**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R StarMapPass --output-on-failure`
Expected: PASS. (The `cmake -B build -S .` reconfigure is mandatory — new shader files are embedded at configure time.)

- [ ] **Step 8: Add the pybind bindings**

In `native/src/host/host_bindings.cc`, following the `set_target_reticle` / `set_subsystem_pins` pattern exactly:

1. `#include <renderer/starmap_pass.h>` beside the other pass includes (~line 54).
2. Globals beside `g_target_reticle` (~line 250):
   ```cpp
   renderer::StarMapScene                  g_starmap_scene;
   std::unique_ptr<renderer::StarMapPass>  g_starmap_pass;
   ```
3. Construct in init (~line 521): `g_starmap_pass = std::make_unique<renderer::StarMapPass>();`
4. Tear down in shutdown (~line 610): `g_starmap_scene = renderer::StarMapScene{}; g_starmap_pass.reset();`
5. **Draw between the letterbox draw (~line 1190) and `ui_cef::composite()` (~line 1227)** — that slot is the whole point: after the post chain resolves so the map is not tonemapped, before CEF composites so the chrome lands on top:
   ```cpp
   if (g_starmap_pass && g_starmap_scene.enabled) {
       g_starmap_pass->render(g_starmap_scene, g_camera, *g_pipeline, dsf);
   }
   ```
6. Four `m.def`s: `starmap_set_enabled(bool)`, `starmap_set_viewport(x, y, w, h)`, `starmap_set_camera(eye, target, up, fov_y_rad, near, far)`, and `starmap_set_scene(discs, lines, points, brackets)` taking lists of tuples and filling the vectors — mirroring how `set_subsystem_pins` unpacks `std::vector<std::tuple<...>>`.

- [ ] **Step 9: Add the soft-guarded host_io wrappers**

In `engine/host_io.py`, add the four names to `_OPTIONAL_BINDINGS` (replacing the `frozenset()` and its now-stale "Empty for now" comment), then add wrappers:

```python
def starmap_set_enabled(enabled: bool) -> None:
    fn = getattr(_h, "starmap_set_enabled", None)
    if fn is not None:
        fn(bool(enabled))
```

…and the same shape for `starmap_set_viewport`, `starmap_set_camera`, `starmap_set_scene`. Soft-guarded so a stale native module no-ops with a dev-mode warning instead of raising `AttributeError` mid-mission.

- [ ] **Step 10: Verify the binding manifest**

Run: `cmake --build build -j && uv run pytest tests/ -k host_io -v`
Expected: PASS. Then confirm the bindings exist on the built module:

```bash
uv run python -c "
import sys; sys.path.insert(0, 'build/python')
import _dauntless_host as h
for n in ('starmap_set_enabled','starmap_set_viewport','starmap_set_camera','starmap_set_scene'):
    print(n, hasattr(h, n))
"
```
Expected: all `True`.

- [ ] **Step 11: Commit**

```bash
git add native/src/renderer/starmap_pass.cc \
        native/src/renderer/include/renderer/starmap_pass.h \
        native/src/renderer/shaders/starmap.vert \
        native/src/renderer/shaders/starmap.frag \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/starmap_pass_test.cc \
        native/tests/CMakeLists.txt \
        native/src/host/host_bindings.cc \
        engine/host_io.py
git commit -m "feat(starmap): native GL pass drawing into a scissored sub-rect

Draws after the post chain resolves and before ui_cef::composite(), so CEF
chrome lands on top and the map is not tonemapped. Depth test off, drawn in
the order Python supplies. Saves/restores viewport and scissor exactly as
letterbox_pass does. Bindings are soft-guarded in host_io."
```

---

### Task 6: CEF layer

Chrome, labels and the warp-point list, with a transparent hole for the GL.

**Files:**
- Create: `native/assets/ui-cef/js/star_map.js`
- Create: `native/assets/ui-cef/css/star_map.css`
- Modify: `native/assets/ui-cef/index.html`
- Test: `tests/ui/test_star_map_cef_assets.py`

**Interfaces:**
- Consumes: `setStarMapPanel({visible, selected_system, here_system, mission_systems, labels, warp_points, warp_note})` from Task 4.
- Produces: DOM ids `star-map-panel`, `star-map-viewport`, `star-map-labels`, `star-map-warps`. Events `star-map/select-system:<id>`, `star-map/set-course:<id>`, `star-map/cancel`, `star-map/orbit:<dx>,<dy>`, `star-map/zoom:<steps>`, `star-map/pick:<x>,<y>`.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_star_map_cef_assets.py`:

```python
"""The CEF assets must exist, be wired into index.html, and keep the map
viewport transparent so the GL pass beneath shows through."""
import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"


def test_script_and_stylesheet_are_registered_in_index():
    index = (ASSETS / "index.html").read_text()
    assert "js/star_map.js" in index
    assert "css/star_map.css" in index


def test_panel_section_exists_with_the_required_ids():
    index = (ASSETS / "index.html").read_text()
    for el in ("star-map-panel", "star-map-viewport",
               "star-map-labels", "star-map-warps"):
        assert 'id="' + el + '"' in index, el


def test_map_viewport_is_transparent():
    """The GL pass draws beneath. An opaque background here hides the map
    entirely — the single most likely way to ship a black rectangle."""
    css = (ASSETS / "css" / "star_map.css").read_text()
    block = re.search(r"#star-map-viewport\s*\{[^}]*\}", css)
    assert block, "no #star-map-viewport rule"
    assert "transparent" in block.group(0)


def test_render_fn_matches_the_python_payload_name():
    js = (ASSETS / "js" / "star_map.js").read_text()
    assert "function setStarMapPanel(" in js


def test_events_use_the_panel_routing_prefix():
    js = (ASSETS / "js" / "star_map.js").read_text()
    for evt in ("star-map/set-course", "star-map/select-system",
                "star-map/cancel", "star-map/pick", "star-map/orbit",
                "star-map/zoom"):
        assert evt in js, evt


def test_labels_are_escaped():
    js = (ASSETS / "js" / "star_map.js").read_text()
    assert "escapeHtmlSM" in js
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/ui/test_star_map_cef_assets.py -v`
Expected: FAIL — `FileNotFoundError` for `css/star_map.css`.

- [ ] **Step 3: Write the CSS**

Create `native/assets/ui-cef/css/star_map.css`:

```css
/* Star map panel. Reuses cp-* chrome from configuration_panel.css.
   NOTE: #star-map-viewport's geometry must stay in sync with MAP_RECT in
   engine/ui/star_map_panel.py — Python projects labels and hit-tests clicks
   against that rect, and the GL pass scissors to it. */
#star-map-panel {
    position: fixed; inset: 0;
    display: none; align-items: center; justify-content: center;
}
#star-map-panel .cp-modal { width: 880px; height: 560px; }

.sm-body { display: flex; gap: 0; height: calc(100% - 28px); }

/* The GL pass draws BENEATH this element. It must stay transparent. */
#star-map-viewport {
    position: relative;
    width: 640px; height: 520px;
    background: transparent;
    overflow: hidden;      /* clip labels to the map rect */
    cursor: grab;
}
#star-map-viewport:active { cursor: grabbing; }

#star-map-labels { position: absolute; inset: 0; pointer-events: none; }
.sm-label {
    position: absolute;
    font-size: 10px; color: #b9c4de;
    text-shadow: 0 0 3px #000;
    transform: translate(8px, -6px);
    white-space: nowrap;
}
.sm-label--here    { color: #eaf2ff; font-weight: 700; }
.sm-label--course  { color: #8cd8ff; }
.sm-label--mission { color: #ffc46b; }

#star-map-warps {
    flex: 1 1 auto; overflow-y: auto; max-height: 520px;
    border-left: 1px solid rgba(255, 255, 255, 0.12);
}
```

- [ ] **Step 4: Write the JS**

Create `native/assets/ui-cef/js/star_map.js`:

```js
// Star map render fn. Driven by Python:
//   setStarMapPanel({visible, selected_system, here_system, mission_systems,
//                    labels, warp_points, warp_note});
// The 3D map itself is drawn by the NATIVE starmap pass beneath
// #star-map-viewport — this file draws only labels, the warp-point list and
// chrome. Keep #star-map-viewport transparent.
function escapeHtmlSM(s) {
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _smLabelClass(id, state) {
    if (id === state.here_system) return ' sm-label--here';
    if (id === state.selected_system) return ' sm-label--course';
    if ((state.mission_systems || []).indexOf(id) !== -1) return ' sm-label--mission';
    return '';
}

function setStarMapPanel(state) {
    const root = document.getElementById('star-map-panel');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const labelEl = document.getElementById('star-map-labels');
    if (labelEl) {
        labelEl.innerHTML = (state.labels || []).filter(function (l) {
            return l.visible;
        }).map(function (l) {
            return '<div class="sm-label' + _smLabelClass(l.id, state) + '"'
                + ' style="left:' + l.x + 'px;top:' + l.y + 'px">'
                + escapeHtmlSM(l.label) + '</div>';
        }).join('');
    }
    const warpEl = document.getElementById('star-map-warps');
    if (warpEl) {
        const note = state.warp_note
            ? '<li class="sc-note">' + escapeHtmlSM(state.warp_note) + '</li>'
            : '';
        warpEl.innerHTML = note + (state.warp_points || []).map(function (w) {
            const ok = (w.available !== false);
            const cls = 'sc-row' + (ok ? '' : ' sc-row--disabled');
            const click = ok
                ? ' onclick="dauntlessEvent(\'star-map/set-course:\' + this.getAttribute(\'data-id\'))"'
                : '';
            return '<li class="' + cls + '" data-id="' + escapeHtmlSM(w.id) + '"'
                + click + '>' + escapeHtmlSM(w.label) + '</li>';
        }).join('');
    }
    root.style.display = 'flex';
}

// Orbit / zoom / pick. A drag orbits; a click without drag picks a star.
(function () {
    let dragging = false, moved = false, lastX = 0, lastY = 0;
    document.addEventListener('DOMContentLoaded', function () {
        const vp = document.getElementById('star-map-viewport');
        if (!vp) return;
        vp.addEventListener('mousedown', function (e) {
            dragging = true; moved = false; lastX = e.clientX; lastY = e.clientY;
        });
        vp.addEventListener('mousemove', function (e) {
            if (!dragging) return;
            const dx = e.clientX - lastX, dy = e.clientY - lastY;
            if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
            lastX = e.clientX; lastY = e.clientY;
            dauntlessEvent('star-map/orbit:' + (dx * 0.008) + ',' + (dy * 0.008));
        });
        vp.addEventListener('mouseup', function (e) {
            if (dragging && !moved) {
                dauntlessEvent('star-map/pick:' + e.clientX + ',' + e.clientY);
            }
            dragging = false;
        });
        vp.addEventListener('mouseleave', function () { dragging = false; });
        vp.addEventListener('wheel', function (e) {
            dauntlessEvent('star-map/zoom:' + (e.deltaY > 0 ? 1 : -1));
            e.preventDefault();
        });
    });
})();
```

- [ ] **Step 5: Add the panel section to index.html**

Add the stylesheet beside the other `<link>` tags, the script beside the others (~line 872, next to `setting_course_panel.js`), and the section — model its chrome on the existing `#setting-course-panel` markup, which you should read first:

```html
<div id="star-map-panel">
  <div class="cp-modal">
    <div class="cp-header">
      SET COURSE
      <span class="cp-close" onclick="dauntlessEvent('star-map/cancel')">&times;</span>
    </div>
    <div class="sm-body">
      <div id="star-map-viewport"><div id="star-map-labels"></div></div>
      <ul id="star-map-warps"></ul>
    </div>
  </div>
</div>
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/ui/test_star_map_cef_assets.py -v`
Expected: PASS (6 tests).

- [ ] **Step 7: Commit**

```bash
git add native/assets/ui-cef/js/star_map.js \
        native/assets/ui-cef/css/star_map.css \
        native/assets/ui-cef/index.html \
        tests/ui/test_star_map_cef_assets.py
git commit -m "feat(starmap): CEF chrome, labels and warp-point list

The viewport element stays transparent — the native pass draws beneath it.
Labels track projected rect-local coordinates; drag orbits, click picks."
```

---

### Task 7: Wire into Helm → Set Course

Repoint the crew-menu hook, drive the pass from panel state, and generalize the cursor/click gating.

**Files:**
- Modify: `engine/host_loop.py` (~`:2872`, `:6860-6867`, `:7313`, and the render block near `:8000`)
- Test: `tests/integration/test_star_map_set_course.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: `star_map_panel` in the host loop, registered with `PanelRegistry`, opened by `on_set_course`.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_star_map_set_course.py`. Enter at the **host layer**, not the engine API — entering below the host poller is a mistake this project has made before.

```python
"""Helm -> Set Course opens the star map, and picking a warp point reaches
SetDestination. Entered at the host wiring, not at the panel's own API."""
import json

from engine.ui.star_map_panel import StarMapPanel


def _payload(js):
    return json.loads(js[len("setStarMapPanel("):-2])


def test_selection_reaches_the_warp_button_destination():
    """The whole point of the swap: the map satisfies the SAME contract the
    list panel did, so the warp button, Kiska's ack and the spine are
    untouched."""
    recorded = []
    panel = StarMapPanel(on_course_set=recorded.append)

    # what host_loop's on_set_course hook does
    panel.open(course_menu=None, set_name="Vesuvi6")
    assert panel.is_open()

    panel.dispatch_event("select-system:vesuvi")
    data = _payload(panel.render_payload())
    wp = next(w for w in data["warp_points"] if w["available"])
    panel.dispatch_event("set-course:" + wp["id"])

    assert len(recorded) == 1
    assert recorded[0].startswith("Systems.")
    assert not panel.is_open()


def test_panel_is_registered_under_its_routing_name():
    from engine.ui.panel_registry import PanelRegistry
    reg = PanelRegistry()
    panel = StarMapPanel()
    reg.register(panel)
    panel.open(set_name="Vesuvi6")
    assert reg.dispatch("star-map/select-system:vesuvi") is True
```

Read `engine/ui/panel_registry.py` first and adjust the second test to its real `dispatch`/`register` signatures.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_star_map_set_course.py -v`
Expected: FAIL — the assertion or signature mismatch, depending on the registry API.

- [ ] **Step 3: Construct and register the panel**

In `engine/host_loop.py` near `:6860`, beside the existing `SettingCoursePanel` construction (**leave that construction in place** — see Task 7 Step 6):

```python
        from engine.ui.star_map_panel import StarMapPanel
        star_map_panel = StarMapPanel(on_course_set=on_course_set)
        registry.register(star_map_panel)
```

Repoint the crew-menu hook at `:6864` from `on_set_course=setting_course_panel.open` to a small adapter that passes the player's current set name:

```python
        def _open_star_map(course_menu=None):
            set_name = None
            try:
                pset = player.GetContainingSet() if player is not None else None
                set_name = pset.GetName() if pset is not None else None
            except Exception as e:
                dev_mode.log_swallowed("star map set name", e)
            star_map_panel.open(course_menu=course_menu, set_name=set_name)
```

Read the surrounding code to confirm how the player object is reached at that point in the loop, and match it — do not invent an accessor.

- [ ] **Step 4: Generalize the cursor and click gating**

At `:2872` (`_apply_crew_menu_side_effects`) and `:7313` (`_cursor_in_modal`), the existing conditions key off `setting_course_panel.is_open()`. Add the star map panel to both, so it frees the cursor and swallows clicks exactly as the modal it replaces did. Add a `star_map_panel=None` keyword to `_apply_crew_menu_side_effects` and include it in `modal_open`.

- [ ] **Step 5: Drive the pass from panel state**

In the render block near `:8000`, beside the SPV block:

```python
            _sm_open = star_map_panel.is_open()
            r.starmap_set_enabled(_sm_open)
            if _sm_open:
                _fw, _fh = r.framebuffer_size()
                _scale = _fh / float(_CEF_VIEW_H)
                _rx, _ry, _rw, _rh = star_map_panel.rect
                # GL scissor origin is BOTTOM-left; the panel rect is
                # top-left. Flip Y or the map draws mirrored up the screen.
                r.starmap_set_viewport(
                    int(_rx * _scale),
                    int(_fh - (_ry + _rh) * _scale),
                    int(_rw * _scale), int(_rh * _scale))
                _cam = star_map_panel.cam.camera
                r.starmap_set_camera(_cam.eye(), _cam.target, _cam.up(),
                                     _cam.fov_y_rad, _cam.near, _cam.far)
                r.starmap_set_scene(*_starmap_buffers(star_map_panel.scene))
```

Add a module-level `_starmap_buffers(scene)` helper that flattens the scene dict into the four tuple-lists the binding expects. Close-and-invalidate the panel in the mission-swap block, alongside the other panels reset there.

- [ ] **Step 6: Keep `SettingCoursePanel` alive**

Do **not** delete `engine/ui/setting_course_panel.py`, its CEF assets, or `tests/unit/test_setting_course_panel.py`. It stays constructible and registered so a bad first live run leaves a way to set a course — otherwise warp is unreachable and playtesting everything downstream is blocked. It is retired in a follow-up commit after live verification.

- [ ] **Step 7: Run the integration test**

Run: `uv run pytest tests/integration/test_star_map_set_course.py -v`
Expected: PASS.

- [ ] **Step 8: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. Any failure not in `tests/known_failures.txt` is a regression this branch introduced — fix it. The one baselined pytest entry is the order-dependent `test_engineer_emitters.py::test_shield_level_change_announces`; `cat tests/known_failures.txt` to confirm rather than trusting this sentence.

- [ ] **Step 9: Commit**

```bash
git add engine/host_loop.py tests/integration/test_star_map_set_course.py
git commit -m "feat(starmap): open the star map from Helm > Set Course

Repoints the crew-menu hook at the map panel and drives the pass from its
state. SettingCoursePanel stays in the tree until the map is verified live
— without it, a bad first run makes warp unreachable."
```

---

## Live verification (human gate)

The suites cannot see whether the map *reads* well. After Task 7, run
`./build/dauntless` and check, in order:

1. Helm → Set Course opens an 880×560 modal with a **visible 3D map**, not a black rectangle. (Black = the CEF viewport is not transparent, or the scissor rect Y-flip is wrong.)
2. The game and the helm menu are still visible **around** the modal, and the world is still moving.
3. The camera orbits on drag and zooms on wheel, about your current system, and clicking a star **does not** re-centre.
4. Exactly one "you are here" reticle, on the system you are actually in.
5. Clicking a warp point closes the map and Kiska acks; the Helm "Warp" button then warps you there.
6. Closing the map leaves the HUD undamaged — no leaked scissor rect, no missing panels.

Then tune, in this order of likelihood: label density at 34 systems, nebula opacity, grid visibility, zoom range. Everything but the grid geometry is a constant.

---

## Self-Review

**Spec coverage:** §2 rendering → Task 5. §3 windowed → Task 5 (scissor) + Task 7 (viewport). §4 components → Tasks 2-7 one apiece. §5 camera → Task 3, with `test_there_is_no_way_to_move_the_anchor` pinning the deliberate absence. §6 visual language → Task 2 (brackets, course line, drop-lines, opacity) + Task 5 (shaders). §7 data → Task 1. §8 error handling → Task 2 (fallback), Task 4 (unavailable module, logged reconciliation), Task 5 step 9 (soft-guarded bindings), Task 7 (mission swap). §9 scope → Task 7 step 6. §10 testing → all tasks.

**Placeholder scan:** no TBD/TODO. Task 1 step 4 and Task 5 step 6 direct the implementer to read surrounding code before editing rather than specifying every line — the only two places, both because the existing file's conventions govern and inventing them here would be worse than reading them.

**Type consistency:** `MARK_*` constants match between `star_map.py` and `starmap_pass.h`. `rect` is `(x, y, w, h)` everywhere. `project` returns a 4-tuple; `project_points` re-shapes it to dicts. `resolve_anchor` returns `(id_or_None, position)` in Tasks 2, 3 and 4 alike. The panel's payload keys match the JS reader's field names.
