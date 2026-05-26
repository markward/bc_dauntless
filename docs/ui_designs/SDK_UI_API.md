# SDK → UI Contract

The Bridge Commander SDK (Python scripts under `sdk/Build/scripts/`) calls a fixed set of UI factory + widget functions to render the bridge interface. These calls are exposed via `App.py` (the SWIG-generated module surface). The engine's job is to **service every one of these calls** by emitting the corresponding panel state to the rendering layer.

This document catalogs:
1. The canonical colour palette (SDK globals + shim accents)
2. Every SDK widget factory function the bridge UI uses
3. Every event the UI dispatches back to the SDK
4. How the engine maps SDK calls to render state

---

## 1. Colour palette

All values are RGB unless noted. **Every panel uses tokens from this table — never inline literal colours.** Sources: `engine/sdk_ui/palette.py` (which mirrors `LoadInterface.SetupColors()` defaults from the SDK).

### 1.1 Chrome family colours (Menu1, Menu2, Menu3)

The chrome of every panel is one of three colour "families". A panel's chrome family signals its role in the menu hierarchy.

| Token | SDK name | Value | Used for |
|---|---|---|---|
| `--bc-menu1-base` | `g_kSTMenu1NormalBase` | `rgb(216, 94, 86)` salmon-orange | Primary panel chrome; top-level menus (TACTICAL, ORDERS, Engineer panel, Officer menu) |
| `--bc-menu1-highlight` | `g_kSTMenu1HighlightedBase` | `rgb(254, 120, 86)` | Hover / focus state on Menu1 |
| `--bc-menu2-base` | `g_kSTMenu2NormalBase` | `rgb(147, 103, 255)` purple | Row body / chosen state across the bridge UI |
| `--bc-menu2-highlight` | `g_kSTMenu2HighlightedBase` | `rgb(173, 132, 255)` | Hover / focus on Menu2 rows |
| `--bc-menu3-base` | `g_kSTMenu3NormalBase` | `rgb(207, 96, 159)` pink | Sub-menu chrome (MANOEUVRES, TACTICS) — Menu1 with a +20° hue shift |
| `--bc-menu3-highlight` | `g_kSTMenu3HighlightedBase` | `rgb(246, 147, 204)` | Hover on Menu3 |
| `--bc-title-color` | `g_kTitleColor` | `rgb(255, 154, 2)` deep orange | Reserved for primary titles / mission name |

The Menu1 header gradient runs `--bc-menu1-base → +20° hue shift`, derived programmatically:

```python
# engine/sdk_ui/palette.py:_hue_shift_plus_20
import colorsys
h, s, v = colorsys.rgb_to_hsv(216/255, 94/255, 86/255)
h = (h + 20.0/360.0) % 1.0
new_rgb = colorsys.hsv_to_rgb(h, s, v)
# → (216, 132, 80) approximately — this is --bc-menu1-accent
```

### 1.2 Subsystem identity colours (engineering)

Each powered subsystem has a canonical colour used wherever it appears (engineer panel rows, power-grid segments, system labels).

| Token | SDK name | Value | Subsystem |
|---|---|---|---|
| `--bc-weapons` | `g_kEngineeringWeaponsColor` | `rgb(207, 139, 76)` | Weapons |
| `--bc-engines` | `g_kEngineeringEnginesColor` | `rgb(199, 76, 200)` | Engines (impulse + warp) |
| `--bc-sensors` | `g_kEngineeringSensorsColor` | `rgb(201, 203, 76)` | Sensor Array |
| `--bc-shields` | `g_kEngineeringShieldsColor` | `rgb(150, 129, 222)` | Shield Generator |
| `--bc-warp-core` | `g_kEngineeringWarpCoreColor` | `rgb(22, 105, 207)` | Warp Core (power source) |
| `--bc-main-battery` | `g_kEngineeringMainPowerColor` | `rgb(180, 157, 64)` | Main Battery |
| `--bc-reserve-power` | `g_kEngineeringBackupPowerColor` | `rgb(208, 87, 42)` | Reserve Power |
| `--bc-tractor` | `g_kEngineeringTractorColor` | `rgb(150, 129, 222)` | Tractor toggle (matches Shield Gen) |
| `--bc-cloak` | `g_kEngineeringCloakColor` | `rgb(235, 128, 21)` | Cloak toggle |

