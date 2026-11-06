#!/usr/bin/env bash
# Former name of the FULL gate, kept so old notes and habits still work.
# There are two tiers now (docs/superpowers/specs/2026-11-06-two-tier-test-gate-design.md):
#   scripts/gate_merge.sh   before every merge into main (< 5 min)
#   scripts/gate_full.sh    by hand, periodically and before every release
echo "check_tests.sh is the FULL gate (scripts/gate_full.sh); merges use scripts/gate_merge.sh" >&2
exec "$(dirname "$0")/gate_full.sh" "$@"
