# 03 — Shields readout

Visual reference: [03-shields-readout.html](03-shields-readout.html) (the side-by-side mockup shows the *palette and per-state visuals*; the actual placement follows the original BC layout — see below).

The SDK `ShipDisplay` widget is instantiated twice per game:
- **Player ShipDisplay** — anchored in the bottom-right tactical cluster, left of the Weapons Settings panel
- **Target ShipDisplay** — anchored at the top-left of the viewport as the "Warbird-2"-style overlay, with a minimize chevron

Both render the full SDK composite: a ship silhouette image (loaded from `game/data/Icons/Ships/<species>.tga` via the runtime TGA→PNG cache at `engine/ui/ship_icons.py`) with six shield-quadrant icons overlaid (top/bottom/front/rear/left/right), a damage list (Engines / Weapons / Sensors / Shield Generator), and a hull-integrity bar.

See `docs/superpowers/specs/2026-05-28-ship-display-panel-design.md` for the engine implementation and `docs/superpowers/plans/2026-05-28-ship-display-panel.md` for the task breakdown.

## Title line states

The TARGET SHIELDS header shows the target's name in its **affiliation colour**:

| State | Token | Value |
|---|---|---|
| Friendly target (Federation) | `--bc-target-friendly` | `rgb(80, 170, 255)` |
| Hostile target | `--bc-target-name` | `rgb(220, 90, 90)` (red) |
| Neutral target | `--bc-sensor-neutral` | `rgb(255, 210, 90)` (gold) |
| No target | `--bc-no-target` | `rgb(110, 110, 110)` (muted grey) |

For the SHIELDS (player) panel, the title is always `"PLAYER"` in `--bc-row-text-bright`.

## Hull integrity bar

A horizontal bar with three colour stops keyed to percentage:

| Range | Token | Value |
|---|---|---|
| 70–100% (healthy) | `--bc-hull-healthy` | `rgb(50, 200, 110)` (green) |
| 25–70% (damaged) | `--bc-hull-damaged` | `rgb(220, 180, 70)` (yellow) |
| 0–25% (critical) | `--bc-hull-critical` | `rgb(220, 60, 60)` (red) |
| Empty track | `--bc-hull-track` | `rgba(30, 25, 50, 0.9)` (dark purple) |

Bar dimensions: full panel-body width × 10 px height, 2 px border-radius, 1 px solid border in the track colour.

The percentage text floats right-aligned at the bar's end, in tabular numerics matching the bar's fill colour.

## SDK runtime contract

```python
# Per-tick update from the tactical loop:
pShields.SetHullIntegrity(0.55)      # 0.0 to 1.0
pShields.SetTargetName("WARBIRD-2")
pShields.SetTargetAffiliation(App.AFFILIATION_HOSTILE)

# Engine derives bar colour from integrity, text colour from affiliation.
```

The shields display is a `ShipDisplay` widget (see `engine/sdk_ui/widgets/ship_display.py`) that owns these three sub-panels and is created once at bridge load.

## When the readout is shown

- **SHIELDS (player)**: always visible while tactical view is active.
- **TARGET SHIELDS (#1)**: visible when the player has a primary target selected; collapses to "NO TARGET" when nothing is selected.
- **TARGET SHIELDS (#2)**: visible only when a secondary target is also selected. Optional.
