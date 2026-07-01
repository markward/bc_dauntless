# Weapons configuration — panel settings view + tactical-menu commands

**Date:** 2026-07-01
**Mockup (canonical):** [../../ui_designs/04b-weapons-combined-config.html](../../ui_designs/04b-weapons-combined-config.html)
**Plan:** `~/.claude/plans/we-are-currently-missing-zany-fog.md`

## Purpose

Bridge Commander's HUD had a middle **Weapons** panel that let the player configure combat systems
(torpedo type, torpedo spread, phaser intensity, tractor on/off, cloak on/off) alongside the torpedo
inventory readout. Dauntless never surfaced those controls — the runtime weapons panel is only the
icon/silhouette readiness view. This feature exposes all of them through **two surfaces**:

1. A **weapon-settings view** inside the existing weapons panel, revealed by a hamburger toggle.
2. Equipment-gated **command rows in the F2 Tactical officer menu**.

Both surfaces drive the *same* engine subsystem APIs, so their state stays in sync.

## Non-goals

- No 1:1 reproduction of BC's original tactical-interface weapons widget.
- Angular spread-pattern *tuning* beyond the three described patterns is out of scope for v1.
- Keyboard-navigation of the settings view is not required for v1 (click-driven, like the mockup).

## Surface 1 — panel weapon-settings view

The existing weapons panel ([engine/ui/weapons_display_panel.py](../../../engine/ui/weapons_display_panel.py)
+ [weapons_display.js/.css](../../../native/assets/ui-cef/panels/weapons_display/)) gains:

- A **hamburger button** (`mode-btn`) floating top-right of the panel body. Default state shows the
  status view **unchanged** (60%-scaled silhouette + per-mount phaser arcs + speed label). Clicking
  it hides the status view and shows the settings view in place; clicking again flips back. Hover
  tooltip: "Weapon settings" / "Hide settings". Hidden entirely if the ship has nothing to configure.
- **Settings view** (`view-settings`), top-aligned:
  - **Torpedoes** section (`section-head` + `section-rule`) — one `torp-row` of two buttons:
    `torp-btn--type` shows `Type (qty)` e.g. *Quantum (250)* (cycles type; renders `--static` grey
    when only one type), and `torp-btn--spread` shows the spread word *Single/Dual/Quad* (cycles).
  - **Phasers** section — an Intensity `row-cycle` cycling *Full / Light*.
  - **Tractor | Cloak** — a `sys-row` of two `sys-btn` toggles at ~50/50; an *on* device fills its
    button with the salmon border colour (`sys-btn--on`), values stay neutral (no green/italic). A
    hull with only one of the two shows a single button at 100% width (`flex:1`).

### Section / control gating

| Element | Shown when |
|---|---|
| Torpedoes section | ship has ≥1 torpedo launcher |
| Type button cyclable | `GetNumAmmoTypes() > 1` (else `--static`) |
| Spread cycles | loadout supports >1 pattern |
| Phasers section | ship has phasers |
| Tractor button | tractor subsystem equipped |
| Cloak button | cloak subsystem equipped |
| Hamburger toggle | any of the above is present |

### Visual language (reused, unchanged)

Antonio font; salmon→orange header gradient; `section-head` gold (rgb 255,154,2); `row-cycle` pink
Menu3 (rgb 246,147,204 @ 35% α, accent rgb 207,96,159); `sys-btn` / toggles salmon Menu1 (rgb
216,94,86); `sys-btn--on` fills solid rgb(216,94,86); neutral value text rgb(235,225,255).

### State shape (Python → JS, `config` block)

```
{ show_settings, has_any_config,
  has_torpedoes, torp_type, torp_count, torp_types_cyclable, spread, spread_options,
  has_phasers, phaser_intensity,
  tractor_present, tractor_on, cloak_present, cloak_on }
```

### Events (JS → Python via `dauntlessEvent('weapons/…')`)

`toggle-view` (panel holds open/closed state), `cycle-type`, `cycle-spread`, `cycle-intensity`,
`toggle-tractor`, `toggle-cloak`. Each dispatch calls the shared engine helper (below) and lets the
next-tick snapshot re-render.

## Surface 2 — F2 tactical-menu commands

Equipment-gated command rows appended to the SDK **Tactical** menu (built by
`Bridge/TacticalMenuHandlers.CreateTacticalMenu`, rendered by
[engine/ui/crew_menu_panel.py](../../../engine/ui/crew_menu_panel.py) via `TacticalControlWindow` →
`STTopLevelMenu`/`STButton`). Buttons created with
`BridgeUtils.CreateBridgeMenuButton(label, event, subevent, dest)`; reuse existing
`BridgeHandlers.ToggleCloak` / `ToggleTractorBeam` where possible.

| # | Command label (dynamic) | Shown when | Action |
|---|---|---|---|
| 3a | **Set Phasers to Light** / **…to Full** | phasers present | flip `PhaserSystem.SetPowerLevel(PP_LOW/PP_HIGH)` |
| 3b | **Use {next type} Torpedoes** | `GetNumAmmoTypes() > 1` | advance `SetAmmoType(nextSlot)` |
| 3c | **Torpedo Spread {current}** | >1 spread available | cycle `SetSpread` |
| 3d | **Engage / Disengage Tractor** | tractor present | tractor toggle |
| 3e | **Engage / Disengage Cloak** | cloak present | `StartCloaking` / `StopCloaking` |

**Dynamic labels** — add `STButton.SetLabel()` in
[engine/appc/characters.py](../../../engine/appc/characters.py); `CrewMenuPanel` already re-snapshots
labels each tick, so a per-tick/refresh label update surfaces automatically. Labels reflect the
*result* of clicking (3a/3d/3e) or the current selection (3b next type, 3c current spread).

## Shared engine helpers (single source of truth)

Both surfaces call one set of helpers so state stays consistent (toggling cloak from the menu updates
the panel's Cloak button next tick and vice-versa). Existing APIs
([engine/appc/weapon_subsystems.py](../../../engine/appc/weapon_subsystems.py),
[subsystems.py](../../../engine/appc/subsystems.py)): torpedo `GetNumReady`/`GetCurrentAmmoType`/
`SetAmmoType`/`GetNumAmmoTypes`; phaser `Get/SetPowerLevel`; tractor `StartFiring`/`StopFiring`/
`IsFiring`; cloak `StartCloaking`/`StopCloaking`/`IsCloaked`. New from Phase 2: torpedo
`Get/SetSpread` + volley/fan-out firing.

## Testing

- Panel unit tests: each dispatch calls the right helper and flips the snapshot; sections/buttons
  gate by subsystem presence; lone-toggle-fills-row; hamburger hidden when nothing to configure.
- Menu unit tests: label reflects state and flips after action; command present only when equipped;
  click invokes the right helper.
- Spread firing tests: Single=1 / Dual=2 / Quad=4 tubes; homing suppressed during `_homing_start_age`
  then engages; Dual/Quad initial directions diverge with correct sign.
- Full gate: `scripts/check_tests.sh` green apart from the known 7 headless-GL FrameTests.

## Risks / open items

- **Axis convention for Quad diamond** — implemented as the target-facing plane (±local-X and
  ±local-up); flagged for confirmation (engine body frame is Y-forward/X-starboard/Z-up).
- Settings-view height must not clip the panel's HUD zone (`index.html`); verify at runtime.
