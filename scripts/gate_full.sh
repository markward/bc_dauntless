#!/usr/bin/env bash
# FULL gate: Mark runs it by hand, periodically and before every release.
#
# Everything: the whole pytest suite in ONE process (order-only leaks need
# one process), ctest one process per case, then each gtest binary once
# in-process from the project root. Also fails past the pytest peak-RSS
# budget and when the merge tier's projected cost outgrows its budget, and
# splits new failures into "the merge gate would also have caught it" and
# "deep-only". Its artefacts regenerate the tiers:
#   uv run python tools/gate_tiers.py generate <artefact dir>
#
#   scripts/gate_full.sh                # build C++, run pytest + ctest + in-process, diff
#   scripts/gate_full.sh --no-build     # skip the cmake build step
#   scripts/gate_full.sh --pytest-only  # skip ctest and the in-process pass
#   scripts/gate_full.sh --ctest-only   # skip pytest
#   scripts/gate_full.sh --no-inproc    # skip the one-process-per-binary C++ pass
#
# Exit 0 = no new failures; 1 = regression(s) or a budget breach; 2 = harness error.
# Spec: docs/superpowers/specs/2026-11-06-two-tier-test-gate-design.md
set -euo pipefail
GATE_TIER=full
source "$(dirname "$0")/_gate_env.sh"
echo "log: $GATE_ARTEFACT_DIR/gate.log"
uv run python tools/check_test_baseline.py --tier full "$@" 2>&1 | tee "$GATE_ARTEFACT_DIR/gate.log"
exit "${PIPESTATUS[0]}"
