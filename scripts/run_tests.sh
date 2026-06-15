#!/usr/bin/env bash
# Run the bc_dauntless test suite under an RSS watchdog so a memory regression
# can never re-freeze the host (the suite once OOM'd at >100 GB; it now
# plateaus near ~290 MB — see docs/test-suite-memory.md).
#
# The watchdog SIGKILLs the run if RSS crosses the ceiling, so this is always
# safe to run, including the full suite in one process.
#
# Usage:
#   scripts/run_tests.sh                 # full suite, one process, 4 GB ceiling
#   scripts/run_tests.sh --batched       # each tests/ subdir as its own process
#   CEILING_MB=8000 scripts/run_tests.sh # raise the ceiling
#   scripts/run_tests.sh tests/unit -k foo   # pass-through pytest args (single run)
set -euo pipefail

cd "$(dirname "$0")/.."
CEILING_MB="${CEILING_MB:-4000}"
WATCHDOG="tools/pytest_rss_watchdog.py"

if [[ "${1:-}" == "--batched" ]]; then
    shift
    rc=0
    for dir in tests/*/; do
        [[ -d "$dir" ]] || continue
        # skip dirs with no test files
        if ! find "$dir" -name 'test_*.py' -print -quit | grep -q .; then continue; fi
        echo "===== $dir ====="
        uv run python "$WATCHDOG" "$CEILING_MB" -- uv run pytest "$dir" -q "$@" || rc=$?
    done
    exit "$rc"
fi

# Single process over whatever paths/args were given (default: full suite).
exec uv run python "$WATCHDOG" "$CEILING_MB" -- uv run pytest -q "$@"
