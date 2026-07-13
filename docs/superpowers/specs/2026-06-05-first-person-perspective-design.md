# First-Person Perspective — Design

**Date:** 2026-06-05
**Status:** Design — ready for implementation plan

## Summary

Add a `perspective` flag to `_CameraDirector` so both Chase and
Tracking modes have a 1st-person variant in addition to the existing
3rd-person geometry. The 1P eye position comes from the player ship's
hardpoint — `FirstPersonCamera` if declared, `ViewscreenForward` as a
fallback. In 1P Chase the camera looks ship-forward; in 1P Tracking it
looks at the target. C is the cycle key: tap toggles mode (existing
Chase ↔ Tracking), long-press (≥ 400 ms) toggles perspective.

This is a perspective *mutator* on top of the existing mode/sub-mode
architecture — the same pattern as `reverse_active` on `_ChaseCamera`
and `zoom_target_active` on `_TrackingCamera`.

## §1 Goals & non-goals

### In scope

- `Perspective` enum (`THIRD_PERSON` | `FIRST_PERSON`) and
  `director.perspective` state.
- `director.toggle_perspective()` flips the flag and snaps the active
  camera so the eye position pops cleanly (orientation glides via the
  existing rotation spring).
- **1P Chase**: eye at hardpoint position transformed to world; look-at
  along the hardpoint's forward axis (which is ship-forward for both
  `FirstPersonCamera` and `ViewscreenForward` in the stock hardpoints);
  up = hardpoint up vector, transformed.
- **1P Tracking**: same eye placement; look-at = target world position;
  up = ship body-up perpendicularised against the new forward direction
  (same pattern as the 3P Tracking solver, so player roll is inherited).
- **Hull clearance**: if hardpoint position magnitude < `0.7 ×
  ship_radius`, push along the body-forward axis until the threshold is
  reached. Cheap heuristic; the constant is tunable post-playtest.
- **Hardpoint mount resolution**: walk `App.g_kModelPropertyManager`
  for the player's ship class. Prefer `FirstPersonCamera`, fall back to
  `ViewscreenForward`. Result cached on the director, keyed by `id(player)`.
- **C-key tap vs long-press**: tap (< 400 ms) calls `toggle_mode`,
  long-press (≥ 400 ms while still held) calls `toggle_perspective`.
  Long-press triggers on threshold crossing, not on release. Long-press
  fires exactly once per hold.
- **Graceful degradation**: ships with neither hardpoint property fall
  back to 3P even when perspective is FIRST_PERSON; one-shot log warning
  identifies the ship class.

### Out of scope (deferred)

- **Shift+mouse "look around the cockpit"** in 1P. Default: Shift+mouse
  no-op in 1P. Could be added as a yaw/pitch offset on the hardpoint
  basis later.
- **Wider FOV in 1P**. Reuses `director.fov_y_rad` (currently 70°).
- **Skipping the player ship NIF** when in 1P. Render side may need to
  cull the player mesh later; the bounding-sphere nudge is the
  first-line defence and may suffice.
- **"Reverse 1P"** (V-held look-back from the bridge). Deferred; could
  mirror the 3P `V` handler if useful.
- **Other Viewscreen properties** (Back / Left / Right / Up / Down).
  Only `FirstPersonCamera` and `ViewscreenForward` are read here.
- **Ships changing class mid-mission**. Mount cache invalidates on
  player swap (different `id(player)`), not on class change within the
  same Python object. Won't matter for stock missions.
- **Other tunables** (`HULL_CLEARANCE_FACTOR`, `C_LONG_PRESS_MS`):
  picked once based on best-guess; revisit if playtest exposes issues.

## §2 State & architecture

### `Perspective` enum + director additions

```python
# engine/cameras/__init__.py — exported alongside CameraMode
class Perspective(Enum):
    THIRD_PERSON = "third_person"
    FIRST_PERSON = "first_person"
```

