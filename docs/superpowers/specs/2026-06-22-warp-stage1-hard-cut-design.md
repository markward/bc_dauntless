# Warp Stage 1 — Hard-Cut Warp Between Systems (Design)

**Date:** 2026-06-22
**Status:** Approved for planning
**Author:** brainstormed with Mark

## Goal

Let the player select a destination in the CEF Set Course panel and warp there:
the screen hard-cuts and the player is loaded into the chosen star system. No
warp VFX, no camera choreography — those are Stages 2 and 3. This stage builds
the **faithful warp spine** so the later stages layer onto it without rework.

This is Stage 1 of a three-stage effort:

- **Stage 1 (this spec):** hard cut — fire the real SDK warp path from the CEF
  panel; load the player into the selected system.
- **Stage 2:** warp VFX (flash, streaks) wired to the procedural starbox.
- **Stage 3:** camera work (cinematic mode, cutscene cameras, bridge interlude).

## Background — how BC warp works (ground truth)

See `[[project_warp_mechanism_sdk]]` (memory) and the SDK analysis. The essentials:

- BC warp is **one choreographed `TGSequence`**, not a teleport. Its centerpiece
  is `ChangeRenderedSetAction_Create(destModule)`, which imports a set module and
  calls its `Initialize()`. **The set-swap *is* the warp.**
- **Every warp point is a self-contained, loadable set module** —
  `Systems/<Sys>/<SysN>.py` with a no-arg `Initialize()` that creates the set,
  `LoadPlacements()` (waypoints + lights, incl. "Player Start"),
  `LoadBackdrops()` (authored `StarSphere`/`BackdropSphere`), and an optional
  `<SysN>_S.py` `Initialize(pSet)` building the system contents (nebula, suns,
  asteroids via `loadspacehelper.CreateShip`). **No mission dependency.** There
  are 263 such modules — that *is* the galaxy. "Mission-registered" only governs
  what shows **bold** in the menu.
- The player STWarpButton fires `ET_WARP_BUTTON_PRESSED`; the SDK's `WarpPressed`
  handler (`Bridge/HelmMenuHandlers.py:726`) runs camera/cinematic setup and
  `RemoveControl`, then `CallNextHandler` reaches the button's default handler
  (C++ in BC), which builds + plays the WarpSequence.

### What the engine already has (de-risks Stage 1)

- The **renderer is already per-set driven**: `_resolve_active_set(player)`
  (`engine/host_loop.py:1877`) reads `GetRenderedSet()` first, and per-frame
  re-aggregates backdrops by that set, suns across all sets, and the procedural
  sky **by set name** via the sector model. Switching the rendered set already
  changes the scene.
- Implemented: `TGSequence`/`TGAction`/`TGScriptAction` (`engine/appc/actions.py`),
  `g_kSetManager` Add/Get/Delete/GetRenderedSet/MakeRenderedSet
  (`engine/appc/sets.py`), `SetClass.Add/RemoveObjectToSet`,
  `PlaceObjectByName` via the waypoint registry (`engine/appc/objects.py:165`),
  `WarpEngineSubsystem` state machine, `STWarpButton` state holder
  (`engine/appc/tg_ui/st_widgets.py:51`).
- Missing (this stage builds them): `WarpSequence_Create`,
  `ChangeRenderedSetAction_Create`/`_CreateFromSet`, the `ET_WARP_BUTTON_PRESSED`
  default handler, the CEF Warp button, mid-mission set realize/teardown, and
  the catalog `module` field.

## Decisions (locked during brainstorming)

1. **Trigger:** CEF Set Course panel stays the UI; its Warp button fires the
   real `ET_WARP_BUTTON_PRESSED` path.
2. **Button label:** **"Warp"**, sourced from the existing `Bridge Menus.TGL`
   key `"Warp"` — no new strings invented. (Deferred gate dialogue
   `CantWarp1`–`5`, `WarpStop1`–`4` is likewise already authored for Stage 2+.)
