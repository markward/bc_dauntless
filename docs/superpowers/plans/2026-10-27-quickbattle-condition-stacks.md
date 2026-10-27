# Quick Battle Condition Stacks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace phase 1's named battle types (Elimination, Kobayashi Maru) with a Victory stack and a Defeat stack of conditions, end to end: model, setup panel, page, battle evaluation, AI targeting, markers, objectives and lines.

**Architecture:** `engine/quickbattle/victory.py` becomes the condition model (pure, no App). `scenario.py` stores it, saves it in presets and turns it into `BattlePlan.victory` (a tuple of `ConditionOrder`). The setup panel exposes verbs and a payload; the page renders layout B. `battle_end.py` arms one battle from the plan's conditions and ends it through phase 1's single ending path; `km_targeting.py` generalises to many protected ships and gains the friendly-side mirror.

**Tech Stack:** Python 3 (engine, pytest), plain JS + CSS in CEF (`native/assets/ui-cef/`, tested under node), BC SDK Quick Battle scripts (wrapped, never edited).

**Spec:** `docs/superpowers/specs/2026-10-27-quickbattle-victory-defeat-conditions-design.md` (approved by Mark 2026-10-27). It replaces the types of `docs/superpowers/specs/2026-10-23-quickbattle-victory-conditions-design.md`, whose §4 battle-end machinery still applies. Mockup: `docs/superpowers/specs/2026-10-27-quickbattle-conditions-mockup.html`.

## Global Constraints

