# Quick Battle redesign: programme roadmap and standing decisions

**Date:** 2026-10-01
**Status:** living roadmap. Each sub-project gets its own brainstorm, spec and
plan. This file records decisions already taken with Mark, so they are not
re-litigated.

**Design reference:** the approved HTML spike, `spikes/quickbattle-setup/` on
branch `spike/quickbattle-setup` (worktree `.claude/worktrees/qb-setup-spike`).
Open `index.html` in a browser after running `build_assets.py` (see its README).
The spike's *design* is approved; its *code* is throwaway.

## Intent

Today's Quick Battle setup reads BC's own config widgets (`g_pShipsPane`) and
offers a flat catalog, two rosters and a player-ship pick
(`engine/ui/quick_battle_setup_panel.py`). The redesign gives it:

- **Ship metadata Dauntless owns:** era span, role, playable, named variants,
  title, and a species that can override the SDK's. Every ship definition must
  carry it; a mod ship that doesn't stops boot until the user supplies it.
- **A richer setup screen:** era and species filter rows, a catalog grouped by
  role, a ship sheet with bio and scale bars, named-ship picks, and presets.
- **Battle groups instead of two rosters.** Each group has an allegiance, a
  direction and a distance from the player.
- **A setup that is remembered between battles**, player ship included.

## Sub-projects

| # | Sub-project | Depends on | Status |
|---|---|---|---|
| 1 | **Ship metadata**: the fields, where they live, stock defaults, how mods declare them, the catalog API the game reads | — | spec + plan written (branch `feat/qb-ship-metadata`): `2026-10-01-ship-metadata-catalog-design.md`, plan `docs/superpowers/plans/2026-10-01-ship-metadata-catalog.md` |
| 2 | **Quick Battle setup screen and battle start**: the CEF screen, groups, presets, persistence, group spawning, named ships | 1 | not started |
| 3 | **Mod metadata gate**, grown into a pre-boot **Mod Ships screen**: gate mode (supply missing metadata), read-only home mode (`--mods`, pause **Quit and Manage Mods** relaunch), CEF keyboard input, a class-by-name catalog model, and the shim `SubMenu` fix | 1 | implemented on `feat/qb-mod-gate`, awaiting live check |
| 4 | **Mod manager**: grows sub-project 3's home mode into a real manager, starting with enabling and disabling mods per mod (persisted, effective on relaunch), then whatever else is needed (load order, conflicts, editing complete ships' metadata) | 3 | not started |

Sub-projects 2 and 3 are independent of each other; either can follow 1.
Sub-project 4 follows 3.

