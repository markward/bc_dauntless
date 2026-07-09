# ViewscreenZoomTarget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zoom the bridge viewscreen onto a target ship (BC's `ViewscreenZoomTarget`), driven by `MissionLib.ViewscreenWatchObject` and by holding `Z` in bridge view, while the bridge stays visible.

**Architecture:** The forward viewscreen feed already renders the live exterior scene into the RTT via `render_space(cam, for_viewscreen=true)` using the fixed forward `g_camera`. We add a native `SceneSource` (mirroring the existing `CommSource`) so an *arbitrary* camera can drive that same branch, then compute that camera in Python from the player camera's `ViewscreenZoomTarget` mode. Precedence in the RTT is comm hail → VZT scene → forward. No shader change → `dauntless` rebuild only, no cmake reconfigure.

**Tech Stack:** C++/pybind11 (`native/src/host/host_bindings.cc`), Python engine (`engine/`), pytest + ctest gate (`scripts/check_tests.sh`).

## Global Constraints

- Game units throughout; column-vector right-handed rotations (CLAUDE.md). Never name a spatial var `*_m`/`*_mps`.
- Never write `bridge_flag()` / `GetRenderedSet()`. The viewscreen source is derived from SDK/input state each frame (pull-model).
- Production render path must be **byte-identical** when no VZT is active (`g_scene_source.active == false` → the forward `else` branch is the exact current code; resolver returns `None` → `clear_viewscreen_scene_source()`).
- `host_bindings.cc` edits need a `dauntless` rebuild (`cmake --build build -j`); a module-only rebuild leaves `./build/dauntless` stale (memory `host_bindings_build_target`). No shader change here, so **no** `cmake -B build -S .` reconfigure needed.
- One build tree only: `build/`. Binary `build/dauntless`, module `build/python/_open_stbc_host.cpython-*.so`. Never spawn a binary at another path.
- Shared git checkout with concurrent sessions: work on a feature branch, commit with **explicit pathspec** (never `git add -A`), verify committed files survive later merges (memory `shared_checkout_hazards`).
- Gate: `scripts/check_tests.sh` (builds C++ + pytest + ctest, diffs against `tests/known_failures.txt`). Green before merge; the only allowed baselined failures are the 7 headless-GL `FrameTest`s.

**Branch setup (do once before Task 1):**

```bash
git checkout -b feat/viewscreen-zoom-target
```

Reference the spec throughout: `docs/superpowers/specs/2026-07-09-viewscreen-zoom-target-design.md`.

---

## File Structure

- `native/src/host/host_bindings.cc` — add `SceneSource` struct + `set_viewscreen_scene_source`/`clear_viewscreen_scene_source` bindings + the `else if (g_scene_source.active)` branch in `frame()`. (Task 1)
- `engine/renderer.py` — add two wrapper functions + two `_REQUIRED_BINDINGS` entries. (Task 2)
- `engine/core/game.py` — add `Game.GetPlayerCamera()` + `_player_camera` field. (Task 3)
- `engine/appc/bridge_set.py` — `CameraObjectClass`: init `_vs_active=False`, add `"ViewscreenZoomTarget"` to `_MODE_FACTORY`, make `AddModeHierarchy` the engagement seam. (Task 4)
- `engine/host_loop.py` — `_adaptive_vs_fov` + `VS_*` constants (Task 5); `_viewscreen_scene_feed` resolver (Task 6); wire the resolver + `Z`-held read into the feed-selection block (Task 7).
- `engine/dev_viewscreen_probe.py` (new) — dev-only pause-menu probe firing `ViewscreenWatchObject` (Task 8).
- Tests under `tests/unit/` and `tests/host/`.

---

### Task 1: Native scene-source RTT capability

**Files:**
- Modify: `native/src/host/host_bindings.cc` (struct near :268; bindings near :1716; `frame()` branch :811-816)

**Interfaces:**
- Produces (pybind, on `_open_stbc_host`):
  - `set_viewscreen_scene_source(eye, target, up, fov_y_rad, near, far)` — tuples `(float,float,float)` for eye/target/up; floats for the rest. Sets `g_scene_source.active = true` + camera.
  - `clear_viewscreen_scene_source()` — sets `g_scene_source.active = false`.
- Behaviour: in `frame()`, the viewscreen-RTT non-comm path uses `g_scene_source.cam` when active, else `g_camera` (unchanged). Comm still wins over scene.

- [ ] **Step 1: Add the `SceneSource` struct.** After the `CommSource g_comm_source;` line (currently `native/src/host/host_bindings.cc:268`), insert:

```cpp
// Active scene source: when set (and no comm source is active), frame() renders
// the main exterior scene from this camera into the viewscreen RTT instead of
// the fixed forward g_camera feed. Drives ViewscreenZoomTarget (host_loop
// _viewscreen_scene_feed). active == false → byte-identical forward feed.
struct SceneSource { bool active = false; scenegraph::Camera cam; };
SceneSource g_scene_source;
```

- [ ] **Step 2: Add the three-way branch in `frame()`.** Replace the current non-comm `else` (currently `native/src/host/host_bindings.cc:811-816`):

```cpp
        } else {
            scenegraph::Camera vcam = g_camera;
            vcam.aspect = static_cast<float>(kViewscreenRttW)
                        / static_cast<float>(kViewscreenRttH);
            render_space(vcam, /*for_viewscreen=*/true);
        }
```

with:

```cpp
        } else if (g_scene_source.active) {
            scenegraph::Camera scam = g_scene_source.cam;
            scam.aspect = static_cast<float>(kViewscreenRttW)
                        / static_cast<float>(kViewscreenRttH);
            render_space(scam, /*for_viewscreen=*/true);
        } else {
            scenegraph::Camera vcam = g_camera;
            vcam.aspect = static_cast<float>(kViewscreenRttW)
                        / static_cast<float>(kViewscreenRttH);
            render_space(vcam, /*for_viewscreen=*/true);
        }
```

