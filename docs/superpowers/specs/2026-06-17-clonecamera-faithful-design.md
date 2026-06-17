# Faithful `CloneCamera` + comm-set render flag — design

**Date:** 2026-06-17
**Status:** Approved, pre-implementation

## Problem

Loading mission `Maelstrom.Episode1.E1M1.E1M1` crashes during `CreateSets`:

```
AttributeError: 'ModelManager' object has no attribute 'CloneCamera'
  MissionLib.SetupBridgeSet(...)  ->  App.g_kModelManager.CloneCamera(pcModelName)
```

`MissionLib.SetupBridgeSet` ([sdk/Build/scripts/MissionLib.py:1469](../../../sdk/Build/scripts/MissionLib.py))
calls `App.g_kModelManager.CloneCamera(pcModelName)` to extract a camera embedded in
the set NIF. Our `ModelManager` shim ([engine/appc/bridge_set.py:120](../../../engine/appc/bridge_set.py))
never implemented it. Because `g_kModelManager` is a *real* instance, the attribute
miss raises `AttributeError` instead of falling through `App.py`'s module-level
`_NamedStub` catch-all.

A stop-gap fix already landed: `CloneCamera` returns `None` unconditionally, which
routes `SetupBridgeSet` into its well-defined fallback branch (build a camera from
explicit coordinates). This design replaces that stop-gap with a faithful
implementation.

## Findings from investigation

- **Some set NIFs carry an embedded camera, the player bridges do not.**
  `starbasecontrolRM.NIF` has one `NiCamera` block named `Camera01`; `DBridge.NIF`
  and `EBridge.NIF` have none. This explains the SDK code: `SetupBridgeSet`'s
  `None` branch hardcodes camera coordinates *specifically* for DBridge/EBridge
  ([MissionLib.py:1475-1478](../../../sdk/Build/scripts/MissionLib.py)) — precisely
  because those NIFs have no embedded camera.
- **`Camera01` has a real placement.** It is nested two NiNodes deep:
  `NiNode 'Camera01'[25] → NiNode ''[26] → NiCamera[27]`. Its world position and
  orientation come from that parent chain, not the origin.
- **The native NIF parser already reads `NiCamera`.** `native/src/nif/include/nif/block.h:57`
  defines the struct (frustum left/right/top/bottom, near/far, viewport, lod_adjust);
  `native/src/nif/src/blocks/scene.cc:58` parses every flat field. The
  `AvObjectBase` carries each node's local transform. So the *frustum/near-far* are
  trivially available; the *world transform* needs a parent-chain walk.
- **No Python binding exposes parsed `NiCamera` data** — NIF parsing happens C++-side.
- **Comm-set rendering is genuinely unimplemented.** The viewscreen RTT
  ([host_bindings.cc:373-456](../../../native/src/host/host_bindings.cc)) always
  renders the *forward space view* (`g_camera`) into the RTT and **ignores**
  `viewscreen._remote_cam`. So `MissionLib.ViewscreenOn` setting a remote camera
  (`pViewScreen.SetRemoteCam(pMainCamera)` + `SetIsOn(1)`,
  [MissionLib.py:1213](../../../sdk/Build/scripts/MissionLib.py)) currently does
  nothing visible. The only set camera the host consumes is the *player* `"bridge"`
  set's `maincamera` ([host_loop.py:2615](../../../engine/host_loop.py)).

## Scope (decided)

Faithful **data plumbing only**, with a **full** camera world transform. Comm-set
rendering itself (rendering a remote set through the cloned camera into the
viewscreen RTT) is **out of scope** — but when a mission requests it, developer mode
must loudly announce that it is not implemented.

## Components

### 1. C++ parse-only binding

New host binding in [native/src/host/host_bindings.cc](../../../native/src/host/host_bindings.cc),
exposed to Python via the host bindings module:

```
parse_set_camera(nif_path: str, search_paths: list[str]) -> dict | None
```

- Runs the existing NIF parser **parse-only** — no GPU upload, no model-cache entry.
- Finds the first `NiCamera` block in the file.
- Composes the camera's **world transform** by walking from the scene root down the
  parent `NiNode` chain to the camera, accumulating each node's local transform
  (rotation · scale, then translation). Reuse the nif→scenegraph loader's existing
  world-transform composition if it is factored out; otherwise a small recursive
  walk over the parsed block tree.
- Returns, or `None` if the NIF contains no `NiCamera`:
  ```
  {
    "position": (x, y, z),            # world-space, NIF model frame, game units
    "rotation": (9 floats),           # 3x3 column-major (per CLAUDE.md convention)
    "frustum":  (left, right, top, bottom),
    "near":     n,
    "far":      f,
  }
  ```
- Frame/units: positions and rotations follow the project's column-vector rotation
  convention (CLAUDE.md) and game-unit convention (1 GU = 175 m); no display
  conversion. Rotation is returned column-major so `R.GetCol(1)` is forward, etc.

### 2. Python camera surface — [engine/appc/bridge_set.py](../../../engine/appc/bridge_set.py)

- `ModelManager.CloneCamera(path)`:
  - **Guarded** import of the host bindings module. If absent (headless tests) →
    return `None`.
  - Call `parse_set_camera(path, search_paths)`. If it returns `None` (no embedded
    camera, or parse failure) → return `None`.
  - Else wrap the dict in a `NiCameraData` holder and return it.
  - Net effect: identical fallback behavior to today wherever a camera is absent or
    the engine isn't present; faithful camera wherever one exists in a running engine.
