# Bridge-camera "stand up" persistence — design

Date: 2026-07-25
Status: approved (design), pending implementation plan

## Problem

In E1M1, when Picard walks onto the bridge the player camera is meant to
**stand up** — rise from the seated captain's-chair eye to a standing eye — so
the player clearly sees Picard and Saffi's walk-on and is introduced to Saffi as
the XO. The stand is a *persistent* camera state: BC holds the standing pose from
the Picard/Saffi walk-on through the start of the XO introduction, until an
explicit sit re-seats the player.

Current Dauntless behaviour: the stand-up animation plays (camera rises), then the
instant the clip finishes the camera **jumps back down** to the seated eye and the
rest of the cutscene plays from a seated POV.

## Root cause

Two independent facts combine.

1. **The cutscene controller reverts after every camera animation.**
   `BridgeCutsceneController._update_camera` (`engine/bridge_cutscene.py:129-132`)
   unconditionally calls `bridge_camera.clear_anim_pose()` when a clip completes,
   dropping the override so the camera falls back to its default eye.

2. **The default eye is a single, seated pose baked once at load.**
   `_BRIDGE_CAMERA_EYE` (`engine/host_loop.py:1405`) is harvested from the
   `GalaxyBridgeCaptain` camera mode's `BasePosition` at mission load
   (`engine/host_loop.py:5908-5934`) and used every frame by
   `_BridgeCamera.compute_camera` (`engine/host_loop.py:2665`). There is no
   "standing eye" state to revert *to*.

### Why the walk-on doesn't show the bug but the stand does

The same `clear_anim_pose()` fires after the `WalkCameraToCaptOnD` walk-on, but
that clip's final keyframe lands exactly on the seated eye, so reverting is
invisible by design (documented at `engine/bridge_cutscene.py:26-28`). The
controller was built on the assumption that *every* camera animation ends at the
seated pose — true for the walk-on, false for `DBCameraStandUp`, whose final
keyframe is the standing eye.

### The SDK's real mechanism: the camera-mode stack

The persistence in BC comes from the **camera-mode stack**, not the animation:

- `Bridge/Characters/CommonAnimations.py:71-89` — `DBCaptainStand` plays
  `DB_Camera_Stand_Up.nif` and, unlike the walk-on, does **not** call
  `UseAnimationPosition`.
- `Maelstrom/Episode1/E1M1/E1M1.py:1899` — `PicardWalkOn` calls
  `pCamera.PopCameraMode("GalaxyBridgeCaptain")` **before** the stand, so nothing
  overwrites the camera transform each frame and the anim node holds its final
  (standing) keyframe.
- `Maelstrom/Episode1/E1M1/E1M1.py:2330` — `DBCaptainSit` plays
  `DB_Camera_Sit_Down.nif` (ends at the seated eye), then
  `ResetBridgeCamera` (`E1M1.py:2067`) re-pushes the seated mode:
  `pCamera.PushCameraMode(pCamera.GetNamedCameraMode("GalaxyBridgeCaptain"))`.

The mode stack is already maintained correctly in Dauntless
(`engine/appc/bridge_set.py:200-224`: `PushCameraMode`/`PopCameraMode` push/pop
`_mode_stack`; `GetNamedCameraMode` tags the mode with `_named`). The **only**
missing link is that the live `_BridgeCamera` never consults it — the seated eye
is baked at load and always used, so `PopCameraMode("GalaxyBridgeCaptain")` pops
an entry nothing reads at runtime.

## Approach (chosen)

**Layer a "held pose" on top of the existing baked seated path**, gated by the
mode stack. Lowest regression surface: the normal (non-cutscene) seated view stays
byte-identical; a new held-pose layer activates only while the seated captain mode
is absent from the stack. Because the gate is the mode stack, the fix is
bridge-agnostic — E-bridge (`WalkCameraToCaptOnE`) and any other bridge get the
same persistence for free, and no-mode bridges (Sovereign) are unaffected.

(Alternative considered and rejected for this change: refactor `_BridgeCamera` to
source the seated eye live from the top-of-stack mode every frame. More general
but touches the normal seated view — larger regression surface to re-verify
in-game. Deferred; not needed to fix the stand.)

## Design

### Part 1 — `_BridgeCamera` gains a gated held pose

