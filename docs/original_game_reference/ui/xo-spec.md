# First Officer (XO) Menu — UI Specification

Officer: **Cmdr. Saffi Larsen** • Hotkey: **`F3`** • Source of truth: [bridge-mode.md § First Officer](bridge-mode.md#first-officer-saffi-menu--f3)

The First Officer menu is a single vertical column. It owns ship-wide alert state and mission-info commands and, in Quick Battle mode, gains scenario controls.

> Although the source manual and bridge-mode.md call her station *First Officer*, the in-game header on the panel reads **"Commander"** (see screenshots 7 and 13).

---

## Panel anatomy

Single column anchored to the **upper-left** of the viewport in both views:

```
┌──────────────────────────┐
│ Commander                │  ← title bar (coral band, yellow text)
├──────────────────────────┤
│ ● Report                 │  ← currently highlighted in screenshot
│ ● Damage Report          │
│ ● Green Alert            │  ← mutually exclusive with the next two
│ ● Yellow Alert           │
│ ● Red Alert              │
│ ● Show Mission Log       │
│ ● Contact Engineer       │  ← only when Brex is in Engineering
│ ● Quick Battle Setup     │  ← Quick Battle mode only
│ ○ Start Combat           │  ← Quick Battle: greyed while a sim is running
│ ● End Combat             │  ← Quick Battle: greyed when not in a sim
└──────────────────────────┘
```

In a single-player **campaign** mission, the Quick Battle rows are replaced by:

```
│ ● Objectives             │
│ ● Contact Starfleet      │
│ ● Contact Engineering    │
```

(See [bridge-mode.md](bridge-mode.md#first-officer-saffi-menu--f3) for the campaign-mode listing.)

A fifth Quick Battle row, **Restart Combat**, appears between *Quick Battle Setup* and *End Combat* once a simulation has been started at least once during the session (visible in screenshot 13).

---

## Alert state interaction

The three Alert rows form a mutually-exclusive radio group:

| Row | Shields | Weapons | Battery behaviour |
|---|---|---|---|
| Green Alert | Off | Off | Batteries recharge; non-aggressive |
| Yellow Alert | **Raised** | Off | Stable; no extra drain from idle systems |
| Red Alert | **Raised** | **Online** | Continuous drain from Reserve while idle |

The active alert is shown by which row carries the **yellow highlight bullet** at its left edge — the other two return to the standard magenta bullet.

---

## Colour reference (from screenshots)

| Element | Human name | Hex (approx.) |
|---|---|---|
| Title bar band | Coral red | `#CC3333` |
| Title text | Yellow gold | `#FFCC00` |
| Row background (enabled) | Lavender | `#CC99CC` |
| Row text (enabled) | Yellow gold | `#FFCC66` |
| Row background (highlighted / hover) | Hot pink | `#FF6699` |
| Row background (disabled) | Charcoal | `#333333` |
| Row text (disabled) | Mid-grey | `#666666` |
| Bullet (active alert) | Bright yellow | `#FFFF00` |
| Bullet (idle row) | Magenta | `#FF33CC` |

---

## When the menu opens

### What appears

- The Commander column at upper-left.
- Nothing else — the XO menu does not summon any HUD panels of its own.

### What disappears

- Any other officer menu closes when `F3` is pressed.

### Interior view (Bridge)

- Saffi is centred in the viewport behind the menu (visible in screenshot 7). The bridge interior fills the rest of the screen.
- No combat HUD is drawn unless the player is already at Red Alert or has Tactical open.

### Exterior view (Tactical)

- Saffi is not on screen; the player's ship is visible in third-person.
- The persistent bottom-edge HUD (Sensors, Shields, Weapons, Speed/Phaser-Arc) **remains drawn beneath the menu** — opening the XO column does not hide them.
- Target Shields and Targets list (upper-left, beneath the XO column) also remain visible when a target is selected.

### Differences between interior and exterior

| Aspect | Interior | Exterior |
|---|---|---|
| Officer rendered | Yes (Saffi visible) | No |
| Bottom HUD present | Only at Red Alert / Tactical open | Always |
| Target Shields visible | Only when targeting + Red Alert / Tactical | Always while targeting |
| Menu position | Identical | Identical |
| Menu rows | Identical | Identical |

---

## Input behaviour

> All key bindings referenced here are the **defaults**. They are remappable through the game's input configuration.

Identical to other officer menus. `F3` toggles open/closed; `F6` also closes; the menu is dismissed by clicking off-menu or by opening another officer with `F1/F2/F4/F5` or click.

---

## Quick Battle overlay

Selecting *Quick Battle Setup* opens the modal **Quick Battle Setup** overlay (see [`quick-battle-setup-spec.md`](quick-battle-setup-spec.md)). The overlay covers the bridge / tactical view entirely; the XO column behind it remains, but is non-interactive until the overlay is closed.

*Start Combat* / *Restart Combat* / *End Combat* control simulation lifecycle without opening any overlay — see [quick-battle-and-multiplayer.md](quick-battle-and-multiplayer.md).