**Small fix, any time (Mark's call when):** delete the revert-on-End-Combat hook
`_sync_quickbattle_player_revert` (`engine/host_loop.py`, commit `c6a21e63`).
It resets the player ship after every battle. BC does not: `EndSimulation` calls
`RecreatePlayer()` with `g_sPlayerType` untouched and leaves the rosters alone.
Sub-project 2 needs this gone regardless.

## Standing decisions

### Ship metadata (sub-project 1)

- **The unit is a ship definition** (one `ships/<id>.py`), not a class. A refit
  is a *separate* definition: an early-TNG Galaxy and a Venture-refit Galaxy are
  two scripts with their own hardpoints, textures, era and title. There is no
  class layer above definitions.
- **Fields:**

  | Field | Values |
  |---|---|
  | **Era** | a **from–to span** over the seven eras below, or `all` (timeless, e.g. Asteroid). A single era is a span of one. |
  | **Role** | Tactical · Auxiliary · Station · Automated / Unmanned |
  | **Playable** | yes / no — governs "Set as player ship" |
  | **Variants** | optional ordered list of named ships; the first is the class default |
  | **Title** | human-friendly name; user-amendable |
  | **Species** | overrides the SDK's faction where Dauntless disagrees (see below) |

- **Eras** (a boundary year belongs to the later era):

  | # | Era | Tag | Years | Summary |
  |---|---|---|---|---|
  | 1 | Pre Federation | ENT | 2140s–2240 | Warp 5 programme, early human exploration, Romulan War |
  | 2 | Early Federation | TOS | 2240–2293 | Five-year missions, Klingon hostility, ending with the Khitomer Accords |
  | 3 | Expansion Era | MOV | 2293–2330 | A golden age of expansion; a more peaceful UFP |
  | 4 | High Era | TNG | 2330–2367 | Stability and discovery, ended by Wolf 359 |
  | 5 | Quadrant Wars | DS9 · VOY | 2367–2399 | Dominion and Borg threats; the Alpha Quadrant reshaped |
  | 6 | Romulan Vacuum | PIC | 2399–2499 | Supernova fallout, the synthetic ban, legacy crews |
  | 7 | Distant Future | DISC | 2500–3200 | Sphere-builder war, the Burn, the Federation rebuilt |

- **All 33 stock catalog entries are Era 5** (BC is set after the Dominion War),
  except **Asteroid = `all`**. Mark ruled Probe, Decoy and Escape Pod Era 5, not
  `all`. The full stock seed is in the appendix.
- **Species diverges from the SDK in two places** (`Multiplayer/SpeciesToShip.py`
  is the SDK's view): Escape Pod is **Federation** (SDK: Neutral), and a new
  **Civilian** species holds Transport and Freighter (SDK: Federation). Card
  Freighter stays Cardassian. Neutral then holds only the Asteroid.
- **"Other Ships" and "Bases" stop being menus.** Faction (species) and Role do
  that job.
- **Named variants come in two kinds**, and the metadata must say which:
  - a **hull-name swap** on the same model: BC's `ReplaceTexture(..., "ID")`
    names (Galaxy: Dauntless, San Francisco, Venture). We render these as
    projected name decals (`engine/appc/hull_decals.py`). ⚠️ Masks exist today
    only for the **Ambassador** (Zhukov, Excalibur) and **Sovereign**
    (Sovereign, Enterprise); Galaxy, Nebula and Akira render nameless until
    theirs are authored.
  - a **separate ship script** on a stock model: Enterprise, Geronimo,
    Peregrine, RanKuf, MatanKeldon, E2M0Warbird, BombFreighter, BiranuStation.
    None is in today's menu.
- **Class defaults** match BC's `MissionLib` "default NCC" and our
  `registry_texture.DEFAULT_REGISTRY_BY_CLASS`: Galaxy → Dauntless,
  Sovereign → Sovereign, Nebula → Berkeley, Akira → Geronimo,
  Ambassador → Zhukov.

### Setup screen (sub-project 2)

The spike is the reference for every point below.

- **Classes come from the catalog, never from BC's menus.** Group ships by
  `engine.ship_catalog` class entries: the `variant_of` name chosen on the
  Mods screen (sub-project 3), with the starred `class_default` as each
  class's default ship. Do NOT read the old panel's widget tree or Foundation
  `SubMenu`/`menuGroup`. That tree reflects the mod author's menus and ignores
  the player's "Variant of" answers, which is why the old panel's nested
  "Defiant Class" menu doesn't rename.
- **Style:** the runtime **cp-\*** modal family (`configuration_panel.css`), not
  `docs/ui_designs/08` — Mark confirmed cp-\* is current.
- **Off-screen CEF rules out three things**, verified in code: no HTML5
  drag-and-drop (the host implements no `StartDragging`), no native `<select>`
  popup (no `PET_POPUP` handling), and no native tooltips. Menus, dropdowns and
  hover text are page-drawn.
- **Layout:** groups in a left column, catalog on the right, footer with presets
  (bottom left) and Close / Start Battle.
- **Filters:** two single-line pill rows that scroll sideways (the mouse wheel
  is mapped to horizontal).
  - **Eras:** multi-select, Quadrant Wars on by default. A year bracket follows
    a ship name only when more than one era is on.
  - **Species:** multi-select, Federation on by default. Each pill shows the
    species insignia (flagship icon if none: Kessok, Civilian, Neutral) and the
    count of matching entries.
- **Catalog:** cards grouped by Role only; within a role, species pill order.
- **Ship sheet:** selecting a card slides a sheet up from the **modal's** bottom
  edge, full width. It shows the image, chips, bio, Weapons text, tactics and
  two scale bars, with actions at the bottom right. It closes on ×, Esc, or a
  second click on the card.
- **Scale bars:** **Hull** and **Shields** (all six faces summed), no
  explanatory note.
  - 100% = the largest **playable** value: largest playable hull, largest
    playable shield total.
  - Larger values (stations) cap at 100%, gold, tagged "off scale".
  - ⚠️ BC's `Ships.tgl` "Shield Rating" text does **not** match the hardpoints
    (Sovereign: text 17F, game 11,000); never display it. "Hull Rating" is
    hull ÷ 1,000.
  - **Must include mod ships:** compute over the live post-mod catalog, and read
    values from the engine's **loaded** ship properties, not by parsing hardpoint
    files (mods override hardpoints).
- **Groups:**
  - Default: a **Friendly group** holding the player (first, marked YOU) and an
    empty **Enemy group**.
  - Each group has an **allegiance** (Friendly / Enemy / Neutral), a
    **direction** relative to the player (fore, aft, port, starboard, dorsal,
    ventral) and a **distance** preset:

    | Preset | km | GU |
    |---|---|---|
    | Close | 20 | ≈114 |
    | Standard | 35 | 200 (BC's own spawn distance) |
    | Long | 80 | ≈457 |
    | Out of range | 150 | ≈857 |

  - **The player's group has no direction or distance.** Its escorts form up
    beside the player, and its allegiance is locked to Friendly.
  - **Clicking a group makes it the add target** (5px gold right border). The
    sheet's main action reads "+ Add to ‹group›". No drag-and-drop.
  - **⋮ on a group:** Details (allegiance, direction, distance) swaps the ship
    list for a form, edits a draft, Update / Cancel. Also Rename, and Delete
    (not on the player's group). Unedited names follow the allegiance
    ("Neutral group 2").
  - **⋮ on a ship row:** pick a named ship (class default otherwise), Move to,
    Remove (the player's ship can't be removed).
  - Duplicate ships are separate rows, so each can be a different named ship.
  - Ships outside the selected eras are allowed but tagged **Out of era**.
  - Groups are a likely future home for per-group **AI** orders. Keep a group a
    stable object with an identity, not a label.
- **Presets:** a page-drawn "Load preset ▾" menu and a **+** that names and saves
  the current scenario, both opening **upwards**. Saving over an existing name
  asks to overwrite. A preset holds the **scenario** (groups, placements, ships,
  named picks, player ship), not the era and species filters. Store them in a
  file beside `settings.json`, as `bridges.json` is (spike: localStorage).
- **Persistence:** reopening the screen after a battle shows the exact same
  setup, player ship included.

### Mod metadata gate (sub-project 3)

- When a mod ship lacks the mandatory metadata, **stop at load** and ask the user
  for the values before the game runs. The user may also amend the **title**.
- The answers must persist, so the gate appears once per ship, not every boot.

## Open questions, by sub-project

These were **not** settled in the brainstorm. Each sub-project's own brainstorm
answers its share.

### 1: Ship metadata

**Answered** in `2026-10-01-ship-metadata-catalog-design.md` (its "Decisions" table):
metadata is a `dauntless` dict on the Foundation `ShipDef`; stock lives in the
committed `engine/foundation/shipdef_overrides.py`; gate answers are written into
the mod; insignias ship in-tree; one read-only catalog in `engine/ship_catalog/`.
The questions below are kept for the record.


- **Where does metadata live?** Candidates:
  - a committed stock table in the engine
  - a file a mod ships in its own folder
  - a user file beside `settings.json` holding gate answers and overrides

  What is the precedence between them? (Likely: user > mod-supplied > stock.)
- **Format and identity.** Key by ship script (`ships/<id>.py`)? How does it
  relate to Foundation's `ShipDefinition` (`engine/foundation/shipdef.py`, which
  already carries `race`, `species`, `name`, `SubMenu`…)?
- **The catalog API** that sub-projects 2 and 3 read: one place that merges
  stock + mods + overrides and answers "every ship definition, with metadata".
- **How a variant names its render path:** hull-name swap (registry/mask) vs
  separate script.
- **Species list ownership** and the insignia artwork. The spike's cleaned SVGs
  (`spikes/quickbattle-setup/insignias/`) are third-party marks. Do they ship
  in-tree, or come from the user or a mod?
- **Collision with BC's own data:** `Ships.tgl` titles ("Card Hybrid" →
  "Hybrid"), `SpeciesToShip` factions, `QuickBattle`'s ST\_\* tables. What is
  read, what is overridden, and what must keep working for the SDK?

### 2: Setup screen and battle start

- **How much of SDK `QuickBattle.py` survives?** Today the panel drives BC's
  widgets and handlers (`StartSimulation2`, `GenerateShips`, `EndSimulation`).
  Groups need our own placement. The precedent is wrapping module globals
  without editing the SDK (`bridge_selection.install_quickbattle_hook`,
  `foundation.quickbattle._ensure_build_dialog_reinjects`).
- **Placement maths:** direction from the player's axes (fore = `GetCol(1)`,
  starboard = `GetCol(0)`, dorsal = `GetCol(2)`; right-handed, see CLAUDE.md),
  km → GU only at the boundary (`engine/units.py`), and spacing within a group.
  What fixed formation do the player's escorts use?
- **Neutral ships:** QuickBattle has never used the mission's neutral group
  (`pMission.GetNeutralGroup()` exists), and there is no neutral AI module
  (only `QuickBattleAI`, `QuickBattleFriendlyAI`, `StarbaseAI`,
  `StarbaseFriendlyAI`). What do neutrals do? And what of win/lose: BC wins when
  the enemy count reaches zero.
- **AI difficulty:** BC's Low/Medium/High (`g_iSelectedAILevel`, Medium today
  because the panel hides it). Per group? Not in the spike.
