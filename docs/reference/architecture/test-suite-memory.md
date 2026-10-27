# Test-suite memory: the full-suite OOM (cleanup #10)

## TL;DR

Running `uv run pytest` over the whole suite was reported to consume **>100 GB
RAM and freeze macOS**. As of 2026-06-15, on current `main`, **it does not** —
the full 3188-test suite peaks at **~290 MB** (in-process `ru_maxrss`
high-water mark) and finishes in ~20–35 s in a single process. The leak that
caused the OOM was fixed by the maturation of per-test isolation
(`engine/host_loop.py:reset_sdk_globals` + the per-module cleanup fixtures, and
the ShipDisplay-registry isolation fix in `59d5f98`). This document records the
evidence and the regression guard that was added so it cannot silently return.

## How it was investigated (systematic-debugging)

Everything ran in small, watchdog-capped batches — never an unbounded full run.

- **Watchdog** (`tools/pytest_rss_watchdog.py`): polls the child process
  tree's RSS via `ps` every 0.5 s and SIGKILLs the process group if it crosses
  a ceiling (8 GB during investigation). macOS does not reliably enforce
  RLIMIT_AS, so this is the safety net.
- **Per-test RSS instrumentation**: a scratch pytest plugin recorded, after
  each test, `resource.getrusage(RUSAGE_SELF).ru_maxrss` (bytes on macOS,
  monotonic high-water mark) plus the lengths of the App.py singleton
  containers (`g_kEventManager._broadcast_handlers`, `g_kTimerManager._timers`,
  `g_kSetManager._sets`, …) and the projectile/VFX accumulators.

### Measured peak RSS (in-process high-water mark)

| Scope | Files | Peak RSS | Shape |
|---|---|---|---|
| tests/cameras | 6 | 65 MB | flat |
| tests/audio | 7 | 65 MB | flat |
| tests/missions | 5 | 65 MB | flat |
| tests/ui | 3 | 68 MB | flat |
| tests/host | 35 | 246 MB | a few one-time native-init spikes (renderer/framebuffer), then flat |
| tests/integration | 98 | 293 MB | one heavy 120-tick host-loop test; flat otherwise |
| tests/unit (each 40-file batch) | 291 | ~100 MB | flat |
| integration+host+80 unit (one process) | 213 | 467 MB | **less** than sum of parts — no super-linear compounding |
| **Full suite, one process** | **447** | **288 MB** | **RSS plateaus flat from 50%→100% of the run** |

The App.py singleton container lengths stayed bounded throughout
(`_sets`=0, `_timers`=0, broadcast handlers single-digit) — per-test isolation
is working. Python object count (`gc.get_objects()`) grows slowly but RSS does
not track it, so those are small, collectable objects, not a leak.

## Root cause of the *original* OOM (historical)

The memory note that flagged the OOM was written when the suite had ~1700
tests and per-test SDK-global teardown was incomplete. Two compounding factors:

1. **Incomplete per-test reset** of the App.py singletons that missions
   populate (sets/timers/event handlers/ship registries). This is what
   `reset_sdk_globals` and the per-module fixtures now handle.
2. **Unscoped collection.** The project had **no pytest configuration at all**,
   so `uv run pytest` collected from the project *root*. Scope was kept correct
   only by pytest's built-in `norecursedirs` default (which happens to skip
   `build/` and dot-dirs). The repo contains a **second full copy of `tests/`**
   under `.claude/worktrees/sdk-ui-shim/`, and pybind11's own numpy/eigen
   tests under `build/_deps/`. A git worktree created **without** a dot prefix
   at the project root would have made pytest collect the suite twice-over in
   one process — multiplying the then-present leak.

## The guard (what changed)

`pyproject.toml` now pins collection scope explicitly:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
norecursedirs = ["*.egg", ".*", "_darcs", "build", "CVS", "dist",
                 "node_modules", "venv", "{arch}", "game", "sdk", "native"]
```

- `testpaths` makes bare `uv run pytest` collect exactly `tests/`,
  rootdir-independent and immune to stray worktrees / vendored test trees.
- `norecursedirs` reinforces this for explicit-path runs like `pytest .`.

Verified zero behavior change: collection is **3188 tests** before and after,
and `pytest .` (which previously would have swept `build/` + `.claude/`) now
also collects exactly 3188.

## Safe way to run the whole suite

```bash
scripts/run_tests.sh            # full suite, one process, 4 GB watchdog ceiling
scripts/run_tests.sh --batched  # each tests/ subdir as its own process
CEILING_MB=8000 scripts/run_tests.sh
```

The watchdog guarantees the host can never be frozen again: if RSS ever crosses
the ceiling the run is SIGKILLed (exit code 99) instead of the machine dying.