```python
# engine/cameras/director.py — new fields and methods
class _CameraDirector:
    def __init__(self):
        # ... existing fields ...
        self.perspective = Perspective.THIRD_PERSON
        self._mount_cache_player_id = None
        self._mount_cache             = None  # Optional[Mount]

    def toggle_perspective(self) -> None:
        """Long-press C handler. Flips perspective. Snaps the active
        camera so eye position pops cleanly; orientation still glides
        via the rotation spring."""

    def is_first_person(self) -> bool:
        """Convenience for callers that want a boolean."""

    def _get_first_person_mount(self, player):
        """Returns cached Mount or re-resolves on player swap.
        Returns None if hardpoint declares neither property."""
```

### New module — `engine/cameras/first_person.py`

```python
@dataclass(frozen=True)
class Mount:
    position:    TGPoint3  # body-frame (post-nudge)
    forward:     TGPoint3  # body-frame unit
    up:          TGPoint3  # body-frame unit
    ship_radius: float     # cached so camera classes don't need a player ref


@dataclass(frozen=True)
class Pose:
    eye:     tuple    # (x, y, z) world
    forward: tuple    # unit (x, y, z) world
    up:      tuple    # unit (x, y, z) world


HULL_CLEARANCE_FACTOR: float = 0.7


def resolve_first_person_mount(player) -> Optional[Mount]:
    """Read player's hardpoint. Prefer FirstPersonCamera; fall back to
    ViewscreenForward. Returns None if neither is declared.

    Applies the hull-clearance nudge to the body-frame position before
    storing in the Mount."""


def transform_mount_to_world(mount, ship_loc, ship_rot) -> Pose:
    """Apply ship's world transform to the body-frame Mount. Position
    nudge already applied during resolve_first_person_mount."""
```

The body-frame → world transform uses BC's column-vector convention
(`world_axis_j = ship_rot.GetCol(j)`), matching the existing
body-frame projection in `_ChaseCamera.compute_camera`.

### `_ChaseCamera` additions

```python
def compute_camera(self, ship_loc, ship_rot, dt=None,
                   first_person_mount=None) -> tuple:
    if first_person_mount is not None:
        return self._compute_first_person(ship_loc, ship_rot,
                                          mount=first_person_mount, dt=dt)
    # ... existing 3P orbit + reverse + spring code unchanged ...

def _compute_first_person(self, ship_loc, ship_rot, *, mount, dt):
    """1P Chase. Eye at hardpoint world position; look-at along the
    hardpoint forward axis transformed by ship rotation; up from the
    hardpoint up vector transformed. Rotation spring applied to
    ship_rot so the cockpit view glides rather than snaps on rapid
    manoeuvres. No orbit, no zoom, no reverse — existing 3P state
    (orbit angles, distance, reverse_active) is preserved across the
    perspective toggle."""
```

### `_TrackingCamera` additions

```python
def compute(self, player, target, dt,
            first_person_mount=None):
    if first_person_mount is not None:
        return self._compute_first_person_tracking(
            player, target, mount=first_person_mount, dt=dt)
    # ... existing 3P branch + ZoomTarget dispatch unchanged ...

def _compute_first_person_tracking(self, player, target, *, mount, dt):
    """1P Tracking. Eye at hardpoint world position; look-at = target
    world position; up = ship body-up perpendicularised against the
    forward direction. No rotation spring (subject to playtest), no
    ZoomTarget sub-mode interaction. 3P state (d_chase_*,
    zoom_target_active) is preserved across the toggle."""
```

### Director dispatch in `compute()`

```python
def compute(self, *, player, dt):
    # ... existing auto-engage and target-loss logic unchanged ...
    mount = (self._get_first_person_mount(player)
             if self.perspective is Perspective.FIRST_PERSON else None)
    if self.mode is CameraMode.TRACKING and tgt is not None:
        return self.tracking.compute(player, tgt, dt=dt,
                                     first_person_mount=mount)
    return self.chase.compute_camera(loc, rot, dt=dt,
                                     first_person_mount=mount)
```

If `perspective` is FIRST_PERSON but `mount` is None (missing
hardpoint), both camera classes ignore the absent mount and the
existing 3P geometry runs. A one-shot warning logs the ship class on
first miss per session.

### Mode-transition cleanup

- `director.snap()`: reset `perspective` to `THIRD_PERSON`; clear mount
  cache. Mission swap = clean slate.
