# 06 — Engineer panel

Visual reference: [06-engineer-panel.html](06-engineer-panel.html) (v28 locked mockup)

The F5 Engineering panel. Shows power allocation sliders, the used/available bar pair, battery-glyph pillars, and siphon-line toggles for tractor beam and cloak. Updated to the v28 redesign (2026-07-06); see "Deviations from old canon" below.

## Structure

```
┌────────────────────────────────────────────────────────────┐ ← no header; 4px salmon left stripe only
║  Weapons    ████████████████░░░░░░░  115%                   │ ← slider row (drag anywhere on track)
║  Engines    ███████████████████░░░░  100%                   │
║  Sensor Array ██████████░░░░░░░░░░░   60%                   │
║  Shields    ████████████████████░░░  110%                   │
║                                                             │
║  0%         50%          100%        125%                   │ ← tick row (0/40/80/100% of track width)
║                                                             │
║  ┌─────────────────────────────────────────────────────┐   │ ← USED bar (28px)
║  │▓▓▓▓│ ████ weapons ████ engines ████ sensors ██ sh.. │   │   damage col + stacked demand segments
║  └─────────────────────────────────────────────────────┘   │
║  ┌─────────────────────────────────────────────────────┐   │ ← AVAILABLE bar (14px, 14px below USED)
║  │▓▓▓▓│ ████████ WARP CORE │ ████ MAIN │ ████ RESERVE │   │   damage col + 3 source segments + ticks
║  └─────────────────────────────────────────────────────┘   │
║        WARP CORE              MAIN           RESERVE        │ ← segment label row (fades <40px wide)
║                                                             │
║  ┌──────────┐   [Tractor On ] ←──── solid/glow  ┌────────┐ │ ← bottom row
║  │   MAIN   │   [Cloak   Off] - - - dashed - - →│RESERVE │ │
║  │  battery │                                    │battery │ │
║  │  (75px)  │                                    │ (50px) │ │
║  │   █████  │                                    │  ████  │ │
║  │   ████▼  │                                    │        │ │
║  │    67%   │                                    │  100%  │ │
║  └──────────┘                                    └────────┘ │
└────────────────────────────────────────────────────────────┘
```

Panel width: ~540 px, top-right, visible only while the Engineering crew menu is open.

## Deviations from old canon (v27 → v28)

| Old (pre-v28) | New (v28) |
|---|---|
| Panel header bar present | **Headerless** — chrome is the 4 px salmon left stripe only |
| System rows had colour-dot indicators | No colour dots; subsystem identity colour on the track and percentage text only |
| Single POWER USED bar (14 px, four buckets inc. OFFLINE) | **USED/AVAILABLE bar pair** — two stacked bars sharing one axis; USED 28 px + AVAILABLE 14 px; damage column spans both |
| WARP CORE, MAIN, RESERVE pillar gauges (three vertical bars) | Warp-core pillar **removed**; only MAIN (75 px) and RESERVE (50 px) battery glyphs remain |
| MAIN and RESERVE pillars same width | MAIN **1.5× wider** (75 px vs 50 px) |
| No pillar battery iconography | Each battery glyph has a rounded **terminal bump** on top; fill bottom-up in battery colour; ▼ inside fill when net flow is negative |
| Tractor/Cloak toggles as plain rows | Toggles sit **between** the batteries; **siphon lines** connect each toggle to its battery (MAIN ← Tractor, RESERVE → Cloak); solid + glow when On, dashed when Off |
| Tractor and Cloak always rendered | **Conditional presence** — Tractor renders only when hardpoints include a tractor emitter; Cloak renders only when ship has a cloaking subsystem |
| Subsystem labelled "Shield Generator" | Labelled **"Shields"** |

## Slider rows

Four rows: Weapons / Engines / Sensor Array / Shields.

Grid layout: `[100 px label] [1fr track] [50 px %]`.

The row IS the slider — drag anywhere on the 10 px track; `cursor: ew-resize`. Track styled as a 25%-opacity tint of the subsystem identity colour. A 3 px white glowing **thumb line** marks the set point. A faint 1 px hairline sits at the **80 % track position** (= 100 % power; track spans 0–125 % pre-scaled: `width = pct/125`). Percentage text in identity colour, tabular numerics.

### Subsystem identity colours

| Subsystem | Token | Value |
|---|---|---|
| Weapons | `--bc-weapons` | `rgb(207, 139, 76)` (orange) |
| Engines | `--bc-engines` | `rgb(199, 76, 200)` (magenta) |
| Sensor Array | `--bc-sensors` | `rgb(201, 203, 76)` (olive) |
| Shields | `--bc-shields` | `rgb(150, 129, 222)` (lavender) |

