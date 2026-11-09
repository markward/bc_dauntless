# Wing leaders — Phase C: fighting smarter

Date: 2026-11-09. Builds on the programme spec and Phases A and B (read
Phase A §2 for the engine facts and §11 for the wing tree, and Phase B §6 for
`WingMoveTo`). Branch `feat/wing-leaders-c`, cut from the end of
`feat/wing-leaders-b`. Mark asked for this phase to be built without his spec
approval. Every choice he didn't make is marked **(call)** and listed in §9.

## 1. What Phase C delivers

Three items from the programme table (§6), added to the decision registry.
Earlier phases are extended, not rewritten.

- **#9 Flank and shield-face focus.** Members take attack positions around
  the wing's primary *while firing*:
  - **focus a face:** concentrate on the shield face that is down;
  - **envelop:** spread around the primary so it can't keep its strong face
    toward everyone.
- **#10 Disable before destroy.** Against a much stronger ship, the wing
  knocks out its weapons first, then kills it.
- **#11 Hold a reserve.** A large wing keeps one healthy ship back and commits
  it where the fight tips.

## 2. Facts this design rests on (verified 2026-11-09)

**Stock `FireScript`** (SDK `AI/Preprocessors.py:40`):
- **Construction.** `FireScript(sTargetName, **kw)` takes the target by
  **name**. Weapons are added with `AddWeaponSystem(pSys)` for the ship's
  torpedo, phaser and pulse systems; with none added it fires nothing.
- **Shape.** It is a `PreprocessingAI` around any child. SDK
  `AI/Player/DisableFromSide.py:39-45` wraps it round `AvoidObstacles` around a
  movement PlainAI.
- **Native path.** It stays native when stock (`ai_native.preprocessor_is_stock`
  checks only the instance class). Don't shadow its methods on the instance.
- **Retarget and aim.** `SetTarget(sName)` retargets it. Its aim cone
  (`fFireDotThreshold`, about 10°) gates only aimed weapons with direction
  info (torpedoes, `CheckGoodShot`); phasers fire on their own arcs.

**Subsystem aim:**
- `FireScript(..., TargetSubsystems=[(CT_x, priority)], DisableOnly=0|1)`.
  The **higher** priority number is targeted first (`AddTargetSubsystem`
  inserts in descending order; SDK `AI/Player/DisableFromSide.py` lists
  `(CT_WEAPON_SYSTEM, 1)` above `(CT_CLOAKING_SUBSYSTEM, 0)`).
- **Runtime switch.** Stock `IgnoreSubsystemTargets()` empties the list
  (hull aim) and `RestoreSubsystemTargets()` puts it back. SDK
  `Bridge/TacticalMenuHandlers.py:1761-1772` uses exactly this for the
  player. The native FireScript re-reads `lTargetSubsystems` from the
  instance on every call (`host_bindings.cc` `s_lTargetSubsystems`), so the
  switch works on the native path.
- **Stock attack flags, never `SetAttackDisabled(0)`** (as built,
  de1a14088). With it, a fire frame with no subsystem chosen (hull aim, a
  fresh target) reaches the SDK's `WeaponTooDangerous`, which calls
  `pSubsystem.GetCondition()` on None: every torpedo frame raised, the weapon
  cycle stuck and the attack branch never fired. Its `DisableOnly` partner
  `SetAttackWithoutValidSubsystems(0)` is no fix: a fresh target never
  reaches its choose frame. Not needed either: stock
  `ChooseTargetSubsystem` already picks among the non-disabled subsystems
  while any is left (SDK `AI/Preprocessors.py` ~846, `lNonDisabled`), and
  `bAttackIfNoSubsystemsLeft` stays 1, so with nothing left it shoots the
  hull.
- **Where weapons-first aim lands (measured, Task 6).** Every stock weapon
  system is `SetTargetable(0)` with targetable banks/tubes. For such a system
  the SDK's `ChooseTargetSubsystem` appends the **system itself** once per
  live child (`lpPossibleTargets.append(pSubsystem)`, not `pTarget`), so the
  aim and the damage land on the system's **own** condition. Its
  `IsDisabled()` is the banks' aggregate (`weapon_subsystems.py`), so it never
  reads that damage. At 0 the system is silent (a Warbird with its three
  systems zeroed hit an Akira 0 times in 60 s, against 22-27) and FireScript
  stops choosing it (`GetCondition() > 0`). So the wing reads a weapon system
  as down when `IsDisabled()` **or** its own condition is 0
  (`brain._weapons_down`). Four Galors on a still Warbird: weapons down at
  ~235 s, `IsDisabled()` never all true.
