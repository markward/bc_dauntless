# Stub-Telemetry Accumulation + Heatmap — Design

**Date:** 2026-07-10
**Status:** Approved (brainstorm), pending implementation plan
**Depends on:** Step 0 stub-observability (merged to main, commit 028c2b56)
**Part of:** the stub-hardening effort (see `project_stub_hardening_ratchet` memory /
`docs/superpowers/plans/2026-07-10-stub-observability.md`)

## Goal

Persist the Step 0 per-run stub telemetry across many runs into a gitignored
sidecar, and generate a committed, versioned **heatmap** that ranks unimplemented
stubs by how often the running game hits them **and** by how saturated their
coverage is. This is "Piece 1" of Track B (the ledger effort) and is the
**prerequisite** for a safe ledger baseline: you cannot freeze `stubs_known.txt`
from a single run, because a mission that never exercises a subsystem never
records its stubs, and freezing an under-covered baseline would make a future
`Unimplemented` raise (crash) the first time a different mission hit an
unrecorded stub. The heatmap's saturation signal tells us when coverage has
plateaued enough that a baseline (Piece 2) is safe.

## Context

Step 0 shipped a dependency-free collector, `engine/core/stub_telemetry.py`,
that — when enabled via `DAUNTLESS_STUB_TELEMETRY=1` — records `(owner, attr)`
access and `__bool__` call-sites on the core `_Stub`, then prints a ranked
report to stderr at exit. It is OFF by default and byte-identical in production.
This design **extends** that collector with persistence and adds an offline
merge/report generator. It does not change the observe-only, off-by-default
nature of the system: nothing here makes any failure loud (that is Piece 2).

## Global Constraints

- **OFF by default; production byte-identical.** Persistence happens only when
  `DAUNTLESS_STUB_TELEMETRY=1`. With the env var unset, no file is touched and
  behavior is identical to today.
- **Never crashes the game.** Every game-side write is wrapped so a persistence
  failure (bad path, full disk, permission error) is swallowed, never propagated.
- **Stdlib only.** Game side adds `json`; the `tools/` script uses
  `json`/`argparse`/`collections`. No new third-party dependencies.
- **Deterministic committed output.** The generated heatmap contains no
  `now()`-derived value; every value derives from the sidecar data, so
  regenerating on the same sidecar yields a byte-identical file (clean git diffs).
- **Append-only accumulation.** The sidecar is only ever appended to by the game
  and only ever read by the tools script. No read-modify-write.

## Architecture & Components

Four pieces, each with one responsibility:

1. **Game-side persistence** — extends `engine/core/stub_telemetry.py`. When
   telemetry is enabled, the existing `atexit` handler, after printing the stderr
   report, appends **one JSON line** for the run to the sidecar. Path from env
   `DAUNTLESS_STUB_TELEMETRY_FILE`; if set it is used as-is (recommend absolute).
   The default is `stub_hits.jsonl` **resolved to an absolute path at module
   import time** (`os.path.abspath` when `stub_telemetry` is first imported,
   which happens early via `engine/core/ids.py` — before GLFW init). This is
   deliberate: the `atexit` write runs at shutdown, and GLFW's documented
   macOS chdir-hijack can move the CWD after init, so a path resolved lazily at
   exit could land in the wrong directory. Capturing the absolute default at
   import pins it to the launch directory. Wrapped so it can never crash the run.
   This is the only change to the running game and stays fully behind the Step 0
   enable gate.
2. **Accumulating sidecar** — `stub_hits.jsonl` at repo root, **gitignored**
   (one new `.gitignore` line). Append-only; one line per run; written by the
   game, read only by the tools script.
3. **Merge + heatmap generator** — new `tools/stub_heatmap.py` (following the
   `tools/analyze_*.py` precedent). Reads the sidecar, computes merged counts +
   per-pair coverage + the saturation curve, and writes the heatmap doc. Built as
   importable pure functions with a thin `__main__` so the math is unit-testable
   without a game run. Invoked deliberately: `uv run python tools/stub_heatmap.py`.
4. **Committed heatmap** — `docs/stub_heatmap.md`, a versioned snapshot
   regenerated on demand by piece 3. **Not** gitignored — it is the shareable
   artifact the next session and the future Piece 2 baseline read; its `git log`
   is the coarse burn-down.

