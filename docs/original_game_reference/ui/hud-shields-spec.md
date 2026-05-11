# Player Shields Panel — UI Specification

The player ship's own shield-state readout. Anchored to the **bottom edge**, left of the Weapons panel.

Companion to: [tactical-mode.md § Shields panel](tactical-mode.md#shields-panel-lower-edge).

---

## Panel anatomy

```
┌── Shields ─────────────┐ ▼
│         ┌─◯─┐          │
│    ◯─[ Ship ]─◯        │   ← top-down silhouette of the player ship
│         └─◯─┘          │     with six shield faces colour-graded
│                        │
│  ████████░░░░  (HP)    │   ← horizontal hull-integrity bar
└────────────────────────┘
```

- Frame: thin coral-red outline `#CC3333` on black `#000000`.
- Title bar with `▼` collapse arrow upper-right.
- Centre: a class-correct top-down silhouette of the player's ship (Galaxy or Sovereign for Federation; visible in screenshots 5 and 8 as a Federation saucer-and-nacelles outline).
- Six shield zones around the silhouette: Bow, Aft, Port, Starboard, Dorsal, Ventral.
- Bottom: horizontal **hull integrity bar**.

### Shield face colours (same legend as Target Shields)

| State | Human name | Hex (approx.) |
|---|---|---|
| Full strength | Bright green | `#33FF33` |
| Partly depleted | Yellow | `#FFCC00` |
| Heavily depleted | Red | `#FF3300` |
| No shielding | Black / unlit | `#000000` |

In screenshots 5 and 8 all six faces are at bright green — the player has not yet been hit.

### Hull integrity bar

A solid horizontal bar at the bottom:

| Fill | Hex (approx.) |
|---|---|
| Healthy | `#33CC33` |
| Damaged | `#FFCC00` |
| Critical | `#CC3333` |
| Empty track | `#333333` |

### Damage-icon overlay

The same icon glyphs documented in [bridge-mode.md § Damage indicators](bridge-mode.md#damage-indicators-shared-with-tactical-mode) are drawn on the player ship silhouette when a subsystem on the player ship is damaged. Colours: yellow (damaged), grey (disabled), red (destroyed).

---

## Colour reference

| Element | Human name | Hex (approx.) |
|---|---|---|
| Frame outline | Coral red | `#CC3333` |
| Title bar | Coral red | `#CC3333` |
| Title text | Yellow gold | `#FFCC00` |
| Background | Black | `#000000` |
| Hull silhouette | Light grey | `#CCCCCC` |
| Collapse arrow `▼` | Yellow | `#FFCC00` |

---

## Interactions

- Click `▼` in the title bar to **minimise** to the title bar.
- The panel is otherwise **read-only** — faces and silhouette are not click-targets.

---

## Interior vs exterior behaviour

| Aspect | Interior (Bridge) | Exterior (Tactical Mode) |
|---|---|---|
| Always visible? | **No** — only when Tactical menu is open or Red Alert is active | **Yes** — persistent at the bottom edge |
| Position | Bottom edge, centre-left | Bottom edge, centre-left |
| Behaviour | Identical | Identical |
| Damage-icon overlay | Same | Same |

> Combat tip the manual emphasises: rotate the ship constantly so no single face is depleted — once a face hits 0%, weapon energy bleeds through to the hull on that face.
