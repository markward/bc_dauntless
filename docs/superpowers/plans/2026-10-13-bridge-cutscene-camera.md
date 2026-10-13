# Bridge Cutscene Camera Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `PlacementWatch` aimed at the bridge set drives the bridge camera, so mission cutscenes that cut to the bridge (E6M1's opening, 18 missions) render the bridge interior instead of space.

**Architecture:** `_active_cutscene_camera()` stops treating the bridge set as an exterior camera source. A new `_bridge_cutscene_camera()` finds a live `PlacementMode` on the bridge set's active camera; a new `_sync_bridge_mode_pose()` feeds its pose into a new `_mode_pose` slot on `_BridgeCamera`, which `compute_camera()` honours below the walk-on clip pose and above the held/captain view.

**Tech Stack:** Python 3 (engine shim), pytest. No C++ changes.

**Spec:** `docs/superpowers/specs/2026-10-13-bridge-cutscene-camera-design.md`

## Global Constraints

- Work on branch `fix/bridge-cutscene-camera`. Never commit to `main`.
- Shared checkout: NEVER run `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit pathspecs only. To mutate a file temporarily, back it up with `cp` and restore with `cp`, then `diff` to prove the restore.
- Run tests with `uv run pytest ...` from the project root.
- Every test that adds a `"bridge"` set uses the `bridge_slot` fixture (Task 1) so the prior `"bridge"` set and rendered-set name are restored.
- `_cutscene_pose(mode, dt, pose_of=None)` already exists in `engine/host_loop.py` and returns `(eye, look_at_point, up)`; reuse it, do not re-implement the direction→point conversion.
- In-space cutscene behaviour must not change: all existing tests in `tests/host/test_cutscene_camera_selection.py` and `tests/host/test_cutscene_camera_override.py` must keep passing unmodified.
- Final gate: `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`).

## Review Focus

1. **Pause mid-shot** — the bridge view must hold the current shot, not snap to the captain view or keep advancing. Pinned in Task 3 (`test_sync_paused_leaves_slot_untouched`).
2. **Mission swap mid-shot** — the next mission must not open on a stale cutscene pose. Pinned in Task 2 (`test_reset_cutscene_pose_clears_mode_pose`).
3. **Placement shot while a walk-on camera clip is playing** — the clip keeps priority. Pinned in Task 2 (`test_anim_pose_outranks_mode_pose`).
4. **Missing placement or dead target** — fall back to the normal captain view, no exception. Pinned in Task 1 (`test_bridge_cutscene_camera_none_for_invalid_placement`).
5. **A live exterior (space) cutscene camera while the bridge also holds a placement mode** — exterior wins, the bridge slot is cleared. Pinned in Task 3 (`test_sync_clears_when_exterior_active`).

---

### Task 1: Route cutscene cameras by set

**Files:**
- Modify: `engine/host_loop.py` — `_active_cutscene_camera()` (currently ~line 7960) and add `_bridge_cutscene_camera()` directly after it.
- Create: `tests/host/test_bridge_cutscene_camera.py`

**Interfaces:**
- Consumes: `App.g_kSetManager.get_explicit_rendered_set()`, `BridgeSet` (`engine/appc/bridge_set.py`), `PlacementMode` (`engine/appc/camera_modes.py`).
- Produces: `_bridge_cutscene_camera() -> tuple | None` returning `(camera, mode)` where `mode` is a valid `PlacementMode`; and `_active_cutscene_camera()` now returns `None` (from its rendered-set branch) when the explicitly rendered set is the bridge. Also the test fixture `bridge_slot` and helper `_bridge_with_shot(cam_name="CutsceneCam")` in the new test file, used by Tasks 2-3.

- [ ] **Step 1: Write the failing tests**

Create `tests/host/test_bridge_cutscene_camera.py`:

```python
# tests/host/test_bridge_cutscene_camera.py
"""A PlacementWatch aimed at the BRIDGE set drives the bridge camera, not the
exterior view. Spec: docs/superpowers/specs/2026-10-13-bridge-cutscene-camera-design.md"""
import pytest

import App
import Camera
from engine.appc.bridge_set import BridgeSet_Create, CameraObjectClass_Create
from engine.appc.camera_modes import PlacementMode
from engine.appc.math import TGPoint3
from engine.host_loop import _active_cutscene_camera, _bridge_cutscene_camera


