# Object emitter emission — design

**Status:** Approved 2026-05-12
**Scope:** Plumbing + `LaunchObject` resolves the emitter and records a structured no-op; spawning real Shuttle/Probe/Decoy objects is out of scope.

## Problem

SDK ship hardpoint scripts (e.g. [sdk/Build/scripts/ships/Hardpoints/sovereign.py:888-931](../../../sdk/Build/scripts/ships/Hardpoints/sovereign.py)) declare emitter templates for shuttle bays, probe launchers, and decoy launchers. Mission scripts and the bridge science menu fire `App.TGScriptAction_Create("Actions.ShipScriptActions", "LaunchObject", shipID, name, OEP_*)` to launch objects from those emitters (e.g. [Bridge/ScienceMenuHandlers.py:426](../../../sdk/Build/scripts/Bridge/ScienceMenuHandlers.py), [Maelstrom/Episode6/E6M3/E6M3.py:2031](../../../sdk/Build/scripts/Maelstrom/Episode6/E6M3/E6M3.py)).

In the engine today:

- `App.py` imports the `ObjectEmitterProperty` class but does *not* import an `ObjectEmitterProperty_Create` factory ([App.py:106-133](../../../App.py)). The class exists only so `GetPropertiesByType(App.CT_OBJECT_EMITTER_PROPERTY)` has a real type to feed `isinstance()`.
- Hardpoint calls fall through `App.__getattr__` ([App.py:713](../../../App.py)) into `_NamedStub`, which records the call name and returns chained stubs. Every emitter's `SetOrientation`/`SetPosition`/`SetEmittedObjectType` data is silently discarded.
- `RegisterLocalTemplate(emitter)` keys `_local` by `prop.GetName()`, which on a `_NamedStub` returns another `_NamedStub` hashed by `id()` — so `FindByName("Probe Launcher", LOCAL_TEMPLATES)` always returns `None`.
- The gameloop harness records 451 calls each, across 30 missions, for the five chained stubs:
  ```
  ObjectEmitterProperty_Create                                30   451
  ObjectEmitterProperty_Create().GetName                       30   451
  ObjectEmitterProperty_Create().SetEmittedObjectType          30   451
  ObjectEmitterProperty_Create().SetOrientation                30   451
  ObjectEmitterProperty_Create().SetPosition                   30   451
  ```
  Confirming that every SDK emitter block executes its standard 5-call recipe (Create + 3 setters + `GetName` from `RegisterLocalTemplate`) but lands in stub-tracker land.

The stale class docstring at [engine/appc/properties.py:88-95](../../../engine/appc/properties.py) frames this as a deliberate Phase-1 deferral. Phase 2 is now active.

## Goals

1. Eliminate the five `ObjectEmitterProperty_Create*` stub-tracker rows.
2. Make `g_kModelPropertyManager.FindByNameAndType(emitter_name, CT_OBJECT_EMITTER_PROPERTY, ...)` return the registered template.
3. Make `App.TGScriptAction_Create("Actions.ShipScriptActions", "LaunchObject", ...)` resolve the correct emitter, compute the world-frame position and orientation correctly, and record the event in a queryable recorder.
4. Provide tests that lock the behaviour in (unit + integration + harness regression).

## Non-goals

- Spawning real `Shuttle`, `Probe`, or `Decoy` `ObjectClass` instances. SDK `LoadSpaceHelper.CreateShip` is not invoked by the hook.
- Renderer-side display of emitted objects.
- `pSensors.AddProbe()` integration on the sensor subsystem.
- Collision-disable between launching ship and emitted object.
- Player-facing bridge UI changes.

These are tracked as follow-on work once the structured-recording surface is verified.

## Architecture (three layers)

### Layer 1 — Real `ObjectEmitterProperty` data property

In [engine/appc/properties.py](../../../engine/appc/properties.py):

```python
class ObjectEmitterProperty(PositionOrientationProperty):
    OEP_UNKNOWN = 0
    OEP_SHUTTLE = 1
    OEP_PROBE   = 2
    OEP_DECOY   = 3

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._forward = None
        self._up      = None
        self._right   = None
        self._position = None
        self._emitted_type = self.OEP_UNKNOWN

    def SetOrientation(self, fwd, up, right):
        self._forward = _copy_point(fwd)
        self._up      = _copy_point(up)
        self._right   = _copy_point(right)

    def GetForward(self):  return _copy_point(self._forward)
    def GetUp(self):       return _copy_point(self._up)
    def GetRight(self):    return _copy_point(self._right)

    def SetPosition(self, p):           self._position = _copy_point(p)
    def GetPosition(self):              return _copy_point(self._position)
    def SetEmittedObjectType(self, t):  self._emitted_type = int(t)
    def GetEmittedObjectType(self):     return self._emitted_type
```

`_copy_point(p)` returns a fresh `TGPoint3(p.x, p.y, p.z)` so callers can `MultMatrixLeft` without mutating the template — matches SDK semantics.

