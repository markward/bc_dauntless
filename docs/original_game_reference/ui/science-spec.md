# Science Menu — UI Specification

Officer: **Lt. Cmdr. Miguel Diaz** • Hotkey: **`F4`** • Source of truth: [bridge-mode.md § Science](bridge-mode.md#science-miguel-menu--f4)

A single vertical column of sensor / probe commands. The simplest of the five officer menus.

---

## Panel anatomy

```
┌──────────────────────────┐
│ Science                  │  ← title bar (coral band, yellow text)
├──────────────────────────┤
│ ● Report                 │
│ ● Scan Area              │
│ ○ Scan Target            │  ← greyed unless a target is selected
│ ● Scan Object          ▶ │  ← submenu chevron when contacts in range
│   └ ● Warbird-2          │  ← expanded child rows appear inline
│ ● Launch Probe           │  ← single-player only; greyed in MP
└──────────────────────────┘
```

Screenshot 2 shows *Scan Object* highlighted and expanded to reveal a single nearby contact (*Warbird-2*) as a child row.

### Row state observations

- *Scan Target* in screenshot 3 is shown with the **darker / desaturated** row colour and no left bullet — this is the disabled state, in effect until a target is locked.
- *Scan Object* carries the **right chevron `▶`** only when at least one scannable contact is in sensor range; expanding it inserts those contacts as indented rows under the parent (screenshot 2).
- *Launch Probe* is interactive only in single-player. In multiplayer the row renders disabled.

---

## Colour reference

| Element | Human name | Hex (approx.) |
|---|---|---|
| Title bar band | Coral red | `#CC3333` |
| Title text | Yellow gold | `#FFCC00` |
| Row background (enabled) | Lavender | `#CC99CC` |
| Row text (enabled) | Yellow gold | `#FFCC66` |
| Row background (highlighted) | Hot pink | `#FF6699` |
| Row background (disabled) | Charcoal / muted lavender | `#444444` |
| Row text (disabled) | Mid-grey | `#666666` |
| Bullet (enabled) | Magenta dot | `#FF33CC` |
| Child row (expanded contact) | Pink, slightly lighter | `#FF99CC` |
| Submenu chevron `▶` | Yellow | `#FFCC00` |

---

## When the menu opens

### What appears

- The Science column at upper-left.
- Nothing else — Science does not summon HUD panels of its own.

### What disappears

- Any other officer menu closes when `F4` is pressed.

### Interior view (Bridge)

- Diaz is visible at the science console behind the menu (screenshots 2 and 3).
- The viewscreen behind him shows the current camera pose.
- No combat HUD elements unless already at Red Alert / Tactical open.

### Exterior view (Tactical)

- Diaz is not on screen; player's ship visible in third-person.
- The persistent bottom-edge HUD remains drawn (Sensors, Shields, Weapons, Speed/Phaser-Arc).
- Target Shields and Targets list (upper-left, below the Science column) remain visible when a target is selected (screenshot 10).

### Differences between interior and exterior

| Aspect | Interior | Exterior |
|---|---|---|
| Officer rendered | Yes | No |
| Bottom HUD present | Only when at Red Alert | Always |
| Target Shields / Targets visible | Only with target + combat HUD shown | Always with target |
| Menu position | Identical | Identical |
| Menu rows | Identical | Identical |

---

## Input behaviour

> All key bindings referenced here are the **defaults**. They are remappable through the game's input configuration.

Identical to other officer menus. `F4` toggles open/closed. The expansion under *Scan Object* uses `→` / `Enter` to open, `←` to collapse.

---

## Notes

- *Scan Area* triggers a sensor sweep without a specific target — narration only.
- *Scan Target* relies on the currently selected Target List entry; the scan result is narrated and updates the Target Shields panel's damage-icon set.
- *Launch Probe* lets the player's sensor coverage continue even after their own Sensor Array is disabled or destroyed; the probe persists from its launch position and reports back through the regular sensor feed.