- Work only in the worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/qb-victory-p1`, branch `feat/qb-victory-p1`.
- No SDK edits. Wrap at the existing seams (`spawn.py`, `battle_end.install`, `km_targeting`).
- Never run destructive git (`checkout -- <path>`, `checkout .`, `restore`, `stash`, `clean`, `reset --hard`, `add -A`, `add .`). Stage explicit paths. Never stage `uv.lock`, `build.log`, `build-configure.log`, `build/`, `.superpowers/`, `mods/`.
- Commit with `git commit -F <file>`; the message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Run only explicit test files with `.venv/bin/python -m pytest <files> -q`. Never a directory, never an empty file list, never `scripts/check_tests.sh`.
- Do not reconfigure cmake. No C++ changes are in scope.
- New dialogue goes into `tools/dialogue/dauntless_crew.json`, then `tools/gen_dauntless_tgl.py --write`; never hand-edit the TGL.
- No game-state mutation in `render_payload`.
- Copy, verbatim:
  - stack headings `Victory` / `Defeat`; hints `Any one of these wins` / `Any one of these loses`;
  - defaults `Destroy All Ships` / `Player Ship Destroyed`, tag `Default`;
  - condition names `Ships Destroyed` / `Timer`; buttons `+ Add ship` / `+ Add condition`;
  - Ships sentence: `Win when` / `Lose when`, then the ANY|ALL toggle, then `of these is destroyed` (ANY) or `of these are destroyed` (ALL);
  - Timer sentence: `Win when` / `Lose when`, the stepper showing `<N> min`, then `run out`;
  - Start problems: `Add an enemy ship to start` (exists), `A Ships Destroyed condition has no ships`.
- Timer minutes: whole numbers 1 to 60; a new Timer starts at 5. A new Ships Destroyed starts empty, mode `any`.
- E6M1 priorities stay `PROTECTED_TARGET_PRIORITY = 2.0`, `OTHER_TARGET_PRIORITY = 1.0`.

## Rulings made while planning (spec silent or builder's)

- Objectives use no articles: "Destroy Galor or Keldon", "Protect Freighter and USS Zhukov" (phase 1's `Protect %s` had none; a class title vs a registry name can't be told apart reliably). Lists join as `A`, `A and B`, `A, B and C`; more than 3 names: `A, B, C and 2 more`. ANY joins with `or` on Victory and `and` on Defeat; ALL the reverse (§5.4 table).
- A Ships Destroyed condition whose ships are all missing from the ship catalog is dropped from the battle plan (logged); Start is not blocked by it (an uncatalogued ship already spawns nothing).
- Equal Victory and Defeat timers: the Victory timer is not scheduled at all, so the Defeat timer settles it as a loss (spec §4.2).

## Review Focus

1. A listed ship removed from the setup, or its group's allegiance changed so the stack no longer allows it: it drops out; an emptied list blocks Start with the copy above (Task 1 `test_reconcile_drops_removed_and_ineligible_ships`).
2. The protected Freighter dies 0.3 s after the last enemy: the pending win becomes a loss (Task 5 `test_defeat_after_pending_win_overturns_it`).
3. One ship in two Defeat conditions (ANY and ALL): its death counts in both (Task 5 `test_ship_counts_in_every_condition_listing_it`).
4. A Victory ALL list naming a late warp-in ship: no win until it has arrived and died (Task 5 `test_victory_all_waits_for_late_target`).
5. A phase 1 Kobayashi Maru preset, and a preset holding one malformed condition: the first converts, the second keeps its good conditions (Task 1 `test_phase1_kobayashi_maru_converts`, `test_malformed_condition_dropped_others_kept`).

## Temporary red between tasks

Task 1 changes the model the panel, page and battle code read. Until the task that owns each consumer lands, these phase 1 tests may fail and are rewritten by that task, not patched earlier:
`tests/unit/test_quick_battle_setup_panel.py` victory tests (Task 2), `tests/ui/test_qb_victory_view_js.py` and `tests/unit/test_quick_battle_setup_page.py` (Task 3), `tests/host/test_qb_battle_end.py` (Task 5), `tests/host/test_qb_km_targeting.py` (Task 6), `tests/integration/test_quickbattle_setup_e2e.py` (Task 7). Each task's reviewer runs that task's files only. Task 7 runs all of them.

---

### Task 1: Condition model, scenario, presets and battle plan

**Files:**
- Rewrite: `engine/quickbattle/victory.py`
- Modify: `engine/quickbattle/scenario.py` (`Scenario.victory`, `to_json`, `from_json`, `_strip_ids`, `VictoryOrder`, `BattlePlan`, `battle_plan`, `can_start`)
- Rewrite: `tests/unit/test_qb_victory.py`
- Modify: `tests/unit/test_qb_presets.py`

**Interfaces — Produces (later tasks rely on these exact names):**
- Constants: `VICTORY = "victory"`, `DEFEAT = "defeat"`, `SIDES = (VICTORY, DEFEAT)`, `SHIPS = "ships"`, `TIMER = "timer"`, `ANY = "any"`, `ALL = "all"`, `MIN_MINUTES = 1`, `MAX_MINUTES = 60`, `DEFAULT_MINUTES = 5`, `NO_ENEMY_PROBLEM`, `EMPTY_SHIPS_PROBLEM = "A Ships Destroyed condition has no ships"`.
- `@dataclass Condition: id: str; side: str; kind: str; mode: str = ANY; ships: list (Entry ids); minutes: int = DEFAULT_MINUTES`
- `@dataclass Victory: conditions: list` (default empty) — the defaults are implicit, never stored.
- `eligible(scenario, side) -> list[(Group, Entry)]`: Victory = non-player entries of enemy groups; Defeat = non-player entries of friendly and neutral groups. Group then entry order.
- `conditions(scenario, side) -> list[Condition]`; `find(scenario, cid) -> Optional[Condition]`; `has_timer(scenario, side) -> bool`.
- `add_condition(scenario, side, kind) -> Optional[Condition]` (None: bad side/kind, or a second Timer on that side).
- `remove_condition(scenario, cid) -> bool`; `set_mode(scenario, cid, mode) -> bool` (Ships only); `add_ship(scenario, cid, entry_id) -> bool` (eligible for its side, not already listed); `remove_ship(scenario, cid, entry_id) -> bool`; `set_minutes(scenario, cid, minutes) -> bool` (Timer only; `type(minutes) is int`, 1..60).
- `reconcile(scenario) -> None`: drops ships no longer eligible for their condition's side. Never removes a condition.
- `start_problem(scenario) -> Optional[str]`: no enemy → `NO_ENEMY_PROBLEM`; else any Ships condition with no ships → `EMPTY_SHIPS_PROBLEM`; else None.
- `summary_suffix(scenario) -> str`: `""` with no conditions; otherwise `" · " + parts + " condition(s)"`, parts = `"<n> victory"` and/or `"<n> defeat"` (non-zero only) joined by `" · "`, the word `condition` when the total is 1 else `conditions`. Examples: `" · 1 victory · 2 defeat conditions"`, `" · 1 defeat condition"`.
- `to_json(v) -> dict` = `{"conditions": [{"id", "side", "kind", "mode", "ships", "minutes"}]}`; `from_json(d) -> Victory`, lenient (below).
- `scenario.py`: `@dataclass(frozen=True) ConditionOrder: side: str; kind: str; mode: str; entry_ids: tuple; time_s: float`; `VictoryOrder` becomes `@dataclass(frozen=True) VictoryOrder: conditions: tuple = ()`; `BattlePlan.victory: VictoryOrder = VictoryOrder()`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_qb_victory.py` (replace the phase 1 file; build scenarios with `sc.default_scenario()`, `add_group`, `update_details`, `add_ship` as the old file does). Each asserts exactly:
  - `test_new_scenario_has_no_conditions`: `s.victory.conditions == []`, `start_problem` is `NO_ENEMY_PROBLEM` before an enemy is added and None after.
  - `test_eligible_ships_by_side`: with an enemy Galor, a neutral Freighter and a friendly Akira: Victory eligible is exactly the Galor entry; Defeat eligible is exactly the Akira then the Freighter in group order; the player never appears.
  - `test_add_ships_condition_defaults`: `add_condition(s, DEFEAT, SHIPS)` returns a Condition with `mode == ANY`, `ships == []`; `start_problem(s) == EMPTY_SHIPS_PROBLEM`; after `add_ship` of the Freighter it is None.
  - `test_one_timer_per_side`: a second `add_condition(s, VICTORY, TIMER)` returns None; a Defeat Timer is still allowed; the new Timer's `minutes == 5`.
  - `test_add_ship_refuses_ineligible_and_duplicates`: adding the Galor to a Defeat condition, the Freighter to a Victory one, or the same ship twice each returns False and leaves the list unchanged.
  - `test_set_minutes_bounds`: 0, 61, `"5"` and `5.0` refused; 1 and 60 accepted.
  - `test_set_mode_only_on_ships`: `set_mode` on a Timer is False; `"all"` on Ships sets `ALL`; `"both"` refused.
  - `test_reconcile_drops_removed_and_ineligible_ships`: a Defeat list holding the Freighter and the Akira; remove the Akira's entry (`s.remove_entry`) and change the Freighter's group to enemy (`update_details`); after `reconcile`, the condition still exists with `ships == []` and `start_problem == EMPTY_SHIPS_PROBLEM`.
  - `test_summary_suffix`: no conditions → `""`; one Victory Ships + two Defeat (Ships, Timer) → `" · 1 victory · 2 defeat conditions"`; only one Defeat Timer → `" · 1 defeat condition"`.
  - `test_json_round_trip`: `from_json(to_json(v))` equals `v` for two conditions, ids included.
  - `test_phase1_kobayashi_maru_converts`: `from_json({"type": "kobayashi_maru", "protect": "e1", "time_limit_min": 3})` gives exactly a Defeat Ships ANY with `ships == ["e1"]` and a Defeat Timer with `minutes == 3`; `{"type": "elimination", ...}` gives `[]`.
  - `test_malformed_condition_dropped_others_kept`: a list holding one good Victory Timer, one with `side: "middle"`, one Ships with `ships: "e1"` (not a list), one Timer with `minutes: 0`, and a second Victory Timer → exactly the first Timer survives.
  - `test_battle_plan_carries_conditions`: a scenario with a Victory Ships ALL [Galor] and a Defeat Timer 2 min → `plan.victory.conditions == (ConditionOrder("victory","ships","all",(galor_eid,),0.0), ConditionOrder("defeat","timer","any",(),120.0))`.
  - `test_battle_plan_drops_uncatalogued_ship_condition`: a Defeat Ships list whose only ship is not in the catalog index is absent from `plan.victory.conditions`.
  - In `tests/unit/test_qb_presets.py` add `test_preset_round_trip_keeps_conditions`: save and reload a scenario with a Defeat Ships ANY [Freighter]; `same_setup` is True; changing its mode to ALL makes `same_setup` False.

