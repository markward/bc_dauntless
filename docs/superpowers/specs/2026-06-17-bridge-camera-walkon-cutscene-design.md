# Bridge camera walk-on cutscene (camera + lift door)

**Date:** 2026-06-17
**Status:** Design approved, pending implementation plan
**Author:** Mark Ward + Claude

## Problem

Loading mission E1M1 crashes during `Briefing()`:

```
AttributeError: 'NoneType' object has no attribute 'UseAnimationPosition'
  E1M1.py:1832  pAnimNode.UseAnimationPosition("WalkCameraToCaptD")
```

Root cause: `pCamera = App.ZoomCameraObjectClass_GetObject(pBridge, "maincamera")`
is a real, truthy `ZoomCameraObjectClass`, but that class subclasses `_LoudStub`
(`engine/appc/bridge_set.py`). `GetAnimNode` is not a real method, so
`_LoudStub.__getattr__` returns `lambda *a, **k: None`; `pCamera.GetAnimNode()`
yields `None`, and the next line dereferences it.

This crash is the entry point to an unbuilt subsystem: the **bridge camera
walk-on cutscene**. At mission start the camera should animate from the
turbolift, glide across the bridge to the captain's chair (`WalkCameraToCaptD`),
open the L1 lift door, then settle. We treat the crash as a tracer for that
functionality and implement it faithfully rather than suppress it.

## Scope

**In scope (v1):**
- Camera-path playback: the camera glides along the baked NIF keyframes
  (`DB_Camera_Walk_Capt.NIF`) in bridge-local space, firing
  `ET_CAMERA_ANIMATION_DONE` on completion so the SDK sequence proceeds.
- L1 lift-door open animation (`DB_Door_L1.nif`) playing alongside the camera
  move (best-effort; see Risks — flagged as a follow-on if the bridge mesh has
  no separable door node).
- Auto-switch to bridge view on E1M1 load; play once; run to completion.

**Out of scope (v1):**
- Skipping the cutscene (ESC/click). Plays to completion.
- Crew walk-ons (`PicardWalkOn`), crew intros (`CrewIntros`), Liu briefing
  dialogue, viewscreen choreography — the rest of the `Briefing()` TGSequence.
- Camera stand-up / sit-down cutscenes (`DBCaptainStand`/`DBCaptainSit`) and the
  E-bridge variants (`WalkCameraToCaptOnE`) — same machinery, follow-on missions.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Delivery scope | Camera motion + lift door | The visible "arrival" moment without crew choreography. |
| Parse/sample architecture | Native parses, Python samples | Single NIF-parse source of truth in native; camera choreography lives in Python next to `_BridgeCamera`, fully unit-testable headless. |
| Trigger / skip | Auto-switch to bridge view on load; play once; run to completion (no skip) | Faithful opening; smallest correct slice — validate camera+door before adding skip/polish. |

## Core insight

Both the camera move and the door open are the same SDK call shape:

```python
App.TGAnimAction_Create(target.GetAnimNode(), clipName, ...)   # play named clip on a target's anim node
```

(`CommonAnimations.WalkCameraToCaptOnD` for the camera;
`Actions.EffectScriptActions.LiftDoorAction` for the door.) They differ only in
the **effect** of playback:

- **Camera** target → drive `_BridgeCamera` along the camera-path NIF keyframes
  (bridge-local eye + orientation).
- **Door** target (the bridge model object) → play `DB_Door_L1.nif` on the
  bridge mesh's door node via the existing `set_instance_animation` path used by
  bridge officers.

## Components

### 1. Native — expose clip parsing to Python
`native/src/host/host_bindings.cc`

New binding:

```
load_animation_clips(nif_path) ->
  [ { "name": str,
      "duration": float,
      "tracks": [ { "node": str,
                    "translation": [(t, x, y, z), ...],
                    "rotation":    [(t, x, y, z, w), ...] } ] } ]
```

Thin wrapper over the existing `assets::load_animation_clips`
(`native/src/assets/include/assets/animation.h`) — no new parsing logic.
Quaternion serialized as `(x, y, z, w)`. Scale/visibility/float tracks omitted
(not needed for the camera path or door).