3. **Source system:** **Terminate on arrival** (after the destination loads).
   Forced by global sun/object aggregation — leaving the old set loaded would
   render two suns at once.
4. **Pre-warp gates:** **deferred** to a later stage (no engine-power or
   nebula/asteroid/starbase proximity checks in Stage 1).
5. **Trigger UX:** select a warp point (highlights), then click **Warp** to
   commit; panel + helm menu close and the sim resumes.
6. **Load failure:** **fail loud (raise)** — an unloadable set module is an
   engine gap to fix, not to paper over. Source teardown runs only after a
   successful destination load, so failures leave the player safely in the
   origin system.
7. **Sequence construction:** route through authentic `ET_WARP_BUTTON_PRESSED`
   (SDK `WarpPressed` runs) but use **our own minimal `WarpSequence_Create`** as
   the default handler — not the SDK's full `WarpSequence.SetupSequence`, which
   assumes the warp-set, bridge interlude, flash, and cutscene cameras
   (Stage 2–3 concerns).

## Architecture & data flow

```
CEF: pick warp point → "Warp" button
  → setting-course/warp:<warp-point-id>          (dauntlessEvent)
  → SettingCoursePanel resolves id → set module "Systems.Vesuvi.Vesuvi4"
  → STWarpButton.SetDestination(module); fire ET_WARP_BUTTON_PRESSED
  → SDK WarpPressed() runs — camera/cinematic actions hit existing no-op
     camera stubs in Stage 1; RemoveControl() removes player control → CallNextHandler
  → STWarpButton default handler: WarpSequence_Create(ship, destModule, warpTime, placement).Play()
       Action 1  ChangeRenderedSetAction(destModule):
                   import module → Initialize() → realize_set() render instances
                   → g_kSetManager.MakeRenderedSet(destName)
       Action 2  SetWarpPlacement (TGScriptAction):
                   move player ship into dest set → PlaceObjectByName("Player Start"), zero velocity
       Action 3  arrival finalize:
                   Terminate() source set + teardown_set() its instances; restore player control
  → panel + helm menu close; sim resumes
```

The sequence is a genuine `TGSequence`; Stages 2–3 insert flash/camera actions
between these steps without rewriting them.

## Components

### `engine/appc/warp.py` (new)

- **`ChangeRenderedSetAction(TGAction)`** + `ChangeRenderedSetAction_Create(module)`
  and `_CreateFromSet(set)`. `_do_play`: if the set isn't already registered,
  `importlib.import_module(module)` and call its `Initialize()`; resolve the set
  name; request render-instance realization for the set (via a host hook, below);
  `App.g_kSetManager.MakeRenderedSet(setName)`. Completes inline (instantaneous).
- **`WarpSequence_Create(ship, destModule, warpTime, placement)`** — returns a
  `TGSequence` with the three actions above. `warpTime` is accepted and stored
  (it drives timing in Stage 2) but Stage 1 uses zero/near-zero delays (hard
  cut). Exposes `GetShip`/`GetDestination`/`GetPlacementName` so later stages and
  SDK-style callers can introspect.
- **Warp-button default handler** — registered so that when
  `ET_WARP_BUTTON_PRESSED` propagates past the SDK `WarpPressed` handler, this
  builds `WarpSequence_Create(...)` from the button's destination and `Play()`s it.
- **`SetWarpPlacement`** — a function (SDK places it in `Actions.ShipScriptActions`;
  mirror that module path) invoked via `TGScriptAction_Create`. Moves the player
  ship out of its current set, into the destination set, and
  `PlaceObjectByName(placement)`.

### `engine/host_loop.py`

