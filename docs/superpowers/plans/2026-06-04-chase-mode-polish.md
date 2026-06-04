# Chase Mode Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the three BC tactical-camera bindings missing from free-orbit Chase Mode — `=`/`−` sticky zoom, `Shift`+mouse orbit, and `V`-held Reverse Chase — all sitting on `_ChaseCamera` with thin director pass-through.

**Architecture:** Each feature is a focused extension of `_ChaseCamera`. Sticky zoom adds `zoom_in`/`zoom_out` methods. Shift+mouse adds `apply_mouse_delta(dx, dy)`. Reverse Chase is a hold-key flag (`reverse_active`) that adds π to the effective orbit yaw — same hold-pattern as `Z` (ZoomTarget). Director gains `start_reverse`/`end_reverse` and extends its existing `zoom_in/zoom_out` to delegate to chase in CHASE mode (dropping the deferred no-op carve-out).

**Tech Stack:** Python 3.13, pytest, BC's column-vector `TGMatrix3` / `TGPoint3`. C++ stub for three new GLFW key bindings.

**Spec:** [`docs/superpowers/specs/2026-06-04-chase-mode-polish-design.md`](../specs/2026-06-04-chase-mode-polish-design.md)

---

## File Structure

```
engine/cameras/chase.py          — Reverse flag, MOUSE_SENSITIVITY, 5 new methods,
                                    compute_camera yaw flip, snap reset
engine/cameras/director.py       — extend zoom_in/zoom_out, add start/end_reverse,
                                    mode-transition cleanup
engine/host_loop.py              — v_held_prev init, V hold + Shift+mouse handlers
native/src/host/host_bindings.cc — expose KEY_V, KEY_LEFT_SHIFT, KEY_RIGHT_SHIFT

tests/cameras/test_chase.py      — extend with Reverse + sticky zoom + Shift+mouse tests
tests/cameras/test_director.py   — extend with director zoom delegation, reverse, cleanup
```

`_ChaseCamera` grows from ~180 to ~230 lines — still one focused class. Director gains ~25 lines. No new files in `engine/`.

---

## Branch setup

Before Task 1: create a feature branch off `main`:

```bash
git checkout main
git checkout -b chase-mode-polish
```

This isolates the implementation from any other in-progress branches.

---

## Task 1: `_ChaseCamera` Reverse Chase flag + `compute_camera` yaw flip

Hold-key flag plus one math change. TDD.

**Files:**
- Modify: `engine/cameras/chase.py`
- Modify: `tests/cameras/test_chase.py`

- [ ] **Step 1: Verify baseline tests pass**

Run: `uv run pytest tests/cameras/ -q`
Expected: all green (count varies by prior task state; record the baseline).

- [ ] **Step 2: Write failing tests**

Append to `tests/cameras/test_chase.py`:

```python
def test_reverse_active_defaults_to_false():
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    assert cc.reverse_active is False


def test_enter_exit_reverse_toggles_flag():
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    assert cc.reverse_active is False
    cc.enter_reverse()
    assert cc.reverse_active is True
    cc.exit_reverse()
    assert cc.reverse_active is False
    # Idempotent.
    cc.enter_reverse()
    cc.enter_reverse()
    assert cc.reverse_active is True
    cc.exit_reverse()
    cc.exit_reverse()
    assert cc.reverse_active is False


def test_reverse_active_flips_eye_to_ship_front():
    """With identity ship and default orbit (yaw=0, pitch≈atan2(0.25, 1.5)):
    behind-ship eye is at (0, -CAM_BACK_RADII, CAM_UP_RADII). Reverse flips
    sign of x and y components; z component preserved (sign flip is in the
    (ox, oy) body-frame plane only)."""
    from engine.cameras.chase  import _ChaseCamera
    from engine.cameras        import CAM_BACK_RADII, CAM_UP_RADII
    from engine.appc.math      import TGPoint3, TGMatrix3

    cc = _ChaseCamera()
    loc = TGPoint3(0.0, 0.0, 0.0); rot = TGMatrix3()

    eye_normal, _, _ = cc.compute_camera(loc, rot)
    cc.enter_reverse()
    eye_reverse, _, _ = cc.compute_camera(loc, rot)

    # x and y flip sign; z is unchanged.
    assert eye_reverse[0] == pytest.approx(-eye_normal[0], abs=1e-9)
    assert eye_reverse[1] == pytest.approx(-eye_normal[1], abs=1e-9)
    assert eye_reverse[2] == pytest.approx( eye_normal[2], abs=1e-9)


def test_reverse_inactive_eye_unchanged_from_baseline():
    """Regression: setting and then unsetting reverse_active leaves eye
    identical to a fresh camera."""
    from engine.cameras.chase import _ChaseCamera
    from engine.appc.math      import TGPoint3, TGMatrix3

    cc1 = _ChaseCamera()
    cc2 = _ChaseCamera()
    cc2.enter_reverse()
    cc2.exit_reverse()

    loc = TGPoint3(0.0, 0.0, 0.0); rot = TGMatrix3()
    eye1, _, _ = cc1.compute_camera(loc, rot)
    eye2, _, _ = cc2.compute_camera(loc, rot)
    assert eye1 == pytest.approx(eye2, abs=1e-12)


def test_reverse_composes_with_orbit_yaw():
    """yaw_effective = orbit_yaw_rad + π. With orbit_yaw_rad = π/4 + π = 5π/4,
    cos/sin produce the same result as a single +π/4 yaw with reverse on."""
    import math
    from engine.cameras.chase import _ChaseCamera
    from engine.appc.math      import TGPoint3, TGMatrix3

    cc_combined = _ChaseCamera()
    cc_combined.orbit_yaw_rad = math.pi / 4
    cc_combined.enter_reverse()

    cc_yaw_only = _ChaseCamera()
    cc_yaw_only.orbit_yaw_rad = math.pi / 4 + math.pi

    loc = TGPoint3(0.0, 0.0, 0.0); rot = TGMatrix3()
    eye_c, _, _ = cc_combined.compute_camera(loc, rot)
    eye_y, _, _ = cc_yaw_only.compute_camera(loc, rot)

    assert eye_c == pytest.approx(eye_y, abs=1e-12)
```

