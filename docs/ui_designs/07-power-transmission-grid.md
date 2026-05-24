# 07 — Power Transmission Grid (engineer sub-component)

Visual reference: [07-power-transmission-grid.html](07-power-transmission-grid.html)

The "POWER USED" stacked bar at the top of the engineer panel. Shows how the ship's total power output is currently allocated across four buckets.

## Structure

```
POWER USED
┌──────────────────────────────────────────────────────────────┐
│ ▓▓▓▓ █████████████ ████████████ ███████████████████          │
└──────────────────────────────────────────────────────────────┘
  OFFLINE  WARP CORE      MAIN              RESERVE
  12%        38%          30%                 20%
```

A single horizontal bar split into four contiguous segments. Each segment's **width** is proportional to that bucket's share of total power. Below the bar, a row of labels aligned to each segment.

## Segment tokens

| Segment | Token | Value | Visual |
|---|---|---|---|
| OFFLINE | `--bc-offline` | `rgb(170, 25, 25)` red | **Diagonal-hatched** stripe pattern in red on darker red (`rgb(80, 17, 17)` background): `repeating-linear-gradient(45deg, ...)` |
| WARP CORE | `--bc-warp-core` | `rgb(22, 105, 207)` blue | Solid fill |
| MAIN | `--bc-main-battery` | `rgb(180, 157, 64)` yellow-olive | Solid fill |
| RESERVE | `--bc-reserve-power` | `rgb(208, 87, 42)` red-orange | Solid fill |

## Bar dimensions

- Height: 14 px
- Border: 1 px solid `rgb(40, 35, 50)` (dark track)
- Border-radius: 2 px
- Overflow: hidden (segments butt-join cleanly)

## Label row

Below the bar, a `display: flex; justify-content: space-between;` row of four labels:
- Font: Antonio 9 px, weight 400
- Letter-spacing: 0.6 px
- Each label coloured to match its segment (slightly brighter than the segment):
  - OFFLINE → `--bc-offline-edge` `rgb(220, 60, 60)`
  - WARP CORE → `--bc-warp-core` `rgb(22, 105, 207)`
  - MAIN → `--bc-main-battery` `rgb(180, 157, 64)`
  - RESERVE → `--bc-reserve-power` `rgb(208, 87, 42)`

The labels report the segment NAME (always the same), not the value. The value (e.g. "38%") could be appended after the name if there's space, but the canonical mockup omits per-segment values to keep the row compact.

## Heading

"POWER USED" caption above the bar:
- Font: Antonio 11 px, weight 600
- Colour: `--bc-row-text-bright`
- Letter-spacing: 1 px
- Uppercase
- Bottom margin: 4 px

## Edge case: an empty bucket

When a bucket is 0% (e.g. nothing offline), its segment collapses to zero width. The label below STILL shows ("OFFLINE" remains visible) but with no segment above it.

## SDK runtime contract

The engineer panel widget pushes the four percentages each tick:

```python
pEng.SetPowerUsedBreakdown(
    offline=12,    # 0-100
    warp_core=38,
    main=30,
    reserve=20,
)
# Must sum to <= 100. Any remainder is "unused" capacity and renders
# as empty (dark track) at the right of the bar.
```

The engine layer asserts `sum(...) <= 100`; the bridge.js binding scales `style.width = pct + '%'` directly.
