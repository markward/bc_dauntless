# Engineering Menu — UI Specification

Officer: **Lt. Cmdr. Brex** • Hotkey: **`F5`** • Source of truth: [bridge-mode.md § Engineering](bridge-mode.md#engineering-brex-menu--f5)

The Engineering menu is unique: it is not a single column of commands but a **multi-panel dashboard** that fills most of the screen. Two panel clusters appear together — the **Engineering damage-control stack** (upper-left) and the **Power Transmission Grid** (upper-right).

---

## Left cluster — Damage-control stack

Anchored to the **upper-left** of the viewport. Three stacked panels:

```
┌── Engineering ───────────────┐
│ ● Report                     │   ← officer's only menu row
├──────────────────────────────┤
│ Repair team assignments:     │
│  • <system #1>               │   ← up to 3 rows; click row to demote
│  • <system #2>               │
│  • <system #3>               │
├──────────────────────────────┤
│ Damaged systems:             │
│  • <queued damaged system>   │   ← click row to promote to top
│  • ...                       │
├──────────────────────────────┤
│ Destroyed systems:           │
│  • <unrepairable system>     │   ← read-only; needs Starbase 12
│  • ...                       │
└──────────────────────────────┘
```

In screenshots 1 and 8 all three lists are empty (no damage). Each list has its own thin title bar with the section name (pale yellow text on a coral band).

### Row state observations

- Rows are clickable in *Repair team assignments* and *Damaged systems* — those clicks reorder the repair queue (demote / promote).
- Rows in *Destroyed systems* are read-only; the only repair path is docking at Starbase 12 (via Helm).

---

## Right cluster — Power Transmission Grid

Anchored to the **upper-right**. The panel has a top-right collapse arrow `▼` that minimises it to the title bar (consistent with all other minimisable HUD panels).

```
┌── Power Transmission Grid ──────────────────────────────┐ ▼
│ Power Used:                                             │
│ [████████████░░░░░░░░░░░░░] ← multi-band horizontal bar │
│                                                         │
│ Weapons         [──────────█──]  100%        │ │ │      │
│ Engines         [──────────█──]  100%        │ │ │      │
│ Sensor Array    [──────────█──]  100%        │ │ │      │
│ Shield Generator[──────────█──]  100%        │ │ │      │
│                                              100% 98% 99%
│                                              ─── ─── ───
│                                              Warp Main Reserve
│                                              Core Batt Power
│                                                         │
│ Tractor: Off                                            │
└─────────────────────────────────────────────────────────┘
```

### Power Used bar

A single horizontal segmented bar. The frame around it is **colour-banded** to indicate which energy source is currently supplying the draw:

| Band | Human name | Hex (approx.) | Meaning |
|---|---|---|---|
| Blue band (left) | Cyan / sky blue | `#3399CC` | Warp-Core production; surplus charges batteries |
| Yellow band (middle) | Gold | `#FFCC00` | Bar has spilled into Main Battery draw |
| Red band (right) | Crimson | `#CC3333` | Reserve Battery now also being drawn |

The filled portion of the bar reflects total instantaneous system draw.

### Per-system sliders

Four rows — **Weapons**, **Engines**, **Sensor Array**, **Shield Generator** — each is a horizontal slider with:

- Slider track (lavender background).
- Movable thumb (pink/magenta vertical bar).
- Right-side numeric percentage label `0–125%` (yellow text).
- Background colour-codes the system identity:
  - Weapons row: pink (`#CC6699`)
  - Engines row: bright magenta (`#CC33CC`)
  - Sensor Array row: yellow-gold (`#CC9933`)
  - Shield Generator row: pale violet (`#9966CC`)

100% is the nominal capacity. Range is `0%` to `125%`; manual states no penalty beyond the extra draw for boosting to 125%.

### Source gauges (right edge, three vertical bars)

Three vertical bars sit at the right margin of the grid, labelled at their bases:

| Position | Source | Behaviour |
|---|---|---|
| Left | Warp Core | Production capacity; falls as the core takes damage; 0% = warp-core breach |
| Centre | Main Battery | Stored charge; depletes when usage > production |
| Right | Reserve Power | Stored charge; depletes only when Main is also draining |

In screenshot 1 the readouts are 100% / 98% / 99% respectively.

The bars share the blue/yellow/red colour banding of the Power Used bar — fill colour shows current level.

### Conditional rows

If the ship hull has them, two extra rows appear below the sliders (visible only in some screenshots):

- **Tractor: On / Off** — current tractor state; draws from Main Battery while engaged. Screenshots 1 and 8 show `Tractor: Off`.
- **Cloak: On / Off** — multiplayer / Quick Battle ships only; draws from Reserve Battery while engaged.

---

## When the menu opens

### What appears

- Left damage-control stack at upper-left.
- Power Transmission Grid at upper-right.

### What disappears or stays hidden

- Any other officer menu closes.
- In **interior** mode the combat HUD at the bottom edge stays hidden unless Red Alert is active.
- The Power Grid panel can be **individually collapsed** via its `▼` button without closing the Engineering menu — the damage-control stack remains open.

### Interior view (Bridge)

- Brex (or whoever is at Engineering — Brex may also be reachable through Saffi's *Contact Engineer*) is visible centred in the viewport behind the panels (screenshot 1).
- Bridge interior fills the gap between the two clusters.

### Exterior view (Tactical mode)

- Brex is not on screen; the player ship is visible in third-person (screenshot 8).
- The persistent bottom-edge HUD remains drawn (Sensors, Shields, Weapons, Speed/Phaser-Arc) **beneath** the Engineering panels — they do not hide it.
- Target Shields and Targets list (left edge, below the damage-control stack) remain visible when a target is selected.

### Differences between interior and exterior

| Aspect | Interior | Exterior |
|---|---|---|
| Officer rendered | Yes (Brex centred) | No |
| Bottom HUD present | Only at Red Alert | Always |
| Panel layout | Identical | Identical |
| Power Grid collapse `▼` | Works | Works |
| Damage-icon overlays on player ship image | N/A — ship image not shown in Engineering panel itself | Same; icons appear on the *Target Shields* mirror image instead |

---

## Colour reference

| Element | Human name | Hex (approx.) |
|---|---|---|
| Engineering title band | Coral / red-orange | `#CC3333` |
| Section title bands (Repair / Damaged / Destroyed) | Coral / red-orange | `#CC3333` |
| Panel frame | Coral red outline on black | `#CC3333` on `#000000` |
| Title text | Yellow gold | `#FFCC00` |
| Body / list text | Yellow gold | `#FFCC66` |
| Power-grid title band | Yellow gold | `#FFCC66` |
| Slider track | Lavender | `#CC99CC` |
| Weapons slider row | Pink | `#CC6699` |
| Engines slider row | Magenta | `#CC33CC` |
| Sensor Array slider row | Gold-tan | `#CC9933` |
| Shield Generator slider row | Pale violet | `#9966CC` |
| Power-used blue band | Cyan blue | `#3399CC` |
| Power-used yellow band | Gold | `#FFCC00` |
| Power-used red band | Crimson | `#CC3333` |
| Source-gauge fill (healthy) | Cyan blue | `#3399CC` |
| Collapse arrow `▼` | Yellow on dark | `#FFCC00` |

---

## Damage icons (where they appear)

Brex's damage-control stack lists **text rows** for damaged systems, not icons. The corresponding **glyph icons** for those systems appear:

- On the *Target Shields* HUD panel (upper-left) when a hostile target is selected — drawn on the target's hull diagram to show its damage state.
- (And on the equivalent panel for the player's ship image, as documented in [tactical-mode.md § Damage Icons](tactical-mode.md#damage-icons).)

Colour code for the glyphs:

- Yellow `#FFCC00` — damaged
- Grey `#888888` — disabled
- Red `#CC0000` — destroyed

See [bridge-mode.md § Damage indicators](bridge-mode.md#damage-indicators-shared-with-tactical-mode) for the icon legend.

---

## Input behaviour

> All key bindings referenced here are the **defaults**. They are remappable through the game's input configuration.

- `F5` — toggle Engineering open / closed.
- Click any row in *Repair team assignments* — **demote** that system (move down priority).
- Click any row in *Damaged systems* — **promote** that system to the top of the repair queue.
- Click any row in *Destroyed systems* — no effect (read-only).
- Drag any slider thumb in the Power Transmission Grid — adjust that system's allocation 0–125%.
- Click `▼` on the Power Transmission Grid — minimise the panel to its title bar.
- Click *Tractor* row — toggle tractor on/off (same effect as Weapons-panel control, or `Alt+T` in Tactical).
- Click *Cloak* row — toggle cloak on/off (if equipped).

---

## Notes

- *Repair team assignments* fills automatically when systems take damage; up to **three teams** auto-assign in damage-arrival order. If only one system is damaged, all three teams pile onto it for 3× speed.
- Auto-adjust: when the Warp Core takes damage, the engine may rebalance the sliders down to fit the reduced production budget.
- Power-budget heuristic the manual gives: stay at Green Alert when not in combat to recharge; if the ship feels sluggish or contacts drop off the Target List, suspect Warp-Core damage or empty batteries.
