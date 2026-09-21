// native/src/renderer/asset_path.cc
#include <renderer/asset_path.h>

#include <cctype>
#include <cstdio>
#include <map>
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

// Project-authored renderer assets (native/assets/). Default is the
// cwd-relative checkout layout; host_loop pushes the absolute path at boot.
std::string& mutable_project_asset_root() {
    static std::string root = "native/assets";
    return root;
}

// Mod-supplied asset overrides, keyed by the case-folded relative path
// engine/mods.py builds. Empty by default so a modless run never consults it.
std::map<std::string, std::string>& mutable_overrides() {
    static std::map<std::string, std::string> overrides;
    return overrides;
}

// Mirrors engine/mods.py:fold() -- the same three operations in the same
// order: backslashes to forward slashes, strip leading AND trailing '/',
// then lowercase. Python builds the map's keys and C++ looks them up, so any
// divergence here means the map silently never hits. Keep both sides in sync
// if either changes.
//
// ONE EXCEPTION, and it is a real one: std::tolower lowercases BYTES, while
// Python's str.lower() is Unicode-aware. A path component containing a
// non-ASCII uppercase letter therefore folds differently on the two sides,
// and that key is unreachable from C++ -- no error, the asset just silently
// resolves to stock. BC's own content is ASCII, but a mod folder named by a
// non-English author need not be. Fixing it means a Unicode-aware fold here
// (or restricting the map to ASCII-foldable keys); until then this comment
// is the record.
std::string fold_key(const std::string& path) {
    std::string out;
    out.reserve(path.size());
    for (char c : path) {
        out.push_back(c == kBackslash ? '/' : c);
    }

    const size_t begin = out.find_first_not_of('/');
    if (begin == std::string::npos) {
        out.clear();
    } else {
        const size_t end = out.find_last_not_of('/');
        out = out.substr(begin, end - begin + 1);
    }

    for (char& c : out) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return out;
}

bool starts_with_dir(const std::string& path, const std::string& prefix) {
    if (prefix.empty() || path.size() <= prefix.size()) return false;
    if (path.compare(0, prefix.size(), prefix) != 0) return false;
    const char sep = path[prefix.size()];
    return sep == '/' || sep == kBackslash;
}

}  // namespace

void set_asset_overrides(const std::map<std::string, std::string>& overrides) {
    mutable_overrides() = overrides;
}

void clear_asset_overrides() { mutable_overrides().clear(); }

void set_game_root(const std::string& root) {
    // An empty root would silently produce "/data/..." -- an absolute path
    // into the filesystem root -- so fall back rather than accept it.
    mutable_game_root() = root.empty() ? "game" : root;
}

const std::string& game_root() { return mutable_game_root(); }

void set_project_asset_root(const std::string& root) {
    mutable_project_asset_root() = root.empty() ? "native/assets" : root;
}

const std::string& project_asset_root() { return mutable_project_asset_root(); }

std::string project_asset_path(const std::string& rel) {
    if (rel.empty()) return rel;
    return project_asset_root() + "/" + rel;
}

std::string resolve_asset_path(const std::string& path) {
    if (path.empty()) return path;
    if (is_absolute_asset_path(path)) return path;

    const auto& overrides = mutable_overrides();
    if (!overrides.empty()) {
        const auto it = overrides.find(fold_key(path));
        if (it != overrides.end()) return it->second;
    }

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