- `director.toggle_perspective()`: snaps the active camera (the existing
  `_ChaseCamera.snap()` / `_TrackingCamera.snap()` methods, which already
  drop position-spring state and reset distances) so the eye position
  pop doesn't drift through intermediate positions.

### Host-loop wiring — C-key tap-vs-long-press

Replace the existing single-line `if _h.key_pressed(KEY_C): toggle_mode`
with a press/hold/release state machine:

```python
C_LONG_PRESS_MS = 400

# Per-loop state (initialised alongside z_held_prev, v_held_prev):
c_press_start_ms:  float | None = None
c_long_press_fired: bool         = False

# Per frame, inside the existing exterior/player/_h/pause guard:
import time
now_ms = time.monotonic() * 1000.0
c_held_now = view_mode.is_exterior and _h.key_state(_h.keys.KEY_C)
if c_held_now and c_press_start_ms is None:
    c_press_start_ms  = now_ms
    c_long_press_fired = False
elif c_held_now and not c_long_press_fired and \
     (now_ms - c_press_start_ms) >= C_LONG_PRESS_MS:
    director.toggle_perspective()
    c_long_press_fired = True
elif not c_held_now and c_press_start_ms is not None:
    if not c_long_press_fired:
        director.toggle_mode(player=player)   # short tap
    c_press_start_ms   = None
    c_long_press_fired = False
```

The clock source is `time.monotonic()` so frame-rate variability
doesn't affect the threshold check. The state vars live in `run()`
scope, alongside `z_held_prev` / `v_held_prev`.

### Files modified

| File | Change |
|---|---|
| `engine/cameras/__init__.py` | Export `Perspective` enum. |
| `engine/cameras/first_person.py` *(new)* | `Mount`, `Pose` dataclasses; `resolve_first_person_mount`, `transform_mount_to_world`; `HULL_CLEARANCE_FACTOR`. |
| `engine/cameras/director.py` | Add `perspective` field + `toggle_perspective` + mount cache + dispatch with `first_person_mount=`. |
| `engine/cameras/chase.py` | Add `first_person_mount` kwarg + `_compute_first_person` helper. |
| `engine/cameras/tracking.py` | Add `first_person_mount` kwarg + `_compute_first_person_tracking` helper. |
| `engine/host_loop.py` | Replace `key_pressed(KEY_C)` handler with tap/long-press state machine. Add `c_press_start_ms` / `c_long_press_fired` to `run()` scope. |
| `tests/cameras/test_first_person.py` *(new)* | Mount resolution + hull clearance + body-to-world transform. |
| `tests/cameras/test_chase.py` | Append 1P Chase tests. |
| `tests/cameras/test_tracking_geometry.py` | Append 1P Tracking tests. |
| `tests/cameras/test_director.py` | Append perspective toggle + dispatch + cleanup tests. |
| `tests/host/test_view_mode.py` *(extend)* | C-key tap vs long-press state-machine tests with fake clock. |

## §3 1P geometry

### Reading the hardpoint

```python
def _lookup_property(player, name: str):
    ship_class_name = player.GetShipClass()
    return App.g_kModelPropertyManager.GetLocalTemplate(
        ship_class_name, name)
```

`PositionOrientationProperty` exposes:
- `GetPosition() → TGPoint3` (body frame)
- `GetForward() → TGPoint3` (body frame unit)
- `GetUp() → TGPoint3` (body frame unit)

`resolve_first_person_mount(player)`:
1. Look up `"FirstPersonCamera"`. If present → use its position/forward/up.
2. Else look up `"ViewscreenForward"`. If present → use its values.
3. Else return None.
4. Apply hull clearance nudge to the body-frame position.
5. Return `Mount(position, forward, up, ship_radius=player.GetRadius())`.

### Hull-clearance nudge

```python
def _nudge_clear_of_hull(pos_body: TGPoint3, ship_radius: float) -> TGPoint3:
    """If |pos_body| < HULL_CLEARANCE_FACTOR × ship_radius, push along
    ship body-forward (+y) until the threshold is reached. Otherwise
    return pos_body unchanged."""
    threshold = HULL_CLEARANCE_FACTOR * ship_radius
    mag = pos_body.Length()
    if mag >= threshold:
        return pos_body
    deficit = threshold - mag
    return TGPoint3(pos_body.x, pos_body.y + deficit, pos_body.z)
```

