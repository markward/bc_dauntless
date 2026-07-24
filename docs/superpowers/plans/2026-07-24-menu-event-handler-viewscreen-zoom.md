# MenuEventHandler Port — Bridge-Camera Viewscreen/Officer Zoom — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconstruct `CharacterClass::MenuEventHandler` so the bridge camera zooms (FOV-narrows) onto an engaged character — an officer talk-menu OR a viewscreen hail — with the zoom state living on `ZoomCameraObjectClass`, closing the E1M1 Liu viewscreen-zoom gap.

**Architecture:** `ZoomCameraObjectClass` becomes a real zoom-state machine (direction flag + eased progress `_zoom_t` + active factor + look-at). `CharacterClass.MenuEventHandler` reconciles that camera to an engaged/disengaged state. The host loop drives it each bridge frame from one precedence-ordered resolver (watch > officer-menu > viewscreen-hail). `_BridgeCamera` reads the camera object and applies the existing eased-forward + FOV-narrow geometry. The ad-hoc `set_zoom_target`/`_active_zoom_officer` path is retired.

**Tech Stack:** Python 3.11 (engine), pytest. No C++/native changes, no cmake reconfigure. Spec: `docs/superpowers/specs/2026-07-24-menu-event-handler-viewscreen-zoom-design.md`.

## Global Constraints

- **Shared checkout / worktree:** never run `git checkout -- <path>`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`/`git add .`. Stage with explicit pathspecs only. (CLAUDE.md)
- **Game units:** all spatial values are GU; never introduce `*_m`/`*_mps` names. Zoom factors are dimensionless FOV multipliers. (engine/units.py)
- **Rotation convention:** column-vector, right-handed; world-forward = `GetCol(1)`. Do not read rows. (CLAUDE.md)
- **Officer regression bar:** the live-verified crew-menu officer zoom must stay behavior-identical — same head-centre look-at, same 0.375 s ease, same `_BRIDGE_ZOOM_MIN`=0.64 fallback. Any test that exercised it must still assert the same framing after the cutover.
- **Freeze under pause:** the zoom transition advances on `_player_dt` (0 while `pause.sim_frozen`), NOT wall/game time — so it freezes under pause/DevTools like the letterbox.
- **Test gate:** `scripts/check_tests.sh` (pytest + ctest) must show no new failures vs `tests/known_failures.txt`. Never eyeball "pre-existing".
- **Concrete SDK values:** `SetMinZoom(0.64)`, `SetMaxZoom(1.0)`, `SetZoomTime(0.375)` (GalaxyBridge/SovereignBridge), harvested at `host_loop.py:5875-5877`. `POSITION_ZOOM_SENTINEL = 1.0`.
- **Stubs telemetry:** `CharacterClass.__getattr__` raises `AttributeError` on `_`-prefixed names; real methods must be defined, not left to the data-bag fallback.

---

## File Structure

- **`engine/appc/bridge_set.py`** — `ZoomCameraObjectClass` gains the real zoom-state machine (Task 1). Owns: `_is_zoomed`, `_zoom_t`, `_active_factor`, `_look_at`, `_min_zoom`, `_max_zoom`, `_zoom_time`; methods `engage`/`disengage`/`advance`/`IsZoomed`/`ToggleZoom`/`LookForward`/`UpdateViewFrustum`.
- **`engine/appc/characters.py`** — `CharacterClass.MenuEventHandler` (Task 2): the SDK-surface dispatcher that fetches the bridge maincamera and engages/disengages it.
- **`engine/appc/character_position_zoom.py`** — `_VIEWSCREEN_ZOOM_FALLBACK` constant (Task 4).
- **`engine/host_loop.py`** — harvest `_BRIDGE_ZOOM_CAM`; `_BridgeCamera.compute_camera`/`apply` read the camera object; the per-frame engagement resolver + `MenuEventHandler` call + `cam.advance`; the new viewscreen-hail producer. Retire `set_zoom_target` + the `_active_zoom_officer_world` thin wrapper; **keep** `_active_zoom_officer` and `_officer_zoom_factor` (the resolver reuses them — same officer behavior, less churn than inlining per spec §3.4) (Tasks 3 & 4).
- **Tests:** `tests/appc/test_zoom_camera_object.py` (new, Task 1), `tests/appc/test_menu_event_handler.py` (new, Task 2), rewrite `tests/unit/test_bridge_camera_zoom.py` (Task 3), `tests/host/test_viewscreen_hail_zoom.py` (new, Task 4).

---

## Task 1: `ZoomCameraObjectClass` zoom-state machine

**Files:**
- Modify: `engine/appc/bridge_set.py:128-173` (the `ZoomCameraObjectClass` class body)
- Test: `tests/appc/test_zoom_camera_object.py` (create)

**Interfaces:**
- Produces:
  - `ZoomCameraObjectClass.engage(factor: float, look_at: tuple|None) -> None` — set the active target factor + look-at world point (or `None`=forward) and mark zoom direction "in".
  - `ZoomCameraObjectClass.disengage() -> None` — mark zoom direction "out".
  - `ZoomCameraObjectClass.advance(dt: float) -> None` — step `_zoom_t` toward 1 (in) / 0 (out) at rate `1/effective_zoom_time`, clamp `[0,1]`; when `_zoom_t` reaches 0, clear `_look_at`.
  - `ZoomCameraObjectClass.IsZoomed() -> int` — the direction flag (1 while engaged).
  - `ZoomCameraObjectClass.zoom_progress() -> float` — current `_zoom_t` in `[0,1]`.
  - `ZoomCameraObjectClass.active_factor` / `.look_at` — read by `_BridgeCamera`.
  - `ZoomCameraObjectClass.ToggleZoom(t=None)`, `.LookForward()`, `.UpdateViewFrustum()` — SDK surface.
  - Module const `_ZOOM_DEFAULT_TIME = 0.375` (pre-`SetZoomTime` fallback so `advance` never divides toward a snap).

- [ ] **Step 1: Write the failing tests**

Create `tests/appc/test_zoom_camera_object.py`:

```python
"""ZoomCameraObjectClass zoom-state machine (MenuEventHandler port)."""
import pytest
from engine.appc.bridge_set import ZoomCameraObjectClass


