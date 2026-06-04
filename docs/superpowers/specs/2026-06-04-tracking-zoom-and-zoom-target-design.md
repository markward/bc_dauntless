# Tracking Zoom + ZoomTarget Mode — Design

**Date:** 2026-06-04
**Status:** Design — ready for implementation plan

## Summary

Add two BC tactical-camera features to the existing `_TrackingCamera`:

1. **ZoomTarget** — while `Z` is held, the camera slides "over" the player
   along the player→target axis and frames the target at the screen
   centre, at the same chase-distance from the target that Tracking
   uses from the player. On release, the camera smoothly returns.
2. **Sticky zoom** — `=` brings the camera closer to its anchor (player
   in normal Tracking, target in ZoomTarget); `−` pushes it farther.
   `+` (shift-=) is intentionally inert. Zoom persists across mode
   transitions; mission-swap resets.

Both are deferred Tracking-mode polish from
[`2026-06-04-tracking-camera-rework-design.md`](2026-06-04-tracking-camera-rework-design.md).

## §1 Goals & non-goals

### In scope
- `Z` (held) — ZoomTarget framing on top of the existing Tracking solver.
- `=` / `−` — sticky zoom against whichever distance the current
  framing uses (Tracking anchor → player; ZoomTarget anchor → target).
- ZoomTarget starts at its minimum distance; `=` is a no-op on entry
  until the user has pressed `−` at least once.
- Zoom value persists across target switches, Z press/release, and
  Chase↔Tracking toggles. Mission swap (`director.snap()`) resets.
- All wiring stays inside `_TrackingCamera` (sub-mode flag plus two
  distance slots) and thin director plumbing for the `Z`, `=`, `−`
  keys.

### Out of scope (deferred follow-ups)
- Chase Mode (free-orbit) sticky zoom — the existing scroll wheel
  covers the gap.
- `V` Reverse Chase.
- Cinematic Mode (`F9` + `F1`–`F6`) and its six camera variants.
- Bridge viewscreen camera.
- A real mode-stack abstraction in the director — only one push state
  is in play here, so a boolean flag is enough.

## §2 State & architecture

`_TrackingCamera` gains four state fields and one branch in `compute()`.
Nothing else moves.

### New state on `_TrackingCamera`

| Field | Meaning |
|---|---|
| `zoom_target_active: bool` | Driven by the `Z` key state — true while held |
| `d_chase_tracking: float` | Sticky zoom for normal Tracking framing — replaces today's `d_chase`, persists |
| `d_chase_zoom: float` | Sticky zoom for ZoomTarget framing (eye → target distance), persists |
| `zoom_min: float` / `zoom_max: float` | Clamp bounds for both distances, set in `set_ship_radius()` |

The current `d_chase` is renamed `d_chase_tracking` to make the
dual-distance state explicit.

### Zoom step / clamp constants (class-level)

```
ZOOM_FACTOR_PER_PRESS = 0.9     # one =/- press = ×0.9 / ÷0.9
ZOOM_MIN_RADII        = 0.6     # reuse CAM_MIN_RADII semantics
ZOOM_MAX_RADII        = 30.0    # reuse CAM_MAX_RADII semantics
ZOOM_DEFAULT_RADII    = 0.6     # ZoomTarget starts at min — = is initially a no-op
```

`set_ship_radius(r)` initialises:

```
d_chase_tracking = sqrt(CAM_BACK_RADII**2 + CAM_UP_RADII**2) * r   # default Tracking
d_chase_zoom     = ZOOM_DEFAULT_RADII * r                          # = zoom_min
zoom_min         = ZOOM_MIN_RADII * r
zoom_max         = ZOOM_MAX_RADII * r
```

### New methods on `_TrackingCamera`

```
zoom_in()              — *= ZOOM_FACTOR_PER_PRESS on active distance, clamp at zoom_min
zoom_out()             — /= ZOOM_FACTOR_PER_PRESS on active distance, clamp at zoom_max
enter_zoom_target()    — zoom_target_active = True; does NOT reset d_chase_zoom
exit_zoom_target()     — zoom_target_active = False
snap()                 — resets d_chase_tracking / d_chase_zoom to seeded defaults,
                          clears zoom_target_active, plus the existing eye/basis snap
```

### `compute()` branch

After the existing plane-basis construction (still needed for the `e3`
body-up direction), branch:

- `zoom_target_active = False` → existing two-angle solver, parameterised
  by `d_chase_tracking`.
- `zoom_target_active = True` → ZoomTarget path (§3).

The position + rotation springs run on the **smoothed** output regardless
of branch. Toggling `zoom_target_active` produces a discontinuous solver
output; the springs naturally interpolate over ~τ, giving the press /
release transition as a free smooth glide.

### Director additions

