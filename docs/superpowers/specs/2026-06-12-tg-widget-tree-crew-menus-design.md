# TG widget tree + crew menus — design

**Date:** 2026-06-12
**Status:** Spec draft, awaiting user review.
**Motivation:** A survey of all 1,233 SDK scripts found 969 `App.*` symbols our shim
does not define; the largest functional cluster is the retained-mode TG widget tree
(`TGPane`, `TGIcon`, `TGIconGroup`, `TGParagraph`, font/icon/focus managers —
~2,360 uses across 83 files) and the bridge crew-interaction layer built on it
(`ET_COMMUNICATE` alone has 231 uses). Every SDK-rendered interface — bridge menus,
tactical interface, engineering power — constructs this tree, attaches event
handlers to it, and mutates it from mission scripts. Today all of it dissolves into
`_NamedStub` no-ops: handlers register on stubs, mission scripts toggle buttons that
don't exist, and the corresponding gameplay (hail, set course, all stop, dock) is
unreachable.

This spec extends the proven two-tier pattern of the
[CEF SDK-UI mirror](2026-06-03-cef-sdk-ui-mirror-design.md): headless Python shims
own state, a `Panel` observes and projects into CEF, CEF clicks route back as SDK
events. Tier 1 (foundation) makes the widget-tree scripts run with correct state and
event behaviour. Tier 2 (first surfaced interface) renders the bridge crew menus and
closes the click loop, proving the architecture end-to-end.

---

## Goals

