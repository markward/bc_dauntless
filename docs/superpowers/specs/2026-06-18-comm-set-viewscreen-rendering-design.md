# Comm-set viewscreen rendering (+ unified set realization)

**Date:** 2026-06-18
**Status:** Design — approved, pending spec review

## 1. Goal

Render BC comm scenes (a remote room + a hailing character) on the bridge
viewscreen, driven entirely by the SDK's `MissionLib.ViewscreenOn` /
`ViewscreenOff`. Today the viewscreen RTT shows only the forward space view; a
comm request is announced by the `CommRenderFlag` developer tripwire and
otherwise ignored.

Along the way, converge the player-bridge and comm-set rendering onto **one
generic set-realization path**, retiring the bridge-special realization
functions. This is the architecture decision (Approach "C"): the SDK setup for
the two kinds of set stays faithful and different, but our **renderer
realization** unifies.

### Guiding principle

The published SDK scripts drive everything — which set, NIF, camera, and
character load, and when (see memory `feedback_sdk_drives_everything`). The
engine's job is to honor the Appc surface those scripts call and realize
whatever they reference. No hardcoded mission/asset specifics (e.g.
`"StarbaseSet"` / `"Liu"`) as a starting point.

### Success criteria

- When a mission calls `ViewscreenOn(set, character)`, the named set's room +
  posed character render on the bridge viewscreen, framed by that set's
  `"maincamera"`, and `ViewscreenOff` returns the screen to the forward view.
- Concretely verifiable in E1M1, which sets up three comm sets at mission load
  (`StarbaseSet`/Liu, `DBridgeSet`/Zeiss, `EBridgeSet`/Martin via
  `SetupBridgeSet` + `SetupCharacter`) and hails them.
- The player bridge, viewscreen, officers, walk-on cutscene, and crew menus
  continue to work, now driven by the generic realization path.

### Out of scope (deferred)

- Static/"snow" overlay (`SetStaticTextureIconGroup` / `SetStaticIsOn`).
- Hail-face variations, viewscreen menus.
- `ViewOn`/`ViewOff` sound + transition polish.
- The pre-existing "lego head" character-head texturing bug
  (`project_bc_character_rigid_skinning`). The comm face will render with
  untextured heads until that separate bug is fixed; the pipeline here is
  considered correct regardless.

## 2. Background — how the SDK sets up each kind of set

The SDK does **not** unify the two at setup time; both converge to the same
renderable shape (geometry + ambient + a `"maincamera"` + characters).

**Comm set** (`MissionLib.SetupBridgeSet`, MissionLib.py:1453):
```
pSet = App.SetClass_Create()
g_kSetManager.AddSet(pSet, name)
pSet.CreateAmbientLight(1,1,1,19, "ambientlight1")
pSet.SetBackgroundModel(nif, 0,0,0)
pNiCamera = g_kModelManager.CloneCamera(nif)
# NiCamera present -> CameraObjectClass_CreateFromNiCamera(.., "maincamera"),
#   frustum halved; else CameraObjectClass_Create(coords, "maincamera")
pSet.AddCameraToSet(pCamera, "maincamera")
```
Characters added via `SetupCharacter(path, setName)` →
`module.CreateCharacter(pSet)`.

**Player bridge** (`LoadBridge.CreateAndPopulateBridgeSet`, LoadBridge.py:176):
```
pBridgeSet = App.BridgeSet_Create()
g_kSetManager.AddSet(pBridgeSet, "bridge")
pBridgeSet.CreateAmbientLight(1,1,1,0.7, "ambientlight1")
# bridge config script: BridgeObjectClass_Create(nif) + g_kModelManager.LoadModel,
#   ViewScreenObject_Create + SetViewScreen, ZoomCameraObjectClass "maincamera"
Bridge.Characters.<Name>.CreateCharacter(pBridgeSet)   # 5 crew + extras
```

**Viewscreen activation** (`MissionLib.ViewscreenOn`, MissionLib.py:1213):
gets the look-at set, grabs `pLookAtSet.GetCamera("maincamera")`, hides all its
characters except the named one, then `pViewScreen.SetRemoteCam(pMainCamera)` +
`pViewScreen.SetIsOn(1)`. `ViewscreenOff` sets the remote cam back to the player
camera.