Module-level factories at the bottom of the file:

```python
def ObjectEmitterProperty_Create(name):
    return ObjectEmitterProperty(name)

def ObjectEmitterProperty_Cast(obj):
    import App
    if isinstance(obj, App._NamedStub):
        return None
    return obj if isinstance(obj, ObjectEmitterProperty) else None
```

The stale "no instances produced by Phase 1" docstring is removed.

[App.py](../../../App.py) imports `ObjectEmitterProperty_Create` and `ObjectEmitterProperty_Cast` alongside the sibling factories in the [App.py:106-133](../../../App.py) block.

### Layer 2 — Emission recorder

A new singleton in [App.py](../../../App.py), placed next to `_stub_tracker` and `_color_consumer_tracker`:

```python
class _EmissionRecorder:
    def __init__(self):
        self._enabled = False
        self._mission = None
        self._events = []

    def enable(self):  self._enabled = True
    def disable(self): self._enabled = False
    def is_enabled(self): return self._enabled

    def set_mission(self, name):  self._mission = name
    def reset_mission(self):       self._mission = None

    def record(self, ship_id, emitter_name, emitter_type,
               world_position, world_forward, world_up):
        if not self._enabled:
            return
        self._events.append({
            "mission": self._mission,
            "ship_id": ship_id,
            "emitter_name": emitter_name,
            "emitter_type": emitter_type,
            "world_position": (world_position.x, world_position.y, world_position.z),
            "world_forward":  (world_forward.x,  world_forward.y,  world_forward.z),
            "world_up":       (world_up.x,       world_up.y,       world_up.z),
        })

    def events(self): return list(self._events)
    def clear(self):  self._events = []

_emission_recorder = _EmissionRecorder()
```

Disabled by default. Harness/tests opt in via `App._emission_recorder.enable()`. Stored values are tuples (not live `TGPoint3`) so events survive per-mission cleanup; the recorder lives on the persistent App module ([tools/gameloop_harness.py:23](../../../tools/gameloop_harness.py)).

### Layer 3 — `LaunchObject` hook (structured no-op)

A new module [engine/appc/emission.py](../../../engine/appc/emission.py) provides the hook:

```python
def _launch_object(pAction, iShipID, pcName, iType):
    import App
    pShip = App.ShipClass_Cast(App.TGObject_GetTGObjectPtr(iShipID))
    if pShip is None:
        return 0

    pPropSet = pShip.GetPropertySet()
    pEmitterInstanceList = pPropSet.GetPropertiesByType(App.CT_OBJECT_EMITTER_PROPERTY)

    pEmitterInstanceList.TGBeginIteration()
    iNumItems = pEmitterInstanceList.TGGetNumItems()
    pLaunchProperty = None
    for _ in range(iNumItems):
        pInstance = pEmitterInstanceList.TGGetNext()
        pProperty = App.ObjectEmitterProperty_Cast(pInstance.GetProperty())
        if pProperty is not None and pProperty.GetEmittedObjectType() == iType:
            pLaunchProperty = pProperty
            break
    pEmitterInstanceList.TGDoneIterating()
    pEmitterInstanceList.TGDestroy()

    if pLaunchProperty is None:
        return 0

    pRotation = pShip.GetWorldRotation()
    pPosition = pLaunchProperty.GetPosition()
    pPosition.MultMatrixLeft(pRotation)
    pPosition.Add(pShip.GetWorldLocation())

    pFwd = pLaunchProperty.GetForward()
    pUp  = pLaunchProperty.GetUp()
    pFwd.MultMatrixLeft(pRotation)
    pUp.MultMatrixLeft(pRotation)

    App._emission_recorder.record(
        iShipID, pLaunchProperty.GetName(), iType,
        pPosition, pFwd, pUp,
    )
    return 0


def install_launch_object_hook():
    import Actions.ShipScriptActions as _ssa
    _ssa.LaunchObject = _launch_object
```

Mirrors SDK [Actions/ShipScriptActions.py:441-522](../../../sdk/Build/scripts/Actions/ShipScriptActions.py) up to and including the world-transform math, then records instead of spawning. Idempotent — calling `install_launch_object_hook()` twice replaces the same slot.

~~`tools/mission_harness.setup_sdk()` calls `install_launch_object_hook()`~~ **Corrected 2026-10-07:** `setup_sdk()` is shared with the live host (`engine/host_loop._setup_sdk`), so installing the hook there made the real game's Launch Probe / shuttles / decoys spawn nothing. The hook is now harness-only: `tools/mission_harness.install_emission_recorder()`, called by the mission-harness and game-loop-harness `main()`s after `setup_sdk()` (it also adds the hooked module to the run baseline so it survives `purge_run_modules`). Guarded by `tests/unit/test_emission_hook.py::test_host_sdk_setup_leaves_the_sdk_launch_object`.