Add `self._held_pose = None` and a reference to the live camera object (the
`ZoomCameraObjectClass` already captured as `_BRIDGE_ZOOM_CAM` at load). New
precedence in `compute_camera` (`engine/host_loop.py:2665`):

1. `_anim_pose` set (a clip is **actively playing**) → use it verbatim.
   *(unchanged)*
2. `_held_pose` set **and the seated captain mode is NOT on the stack** → use the
   held pose, with the same FOV as the anim-pose path (seamless continuation from
   the clip that just finished). **← new**
3. otherwise → the existing baked seated eye with turn-lift + mouse-look.
   *(unchanged — covers both "seated mode active" and Sovereign "no-mode"
   bridges)*

"Seated mode active" means the camera's top-of-stack mode is a live seated bridge
mode — `GetCurrentCameraMode()._named == "GalaxyBridgeCaptain"` (equivalently a
`PlaceByDirectionMode`). When the seated mode *is* active, `_held_pose` is
discarded, so each cutscene starts from a fresh latch rather than a stale one.

The held pose freezes mouse-look and zoom (the camera is mid-cutscene and player
control is removed via `RemoveControl` anyway), matching BC — a popped-mode
camera is a static held transform.

### Part 2 — the controller holds instead of clearing

In `engine/bridge_cutscene.py:129-132`, on clip completion replace the
unconditional `bridge_camera.clear_anim_pose()` with a **hold**: latch the final
sampled pose as `_held_pose` and clear the transient `_anim_pose`. Always-hold is
safe because all gating lives in `compute_camera`:

- **Walk-on** (`WalkCameraToCaptD`): seated mode never popped → held gated off →
  live seated eye (final keyframe == seated eye anyway). *Behaviour unchanged.*
- **Stand** (`DBCameraStandUp`): seated mode popped at `E1M1.py:1899` → held wins
  → **standing pose persists.** *This is the fix.*
- **Sit** (`DBCameraSitDown`): ends at the seated eye; a frame later
  `ResetBridgeCamera` re-pushes the seated mode → held discarded → live seated
  eye. *Seamless re-seat.*

`BridgeCutsceneController` is bridge-only (it calls `view_mode.set_bridge()`);
in-space cutscene cameras run through the separate `engine/appc/camera_modes.py` /
`_CameraDirector` path, so this change cannot leak into space shots.

### Part 3 — wiring & safety

- `_BridgeCamera` receives the live cam via a setter called in the post-load
  harvest, right where `_BRIDGE_ZOOM_CAM = _cam` is set
  (`engine/host_loop.py:5934`). This keeps it testable — a fake cam exposing
  `GetCurrentCameraMode()` drives the mode-stack gate in unit tests.
- Mission swap already recreates `_BridgeCamera` and the controller resets its
  cutscene state, so `_held_pose` cannot leak across missions.
- Sovereign / no-mode bridges: mode-stack-agnostic by construction. They never
  latch a held pose during normal play (they fall to the baked seated eye);
  E-bridge's `WalkCameraToCaptOnE` and its stand get the same persistence for
  free.

## Testing

- **Unit (`_BridgeCamera`)**:
  - held pose set + seated mode absent → `compute_camera` returns the held pose.
  - held pose set + seated mode present → returns the baked seated eye (held
    discarded).
  - no held pose → baked seated eye.
  - Sovereign fake (empty mode stack, no held pose) → baked seated eye.
- **Unit (`BridgeCutsceneController`)**: clip completion latches the final sampled
  pose as held and clears the transient `_anim_pose`; walk-on vs stand
  distinguished purely by the fake cam's mode-stack state.
- **Gate**: `scripts/check_tests.sh` (pytest + ctest) green, no new failures
  outside `tests/known_failures.txt`.
- **Live verification (required)**: this is a camera/render change — green tests
  cannot confirm it looks right. Final confirmation is Mark watching E1M1: the
  stand-up holds through the Picard/Saffi walk-on and the XO introduction, then
  sits cleanly when `DBCaptainSit` plays.

## Non-goals

- Refactoring `_BridgeCamera` to be fully mode-stack-driven each frame (deferred).
- Any change to in-space cutscene cameras (`camera_modes.py` / `_CameraDirector`).
- Changing the seated-eye harvest or the turn-lift / mouse-look behaviour of the
  normal seated view.
