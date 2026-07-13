# Bridge Mode

The first-person, in-bridge view. The player is the captain seated on
the bridge, looking around the room and giving orders to officers at
their stations. This is the **default** view during single-player
missions, multiplayer games (with bridges), and Quick Battles.

> Switch to the external view at any time with `Space`. See
> [`tactical-mode.md`](tactical-mode.md) for that side.

---

## Camera and look controls

The bridge camera is fixed at the captain's chair. The player rotates
their **head** with the mouse to look around the room and centre on a
crew member.

- **Mouse left / right** — pans the view horizontally.
- **Crew tool tips** appear above any officer the view is centred on
  (rank, name, station, current order/status). The Configure General
  Options toggle **Character Tool Tips** controls whether these are
  shown.

There's a separate **viewscreen** at the front of the bridge — the
big screen the bridge crew faces. Its picture can be redirected
without leaving Bridge Mode:

| Key | Viewscreen pose |
|---|---|
| `Home` | Look forward |
| `Del` | Look to port (left) |
| `PgDn` | Look to starboard (right) |
| `End` | Look aft (back) |
| `PgUp` | Look up (dorsal) |
| `Ins` | Look down (ventral) |
| `ScrLk` | Lock viewscreen onto current target |
| `=` / `+` | Zoom viewscreen in |
| `-` | Zoom viewscreen out |
| `F9` | Toggle Cinematic Mode (overrides viewscreen) |

