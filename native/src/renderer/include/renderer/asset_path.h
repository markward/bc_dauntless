// native/src/renderer/include/renderer/asset_path.h
#pragma once
#include <string>

namespace renderer {

/// Resolve an SDK/BC asset path (relative to the game install root, e.g.
/// "data/Textures/Effects/ExplosionB.tga") to a path openable from the
/// renderer's working directory (the repo root), where BC assets live under
/// "game/". Idempotent: already-"game/"-prefixed, absolute, and empty paths
/// are returned unchanged. Mirrors hit_vfx_pass.cc's hardcoded "game/" prefix.
inline std::string resolve_asset_path(const std::string& path) {
    if (path.empty()) return path;
    if (path[0] == '/') return path;                  // absolute — leave as-is
    if (path.rfind("game/", 0) == 0) return path;    // already prefixed
    return "game/" + path;
}

}  // namespace renderer