- [ ] **Step 2: Run them, watch them fail on assertions** (not only on import errors; stub the new names first if needed so the failures are real):
  `.venv/bin/python -m pytest tests/unit/test_qb_victory.py tests/unit/test_qb_presets.py -q`

- [ ] **Step 3: Implement** the Interfaces above.
  - `from_json`: a dict with `"type"` is the phase 1 shape and converts as in the test (time limit clamped into 1..60, ignored when 0); otherwise read `"conditions"` and drop, with one `_log.warning` each, any entry that is not a dict, has an unknown side/kind/mode, non-list or non-string ships, a Timer whose minutes are not an int in 1..60, or a second Timer on a side. A missing id gets `scenario.new_id()`-style `secrets.token_hex(4)`.
  - `scenario.from_json` calls `victory.reconcile(s)` after building (as now). `_strip_ids` replaces each condition's id and maps each ship id to its `(group index, entry index)`, as phase 1 does for `protect`.
  - `Scenario.remove_entry`, `move_entry` and `update_details` stay unaware of conditions; the panel calls `reconcile` after every change (Task 2).
  - `battle_plan`: one `ConditionOrder` per condition, in stored order; Ships `entry_ids` keep only ids that produced a `SpawnOrder`; drop the condition (log) when none remain; Timer `time_s = minutes * 60.0`, `mode` stored as-is (`any`), `entry_ids = ()`.

- [ ] **Step 4: Run Step 2's command.** Expected: all pass.

- [ ] **Step 5: Commit** `engine/quickbattle/victory.py engine/quickbattle/scenario.py tests/unit/test_qb_victory.py tests/unit/test_qb_presets.py` — `feat(qb): victory and defeat condition model replaces battle types`.

