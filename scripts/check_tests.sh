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

# Some C++ asset tests (BuildVentingDescriptors.TextureFileExistsOnDisk,
# HitVfxTextures.ConstantPathsResolveFromRendererCwd) honour
# DAUNTLESS_GAME_DIR and skip when it is unset, so they never ran in the gate.
# Derive it by asking Python -- the single authority on where the configured
# BC install lives -- never by hardcoding a path. Left unset (and those tests
# skip, as before) on a machine where paths do not resolve.
DAUNTLESS_GAME_DIR="$(uv run python -c 'from engine import paths; print(paths.game_root())' 2>/dev/null)" || DAUNTLESS_GAME_DIR=""
[ -n "$DAUNTLESS_GAME_DIR" ] && export DAUNTLESS_GAME_DIR || true

# Same reasoning for optional mods: a handful of asset-backed C++ tests exist
# only to exercise a mod dropped into mods/ (e.g. CGSovereign), and their
# search paths honour DAUNTLESS_MODS_DIR (native/tests/support/content_root.h)
# rather than a hard-coded <project>/mods. Ask engine.mods, the single
# authority, so ctest and the engine agree on where mods live.
DAUNTLESS_MODS_DIR="$(uv run python -c 'from engine import mods; print(mods.mods_root())' 2>/dev/null)" || DAUNTLESS_MODS_DIR=""
[ -n "$DAUNTLESS_MODS_DIR" ] && export DAUNTLESS_MODS_DIR || true

exec uv run python tools/check_test_baseline.py "$@"
