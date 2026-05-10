# Tactical Mode

The external-view combat HUD. Pressing `Space` from the bridge switches
the camera outside the ship and overlays a heads-up display, while WASD
/ Q / E / `F` / `X` give the player direct flight + weapon control.

> Issuing **any** order to Felix while in Tactical Mode (or returning
> to Bridge) hands the conn back to him; the player loses direct
> control until they press a flight key again.

---

## Camera

Default camera is a third-person chase camera trailing the player ship.

| Key | Camera action |
|---|---|
| `C` | Toggle between Chase and Tracking modes. |
| `V` | Set the camera to **Reverse Chase** (look back at own ship). |
| `Shift` (held) | From Chase Mode, allows free mouse rotation of the camera. |
| `Z` (held) | Zoom in on the current target while held. |
| `=` / `+` | Zoom in (sticky). |
| `-` | Zoom out (sticky). |
| `F9` | Toggle Cinematic Mode. |

### Cinematic Mode

`F9` toggles a cinematic camera overlay. While cinematic mode is
active, `F1`–`F6` pick the cinematic camera variant:

| Key | Cinematic camera |
|---|---|
| `F1` | Fly-by camera |
| `F2` | Free Camera (mouse rotates) |
| `F3` | Target Camera (cycles through targets) |
| `F4` | Torpedo Camera |
| `F5` | Panoramic View — **requires a target selected** |
| `F6` | Long Range Free Camera |

> While cinematic mode is on, the F-keys do *not* open the crew menus.
> Toggle cinematic off (`F9`) to use the F-keys for crew again.

---

## Direct ship control

| Input | Effect |
|---|---|
| `W` | Pitch nose up |
| `S` | Pitch nose down |
| `A` | Yaw left |
| `D` | Yaw right |
| `Q` | Roll left (counter-clockwise) |
| `E` | Roll right (clockwise) |
| `0` | All Stop |
| `1`–`9` | Set impulse speed 1 through 9 |
| Mouse wheel up | Increase speed |
| Mouse wheel down | Decrease speed |
| `R` | Reverse |
| `F` *or* `LMB` (off-menu) | Fire phasers |
| `X` *or* `RMB` (off-menu) | Fire torpedoes |
| `G` *or* `MMB` (off-menu) | Fire disruptors (faction ships only) |
| `Ctrl + I` | Intercept current target (auto-warp if > 50 km) |
| `Alt + T` | Toggle tractor beam on/off |
| `Alt + C` | Toggle cloaking device on/off |
| `Ctrl + D` | Self destruct |

Important rule the manual emphasises: when using `LMB` / `RMB` to fire,
**make sure the cursor is not over a HUD menu** — clicks on a menu
panel always go to the menu first.

---

## Targeting

| Key | Effect |
|---|---|
| `T` | Cycle to next target (any contact) |
| `Y` | Cycle to previous target |
| `U` | Target nearest contact |
| `I` | Cycle to next *enemy* target |
| `J` | Target the attacker of the currently selected target |
| `N` | Cycle to next nav point |
| `P` | Cycle to next planet |
| `H` | Toggle Manual Fire mode on/off |
| `Ctrl + T` | Clear the current target |

Selecting a target is also possible by clicking the row in the **Target
List** panel (see below) or by clicking on the ship in 3D space.

---

## HUD layout

The Tactical-Mode HUD is built from independent corner panels. Each
panel has a small **arrow in its top-right corner**; clicking it
**minimises** the panel (collapses it to its title bar). Click again
to expand.

```
 ┌──────────────────────────────────────────────────────────────────┐
 │ [Target Shields]                                                 │
 │  upper-left                                                      │
 │                                                                  │
 │                                                                  │
 │                                                                  │
 │                                                                  │
 │                                                                  │
 │                                                  [Speed]         │
 │                                                  [Shields]       │
 │                                                  [Weapons]       │
 │  [Sensors]                                       [Phaser Arc /   │
 │  lower-left                                       Torpedo /      │
 │                                                   Speed]         │
 │                                                  lower-right     │
 └──────────────────────────────────────────────────────────────────┘
```

The same panels appear in Bridge Mode, anchored to the same screen
corners. Manual phrasing:

> "In the lower right hand corner of the screen, you will notice
> several displays. These displays indicate the speed of your ship,
> the type of torpedoes you are using, your phaser intensity setting,
> the strength of your shields and the readiness of your weapons."
> — manual, p. 24.

---

## Sensors panel (lower-left)

A round 2D sensor display centred on an icon of the player ship.