- **Region:** Change Combat Region is not in the spike; battles happen where the
  player is (`_sync_quickbattle_spawn_set`). Confirm that stays.
- **Named ships at spawn:** hull-name swaps need masks (see above). Separate-
  script variants need `CreateShip` with that script.
- **Delete with ships:** the spike deletes a group and its ships without
  confirmation. Loading a preset doesn't warn about unsaved changes, and there
  is no way to delete a preset.

### 3: Mod metadata gate

**Answered** in `2026-10-01-mod-ships-screen-design.md` (its Decisions table):
it runs pre-boot after Foundation plugins load, as one table of all mod ships
with ticked-row bulk edits. Escapes are **Skip for now** (session-only) and
Quit. Re-asking is automatic, because a mod update's new ships are simply
incomplete. The questions below are kept for the record.

- **When exactly?** At boot after Foundation plugins load (`foundation.load_plugins`),
  before the game loop. The first-run picker (`engine/ui/first_run_panel.py`,
  driven from `host_loop.py`'s own pump loop) is the precedent for a CEF screen
  that runs before boot.
- **Per ship or per mod?** A pack like DCMPv2 registers 12 ships; filling 12
  forms one by one is heavy. Batch editing? Defaults pre-filled from the SDK
  (species, a role guess)?
- **"Skip for now"?** Mark's brief says stop. Can the user disable the mod
  instead (`--disable-mods` / `DAUNTLESS_DISABLE_MODS` exist, but switch off *all* mods)?
- **Re-asking:** what if a mod updates and adds ships?

## Evidence notes

- The stbc-reference MCP (clean-room RE) was **unavailable** during the
  brainstorm (connection failure). Nothing here depends on RE'd behaviour; the
  BC facts are from the SDK scripts and were checked in the tree:
  - `EndSimulation` keeps the player ship and rosters
  - `GenerateShips` places at radii + 200 GU ahead, with random jitter
  - `ReplaceTexture(…, "ID")` names
  - SpeciesToShip factions
- **Installed mods at the time:** CGSovereign (collides with stock "Sovereign"
  and is rejected by `foundation.quickbattle.register`), DCMPv2 (12 Defiant-class
  ships, `SubMenu` "Defiant Class") and LC Intrepid Pack (3 ships). All declare
  `menuGroup`/`playerMenuGroup = 'Fed Ships'`.
- **Scale-bar reference values** (stock, from SDK hardpoints):
  - largest playable hull: **Warbird 24,000**
  - largest playable shield total: **Sovereign 49,500**
  - largest single shield face: **Vor'cha fore 24,000**
  - largest hull in the whole install: **Asteroidh1 400,000** (a campaign rock,
    which is why the scale is *playable*, not *install*)

## Appendix: stock metadata seed

From the session of 2026-10-01; the source for sub-project 1's stock defaults.
Era is 5 (Quadrant Wars) unless stated. "Playable" = BC's own player menu (16
ships, matching the SDK's `MAX_FLYABLE_SHIPS = 16`).

| ship_id | Title | Species | Role | Playable | Variants (class default first) |
|---|---|---|---|---|---|
| Akira | Akira | Federation | Tactical | yes | USS Geronimo, USS Devore |
| Ambassador | Ambassador | Federation | Tactical | yes | USS Zhukov, USS Excalibur |
| Galaxy | Galaxy | Federation | Tactical | yes | USS Dauntless, USS San Francisco, USS Venture |
| Nebula | Nebula | Federation | Tactical | yes | USS Berkeley, USS Prometheus, USS Khitomer, USS Nightingale |
| Sovereign | Sovereign | Federation | Tactical | yes | USS Sovereign, USS Enterprise |
| Shuttle | Shuttle | Federation | Auxiliary | yes | — |
| EscapePod | Escape Pod | Federation | Auxiliary | no | — |
| FedStarbase | Fed Starbase | Federation | Station | no | — |
| FedOutpost | Fed Outpost | Federation | Station | no | — |
| SpaceFacility | Space Facility | Federation | Station | no | — |
| DryDock | Dry Dock | Federation | Station | no | — |
| CommArray | Comm Array | Federation | Automated / Unmanned | no | — |
| Probe | Probe | Federation | Automated / Unmanned | no | — |
| Decoy | Decoy | Federation | Automated / Unmanned | no | — |
| BirdOfPrey | Bird of Prey | Klingon | Tactical | yes | — |
| Vorcha | Vor'cha | Klingon | Tactical | yes | — |
| Warbird | Warbird | Romulan | Tactical | yes | — |
| Galor | Galor | Cardassian | Tactical | yes | — |
| Keldon | Keldon | Cardassian | Tactical | yes | — |
| CardHybrid | Hybrid | Cardassian | Tactical | yes | — |
| CardFreighter | Card Freighter | Cardassian | Auxiliary | no | — |
| CardStarbase | Card Starbase | Cardassian | Station | no | — |
| CardStation | Card Station | Cardassian | Station | no | — |
| CardOutpost | Card Outpost | Cardassian | Station | no | — |
| CommLight | Comm Light | Cardassian | Automated / Unmanned | no | — |
| Marauder | Marauder | Ferengi | Tactical | yes | — |
| KessokLight | Kessok Light | Kessok | Tactical | yes | — |
| KessokHeavy | Kessok Heavy | Kessok | Tactical | yes | — |
| KessokMine | Kessok Mine | Kessok | Automated / Unmanned | no | — |
| Sunbuster | Sun Buster | Kessok | Automated / Unmanned | no | — |
| Transport | Transport | Civilian | Auxiliary | yes | — |
| Freighter | Freighter | Civilian | Auxiliary | no | — |
| Asteroid | Asteroid | Neutral | Automated / Unmanned | no | — (era `all`) |

Only the variants named by BC's own campaign scripts are listed. The role of
**Asteroid** is a placeholder: none of the four roles fits a rock, and that
wasn't discussed.
