# Wing Leaders Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quick Battle groups fight as wings: a 1 Hz wing brain with a chain of command feeds stock BC AI a per-wing target group and leash/regroup/desperation branches, so battles stay in one place.

**Architecture:** `engine/wings/` holds pure planning (chain, assessment, decisions, target/rejoin plans) and thin glue (snapshot from the live world, apply to target groups and pushed conditions). SDK-namespace library modules (`DauntlessWings`, `AI.PlainAI.WingRejoin`, `Conditions.ConditionWing`) are served from `engine/compat/wing_library/` by the claimed-namespace rule. Quick Battle and `combat_stress` are the two consumers. Stock `SelectTarget` stays on its native path: we only mutate its weights and its (shared) target group.

**Tech Stack:** Python 3.11 engine shim (`engine/appc`), BC SDK AI scripts, pytest (headless `_dauntless_host`).

**Spec:** `docs/superpowers/specs/2026-11-09-wing-leaders-phase-a-design.md` (and the programme spec it builds on, `2026-11-09-wing-leaders-programme-design.md`). Executors read both.

## Global Constraints

- Work only in the worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/wing-leaders`, branch `feat/wing-leaders-a`. Use plain `uv run` (never `--active`).
- ⛔ Never run `scripts/gate_merge.sh`, `scripts/gate_full.sh`, `scripts/check_tests.sh`, or a whole pytest directory (`tests`, `tests/unit`, `tests/ui`, `tests/host`, `tests/integration`). Run ONLY the focused test files named in your task, plus the tree guards: `uv run pytest tests/docs tests/unit/test_path_indirection.py tests/unit/test_install_write_guard.py tests/unit/test_gate_tiers.py -q`.
- ⛔ Banned git: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit paths.
- No C++ changes in this phase (no rebuild needed).
- Never spell `game` or `sdk` as a path segment; never capture a path at import (`tests/unit/test_path_indirection.py`).
- Never mutate game state from a `render_payload` path.
- Game units only: distances are `*_gu`, never metres.
- Default dial values (spec §7-§10): `leash_gu` 200.0, `leash_slack_gu` 100.0, `regroup_gather_gu` 100.0, `engage_gu` 350.0, `wing_popularity` -0.3, `stickiness` 0.25, `odds_ratio` 0.8, `desperate_hull` 0.4, `ram_chance` 0.3, `brain_period_s` 1.0.
- Target priorities: primary 3.0, secondaries (max 2) 1.5, reach-set base 0.0 (or the km_targeting priority for a listed ship).
- Chain size: `max(1, floor(0.2 * n_mobile_members))`; the player, if a member, is prepended and counts as one of them.
- Env: `DAUNTLESS_WINGS=0` disables wings everywhere; `DAUNTLESS_WINGS_LOG=1` prints `[wings]` lines to stderr; `DAUNTLESS_COMBAT_WING_SIZE` (default 0) wires wings into `combat_stress`.
- Profiler scope name: `gl.wings`. Dial group name: `"wings"`.
- Library code may use modern Python. Keep SDK-facing names in BC style (`CreateWing`, `GetCommander`, …).

## Review Focus

1. **The stock SelectTarget is built lazily** (attack compounds use `BuilderAI`, activated on the first AI tick; see `tests/host/test_qb_km_targeting.py:_select_target`). Wing code must discover a member's SelectTarget on a later brain tick, not at `CreateAI` — pinned by Task 6's `test_select_target_discovered_after_builder_activation`.
2. **A dead or deleted ship name stays in groups.** Snapshots must skip names whose object is missing, dead or dying (`IsDead()`/`IsDying()`) and never raise — pinned by Task 5's `test_snapshot_skips_dead_and_missing`.
3. **Commander dies mid-rejoin:** followers rejoining the dead commander must retarget the successor with no tree rebuild — pinned by Task 6's `test_rejoin_follows_handover`.
4. **Mission swap / End Combat / Restart mid-battle** must leave no wing state, no wrapped `CreateAI`, and stop `gl.wings` work — pinned by Task 8's `test_reset_on_end_and_swap_clears_wings`.
5. **Wings off means stock**: with `DAUNTLESS_WINGS=0` the ship trees are the stock trees and SelectTarget weights are stock — pinned by Task 8's `test_wings_off_is_stock`.

---

### Task 1: Pure chain + assessment + dials

**Files:**
- Create: `engine/wings/__init__.py` (empty docstring), `engine/wings/chain.py`, `engine/wings/assess.py`, `engine/wings/dials.py`
- Test: `tests/unit/test_wings_chain_assess.py`, `tests/unit/test_wings_dials.py`

**Interfaces:**
- Produces:
  - `chain.chain_size(n_mobile: int) -> int` — `max(1, n_mobile // 5)`.
  - `chain.build_chain(members: list[tuple[str, float]], player: str | None) -> list[str]` — members are `(name, rated_power)` in group order (player excluded from `members`); returns the player first (if given) then the top members by power, stable on ties, total length `chain_size(len(members) + (1 if player else 0))`.
  - `chain.current_commander(chain: list[str], is_alive: Callable[[str], bool]) -> str | None`.
  - `assess.ShipView` frozen dataclass: `name: str, pos: tuple[float,float,float], hull: float, shield: float, power: float, wing_id: str | None = None, is_commander: bool = False`.
  - `assess.strength(v: ShipView) -> float` = `v.power * v.hull * (0.5 + 0.5 * v.shield)`.
  - `assess.dist(a, b) -> float` (positions), `assess.side_strength(views, anchor_pos, within_gu) -> float`, `assess.weakest(views) -> ShipView | None` (lowest strength, ties by name), `assess.fraction_beyond(member_views, anchor_pos, radius_gu) -> float`.
  - `dials.DEFAULTS: dict[str, float]` (the ten Global Constraints values), `dials.DIAL_ORDER`, `dials.get(name) -> float`, `dials.reset()`, `dials.register()` — copy the shape of `engine/appc/sensor_dials.py` (step table, `current`, `register_group("wings", ...)` via `engine/dev_dial_groups.py`).

- [ ] **Step 1: Write failing tests** — `test_chain_size_table`: `chain_size(n)` for n = 1,4,5,9,10,25 → 1,1,1,1,2,5. `test_build_chain_power_order_and_ties`: members `[("a",500),("b",1000),("c",1000),("d",200),("e",100),("f",50),("g",40),("h",30),("i",20),("j",10)]` → `["b","c"]`. `test_build_chain_player_first`: same members, player `"P"` → length `chain_size(11)` = 2 → `["P","b"]`. `test_current_commander_skips_dead`. `test_strength_formula`: power 1000, hull 0.5, shield 0.0 → 250.0; shield 1.0 → 500.0. `test_weakest_ties_by_name`. `test_fraction_beyond`. Dials: `test_defaults_match_spec` (all ten values), `test_get_reads_current_after_step`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_wings_chain_assess.py tests/unit/test_wings_dials.py -q` — expect FAIL (import errors).
- [ ] **Step 3: Implement** the three modules (pure, no App imports in `chain`/`assess`).
- [ ] **Step 4: Run** the same command — expect PASS.
- [ ] **Step 5: Commit** `git add engine/wings/__init__.py engine/wings/chain.py engine/wings/assess.py engine/wings/dials.py tests/unit/test_wings_chain_assess.py tests/unit/test_wings_dials.py && git commit -m "feat(wings): chain of command, assessment, dials"`

### Task 2: Decisions registry + stock decisions

**Files:**
- Create: `engine/wings/decisions.py`
- Test: `tests/unit/test_wings_decisions.py`

**Interfaces:**
- Consumes: `assess.*`, `dials.get`.
- Produces:
  - `decisions.Context` dataclass: `members: list[ShipView]` (live member views, the player included when a member), `anchor: ShipView`, `enemies: list[ShipView]` (live candidates), `current: str | None` (current decision name).
  - `decisions.Choice` dataclass: `primary: str | None`, `secondaries: tuple[str, ...]`, `gather: bool`.
  - Protocol `Decision`: attribute `name: str`; `score(ctx) -> float`; `choose(ctx) -> Choice`.
  - `decisions.register(decision) -> None` (replaces by name), `decisions.registered() -> list[Decision]` (registration order), `decisions.reset_registry()` (back to the three stock ones).
  - `decisions.pick(ctx) -> Decision` — highest `score`, current decision gets `+ dials.get("stickiness")`, ties keep current, else registration order.
  - Stock decisions `Regroup` (`name="regroup"`), `SwarmWeakest` (`"swarm_weakest"`), `SwarmCommander` (`"swarm_commander"`) with scores exactly as spec §8. "Reach" for choosing primaries = enemies within `leash_gu` of the anchor; strengths summed within `engage_gu`.
  - `SwarmWeakest.choose`: primary = weakest in reach; secondaries = next two weakest in reach. `SwarmCommander.choose`: primary = the in-reach enemy with `is_commander` nearest the anchor; secondaries = the two in-reach enemies of that commander's `wing_id` nearest to it. `Regroup.choose`: `gather=True`, primary/secondaries as `SwarmWeakest`.
  - When nothing is in reach every decision's `choose` returns `primary=None` (Task 4 handles the advance).

- [ ] **Step 1: Write failing tests** — `test_regroup_wins_when_most_strayed` (3 of 4 members at 400 GU → regroup score 1.5 > 1.0); `test_swarm_weakest_when_not_outmatched`; `test_swarm_commander_when_outmatched_and_commander_visible`; `test_swarm_commander_low_without_enemy_commander` (score 0.3); `test_stickiness_keeps_current_on_near_tie`; `test_register_replaces_by_name_and_reset_restores_stock`; `test_choose_returns_none_primary_when_nothing_in_reach`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_wings_decisions.py -q` — FAIL.
- [ ] **Step 3: Implement** `engine/wings/decisions.py`.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(wings): decision registry and phase A decisions`.

### Task 3: Roster (wings, members, registry)

**Files:**
- Create: `engine/wings/roster.py`
- Test: `tests/unit/test_wings_roster.py`

**Interfaces:**
- Produces:
  - `roster.Member` dataclass: `name: str`, `is_player: bool = False`, `in_chain_eligible: bool = True` (False for late arrivals), `select_nodes: list = []` (PreprocessingAI nodes holding a stock SelectTarget, filled lazily), `rejoin: bool = False`, `desperate: str | None = None` (`"ram"`/`"flee"`), `conditions: dict[str, object] = {}` (kind → TGCondition, registered by `ConditionWing`), `ram_script = None` (the `Ram` PlainAI script instance, set by `tree.wrap_tree`; the brain calls its `SetTargetObjectName` with the ship's current target name when desperation assigns `"ram"`).
  - `roster.Wing` dataclass: `wing_id: str`, `enemy_group` (an `ObjectGroup` whose names are candidate enemies), `target_group` (an `App.ObjectGroupWithInfo`, created in `create_wing`), `members: dict[str, Member]` (insertion = group order), `chain: list[str] = []`, `commander: str | None = None`, `leaderless: bool = False`, `decision: str | None = None`, `primary: str | None = None`, `km_priorities: Callable[[], dict[str, float]] = lambda: {}`, `phase_s: float = 0.0`, `accum_s: float = 0.0`, `rng: random.Random` (seeded from `wing_id` via `zlib.crc32`).
  - `roster.create_wing(wing_id, enemy_group, km_priorities=None) -> Wing`; `roster.add_member(wing, name, *, is_player=False, chain_eligible=True) -> Member`; `roster.wing_of(name) -> Wing | None`; `roster.member(name) -> Member | None`; `roster.wings() -> list[Wing]` (creation order); `roster.reset() -> None`.
  - `create_wing` seeds `target_group` with every name currently in `enemy_group` at Priority 0.0 so `SelectTarget` has candidates before the first brain tick.

- [ ] **Step 1: Write failing tests** — create/lookup/reset; duplicate member add is idempotent; `wing_of` after reset is None; `test_target_group_seeded_from_enemy_group` (uses `App.ObjectGroup()` with two names → target group holds both at `{"Priority": 0.0}`); `test_rng_deterministic_per_wing_id`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_wings_roster.py -q` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(wings): wing roster and registry`.

### Task 4: Pure plans — target group, rejoin, desperation

**Files:**
- Create: `engine/wings/plans.py`
- Test: `tests/unit/test_wings_plans.py`

**Interfaces:**
- Consumes: `assess`, `decisions.Choice`, `dials.get`.
- Produces:
  - `plans.target_priorities(enemies: list[ShipView], anchor: ShipView, choice: Choice, km: dict[str, float], player_target: str | None) -> dict[str, float]` — spec §9: reach set (within `leash_gu` of anchor) at `km.get(name, 0.0)`; primary 3.0 (or `player_target` if it is an enemy in `enemies`, which then replaces the choice's primary), secondaries 1.5 (`max` with km); if reach set empty and enemies non-empty → `{nearest: 3.0}`; if no enemies → `{}`.
  - `plans.leaderless_priorities(enemies, km) -> dict[str, float]` — every enemy at `km.get(name, 0.0)`.
  - `plans.rejoin_flags(member_views, anchor, prev: dict[str, bool], gather: bool, commander: str) -> dict[str, bool]` — hysteresis per spec §7 (set > `leash_gu + leash_slack_gu`, clear < `leash_gu`); with `gather` a member also stays/sets while > `regroup_gather_gu`; the commander and the player are always False.
  - `plans.desperation(member_views, already: dict[str, str | None], rng) -> dict[str, str]` — for each member with `hull < desperate_hull` and no entry yet: `"ram"` if `rng.random() < ram_chance` else `"flee"`; iterate members in name order so the rng sequence is deterministic; return only new assignments.

- [ ] **Step 1: Write failing tests** — `test_reach_set_and_priorities` (two enemies in reach + one at 500 GU → far one absent, primary 3.0, secondary 1.5, other 0.0); `test_km_priority_kept_and_maxed`; `test_nothing_in_reach_targets_nearest`; `test_player_target_overrides_primary`; `test_rejoin_hysteresis` (member at 250 GU stays as prev; 310 sets; 190 clears); `test_gather_holds_until_inside_gather`; `test_commander_never_rejoins`; `test_desperation_deterministic_and_once` (same seed twice → same dict; second call with `already` filled → `{}`).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_wings_plans.py -q` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(wings): target, rejoin and desperation plans`.

### Task 5: Brain glue — snapshot and apply

**Files:**
- Create: `engine/wings/brain.py`
- Test: `tests/host/test_wings_brain.py` (headless, `pytest.importorskip("_dauntless_host")`; build ships the way `tests/host/test_qb_km_targeting.py` / `tests/integration/test_quickbattle_setup_e2e.py`'s `world` fixture does, or with `loadspacehelper.CreateShip` in a fresh set)

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces:
  - `brain.view_of(ship, wing_id=None, is_commander=False) -> ShipView | None` — None if missing/dead/dying. Position from `GetWorldLocation()`; hull = `GetHull().GetConditionPercentage()`; shield = mean of the six shield faces' fractions from `GetShields()` (0.0 if no shield subsystem); power = `GetPowerSubsystem().GetProperty().GetPowerOutput()` (0.0 if absent).
  - `brain.arm_chain(wing) -> None` — builds `wing.chain` with `chain.build_chain` from chain-eligible, non-player members' rated power and the player member's name; sets `wing.commander`.
  - `brain.tick_wing(wing) -> None` — spec §6 steps 1-5:
    1. snapshot members + enemies (`wing.enemy_group.GetNameTuple()`, resolved via `App.ShipClass_GetObject(set, name)` in the anchor's set; enemy `is_commander`/`wing_id` from `roster`);
    2. commander via `chain.current_commander`; on change log `handover`; if None → set `wing.leaderless=True` (latched), log once, restore stock weights on members' select nodes (`SetRelativeImportance()` with no args), write `leaderless_priorities`, clear rejoin, then run `plans.desperation`, store it on `member.desperate`, set `member.ram_script`'s target (if present) for `"ram"`, and push the `"ram"`/`"flee"` condition; return;
    3. `decisions.pick` → `choose`; log on decision change;
    4. write the target group: set every planned name via `target_group[name] = {"Priority": p}`, remove names no longer planned (`RemoveName`);
    5. push condition statuses: for each member, `conditions["rejoin"].SetStatus(1/0)`; if `wing.primary` changed, `ForceUpdate()` each member's select nodes.
  - Player target: `App.Game_GetCurrentPlayer()`'s `GetTarget()` name when the player is a member and commander.
  - Logging helper `brain.log(msg)` prints `"[wings] " + msg` to stderr only when `DAUNTLESS_WINGS_LOG=1` (read at use).

- [ ] **Step 1: Write failing tests** — `test_snapshot_skips_dead_and_missing` (a name in the enemy group with no object, one dead ship: no exception, neither in the plan); `test_tick_writes_reach_set_and_primary` (2 members, 3 enemies placed at known GU offsets → group priorities match `plans.target_priorities`); `test_far_enemy_removed_from_group` (move an enemy to 600 GU, tick → name gone); `test_handover_on_commander_death` (kill commander → `wing.commander` is the next chain entry); `test_leaderless_latches_and_restores_stock` (kill all chain → `leaderless`, group holds all enemies, select weights stock, later ticks keep it leaderless).
- [ ] **Step 2: Run** `uv run pytest tests/host/test_wings_brain.py -q` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(wings): brain tick glue`.

### Task 6: Library modules + wrapped tree

**Files:**
- Modify: `engine/compat/claimed.py` — `_CLAIMS` gains entries that map a dotted name to a single `.py` file: `"ai.plainai.wingrejoin" -> wing_library/AI/PlainAI/WingRejoin.py`, `"conditions.conditionwing" -> wing_library/Conditions/ConditionWing.py`, `"dauntlesswings" -> wing_library/DauntlessWings.py`. When a claim's base is a file, `claimed_spec` returns `spec_from_file_location(fullname, file)` for an exact (case-folded) name match.
- Create: `engine/compat/wing_library/AI/PlainAI/WingRejoin.py`, `engine/compat/wing_library/Conditions/ConditionWing.py`, `engine/wings/tree.py`
- Test: `tests/unit/test_claimed_single_file.py`, `tests/host/test_wings_tree.py`

**Interfaces:**
- Produces:
  - `Conditions.ConditionWing.ConditionWing(pCodeCondition, sShip: str, sKind: str)` — `sKind` ∈ `"rejoin"`, `"ram"`, `"flee"`; on construction registers `pCodeCondition` into `roster.member(sShip).conditions[sKind]` (no-op if not a member); initial status 0.
  - `AI.PlainAI.WingRejoin.WingRejoin(pCodeAI)` — behaves like SDK `AI/PlainAI/FollowObject.py` toward `roster.wing_of(<own ship name>).commander` (re-read every `Update`); if no commander, returns the PlainAI "done/dormant" status the SDK manoeuvres use. Reuse FollowObject by delegation (instantiate the SDK class and set its `pcFollowObjectName` before each `Update`), not by copying its body.
  - `tree.wrap_tree(pShip, pStockTree, wing) -> ArtificialIntelligence` — spec §11 tree: `PriorityListAI` with 1 Conditional(ConditionWing ram) → PlainAI `Ram` (`SetTargetObjectName` re-set by the brain when desperation assigns it, to the ship's current target name), 2 Conditional(ConditionWing flee) → PlainAI `Flee` (`SetFleeFromGroup(wing.enemy_group)`), 3 Conditional(ConditionWing rejoin) → PreprocessingAI `AvoidObstacles` (stock `AI.Preprocessors.AvoidObstacles`) around PlainAI `WingRejoin`, 4 the stock tree. EvalFuncs exactly `def EvalFunc(bOn): ... return ACTIVE if bOn else DORMANT` using only `App` names (memoisable, `ai_driver._memoisable_evalfunc`). Interruptable 1 throughout.
  - `tree.discover_select_nodes(pShip, member) -> bool` — walks `pShip.GetAI().GetAllAIsInTree()` for `PreprocessingAI` named `"SelectTarget"` whose `GetPreprocessingInstance()` is a stock SelectTarget (`type(inst).__name__ == "SelectTarget"`); appends new nodes to `member.select_nodes`; sets each instance's weights with `SetRelativeImportance(fPopularity=dials.get("wing_popularity"))` (other args stock defaults); returns True if any found. Called by `brain.tick_wing` for members with no nodes yet (Task 5 glue gains this one call — edit `brain.py` in this task).

- [ ] **Step 1: Write failing tests** — claimed: `test_single_file_claim_imports` (`import DauntlessWings`… use a temporary claim to a tmp file in the test, not the real library). Tree: `test_wrapped_tree_shape` (priorities 1-4, stock tree last, node types); `test_condition_push_activates_branch` (push rejoin=1 on a member → its Conditional reports active after the AI tick); `test_select_target_discovered_after_builder_activation` (before the first AI tick `discover_select_nodes` returns False; after activating builders as `tests/host/test_qb_km_targeting.py:_select_target` does, True, and the instance's `fPopularityFactor == -0.3`, other factors stock); `test_select_target_stays_native` (`ai_native.preprocessor_is_stock(inst, "SelectTarget", ("GetTargetRating",))` is true after weights are set); `test_rejoin_follows_handover` (WingRejoin's follow name equals the new commander after `wing.commander` changes, no tree rebuild).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_claimed_single_file.py tests/host/test_wings_tree.py -q` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS, plus `uv run pytest tests/host/test_wings_brain.py -q` still PASS.
- [ ] **Step 5: Commit** `feat(wings): wing library modules and wrapped tree`.

### Task 7: Service — switch, arm/reset, GameLoop hook, DauntlessWings surface

**Files:**
- Create: `engine/wings/service.py`, `engine/compat/wing_library/DauntlessWings.py`
- Modify: `engine/core/loop.py` (after the `gl.shuttles` block, add `with _prof.scope("gl.wings"): service.tick(TICK_DELTA)`), `engine/host_loop.py:reset_mission_state` (call `engine.wings.service.reset()` in the QB block near `_qb_end.reset()`)
- Test: `tests/unit/test_wings_service.py`, `tests/unit/test_dauntless_wings_surface.py`

**Interfaces:**
- Produces:
  - `service.enabled() -> bool` — `os.environ.get("DAUNTLESS_WINGS") != "0" and _dev_enabled` (`_dev_enabled` default True; `service.set_dev_enabled(on)`; reset to True by `service.reset_dev()` only — mission reset does not touch it).
  - `service.arm(wing) -> None` — `brain.arm_chain`, assigns `phase_s = i / n * brain_period_s` across currently armed wings (re-spread on each arm), logs `arm`.
  - `service.tick(dt: float) -> None` — no-op unless something is armed; per wing `accum_s += dt`; when `accum_s >= phase_s + brain_period_s` (first time) / `>= brain_period_s` (after), run `brain.tick_wing` and subtract the period. No work when `App.g_kUtopiaModule` game is paused (check the same pause predicate GameLoop uses; if GameLoop.tick isn't called while paused, document that and add no check).
  - `service.reset() -> None` — `roster.reset()`, clears armed list. `decisions.reset_registry()` is NOT called (mods registered decisions survive a battle); `service.reset_all()` (tests only) does both.
  - `DauntlessWings` functions (spec §11): `CreateWing(sWingID, pEnemyGroup)`, `AddMember(sWingID, sShip, bPlayer=0, bChainEligible=1)`, `ArmWing(sWingID)`, `WrapTree(pShip, pTree)` (returns `pTree` unchanged when wings are disabled or the ship is not a member), `GetWing(sShip)`, `GetCommander(sShip)`, `IsCommander(sShip)`, `IsLeaderless(sShip)`, `GetWingTargets(sShip)` (tuple of names with Priority > 0, highest first), `RegisterDecision(pDecision)`, `IsEnabled()`. Module docstring documents each (modder-facing).

- [ ] **Step 1: Write failing tests** — `test_disabled_by_env` (monkeypatch env `0` → `enabled()` False; `WrapTree` returns input object); `test_tick_runs_on_cadence_and_stagger` (two armed wings with a stubbed `brain.tick_wing` recorder; tick 1/60 s steps for 2.0 s → each ticked twice, first ticks at different times); `test_reset_clears`; surface: every listed function exists and `GetCommander` reflects the roster.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_wings_service.py tests/unit/test_dauntless_wings_surface.py -q` — FAIL.
- [ ] **Step 3: Implement**, including the `loop.py` and `reset_mission_state` edits.
- [ ] **Step 4: Run** — PASS. Also `uv run pytest tests/unit/test_path_indirection.py tests/unit/test_install_write_guard.py -q`.
- [ ] **Step 5: Commit** `feat(wings): service, GameLoop hook and DauntlessWings surface`.

### Task 8: Quick Battle consumer

**Files:**
- Create: `engine/quickbattle/wings_qb.py`
- Modify: `engine/quickbattle/scenario.py` (`PlayerOrder.group_id: Optional[str] = None`, set in `battle_plan()` from the player's group), `engine/quickbattle/battle_end.py` (`begin`: call `wings_qb.arm(qb, plan)` unconditionally, BEFORE the km_targeting block; `reset`: call `wings_qb.reset()`), `engine/quickbattle/late_arrivals.py:_spawn_one` (call `wings_qb.ship_arrived(qb, order, ship.GetName())` before `ship.SetAI(...)`), `engine/quickbattle/km_targeting.py` (`_create_ai`: if `wings_qb.owns(pShip.GetName())` call `orig` with no redirect; add `priorities_for(allegiance: str) -> dict[str, float]` returning the weighted group's name → Priority for the side whose AI attacks with it, `{}` when unarmed)
- Test: `tests/host/test_qb_wings.py` (drive like `tests/host/test_qb_km_targeting.py`: the `world` fixture and helpers from `tests/integration/test_quickbattle_setup_e2e.py` / `tests/host/test_qb_battle_end.py`)

**Interfaces:**
- Consumes: `service`, `roster`, `tree.wrap_tree`, `km_targeting.priorities_for`.
- Produces:
  - `wings_qb.arm(qb, plan) -> None` — no-op unless `service.enabled()`. Name → order map with `naming.object_name(o.title, n)` over `enumerate(plan.orders, start=1)`. One wing per non-neutral group id (`wing_id = "qb:" + group_id`); members = orders whose AI module (`spawn._details`) is `QuickBattleAI` or `QuickBattleFriendlyAI`; late orders (`warp_in_s > 0`) are added `chain_eligible=False` when they arrive, not now. The player joins the wing of `plan.player.group_id` with `is_player=True`. Enemy group per wing: enemies' wings use `qb.pFriendlies`, friendlies' use `qb.pEnemies` (via `App.ObjectGroup_FromModule("QuickBattle.QuickBattle", ...)`). `km_priorities` = `lambda: km_targeting.priorities_for(allegiance)`. Wraps `QuickBattleAI.CreateAI` / `QuickBattleFriendlyAI.CreateAI` (tag attribute like km's `_ORIG_ATTR`) so that during the original call `App.ObjectGroup_FromModule("QuickBattle.QuickBattle", <attacked side>)` returns the ship's wing `target_group`, then returns `tree.wrap_tree(pShip, <stock tree>, wing)`. `service.arm` each wing after members are added.
  - `wings_qb.owns(name) -> bool`, `wings_qb.ship_arrived(qb, order, name) -> None`, `wings_qb.reset() -> None` (restore wrapped CreateAIs, `service.reset()`).

- [ ] **Step 1: Write failing tests** — `test_wings_armed_per_group` (2 enemy groups + player group → 3 wings, chains sized per rule, player first in its chain); `test_members_share_wing_target_group` (every member's attack-AI `pAllTargetsGroup` is its wing's `target_group`, cf. km test's `_target_group`); `test_stations_and_neutrals_not_members`; `test_km_priorities_reach_wing_group` (a Defeat-protected friendly appears in the enemy wing's group with Priority ≥ 2.0 after a brain tick); `test_late_arrival_joins_not_in_chain`; `test_reset_on_end_and_swap_clears_wings` (End Combat path and `reset_mission_state` → `roster.wings() == []`, `QuickBattleAI.CreateAI` is the original function); `test_wings_off_is_stock` (env `DAUNTLESS_WINGS=0` → no wings, tree root is the stock QuickBattleAI root type/name, km behaviour unchanged).
- [ ] **Step 2: Run** `uv run pytest tests/host/test_qb_wings.py -q` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/host/test_qb_wings.py tests/host/test_qb_km_targeting.py tests/host/test_qb_battle_end.py tests/unit/test_qb_battle_plan.py -q` — PASS.
- [ ] **Step 5: Commit** `feat(wings): Quick Battle groups fight as wings`.

### Task 9: combat_stress consumer + behaviour test

**Files:**
- Modify: `engine/dev_missions/combat_stress.py` — read `DAUNTLESS_COMBAT_WING_SIZE` (int, default 0, read at use in `Initialize`); when > 0 and `service.enabled()`: per side, split ships in ring order into wings of N (`wing_id = "cs:<side>:<k>"`), `CreateWing` with the side's attacked group, `AddMember` each, `ArmWing`; build each tree as today, then `WrapTree`. With the target group: pass the wing's `target_group` as the `BasicAttack.CreateAI` targets argument instead of the side group when wings are on. Update the module docstring's env list.
- Test: `tests/host/test_wings_combat_stress.py`

**Interfaces:**
- Consumes: `DauntlessWings`.

- [ ] **Step 1: Write failing tests** — `test_wing_size_zero_is_unchanged` (no wings; trees stock); `test_wing_size_splits_sides` (16 ships, size 4 → 4 wings, 2 per side); `test_wings_keep_formation_together` (16 ships, size 4, run the headless loop ~3000 ticks as other combat_stress host tests do; assert 90th-percentile member→commander distance over the last 1000 ticks < `leash_gu + leash_slack_gu` (300 GU); also record the same metric with `DAUNTLESS_WINGS=0` and print both). Mark this test `@pytest.mark.slow` if the repo uses that marker; otherwise leave it and let the tier generator decide.
- [ ] **Step 2: Run** `uv run pytest tests/host/test_wings_combat_stress.py -q` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS. Report both spread numbers in the task report.
- [ ] **Step 5: Commit** `feat(wings): combat_stress wing wiring for perf A/B`.

### Task 10: Developer toggles, commander marker, dials registration, docs

**Files:**
- Modify: `engine/ui/developer_options_panel.py` + `native/assets/ui-cef/js/developer_options.js` (Combat tab: toggle `wing_ai` "Wing AI" → `service.set_dev_enabled`, default on; toggle `wing_markers` "Show Wing Commanders" → `engine.wings.service.set_show_markers`, default off; follow the `god_mode` row's pattern end to end), `engine/ui/target_list_view.py` (in `_snapshot`, when `service.show_markers()` and `dev_mode.is_enabled()` and `service.is_commander(name)`, prefix the caption with `"★ "`; read-only), `engine/host_loop.py` (register `engine.wings.dials` in the dev-mode dial block at ~12142-12153), `CLAUDE.md` (one table row "Wing leaders — Quick Battle wings" pointing at the programme + phase A specs, `engine/wings/`, `engine/compat/wing_library/`, env switches, dial group, the ⚠️ that SelectTarget is lazily built and the target group must be mutated never swapped), `docs/reference/engine/perf-cadences-and-latency.md` (a short entry: wing brain decides at 1 Hz, staggered; a wing reacts to a death/handover within ≤ 1 s + SelectTarget's ForceUpdate)
- Test: `tests/ui/test_developer_options_wings.py`, `tests/ui/test_target_list_commander_marker.py`

- [ ] **Step 1: Write failing tests** — toggles round-trip through `dispatch_event("toggle:wing_ai")` / `"toggle:wing_markers"` and appear in the payload; marker appears only with dev mode + toggle on + commander; caption unchanged otherwise.
- [ ] **Step 2: Run** `uv run pytest tests/ui/test_developer_options_wings.py tests/ui/test_target_list_commander_marker.py -q` — FAIL.
- [ ] **Step 3: Implement** (including CLAUDE.md row and perf-cadences entry).
- [ ] **Step 4: Run** the two files + `uv run pytest tests/docs tests/unit/test_gate_tiers.py -q` — PASS.
- [ ] **Step 5: Commit** `feat(wings): developer toggles, commander marker, docs`.

## Phase end (controller, not a subagent task)

1. Whole-branch review.
2. Perf A/B per spec §14 (Debug worktree build; headless; `DAUNTLESS_WINGS=0` vs unset; off/on/on/off; 128 ships, wing size 8). Record signals in `docs/reference/engine/perf-register.md`.
3. `scripts/gate_merge.sh` once; read failures from its artefact dir.
4. Acceptance criteria (spec §15) to Mark.