- [ ] **Step 3: Add the two bindings.** After the `clear_viewscreen_comm_source` binding (currently ends `native/src/host/host_bindings.cc:1716`), insert:

```cpp
    m.def("set_viewscreen_scene_source",
          [](std::tuple<float,float,float> eye,
             std::tuple<float,float,float> target,
             std::tuple<float,float,float> up,
             float fov_y_rad, float near, float far) {
              g_scene_source.active = true;
              g_scene_source.cam.eye    = {std::get<0>(eye),    std::get<1>(eye),    std::get<2>(eye)};
              g_scene_source.cam.target = {std::get<0>(target), std::get<1>(target), std::get<2>(target)};
              g_scene_source.cam.up     = {std::get<0>(up),     std::get<1>(up),     std::get<2>(up)};
              g_scene_source.cam.fov_y_rad = fov_y_rad;
              g_scene_source.cam.near = near;
              g_scene_source.cam.far  = far;
          },
          py::arg("eye"), py::arg("target"), py::arg("up"),
          py::arg("fov_y_rad"), py::arg("near"), py::arg("far"));
    m.def("clear_viewscreen_scene_source",
          []() { g_scene_source.active = false; });
```

- [ ] **Step 4: Build and verify the bindings exist.**

Run:
```bash
cmake --build build -j
PYTHONPATH=build/python python -c "import _open_stbc_host as m; assert hasattr(m,'set_viewscreen_scene_source') and hasattr(m,'clear_viewscreen_scene_source'); print('OK')"
```
Expected: build succeeds; prints `OK`.

- [ ] **Step 5: Commit.**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(renderer): viewscreen scene-source RTT capability for VZT

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `engine/renderer.py` surface

**Files:**
- Modify: `engine/renderer.py` (wrappers near :728; `_REQUIRED_BINDINGS` near :37-59)
- Test: `tests/host/test_viewscreen_scene_source_surface.py` (create)

**Interfaces:**
- Consumes (Task 1): `_h.set_viewscreen_scene_source`, `_h.clear_viewscreen_scene_source`.
- Produces:
  - `renderer.set_viewscreen_scene_source(eye, target, up, fov_y_rad, near, far) -> None`
  - `renderer.clear_viewscreen_scene_source() -> None`

- [ ] **Step 1: Write the failing test.** Create `tests/host/test_viewscreen_scene_source_surface.py`:

```python
import engine.renderer as renderer


class _FakeHost:
    def __init__(self):
        self.calls = []

    def set_viewscreen_scene_source(self, eye, target, up, fov_y_rad, near, far):
        self.calls.append(("set", eye, target, up, fov_y_rad, near, far))

    def clear_viewscreen_scene_source(self):
        self.calls.append(("clear",))


def test_scene_source_passthrough(monkeypatch):
    fake = _FakeHost()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_viewscreen_scene_source(
        (1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (0.0, 0.0, 1.0), 0.5, 1.0, 5000.0)
    renderer.clear_viewscreen_scene_source()
    assert fake.calls == [
        ("set", (1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (0.0, 0.0, 1.0), 0.5, 1.0, 5000.0),
        ("clear",),
    ]


def test_scene_source_in_required_bindings():
    assert "set_viewscreen_scene_source" in renderer._REQUIRED_BINDINGS
    assert "clear_viewscreen_scene_source" in renderer._REQUIRED_BINDINGS
```

- [ ] **Step 2: Run it, verify it fails.**

Run: `uv run pytest tests/host/test_viewscreen_scene_source_surface.py -v`
Expected: FAIL — `AttributeError: module 'engine.renderer' has no attribute 'set_viewscreen_scene_source'` and the manifest assert fails.

- [ ] **Step 3: Add the wrappers.** After `clear_viewscreen_comm_source` (currently `engine/renderer.py:728`), add:

```python
def set_viewscreen_scene_source(eye, target, up, fov_y_rad, near, far) -> None:
    """Render the live exterior scene into the viewscreen RTT through the given
    camera (ViewscreenZoomTarget). Takes precedence over the forward feed; the
    comm source still wins over this. Game units; column-vector convention."""
    _h.set_viewscreen_scene_source(eye, target, up, fov_y_rad, near, far)


def clear_viewscreen_scene_source() -> None:
    """Disable the scene source, returning the viewscreen to the forward feed."""
    _h.clear_viewscreen_scene_source()
```

- [ ] **Step 4: Add both names to `_REQUIRED_BINDINGS`.** In the frozenset (currently `engine/renderer.py:37`), add alongside `clear_viewscreen_comm_source`:

```python
    "clear_viewscreen_comm_source", "clear_viewscreen_scene_source",
```

and alongside `set_viewscreen_comm_source` (currently :58):

```python
    "set_viewscreen_brightness", "set_viewscreen_comm_source",
    "set_viewscreen_scene_source",
```

- [ ] **Step 5: Run the test, verify it passes.**

Run: `uv run pytest tests/host/test_viewscreen_scene_source_surface.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit.**

```bash
git add engine/renderer.py tests/host/test_viewscreen_scene_source_surface.py
git commit -m "feat(renderer): scene-source Python surface + manifest

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `Game.GetPlayerCamera()`

**Files:**
- Modify: `engine/core/game.py` (`__init__` near :275; add method after `GetPlayerSet`/near :357)
- Test: `tests/unit/test_get_player_camera.py` (create)

