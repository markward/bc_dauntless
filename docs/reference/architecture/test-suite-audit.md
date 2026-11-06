# Test-suite audit (2026-11-06)

Branch `fix/test-suite-and-gate`, off local `main` at `ecbeec5a0`. Companion
docs: [test-suite-memory.md](test-suite-memory.md) (the memory fix) and the
two-tier gate spec,
[2026-11-06-two-tier-test-gate-design.md](../../superpowers/specs/2026-11-06-two-tier-test-gate-design.md).

## Method

Every decision rests on one instrumented whole-suite run (per-test duration,
RSS, malloc and pymalloc blocks; ctest JUnit timings; each gtest binary
timed in-process), kept in the session scratchpad. On top of that:

- **Exact duplicates:** every test function's AST hashed with its docstring
  stripped (decorators and argument names included). A pair in the same file
  shares helpers and fixtures by construction. A cross-file pair was kept
  unless its helpers resolve to the same definitions.
- **Assertion-free tests:** an AST scan for test functions with no `assert`,
  `raise` or asserting call, directly or through a local helper. Of the 188
  hits, almost all are deliberate "does not raise" smoke tests, and those
  stay. The two below were designed to assert nothing.
- **Leftover diagnostics:** names with `diag`, `probe`, `spike`, `bench` were
  read one by one. Most "probe" names are the in-game sensor probe.
- **Source-text pins:** files using `inspect.getsource` / `__doc__`.
- **Coverage contexts** (`--cov-context=test`) were **not** run over the
  whole suite. That costs about three full runs of machine time on a shared
  perf machine, and the AST hash already finds the exact copies. They remain
  the tool for a deeper pass on one area.

## Before and after

| | Before (`ecbeec5a0`) | After (this branch) |
|---|---|---|
| pytest tests | 17,327 | 17,331 (15 removed; new guards and tier-gate cases added, listed below) |
| Removed tests | | 15 tests (9.4 s of measured time) |
| Rewritten tests | | 2 source-text pins become behavioural; `UpdateNeverBlocks` becomes 2 cases |
| Per-test overhead | 3.55 ms | 1.90 ms (self-check cache, about 28 s per full run) |
| Full pytest wall time | 26 min measured (about 20 min without the probe) | 18:51 (17,302 passed, final full gate) |
| Gate a merge waits for | about 36 min (and it died at 4 GB) | the merge gate: 189 s (final run) |

Removing tests is the small part. The time goes to the tiers and the
per-test overhead fix: the suite is well kept, and its slow tests are slow
because they test something deep.

## Removals (one commit per kind)

### 1. Assertion-free diagnostics (`e9fa0f44e`)

| Test | Why | What still covers it |
|---|---|---|
| `tests/integration/test_close_range_combat_diagnostic.py::test_close_range_combat_log` | Its own docstring: "no assertions, a sighting scope, not a gate". Prints fire traces from the May 2026 AI-doesn't-fire hunt. | `test_ai_driver_got_focus.py` (the GotFocus dispatch it uncovered), `test_close_range_combat_motion.py` |
| `tests/integration/test_galaxy_combat_fire_diagnostic.py::test_galaxy_vs_galaxy_fire_trace` | "The test asserts nothing". Prints a per-second phaser snapshot. | `test_m2objects_live_path.py` ("phasers must fire within 15 s"), `test_golden_fights.py` |

### 2. Leftover spike (`c2f2be962`)

| Test | Why | What still covers it |
|---|---|---|
| `tests/host/test_gesture_retarget_spike.py` | A 2026-06-19 go/no-go spike ("Verdict: RETARGET-OK"). It asserts that two stock BC NIFs name the same Bip01 bones, a fact about unchanging BC content, not engine code. | `tests/host/test_load_instance_clip.py`, `tests/unit/test_bridge_character_anim*.py` |

### 3. Exact copies of another test (`3fbea0c8b`)

