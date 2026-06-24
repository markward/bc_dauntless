#!/usr/bin/env bash
# The test GATE: run BOTH suites (pytest + C++ ctest) and fail loudly on any
# failure that is not in tests/known_failures.txt. Use this before merging —
# scripts/run_tests.sh is pytest-only and cannot see C++ regressions.
#
#   scripts/check_tests.sh                # build C++, run pytest + ctest, diff
#   scripts/check_tests.sh --no-build     # skip the cmake build step
#   scripts/check_tests.sh --pytest-only  # skip ctest
#   scripts/check_tests.sh --ctest-only   # skip pytest
#
# Exit 0 = no new failures; 1 = regression(s); 2 = harness error.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python tools/check_test_baseline.py "$@"
