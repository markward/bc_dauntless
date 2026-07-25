# Bridge-camera "stand up" persistence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make E1M1's captain "stand up" camera pose persist through the Picard/Saffi walk-on and XO introduction instead of snapping back to the seated eye the instant the stand-up clip finishes.

**Architecture:** Layer a mode-stack-gated *held pose* on top of the existing baked seated-eye path in `_BridgeCamera`. When a bridge camera animation completes, latch its final pose instead of clearing it; `compute_camera` returns that held pose only while the seated captain mode (`GalaxyBridgeCaptain`, a `PlaceByDirectionMode`) is absent from the live maincamera's mode stack, and reverts to the normal seated eye the moment the SDK re-pushes it (`ResetBridgeCamera`). The seated path stays byte-identical.

**Tech Stack:** Python 3 (headless engine), pytest. No native/C++ changes. No renderer changes.

## Global Constraints

- Shared checkout: commit with **explicit pathspecs only** — never `git add -A` / `git add .` / `git checkout` / `git restore` / `git stash` / `git reset --hard`. (`CLAUDE.md` "Shared checkout" rule.)
- The normal (non-cutscene) seated bridge view must remain behaviourally unchanged. The held pose activates ONLY when a held pose is latched AND the seated captain mode is off the stack.
- The seated captain mode is `CameraModes.GalaxyBridgeCaptain`, built via `App.CameraMode_Create("PlaceByDirection", ...)` → `engine.appc.camera_modes.PlaceByDirectionMode` (`sdk/Build/scripts/CameraModes.py:353`).
- `BridgeCutsceneController` is bridge-only (it calls `view_mode.set_bridge()`); do NOT touch in-space cutscene cameras (`engine/appc/camera_modes.py` mode-stack + `_CameraDirector`).
- The live maincamera is reachable from `_BridgeCamera` via the existing `_zoom_cam()` → module global `hl._BRIDGE_ZOOM_CAM` (set at load, `engine/host_loop.py:5934`). No new wiring is needed.
- Test gate: `scripts/check_tests.sh` (pytest + ctest), green except entries already in `tests/known_failures.txt`.
- This is a camera/render change: green tests cannot confirm it looks right. Live in-game verification by Mark is required before claiming done (`CLAUDE.md` test-gate + memory "Green tests cannot see asset paths").

---

### Task 1: `_BridgeCamera` gains a mode-stack-gated held pose

**Files:**
- Modify: `engine/host_loop.py` — `_BridgeCamera.__init__` (~line 2560), add two methods near `clear_anim_pose` (~line 2628), and the head of `compute_camera` (~line 2653).
- Test: `tests/unit/test_bridge_camera_held_pose.py` (create)

**Interfaces:**
- Consumes: `hl._BRIDGE_ZOOM_CAM` (a `ZoomCameraObjectClass` or `None`); `hl._BRIDGE_CAMERA_EYE`, `hl._BRIDGE_ZOOM_MAX`; `_BridgeCamera._zoom_cam()` (existing static returning `_BRIDGE_ZOOM_CAM`); `ZoomCameraObjectClass.GetCurrentCameraMode()` / `PushCameraMode(mode)` (`engine/appc/bridge_set.py`); `engine.appc.camera_modes.PlaceByDirectionMode`.
- Produces:
  - `_BridgeCamera.hold_anim_pose() -> None` — latches `self._anim_pose` into `self._held_pose` and sets `self._anim_pose = None`.
  - `_BridgeCamera._seated_mode_active() -> bool` — True iff the live maincamera's top-of-stack mode is a `PlaceByDirectionMode`.
  - `_BridgeCamera._held_pose` attribute: `None` or `((ex,ey,ez),(tx,ty,tz),(ux,uy,uz))`.
  - `compute_camera()` return contract unchanged: `(eye, target, up, fov_y_rad)`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bridge_camera_held_pose.py`:

```python
"""_BridgeCamera held-pose persistence: a completed bridge camera animation
holds its final pose while the seated captain mode (GalaxyBridgeCaptain,
a PlaceByDirectionMode) is popped off the live maincamera's mode stack, and
reverts to the baked seated eye the moment that mode is re-pushed.

See docs/superpowers/specs/2026-07-25-bridge-camera-stand-persistence-design.md.
"""
import pytest