Each runs the same statements through the same helpers as the twin kept.

| Removed | Kept twin |
|---|---|
| `test_host_loop_unit::test_run_M1_Basic_player_unmoved_without_input` (it never measured the drift its docstring promised; a 4.4 s boot) | `test_run_M1_Basic_for_a_few_ticks` |
| `test_sun_integration::test_aggregate_suns_called_does_not_raise` | `test_host_loop_suns::test_aggregate_suns_returns_list` |
| `test_ai_driver_subsystem_target_sync::test_sync_still_picks_subsystem_when_target_is_not_cloaked` | `test_sync_pushes_chosen_subsystem_onto_ship` |
| `test_engineering_power_panel::test_is_showing_true_with_powered_player` | `test_is_showing_true_when_engineering_menu_open` |
| `test_phaser_fire_range_gate::test_target_well_within_global_range_returns_true` | `test_gate_ignores_per_bank_max_damage_distance` |
| `test_sensor_probes::test_observer_side_rock_still_cancels_memory_without_a_probe` | `test_sensor_reach::test_memory_respects_occlusion` (same imported helpers) |
| `test_ship_death_hulks::test_locks_release_the_moment_the_throes_end` | `test_ship_death::test_locks_clear_when_the_throes_end` |
| `test_subsystem_threshold_events::test_destroyed_fires_and_beats_disabled` | `test_plain_subsystem_still_destroys_on_zero_condition_regression` |
| `test_system_map_validate::test_ordered_profile_is_clean` | `test_radiation_near_the_star_is_fine` |
| `test_torpedo_tube_fire::test_fire_no_sfx_in_pr2a` | `test_fire_with_none_target_succeeds` |

Not duplicates, despite identical bodies: `test_fire_key_input_chain` vs
`test_fkey_input_chain` (different `STOCK_MAP`), the two
`*_binding_manifest::test_validate_not_invoked_at_module_scope` (different
`_SRC`), and the K2/K3 `*_override_guard::test_every_allowance_is_still_needed`
(different allowance tables).

### 4. Subsumed by a stronger test on the same path (`fff1c4719`)

| Removed | Why it adds nothing |
|---|---|
| `test_sun_integration::test_run_M1Basic_with_sun_wiring_does_not_crash` (4.8 s) | `run(M1Basic, max_ticks=2) == 0`. The same boot is asserted `== 0` by `test_host_loop_unit::test_run_M1_Basic_for_a_few_ticks` (5 ticks), and the same file's `test_run_M1Basic_verbose_logs_sun_count` runs it and checks the sun aggregation ran. |
| `tests/integration/test_turn_to_orientation_smoke.py` | One `Update()` of the TurnToOrientation PlainAI returning a valid status. `test_ai_turn_to_orientation_smoke.py` drives the same PlainAI script through `GameLoop` and asserts the rotation, both turn directions and the lineup completion. |

### Rewritten, not removed

- `test_far_host_wiring::test_a_mission_swap_resets_the_scenery_contacts` and
  `test_ship_death::test_mission_teardown_calls_ship_death_reset` asserted,
  via `inspect.getsource`, that a reset call's **text** sat inside
  `HostController` (one within 200 characters of another). A pure refactor
  broke both. They now spy on the resets over a real dev-picker swap and
  fail when either reset is removed (mutation-checked). Commit `feef40285`.
- `BridgePanels.UpdateNeverBlocks` became `UpdateNeverWaitsForAParkedRaster`
  (deterministic) and `UpdateThatUploadsStaysCheap` (CPU-time bound). Commit
  `143c71051`; see the spec.

### Added

- `tests/unit/test_conftest_frees_previous_tests_ships.py`: the memory fix's
  guard.
- `tests/unit/test_gate_tiers.py`: the tier rot guard.
- New cases in `tests/tools/test_check_test_baseline.py` for the tier gate.
- `test_native_combat_mirror::test_self_check_runs_once_per_set_of_compared_objects`.

