# SDK-Driven Bridge Mesh (Step 3) — Design

**Date:** 2026-06-15
**Status:** Approved (design); plan pending
**Parent:** `docs/superpowers/specs/2026-06-15-sdk-driven-bridge-init-design.md` (spec step 3)
**Builds on:** steps 1–2 (`docs/superpowers/plans/2026-06-15-sdk-driven-bridge-init.md`, merged to main)

## Problem

Steps 1–2 made bridge **initialization** SDK-driven: the real
`sdk/Build/scripts/LoadBridge.py::Load(name)` runs end-to-end against loud,
control-flow-correct stubs in `engine/appc/bridge_set.py`. But the bridge
**mesh on screen** still does not come from that SDK path. Two stubs are no-ops:

- `App.g_kModelManager.LoadModel(nif, None, envpath)` — records nothing, renders
  nothing.
- `App.BridgeObjectClass_Create(nif)` — returns a `_LoudStub` that draws nothing.

The interior the player actually sees comes from a **separate eager fallback**
in `engine/host_loop.py` (~lines 2091–2105): the host loads `DBRIDGE_NIF_REL`
and calls `r.create_bridge_instance(...)` directly at startup, independent of the
SDK. So `Bridge/GalaxyBridge.py::CreateBridgeModel` creates a logical bridge
object that renders nothing, while a parallel host load renders the geometry.

## Goal

Make the SDK-created `"bridge"` set object produce the **actual** render
instance, and delete the eager fallback so the SDK is the single source of the
bridge mesh. After step 3:

- `BridgeObjectClass_Create` and `g_kModelManager.LoadModel` drop off the
  `*** [BRIDGE-STUB] SUMMARY`.
- The bridge interior on screen is the instance created from the SDK's bridge
  object.
- Mesh selection is **config-driven** (read from the bridge object the SDK
  config script created), so EBridge / SovereignBridge are supported with no
  bridge-name branching — strictly better than the deleted `_BRIDGE_NIF_MAP`.

Out of scope (later steps / separate bugs): officer placement (step 4),
viewscreen + camera (step 5), and the officer-head "lego" rendering bug.

## What the SDK actually calls

`Bridge/GalaxyBridge.py::CreateBridgeModel(pBridgeSet)`:

```python
iDetail  = App.g_kImageManager.GetImageDetail()
pcEnvPath = "data/Models/Sets/DBridge/" + ["Low/","Medium/","High/"][iDetail]

App.g_kModelManager.LoadModel("data/Models/Sets/DBridge/DBridge.nif", None, pcEnvPath)
App.g_kModelManager.LoadModel("data/Models/Sets/DBridge/DBridgeViewScreen.nif", None, pcEnvPath)
...
pBridgeObject = App.BridgeObjectClass_Create("data/Models/Sets/DBridge/DBridge.nif")
pBridgeSet.AddObjectToSet(pBridgeObject, "bridge")
pBridgeObject.SetTranslateXYZ(0.0, 0.0, 0.0)
pBridgeObject.SetAngleAxisRotation(0.0, 1.0, 0.0, 0.0)
pPropertySet = pBridgeObject.GetPropertySet()   # DBridgeProperties hardpoints
```

Key facts that shape the design:

- The texture **env/detail path** is passed to `LoadModel`, **not** to
  `BridgeObjectClass_Create`. So the env path naturally flows through
  `LoadModel`; the bridge object only carries the NIF path.
- `LoadBridge.Load` runs per mission load. **Same config → returns early**
  (reuses the existing bridge object). **Different config →
  `DeleteObjectFromSet("bridge")` then recreate.** Realization must be
  idempotent and destroy the prior instance on a real config change or
  set rebuild.
- `controller.bridge_instance` is only ever *assigned* in `host_loop` (never
  read for drawing): `create_bridge_instance` = `create_instance` +
  `set_pass(Bridge)` in `host_bindings.cc`, registering the mesh into the C++
  bridge pass internally. `destroy_instance` works on a bridge-tagged instance
  like any other. So step 3 reduces to: get `create_bridge_instance` called
  from the SDK object, and harvest/own the iid on the controller.

## Architecture & layering decision