### 1.3 Subsystem state colours

Used for damage indicators and percentage bars.

| Token | SDK name | Value | Meaning |
|---|---|---|---|
| `--bc-subsystem-fill` | `g_kSubsystemFillColor` | `rgb(184, 255, 0)` | Healthy fill (legacy SDK; we use `--bc-hull-healthy` for newer panels) |
| `--bc-subsystem-empty` | `g_kSubsystemEmptyColor` | `rgb(170, 25, 25)` | Empty / damaged-zone (used in power-grid OFFLINE segment hatch) |
| `--bc-subsystem-disabled` | `g_kSubsystemDisabledColor` | `rgb(153, 153, 153)` | Disabled / unavailable |
| `--bc-damage-damaged` | `g_kDamageDisplayDamagedColor` | `rgb(184, 255, 0)` | Damaged-but-online |
| `--bc-damage-disabled` | `g_kDamageDisplayDisabledColor` | `rgb(153, 153, 153)` | Disabled |
| `--bc-damage-destroyed` | `g_kDamageDisplayDestroyedColor` | `rgb(255, 64, 0)` | Destroyed |

### 1.4 Radar / sensor affiliation colours

For the F4 Science sensor disc.

| Token | SDK name | Value | Affiliation |
|---|---|---|---|
| `--bc-radar-friendly` | `g_kRadarFriendlyColor` | `rgb(80, 112, 230)` blue | Friendly contact |
| `--bc-radar-enemy` | `g_kRadarEnemyColor` | `rgb(216, 43, 43)` red | Hostile contact |
| `--bc-radar-neutral` | `g_kRadarNeutralColor` | `rgb(255, 255, 175)` pale yellow | Neutral contact |
| `--bc-radar-unknown` | `g_kRadarUnknownColor` | `rgb(128, 128, 128)` grey | Unknown affiliation |
| `--bc-radar-torpedo` | `g_kSTRadarIncomingTorpColor` | `rgb(255, 255, 0)` yellow | Incoming torpedo |

### 1.5 Shim-defined constants

Not in the SDK directly; added by the shim because the SDK leaves these implicit.

| Token | Value | Used for |
|---|---|---|
| `--bc-chosen-gold` | `rgb(255, 210, 90)` | Chosen-row caret (`▸`), radio "filled" indicator |
| `--bc-label-text` | `rgb(235, 225, 255)` | Default row label colour |
| `--bc-body-bg` | `rgba(10, 10, 16, 0.85)` | Panel body translucent fill |
| `--bc-offline-fill` | `rgba(60, 10, 10, 0.6)` | Power-grid OFFLINE segment darker fill |
| `--bc-hull-healthy` | `rgb(50, 210, 80)` | Hull integrity ≥70% |
| `--bc-hull-damaged` | `rgb(255, 200, 60)` | Hull integrity 25–70% |
| `--bc-hull-critical` | `rgb(255, 80, 40)` | Hull integrity <25% |
| `--bc-hull-track` | `rgb(40, 40, 40)` | Hull-bar empty track |
| `--bc-disc-bg-inner` | `rgb(8, 12, 32)` | Sensor disc inner gradient stop |
| `--bc-disc-bg-outer` | `rgb(2, 4, 16)` | Sensor disc outer gradient stop |

---

## 2. Widget factory API

The SDK creates UI widgets by calling factory functions on `App`. The engine's job is to return a widget object that:
1. Records the construction (label / event / flags)
2. Honours subsequent mutator calls (`SetEnabled`, `SetLabel`, `SetChosen`, etc.)
3. Renders correctly when added to a parent via `parent.AddChild(child, x, y, z)`

All factory functions come in two forms: `_Create(...)` (narrow / ASCII text) and `_CreateW(...)` (wide / unicode text). The shim treats them identically; the `W` suffix is a legacy SWIG distinction.

