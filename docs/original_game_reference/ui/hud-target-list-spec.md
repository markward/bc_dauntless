# Targets List Panel — UI Specification

A flat scrollable list of every sensor contact, used to pick a target and drill into its subsystems. Anchored to the **upper-left**, **directly beneath the Target Shields panel** when that is visible.

Companion to: [tactical-mode.md § Target List](tactical-mode.md#target-list-panel-right-side), [bridge-mode.md § Target List](bridge-mode.md#target-list-and-subsystem-drill-down).

---

## Panel anatomy

```
┌── Targets ─────────────────────┐ ▼
│ ▶ Comm Array-1                 │  ← red row = hostile target
│ ▶ Warbird-2                    │  ← blue row = hostile (alt-class)
│   ├ Shield Generator           │  ← second click expands subsystems
│   ├ Warp Core                  │
│   ├ Compressors                │
│   ├ Torpedoes              ▶   │  ← arrow = component sub-sublist
│   │   ├ Forward Torpedo        │
│   │   └ Aft Torpedo            │
│   ├ Impulse Engines            │
│   ├ Warp Engine                │
│   ├ Sensor Array               │
│   └ Tractors                   │
└────────────────────────────────┘
```

Each row is a pill-shaped button with:

- A small **left-edge chevron `▶`** on the row when it has expandable children.
- The contact's name in centred white-on-coloured text.
- Affiliation colour-coding of the row background (see palette below).

### Row state observations (from screenshots)

- Selected row carries a **brighter, saturated background** — in screenshot 14 the *Comm Array-1* row is solid coral red while *Warbird-2* below it is dim.
- An *Unknown Station* / *Unknown Ship* label is used when scan information is not yet available (screenshot 9). Once *Scan Target* completes, the label is replaced with the ship class / station name.
- Disabled subsystems render in **grey** text.
- Destroyed subsystems are **removed** from the list entirely.

### Subsystem drill-down

- First click on a contact row = **select** that contact as target.
- Second click on the same row = **expand** its subsystems list inline.
- Subsystems carrying their own `▶` chevron expand once more to a component list (e.g. *Torpedoes ▶* → *Forward Torpedo*, *Aft Torpedo*).
- Click an expanded row to collapse it back.

---

## Colour reference

| Element | Human name | Hex (approx.) |
|---|---|---|
| Frame outline | Coral red | `#CC3333` |
| Title bar text | Yellow gold | `#FFCC00` |
| Row — hostile (red class) | Coral red | `#CC3333` |
| Row — hostile (blue class) | Steel blue | `#3366CC` |
| Row — friendly | Bright magenta-pink | `#FF66CC` |
| Row — neutral | Lavender | `#CC99CC` |
| Row — selected (active target) | Saturated foreground colour, full-opacity | (as above, +25% brightness) |
| Subsystem row (enabled) | Lavender | `#CC99CC` |
| Subsystem row (disabled) | Grey | `#888888` |
| Row text | White on saturated bands | `#FFFFFF` |
| Chevron `▶` | Yellow | `#FFCC00` |
| Collapse arrow `▼` (title bar) | Yellow | `#FFCC00` |

> The two distinct hostile row colours seen in screenshots (Comm Array-1 in red, Warbird-2 in blue) appear to reflect *contact class* (station vs ship) rather than affiliation alone — both are enemies in the scenario.

---

## Interactions

| Input | Effect |
|---|---|
| `LMB` (first click) | Select that contact as the current target |
| `LMB` (second click on same row) | Expand subsystems beneath the row |
| `LMB` on subsystem with `▶` | Expand component sub-sublist |
| `LMB` on expanded row | Collapse |
| `Tab` | Cycle focus among HUD panels until Targets is focused |
| `↑` / `↓` | Walk the list |
| `→` / `Enter` | Select / expand current row |
| `LMB` on `▼` in title bar | Minimise panel to title bar |
| `T` / `Y` / `U` / `I` | Cycle target via keyboard (next / prev / nearest / next-enemy) |
| `Ctrl+T` | Clear current target |

> All key bindings listed above are the **defaults**. They are remappable through the game's input configuration.

---

## Interior vs exterior behaviour

| Aspect | Interior (Bridge) | Exterior (Tactical Mode) |
|---|---|---|
| Panel visible? | Only when an officer menu that summons it is open (Tactical), or when at Red Alert | Whenever a contact is in sensor range |
| Position | Upper-left | Upper-left |
| Drill-down behaviour | Identical | Identical |
| Officer-menu overlap | Helm / Science / XO / Engineering menus also anchor upper-left and stack **above** the Targets panel; the Targets panel remains visible below them (see screenshots 10, 11, 13) | Same |

When the Tactical menu is open, the Targets panel is *part* of that overlay and is always shown. Felix's menu, the Targets panel, the Target Shields panel and the bottom-edge HUD are all summoned together.