**Interfaces:**
- Consumes: `engine.appc.bridge_set.CameraObjectClass_Create(x,y,z,a,ax,ay,az,name)`.
- Produces: `Game.GetPlayerCamera() -> CameraObjectClass` — lazy, identity-stable, named `"MainPlayerCamera"`.

- [ ] **Step 1: Write the failing test.** Create `tests/unit/test_get_player_camera.py`:

```python
from engine.core.game import Game
from engine.appc.bridge_set import CameraObjectClass


def test_get_player_camera_is_lazy_and_stable():
    g = Game()
    assert g._player_camera is None
    cam = g.GetPlayerCamera()
    assert isinstance(cam, CameraObjectClass)
    assert g.GetPlayerCamera() is cam          # identity-stable
    assert g._player_camera is cam


def test_get_player_camera_name():
    cam = Game().GetPlayerCamera()
    assert cam._name == "MainPlayerCamera"
```

- [ ] **Step 2: Run it, verify it fails.**

Run: `uv run pytest tests/unit/test_get_player_camera.py -v`
Expected: FAIL — `AttributeError: 'Game' object has no attribute '_player_camera'` / `GetPlayerCamera`.

- [ ] **Step 3: Add the field.** In `Game.__init__` (currently `engine/core/game.py:275`), after `self._player = None`, add:

```python
        self._player_camera = None   # lazy MainPlayerCamera (GetPlayerCamera)
```

- [ ] **Step 4: Add the method.** After the `GetCurrentPlayer = GetPlayer` / `SetCurrentPlayer = SetPlayer` aliases (currently near `engine/core/game.py:357`), add:

```python
    def GetPlayerCamera(self):
        """BC's "MainPlayerCamera" (Camera.MakePlayerCamera), the SpaceCamera
        that follows the player ship and feeds the bridge viewscreen. Our shim
        never runs MakePlayerCamera, so lazily create a real CameraObjectClass
        the SDK camera-mode surface can drive: MissionLib.ViewscreenWatchObject
        needs GetNamedCameraMode("ViewscreenZoomTarget") + AddModeHierarchy to
        run against a real mode instead of TGObject's truthy _Stub."""
        if self._player_camera is None:
            from engine.appc.bridge_set import CameraObjectClass_Create
            self._player_camera = CameraObjectClass_Create(
                0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "MainPlayerCamera")
        return self._player_camera
```

- [ ] **Step 5: Run the test, verify it passes.**

Run: `uv run pytest tests/unit/test_get_player_camera.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit.**

```bash
git add engine/core/game.py tests/unit/test_get_player_camera.py
git commit -m "feat(camera): real Game.GetPlayerCamera (MainPlayerCamera)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `ViewscreenZoomTarget` mode + `AddModeHierarchy` engagement seam

**Files:**
- Modify: `engine/appc/bridge_set.py` (`CameraObjectClass.__init__` :269-275; `_MODE_FACTORY` :371; `AddModeHierarchy` :441-442)
- Test: `tests/unit/test_viewscreen_zoom_target_mode.py` (create)

**Interfaces:**
- Consumes (Task 3): `Game.GetPlayerCamera()`; `engine.appc.camera_modes.ZoomTargetMode`.
- Produces:
  - `cam.GetNamedCameraMode("ViewscreenZoomTarget")` → a `ZoomTargetMode` (owner = `cam`).
  - `cam._vs_active` — bool, **initialized `False`** (must be a real attr, not a `_LoudStub` fallthrough).
  - `cam.AddModeHierarchy("InvalidViewscreen", "ViewscreenZoomTarget")` sets `cam._vs_active = True`; all other arg pairs stay no-ops returning `None`.

**Critical gotcha:** `CameraObjectClass` derives from `_LoudStub`, whose `__getattr__` returns a truthy `lambda *a, **k: None` for any missing attribute. So `_vs_active` **must** be set in `__init__` — otherwise `cam._vs_active` returns a truthy lambda and VZT is always "engaged". (Do **not** rely on `getattr(cam, "_vs_active", False)`; the default is never reached.)

- [ ] **Step 1: Write the failing test.** Create `tests/unit/test_viewscreen_zoom_target_mode.py`:

```python
from engine.appc.bridge_set import CameraObjectClass_Create
from engine.appc.camera_modes import ZoomTargetMode


def _cam():
    return CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "MainPlayerCamera")


def test_viewscreen_zoom_target_is_zoomtarget_mode():
    cam = _cam()
    mode = cam.GetNamedCameraMode("ViewscreenZoomTarget")
    assert isinstance(mode, ZoomTargetMode)
    # identity-stable (same mode instance on re-fetch)
    assert cam.GetNamedCameraMode("ViewscreenZoomTarget") is mode
    assert mode._owner_camera is cam


def test_vs_active_defaults_false_not_stub():
    cam = _cam()
    # Real attribute — must be exactly False, NOT a truthy _LoudStub lambda.
    assert cam._vs_active is False


def test_addmodehierarchy_engagement_seam():
    cam = _cam()
    assert cam._vs_active is False
    cam.AddModeHierarchy("InvalidViewscreen", "ViewscreenZoomTarget")
    assert cam._vs_active is True


def test_addmodehierarchy_other_pairs_are_noops():
    cam = _cam()
    cam.AddModeHierarchy("ViewscreenZoomTarget", "ViewscreenForward")
    assert cam._vs_active is False
    cam.AddModeHierarchy("InvalidSpace", "Target")
    assert cam._vs_active is False
```

- [ ] **Step 2: Run it, verify it fails.**

Run: `uv run pytest tests/unit/test_viewscreen_zoom_target_mode.py -v`
Expected: FAIL — `GetNamedCameraMode("ViewscreenZoomTarget")` returns `None` (not in factory) so `isinstance` fails; `_vs_active` is a truthy lambda so `is False` fails.

