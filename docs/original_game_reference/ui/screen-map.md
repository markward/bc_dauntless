# Screen Map and Navigation

The complete graph of screens the player can reach in *Star Trek: Bridge
Commander*, plus the inputs that move them between screens. Every node
on this graph is documented in detail in one of the sibling files.

---

## Top-level screen graph

```
                        ┌────────────────────────────────┐
                        │ 1. Launch Screen (OS shell)    │
                        │    Install · Extras · Links    │
                        │    Play · Help/Support · Exit  │
                        └─────────────┬──────────────────┘
                                      │ Play
                                      ▼
              ┌─────────────────────────────────────────────────┐
              │ 2. Main LCARS Menu                              │◄── ESC from
              │   ┌────────────────────────────────────────┐    │    most in-game
              │   │ • New Game                             │    │    screens
              │   │ • Quick Battle                         │    │
              │   │ • Multiplayer                          │    │
              │   │ • Load Game                            │    │
              │   │ • Configure                            │    │
              │   │ • Quit Game                            │    │
              │   └────────────────────────────────────────┘    │
              └─┬───────┬───────┬───────┬──────────┬────────────┘
                │       │       │       │          │
                │       │       │       │          └─► (3) Configure ──┐
                │       │       │       └─► (4) Load Game dialog       │
                │       │       └─► (5) Multiplayer Main Menu          │
                │       │              ├─► (5a) Join Game              │
                │       │              ├─► (5b) Host Game              │
                │       │              │    └─► (5c) Ship Select       │
                │       │              │            └─► (8) MP Bridge  │
                │       │              └─► back to (2)                 │
                │       └─► (6) Quick Battle (loads bridge directly)   │
                │              └─► (7) Quick Battle Setup (Saffi menu) │
                │                       └─► (8) Bridge in QB mode      │
                │                                                      │
                └─► (8) Single-Player Campaign Bridge ◄────────────────┘
                          │ ▲                       │
                          │ │ Space                 │
                          │ ▼                       │
                        (9) Tactical Mode           │
                                                    │
                       ESC from (8) or (9) ─────────┘
                       (returns overlayed (2))
```

The **screen IDs in parentheses** match the section numbering used below.

---

## (1) Launch Screen

Pre-game host shell, presented before `stbc.exe` enters the LCARS UI.
Auto-shown when the install CD is inserted (AutoPlay), or by running
`Setup` manually.

- **Install** — runs/repeats install. Becomes *Reinstall* once installed.
- **Extras** — demos / other-product browser.
- **Links** — opens external Star Trek website links.
- **Play** — launches the actual game (greyed until installed). This is
  the only edge that leads into screen (2).
- **Help/Support** — opens the Bridge Commander Help File (HTML).
- **Exit** — closes the launcher.

