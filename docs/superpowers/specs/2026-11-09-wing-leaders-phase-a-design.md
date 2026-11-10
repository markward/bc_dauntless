# Wing leaders — Phase A: foundation (fixes the drift)

Date: 2026-11-09. Builds on `2026-11-09-wing-leaders-programme-design.md`
(read it first: §2 goals/anti-goals, §3 layers, §4 chain of command, §5
cohesion, §8 process). Branch `feat/wing-leaders-a`.

Items marked **(call)** were decided by Claude without Mark, under his
instruction to proceed without spec approval; they are listed again in §12 for
his review at play-test time.

## 1. What Phase A delivers

- The **wing brain** (one per wing, ~1 Hz of game time) and its registry.
- The **chain of command** (programme §4).
- **Swarm** (#1) with the **wing target group** that feeds stock
  `SelectTarget` — the perf lever.
- **Regroup** (#5) and **don't chase** (#6) — the drift fix.
- **Leaderless fallback + desperation.**
- The first **behaviour library** entries and the SDK-facing surface
  (`DauntlessWings`) that both Quick Battle and `combat_stress` use.
- A switch, a dial group, a dev log, a commander marker, and the
  `combat_stress` wiring the perf A/B needs. (Mark, 2026-11-09: the switch is
  a Quick Battle setup option and the marker is always on, §11.)

## 2. Facts this design rests on (verified 2026-11-09)

- QB groups: `engine/quickbattle/scenario.py:46-56` (`Group`: id, allegiance,
  difficulty, player, entries…). `battle_plan()` (:431-465) emits
  `SpawnOrder`s with `group_id`; the player entry is skipped and
  `PlayerOrder` (:365-370) has **no group id**. Ship name → group is not
  recorded after spawn, but object names are `naming.object_name(order.title,
  n)` with n the 1-based plan index (`battle_end.py:244` builds the same
  index).
- `km_targeting` (`engine/quickbattle/km_targeting.py`) wraps each QB AI
  module's `CreateAI` and, for the duration of that call only, redirects
  `App.ObjectGroup_FromModule("QuickBattle.QuickBattle", <side>)` to a weighted
  `ObjectGroupWithInfo`. `ObjectGroup_ForceToGroup` keeps identity, so every
  `SelectTarget` built in that call **shares the group object**. Armed from
  `battle_end.begin`; reset by `battle_end.reset` and `reset_mission_state`.
- Stock `SelectTarget` stays on the native rating path when we (a) call
  `SetRelativeImportance`, (b) mutate its `pTargetGroup` membership, (c) change
  `Priority` values (`ai_native.preprocessor_is_stock`; `host_bindings.cc`
  reads weights and the group live each call; no memo covers membership or
  priorities). **Swapping** `pTargetGroup` for a different object loses the
  ENTERED_SET → `TargetEnteredSet` wake registered once on the original group
  (`ai_driver.py:547-584`): so we install the wing group at `CreateAI` time and
  only ever mutate it.
- Popularity is native and **set-wide**: every ship in the set whose target is
  the candidate (`set_index.cc:276-283`).
- `SelectTarget` re-picks every 5 s; `ForceUpdate()` makes it re-pick within
  the AI sleep cap (≤ 4 ticks).
- `ConditionScript_Create(module, cls, …)` imports any dotted name; status is
  pushed with `pCodeCondition.SetStatus(n)` and `ConditionalAI` reacts.
  `ConditionalAI` EvalFuncs must be **pure** (only `App` globals, no closure
  free vars) or the native walker's memo declines them (`ai_driver.py:278-319`).
- `PlainAI.SetScriptModule(name)` imports **`AI.PlainAI.<name>`** with class
  `<name>` (`ai.py:688-708`), silently falling back on failure.
- Project modules in SDK namespaces are served by the claimed-namespace rule
  (`engine/compat/claimed.py`, consulted by both `_SDKFinder`s before mods and
  the SDK). Never create a project-root `AI/` or `Conditions/` package.
- Rated reactor output: `ship.GetPowerSubsystem().GetProperty().GetPowerOutput()`
  (the subsystem's own `GetPowerOutput()` is health-scaled; not used).
- `GameLoop.tick` (`engine/core/loop.py`) runs `gl.ai` then later
  `gl.warp_states`, `gl.shuttles`; no existing 1 Hz service lives there.
- `combat_stress` builds `BasicAttack` trees directly against the mission's
  friendly/enemy groups (no QB plan); `QuickBattleAI` cannot run there.
- Stock manoeuvres used: `FollowObject` (`SetFollowObjectName`,
  `SetRoughDistances`), `Ram` (`SetTargetObjectName`, `SetMaximumSpeed`),
  `Flee` (`SetFleeFromGroup`, `SetSpeed`).

## 3. Architecture

```
engine/wings/                 the wing brain (engine)
  roster.py      Wing, WingMember, registry, ship-name -> wing lookup
  chain.py       chain of command (pure functions)
  assess.py      strength / weakest / spread (pure functions over a snapshot)
  decisions.py   Decision protocol, registry, stock decisions (swarm, regroup)
  brain.py       per-wing tick: snapshot -> chain -> decision -> outputs
  service.py     arm/reset, the GameLoop hook (cadence), switch, log
  dials.py       "wings" dial group
  tree.py        wrap_tree(): adds wing branches above a stock tree
engine/compat/wing_library/   SDK-namespace library modules (claimed)
  DauntlessWings.py                 the SDK-facing surface
  AI/PlainAI/WingRejoin.py          manoeuvre
  Conditions/ConditionWing.py       question (pushed status)
engine/quickbattle/wings_qb.py      Quick Battle consumer
engine/dev_missions/combat_stress.py   second consumer (perf scene)
```

The brain never runs inside an AI tick and never needs an answer from an AI
script: it reads world state on its own cadence and **writes data** (target
group contents, weights, condition statuses, manoeuvre targets) that the stock
AI reads on its own schedule (programme anti-goal: no sim check-ins).

## 4. Wings and membership

- A **wing** is created by a consumer with: an id, a side's **candidate enemy
  group** (the `ObjectGroup` the side's stock AI already targets), member ship
  names in group order, and whether the player belongs to it.
- **Members** are ships whose tree the consumer wrapped with `wrap_tree`
  (mobile attack AI). In Quick Battle that is every ship spawned with
  `QuickBattleAI` / `QuickBattleFriendlyAI`. **(call)** Starbase/station AI
  ships, neutral groups, and ships with no AI are **not** wing members and
  never enter a chain: a station can't anchor a leash. **(ruling)** Members
  must also be **mobile** (impulse engines, max speed > 0). A wing whose
  initial members are all late builds its chain from its first arrival wave.
- ~~The player is a member of the player's group's wing.~~ **Superseded
  (Mark, 2026-11-09):** the player's group is **AI-led** until an orders UI
  exists. Quick Battle puts the player in no wing; the friendly wing's chain
  is built from its AI members only (top 20% by rated power, min 1), its
  anchor is the AI commander, and it never takes the player's target as its
  primary. A player-only group gets no wing. The "player commands" paths in
  `engine/wings` (`is_player`, `DauntlessWings.AddMember(..., bPlayer)`) stay
  for that future orders UI, unused by Quick Battle. `PlayerOrder.group_id`
  stays (it names the player's group).
- Late arrivals (`late_arrivals._spawn_one`) are added to their group's wing
  at spawn (the order carrying `group_id` is in scope there) and get the same
  wrapped tree; they never enter the chain.
- A wing of one is still a wing (its only member commands itself). Harmless,
  and keeps the code path single.

## 5. Chain of command

Exactly programme §4. Implementation notes:

- Computed once when the wing is armed, from rated reactor output (§2). A ship
  with no power subsystem rates 0. Ties keep group order. Candidates =
  `max(1, floor(0.2 · n_members))` where `n_members` counts mobile AI members
  at arming (late arrivals excluded); the player, if a member, is prepended
  and counts as one of them **(call)**.
- **Current commander** = first chain entry whose ship exists, is not dead /
  dying, and is in the wing's set. Re-evaluated every brain tick; a change is a
  **handover** (logged).
- When every chain entry is gone the wing is **leaderless** for the rest of
  the battle (no re-election: losing command is meant to be decisive).

## 6. The brain tick

`service.tick(dt)` is called from `GameLoop.tick` next to `gl.warp_states` (after `gl.ai`), in its own profiler scope **`gl.wings`**, and runs
each armed wing whose game-time accumulator has passed `brain_period_s`
(default 1.0). Wings are **phase-staggered** (wing *i* starts at
`i / n_wings · period`) so 16 wings don't all run on the same tick **(call)**.
Paused game time pauses the brain.

Each tick of one wing:

1. **Snapshot** (one pass): live members (position, hull fraction, shield
   fraction, rated power), the anchor (§7), candidate enemies from the side's
   enemy group that are alive, in the wing's set and **not cloaked or
   cloaking** (position, hull, shield, rated power, which wing they belong to
   if any, whether they command it). **(ruling)** A cloaked ship is never a
   candidate: stock SelectTarget skips it, so a group of only cloaked ships
   idled the wing; it is back the tick after it decloaks.
2. **Chain:** resolve the current commander; detect handover / leaderless.
3. **Leaderless?** → §10, stop.
4. **Score decisions** (§8) and pick one with stickiness.
5. **Apply**: rebuild the wing target group (§9), push condition statuses and
   rejoin targets (§7), `ForceUpdate` members' `SelectTarget` only when the
   primary target changed.

## 7. Cohesion: anchor, leash, regroup, rejoin

- **Anchor** = the current commander's ship (the player's ship when the
  player commands).
- **Leash** = `leash_gu` (dial, default **200 GU**, BC's mid band).
  **Slack** = `leash_slack_gu` (default **100 GU**) **(call)**.
- Per member, a **rejoin** flag with hysteresis: set when distance to anchor
  > `leash_gu + leash_slack_gu`; cleared when < `leash_gu`. The slack is what
  stops a follower mid torpedo run being yanked back the instant it crosses
  the line.
- **Regroup decision** (§8): when chosen, every member farther than
  `regroup_gather_gu` (default **100 GU**, BC's close band) from the anchor gets
  the rejoin flag until it is inside that distance.
- **The commander never rejoins** (it is the anchor).
- **Rejoin behaviour** (library manoeuvre `WingRejoin`): stock `FollowObject`
  semantics toward the wing's **current** anchor (it reads the anchor name from
  the wing each update, so a handover retargets it with no tree surgery),
  wrapped in stock `AvoidObstacles`.

## 8. Decisions (Phase A set)

A **Decision** is a library object: `name`, `score(ctx) -> float`,
`apply(ctx)`. The registry is open (`DauntlessWings.RegisterDecision`), so
later phases and mods add entries without touching the brain. Each tick the
brain scores every registered decision; the current decision gets
`+stickiness` (dial, default **0.25**); highest wins; ties keep the current
one. (Phase B: a current decision scoring 0 gets no bonus and does not win
ties — see the Phase B spec §5.)

Phase A registers three:

| Decision | Score | Effect |
|---|---|---|
| `regroup` | `2 · fraction of members beyond leash+slack` (so > 0.5 of the wing strayed ⇒ beats anything scoring ≤ 1) | §7 gather; target group still built (members not rejoining keep fighting) |
| `swarm_weakest` | `1.0` if our strength ≥ `odds_ratio` (dial, default **0.8**) × their strength, else `0.4` | primary = weakest candidate (§9) |
| `swarm_commander` | `1.0` if our strength < `odds_ratio` × theirs **and** an enemy commander is a candidate, else `0.3` | primary = nearest enemy wing's commander; secondaries = its two nearest wingmates |

**Strength** of a ship = rated power × hull fraction × (0.5 + 0.5 · mean
shield fraction) **(call)**; a side's strength = sum over ships within
`engage_gu` (dial, default **350 GU**, BC's long band) of the anchor.
**Weakest** = lowest strength among candidates within reach (§9).

**Don't chase (#6) is a standing rule, not a decision:** it is how the target
group's candidate set is cut (§9), so it applies under every decision.

## 9. The wing target group (swarm + don't chase + the perf lever)

One `ObjectGroupWithInfo` per wing, installed as every member's
`SelectTarget.pTargetGroup` at `CreateAI` time and only ever mutated.

Rebuilt each brain tick:

- **Reach set** = candidate enemies (**ruling:** the enemy group ∪ the
  km-listed names for the side) within `leash_gu` of the anchor.
  Each enters at `Priority` 0.0 — or its `km_targeting` priority if the
  ship is a listed protect/hunt target (QB victory conditions keep working).
  **(ruling)** A km-listed ship in reach becomes the primary (the decision's
  pick drops to a secondary; a commanding player still overrides).
- **Primary** (from the decision) gets `Priority` **3.0**; up to two
  **secondaries** get **1.5** **(call)**. Primary/secondaries are chosen
  from the reach set.
- **Don't chase:** an enemy outside the reach set is **not in the group**, so
  no member picks it; one that runs off is dropped at the next tick.
- **Nothing in reach:** the group holds only the **nearest** candidate enemy,
  at `Priority` 3.0. The commander (whose own SelectTarget reads the same
  group) heads for it and the leash pulls the wing along: the wing advances as
  a body instead of scattering after separate targets.
- **Player commanding:** the player's current target, if it is a candidate
  enemy, is the primary regardless of decision. **(ruling)** In every case,
  even outside reach. **(ruling)** When the player commands, nothing is in
  reach and its target is not a candidate, the group is **empty** (not the
  nearest) and every non-player member beyond `regroup_gather_gu` gets the
  rejoin flag: the escorts form up on the player instead of charging an
  enemy the leash yanks them back from.

**Wing members' SelectTarget weights** (set once at wrap time via the stock
`SetRelativeImportance`): stock values except **popularity = `wing_popularity`**
(dial, default **−0.3**, stock −1.1) **(call)**. **(ruling)** Only
`fPopularityFactor` is touched (original saved and restored on leaderless);
the player's own SelectTarget is never weighted. With a 1.5 priority gap and
distance worth ≤ 1.0, a wing piles onto its primary but overflows to a
secondary at about five attackers — swarm without a 25-ship scrum. Self-defence
is kept: an enemy in reach that is shooting a member still rates through
stock's damage-dealt factor.

**Why this is the perf lever:** each member rates the reach set (local
enemies) instead of the side's whole enemy list, and the brain computes
strength/weakness once per wing per second instead of every ship
re-deriving it. Whether this lowers `gl.ai` at 128 ships is **measured, not
assumed** (§11).

## 10. Leaderless and desperation

When a wing becomes leaderless:

- the wing target group is **refilled with every candidate enemy** at
  Priority 0 (km priorities kept), members' weights are restored to stock
  (`SetRelativeImportance()` defaults), rejoin flags cleared: ships fight
  like stock BC again;
- **desperation**: each brain tick (the brain keeps ticking a leaderless wing
  at the same cadence, doing only this), a member whose hull fraction is below
  `desperate_hull` (dial, default **0.4**) and not yet desperate rolls once
  (seeded per wing, deterministic): `ram_chance` (dial, default **0.3**) ⇒
  **Ram** its current target (stock `Ram`, full speed); otherwise **Flee**
  from the enemy group (stock `Flee`) **(call)**. The choice is permanent for
  that ship. Both are wing branches (§11 tree) driven by pushed conditions.

## 11. The wrapped tree, library surface, consumers

**Tree** (`engine.wings.tree.wrap_tree(pShip, pStockTree, wing)`), returned in place of
the stock tree:

```
PriorityList
  1  Conditional[ConditionWing(ship, "ram")]     -> Ram(current target)
  2  Conditional[ConditionWing(ship, "flee")]    -> Flee(enemy group)
  3  Conditional[ConditionWing(ship, "rejoin")]  -> AvoidObstacles(WingRejoin)
  4  <stock tree, unchanged>
```

All conditions are pushed by the brain (status 0/1), EvalFuncs are the pure
`ACTIVE if b else DORMANT` form. The stock tree keeps its own preprocessors
(SelectTarget, FireScript, AvoidObstacles, power, alert) native as before.
`wrap_tree` finds the stock tree's `SelectTarget` instance(s) (walk the tree's
`PreprocessingAI` nodes for a stock `SelectTarget`) and records them on the
member for weights and `ForceUpdate`.

**Library modules** (served by the claimed-namespace rule; extend
`claimed.py` to allow a claim that maps a dotted name to a single `.py` file):

- `DauntlessWings` — `CreateWing(...)`, `AddMember(...)`, `WrapTree(pShip,
  pTree)`, `GetWing(shipName)`, `GetCommander(shipName)`, `IsCommander(name)`,
  `IsLeaderless(shipName)`, `GetWingTargets(shipName)`,
  `RegisterDecision(decision)`. Modern Python. Documented in the module
  docstring (that is the modder-facing doc for now).
- `AI.PlainAI.WingRejoin` — class `WingRejoin`.
- `Conditions.ConditionWing` — class `ConditionWing(pCodeCondition, sShip,
  sKind)`; registers itself with the wing so the brain can push status.

**Quick Battle consumer** (`engine/quickbattle/wings_qb.py`):

- Armed from `battle_end.begin` next to `km_targeting.arm` (always, not only
  when there are listed ships); builds name → group from the plan
  (`naming.object_name`), creates one wing per non-neutral group, wraps the QB
  AI modules' `CreateAI` (same wrapper pattern as km_targeting, composed with
  it: when wings are on, the wing module supplies the `FromModule` redirect,
  returning the **wing's** group, and copies km priorities into it).
- `late_arrivals._spawn_one` → `wings_qb.ship_arrived(order, name)`.
- Reset from `battle_end.reset` and `reset_mission_state`.

**combat_stress consumer:** new env `DAUNTLESS_COMBAT_WING_SIZE` (default **0**
= no wings, so every existing capture command means what it meant). With N >
0, each side is split into wings of N in ring order and each tree wrapped via
`DauntlessWings`.

**Home set (ruling):** the wing's home set is the set holding most live
non-player members, and a commander must be in it. **(ruling)** While command
is alive but away (no chain entry in the home set), the wing is
**temporarily leaderless, not latched**: the group gets every candidate at
stock priority (`leaderless_priorities`), each member's popularity is
restored, rejoin is pushed off for every member in any set, SelectTarget is
forced once on entering; no desperation rolls. When a chain entry is home
again normal ticking resumes. In a normal tick a member outside the home set
is pushed rejoin off too (WingRejoin cannot reach a commander in another
set).

**Switch:** `DAUNTLESS_WINGS=0` disables wings everywhere (consumers don't
arm, trees are stock); `service.enabled()` is that env check only. Otherwise
on in Quick Battle, per battle: **(Mark's ruling 2026-11-09, replaces the
Developer Options toggles)** the Quick Battle setup screen's victory
(battle settings) view has a **"Wing commanders"** On/Off row ("Groups pick
leaders and fight together"), stored as `Scenario.wings` (default on, saved
with presets; a preset without the key loads on), carried as
`BattlePlan.wings`, and read by `wings_qb.arm` at battle start. Armed wings
keep ticking until reset. `service.tick` reads only the env and the armed
list.

**Diagnostics:** `DAUNTLESS_WINGS_LOG=1` prints `[wings]` lines to stderr on
arm, handover, decision change, leaderless, desperation. **(Mark's ruling
2026-11-09, replaces the dev-only ★ toggle)** The target list always marks
each wing's current commander with a small inline **command chevron** before
the name (a row's `commander` flag), for everyone, no toggle. It moves on a
handover and disappears when a wing goes leaderless.
**Focus marker (Mark, 2026-11-09):** the player's own group's wing's current
primary (`service.player_focus()`) gets a crosshair with a filled centre dot
(a row's `focus` flag), after the chevron. None when that wing is
leaderless, away or has no primary, or the player's group has no wing.

**Dials:** group `"wings"` on `/ L O` (pattern `engine/appc/sensor_dials.py`):
`leash_gu`, `leash_slack_gu`, `regroup_gather_gu`, `engage_gu`,
`wing_popularity`, `stickiness`, `odds_ratio`, `desperate_hull`,
`ram_chance`, `brain_period_s`. All read at use.

## 12. Calls made without Mark (review at play test)

1. Stations / starbase AI and neutrals are never wing members.
2. ~~Player counts as one of the 20% when in a group.~~ Superseded: the
   player's group is AI-led until an orders UI exists — Mark 2026-11-09 (§4).
3. Leash slack 100 GU; regroup gathers to 100 GU.
4. Strength formula; weakest = lowest strength.
5. Swarm strategy chosen by odds (≥ 0.8 of their strength ⇒ weakest, else commander).
6. Target priorities 3.0 / 1.5 / 0; popularity −0.3 for wing members.
7. Desperation: below 40% hull, 30% ram else flee, rolled once, permanent.
8. Brain at 1 Hz, wings phase-staggered.
9. ~~A dev-only ★ commander marker in the target list for play-testing.~~
   Replaced (Mark's ruling 2026-11-09): an always-on command chevron in the
   target list, and the Wing AI switch moved to the Quick Battle setup
   screen ("Wing commanders"); the Developer Options toggles are gone (§11).
10. Members must be mobile (impulse engines, max speed > 0).
11. A wing whose initial members are all late builds its chain from its first
    arrival wave.
12. A km-listed ship in reach is the primary; a commanding player's target is
    the primary even outside reach. (The "player commands" rules are
    reachable only via DauntlessWings `bPlayer`, see §4, not Quick Battle.)
13. Only `fPopularityFactor` is touched; the player's SelectTarget is never
    weighted.
14. Home set = the set with most live non-player members; away command makes
    the wing temporarily leaderless (stock targeting, no latch, no
    desperation).
15. Cloaked / cloaking enemies are never candidates.
16. A commanding player with nothing in reach and no candidate target: empty
    group, escorts gather on the player.
17. The focus marker shows the primary only, not secondaries, as a crosshair
    with a filled centre dot (distinct from the outline hunt-target marker).

## 13. Testing

- **Unit (pure):** chain sizes (1, 4, 9, 10, 25 members; ties; player
  prepended; no power subsystem), handover order, leaderless latch; strength /
  weakest / spread; decision scoring + stickiness; target-group rebuild
  (reach set, priorities, km merge, nothing-in-reach, player primary); rejoin
  hysteresis; desperation determinism.
- **Integration (headless):** a QB battle plan with two groups a side runs
  through `battle_end.begin`: wings armed, trees wrapped, every member's
  `SelectTarget` shares the wing group and stays on the native path (the
  `ai native:` counters show no Python ratings), late arrival joins, reset on
  end and on mission swap leaves no wing state.
- **Behaviour (headless, slow — may be deep tier):** `combat_stress`, wing
  size 4, 18000 ticks per arm: asserts ON < 0.6 × OFF p90
  member-to-commander distance (the claim), and ON < 450 GU as a sanity
  bound only (the scene is nondeterministic run to run).
- **Off means off:** with `DAUNTLESS_WINGS=0` the trees are byte-for-byte the
  stock trees (same node types/order) and no `gl.wings` work runs.
- Tree guards as always (`tests/docs`, path indirection, install-write,
  gate tiers).

## 14. Phase-end checks (programme §8)

- **Perf A/B**, Debug worktree build, headless, one build, interleaved
  off/on/on/off, 90 s cool-downs, 1500 frames,
  `DAUNTLESS_MISSION=engine.dev_missions.combat_stress
  DAUNTLESS_COMBAT_SHIPS=128 DAUNTLESS_COMBAT_WING_SIZE=8 DAUNTLESS_DEV_VIEW=bridge`
  with `DAUNTLESS_WINGS=0` vs unset; scoring per runbook
  (`native-motion/phase0-runbook.md` §1). **Pass:** on-side
  `gl.ai + gl.wings` ≤ off-side `gl.ai` beyond run-to-run spread; Phase A's
  goal is a reduction. Anything beyond spread in the wrong direction → review
  before moving on. Frame time reported with the "more ships in range" caveat.
  Recorded as perf-register signals.
- **Merge gate** `scripts/gate_merge.sh`, read from its artefact log.

## 15. Acceptance criteria for Mark's play test

1. **One battle.** In a Quick Battle with two groups of 5+ ships a side, after
   three minutes the fight is still in one area: wing members stay within
   roughly mid range (~35 km) of their commander, instead of the 100 km+
   spread with "Wing commanders" Off.
2. **Focus.** Most of a wing shoots the same one or two targets at a time and
   moves on together when one dies; the chevron in the target list shows who
   commands each wing.
3. **Command matters.** Destroying a wing's commander hands command to the
   next strongest ship (the chevron moves); destroying all of a wing's top 20% makes the
   survivors fight on their own, and badly damaged ones flee or ram.