The +y-only push assumes:
- The ship's hull centres on the body origin.
- The bridge mount sits forward (or at least not aft) of origin.

Both hold for the stock hardpoints (Galaxy: FirstPersonCamera y=3.3,
Sovereign: ViewscreenForward y=2.4). A ventral-aft hardpoint would
push further forward than expected, but those don't exist for
cockpit/viewscreen properties.

`ship_radius = 0` → threshold = 0 → no nudge. Degenerate-ship safe.

### Body frame → world transform

```python
def transform_mount_to_world(mount, ship_loc, ship_rot) -> Pose:
    rgt = ship_rot.GetCol(0)
    fwd = ship_rot.GetCol(1)
    up  = ship_rot.GetCol(2)

    def _to_world(v):
        return (v.x * rgt.x + v.y * fwd.x + v.z * up.x,
                v.x * rgt.y + v.y * fwd.y + v.z * up.y,
                v.x * rgt.z + v.y * fwd.z + v.z * up.z)

    eye_offset = _to_world(mount.position)
    return Pose(
        eye     = (ship_loc.x + eye_offset[0],
                   ship_loc.y + eye_offset[1],
                   ship_loc.z + eye_offset[2]),
        forward = _to_world(mount.forward),
        up      = _to_world(mount.up),
    )
```

Matches BC's column-vector convention (CLAUDE.md). The same projection
used by `_ChaseCamera.compute_camera`'s body-frame offset code.

### `_compute_first_person` (Chase)

```python
def _compute_first_person(self, ship_loc, ship_rot, *, mount, dt):
    basis = (self._advance_smoothing(ship_rot, dt)
             if dt is not None else ship_rot)
    pose = transform_mount_to_world(mount, ship_loc, basis)
    look_at = (pose.eye[0] + pose.forward[0],
               pose.eye[1] + pose.forward[1],
               pose.eye[2] + pose.forward[2])
    return pose.eye, look_at, pose.up
```

Rotation spring is applied to ship_rot before the body→world
projection so the cockpit view glides smoothly on rapid manoeuvres.
Position is fixed to the hardpoint mount — no smoothing.

### `_compute_first_person_tracking`

```python
def _compute_first_person_tracking(self, player, target, *, mount, dt):
    ship_rot = player.GetWorldRotation()
    ship_loc = player.GetWorldLocation()
    pose = transform_mount_to_world(mount, ship_loc, ship_rot)

    tgt_loc = target.GetWorldLocation()
    dx, dy, dz = (tgt_loc.x - pose.eye[0],
                  tgt_loc.y - pose.eye[1],
                  tgt_loc.z - pose.eye[2])
    flen = sqrt(dx*dx + dy*dy + dz*dz)
    forward = (dx/flen, dy/flen, dz/flen)

    body_up = ship_rot.GetCol(2)
    dot = (body_up.x*forward[0] + body_up.y*forward[1] + body_up.z*forward[2])
    ux = body_up.x - dot * forward[0]
    uy = body_up.y - dot * forward[1]
    uz = body_up.z - dot * forward[2]
    ulen = sqrt(ux*ux + uy*uy + uz*uz)
    up = (ux/ulen, uy/ulen, uz/ulen)

    look_at = (pose.eye[0] + forward[0],
               pose.eye[1] + forward[1],
               pose.eye[2] + forward[2])
    return pose.eye, look_at, up
```

Eye and look-at derive directly from hardpoint position and target
position. No rotation spring (deferred until playtest shows it's
needed). `zoom_target_active` and `d_chase_zoom` are not consulted in
this path.

### Edge cases

