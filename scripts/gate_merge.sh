#!/usr/bin/env bash
# MERGE gate: run before every merge into main. Budget: under 5 minutes.
#
# Broad, not deep: pytest minus the generated deep list (tests/gate_tiers/
# deep_pytest.txt), and each gtest binary once in-process minus
# deep_gtest.txt. A new test is in this tier by rule. Diffs failures and
# skips against tests/known_failures.txt like the full gate.
#
#   scripts/gate_merge.sh              # build C++, pytest (merge tier), gtest (merge tier)
#   scripts/gate_merge.sh --no-build
#
# Exit 0 = no new failures; 1 = regression(s); 2 = harness error.
# Spec: docs/superpowers/specs/2026-11-06-two-tier-test-gate-design.md
set -euo pipefail
GATE_TIER=merge
source "$(dirname "$0")/_gate_env.sh"
echo "log: $GATE_ARTEFACT_DIR/gate.log"
uv run python tools/check_test_baseline.py --tier merge "$@" 2>&1 | tee "$GATE_ARTEFACT_DIR/gate.log"
exit "${PIPESTATUS[0]}"
