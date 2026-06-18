# In-space cutscene-camera subsystem (v1)

**Date:** 2026-06-18
**Status:** Design approved, pending spec review
**Branch:** `feat/cutscene-camera`
**Follow-up to:** Layer 1 plumbing fix (commit on this branch) and
`project_comm_set_viewscreen` follow-up "E".

## Problem

The SDK's in-space cutscene-camera path
(`sdk/Build/scripts/Actions/CameraScriptActions.py`) lets missions point the
*rendered space view* at a scripted camera: `ChangeRenderedSet` →
`CutsceneCameraBegin` → a camera-mode action (`LockedView`, `ChaseCam`,
`TargetWatch`, …) → `CutsceneCameraEnd`. Each action funnels through
`Camera.NewMode` (`Camera.py:437`), which drives a **CameraMode** object on the
camera: an attribute bag plus a per-frame `Update()` that computes the camera's
world pose from those attributes and the **live** target object's position.

Layer 1 (already fixed on this branch) added `SetMatrixRotation` and
`CameraObjectClass_GetObject`, so `CutsceneCameraBegin/End` now run cleanly and
pose the camera object correctly. But two things are still missing for the shot
to be *visible*:

1. **The camera-mode subsystem is unbuilt.** `GetNamedCameraMode`,
   `PushCameraMode`, `GetCurrentCameraMode`, `pMode.Update()` are all
   `_LoudStub` no-ops, so `Camera.NewMode` returns 0 and no mode is ever pushed.
   BC's CameraMode geometry lived in Appc C++ and has no Python equivalent here.
2. **The engine never renders through a set's active camera in space.**
   `_compute_camera` (`engine/host_loop.py:2214`) always picks the player
   director (Chase/Tracking) or the bridge first-person camera; `GetRenderedSet()`
   feeds only lighting/backdrops (`_resolve_active_set:1769`), never the camera.