- The engine copies the chosen subsystem onto the ship in
  `ai_driver._sync_fire_script_target_subsystem`. This only holds while
  **`ship.GetTarget()` names the same ship as the FireScript target**;
  otherwise aim reverts to the hull.

**Stock attack keywords.** QB's `QuickBattleAI` builds `BasicAttack` with
`Difficulty = QuickBattle.GetCurrentAILevel()`. `BasicAttack.CreateAI`
turns that into flags with `SetFlagsFromDifficulty(prefix, dKeywords)`
(prefix from `App.Game_GetDifficulty()`), and `FedAttack` builds every
FireScript as `apply(FireScript, (sTarget,), dKeywords)` and then adds the
torpedo, phaser and pulse systems.

**Shield faces:**
- Per-face fraction: `ship.GetShields().GetSingleShieldPercentage(face)`.
- Face constants: FRONT 0, REAR 1, TOP 2, BOTTOM 3, LEFT 4, RIGHT 5.
- Body axes: FRONT +Y, REAR −Y, TOP +Z, BOTTOM −Z, LEFT −X, RIGHT +X.
- World direction of a face = `R · axis` with `R = GetWorldRotation()`. Its
  columns are the body axes.

**Ranges:**
- Stock attack bands are close ~100–150, mid ~200 and long 350 GU.
- Phaser full damage is within ~60–70 GU. The engine's firing gate is 700 GU.

## 3. The attack branch (shared by #9 and #10)

A new wing branch, **`attack`**:

```
Conditional[ConditionWing(ship, "attack")]
  -> PreprocessingAI "WingFire" (stock FireScript instance, owned by the wing)
       -> PreprocessingAI AvoidObstacles
            -> PlainAI WingMoveTo
```

**The wing's FireScript instance.**
- It is built at `wrap_tree` time per member exactly as `FedAttack` builds
  one: `apply(FireScript, (name,), dKeywords)` then `AddWeaponSystem` for
  each of the torpedo, phaser and pulse systems that exist. `dKeywords` are
  the stock attack's: the consumer passes them (QB: `Difficulty` from
  `QuickBattle.GetCurrentAILevel()` through `SetFlagsFromDifficulty`); with
  none, `{"Difficulty": 0.5}` through the same function.
- It is also given `TargetSubsystems=[(CT_WEAPON_SYSTEM, 1)]`, then
  `IgnoreSubsystemTargets()`, so it starts in hull mode. Its attack flags
  stay stock in both modes; `SetAttackDisabled(0)` was dropped during the
  build because it crashed hull-mode fire (§2).
- The brain retargets it with `SetTarget(name)` when the member's attack
  target changes. **(call)** The brain also calls `ship.SetTarget(name)` so the
  engine's subsystem aim sticks (§2). This is the only new ship-state write in
  Phase C, and it is the same write stock SelectTarget makes.
