# Keyboard and Mouse Reference

The complete default-binding table, grouped exactly as the in-game
**Configure Controls** screen groups them. All bindings are remappable
via *Main LCARS Menu → Configure → Configure Controls*.

> Source: manual, "Keyboard Commands" (pp. 34–36) and "Keyboard Command
> Chart" (p. 94).

---

## Mouse summary

### On the bridge

- **Look** — moving the mouse left/right rotates the captain's view.
- **`LMB` on a crew member** — opens that officer's menu (the view must
  be centred on them, with their tool-tip status window visible).
- **`LMB` on a menu item** — activates it.
- **`LMB` off the menu (with a menu open)** — deselects / closes the
  menu.
- **`LMB` on a different crew member (with a menu open)** — closes the
  current menu and opens the new officer's menu.

### In Tactical Mode

- **`LMB` (off any HUD menu)** — fires phasers.
- **`RMB` (off any HUD menu)** — fires torpedoes.
- **`MMB` (off any HUD menu)** — fires disruptors (faction ships only).
- **`LMB` on a HUD menu / panel** — interacts with that menu/panel
  (clicks always go to the menu first).
- **`LMB` in Cinematic *Free Camera* mode (`F2`)** — rotates the
  camera (see [`tactical-mode.md` § Camera](tactical-mode.md#camera)).

### In any UI screen

- **`LMB`** — primary "select / activate".
- **Drag** — used on Configure sliders (Sound) and Power Allocation
  Sliders (Engineering).
- **Mouse wheel up** — Increase Speed (in Tactical).
- **Mouse wheel down** — Decrease Speed (in Tactical).

### Reserved binds

The following bindings are **shipping defaults**; the player can rebind
them all in *Configure Controls*.

---

## Miscellaneous Commands

| Default | Command |
|---|---|
| `ESC` | Toggle the LCARS Menu System (options menu) |
| `Backspace` | Skip dialog |
| `Space` | Toggle between Bridge Mode and Tactical Mode |
| `M` | Toggle Map Mode |
| `[` | Toggle the Score Window (Multiplayer only) |
| `]` | Toggle the Chat Window (Multiplayer only) |
| `\` | Team Chat (Multiplayer only) |
| `F1` | Talk to LoMar (Helm); deselect Helm Menu |
| `F2` | Talk to Felix (Tactical); deselect Tactical Menu |
| `F3` | Talk to Saffi (First Officer); deselect Commander Menu |
| `F4` | Talk to Miguel (Science); deselect Science Menu |
| `F5` | Talk to Brex (Engineering); deselect Engineering Menu |
| `F6` | Talk to any guest on the bridge / close any open menu |
| `Shift + 1` | Go to Green Alert |
| `Shift + 2` | Go to Yellow Alert |
| `Shift + 3` | Go to Red Alert |
| `Print Screen` | Take Screenshot |

---

## Menu Commands

| Default | Command |
|---|---|
| `↑` | Scroll up on the active (highlighted) menu |
| `↓` | Scroll down on the active (highlighted) menu |
| `←` | Back out of a sub-menu |
| `→` | Open a sub-menu |
| `Enter` | Select the current option in a menu (open a menu / select a button) |
| `Num 1`–`Num 9` | Select the 1st through 9th options in a menu |
| `Tab` | Cycle through the focus blocks (cycle through and highlight tactical interface panels) |

---

## Ship Commands

| Default | Command |
|---|---|
| `W` | Turn your ship up (pitch nose up) |
| `A` | Turn your ship left (yaw) |
| `S` | Turn your ship down (pitch nose down) |
| `D` | Turn your ship right (yaw) |
| `Q` | Roll your ship left (counter-clockwise) |
| `E` | Roll your ship right (clockwise) |
| `F` *or* `LMB` | Fire phasers |
| `X` *or* `RMB` | Fire torpedoes |
| `G` *or* `MMB` | Fire disruptors |
| `0` | All Stop |
| `1`–`9` | Set Impulse Speed: 1–9 |
| Mouse wheel up | Increase Speed |
| Mouse wheel down | Decrease Speed |
| `R` | Reverse |
| `Ctrl + I` | Intercept |
| `Alt + T` | Toggle Tractor Beam On/Off |
| `Alt + C` | Toggle Cloaking Device On/Off |
| `Ctrl + D` | Self Destruct |

---

## Targeting Commands

| Default | Command |
|---|---|
| `T` | Next target |
| `Y` | Previous target |
| `U` | Nearest target |
| `I` | Target the next enemy |
| `J` | Target the attacker of the selected target |
| `N` | Target the next Nav Point |
| `P` | Target the next planet |
| `H` | Toggle Manual Firing on/off |
| `Ctrl + T` | Clear Target |

---

## Camera Commands — Tactical Mode

| Default | Command |
|---|---|
| `C` | Toggle Chase / Tracking Modes |
| `V` | Set the camera to Reverse Chase Mode |
| `Shift` (held) | Allow camera rotation with the mouse (from Chase Mode only) |
| `Z` (held) | Zoom in on the target while held |
| `=` / `+` | Zoom in (sticky) |
| `-` | Zoom out (sticky) |
| `F9` | Toggle Cinematic Mode |

---

## Camera Commands — Bridge Mode

These control the bridge **viewscreen** (the front display the bridge
crew faces).

| Default | Command |
|---|---|
| `Scroll Lock` | Show your target on the viewscreen |
| `Home` | Set viewscreen to look forward |
| `Del` | Set viewscreen to look left |
| `PgDn` | Set viewscreen to look right |
| `End` | Set viewscreen to look back |
| `PgUp` | Set viewscreen to look up |
| `Ins` | Set viewscreen to look down |
| `=` / `+` | Zoom in |
| `-` | Zoom out |
| `F9` | Toggle Cinematic Mode |

---

## Cinematic Modes

These keys are only meaningful **after** Cinematic Mode has been
toggled on with `F9`.

| Default | Command |
|---|---|
| `F1` | Fly-by Camera |
| `F2` | Free Camera (use mouse to rotate) |
| `F3` | Target Camera (cycles between targets) |
| `F4` | Torpedo Camera |
| `F5` | Panoramic View (must have a target selected) |
| `F6` | Long Range Free Camera |
| `F9` | Toggle Cinematic Mode (back off) |

> While cinematic mode is active, the F1–F6 keys are **redirected** to
> these camera variants instead of opening crew menus. Toggle cinematic
> off with `F9` to restore F1–F6's crew-menu behaviour.

---

## Layered modal binds

Some of the bindings above behave differently in different contexts.

### `LMB` / `RMB` / `MMB`

| Mode | Cursor over a HUD menu? | Effect |
|---|---|---|
| Bridge | n/a | Click selects/activates menu items or crew. |
| Tactical | yes | Click activates the menu item. |
| Tactical | no | Fires phasers / torpedoes / disruptors respectively. |

### `F1`–`F6`

| Mode | Cinematic Mode? | Effect |
|---|---|---|
| Bridge | off | Toggle the corresponding crew menu (`F6` = guest / close any). |
| Tactical | off | Same — open / close crew menus. |
| Either | **on** | Pick a cinematic camera variant. |

### `Shift`

| Context | Effect |
|---|---|
| Held while in Tactical *Chase Mode* | Allows mouse-driven camera rotation. |
| Combined with `1` / `2` / `3` (any mode) | Switches to Green / Yellow / Red Alert. |
| Held in any UI text field | Standard OS behaviour (capitals). |

### `=` / `+` / `-`

| Mode | Effect |
|---|---|
| Bridge | Zoom the viewscreen. |
| Tactical | Zoom the camera. |

### `M`

Works in **both** Bridge and Tactical to toggle Map Mode — the manual
explicitly lists `M` under "General" rather than per-mode.

---

## Self-test: chord-style binds

A handful of in-game binds are chords (modifier + key). These are listed
verbatim where they appear in the manual (none of these may be split or
re-mapped to single keys without using Configure Controls):

- `Ctrl + I` — Intercept.
- `Ctrl + T` — Clear Target.
- `Ctrl + D` — Self Destruct.
- `Alt + T` — Toggle Tractor.
- `Alt + C` — Toggle Cloak.
- `Shift + 1` / `Shift + 2` / `Shift + 3` — Green / Yellow / Red Alert.

---

## What the Configure Controls screen presents

The Configure Controls screen exposes the **same binding table as
above**, broken into the same four expandable command groups
(*Miscellaneous*, *Menu*, *Ship*, *Camera*). The procedure for
re-binding any row is in
[`launch-and-main-menu.md` § Configure Controls](launch-and-main-menu.md#configure-controls).
