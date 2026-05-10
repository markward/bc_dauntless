# Quick Battle and Multiplayer

Two non-campaign modes share most of their UI: both drop the player
onto a bridge (or directly into Tactical) and let them fight in a
configurable scenario. Quick Battle is offline / single-player;
Multiplayer is online or LAN.

> See [`screen-map.md`](screen-map.md) for how these screens connect to
> the rest of the UI.

---

## Quick Battle

Reached from *Main LCARS Menu → Quick Battle*. The game **does not
present a setup screen first** — instead, the player is dropped onto
the bridge of a default ship, and the configuration UI is exposed as
**three special entries on Saffi's menu**:

```
First Officer (Saffi) menu — Quick Battle additions
─────────────────────────────────────────────────
  Report
  Damage Report
  Green / Yellow / Red Alert
  Objectives
  Show Mission Log
  Contact Starfleet
  Contact Engineering
  ─────────────────────────────────
  Quick Battle Setup            ← only in QB mode
  Start Combat Simulation       ← only in QB mode
  End Combat Simulation         ← only in QB mode
```

| Saffi item | Effect |
|---|---|
| *Quick Battle Setup* | Opens the Quick Battle Setup overlay (next section). |
| *Start Combat Simulation* | Begins the simulated battle with current settings. |
| *End Combat Simulation* | Terminates the simulated battle (the simulation also auto-ends if the player ship is destroyed). |

### Quick Battle Setup overlay

A modal overlay opened by Saffi → *Quick Battle Setup*. Top-row buttons
choose the sub-view; bottom-row buttons close or commit:

```
┌── Quick Battle Setup ─────────────────────────────────┐
│  [Ships]   [Player and Region]            [Close] [Start]
├───────────────────────────────────────────────────────┤
│                                                       │
│   <selected sub-view's content>                       │
│                                                       │
└───────────────────────────────────────────────────────┘
```

#### Ships sub-view

Two columns. The left column lists every ship type the engine knows;
the right column shows the current battle roster (split into Friendly
and Enemy sections).

| Element | Behaviour |
|---|---|
| Left list (ship types) | Click to highlight a class. |
| **AI Level** buttons (**Low**, **Medium**, **High**) | Set the AI rating for the next ship added. |
| **Add as Friendly Ship** | Adds the highlighted ship to the right column under Friendly. |
| **Add as Enemy Ship** | Adds the highlighted ship to the right column under Enemy. |
| Right list rows | Click to select an existing roster ship. |
| Selected roster row | Can be deleted, or its allegiance flipped. |

> AI Level applies **at the moment of adding** a ship. Existing ships
> retain whatever AI level was set when they were added.

#### Player and Region sub-view

Two columns. The left column picks the player's own ship; the right
column picks the system / region the battle takes place in.

Player-ship selection drilldown:

1. Pick a **race** (Federation, Klingon, Romulan, Cardassian, Ferengi,
   Kessok…).
2. Pick a **specific ship class** within that race.

Because Quick Battle is a *simulation*, the bridge is always either the
**Galaxy** or **Sovereign** class bridge — it doesn't try to render a
unique non-Federation bridge for the simulated vessel.

Region selection: pick a system / region from the right list. A
description is shown on focus.

#### Bottom-row buttons

| Button | Effect |
|---|---|
| **Close** | Dismisses the overlay; returns to bridge in QB-ready state. |
| **Start** | Commits + launches the simulated battle. |

---

## Multiplayer

Reached from *Main LCARS Menu → Multiplayer*.

### Network Minimum System Requirements (manual quote, p. 28)

- **28.8k modem** — up to 3 players.
- **33.6k modem** — up to 4 players.
- **56k modem** — 4 players *with a dedicated server*.
- **LAN/Broadband** — required for 5–8 player games.

### Main Multiplayer Menu

```
┌── Multiplayer ──────────────┐
│  [ Host Game ]              │
│  [ Join Game ]              │
│  [ Main Menu ]              │
└─────────────────────────────┘
```

| Button | Effect |
|---|---|
| **Host Game** | Open Host Game form. |
| **Join Game** | Open Join Game form. |
| **Main Menu** | Return to Main LCARS Menu. |

### Join Game

```
┌── Join Game ──────────────────────────────────────────────┐
│ Player Name:    [_________________]                       │
│ Password:       [_________________]                       │
│                                                           │
│ [Direct Join Game]   IP: [___.___.___.___]                │
│                                                           │
│ ( ) Internet     ( ) LAN                                  │
│                                                           │
│ [Start Query]   [Stop Query]                              │
│                                                           │
│ ┌── Result table ──────────────────────────────────────┐  │
│ │ Name       Type     Ping  P/M   Players    Game Info │  │
│ │ <rows from query>                                    │  │
│ └──────────────────────────────────────────────────────┘  │
│                                                           │
│                                            [   Start   ]  │
└───────────────────────────────────────────────────────────┘
```

Field semantics:

| Field | Behaviour |
|---|---|
| **Player Name** | The player's display name in the game. |
| **Password** | Required if joining a host that is restricted. |
| **Direct Join Game + IP** | Immediate connect by typed IP. **Validation**: the IP must contain no more than 12 numeric digits with each of the four octets being **at most 3 digits**, separated by `.`. Invalid → *Invalid IP Address* error. Example given: `192.168.x.x`. |
| **Internet / LAN** | Selects the lookup network for the query. |
| **Start Query** | Begins searching for hosted games. |
| **Stop Query** | Aborts the search before completion. |

Result columns:

| Column | Meaning |
|---|---|
| **Name** | Game name set by the host. |
| **Type** | Game type (Deathmatch, Team Deathmatch, etc.). |
| **Ping** | RTT in ms — lower is better. |
| **P/M** | Current players / Max players. |
| **Players** | Names of players already in the game. |
| **Game Info** | Specific win-condition parameters set by the host. |