import engine.host_loop as hl
from engine.host_loop import _BridgeCamera
from engine.appc.bridge_set import ZoomCameraObjectClass
from engine.appc.camera_modes import PlaceByDirectionMode

_SAVED = {}

_STAND = ((1.0, 2.0, 3.0), (1.0, 2.0, 4.0), (0.0, 0.0, 1.0))


def _make_cam():
    c = ZoomCameraObjectClass(0, 0, 0, 1, 0, 0, 0, "maincamera")
    c.SetMinZoom(0.64); c.SetMaxZoom(1.0); c.SetZoomTime(0.375)
    return c


def setup_function(_):
    for k in ("_BRIDGE_CAMERA_EYE", "_BRIDGE_CAMERA_MOVE", "_BRIDGE_ZOOM_MIN",
              "_BRIDGE_ZOOM_MAX", "_BRIDGE_ZOOM_TIME", "_BRIDGE_ZOOM_CAM"):
        _SAVED[k] = getattr(hl, k)
    hl._BRIDGE_CAMERA_EYE = (0.0, 0.0, 0.0)   # baked seated eye = origin in this fixture
    hl._BRIDGE_CAMERA_MOVE = None
    hl._BRIDGE_ZOOM_MIN = 0.64
    hl._BRIDGE_ZOOM_MAX = 1.0
    hl._BRIDGE_ZOOM_TIME = 0.375
    hl._BRIDGE_ZOOM_CAM = _make_cam()         # empty mode stack => seated mode absent


def teardown_function(_):
    for k, v in _SAVED.items():
        setattr(hl, k, v)


def test_hold_anim_pose_latches_final_and_clears_transient():
    bc = _BridgeCamera()
    bc.set_anim_pose(*_STAND)
    bc.hold_anim_pose()
    assert bc._anim_pose is None
    assert bc._held_pose == _STAND


def test_held_pose_used_when_seated_mode_absent():
    # Seated captain mode is NOT on the (empty) stack: the standing pose governs.
    bc = _BridgeCamera()
    bc.set_anim_pose(*_STAND)
    bc.hold_anim_pose()
    eye, target, up, fov = bc.compute_camera()
    assert eye == (1.0, 2.0, 3.0)
    assert target == (1.0, 2.0, 4.0)
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD * hl._BRIDGE_ZOOM_MAX)


def test_held_pose_discarded_when_seated_mode_present():
    # ResetBridgeCamera re-pushes GalaxyBridgeCaptain: revert to the seated eye.
    bc = _BridgeCamera()
    bc.set_anim_pose(*_STAND)
    bc.hold_anim_pose()
    hl._BRIDGE_ZOOM_CAM.PushCameraMode(PlaceByDirectionMode("PlaceByDirection"))
    eye, _target, _up, fov = bc.compute_camera()
    assert eye == (0.0, 0.0, 0.0)          # baked seated eye, NOT the held (1,2,3)
    assert bc._held_pose is None           # stale latch dropped
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD)


def test_no_held_pose_uses_seated_eye():
    # Regression guard: normal seated view is untouched.
    bc = _BridgeCamera()
    eye, _target, _up, fov = bc.compute_camera()
    assert eye == (0.0, 0.0, 0.0)
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_camera_held_pose.py -v`
Expected: FAIL — `test_hold_anim_pose_latches_final_and_clears_transient` errors with `AttributeError: '_BridgeCamera' object has no attribute 'hold_anim_pose'` (and the held-pose tests fail because `compute_camera` has no held-pose branch).

- [ ] **Step 3: Add `_held_pose` to `_BridgeCamera.__init__`**

In `engine/host_loop.py`, in `_BridgeCamera.__init__` (~line 2569), immediately after `self._anim_pose = None`, add:

```python
        # Persistent post-animation pose. A completed bridge camera clip latches
        # its final pose here (hold_anim_pose); compute_camera returns it while
        # the seated captain mode is popped off the maincamera stack, and drops
        # it when ResetBridgeCamera re-pushes that mode. See
        # docs/superpowers/specs/2026-07-25-bridge-camera-stand-persistence-design.md.
        self._held_pose = None
