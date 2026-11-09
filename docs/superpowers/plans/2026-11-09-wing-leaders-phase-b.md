# Wing Leaders Phase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quick Battle wings look after each other: protect a wingmate under heavy fire (with body-blocking guards), rotate shield-depleted ships out and back, and withdraw together when badly outmatched.

**Architecture:** Additive to Phase A's `engine/wings/`. New pure modules decide (`protect.py`, `rotate.py`) and two new registered decisions (`Protect`, `Withdraw`); the brain gains a strength history, target reads and per-member move points; one new library manoeuvre `AI.PlainAI.WingMoveTo` flies to a brain-computed point; three new pushed condition kinds add tree branches above rejoin.

**Tech Stack:** Python 3.11 engine shim, BC SDK AI scripts, pytest (headless `_dauntless_host`).

**Spec:** `docs/superpowers/specs/2026-11-09-wing-leaders-phase-b-design.md` (binding), on top of `2026-11-09-wing-leaders-phase-a-design.md` and the programme spec. Executors read the Phase B spec.

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/wing-leaders`, branch `feat/wing-leaders-b`. Plain `uv run` (never `--active`).
- ⛔ Never run `scripts/gate_merge.sh`, `scripts/gate_full.sh`, `scripts/check_tests.sh`, or a whole test directory. Run ONLY your task's named test files plus the tree guards: `uv run pytest tests/docs tests/unit/test_path_indirection.py tests/unit/test_install_write_guard.py tests/unit/test_gate_tiers.py -q`.
- ⛔ Banned git: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No C++ changes. No game-state mutation in any `render_payload` path. Distances `*_gu`.
- Additive only: do not rewrite Phase A behaviour; extend it. Phase A tests must keep passing (run `tests/host/test_wings_brain.py tests/host/test_wings_tree.py tests/unit/test_wings_*.py tests/host/test_qb_wings.py` in every task that touches brain/tree/decisions).
- New dials (added to `engine/wings/dials.py` DEFAULTS + DIAL_ORDER, read at use): `heavy_fire_window_s` 5.0, `heavy_fire_frac` 0.15, `heavy_fire_attackers` 3, `guard_count` 1 (2 when ≥ 6 live members), `interpose_gu` 40.0, `rotate_out_shield` 0.25, `rotate_in_shield` 0.6, `rotate_max_s` 30.0, `rotate_cap_frac` 0.34, `withdraw_odds` 0.4, `withdraw_wing_frac` 0.5, `withdraw_step_gu` 300.0, `withdraw_clear_s` 10.0, `withdraw_max_s` 60.0, `withdraw_cooldown_s` 120.0.
- Scores: Protect 1.5 while a protectee is under heavy fire else 0; Withdraw 2.5 when all gates hold else 0.
- Tree order (spec §6): 1 ram, 2 flee, 3 withdraw, 4 guard, 5 fallback, 6 rejoin, 7 stock. Withdraw/guard/fallback contain `AvoidObstacles(WingMoveTo)`.
- Game time: `App.g_kUtopiaModule.GetGameTime()`.

## Review Focus

1. **Stale move points** — a guard whose protectee or attacker dies must stop guarding on the next brain tick (no flying to a dead ship's last position forever) — pinned in Task 4 `test_guard_released_when_protectee_dies`.
2. **Everyone leaves** — rotate cap + exclusions must never strip a wing to only fallers; with 2 live members at most 1 falls back — Task 2 `test_cap_two_members_one_falls_back`.
3. **Withdraw stalls the battle** — withdraw must end by `withdraw_max_s` and then not re-trigger for `withdraw_cooldown_s` — Task 3 `test_withdraw_max_then_cooldown`.
4. **Wings off / leaderless / command away** — none of the new branches may stay pushed when a wing goes leaderless or command is away (stand down guard/fallback/withdraw like rejoin) — Task 4 `test_new_branches_stand_down_when_leaderless_or_away`.
5. **Player as protectee** — the player (not a member) is protected by their own group's wing but is never given a move point or a branch — Task 5 `test_player_is_protectee_not_member`.

---

### Task 1: Views see targets; strength history; protect + rotate pure rules

**Files:**
- Modify: `engine/wings/assess.py` (`ShipView.target: str | None = None`), `engine/wings/roster.py` (Member: `strength_hist: list = []` of `(t, strength)`, `move_point: tuple | None = None`, `guard: bool = False`, `fallback_since: float | None = None`; Wing: `armed_strength: float = 0.0`, `protect_names: Callable[[], Iterable[str]] = lambda: ()`, `withdraw_since: float | None = None`, `withdraw_cooldown_until: float = -1.0`, `clear_since: float | None = None`), `engine/wings/dials.py` (the new dials)
- Create: `engine/wings/protect.py`, `engine/wings/rotate.py`
- Test: `tests/unit/test_wings_protect.py`, `tests/unit/test_wings_rotate.py`, extend `tests/unit/test_wings_dials.py`

**Interfaces (produces):**
- `protect.damage_rate(hist: list[tuple[float,float]], now: float, window_s: float) -> float` — fraction of strength lost between the oldest sample within the window and the newest (0.0 if < 2 samples or oldest strength ≤ 0; never negative).
- `protect.attackers_of(name, enemies: list[ShipView], reach_center, reach_gu) -> list[ShipView]` — enemies within reach whose `target == name`.
- `protect.threatened(protectees: list[ShipView], rates: dict[str,float], enemies: list[ShipView], anchor: ShipView) -> ShipView | None` (attackers counted via `attackers_of(name, enemies, anchor.pos, engage_gu)`) — the most threatened protectee under heavy fire (rate ≥ heavy_fire_frac OR attackers ≥ heavy_fire_attackers), ties by attacker count then name; None if none.
- `protect.pick_guards(members: list[ShipView], protectee: ShipView, exclude: set[str], strength_frac: dict[str,float]) -> list[str]` — count = `guard_count` (2 if ≥ 6 live members), healthiest (frac ≥ 0.6) nearest to the protectee, excluding `exclude` (commander, player, protectee).
- `protect.guard_point(protectee_pos, attacker_pos) -> tuple` — `p + unit(a − p) × min(interpose_gu, 0.5 × |a − p|)`; if coincident, `p`.
- `rotate.fallback_flags(member_views, prev: dict[str, float|None], now, exclude: set[str]) -> dict[str, float|None]` — per member the time it started falling back or None; out when mean shield < rotate_out_shield and hull ≥ desperate_hull; back when shield ≥ rotate_in_shield or now − since ≥ rotate_max_s; cap `max(1, floor(rotate_cap_frac × live))` (but never all live members: with n live, cap ≤ n − 1 when n ≥ 2, 0 when n == 1), worst shields first; `exclude` never falls back.
- `rotate.fallback_point(anchor_pos, enemy_centroid, gather_gu) -> tuple` — `anchor + unit(anchor − centroid) × gather_gu`.
- `assess.centroid(views) -> tuple | None`.

- [ ] **Step 1: Write failing tests** — `test_damage_rate_window`, `test_damage_rate_never_negative`, `test_attackers_of_reach_and_target`, `test_threatened_by_rate`, `test_threatened_by_attackers`, `test_threatened_ties`, `test_pick_guards_healthiest_nearest_excludes`, `test_guard_count_two_when_six`, `test_guard_point_capped_and_halfway`, `test_fallback_out_and_back_hysteresis`, `test_fallback_max_time`, `test_cap_two_members_one_falls_back`, `test_cap_one_member_none`, `test_fallback_excludes`, `test_fallback_point_behind_anchor`, dial defaults.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_wings_protect.py tests/unit/test_wings_rotate.py tests/unit/test_wings_dials.py -q` — FAIL.
- [ ] **Step 3: Implement** (pure; no App imports in protect/rotate).
- [ ] **Step 4: Run** — PASS; plus `tests/unit/test_wings_*.py`.
- [ ] **Step 5: Commit** `feat(wings): protect and rotate rules`.