### 2.1 Primitive containers

| Function | Args | Returns | Renders as |
|---|---|---|---|
| `TGPane_Create(...)` | (no args) | `_TGPane` | Empty container; children laid out in absolute position by `AddChild(child, x, y, z)`. Used for free-positioned overlays. |
| `TGParagraph_Create()` / `_CreateW()` | (no args) | `_TGParagraph` | Single text paragraph. `.SetTextW(text)` or `.SetText(text)` sets content. |
| `TGIcon_Create(group_name, index, color=None)` | `group_name: str, index: int, color: tuple?` | `TGIconElement` | Icon from a previously-registered `TGIconGroup` (see §2.4 below). |
| `TGFrame_Create(...)` | (no args) | `_TGFrame` | Border frame (typically used to wrap a sub-section). |

### 2.2 Buttons

```python
# Standard text button
STButton_Create(label: str = "", event: TGEvent? = None, flags: int = 0) -> _STButton
STButton_CreateW(label: str = "", event: TGEvent? = None, flags: int = 0) -> _STButton
```

**Flags:**
| Flag | Value | Meaning |
|---|---|---|
| `STBSF_DEFAULT` | `0` | Default button (no special sizing) |
| `STBSF_SIZE_TO_TEXT` | `1` | Auto-size width to fit the label |
| `STBSF_NO_AUTOHIGHLIGHT` | `2` | Don't apply the hover-highlight state automatically |

**Mutators on `_STButton`:**
| Method | Effect |
|---|---|
| `SetLabel(text)` | Update button text |
| `SetEnabled(enabled: bool)` | Enable / disable. Disabled buttons render in `--bc-subsystem-disabled` and reject clicks. |
| `SetDisabled(disabled: bool)` | Same as `SetEnabled(not disabled)` |
| `SetChosen(chosen: bool)` | Set / clear the "chosen" radio state (row gets `--bc-row-chosen-bg` styling). |
| `IsChosen()` | Read the chosen flag |
| `SetEvent(event: TGEvent)` | Bind a different event to fire on click |
| `SendActivationEvent()` | Programmatically fire the bound event |

**Other button variants** (same args, different chrome):