| Method | Behaviour |
|---|---|
| `start_zoom_target(*, player)` | If `mode is TRACKING` and `_valid_target(player) is not None`, call `tracking.enter_zoom_target()`. Otherwise no-op. |
| `end_zoom_target()` | Unconditionally call `tracking.exit_zoom_target()`. |
| `zoom_in()` / `zoom_out()` | If `mode is TRACKING`, delegate to `tracking`. Otherwise no-op (Chase sticky zoom is deferred). |
| `snap()` (existing) | Continues to forward to both cameras' `snap()`; tracking's snap now also resets zoom state. |

`start_zoom_target` gates on `mode is TRACKING` because Tracking is the
only mode that knows about ZoomTarget. In Chase Mode (no target), `Z`
does nothing — consistent with the auto-engage rule from
[`2026-06-04-tracking-camera-rework-design.md`](2026-06-04-tracking-camera-rework-design.md)
that says target acquisition is what switches the director into
Tracking.

### Mode-transition cleanup

| Trigger | Action |
|---|---|
| Target lost mid-Tracking (durable fallback in `director.compute()`) | Also call `tracking.exit_zoom_target()` so `zoom_target_active` doesn't get stuck |
| C-key toggle from TRACKING to CHASE | Also call `tracking.exit_zoom_target()` |

## §3 ZoomTarget geometry

Working in the same `(e1, e3)` plane as the Tracking solver:

```
e1 = (target − player).normalised                       # ship→target axis
e3 = (B − (B·e1) e1).normalised                          # body-up perpendicularised
```

### Eye placement

```
eye = target_pos − e1 × d_chase_zoom
```

Camera sits `d_chase_zoom` "behind" the target along the ship→target
axis (on the player-side of the target).

### Forward

```
forward = (target − eye).normalised  =  e1
```

Eye lies on the ship→target line, so the forward unit vector collapses
to `e1`. Target projects exactly at screen-centre.

### Up

`e3` re-projected perpendicular to `forward` and normalised — identical
to the Tracking solver's up step. Inherits player roll.

### Right

Falls out as `forward × up`, packed into the basis matrix for the
rotation spring.

### Player position in this framing

For `S = player_pos`, `T = target_pos`, `D = |T − S|`:

```
(S − eye) = S − (T − e1 × d_chase_zoom) = −D × e1 + d_chase_zoom × e1
         = (d_chase_zoom − D) × e1
```

Since `d_chase_zoom < D` in the normal case (zoom-target sits between
player and target), the e1-component is negative, meaning the player is
**behind** the camera. `(S − eye) · forward < 0` — player off-screen
behind. As intended: target dominates, player isn't in frame.

### FOV

Unchanged — same `EXTERIOR_FOV_Y_RAD = 60°` as Tracking. ZoomTarget
achieves its zoomed feel via the closer eye position, not via FOV
narrowing.

### Edge cases

| Condition | Behaviour |
|---|---|
| No target | `start_zoom_target` rejects; Z hold is ignored. Tracking continues. |
| Target acquired mid-Z-hold | Host-loop polls Z each frame and retries `start_zoom_target` whenever `Z held AND not zoom_target_active`. The next frame after target acquisition succeeds. |
| Target lost mid-Z-hold | Tracking's existing durable-fallback fires in `compute()`; cleanup also clears `zoom_target_active`. |
| `D < d_chase_zoom` (target inside chase distance) | Use an effective distance `min(d_chase_zoom, 0.9 × D)` for the eye placement that frame. Do **not** mutate the stored `d_chase_zoom` — preserve the user's zoom setting for when `D` grows again. Cosmetic; revisit if it feels wrong. |
| `B` parallel to `(T − S)` | Same as Tracking's `_plane_basis` fallback (arbitrary perpendicular to `e1`). No new handling. |

## §4 Sticky zoom semantics

### Dispatch

```python
def zoom_in(self):
    if self.zoom_target_active:
        self.d_chase_zoom = max(self.d_chase_zoom * self.ZOOM_FACTOR_PER_PRESS,
                                self.zoom_min)
    else:
        self.d_chase_tracking = max(self.d_chase_tracking * self.ZOOM_FACTOR_PER_PRESS,
                                    self.zoom_min)

def zoom_out(self):
    if self.zoom_target_active:
        self.d_chase_zoom = min(self.d_chase_zoom / self.ZOOM_FACTOR_PER_PRESS,
                                self.zoom_max)
    else:
        self.d_chase_tracking = min(self.d_chase_tracking / self.ZOOM_FACTOR_PER_PRESS,
                                    self.zoom_max)
```

### "= initially no-op" behaviour

Since `set_ship_radius` seeds `d_chase_zoom = zoom_min`, the first `=`
press while in ZoomTarget tries `× 0.9`, clamps back to floor, no
visible change. After one `−` press, `d_chase_zoom > zoom_min`, and `=`
becomes effective. Matches the BC behaviour observed in playtest.

