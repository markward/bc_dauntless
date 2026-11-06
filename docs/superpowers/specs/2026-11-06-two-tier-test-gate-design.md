# Two-tier test gate

Status: built on `fix/test-suite-and-gate` (2026-11-06). Not merged.

## Problem

`scripts/check_tests.sh` was the only gate: the whole pytest suite in one
process, then ctest (one process per case), then each gtest binary once
in-process. Measured 2026-11-06 on `ecbeec5a0`: pytest 26 min (17,327 tests)
plus ctest 5.7 min plus the in-process pass 3.6 min, about **36 min**, and
the pytest phase was SIGKILLed by the 4 GB RSS watchdog about 11% in. It
blocked merges four times in one day.

## Shape

| | Merge gate | Full gate |
|---|---|---|
| Command | `scripts/gate_merge.sh` | `scripts/gate_full.sh` (`scripts/check_tests.sh` is an alias) |
| When | every branch merged into `main` | by hand, periodically and before every release |
| Who | whoever merges (a session, at Mark's say-so) | Mark |
| Budget | < 5 min wall-clock on this machine, measured | whole suite, in one process |
| Python | every test **not** in the deep list, one process | every test, one process |
| C++ | each gtest binary once, in-process, minus the deep list | ctest per case + each binary in-process |
| Ledger | `tests/known_failures.txt`: new failures named, skips gated | same |
| Reports | phase times + total | phase times, total, **peak RSS**, merge-catchable vs deep-only failures, tier budget |

Both are one process for pytest. Neither uses xdist: order-only leaks (two
caught by the gate on 2026-11-05) need one process, and the machine is shared
for perf work.

## Selection mechanism: a generated deep-only list, everything else is merge

`tests/gate_tiers/deep_pytest.txt` and `tests/gate_tiers/deep_gtest.txt` list
what runs **only** in the full gate. Everything not listed is in the merge
tier. Alternatives considered:

- **Markers in each file** (`@pytest.mark.deep`). The choice would be spread
  over 1,700 files, nobody re-measures them, and a test that got slow is
  never demoted. Rejected.
- **Directory rules** (merge = `tests/unit`, ...). Every directory mixes fast
  and slow tests: `tests/integration` has 900 tests, most under 50 ms, and the
  slowest unit test takes 34 s. A directory rule either drops whole areas or
  keeps the slow tests. Rejected.
- **Positive manifest** (list what IS in the merge tier). A new test would be
  in no tier until someone remembered it. Rejected: this is the rot the brief
  names.

The negative list makes the rule **default-in**: a new test file is in the
merge tier the moment it exists. That is safe for coverage and costs time
only until the next regeneration. The list is **generated**, never
hand-edited: `tools/gate_tiers.py generate <full-gate artefact dir>` reads the
per-test durations the full gate writes and demotes the slowest tests until
the merge tier's measured cost fits its budget. The merge tier holds 15,516 of 17,331 tests after regenerating from the full gate's
own durations. Selection is at function
level for pytest (all parametrize cases of a slow function move together, and
a file whose every function is demoted is listed as the file), and at case
level for gtest.

What may never be demoted, enforced by `tests/unit/test_gate_tiers.py` (which
is itself in the merge tier):

- the tree-scanning guards: `test_path_indirection.py`,
  `test_install_write_guard.py`, `test_no_install_writes.py`,
  `test_raw_key_reads.py`, every `*drift*` test, everything in `tests/docs/`;
  and `test_gate_tiers.py` itself;
- **every area keeps merge coverage**: each `tests/<dir>` keeps at least one
  merge-tier test file, and each first-level `engine/` package is imported by
  at least one merge-tier test file (static import scan). For C++, each gtest
  binary and each test suite keeps at least one merge-tier case (the generator
  keeps the fastest; `gate_merge` re-checks at run time);
- every list entry still resolves (the file, and the function or the
  `TEST*(Suite, Case)` it names, still exist).

### Budgets

- Generation targets: pytest merge tier <= 150 s of measured test time; gtest
  merge tier <= 25 s. Measured on this machine's Debug build.
- The full gate projects the merge tier's cost from its own measured
  durations, and **fails** past 200 s (pytest) or 40 s (gtest), printing the
  regenerate command. That is the check that the selection has not rotted.
  It lives in the full gate, not the merge gate: a merge gate that failed on
  wall time would block merges whenever the machine was busy, which is the
  friction this design removes.
- The merge gate prints its phase times and total, and warns over 300 s.

Measured (development run, 2026-11-06, this machine, Debug): build 13 s
(nothing to rebuild), pytest 164 s (15,057 tests, peak RSS 579 MB),
in-process gtest 27 s, **205 s total**. The build phase is whatever the
branch left unbuilt. A session that ran its focused tests has already built,
but a merge that touches widely included C++ headers adds its rebuild (a
from-scratch build is about 100 s).

Full gate, measured (development run, same day): pytest 1,148 s (17,301
passed, peak RSS 2,903 MB), ctest 366 s, in-process 219 s, **28.9 min**.

## Memory guard (full gate)

The watchdog ceiling stays at 4,000 MB as the host's safety net. The full
gate also fails when pytest's peak RSS exceeds a stated **budget**
(`PYTEST_RSS_BUDGET_MB`, default in `tools/check_test_baseline.py`, set from
the measured post-fix peak with headroom). A budget breach names the number
and points at `docs/reference/architecture/test-suite-memory.md`.

## Failure attribution (full gate)

Each new failure is printed under one of two headings:

- **merge gate would have caught it**: a pytest node id not in the deep
  list, or a gtest case not in the deep list;
- **deep-only**: everything else (deep pytest tests, and failures that only
  per-case ctest or the in-process pass of a deep case shows).

## IDs and the ledger

Unchanged ids: `pytest:<nodeid>`, `ctest:<name>`, `inproc:<name>`. The merge
gate's in-process C++ failures are `inproc:<Suite.Case>`, as in the full
gate's in-process pass, so one ledger line covers both. In-process skips are
mapped to their ctest name (the binary's `TEST_PREFIX` added) so the ledger's
existing `skip:ctest:` and `optional-mod:ctest:` lines apply unchanged.

## For Mark

1. **The two budgets** (150 s / 25 s to generate, 200 s / 40 s to fail the
   full gate) are my picks from one measured run. Raise them for more merge
   depth, or lower them for a faster merge.
2. **The full gate fails on a tier-budget breach.** The alternative is a loud
   warning. I chose failure because a warning is exactly how a selection
   rots, and the fix is one command plus a commit.
3. **The RSS budget: 3,300 MB** (`PYTEST_RSS_BUDGET_MB`). Measured peak
   2,903 / 2,896 MB, set by a few heavy deep tests' working sets (the gate
   names the top five; the largest is `test_golden_fights::test_k1_gameloop_ai`,
   +658 MB; see test-suite-memory.md). Lower it once those are slimmed. I
   did not touch the 4,000 MB watchdog ceiling.
4. **`UpdateNeverBlocks` tier.** I split it into a deterministic
   never-waits test (~55 ms, merge tier by the rule) and a CPU-bound cost test
   (~1.3 s, deep). See the audit doc.