- **Coloured arrow icons** — every contact in range. Colour indicates
  affiliation (enemy vs ally). Direction of the arrow indicates the
  contact's **facing/direction of motion**.
- **Bracket** — the currently selected target is highlighted with a
  bracket.
- **Hostile-fire indicator** — ships that are firing on the player are
  also bracketed.
- **Torpedo icons** — incoming torpedoes are drawn distinctly, and
  differentiated by torpedo *type* (so the player can identify threats
  even when no eyeball detection is possible).
- **Range falloff** — the display is non-linear. Distant objects
  remain near the edge of the disk rather than disappearing entirely;
  this means two contacts that look equidistant on the disk may
  actually be at very different actual ranges.
- **Vertical fade** — contacts above or below the player's flight
  plane fade as they leave it.

Click the upper-right arrow to **minimise**.

---

## Target List panel (right side)

When a target is selected (or a contact is in range), the Target List
shows it as a row.

```
┌── Targets ──────────────────────┐
│  Klingon Bird of Prey           │ ← single click selects as target
│  Keldon                         │ ← second click expands subsystems
│   ├ Shield Generator            │
│   ├ Warp Core                   │
│   ├ Compressors                 │
│   ├ Torpedoes              ▶    │ ← arrow = expandable component list
│   │   ├ Forward Torpedo         │
│   │   └ Aft Torpedo             │
│   ├ Impulse Engines             │
│   ├ Warp Engine                 │
│   ├ Sensor Array                │
│   └ Tractors                    │
└─────────────────────────────────┘
```

