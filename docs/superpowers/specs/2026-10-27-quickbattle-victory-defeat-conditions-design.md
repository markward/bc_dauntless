# Quick Battle victory and defeat conditions

**Date:** 2026-10-27
**Status:** built, not live-verified
**Replaces:** the named battle types of
`2026-10-23-quickbattle-victory-conditions-design.md` (its §3, §5.1, §5.2 and
the "named types" rulings in §8). Its battle-end machinery (§4), and the
mechanics of Starbase Assault, Capture the Flag and beam transport (§5.3,
§5.4, §6), still stand; §8 below says how those become conditions.
**Branch:** `feat/qb-victory-p1`. This rework lands there, replacing the
battle types, **before** the branch merges (Mark, 2026-10-27).

## 1. Intent

Phase 1 shipped two named battle types, Elimination and Kobayashi Maru. Mark
found named types too restrictive: they cannot express the reverse of
Kobayashi Maru (hunt one particular enemy), or protecting three ships, or
surviving for a time.

So the victory view stops offering battle types and instead lists two stacks
of **conditions**:

- **Victory conditions**: any one of them met wins the battle.
- **Defeat conditions**: any one of them met loses it.

Each stack starts with a fixed default that cannot be removed, which together
are exactly stock Quick Battle:

| Stack | Default |
|---|---|
| Victory | **Destroy All Ships** (every enemy destroyed, late arrivals included) |
| Defeat | **Player Ship Destroyed** |

The player adds more conditions to either stack. Kobayashi Maru becomes
"Defeat: Ships Destroyed (the Freighter)" plus an optional Defeat Timer; its
mirror is "Victory: Ships Destroyed (the Galor)".

## 2. Goals, non-goals, anti-goals

**Goals**
- Two condition kinds in this phase, each addable to either stack:
  **Ships Destroyed** and **Timer** (§4).
- Everything phase 1 built for Kobayashi Maru (markers, enemy targeting,
  objectives, countdown, loss line, presets) works per condition, for any
  number of ships.

**Non-goals**
- Grouping or nesting conditions (no "A and (B or C)"). The only AND is the
  ALL mode inside one Ships Destroyed list.
- New condition kinds beyond the two above. Starbase and flag conditions come
  with the later phases (§8).
- Recording voice audio. New lines ship as subtitles, as phase 1's did.

**Anti-goals**
- A screen that looks or behaves unlike the rest of the setup screen. It
  reuses the setup screen's classes and tokens (`cp-*`, `--qbs-*`), as the
  mockup does.
- A battle that can never end in a win **because of a bug** (a condition
  that is never evaluated, a timer that never fires). A setup the player
  makes unwinnable on purpose is allowed: for example a 2 min Defeat Timer
  with the only enemies warping in at 5 min. Start Battle does not check
  reachability (Mark, 2026-10-27: "there's no fatal consequence... the
  player is just setting something up they can't win").
- SDK edits. Everything stays in the existing wrappers.

## 3. The screen

**Design reference:** `2026-10-27-quickbattle-conditions-mockup.html` beside
this spec (Mark: "much better"; brainstorm original
`.superpowers/brainstorm/93527-1793105507/content/conditions-b-v2.html`, with
the rejected layout A in `conditions-layouts.html`). It loads the real
`configuration_panel.css` and `quick_battle_setup.css`; its new rules are
built only from existing tokens.

- The **⚙ button**, the footer, presets, Close and Start Battle are unchanged.
  ⚙ still swaps the groups column and the ship catalog for this view.
- The view is **two equal columns** split by a single rule: **Victory** on the
  left, **Defeat** on the right. Each column is headed by its section label
  and, at the right, "Any one of these wins" / "Any one of these loses".
- **Defaults** are dashed, quiet cards marked "Default", with no ×.
- **Added conditions** are solid cards with one × at the top right that
  removes the condition.
- **Ships Destroyed card:**
  - a sentence with an ANY / ALL segmented toggle: "Win when [ANY|ALL] of
    these are destroyed" / "Lose when [ANY|ALL] of these is destroyed" (the
    verb agrees: "is" for ANY, "are" for ALL);
  - the listed ships as the setup screen's own rows: the ship's icon (the
    same icon source as the ships view), its name, its group, an edge
    coloured by the group's allegiance, and its own × to drop it;
  - "+ Add ship", which opens the setup screen's usual drop menu listing the
    ships this stack may name that are not already in this list.
- **Timer card:** "Win when [− N min +] run out" / "Lose when [− N min +] run
  out", the existing − / + stepper, whole minutes, 1 to 60 (my call).
- **"+ Add condition"** at the bottom of each column opens the drop menu:
  *Ships Destroyed*, *Timer*. *Timer* is not offered when that stack already
  has one.
- **Footer summary:** the ship counts plus the added conditions as counts,
  e.g. "3 groups · 6 ships · 1 victory · 2 defeat conditions" (defaults not
  counted; with none added the suffix is omitted). When Start Battle is
  disabled it says why instead. (My call: the mockup's spelled-out summary is
  too long for the footer.)

