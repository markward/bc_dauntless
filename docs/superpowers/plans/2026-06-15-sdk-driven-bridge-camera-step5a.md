# SDK-driven captain camera + zoom-to-officer (step 5a) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the SDK `ZoomCameraObjectClass` the source of truth for the bridge captain's-chair pose (dropping the last bridge-load stub), and add zoom-into-officer: the captain camera stays at the chair but rotates + narrows FOV onto the officer whose crew menu is open.

**Architecture:** Promote `ZoomCameraObjectClass` to a real data object (over `_LoudStub`); the host caches its position + zoom params at mission load into module globals; `_BridgeCamera` reads the position for its eye and gains a small zoom state machine (eased look-at + FOV toward the selected officer's rendered world centre). Triggered by the existing F1–F5 crew-menu selection.

**Tech Stack:** Python (headless `engine/appc` shim + host loop), pytest. **Pure Python — no rebuild** (the renderer already accepts a per-frame `fov_y_rad`).

**Spec:** `docs/superpowers/specs/2026-06-15-sdk-driven-bridge-camera-step5a-design.md`

> ⚠️ **NEVER run the full pytest suite** (`uv run pytest` with no path) — it uses >100 GB RAM and freezes macOS. Always pass explicit test paths (every `Run:` below does). Warn any subagent.

---

## File Structure

- **Modify** `engine/appc/bridge_set.py` — `ZoomCameraObjectClass` becomes a real data object; `ZoomCameraObjectClass_Create` + `_GetObject` drop their `stub_call`.
- **Modify** `engine/host_loop.py` — module globals `_BRIDGE_CAMERA_EYE` + `_BRIDGE_ZOOM_{MIN,MAX,TIME}` (replace `_BRIDGE_CAMERA_OFFSETS`/`_CURRENT_BRIDGE_NAME`); `_BridgeCamera` zoom state machine + 4-tuple `compute_camera`; `_after_mission_loaded` caches the SDK camera; `_active_zoom_officer_world` helper; render-block wiring.
- **Modify** `engine/ui/crew_menu_panel.py` — `open_menu_label()` accessor.
- **Modify** `tests/unit/test_bridge_set_stubs.py` — flip the `ZoomCameraObjectClass` stub assertions; assert the data round-trips.
- **Modify** `tests/integration/test_sdk_bridge_load.py` — camera position 61.93 + zoom params + empty bridge-stub summary.
- **Modify** `tests/host/test_bridge_camera.py` — `compute_camera` now returns 4 values; update unpacking + a stale docstring.
- **Create** `tests/unit/test_bridge_camera_zoom.py` — `_BridgeCamera` zoom state machine.
- **Create** `tests/unit/test_active_zoom_officer.py` — the officer-resolution helper + `open_menu_label`.

---

## Task 1: Promote `ZoomCameraObjectClass` + drop the last stub

**Files:**
- Modify: `engine/appc/bridge_set.py` (`ZoomCameraObjectClass` class ~lines 71-82; `ZoomCameraObjectClass_Create` ~155-157; `ZoomCameraObjectClass_GetObject` ~160-167)
- Test: `tests/unit/test_bridge_set_stubs.py`, `tests/integration/test_sdk_bridge_load.py`

- [ ] **Step 1: Update the unit test (write failing test).**

In `tests/unit/test_bridge_set_stubs.py`, **replace** `test_camera_stub_supports_sdk_calls` (currently asserts `"ZoomCameraObjectClass_Create" in st.fired()`) with:

```python
def test_zoom_camera_is_real_data_object_and_round_trips():
    cam = ZoomCameraObjectClass_Create(0.683736, 86.978439, 50.0,
                                       1.570796, -0.000665, -0.087559, 0.996159,
                                       "maincamera")
    # Step 5a: real data object now -> off the stub summary.
    assert "ZoomCameraObjectClass_Create" not in st.fired()
    assert cam.position == (0.683736, 86.978439, 50.0)
    assert cam.orientation == (1.570796, -0.000665, -0.087559, 0.996159)
    # Zoom params round-trip through the getters.
    cam.SetMinZoom(0.64); cam.SetMaxZoom(1.0); cam.SetZoomTime(0.375)
    assert cam.GetMinZoom() == 0.64
    assert cam.GetMaxZoom() == 1.0
    assert cam.GetZoomTime() == 0.375
    # ConfigureCharacters overrides the position via SetTranslateXYZ.
    cam.SetTranslateXYZ(0.683736, 86.978439, 61.934944)
    assert cam.position == (0.683736, 86.978439, 61.934944)
    # The unbuilt camera-mode / zoom-animation surface still no-ops via _LoudStub.
    assert cam.PushCameraMode(cam.GetNamedCameraMode("GalaxyBridgeCaptain")) is None
    assert cam.ToggleZoom(0.0) is None
    assert cam.Update(0.0) is None


def test_zoom_camera_get_object_returns_added_camera_not_loud():
    bs = BridgeSet_Create()
    cam = ZoomCameraObjectClass_Create(0, 0, 0, 0, 0, 0, 1, "maincamera")
    bs.AddCameraToSet(cam, "maincamera")
    assert ZoomCameraObjectClass_GetObject(bs, "maincamera") is cam
    assert "ZoomCameraObjectClass_GetObject" not in st.fired()
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py -q`
Expected: FAIL — `ZoomCameraObjectClass_Create` still fires `stub_call`; `cam.position`/`orientation`/getters don't exist.

- [ ] **Step 3: Rewrite `ZoomCameraObjectClass`.**

In `engine/appc/bridge_set.py`, **replace** the current class:

```python
class ZoomCameraObjectClass(_LoudStub):
    def __init__(self, x, y, z, qw, qx, qy, qz, name):
        self._name = name
    def SetMinZoom(self, v): return None
    def SetMaxZoom(self, v): return None
    def SetZoomTime(self, v): return None
    def GetNamedCameraMode(self, name):
        return _LoudStub()
    def PushCameraMode(self, mode): return None
    def Update(self, t): return None
    def SetTranslateXYZ(self, x, y, z): return None
```

with:

```python
class ZoomCameraObjectClass(_LoudStub):
    """SDK bridge camera ("maincamera"). Core data is real (captain-chair
    position, angle-axis orientation, zoom min/max/time); the engine's
    camera-mode + zoom-transform surface (GetNamedCameraMode, PushCameraMode,
    Update, ToggleZoom, Zoom, IsZoomed, LookForward, ...) stays a silent
    _LoudStub no-op — that geometry lived in Appc and is not reconstructed
    here. The host reads `position` + the zoom getters after LoadBridge.Load to
    drive _BridgeCamera (see host_loop). Kept a _LoudStub (unlike
    BridgeObjectClass) precisely because that camera-mode surface is large and
    not built."""
    def __init__(self, x, y, z, qw, qx, qy, qz, name):
        self.position = (x, y, z)
        self.orientation = (qw, qx, qy, qz)   # angle, axis-x, axis-y, axis-z
        self._name = name
        self._min_zoom = 1.0
        self._max_zoom = 1.0
        self._zoom_time = 0.0

    def SetMinZoom(self, v):  self._min_zoom = v
    def SetMaxZoom(self, v):  self._max_zoom = v
    def SetZoomTime(self, v): self._zoom_time = v
    def GetMinZoom(self):  return self._min_zoom
    def GetMaxZoom(self):  return self._max_zoom
    def GetZoomTime(self): return self._zoom_time
    def SetTranslateXYZ(self, x, y, z): self.position = (x, y, z)
```

- [ ] **Step 4: Drop the `stub_call`s from the two factories.**

**Replace**:
```python
def ZoomCameraObjectClass_Create(x, y, z, qw, qx, qy, qz, name):
    _stub_trace.stub_call("ZoomCameraObjectClass_Create", "name=%s" % name)
    return ZoomCameraObjectClass(x, y, z, qw, qx, qy, qz, name)


def ZoomCameraObjectClass_GetObject(pSet, name):
    # The camera was added to the set via AddCameraToSet; return it (or a loud
    # stub if not present so ConfigureCharacters' SetTranslateXYZ doesn't crash).
    cam = pSet.GetCamera(name) if pSet is not None else None
    if cam is None:
        _stub_trace.stub_call("ZoomCameraObjectClass_GetObject", "name=%s" % name)
        return _LoudStub()
    return cam
```
with:
```python
def ZoomCameraObjectClass_Create(x, y, z, qw, qx, qy, qz, name):
    return ZoomCameraObjectClass(x, y, z, qw, qx, qy, qz, name)  # real -> off summary


def ZoomCameraObjectClass_GetObject(pSet, name):
    # Return the real camera added via AddCameraToSet. The _LoudStub fallback
    # (camera absent) keeps ConfigureCharacters' SetTranslateXYZ from crashing,
    # but no longer fires stub_call.
    cam = pSet.GetCamera(name) if pSet is not None else None
    return cam if cam is not None else _LoudStub()
```

- [ ] **Step 5: Run the unit tests.**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py -q`
Expected: PASS (all).

- [ ] **Step 6: Update the integration test (write failing assertions).**

In `tests/integration/test_sdk_bridge_load.py`, in `test_sdk_load_runs_end_to_end_and_populates_crew`, the `fired` block currently asserts `"ZoomCameraObjectClass_Create" in fired`. **Replace** the two still-stubbed asserts:
```python
    # Still-stubbed control-flow symbols prove the SDK path actually ran.
    assert "BridgeSet_Create" in fired
    assert "ZoomCameraObjectClass_Create" in fired
```
with:
```python
    # Step 5a: the zoom camera is real now; BridgeSet_Create proves the SDK path
    # ran, and NO bridge-load symbol remains stubbed.
    assert "BridgeSet_Create" in fired
    assert "ZoomCameraObjectClass_Create" not in fired
    assert "ZoomCameraObjectClass_GetObject" not in fired

    # The SDK-created maincamera carries the captain pose; ConfigureCharacters'
    # SetTranslateXYZ override won (z=61.934944, not the 50.0 from create), and
    # the zoom params are the GalaxyBridge values.
    cam = bridge.GetCamera("maincamera")
    assert cam is not None
    assert cam.position == (0.683736, 86.978439, 61.934944)
    assert (cam.GetMinZoom(), cam.GetMaxZoom(), cam.GetZoomTime()) == (0.64, 1.0, 0.375)
```

Then in `test_summary_prints_outstanding_stubs`, **replace**:
```python
    # Step 5b: the viewscreen + BridgeSet.* are real now; only the zoom
    # camera remains stubbed for step 5a.
    assert "ZoomCameraObjectClass_Create" in err
    assert "ViewScreenObject_Create" not in err
    assert "BridgeObjectClass_Create" not in err
```
with:
```python
    # Step 5a: the zoom camera is real now too -> NO bridge-load stubs remain.
    assert "ZoomCameraObjectClass_Create" not in err
    assert "ZoomCameraObjectClass_GetObject" not in err
    assert "ViewScreenObject_Create" not in err
    assert "BridgeObjectClass_Create" not in err
```

> If `test_summary_prints_outstanding_stubs` asserts the summary contains "still need fleshing out" text unconditionally, leave that assertion; with no bridge-load stubs the summary may now be empty of bridge symbols but the harness still prints its header — only the per-symbol asserts change. If the summary body is genuinely empty and the test asserted a non-empty body, adjust that test to assert the bridge symbols are absent (as above) rather than forcing a non-empty body.

- [ ] **Step 7: Run the integration test.**

Run: `uv run pytest tests/integration/test_sdk_bridge_load.py -q`
Expected: PASS (2 tests).

- [ ] **Step 8: Commit.**

```bash
git add engine/appc/bridge_set.py tests/unit/test_bridge_set_stubs.py tests/integration/test_sdk_bridge_load.py
git commit -m "feat(bridge): make ZoomCameraObjectClass real — last bridge-load stub gone (step 5a)

Promote ZoomCameraObjectClass to a real data object (captain position,
angle-axis orientation, zoom min/max/time) over a _LoudStub base that
keeps the unbuilt camera-mode/zoom-animation surface a silent no-op.
Create + GetObject drop their stub_call. A real Load('GalaxyBridge') now
leaves the [BRIDGE-STUB] SUMMARY empty of bridge-load symbols; the
maincamera carries the z=61.93 ConfigureCharacters override.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Captain eye position from the SDK camera

**Files:**
- Modify: `engine/host_loop.py` (module globals ~783-793; `_BridgeCamera._eye_offset` ~1258-1264; `_after_mission_loaded` config-name block ~2358-2366)
- Test: `tests/host/test_bridge_camera.py` (small addition)

- [ ] **Step 1: Write the failing test.**

In `tests/host/test_bridge_camera.py`, add:

```python
def test_eye_offset_reads_module_global(monkeypatch):
    """Step 5a: the captain eye comes from the SDK-camera-derived module
    global, not a hardcoded per-bridge table."""
    import engine.host_loop as hl
    from engine.host_loop import _BridgeCamera
    monkeypatch.setattr(hl, "_BRIDGE_CAMERA_EYE", (1.0, 2.0, 3.0))
    assert _BridgeCamera()._eye_offset() == (1.0, 2.0, 3.0)
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `uv run pytest tests/host/test_bridge_camera.py::test_eye_offset_reads_module_global -q`
Expected: FAIL with `AttributeError: ... has no attribute '_BRIDGE_CAMERA_EYE'`.

- [ ] **Step 3: Replace the hardcoded offsets with module globals.**

In `engine/host_loop.py`, **delete** the `_BRIDGE_CAMERA_OFFSETS` dict and the `_CURRENT_BRIDGE_NAME` global (the block around lines 777-793 that defines `_BRIDGE_CAMERA_OFFSETS` and `_CURRENT_BRIDGE_NAME`), and **replace** it with:

```python
# Captain's-chair eye position + zoom params, taken from the SDK
# ZoomCameraObjectClass ("maincamera") at mission load (see
# _after_mission_loaded). Defaults are GalaxyBridge's create-time values; the
# host overwrites them per bridge — config-driven, replacing the old hardcoded
# _BRIDGE_CAMERA_OFFSETS table. The zoom params are FOV multipliers + seconds
# consumed by _BridgeCamera's zoom state machine.
_BRIDGE_CAMERA_EYE: tuple = (0.683736, 86.978439, 50.0)
_BRIDGE_ZOOM_MIN: float = 1.0     # SDK GetMinZoom — zoomed-in FOV factor
_BRIDGE_ZOOM_MAX: float = 1.0     # SDK GetMaxZoom — captain FOV factor
_BRIDGE_ZOOM_TIME: float = 0.0    # SDK GetZoomTime — ease duration (seconds)
```

- [ ] **Step 4: Rewrite `_BridgeCamera._eye_offset`.**

**Replace** the current `_eye_offset` (which reads `_BRIDGE_CAMERA_OFFSETS.get(_CURRENT_BRIDGE_NAME, self.DEFAULT_BRIDGE_OFFSET)`) with:

```python
    def _eye_offset(self) -> tuple:
        """Captain's-chair eye, taken from the SDK maincamera at mission load
        (module global _BRIDGE_CAMERA_EYE), config-driven for every bridge."""
        return _BRIDGE_CAMERA_EYE
```

(Leave the `DEFAULT_BRIDGE_OFFSET` class constant in place — harmless — or delete it if unused after this; grep `DEFAULT_BRIDGE_OFFSET` first and only remove it if no other reference exists.)

- [ ] **Step 5: Cache the SDK camera in `_after_mission_loaded`.**

In `engine/host_loop.py`, in `_after_mission_loaded`, **replace** the config-name caching block:
```python
            global _CURRENT_BRIDGE_NAME
            import App as _App
            _bridge = _App.g_kSetManager.GetSet("bridge")
            if _bridge is not None and hasattr(_bridge, "GetConfig"):
                _name = _bridge.GetConfig() or ""
                if _name:
                    _CURRENT_BRIDGE_NAME = _name
```
with:
```python
            # Step 5a: take the captain's-chair eye + zoom params from the SDK
            # maincamera (config-driven; replaces the hardcoded offsets table).
            global _BRIDGE_CAMERA_EYE, _BRIDGE_ZOOM_MIN, _BRIDGE_ZOOM_MAX, _BRIDGE_ZOOM_TIME
            import App as _App
            _bridge = _App.g_kSetManager.GetSet("bridge")
            _cam = _bridge.GetCamera("maincamera") if _bridge is not None else None
            if _cam is not None and hasattr(_cam, "position"):
                _BRIDGE_CAMERA_EYE = _cam.position
                _BRIDGE_ZOOM_MIN = _cam.GetMinZoom()
                _BRIDGE_ZOOM_MAX = _cam.GetMaxZoom()
                _BRIDGE_ZOOM_TIME = _cam.GetZoomTime()
```

> `_bridge` is still defined here for the realize calls that follow. If `_realize_bridge_model`/`_realize_viewscreen` referenced the old local `_bridge`, they re-fetch the set themselves — confirm by reading; this block keeps `_bridge` defined regardless.

- [ ] **Step 6: Clean up stale references.**

Grep `engine/host_loop.py` for `_CURRENT_BRIDGE_NAME` and `_BRIDGE_CAMERA_OFFSETS` — there should be NO remaining references after Steps 3-5 (the only consumer was `_eye_offset`). Remove any leftover comments mentioning them. In `tests/host/test_bridge_camera.py`, the docstring of `test_camera_anchored_at_bridge_local_offset` mentions `_CURRENT_BRIDGE_NAME` — update it to say `_BRIDGE_CAMERA_EYE`.

Run: `cd /Users/mward/Documents/Projects/bc_dauntless && grep -n "_CURRENT_BRIDGE_NAME\|_BRIDGE_CAMERA_OFFSETS" engine/host_loop.py`
Expected: no output (all removed).

- [ ] **Step 7: Run the camera tests.**

Run: `uv run pytest tests/host/test_bridge_camera.py -q`
Expected: PASS (existing tests + the new `test_eye_offset_reads_module_global`).

- [ ] **Step 8: Commit.**

```bash
git add engine/host_loop.py tests/host/test_bridge_camera.py
git commit -m "feat(bridge): captain eye from the SDK maincamera, not a hardcoded table (step 5a)

_after_mission_loaded reads the realized ZoomCameraObjectClass position +
zoom params into module globals; _BridgeCamera._eye_offset returns the
SDK position (config-driven for every bridge). Deletes
_BRIDGE_CAMERA_OFFSETS and the now-orphaned _CURRENT_BRIDGE_NAME.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `_BridgeCamera` zoom state machine + per-frame FOV

**Files:**
- Modify: `engine/host_loop.py` (`_BridgeCamera.__init__`, `apply`, `compute_camera`; render-block call site ~3029-3049)
- Test: `tests/host/test_bridge_camera.py` (update unpacking), `tests/unit/test_bridge_camera_zoom.py` (new)

- [ ] **Step 1: Write the failing zoom test.**

Create `tests/unit/test_bridge_camera_zoom.py`:

```python
"""_BridgeCamera zoom-into-officer state machine (step 5a). Pure unit — drives
set_zoom_target/compute_camera with module-global zoom params injected."""
import math
import pytest

import engine.host_loop as hl
from engine.host_loop import _BridgeCamera

_SAVED = {}


def setup_function(_):
    for k in ("_BRIDGE_CAMERA_EYE", "_BRIDGE_ZOOM_MIN", "_BRIDGE_ZOOM_MAX",
              "_BRIDGE_ZOOM_TIME"):
        _SAVED[k] = getattr(hl, k)
    hl._BRIDGE_CAMERA_EYE = (0.0, 0.0, 0.0)
    hl._BRIDGE_ZOOM_MIN = 0.64
    hl._BRIDGE_ZOOM_MAX = 1.0
    hl._BRIDGE_ZOOM_TIME = 0.375


def teardown_function(_):
    for k, v in _SAVED.items():
        setattr(hl, k, v)


def test_captain_view_when_no_target():
    bc = _BridgeCamera()
    eye, target, up, fov = bc.compute_camera()
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD)         # max_zoom == 1.0
    assert len((eye, target, up, fov)) == 4


def test_full_zoom_points_at_target_and_narrows_fov():
    bc = _BridgeCamera()
    # Drive the ease to completion (dt >> zoom_time clamps _zoom_t to 1.0).
    bc.set_zoom_target((10.0, 0.0, 0.0), dt=10.0)
    eye, target, up, fov = bc.compute_camera()
    fwd = (target[0] - eye[0], target[1] - eye[1], target[2] - eye[2])
    fl = math.sqrt(sum(c * c for c in fwd))
    assert (fwd[0] / fl, fwd[1] / fl, fwd[2] / fl) == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD * 0.64)


def test_deselect_eases_back_to_captain_view():
    bc = _BridgeCamera()
    bc.set_zoom_target((10.0, 0.0, 0.0), dt=10.0)   # zoomed in
    bc.set_zoom_target(None, dt=10.0)               # eased fully back
    _, _, _, fov = bc.compute_camera()
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD)


def test_mouse_look_suspended_while_zooming():
    bc = _BridgeCamera()
    bc.set_zoom_target((10.0, 0.0, 0.0), dt=10.0)
    y0 = bc.yaw_rad
    bc.apply(100.0, 50.0)                            # ignored while zoomed
    assert bc.yaw_rad == y0


def test_zoom_t_clamps_to_unit_interval():
    bc = _BridgeCamera()
    bc.set_zoom_target((10.0, 0.0, 0.0), dt=100.0)
    assert bc._zoom_t == 1.0
    bc.set_zoom_target(None, dt=100.0)
    assert bc._zoom_t == 0.0
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `uv run pytest tests/unit/test_bridge_camera_zoom.py -q`
Expected: FAIL — `compute_camera` returns 3 values (unpack error) and `set_zoom_target` doesn't exist.

- [ ] **Step 3: Add zoom state + helpers to `_BridgeCamera.__init__`.**

In `_BridgeCamera.__init__` (after `self.pitch_rad = 0.0`), add:

```python
        # Zoom-into-officer state (step 5a). _zoom_t eases 0 (captain view) ->
        # 1 (framed on officer). _zoom_target_world is the look-at point (kept
        # during ease-out until _zoom_t returns to 0). _zoom_active = a target
        # is currently selected.
        self._zoom_t = 0.0
        self._zoom_active = False
        self._zoom_target_world = None
```

Add two static helpers to the class (anywhere in the class body):

```python
    @staticmethod
    def _smoothstep(t: float) -> float:
        return t * t * (3.0 - 2.0 * t)

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * t

    def set_zoom_target(self, world_xyz, dt: float) -> None:
        """Select (world_xyz != None) or deselect (None) an officer to zoom
        onto; advance the ease by dt at rate 1/zoom_time, clamped to [0, 1].
        Mouse-look is suspended whenever a zoom is in progress (see apply)."""
        self._zoom_active = world_xyz is not None
        if world_xyz is not None:
            self._zoom_target_world = world_xyz
        step = dt / max(_BRIDGE_ZOOM_TIME, 1e-6)
        if self._zoom_active:
            self._zoom_t = min(1.0, self._zoom_t + step)
        else:
            self._zoom_t = max(0.0, self._zoom_t - step)
            if self._zoom_t == 0.0:
                self._zoom_target_world = None
```

- [ ] **Step 4: Suspend mouse-look during zoom in `apply`.**

At the top of `_BridgeCamera.apply` (before the yaw/pitch accumulation), add:

```python
        # Mouse-look is frozen while a zoom is in progress or held — the camera
        # is framing the officer; it resumes only at the full captain view.
        if self._zoom_t > 0.0 or self._zoom_active:
            return
```

- [ ] **Step 5: Make `compute_camera` return `(eye, target, up, fov)` with the zoom blend.**

**Replace** the body of `compute_camera` with (keeps the captain-basis math, then blends toward the officer + narrows FOV):

```python
    def compute_camera(self) -> tuple:
        """Return (eye, target, up, fov_y_rad). Captain view is mouse-look at
        the SDK eye + base FOV. When an officer is selected the look direction
        eases toward that officer's world position and the FOV narrows toward
        FOV_Y_RAD * min_zoom, both over the SDK zoom time. The camera never
        leaves the chair (eye is fixed)."""
        local_fwd = (0.0, 1.0, 0.0)   # bridge-local +Y
        local_up  = (0.0, 0.0, 1.0)   # bridge-local +Z

        local_fwd = _rot_around(local_fwd, (0.0, 0.0, 1.0), self.yaw_rad)
        right = (
            local_fwd[1]*local_up[2] - local_fwd[2]*local_up[1],
            local_fwd[2]*local_up[0] - local_fwd[0]*local_up[2],
            local_fwd[0]*local_up[1] - local_fwd[1]*local_up[0],
        )
        rlen = _math.sqrt(right[0]**2 + right[1]**2 + right[2]**2)
        if rlen > 1e-6:
            right = (right[0]/rlen, right[1]/rlen, right[2]/rlen)
            local_fwd = _rot_around(local_fwd, right, self.pitch_rad)
            local_up  = _rot_around(local_up,  right, self.pitch_rad)

        eye = self._eye_offset()
        fov = self.FOV_Y_RAD * _BRIDGE_ZOOM_MAX

        if self._zoom_t > 0.0 and self._zoom_target_world is not None:
            e = self._smoothstep(self._zoom_t)
            dx = self._zoom_target_world[0] - eye[0]
            dy = self._zoom_target_world[1] - eye[1]
            dz = self._zoom_target_world[2] - eye[2]
            dl = _math.sqrt(dx*dx + dy*dy + dz*dz)
            if dl > 1e-6:
                ofwd = (dx/dl, dy/dl, dz/dl)
                bx = self._lerp(local_fwd[0], ofwd[0], e)
                by = self._lerp(local_fwd[1], ofwd[1], e)
                bz = self._lerp(local_fwd[2], ofwd[2], e)
                bl = _math.sqrt(bx*bx + by*by + bz*bz)
                if bl > 1e-6:
                    local_fwd = (bx/bl, by/bl, bz/bl)
            fov = self.FOV_Y_RAD * self._lerp(_BRIDGE_ZOOM_MAX, _BRIDGE_ZOOM_MIN, e)

        target = (eye[0] + local_fwd[0], eye[1] + local_fwd[1], eye[2] + local_fwd[2])
        return eye, target, local_up, fov
```

- [ ] **Step 6: Run the zoom test.**

Run: `uv run pytest tests/unit/test_bridge_camera_zoom.py -q`
Expected: PASS (5 tests).

- [ ] **Step 7: Update the existing camera test for the 4-tuple.**

In `tests/host/test_bridge_camera.py`:
- `test_camera_anchored_at_bridge_local_offset`: change `eye, target, up = bc.compute_camera()` to `eye, target, up, _fov = bc.compute_camera()`.
- `test_yaw_rotates_forward_in_xy_plane`: change `eye, target, _ = bc.compute_camera()` to `eye, target, _up, _fov = bc.compute_camera()`.
- (`test_compute_camera_takes_no_ship_args` calls `bc.compute_camera()` without unpacking — leave it.)

Run: `uv run pytest tests/host/test_bridge_camera.py -q`
Expected: PASS.

- [ ] **Step 8: Wire the 4-tuple + per-frame FOV into the render block (zoom target = None for now).**

In `engine/host_loop.py`, in the bridge-view render block, **replace**:
```python
                    if not pause.is_open:
                        bridge_camera.apply(mouse_dx, mouse_dy)
                    b_eye, b_target, b_up = bridge_camera.compute_camera()
                    b_eye, b_target, b_up = camera_shake.perturb(b_eye, b_target, b_up)
                    r.set_bridge_camera(
                        eye=b_eye, target=b_target, up=b_up,
                        fov_y_rad=_BridgeCamera.FOV_Y_RAD,
                        near=_BridgeCamera.NEAR,
                        far=_BridgeCamera.FAR,
                    )
```
with (Task 4 replaces the `None` with the real officer resolution):
```python
                    if not pause.is_open:
                        bridge_camera.set_zoom_target(None, _player_dt)
                        bridge_camera.apply(mouse_dx, mouse_dy)
                    b_eye, b_target, b_up, b_fov = bridge_camera.compute_camera()
                    b_eye, b_target, b_up = camera_shake.perturb(b_eye, b_target, b_up)
                    r.set_bridge_camera(
                        eye=b_eye, target=b_target, up=b_up,
                        fov_y_rad=b_fov,
                        near=_BridgeCamera.NEAR,
                        far=_BridgeCamera.FAR,
                    )
```

- [ ] **Step 9: Run the camera tests once more (no regression).**

Run: `uv run pytest tests/host/test_bridge_camera.py tests/unit/test_bridge_camera_zoom.py -q`
Expected: PASS (all).

- [ ] **Step 10: Commit.**

```bash
git add engine/host_loop.py tests/host/test_bridge_camera.py tests/unit/test_bridge_camera_zoom.py
git commit -m "feat(bridge): _BridgeCamera zoom-into-officer state machine + per-frame FOV (step 5a)

compute_camera now returns (eye, target, up, fov); when an officer is
selected the look direction eases toward their world position and the FOV
narrows toward base*min_zoom over the SDK zoom time, eye fixed at the
chair. Mouse-look frozen while zooming. Render block passes the live FOV.
Target wiring (active officer) lands in the next task — set to None here.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Active-officer resolution + wiring

**Files:**
- Modify: `engine/ui/crew_menu_panel.py` (`open_menu_label` accessor)
- Modify: `engine/host_loop.py` (`_active_zoom_officer_world` helper; render-block target)
- Test: `tests/unit/test_active_zoom_officer.py` (new)

- [ ] **Step 1: Write the failing tests.**

Create `tests/unit/test_active_zoom_officer.py`:

```python
"""Resolve the open crew-menu officer to a world-space look-at point (step 5a)."""
import engine.host_loop as hl
from engine.host_loop import _active_zoom_officer_world


class _FakePanel:
    def __init__(self, label):
        self._label = label
    def open_menu_label(self):
        return self._label


class _FakeOfficer:
    def __init__(self, iid):
        self._render_instance = iid


class _FakeRenderer:
    def __init__(self, bounds):
        self._bounds = bounds
    def get_instance_bounds(self, iid):
        return self._bounds


def test_resolves_open_menu_officer_to_world_centre(monkeypatch):
    monkeypatch.setattr(
        "engine.ui.crew_menu_hotkeys.resolve_character",
        lambda label: _FakeOfficer(42) if label == "Tactical" else None)
    r = _FakeRenderer((1.0, 2.0, 3.0, 9.0))
    assert _active_zoom_officer_world(_FakePanel("Tactical"), r) == (1.0, 2.0, 3.0)


def test_none_when_no_menu_open():
    assert _active_zoom_officer_world(_FakePanel(None), _FakeRenderer(None)) is None


def test_none_when_label_resolves_to_no_officer(monkeypatch):
    monkeypatch.setattr("engine.ui.crew_menu_hotkeys.resolve_character",
                        lambda label: None)
    assert _active_zoom_officer_world(_FakePanel("Tactical"),
                                      _FakeRenderer((1, 2, 3, 4))) is None


def test_none_when_officer_has_no_instance(monkeypatch):
    monkeypatch.setattr("engine.ui.crew_menu_hotkeys.resolve_character",
                        lambda label: _FakeOfficer(None))
    assert _active_zoom_officer_world(_FakePanel("Tactical"),
                                      _FakeRenderer((1, 2, 3, 4))) is None


def test_none_when_bounds_unavailable(monkeypatch):
    monkeypatch.setattr("engine.ui.crew_menu_hotkeys.resolve_character",
                        lambda label: _FakeOfficer(7))
    assert _active_zoom_officer_world(_FakePanel("Tactical"),
                                      _FakeRenderer(None)) is None


def test_none_when_panel_missing():
    assert _active_zoom_officer_world(None, _FakeRenderer((1, 2, 3, 4))) is None
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `uv run pytest tests/unit/test_active_zoom_officer.py -q`
Expected: FAIL — `_active_zoom_officer_world` doesn't exist.

- [ ] **Step 3: Add `open_menu_label` to `CrewMenuPanel`.**

In `engine/ui/crew_menu_panel.py`, add a method (next to `has_open_menu`):

```python
    def open_menu_label(self) -> Optional[str]:
        """Label of the open top-level (station) menu, or None. The open id is
        always a top-level menu (toggle_menu only fires for titles), so its
        root is itself; the label feeds crew_menu_hotkeys.resolve_character."""
        if self._open_menu_id is None:
            return None
        root = self._root_of(self._open_menu_id)
        return root.GetLabel() if root is not None else None
```

- [ ] **Step 4: Add the `_active_zoom_officer_world` helper.**

In `engine/host_loop.py`, add a module-level function (near `_BridgeCamera`):

```python
def _active_zoom_officer_world(crew_menu_panel, r):
    """World-space centre (x, y, z) of the officer whose crew menu is open, or
    None. Resolves the open menu's label -> bridge CharacterClass (via
    crew_menu_hotkeys.resolve_character) -> its step-4 render instance ->
    get_instance_bounds. Any missing hop -> None (captain view, no zoom)."""
    if crew_menu_panel is None:
        return None
    label = crew_menu_panel.open_menu_label()
    if not label:
        return None
    from engine.ui import crew_menu_hotkeys
    off = crew_menu_hotkeys.resolve_character(label)
    if off is None:
        return None
    iid = getattr(off, "_render_instance", None)
    if iid is None:
        return None
    bounds = r.get_instance_bounds(iid)
    if not bounds:
        return None
    return (bounds[0], bounds[1], bounds[2])
```

- [ ] **Step 5: Run the helper tests.**

Run: `uv run pytest tests/unit/test_active_zoom_officer.py -q`
Expected: PASS (6 tests).

- [ ] **Step 6: Wire the real target into the render block.**

In `engine/host_loop.py`, in the bridge-view render block, **replace** the Task 3 placeholder line:
```python
                        bridge_camera.set_zoom_target(None, _player_dt)
```
with:
```python
                        bridge_camera.set_zoom_target(
                            _active_zoom_officer_world(crew_menu_panel, r),
                            _player_dt)
```

> Confirm `crew_menu_panel` is in scope at this point (it is created before the main loop, ~`crew_menu_panel = CrewMenuPanel()`). If it is created conditionally and might be undefined, guard with `getattr`/a local default; do NOT silently swallow — if it's genuinely not in scope, report it.

- [ ] **Step 7: Run the touched tests.**

Run: `uv run pytest tests/unit/test_active_zoom_officer.py tests/host/test_bridge_camera.py tests/unit/test_bridge_camera_zoom.py -q`
Expected: PASS (all).

- [ ] **Step 8: Commit.**

```bash
git add engine/ui/crew_menu_panel.py engine/host_loop.py tests/unit/test_active_zoom_officer.py
git commit -m "feat(bridge): zoom onto the officer whose crew menu is open (step 5a)

Add CrewMenuPanel.open_menu_label + _active_zoom_officer_world (open menu
label -> bridge character -> step-4 render instance -> world centre), and
feed it to _BridgeCamera.set_zoom_target each bridge frame. F1-F5 now zoom
the captain camera onto each officer from the chair.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Focused suite check + live-verify handoff

**Files:** none (verification only)

- [ ] **Step 1: Run all touched tests together.**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py tests/integration/test_sdk_bridge_load.py tests/host/test_bridge_camera.py tests/unit/test_bridge_camera_zoom.py tests/unit/test_active_zoom_officer.py -q`
Expected: PASS (all). **Do NOT run the bare `uv run pytest`.**

- [ ] **Step 2: Regression guard (steps 3–5c bridge path).**

Run: `uv run pytest tests/unit/test_realize_viewscreen.py tests/integration/test_officer_placement_sdk.py -q`
Expected: PASS.

- [ ] **Step 3: Hand off to Mark for live verification.**

Mark drives all visual verification (no synthetic desktop input / full-screen capture). Pure Python — no rebuild; just run `./build/dauntless`. Ask him to:
1. Enter a mission, switch to bridge view — the captain eye sits at the faithful z≈61.93 (slightly higher than before).
2. Press F1–F5 — the camera stays at the chair but rotates onto each officer and narrows FOV (zoom-into-officer), eased smoothly.
3. Close the menu / ESC — the camera eases back to the captain view and mouse-look resumes.
4. Confirm no crash; the on-exit `[BRIDGE-STUB] SUMMARY` lists **no bridge-load stubs** (the bridge load is fully SDK-driven).

Note: the zoom geometry (rotate-to-look-at + FOV-narrow) is our faithful reconstruction; every number (eye, min zoom, zoom time) is the SDK's. Off-axis officers (e.g. Engineer) may swing the look hard — tune the ease/clamp by feel if needed.

---

## Self-Review

**Spec coverage:**
- `ZoomCameraObjectClass` real (position/orientation/zoom params); Create + GetObject off the summary → Task 1. ✓
- Captain eye from SDK camera, config-driven, delete `_BRIDGE_CAMERA_OFFSETS`/`_CURRENT_BRIDGE_NAME` → Task 2. ✓
- Zoom-into-officer: eye fixed, eased look-at + FOV narrow toward officer world centre, SDK-parameterized; mouse-look suspended → Task 3. ✓
- Trigger = open crew menu; `open_menu_label` + `_active_zoom_officer_world` via `resolve_character` + `get_instance_bounds` → Task 4. ✓
- Orientation stays mouse-look (decision A) — no SDK-orientation adoption anywhere. ✓
- Integration: position 61.93, zoom params, empty bridge-stub summary → Task 1. ✓
- Pure Python / no rebuild → no cmake steps. ✓
- Live verify → Task 5. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; every `Run:` has explicit path + expected result. ✓

**Type consistency:** `ZoomCameraObjectClass.position`/`orientation`/`GetMinZoom`/`GetMaxZoom`/`GetZoomTime`/`SetTranslateXYZ`; module globals `_BRIDGE_CAMERA_EYE`/`_BRIDGE_ZOOM_MIN`/`_BRIDGE_ZOOM_MAX`/`_BRIDGE_ZOOM_TIME`; `_BridgeCamera.set_zoom_target`/`_zoom_t`/`_zoom_active`/`_zoom_target_world`/`_smoothstep`/`_lerp`; `compute_camera` 4-tuple consistently unpacked at the render site and in tests; `CrewMenuPanel.open_menu_label`; `_active_zoom_officer_world(crew_menu_panel, r)`; `resolve_character` returns a character object with `_render_instance`; `get_instance_bounds` → `(cx,cy,cz,radius)`. All names match across tasks. ✓