- [ ] **Step 3: Initialize `_vs_active` in `__init__`.** In `CameraObjectClass.__init__` (currently `engine/appc/bridge_set.py:269-275`), after `self._far = far`, add:

```python
        # ViewscreenZoomTarget (VZT) engagement flag. MUST be a real attribute:
        # _LoudStub.__getattr__ hands back a truthy lambda for any missing name,
        # so an unset flag would read as permanently "engaged". Set by
        # AddModeHierarchy("InvalidViewscreen", "ViewscreenZoomTarget"); read by
        # host_loop._viewscreen_scene_feed each frame.
        self._vs_active = False
```

- [ ] **Step 4: Register the named mode.** In `_MODE_FACTORY` (currently `engine/appc/bridge_set.py:371`), add the entry:

```python
        "ViewscreenZoomTarget": ("ZoomTargetMode", {}),
```

- [ ] **Step 5: Make `AddModeHierarchy` the engagement seam.** Replace the current no-op (currently `engine/appc/bridge_set.py:441-442`):

```python
    def AddModeHierarchy(self, *args):
        return None
```

with:

```python
    def AddModeHierarchy(self, *args):
        # BC's viewscreen engagement seam. MissionLib.ViewscreenWatchObject
        # (and BC's bridge zoom trigger) call AddModeHierarchy(
        # "InvalidViewscreen", "ViewscreenZoomTarget") to make the viewscreen
        # resolve to the zoom mode. We don't model the full fallback tree; we
        # treat exactly that pair as "engage VZT" by flipping a flag the host
        # reads each frame (host_loop._viewscreen_scene_feed). All other pairs
        # stay no-ops, matching the prior stub.
        if args[:2] == ("InvalidViewscreen", "ViewscreenZoomTarget"):
            self._vs_active = True
        return None
```

- [ ] **Step 6: Run the test, verify it passes.**

Run: `uv run pytest tests/unit/test_viewscreen_zoom_target_mode.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit.**

```bash
git add engine/appc/bridge_set.py tests/unit/test_viewscreen_zoom_target_mode.py
git commit -m "feat(camera): ViewscreenZoomTarget mode + AddModeHierarchy engage seam

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Adaptive-fill FOV law

**Files:**
- Modify: `engine/host_loop.py` (add constants + `_adaptive_vs_fov` near the other module-level camera helpers, e.g. just above `_active_cutscene_camera`)
- Test: `tests/unit/test_adaptive_vs_fov.py` (create)

**Interfaces:**
- Produces: `host_loop._adaptive_vs_fov(target, eye) -> float` (vertical FOV, radians). `target` has `GetWorldLocation()` (TGPoint3) and `GetRadius()` (float, game units); `eye` is a 3-tuple. Module constants `VS_NEAR`, `VS_FAR`, `VS_FILL_K`, `VS_FOV_MIN`, `VS_FOV_MAX`.

- [ ] **Step 1: Write the failing test.** Create `tests/unit/test_adaptive_vs_fov.py`:

```python
import math
from engine import host_loop


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Target:
    def __init__(self, loc, radius):
        self._loc, self._r = loc, radius

    def GetWorldLocation(self):
        return self._loc

    def GetRadius(self):
        return self._r


def test_fov_clamps_to_max_when_very_close():
    # radius huge relative to distance -> clamp to VS_FOV_MAX
    t = _Target(_Pt(1.0, 0.0, 0.0), 100.0)
    fov = host_loop._adaptive_vs_fov(t, (0.0, 0.0, 0.0))
    assert abs(fov - host_loop.VS_FOV_MAX) < 1e-6


def test_fov_clamps_to_min_when_very_far():
    t = _Target(_Pt(100000.0, 0.0, 0.0), 1.0)
    fov = host_loop._adaptive_vs_fov(t, (0.0, 0.0, 0.0))
    assert abs(fov - host_loop.VS_FOV_MIN) < 1e-6


def test_fov_midrange_matches_formula():
    # choose r/dist so the clamp is not active: half = 1.6*6/100 = 0.096,
    # between tan(3deg)=0.052 and tan(20deg)=0.364.
    dist = 100.0
    r = 6.0
    t = _Target(_Pt(dist, 0.0, 0.0), r)
    fov = host_loop._adaptive_vs_fov(t, (0.0, 0.0, 0.0))
    expected = 2.0 * math.atan(host_loop.VS_FILL_K * r / dist)
    assert host_loop.VS_FOV_MIN <= fov <= host_loop.VS_FOV_MAX
    assert abs(fov - expected) < 1e-6


def test_fov_degenerate_zero_distance_is_max():
    t = _Target(_Pt(0.0, 0.0, 0.0), 5.0)
    fov = host_loop._adaptive_vs_fov(t, (0.0, 0.0, 0.0))
    assert abs(fov - host_loop.VS_FOV_MAX) < 1e-6
```

- [ ] **Step 2: Run it, verify it fails.**

Run: `uv run pytest tests/unit/test_adaptive_vs_fov.py -v`
Expected: FAIL — `AttributeError: module 'engine.host_loop' has no attribute '_adaptive_vs_fov'`.

- [ ] **Step 3: Add constants + function.** In `engine/host_loop.py`, just above the `def _active_cutscene_camera(` definition, add (`_math` is already imported and used in this module):