**Build note:** `host_bindings.cc` is compiled into both `build/dauntless` and
the `_dauntless_host` module — requires a full `dauntless` rebuild, not just the
module (see memory `feedback_host_bindings_build_target`).

### 2. Python — real `TGAnimNode`
new `engine/appc/anim_node.py`

A recording object replacing the per-class `GetAnimNode` stubs:

- `UseAnimationPosition(name)` → stores `position_clip = name`.
- Full TGAnimNode surface from `sdk/.../App.py:587-598`
  (`UseAnimation`, `SetExclusiveAnimation`, `SetNonExclusiveAnimation`,
  `StopNonExclusiveAnimation`, `SetExclusiveAnimationUseDefault`, `Stop`,
  `Copy`, `IsAnimate`, `SetBlendTime`, `GetBlendTime`, `SetRootNode`,
  `GetRootNode`, `FindNode`) — records the clip name where meaningful, otherwise
  a chainable/truthy no-op.
- Carries a back-reference to its **owner** object and a `kind` tag
  (`"camera"` for `ZoomCameraObjectClass`, `"object"` for `BridgeObjectClass`)
  so a `TGAnimAction` built from it knows the playback target and effect.

Wiring:
- `ZoomCameraObjectClass.GetAnimNode()` returns a persistent `TGAnimNode(kind="camera", owner=self)` — fixes the reported crash.
- `BridgeObjectClass.GetAnimNode()` returns a persistent `TGAnimNode(kind="object", owner=self)` (was `None`); must keep `PutGuestChairOut/In` working — they only build a `TGAnimPosition` from the node, which is safe.

### 3. Python — `BridgeCutsceneController`
new `engine/bridge_cutscene.py`

The seam between the headless SDK action layer and the host/renderer. Holds at
most one active camera-path request plus any door request.

- `request_camera_path(action, anim_node, clip_name)` — called by the camera
  `TGAnimAction._do_play`. Records the request; the action stays `_playing`
  (does **not** auto-complete).
- `request_object_anim(action, anim_node, clip_name)` — door variant.
- `update(dt, *, bridge_camera, view_mode, renderer, anim_mgr, bridge_iid)`,
  called once per host tick:
  - **new camera request:** resolve `clip_name → nif` via
    `anim_mgr.path_for`, native-load the clip table, hand it to
    `bridge_camera.play_path(table)`, flip `view_mode` to bridge, set `t = 0`.
  - **new door request:** resolve nif, call `renderer.set_instance_animation(bridge_iid, ...)`.
  - advance `t += dt`; when `t >= duration`: `bridge_camera.end_path()`, call
    `action.Completed()` (→ `ET_CAMERA_ANIMATION_DONE`), clear the request.

Native and renderer are only touched in the live host; unit tests drive
`update` with a synthetic clip table and fake `action`/`camera`/`view_mode`.

### 4. Python — `_BridgeCamera` animation override
`engine/host_loop.py:1324`

- `play_path(table)` / `end_path()` + `_anim_table`, `_anim_t`, `_anim_active`.
- While active, `compute_camera()` returns the sampled `(eye, target, up, fov)`:
  translation LERP, rotation SLERP between surrounding keys (clamp `t` to
  `[0, duration]`); `forward = quat · localForward`, `up = quat · localUp`;
  mouse-look (`apply`) frozen.
- When inactive, the existing captain's-chair mouse-look + officer-zoom path is
  byte-identical to today.

Sampling helpers (LERP/SLERP) live in Python here (or a small
`engine/anim_sample.py`) and are unit-tested directly.

### 5. Camera/object-aware `TGAnimAction`
`engine/appc/actions.py:411`

`TGAnimAction_Create(node, clipName, ...)` records the target anim node and clip
name. On `_do_play`:
- node `kind == "camera"` → `controller.request_camera_path(self, node, clip)`, defer completion.
- node `kind == "object"` with a door clip → `controller.request_object_anim(self, node, clip)`, defer completion.
- otherwise (the dozens of character gesture `TGAnimAction`s, and any node
  without a registered controller) → today's instant-complete behavior, no
  regression.