- Weapons-first mode (#10) is `RestoreSubsystemTargets()`; hull mode (#9) is
  `IgnoreSubsystemTargets()`. Both are called only on a change.

**`WingMoveTo` gains slots.**
- `Member.slot`: `(target_name, body_dir, standoff_gu)` or None. With a slot,
  every Update (0.2 s) computes the point from the target's **live** pose,
  `target_pos + R · body_dir · standoff`, instead of reading `move_point`. A
  slot fixed in the target's frame sweeps at up to ~36 GU/s when a ship turns
  at 0.3 rad/s 120 GU away; a 1 Hz point would always be behind it.
- Within the slot radius, `min(20, 0.25 × standoff)` GU, of the slot point
  it enters **hold mode** and leaves it only past twice that (48 GU
  standoff: 12 in / 24 out; 80 GU: 20 / 40) (`Member.slot_hold`; the brain
  clears it when the slot changes). The approach slow-down uses the same
  radius.
  Holding, it turns toward the target and thrusts only by the slot offset
  along its nose, `clamp(dot(forward, slot − here) / 20, 0, 1)`: nothing
  when the slot is behind or beside it (§11). On the way the nose points at
  the slot, and FireScript fires whenever the target happens to be in its
  cone.
- A missing or dead slot target falls back to `move_point` (stop if None).

**Slot geometry.** A slot is the target position + `R · dir · d`, with
`R = target.GetWorldRotation()`:
- `dir` is a unit vector in the target's body frame;
- `d` is the holder's own standoff (§11 ruling 4):
  `clamp(0.8 × r, attack_standoff_min_gu, attack_standoff_gu)` (dials,
  defaults **25** and **80 GU**), where `r` is the smallest
  `GetMaxDamageDistance` over its phaser and pulse banks (tractors and
  torpedoes excluded), cached on the member at wrap; no such banks →
  `attack_standoff_gu`. Under focus_face and envelop the floor is raised
  to `attack_flank_min_gu` (default **60 GU**); disable keeps the pure
  beam-range standoff. Slots are assigned on points at `attack_standoff_gu`.

**Who takes slots.**
- Up to `attack_slots` members (dial, default **3**).
- They must be alive, not the commander, not the player, not guards, not
  fallers and not reserves.
- Nearest to their slot first, with greedy assignment. A holder keeps its
  slot while the primary and the slot set are unchanged; only vacated slots
  are refilled (§11). More holders than directions (disable) get each wrap
  of the directions turned a further 25°, so no two share a point.
- **(call)** The commander keeps the stock tree, so it anchors the wing.

**Exclusivity.**
- Slot-holders are exempt from rejoin (their slot hangs off the primary, which
  is inside reach).
- Branch order:
  1. ram
  2. flee
  3. withdraw
  4. guard
  5. fallback
  6. **reserve**
  7. **attack**
  8. rejoin
  9. stock

## 4. Flank / shield-face focus (#9)

Two new decisions. Both choose their primary the way swarm does: the decision
the two swarm decisions would pick, with the same odds rule. They add slots on
top.

**`focus_face`.**
- **Score 1.2** when all of these hold **(call)**:
  - the primary is in reach;
  - its weakest face is below `face_weak` (dial, default **0.3**);
  - the mean of its other faces is ≥ 0.6;
  - at least 2 members are eligible for slots.
- **Slots:** the weak face's axis, spread on a ±25° arc about it, one per
  slot-holder.

**`envelop`.**
- **Score 1.05** (just above swarm) when all of these hold **(call)**:
  - no face is below `face_weak`;
  - the primary's mean shield is ≥ 0.5;
  - at least 3 members are eligible.
- **Slots:** the REAR, LEFT and RIGHT axes (for 3 slot-holders; more get TOP
  and BOTTOM).
- The target can face only one of them at a time.

**When focus switches on and off.** Focus stops when the face recovers to
≥ `face_weak + 0.2`, or when the primary changes. Stickiness keeps it from
flapping.

## 5. Disable before destroy (#10)

**`disable`.**
- **Score 1.3** when all of these hold **(call)**:
  - the strongest enemy in reach has strength ≥ `disable_threat` (dial,
    default **1.5**) × our strongest member;
  - its weapon systems are not all down. A torpedo, phaser or pulse system
    that exists is down when `IsDisabled()` or its own condition is 0
    (§2 "Where weapons-first aim lands").
- **Choice:**
  - the primary is that ship;
  - **every** slot-eligible member, not just `attack_slots`, takes an attack
    assignment with weapons-first subsystem aim, on the slots `envelop` would
    use.
- **Latched** once running: it stays on the same target (the wing's
  primary) while that is alive, in reach and its weapons are up. The
  strength ratio is not re-checked: stripping the shields alone halves it
  (§11).
- **Ends** when all its weapon systems are down. The score drops to 0 and
  swarm takes over; it is now the weakest or a commander target, and the
  wing kills it. It also ends after `disable_max_s` (dial, default
  **300 s**) on one target. A disable that ends with the target still alive
  marks it done: disable never re-enters against it.
- **(call)** Engine-disabling a fleeing ship is not in this phase. It conflicts
  with Phase A's don't-chase, which drops runners anyway. This is noted for
  later.

## 6. Hold a reserve (#11)

A **standing rule**, like rotate.

**Who.**
- At arming, a wing with ≥ `reserve_min_wing` (dial, default **5**) live
  non-player members holds **one** member in reserve **(call)**: the healthiest
  non-commander member. **Ruling (build):** among equally healthy members, the
  lowest power, then the name.
- A late wave's wing (chain from its first arrival wave) applies the rule when
  its first wave arrives.

**Where.**
- Reserve point: `reserve_gu` (dial, default **150 GU**) farther from the
  enemy centroid than the anchor, **on the reserve's own bearing** from the
  centroid (`reserve.hold_point`; on the anchor's bearing if the reserve sits
  on the centroid). It is not "behind the commander": it holds on its own
  bearing, `reserve_gu` farther from the enemy than the commander.
- **Changed in Task 6.** The first formula, `anchor + unit(anchor −
  enemy_centroid) × reserve_gu`, swings round with a commander circling the
  enemy: at 100 GU from the centroid and 6.6 GU/s it moves ~16 GU/s at the
  reserve's range, faster than any ship of the wing. The reserve chased it
  and drifted in: six Akiras vs two Warbirds, it was farther from the enemy
  than its commander on only 68-69% of held samples over 85 s, and in front
  of it from ~60 s. With its own bearing it only moves in and out: 100%, ≤
  20 GU from its point from 20 s. ⚠️ Not Mark's call yet.
- Recomputed each tick. With no enemies in reach, the reserve just holds near
  the anchor through the same point formula, using the last centroid, or the
  anchor itself if there was never one.
- It runs the `reserve` branch → `AvoidObstacles(WingMoveTo)` and does not
  fire.

**Commits** permanently, once, on the first of these **(call)**:
- a wing member dies;
- Protect becomes the decision;
- the wing primary's hull is < 0.3 (finish it);
- our strength in reach ≥ 2 × theirs (pile on), with at least one enemy in
  reach (**ruling, build**: 2× nothing is no advantage);
- `reserve_max_s` (dial, default **90 s**) has passed.

**Rulings (build):** it also commits on "command" (the reserve becomes the
commander) and "gone" (it died or left the home set): spent either way.

Committed, it is an ordinary member.

**Stand-down.** Leaderless or command away stands the reserve down and commits
it. A wing without command doesn't hold anything back: **ruling (build)**, the
stand-down spends the reserve even when none is held, so a later re-arm never
picks one.

## 7. Perf

- Slot geometry is per slot-holder per tick, which is small.
- The wing FireScript is a stock instance on the native path.
- A face read is 6 per primary per tick.
- Same A/B rule as before: compare with SIG-225 and with the Phase B
  measurement.

## 8. Testing

**Unit (pure).**
- Slot geometry: the face axis to a world point, the ±25° arc, and the
  envelop face set.
- Weakest-face detection.
- `focus_face`, `envelop` and `disable` scoring gates.
- Greedy slot assignment.
- Reserve pick, commit triggers and their permanence.

**Host.**
- The attack branch contains a stock FireScript with weapons added, and it
  stays native.
- `WingMoveTo` faces `face_name` at the slot.
- A slot-holder ends up within 40 GU of its slot and facing the target.
- Subsystem aim:
  - in disable, the member's `GetTargetSubsystem()` becomes one of the
    target's weapon systems;
  - aim survives the engine sync (`ship.GetTarget()` matches).
- The reserve holds farther from the enemy than the commander and commits
  on a member death.

**Behaviour (headless, generous bounds, 3 runs).**
- (a) Focus-face: with a target's LEFT face forced to 0.1, at least 2
  slot-holders end up on the LEFT side of the target, in the target's body
  frame.
- (b) Disable: against a much stronger ship, its weapon systems go down
  (§5) before its hull drops below 50%.
- (c) Reserve: the reserve stays farther from the enemy than the commander
  until a member dies, then closes.
- Built as `tests/host/test_wings_phase_c_behaviour.py`, each against a
  control with the behaviour dialled off. (b)'s target holds still: fighting
  back, one run in three let the commander drift past the 200 GU leash for
  ~2 min, which turns disable off. (c) closes "≥ 50 GU within 25 s of the
  loss": a held reserve sits ~140 GU farther out and must turn about first.

## 9. Acceptance criteria for Mark's play test

1. **Flanking.** When an enemy's shield face is down, several ships of the
   wing swing round to that side and pour fire into it. Against a healthy
   target they spread round it instead of all coming in from the same side.
2. **Disable first.** A wing facing a much bigger ship goes for its weapons
   first. Its weapons go offline before it's destroyed. Then the wing finishes
   it.
3. **Reserve.** A wing of 5+ keeps one healthy ship back behind its commander
   at the start. It joins the fight when the wing loses a ship, needs to
   protect someone, or the target is nearly dead.

## 10. Calls made without Mark

1. Attack standoff 120 GU, superseded by §11 ruling 4 (each holder's own
   beam range). Up to 3 slot-holders (disable uses all eligible
   members). The commander never takes a slot.
2. The brain sets `ship.SetTarget` for slot-holders, so subsystem aim sticks.
3. `focus_face` score 1.2 needs a face < 0.3 with the others ≥ 0.6. Slots sit
   on a ±25° arc about it.
4. `envelop` score 1.05 needs mean shields ≥ 0.5 and 3+ eligible members.
   Slots are REAR, LEFT, RIGHT, then TOP, BOTTOM.
5. `disable` score 1.3 against an enemy ≥ 1.5× our strongest, weapons first.
   Engine-disabling runners is deferred.
6. Reserve: wings of 5+, one ship held on its own bearing, 150 GU farther
   from the enemy than the commander. It commits
   once on loss, protect, near-kill, a 2× advantage or 90 s.
7. Branch order: ram, flee, withdraw, guard, fallback, reserve, attack,
   rejoin, stock. Slot-holders are exempt from rejoin.

## 11. Build rulings (final review, 2026-11-09)

1. **Disable latches (I1).** A running disable holds its target while it is
   alive, in reach and its weapons are up, without re-checking the strength
   ratio. Before, Akira ×4 vs a Warbird (1.88×) left disable at 103 s with
   the weapons up, and they never went down. The cap `disable_max_s` was
   ruled at 120 s; measured, the weapons went down at 179–267 s (that
   scene, 3 seeds; 224–270 s with ruling 3's hold mode) and 235 s
   (behaviour test (b)), and at 120 s none did, so it defaults to
   **300 s** (accepted as the measured value). With ruling 4's standoff the
   weapons go down at 133–160 s (Akira ×4 vs Warbird) and 166 s ((b)). A
   target done by the cap, or by any end but its death, is never disabled
   again.
2. **Slot incumbency (I2).** A previous holder keeps its slot index while
   the primary and the slot set are unchanged; only vacated slots are
   filled nearest-first. Same-primary swaps over 120 s: 20–32 → 0–3.
3. **WingMoveTo holds the slot (I3).** Hold mode in at 20 GU, out at 40 GU;
   holding, it faces the target and thrusts only by the slot offset along
   its nose. Against a still target: on the slot and facing it 0.48 → 0.92
   of samples. Against a target that turns, its body-frame slot sweeps
   faster than an Akira flies, and the dwell barely changes.
   Holding exposed the fixed 120 GU standoff (§10 call 1): far past the
   beams' full-damage distance, so behaviour test (b) failed 3 of 3
   (weapons never down in 600 s). Driving through the slot had hidden it,
   bringing holders in to ~95 GU on average. Ruling 4 fixes the standoff.
4. **Slot standoff from each holder's beam range.** Each holder's standoff
   is `clamp(0.8 × r, attack_standoff_min_gu (25), attack_standoff_gu
   (80))`, `r` its smallest phaser/pulse `GetMaxDamageDistance`: Akira
   60 → 48 GU, Warbird 40 → 32 GU, Galor 30 (Forward Beam; its other beams
   40) → 25 GU, Bird of Prey 100 → 80 GU. Test (b): weapons down at
   166 s, hull below half at 192 s (3 seeds). Against a still target the
   holders are on the slot and facing it on 0.72 of samples (0.54 at
   120 GU, 0.17 before hold mode). ⚠️ **Open:** behaviour test (a)
   (focus face against a Bird of Prey that turns and fights back) fails 2
   of 3 seeds at the Akira's 48 GU: ≥ 2 holders on the weak side on 0.35 /
   0.93 / 0.07 of samples (bound 0.7). The same scene at a fixed 80 GU gives
   0.93 / 0.93 / 0.87, and at 120 GU 0.33 / 0.93 / 0.93. Scaling the
   hold hysteresis with the standoff (in at `min(20, 0.25 × standoff)`,
   out at twice that) left (a) at 0.35 / 0.93 / 0.07. A 60 GU floor for
   focus_face and envelop (`attack_flank_min_gu`; disable keeps its pure
   beam-range standoff) gives 0.22 / 0.93 / 0.87: seed 1 still fails.
   Re-bounding (a) or raising the floor is a ruling still owed.
5. **Minors.** Repeated disable directions are turned 25° per wrap; Regroup
   does not count last tick's slot-holders or the held reserve as strays; a
   failed QB difficulty read is logged once (`DAUNTLESS_WINGS_LOG=1`).