### `+` inertness

`+` requires Shift. The host-loop binds `key_pressed(KEY_EQUAL)`, which
fires on the bare `=` key event. `Shift+=` produces a different keycode
the host-loop does not listen for. Nothing extra to do.

### Persistence

- Mode transitions (Z press/release, target switch, Chase↔Tracking
  C-toggle): zoom values **kept**.
- Mission swap → `director.snap()` → `_TrackingCamera.snap()` resets
  both distances to their `set_ship_radius`-seeded values.

### Spring interaction

Zoom changes the solver output; the existing position spring smooths
the camera's actual position toward the new solver eye over ~τ. Each
`=` / `−` press is felt as a smooth glide, not a jump.

### Edge case — zoom with no target

Director is in Chase Mode (target absence forces Chase per the
auto-engage rule). Per §2, `director.zoom_in/out()` is a no-op in Chase.
The player can mash `=` with no target; nothing happens.

## §5 Director integration & key bindings

### Z handling — held, not pressed

```python
z_held_now = view_mode.is_exterior and _h.key_state(_h.keys.KEY_Z)
if z_held_now and not director.tracking.zoom_target_active:
    director.start_zoom_target(player=player)
elif z_held_prev and not z_held_now:
    director.end_zoom_target()
z_held_prev = z_held_now
```

The `not director.tracking.zoom_target_active` guard on the entry
branch lets Z-held-through-target-acquisition succeed on whichever
frame the target appears, without re-firing on later frames.

`z_held_prev` lives in the outer `run()` scope alongside other
loop-local state.

### `=` / `−` handling — press-edge

```python
if view_mode.is_exterior and _h.key_pressed(_h.keys.KEY_EQUAL):
    director.zoom_in()
if view_mode.is_exterior and _h.key_pressed(_h.keys.KEY_MINUS):
    director.zoom_out()
```

`key_pressed` fires once per OS-level key event. OS auto-repeat
produces continuous zoom when the key is held — matches stock keyboard
behaviour. No custom repeat logic needed.

### Insertion point in `host_loop.py`

Same block as the existing `C` key handler — post-`director.chase.apply(...)`,
gated on `view_mode.is_exterior and player is not None and _h is not
None and not pause.is_open`:

```python
if view_mode.is_exterior and player is not None and _h is not None and not pause.is_open:
    if _h.key_pressed(_h.keys.KEY_C):
        director.toggle_mode(player=player)
    # Z hold — ZoomTarget mode
    z_held_now = _h.key_state(_h.keys.KEY_Z)
    if z_held_now and not director.tracking.zoom_target_active:
        director.start_zoom_target(player=player)
    elif z_held_prev and not z_held_now:
        director.end_zoom_target()
    z_held_prev = z_held_now
    # Sticky zoom
    if _h.key_pressed(_h.keys.KEY_EQUAL):
        director.zoom_in()
    if _h.key_pressed(_h.keys.KEY_MINUS):
        director.zoom_out()
```

### Key bindings to add to `_dauntless_host`

`KEY_Z`, `KEY_EQUAL`, `KEY_MINUS`. The current bindings module already
exposes `KEY_C`, `KEY_T`, etc. — adding three more is straight
plumbing.

## §6 Testing

Pure unit tests against `_TrackingCamera` and `_CameraDirector`. No
renderer, no host loop, no PyBullet.

### Geometry — extend `tests/cameras/test_tracking_geometry.py`

| Test | Setup | Assertion |
|---|---|---|
| ZoomTarget eye lies on player→target axis | identity ship, S=(0,0,0), T=(0,20,0), `d_chase_zoom = 5`, `zoom_target_active = True` | Eye = (0, 15, 0); forward = (0, 1, 0); up perpendicular to forward, in (e1, e3) plane |
| ZoomTarget target projects to screen-centre | same | Project T into camera frame → screen_y ≈ 0 (±1e-9) |
| ZoomTarget framing independent of target range | sweep `\|T−S\|` ∈ {5, 50, 500}, fixed `d_chase_zoom = 5` | Target screen-Y stays ≈ 0; eye stays exactly `d_chase_zoom` from target |
| ZoomTarget inherits player roll into camera up | ship rolled 30° around body-Y | `up` ≈ projection of body-up perpendicular to forward, no world-Z |
| ZoomTarget `D < d_chase_zoom` clamp | `D = 3`, `d_chase_zoom = 10` | Eye still in front of target along −e1; not "past" target |
| ZoomTarget eye is between player and target | T behind S in world | Sign sanity — eye is between S and T regardless of orientation |

### Sticky zoom — new `tests/cameras/test_tracking_zoom.py`

