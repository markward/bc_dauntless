# Tracking Zoom + ZoomTarget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the BC `Z`-held ZoomTarget framing and the `=`/`−` sticky zoom to the existing `_TrackingCamera`, so the player can "binocular" onto the target and adjust the chase distance against either the player or the target anchor.

**Architecture:** Sub-mode flag inside `_TrackingCamera` (`zoom_target_active`) selects between the existing two-angle solver and a new ZoomTarget eye placement. Two persistent distance slots (`d_chase_tracking`, `d_chase_zoom`) keep state across mode toggles. Director adds `start_zoom_target`/`end_zoom_target`/`zoom_in`/`zoom_out` methods. Host-loop polls `Z` as a held key and `=`/`−` as press-edge.

**Tech Stack:** Python 3.13, pytest, BC's column-vector `TGMatrix3` / `TGPoint3`. C++ stub for new GLFW key bindings.

**Spec:** [`docs/superpowers/specs/2026-06-04-tracking-zoom-and-zoom-target-design.md`](../specs/2026-06-04-tracking-zoom-and-zoom-target-design.md)

---

## File Structure

```
engine/cameras/tracking.py       — add ZoomTarget branch, zoom state, zoom methods
engine/cameras/director.py       — add start/end_zoom_target, zoom_in/out, mode-transition cleanup
engine/host_loop.py              — wire Z hold + =/- key handlers
native/src/host/host_bindings.cc — expose KEY_Z, KEY_EQUAL, KEY_MINUS

tests/cameras/test_tracking_geometry.py — extend with ZoomTarget geometry tests
tests/cameras/test_tracking_zoom.py     — new file: sticky zoom + state persistence
tests/cameras/test_tracking_springs.py  — extend with Z press/release spring continuity
tests/cameras/test_director.py          — extend with director zoom methods + mode-cleanup
```

`_TrackingCamera` grows from ~270 lines to ~340 — still well within "one class, one focused responsibility". No new files in `engine/`.

---

## Task 1: Rename `d_chase` → `d_chase_tracking` + add zoom state fields

Behaviour-preserving refactor that prepares the camera for two distance slots. After this task all existing tests still pass with no semantic change — only the field name changes.

**Files:**
- Modify: `engine/cameras/tracking.py`
- Modify: `tests/cameras/test_tracking_geometry.py` (rename all `tc.d_chase` references)
- Modify: `tests/cameras/test_tracking_springs.py` (rename + the test function)

- [ ] **Step 1: Verify existing tests pass before refactoring**

Run: `uv run pytest tests/cameras/ -q`
Expected: 36 passed, 5 skipped.

- [ ] **Step 2: Rename in `engine/cameras/tracking.py`**

Top-of-class state and constants:

Replace the existing class header (currently lines 17–33) with:

```python
class _TrackingCamera:
    """Two-angle solver + ZoomTarget sub-mode + eye/basis springs."""

    # Default screen-Y fractions of the half-image, signed:
    #   negative = below centre, positive = above centre.
    y_p: float = -0.25   # player
    y_t: float = +0.25   # target

    # Spring time constants — see tracking-camera-rework spec §4.
    POS_SPRING_TAU_S: float = 0.25
    ROT_SPRING_TAU_S: float = 0.50

    # Sticky zoom — see tracking-zoom-and-zoom-target spec §2.
    ZOOM_FACTOR_PER_PRESS: float = 0.9     # one =/- press = ×0.9 / ÷0.9
    ZOOM_MIN_RADII:        float = 0.6     # reuse CAM_MIN_RADII semantics
    ZOOM_MAX_RADII:        float = 30.0    # reuse CAM_MAX_RADII semantics
    ZOOM_DEFAULT_RADII:    float = 0.6     # ZoomTarget seed = ZOOM_MIN_RADII

    def __init__(self):
        self.v_fov_rad        = EXTERIOR_FOV_Y_RAD
        # Two persistent distance slots. d_chase_tracking is the chase
        # distance from the player in normal Tracking framing.
        # d_chase_zoom is the eye-to-target distance in ZoomTarget mode.
        self.d_chase_tracking = 1.0   # seeded by set_ship_radius()
        self.d_chase_zoom     = 1.0   # seeded by set_ship_radius()
        self.zoom_min         = 1.0   # seeded by set_ship_radius()
        self.zoom_max         = 1.0   # seeded by set_ship_radius()
        # ZoomTarget sub-mode flag — toggled by enter/exit_zoom_target.
        self.zoom_target_active = False
        # Spring state (unchanged).
        self._smoothed_eye   = None
        self._smoothed_basis = None
```

Update `set_ship_radius`:

```python
    def set_ship_radius(self, radius: float) -> None:
        radius = max(radius, 1e-6)
        self.d_chase_tracking = _math.sqrt(CAM_BACK_RADII**2 + CAM_UP_RADII**2) * radius
        self.zoom_min         = self.ZOOM_MIN_RADII * radius
        self.zoom_max         = self.ZOOM_MAX_RADII * radius
        # ZoomTarget seeds at minimum so the first `=` press is a no-op
        # (matches BC behaviour observed in playtest).
        self.d_chase_zoom     = self.ZOOM_DEFAULT_RADII * radius
```

Update the single internal use of `self.d_chase` inside `compute()` to `self.d_chase_tracking`:

Find this line:
```python
        e_x, e_y = self._solve_eye_2d(D, self.d_chase, beta)
```
Replace with:
```python
        e_x, e_y = self._solve_eye_2d(D, self.d_chase_tracking, beta)
```

- [ ] **Step 3: Update test references**