Add `import pytest` and `import math` at the top of the test file if not already present.

- [ ] **Step 3: Run, watch them fail**

Run: `uv run pytest tests/cameras/test_chase.py -v`
Expected: the 5 new tests fail (`AttributeError: '_ChaseCamera' object has no attribute 'reverse_active'`).

- [ ] **Step 4: Implement in `engine/cameras/chase.py`**

Add `reverse_active = False` to `__init__`. Find:

```python
    def __init__(self):
        self.orbit_yaw_rad      = self.DEFAULT_YAW_RAD
        self.orbit_pitch_rad    = self.DEFAULT_PITCH_RAD
        self._smoothed_rot      = None  # seeded on first compute_camera(..., dt=...)
        self.set_ship_radius(1.0)
```

Replace with:

```python
    def __init__(self):
        self.orbit_yaw_rad      = self.DEFAULT_YAW_RAD
        self.orbit_pitch_rad    = self.DEFAULT_PITCH_RAD
        self.reverse_active     = False
        self._smoothed_rot      = None  # seeded on first compute_camera(..., dt=...)
        self.set_ship_radius(1.0)
```

Add the two methods after `snap`:

```python
    def enter_reverse(self) -> None:
        """V-key down: flip camera to in-front-of-ship perspective."""
        self.reverse_active = True

    def exit_reverse(self) -> None:
        """V-key up: return to behind-ship perspective."""
        self.reverse_active = False
```

Modify `compute_camera` to use `yaw_effective`. Find:

```python
        cy = _math.cos(self.orbit_yaw_rad)
        sy = _math.sin(self.orbit_yaw_rad)
```

Replace with:

```python
        yaw_effective = self.orbit_yaw_rad + (_math.pi if self.reverse_active else 0.0)
        cy = _math.cos(yaw_effective)
        sy = _math.sin(yaw_effective)
```

- [ ] **Step 5: Run, expect all pass**

Run: `uv run pytest tests/cameras/test_chase.py -v`
Expected: all green (existing tests + 5 new).

Run: `uv run pytest tests/cameras/ -q`
Expected: still all green.

- [ ] **Step 6: Commit**

```bash
git add engine/cameras/chase.py tests/cameras/test_chase.py
git commit -m "feat(cameras): _ChaseCamera Reverse Chase flag + yaw flip

reverse_active hold-key flag adds π to the effective orbit yaw,
flipping the camera to in-front-of-ship perspective. enter_reverse
/ exit_reverse toggle the flag. compute_camera uses yaw_effective
in place of orbit_yaw_rad for the body-frame projection;
everything else (pitch, distance, body-frame mapping, rotation
spring) is unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `_ChaseCamera` sticky zoom methods

`zoom_in` / `zoom_out` mirror the existing scroll-wheel zoom step. TDD.

**Files:**
- Modify: `engine/cameras/chase.py`
- Modify: `tests/cameras/test_chase.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/cameras/test_chase.py`:

```python
def test_chase_zoom_in_decreases_distance_by_factor():
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    seed = cc.distance
    cc.zoom_in()
    assert cc.distance == pytest.approx(seed * cc.ZOOM_FACTOR_PER_NOTCH)


