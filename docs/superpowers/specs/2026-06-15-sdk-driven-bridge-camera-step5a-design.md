# SDK-driven bridge init — Step 5a: captain camera + zoom-to-officer

**Date:** 2026-06-15
**Project:** SDK-driven bridge initialization (see
`docs/superpowers/specs/2026-06-15-sdk-driven-bridge-init-design.md`)
**Predecessors:** steps 1–4, 5b (viewscreen mesh), 5c (viewscreen RTT) — all merged
**Status:** design approved, ready for implementation plan

## Context

`ZoomCameraObjectClass_Create` + `ZoomCameraObjectClass_GetObject` are the **last
remaining bridge-load loud stubs**. The SDK's `GalaxyBridge.CreateBridgeModel`
creates the bridge `maincamera` at the captain's-chair position and pushes a
camera mode; `ConfigureCharacters` then overrides its Z. Step 5a makes that SDK
camera the source of truth for the bridge view's captain pose, and adds the
zoom-into-officer behaviour, finishing the "no bridge-load stubs" goal.

### What the SDK does (verified)

`Bridge/GalaxyBridge.py::CreateBridgeModel`:
```python
lPos = GetBaseCameraPosition()                 # (0.683736, 86.978439, 50.0)
pCamera = App.ZoomCameraObjectClass_Create(lPos[0], lPos[1], lPos[2],
            1.570796, -0.000665, -0.087559, 0.996159, "maincamera")  # angle-axis
pCamera.SetMinZoom(0.64); pCamera.SetMaxZoom(1.0); pCamera.SetZoomTime(0.375)
pBridgeSet.AddCameraToSet(pCamera, "maincamera")
pCamera.PushCameraMode(pCamera.GetNamedCameraMode("GalaxyBridgeCaptain"))
pCamera.Update(App.g_kUtopiaModule.GetGameTime())
```
`ConfigureCharacters` then: `App.ZoomCameraObjectClass_GetObject(pBridgeSet,
"maincamera").SetTranslateXYZ(0.683736, 86.978439, 61.934944)` — so the camera's
**final** position is z=**61.934944**, not the 50.0 from create. Both calls run
in our headless `LoadBridge.Load` path.

### Current host state (what 5a replaces)

- `host_loop._BridgeCamera` is **our own** first-person mouse-look camera. Its eye
  comes from a hardcoded `_BRIDGE_CAMERA_OFFSETS` table keyed by
  `_CURRENT_BRIDGE_NAME` (GalaxyBridge → z=**50.0**, unfaithful to the final 61.93).
  `_CURRENT_BRIDGE_NAME`/`_BRIDGE_CAMERA_OFFSETS` are consumed **only** by the
  camera's `_eye_offset()`.
- `compute_camera()` returns `(eye, target, up)`; the host hands them to
  `r.set_bridge_camera(eye, target, up, fov_y_rad, near, far)` with `fov_y_rad =
  _BridgeCamera.FOV_Y_RAD` (a constant 60°).
- Officers are rendered and tracked: step 4 sets `off._render_instance = iid` per
  `CharacterClass` and appends to `controller.officer_instances`; station → officer
  is `bridge.GetObject("Helm"/"Tactical"/"XO"/"Science"/"Engineer")`.
- Crew menus open via **F1–F5** (`engine/ui/crew_menu_hotkeys.py`, map
  `_KEY_TO_CHARACTER`: menu "Commander"→char "XO", "Engineering"→"Engineer"); the
  open menu is tracked by `CrewMenuPanel._open_menu_id` / `has_open_menu()`.
- `get_instance_bounds(iid)` returns an instance's world-space `(x,y,z,radius)`
  (used by the Ship Property Viewer).

## Goal & scope

1. **Captain pose = SDK source of truth.** Make `ZoomCameraObjectClass` a real
   data object; the host reads the realized `maincamera` position; `_BridgeCamera`
   uses it (config-driven for every bridge), deleting `_BRIDGE_CAMERA_OFFSETS`.
   Drop `ZoomCameraObjectClass_Create` + `_GetObject` off the stub summary — **the
   last bridge-load stub**.
