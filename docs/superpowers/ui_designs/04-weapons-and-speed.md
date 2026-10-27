# 04 — Weapons + Speed readout

Visual reference: [04-weapons-and-speed.html](04-weapons-and-speed.html)

Two side-by-side readout panels for tactical:
- **WEAPONS** — current torpedo/phaser loadout + cycle / spread / intensity settings + tractor/cloak toggle
- **SPEED** — current speed in KPH and warp factor (placeholder in mockup)

## Weapons panel

```
┌─ WEAPONS ────────▼┐
║ TORPEDOES   250   │     ← section heading in Menu1 accent; count in gold
║ ▸ Type     Photon │     ← cycle row (Menu3 sub-tone)
║ ▸ Spread   Single │     ← cycle row
╞═══════════════════╡
║ PHASERS           │     ← section heading
║ ▸ Intensity Full  │
╞═══════════════════╡
║ ▸ Tractor    On   │     ← toggle row (Menu1 salmon)
║ ▸ Cloak     Off   │     ← toggle row (muted when off)
└───────────────────┘
```

## Section headings

`TORPEDOES`, `PHASERS` etc. are non-interactive section labels:
- Font: Antonio 12 px, weight 600
- Colour: `--bc-menu1-accent` `rgb(216, 132, 80)` (the chrome accent)
- Letter-spacing: 2 px, uppercase
- Right-aligned value (e.g. `250` torpedo count) in `--bc-gold` `rgb(255, 210, 90)`
- 1 px dark separator below

## Cycle rows (Menu3 sub-tone)

Each row is a key/value pair where clicking cycles through preset values:

| Element | Token / value |
|---|---|
| Row background | `--bc-row-available-bg` (purple) |
| Left edge | `--bc-menu3-base` `rgb(195, 95, 175)` (pink — signals Menu3 child of weapons panel) |
| Label | `--bc-row-text-bright` `rgb(220, 210, 255)` |
| Value text | `--bc-row-text-dim` `rgb(180, 170, 220)` right-aligned |

SDK exposes these as `STButton` instances whose text is the current value (`"Photon"`, `"Single"`, `"Full"`); clicks call `pButton.Cycle()` which fires a `CycleEvent` that the SDK handler maps to the next option.

## Toggle rows (Menu1 salmon)

Tractor and Cloak each occupy one row at the bottom of the weapons panel:

| State | Left edge | Value text |
|---|---|---|
| **On** | `--bc-menu1-base` salmon | `--bc-good` `rgb(120, 200, 120)` green, label "On" |
| **Off** | `--bc-subsystem-disabled` muted grey | `--bc-subsystem-disabled` `rgb(110, 110, 110)`, label "Off" |

Click toggles the state. SDK fires the corresponding event (`Engineer.ToggleTractor`, `Engineer.ToggleCloak`).

## Speed panel

```
┌─ SPEED ────▼┐
║             │
║  SPEED      │   ← centred placeholder in mockup
║  0 - 0 KPH  │
║             │
└─────────────┘
```

In runtime: displays "current_kph / max_kph" plus the active warp factor (e.g. "Warp 5") when above impulse. Layout is centred text in `--bc-row-text-bright` at 14 px.

## SDK runtime contract

```python
pWeapons = App.WeaponsDisplay_Create(...)
pWeapons.SetTorpedoCount(250)
pWeapons.SetTorpedoType("Photon")
pWeapons.SetTorpedoSpread("Single")
pWeapons.SetPhaserIntensity("Full")
pWeapons.SetTractorActive(True)
pWeapons.SetCloakActive(False)

pSpeed = App.SpeedDisplay_Create(...)
pSpeed.SetCurrent(120.5)   # KPH
pSpeed.SetMax(1000.0)
pSpeed.SetWarp(None)       # None = impulse only
```

Both displays update on every tick via `tactical_window.UpdateTargets()` (or equivalent in the SDK).
