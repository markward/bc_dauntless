# Configure Screen — UI Specification

The Configure screen opened from the Main LCARS Menu. Four functional categories — **General**, **Sound**, **Graphics**, **Controls** — selected from a column of category buttons. *Controls* fans out into four sub-categories (Misc., Menu, Ship, Camera).

Source of truth (text-level): [launch-and-main-menu.md § Configure](launch-and-main-menu.md#configure). This file documents the visual layout, palette, and per-row content observed in the screenshots.

---

## Overall screen layout

The Configure screen is rendered over the persistent **Main LCARS Menu chrome**. The chrome remains visible in every screenshot:

```
┌───────────────────────────────────────────────────────────────────┐
│ ▓▓▓ red-orange band ▓▓▓                                           │  ← top header band
│ STAR TREK    [ New Game ][ Multiplayer ][ Configure ][ Quit Game ]│
│ BRIDGE       [ Load Game ][ Quick Battle ][ Credits ]             │
│ COMMANDER                                                         │
├───────────────────────────────────────────────────────────────────┤
│ ┌──────┐  ┌──────── Configure ─────────────────┐                  │
│ │ LCARS│  │                                    │                  │
│ │ side │  │  Category │ Sub-category │ Detail  │                  │
│ │ panel│  │  buttons  │ buttons (if  │ pane    │                  │
│ │      │  │           │ Controls)    │         │                  │
│ │ ship │  │                                    │                  │
│ │ icon │  │  [Cancel] [Default]                │                  │
│ └──────┘  └────────────────────────────────────┘                  │
└───────────────────────────────────────────────────────────────────┘
```

### Top header

- Title-band colour: red-orange `#CC3333` running edge-to-edge across the top.
- **"STAR TREK BRIDGE COMMANDER"** wordmark on the left in pale grey-tan over the band.
- Two rows of pill buttons on the right:
  - Row 1: **New Game**, **Multiplayer**, **Configure**, **Quit Game**
  - Row 2: **Load Game**, **Quick Battle**, **Credits**
- Active button (the screen the user is on — *Configure* in every screenshot) renders in **burnt orange `#CC6633` with dark text**; idle buttons are **pale yellow `#FFCC66` with dark text**.

### Left LCARS side panel

A purely cosmetic LCARS column running the full height of the screen on the left:

- Lavender / pale violet background `#9999CC` and `#CCCCFF`.
- Random-looking **telemetry numbers** scattered through it (`6524 717`, `42 76264`, `24453 12`, `028`, etc.). These differ between screenshots; they are LCARS decoration — not real configuration data.
- A **ship-class wireframe / render** at the bottom (the player's currently selected hull — Galaxy / Sovereign / Akira variants are visible across screenshots), with a ship registry number `25` and serial `4926452 961` below.
- A small **mission-tally style box** with a three-digit number (`028`, `162`, `413`, etc.) — also decorative.

The side panel is non-interactive in this screen.

### Bottom strip

A red-orange `#CC3333` band running across the bottom edge of the screen, mirroring the top. Holds no interactive elements on Configure — purely framing.

### Right LCARS sliver

A narrow column on the right edge that mirrors the colours of the left panel but is much thinner. Carries two more telemetry numbers near the bottom-right (`284 99`, `297 59`, `296 34` …) and the **Starfleet arrowhead** logo.

---

## Configure panel — common chrome

The active Configure window sits centred-left. Layout is constant across all four categories:

```
┌─ Configure ──────────────────────────────────────┐
│                                                  │
│  ┌────────┐  ┌────────┐  ┌────── detail ──────┐  │
│  │General │  │ Misc.  │  │  (scrollable rows  │  │
│  │ Sound  │  │ Menu   │  │   with ▲▼ arrows   │  │
│  │Graphics│  │ Ship   │  │   when overflowing)│  │
│  │Controls│  │ Camera │  │                    │  │
│  └────────┘  └────────┘  └────────────────────┘  │
│  ┌────────┐                                      │
│  │ Cancel │                                      │
│  │Default │                                      │
│  └────────┘                                      │
└──────────────────────────────────────────────────┘
```

### Common palette

| Element | Human name | Hex (approx.) |
|---|---|---|
| Configure window frame | Lavender | `#CC99CC` |
| Window title "Configure" | Hot pink | `#CC66CC` |
| Category button (idle) | Burnt orange | `#CC6633` |
| Category button (active) | Brown / muted orange | `#996633` |
| Category button text | Dark brown / black | `#332211` |
| Sub-category button (idle) | Pink | `#CC6699` |
| Sub-category button (active) | Dark magenta | `#663366` |
| Sub-category button text | Dark text | `#332211` |
| **Cancel** button | Pale yellow | `#FFCC66` |
| **Default** button | Pale yellow | `#FFCC66` |
| Detail-pane background | Black | `#000000` |
| Detail-pane frame | Coral red | `#CC3333` |
| Scrollable row (idle) | Lavender | `#CC99CC` |
| Scrollable row (selected / hover) | Hot pink | `#FF6699` |
| Row text | Yellow gold | `#FFCC66` |
| Detail-pane scroll arrows `▲ ▼` | Coral on yellow | `#CC3333` on `#FFCC66` |
| Toggle bullet (on) | Bright yellow | `#FFFF00` |
| Toggle bullet (off / unavailable) | Black / charcoal | `#222222` |
| Expansion chevron `▶` | Coral red on lavender | `#CC3333` |

### Category buttons (always present)

- **General**
- **Sound**
- **Graphics**
- **Controls** — when active, surfaces the four sub-category buttons (Misc., Menu, Ship, Camera) to its right.

Only one category is active at a time; clicking another switches the detail pane immediately.

### Cancel / Default buttons (bottom-left of window)

- **Cancel** — discard changes made in this Configure session, revert to bindings / values in effect when the screen was opened.
- **Default** — replace all bindings / values with the out-of-box defaults.

Both apply *globally* across all four categories, not just the currently-shown one.

---

## General category

Single flat list of four boolean toggles. Visible in screenshot 7.

| Row | Toggle state shown | Effect |
|---|---|---|
| **Subtitles** | On (yellow bullet) | Spoken-line subtitles on / off |
| **Collisions** | On | Disable to make the ship pass through other vessels without ramming damage |
| **Character Tool Tips** | On | Floating crew-status tooltip when a crewman is centred in view on the bridge |
| **Collision Alert** | On | Audible/visual collision alarm |

Layout: each row is a single lavender pill with the label on the left and a yellow toggle bullet at the left edge. No sliders, no chevrons.

---

## Sound category

Four logical groups, two of which expose **sub-options under an expansion**:

### Expanded view (screenshot 9)

```
▶ Sound Quality          ← expanded header (chevron pointing down/left)
  ○ EAX Hardware         ← disabled / unavailable on this system (grey)
  ● Low Quality Software ← current selection (highlighted)
● SFX
  SFX Volume   [████████████████] 100%
● Voice
  Voice Volume [████████████░░░░]  80%
● Music
  Music Volume [████████░░░░░░░░]  60%
```

### Collapsed view (screenshot 10)

```
▶ Sound Quality          ← chevron pointing right; sub-options hidden
● SFX
  SFX Volume   [████████████████] 100%
● Voice
  Voice Volume [████████████░░░░]  80%
● Music
  Music Volume [████████░░░░░░░░]  60%
```

### Rows

| Row | Type | Notes |
|---|---|---|
| **Sound Quality** | Expandable | Chevron `▶` toggles expand / collapse. Sub-options are mutually-exclusive radio rows. |
| → EAX Hardware | Radio | Greyed when the hardware doesn't support it (screenshot 9). |
| → Low Quality Software | Radio | Fallback software-mixed sound. |
| **SFX** | Toggle | Enables / disables sound effects channel. Yellow bullet at left. |
| **SFX Volume** | Slider | 0–100%; current value shown right-aligned. |
| **Voice** | Toggle | Enables / disables voice-over channel. |
| **Voice Volume** | Slider | 0–100%. |
| **Music** | Toggle | Enables / disables music channel. |
| **Music Volume** | Slider | 0–100%. |

### Volume slider visual

A pink/coral fill track `#CC6699` with a small **white thumb** marking the current value. The percentage value is rendered at the right end of the row in yellow text.

The manual references additional 3-D positional sound options (Aureal A3D, EAX 3D) that surface only on supporting hardware — the screenshot's system shows only the `EAX Hardware` row (greyed) plus `Low Quality Software`. See [launch-and-main-menu.md § Sound](launch-and-main-menu.md#sound).

---

## Graphics category

Single scrollable list mixing **expandable rows**, **cycle-value rows** and **toggles**. Visible in screenshot 8, with the *Resolution* row in its expanded state.

### Rows

| Row | Type | Visible values | Notes |
|---|---|---|---|
| **Display Device** | Expandable | `T&L Intel(R) HD Graphics` shown | One row per detected video adapter |
| **Resolution** | Expandable | `640 x 480`, **`800 x 600`** (selected), `1024 x 768`, `1280 x 1024`, `1600 x 1200` | The current selection has a yellow / lighter highlight; clicking another sets it |
| **Color depth** | Cycle | `LOW` | Toggles `LOW` ↔ `HIGH` (16 ↔ 32 bpp). Locked while a mission is running |
| **Master Graphic Quality** | Cycle | `HIGH` | Cycles `HIGH` / `MEDIUM` / `LOW` / `CUSTOM`; flips to *Custom* automatically when any per-feature toggle is changed |
| **Model Detail** | Cycle | `HIGH` | `HIGH` / `MEDIUM` / `LOW`. Locked in mission |
| **Texture Detail** | Cycle | `HIGH` | `HIGH` / `MEDIUM` / `LOW`. Locked in mission |
| **Visible Damage** | Cycle | `HIGH` | `OFF` / `LOW` / `MEDIUM` / `HIGH`. Locked in mission |
| **MipMaps** | Toggle | On (yellow bullet) | Live |
| **Glow Effects** | Toggle | On | Locked in mission |
| **Enhanced Glows** | Toggle | **Off** (dark bullet) | Visible in screenshot 8 with a black bullet — likely *unavailable* because either Glow Effects-dependent or hardware-limited. Live when available |
| **Specular Highlights** | Toggle | On | Live |
| **Motion Blur** | Toggle | On | Live; engages on in-system warp transitions |

A **Space Dust** row (per the manual) is expected below Motion Blur but was not visible in screenshot 8 — it may require scrolling.

### Expanded-row visual style

When an expandable row is expanded, its **chevron rotates** from `▶` to a downward/leftward orientation and the child rows render below it, indented and using the same pill style. The current value of the child set carries a **lighter pink highlight** (visible on the `800 x 600` row in screenshot 8).

### Scroll arrows

A `▲ ▼` pair appears at the **bottom-right corner of the detail pane** when the row list overflows the visible area — visible in screenshots 3, 4, 5, 6. Click to scroll.

---

## Controls category

Four sub-categories surface when *Controls* is selected: **Misc.**, **Menu**, **Ship**, **Camera**. Each is a flat scrollable list of `[ <key> ] : <action>` rows.

Each row is a single lavender pill with the keystroke in brackets (e.g. `[ c ]`, `[ CTRL-I ]`, `[ ALT-T ]`, `[ Scroll Up ]`, `[ f, L Button ]` for keys with alt mouse bindings) followed by `:` and the action label. Click any row to enter a **rebind prompt** (a modal that waits for the next key / mouse-button press and assigns it).

> Bindings shown below are the **out-of-the-box defaults**. Every row is remappable; values written here reflect what the screenshots show, not what's hardcoded.

### Controls → Misc. (screenshots 3 and 4)

A long list spanning two screenshots of scrolling.

| Key | Action |
|---|---|
| `"` | Go to yellow alert |
| `£` | Go to red alert |
| `CTRL-I` | Intercept target |
| `CTRL-T` | Clear target |
| `t` | Select next target |
| `y` | Select previous target |
| `u` | Select nearest target |
| `i` | Target next enemy |
| `j` | Target target's attacker |
| `n` | Target next nav point |
| `p` | Target the next planet |
| `SCRL LOCK` | On screen *(lock viewscreen onto current target — see [bridge-mode.md § Camera and look controls](bridge-mode.md#camera-and-look-controls))* |
| `HOME` | Viewscreen forward |
| `DEL` | Viewscreen left |
| `PG DN` | Viewscreen right |
| `END` | Viewscreen backwards |
| `PG UP` | Viewscreen up |
| `INS` | Viewscreen down |
| `SPACE` | Bridge or tactical |
| `m` | Toggle map mode |
| `F9` | Toggle cinematic mode |
| `PRINT SCRN` | Screen shot |
| `h` | Toggle manual fire |
| `ALT-T` | Toggle tractor beam |
| `ALT-C` | Toggle cloaking device |
| `[` | Toggle score window |
| `]` | Toggle chat window |
| `#` | Toggle team chat |
| `F1` | Talk to helm |
| `F2` | Talk to tactical |
| `F3` | Talk to first officer |
| `F4` | Talk to science |
| `F5` | Talk to engineering |
| `F6` | Talk to guest |
| `BACKSP` | Skip past dialog |
| `!` | Go to green alert |

### Controls → Menu (screenshot 2)

| Key | Action |
|---|---|
| `UP` | Previous menu item |
| `DOWN` | Next menu item |
| `RIGHT`, `Num Enter` | Select menu item |
| `LEFT` | Close a sub menu |
| `Num 1` | First menu option |
| `Num 2` | Second menu option |
| `Num 3` | Third menu option |
| `Num 4` | Forth menu option *(sic — "Fourth" mis-spelled in-game)* |
| `Num 5` | Fifth menu option |
| `Num 6` | Sixth menu option |
| `Num 7` | Seventh menu option |
| `Num 8` | Eighth menu option |
| `Num 9` | Ninth menu option |
| `TAB` | Tab through focus |

### Controls → Ship (screenshots 5 and 6)

| Key | Action |
|---|---|
| `w` | Turn your ship up |
| `a` | Turn your ship left |
| `s` | Turn your ship down |
| `d` | Turn your ship right |
| `q` | Roll your ship left |
| `e` | Roll your ship right |
| `f`, **L Button** | Fire phasers |
| `x`, **R Button** | Fire torpedoes |
| `g`, **M Button** | Fire disruptors |
| `r` | Set impulse: reverse |
| `0` | Set impulse: all stop |
| `1` | Set impulse: 1 |
| `2` | Set impulse: 2 |
| `3` | Set impulse: 3 |
| `4` | Set impulse: 4 |
| `5` | Set impulse: 5 |
| `6` | Set impulse: 6 |
| `7` | Set impulse: 7 |
| `8` | Set impulse: 8 |
| `9` | Set impulse: 9 |
| `Scroll Up` | Inc speed |
| `Scroll Down` | Dec speed |
| `CTRL-D` | Self destruct |

### Controls → Camera (screenshot 1)

| Key | Action |
|---|---|
| `c` | Next camera mode |
| `v` | Reverse chase mode |
| `SHIFT` | Camera rotation |
| `z` | Zoom in on the target |
| `Num +`, `=` | Zoom in |
| `Num -`, `-` | Zoom out |

### Rebinding procedure

1. Click the row for the command to rebind.
2. A modal *Select a new key* prompt appears (manual reference — not directly visible in supplied screenshots).
3. Press the new key, or click the new mouse button. The new bind takes effect immediately.
4. Click *Cancel* on the modal to abort.

Per-row controls — there is no separate "default-this-row" button visible. To revert all bindings at once, use the screen-level **Default** button.

---

## Visual asides on the LCARS chrome

### Sound-category waveform

When the *Sound* category is active, the lavender LCARS side panel changes — a stylised **red sine-wave** is rendered inside one of its lower cells (visible in screenshots 9 and 10). The wave shifts shape between screenshots — likely animated or pegged to the *Voice* / *Music* test ping. Above and below it are short bar-graph "ticker" elements in red/orange.

### Graphics-category waveform

Screenshot 8 (Graphics) shows the **same waveform asset** in the side panel as Sound — they appear to share the inset. (The asset may be a generic "tech panel" decoration rather than purpose-bound to either category.)

### General-category galaxy map

When *General* is active (screenshot 7), the LCARS side-panel inset becomes a small **galaxy map** labelled with the four-quadrant Trek geography (*GAMMA QUADRANT*, *ALPHA QUADRANT*, *DELTA QUADRANT*, *BETA QUADRANT*) and a *GALACTIC CORE* marker. Purely decorative.

### Controls-category — no inset

When *Controls* is active (screenshots 1–6) the left panel inset is **blank** (just lavender panels, no galaxy / waveform).

These three insets — galaxy, waveform, blank — are the only category-driven changes to the LCARS chrome.

---

## Interactions summary

| Input | Effect |
|---|---|
| `LMB` on a category button | Switch detail pane to that category |
| `LMB` on a sub-category button (Controls) | Switch sub-pane |
| `LMB` on a toggle row | Flip on / off |
| `LMB` on a cycle row | Advance to next value |
| `LMB` on an expandable row | Expand / collapse children |
| `LMB` on a slider track | Jump value; drag to scrub |
| `LMB` on a binding row | Open rebind modal |
| `LMB` on `▲` / `▼` | Scroll detail pane |
| `LMB` on **Cancel** | Revert and exit Configure |
| `LMB` on **Default** | Reset all bindings / values to factory defaults |
| `ESC` | Open Main LCARS overlay (does not implicitly save / cancel — *behaviour with unsaved bindings is undocumented in the manual; the in-game default is to apply changes immediately*) |

> All key bindings referenced anywhere in this document are the **defaults** as shown in the screenshots. They are remappable through this screen.

---

## Differences from the manual reference

A few things the in-game screen shows that [launch-and-main-menu.md](launch-and-main-menu.md) doesn't fully capture:

- The **Misc. binding for Map Mode** is `m`, not `M` (case-insensitive in practice).
- **Talk to** rows are bound to `F1`–`F6`; these are the same keys that open officer menus in-game — Configure labels them as *Talk to helm / tactical / first officer / science / engineering / guest* rather than "Open menu".
- **`SCRL LOCK`** is labelled simply *On screen* in the binding list — its actual effect (lock viewscreen to current target) lives in [bridge-mode.md § Camera and look controls](bridge-mode.md#camera-and-look-controls).
- **EAX Hardware** appears in the Sound Quality submenu even when the hardware doesn't support it — it renders **greyed**, not hidden.
- **Enhanced Glows** is visible-but-off in screenshot 8 — likely because the host card lacks the feature; the option remains in the list rather than being removed.
- **"Forth menu option"** is mis-spelled in the in-game string (screenshot 2). Preserved as-shown above.