2. **Zoom-into-officer.** Selecting an officer (their open crew menu) makes the
   captain camera — **without leaving the chair** — rotate to look at that officer
   and narrow FOV onto them, eased over the SDK zoom time; deselect eases back to
   the captain view. Driven by SDK numbers (min zoom 0.64, zoom time 0.375) over a
   look-at target we already have (the officer's rendered world position).

**Orientation stays the existing tuned mouse-look** (decision A) — only the
*position* comes from the SDK; the camera's base look direction is unchanged.

**Out of scope (deferred):**
- Camera-mode *targeting geometry* beyond looking at the officer (the engine's
  named modes `GalaxyBridgeCaptain`/station framings) — we reconstruct
  "look at the officer + narrow FOV", not the engine's internal mode transforms.
- Free/forward zoom when no officer is selected (captain view is plain mouse-look
  at full FOV).
- Continuous mouse-wheel `Zoom(factor)`; viewscreen-zoom-target mode; `ToggleZoom`
  hardware-key path — all remain `_LoudStub` no-ops.

**Pure Python — no rebuild** (the renderer already takes a per-frame `fov_y_rad`).
`engine/appc/` stays headless.

## Design

### 1. `ZoomCameraObjectClass` becomes a real data object (`engine/appc/bridge_set.py`)

Mirror 5b's `ViewScreenObject` promotion: keep `_LoudStub` as the base (the SDK
calls a large camera-mode/zoom surface — `GetNamedCameraMode`, `PushCameraMode`,
`Update`, `ToggleZoom`, `Zoom`, `IsZoomed`, `LookForward`, … — that we do not
implement and must stay silent no-ops), but make the *data* real:

```python
class ZoomCameraObjectClass(_LoudStub):
    """SDK bridge camera ("maincamera"). Core data is real (captain-chair
    position, angle-axis orientation, zoom min/max/time); the engine's
    camera-mode + zoom-transform surface (GetNamedCameraMode, PushCameraMode,
    Update, ToggleZoom, Zoom, IsZoomed, ...) stays a silent _LoudStub no-op —
    that geometry lived in Appc and is not reconstructed here. The host reads
    `position` + zoom params after LoadBridge.Load to drive _BridgeCamera."""
    def __init__(self, x, y, z, qw, qx, qy, qz, name):
        self.position = (x, y, z)
        self.orientation = (qw, qx, qy, qz)   # angle, axis-x, axis-y, axis-z
        self._name = name
        self._min_zoom = 1.0
        self._max_zoom = 1.0
        self._zoom_time = 0.0
    def SetMinZoom(self, v):  self._min_zoom = v
    def SetMaxZoom(self, v):  self._max_zoom = v
    def SetZoomTime(self, v): self._zoom_time = v
    def GetMinZoom(self):  return self._min_zoom
    def GetMaxZoom(self):  return self._max_zoom
    def GetZoomTime(self): return self._zoom_time
    def SetTranslateXYZ(self, x, y, z): self.position = (x, y, z)
```

- `ZoomCameraObjectClass_Create(...)` — drop the `stub_call` (real → off summary).
- `ZoomCameraObjectClass_GetObject(pSet, name)` — drop the `stub_call`; return the
  real camera from the set (`pSet.GetCamera(name)`); keep the `_LoudStub()`
  fallback only when the camera is absent (so `ConfigureCharacters`'
  `SetTranslateXYZ` never crashes), but that path no longer fires `stub_call`.

After this, a real `Load("GalaxyBridge")` leaves the `[BRIDGE-STUB] SUMMARY`
**empty of bridge-load symbols**.

### 2. Host: captain eye position from the SDK camera (`engine/host_loop.py`)