def test_chase_zoom_out_increases_distance_by_factor():
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    seed = cc.distance
    cc.zoom_out()
    assert cc.distance == pytest.approx(seed / cc.ZOOM_FACTOR_PER_NOTCH)


def test_chase_zoom_in_clamps_at_distance_min():
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    cc.distance = cc.distance_min
    cc.zoom_in()
    assert cc.distance == pytest.approx(cc.distance_min)


def test_chase_zoom_out_clamps_at_distance_max():
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    cc.distance = cc.distance_max
    cc.zoom_out()
    assert cc.distance == pytest.approx(cc.distance_max)


def test_chase_zoom_round_trip_returns_to_original():
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    seed = cc.distance
    cc.zoom_in()
    cc.zoom_out()
    assert cc.distance == pytest.approx(seed, abs=1e-9)
```

- [ ] **Step 2: Run, watch them fail**

Run: `uv run pytest tests/cameras/test_chase.py -v -k "chase_zoom"`
Expected: all 5 fail (`AttributeError: '_ChaseCamera' object has no attribute 'zoom_in'`).

- [ ] **Step 3: Implement in `engine/cameras/chase.py`**

Add the two methods after `exit_reverse`:

```python
    def zoom_in(self) -> None:
        """=-key press. Decrease distance, clamped at distance_min."""
        self.distance = max(self.distance * self.ZOOM_FACTOR_PER_NOTCH,
                            self.distance_min)

    def zoom_out(self) -> None:
        """-key press. Increase distance, clamped at distance_max."""
        self.distance = min(self.distance / self.ZOOM_FACTOR_PER_NOTCH,
                            self.distance_max)
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/cameras/test_chase.py -v -k "chase_zoom"`
Expected: 5 green.

Run: `uv run pytest tests/cameras/ -q`
Expected: still all green.

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/chase.py tests/cameras/test_chase.py
git commit -m "feat(cameras): _ChaseCamera sticky zoom methods

zoom_in / zoom_out mirror the existing scroll-wheel step,
multiplying/dividing self.distance by ZOOM_FACTOR_PER_NOTCH and
clamping at the same distance_min / distance_max the wheel
respects. The director's zoom_in/zoom_out (Task 5) will delegate
here when in CHASE mode.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `_ChaseCamera.apply_mouse_delta` + `MOUSE_SENSITIVITY`

Shift+mouse drives orbit yaw/pitch additively. TDD.

**Files:**
- Modify: `engine/cameras/chase.py`
- Modify: `tests/cameras/test_chase.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/cameras/test_chase.py`:

```python
def test_chase_mouse_delta_yaw_additive():
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    seed = cc.orbit_yaw_rad
    cc.apply_mouse_delta(100.0, 0.0)
    assert cc.orbit_yaw_rad == pytest.approx(
        seed + 100.0 * cc.MOUSE_SENSITIVITY)


def test_chase_mouse_delta_pitch_subtractive_sign():
    """Convention: pitch -= dy × sensitivity. So +dy (mouse-down)
    decreases pitch; -dy (mouse-up) increases pitch."""
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    seed = cc.orbit_pitch_rad
    cc.apply_mouse_delta(0.0, 100.0)
    assert cc.orbit_pitch_rad == pytest.approx(
        seed - 100.0 * cc.MOUSE_SENSITIVITY)


def test_chase_mouse_delta_pitch_clamps_upper():
    """Sustained mouse-up (negative dy → +pitch) clamps at +PITCH_LIMIT_RAD."""
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    cc.apply_mouse_delta(0.0, -1.0e9)
    assert cc.orbit_pitch_rad == pytest.approx(cc.PITCH_LIMIT_RAD)


def test_chase_mouse_delta_pitch_clamps_lower():
    """Sustained mouse-down (positive dy → -pitch) clamps at -PITCH_LIMIT_RAD."""
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    cc.apply_mouse_delta(0.0, 1.0e9)
    assert cc.orbit_pitch_rad == pytest.approx(-cc.PITCH_LIMIT_RAD)


def test_chase_mouse_delta_zero_is_noop():
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    seed_yaw = cc.orbit_yaw_rad
    seed_pitch = cc.orbit_pitch_rad
    cc.apply_mouse_delta(0.0, 0.0)
    assert cc.orbit_yaw_rad == pytest.approx(seed_yaw)
    assert cc.orbit_pitch_rad == pytest.approx(seed_pitch)