```python
# ── ViewscreenZoomTarget (VZT) framing ─────────────────────────────────────────
# The bridge viewscreen zoom onto a target. Tunable here (no rebuild). FOV is
# adaptive-fill: the target subtends a fixed fraction of the viewscreen at any
# range. All lengths in game units; angles in radians.
VS_NEAR: float = 1.0
VS_FAR: float = 5000.0
VS_FILL_K: float = 1.6                       # radius→apparent-fill gain; tune live
VS_FOV_MIN: float = _math.radians(6.0)       # most-zoomed (distant target) clamp
VS_FOV_MAX: float = _math.radians(40.0)      # least-zoomed (near target) clamp


def _adaptive_vs_fov(target, eye) -> float:
    """Vertical FOV (radians) so `target` subtends a fixed fraction of the
    viewscreen regardless of range ("zoom onto that ship"). Clamped to
    [VS_FOV_MIN, VS_FOV_MAX]; degenerate inputs (zero distance / radius, missing
    getters) return the widest FOV (VS_FOV_MAX)."""
    try:
        loc = target.GetWorldLocation()
        r = float(target.GetRadius())
    except Exception:
        return VS_FOV_MAX
    dx = loc.x - eye[0]
    dy = loc.y - eye[1]
    dz = loc.z - eye[2]
    dist = _math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist <= 0.0 or r <= 0.0:
        return VS_FOV_MAX
    half = VS_FILL_K * r / dist
    lo = _math.tan(VS_FOV_MIN / 2.0)
    hi = _math.tan(VS_FOV_MAX / 2.0)
    half = max(lo, min(hi, half))
    return 2.0 * _math.atan(half)
```

- [ ] **Step 4: Run the test, verify it passes.**

Run: `uv run pytest tests/unit/test_adaptive_vs_fov.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit.**

```bash
git add engine/host_loop.py tests/unit/test_adaptive_vs_fov.py
git commit -m "feat(camera): adaptive-fill FOV law for viewscreen zoom

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `_viewscreen_scene_feed` resolver

**Files:**
- Modify: `engine/host_loop.py` (add `_viewscreen_scene_feed` right below `_adaptive_vs_fov`)
- Test: `tests/host/test_viewscreen_scene_feed.py` (create)

**Interfaces:**
- Consumes: `Game_GetCurrentGame()` (imported at `engine/host_loop.py:59`); `game.GetPlayerCamera()` (Task 3); `cam.GetNamedCameraMode` + `cam._vs_active` (Task 4); `_adaptive_vs_fov` (Task 5); `engine.appc.camera_modes._target_alive`.
- Produces: `host_loop._viewscreen_scene_feed(controller, player, dt, zoom_held) -> tuple | None` — `(eye, target, up, fov_y_rad, near, far)` when VZT should render, else `None`. `eye`/`target`/`up` are 3-tuples.

- [ ] **Step 1: Write the failing test.** Create `tests/host/test_viewscreen_scene_feed.py`:

```python
import math
import pytest
from engine import host_loop
from engine.core import game as game_mod
from engine.appc.bridge_set import CameraObjectClass_Create


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Rot:
    # column-vector: col2 = up (0,0,1)
    def GetCol(self, i):
        return _Pt(0.0, 0.0, 1.0) if i == 2 else _Pt(0.0, 1.0, 0.0)


class _Ship:
    def __init__(self, loc, radius=2.0, target=None):
        self._loc, self._r, self._target = loc, radius, target

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return _Rot()

    def GetRadius(self):
        return self._r

    def GetTarget(self):
        return self._target

    def IsDying(self):
        return 0


class _Game:
    def __init__(self, cam):
        self._cam = cam

    def GetPlayerCamera(self):
        return self._cam


@pytest.fixture
def wired(monkeypatch):
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "MainPlayerCamera")
    monkeypatch.setattr(host_loop, "Game_GetCurrentGame", lambda: _Game(cam))
    return cam


def test_none_when_not_engaged(wired):
    tgt = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt)
    assert host_loop._viewscreen_scene_feed(None, player, 0.016, False) is None


def test_hold_zoom_uses_player_target(wired):
    tgt = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=tgt)
    out = host_loop._viewscreen_scene_feed(None, player, 0.016, True)
    assert out is not None
    eye, target, up, fov, near, far = out
    assert eye == (0.0, 0.0, 0.0)                       # eye at player (Source)
    # looks toward the target (+X): target = eye + forward
    assert target[0] > 0.0 and abs(target[1]) < 1e-6
    assert near == host_loop.VS_NEAR and far == host_loop.VS_FAR
    assert host_loop.VS_FOV_MIN <= fov <= host_loop.VS_FOV_MAX


def test_hold_with_no_target_is_none(wired):
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=None)
    assert host_loop._viewscreen_scene_feed(None, player, 0.016, True) is None


def test_mission_sticky_engages_without_hold(wired):
    watched = _Ship(_Pt(0.0, 800.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=None)
    mode = wired.GetNamedCameraMode("ViewscreenZoomTarget")
    mode.SetAttrIDObject("Target", watched)
    wired.AddModeHierarchy("InvalidViewscreen", "ViewscreenZoomTarget")   # engage
    out = host_loop._viewscreen_scene_feed(None, player, 0.016, False)
    assert out is not None
    _eye, target, _up, _fov, _n, _f = out
    assert target[1] > 0.0                              # looks toward watched (+Y)


def test_mission_sticky_wins_over_hold_target(wired):
    watched = _Ship(_Pt(0.0, 800.0, 0.0))
    combat = _Ship(_Pt(500.0, 0.0, 0.0))
    player = _Ship(_Pt(0.0, 0.0, 0.0), target=combat)
    mode = wired.GetNamedCameraMode("ViewscreenZoomTarget")
    mode.SetAttrIDObject("Target", watched)
    wired.AddModeHierarchy("InvalidViewscreen", "ViewscreenZoomTarget")
    out = host_loop._viewscreen_scene_feed(None, player, 0.016, True)
    _eye, target, _up, _fov, _n, _f = out
    assert target[1] > 0.0 and abs(target[0]) < 1e-6    # watched (+Y), not combat (+X)


def test_source_pinned_to_live_player(wired):
    tgt = _Ship(_Pt(0.0, 0.0, 900.0))
    player = _Ship(_Pt(10.0, 20.0, 30.0), target=tgt)
    out = host_loop._viewscreen_scene_feed(None, player, 0.016, True)
    eye = out[0]
    assert eye == (10.0, 20.0, 30.0)                    # eye follows the live player
```

