# Quick Battle victory conditions

**Date:** 2026-10-23
**Status:** design, awaiting Mark's approval
**Roadmap:** sub-project 2c of `2026-10-01-quickbattle-redesign-roadmap.md`.
This design replaces that row's "free condition builder" idea: Mark compared
a rule builder against named battle types (mockups in
`.superpowers/brainstorm/52410-1792767062/content/`) and chose **named battle
types**.

## 1. Intent

Stock Quick Battle has one way to win: destroy every enemy. Even that win
does not end the battle (`QuickBattle.py:3356` plays the win lines and leaves
you flying), and the only loss is your own death. This sub-project adds a
small set of named battle types, each with clear win and lose rules, and
makes every battle end properly.

The types come from what BC's own scripts already do: campaign "protect this
ship" missions (E2M0, E2M6, E4M5, E7M1 and others), multiplayer Mission5's
starbase attack and defence, and E5M2's away team.

## 2. Goals, non-goals, anti-goals

**Goals**
- Four battle types: **Elimination**, **Kobayashi Maru**, **Starbase
  Assault**, **Capture the Flag**.
- A victory view on the existing setup screen to pick and configure the type.
- Every battle ends on a win or a loss, with a line, the fanfare and Saffi's
  menu (Restart).
- One shared **beam transport** action and a new **Transporter** subsystem,
  used by Starbase Assault and Capture the Flag.

**Non-goals**
- A general win/lose rule builder (rejected in favour of named types).
- Hold the Line and Capture the Technology (both considered, both cut by Mark).
- Friendly ships beaming *from* the player's ship, or the player beaming
  through an ally's Transporter. Every ship beams only with its own.
- Recording new voice audio (the one new line ships as a subtitle until a
  recording exists).
- Campaign or multiplayer changes: this is Quick Battle only.

**Anti-goals** (would make this a failure even if it works)
- A victory view that looks or behaves unlike the rest of the setup screen.
  It must reuse the setup screen's existing classes and controls.
- A battle that can be started but can never be won.
- Edits to SDK files. Everything wraps SDK functions, the way
  `spawn.install_generate_ships_hook` and `spawn.install_end_simulation_hook`
  already do.

## 3. The victory view (setup screen)

- A **⚙ button** sits immediately left of **Close** in the setup footer
  (`native/assets/ui-cef/index.html`, `#qbs-close`). It is lit
  (`cp-toggle--on` look) while the victory view is open.
- Clicking it swaps the **groups column and the ship catalog** for the
  victory view. The footer (presets, summary, ⚙, Close, Start Battle) stays.
  Clicking ⚙ again returns to the ships view.
- **Left column:** the battle types as cards in the group-card style
  (`.qbs-group`), in this order, each with a one-line description:

  | Type | Card description |
  |---|---|
  | Elimination | Destroy every enemy to win. |
  | Kobayashi Maru | Destroy every enemy and keep one ship alive |
  | Starbase Assault | Attack or defend a starbase |
  | Capture the Flag | Take the flag and hold it longest |

  The selected card uses the purple selected style. Wording on the last two
  is my call; Elimination's wording is Mark's.
- **Right side (`cp-body`):** the type's name as a section heading, a one-line
  rule summary, then only the blanks that type needs (§5).
- **Unavailable types grey out**, with the reason shown on the card in place
  of its description (e.g. "Add a friendly or neutral ship first").
- **Design reference:** `victory-pane-v4.html` in the brainstorm folder above.
  It loads the real `configuration_panel.css` and `quick_battle_setup.css`.
  Any new rule must use the existing tokens (`--qbs-*`, `cp-*`).
- **New setups default to Elimination.**
- **If an edit to the ships makes the chosen type invalid** (e.g. the protected
  ship is removed), the type falls back to Elimination and the footer summary
  says why.
- **Footer summary** names the type and its key choice, e.g.
  "Kobayashi Maru · protect SS Kobayashi Maru". When Start Battle is disabled
  it says why.
- **Presets** save the victory settings with the ships
  (`quickbattle_presets.json`). A preset saved before this work loads as
  Elimination. The victory settings persist within a run only, like the rest
  of the setup.

### Start Battle gating

