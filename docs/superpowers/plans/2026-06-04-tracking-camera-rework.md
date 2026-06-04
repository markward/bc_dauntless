# Tracking Camera Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken target-lock branch of `_CameraControl` with a clean Tracking Mode camera that holds player at screen-Y ≈ −25% and target at ≈ +25% across all ranges, with camera-up always from the ship body frame (no world-Z reference), under a new mode-dispatch scaffold that future camera modes plug into.

**Architecture:** Extract a small `engine/cameras/` package: `_ChaseCamera` (pure rename of `_CameraControl`, behaviourally unchanged), `_TrackingCamera` (new — two-angle inscribed-angle solver with eye and basis springs), and `_CameraDirector` (mode flag, `C`-key toggle, target-loss fallback to Chase). `host_loop._compute_camera` becomes a thin shim that calls the director.

**Tech Stack:** Python 3.13, pytest, BC's column-vector `TGMatrix3` / `TGPoint3` (from `engine/appc/math.py`). No new dependencies. All tests are pure unit tests against the camera classes — no renderer, no PyBullet, no host loop.

**Spec:** [`docs/superpowers/specs/2026-06-04-tracking-camera-rework-design.md`](../specs/2026-06-04-tracking-camera-rework-design.md)

---

## File Structure

```
engine/cameras/
    __init__.py        — re-exports CameraMode, CameraDirector, EXTERIOR_FOV_Y_RAD
    chase.py           — _ChaseCamera (moved from host_loop.py, pure rename)
    tracking.py        — _TrackingCamera + inscribed-angle solver
    director.py        — _CameraDirector + CameraMode enum

engine/host_loop.py    — _compute_camera reduced to a director.compute() shim;
                          old target-lock code (_relocate_eye_for_target_lock,
                          target_lock_* fields, world-Z lift) removed

tests/cameras/
    __init__.py
    test_chase.py              — renamed from tests/host/test_camera_control.py
                                   (import path updates only; content unchanged)
    test_tracking_geometry.py  — solver math + edge cases (~ tasks 5–8 tests)
    test_tracking_springs.py   — eye + basis springs, snap()
    test_director.py           — mode transitions, target-loss, snap propagation
```

Each file has one clear responsibility. `_ChaseCamera` keeps the orbit/zoom/rotation-spring behaviour it has today (no changes). `_TrackingCamera` is self-contained with no knowledge of orbit angles. `_CameraDirector` knows only the mode flag and forwards `compute()` calls.

---

## Task 1: Package skeleton

Set up the directory layout and shared constants. No behavioural change — just empty files and one re-export — so this task has no tests.

**Files:**
- Create: `engine/cameras/__init__.py`
- Create: `engine/cameras/chase.py` (empty placeholder)
- Create: `engine/cameras/tracking.py` (empty placeholder)
- Create: `engine/cameras/director.py` (empty placeholder)
- Create: `tests/cameras/__init__.py` (empty)

- [ ] **Step 1: Create the package directory and stubs**

```bash
mkdir -p engine/cameras tests/cameras
```

Write `engine/cameras/__init__.py`:

```python
"""Camera modes for the tactical view.

Each mode is a separate class returning (eye, look_at, up) in world
space. The director dispatches based on the active mode flag.

Adding a new mode = new file in this package + new entry in CameraMode
enum + one branch in the director. No edits to existing modes.
"""
import math

# Vertical field of view for the exterior camera, used by the
# Tracking solver to convert screen-Y fractions to angles via
#     α = atan(y × tan(v_fov / 2))
# Must stay in sync with the value passed to r.set_camera in
# host_loop.py (see Task 4).
EXTERIOR_FOV_Y_RAD: float = math.radians(60.0)
```

Write `engine/cameras/chase.py`:

```python
"""Chase Mode — free-orbit chase camera. Behaviourally unchanged
straight rename of host_loop._CameraControl (see Task 2)."""
```

Write `engine/cameras/tracking.py`:

```python
"""Tracking Mode — two-angle inscribed-angle solver.

Placeholder; implementation arrives over Tasks 5–9."""
```

Write `engine/cameras/director.py`:

```python
"""Camera mode dispatch. Placeholder; implementation arrives in Task 3."""
```

Write `tests/cameras/__init__.py`:

```python
```

- [ ] **Step 2: Sanity-check imports**

Run: `uv run python -c "import engine.cameras; print(engine.cameras.EXTERIOR_FOV_Y_RAD)"`
Expected: `1.0471975511965976` (60° in radians).

- [ ] **Step 3: Commit**

```bash
git add engine/cameras/ tests/cameras/__init__.py
git commit -m "scaffold(cameras): engine/cameras package + shared FOV constant

Empty stubs for chase/tracking/director, plus EXTERIOR_FOV_Y_RAD
re-export. Behaviour unchanged; subsequent tasks fill in the
modules and migrate _CameraControl into chase.py.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Move `_CameraControl` to `engine/cameras/chase.py` as `_ChaseCamera`

Pure rename + move. No behaviour change. Update all import sites and the test file. The single existing test file `tests/host/test_camera_control.py` becomes `tests/cameras/test_chase.py` with import-path updates only — all test bodies unchanged.

**Files:**
- Modify: `engine/host_loop.py` (cut `_CameraControl`, replace with import)
- Modify: `engine/cameras/chase.py` (paste class, rename to `_ChaseCamera`)
- Modify: `tests/host/test_camera_control.py` → `tests/cameras/test_chase.py` (rename file, update imports)

- [ ] **Step 1: Verify existing tests pass before moving anything**

Run: `uv run pytest tests/host/test_camera_control.py tests/host/test_bridge_camera.py -v`
Expected: all 30+ tests pass.

- [ ] **Step 2: Cut `_CameraControl` class from `host_loop.py`**

In `engine/host_loop.py`, locate the `_CameraControl` class definition (currently at line 893, runs through ~line 1091 including `_advance_smoothing`). Cut the entire class body and the `_FakeKeys`-aware key-handling within it. Leave the constants `CAM_BACK_RADII`, `CAM_UP_RADII`, etc. in `host_loop.py` for now — Task 2.5 deals with them.

Replace the cut location with a single import statement:

```python
from engine.cameras.chase import _ChaseCamera as _CameraControl
```

This alias keeps every other call site in `host_loop.py` working unchanged for this task.

- [ ] **Step 3: Paste the class into `engine/cameras/chase.py` and rename**

Write `engine/cameras/chase.py`:

```python
"""Chase Mode — free-orbit chase camera.

Arrow-key orbit + scroll-wheel zoom in the player ship's body frame.
The orbit angles and distance are stored in ship-relative coordinates
so the camera "rotates with" the ship: banking/pitching/yawing
preserves the relative camera position.

Conventions:
    orbit_yaw_rad   — rotation around ship-Z. 0 = directly behind,
                      +ve = camera moves to ship-right, -ve = ship-left.
                      Wraps freely; not clamped.
    orbit_pitch_rad — elevation above the ship's XY plane. 0 = level
                      with the ship; +ve = camera above. Clamped to
                      ±PITCH_LIMIT.
    distance        — eye-to-ship distance, multiplicative on scroll.

Behaviourally identical to the prior host_loop._CameraControl; this is
a pure rename + move under Task 2 of the tracking-camera rework.
"""
import math as _math

from engine.host_loop import (
    CAM_BACK_RADII, CAM_UP_RADII, CAM_MIN_RADII, CAM_MAX_RADII,
    CAM_LOOK_UP_RADII, CAM_TARGET_LOCK_LIFT_RADII,
)


class _ChaseCamera:
    """Arrow-key orbit + scroll-wheel zoom around the player ship."""

    TURN_RATE_RAD_PER_S    = 1.5
    ZOOM_FACTOR_PER_NOTCH  = 0.9
    PITCH_LIMIT_RAD        = _math.radians(85)
    DEFAULT_YAW_RAD        = 0.0
    DEFAULT_PITCH_RAD      = _math.atan2(CAM_UP_RADII, CAM_BACK_RADII)
    SPRING_TAU_S           = 0.50

    def __init__(self):
        self.orbit_yaw_rad      = self.DEFAULT_YAW_RAD
        self.orbit_pitch_rad    = self.DEFAULT_PITCH_RAD
        self._smoothed_rot      = None
        self.look_up_offset     = 0.0
        self.target_lock_enabled = True
        self.target_lock_bias    = 0.15
        self.set_ship_radius(1.0)

    # ... (rest of the class body — set_ship_radius, reset_orbit,
    # lock_to_target, snap, apply, compute_camera, _advance_smoothing —
    # copied verbatim from the host_loop.py version with the class name
    # changed from `_CameraControl` to `_ChaseCamera`. No code changes
    # inside the methods.)