def test_chase_mouse_and_arrow_compose():
    """Mouse delta + held arrow key advance the same orbit angles."""
    from engine.cameras.chase import _ChaseCamera

    class _FakeKeys:
        KEY_UP = 100; KEY_DOWN = 101; KEY_LEFT = 102; KEY_RIGHT = 103; KEY_C = 104
    class _FakeKeyReader:
        keys = _FakeKeys()
        def __init__(self): self.held = set()
        def key_state(self, key): return key in self.held
        def key_pressed(self, key): return False

    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    reader = _FakeKeyReader()
    reader.held.add(reader.keys.KEY_RIGHT)
    seed = cc.orbit_yaw_rad
    cc.apply(dt=1.0, h=reader, scroll_y=0.0)   # +TURN_RATE × 1.0 to yaw
    cc.apply_mouse_delta(100.0, 0.0)            # +100 × SENSITIVITY to yaw
    expected = seed + cc.TURN_RATE_RAD_PER_S + 100.0 * cc.MOUSE_SENSITIVITY
    assert cc.orbit_yaw_rad == pytest.approx(expected)
```

- [ ] **Step 2: Run, watch them fail**

Run: `uv run pytest tests/cameras/test_chase.py -v -k "mouse_delta"`
Expected: 6 failures (no `apply_mouse_delta` method, no `MOUSE_SENSITIVITY`).

- [ ] **Step 3: Implement in `engine/cameras/chase.py`**

Add the class constant near the other constants (after `SPRING_TAU_S`):

```python
    MOUSE_SENSITIVITY      = 0.005                              # radians per pixel
```

Add the method after `zoom_out`:

```python
    def apply_mouse_delta(self, dx: float, dy: float) -> None:
        """Shift+mouse: additive orbit input alongside arrow keys.
        Pitch clamped to the same ±PITCH_LIMIT_RAD as arrow input."""
        self.orbit_yaw_rad   += dx * self.MOUSE_SENSITIVITY
        self.orbit_pitch_rad -= dy * self.MOUSE_SENSITIVITY
        if self.orbit_pitch_rad >  self.PITCH_LIMIT_RAD:
            self.orbit_pitch_rad =  self.PITCH_LIMIT_RAD
        if self.orbit_pitch_rad < -self.PITCH_LIMIT_RAD:
            self.orbit_pitch_rad = -self.PITCH_LIMIT_RAD
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/cameras/test_chase.py -v -k "mouse_delta"`
Expected: 6 green.

Run: `uv run pytest tests/cameras/ -q`
Expected: still all green.

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/chase.py tests/cameras/test_chase.py
git commit -m "feat(cameras): _ChaseCamera apply_mouse_delta + MOUSE_SENSITIVITY

Shift+mouse delta drives orbit_yaw_rad / orbit_pitch_rad additively
alongside arrow keys. Pitch clamped to ±PITCH_LIMIT_RAD per the
existing arrow-input clamp. MOUSE_SENSITIVITY = 0.005 rad/px
(~0.29°/px) — roughly 2× the bridge camera; tunable post-playtest.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Extend `_ChaseCamera.snap()` to reset distance and reverse

Brings Chase snap semantics in line with Tracking's (which resets distance + sub-mode flag). TDD.

**Files:**
- Modify: `engine/cameras/chase.py`
- Modify: `tests/cameras/test_chase.py`

- [ ] **Step 1: Write failing test**

Append to `tests/cameras/test_chase.py`:

```python
def test_chase_snap_resets_distance_and_reverse():
    from engine.cameras.chase import _ChaseCamera
    cc = _ChaseCamera()
    cc.set_ship_radius(1.0)
    # Mutate everything.
    cc.distance = 12345.0
    cc.reverse_active = True
    cc._smoothed_rot = "non-None placeholder"
    cc.snap()
    assert cc.distance == pytest.approx(cc.default_distance)
    assert cc.reverse_active is False
    assert cc._smoothed_rot is None
```

- [ ] **Step 2: Run, watch it fail**

Run: `uv run pytest tests/cameras/test_chase.py -v -k "snap_resets_distance_and_reverse"`
Expected: fails (`distance` and `reverse_active` are not reset).

- [ ] **Step 3: Implement in `engine/cameras/chase.py`**

Replace the existing `snap`:

```python
    def snap(self) -> None:
        """Drop smoothed rotation, reset distance to default, and clear the
        reverse-active flag. Use on hard cuts (mission swap, teleport,
        warp exit)."""
        self._smoothed_rot  = None
        self.distance       = self.default_distance
        self.reverse_active = False
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/cameras/test_chase.py -v`
Expected: all green including the new test. The existing `test_spring_snap_clears_smoothing` should still pass (it only asserts `_smoothed_rot is None`).

Run: `uv run pytest tests/cameras/ -q`
Expected: still all green.

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/chase.py tests/cameras/test_chase.py
git commit -m "feat(cameras): extend _ChaseCamera.snap() to reset distance + reverse

snap() now resets distance to default_distance and clears
reverse_active in addition to the existing _smoothed_rot drop.
Brings Chase snap semantics in line with _TrackingCamera.snap()
which already resets its zoom state + sub-mode flag.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Director extends `zoom_in`/`zoom_out` to delegate to chase

Drops the deferred-Chase no-op carve-out from the tracking-zoom spec. TDD.

**Files:**
- Modify: `engine/cameras/director.py`
- Modify: `tests/cameras/test_director.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/cameras/test_director.py`:

```python
def test_director_zoom_in_in_chase_delegates_to_chase():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    seed_chase = d.chase.distance
    seed_tracking = d.tracking.d_chase_tracking
    d.zoom_in()
    assert d.chase.distance == pytest.approx(
        seed_chase * d.chase.ZOOM_FACTOR_PER_NOTCH)
    assert d.tracking.d_chase_tracking == pytest.approx(seed_tracking)


