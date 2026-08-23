// native/src/renderer/include/renderer/asset_path.h
#pragma once
#include <string>

namespace renderer {

/// Backslash by code point: a path separator is data here, and spelling it as
/// a char literal makes this header fragile to every layer that rewrites
/// escapes on the way in.
inline constexpr char kBackslash = 0x5C;

/// True for a path that already names a location on its own: a POSIX root, a
/// Windows root or UNC share, or a drive-qualified path ("C:/x", "C:\x").
///
/// Testing only for a leading '/' silently treated every Windows absolute path
/// as relative, so "C:\game\data\x.NIF" resolved to
/// "game/C:\game\data\x.NIF" and every load through it failed to find
/// the file -- surfacing as a zero-clip animation or a missing texture rather
/// than an error naming the path.
inline bool is_absolute_asset_path(const std::string& path) {
    if (path.empty()) return false;
    if (path[0] == '/' || path[0] == kBackslash) return true;
    return path.size() >= 3 && path[1] == ':'
           && (path[2] == '/' || path[2] == kBackslash);
}

/// Resolve an SDK/BC asset path (relative to the game install root, e.g.
/// "data/Textures/Effects/ExplosionB.tga") to a path openable from the
/// renderer's working directory (the repo root), where BC assets live under
/// "game/". Idempotent: already-"game/"-prefixed, absolute, and empty paths
/// are returned unchanged. Mirrors hit_vfx_pass.cc's hardcoded "game/" prefix.
inline std::string resolve_asset_path(const std::string& path) {
    if (path.empty()) return path;
    if (is_absolute_asset_path(path)) return path;
    if (path.rfind("game", 0) == 0 && path.size() > 4
        && (path[4] == '/' || path[4] == kBackslash)) {
        return path;                                 // already prefixed
    }
    return "game/" + path;
}

}  // namespace renderer
