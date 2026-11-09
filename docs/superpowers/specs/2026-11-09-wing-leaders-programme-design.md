# Wing leaders — programme design

Date: 2026-11-09. Brainstormed with Mark the same day. This is the PROGRAMME
document: what the whole thing is for, the decisions that hold across every
phase, and how the work is run. Each phase (A–D) gets its own spec and plan,
which build on this one.

## 1. Why

In Quick Battle every ship fights its own duel. Within a few minutes ships are
100 km+ apart and there is no longer "a battle" on screen. Mark introduced
Quick Battle **groups** partly to represent the wings of starships heard about
in large Trek battles; this programme makes those groups fight as wings.

What it should feel like:

- the fight stays in one place (within BC's close/mid range bands);
- a wing's ships pick targets that make sense for the group, protect each
  other, and pursue Quick Battle objectives together;
- killing a wing's command is visible and matters: a leaderless wing falls
  apart into individual, more desperate ships.

Mark, verbatim on scope: "I don't want to completely change the game's AI, I
just want to give it a sense of direction."

### Root cause found in the SDK

`AI/Preprocessors.py` `SelectTarget.GetTargetRating` scores each candidate
from nine weighted factors. The **popularity** factor defaults to **−1.1 per
other ship already targeting the candidate**, while being close adds at most
1.0. BC deliberately spreads ships across different targets, so a free target
far away beats a nearby one somebody else is already shooting. Combined with
every attack tree chasing its own target wherever it runs (`Intercept` past
~350 GU), the battle splits into duels.

## 2. Goals, non-goals, anti-goals

**Goals**

- Wings stay together and fight one battle (leash ≈ mid range, see §5).
- Coordinated target choice, mutual protection, objective support.
- A **behaviour library** modders can extend and mix into their own AI, the
  way BC's `AI/` and `Conditions/` folders were a library its AIEditor and
  modders assembled.
- **Performance:** large battles get slightly faster (followers rate a short
  list instead of every enemy); small battles get no slower.

**Non-goals**

- Replacing BC's attack AI. Stock trees still do all the flying and fighting.
- Campaign missions. They build their own AI and are untouched unless a
  script chooses to use the library.
- Species instincts (Klingons go for the weakest, Romulans guard the leader).
  A later layer that shifts decision scores; the programme leaves the seam.
- New AI decider node types (`PriorityListAI` etc.). Not needed; new
  questions + existing deciders express everything below.

**Anti-goals** (a failure even if it technically works)

- Any loss in performance beyond run-to-run variation (§8).
- Breaking SDK or mod AI scripts, or knocking stock preprocessors off the
  native path for ships that don't use wings.
- A sim that must "check in" with Python mid-step (see
  `feedback_sim_runs_without_python_checkins`): the wing brain runs on its own
  cadence and writes data the stock AI reads.

## 3. Three layers

1. **Wing brain** (engine). One per Quick Battle group, ticking on the sim at
   about 1 Hz of game time. Looks at the whole wing: picks priority targets,
   notices wingmates in trouble, measures spread, hands over command. Python
   first; it goes native later like the rest of the AI if measurement says so.
   Its state is readable by scripts through a small documented surface.
2. **Behaviour library** (SDK-style Python). New **questions** (conditions),
   **manoeuvres** (PlainAI script modules), **background scripts**
   (preprocessors) and **decisions** (what a wing brain may choose to do),
   importable and composable like `AI.PlainAI.Intercept` or
   `Conditions.ConditionInRange`. They connect a ship's tree to its wing brain.
   Modern Python is fine (the library depends on the wing brain, which only
   exists in Dauntless; it never has to run in original BC).
3. **Stock BC AI**, unchanged: Quick Battle's `QuickBattleAI` /
   `QuickBattleFriendlyAI` → `BasicAttack` → Fed/NonFed/Cloak attack trees.

Quick Battle is the first consumer: it builds each ship's tree from the stock
attack plus wing behaviours.

## 4. Chain of command

- **Candidates:** the top 20% of the group by reactor (power plant) output,
  **rounded down, minimum 1**. 25 ships → 5; 9 → 1; 10 → 2.
- **One commander at a time.** The other candidates are successors in power
  order. When the commander dies the next candidate takes over; the wing
  brain keeps running, only whose ship it treats as the leader changes.
- **Fixed at battle start.** Not re-ranked by damage: a battered flagship
  stays in command while it lives. Ties: the order the group lists its ships.
- **The player** tops the chain of any group they are in, regardless of power.
- **Late arrivals** join their group's wing but never enter the chain.
- **Leaderless:** when the last candidate dies the wing dissolves. Ships fall
  back to stock AI and become more desperate (more willing to flee, more
  willing to ram), by re-weighting when the stock `Flee` and `Ram`
  manoeuvres are used, not by new movement.
- "Go for the enemy leader" means the CURRENT commander; it moves to the
  successor when the commander dies, so decapitating a big wing takes several
  kills.

## 5. Cohesion

- **Anchor = the leader**, not the wing's centre (a centroid moves strangely
  when one ship strays; the leader is easy to see and reason about). When the
  player leads, the anchor is the player's ship.