def test_director_zoom_out_in_chase_delegates_to_chase():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    seed_chase = d.chase.distance
    seed_tracking = d.tracking.d_chase_tracking
    d.zoom_out()
    assert d.chase.distance == pytest.approx(
        seed_chase / d.chase.ZOOM_FACTOR_PER_NOTCH)
    assert d.tracking.d_chase_tracking == pytest.approx(seed_tracking)
```

The existing `test_director_zoom_in_in_chase_is_noop` test from the tracking-zoom spec is now obsolete (it expected zoom_in to be a no-op in CHASE). Locate it and DELETE it.

Also the existing `test_director_zoom_in_in_tracking_delegates` and `test_director_zoom_out_in_tracking_delegates` should keep passing — verify after the implementation lands.

- [ ] **Step 2: Run, watch them fail**

Run: `uv run pytest tests/cameras/test_director.py -v -k "in_chase_delegates_to_chase"`
Expected: 2 fail (zoom currently no-ops in CHASE).

Also confirm the old `test_director_zoom_in_in_chase_is_noop` test is GONE:

Run: `git grep -n "test_director_zoom_in_in_chase_is_noop" tests/`
Expected: no matches.

- [ ] **Step 3: Implement in `engine/cameras/director.py`**

Replace the existing `zoom_in` and `zoom_out` methods. Find:

```python
    def zoom_in(self) -> None:
        """=-key press. Delegate to tracking when in Tracking mode.
        No-op in Chase (Chase sticky zoom is deferred)."""
        if self.mode is CameraMode.TRACKING:
            self.tracking.zoom_in()

    def zoom_out(self) -> None:
        """-key press. Symmetric to zoom_in."""
        if self.mode is CameraMode.TRACKING:
            self.tracking.zoom_out()
```

Replace with:

```python
    def zoom_in(self) -> None:
        """=-key press. Delegate to the active mode's camera."""
        if self.mode is CameraMode.TRACKING:
            self.tracking.zoom_in()
        else:  # CHASE
            self.chase.zoom_in()

    def zoom_out(self) -> None:
        """-key press. Symmetric to zoom_in."""
        if self.mode is CameraMode.TRACKING:
            self.tracking.zoom_out()
        else:  # CHASE
            self.chase.zoom_out()
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/cameras/test_director.py -v -k "zoom"`
Expected: the 2 new CHASE tests + the existing TRACKING tests all pass.

Run: `uv run pytest tests/cameras/ -q`
Expected: still all green.

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/director.py tests/cameras/test_director.py
git commit -m "feat(cameras): director.zoom_in/zoom_out delegate to chase in CHASE

Drops the deferred-Chase no-op carve-out from the tracking-zoom
spec. =/- now affects chase distance in CHASE mode and tracking
distance in TRACKING (the previous behaviour). Single coherent
zoom contract across both modes.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Director `start_reverse` / `end_reverse` + mode-transition cleanup

V-key director surface plus the same cleanup-on-leave-Tracking pattern used by ZoomTarget. TDD.

**Files:**
- Modify: `engine/cameras/director.py`
- Modify: `tests/cameras/test_director.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/cameras/test_director.py`:

```python
def test_director_start_reverse_in_chase_sets_flag():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.start_reverse()
    assert d.chase.reverse_active is True


def test_director_start_reverse_in_tracking_is_noop():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.mode = CameraMode.TRACKING
    d.start_reverse()
    assert d.chase.reverse_active is False


def test_director_end_reverse_clears_unconditionally():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.chase.reverse_active = True
    d.end_reverse()
    assert d.chase.reverse_active is False
    # Idempotent.
    d.end_reverse()
    assert d.chase.reverse_active is False