These keys do nothing in Tactical Mode (the viewscreen isn't visible).

---

## Selecting a crew member

The bridge has **five named officer stations** plus a **guest slot**:

| Station | Officer (single-player default) | Function key |
|---|---|---|
| Helm / Conn | Ensign Kiska LoMar | `F1` |
| Tactical | Lt. Felix Savali | `F2` |
| First Officer / XO | Cmdr. Saffi Larsen | `F3` |
| Science | Lt. Cmdr. Miguel Diaz | `F4` |
| Engineering | Lt. Cmdr. Brex *(may be at Engineering panel)* | `F5` |
| Guest | situational | `F6` |

Two ways to open an officer's menu:

- **Mouse**: pan until the view is centred on that officer (status
  window appears), then `LMB`-click them.
- **Keyboard**: press the function key for that station. The same key
  also closes the menu (keys are toggles).

Once a menu is open:

| Input | Behaviour |
|---|---|
| `↑` / `↓` | Move highlight up/down menu options. |
| `Enter` | Activate the highlighted option. |
| `←` | Back out of a submenu (or close the menu if at root). |
| `→` | Open a submenu under the highlighted option. |
| `Num 1`–`Num 9` | Direct-select the 1st through 9th option in the open menu. |
| `LMB` (off-menu) | Closes the menu (acts like deselect). |
| `LMB` (other officer) | Closes this menu and opens that officer's. |
| `F6` | Closes any open menu. |

---

## First Officer (Saffi) menu — `F3`

Saffi is the player's right hand. She owns ship-wide alert state and
mission-info commands.

```
┌───────────────────────────────┐
│ First Officer (Cmdr. Larsen)  │
├───────────────────────────────┤
│  Report                       │  ── ask for advice / opinion
│  Damage Report                │  ── solicits status from bridge crew
│  Green Alert                  │  ── Condition Green
│  Yellow Alert                 │  ── Condition Yellow
│  Red Alert                    │  ── Condition Red (combat-ready)
│  Objectives                   │  ── lists current mission objectives
│  Show Mission Log             │  ── transcript of pertinent dialogue
│  Contact Starfleet            │  ── opens channel to Adm. Liu @ SB12
│  Contact Engineering          │  ── speak with Brex when he's in Eng.
└───────────────────────────────┘
```

### Alert states

The three Alert buttons are mutually exclusive (selecting one cancels
the others):

| Alert | Shields | Weapons | Battery |
|---|---|---|---|
| **Green** | Down (powered off) | Down (powered off) | Recharges; non-aggressive posture |
| **Yellow** | **Up** (raised) | Down | No drain unless other systems are powered |
| **Red** | Up | **Up** | Drains continuously while idle (full combat-ready posture) |

> "At Red Alert you will begin draining battery power" — manual, p. 11.

### Quick Battle additions

In Quick Battle (screen 6 / 7 in [`screen-map.md`](screen-map.md)),
Saffi gains three additional entries:

- *Quick Battle Setup* — opens the modal Quick Battle Setup overlay.
- *Start Combat Simulation* — begins fighting.
- *End Combat Simulation* — terminates the simulated battle.

(See [`quick-battle-and-multiplayer.md`](quick-battle-and-multiplayer.md).)

---

## Helm (LoMar) menu — `F1`

LoMar is responsible for piloting and communications.

```
┌───────────────────────────────┐
│ Helm (Ens. LoMar)             │
├───────────────────────────────┤
│  Report                       │
│  Hail                         │  ── opens list of nearby contacts
│   ├─ <ship/colony/base>       │     • selecting opens a channel
│   └─ (when given a friendly:  │
│       these extra entries     │     • only when LoMar already
│       appear)                 │       commands a friendly ship
│       ├─ Resume Old Orders    │
│       ├─ Attack Target        │
│       ├─ Disable Target       │
│       ├─ Defend Target        │
│       ├─ Protect Me           │
│       └─ Dock With Starbase   │
│  Set Course                   │  ── solar-system list
│   └─ (current system) ──► regions inside it
│  Warp                         │  ── engage warp to course
│  Orbit Planet                 │  ── lists planets/moons in region
│   └─ <planet name>            │
│  Nav Points                   │  ── plotted nav coordinates
│   └─ <nav point name>         │
│  Intercept                    │  ── only when a target is selected
│  All Stop                     │
│  Dock                         │  ── only when near Starbase 12
└───────────────────────────────┘
```

### Important navigation rules

- **Set Course** lists *solar systems*. The current system appears at
  the top; clicking it opens a sub-list of regions inside that system.
- **Starfleet regulation: cannot warp directly to an inner planet.**
  Once the ship arrives at the outer edge of a destination system, it
  may continue inside at a *reduced* warp factor.
- **Intercept** auto-triggers an in-system warp if the target is more
  than 50 km away.
- **Dock** is conditional on Starbase 12 proximity. Successful dock
  resupplies torpedoes and repairs damaged systems (the *only* way to
  repair systems on the *Destroyed* list — see Engineering, below).

### Friendly-ship commands

When the mission gives the player a friendly vessel under their
command, LoMar's *Hail* menu gains an additional submenu of orders for
that ship: *Resume Old Orders*, *Attack Target*, *Disable Target*,
*Defend Target*, *Protect Me*, *Dock With Starbase*.

---

## Tactical (Felix) menu — `F2`

Felix runs combat. His menu is more elaborate than the others; it is
also the menu that mirrors the in-Tactical-Mode HUD.

```
┌───────────────────────────────┬──────────────────────────────┐
│ Tactical (Lt. Savali)         │ Orders                        │
├───────────────────────────────┼──────────────────────────────┤
│  Report                       │  Destroy                      │
│  Manual Fire (toggle)         │  Disable                      │
│  Phasers Only (toggle)        │  Stop                         │
│  Target At Will (toggle)      │  Evade (toggle)               │
├───────────────────────────────┼──────────────────────────────┤
│ Manoeuvres                    │ Tactics                       │
├───────────────────────────────┼──────────────────────────────┤
│  At Will                      │  At Will                      │
│  Close Distance               │  Left Phaser Attack           │
│  Maintain Distance            │  Right Phaser Attack          │
│  Separate Distance            │  Fore Attack                  │
│                               │  Aft Attack                   │
│                               │  Top Shields                  │
│                               │  Bottom Shields               │
├───────────────────────────────┴──────────────────────────────┤
│ Targets                                                       │
│   <list of all sensor contacts>                               │
│      └─ click again to expand subsystems                      │
│              └─ some subsystems expand into components        │
├───────────────────────────────────────────────────────────────┤
│ Weapons                                                       │
│   Torpedoes (unused count)                                    │
│     Type:    Photon | <other types as loaded>                 │
│     Spread:  Single | <multi-fire counts>                     │
│   Phasers                                                     │
│     Intensity: Full | Low                                     │
│   Tractor: On | Off                                           │
│   Cloak: On | Off   (only if ship has cloak — MP/QB only)     │
└───────────────────────────────────────────────────────────────┘
```

### Behavioural notes

- **Manual Fire (toggle)** — when on, the cursor becomes a targeting
  reticle; the player fires phasers/torpedoes directly. Felix retains
  ship manoeuvres unless overridden. Move the reticle over a hull
  region to attack a specific component. Toggling off restores cursor
  + Felix-controlled fire.
- **Phasers Only (toggle)** — when on, Felix never launches torpedoes.
- **Target At Will (toggle)** — when on, Felix picks his own targets
  and switches as targets are destroyed.
- **Orders → Destroy / Disable / Stop / Evade** — Felix's behaviour
  toward the *currently targeted* contact (or its targeted subsystem).
- **Manoeuvres** — distance posture relative to target.
- **Tactics** — which weapons / which shield faces. *Top Shields* and
  *Bottom Shields* rotate the ship to keep the dorsal/ventral shield
  aligned with the target.
- **Tactical Mode interaction** — issuing any of these orders while in
  Tactical Mode (or upon returning to Bridge from Tactical) hands the
  conn back to Felix; the player loses direct ship control. To take
  over again, press a flight key (WASD / Q / E).

### Weapons sub-controls

Cycle by clicking; values rotate among:

- **Torpedo Type** — Photon by default; additional types unlock as the
  campaign loads them. Each type is its own loadout.
- **Torpedo Spread** — single shot, or multi-shot counts.
- **Phaser Intensity** — Full or Low.
  - *Full* — max damage / fastest drain.
  - *Low* — less DPS but lower energy use; **does not damage hull
    if no specific subsystem/component is targeted**, so it's safer
    when disabling a ship you don't want to destroy. Does damage
    hull if no subsystem is targeted. **More effective for damaging
    subsystems once shields are down or weakened.**
- **Tractor** — toggle. Tractor only locks if a target is in range and
  fore/aft of the player ship; while held the target's manoeuvring is
  impeded. Draws from the **Main Battery**.
- **Cloak** (multiplayer / Quick Battle only — only present if the ship
  hull has one) — drops shields and weapons offline; you become invisible
  on enemy Target Lists and immune to phaser fire. Draws from the
  **Reserve Battery**.

### Target List and subsystem drill-down

Targets are listed as one row each. The drill is **click-to-expand**:

```
Keldon                         ← single click selects as target
  Shield Generator             ← second click expands subsystems
  Warp Core
  Compressors
  Torpedoes              ▶     ← arrow = component sublist
    Forward Torpedo
    Aft Torpedo
  Impulse Engines
  Warp Engine
  Sensor Array
  Tractors
```

- A **rightward arrow ▶** to the left of a subsystem name indicates a
  further component sublist; click that subsystem to expand.
- **Disabled** subsystems are greyed in the list.
- **Destroyed** subsystems are **removed** from the list.

Keyboard navigation:

- `Tab` cycles "focus blocks" between the menu and the panels until the
  Target List has focus.
- `↑` / `↓` walk the list.
- `→` or `Enter` selects / opens a row's children.

---

## Science (Miguel) menu — `F4`

Miguel runs sensors and probes.

```
┌───────────────────────────────┐
│ Science (Lt. Cmdr. Diaz)      │
├───────────────────────────────┤
│  Report                       │
│  Scan Area                    │  ── general scan of vicinity
│  Scan Target                  │  ── scans the currently targeted
│  Scan Object                  │     contact
│   └─ <list of nearby objects> │
│  Launch Probe                 │  ── single-player only;
│                               │     extends sensor range; ignores
│                               │     loss of own Sensor Array
└───────────────────────────────┘
```

> **Probes are not launchable in multiplayer.**

A launched probe gives the player full sensor information from its own
position, even if the player ship's Sensor Array has been disabled or
destroyed.

---

## Engineering (Brex) menu — `F5`

Brex prioritises repair teams and balances power.

```
┌──────────────────────────────────────────────────────────┐
│ Engineering (Lt. Cmdr. Brex)                              │
├──────────────────────────────────────────────────────────┤
│  Report                                                   │
│                                                           │
│ ┌── Repair Team Assignments ─────────────┐                │
│ │  <up to 3 systems being repaired now>  │                │
│ │  click any to demote it in priority    │                │
│ └────────────────────────────────────────┘                │
│                                                           │
│ ┌── Damaged Systems ─────────────────────┐                │
│ │  <queued damaged systems>              │                │
│ │  click any to promote it to top of     │                │
│ │  the repair queue immediately          │                │
│ └────────────────────────────────────────┘                │
│                                                           │
│ ┌── Destroyed Systems ───────────────────┐                │
│ │  <list of unrepairable systems>        │                │
│ │  read-only; only Starbase 12 can       │                │
│ │  rebuild these                         │                │
│ └────────────────────────────────────────┘                │
│                                                           │
│ ┌── Power Transmission Grid ─────────────────────┐        │
│ │  Power Used:                                   │        │
│ │  [██████████░░░░░░░░░░] (blue/yellow/red bar)  │        │
│ │                                                │        │
│ │  Weapons         [────█────]   100%            │        │
│ │  Engines         [────█────]   100%            │        │
│ │  Sensor Array    [────█────]   100%            │        │
│ │  Shield Generator[────█────]   100%            │        │
│ │  Tractor:  On / Off  (if applicable)           │        │
│ │  Cloak:    On / Off  (if applicable)           │        │
│ │                                                │        │
│ │              [Warp Core │ Main │ Reserve]      │        │
│ └────────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────┘
```

### Repair lists — behavioural rules

- **Three repair teams** auto-assign in damage-arrival order.
- If only one system is damaged, **all three teams work it together**,
  giving 3× repair speed.
- Click a row in *Repair Team Assignments* to **demote** that system
  (move it down the priority queue, freeing a team for the next
  damaged system).
- Click a row in *Damaged Systems* to **promote** that system
  (immediately move it to the top of the repair queue).
- *Destroyed Systems* are read-only. The **only** in-game repair is to
  dock at Starbase 12 (LoMar → *Dock*).

### Power Transmission Grid

Shows the live state of the ship's three energy reservoirs and how
power is allocated to systems.

#### Power Source Gauges (right edge, three vertical bars)

| Bar | Source |
|---|---|
| Left | **Warp Core** condition. As the Warp Core is damaged its production drops; if it reaches 0% the ship suffers a warp core breach and is destroyed. |
| Middle | **Main Battery** charge. Drains when usage > Warp Core production; recharges when usage < production. |
| Right | **Reserve Battery** charge. Only drained when Main is also being drawn; recharges when not. |

#### Power Used Bar

A single horizontal bar showing total system draw. The frame around it
is colour-banded so the source of the power is visible:

| Frame band | Meaning |
|---|---|
| **Blue** | Warp-Core production. Anything within this band is being supplied by the Warp Core; surplus charges batteries. |
| **Yellow** | Bar has spilled into the yellow band — power is being drawn from the Main Battery. |
| **Red** | Bar has spilled all the way into the red band — Reserve Battery is now also being drawn. Reserve has a hard limit. |

#### Power Allocation Sliders

Per system, drag the slider to set 0–125%. The percentage is shown on
the right end of each bar.

- **100%** is normal capacity; the manual states there is **no penalty
  for boosting to 125% beyond the increased power draw**.
- **Weapons** — higher power → faster phaser charge / torpedo reload;
  lower → slower.
- **Engines** — higher → more responsive turning + higher max speed;
  lower → sluggish + slower.
- **Sensor Array** — higher → longer effective sensor range; *also*
  changes the range at which contacts appear on the Target List.
- **Shield Generator** — higher → faster shield recharge; lower →
  slower recharge.

When the Warp Core takes damage, the engine may **auto-adjust** power
allocations to fit the reduced production budget.

#### Tractor / Cloak indicators

If the ship has these systems, two extra rows appear:

- **Tractor: On / Off** — current tractor state.
- **Cloak: On / Off** — current cloak state.

Both also draw battery power continuously while engaged (Tractor → Main,
Cloak → Reserve).

#### Power-management heuristics (manual's tips)

- Don't sit at Red Alert when not in combat — drop to Green to
  conserve and recharge.
- Sluggish ship + targets dropping off the Target List = check for
  Warp-Core damage or empty batteries; rebalance allocations.
- Power Used Bar:
  - Inside the blue frame → batteries are *charging*.
  - Spilled into yellow → drawing Main Battery.
  - Spilled into red → drawing Reserve Battery as well.
- Docking at a starbase replenishes batteries.
- Tractor + Cloak are extremely useful but can drain batteries fast —
  monitor.

---

## Damage indicators (shared with Tactical Mode)

When a subsystem on the player ship is damaged, an **icon** is drawn on
the ship-image inside the Engineering damage-control panel **and** on
the *Target Shields* HUD when the player targets another ship.

Icons (manual, p. 25):

| Icon | System |
|---|---|
| ✦ Sensor Array | sensor coverage |
| ⚙ Device | misc devices |
| ▣ Hull | hull integrity |
| ╱ Impulse Engine | impulse propulsion |
| ╳ Warp Engine | warp propulsion |
| ⌂ Warp Core | reactor |
| ◯ Shield Generator | shield grid |
| ▦ Torpedo Tube | torpedo launchers |
| ⊡ Phaser / Beam Weapon | phaser arrays / beams |
| ⊞ Pulse Weapon / Cannon | pulse / cannon weapons |

Colour code:

- **Yellow** icon → system is *damaged* (degraded).
- **Grey** icon → system is *disabled*.
- **Red** icon → system is *destroyed*.

The same icon glyphs appear on the *Target Shields* panel when the
player has a hostile target selected, allowing quick assessment of how
damaged the enemy is.

---

## Bridge transitions

| Trigger | Effect |
|---|---|
| `Space` | Switch to Tactical Mode. |
| `ESC` | Open Main LCARS Menu overlay. |
| LoMar → *Warp* | Cinematic in-system or interstellar warp; ship arrives at chosen course. |
| LoMar → *Orbit Planet* | Establishes orbit around chosen body. |
| LoMar → *Intercept* | Closes on selected target (auto-warps if > 50 km). |
| LoMar → *Dock* | Begins docking sequence at Starbase 12 (only when in range). On completion, all repairs + restock. |
| Saffi → *Quick Battle Setup* | Opens QB Setup overlay (Quick Battle mode only). |
| Saffi → *Start Combat Simulation* | Begins QB combat (Quick Battle mode only). |
| Saffi → *End Combat Simulation* | Ends QB combat (Quick Battle mode only). |
| Saffi → *Contact Starfleet* / *Contact Engineering* | Opens dialogue with NPC. |