Behavioural rules (shared with Felix's menu, see [`bridge-mode.md` § Target List](bridge-mode.md#target-list-and-subsystem-drill-down)):

- One click = select that contact as the player's target.
- Second click on the same row = expand its subsystems list.
- Subsystems with a **▶** arrow expand to a component list on click.
- **Disabled** subsystems show in **grey**.
- **Destroyed** subsystems are **removed** from the list.

Keyboard navigation:

- `Tab` cycles focus between HUD panels until Target List is focused.
- `↑` / `↓` walk the rows.
- `→` or `Enter` selects / expands.

---

## Shields panel (lower edge)

Diagram of the player ship in plan view, showing six shield faces:

| Face | Position |
|---|---|
| Bow / Forward | front |
| Aft / Rear | back |
| Port | left |
| Starboard | right |
| Dorsal / Top | above |
| Ventral / Bottom | below |

Each face is colour-coded by current strength:

| Colour | Meaning |
|---|---|
| **Bright green** | Full strength |
| **Yellow** | Partly depleted |
| **Red** | Heavily depleted |
| **Black** | No shielding remaining on that face |

When a shield face is at 0%, weapons energy begins **bleeding through
to the hull** on that face.

> Tactical tip the manual gives explicitly: rotate the ship constantly
> in combat to prevent any one face from being depleted.

---

## Target Shields panel (upper-left)

Mirror of the Shields panel, but for the *currently selected target*.
Same six-face layout, same colour code. **Damage Icons** for the
target's degraded subsystems are drawn on this panel as well, so the
player can see which of their own shots are landing on which subsystem
of the enemy.

> The same icon legend used here is shared with the Engineering damage
> panel — see [`bridge-mode.md` § Damage indicators](bridge-mode.md#damage-indicators-shared-with-tactical-mode).

---

## Weapons panel

Shows the ship's currently configurable weapons settings (mirrors the
Weapons sub-panel of Felix's menu — same controls, just exposed in the
HUD). All controls are click-cycled:

| Control | Values |
|---|---|
| Torpedo type | Photon (default) / additional types as loaded |
| Torpedo spread | Single, or multi-fire counts |
| Phasers | (heading) |
| Phaser intensity | Full / Low |
| Tractor | On / Off |
| Cloak (if equipped, MP/QB only) | On / Off |

Above the weapons fields is the unused-torpedo count.

---

## Phaser Arc / Torpedo Display (lower-right)

A combined readout of speed, phaser readiness, and torpedo readiness.
At Red Alert this panel becomes informative; at Green Alert it shows
ship speed only.

### Components

```
┌── Speed: 0.4322 lyph ──┐
│                         │
│  ┌───────────────┐      │
│  │  ◔ ◔ ◔ ◔ ◔   │      │  ← phaser strips wrap the ship image
│  │   ◯  ship  ◯  │      │     (two layers: dorsal + ventral)
│  │  ◔ ◔ ◔ ◔ ◔   │      │
│  └───────────────┘      │
│                         │
│  ●●  fore tubes         │  ← torpedo readiness dots
│  ●●  aft tubes          │
└─────────────────────────┘
```

### Phaser strips

Strips around the ship icon represent each phaser array.

- Two layers: the **dorsal** strips and the **ventral** strips.
- Per-strip colour:
  | Colour | Meaning |
  |---|---|
  | **Green** | Fully charged & ready to fire |
  | **Yellow** | Charging |
  | **Red** | Heavily depleted |
  | **Black** | Drained |
  | **Grey** | Disabled |
  | (no strip) | Destroyed — the strip disappears |
- A **transparent blue/grey indicator** emanates from the ship image
  toward the strip(s) that *can fire on the current target* (within
  arc). A target may be in more than one arc at once. **No indicator
  means the target is in a blind spot** — no phaser can fire.

> Combat tip the manual emphasises: rotate the ship to keep moving
> the target between arcs, so no single array gets fully drained, and
> to keep enemies *out* of blind spots.

Phaser recharge speed scales with the **Weapons** power slider in
Engineering's Power Allocation Sliders.

### Torpedo readiness dots

Small circular dots near the bow and stern of the ship icon, one per
torpedo tube.

| Dot colour | Meaning |
|---|---|
| **Green** | Loaded, ready to fire |
| **Red** | Currently loading, or out of torpedoes |
| **Grey** | Tube disabled |
| (no dot) | Tube destroyed |

---

## Damage Icons

Icons drawn on the player ship image (Engineering panel) and on the
target's image (Target Shields panel) to indicate per-system damage.

Glyphs and meaning are shared with Bridge Mode; see [`bridge-mode.md` § Damage indicators](bridge-mode.md#damage-indicators-shared-with-tactical-mode).

Colour code (same as elsewhere):

- **Yellow** → damaged.
- **Grey** → disabled.
- **Red** → destroyed.

---

## Manual Fire mode

Toggled on either via Felix's *Manual Fire* button or the `H` key.

When active:

- The cursor changes to a **targeting reticle**.
- Felix may continue manoeuvring the ship if he was given those orders.
- `LMB` (or `F`) fires phasers.
- `RMB` (or `X`) fires torpedoes.
- `MMB` (or `G`) fires disruptors (faction ships only).
- The reticle position selects which **subsystem / hull region** the
  shot is aimed at; place it on a specific component of the target to
  attack that component.

When toggled off, the cursor returns to standard form and Felix
resumes weapons control.

---

## Map Mode

`M` toggles Map Mode in either Bridge or Tactical view. The manual
documents Map Mode's *toggle*, but does not describe its visual layout
in detail; behavioural notes:

- It's an alternate orientation/overview view; the player remains in
  whatever mission state they were in.
- `M` again returns to the prior view.

---

## Multiplayer-only HUD overlays

In a multiplayer session, three additional overlays exist:

| Key | Overlay |
|---|---|
| `[` | Toggle Score Window |
| `]` | Toggle Chat Window |
| `\` | Initiate **Team Chat** message entry (team-only delivery) |

These are independent of mode; they layer on top of either Bridge or
Tactical without changing the underlying view.

---

## Combat behavioural rules (manual's "Combat" section)

Captured here because they shape how the HUD is read.

### Distance

- Phasers do **reduced damage at greater distances** (range falloff
  varies per ship class; stations have the longest effective range).
- Torpedoes track **better from a distance**, so they're harder to
  evade if the firer maintains range — but they're easier to evade by
  the *receiver* if they remain outside the torpedo's tracking range.
- When taking torpedo fire: **increase speed** and turn perpendicular
  to torpedo trajectory; if you can't avoid all of them, eat the hit
  on a stronger shield face.

### Offence

- Take down individual **subsystems** (Target List drill-down) rather
  than blindly trading hits with the hull:
  - Disabling weapons stops their offence.
  - Disabling/damaging an engine handicaps their manoeuvring.
  - Disabling sensors prevents them from targeting you.
  - Disabling cloak strips their concealment.
- Or wear down a **single shield face** before attacking subsystems —
  don't spread fire around the hull.

### Defence

- Prioritise repairs (Brex's panel) — sometimes shields > weapons,
  sometimes phasers > torpedoes, depending on the moment.
- Move the slider in **Engineering** to bias power: weapons + shields
  up, sensors down, in tough fights; engines up vs. faster opponents.
- Keep rotating the ship — don't let a single shield face be hammered
  to depletion.
- Increase distance vs. phaser pressure (range falloff helps you).