`engine/appc/` is the headless Appc shim and imports nothing host-side;
`engine/renderer.py` hard-imports `_dauntless_host` (absent under pytest). So
**the renderer call lives host-side, not in the appc stubs.** The SDK-created
bridge object stays a pure, headless data object; the host reads it after
`Load` and realizes the render instance. This keeps `engine/appc` fully
testable headless and keeps rendering where it belongs.

(Decisions confirmed with Mark: *host harvests*; *LoadModel records env path*;
*config-agnostic mesh selection, defer non-Galaxy live verify*.)

## Components

### `engine/appc/bridge_set.py` — two stubs become real

**`ModelManager.LoadModel(path, a=None, env=None)`** → real, pure recording:

```python
class ModelManager:
    def __init__(self):
        self._env = {}                     # nif path -> texture/env path

    def LoadModel(self, path, a=None, env=None):
        # Real (no stub_call): our renderer loads lazily at instance creation
        # host-side, so LoadModel's faithful equivalent is to remember the
        # texture/env path the host should search when it realizes this NIF.
        self._env[path] = env
        return None

    def env_for(self, path):
        return self._env.get(path)
```

It loads **nothing** into the renderer itself. Officer/viewscreen NIF env paths
get recorded harmlessly and are simply never realized in step 3.

**`BridgeObjectClass`** → real, pure object:

```python
class BridgeObjectClass:
    def __init__(self, nif):
        self.nif = nif
        self.translate = (0.0, 0.0, 0.0)
        self.rotation = (0.0, 1.0, 0.0, 0.0)   # angle, x, y, z
        self.render_instance = None            # host fills this in
        self._property_set = _LoudStub()        # DBridgeProperties hardpoints (later)

    def GetPropertySet(self):
        return self._property_set

    def SetTranslateXYZ(self, x, y, z):
        self.translate = (x, y, z)

    def SetAngleAxisRotation(self, a, x, y, z):
        self.rotation = (a, x, y, z)


def BridgeObjectClass_Create(nif):
    return BridgeObjectClass(nif)              # no stub_call -> off summary
```

It is **no longer** a `_LoudStub` subclass: the SDK only calls
`SetTranslateXYZ`, `SetAngleAxisRotation`, and `GetPropertySet`, all defined
above. (`GetPropertySet` keeps returning a `_LoudStub` so
`DBridgeProperties.LoadPropertySet(pPropertySet)` still runs — hardpoints are a
later step.)

**Unchanged (still loud stubs — steps 4–6):** `ViewScreenObject` /
`ViewScreenObject_Create`, `ZoomCameraObjectClass` / `_Create` / `_GetObject`,
`BridgeSet`'s config/viewscreen/camera-delete methods. These remain on the
summary, which is correct.

### `engine/host_loop.py` — host harvest + delete eager fallback

New helper, called from `_after_mission_loaded` (which already runs on the
initial load **and** every mission swap, after the SDK `Load` has run):

```python
def _realize_bridge_model(controller, r):
    """Turn the SDK-created 'bridge' set object into the rendered instance.
    Idempotent: same-config reuse is a no-op; a config change / set rebuild
    destroys the prior instance first."""
    import App as _App
    bridge = _App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        return
    obj = bridge.GetObject("bridge")
    if obj is None or not hasattr(obj, "nif"):
        return                                  # no SDK bridge object yet
    if obj.render_instance is not None:
        return                                  # same-config reuse

    if controller.bridge_instance is not None:
        try:
            r.destroy_instance(controller.bridge_instance)
        except Exception:
            pass
        controller.bridge_instance = None

    nif_abs = str(PROJECT_ROOT / "game" / obj.nif)
    env = _App.g_kModelManager.env_for(obj.nif)
    tex_abs = (str(PROJECT_ROOT / "game" / env) if env
               else str(PROJECT_ROOT / "game" / DBRIDGE_TEX_REL))

    handle = r.load_model(nif_abs, tex_abs)
    iid = r.create_bridge_instance(handle)
    r.set_world_transform(iid, IDENTITY_MAT4)

    obj.render_instance = iid
    controller.bridge_instance = iid
    controller.nif_to_handle[nif_abs] = handle
    controller.current_bridge_nif_abs = nif_abs
```