## Tick row

Below the slider rows: labels at 0 % / 50 % / 100 % / 125 % positioned at their TRUE track fractions (0 / 40 % / 80 % / 100 % of track width). 100 % label brightened. Font: Antonio 10 px, weight 400, `--bc-row-text-dim`. Spans exactly the track column.

## USED / AVAILABLE bar pair

Two bars stacked with a 14 px gap, sharing one full-width horizontal axis.
A **damage hatch** (red diagonal) spans the right side of BOTH bars — the slice
of bandwidth lost to reactor damage. The usable axis (warp-core + main + reserve)
occupies the left portion; used bar and available bar both start at `left:0`.

**Faithful axis (PowerDisplay.py:734,681-689):**
`D = GetMaxMainConduitCapacity() + GetBackupConduitCapacity()` (~1400 Galaxy).
Four grid pieces are fractions of D and sum to 1.0:
`warp_core + main + reserve + damage = 1.0`.
Reserve-drain threshold (`reserve_threshold = GetMainConduitCapacity()/D ≈ 0.8571`):
when the used bar crosses this mark, the ship draws from reserve/backup power.

### Damage hatch (right)

Rendered at the right edge of the grid. Width = `(GetMaxMainConduitCapacity() − GetMainConduitCapacity()) / D`. Zero when the reactor is healthy. Styled as diagonal-hatched `rgb(170, 25, 25)` on `rgb(80, 17, 17)`.

### USED bar (28 px)

Stacked segments in the four groups' identity colours, proportional to demand.
When total used exceeds D (overload: `used_total > 1.0`), the entire used fill
takes a damage-red tint and is clamped to the full-bar width (1.0).

### AVAILABLE bar (14 px)

Three contiguous segments:

| Segment | Token | Value |
|---|---|---|
| WARP CORE | `--bc-warp-core` | `rgb(22, 105, 207)` (blue) |
| MAIN | `--bc-main-battery` | `rgb(180, 157, 64)` (yellow-olive) |
| RESERVE | `--bc-reserve-power` | `rgb(208, 87, 42)` (red-orange) |

At each segment boundary: a 2 px **boundary tick** in a brightened variant of the segment colour, flush with the bar's bottom edge, extending 5 px above only.

### Segment label row

Below the AVAILABLE bar, segment names: WARP CORE / MAIN / RESERVE. Each label centred under its segment; label width tracks the segment width. **Narrow-segment rule:** when a segment is below 40 px wide the label fades to `opacity: 0` rather than overflowing. No OFFLINE label (damage is a column, not a bucket).

## Battery glyphs (bottom row)

Full-width row: `MAIN glyph | centred toggle stack | RESERVE glyph`.

### MAIN battery (left)

- Width: 75 px (1.5× Reserve)
- Height: 80 px (track body)
- Rounded-corner rectangle; fill clipped inside; small centred rounded **terminal bump** on top
- Charge fill bottom-up in `--bc-main-battery` `rgb(180, 157, 64)`
- Name ("MAIN") + percentage centred beneath
- ▼ inside the fill when net battery flow this interval is negative (draining)

### RESERVE battery (right)

- Width: 50 px
- Same geometry, fill colour `--bc-reserve-power` `rgb(208, 87, 42)`

### Shared battery tokens

| Element | Token | Value |
|---|---|---|
| Battery track bg | `--bc-panel-bg` (dark) | `rgba(15, 12, 35, 0.9)` |
| Battery border | battery colour at 40% opacity | — |
| Drain indicator | `▼` glyph in battery colour, centred in fill | — |

## Toggle stack + siphon lines

Centred between the two battery glyphs: Tractor above Cloak, 12 px apart. State text ("On" / "Off") in the battery colour when active, `--bc-subsystem-disabled` (grey) when off.

### Siphon lines

- **Tractor → MAIN** (line goes leftward from the toggle to the MAIN glyph edge)
- **Cloak → RESERVE** (line goes rightward to the RESERVE glyph edge)
- Line colour = the battery's identity colour
- **Solid + glow when On; dashed when Off**
- Lines are rendered under the opaque battery glyph (terminate visually at the glyph edge)

### Conditional presence

- Tractor row + siphon line render only when `GetTractorBeamSystem()` is non-null and returns ≥ 1 weapon
- Cloak row + siphon line render only when `GetCloakingSubsystem()` is non-null
- If one is absent: the remaining toggle centres alone in the toggle column
- If both absent: toggle column renders empty (no rows)