- In `_after_mission_loaded` (where `_realize_viewscreen` etc. run), read the
  realized camera and cache its position in a module global, replacing the
  hardcoded table:
  ```python
  global _BRIDGE_CAMERA_EYE
  _cam = bridge.GetCamera("maincamera")
  if _cam is not None and hasattr(_cam, "position"):
      _BRIDGE_CAMERA_EYE = _cam.position
  ```
  Also cache the zoom params onto the live `bridge_camera` (see §3):
  `bridge_camera.set_zoom_params(_cam.GetMinZoom(), _cam.GetMaxZoom(),
  _cam.GetZoomTime())`.
- `_BridgeCamera._eye_offset()` returns `_BRIDGE_CAMERA_EYE` (default = the
  GalaxyBridge captain position as a fallback when no SDK camera is present).
- **Delete** `_BRIDGE_CAMERA_OFFSETS`. `_CURRENT_BRIDGE_NAME` becomes orphaned
  (its only consumer was `_eye_offset`); remove it and its mission-load setter.

### 3. `_BridgeCamera` zoom state machine (`engine/host_loop.py`)

`_BridgeCamera` gains (pure Python, no renderer dependency — the host resolves the
target world position and passes it in):

```python
# zoom params (set from the SDK camera at mission load; FOV multipliers + seconds)
self._min_zoom = 1.0      # zoomed-in FOV factor (0.64) -> telephoto
self._max_zoom = 1.0      # captain FOV factor (1.0)
self._zoom_time = 0.0     # seconds for a full ease
# zoom state
self._zoom_t = 0.0                 # 0 = captain view, 1 = framed on officer
self._zoom_target = None           # (x,y,z) world pos of the officer, or None
```

- `set_zoom_params(min_z, max_z, t)` — store the SDK values.
- `set_zoom_target(world_xyz_or_none, dt)` — set `_zoom_target`; advance `_zoom_t`
  toward 1.0 when a target is set, toward 0.0 when `None`, at rate `dt /
  max(_zoom_time, eps)`, clamped to [0, 1]. While a target is set, **mouse-look is
  suspended** (skip yaw/pitch accumulation in `apply`).
- `compute_camera()` returns `(eye, target, up, fov_y_rad)` — FOV is now per-frame:
  - `eye = _eye_offset()` (SDK position).
  - Compute the captain look basis (existing mouse-look forward/up).
  - If `_zoom_t > 0` and `_zoom_target` is not None: form the officer look
    direction `normalize(_zoom_target - eye)`, and **slerp/blend** the look
    direction from captain-forward toward officer-forward by `ease(_zoom_t)`
    (smoothstep); `target = eye + blended_forward`.
  - `fov_y_rad = FOV_Y_RAD * lerp(_max_zoom, _min_zoom, ease(_zoom_t))`.
  - At `_zoom_t == 0`: pure mouse-look + `FOV_Y_RAD * _max_zoom`.

The host's per-frame render block (where it already calls
`bridge_camera.apply(...)` and `set_bridge_camera(...)`) gains: resolve the active
officer iid (§4) → its world centre via `get_instance_bounds` → call
`bridge_camera.set_zoom_target(world_or_none, dt)`; then pass the returned
`fov_y_rad` into `r.set_bridge_camera(..., fov_y_rad=fov)` instead of the constant.

### 4. Active-officer resolution (`engine/host_loop.py`)

A small pure helper, unit-testable with fakes:

```python
def _active_zoom_officer_world(crew_menu_panel, bridge, r):
    """Return the world-space centre (x,y,z) of the officer whose crew menu is
    open, or None. Resolves the open menu -> station name -> bridge character ->
    its rendered instance -> get_instance_bounds. None when no menu is open, the
    station/officer/instance is missing, or bounds are unavailable."""
```

Resolution path: `crew_menu_panel.has_open_menu()` → the open menu's root → its
menu label → `_KEY_TO_CHARACTER`-style map → character station name →
`bridge.GetObject(station)` → `off._render_instance` → `r.get_instance_bounds(iid)`
→ `(x, y, z)`. Any missing hop returns `None` (→ captain view). The exact
open-menu→station mapping reuses the crew-menu-hotkeys label map; the plan pins the
lookup. Called once per bridge frame; the result is fed to `set_zoom_target`.

