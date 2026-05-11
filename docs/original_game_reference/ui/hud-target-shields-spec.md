# Target Shields Panel — UI Specification

Mirror of the player's Shields panel, but rendered for the **currently selected target**. Anchored to the **upper-left**, above the Targets list.

Companion to: [tactical-mode.md § Target Shields](tactical-mode.md#target-shields-panel-upper-left).

---

## Panel anatomy

```
┌── Target Shields ──────┐ ▼
│                        │
│        ┌─◯─┐           │   ← top-down silhouette of the target hull
│   ◯─[ Ship ]─◯         │     with six shield faces colour-graded
│        └─◯─┘           │
│                        │
│   ◯ ⊡ ▦  (damage)      │   ← per-system damage icons drawn on hull
│                        │
│   ████░░░░  (HP bar)   │   ← bottom horizontal health bar
└────────────────────────┘
```

- Frame: thin coral-red outline `#CC3333` on a near-black `#000000` background.
- Title bar carries the `▼` collapse arrow (upper-right).
- Centre: an isometric / top-down silhouette of the target — visible in screenshot 14 showing a Romulan Warbird outline; screenshot 5 shows a Federation-style outline. The silhouette is class-specific.
- Six shield-face zones surround / cap the silhouette: Bow, Aft, Port, Starboard, Dorsal (top), Ventral (bottom).
- Below the silhouette: a thin horizontal **health / hull integrity bar** (visible green in screenshot 14).

### Shield-face colours

Each face is tinted by current strength:

| Face state | Human name | Hex (approx.) |
|---|---|---|
| Full strength | Bright green | `#33FF33` |
| Partly depleted | Yellow | `#FFCC00` |
| Heavily depleted | Red | `#FF3300` |
| No shielding | Black / unlit | `#000000` |

When a face hits 0%, weapon energy begins **bleeding through to the hull** on that face — this is the cue to rotate the ship in combat.

### Damage-icon overlay

The same icon glyphs used in the Engineering damage tab are drawn on top of the target silhouette to show subsystem damage:

| Icon | System |
|---|---|
| ✦ | Sensor Array |
| ⚙ | Device |
| ▣ | Hull |
| ╱ | Impulse Engine |
| ╳ | Warp Engine |
| ⌂ | Warp Core |
| ◯ | Shield Generator |
| ▦ | Torpedo Tube |
| ⊡ | Phaser / Beam Weapon |
| ⊞ | Pulse Weapon / Cannon |

Glyph colour:

- Yellow `#FFCC00` — damaged
- Grey `#888888` — disabled
- Red `#CC0000` — destroyed

Icons appear and update live as scans / hits resolve.

### Health bar

A single horizontal bar across the bottom of the silhouette area:

| Element | Human name | Hex (approx.) |
|---|---|---|
| Healthy fill | Bright green | `#33CC33` |
| Damaged fill | Yellow | `#FFCC00` |
| Critical fill | Red | `#CC3333` |
| Empty track | Dark grey | `#333333` |

### "No Target" state

When nothing is selected (screenshot 9), the panel keeps its frame and title bar but the body displays the text **"No Target"** in white on the black background, with no silhouette or icons. The Targets list below still lists known contacts.

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
- The panel is otherwise **read-only** — no targets can be selected from it; the shield faces are not click-targets.

---

## Interior vs exterior behaviour

| Aspect | Interior (Bridge) | Exterior (Tactical Mode) |
|---|---|---|
| Visible when no target selected? | No | Yes — shows "No Target" body |
| Visible with target selected? | Only when Tactical menu is open or at Red Alert | Always |
| Position | Upper-left | Upper-left |
| Stack order | Below officer menu column if one is open | Below officer menu column if one is open |
| Behaviour | Identical | Identical |

When stacked with an officer menu, the Target Shields panel renders **below the menu's last row** with a small vertical gap, never overlapping. The Targets list sits below Target Shields.