```

The `... (rest of the class body ...)` comment above is a marker for the engineer — the actual paste must contain every method of `_CameraControl` verbatim (≈200 lines from `set_ship_radius` through `_advance_smoothing`).

Note the circular import risk: `chase.py` imports `CAM_*` constants from `host_loop.py`. This is fine because `host_loop.py` imports `_ChaseCamera` at module body level too — but only the alias is needed at import time, not the class internals. If pytest reports an `ImportError` for `engine.cameras.chase`, hoist the `CAM_*` constants into `engine/cameras/__init__.py` (Task 2.5 below) and have both `host_loop.py` and `chase.py` import from there.

- [ ] **Step 4: Rename and relocate the test file**

```bash
git mv tests/host/test_camera_control.py tests/cameras/test_chase.py
```

In the new `tests/cameras/test_chase.py`, replace every occurrence of:

```python
from engine.host_loop import _CameraControl
```

with:

```python
from engine.cameras.chase import _ChaseCamera as _CameraControl
```

Leave the `_CameraControl` alias in place inside the test file so test bodies stay verbatim. The class behaviour is identical; the rename to `_ChaseCamera` in production code does not require renaming inside the existing tests.

- [ ] **Step 5: Run tests, expect all to pass**

Run: `uv run pytest tests/cameras/test_chase.py tests/host/test_bridge_camera.py -v`
Expected: same 30+ tests pass, zero behaviour change.

- [ ] **Step 6: Run a broader sweep to catch any missed `_CameraControl` references**

Run: `uv run pytest tests/host/ -x --tb=short`
Expected: all green. If any test imports `_CameraControl` from `engine.host_loop` directly, the alias in Step 2 covers it.

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py engine/cameras/chase.py tests/cameras/test_chase.py tests/host/test_camera_control.py
git commit -m "refactor(cameras): move _CameraControl to engine/cameras/chase.py:_ChaseCamera

Pure rename + relocation; behaviour unchanged. host_loop keeps a
_CameraControl = _ChaseCamera alias so call sites are untouched
this commit.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2.5: (Conditional) Hoist `CAM_*` constants out of `host_loop.py`

Only run this task if Task 2 Step 5 fails with a circular-import error. If Task 2 tests passed, skip to Task 3.

**Files:**
- Modify: `engine/cameras/__init__.py` (add constants)
- Modify: `engine/host_loop.py` (re-export from package)
- Modify: `engine/cameras/chase.py` (import from package)

- [ ] **Step 1: Move constants into `engine/cameras/__init__.py`**

Append to `engine/cameras/__init__.py`:

```python
# Camera-follow distances as multiples of the player ship's GetRadius().
CAM_BACK_RADII             =  1.5
CAM_UP_RADII               =  0.25
CAM_MIN_RADII              =  0.6
CAM_MAX_RADII              = 30.0
CAM_LOOK_UP_RADII          =  0.20
CAM_TARGET_LOCK_LIFT_RADII =  1.0
```

- [ ] **Step 2: Replace `host_loop.py` definitions with re-imports**

In `engine/host_loop.py`, replace the `CAM_BACK_RADII = …` block with:

```python
from engine.cameras import (
    CAM_BACK_RADII, CAM_UP_RADII, CAM_MIN_RADII, CAM_MAX_RADII,
    CAM_LOOK_UP_RADII, CAM_TARGET_LOCK_LIFT_RADII,
)
```

- [ ] **Step 3: Update `engine/cameras/chase.py` import**

Change the import at the top of `chase.py` from `from engine.host_loop import …` to:

```python
from engine.cameras import (
    CAM_BACK_RADII, CAM_UP_RADII, CAM_MIN_RADII, CAM_MAX_RADII,
    CAM_LOOK_UP_RADII, CAM_TARGET_LOCK_LIFT_RADII,
)
```

- [ ] **Step 4: Rerun the Task 2 tests**

Run: `uv run pytest tests/cameras/test_chase.py tests/host/test_bridge_camera.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py engine/cameras/__init__.py engine/cameras/chase.py
git commit -m "refactor(cameras): hoist CAM_* constants into engine/cameras package

Breaks the circular import between host_loop.py and chase.py.
Constants are still re-exported from host_loop so existing test
imports keep working.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `CameraMode` enum and `_CameraDirector` (CHASE-only)

Create the dispatch layer. At this task it only knows CHASE — TRACKING is wired in Task 10. The point is to land the scaffold first so subsequent tasks have a place to slot the tracking camera in.

**Files:**
- Modify: `engine/cameras/director.py`
- Modify: `engine/cameras/__init__.py` (re-export)
- Create: `tests/cameras/test_director.py`

- [ ] **Step 1: Write the failing test**

Write `tests/cameras/test_director.py`:

```python
"""Unit tests for _CameraDirector — mode dispatch shim that owns the
mode flag and forwards compute() to the appropriate camera class.

At Task 3 the director only handles CHASE mode. TRACKING dispatch and
mode transitions arrive in Task 10."""
import math
import pytest


def _make_ship_pose():
    from engine.appc.math import TGPoint3, TGMatrix3
    return TGPoint3(0.0, 0.0, 0.0), TGMatrix3()


class _FakePlayer:
    def __init__(self):
        self._loc, self._rot = _make_ship_pose()

    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetTarget(self):        return None  # no target → stays in Chase


def test_director_starts_in_chase_mode():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    assert d.mode is CameraMode.CHASE


def test_director_compute_matches_chase_camera_when_in_chase():
    from engine.cameras.director import _CameraDirector
    from engine.cameras.chase    import _ChaseCamera

    d  = _CameraDirector()
    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    d.chase.set_ship_radius(1.0)

    player = _FakePlayer()
    eye_d, look_d, up_d = d.compute(player=player, dt=1.0/60)
    eye_c, look_c, up_c = cc.compute_camera(
        player.GetWorldLocation(), player.GetWorldRotation(), dt=1.0/60,
    )

    for got, want in zip(eye_d, eye_c):  assert got == pytest.approx(want, abs=1e-6)
    for got, want in zip(look_d, look_c): assert got == pytest.approx(want, abs=1e-6)
    for got, want in zip(up_d, up_c):    assert got == pytest.approx(want, abs=1e-6)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `uv run pytest tests/cameras/test_director.py -v`
Expected: FAIL with `ImportError: cannot import name '_CameraDirector'`.

- [ ] **Step 3: Implement the director**

Write `engine/cameras/director.py`:

```python
"""Camera mode dispatch.

The director owns one camera object per CameraMode and a current-mode
flag. compute(...) forwards to the active camera. Mode transitions
(C-key toggle, target-loss fallback) arrive in Task 10.
"""
from enum import Enum

from engine.cameras.chase import _ChaseCamera


class CameraMode(Enum):
    CHASE    = "chase"
    TRACKING = "tracking"


class _CameraDirector:
    """Mode flag + per-mode camera objects + dispatch."""

    def __init__(self):
        self.mode  = CameraMode.CHASE
        self.chase = _ChaseCamera()
        # self.tracking added in Task 5.

    def compute(self, *, player, dt):
        """Return (eye, look_at, up) in world space for the active mode."""
        loc = player.GetWorldLocation()
        rot = player.GetWorldRotation()
        if self.mode is CameraMode.CHASE:
            return self.chase.compute_camera(loc, rot, dt=dt)
        raise RuntimeError(f"unhandled camera mode: {self.mode}")
```

Append to `engine/cameras/__init__.py`:

```python
from engine.cameras.director import CameraMode, _CameraDirector  # noqa: E402
```

- [ ] **Step 4: Run the test, expect pass**

Run: `uv run pytest tests/cameras/test_director.py -v`
Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/director.py engine/cameras/__init__.py tests/cameras/test_director.py
git commit -m "feat(cameras): CameraMode enum + _CameraDirector (CHASE-only)

Director owns the mode flag and per-mode cameras. CHASE dispatch
forwards to _ChaseCamera; TRACKING dispatch arrives in Task 10
once _TrackingCamera exists.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Wire the director into `host_loop._compute_camera`

Replace the direct `cam_control` reference in `_compute_camera` with a director instance. Old behaviour preserved (target-lock branch still runs through the chase camera). This is the integration step that lets Tasks 5–10 land without churning the host loop.

**Files:**
- Modify: `engine/host_loop.py`

- [ ] **Step 1: Locate the construction site of `cam_control`**

In `engine/host_loop.py` around line 2173 there is:

```python
        cam_control    = _CameraControl()
        if controller.session is not None and controller.session.player is not None:
            cam_control.set_ship_radius(controller.session.player.GetRadius())
```

- [ ] **Step 2: Replace with director construction**

Change those lines to:

```python
        from engine.cameras import _CameraDirector
        director       = _CameraDirector()
        cam_control    = director.chase   # back-compat alias for downstream sites
        if controller.session is not None and controller.session.player is not None:
            cam_control.set_ship_radius(controller.session.player.GetRadius())
```

The `cam_control = director.chase` alias keeps the existing `cam_control.set_ship_radius`, `cam_control.apply`, and `cam_control.snap` call sites working unchanged. Subsequent tasks migrate those to the director.

- [ ] **Step 3: Replace the `_compute_camera` body**

Locate `_compute_camera` (currently around line 1922). Replace the entire function body with a delegation to the director, keeping the bridge-mode branch intact:

```python
def _compute_camera(view_mode, director, *, player, dt) -> tuple:
    """Per-tick camera dispatch.

    Bridge mode anchors at the ship origin looking along ship-Y
    forward. Exterior mode delegates to the director, which chooses
    between Chase Mode (free orbit) and Tracking Mode (two-angle
    solver). Returns (eye, look_at, up) as 3-tuples in world space.
    """
    loc = player.GetWorldLocation()
    rot = player.GetWorldRotation()
    if view_mode.is_bridge:
        fwd = rot.GetCol(1)
        up  = rot.GetCol(2)
        eye    = (loc.x, loc.y, loc.z)
        target = (loc.x + fwd.x, loc.y + fwd.y, loc.z + fwd.z)
        up_vec = (up.x, up.y, up.z)
        return eye, target, up_vec
    return director.compute(player=player, dt=dt)