Used by warp sequences (`WarpSequence.py`) and Episode 6/7/8 missions
(e.g. E7M2's `Albirea3` beat: `LockedView("Albirea3","player",0,190,10)`).

## Scope

**v1 renders the SPACE/exterior view through the active cutscene camera of the
rendered space set, for three camera modes:**

- `LockedSphericalMode` — `LockedView` / `LockedViewAnyAngle`
  (`LockedSpherical` / `LockedSphericalLookCenter`). The mode E7M2 uses for its
  space beat; primary verification target.
- `ChaseMode` — `ChaseCam` / `ReverseChaseCam` (`Camera.Chase` / `.Reverse`).
- `TargetMode` — `TargetWatch` (`Camera.Target`): look from a source object to a
  target object.

`bSweep` is honored: the camera glides toward the ideal pose (exponential
smoothing over `SWEEP_SECONDS`) when `bSweep=1`, snaps when `bSweep=0`.

### Out of scope (v1)

- **Bridge-set cutscene cameras / `PlacementWatch("bridge", …)`.** These render
  through the first-person bridge camera and overlap the existing
  `BridgeCutsceneController`. When verifying E7M2, the bridge-set watch beats
  behave exactly as they do today; only the `Albirea3` `LockedView` space shot
  changes. This is the intended seam.
- `Placement` / `DropAndWatch` / `WatchWarpPlacement` / `WatchShipLeave`
  (warp-in/out watching) — needs warp-event hooks not yet wired.
- `AddModeHierarchy` fallback tree (modes are flat; no graceful-degrade chain).
- `StartCinematicMode` / cinematic window.
- Sweep easing curves beyond simple exponential smoothing.

## Architecture — three units

### 1. `engine/appc/camera_modes.py` (new)

Pure-Python mode object model. Game units throughout (no `*_m`/`*_mps`).

- **`CameraMode` (base).** Holds an attribute dict; `SetAttrFloat`,
  `SetAttrPoint`, `SetAttrIDObject` (+ matching getters with sane defaults).
  `IsValid()` returns false when the resolved target is `None`/dead.
  `Update(dt) -> (eye, forward, up)` returns the smoothed pose: subclasses
  implement `_ideal(dt) -> (eye, forward, up)`; the base lerps the held current
  pose toward the ideal (snap when the mode was pushed with `bSweep=0`). Eyes are
  `TGPoint3`-or-tuple in world game units; forward/up are unit world vectors.
- **`LockedSphericalMode`.** Reads `Source` (target object), position spherical
  coords (`fDegreesAround`, `fDegreesHeight`, `fDistance`) and optional view
  spherical coords. Ideal pose = target world location + spherical offset
  (`CalcSphericalPosition`, `Camera.py:155`), looking back at the target (or
  along the view spherical for `AnyAngle`), up aligned with model-up
  (`App.TGPoint3_GetModelUp()`).
- **`ChaseMode`.** Reads `Source`; positions behind (or, for reverse, ahead of)
  the target along the target's world-forward (`GetWorldRotation().GetCol(1)`),
  offset up, looking at the target.
- **`TargetMode`.** Reads `Source` + `Target`; eye at source world location,
  forward = normalize(target − source), up from model-up.

Geometry is lifted from `Camera.py`'s `LockedSphericalLookCenter` /
`CalcSphericalPosition` and, where it overlaps, the Tracking director's
two-angle spherical solve (`engine/cameras/`). Constants: `SWEEP_SECONDS`
(~0.8 s), default distances/angles for missing attributes.

### 2. `CameraObjectClass` mode stack (`engine/appc/bridge_set.py`)

Replace the `_LoudStub` no-ops on `CameraObjectClass` with a real mode stack so
`Camera.NewMode` can push live modes:

- `GetNamedCameraMode(name)` — lazily build + cache the named mode
  (`LockedSpherical`, `Chase`, `Target`, plus the aliases `Camera.py` uses);
  return `None` for unknown names so `NewMode` bails cleanly.
- `PushCameraMode(mode)` / `PopCameraMode([mode])` / `GetCurrentCameraMode([i])`
  — a simple list stack; current = top.
- `AddModeHierarchy(child, parent)` — no-op (fallback tree out of scope).
- `GetObjID()` already exists via the object base; `NewMode` compares mode obj
  IDs, so `CameraMode` carries a unique id.

`ZoomCameraObjectClass` (bridge "maincamera") keeps its no-op stack — bridge-set
modes are out of scope for v1.

### 3. Host render-path selection (`engine/host_loop.py`)

- `_active_cutscene_camera(player) -> (camera, mode) | None`: resolve the
  rendered set (`GetRenderedSet()`); if its active camera is a non-default
  cutscene camera with a current mode that `IsValid()`, return them; else `None`.
- In the exterior-view branch (only when `view_mode` is **not** bridge and the
  pause/SPV overlays aren't active), if `_active_cutscene_camera` returns a
  `(camera, mode)`, call `mode.Update(dt)` and feed `(eye, target, up)` + the
  camera's FOV/near/far into the existing `r.set_camera(...)` — the same call the
  director uses. Otherwise fall through to `_compute_camera` unchanged.
- On `CutsceneCameraEnd` (camera deleted) or mode pop, the helper returns `None`
  and the director resumes — clean revert, no held state.

No C++/renderer/shader changes; no rebuild. Pure Python, same render path as the
player director, mirroring the comm-feed and bridge-cutscene per-frame drivers.

## Data flow (E7M2 Albirea3 beat)

```
ChangeRenderedSet("Albirea3")          → MakeRenderedSet stores rendered-set name
CutsceneCameraBegin("Albirea3")        → create CutsceneCam, copy active pose, SetActiveCamera
LockedView("Albirea3","player",0,190,10)
   → Camera.LockedSphericalLookCenter → Camera.NewMode
   → cam.GetNamedCameraMode("LockedSpherical")  (builds live mode)
   → mode.SetAttr* (Source=player, distance=10, around=0, height=190); PushCameraMode(mode)
[each exterior frame] host._active_cutscene_camera:
   rendered set "Albirea3" → active CutsceneCam → current mode valid
   → mode.Update(dt) reads player.GetWorldLocation()/Rotation → (eye,target,up)
   → r.set_camera(eye,target,up,fov,near,far)
CutsceneCameraEnd("Albirea3")          → DeleteCameraFromSet → helper None → director resumes
```

## Error handling

- Target resolves to `None`/dead → `IsValid()` false → host skips, falls back to
  the director (no frozen/black frame). Logged via `dev_mode.log_swallowed`.
- Degenerate geometry (target at eye, zero-length forward) → keep last good pose;
  never emit a NaN camera.
- Missing attributes → sane defaults so a partially-configured mode still poses.
- `App.TGPoint3_GetModelUp()` / model-axis helpers must return real unit vectors
  (BC is Z-up: model-up = (0,0,1)); verify the shim provides them, add if stubbed.

## Testing

- **Unit — `camera_modes`:** LockedView spherical math against a placed target
  (0°/190°/10 → expected eye + look direction); Chase behind/ahead offset;
  Target look-from-source; sweep converges to ideal over time; snap is immediate;
  invalid/dead target → not valid.
- **Unit — `bridge_set` stack:** `GetNamedCameraMode` builds + caches; push / pop
  / current; `Camera.NewMode` end-to-end pushes a live mode and sets attributes.
- **Integration — host-loop selection:** rendered space set + active cutscene
  mode → camera tuple comes from the mode, not the director; `CutsceneCameraEnd`
  reverts to the director; bridge view and pause/SPV overrides unaffected.
- **Live (manual, Mark drives GUI):** load E7M2 via the dev mission picker, reach
  the `Albirea3` `LockedView` beat, confirm the space view locks/orbits on the
  player ship and reverts afterward.

## Files

- `engine/appc/camera_modes.py` — new mode subsystem.
- `engine/appc/bridge_set.py` — real mode stack on `CameraObjectClass`.
- `engine/host_loop.py` — `_active_cutscene_camera` + exterior-branch selection.
- `App.py` — export any new module-up / mode helpers if added.
- `tests/unit/test_camera_modes.py`, `tests/unit/test_cutscene_camera.py`
  (extend), `tests/host/…` integration test.

## Constraints

- Rotation: column-vector, right-handed (`GetCol(1)`=forward, `GetCol(2)`=up).
- Game units throughout; convert only at display boundaries (no `*_m`).
- One build tree; this is pure-Python (no rebuild). Pure shim changes need no
  rebuild.
- SDK-faithful: honor `CutsceneCameraBegin`/`SetActiveCamera`/the camera-mode
  actions; do not hardcode per-mission camera moves.
- TDD for the mode geometry and the host-loop selection.
