# Quick Battle Victory Conditions, Phase 1: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the ⚙ victory view to the Quick Battle setup screen with two battle types, **Elimination** and **Kobayashi Maru**, and make every Quick Battle end on a win or a loss.

**Architecture:**
- A pure `engine/quickbattle/victory.py` holds the victory settings. They ride on the `Scenario`, and so in presets, and they gate Start Battle.
- The panel and page add a second view.
- A runtime module, `engine/quickbattle/battle_end.py`, wraps three QuickBattle SDK functions, the same way `spawn.install_*_hook` already does. It owns win and lose. It ends a battle by posting BC's own `ET_END_SIMULATION` (int 2 = win, int 1 = loss) to the XO on a 1-second timer, exactly as BC's player-death path does.

**Tech Stack:** Python 3 (engine), Quick Battle SDK scripts (Python 1.5 originals, wrapped and never edited), CEF page (vanilla JS/CSS), pytest. JS is tested under node with a fake DOM.

**Spec:** `docs/superpowers/specs/2026-10-23-quickbattle-victory-conditions-design.md`. Phase 1 = spec §11 item 1, meaning §3, §4.1, §4.2, §4.4, §4.5 and §5.1–5.2. Phases 2–4 (Transporter, beam, Capture the Flag, Starbase Assault) are out of scope.

**Branch:** all work goes on `feat/qb-victory-p1`, never on `main`.

## Global Constraints