def test_c_toggle_chase_to_tracking_clears_reverse():
    """C-key explicit CHASE → TRACKING must clear reverse_active."""
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    p = _FakeShipWithTarget(target=_make_target_at())
    d.chase.reverse_active = True
    d.toggle_mode(player=p)
    assert d.mode is CameraMode.TRACKING
    assert d.chase.reverse_active is False


def test_target_auto_engage_clears_reverse():
    """Auto-engage Tracking on target acquisition must clear
    reverse_active so a future return to Chase doesn't surprise the
    user with leftover flip."""
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.chase.reverse_active = True

    p_with_target = _FakeShipWithTarget(target=_make_target_at())
    d.compute(player=p_with_target, dt=1.0/60)  # auto-engage
    assert d.mode is CameraMode.TRACKING
    assert d.chase.reverse_active is False


def test_director_snap_resets_chase_reverse():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.chase.reverse_active = True
    d.snap()
    assert d.chase.reverse_active is False
```

- [ ] **Step 2: Run, watch them fail**

Run: `uv run pytest tests/cameras/test_director.py -v -k "reverse or auto_engage"`
Expected: 6 fail (`start_reverse`/`end_reverse` don't exist; cleanup paths don't fire).

- [ ] **Step 3: Implement in `engine/cameras/director.py`**

Add two new methods. Place them in the zoom-controls section, after `end_zoom_target`:

```python
    def start_reverse(self) -> None:
        """V-key down. Enter Reverse Chase if currently in CHASE mode.
        No-op in Tracking (V is Chase-only per spec §1)."""
        if self.mode is CameraMode.CHASE:
            self.chase.enter_reverse()

    def end_reverse(self) -> None:
        """V-key up. Idempotent."""
        self.chase.exit_reverse()
```

In `toggle_mode`, modify the CHASE → TRACKING branch. Find:

```python
        if self.mode is CameraMode.CHASE:
            tgt = self._valid_target(player)
            if tgt is None:
                return  # no target → stay in Chase
            self.mode = CameraMode.TRACKING
            self.tracking.snap()
            self._opted_out_target = None
```

Replace with:

```python
        if self.mode is CameraMode.CHASE:
            tgt = self._valid_target(player)
            if tgt is None:
                return  # no target → stay in Chase
            self.mode = CameraMode.TRACKING
            self.tracking.snap()
            self._opted_out_target = None
            self.chase.exit_reverse()
```

In `compute`'s auto-engage branch, modify the CHASE → TRACKING path. Find:

```python
            elif tgt is not self._opted_out_target:
                self.mode = CameraMode.TRACKING
                self.tracking.snap()
                self._opted_out_target = None
                return self.tracking.compute(player=player, target=tgt, dt=dt)
```

Replace with:

```python
            elif tgt is not self._opted_out_target:
                self.mode = CameraMode.TRACKING
                self.tracking.snap()
                self._opted_out_target = None
                self.chase.exit_reverse()
                return self.tracking.compute(player=player, target=tgt, dt=dt)
```

`director.snap()` already propagates to `chase.snap()`, which (after Task 4) resets `reverse_active`. No further change needed there.

- [ ] **Step 4: Run, expect pass**

Run: `uv run pytest tests/cameras/test_director.py -v`
Expected: all green.

Run: `uv run pytest tests/cameras/ -q`
Expected: still all green.

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/director.py tests/cameras/test_director.py
git commit -m "feat(cameras): director start/end_reverse + Tracking-entry cleanup

start_reverse delegates to chase.enter_reverse() only when in
CHASE; end_reverse always clears. CHASE → TRACKING transitions
(both C-toggle and auto-engage) now call chase.exit_reverse()
so a future return to Chase doesn't surprise the user with a
stale reverse flag. director.snap() already propagates the
clear via chase.snap().

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Native key bindings for `KEY_V`, `KEY_LEFT_SHIFT`, `KEY_RIGHT_SHIFT`

Three GLFW key constants in the C++ bindings. Requires a CMake rebuild.

**Files:**
- Modify: `native/src/host/host_bindings.cc`

- [ ] **Step 1: Add the three constants**

In `native/src/host/host_bindings.cc`, locate the existing `KEY_Z` / `KEY_EQUAL` / `KEY_MINUS` block added by the tracking-zoom spec (around line 783–785 — confirm via `grep -n "KEY_Z\|KEY_EQUAL" native/src/host/host_bindings.cc`).

Append three new lines after that block (keeping alphabetical-ish grouping with the existing letter keys):

```cpp
    keys.attr("KEY_V")           = GLFW_KEY_V;
    keys.attr("KEY_LEFT_SHIFT")  = GLFW_KEY_LEFT_SHIFT;
    keys.attr("KEY_RIGHT_SHIFT") = GLFW_KEY_RIGHT_SHIFT;