def _cam():
    # (x,y,z, qw,qx,qy,qz, name) — args mirror ZoomCameraObjectClass_Create.
    c = ZoomCameraObjectClass(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, "maincamera")
    c.SetMinZoom(0.64)
    c.SetMaxZoom(1.0)
    c.SetZoomTime(0.375)
    return c


def test_starts_disengaged():
    c = _cam()
    assert c.IsZoomed() == 0
    assert c.zoom_progress() == 0.0
    assert c.look_at is None


def test_engage_sets_factor_lookat_and_direction():
    c = _cam()
    c.engage(0.5, (1.0, 2.0, 3.0))
    assert c.IsZoomed() == 1
    assert c.active_factor == pytest.approx(0.5)
    assert c.look_at == (1.0, 2.0, 3.0)


def test_advance_eases_in_over_zoom_time_and_clamps():
    c = _cam()
    c.engage(0.5, None)
    c.advance(0.375 / 2)          # half the ease time
    assert c.zoom_progress() == pytest.approx(0.5, abs=1e-6)
    c.advance(10.0)               # overshoot clamps to 1.0
    assert c.zoom_progress() == 1.0


def test_disengage_eases_back_to_zero_and_clears_lookat():
    c = _cam()
    c.engage(0.5, (1.0, 0.0, 0.0))
    c.advance(10.0)               # fully in
    c.disengage()
    c.advance(10.0)               # fully out
    assert c.zoom_progress() == 0.0
    assert c.IsZoomed() == 0
    assert c.look_at is None      # cleared when _zoom_t hits 0


def test_mid_transition_reverse_resumes_from_current_progress():
    c = _cam()
    c.engage(0.5, None)
    c.advance(0.375 * 0.4)        # 40% in
    p = c.zoom_progress()
    c.disengage()                 # reverse mid-transition
    c.advance(0.375 * 0.1)        # step out a little
    assert c.zoom_progress() == pytest.approx(p - 0.1, abs=1e-6)  # smooth, no snap


def test_zero_zoom_time_falls_back_to_default_not_snap():
    c = ZoomCameraObjectClass(0, 0, 0, 1, 0, 0, 0, "maincamera")  # never SetZoomTime
    c.engage(0.5, None)
    c.advance(0.375 / 2)          # half of the DEFAULT 0.375, not an instant snap
    assert c.zoom_progress() == pytest.approx(0.5, abs=1e-6)


def test_lookforward_clears_lookat():
    c = _cam()
    c.engage(0.5, (1.0, 2.0, 3.0))
    c.LookForward()
    assert c.look_at is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd <worktree> && uv run pytest tests/appc/test_zoom_camera_object.py -q`
Expected: FAIL (`engage`/`advance`/`zoom_progress`/`active_factor` not defined; the class is a `_LoudStub`).

- [ ] **Step 3: Implement the state machine**

In `engine/appc/bridge_set.py`, add near the top of the module (after imports):

```python
_ZOOM_DEFAULT_TIME = 0.375   # BC SetZoomTime on Galaxy/Sovereign maincamera;
                             # pre-SetZoomTime fallback so advance() never snaps.
```

In `ZoomCameraObjectClass.__init__` (currently ends at the `self._mode_stack = []` line), append the runtime zoom state:

```python
        # Zoom-state machine (MenuEventHandler port). _is_zoomed is the direction
        # (in/out); _zoom_t eases 0->1 while in, 1->0 while out; _active_factor is
        # the target FOV multiplier for the current engagement (does NOT clobber
        # _min_zoom, which stays the SetMinZoom default = the officer sentinel
        # fallback); _look_at is the world aim point, or None = base-forward.
        self._is_zoomed = False
        self._zoom_t = 0.0
        self._active_factor = self._min_zoom
        self._look_at = None