| Condition | Behaviour |
|---|---|
| Hardpoint has neither `FirstPersonCamera` nor `ViewscreenForward` | `resolve_first_person_mount` returns None. Director's `compute()` passes `mount=None`; both camera classes fall through to 3P for that frame. `toggle_perspective` logs a one-shot warning ("FirstPerson camera unavailable for {ship_class}") and reverts perspective to ThirdPerson. |
| `ship_radius == 0` | `_nudge_clear_of_hull` no-ops; eye sits at body-frame position. |
| Target == player | Director's `_valid_target` already rejects `tgt is player`; `_compute_first_person_tracking` never sees this case. |
| Hardpoint forward = hardpoint up (degenerate basis) | In `_compute_first_person_tracking`, forward is computed from look-at (target − eye), not from hardpoint, so the hardpoint's forward axis is unused there. In `_compute_first_person` (Chase), the hardpoint forward becomes look direction; if hardpoint up = hardpoint forward, project hardpoint up onto plane perpendicular to forward; if degenerate after projection, pick world-X (same fallback as `_TrackingCamera._plane_basis`). |
| Player swap mid-mission | `_get_first_person_mount` keys cache on `id(player)`; the next call after a swap re-resolves automatically. |

## §4 Testing

Pure unit tests against `_CameraDirector`, `_ChaseCamera`,
`_TrackingCamera`, and the new `first_person` module. No renderer, no
host loop, no PyBullet.

### `first_person` module — `tests/cameras/test_first_person.py` *(new)*

| Test | Setup | Assertion |
|---|---|---|
| Mount resolution prefers FirstPersonCamera | Fake hardpoint registers both `FirstPersonCamera` (0, 3.3, 0.307) and `ViewscreenForward` (0, 2.9, 0.5) | Returned Mount.position pre-nudge = FirstPersonCamera's |
| Mount resolution falls back to ViewscreenForward | Fake hardpoint registers only `ViewscreenForward` | Returned Mount.position pre-nudge = ViewscreenForward's |
| Mount resolution returns None when neither exists | Empty hardpoint | `resolve_first_person_mount(player)` returns None |
| Hull-clearance nudge no-ops when position already clear | position = (0, 5.0, 0), ship_radius = 1.0 | Returned position unchanged (1e-12) |
| Hull-clearance nudge pushes forward when inside threshold | position = (0, 0.3, 0), ship_radius = 1.0 | Returned position = (0, 0.7, 0); only +y changed |
| Hull-clearance nudge with radius = 0 | position = (0, 0.3, 0), ship_radius = 0 | Returned position unchanged |
| Body-to-world transform: identity ship | Mount (position (0, 3.3, 0.307), forward (0,1,0), up (0,0,1)), ship_loc (0,0,0), ship_rot identity | Pose.eye = (0, 3.3, 0.307); pose.forward = (0, 1, 0); pose.up = (0, 0, 1) |
| Body-to-world transform: ship rotated +90° around body-Z | identity hardpoint; ship rot = +90° yaw | Pose.eye.x ≠ 0 (rotated); forward direction rotated; up direction rotated |

### 1P Chase — extend `tests/cameras/test_chase.py`

| Test | Setup | Assertion |
|---|---|---|
| 1P Chase eye is at hardpoint world position | identity ship, Mount with position (0, 3.3, 0.307) | Returned eye = (0, 3.3, 0.307) (within 1e-9) |
| 1P Chase look-at is along ship-forward | same; mount.forward = (0, 1, 0) | (look_at - eye) normalised = (0, 1, 0) |
| 1P Chase up matches mount up vector | same; mount.up = (0, 0, 1) | Returned up = (0, 0, 1) |
| 1P Chase inherits ship rotation | Ship rotated +90° around body-Z | Eye rotated; forward rotated |
| 1P Chase preserves 3P state | Set orbit_yaw = 1.0, distance = 10.0, reverse_active = True; compute 1P; then compute 3P | 3P output matches a fresh 3P-only call with the same orbit state |

### 1P Tracking — extend `tests/cameras/test_tracking_geometry.py`

