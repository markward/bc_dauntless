# Launch Screen, Main LCARS Menu, Load, Configure

Everything outside actual gameplay: the OS-level launcher, the LCARS
shell, save management, and the configuration screens.

---

## Launch Screen

Pre-`stbc.exe` host shell. Auto-shown when the game CD is inserted (if
AutoPlay is enabled), or by manually running `Setup` from the CD root.
This is technically not the game UI — it's a Windows installer/launcher
window — but it's the documented entry point in the manual.

### Buttons

| Button | Behaviour |
|---|---|
| **Install** | Begins installation. Renames itself to *Reinstall* once installation is complete. |
| **Extras** | Browser of demos and other titles. |
| **Links** | External URLs to other Star Trek and Activision websites. |
| **Play** | Launches the installed game. **Disabled until the game is installed.** |
| **Help/Support** | Opens the Bridge Commander Help File (HTML — install instructions, known compatibility issues, troubleshooting steps). |
| **Exit** | Closes the launcher. |

The manual is silent on Launch Screen layout details (button order,
geometry); it lists the buttons in the order above.

---

## Main LCARS Menu

The first in-game screen the player sees after pressing *Play*. Named
"LCARS" after Trek's *Library Computer Access and Retrieval System*.

### Reachability

- **First load**: shown automatically on game launch.
- **Mid-game**: pressing `ESC` *anywhere* in the game opens this menu as
  an overlay on the current screen. Pressing `ESC` again closes it.
- **End of mission / save**: returns here.

### Menu items (top-to-bottom)

