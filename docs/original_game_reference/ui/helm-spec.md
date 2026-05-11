# Helm Menu — UI Specification

Officer: **Ensign Kiska LoMar** • Hotkey: **`F1`** • Source of truth: [bridge-mode.md § Helm](bridge-mode.md#helm-lomar-menu--f1)

This document describes how the Helm menu renders on-screen, what other panels appear or disappear when it opens, and the differences between interior (Bridge) and exterior (Tactical) views.

---

## Panel anatomy

The Helm menu is a single vertical column anchored to the **upper-left corner** of the viewport. It is the same widget in both interior and exterior modes.

```
┌──────────────────────────┐
│ Helm                     │  ← title bar (orange-red band, yellow text)
├──────────────────────────┤
│ ● Report                 │  ← root option (lavender row, dark text)
│ ● Hail                 ▶ │  ← submenu (right-pointing chevron)
│ ● Set Course           ▶ │
│ ○ Warp                   │  ← disabled when no course laid
│ ● Orbit Planet         ▶ │
│ ● Nav Points           ▶ │
│ ● Intercept              │  ← only enabled with target selected
│ ○ All Stop               │
│ ○ Dock                   │  ← greyed unless in Starbase 12 range
└──────────────────────────┘
```

### Colour reference (from screenshots)

| Element | Human name | Hex (approx.) |
|---|---|---|
| Title bar band | Coral / red-orange | `#CC3333` |
| Title text | Bright yellow | `#FFCC00` |
| Row background (enabled) | Lavender / light magenta | `#CC99CC` |
| Row text (enabled) | Yellow gold | `#FFCC66` |
| Row background (highlighted) | Hot pink | `#FF6699` |
| Row background (disabled) | Charcoal | `#333333` |
| Row text (disabled) | Mid-grey | `#666666` |
| Bullet (enabled) | Magenta dot | `#FF33CC` |
| Bullet (disabled) | Dark grey | `#555555` |
| Submenu chevron `▶` | Yellow | `#FFCC00` |

Rows are pill-shaped with a flat right edge and rounded left cap — the standard LCARS button shape used by every officer menu.

### Bullet / state indicators (left edge)

- **Filled magenta circle** — option is enabled and idle.
- **Yellow dot** — option currently highlighted via keyboard `↑`/`↓` or mouse hover.
- **Empty / dark circle** — option is disabled in the current context (e.g. *Warp* with no course set, *Dock* outside Starbase 12 range, *Intercept* with no target).

### Submenu chevron (right edge)

A small right-pointing triangle `▶` appears on rows that open a submenu (*Hail*, *Set Course*, *Orbit Planet*, *Nav Points*). Activating those rows replaces or extends the column with a child list — see [bridge-mode.md § Helm](bridge-mode.md#helm-lomar-menu--f1) for content.

---

## When the menu opens

### What appears

- The Helm column at upper-left.
- A **green target reticle** plus distance/speed readout (`38.29 km / 0 kph` in screenshot) centres on the **currently selected target** if one exists. This is a viewscreen/HUD overlay — it is not part of the Helm menu, but it is the only contact-detail readout visible to the helmsman.

### What disappears or stays hidden

- No other officer menu may be open simultaneously; opening Helm closes any other menu.
- In **interior mode**, opening Helm does **not** summon the combat HUD (Shields, Weapons, Sensors, Phaser Arc). Those remain hidden unless Red Alert is active **or** the Tactical menu is opened.
- The viewscreen pose (`Home`/`Del`/`PgDn`/`End`/`PgUp`/`Ins`) is unaffected.

---

## Interior view (Bridge)

- LoMar is visible at the helm console, partially occluding the lower-left of the screen.
- The viewscreen behind her shows whatever the camera is pointed at — typically the forward arc when *Look Forward* is active. A targeted contact is bracketed there with the green reticle and distance label.
- No combat HUD panels are drawn at the bottom edges of the screen unless Tactical is active.

## Exterior view (Tactical)

- The Helm column is drawn in the same upper-left position.
- The player ship is now visible in third-person chase view; LoMar is not on screen.
- The bottom-edge HUD (Sensors, Shields, Weapons, Speed/Phaser-Arc) is **always present** in this mode, regardless of which officer menu is open.
- When a target is selected, **Target Shields** appears upper-left *under* the Helm column, and **Targets** list appears beneath that — both visible at once with the menu. The Helm column does not collapse them.

---

## Input behaviour (mirrors bridge-mode.md)

> All key bindings listed below are the **defaults**. They are remappable through the game's input configuration.

| Input | Effect |
|---|---|
| `F1` | Toggle Helm menu open / closed |
| `↑` / `↓` | Move highlight |
| `Enter` | Activate highlighted row |
| `→` | Open submenu under highlighted row |
| `←` | Back out of submenu, or close menu at root |
| `Num 1`–`Num 9` | Activate the Nth row directly |
| `LMB` on row | Activate / select |
| `LMB` off-menu | Close the menu |
| `LMB` on another officer | Close Helm, open that officer's menu |

---

## Notes

- The chevron-bearing options (*Hail*, *Set Course*, *Orbit Planet*, *Nav Points*) cascade into child columns; child columns inherit the same colour palette and bullet conventions.
- When LoMar has been given command of a friendly vessel, *Hail* gains an extra block of orders (*Resume Old Orders*, *Attack Target*, *Disable Target*, *Defend Target*, *Protect Me*, *Dock With Starbase*) below the contact list.
- The *Warp* row only lights up after *Set Course* has been used to pick a destination.
