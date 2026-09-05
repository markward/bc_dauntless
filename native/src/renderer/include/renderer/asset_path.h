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
    if (path[0] == '/') return true;
#ifdef _WIN32
    // Windows-only, deliberately: on POSIX a backslash is an ordinary filename
    // character and "C:" is a legal relative name, so applying these rules
    // everywhere would reclassify legitimate relative paths as absolute.
    if (path[0] == kBackslash) return true;               // root or UNC share
    return path.size() >= 3 && path[1] == ':'             // drive-qualified
           && (path[2] == '/' || path[2] == kBackslash);
#else
    return false;
#endif
}

/// The BC install root every relative asset path is resolved against.
/// Defaults to the literal "game", which is cwd-relative and preserves the
/// in-project layout; host_loop sets an absolute path at boot once
/// engine.paths has resolved one. Settable more than once: the first-run
/// picker changes it after the window is already up.
void set_game_root(const std::string& root);
const std::string& game_root();

/// Resolve an SDK/BC asset path (relative to the game install root, e.g.
/// "data/Textures/Effects/ExplosionB.tga") to an openable path.
/// Idempotent: already-rooted, absolute, and empty paths are returned
/// unchanged.
///
/// A path that still carries a literal "game/" prefix while the root is
/// something else is a MISSED MIGRATION: the prefix is stripped so the asset
/// still loads, and the fact is logged once. Without that, the symptom would
/// be an untextured pass and no error at all.
std::string resolve_asset_path(const std::string& path);

}  // namespace renderer