| Item | Action |
|---|---|
| **New Game** | Opens the player-name / difficulty entry pane; *Start* there begins the single-player campaign at mission 1. |
| **Quick Battle** | Drops the player onto a ready bridge with Quick Battle options on Saffi's menu. (See [`quick-battle-and-multiplayer.md` § Quick Battle](quick-battle-and-multiplayer.md#quick-battle).) |
| **Multiplayer** | Opens the Multiplayer Main Menu. (See [`quick-battle-and-multiplayer.md` § Multiplayer](quick-battle-and-multiplayer.md#multiplayer).) |
| **Load Game** | Opens the [Load Game](#load-game) dialog. |
| **Configure** | Opens [Configure](#configure). |
| **Quit Game** | Ends the current game / exits to the OS desktop. |

### Navigation rules

| Input | Effect |
|---|---|
| Mouse hover + `LMB` | Standard click-to-select. |
| `↑` / `↓` | Move highlight up/down menu items. |
| `Enter` | Activate highlighted item (open submenu / press button). |
| `Tab` | Cycle between distinct sub-areas of the screen (the menu list, a sidebar, etc.). |
| `←` / `→` | Step through value cycles on settings; collapse / expand a parent menu. |
| `ESC` | Close the LCARS overlay (returns to the underlying game screen, if any). |

### New Game pane

Reached from *Main LCARS Menu → New Game*.

Fields:

- **Player's Name** — free-form text. Forbidden characters: `,` `<` `.`
  `>` `?` `/` `"` `\` `|` `:`. Optional, but used as the save-game
  identifier — keeping the same name on a re-start overwrites old saves.
- **Difficulty** — three radio buttons, mutually exclusive:
  - *First Officer* (easiest — friendliest to new players / story-mode).
  - *Captain* (medium — middle ground).
  - *Admiral* (hardest — for seasoned players).
- **Start** — bottom-right; commits and launches mission 1.

The manual doesn't specify a *Cancel* button, but the screen is
escapable via the standard `ESC` toggle to the LCARS overlay.

---

## Load Game

Reached from *Main LCARS Menu → Load Game*.

Save files are auto-created at "key points" during the single-player
campaign. They are named by the **Player's Name** entered on the New
Game screen.

UI elements:

- A **list of save files** (one row per player name).
- **Load Game** button — loads the highlighted file → bridge.
- **Delete** button — removes the highlighted file (irreversible — the
  manual does not document a confirmation step).

The manual does not document file metadata shown in the list (date,
mission, score). It shows only that selection is by player name.

---

## Configure

Reached from *Main LCARS Menu → Configure*. Four functional groupings —
the manual presents them as one scrolling configure screen with
expandable sub-headings rather than separate tabs.

### Configure UI conventions

These conventions apply across all four groupings:

- **Click an option** to cycle through its valid settings or to toggle
  on/off.
- **A checkbox to the immediate left of an option** is the on/off
  indicator; **lit = on**.
- **A rightward-pointing arrow to the immediate left of an option**
  indicates an expandable submenu. Click the heading to expand it; the
  arrow rotates to point left to indicate the expanded state. Click
  again to collapse.

### General Options

| Option | Effect | Default behaviour stated in manual |
|---|---|---|
| **Subtitles** | Toggles spoken-line subtitles on/off. | unspecified |
| **Collisions** | Off → the ship cannot collide with / ram other vessels. On → standard hard-body collisions. | unspecified |
| **Character Tool Tips** | Shows / hides the floating status window above a crew member when they're centred in view on the bridge. | unspecified |
| **Collision Alert** | Toggles the audible/visual ship-collision-alert messages. | unspecified |

### Sound

| Control | Effect |
|---|---|
| **Sound Quality** | Submenu. Includes Aureal A3D and Creative Labs EAX 3D-positional sound options if the host hardware supports them. |
| **SFX** | Toggle sound effects. |
| **SFX Volume** | Slider; `←` / `→` arrow buttons or drag. Drives interface + SFX volume. |
| **Voice** | Toggle voice-over lines. |
| **Voice Volume** | Slider for voice volume. |
| **Music** | Toggle music. |
| **Music Volume** | Slider for music volume. |

### Configure your Computer's Graphics

Three nested groupings.

#### Screen Options

| Option | Effect |
|---|---|
| **Display Device** | Pick which video adapter the game uses (one entry per video card). |
| **Resolution** | Cycle resolutions. Higher = better visuals, slower on most cards. |
| **Color Depth** | High (32 bpp) or Low (16 bpp). **Cannot be changed during a mission.** |

#### Master Graphic Quality

A global preset that drives every per-feature toggle below: **High /
Medium / Low / Custom**. Setting any of the per-feature toggles flips
this to *Custom*.

#### Per-feature graphics toggles

> Marked **(locked in mission)** = *cannot be changed while a mission is currently running*. The remainder can be toggled live.

| Option | Effect | In-mission lock |
|---|---|---|
| **Model Detail** | High / Medium / Low. Higher = more detailed ship models, slower on older cards. | locked in mission |
| **Texture Detail** | High / Medium / Low. Lower = lower-VRAM-footprint textures. | locked in mission |
| **Visible Damage** | Off / Low / Medium / High. Off → no damage visuals. Low → surface damage only. Medium → adds hull holes. High → adds component separation (broken pieces fly off). Medium and High are recommended only on fast machines. | locked in mission |
| **MipMaps** | On/Off. Off saves texture VRAM at the cost of rendering quality. | live |
| **Glow Effects** | On/Off. Lights up warp nacelles and ship lights. Small or no perf cost. | locked in mission |
| **Enhanced Glows** | On/Off. Improves the standard glows. **Disabled unless Glow Effects is on AND the 3D card supports it.** | live |
| **Specular Highlights** | On/Off. Adds shiny/metallic highlights. | live |
| **Motion Blur** | On/Off. Engages on in-system warp speed transitions only. | live |
| **Space Dust** | On/Off. Visualises ship motion through space. | live |

### Configure Controls

A table of **command groups**, each containing one or more remappable
commands. The four groups are:

- **Miscellaneous** (LCARS toggle, screenshot, alert states, dialog skip,
  menu select, viewscreen toggles, score/chat/team-chat windows).
- **Menu** (menu navigation, Tab focus block).
- **Ship** (flight, weapons, speed, intercept, tractor, cloak, self
  destruct).
- **Camera** (Tactical and Bridge cameras, zoom, cinematic).

Procedure to remap:

1. Click the group heading to expand it.
2. Click the row for the command you want to rebind. A modal *Select a
   new key* prompt appears.
3. Press the new key (or click the new mouse button). The new bind takes
   effect immediately.
4. To abort before pressing anything, click *Cancel*.

Bottom-row buttons:

- **Cancel** — discard the changes you just made and revert to the
  bindings in effect when you opened the screen.
- **Default** — replace all bindings with the original out-of-box
  defaults.

> The full list of out-of-box default bindings is in
> [`keyboard-mouse-reference.md`](keyboard-mouse-reference.md).

---

## Quit Game

The *Quit Game* item on the Main LCARS Menu has two interpretations,
depending on context:

- If a mission is running (single-player or QB) → ends the current game,
  returning to the menu.
- If no mission is running → exits `stbc.exe` to the OS desktop.

The manual does not document a confirm prompt; in practice both branches
of the manual entry simply say "select this option to end your current
game, or to exit the program to the desktop."
