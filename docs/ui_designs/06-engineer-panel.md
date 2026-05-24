# 06 — Engineer panel

Visual reference: [06-engineer-panel.html](06-engineer-panel.html)

The F5 Engineer panel. The most information-dense panel in the bridge UI. Composes:

1. **POWER USED stacked bar** (see [07-power-transmission-grid](07-power-transmission-grid.md)) — top of panel body
2. **System rows** — Weapons / Engines / Sensor Array / Shield Generator, each with a percentage fill bar and identifying colour
3. **Pillar gauges** — Warp Core / Main Battery / Reserve Power, vertical bars
4. **Toggle bar** — Tractor (purple) + Cloak (orange), bottom row

## Structure

```
┌─ POWER TRANSMISSION GRID ────────────────────────────▼┐
║                                                       │
║  POWER USED                                           │
║  ┌─────────────────────────────────────────────────┐  │
║  │ ▓▓ blue ████ yellow ███ orange ████             │  │  ← stacked bar (see #07)
║  │ off  warp core    main         reserve          │  │
║  └─────────────────────────────────────────────────┘  │
║                                                       │
║  ● Weapons       ████████████░░░░░░    115%           │  ← system row
║  ● Engines       ████████████░░░░░░    100%           │
║  ● Sensor Array  ██████░░░░░░░░░░░░     60%           │
║  ● Shield Gen    ████████████████░░    110%           │
║                                                       │
║       0%        50%       100%      125%              │  ← tick marks
║                                                       │
║          ┌─┐           ┌─┐           ┌─┐              │  ← pillar gauges
║          │█│           │█│           │█│              │
║          │█│           │█│           │█│              │
║          │ │           │█│ ▼         │█│              │
║          │ │           │█│           │█│              │
║       WARP CORE    MAIN BATTERY  RESERVE POWER        │
║       70% (max)       65%          100%               │
║                                                       │
║   ┌─ Tractor   On ─┐  ┌─ Cloak    Off ─┐              │
└───┴─────────────────┴──┴────────────────┴─────────────┘
```

Panel width: 540 px in the mockup (wider than other panels).

## System rows

Each row identifies a powered subsystem with its **canonical SDK colour** (`g_kEngineering*Color`). Four subsystems:

| Subsystem | Token | Value |
|---|---|---|
| Weapons | `--bc-weapons` | `rgb(207, 139, 76)` (orange) |
| Engines | `--bc-engines` | `rgb(199, 76, 200)` (magenta) |
| Sensor Array | `--bc-sensors` | `rgb(201, 203, 76)` (olive) |
| Shield Generator | `--bc-shields` | `rgb(150, 129, 222)` (lavender) |

### Row anatomy

- Grid layout: `[110 px label] [1fr bar] [50 px percentage]`
- Label colour: `--bc-row-text-bright`
- Bar: 10 px tall, no border, fill in the subsystem identity colour
- Bar background (empty track): dark tint of the identity colour at ~25% opacity
- Percentage text: tabular numerics, right-aligned, identity-colour
- Each row has a colour-dot indicator (the identifying colour as a 6 px square) at the left

### Bar fill semantics

- 0–100% renders normally
- 100–125% is the "boost" range — the bar overshoots its track. Either:
  - **Visual overflow** (current implementation): bar extends past 100% mark
  - **Pre-scaled** (recommended): map `pct → pct/125 × 100` so the thumb stays inside the 100%-wide track and the value labels read true. The Python widget should do this scaling, not bridge.js.

## Percentage tick marks

Below the four system rows, a horizontal axis with labels at 0%, 50%, 100%, 125%:
- Font: Antonio 10 px, weight 400
- Colour: `--bc-row-text-dim`
- 1 px hairline at the tick positions

## Pillar gauges

Three vertical bars at the bottom representing **power sources** (not consumers):

| Pillar | Token | Value | Note |
|---|---|---|---|
| Warp Core | `--bc-warp-core` | `rgb(22, 105, 207)` (blue) | Damage cap: any fraction above ~70% may be unavailable due to damage — show as a hatched overlay at the top of the bar |
| Main Battery | `--bc-main-battery` | `rgb(180, 157, 64)` (yellow) | When draining: show a downward `▼` indicator inside the fill, near the current drain level |
| Reserve Power | `--bc-reserve-power` | `rgb(208, 87, 42)` (orange) | Solid fill, no special indicators |

### Pillar anatomy

- Width: 50 px, Height: 80 px
- Track background: `rgba(15, 12, 35, 0.9)`, 1 px solid border in the pillar's colour at 40% opacity
- Fill: bottom-up, fill height = percentage
- Name label: Antonio 10 px, weight 600, in `--bc-row-text-dim`, below the bar
- Percent label: Antonio 11 px, weight 600, in the pillar's identity colour, below the name
- Optional suffix (e.g. "(max)" on Warp Core when at capacity): same font, in `--bc-row-text-dim`

## Toggle bar (Tractor / Cloak)

Two side-by-side rows at the very bottom of the panel:

| Toggle | Token | Active colour | Inactive colour |
|---|---|---|---|
| Tractor | `--bc-tractor` | `rgb(150, 129, 222)` (lavender / Shield-Gen tone) | muted grey |
| Cloak | `--bc-cloak` | `rgb(235, 128, 21)` (vivid orange) | muted grey |

Each row: label on the left in `--bc-row-text-bright`, "On" / "Off" state text on the right in the active colour (or `--bc-subsystem-disabled` when off).

Clicks fire `Engineer.ToggleTractor` / `Engineer.ToggleCloak` events.

## SDK runtime contract

```python
pEng = App.EngPowerDisplay_Create(parent, ...)
pEng.SetSubsystemPercent("weapons", 115)
pEng.SetSubsystemPercent("engines", 100)
pEng.SetSubsystemPercent("sensor_array", 60)
pEng.SetSubsystemPercent("shield_gen", 110)
pEng.SetPillar("warp_core", 70, suffix="(max)")
pEng.SetPillar("main_battery", 65, drain=True)
pEng.SetPillar("reserve_power", 100)
pEng.SetTractor(True)
pEng.SetCloak(False)
# Power-used stacked bar is updated automatically from the SDK's
# power-flow ledger; see #07 for its data shape.
```