@pytest.fixture
def bridge_slot():
    """Restore whatever "bridge" set and rendered-set name existed before."""
    mgr = App.g_kSetManager
    prior = mgr.GetSet("bridge")
    prior_rendered = mgr._rendered_set_name
    yield
    mgr.DeleteSet("bridge")
    if prior is not None:
        mgr.AddSet(prior, "bridge")
    mgr._rendered_set_name = prior_rendered


def _bridge_with_shot(cam_name="CutsceneCam", shoot=True):
    """A bridge set whose active camera `cam_name` holds a PlacementWatch from
    "ShotCam" at "Shot Head" (bridge-local coords, like E6M1's FelixCam2)."""
    b = BridgeSet_Create()
    App.g_kSetManager.AddSet(b, "bridge")
    eye = App.Waypoint_Create("ShotCam", "bridge", None)
    eye.SetTranslate(TGPoint3(-35.0, -142.0, 45.0))
    head = App.Waypoint_Create("Shot Head", "bridge", None)
    head.SetTranslate(TGPoint3(-25.0, -60.0, 60.0))
    cam = CameraObjectClass_Create(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, cam_name)
    b.AddCameraToSet(cam, cam_name)
    b.SetActiveCamera(cam_name)
    if shoot:
        # PlacementWatch("bridge", "Shot Head", "ShotCam") -> bSweep=0, bReplace=1
        Camera.Placement("ShotCam", "Shot Head", "bridge", 0, 1)
    return b, cam, eye, head


def test_exterior_camera_ignores_rendered_bridge_set(bridge_slot):
    # E6M1: ChangeRenderedSet("bridge") + PlacementWatch on the bridge. Today
    # this returns the bridge camera and the host draws SPACE through it.
    _bridge_with_shot()
    App.g_kSetManager.MakeRenderedSet("bridge")
    assert _active_cutscene_camera() is None


def test_bridge_cutscene_camera_finds_placement_on_cutscene_cam(bridge_slot):
    b, cam, eye, head = _bridge_with_shot()
    got = _bridge_cutscene_camera()
    assert got is not None
    assert got[0] is cam
    assert isinstance(got[1], PlacementMode)


def test_bridge_cutscene_camera_finds_placement_on_maincamera(bridge_slot):
    # E4M4 MissionFailDialog: PlacementWatch with no CutsceneCameraBegin lands
    # on the bridge's own maincamera.
    b, cam, eye, head = _bridge_with_shot(cam_name="maincamera")
    got = _bridge_cutscene_camera()
    assert got is not None and got[0] is cam


def test_bridge_cutscene_camera_works_without_rendered_bridge(bridge_slot):
    # E3M2 BerkeleyIntro & 5 others never ChangeRenderedSet("bridge").
    _bridge_with_shot()
    App.g_kSetManager.MakeRenderedSet("__some_space_set__")
    assert _bridge_cutscene_camera() is not None


def test_bridge_cutscene_camera_none_for_non_placement_mode(bridge_slot):
    # Only PlacementMode counts. A VALID non-Placement mode on the bridge
    # camera (ZoomTarget: real camera action, never aimed at the bridge by any
    # SDK mission) must be rejected by the TYPE gate. (The Galaxy seated
    # GalaxyBridgeCaptain mode is a PlaceByDirection attr bag whose IsValid()
    # is always 0 in our shim, so it cannot pin the type gate -- hence
    # ZoomTarget here.)
    b, cam, eye, head = _bridge_with_shot(shoot=False)
    Camera.ZoomTarget("ShotCam", "Shot Head", "bridge", 0, 1)
    assert cam.GetCurrentCameraMode().IsValid()      # precondition
    assert _bridge_cutscene_camera() is None


def test_bridge_cutscene_camera_none_for_invalid_placement(bridge_slot):
    b, cam, eye, head = _bridge_with_shot(shoot=False)
    mode = cam.GetNamedCameraMode("Placement")      # no Source => invalid
    cam.PushCameraMode(mode)
    assert _bridge_cutscene_camera() is None


