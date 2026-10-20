# Target Zoom Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exterior Z and the bridge viewscreen frame the whole target at its real (scaled) size, centred on it, never further back than the player, sliding out to the target's surface when the player hugs it.

**Architecture:** A new pure module `engine/cameras/zoom_fit.py` measures the target (oriented hull box, sphere fallback), solves the fit distance for a given FOV + aspect, and combines it with the player cap and surface rule. `_TrackingCamera._compute_zoom_target` (the one solver both views share) calls it. The shared `camera_modes._target_radius` becomes scale-aware. The host feeds the real aspect to both views and gives the viewscreen a persistent distance smoother.

**Tech Stack:** Python 3.11, pytest. No C++ change, no rebuild of shaders.

**Spec:** `docs/superpowers/specs/2026-10-20-target-zoom-fit-design.md` — read it first; rule numbers below (R1–R7) are its §5 rules.

## Global Constraints

- Work in the worktree `.claude/worktrees/target-zoom-fit`, branch `fix/target-zoom-fit`. Before Task 1: `uv sync --extra dev`. If a test import fails on `_dauntless_host`, build per the memory recipe (`cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=$PWD/.venv/bin/python3 -DPython3_ROOT_DIR=~/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none -DPython3_FIND_FRAMEWORK=NEVER -DPython3_FIND_STRATEGY=LOCATION && cmake --build build -j`).
- ⛔ Run ONLY the focused test files named in each task (`uv run pytest <file> -v`). Never a whole suite, never `scripts/check_tests.sh` (CLAUDE.md "Test gate").
- ⛔ No destructive git (`checkout --`, `restore`, `stash`, `clean`, `reset --hard`, `add -A`/`add .`). Stage explicit paths. Commit with `git commit -F <file>`; end messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Game units only (`*_gu`); column-vector rotations: `R.GetCol(0)` right, `GetCol(1)` forward, `GetCol(2)` up; right = forward × up.
- Fit margin `FIT_MARGIN = 0.10` (target spans ≤ 90% of the tighter axis).
- Zoom-key multiple: default/min `1.0`, max `5.0`, step `ZOOM_OUT_FACTOR` / `ZOOM_IN_FACTOR` (from `engine.cameras`).
- Viewscreen distance smoothing tau `0.25` s (= `_TrackingCamera.POS_SPRING_TAU_S`); snap on retarget.
- Viewscreen aspect `640 / 360` (`kViewscreenRttW/H`, `native/src/host/host_bindings.cc:586`).
- `GetRadius()` stays UNSCALED SDK surface — never change what it returns; scale is applied by readers.

## Review Focus

1. Target destroyed while Z is held → the director frames the `_GhostTarget` (no box, no `GetScale`): sphere fallback, no exception. Test in Task 3.
2. A planet (no hull box, huge sphere) with the player in low orbit → eye outside the sphere, never behind the player. Test in Task 2.
3. Player centre exactly at / inside the target's box centre (degenerate direction) → finite eye, no NaN. Test in Task 3.
4. Sim paused (`dt == 0`) on the viewscreen → smoothed distance holds still, does not snap or drift. Test in Task 2.
5. Target with `GetScale()` returning 0, non-finite, or a `TGObject` stub, and a `DebrisChunk` (its radius is already world size) → radius = unscaled / chunk radius, never 0 or ×57. Test in Task 1.

---

### Task 1: Scale-aware camera radius

**Files:**
- Modify: `engine/appc/camera_modes.py:269-281` (`_target_radius`)
- Test: `tests/unit/test_camera_modes.py`