```

Add methods to the class (after `SetTranslateXYZ`, before the camera-mode stack section):

```python
    # ── Zoom-state machine (read by host _BridgeCamera) ─────────────────────────
    @property
    def active_factor(self) -> float:
        return self._active_factor

    @property
    def look_at(self):
        return self._look_at

    def engage(self, factor, look_at) -> None:
        """Zoom in toward `factor` (FOV multiplier) aiming at `look_at`
        (world xyz, or None = base-forward). Idempotent: re-engaging just
        updates the target; the ease continues from the current progress."""
        self._active_factor = float(factor)
        self._look_at = tuple(look_at) if look_at is not None else None
        self._is_zoomed = True

    def disengage(self) -> None:
        """Zoom back out to the captain view; _look_at is kept until the ease
        reaches 0 (so the eye eases back along the same line)."""
        self._is_zoomed = False

    def advance(self, dt) -> None:
        eff = self._zoom_time if self._zoom_time > 0.0 else _ZOOM_DEFAULT_TIME
        step = dt / max(eff, 1e-6)
        if self._is_zoomed:
            self._zoom_t = min(1.0, self._zoom_t + step)
        else:
            self._zoom_t = max(0.0, self._zoom_t - step)
            if self._zoom_t == 0.0:
                self._look_at = None

    def zoom_progress(self) -> float:
        return self._zoom_t

    def IsZoomed(self) -> int:
        return 1 if self._is_zoomed else 0

    def ToggleZoom(self, t=None) -> None:
        # SDK surface: flip the zoom direction. Our host drives engage/disengage
        # directly; this keeps MissionLib/SDK ToggleZoom callers from no-op'ing.
        if self._is_zoomed:
            self.disengage()
        else:
            self._is_zoomed = True

    def LookForward(self) -> None:
        # SDK surface (MissionLib.ViewscreenOn / LookForward): aim at the
        # viewscreen (base-forward). Was a silent _LoudStub no-op.
        self._look_at = None

    def UpdateViewFrustum(self) -> None:
        # SDK surface: the frustum is realized by _BridgeCamera.compute_camera
        # each frame; this exists so SDK callers stop hitting the _LoudStub.
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd <worktree> && uv run pytest tests/appc/test_zoom_camera_object.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/bridge_set.py tests/appc/test_zoom_camera_object.py
git commit -m "feat(bridge): ZoomCameraObjectClass zoom-state machine (was _LoudStub no-op)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `CharacterClass.MenuEventHandler`

**Files:**
- Modify: `engine/appc/characters.py` (add method to `CharacterClass`, near `MenuUp`/`MenuDown` ~1224-1288)
- Test: `tests/appc/test_menu_event_handler.py` (create)

**Interfaces:**
- Consumes: `ZoomCameraObjectClass.engage/disengage` (Task 1); `App.g_kSetManager.GetSet("bridge").GetCamera("maincamera")`.
- Produces: `CharacterClass.MenuEventHandler(engaged: bool, look_at: tuple|None, zoom_factor: float, now=None) -> None` — fetch the bridge maincamera; `engaged` ⇒ `cam.engage(zoom_factor, look_at)`, else `cam.disengage()` + best-effort `BridgeHandlers.DropOutOfManualFireMode()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/appc/test_menu_event_handler.py`:

```python
"""CharacterClass.MenuEventHandler drives the bridge maincamera zoom."""
import pytest
import App
from engine.appc.bridge_set import ZoomCameraObjectClass


class _FakeBridge:
    def __init__(self, cam):
        self._cam = cam
    def GetCamera(self, name):
        return self._cam if name == "maincamera" else None


@pytest.fixture
def wired(monkeypatch):
    cam = ZoomCameraObjectClass(0, 0, 0, 1, 0, 0, 0, "maincamera")
    cam.SetMinZoom(0.64); cam.SetMaxZoom(1.0); cam.SetZoomTime(0.375)
    bridge = _FakeBridge(cam)

    class _SM:
        def GetSet(self, name):
            return bridge if name == "bridge" else None
    monkeypatch.setattr(App, "g_kSetManager", _SM(), raising=False)
    return cam


def _char():
    from engine.appc.characters import CharacterClass_Create
    return CharacterClass_Create("", "")


def test_engage_zooms_camera_in(wired):
    _char().MenuEventHandler(True, (1.0, 2.0, 3.0), 0.5)
    assert wired.IsZoomed() == 1
    assert wired.active_factor == pytest.approx(0.5)
    assert wired.look_at == (1.0, 2.0, 3.0)


def test_disengage_zooms_camera_out(wired):
    c = _char()
    c.MenuEventHandler(True, None, 0.5)
    c.MenuEventHandler(False, None, 0.5)
    assert wired.IsZoomed() == 0


def test_forward_engage_keeps_none_lookat(wired):
    _char().MenuEventHandler(True, None, 0.5)
    assert wired.IsZoomed() == 1
    assert wired.look_at is None


def test_missing_maincamera_is_safe(monkeypatch):
    class _SM:
        def GetSet(self, name):
            return None
    monkeypatch.setattr(App, "g_kSetManager", _SM(), raising=False)
    _char().MenuEventHandler(True, None, 0.5)   # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd <worktree> && uv run pytest tests/appc/test_menu_event_handler.py -q`
Expected: FAIL (`MenuEventHandler` resolves to the `__getattr__` data-bag no-op lambda; `IsZoomed()` stays 0).

- [ ] **Step 3: Implement `MenuEventHandler`**

In `engine/appc/characters.py`, add to `CharacterClass` right after `MenuDown` (before `_notify_menu`):