| Function | Use case |
|---|---|
| `STRoundedButton_Create / _CreateW` | LCARS pill button with rounded ends (used in modal dialog button row) |
| `TGButton_Create` | Plain text button without ST chrome (legacy) |
| `TGTextButton_Create / _CreateW` | Like TGButton but with explicit text styling |
| `STToggle_Create / _CreateW(label, default_on=0, label_on=None, on_event=None, off_event=None)` | Boolean toggle button (e.g. Tractor/Cloak); shows different labels for on/off |
| `STTiledIcon_Create(group: str, index: int)` | Pure icon button, no text |
| `STFillGauge_Create()` | A bar/gauge widget (used for the engineer's pillar gauges) |
| `STWarpButton_Create / _CreateW` | Specialised button for the warp-engage row |

### 2.3 Menus

Menus are containers for buttons (each `AddChild(button)` appends a row). Four kinds, all with the same factory shape:

```python
STTopLevelMenu_Create(label: str = "") -> _STTopLevelMenu       # primary menus (Tactical, Engineer)
STTopLevelMenu_CreateW(label: str = "") -> _STTopLevelMenu
STTopLevelMenu_CreateNull(label: str = "") -> _STTopLevelMenu   # menu that's never bound to a panel
STMenu_Create(label: str = "") -> _STMenu                       # sub-menus (Manoeuvres, Tactics)
STMenu_CreateW(label: str = "") -> _STMenu
STCharacterMenu_Create(label: str = "") -> _STCharacterMenu     # officer-presents-a-character menu
STCharacterMenu_CreateW(label: str = "") -> _STCharacterMenu
STTargetMenu_Create(label: str = "") -> _STTargetMenu           # menu populated from target list
STTargetMenu_CreateW(label: str = "") -> _STTargetMenu
```

Plus type casts:
```python
STMenu_Cast(obj) -> _STMenu?           # type-check / return None if not a menu
STTopLevelMenu_Cast(obj) -> _STTopLevelMenu?
```

**Mutators / behaviour:**

| Method | Effect |
|---|---|
| `AddChild(button: _STButton, x=0, y=0, z=0)` | Append the button as a new row. SDK ignores `x/y/z` — layout is HTML-driven. |
| `RemoveChild(button)` | Remove a row |
| `KillChildren()` | Clear all rows (preserves the menu shell) |
| `DeleteChild(button)` | Same as RemoveChild + button cleanup |
| `SetLabel(text)` | Update menu title |
| `SetEnabled(enabled)` / `SetDisabled(disabled)` | Disabled menus reject clicks on rows |
| `SetFocus(button)` | Make a specific button the "focused" / hovered row |
| `Open()` | Set menu's `_open = True` (header collapse glyph `▲`) |
| `Close()` | Set menu's `_open = False` (header collapse glyph `▼`) |
| `GetButtonW(label)` | Find a button by its label (returns existing or auto-vivified empty button) |

**Radio-group semantics:** When the SDK calls `SetChosen(True)` on a button inside a menu, the engine must call `SetChosen(False)` on every sibling. The `_STMenu._select` method enforces this.

### 2.4 Icons (`g_kIconManager`)

The SDK registers icon groups at bridge load time:

```python
pGroup = App.g_kIconManager.CreateIconGroup("NormalStyleFrame")
App.g_kIconManager.AddIconGroup(pGroup)
pTexture = pGroup.LoadIconTexture("Data/Icons/Bridge/NormalStyleFrame.tga")
pGroup.SetIconLocation(0, pTexture, 0, 0, 12, 22)   # index, texture, x, y, w, h
```

Then individual icons are created via:

```python
icon = App.TGIcon_Create("NormalStyleFrame", 0)  # group name + index
```

The engine maps `(group_name, index)` → a friendly CSS class fragment via `engine/sdk_ui/icon_classmap.py`. The class names come from comments in the SDK's `StylizedWindow.py:62-106`. Example:

| (group, index) | CSS class fragment | Visual |
|---|---|---|
| ("NormalStyleFrame", 0) | `bc-frame-tl-curve` | Top-left curved frame corner |
| ("NormalStyleFrame", 1) | `bc-frame-tr-curve` | Top-right curved frame corner |
| ("NormalStyleFrame", 2) | `bc-frame-bl-curve` | Bottom-left curved frame corner |
| ... | ... | ... |

The full classmap is in `engine/sdk_ui/icon_classmap.py`. For the CEF rebuild, icons should be rendered as styled `<div>` or `<span>` elements with the friendly class — not as raster textures.

### 2.5 Stylized windows

```python
STStylizedWindow_Create(title, x, y, w, h, parent=None) -> _STStylizedWindow
STStylizedWindow_CreateW(title, x, y, w, h, parent=None) -> _STStylizedWindow
STSubPane_Create(...) -> _STSubPane
```

`STStylizedWindow` is the SDK's window primitive. In CEF terms it maps to a `bc-panel` instance with its `data-panel` attribute set to the title. The SDK uses `STStylizedWindow` for the engineer panel, target list, modal dialog, and most other top-level widgets.

### 2.6 Domain widgets

These are higher-level factories that compose the primitives. The engine maps each to a specific CEF panel:

| Function | Maps to | Mockup |
|---|---|---|
| `App.WeaponsDisplay_Create(parent, ...)` | `weapons_speed` panel (Weapons section) | [04](04-weapons-and-speed.md) |
| `App.SpeedDisplay_Create(parent, ...)` | `weapons_speed` panel (Speed section) | [04](04-weapons-and-speed.md) |
| `App.RadarDisplay_Create(parent, ...)` | `science` panel | [05](05-sensors-radar.md) |
| `App.ShipDisplay_Create(parent, ...)` | `shields` readout (player + target) | [03](03-shields-readout.md) |
| `App.EngPowerDisplay_Create(parent, ...)` | `engineer` panel (power grid + pillar gauges) | [06](06-engineer-panel.md), [07](07-power-transmission-grid.md) |
| `App.EngRepairPane_Create(parent, ...)` | `engineer` panel (repair status section) | [06](06-engineer-panel.md) |
| `App.ModalDialogWindow_Cast(...)` | `modal` panel | [08](08-modal-dialog.md) |

The widget's `.Set*()` mutator methods correspond directly to the state-shape documented on each mockup's MD.

### 2.7 Window + viewport singletons

```python
App.g_kRootWindow             # root window (parent of all panes for positioning)
App.g_kTacticalWindow         # tactical-area host window; holds target list + tactical readouts
App.g_kIconManager            # icon-group registry (see §2.4)
App.g_kEventManager           # event bus (see §3 below)
App.g_kInterface              # TGUITheme singleton (used for `App.TGUITheme_Create()`)
```

The bridge SDK looks up `g_kRootWindow.AddChild(pane)` to attach top-level panes. The engine layer must provide these singletons; they're constructed during bridge load in `engine/sdk_ui/host_panels.py`.

---

## 3. Event dispatch (UI → SDK)

The UI fires events back to the SDK via `App.g_kEventManager`. Event types are integer constants defined in `engine/sdk_ui/events.py`:

| Constant | Value | Meaning |
|---|---|---|
| `ET_LOAD_GAME` | 1 | User selected a mission to load |
| `ET_NEW_GAME` | 2 | User chose "New Game" |
| `ET_CANCEL` | 3 | User cancelled a modal / picker |
| `ET_BUTTON_CLICKED` | 4 | Generic button click |
| `ET_SET_TARGET` | (C++ enum) | Player chose a target — destination event sent to the player ship. Target-list row clicks call `pPlayer.SetTarget(name)` which fires this. |
| `ET_TARGET_WAS_CHANGED` | (C++ enum) | Broadcast — fires after `ET_SET_TARGET` so UI panels (TacticalMenuHandlers.TargetChanged et al.) can react. |
| `ET_MENU_OPEN` | 6 | A menu was opened |
| `ET_MENU_CLOSE` | 7 | A menu was closed |
| `ET_OPTION_CHANGED` | 8 | A toggle/cycle widget changed value |
| `ET_RESUME_GAME` | 9 | User resumed (e.g. from pause menu) |
| `ET_QUIT_TO_MAIN_MENU` | 10 | User quit to main menu |
| `ET_GAME_OVER` | 11 | Game-over state reached |

> The SDK does NOT define `ET_TARGET_SELECTED`. Target-list row clicks
> route through `pPlayer.SetTarget(ship_name)` which fires the two
> events above. Earlier drafts of this document listed
> `ET_TARGET_SELECTED = 5`; this has been corrected.

Events are created via:

```python
event = App.TGEvent_Create(event_type: int, name: str)
button.SetEvent(event)         # bind to a button
button.SendActivationEvent()   # programmatically fire
```

Handlers are registered through `App.g_kEventManager`:

```python
App.g_kEventManager.AddBroadcastEventHandler(event_name, callback)
App.g_kEventManager.AddPythonFuncHandlerForInstance(instance, event_name, callback)
App.g_kEventManager.FireEvent(event_name)        # synchronous dispatch
App.g_kEventManager.AddEvent(event)              # queued for next tick
```

The CEF rebuild's `_cef_backend._dispatch_event` is the bridge: renderer-originated `cefQuery({request: 'event:<name>'})` calls land in C++, get dispatched to Python, and Python calls `App.g_kEventManager.FireEvent(name)` so SDK handlers fire as if the click had come from a native click handler.

---

## 4. Engine implementation contract

Given the SDK API above, the engine layer must:

### 4.1 Render

For every panel the SDK constructs, emit per-tick state matching the shape documented in the panel's MD (under `docs/ui_designs/`). The render path is:

```
SDK script → App.<factory>() → engine.sdk_ui Python widget →
  per-tick state dict → _cef_backend.push_state(panel_name, state) →
  C++ ProcessMessage → bridge.js applies to [data-bind] DOM
```

### 4.2 Honour mutators

When the SDK calls a mutator on a widget instance (`pButton.SetEnabled(False)`, `pMenu.AddChild(...)`, etc.), the corresponding engine widget must update its state representation AND push the updated state to the renderer. Most mutators do this lazily — they mutate the Python widget object, then the next tick's `_emit_state()` picks up the change.

### 4.3 Dispatch events

When a user clicks a `[data-event]` element in the renderer, the engine must:
1. Receive the event name via `_cef_backend._dispatch_event(name)`
2. Resolve the corresponding SDK button instance (typically by panel + row index)
3. Call `button._on_click(event)` so the SDK's handler fires
4. Also fire `App.g_kEventManager.FireEvent(name)` so broadcast subscribers see it

### 4.4 Preserve the SDK shape

The SDK code in `sdk/Build/scripts/Bridge/` is **not modified** by the rebuild. Every call signature in §2 must continue to work. The engine widgets in `engine/sdk_ui/` are the implementation layer; they translate SDK calls into render state.

### 4.5 What the engine does NOT need to provide

- **Animations**: panels can transition statically (no fade-in / slide-in required).
- **Mouse hover**: CSS `:hover` is sufficient; no SDK call for hover state.
- **Keyboard focus** beyond click + dispatched events. F-key handling lives outside the SDK (in `engine/host_loop.py`).
- **Sub-pixel positioning**: SDK passes (x, y, z) coordinates to `AddChild`; the engine ignores them and uses CSS layout instead.

---

## 5. Reference paths

| File | Purpose |
|---|---|
| `engine/sdk_ui/palette.py` | Canonical colour palette (SDK + shim) |
| `engine/sdk_ui/__init__.py` | Public re-exports of the shim API |
| `engine/sdk_ui/buttons.py` | All `STButton_*`, `STToggle_*`, `STRoundedButton_*` factories |
| `engine/sdk_ui/menus.py` | All `STMenu_*`, `STTopLevelMenu_*`, `STCharacterMenu_*`, `STTargetMenu_*` factories |
| `engine/sdk_ui/primitives.py` | `TGPane_Create`, `TGParagraph_*`, `TGIcon_Create`, `TGFrame_Create` |
| `engine/sdk_ui/stylized.py` | `STStylizedWindow_*`, `STSubPane_Create` |
| `engine/sdk_ui/icons.py` | `g_kIconManager`, `TGIconGroup`, `TGIcon_Create` |
| `engine/sdk_ui/icon_classmap.py` | (group, index) → friendly CSS class fragment |
| `engine/sdk_ui/events.py` | `TGEvent_Create`, all `ET_*` constants |
| `engine/sdk_ui/theme.py` | `TGUITheme_Create`, `g_kInterface` singleton |
| `engine/sdk_ui/host_panels.py` | `g_kRootWindow`, anchor-based panel positioning |
| `engine/sdk_ui/target_list.py` | `g_kTacticalWindow`, target list widget |
| `engine/sdk_ui/widgets/` | Domain widgets (WeaponsDisplay, RadarDisplay, etc.) |
| `App.py` (project root) | The shim that re-exports everything above as `App.*` |
| `sdk/Build/scripts/Bridge/` | Actual SDK callers — read these to see how the API is used in production |

Most useful SDK callsites to read for examples:
- `sdk/Build/scripts/LoadBridge.py` — bridge construction (creates all the top-level panes)
- `sdk/Build/scripts/Bridge/TacticalMenuHandlers.py` — tactical menu construction + radio behaviour
- `sdk/Build/scripts/Bridge/EngineerMenuHandlers.py` — engineer panel construction
- `sdk/Build/scripts/Bridge/XOMenuHandlers.py` — officer menu construction
- `sdk/Build/scripts/MainMenu/KeyboardConfig.py` — keyboard config modal (modal dialog example)
- `sdk/Build/scripts/StylizedWindow.py` — most STStylizedWindow / STButton usage examples
