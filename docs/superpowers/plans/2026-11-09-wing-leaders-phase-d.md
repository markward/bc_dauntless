# Wing Leaders Phase D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wings on one side see each other and act together: an idle wing reinforces a losing ally, flanks an ally's fight or screens a weak ally, and a fighting wing can feint back onto an idle ally.

**Architecture:** Each led wing publishes a `WingStatus` at the end of its brain tick; decisions read their side's allies from `Context.allies` (pure). Four new registered decisions (`reinforce`, `screen`, `flank`, `feint`). Reinforce moves the wing by a far primary (`Choice.far`); screen/flank/feint move every non-player member — commander included — through a new `hold` branch in a ring formation.

**Tech Stack:** Python 3.11 engine (`engine/wings/`), SDK-style library (`engine/compat/wing_library/`), pytest (unit, host).

**Spec:** `docs/superpowers/specs/2026-11-09-wing-leaders-phase-d-design.md` (background: Phase A §2/§11, Phase B §6, Phase C §3/§11 specs in the same folder).

## Global Constraints

- Branch `feat/wing-leaders-d` in worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/wing-leaders`.
- ⛔ Run ONLY the focused test files named in your task plus the cheap tree guards (`tests/docs`, `tests/unit/test_path_indirection.py`, `tests/unit/test_install_write_guard.py`, `tests/unit/test_gate_tiers.py`). Never a whole suite, never `scripts/gate_*.sh`, never an empty pytest file list.
- ⛔ No destructive git: no `git checkout -- / .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A/.`. Stage explicit paths. To mutate a file temporarily, back up with `cp` and restore with `cp` + `diff`.
- Plain `uv run`, never `uv run --active`. Do not launch the game window. Do not dispatch subagents.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (use `git commit -F <file>`).
- Pure modules stay App-free: `engine/wings/{assess,decisions,plans,rotate,protect,attack,reserve,chain,dials,allies}.py`.
- Decisions must keep using the per-Context memo (Phase C perf, `decisions.py`): read reach / side strengths / swarm choice through the memoised helpers, never recompute 64-enemy filters per decision.
- Units are GU (`*_gu`). Every new dial gets `DEFAULTS`, `_STEP`, `_MIN` (`_MAX` for fractions) and an entry in `tests/unit/test_wings_dials.py`'s SPEC table.
- New dials and defaults (spec §3–§6): `reinforce_odds` 1.0 (step 0.1, min 0, max 5), `reinforce_spare_odds` 2.5 (step 0.1, min 1, max 10), `reinforce_range_gu` 1500.0 (step 100, min 100), `reinforce_max_s` 90.0 (step 5, min 5), `reinforce_cooldown_s` 60.0 (step 5, min 0), `hold_spread_gu` 30.0 (step 5, min 5), `screen_watch_gu` 700.0 (step 50, min 100), `screen_gu` 150.0 (step 10, min 25), `flank_gu` 250.0 (step 25, min 50), `feint_range_gu` 800.0 (step 50, min 100), `feint_stop_gu` 100.0 (step 10, min 25), `feint_odds` 1.0 (step 0.1, min 0.1, max 5), `feint_cooldown_s` 180.0 (step 10, min 0), `feint_max_s` 45.0 (step 5, min 5).

## Review Focus

1. An ally that dies, goes leaderless, or warps away mid-reinforce/feint: the decision ends next tick, no stale ally id, no exception (Task 3 tests).
2. Two idle wings both scoring reinforce for the same ally: both may go (no coordination needed), but neither oscillates between reinforce and flank tick to tick (stickiness + latches; Task 2 test).
3. A wing whose commander is the player-adjacent wing (the player's group wing) moving its commander via `hold`: the player is never given a move point or a push (Task 3 test).
4. Hold formation with 1–2 live members (ring with fewer points than members, or the commander alone) (Task 3 test).
5. Feint while the wing holds a reserve or has attack slots: slots and guards are off during hold; the reserve keeps its held flag but moves with the formation (Task 3 test).

---

### Task 1: Allies — side, status publishing, Context.allies

**Files:**
- Create: `engine/wings/allies.py`
- Modify: `engine/wings/roster.py` (Wing.side, Wing.status), `engine/wings/brain.py` (publish/clear status; fill `Context.allies`), `engine/wings/decisions.py` (Context.allies field only), `engine/wings/dials.py`, `engine/quickbattle/wings_qb.py` and `engine/dev_missions/combat_stress.py` (set `side`)
- Test: `tests/unit/test_wings_allies.py`, `tests/host/test_wings_allies.py`, `tests/unit/test_wings_dials.py` (SPEC rows)

**Interfaces:**
- Produces:
  - `allies.WingStatus` (frozen dataclass): `wing_id: str, side: str, anchor: tuple, strength_frac: float, ours: float, theirs: float, enemy_centroid: tuple | None, engaged: bool, decision: str | None`.
  - `allies.in_trouble(s: WingStatus) -> bool` — `s.engaged and (s.ours < dials.get("reinforce_odds") * s.theirs or s.decision in ("protect", "withdraw"))`.
  - `allies.side_allies(wing, wings) -> tuple[WingStatus, ...]` — statuses of the other wings in `wings` with the same `side` whose `status` is not None, sorted by `wing_id`.
  - `roster.Wing.side: str | None = None` (consumers set it; `allies.side_of(wing)` returns `wing.side` or `str(id(wing.enemy_group))`); `roster.Wing.status: WingStatus | None = None`.
  - `decisions.Context.allies: tuple = ()`.
  - Brain: at the end of a led tick, `wing.status = WingStatus(...)` with `ours/theirs` = the memoised side strengths within `engage_gu` of the anchor (reuse the Context's memo), `enemy_centroid` = `assess.centroid(near)`, `strength_frac` = live strength / `wing.armed_strength` (0 if armed is 0), `engaged = bool(near)`. Leaderless, command away and stand-down set `wing.status = None`. Before `decisions.pick`, `ctx.allies = allies.side_allies(wing, roster.wings())`.
  - Dials: all fourteen from Global Constraints (later tasks read them).
- [ ] **Step 1: Failing tests:** unit — `in_trouble` (losing odds; protect; withdraw; not engaged → False), `side_allies` (same side only, excludes self and status None, sorted), `side_of` default. Host — after a led tick `wing.status` carries the anchor and engaged flag; `_go_leaderless` / command away clears it; two QB wings on the friendly side see each other in `ctx.allies` (spy on `decisions.pick` to capture the ctx), an enemy-side wing doesn't.
- [ ] **Step 2:** `uv run pytest tests/unit/test_wings_allies.py tests/host/test_wings_allies.py tests/unit/test_wings_dials.py -q` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Same command plus `tests/host/test_wings_brain.py tests/host/test_wings_brain_c.py tests/host/test_qb_wings.py tests/host/test_wings_combat_stress.py` → PASS.
- [ ] **Step 5:** Commit `feat(wings): allies — side statuses`.

---

### Task 2: Four decisions, hold geometry, far targets

**Files:**
- Modify: `engine/wings/decisions.py`, `engine/wings/allies.py` (geometry), `engine/wings/plans.py` (`target_priorities` far)
- Test: `tests/unit/test_wings_decisions_d.py`, `tests/unit/test_wings_allies.py` (geometry), `tests/unit/test_wings_plans.py`

**Interfaces:**
- Consumes: Task 1 `WingStatus`, `in_trouble`, `Context.allies`, dials.
- Produces:
  - `Choice` gains `far: bool = False`, `hold_point: tuple | None = None`, `hold_kind: str | None = None` (`"screen" | "flank" | "feint"`), `ally: str | None = None`.
  - `Context` gains latch/cooldown inputs the brain fills (Task 3): `reinforce_ally: str | None = None`, `reinforce_done: frozenset = frozenset()` (allies on cooldown), `feint_ally: str | None = None`, `feint_ready: bool = True` (cooldown over), `feint_quiet_s: float = 0.0` (seconds with no enemy within engage of our anchor while feinting), `decision_age_s: float = 0.0` (seconds the current decision has been current).
  - `allies.screen_point(ally_anchor, enemy_centroid) -> tuple`, `allies.flank_point(our_anchor, ally_anchor, centroid) -> tuple`, `allies.lure_point(our_anchor, f_anchor) -> tuple` (formulas and fallbacks per spec §5–§6; dials read at use).
  - Decisions `Reinforce` ("reinforce"), `Feint` ("feint"), `Screen` ("screen"), `Flank` ("flank"), registered after the Phase C decisions in `_stock()` in that order (spec §7 tie rule: focus_face before feint).
  - `plans.target_priorities`: when `choice.far`, the primary and secondaries are kept even beyond leash (primary 3.0, secondaries 1.5, km priorities still win as today for in-reach listed ships).

Scoring and ends exactly per spec §4–§6, with these clarifications:
- "Engaged" for us = the memoised `_in_reach`-style filter at `engage_gu` (add a memoised `_near(ctx)` alongside the existing helpers); "ours"/"theirs" for us = the memoised side strengths.
- Latches: `Reinforce.score` while `ctx.current == "reinforce"` uses `ctx.reinforce_ally` and checks only the end conditions (arrival within `leash_gu` of the ally's anchor, ally not in trouble, ally missing, `decision_age_s ≥ reinforce_max_s`); otherwise the entry gate, skipping allies in `ctx.reinforce_done`. Flank likewise latches on `ctx.current == "flank"` (end conditions only). Feint latches on `ctx.feint_ally` with its §6 end conditions (`feint_quiet_s ≥ 10`, `decision_age_s ≥ feint_max_s`, ...). Screen has no latch.
- Feint's "the enemies we were fighting come within `engage_gu` of F's anchor": use F's status `engaged` flag (F becomes engaged ⇒ sprung) — ends either way.
- `Feint.choose`: `Choice(primary=None, hold_point=lure_point, hold_kind="feint", ally=F)`; `Screen.choose` / `Flank.choose`: the swarm choice plus `hold_point`, `hold_kind`, `ally`; `Reinforce.choose`: `Choice(primary, secondaries, far=True, ally=A)`.
- [ ] **Step 1: Failing tests** (`tests/unit/test_wings_decisions_d.py`): per decision — scores at its value when every gate holds; 0 when each gate fails (one test per gate); latch keeps reinforce/flank/feint on after the entry gate fails and ends on each end condition; reinforce skips an ally in `reinforce_done`; feint 0 when `feint_ready` is False; choose outputs (primary nearest the ally's anchor, `far`, hold points); tie: focus_face beats a fresh feint, a current feint keeps winning; `test_no_flip_between_reinforce_and_flank` (an ally in trouble → reinforce; the same context with ally not in trouble → flank; a current reinforce whose ally recovers ends rather than flipping to flank in the same tick only via score 0 → next pick); geometry unit tests incl. flank dead-behind fallback; `target_priorities` far keeps an out-of-leash primary at 3.0 and leaves today's output unchanged when `far` is False (existing plans tests pass).
- [ ] **Step 2:** `uv run pytest tests/unit/test_wings_decisions_d.py tests/unit/test_wings_allies.py tests/unit/test_wings_plans.py -q` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Same plus `tests/unit/test_wings_decisions.py tests/unit/test_wings_decisions_b.py tests/unit/test_wings_decisions_c.py tests/host/test_wings_brain.py tests/host/test_wings_brain_b.py tests/host/test_wings_brain_c.py` → PASS (update registry-list assertions for the four new names).
- [ ] **Step 5:** Commit `feat(wings): reinforce, feint, screen and flank decisions`.

---

### Task 3: Hold branch, formation, brain wiring

**Files:**
- Modify: `engine/wings/tree.py` (hold branch at priority 4; later branches shift by one), `engine/compat/wing_library/Conditions/ConditionWing.py` (docstring kinds), `engine/wings/roster.py` (Wing latch/cooldown fields, Member.hold flag if needed), `engine/wings/brain.py`, `engine/wings/allies.py` (formation)
- Test: `tests/host/test_wings_brain_d.py`, `tests/host/test_wings_tree.py`, `tests/unit/test_wings_allies.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - Tree order: ram 1, flee 2, withdraw 3, **hold 4**, guard 5, fallback 6, reserve 7, attack 8, rejoin 9, stock 10.
  - `allies.formation_points(hold_point, toward, n, spread_gu) -> list[tuple]` — index 0 is the hold point itself (the commander's); the rest evenly spaced on a ring of radius `spread_gu` in the plane perpendicular to `toward − hold_point` (any perpendicular basis when degenerate).
  - Wing fields: `reinforce_ally`, `reinforce_since`, `reinforce_done: dict[str, float]` (ally → cooldown-until game time), `feint_ally`, `feint_cooldown_until: float = -1.0`, `feint_quiet_since: float | None`, `decision_since: float`, `hold_prev: tuple | None` (hold point + assignment for incumbency).

Brain behaviour (spec §4–§6):
- Fill the Context latch/cooldown fields from the wing before `pick`; after `choose`, update them (start/stop reinforce/feint, mark `reinforce_done[ally] = now + reinforce_cooldown_s` when reinforce ends by cap, start the feint cooldown when a feint ends for any reason, track `feint_quiet_since`, `decision_since` on decision change).
- With `choice.hold_point`: every non-player member (commander included) is in the hold set: commander → formation point 0; others assigned with `attack.assign_slots(..., prev=...)` (incumbency while the hold point moved < `hold_spread_gu`); push `"hold"` True; guards, fallers, slots and rejoin pushed off; the held reserve keeps `wing.reserve` and its flag but pushes `"reserve"` False this tick (hold outranks it anyway; keep exclusivity: exactly one branch on). Target writes: `{}` for `hold_kind == "feint"`, else as normal.
- Without a hold: push `"hold"` False for everyone; existing behaviour byte-identical.
- `_stand_down` / leaderless: push `"hold"` False, clear reinforce/feint state (feint cooldown starts), `status = None` (Task 1).
- Log `"%s %s -> %s"` on hold start (kind, ally) and `"%s %s ends"`.
- [ ] **Step 1: Failing tests:** tree order test; formation geometry unit tests (n=1, n=2, n=8, degenerate); host: two-wing scene (copy `tests/host/test_wings_brain_b.py` / `_c.py` helpers, give both wings the same `side`) — reinforce writes the far primary into the idle wing's target group and its commander's `ship.GetTarget()` becomes it after the AI runs; screen/flank put every non-player member including the commander on "hold" with ring points, guard/fallback/attack/rejoin off; feint writes `{}` and ends when the ally becomes engaged; ally death mid-reinforce ends it next tick; the player is never given a hold point (player's group wing); 1- and 2-member hold; reserve + hold exclusivity; latch state survives a tick and clears on stand-down.
- [ ] **Step 2:** `uv run pytest tests/host/test_wings_brain_d.py tests/host/test_wings_tree.py tests/unit/test_wings_allies.py -q` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Same plus `tests/host/test_wings_brain.py tests/host/test_wings_brain_b.py tests/host/test_wings_brain_c.py tests/host/test_wings_reserve.py tests/host/test_wings_moveto.py tests/host/test_qb_wings.py tests/host/test_wings_allies.py` → PASS (tree priority renumbering will touch existing tree tests).
- [ ] **Step 5:** Commit `feat(wings): hold branch and side coordination`.

---

### Task 4: Behaviour tests and docs

**Files:**
- Create: `tests/host/test_wings_phase_d_behaviour.py`
- Modify: `CLAUDE.md` ("Wing leaders" row, within its ~1200-character budget — rewrite, don't append), `docs/reference/engine/perf-cadences-and-latency.md` §8 (one line: ally statuses are up to one brain period old), the Phase D spec (§11 build rulings if any).

Behaviour tests (spec §9; headless, 3 seeds, generous bounds, each with a control where the decision is unregistered via `decisions.register`/`reset_registry` or a dial; step the sim the way `tests/host/test_wings_phase_c_behaviour.py` `_step` does so combat deals damage; unset `OPEN_STBC_HOST_HEADLESS` like the Phase C file if radii matter):
- (a) `test_idle_wing_reinforces_losing_ally`: wing B (2 ships) fighting 5 enemies 600 GU from idle wing A (4 ships); within 60 s A's commander is within `leash_gu` of B's commander; control: A's commander stays > 400 GU away.
- (b) `test_idle_wing_flanks_even_fight`: B (4) vs 4 enemies, A (4) idle 600 GU off on the same side as B; when A first comes within `engage_gu` of the enemy centroid C, the angle at C between A's and B's anchors is ≥ 60° on ≥ 2 of 3 seeds and its mean over seeds exceeds the control's mean by ≥ 20°.
- (c) `test_feint_draws_enemy_onto_ally`: wing W (4) fighting 3 enemies, idle ally F (4) 500 GU away; after 40 s the enemy centroid's distance to F's anchor is smaller than in the control (feint unregistered) on ≥ 2 of 3 seeds, by ≥ 50 GU on average.
- [ ] **Step 1:** Write the tests; run `uv run pytest tests/host/test_wings_phase_d_behaviour.py -q`. If a behaviour does not emerge, find out why: fix it in the owning module (separate commit, before/after numbers in the report) or fix the test when the test is wrong; never weaken an assertion until it says nothing.
- [ ] **Step 2:** Docs; `uv run pytest tests/docs -q`.
- [ ] **Step 3:** Run once: `tests/host/test_wings_phase_b_behaviour.py tests/host/test_wings_phase_c_behaviour.py tests/host/test_wings_combat_stress.py`.
- [ ] **Step 4:** Commit `test(wings): phase D behaviour; docs`.