- [ ] **Step 2: Run it, verify it fails.**

Run: `uv run pytest tests/host/test_viewscreen_scene_feed.py -v`
Expected: FAIL — `AttributeError: module 'engine.host_loop' has no attribute '_viewscreen_scene_feed'`.

- [ ] **Step 3: Add the resolver.** In `engine/host_loop.py`, immediately below `_adaptive_vs_fov`, add:

```python
def _viewscreen_scene_feed(controller, player, dt, zoom_held):
    """Resolve the ViewscreenZoomTarget scene feed. Returns
    (eye, target, up, fov_y_rad, near, far) to render the live exterior scene
    zoomed onto a target into the bridge viewscreen RTT, or None to leave the
    forward feed. Pull-model: reads SDK/input state, never writes it.

    Two engagement sources, mission-sticky first: the player camera's _vs_active
    flag (set by ViewscreenWatchObject via AddModeHierarchy) with the mode's
    explicit Target, else a held Z in bridge view following player.GetTarget()."""
    if player is None:
        return None
    from engine.appc.camera_modes import _target_alive
    game = Game_GetCurrentGame()
    if game is None:
        return None
    cam = game.GetPlayerCamera()
    if cam is None:
        return None
    mode = cam.GetNamedCameraMode("ViewscreenZoomTarget")
    if mode is None:
        return None

    explicit = mode.GetAttrIDObject("Target")
    if cam._vs_active and _target_alive(explicit):
        tgt = explicit                          # mission watch (sticky) wins
    elif zoom_held:
        tgt = player.GetTarget()                # Z held in bridge → live target
    else:
        return None                             # not engaged → forward feed
    if not _target_alive(tgt):
        return None

    mode.SetAttrIDObject("Source", player)      # pin Source to the live player
    mode.SetAttrIDObject("Target", tgt)
    if not mode.IsValid():                      # _ideal() resolvable?
        return None
    eye, fwd, up = mode.Update(dt)
    target = (eye[0] + fwd[0], eye[1] + fwd[1], eye[2] + fwd[2])
    fov = _adaptive_vs_fov(tgt, eye)
    return (eye, target, up, fov, VS_NEAR, VS_FAR)
```

- [ ] **Step 4: Run the test, verify it passes.**

Run: `uv run pytest tests/host/test_viewscreen_scene_feed.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit.**

```bash
git add engine/host_loop.py tests/host/test_viewscreen_scene_feed.py
git commit -m "feat(camera): _viewscreen_scene_feed VZT resolver (mission + hold-Z)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Wire resolver + hold-`Z` into the feed-selection block

**Files:**
- Modify: `engine/host_loop.py` (the feed-selection block, currently `:6251-6275`)
- Test: `tests/host/test_viewscreen_feed_precedence.py` (create)

**Interfaces:**
- Consumes: `_viewscreen_scene_feed` (Task 6); `renderer.set_viewscreen_scene_source` / `clear_viewscreen_scene_source` (Task 2); `host_io.key_state`, `input_map.code` (already imported in host_loop); `view_mode.is_bridge`.
- Produces: per-frame RTT source selection with precedence **comm > scene > forward**; a held `Z` in bridge view engages VZT via `_z_held_bridge`.

**Note on testing:** the surrounding `run()` loop is not unit-testable in isolation. Extract the three-way selection into a small pure helper `_select_viewscreen_source(r, controller, player, dt, comm_feed, scene_feed)` so precedence is testable, and call it from the loop. This keeps the loop edit tiny.

- [ ] **Step 1: Write the failing test.** Create `tests/host/test_viewscreen_feed_precedence.py`:

```python
from engine import host_loop


class _Recorder:
    def __init__(self):
        self.calls = []

    def set_viewscreen_comm_source(self, *a):
        self.calls.append(("comm", a))

    def clear_viewscreen_comm_source(self):
        self.calls.append(("clear_comm",))

    def set_viewscreen_scene_source(self, *a):
        self.calls.append(("scene", a))

    def clear_viewscreen_scene_source(self):
        self.calls.append(("clear_scene",))


def _names(rec):
    return [c[0] for c in rec.calls]


def test_comm_wins_and_clears_scene():
    rec = _Recorder()
    comm = (7, (0, 0, 0), (0, 1, 0), (0, 0, 1), 0.5, 1.0, 5000.0)
    # The helper does NOT render comm itself (the loop does, with set bounds); it
    # returns "comm" and guarantees the scene source is cleared.
    result = host_loop._select_viewscreen_source(
        rec, controller=None, player=None, dt=0.016,
        comm_feed=comm, scene_feed=(1, 2, 3, 4, 5, 6))
    assert result == "comm"
    assert "clear_scene" in _names(rec)
    assert "clear_comm" not in _names(rec)
    assert "scene" not in _names(rec)


def test_scene_when_no_comm():
    rec = _Recorder()
    host_loop._select_viewscreen_source(
        rec, controller=None, player=None, dt=0.016,
        comm_feed=None, scene_feed=((0, 0, 0), (0, 1, 0), (0, 0, 1), 0.4, 1.0, 5000.0))
    assert "clear_comm" in _names(rec)
    assert "scene" in _names(rec)
    assert "clear_scene" not in _names(rec)


def test_forward_when_neither():
    rec = _Recorder()
    host_loop._select_viewscreen_source(
        rec, controller=None, player=None, dt=0.016,
        comm_feed=None, scene_feed=None)
    assert "clear_comm" in _names(rec)
    assert "clear_scene" in _names(rec)
    assert "comm" not in _names(rec) and "scene" not in _names(rec)
```