```

- [ ] **Step 4: Update the call site of `_compute_camera`**

Locate the call (around line 2598). Change:

```python
                eye, target, up_vec = _compute_camera(
                    view_mode, cam_control,
                    player=player, dt=TICK_DT)
```

to:

```python
                eye, target, up_vec = _compute_camera(
                    view_mode, director,
                    player=player, dt=TICK_DT)
```

- [ ] **Step 5: Delete `_relocate_eye_for_target_lock`**

The director.compute path goes through `_ChaseCamera.compute_camera` only (TRACKING dispatch raises). The old target-lock branching code is unreachable now. Delete the entire `_relocate_eye_for_target_lock` function from `host_loop.py` (currently around lines 1981–2034) and any docstring references to "target lock" in `_compute_camera`'s rewritten docstring (already gone above).

Important: the chase camera's `target_lock_enabled`, `target_lock_bias`, `target_lock_z_lift`, `look_up_offset`, and `lock_to_target()` are NOT removed in this task. They are still touched by host_loop's `C`-key path and by tests in `tests/cameras/test_chase.py`. Task 10 removes them once the director's `C` toggle lands.

- [ ] **Step 6: Run the existing test sweep**

Run: `uv run pytest tests/cameras/test_chase.py tests/cameras/test_director.py tests/host/test_bridge_camera.py -v`
Expected: all green. Behaviour unchanged: chase produces the same pose; target-lock framing now matches Chase Mode (no lock applied) — this is OK because Task 12's manual verification covers final framing; intermediate tasks just need the harness to not crash.

- [ ] **Step 7: Smoke-check the host loop boots**

Run: `uv run python -c "from engine.host_loop import _compute_camera; print('ok')"`
Expected: `ok`.

- [ ] **Step 8: Commit**

```bash
git add engine/host_loop.py
git commit -m "refactor(host_loop): route _compute_camera through _CameraDirector

Delete _relocate_eye_for_target_lock (unreachable now that the
director dispatches by mode). cam_control left as an alias for
director.chase so the C-key reset path and chase tests continue
to work; full removal lands in Task 10.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: `_TrackingCamera` skeleton + screen-Y → angle conversion

Stand up the class with its tunable defaults and a small helper. No solver yet — `compute()` raises `NotImplementedError` and is filled in over Tasks 6–9. Wire the director's TRACKING branch to instantiate the new class but do NOT switch the default mode (Chase stays the boot-time default).

**Files:**
- Modify: `engine/cameras/tracking.py`
- Modify: `engine/cameras/director.py`
- Create: `tests/cameras/test_tracking_geometry.py`

- [ ] **Step 1: Write the failing test**

Write `tests/cameras/test_tracking_geometry.py`:

```python
"""Unit tests for _TrackingCamera — two-angle solver for the
tactical-mode target camera. See:
    docs/superpowers/specs/2026-06-04-tracking-camera-rework-design.md
"""
import math
import pytest


def test_tracking_camera_has_default_screen_y_constants():
    from engine.cameras.tracking import _TrackingCamera
    tc = _TrackingCamera()
    assert tc.y_p == pytest.approx(-0.25)
    assert tc.y_t == pytest.approx(+0.25)


def test_tracking_camera_converts_screen_y_to_angle():
    """y → α via α = atan(y × tan(v_fov / 2)). For y = 0.25 and the
    default 60° v_fov, α ≈ atan(0.25 × tan(30°)) ≈ 8.213°."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.cameras           import EXTERIOR_FOV_Y_RAD

    tc = _TrackingCamera()
    alpha = tc._screen_y_to_angle(0.25)
    expected = math.atan(0.25 * math.tan(EXTERIOR_FOV_Y_RAD / 2))
    assert alpha == pytest.approx(expected, abs=1e-9)


def test_tracking_camera_screen_y_zero_gives_zero_angle():
    from engine.cameras.tracking import _TrackingCamera
    tc = _TrackingCamera()
    assert tc._screen_y_to_angle(0.0) == pytest.approx(0.0)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `uv run pytest tests/cameras/test_tracking_geometry.py -v`
Expected: FAIL with `ImportError: cannot import name '_TrackingCamera'`.

- [ ] **Step 3: Implement the class skeleton**

Write `engine/cameras/tracking.py`:

```python
"""Tracking Mode — two-angle inscribed-angle solver.

Frames player and target at fixed screen-Y fractions across all
ranges. Camera-up is derived from the player ship body frame; no
world-Z reference. Springs on eye position and camera basis.

See:
    docs/superpowers/specs/2026-06-04-tracking-camera-rework-design.md
"""
import math as _math

from engine.cameras import EXTERIOR_FOV_Y_RAD


class _TrackingCamera:
    """Two-angle solver + eye/basis springs."""

    # Default screen-Y fractions of the half-image, signed:
    #   negative = below centre, positive = above centre.
    y_p: float = -0.25   # player
    y_t: float = +0.25   # target

    # Spring time constants — see spec §4.
    POS_SPRING_TAU_S: float = 0.25
    ROT_SPRING_TAU_S: float = 0.50

    def __init__(self):
        self.v_fov_rad      = EXTERIOR_FOV_Y_RAD
        self.d_chase        = 1.0  # set via set_ship_radius (Task 9)
        self._smoothed_eye  = None
        self._smoothed_basis = None

    # ── small helpers ────────────────────────────────────────────────

    def _screen_y_to_angle(self, y: float) -> float:
        """Convert a screen-Y fraction in [-1, +1] to a signed angle from
        camera-forward, using the camera's vertical FOV."""
        return _math.atan(y * _math.tan(self.v_fov_rad / 2))

    # ── public surface ───────────────────────────────────────────────

    def compute(self, player, target, dt):
        """Return (eye, look_at, up) in world space.

        Implementation arrives over Tasks 6–9. For now raises so
        callers fail loudly if they reach Tracking before the solver
        exists.
        """
        raise NotImplementedError("tracking solver lands in Tasks 6–9")
```

Update `engine/cameras/director.py` to instantiate the new class but leave dispatch to Chase only — TRACKING branch raises until Task 10:

```python
"""Camera mode dispatch."""
from enum import Enum

from engine.cameras.chase    import _ChaseCamera
from engine.cameras.tracking import _TrackingCamera


class CameraMode(Enum):
    CHASE    = "chase"
    TRACKING = "tracking"


class _CameraDirector:
    """Mode flag + per-mode camera objects + dispatch."""

    def __init__(self):
        self.mode     = CameraMode.CHASE
        self.chase    = _ChaseCamera()
        self.tracking = _TrackingCamera()

    def compute(self, *, player, dt):
        loc = player.GetWorldLocation()
        rot = player.GetWorldRotation()
        if self.mode is CameraMode.CHASE:
            return self.chase.compute_camera(loc, rot, dt=dt)
        raise RuntimeError(f"unhandled camera mode: {self.mode}")
```

- [ ] **Step 4: Run the tests, expect pass**

Run: `uv run pytest tests/cameras/test_tracking_geometry.py tests/cameras/test_director.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/tracking.py engine/cameras/director.py tests/cameras/test_tracking_geometry.py
git commit -m "feat(cameras): _TrackingCamera skeleton + screen-Y → angle helper

Class + tunable y_p/y_t defaults + v_fov / screen-Y conversion.
compute() raises NotImplementedError; solver lands in Tasks 6–9.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Inscribed-angle solver — eye placement (happy path)

Implement the 2D plane construction and the eye placement on the locus arc. Tests cover the standard case (target ahead of player, body-up perpendicular to ship→target axis). Edge cases come in Task 8.

**Files:**
- Modify: `engine/cameras/tracking.py`
- Modify: `tests/cameras/test_tracking_geometry.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/cameras/test_tracking_geometry.py`:

```python
def _ship(loc_xyz=(0.0, 0.0, 0.0), rot=None):
    from engine.appc.math import TGPoint3, TGMatrix3
    loc = TGPoint3(*loc_xyz)
    return loc, rot if rot is not None else TGMatrix3()


def _project_to_screen_y(point, eye, forward, up):
    """Forward and up are unit 3-tuples. Returns screen-Y fraction:
        y = ((P - E) · u) / ((P - E) · f) × cot(v_fov/2)
    For matching, divide by tan(v_fov/2) to land in [-1, +1]."""
    px, py, pz = point
    ex, ey, ez = eye
    dx, dy, dz = px - ex, py - ey, pz - ez
    fx, fy, fz = forward
    ux, uy, uz = up
    along_f = dx*fx + dy*fy + dz*fz
    along_u = dx*ux + dy*uy + dz*uz
    from engine.cameras import EXTERIOR_FOV_Y_RAD
    return (along_u / along_f) / math.tan(EXTERIOR_FOV_Y_RAD / 2)


def test_solver_places_player_at_minus_quarter_screen_y():
    from engine.cameras.tracking import _TrackingCamera

    tc = _TrackingCamera()
    tc.d_chase = 10.0

    s_loc, s_rot = _ship((0.0, 0.0, 0.0))  # identity rot → body-up = +z
    t_loc, _     = _ship((0.0, 20.0, 0.0))  # 20 GU along +y (ship-forward)

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    fx = look_at[0] - eye[0]
    fy = look_at[1] - eye[1]
    fz = look_at[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    forward = (fx/flen, fy/flen, fz/flen)

    y_p = _project_to_screen_y((0.0, 0.0, 0.0), eye, forward, up)
    assert y_p == pytest.approx(-0.25, abs=1e-3)


def test_solver_places_target_at_plus_quarter_screen_y():
    from engine.cameras.tracking import _TrackingCamera

    tc = _TrackingCamera()
    tc.d_chase = 10.0

    s_loc, s_rot = _ship((0.0, 0.0, 0.0))
    t_loc, _     = _ship((0.0, 20.0, 0.0))

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)
    fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    forward = (fx/flen, fy/flen, fz/flen)

    y_t = _project_to_screen_y((0.0, 20.0, 0.0), eye, forward, up)
    assert y_t == pytest.approx(+0.25, abs=1e-3)


def test_solver_framing_is_invariant_across_range():
    """Player & target screen-Y must be ≈ ±0.25 whether target is 5,
    50, or 500 GU away. This is the regression the rewrite exists to
    fix."""
    from engine.cameras.tracking import _TrackingCamera

    s_loc, s_rot = _ship((0.0, 0.0, 0.0))
    for d in (5.0, 50.0, 500.0):
        tc = _TrackingCamera()
        tc.d_chase = 10.0
        t_loc, _ = _ship((0.0, d, 0.0))

        eye, look_at, up = tc.compute(
            player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

        fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
        flen = math.sqrt(fx*fx + fy*fy + fz*fz)
        forward = (fx/flen, fy/flen, fz/flen)

        y_p = _project_to_screen_y((0.0, 0.0, 0.0), eye, forward, up)
        y_t = _project_to_screen_y((0.0,  d,  0.0), eye, forward, up)
        assert y_p == pytest.approx(-0.25, abs=1e-3), f"range {d}: y_p={y_p}"
        assert y_t == pytest.approx(+0.25, abs=1e-3), f"range {d}: y_t={y_t}"


class _FakeShip:
    """Minimal player/target stub: just the world transform getters."""
    def __init__(self, loc, rot):
        self._loc, self._rot = loc, rot
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
```

- [ ] **Step 2: Run, watch them fail**

Run: `uv run pytest tests/cameras/test_tracking_geometry.py -v`
Expected: the three new tests fail with `NotImplementedError`.

- [ ] **Step 3: Implement the solver — plane construction + eye placement**

Replace `_TrackingCamera.compute` (currently raising) and add helpers. In `engine/cameras/tracking.py`:

```python
    def compute(self, player, target, dt):
        """Return (eye, look_at, up) in world space.

        Builds a 2D solver plane spanned by (T−S) and ship-body-up,
        places the eye on the inscribed-angle locus arc above and
        behind the player at distance d_chase, and constructs the
        camera basis so player projects to y_p and target to y_t.

        dt is currently unused; springs land in Task 9.
        """
        from engine.appc.math import TGPoint3

        S = player.GetWorldLocation()
        T = target.GetWorldLocation()
        R = player.GetWorldRotation()
        B = R.GetCol(2)  # ship body-up in world space

        # Plane basis (e1, e3): e1 along ship→target, e3 = body-up
        # projected perpendicular to e1, normalised.
        e1, e3 = self._plane_basis(S, T, B)

        # 2D coords: S = (0,0), T = (D,0). Solve for eye (e_x, e_y).
        D    = (TGPoint3(T.x-S.x, T.y-S.y, T.z-S.z)).Length()
        a_p  = self._screen_y_to_angle(self.y_p)
        a_t  = self._screen_y_to_angle(self.y_t)
        beta = a_t - a_p

        e_x, e_y = self._solve_eye_2d(D, self.d_chase, beta)

        # Lift back to 3D: E = S + e_x * e1 + e_y * e3.
        eye = (S.x + e_x * e1.x + e_y * e3.x,
               S.y + e_x * e1.y + e_y * e3.y,
               S.z + e_x * e1.z + e_y * e3.z)

        # Forward, up — Task 7.
        # Placeholder so subsequent tests can exercise eye placement:
        # forward = (S − E).normalised, up = e3.
        fx, fy, fz = S.x - eye[0], S.y - eye[1], S.z - eye[2]
        flen = _math.sqrt(fx*fx + fy*fy + fz*fz)
        forward = (fx/flen, fy/flen, fz/flen)
        look_at = (eye[0] + forward[0], eye[1] + forward[1], eye[2] + forward[2])
        up = (e3.x, e3.y, e3.z)
        return eye, look_at, up

    # ── solver internals ─────────────────────────────────────────────

    @staticmethod
    def _plane_basis(S, T, B):
        """Return (e1, e3) as TGPoint3 unit vectors in world space.

        e1 = (T − S).normalised
        e3 = (B − (B·e1) e1).normalised — body-up perpendicularised
        """
        from engine.appc.math import TGPoint3
        dx, dy, dz = T.x - S.x, T.y - S.y, T.z - S.z
        D = _math.sqrt(dx*dx + dy*dy + dz*dz)
        e1 = TGPoint3(dx/D, dy/D, dz/D)
        dot_b_e1 = B.x*e1.x + B.y*e1.y + B.z*e1.z
        ux = B.x - dot_b_e1 * e1.x
        uy = B.y - dot_b_e1 * e1.y
        uz = B.z - dot_b_e1 * e1.z
        ulen = _math.sqrt(ux*ux + uy*uy + uz*uz)
        if ulen < 1e-9:
            # Body-up parallel to (T − S); pick any perpendicular.
            # Task 8 strengthens this; for now use world-z as a stopgap.
            return e1, TGPoint3(0.0, 0.0, 1.0)
        return e1, TGPoint3(ux/ulen, uy/ulen, uz/ulen)

    @staticmethod
    def _solve_eye_2d(D, d_chase, beta):
        """Return (e_x, e_y) of camera in 2D (e1, e3) coords.

        Locus circle: centre (D/2, +D/(2 tan β)) on the +e3 side,
        radius r = D / (2 sin β). S lies on this circle, so the
        distance between centres equals r, and the two intersection
        points lie on the line through S perpendicular to the
        centre-to-centre direction. The "behind-player" intersection
        (e_x < 0) is the camera position.
        """
        sin_b = _math.sin(beta)
        cos_b = _math.cos(beta)
        r     = D / (2.0 * sin_b)

        # Centre-to-centre unit vector: (D/(2r), +h/r) = (sin β, +cos β).
        # Perpendicular pointing toward "behind player": (-cos β, +sin β).
        a     = (d_chase * d_chase) / (2.0 * r)
        disc  = d_chase * d_chase - a * a
        if disc < 0.0:
            # Numeric guard — Task 8 supplies the proper fallback.
            disc = 0.0
        h_chord = _math.sqrt(disc)

        # P_1 = midpoint − h_chord × perp.  (Spec §3 step 4.)
        e_x = a * sin_b - h_chord * cos_b
        e_y = a * cos_b + h_chord * sin_b
        return e_x, e_y
```

- [ ] **Step 4: Run, expect player and target screen-Y tests to pass**

Run: `uv run pytest tests/cameras/test_tracking_geometry.py -v`
Expected: `test_solver_places_player_at_minus_quarter_screen_y` and `test_solver_framing_is_invariant_across_range`'s y_p assertion pass; **the y_t assertions may still fail** because Task 6 only places the eye and returns a placeholder forward — Task 7 corrects the basis. Confirm the y_p assertions pass; failing y_t lines are expected at this checkpoint.

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/tracking.py tests/cameras/test_tracking_geometry.py
git commit -m "feat(cameras): tracking solver — eye placement on inscribed-angle locus

Plane basis (e1, e3) from ship→target and body-up. Closed-form eye
position by intersecting the chase-distance circle with the
inscribed-angle locus circle and picking the behind-player point.
Forward and up are placeholders — Task 7 builds the correct basis.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Tracking solver — camera basis

Compute `forward`, `up`, `right` so that player projects to `y_p` and target to `y_t` exactly. The placeholder basis from Task 6 satisfies neither in general.

