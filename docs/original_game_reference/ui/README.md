# Star Trek: Bridge Commander — User Interface Reference

> Source: Activision/Totally Games *Star Trek: Bridge Commander* PC manual
> (`stbc manual.pdf`, retail print, 2002).
>
> Anything in this folder is an as-shipped behavioural description, not an
> implementation note. Where the manual is silent (e.g. exact pixel
> positions, font sizes), the docs say so explicitly rather than guessing.

This subtree documents every screen the original 2002 game presents to the
player, the controls each screen accepts, and the navigation paths that
connect them. It is written so that an engine reimplementation can
reproduce the player-visible behaviour faithfully.

---

## Document map

| File | Covers |
|---|---|
| [`screen-map.md`](screen-map.md) | The full graph of screens and the inputs that move the player between them — read this first. |
| [`launch-and-main-menu.md`](launch-and-main-menu.md) | Launch Screen (pre-game shell), Main LCARS Menu, Load Game dialog, Configure (general/sound/graphics/controls), Quit. |
| [`bridge-mode.md`](bridge-mode.md) | Bridge-mode camera and selection rules, Character Tool Tips, the per-crew menus (First Officer, Helm, Tactical, Science, Engineering), the Power Transmission Grid, alert states, and orbital/warp navigation. |
| [`tactical-mode.md`](tactical-mode.md) | External Tactical view: ship piloting controls, Sensors panel, Target List panel, Shields panel, Target Shields panel, Weapons panel, Phaser Arc / Torpedo / Speed display, Damage Icons, Manual Fire mode, Map Mode, Cinematic Mode. |
| [`quick-battle-and-multiplayer.md`](quick-battle-and-multiplayer.md) | Quick Battle Setup (Ships, Player and Region, AI levels), Multiplayer main, Join Game, Host Game, Ship Select, the five game types, scoring rules. |
| [`keyboard-mouse-reference.md`](keyboard-mouse-reference.md) | Default key/mouse bindings for every documented command, grouped exactly as the in-game **Configure Controls** screen groups them. |

---

## High-level mental model

The player experience is structured as a small number of distinct
**screen modes**, each with its own input rules:

```
                 ┌────────────────────────┐
                 │      Launch Screen     │   ← OS shell, before stbc.exe
                 │  (Install/Play/Help…)  │      really runs
                 └───────────┬────────────┘
                             │ Play
                             ▼
                 ┌────────────────────────┐
                 │    Main LCARS Menu     │   ← top-level in-game menu;
                 │  New / QB / MP / Load  │      reachable from anywhere
                 │   Configure / Quit     │      via ESC
                 └─┬──────┬──────┬──────┬─┘
                   │      │      │      │
                   │      │      │      └────► Configure
                   │      │      └───────────► Multiplayer flow
                   │      └──────────────────► Quick Battle
                   │                           (in-bridge setup)
                   ▼
        ┌─────────────────────────────┐
        │  In-mission Bridge view     │ ◄──Space──► ┌─────────────────┐
        │  (1st-person on bridge,     │             │  Tactical view  │
        │   crew menus via mouse/F1-6)│             │  (external 3rd  │
        │                             │             │   person; HUD)  │
        └─────────────────────────────┘             └─────────────────┘
                   ▲                                        ▲
                   └─────────────── ESC ────────────────────┘
                                    │
                                    ▼
                        Main LCARS Menu (overlay)
```

Two ideas drive almost every UI decision:

1. **Bridge mode is "command by delegation"** — the player looks at a
   crew officer, opens that officer's menu, and issues an order. The
   officer carries it out. The player rarely touches the ship directly.

2. **Tactical mode is "command by hand"** — the camera moves outside the
   ship, a HUD overlays the scene, and WASD/Q/E/F/X put the player in
   direct control of flight and weapons. Issuing any order to Felix
   (Tactical Officer) hands controls back to him.

Switching between the two is a single press of **Space**. Every other
top-level screen is reached either from the Main LCARS Menu (ESC) or from
in-bridge submenus (e.g. Quick Battle Setup is opened from Saffi's menu
*while the player is sitting on the bridge*).

---

## Conventions used by these docs

- **Fixed inputs** are written as keycaps (e.g. `Space`, `F1`, `T`).
  Mouse buttons are written `LMB` / `RMB` / `MMB`.
- **In-game button labels** are written in *italics* (e.g. *Hail*, *Set
  Course*, *Start*).
- **Crew-officer menus** are referenced by the officer's name and rank as
  they appear on the bridge: *First Officer (Saffi)*, *Tactical (Felix)*,
  *Helm (LoMar)*, *Science (Miguel)*, *Engineering (Brex)*.
- **"Panel"** refers to one of the corner HUD widgets in Tactical Mode
  (Sensors, Target List, Shields, etc.) — each has a minimise arrow in
  its top-right corner.
- **"Status window"** / **Character Tool Tip** is the floating label that
  appears above an officer when the bridge view is centred on them.
- The manual is silent on exact pixel positions; descriptions use
  cardinal screen quadrants ("lower-right corner", "upper-left corner")
  exactly as the manual does.

---

## What this folder deliberately does **not** cover

- Internal engine plumbing (NIF tags, Python binding internals,
  netcode). See `architecture/`, `engine/`, `networking/`, `protocol/`.
- Per-mission scripted UI (mission-specific viewscreen overlays, etc.)
  beyond what the manual describes generically.
- Modder-added UI elements not present in the shipping retail build.
