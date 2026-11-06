# Test-suite memory

## TL;DR (2026-11-06)

The full pytest suite in one process peaked at **4.3 GB** on `ecbeec5a0`
(17,327 tests), and the gate's 4 GB watchdog SIGKILLed it. The cause was a
true leak: **every ship any test built stayed alive to the end of the run**.
Module registries that the game clears only on a mission swap held strong
references, and the per-test reset's hand-kept copy of the swap's reset list
had drifted 15 entries behind it. Fixed by giving both callers one list,
`engine.host_loop.reset_mission_state`. After the fix the full suite peaks at
**2,903 MB** (2,896 MB in the final run). What remains is the working sets
of a few heavy deep tests, each adding to a high-water mark the process
never hands back. The full gate now fails past a **3,300 MB** budget and
names the tests that raised the high-water most.

## How it was measured (2026-11-06)

One instrumented whole-suite run, with a scratch pytest plugin recording per
test:

- current RSS (mach `task_info`, not the `ru_maxrss` high-water mark, so
  drops show);
- `malloc_zone_statistics` in-use bytes: native allocations plus Python
  objects over 512 B;
- `sys.getallocatedblocks()`: live pymalloc small objects. pymalloc arenas
  are mmap'd, so they count in RSS but not in malloc;
- at each file boundary, `len(gc.get_objects())` and a type histogram.

Then a referrer walk from surviving `ShipClass` instances back to a module
global (BFS over `gc.get_referrers`, blocking each root found and searching
again until none is left), on single files, and A/B runs of the heaviest
40 files with the old and new conftest.

### What it showed

| Signal (full suite, before) | Value |
|---|---|
| Peak RSS | 4,308 MB |
| RSS by file 400 of 1,707 | 4,126 MB, then flat to the end |
| malloc in use at the end | 624 MB |
| Live pymalloc blocks at the end | 15.4 M |
| Live gc objects at the end | 5.3 M (406 k after the first file) |
| Survivors by type | 2.1 M lists, 712 k `TGPoint3`, 212 k **live `weakref.finalize`**, 16 k `PhaserBank`, 12 k `ConditionalAI` |

So the growth was Python-side (blocks and objects, not malloc), it happened
in the host and integration files that build ships, and the survivors were
engine objects. A live `weakref.finalize` means its object has not been
collected: about 200 k engine objects were being kept alive.

### The roots

The referrer walk after `tests/integration/test_native_k0_differential.py`
(90 ships alive after `gc.collect()`) found three:

1. `engine.appc.ship_lifecycle._live`: a set holding every ship
   `SetClass.AddObjectToSet` published. The game clears it only on a mission
   swap (`HostController._drain_pending_swap`).
2. `engine.appc.registry_texture._pending`: `{id(ship): {"ship": ship, ...}}`,
   swap-only as well.
3. SDK `MissionLib.g_dConditionEventTriggers`: per-mission condition
   triggers, emptied by the SDK's `MissionDeleted` when the mission object is
   deleted. A test's mission never is.

The swap teardown resets about 30 registries. The per-test reset in
`tests/conftest.py` had its own hand-kept list, which lacked 15 of them
(`ship_lifecycle`, `registry_texture`, `ship_death`, `visible_damage`,
`object_lifetime`, `subsystem_cascade`, `damage_eligibility`, ...).

### The fix

- The swap's renderer-independent resets became
  `engine.host_loop.reset_mission_state(renderer)`. The swap calls it with
  its renderer, and the per-test reset calls it with `None`. A new
  mission-scoped registry goes there, and both callers get it.
- The conftest clears `MissionLib.g_dConditionEventTriggers` (a test-only
  gap).
- Guard: `tests/unit/test_conftest_frees_previous_tests_ships.py`. One test
  publishes a ship; the next asserts the registries are empty and the ship
  was collected. It fails on the old conftest.

After it, 9 ships survive the k0 file instead of 90: the last test's own,
held by the current set manager, which the conftest leaves alone on purpose.

A side effect, also fixed: now that ships die, their `weakref.finalize`
callbacks queue native-mirror frees at whatever moment the cyclic GC
chooses, sometimes inside a later test.
`test_native_k3_dispatch::test_switch_off_unchanged_calls` assumed that queue
was empty (true only while nothing died). It now drains first and holds the
GC off for its window.

## What remains, and why it is legitimate