**Files:**
- Modify: `engine/cameras/tracking.py`
- Modify: `tests/cameras/test_tracking_geometry.py` (add basis-specific tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/cameras/test_tracking_geometry.py`:

```python
def test_solver_up_vector_lies_in_ship_target_body_up_plane():
    """The returned up vector must lie in the plane spanned by
    (T − S) and the ship body-up axis — equivalently, up must be a
    linear combination of e1 and e3."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera(); tc.d_chase = 10.0
    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    t_loc = TGPoint3(0.0, 20.0, 0.0)

    _, _, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    # e1 is +y world, e3 is +z world for identity rotation. up should
    # have no x component.
    assert up[0] == pytest.approx(0.0, abs=1e-9)


def test_solver_camera_basis_is_orthonormal():
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera(); tc.d_chase = 10.0
    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    t_loc = TGPoint3(0.0, 20.0, 0.0)

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    forward = (fx/flen, fy/flen, fz/flen)

    dot_fu = forward[0]*up[0] + forward[1]*up[1] + forward[2]*up[2]
    ulen   = math.sqrt(up[0]**2 + up[1]**2 + up[2]**2)
    assert dot_fu == pytest.approx(0.0, abs=1e-9)
    assert flen   == pytest.approx(1.0, abs=1e-9)
    assert ulen   == pytest.approx(1.0, abs=1e-9)


def test_solver_player_roll_inherited_into_camera_up():
    """Roll the ship 30° around its forward axis (body-Y). The camera
    up should rotate with it — projection of body-up onto the
    perpendicular to forward."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera(); tc.d_chase = 10.0
    s_loc = TGPoint3(0.0, 0.0, 0.0)
    s_rot = TGMatrix3(); s_rot.MakeYRotation(math.radians(30))  # roll
    t_loc = TGPoint3(0.0, 20.0, 0.0)

    _, _, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    # Body-up after a Y-roll of 30° is (sin 30°, 0, cos 30°). The
    # ship→target direction is (0, 1, 0), so e1 perpendicular projection
    # of body-up keeps the (sin 30°, 0, cos 30°) intact (already
    # perpendicular to (0,1,0)).
    assert up[0] == pytest.approx(math.sin(math.radians(30)), abs=1e-6)
    assert up[1] == pytest.approx(0.0,                          abs=1e-6)
    assert up[2] == pytest.approx(math.cos(math.radians(30)), abs=1e-6)
```

Also un-skip the existing `test_solver_places_target_at_plus_quarter_screen_y` and the y_t branch of `test_solver_framing_is_invariant_across_range` — they should now pass once the basis is correct.

- [ ] **Step 2: Run, watch the basis tests fail**

Run: `uv run pytest tests/cameras/test_tracking_geometry.py -v`
Expected: orthonormality and target screen-Y tests fail with the placeholder basis from Task 6.

- [ ] **Step 3: Replace the placeholder basis with the proper construction**

Replace the basis section at the end of `_TrackingCamera.compute` (the block beginning with `# Forward, up — Task 7.`) with:

```python
        # Forward = (S − E).normalised, then rotate by −α_p around the
        # e3 axis so the player projects at angle α_p (below centre when
        # α_p < 0). This places player at screen-Y = y_p exactly.
        es_x = S.x - eye[0]
        es_y = S.y - eye[1]
        es_z = S.z - eye[2]
        es_len = _math.sqrt(es_x*es_x + es_y*es_y + es_z*es_z)
        es = (es_x/es_len, es_y/es_len, es_z/es_len)

        # Rotate `es` by -alpha_p around the e3 axis using Rodrigues:
        # v' = v cos θ + (k × v) sin θ + k (k · v) (1 − cos θ)
        # with θ = −α_p and k = e3.
        theta = -a_p
        c, s_ = _math.cos(theta), _math.sin(theta)
        kx, ky, kz = e3.x, e3.y, e3.z
        kdotv = kx*es[0] + ky*es[1] + kz*es[2]
        cross = (ky*es[2] - kz*es[1],
                 kz*es[0] - kx*es[2],
                 kx*es[1] - ky*es[0])
        forward = (
            es[0]*c + cross[0]*s_ + kx*kdotv*(1 - c),
            es[1]*c + cross[1]*s_ + ky*kdotv*(1 - c),
            es[2]*c + cross[2]*s_ + kz*kdotv*(1 - c),
        )
        # Re-normalise (defensive against floating drift).
        flen = _math.sqrt(forward[0]**2 + forward[1]**2 + forward[2]**2)
        forward = (forward[0]/flen, forward[1]/flen, forward[2]/flen)

        # Up = e3 with the forward-parallel component projected out.
        dot_u_f = e3.x*forward[0] + e3.y*forward[1] + e3.z*forward[2]
        ux = e3.x - dot_u_f * forward[0]
        uy = e3.y - dot_u_f * forward[1]
        uz = e3.z - dot_u_f * forward[2]
        ulen = _math.sqrt(ux*ux + uy*uy + uz*uz)
        up = (ux/ulen, uy/ulen, uz/ulen)

        look_at = (eye[0] + forward[0], eye[1] + forward[1], eye[2] + forward[2])
        return eye, look_at, up
```

- [ ] **Step 4: Run, expect all geometry tests to pass**

Run: `uv run pytest tests/cameras/test_tracking_geometry.py -v`
Expected: all tests in the file pass, including the framing-across-range and roll-inheritance ones.

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/tracking.py tests/cameras/test_tracking_geometry.py
git commit -m "feat(cameras): tracking solver — camera basis from eye

Forward = rotate (S−E)/|S−E| by −α_p around e3. Up = e3
perpendicularised against forward. Right falls out (cross product
left implicit in the look_at return).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Tracking solver — edge cases

Close-target fallback (D_chase ≥ D cot β) and body-up parallel to ship→target. Both must return finite, non-NaN output.

**Files:**
- Modify: `engine/cameras/tracking.py`
- Modify: `tests/cameras/test_tracking_geometry.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/cameras/test_tracking_geometry.py`:

```python
def test_solver_close_target_falls_back_gracefully():
    """When d_chase ≥ D cot β, the back-of-player intersection
    doesn't exist. Solver must pull the eye onto the locus arc behind
    the player rather than emit NaN."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera(); tc.d_chase = 10.0
    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    # D = 5 GU < d_chase × tan(β), forces fallback.
    t_loc = TGPoint3(0.0, 5.0, 0.0)

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    # Finite output:
    for v in (*eye, *look_at, *up):
        assert math.isfinite(v)
    # Eye behind player (negative y in this setup since e1 = +y):
    assert eye[1] < 0.0
    # Player still framed at y_p ≈ −0.25:
    fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    forward = (fx/flen, fy/flen, fz/flen)
    y_p = _project_to_screen_y((0.0, 0.0, 0.0), eye, forward, up)
    assert y_p == pytest.approx(-0.25, abs=1e-3)


def test_solver_body_up_parallel_to_ship_target_does_not_crash():
    """When body-up is parallel to (T − S), the projection that
    builds e3 degenerates. Solver must return finite output."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera(); tc.d_chase = 10.0
    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()  # body-up = +z
    # Target directly above ship in body frame:
    t_loc = TGPoint3(0.0, 0.0, 20.0)

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    for v in (*eye, *look_at, *up):
        assert math.isfinite(v)
```

- [ ] **Step 2: Run, watch them fail**

Run: `uv run pytest tests/cameras/test_tracking_geometry.py -v`
Expected: close-target test fails (eye may be NaN or in front of player); body-up parallel test may already pass thanks to the stopgap from Task 6 — confirm.

- [ ] **Step 3: Implement the close-target fallback**

Replace `_solve_eye_2d` in `engine/cameras/tracking.py` with:

```python
    @staticmethod
    def _solve_eye_2d(D, d_chase, beta):
        """Return (e_x, e_y) of camera in 2D (e1, e3) coords.

        Standard case: closed-form via inscribed-angle / chase-circle
        intersection (spec §3 step 4).
        Fallback (d_chase ≥ D cot β): place E on the locus arc
        directly behind the player (spec §3 step 5).
        """
        sin_b = _math.sin(beta)
        cos_b = _math.cos(beta)
        r     = D / (2.0 * sin_b)
        h     = D / (2.0 * _math.tan(beta))    # locus centre e3-coord

        # Condition: d_chase < D / tan β  ↔  back-of-player solution exists.
        if d_chase < D / _math.tan(beta):
            a       = (d_chase * d_chase) / (2.0 * r)
            disc    = d_chase * d_chase - a * a
            h_chord = _math.sqrt(max(disc, 0.0))
            e_x = a * sin_b - h_chord * cos_b
            e_y = a * cos_b + h_chord * sin_b
            return e_x, e_y

        # Fallback: closest point on locus arc to the −e1 ray (the ray
        # behind the player along the ship→target axis).
        # The locus circle centred at (D/2, h) intersects the e1 axis
        # at S = (0,0) and T = (D, 0). Going "left" along the major
        # arc from S puts the camera at the leftmost point of the
        # circle: (D/2 − r, h). That's the fallback eye.
        return (D / 2.0 - r, h)
```

- [ ] **Step 4: Strengthen the body-up-parallel branch in `_plane_basis`**

Replace the `if ulen < 1e-9:` branch with a proper perpendicular pick:

```python
        if ulen < 1e-9:
            # Body-up parallel to (T − S). Pick any unit vector
            # perpendicular to e1. Use the world-X axis unless e1 is
            # already aligned with it; then fall back to world-Y.
            if abs(e1.x) < 0.9:
                ax, ay, az = 1.0, 0.0, 0.0
            else:
                ax, ay, az = 0.0, 1.0, 0.0
            dot = ax*e1.x + ay*e1.y + az*e1.z
            px, py, pz = ax - dot*e1.x, ay - dot*e1.y, az - dot*e1.z
            plen = _math.sqrt(px*px + py*py + pz*pz)
            return e1, TGPoint3(px/plen, py/plen, pz/plen)
```

This violates "no world-Z" in the *seed direction*, but the result is normalised in the plane perpendicular to `e1` — the world axis is only used as an arbitrary tie-breaker when the player's body-up has nothing meaningful to contribute. No preferred world orientation enters the framing.

- [ ] **Step 5: Run, expect all geometry tests to pass**

Run: `uv run pytest tests/cameras/test_tracking_geometry.py -v`
Expected: all geometry tests green.

- [ ] **Step 6: Commit**

```bash
git add engine/cameras/tracking.py tests/cameras/test_tracking_geometry.py
git commit -m "feat(cameras): tracking solver — edge cases

Close-target fallback (d_chase ≥ D cot β): eye lands at the
leftmost point of the locus arc, behind the player along −e1.
Body-up parallel to ship→target: pick an arbitrary
perpendicular as the in-plane up, normalised in plane.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Position + rotation springs, `snap()`, `set_ship_radius()`

Add the eye position spring and basis rotation spring inside `_TrackingCamera`. Also wire `set_ship_radius` so the director can bind `d_chase` to the ship's actual radius. `snap()` clears both spring states.

**Files:**
- Modify: `engine/cameras/tracking.py`
- Create: `tests/cameras/test_tracking_springs.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/cameras/test_tracking_springs.py`:

```python
"""Unit tests for _TrackingCamera position + rotation springs."""
import math
import pytest


class _FakeShip:
    def __init__(self, loc, rot):
        self._loc, self._rot = loc, rot
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot


def _identity_setup():
    from engine.appc.math import TGPoint3, TGMatrix3
    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    t_loc = TGPoint3(0.0, 20.0, 0.0)
    return _FakeShip(s_loc, s_rot), _FakeShip(t_loc, s_rot)


def test_first_call_with_dt_seeds_springs_to_solver_output():
    from engine.cameras.tracking import _TrackingCamera

    tc = _TrackingCamera(); tc.d_chase = 10.0
    player, target = _identity_setup()

    eye_seeded, _, up_seeded = tc.compute(player=player, target=target, dt=1.0/60)
    # With springs seeded on first call, output equals the solver
    # output exactly — no lag.
    eye_solver, _, up_solver = tc.compute(player=player, target=target, dt=None)
    for got, want in zip(eye_seeded, eye_solver):
        assert got == pytest.approx(want, abs=1e-9)
    for got, want in zip(up_seeded, up_solver):
        assert got == pytest.approx(want, abs=1e-9)


def test_position_spring_lags_after_target_jump_then_converges():
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera(); tc.d_chase = 10.0

    # Seed at one target position.
    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    t_loc_a = TGPoint3(0.0, 20.0, 0.0)
    t_loc_b = TGPoint3(0.0, 200.0, 0.0)   # far jump

    player   = _FakeShip(s_loc, s_rot)
    target_a = _FakeShip(t_loc_a, s_rot)
    target_b = _FakeShip(t_loc_b, s_rot)

    # Seed.
    tc.compute(player=player, target=target_a, dt=1.0/60)
    # Jump the target. One frame after the jump, eye should still be
    # close to its old position (within 90% of pre-jump value, since
    # one frame at τ=0.25 gives α ≈ 1 − exp(−1/15) ≈ 0.0645).
    eye_pre, _, _ = tc.compute(player=player, target=target_a, dt=None)
    eye_one_frame, _, _ = tc.compute(player=player, target=target_b, dt=1.0/60)
    # Solver output for target_b directly:
    eye_solver_b, _, _ = _TrackingCamera()  # fresh, no spring
    fresh = _TrackingCamera(); fresh.d_chase = 10.0
    eye_solver_b, _, _ = fresh.compute(player=player, target=target_b, dt=None)

    # Lag check: smoothed eye much closer to pre-jump than to solver_b.
    def _dist(a, b): return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))
    assert _dist(eye_one_frame, eye_pre)      < 0.2 * _dist(eye_pre, eye_solver_b)

    # Convergence: after ~30 frames at dt=1/60 with τ=0.25, spring is
    # within 1% of target.
    for _ in range(30):
        tc.compute(player=player, target=target_b, dt=1.0/60)
    eye_settled, _, _ = tc.compute(player=player, target=target_b, dt=1.0/60)
    err = _dist(eye_settled, eye_solver_b)
    initial_err = _dist(eye_pre, eye_solver_b)
    assert err < 0.01 * initial_err