def test_bridge_cutscene_camera_none_without_bridge_set(bridge_slot):
    App.g_kSetManager.DeleteSet("bridge")
    assert _bridge_cutscene_camera() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/host/test_bridge_cutscene_camera.py -v`
Expected: collection ERROR — `ImportError: cannot import name '_bridge_cutscene_camera' from 'engine.host_loop'`.

- [ ] **Step 3: Implement**

In `engine/host_loop.py`, inside `_active_cutscene_camera()`, change the rendered-set branch so it skips the bridge set:

```python
    rendered = _App.g_kSetManager.get_explicit_rendered_set()
    if rendered is not None and _is_bridge_set(rendered):
        # A bridge-set camera is a BRIDGE shot, not an exterior one: it is
        # handled by _bridge_cutscene_camera() and drives the bridge camera.
        rendered = None
    if rendered is not None:
```

(leave the rest of the function, including the cinematic-mode branch, unchanged), and add these two functions directly after `_active_cutscene_camera()`:

```python
def _is_bridge_set(pSet) -> bool:
    """The same bridge test _resolve_active_set uses."""
    from engine.appc.bridge_set import BridgeSet
    return isinstance(pSet, BridgeSet) or pSet.GetName() == "bridge"


def _bridge_cutscene_camera():
    """(camera, mode) when the bridge set's active camera holds a live
    PlacementMode, else None.

    Every SDK camera action aimed at the bridge is PlacementWatch or
    PlacementOffsetWatch (223 uses, 18 missions) and both build a
    PlacementMode. Gating on the mode TYPE -- not on the camera or the rendered
    set -- covers shots on a CutsceneCameraBegin camera and on the bridge
    maincamera alike (E4M4 MissionFailDialog), and shots in cutscenes that never
    ChangeRenderedSet("bridge") (E3M2 BerkeleyIntro), while never matching the
    Galaxy seated GalaxyBridgeCaptain mode. Bridge placements are bridge-local
    render coordinates (Player Cam == the maincamera == the captain eye), so the
    pose needs no conversion. Spec 2026-10-13-bridge-cutscene-camera-design."""
    import App as _App
    from engine.appc.camera_modes import PlacementMode
    bridge = _App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        return None
    get_active = getattr(bridge, "GetActiveCamera", None)
    cam = get_active() if callable(get_active) else None
    if cam is None:
        return None
    get_mode = getattr(cam, "GetCurrentCameraMode", None)
    mode = get_mode() if callable(get_mode) else None
    if isinstance(mode, PlacementMode) and mode.IsValid():
        return (cam, mode)
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/host/test_bridge_cutscene_camera.py tests/host/test_cutscene_camera_selection.py tests/host/test_cutscene_camera_override.py -v`
Expected: all PASS.

(Verified while planning: `Camera.Placement` / `Camera.ZoomTarget` on a `BridgeSet_Create()` set registered as `"bridge"` with `Waypoint_Create(..., "bridge", None)` waypoints yield a valid `PlacementMode` / `ZoomTargetMode` on the active camera — both for a camera named `"CutsceneCam"` and one named `"maincamera"`; a bare `GetNamedCameraMode("Placement")` is a `PlacementMode` with `IsValid() == 0`; `DeleteSet` on a missing set does not raise.)

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_bridge_cutscene_camera.py
git commit -m "fix(camera): bridge-set placement cameras are bridge shots, not exterior

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `_BridgeCamera` mode-pose slot

**Files:**
- Modify: `engine/host_loop.py` — `class _BridgeCamera` (~line 3816): `__init__`, new `set_mode_pose` / `clear_mode_pose`, `reset_cutscene_pose`, `apply`, `compute_camera`.
- Test: `tests/unit/test_bridge_camera_mode_pose.py` (create)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `_BridgeCamera.set_mode_pose(eye, target, up) -> None`, `_BridgeCamera.clear_mode_pose() -> None`, attribute `_mode_pose` (tuple of three 3-tuples, or `None`). Precedence in `compute_camera()`: `_anim_pose` → `_mode_pose` → held pose → captain view.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_bridge_camera_mode_pose.py`:

