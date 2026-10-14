# Bridge cutscene camera — PlacementWatch on the bridge set drives the bridge view

**Status:** design, awaiting review · **Date:** 2026-10-13 · **Branch:** `fix/bridge-cutscene-camera`

## 1. Problem

Mission cutscenes that point a camera at the **bridge** render **space** instead.
E6M1's opening briefing is the reference case (`E6M1.py:1627-1730`): it starts on
Starbase 12, then `ChangeRenderedSet("bridge")` + `CutsceneCameraBegin("bridge")`
+ `PlacementWatch("bridge", "Felix Head", "FelixCam2")` and a run of further
bridge shots (guest, Saffi, the captain's view of Liu on the viewscreen). In
Dauntless the whole briefing stays in space — Mark: it has never cut to the
bridge.

**Root cause** (`engine/host_loop.py`, render prep):

```python
_cc = None if pause.sim_frozen else _active_cutscene_camera()
_apply_bridge_pass_state(view_mode.is_bridge and _cc is None, _h, view_mode)
```

`_active_cutscene_camera()` returns any live mode on the active camera of
`get_explicit_rendered_set()`. The in-space cutscene design
(`2026-07-08`, merged `5a007e2a`) assumed every such camera is exterior. When the
explicitly rendered set **is the bridge**, the bridge's own placement camera is
treated as an exterior camera: the bridge pass turns off and the space scene is
drawn from a bridge-local pose.

Headless probe of E6M1 confirms the state after the cut: explicit rendered set
`bridge`, cutscene mode on, `_active_cutscene_camera()` = live `PlacementMode`.

## 2. Evidence that shapes the design

- **Only placement cameras target the bridge.** Across `Maelstrom/`, camera
  actions with set `"bridge"` are `PlacementWatch` (220), `ChangeRenderedSet`
  (45), `CutsceneCameraEnd` (35), `CutsceneCameraBegin` (33),
  `PlacementOffsetWatch` (3), in 18 missions. Both watch actions build a
  `PlacementMode` (`Camera.LowPlacementWatch` / `PlacementOffsetWatch` →
  `NewMode(..., "Placement", ...)`).
- **Bridge placements are already bridge-local render coordinates.** In E6M1
  the bridge `Player Cam` waypoint is `(0.7, 129.6, 70.7)`, identical to the
  bridge `maincamera` position, which on the Sovereign bridge is
  `_BRIDGE_CAMERA_EYE` — the captain eye the bridge pass renders from. `View`
  sits at y = −98.5, along bridge-forward (−Y). No frame conversion is needed.
- **"Is the explicit rendered set the bridge?" is the wrong test.** 6 of the
  36 functions that call `CutsceneCameraBegin("bridge")` never call
  `ChangeRenderedSet("bridge")` — they rely on the player already being on the
  bridge (`E3M1 IntroDialogue`, `E3M1 WarpButtonPressed`, `E3M2 BerkeleyIntro`,
  `E4M4 IntroDialogue`, `E7M1 SaalekBriefing`, `Ep2Cutscene PlayCutscene`).
- **"The camera is not `maincamera`" is the wrong test too.** E4M4
  `MissionFailDialog` does `StartCutscene` → `ChangeRenderedSet("bridge")` →
  `PlacementWatch("bridge", "View", "Player Cam")` with no
  `CutsceneCameraBegin`, so the placement mode lands on the bridge
  `maincamera`. `Camera.NewMode` with `bReplace=1` replaces the Galaxy
  bridge's `GalaxyBridgeCaptain` mode there until `ResetBridgeCamera` re-pushes
  it — BC's own behaviour.
- **The bridge camera already has a bridge-local override seam.**
  `_BridgeCamera.set_anim_pose(eye, target, up)` is how
  `BridgeCutsceneController` (E1M1 walk-on camera clips) drives it; but that
  slot is coupled to `hold_anim_pose`'s latch semantics, so it is not reused.

## 3. Design

### 3.1 Rule

Each frame, a cutscene camera drives the view it belongs to:

1. **Exterior (unchanged):** a live mode on the active camera of an explicitly
   rendered **non-bridge** set drives the exterior view, exactly as today.
2. **Bridge (new):** otherwise, if the bridge is on screen and the bridge set's
   active camera has a live **`PlacementMode`**, that mode's pose drives the
   bridge camera. The bridge pass stays on.

Gating on the mode *type* (`PlacementMode`) rather than on the camera covers
all 223 SDK uses — cutscene camera or `maincamera` alike — and never fires on
the Galaxy seated `GalaxyBridgeCaptain` mode, which is a different mode.

### 3.2 Components

**`_active_cutscene_camera()` (host_loop)** — the explicit-rendered-set branch
returns nothing when that set is the bridge (`isinstance(set, BridgeSet)` or
name `"bridge"`, the same test `_resolve_active_set` already uses). The
cinematic-mode (F9) branch is unchanged. Every caller —
`_apply_bridge_pass_state`, `_apply_bridge_player_visibility`, the exterior
pose, `_player_render_interpolated` — then sees "no exterior cutscene" during a
bridge shot, with no change of its own.

**`_bridge_cutscene_camera()` (host_loop, new)** — returns `(camera, mode)` when
`g_kSetManager.GetSet("bridge")` exists, its `GetActiveCamera()` has a current
mode that is a `PlacementMode`, and `mode.IsValid()`; else `None`. Pure lookup,
no side effects.

**`_BridgeCamera` mode-pose slot (host_loop)** — a new `_mode_pose` slot beside
`_anim_pose`, with `set_mode_pose(eye, target, up)` / `clear_mode_pose()`.
- `compute_camera` precedence: `_anim_pose` (walk-on clip) → `_mode_pose` →
  held pose → normal captain view (mouse-look, crew-menu zoom). FOV is the
  base bridge FOV, the same value `_anim_pose` uses.
- `apply()` returns early while `_mode_pose` is set, so mouse-look cannot
  accumulate during the shot and snap the view when it ends.
- `reset_cutscene_pose()` (mission swap) also clears `_mode_pose`.
- `hold_anim_pose()` is untouched: it latches only `_anim_pose`.

**Host frame wiring** — in the bridge-render block (the effective-bridge path,
before `_bridge_camera_pose(...)`):
- `bcc = _bridge_cutscene_camera()`
- if `bcc`: `bridge_camera.set_mode_pose(*_cutscene_pose(mode, dt))`, reusing
  the existing direction→look-at conversion; `pose_of` is `None` (bridge
  placements are static waypoints).
- else: `bridge_camera.clear_mode_pose()`.
- While `pause.sim_frozen`, skip the update and keep the last pose, so pausing
  mid-shot holds the frame. (This deliberately differs from the exterior path,
  which drops `_cc` to `None` while paused; that existing behaviour is left
  alone.)

### 3.3 Lifecycle

- **Shot starts:** `PlacementWatch("bridge", ...)` pushes the mode; the next
  frame sets the mode pose.
- **Shot changes:** the next `PlacementWatch` replaces the mode
  (`bReplace=1`); the pose follows the next frame.
- **Shot ends:** `CutsceneCameraEnd("bridge")` removes the cutscene camera, so
  the active camera reverts to `maincamera` (no `PlacementMode`); the slot
  clears and the captain view returns. On `maincamera` (E4M4
  `MissionFailDialog`) the pose holds until something replaces the mode —
  `ResetBridgeCamera` re-pushing the seated mode — as in BC.
- **E6M1 specifically:** the Starbase 12 cutscene camera stays live until
  `CutsceneCameraEnd("Starbase12")` at the end, but once the explicit rendered
  set is the bridge it is no longer consulted, so the bridge shots win.

### 3.4 Failure behaviour

A missing placement or dead target makes `PlacementMode.IsValid()` false, so
`_bridge_cutscene_camera()` returns `None` and the normal captain view renders
— the same graceful fallback the exterior path has. No exception paths are
added.

## 4. Testing

Unit (`tests/host/`, alongside `test_cutscene_camera_selection.py`):
1. `_active_cutscene_camera()` is `None` when the explicitly rendered set is the
   bridge and its active camera holds a live `PlacementMode` (**fails today**).
2. A space set with a live mode still returns `(cam, mode)` (regression guard
   for the exterior path; existing tests also cover this).
3. `_bridge_cutscene_camera()` finds a live `PlacementMode` on a bridge
   cutscene camera, and on the bridge `maincamera`.
4. It returns `None` for a non-Placement mode on the bridge camera, for an
   invalid `PlacementMode`, and when there is no bridge set.
5. `_BridgeCamera`: mode pose overrides the captain view; a walk-on
   `_anim_pose` overrides the mode pose; `apply()` is frozen while it is set;
   `reset_cutscene_pose()` clears it; clearing returns the captain view.

Integration (headless E6M1, `tests/integration/`): load
`Maelstrom.Episode6.E6M1.E6M1`, tick until the explicit rendered set is
`bridge` with a live bridge `PlacementMode`; assert
`_active_cutscene_camera()` is `None` and the bridge mode pose's eye equals the
`FelixCam2` waypoint and its forward points at `Felix Head`. Tick to the end of
the briefing; assert no bridge mode remains.

Gate: `scripts/check_tests.sh`.

**Live (Mark):** E6M1 opening — after Felix's fourth intro line the view cuts to
the bridge: Felix close-up, guest shot, Saffi, then the captain's view of Liu on
the viewscreen; at the end of the briefing the normal captain view returns with
mouse-look working. With `fix/bare-action-turn-builders` merged in, Kiska also
turns to Felix ~1 s after the viewscreen comes on.

## 5. Out of scope

- Driving the whole bridge camera from BC's camera-mode stack (seated captain
  modes included) — the faithful long-term model, but a rewrite.
- Non-Placement modes on the bridge (`ZoomTarget`, `Locked`, ...): no SDK
  mission uses them there.
- Mode sweeps (`bSweep`): every bridge `PlacementWatch` passes `bSweep=0`.