def test_snap_clears_spring_state():
    from engine.cameras.tracking import _TrackingCamera

    tc = _TrackingCamera(); tc.d_chase = 10.0
    player, target = _identity_setup()
    for _ in range(5):
        tc.compute(player=player, target=target, dt=1.0/60)
    tc.snap()
    assert tc._smoothed_eye   is None
    assert tc._smoothed_basis is None


def test_set_ship_radius_updates_d_chase():
    from engine.cameras.tracking import _TrackingCamera
    from engine.cameras           import CAM_BACK_RADII, CAM_UP_RADII
    tc = _TrackingCamera()
    tc.set_ship_radius(2.0)
    expected = math.sqrt(CAM_BACK_RADII**2 + CAM_UP_RADII**2) * 2.0
    assert tc.d_chase == pytest.approx(expected)
```

- [ ] **Step 2: Run, watch them fail**

Run: `uv run pytest tests/cameras/test_tracking_springs.py -v`
Expected: failures across the board (no spring logic, no snap, no set_ship_radius).

- [ ] **Step 3: Implement springs and helpers**

In `engine/cameras/tracking.py`, update the imports and class body:

```python
import math as _math

from engine.cameras import (
    EXTERIOR_FOV_Y_RAD, CAM_BACK_RADII, CAM_UP_RADII,
)
```

(If Task 2.5 was skipped — i.e. `CAM_*` still lives in `host_loop.py` — import them from `engine.host_loop` instead.)

Modify `_TrackingCamera.__init__` and add `set_ship_radius`, `snap`, and the spring helpers:

```python
    def __init__(self):
        self.v_fov_rad       = EXTERIOR_FOV_Y_RAD
        self.d_chase         = 1.0
        self._smoothed_eye   = None
        self._smoothed_basis = None

    def set_ship_radius(self, radius: float) -> None:
        radius = max(radius, 1e-6)
        self.d_chase = _math.sqrt(CAM_BACK_RADII**2 + CAM_UP_RADII**2) * radius

    def snap(self) -> None:
        """Drop both smoothing states. Next compute() will seed from
        the solver output directly. Use on mode-enter, mission swap,
        teleport / warp exit."""
        self._smoothed_eye   = None
        self._smoothed_basis = None
```

Update `compute()` to apply the springs. After the solver block returns `(eye_solver, forward_solver, up_solver)` — refactor the function so the solver result is built into intermediate variables — add:

```python
        # Build the solver basis matrix (columns: right, forward, up).
        from engine.appc.math import TGPoint3, TGMatrix3
        right_solver = (
            up_solver[1]*forward[2] - up_solver[2]*forward[1],
            up_solver[2]*forward[0] - up_solver[0]*forward[2],
            up_solver[0]*forward[1] - up_solver[1]*forward[0],
        )
        basis_solver = TGMatrix3()
        basis_solver.SetCol(0, TGPoint3(*right_solver))
        basis_solver.SetCol(1, TGPoint3(*forward))
        basis_solver.SetCol(2, TGPoint3(*up_solver))

        if dt is None:
            # No springs — return solver output directly. (Used by
            # geometry tests in Tasks 6–8.)
            eye_out   = eye
            forward_o = forward
            up_o      = up_solver
        else:
            eye_out, basis_out = self._advance_springs(
                eye_solver=eye, basis_solver=basis_solver, dt=dt,
            )
            f = basis_out.GetCol(1); u = basis_out.GetCol(2)
            forward_o = (f.x, f.y, f.z)
            up_o      = (u.x, u.y, u.z)

        look_at = (
            eye_out[0] + forward_o[0],
            eye_out[1] + forward_o[1],
            eye_out[2] + forward_o[2],
        )
        return eye_out, look_at, up_o