`IDENTITY_MAT4` is hoisted to module scope (it currently lives inline in the
deleted eager block; the bridge pass camera works in bridge-local frame, so the
bridge's world position is irrelevant — identity is correct).

**Deleted:** the eager block at host_loop.py:2091–2105 (the startup
`r.load_model` / `create_bridge_instance` fallback). `controller.bridge_instance`
starts `None`; `_realize_bridge_model` populates it on first load.

> Note: `obj.nif` is the game-relative path the SDK passed
> (`data/Models/Sets/DBridge/DBridge.nif`). The macOS filesystem is
> case-insensitive, so this resolves against the on-disk `Dbridge.NIF`. No
> bridge-name branching — `obj.nif` is whatever the active `Bridge.<name>`
> config script set, so EBridge / SovereignBridge work automatically.

## Data flow

```
mission load → loader.load() → StartMission → LoadBridge.Load(name)   [SDK]
    → CreateBridgeModel(set)
        → g_kModelManager.LoadModel(nif, None, envpath)   [records env path]
        → BridgeObjectClass_Create(nif)                   [pure object]
        → AddObjectToSet(obj, "bridge")                   [real SetClass]
_after_mission_loaded():
    → _realize_bridge_model(controller, r)                [HOST: load + create_bridge_instance]
    → dump_stub_summary()                                  [no longer lists the two symbols]
```

## Lifecycle / idempotency matrix

| Situation | `GetSet("bridge")` | `obj.render_instance` | Action |
|---|---|---|---|
| First load | new set, new obj | `None` | create instance |
| Swap, same config | persists | set | no-op (reuse) |
| Swap, different config | persists, obj replaced | `None` | destroy prior `controller.bridge_instance`, create new |
| Swap, set manager cleared | new set, new obj | `None` | destroy prior `controller.bridge_instance`, create new |

The rule "create iff `obj.render_instance is None`, destroying any prior
`controller.bridge_instance` first" covers every row regardless of whether the
host clears the set manager between missions.

## Error handling

- Missing bridge set / object → `_realize_bridge_model` returns quietly (the
  loud stub summary already flags an incomplete SDK path).
- `destroy_instance` of a prior instance is wrapped so a stale/invalid id can't
  break a swap.
- `load_model` raising (missing NIF) propagates as today's eager block did —
  loudly, not silently — so a bad asset path is visible.

## Testing

Focused subsets only — **never** the full suite (>100 GB RAM, freezes macOS).

- **Unit** `tests/unit/test_bridge_set_stubs.py` (update):
  - `LoadModel` / `BridgeObjectClass_Create` are **absent** from `st.fired()`.
  - `ModelManager.LoadModel` records and `env_for(path)` round-trips.
  - `BridgeObjectClass.SetTranslateXYZ` / `SetAngleAxisRotation` record;
    `GetPropertySet()` is truthy; `render_instance` defaults `None`.
- **Integration** `tests/integration/test_sdk_bridge_load.py` (extend):
  - after `Load("GalaxyBridge")`, `bridge.GetObject("bridge")` is a
    `BridgeObjectClass` whose `.nif` ends `DBridge.nif`.
  - the summary no longer lists `BridgeObjectClass_Create` /
    `g_kModelManager.LoadModel`.
- **Host realization** (new, with a fake renderer so it runs headless):
  `_realize_bridge_model` with a fake `r` recording calls — asserts
  `load_model` + `create_bridge_instance` fire once on first call, no-op on the
  second (reuse), and `destroy_instance` fires when a fresh object replaces a
  prior instance.
- **C++:** untouched; existing skinned-bridge tests stay green (no rebuild
  needed — no `host_bindings.cc`/shader/CMake change in step 3).
- **Live (Mark):** GalaxyBridge interior renders from the SDK path; the summary
  drops the two symbols; no synthetic input / full-screen capture.

## Caveat

Non-Galaxy bridges (EBridge / SovereignBridge) are supported by construction
(config-agnostic mesh read) but are **not** live-verified in step 3 — a
follow-on confirms they render. Officer placement still uses the existing
`assemble_officer` path until step 4.