### Task 2: Protect and Withdraw decisions

**Files:** Modify `engine/wings/decisions.py`; Test `tests/unit/test_wings_decisions_b.py`

**Interfaces:**
- `decisions.Context` gains (defaults keep Phase A callers valid): `protectees: list = ()`, `rates: dict = {}` (name → damage rate), `armed_strength: float = 0.0`, `now: float = 0.0`, `withdraw_since: float | None = None`, `withdraw_cooldown_until: float = -1.0`, `clear_since: float | None = None`, `player_commands: bool = False`.
- `decisions.Choice` gains `protectee: str | None = None`, `withdraw: bool = False`.
- `Protect` (`name="protect"`): score 1.5 when `protect.threatened(...)` is not None else 0; choose: primary = threatened's attacker nearest the protectee, secondaries next two attackers, `protectee=` its name.
- `Withdraw` (`name="withdraw"`): score 2.5 when ours < withdraw_odds × theirs AND current member strength sum < withdraw_wing_frac × armed_strength AND not player_commands AND now ≥ withdraw_cooldown_until AND not ended (ended = `withdraw_since` set and (now − withdraw_since ≥ withdraw_max_s OR (clear_since set and now − clear_since ≥ withdraw_clear_s) OR ours ≥ withdraw_odds × 1.5 × theirs)); else 0. choose: `Choice(None, (), gather=True, withdraw=True)`.
- Both registered in `_stock()` after Phase A's three.