```

(You'll need to rename the local `up` from Task 7 to `up_solver` and the local `eye` to `eye_solver` for clarity inside the new structure. The final return uses `eye_out, look_at, up_o`.)

Add the spring engine:

```python
    def _advance_springs(self, *, eye_solver, basis_solver, dt):
        """Apply position + rotation springs. Seeds on first call.

        Returns (eye_smoothed_tuple, basis_smoothed_TGMatrix3).
        """
        from engine.appc.math import TGPoint3, TGMatrix3

        if self._smoothed_eye is None:
            self._smoothed_eye = list(eye_solver)
        if self._smoothed_basis is None:
            self._smoothed_basis = TGMatrix3()
            for i in range(3):
                self._smoothed_basis.SetCol(i, basis_solver.GetCol(i))

        # Position spring.
        alpha_p = 1.0 - _math.exp(-dt / self.POS_SPRING_TAU_S) if dt > 0.0 else 0.0
        for i in range(3):
            self._smoothed_eye[i] += alpha_p * (eye_solver[i] - self._smoothed_eye[i])

        # Rotation spring — Gram-Schmidt re-orthonormalisation.
        alpha_r = 1.0 - _math.exp(-dt / self.ROT_SPRING_TAU_S) if dt > 0.0 else 0.0
        blended = [None, None, None]
        for i in range(3):
            s = self._smoothed_basis.GetCol(i)
            l = basis_solver.GetCol(i)
            blended[i] = TGPoint3(
                s.x + alpha_r * (l.x - s.x),
                s.y + alpha_r * (l.y - s.y),
                s.z + alpha_r * (l.z - s.z),
            )

        def _norm(v):
            m = _math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z)
            return TGPoint3(v.x/m, v.y/m, v.z/m)

        f = _norm(blended[1])
        u_in = blended[2]
        dot_uf = u_in.x*f.x + u_in.y*f.y + u_in.z*f.z
        u = _norm(TGPoint3(
            u_in.x - dot_uf * f.x,
            u_in.y - dot_uf * f.y,
            u_in.z - dot_uf * f.z,
        ))
        r = TGPoint3(
            f.y*u.z - f.z*u.y,
            f.z*u.x - f.x*u.z,
            f.x*u.y - f.y*u.x,
        )
        self._smoothed_basis.SetCol(0, r)
        self._smoothed_basis.SetCol(1, f)
        self._smoothed_basis.SetCol(2, u)
        return tuple(self._smoothed_eye), self._smoothed_basis
```

- [ ] **Step 4: Run all tracking tests**

Run: `uv run pytest tests/cameras/test_tracking_springs.py tests/cameras/test_tracking_geometry.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/tracking.py tests/cameras/test_tracking_springs.py
git commit -m "feat(cameras): tracking springs + snap + set_ship_radius

Position spring (τ = 0.25s) on the eye, rotation spring (τ = 0.50s)
on the basis with per-frame Gram-Schmidt re-orthonormalisation.
snap() clears both. set_ship_radius binds d_chase to the player
ship's GetRadius() in the same units as _ChaseCamera's distance.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: Director — TRACKING mode dispatch, `C`-key toggle, target-loss fallback, host_loop integration

This is the biggest single task because the changes are tightly coupled — the director's mode flag, the host_loop's `C`-key handler, and the removal of the old target-lock state on `_ChaseCamera` all need to land together.

**Files:**
- Modify: `engine/cameras/director.py`
- Modify: `engine/cameras/chase.py` (remove target-lock fields)
- Modify: `engine/host_loop.py` (route `C` through director, drop `cam_control` alias)
- Modify: `tests/cameras/test_director.py`
- Modify: `tests/cameras/test_chase.py` (remove tests for deleted target-lock fields)

- [ ] **Step 1: Write the failing director tests**

Append to `tests/cameras/test_director.py`:

```python
class _FakeShipWithTarget:
    def __init__(self, target):
        from engine.appc.math import TGPoint3, TGMatrix3
        self._loc = TGPoint3(0.0, 0.0, 0.0)
        self._rot = TGMatrix3()
        self._target = target
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetTarget(self):        return self._target


def _make_target_at(x=0.0, y=20.0, z=0.0):
    from engine.appc.math import TGPoint3, TGMatrix3
    class _T:
        def __init__(self):
            self._loc = TGPoint3(x, y, z); self._rot = TGMatrix3()
        def GetWorldLocation(self): return self._loc
        def GetWorldRotation(self): return self._rot
    return _T()


def test_toggle_chase_to_tracking_flips_mode_and_snaps_tracking():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0)
    d.tracking.set_ship_radius(1.0)
    # Warm up tracking spring state so we can verify snap clears it.
    d.tracking._smoothed_eye = [1.0, 2.0, 3.0]
    d.toggle_mode(player=_FakeShipWithTarget(target=_make_target_at()))
    assert d.mode is CameraMode.TRACKING
    assert d.tracking._smoothed_eye is None


def test_toggle_tracking_to_chase_flips_mode_preserving_chase_state():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.toggle_mode(player=_FakeShipWithTarget(target=_make_target_at()))
    d.chase.orbit_yaw_rad = 1.2
    d.toggle_mode(player=_FakeShipWithTarget(target=_make_target_at()))
    assert d.mode is CameraMode.CHASE
    assert d.chase.orbit_yaw_rad == pytest.approx(1.2)


def test_toggle_in_chase_with_no_target_stays_in_chase():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.toggle_mode(player=_FakeShipWithTarget(target=None))
    assert d.mode is CameraMode.CHASE


def test_target_lost_mid_tracking_falls_back_to_chase_on_compute():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)

    p_with    = _FakeShipWithTarget(target=_make_target_at())
    p_without = _FakeShipWithTarget(target=None)

    d.toggle_mode(player=p_with)
    assert d.mode is CameraMode.TRACKING

    # Player loses target.
    eye, look_at, up = d.compute(player=p_without, dt=1.0/60)
    assert d.mode is CameraMode.CHASE   # durable switch (spec §5)


def test_snap_propagates_to_both_cameras():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.chase._smoothed_rot = "non-None placeholder"
    d.tracking._smoothed_eye = [1.0, 2.0, 3.0]
    d.tracking._smoothed_basis = "non-None placeholder"
    d.snap()
    assert d.chase._smoothed_rot     is None
    assert d.tracking._smoothed_eye  is None
    assert d.tracking._smoothed_basis is None


def test_tracking_dispatch_returns_solver_output_when_target_present():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    p = _FakeShipWithTarget(target=_make_target_at())
    d.toggle_mode(player=p)
    eye, look_at, up = d.compute(player=p, dt=1.0/60)
    # Just check finiteness — geometry covered in Task 6–8.
    for v in (*eye, *look_at, *up):
        assert math.isfinite(v)
```

- [ ] **Step 2: Run, watch them fail**