```python
    def MenuEventHandler(self, engaged, look_at, zoom_factor, now=None) -> None:
        """BC CharacterClass::MenuEventHandler (0x0066D450) — reconcile the bridge
        maincamera zoom to this character's engagement. `engaged` ⇒ zoom in toward
        `zoom_factor` aiming at `look_at` (world xyz, or None = viewscreen-forward);
        else zoom out. The host resolves engagement + look_at/zoom_factor each frame
        (it owns the renderer for head-centre look-ats) and calls this; the zoom
        STATE lives on the ZoomCameraObjectClass. Best-effort: never raises."""
        try:
            import App
            bridge = App.g_kSetManager.GetSet("bridge")
            cam = bridge.GetCamera("maincamera") if bridge is not None else None
            if cam is None or not hasattr(cam, "engage"):
                return
            if engaged:
                cam.engage(zoom_factor, look_at)
            else:
                cam.disengage()
                try:
                    import BridgeHandlers
                    BridgeHandlers.DropOutOfManualFireMode()
                except Exception:
                    pass
        except Exception:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd <worktree> && uv run pytest tests/appc/test_menu_event_handler.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/characters.py tests/appc/test_menu_event_handler.py
git commit -m "feat(characters): CharacterClass.MenuEventHandler drives maincamera zoom

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Officer-path cutover — `_BridgeCamera` reads the camera object

This is the risky, atomic cutover: relocate the zoom state/advance from `_BridgeCamera` to the `ZoomCameraObjectClass`, drive it via `MenuEventHandler` from the host resolver, and keep the **officer** zoom behavior-identical. Viewscreen-hail is Task 4.

**Files:**
- Modify: `engine/host_loop.py` — harvest `_BRIDGE_ZOOM_CAM` (~5875); rewrite `_BridgeCamera.__init__`/`apply`/`compute_camera` to read the camera; rewrite the resolver block (~7074-7084) to call `MenuEventHandler` + `cam.advance`; delete `set_zoom_target`; keep `_active_zoom_officer`/`_officer_zoom_factor` (used by the resolver).
- Modify (rewrite, don't orphan): `tests/unit/test_bridge_camera_zoom.py`

**Interfaces:**
- Consumes: `ZoomCameraObjectClass` (Task 1), `CharacterClass.MenuEventHandler` (Task 2).
- Produces: module global `_BRIDGE_ZOOM_CAM` (the maincamera `ZoomCameraObjectClass` or `None`); `_BridgeCamera._zoom_cam()` accessor; `compute_camera(now=None)` reading `cam.zoom_progress()/active_factor/look_at`.

- [ ] **Step 1: Rewrite the failing tests first**

Replace the body of `tests/unit/test_bridge_camera_zoom.py` (drive the camera object, not the removed `set_zoom_target`). Keep the geometry assertions (points-at-target, fov×0.64, roll-free) — those are the officer regression bar:

```python
"""_BridgeCamera zoom geometry, driven via the ZoomCameraObjectClass the host
harvests into hl._BRIDGE_ZOOM_CAM (MenuEventHandler port)."""
import math
import pytest

import engine.host_loop as hl
from engine.host_loop import _BridgeCamera
from engine.appc.bridge_set import ZoomCameraObjectClass

_SAVED = {}


def _make_cam():
    c = ZoomCameraObjectClass(0, 0, 0, 1, 0, 0, 0, "maincamera")
    c.SetMinZoom(0.64); c.SetMaxZoom(1.0); c.SetZoomTime(0.375)
    return c


def setup_function(_):
    for k in ("_BRIDGE_CAMERA_EYE", "_BRIDGE_CAMERA_MOVE", "_BRIDGE_ZOOM_MIN",
              "_BRIDGE_ZOOM_MAX", "_BRIDGE_ZOOM_TIME", "_BRIDGE_ZOOM_CAM"):
        _SAVED[k] = getattr(hl, k)
    hl._BRIDGE_CAMERA_EYE = (0.0, 0.0, 0.0)
    hl._BRIDGE_CAMERA_MOVE = None
    hl._BRIDGE_ZOOM_MIN = 0.64
    hl._BRIDGE_ZOOM_MAX = 1.0
    hl._BRIDGE_ZOOM_TIME = 0.375
    hl._BRIDGE_ZOOM_CAM = _make_cam()


def teardown_function(_):
    for k, v in _SAVED.items():
        setattr(hl, k, v)


def test_captain_view_when_no_target():
    bc = _BridgeCamera()
    eye, target, up, fov = bc.compute_camera()
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD)
    assert len((eye, target, up, fov)) == 4


def test_full_zoom_points_at_target_and_narrows_fov():
    bc = _BridgeCamera()
    hl._BRIDGE_ZOOM_CAM.engage(0.64, (10.0, 0.0, 0.0))
    hl._BRIDGE_ZOOM_CAM.advance(10.0)          # ease to completion
    eye, target, up, fov = bc.compute_camera()
    fwd = (target[0] - eye[0], target[1] - eye[1], target[2] - eye[2])
    fl = math.sqrt(sum(c * c for c in fwd))
    assert (fwd[0] / fl, fwd[1] / fl, fwd[2] / fl) == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD * 0.64)


def test_deselect_eases_back_to_captain_view():
    bc = _BridgeCamera()
    hl._BRIDGE_ZOOM_CAM.engage(0.64, (10.0, 0.0, 0.0)); hl._BRIDGE_ZOOM_CAM.advance(10.0)
    hl._BRIDGE_ZOOM_CAM.disengage(); hl._BRIDGE_ZOOM_CAM.advance(10.0)
    _, _, _, fov = bc.compute_camera()
    assert fov == pytest.approx(_BridgeCamera.FOV_Y_RAD)


def test_mouse_look_suspended_while_zooming():
    bc = _BridgeCamera()
    hl._BRIDGE_ZOOM_CAM.engage(0.64, (10.0, 0.0, 0.0)); hl._BRIDGE_ZOOM_CAM.advance(10.0)
    y0 = bc.yaw_rad
    bc.apply(100.0, 50.0)
    assert bc.yaw_rad == y0