## Test plan

### Unit tests — [tests/unit/test_object_emitter_property.py](../../../tests/unit/test_object_emitter_property.py)

1. `ObjectEmitterProperty_Create("name")` returns an `ObjectEmitterProperty` with `GetName() == "name"`.
2. `ObjectEmitterProperty_Cast` accepts an emitter (returns it), rejects `_NamedStub`, rejects unrelated `TGModelProperty` subclasses (returns `None`).
3. `OEP_UNKNOWN/OEP_SHUTTLE/OEP_PROBE/OEP_DECOY` are integers and pairwise distinct.
4. `SetOrientation(fwd, up, right)` then `GetForward/Up/Right()` round-trip values; mutating a getter result does not change the template.
5. `SetPosition(p)` / `GetPosition()` round-trip with copy semantics.
6. `SetEmittedObjectType(t)` / `GetEmittedObjectType()` round-trip.
7. **Profile regression:** import [sdk/Build/scripts/ships/Hardpoints/sovereign.py](../../../sdk/Build/scripts/ships/Hardpoints/sovereign.py) inside a fresh `_stub_tracker.set_mission("test")` window; assert no `ObjectEmitterProperty_Create*` entries appear in `_stub_tracker.report()`.
8. `g_kModelPropertyManager.RegisterLocalTemplate(emitter)` then `FindByName("Probe Launcher", LOCAL_TEMPLATES)` returns the same instance (proves dict key is now a real string).

### Integration tests — [tests/integration/test_emission_hook.py](../../../tests/integration/test_emission_hook.py)

Build a minimal scenario: place a Sovereign at a known world position with a known rotation matrix, install the hook, call the hooked `LaunchObject(None, ship.GetObjID(), "test-shuttle", App.ObjectEmitterProperty.OEP_SHUTTLE)` directly.

1. Exactly one event in `App._emission_recorder.events()`.
2. `emitter_type == OEP_SHUTTLE`, `emitter_name == "Shuttle Bay"` (sovereign hardpoint name).
3. `world_position` equals `ship.GetWorldLocation() + R · emitter.GetPosition()` computed independently in the test, within `1e-6` tolerance per component.
4. `world_forward` equals `R · emitter.GetForward()`; `world_up` equals `R · emitter.GetUp()`; same tolerance.

Variants:
- `OEP_PROBE` resolves to sovereign's `ProbeLauncher`, not its `ShuttleBay`.
- `OEP_DECOY` resolves to sovereign's `Decoylauncher`.
- Ship with only a shuttle bay asked for `OEP_PROBE` → no event recorded, function returns 0.
- Recorder disabled → emitter resolution still runs (no exception) but `events()` stays empty.

### Hook idempotence — [tests/unit/test_emission_hook.py](../../../tests/unit/test_emission_hook.py)

`install_launch_object_hook()` called twice: `Actions.ShipScriptActions.LaunchObject` is the wrapper exactly once (second call replaces, doesn't compose).

### Harness regression — extend [tests/integration/test_gameloop_harness.py](../../../tests/integration/test_gameloop_harness.py)

Run the gameloop harness with `profile=True`, assert that no row whose name starts with `ObjectEmitterProperty_Create` appears in `_stub_tracker.report()`. Confirms the change holds across all ~73 missions.

## File changes summary

| File | Change |
|---|---|
| [engine/appc/properties.py](../../../engine/appc/properties.py) | `ObjectEmitterProperty` gains storage + accessors + OEP_* constants; module-level `ObjectEmitterProperty_Create` and `ObjectEmitterProperty_Cast` factories; stale docstring removed |
| [App.py](../../../App.py) | Import the two new factories; add `_EmissionRecorder` singleton next to `_stub_tracker` |
| [engine/appc/emission.py](../../../engine/appc/emission.py) | New module: `_launch_object` wrapper + `install_launch_object_hook()` |
| [tools/mission_harness.py](../../../tools/mission_harness.py) | `install_emission_recorder()` (harness-only, called by the harness `main()`s) installs the hook — never `setup_sdk()` (corrected 2026-10-07) |
| [tests/unit/test_object_emitter_property.py](../../../tests/unit/test_object_emitter_property.py) | New: unit tests 1-8 above |
| [tests/integration/test_emission_hook.py](../../../tests/integration/test_emission_hook.py) | New: integration scenarios above |
| [tests/unit/test_emission_hook.py](../../../tests/unit/test_emission_hook.py) | New: hook idempotence |
| [tests/integration/test_gameloop_harness.py](../../../tests/integration/test_gameloop_harness.py) | Extend: assert no `ObjectEmitterProperty_Create*` rows in profile |

## Open questions

None. Follow-on work (real spawning, sensor probe registration, collision-disable, renderer-side rendering of emitted objects) is explicitly out of scope and will be tracked separately once this lands and the recording surface is verified across the harness.