- **No SDK edits.** Wrap module attributes once per load; the existing hooks show the pattern (`engine/quickbattle/spawn.py:451` `install_generate_ships_hook`). Mark each wrapper with an `_dauntless_*_orig` attribute so a second install is a no-op.
- **Run only the focused test files named in each task.** Never `tests/`, `tests/unit` or `tests/ui` whole, and never `scripts/check_tests.sh` (the gate runs only on the main merge, when Mark says so). Never pass pytest an empty file list.
- **Never run destructive git:** `checkout -- <path>`, `restore`, `stash`, `clean`, `reset --hard`, `add -A`/`add .`. Stage explicit paths only.
- All battle clocks run on **game time** through `App.g_kTimerManager`, so they freeze under pause.
- No game-state mutation inside any `render_payload` (`docs/engine/perf-cadences-and-latency.md`).
- **Phase 1 lists only two cards**, Elimination and Kobayashi Maru (my call: unbuilt types don't appear until their phase lands).
- **Exact copy** (Mark's words are marked; the rest are my calls and must be used verbatim):
  - Elimination card: `Destroy every enemy to win.` (Mark)
  - Kobayashi Maru card: `Destroy every enemy and keep one ship alive`
  - Kobayashi Maru greyed-out reason: `Add a friendly or neutral ship first`
  - Kobayashi Maru rule line: `You win when every enemy is destroyed. You lose if the ship you protect is destroyed, or you are.`, plus ` You also lose if time runs out.` when a time limit is set
  - Start blocked, no enemy: `Add an enemy ship to start`
  - Fallback notice: `Kobayashi Maru needs a ship to protect; switched to Elimination`
  - Footer summary: `<n> groups · <n> ships`, plus ` · Kobayashi Maru · protect <name>` for Kobayashi Maru
  - Objectives: `Destroy all enemy ships`, `Protect <name>`, `Win within <n> min`
  - Protected-ship loss line, key `SaffiQBProtectedLost1`: `The ship we were assigned to protect has been destroyed. Ending simulation.` (Mark)
  - Time-up loss line, key `SaffiQBTimeUp1`: `We have run out of time. Ending simulation.`
- New dialogue lines are **subtitle-only** (no voice file yet).

## Review Focus

1. **A protected ship edited away.** Removing the ship, moving it to an enemy group, or making it the player's ship must fall back to Elimination with the notice, never leave a battle with no protect target. *(Task 1 test.)*
2. **A preset saved as Kobayashi Maru** must load still protecting the same ship (entry ids survive), and `same_setup`/dirty must not report a change after load. *(Task 1 test.)*
3. **The player's own fire** destroying the protected ship is still a loss. Quick Battle turns off friendly-fire game over (`SetupFriendlyFireNoGameOver`). *(Task 6 test.)*
4. **End Combat or XO Restart** while an end timer, a time limit or a countdown is pending must leave nothing to fire into the next battle. *(Task 6 test.)*
5. **XO Restart bypasses the setup screen.** It must re-arm the evaluator from the current plan, including a protected ship in a late warp-in group that is destroyed after it arrives. *(Task 7 test.)*

---

### Task 1: Victory settings model

**Files:**
- Create: `engine/quickbattle/victory.py`
- Modify: `engine/quickbattle/scenario.py` (`Scenario` gets `victory`; `can_start`, `to_json`, `from_json`, `_strip_ids`, `BattlePlan`, `battle_plan`)
- Modify: `engine/quickbattle/spawn.py:131-145` (`sync_sdk` enables XO Start from `plan.startable`)
- Test: `tests/unit/test_qb_victory.py` (new)
- Modify tests: `tests/unit/test_qb_scenario.py` (`test_escort_counts_for_can_start` now expects False: an escort alone is no enemy), `tests/unit/test_qb_presets.py`

**Interfaces:**
- Produces, in `engine/quickbattle/victory.py` (pure, no App; it never imports `scenario` at module level, because `scenario` imports it):
  - Type ids `ELIMINATION = "elimination"`, `KOBAYASHI_MARU = "kobayashi_maru"`.
  - `TYPES: tuple[TypeInfo, ...]` in card order. `TypeInfo(id: str, label: str, description: str)` is a frozen dataclass, with labels "Elimination" and "Kobayashi Maru".
  - `@dataclass class Victory: type: str = ELIMINATION; protect: Optional[str] = None; time_limit_min: int = 0` (`protect` is an `Entry.id`).
  - `protect_candidates(scenario) -> list[tuple[Group, Entry]]`: non-player entries of friendly and neutral groups, in group order then entry order.
  - `unavailable_reason(scenario, type_id) -> Optional[str]`
  - `start_problem(scenario) -> Optional[str]`: `"Add an enemy ship to start"` when no enemy-group entry exists (late groups count); else None.
  - `set_type(scenario, type_id) -> bool`: refuses an unknown or unavailable type. Choosing Kobayashi Maru with no `protect` pre-selects the first candidate.
  - `set_protect(scenario, entry_id) -> bool`: only a current candidate.
  - `set_time_limit(scenario, minutes: int) -> bool`: an int ≥ 0.
  - `reconcile(scenario) -> Optional[str]`: falls back to Elimination and returns the fallback notice when the type is Kobayashi Maru and `protect` is no longer a candidate; else None.
  - `rule_text(scenario) -> str` and `summary_suffix(scenario, title_of) -> str`, where `title_of(entry) -> str` is supplied by the panel.
  - `to_json(v) -> dict` and `from_json(d) -> Victory`: lenient. A missing dict, an unknown type id or a bad field gives the default `Victory()`, with a `_log.warning` for an unknown type (later phases add types and their presets must not break this one).
- Produces, in `scenario.py`:
  - `Scenario.victory: Victory`, defaulting to `Victory()`.
  - `Scenario.can_start()` returns `start_problem(self) is None`.
  - `to_json()` adds the key `"victory"`.
  - `from_json` reads it, then calls `victory.reconcile` on the result.
  - `@dataclass(frozen=True) class VictoryOrder: type: str; protect_entry_id: Optional[str]; time_limit_s: float`
  - `BattlePlan` gains `victory: VictoryOrder` (default Elimination) and `startable: bool = True`, both filled by `battle_plan`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_qb_victory.py`:
  - `test_default_is_elimination`: `default_scenario().victory == Victory()`.
  - `test_can_start_needs_an_enemy`: a default scenario with its enemy group emptied and a friendly escort added gives `can_start() is False` and `start_problem(...) == "Add an enemy ship to start"`. One enemy entry gives True. An enemy group with `warp_in_min=2` also counts.
  - `test_km_unavailable_without_candidate`: player plus enemies only gives `unavailable_reason(s, "kobayashi_maru") == "Add a friendly or neutral ship first"`, and `set_type` returns False.
  - `test_km_preselects_first_candidate`: friendly escort E1, then a neutral group with N1. `set_type(s, "kobayashi_maru")` gives `protect == E1.id`. `set_protect(s, N1.id)` is True; `set_protect` with the player entry id or an enemy entry id is False.
  - `test_km_falls_back_when_protected_ship_goes` (Review Focus 1), parametrised over two edits: remove the protected entry, and move it to the enemy group. (The player entry can never be a candidate, so the "made it the player" case is covered by `set_protect` refusing the player id above.) After either edit, `reconcile(s)` returns `"Kobayashi Maru needs a ship to protect; switched to Elimination"` and `s.victory.type == "elimination"`.
  - `test_json_round_trip_keeps_protect_id` (Review Focus 2): `from_json(s.to_json())` keeps `type`, `protect` and `time_limit_min`, and `same_setup(s, loaded) is True`.
  - `test_same_setup_sees_victory_changes`: changing the type, the protected ship or the time limit makes `same_setup` False. `_strip_ids` must express `protect` as the (group index, entry index) of its entry, because ids are stripped.
  - `test_old_preset_without_victory_loads_as_elimination` and `test_unknown_type_loads_as_elimination`.
  - `test_rule_text`: Kobayashi Maru with time 0 gives exactly the rule line. With 5 minutes it gives the rule line + `" You also lose if time runs out."`.
  - `test_battle_plan_carries_victory`: Kobayashi Maru protecting E1 with 3 minutes gives `plan.victory == VictoryOrder("kobayashi_maru", E1.id, 180.0)`. With no enemy, `plan.startable is False`.
  - In `tests/unit/test_qb_presets.py`, `test_preset_round_trips_victory`: save, then load, and the victory is equal.

- [ ] **Step 2: Run the tests and see them fail**
  Run: `uv run pytest tests/unit/test_qb_victory.py tests/unit/test_qb_presets.py tests/unit/test_qb_scenario.py -q`
  Expected: FAIL, `ModuleNotFoundError: engine.quickbattle.victory`.

- [ ] **Step 3: Implement `victory.py` and the `scenario.py` changes** to the Interfaces above. Update `test_escort_counts_for_can_start` in `test_qb_scenario.py` to the new rule: an escort alone cannot start. In `spawn.sync_sdk`, replace `bool(plan.orders)` with `plan.startable`.

- [ ] **Step 4: Run the tests and see them pass**
  Run: the Step 2 command, plus `uv run pytest tests/unit/test_qb_battle_plan.py tests/host/test_qb_spawn.py -q`
  Expected: PASS.

- [ ] **Step 5: Commit**
  `git add engine/quickbattle/victory.py engine/quickbattle/scenario.py engine/quickbattle/spawn.py tests/unit/test_qb_victory.py tests/unit/test_qb_scenario.py tests/unit/test_qb_presets.py` then `git commit -m "feat(qb): victory settings model, Start needs an enemy"`

---

### Task 2: Panel state for the victory view

**Files:**
- Modify: `engine/ui/quick_battle_setup_panel.py`
- Test: `tests/unit/test_quick_battle_setup_panel.py`

**Interfaces:**
- Consumes: Task 1's `victory` functions and `Scenario.victory`.
- Produces: new verbs and payload keys. Task 3's page relies on these exact names.
  - `victory-view` toggles `self._view` between `"ships"` and `"victory"`. `open()` resets it to `"ships"`.
  - `victory-type:<id>`, `victory-protect:<entry id>` and `victory-time:<n>` (whole minutes, ≥ 0) call the Task 1 setters, then `_after_change()`. They return the setter's result, so a refusal is logged as today.
  - `_after_change()` also runs `victory.reconcile(self._scenario)` and stores any notice in `self._notice`. The notice is shown once and cleared by the next successful verb.
  - Payload `"view"` is `"ships"` or `"victory"`.
  - Payload `"victory"`:
    ```
    {"type": str, "protect": str|None, "time_limit_min": int, "rule": str,
     "types": [{"id","label","description","available": bool,"reason": str|None}],
     "candidates": [{"group": gid, "group_name": str, "allegiance": str,
                     "entries": [{"id", "title"}]}]}
    ```
    Each entry's `title` is the variant name if set, else the catalog title, else the ship id.
  - Payload `"summary"` is the existing text + `victory.summary_suffix(...)`. When `can_start` is False the summary is the `start_problem` text, and a pending `_notice` takes priority over both.
  - Payload `"can_start"` is `scenario.can_start()`, and `_on_start` keeps its existing guard on it.

- [ ] **Step 1: Write the failing tests** in `test_quick_battle_setup_panel.py`, using that file's existing panel fixture and catalog stubs:
  - `test_victory_view_toggles_and_resets_on_open`
  - `test_victory_payload_lists_two_types_with_km_greyed`
  - `test_choose_km_then_protect_and_time`: verbs succeed, the payload reflects them, and the summary ends with ` · Kobayashi Maru · protect <title>`.
  - `test_victory_type_refused_when_unavailable`
  - `test_removing_protected_ship_shows_notice_once`: the next payload's summary is the fallback notice, and the one after an unrelated successful verb is the normal summary.
  - `test_start_blocked_without_enemy_says_why`: `can_start` False, the summary is `"Add an enemy ship to start"`, and `dispatch_event("start")` does not call `on_start`.
  - `test_victory_change_marks_dirty` (against a loaded preset).

- [ ] **Step 2: Run and see them fail**: `uv run pytest tests/unit/test_quick_battle_setup_panel.py -q`. Expected: FAIL (unknown verb `victory-view`).

- [ ] **Step 3: Implement** the verbs, `_view`, `_notice` and payload keys above. Add the verbs to `_HANDLERS`.

- [ ] **Step 4: Run and see them pass**: the same command. Expected: PASS.

- [ ] **Step 5: Commit**: `git add engine/ui/quick_battle_setup_panel.py tests/unit/test_quick_battle_setup_panel.py`, then `git commit -m "feat(qb): victory view state and verbs"`

---

### Task 3: The victory view on the page

**Files:**
- Modify: `native/assets/ui-cef/index.html` (the `#quick-battle-setup` section, lines ~219-243)
- Modify: `native/assets/ui-cef/js/quick_battle_setup.js`
- Modify: `native/assets/ui-cef/css/quick_battle_setup.css`
- Create: `docs/superpowers/specs/2026-10-23-quickbattle-victory-view-mockup.html`, a copy of the approved mockup `.superpowers/brainstorm/52410-1792767062/content/victory-pane-v4.html`, so the reference is committed
- Test: `tests/unit/test_quick_battle_setup_page.py`; `tests/ui/test_qb_victory_view_js.py` (new)

**Interfaces:**
- Consumes: Task 2's payload keys and verbs.
- **Markup to add:**
  - The cog: `<button class="cp-done-button qbs-victory-btn" id="qbs-victory-btn" data-action="victory-view" aria-label="Victory conditions">⚙</button>`, placed immediately before `#qbs-close`.
  - Inside `.cp-content`: `<aside id="qbs-vtypes" class="qbs-groups" hidden></aside>` and `<main id="qbs-vbody" class="cp-body qbs-catalog" hidden></main>`.
- **Behaviour:**
  - When `view === "victory"`: `#qbs-groups` and the catalog `<main>` are hidden, and `#qbs-vtypes` and `#qbs-vbody` are shown. The cog gets `qbs-victory-btn--on`, styled like `cp-toggle--on`, built only from existing `--qbs-*` and `cp-*` tokens.
  - **Type cards** reuse `.qbs-group`. The selected card gets `vc-type--on` (purple border and background as in the mockup). A greyed card shows its `reason` in place of its description, and its click is inert.
  - **Body:**
    - a `.qbs-section` heading with the type label, then the `rule` line;
    - for Kobayashi Maru, a "Ship to protect" section with one `.qbs-group` per candidate group (left border by allegiance), each row a `.qbs-row` with a `cp-toggle` "Protect" (`cp-toggle--on` when chosen);
    - a "Time limit" stepper styled like `qbsDelayStepper`, showing `None` at 0 and `<n> min` otherwise, sending `victory-time:<n±1>`.
  - Clicks route through the existing `data-action` dispatch.
- Follow the mockup's layout. Don't add `<select>`, `title=`, `draggable` or drag-and-drop (the existing page guards forbid them).

- [ ] **Step 1: Write the failing tests:**
  - Source-shape tests in `test_quick_battle_setup_page.py`:
    - `test_victory_cog_sits_left_of_close` (in the footer HTML, `id="qbs-victory-btn"` appears before `id="qbs-close"`);
    - `test_victory_containers_exist`.
  - A node harness test `tests/ui/test_qb_victory_view_js.py`, copying the fake-DOM harness approach of `tests/ui/test_qb_warp_in_stepper_js.py`:
    - `test_victory_view_swaps_panes` (the hidden flags flip both ways);
    - `test_km_greyed_card_shows_reason_and_is_inert`;
    - `test_protect_toggle_sends_verb` (`quick-battle-setup/victory-protect:<id>`);
    - `test_time_stepper_shows_none_then_minutes` (0 renders `None`, the minus button is disabled at 0, and plus sends `victory-time:1`).

- [ ] **Step 2: Run and see them fail**: `uv run pytest tests/unit/test_quick_battle_setup_page.py tests/ui/test_qb_victory_view_js.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement** the markup, `renderVictory()` (called from `setQuickBattleSetup`) and the CSS. Copy the mockup file into `docs/`.

- [ ] **Step 4: Run and see them pass**: the same command, plus `uv run pytest tests/ui/test_qb_warp_in_stepper_js.py -q`. Expected: PASS.

- [ ] **Step 5: Commit**: the three asset files, the mockup copy and both tests by explicit path, with `git commit -m "feat(qb): victory view on the setup screen"`

---

### Task 4: Subtitle-only crew lines

**Files:**
- Modify: `tools/dialogue/dauntless_crew.json`, adding `SaffiQBProtectedLost1` and `SaffiQBTimeUp1` with the Global Constraints text and **no `sound` key**
- Modify: `tools/gen_dauntless_tgl.py`, only if needed so a line without a sound writes an empty sound
- Regenerate: `native/assets/replacements/data/TGL/Dauntless Crew.tgl` via `uv run python tools/gen_dauntless_tgl.py --write` (never hand-edit)
- Modify: `tests/tools/test_dauntless_dialogue_drift.py`
- Modify: `docs/engine/dauntless-crew-dialogue.md`, one line: a line may omit `sound`, and it is then subtitle-only
- Test: `tests/unit/test_crew_speech_text_only.py` (new)

**Interfaces:**
- Produces: TGL keys `SaffiQBProtectedLost1` and `SaffiQBTimeUp1` in `data/TGL/Dauntless Crew.tgl`, which Task 6 speaks through the XO.

- [ ] **Step 1: Write the failing tests:**
  - In the drift test, `test_subtitle_only_lines_are_allowed`: these two keys have `sound == ""`, are in the generated TGL with their exact text, and are skipped by the shipped-file check.
  - In `test_crew_speech_text_only.py`, `test_text_only_line_shows_subtitle_and_has_duration`: `crew_speech.emit("XO", <Dauntless Crew db>, "SaffiQBProtectedLost1", 0)` returns a duration > 0, and the subtitle bus received the exact text. Use the bus test seam already used by `crew_speech` tests; find it with `grep -rn "crew_speech" tests/unit | head`.

- [ ] **Step 2: Run and see them fail**: `uv run pytest tests/tools/test_dauntless_dialogue_drift.py tests/unit/test_crew_speech_text_only.py -q`

- [ ] **Step 3: Implement**: the JSON lines, the drift test's empty-sound skip, any generator change, regeneration, and the doc line.

- [ ] **Step 4: Run and see them pass**: the same command. Expected: PASS.

- [ ] **Step 5: Commit**: the explicit paths above, then `git commit -m "feat(dialogue): subtitle-only crew lines for Quick Battle endings"`

---

### Task 5: Target list markers

**Files:**
- Create: `engine/ui/target_markers.py`
- Modify: `engine/ui/target_list_view.py` (the row tuple and payload gain `marker`; lines ~350-409)
- Modify: `native/assets/ui-cef/js/target_list.js` (~line 88: a marker span before the name)
- Modify: `native/assets/ui-cef/css/target_list.css`
- Modify: the reset sites, so markers never leak across missions or tests:
  - `engine/host_loop.py:7697`;
  - `engine/host_loop.py:13455`;
  - `tests/conftest.py:1063`.
- Test: `tests/unit/test_target_markers.py` (new); `tests/unit/test_target_list_view.py`

**Interfaces:**
- Produces, in `engine/ui/target_markers.py` (keyed by ship object name, i.e. `GetName()`):
  - `set_marker(ship_name: str, kind: str)` where `kind` is in `{"protect"}`; later phases add `"flag"`;
  - `clear_marker(ship_name: str)`;
  - `marker_for(ship_name: str) -> Optional[str]`;
  - `clear() -> None`.
- Target list payload rows gain `"marker": str|None`. The JS renders `<span class="target-list__marker target-list__marker--protect">` holding a small inline SVG shield, sized to the row's text, in the row's text colour. No colour states (Mark).

- [ ] **Step 1: Write the failing tests:**
  - `test_markers_set_clear_and_reset`;
  - in `test_target_list_view.py`, `test_row_carries_marker`. Set a marker for a listed ship: its payload row has `"marker": "protect"` and others have None. Changing the marker alone must change the snapshot, so it re-renders.
  - a source-shape assertion that `target_list.js` emits `target-list__marker--` plus the row's marker.

- [ ] **Step 2: Run and see them fail**: `uv run pytest tests/unit/test_target_markers.py tests/unit/test_target_list_view.py -q`

- [ ] **Step 3: Implement**: the module, the row field, the JS span, the CSS and the three reset calls.

- [ ] **Step 4: Run and see them pass**: the same command. Expected: PASS.

- [ ] **Step 5: Commit**: the explicit paths, then `git commit -m "feat(ui): target list markers (protect)"`

---

### Task 6: Battle end runtime (Elimination and Kobayashi Maru)

**Files:**
- Create: `engine/quickbattle/battle_end.py`
- Modify: `engine/quickbattle/spawn.py`:
  - in `install_generate_ships_hook`'s wrapper, call `battle_end.begin(qb, plan)` after either branch, in a try/except that logs;
  - in `install_end_simulation_hook`'s wrapper, call `battle_end.reset()` before `orig`.
- Modify: `engine/quickbattle/late_arrivals.py:128-136` (`check_win` delegates to `battle_end.check_win(qb)`)
- Modify: `engine/host_loop.py:7904` (call `battle_end.install(_QB)` beside the other installs) and the three reset sites from Task 5 (`battle_end.reset()`)
- Test: `tests/host/test_qb_battle_end.py` (new), modelled on `tests/host/test_qb_late_arrivals.py`

**Interfaces:**
- Consumes:
  - `BattlePlan.victory` and `.orders` (Task 1);
  - `engine.quickbattle.naming.object_name(title, n)`. Object names are `object_name(order.title, n)`, with `n` the 1-based index in `plan.orders`, for now and late ships alike (`spawn.py:361-367`);
  - `target_markers` (Task 5);
  - the TGL keys (Task 4);
  - `engine/appc/mission_goals.py` (`objectives_submenu`, `add_goal_button`).
- Produces, in `engine/quickbattle/battle_end.py`:
  - Reasons: `REASON_ELIMINATION = "elimination"`, `REASON_PLAYER = "player"`, `REASON_PROTECTED = "protected"`, `REASON_TIME = "time"`.
  - `END_DELAY_S = 1.0`
  - `install(qb) -> bool` wraps `qb.ShipDestroyed`, `qb.GenerateLoseSequence` and `qb.GenerateWinSequence`. It is idempotent.
  - `begin(qb, plan_or_None) -> None` arms one battle. With `None`, the type is Elimination.
  - `end_battle(qb, won: bool, reason: str) -> bool` returns False if the battle has already ended. Otherwise it sets `qb.bWonOrLost = 1` and posts `ET_END_SIMULATION` (int 2 if won, else 1) to `qb.g_pXO` after `END_DELAY_S`, the way `QuickBattle.py:3300-3316` does, storing the timer id in `qb.g_idTimer`.
  - `check_win(qb) -> None` ends with a win when the battle is armed and not ended, `qb.bInSimulation`, `qb.bWonOrLost == 0` and `qb.g_iNumEnemies == 0`.
  - `state() -> Optional[BattleState]`, where `BattleState` has `type`, `protected_name: Optional[str]`, `ended: bool`, `won: Optional[bool]` and `reason: Optional[str]`.
  - `reset() -> None` cancels every timer this module made, kills and hides the Objectives entries, clears its markers and forgets the state.
- **`ShipDestroyed` wrapper order** (decides all precedence; don't reorder):
  1. Get the ship from `ShipClass_Cast(pEvent.GetDestination())`.
  2. If it is the player and `qb.bInSimulation`:
     - delete this module's pending end timer, if any (player death beats everything, spec §4.1);
     - mark the state ended with reason `player` and `won = False`.
  3. Else, if it is the protected ship and the battle is armed and not ended: `end_battle(qb, False, REASON_PROTECTED)`.
  4. Save `qb.bWonOrLost`, set it to 1, call `orig`, then restore the saved value unless the battle has ended. This suppresses BC's own win branch (`QuickBattle.py:3356`) while keeping its count and destroyed-callout bookkeeping.
  5. `check_win(qb)`.
- **`GenerateLoseSequence` wrapper:**
  - For reason `protected` or `time`, build BC's lose sequence (`GenerateLoseSequence`, `QuickBattle.py:3380-3420`), with the XO line replaced by `SaffiQBProtectedLost1` / `SaffiQBTimeUp1` from `data/TGL/Dauntless Crew.tgl`.
  - Otherwise call `orig`.
- **`GenerateWinSequence` wrapper:** call `orig(pSequence)`. Then, when this module ended the battle as a win, run BC's own win tail: `BridgeHandlers.DropMenusTurnBack()` and `qb.g_pXO.MenuUp()` (`QuickBattle.py:3365-3368`).
- **`begin`:**
  - Resolve the protected ship's object name from the plan (`None` for Elimination), and `target_markers.set_marker(name, "protect")`.
  - Make the Objectives submenu visible (Quick Battle hides it, `QuickBattle.py:735-739`), empty it, then add `Destroy all enemy ships`, plus `Protect <display name>` (the order's `display_name`, else the object name) for Kobayashi Maru, plus `Win within <n> min` when `time_limit_s > 0`.
  - With a time limit:
    - a game-time timer ends the battle as `REASON_TIME`;
    - at each whole minute remaining from `min(limit_min, 10)` down to 1, the **Science** officer (`App.CharacterClass_GetObject(<bridge set>, "Science")`) says `E8M2Countdown<N>` from `data/TGL/Maelstrom/Episode 8/E8M2.TGL` with `SayLine(db, key, "Captain", 1)`. This is Miguel, as in `E8M2.py:2984-3020`.
  - Timer event types are allocated lazily and forgotten by `reset()`, as `late_arrivals._event_type` does.

- [ ] **Step 1: Write the failing tests** in `tests/host/test_qb_battle_end.py`, using the `world` fixture and helpers style of `tests/integration/test_quickbattle_setup_e2e.py` (panel → start → `_destroy`):
  - `test_elimination_win_ends_the_battle`: killing the last enemy gives `state().won is True`, `qb.bWonOrLost == 1`, and `qb.g_idTimer` set. Ticking `App.g_kTimerManager` 1.1 s gives `qb.bInSimulation == 0`. Felix's `QBFelixWin` was said, and the XO menu is up.
  - `test_km_protected_destroyed_is_a_loss`: the reason is `protected`. After the tick, the XO subtitle is the exact protected-loss text.
  - `test_km_protected_neutral_destroyed_is_a_loss`: a neutral protected ship has no `g_kShips` row and must still lose.
  - `test_km_protected_killed_by_player_fire_is_a_loss` (Review Focus 3): drive the destruction through the damage path with the player as the attacker. Find the helper with `grep -rn "apply_hit" tests/host | head`.
  - `test_km_win_needs_protected_alive`
  - `test_player_death_beats_protected_same_tick`: protected destroyed, then the player, before the tick. Only BC's player-loss timer remains and the reason is `player`.
  - `test_time_limit_loses_and_counts_down`: 2 minutes. Each tick to the 1-minute mark hears `E8M2Countdown1` from Science. At 120 s the battle ends with the reason `time` and the time-up subtitle.
  - `test_end_combat_cancels_everything` (Review Focus 4):
    - set a time limit, then call `QB.EndSimulation()`;
    - ticking past the limit changes nothing, and `state()` is None;
    - the Objectives submenu is empty and hidden, and `target_markers.marker_for(protected) is None`.
  - `test_objectives_listed_for_km`
  - `test_late_arrivals_win_routes_through_battle_end`: `late_arrivals.check_win` now ends the battle (the timer is posted).

- [ ] **Step 2: Run and see them fail**: `uv run pytest tests/host/test_qb_battle_end.py -q`. Expected: FAIL (no module).

- [ ] **Step 3: Implement `battle_end.py`** and the wiring above.

- [ ] **Step 4: Run and see them pass**: the same command, plus the existing tests it touches: `uv run pytest tests/host/test_qb_late_arrivals.py tests/host/test_qb_spawn.py tests/integration/test_quickbattle_setup_e2e.py tests/integration/test_quickbattle_friendly_fire_warning.py -q`. Expected: PASS. The existing E2E assertions (`bWonOrLost == 1` after a win, `g_idTimer` set after player death) must still hold.

- [ ] **Step 5: Commit**: the explicit paths, then `git commit -m "feat(qb): battle end evaluator — win ends the battle, Kobayashi Maru"`

---

### Task 7: End-to-end, XO Restart, and docs

**Files:**
- Modify: `tests/integration/test_quickbattle_setup_e2e.py`
- Modify: `docs/superpowers/specs/2026-10-23-quickbattle-victory-conditions-design.md` (status line: "approved; phase 1 built, not live-verified")
- Modify: `docs/superpowers/specs/2026-10-01-quickbattle-redesign-roadmap.md` (row 2c status: "phase 1 built; named types replace the condition builder, see 2026-10-23 spec")
- Modify: `CLAUDE.md` ("Quick Battle setup + group spawning" row: one clause naming `victory.py` and `battle_end.py`, and that a win now ends the battle)

**Interfaces:** consumes everything above. Produces nothing new.

- [ ] **Step 1: Write the failing E2E tests**, driven from the panel as the existing ones are:
  - `test_km_e2e_from_the_victory_view`:
    1. Add a neutral Transport group and a Warbird.
    2. Send `victory-view`, `victory-type:kobayashi_maru` and `victory-protect:<transport entry>`.
    3. Start. The Transport has the `protect` marker.
    4. Destroy the Transport: it is a loss with the reason `protected`.
  - `test_xo_restart_rearms_from_current_plan` (Review Focus 5):
    1. Set up Kobayashi Maru with the protected ship in a late group (warp-in 1).
    2. Start, then XO-Restart as BC's button does: `QB.RestartSimulation(stub, None)`, where `stub` is a minimal object whose `CallNextHandler` is a no-op (the SDK calls `pObject.CallNextHandler`, `QuickBattle.py:3163`). Then complete the new start the way `_go` does: tick 3 s and call `hl._fire_pending_preload_done()`.
    3. Tick past the arrival.
    4. Destroy the arrived protected ship: it is a loss.
  - `test_preset_km_round_trip_e2e`: save a Kobayashi Maru preset, load it in a fresh panel, start, and the protected ship is marked.

- [ ] **Step 2: Run and see them fail**, then fix whatever they expose in the owning module: `uv run pytest tests/integration/test_quickbattle_setup_e2e.py -q`

- [ ] **Step 3: Make the doc edits** listed above.

- [ ] **Step 4: Run every focused file from this plan once**, as an explicit list (never a directory):
  ```
  uv run pytest tests/unit/test_qb_victory.py tests/unit/test_qb_scenario.py tests/unit/test_qb_presets.py tests/unit/test_qb_battle_plan.py tests/unit/test_quick_battle_setup_panel.py tests/unit/test_quick_battle_setup_page.py tests/ui/test_qb_victory_view_js.py tests/ui/test_qb_warp_in_stepper_js.py tests/tools/test_dauntless_dialogue_drift.py tests/unit/test_crew_speech_text_only.py tests/unit/test_target_markers.py tests/unit/test_target_list_view.py tests/host/test_qb_battle_end.py tests/host/test_qb_late_arrivals.py tests/host/test_qb_spawn.py tests/integration/test_quickbattle_setup_e2e.py tests/integration/test_quickbattle_friendly_fire_warning.py -q
  ```
  Expected: PASS.

- [ ] **Step 5: Commit**: the test file and the three docs by explicit path, then `git commit -m "test(qb): victory phase 1 end-to-end; docs"`

**Live check owed (Mark), not part of this plan's done:**
- the cog and the victory view look;
- the shield marker;
- the subtitle-only loss lines;
- the win now ending the battle with Felix, the fanfare and the menu;
- the countdown voice.