- [ ] **Step 2: Run it, verify it fails.**

Run: `uv run pytest tests/host/test_viewscreen_feed_precedence.py -v`
Expected: FAIL — `AttributeError: module 'engine.host_loop' has no attribute '_select_viewscreen_source'`.

- [ ] **Step 3: Add the pure selection helper.** In `engine/host_loop.py`, just below `_viewscreen_scene_feed`, add:

```python
def _select_viewscreen_source(r, controller, player, dt, comm_feed, scene_feed):
    """Push the viewscreen RTT source for this frame with precedence
    comm hail > VZT scene > forward. `comm_feed` is the tuple already resolved
    by _active_comm_feed (or None); `scene_feed` is _viewscreen_scene_feed's
    return (or None). Exactly one of comm/scene is active at a time; the other
    source is always cleared, so an unset source can never linger."""
    if comm_feed is not None:
        # Caller renders the comm source (it owns the set-bounds framing); we
        # only guarantee the scene source is cleared so it can't co-render.
        r.clear_viewscreen_scene_source()
        return "comm"
    r.clear_viewscreen_comm_source()
    if scene_feed is not None:
        r.set_viewscreen_scene_source(*scene_feed)
        return "scene"
    r.clear_viewscreen_scene_source()
    return "forward"
```

Design note: when comm wins, the helper returns `"comm"` and clears the scene source but does **not** call `set_viewscreen_comm_source` — the loop renders comm itself (it needs the per-set bounds framing). The helper's job is precedence + guaranteeing the inactive source is always cleared.

- [ ] **Step 4: Run the test, verify it passes.**

Run: `uv run pytest tests/host/test_viewscreen_feed_precedence.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Wire the loop to use the helper + resolver + hold-`Z`.** In `engine/host_loop.py`, replace the current feed-selection block (currently `:6251-6275`):

```python
            _feed = _active_comm_feed(controller)
            if _feed is not None:
                _set_id, _cam = _feed
                def _comm_bounds(_set_id=_set_id):
                    _set_name = next((n for n, i in controller.comm_set_ids.items()
                                      if i == _set_id), None)
                    _iids = controller.comm_instances_by_set.get(_set_name, [])
                    if not _iids:
                        return None
                    try:
                        return r.get_instance_bounds(_iids[0])
                    except Exception as _e:
                        dev_mode.log_swallowed("comm get_instance_bounds", _e)
                        return None
                _eye, _tgt, _up, _fov, _near, _far = _comm_feed_view(
                    _cam, _comm_bounds)
                r.set_viewscreen_comm_source(_set_id, _eye, _tgt, _up,
                                             _fov, _near, _far)
            else:
                r.clear_viewscreen_comm_source()
```

with (adds the `Z`-held read, resolves the scene feed, and routes both through the helper — comm framing still done inline when comm wins):

```python
            _feed = _active_comm_feed(controller)
            # Hold Z in bridge view engages VZT (mirrors the exterior zoom read
            # at ~:5901, which stays gated on is_exterior and is untouched).
            _z_held_bridge = (view_mode.is_bridge
                              and host_io.key_state(input_map.code("camera_zoom_target")))
            _scene = None
            if _feed is None:
                _scene = _viewscreen_scene_feed(
                    controller, player, _player_dt, _z_held_bridge)
            _vs_src = _select_viewscreen_source(
                r, controller, player, _player_dt, _feed, _scene)
            if _vs_src == "comm":
                _set_id, _cam = _feed
                def _comm_bounds(_set_id=_set_id):
                    _set_name = next((n for n, i in controller.comm_set_ids.items()
                                      if i == _set_id), None)
                    _iids = controller.comm_instances_by_set.get(_set_name, [])
                    if not _iids:
                        return None
                    try:
                        return r.get_instance_bounds(_iids[0])
                    except Exception as _e:
                        dev_mode.log_swallowed("comm get_instance_bounds", _e)
                        return None
                _eye, _tgt, _up, _fov, _near, _far = _comm_feed_view(
                    _cam, _comm_bounds)
                r.set_viewscreen_comm_source(_set_id, _eye, _tgt, _up,
                                             _fov, _near, _far)
```

- [ ] **Step 6: Run the full pytest suite (no regressions).**

Run: `uv run pytest tests/host/test_comm_viewscreen_feed.py tests/host/test_viewscreen_feed_precedence.py tests/host/test_viewscreen_scene_feed.py -v`
Expected: PASS (existing comm feed tests still green + new tests).

- [ ] **Step 7: Commit.**

```bash
git add engine/host_loop.py tests/host/test_viewscreen_feed_precedence.py
git commit -m "feat(camera): route VZT scene feed + hold-Z into viewscreen RTT selection

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Developer probe (live-verify harness)

**Files:**
- Create: `engine/dev_viewscreen_probe.py`
- Modify: `engine/host_loop.py` (register the probe where other dev pause-menu entries register, near `:5213`)

**Interfaces:**
- Consumes: `dev_mode.register_dev_pause_menu_entry(label, handler)`; `Game_GetCurrentGame()`; `MissionLib.ViewscreenWatchObject`.
- Produces: a dev-only "VZT: Watch Current Target" pause-menu row (only registered under `--developer`).