def test_zoom_from_behind_and_up_stays_roll_free():
    bc = _BridgeCamera()
    bc.yaw_rad = math.pi
    bc.pitch_rad = 0.3
    hl._BRIDGE_ZOOM_CAM.engage(0.64, (10.0, 0.0, 0.0)); hl._BRIDGE_ZOOM_CAM.advance(10.0)
    eye, target, up, _ = bc.compute_camera()
    fwd = (target[0] - eye[0], target[1] - eye[1], target[2] - eye[2])
    right = (fwd[1] * 1.0 - fwd[2] * 0.0,
             fwd[2] * 0.0 - fwd[0] * 1.0,
             fwd[0] * 0.0 - fwd[1] * 0.0)
    roll = sum(u * r for u, r in zip(up, right))
    assert roll == pytest.approx(0.0, abs=1e-6)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd <worktree> && uv run pytest tests/unit/test_bridge_camera_zoom.py -q`
Expected: FAIL (`hl._BRIDGE_ZOOM_CAM` doesn't exist; `compute_camera` still reads `self._zoom_*`).

- [ ] **Step 3: Add the module global + harvest it at load**

In `engine/host_loop.py`, after line 1416 (`_BRIDGE_ZOOM_TIME: float = 0.0 ...`) add:

```python
_BRIDGE_ZOOM_CAM = None            # bridge "maincamera" ZoomCameraObjectClass (harvested at load)
```

In the load hook, extend the `global` at line 5843 and the harvest at 5875-5877:

```python
            global _BRIDGE_ZOOM_MIN, _BRIDGE_ZOOM_MAX, _BRIDGE_ZOOM_TIME, _BRIDGE_ZOOM_CAM
```
```python
                _BRIDGE_ZOOM_MIN = _cam.GetMinZoom()
                _BRIDGE_ZOOM_MAX = _cam.GetMaxZoom()
                _BRIDGE_ZOOM_TIME = _cam.GetZoomTime()
                _BRIDGE_ZOOM_CAM = _cam
```

- [ ] **Step 4: Rewrite `_BridgeCamera` to read the camera object**

In `engine/host_loop.py`, replace the zoom-state fields in `_BridgeCamera.__init__` (lines 2557-2564) with just the cutscene pose field note (the zoom state now lives on the camera):

```python
        # Zoom state now lives on the bridge "maincamera" ZoomCameraObjectClass
        # (hl._BRIDGE_ZOOM_CAM), driven by CharacterClass.MenuEventHandler. This
        # camera reads it each frame; it holds no zoom state of its own.
```

Add an accessor and a "zooming?" helper to `_BridgeCamera` (after `_lerp`):

```python
    @staticmethod
    def _zoom_cam():
        return _BRIDGE_ZOOM_CAM

    def _zoom_state(self):
        """(_zoom_t, active_factor, look_at) from the maincamera, or the neutral
        captain view when there is no camera / no zoom."""
        cam = self._zoom_cam()
        if cam is None:
            return 0.0, _BRIDGE_ZOOM_MAX, None
        return cam.zoom_progress(), cam.active_factor, cam.look_at
```

Delete `set_zoom_target` entirely (lines 2611-2641).

In `apply` (lines 2650-2663), replace the zoom guard:

```python
        # Mouse-look is frozen while a zoom is in progress — the camera is framing
        # the officer/viewscreen; it resumes only at the full captain view.
        cam = self._zoom_cam()
        if cam is not None and (cam.zoom_progress() > 0.0 or cam.IsZoomed()):
            return
```

In `compute_camera` (lines 2665-2728), replace the zoom block (2692-2725) with a read of `_zoom_state()`. The eased-forward + FOV-narrow + roll-free-up math is unchanged; only the source of `(_zoom_t, factor, target_world)` changes:

```python
        zoom_t, factor, target_world = self._zoom_state()
        if zoom_t > 0.0 and target_world is not None:
            e = self._smoothstep(zoom_t)
            dx = target_world[0] - eye[0]
            dy = target_world[1] - eye[1]
            dz = target_world[2] - eye[2]
            dl = _math.sqrt(dx*dx + dy*dy + dz*dz)
            if dl > 1e-6:
                ofwd = (dx/dl, dy/dl, dz/dl)
                bx = self._lerp(local_fwd[0], ofwd[0], e)
                by = self._lerp(local_fwd[1], ofwd[1], e)
                bz = self._lerp(local_fwd[2], ofwd[2], e)
                bl = _math.sqrt(bx*bx + by*by + bz*bz)
                if bl > 1e-6:
                    local_fwd = (bx/bl, by/bl, bz/bl)
                    zr = (
                        local_fwd[1]*1.0 - local_fwd[2]*0.0,
                        local_fwd[2]*0.0 - local_fwd[0]*1.0,
                        local_fwd[0]*0.0 - local_fwd[1]*0.0,
                    )
                    zrl = _math.sqrt(zr[0]**2 + zr[1]**2 + zr[2]**2)
                    if zrl > 1e-6:
                        zr = (zr[0]/zrl, zr[1]/zrl, zr[2]/zrl)
                        local_up = (
                            zr[1]*local_fwd[2] - zr[2]*local_fwd[1],
                            zr[2]*local_fwd[0] - zr[0]*local_fwd[2],
                            zr[0]*local_fwd[1] - zr[1]*local_fwd[0],
                        )
            fov = self.FOV_Y_RAD * self._lerp(_BRIDGE_ZOOM_MAX, factor, e)
        elif zoom_t > 0.0:
            # look_at is None: viewscreen-forward zoom — narrow FOV only, aim
            # unchanged (Task 4 refines the forward re-centre + pitch).
            e = self._smoothstep(zoom_t)
            fov = self.FOV_Y_RAD * self._lerp(_BRIDGE_ZOOM_MAX, factor, e)
