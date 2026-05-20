# SDK UI Shim — Full Bridge UI Parity

**Status:** design
**Date:** 2026-05-19

## Problem

Phase 1 of dauntless committed to running unmodified SDK Python scripts via project-root shims (`App.py`, `LoadBridge.py`, the `_SDKFinder` import hook). The current UI work in [engine/ui/](../../engine/ui/) breaks that contract: it exposes a modern declarative component API (`UiPanel`, `UiButton`, `UiCollapsibleList`, `UiStatRow`) that no SDK script can call. Bridge menu scripts in `sdk/Build/scripts/Bridge/` reach for `App.TGPane_Create`, `App.STButton_CreateW`, `pPane.AddChild(child, x, y, z)`, `App.g_kEventManager` — none of which exist in the new engine.

Audit findings (full conversation captured in session log 2026-05-19):
- SDK UI is **partially Python-defined** — C++ owns top-level windows (`TopWindow`, `BridgeWindow`, `TacticalWindow`, `MainWindow`); Python composes everything inside via `*_Create` calls and `AddChild` trees.
- Bridge UI uses ~13 distinct widget primitives plus event manager, theme, and icon-group infrastructure.
- The SDK coordinate system is **resolution-independent fractions** (`0.0` to `1.0`) of the root window. `AddChild(child, x, y, z)` offsets are screen-fraction offsets from the parent's origin, not parent-relative percentages.
- The current new-engine UI has a fundamentally incompatible API surface.

This spec covers the work to add a Python-side shim that lets unmodified SDK bridge UI scripts run on the new engine.

## Goals

- All six bridge crew menu handler scripts (`Bridge/DataMenuHandlers.py`, `EngineerMenuHandlers.py`, `HelmMenuHandlers.py`, `ScienceMenuHandlers.py`, `TacticalMenuHandlers.py`, `XOMenuHandlers.py`) construct their UIs unmodified. Character-specific overlays (`Bridge/*CharacterHandlers.py`, `PicardMenuHandlers.py`, `SaalekMenuHandlers.py`) also work where they depend only on the same widget surface.
- `MissionLib.CreateGameOverScreen()` and similar MissionLib screens run unmodified.
- SDK scripts use `App.TG*_Create*` and `App.ST*_Create*` factory functions returning objects with the SDK's expected method surface (`AddChild`, `SetVisible`, `GetScreenOffset`, `GetWidth`, `AddPythonFuncHandlerForInstance`, etc.).
- Event flow matches SDK semantics: `TGEvent_Create` + `SetDestination` + `SetEventType` + per-instance handlers resolved by string name (`"module.func"`).
- Theme system (`TGUITheme_Create`, `g_kInterface` color setters from `LoadInterface.py`) propagates to widget visuals.
- Engine-owned target list element exists and is exposed to Python through the same `TGUIObject` surface as other widgets.
- Existing `engine/ui/` directory is removed; internal callers (mission-picker, target-list controller, HUD) port to the shim API.

## Non-goals

- **Pixel-perfect visual fidelity with original BC.** The UI is modernized — rendering uses HTML/CSS treatments rather than original LCARS sprite blits. Construction APIs are faithful; visuals are a polished modern reinterpretation.
- **Main menu, options screens, multiplayer UI, text-entry composites.** Different (older) SDK construction idioms, not in scope here.
- **Animation primitives** (`TGAnimAction`, `TGAnimPosition`, `TGSequence`). Bridge UI doesn't use these for layout.
- **Sound action primitives** (`TGSoundAction`).
- **Input manager** (`MoveMouseCursorTo`, etc.) — surface accepted but no-op.
- **Dynamic font theming.** One stylesheet font for now.
- **Pushing target-list contents update into C++.** The target list element is engine-owned; contents are still composed by Python from `ship_lifecycle` events (extending the existing [2026-05-11-target-list-from-scene-design.md](2026-05-11-target-list-from-scene-design.md)).
- **Performance optimization of the shim.** UI construction is not a hot path; optimization deferred until profiling shows otherwise.