- [ ] Steps 1-5 as usual: tests `test_protect_scores_when_threatened`, `test_protect_choice_attackers`, `test_withdraw_gates_each`, `test_withdraw_max_then_cooldown` (the brain sets cooldown; here assert score 0 while now < cooldown_until and 0 once ended by max), `test_withdraw_beats_regroup`, `test_phase_a_scores_unchanged`. Run `uv run pytest tests/unit/test_wings_decisions_b.py tests/unit/test_wings_decisions.py -q`. Commit `feat(wings): protect and withdraw decisions`.

### Task 3: WingMoveTo manoeuvre, new condition kinds, tree branches

**Files:**
- Create: `engine/compat/wing_library/AI/PlainAI/WingMoveTo.py` (+ single-file claim in `engine/compat/claimed.py` for `ai.plainai.wingmoveto`)
- Modify: `engine/compat/wing_library/Conditions/ConditionWing.py` (accept kinds `withdraw`, `guard`, `fallback`), `engine/wings/tree.py` (`wrap_tree` order per Global Constraints)
- Test: `tests/host/test_wings_moveto.py`, extend `tests/host/test_wings_tree.py`

**Interfaces:**
- `WingMoveTo(pCodeAI)`: each `Update` reads `roster.member(own ship name).move_point`; with a point, flies there like SDK `AI/PlainAI/Intercept.py` drives toward `vDestination` (`TurnTowardLocation(TGPoint3)` + `SetImpulse(fraction, forward, DIRECTION_MODEL_SPACE)`, fraction scaling down linearly inside 20 GU, 0 within 2 GU); with no point, `SetImpulse(0, …)`. Always returns the ACTIVE status (never DONE). Verify the exact ship API names in `engine/appc` before use.
- `tree.wrap_tree` builds branches 3-5 as Conditionals over `AvoidObstacles(WingMoveTo)` with kinds `withdraw`/`guard`/`fallback`.

- [ ] Steps: tests `test_moveto_turns_and_moves_toward_point`, `test_moveto_slows_near_and_stops_at_point`, `test_moveto_no_point_stops`, `test_moveto_never_done`, `test_wrapped_tree_phase_b_order`, `test_new_kinds_activate_branch`. Run `uv run pytest tests/host/test_wings_moveto.py tests/host/test_wings_tree.py tests/unit/test_claimed_single_file.py -q`. Commit `feat(wings): WingMoveTo and phase B tree branches`.

### Task 4: Brain glue — history, targets, protect/guards, fallback, withdraw

**Files:** Modify `engine/wings/brain.py`, `engine/wings/service.py` (arm sets `armed_strength`); Test extend `tests/host/test_wings_brain.py` (or new `tests/host/test_wings_brain_b.py`)