```

(`KEY_LEFT_SUPER` and `KEY_LEFT_CONTROL` already exist — confirm `KEY_LEFT_SHIFT` is not already there with `grep -n "KEY_LEFT_SHIFT" native/src/host/host_bindings.cc`. If present, skip that line.)

- [ ] **Step 2: Rebuild**

Run:
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: clean build. `build/dauntless` and `build/python/_open_stbc_host.cpython-*.so` exist. Warnings about macOS version mismatches and OpenAL are pre-existing.

- [ ] **Step 3: Smoke-check the new constants**

Run:
```bash
uv run python -c "import _dauntless_host as h; print(h.keys.KEY_V, h.keys.KEY_LEFT_SHIFT, h.keys.KEY_RIGHT_SHIFT)"
```
Expected: three integer values (GLFW keycodes). If `AttributeError`, the build picked up a stale `.so` — delete `build/python/_open_stbc_host*.so` and rebuild.

- [ ] **Step 4: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(host): expose KEY_V, KEY_LEFT_SHIFT, KEY_RIGHT_SHIFT bindings

GLFW keycodes for the upcoming Chase Mode polish handlers in
host_loop: V hold (Reverse Chase) and Shift+mouse (orbit
modifier).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Host-loop wiring (V hold + Shift+mouse + mouse-delta drain)

Wire all three new bindings into the run loop. Same insertion point as the existing C/Z/=/- handlers.

**Files:**
- Modify: `engine/host_loop.py`

- [ ] **Step 1: Locate the existing C/Z/zoom block**

Run: `grep -n "z_held_prev\|KEY_Z\|KEY_EQUAL" engine/host_loop.py | head -10`

Find the block from the tracking-zoom spec where the C, Z, =, − handlers live (approximately around lines 2266–2280, after the C-key handler).

- [ ] **Step 2: Add `v_held_prev = False` initialisation**

Find where `z_held_prev = False` is initialised (around line 1866, immediately after `director = _CameraDirector()` construction inside `run()`). Add `v_held_prev = False` immediately after it. Use `grep -n "z_held_prev = False" engine/host_loop.py` to confirm the location.

After:
```python
        z_held_prev = False
```

Insert:
```python
        v_held_prev = False
```

- [ ] **Step 3: Add the V hold + Shift+mouse handler block**

Inside the C/Z/=/- handler block, after the existing `if _h.key_pressed(_h.keys.KEY_MINUS): director.zoom_out()` line, add:

```python
                    # V-key: Reverse Chase while held. Same hold-state
                    # edge detection as Z, with a retry guard so a
                    # V-held-during-mode-transition succeeds on the
                    # next eligible frame.
                    v_held_now = view_mode.is_exterior and _h.key_state(_h.keys.KEY_V)
                    if v_held_now and not director.chase.reverse_active:
                        director.start_reverse()
                    elif v_held_prev and not v_held_now:
                        director.end_reverse()
                    v_held_prev = v_held_now
                    # Shift+mouse: orbit yaw/pitch additive on top of
                    # arrow keys. Drain the mouse delta unconditionally
                    # in exterior view so non-Shift mouse motion doesn't
                    # accumulate and snap the camera on the next Shift
                    # press.
                    mouse_dx_exterior, mouse_dy_exterior = 0.0, 0.0
                    if view_mode.is_exterior:
                        mouse_dx_exterior, mouse_dy_exterior = _h.consume_mouse_delta()
                    shift_held = view_mode.is_exterior and (
                        _h.key_state(_h.keys.KEY_LEFT_SHIFT) or
                        _h.key_state(_h.keys.KEY_RIGHT_SHIFT)
                    )
                    if shift_held and director.mode is CameraMode.CHASE:
                        director.chase.apply_mouse_delta(
                            mouse_dx_exterior, mouse_dy_exterior)