## Approach

**Python-side shim, minimal C++ changes.** All `TG*` and `ST*` classes are implemented as Python classes in a new `engine/sdk_ui/` module. Each class wraps an RmlUi element ID and translates SDK method calls (`AddChild`, `SetVisible`, `GetScreenOffset`) to the existing native helpers (`append_div`, `set_class`, `set_text`, `on_click`) plus a small set of new readback and styling bindings. `App.py` re-exports the shim symbols. The event manager is pure Python with a `__import__`+`getattr` resolver for string handler names. Native side gets minimal additions: layout pump, screen-rect readback, a handful of element-mutation bindings, theme CSS-var setter, and the engine-owned target-list constructor.

UI construction is not performance-critical (screens are built once per scene, not per frame). The shim's job is to be **correct and faithful to the SDK API surface**, not fast. If a specific widget ever becomes a hotspot, individual lowerings to C++ are possible without changing the Python-visible API.

## Architecture

### Module layout

```
engine/sdk_ui/                  # NEW
  __init__.py
  base.py                       # TGUIObject base class, coord helpers, screen-rect readback
  primitives.py                 # TGPane, TGIcon, TGParagraph, TGFrame, TGButton, TGTextButton
  stylized.py                   # STStylizedWindow, STSubPane (frame composition)
  buttons.py                    # STButton, STRoundedButton, STToggle, STTiledIcon, STFillGauge, STWarpButton
  menus.py                      # STTopLevelMenu, STCharacterMenu, STMenu, STTargetMenu
  events.py                     # ET_* constants, TGEvent, g_kEventManager, dispatch
  theme.py                      # TGUITheme, g_kInterface setters, CSS-var bridge
  icons.py                      # g_kIconManager, TGIconGroup, sprite metadata storage
  icon_classmap.py              # (group, index) -> CSS class name table
  target_list.py                # engine-owned widget wrapper + TargetListController
  resolver.py                   # "module.func" string -> callable resolution

App.py                          # CHANGED: re-export sdk_ui symbols as App.TGPane_Create etc

engine/ui/                      # DELETED entirely

native/src/host/
  host_bindings.cc              # CHANGED: add readbacks, layout pump, theme var setter,
                                  new element mutation fns, target-list accessor
  ui_target_list.cc             # NEW: creates the engine-owned target-list element

assets/ui/
  sdk_ui.rcss                   # NEW: theme vars, widget styling, decorative frame classes
```

### Coordinate system

**Python-side unit:** SDK convention — fractions of the root window, roughly [0.0, 1.0]. This applies to every method consuming or returning a position or size: `AddChild(child, x, y, z)`, `GetWidth()`, `GetHeight()`, `GetScreenOffset(point)`.

**RmlUi-side storage:**
- Each child element is `position: absolute` against its parent (parent gets `position: relative`).
- At `AddChild` time the shim computes `child.style.left = (x / parent.GetWidth()) * 100 + '%'` and same for `top`. Z-order goes through a new `set_z_index` native binding.
- Top-level panes (`TGPane_Create(w, h)` called at the SDK root) get `width: <w>vw; height: <h>vh` against the viewport.
- Nested elements inherit a screen-relative box automatically through CSS `%` chaining.

**Readback methods:**
- `GetScreenOffset(NiPoint2)` queries RmlUi's `Element::GetAbsoluteOffset()`, divides by viewport dimensions, fills the out-arg in screen-fraction units.
- `GetWidth()` / `GetHeight()` query `Element::GetBox().GetSize()`, divide by viewport dimensions.
- All three values are queried fresh; no caching; layout changes are automatically reflected.