**Behaviour:**
- `view_of` fills `target` (`GetTarget().GetName()` or None). The shared enemy snapshot (Phase A M2) carries it.
- Each normal tick append `(now, strength)` to each live member's `strength_hist`, trimming samples older than `heavy_fire_window_s`; compute `rates`.
- Protectees = live member views + views of `wing.protect_names()` resolved in the home set (deduped).
- Build `Context` with the new fields; `pick` → `choose`.
- **Withdraw**: on entering, set `withdraw_since = now`; commander's `move_point = rotate.fallback_point(anchor, centroid, withdraw_step_gu)` (reuse the helper with the step distance), push `withdraw` for the commander only; others get rejoin with gather (Phase A path); target group emptied (`{}`). Track `clear_since` (set when no enemy within engage_gu of anchor, cleared otherwise). On leaving Withdraw (any other decision chosen after it), set `withdraw_cooldown_until = now + withdraw_cooldown_s`, `withdraw_since = None`, `clear_since = None`, push withdraw 0, clear the commander's move point.
- **Protect**: guards = `protect.pick_guards(...)`; each guard gets `guard=True`, `move_point = protect.guard_point(protectee, primary attacker)`, push `guard` 1; former guards no longer chosen (or protectee/attacker gone) → guard 0, move_point None.
- **Fallback** (standing rule, skipped while Withdraw): `rotate.fallback_flags(...)` with exclude = {commander, player, guards, protectee}; fallers get `move_point = rotate.fallback_point(anchor, centroid, regroup_gather_gu)`, push `fallback` 1; returners push 0. No enemies in reach → nobody falls back (clear all).
- **Stand-down**: on going leaderless (latched) or command away, push guard/fallback/withdraw 0 and clear move points for every member (like rejoin). Desperation unchanged.
- Player: never given a move point or any push (not a member).

- [ ] Steps: tests `test_history_and_rate`, `test_protect_assigns_guard_between`, `test_guard_released_when_protectee_dies`, `test_fallback_moves_behind_and_returns`, `test_withdraw_enters_and_cools_down`, `test_new_branches_stand_down_when_leaderless_or_away`, plus Phase A brain tests still green. Run `uv run pytest tests/host/test_wings_brain.py tests/host/test_wings_brain_b.py tests/host/test_wings_tree.py tests/unit/test_wings_*.py -q`. Commit `feat(wings): brain drives protect, rotate and withdraw`.

### Task 5: Quick Battle hooks, behaviour test, docs

**Files:** Modify `engine/quickbattle/wings_qb.py` (`wing.protect_names`: for each wing, the Defeat-protected ships of its side = `km_targeting.priorities_for(<other allegiance>)` keys that are on this wing's side, plus — for the player's group's wing — the player's ship name), `CLAUDE.md` wing row (Phase B in a few words), `docs/reference/engine/perf-cadences-and-latency.md` (protect/rotate/withdraw react at the 1 Hz brain cadence), Phase B spec status line; Test extend `tests/host/test_qb_wings.py`, create `tests/host/test_wings_phase_b_behaviour.py`

- [ ] Tests: `test_player_is_protectee_not_member`, `test_protected_friendly_is_protectee`; behaviour (headless, combat_stress-style scene, pin `OPEN_STBC_HOST_HEADLESS` unset as tests/host/test_wings_combat_stress.py does): (a) a wing of 4 vs 4 where one member is focus-fired — within 10 s a guard's distance to the protectee→attacker segment midpoint shrinks below 60 GU; (b) a member with shields forced to 0.1 ends up farther from the enemy centroid than the commander within 15 s; (c) a 2-ship wing at 0.3 hull vs 8 enemies opens distance from the enemy centroid over 20 s. Use generous, documented bounds (scene is nondeterministic); if a bound can't be made robust, report rather than loosen.
- [ ] Run `uv run pytest tests/host/test_qb_wings.py tests/host/test_wings_phase_b_behaviour.py tests/host/test_wings_combat_stress.py -q` + tree guards. Commit `feat(wings): quick battle protect hooks, behaviour tests, docs`.

## Phase end (controller)

Whole-branch review (base = Phase A tip `b38855e2e`), perf A/B (Debug, combat_stress 128 ships, wing size 8, off/on/on/off; compare with SIG-225), merge gate, three acceptance criteria (spec §9).