In `tests/cameras/test_tracking_geometry.py`, replace every `tc.d_chase = ...` and `fresh.d_chase = ...` with `tc.d_chase_tracking = ...` / `fresh.d_chase_tracking = ...`. The 14 references identified by `grep -n "d_chase" tests/cameras/test_tracking_geometry.py`. Also update the in-comment references (`# D = 5 GU, d_chase = 10` etc.) for accuracy — these are doc-only.

In `tests/cameras/test_tracking_springs.py`, do the same. Specifically:

- Lines that assign `tc.d_chase = 10.0` / `fresh.d_chase = 10.0` → `d_chase_tracking`.
- The test function `test_set_ship_radius_updates_d_chase` — its assertion line:

```python
    assert tc.d_chase == pytest.approx(expected)
```

becomes:

```python
    assert tc.d_chase_tracking == pytest.approx(expected)
```

The test function name stays the same — `set_ship_radius` still "updates `d_chase`" in spirit. (If you prefer renaming the function to match, also rename to `test_set_ship_radius_seeds_distance_slots`, but this is optional.)

- [ ] **Step 4: Run tests, expect all to pass**

Run: `uv run pytest tests/cameras/ -q`
Expected: 36 passed, 5 skipped — same count as Step 1. No semantic change.

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/tracking.py tests/cameras/test_tracking_geometry.py tests/cameras/test_tracking_springs.py
git commit -m "refactor(cameras): split d_chase → d_chase_tracking + d_chase_zoom

Pure rename + add the second distance slot. d_chase_tracking holds
the player-anchor chase distance; d_chase_zoom holds the
target-anchor distance for the upcoming ZoomTarget sub-mode.
ZoomTarget seeds at zoom_min so the first = press is naturally a
no-op (matches BC behaviour). No behaviour change in this commit.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: ZoomTarget geometry branch in `compute()`

Add the alternate eye placement that fires when `zoom_target_active = True`. TDD.

**Files:**
- Modify: `engine/cameras/tracking.py`
- Modify: `tests/cameras/test_tracking_geometry.py` (append ZoomTarget tests)

- [ ] **Step 1: Write the failing geometry tests**

Append to `tests/cameras/test_tracking_geometry.py` (after the existing tests, before any module-level class definitions):

```python
def test_zoom_target_eye_on_player_target_axis_at_d_chase_zoom_from_target():
    """ZoomTarget eye sits d_chase_zoom behind the target along the
    ship→target axis (between player and target)."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera()
    tc.set_ship_radius(1.0)
    tc.d_chase_zoom = 5.0
    tc.zoom_target_active = True

    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    t_loc = TGPoint3(0.0, 20.0, 0.0)  # +y forward

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    # e1 = +y in this setup. Eye = T - 5 * e1 = (0, 15, 0).
    assert eye[0] == pytest.approx(0.0,  abs=1e-9)
    assert eye[1] == pytest.approx(15.0, abs=1e-9)
    assert eye[2] == pytest.approx(0.0,  abs=1e-9)
    # Forward should be e1 itself (camera looks straight at target).
    fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    assert (fx/flen, fy/flen, fz/flen) == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)


def test_zoom_target_target_projects_to_screen_centre():
    """With eye on the target→player ray and look-at = target, target
    must land at screen-Y = 0."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera()
    tc.set_ship_radius(1.0)
    tc.d_chase_zoom = 5.0
    tc.zoom_target_active = True

    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    t_loc = TGPoint3(0.0, 20.0, 0.0)

    eye, look_at, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
    flen = math.sqrt(fx*fx + fy*fy + fz*fz)
    forward = (fx/flen, fy/flen, fz/flen)

    y_t = _project_to_screen_y((0.0, 20.0, 0.0), eye, forward, up)
    assert y_t == pytest.approx(0.0, abs=1e-9)


def test_zoom_target_framing_invariant_across_range():
    """Across target ranges 5, 50, 500 GU with fixed d_chase_zoom = 5,
    target stays centred and eye is exactly d_chase_zoom from target."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    for d in (5.0, 50.0, 500.0):
        tc = _TrackingCamera()
        tc.set_ship_radius(1.0)
        tc.d_chase_zoom = 5.0
        tc.zoom_target_active = True

        s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
        t_loc = TGPoint3(0.0, d, 0.0)

        eye, look_at, up = tc.compute(
            player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

        # Distance from eye to target should be exactly d_chase_zoom = 5.
        dx = t_loc.x - eye[0]; dy = t_loc.y - eye[1]; dz = t_loc.z - eye[2]
        assert math.sqrt(dx*dx + dy*dy + dz*dz) == pytest.approx(5.0, abs=1e-6), \
            f"range {d}: eye→target = {math.sqrt(dx*dx + dy*dy + dz*dz)}"

        # Target screen-Y ≈ 0.
        fx = look_at[0] - eye[0]; fy = look_at[1] - eye[1]; fz = look_at[2] - eye[2]
        flen = math.sqrt(fx*fx + fy*fy + fz*fz)
        forward = (fx/flen, fy/flen, fz/flen)
        y_t = _project_to_screen_y((0.0, d, 0.0), eye, forward, up)
        assert y_t == pytest.approx(0.0, abs=1e-6), f"range {d}: y_t={y_t}"


def test_zoom_target_inherits_player_roll_into_up():
    """Ship rolled 30° around body-Y; ZoomTarget up follows ship body-up
    perpendicularised against forward."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera()
    tc.set_ship_radius(1.0)
    tc.d_chase_zoom = 5.0
    tc.zoom_target_active = True

    s_loc = TGPoint3(0.0, 0.0, 0.0)
    s_rot = TGMatrix3(); s_rot.MakeYRotation(math.radians(30))
    t_loc = TGPoint3(0.0, 20.0, 0.0)

    _, _, up = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    # Body-up after Y-roll 30° = (sin 30°, 0, cos 30°). e1 = (0,1,0).
    # body-up already perpendicular to e1, so e3 = body-up exactly.
    # Forward = e1 = (0,1,0), so up perpendicularised against forward = e3.
    assert up[0] == pytest.approx(math.sin(math.radians(30)), abs=1e-6)
    assert up[1] == pytest.approx(0.0,                          abs=1e-6)
    assert up[2] == pytest.approx(math.cos(math.radians(30)), abs=1e-6)


def test_zoom_target_clamp_when_target_inside_d_chase_zoom():
    """If D < d_chase_zoom, the eye placement must clamp to 0.9 × D so
    the camera stays in front of the target (not past it). Stored
    d_chase_zoom is NOT mutated (preserve user's zoom setting)."""
    from engine.cameras.tracking import _TrackingCamera
    from engine.appc.math         import TGPoint3, TGMatrix3

    tc = _TrackingCamera()
    tc.set_ship_radius(1.0)
    tc.d_chase_zoom = 10.0  # user-set zoom: 10 GU
    tc.zoom_target_active = True

    s_loc = TGPoint3(0.0, 0.0, 0.0); s_rot = TGMatrix3()
    t_loc = TGPoint3(0.0, 3.0, 0.0)  # D = 3, d_chase_zoom = 10 → clamp

    eye, _, _ = tc.compute(
        player=_FakeShip(s_loc, s_rot), target=_FakeShip(t_loc, s_rot), dt=None)

    # Eye should be at T - effective × e1 where effective = 0.9 × D = 2.7.
    # So eye_y = 3.0 - 2.7 = 0.3.
    assert eye[1] == pytest.approx(0.3, abs=1e-6)
    # Stored d_chase_zoom unchanged.
    assert tc.d_chase_zoom == pytest.approx(10.0, abs=1e-9)
```

