# SDK-Driven Bridge Initialization — Design

**Date:** 2026-06-15
**Status:** Approved (design); implementation pending plan
**Supersedes:** the hand-rolled bridge-crew/placement shortcut (SP3 placement layer)

## Problem

Bridge initialization is currently a Phase-1/2 **shortcut**, not the real game
sequence:

- `LoadBridge._BRIDGE_CREW` — a hardcoded GalaxyBridge-only roster.
- `populate_bridge_crew` — builds that roster directly.
- `engine/bridge_officers.py::place_officers` / `_place_one` / `resolve_placement`
  / `_BRIDGE_IDENTITY_MAT4` — an invented placement transform (with an X-flip).
- `native/src/renderer/placement_map.{h,cc}` — an invented location→clip table.
- `engine/host_loop.py::_place_bridge_officers` post-load hook + `_BRIDGE_NIF_MAP`.

The real game runs:

```
LoadBridge.Load(name)
  → CreateAndPopulateBridgeSet()        # BridgeSet, ambient light, character menus,
                                        # 5 standard crew, 3 random extras
  → __import__("Bridge." + name)
      → CreateBridgeModel(set)          # bridge NIF + viewscreen + bridge object + camera
      → ConfigureCharacters(set)        # Cast each officer, ConfigureForGalaxy (placement)
      → PreloadAnimations()
```

The shortcut can't handle non-Galaxy bridges, skips the extras / viewscreen /
camera / `CreateBridgeModel`, only partially does `ConfigureCharacters`, and —
critically — is an **uncontrolled variable**: we can't rule out the shortcut
itself causing the wrong/misplaced/odd characters we see on screen. Mission
scripts also add **guests** (e.g. Maelstrom: `SetLocation(...)` + a guest chair)
that the shortcut never runs.

## Goal

Make bridge initialization **SDK-driven**: route to the real
`sdk/Build/scripts/LoadBridge.py` and let its transitive sequence run. Stub the
missing Appc surface so the sequence runs end-to-end first, then replace stubs
with faithful behavior one at a time until the renderer consumes the resulting
set objects (bridge mesh, characters, camera) instead of parallel-loading them
via the shortcut.

## Keep / Replace decision (do NOT revert SP1/SP2)

**KEEP** (foundation-independent; the shortcut never touched it):
- The SP1 skinned render pipeline + SP2 GPU bone-palette skinning: skinned
  shader, `build_bone_palette` / inverse-bind, `sample_pose`, per-frame palette,
  and the correctness fixes (bind-model vertex bake, `u_model = inst.world`,
  head-subtree graft, clip-rest-pose base, skinned-pass culling-off).
- `compose_officer_model` (body + head graft + per-officer texture override).

**REPLACE** (delete, not git-revert):
- `_BRIDGE_CREW`, the hardcoded part of `populate_bridge_crew`, `bridge_officers()`,
  our `Load()`.
- `engine/bridge_officers.py::place_officers` / `_place_one` / `resolve_placement`
  / `_BRIDGE_IDENTITY_MAT4`.
- `native/src/renderer/placement_map.{h,cc}`.
- `engine/host_loop.py::_place_bridge_officers` + `_BRIDGE_NIF_MAP`.

## Architecture

Our root `LoadBridge.py` currently **shadows** the SDK's `LoadBridge.py`
(`tests/conftest.py::_SDKFinder` checks `PROJECT_ROOT` before `sdk/`). The pivot:
stop shadowing the bridge-load logic — let the real
`sdk/Build/scripts/LoadBridge.py::Load(name)` run. To make it run without
crashing, add the missing Appc symbols as **loud stubs** in `engine/appc/`,
registered into `App.py` alongside the existing managers. The existing
`SetClass` / lights / character-creation code is reused unchanged.

### Appc surface inventory

**Already implemented** (reuse as-is):
`g_kSetManager` + `SetClass`/`SetManager` (`engine/appc/sets.py`),
`CreateAmbientLight` + bridge-set helpers (`engine/appc/lights.py`),
`AddCameraToSet` (`sets.py`), `CharacterClass_Create`, `g_kImageManager`,
`g_kModelPropertyManager`, `engine/appc/placement.py`.

**Missing** (need loud stubs, then faithful implementation):
`BridgeSet_Create` / `BridgeSet_Cast` + `BridgeSet` methods (`IsSameConfig`,
`GetConfig`/`SetConfig`, `GetViewScreen`/`SetViewScreen`), `BridgeObjectClass_Create`,
`ViewScreenObject_Create`, `ZoomCameraObjectClass_Create`, `GetNamedCameraMode`,
`PushCameraMode`, `g_kModelManager`.

## Components

### `engine/appc/_stub_trace.py` (new)

Backs every stub so they're consistent, loud, and greppable:

```python
import sys

_HIT = set()

def stub_call(symbol, detail=""):
    # Print to BOTH stderr and stdout so the banner shows in the terminal
    # regardless of how the host routes output. Record the symbol.
    banner = "\n*** [BRIDGE-STUB] %s — NOT YET IMPLEMENTED %s\n" % (symbol, detail)
    sys.stderr.write(banner)
    sys.stdout.write(banner)
    _HIT.add(symbol)

def dump_stub_summary():
    # Called once after LoadBridge.Load returns. Prints the full set of stubs
    # that fired this load — the running "what's left to flesh out" to-do list.
    # When this prints nothing, the sequence is fully faithful.
    if not _HIT:
        sys.stderr.write("\n*** [BRIDGE-STUB] none fired — bridge init is faithful\n")
        return
    sys.stderr.write("\n*** [BRIDGE-STUB] SUMMARY — %d stub(s) still need fleshing out:\n"
                     % len(_HIT))
    for s in sorted(_HIT):
        sys.stderr.write("***   - %s\n" % s)

def reset():
    # Tests + each mission load start from a clean set.
    _HIT.clear()
```

