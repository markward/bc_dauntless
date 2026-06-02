# Tactical UI — implementation state

Snapshot as of 2026-06-02 (post-merge of layout-zones + SpeedDisplay). Maps each tactical-view panel to:
- Its mockup under `docs/ui_designs/`
- Its SDK factory function
- The engine implementation (or "stub" if NamedStub-absorbed)
- Per-tick refresh source
- Current CSS positioning (and the layout-system gap)

## Panels in tactical view

| Panel | Mockup | SDK factory | Engine impl | Per-tick source | Position today |
|---|---|---|---|---|---|
| Target list | [02](02-tactical-cluster.md) | `STTargetMenu_CreateW` | `engine/ui/target_list_view.py` + `engine/appc/target_menu.py` | Subscribes to player's spatial set; reads `player.GetTarget()`, hull/shield % per row | Flex child of `#tactical-target-stack` in the 224 px-wide left column |
| Radar / sensors | [05](05-sensors-radar.md) | `RadarDisplay_Create` | `engine/ui/sensors_panel.py` + `engine/appc/radar.py` | Walks player's spatial set, projects positions to the disc each tick | Flex child of `#tactical-radar` (pinned bottom of left column) |
| Ship display × 2 (player + target shields/hull) | [03](03-shields-readout.md) | `ShipDisplay_Create` | `engine/ui/ship_display_panel.py` + `engine/sdk_ui/widgets/ship_display.py` | `player.GetHull()/GetShields()` (player role); `player.GetTarget().GetHull()/GetShields()` (target role) | Player → `#tactical-bottom-row` flex-end; target → first child of `#tactical-target-stack` (above the target list) |
| Speed | [04](04-weapons-and-speed.md) | (no SDK call yet — eager construction) | `engine/ui/speed_display.py` | Reads `_PlayerControl._current_speed` + `_warp_boost`; max from `player.GetImpulseEngineSubsystem().GetMaxSpeed()` | Flex child of `#tactical-bottom-row`, to the left of the player ship-display |
| Pause menu (legacy overlay, not a Panel subclass) | [10](10-pause-menu.md) | dauntless-native (ESC keybind) | `engine/ui/pause_menu.py` | Held in Python state; only emits while paused | Full-screen modal |

## Panels NOT YET implemented (SDK factories present but NamedStub-absorbed → no-op)

| Panel | Mockup | SDK factory | Where it'd plug in |
|---|---|---|---|
| Weapons display (torp + phaser cycle) | [04](04-weapons-and-speed.md) | `WeaponsDisplay_Create` | Bottom row, to the left of Speed |
| Engineer panel (F5: power grid + system rows + tractor/cloak) | [06](06-engineer-panel.md), [07](07-power-transmission-grid.md) | `EngPowerDisplay_Create` + `EngRepairPane_Create` | Bottom-right, large; only visible when F5 is the active station |
| Officer menu (F1 Helm / F3 XO / F6 Guest etc.) | [01](01-officer-menu.md) | `STTopLevelMenu_Create*` (shim in `engine/appc/characters.py`, no CEF render yet) | Stacks in the left column above the target list when an officer menu is opened |
| Tactical cluster (F2: TACTICAL + ORDERS + MANOEUVRES + TACTICS) | [02](02-tactical-cluster.md) | `STTopLevelMenu_Create*` again | Stacks in the left column; replaces target list focus when F2 is open |
| Modal dialog (quit confirm, save prompt, etc.) | [08](08-modal-dialog.md) | `ModalDialogWindow_Cast` | Full-screen modal overlay |

## Layout zones

Panels render as flex children of two top-level containers in `hello.html` — no per-panel `position: absolute|fixed`. Tweaking the zone CSS reflows everything inside it.

```html
<body>
  <div id="tactical-left-column">          <!-- fixed top:24 left:24 bottom:24 width:224 -->
    <div id="tactical-target-stack">       <!-- flex:1 1 auto, gap:8 -->
      <!-- ship-display-target (when a target is selected) -->
      <!-- target-list-panel -->
      <!-- (later: officer menus prepended when F1/F3 is open) -->
    </div>
    <div id="tactical-radar">              <!-- flex:0 0 auto, margin-top:12 -->
      <!-- sensors-panel -->
    </div>
  </div>

  <div id="tactical-bottom-row">           <!-- fixed right:0 bottom:0 flex-end -->
    <!-- max-width: calc(100vw - 224px - 24px) -->
    <!-- panels stack right→left; player ship-display rightmost -->
    <!-- speed-display, ship-display-player -->
    <!-- (later: WeaponsDisplay, AlertBanner) -->
  </div>
</body>
```

Click forwarding from the host to CEF is gated on two bboxes in `engine/host_loop.py` (`_cursor_in_left_column`, `_cursor_in_bottom_row`) that mirror the zone positions. New zones or width changes need both the CSS and the bbox kept in lockstep, or clicks silently swallow / mis-fire phasers.

Note: SDK x/y/z coords from `Create*` and `AddChild` are deliberately ignored — see [SDK_UI_API.md §4.5](SDK_UI_API.md). We route to containers by *which factory was called*, not by what coords it passed.

## Key architectural conventions (carried forward from target-list work)

- `engine/ui/panel.py` — `Panel` ABC: `name`, `visible`, `render_payload`, `dispatch_event`, `invalidate`
- `engine/ui/panel_registry.py` — registry + slash-prefixed event routing + legacy fallback for pause menu
- Each panel: own Python file in `engine/ui/`, own JS file in `native/assets/ui-cef/js/`, own CSS, own HTML container
- Per-tick render: `registry.render_all()` collects `setXxx({...})` JS snippets and pushes via `cef_execute_javascript`
- JS→Python click events: `dauntlessEvent('panel/action')` → `console.info('dauntless-event:panel/action')` → C++ `OnConsoleMessage` → Python callback → `PanelRegistry.dispatch`
- CEF renders at device-pixel resolution (DSF wired through `cef_initialize`); composite blits 1:1 — text is crisp
- HTML-escape ship/subsystem names via helpers in `target_list.js` (`escapeHtml`, `escapeJsString`, `clickAttr`) — reuse the pattern for new panels

## Per-panel state-source quick reference (for the panels not yet built)

- **Weapons**: `player.GetTorpedoSystem()` → array of tubes with `GetCurrentTorpedoType()` and reload countdown; `player.GetPhaserSystem()` → array of phaser banks with charge level
- **Speed**: `player.GetImpulseEngineSubsystem().GetCurrentSpeed()` and `.GetTopSpeed()`; warp factor from `player.GetWarpEngineSubsystem()`
- **Engineer power grid**: `player.GetPowerSubsystem()` → per-system power allocation; tractor/cloak via subsystem toggles
- **Officer menu**: enumerated from `STTopLevelMenu` children — already shimmed; needs Panel + CEF render

## Deferred (intentionally not yet wired)

- Persistent target save/load (engine has no save/load yet)
- Sensor identification (`ShowUnknownName` / `ShowRealName`) — engine drives, not SDK
- Per-subsystem health bars (slot exists in target list CSS but data path not wired)
- Reticule rendering in 3D scene (parked)
- Localized ship display names (`ship.GetName()` is used as the row label)