- [ ] **Step 1: Create the probe module.** Create `engine/dev_viewscreen_probe.py`:

```python
"""Developer-only probe for live-verifying ViewscreenZoomTarget.

Fires MissionLib.ViewscreenWatchObject on the player's current target, so the
mission-driven VZT path can be verified in QuickBattle without reaching an
E-series ViewscreenWatch beat. Diagnostics use print() — the host has no logging
handler (memory npc_subsystem_aim_gap). Remove once live-verified."""


def watch_current_target(*_args):
    from engine.core.game import Game_GetCurrentGame
    game = Game_GetCurrentGame()
    player = game.GetPlayer() if game is not None else None
    if player is None:
        print("[vzt-probe] no current player")
        return
    target = player.GetTarget()
    if target is None:
        print("[vzt-probe] no player target — select a target first")
        return
    import MissionLib
    ok = MissionLib.ViewscreenWatchObject(target)
    name = getattr(target, "GetName", lambda: "?")()
    print("[vzt-probe] ViewscreenWatchObject(%s) -> %s" % (name, ok))
```

- [ ] **Step 2: Register it (dev-only).** In `engine/host_loop.py`, in the block that registers dev pause-menu entries (near `:5213`, alongside the existing `dev_mode.register_dev_pause_menu_entry(...)` calls), add:

```python
            from engine.dev_viewscreen_probe import watch_current_target
            dev_mode.register_dev_pause_menu_entry(
                "VZT: Watch Current Target", watch_current_target)
```

- [ ] **Step 3: Verify import + registration under dev mode.** Create a quick smoke `tests/host/test_vzt_probe_registers.py`:

```python
import engine.dev_mode as dev_mode


def test_probe_handler_importable():
    from engine.dev_viewscreen_probe import watch_current_target
    assert callable(watch_current_target)


def test_probe_handler_no_player_is_safe(monkeypatch, capsys):
    import engine.dev_viewscreen_probe as probe
    import engine.core.game as game_mod
    monkeypatch.setattr(game_mod, "Game_GetCurrentGame", lambda: None)
    probe.watch_current_target()
    assert "no current player" in capsys.readouterr().out
```

Run: `uv run pytest tests/host/test_vzt_probe_registers.py -v`
Expected: PASS (2 tests).

- [ ] **Step 4: Commit.**

```bash
git add engine/dev_viewscreen_probe.py engine/host_loop.py tests/host/test_vzt_probe_registers.py
git commit -m "feat(dev): VZT live-verify probe (pause-menu watch-current-target)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Gate + live-verify + remove probe

**Files:**
- Modify: `engine/dev_viewscreen_probe.py` (delete), `engine/host_loop.py` (remove registration), test file (delete) — after live-verify.

- [ ] **Step 1: Run the full gate.**

Run: `scripts/check_tests.sh`
Expected: exits 0. Any failure NOT in `tests/known_failures.txt` (the 7 headless-GL `FrameTest`s) is a regression introduced here — fix it before proceeding. Do **not** eyeball "pre-existing"; the gate is authoritative.

- [ ] **Step 2: Live-verify in QuickBattle (mission path).**

Run `./build/dauntless --developer`, start QuickBattle, select an enemy as target, open the pause menu → **VZT: Watch Current Target**. Confirm: the bridge stays visible and the **viewscreen** zooms onto the selected ship (exterior view, target framed). Check the console for `[vzt-probe] ViewscreenWatchObject(<name>) -> 1`. This is a live workstation — do not synthetic-click or full-screen capture (memory `no_desktop_interaction`); drive it yourself and observe.

- [ ] **Step 3: Live-verify hold-`Z`.**

In bridge view with a target selected, **hold `Z`**: the viewscreen zooms onto the current target while held and returns to the forward view on release. Switch to the exterior view and confirm holding `Z` still does the exterior zoom-on-target (unchanged).

- [ ] **Step 4: If anything is off, tune (no rebuild).**

Adjust `VS_FILL_K` / `VS_FOV_MIN` / `VS_FOV_MAX` in `engine/host_loop.py` and re-run — these are pure-Python and need no rebuild. Re-verify Steps 2-3.

- [ ] **Step 5: Remove the probe.**

Delete `engine/dev_viewscreen_probe.py` and `tests/host/test_vzt_probe_registers.py`, and remove the registration block added in Task 8 Step 2 from `engine/host_loop.py`.

Run: `scripts/check_tests.sh`
Expected: exits 0.

- [ ] **Step 6: Commit.**

```bash
git add engine/host_loop.py
git rm engine/dev_viewscreen_probe.py tests/host/test_vzt_probe_registers.py
git commit -m "chore(dev): remove VZT live-verify probe (verified)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review notes

- **Spec coverage:** Decision 1 → Task 1-2; Decision 2 → Task 3-4; Decision 3 (mission seam + hold-Z + resolver + precedence) → Task 4/6/7; adaptive FOV → Task 5; visibility guarantee → relies on existing `_apply_bridge_player_visibility` (no change; verified in Task 9 Step 2); testing → each task; dev harness + live-verify → Task 8-9. Byte-identical-when-inactive → Task 1 (`else` unchanged) + Task 7 helper (always clears the inactive source).
- **Player-hull visibility:** no code change needed — VZT is a bridge frame (`_cc is None`), so `_apply_bridge_player_visibility` already hides the player hull; the eye-at-player RTT camera therefore does not clip it. Confirmed live in Task 9 Step 2.
- **Divergence noted:** after `ViewscreenWatchObject(X)`, cycling combat targets keeps showing `X` (we don't model `PlayerTargetChanged`) — acceptable per spec Non-goals.