Disambiguation is by node type, not clip-name guessing: only camera and
bridge-object anim nodes are our new `TGAnimNode` (carry a `kind`). Character
gesture `TGAnimAction`s are built from `CharacterClass.GetAnimNode()`, which
returns the existing `_NodeStub` (`engine/appc/objects.py:200`) — no `kind`, so
they never route to the controller. The bridge object only ever produces
`TGAnimAction`s for doors (`PutGuestChairOut/In` use `TGAnimPosition`, a
different class), so `kind == "object"` unambiguously means a door.

The controller is resolved lazily (module-level accessor) so `actions.py` stays
importable without the host; if no controller is registered (pure headless
tests that don't exercise the cutscene), the action falls back to instant
complete.

## Data flow

```
Briefing()  →  WalkCameraToCaptOnD(pCamera)
  pCamera.GetAnimNode()                       → TGAnimNode(kind=camera, owner=cam)   [#2]
  TGAnimAction(node, "WalkCameraToCaptD").Play → controller.request_camera_path(...) [#5→#3]
  LiftDoorAction → TGAnimAction(bridge.GetAnimNode(), "DB_Door_L1") + TGSoundAction("LiftDoor")
                                              → controller.request_object_anim(...)  [#5→#3]

host tick → controller.update(dt, ...):
  native load_animation_clips(path)            [#1]  → table
  camera: bridge_camera.play_path(table)       [#4]
  door:   renderer.set_instance_animation(bridge_iid, doorclip)
  view_mode → bridge
  t ≥ duration → action.Completed()            → ET_CAMERA_ANIMATION_DONE; sequence proceeds
```

## Asset notes

- E1M1's direct `LoadAnimation("data/animations/db_camera_capt_walk.nif",
  "WalkCameraToCaptD")` references a **missing** file, but
  `CommonAnimations.WalkCameraToCaptOnD` immediately re-registers the same name
  to `db_camera_walk_capt.nif` (**present**, `DB_Camera_Walk_Capt.NIF`, 3802 B).
  The latter is the real camera-path data; the former never resolves and is
  harmless (the re-register wins).
- Door: `DB_Door_L1.nif` present; sound `"LiftDoor"`.

## Testing strategy

| Level | Test |
|---|---|
| Unit | `TGAnimNode` records `UseAnimationPosition`; `ZoomCameraObjectClass.GetAnimNode().UseAnimationPosition("X")` does **not** raise (regression test for the reported bug). |
| Unit | `BridgeObjectClass.GetAnimNode()` real node still lets `PutGuestChairOut/In` build their `TGAnimPosition` without error. |
| Unit | `BridgeCutsceneController.update` drives a fake camera along a synthetic 2-key table and calls `action.Completed()` exactly at `t == duration`; `view_mode` flipped to bridge on first update. |
| Unit | `_BridgeCamera.compute_camera()` returns the sampled transform mid-path and freezes mouse-look; restores prior behavior after `end_path()`. |
| Unit | Sampling helpers: LERP translation + SLERP rotation match hand-computed values at key boundaries and midpoints; `t` clamps. |
| Integration | native `load_animation_clips("DB_Camera_Walk_Capt.NIF")` returns ≥1 track with `duration > 0` and non-empty translation+rotation keys. |
| Live | E1M1 loads with no `AttributeError`; in bridge view the camera glides to the captain's chair and the L1 door opens. |

## Risks

- **Door rigging.** Depends on `DB_Door_L1.nif`'s track targeting a node that
  exists in the loaded bridge model. If the bridge mesh exposes no separable
  door node, the door is split to a follow-on and the camera move still ships.
  Verified during implementation, not assumed.
- **`BridgeObjectClass.GetAnimNode()` behavior change** (None → real node).
  Mitigated by the `PutGuestChairOut/In` regression test above.
- **Completion coupling.** The action's completion is host-driven (native owns
  clip duration), not a headless Python timer. If the host never calls
  `controller.update` (e.g. cutscene requested while not rendering), the action
  would hang `_playing`. Mitigation: the controller forces completion if no
  bridge view is reachable, and the host always pumps `update` each tick.

## Out-of-scope follow-ons (noted for later)

- Skippable cutscenes (ESC/click → snap to end pose).
- `WalkCameraToCaptOnE` (Sovereign bridge), `DBCaptainStand`/`DBCaptainSit`.
- Full `Briefing()` sequence: crew walk-ons, intros, Liu dialogue, viewscreen.