**Interfaces:**
- Produces: `_target_radius(obj, default=1.0) -> float` — the object's DRAWN radius in GU: `rocks.rock.effective_radius(obj)` for a rock (`rocks.rock.is_rock`), else `collisions.world_radius(obj)`; `default` when the object has no real `GetRadius` (keep the existing `implements` check) or the result ≤ 1e-6. Every existing caller (camera_modes `:305 :407 :711 :1026 :1045`, `director.py:251`, `tracking.py:197`) picks it up unchanged.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_camera_modes.py`:
  - `test_target_radius_includes_the_objects_scale`: a ship with `SetRadius(5.0)`, `SetScale(3.0)` → `_target_radius(ship) == pytest.approx(15.0)`.
  - `test_target_radius_of_a_scaled_rock_uses_the_hull_radius_fallback`: a rock (`rocks.rock` `make_rock`/`maybe_become_rock` path) with `GetRadius() == 0`, hull radius 0.8, `SetScale(3.0)` → `== pytest.approx(2.4)`.
  - `test_target_radius_ignores_a_bad_scale`: `SetScale(0.0)` → `== 5.0`; a debris chunk with `radius=0.3, scale=57.0` → `== pytest.approx(0.3)`.
  - `test_zoom_target_mode_stands_off_the_scaled_radius`: extend the existing `test_zoom_target_mode_eye_stands_off_target_by_distance_times_target_radius` pattern with a target at `SetScale(2.0)` → standoff `Distance × 2 × r`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_camera_modes.py -v` — new tests FAIL (radius unscaled).
- [ ] **Step 3: Implement** `_target_radius` as in Interfaces. Import lazily inside the function (camera_modes is imported early). Update its docstring: drawn radius, why (E1M2 `SetScale(3)`), and that BC-scale-inclusion is *inferred* (spec §6).
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_camera_modes.py tests/cameras/test_director.py -v` — all PASS. If an existing test seeded a scaled object and asserted the unscaled standoff, update it to the scaled value and say so in the commit.
- [ ] **Step 5: Commit** `fix(cameras): camera radius includes the object's scale`.

### Task 2: `zoom_fit` — measure, fit, cap, smooth

**Files:**
- Create: `engine/cameras/zoom_fit.py`
- Test: `tests/cameras/test_zoom_fit.py`