- [ ] **Step 2: Run, watch the new tests fail**

Run: `uv run pytest tests/cameras/test_tracking_geometry.py -v`
Expected: the five new ZoomTarget tests fail (compute() doesn't branch yet — Tracking solver runs, produces wrong values).

- [ ] **Step 3: Implement the ZoomTarget branch in `compute()`**

In `engine/cameras/tracking.py`, refactor `compute()` to split the work:

After the line `e1, e3 = self._plane_basis(S, T, B)`, replace the rest of the function up to (but not including) the basis-matrix construction at `# Build the solver basis matrix` with:

```python
        if self.zoom_target_active:
            eye_solver, forward_solver, up_solver = self._compute_zoom_target(
                S=S, T=T, e1=e1, e3=e3,
            )
        else:
            eye_solver, forward_solver, up_solver = self._compute_tracking(
                S=S, T=T, e1=e1, e3=e3,
            )
```

Then extract two helper methods. After the existing `_advance_springs` method, before `_plane_basis`, add:

```python
    # ── per-branch solver ────────────────────────────────────────────

    def _compute_tracking(self, *, S, T, e1, e3):
        """Two-angle inscribed-angle solver against the player anchor.
        See tracking-camera-rework spec §3."""
        from engine.appc.math import TGPoint3

        D    = TGPoint3(T.x-S.x, T.y-S.y, T.z-S.z).Length()
        a_p  = self._screen_y_to_angle(self.y_p)
        a_t  = self._screen_y_to_angle(self.y_t)
        beta = a_t - a_p

        e_x, e_y = self._solve_eye_2d(D, self.d_chase_tracking, beta)
        eye_solver = (S.x + e_x * e1.x + e_y * e3.x,
                      S.y + e_x * e1.y + e_y * e3.y,
                      S.z + e_x * e1.z + e_y * e3.z)

        # Project (S − E) onto the solver plane, rotate by −α_p so the
        # player projects at y_p, then perpendicularise e3 against forward.
        s_minus_e = (S.x - eye_solver[0], S.y - eye_solver[1], S.z - eye_solver[2])
        es_e1 = s_minus_e[0]*e1.x + s_minus_e[1]*e1.y + s_minus_e[2]*e1.z
        es_e3 = s_minus_e[0]*e3.x + s_minus_e[1]*e3.y + s_minus_e[2]*e3.z
        angle_fwd = _math.atan2(es_e3, es_e1) - a_p
        f_2d = (_math.cos(angle_fwd), _math.sin(angle_fwd))

        forward_solver = (
            f_2d[0]*e1.x + f_2d[1]*e3.x,
            f_2d[0]*e1.y + f_2d[1]*e3.y,
            f_2d[0]*e1.z + f_2d[1]*e3.z,
        )
        dot_u_f = e3.x*forward_solver[0] + e3.y*forward_solver[1] + e3.z*forward_solver[2]
        ux = e3.x - dot_u_f * forward_solver[0]
        uy = e3.y - dot_u_f * forward_solver[1]
        uz = e3.z - dot_u_f * forward_solver[2]
        ulen = _math.sqrt(ux*ux + uy*uy + uz*uz)
        up_solver = (ux/ulen, uy/ulen, uz/ulen)

        return eye_solver, forward_solver, up_solver

    def _compute_zoom_target(self, *, S, T, e1, e3):
        """ZoomTarget framing: eye on the ship→target axis at
        effective_distance behind target, look-at = target.
        See tracking-zoom-and-zoom-target spec §3.
        """
        D = TGPoint3_norm = _math.sqrt((T.x-S.x)**2 + (T.y-S.y)**2 + (T.z-S.z)**2)
        # Clamp the *effective* distance to 0.9 × D when target is closer
        # than d_chase_zoom. Stored field unchanged (preserves user's
        # zoom setting for when D grows back).
        effective = min(self.d_chase_zoom, 0.9 * D)

        eye_solver = (T.x - effective * e1.x,
                      T.y - effective * e1.y,
                      T.z - effective * e1.z)
        # Forward = (T − eye) / |T − eye| = e1 (eye lies on the e1 line).
        forward_solver = (e1.x, e1.y, e1.z)
        # Up = e3 perpendicularised against forward. Identical pattern
        # to the Tracking solver's up step.
        dot_u_f = e3.x*forward_solver[0] + e3.y*forward_solver[1] + e3.z*forward_solver[2]
        ux = e3.x - dot_u_f * forward_solver[0]
        uy = e3.y - dot_u_f * forward_solver[1]
        uz = e3.z - dot_u_f * forward_solver[2]
        ulen = _math.sqrt(ux*ux + uy*uy + uz*uz)
        up_solver = (ux/ulen, uy/ulen, uz/ulen)

        return eye_solver, forward_solver, up_solver
```

(The local `TGPoint3` import isn't used in `_compute_zoom_target`; `TGPoint3_norm = _math.sqrt(...)` is just a local name for the length and could be inlined. The line is written this way to mirror the readability of the Tracking branch.)

Also add an import alias for `TGPoint3` at the top of `_compute_zoom_target` if needed (the function uses `_math.sqrt` only, so no `TGPoint3` import is required — the line is fine as written).

- [ ] **Step 4: Run, expect new tests to pass and existing tests to still pass**

Run: `uv run pytest tests/cameras/ -q`
Expected: 41 passed, 5 skipped (36 prior + 5 new).

If the clamp test fails because the eye lands at `T − 10 × e1 = -7` instead of `0.3`, the clamp logic in `_compute_zoom_target` is missing the `min(self.d_chase_zoom, 0.9 * D)` step. Check.

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/tracking.py tests/cameras/test_tracking_geometry.py
git commit -m "feat(cameras): ZoomTarget geometry branch in _TrackingCamera.compute

When zoom_target_active is True, place eye on the ship→target axis
at d_chase_zoom behind the target, look-at = target. Forward
collapses to e1 (target dead-centre). Up is e3 perpendicularised
against forward (player roll inherited). Clamp effective distance
to 0.9 × D when target is closer than d_chase_zoom — preserves the
stored zoom setting.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `zoom_in` / `zoom_out` / `enter_zoom_target` / `exit_zoom_target` + `snap()` update

Add the sticky zoom methods and the ZoomTarget toggle helpers. Update `snap()` to reset zoom state.

**Files:**
- Modify: `engine/cameras/tracking.py`
- Create: `tests/cameras/test_tracking_zoom.py`

- [ ] **Step 1: Write the failing tests**

Write `tests/cameras/test_tracking_zoom.py`:

```python
"""Unit tests for _TrackingCamera sticky zoom + ZoomTarget toggles.
See docs/superpowers/specs/2026-06-04-tracking-zoom-and-zoom-target-design.md §4."""
import math
import pytest


def _seeded_camera(radius=1.0):
    from engine.cameras.tracking import _TrackingCamera
    tc = _TrackingCamera()
    tc.set_ship_radius(radius)
    return tc


def test_zoom_in_in_tracking_decreases_d_chase_tracking():
    tc = _seeded_camera()
    seed = tc.d_chase_tracking
    seed_zoom = tc.d_chase_zoom
    tc.zoom_in()
    assert tc.d_chase_tracking == pytest.approx(seed * tc.ZOOM_FACTOR_PER_PRESS)
    assert tc.d_chase_zoom == pytest.approx(seed_zoom)  # unchanged


def test_zoom_in_in_zoom_target_decreases_d_chase_zoom():
    tc = _seeded_camera()
    # Pre-zoom-out so d_chase_zoom > zoom_min and the press is effective.
    tc.zoom_target_active = True
    tc.d_chase_zoom = tc.zoom_min * 2.0
    seed_tracking = tc.d_chase_tracking
    seed_zoom = tc.d_chase_zoom
    tc.zoom_in()
    assert tc.d_chase_zoom == pytest.approx(seed_zoom * tc.ZOOM_FACTOR_PER_PRESS)
    assert tc.d_chase_tracking == pytest.approx(seed_tracking)  # unchanged


def test_zoom_in_clamps_at_zoom_min():
    """ZoomTarget seeds at zoom_min, so the first = press in
    ZoomTarget must be a no-op (matches BC behaviour)."""
    tc = _seeded_camera()
    tc.zoom_target_active = True
    # set_ship_radius already seeded d_chase_zoom = zoom_min.
    assert tc.d_chase_zoom == pytest.approx(tc.zoom_min)
    tc.zoom_in()
    assert tc.d_chase_zoom == pytest.approx(tc.zoom_min)  # still at floor


def test_zoom_out_clamps_at_zoom_max():
    tc = _seeded_camera()
    tc.d_chase_tracking = tc.zoom_max
    tc.zoom_out()
    assert tc.d_chase_tracking == pytest.approx(tc.zoom_max)  # still at ceiling


def test_zoom_round_trip_returns_to_original():
    tc = _seeded_camera()
    seed = tc.d_chase_tracking
    tc.zoom_in()
    tc.zoom_out()
    assert tc.d_chase_tracking == pytest.approx(seed, abs=1e-9)


def test_zoom_persists_across_enter_exit_zoom_target():
    tc = _seeded_camera()
    # Zoom in once in tracking.
    tc.zoom_in()
    after_zoom = tc.d_chase_tracking
    # Enter and exit ZoomTarget — d_chase_tracking must be preserved.
    tc.enter_zoom_target()
    tc.exit_zoom_target()
    assert tc.d_chase_tracking == pytest.approx(after_zoom)


def test_enter_exit_zoom_target_toggles_flag():
    tc = _seeded_camera()
    assert tc.zoom_target_active is False
    tc.enter_zoom_target()
    assert tc.zoom_target_active is True
    tc.exit_zoom_target()
    assert tc.zoom_target_active is False


def test_snap_resets_zoom_state():
    tc = _seeded_camera()
    seed_tracking = tc.d_chase_tracking
    seed_zoom = tc.d_chase_zoom
    # Mutate everything.
    tc.zoom_in()                  # d_chase_tracking down
    tc.zoom_target_active = True
    tc.d_chase_zoom = tc.zoom_max # d_chase_zoom up
    # Snap.
    tc.snap()
    assert tc.d_chase_tracking == pytest.approx(seed_tracking)
    assert tc.d_chase_zoom == pytest.approx(seed_zoom)
    assert tc.zoom_target_active is False
    # Spring state also cleared (existing snap behaviour).
    assert tc._smoothed_eye is None
    assert tc._smoothed_basis is None
```

- [ ] **Step 2: Run, watch them fail**

Run: `uv run pytest tests/cameras/test_tracking_zoom.py -v`
Expected: all fail (methods don't exist).

- [ ] **Step 3: Implement the methods**

In `engine/cameras/tracking.py`, add the new public methods. Place them after `set_ship_radius`, before `snap`:

```python
    def zoom_in(self) -> None:
        """Sticky zoom (= key): bring the camera closer to its anchor.
        Modifies whichever distance is active based on zoom_target_active."""
        if self.zoom_target_active:
            self.d_chase_zoom = max(
                self.d_chase_zoom * self.ZOOM_FACTOR_PER_PRESS,
                self.zoom_min,
            )
        else:
            self.d_chase_tracking = max(
                self.d_chase_tracking * self.ZOOM_FACTOR_PER_PRESS,
                self.zoom_min,
            )

    def zoom_out(self) -> None:
        """Sticky zoom (- key): push the camera farther from its anchor."""
        if self.zoom_target_active:
            self.d_chase_zoom = min(
                self.d_chase_zoom / self.ZOOM_FACTOR_PER_PRESS,
                self.zoom_max,
            )
        else:
            self.d_chase_tracking = min(
                self.d_chase_tracking / self.ZOOM_FACTOR_PER_PRESS,
                self.zoom_max,
            )

    def enter_zoom_target(self) -> None:
        """Activate the ZoomTarget sub-mode. Does NOT reset
        d_chase_zoom — preserves it across press/release."""
        self.zoom_target_active = True

    def exit_zoom_target(self) -> None:
        """Deactivate the ZoomTarget sub-mode."""
        self.zoom_target_active = False
```

Update `snap()` to reset zoom state. Replace the existing `snap` method:

```python
    def snap(self) -> None:
        """Drop both smoothing states and reset zoom to defaults.
        Used on mission swap / hard cut."""
        self._smoothed_eye   = None
        self._smoothed_basis = None
        # Reset zoom by re-seeding from the current ship radius.
        # Recover the radius from zoom_max / ZOOM_MAX_RADII.
        if self.zoom_max > 0.0:
            radius = self.zoom_max / self.ZOOM_MAX_RADII
            self.d_chase_tracking = _math.sqrt(CAM_BACK_RADII**2 + CAM_UP_RADII**2) * radius
            self.d_chase_zoom     = self.ZOOM_DEFAULT_RADII * radius
        self.zoom_target_active = False
```

- [ ] **Step 4: Run, expect all to pass**

Run: `uv run pytest tests/cameras/test_tracking_zoom.py tests/cameras/test_tracking_geometry.py tests/cameras/test_tracking_springs.py -v`
Expected: 8 new zoom tests pass + all prior tests still pass.

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/tracking.py tests/cameras/test_tracking_zoom.py
git commit -m "feat(cameras): sticky zoom + enter/exit_zoom_target + snap reset

zoom_in / zoom_out modify whichever distance is active based on
zoom_target_active, with clamping at zoom_min / zoom_max.
ZoomTarget seeds at zoom_min so the first = press is a no-op
until - has been pressed (matches BC behaviour).
enter/exit_zoom_target flip the sub-mode flag without resetting
d_chase_zoom — preserves zoom across hold/release.
snap() now resets both distances and clears the sub-mode flag
in addition to the existing spring-state drop.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Director `start_zoom_target` / `end_zoom_target` / `zoom_in` / `zoom_out`

Thin pass-through methods that gate on the active camera mode.

**Files:**
- Modify: `engine/cameras/director.py`
- Modify: `tests/cameras/test_director.py` (append new tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/cameras/test_director.py`:

```python
def test_start_zoom_target_in_chase_is_noop():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.tracking.set_ship_radius(1.0)
    # mode is CHASE by default
    d.start_zoom_target(player=_FakeShipWithTarget(target=_make_target_at()))
    assert d.tracking.zoom_target_active is False


def test_start_zoom_target_in_tracking_with_target_activates():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    # Enter Tracking first (via toggle).
    p = _FakeShipWithTarget(target=_make_target_at())
    d.toggle_mode(player=p)
    assert d.mode is CameraMode.TRACKING
    d.start_zoom_target(player=p)
    assert d.tracking.zoom_target_active is True


def test_start_zoom_target_in_tracking_with_no_target_is_noop():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    # Force Tracking even though there's no target (test scaffold).
    d.mode = CameraMode.TRACKING
    p = _FakeShipWithTarget(target=None)
    d.start_zoom_target(player=p)
    assert d.tracking.zoom_target_active is False


def test_end_zoom_target_clears_unconditionally():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.tracking.set_ship_radius(1.0)
    d.tracking.zoom_target_active = True
    d.end_zoom_target()
    assert d.tracking.zoom_target_active is False
    # Called again — still False (idempotent).
    d.end_zoom_target()
    assert d.tracking.zoom_target_active is False


def test_director_zoom_in_in_chase_is_noop():
    from engine.cameras.director import _CameraDirector
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    seed_tracking = d.tracking.d_chase_tracking
    seed_zoom = d.tracking.d_chase_zoom
    d.zoom_in()
    d.zoom_out()
    assert d.tracking.d_chase_tracking == pytest.approx(seed_tracking)
    assert d.tracking.d_chase_zoom == pytest.approx(seed_zoom)


def test_director_zoom_in_in_tracking_delegates():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.mode = CameraMode.TRACKING
    seed = d.tracking.d_chase_tracking
    d.zoom_in()
    assert d.tracking.d_chase_tracking == pytest.approx(
        seed * d.tracking.ZOOM_FACTOR_PER_PRESS)


def test_director_zoom_out_in_tracking_delegates():
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)
    d.mode = CameraMode.TRACKING
    seed = d.tracking.d_chase_tracking
    d.zoom_out()
    assert d.tracking.d_chase_tracking == pytest.approx(
        seed / d.tracking.ZOOM_FACTOR_PER_PRESS)
```

- [ ] **Step 2: Run, watch them fail**

Run: `uv run pytest tests/cameras/test_director.py -v`
Expected: 7 new tests fail with `AttributeError` (methods don't exist).

- [ ] **Step 3: Implement on `_CameraDirector`**

Add four new methods to `engine/cameras/director.py`. Place them after `snap()`, before the dispatch section:

```python
    # ── zoom controls ────────────────────────────────────────────────

    def start_zoom_target(self, *, player) -> None:
        """Z-key down. Enter ZoomTarget if currently in Tracking with a
        valid target. Otherwise no-op."""
        if self.mode is not CameraMode.TRACKING:
            return
        if self._valid_target(player) is None:
            return
        self.tracking.enter_zoom_target()

    def end_zoom_target(self) -> None:
        """Z-key up. Unconditionally exit ZoomTarget (safe to call when
        not active — idempotent)."""
        self.tracking.exit_zoom_target()

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

- [ ] **Step 4: Run, expect all to pass**

Run: `uv run pytest tests/cameras/test_director.py -v`
Expected: all green (existing tests + 7 new).

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/director.py tests/cameras/test_director.py
git commit -m "feat(cameras): director start/end_zoom_target + zoom_in/zoom_out

Thin pass-through methods. start_zoom_target requires mode TRACKING
+ valid target; end_zoom_target is unconditional. zoom_in/out are
no-ops in CHASE (deferred). Wires to the new _TrackingCamera
controls landed in the previous task.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Director mode-transition cleanup for ZoomTarget

When the user leaves Tracking (target-lost durable fallback OR explicit C-toggle), the ZoomTarget sub-mode must also be cleared so a future Tracking entry doesn't surprise with stale state.

**Files:**
- Modify: `engine/cameras/director.py`
- Modify: `tests/cameras/test_director.py` (append cleanup tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/cameras/test_director.py`:

```python
def test_target_lost_in_tracking_with_zoom_target_active_clears_both():
    """Durable target-loss fallback must clear ZoomTarget sub-mode
    in addition to flipping mode to CHASE."""
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)

    p_with = _FakeShipWithTarget(target=_make_target_at())
    p_without = _FakeShipWithTarget(target=None)

    d.toggle_mode(player=p_with)
    assert d.mode is CameraMode.TRACKING
    d.start_zoom_target(player=p_with)
    assert d.tracking.zoom_target_active is True

    # Target lost.
    d.compute(player=p_without, dt=1.0/60)
    assert d.mode is CameraMode.CHASE
    assert d.tracking.zoom_target_active is False


def test_c_toggle_tracking_to_chase_clears_zoom_target():
    """C-key explicit Tracking → Chase must also clear ZoomTarget."""
    from engine.cameras.director import _CameraDirector, CameraMode
    d = _CameraDirector()
    d.chase.set_ship_radius(1.0); d.tracking.set_ship_radius(1.0)

    p = _FakeShipWithTarget(target=_make_target_at())
    d.toggle_mode(player=p)
    d.start_zoom_target(player=p)
    assert d.tracking.zoom_target_active is True

    # C pressed.
    d.toggle_mode(player=p)
    assert d.mode is CameraMode.CHASE
    assert d.tracking.zoom_target_active is False
```

- [ ] **Step 2: Run, watch them fail**

Run: `uv run pytest tests/cameras/test_director.py::test_target_lost_in_tracking_with_zoom_target_active_clears_both tests/cameras/test_director.py::test_c_toggle_tracking_to_chase_clears_zoom_target -v`
Expected: both fail (`zoom_target_active` stays True after the transition).

- [ ] **Step 3: Add cleanup to the two transition sites**

In `engine/cameras/director.py`:

In `toggle_mode`, modify the TRACKING → CHASE branch. Find:

```python
        else:
            # Leaving Tracking manually: record the current target so
            # auto-engage doesn't immediately re-fire next frame.
            tgt = self._valid_target(player)
            self._opted_out_target = tgt  # None if no target (defensive)
            self.mode = CameraMode.CHASE
```

Replace with:

```python
        else:
            # Leaving Tracking manually: record the current target so
            # auto-engage doesn't immediately re-fire next frame.
            tgt = self._valid_target(player)
            self._opted_out_target = tgt  # None if no target (defensive)
            self.mode = CameraMode.CHASE
            self.tracking.exit_zoom_target()
```

In `compute`, modify the durable target-loss fallback. Find:

```python
        if self.mode is CameraMode.TRACKING:
            tgt = self._valid_target(player)
            if tgt is None:
                # Target lost → durable fallback to Chase; clear opt-out so
                # re-acquiring any target (including the old one) auto-engages.
                self.mode = CameraMode.CHASE
                self._opted_out_target = None
```

Replace with:

```python
        if self.mode is CameraMode.TRACKING:
            tgt = self._valid_target(player)
            if tgt is None:
                # Target lost → durable fallback to Chase; clear opt-out so
                # re-acquiring any target (including the old one) auto-engages.
                # Also clear the ZoomTarget sub-mode so a future Tracking
                # entry doesn't inherit a stale flag.
                self.mode = CameraMode.CHASE
                self._opted_out_target = None
                self.tracking.exit_zoom_target()
```

- [ ] **Step 4: Run, expect all tests pass**

Run: `uv run pytest tests/cameras/ -q`
Expected: 50 passed, 5 skipped (41 prior + 7 from Task 4 + 2 from this task).

- [ ] **Step 5: Commit**

```bash
git add engine/cameras/director.py tests/cameras/test_director.py
git commit -m "fix(cameras): clear zoom_target_active on Tracking→Chase transitions

Both target-loss durable fallback and C-key explicit toggle now
call tracking.exit_zoom_target() so the sub-mode flag doesn't
survive into the next Tracking entry. Without this, re-engaging
Tracking after a Z-held-then-target-lost sequence would resume
in ZoomTarget framing unexpectedly.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Native key bindings for `KEY_Z`, `KEY_EQUAL`, `KEY_MINUS`

Add three GLFW key constants to the C++ bindings module. Requires a CMake rebuild.

**Files:**
- Modify: `native/src/host/host_bindings.cc`

- [ ] **Step 1: Add the three constants**

In `native/src/host/host_bindings.cc`, locate the existing `keys.attr("KEY_C") = GLFW_KEY_C;` line (around line 782). Append three new lines after the existing arrow keys block:

```cpp
    keys.attr("KEY_Z")     = GLFW_KEY_Z;
    keys.attr("KEY_EQUAL") = GLFW_KEY_EQUAL;
    keys.attr("KEY_MINUS") = GLFW_KEY_MINUS;
```

The exact insertion point is between `keys.attr("KEY_C")     = GLFW_KEY_C;` and `keys.attr("KEY_UP")    = GLFW_KEY_UP;` to keep alphabetical-ish grouping with other letter keys.

- [ ] **Step 2: Rebuild**

Run:
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: clean build, `build/dauntless` and `build/python/_open_stbc_host.cpython-*.so` exist. Warnings about macOS version mismatches are pre-existing and irrelevant.

- [ ] **Step 3: Smoke-check the new constants exist**

Run:
```bash
uv run python -c "import _dauntless_host as h; print(h.keys.KEY_Z, h.keys.KEY_EQUAL, h.keys.KEY_MINUS)"
```
Expected: three integer values printed (the GLFW keycodes). If you get `AttributeError`, the build picked up a stale `.so`. Delete `build/python/_open_stbc_host*.so` and rebuild.

- [ ] **Step 4: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(host): expose KEY_Z, KEY_EQUAL, KEY_MINUS bindings

GLFW keycodes for the upcoming Z hold (ZoomTarget) and =/- sticky
zoom handlers in host_loop.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Host-loop key wiring

Wire Z-hold edge detection and =/- press handlers into the main loop. Same insertion point as the existing C-key handler.

**Files:**
- Modify: `engine/host_loop.py`

- [ ] **Step 1: Locate the existing C-key block**

Around line 2266 of `engine/host_loop.py`:

```python
                    if view_mode.is_exterior and _h.key_pressed(_h.keys.KEY_C):
                        director.toggle_mode(player=player)
```

- [ ] **Step 2: Add Z-hold state to `run()` scope**

The Z-hold edge detection needs a per-frame "was held last frame" memory. The cleanest place is alongside other per-loop state. Find the line where `cam_control` was originally constructed (now `director = _CameraDirector()` etc.) and add a `z_held_prev = False` initialisation in the same neighbourhood.

Concretely, find:

```python
        from engine.cameras import _CameraDirector
        director       = _CameraDirector()
```

and immediately after, add:

```python
        z_held_prev = False
```

If multiple matches, prefer the one inside `run()`, not test scaffolds.

- [ ] **Step 3: Replace the C-key block with C + Z + zoom handlers**

Replace the C-key block (the two lines from Step 1) with:

```python
                    # C-key: toggle Chase ↔ Tracking (only enters Tracking if
                    # the player has a valid target). key_pressed fires once per
                    # key-down event (not while held). Gate on exterior view so
                    # the mode cannot flip silently while the bridge is active.
                    if view_mode.is_exterior and _h.key_pressed(_h.keys.KEY_C):
                        director.toggle_mode(player=player)
                    # Z-key: ZoomTarget framing while held. Held-state (not
                    # press-edge) so the camera enters/exits as the key state
                    # changes. The `not director.tracking.zoom_target_active`
                    # retry guard lets a Z-held-during-target-acquisition
                    # succeed on whichever frame the target appears.
                    z_held_now = view_mode.is_exterior and _h.key_state(_h.keys.KEY_Z)
                    if z_held_now and not director.tracking.zoom_target_active:
                        director.start_zoom_target(player=player)
                    elif z_held_prev and not z_held_now:
                        director.end_zoom_target()
                    z_held_prev = z_held_now
                    # =/- sticky zoom: press-edge (OS auto-repeat for hold).
                    if view_mode.is_exterior and _h.key_pressed(_h.keys.KEY_EQUAL):
                        director.zoom_in()
                    if view_mode.is_exterior and _h.key_pressed(_h.keys.KEY_MINUS):
                        director.zoom_out()
```

- [ ] **Step 4: Verify the existing test suite still passes**

Run: `uv run pytest tests/cameras/ tests/host/ -q`
Expected: all green. The host-loop changes don't break any tests because the test fakes for `_h` don't set the new keys (key_state and key_pressed return defaults).

- [ ] **Step 5: Smoke-check imports**

Run:
```bash
uv run python -c "from engine.host_loop import _apply_input; print('ok')"
```
Expected: `ok` (or the pre-existing `_dauntless_host` import failure, which is not our concern).

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host_loop): wire Z hold + =/- sticky zoom to director

Z key drives start/end_zoom_target via held-state edge detection
with a retry guard so target-acquired-while-Z-held works.
= and - press-edges drive director.zoom_in / zoom_out; OS
auto-repeat handles continuous zoom while held. All gated on
view_mode.is_exterior so bridge view can't be confused.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Manual verification

Build and run the host loop. Verify ZoomTarget + sticky zoom behave per the spec.

**Files:** none modified — this is a manual run.

- [ ] **Step 1: Rebuild and run**

Run: `./build/dauntless`

If the Python `engine/` changes didn't pick up after the previous Task-6 build, restart the binary.

- [ ] **Step 2: Tracking sticky zoom (no Z)**

With a target selected (Tracking auto-engaged):

- Press `=` repeatedly — camera should glide closer to the player; the player ship grows in frame; both ships still hold their ±25% screen-Y positions.
- Press `−` repeatedly — camera glides farther from player.
- Hold `=` — OS auto-repeat produces continuous zoom; smooth glide from the position spring.
- Press `+` (shift + `=`) — nothing should happen.
- Press `=` past the floor — clamp; no further zoom.
- Press `−` past the ceiling — clamp; no further zoom.

- [ ] **Step 3: ZoomTarget (Z held)**

- Hold `Z` with a target selected — camera should slide "over" the player along the player→target axis and end up with the target centred. Player goes off-bottom of screen.
- Release `Z` — camera glides back to the Tracking framing.
- Hold `Z`, press `=` — nothing should happen on first press (already at zoom_min).
- Hold `Z`, press `−` — camera moves farther from target.
- Hold `Z`, then press `=` after `−` — camera moves closer to target again.
- Release `Z`, hold `Z` again — should re-enter at whatever d_chase_zoom you left it at (persistence).

- [ ] **Step 4: Edge cases**

- Hold `Z` with no target selected — nothing happens.
- Press `T` to switch targets while in Tracking — auto-engages on new target; zoom values persist.
- Press `C` to manually exit Tracking — ZoomTarget cleared; sub-mode flag false.
- Trigger a mission reload — both zoom values reset to seed (verify by zooming in heavily first, then reloading and confirming Tracking starts at default framing).

- [ ] **Step 5: Tune if needed**

If anything feels wrong, the constants live at the top of [`engine/cameras/tracking.py`](engine/cameras/tracking.py):

- `ZOOM_FACTOR_PER_PRESS = 0.9` — bigger jumps per press: lower (e.g. 0.8).
- `ZOOM_DEFAULT_RADII = 0.6` — ZoomTarget starts further out: raise to e.g. 1.0.
- `ZOOM_MIN_RADII`, `ZOOM_MAX_RADII` — change clamp bounds.

These are all single-constant edits — no test changes unless tolerances tighten.

- [ ] **Step 6: Commit any tuning**

If Step 5 required changes, commit them:

```bash
git add engine/cameras/tracking.py
git commit -m "tune(cameras): tracking zoom constants from manual playtest

<one-line description>

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

If no tuning needed, no commit.

---

## Self-review

Skimmed the plan against the spec:

- §1 Goals → Tasks 1–7 collectively implement everything in scope. ZoomTarget Tasks 2 + 7; sticky zoom Tasks 3 + 7; persistence Task 3; mission-swap reset Task 3; key gating Task 7. Nothing in scope is unimplemented.
- §2 State & architecture → Task 1 (state fields), Task 4 (director surface), Task 5 (transition cleanup).
- §3 Geometry → Task 2.
- §4 Sticky zoom semantics → Task 3.
- §5 Director integration & key bindings → Tasks 4, 6, 7.
- §6 Testing → spread inline across Tasks 2, 3, 4, 5.

Placeholder scan: every step has actual code or actual commands. The one comment-marker line in Task 2 Step 3 (`# Build the solver basis matrix`) is a location anchor for the existing code, not a placeholder. No "TBD", no "similar to Task N".

Type consistency:
- `d_chase_tracking`, `d_chase_zoom`, `zoom_min`, `zoom_max`, `zoom_target_active` — names match across all tasks.
- `ZOOM_FACTOR_PER_PRESS`, `ZOOM_MIN_RADII`, `ZOOM_MAX_RADII`, `ZOOM_DEFAULT_RADII` — consistent class-level constants.
- `enter_zoom_target` / `exit_zoom_target` on `_TrackingCamera`; `start_zoom_target` / `end_zoom_target` on `_CameraDirector` — different names because they live on different classes (director: control surface; camera: state mutator). This asymmetry is intentional and called out in the spec.
- `_compute_tracking`, `_compute_zoom_target` — referenced consistently in Task 2.

One latent risk: Task 1's `set_ship_radius` change seeds `d_chase_zoom = ZOOM_DEFAULT_RADII × radius` which equals `zoom_min` because `ZOOM_DEFAULT_RADII == ZOOM_MIN_RADII == 0.6`. This is intentional (per spec §4) but the constants are formally redundant. Either constant could be removed and the other reused, but having both makes the "default = min, by design" intent explicit. Left as-is.