`Start` joins the highlighted game → moves to the [Ship Select](#ship-select-screen) screen.

### Host Game

```
┌── Host Game ──────────────────────────────────────────────┐
│ Game:           [ Deathmatch | Team DM | UFP vs. Non-UFP   │
│                   | Defend the Starbase ]                  │
│ Game Name:      [_________________]                        │
│ Player Name:    [_________________]                        │
│ Password:       [_________________]                        │
│                                                            │
│ ( ) Internet Game   ( ) LAN Game                           │
│                                                            │
│ [ ] Dedicated Server                                       │
│                                                            │
│                                                [  Start  ] │
└────────────────────────────────────────────────────────────┘
```

Field semantics:

| Field | Behaviour |
|---|---|
| **Game** | Pick a game type from the supported list (see [Game Types](#game-types)). |
| **Game Name** | The game's lobby name (visible to joiners' query). |
| **Player Name** | Host's display name. |
| **Password** | Optional; if set, joiners must supply it. |
| **Internet / LAN** | Network the game is announced on. |
| **Dedicated Server** | When checked, the host doesn't play; gains the ability to view scores and **boot unruly players**. |

`Start` → [Ship Select](#ship-select-screen).

### Ship Select Screen

The lobby where each player picks their ship. The host has additional
controls for global match settings.

```
┌── Ship Select ────────────────────────────────────────────┐
│ ┌── Ship class ──┐  ┌── Selected ship preview ──┐         │
│ │ Race lists     │  │  <render or stat panel>   │         │
│ │ Federation     │  │   • Race                  │         │
│ │ Klingon        │  │   • Class                 │         │
│ │ Romulan        │  │   • Description           │         │
│ │ Cardassian     │  │   • Weapon rating         │         │
│ │ Ferengi        │  │   • Shield rating         │         │
│ │ Kessok         │  │   • Hull rating           │         │
│ └────────────────┘  │   • Tactical tips         │         │
│                     └───────────────────────────┘         │
│                                                           │
│ ┌── (host only) ─────────────────────────────────────┐    │
│ │  System / region selector                          │    │
│ │  Player count                                      │    │
│ │  Time limit                                        │    │
│ │  Score limit                                       │    │
│ └────────────────────────────────────────────────────┘    │
│                                                           │
│                                                [  Start  ]│
└───────────────────────────────────────────────────────────┘
```

> "When selecting a ship to play in Multiplayer, you will notice that
> the ship description is immediately followed by a brief list of
> tactical tips. All of the ships have these tips." — manual, p. 30.

`Start` launches the multiplayer match. Players load into the bridge
of their chosen ship.

---

## Game Types

The host picks one of four game types when creating the game.

### Deathmatch

- **Free-for-all** — every player against every other.
- Any ship class is selectable.
- **Scoring**: kills don't directly equal points. Stronger-ship-vs-
  weaker-ship kills are worth less; weaker-ship-vs-stronger-ship kills
  are worth more. The relative ship values determine point award.
- End condition: time limit *or* score limit (host's choice).
- Score-vs-frags interpretation: when score limit is set, **points are
  more important than frags**.

### Team Deathmatch

- Two teams. Players pick a side at lobby; either side may pick any
  ship.
- End condition: time limit *or* score limit.
- Same scoring logic as Deathmatch.

### UFP vs. Non-UFP Deathmatch

- Asymmetric two-team mode.
  - **UFP team** — any Federation vessel (including a Shuttle).
  - **Non-UFP team** — any non-Federation vessel.
- End condition: time limit *or* score limit.
- Same point logic as Deathmatch.

### Defend the Starbase

- One team protects a starbase, the other team attacks it.
- Either side can select any ship.
- End condition is **either**:
  - **Time limit** — defenders win if it expires before the starbase
    is destroyed.
  - **Frag limit** (manual: "a certain number of frags have been
    scored by the defending team") — defenders win if attackers are
    killed enough times.
- Attackers' win condition: destroy the starbase before any time/frag
  limit aborts them.
- When the manual phrases this section it explicitly notes: in this
  game type, **kills (frags) are more important than score**.

---

## Ship and station combat data

The manual's *Starfleet Archival Database* section (pp. 59–76) lists
specifications and "Tactical Tips" for every multiplayer-selectable
ship and every station type. Those raw numbers (displacement, hull
rating, shield ratings on six faces, weapons loadout) are reflected in
the Ship Select preview panel.

This file does not duplicate the per-ship statlines — see the
`gameplay/` documentation set for combat-side numbers
(`gameplay/combat-and-damage.md`, `gameplay/ship-subsystems.md`). The
UI just exposes the values that exist there.

---

## Cloak in MP/QB

The cloak feature is **only present** in Multiplayer and Quick Battle
(it is not used in the single-player campaign). When the player ship
class has a cloak, it is exposed:

- As an entry on Felix's Tactical menu (toggle).
- As an entry on Brex's Power Transmission Grid (status indicator).
- In the Tactical-Mode Weapons panel (toggle).
- Bound to `Alt + C` by default.

While cloaked:

- The player's ship does **not appear** on enemy Target Lists.
- Phasers cannot lock onto the player.
- The player's **shields go offline**.
- The player **cannot fire weapons**.
- Power is drained continuously from the **Reserve Battery**.

---

## Probes are restricted in MP

> *"Note: Probes may not be launched in Multiplayer."* — manual, p. 16.

Miguel's *Launch Probe* entry is disabled (or omitted) in MP sessions.
Probes remain available in single-player and Quick Battle.
