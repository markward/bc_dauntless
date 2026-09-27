// native/tests/support/renderer_game_root.h
//
// Scoped control of renderer::game_root() for tests that resolve assets the
// way the renderer does at runtime (resolve_asset_path). The root is
// process-global and ctest runs a binary's cases in one process, so every
// mutation must be undone on scope exit.
#pragma once

#include <cstdlib>
#include <string>

#include <renderer/asset_path.h>

#include "support/content_root.h"

namespace test_support {

struct RendererGameRootGuard {
    std::string saved = renderer::game_root();
    ~RendererGameRootGuard() { renderer::set_game_root(saved); }

    // Point the renderer at `env` when it names a root; otherwise leave the
    // renderer's default RELATIVE "game" alone, so tests that emulate the
    // runtime CWD still exercise resolve_asset_path's relative branch.
    void apply_env(const char* env) {
        if (env != nullptr && *env != '\0') renderer::set_game_root(env);
    }

    // apply_env() with the configured DAUNTLESS_GAME_DIR.
    void apply_configured() { apply_env(std::getenv(kGameDirEnv)); }
};

}  // namespace test_support
