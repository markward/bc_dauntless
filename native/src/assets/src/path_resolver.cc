#include <assets/path_resolver.h>

#include <algorithm>
#include <cctype>

namespace fs = std::filesystem;

namespace assets {

TextureNotFound::TextureNotFound(std::string basename, fs::path searched_dir)
    : std::runtime_error(
          "texture not found: " + basename + " in " + searched_dir.string())
    , basename_(std::move(basename))
    , searched_dir_(std::move(searched_dir)) {}

std::string PathResolver::to_lower(std::string_view s) {
    std::string out(s);
    std::transform(out.begin(), out.end(), out.begin(),
        [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return out;
}

bool PathResolver::has_extension(std::string_view basename) {
    auto last_slash = basename.find_last_of("/\\");
    auto last_dot   = basename.find_last_of('.');
    if (last_dot == std::string_view::npos) return false;
    if (last_slash != std::string_view::npos && last_dot < last_slash) return false;
    return true;
}

PathResolver::LowerToActual&
PathResolver::cache_for(const fs::path& dir, bool force_rebuild) {
    auto key = fs::weakly_canonical(dir).string();
    if (force_rebuild) cache_.erase(key);
    auto it = cache_.find(key);
    if (it != cache_.end()) return it->second;

    LowerToActual map;
    if (fs::is_directory(dir)) {
        for (auto& entry : fs::directory_iterator(dir)) {
            if (!entry.is_regular_file()) continue;
            auto fname = entry.path().filename().string();
            map[to_lower(fname)] = fname;
        }
    }
    return cache_.emplace(key, std::move(map)).first->second;
}

fs::path PathResolver::resolve(std::string basename, const fs::path& search_dir) {
    if (!has_extension(basename)) basename += ".tga";

    // BC bridge NIFs (e.g. DBridge.NIF) embed mixed conventions — some
    // texture references are bare ("Map 20.tga") and others carry a
    // leading subpath ("DBridge/floor lm.tga") even though the actual
    // files live flat in the configured search_dir. Strip any leading
    // directory component before lookup. Bare names pass through
    // unchanged; ship NIFs (which always use bare names) are unaffected.
    fs::path basename_path(basename);
    std::string filename = basename_path.has_parent_path()
        ? basename_path.filename().string()
        : basename;

    auto& dir_map = cache_for(search_dir, /*force_rebuild=*/false);
    auto lower = to_lower(filename);

    if (auto it = dir_map.find(lower); it != dir_map.end()) {
        return search_dir / it->second;
    }

    // Miss — rebuild map once and retry. Handles new files dropped at runtime.
    auto& fresh = cache_for(search_dir, /*force_rebuild=*/true);
    if (auto it = fresh.find(lower); it != fresh.end()) {
        return search_dir / it->second;
    }

    throw TextureNotFound(std::move(basename), search_dir);
}

}  // namespace assets
