// native/tests/support/content_root.h
//
// The ONE place an asset-backed C++ test finds BC content. BC content is
// configurable (engine/paths.py) and need not live under <project>/game, so a
// test that hard-codes the in-project path silently SKIPs on any machine whose
// install lives elsewhere -- and a gtest SKIP is invisible to the gate.
//
// Honours DAUNTLESS_GAME_DIR, the env var engine/paths.py reads and
// scripts/check_tests.sh exports from paths.game_root(). Empty counts as unset,
// matching the engine. Unset falls back to the legacy <project>/game.
//
// Header-only and renderer-free so every test target (nif, assets, voxel,
// renderer) can use it; the renderer's process-global root lives in
// renderer_game_root.h.
#pragma once

#include <cstdlib>
#include <filesystem>

#ifndef OPEN_STBC_PROJECT_ROOT
#error "OPEN_STBC_PROJECT_ROOT must be defined by CMake"
#endif

namespace test_support {

inline constexpr const char* kGameDirEnv = "DAUNTLESS_GAME_DIR";

// Pure resolution rule, separated from getenv so it is testable.
inline std::filesystem::path resolve_game_root(
        const char* env, const std::filesystem::path& project_root) {
    if (env != nullptr && *env != '\0') return std::filesystem::path(env);
    return project_root / "game";
}

inline std::filesystem::path project_root() {
    return std::filesystem::path(OPEN_STBC_PROJECT_ROOT);
}

// Absolute BC content root for this run.
inline std::filesystem::path game_root() {
    return resolve_game_root(std::getenv(kGameDirEnv), project_root());
}

// Mirrors engine.mods.mods_root(): the same env rule as game_root() above,
// falling back to <project>/mods rather than <project>/game. A test whose
// asset lives inside an OPTIONAL mod (present only where that mod is
// installed) resolves its search path through this, never a hard-coded
// "mods/<name>/..." under the project root -- the mod need not live inside
// the checkout, same reasoning as game_root().
inline constexpr const char* kModsDirEnv = "DAUNTLESS_MODS_DIR";

inline std::filesystem::path resolve_mods_root(
        const char* env, const std::filesystem::path& project_root) {
    if (env != nullptr && *env != '\0') return std::filesystem::path(env);
    return project_root / "mods";
}

inline std::filesystem::path mods_root() {
    return resolve_mods_root(std::getenv(kModsDirEnv), project_root());
}

}  // namespace test_support
