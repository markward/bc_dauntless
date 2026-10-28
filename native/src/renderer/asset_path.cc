// native/src/renderer/asset_path.cc
#include <renderer/asset_path.h>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <filesystem>
#include <map>
#include <mutex>
#include <string>
#include <vector>

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

// `path` as spelled if it exists, else the existing path whose components
// match it case-insensitively, else `path` unchanged (so a missing asset still
// fails to open, under the name the caller asked for).
//
// BC content spells paths with whatever case it likes ("DBridge.nif" for a
// file named "Dbridge.NIF"), which only a case-sensitive filesystem notices.
// Twin of engine/core/case_paths.py:resolve -- the same exact-first rule and
// the same sorted first-match tie-break. Directory listings are cached for
// the process (BC content does not change under a running game), behind a
// mutex because assets also load from worker threads.
std::string case_resolve(const std::string& path) {
    namespace fs = std::filesystem;
    std::error_code ec;
    if (fs::exists(path, ec)) return path;

    static std::mutex mu;
    static std::map<std::string, std::vector<std::string>> listings;
    auto entries_of = [&](const fs::path& dir) -> const std::vector<std::string>& {
        const std::string key = dir.string();
        auto it = listings.find(key);
        if (it != listings.end()) return it->second;
        std::vector<std::string> names;
        std::error_code iter_ec;
        for (fs::directory_iterator d(dir, iter_ec), end; !iter_ec && d != end;
             d.increment(iter_ec)) {
            names.push_back(d->path().filename().string());
        }
        std::sort(names.begin(), names.end());
        return listings.emplace(key, std::move(names)).first->second;
    };
    auto lower = [](std::string s) {
        for (char& c : s) {
            c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        }
        return s;
    };

    std::lock_guard<std::mutex> lock(mu);
    const fs::path in(path);
    // Empty `cur` keeps a relative input relative; it is listed as ".".
    fs::path cur = in.root_path();
    for (const auto& part : in.relative_path()) {
        const fs::path exact = cur / part;
        if (fs::exists(exact, ec)) {
            cur = exact;
            continue;
        }
        const std::string want = lower(part.string());
        const std::string* match = nullptr;
        for (const auto& name : entries_of(cur.empty() ? fs::path(".") : cur)) {
            if (lower(name) == want) { match = &name; break; }
        }
        if (!match) return path;
        cur /= *match;
    }
    return cur.string();
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
    if (is_absolute_asset_path(path)) return case_resolve(path);

    const auto& overrides = mutable_overrides();
    if (!overrides.empty()) {
        const auto it = overrides.find(fold_key(path));
        if (it != overrides.end()) return it->second;
    }

    const std::string& root = game_root();
    if (starts_with_dir(path, root)) return case_resolve(path);

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
    return case_resolve(root + "/" + rel);
}

}  // namespace renderer