### Which ships a stack may name

| Stack | Eligible ships |
|---|---|
| Victory | every ship in an **enemy** group (Mark) |
| Defeat | every ship in a **friendly or neutral** group, never the player (Mark) |

Ships in late warp-in groups are eligible (my call).

### Start Battle

Enabled only when both hold:
1. At least one enemy ship (unchanged from phase 1; late groups count).
2. **No Ships Destroyed condition is empty.** An empty one blocks Start with
   a reason in the footer, e.g. "A Ships Destroyed condition has no ships"
   (my call). The player can fix it by adding a ship or removing the
   condition.

### Keeping conditions valid as the setup changes

- A ship removed from the setup drops out of every list it was in.
- A ship whose group changes allegiance so that its stack no longer allows
  it (an enemy made neutral, a neutral made enemy) drops out of that list.
- A list emptied this way stays, empty, and blocks Start (above). Phase 1's
  "fall back to Elimination with a notice" goes away.

### Presets

Presets save both stacks. A preset saved by phase 1 loads by conversion:
Elimination → no added conditions; Kobayashi Maru → a Defeat Ships Destroyed
(ANY) holding the protected ship, plus a Defeat Timer if it had a time limit.
A preset saved before phase 1 loads with no added conditions. Unknown or
malformed condition data is dropped leniently, as phase 1's loader does (my
call).

## 4. The rules

### 4.1 Ships Destroyed
- Holds one or more ships and a mode, **ANY** or **ALL** (Mark). Default mode
  when added: **ANY** (my call).
- **ANY** is met when any listed ship is destroyed; **ALL** when every listed
  ship is destroyed.
- A ship counts as destroyed **whoever destroys it**, friendly fire and
  collisions included (my call; phase 1's protected ship already works this
  way).
- A listed ship in a late group that has not arrived yet is simply not
  destroyed. ALL cannot be met until it has arrived and died.
- The same ship may appear in two conditions of the same stack (harmless). A
  ship can never be in both stacks, because the stacks name disjoint
  allegiances.

### 4.2 Timer
- **Victory Timer:** met when its time runs out. The player wins by
  surviving (with the defaults, by staying alive).
- **Defeat Timer:** met when its time runs out. Phase 1's Kobayashi Maru time
  limit.
- At most one per stack (my call). The clock starts when the battle starts,
  runs on game time and freezes under pause, as phase 1's does.
- The spoken countdown (E8M2 `E8M2Countdown9`…`1`, at 9/7/5/3/1 minutes
  remaining) follows the **earlier** timer when both stacks have one (my
  call); it is the clock that will settle the battle.