| Source | Size | Kind |
|---|---|---|
| `tests/integration/test_native_off_lock_stress.py` | **1.6 GB peak on its own** (RSS 385 to 1,578 MB in one test) | Working set. The churn thread turns the cyclic collector off process-wide and collects only generations 0/1, so 600 ticks of a 64-ship fight's cyclic garbage pile up until the arm ends. In the suite it does not raise the high-water (see below). |
| GL init/shutdown cycles | about 1 MB RSS per cycle (12 cycles: 124 to 136 MB) | Small, bounded, mostly the driver; not chased. |
| Host tests loading real assets (`test_rock_near_host`, `test_frame_rate_independence`) | +240 to +380 MB RSS steps with malloc flat | GL driver / asset memory, freed at shutdown but kept by the process. |

Because RSS keeps its high-water mark, the suite's peak is the sum of the
largest rises, wherever those tests run in the order. Collecting at every file boundary was tried and did not move the peak
(2,873 MB vs 2,638 MB on the heavy-40 subset), because the peak forms inside
one test.

### Before and after

| Run | Before | After |
|---|---|---|
| Heaviest 40 files, one process | 3,099 MB | 2,638 MB |
| `test_native_k0_differential.py`: ships alive after `gc.collect()` | 90 | 9 |
| Full suite, one process | 4,308 MB (and SIGKILLed at 4,000 in the gate) | 2,903 MB (17,301 passed, 19:01) |
| Merge tier, one process | (did not exist) | 579 MB |

## The guard

`scripts/gate_full.sh` runs pytest under `tools/pytest_rss_watchdog.py`
(4,000 MB SIGKILL ceiling: the host's safety net, unchanged) and **fails the
gate when the reported peak exceeds `PYTEST_RSS_BUDGET_MB`** (default in
`tools/check_test_baseline.py`). The peak is printed every run, so creep
shows long before the ceiling.

Budget: **3,300 MB**, about 14% over the measured peaks (2,903 and 2,896 MB
in two full-gate runs) and 700 MB under the 4,000 MB ceiling.

Where the peak comes from: the full gate's own report of the tests that
raised the RSS high-water most (final run, 2026-11-06; measured, per-test
`ru_maxrss` rise):

| Test | High-water rise |
|---|---|
| `tests/integration/test_golden_fights.py::test_k1_gameloop_ai` | +658 MB |
| `tests/host/test_frame_rate_independence.py::test_every_consumer_gets_the_game_time_the_loop_advanced[15]` | +439 MB |
| `tests/host/test_far_bindings.py::test_near_density_dials_reach_the_near_band` | +271 MB |
| `tests/host/test_sun_integration.py::test_run_M1Basic_verbose_logs_sun_count` | +250 MB |
| `tests/host/test_native_combat_scene_audit.py::test_combat_stress_runs_clean_under_the_native_audit` | +214 MB |

So the peak is set by a few heavy deep tests' working sets (a fight
recorded per tick, real-asset GL host tests), each adding to a high-water
that pymalloc and the GL driver never hand back. The merge tier runs none of
them and peaks at 579-686 MB. `test_native_off_lock_stress.py` (1.6 GB on
its own) does not raise the in-suite high-water at all: by the time it runs,
the floor is already above its need. Lowering the full-suite peak means
slimming those tests' working sets, starting with `test_k1_gameloop_ai`; I
did not, because each is a reference for a native kernel.

## History: the original >100 GB OOM (2026-06)

The first OOM report came when the suite had ~1,700 tests and per-test SDK
teardown was incomplete; it was fixed by `reset_sdk_globals` and the
per-module cleanup fixtures (and `59d5f98`, the ShipDisplay registry).
**Unscoped collection** made it worse: the repo had no pytest config, so a
stray non-dot worktree at the root would have been collected too.
`pyproject.toml` now pins `testpaths = ["tests"]` and `norecursedirs`. By
2026-06-15 the 3,188-test suite peaked at about 290 MB. Between June and
November the suite grew to 17,000 tests, and the conftest's copy of the swap
resets fell behind as swap-time registries were added. That drift is what
the shared `reset_mission_state` now prevents.

## Running the suite safely

```bash
scripts/gate_full.sh              # the full gate: budgeted, in one process
scripts/run_tests.sh              # pytest only, one process, 4 GB watchdog
CEILING_MB=8000 scripts/run_tests.sh
```

`scripts/run_tests.sh --batched` (one process per `tests/` subdirectory)
still exists for triage, but it **hides build-up**: never use it to call the
memory fine.