| Test | Setup | Assertion |
|---|---|---|
| 1P Tracking eye is at hardpoint position | identity ship, target at (0, 100, 0), Mount position (0, 3.3, 0.307) | Eye = (0, 3.3, 0.307) |
| 1P Tracking look-at = target | same | (look_at - eye) normalised points toward target world position |
| 1P Tracking up inherits ship body-up | Ship rolled 30° around body-Y; identity hardpoint up | Returned up = body-up perpendicularised against forward; zero X-component world matches body-roll projection |
| 1P Tracking ignores d_chase_zoom and zoom_target_active | Set d_chase_zoom = 5, zoom_target_active = True; compute 1P | Eye unchanged from non-zoom-target 1P case; flag not consulted |
| 1P Tracking returns finite output when target near eye | Mount position (0, 3.3, 0.307); target at (0, 3.5, 0.307) | All output components finite |

### Director — extend `tests/cameras/test_director.py`

| Test | Assertion |
|---|---|
| `perspective` defaults to ThirdPerson | `_CameraDirector().perspective is Perspective.THIRD_PERSON` |
| `toggle_perspective` flips the flag | THIRD_PERSON → FIRST_PERSON → THIRD_PERSON |
| `toggle_perspective` snaps the active camera | Stub `chase.snap` / `tracking.snap`; toggle in each mode; verify the right one fired |
| `compute` in 1P + valid hardpoint dispatches with mount | Patch compute methods to record `first_person_mount=`; verify non-None |
| `compute` in 1P + missing hardpoint falls back to 3P | Player hardpoint declares neither property; compute returns 3P output; warning logged once |
| `compute` in 3P never passes mount | `first_person_mount=` kwarg stays None even when hardpoint declares FirstPersonCamera |
| `snap` resets perspective to ThirdPerson | director.perspective = FIRST_PERSON; snap(); back to THIRD_PERSON |
| `snap` clears mount cache | Set cached mount; snap(); next compute() re-resolves from hardpoint |
| Mount cache invalidates on player swap | Compute with player_a; player_b has different hardpoint values; compute with player_b returns new values |

### Host-loop C-key state machine — extend `tests/host/test_view_mode.py`

Inject a fake clock into the C-key handler. Tests verify tap-vs-long-press dispatch.

| Test | Setup | Assertion |
|---|---|---|
| Tap (press + release within threshold) calls `toggle_mode` | Press at t=0, release at t=200ms (threshold=400ms) | `toggle_mode` called once; `toggle_perspective` not called |
| Long-press (held past threshold) calls `toggle_perspective` | Press at t=0, frame at t=500ms with key held | `toggle_perspective` called once; `toggle_mode` not called |
| Long-press fires once per hold | Press at t=0, frames at t=500/600/700ms with key held | `toggle_perspective` called exactly once |
| Release after long-press fires no tap action | Long-press fires, release at t=800ms | No additional `toggle_mode` call |
| Multiple tap cycles fire multiple `toggle_mode` calls | Three tap/release cycles | `toggle_mode` called three times |
| State cleared between presses | Release; press again | Subsequent press correctly tracks new timer |

### What's not tested at unit level
- Rendered output (subjective; manual playtest).
- Player ship NIF occlusion in 1P (visual; deferred per §1).
- `C_LONG_PRESS_MS = 400` threshold tuning (subjective; constant tunable).
- "Look around the cockpit" Shift+mouse (deferred per §1).

## References

- Hardpoint property reader & layout:
  [`sdk/Build/scripts/ships/Hardpoints/galaxy.py`](../../../sdk/Build/scripts/ships/Hardpoints/galaxy.py)
  lines 1134–1230 (Viewscreen* + FirstPersonCamera).
- Prior reverse-flag mutator pattern:
  [`docs/superpowers/specs/2026-06-04-chase-mode-polish-design.md`](2026-06-04-chase-mode-polish-design.md) §2.
- Prior ZoomTarget sub-mode pattern:
  [`docs/superpowers/specs/2026-06-04-tracking-zoom-and-zoom-target-design.md`](2026-06-04-tracking-zoom-and-zoom-target-design.md) §3.
- Rotation-matrix convention: [`CLAUDE.md`](../../../CLAUDE.md)
  § "Rotation matrix convention — column-vector, always".
- BC keyboard reference (C-key entry):
  [`docs/ui/keyboard-mouse-reference.md`](../../docs/ui/keyboard-mouse-reference.md)
  § Camera Commands — Tactical Mode.
