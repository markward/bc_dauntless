# Chase Mode Polish — Design

**Date:** 2026-06-04
**Status:** Design — ready for implementation plan

## Summary

Add three BC tactical-camera bindings that the existing free-orbit
Chase Mode is missing:

1. **`Z`-equivalent for Chase: `=`/`−` sticky zoom** — already wired into
   `_CameraDirector.zoom_in/zoom_out` but no-op in CHASE today. Delegate
   to `_ChaseCamera`.
2. **Shift+mouse orbit** — while `Shift` is held in exterior + Chase,
   mouse delta drives `orbit_yaw_rad` and `orbit_pitch_rad` additively
   alongside the existing arrow-key input.
3. **`V`-held Reverse Chase** — flag on `_ChaseCamera` that adds `π` to
   the effective orbit yaw, flipping the camera to in-front-of-ship.

All three sit on `_ChaseCamera`. Director adds thin pass-through methods.
Reverse Chase is a held-key flag (not a separate director mode), mirroring
the `Z`-held ZoomTarget pattern from
[`2026-06-04-tracking-zoom-and-zoom-target-design.md`](2026-06-04-tracking-zoom-and-zoom-target-design.md).

## §1 Goals & non-goals

### In scope

- **Sticky zoom (`=`/`−`)** in Chase Mode. Same `0.9` factor per press as
  Tracking. Clamped to existing `distance_min` / `distance_max` (set by
  `_ChaseCamera.set_ship_radius` from `CAM_MIN_RADII × radius` and
  `CAM_MAX_RADII × radius`). Persistent across mode toggles; reset on
  mission swap via `_ChaseCamera.snap()`.
- **Shift+mouse orbit**: while `Shift` held in exterior + Chase, mouse
  delta drives orbit yaw/pitch additively alongside arrow keys. Pitch
  clamped to the existing `±PITCH_LIMIT_RAD = 85°`.
- **Reverse Chase (`V` held)**: hold-key flag on `_ChaseCamera` that adds
  `π` to the effective orbit yaw. Release returns to normal. No new
  director mode; same hold-pattern as `Z` (ZoomTarget).
- **Plumbing**: native `KEY_V`, `KEY_LEFT_SHIFT`, `KEY_RIGHT_SHIFT`.
  Host-loop key handlers gated on `view_mode.is_exterior` per the
  established C/Z/=/− pattern.
- **Mouse-delta drain**: in exterior mode, drain
  `_h.consume_mouse_delta()` unconditionally each frame so that a
  non-Shift mouse motion doesn't accumulate and snap the camera on the
  next Shift press.

### Out of scope (deferred follow-ups)