Split of responsibility: the game **accumulates** automatically (cheap,
append-only, per-run); a human **generates** the heatmap deliberately at
milestones. The Piece 2 gate file (`stubs_known.txt`) never appears here — this
is all observation.

## Data Flow & Formats

### Sidecar line (one JSON object per run)
```json
{"t": 1720641696.4,
 "attr_hits": {"TorpedoTube\tGetMaxCharge": 602976, "TorpedoTube\tUpdateCharge": 421956},
 "bool_sites": {"engine/bridge_idle_gestures.py:29": 20630}}
```
- The `(owner, attr)` pair is encoded as a **tab-separated** string key
  (`"owner\tattr"`). Class names contain no tab; `attr` may contain dots (chained
  breadcrumbs like `GetWarpCore.GetMaxCharge`), so a dot-join would be ambiguous —
  a tab is not. The merge splits on the first tab.
- `t` is the run's wall-clock (`time.time()`), acceptable in the game process.
  The merge tolerates its absence (older lines, or a run where the clock read
  failed).
- Line position is run identity and order; no run-id field is needed.

### Merge (`tools/stub_heatmap.py`, tolerant of malformed lines)
- Read all lines; skip any that fail to parse as a JSON object with the expected
  shape, and count the skips.
- `M` = number of valid run records.
- Per `(owner, attr)`: `total_hits` = sum across runs; `runs_seen` = number of
  runs it appeared in; `coverage = runs_seen / M`. Identical treatment for
  `bool_sites` keyed by `"file:line"`.

### Saturation curve (the "ready for Piece 2?" instrument)
Walk runs in append order, maintaining a growing set of seen `(owner, attr)`
pairs. For each run, record how many **new** pairs it introduced (pairs not in
any earlier run). If the last few runs introduced ≈0 new pairs, coverage has
plateaued and a baseline would be reasonably safe; if the latest run still
introduces many, keep accumulating. Reported as a short new-pairs-per-run series
plus a plain-English verdict.

### Committed heatmap (`docs/stub_heatmap.md`)
- **Header:** accumulated from `M` runs; date range derived from the sidecar's
  own min/max `t` (never `now()`); count of distinct pairs; count of skipped
  malformed lines.
- **Saturation summary:** new-pairs-per-run series + plateau verdict.
- **Roadmap table:** rank · `owner.attr` · total hits · seen in `N/M` runs
  (coverage %). Sorted by total hits descending, then key ascending for ties.
- **Bool-sites table:** `file:line` · total hits · seen in `N/M` runs — the
  truthiness-risk roadmap.
- A one-line note that this is an observation artifact; the ledger (Piece 2) is
  separate.
- Sorting is fully deterministic so the committed file is stable across
  regenerations on the same data.

## Error Handling

- Game-side append: `try/except Exception: pass` around the file write; a failure
  never reaches the game loop.
- Merge: malformed/truncated lines skipped and counted (a hard-killed run's
  partial final line cannot poison the history).
- Missing sidecar: the tools script reports "no runs accumulated yet" and exits
  cleanly rather than erroring.

## Testing

- **Game-side persist (unit):** enabled + temp path → exactly one valid JSON line
  with expected keys; disabled → nothing written; unwritable path → swallowed,
  never raises. Mirrors Step 0 test patterns.
- **Merge math (unit, pure fns):** synthetic JSONL → `total_hits` sums,
  `runs_seen` counts, `coverage` fractions correct across several runs.
- **Saturation (unit):** runs with known new-pair introductions → assert the
  new-pairs-per-run series and the plateau verdict.
- **Malformed tolerance (unit):** a garbage line is skipped and counted while
  valid lines still merge.
- **Deterministic rendering (unit):** same sidecar → byte-identical heatmap
  string; tie-sorting correct; date range derived from data, never `now()`.
- No game run needed for any test. The full `check_tests.sh` gate stays green.

## Out of Scope (deferred)

- In-game dev-menu / keybinding toggle for enabling telemetry (env var suffices).
- Any auto-regeneration of the heatmap or CI wiring (manual, deliberate script).
- Sidecar auto-pruning (delete `stub_hits.jsonl` to reset a coverage campaign).
- The ledger itself, the `Unimplemented`/`Inert` type split, and the gate — all
  Piece 2, a separate spec that consumes this heatmap's saturated data.