> Detail: [`launch-and-main-menu.md` § Launch Screen](launch-and-main-menu.md#launch-screen).

---

## (2) Main LCARS Menu

The top-level in-game menu. Reachable from any in-game screen by
pressing `ESC` (acts as a toggle).

| Option | Goes to |
|---|---|
| New Game | Player-name / difficulty entry → (8) Bridge with mission 1 |
| Quick Battle | (6) Quick Battle (bridge w/ Quick Battle Setup option) |
| Multiplayer | (5) Multiplayer Main Menu |
| Load Game | (4) Load Game dialog |
| Configure | (3) Configure |
| Quit Game | Ends mission, or exits to OS |

Navigation **inside the LCARS menu**:

- Mouse: hover and `LMB`-click.
- Keyboard: `↑` / `↓` to move highlight, `Enter` to select, `Tab` to
  cycle between sub-areas of the screen, `←` / `→` to expand/collapse
  submenus or to step through value cycles on settings.

> Detail: [`launch-and-main-menu.md` § Main LCARS Menu](launch-and-main-menu.md#main-lcars-menu).

---

## (3) Configure

Sub-tabs:
- **General Options** — Subtitles, Collisions, Character Tool Tips,
  Collision Alert.
- **Sound** — Sound Quality (incl. A3D / EAX), SFX & Voice & Music
  toggles + volume sliders.
- **Configure your Computer's Graphics** — Display Device, Resolution,
  Color Depth, Master Graphic Quality, then per-feature toggles
  (Model Detail, Texture Detail, Visible Damage, MipMaps, Glow Effects,
  Enhanced Glows, Specular Highlights, Motion Blur, Space Dust).
- **Configure Controls** — re-binding UI for all command groups.

Returns to (2) on `ESC` or via the screen's back/close affordance.

> Detail: [`launch-and-main-menu.md` § Configure](launch-and-main-menu.md#configure).

---

## (4) Load Game dialog

Lists save files keyed by player name. Two operations:

- *Load Game* — selects a file and loads → (8) Bridge.
- *Delete* — selects a file and removes it.

Returns to (2) when dismissed.

> Detail: [`launch-and-main-menu.md` § Load Game](launch-and-main-menu.md#load-game).

---

## (5) Multiplayer Main Menu

Three buttons:

- **Host Game** → (5b)
- **Join Game** → (5a)
- **Main Menu** → returns to (2)

> Detail: [`quick-battle-and-multiplayer.md` § Multiplayer](quick-battle-and-multiplayer.md#multiplayer).

### (5a) Join Game

Form:
- Player Name (text)
- Password (text — for joining a restricted game)
- Direct Join Game button + IP-address field
- Internet/LAN selector
- Start Query / Stop Query button
- Result table: Name, Type, Ping, P/M (current/max), Players, Game Info
- *Start* button → joins the highlighted game → (5c) Ship Select

### (5b) Host Game

Form:
- Game (select from game-type list — see below)
- Game Name (text)
- Player Name (text)
- Password (text)
- Internet Game / LAN Game radios
- Dedicated Server toggle
- *Start* → (5c)

### (5c) Ship Select

Lobby:
- Ship-class list (filtered by game-type rules, see
  [`quick-battle-and-multiplayer.md`](quick-battle-and-multiplayer.md)).
  Selecting shows ratings + tactical tip text.
- (Host only) System / region selector.
- (Host only) Player count, time-limit, score-limit setters.
- *Start* → (8) MP Bridge.

### Game types reachable from (5b) → (5c):

- **Deathmatch** — free-for-all.
- **Team Deathmatch** — two teams.
- **UFP vs. Non-UFP Deathmatch** — Federation vs. all others.
- **Defend the Starbase** — attackers vs. defenders.

(See [`quick-battle-and-multiplayer.md` § Game Types](quick-battle-and-multiplayer.md#game-types).)

---

## (6) Quick Battle (in-bridge entry)

Selecting *Quick Battle* on (2) drops the player straight onto a bridge.
At this point Saffi's menu has three Quick Battle-specific entries:

- *Quick Battle Setup* → opens (7).
- *Start Combat Simulation* → begins fighting.
- *End Combat Simulation* → returns to a "ready" state on the bridge.

> Detail: [`quick-battle-and-multiplayer.md` § Quick Battle](quick-battle-and-multiplayer.md#quick-battle).

### (7) Quick Battle Setup

Modal panel reached from Saffi's menu in (6). Two sub-views:

- **Ships** — pick friendly + enemy ships, set per-ship AI level (Low /
  Medium / High), Add as Friendly / Add as Enemy / delete.
- **Player and Region** — pick the player's race and ship, plus the
  region/planet for the engagement.

Plus *Close* (returns to (6)) and *Start* (begins the simulated battle
in (8)).

---

## (8) In-mission Bridge

The first-person bridge view, used for both single-player and
multiplayer missions and for Quick Battle. Two layers of content
co-exist on this screen:

- **The bridge itself** — 3D scene with crew at their stations. Look
  left/right with the mouse to centre on a crew member. A *Character
  Tool Tip* appears showing rank, name, station, and current order.
- **Crew menus** — opening any officer's menu (LMB or `F1`–`F5`)
  layers an LCARS-style menu over the screen with that officer's
  available orders. `F6` opens a guest menu (when a guest is on the
  bridge).

Always-visible HUD pieces while on the bridge:
- Sensors (lower-left)
- Shields (lower area)
- Weapons (lower area)
- Speed indicator
- Phaser Arc / Torpedo display (lower-right)
- Target Shields (upper-left, when a target is selected)

(These are shared with Tactical Mode — see [§ tactical-mode](tactical-mode.md).)

Bridge-only viewscreen camera commands (the front "viewscreen" picture
the bridge looks at): `Home` / `Del` / `PgDn` / `End` / `PgUp` / `Ins`
plus `=`/`–` zoom and `ScrLk` (lock to target).

> Detail: [`bridge-mode.md`](bridge-mode.md).

### Edges out of (8):

- `Space` → (9) Tactical Mode (toggles back the same way).
- `ESC` → overlays (2) Main LCARS Menu.
- Saffi → *Contact Starfleet* / *Contact Engineering* / *Show Mission
  Log* / *Objectives* — these are sub-menus within the bridge, not
  separate screens.
- LoMar → *Set Course* (system list) → *Warp* (transition with
  cinematic), *Orbit Planet* → planetary orbit, *Dock* → docking with
  Starbase 12 (resupply/repair).

---

## (9) Tactical Mode

External 3rd-person camera over the player's ship. Same HUD elements as
(8) but the player now flies and fires the ship directly.

- `Space` → (8) Bridge.
- `ESC` → (2) Main LCARS Menu (overlay).
- `M` → toggles Map Mode (a navigation overview, see
  [`tactical-mode.md` § Map Mode](tactical-mode.md#map-mode)).
- `F9` → toggles Cinematic Mode; once in cinematic mode, `F1`–`F6`
  pick a cinematic camera variant (Fly-by, Free Camera, Target Camera,
  Torpedo Camera, Panoramic, Long Range Free).

Issuing any order to Felix (`F2` menu, or any of his manoeuvre/tactic
choices) hands the conn back to him; the player loses direct piloting
control until they take it again with WASD.

> Detail: [`tactical-mode.md`](tactical-mode.md).

---

## Cross-cutting overlays (not full screens)

These are not separate screens but layered modal-ish UI on top of the
current mode:

| Overlay | Trigger | Where it appears |
|---|---|---|
| Crew menu | LMB on a crew member, or `F1`–`F6` | Bridge view |
| Guest menu | `F6` | Bridge view (only if a guest is present) |
| Manual Fire reticle | Toggle on Felix's menu, or `H` | Tactical (cursor changes) |
| Map Mode | `M` | Tactical |
| Score Window (MP) | `[` | Either |
| Chat Window (MP) | `]` | Either |
| Team Chat input | `\` | Either |
| Cinematic camera | `F9`, then `F1`–`F6` | Tactical |
| LCARS Menu (Main) | `ESC` | Either, layered on top |

---

## Navigation matrix

A flat lookup of "from screen X with input Y, go to Z":

| From | Input | To |
|---|---|---|
| (1) Launch | *Play* | (2) Main LCARS |
| (1) Launch | *Exit* | OS |
| (2) Main LCARS | *New Game* → name → *Start* | (8) Bridge (mission 1) |
| (2) Main LCARS | *Quick Battle* | (6) Quick Battle ready |
| (2) Main LCARS | *Multiplayer* | (5) MP Main |
| (2) Main LCARS | *Load Game* | (4) Load dialog |
| (2) Main LCARS | *Configure* | (3) Configure |
| (2) Main LCARS | *Quit Game* | OS or post-mission |
| (3) Configure | `ESC` | (2) Main LCARS |
| (4) Load | *Load Game* | (8) Bridge |
| (4) Load | back | (2) Main LCARS |
| (5) MP Main | *Host Game* | (5b) Host |
| (5) MP Main | *Join Game* | (5a) Join |
| (5) MP Main | *Main Menu* | (2) Main LCARS |
| (5a) Join | *Start* | (5c) Ship Select |
| (5b) Host | *Start* | (5c) Ship Select |
| (5c) Ship Select | *Start* | (8) Bridge (MP) |
| (6) Quick Battle | Saffi → *Quick Battle Setup* | (7) QB Setup |
| (6) Quick Battle | Saffi → *Start Combat Simulation* | (8) Bridge (sim) |
| (7) QB Setup | *Close* | (6) Quick Battle |
| (7) QB Setup | *Start* | (8) Bridge (sim) |
| (8) Bridge | `Space` | (9) Tactical |
| (8) Bridge | `ESC` | (2) Main LCARS overlay |
| (8) Bridge | LoMar → *Warp* | (8) Bridge in destination system |
| (8) Bridge | LoMar → *Dock* (near SB12) | docking sequence + auto-resupply |
| (8) Bridge | Saffi → *End Combat Simulation* (QB only) | (6) Quick Battle ready |
| (9) Tactical | `Space` | (8) Bridge |
| (9) Tactical | `ESC` | (2) Main LCARS overlay |
| (9) Tactical | order to Felix (any) | (9) but conn returned to Felix |

---

## Mode-aware key behaviours

A handful of keys mean different things depending on which mode you're
in:

| Key | Bridge | Tactical |
|---|---|---|
| `F1` | Open / close LoMar (Helm) menu | (same) |
| `F2` | Open / close Felix (Tactical) menu | (same) |
| `F3` | Open / close Saffi (First Officer) menu | (same) |
| `F4` | Open / close Miguel (Science) menu | (same) |
| `F5` | Open / close Brex (Engineering) menu | (same) |
| `F6` | Open / close guest menu / close any menu | (same) |
| `Space` | Toggle to Tactical | Toggle to Bridge |
| `M` | Toggle Map Mode (still works on bridge) | Toggle Map Mode |
| `Home`–`Ins` numpad block | Aim viewscreen | (no effect — viewscreen isn't visible) |
| `=` / `–` | Zoom on viewscreen | Zoom camera |
| `LMB` | Click crew / menu items | Fire phasers (if cursor outside menu) |
| `RMB` | Cancel / deselect | Fire torpedoes (if cursor outside menu) |
| `MMB` | — | Fire disruptors (faction ships only) |
| `WASD/Q/E` | (no effect — bridge is fixed) | Pilot the ship |

---

## See also

- [`bridge-mode.md`](bridge-mode.md) for the per-officer menu trees.
- [`tactical-mode.md`](tactical-mode.md) for HUD panel layout.
- [`keyboard-mouse-reference.md`](keyboard-mouse-reference.md) for the
  full default bind list as the Configure Controls screen organises it.