**Interfaces:**
- Consumes: `camera_modes._target_radius` (Task 1); `combat._hull_box_for(ship) -> ((cx,cy,cz),(hx,hy,hz)) | None` (body frame, current scale).
- Produces:
  - `FIT_MARGIN: float = 0.10`
  - `@dataclass(frozen=True) class TargetExtent: centre: tuple[float,float,float]; axes: tuple[Vec3, Vec3, Vec3] | None; half: tuple[float,float,float] | None; radius: float` — `axes` = the target's world rotation columns, `half` = box half-extents; both `None` for a sphere; `radius` = `_target_radius(obj)` always (sphere measure / fallback).
  - `target_extent(obj, loc, rot) -> TargetExtent` — `loc`/`rot` are the pose to use (the caller's `pose_of` result). Box when `_hull_box_for(obj)` is not None: `centre = loc + rot·c` (column-vector). Else a sphere at `loc`. Must not raise for objects lacking `_shield_hull_box` (ghost, planet, stub).
  - `fit_distance(ext, forward, up, fov_y_rad, aspect, margin=FIT_MARGIN) -> float` — eye-to-centre distance along `-forward` at which the whole extent fits the frustum shrunk by `k = 1 - margin`. `tan_v = tan(fov_y/2)`, `tan_h = tan_v·aspect`. Sphere: `r / (k·sin(atan(min(tan_v, tan_h))))`. Box: `right = forward × up`; for each of 8 corners `p` with `q = p − centre`, `x=q·right, y=q·up, z=q·forward`: `d ≥ |x|/(k·tan_h) − z` and `d ≥ |y|/(k·tan_v) − z`; return the max over corners (and ≥ 0).
  - `surface_distance(ext, forward) -> float` — distance from `centre` along `-forward` to where that ray leaves the box (slab method on the box axes) or sphere (`radius`).
  - `zoom_target_distance(*, d_fit, zoom, player_dist, r_player, d_surface) -> float` — R4 + R6: `d = min(d_fit·zoom, player_dist − r_player)`; `d = max(d, d_surface)`; `d = min(d, player_dist)`; `max(d, 0.0)`.
  - `class DistanceSmoother: step(key, d: float, dt: float | None) -> float` — exponential approach with tau `0.25`; snaps (returns `d`, stores it) when `key` differs from the last call's or `dt is None`; `dt == 0` returns the held value. `reset()` forgets.

- [ ] **Step 1: Write the failing tests** in `tests/cameras/test_zoom_fit.py`. Helper: project a world point through (eye, forward, up, fov_y, aspect) to NDC. Tests:
  - `test_sphere_fit_puts_the_silhouette_at_ninety_percent`: r=15, fov_y=35°, aspect 16/9 → `fit_distance` = `15/(0.9·sin(17.5°))` (vertical tighter).
  - `test_box_fit_keeps_every_corner_inside_the_margin` — parametrize box half (2.3, 8.0, 0.7) (Galaxy-like) × three orientations (side-on, nose-on, 30° yaw + 20° pitch) × aspect (16/9, 4/3, 640/360): eye `= centre − d·forward`; every corner's |NDC x| and |NDC y| ≤ 0.9 + 1e-6, and at least one == 0.9 ± 1e-6 (tight).
  - `test_box_fit_frames_a_long_hull_tighter_than_its_sphere`: side-on Galaxy box `fit_distance` < sphere fit of the same box's corner radius.
  - `test_surface_distance_box_and_sphere`: axis-aligned box half (5,10,2), forward = +y → 10; sphere r=15 → 15.
  - `test_cap_spills_when_the_player_is_close`: `d_fit=60, zoom=1, player_dist=40, r_player=4, d_surface=15` → 36.
  - `test_surface_wins_over_own_hull_when_hugging`: `d_fit=600, player_dist=130, r_player=4, d_surface=128` → 128.
  - `test_never_behind_the_player_even_inside_the_surface`: `player_dist=100, d_surface=150` → 100.
  - `test_planet_in_low_orbit_keeps_the_eye_outside_the_sphere` (Review Focus 2): sphere r=900, player at 1050 from centre, r_player 4 → result ≥ 900 and ≤ 1050.
  - `test_target_extent_without_a_box_is_a_sphere_at_the_pose`: plain object with `GetRadius()=2`, no `_shield_hull_box` → `axes is None`, `centre == loc`, `radius == 2`.
  - `test_target_extent_box_centre_is_offset_through_the_rotation`: `_shield_hull_box = ((0, 1, 0), (1, 2, 1))`, rot = 90° about z → centre = loc + (−1, 0, 0).
  - `test_smoother_eases_snaps_on_retarget_and_holds_when_paused` (Review Focus 4): step("a", 10, None) == 10; step("a", 20, 0.25) ≈ 10 + 10·(1−e⁻¹); step("a", 20, 0.0) returns the previous value; step("b", 50, 0.1) == 50.
- [ ] **Step 2: Run** `uv run pytest tests/cameras/test_zoom_fit.py -v` — FAIL (module missing).
- [ ] **Step 3: Implement** `engine/cameras/zoom_fit.py` per Interfaces. Plain tuples, `math` only; no `TGPoint3` dependency in the maths (accept anything with `.x .y .z` for `loc`, `rot.GetCol(i)` for `rot`). Module docstring cites the spec and states this is a deliberate BC departure (spec §7).
- [ ] **Step 4: Run** `uv run pytest tests/cameras/test_zoom_fit.py -v` — PASS.
- [ ] **Step 5: Commit** `feat(cameras): zoom_fit — fit-to-frame distance, player cap, surface rule`.

### Task 3: ZoomTarget solver uses the fit

**Files:**
- Modify: `engine/cameras/tracking.py` (constants `:38-48`, `__init__`, `zoom_in/zoom_out/snap`, `compute :155-230`, `_compute_zoom_target :330-363`)
- Test: `tests/cameras/test_tracking_geometry.py` (zoom-target tests `:282-560`), `tests/cameras/test_tracking_zoom.py`, `tests/cameras/test_director.py`

**Interfaces:**
- Consumes: Task 2's `target_extent`, `fit_distance`, `surface_distance`, `zoom_target_distance`, `DistanceSmoother`.
- Produces on `_TrackingCamera`:
  - `aspect: float` (init `16/9`), set by the host each frame (Task 4).
  - `zoom_target_scale: float` replaces `zoom_target_radii`; constants `ZOOM_TARGET_SCALE_DEFAULT = 1.0`, `ZOOM_TARGET_SCALE_MIN = 1.0`, `ZOOM_TARGET_SCALE_MAX = 5.0` replace `ZOOM_TARGET_*_RADII`. Rename every use (`grep -rn "zoom_target_radii\|ZOOM_TARGET_.*_RADII" engine tests`) — `camera_modes.ZOOM_TARGET_DEFAULT_DISTANCE` is the SDK camera mode and is NOT touched.
  - `compute(player, target, dt, aim_point=None, pose_of=None, distance_filter=None)` — `distance_filter(target, d_fit) -> float` is applied to `d_fit·zoom_target_scale` before the cap (R7: smoothing never breaks the cap or surface rule). Only used in ZoomTarget.
- Behaviour when `zoom_target_active`: T = `target_extent(target, *pose).centre` — the `aim_point` is IGNORED (R2); e1 = unit(S → T); up from `_plane_basis` as today; `d = zoom_target_distance(d_fit=filter(fit_distance(ext, e1, e3_perp, self.v_fov_rad, self.aspect)·scale), …, player_dist=|T−S|, r_player=_target_radius(player), d_surface=surface_distance(ext, e1))`; eye = T − d·e1. `fov_scale` is NOT applied in ZoomTarget (spec R3). Tracking (non-Z) path unchanged, still uses `aim_point`.

- [ ] **Step 1: Rewrite the zoom-target tests.** In `test_tracking_geometry.py` replace the BC-standoff tests (`test_zoom_target_eye_on_player_target_axis_at_zoom_radii_from_target`, `…distance_scales_with_the_targets_radius…`, `…pushes_the_eye_clear_of_the_players_own_hull`, `…eye_distance_is_scaled_by_fov_scale`) with:
  - `test_zoom_target_fits_a_scaled_rock_from_far` — target `GetRadius 5, GetScale 3`, player 400 GU away → eye on the S→T axis at `fit_distance` of a 15 GU sphere from T; eye outside the sphere.
  - `test_zoom_target_looks_at_the_box_centre_not_the_aim_point` — `_shield_hull_box` with centre offset; pass an `aim_point` 3 GU off → forward == unit(eye → box centre).
  - `test_zoom_target_never_behind_the_player` — player 30 GU from a r=15 target, r_player 4 → |eye − T| == 26, eye between S and T.
  - `test_zoom_target_ignores_fov_scale` — `fov_scale = 2.0` changes nothing.
  - `test_zoom_target_uses_the_cameras_aspect` — same scene, `aspect` 16/9 vs 0.5 → the narrower aspect gives the larger distance.
  - `test_zoom_target_distance_filter_runs_before_the_cap` — filter `lambda t, d: d * 10` with the player at 30 GU → still 26.
  - `test_zoom_target_player_at_the_target_centre_is_finite` (Review Focus 3) — S == T → eye components finite.
  - Keep `…target_projects_to_screen_centre`, `…inherits_player_roll_into_up`, `…target_without_a_radius_surface_is_framed_at_unit_radius`, `…compute_reads_player_and_target_through_pose_of` — adjust expected distances only.
  In `test_tracking_zoom.py` rename to `zoom_target_scale`, assert seed 1.0, zoom-in at the floor is a no-op, zoom-out ×1.125 per press clamped at 5.0, snap resets to 1.0. In `test_director.py` add `test_zoom_target_on_a_destroyed_target_frames_the_ghost` (Review Focus 1): Z held, target destroyed → `director.compute` returns a finite pose at the ghost's sphere fit.
- [ ] **Step 2: Run** `uv run pytest tests/cameras/test_tracking_geometry.py tests/cameras/test_tracking_zoom.py tests/cameras/test_director.py -v` — new tests FAIL.
- [ ] **Step 3: Implement** per Interfaces. Replace `_compute_zoom_target`'s docstring: the fit/cap/surface rule, the spec path, and "deliberately replaces BC's `Distance × r_target` standoff (`0x00423E20`) and own-hull push-out (`FUN_0041FF50`)". Update the class constants' comment the same way.
- [ ] **Step 4: Run** the Step 2 command, plus `uv run pytest tests/host/test_viewscreen_scene_feed.py -v` — all PASS (fix expected distances there only if they asserted the old 4×r).
- [ ] **Step 5: Commit** `fix(cameras): Z zoom fits the whole target, capped at the player`.

### Task 4: Host wiring — real aspect, viewscreen smoothing

**Files:**
- Modify: `engine/cameras/director.py` (add `set_aspect`), `engine/host_loop.py` (exterior wrapper `~8235-8251`; `VS_*` constants `:8276`; `_viewscreen_scene_feed :8280`; its call site `:12961`)
- Test: `tests/host/test_viewscreen_scene_feed.py`, `tests/cameras/test_director.py`

**Interfaces:**
- Consumes: `_TrackingCamera.aspect`, `compute(..., distance_filter=)` (Task 3); `DistanceSmoother` (Task 2).
- Produces:
  - `_CameraDirector.set_aspect(aspect: float) -> None` — sets `self.tracking.aspect`; ignores non-finite or ≤ 0.
  - Exterior: the wrapper calls `director.set_aspect(fb_w / fb_h)` from `host_io.framebuffer_size()` each frame before `director.compute` (skip when `fb_h <= 0`).
  - `VS_ASPECT: float = 640.0 / 360.0` beside `VS_NEAR` — comment: keep in step with `kViewscreenRttW/H` in `host_bindings.cc`.
  - `_VS_ZOOM_SMOOTHER = zoom_fit.DistanceSmoother()` module-level; `reset()` wherever the module's per-mission viewscreen state is cleared on mission swap (find `_vs_last_player_target` resets; if none, reset when `_viewscreen_scene_feed` returns None).
  - `_viewscreen_scene_feed(player, forward_fov, dt=None)` — sets `tc.v_fov_rad = forward_fov`, `tc.aspect = VS_ASPECT`, passes `distance_filter=lambda t, d: _VS_ZOOM_SMOOTHER.step(id(t), d, dt)`. The call site passes `_player_dt` (frozen under pause). Still rigid (`dt=None` to `compute`).

- [ ] **Step 1: Write the failing tests:**
  - `test_director.py::test_set_aspect_reaches_the_tracking_solver_and_rejects_junk` — 2.0 sets it; 0, -1, `float("nan")` leave it.
  - `test_viewscreen_scene_feed.py::test_feed_uses_the_viewscreen_aspect` — monkeypatch `_TrackingCamera.compute` to capture `self.aspect` → `== pytest.approx(640/360)`.
  - `…::test_feed_distance_eases_between_frames_and_snaps_on_retarget` — call the feed twice with `dt=0.25` while the target's radius jumps 2 → 4: the second eye-to-target distance lies strictly between the two fits; retarget to another ship → exact fit.
  - `…::test_feed_holds_distance_when_paused` — `dt=0.0` second call with a changed radius → same distance as the first.
  - Update `test_eye_is_behind_target_not_at_player` if it pinned 4×r.
- [ ] **Step 2: Run** `uv run pytest tests/host/test_viewscreen_scene_feed.py tests/cameras/test_director.py -v` — new tests FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** the Step 2 command plus `uv run pytest tests/unit/test_viewscreen_zoom_target_mode.py tests/host/test_comm_viewscreen_feed.py -v` — PASS.
- [ ] **Step 5: Commit** `fix(viewscreen): target feed fits at the viewscreen's aspect, smoothed distance`.

### Task 5: E1M2 headless end-to-end + docs

**Files:**
- Create: `tests/integration/test_e1m2_target_zoom_fit.py`
- Modify: `docs/superpowers/specs/2026-10-20-target-zoom-fit-design.md` (status line), `CLAUDE.md` (one row — see Step 5)

**Interfaces:**
- Consumes: `_viewscreen_scene_feed` (Task 4), `tests.integration.test_sdk_bridge_load._fresh_world`, `host_loop._init_mission("Maelstrom.Episode1.E1M2.E1M2")` (pattern: `tests/integration/test_e1m2_scan_area.py`).

- [ ] **Step 1: Write the test** `test_viewscreen_frames_each_e1m2_debris_rock_from_the_start`: init E1M2; if `Debris1..6` are not in set `Vesuvi6` after init, call `mod.CreateDebris()`; assert each has `GetScale() == 3`. Wire a player camera as in `tests/host/test_viewscreen_scene_feed.py`'s `wired` fixture. For each rock: `player.SetTarget(rock)`, call the feed (`dt=None`), then assert (a) `|eye − rock centre| ≥ _target_radius(rock)` (outside), (b) `|eye − rock| ≤ |player − rock|` (not behind the player), (c) when `|player − rock| − r_player ≥ fit`, the rock's sphere projects within ±0.9 NDC at `VS_ASPECT`. Also assert `Debris4`'s radius ≈ 15 GU (5 × 3).
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_e1m2_target_zoom_fit.py -v` — PASS on the branch. Prove it bites: back up `engine/appc/camera_modes.py` with `cp`, revert `_target_radius` to the unscaled read, run, see (a) or the radius assert FAIL, restore with `cp`, `diff` byte-identical.
- [ ] **Step 3: Commit** `test(cameras): E1M2 debris rocks fit the viewscreen from the start`.
- [ ] **Step 4: Spec status** — change the spec header to `built on fix/target-zoom-fit, not live-verified`.
- [ ] **Step 5: CLAUDE.md row** — add one table row "Target zoom fit (Z + viewscreen)" pointing at `engine/cameras/zoom_fit.py`, `tracking.py:_compute_zoom_target`, the spec; one-line rule: fit the scaled hull box at the rendered FOV + aspect, never behind the player, surface beats own hull, viewscreen distance smoothed; ⚠️ deliberate BC departure; ⚠️ not live-verified. Commit `docs: target zoom fit`.

Live check (Mark, not a task): the spec's §9 list.
