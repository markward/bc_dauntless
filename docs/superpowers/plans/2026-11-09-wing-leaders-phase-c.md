# Wing Leaders Phase C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wings fight smarter: slot-holders flank a weak shield face or envelop a healthy target while firing (#9), the wing knocks out a much stronger ship's weapons before killing it (#10), and a large wing holds one ship in reserve until the fight tips (#11).

**Architecture:** Two new wing branches in each member's tree: `reserve` (AvoidObstacles(WingMoveTo)) and `attack` (a stock FireScript owned by the wing around AvoidObstacles(WingMoveTo)). Three new registered decisions (`focus_face`, `envelop`, `disable`) put slot directions on the Choice. The brain assigns slots greedily, retargets each slot-holder's FireScript (hull or weapons-first), and runs the standing reserve rule. WingMoveTo learns live slot tracking and facing.

**Tech Stack:** Python 3.11 engine (`engine/wings/`), SDK-style library modules served by the claimed namespace (`engine/compat/wing_library/`), pytest (unit, host).

**Spec:** `docs/superpowers/specs/2026-11-09-wing-leaders-phase-c-design.md` (read Phase A spec §2 and §11 and Phase B spec §6 for background).

## Global Constraints

- Branch `feat/wing-leaders-c` in worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/wing-leaders`.
- ⛔ Run ONLY the focused test files named in your task plus the cheap tree guards (`tests/docs`, `tests/unit/test_path_indirection.py`, `tests/unit/test_install_write_guard.py`, `tests/unit/test_gate_tiers.py`). Never a whole suite, never `scripts/gate_*.sh`. Never an empty file list (that runs the whole suite).
- ⛔ No destructive git: no `git checkout -- / .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A/.`. Stage explicit paths.
- Plain `uv run`, never `uv run --active`. Do not launch the game.
- Do not dispatch subagents.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `engine/wings/{assess,decisions,plans,rotate,protect,attack,reserve,chain,dials}.py` stay pure (no `App` import).
- Library modules (`engine/compat/wing_library/**`) are SDK-style: `import App`, no f-strings needed but Python 3 is fine (they run in our 3.11).
- The stock FireScript instance is never subclassed, monkey-patched or given instance-level method overrides (`ai_native.preprocessor_is_stock` must stay true).
- Units are GU (`*_gu`), never metres.
- Every new dial gets `DEFAULTS`, `_STEP`, `_MIN` (and `_MAX` for fractions) entries in `engine/wings/dials.py`.
- New dials and defaults (spec §3–§6): `attack_standoff_gu` 120.0 (step 10, min 20), `attack_slots` 3 (step 1, min 0), `face_weak` 0.3 (step 0.05, min 0, max 1), `disable_threat` 1.5 (step 0.1, min 1.0, max 5.0), `reserve_min_wing` 5 (step 1, min 2), `reserve_gu` 150.0 (step 10, min 25), `reserve_max_s` 90.0 (step 5, min 5).

## Review Focus

1. A slot target that dies, cloaks or leaves the set mid-assignment: WingMoveTo must fall back to `move_point`/stop and the brain must clear the slot and the attack push on its next tick (Task 3 and Task 4 tests).
2. A member that is both a would-be slot-holder and a guard/faller/reserve: exactly one branch is pushed on (Task 4 exclusivity test).
3. Disable against a target whose weapon systems are all already disabled, or which has none: `disable` scores 0, never sticks (Task 2 test).
4. Reserve commit on "2× advantage" before any enemy is in reach: must NOT commit (Task 5 test).
5. Leaderless / command-away: every attack slot and the reserve stand down; the reserve is committed (Task 4/5 tests).

---

### Task 1: Pure slot geometry, face reads, reserve rules, dials

**Files:**
- Create: `engine/wings/attack.py`, `engine/wings/reserve.py`
- Modify: `engine/wings/dials.py`
- Test: `tests/unit/test_wings_attack.py`, `tests/unit/test_wings_reserve.py`

**Interfaces:**
- Produces (attack.py):
  - `FACE_AXES: dict[int, tuple]` = {0: (0,1,0), 1: (0,-1,0), 2: (0,0,1), 3: (0,0,-1), 4: (-1,0,0), 5: (1,0,0)} (FRONT, REAR, TOP, BOTTOM, LEFT, RIGHT).
  - `ENVELOP_ORDER: tuple = (1, 4, 5, 2, 3)` (REAR, LEFT, RIGHT, TOP, BOTTOM).
  - `weakest_face(faces: tuple) -> tuple[int, float] | None` — index and value of the lowest face; ties → lowest index; `()` → None.
  - `focus_dirs(face: int, n: int, arc_deg: float = 25.0) -> tuple[tuple, ...]` — n unit body-frame dirs spread evenly on ±arc_deg about the face axis, rotating about a perpendicular axis (FRONT/REAR/LEFT/RIGHT faces spread about body Z, TOP/BOTTOM about body X). n=1 → the axis itself; n≥2 → endpoints at ±arc_deg.
  - `envelop_dirs(n: int) -> tuple[tuple, ...]` — the first n axes of `ENVELOP_ORDER`, cycling if n > 5.
  - `slot_point(target_pos: tuple, rot_cols: tuple[tuple, tuple, tuple], body_dir: tuple, standoff_gu: float) -> tuple` — `target_pos + (c0*dx + c1*dy + c2*dz) * standoff`, where `rot_cols` are R's columns (right, forward, up).
  - `assign_slots(candidates: list[ShipView], points: list[tuple]) -> dict[str, int]` — greedy: repeatedly take the (candidate, slot) pair with the smallest distance (ties: name, then slot index), remove both; returns name → slot index; stops when either runs out.
- Produces (reserve.py):
  - `pick_reserve(views: list[ShipView], commander: str | None, players: set, min_wing: int) -> str | None` — None if fewer than `min_wing` non-player views; else the healthiest non-commander non-player by `(hull + shield)` descending, ties by `power` ascending (keep the least valuable healthy ship back — ruling 2026-11-09), then name.
  - `commit_reason(*, lost_member: bool, decision: str | None, primary_hull: float | None, ours: float, theirs: float, enemies_in_reach: int, held_s: float) -> str | None` — first true of: `"loss"` (lost_member), `"protect"` (decision == "protect"), `"finish"` (primary_hull is not None and < 0.3), `"advantage"` (enemies_in_reach ≥ 1 and ours ≥ 2 × theirs), `"timeout"` (held_s ≥ dial `reserve_max_s`); else None.

- [ ] **Step 1: Write failing tests** in `tests/unit/test_wings_attack.py`:
  - `test_weakest_face_picks_lowest_and_ties_low_index`: `weakest_face((1,1,0.5,0.5,1,1)) == (2, 0.5)`; `weakest_face(()) is None`.
  - `test_focus_dirs_single_is_axis`: `focus_dirs(4, 1) == ((-1.0, 0.0, 0.0),)` (approx).
  - `test_focus_dirs_spread_within_arc`: for face 4, n=3: every dir unit length, angle to (-1,0,0) ≤ 25° + 1e-6, max angle == 25° (approx), z component 0.
  - `test_focus_dirs_top_spreads_about_x`: face 2, n=2: x components 0, angles ±25° from (0,0,1).
  - `test_envelop_dirs_order_and_cycle`: `envelop_dirs(3)` == REAR, LEFT, RIGHT axes; `len(envelop_dirs(7)) == 7` and `envelop_dirs(7)[5] == FACE_AXES[1]`.
  - `test_slot_point_rotates_body_dir`: target at (10,0,0), rot_cols for a 90° yaw (right=(0,1,0), forward=(-1,0,0), up=(0,0,1)), body_dir LEFT (-1,0,0), standoff 120 → (10, -120, 0).
  - `test_assign_slots_greedy_nearest`: two candidates and two points where greedy-nearest differs from index order; assert mapping; three candidates and two points → exactly two assigned.
  - In `tests/unit/test_wings_reserve.py`: `test_pick_reserve_needs_min_wing` (4 views, min 5 → None), `test_pick_reserve_healthiest_noncommander` (commander healthiest is skipped; a damaged ship loses to a healthy one; healthy ties → lower power), `test_pick_reserve_ignores_players`, and one test per `commit_reason` trigger plus `test_advantage_needs_enemy_in_reach` (`ours=10, theirs=0, enemies_in_reach=0` → None) and `test_no_trigger_returns_none`.
- [ ] **Step 2:** `uv run pytest tests/unit/test_wings_attack.py tests/unit/test_wings_reserve.py -q` → FAIL (import errors).
- [ ] **Step 3:** Implement both modules and the seven dials (Global Constraints values).
- [ ] **Step 4:** Same command → PASS; also `uv run pytest tests/unit/test_wings_dials.py -q` if it exists (dial-table consistency).
- [ ] **Step 5:** Commit `feat(wings): phase C slot geometry, reserve rules, dials`.

---

### Task 2: Views carry faces and weapon state; three new decisions

**Files:**
- Modify: `engine/wings/assess.py` (ShipView), `engine/wings/decisions.py`, `engine/wings/brain.py` (`view_of` only)
- Test: `tests/unit/test_wings_decisions_c.py`; existing `tests/unit/test_wings_decisions*.py` must still pass

**Interfaces:**
- Consumes: Task 1 `attack.weakest_face`, `attack.focus_dirs`, `attack.envelop_dirs`.
- Produces:
  - `ShipView.faces: tuple = ()` (6 per-face fractions, index = face constant) and `ShipView.weapons_down: bool = False`.
  - `brain.view_of(ship, wing_id=None, is_commander=False, weapons=False)`: fills `faces` from the same six `GetSingleShieldPercentage` reads `_shield_fraction` makes (read once, mean derived from them); with `weapons=True` sets `weapons_down` = every existing system among `GetTorpedoSystem()`, `GetPhaserSystem()`, `GetPulseWeaponSystem()` reports `IsDisabled()` (a ship with none → True). The brain's enemy views pass `weapons=True`; member views don't.
  - `Context.slot_eligible: int = 0` (the brain fills it, Task 4).
  - `Choice.slot_dirs: tuple = ()`, `Choice.weapons_first: bool = False`, `Choice.slot_all: bool = False`.
  - `decisions.swarm_choice(ctx) -> Choice` — the Choice the higher-scoring of SwarmWeakest / SwarmCommander would make (tie → SwarmWeakest), with no stickiness.
  - Decisions `FocusFace` (name `"focus_face"`), `Envelop` (`"envelop"`), `Disable` (`"disable"`), added to `_stock()` after `Withdraw`.

Scoring (spec §4–§5; read dials at use):
- `FocusFace.score`: 1.2 when the swarm primary is in reach (`_in_reach`), `weakest_face(primary.faces)` value < `face_weak`, the mean of the other five ≥ 0.6, and `ctx.slot_eligible ≥ 2`; else 0. While `ctx.current == "focus_face"` the face threshold is `face_weak + 0.2` (hysteresis, spec §4 "stops when the face recovers to ≥ face_weak + 0.2").
- `FocusFace.choose`: swarm choice + `slot_dirs = focus_dirs(face, min(attack_slots, slot_eligible))`.
- `Envelop.score`: 1.05 when the swarm primary is in reach, has faces, no face < `face_weak`, mean shield ≥ 0.5 and `ctx.slot_eligible ≥ 3`; else 0.
- `Envelop.choose`: swarm choice + `slot_dirs = envelop_dirs(min(attack_slots, slot_eligible))`.
- `Disable.score`: 1.3 when the strongest enemy in reach (by `assess.strength`, ties name) has strength ≥ `disable_threat` × the strongest member's strength and `not weapons_down`; else 0.
- `Disable.choose`: `Choice(primary=that enemy, secondaries=swarm's secondaries minus it, slot_dirs=envelop_dirs(max(slot_eligible, 1)), weapons_first=True, slot_all=True)`.

- [ ] **Step 1: Failing tests** in `tests/unit/test_wings_decisions_c.py` (build `Context`s from `ShipView`s like the existing decisions tests do):
  - `test_focus_face_scores_with_weak_face_and_two_eligible` (LEFT 0.1, others 0.9, eligible 2 → 1.2), `test_focus_face_zero_when_others_weak` (others mean 0.5 → 0), `test_focus_face_zero_with_one_eligible`, `test_focus_face_hysteresis` (face 0.4: 0 when current is None, 1.2 when current == "focus_face"; face 0.55 → 0 either way), `test_focus_face_choose_slots_about_weak_face` (eligible 5, attack_slots 3 → 3 dirs, each within 25° of LEFT axis, primary = swarm primary).
  - `test_envelop_scores_healthy_target_three_eligible`, `test_envelop_zero_when_a_face_weak`, `test_envelop_choose_rear_left_right`.
  - `test_disable_scores_against_much_stronger`, `test_disable_zero_when_weapons_down`, `test_disable_zero_when_not_stronger_enough`, `test_disable_choose_weapons_first_all_slots` (`weapons_first`, `slot_all`, primary is the strong enemy even if it is not the weakest).
  - `test_disable_beats_focus_beats_envelop_beats_swarm` via `decisions.pick` on a context where all four score.
  - `test_zero_score_no_stickiness_for_new_decisions` (current "disable", weapons_down → pick ≠ disable).
  - Host-free test for `view_of`'s new fields belongs in Task 4's host tests; here keep `brain.view_of` untested beyond the existing tests passing.
- [ ] **Step 2:** `uv run pytest tests/unit/test_wings_decisions_c.py -q` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `uv run pytest tests/unit/test_wings_decisions_c.py tests/unit/test_wings_decisions.py tests/host/test_wings_brain.py tests/host/test_wings_brain_b.py -q` → PASS (adjust the glob to the existing decision test file names; list them with `ls tests/unit/test_wings_*`).
- [ ] **Step 5:** Commit `feat(wings): focus_face, envelop and disable decisions`.

---

### Task 3: Tree branches, wing FireScript, WingMoveTo slots and facing

**Files:**
- Modify: `engine/wings/roster.py` (Member), `engine/wings/tree.py`, `engine/compat/wing_library/AI/PlainAI/WingMoveTo.py`, `engine/quickbattle/wings_qb.py`, `engine/dev_missions/combat_stress.py` (only if it calls `wrap_tree`)
- Test: `tests/host/test_wings_tree.py` (extend), `tests/host/test_wings_moveto.py` (extend)

**Interfaces:**
- Produces:
  - `Member.slot: tuple | None = None` — `(target_name, body_dir, standoff_gu)`; `Member.fire_script: object = None` (the FireScript instance); `Member.attack_target: str | None = None`; `Member.weapons_first: bool = False`; `Member.reserve: bool = False`.
  - `tree.fire_keywords(difficulty: float | None) -> dict` — `{"Difficulty": difficulty if not None else 0.5}` passed through `AI.Compound.BasicAttack.SetFlagsFromDifficulty(prefix, d)` with `prefix = ("Easy_", "", "Hard_")[App.Game_GetDifficulty()]` (exactly as `BasicAttack.CreateAI` does), returned.
  - `tree.wrap_tree(pShip, pStockTree, wing, fire_keywords=None)`: priorities ram 1, flee 2, withdraw 3, guard 4, fallback 5, **reserve 6** (`Conditional[ConditionWing(ship,"reserve")] -> AvoidObstacles(WingMoveTo "Movereserve")`), **attack 7** (`Conditional[ConditionWing(ship,"attack")] -> PreprocessingAI "WingFire" (FireScript.Update) -> AvoidObstacles -> WingMoveTo "Moveattack"`), rejoin 8, stock 9. The FireScript is built as FedAttack builds FireAll: `apply(AI.Preprocessors.FireScript, (pShip.GetName(),), dict(kw, TargetSubsystems=[(App.CT_WEAPON_SYSTEM, 1)]))` with `kw = fire_keywords or tree.fire_keywords(None)`, then `AddWeaponSystem` for each non-null torpedo/phaser/pulse system, then `SetAttackDisabled(0)` and `IgnoreSubsystemTargets()`. Its initial target is the ship's own name (a placeholder the brain replaces before the branch ever runs; FireScript tolerates a missing target). Store it on `member.fire_script`.
  - `wings_qb` passes `fire_keywords=tree.fire_keywords(QuickBattle.GetCurrentAILevel())` (import `QuickBattle.QuickBattle` lazily, guarded: on any failure pass None).
  - WingMoveTo: if `member.slot` is set and its target resolves to a live ship in the member's set (`App.ShipClass_GetObject(pShip.GetContainingSet(), name)`, alive = not dead/dying the way `brain._alive` checks), the point is `target_pos + R·body_dir·standoff` with `R = target.GetWorldRotation()` columns; within `_SLOW_GU` (20) of that point it calls `TurnTowardLocation(target world location)` instead of the point. Else it falls back to `move_point` as today.
- [ ] **Step 1: Failing host tests:**
  - `test_wrap_tree_branch_order_c` — the PriorityList children in order: WingRam, WingFlee, WingWithdraw, WingGuard, WingFallback, WingReserve, WingAttack, WingRejoin, stock.
  - `test_attack_branch_holds_stock_firescript_with_weapons` — `type(member.fire_script) is AI.Preprocessors.FireScript`, `len(member.fire_script.lWeapons) ≥ 1` for a ship with phasers, `member.fire_script.lTargetSubsystems == []` (hull mode), `member.fire_script.HasSubsystemTargets()` false then true after `RestoreSubsystemTargets()` with `(CT_WEAPON_SYSTEM, 1)`, and `ai_native.preprocessor_is_stock(member.fire_script)` true.
  - `test_fire_keywords_from_difficulty` — `tree.fire_keywords(1.0)` contains `"Difficulty": 1.0` and at least one flag key that `SetFlagsFromDifficulty` sets (read `g_lAllFlags`).
  - `test_qb_passes_fire_keywords` in `tests/host/test_qb_wings.py` — a QB member's FireScript reflects the QB AI level (e.g. a flag that only Difficulty 1.0 sets).
  - In `test_wings_moveto.py`: `test_slot_tracks_target_live_pose` (set `member.slot = (target, (-1,0,0), 120)`, rotate the target 90° between two Updates; the ship's commanded turn location moves with it — assert via the ship's turn target or by stepping the sim N ticks and checking the ship ends within 40 GU of the rotated slot), `test_slot_faces_target_when_close` (ship placed on the slot point → after an Update its turn target is the target ship's position), `test_slot_dead_target_falls_back_to_move_point`.
- [ ] **Step 2:** Run `uv run pytest tests/host/test_wings_tree.py tests/host/test_wings_moveto.py tests/host/test_qb_wings.py -q` → new tests FAIL.
- [ ] **Step 3:** Implement. `ConditionWing` already accepts any `sKind`; only add "reserve" and "attack" to its docstring's list.
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5:** Commit `feat(wings): attack and reserve branches, wing FireScript, slot tracking`.

---

### Task 4: Brain assigns slots, retargets fire, stands down

**Files:**
- Modify: `engine/wings/brain.py`
- Test: `tests/host/test_wings_brain_c.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: `brain._apply_attack(wing, members, enemies, choice, busy: set) -> set[str]` returns the slot-holders; `busy` = commander ∪ players ∪ guards ∪ fallers ∪ reserve ∪ withdrawers.

Behaviour (spec §3):
- Enemy views are built with `view_of(..., weapons=True)`.
- Before `decisions.pick`, `ctx.slot_eligible` = live non-player non-commander members, minus last tick's fallers (`fallback_since is not None`) and the reserve.
- `_apply_moves` runs first (it picks guards/fallers); then `_apply_attack` with `busy` from its results (have `_apply_moves` return its guards/fallers/withdrawers, or read the member flags it just set).
- With `choice.slot_dirs` and a primary that resolves to a live ship: candidates = members not in `busy`; take `len(slot_dirs)` (or all candidates when `slot_all`, cycling `slot_dirs`); points via `attack.slot_point` from the target's `GetWorldRotation()` columns and `attack_standoff_gu`; `attack.assign_slots`.
- For each slot-holder: `member.slot = (primary, dir, standoff)`; if `member.attack_target != primary`: `fire_script.SetTarget(primary)`, `ship.SetTarget(primary)`, `member.attack_target = primary`; if `member.weapons_first != choice.weapons_first`: `RestoreSubsystemTargets()` / `IgnoreSubsystemTargets()` and store; push `"attack"` True and push `"rejoin"` False (slot-holders exempt from rejoin; set `m.rejoin = False` after `plans.rejoin_flags` runs).
- Everyone else: `member.slot = None`, `member.attack_target = None` (FireScript target left as is; it only runs while the branch is on), push `"attack"` False.
- `_stand_down` (leaderless/away) also clears slots and pushes `"attack"` False; withdraw means no slot-holders.
- Log `"%s attack %s slots=%d weapons_first=%d"` on a change of (primary, holder set, weapons_first).

- [ ] **Step 1: Failing host tests** (use the scene helpers from `tests/host/test_wings_brain_b.py`; force shields with the same setters those tests use, and read `brain.tick_wing` directly):
  - `test_focus_face_assigns_slots_on_weak_side`: enemy LEFT face forced to 0.1, 4 members → `wing.decision == "focus_face"`, ≥2 members have `slot` with body dir x < 0, their `fire_script.sTarget == primary` and `ship.GetTarget().GetName() == primary`, `conditions` for "attack" on, "rejoin" off.
  - `test_commander_guard_faller_reserve_never_slot`: each excluded role never gets a slot; exactly one of guard/fallback/reserve/attack/withdraw is on per member.
  - `test_disable_aims_at_weapons_and_survives_sync`: a much stronger enemy → decision "disable", slot-holders' `fire_script.lTargetSubsystems` non-empty; step the sim until `ship.GetTargetSubsystem()` is set for one holder; it is a weapon subsystem of the target (or a child of one) and stays set over 60 more ticks (the `ai_driver` sync keeps it because `GetTarget()` matches).
  - `test_slot_target_death_clears_slots`: kill the primary → next tick no member has a slot or "attack" on.
  - `test_leaderless_clears_attack`.
  - `test_slot_holder_reaches_slot_and_faces`: run the scene ~1800 ticks with focus_face; at least one holder within 40 GU of its live slot point and the angle between its forward and the line to the target < 30°.
- [ ] **Step 2:** `uv run pytest tests/host/test_wings_brain_c.py -q` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `uv run pytest tests/host/test_wings_brain_c.py tests/host/test_wings_brain.py tests/host/test_wings_brain_b.py tests/host/test_wings_tree.py -q` → PASS.
- [ ] **Step 5:** Commit `feat(wings): slot assignment and wing fire control`.

---

### Task 5: The reserve

**Files:**
- Modify: `engine/wings/roster.py` (Wing fields), `engine/wings/brain.py`, `engine/wings/service.py` if arming lives there
- Test: `tests/host/test_wings_reserve.py`

**Interfaces:**
- Consumes: Task 1 `reserve.pick_reserve`, `reserve.commit_reason`; Task 3 `Member.reserve`.
- Produces: `Wing.reserve: str | None = None`, `Wing.reserve_since: float | None = None`, `Wing.reserve_spent: bool = False`, `Wing.reserve_live: int = 0`, `Wing.last_centroid: tuple | None = None`.

Behaviour (spec §6):
- Pick once, when the chain is armed (`brain.arm_chain`; a late wave's wing arms when its first wave arrives, so the same call covers it): if not `reserve_spent`, `wing.reserve = pick_reserve(views, commander, players, int(dial reserve_min_wing))`, `reserve_since = now`, `reserve_live` = live non-player member count. Log `"%s reserve %s"`.
- Each led tick, before `_apply_moves`: `commit_reason(lost_member = live non-player count in `members` < reserve_live, decision = wing.decision, primary_hull = hull of the wing's previous primary if alive, ours/theirs = side_strength within engage_gu of the anchor, enemies_in_reach = len(near), held_s = now − reserve_since)`. On a reason: `reserve = None`, `reserve_spent = True`, log `"%s reserve commits (%s)"`. A dead reserve is spent too. Update `reserve_live` each tick.
- While held: the reserve is excluded from guards, fallers and slots; `member.move_point = rotate.fallback_point(anchor.pos, centroid, reserve_gu)` with centroid = `assess.centroid(near)` or `wing.last_centroid` (store it whenever `near` is non-empty) or the anchor itself (then the point is the anchor); push `"reserve"` True, `"rejoin"` False. Withdraw: the reserve withdraws like everyone (withdraw outranks it in the tree; its reserve push goes False while withdrawing and comes back after).
- `_stand_down` and `_go_leaderless` commit the reserve (spent) and push `"reserve"` False.

- [ ] **Step 1: Failing host tests:**
  - `test_reserve_picked_in_wing_of_five` / `test_no_reserve_in_wing_of_four`.
  - `test_reserve_holds_behind_commander`: with enemies in reach, the reserve's move point is farther from the enemy centroid than the anchor, by ≈ `reserve_gu`; "reserve" on; "attack", "guard", "fallback" off for it.
  - `test_reserve_commits_on_member_death` (kill a non-reserve member → next tick `wing.reserve is None`, `reserve_spent`, "reserve" off), `test_reserve_commits_on_protect`, `test_reserve_commits_on_timeout` (advance game time past `reserve_max_s`), `test_reserve_never_repicked_after_commit`.
  - `test_reserve_no_advantage_commit_without_enemies`: no enemies in reach for 20 ticks → still held.
  - `test_leaderless_commits_reserve`.
- [ ] **Step 2:** `uv run pytest tests/host/test_wings_reserve.py -q` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `uv run pytest tests/host/test_wings_reserve.py tests/host/test_wings_brain_c.py tests/host/test_wings_brain_b.py tests/host/test_qb_wings.py -q` → PASS.
- [ ] **Step 5:** Commit `feat(wings): hold a reserve`.

---

### Task 6: Behaviour tests and docs

**Files:**
- Create: `tests/host/test_wings_phase_c_behaviour.py`
- Modify: `CLAUDE.md` ("Wing leaders" row; keep it under its ~1200-character budget — replace words, don't append a paragraph), `docs/reference/engine/perf-cadences-and-latency.md` §8 (one line: slot points track the live target pose every 0.2 s in WingMoveTo; the assignment changes at the brain's 1 Hz), the Phase C spec §2 if a fact turns out different.

Behaviour tests (spec §8; headless, generous bounds, each run 3 times with different seeds via `pytest.mark.parametrize`; follow `tests/host/test_wings_phase_b_behaviour.py` for scene setup, and unset `OPEN_STBC_HOST_HEADLESS` as `tests/host/test_wings_combat_stress.py` does if the scene relies on real radii):
- (a) `test_focus_face_flanks_weak_side`: a wing of 5 vs one target whose LEFT face is held at 0.1 (re-forced every tick); after the brain has run ≥ 20 s, at least 2 slot-holders sit on the target's LEFT side (body-frame x < 0 from `world_to_body` / R^T·(p − t)).
- (b) `test_disable_weapons_before_hull_half`: a wing vs a ship with strength ≥ 2× the wing's strongest; record the tick the target's weapons all read `IsDisabled()` and the tick its hull first drops below 0.5; the first happens and precedes the second (or the hull never drops below 0.5 within the run while the weapons do go down).
- (c) `test_reserve_stays_back_until_loss`: a wing of 6 vs enemies; while held, the reserve's distance to the enemy centroid exceeds the commander's on ≥ 80% of sampled ticks; kill a member; within 10 s the reserve's distance to the enemy centroid drops below its held-phase mean by ≥ 50 GU.
- [ ] **Step 1:** Write the three tests; run `uv run pytest tests/host/test_wings_phase_c_behaviour.py -q`. If one fails, decide whether the test or the behaviour is wrong; fix the behaviour (in the owning module) when it is the behaviour, and say so in the report.
- [ ] **Step 2:** Docs edits; run `uv run pytest tests/docs -q`.
- [ ] **Step 3:** Commit `test(wings): phase C behaviour; docs`.
