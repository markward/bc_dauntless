# Camera mode hierarchy: AddModeHierarchy for real

**Date:** 2026-08-18
**Status:** design approved
**Branch:** `feat/camera-named-modes-bc-convention`
**Predecessor:** `2026-08-18-cinematic-mode-input-focus-design.md` (shipped). That
work made F9 + F1–F6 dispatch cleanly; this work makes them move the camera.

## Problem

The cinematic camera handlers select a camera EXCLUSIVELY via the mode
hierarchy — `CinematicInterfaceHandlers.CameraChase` (`:335-342`) does nothing
but `pPlayerCam.AddModeHierarchy("InvalidCinematic", "Chase")`. Our
`CameraObjectClass.AddModeHierarchy` is a deliberate no-op
(`engine/appc/bridge_set.py:533`), so every cinematic key dispatches cleanly and
changes nothing.

## BC's mechanism (verified in the SDK)

- **Entry:** the engine calls `Camera.PlayerCameraAsCinematic()`
  (`Camera.py:810-816`) on window switch →
  `NewMode(pCamera, "InvalidCinematic", 0, 1, (), UseInvalid=1)` → pushes an
  **always-invalid marker mode** as current. The marker is nothing special:
  `AddNamedCameraMode("InvalidCinematic", CameraMode_Create("Chase", pCamera))`
  (`Camera.py:627`) — a bare Chase mode that is never given a Target, so
  `IsValid()` is always false.
- **Selection:** per-frame resolution walks hierarchy edges BY NAME from the
  current mode until it finds a valid one. The F-keys re-point one edge:
  `AddModeHierarchy("InvalidCinematic", "Chase")`. The hierarchy IS the camera
  selector. Edges REPLACE (same parent, new child).
- **Defaults** (`Camera.py:630-646`): `InvalidViewscreen→ViewscreenZoomTarget→
  ViewscreenForward`; `InvalidSpace→Target`, `Target→Chase`, `ZoomTarget→Chase`;
  `InvalidCinematic→DropAndWatch`, `TorpCam→Chase`,
  `CinematicReverseTarget→Chase`; `InvalidMap→Map`.
