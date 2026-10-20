# Target zoom that fits the target — design

**Date:** 2026-10-20 · **Branch:** `fix/target-zoom-fit` (worktree `.claude/worktrees/target-zoom-fit`) · **Status:** design, approved in conversation, not built

## 1. Intent

Pressing **Z** in the exterior view, and the **bridge viewscreen** whenever a
target is selected, must show the **whole target, edge to edge** — top, bottom,
left and right inside the frame — from a shuttle to a starbase.

Today big objects swallow the camera: it ends up on or inside the target and
the screen shows bare rock or nothing. On the viewscreen that is worse, because
nothing there tells the player what they are looking at. The six asteroids at
the start of E1M2 are the reference case; the biggest one (`Debris4`) shows the
problem best.

## 2. What exists today (verified 2026-10-20)

Both views use **one solver**: `_TrackingCamera._compute_zoom_target`
(`engine/cameras/tracking.py:330`).

- **Exterior Z** — held key, `host_loop.py:12009` → `director.start_zoom_target`
  / `end_zoom_target`; the director's `_TrackingCamera` runs with springs.
  `=`/`-` step `zoom_target_radii` between `ZOOM_TARGET_MIN_RADII` (4) and
  `ZOOM_TARGET_MAX_RADII` (20).
- **Viewscreen** — `_viewscreen_scene_feed` (`host_loop.py:8280`) builds a
  fresh `_TrackingCamera` every frame, enters ZoomTarget, computes rigidly
  (`dt=None`), passes `director.fov_y_rad` as the FOV. It never sets
  `fov_scale` (stays 1.0). The RTT is 640×360 (`kViewscreenRttW/H`,
  `host_bindings.cc:586`), i.e. 16:9.

The solver places the eye at `T − zoom_target_radii · r_target · fov_scale · e1`
(T = aim point, e1 = unit player→T), looking along e1, then applies an own-hull
push-out: if the eye is less than `r_player` ahead of the player's centre along
e1, it is moved **forward** by the deficit.

### Causes

1. **The radius ignores scale.** `r_target` comes from
   `camera_modes._target_radius` = `GetRadius()`, which in this engine is the
   **unscaled** model radius (`_seed_ship_radius`, `host_loop.py:6251`;
   collisions multiply by `GetScale()` themselves). E1M2's `CreateDebris`
   calls `SetScale(3)` on all six rocks (SDK `E1M2.py:1110`). `Debris4` is
   `Asteroid3`, stock radius 5 GU, so ~15 GU real, but the camera parks at
   4 × 5 = 20 GU from its centre: the rock covers roughly three screens.
   E1M2's later rocks are scaled 3.7–8.5× (`engine/rocks/rock.py:effective_radius`
   docstring), which puts the eye **inside** them. The rock code already has
   the right measure (`effective_radius` = base × `GetScale()`); the camera
   does not use it.
2. **The push-out goes the wrong way for big targets.** When the player is
   nearer the target than the standoff, the eye is pushed toward the target.
   Beside a starbase that pushes it into the station.
3. **The standoff is a fixed multiple.** 4 × r is BC's number
   (`ZoomTargetCameraMode::GetIdealPosition`) and is not tied to the actual FOV
   or the screen's shape. A sphere of radius r needs d ≥ r / sin(fov/2); at
   35° vertical that is 3.3 r, so 4 r only works when r is right — and a
   bounding **sphere** frames a 4–8:1 hull (a Galaxy) small in the middle.
4. **Look-at is the subsystem aim point** (`target_aim_point`), so targeting a
   subsystem moves the framing off the object.

## 3. Goals

- G1. Exterior Z and the viewscreen frame the target's **full real extent**
  (scale included) inside the view, with a small margin.
- G2. One rule, one solver, shared by both views.
- G3. The camera is **never further from the target than the player's ship**.
- G4. The shot is centred on the **target object**, even when a subsystem is
  targeted.

## 4. Non-goals

- Any viewscreen overlay (reticle, target name, info). Mark: "we'll sort that
  afterwards" — a separate follow-up.
- Widening the lens to fit when close. Mark chose **spill** (§5 rule 4).
- Retuning the ordinary Chase / Tracking framing beyond what the radius fix
  (§6) changes.

## 5. The rule (decided with Mark)

For the current target, every frame:

1. **Real size.** Measure the target at its real, scaled size.
   *Claude's call:* use the target's **oriented hull box**
   (`combat._hull_box_for(ship)` — body-frame centre + half-extents at the
   current `GetScale()`, cached at realize for every realized ship) so a long
   hull fills the frame. Fall back to a sphere of `GetRadius() × GetScale()`
   (rocks: `rocks.rock.effective_radius`) when no box is cached.
2. **Direction and look-at.** View from the player's side along e1 = unit
   (player centre → target **box centre** in world space), looking at the box
   centre. Not the subsystem aim point (Mark: "it should stay on the target");
   not the model origin, which sits off-centre on some hulls (Sovereign,
   Keldon). The reticle still marks the subsystem as it does today.
3. **Fit distance.** Move the eye back along −e1 to the smallest distance
   `d_fit` at which every point of the target's extent lies inside the view
   frustum shrunk by the margin. The **tighter screen axis decides**: use the
   real vertical FOV and the real aspect of the surface being drawn (exterior
   window; viewscreen 640×360). *Claude's call:* margin ≈ 10% (the target
   spans at most ~90% of the tighter axis); make it one named constant.
   *Claude's call:* the fit uses the FOV actually rendered, so the
   `fov_distance_scale` compensation is **not** applied on top of it (the fit
   already accounts for the FOV).