- `NiCameraData`: lightweight immutable holder for the parsed dict — this is the
  object the SDK treats as the opaque "pNiCamera" handle. Carries the source path
  for diagnostics.
- `_NiFrustum`: mutable struct with attributes `m_fLeft`, `m_fRight`, `m_fTop`,
  `m_fBottom` (the SDK reads, scales by 0.5, and writes them back).
- `CameraObjectClass`: real camera data object:
  - `position`, `orientation`
  - `GetNiFrustum() -> _NiFrustum`
  - `SetNiFrustum(frustum)`
  - `SetNearAndFarDistance(near, far)`
  - Stored in a `SetClass` by name via the existing `AddCameraToSet`/`GetCamera`.
- Module-level functions registered into the `App` namespace (explicit attributes
  shadow `App.py`'s `__getattr__` catch-all, same mechanism as
  `ZoomCameraObjectClass_Create`):
  - `CameraObjectClass_CreateFromNiCamera(niCamera, name)` — builds a
    `CameraObjectClass` from `NiCameraData` (copies frustum/near/far/transform).
    Used by `SetupBridgeSet`'s `else` (camera-found) branch.
  - `CameraObjectClass_Create(x, y, z, a, ax, ay, az, name)` — builds a
    `CameraObjectClass` from explicit coordinates. Currently resolves to a
    `_NamedStub`; making it real makes both `SetupBridgeSet` branches uniform and
    unit-testable.

### 3. Dev-mode comm-set render flag — host step-5c

In [engine/host_loop.py:3341-3345](../../../engine/host_loop.py) where the viewscreen
RTT feed is driven on/off:

- When the realized viewscreen object reports `IsOn()` **and** has a non-`None`
  `GetRemoteCam()` (a comm/remote set was requested via `ViewscreenOn`), and
  `dev_mode.is_enabled()`, log a **loud one-shot** warning on the on-transition
  (tracked so it fires once per activation, not every frame):

  > `comm-set rendering requested (remote maincamera) — NOT IMPLEMENTED; viewscreen shows forward view instead.`

- Gated by `dev_mode.is_enabled()`. Production (dev off) is **byte-identical** — no
  log, and the RTT already ignores the remote cam, so behavior is unchanged.
- The announcement logic is factored into a small pure helper so it is unit-testable
  without the renderer.

## Data flow

```
SetupBridgeSet("StarbaseSet", nif, ...)
  -> CloneCamera(nif)
       -> _dauntless_host.parse_set_camera(nif, search_paths)  -> dict | None
       -> NiCameraData (or None)
  -> else branch (camera found):
       CameraObjectClass_CreateFromNiCamera(NiCameraData, "maincamera") -> CameraObjectClass
       GetNiFrustum() *0.5 each side -> SetNiFrustum()
       AddCameraToSet(camera, "maincamera")
  -> None branch (no camera): CameraObjectClass_Create(coords) -> AddCameraToSet  [unchanged]

later: ViewscreenOn("StarbaseSet", "Liu")
  -> pMainCamera = set.GetCamera("maincamera")
  -> viewscreen.SetRemoteCam(pMainCamera); viewscreen.SetIsOn(1)

host step-5c: viewscreen.IsOn() and viewscreen.GetRemoteCam() is not None
  -> dev_mode.is_enabled() -> loud one-shot "comm render NOT IMPLEMENTED"
```

## Error handling

- Host bindings module absent (headless tests, stale `.so`) → `CloneCamera` returns
  `None` → SDK fallback branch (existing, safe).
- `parse_set_camera` on a missing or malformed NIF → returns `None` (logged C++-side)
  → fallback branch.
- NIF with no `NiCamera` (e.g. DBridge/EBridge) → `None` → fallback branch.

## Testing

**Headless unit (no binary required):**
- `CameraObjectClass_CreateFromNiCamera` with synthetic `NiCameraData`: frustum,
  near/far, position, orientation are copied; `GetNiFrustum`/`SetNiFrustum`
  round-trip; the SDK's 0.5 frustum-halving produces expected values.
- `CameraObjectClass_Create` fallback: produces a real camera at the given coords.
- `SetupBridgeSet` **else** branch: `CloneCamera` monkeypatched to return a
  `NiCameraData` → set has a `maincamera` with halved frustum, no exception.
- `SetupBridgeSet` **None** branch: `CloneCamera` → `None` → fallback camera added
  (preserves today's behavior).
- Dev-announce helper: fires exactly once when viewscreen is on + has a remote cam;
  silent when `dev_mode` is disabled; silent when no remote cam.

**Native (native/tests/nif):**
- `parse_set_camera` on `starbasecontrolRM.NIF` returns a camera with the expected
  frustum bounds and a non-identity world transform.
- `parse_set_camera` on `DBridge.NIF` / `EBridge.NIF` returns `None`.

**Integration (manual, running engine):**
- Load `Maelstrom.Episode1.E1M1.E1M1` via the developer mission picker → no crash.
- With `--developer`, the comm-render-not-implemented warning appears when Admiral
  Liu's viewscreen scene (`ViewscreenOn`) triggers.

## Out of scope

- Rendering the remote/comm set through the cloned camera into the viewscreen RTT
  (the actual comm scene). Deferred; surfaced loudly under developer mode by
  component 3 so it is not silently forgotten.
- Any change to the player `"bridge"` set camera path (`ZoomCameraObjectClass`,
  captain's-chair eye) — untouched.