```

- [ ] **Step 5: Rewrite the host resolver + drive MenuEventHandler**

In `engine/host_loop.py`, replace the resolver block (lines 7074-7084) that called `set_zoom_target`:

```python
                        # Resolve the single active engagement this frame, in
                        # precedence order: AT_WATCH_ME/LOOK_AT target > open crew
                        # menu > (Task 4: viewscreen hail). The winner supplies a
                        # world look-at + FOV factor; MenuEventHandler reconciles
                        # the maincamera zoom; advance() eases it on _player_dt so
                        # it freezes under pause.
                        _engaged = False
                        _look_at = None
                        _zoom_factor = _BRIDGE_ZOOM_MIN
                        _engaged_char = None
                        if watch_ctrl is not None:
                            _w = watch_ctrl.resolve_target_world(r)
                            if _w is not None:
                                _engaged, _look_at = True, _w
                        if not _engaged:
                            _wc, _zoom_off = _active_zoom_officer(crew_menu_panel, r)
                            if _wc is not None:
                                _engaged, _look_at = True, _wc
                                _zoom_factor = _officer_zoom_factor(_zoom_off)
                                _engaged_char = _zoom_off
                        _drv = _engaged_char or _last_engaged_char[0]
                        if _drv is not None:
                            _drv.MenuEventHandler(_engaged, _look_at, _zoom_factor,
                                                  now=_App.g_kUtopiaModule.GetGameTime())
                        if _engaged_char is not None:
                            _last_engaged_char[0] = _engaged_char
                        if _BRIDGE_ZOOM_CAM is not None:
                            _BRIDGE_ZOOM_CAM.advance(_player_dt)
```

Add a mutable holder near the other bridge-frame locals (so disengage has a character to call `MenuEventHandler` on after the officer is gone). Put it just before the `while` render loop where `bridge_camera` is created (~5907):

```python
        _last_engaged_char = [None]   # last officer we zoomed to (for disengage)
```

Note: `watch_ctrl.consume_snap()` — the old `snap=` path — is dropped; `AT_LOOK_AT_ME_NOW` now snaps by advancing with a large dt is NOT automatic. If `tests/unit/test_watch_ctrl_wiring.py` asserts snap, satisfy it by calling `_BRIDGE_ZOOM_CAM.advance(1e9)` when `watch_ctrl.consume_snap()` is true, right after the `advance(_player_dt)` line:

```python
                        if _BRIDGE_ZOOM_CAM is not None and watch_ctrl is not None \
                                and watch_ctrl.consume_snap():
                            _BRIDGE_ZOOM_CAM.advance(1e9)   # AT_LOOK_AT_ME_NOW
```

- [ ] **Step 6: Run the rewritten + neighbouring tests**

Run:
```bash
cd <worktree> && uv run pytest tests/unit/test_bridge_camera_zoom.py \
  tests/unit/test_active_zoom_officer.py tests/unit/test_bridge_camera_watch.py \
  tests/unit/test_watch_ctrl_wiring.py tests/unit/test_camera_dt_wiring.py \
  tests/host/test_bridge_camera.py -q
```
Expected: PASS. If `test_watch_ctrl_wiring.py` / `test_camera_dt_wiring.py` reference `set_zoom_target` or `_zoom_t`/`_zoom_active` on `_BridgeCamera`, update those references to the camera-object path (engage/advance/`_BRIDGE_ZOOM_CAM`) in the same commit — do not orphan them.

- [ ] **Step 7: Run the full gate**

Run: `cd <worktree> && scripts/check_tests.sh 2>&1 | tail -20`
Expected: "OK — no new failures." Investigate any failure not in `tests/known_failures.txt` before proceeding.

- [ ] **Step 8: Commit**

```bash
git add engine/host_loop.py tests/unit/test_bridge_camera_zoom.py \
        tests/unit/test_watch_ctrl_wiring.py tests/unit/test_camera_dt_wiring.py
git commit -m "refactor(bridge): drive maincamera zoom via MenuEventHandler; _BridgeCamera reads it

Officer zoom behavior-identical; set_zoom_target retired.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Viewscreen-hail producer (the E1M1 Liu zoom)

**Files:**
- Modify: `engine/appc/character_position_zoom.py` — add `_VIEWSCREEN_ZOOM_FALLBACK`.
- Modify: `engine/host_loop.py` — `_VIEWSCREEN_LOOK_PITCH`; `_viewscreen_hail_engagement`; add it as the lowest-precedence producer in the resolver; refine the `look_at is None` forward-recentre in `compute_camera`.
- Test: `tests/host/test_viewscreen_hail_zoom.py` (create).

**Interfaces:**
- Consumes: `_active_comm_feed(controller)` (host_loop:5092), `ZoomCameraObjectClass` (Task 1), `MenuEventHandler` (Task 2).
- Produces: `_viewscreen_hail_engagement(controller) -> (char, zoom_factor) | None`; `_VIEWSCREEN_ZOOM_FALLBACK = 0.5`; `_VIEWSCREEN_LOOK_PITCH` (radians).