## Testing

Focused files only. **Never** the full suite (>100 GB RAM, freezes macOS) — warn
subagents.

- **`tests/unit/test_bridge_set_stubs.py`** (update — the existing
  `test_camera_stub_supports_sdk_calls` asserts `ZoomCameraObjectClass_Create` *is*
  fired; flip it): `ZoomCameraObjectClass` stores position/orientation/zoom params;
  `SetMinZoom/Max/ZoomTime` round-trip via the getters; `SetTranslateXYZ` updates
  `position`; `ZoomCameraObjectClass_Create` + `_GetObject` no longer fire
  `stub_call`; an unbuilt method (e.g. `PushCameraMode`/`ToggleZoom`) still no-ops
  via `_LoudStub`.
- **`tests/integration/test_sdk_bridge_load.py`** (update) — after a real
  `Load("GalaxyBridge")`: `bridge.GetCamera("maincamera").position` is
  `(0.683736, 86.978439, 61.934944)` (the ConfigureCharacters override won),
  zoom params are (0.64, 1.0, 0.375), and the `[BRIDGE-STUB] SUMMARY` is **empty**
  (no `ZoomCameraObjectClass_*`, no other bridge-load symbols).
- **`tests/unit/test_bridge_camera_zoom.py`** (new) — `_BridgeCamera` as a pure
  unit: with eye, a target world pos, and params (min=0.64, max=1.0, time=0.375):
  at `_zoom_t == 0` → look-dir = captain forward, `fov == FOV_Y_RAD`; after
  easing to `_zoom_t == 1` (drive `set_zoom_target(target, dt)` enough) → look-dir
  points at the target and `fov == FOV_Y_RAD * 0.64`; `set_zoom_target(None, dt)`
  eases back to captain view; mouse-look `apply` is a no-op while a target is set;
  `_zoom_t` clamps to [0, 1].
- **`tests/unit/test_active_zoom_officer.py`** (new) — `_active_zoom_officer_world`
  with fakes: open menu for "Tactical" → returns that officer's bounds centre;
  no open menu → None; missing instance/bounds → None.

Live verify (Mark): in bridge view, F1–F5 zoom the captain camera onto each
officer from the chair (camera does not move, FOV narrows, officer centred); ESC /
closing the menu eases back to the captain view; the eye sits at the faithful
z≈61.93.

## Verification, risks, rollback

- **Risks:** (a) the eased look-at toward an off-axis officer (e.g. Engineer
  behind the chair) may swing past comfortable limits — accepted; tune the ease /
  clamp by feel during live verify. (b) `get_instance_bounds` centre is the
  officer's mesh AABB centre (torso-ish), a good enough look-at point; if it reads
  oddly we record it, not invent an offset. (c) the open-menu→station label
  mapping must match the crew-menu labels exactly (Commander/Engineering aliases)
  — covered by reusing the existing map.
- **No regression:** exterior/SPV/viewscreen paths untouched; bridge mesh +
  officers + RTT feed unchanged. The only live change in the default bridge view is
  the eye height (50.0 → 61.93) and the per-frame (vs constant) FOV, which equals
  the old constant when no officer is selected (`_max_zoom == 1.0`).
- **Rollback:** revert the branch; all changes are additive Python (stub
  promotion + camera state + host wiring). No rebuild.

## Follow-ups (not this step)

- Engine-faithful camera modes (the real `GalaxyBridgeCaptain` / station / viewscreen
  zoom-target geometry, mode hierarchy, `Update`/`SnapToIdealPosition`) — a separate
  reverse-engineering project if ever wanted.
- Continuous mouse-wheel zoom and the hardware `ToggleZoom` key path.
- **Step 6:** verify extras/menus + live-verify non-Galaxy bridges (now fully
  config-driven incl. their camera positions).
