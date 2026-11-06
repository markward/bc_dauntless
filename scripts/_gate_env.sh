# Sourced by scripts/gate_merge.sh and scripts/gate_full.sh: the environment
# both tiers share. Spec: docs/superpowers/specs/2026-11-06-two-tier-test-gate-design.md
cd "$(dirname "${BASH_SOURCE[0]}")/.."

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

# Every run keeps its log and artefacts (per-test durations, each gtest
# binary's output) so a failure is never re-run just to be read.
if [ -z "${GATE_ARTEFACT_DIR:-}" ]; then
    GATE_ARTEFACT_DIR="${TMPDIR:-/tmp}/dauntless-gate/${GATE_TIER}-$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p "$GATE_ARTEFACT_DIR"
export GATE_ARTEFACT_DIR
