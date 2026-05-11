# Sensors Panel (Radar) — UI Specification

The Sensors panel is the 2-D radar at the **lower-left** of the screen. It shows every sensor contact within range, on a non-linear disk centred on the player ship.

Companion to: [tactical-mode.md § Sensors panel](tactical-mode.md#sensors-panel-lower-left).

---

## Panel anatomy

```
┌── Sensors ─────────────┐ ▼
│                        │
│        ─ ┐             │   ← contacts drawn as coloured arrows
│   ▲      │             │     pointing in their direction of motion
│          │             │
│        ╭─┼─╮           │
│        │ ◉ │           │   ← centre dot = player ship
│        ╰─┼─╯           │
│          │             │
│      ◣   │             │   ← bracketed = current target / hostile fire
│          │             │
└────────────────────────┘
```

- Round disk display, ~150 px on a 800-wide HUD.
- Frame: thin coral-red outline `#CC3333`.
- Disk background: deep navy / near-black `#000033`.
- Title bar `Sensors` at the top with a `▼` collapse arrow in the upper-right (the same minimise affordance used by every Tactical-Mode HUD panel).

### Contact glyphs

| Glyph | Meaning | Notes |
|---|---|---|
| Coloured arrow | Sensor contact | Arrow direction = contact's facing / heading |
| Bracket around arrow | The currently selected target **or** a ship currently firing on the player | Doubles as hostile-fire warning |
| Torpedo icon | Inbound torpedo | Differentiated by torpedo *type* so threats can be assessed |
| Vertical fade | Contact above / below the player's flight plane | Fades as it leaves the plane |

### Colour reference

| Element | Human name | Hex (approx.) |
|---|---|---|
| Frame outline | Coral red | `#CC3333` |
| Title bar text | Yellow gold | `#FFCC00` |
| Disk background | Near-black navy | `#000033` |
| Friendly contact | Sky blue | `#3399FF` |
| Hostile contact | Red | `#CC3333` |
| Neutral / unknown contact | Yellow | `#FFCC00` |
| Player-ship centre | White | `#FFFFFF` |
| Target / fire bracket | Yellow | `#FFFF00` |
| Collapse arrow `▼` | Yellow on dark | `#FFCC00` |

(The exact colour mapping between affiliation and hue is taken from the in-game palette; the screenshots show a clear distinction between blue-friendly and red-hostile arrows on the disk.)

### Range falloff (non-linear)

The disk is non-linear: distant contacts compress toward the edge rather than disappearing. This means two contacts that appear equidistant on the radar may be at very different *actual* ranges. The player must read the Targets list or HUD distance label for true range.

---

## Interactions

- Click `▼` in the title bar to **minimise** the panel to its title bar.
- Click again on the title bar to expand.
- The panel is **non-interactive** beyond the minimise toggle — you cannot click a contact glyph to select it. Selection happens via the Targets list or `T`/`Y`/`U`/`I` cycling keys.

> Key bindings referenced here are the **defaults** and are remappable through the game's input configuration.

---

## Interior vs exterior behaviour

| Aspect | Interior (Bridge) | Exterior (Tactical Mode) |
|---|---|---|
| Panel always visible? | **No** — only when Red Alert is active or the Tactical menu is open | **Yes** — persistent |
| Position | Lower-left | Lower-left |
| Behaviour | Identical | Identical |
| Collapse `▼` | Works | Works |

When the panel is hidden in interior mode (Green / Yellow Alert with no Tactical menu open), there is no fallback radar elsewhere — the player must rely on the viewscreen, the Targets list when displayed, and verbal reports from Felix and Diaz.