- Spring smoothing on the eye position when `V` is engaged/released.
  Accept the instantaneous position jump for now; revisit only if
  playtest finds it jarring (would require adding a position spring to
  `_ChaseCamera`, mirroring `_TrackingCamera`'s).
- Reverse Chase + Tracking interaction. `V` is Chase-only — no-op in
  Tracking, no flag preserved across mode transitions.
- Cinematic Mode (`F9` + `F1`–`F6`).
- Bridge viewscreen camera.

## §2 State & architecture

### `_ChaseCamera` additions

| Field | Meaning |
|---|---|
| `reverse_active: bool` | `V` key state — `False` (chase) / `True` (reverse) |

### `_ChaseCamera` constants (class-level)

```
MOUSE_SENSITIVITY: float = 0.005    # radians per pixel
```

`ZOOM_FACTOR_PER_NOTCH = 0.9` already exists on `_ChaseCamera` from the
scroll-wheel zoom — sticky zoom reuses it.

### New `_ChaseCamera` methods

```python
def zoom_in(self) -> None:
    """=-key press. Decrease distance, clamped at distance_min."""
    self.distance = max(self.distance * self.ZOOM_FACTOR_PER_NOTCH,
                        self.distance_min)

def zoom_out(self) -> None:
    """-key press. Increase distance, clamped at distance_max."""
    self.distance = min(self.distance / self.ZOOM_FACTOR_PER_NOTCH,
                        self.distance_max)

def apply_mouse_delta(self, dx: float, dy: float) -> None:
    """Shift+mouse: additive orbit input alongside arrow keys.
    Pitch clamped to the same ±PITCH_LIMIT_RAD as arrow input."""
    self.orbit_yaw_rad   += dx * self.MOUSE_SENSITIVITY
    self.orbit_pitch_rad -= dy * self.MOUSE_SENSITIVITY
    if self.orbit_pitch_rad >  self.PITCH_LIMIT_RAD:
        self.orbit_pitch_rad =  self.PITCH_LIMIT_RAD
    if self.orbit_pitch_rad < -self.PITCH_LIMIT_RAD:
        self.orbit_pitch_rad = -self.PITCH_LIMIT_RAD

def enter_reverse(self) -> None:
    """V-key down: flip camera to in-front-of-ship perspective."""
    self.reverse_active = True

def exit_reverse(self) -> None:
    """V-key up: return to behind-ship perspective."""
    self.reverse_active = False
```

### `_ChaseCamera.compute_camera` change

Replace the existing yaw projection. Currently:

```python
sy = _math.sin(self.orbit_yaw_rad)
cy = _math.cos(self.orbit_yaw_rad)
```

Becomes:

```python
yaw_effective = self.orbit_yaw_rad + (_math.pi if self.reverse_active else 0.0)
sy = _math.sin(yaw_effective)
cy = _math.cos(yaw_effective)
```

Everything downstream (the body-frame projection, the look-at, the
rotation spring) is untouched. The effect is mathematically just a
sign flip on the `(ox, oy)` body-frame plane.

### `_ChaseCamera.snap()` update

Currently only clears `_smoothed_rot`. Extend to also reset `distance`
to `default_distance` and clear `reverse_active`:

```python
def snap(self) -> None:
    self._smoothed_rot   = None
    self.distance        = self.default_distance
    self.reverse_active  = False
```

This brings Chase's snap semantics in line with `_TrackingCamera.snap()`
(which resets its own distance and sub-mode flag).

### Director additions and modifications

```python
def zoom_in(self) -> None:
    if self.mode is CameraMode.TRACKING:
        self.tracking.zoom_in()
    else:                                # CHASE
        self.chase.zoom_in()

def zoom_out(self) -> None:
    if self.mode is CameraMode.TRACKING:
        self.tracking.zoom_out()
    else:                                # CHASE
        self.chase.zoom_out()

def start_reverse(self) -> None:
    """V-key down. Enter Reverse Chase if currently in CHASE mode.
    No-op in Tracking (V is Chase-only per spec §1)."""
    if self.mode is CameraMode.CHASE:
        self.chase.enter_reverse()

def end_reverse(self) -> None:
    """V-key up. Idempotent."""
    self.chase.exit_reverse()
```

The `zoom_in/zoom_out` change drops the Chase-no-op carve-out from the
tracking-zoom spec; this is the deferred Chase sticky zoom landing.

### Mode-transition cleanup

When the director enters Tracking, the Chase camera's `reverse_active`
should be cleared so a future return to Chase doesn't surprise the user
with leftover flip. Add `self.chase.exit_reverse()` to:

- `toggle_mode()` CHASE → TRACKING branch (after `self.mode = CameraMode.TRACKING`)
- `compute()` auto-engage path (after `self.tracking.snap()`)

`director.snap()` already propagates to `chase.snap()`, which (after the
update above) resets `reverse_active`.

### Host-loop wiring

Same insertion point as the existing `C` / `Z` / `=` / `−` handlers
inside the `if view_mode.is_exterior and player is not None …` block:

```python
# V-key: Reverse Chase while held. Held-state edge detection with
# retry guard so V-held-during-mode-transition succeeds on the
# next eligible frame.
v_held_now = view_mode.is_exterior and _h.key_state(_h.keys.KEY_V)
if v_held_now and not director.chase.reverse_active:
    director.start_reverse()
elif v_held_prev and not v_held_now:
    director.end_reverse()
v_held_prev = v_held_now

# Shift+mouse: orbit yaw/pitch additive on top of arrow keys.
# Drain the mouse delta unconditionally in exterior view so a
# non-Shift mouse motion doesn't accumulate and snap the camera
# on the next Shift press.
mouse_dx_exterior, mouse_dy_exterior = 0.0, 0.0
if view_mode.is_exterior and _h is not None:
    mouse_dx_exterior, mouse_dy_exterior = _h.consume_mouse_delta()
shift_held = view_mode.is_exterior and _h is not None and (
    _h.key_state(_h.keys.KEY_LEFT_SHIFT) or
    _h.key_state(_h.keys.KEY_RIGHT_SHIFT)
)
if shift_held and director.mode is CameraMode.CHASE:
    director.chase.apply_mouse_delta(mouse_dx_exterior, mouse_dy_exterior)
```

`v_held_prev` lives in `run()` scope alongside `z_held_prev`.

### Files modified

| File | Change |
|---|---|
| `engine/cameras/chase.py` | Add `reverse_active`, `MOUSE_SENSITIVITY`, 5 new methods, modify `compute_camera`, extend `snap` |
| `engine/cameras/director.py` | Extend `zoom_in/zoom_out`; add `start_reverse`/`end_reverse`; cleanup in `toggle_mode` and `compute` auto-engage |
| `engine/host_loop.py` | Add `v_held_prev` init; add V hold + Shift+mouse handler block |
| `native/src/host/host_bindings.cc` | Expose `KEY_V`, `KEY_LEFT_SHIFT`, `KEY_RIGHT_SHIFT` |
| `tests/cameras/test_chase.py` | Append Reverse + zoom + Shift+mouse tests |
| `tests/cameras/test_director.py` | Append director-level tests for new methods + cleanup |

## §3 Constants & defaults

| Constant | Value | Rationale |
|---|---|---|
| `MOUSE_SENSITIVITY` | `0.005` rad/px | ~0.29° per pixel; 100 px sweep ≈ 29°. Roughly 2× the bridge camera's 0.0025 because Chase is "nudge an orbit camera" rather than "look around a room". Tunable post-playtest. |
| `ZOOM_FACTOR_PER_NOTCH` | `0.9` (existing) | Reused. Matches Tracking sticky-zoom step and one scroll-wheel notch. |
| `PITCH_LIMIT_RAD` | `±85°` (existing) | Reused. Same upper/lower clamp Shift+mouse and arrows share. |
| `distance_min`, `distance_max` | `CAM_MIN_RADII × radius`, `CAM_MAX_RADII × radius` (existing) | Reused. Same clamps the scroll wheel already respects. |

No new "default" distances — Reverse Chase has no separate distance state,
just the yaw flip on top of whatever `self.distance` currently holds.

## §4 Edge cases & behaviour notes

| Condition | Behaviour |
|---|---|
| `V` held while in Tracking mode | `director.start_reverse()` checks `mode is CHASE` and no-ops. Releasing `V` also no-ops. The flag never gets set. |
| `V` released while `reverse_active` was never set | `end_reverse()` calls `chase.exit_reverse()` which sets False to False. Idempotent. |
| `V` held during a CHASE → TRACKING transition | Cleanup in `toggle_mode` and `compute()` auto-engage clears `reverse_active`. When the user returns to Chase, the host-loop V state machine is in `v_held_prev=True, v_held_now=True` — neither branch fires, so reverse stays cleared until V is released and re-pressed. |
| `Shift+mouse` outside Chase (in Tracking) | Gated on `director.mode is CameraMode.CHASE`; mouse delta is still drained from `_h` to keep state clean, but `apply_mouse_delta` is not called. |
| `Shift+mouse` with delta `(0, 0)` | `apply_mouse_delta(0, 0)` is a no-op (no orbit change). |
| Mouse moves while in bridge view | Bridge already consumes the delta per-frame. Switching back to exterior with a stale accumulation is impossible. |
| Mouse moves in exterior + Chase + Shift NOT held | The unconditional exterior drain discards the delta. No surprise snap when Shift is later pressed. |
| `=`/`−` past `distance_min` / `distance_max` | Clamps. Same as Tracking sticky zoom. |
| Scroll wheel and `=`/`−` mixed | Both call into the same `distance` state with the same clamps. Composing fine. |
| Mission swap with `V` held | `director.snap()` → `chase.snap()` resets `distance` and clears `reverse_active`. V handler's edge detection re-engages reverse next frame if `V` is still held (because `reverse_active` is now False). |
| Reverse + non-zero orbit yaw | `yaw_effective = orbit_yaw_rad + π` composes additively. Arrow-key orbit while reverse-held simply rotates the flipped camera around the ship. |
| Reverse + non-zero orbit pitch | Pitch composes orthogonally; the V flip only touches `(ox, oy)`. Looking up/down behind the ship works identically to looking up/down in front. |

### Open notes

- **No spring on V transition.** Eye position pops the moment `V`
  engages. The existing rotation spring on the basis means orientation
  glides; only position pops. Playtest decides whether this is
  acceptable. If not, follow-up adds a position spring to
  `_ChaseCamera` (mirroring `_TrackingCamera`'s).
- **Sticky zoom step matches scroll-wheel step.** `=`/`−` and the wheel
  give identical 10% changes. Holding either uses OS auto-repeat for
  continuous zoom.

## §5 Testing

Pure unit tests against `_ChaseCamera` and `_CameraDirector`. No
renderer, no host loop, no PyBullet.

### Reverse Chase — extend `tests/cameras/test_chase.py`

| Test | Setup | Assertion |
|---|---|---|
| `enter_reverse` / `exit_reverse` toggle flag | post-`set_ship_radius(1.0)` | `cc.reverse_active` False → True → False; idempotent re-entry/exit |
| `reverse_active=True` flips camera to ship-front | identity ship, default orbit | Eye at `(0, +CAM_BACK_RADII, CAM_UP_RADII)` instead of `(0, −CAM_BACK_RADII, CAM_UP_RADII)` — y-component sign flipped, x and z unchanged |
| `reverse_active=False` leaves camera unchanged from baseline | identity ship, default orbit | Eye matches `(0, −CAM_BACK_RADII, CAM_UP_RADII)` — no regression |
| Reverse + non-zero orbit yaw composes | `orbit_yaw_rad = π/4`, reverse on | Eye computed with `yaw_effective = π/4 + π` |
| Reverse + ship rotation works in body frame | ship rolled 30° around body-Y, reverse on | Eye position rotates with the ship — body-frame placement preserved |
| `snap()` clears `reverse_active` and resets distance | `cc.reverse_active = True`, `cc.distance = 12345.0`, call `snap()` | `cc.reverse_active is False`, `cc.distance == cc.default_distance` |

### Sticky zoom — extend `tests/cameras/test_chase.py`

| Test | Setup | Assertion |
|---|---|---|
| `zoom_in` decreases distance by factor | post-seed; `seed = cc.distance` | After `zoom_in()`: `cc.distance == seed × ZOOM_FACTOR_PER_NOTCH` |
| `zoom_out` increases distance by factor | post-seed | After `zoom_out()`: `cc.distance == seed / ZOOM_FACTOR_PER_NOTCH` |
| `zoom_in` clamps at `distance_min` | `cc.distance = cc.distance_min` | After `zoom_in()`: still at `distance_min` |
| `zoom_out` clamps at `distance_max` | `cc.distance = cc.distance_max` | After `zoom_out()`: still at `distance_max` |
| Round-trip returns to original | `zoom_in` then `zoom_out` | `cc.distance ≈ seed` (±1e-9) |

### Shift+mouse — extend `tests/cameras/test_chase.py`

| Test | Setup | Assertion |
|---|---|---|
| `apply_mouse_delta(dx, 0)` rotates orbit yaw additively | `seed_yaw = cc.orbit_yaw_rad` | After `apply_mouse_delta(100.0, 0.0)`: `cc.orbit_yaw_rad == seed_yaw + 100 × MOUSE_SENSITIVITY` |
| `apply_mouse_delta(0, dy)` rotates pitch (sign-correct) | `seed_pitch = cc.orbit_pitch_rad` | After `apply_mouse_delta(0.0, 100.0)`: `cc.orbit_pitch_rad == seed_pitch − 100 × MOUSE_SENSITIVITY` |
| Pitch clamps at upper limit | very large negative `dy` (mouse-up sustained) — sign reflects `pitch -= dy × sens` | `cc.orbit_pitch_rad == +PITCH_LIMIT_RAD` |
| Pitch clamps at lower limit | very large positive `dy` (mouse-down sustained) | `cc.orbit_pitch_rad == −PITCH_LIMIT_RAD` |
| Zero delta is harmless | `apply_mouse_delta(0, 0)` | No state change |
| Mouse and arrow input compose | hold `KEY_RIGHT` in `apply` then `apply_mouse_delta(dx, 0)` | Yaw is sum of both contributions |

### Director — extend `tests/cameras/test_director.py`

| Test | Assertion |
|---|---|
| `director.zoom_in()` in CHASE delegates to chase | `cc.distance` decreased by factor; tracking distances unchanged |
| `director.zoom_out()` in CHASE delegates to chase | symmetric |
| `director.zoom_in/out()` in TRACKING still delegates to tracking | regression check |
| `start_reverse` in CHASE sets `chase.reverse_active = True` | direct check |
| `start_reverse` in TRACKING is no-op | `chase.reverse_active` stays False |
| `end_reverse` clears flag unconditionally | even when never started; idempotent |
| C-toggle CHASE→TRACKING clears `reverse_active` | mode switches AND `chase.reverse_active is False` |
| Target-acquisition auto-engage clears `reverse_active` | mode switches to TRACKING AND `chase.reverse_active is False` |
| `director.snap()` propagates to chase reset (incl. reverse) | both `distance` and `reverse_active` reset |

### What's not tested at unit level

- Host-loop key binding wiring (manual playtest).
- Actual GLFW keycodes for `KEY_V`, `KEY_LEFT_SHIFT`, `KEY_RIGHT_SHIFT`
  (smoke check after build).
- Mouse-delta drain interaction with bridge camera (covered manually).
- Position-jump on `V` engage feel (subjective; playtest decides whether
  to add a position spring later).

## References

- Existing implementation:
  [`engine/cameras/chase.py`](../../../engine/cameras/chase.py),
  [`engine/cameras/director.py`](../../../engine/cameras/director.py),
  [`engine/host_loop.py`](../../../engine/host_loop.py).
- Prior tracking specs:
  [`2026-06-04-tracking-camera-rework-design.md`](2026-06-04-tracking-camera-rework-design.md),
  [`2026-06-04-tracking-zoom-and-zoom-target-design.md`](2026-06-04-tracking-zoom-and-zoom-target-design.md).
- BC reference — `V` / Shift / `=` / `−` handlers:
  [`sdk/Build/scripts/TacticalInterfaceHandlers.py`](../../../sdk/Build/scripts/TacticalInterfaceHandlers.py)
  (`Zoom`, `ReverseChase`);
  [`sdk/Build/scripts/CameraModes.py`](../../../sdk/Build/scripts/CameraModes.py)
  (`Chase` and `ReverseChase` mode constructors — Reverse Chase is Chase
  with camera position flipped from `(0, −1, 0.1)` to `(0, +1, 0.1)`);
  manual:
  [`docs/ui/keyboard-mouse-reference.md`](../../docs/ui/keyboard-mouse-reference.md)
  § Camera Commands — Tactical Mode.
- Rotation-matrix convention: [`CLAUDE.md`](../../../CLAUDE.md)
  § "Rotation matrix convention — column-vector, always".
