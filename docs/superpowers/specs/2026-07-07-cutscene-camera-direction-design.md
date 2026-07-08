# Cutscene camera-direction system

**Date:** 2026-07-07
**Status:** Design approved; ready for planning
**Canonical live-verify:** E1M1 "leaving drydock" undock shot
(`E1M1.py:2524-2548`)

## Problem

Mission scripts aim the exterior/cinematic camera during in-space cutscenes
through `Actions/CameraScriptActions.py`:

```
CutsceneCameraBegin(set) → ChangeRenderedSet(set) →
  PlacementWatch / PlacementOffsetWatch / LockedView / ChaseCam / TargetWatch →
CutsceneCameraEnd(set)
```

These route through `Camera.py` (`Camera.Placement`, `Camera.NewMode`, …) which
call `pCamera.GetNamedCameraMode(kind)` + `SetAttr*` + `pCamera.PushCameraMode()`.
Today the *cinematic* modes never take effect, so the camera never leaves the
bridge. The canonical case — the Enterprise pulling out of spacedock from the
"Cam Pos 1" placement while Picard speaks — shows the bridge the whole time.

### Verified root causes

1. **`Placement`/`ZoomTarget` modes don't exist.** `CameraObjectClass._MODE_FACTORY`
   (`engine/appc/bridge_set.py`) has only `Locked`/`Chase`/`ReverseChase`/`Target`.
   `GetNamedCameraMode("Placement")` returns `None`, so `Camera.NewMode` silently
   fails and no mode is pushed. (`CameraMode_Create` also ignores its `kind` arg
   — Gap 1 — but that is a *different* path: the drydock `CutsceneCam` is a
   `CameraObjectClass` built by `CameraObjectClass_Create`, so it uses
   `_MODE_FACTORY`, not `CameraMode_Create`.)

2. **The cutscene camera is never consulted while the bridge flag is set.**
   `host_loop._active_cutscene_camera()` is read only inside the
   `not view_mode.is_bridge` branch. `ChangeRenderedSet(space_set)` calls only
   `MakeRenderedSet` — it does **not** flip the view to exterior — so during the
   drydock shot the player is "on the bridge" in state (`bridge_flag()==True`)
   and the cutscene camera is skipped.