- **Leash = mid range** (~200 GU ≈ 35 km; BC's attack trees' own mid band),
  one dial, tunable live. Per-ship slack so a follower mid torpedo run isn't
  yanked back the instant it crosses the line.
- BC's range bands for reference (`AI/Compound/FedAttack.py`,
  `NonFedAttack.py`): close ~150 GU Fed / ~100 GU other; mid ~200 GU; long
  (intercept) past 350 GU.

## 6. Decisions

A commander picks its wing's current decision by **scoring every decision it
knows** each brain tick, with **stickiness** (hysteresis) so it doesn't
flip-flop. Decisions are library entries: a mod can add one the way it adds a
manoeuvre, and species instincts later just shift the scores.

| # | Decision | Phase |
|---|---|---|
| 1 | **Swarm**: concentrate on a chosen target — the enemy's weakest ships, or its commander and that commander's support | A |
| 5 | **Regroup**: gather on the leader when the wing is too spread out | A |
| 6 | **Don't chase**: let a target that runs past the leash go | A |
| 2 | **Protect**: defend a wingmate (or a QB "protect" ship) under heavy fire, including putting a ship physically between it and its attackers | B |
| 7 | **Rotate damaged ships**: a ship with failing shields drops behind fresh wingmates until they recover | B |
| 8 | **Withdraw**: the wing pulls out together in good order when the odds turn | B |
| 9 | **Flank / focus a shield face**: spread round a target so it can't turn its strong face to everyone, or concentrate on the face that's down | C |
| 10 | **Disable rather than destroy**: knock out the biggest threat's weapons or a ship's engines | C |
| 11 | **Hold a reserve**: keep a ship or two back and commit them where the fight tips | C |
| 3 | **Reinforce** a friendly wing that needs it | D |
| 4 | **Hold a location** to draw enemies out of shape | D |
| 12 | **Bait and feint**: a false retreat that draws enemies onto another wing | D |

Prior art: Starsector's admiral AI (orders to ship groups rather than flying
them: eliminate, escort, rally, capture, harass, avoid, retreat); Total War
(morale, routing, the classic loss of shape chasing routers); squad-shooter
AI such as F.E.A.R. (regroup, flank).

### Locations are relative to groups (Mark, 2026-11-09)

Phase D's "hold a location" never uses a fixed map point. Every location is
defined relative to groups and recomputed as they move: a **flank** position
off an enemy wing (relative to its leader and heading), a **screen** between
an enemy wing and a friendly wing, a **lure** point away from an enemy wing
chosen to pull it off the friendly wing it is engaging. No map data needed,
so it works in every Quick Battle region.

## 7. Phases

Each phase is its own spec + plan + subagent-driven build, on its own branch
cut from the end of the previous phase. Each is additive (new behaviours and
decisions; it does not rewrite the previous phase's), so a play-test fix on an
earlier phase forwards cleanly.

- **A. Foundation — fixes the drift.** Wing brain, chain of command, library
  surface, swarm (#1, with the follower shortlist that carries the perf gain),
  regroup (#5), don't chase (#6), leaderless fallback + desperation.
- **B. Looking after each other.** Protect (#2) with a new body-block
  manoeuvre, rotate damaged ships (#7), withdraw (#8).
- **C. Fighting smarter.** Flank / shield face (#9), disable (#10), reserve (#11).
- **D. Wings working together.** Reinforce (#3), hold a relative location
  (#4), bait and feint (#12). The base for later many-wing objectives.

## 8. How the work is run (Mark, 2026-11-09)

- Project branch `feat/wing-leaders` (cut from local main 5a3c93ddb). Phase
  branches `feat/wing-leaders-a` … `-d`, each cut from the end of the one
  before. One dedicated worktree (`.claude/worktrees/wing-leaders`) with its
  own Debug build, so the main checkout stays on main and runs measure this
  branch's code.
- Per phase: write the phase spec and plan, implement subagent-driven, and do
  NOT wait for Mark's live check or spec approval before the next phase.
- **End of each phase: a headless perf A/B and `scripts/gate_merge.sh`.**
  This is a deliberate exception to the "gate only on a main merge" rule, for
  this programme only: Mark wants problems caught at the phase that
  introduces them.
- **Perf rule:** the same headless large battle run with wings off vs on, same
  build. The pass/fail number is `gl.ai`: it must not rise in any phase, and
  phase A must lower it at large ship counts. Whole-frame time is reported
  alongside, read knowing tighter battles put more ships in weapons range.
  **Anything that looks like more than run-to-run variation triggers a
  review** — there is no "minor loss" allowance. Results go in the perf
  register as signals.
- Each phase ends with **three acceptance criteria** for Mark's play test.
  After sign-off Mark merges the phases into the project branch in order, then
  the project branch into main (with its own merge gate).