4. **Cap at the player.** The eye may be no further from the box centre than
   the point just ahead of the player's own hull: `d_cap = D − r_player`,
   where D = |player centre → box centre| and `r_player` is the player's real
   (scaled) radius, as in today's push-out. Use `d = min(d_fit × zoom, d_cap)`.
   If `d_cap < d_fit`, the target **spills** off the edges; the lens stays
   normal. Never move the eye behind the player; never push it toward the target
   beyond `d_cap`.
5. **Zoom keys** (exterior only; *Claude's call, matching BC's "the seed sits on
   the floor"*): `zoom_target_radii` becomes a multiple of `d_fit`, default and
   minimum 1.0 (zoom-in from the fitted shot is a no-op), `-` steps out by
   `ZOOM_OUT_FACTOR` up to 5.0 (= today's 20/4 ratio), `=` steps back. Still
   capped by rule 4. The viewscreen always uses 1.0 (it builds a fresh camera
   each frame).

6. **Surface wins over own hull** (Mark, 2026-10-20). `r_player` is
   generous (a Galaxy's `GetRadius()` ≈ 4 GU against a 0.7 GU half-height), so
   when the player hugs a big target — parked against a starbase wall, in or
   leaving its bay (`hull_bounds.py`: ~125 GU from centre, inside a 150 GU
   bound) — the rule-4 point can already be inside the target. Then the eye
   slides back toward the player until it is **outside the target's surface**,
   even though that puts it inside the player's own `r_player` reach. It still
   never goes behind the player's centre (G3). If even the player's centre is
   inside the target's surface measure, take the player's centre and accept the
   shot. *Claude's call:* "surface" = the target's oriented box (rule 1's
   measure, sphere fallback), not a mesh trace — cheap, headless-testable;
   upgrading to `ray_trace_mesh` on the targeted hull is a later option if the
   box proves too loose live.
7. **Smoothed distance** (Mark, 2026-10-20). The fitted distance changes as a
   long hull turns side-on → nose-on; that is accepted. Exterior Z smooths it
   through its existing spring. The viewscreen gains the same smoothing **on
   the camera distance only** (direction and look-at stay rigid, so the lock
   still reads clean), which needs per-target state that survives across
   frames — today it builds a fresh camera each frame. Snap (no smoothing) on
   retarget so a new target doesn't swoop in. *Claude's call:* time constant
   ≈ the exterior position spring's (0.25 s).

### Edge cases (builder's call, keep simple)

- Player overlapping the target: rule 6's last sentence. This is a collision
  state anyway.
- Degenerate e1 (player at the box centre): reuse `_plane_basis`'s fallback.
- No box and no radius: today's `default=1.0` behaviour.

## 6. The radius fix (shared)

`camera_modes._target_radius` returns the **scaled** radius (`GetRadius() ×
GetScale()`, with the rock hull-radius fallback that `effective_radius` uses).
That changes every caller, not just ZoomTarget: `ChaseMode` (`camera_modes.py:305`),
`:407`, `:711`, `:1026`, `:1045`, and the director's ghost target
(`director.py:251`). For unscaled objects (scale 1, almost everything) nothing
changes; scaled objects get framed at their real size in every mode.
*Claude's call*, with an evidence caveat: Gamebryo world-bound radii include
scale, so BC's `GetRadius` probably did too — **inferred, not verified** (the
`stbc-reference` server was down when this was written). If that check later
says BC's camera modes used the unscaled radius, keep the scaled radius in
ZoomTarget only and revert the shared helper.

## 7. Departures from BC

The fit-to-frame distance (rule 3), box-centred look-at (rule 2) and the
player cap (rule 4) **replace** BC's `Distance × r_target` standoff and its
own-hull push-out for ZoomTarget. That is deliberate; record it in the
solver's docstring, which today cites the BC addresses as the authority.

## 8. Anti-goals (a failure even if the tests pass)

- The eye inside the target while the player's centre is outside it (rule 6).
- The eye behind the player (further from the target than the player).
- The lens narrowing (it blurred the sky cubemap last time — see
  `project_viewscreen_zoom_target` memory) or widening.
- The viewscreen and exterior Z disagreeing about framing.

## 9. Verification

- **Focused unit tests** on the solver (no full suites, no gate — see
  CLAUDE.md "Test gate"): a scaled rock fits; every box corner lands inside the
  margin frustum for several orientations and both aspects (window, 16:9
  viewscreen); the cap holds and spill happens when the player is close; the
  look-at is the box centre when a subsystem is targeted; zoom keys clamp; a
  player hugging a big box gets an eye outside the box and not behind its own
  centre (rule 6); the viewscreen distance eases between two orientations and
  snaps on retarget (rule 7).
- **Headless check, recommended:** load E1M2 in the mission harness, take the
  player's start pose, and assert the viewscreen feed's eye is outside each of
  the six `Debris*` rocks with every box corner in frame.
- **Live check by Mark** (in the main checkout or this worktree, per his call):
  E1M2 start, target each of the six rocks, look at the viewscreen and hold Z;
  Starbase 12 from far and from beside it (expect spill, camera never behind
  the ship); hugging Starbase 12 and leaving its bay (expect the station's
  surface, never its inside); a Galaxy side-on and nose-on, and circling one
  (the viewscreen distance eases, no jitter); a small object (CommLight or a
  shuttle).

Note for the headless tests: the hull box is cached only by the live
renderer at realize (`_cache_shield_hull_box`), so tests of the box path need
real AABB fixtures set on the ship.

## 10. Left to the builder

The closed-form fit (per-corner: in camera axes, a corner at lateral offset x
and depth z relative to the centre needs d ≥ |x| / (k · tan(half-fov)) − z;
take the max over corners and both axes, k = 1 − margin), how the aspect
reaches the solver, how the exterior effective FOV (speed boost included) is
plumbed, test names and file layout.