1. **Foundation:** real headless classes for the TG widget tier so the 83 widget-tree
   files (Icons/, LoadInterface, Bridge/*MenuHandlers, Tactical/Interface) import and
   run without `_NamedStub` leakage.
2. **Event truth:** the bridge-interaction `ET_*` constants become real stable ints so
   handler registration and future engine broadcasts route correctly.
3. **Crew menus surfaced:** the `STTopLevelMenu` trees SDK code attaches to
   `TacticalControlWindow` render in CEF (dauntless chrome), live-update when SDK
   code mutates them, and clicks fire the original SDK handlers.
4. **Proof of loop:** clicking "All Stop" in CEF runs `HelmMenuHandlers.AllStop`
   unmodified and the ship stops via existing engine surfaces.

## Non-goals

- **No rendering of icons, fonts, or pixel layout.** `TGIconGroup.SetIconLocation`
  atlas records and `g_kFontManager.RegisterFont` entries are stored, never drawn.
  All `(x, y)` arguments are accepted and stored, never consulted — same decision as
  the 2026-06-03 mirror spec (dauntless re-style, not LCARS).
- **No character animation.** `g_kAnimationManager.LoadAnimation` records and plays
  nothing. Phase 2 NIF animation is its own project. Hail/Communicate yield the menu,
  the dialogue line (subtitle mirror + `TGSound` where assets resolve), and the
  gameplay effect — no bridge-crew visuals.
- **No warp execution.** `STWarpButton` / `SortedRegionMenu` get headless classes so
  `CreateMenus()` completes; the warp/set-course *behaviour* (`WarpSequence`,
  `ET_WARP_BUTTON_PRESSED` plumbing) is a follow-up spec.
- **No other interfaces surfaced.** Engineering power display, science/XO/tactical
  character menus, main menu, multiplayer menus: the foundation makes their scripts
  run; each gets its own follow-up panel spec ("one shim + one slot").
- **No save-game persistence of widget state.** Menus are rebuilt by SDK code on
  mission load, same as original BC.
- **No focus/keyboard navigation semantics.** `g_kFocusManager` holds a focused-widget
  reference; nothing reads it yet.

---

## Architecture

### Tier 1 — headless TG widget tier: `engine/appc/tg_ui/`

| File | Purpose |
|---|---|
| `engine/appc/tg_ui/__init__.py` | Package marker; re-exports public factories |
| `engine/appc/tg_ui/widgets.py` | `TGPane`, `TGIcon`, `TGParagraph`, `TGIconGroup` + `_Create`/`_CreateW`/`_Cast` factories |
| `engine/appc/tg_ui/managers.py` | `TGFontManager`, `TGIconManager`, `TGImageManager`, `TGFocusManager` classes + `g_k*` singletons; `g_kRootWindow` (a `TGPane`) |
| `engine/appc/tg_ui/graphics_mode.py` | `GraphicsModeInfo` canned singleton + `GraphicsModeInfo_GetCurrentMode`; `TGUIModule_PixelAlignValue` (identity) |

Conventions (all matching `engine/appc/characters.py` `STMenu`/`STButton`):

- Widgets hold: children list with stored `(x, y)`, visibility, enabled flag,
  name/text. Hierarchy via `AddChild` / `KillChildren` / `DeleteChild`.
- Event-handler registration inherits the existing
  `TGEventHandlerObject.AddPythonFuncHandlerForInstance` machinery
  (`engine/appc/events.py`) — registration by module-path string, identical to every
  other shim.
- `TGIconGroup.ROTATE_*` are class attributes; `SetIconLocation(...)` appends an
  atlas record `(slot, texture, x, y, w, h, rotation)`.
- Casts are the lenient pass-through style (`return obj if isinstance(...) else None`,
  rejecting `_NamedStub`).
- `g_kFontManager.RegisterFont` records entries; font-handle lookups return an object
  with plausible metrics (height = point size, fixed advance) so layout math in SDK
  scripts produces finite numbers.
- `GraphicsModeInfo_GetCurrentMode()` → singleton: 1024×768,
  `GetLcarsModule()` → `"LCARS_1024"`.

**Supporting change — bare-name Icons imports:** BC's `Autoexec.py` does
`sys.path.append("scripts/Icons")`, so SDK code imports `LCARS_1024` and
`FontsAndIcons` as top-level names. `_SDKFinder` (in `tests/conftest.py` and the host
loop's equivalent) learns to resolve bare module names from
`sdk/Build/scripts/Icons/` as a final fallback.

**ET_ constants (App.py stable-int block):** `ET_ST_BUTTON_CLICKED`,
`ET_COMMUNICATE`, `ET_HAIL`, `ET_SCAN`, `ET_SET_COURSE`, `ET_ALL_STOP`, `ET_DOCK`,
`ET_MANAGE_POWER`, `ET_MANEUVER`, `ET_HAILABLE_CHANGE`, `ET_SENSORS_SHIP_IDENTIFIED`,
`ET_CLOAK_COMPLETED`, `ET_DECLOAK_COMPLETED`, `ET_CHARACTER_MENU`,
`ET_CONTACT_STARFLEET`, plus any additional constants the helm/tactical menu files
reference at import time (enumerated during implementation by running the imports).
Real ints fix the silent-never-fires failure mode for these events.

**New headless ST widgets** (in `engine/appc/tg_ui/st_widgets.py` —
`characters.py` is already 572 lines and stays untouched): `STCharacterMenu` (+`_CreateW`), `STWarpButton` (+`_CreateW`,
stores `SetWarpTime`/`SetCourseMenu`), `SortedRegionMenu` (+`_CreateW`,
`SortedRegionMenu_SetWarpButton`/`_GetWarpButton`/`_SetPauseSorting` module
functions), `STButton_Cast`, `STStylizedWindow_Cast`, `STRoundedButton` (+`_CreateW`,
`_Cast`), `STSubPane` (+`_Create`, `_Cast`). All state-holding subclasses of the
existing `STMenu`/`STButton`/pane classes.

### Tier 2 — `CrewMenuPanel`

| File | Purpose |
|---|---|
| `engine/ui/crew_menu_panel.py` | `CrewMenuPanel(Panel)` — snapshot + click dispatch |
| `native/assets/ui-cef/js/crew_menus.js` | `setCrewMenus(payload)` rendering + click emit |
| `native/assets/ui-cef/css/crew_menus.css` | Dauntless chrome for the menu bar |
| `native/assets/ui-cef/hello.html` | Slot + script/css links |
| `engine/host_loop.py` | Construct + register panel (always-on, not dev-gated) |

**Outbound.** Once per tick the panel iterates
`TacticalControlWindow.GetInstance()`'s menu list (`AddMenuToList` is the existing
attachment point — the panel never walks the full widget tree). Snapshot per menu:
stable widget id, label, enabled, visible, children (recursive). JSON payload, diffed
against last push (same dedup + `invalidate()` semantics as `SDKMirrorPanel`),
emitted as `setCrewMenus(...)`.

**Inbound.** Snapshot nodes carry ids; CEF clicks dispatch `crew-menu/click:<id>`.
The panel resolves the id to the live widget and fires the button's stored
activation `TGEvent` (the one `BridgeMenus.CreateBridgeMenuButton` attached — event
type + destination) through `g_kEventManager`, exactly what the original engine's
input layer did. The SDK handler (`HelmMenuHandlers.Hail`, `.AllStop`, …) runs
unmodified and drives the game through engine surfaces.

**Widget ids:** monotonically increasing `_widget_id` int assigned at widget
construction by a module-level counter in `tg_ui`. Ids are per-process, never
persisted.

### Data flow

```
Mission load
  HelmMenuHandlers.CreateMenus()            (unmodified SDK)
    ├─ STTopLevelMenu_CreateW("Helm")        → headless tree
    ├─ CreateBridgeMenuButton("All Stop", ET_ALL_STOP, …)
    │     stores TGEvent(type=ET_ALL_STOP, dest=pHelmMenu) on the button
    ├─ pHelmMenu.AddPythonFuncHandlerForInstance(ET_ALL_STOP, "….AllStop")
    └─ pTacticalControlWindow.AddMenuToList(pHelmMenu)

Tick                                   Click
  CrewMenuPanel.render_payload()         CEF emits crew-menu/click:<id>
    walk menu list → JSON → diff           panel resolves id → live STButton
    → setCrewMenus(...) → CEF DOM          → fire stored TGEvent via g_kEventManager
                                           → HelmMenuHandlers.AllStop (SDK)
                                           → engine SetSpeed(0) — ship stops
```

---

## Error handling

1. **No `_NamedStub` leakage:** every symbol this spec claims is a real class;
   failures are loud `AttributeError`s, not silent stub chains.
2. **Panel never throws into the tick:** unknown widget types in a menu tree are
   logged once per type and skipped (same as `SDKMirrorPanel._log_unrecognised_once`).
3. **Stale click ids:** a click whose id no longer resolves (menu rebuilt between
   frames) is dropped with a log line; the next snapshot repairs the UI.

## Testing

Focused subsets only (full-suite pytest OOMs the host).

- **Unit:** `tests/unit/test_tg_ui_widgets.py` (construction, hierarchy, mutation,
  casts); `tests/unit/test_tg_ui_managers.py` (font/icon registration, canned
  graphics mode); `tests/unit/test_crew_menu_panel.py` (snapshot shape, diffing,
  invalidate, stale-id drop).
- **Integration:** import `FontsAndIcons` and `LCARS_1024` through `_SDKFinder`
  cleanly; run `HelmMenuHandlers.CreateMenus()` and assert the helm tree exists with
  the expected buttons and handler registrations; round-trip — simulated
  `crew-menu/click:<id>` on All Stop fires the SDK handler and the player ship's
  impulse drops to zero.

## Follow-up specs unlocked

Each is "one shim + one slot" on this foundation: warp/set-course execution
(`WarpSequence`), engineering power display (`EngPowerCtrl`, `ET_MANAGE_POWER`),
character speech depth (voice asset routing), tactical/science/XO menu surfacing,
bridge VFX emitter properties.