```python
# tests/unit/test_bridge_camera_mode_pose.py
"""_BridgeCamera's mode-pose slot: a bridge PlacementWatch shot.
Spec: docs/superpowers/specs/2026-10-13-bridge-cutscene-camera-design.md §3.2"""
import engine.host_loop as hl
from engine.host_loop import _BridgeCamera

SHOT = ((-35.0, -142.0, 45.0), (-25.0, -60.0, 60.0), (0.0, 0.0, 1.0))


def test_mode_pose_overrides_captain_view():
    cam = _BridgeCamera()
    cam.set_mode_pose(*SHOT)
    eye, target, up, fov = cam.compute_camera()
    assert (eye, target, up) == SHOT
    assert fov == _BridgeCamera.FOV_Y_RAD * hl._BRIDGE_ZOOM_MAX


def test_clear_mode_pose_restores_captain_view():
    cam = _BridgeCamera()
    base = cam.compute_camera()
    cam.set_mode_pose(*SHOT)
    cam.clear_mode_pose()
    assert cam.compute_camera() == base


def test_mode_pose_freezes_mouse_look():
    cam = _BridgeCamera()
    cam.set_mode_pose(*SHOT)
    before = (cam.yaw_rad, cam.pitch_rad)
    cam.apply(100.0, 100.0)
    assert (cam.yaw_rad, cam.pitch_rad) == before


def test_anim_pose_outranks_mode_pose():
    cam = _BridgeCamera()
    cam.set_mode_pose(*SHOT)
    clip = ((1.0, 2.0, 3.0), (1.0, 3.0, 3.0), (0.0, 0.0, 1.0))
    cam.set_anim_pose(*clip)
    eye, target, up, _ = cam.compute_camera()
    assert (eye, target, up) == clip


def test_hold_anim_pose_does_not_latch_mode_pose():
    cam = _BridgeCamera()
    cam.set_mode_pose(*SHOT)
    cam.hold_anim_pose()               # no clip active: latches None
    cam.clear_mode_pose()
    assert cam._held_pose is None


def test_reset_cutscene_pose_clears_mode_pose():
    cam = _BridgeCamera()
    base = cam.compute_camera()
    cam.set_mode_pose(*SHOT)
    cam.reset_cutscene_pose()          # mission swap
    assert cam.compute_camera() == base
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_bridge_camera_mode_pose.py -v`
Expected: FAIL — `AttributeError: '_BridgeCamera' object has no attribute 'set_mode_pose'`.

- [ ] **Step 3: Implement**

In `_BridgeCamera.__init__`, after `self._held_pose = None`, add:

```python
        # Bridge cutscene SHOT: the pose of a live PlacementMode on the bridge
        # set's active camera (PlacementWatch "bridge"), fed every frame by
        # host_loop._sync_bridge_mode_pose. Ranks below a walk-on camera clip
        # (_anim_pose) and above the held/captain view; never latched by
        # hold_anim_pose. Spec 2026-10-13-bridge-cutscene-camera-design.
        self._mode_pose = None
```

After `clear_anim_pose`, add:

```python
    def set_mode_pose(self, eye, target, up) -> None:
        """Override the camera with a bridge cutscene shot (bridge-local)."""
        self._mode_pose = (tuple(eye), tuple(target), tuple(up))

    def clear_mode_pose(self) -> None:
        self._mode_pose = None
```

In `reset_cutscene_pose`, add `self._mode_pose = None` alongside the two existing clears.

In `apply`, change the first guard to:

```python
        if self._anim_pose is not None or self._mode_pose is not None:
            return
```

In `compute_camera`, directly after the existing `_anim_pose` early return, add:

```python
        if self._mode_pose is not None:
            eye, target, up = self._mode_pose
            return eye, target, up, self.FOV_Y_RAD * _BRIDGE_ZOOM_MAX
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_bridge_camera_mode_pose.py tests/unit/test_bridge_camera_anim.py tests/unit/test_bridge_camera_held_pose.py tests/unit/test_bridge_camera_zoom.py tests/unit/test_bridge_camera_zoom_lift.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/unit/test_bridge_camera_mode_pose.py
git commit -m "feat(bridge): _BridgeCamera mode-pose slot for bridge cutscene shots

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Feed the shot into the bridge camera each frame

**Files:**
- Modify: `engine/host_loop.py` — add `_sync_bridge_mode_pose()` after `_bridge_cutscene_camera()`; call it at the top of the `if view_mode.is_bridge:` render block (~line 11910, the block that calls `cutscene.update(...)`).
- Modify: `tests/host/test_bridge_cutscene_camera.py` (append)

**Interfaces:**
- Consumes: `_bridge_cutscene_camera()` (Task 1), `_BridgeCamera.set_mode_pose` / `clear_mode_pose` (Task 2), existing `_cutscene_pose(mode, dt, pose_of=None) -> (eye, look_at, up)`.
- Produces: `_sync_bridge_mode_pose(bridge_camera, dt, *, exterior_active: bool, paused: bool) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/host/test_bridge_cutscene_camera.py`:

```python
from engine.host_loop import _BridgeCamera, _sync_bridge_mode_pose