Start Battle is enabled only when **both** hold:
1. There is at least one enemy ship. Late-arriving (warp-in) groups count.
   This replaces today's "any ship besides the player" rule in
   `engine/quickbattle/scenario.py:87` `can_start`.
2. The chosen type's requirements and blanks are satisfied (§5).

## 4. Shared battle machinery

### 4.1 One place that ends a battle
An evaluator owns win and lose for the four types. It ends a battle by posting
BC's own `ET_END_SIMULATION` to the XO with **int 2 for a win, int 1 for a
loss** (`QuickBattle.py:3175` `EndSimulationEvent`, which runs `EndSimulation`,
the win/lose sequence and the fanfare). That is the path BC already uses for
player death.

- A **win ends the battle for every type, including Elimination.** This is a
  deliberate departure from BC, where a win leaves you flying.
- **Your own death** is always a loss, unchanged.
- **Only one ending per battle.** If two endings fire in the same tick, the
  player-death loss beats everything else; otherwise the first one evaluated
  wins (BC's `bWonOrLost` guard).
- All battle clocks run on **game time** and freeze under pause. Every timer
  is cancelled by End Combat, Restart and mission swap, through the existing
  `EndSimulation` hook.
- No evaluator state change may live in `render_payload` (see
  `docs/reference/engine/perf-cadences-and-latency.md`).

### 4.2 Ending lines
- **Win:** Felix's existing "That's it! We got 'em." (`QBFelixWin`), win
  fanfare, Saffi's menu with Restart.
- **Loss, own ship destroyed:** unchanged (`QBComputerLose`, "The ship has
  been destroyed. Ending simulation.").
- **Loss, protected ship or station destroyed:** a **new Saffi line**, "The
  ship we were assigned to protect has been destroyed. Ending simulation."
  (Mark's wording). It is authored in `tools/dialogue/dauntless_crew.json` and
  generated with `tools/gen_dauntless_tgl.py`. There is no recording, so it
  plays as a subtitle only until one exists.
- **Other losses** (the attackers hold the station, the flag match is lost):
  a builder's choice of line, subtitle only if new. Wording is left to the
  builder; keep it in BC's terse style.

### 4.3 Reused BC lines
Use these where they fit. Before wiring each one, check that its sound file
exists and that its speaker is on the Quick Battle bridge.

| Moment | Line | Source TGL |
|---|---|---|
| Our shields drop for a beam | "Lowering shields for transport." | Bridge Crew General `LoweringShields` |
| Target's shields are down | "Enemy's shields are down." | Bridge Crew General `gt024` |
| Beam ordered with our shields up | "We'll need to lower our shields, Captain." | E1M1 `E1M1ShieldProd2` |
| Countdown | "Nine / Seven / Five / Three / One minute(s) remaining" | E8M2 `E8M2Countdown9`…`1` |
| Time nearly up | "We're running out of time! We must destroy them now!" | E6M3 `E6M3TroopsLand` |
| Starbase lost | "Sir, the Starbase has been destroyed." | E7M1 `E7M1StarbaseDestroyed` |

Quick Battle's own lines (per-class "Simulated friendly … destroyed", the win
and lose banter) are already wired up and keep working.

### 4.4 Objectives
Each type adds its goals to **Saffi's Objectives menu**, the way campaign
missions do (`engine/appc/mission_goals.py`). Goal text is new and generated
into our TGL. Examples: "Protect SS Kobayashi Maru" and "Destroy all enemy
ships".

### 4.5 Target list markers
- The **protected ship** (Kobayashi Maru) has a **shield icon** beside its name.
- The ship or probe **holding the flag** (Capture the Flag) has a **flag icon**.
- The icons have no colour states. Any separate on-screen alert is a later,
  independent piece of work (Mark).

### 4.6 Top-right battle display
Starbase Assault and Capture the Flag show their live state in the
**top-right corner** of the screen, which Mark says is always clear. Contents
per type are in §5. A beam in progress also shows its progress there.

## 5. The battle types

### 5.1 Elimination
- **Win:** every enemy destroyed, late arrivals included. **Lose:** your death.
- Needs at least one enemy (already covered by Start Battle gating).
- The only change from today: the win ends the battle (§4.1).

### 5.2 Kobayashi Maru
- **Blanks:**
  - **Ship to protect:** a list of every friendly and neutral ship in the
    setup, never the player and never an enemy. It is grouped the way the
    ships view groups them, with a Protect toggle per row (the `cp-toggle`
    look). Exactly one is chosen.
  - **Time limit:** optional, default None. It uses the warp-in delay's
    − / + stepper, in whole minutes.
- **Greys out** when there is no friendly or neutral ship other than the player.
- **Win:** every enemy destroyed while the protected ship is alive.
- **Lose:**
  - the protected ship is destroyed, by anyone, friendly fire included;
  - your death;
  - the time limit runs out before the win.
- The E8M2 countdown lines call out the remaining minutes.
- **Markers:** the shield icon (§4.5) and an Objectives entry.

### 5.3 Starbase Assault
One type with two sides. The **station's allegiance** in the setup decides the
player's role: an **enemy** station means you attack it, a **friendly** station
means you defend it.

- **Blanks:**
  - **Station:** chosen from the setup's stations, meaning entries whose
    catalog role is Station, friendly or enemy only. If there is only one,
    it is pre-chosen.
  - **Hold time:** default **2 minutes**, − / + stepper.
- **Greys out** with no friendly or enemy station in the setup, or when the
  player's ship has no Transporter (§6.3).
- **Control** is a bar from 0 to 100%.
  - Each **attacking team** aboard pushes it up and each **defending team**
    aboard pushes it down. Equal numbers stall it.
  - Each side can have at most **4 teams** aboard, counted across all of that
    side's ships.
  - Teams arrive only by beam transport (§6). The station starts with no
    teams aboard and control at 0% (my call).
  - Whichever side owns the station beams its own defending teams over:
    enemy ships do this when the player attacks (Mark's original idea), and
    the player does it when defending.
  - **Teams fight it out** (Mark). While both sides have teams aboard, each
    side loses one team every **30 seconds** (a dial, §6.2). A stalled bar
    therefore never stays stalled, and holding control means continuing to
    beam reinforcements.
- **Hold:** when control reaches 100% the attackers hold the station and a
  **2-minute hold clock** starts. Pushing control back below 100% **resets** the
  clock to the full hold time (Mark: restart, not pause).
- **Attackers win** by holding the station for the full hold time.
- **Defenders win** by destroying every attacking ship. There is no overall
  time limit.
- When the player attacks, destroying every enemy ship except the station
  does **not** win early. Nobody is left to beam defenders over, but the
  station still has to be taken and held.
- **Destroying the station loses the battle for the player,** whichever side
  the player is on. It is the prize when attacking and the thing to protect
  when defending. The new protect line (§4.2) plays when defending.
- The station keeps its own AI and keeps firing on the attackers throughout.
  It does **not** switch sides while the attackers hold it.
- **Top-right display:** the control bar, both sides' team counts (transports
  completed, out of 4) and the hold clock when it is running.

### 5.4 Capture the Flag
- **Blanks:**
  - **Flag carrier:** chosen from the setup's enemy and neutral ships.
  - **Match length:** default **5 minutes**, − / + stepper.
- **Greys out** with no enemy or neutral ship, or when the player's ship has
  no Transporter.
- **Taking the flag:**
  - **From a ship:** one beam transport (§6) takes the flag straight across,
    with no return trip.
  - **Stealing it back:** enemy ships take it from the player the same way.
  - **When a holder is destroyed** (an enemy holder; the player's death ends
    the battle anyway), the flag drops into space as a **probe** at the
    holder's position.
    - It is BC's `Probe` ship script, named "Flag" and invincible
      (`SetInvincible`).
    - It is listed in the target list with the flag icon.
    - It drifts with the holder's last velocity.
  - **Grabbing a loose flag** needs only the grabbing ship's own shields down
    and a working Transporter, for the usual 10 seconds.
- **Scoring:**
  - Each side builds up time for as long as one of its ships holds the flag.
  - Nothing resets. A loose flag adds time to nobody.
  - When the match clock runs out, the side with more total time wins.
  - **A tie is a loss** for the player.
- **Destroying every enemy wins at once** (Mark). The match clock doesn't have
  to be sat out.
- **Lose** also on your own death.
- **Top-right display:** the match clock, who holds the flag, and each side's
  total time.
- **NPC behaviour:** the carrier's side defends the flag. Once the player's
  side has it, enemy ships pursue the holder to steal it back. **Friendly
  ships beam too** (Mark): they try to take the flag off enemy holders. Both
  sides go for a loose flag. A friendly ship holding the flag adds time to the
  player's side.

## 6. Beam transport and the Transporter subsystem

### 6.1 The action
- It is ordered from **Felix's Tactical menu** (`Bridge/TacticalMenuHandlers.py`
  surface) and acts on the **current target**. The button label is a builder's
  choice that fits the type ("Beam Team", "Beam Flag").
- **It needs all of these, held for 10 unbroken seconds:**
  1. The **beaming ship's own shields are down**, meaning its shield
     subsystem is off. **Ordering a beam lowers them automatically** (Mark):
     Felix says "Lowering shields for transport." and the shields come back
     up when the beam ends or is cancelled. This must **not** go through the
     alert level, which would also switch the weapons off (`SetAlertLevel`
     in `engine/appc/ships.py`). It needs its own lower-and-restore path that
     leaves weapons and alert state untouched. A manual re-raise during the
     beam cancels it. Enemy ships use the same path.
  2. The **target's shield face toward the beaming ship is down**, using the
     existing hull-box face selection
     (`engine/appc/combat.py:_shield_face_from_hit_point`). Not needed for a
     loose flag probe.
  3. **When beaming onto a friendly station:** the station lowers its own
     shields automatically when the transport starts and raises them when
     it ends. This leaves it exposed, which is intended (Mark).
  4. The **beaming ship's Transporter is working** (§6.3).
- **No range limit** (Mark: the show beams to planets). Weapons ranges keep
  this honest, because shields recharge unless the target stays under fire.
- **Cancelled** if any condition fails partway through: either set of shields
  comes back up, or the Transporter is disabled or destroyed. Felix says why,
  reusing §4.3 lines where they fit.
- **NPC ships on both sides** beam under exactly the same rules, each with
  its own Transporter (Mark: "your allies should try to beam off enemy ships
  too"). Allies board an enemy station and take the flag off enemy ships.
  When the player defends a friendly station, allies also beam defending
  teams onto it (my call, by symmetry).

### 6.2 What "shields down" means
The face counts as down at or below a threshold fraction of its maximum. It
is a dial, read at use. Its default is my call: **5%**. It needs live tuning,
because face recharge (every 0.5 s) decides whether a beam can ever finish.
The control-bar rate (§5.3) is also a dial. Both go in a dev dial group on the
existing developer dials.

### 6.3 The Transporter subsystem
- A new subsystem, **"Transporter"**, which every beam needs. **Disabling it is
  the counter-play** (Mark): disable a carrier's Transporter and it cannot
  steal the flag back.
- **Stock ships:** add it to every stock ship through the existing hardpoint
  override system (`engine/appc/hardpoint_overrides.py`). It must use the
  stock-BC-safe `hasattr`-guarded extension format, so the same hardpoint
  text still loads in the original game.
- **Mod ships with no Transporter cannot beam** until someone adds one (Mark).
  The Ship Property Viewer's **+ Add** gains a **Transporter** entry, next to
  Running Light, and saves it into the mod's hardpoint file the way existing
  SPV saves do.
- Stations get one too. Only the **beaming** ship's Transporter matters, not
  the target's.
- It is targetable and damageable like any other subsystem. **Disabled** is
  temporary: it comes back with repair. **Destroyed** is permanent, under the
  existing rule that destroyed subsystems are never repaired.
- **Out of transporters is a loss** (Mark). In Starbase Assault and Capture
  the Flag, the player loses once **no ship on the player's side** (you or an
  ally) has a Transporter that isn't destroyed. Losing your own Transporter
  with an ally's still working is not a loss. The enemy side running out
  just means it can no longer beam.
- A ship can carry more than one Transporter subsystem (my call). The ship
  can beam while any one of them works.
- Placement and hit points per class are the builder's.

## 7. Constraints

- **No SDK edits.** Wrap module functions once per load, as the existing hooks
  do.
- Follow CLAUDE.md:
  - paths resolve at use;
  - game units in GU;
  - the column-vector rotation convention;
  - write nothing under the install outside the allowlist;
  - keep stock ship-data literals Python 1.5-safe.
- Run focused tests only during development. The gate runs only at the
  main merge, when Mark says.
- **Headless end-to-end tests** must drive a real Quick Battle through each
  type's win and each loss, entering at the setup panel's plan, not below it.

## 8. Decided by Mark

- Named battle types, picked in a cog-toggled view, not a rule builder.
- The four types above; Hold the Line and Capture the Technology are cut.
- Elimination's card text "Destroy every enemy to win."
- Protect list: friendly and neutral only. Kobayashi Maru greys out without
  one.
- Start Battle needs at least one enemy and the chosen type's needs met.
- Shield icon on the protected ship, with no colour states.
- Objectives in Saffi's menu.
- The new Saffi loss line, worded as in §4.2.
- A win ends the battle (Felix, fanfare, menu).
- Starbase Assault merges attack and defend. Control bar with up to 4 teams a
  side. A 2-minute hold that restarts when broken. A top-right display with
  team counts.
- Defending: the station's shields and yours both drop, and the station
  lowers its own.
- Capture the Flag: the flag is grabbed in one 10-second beam. Total time held
  within a configurable match (default 5 minutes), with no resets. A dropped
  flag becomes a probe in the target list.
- Beam: no range limit, cancelled if shields recover, ordered from Felix's
  Tactical menu.
- A Transporter subsystem added via hardpoint overrides. Disabling it blocks
  beaming. Mod ships without one cannot beam.
- Starbase teams fight it out: one lost per side every 30 s while both sides
  are aboard.
- Ordering a beam lowers your shields automatically and restores them after.
- Capture the Flag: destroying every enemy wins at once.
- The Transporter can be destroyed. You lose when no ship on your side has
  one left.
- Allies beam too, off enemy ships, each with its own Transporter.

## 9. My calls (Mark to check)

- New setups default to Elimination. An invalid type falls back to
  Elimination, and the footer says why.
- Card wording for Kobayashi Maru, Starbase Assault and Capture the Flag.
- Starbase Assault: defenders win by destroying every attacker. Destroying
  the station loses for the player on either side. The station never switches
  sides.
- Capture the Flag: a tie is a loss. The loose flag is invincible and drifts.
  A loose-flag grab needs only the grabber's shields down.
- "Shields down" threshold 5%, as a dial.
- Allies beam onto a friendly station they are defending, as well as off
  enemy ships. Neutrals stay inert, as Quick Battle already rules, so a
  neutral flag carrier never moves or fights.
- Late-arriving groups count as enemies for Start Battle and for wins. A
  protected ship may be in a late group; it counts as protected from arrival.
- Simultaneous endings: the player-death loss beats everything, otherwise the
  first evaluated.

## 10. Left to the builder

- Evaluator structure, module layout, and how state reaches the CEF views.
- The NPC AI for beaming and flag pursuit, on both sides (§5.3, §5.4, §6.1). It must respect the
  AI cadences in `perf-cadences-and-latency.md`.
- Exact control-bar rate, HUD styling within the existing HUD language, and
  icon artwork (match the target list's style).
- Which speaker says each reused line, after checking the sound files.
- Transporter placement and hit points per stock class.

## 11. Suggested build order

Each phase is shippable and live-checkable on its own:

1. **Victory view, evaluator, battle endings, Elimination and Kobayashi Maru**
   (§3, §4, §5.1, §5.2).
2. **Transporter subsystem and beam transport**, with the top-right display
   (§6, §4.6), including the SPV + Add entry.
3. **Capture the Flag** (§5.4), including flag pursuit for both sides.
4. **Starbase Assault** (§5.3), including boarding AI for both sides. This is the
   largest, because of the AI.

## 12. Not live-verified

Everything here is unbuilt. Game feel needs Mark's live check per phase,
above all: beam success against recharging shields, the 2-minute hold, the
5-minute match length, and the enemy beaming behaviour.