- [ ] **Step 1: Write the failing test**

Create `tests/host/test_viewscreen_hail_zoom.py`:

```python
"""A viewscreen hail engages the bridge maincamera zoom (forward, fallback FOV)."""
import pytest
import engine.host_loop as hl
from engine.appc.bridge_set import ZoomCameraObjectClass
from engine.appc.character_position_zoom import POSITION_ZOOM_SENTINEL


class _RemoteChar:
    """Hailed character with no authored bridge position-zoom (GetPositionZoom
    misses -> sentinel), mirroring E1M1 Liu = SetLocation('StarbaseSeated')."""
    def GetLocation(self):
        return "StarbaseSeated"
    def GetPositionZoom(self, loc):
        return POSITION_ZOOM_SENTINEL


class _Controller:
    def __init__(self, char):
        self._char = char
    # _active_comm_feed is monkeypatched to key off this.


def test_hail_resolves_forward_fallback_engagement(monkeypatch):
    char = _RemoteChar()
    ctrl = _Controller(char)
    monkeypatch.setattr(hl, "_active_comm_feed", lambda c: (7, object()))
    monkeypatch.setattr(hl, "_hailed_character", lambda c: char)
    out = hl._viewscreen_hail_engagement(ctrl)
    assert out is not None
    got_char, factor = out
    assert got_char is char
    assert factor == pytest.approx(hl._VIEWSCREEN_ZOOM_FALLBACK)   # sentinel -> 0.5


def test_no_hail_returns_none(monkeypatch):
    monkeypatch.setattr(hl, "_active_comm_feed", lambda c: None)
    assert hl._viewscreen_hail_engagement(_Controller(None)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd <worktree> && uv run pytest tests/host/test_viewscreen_hail_zoom.py -q`
Expected: FAIL (`_viewscreen_hail_engagement`, `_VIEWSCREEN_ZOOM_FALLBACK`, `_hailed_character` not defined).

- [ ] **Step 3: Add the fallback constant**

In `engine/appc/character_position_zoom.py`, after `POSITION_ZOOM_SENTINEL` (line 17):

```python
# Viewscreen-hail sentinel fallback. A hailed/remote character SetLocations a
# remote-set location with no AddPositionZoom, so GetPositionZoom misses and
# returns POSITION_ZOOM_SENTINEL. BC substitutes a hardcoded fallback stronger
# than a bridge station's 0.64 (the user-observed ~2x fill = 1/0.5). Officers
# keep their own _BRIDGE_ZOOM_MIN sentinel fallback (regression-safe); only the
# viewscreen reaches this. Tunable (calibrate up then down); no rebuild.
VIEWSCREEN_ZOOM_FALLBACK = 0.5
```

- [ ] **Step 4: Add the producer + constants in host_loop**

In `engine/host_loop.py`, near the other bridge zoom constants (after the new `_BRIDGE_ZOOM_CAM` line):

```python
from engine.appc.character_position_zoom import (
    POSITION_ZOOM_SENTINEL as _POSITION_ZOOM_SENTINEL,
    VIEWSCREEN_ZOOM_FALLBACK as _VIEWSCREEN_ZOOM_FALLBACK,
)
_VIEWSCREEN_LOOK_PITCH = 0.0       # extra downward pitch to centre the screen (tunable)
```

Add the hailed-character resolver + engagement producer near `_active_comm_feed` (~5092):

```python
def _hailed_character(controller):
    """The character currently shown on the viewscreen hail, or None. BC's
    MissionLib.ViewscreenOn un-hides exactly one named CharacterClass on the
    look-at (comm) set; return it so its GetPositionZoom(GetLocation()) drives
    the zoom factor (a miss -> the viewscreen fallback)."""
    vs = getattr(controller, "viewscreen_obj", None)
    if vs is None or not vs.IsOn():
        return None
    name = getattr(vs, "remote_character_name", None)
    if not name:
        return None
    import App as _App
    cam = vs.GetRemoteCam()
    for _n, s in list(_App.g_kSetManager.iter_sets()):
        if s.GetCamera("maincamera") is cam:
            return _App.CharacterClass_GetObject(s, name)
    return None


def _viewscreen_hail_engagement(controller):
    """(char, zoom_factor) while a hail is on the viewscreen, else None. Factor =
    the hailed char's GetPositionZoom(GetLocation()); a sentinel miss (remote
    location, no AddPositionZoom) -> _VIEWSCREEN_ZOOM_FALLBACK. look_at is always
    None (viewscreen-forward)."""
    if _active_comm_feed(controller) is None:
        return None
    char = _hailed_character(controller)
    if char is None:
        return None
    factor = char.GetPositionZoom(char.GetLocation())
    if factor is None or factor == _POSITION_ZOOM_SENTINEL:
        factor = _VIEWSCREEN_ZOOM_FALLBACK
    return char, factor
```

Note: if `ViewScreenObject` does not already record the un-hidden character name, store it in `MissionLib.ViewscreenOn`'s host mirror. Check `engine/appc/*viewscreen*` / the `viewscreen_obj` for a `remote_character_name`; if absent, set it where `pcName` is applied (the same place `_sync_comm_character_visibility` un-hides it) and add a one-line test. Keep this within Task 4.

- [ ] **Step 5: Wire the producer into the resolver (lowest precedence)**

In the resolver block from Task 3 Step 5, after the officer branch and before the `_drv` dispatch, add:

```python
                        if not _engaged:
                            _hail = _viewscreen_hail_engagement(controller)
                            if _hail is not None:
                                _engaged_char, _zoom_factor = _hail
                                _engaged, _look_at = True, None   # viewscreen-forward
```

- [ ] **Step 6: Refine the forward re-centre in `compute_camera`**

Replace the `elif zoom_t > 0.0:` branch added in Task 3 Step 4 so a forward (look_at=None) zoom eases the aim toward BASE forward (yaw=INITIAL_YAW, pitch=`_VIEWSCREEN_LOOK_PITCH`) — BC's LookForward — in addition to narrowing FOV:

```python
        elif zoom_t > 0.0:
            # Viewscreen-forward zoom (look_at is None): ease the aim toward the
            # captain's BASE forward (recentre on the screen, BC LookForward) and
            # narrow FOV. Base forward = local +Y rotated by INITIAL_YAW, pitched
            # down by _VIEWSCREEN_LOOK_PITCH.
            e = self._smoothstep(zoom_t)
            bf = _rot_around((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), self.INITIAL_YAW_RAD)
            if _VIEWSCREEN_LOOK_PITCH:
                _bright = _rot_around(bf, (0.0, 0.0, 1.0), -_math.pi / 2)
                bf = _rot_around(bf, _bright, _VIEWSCREEN_LOOK_PITCH)
            bx = self._lerp(local_fwd[0], bf[0], e)
            by = self._lerp(local_fwd[1], bf[1], e)
            bz = self._lerp(local_fwd[2], bf[2], e)
            bl = _math.sqrt(bx*bx + by*by + bz*bz)
            if bl > 1e-6:
                local_fwd = (bx/bl, by/bl, bz/bl)
                zr = (local_fwd[1], -local_fwd[0], 0.0)
                zrl = _math.sqrt(zr[0]**2 + zr[1]**2 + zr[2]**2)
                if zrl > 1e-6:
                    zr = (zr[0]/zrl, zr[1]/zrl, zr[2]/zrl)
                    local_up = (
                        zr[1]*local_fwd[2] - zr[2]*local_fwd[1],
                        zr[2]*local_fwd[0] - zr[0]*local_fwd[2],
                        zr[0]*local_fwd[1] - zr[1]*local_fwd[0],
                    )
            fov = self.FOV_Y_RAD * self._lerp(_BRIDGE_ZOOM_MAX, factor, e)
```

- [ ] **Step 7: Run the new + regression tests**

Run:
```bash
cd <worktree> && uv run pytest tests/host/test_viewscreen_hail_zoom.py \
  tests/unit/test_bridge_camera_zoom.py tests/host/test_host_loop_viewscreen_drive.py -q
```
Expected: PASS.

- [ ] **Step 8: Run the full gate**

Run: `cd <worktree> && scripts/check_tests.sh 2>&1 | tail -20`
Expected: "OK — no new failures."

- [ ] **Step 9: Commit**

```bash
git add engine/appc/character_position_zoom.py engine/host_loop.py \
        tests/host/test_viewscreen_hail_zoom.py
git commit -m "feat(bridge): zoom the maincamera onto the viewscreen on a hail (E1M1 Liu)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Live-verify readiness + docs

**Files:**
- Modify: `docs/superpowers/specs/2026-07-24-menu-event-handler-viewscreen-zoom-design.md` — mark implemented; note tuning knobs (`VIEWSCREEN_ZOOM_FALLBACK`, `_VIEWSCREEN_LOOK_PITCH`).

- [ ] **Step 1: Confirm the whole gate is green**

Run: `cd <worktree> && scripts/check_tests.sh 2>&1 | tail -20`
Expected: "OK — no new failures."

- [ ] **Step 2: Note the tuning knobs + live-verify plan in the spec**

Append an "Implemented" note: `VIEWSCREEN_ZOOM_FALLBACK` (0.5) and `_VIEWSCREEN_LOOK_PITCH` (0.0) are the two live-tuning knobs (no rebuild). Live-verify happens in the MAIN tree (bring the branch over): E1M1 Liu briefing zooms ~2× to fill on the hail and returns on ViewscreenOff; crew-menu open still frames its officer identically.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-07-24-menu-event-handler-viewscreen-zoom-design.md
git commit -m "docs(camera): mark MenuEventHandler viewscreen-zoom implemented + tuning knobs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** §3.1 A → Task 1; §3.1 B → Task 2; §3.1 C/D + §3.2 officer path + §3.4 retirements → Task 3; §3.2 viewscreen path + §3.5 fallback → Task 4; testing §4 spread across tasks; live-verify → Task 5. Turn-to-face + shake divergences (§3.3) need no code (turn stays in `MenuUp`; shake magnitude 0).
- **Precedence:** watch > officer-menu > viewscreen-hail, enforced by the resolver order in Task 3 Step 5 + Task 4 Step 5. Baked cutscene pose (`set_anim_pose`) still returns early in `compute_camera` (line 2671), outranking all zoom — unchanged.
- **Officer regression bar:** Task 3 keeps `compute_camera` geometry byte-identical and re-drives it through the camera object; the rewritten `test_bridge_camera_zoom.py` asserts the same fov×0.64 + roll-free framing.
- **Open verification for the implementer:** whether `ViewScreenObject`/`viewscreen_obj` already records the un-hidden hail character name (Task 4 Step 4 note). If not, add it where `pcName` is applied; do not reach into SDK internals.