3. **`_target_alive` reads waypoints as dead.** `getattr(waypoint, "IsDying")`
   returns a truthy `_Stub` (TGObject's catch-all `__getattr__`, `engine/core/ids.py`).
   The current `not (callable(is_dying) and is_dying())` then evaluates
   `not (True and truthy)` → `False`. A `PlacementMode` whose Source is a
   waypoint ("Cam Pos 1" is `Waypoint_Create`d in `Dock_P.py`) would be invalid
   forever.

4. **Latent seam bug in the merged in-space controller (365207f7, never
   live-verified).** `CameraMode.Update()` returns `(eye, fwd, up)` where the 2nd
   element is a forward *direction*. `host_loop.py:5946` feeds it straight to
   `r.set_camera` as a look-at *point*. `_compute_camera` and `director.compute`
   both return look-at *points*, so Chase/Locked/Target modes currently look at
   ≈origin. This is exercised for the first time by this work.

## The architectural answer (user-confirmed)

**An active cutscene camera on the explicitly-rendered set overrides the bridge
*render*, driven purely by `get_explicit_rendered_set()` + a live-valid-mode
predicate. The `bridge_flag()` source of truth is never mutated.**

Two queries answer two different questions and never fight:

- `get_explicit_rendered_set()` — the render-target authority (what
  `MakeRenderedSet` last set). During the drydock shot this is `DryDock`.
- `GetRenderedSet()` — stays **bridge-wins** for SDK queries (E1M1's
  `str(pBridgeSet) != str(pRenderedSet)` comparisons and
  `MissionLib.EndCutscene`'s restore conditional keep working verbatim).

One per-frame predicate, `cutscene_exterior_active = _active_cutscene_camera() is
not None`, feeds the render decisions. It is naturally false during normal bridge
play (the bridge maincamera's only mode is the `PlaceByDirection` attr-bag,
`IsValid()==0`) and during normal flight (no pushed mode), so nothing changes
outside a scripted in-space cutscene.

**Why this differs from the abandoned `622be12f`.** That commit kept the bridge
pass *on* and moved the first-person bridge camera to the placement — which for a
*space* set renders bridge-interior geometry from a drydock waypoint (wrong scene
entirely). It was also push-based (per-mission listener wiring), the failure mode
the merged pull-model already retired. This design turns the bridge pass *off*
and lets the always-rendered main scene show through — the correct surface — with
no listeners and no mission-load wiring.

### Scope

- **In:** `Placement` + `ZoomTarget` camera modes; the full-screen
  cutscene-camera render override; `CameraMode_Create` kind-dispatch (Gap 1);
  `_target_alive` waypoint fix; the `Update()` direction→point seam fix;
  `PopCameraMode` string-name matching; `PlacementOffsetWatch`'s
  `TargetOffsetWorld`.
- **Out (follow-up spec):** `ViewscreenZoomTarget`. It is a different render
  surface — the bridge **viewscreen RTT** showing a zoomed *exterior* view of the
  player's target while the bridge stays visible around it. The RTT today renders
  only tagged **comm sets** (`set_viewscreen_comm_source` takes a `set_id`); there
  is no path to render the live exterior scene into it. That needs a native
  renderer capability + a `dauntless` rebuild, is not exercised by the drydock
  test, and shares almost no code with the modes above. It gets its own spec and
  its own live-verify (an E-series viewscreen zoom).

## Design

### 1. New camera modes — `engine/appc/camera_modes.py`

Both follow the existing `CameraMode` contract: an attribute bag filled by
`Camera.NewMode` via `SetAttrIDObject`/`SetAttrPoint`/`SetAttrFloat`, and an
`_ideal()` that computes `(eye, fwd, up)` from the **live** object transforms
every frame. `fwd`/`up` are unit vectors; game units; column-vector right-handed
convention (CLAUDE.md).

**`PlacementMode`** — BC's `PlacementWatch` (`Camera.LowPlacementWatch` →
`NewMode("Placement", [("Source", pPlacement), ("Target", pTarget)])`;
`PlacementOffsetWatch` adds `("TargetOffsetWorld", vOffset)`):

- `Source` = a `Waypoint`/`PlacementObject`/`ObjectClass`. Eye = Source world
  location; up = Source rotation col2 (its authored up).
- `Target` set → look at `target_world_loc + TargetOffsetWorld` (offset defaults
  to zero when the attr is absent).
- `Target` `None` (legal — `Camera.Placement`'s `sTarget=None` branch still calls
  `SetAttrIDObject("Target", None)`) → look along the Source's own forward (col1).
- Invalid (`_ideal()` → `None`) if Source dead, or Target set but dead.

**`ZoomTargetMode`** — BC's `ZoomTarget` (`Camera.LowZoomTarget` →
`NewMode("ZoomTarget", [("Source", pSource), ("Target", pTarget)])`):

- Eye at `Source` world location, looking at `Target`; up from Source col2.
- `Source` unset/`None` → fall back to the **owning camera's** pose
  (`self._owner_camera` `GetWorldLocation`/`GetWorldRotation`) — "zoom from the
  current viewpoint toward the target". `MakePlayerCamera_PlayerChanged` (which
  would wire `Source=player`) never runs in our shim, so this fallback is the
  live path for a player-camera zoom.
- Invalid if Target dead; if `Source` was set but died; or if the owner-camera
  fallback can't resolve a pose.

