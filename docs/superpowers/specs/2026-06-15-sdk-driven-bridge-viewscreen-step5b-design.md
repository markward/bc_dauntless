# SDK-driven bridge init — Step 5b: viewscreen mesh

**Date:** 2026-06-15
**Project:** SDK-driven bridge initialization (see
`docs/superpowers/specs/2026-06-15-sdk-driven-bridge-init-design.md`)
**Predecessors:** step 3 (bridge mesh), step 4 (officers) — both merged to `main`
**Status:** design approved, ready for implementation plan

## Context

`LoadBridge.Load("GalaxyBridge")` runs end-to-end on the SDK path. Step 3
realized the SDK-created bridge mesh; step 4 placed the SDK-created officers.
The remaining `[BRIDGE-STUB] SUMMARY` entries are `ViewScreenObject_Create`,
`ZoomCameraObjectClass_Create` (+ `_GetObject`), and the `BridgeSet.*`
config/viewscreen/camera methods.

Step 5 (viewscreen + zoom camera) splits into three separable pieces:

- **5a** — bridge zoom camera: make the SDK `ZoomCameraObjectClass` the source
  of truth for the captain's-chair position + zoom params (pure Python).
- **5b — this spec** — viewscreen mesh realization.
- **5c** — viewscreen render-to-texture of the tactical scene (deferred-work
  item #26; a real C++ framebuffer feature).

**Mark chose to do 5b first.**

### What the SDK does

`Bridge/GalaxyBridge.py::CreateBridgeModel`:

```python
App.g_kModelManager.LoadModel("data/Models/Sets/DBridge/DBridgeViewScreen.nif", None, pcEnvPath)
pViewScreen = App.ViewScreenObject_Create("data/Models/Sets/DBridge/DBridgeViewScreen.nif")
pBridgeSet.SetViewScreen(pViewScreen, "viewscreen")   # stores _viewscreen AND AddObjectToSet(..., "viewscreen")
```

`LoadBridge.Load` later saves/restores the viewscreen's remote camera
(`GetRemoteCam`/`SetRemoteCam`/`SetIsOn`) — on a *fresh* load `pCamera == None`,
so those are not hit; they matter for 5c and for mission-driven viewscreen
changes.

### Asset facts (verified)

- `DBridgeViewScreen.nif` (`game/data/Models/Sets/DBridge/DbridgeViewScreen.NIF`)
  is **1556 bytes**: a single `NiTriShape` named **"room screen"** with a
  `NiTextureModeProperty` and **no authored base texture** (no `.tga`/`.dds`
  string). The screen surface is purely the RTT *target* — in the real game it
  always displays the remote-cam feed.
- The SDK never calls `SetTranslateXYZ` on the viewscreen, so it lives at
  **identity** in bridge-local space — the same frame as `DBridge.nif`. The
  "room screen" geometry is authored in bridge-local coords; identity aligns it
  to the front wall by construction (exactly the assumption the SDK relies on).
- `bridge.frag` samples `u_base_color`; with no authored texture the renderer
  binds its default (white), so the screen renders as `base.rgb * lightmap *
  light` — a flat blank/bright panel. **No shader change needed.**

## Goal & scope

Realize the SDK-created viewscreen object into a rendered bridge instance,
**mirroring step 3's `_realize_bridge_model`**. The screen renders
**faithfully-as-authored** (a flat blank panel — no live feed until 5c).

This drops `ViewScreenObject_Create` **and** the entire `BridgeSet.*` block off
the `[BRIDGE-STUB] SUMMARY`, leaving only `ZoomCameraObjectClass_Create` /
`ZoomCameraObjectClass_GetObject` for step 5a.

**Decision (A):** render the viewscreen faithfully as authored. The blank/bright
panel is the honest "on, no feed yet" state and gives 5c a clean seam (RTT just
replaces `u_base_color` for that surface). We do **not** force a deliberate
"off" look — that would be a throwaway visual requiring a C++/shader override.

**Out of scope:**

- 5a (zoom camera) and 5c (RTT / deferred item #26).
- The viewscreen station-menu / handler surface (`SetMenu`, `ToggleRemoteCam`,
  `AddPythonFuncHandlerForInstance`, `IsStaticOn`, `MenuDown`, …) — ~13 methods
  the SDK calls on the viewscreen for features we have not built.

**Pure Python — no C++/shader/CMake/rebuild.** `engine/appc/` stays headless
(no renderer import).

## Design

### 1. `engine/appc/bridge_set.py`

**`ViewScreenObject`** — promote from pure loud-stub to a real data object, but
**keep `_LoudStub` as the base** so the unbuilt menu/handler methods stay silent
no-ops. This is the step-3 `GetAnimNode` lesson: a bare data class would crash
any mission that calls `SetMenu`/`ToggleRemoteCam`/etc., because those lose the
catch-all `__getattr__` no-op. (Contrast `BridgeObjectClass`, which is *not* a
`_LoudStub` because its full method surface was known and bounded.)

```python
class ViewScreenObject(_LoudStub):
    """SDK viewscreen object. Core data is real (nif, render_instance, the
    RemoteCam/IsOn feed state consumed later by 5c RTT); the unbuilt
    station-menu/handler surface (SetMenu, ToggleRemoteCam,
    AddPythonFuncHandlerForInstance, IsStaticOn, MenuDown, ...) falls through
    _LoudStub.__getattr__ as a silent no-op so missions that touch it don't
    crash. The HOST reads this object after LoadBridge.Load and fills in
    render_instance (see host_loop._realize_viewscreen), mirroring
    BridgeObjectClass."""
    def __init__(self, nif):
        self.nif = nif
        self.render_instance = None    # host fills this in
        self._remote_cam = None
        self._is_on = 0
    def GetRemoteCam(self):      return self._remote_cam
    def SetRemoteCam(self, cam): self._remote_cam = cam
    def SetIsOn(self, on):       self._is_on = on
```

- **`ViewScreenObject_Create`** — drop the `stub_call` (the object is now real →
  off summary). Because `_LoudStub.__getattr__` never called `stub_call` (only
  the factory did), removing the factory's `stub_call` is sufficient to drop the
  symbol; the unbuilt methods remain silent.
- **`BridgeSet.GetViewScreen` / `SetViewScreen` / `GetConfig` / `SetConfig` /
  `IsSameConfig` / `DeleteCameraFromSet`** — drop all `stub_call`s; bodies stay
  exactly as-is (already correct plumbing the host/SDK consume). The whole
  `BridgeSet.*` block leaves the summary.

### 2. Host realization: `_realize_viewscreen`

New module-level function in `engine/host_loop.py`, a near-clone of
`_realize_bridge_model`, called from `_after_mission_loaded` **right after**
`_realize_bridge_model` (and before `_place_bridge_officers`):

```python
def _realize_viewscreen(controller, r) -> None:
    """Turn the SDK-created viewscreen object into a rendered bridge instance.

    Mirrors _realize_bridge_model: reads bridge.GetViewScreen() (set by the SDK's
    CreateBridgeModel -> ViewScreenObject_Create + SetViewScreen), resolves the
    NIF + env path the SDK pre-loaded via g_kModelManager.LoadModel, and creates
    a bridge-pass instance at identity. The screen renders faithfully-as-authored
    (a blank panel) until 5c/RTT feeds u_base_color from the tactical camera.

    Idempotent/leak-free (identical to _realize_bridge_model): same-config reuse
    (object already has render_instance) is a no-op; a fresh object (set rebuild
    via reset_sdk_globals) destroys the prior instance first. Config-driven —
    reads vs.nif, so Sovereign/EBridge viewscreens work with no name branching.
    """
    import App as _App
    bridge = _App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        return
    vs = bridge.GetViewScreen()
    if vs is None or not hasattr(vs, "nif"):
        return
    if vs.render_instance is not None:
        return                                       # same-config reuse

    if controller.viewscreen_instance is not None:
        try:
            r.destroy_instance(controller.viewscreen_instance)
        except Exception:
            pass
        controller.viewscreen_instance = None

    nif_abs = str(PROJECT_ROOT / "game" / vs.nif)
    env = _App.g_kModelManager.env_for(vs.nif)
    tex_abs = (str(PROJECT_ROOT / "game" / env) if env
               else str(PROJECT_ROOT / "game" / DBRIDGE_TEX_REL))

    handle = r.load_model(nif_abs, tex_abs)
    iid = r.create_bridge_instance(handle)
    r.set_world_transform(iid, IDENTITY_MAT4)

    vs.render_instance = iid
    controller.viewscreen_instance = iid
    controller.nif_to_handle[nif_abs] = handle
```

- Add `self.viewscreen_instance: Optional[Any] = None` to the controller, next
  to `self.bridge_instance`.
- Wire `_realize_viewscreen(controller, r)` into `_after_mission_loaded`
  immediately after `_realize_bridge_model(controller, r)`.
- **Identity transform** — see asset facts; the SDK relies on it.
- **`create_bridge_instance`** tags the instance for the bridge pass so it
  renders alongside the mesh + officers.
- **Config-driven** — `vs.nif` comes from the active `Bridge.<name>` config, so
  non-Galaxy viewscreens work by construction (not live-verified).

## Testing

Focused files only. **Never** run the full suite (>100 GB RAM, freezes macOS) —
warn subagents.

- **`tests/unit/test_realize_viewscreen.py`** (new) — fake-renderer idempotency
  matrix mirroring `test_realize_bridge_model.py`:
  - realize once → `load_model` / `create_bridge_instance` /
    `set_world_transform(IDENTITY)` called; instance harvested onto
    `vs.render_instance` **and** `controller.viewscreen_instance`;
  - same-config reuse (object already has `render_instance`) → no-op;
  - fresh object (`render_instance is None`) with a prior
    `controller.viewscreen_instance` → destroys the prior instance first;
  - missing / `None` viewscreen (or object without `.nif`) → returns cleanly.
- **`tests/unit/test_bridge_set_stubs.py`** (update) — assert
  `ViewScreenObject_Create` and the `BridgeSet.*` methods **no longer** fire
  `stub_call`; `ViewScreenObject` stores `nif` / `render_instance`, round-trips
  `SetRemoteCam`↔`GetRemoteCam` and `SetIsOn`; an unbuilt method (e.g.
  `SetMenu(...)`) still no-ops via the `_LoudStub` catch-all without raising.
- **`tests/integration/test_sdk_bridge_load.py`** (update) — after a real
  `Load("GalaxyBridge")`, `bridge.GetViewScreen()` returns a `ViewScreenObject`
  carrying `DBridgeViewScreen.nif`; `[BRIDGE-STUB] SUMMARY` no longer lists
  `ViewScreenObject_Create` or any `BridgeSet.*` entry — only
  `ZoomCameraObjectClass_*` remain.

## Verification, risks, rollback

- **Live verify (Mark drives):** launch `./build/dauntless`, enter bridge view —
  the front viewscreen surface renders as a blank panel where previously there
  was nothing. No crash; mesh + officers unchanged; stub summary shows only the
  two `ZoomCamera` symbols. No synthetic desktop input / full-screen capture.
- **Risks:**
  - (a) The blank panel may render bright-white/gray (default texture ×
    material emissive) rather than a pleasing "off" look — **accepted** under
    decision A; 5c replaces it.
  - (b) `create_bridge_instance` on the 1.5 KB single-trishape NIF is untested
    but uses the same loader as `DBridge.nif` — low risk.
  - (c) If "room screen" geometry is mis-aligned at identity, that is a NIF
    coordinate finding to **note**, not a transform to invent (we do not
    fabricate offsets).
- **No regression** to the SP1/SP2 renderer, `compose_officer_model`, or steps
  1–4: this only *adds* one bridge-pass instance; the officer/mesh paths are
  untouched.
- **Rollback:** drop the `_realize_viewscreen` call + revert `bridge_set.py`; no
  rebuild, no migration.

## Follow-ups (not this step)

- **5a** — SDK `ZoomCameraObjectClass` as the captain's-camera source of truth
  (note: `GalaxyBridge.ConfigureCharacters` overrides the camera Z to
  **61.934944** after `CreateBridgeModel` set 50.0, so the host's hardcoded
  `_BRIDGE_CAMERA_OFFSETS` z=50.0 is unfaithful to the final state).
- **5c** — viewscreen render-to-texture (deferred-work item #26); consumes the
  `SetRemoteCam`/`SetIsOn` state this step stores; unblocks item #25.
- **6** — verify extras/menus + live-verify non-Galaxy bridges (incl. their
  viewscreens, now config-driven).
