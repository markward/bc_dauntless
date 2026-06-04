# Tracking Camera Rework — Design

**Date:** 2026-06-04
**Status:** Design — ready for implementation plan

## Summary

Rewrite the tactical-mode target camera (BC's "Tracking Mode") to match the
framing observed in the original game and to share a clean
mode-dispatch scaffold with future camera modes. Today's implementation
in [`engine/host_loop.py`](../../../engine/host_loop.py)
(`_CameraControl` + `_relocate_eye_for_target_lock`) ships the wrong
framing in two ways: vertical lift is along world-Z (introducing a
preferred orientation a space sim should not have), and the player's
on-screen position drifts with target range. Tracking Mode is the only
behavioural change in this spec; Chase Mode is renamed but unchanged.

## §1 Goals & non-goals

### In scope
- Rewrite Tracking Mode so the player ship sits at screen-Y ≈ −25% and
  the target at ≈ +25% regardless of range, matching the original BC
  framing.
- Camera-up = ship body-up at all times. No world-Z reference anywhere
  in camera math.
- Position spring on eye + rotation spring on camera basis.
- Refactor `_compute_camera` dispatch so additional camera modes plug in
  by adding a class and one enum entry, without touching existing modes.
- Adopt BC's terminology: "Chase Mode" and "Tracking Mode" replace the
  ad-hoc "chase / target lock" naming.

### Out of scope (deferred to follow-up specs)
- Chase Mode behaviour: Shift-mouse rotation, `Z` hold-zoom, `=`/`−`
  sticky zoom, `V` Reverse Chase.
- Cinematic Mode (`F9` + `F1`–`F6`) and its six camera variants.
- Bridge viewscreen camera (separate subsystem).
- New Dauntless-specific modes (scaffold leaves room; modes themselves
  are a later conversation).

## §2 Architecture — mode dispatch

Introduce a `CameraMode` enum and a `_CameraDirector` that owns one
camera per mode:

```python
class CameraMode(Enum):
    CHASE    = "chase"
    TRACKING = "tracking"
    # Future modes: REVERSE_CHASE, CINEMATIC_FLYBY, …
```

`_compute_camera` becomes a thin shim that delegates to the director:

```python
director = _CameraDirector(chase=_ChaseCamera(), tracking=_TrackingCamera())
eye, look_at, up = director.compute(view_mode, player, dt)
```

### Class boundaries

| Class | Responsibility | State |
|---|---|---|
| `_ChaseCamera` | Free-orbit chase. Behaviourally **unchanged** — straight rename of today's `_CameraControl`. | orbit angles, distance, rotation spring |
| `_TrackingCamera` | Two-angle solver, position spring, rotation spring. | smoothed eye, smoothed basis |
| `_CameraDirector` | Mode flag, `C`-key toggle, dispatch, target-loss fallback. | current mode |
| `_BridgeCamera` | Unchanged. | — |

### Key bindings

| Key | Effect |
|---|---|
| `C` | Toggle Chase ↔ Tracking. (Today's `C` resets orbit and disables lock; that becomes "switch mode" instead.) |

Other BC bindings (`V`, `Z`, `Shift`, `=`/`−`, `F9`) are deferred.

### File layout

A new `engine/cameras/` package:

```
engine/cameras/
    __init__.py        # re-exports CameraMode, CameraDirector
    chase.py           # _ChaseCamera (moved from host_loop.py)
    tracking.py        # _TrackingCamera + solver
    director.py        # _CameraDirector
```

`engine/host_loop.py` keeps the dispatch shim only.

## §3 Tracking Mode — geometry

### Inputs each frame

| Symbol | Meaning |
|---|---|
| `S` | Player world position |
| `T` | Target world position |
| `B` | Ship body-up = `player.GetWorldRotation().GetCol(2)` |
| `D_chase` | Desired eye→player distance — use the same value `_ChaseCamera` would use at default orbit so mode switches do not change perceived zoom |
| `y_p` | Desired player screen-Y as a fraction of the half-image — default `−0.25` |
| `y_t` | Desired target screen-Y as a fraction of the half-image — default `+0.25` |

`y_p` and `y_t` are tunable constants at the top of `_TrackingCamera`
so playtest tuning does not require touching the solver body. Inside
the solver they are converted to angles via
`α = atan(y × tan(v_fov / 2))`. `α_p` and `α_t` below refer to those
converted angles.

### Working plane

The solver operates in the 2D plane containing `S`, `T`, and `B`:

```
e1 = (T − S) / |T − S|              # along ship→target axis
e3 = (B − (B·e1) e1).normalised      # body-up, perpendicularised
```

`e3` is the in-plane "up". The returned camera-up is parallel to `e3`,
re-projected perpendicular to the final forward axis. This is how the
"no world-Z" rule is honoured: up comes from the player ship.

### Solver — inscribed-angle construction

Working in `(e1, e3)` with `S = (0, 0)` and `T = (D, 0)`, `D = |T − S|`:

1. **Total angular spread.** β = α_t − α_p. β is the angle ∠SET that
   the camera E must subtend.
2. **Locus arc.** All E with ∠SET = β lie on an arc through S and T.
   Two arcs satisfy the inscribed-angle constraint (one on each side of
   ST). The matching arc is the major arc on the **+e3 side** of ST
   (camera sits *above* the ship→target line in the plane and tilts
   downward to put the target in the upper image-half and the player in
   the lower half — consistent with all reference screenshots). Its
   centre is on the −e3 side at `(D/2, −D/(2 tan β))` with radius
   `r = D / (2 sin β)`.
3. **Chase-distance circle.** E lies on a circle of radius `D_chase`
   around S.
4. **Pick E.** Intersect the two circles. From the up-to-two
   intersection points, select the one with `e3 > 0` (above ST) and
   `e1 ≤ 0` (behind the player). When both criteria match a single
   point, that is E; when they conflict (chase circle too large to land
   above ST at the required β), apply the fallback below.
5. **Fallback — chase-distance unsatisfiable.** When step 4 has no
   above-line behind-player solution, discard the `D_chase` constraint
   and choose E as the closest point on the locus arc to the −e1 axis
   (i.e. the point on the arc directly behind the player). Player is
   still framed at `α_p` and the spread is still β; only the
   eye→player distance relaxes. This case fires for very close targets;
   "pull back as needed" per playtest direction, revisit after.

A closed-form expression for the two intersection points falls out of
standard two-circle intersection and is left to the implementation
plan; the description above pins down the constraints and the
selection rules without prescribing the exact algebra.

### Camera basis from E

- `f̂` (forward) — rotate `(S − E).normalised` by `−α_p` around the e3
  axis. Sign: `α_p < 0` → player below centre → forward tilts slightly
  down past S in the e3 plane.
- `û` (up) — `e3` re-projected perpendicular to `f̂` and normalised.
- `r̂` (right) — `û × f̂`.

`E`, `f̂`, `û` are 3D vectors throughout (built from 3D `S`, `e1`, `e3`).
The returned tuple matches `r.set_camera`:

```python
return eye=E, look_at=E + f̂, up=û
```

### Edge cases

| Condition | Behaviour |
|---|---|
| No target / target is self | Director falls back to Chase; Tracking is not entered |
| `|T − S| < ε` | Same — Chase fallback for that frame |
| `B` parallel to `(T − S)` (target along ship body-up) | `e3` undefined; choose any unit perpendicular to `e1`; spring smoothing carries the camera through the singularity |
| Two-circle intersection empty (target so close `D_chase > 2r`, or both intersections sit below ST) | Per §3 step 5 fallback: discard `D_chase`, place E at the point on the locus arc closest to the −e1 ray. Player still at `α_p`, target still spread by β above |
| β = 0 (`α_t == α_p`) | Configuration error; assert in dev mode. Not reachable with the shipped defaults |

## §4 Springs

Two independent springs, both owned by `_TrackingCamera`. Form (identical to
today's basis spring):

```
α = 1 − exp(−dt / τ)
state ← state + α × (target − state)
```

### Position spring (eye)

- State: `_smoothed_eye: TGPoint3 | None`
- Target: `E_solved` from §3
- τ: **0.25 s** — snappier than rotation; target switches glide and
  small solver jitter is ironed out; longer τ feels sluggish.
- Seeded on first frame and on mode-enter (see §5 — Tracking does not
  glide from the previous Chase pose).
- No renormalisation.

### Rotation spring (basis)

- State: `_smoothed_basis: TGMatrix3 | None`
- Target: `(f̂, û, r̂)` packed as columns per BC's column-vector
  convention.
- τ: **0.50 s** — same as today's [`_CameraControl.SPRING_TAU_S`](../../../engine/host_loop.py),
  preserves the "ship rotates against the camera briefly during a
  manoeuvre, then settles" feel.
- Renormalisation: Gram-Schmidt each frame, forward as primary,
  project up perpendicular, derive right via `forward × up`. Same
  algorithm as [`_CameraControl._advance_smoothing`](../../../engine/host_loop.py).

### Output

`(eye, look_at, up)` is built from the **smoothed** eye and basis:

```python
eye      = _smoothed_eye
forward  = _smoothed_basis.GetCol(1)
up       = _smoothed_basis.GetCol(2)
look_at  = eye + forward
```

`look_at` is one unit ahead — only direction matters to `r.set_camera`.

### `_TrackingCamera.snap()`

Clears both smoothing states. Director calls this on:

- Mission swap (matches today's `_CameraControl.snap()` use).
- Mode transition into Tracking (so the first frame seeds from the
  solver output, not from stale state — see §5).

## §5 Mode transitions

### Chase → Tracking (`C` pressed, valid target)

- Director sets `mode = TRACKING`.
- Director calls `_TrackingCamera.snap()`.
- First Tracking frame: solver runs, springs seed from solver output,
  eye/basis snap directly to the framed pose.

**Net:** instantaneous cut. Rationale: the two poses are geometrically
unrelated (chase pose is wherever the user last orbited to; tracking
pose is determined by the target). A spring glide between them would
sweep through arbitrary intermediate orientations.

### Tracking → Chase

| Trigger | Behaviour |
|---|---|
| `C` pressed | Director sets `mode = CHASE`. `_ChaseCamera` retains its orbit angles / distance from before the lock, so Chase resumes from where it left off. No snap. |
| Target lost (cleared, destroyed, becomes self) | Durable switch to `CHASE`. The player must press `C` again after acquiring a new target. |

The "durable switch on target loss" rule may need revisiting if
playtest shows BC actually auto-resumes Tracking on the next target —
single-line change in the director.

### Mission swap / hard cut

Director's `snap()` propagates to both cameras' `snap()`.

## §6 Testing

Pure unit tests against `_TrackingCamera.compute()`. No renderer, no
host loop, no PyBullet.

### Geometry (single-frame, `dt=None`)

| Test | Setup | Assertion |
|---|---|---|
| Player at desired screen-Y | S, T separated by 20 GU along +x; B = +z; D_chase = 10 GU; defaults | Project S into camera → `screen_y ≈ −0.25` (±1e-3) |
| Target at desired screen-Y | Same | Project T → `screen_y ≈ +0.25` |
| Camera-up matches ship body-up | Ship rolled 45° around forward axis | Returned `up` = projection of `B` perpendicular to `forward`, normalised — **not** world-Z |
| Camera behind player | Standard setup | `(camera − S) · (T − S) < 0`; distance `≈ D_chase` |
| Framing constant across range | Run at `|T−S|` = 5, 50, 500 GU | Screen-Y values identical (±1e-3) — the regression the rewrite exists to fix |
| Player-roll inheritance | Ship rolled 180° | `up` ≈ −world-Z (because body-up flipped); ship still renders right-side-up to camera |

### Edge cases

| Test | Setup | Assertion |
|---|---|---|
| Target = self | Director called | Tracking solver not invoked; Chase output returned |
| `|T−S| < ε` | Tracking entered, then target moved onto player | Director falls back to Chase for that frame |
| Body-up parallel to ship→target | `B = e1` | Solver returns finite, non-NaN output; up is some perpendicular to forward; no crash |
| Two-circle empty (target too close) | `|T−S| < D_chase × sin β` (e.g. `D_chase = 10`, `|T−S| = 1`, default β) | Solver returns locus-arc fallback; player still at `α_p`; spread still β; eye→player distance smaller than `D_chase` |

### Springs

| Test | Setup | Assertion |
|---|---|---|
| Position spring converges | Solver output held constant; 30 frames at dt=1/60, τ=0.25 | `|smoothed_eye − solver_eye| < 1%` of initial error |
| Rotation spring converges | Same with τ=0.50 | Smoothed basis within 1% of solver basis |
| `snap()` clears state | Run a few frames; call `snap()`; one more frame | Returned eye/basis = solver output exactly |
| Springs independent | Move solver eye only → only position lags. Rotate basis only → only rotation lags. | No cross-coupling |

### Director / transitions

| Test | Assertion |
|---|---|
| `C` in Chase with valid target | Mode flips to TRACKING; `_TrackingCamera.snap()` called |
| `C` in Tracking | Mode flips to CHASE; chase's orbit angles preserved |
| `C` in Chase with no target | Mode stays CHASE; no broken state |
| Target lost mid-Tracking | Mode flips durably to CHASE |
| Mission swap | Director's `snap()` propagates to both cameras |

### What's not tested at unit level
- Rendered output — verified by running the build.
- `_BridgeCamera` interaction — separate code path, untouched.
- Cinematic Mode — out of scope.

## References

- Current implementation:
  [`engine/host_loop.py:893`](../../../engine/host_loop.py) (`_CameraControl`),
  [`engine/host_loop.py:1922`](../../../engine/host_loop.py)
  (`_compute_camera`, `_relocate_eye_for_target_lock`).
- BC binding reference:
  [`docs/original_game_reference/ui/keyboard-mouse-reference.md`](../../original_game_reference/ui/keyboard-mouse-reference.md)
  § Camera Commands — Tactical Mode.
- Rotation-matrix convention: [`CLAUDE.md`](../../../CLAUDE.md)
  § "Rotation matrix convention — column-vector, always".
- Game-unit convention: [`engine/units.py`](../../../engine/units.py),
  [`CLAUDE.md`](../../../CLAUDE.md) § "Game-unit conversion".