The loud banner (blank line + `***` + ALL-CAPS marker) makes stubs impossible to
miss; the end-of-load summary is the project's live to-do list.

### `engine/appc/bridge_set.py` (new)

Holds the stub classes/factories: `BridgeSet` (subclass of the existing set
class) + `BridgeSet_Create`/`BridgeSet_Cast`, `BridgeObjectClass` +
`BridgeObjectClass_Create`, `ViewScreenObject` + `ViewScreenObject_Create`,
`ZoomCameraObjectClass` + `ZoomCameraObjectClass_Create`. Each factory/method
calls `stub_call(...)` on entry with useful detail (e.g. the NIF path). Stubs do
the minimum to not crash (record arguments, return a placeholder object with the
methods the SDK calls).

`g_kModelManager`, `SetViewScreen`, `GetNamedCameraMode`, `PushCameraMode` get
loud stubs too (in `bridge_set.py` or the appropriate existing module), all
routed through `stub_call`.

These are registered into `App.py` next to the existing managers.

## Data flow

```
host_loop (mission load)
  → _stub_trace.reset()
  → LoadBridge.Load(name)                     [real SDK]
      → CreateAndPopulateBridgeSet()          [real SDK]
          → BridgeSet_Create                  [STUB → real]
          → CreateAmbientLight                [have it]
          → CreateCharacterMenus              [have it]
          → 5× Bridge.Characters.X.CreateCharacter + ConfigureForGalaxy  [have it]
          → 3× random {Female,Male}Extra      [have it]
      → __import__("Bridge." + name)          [real SDK]
          → CreateBridgeModel(set)            [g_kModelManager / BridgeObjectClass /
                                               ViewScreenObject / ZoomCamera STUBS]
          → ConfigureCharacters(set)          [Cast + ConfigureForGalaxy; placement
                                               via CommonAnimations.SetPosition]
          → PreloadAnimations()
  → _stub_trace.dump_stub_summary()           [prints remaining work]
  → renderer consumes set objects             [bridge mesh instance, characters, camera]
```

## Incremental replacement order

Re-run (headless test + live) between each step; each step shrinks the summary:

1. **Cleanup commit** — delete the shortcut so the real SDK path is the *only*
   path (no silent fallback masking a missing stub). KEEP the renderer +
   `compose_officer_model`.
2. **Run end-to-end on stubs** — `LoadBridge.Load("GalaxyBridge")` completes; the
   stub summary prints; no crash. 5 crew + 3 extras exist in the "bridge" set.
3. **`BridgeObjectClass_Create` → real** — produces the bridge NIF instance the
   renderer draws.
4. **Character placement → real** — real `ConfigureCharacters` /
   `CommonAnimations.SetPosition` so officers sit where the SDK puts them
   (replaces the invented X-flip/identity transform).
5. **Viewscreen + camera → real** — `ViewScreenObject_Create`,
   `ZoomCameraObjectClass_Create`, camera modes.
6. **Verify extras/menus** — already real; confirm faithful.

## Cleanup of the old shadow loader (step 1)

- Root `LoadBridge.py`: remove `_BRIDGE_CREW`, the hardcoded-roster part of
  `populate_bridge_crew`, `bridge_officers()`, our `Load()`. Delete the file
  entirely if no headless test still needs a bare `SetClass` registration; reduce
  it to exactly that registration otherwise. Check consumers first; leave no dead
  code.
- `engine/bridge_officers.py`: delete `place_officers` / `_place_one` /
  `resolve_placement` / `_BRIDGE_IDENTITY_MAT4`.
- `native/src/renderer/placement_map.{h,cc}`: delete + drop from CMake.
- `engine/host_loop.py`: remove `_place_bridge_officers` hook + `_BRIDGE_NIF_MAP`.

## Error handling

- Stubs never crash the load: they record + return placeholder objects exposing
  the methods the SDK calls. A genuinely missing attribute surfaces as a normal
  Python `AttributeError` (the loud banner just before it pinpoints the symbol).
- The end-of-load summary is the canonical "not yet faithful" signal — empty
  summary ⇒ done.

## Testing

- **Headless pytest (focused subsets only — never the full suite; it OOMs the
  host):** `LoadBridge.Load("GalaxyBridge")` runs to completion against stubs;
  assert the expected stub-symbol set fired and that 5 crew + 3 extras exist in
  the "bridge" set. As each stub becomes real, assert it is **absent** from the
  fired set and assert the new real artifact (e.g. a bridge instance registered).
- **C++:** existing skinned-bridge tests stay green (renderer untouched).
- **Live verification by Mark** at each milestone — no synthetic desktop input,
  no full-screen capture.

## Caveat

SP2 rendering was validated against the shortcut's scenario. Once the SDK drives
placement (step 4), re-verify rendering against the real poses/positions — the
X-flip assumption lived in the replaced placement layer.

## Out of scope

The open renderer bug — officer heads render as blocky/untextured "lego/skeleton"
(`felix_head.tga` not landing as a recognizable face) — is a **separate**
renderer-pipeline issue independent of bridge init. Not addressed here.