**`_target_alive` fix** — after fetching `IsDying`, treat a `_Stub` result (from
`engine.core.ids`) or any non-bool as **alive** (waypoints/placements never die;
they are the Source of every placement shot). Objects that implement a real
`IsDying()` returning a bool keep their current semantics.

**Base `CameraMode`** gains `self._owner_camera = None`, set by the camera when
the mode is created (below).

### 2. Mode wiring — `engine/appc/bridge_set.py` (`CameraObjectClass`)

- `_MODE_FACTORY` gains:
  - `"Placement": ("PlacementMode", {})`
  - `"ZoomTarget": ("ZoomTargetMode", {})`
- `GetNamedCameraMode(name)` tags the freshly-built mode with
  `mode._owner_camera = self` before caching/returning it (so `ZoomTargetMode`'s
  fallback can read the camera pose).
- `PopCameraMode(mode=None)` also accepts a **mode-name string** (`Camera.LowPop`
  → `pCamera.PopCameraMode(sMode)` passes a string): when `mode` is a string,
  pop the top-most stack entry whose `_named_modes` key matches. Existing
  mode-object and `None` (pop-top) behaviours are unchanged.

### 3. `CameraMode_Create` kind-dispatch — `engine/appc/camera_modes.py` (Gap 1)

Dispatch on `kind`:

| `kind` | class |
|---|---|
| `"Locked"` | `LockedMode` |
| `"Chase"` | `ChaseMode` |
| `"ReverseChase"` | `ChaseMode(reverse=True)` |
| `"Target"` | `TargetMode` |
| `"Placement"` | `PlacementMode` |
| `"ZoomTarget"` | `ZoomTargetMode` |
| `"PlaceByDirection"` / anything else | `PlaceByDirectionMode(kind)` |