**Pre-layout edge case:** every `*_Create*` shim function ends with a synchronous layout pump (a new `update_layout(element_id)` native binding calling RmlUi's `Element::UpdateLayout()`). After Create returns, `GetWidth/GetHeight/GetScreenOffset` always produce real values. SDK code can immediately do centering math like `0.25 - pButton.GetWidth() / 2.0` without surprise.

### Widget catalog and method surface

Every widget inherits from `TGUIObject` and supports these methods. Source: `sdk/Build/scripts/App.py` SWIG bindings plus grepped real usage in `Bridge/*.py` and `MissionLib.py`.

**Base — `TGUIObject`:**
- `AddChild(child, x=0.0, y=0.0, z=0)`, `RemoveChild(child)`, `RemoveAllChildren()`
- `SetParent(parent)`, `GetParent()`, `GetConceptualParent()`
- `SetVisible()`, `SetNotVisible()`, `IsVisible()`
- `SetDisabled(bool)`, `IsDisabled()`
- `SetFocus(child)`, `HasFocus()`
- `GetScreenOffset(NiPoint2)`, `GetWidth()`, `GetHeight()`, `SetWidth(w)`, `SetHeight(h)`
- `AddPythonFuncHandlerForInstance(eventType, "module.func")`
- `CallNextHandler(event)`, `SetAlwaysHandleEvents()`
- `MoveToFront(child)`, `AlignTo(ref, myCorner, refCorner)`

**Containers (4):**
| Factory | Notes |
|---|---|
| `TGPane_Create(w=1.0, h=1.0)` | Basic rectangular container |
| `STStylizedWindow_Create(name, template, parent)` / `_CreateW(...)` | LCARS-style window. Frame children honored as decorative spans (see Icon system below) |
| `STSubPane_Create(...)` | Subdivision pane inside a stylized window |
| `TGFrame_Create(...)` | Border/frame decoration |

**Widgets (9):**
| Factory | Notes |
|---|---|
| `TGIcon_Create(spriteName, index, color=None)` | Renders as decorative span with CSS class |
| `TGParagraph_Create(text, w, font, size)` / `_CreateW(...)` | Wide-string variant for localized text |
| `TGButton_Create(...)`, `TGTextButton_Create(...)` / `_CreateW(...)` | Plain buttons |
| `STButton_CreateW(label, event, sizeFlag)` | Themed bridge button |
| `STRoundedButton_Create(...)` / `_CreateW(...)` | Rounded variant |
| `STToggle_CreateW(...)` | Checkbox / on-off toggle |
| `STTiledIcon_Create(...)` | Tiled/repeating sprite |
| `STFillGauge_Create(...)` | Fill bar (power, shields) |
| `STWarpButton_CreateW(...)` | Warp-specific button variant |

**Menus (6):**
| Factory | Notes |
|---|---|
| `STTopLevelMenu_CreateW(name)` / `_CreateNull(name)` | Composite — manages child buttons + radio-group selection internally |
| `STCharacterMenu_CreateW(character, ...)` | Character-specific submenus |
| `STMenu_Create(...)` / `_CreateW(...)` | Generic menu |
| `STTargetMenu_CreateW(...)` | Target-specific menu variant |

**Theme:**
- `TGUITheme_Create()` — instantiates and registers the global theme

**Engine-owned:**
- `App.g_kTacticalWindow.GetTargetList()` — returns a `TGUIObject` wrapper around the C++-managed target list element

**Methods accepted but no-op (don't crash, don't visibly do anything):**
- `MoveMouseCursorToUIObject` (input manager surface)
- Window minimize/restore on STStylizedWindow
- Some STBSF_* style flags

**Methods not implemented (raise `AttributeError` if SDK code touches them):**
- Animation primitives — bridge UI doesn't use them
- Sound action primitives

### Event system façade

The SDK's event flow:
```python
pEvent = App.TGEvent_Create()
pEvent.SetDestination(pPane)
pEvent.SetEventType(App.ET_LOAD_GAME)
pButton = App.STButton_CreateW(label, pEvent, App.STBSF_SIZE_TO_TEXT)
pPane.AddChild(pButton, ...)
pPane.AddPythonFuncHandlerForInstance(App.ET_LOAD_GAME, __name__ + ".RestartGame")
App.g_kEventManager.AddBroadcastPythonFuncHandler(
    App.ET_NEW_GAME, pPane, __name__ + ".DestroyGameOverScreen")
```

**Implementation in `engine/sdk_ui/events.py`:**
- `ET_*` constants — integer enums for the ~25–40 event types referenced by bridge UI and MissionLib. Enumerated from grep.
- `TGEvent` — small dataclass-like Python object with `{type, destination, source, payload}` and `SetDestination/SetEventType/SetX/SetY/GetX/GetY/...` accessors.
- `_EventManager` singleton with two registries:
  - `_per_instance: dict[(element_id, event_type), list[handler_str]]`
  - `_broadcast: dict[event_type, list[(element_id, handler_str)]]`
- `g_kEventManager` — module-level instance, importable as `App.g_kEventManager`.
- `_resolve(handler_str) → callable` — `"module.submod.func"` → `importlib.import_module("module.submod").func`. Cached after first lookup. Raises `EventHandlerError` on failure (no silent swallow).

**Click → handler wiring:**
1. `STButton_CreateW(label, event_template, flags)` stashes the event template in the button wrapper.
2. The wrapper registers a single native `on_click` handler calling `_dispatch_button_click(element_id)`.
3. Dispatcher looks up the button's event template, clones it with the button as source, sets destination if needed, fires through `_EventManager.dispatch(event)`.
4. Dispatch walks: per-instance handlers on destination, then `CallNextHandler` walks up the conceptual-parent chain if a handler doesn't consume, then broadcast handlers fire last.

**Handler return semantics:** SDK convention is that handlers return `None` (or fall through to `CallNextHandler`) to let the event propagate; "consumed" is signaled by not calling `CallNextHandler`. We follow that.

### Theme system

SDK side (called once at startup, then possibly again on affiliation switch):
```python
App.TGUITheme_Create()
App.g_kInterface.SetMainBackgroundColor(r, g, b)
App.g_kInterface.SetMainBorderColor(r, g, b)
App.g_kInterface.SetMainTextColor(r, g, b)
# ... ~30 more setters
```

**Implementation in `engine/sdk_ui/theme.py`:**
- `TGUITheme` — Python class with a flat dict of named color slots (`main_background`, `main_border`, `main_text`, `submenu_background`, `submenu_text`, `disabled_text`, `affiliation_federation_primary`, etc.). Slots enumerated by grepping `LoadInterface.py`.
- `TGUITheme_Create()` instantiates one and stores it as `_active_theme`. Repeat calls replace.
- `g_kInterface` façade with `SetMain*Color(r, g, b)` setters that write to `_active_theme` and call `set_root_css_var("--bc-<slot>", "rgb(...)")`.

**RmlUi bridge (CSS custom properties):**
```css
:root {
  --bc-main-background: rgb(...);
  --bc-affiliation-federation: rgb(...);
  /* ... */
}

.bc-button { background-color: var(--bc-main-background); border-color: var(--bc-main-border); }
.bc-button.bc-affiliation-klingon { background-color: var(--bc-affiliation-klingon); }
```

Theme changes at runtime re-run the setters; CSS variable cascade re-paints automatically. No per-element updates needed.

**Widget-side class assignment:** widgets get CSS classes at Create time based on construction args. `STButton_CreateW` → `class="bc-button"`. A Federation-affiliated button → `class="bc-button bc-affiliation-federation"`. `SetDisabled` toggles `bc-disabled`.

**Sprite-based widgets** (`TGIcon_Create` with explicit `pMainColor`): the color is applied as inline `style.color` or `image-color`, bypassing the CSS-var path. Theme only applies when no explicit color is given.

### Icon system (modernized)

SDK code constructs LCARS frames by adding ~24 sprite children with explicit `(group, index)` pairs (see [StylizedWindow.py:62-106](../../sdk/Build/scripts/StylizedWindow.py#L62-L106)). The shim accepts the entire API:

```python
# engine/sdk_ui/icons.py
class TGIconGroup:
    ROTATE_0 = 0; ROTATE_90 = 1; ROTATE_180 = 2; ROTATE_270 = 3
    MIRROR_NONE = 0; MIRROR_HORIZONTAL = 1; MIRROR_VERTICAL = 2

    def LoadIconTexture(self, path) -> "TGTextureHandle": ...
    def SetIconLocation(self, index, texture, x, y, w, h, rotation=0, mirror=0): ...

class _IconManager:
    def CreateIconGroup(self, name) -> TGIconGroup: ...
    def AddIconGroup(self, group): ...

g_kIconManager = _IconManager()
```

**Visual rendering:** modernized — sprite sub-rect coordinates are stored but **not used to blit the original TGA**. Instead, `TGIcon_Create(group_name, index, color)` renders the child as:

```html
<span class="bc-frame bc-frame-NormalStyleFrame bc-frame-NormalStyleFrame-0"
      style="color: <tint>; transform: rotate(0deg) scaleX(-1)"></span>
```

A new `engine/sdk_ui/icon_classmap.py` defines the friendly name per `(group, index)` based on the comments in `StylizedWindow.py` (e.g. index 0 = `tl-curve`, 1 = `left-side`, 23 = `under-title-spacing`). The stylesheet `assets/ui/sdk_ui.rcss` defines what each class looks like — initially minimal CSS treatments (border-radius, gradients, simple shapes), refined during visual polish.

Mirror and rotation flags from `SetIconLocation` map to `style.transform`, so SDK hints (e.g. flipping a top-left curve into a top-right curve via `MIRROR_HORIZONTAL`) still produce the expected visual.

This satisfies the goal: SDK construction order influences visuals via CSS class assignment, but visual treatment is a modern reinterpretation rather than a faithful sprite blit.

### Engine-owned target list

The target list **element** is engine-owned; the **contents** remain Python-composed.

**Why this split:** the source of truth for which ships exist already lives in Python (`engine/appc/ship_lifecycle.py` from the existing [target-list-from-scene spec](2026-05-11-target-list-from-scene-design.md)). Duplicating that bookkeeping in C++ adds no value. What C++ owns is the *stable element* — the box in the document tree, with a known id, available from boot.

**Pieces:**

1. **Native side** (`native/src/host/host_bindings.cc` + `ui_target_list.cc`):
   - At tactical window init, create an RmlUi element with a fixed id (`#target-list`) as a child of the tactical window root.
   - Register binding `get_target_list_element() → int` returning the element's ID.
   - No contents logic in C++.

2. **Python wrapper** (`engine/sdk_ui/target_list.py`):
   - `App.g_kTacticalWindow.GetTargetList()` returns a `TGUIObject` wrapper around the engine-owned element.
   - Wrapper is the same class as any other shimmed widget — full SDK method surface.
   - SDK scripts cannot tell it apart from a `TGPane_Create`-returned object.

3. **`TargetListController`** (rewrite of current `engine/ui/target_list.py`):
   - Subscribes to `ship_lifecycle` as in the existing spec.
   - On `added`: `target_list.AddChild(STStylizedWindow_CreateW(...))` + child `STButton_CreateW(...)` for each row.
   - On `destroyed`: removes the row.
   - Click handler → `player.SetTarget(ship)`.
   - Lives in `engine/sdk_ui/target_list.py`.

4. **Stage 2 (subsystem expansion)** unchanged from the existing spec — uses the same shim API.

**Updates to the existing target-list spec:** path changes from `engine/ui/target_list.py` to `engine/sdk_ui/target_list.py`; `UiPanel.collapsible(...)` calls become `STStylizedWindow_CreateW(...)` + child buttons. Data-flow architecture (`ship_lifecycle` pub/sub, mission swap teardown, dead-ship cleanup) is preserved.

### Native binding additions

Existing native surface (`create_panel`, `append_div`, `set_class`, `set_text`, `on_click`, `set_visible`) covers most construction needs. The shim adds:

| Binding | Purpose |
|---|---|
| `get_screen_rect(element_id) -> ScreenRect{x,y,w,h}` | Single readback for `GetScreenOffset/GetWidth/GetHeight`. All values in screen-fraction units. |
| `update_layout(element_id)` | Synchronous RmlUi layout pump on subtree. Called at end of every `*_Create*` shim function. |
| `append_text(parent_id, text)` | Text node creation |
| `set_z_index(element_id, z)` | Z-order via RmlUi |
| `set_style(element_id, property, value)` | Catch-all inline-style setter for cases CSS classes can't express |
| `remove_element(element_id)` | RemoveChild support |
| `remove_all_children(element_id)` | RemoveAllChildren support |
| `set_root_css_var(name, value)` | Theme propagation |
| `get_target_list_element() -> int` | Engine-owned target-list accessor |

9 new bindings, all stateless except the target-list-element constructor.

`TGIcon` (decorative spans) and `STToggle` (styled div with class toggle) are implemented using the existing `append_div` + `set_class` surface — no new bindings needed for them.

**Asset loading (deferred):** `load_texture(path)` and `append_sprite(parent_id, texture_id, sub_x, sub_y, sub_w, sub_h, rotation, mirror, color)` are **not in scope** for this spec. They become relevant only for *content* icons (ship icons, character portraits, damage indicators), not for chrome. Content sprites are a separate, smaller follow-on workstream.

## Testing strategy

Three layers, different cost/coverage tradeoffs.

**Layer 1 — Pure-Python unit tests** (cheap, fast, high coverage):

The shim is mostly translation logic. A `FakeNativeBackend` replaces native bindings, recording calls and returning canned data. Tests verify:
- `TGPane_Create(0.5, 0.5)` calls `create_panel` with right args.
- `pPane.AddChild(pButton, 0.25, 0.45)` triggers `set_style("left", "50%")` after coord conversion (parent width 0.5).
- `AddPythonFuncHandlerForInstance` + simulated click → handler resolves and fires.
- Event manager broadcast routing, `CallNextHandler` walk, return semantics.
- Theme: `SetMainBackgroundColor(1,0,0)` → `set_root_css_var("--bc-main-background", "rgb(255,0,0)")`.
- Icon group: `SetIconLocation` + `TGIcon_Create` → `append_div` with the expected `bc-frame-<group>-<index>` class and correct `transform` style.

Coverage target: every public method has at least one happy-path test. ~80% line coverage of `engine/sdk_ui/`. Runs in <5s.

**Layer 2 — SDK-script smoke tests** (medium cost, catches API mismatches):

Load actual unmodified SDK scripts and verify they construct. Uses the existing `_SDKFinder` import hook. Battery:
- `MissionLib.CreateGameOverScreen()`
- One screen each from Data, Engineer, Helm, Science, Tactical, XO menu handlers (6 screens)
- `MissionLib.CreateLoadingScreen()` if in scope

For each: construct the widget tree, pump layout, dispatch a synthetic click to the first button, verify the registered handler fires, tear down. ~10 tests, <30s with native side included.

**This layer is the primary signal** that the shim works. It will fail with `AttributeError: App.X has no attribute Y` whenever a script touches an unimplemented SDK method — that's the punch list for completing the shim.

**Layer 3 — Visual verification** (expensive, low frequency):
- Snapshot tests for 3–5 key screens (GameOverScreen, one bridge menu, target list). Native renders to offscreen buffer; diff against committed PNG. Run on demand; regenerated on intentional visual changes.
- Manual checklist (`tests/manual/bridge_ui_smoke.md`): open bridge, click each menu, verify selection states, check affiliation color swap.

**Explicitly not tested:**
- RmlUi internals
- Pixel-perfect comparison with original BC visuals (not a goal)
- Performance / layout pump cost (measured later if needed)

**Test infrastructure work:**
- `FakeNativeBackend` for Layer 1 — new file, ~200 lines
- `headless_host_loop()` context manager for Layer 2 — initializes RmlUi without a window; may already mostly exist in `engine/host_loop.py` test setup
- Snapshot harness for Layer 3 — defer until Layer 2 stabilizes

**Verification target:** at project end, `Bridge/ScienceMenuHandlers.py` (unmodified, from the SDK directory via `_SDKFinder`) executes its full `CreateMenus()` call and produces a renderable widget tree with working button events. That's the binary pass/fail.

## Phasing

Five slices. Each ships a working subset to `main` with passing tests before the next starts.

### Slice 1 — Foundations + GameOverScreen (~1.5 weeks)

Verifies the architecture end-to-end on the simplest target.

- `engine/sdk_ui/base.py` — `TGUIObject` base, coord helpers, screen-rect wrapper
- `engine/sdk_ui/primitives.py` — `TGPane`, `TGParagraph`
- `engine/sdk_ui/buttons.py` — `STButton` only
- `engine/sdk_ui/events.py` — full event manager façade, ET_* constants used by GameOverScreen, handler resolver
- `engine/sdk_ui/stylized.py` — `STStylizedWindow` minimal (frame children honored as decorative spans, basic CSS treatment)
- Native side: `get_screen_rect`, `update_layout`, `append_text`, `set_z_index`, `set_style`, `remove_element`, `remove_all_children`
- `App.py` re-exports
- Layer 1 unit tests
- Layer 2 smoke: `MissionLib.CreateGameOverScreen()` constructs, renders, click → handler fires

**Done when:** unmodified `MissionLib.CreateGameOverScreen()` runs and a "Restart" click calls `RestartGame`.

### Slice 2 — Delete `engine/ui/`, port internal callers (~1 week)

Clean-break commitment from the API decision.

- Rewrite `engine/ui/target_list.py` → `engine/sdk_ui/target_list.py` using shim API (Stage 1 only)
- Port mission-picker bindings off `UiPanel`/`UiButton`/`UiCollapsibleList`
- Port HUD/StatRow callers if any remain
- Delete `engine/ui/`
- Update `host_loop.py` integration
- All existing tests pass

**Done when:** `engine/ui/` is gone, mission-picker and target list work via the shim, no regressions.

### Slice 3 — Icon manager + theme system (~1 week)

Remaining infrastructure.

- `engine/sdk_ui/icons.py` — `g_kIconManager`, `TGIconGroup`, `SetIconLocation`, rotation/mirror constants
- `engine/sdk_ui/icon_classmap.py` — name table for common (group, index) pairs
- `TGIcon_Create` renders decorative span with CSS class + transform
- `engine/sdk_ui/theme.py` — `TGUITheme_Create`, `g_kInterface` setters, CSS-var propagation
- `set_root_css_var` native binding
- `assets/ui/sdk_ui.rcss` — initial stylesheet
- Layer 1 tests

**Done when:** runtime theme switching works, stylized window frames render as styled CSS, no AttributeError on icon manager calls.

### Slice 4 — Menu composites + remaining widgets (~2 weeks)

Biggest slice — bridge menus are the verification target.

- `engine/sdk_ui/menus.py` — `STTopLevelMenu`, `STCharacterMenu`, `STMenu`, `STTargetMenu` (radio-group selection, internal layout)
- Remaining widgets: `TGIcon`, `TGFrame`, `TGButton`, `TGTextButton`, `STRoundedButton`, `STToggle`, `STTiledIcon`, `STFillGauge`, `STWarpButton`
- `STSubPane`
- Layer 2 smoke tests for all six bridge menu handlers
- Layer 1 unit tests

**Done when:** all six `Bridge/*MenuHandlers.py` scripts (Data, Engineer, Helm, Science, Tactical, XO) construct without error and route clicks to their handlers.

### Slice 5 — Engine-owned target list polish + visual pass (~1.5 weeks)

Closing the gap between "works" and "looks good."

- Native: `get_target_list_element`, `ui_target_list.cc`
- Wire `TargetListController` to engine-owned element
- Stage 2 (subsystem expansion) from existing spec
- Visual polish on `sdk_ui.rcss` — frame treatments, button styling, affiliation accents
- Layer 3 snapshot tests for 3–5 key screens
- `tests/manual/bridge_ui_smoke.md`

**Done when:** bridge UI looks polished, target list is engine-owned, all six bridge menus render correctly in a running game session.

**Total: ~7 weeks.**

## Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | **Slice 4 menu composites have unclear internal semantics** (radio-group selection, layout). Could surface significant scope. | Time-box; if a specific composite proves harder than expected, ship its scripts in a "second pass" and unblock the rest. |
| 2 | **RmlUi runtime CSS-variable update mechanism unverified.** Theme propagation depends on RmlUi exposing a way to update `:root` vars at runtime. | Investigate during Slice 3 setup; fallback is per-element style application (slower but works). |
| 3 | **Internal caller porting in Slice 2 may surface hidden dependencies** on `engine/ui/` API. | Pre-Slice-2 grep for all `engine.ui` imports; estimate breakdown before committing slice timeline. |
| 4 | **`STStylizedWindow` minimize/restore semantics may be needed by some bridge scripts.** Currently scoped as no-op. | Verify via Layer 2 smoke before Slice 5; if needed, add. |
| 5 | **Pre-layout `GetWidth`/`GetHeight` reliability.** Layout pump may not produce intrinsic sizes in all edge cases (e.g. text waiting for font load). | Verify with Slice 1 GameOverScreen end-to-end; the centering math is the canary. |
| 6 | **Visual polish is open-ended.** Slice 5 has no natural "done" condition. | Time-box; ship "good enough" and treat further polish as a separate workstream. |

## Open questions

- **STStylizedWindow templates.** SDK code passes strings like `"StylizedWindow"`, `"RightBorder"`, `"NoMinimize"`. We accept them but don't yet know what each template should look like visually. Decide during Slice 3/5 alongside the stylesheet work.
- **Exact set of `ET_*` event types.** A grep across `Bridge/` and `MissionLib.py` gives a number; need a final tally before Slice 1 ships. Out-of-band: enumerate during Slice 1.
- **Will any bridge script depend on `MoveMouseCursorToUIObject` actually moving the cursor?** Currently scoped as no-op. If yes, add an input-manager binding.

## Relationship to existing specs

- **Supersedes** [2026-05-11-ui-components-design.md](2026-05-11-ui-components-design.md). The `UiPanel`/`UiButton`/`UiCollapsibleList` API described there is deleted. The theming approach (registries mirroring `LoadInterface.py`) is preserved in spirit and re-expressed through CSS variables.
- **Modifies** [2026-05-11-target-list-from-scene-design.md](2026-05-11-target-list-from-scene-design.md). The data flow (`ship_lifecycle` pub/sub, mission swap teardown) is preserved; the UI composition is rewritten on top of the shim API and the element is engine-owned.
- **Compatible with** [2026-05-11-mission-picker-design.md](2026-05-11-mission-picker-design.md) — mission picker will be ported off `UiPanel`/`UiButton` in Slice 2.
- **Compatible with** [2026-05-10-rmlui-hud-design.md](2026-05-10-rmlui-hud-design.md) — RmlUi remains the rendering backend; this spec only changes the API surface above it.