```

- [ ] **Step 4: Add `hold_anim_pose` and `_seated_mode_active`**

In `engine/host_loop.py`, directly after `clear_anim_pose` (~line 2629), add:

```python
    def hold_anim_pose(self) -> None:
        """Latch the current (final) cutscene pose as the persistent held pose
        and end the active override. Called by BridgeCutsceneController when a
        bridge camera clip completes: the pose survives (via compute_camera)
        until the SDK re-pushes the seated captain mode (ResetBridgeCamera)."""
        self._held_pose = self._anim_pose
        self._anim_pose = None

    def _seated_mode_active(self) -> bool:
        """True when the live maincamera's top-of-stack mode is the seated
        captain mode (a PlaceByDirectionMode). BC pops it (PopCameraMode) before
        a stand and re-pushes it (ResetBridgeCamera) to re-seat; while it is
        absent, a completed camera animation's held pose governs the view."""
        cam = self._zoom_cam()
        get = getattr(cam, "GetCurrentCameraMode", None)
        if not callable(get):
            return False
        from engine.appc.camera_modes import PlaceByDirectionMode
        return isinstance(get(), PlaceByDirectionMode)
```

- [ ] **Step 5: Add the held-pose branch to `compute_camera`**

In `engine/host_loop.py`, in `compute_camera` (~lines 2653-2655), immediately after the existing `_anim_pose` early-return block:

```python
        if self._anim_pose is not None:
            eye, target, up = self._anim_pose
            return eye, target, up, self.FOV_Y_RAD * _BRIDGE_ZOOM_MAX
```

insert:

```python
        if self._held_pose is not None:
            if self._seated_mode_active():
                self._held_pose = None          # seated mode restored: drop the latch
            else:
                eye, target, up = self._held_pose
                return eye, target, up, self.FOV_Y_RAD * _BRIDGE_ZOOM_MAX
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_camera_held_pose.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Run neighbouring camera tests (no regression in the seated/zoom path)**

Run: `uv run pytest tests/unit/test_bridge_camera_zoom.py tests/host/test_bridge_camera.py -v`
Expected: PASS (unchanged).

- [ ] **Step 8: Commit**

```bash
git add engine/host_loop.py tests/unit/test_bridge_camera_held_pose.py
git commit -m "feat(bridge): held camera pose gated by seated-mode stack

_BridgeCamera latches a completed cutscene clip's final pose and returns it
from compute_camera while the seated captain mode (PlaceByDirectionMode) is
absent from the maincamera stack, reverting to the baked seated eye when it is
re-pushed. Seated view unchanged when no pose is held.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `BridgeCutsceneController` holds the final pose instead of clearing it

**Files:**
- Modify: `engine/bridge_cutscene.py:130` — the camera-completion branch in `_update_camera`.
- Modify: `tests/unit/test_bridge_cutscene.py` — add `hold_anim_pose` to `_FakeCamera`; update the existing completion assertion; add a completion-holds test.

**Interfaces:**
- Consumes: `_BridgeCamera.hold_anim_pose()` (from Task 1).
- Produces: no new public interface. Behaviour change: on camera-clip completion the controller calls `bridge_camera.hold_anim_pose()` (was `clear_anim_pose()`).

- [ ] **Step 1: Update the fake camera and the existing completion test (RED)**

In `tests/unit/test_bridge_cutscene.py`, in `_FakeCamera` (~lines 15-27):

- Add to `__init__` (after `self.cleared = False`):

```python
        self.held = None
```

- Add a method (after `clear_anim_pose`):

```python
    def hold_anim_pose(self):
        self.held = self.pose
        self.pose = None
```

Then, in `test_camera_path_drives_pose_and_completes_at_duration`, replace the final assertion block (currently lines ~108-111):

```python
    # Reaching duration completes the action and clears the pose.
    ctrl.update(0.5, **_ctx(cam, vm, rend, mgr))
    assert action.completed is True
    assert cam.cleared is True