- **Two reads:** `GetCurrentCameraMode(0)` = raw top of stack (NewMode's
  identity compare, `Camera.py:463`); no-arg = hierarchy-RESOLVED
  (`Camera.py:478` — "may not be the mode we pushed, if the mode we pushed was
  invalid").
- **Player attrs:** `MakePlayerCamera_PlayerChanged` (`Camera.py:685-703`) sets
  the player object onto an 18-row (mode-name, attr-name) table on ET_SET_PLAYER
  — this is what gives `Chase` its Target. Without it the hierarchy resolves to
  nothing.
- **Exit:** the engine calls `Camera.PlayerCameraAsSpace()` when the
  tactical/bridge window takes back focus.

## Design

### 1. Real hierarchy on `CameraObjectClass` (`engine/appc/bridge_set.py`)

- `AddNamedCameraMode(name, mode)` — store into the existing `_named_modes`
  cache (tag `mode._named = name`), so `GetNamedCameraMode` finds it before
  falling back to the `CameraModes.<name>` builder.
- `AddModeHierarchy(parent_name, child_name)` — store `edges[parent] = child`
  in a new `_mode_hierarchy` dict. Replacing, not appending.
- `GetCurrentCameraMode(*args)`:
  - `(0)` → raw top of stack (today's behaviour, unchanged).
  - no-arg / truthy arg → resolve: start at raw top; while the mode is invalid
    AND `_mode_hierarchy` has an edge for its `_named` tag, follow the edge via
    `GetNamedCameraMode`. Cycle-guarded with a visited set. Returns the first
    valid mode, or the last mode reached (still invalid) if the walk dead-ends
    — callers already gate on `IsValid()`.
- `ZoomCameraObjectClass` (bridge camera) keeps its `_LoudStub` no-op —
  the viewscreen feed is resolved in `host_loop._viewscreen_scene_feed`, not
  via hierarchy, and must not change.

### 2. Seed the player camera (`engine/core/game.py:GetPlayerCamera` + `SetPlayer`)

Our shim never runs `Camera.MakePlayerCamera`, so the lazy `GetPlayerCamera`
seeds what it would have:

- Four `AddNamedCameraMode("Invalid*", CameraMode_Create("Chase", cam))`
  markers (never given a Target — always invalid, exactly BC's trick).
- The default hierarchy edges, verbatim from `Camera.py:630-646`.

`Game.SetPlayer` applies the 18-row player-attr table (`Camera.py:685-703`)
to the player camera's named modes via `GetNamedCameraMode(name)` +
`SetAttrIDObject(attr, player)`. Building the named modes eagerly at that point
is acceptable — they are small attr bags.

### 3. Entry/exit from the toggle (`engine/appc/top_window.py`)

`ToggleCinematicWindow` calls the REAL SDK functions — in BC these are invoked
by the C++ engine on window switch, and our toggle is that seam:

- enter → `Camera.PlayerCameraAsCinematic()`
- exit → `Camera.PlayerCameraAsSpace()` (keeps the mode stack from growing and
  restores the space chain, exactly as BC does)

Guarded import + failure-tolerant like `_init_cinematic_handlers`, and
non-silent on failure.

### 4. Render branch (`engine/host_loop.py:_active_cutscene_camera`)

When `TopWindow.is_cinematic_active()`, consult `Game.GetPlayerCamera()`'s
RESOLVED current mode first; if valid, drive the exterior view from it (same
`_cutscene_pose` conversion, same `pose_of` interpolation). If invalid — no
player, dead target — fall through to the existing logic (mission cutscene
camera, then player director), unchanged.

## Out of scope

- `Map`/`FreeOrbit`, `DropAndWatch`, `TorpCam` mode classes. F6/F1/F4 resolve
  through their edges to Chase (BC's own fallbacks: `InvalidCinematic→
  DropAndWatch` dead-ends by name → stays invalid → walk continues only where
  edges exist; after an F-key re-points the edge the chain is direct). Where a
  chain dead-ends invalid, the director keeps the frame — clean degradation.
- The camera-mode caption (`UpdateCameraModeText`) rendering surface.
- `KeyboardBinding.FindKey` / modal keyboard filters.

## Testing

1. Hierarchy: replace-edge semantics; cycle guard; `(0)` vs no-arg resolution;
   unresolved walk returns the invalid tail.
2. Seeding: player camera has the four markers + default edges; `SetPlayer`
   puts the player on the 18-row table's modes.
3. Toggle: enter pushes `InvalidCinematic` as raw current; exit swaps to
   `InvalidSpace`; stack depth stable across N toggles.
4. Render: cinematic active + valid resolved mode → frame driven by it;
   invalid resolved mode → director (existing behaviour); mission-cutscene
   camera still wins its own path; ViewscreenZoomTarget flow untouched
   (`tests/unit/test_viewscreen_zoom_target_mode.py` stays green).
5. End-to-end: F9 → F2 drives a ChaseMode pose from the player ship;
   F3 cycles CinematicReverseTarget sources.
6. Gate baseline unchanged (0 ctest, 1 known pytest).

## Risks

- `GetCurrentCameraMode()` resolution changes a shared read. Bounded: cameras
  nobody seeds have no edges, so resolution degrades to raw-top — today's
  behaviour. The cutscene camera (`CutsceneCameraBegin`) gets no edges.
- The 18-row table sets attrs on modes that may already hold live SDK-set
  values (ViewscreenZoomTarget's Source). `SetPlayer` runs before missions
  drive those, and BC does the same overwrite on every player change.
- Live pass required: F9 + F2/F3/F5 in-game, plus the bridge viewscreen and a
  mission cutscene to prove no regression.