- Both timers with the **same** time: the loss wins (my call, matching phase
  1's tie-goes-to-the-loss rule in Capture the Flag).

### 4.3 Settling a battle
- The battle ends the moment any victory condition or any defeat condition
  is met, through phase 1's single ending path (`battle_end.end_battle`,
  BC's `ET_END_SIMULATION` int 2 / int 1).
- **Only one ending, and a loss can overturn a pending win.** Phase 1 posts
  an ending 1 s of game time after it is decided (`END_DELAY_S`, BC's own
  delay), and a player death inside that second cancels a pending win. That
  window now applies to **every** defeat condition: any defeat condition met
  before a pending win is posted replaces it with that loss (my call). The
  case it covers is the explosion chain: the protected Freighter dies 0.3 s
  after the last enemy, in that enemy's blast. A pending loss is never
  overturned by a win. Player death is then just another defeat condition.
- An unarmed battle (no plan) keeps BC's stock behaviour, as in phase 1.

## 5. What each condition carries in the battle

### 5.1 Defeat: Ships Destroyed (the protected ships)
- **Marker:** the shield icon beside each listed ship in the target list
  (phase 1's `target_markers`).
- **Enemy targeting:** phase 1's E6M1 weighting (`km_targeting.py`), now for
  every ship in every Defeat Ships Destroyed list: each at
  `{"Priority": 2.0}`, listed first, every `pFriendlies` member at
  `{"Priority": 1.0}`. BC's popularity term spreads several attackers across
  several protected ships. Neutral protected ships stay neutral.
- **Loss line** (Saffi, subtitle): ANY → phase 1's "The ship we were
  assigned to protect has been destroyed. Ending simulation."
  (`SaffiQBProtectedLost1`). ALL with more than one ship → a new line, "The
  ships we were assigned to protect have been destroyed. Ending simulation."
  (my wording, in Mark's pattern).

### 5.2 Victory: Ships Destroyed (the targets)
- **Marker:** a **crosshair** icon beside each listed ship, in the shield
  icon's style (my call).
- **Friendly targeting:** the mirror of §5.1 (my call). Friendly NPC attack
  AI (`QuickBattleFriendlyAI`, `StarbaseFriendlyAI`, which target
  `pEnemies`) gets an `ObjectGroupWithInfo` with each listed target at
  `{"Priority": 2.0}`, listed first, and every `pEnemies` member at
  `{"Priority": 1.0}`, through the same redirect mechanism, so escorts help
  with the hunt. With no Victory target list, friendly targeting stays
  stock.
- **Win line:** Felix's existing "That's it! We got 'em." (`QBFelixWin`), as
  for any combat win.

### 5.3 Timers
- **Victory Timer win line:** a new Saffi subtitle line, "Time is up. We held
  them off. Ending simulation." (my wording).
- **Defeat Timer loss line:** phase 1's `SaffiQBTimeUp1`, "We have run out of
  time. Ending simulation."
- Countdown as in §4.2.

### 5.4 Objectives
One entry per condition in Saffi's Objectives menu, defaults included
(wording my call, generated into our TGL like phase 1's):

| Condition | Entry |
|---|---|
| Destroy All Ships | "Destroy all enemy ships" |
| Victory Ships Destroyed, ANY | "Destroy the Galor or the Keldon" |
| Victory Ships Destroyed, ALL | "Destroy the Galor and the Keldon" |
| Victory Timer | "Survive for 5 min" |
| Defeat Ships Destroyed, ANY | "Protect the Freighter and USS Zhukov" |
| Defeat Ships Destroyed, ALL | "Keep the Freighter or USS Zhukov alive" |
| Defeat Timer | "Win within 5 min" |

Player Ship Destroyed gets no entry (it is implied, as in phase 1). With one
ship the list wording collapses to "Destroy the Galor" / "Protect the
Freighter". Long lists may be shortened ("…and 2 more") at the builder's
choice.

## 6. Constraints

- Everything in the phase 1 spec's §7 still applies: no SDK edits, CLAUDE.md
  rules, focused tests only, headless end-to-end tests that enter at the
  setup panel's plan.
- The view keeps phase 1's page/panel split: Python owns state and verbs,
  the page renders the payload and sends verbs. No game-state mutation in
  `render_payload`.
- New dialogue goes through `tools/dialogue/dauntless_crew.json` and
  `tools/gen_dauntless_tgl.py`, never a hand-edited TGL.

## 7. Decided by Mark (2026-10-27)

- Victory and defeat **condition stacks** replace named battle types.
- Fixed, unremovable defaults: Victory "Destroy All Ships", Defeat "Player
  Ship Destroyed".
- **Ships Destroyed** can be added to either stack: enemies only on the
  Victory side, friendly or neutral on the Defeat side.
- A Ships Destroyed condition holds several ships and its own **ANY / ALL**
  mode.
- **Timer** can be added to either stack.
- Layout **B**, side-by-side stacks edited in place, cleaned up as in
  `conditions-b-v2.html`.
- The rework lands on `feat/qb-victory-p1`, replacing the types, before the
  branch merges.
- No reachability check on Start: an unwinnable setup is the player's choice.

## 8. My calls (Mark to check)

- Any one condition met settles its stack (the rule that makes the flip
  work); any defeat condition met before a pending win is posted turns it
  into a loss.
- A ship counts as destroyed whoever destroys it.
- One Timer per stack; 1-60 min; the countdown follows the earlier timer;
  equal timers resolve as a loss.
- An empty Ships Destroyed list blocks Start; allegiance changes drop
  ineligible ships; late-group ships are eligible.
- New Ships Destroyed conditions start in ANY mode.
- Crosshair marker on Victory targets; friendly NPCs weight Victory targets
  E6M1-style.
- The two new Saffi lines and the Objectives wording in §5.
- Footer summary as counts.
- Phase 1 presets convert; malformed condition data is dropped.

**Later phases** keep the phase 1 spec's mechanics but arrive as condition
kinds in these stacks rather than as battle types (my call), for example:
- Starbase Assault → Victory "Hold [station] for 2 min" (attacking) and
  Defeat "[station] held by the enemy for 2 min" (defending), with the
  station's destruction expressed as an ordinary Ships Destroyed condition.
- Capture the Flag → Victory "Hold the flag longest in N min", with its
  carrier and match length as the condition's blanks.
The phase 1 spec's §11 build order is otherwise unchanged; each later phase
rewrites its section in these terms when it is designed.

## 9. Left to the builder

- The data model and JSON shape of conditions, verbs and payload keys.
- How `battle_end` evaluates the stacks (event-driven on destruction and
  timers, as today, rather than polled).
- How `km_targeting` generalises to several protected ships and to the
  friendly-side mirror.
- Crosshair icon artwork, in the shield icon's style.
- Whether the drop menus reuse `qbs-menu` as-is or need a small variant.

## 10. Not live-verified

Built (Tasks 1-7, headless-tested end to end); nothing here is live-verified yet. Mark's live check, above all: the screen at real
size, the hunt (friendly escorts actually helping), several protected ships
spreading the enemy, and the survival timer.