## 3. Current engine state

- `engine/appc/sets.py` — `SetClass`. `SetBackgroundModel` / `CreateAmbientLight`
  currently fall through `__getattr__` to a `_RendererStub` (no-op). `GetCamera`
  / `AddCameraToSet` already store cameras. `BridgeSet` is a `SetClass` subclass
  (`engine/appc/bridge_set.py`).
- `engine/appc/bridge_set.py` — `BridgeObjectClass` (bridge NIF + transform +
  `render_instance`), `ViewScreenObject` (NIF + `render_instance` + remote-cam /
  IsOn state), `ZoomCameraObjectClass` ("maincamera"), `CameraObjectClass` (set
  camera from `CloneCamera` / explicit coords; pos/orient/frustum/near/far).
- `engine/host_loop.py` — `_realize_bridge_model` (reads `GetSet("bridge")
  .GetObject("bridge")`), `_realize_viewscreen` (reads `bridge.GetViewScreen()`),
  bridge officer placement (enumerates `CharacterClass` in the `"bridge"` set).
  All keyed to the name `"bridge"`. `_viewscreen_feed_on(vs)` gates the RTT;
  `CommRenderFlag.notice(vs)` is the dev tripwire.
- `native/src/scenegraph/include/scenegraph/instance.h` — `enum class Pass {
  Space=0, Bridge=1 }`.
- `native/src/host/host_bindings.cc::frame()` — RTT block renders the forward
  space view (`render_space(vcam, for_viewscreen=true)`) into `g_viewscreen_hdr`
  when `viewscreen_on`; `bridge_pass` samples it onto the viewscreen instance.
  (V-flip already fixed, 2026-06-18.)
- `native/src/renderer/bridge_pass.cc` — base + skinned bridge sub-passes.

## 4. Design

### 4.1 Unified realization layer

Introduce a generic host routine that realizes any named set:

```
realize_set(controller, r, set):
    # idempotent + leak-free, mirroring today's _realize_bridge_model:
    #   reuse when the carrier already has a render_instance; destroy prior
    #   instances on a fresh carrier / set rebuild.
    1. background geometry NIF:
         - bridge: BridgeObjectClass carrier (set.GetObject("bridge").nif)
         - comm:   set._background_model (recorded by SetBackgroundModel)
       -> load model, create render instance, tag with set name + Pass
    2. ambient: set._ambient (recorded by CreateAmbientLight) -> instance lighting
    3. characters: every CharacterClass in the set -> skinned render instances,
       placed by the existing CreateCharacter / placement-anim path, tagged with
       the set name
    4. viewscreen (bridge only): realize ViewScreenObject as today
```

`SetClass.SetBackgroundModel(nif, x, y, z)` and `CreateAmbientLight(r,g,b,d,name)`
stop being stubs: they record `_background_model` (nif + offset) and `_ambient`
on the `SetClass` so `realize_set` can read them. (Ambient keeps the existing
clamp on `CreateAmbientLight`'s 4th arg.)

`BridgeObjectClass` / `ViewScreenObject` remain as data carriers. The
bridge-special functions `_realize_bridge_model`, `_realize_viewscreen`, and the
bridge-only officer-placement loop are **replaced** by `realize_set` (the bridge
becomes "the set named `bridge`"). The viewscreen realization stays a
bridge-only sub-step of `realize_set` (only the bridge set has a
`ViewScreenObject`).

### 4.2 Passes & set tagging

Add `Comm = 2` to `scenegraph::Pass`. The player bridge realizes into
`Pass::Bridge`; comm sets realize into `Pass::Comm`. Each comm instance carries
its **owning set name** so the renderer can filter to a single active comm set
(E1M1 has three comm sets live simultaneously; only one shows at a time).

### 4.3 Camera

Each set's `"maincamera"` (`CameraObjectClass`: position, orientation `TGMatrix3`
column-vector, `_NiFrustum`, near/far) provides the comm view. Built already by
`CloneCamera` → `CameraObjectClass_CreateFromNiCamera` (frustum halved by the
SDK) for comm sets. The host builds a `scenegraph::Camera` from it (game units,
right-handed convention per CLAUDE.md).

### 4.4 Data flow

