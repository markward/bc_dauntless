# Tactical Menu — UI Specification

Officer: **Lt. Felix Savali** • Hotkey: **`F2`** • Source of truth: [bridge-mode.md § Tactical](bridge-mode.md#tactical-felix-menu--f2)

The Tactical menu is the most elaborate officer menu — it does not replace the combat HUD, it *summons all of it at once*. Opening Tactical effectively turns the screen into the combat overlay even when the player is in interior Bridge mode.

---

## Top-row panel cluster

When `F2` is pressed, the **upper edge** of the viewport fills with a row of four panels, left to right:

```
┌── Tactical ──────────┐ ┌── Orders ───────────┐ ┌── Manoeuvres ────┐ ┌── Tactics ──────┐
│ ● Report             │ │ ● Destroy           │ │  At Will       ▶ │ │  At Will       ▶│
│ ● Manual Fire        │ │ ● Disable           │ └──────────────────┘ └─────────────────┘
│ ● Phasers Only       │ │ ● Stop              │
│ ● Target At Will     │ │ ● Evade             │
└──────────────────────┘ └─────────────────────┘
```

### Tactical column (leftmost)

The officer's own command list:

| Row | Type | Notes |
|---|---|---|
| Report | Action | Felix narrates the combat picture |
| Manual Fire | Toggle | Cursor → reticle; player fires phasers/torpedoes directly |
| Phasers Only | Toggle | Felix never launches torpedoes while on |
| Target At Will | Toggle | Felix selects and switches targets autonomously |

Toggle state is shown by the **left-edge bullet**: a filled yellow/green dot for **on**, a hollow / dark dot for **off**.

### Orders column

Behavioural directive Felix follows for the *current* target:

- **Destroy** — full lethality
- **Disable** — phasers tuned to subsystems, avoid total kill
- **Stop** — pursue + neutralise but hold short of destruction
- **Evade** — break from target, defensive posture (mutually-exclusive toggle)

Only one of *Destroy / Disable / Stop* is active at a time; *Evade* is an independent toggle.

### Manoeuvres column

A small single-row panel that opens a submenu (`▶`) listing:

- At Will (default)
- Close Distance
- Maintain Distance
- Separate Distance

### Tactics column

A small single-row panel that opens a submenu (`▶`) listing:

- At Will (default)
- Left Phaser Attack
- Right Phaser Attack
- Fore Attack
- Aft Attack
- Top Shields
- Bottom Shields

---

## Left edge — Target Shields + Targets

Below the top cluster, two panels stack at the **left edge**:

1. **Target Shields** — small isometric ship outline with six shield faces colour-graded green/yellow/red/black + damage icons. See [`hud-target-shields-spec.md`](hud-target-shields-spec.md).
2. **Targets** — flat list of all sensor contacts. First click = select; second click on the same row = expand subsystems; subsystems with `▶` expand again to components. See [`hud-target-list-spec.md`](hud-target-list-spec.md).

Both panels are also part of the persistent tactical HUD; opening the Tactical menu does not change them — it just guarantees they are visible.

## Bottom edge — Sensors / Shields / Weapons / Speed-Phaser

The **lower edge** of the screen fills with the four standard combat panels:

| Anchor | Panel | Spec |
|---|---|---|
| Lower-left | Sensors (radar) | [`hud-sensors-spec.md`](hud-sensors-spec.md) |
| Bottom-centre-left | Shields (player) | [`hud-shields-spec.md`](hud-shields-spec.md) |
| Bottom-centre-right | Weapons (loadout) | [`hud-weapons-spec.md`](hud-weapons-spec.md) |
| Lower-right | Speed + Phaser Arc / Torpedo readout | [`hud-speed-display-spec.md`](hud-speed-display-spec.md) |

---

## Colour reference (from screenshots)

| Element | Human name | Hex (approx.) |
|---|---|---|
| Tactical column title band | Coral red | `#CC3333` |
| Orders column title band | Coral red | `#CC3333` |
| Manoeuvres / Tactics title band | Pink / magenta | `#CC6699` |
| Title text | Yellow gold | `#FFCC00` |
| Active toggle bullet | Yellow | `#FFFF00` |
| Inactive toggle bullet | Dark magenta | `#663366` |
| Row background (enabled) | Lavender | `#CC99CC` |
| Row text (enabled) | Yellow gold | `#FFCC66` |
| Row background (disabled) | Charcoal | `#333333` |
| Row text (disabled) | Mid-grey | `#666666` |
| Submenu chevron `▶` | Yellow | `#FFCC00` |
| Frame outline | Black | `#000000` |

---

## When the menu opens

### Interior view (Bridge)

- Felix is **not** typically centred in the viewport while Tactical is open (his console is to one side). The bridge environment is mostly hidden behind the panels.
- All four top-row panels appear at once. The screenshot shows them rendered over an explosion in the viewscreen.
- The bottom-edge HUD (Sensors / Shields / Weapons / Speed-Phaser) appears in this mode **only when the Tactical menu is open**, or when Red Alert is active. Closing Tactical (press `F2` again or `F6`) hides them.

### Exterior view (Tactical mode)

- The bottom-edge HUD is **already on** in this mode at all times, so opening the Tactical menu only adds the top-row cluster.
- The third-person ship view is partially occluded by the panels.
- All other officer menus dismiss when this one opens.

### Differences between interior and exterior

| Aspect | Interior (Bridge) | Exterior (Tactical Mode) |
|---|---|---|
| Bottom HUD always visible? | No — only with this menu open or at Red Alert | Yes — persistent |
| Top-cluster appearance | Identical | Identical |
| Camera | Locked to captain's chair | Third-person chase / tracking |
| Crew visible | Felix occluded, viewscreen visible | Player ship, no crew |
| Switching | `Space` toggles to exterior; menu stays open | `Space` toggles back; menu stays open |

---

## Input behaviour

> All key bindings listed below are the **defaults**. They are remappable through the game's input configuration.

| Input | Effect |
|---|---|
| `F2` | Toggle the entire Tactical cluster open / closed |
| `Tab` | Cycle focus between the top-row columns and the Target List |
| `↑` / `↓` | Walk current focused column / list |
| `→` / `Enter` | Activate / expand |
| `←` | Back out of submenu |
| `H` | Toggle Manual Fire (matches Tactical → Manual Fire) |
| `LMB` on row | Activate / cycle value |

> Issuing **any** of these orders while in Tactical Mode (or upon returning to Bridge) hands the conn back to Felix. The player must press a flight key (WASD / Q / E) to take direct control again.

---

## Notes

- *Weapons* sub-controls (Torpedo Type, Spread, Phaser Intensity, Tractor, Cloak) live in the bottom Weapons panel — they are not part of Felix's column. See [`hud-weapons-spec.md`](hud-weapons-spec.md).
- The Tactical menu is the **only** officer menu that lays out content horizontally (a top row of four panels). All others are a single vertical column.
- When Manual Fire is on, the cursor reticle's hull-region placement selects the subsystem under attack — independent of the Targets list expansion.
- *Cloak* row in the Weapons panel appears only on hulls that have one (multiplayer / Quick Battle ships only).