```

Note: `CameraMode` may not be imported at this site. Confirm with `grep -n "from engine.cameras import\|CameraMode" engine/host_loop.py`. If missing, add `CameraMode` to the existing import line at the top of the file's `from engine.cameras import _CameraDirector` line (or wherever it lives).

- [ ] **Step 4: Verify existing test suite still passes**

Run: `uv run pytest tests/cameras/ tests/host/ -q`
Expected: all green. (The host-loop changes don't break tests because the test fakes for `_h` return defaults for unbound keys.)

- [ ] **Step 5: Smoke-check imports**

Run:
```bash
uv run python -c "from engine.host_loop import _apply_input; print('ok')"
```
Expected: `ok` (the native `_dauntless_host` module is now built so imports should resolve).

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host_loop): wire V hold + Shift+mouse to director

V key drives start/end_reverse via held-state edge detection
(retry guard mirrors the Z/ZoomTarget pattern).
Shift+mouse delta drives director.chase.apply_mouse_delta in
exterior + CHASE mode. Mouse delta is drained unconditionally
in exterior view so non-Shift motion doesn't accumulate and
snap the camera on the next Shift press. All handlers gated
on view_mode.is_exterior.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Manual verification

Build and run; verify all three features behave per spec.

**Files:** none modified — manual run.

- [ ] **Step 1: Rebuild (Python only — native already built in Task 7)**

If Tasks 1–6 modified only Python, no rebuild needed. If you want a fresh start, run:
```bash
cmake --build build -j
```

- [ ] **Step 2: Run**

Run: `./build/dauntless`

- [ ] **Step 3: Sticky zoom in Chase**

With no target (Chase Mode active):
- Press `=` repeatedly — camera glides closer to the ship.
- Press `−` repeatedly — camera glides farther.
- Hold `=` — OS auto-repeat for continuous zoom.
- Press past floor / ceiling — clamps.
- Mix with scroll wheel — both affect the same distance.

- [ ] **Step 4: Shift+mouse orbit in Chase**

With no target:
- Hold `Shift` + move mouse — camera orbits the ship in real-time.
- Mouse right → camera moves to ship-right.
- Mouse up → camera tilts up.
- Combine with arrow keys → both inputs compose.
- Release `Shift`, move mouse — nothing happens (drain works).
- Re-press `Shift` after a pause — no surprise snap.

- [ ] **Step 5: Reverse Chase (V hold)**

With no target:
- Hold `V` — camera flips to in-front of ship looking back.
- Release `V` — camera pops back to behind-ship.
- Hold `V` + arrow keys — orbit works around the flipped position.
- Hold `V` + Shift+mouse — same.
- Hold `V` + `=`/`−` — zoom works against flipped position.

- [ ] **Step 6: Mode interactions**

- Select a target while in Chase → Tracking auto-engages. If `V` was held, Reverse is cleared.
- Press `V` while in Tracking → nothing happens.
- Press `C` to leave Tracking back to Chase → no leftover reverse.
- Mission reload → all zoom values reset to default; reverse cleared.

- [ ] **Step 7: Bridge view interactions**

- Press SPACE to switch to bridge view → mouse goes to bridge look-around.
- Switch back to exterior → no surprise camera state (mouse drain prevented carry-over).

- [ ] **Step 8: Tune if needed**

If anything feels wrong, the constants live at the top of [`engine/cameras/chase.py`](engine/cameras/chase.py):

- `MOUSE_SENSITIVITY = 0.005` — bigger = mouse moves camera more per pixel.
- `ZOOM_FACTOR_PER_NOTCH = 0.9` — bigger jumps per zoom press: lower (e.g. 0.8).

Single-constant edits; no test changes unless tolerances tighten.

- [ ] **Step 9: Commit any tuning**

If Step 8 required changes:

```bash
git add engine/cameras/chase.py
git commit -m "tune(cameras): Chase Mode polish constants from manual playtest

<one-line description>

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

If no tuning needed, no commit.

---

## Self-review

Skimmed the plan against the spec:

- §1 Goals → Tasks 1 (Reverse flag), 2 (zoom), 3 (Shift+mouse), 4 (snap), 5 (director zoom), 6 (director reverse + cleanup), 7 (native bindings), 8 (host_loop wiring), 9 (verification). Everything in scope is covered.
- §2 State & architecture → Task 1 (reverse_active + compute_camera flip), Task 3 (MOUSE_SENSITIVITY), Task 4 (snap), Tasks 5/6 (director changes), Task 8 (host_loop).
- §3 Constants → Task 3 (MOUSE_SENSITIVITY). Existing constants reused as-is.
- §4 Edge cases → covered by the test tables in Tasks 1, 2, 3, 5, 6.
- §5 Testing → spread inline across Tasks 1–6.

Placeholder scan: every step has actual code or actual command output. No "TBD" / "similar to Task N" / "add error handling".

Type consistency:
- `reverse_active`, `MOUSE_SENSITIVITY`, `zoom_in`, `zoom_out`, `enter_reverse`, `exit_reverse`, `apply_mouse_delta` — names used consistently across all tasks.
- `start_reverse` / `end_reverse` on director vs `enter_reverse` / `exit_reverse` on camera — intentional asymmetry mirroring the Z/ZoomTarget pattern (director surface = key-down/-up semantics; camera surface = state-mutator semantics).
- `v_held_prev` / `v_held_now` — used consistently in Task 8.
- `CameraMode.CHASE` / `CameraMode.TRACKING` — used consistently.
