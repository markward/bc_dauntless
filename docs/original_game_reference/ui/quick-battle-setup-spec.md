# Quick Battle Setup Overlay — UI Specification

A full-screen modal dialog opened from the XO/Commander menu's *Quick Battle Setup* row. Lets the player build a combat scenario — choose ships for both sides, pick the player's bridge / faction, pick a combat region.

Companion to: [quick-battle-and-multiplayer.md](quick-battle-and-multiplayer.md), [xo-spec.md](xo-spec.md).

---

## Overall layout

The overlay covers the bridge / tactical view entirely. Three-zone layout below a top toolbar:

```
┌─ Quick Battle Setup ──────────────────────────────────────────────────┐
│ [ Ships ] [ Player and Region ]                       [ Close ][ Start ]
├───────────────────────────────────────────────────────────────────────┤
│  ┌────────────────┐   ┌──────────────────┐   ┌──────────────────────┐ │
│  │  Catalogue     │   │  Detail / preview │   │  Sides / Region      │ │
│  │  (left column) │   │  (centre column)  │   │  (right column)      │ │
│  └────────────────┘   └──────────────────┘   └──────────────────────┘ │
└───────────────────────────────────────────────────────────────────────┘
```

### Top toolbar

| Element | Human name | Hex (approx.) | Function |
|---|---|---|---|
| `Quick Battle Setup` title band | Coral red on yellow band | `#FFCC66` band, `#CC3333` text | Panel title |
| **Ships** tab | Yellow band when active | `#FFCC66` active / `#CC6633` idle | Switch to ship catalogue + sides editor |
| **Player and Region** tab | Yellow band when active | `#FFCC66` active / `#CC6633` idle | Switch to player faction + region picker |
| **Close** button | Coral red | `#CC3333` | Cancel and return to bridge / tactical view |
| **Start** button | Grey (idle) / yellow (ready) | `#888888` / `#FFCC66` | Begin combat simulation. Enabled only when at least one Enemy Ship is set |

Only one of the two left-side tabs is active at a time. The whole overlay is modal — bridge and combat input behind it is suppressed until Close or Start is clicked.

---

## Tab 1 — Ships

(Screenshots 16 and 17.)

### Left column — Ship catalogue tree

A scrollable expandable list of all available ship classes and bases. Top-level groups:

- Federation Ships
- Klingon Ships
- Ferengi Ships
- Romulan Ships
- Cardassian Ships
- Kessok Ships
- Other Ships
- Bases — *with subgroup expansion to:* Card Starbase, Card Station, Card Outpost, Comm Array, Comm Light, Dry Dock, Fed Starbase, Fed Outpost, Space Facility

Each group is a coral-red pill row. Expanded children render as lavender pill rows beneath their parent with indentation, e.g. *Romulan Ships → Warbird*. The currently highlighted child shows a yellow bullet dot to the left of its name (e.g. *Card Starbase* selected in screenshot 16).

### Centre column — Detail / preview

When a class is selected from the catalogue:

- **Ship Description** box — a tall lavender/purple-frame panel with body text describing the class. In screenshot 15 the Galaxy class is described: *"Until very recently, the Galaxy design was the Federation's top-of-the-line class of ship. Though created with space exploration in mind, the Galaxy class can make for a formidable battleship as well."* Weapons line below: *"Weapons: 8 Phasers and 6 …"*.
- 3-D / static preview render of the ship sits above the description (the Galaxy class is shown in screenshot 15).
- Two scrollbar-style arrows `▲ ▼` to the right of the description scroll its body if it overflows.

Below the description (Ships tab only — screenshots 16 / 17):

| Button | Function |
|---|---|
| **Add As Friendly Ship** | Appends the selected class to the Friendly Ships list (right column) |
| **Add As Enemy Ship** | Appends the selected class to the Enemy Ships list (right column) |
| **AI Level** | Sub-panel for setting the per-ship AI difficulty for the next-added unit |

### Right column — Sides editor (Ships tab)

Two stacked lists with action buttons between them:

```
┌── Friendly Ships ──────────┐
│                            │
│  (list of friendlies)      │
│                            │
├────────────────────────────┤
│  [ Move to Enemy Ships ]   │
│  [ Delete ]                │
│  [ Move to Friendly Ships ]│
├────────────────────────────┤
│ ── Enemy Ships ──          │
│                            │
│  (list of hostiles)        │
│                            │
└────────────────────────────┘
```

- *Friendly Ships* and *Enemy Ships* are each a vertical list of pill rows naming each entry. Empty in screenshots.
- **Move to Enemy Ships** — re-side the currently-highlighted friendly entry to the enemy list.
- **Move to Friendly Ships** — re-side the currently-highlighted enemy entry to the friendly list.
- **Delete** — remove the currently-highlighted entry from its list.

