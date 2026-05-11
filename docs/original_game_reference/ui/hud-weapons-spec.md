# Weapons Panel — UI Specification

Weapons loadout / cycle controls for the player ship. Anchored to the **bottom edge**, between the Shields panel and the Speed / Phaser-Arc display.

Companion to: [tactical-mode.md § Weapons panel](tactical-mode.md#weapons-panel) and the *Weapons* sub-section of [bridge-mode.md § Tactical](bridge-mode.md#tactical-felix-menu--f2).

---

## Panel anatomy

```
┌── Weapons ─────────────────┐ ▼
│ Torpedoes 250              │  ← unused-torpedo count (yellow)
├────────────────────────────┤
│ ● Type:    Photon          │  ← click-cycles between loaded types
│ ● Spread:  Single          │  ← click-cycles single / N-spread
├── Phasers ─────────────────┤
│ ● Intensity: Full          │  ← Full / Low
├────────────────────────────┤
│ ● Tractor Off              │  ← toggle on/off; draws Main Battery
│ ● Cloak  Off               │  ← toggle on/off (if equipped)
└────────────────────────────┘
```

- Frame: thin coral-red outline `#CC3333` on black `#000000`.
- Title bar `Weapons` with `▼` collapse arrow in upper-right.
- Internal subsection headers ("Torpedoes", "Phasers") are thin coral bands matching the title.
- Rows are pill-shaped lavender buttons identical to the officer-menu rows; each label "Type:", "Spread:", "Intensity:" is followed by the current value, and clicking the row cycles to the next value.

### Row state observations (from screenshots)

- All rows render in lavender `#CC99CC` when enabled.
- *Tractor Off* in screenshots 1, 5 and 8 is shown with the standard magenta bullet; the row is interactable but the tractor is off.
- The torpedo count `250` in screenshot 5 sits inside the panel as text, not a button; it updates as torpedoes are fired or restocked.

### Cycle-row values

| Row | Cycle values |
|---|---|
| Type | Photon (default) / Quantum / additional types as loaded by the campaign |
| Spread | Single / 2 / 3 / 4 / … up to the loadout limit |
| Intensity (Phasers) | Full / Low |
| Tractor | On / Off |
| Cloak | On / Off (only on hulls that have one — multiplayer / Quick Battle ships) |

### Phaser Intensity behaviour

- **Full** — max DPS, fastest energy drain.
- **Low** — less DPS, lower drain. **Does not damage hull when no specific subsystem / component is targeted** (so it's the disabling option). **More effective at damaging subsystems once shields are down or weak.**

### Tractor / Cloak draw

- Tractor draws continuously from **Main Battery** while engaged.
- Cloak draws continuously from **Reserve Battery** while engaged, and drops shields + weapons offline. Invisible to enemy Targets lists and immune to phaser fire while cloaked.

---

## Colour reference

| Element | Human name | Hex (approx.) |
|---|---|---|
| Frame outline | Coral red | `#CC3333` |
| Title / subsection bands | Coral red | `#CC3333` |
| Title text | Yellow gold | `#FFCC00` |
| Row background | Lavender | `#CC99CC` |
| Row label text | Yellow gold | `#FFCC66` |
| Bullet (on / engaged) | Bright yellow | `#FFFF00` |
| Bullet (off / idle) | Magenta | `#FF33CC` |
| Torpedo count text | Yellow | `#FFCC00` |
| Collapse arrow `▼` | Yellow | `#FFCC00` |

---

## Interactions

- Click any value row → cycle to the next value.
- Click `▼` in title bar → minimise to title bar.
- `Alt+T` (default) → toggle Tractor.
- `Alt+C` (default) → toggle Cloak.
- The Tactical menu's *Weapons* sub-controls (under Felix → Tactical) mirror this panel — same values, same cycle behaviour.

> Key bindings referenced here are the **defaults** and are remappable through the game's input configuration.

---

## Interior vs exterior behaviour

| Aspect | Interior (Bridge) | Exterior (Tactical Mode) |
|---|---|---|
| Always visible? | **No** — only when Tactical menu is open or Red Alert is active | **Yes** — persistent |
| Position | Bottom edge, centre-right of Shields | Bottom edge, centre-right of Shields |
| Cycle / toggle behaviour | Identical | Identical |
| Cloak row | Hidden on hulls without cloak (most campaign ships) | Same |

---

## Notes

- The torpedo count (`250` in screenshots) represents **unused torpedoes**, not the per-tube readiness — that's on the Phaser Arc / Torpedo readout in the lower-right panel.
- A "no subsystem targeted" shot on Low intensity still damages the hull only if the player **is** targeting the contact at the hull level — see [bridge-mode.md § Weapons sub-controls](bridge-mode.md#weapons-sub-controls) for the exact rule.