## SDK runtime contract

Python payload produced by `EngineeringPowerPanel._snapshot()` in `engine/ui/engineering_power_panel.py`.

### Shared denominator (faithful conduit-bandwidth axis)

`D = GetMaxMainConduitCapacity() + GetBackupConduitCapacity()`

RAW conduit-bandwidth values (Galaxy class: 1200+200=1400). Faithful to
`PowerDisplay.py:734` `fMaxBandwidth`. **Supersedes the initial 2400-denominator
contract** which placed the reserve threshold at ~42%, making all-125% draw
invisible as a reserve-zone event.

### Payload shape

```python
{
    "visible": True,
    "sliders": [
        {"key": "weapons",  "label": "Weapons",      "pct": 1.15, "present": True},
        {"key": "engines",  "label": "Engines",       "pct": 1.00, "present": True},
        {"key": "sensors",  "label": "Sensor Array",  "pct": 0.60, "present": True},
        {"key": "shields",  "label": "Shields",       "pct": 1.10, "present": True},
    ],
    "grid": {
        "damage":    0.0,    # (GetMaxMainConduitCapacity() − GetMainConduitCapacity()) / D; 0 when healthy
        "available": {
            "warp_core": 0.7143,  # GetPowerOutput() / D  (health-scaled)
            "main":      0.1429,  # max(0, GetMainConduitCapacity() − GetPowerOutput()) / D
            "reserve":   0.1429,  # GetBackupConduitCapacity() / D  (RAW)
        },
        "reserve_threshold": 0.8571,  # GetMainConduitCapacity() / D  (used bar crossing = reserve draining)
        "used": [
            {"key": "weapons", "frac": 0.30},  # Σ GetNormalPowerWanted()×GetPowerPercentageWanted() / D
            {"key": "engines", "frac": 0.28},
            {"key": "sensors", "frac": 0.10},
            {"key": "shields", "frac": 0.22},
        ],
        "overload": False,  # True when sum(used fracs) > 1.0 (exceeds total D)
    },
    "batteries": {
        "main":    {"charge": 0.67, "draining": True},   # GetMainBatteryPower()/limit; draining = net delta < 0
        "reserve": {"charge": 1.00, "draining": False},
    },
    "tractor": {"present": True,  "active": True},   # present = has emitter; active = _wants_power()
    "cloak":   {"present": False, "active": False},  # absent on Galaxy (no cloaking subsystem)
}
```

### Formula table

| Element | Formula | Notes |
|---|---|---|
| `grid.damage` | `(GetMaxMainConduitCapacity() − GetMainConduitCapacity()) / D` | 0 healthy; grows with reactor damage |
| `grid.available.warp_core` | `GetPowerOutput() / D` | health-scaled |
| `grid.available.main` | `max(0, GetMainConduitCapacity() − GetPowerOutput()) / D` | corridor; health-scaled |
| `grid.available.reserve` | `GetBackupConduitCapacity() / D` | RAW; ~0.1429 Galaxy |
| `grid.reserve_threshold` | `GetMainConduitCapacity() / D` | ~0.8571 healthy; bar crossing = reserve draining |
| `grid.used[i].frac` | `Σ GetNormalPowerWanted() × GetPowerPercentageWanted() / D` per group | same D |
| `grid.overload` | `sum(used fracs) > 1.0` — used fracs clamped to 1.0 when True | |
| `batteries.main.charge` | `GetMainBatteryPower() / GetMainBatteryLimit()` | independent of grid bands |
| `batteries.reserve.charge` | `GetBackupBatteryPower() / GetBackupBatteryLimit()` | |
| `batteries.*.draining` | net battery delta over last power interval < 0 | |
| `tractor.active` | existing `_wants_power()` firing state | |
| `cloak.active` | `IsTryingToCloak()` | |

Note: tractor and cloak drain are shown by the siphon lines and falling battery pillars only — they are deliberately excluded from the USED demand segments.
Available segments are **threshold bands** — they move only with reactor damage, NOT battery charge. Battery charge is shown exclusively by pillar fills.

## Interactions

- **Slider drag** → `engpower/set:<group>:<value>` → `Bridge.EngineerMenuHandlers.SetPowerToSubsystem` (0 % ⇒ TurnOff etc. — unchanged)
- **Tractor toggle click** → `engpower/toggle:tractor` → `weapon_config.toggle_tractor(player)`
- **Cloak toggle click** → `engpower/toggle:cloak` → `weapon_config.toggle_cloak(player)`
- Drag-safe update rules retained (build-once DOM; skip `document.activeElement`)