## Judgement calls, NOT removed (for Mark)

1. **`test_host_loop_run_uninstalls_hooks.py`: five host-loop boots, 24 s.**
   Each boots M1 Basic and checks that one kind of hook is gone afterwards.
   One shared boot would not work as written, because the per-test reset
   itself uninstalls those hooks before the next test, so the later
   assertions would pass vacuously. Merging them into one test that checks
   all five after a single boot would save about 19 s and lose only the
   per-hook test names. Now in the deep tier.
2. **Three verbose M1 Basic boots, 13 s:** `test_sun_integration`,
   `test_host_loop_planets` and `test_host_loop_lighting` each boot M1 Basic
   with `OPEN_STBC_HOST_VERBOSE=1` to check one log line. One boot could
   check all three lines.
3. **Heavy working sets set the full-suite RSS peak.** The final full gate
   names `test_golden_fights::test_k1_gameloop_ai` (+658 MB high-water) and
   four real-asset host tests (+214 to +439 MB). Slimming them, e.g. comparing
   per tick instead of recording every tick, would lower the 3,300 MB
   budget. Separately, **`test_native_off_lock_stress.py` peaks at 1.6 GB on
   its own** (it does not raise the in-suite high-water). The
   churn thread turns the cyclic collector off process-wide and runs only
   generation-0/1 collections, so the stressed arm's 600 ticks of cyclic
   garbage pile up until the arm ends. A generation-2 collection on the churn thread
   every N ticks would cut it, but it changes what the stress test stresses,
   so it is your call.
4. **`inspect.getsource` wiring tests (about 24 files)**, e.g.
   `test_scene_reconcile_ordering`, `test_render_space_feeds`,
   `test_warp_state_host_wiring`, `test_qb_prewarm_wiring`,
   `test_paths_resolve` ("configure paths BEFORE `_setup_sdk()`"). They pin
   the order of calls in `host_loop.run()` by source text, so they break on
   refactors. But several are the only guard for an ordering bug, and an
   ordering guard by behaviour needs a harness `host_loop.run()` does not
   have. Kept; rewrite them one by one when each breaks.
5. **`test_alert_keys::test_plain_digit_still_bumps_throttle`** has the same
   body as `test_player_control::test_digit_5_sets_forward_5`, but over a
   different `_FakeShip`/key reader, so its fakes may model the shift key the
   alert keys need. Kept; near-zero cost.
6. **`test_shuttle_service::test_no_two_shuttles_ever_share_a_pose`, 34 s.**
   A 2,400 s sim horizon, chosen so the one-a-minute stagger has drifted.
   A shorter horizon might still reach the shared-dock case. Deep tier.
7. **Names that over-claim:** `test_engagement_distance_diag.py` asserts a
   pursuit bound (keep, maybe rename), and `test_particles_death_probe.py`
   says "the skips ARE the deliverable", but every wall is now cleared and
   it asserts (keep, refresh the docstring).
8. **Tests that never run on this machine:**
   `tests/tools/test_app_icon_drift.py` is a **drift test** that skips
   because `svglib` is not in the dev extras, so the icon can drift
   unnoticed. Add `svglib` to `[project.optional-dependencies] dev`?
   The three `test_backdrops_integration` cases skip on macOS by design
   (hidden GLFW windows do not present). (Resolved: the LC Intrepid
   running-lights test skipped in every suite run, because it looked under
   `<data dir>/mods` and the suite always runs under a temp data dir. At
   Mark's suggestion it now loads the stock Galaxy, which has running lights:
   17 lights, mutation-checked; commit `994c24ea5`.)
9. **Wide sweeps kept:** `test_no_install_writes` (26 campaign missions,
   8.7 s; a protected guard) and `test_warp_button_handler_sweep`
   (26 missions, 8.5 s). Every mission is a real case.