The default branch preserves the bridge-captain path (`GalaxyBridgeCaptain` /
`MakePlayerCamera`'s `InvalidX` modes) byte-for-byte. This is a correctness
cleanup; the drydock path does not depend on it (it uses `_MODE_FACTORY`).

### 4. Render-target override — `engine/host_loop.py`

**Predicate (once per tick, when not paused):**
`_cc = _active_cutscene_camera()`. Move this read **out** of the
`not view_mode.is_bridge` gate so it is consulted regardless of the bridge flag.
`_active_cutscene_camera()` already keys off `get_explicit_rendered_set()` and
gates on a live `IsValid()` mode — no change to that function.

**Camera pose:** new helper `_cutscene_pose(mode, dt) -> (eye, look_at, up)`
returning `look_at = (eye[0]+fwd[0], …)` from `mode.Update(dt)`'s `(eye, fwd,
up)`. When `_cc` is live, this overrides the main-scene `eye, target, up_vec`
that feed `r.set_camera`. This is the single site that fixes the direction→point
seam (root cause 4); the old inline `eye, target, up_vec = _cc[1].Update(...)` at
~5946 is replaced by this helper.

**Bridge pass:** `effective_bridge = view_mode.is_bridge and _cc is None`. A
dedicated per-frame driver (its own latch, mirroring
`_apply_view_mode_side_effects`'s idempotence) calls
`bridge_pass_set_enabled(effective_bridge)`. When `_cc` is live the bridge pass
turns **off**; the main scene (always rendered, camera set from the cutscene pose)
shows through. The exterior scene's ship/light scoping already keys off the
explicit rendered set / player's containing set (`_resolve_active_set`,
`iter_active_ships`), and the player ship is in the `DryDock` set during the shot,
so the correct ships render with no further change.

**Deliberately unchanged:**

- `bridge_flag()` — never written by this system.
- `GetRenderedSet()` — stays bridge-wins for SDK queries.
- Cursor lock, engine-rumble mute, bridge ambient hum — stay keyed on the raw
  `is_bridge` (the player is on the bridge in state; only what they *see*
  changes).
- The bridge **sim** block (`cutscene.update`, `char_anim`, `lip_runtime`,
  `idle_gestures`, `node_anim`) stays gated on `is_bridge` and keeps running —
  Picard's "leaving drydock" VO + lip-sync play (invisibly) over the exterior.
  Only `set_bridge_camera`/the bridge render is dark (harmless: bridge pass off).
- Tactical HUD + target reticle — already key off `view_mode.is_exterior`, which
  stays `False`, so they remain hidden (correct cinematic frame).
- Letterbox — continues to follow `TopWindow.IsCutsceneMode()` as today
  (unchanged; the drydock sequence does not enter MissionLib cutscene mode, so no
  bars — SDK-faithful).

**Auto-revert:** `CutsceneCameraEnd("DryDock")` deletes the `CutsceneCam`
(`DeleteCameraFromSet`) → the set has no active camera → `_cc` is `None`;
`ChangeRenderedSet("bridge")` → `MakeRenderedSet("bridge")` + `ForceBridgeVisible`
→ `effective_bridge` True → bridge pass re-enables. No teardown code of our own.

### 5. Testing

**Unit — `tests/unit/test_camera_modes.py` (+ new cases):**
- `PlacementMode._ideal`: eye at Source loc, up = Source col2; Target set → looks
  at target; `TargetOffsetWorld` shifts the look-at; Target `None` → looks along
  Source col1; invalid when Source dead / Target-set-but-dead.
- `ZoomTargetMode._ideal`: eye at Source, looks at Target; `Source=None` → owner
  camera pose; invalid on dead Target / dead-set Source / unresolvable owner.
- `_target_alive`: a bare `Waypoint` reads **alive**; a real `IsDying()==1` reads
  dead; `IsDying()==0` reads alive.
- `CameraMode_Create`: each `kind` string → the right class; unknown → `PlaceByDirectionMode`.

**Unit — `tests/unit/test_camera_mode_stack.py` (+ cases):**
- `_MODE_FACTORY` builds `Placement`/`ZoomTarget`; `GetNamedCameraMode` sets
  `_owner_camera`.
- `PopCameraMode("Placement")` pops the named mode; object/None paths unchanged.

**Host — `tests/host/` (drydock choreography, new or extend
`test_bridge_mode_camera.py`):**
- Build a `DryDock` space set with a player ship + a "Cam Pos 1" waypoint; run
  `CutsceneCameraBegin` → `ChangeRenderedSet("DryDock")` → `PlacementWatch("DryDock",
  "player", "Cam Pos 1")`. Assert `_active_cutscene_camera()` returns a valid
  mode; the computed pose eye ≈ waypoint loc and look-at points at the player;
  `effective_bridge` is `False`.
- Then `CutsceneCameraEnd("DryDock")` + `ChangeRenderedSet("bridge")` → `_cc` is
  `None`, `effective_bridge` `True`.
- Assert `bridge_flag()` is **never** mutated across the whole sequence.

**Regression:** the `_cutscene_pose` fix is covered by a Chase/Target case
asserting the look-at is `eye + fwd` (a far-from-origin chase looks at the ship,
not ≈origin).

**Gate:** `scripts/check_tests.sh` green (pytest + ctest, diffed against
`tests/known_failures.txt`). Then live-verify the E1M1 drydock shot: the
Enterprise is shown pulling out of spacedock from "Cam Pos 1" with Picard's VO,
then the view returns to the bridge.

## Lifecycle / risk notes

- All new state lives on SDK objects that `reset_sdk_globals()` already rebuilds
  (the set's camera + its mode stack are recreated per mission swap). No
  boot-only wiring; nothing whose absence fails silently.
- The override is a pure read of existing SDK state each frame — consistent with
  the merged pull-model; one frame of 60 Hz latency is invisible.
- Production/normal-flight render path is byte-identical: outside a scripted
  in-space cutscene `_active_cutscene_camera()` returns `None`, so
  `effective_bridge == is_bridge` and every render decision is unchanged.