Run: `uv run pytest tests/cameras/test_director.py -v`
Expected: all new tests fail (`toggle_mode` doesn't exist, dispatch raises for TRACKING, etc.).

- [ ] **Step 3: Implement `_CameraDirector` mode transitions and dispatch**

Replace `engine/cameras/director.py` with:

```python
"""Camera mode dispatch.

The director owns the mode flag, the C-key toggle, and the
target-loss fallback. compute() forwards to the active camera. Mode
transitions snap the receiving camera so the first frame in the new
mode lands directly on the solver pose without springing in from
stale state.
"""
from enum import Enum

from engine.cameras.chase    import _ChaseCamera
from engine.cameras.tracking import _TrackingCamera


class CameraMode(Enum):
    CHASE    = "chase"
    TRACKING = "tracking"


class _CameraDirector:
    def __init__(self):
        self.mode     = CameraMode.CHASE
        self.chase    = _ChaseCamera()
        self.tracking = _TrackingCamera()

    # ── mode transitions ─────────────────────────────────────────────

    def toggle_mode(self, *, player) -> None:
        """C-key handler. Chase ↔ Tracking, but only enter Tracking if
        the player has a valid (non-self) target."""
        if self.mode is CameraMode.CHASE:
            tgt = self._valid_target(player)
            if tgt is None:
                return  # no target → stay in Chase
            self.mode = CameraMode.TRACKING
            self.tracking.snap()
        else:
            self.mode = CameraMode.CHASE

    def snap(self) -> None:
        """Propagate snap() to both cameras. Use on mission swap /
        hard cut."""
        self.chase.snap()
        self.tracking.snap()

    # ── per-frame dispatch ───────────────────────────────────────────

    def compute(self, *, player, dt):
        loc = player.GetWorldLocation()
        rot = player.GetWorldRotation()
        if self.mode is CameraMode.TRACKING:
            tgt = self._valid_target(player)
            if tgt is None:
                # Target lost → durable fallback to Chase.
                self.mode = CameraMode.CHASE
            else:
                return self.tracking.compute(player=player, target=tgt, dt=dt)
        return self.chase.compute_camera(loc, rot, dt=dt)

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _valid_target(player):
        get_target = getattr(player, "GetTarget", None)
        if get_target is None:
            return None
        tgt = get_target()
        if tgt is None or tgt is player:
            return None
        return tgt
```

- [ ] **Step 4: Remove `_ChaseCamera`'s target-lock fields**

Now that the director owns the Chase↔Tracking decision, `_ChaseCamera` no longer needs `target_lock_enabled`, `target_lock_bias`, `target_lock_z_lift`, `look_up_offset`, or `lock_to_target()`. These were Chase-Mode hacks that the new architecture replaces with the Tracking class.

In `engine/cameras/chase.py`:

- In `__init__`, remove the assignments:
  ```python
        self.look_up_offset     = 0.0
        self.target_lock_enabled = True
        self.target_lock_bias    = 0.15
  ```
- In `set_ship_radius`, remove:
  ```python
        self.look_up_offset      = CAM_LOOK_UP_RADII * radius
        self.target_lock_z_lift  = CAM_TARGET_LOCK_LIFT_RADII * radius
  ```
- Delete the entire `lock_to_target` method.
- In `apply`, replace the `C`-key branch:
  ```python
        if h.key_pressed(h.keys.KEY_C):
            self.reset_orbit()
            self.target_lock_enabled = False
            return
  ```
  with:
  ```python
        # C-key is now handled by _CameraDirector.toggle_mode; the
        # chase camera only owns orbit reset on its own dedicated
        # binding (none today — kept as a no-op until a future spec
        # rewires it).
        pass
  ```
- In `compute_camera`, remove the `look_up_offset` / `lu` terms:
  ```python
        lu = self.look_up_offset
        eye = (
            ship_loc.x + ox * rgt.x + oy * fwd.x + oz * up.x + lu * up.x,
            ...
        )
        target = (
            ship_loc.x + lu * up.x,
            ...
        )
  ```
  becomes:
  ```python
        eye = (
            ship_loc.x + ox * rgt.x + oy * fwd.x + oz * up.x,
            ship_loc.y + ox * rgt.y + oy * fwd.y + oz * up.y,
            ship_loc.z + ox * rgt.z + oy * fwd.z + oz * up.z,
        )
        target = (ship_loc.x, ship_loc.y, ship_loc.z)
  ```

Also remove the now-unused `CAM_LOOK_UP_RADII` and `CAM_TARGET_LOCK_LIFT_RADII` constants from `engine/cameras/__init__.py` (or `engine/host_loop.py` if Task 2.5 didn't fire), along with any imports of them.

- [ ] **Step 5: Update the chase tests for the removed fields**

In `tests/cameras/test_chase.py`:

- Delete `test_target_lock_enabled_by_default` (the attribute no longer exists).
- Delete `test_C_resets_orbit_and_disables_target_lock` (C no longer hits `_ChaseCamera.apply`).
- Delete `test_lock_to_target_resets_orbit_and_enables_lock` (`lock_to_target` removed).
- In `test_compute_camera_at_defaults_at_origin_identity_rotation`, drop the `look_up_offset` term from the expected `target` and `eye_z`:
  ```python
      assert eye[2] == pytest.approx(CAM_UP_RADII, abs=1e-3)
      assert target == pytest.approx((0.0, 0.0, 0.0))
  ```
- Similarly in `test_compute_camera_offset_is_in_ship_body_frame`:
  ```python
      expected_eye_z = CAM_UP_RADII
  ```

- [ ] **Step 6: Rewire host_loop's `C` key through the director**

In `engine/host_loop.py`:

- Delete the `cam_control = director.chase` alias (Task 4 introduced it). Replace every `cam_control.` call with the appropriate `director.chase.` or `director.` call:
  - `cam_control.set_ship_radius(...)` → `director.chase.set_ship_radius(...); director.tracking.set_ship_radius(...)` (sized to the same player radius).
  - `cam_control.apply(dt, _h, scroll_y)` → keep as `director.chase.apply(dt, _h, scroll_y)` (Chase Mode still consumes its own orbit / zoom keys).
  - `cam_control.snap()` (the mission-swap path) → `director.snap()`.
- After `director.chase.apply(...)` (or wherever the per-frame `_h.key_pressed` calls live), add:
  ```python
  if _h.key_pressed(_h.keys.KEY_C):
      director.toggle_mode(player=controller.session.player)
  ```

Locate the existing `KEY_C` press handler in `_ChaseCamera.apply` (now a no-op after Step 4) and the surrounding host-loop input dispatch to find the right insertion point. The press should fire once per key-down event, matching `key_pressed` semantics.

- [ ] **Step 7: Run all tests**

Run: `uv run pytest tests/cameras/ -v`
Expected: all green (chase, director, tracking-geometry, tracking-springs).

Run: `uv run pytest tests/host/ -x --tb=short`
Expected: all green. If any test still imports the removed `target_lock_*` attributes, it needs deleting or updating — those tests were validating a now-removed code path.

- [ ] **Step 8: Smoke-check the host loop boots**

Run: `uv run python -c "from engine.host_loop import _compute_camera; from engine.cameras import _CameraDirector; print('ok')"`
Expected: `ok`.

- [ ] **Step 9: Commit**

```bash
git add engine/cameras/director.py engine/cameras/chase.py engine/cameras/__init__.py engine/host_loop.py tests/cameras/test_director.py tests/cameras/test_chase.py
git commit -m "feat(cameras): Tracking dispatch, C-key toggle, target-loss fallback

Director toggles Chase ↔ Tracking on C-key (requires valid target
to enter Tracking). Mid-Tracking target loss durably reverts to
Chase. snap() propagates to both cameras for mission swaps.
_ChaseCamera's target_lock_* fields, lock_to_target(), and
look_up_offset are removed — the director now owns mode and
the tracking camera owns framing.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 11: Manual verification

Build and run the host loop. Verify that Chase Mode looks unchanged from before the refactor and Tracking Mode produces framing that matches the reference screenshots.

**Files:** none modified — this is a manual run.

- [ ] **Step 1: Rebuild the renderer**

Run:
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: clean build, `build/dauntless` exists.

- [ ] **Step 2: Run the host**

Run: `./build/dauntless`

- [ ] **Step 3: Chase Mode parity check**

With no target selected, verify:
- Camera sits behind the player ship along its body-Y forward, slightly above (matches pre-refactor behaviour).
- Arrow keys orbit around the ship.
- Scroll wheel zooms in/out.
- Banking the ship rolls the camera with it.

If any of these regress, the cause is in `_ChaseCamera` — most likely the changes from Task 10 Step 4 (`look_up_offset` removal). The chase tests catch most of this; eyeball the mission for any residual issue.

- [ ] **Step 4: Tracking Mode framing check**

Select a target (`T` key cycles), then press `C`. Verify:
- The camera snaps to the new framing without springing through the chase pose.
- The target sits roughly 25% above screen-centre, the player roughly 25% below.
- The framing is consistent whether the target is 5 km or 50 km away (intercept distance changes target size on screen but NOT its screen-Y position).
- Rolling the ship banks the camera with it; the ship still appears "right-side-up" on screen because camera-up follows ship-up.
- Pressing `C` again returns to Chase Mode, restoring the prior orbit angles.
- Pressing `T` to switch targets does not exit Tracking Mode; the camera glides (position spring) toward the new framing.
- Destroying the target (in combat) drops back to Chase Mode durably.

- [ ] **Step 5: Compare against the reference screenshots**

Side-by-side against the screenshots from the original game:
- Player saucer in the lower 50% of the frame: ✓ / ✗
- Target reticle / sprite in the upper 50%: ✓ / ✗
- Camera "rotates with" the ship without inverting on rolls: ✓ / ✗

If any item fails, the most likely culprits and fixes:
- Player not at −25%: tune `_TrackingCamera.y_p` at the top of `engine/cameras/tracking.py`.
- Target not at +25%: tune `_TrackingCamera.y_t`.
- Position spring feels too laggy / too snappy: adjust `POS_SPRING_TAU_S`.
- Rotation spring feels too laggy / too snappy: adjust `ROT_SPRING_TAU_S`.
- Close target produces weird framing: revisit the fallback in `_solve_eye_2d` (spec §3 step 5).

These are all single-constant edits in `engine/cameras/tracking.py`; no tests change unless the new tuning shifts the precision of existing assertions.

- [ ] **Step 6: Commit any tuning changes**

If Step 5 required constant tuning:

```bash
git add engine/cameras/tracking.py
git commit -m "tune(cameras): tracking framing constants from manual playtest

<one-line description of what changed and why>

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

If no tuning needed, no commit for this task.

---

## Self-review

Skimmed the plan against the spec:

- §1 Goals → Tasks 1–11 collectively implement everything in scope; nothing out-of-scope.
- §2 Architecture → Task 1 (skeleton), Task 2 (chase rename), Task 3 (director CHASE-only), Task 5 (tracking class), Task 10 (full dispatch).
- §3 Geometry → Tasks 6 (eye placement), 7 (basis), 8 (edge cases). Plane construction, inscribed-angle solver, basis from eye, close-target fallback, body-up-parallel singularity all have implementation + tests.
- §4 Springs → Task 9. Both springs, both time constants, `snap()`.
- §5 Mode transitions → Task 10. Chase→Tracking with snap, Tracking→Chase preserving state, target loss durable, mission swap snap propagation.
- §6 Testing → Each task includes the matching tests inline.

Placeholder scan: every step has the actual code or actual command. No "TBD", no "similar to Task N". The one structural ellipsis is the `... (rest of the class body ...)` in Task 2 Step 3, which is explicitly annotated as a verbatim paste of the cut-out source and not a placeholder for new code.

Type consistency check:
- `_CameraDirector.compute(player, dt)` — same signature across Tasks 3, 5, 10. ✓
- `_TrackingCamera.compute(player, target, dt)` — same across Tasks 5, 6, 9. ✓
- `set_ship_radius(radius)` — same on both cameras. ✓
- `snap()` — same on both cameras and director. ✓
- `CameraMode.CHASE` / `CameraMode.TRACKING` — used consistently. ✓
- `y_p`, `y_t`, `d_chase`, `v_fov_rad` — same names throughout. ✓
