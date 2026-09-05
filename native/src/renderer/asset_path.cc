// native/src/renderer/asset_path.cc
#include <renderer/asset_path.h>

#include <cstdio>
#include <string>

namespace renderer {
namespace {

// Default "game": cwd-relative, matching the in-project layout the host
// chdir's into. Not a std::string constant at namespace scope in the header,
// because the whole point is that this is mutable at runtime.
std::string& mutable_game_root() {
    static std::string root = "game";
    return root;
}

bool starts_with_dir(const std::string& path, const std::string& prefix) {
    if (prefix.empty() || path.size() <= prefix.size()) return false;
    if (path.compare(0, prefix.size(), prefix) != 0) return false;
    const char sep = path[prefix.size()];
    return sep == '/' || sep == kBackslash;
}

}  // namespace

void set_game_root(const std::string& root) {
    // An empty root would silently produce "/data/..." -- an absolute path
    // into the filesystem root -- so fall back rather than accept it.
    mutable_game_root() = root.empty() ? "game" : root;
}

const std::string& game_root() { return mutable_game_root(); }

std::string resolve_asset_path(const std::string& path) {
    if (path.empty()) return path;
    if (is_absolute_asset_path(path)) return path;

    const std::string& root = game_root();
    if (starts_with_dir(path, root)) return path;

    std::string rel = path;
    if (root != "game" && starts_with_dir(path, "game")) {
        static bool warned = false;
        if (!warned) {
            warned = true;
            std::fprintf(stderr,
                         "[asset_path] a literal \"game/\" prefix reached "
                         "resolve_asset_path while the root is \"%s\" (first: "
                         "\"%s\"). That is an unmigrated load site -- the "
                         "prefix is being stripped so the asset still loads.\n",
                         root.c_str(), path.c_str());
        }
        rel = path.substr(5);
    }
    return root + "/" + rel;
}

}  // namespace renderer