| Test | Setup | Assertion |
|---|---|---|
| `zoom_in` while not in ZoomTarget modifies `d_chase_tracking` | post-`set_ship_radius(1.0)`; `zoom_target_active = False` | `d_chase_tracking` drops by factor `ZOOM_FACTOR_PER_PRESS`; `d_chase_zoom` unchanged |
| `zoom_in` while in ZoomTarget modifies `d_chase_zoom` | `zoom_target_active = True`; pre-zoom-out so `d_chase_zoom > zoom_min` | `d_chase_zoom` drops by factor; `d_chase_tracking` unchanged |
| `zoom_in` clamps at `zoom_min` | `d_chase_zoom = zoom_min` initially | After `zoom_in()`, `d_chase_zoom == zoom_min` (no-op) — matches "= initially does nothing" |
| `zoom_out` clamps at `zoom_max` | `d_chase_tracking = zoom_max` initially | After `zoom_out()`, `d_chase_tracking == zoom_max` |
| Round-trip zoom returns to original | `zoom_in()` then `zoom_out()` | `d_chase_*` back to seed value (±1e-9) |
| Zoom persists across `enter_zoom_target` / `exit_zoom_target` | set `d_chase_tracking = 0.7 × default`; toggle Z on/off | `d_chase_tracking` still `0.7 × default` after exit |
| `snap()` resets both distances and clears Z flag | mutate both; set Z flag; call `snap()` | Both equal seeded values; `zoom_target_active = False` |

### Director — extend `tests/cameras/test_director.py`

| Test | Assertion |
|---|---|
| `start_zoom_target` in CHASE no-ops | `tracking.zoom_target_active` stays False |
| `start_zoom_target` in TRACKING with valid target sets flag | direct check |
| `start_zoom_target` in TRACKING with no target no-ops | guard fires |
| `end_zoom_target` clears the flag unconditionally | even when called before any start |
| `zoom_in` / `zoom_out` in CHASE no-op | no distance mutation on tracking |
| `zoom_in` / `zoom_out` in TRACKING delegate to tracking | distance changes per `ZOOM_FACTOR_PER_PRESS` |
| Target-lost durable fallback also calls `exit_zoom_target` | enter ZoomTarget; null the target; `compute()` → mode CHASE AND `zoom_target_active = False` |
| C-toggle TRACKING→CHASE also calls `exit_zoom_target` | enter ZoomTarget; `toggle_mode()` → mode CHASE AND `zoom_target_active = False` |
| `director.snap()` propagates to clear zoom state | both distances reset, `zoom_target_active = False` |

### Spring continuity — extend `tests/cameras/test_tracking_springs.py`

| Test | Setup | Assertion |
|---|---|---|
| Z press: smoothed eye lags then converges to ZoomTarget pose | Seed at Tracking pose; flip `zoom_target_active = True`; step at dt=1/60 | First frame's smoothed eye close to Tracking pose; after ~70 frames within 1% of ZoomTarget solver eye |
| Z release: reverse converges to Tracking solver eye | symmetric to above | Converges back to Tracking solver eye |

### What's not tested at unit level
- Host-loop key binding wiring (covered by manual playtest).
- The actual `_dauntless_host` keysym values for `KEY_Z`, `KEY_EQUAL`,
  `KEY_MINUS` (verified by smoke run).
- ZoomTarget under simultaneous mode-transition + target-loss races
  (rare; covered structurally by the per-condition tests above).

## References

- Existing implementation:
  [`engine/cameras/tracking.py`](../../../engine/cameras/tracking.py),
  [`engine/cameras/director.py`](../../../engine/cameras/director.py),
  [`engine/host_loop.py`](../../../engine/host_loop.py).
- Tracking-mode-rewrite spec:
  [`2026-06-04-tracking-camera-rework-design.md`](2026-06-04-tracking-camera-rework-design.md).
- BC reference — `Z` / `=` / `−` handlers:
  [`sdk/Build/scripts/TacticalInterfaceHandlers.py`](../../../sdk/Build/scripts/TacticalInterfaceHandlers.py)
  (`Zoom`, `ZoomTarget` functions);
  [`sdk/Build/scripts/CameraModes.py`](../../../sdk/Build/scripts/CameraModes.py)
  (`ZoomTarget` mode constructor with `Distance=4`, `MinimumDistance=4`,
  `MaximumDistance=20`); manual:
  [`docs/original_game_reference/ui/keyboard-mouse-reference.md`](../../original_game_reference/ui/keyboard-mouse-reference.md)
  § Camera Commands — Tactical Mode.
- Rotation-matrix convention: [`CLAUDE.md`](../../../CLAUDE.md)
  § "Rotation matrix convention — column-vector, always".
- Game-unit convention: [`engine/units.py`](../../../engine/units.py),
  [`CLAUDE.md`](../../../CLAUDE.md) § "Game-unit conversion".