- **Mission load:** after `StartMission`, the host enumerates every set in
  `g_kSetManager` and `realize_set`s each. Bridge → main view; comm sets
  realized but not shown.
- **Per frame:** read the bridge `ViewScreenObject`. If `IsOn()` and
  `GetRemoteCam()` is a comm set's `maincamera`, Python resolves the owning set
  by scanning `g_kSetManager`'s sets for the one whose
  `GetCamera("maincamera")` *is* the remote-cam object (identity match), then
  passes that set's name + its camera to the host, which renders that set's
  `Pass::Comm` instances from the camera into `g_viewscreen_hdr`. A `CommRenderFlag`-
  style "is this a set maincamera vs the player camera" check distinguishes the
  comm case from the forward case. Otherwise fall back to the forward-space feed
  (remote cam is the player camera / off → existing behavior, or blank).
- The `CommRenderFlag` tripwire is retired (the path it warned about now exists).

### 4.5 Native render branch

In `host_bindings::frame()`, add a comm branch parallel to `render_space`:
render the active comm set's `Pass::Comm` instances (room geometry + skinned
characters) from the comm camera into the viewscreen HDR target, lit by that
set's ambient, reusing the bridge-pass shaders filtered to the active set name.
The existing V-flip on the viewscreen feed applies unchanged. New host binding(s)
convey the active comm set id + camera (e.g. `set_viewscreen_comm_source(name,
camera)` / clear).

## 5. Components & boundaries

| Unit | Responsibility | Depends on |
|---|---|---|
| `SetClass.SetBackgroundModel`/`CreateAmbientLight` | record NIF + ambient on the set | — |
| `realize_set` (host_loop) | turn any set into renderable instances (geometry + ambient + characters [+ viewscreen for bridge]), idempotent/leak-free | SetClass data, renderer wrapper, model manager |
| `Pass::Comm` + set-name tag (scenegraph) | separate comm instances; allow per-set filtering | instance.h |
| comm render branch (host_bindings) | render active comm set from its maincamera into the viewscreen HDR target | bridge pass shaders, camera |
| viewscreen-feed selection (host_loop) | choose comm-set feed vs forward feed from the remote cam | ViewScreenObject, CameraObjectClass |

## 6. Testing

**Python (pytest):**
- `realize_set` realizes geometry + ambient + characters + camera for a generic
  fake set; idempotent (same-config reuse is a no-op) and leak-free (fresh
  carrier destroys prior instances) — adapt the existing bridge-realization
  tests onto the generic path.
- `SetClass.SetBackgroundModel` / `CreateAmbientLight` record values (no longer
  stubs).
- A comm set built via `SetBackgroundModel` + `CreateCharacter` realizes its
  room + character.
- Viewscreen-feed selection returns the active comm set + camera when the bridge
  `ViewScreenObject` has a set `maincamera` as remote cam, and the forward/blank
  fallback otherwise; `ViewscreenOff` reverts.
- Regression: player bridge still realizes (officers, viewscreen) via the generic
  path.

**Native (renderer_tests, gtest):**
- A `Pass::Comm` render-from-camera test: instances tagged with a set name
  render into an offscreen target from a supplied camera (mirror the existing
  bridge / skinned render tests).
- Pass partitioning counts `Pass::Comm` instances separately and filters by set
  name.

## 7. Risks

- **Bridge refactor blast radius.** `realize_set` replaces working bridge-specific
  code that the walk-on cutscene and crew menus sit near. Mitigation: keep the
  `BridgeObjectClass` / `ViewScreenObject` data carriers, adapt rather than delete
  the bridge tests, and verify the bridge end-to-end before relying on the comm
  path. (The pre-existing renderer_tests GL-readback failures when run as one
  batch are unrelated — they pass individually.)
- **Multiple live comm sets.** E1M1 realizes three at once; the set-name tag +
  active-set filter prevents cross-rendering. Build verifies only the
  remote-cam's set draws.
- **Shader rebuild gotcha.** Any `.vert`/`.frag` change needs a cmake reconfigure,
  not just `--build` (memory `feedback_shader_rebuild`). Native `host_bindings.cc`
  edits need a `dauntless` rebuild (memory `feedback_host_bindings_build_target`).