The player's own ship is **not** added through this column — it comes from the *Player and Region* tab's Player Bridge selector.

---

## Tab 2 — Player and Region

(Screenshot 15.)

### Left column — Faction / class catalogue

Same expandable tree as Tab 1, restricted to ship classes (no Bases). Highlighting a class shows its preview + Ship Description in the centre column. The currently-highlighted entry in screenshot 15 is *Galor* under Cardassian Ships, with Warbird under Romulan Ships also highlighted — the visual indication suggests **expanded but not selected**; only the row carrying the *yellow bullet* is the active selection.

### Centre column — Detail + Player Bridge selector

- Same ship-preview render + Ship Description body as Tab 1.
- Below the description: a **Player Bridge** sub-panel listing the bridges available for the selected faction. In screenshot 15: *Galaxy* (highlighted yellow) and *Sovereign* — these are the Federation bridges, each corresponding to a different hull. Clicking one sets it as the player's command bridge for the simulation.

### Right column — Combat Region

A long scrollable list of system / region names — every region defined in the campaign map. Visible entries in screenshot 15:

> Albirea, Alioth, Artrus, Ascella, Belaruz, Beol, Biranu, Cebalrai, Chambana, **Deep Space** (selected — purple/yellow row), Geble, Itari, Nepenthe, Omega Draconis, Ona, Poseidon, Prendel, Riha, Savoy, Serris, Tevron, Tezle, Vesuvi.

Each region is a coral-red pill row with a small `▶` chevron at the left edge. The current selection is shown by a lavender highlight (Deep Space and Riha both highlighted in screenshot 15 — the *bullet dot* on Deep Space indicates the active pick).

---

## Colour reference

| Element | Human name | Hex (approx.) |
|---|---|---|
| Overlay frame | Coral red | `#CC3333` |
| Title bar background | Pale yellow | `#FFCC66` |
| Title bar text | Coral red | `#CC3333` |
| Active tab band | Pale yellow | `#FFCC66` |
| Idle tab band | Burnt orange | `#CC6633` |
| **Close** button | Coral red | `#CC3333` |
| **Start** button (disabled) | Grey | `#888888` |
| **Start** button (enabled) | Pale yellow | `#FFCC66` |
| Catalogue group row | Coral red | `#CC3333` |
| Catalogue expanded child | Lavender | `#CC99CC` |
| Selected catalogue row | Lavender + yellow bullet | `#CC99CC` + `#FFFF00` |
| Ship Description frame | Lavender / purple | `#9966CC` |
| Description body text | White / pale yellow | `#FFFFCC` |
| Sides-action buttons | Lavender pill | `#CC99CC` |
| Sides-action button text | Yellow gold | `#FFCC66` |

---

## Interactions

- Click a group row in the catalogue → expand / collapse its child list.
- Click a child row → set it as the catalogue selection (yellow bullet on left).
- Click **Add As Friendly Ship** / **Add As Enemy Ship** → append the catalogue selection to that side.
- Click an entry in Friendly Ships or Enemy Ships → highlight; then **Move to …** or **Delete** acts on that entry.
- Click a Player Bridge row (Tab 2) → set the player's command bridge.
- Click a Combat Region row → set the simulation venue.
- Switch tabs by clicking **Ships** or **Player and Region** at the top.
- Click **Close** to dismiss the overlay without starting.
- Click **Start** to begin the simulation (becomes interactive once at least one Enemy Ship is configured).

> The overlay is mouse-driven; keyboard navigation falls back to `↑` / `↓` to walk the focused list and `Enter` to activate. All bindings are remappable through the game's input configuration.

---

## Interior vs exterior behaviour

The overlay is **modal and renders on top of whatever view was active** when *Quick Battle Setup* was selected:

| Aspect | Interior (Bridge) | Exterior (Tactical Mode) |
|---|---|---|
| Background view visible behind overlay? | Yes — the bridge interior shows through any transparent gaps (screenshots 15 / 16 show Saffi behind the panel) | Yes — the third-person ship view shows through |
| Bridge / Tactical input | Suppressed (modal) | Suppressed (modal) |
| Closes via | **Close** button (returns to whichever view was active) | **Close** button (same) |
| Layout | Identical | Identical |

When the overlay is dismissed via **Start**, the simulation begins immediately — the player is returned to the bridge / tactical view with the new opposing force already in place and the XO's *Start Combat* row already toggled. **End Combat** under XO terminates the scenario.