- Factor the per-set render-instance construction currently inline in
  `_MissionLoader.load` into a reusable **`realize_set(set)`** (build instances
  for a set's ships/planets/backdrops) and **`teardown_set(set)`** (destroy a
  set's instances + renderer handles). These must be callable mid-mission, not
  only at mission load.
- Provide the host hook `ChangeRenderedSetAction` / arrival-finalize use to
  realize the destination set and tear down the source set. (The action layer
  stays renderer-agnostic; the host supplies the realize/teardown callable, like
  existing host→engine wiring.)

### `engine/ui/setting_course_panel.py`

- Add a `warp` action to `dispatch_event`: resolve `self._selected_warp` →
  set module (via the catalog), set the live `STWarpButton` destination, fire
  the warp, then `close()`.
- Render payload gains a `can_warp` flag (true once a warp point is selected) so
  the JS enables the Warp button.
- The active-system **bold** overlay logic is unchanged.

### `native/assets/ui-cef/` (js / html / css)

- Add a **Warp** button to `#setting-course-panel` (label from the panel
  payload, fed from `Bridge Menus.TGL` `"Warp"`). Disabled until a warp point is
  selected; on click fires `setting-course/warp:<id>`. Reuse `cp-*`/`sc-*`
  styling. CEF loads from source — relaunch only, no rebuild.

### `tools/bake_set_course_catalog.py` + `engine/appc/sector_model.json`

- Extend each warp-point record (and each empty-system self-row) with
  **`module`** = the set region module (e.g. `"Systems.Vesuvi.Vesuvi4"`,
  `"Systems.Riha.Riha1"`). The baker already walks `CreateMenus`, where the
  region module is the `SortedRegionMenu` region argument — capture it. Re-run
  the baker and commit the updated `sector_model.json`. Preserve existing
  `bake_sector_model.py` data (the two bakers already co-preserve).

### Root `App.py`

- Export `WarpSequence_Create`, `ChangeRenderedSetAction_Create`,
  `ChangeRenderedSetAction_CreateFromSet` from `engine.appc.warp`.

## Destination resolution

The panel maps the selected warp-point `id` → its `module` via the re-baked
catalog. For the empty systems (Tau Ceti / Deep Space / Riha), whose right-column
row is the system itself, `module` is the system's own set (e.g.
`Systems.Riha.Riha1`); the baker captures these the same way.

## Error handling

- **Fail loud:** a destination module that fails to import or `Initialize()`
  raises; the exception is visible in the console (not swallowed).
- **Ordering:** destination loads and realizes **before** the source set is
  terminated, so a failed warp leaves the player in the origin system with no
  half-torn-down state.
- The player ship instance is **reused** (moved between sets), not destroyed and
  recreated.

## Testing

**Headless pytest:**

- `WarpSequence_Create(...).Play()` loads the destination set, makes it the
  rendered set (`GetRenderedSet()` == destName), and the player ends up in the
  destination set positioned at "Player Start".
- The source set is terminated (removed from `g_kSetManager`) after arrival.
- `ChangeRenderedSetAction` on an already-registered set switches to it without
  re-`Initialize()`.
- Catalog id → module resolution in `SettingCoursePanel` (incl. empty-system
  self-rows).
- The baker emits a `module` field for every warp point and self-row.
- A `warp` event with no selection is a no-op; with a selection it fires warp and
  closes the panel.
- Fail-loud: a deliberately bad module raises (and the source set survives).

**Live human gate (Mark):** from a mission, open Helm → Set Course, pick a
populated destination (e.g. Vesuvi Dust Cloud) and an empty one (e.g. Riha),
click Warp, and confirm the scene hard-cuts into the new system (new
sky/sun/contents) with the player flyable.

## Out of scope (Stage 1)

- Warp VFX: flash, streaks, dewarp (Stage 2).
- Camera: cinematic mode, cutscene cameras, bridge interlude, warp-set (Stage 3).
- Pre-warp gameplay gates and their crew dialogue (later stage).
- Multiplayer warp paths; save/load of warp/destination state.
- Procedurally synthesizing sets — unnecessary; all warp points have authored
  set modules.

## Related memories

`[[project_warp_mechanism_sdk]]`, `[[project_two_set_course_branches]]`,
`[[feedback_sdk_drives_everything]]`, `[[project_sun_render_pipeline]]`,
`[[project_cutscene_camera]]`.