```

with (the `_FakeRenderer` clip is a +X slide ending at eye = (10,0,0) with identity rotation; equality on the eye X is exact — linear interp at t == duration returns the final key verbatim — so no float tolerance is needed here):

```python
    # Reaching duration completes the action and HOLDS the final pose (it
    # persists until the SDK re-pushes the seated captain mode); not cleared.
    ctrl.update(0.5, **_ctx(cam, vm, rend, mgr))
    assert action.completed is True
    assert cam.cleared is False
    assert cam.held is not None
    assert cam.held[0][0] == 10.0        # final eye X (end of the +X slide)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest "tests/unit/test_bridge_cutscene.py::test_camera_path_drives_pose_and_completes_at_duration" -v`
Expected: FAIL — controller still calls `clear_anim_pose()`, so `cam.cleared is False` fails (and `cam.held` is `None`).

- [ ] **Step 3: Switch the controller from clear to hold**

In `engine/bridge_cutscene.py`, in `_update_camera`, change the completion branch (~lines 129-132):

```python
        if ac["t"] >= ac["duration"]:
            bridge_camera.clear_anim_pose()
            ac["action"].Completed()
            self._active_camera = None
```

to:

```python
        if ac["t"] >= ac["duration"]:
            # Hold the clip's final pose rather than clearing it: for the walk-on
            # and the sit the final keyframe IS the seated eye and _BridgeCamera
            # gates the held pose off (seated mode present), so nothing changes;
            # for the stand (seated mode popped at E1M1 PicardWalkOn) the standing
            # pose persists until ResetBridgeCamera re-pushes the seated mode.
            bridge_camera.hold_anim_pose()
            ac["action"].Completed()
            self._active_camera = None
```

Also update the class docstring line that says the tick "drives _BridgeCamera, completing the action when the clip ends" is unaffected; no other edit needed.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest "tests/unit/test_bridge_cutscene.py::test_camera_path_drives_pose_and_completes_at_duration" -v`
Expected: PASS.

- [ ] **Step 5: Add a focused completion-holds test**

In `tests/unit/test_bridge_cutscene.py`, after the updated test, add:

```python
def test_camera_completion_holds_not_clears():
    """On clip completion the controller latches the final pose via
    hold_anim_pose (persistence) and never falls back to clear_anim_pose."""
    ctrl = BridgeCutsceneController()
    action = _FakeAction()
    ctrl.request_camera_path(action, _FakeNode("camera"), "WalkCameraToCaptD")

    cam, vm, rend, mgr = _FakeCamera(), _FakeViewMode(), _FakeRenderer(), _FakeAnimMgr()
    ctrl.update(0.0, **_ctx(cam, vm, rend, mgr))     # load + t=0
    ctrl.update(1.0, **_ctx(cam, vm, rend, mgr))     # reach duration

    assert action.completed is True
    assert cam.held is not None       # final pose latched
    assert cam.pose is None           # transient override ended
    assert cam.cleared is False       # NOT the old clear path
```

- [ ] **Step 6: Run the whole cutscene test module**

Run: `uv run pytest tests/unit/test_bridge_cutscene.py -v`
Expected: PASS (all tests, including the two updated/added).

- [ ] **Step 7: Commit**

```bash
git add engine/bridge_cutscene.py tests/unit/test_bridge_cutscene.py
git commit -m "feat(bridge): hold final cutscene pose on completion (stand-up persists)

BridgeCutsceneController now latches the final camera pose via hold_anim_pose
instead of clear_anim_pose when a bridge camera clip ends. Walk-on/sit are
unchanged (their final keyframe is the seated eye and _BridgeCamera gates the
held pose off while the seated mode is present); the E1M1 captain stand-up now
persists through the Picard/Saffi walk-on and XO intro.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Final verification (after both tasks)

- [ ] **Run the full gate**

Run: `scripts/check_tests.sh`
Expected: green — no failure outside `tests/known_failures.txt` (the 7 baselined headless-GL FrameTests). If a new failure appears, it is a regression from this change; fix it before proceeding.

- [ ] **Live in-game verification (Mark)**

Build + run, load E1M1 (`--developer` → mission picker if needed), and watch the Briefing → PicardWalkOn beat:
- The camera stands up as Picard enters and **stays** standing through Picard's line and Saffi's walk-on to the helm and the XO introduction.
- When `DBCaptainSit` plays later, the camera sits back down cleanly to the normal seated eye with mouse-look restored (no jump, no stuck standing pose).

This visual confirmation is the acceptance gate — green tests alone are not sufficient for a camera/render change.
```
