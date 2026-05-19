# Deferred: BridgeSet_Cast and ViewScreen shim

**Status:** deferred 2026-05-18. Decision: do not implement a `BridgeSet` subclass or `BridgeSet_Cast` shim right now. The harness profile will continue to record `BridgeSet_Cast` and its `.GetViewScreen().*` subtree as un-implemented engine surface until the bridge view POC lands. Resolution work is owned by [`docs/superpowers/specs/2026-05-11-bridge-view-poc-design.md`](../specs/2026-05-11-bridge-view-poc-design.md) and [`docs/superpowers/specs/2026-05-11-bridge-interior-render-design.md`](../specs/2026-05-11-bridge-interior-render-design.md).

## Context

The gameloop harness profile reports `BridgeSet_Cast` as the top remaining un-implemented engine surface after the [GridClass shim](2026-05-18-gridclass-debug-overlay.md) landed. 26 of 35 missions cast `g_kSetManager.GetSet("bridge")` to a `BridgeSet`; the call site is identical everywhere ([MissionLib.py:1050](../../../sdk/Build/scripts/MissionLib.py#L1050) is the canonical form):

```python
pSet = App.BridgeSet_Cast(App.g_kSetManager.GetSet("bridge"))
```

The cast is a downcast from generic `SetClass*` to the `BridgeSet` subclass so callers can reach bridge-specific methods on the returned object — primarily `GetViewScreen()`, `SetViewScreen()`, `SetConfig()`, `GetConfig()`, `IsSameConfig()` ([sdk App.py:4871-4888](../../../sdk/Build/scripts/App.py#L4871-L4888)). The viewscreen object itself ([sdk App.py:4821-4858](../../../sdk/Build/scripts/App.py#L4821-L4858)) carries the bulk of the runtime methods (`SetIsOn`, `SetRemoteCam`, `SetStaticIsOn`, `SetMenu`, etc.), which is why the harness shows a whole `BridgeSet_Cast().GetViewScreen().*` subtree under the root cast.

## Why we are not shimming this

Unlike `GridClass`, `BridgeSet_Cast` is **not** dead code. Mission scripts actively drive the viewscreen during warp-in/out, comm channel toggles, and cutscenes, and several callers (e.g. [WarpSequence.py:384](../../../sdk/Build/scripts/WarpSequence.py#L384)) do not guard `GetViewScreen()` against `None`. A minimum-effort `Cast → None` shim would crash those paths.

A "real `BridgeSet` subclass with a stub `ViewScreenObject`" shim is feasible (~50 lines in [`engine/appc/sets.py`](../../../engine/appc/sets.py) + [`engine/appc/objects.py`](../../../engine/appc/objects.py)) and was the obvious next step, but the bridge POC work is already specced and the shim's state model (`is_on`, `remote_cam_target`, `static_on`, `menu`) will be re-derived by that spec. Doing both means writing the same state machine twice and migrating callers when the renderer lands. Cleaner to wait and have the bridge POC own the data model from day one.

Cost of deferral: the harness profile keeps the BridgeSet rows. We can filter the report when other surfaces are under investigation.

## Resolution path

The bridge view POC ([`2026-05-11-bridge-view-poc-design.md`](../specs/2026-05-11-bridge-view-poc-design.md)) is the work that retires this entry. When that lands it should:

- Provide a real `BridgeSet(SetClass)` subclass in [`engine/appc/sets.py`](../../../engine/appc/sets.py) with `GetViewScreen`, `SetViewScreen`, `SetConfig`, `GetConfig`, `IsSameConfig`.
- Expose `BridgeSet_Cast` from [`App.py`](../../../App.py) returning the `BridgeSet` when the named set exists, `None` otherwise (matching the SWIG semantics).
- Replace the [LoadBridge.py shim](../../../LoadBridge.py) registration so `g_kSetManager.GetSet("bridge")` returns a `BridgeSet`, not a generic `SetClass`.
- Implement a `ViewScreenObject(ObjectClass)` with at minimum `SetIsOn`, `IsOn`, `SetRemoteCam`, `SetStaticIsOn`, `IsStaticOn`, `SetMenu`, `ClearMenu`, `AddPythonFuncHandlerForInstance`. Backed by the actual viewscreen render target produced by the bridge interior pass.

Acceptance check after that work: running `uv run python tools/gameloop_harness.py --profile` shows the `BridgeSet_Cast` subtree gone from the report, and the viewscreen-rendering smoke test in the POC spec passes.

## Revisit trigger

Re-evaluate if the bridge POC slips materially (e.g. blocked on interior-render dependencies for more than a sprint). In that case implement the stub-state shim (`BridgeSet` + `ViewScreenObject` recording on/off, remote-cam target, static state, menu) as an interim — same pattern as `GridClass` but with state instead of no-ops. The shim becomes a useful contract for the POC to consume rather than throwaway work.

## Files in scope (for the resolving work, not now)

| File | Relevance |
|---|---|
| [`engine/appc/sets.py`](../../../engine/appc/sets.py) | Add `BridgeSet(SetClass)` with bridge-specific methods |
| [`engine/appc/objects.py`](../../../engine/appc/objects.py) | Add `ViewScreenObject(ObjectClass)` |
| [`App.py`](../../../App.py) | Export `BridgeSet`, `ViewScreenObject`, `BridgeSet_Cast` |
| [`LoadBridge.py`](../../../LoadBridge.py) | Register a `BridgeSet` instead of generic `SetClass` |
| [`docs/superpowers/specs/2026-05-11-bridge-view-poc-design.md`](../specs/2026-05-11-bridge-view-poc-design.md) | Owns the resolution |
| [`docs/superpowers/specs/2026-05-11-bridge-interior-render-design.md`](../specs/2026-05-11-bridge-interior-render-design.md) | Renderer-side dependency |