def test_sync_sets_bridge_pose_from_shot(bridge_slot):
    _bridge_with_shot()
    cam = _BridgeCamera()
    _sync_bridge_mode_pose(cam, 0.0, exterior_active=False, paused=False)
    eye, target, up, _ = cam.compute_camera()
    assert eye == (-35.0, -142.0, 45.0)              # at ShotCam
    # looking from ShotCam toward Shot Head (+X, +Y, +Z)
    assert target[0] > eye[0] and target[1] > eye[1] and target[2] > eye[2]


def test_sync_clears_when_shot_ends(bridge_slot):
    b, cam_obj, eye, head = _bridge_with_shot()
    cam = _BridgeCamera()
    base = cam.compute_camera()
    _sync_bridge_mode_pose(cam, 0.0, exterior_active=False, paused=False)
    App.g_kSetManager.DeleteSet("bridge")            # shot gone (camera removed)
    _sync_bridge_mode_pose(cam, 0.0, exterior_active=False, paused=False)
    assert cam.compute_camera() == base


def test_sync_clears_when_exterior_active(bridge_slot):
    _bridge_with_shot()
    cam = _BridgeCamera()
    cam.set_mode_pose((9.0, 9.0, 9.0), (9.0, 10.0, 9.0), (0.0, 0.0, 1.0))
    base_cam = _BridgeCamera()
    _sync_bridge_mode_pose(cam, 0.0, exterior_active=True, paused=False)
    assert cam.compute_camera() == base_cam.compute_camera()


def test_sync_paused_leaves_slot_untouched(bridge_slot):
    _bridge_with_shot()
    cam = _BridgeCamera()
    held = ((1.0, 1.0, 1.0), (1.0, 2.0, 1.0), (0.0, 0.0, 1.0))
    cam.set_mode_pose(*held)
    _sync_bridge_mode_pose(cam, 0.0, exterior_active=False, paused=True)
    eye, target, up, _ = cam.compute_camera()
    assert (eye, target, up) == held
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/host/test_bridge_cutscene_camera.py -v`
Expected: collection ERROR — `ImportError: cannot import name '_sync_bridge_mode_pose'`.

- [ ] **Step 3: Implement the helper**

Add after `_bridge_cutscene_camera()` in `engine/host_loop.py`:

```python
def _sync_bridge_mode_pose(bridge_camera, dt, *, exterior_active, paused) -> None:
    """Feed a live bridge PlacementWatch shot into the bridge camera's
    mode-pose slot, or clear it. Paused: leave the slot alone so the shot holds.
    An exterior cutscene camera owning the frame clears it (exterior wins)."""
    if paused:
        return
    bcc = None if exterior_active else _bridge_cutscene_camera()
    if bcc is None:
        bridge_camera.clear_mode_pose()
        return
    eye, target, up = _cutscene_pose(bcc[1], dt)
    bridge_camera.set_mode_pose(eye, target, up)
```

- [ ] **Step 4: Wire the call site**

In the render loop, find the block that starts:

```python
                if view_mode.is_bridge:
                    import App as _App
                    if not pause.sim_frozen:
                        # CAMERA half only — the door half (_update_doors) is
```

and insert the call as the block's first statement:

```python
                if view_mode.is_bridge:
                    import App as _App
                    # Bridge cutscene SHOT (PlacementWatch "bridge"): drive the
                    # bridge camera from it -- see _bridge_cutscene_camera.
                    _sync_bridge_mode_pose(bridge_camera, _player_dt,
                                           exterior_active=_cc is not None,
                                           paused=pause.sim_frozen)
                    if not pause.sim_frozen:
```

`_cc` is the value computed earlier in the same frame (`_cc = None if pause.sim_frozen else _active_cutscene_camera()`); do not recompute it.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/host/test_bridge_cutscene_camera.py tests/host/test_cutscene_camera_selection.py tests/host/test_cutscene_camera_override.py tests/unit/test_bridge_camera_mode_pose.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/host/test_bridge_cutscene_camera.py
git commit -m "fix(camera): drive the bridge camera from bridge PlacementWatch shots

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Headless E6M1 end-to-end

**Files:**
- Create: `tests/integration/test_e6m1_bridge_cutscene_camera.py`

**Interfaces:**
- Consumes: `_active_cutscene_camera()`, `_bridge_cutscene_camera()`, `_sync_bridge_mode_pose()` (Tasks 1, 3), `_BridgeCamera` (Task 2), `tests.helpers.headless_mission` (`load`, `tick_until`, fixture `no_logged_failures`).
- Produces: nothing.

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_e6m1_bridge_cutscene_camera.py
"""E6M1's opening briefing cuts from Starbase 12 to the bridge
(ChangeRenderedSet("bridge") + PlacementWatch("bridge", "Felix Head",
"FelixCam2"), E6M1.py:1663-1708). The bridge shot must drive the bridge camera
and must not be treated as an exterior camera.
Spec: docs/superpowers/specs/2026-10-13-bridge-cutscene-camera-design.md §4"""
import math

import App
from engine.host_loop import (
    _BridgeCamera, _active_cutscene_camera, _bridge_cutscene_camera,
    _sync_bridge_mode_pose,
)
from tests.helpers import headless_mission as hm
from tests.helpers.headless_mission import no_logged_failures  # noqa: F401


def _on_bridge_shot():
    rs = App.g_kSetManager.get_explicit_rendered_set()
    return (rs is not None and rs.GetName() == "bridge"
            and _bridge_cutscene_camera() is not None)


def test_e6m1_briefing_cuts_to_the_bridge(no_logged_failures):
    hm.load("Maelstrom.Episode6.E6M1.E6M1")
    hm.tick_until(_on_bridge_shot, bound_s=90)

    assert _active_cutscene_camera() is None          # not an exterior shot

    cam = _BridgeCamera()
    _sync_bridge_mode_pose(cam, 0.0, exterior_active=False, paused=False)
    eye, target, _up, _fov = cam.compute_camera()

    bridge = App.g_kSetManager.GetSet("bridge")
    src = bridge.GetObject("FelixCam2").GetWorldLocation()
    head = bridge.GetObject("Felix Head").GetWorldLocation()
    assert math.isclose(eye[0], src.x, abs_tol=1e-4)
    assert math.isclose(eye[1], src.y, abs_tol=1e-4)
    assert math.isclose(eye[2], src.z, abs_tol=1e-4)
    # forward points at Felix Head
    f = [target[i] - eye[i] for i in range(3)]
    d = [head.x - eye[0], head.y - eye[1], head.z - eye[2]]
    nf = math.sqrt(sum(c * c for c in f))
    nd = math.sqrt(sum(c * c for c in d))
    assert sum(f[i] * d[i] for i in range(3)) / (nf * nd) > 0.999


def test_e6m1_briefing_releases_the_bridge_camera(no_logged_failures):
    hm.load("Maelstrom.Episode6.E6M1.E6M1")
    hm.tick_until(_on_bridge_shot, bound_s=90)
    hm.tick_until(lambda: _bridge_cutscene_camera() is None, bound_s=120)
    cam = _BridgeCamera()
    base = cam.compute_camera()
    cam.set_mode_pose((1.0, 1.0, 1.0), (1.0, 2.0, 1.0), (0.0, 0.0, 1.0))
    _sync_bridge_mode_pose(cam, 0.0, exterior_active=False, paused=False)
    assert cam.compute_camera() == base               # captain view back
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/integration/test_e6m1_bridge_cutscene_camera.py -v`
Expected: both PASS (Tasks 1-3 already implement the behaviour; this pins it end to end against the real SDK mission).

Prove it guards the fix: back up `engine/host_loop.py` (`cp engine/host_loop.py /tmp/hl_bak.py`), delete the three lines Task 1 added to `_active_cutscene_camera()` (the `_is_bridge_set` guard), re-run — `test_e6m1_briefing_cuts_to_the_bridge` must FAIL on `assert _active_cutscene_camera() is None`. Restore with `cp /tmp/hl_bak.py engine/host_loop.py` and `diff engine/host_loop.py /tmp/hl_bak.py` (no output).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_e6m1_bridge_cutscene_camera.py
git commit -m "test(camera): E6M1 briefing cuts to the bridge, headless end to end

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. Any failure named under "NEW FAILURES" is a regression to fix before reporting done; do not baseline it.