---

### Task 2: Setup panel verbs and payload

**Files:**
- Modify: `engine/ui/quick_battle_setup_panel.py` (`_after_change`, `_victory_payload`, `_summary`, the victory verb handlers and the verb table)
- Modify: `tests/unit/test_quick_battle_setup_panel.py` (replace the phase 1 victory tests)

**Interfaces:**
- Consumes: Task 1's `victory` functions.
- Produces — verbs (arg after the first `:`; two-part args split with `partition(":")`):
  `victory-view` (unchanged), `cond-add:<side>:<kind>`, `cond-remove:<cid>`, `cond-mode:<cid>:<any|all>`, `cond-ship-add:<cid>:<eid>`, `cond-ship-remove:<cid>:<eid>`, `cond-minutes:<cid>:<n>`. `victory-type`, `victory-protect` and `victory-time` are removed.
- Produces — payload key `victory`:
  ```
  {"stacks": [S_victory, S_defeat]}
  S = {"side": "victory"|"defeat", "can_add_timer": bool, "conditions": [C, ...]}
  C = {"id", "kind": "ships"|"timer", "mode": "any"|"all", "minutes": int,
       "ships":   [R, ...],     # listed, in list order
       "addable": [R, ...]}     # eligible for this side and not listed, eligible() order
  R = {"id", "title", "group_name", "allegiance", "icon"}   # icon as _icon(ce.icon), None off-catalog
  ```

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_quick_battle_setup_panel.py` (replace every test that used `victory-type`, `victory-protect` or `victory-time`; keep using the file's existing panel fixture):
  - `test_cond_add_and_remove`: `cond-add:defeat:ships` returns True and the payload's defeat stack has one condition with `kind == "ships"`, `ships == []`; `cond-remove:<id>` empties it; `cond-add:middle:ships` and `cond-add:victory:laser` return False.
  - `test_cond_timer_once_per_side`: after `cond-add:victory:timer`, the victory stack's `can_add_timer` is False and a second `cond-add:victory:timer` returns False; the defeat stack's stays True.
  - `test_cond_ship_add_remove_and_addable`: with a neutral Freighter and an enemy Galor, a defeat Ships condition's `addable` lists only the Freighter (with `title`, `group_name`, `allegiance == "neutral"` and an `icon` key); after `cond-ship-add:<cid>:<freighter>` it moves to `ships` and `addable` is empty; `cond-ship-add` of the Galor returns False.
  - `test_cond_mode_and_minutes_verbs`: `cond-mode:<cid>:all` sets `mode`; `cond-minutes:<cid>:7` sets `minutes == 7`; `cond-minutes:<cid>:x` and `:0` return False.
  - `test_summary_reports_conditions_and_problems`: with an enemy and no conditions the summary has no condition suffix; an empty Ships condition makes the summary exactly `"A Ships Destroyed condition has no ships"` and the start control disabled; adding a ship gives a summary ending `" · 1 defeat condition"`.
  - `test_removing_a_listed_ship_drops_it`: remove the listed Freighter's entry through the panel's remove verb; the condition's `ships` is `[]`.
  - `test_old_victory_verbs_gone`: `victory-type:kobayashi_maru` returns False.

- [ ] **Step 2: Run, watch them fail:** `.venv/bin/python -m pytest tests/unit/test_quick_battle_setup_panel.py -q`

- [ ] **Step 3: Implement.** `_after_change` calls `vic.reconcile` (no notice any more: the condition model has no fallback). `_summary` = existing notice, else `start_problem`, else counts + `vic.summary_suffix(s)`. Handlers go through the existing `_victory_set`-style helper that calls `_after_change` on success.

- [ ] **Step 4: Run Step 2's command.** Expected: all pass.

- [ ] **Step 5: Commit** `engine/ui/quick_battle_setup_panel.py tests/unit/test_quick_battle_setup_panel.py` — `feat(qb): setup panel verbs and payload for condition stacks`.

---

### Task 3: The page — layout B

**Files:**
- Modify: `native/assets/ui-cef/index.html` (replace `#qbs-vtypes` / `#qbs-vbody` with one `<main id="qbs-vcond" class="vc-cols" hidden>` holding `<div id="qbs-vc-victory" class="vc-col">` and `<div id="qbs-vc-defeat" class="vc-col">`)
- Modify: `native/assets/ui-cef/js/quick_battle_setup.js` (`renderVictory`, `qbsClick` cases, two menus)
- Modify: `native/assets/ui-cef/css/quick_battle_setup.css` (replace the phase 1 `vc-type*`, `vc-pick`, `vc-blurb` rules with the mockup's `vc-*` rules, scoped under `#quick-battle-setup`)
- Rewrite: `tests/ui/test_qb_victory_view_js.py`; Modify: `tests/unit/test_quick_battle_setup_page.py`

**Interfaces:**
- Consumes: Task 2's payload and verbs.
- The look is `docs/superpowers/specs/2026-10-27-quickbattle-conditions-mockup.html`: copy its `vc-*` CSS rules and markup shape. Ship rows use `qbsArt(r.icon)` (the ships view's art) inside the mockup's `.vc-ship`, with `--a` set from `qbsAllegianceColour(r.allegiance)`.
- Page-local actions (no Python verb): `cond-add-menu` (`data-side`) opens `qbsOpenMenu` with two `qbsItem`s, `Ships Destroyed` → `cond-add` arg `<side>:ships` and `Timer` → `<side>:timer` (Timer omitted when `can_add_timer` is false); `cond-ship-menu` (`data-cond`) lists the condition's `addable` rows → `cond-ship-add` arg `<cid>:<eid>`, or a disabled `qbs-menu__empty` "No ships to add" when empty.
- Python verbs are sent as `dauntlessEvent('quick-battle-setup/<verb>:<arg>')`, as today.

- [ ] **Step 1: Write the failing tests** in `tests/ui/test_qb_victory_view_js.py`, reusing the current file's node harness:
  - `test_view_toggle_hides_ships_view`: with `view: "victory"` the groups and main elements are hidden and `qbs-vcond` is shown; the cog has `qbs-victory-btn--on`.
  - `test_defaults_render_fixed_cards`: each column holds its heading, hint, and a `vc-cond--fixed` card with `Destroy All Ships` / `Player Ship Destroyed` and `Default`, and no remove button inside it.
  - `test_ships_condition_sentence_agrees`: a defeat Ships condition in ANY renders `Lose when`, the `cp-toggle--on` on ANY and `of these is destroyed`; the same in ALL renders `of these are destroyed`; a victory one renders `Win when`.
  - `test_ship_rows_with_art_and_remove`: a listed ship with an icon renders an `<img` (not `qbs-noart`), its title, group name, and a remove button whose click sends `quick-battle-setup/cond-ship-remove:<cid>:<eid>`.
  - `test_mode_toggle_and_remove_send_verbs`: clicking ALL sends `cond-mode:<cid>:all`; the card's × sends `cond-remove:<cid>`.
  - `test_timer_stepper`: a timer at 5 renders `5 min`, its − sends `cond-minutes:<cid>:4` and + sends `:6`; at 1 the − is disabled, at 60 the + is disabled.
  - `test_add_condition_menu`: clicking `+ Add condition` in the victory column opens the menu with `Ships Destroyed` and `Timer`; with `can_add_timer: false` only `Ships Destroyed`; clicking an item sends `cond-add:victory:ships`.
  - `test_add_ship_menu_lists_addable`: `+ Add ship` opens a menu of the `addable` titles; clicking one sends `cond-ship-add:<cid>:<eid>`.
  - In `tests/unit/test_quick_battle_setup_page.py` replace the `qbs-vtypes`/`qbs-vbody` assertions with: `index.html` has `id="qbs-vcond"`, `id="qbs-vc-victory"`, `id="qbs-vc-defeat"`; the CSS no longer has `.vc-type`; every `vc-` rule is scoped under `#quick-battle-setup`.

- [ ] **Step 2: Run, watch them fail:** `.venv/bin/python -m pytest tests/ui/test_qb_victory_view_js.py tests/unit/test_quick_battle_setup_page.py -q`

- [ ] **Step 3: Implement** to the mockup. Escape every payload string with `qbsEsc`.

- [ ] **Step 4: Run Step 2's command.** Expected: all pass.

- [ ] **Step 5: Commit** the five files — `feat(qb): victory view shows the two condition stacks (layout B)`.

---

### Task 4: New lines and the crosshair marker

**Files:**
- Modify: `tools/dialogue/dauntless_crew.json`, regenerate `native/assets/replacements/data/TGL/Dauntless Crew.tgl` with `.venv/bin/python tools/gen_dauntless_tgl.py --write`
- Modify: `engine/ui/target_markers.py` (`KINDS = frozenset({"protect", "target"})`)
- Modify: `native/assets/ui-cef/js/target_list.js` (render `row.marker === 'target'` as a crosshair SVG in a `target-list__marker--target` span), `native/assets/ui-cef/css/target_list.css` if the crosshair needs a rule
- Modify: `tests/unit/test_target_markers.py`, and the existing target-list JS/view test that covers the shield marker (find it with `grep -rln "target-list__marker" tests/`)

**Interfaces — Produces:** dialogue keys `SaffiQBProtectedLostAll1` = "The ships we were assigned to protect have been destroyed. Ending simulation." and `SaffiQBSurvived1` = "Time is up. We held them off. Ending simulation." (no `sound`, like phase 1's two Saffi lines); marker kind `"target"`.

- [ ] **Step 1: Write the failing tests:** `test_target_kind_accepted` (`set_marker("Galor-1", "target")` then `marker_for == "target"`; an unknown kind still raises `ValueError`); in the target-list test, a row with `marker: "target"` renders `target-list__marker--target` with an `<svg`, and a `protect` row still renders its shield. The dialogue drift test (`tests/tools/test_dauntless_dialogue_drift.py`) must pass after regeneration; add `test_new_saffi_lines_present` there or beside the existing text-only test (`tests/unit/test_crew_speech_text_only.py`) asserting both keys load with the exact texts above.
- [ ] **Step 2: Run, watch them fail:** `.venv/bin/python -m pytest tests/unit/test_target_markers.py tests/unit/test_crew_speech_text_only.py tests/tools/test_dauntless_dialogue_drift.py <the target-list test file> -q`
- [ ] **Step 3: Implement.** The crosshair matches the shield icon's size, stroke and colour (read the shield's SVG in `target_list.js:136`).
- [ ] **Step 4: Run Step 2's command.** Expected: all pass.
- [ ] **Step 5: Commit** the changed files — `feat(qb): crosshair target marker and two Saffi lines for condition endings`.

---

### Task 5: Battle evaluation from the condition stacks

**Files:**
- Modify: `engine/quickbattle/battle_end.py`
- Rewrite: `tests/host/test_qb_battle_end.py` (keep its world/helper style; replace `_km` with a helper that builds conditions through the panel verbs of Task 2)

**Interfaces:**
- Consumes: `plan.victory.conditions` (Task 1), marker kinds and line keys (Task 4). Targeting: keep calling phase 1's `km_targeting.arm(qb, plan, protected_name, present)` with the FIRST Defeat ship name (or not at all when there is none); Task 6 replaces this call.
- Produces:
  - reasons `REASON_ELIMINATION = "elimination"`, `REASON_TARGETS = "targets"`, `REASON_SURVIVED = "survived"`, `REASON_PLAYER = "player"`, `REASON_PROTECTED = "protected"`, `REASON_PROTECTED_ALL = "protected_all"`, `REASON_TIME = "time"`;
  - `BattleState` with `ended`, `won`, `reason` (as now) plus the armed conditions, so tests can read `state()`;
  - `protected_names() -> list` and `target_names() -> list` for the armed battle (object names), used by Task 6.

- [ ] **Step 1: Write the failing tests** (headless, real SDK Quick Battle, started through the setup panel as phase 1's tests do). Each asserts the ending through `state()` and the posted `ET_END_SIMULATION` int:
  - `test_elimination_default_still_wins`: no conditions; destroy every enemy → won, `REASON_ELIMINATION`.
  - `test_victory_ships_any_wins_on_first_kill`: Victory Ships ANY [Galor, Keldon] with a third enemy alive; destroy the Galor → won, `REASON_TARGETS`.
  - `test_victory_ships_all_needs_every_kill`: ALL [Galor, Keldon]; Galor alone → not ended; then Keldon → won.
  - `test_defeat_ships_any_loses`: Defeat ANY [Freighter, Akira]; destroy the Akira → lost, `REASON_PROTECTED`, the lose sequence speaks `SaffiQBProtectedLost1`.
  - `test_defeat_ships_all_loses_on_last`: Defeat ALL [Freighter, Akira]; first death → not ended; second → lost, `REASON_PROTECTED_ALL`, line `SaffiQBProtectedLostAll1`. ALL with one ship uses `REASON_PROTECTED`.
  - `test_ship_counts_in_every_condition_listing_it`: the Freighter in a Defeat ALL [Freighter] and a Defeat ANY [Freighter, Akira]; its death ends the battle lost.
  - `test_defeat_after_pending_win_overturns_it`: destroy the last enemy (win pending), then within `END_DELAY_S` destroy the protected Freighter → lost, `REASON_PROTECTED`, and only one `ET_END_SIMULATION` timer is live (int 1).
  - `test_player_death_still_beats_pending_win`: phase 1's behaviour kept.
  - `test_victory_timer_wins`: Victory Timer 1 min; tick the timer manager past 60 s → won, `REASON_SURVIVED`; the win sequence speaks `SaffiQBSurvived1` and not `QBFelixWin`.
  - `test_defeat_timer_loses`: Defeat Timer 1 min → lost, `REASON_TIME`, `SaffiQBTimeUp1`.
  - `test_equal_timers_lose`: both 2 min → lost, `REASON_TIME`.
  - `test_countdown_follows_earlier_timer`: Victory 3 min, Defeat 7 min → the countdown speaks exactly `E8M2Countdown3` at t = 0 s and `E8M2Countdown1` at t = 120 s (3 and 1 minutes left on the 3-minute timer; phase 1's rule of scheduling every listed minute that fits inside the limit), and nothing for the 7-minute timer.
  - `test_victory_all_waits_for_late_target`: Victory ALL [Galor (now), Vorcha in a group warping in at 1 min]; destroy the Galor → not ended; let the Vorcha arrive and destroy it → won.
  - `test_markers_and_objectives`: Defeat ANY [Freighter] → `marker_for("Freighter-2") == "protect"`; Victory ANY [Galor] → `"target"`; the Objectives submenu lists exactly `Destroy all enemy ships`, `Destroy Galor`, `Protect Freighter` (plus a timer line when one is present: `Survive for 5 min` / `Win within 5 min`); End Combat clears markers and objectives.
  - `test_unarmed_battle_keeps_bc_win`: no plan → BC's own win branch (pins phase 1 Ruling 4).

- [ ] **Step 2: Run, watch them fail:** `.venv/bin/python -m pytest tests/host/test_qb_battle_end.py -q`

- [ ] **Step 3: Implement.**
  - `begin` resolves every Ships condition's entry ids to object names with `naming.object_name(order.title, n)` (n = the order's 1-based plan index, as `_protected_order` does today) and records the object id of each ship that exists at begin (late ships: name only), so a same-named stranger never counts.
  - On each ship death (the existing `_before_bc` step, before BC's handler): mark it destroyed in every condition listing it; then evaluate Defeat conditions first, then Victory. A met Defeat condition ends the battle lost — and if a WIN is pending (ended, won, end timer not yet fired), cancel that timer and end lost instead. A met Victory condition ends it won only if nothing has ended. Never overturn a pending loss.
  - Timers: one TGTimer per side's Timer, on the existing event type and handler, with distinct int keys for victory time-up and defeat time-up; skip scheduling the Victory timer when it is not earlier than the Defeat timer; the countdown is scheduled against the earlier scheduled timer only.
  - Lines: extend `_LOSE_LINES` with `REASON_PROTECTED_ALL`; the win wrapper plays `SaffiQBSurvived1` from the XO (mirroring `_lose_sequence`'s speak action and BC's `GenerateWinSequence` shape) instead of BC's Felix line when the reason is `REASON_SURVIVED`, then the existing win tail.
  - Objectives and markers per the Rulings section and spec §5.4.
  - Targeting: as in Interfaces (first Defeat ship only, until Task 6).
- [ ] **Step 4: Run Step 2's command**, plus `tests/host/test_qb_late_arrivals.py tests/host/test_qb_spawn.py`. Expected: all pass.
- [ ] **Step 5: Commit** `engine/quickbattle/battle_end.py tests/host/test_qb_battle_end.py` — `feat(qb): battles end from the victory and defeat stacks`.

---

### Task 6: AI targeting for many protected ships and for hunting targets

**Files:**
- Modify: `engine/quickbattle/km_targeting.py`, `engine/quickbattle/battle_end.py` (the `arm` call), `engine/quickbattle/late_arrivals.py` (`ship_arrived` call stays; only if its signature changes)
- Rewrite: `tests/host/test_qb_km_targeting.py`

**Interfaces:**
- Consumes: `battle_end.protected_names()`, `battle_end.target_names()` (Task 5).
- Produces: `arm(qb, plan, protected_names: list, target_names: list, present: set) -> None` (`present` = the names that exist at arm time); `enemy_target_group()` and `friendly_target_group()` (each the armed `ObjectGroupWithInfo` or None); `ship_arrived(qb, name)` and `reset()` as today.
- Mechanism, unchanged in kind: while armed, wrapped `CreateAI` of each AI module the plan's enemies (side `Enemy`, via `spawn._details`) and friendlies (side `Friendly`) use, redirects `App.ObjectGroup_FromModule("QuickBattle.QuickBattle", "pFriendlies")` (for a ship in `pEnemies`) to the enemy group, and `(..., "pEnemies")` (for a ship in `pFriendlies`) to the friendly group, for that one call only.
- Enemy group: every `protected_names` entry at `{"Priority": 2.0}` first (in list order), then every `pFriendlies` member at `{"Priority": 1.0}`. Friendly group: every `target_names` entry at 2.0 first, then every `pEnemies` member at 1.0. A group is built only when its name list is non-empty; otherwise that side's AI is never wrapped and stays stock.
- Late arrivals: a late protected or target name joins its group at 2.0 and moves to the front among the 2.0 names (`_put_first`); late friendlies/enemies join the matching group at 1.0.

- [ ] **Step 1: Write the failing tests** (keep the file's `_target_group`, `_select_target` helpers and the stray-module rule in its restart test):
  - `test_enemy_group_weights_every_protected_ship`: Defeat ANY [Freighter (neutral), Akira (friendly)] and a Warbird → the Warbird's target group has both at 2.0, first, the player at 1.0.
  - `test_enemy_prefers_protected_when_equal`: phase 1's SelectTarget test, kept.
  - `test_friendly_group_weights_targets`: Victory ANY [Galor] with a second enemy Keldon and a friendly Akira → the Akira's target group has the Galor at 2.0 first and the Keldon at 1.0.
  - `test_friendly_prefers_target_when_equal`: the friendly Akira equidistant from the Galor and the Keldon, no damage → the real SelectTarget picks the Galor.
  - `test_no_conditions_targeting_is_stock`: no conditions → the Warbird's group `is QB.pFriendlies` and the Akira's `is QB.pEnemies`.
  - `test_neutral_protected_keeps_neutral_affiliation`: kept from phase 1.
  - `test_late_arrivals_join_groups`: a late friendly joins the enemy group at 1.0; a late target joins the friendly group at 2.0, first.
  - `test_restart_into_no_conditions_is_stock`: after End Combat both groups are None and no `CreateAI` keeps the wrap mark (check `sys.modules["QuickBattle.QuickBattleAI"]` and `sys.modules["QuickBattle.QuickBattleFriendlyAI"]`; never `__import__` an AI module by bare name — see the existing comment).
  - `test_sync_failure_does_not_abort_ai_assignment`: kept.
- [ ] **Step 2: Run, watch them fail:** `.venv/bin/python -m pytest tests/host/test_qb_km_targeting.py -q`
- [ ] **Step 3: Implement**, then switch `battle_end.begin` to the new `arm` signature.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/host/test_qb_km_targeting.py tests/host/test_qb_battle_end.py tests/host/test_qb_late_arrivals.py tests/integration/test_quickbattle_station_defends.py -q`. Expected: all pass.
- [ ] **Step 5: Commit** — `feat(qb): enemies weight every protected ship; friendlies weight hunt targets`.

---

### Task 7: End to end, docs, and the full focused sweep

**Files:**
- Modify: `tests/integration/test_quickbattle_setup_e2e.py`
- Modify: `CLAUDE.md` (the Quick Battle row: name the condition stacks in place of "victory.py holds the victory settings"; the row must stay under the doc-consistency test's length limit)
- Modify: `docs/superpowers/specs/2026-10-27-quickbattle-victory-defeat-conditions-design.md` (Status: built, not live-verified)
- Modify: `docs/superpowers/specs/2026-10-01-quickbattle-redesign-roadmap.md` (the 2c row names the condition stacks)

- [ ] **Step 1: Write the failing end-to-end tests**, entering at the setup panel (verbs) and running real Quick Battles:
  - `test_hunt_scenario_end_to_end`: enemy Galor + Keldon; Victory Ships ANY [Galor]; start; destroy the Galor → `ET_END_SIMULATION` int 2, Felix's win line, markers and objectives cleared after End Combat.
  - `test_three_protected_end_to_end`: three neutral transports in Defeat ANY plus a Defeat Timer 2 min; destroying one → loss with `SaffiQBProtectedLost1`.
  - `test_preset_round_trip_end_to_end`: save the hunt setup as a preset, load it into a fresh panel, start, and the plan carries the same conditions.
  - Replace phase 1's Kobayashi Maru end-to-end cases with their condition-stack equivalents.
- [ ] **Step 2: Run, watch them fail:** `.venv/bin/python -m pytest tests/integration/test_quickbattle_setup_e2e.py -q`
- [ ] **Step 3: Implement** whatever the end-to-end tests expose (fixes go in the owning module), then the docs.
- [ ] **Step 4: Run the full focused sweep:**
  `.venv/bin/python -m pytest tests/unit/test_qb_victory.py tests/unit/test_qb_presets.py tests/unit/test_quick_battle_setup_panel.py tests/unit/test_quick_battle_setup_page.py tests/ui/test_qb_victory_view_js.py tests/unit/test_target_markers.py tests/unit/test_crew_speech_text_only.py tests/tools/test_dauntless_dialogue_drift.py tests/host/test_qb_battle_end.py tests/host/test_qb_km_targeting.py tests/host/test_qb_late_arrivals.py tests/host/test_qb_spawn.py tests/integration/test_quickbattle_setup_e2e.py tests/integration/test_quickbattle_station_defends.py tests/integration/test_quickbattle_target_chain.py tests/integration/test_home_stations_quickbattle.py tests/docs/test_doc_consistency.py -q`
  Expected: all pass.
- [ ] **Step 5: Commit** — `test(qb): condition stacks end to end; docs`.
