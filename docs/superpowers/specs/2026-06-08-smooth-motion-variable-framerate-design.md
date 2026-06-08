# Smooth motion under variable frame rate — design

**Date:** 2026-06-08
**Status:** Approved, ready for implementation plan

## Problem

Players notice visible judder/stutter on both the player ship and AI
ships, even when the render frame rate is high. The simulation runs on a
fixed 60 Hz timestep (`engine/core/loop.py`, `TICK_DELTA = 1/60`) driven
by a Fiedler accumulator (`engine/core/timestep.py:step_accumulator`),
but the render path does not account for the gap between the sim cadence
and the render cadence. Two independent root causes were identified:

1. **Camera spring fed a fixed dt.** The chase/tracking cameras do
   correct frame-rate-independent exponential smoothing
   (`alpha = 1 - exp(-dt / SPRING_TAU_S)`, `engine/cameras/chase.py:180`),
   but `_compute_camera` is invoked with `dt=TICK_DT` (a constant 1/60)
   **every render frame** regardless of the real elapsed time
   (`engine/host_loop.py:2514-2516`). At refresh rates other than 60 Hz
   the camera springs by a fixed per-frame step that does not match the
   player ship's smooth wall-clock motion, so the player ship appears to
   swim/judder inside the frame. This is the same oversight the
   `_apply_input` comment at `host_loop.py:2477` already warns about for
   player input — the camera never received the same treatment.

2. **No render interpolation for AI ships.** AI/non-player ships are
   integrated by `tick_all_ship_motion` on the fixed 60 Hz timestep and
   then their live transform is pushed to the renderer once per frame
   (`host_loop.py:2499-2504`). The leftover `_accumulator` is discarded,
   so AI ships move in discrete 60 Hz world-space jumps and judder
   against a smooth camera.

The player ship's world-space position is already smooth (it is
integrated directly by `_PlayerControl.apply` once per render frame on
wall-clock `_player_dt`, and `tick_all_ship_motion` skips it), so the
player ship needs only the camera fix, not interpolation.

## Scope

In scope:
- Camera smoothing dt correction (player-ship judder).
- Render interpolation for non-player ships (AI-ship judder).

Out of scope (explicitly not changed by this work):
- Player input architecture (`_player_dt` wall-clock integration stays
  as-is — this is the deliberate per-render-frame path).
- Planets / astro bodies, debris, projectiles. The user reports judder
  on ships only; the same mechanism can be extended later if needed.
- The `MAX_FRAME_DT` spiral-of-death cap and dropped-time-on-stall
  behavior — unchanged.
- Renderer / native code. The renderer already accepts a fresh world
  transform per frame, so all changes are Python-side in
  `engine/host_loop.py` plus one new helper module.

## Architecture

Both fixes live in `engine/host_loop.py` plus a new pure helper module
`engine/core/interpolate.py`. No renderer/native changes.

### Component 1 — Camera smoothing dt

Pass the real wall-clock frame delta to the camera instead of the fixed
sim tick:

- Change `_compute_camera(view_mode, director, player=player, dt=TICK_DT)`
  to `dt=_player_dt` (`host_loop.py:2514-2516`).
- `_player_dt` already exists at `host_loop.py:2374`: it is the
  wall-clock frame delta, clamped to `[0, MAX_FRAME_DT]` and forced to
  `0.0` while paused. Feeding it into the camera means the
  `1 - exp(-dt/τ)` springs in `chase.compute_camera` / `tracking.compute`
  converge in correct wall-clock time, and spring behavior on stalls and
  pause is unchanged.
- Bridge view takes the direct, non-springing path in `_compute_camera`
  (`host_loop.py:1798-1804`) and is unaffected by the dt change.

### Component 2 — AI-ship render interpolation

New pure helper `engine/core/interpolate.py`:

- `lerp_transform(prev_loc, prev_rot, cur_loc, cur_rot, alpha)` returns
  an interpolated `(loc, rot)`:
  - Position: component-wise linear interpolation.
  - Rotation: nlerp of the basis columns followed by Gram-Schmidt
    re-orthonormalization, reusing the column-vector convention and the
    same re-orthonormalization approach already in
    `chase._advance_smoothing` (`engine/cameras/chase.py:191-216`):
    keep forward (col 1) as primary, re-derive right (col 0) and up
    (col 2).
- Pure functions, no engine/global state, unit-testable in isolation.

In the host loop, maintain two dicts keyed by render instance id
(`iid`):

- `_prev_xform[iid] = (loc, rot)` — state at the end of the previous
  tick batch.
- `_cur_xform[iid] = (loc, rot)` — state at the end of the current tick
  batch.

Per render frame:

1. Compute `_sim_ticks_this_frame` via the existing accumulator step.
2. If `_sim_ticks_this_frame > 0`: copy `_cur_xform → _prev_xform`, run
   the ticks, then re-capture `_cur_xform` from each non-player ship's
   live `(GetWorldLocation(), GetWorldRotation())`.
3. Compute `alpha = _accumulator / TICK_DT` (in `[0, 1)` after the
   accumulator step).
4. For each non-player ship, push
   `r.set_world_transform(iid, _ship_world_matrix_from(lerp_transform(prev, cur, alpha)))`.
   The matrix is built from the interpolated `(loc, rot)` using the same
   `BC_MODEL_SCALE` / X-axis-flip handling as the existing
   `_ship_world_matrix`.
5. The **player ship** keeps its existing live-transform push
   (`host_loop.py:2501`), excluded from interpolation.

## State lifecycle & edge cases

- **Teleport / mission swap.** The loop already detects swaps via
  `controller._drain_pending_swap()` + `director.snap()`
  (`host_loop.py:2380-2384`). On a swap frame, reset both snapshots to
  live (`_prev = _cur = live`) so the first post-swap frame renders at
  the true position with no lerp across the discontinuity.
- **First frame.** Same reset: seed `_prev = _cur = live` on initial
  loop entry (no prior state to interpolate from).
- **Ship appears.** Unknown `iid` → seed both `_prev` and `_cur` from
  the live transform (renders static-correct for one frame, interpolates
  thereafter).
- **Ship disappears.** Prune `iid`s no longer present in the live
  `session.ship_instances` so the dicts do not leak over a long session.
- **Pause.** `_frame_dt` forced to 0 → 0 ticks, accumulator does not
  grow, `alpha` holds → ships render frozen at the last interpolated
  pose. Matches existing pause behavior.
- **Sub-60 fps.** Accumulator fires multiple ticks per frame; `_prev →
  _cur` still spans exactly the last tick and `alpha` stays in `[0, 1)`.
  Interpolation degrades gracefully (less benefit, no artifacts). The
  `MAX_FRAME_DT` cap is untouched.

## Testing

- **`engine/core/interpolate.py`** (pure unit tests): `alpha=0` returns
  prev; `alpha=1` returns cur; `alpha=0.5` gives midpoint position;
  interpolated rotation stays orthonormal (unit columns, det ≈ +1); a
  known 90° interpolation lands where expected.
- **Snapshot bookkeeping** (extracted into a small testable unit):
  0-tick frame keeps prev/cur unchanged; ≥1-tick frame rotates
  cur→prev and re-captures cur; swap/first-frame resets to live; stale
  `iid`s pruned; new `iid`s seeded.
- **Camera dt**: assert `_compute_camera` receives `_player_dt` (and
  `0.0` while paused), guarding against a regression back to `TICK_DT`.
- **Manual**: run the host loop at an uncapped / high refresh rate and
  eyeball player + AI ship motion — the real acceptance test for judder.

## Notes

- Per the project memory on pytest memory cost, run focused test subsets
  (e.g. the new `interpolate` and host-loop bookkeeping tests) rather
  than the full suite.
- Rotation interpolation must follow the column-vector convention
  documented in `CLAUDE.md` (forward = `GetCol(1)`); the Gram-Schmidt
  step mirrors `chase._advance_smoothing` exactly.
